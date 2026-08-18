from __future__ import annotations

import sqlite3
import uuid
from pathlib import Path

import pytest

from athena.config.settings import AthenaSettings
from athena.core.application import AthenaApplication
from athena.security.models import Argon2idParameters
from athena.source.protected_semantic import (
    SourceProtectedSemanticIntegrityError,
    SourceProtectedSemanticRepository,
    decode_representation_semantics,
    representation_neutral_content_hash,
)

_TEST_KDF = Argon2idParameters(
    iterations=1,
    lanes=1,
    memory_cost_kib=8 * 1024,
    length=32,
)


def _app(
    root: Path,
) -> AthenaApplication:
    app = AthenaApplication(
        AthenaSettings(
            local_root=root,
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
        app.protected_content
        .create_scope(
            password,
            neutral_label=(
                "representation-semantic-test"
            ),
        )
    )

    app.protected_content.unlock_scope(
        scope.protection_scope_id,
        password,
    )

    return scope


def _representation(
    app: AthenaApplication,
    tmp_path: Path,
    *,
    name: str = "semantic-source.txt",
):
    path = (
        tmp_path
        / name
    )

    path.write_text(
        (
            "ATHENA_REPRESENTATION_"
            "SEMANTIC_CANARY_91B5\n"
            "Sensitive retained source text.\n"
        ),
        encoding="utf-8",
        newline="",
    )

    source = (
        app.sources
        .capture_file(
            path
        )
        .source
    )

    representation = (
        app.source_text
        .build(
            source.source_id
        )
        .result
        .representation
    )

    return (
        source,
        representation,
    )


def _writer(
    app: AthenaApplication,
    protection_scope_id,
    *,
    calls: list[bytes] | None = None,
):
    def write(
        connection: sqlite3.Connection,
        plaintext: bytes,
    ) -> uuid.UUID:
        if calls is not None:
            calls.append(
                plaintext
            )

        record = (
            app.protected_content
            .prepare_payload(
                protection_scope_id,
                plaintext,
            )
        )

        (
            app.protection_repository
            .insert_payload_in_transaction(
                connection,
                record,
            )
        )

        return (
            record
            .protected_payload_id
        )

    return write


def test_representation_semantics_are_encrypted_and_public_fields_neutralized_atomically(
    tmp_path: Path,
) -> None:
    app = _app(
        tmp_path
        / "runtime"
    )

    try:
        source, representation = (
            _representation(
                app,
                tmp_path,
            )
        )

        original_hash = (
            representation
            .content_hash
        )
        original_options = (
            representation
            .options_json
        )

        scope = _scope(
            app,
            password=(
                b"representation-semantic-password"
            ),
        )

        repository = (
            SourceProtectedSemanticRepository(
                app.database
            )
        )

        with (
            app.database
            .write_transaction()
            as connection
        ):
            mapping = (
                repository
                .protect_representation_semantics(
                    connection,
                    source_id=(
                        source.source_id
                    ),
                    representation_id=(
                        representation
                        .representation_id
                    ),
                    protection_scope_id=(
                        scope.protection_scope_id
                    ),
                    payload_writer=_writer(
                        app,
                        scope.protection_scope_id,
                    ),
                )
            )

        row = (
            app.database
            .connection
            .execute(
                """
                SELECT
                    content_hash,
                    options_json
                FROM source_representations
                WHERE representation_id = ?
                """,
                (
                    representation
                    .representation_id
                    .bytes,
                ),
            )
            .fetchone()
        )

        assert row is not None

        assert bytes(
            row[
                "content_hash"
            ]
        ) == (
            representation_neutral_content_hash(
                representation
                .representation_id
            )
        )

        assert str(
            row[
                "options_json"
            ]
        ) == "{}"

        assert bytes(
            row[
                "content_hash"
            ]
        ) != original_hash

        plaintext = (
            app.protected_content
            .load_payload(
                mapping
                .protected_payload_id
            )
        )

        protected = (
            decode_representation_semantics(
                plaintext
            )
        )

        assert (
            protected
            .representation_id
            == representation
            .representation_id
        )

        assert (
            protected
            .content_hash
            == original_hash
        )

        assert (
            protected
            .options_json
            == original_options
        )

        stored_mapping = (
            repository
            .get_representation_mapping(
                source_id=(
                    source.source_id
                ),
                representation_id=(
                    representation
                    .representation_id
                ),
            )
        )

        assert stored_mapping == mapping

    finally:
        app.stop()


def test_representation_semantic_cutover_is_idempotent_without_new_ciphertext(
    tmp_path: Path,
) -> None:
    app = _app(
        tmp_path
        / "runtime"
    )

    try:
        source, representation = (
            _representation(
                app,
                tmp_path,
            )
        )

        scope = _scope(
            app,
            password=(
                b"idempotent-semantic-password"
            ),
        )

        repository = (
            SourceProtectedSemanticRepository(
                app.database
            )
        )

        calls: list[
            bytes
        ] = []

        writer = _writer(
            app,
            scope.protection_scope_id,
            calls=calls,
        )

        with (
            app.database
            .write_transaction()
            as connection
        ):
            first = (
                repository
                .protect_representation_semantics(
                    connection,
                    source_id=(
                        source.source_id
                    ),
                    representation_id=(
                        representation
                        .representation_id
                    ),
                    protection_scope_id=(
                        scope.protection_scope_id
                    ),
                    payload_writer=writer,
                )
            )

        payloads_after_first = int(
            app.database
            .connection
            .execute(
                """
                SELECT COUNT(*)
                FROM protected_payloads
                """
            )
            .fetchone()[0]
        )

        with (
            app.database
            .write_transaction()
            as connection
        ):
            second = (
                repository
                .protect_representation_semantics(
                    connection,
                    source_id=(
                        source.source_id
                    ),
                    representation_id=(
                        representation
                        .representation_id
                    ),
                    protection_scope_id=(
                        scope.protection_scope_id
                    ),
                    payload_writer=writer,
                )
            )

        payloads_after_second = int(
            app.database
            .connection
            .execute(
                """
                SELECT COUNT(*)
                FROM protected_payloads
                """
            )
            .fetchone()[0]
        )

        assert second == first
        assert len(
            calls
        ) == 1
        assert (
            payloads_after_second
            == payloads_after_first
        )

    finally:
        app.stop()


def test_representation_semantic_cutover_rolls_back_ciphertext_mapping_and_row_together(
    tmp_path: Path,
) -> None:
    app = _app(
        tmp_path
        / "runtime"
    )

    try:
        source, representation = (
            _representation(
                app,
                tmp_path,
            )
        )

        original_hash = (
            representation
            .content_hash
        )
        original_options = (
            representation
            .options_json
        )

        scope = _scope(
            app,
            password=(
                b"rollback-semantic-password"
            ),
        )

        repository = (
            SourceProtectedSemanticRepository(
                app.database
            )
        )

        before_payloads = int(
            app.database
            .connection
            .execute(
                """
                SELECT COUNT(*)
                FROM protected_payloads
                """
            )
            .fetchone()[0]
        )

        with (
            app.database
            .write_transaction()
            as connection
        ):
            connection.execute(
                """
                CREATE TRIGGER
                test_fail_semantic_mapping
                BEFORE INSERT ON
                source_protected_semantic_payloads
                BEGIN
                    SELECT RAISE(
                        ABORT,
                        'synthetic semantic mapping failure'
                    );
                END
                """
            )

        try:
            with pytest.raises(
                SourceProtectedSemanticIntegrityError,
                match=(
                    "mapping violates"
                ),
            ):
                with (
                    app.database
                    .write_transaction()
                    as connection
                ):
                    (
                        repository
                        .protect_representation_semantics(
                            connection,
                            source_id=(
                                source.source_id
                            ),
                            representation_id=(
                                representation
                                .representation_id
                            ),
                            protection_scope_id=(
                                scope
                                .protection_scope_id
                            ),
                            payload_writer=(
                                _writer(
                                    app,
                                    scope
                                    .protection_scope_id,
                                )
                            ),
                        )
                    )

        finally:
            with (
                app.database
                .write_transaction()
                as connection
            ):
                connection.execute(
                    """
                    DROP TRIGGER IF EXISTS
                    test_fail_semantic_mapping
                    """
                )

        after_payloads = int(
            app.database
            .connection
            .execute(
                """
                SELECT COUNT(*)
                FROM protected_payloads
                """
            )
            .fetchone()[0]
        )

        assert (
            after_payloads
            == before_payloads
        )

        assert (
            repository
            .get_representation_mapping(
                source_id=(
                    source.source_id
                ),
                representation_id=(
                    representation
                    .representation_id
                ),
            )
            is None
        )

        row = (
            app.database
            .connection
            .execute(
                """
                SELECT
                    content_hash,
                    options_json
                FROM source_representations
                WHERE representation_id = ?
                """,
                (
                    representation
                    .representation_id
                    .bytes,
                ),
            )
            .fetchone()
        )

        assert row is not None
        assert bytes(
            row[
                "content_hash"
            ]
        ) == original_hash
        assert str(
            row[
                "options_json"
            ]
        ) == original_options

    finally:
        app.stop()


def test_representation_semantic_cutover_rejects_wrong_source_before_encrypting(
    tmp_path: Path,
) -> None:
    app = _app(
        tmp_path
        / "runtime"
    )

    try:
        _source, representation = (
            _representation(
                app,
                tmp_path,
            )
        )

        scope = _scope(
            app,
            password=(
                b"wrong-source-semantic-password"
            ),
        )

        repository = (
            SourceProtectedSemanticRepository(
                app.database
            )
        )

        calls: list[
            bytes
        ] = []

        with pytest.raises(
            SourceProtectedSemanticIntegrityError,
            match=(
                "does not belong"
            ),
        ):
            with (
                app.database
                .write_transaction()
                as connection
            ):
                (
                    repository
                    .protect_representation_semantics(
                        connection,
                        source_id=uuid.uuid4(),
                        representation_id=(
                            representation
                            .representation_id
                        ),
                        protection_scope_id=(
                            scope
                            .protection_scope_id
                        ),
                        payload_writer=(
                            _writer(
                                app,
                                scope
                                .protection_scope_id,
                                calls=calls,
                            )
                        ),
                    )
                )

        assert calls == []

    finally:
        app.stop()


def test_representation_semantic_cutover_requires_active_transaction(
    tmp_path: Path,
) -> None:
    app = _app(
        tmp_path
        / "runtime"
    )

    try:
        source, representation = (
            _representation(
                app,
                tmp_path,
            )
        )

        scope = _scope(
            app,
            password=(
                b"transaction-semantic-password"
            ),
        )

        repository = (
            SourceProtectedSemanticRepository(
                app.database
            )
        )

        with pytest.raises(
            RuntimeError,
            match=(
                "requires an active transaction"
            ),
        ):
            (
                repository
                .protect_representation_semantics(
                    app.database.connection,
                    source_id=(
                        source.source_id
                    ),
                    representation_id=(
                        representation
                        .representation_id
                    ),
                    protection_scope_id=(
                        scope.protection_scope_id
                    ),
                    payload_writer=(
                        _writer(
                            app,
                            scope
                            .protection_scope_id,
                        )
                    ),
                )
            )

    finally:
        app.stop()


def test_existing_mapping_with_non_neutral_public_row_fails_closed(
    tmp_path: Path,
) -> None:
    app = _app(
        tmp_path
        / "runtime"
    )

    try:
        source, representation = (
            _representation(
                app,
                tmp_path,
            )
        )

        scope = _scope(
            app,
            password=(
                b"mixed-state-semantic-password"
            ),
        )

        repository = (
            SourceProtectedSemanticRepository(
                app.database
            )
        )

        writer = _writer(
            app,
            scope.protection_scope_id,
        )

        with (
            app.database
            .write_transaction()
            as connection
        ):
            (
                repository
                .protect_representation_semantics(
                    connection,
                    source_id=(
                        source.source_id
                    ),
                    representation_id=(
                        representation
                        .representation_id
                    ),
                    protection_scope_id=(
                        scope.protection_scope_id
                    ),
                    payload_writer=writer,
                )
            )

        with (
            app.database
            .write_transaction()
            as connection
        ):
            connection.execute(
                """
                UPDATE source_representations
                SET options_json = ?
                WHERE representation_id = ?
                """,
                (
                    representation
                    .options_json,
                    representation
                    .representation_id
                    .bytes,
                ),
            )

        with pytest.raises(
            SourceProtectedSemanticIntegrityError,
            match=(
                "not neutralized"
            ),
        ):
            with (
                app.database
                .write_transaction()
                as connection
            ):
                (
                    repository
                    .protect_representation_semantics(
                        connection,
                        source_id=(
                            source.source_id
                        ),
                        representation_id=(
                            representation
                            .representation_id
                        ),
                        protection_scope_id=(
                            scope
                            .protection_scope_id
                        ),
                        payload_writer=writer,
                    )
                )

    finally:
        app.stop()
