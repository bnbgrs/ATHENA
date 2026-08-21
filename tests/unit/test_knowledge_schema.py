import json
import sqlite3

from athena.common.ids import new_uuid7, uuid_to_blob
from athena.storage.database import SQLiteDatabase
from athena.storage.schema import (
    CONSOLIDATED_OPERATIONS_SCHEMA_VERSION,
    DELETION_LEDGER_MIGRATION_ID,
    DELETION_LEDGER_SCHEMA_VERSION,
    DURABLE_JOBS_SCHEMA_VERSION,
    EXHAUSTIVE_RESEARCH_SCHEMA_VERSION,
    EXTRACTION_SNAPSHOT_SCHEMA_VERSION,
    GROUNDED_RESPONSE_RECEIPT_MIGRATION_ID,
    HIERARCHICAL_SOURCE_EXTRACTION_SCHEMA_VERSION,
    KNOWLEDGE_SCHEMA_VERSION,
    LEGACY_SCHEMA_VERSION,
    LOCAL_EMBEDDINGS_SCHEMA_VERSION,
    LOCAL_FTS_SCHEMA_VERSION,
    MERGE_REVIEW_MULTI_TARGET_SCHEMA_VERSION,
    MERGE_REVIEW_SCHEMA_VERSION,
    MODEL_RUNS_SCHEMA_VERSION,
    NEWS_EVENT_STRUCTURE_MIGRATION_ID,
    NEWS_EVENT_STRUCTURE_SCHEMA_VERSION,
    NEWS_OPERATIONAL_MIGRATION_ID,
    NEWS_OPERATIONAL_SCHEMA_VERSION,
    NEWS_SYSTEM_MIGRATION_ID,
    NEWS_SYSTEM_SCHEMA_VERSION,
    PERSONAL_MEMORY_MIGRATION_ID,
    PERSONAL_MEMORY_SCHEMA_VERSION,
    PRECISE_RESEARCH_PROVENANCE_MIGRATION_ID,
    PRECISE_RESEARCH_PROVENANCE_SCHEMA_VERSION,
    PROVENANCE_SCHEMA_VERSION,
    RESEARCH_ORCHESTRATION_MIGRATION_ID,
    RESEARCH_ORCHESTRATION_SCHEMA_VERSION,
    RESEARCH_SYNTHESIS_MIGRATION_ID,
    RESEARCH_SYNTHESIS_SCHEMA_VERSION,
    REVIEW_QUEUE_SCHEMA_VERSION,
    SCHEMA_VERSION,
    SOURCE_ANALYSIS_SCHEMA_VERSION,
    SOURCE_ANCHOR_SCHEMA_VERSION,
    SOURCE_CAPTURE_SCHEMA_VERSION,
    SOURCE_DOCUMENT_STRUCTURE_SCHEMA_VERSION,
    SOURCE_KNOWLEDGE_SCHEMA_VERSION,
    SOURCE_PAGE_MAP_SCHEMA_VERSION,
    SOURCE_REPRESENTATION_SCHEMA_VERSION,
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
    "blob_records",
    "archive_replication_outbox",
    "archive_replication_watermark",
    "grounded_response_receipts",
    "key_slots",
    "protection_scopes",
    "protection_scope_keys",
    "protected_payloads",
    "protected_blob_envelopes",
    "protected_sources",
    "source_protection_transitions",
    "sources",
    "source_representations",
    "source_representation_pages",
    "source_representation_structures",
    "source_anchor_structures",
    "chunking_profiles",
    "source_anchors",
    "jobs",
    "checkpoints",
    "source_analyses",
    "source_analysis_work_items",
    "source_analysis_artifacts",
    "source_analysis_work_inputs",
    "source_extraction_result_snapshots",
    "source_analysis_knowledge_origins",
    "source_extractions",
    "source_extraction_evidence",
    "source_extraction_work_items",
    "source_extraction_artifacts",
    "source_extraction_work_inputs",
    "personal_memory_entries",
    "personal_memory_revisions",
    "research_scopes",
    "research_candidate_sets",
    "research_candidates",
    "research_work_items",
    "research_synthesis_work_items",
    "research_synthesis_work_inputs",
    "research_synthesis_artifacts",
    "research_synthesis_output_evidence",
    "research_synthesis_output_source_evidence",
    "research_results",
    "research_promotion_sets",
    "research_promotion_items",
    "research_knowledge_origins",
    "external_access_authorizations",
    "external_access_events",
    "external_source_captures",
    "resource_policy",
    "resource_runtime_snapshots",
    "backup_targets",
    "backup_snapshots",
    "backup_snapshot_pins",
    "deletion_ledger",
    "news_schema_metadata",
    "news_categories",
    "news_profiles",
    "news_sources",
    "news_source_categories",
    "news_runs",
    "news_discoveries",
    "news_events",
    "news_finding_assessments",
    "news_event_links",
    "news_period_runs",
    "news_digests",
    "news_profile_categories",
    "news_source_states",
    "news_event_members",
    "news_digest_items",
}


def _table_names(connection: sqlite3.Connection) -> set[str]:
    rows = connection.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table'"
    ).fetchall()
    return {str(row[0]) for row in rows}


def _strip_v36_deletion_ledger_for_legacy_fixture(
    connection: sqlite3.Connection,
) -> None:
    """Remove v36-only additions before declaring an older schema boundary."""

    # v39 is additive. Legacy fixtures that construct an
    # older boundary from a current database must remove
    # these child objects before removing their v32/v34
    # parents. Production migrations intentionally remain
    # fail-closed and do not use CREATE TABLE IF NOT EXISTS.
    connection.execute(
        "DROP TABLE IF EXISTS "
        "source_protection_representation_blobs"
    )
    connection.execute(
        "DROP TABLE IF EXISTS "
        "source_protected_semantic_payloads"
    )
    tables = _table_names(
        connection
    )

    if "deletion_ledger" in tables:
        connection.execute(
            "DROP TABLE deletion_ledger"
        )

    for table in (
        "backup_targets",
        "backup_snapshots",
    ):
        columns = {
            str(row[1])
            for row in connection.execute(
                f"PRAGMA table_info({table})"
            )
        }

        if (
            "deletion_ledger_watermark"
            in columns
        ):
            connection.execute(
                f"ALTER TABLE {table} "
                "DROP COLUMN deletion_ledger_watermark"
            )



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
        GROUNDED_RESPONSE_RECEIPT_MIGRATION_ID,
        SCHEMA_VERSION,
    )

    database.stop()


def test_v1_database_is_upgraded_without_losing_existing_actor(tmp_path) -> None:
    path = tmp_path / "athena.db"
    actor_id = new_uuid7()

    legacy = sqlite3.connect(path, autocommit=True)
    legacy.row_factory = sqlite3.Row

    _strip_v36_deletion_ledger_for_legacy_fixture(
        legacy
    )
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

    _strip_v36_deletion_ledger_for_legacy_fixture(
        legacy
    )
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

    _strip_v36_deletion_ledger_for_legacy_fixture(
        legacy
    )
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

    _strip_v36_deletion_ledger_for_legacy_fixture(
        legacy
    )
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

    _strip_v36_deletion_ledger_for_legacy_fixture(
        legacy
    )
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

    _strip_v36_deletion_ledger_for_legacy_fixture(
        legacy
    )
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

    _strip_v36_deletion_ledger_for_legacy_fixture(
        legacy
    )
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

    _strip_v36_deletion_ledger_for_legacy_fixture(
        legacy
    )
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

    _strip_v36_deletion_ledger_for_legacy_fixture(
        legacy
    )
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


def test_v10_database_is_upgraded_additively_to_source_capture(tmp_path) -> None:
    from athena.storage.schema import (
        _migrate_schema_v3_to_v4,
        _migrate_schema_v4_to_v5,
        _migrate_schema_v5_to_v6,
        _migrate_schema_v6_to_v7,
        _migrate_schema_v7_to_v8,
        _migrate_schema_v8_to_v9,
        _migrate_schema_v9_to_v10,
    )

    path = tmp_path / "athena.db"
    legacy = sqlite3.connect(path, autocommit=True)
    legacy.row_factory = sqlite3.Row

    _strip_v36_deletion_ledger_for_legacy_fixture(
        legacy
    )
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
    _migrate_schema_v9_to_v10(legacy)
    assert legacy.execute("PRAGMA user_version").fetchone()[0] == LOCAL_EMBEDDINGS_SCHEMA_VERSION
    assert "sources" not in _table_names(legacy)
    assert "blob_records" not in _table_names(legacy)
    legacy.close()

    database = SQLiteDatabase(path)
    database.start()
    assert database.connection.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION
    assert "sources" in _table_names(database.connection)
    assert "blob_records" in _table_names(database.connection)
    database.stop()


def test_v11_database_is_upgraded_additively_to_source_representations(tmp_path) -> None:
    from athena.storage.schema import (
        _migrate_schema_v3_to_v4,
        _migrate_schema_v4_to_v5,
        _migrate_schema_v5_to_v6,
        _migrate_schema_v6_to_v7,
        _migrate_schema_v7_to_v8,
        _migrate_schema_v8_to_v9,
        _migrate_schema_v9_to_v10,
        _migrate_schema_v10_to_v11,
    )

    path = tmp_path / "athena.db"
    legacy = sqlite3.connect(path, autocommit=True)
    legacy.row_factory = sqlite3.Row

    _strip_v36_deletion_ledger_for_legacy_fixture(
        legacy
    )
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
    _migrate_schema_v9_to_v10(legacy)
    _migrate_schema_v10_to_v11(legacy)
    assert legacy.execute("PRAGMA user_version").fetchone()[0] == SOURCE_CAPTURE_SCHEMA_VERSION
    assert "sources" in _table_names(legacy)
    assert "source_representations" not in _table_names(legacy)
    legacy.close()

    database = SQLiteDatabase(path)
    database.start()
    assert database.connection.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION
    assert "sources" in _table_names(database.connection)
    assert "source_representations" in _table_names(database.connection)
    database.stop()



def test_v12_database_is_upgraded_additively_to_chunking_profiles(tmp_path) -> None:
    from athena.storage.schema import (
        _migrate_schema_v3_to_v4,
        _migrate_schema_v4_to_v5,
        _migrate_schema_v5_to_v6,
        _migrate_schema_v6_to_v7,
        _migrate_schema_v7_to_v8,
        _migrate_schema_v8_to_v9,
        _migrate_schema_v9_to_v10,
        _migrate_schema_v10_to_v11,
        _migrate_schema_v11_to_v12,
    )

    path = tmp_path / "athena.db"
    legacy = sqlite3.connect(path, autocommit=True)
    legacy.row_factory = sqlite3.Row

    _strip_v36_deletion_ledger_for_legacy_fixture(
        legacy
    )
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
    _migrate_schema_v9_to_v10(legacy)
    _migrate_schema_v10_to_v11(legacy)
    _migrate_schema_v11_to_v12(legacy)
    assert legacy.execute("PRAGMA user_version").fetchone()[0] == SOURCE_REPRESENTATION_SCHEMA_VERSION
    assert "source_representations" in _table_names(legacy)
    assert "chunking_profiles" not in _table_names(legacy)
    legacy.close()

    database = SQLiteDatabase(path)
    database.start()
    assert database.connection.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION
    assert "source_representations" in _table_names(database.connection)
    assert "chunking_profiles" in _table_names(database.connection)
    assert "source_chunks" not in _table_names(database.connection)
    database.stop()


def test_v13_database_is_upgraded_additively_to_source_anchors(tmp_path) -> None:
    from athena.storage.schema import (
        SOURCE_CHUNK_PROFILE_SCHEMA_VERSION,
        _migrate_schema_v3_to_v4,
        _migrate_schema_v4_to_v5,
        _migrate_schema_v5_to_v6,
        _migrate_schema_v6_to_v7,
        _migrate_schema_v7_to_v8,
        _migrate_schema_v8_to_v9,
        _migrate_schema_v9_to_v10,
        _migrate_schema_v10_to_v11,
        _migrate_schema_v11_to_v12,
        _migrate_schema_v12_to_v13,
    )

    path = tmp_path / "athena.db"
    legacy = sqlite3.connect(path, autocommit=True)
    legacy.row_factory = sqlite3.Row

    _strip_v36_deletion_ledger_for_legacy_fixture(
        legacy
    )
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
    _migrate_schema_v9_to_v10(legacy)
    _migrate_schema_v10_to_v11(legacy)
    _migrate_schema_v11_to_v12(legacy)
    _migrate_schema_v12_to_v13(legacy)
    assert legacy.execute("PRAGMA user_version").fetchone()[0] == SOURCE_CHUNK_PROFILE_SCHEMA_VERSION
    assert "chunking_profiles" in _table_names(legacy)
    assert "source_anchors" not in _table_names(legacy)
    legacy.close()

    database = SQLiteDatabase(path)
    database.start()
    assert database.connection.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION
    assert "chunking_profiles" in _table_names(database.connection)
    assert "source_anchors" in _table_names(database.connection)
    database.stop()

def test_v14_database_is_upgraded_additively_to_durable_jobs(tmp_path) -> None:
    from athena.storage.schema import (
        _migrate_schema_v3_to_v4,
        _migrate_schema_v4_to_v5,
        _migrate_schema_v5_to_v6,
        _migrate_schema_v6_to_v7,
        _migrate_schema_v7_to_v8,
        _migrate_schema_v8_to_v9,
        _migrate_schema_v9_to_v10,
        _migrate_schema_v10_to_v11,
        _migrate_schema_v11_to_v12,
        _migrate_schema_v12_to_v13,
        _migrate_schema_v13_to_v14,
    )

    path = tmp_path / "athena.db"
    legacy = sqlite3.connect(path, autocommit=True)
    legacy.row_factory = sqlite3.Row

    _strip_v36_deletion_ledger_for_legacy_fixture(
        legacy
    )
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
    _migrate_schema_v9_to_v10(legacy)
    _migrate_schema_v10_to_v11(legacy)
    _migrate_schema_v11_to_v12(legacy)
    _migrate_schema_v12_to_v13(legacy)
    _migrate_schema_v13_to_v14(legacy)
    assert legacy.execute("PRAGMA user_version").fetchone()[0] == SOURCE_ANCHOR_SCHEMA_VERSION
    assert "source_anchors" in _table_names(legacy)
    assert "jobs" not in _table_names(legacy)
    legacy.close()

    database = SQLiteDatabase(path)
    database.start()
    assert database.connection.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION
    assert "jobs" in _table_names(database.connection)
    assert "checkpoints" in _table_names(database.connection)
    assert "source_representation_pages" in _table_names(database.connection)
    assert "source_representation_structures" in _table_names(database.connection)
    metadata = database.connection.execute(
        "SELECT last_migration_id FROM schema_metadata WHERE singleton_id = 1"
    ).fetchone()
    assert metadata is not None
    assert metadata["last_migration_id"] == GROUNDED_RESPONSE_RECEIPT_MIGRATION_ID
    database.stop()


def test_v15_database_is_upgraded_additively_to_pdf_page_map(tmp_path) -> None:
    from athena.storage.schema import (
        _migrate_schema_v3_to_v4,
        _migrate_schema_v4_to_v5,
        _migrate_schema_v5_to_v6,
        _migrate_schema_v6_to_v7,
        _migrate_schema_v7_to_v8,
        _migrate_schema_v8_to_v9,
        _migrate_schema_v9_to_v10,
        _migrate_schema_v10_to_v11,
        _migrate_schema_v11_to_v12,
        _migrate_schema_v12_to_v13,
        _migrate_schema_v13_to_v14,
        _migrate_schema_v14_to_v15,
    )

    path = tmp_path / "athena.db"
    legacy = sqlite3.connect(path, autocommit=True)
    legacy.row_factory = sqlite3.Row

    _strip_v36_deletion_ledger_for_legacy_fixture(
        legacy
    )
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
    _migrate_schema_v9_to_v10(legacy)
    _migrate_schema_v10_to_v11(legacy)
    _migrate_schema_v11_to_v12(legacy)
    _migrate_schema_v12_to_v13(legacy)
    _migrate_schema_v13_to_v14(legacy)
    _migrate_schema_v14_to_v15(legacy)
    assert legacy.execute("PRAGMA user_version").fetchone()[0] == DURABLE_JOBS_SCHEMA_VERSION
    assert "source_representation_pages" not in _table_names(legacy)
    legacy.close()

    database = SQLiteDatabase(path)
    database.start()
    assert database.connection.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION
    assert "source_representation_pages" in _table_names(database.connection)
    database.stop()


def test_v16_database_is_upgraded_additively_to_document_structure(tmp_path) -> None:
    from athena.storage.schema import (
        _migrate_schema_v3_to_v4,
        _migrate_schema_v4_to_v5,
        _migrate_schema_v5_to_v6,
        _migrate_schema_v6_to_v7,
        _migrate_schema_v7_to_v8,
        _migrate_schema_v8_to_v9,
        _migrate_schema_v9_to_v10,
        _migrate_schema_v10_to_v11,
        _migrate_schema_v11_to_v12,
        _migrate_schema_v12_to_v13,
        _migrate_schema_v13_to_v14,
        _migrate_schema_v14_to_v15,
        _migrate_schema_v15_to_v16,
    )

    path = tmp_path / "athena.db"
    legacy = sqlite3.connect(path, autocommit=True)
    legacy.row_factory = sqlite3.Row

    _strip_v36_deletion_ledger_for_legacy_fixture(
        legacy
    )
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
    _migrate_schema_v9_to_v10(legacy)
    _migrate_schema_v10_to_v11(legacy)
    _migrate_schema_v11_to_v12(legacy)
    _migrate_schema_v12_to_v13(legacy)
    _migrate_schema_v13_to_v14(legacy)
    _migrate_schema_v14_to_v15(legacy)
    _migrate_schema_v15_to_v16(legacy)
    assert legacy.execute("PRAGMA user_version").fetchone()[0] == SOURCE_PAGE_MAP_SCHEMA_VERSION
    assert "source_representation_pages" in _table_names(legacy)
    assert "source_representation_structures" not in _table_names(legacy)
    legacy.close()

    database = SQLiteDatabase(path)
    database.start()
    assert database.connection.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION
    assert "source_representation_structures" in _table_names(database.connection)
    assert "source_anchor_structures" in _table_names(database.connection)
    assert "source_analyses" in _table_names(database.connection)
    database.stop()


def test_v17_database_is_upgraded_additively_to_hierarchical_source_analysis(tmp_path) -> None:
    from athena.storage.schema import (
        _migrate_schema_v3_to_v4,
        _migrate_schema_v4_to_v5,
        _migrate_schema_v5_to_v6,
        _migrate_schema_v6_to_v7,
        _migrate_schema_v7_to_v8,
        _migrate_schema_v8_to_v9,
        _migrate_schema_v9_to_v10,
        _migrate_schema_v10_to_v11,
        _migrate_schema_v11_to_v12,
        _migrate_schema_v12_to_v13,
        _migrate_schema_v13_to_v14,
        _migrate_schema_v14_to_v15,
        _migrate_schema_v15_to_v16,
        _migrate_schema_v16_to_v17,
    )

    path = tmp_path / "athena.db"
    legacy = sqlite3.connect(path, autocommit=True)
    legacy.row_factory = sqlite3.Row

    _strip_v36_deletion_ledger_for_legacy_fixture(
        legacy
    )
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
    _migrate_schema_v9_to_v10(legacy)
    _migrate_schema_v10_to_v11(legacy)
    _migrate_schema_v11_to_v12(legacy)
    _migrate_schema_v12_to_v13(legacy)
    _migrate_schema_v13_to_v14(legacy)
    _migrate_schema_v14_to_v15(legacy)
    _migrate_schema_v15_to_v16(legacy)
    _migrate_schema_v16_to_v17(legacy)
    assert legacy.execute("PRAGMA user_version").fetchone()[0] == (
        SOURCE_DOCUMENT_STRUCTURE_SCHEMA_VERSION
    )
    assert "source_analyses" not in _table_names(legacy)
    legacy.close()

    database = SQLiteDatabase(path)
    database.start()
    assert database.connection.execute("PRAGMA user_version").fetchone()[0] == (
        SCHEMA_VERSION
    )
    tables = _table_names(database.connection)
    assert {
        "source_analyses",
        "source_analysis_work_items",
        "source_analysis_artifacts",
        "source_analysis_work_inputs",
    }.issubset(tables)
    metadata = database.connection.execute(
        "SELECT last_migration_id FROM schema_metadata WHERE singleton_id = 1"
    ).fetchone()
    assert metadata is not None
    assert metadata["last_migration_id"] == GROUNDED_RESPONSE_RECEIPT_MIGRATION_ID
    database.stop()


def test_v18_database_is_upgraded_additively_to_source_knowledge_promotion(tmp_path) -> None:
    from athena.storage.schema import (
        _migrate_schema_v3_to_v4,
        _migrate_schema_v4_to_v5,
        _migrate_schema_v5_to_v6,
        _migrate_schema_v6_to_v7,
        _migrate_schema_v7_to_v8,
        _migrate_schema_v8_to_v9,
        _migrate_schema_v9_to_v10,
        _migrate_schema_v10_to_v11,
        _migrate_schema_v11_to_v12,
        _migrate_schema_v12_to_v13,
        _migrate_schema_v13_to_v14,
        _migrate_schema_v14_to_v15,
        _migrate_schema_v15_to_v16,
        _migrate_schema_v16_to_v17,
        _migrate_schema_v17_to_v18,
    )

    path = tmp_path / "athena.db"
    legacy = sqlite3.connect(path, autocommit=True)
    legacy.row_factory = sqlite3.Row

    _strip_v36_deletion_ledger_for_legacy_fixture(
        legacy
    )
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
    _migrate_schema_v9_to_v10(legacy)
    _migrate_schema_v10_to_v11(legacy)
    _migrate_schema_v11_to_v12(legacy)
    _migrate_schema_v12_to_v13(legacy)
    _migrate_schema_v13_to_v14(legacy)
    _migrate_schema_v14_to_v15(legacy)
    _migrate_schema_v15_to_v16(legacy)
    _migrate_schema_v16_to_v17(legacy)
    _migrate_schema_v17_to_v18(legacy)
    assert legacy.execute("PRAGMA user_version").fetchone()[0] == SOURCE_ANALYSIS_SCHEMA_VERSION
    assert "source_extraction_result_snapshots" not in _table_names(legacy)
    legacy.close()

    database = SQLiteDatabase(path)
    database.start()
    assert database.connection.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION
    assert "source_extraction_result_snapshots" in _table_names(database.connection)
    assert "source_analysis_knowledge_origins" in _table_names(database.connection)
    metadata = database.connection.execute(
        "SELECT last_migration_id FROM schema_metadata WHERE singleton_id = 1"
    ).fetchone()
    assert metadata is not None
    assert metadata["last_migration_id"] == GROUNDED_RESPONSE_RECEIPT_MIGRATION_ID
    database.stop()


def test_v19_database_is_upgraded_additively_to_hierarchical_source_extraction(tmp_path) -> None:
    from athena.storage.schema import (
        _migrate_schema_v3_to_v4,
        _migrate_schema_v4_to_v5,
        _migrate_schema_v5_to_v6,
        _migrate_schema_v6_to_v7,
        _migrate_schema_v7_to_v8,
        _migrate_schema_v8_to_v9,
        _migrate_schema_v9_to_v10,
        _migrate_schema_v10_to_v11,
        _migrate_schema_v11_to_v12,
        _migrate_schema_v12_to_v13,
        _migrate_schema_v13_to_v14,
        _migrate_schema_v14_to_v15,
        _migrate_schema_v15_to_v16,
        _migrate_schema_v16_to_v17,
        _migrate_schema_v17_to_v18,
        _migrate_schema_v18_to_v19,
    )

    path = tmp_path / "athena.db"
    legacy = sqlite3.connect(path, autocommit=True)
    legacy.row_factory = sqlite3.Row

    _strip_v36_deletion_ledger_for_legacy_fixture(
        legacy
    )
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
    _migrate_schema_v9_to_v10(legacy)
    _migrate_schema_v10_to_v11(legacy)
    _migrate_schema_v11_to_v12(legacy)
    _migrate_schema_v12_to_v13(legacy)
    _migrate_schema_v13_to_v14(legacy)
    _migrate_schema_v14_to_v15(legacy)
    _migrate_schema_v15_to_v16(legacy)
    _migrate_schema_v16_to_v17(legacy)
    _migrate_schema_v17_to_v18(legacy)
    _migrate_schema_v18_to_v19(legacy)
    assert legacy.execute("PRAGMA user_version").fetchone()[0] == SOURCE_KNOWLEDGE_SCHEMA_VERSION
    assert "source_extractions" not in _table_names(legacy)
    legacy.close()

    database = SQLiteDatabase(path)
    database.start()
    assert database.connection.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION
    assert {
        "source_extractions",
        "source_extraction_evidence",
        "source_extraction_work_items",
        "source_extraction_artifacts",
        "source_extraction_work_inputs",
    }.issubset(_table_names(database.connection))
    metadata = database.connection.execute(
        "SELECT last_migration_id FROM schema_metadata WHERE singleton_id = 1"
    ).fetchone()
    assert metadata is not None
    assert metadata["last_migration_id"] == GROUNDED_RESPONSE_RECEIPT_MIGRATION_ID
    database.stop()


def test_v20_database_is_upgraded_additively_to_personal_memory(tmp_path) -> None:
    from athena.storage.schema import (
        _migrate_schema_v3_to_v4,
        _migrate_schema_v4_to_v5,
        _migrate_schema_v5_to_v6,
        _migrate_schema_v6_to_v7,
        _migrate_schema_v7_to_v8,
        _migrate_schema_v8_to_v9,
        _migrate_schema_v9_to_v10,
        _migrate_schema_v10_to_v11,
        _migrate_schema_v11_to_v12,
        _migrate_schema_v12_to_v13,
        _migrate_schema_v13_to_v14,
        _migrate_schema_v14_to_v15,
        _migrate_schema_v15_to_v16,
        _migrate_schema_v16_to_v17,
        _migrate_schema_v17_to_v18,
        _migrate_schema_v18_to_v19,
        _migrate_schema_v19_to_v20,
    )

    path = tmp_path / "athena.db"
    legacy = sqlite3.connect(path, autocommit=True)
    legacy.row_factory = sqlite3.Row

    _strip_v36_deletion_ledger_for_legacy_fixture(
        legacy
    )
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
    _migrate_schema_v9_to_v10(legacy)
    _migrate_schema_v10_to_v11(legacy)
    _migrate_schema_v11_to_v12(legacy)
    _migrate_schema_v12_to_v13(legacy)
    _migrate_schema_v13_to_v14(legacy)
    _migrate_schema_v14_to_v15(legacy)
    _migrate_schema_v15_to_v16(legacy)
    _migrate_schema_v16_to_v17(legacy)
    _migrate_schema_v17_to_v18(legacy)
    _migrate_schema_v18_to_v19(legacy)
    _migrate_schema_v19_to_v20(legacy)
    assert legacy.execute("PRAGMA user_version").fetchone()[0] == (
        HIERARCHICAL_SOURCE_EXTRACTION_SCHEMA_VERSION
    )
    assert "personal_memory_entries" not in _table_names(legacy)
    legacy.close()

    database = SQLiteDatabase(path)
    database.start()
    assert database.connection.execute("PRAGMA user_version").fetchone()[0] == (
        SCHEMA_VERSION
    )
    assert {
        "personal_memory_entries",
        "personal_memory_revisions",
    }.issubset(_table_names(database.connection))
    metadata = database.connection.execute(
        "SELECT last_migration_id FROM schema_metadata WHERE singleton_id = 1"
    ).fetchone()
    assert metadata is not None
    assert metadata["last_migration_id"] == GROUNDED_RESPONSE_RECEIPT_MIGRATION_ID
    database.stop()


def test_v21_database_is_upgraded_additively_to_exhaustive_research(tmp_path) -> None:
    from athena.storage.schema import (
        _migrate_schema_v3_to_v4,
        _migrate_schema_v4_to_v5,
        _migrate_schema_v5_to_v6,
        _migrate_schema_v6_to_v7,
        _migrate_schema_v7_to_v8,
        _migrate_schema_v8_to_v9,
        _migrate_schema_v9_to_v10,
        _migrate_schema_v10_to_v11,
        _migrate_schema_v11_to_v12,
        _migrate_schema_v12_to_v13,
        _migrate_schema_v13_to_v14,
        _migrate_schema_v14_to_v15,
        _migrate_schema_v15_to_v16,
        _migrate_schema_v16_to_v17,
        _migrate_schema_v17_to_v18,
        _migrate_schema_v18_to_v19,
        _migrate_schema_v19_to_v20,
        _migrate_schema_v20_to_v21,
    )

    path = tmp_path / "athena.db"
    legacy = sqlite3.connect(path, autocommit=True)
    legacy.row_factory = sqlite3.Row

    _strip_v36_deletion_ledger_for_legacy_fixture(
        legacy
    )
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
    _migrate_schema_v9_to_v10(legacy)
    _migrate_schema_v10_to_v11(legacy)
    _migrate_schema_v11_to_v12(legacy)
    _migrate_schema_v12_to_v13(legacy)
    _migrate_schema_v13_to_v14(legacy)
    _migrate_schema_v14_to_v15(legacy)
    _migrate_schema_v15_to_v16(legacy)
    _migrate_schema_v16_to_v17(legacy)
    _migrate_schema_v17_to_v18(legacy)
    _migrate_schema_v18_to_v19(legacy)
    _migrate_schema_v19_to_v20(legacy)
    _migrate_schema_v20_to_v21(legacy)
    assert legacy.execute("PRAGMA user_version").fetchone()[0] == (
        PERSONAL_MEMORY_SCHEMA_VERSION
    )
    metadata = legacy.execute(
        "SELECT last_migration_id FROM schema_metadata WHERE singleton_id = 1"
    ).fetchone()
    assert metadata is not None
    assert metadata["last_migration_id"] == PERSONAL_MEMORY_MIGRATION_ID
    assert "research_scopes" not in _table_names(legacy)
    legacy.close()

    database = SQLiteDatabase(path)
    database.start()
    assert database.connection.execute("PRAGMA user_version").fetchone()[0] == (
        SCHEMA_VERSION
    )
    assert {
        "research_scopes",
        "research_candidate_sets",
        "research_candidates",
        "research_work_items",
    }.issubset(_table_names(database.connection))
    metadata = database.connection.execute(
        "SELECT last_migration_id FROM schema_metadata WHERE singleton_id = 1"
    ).fetchone()
    assert metadata is not None
    assert metadata["last_migration_id"] == GROUNDED_RESPONSE_RECEIPT_MIGRATION_ID
    database.stop()


def test_v22_database_is_upgraded_additively_to_research_orchestration(
    tmp_path,
) -> None:
    from athena.storage.schema import (
        _migrate_schema_v3_to_v4,
        _migrate_schema_v4_to_v5,
        _migrate_schema_v5_to_v6,
        _migrate_schema_v6_to_v7,
        _migrate_schema_v7_to_v8,
        _migrate_schema_v8_to_v9,
        _migrate_schema_v9_to_v10,
        _migrate_schema_v10_to_v11,
        _migrate_schema_v11_to_v12,
        _migrate_schema_v12_to_v13,
        _migrate_schema_v13_to_v14,
        _migrate_schema_v14_to_v15,
        _migrate_schema_v15_to_v16,
        _migrate_schema_v16_to_v17,
        _migrate_schema_v17_to_v18,
        _migrate_schema_v18_to_v19,
        _migrate_schema_v19_to_v20,
        _migrate_schema_v20_to_v21,
        _migrate_schema_v21_to_v22,
    )

    path = tmp_path / "athena.db"
    legacy = sqlite3.connect(path, autocommit=True)
    legacy.row_factory = sqlite3.Row

    _strip_v36_deletion_ledger_for_legacy_fixture(
        legacy
    )
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
    _migrate_schema_v9_to_v10(legacy)
    _migrate_schema_v10_to_v11(legacy)
    _migrate_schema_v11_to_v12(legacy)
    _migrate_schema_v12_to_v13(legacy)
    _migrate_schema_v13_to_v14(legacy)
    _migrate_schema_v14_to_v15(legacy)
    _migrate_schema_v15_to_v16(legacy)
    _migrate_schema_v16_to_v17(legacy)
    _migrate_schema_v17_to_v18(legacy)
    _migrate_schema_v18_to_v19(legacy)
    _migrate_schema_v19_to_v20(legacy)
    _migrate_schema_v20_to_v21(legacy)
    _migrate_schema_v21_to_v22(legacy)
    assert legacy.execute("PRAGMA user_version").fetchone()[0] == (
        EXHAUSTIVE_RESEARCH_SCHEMA_VERSION
    )
    assert "source_processing_job_id" not in {
        str(row[1])
        for row in legacy.execute("PRAGMA table_info(research_work_items)")
    }
    legacy.close()

    database = SQLiteDatabase(path)
    database.start()
    assert database.connection.execute("PRAGMA user_version").fetchone()[0] == (
        SCHEMA_VERSION
    )
    assert "source_processing_job_id" in {
        str(row[1])
        for row in database.connection.execute(
            "PRAGMA table_info(research_work_items)"
        )
    }
    scope_columns = {
        str(row[1])
        for row in database.connection.execute("PRAGMA table_info(research_scopes)")
    }
    assert {
        "model_id",
        "model_signature_id",
        "model_signature_sha256",
        "effective_context_limit",
        "output_reserve",
        "safety_margin",
        "token_estimator",
        "max_hierarchy_depth",
    }.issubset(scope_columns)
    metadata = database.connection.execute(
        "SELECT last_migration_id FROM schema_metadata WHERE singleton_id = 1"
    ).fetchone()
    assert metadata is not None
    assert metadata["last_migration_id"] == GROUNDED_RESPONSE_RECEIPT_MIGRATION_ID
    database.stop()


def test_v23_database_is_upgraded_additively_to_research_synthesis(tmp_path) -> None:
    from athena.storage.schema import (
        _migrate_schema_v3_to_v4,
        _migrate_schema_v4_to_v5,
        _migrate_schema_v5_to_v6,
        _migrate_schema_v6_to_v7,
        _migrate_schema_v7_to_v8,
        _migrate_schema_v8_to_v9,
        _migrate_schema_v9_to_v10,
        _migrate_schema_v10_to_v11,
        _migrate_schema_v11_to_v12,
        _migrate_schema_v12_to_v13,
        _migrate_schema_v13_to_v14,
        _migrate_schema_v14_to_v15,
        _migrate_schema_v15_to_v16,
        _migrate_schema_v16_to_v17,
        _migrate_schema_v17_to_v18,
        _migrate_schema_v18_to_v19,
        _migrate_schema_v19_to_v20,
        _migrate_schema_v20_to_v21,
        _migrate_schema_v21_to_v22,
        _migrate_schema_v22_to_v23,
    )

    path = tmp_path / "athena.db"
    legacy = sqlite3.connect(path, autocommit=True)
    legacy.row_factory = sqlite3.Row

    _strip_v36_deletion_ledger_for_legacy_fixture(
        legacy
    )
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
    _migrate_schema_v9_to_v10(legacy)
    _migrate_schema_v10_to_v11(legacy)
    _migrate_schema_v11_to_v12(legacy)
    _migrate_schema_v12_to_v13(legacy)
    _migrate_schema_v13_to_v14(legacy)
    _migrate_schema_v14_to_v15(legacy)
    _migrate_schema_v15_to_v16(legacy)
    _migrate_schema_v16_to_v17(legacy)
    _migrate_schema_v17_to_v18(legacy)
    _migrate_schema_v18_to_v19(legacy)
    _migrate_schema_v19_to_v20(legacy)
    _migrate_schema_v20_to_v21(legacy)
    _migrate_schema_v21_to_v22(legacy)
    _migrate_schema_v22_to_v23(legacy)
    assert legacy.execute("PRAGMA user_version").fetchone()[0] == (
        RESEARCH_ORCHESTRATION_SCHEMA_VERSION
    )
    assert "research_synthesis_work_items" not in _table_names(legacy)
    metadata = legacy.execute(
        "SELECT last_migration_id FROM schema_metadata WHERE singleton_id = 1"
    ).fetchone()
    assert metadata is not None
    assert metadata["last_migration_id"] == RESEARCH_ORCHESTRATION_MIGRATION_ID
    legacy.close()

    database = SQLiteDatabase(path)
    database.start()
    connection = database.connection
    assert connection.execute("PRAGMA user_version").fetchone()[0] == (
        SCHEMA_VERSION
    )
    assert {
        "research_synthesis_work_items",
        "research_synthesis_work_inputs",
        "research_synthesis_artifacts",
        "research_synthesis_output_evidence",
        "research_results",
    }.issubset(_table_names(connection))
    metadata = connection.execute(
        "SELECT last_migration_id, minimum_reader_version "
        "FROM schema_metadata WHERE singleton_id = 1"
    ).fetchone()
    assert metadata is not None
    assert metadata["last_migration_id"] == GROUNDED_RESPONSE_RECEIPT_MIGRATION_ID
    assert metadata["minimum_reader_version"] == SCHEMA_VERSION
    assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
    database.stop()


def test_v26_news_schema_preserves_v25_operational_foundation(tmp_path) -> None:
    assert RESEARCH_SYNTHESIS_SCHEMA_VERSION == 24
    assert RESEARCH_SYNTHESIS_MIGRATION_ID == "0024_exhaustive_research_synthesis"
    assert CONSOLIDATED_OPERATIONS_SCHEMA_VERSION == 25
    assert NEWS_SYSTEM_SCHEMA_VERSION == 26
    assert NEWS_SYSTEM_MIGRATION_ID == "0026_news_system"
    assert NEWS_EVENT_STRUCTURE_SCHEMA_VERSION == 27
    assert NEWS_EVENT_STRUCTURE_MIGRATION_ID == "0027_news_event_structure"
    assert NEWS_OPERATIONAL_SCHEMA_VERSION == 28
    assert NEWS_OPERATIONAL_MIGRATION_ID == "0028_news_operational_completion"
    database = SQLiteDatabase(tmp_path / "athena.db")
    database.start()
    connection = database.connection
    assert connection.execute("PRAGMA user_version").fetchone()[0] == (
        SCHEMA_VERSION
    )
    policy = connection.execute(
        """
        SELECT mode, ram_headroom_bytes, disk_headroom_bytes
        FROM resource_policy
        WHERE singleton_id = 1
        """
    ).fetchone()
    assert policy is not None
    assert policy["mode"] == "balanced"
    assert int(policy["ram_headroom_bytes"]) > 0
    assert int(policy["disk_headroom_bytes"]) > 0
    news_tables = {
        "news_schema_metadata", "news_categories", "news_profiles",
        "news_sources", "news_source_categories", "news_runs",
        "news_discoveries", "news_events", "news_event_links",
        "news_period_runs", "news_digests", "news_profile_categories",
        "news_source_states", "news_event_members", "news_digest_items",
        "news_finding_assessments",
    }
    assert news_tables.issubset(_table_names(connection))
    news_meta = connection.execute(
        "SELECT schema_version, schema_id FROM news_schema_metadata WHERE singleton_id = 1"
    ).fetchone()
    assert news_meta is not None
    assert tuple(news_meta) == (4, "news-domain-v4")
    assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
    database.stop()


def test_v28_database_is_upgraded_additively_to_precise_research_provenance(
    tmp_path,
) -> None:
    path = tmp_path / "athena.db"

    latest = SQLiteDatabase(path)
    latest.start()
    latest.stop()

    legacy = sqlite3.connect(
        path,
        autocommit=True,
    )

    # This fixture starts from the current schema and
    # reconstructs an older boundary. Remove additive
    # v39 child state before removing older parents or
    # rewriting schema metadata. Production migration
    # behavior intentionally remains fail-closed.
    legacy.execute(
        "DROP TABLE IF EXISTS "
        "grounded_response_receipts"
    )
    legacy.execute(
        "DROP TABLE IF EXISTS "
        "source_protection_representation_blobs"
    )
    legacy.execute(
        "DROP TABLE IF EXISTS "
        "source_protected_semantic_payloads"
    )
    legacy.row_factory = sqlite3.Row

    _strip_v36_deletion_ledger_for_legacy_fixture(
        legacy
    )

    # This test creates the latest database first and then
    # reconstructs an older schema boundary. Remove every
    # additive v31 object before declaring the DB v28/v29.
    # Reconstruct a pre-v32 boundary: remove every additive
    # Protected-Content object before downgrading metadata.
    legacy.execute("DROP TRIGGER trg_source_protection_transition_block_blob_reuse")
    legacy.execute("DROP TRIGGER trg_source_protection_transition_block_source_update")
    legacy.execute("DROP TRIGGER trg_source_protection_transition_block_source_delete")
    legacy.execute("DROP TRIGGER trg_source_protection_transition_block_representation")
    legacy.execute("DROP TRIGGER trg_source_protection_transition_block_old_blob_update")
    legacy.execute("DROP TRIGGER trg_source_protection_transition_block_old_blob_delete")
    legacy.execute("DROP TABLE source_protection_transitions")
    legacy.execute(
        "DROP TABLE protected_sources"
    )

    legacy.execute(
        "DROP TABLE "
        "protected_blob_envelopes"
    )
    legacy.execute(
        "DROP TABLE "
        "protected_payloads"
    )
    legacy.execute(
        "DROP TABLE "
        "protection_scope_keys"
    )
    legacy.execute(
        "DROP TABLE "
        "protection_scopes"
    )
    legacy.execute(
        "DROP TABLE "
        "key_slots"
    )

    legacy.execute(
        "DROP TRIGGER "
        "trg_blob_records_archive_replication_outbox"
    )
    legacy.execute(
        "DROP TABLE archive_replication_watermark"
    )
    legacy.execute(
        "DROP TABLE archive_replication_outbox"
    )

    legacy.execute(
        "DROP TABLE news_finding_assessments"
    )
    legacy.execute(
        "DROP INDEX "
        "uq_news_events_run_finding_ordinal"
    )
    legacy.execute(
        "ALTER TABLE news_events "
        "DROP COLUMN finding_ordinal"
    )
    legacy.execute(
        """
        UPDATE news_schema_metadata
        SET schema_version = 3,
            schema_id = 'news-domain-v3'
        WHERE singleton_id = 1
        """
    )

    legacy.execute(
        "DROP TABLE "
        "research_synthesis_output_source_evidence"
    )

    legacy.execute(
        """
        UPDATE schema_metadata
        SET schema_version = ?,
            last_migration_id = ?,
            minimum_reader_version = ?
        WHERE singleton_id = 1
        """,
        (
            NEWS_OPERATIONAL_SCHEMA_VERSION,
            NEWS_OPERATIONAL_MIGRATION_ID,
            NEWS_OPERATIONAL_SCHEMA_VERSION,
        ),
    )

    legacy.execute(
        f"PRAGMA user_version = "
        f"{NEWS_OPERATIONAL_SCHEMA_VERSION}"
    )

    legacy.close()

    upgraded = SQLiteDatabase(path)
    upgraded.start()

    connection = upgraded.connection

    assert (
        connection.execute(
            "PRAGMA user_version"
        ).fetchone()[0]
        == SCHEMA_VERSION
    )

    assert (
        "research_synthesis_output_source_evidence"
        in _table_names(connection)
    )

    provenance_columns = {
        str(row[1])
        for row in connection.execute(
            "PRAGMA table_info("
            "research_synthesis_output_source_evidence"
            ")"
        )
    }

    assert provenance_columns == {
        "artifact_id",
        "output_kind",
        "output_ordinal",
        "source_analysis_artifact_id",
    }

    referenced_tables = {
        str(row[2])
        for row in connection.execute(
            "PRAGMA foreign_key_list("
            "research_synthesis_output_source_evidence"
            ")"
        )
    }

    assert {
        "research_synthesis_artifacts",
        "source_analysis_artifacts",
    } <= referenced_tables

    assert (
        "news_finding_assessments"
        in _table_names(connection)
    )

    event_columns = {
        str(row[1])
        for row in connection.execute(
            "PRAGMA table_info(news_events)"
        )
    }

    assert "finding_ordinal" in event_columns

    metadata = connection.execute(
        """
        SELECT
            schema_version,
            last_migration_id,
            minimum_reader_version
        FROM schema_metadata
        WHERE singleton_id = 1
        """
    ).fetchone()

    assert metadata is not None

    assert tuple(metadata) == (
        SCHEMA_VERSION,
        GROUNDED_RESPONSE_RECEIPT_MIGRATION_ID,
        SCHEMA_VERSION,
    )

    news_metadata = connection.execute(
        """
        SELECT schema_version, schema_id
        FROM news_schema_metadata
        WHERE singleton_id = 1
        """
    ).fetchone()

    assert news_metadata is not None
    assert tuple(news_metadata) == (
        4,
        "news-domain-v4",
    )

    assert connection.execute(
        "PRAGMA foreign_key_check"
    ).fetchall() == []

    upgraded.stop()


def test_v29_database_is_upgraded_additively_to_news_event_eligibility(
    tmp_path,
) -> None:
    path = tmp_path / "athena.db"

    latest = SQLiteDatabase(path)
    latest.start()
    latest.stop()

    legacy = sqlite3.connect(
        path,
        autocommit=True,
    )

    # This fixture starts from the current schema and
    # reconstructs an older boundary. Remove additive
    # v39 child state before removing older parents or
    # rewriting schema metadata. Production migration
    # behavior intentionally remains fail-closed.
    legacy.execute(
        "DROP TABLE IF EXISTS "
        "grounded_response_receipts"
    )
    legacy.execute(
        "DROP TABLE IF EXISTS "
        "source_protection_representation_blobs"
    )
    legacy.execute(
        "DROP TABLE IF EXISTS "
        "source_protected_semantic_payloads"
    )
    legacy.row_factory = sqlite3.Row

    _strip_v36_deletion_ledger_for_legacy_fixture(
        legacy
    )

    # This test creates the latest database first and then
    # reconstructs an older schema boundary. Remove every
    # additive v31 object before declaring the DB v28/v29.
    # Reconstruct a pre-v32 boundary: remove every additive
    # Protected-Content object before downgrading metadata.
    legacy.execute("DROP TRIGGER trg_source_protection_transition_block_blob_reuse")
    legacy.execute("DROP TRIGGER trg_source_protection_transition_block_source_update")
    legacy.execute("DROP TRIGGER trg_source_protection_transition_block_source_delete")
    legacy.execute("DROP TRIGGER trg_source_protection_transition_block_representation")
    legacy.execute("DROP TRIGGER trg_source_protection_transition_block_old_blob_update")
    legacy.execute("DROP TRIGGER trg_source_protection_transition_block_old_blob_delete")
    legacy.execute("DROP TABLE source_protection_transitions")
    legacy.execute(
        "DROP TABLE protected_sources"
    )

    legacy.execute(
        "DROP TABLE "
        "protected_blob_envelopes"
    )
    legacy.execute(
        "DROP TABLE "
        "protected_payloads"
    )
    legacy.execute(
        "DROP TABLE "
        "protection_scope_keys"
    )
    legacy.execute(
        "DROP TABLE "
        "protection_scopes"
    )
    legacy.execute(
        "DROP TABLE "
        "key_slots"
    )

    legacy.execute(
        "DROP TRIGGER "
        "trg_blob_records_archive_replication_outbox"
    )
    legacy.execute(
        "DROP TABLE archive_replication_watermark"
    )
    legacy.execute(
        "DROP TABLE archive_replication_outbox"
    )

    legacy.execute(
        "DROP TABLE news_finding_assessments"
    )
    legacy.execute(
        "DROP INDEX "
        "uq_news_events_run_finding_ordinal"
    )
    legacy.execute(
        "ALTER TABLE news_events "
        "DROP COLUMN finding_ordinal"
    )
    legacy.execute(
        """
        UPDATE news_schema_metadata
        SET schema_version = 3,
            schema_id = 'news-domain-v3'
        WHERE singleton_id = 1
        """
    )

    legacy.execute(
        """
        UPDATE schema_metadata
        SET schema_version = ?,
            last_migration_id = ?,
            minimum_reader_version = ?
        WHERE singleton_id = 1
        """,
        (
            PRECISE_RESEARCH_PROVENANCE_SCHEMA_VERSION,
            PRECISE_RESEARCH_PROVENANCE_MIGRATION_ID,
            PRECISE_RESEARCH_PROVENANCE_SCHEMA_VERSION,
        ),
    )

    legacy.execute(
        f"PRAGMA user_version = "
        f"{PRECISE_RESEARCH_PROVENANCE_SCHEMA_VERSION}"
    )

    assert (
        "research_synthesis_output_source_evidence"
        in _table_names(legacy)
    )

    assert (
        "news_finding_assessments"
        not in _table_names(legacy)
    )

    legacy.close()

    upgraded = SQLiteDatabase(path)
    upgraded.start()

    connection = upgraded.connection

    assert (
        connection.execute(
            "PRAGMA user_version"
        ).fetchone()[0]
        == SCHEMA_VERSION
    )

    assert (
        "news_finding_assessments"
        in _table_names(connection)
    )

    event_columns = {
        str(row[1])
        for row in connection.execute(
            "PRAGMA table_info(news_events)"
        )
    }

    assert "finding_ordinal" in event_columns

    metadata = connection.execute(
        """
        SELECT
            schema_version,
            last_migration_id,
            minimum_reader_version
        FROM schema_metadata
        WHERE singleton_id = 1
        """
    ).fetchone()

    assert metadata is not None

    assert tuple(metadata) == (
        SCHEMA_VERSION,
        GROUNDED_RESPONSE_RECEIPT_MIGRATION_ID,
        SCHEMA_VERSION,
    )

    news_metadata = connection.execute(
        """
        SELECT schema_version, schema_id
        FROM news_schema_metadata
        WHERE singleton_id = 1
        """
    ).fetchone()

    assert news_metadata is not None
    assert tuple(news_metadata) == (
        4,
        "news-domain-v4",
    )

    assert connection.execute(
        "PRAGMA foreign_key_check"
    ).fetchall() == []

    upgraded.stop()



def test_v36_operational_error_text_is_sanitized_without_changing_resume_state(
    tmp_path,
) -> None:
    path = tmp_path / "athena.db"

    current = SQLiteDatabase(
        path
    )
    current.start()
    current.stop()

    legacy = sqlite3.connect(
        path,
        autocommit=True,
    )
    legacy.row_factory = sqlite3.Row

    actor_id = new_uuid7()
    run_id = new_uuid7()
    job_id = new_uuid7()
    checkpoint_id = new_uuid7()

    secret = (
        "ATHENA_P1_04_MIGRATION_SECRET_"
        "8A3CC681"
    )

    legacy.execute(
        """
        INSERT INTO actors (
            actor_id,
            actor_type,
            display_name,
            plugin_id,
            created_at_us,
            active
        ) VALUES (?, 'user', NULL, NULL, 1, 1)
        """,
        (
            uuid_to_blob(
                actor_id
            ),
        ),
    )

    legacy.execute(
        """
        INSERT INTO processing_runs (
            processing_run_id,
            run_type,
            started_at_us,
            finished_at_us,
            status,
            trigger_actor_id,
            pipeline_version,
            input_snapshot_json,
            configuration_hash,
            model_signature_id,
            prompt_template_id,
            prompt_template_version,
            error_detail
        ) VALUES (
            ?, 'migration-test',
            10, 11, 'failed',
            ?, 'test-v1', '{}', ?,
            NULL, NULL, NULL, ?
        )
        """,
        (
            uuid_to_blob(
                run_id
            ),
            uuid_to_blob(
                actor_id
            ),
            bytes(
                [17]
            )
            * 32,
            (
                "RuntimeError: "
                + secret
            ),
        ),
    )

    legacy.execute(
        """
        INSERT INTO jobs (
            job_id,
            job_type,
            created_at_us,
            created_by_actor_id,
            priority,
            state,
            requested_scope_json,
            processing_run_id,
            current_stage,
            last_checkpoint_id,
            retry_count,
            next_run_at_us,
            blocked_reason,
            pinned_configuration_json,
            protection_scope_id,
            protected_payload_id,
            worker_id,
            lease_token,
            lease_acquired_at_us,
            lease_expires_at_us,
            heartbeat_at_us,
            fencing_sequence,
            updated_at_us
        ) VALUES (
            ?, 'source.extract',
            20, ?, 3, 'failed',
            '{"stable":"scope"}',
            NULL,
            'stable_stage',
            NULL,
            4,
            123456789,
            ?,
            '{"stable":"config"}',
            NULL, NULL,
            NULL, NULL, NULL, NULL, NULL,
            7,
            30
        )
        """,
        (
            uuid_to_blob(
                job_id
            ),
            uuid_to_blob(
                actor_id
            ),
            "source_processing:SourceProcessingJobError",
        ),
    )

    original_output = {
        "error": (
            "ProviderRefusalError: "
            + secret
        ),
        "stable": {
            "resume_value": 42,
            "error": "semantic error must remain verbatim",
            "detail": "semantic detail must remain verbatim",
        },
    }

    legacy.execute(
        """
        INSERT INTO checkpoints (
            checkpoint_id,
            job_id,
            processing_stage_id,
            created_at_us,
            progress_state_json,
            last_confirmed_input_json,
            last_confirmed_output_json,
            resume_metadata_json,
            commit_id,
            protection_scope_id,
            protected_payload_id,
            fencing_sequence
        ) VALUES (
            ?, ?, NULL, 25,
            '{"progress":7}',
            '{"input":"stable"}',
            ?,
            '{"resume":"stable"}',
            NULL, NULL, NULL, 7
        )
        """,
        (
            uuid_to_blob(
                checkpoint_id
            ),
            uuid_to_blob(
                job_id
            ),
            json.dumps(
                original_output,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ),
        ),
    )

    legacy.execute(
        """
        UPDATE jobs
        SET last_checkpoint_id = ?
        WHERE job_id = ?
        """,
        (
            uuid_to_blob(
                checkpoint_id
            ),
            uuid_to_blob(
                job_id
            ),
        ),
    )

    # Remove additive v39 objects before declaring
    # this current database to be an older schema.
    # The production migration remains fail-closed.
    legacy.execute(
        "DROP TABLE IF EXISTS "
        "grounded_response_receipts"
    )
    legacy.execute(
        "DROP TABLE IF EXISTS "
        "source_protection_representation_blobs"
    )
    legacy.execute(
        "DROP TABLE IF EXISTS "
        "source_protected_semantic_payloads"
    )

    legacy.execute(
        """
        UPDATE schema_metadata
        SET schema_version = ?,
            last_migration_id = ?,
            minimum_reader_version = ?
        WHERE singleton_id = 1
        """,
        (
            DELETION_LEDGER_SCHEMA_VERSION,
            DELETION_LEDGER_MIGRATION_ID,
            DELETION_LEDGER_SCHEMA_VERSION,
        ),
    )

    legacy.execute(
        f"PRAGMA user_version = "
        f"{DELETION_LEDGER_SCHEMA_VERSION}"
    )

    legacy.close()

    upgraded = SQLiteDatabase(
        path
    )
    upgraded.start()

    connection = upgraded.connection

    assert (
        connection.execute(
            "PRAGMA user_version"
        ).fetchone()[0]
        == SCHEMA_VERSION
    )

    metadata = connection.execute(
        """
        SELECT
            schema_version,
            last_migration_id,
            minimum_reader_version
        FROM schema_metadata
        WHERE singleton_id = 1
        """
    ).fetchone()

    assert metadata is not None

    assert tuple(
        metadata
    ) == (
        SCHEMA_VERSION,
        GROUNDED_RESPONSE_RECEIPT_MIGRATION_ID,
        SCHEMA_VERSION,
    )

    run = connection.execute(
        """
        SELECT error_detail
        FROM processing_runs
        WHERE processing_run_id = ?
        """,
        (
            uuid_to_blob(
                run_id
            ),
        ),
    ).fetchone()

    assert run is not None
    assert (
        run["error_detail"]
        == "RuntimeError"
    )

    job = connection.execute(
        """
        SELECT
            state,
            current_stage,
            retry_count,
            next_run_at_us,
            blocked_reason,
            requested_scope_json,
            pinned_configuration_json,
            last_checkpoint_id,
            fencing_sequence
        FROM jobs
        WHERE job_id = ?
        """,
        (
            uuid_to_blob(
                job_id
            ),
        ),
    ).fetchone()

    assert job is not None

    assert tuple(
        job
    ) == (
        "failed",
        "stable_stage",
        4,
        123456789,
        "source_processing:SourceProcessingJobError",
        '{"stable":"scope"}',
        '{"stable":"config"}',
        uuid_to_blob(
            checkpoint_id
        ),
        7,
    )

    checkpoint = connection.execute(
        """
        SELECT
            progress_state_json,
            last_confirmed_input_json,
            last_confirmed_output_json,
            resume_metadata_json,
            fencing_sequence
        FROM checkpoints
        WHERE checkpoint_id = ?
        """,
        (
            uuid_to_blob(
                checkpoint_id
            ),
        ),
    ).fetchone()

    assert checkpoint is not None

    assert checkpoint[
        "progress_state_json"
    ] == '{"progress":7}'

    assert checkpoint[
        "last_confirmed_input_json"
    ] == '{"input":"stable"}'

    assert checkpoint[
        "resume_metadata_json"
    ] == '{"resume":"stable"}'

    migrated_output = json.loads(
        checkpoint[
            "last_confirmed_output_json"
        ]
    )

    assert migrated_output == {
        "error": "ProviderRefusalError",
        "stable": {
            "resume_value": 42,
            "error": "semantic error must remain verbatim",
            "detail": "semantic detail must remain verbatim",
        },
    }

    assert checkpoint[
        "fencing_sequence"
    ] == 7

    database_text = " ".join(
        str(
            row[0]
        )
        for row in connection.execute(
            """
            SELECT error_detail
            FROM processing_runs
            WHERE error_detail IS NOT NULL
            """
        ).fetchall()
    )

    assert secret not in database_text

    assert connection.execute(
        "PRAGMA foreign_key_check"
    ).fetchall() == []

    upgraded.stop()

    # Opening v37 again must be a pure verification path, not another migration.
    reopened = SQLiteDatabase(
        path
    )
    reopened.start()

    assert (
        reopened.connection.execute(
            "PRAGMA user_version"
        ).fetchone()[0]
        == SCHEMA_VERSION
    )

    reopened.stop()
