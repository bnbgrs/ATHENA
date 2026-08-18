from __future__ import annotations

from pathlib import Path

import pytest

from athena.config.settings import AthenaSettings
from athena.core.application import AthenaApplication
from athena.security.models import Argon2idParameters

_TEST_KDF = Argon2idParameters(
    iterations=1,
    lanes=1,
    memory_cost_kib=8 * 1024,
    length=32,
)


def _app(
    local_root: Path,
) -> AthenaApplication:
    app = AthenaApplication(
        AthenaSettings(
            local_root=local_root,
        )
    )

    app.start()

    return app


def _scope(
    app: AthenaApplication,
    *,
    password: bytes,
):
    app.protected_content.initialize_password(
        password,
        parameters=_TEST_KDF,
    )

    scope = (
        app.protected_content.create_scope(
            password,
            neutral_label=(
                "transactional-payload-test"
            ),
        )
    )

    app.protected_content.unlock_scope(
        scope.protection_scope_id,
        password,
    )

    return scope


def test_prepare_payload_does_not_persist_until_caller_transaction_inserts(
    tmp_path: Path,
) -> None:
    app = _app(
        tmp_path
        / "runtime"
    )

    plaintext = (
        b"ATHENA_TRANSACTIONAL_"
        b"PAYLOAD_CANARY_5F7D"
    )

    try:
        scope = _scope(
            app,
            password=(
                b"transactional-payload-password"
            ),
        )

        with (
            app.database.write_transaction()
            as connection
        ):
            record = (
                app.protected_content
                .prepare_payload(
                    scope.protection_scope_id,
                    plaintext,
                )
            )

            before = connection.execute(
                """
                SELECT COUNT(*)
                FROM protected_payloads
                WHERE protected_payload_id = ?
                """,
                (
                    record
                    .protected_payload_id
                    .bytes,
                ),
            ).fetchone()

            assert before is not None
            assert int(
                before[0]
            ) == 0

            app.protection_repository.insert_payload_in_transaction(
                connection,
                record,
            )

            inside = connection.execute(
                """
                SELECT COUNT(*)
                FROM protected_payloads
                WHERE protected_payload_id = ?
                """,
                (
                    record
                    .protected_payload_id
                    .bytes,
                ),
            ).fetchone()

            assert inside is not None
            assert int(
                inside[0]
            ) == 1

        assert (
            app.protected_content
            .load_payload(
                record
                .protected_payload_id
            )
            == plaintext
        )

    finally:
        app.stop()


def test_transactional_payload_insert_rolls_back_with_caller_transaction(
    tmp_path: Path,
) -> None:
    app = _app(
        tmp_path
        / "runtime"
    )

    plaintext = (
        b"ATHENA_TRANSACTIONAL_"
        b"ROLLBACK_CANARY_C419"
    )

    class SyntheticRollback(
        RuntimeError
    ):
        pass

    record_id = None

    try:
        scope = _scope(
            app,
            password=(
                b"transactional-rollback-password"
            ),
        )

        with pytest.raises(
            SyntheticRollback
        ):
            with (
                app.database
                .write_transaction()
                as connection
            ):
                record = (
                    app.protected_content
                    .prepare_payload(
                        scope.protection_scope_id,
                        plaintext,
                    )
                )

                record_id = (
                    record
                    .protected_payload_id
                )

                app.protection_repository.insert_payload_in_transaction(
                    connection,
                    record,
                )

                visible = (
                    connection.execute(
                        """
                        SELECT COUNT(*)
                        FROM protected_payloads
                        WHERE protected_payload_id = ?
                        """,
                        (
                            record
                            .protected_payload_id
                            .bytes,
                        ),
                    ).fetchone()
                )

                assert visible is not None
                assert int(
                    visible[0]
                ) == 1

                raise SyntheticRollback(
                    "rollback transactional "
                    "protected payload"
                )

        assert record_id is not None

        after = (
            app.database.connection
            .execute(
                """
                SELECT COUNT(*)
                FROM protected_payloads
                WHERE protected_payload_id = ?
                """,
                (
                    record_id.bytes,
                ),
            )
            .fetchone()
        )

        assert after is not None
        assert int(
            after[0]
        ) == 0

    finally:
        app.stop()


def test_transactional_payload_insert_requires_active_transaction(
    tmp_path: Path,
) -> None:
    app = _app(
        tmp_path
        / "runtime"
    )

    try:
        scope = _scope(
            app,
            password=(
                b"transaction-required-password"
            ),
        )

        record = (
            app.protected_content
            .prepare_payload(
                scope.protection_scope_id,
                b"ATHENA_ACTIVE_TRANSACTION_CANARY_5B22",
            )
        )

        with pytest.raises(
            RuntimeError,
            match=(
                "requires an active transaction"
            ),
        ):
            app.protection_repository.insert_payload_in_transaction(
                app.database.connection,
                record,
            )

    finally:
        app.stop()


def test_existing_store_payload_contract_still_round_trips(
    tmp_path: Path,
) -> None:
    app = _app(
        tmp_path
        / "runtime"
    )

    plaintext = (
        b"ATHENA_STORE_PAYLOAD_"
        b"COMPATIBILITY_6E08"
    )

    try:
        scope = _scope(
            app,
            password=(
                b"store-payload-compatibility-password"
            ),
        )

        record = (
            app.protected_content
            .store_payload(
                scope.protection_scope_id,
                plaintext,
            )
        )

        assert (
            app.protected_content
            .load_payload(
                record
                .protected_payload_id
            )
            == plaintext
        )

    finally:
        app.stop()
