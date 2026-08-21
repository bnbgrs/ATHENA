"""ATHENA SQLite schema bootstrap, additive migrations, and compatibility checks."""

from __future__ import annotations

import sqlite3

from athena.news.schema import (
    migrate_news_schema_v25_to_v26,
    migrate_news_schema_v26_to_v27,
    migrate_news_schema_v27_to_v28,
    migrate_news_schema_v29_to_v30,
)
from athena.storage.schema_contract import (
    ARCHIVE_REPLICATION_MIGRATION_ID as ARCHIVE_REPLICATION_MIGRATION_ID,
)
from athena.storage.schema_contract import (
    ARCHIVE_REPLICATION_SCHEMA_VERSION as ARCHIVE_REPLICATION_SCHEMA_VERSION,
)
from athena.storage.schema_contract import (
    ATHENA_APPLICATION_ID as ATHENA_APPLICATION_ID,
)
from athena.storage.schema_contract import (
    BACKUP_RETENTION_MIGRATION_ID as BACKUP_RETENTION_MIGRATION_ID,
)
from athena.storage.schema_contract import (
    BACKUP_RETENTION_SCHEMA_VERSION as BACKUP_RETENTION_SCHEMA_VERSION,
)
from athena.storage.schema_contract import (
    BLOB_FORMAT_VERSION as BLOB_FORMAT_VERSION,
)
from athena.storage.schema_contract import (
    CONSOLIDATED_OPERATIONS_MIGRATION_ID as CONSOLIDATED_OPERATIONS_MIGRATION_ID,
)
from athena.storage.schema_contract import (
    CONSOLIDATED_OPERATIONS_SCHEMA_VERSION as CONSOLIDATED_OPERATIONS_SCHEMA_VERSION,
)
from athena.storage.schema_contract import (
    DELETION_LEDGER_MIGRATION_ID as DELETION_LEDGER_MIGRATION_ID,
)
from athena.storage.schema_contract import (
    DELETION_LEDGER_SCHEMA_VERSION as DELETION_LEDGER_SCHEMA_VERSION,
)
from athena.storage.schema_contract import (
    DURABLE_JOBS_MIGRATION_ID as DURABLE_JOBS_MIGRATION_ID,
)
from athena.storage.schema_contract import (
    DURABLE_JOBS_SCHEMA_VERSION as DURABLE_JOBS_SCHEMA_VERSION,
)
from athena.storage.schema_contract import (
    EXHAUSTIVE_RESEARCH_MIGRATION_ID as EXHAUSTIVE_RESEARCH_MIGRATION_ID,
)
from athena.storage.schema_contract import (
    EXHAUSTIVE_RESEARCH_SCHEMA_VERSION as EXHAUSTIVE_RESEARCH_SCHEMA_VERSION,
)
from athena.storage.schema_contract import (
    EXTRACTION_SNAPSHOT_MIGRATION_ID as EXTRACTION_SNAPSHOT_MIGRATION_ID,
)
from athena.storage.schema_contract import (
    EXTRACTION_SNAPSHOT_SCHEMA_VERSION as EXTRACTION_SNAPSHOT_SCHEMA_VERSION,
)
from athena.storage.schema_contract import (
    GROUNDED_RESPONSE_RECEIPT_MIGRATION_ID as GROUNDED_RESPONSE_RECEIPT_MIGRATION_ID,
)
from athena.storage.schema_contract import (
    GROUNDED_RESPONSE_RECEIPT_SCHEMA_VERSION as GROUNDED_RESPONSE_RECEIPT_SCHEMA_VERSION,
)
from athena.storage.schema_contract import (
    HIERARCHICAL_SOURCE_EXTRACTION_MIGRATION_ID as HIERARCHICAL_SOURCE_EXTRACTION_MIGRATION_ID,
)
from athena.storage.schema_contract import (
    HIERARCHICAL_SOURCE_EXTRACTION_SCHEMA_VERSION as HIERARCHICAL_SOURCE_EXTRACTION_SCHEMA_VERSION,
)
from athena.storage.schema_contract import (
    KNOWLEDGE_CORE_MIGRATION_ID as KNOWLEDGE_CORE_MIGRATION_ID,
)
from athena.storage.schema_contract import (
    KNOWLEDGE_SCHEMA_VERSION as KNOWLEDGE_SCHEMA_VERSION,
)
from athena.storage.schema_contract import (
    LEGACY_SCHEMA_VERSION as LEGACY_SCHEMA_VERSION,
)
from athena.storage.schema_contract import (
    LOCAL_EMBEDDINGS_MIGRATION_ID as LOCAL_EMBEDDINGS_MIGRATION_ID,
)
from athena.storage.schema_contract import (
    LOCAL_EMBEDDINGS_SCHEMA_VERSION as LOCAL_EMBEDDINGS_SCHEMA_VERSION,
)
from athena.storage.schema_contract import (
    LOCAL_FTS_SCHEMA_VERSION as LOCAL_FTS_SCHEMA_VERSION,
)
from athena.storage.schema_contract import (
    LOCAL_FTS_SEARCH_MIGRATION_ID as LOCAL_FTS_SEARCH_MIGRATION_ID,
)
from athena.storage.schema_contract import (
    MERGE_REVIEW_MIGRATION_ID as MERGE_REVIEW_MIGRATION_ID,
)
from athena.storage.schema_contract import (
    MERGE_REVIEW_MULTI_TARGET_MIGRATION_ID as MERGE_REVIEW_MULTI_TARGET_MIGRATION_ID,
)
from athena.storage.schema_contract import (
    MERGE_REVIEW_MULTI_TARGET_SCHEMA_VERSION as MERGE_REVIEW_MULTI_TARGET_SCHEMA_VERSION,
)
from athena.storage.schema_contract import (
    MERGE_REVIEW_SCHEMA_VERSION as MERGE_REVIEW_SCHEMA_VERSION,
)
from athena.storage.schema_contract import (
    MODEL_RUNS_MIGRATION_ID as MODEL_RUNS_MIGRATION_ID,
)
from athena.storage.schema_contract import (
    MODEL_RUNS_SCHEMA_VERSION as MODEL_RUNS_SCHEMA_VERSION,
)
from athena.storage.schema_contract import (
    NEWS_EVENT_ELIGIBILITY_MIGRATION_ID as NEWS_EVENT_ELIGIBILITY_MIGRATION_ID,
)
from athena.storage.schema_contract import (
    NEWS_EVENT_ELIGIBILITY_SCHEMA_VERSION as NEWS_EVENT_ELIGIBILITY_SCHEMA_VERSION,
)
from athena.storage.schema_contract import (
    NEWS_EVENT_STRUCTURE_MIGRATION_ID as NEWS_EVENT_STRUCTURE_MIGRATION_ID,
)
from athena.storage.schema_contract import (
    NEWS_EVENT_STRUCTURE_SCHEMA_VERSION as NEWS_EVENT_STRUCTURE_SCHEMA_VERSION,
)
from athena.storage.schema_contract import (
    NEWS_OPERATIONAL_MIGRATION_ID as NEWS_OPERATIONAL_MIGRATION_ID,
)
from athena.storage.schema_contract import (
    NEWS_OPERATIONAL_SCHEMA_VERSION as NEWS_OPERATIONAL_SCHEMA_VERSION,
)
from athena.storage.schema_contract import (
    NEWS_SYSTEM_MIGRATION_ID as NEWS_SYSTEM_MIGRATION_ID,
)
from athena.storage.schema_contract import (
    NEWS_SYSTEM_SCHEMA_VERSION as NEWS_SYSTEM_SCHEMA_VERSION,
)
from athena.storage.schema_contract import (
    OPERATIONAL_ERROR_PHYSICAL_CLEANUP_MIGRATION_ID as OPERATIONAL_ERROR_PHYSICAL_CLEANUP_MIGRATION_ID,
)
from athena.storage.schema_contract import (
    OPERATIONAL_ERROR_PHYSICAL_CLEANUP_SCHEMA_VERSION as OPERATIONAL_ERROR_PHYSICAL_CLEANUP_SCHEMA_VERSION,
)
from athena.storage.schema_contract import (
    OPERATIONAL_ERROR_SANITIZATION_MIGRATION_ID as OPERATIONAL_ERROR_SANITIZATION_MIGRATION_ID,
)
from athena.storage.schema_contract import (
    OPERATIONAL_ERROR_SANITIZATION_SCHEMA_VERSION as OPERATIONAL_ERROR_SANITIZATION_SCHEMA_VERSION,
)
from athena.storage.schema_contract import (
    PERSONAL_MEMORY_MIGRATION_ID as PERSONAL_MEMORY_MIGRATION_ID,
)
from athena.storage.schema_contract import (
    PERSONAL_MEMORY_SCHEMA_VERSION as PERSONAL_MEMORY_SCHEMA_VERSION,
)
from athena.storage.schema_contract import (
    PRECISE_RESEARCH_PROVENANCE_MIGRATION_ID as PRECISE_RESEARCH_PROVENANCE_MIGRATION_ID,
)
from athena.storage.schema_contract import (
    PRECISE_RESEARCH_PROVENANCE_SCHEMA_VERSION as PRECISE_RESEARCH_PROVENANCE_SCHEMA_VERSION,
)
from athena.storage.schema_contract import (
    PROTECTED_CONTENT_MIGRATION_ID as PROTECTED_CONTENT_MIGRATION_ID,
)
from athena.storage.schema_contract import (
    PROTECTED_CONTENT_SCHEMA_VERSION as PROTECTED_CONTENT_SCHEMA_VERSION,
)
from athena.storage.schema_contract import (
    PROTECTED_SOURCE_BLOB_MIGRATION_ID as PROTECTED_SOURCE_BLOB_MIGRATION_ID,
)
from athena.storage.schema_contract import (
    PROTECTED_SOURCE_BLOB_SCHEMA_VERSION as PROTECTED_SOURCE_BLOB_SCHEMA_VERSION,
)
from athena.storage.schema_contract import (
    PROTECTED_SOURCE_SEMANTIC_MIGRATION_ID as PROTECTED_SOURCE_SEMANTIC_MIGRATION_ID,
)
from athena.storage.schema_contract import (
    PROTECTED_SOURCE_SEMANTIC_SCHEMA_VERSION as PROTECTED_SOURCE_SEMANTIC_SCHEMA_VERSION,
)
from athena.storage.schema_contract import (
    PROVENANCE_INPUTS_MIGRATION_ID as PROVENANCE_INPUTS_MIGRATION_ID,
)
from athena.storage.schema_contract import (
    PROVENANCE_SCHEMA_VERSION as PROVENANCE_SCHEMA_VERSION,
)
from athena.storage.schema_contract import (
    RESEARCH_ORCHESTRATION_MIGRATION_ID as RESEARCH_ORCHESTRATION_MIGRATION_ID,
)
from athena.storage.schema_contract import (
    RESEARCH_ORCHESTRATION_SCHEMA_VERSION as RESEARCH_ORCHESTRATION_SCHEMA_VERSION,
)
from athena.storage.schema_contract import (
    RESEARCH_SYNTHESIS_MIGRATION_ID as RESEARCH_SYNTHESIS_MIGRATION_ID,
)
from athena.storage.schema_contract import (
    RESEARCH_SYNTHESIS_SCHEMA_VERSION as RESEARCH_SYNTHESIS_SCHEMA_VERSION,
)
from athena.storage.schema_contract import (
    REVIEW_QUEUE_MIGRATION_ID as REVIEW_QUEUE_MIGRATION_ID,
)
from athena.storage.schema_contract import (
    REVIEW_QUEUE_SCHEMA_VERSION as REVIEW_QUEUE_SCHEMA_VERSION,
)
from athena.storage.schema_contract import (
    SCHEMA_VERSION as SCHEMA_VERSION,
)
from athena.storage.schema_contract import (
    SOURCE_ANALYSIS_MIGRATION_ID as SOURCE_ANALYSIS_MIGRATION_ID,
)
from athena.storage.schema_contract import (
    SOURCE_ANALYSIS_SCHEMA_VERSION as SOURCE_ANALYSIS_SCHEMA_VERSION,
)
from athena.storage.schema_contract import (
    SOURCE_ANCHOR_MIGRATION_ID as SOURCE_ANCHOR_MIGRATION_ID,
)
from athena.storage.schema_contract import (
    SOURCE_ANCHOR_SCHEMA_VERSION as SOURCE_ANCHOR_SCHEMA_VERSION,
)
from athena.storage.schema_contract import (
    SOURCE_CAPTURE_MIGRATION_ID as SOURCE_CAPTURE_MIGRATION_ID,
)
from athena.storage.schema_contract import (
    SOURCE_CAPTURE_SCHEMA_VERSION as SOURCE_CAPTURE_SCHEMA_VERSION,
)
from athena.storage.schema_contract import (
    SOURCE_CHUNK_PROFILE_MIGRATION_ID as SOURCE_CHUNK_PROFILE_MIGRATION_ID,
)
from athena.storage.schema_contract import (
    SOURCE_CHUNK_PROFILE_SCHEMA_VERSION as SOURCE_CHUNK_PROFILE_SCHEMA_VERSION,
)
from athena.storage.schema_contract import (
    SOURCE_DOCUMENT_STRUCTURE_MIGRATION_ID as SOURCE_DOCUMENT_STRUCTURE_MIGRATION_ID,
)
from athena.storage.schema_contract import (
    SOURCE_DOCUMENT_STRUCTURE_SCHEMA_VERSION as SOURCE_DOCUMENT_STRUCTURE_SCHEMA_VERSION,
)
from athena.storage.schema_contract import (
    SOURCE_KNOWLEDGE_MIGRATION_ID as SOURCE_KNOWLEDGE_MIGRATION_ID,
)
from athena.storage.schema_contract import (
    SOURCE_KNOWLEDGE_SCHEMA_VERSION as SOURCE_KNOWLEDGE_SCHEMA_VERSION,
)
from athena.storage.schema_contract import (
    SOURCE_PAGE_MAP_MIGRATION_ID as SOURCE_PAGE_MAP_MIGRATION_ID,
)
from athena.storage.schema_contract import (
    SOURCE_PAGE_MAP_SCHEMA_VERSION as SOURCE_PAGE_MAP_SCHEMA_VERSION,
)
from athena.storage.schema_contract import (
    SOURCE_PROTECTION_TRANSITION_MIGRATION_ID as SOURCE_PROTECTION_TRANSITION_MIGRATION_ID,
)
from athena.storage.schema_contract import (
    SOURCE_PROTECTION_TRANSITION_SCHEMA_VERSION as SOURCE_PROTECTION_TRANSITION_SCHEMA_VERSION,
)
from athena.storage.schema_contract import (
    SOURCE_REPRESENTATION_MIGRATION_ID as SOURCE_REPRESENTATION_MIGRATION_ID,
)
from athena.storage.schema_contract import (
    SOURCE_REPRESENTATION_SCHEMA_VERSION as SOURCE_REPRESENTATION_SCHEMA_VERSION,
)
from athena.storage.schema_contract import (
    STORAGE_LAYOUT_VERSION as STORAGE_LAYOUT_VERSION,
)
from athena.storage.schema_contract import (
    DatabaseCompatibilityError as DatabaseCompatibilityError,
)
from athena.storage.schema_contract import (
    _user_tables as _user_tables,
)
from athena.storage.schema_error_sanitization import (
    _PERSISTED_ERROR_CHECKPOINT_JOB_TYPES as _PERSISTED_ERROR_CHECKPOINT_JOB_TYPES,
)
from athena.storage.schema_error_sanitization import (
    _PERSISTED_ERROR_CODE_RE as _PERSISTED_ERROR_CODE_RE,
)
from athena.storage.schema_error_sanitization import (
    _PERSISTED_ERROR_SCALAR_FIELDS as _PERSISTED_ERROR_SCALAR_FIELDS,
)
from athena.storage.schema_error_sanitization import (
    _canonical_migration_json as _canonical_migration_json,
)
from athena.storage.schema_error_sanitization import (
    _sanitize_checkpoint_error_payload as _sanitize_checkpoint_error_payload,
)
from athena.storage.schema_error_sanitization import (
    _sanitize_persisted_error_value as _sanitize_persisted_error_value,
)
from athena.storage.schema_evolution import (
    _create_schema_v1 as _create_schema_v1,
)
from athena.storage.schema_evolution import (
    _migrate_schema_v1_to_v2 as _migrate_schema_v1_to_v2,
)
from athena.storage.schema_evolution import (
    _migrate_schema_v2_to_v3 as _migrate_schema_v2_to_v3,
)
from athena.storage.schema_evolution import (
    _migrate_schema_v3_to_v4 as _migrate_schema_v3_to_v4,
)
from athena.storage.schema_evolution import (
    _migrate_schema_v4_to_v5 as _migrate_schema_v4_to_v5,
)
from athena.storage.schema_evolution import (
    _migrate_schema_v5_to_v6 as _migrate_schema_v5_to_v6,
)
from athena.storage.schema_evolution import (
    _migrate_schema_v6_to_v7 as _migrate_schema_v6_to_v7,
)
from athena.storage.schema_evolution import (
    _migrate_schema_v7_to_v8 as _migrate_schema_v7_to_v8,
)
from athena.storage.schema_evolution import (
    _migrate_schema_v8_to_v9 as _migrate_schema_v8_to_v9,
)
from athena.storage.schema_evolution import (
    _migrate_schema_v9_to_v10 as _migrate_schema_v9_to_v10,
)
from athena.storage.schema_evolution import (
    _migrate_schema_v10_to_v11 as _migrate_schema_v10_to_v11,
)
from athena.storage.schema_evolution import (
    _migrate_schema_v11_to_v12 as _migrate_schema_v11_to_v12,
)
from athena.storage.schema_evolution import (
    _migrate_schema_v12_to_v13 as _migrate_schema_v12_to_v13,
)
from athena.storage.schema_evolution import (
    _migrate_schema_v13_to_v14 as _migrate_schema_v13_to_v14,
)
from athena.storage.schema_evolution import (
    _migrate_schema_v14_to_v15 as _migrate_schema_v14_to_v15,
)
from athena.storage.schema_evolution import (
    _migrate_schema_v15_to_v16 as _migrate_schema_v15_to_v16,
)
from athena.storage.schema_evolution import (
    _migrate_schema_v16_to_v17 as _migrate_schema_v16_to_v17,
)
from athena.storage.schema_evolution import (
    _migrate_schema_v17_to_v18 as _migrate_schema_v17_to_v18,
)
from athena.storage.schema_evolution import (
    _migrate_schema_v18_to_v19 as _migrate_schema_v18_to_v19,
)
from athena.storage.schema_evolution import (
    _migrate_schema_v19_to_v20 as _migrate_schema_v19_to_v20,
)
from athena.storage.schema_evolution import (
    _migrate_schema_v20_to_v21 as _migrate_schema_v20_to_v21,
)
from athena.storage.schema_evolution import (
    _migrate_schema_v21_to_v22 as _migrate_schema_v21_to_v22,
)
from athena.storage.schema_evolution import (
    _migrate_schema_v22_to_v23 as _migrate_schema_v22_to_v23,
)
from athena.storage.schema_evolution import (
    _migrate_schema_v23_to_v24 as _migrate_schema_v23_to_v24,
)
from athena.storage.schema_evolution import (
    _migrate_schema_v24_to_v25 as _migrate_schema_v24_to_v25,
)
from athena.storage.schema_evolution import (
    _migrate_schema_v28_to_v29 as _migrate_schema_v28_to_v29,
)
from athena.storage.schema_evolution import (
    _migrate_schema_v30_to_v31 as _migrate_schema_v30_to_v31,
)
from athena.storage.schema_evolution import (
    _migrate_schema_v31_to_v32 as _migrate_schema_v31_to_v32,
)
from athena.storage.schema_evolution import (
    _migrate_schema_v32_to_v33 as _migrate_schema_v32_to_v33,
)
from athena.storage.schema_evolution import (
    _migrate_schema_v33_to_v34 as _migrate_schema_v33_to_v34,
)
from athena.storage.schema_evolution import (
    _migrate_schema_v34_to_v35 as _migrate_schema_v34_to_v35,
)
from athena.storage.schema_evolution import (
    _migrate_schema_v35_to_v36 as _migrate_schema_v35_to_v36,
)
from athena.storage.schema_evolution import (
    _migrate_schema_v36_to_v37 as _migrate_schema_v36_to_v37,
)
from athena.storage.schema_evolution import (
    _migrate_schema_v38_to_v39 as _migrate_schema_v38_to_v39,
)
from athena.storage.schema_evolution import (
    _migrate_schema_v39_to_v40 as _migrate_schema_v39_to_v40,
)
from athena.storage.schema_verification import (
    _verify_schema_v15 as _verify_schema_v15,
)
from athena.storage.schema_verification import (
    _verify_schema_v16 as _verify_schema_v16,
)
from athena.storage.schema_verification import (
    _verify_schema_v17 as _verify_schema_v17,
)
from athena.storage.schema_verification import (
    _verify_schema_v18 as _verify_schema_v18,
)
from athena.storage.schema_verification import (
    _verify_schema_v19 as _verify_schema_v19,
)
from athena.storage.schema_verification import (
    _verify_schema_v20 as _verify_schema_v20,
)
from athena.storage.schema_verification import (
    _verify_schema_v21 as _verify_schema_v21,
)
from athena.storage.schema_verification import (
    _verify_schema_v22 as _verify_schema_v22,
)
from athena.storage.schema_verification import (
    _verify_schema_v23 as _verify_schema_v23,
)
from athena.storage.schema_verification import (
    _verify_schema_v24 as _verify_schema_v24,
)
from athena.storage.schema_verification import (
    _verify_schema_v24_compatible as _verify_schema_v24_compatible,
)
from athena.storage.schema_verification import (
    _verify_schema_v25 as _verify_schema_v25,
)
from athena.storage.schema_verification import (
    _verify_schema_v26 as _verify_schema_v26,
)
from athena.storage.schema_verification import (
    _verify_schema_v27 as _verify_schema_v27,
)
from athena.storage.schema_verification import (
    _verify_schema_v28 as _verify_schema_v28,
)
from athena.storage.schema_verification import (
    _verify_schema_v29 as _verify_schema_v29,
)
from athena.storage.schema_verification import (
    _verify_schema_v30 as _verify_schema_v30,
)
from athena.storage.schema_verification import (
    _verify_schema_v31 as _verify_schema_v31,
)
from athena.storage.schema_verification import (
    _verify_schema_v31_compatible as _verify_schema_v31_compatible,
)
from athena.storage.schema_verification import (
    _verify_schema_v32 as _verify_schema_v32,
)
from athena.storage.schema_verification import (
    _verify_schema_v33 as _verify_schema_v33,
)
from athena.storage.schema_verification import (
    _verify_schema_v34 as _verify_schema_v34,
)
from athena.storage.schema_verification import (
    _verify_schema_v35 as _verify_schema_v35,
)
from athena.storage.schema_verification import (
    _verify_schema_v36 as _verify_schema_v36,
)
from athena.storage.schema_verification import (
    _verify_schema_v37 as _verify_schema_v37,
)
from athena.storage.schema_verification import (
    _verify_schema_v38 as _verify_schema_v38,
)
from athena.storage.schema_verification import (
    _verify_schema_v39 as _verify_schema_v39,
)
from athena.storage.schema_verification import (
    _verify_schema_v40 as _verify_schema_v40,
)


def _configure_connection(connection: sqlite3.Connection) -> None:
    connection.execute("PRAGMA foreign_keys = ON")
    mode = str(connection.execute("PRAGMA journal_mode = WAL").fetchone()[0]).lower()
    if mode != "wal":
        raise DatabaseCompatibilityError(
            f"ATHENA requires SQLite WAL mode, but SQLite returned {mode!r}."
        )
    connection.execute("PRAGMA synchronous = FULL")
    connection.execute("PRAGMA busy_timeout = 5000")
    connection.execute("PRAGMA secure_delete = ON")
    connection.execute("PRAGMA read_uncommitted = OFF")
    connection.execute("PRAGMA wal_autocheckpoint = 1000")
    connection.execute("PRAGMA trusted_schema = OFF")


def initialize_schema(connection: sqlite3.Connection, *, created_at_us: int) -> None:
    """Validate, initialize, or safely advance the ATHENA SQLite schema.

    Schema v4 adds persistent ModelSignatures and ProcessingRuns. Existing v1-v3
    databases are upgraded transactionally without rewriting chat or Knowledge
    payloads. Unknown, unrelated, and newer databases fail closed.
    """
    existing_application_id = int(
        connection.execute("PRAGMA application_id").fetchone()[0]
    )
    existing_user_version = int(connection.execute("PRAGMA user_version").fetchone()[0])
    tables = _user_tables(connection)

    if existing_application_id not in {0, ATHENA_APPLICATION_ID}:
        raise DatabaseCompatibilityError(
            "Database application_id does not belong to ATHENA."
        )

    if existing_application_id == 0 and tables:
        raise DatabaseCompatibilityError(
            "Refusing to adopt a non-empty SQLite database without ATHENA application_id."
        )

    if existing_user_version > SCHEMA_VERSION:
        raise DatabaseCompatibilityError(
            f"Database schema version {existing_user_version} is newer than supported "
            f"version {SCHEMA_VERSION}."
        )

    supported_versions = {
        0,
        LEGACY_SCHEMA_VERSION,
        KNOWLEDGE_SCHEMA_VERSION,
        PROVENANCE_SCHEMA_VERSION,
        MODEL_RUNS_SCHEMA_VERSION,
        REVIEW_QUEUE_SCHEMA_VERSION,
        MERGE_REVIEW_SCHEMA_VERSION,
        MERGE_REVIEW_MULTI_TARGET_SCHEMA_VERSION,
        EXTRACTION_SNAPSHOT_SCHEMA_VERSION,
        LOCAL_FTS_SCHEMA_VERSION,
        LOCAL_EMBEDDINGS_SCHEMA_VERSION,
        SOURCE_CAPTURE_SCHEMA_VERSION,
        SOURCE_REPRESENTATION_SCHEMA_VERSION,
        SOURCE_CHUNK_PROFILE_SCHEMA_VERSION,
        SOURCE_ANCHOR_SCHEMA_VERSION,
        DURABLE_JOBS_SCHEMA_VERSION,
        SOURCE_PAGE_MAP_SCHEMA_VERSION,
        SOURCE_DOCUMENT_STRUCTURE_SCHEMA_VERSION,
        SOURCE_ANALYSIS_SCHEMA_VERSION,
        SOURCE_KNOWLEDGE_SCHEMA_VERSION,
        HIERARCHICAL_SOURCE_EXTRACTION_SCHEMA_VERSION,
        PERSONAL_MEMORY_SCHEMA_VERSION,
        EXHAUSTIVE_RESEARCH_SCHEMA_VERSION,
        RESEARCH_ORCHESTRATION_SCHEMA_VERSION,
        RESEARCH_SYNTHESIS_SCHEMA_VERSION,
        CONSOLIDATED_OPERATIONS_SCHEMA_VERSION,
        NEWS_SYSTEM_SCHEMA_VERSION,
        NEWS_EVENT_STRUCTURE_SCHEMA_VERSION,
        NEWS_OPERATIONAL_SCHEMA_VERSION,
        PRECISE_RESEARCH_PROVENANCE_SCHEMA_VERSION,
        NEWS_EVENT_ELIGIBILITY_SCHEMA_VERSION,
        ARCHIVE_REPLICATION_SCHEMA_VERSION,
        PROTECTED_CONTENT_SCHEMA_VERSION,
        PROTECTED_SOURCE_BLOB_SCHEMA_VERSION,
        SOURCE_PROTECTION_TRANSITION_SCHEMA_VERSION,
        BACKUP_RETENTION_SCHEMA_VERSION,
        DELETION_LEDGER_SCHEMA_VERSION,
        OPERATIONAL_ERROR_SANITIZATION_SCHEMA_VERSION,
        OPERATIONAL_ERROR_PHYSICAL_CLEANUP_SCHEMA_VERSION,
        PROTECTED_SOURCE_SEMANTIC_SCHEMA_VERSION,
        SCHEMA_VERSION,
    }
    if existing_user_version not in supported_versions:
        raise DatabaseCompatibilityError(
            f"Database schema version {existing_user_version} requires an unsupported "
            "migration path."
        )

    if existing_user_version == 0:
        # Must be selected before schema objects are created for a new database.
        connection.execute("PRAGMA auto_vacuum = INCREMENTAL")
        connection.execute(f"PRAGMA application_id = {ATHENA_APPLICATION_ID}")
        _create_schema_v1(connection, created_at_us=created_at_us)
        existing_user_version = LEGACY_SCHEMA_VERSION

    if existing_user_version == LEGACY_SCHEMA_VERSION:
        _migrate_schema_v1_to_v2(connection)
        existing_user_version = KNOWLEDGE_SCHEMA_VERSION

    if existing_user_version == KNOWLEDGE_SCHEMA_VERSION:
        _migrate_schema_v2_to_v3(connection)
        existing_user_version = PROVENANCE_SCHEMA_VERSION

    if existing_user_version == PROVENANCE_SCHEMA_VERSION:
        _migrate_schema_v3_to_v4(connection)
        existing_user_version = MODEL_RUNS_SCHEMA_VERSION

    if existing_user_version == MODEL_RUNS_SCHEMA_VERSION:
        _migrate_schema_v4_to_v5(connection)
        existing_user_version = REVIEW_QUEUE_SCHEMA_VERSION

    if existing_user_version == REVIEW_QUEUE_SCHEMA_VERSION:
        _migrate_schema_v5_to_v6(connection)
        existing_user_version = MERGE_REVIEW_SCHEMA_VERSION

    if existing_user_version == MERGE_REVIEW_SCHEMA_VERSION:
        _migrate_schema_v6_to_v7(connection)
        existing_user_version = MERGE_REVIEW_MULTI_TARGET_SCHEMA_VERSION

    if existing_user_version == MERGE_REVIEW_MULTI_TARGET_SCHEMA_VERSION:
        _migrate_schema_v7_to_v8(connection)
        existing_user_version = EXTRACTION_SNAPSHOT_SCHEMA_VERSION

    if existing_user_version == EXTRACTION_SNAPSHOT_SCHEMA_VERSION:
        _migrate_schema_v8_to_v9(connection)
        existing_user_version = LOCAL_FTS_SCHEMA_VERSION

    if existing_user_version == LOCAL_FTS_SCHEMA_VERSION:
        _migrate_schema_v9_to_v10(connection)
        existing_user_version = LOCAL_EMBEDDINGS_SCHEMA_VERSION

    if existing_user_version == LOCAL_EMBEDDINGS_SCHEMA_VERSION:
        _migrate_schema_v10_to_v11(connection)
        existing_user_version = SOURCE_CAPTURE_SCHEMA_VERSION

    if existing_user_version == SOURCE_CAPTURE_SCHEMA_VERSION:
        _migrate_schema_v11_to_v12(connection)
        existing_user_version = SOURCE_REPRESENTATION_SCHEMA_VERSION

    if existing_user_version == SOURCE_REPRESENTATION_SCHEMA_VERSION:
        _migrate_schema_v12_to_v13(connection)
        existing_user_version = SOURCE_CHUNK_PROFILE_SCHEMA_VERSION

    if existing_user_version == SOURCE_CHUNK_PROFILE_SCHEMA_VERSION:
        _migrate_schema_v13_to_v14(connection)
        existing_user_version = SOURCE_ANCHOR_SCHEMA_VERSION

    if existing_user_version == SOURCE_ANCHOR_SCHEMA_VERSION:
        _migrate_schema_v14_to_v15(connection)
        existing_user_version = DURABLE_JOBS_SCHEMA_VERSION

    if existing_user_version == DURABLE_JOBS_SCHEMA_VERSION:
        _migrate_schema_v15_to_v16(connection)
        existing_user_version = SOURCE_PAGE_MAP_SCHEMA_VERSION

    if existing_user_version == SOURCE_PAGE_MAP_SCHEMA_VERSION:
        _migrate_schema_v16_to_v17(connection)
        existing_user_version = SOURCE_DOCUMENT_STRUCTURE_SCHEMA_VERSION

    if existing_user_version == SOURCE_DOCUMENT_STRUCTURE_SCHEMA_VERSION:
        _migrate_schema_v17_to_v18(connection)
        existing_user_version = SOURCE_ANALYSIS_SCHEMA_VERSION

    if existing_user_version == SOURCE_ANALYSIS_SCHEMA_VERSION:
        _migrate_schema_v18_to_v19(connection)
        existing_user_version = SOURCE_KNOWLEDGE_SCHEMA_VERSION

    if existing_user_version == SOURCE_KNOWLEDGE_SCHEMA_VERSION:
        _migrate_schema_v19_to_v20(connection)
        existing_user_version = HIERARCHICAL_SOURCE_EXTRACTION_SCHEMA_VERSION

    if existing_user_version == HIERARCHICAL_SOURCE_EXTRACTION_SCHEMA_VERSION:
        _migrate_schema_v20_to_v21(connection)
        existing_user_version = PERSONAL_MEMORY_SCHEMA_VERSION

    if existing_user_version == PERSONAL_MEMORY_SCHEMA_VERSION:
        _migrate_schema_v21_to_v22(connection)
        existing_user_version = EXHAUSTIVE_RESEARCH_SCHEMA_VERSION

    if existing_user_version == EXHAUSTIVE_RESEARCH_SCHEMA_VERSION:
        _migrate_schema_v22_to_v23(connection)
        existing_user_version = RESEARCH_ORCHESTRATION_SCHEMA_VERSION

    if existing_user_version == RESEARCH_ORCHESTRATION_SCHEMA_VERSION:
        _migrate_schema_v23_to_v24(connection)
        existing_user_version = RESEARCH_SYNTHESIS_SCHEMA_VERSION

    if existing_user_version == RESEARCH_SYNTHESIS_SCHEMA_VERSION:
        _migrate_schema_v24_to_v25(connection)
        existing_user_version = CONSOLIDATED_OPERATIONS_SCHEMA_VERSION

    if existing_user_version == CONSOLIDATED_OPERATIONS_SCHEMA_VERSION:
        migrate_news_schema_v25_to_v26(
            connection,
            schema_version=NEWS_SYSTEM_SCHEMA_VERSION,
            migration_id=NEWS_SYSTEM_MIGRATION_ID,
        )
        existing_user_version = NEWS_SYSTEM_SCHEMA_VERSION

    if existing_user_version == NEWS_SYSTEM_SCHEMA_VERSION:
        migrate_news_schema_v26_to_v27(
            connection,
            schema_version=NEWS_EVENT_STRUCTURE_SCHEMA_VERSION,
            migration_id=NEWS_EVENT_STRUCTURE_MIGRATION_ID,
        )
        existing_user_version = NEWS_EVENT_STRUCTURE_SCHEMA_VERSION

    if existing_user_version == NEWS_EVENT_STRUCTURE_SCHEMA_VERSION:
        migrate_news_schema_v27_to_v28(
            connection,
            schema_version=NEWS_OPERATIONAL_SCHEMA_VERSION,
            migration_id=NEWS_OPERATIONAL_MIGRATION_ID,
        )
        existing_user_version = NEWS_OPERATIONAL_SCHEMA_VERSION

    if existing_user_version == NEWS_OPERATIONAL_SCHEMA_VERSION:
        _migrate_schema_v28_to_v29(connection)
        existing_user_version = (
            PRECISE_RESEARCH_PROVENANCE_SCHEMA_VERSION
        )

    if (
        existing_user_version
        == PRECISE_RESEARCH_PROVENANCE_SCHEMA_VERSION
    ):
        _verify_schema_v29(connection)
        migrate_news_schema_v29_to_v30(
            connection,
            schema_version=(
                NEWS_EVENT_ELIGIBILITY_SCHEMA_VERSION
            ),
            migration_id=(
                NEWS_EVENT_ELIGIBILITY_MIGRATION_ID
            ),
        )
        existing_user_version = (
            NEWS_EVENT_ELIGIBILITY_SCHEMA_VERSION
        )

    if (
        existing_user_version
        == NEWS_EVENT_ELIGIBILITY_SCHEMA_VERSION
    ):
        _verify_schema_v30(connection)
        _migrate_schema_v30_to_v31(connection)
        existing_user_version = (
            ARCHIVE_REPLICATION_SCHEMA_VERSION
        )

    if (
        existing_user_version
        == ARCHIVE_REPLICATION_SCHEMA_VERSION
    ):
        _verify_schema_v31(connection)
        _migrate_schema_v31_to_v32(connection)
        existing_user_version = (
            PROTECTED_CONTENT_SCHEMA_VERSION
        )

    if (
        existing_user_version
        == PROTECTED_CONTENT_SCHEMA_VERSION
    ):
        _verify_schema_v32(connection)
        _migrate_schema_v32_to_v33(connection)
        existing_user_version = (
            PROTECTED_SOURCE_BLOB_SCHEMA_VERSION
        )

    if (
        existing_user_version
        == PROTECTED_SOURCE_BLOB_SCHEMA_VERSION
    ):
        _verify_schema_v33(connection)
        _migrate_schema_v33_to_v34(connection)
        existing_user_version = (
            SOURCE_PROTECTION_TRANSITION_SCHEMA_VERSION
        )

    if (
        existing_user_version
        == SOURCE_PROTECTION_TRANSITION_SCHEMA_VERSION
    ):
        _verify_schema_v34(connection)
        _migrate_schema_v34_to_v35(connection)
        existing_user_version = BACKUP_RETENTION_SCHEMA_VERSION

    if (
        existing_user_version
        == BACKUP_RETENTION_SCHEMA_VERSION
    ):
        _verify_schema_v35(connection)
        _migrate_schema_v35_to_v36(connection)
        existing_user_version = DELETION_LEDGER_SCHEMA_VERSION

    if (
        existing_user_version
        == DELETION_LEDGER_SCHEMA_VERSION
    ):
        _verify_schema_v36(connection)
        _migrate_schema_v36_to_v37(connection)
        existing_user_version = (
            OPERATIONAL_ERROR_SANITIZATION_SCHEMA_VERSION
        )

    if (
        existing_user_version
        == OPERATIONAL_ERROR_SANITIZATION_SCHEMA_VERSION
    ):
        _verify_schema_v37(connection)
        _migrate_schema_v37_to_v38(connection)
        existing_user_version = (
            OPERATIONAL_ERROR_PHYSICAL_CLEANUP_SCHEMA_VERSION
        )

    if (
        existing_user_version
        == OPERATIONAL_ERROR_PHYSICAL_CLEANUP_SCHEMA_VERSION
    ):
        _verify_schema_v38(connection)
        _migrate_schema_v38_to_v39(connection)
        existing_user_version = (
            PROTECTED_SOURCE_SEMANTIC_SCHEMA_VERSION
        )

    if (
        existing_user_version
        == PROTECTED_SOURCE_SEMANTIC_SCHEMA_VERSION
    ):
        _verify_schema_v39(connection)
        _migrate_schema_v39_to_v40(connection)
        existing_user_version = (
            GROUNDED_RESPONSE_RECEIPT_SCHEMA_VERSION
        )

    _configure_connection(connection)
    _verify_schema_v40(connection)























































































def _checkpoint_wal_truncate_for_physical_cleanup(
    connection: sqlite3.Connection,
) -> None:
    try:
        row = connection.execute(
            "PRAGMA wal_checkpoint(TRUNCATE)"
        ).fetchone()

    except sqlite3.OperationalError as exc:
        raise DatabaseCompatibilityError(
            "SQLite WAL physical-cleanup checkpoint "
            "could not run."
        ) from exc

    if (
        row is None
        or len(row) < 1
        or int(row[0]) != 0
    ):
        raise DatabaseCompatibilityError(
            "SQLite WAL physical-cleanup checkpoint is busy."
        )


def _physical_cleanup_operational_error_remnants(
    connection: sqlite3.Connection,
) -> None:
    """Remove unreachable historical error bytes from SQLite storage."""
    if connection.in_transaction:
        raise RuntimeError(
            "Operational-error physical cleanup "
            "requires no active transaction."
        )

    # Do not switch a freshly created database into WAL here.
    # A manual checkpoint immediately after that transition can be
    # blocked by statements from the same startup connection.
    journal_row = connection.execute(
        "PRAGMA journal_mode"
    ).fetchone()

    if journal_row is None:
        raise DatabaseCompatibilityError(
            "SQLite journal mode could not be determined."
        )

    journal_mode = str(
        journal_row[0]
    ).lower()

    # Existing ATHENA databases are WAL. A database being created by
    # this same initialize_schema() call is still in SQLite's default
    # DELETE mode until normal connection configuration runs below.
    if journal_mode not in {
        "wal",
        "delete",
    }:
        raise DatabaseCompatibilityError(
            "ATHENA physical cleanup encountered "
            f"unsupported SQLite journal mode {journal_mode!r}."
        )

    connection.execute(
        "PRAGMA busy_timeout = 5000"
    )

    connection.execute(
        "PRAGMA secure_delete = ON"
    )

    secure_delete_row = connection.execute(
        "PRAGMA secure_delete"
    ).fetchone()

    if (
        secure_delete_row is None
        or int(secure_delete_row[0]) != 1
    ):
        raise DatabaseCompatibilityError(
            "SQLite secure_delete could not be enabled."
        )

    # Existing ATHENA databases may still contain historical frames
    # in their WAL. Fresh databases are still in DELETE mode and have
    # no WAL to checkpoint.
    if journal_mode == "wal":
        _checkpoint_wal_truncate_for_physical_cleanup(
            connection
        )

    # VACUUM must run outside a transaction. With secure_delete
    # enabled it rebuilds the main database using only reachable
    # logical content.
    connection.execute(
        "VACUUM"
    )

    # VACUUM in WAL mode may itself create WAL frames. Truncate them
    # before declaring the physical cleanup complete.
    if journal_mode == "wal":
        _checkpoint_wal_truncate_for_physical_cleanup(
            connection
        )

    quick_check = tuple(
        str(row[0])
        for row in connection.execute(
            "PRAGMA quick_check"
        )
    )

    if quick_check != ("ok",):
        raise DatabaseCompatibilityError(
            "ATHENA physical-cleanup integrity verification failed."
        )

    if connection.execute(
        "PRAGMA foreign_key_check"
    ).fetchall():
        raise DatabaseCompatibilityError(
            "ATHENA physical-cleanup foreign-key verification failed."
        )


def _migrate_schema_v37_to_v38(
    connection: sqlite3.Connection,
) -> None:
    """Physically purge unreachable historical operational-error bytes."""
    if connection.in_transaction:
        raise RuntimeError(
            "Operational-error physical-cleanup migration "
            "requires no active transaction."
        )

    _verify_schema_v37(
        connection
    )

    # Crucially, perform the physical work before advancing durable
    # schema metadata. A crash or failure before the final transaction
    # leaves the database at v37 so startup retries the cleanup.
    _physical_cleanup_operational_error_remnants(
        connection
    )

    try:
        connection.execute(
            "BEGIN IMMEDIATE"
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

        connection.execute(
            "COMMIT"
        )

    except BaseException:
        connection.rollback()
        raise
