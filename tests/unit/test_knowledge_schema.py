import sqlite3

from athena.common.ids import new_uuid7, uuid_to_blob
from athena.storage.database import SQLiteDatabase
from athena.storage.schema import (
    EXTRACTION_SNAPSHOT_SCHEMA_VERSION,
    KNOWLEDGE_SCHEMA_VERSION,
    LEGACY_SCHEMA_VERSION,
    LOCAL_EMBEDDINGS_MIGRATION_ID,
    LOCAL_FTS_SCHEMA_VERSION,
    MERGE_REVIEW_MULTI_TARGET_SCHEMA_VERSION,
    MERGE_REVIEW_SCHEMA_VERSION,
    MODEL_RUNS_SCHEMA_VERSION,
    PROVENANCE_SCHEMA_VERSION,
    REVIEW_QUEUE_SCHEMA_VERSION,
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
    "semantic_review_items",
    "semantic_merge_review_payloads",
    "extraction_result_snapshots",
    "search_fts",
    "search_index_state",
    "search_embeddings",
    "search_embedding_state",
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
        LOCAL_EMBEDDINGS_MIGRATION_ID,
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


def test_v4_database_is_upgraded_additively_to_review_queue(tmp_path) -> None:
    from athena.storage.schema import _migrate_schema_v3_to_v4

    path = tmp_path / "athena.db"
    legacy = sqlite3.connect(path, autocommit=True)
    legacy.row_factory = sqlite3.Row
    legacy.execute("PRAGMA auto_vacuum = INCREMENTAL")
    legacy.execute("PRAGMA application_id = 1096042574")
    _create_schema_v1(legacy, created_at_us=1)
    _migrate_schema_v1_to_v2(legacy)
    _migrate_schema_v2_to_v3(legacy)
    _migrate_schema_v3_to_v4(legacy)
    assert legacy.execute("PRAGMA user_version").fetchone()[0] == MODEL_RUNS_SCHEMA_VERSION
    assert "semantic_review_items" not in _table_names(legacy)
    legacy.close()

    database = SQLiteDatabase(path)
    database.start()
    assert database.connection.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION
    assert "semantic_review_items" in _table_names(database.connection)
    database.stop()


def test_v5_database_is_upgraded_additively_to_persistent_merge_reviews(tmp_path) -> None:
    from athena.storage.schema import _migrate_schema_v3_to_v4, _migrate_schema_v4_to_v5

    path = tmp_path / "athena.db"
    legacy = sqlite3.connect(path, autocommit=True)
    legacy.row_factory = sqlite3.Row
    legacy.execute("PRAGMA auto_vacuum = INCREMENTAL")
    legacy.execute("PRAGMA application_id = 1096042574")
    _create_schema_v1(legacy, created_at_us=1)
    _migrate_schema_v1_to_v2(legacy)
    _migrate_schema_v2_to_v3(legacy)
    _migrate_schema_v3_to_v4(legacy)
    _migrate_schema_v4_to_v5(legacy)
    assert legacy.execute("PRAGMA user_version").fetchone()[0] == REVIEW_QUEUE_SCHEMA_VERSION
    assert "semantic_merge_review_payloads" not in _table_names(legacy)
    legacy.close()

    database = SQLiteDatabase(path)
    database.start()
    assert database.connection.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION
    assert "semantic_merge_review_payloads" in _table_names(database.connection)
    database.stop()


def test_v6_database_is_upgraded_to_multi_target_merge_reviews(tmp_path) -> None:
    from athena.storage.schema import (
        _migrate_schema_v3_to_v4,
        _migrate_schema_v4_to_v5,
        _migrate_schema_v5_to_v6,
    )

    path = tmp_path / "athena.db"
    legacy = sqlite3.connect(path, autocommit=True)
    legacy.row_factory = sqlite3.Row
    legacy.execute("PRAGMA auto_vacuum = INCREMENTAL")
    legacy.execute("PRAGMA application_id = 1096042574")
    _create_schema_v1(legacy, created_at_us=1)
    _migrate_schema_v1_to_v2(legacy)
    _migrate_schema_v2_to_v3(legacy)
    _migrate_schema_v3_to_v4(legacy)
    _migrate_schema_v4_to_v5(legacy)
    _migrate_schema_v5_to_v6(legacy)
    assert legacy.execute("PRAGMA user_version").fetchone()[0] == MERGE_REVIEW_SCHEMA_VERSION
    index_names = {
        str(row["name"])
        for row in legacy.execute("PRAGMA index_list('semantic_merge_review_payloads')")
    }
    assert "uq_semantic_merge_review_identity" in index_names
    legacy.close()

    database = SQLiteDatabase(path)
    database.start()
    assert database.connection.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION
    payload_indexes = {
        str(row["name"])
        for row in database.connection.execute(
            "PRAGMA index_list('semantic_merge_review_payloads')"
        )
    }
    review_indexes = {
        str(row["name"])
        for row in database.connection.execute(
            "PRAGMA index_list('semantic_review_items')"
        )
    }
    assert "uq_semantic_merge_review_identity" not in payload_indexes
    assert "idx_semantic_merge_review_identity" in payload_indexes
    assert "uq_semantic_merge_review_target" in review_indexes
    database.stop()


def test_v7_database_is_upgraded_to_frozen_extraction_snapshots(tmp_path) -> None:
    from athena.storage.schema import (
        _migrate_schema_v3_to_v4,
        _migrate_schema_v4_to_v5,
        _migrate_schema_v5_to_v6,
        _migrate_schema_v6_to_v7,
    )

    path = tmp_path / "athena.db"
    legacy = sqlite3.connect(path, autocommit=True)
    legacy.row_factory = sqlite3.Row
    legacy.execute("PRAGMA auto_vacuum = INCREMENTAL")
    legacy.execute("PRAGMA application_id = 1096042574")
    _create_schema_v1(legacy, created_at_us=1)
    _migrate_schema_v1_to_v2(legacy)
    _migrate_schema_v2_to_v3(legacy)
    _migrate_schema_v3_to_v4(legacy)
    _migrate_schema_v4_to_v5(legacy)
    _migrate_schema_v5_to_v6(legacy)
    _migrate_schema_v6_to_v7(legacy)
    assert (
        legacy.execute("PRAGMA user_version").fetchone()[0]
        == MERGE_REVIEW_MULTI_TARGET_SCHEMA_VERSION
    )
    assert "extraction_result_snapshots" not in _table_names(legacy)
    legacy.close()

    database = SQLiteDatabase(path)
    database.start()
    assert database.connection.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION
    assert "extraction_result_snapshots" in _table_names(database.connection)
    database.stop()


def test_v8_database_is_upgraded_additively_to_local_fts_search(tmp_path) -> None:
    from athena.storage.schema import (
        _migrate_schema_v3_to_v4,
        _migrate_schema_v4_to_v5,
        _migrate_schema_v5_to_v6,
        _migrate_schema_v6_to_v7,
        _migrate_schema_v7_to_v8,
    )

    path = tmp_path / "athena.db"
    legacy = sqlite3.connect(path, autocommit=True)
    legacy.row_factory = sqlite3.Row
    legacy.execute("PRAGMA auto_vacuum = INCREMENTAL")
    legacy.execute("PRAGMA application_id = 1096042574")
    _create_schema_v1(legacy, created_at_us=1)
    _migrate_schema_v1_to_v2(legacy)
    _migrate_schema_v2_to_v3(legacy)
    _migrate_schema_v3_to_v4(legacy)
    _migrate_schema_v4_to_v5(legacy)
    _migrate_schema_v5_to_v6(legacy)
    _migrate_schema_v6_to_v7(legacy)
    _migrate_schema_v7_to_v8(legacy)
    assert (
        legacy.execute("PRAGMA user_version").fetchone()[0]
        == EXTRACTION_SNAPSHOT_SCHEMA_VERSION
    )
    assert "search_fts" not in _table_names(legacy)
    legacy.close()

    database = SQLiteDatabase(path)
    database.start()
    assert database.connection.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION
    assert "search_fts" in _table_names(database.connection)
    assert "search_index_state" in _table_names(database.connection)
    database.stop()


def test_v9_database_is_upgraded_additively_to_local_embeddings(tmp_path) -> None:
    from athena.storage.schema import (
        _migrate_schema_v3_to_v4,
        _migrate_schema_v4_to_v5,
        _migrate_schema_v5_to_v6,
        _migrate_schema_v6_to_v7,
        _migrate_schema_v7_to_v8,
        _migrate_schema_v8_to_v9,
    )

    path = tmp_path / "athena.db"
    legacy = sqlite3.connect(path, autocommit=True)
    legacy.row_factory = sqlite3.Row
    legacy.execute("PRAGMA auto_vacuum = INCREMENTAL")
    legacy.execute("PRAGMA application_id = 1096042574")
    _create_schema_v1(legacy, created_at_us=1)
    _migrate_schema_v1_to_v2(legacy)
    _migrate_schema_v2_to_v3(legacy)
    _migrate_schema_v3_to_v4(legacy)
    _migrate_schema_v4_to_v5(legacy)
    _migrate_schema_v5_to_v6(legacy)
    _migrate_schema_v6_to_v7(legacy)
    _migrate_schema_v7_to_v8(legacy)
    _migrate_schema_v8_to_v9(legacy)
    assert legacy.execute("PRAGMA user_version").fetchone()[0] == LOCAL_FTS_SCHEMA_VERSION
    assert "search_embeddings" not in _table_names(legacy)
    legacy.close()

    database = SQLiteDatabase(path)
    database.start()
    assert database.connection.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION
    assert "search_embeddings" in _table_names(database.connection)
    assert "search_embedding_state" in _table_names(database.connection)
    database.stop()
