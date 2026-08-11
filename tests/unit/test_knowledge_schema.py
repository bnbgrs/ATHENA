import sqlite3

from athena.common.ids import new_uuid7, uuid_to_blob
from athena.storage.database import SQLiteDatabase
from athena.storage.schema import (
    KNOWLEDGE_CORE_MIGRATION_ID,
    LEGACY_SCHEMA_VERSION,
    SCHEMA_VERSION,
    _create_schema_v1,
)

EXPECTED_KNOWLEDGE_TABLES = {
    "knowledge_units",
    "knowledge_unit_revisions",
    "claims",
    "claim_revisions",
    "claim_evidence",
}


def _table_names(connection: sqlite3.Connection) -> set[str]:
    rows = connection.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table'"
    ).fetchall()
    return {str(row[0]) for row in rows}


def test_fresh_database_contains_knowledge_schema(tmp_path) -> None:
    database = SQLiteDatabase(tmp_path / "athena.db")
    database.start()

    connection = database.connection
    assert connection.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION
    assert EXPECTED_KNOWLEDGE_TABLES.issubset(_table_names(connection))

    metadata = connection.execute(
        "SELECT schema_version, last_migration_id, minimum_reader_version "
        "FROM schema_metadata WHERE singleton_id = 1"
    ).fetchone()
    assert tuple(metadata) == (
        SCHEMA_VERSION,
        KNOWLEDGE_CORE_MIGRATION_ID,
        SCHEMA_VERSION,
    )

    database.stop()


def test_v1_database_is_upgraded_without_losing_existing_actor(tmp_path) -> None:
    path = tmp_path / "athena.db"
    actor_id = new_uuid7()

    legacy = sqlite3.connect(path, autocommit=True)
    legacy.row_factory = sqlite3.Row
    legacy.execute("PRAGMA auto_vacuum = INCREMENTAL")
    legacy.execute("PRAGMA application_id = 1096042574")
    _create_schema_v1(legacy, created_at_us=1)
    legacy.execute(
        """
        INSERT INTO actors (
            actor_id, actor_type, display_name, plugin_id, created_at_us, active
        ) VALUES (?, 'user', 'migration-test-user', NULL, 2, 1)
        """,
        (uuid_to_blob(actor_id),),
    )
    assert legacy.execute("PRAGMA user_version").fetchone()[0] == LEGACY_SCHEMA_VERSION
    legacy.close()

    database = SQLiteDatabase(path)
    database.start()

    connection = database.connection
    assert connection.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION
    assert EXPECTED_KNOWLEDGE_TABLES.issubset(_table_names(connection))
    actor = connection.execute(
        "SELECT display_name FROM actors WHERE actor_id = ?",
        (uuid_to_blob(actor_id),),
    ).fetchone()
    assert actor is not None
    assert actor["display_name"] == "migration-test-user"

    database.stop()


def test_claim_evidence_schema_rejects_reference_free_row(tmp_path) -> None:
    database = SQLiteDatabase(tmp_path / "athena.db")
    database.start()

    connection = database.connection
    columns = {
        str(row[1])
        for row in connection.execute("PRAGMA table_info(claim_evidence)").fetchall()
    }
    assert {
        "claim_id",
        "anchor_id",
        "message_id",
        "evidence_entity_id",
        "evidence_revision_id",
        "evidence_role",
        "provenance_id",
    }.issubset(columns)

    database.stop()
