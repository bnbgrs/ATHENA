from __future__ import annotations

import uuid
from pathlib import Path

import pytest

from athena.config.settings import AthenaSettings
from athena.core.application import AthenaApplication
from athena.lifecycle.protected_purge import (
    ProtectedScopeDeletionBlockedError,
)
from athena.security.models import Argon2idParameters

_PASSWORD = b"slice15-offline-regression-password"


def _application(
    tmp_path: Path,
) -> tuple[
    AthenaApplication,
    Path,
]:
    archive_root = (
        tmp_path
        / "configured-but-unavailable-archive"
    )

    app = AthenaApplication(
        AthenaSettings(
            local_root=(
                tmp_path
                / "runtime"
            ),
            archive_root=archive_root,
            log_level="WARNING",
        )
    )

    app.start()

    app.protected_content.initialize_password(
        _PASSWORD,
        parameters=Argon2idParameters(
            iterations=1,
            lanes=1,
            memory_cost_kib=8 * 1024,
            length=32,
        ),
    )

    return (
        app,
        archive_root,
    )


def _capture_protected_source(
    app: AthenaApplication,
    tmp_path: Path,
) -> tuple[
    uuid.UUID,
    uuid.UUID,
    str,
]:
    source_path = (
        tmp_path
        / "protected.bin"
    )

    source_path.write_bytes(
        b"protected-offline-regression"
    )

    scope = (
        app.protected_content
        .create_scope(
            _PASSWORD,
            neutral_label="offline regression",
        )
    )

    app.protected_content.unlock_scope(
        scope.protection_scope_id,
        _PASSWORD,
    )

    captured = (
        app.sources
        .capture_protected_file(
            source_path,
            protection_scope_id=(
                scope.protection_scope_id
            ),
        )
    )

    return (
        scope.protection_scope_id,
        captured.source.source_id,
        captured.blob.storage_locator,
    )


def test_protected_scope_delete_uses_reachable_spool_when_archive_unavailable(
    tmp_path: Path,
) -> None:
    app, archive_root = (
        _application(
            tmp_path
        )
    )

    try:
        (
            scope_id,
            source_id,
            storage_locator,
        ) = _capture_protected_source(
            app,
            tmp_path,
        )

        assert (
            not archive_root.exists()
        )

        spool_path = (
            app.paths.spool_root
            / Path(
                storage_locator
            )
        )

        assert (
            spool_path.is_file()
        )

        preview = (
            app.protected_scope_purge
            .preview(
                scope_id
            )
        )

        result = (
            app.protected_scope_purge
            .delete(
                scope_id,
                preview_digest=(
                    preview.preview_digest
                ),
            )
        )

        assert (
            result.protection_scope_id
            == scope_id
        )

        assert (
            source_id
            in result.deleted_source_ids
        )

        assert (
            result.deleted_replica_count
            == 1
        )

        assert (
            not spool_path.exists()
        )

        assert (
            not archive_root.exists()
        )

        connection = (
            app.database.connection
        )

        scope = connection.execute(
            """
            SELECT
                lifecycle_state,
                current_scope_key_id
            FROM protection_scopes
            WHERE protection_scope_id = ?
            """,
            (
                scope_id.bytes,
            ),
        ).fetchone()

        assert scope is not None

        assert (
            str(
                scope[
                    "lifecycle_state"
                ]
            )
            == "pending_delete"
        )

        assert (
            scope[
                "current_scope_key_id"
            ]
            is None
        )

    finally:
        app.stop()


def test_protected_scope_blocks_null_scope_live_source_sharing_blob(
    tmp_path: Path,
) -> None:
    app, _archive_root = (
        _application(
            tmp_path
        )
    )

    try:
        (
            scope_id,
            source_id,
            _storage_locator,
        ) = _capture_protected_source(
            app,
            tmp_path,
        )

        outside_source_id = (
            uuid.uuid4()
        )

        with (
            app.database
            .write_transaction()
            as connection
        ):
            entity_columns = tuple(
                str(
                    row[
                        "name"
                    ]
                )
                for row
                in connection.execute(
                    """
                    PRAGMA table_info(
                        entity_registry
                    )
                    """
                ).fetchall()
            )

            source_columns = tuple(
                str(
                    row[
                        "name"
                    ]
                )
                for row
                in connection.execute(
                    """
                    PRAGMA table_info(
                        sources
                    )
                    """
                ).fetchall()
            )

            entity_select: list[
                str
            ] = []

            entity_params: list[
                object
            ] = []

            for column in entity_columns:
                if column == "entity_id":
                    entity_select.append(
                        "?"
                    )

                    entity_params.append(
                        outside_source_id.bytes
                    )

                elif (
                    column
                    == "protection_scope_id"
                ):
                    entity_select.append(
                        "NULL"
                    )

                else:
                    entity_select.append(
                        f'"{column}"'
                    )

            entity_params.append(
                source_id.bytes
            )

            connection.execute(
                f"""
                INSERT INTO entity_registry (
                    {
                        ", ".join(
                            f'"{column}"'
                            for column
                            in entity_columns
                        )
                    }
                )
                SELECT
                    {
                        ", ".join(
                            entity_select
                        )
                    }
                FROM entity_registry
                WHERE entity_id = ?
                """,
                tuple(
                    entity_params
                ),
            )

            source_select: list[
                str
            ] = []

            source_params: list[
                object
            ] = []

            for column in source_columns:
                if column == "source_id":
                    source_select.append(
                        "?"
                    )

                    source_params.append(
                        outside_source_id.bytes
                    )

                else:
                    source_select.append(
                        f'"{column}"'
                    )

            source_params.append(
                source_id.bytes
            )

            connection.execute(
                f"""
                INSERT INTO sources (
                    {
                        ", ".join(
                            f'"{column}"'
                            for column
                            in source_columns
                        )
                    }
                )
                SELECT
                    {
                        ", ".join(
                            source_select
                        )
                    }
                FROM sources
                WHERE source_id = ?
                """,
                tuple(
                    source_params
                ),
            )

        with pytest.raises(
            ProtectedScopeDeletionBlockedError,
            match=(
                "live Source outside "
                "this scope"
            ),
        ):
            (
                app.protected_scope_purge
                .preview(
                    scope_id
                )
            )

    finally:
        app.stop()
