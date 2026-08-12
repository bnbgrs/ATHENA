import sqlite3

from athena.common.ids import new_uuid7, uuid_to_blob
from athena.storage.database import SQLiteDatabase
from athena.storage.schema import (
    KNOWLEDGE_SCHEMA_VERSION,
    LEGACY_SCHEMA_VERSION,
    MODEL_RUNS_MIGRATION_ID,
    PROVENANCE_SCHEMA_VERSION,
    SCHEMA_VERSION,
    _create_schema_v1,
    _migrate_schema_v1_to_v2,
    _migrate_schema_v2_to_v3,
)

EXPECTED_SEMANTIC_TABLES = {
    "knowledge_units",
    "knowledge_unit_revisions",
    "claims",
    "claim_revisions",
    "claim_evidence",
    "provenance_inputs",
    "model_signatures",
    "processing_runs",
}


def _table_names(connection: sqlite3.Connection) -> set[str]:
    rows = connection.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table'"
    ).fetchall()
    return {str(row[0]) for row in rows}


def test_fresh_database_contains_semantic_schema(tmp_path) -> None:
    database = SQLiteDatabase(tmp_path / "athena.db")
    database.start()

    connection = database.connection
    assert connection.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION
    assert EXPECTED_SEMANTIC_TABLES.issubset(_table_names(connection))

    metadata = connection.execute(
        "SELECT schema_version, last_migration_id, minimum_reader_version "
        "FROM schema_metadata WHERE singleton_id = 1"
    ).fetchone()
    assert tuple(metadata) == (
        SCHEMA_VERSION,
        MODEL_RUNS_MIGRATION_ID,
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
    assert EXPECTED_SEMANTIC_TABLES.issubset(_table_names(connection))
    actor = connection.execute(
        "SELECT display_name FROM actors WHERE actor_id = ?",
        (uuid_to_blob(actor_id),),
    ).fetchone()
    assert actor is not None
    assert actor["display_name"] == "migration-test-user"

    database.stop()


def test_v2_database_is_upgraded_additively_to_latest_schema(tmp_path) -> None:
    path = tmp_path / "athena.db"

    legacy = sqlite3.connect(path, autocommit=True)
    legacy.row_factory = sqlite3.Row
    legacy.execute("PRAGMA auto_vacuum = INCREMENTAL")
    legacy.execute("PRAGMA application_id = 1096042574")
    _create_schema_v1(legacy, created_at_us=1)
    _migrate_schema_v1_to_v2(legacy)
    assert legacy.execute("PRAGMA user_version").fetchone()[0] == KNOWLEDGE_SCHEMA_VERSION
    assert "provenance_inputs" not in _table_names(legacy)
    legacy.close()

    database = SQLiteDatabase(path)
    database.start()

    connection = database.connection
    assert connection.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION
    assert EXPECTED_SEMANTIC_TABLES.issubset(_table_names(connection))
    database.stop()


def test_v3_database_is_upgraded_additively_to_model_run_schema(tmp_path) -> None:
    path = tmp_path / "athena.db"

    legacy = sqlite3.connect(path, autocommit=True)
    legacy.row_factory = sqlite3.Row
    legacy.execute("PRAGMA auto_vacuum = INCREMENTAL")
    legacy.execute("PRAGMA application_id = 1096042574")
    _create_schema_v1(legacy, created_at_us=1)
    _migrate_schema_v1_to_v2(legacy)
    _migrate_schema_v2_to_v3(legacy)
    assert legacy.execute("PRAGMA user_version").fetchone()[0] == PROVENANCE_SCHEMA_VERSION
    assert "model_signatures" not in _table_names(legacy)
    assert "processing_runs" not in _table_names(legacy)
    legacy.close()

    database = SQLiteDatabase(path)
    database.start()

    connection = database.connection
    assert connection.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION
    assert "model_signatures" in _table_names(connection)
    assert "processing_runs" in _table_names(connection)
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
