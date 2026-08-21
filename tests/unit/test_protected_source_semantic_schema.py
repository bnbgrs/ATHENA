from __future__ import annotations

import sqlite3
from pathlib import Path

from athena.storage.schema import (
    GROUNDED_RESPONSE_RECEIPT_MIGRATION_ID,
    GROUNDED_RESPONSE_RECEIPT_SCHEMA_VERSION,
    OPERATIONAL_ERROR_PHYSICAL_CLEANUP_MIGRATION_ID,
    OPERATIONAL_ERROR_PHYSICAL_CLEANUP_SCHEMA_VERSION,
    PROTECTED_SOURCE_SEMANTIC_SCHEMA_VERSION,
    SCHEMA_VERSION,
    initialize_schema,
)


def _connect(
    path: Path,
) -> sqlite3.Connection:
    connection = sqlite3.connect(
        path
    )

    connection.row_factory = (
        sqlite3.Row
    )

    return connection


def _schema_metadata(
    connection: sqlite3.Connection,
) -> sqlite3.Row:
    row = connection.execute(
        """
        SELECT
            schema_version,
            last_migration_id,
            minimum_reader_version
        FROM schema_metadata
        WHERE singleton_id = 1
        """
    ).fetchone()

    assert row is not None

    return row


def test_fresh_database_reaches_protected_source_semantic_schema(
    tmp_path: Path,
) -> None:
    database_path = (
        tmp_path
        / "fresh-v39.db"
    )

    connection = _connect(
        database_path
    )

    try:
        initialize_schema(
            connection,
            created_at_us=1,
        )

        assert (
            PROTECTED_SOURCE_SEMANTIC_SCHEMA_VERSION
            == 39
        )

        assert (
            SCHEMA_VERSION
            == GROUNDED_RESPONSE_RECEIPT_SCHEMA_VERSION
            == 40
        )

        assert int(
            connection.execute(
                "PRAGMA user_version"
            ).fetchone()[0]
        ) == SCHEMA_VERSION

        metadata = _schema_metadata(
            connection
        )

        assert int(
            metadata[
                "schema_version"
            ]
        ) == SCHEMA_VERSION

        assert (
            str(
                metadata[
                    "last_migration_id"
                ]
            )
            == GROUNDED_RESPONSE_RECEIPT_MIGRATION_ID
        )

        assert int(
            metadata[
                "minimum_reader_version"
            ]
        ) == SCHEMA_VERSION

        tables = {
            str(row[0])
            for row
            in connection.execute(
                """
                SELECT name
                FROM sqlite_master
                WHERE type = 'table'
                """
            )
        }

        assert (
            "source_protected_semantic_payloads"
            in tables
        )

        assert (
            "source_protection_representation_blobs"
            in tables
        )

        assert (
            connection.execute(
                "PRAGMA foreign_key_check"
            ).fetchall()
            == []
        )

    finally:
        connection.close()


def test_realistic_v38_database_migrates_additively_to_v39(
    tmp_path: Path,
) -> None:
    database_path = (
        tmp_path
        / "upgrade-v38-v39.db"
    )

    connection = _connect(
        database_path
    )

    try:
        # Build the complete current schema first,
        # then remove only the additive v39 state and
        # restore v38 metadata. This yields an exact
        # structural v38 predecessor using the same
        # local schema implementation.
        initialize_schema(
            connection,
            created_at_us=1,
        )

        connection.execute(
            """
            DROP TABLE
            grounded_response_receipts
            """
        )

        connection.execute(
            """
            DROP TABLE
            source_protection_representation_blobs
            """
        )

        connection.execute(
            """
            DROP TABLE
            source_protected_semantic_payloads
            """
        )

        connection.execute(
            """
            UPDATE schema_metadata
            SET schema_version = ?,
                last_migration_id = ?,
                minimum_reader_version = ?
            WHERE singleton_id = 1
            """,
            (
                OPERATIONAL_ERROR_PHYSICAL_CLEANUP_SCHEMA_VERSION,
                OPERATIONAL_ERROR_PHYSICAL_CLEANUP_MIGRATION_ID,
                OPERATIONAL_ERROR_PHYSICAL_CLEANUP_SCHEMA_VERSION,
            ),
        )

        connection.execute(
            f"PRAGMA user_version = "
            f"{OPERATIONAL_ERROR_PHYSICAL_CLEANUP_SCHEMA_VERSION}"
        )

        connection.commit()

        assert int(
            connection.execute(
                "PRAGMA user_version"
            ).fetchone()[0]
        ) == 38

        initialize_schema(
            connection,
            created_at_us=2,
        )

        assert int(
            connection.execute(
                "PRAGMA user_version"
            ).fetchone()[0]
        ) == SCHEMA_VERSION

        metadata = _schema_metadata(
            connection
        )

        assert int(
            metadata[
                "schema_version"
            ]
        ) == SCHEMA_VERSION

        assert (
            str(
                metadata[
                    "last_migration_id"
                ]
            )
            == GROUNDED_RESPONSE_RECEIPT_MIGRATION_ID
        )

        assert (
            connection.execute(
                "PRAGMA foreign_key_check"
            ).fetchall()
            == []
        )

    finally:
        connection.close()


def test_v39_semantic_and_representation_transition_contracts(
    tmp_path: Path,
) -> None:
    database_path = (
        tmp_path
        / "contracts-v39.db"
    )

    connection = _connect(
        database_path
    )

    try:
        initialize_schema(
            connection,
            created_at_us=1,
        )

        semantic_columns = {
            str(row["name"])
            for row
            in connection.execute(
                """
                PRAGMA table_info(
                    source_protected_semantic_payloads
                )
                """
            )
        }

        assert {
            "source_id",
            "semantic_kind",
            "entity_id",
            "protection_scope_id",
            "protected_payload_id",
            "payload_version",
            "created_at_us",
        }.issubset(
            semantic_columns
        )

        semantic_foreign_keys = {
            (
                str(row["from"]),
                str(row["table"]),
                str(row["to"]),
            )
            for row
            in connection.execute(
                """
                PRAGMA foreign_key_list(
                    source_protected_semantic_payloads
                )
                """
            )
        }

        assert {
            (
                "source_id",
                "sources",
                "source_id",
            ),
            (
                "protection_scope_id",
                "protection_scopes",
                "protection_scope_id",
            ),
            (
                "protected_payload_id",
                "protected_payloads",
                "protected_payload_id",
            ),
        }.issubset(
            semantic_foreign_keys
        )

        representation_foreign_keys = {
            (
                str(row["from"]),
                str(row["table"]),
                str(row["to"]),
            )
            for row
            in connection.execute(
                """
                PRAGMA foreign_key_list(
                    source_protection_representation_blobs
                )
                """
            )
        }

        assert {
            (
                "transition_id",
                "source_protection_transitions",
                "transition_id",
            ),
            (
                "representation_id",
                "source_representations",
                "representation_id",
            ),
            (
                "old_blob_id",
                "blob_records",
                "blob_id",
            ),
            (
                "target_blob_id",
                "blob_records",
                "blob_id",
            ),
        }.issubset(
            representation_foreign_keys
        )

        indexes = {
            str(row[0])
            for row
            in connection.execute(
                """
                SELECT name
                FROM sqlite_master
                WHERE type = 'index'
                """
            )
        }

        assert {
            "idx_source_protected_semantic_scope",
            "idx_source_protected_semantic_entity",
            "idx_source_protection_representation_state",
            "idx_source_protection_representation_old_blob",
        }.issubset(
            indexes
        )

        assert (
            connection.execute(
                "PRAGMA foreign_key_check"
            ).fetchall()
            == []
        )

    finally:
        connection.close()
