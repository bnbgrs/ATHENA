"""ATHENA SQLite schema bootstrap, additive migrations, and compatibility checks."""

from __future__ import annotations

import sqlite3

ATHENA_APPLICATION_ID = 1_096_042_574  # ASCII "ATHN" / 0x4154484E
LEGACY_SCHEMA_VERSION = 1
KNOWLEDGE_SCHEMA_VERSION = 2
PROVENANCE_SCHEMA_VERSION = 3
MODEL_RUNS_SCHEMA_VERSION = 4
REVIEW_QUEUE_SCHEMA_VERSION = 5
MERGE_REVIEW_SCHEMA_VERSION = 6
MERGE_REVIEW_MULTI_TARGET_SCHEMA_VERSION = 7
EXTRACTION_SNAPSHOT_SCHEMA_VERSION = 8
LOCAL_FTS_SCHEMA_VERSION = 9
LOCAL_EMBEDDINGS_SCHEMA_VERSION = 10
SOURCE_CAPTURE_SCHEMA_VERSION = 11
SOURCE_REPRESENTATION_SCHEMA_VERSION = 12
SOURCE_CHUNK_PROFILE_SCHEMA_VERSION = 13
SOURCE_ANCHOR_SCHEMA_VERSION = 14
DURABLE_JOBS_SCHEMA_VERSION = 15
SOURCE_PAGE_MAP_SCHEMA_VERSION = 16
SOURCE_DOCUMENT_STRUCTURE_SCHEMA_VERSION = 17
SOURCE_ANALYSIS_SCHEMA_VERSION = 18
SOURCE_KNOWLEDGE_SCHEMA_VERSION = 19
SCHEMA_VERSION = SOURCE_KNOWLEDGE_SCHEMA_VERSION
STORAGE_LAYOUT_VERSION = 1
BLOB_FORMAT_VERSION = 1
KNOWLEDGE_CORE_MIGRATION_ID = "0002_knowledge_core"
PROVENANCE_INPUTS_MIGRATION_ID = "0003_provenance_inputs"
MODEL_RUNS_MIGRATION_ID = "0004_model_signatures_processing_runs"
REVIEW_QUEUE_MIGRATION_ID = "0005_semantic_review_queue"
MERGE_REVIEW_MIGRATION_ID = "0006_persistent_merge_review_decisions"
MERGE_REVIEW_MULTI_TARGET_MIGRATION_ID = "0007_merge_review_multi_target_identity"
EXTRACTION_SNAPSHOT_MIGRATION_ID = "0008_frozen_extraction_snapshots"
LOCAL_FTS_SEARCH_MIGRATION_ID = "0009_local_fts_search"
LOCAL_EMBEDDINGS_MIGRATION_ID = "0010_local_embeddings"
SOURCE_CAPTURE_MIGRATION_ID = "0011_source_capture"
SOURCE_REPRESENTATION_MIGRATION_ID = "0012_source_representations"
SOURCE_CHUNK_PROFILE_MIGRATION_ID = "0013_source_chunk_profiles"
SOURCE_ANCHOR_MIGRATION_ID = "0014_source_anchors"
DURABLE_JOBS_MIGRATION_ID = "0015_durable_jobs_checkpoints"
SOURCE_PAGE_MAP_MIGRATION_ID = "0016_source_representation_page_map"
SOURCE_DOCUMENT_STRUCTURE_MIGRATION_ID = "0017_source_representation_document_structure"
SOURCE_ANALYSIS_MIGRATION_ID = "0018_hierarchical_source_analysis"
SOURCE_KNOWLEDGE_MIGRATION_ID = "0019_source_analysis_knowledge_promotion"


class DatabaseCompatibilityError(RuntimeError):
    """Raised when a database cannot safely be opened by this ATHENA build."""


def _user_tables(connection: sqlite3.Connection) -> tuple[str, ...]:
    rows = connection.execute(
        """
        SELECT name
        FROM sqlite_master
        WHERE type = 'table'
          AND name NOT LIKE 'sqlite_%'
        ORDER BY name
        """
    ).fetchall()
    return tuple(str(row[0]) for row in rows)


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

    _configure_connection(connection)
    _verify_schema_v19(connection)


def _create_schema_v1(connection: sqlite3.Connection, *, created_at_us: int) -> None:
    """Create the historical v1 foundation used as the migration baseline."""
    connection.executescript(
        f"""
        BEGIN IMMEDIATE;

        CREATE TABLE schema_metadata (
            singleton_id INTEGER PRIMARY KEY CHECK(singleton_id = 1),
            schema_epoch INTEGER NOT NULL,
            schema_version INTEGER NOT NULL,
            storage_layout_version INTEGER NOT NULL,
            blob_format_version INTEGER NOT NULL,
            created_at_us INTEGER NOT NULL,
            last_migration_id TEXT NULL,
            minimum_reader_version INTEGER NOT NULL
        );

        INSERT INTO schema_metadata (
            singleton_id,
            schema_epoch,
            schema_version,
            storage_layout_version,
            blob_format_version,
            created_at_us,
            last_migration_id,
            minimum_reader_version
        ) VALUES (
            1,
            1,
            {LEGACY_SCHEMA_VERSION},
            {STORAGE_LAYOUT_VERSION},
            {BLOB_FORMAT_VERSION},
            {created_at_us},
            NULL,
            1
        );

        CREATE TABLE actors (
            actor_id BLOB(16) PRIMARY KEY CHECK(length(actor_id) = 16),
            actor_type TEXT NOT NULL CHECK(actor_type IN (
                'user', 'primary_model', 'infrastructure_model', 'plugin', 'system'
            )),
            display_name TEXT NULL,
            plugin_id BLOB(16) NULL CHECK(plugin_id IS NULL OR length(plugin_id) = 16),
            created_at_us INTEGER NOT NULL,
            active INTEGER NOT NULL CHECK(active IN (0, 1))
        ) WITHOUT ROWID;

        CREATE TABLE commit_records (
            commit_seq INTEGER PRIMARY KEY AUTOINCREMENT,
            commit_id BLOB(16) NOT NULL UNIQUE CHECK(length(commit_id) = 16),
            committed_at_us INTEGER NOT NULL,
            actor_id BLOB(16) NOT NULL CHECK(length(actor_id) = 16),
            operation_type TEXT NOT NULL,
            reason TEXT NULL,
            FOREIGN KEY(actor_id) REFERENCES actors(actor_id)
        );

        CREATE TABLE entity_registry (
            entity_id BLOB(16) PRIMARY KEY CHECK(length(entity_id) = 16),
            entity_type TEXT NOT NULL,
            domain TEXT NOT NULL CHECK(domain IN (
                'knowledge',
                'personal_memory',
                'raw_archive',
                'audit_provenance',
                'configuration',
                'operational'
            )),
            created_at_us INTEGER NOT NULL,
            created_by_actor_id BLOB(16) NULL,
            lifecycle_state TEXT NOT NULL,
            protection_scope_id BLOB(16) NULL,
            schema_version INTEGER NOT NULL,
            FOREIGN KEY(created_by_actor_id) REFERENCES actors(actor_id),
            CHECK(protection_scope_id IS NULL OR length(protection_scope_id) = 16)
        ) WITHOUT ROWID;

        CREATE TABLE entity_state_history (
            entity_id BLOB(16) NOT NULL CHECK(length(entity_id) = 16),
            valid_from_commit_seq INTEGER NOT NULL,
            valid_to_commit_seq INTEGER NULL,
            lifecycle_state TEXT NOT NULL,
            protection_scope_id BLOB(16) NULL,
            changed_by_actor_id BLOB(16) NOT NULL CHECK(length(changed_by_actor_id) = 16),
            reason TEXT NULL,
            PRIMARY KEY(entity_id, valid_from_commit_seq),
            FOREIGN KEY(entity_id) REFERENCES entity_registry(entity_id),
            FOREIGN KEY(valid_from_commit_seq) REFERENCES commit_records(commit_seq),
            FOREIGN KEY(valid_to_commit_seq) REFERENCES commit_records(commit_seq),
            FOREIGN KEY(changed_by_actor_id) REFERENCES actors(actor_id),
            CHECK(protection_scope_id IS NULL OR length(protection_scope_id) = 16)
        ) WITHOUT ROWID;

        CREATE TABLE provenance_records (
            provenance_id BLOB(16) PRIMARY KEY CHECK(length(provenance_id) = 16),
            subject_entity_id BLOB(16) NOT NULL CHECK(length(subject_entity_id) = 16),
            subject_revision_id BLOB(16) NULL,
            operation TEXT NOT NULL,
            actor_id BLOB(16) NOT NULL CHECK(length(actor_id) = 16),
            created_at_us INTEGER NOT NULL,
            model_signature_id BLOB(16) NULL,
            processing_run_id BLOB(16) NULL,
            reason TEXT NULL,
            protection_scope_id BLOB(16) NULL,
            FOREIGN KEY(subject_entity_id) REFERENCES entity_registry(entity_id),
            FOREIGN KEY(actor_id) REFERENCES actors(actor_id),
            FOREIGN KEY(subject_revision_id) REFERENCES revisions(revision_id)
                DEFERRABLE INITIALLY DEFERRED,
            CHECK(model_signature_id IS NULL OR length(model_signature_id) = 16),
            CHECK(processing_run_id IS NULL OR length(processing_run_id) = 16),
            CHECK(protection_scope_id IS NULL OR length(protection_scope_id) = 16)
        ) WITHOUT ROWID;

        CREATE TABLE revisions (
            revision_id BLOB(16) PRIMARY KEY CHECK(length(revision_id) = 16),
            entity_id BLOB(16) NOT NULL CHECK(length(entity_id) = 16),
            revision_no INTEGER NOT NULL CHECK(revision_no >= 1),
            parent_revision_id BLOB(16) NULL,
            created_at_us INTEGER NOT NULL,
            created_by_actor_id BLOB(16) NOT NULL CHECK(length(created_by_actor_id) = 16),
            provenance_id BLOB(16) NOT NULL CHECK(length(provenance_id) = 16),
            schema_version INTEGER NOT NULL,
            payload_hash BLOB(32) NOT NULL CHECK(length(payload_hash) = 32),
            change_kind TEXT NOT NULL,
            commit_id BLOB(16) NOT NULL CHECK(length(commit_id) = 16),
            UNIQUE(entity_id, revision_no),
            FOREIGN KEY(entity_id) REFERENCES entity_registry(entity_id),
            FOREIGN KEY(parent_revision_id) REFERENCES revisions(revision_id),
            FOREIGN KEY(created_by_actor_id) REFERENCES actors(actor_id),
            FOREIGN KEY(provenance_id) REFERENCES provenance_records(provenance_id)
                DEFERRABLE INITIALLY DEFERRED,
            FOREIGN KEY(commit_id) REFERENCES commit_records(commit_id)
        ) WITHOUT ROWID;

        CREATE TABLE entity_heads (
            entity_id BLOB(16) PRIMARY KEY CHECK(length(entity_id) = 16),
            current_revision_id BLOB(16) NOT NULL CHECK(length(current_revision_id) = 16),
            current_revision_no INTEGER NOT NULL CHECK(current_revision_no >= 1),
            FOREIGN KEY(entity_id) REFERENCES entity_registry(entity_id),
            FOREIGN KEY(current_revision_id) REFERENCES revisions(revision_id)
        ) WITHOUT ROWID;

        CREATE TABLE commit_changes (
            commit_seq INTEGER NOT NULL,
            entity_id BLOB(16) NOT NULL CHECK(length(entity_id) = 16),
            revision_id BLOB(16) NULL,
            change_type TEXT NOT NULL,
            PRIMARY KEY(commit_seq, entity_id, change_type),
            FOREIGN KEY(commit_seq) REFERENCES commit_records(commit_seq),
            FOREIGN KEY(entity_id) REFERENCES entity_registry(entity_id),
            FOREIGN KEY(revision_id) REFERENCES revisions(revision_id)
        ) WITHOUT ROWID;

        CREATE TABLE chats (
            chat_id BLOB(16) PRIMARY KEY CHECK(length(chat_id) = 16),
            started_at_us INTEGER NOT NULL,
            ended_at_us INTEGER NULL,
            archive_mode TEXT NOT NULL CHECK(archive_mode IN (
                'standard', 'temporary', 'do_not_store'
            )),
            lifecycle_state TEXT NOT NULL,
            protection_scope_id BLOB(16) NULL,
            FOREIGN KEY(chat_id) REFERENCES entity_registry(entity_id),
            CHECK(protection_scope_id IS NULL OR length(protection_scope_id) = 16)
        ) WITHOUT ROWID;

        CREATE TABLE chat_messages (
            message_id BLOB(16) PRIMARY KEY CHECK(length(message_id) = 16),
            chat_id BLOB(16) NOT NULL CHECK(length(chat_id) = 16),
            sequence_no INTEGER NOT NULL CHECK(sequence_no >= 1),
            message_type TEXT NOT NULL CHECK(message_type IN (
                'user', 'assistant', 'tool_result', 'system_event'
            )),
            actor_id BLOB(16) NULL,
            UNIQUE(chat_id, sequence_no),
            FOREIGN KEY(message_id) REFERENCES entity_registry(entity_id),
            FOREIGN KEY(chat_id) REFERENCES chats(chat_id),
            FOREIGN KEY(actor_id) REFERENCES actors(actor_id)
        ) WITHOUT ROWID;

        CREATE TABLE chat_message_revisions (
            revision_id BLOB(16) PRIMARY KEY CHECK(length(revision_id) = 16),
            content TEXT NULL,
            content_format TEXT NULL,
            protected_payload_id BLOB(16) NULL,
            FOREIGN KEY(revision_id) REFERENCES revisions(revision_id),
            CHECK(protected_payload_id IS NULL OR length(protected_payload_id) = 16)
        ) WITHOUT ROWID;

        CREATE INDEX idx_chat_messages_chat_sequence
            ON chat_messages(chat_id, sequence_no);
        CREATE INDEX idx_revisions_entity_revision
            ON revisions(entity_id, revision_no);
        CREATE INDEX idx_commit_changes_entity
            ON commit_changes(entity_id, commit_seq);

        PRAGMA user_version = {LEGACY_SCHEMA_VERSION};
        COMMIT;
        """
    )


def _migrate_schema_v1_to_v2(connection: sqlite3.Connection) -> None:
    """Add the canonical Knowledge/Claim tables without rewriting v1 data."""
    connection.executescript(
        f"""
        BEGIN IMMEDIATE;

        CREATE TABLE knowledge_units (
            knowledge_id BLOB(16) PRIMARY KEY CHECK(length(knowledge_id) = 16),
            FOREIGN KEY(knowledge_id) REFERENCES entity_registry(entity_id)
        ) WITHOUT ROWID;

        CREATE TABLE knowledge_unit_revisions (
            revision_id BLOB(16) PRIMARY KEY CHECK(length(revision_id) = 16),
            knowledge_kind TEXT NULL,
            title TEXT NULL,
            body TEXT NULL,
            valid_from_us INTEGER NULL,
            valid_to_us INTEGER NULL,
            epistemic_status TEXT NULL,
            protected_payload_id BLOB(16) NULL,
            FOREIGN KEY(revision_id) REFERENCES revisions(revision_id),
            CHECK(valid_to_us IS NULL OR valid_from_us IS NULL OR valid_to_us >= valid_from_us),
            CHECK(protected_payload_id IS NULL OR length(protected_payload_id) = 16)
        ) WITHOUT ROWID;

        CREATE TABLE claims (
            claim_id BLOB(16) PRIMARY KEY CHECK(length(claim_id) = 16),
            FOREIGN KEY(claim_id) REFERENCES entity_registry(entity_id)
        ) WITHOUT ROWID;

        CREATE TABLE claim_revisions (
            revision_id BLOB(16) PRIMARY KEY CHECK(length(revision_id) = 16),
            claim_kind TEXT NULL,
            statement TEXT NULL,
            subject_entity_id BLOB(16) NULL,
            predicate TEXT NULL,
            object_entity_id BLOB(16) NULL,
            attributed_to_entity_id BLOB(16) NULL,
            valid_from_us INTEGER NULL,
            valid_to_us INTEGER NULL,
            epistemic_status TEXT NULL,
            protected_payload_id BLOB(16) NULL,
            FOREIGN KEY(revision_id) REFERENCES revisions(revision_id),
            FOREIGN KEY(subject_entity_id) REFERENCES entity_registry(entity_id),
            FOREIGN KEY(object_entity_id) REFERENCES entity_registry(entity_id),
            FOREIGN KEY(attributed_to_entity_id) REFERENCES entity_registry(entity_id),
            CHECK(subject_entity_id IS NULL OR length(subject_entity_id) = 16),
            CHECK(object_entity_id IS NULL OR length(object_entity_id) = 16),
            CHECK(attributed_to_entity_id IS NULL OR length(attributed_to_entity_id) = 16),
            CHECK(valid_to_us IS NULL OR valid_from_us IS NULL OR valid_to_us >= valid_from_us),
            CHECK(protected_payload_id IS NULL OR length(protected_payload_id) = 16)
        ) WITHOUT ROWID;

        CREATE TABLE claim_evidence (
            claim_id BLOB(16) NOT NULL CHECK(length(claim_id) = 16),
            anchor_id BLOB(16) NULL,
            message_id BLOB(16) NULL,
            evidence_entity_id BLOB(16) NULL,
            evidence_revision_id BLOB(16) NULL,
            evidence_role TEXT NOT NULL,
            provenance_id BLOB(16) NOT NULL CHECK(length(provenance_id) = 16),
            FOREIGN KEY(claim_id) REFERENCES claims(claim_id),
            FOREIGN KEY(message_id) REFERENCES chat_messages(message_id),
            FOREIGN KEY(evidence_entity_id) REFERENCES entity_registry(entity_id),
            FOREIGN KEY(evidence_revision_id) REFERENCES revisions(revision_id),
            FOREIGN KEY(provenance_id) REFERENCES provenance_records(provenance_id),
            CHECK(anchor_id IS NULL OR length(anchor_id) = 16),
            CHECK(message_id IS NULL OR length(message_id) = 16),
            CHECK(evidence_entity_id IS NULL OR length(evidence_entity_id) = 16),
            CHECK(evidence_revision_id IS NULL OR length(evidence_revision_id) = 16),
            CHECK(
                anchor_id IS NOT NULL
                OR message_id IS NOT NULL
                OR evidence_entity_id IS NOT NULL
                OR evidence_revision_id IS NOT NULL
            ),
            UNIQUE(
                claim_id,
                anchor_id,
                message_id,
                evidence_entity_id,
                evidence_revision_id,
                evidence_role
            )
        );

        CREATE INDEX idx_knowledge_unit_revisions_kind
            ON knowledge_unit_revisions(knowledge_kind);
        CREATE INDEX idx_claim_revisions_kind
            ON claim_revisions(claim_kind);
        CREATE INDEX idx_claim_revisions_subject_predicate
            ON claim_revisions(subject_entity_id, predicate);
        CREATE INDEX idx_claim_evidence_claim
            ON claim_evidence(claim_id);
        CREATE INDEX idx_claim_evidence_message
            ON claim_evidence(message_id)
            WHERE message_id IS NOT NULL;

        UPDATE schema_metadata
        SET schema_version = {KNOWLEDGE_SCHEMA_VERSION},
            last_migration_id = '{KNOWLEDGE_CORE_MIGRATION_ID}',
            minimum_reader_version = {KNOWLEDGE_SCHEMA_VERSION}
        WHERE singleton_id = 1;

        PRAGMA user_version = {KNOWLEDGE_SCHEMA_VERSION};
        COMMIT;
        """
    )


def _migrate_schema_v2_to_v3(connection: sqlite3.Connection) -> None:
    """Add explicit multi-input provenance required by semantic writes."""
    connection.executescript(
        f"""
        BEGIN IMMEDIATE;

        CREATE TABLE provenance_inputs (
            provenance_id BLOB(16) NOT NULL CHECK(length(provenance_id) = 16),
            input_entity_id BLOB(16) NOT NULL CHECK(length(input_entity_id) = 16),
            input_revision_id BLOB(16) NULL,
            input_role TEXT NOT NULL,
            ordinal INTEGER NOT NULL CHECK(ordinal >= 0),
            PRIMARY KEY(provenance_id, ordinal),
            FOREIGN KEY(provenance_id) REFERENCES provenance_records(provenance_id),
            FOREIGN KEY(input_entity_id) REFERENCES entity_registry(entity_id),
            FOREIGN KEY(input_revision_id) REFERENCES revisions(revision_id),
            CHECK(input_revision_id IS NULL OR length(input_revision_id) = 16)
        ) WITHOUT ROWID;

        CREATE UNIQUE INDEX uq_provenance_inputs_revision
            ON provenance_inputs(
                provenance_id, input_entity_id, input_revision_id, input_role
            )
            WHERE input_revision_id IS NOT NULL;

        CREATE UNIQUE INDEX uq_provenance_inputs_entity_only
            ON provenance_inputs(provenance_id, input_entity_id, input_role)
            WHERE input_revision_id IS NULL;

        CREATE INDEX idx_provenance_inputs_entity
            ON provenance_inputs(input_entity_id, input_revision_id);

        UPDATE schema_metadata
        SET schema_version = {PROVENANCE_SCHEMA_VERSION},
            last_migration_id = '{PROVENANCE_INPUTS_MIGRATION_ID}',
            minimum_reader_version = {PROVENANCE_SCHEMA_VERSION}
        WHERE singleton_id = 1;

        PRAGMA user_version = {PROVENANCE_SCHEMA_VERSION};
        COMMIT;
        """
    )



def _migrate_schema_v3_to_v4(connection: sqlite3.Connection) -> None:
    """Add reproducibility metadata required for model-driven semantic work."""
    connection.executescript(
        f"""
        BEGIN IMMEDIATE;

        CREATE TABLE model_signatures (
            model_signature_id BLOB(16) PRIMARY KEY CHECK(length(model_signature_id) = 16),
            provider TEXT NOT NULL,
            model_identifier TEXT NOT NULL,
            model_revision TEXT NULL,
            quantization TEXT NULL,
            generation_parameters_json TEXT NOT NULL,
            context_configuration_json TEXT NULL,
            signature_hash BLOB(32) NOT NULL UNIQUE CHECK(length(signature_hash) = 32),
            created_at_us INTEGER NOT NULL
        ) WITHOUT ROWID;

        CREATE TABLE processing_runs (
            processing_run_id BLOB(16) PRIMARY KEY CHECK(length(processing_run_id) = 16),
            run_type TEXT NOT NULL,
            started_at_us INTEGER NOT NULL,
            finished_at_us INTEGER NULL,
            status TEXT NOT NULL CHECK(status IN (
                'running', 'succeeded', 'failed', 'cancelled'
            )),
            trigger_actor_id BLOB(16) NOT NULL CHECK(length(trigger_actor_id) = 16),
            pipeline_version TEXT NOT NULL,
            input_snapshot_json TEXT NOT NULL,
            configuration_hash BLOB(32) NOT NULL CHECK(length(configuration_hash) = 32),
            model_signature_id BLOB(16) NULL,
            prompt_template_id TEXT NULL,
            prompt_template_version TEXT NULL,
            error_detail TEXT NULL,
            FOREIGN KEY(trigger_actor_id) REFERENCES actors(actor_id),
            FOREIGN KEY(model_signature_id) REFERENCES model_signatures(model_signature_id),
            CHECK(model_signature_id IS NULL OR length(model_signature_id) = 16),
            CHECK(finished_at_us IS NULL OR finished_at_us >= started_at_us),
            CHECK(
                (status = 'running' AND finished_at_us IS NULL)
                OR (status != 'running' AND finished_at_us IS NOT NULL)
            )
        ) WITHOUT ROWID;

        CREATE INDEX idx_processing_runs_status_started
            ON processing_runs(status, started_at_us);
        CREATE INDEX idx_processing_runs_model_signature
            ON processing_runs(model_signature_id)
            WHERE model_signature_id IS NOT NULL;

        UPDATE schema_metadata
        SET schema_version = {MODEL_RUNS_SCHEMA_VERSION},
            last_migration_id = '{MODEL_RUNS_MIGRATION_ID}',
            minimum_reader_version = {MODEL_RUNS_SCHEMA_VERSION}
        WHERE singleton_id = 1;

        PRAGMA user_version = {MODEL_RUNS_SCHEMA_VERSION};
        COMMIT;
        """
    )


def _migrate_schema_v4_to_v5(connection: sqlite3.Connection) -> None:
    """Add a persistent queue for semantic decisions that require user review."""
    connection.executescript(
        f"""
        BEGIN IMMEDIATE;

        CREATE TABLE semantic_review_items (
            review_id BLOB(16) PRIMARY KEY CHECK(length(review_id) = 16),
            review_type TEXT NOT NULL CHECK(review_type IN (
                'contradiction', 'merge_candidate'
            )),
            status TEXT NOT NULL CHECK(status IN (
                'pending', 'accepted', 'rejected', 'superseded'
            )),
            created_at_us INTEGER NOT NULL,
            resolved_at_us INTEGER NULL,
            processing_run_id BLOB(16) NOT NULL CHECK(length(processing_run_id) = 16),
            model_signature_id BLOB(16) NOT NULL CHECK(length(model_signature_id) = 16),
            left_entity_id BLOB(16) NULL CHECK(
                left_entity_id IS NULL OR length(left_entity_id) = 16
            ),
            left_revision_id BLOB(16) NULL CHECK(
                left_revision_id IS NULL OR length(left_revision_id) = 16
            ),
            right_entity_id BLOB(16) NULL CHECK(
                right_entity_id IS NULL OR length(right_entity_id) = 16
            ),
            right_revision_id BLOB(16) NULL CHECK(
                right_revision_id IS NULL OR length(right_revision_id) = 16
            ),
            confidence REAL NOT NULL CHECK(confidence >= 0.0 AND confidence <= 1.0),
            reason TEXT NOT NULL,
            decision_actor_id BLOB(16) NULL CHECK(
                decision_actor_id IS NULL OR length(decision_actor_id) = 16
            ),
            decision_reason TEXT NULL,
            FOREIGN KEY(processing_run_id) REFERENCES processing_runs(processing_run_id),
            FOREIGN KEY(model_signature_id) REFERENCES model_signatures(model_signature_id),
            FOREIGN KEY(left_entity_id) REFERENCES entity_registry(entity_id),
            FOREIGN KEY(left_revision_id) REFERENCES revisions(revision_id),
            FOREIGN KEY(right_entity_id) REFERENCES entity_registry(entity_id),
            FOREIGN KEY(right_revision_id) REFERENCES revisions(revision_id),
            FOREIGN KEY(decision_actor_id) REFERENCES actors(actor_id),
            CHECK(
                (status = 'pending' AND resolved_at_us IS NULL AND decision_actor_id IS NULL)
                OR
                (status != 'pending' AND resolved_at_us IS NOT NULL AND decision_actor_id IS NOT NULL)
            ),
            CHECK(
                review_type != 'contradiction'
                OR (
                    left_entity_id IS NOT NULL
                    AND left_revision_id IS NOT NULL
                    AND right_entity_id IS NOT NULL
                    AND right_revision_id IS NOT NULL
                    AND left_entity_id != right_entity_id
                )
            )
        ) WITHOUT ROWID;

        CREATE UNIQUE INDEX uq_pending_contradiction_review
            ON semantic_review_items(
                review_type, left_entity_id, right_entity_id
            )
            WHERE status = 'pending' AND review_type = 'contradiction';

        CREATE INDEX idx_semantic_review_pending
            ON semantic_review_items(status, review_type, created_at_us);

        UPDATE schema_metadata
        SET schema_version = {REVIEW_QUEUE_SCHEMA_VERSION},
            last_migration_id = '{REVIEW_QUEUE_MIGRATION_ID}',
            minimum_reader_version = {REVIEW_QUEUE_SCHEMA_VERSION}
        WHERE singleton_id = 1;

        PRAGMA user_version = {REVIEW_QUEUE_SCHEMA_VERSION};
        COMMIT;
        """
    )


def _migrate_schema_v5_to_v6(connection: sqlite3.Connection) -> None:
    """Persist merge-candidate identity and the user's explicit resolution."""
    connection.executescript(
        f"""
        BEGIN IMMEDIATE;

        CREATE TABLE semantic_merge_review_payloads (
            review_id BLOB(16) PRIMARY KEY CHECK(length(review_id) = 16),
            proposal_type TEXT NOT NULL CHECK(proposal_type IN ('knowledge', 'claim')),
            proposal_index INTEGER NOT NULL CHECK(proposal_index >= 0),
            source_entity_id BLOB(16) NOT NULL CHECK(length(source_entity_id) = 16),
            source_revision_id BLOB(16) NOT NULL CHECK(length(source_revision_id) = 16),
            proposal_text TEXT NOT NULL CHECK(length(proposal_text) > 0),
            proposal_kind TEXT NOT NULL CHECK(length(proposal_kind) > 0),
            proposal_epistemic_status TEXT NOT NULL CHECK(length(proposal_epistemic_status) > 0),
            similarity REAL NOT NULL CHECK(similarity >= 0.0 AND similarity <= 1.0),
            decision TEXT NULL CHECK(decision IN ('merge', 'keep_separate')),
            FOREIGN KEY(review_id) REFERENCES semantic_review_items(review_id) ON DELETE CASCADE,
            FOREIGN KEY(source_entity_id) REFERENCES entity_registry(entity_id),
            FOREIGN KEY(source_revision_id) REFERENCES revisions(revision_id)
        ) WITHOUT ROWID;

        CREATE UNIQUE INDEX uq_semantic_merge_review_identity
            ON semantic_merge_review_payloads(
                proposal_type,
                source_entity_id,
                source_revision_id,
                proposal_kind,
                proposal_epistemic_status,
                proposal_text
            );

        CREATE INDEX idx_semantic_merge_review_decision
            ON semantic_merge_review_payloads(decision);

        UPDATE schema_metadata
        SET schema_version = {MERGE_REVIEW_SCHEMA_VERSION},
            last_migration_id = '{MERGE_REVIEW_MIGRATION_ID}',
            minimum_reader_version = {MERGE_REVIEW_SCHEMA_VERSION}
        WHERE singleton_id = 1;

        PRAGMA user_version = {MERGE_REVIEW_SCHEMA_VERSION};
        COMMIT;
        """
    )


def _migrate_schema_v6_to_v7(connection: sqlite3.Connection) -> None:
    """Allow one proposal to have multiple distinct canonical merge targets."""
    connection.executescript(
        f"""
        BEGIN IMMEDIATE;

        DROP INDEX IF EXISTS uq_semantic_merge_review_identity;

        CREATE INDEX idx_semantic_merge_review_identity
            ON semantic_merge_review_payloads(
                proposal_type,
                source_entity_id,
                source_revision_id,
                proposal_kind,
                proposal_epistemic_status,
                proposal_text
            );

        CREATE UNIQUE INDEX uq_semantic_merge_review_target
            ON semantic_review_items(
                review_type,
                processing_run_id,
                left_entity_id,
                left_revision_id
            )
            WHERE review_type = 'merge_candidate';

        UPDATE schema_metadata
        SET schema_version = {MERGE_REVIEW_MULTI_TARGET_SCHEMA_VERSION},
            last_migration_id = '{MERGE_REVIEW_MULTI_TARGET_MIGRATION_ID}',
            minimum_reader_version = {MERGE_REVIEW_MULTI_TARGET_SCHEMA_VERSION}
        WHERE singleton_id = 1;

        PRAGMA user_version = {MERGE_REVIEW_MULTI_TARGET_SCHEMA_VERSION};
        COMMIT;
        """
    )


def _migrate_schema_v7_to_v8(connection: sqlite3.Connection) -> None:
    """Persist immutable proposal snapshots for reproducible post-review acceptance."""
    connection.executescript(
        f"""
        BEGIN IMMEDIATE;

        CREATE TABLE extraction_result_snapshots (
            processing_run_id BLOB(16) PRIMARY KEY CHECK(length(processing_run_id) = 16),
            chat_id BLOB(16) NOT NULL CHECK(length(chat_id) = 16),
            model_json TEXT NOT NULL CHECK(length(model_json) > 0),
            proposals_json TEXT NOT NULL CHECK(length(proposals_json) > 0),
            created_at_us INTEGER NOT NULL,
            FOREIGN KEY(processing_run_id) REFERENCES processing_runs(processing_run_id),
            FOREIGN KEY(chat_id) REFERENCES entity_registry(entity_id)
        ) WITHOUT ROWID;

        CREATE INDEX idx_extraction_result_snapshots_chat
            ON extraction_result_snapshots(chat_id, created_at_us);

        UPDATE schema_metadata
        SET schema_version = {EXTRACTION_SNAPSHOT_SCHEMA_VERSION},
            last_migration_id = '{EXTRACTION_SNAPSHOT_MIGRATION_ID}',
            minimum_reader_version = {EXTRACTION_SNAPSHOT_SCHEMA_VERSION}
        WHERE singleton_id = 1;

        PRAGMA user_version = {EXTRACTION_SNAPSHOT_SCHEMA_VERSION};
        COMMIT;
        """
    )


def _migrate_schema_v8_to_v9(connection: sqlite3.Connection) -> None:
    """Add a reconstructible local FTS5 index for current unprotected text."""
    try:
        connection.executescript(
            f"""
            BEGIN IMMEDIATE;

            CREATE VIRTUAL TABLE search_fts USING fts5(
                entity_id UNINDEXED,
                revision_id UNINDEXED,
                entity_type UNINDEXED,
                title,
                body,
                tokenize = 'unicode61 remove_diacritics 2'
            );

            CREATE TABLE search_index_state (
                singleton_id INTEGER PRIMARY KEY CHECK(singleton_id = 1),
                indexed_commit_seq INTEGER NOT NULL CHECK(indexed_commit_seq >= 0),
                rebuilt_at_us INTEGER NOT NULL
            );

            INSERT INTO search_index_state (
                singleton_id, indexed_commit_seq, rebuilt_at_us
            ) VALUES (1, 0, 0);

            UPDATE schema_metadata
            SET schema_version = {LOCAL_FTS_SCHEMA_VERSION},
                last_migration_id = '{LOCAL_FTS_SEARCH_MIGRATION_ID}',
                minimum_reader_version = {LOCAL_FTS_SCHEMA_VERSION}
            WHERE singleton_id = 1;

            PRAGMA user_version = {LOCAL_FTS_SCHEMA_VERSION};
            COMMIT;
            """
        )
    except sqlite3.OperationalError as exc:
        if connection.in_transaction:
            connection.execute("ROLLBACK")
        raise DatabaseCompatibilityError(
            "ATHENA local retrieval requires SQLite FTS5 support."
        ) from exc


def _migrate_schema_v9_to_v10(connection: sqlite3.Connection) -> None:
    """Add reconstructible local embedding vectors for hybrid retrieval."""
    connection.executescript(
        f"""
        BEGIN IMMEDIATE;

        CREATE TABLE search_embeddings (
            entity_type TEXT NOT NULL
                CHECK(entity_type IN ('knowledge', 'claim', 'chat_message')),
            entity_id BLOB(16) NOT NULL CHECK(length(entity_id) = 16),
            revision_id BLOB(16) NOT NULL CHECK(length(revision_id) = 16),
            model_id TEXT NOT NULL CHECK(length(model_id) > 0),
            dimensions INTEGER NOT NULL CHECK(dimensions > 0),
            vector_blob BLOB NOT NULL CHECK(length(vector_blob) = dimensions * 4),
            text_sha256 BLOB(32) NOT NULL CHECK(length(text_sha256) = 32),
            created_at_us INTEGER NOT NULL,
            PRIMARY KEY(entity_type, entity_id, revision_id, model_id)
        ) WITHOUT ROWID;

        CREATE INDEX idx_search_embeddings_model
            ON search_embeddings(model_id, entity_type);

        CREATE TABLE search_embedding_state (
            model_id TEXT PRIMARY KEY CHECK(length(model_id) > 0),
            indexed_commit_seq INTEGER NOT NULL CHECK(indexed_commit_seq >= 0),
            dimensions INTEGER NOT NULL CHECK(dimensions > 0),
            document_count INTEGER NOT NULL CHECK(document_count >= 0),
            rebuilt_at_us INTEGER NOT NULL
        ) WITHOUT ROWID;

        UPDATE schema_metadata
        SET schema_version = {LOCAL_EMBEDDINGS_SCHEMA_VERSION},
            last_migration_id = '{LOCAL_EMBEDDINGS_MIGRATION_ID}',
            minimum_reader_version = {LOCAL_EMBEDDINGS_SCHEMA_VERSION}
        WHERE singleton_id = 1;

        PRAGMA user_version = {LOCAL_EMBEDDINGS_SCHEMA_VERSION};
        COMMIT;
        """
    )


def _migrate_schema_v10_to_v11(connection: sqlite3.Connection) -> None:
    """Add authoritative Raw Archive Source and immutable BlobRecord capture."""
    connection.executescript(
        f"""
        BEGIN IMMEDIATE;

        CREATE TABLE blob_records (
            blob_id BLOB(16) PRIMARY KEY CHECK(length(blob_id) = 16),
            byte_length INTEGER NOT NULL CHECK(byte_length >= 0),
            media_type TEXT NULL,
            storage_area TEXT NOT NULL CHECK(storage_area IN ('archive', 'spool')),
            storage_locator TEXT NOT NULL CHECK(length(storage_locator) > 0),
            integrity_sha256 BLOB(32) NOT NULL CHECK(length(integrity_sha256) = 32),
            encryption_state TEXT NOT NULL CHECK(encryption_state IN ('none')),
            created_at_us INTEGER NOT NULL,
            verified_at_us INTEGER NOT NULL,
            UNIQUE(integrity_sha256, byte_length, encryption_state),
            UNIQUE(storage_area, storage_locator),
            FOREIGN KEY(blob_id) REFERENCES entity_registry(entity_id)
        ) WITHOUT ROWID;

        CREATE TABLE sources (
            source_id BLOB(16) PRIMARY KEY CHECK(length(source_id) = 16),
            source_type TEXT NOT NULL CHECK(source_type IN (
                'file', 'web_snapshot', 'email', 'text', 'image',
                'audio', 'video', 'document', 'api_capture',
                'chat_export', 'other'
            )),
            created_at_us INTEGER NOT NULL,
            acquired_at_us INTEGER NOT NULL,
            original_name TEXT NULL,
            original_modified_at_us INTEGER NULL,
            mime_type TEXT NULL,
            blob_id BLOB(16) NOT NULL CHECK(length(blob_id) = 16),
            content_sha256 BLOB(32) NOT NULL CHECK(length(content_sha256) = 32),
            source_uri TEXT NULL,
            lifecycle_state TEXT NOT NULL CHECK(lifecycle_state IN (
                'captured', 'processing', 'ready', 'partial',
                'failed', 'quarantined', 'cancelled'
            )),
            provenance_id BLOB(16) NOT NULL CHECK(length(provenance_id) = 16),
            FOREIGN KEY(source_id) REFERENCES entity_registry(entity_id),
            FOREIGN KEY(blob_id) REFERENCES blob_records(blob_id),
            FOREIGN KEY(provenance_id) REFERENCES provenance_records(provenance_id)
        ) WITHOUT ROWID;

        CREATE INDEX idx_sources_acquired_at
            ON sources(acquired_at_us DESC, source_id);
        CREATE INDEX idx_sources_blob
            ON sources(blob_id);

        UPDATE schema_metadata
        SET schema_version = {SOURCE_CAPTURE_SCHEMA_VERSION},
            last_migration_id = '{SOURCE_CAPTURE_MIGRATION_ID}',
            minimum_reader_version = {SOURCE_CAPTURE_SCHEMA_VERSION}
        WHERE singleton_id = 1;

        PRAGMA user_version = {SOURCE_CAPTURE_SCHEMA_VERSION};
        COMMIT;
        """
    )


def _migrate_schema_v11_to_v12(connection: sqlite3.Connection) -> None:
    """Add immutable retained SourceRepresentations backed by concrete runs."""
    connection.executescript(
        f"""
        BEGIN IMMEDIATE;

        CREATE TABLE source_representations (
            representation_id BLOB(16) PRIMARY KEY CHECK(length(representation_id) = 16),
            source_id BLOB(16) NOT NULL CHECK(length(source_id) = 16),
            representation_type TEXT NOT NULL CHECK(representation_type IN (
                'normalized_text', 'extracted_text', 'ocr_text', 'transcript',
                'thumbnail', 'page_images'
            )),
            blob_id BLOB(16) NOT NULL CHECK(length(blob_id) = 16),
            processing_run_id BLOB(16) NOT NULL CHECK(length(processing_run_id) = 16),
            content_hash BLOB(32) NOT NULL CHECK(length(content_hash) = 32),
            retention_state TEXT NOT NULL CHECK(retention_state IN ('disposable', 'retained')),
            media_type TEXT NOT NULL CHECK(length(media_type) > 0),
            parser_id TEXT NOT NULL CHECK(length(parser_id) > 0),
            parser_version TEXT NOT NULL CHECK(length(parser_version) > 0),
            options_json TEXT NOT NULL CHECK(json_valid(options_json)),
            created_at_us INTEGER NOT NULL,
            provenance_id BLOB(16) NOT NULL CHECK(length(provenance_id) = 16),
            FOREIGN KEY(representation_id) REFERENCES entity_registry(entity_id),
            FOREIGN KEY(source_id) REFERENCES sources(source_id),
            FOREIGN KEY(blob_id) REFERENCES blob_records(blob_id),
            FOREIGN KEY(processing_run_id) REFERENCES processing_runs(processing_run_id),
            FOREIGN KEY(provenance_id) REFERENCES provenance_records(provenance_id)
        ) WITHOUT ROWID;

        CREATE INDEX idx_source_representations_source_created
            ON source_representations(source_id, created_at_us DESC, representation_id);
        CREATE INDEX idx_source_representations_run
            ON source_representations(processing_run_id);

        UPDATE schema_metadata
        SET schema_version = {SOURCE_REPRESENTATION_SCHEMA_VERSION},
            last_migration_id = '{SOURCE_REPRESENTATION_MIGRATION_ID}',
            minimum_reader_version = {SOURCE_REPRESENTATION_SCHEMA_VERSION}
        WHERE singleton_id = 1;

        PRAGMA user_version = {SOURCE_REPRESENTATION_SCHEMA_VERSION};
        COMMIT;
        """
    )


def _migrate_schema_v12_to_v13(connection: sqlite3.Connection) -> None:
    """Add durable versioned chunking profiles; SourceChunks remain Derived State."""
    connection.executescript(
        f"""
        BEGIN IMMEDIATE;

        CREATE TABLE chunking_profiles (
            chunking_profile_id BLOB(16) PRIMARY KEY CHECK(length(chunking_profile_id) = 16),
            algorithm TEXT NOT NULL CHECK(length(algorithm) > 0),
            tokenizer TEXT NULL,
            target_size INTEGER NULL CHECK(target_size IS NULL OR target_size > 0),
            overlap_size INTEGER NULL CHECK(overlap_size IS NULL OR overlap_size >= 0),
            structure_rules_json TEXT NOT NULL CHECK(json_valid(structure_rules_json)),
            profile_version INTEGER NOT NULL CHECK(profile_version > 0),
            configuration_hash BLOB(32) NOT NULL UNIQUE CHECK(length(configuration_hash) = 32),
            created_at_us INTEGER NOT NULL
        ) WITHOUT ROWID;

        UPDATE schema_metadata
        SET schema_version = {SOURCE_CHUNK_PROFILE_SCHEMA_VERSION},
            last_migration_id = '{SOURCE_CHUNK_PROFILE_MIGRATION_ID}',
            minimum_reader_version = {SOURCE_CHUNK_PROFILE_SCHEMA_VERSION}
        WHERE singleton_id = 1;

        PRAGMA user_version = {SOURCE_CHUNK_PROFILE_SCHEMA_VERSION};
        COMMIT;
        """
    )


def _migrate_schema_v13_to_v14(connection: sqlite3.Connection) -> None:
    """Add persistent SourceAnchors for durable evidence across re-chunking."""
    connection.executescript(
        f"""
        BEGIN IMMEDIATE;

        CREATE TABLE source_anchors (
            anchor_id BLOB(16) PRIMARY KEY CHECK(length(anchor_id) = 16),
            source_id BLOB(16) NOT NULL CHECK(length(source_id) = 16),
            representation_id BLOB(16) NULL CHECK(representation_id IS NULL OR length(representation_id) = 16),
            anchor_type TEXT NOT NULL CHECK(anchor_type IN (
                'whole_source', 'text_range', 'page_range', 'page_region',
                'audio_time_range', 'video_time_range', 'table_cell',
                'message', 'structured_path'
            )),
            start_offset INTEGER NULL CHECK(start_offset IS NULL OR start_offset >= 0),
            end_offset INTEGER NULL CHECK(end_offset IS NULL OR end_offset >= 0),
            page_start INTEGER NULL CHECK(page_start IS NULL OR page_start >= 1),
            page_end INTEGER NULL CHECK(page_end IS NULL OR page_end >= 1),
            start_time_ms INTEGER NULL CHECK(start_time_ms IS NULL OR start_time_ms >= 0),
            end_time_ms INTEGER NULL CHECK(end_time_ms IS NULL OR end_time_ms >= 0),
            geometry_json TEXT NULL CHECK(geometry_json IS NULL OR json_valid(geometry_json)),
            quoted_hash BLOB(32) NULL CHECK(quoted_hash IS NULL OR length(quoted_hash) = 32),
            FOREIGN KEY(anchor_id) REFERENCES entity_registry(entity_id),
            FOREIGN KEY(source_id) REFERENCES sources(source_id),
            FOREIGN KEY(representation_id) REFERENCES source_representations(representation_id),
            CHECK(end_offset IS NULL OR start_offset IS NOT NULL),
            CHECK(end_offset IS NULL OR end_offset >= start_offset),
            CHECK(page_end IS NULL OR page_start IS NOT NULL),
            CHECK(page_end IS NULL OR page_end >= page_start),
            CHECK(end_time_ms IS NULL OR start_time_ms IS NOT NULL),
            CHECK(end_time_ms IS NULL OR end_time_ms >= start_time_ms),
            CHECK(anchor_type != 'text_range' OR (
                representation_id IS NOT NULL AND start_offset IS NOT NULL
                AND end_offset IS NOT NULL AND quoted_hash IS NOT NULL
            ))
        ) WITHOUT ROWID;

        CREATE UNIQUE INDEX uq_source_anchor_text_range
            ON source_anchors(
                source_id, representation_id, start_offset, end_offset, quoted_hash
            )
            WHERE anchor_type = 'text_range';
        CREATE INDEX idx_source_anchors_source
            ON source_anchors(source_id, anchor_type, anchor_id);
        CREATE INDEX idx_source_anchors_representation
            ON source_anchors(representation_id, anchor_type, anchor_id)
            WHERE representation_id IS NOT NULL;

        UPDATE schema_metadata
        SET schema_version = {SOURCE_ANCHOR_SCHEMA_VERSION},
            last_migration_id = '{SOURCE_ANCHOR_MIGRATION_ID}',
            minimum_reader_version = {SOURCE_ANCHOR_SCHEMA_VERSION}
        WHERE singleton_id = 1;

        PRAGMA user_version = {SOURCE_ANCHOR_SCHEMA_VERSION};
        COMMIT;
        """
    )


def _migrate_schema_v14_to_v15(connection: sqlite3.Connection) -> None:
    """Add durable jobs, worker leases/fencing, and confirmed checkpoints."""
    connection.executescript(
        f"""
        BEGIN IMMEDIATE;

        CREATE TABLE jobs (
            job_id BLOB(16) PRIMARY KEY CHECK(length(job_id) = 16),
            job_type TEXT NOT NULL CHECK(length(job_type) > 0),
            created_at_us INTEGER NOT NULL,
            created_by_actor_id BLOB(16) NOT NULL CHECK(length(created_by_actor_id) = 16),
            priority INTEGER NOT NULL CHECK(priority BETWEEN 0 AND 5),
            state TEXT NOT NULL CHECK(state IN (
                'queued', 'waiting', 'running', 'paused',
                'cancel_requested', 'cancelled', 'failed', 'completed'
            )),
            requested_scope_json TEXT NULL CHECK(
                requested_scope_json IS NULL OR json_valid(requested_scope_json)
            ),
            processing_run_id BLOB(16) NULL CHECK(
                processing_run_id IS NULL OR length(processing_run_id) = 16
            ),
            current_stage TEXT NULL,
            last_checkpoint_id BLOB(16) NULL CHECK(
                last_checkpoint_id IS NULL OR length(last_checkpoint_id) = 16
            ),
            retry_count INTEGER NOT NULL CHECK(retry_count >= 0),
            next_run_at_us INTEGER NULL,
            blocked_reason TEXT NULL,
            pinned_configuration_json TEXT NULL CHECK(
                pinned_configuration_json IS NULL OR json_valid(pinned_configuration_json)
            ),
            protection_scope_id BLOB(16) NULL CHECK(
                protection_scope_id IS NULL OR length(protection_scope_id) = 16
            ),
            protected_payload_id BLOB(16) NULL CHECK(
                protected_payload_id IS NULL OR length(protected_payload_id) = 16
            ),
            worker_id TEXT NULL,
            lease_token BLOB(32) NULL CHECK(
                lease_token IS NULL OR length(lease_token) = 32
            ),
            lease_acquired_at_us INTEGER NULL,
            lease_expires_at_us INTEGER NULL,
            heartbeat_at_us INTEGER NULL,
            fencing_sequence INTEGER NOT NULL DEFAULT 0 CHECK(fencing_sequence >= 0),
            updated_at_us INTEGER NOT NULL,
            FOREIGN KEY(created_by_actor_id) REFERENCES actors(actor_id),
            FOREIGN KEY(processing_run_id) REFERENCES processing_runs(processing_run_id),
            FOREIGN KEY(last_checkpoint_id) REFERENCES checkpoints(checkpoint_id),
            CHECK((state IN ('running', 'cancel_requested')) = (lease_token IS NOT NULL)),
            CHECK(state != 'waiting' OR blocked_reason IN (
                'waiting_resource', 'waiting_storage', 'waiting_network',
                'waiting_dependency', 'waiting_schedule', 'waiting_user',
                'waiting_backoff'
            )),
            CHECK((worker_id IS NULL) = (lease_token IS NULL)),
            CHECK((lease_acquired_at_us IS NULL) = (lease_token IS NULL)),
            CHECK((lease_expires_at_us IS NULL) = (lease_token IS NULL)),
            CHECK((heartbeat_at_us IS NULL) = (lease_token IS NULL)),
            CHECK(lease_expires_at_us IS NULL OR lease_acquired_at_us IS NOT NULL),
            CHECK(lease_expires_at_us IS NULL OR lease_expires_at_us > lease_acquired_at_us)
        ) WITHOUT ROWID;

        CREATE INDEX idx_jobs_queue
            ON jobs(priority, next_run_at_us, created_at_us, job_id)
            WHERE state = 'queued';
        CREATE INDEX idx_jobs_state_updated
            ON jobs(state, updated_at_us, job_id);
        CREATE INDEX idx_jobs_expired_lease
            ON jobs(lease_expires_at_us, job_id)
            WHERE state IN ('running', 'cancel_requested');

        CREATE TABLE checkpoints (
            checkpoint_id BLOB(16) PRIMARY KEY CHECK(length(checkpoint_id) = 16),
            job_id BLOB(16) NOT NULL CHECK(length(job_id) = 16),
            processing_stage_id BLOB(16) NULL CHECK(
                processing_stage_id IS NULL OR length(processing_stage_id) = 16
            ),
            created_at_us INTEGER NOT NULL,
            progress_state_json TEXT NULL CHECK(
                progress_state_json IS NULL OR json_valid(progress_state_json)
            ),
            last_confirmed_input_json TEXT NULL CHECK(
                last_confirmed_input_json IS NULL OR json_valid(last_confirmed_input_json)
            ),
            last_confirmed_output_json TEXT NULL CHECK(
                last_confirmed_output_json IS NULL OR json_valid(last_confirmed_output_json)
            ),
            resume_metadata_json TEXT NULL CHECK(
                resume_metadata_json IS NULL OR json_valid(resume_metadata_json)
            ),
            commit_id BLOB(16) NULL CHECK(commit_id IS NULL OR length(commit_id) = 16),
            protection_scope_id BLOB(16) NULL CHECK(
                protection_scope_id IS NULL OR length(protection_scope_id) = 16
            ),
            protected_payload_id BLOB(16) NULL CHECK(
                protected_payload_id IS NULL OR length(protected_payload_id) = 16
            ),
            fencing_sequence INTEGER NOT NULL CHECK(fencing_sequence > 0),
            FOREIGN KEY(job_id) REFERENCES jobs(job_id),
            FOREIGN KEY(commit_id) REFERENCES commit_records(commit_id)
        ) WITHOUT ROWID;

        CREATE INDEX idx_checkpoints_job
            ON checkpoints(job_id, created_at_us, checkpoint_id);

        UPDATE schema_metadata
        SET schema_version = {DURABLE_JOBS_SCHEMA_VERSION},
            last_migration_id = '{DURABLE_JOBS_MIGRATION_ID}',
            minimum_reader_version = {DURABLE_JOBS_SCHEMA_VERSION}
        WHERE singleton_id = 1;

        PRAGMA user_version = {DURABLE_JOBS_SCHEMA_VERSION};
        COMMIT;
        """
    )


def _migrate_schema_v15_to_v16(connection: sqlite3.Connection) -> None:
    """Add retained page-offset maps for paginated SourceRepresentations."""
    connection.executescript(
        f"""
        BEGIN IMMEDIATE;

        CREATE TABLE source_representation_pages (
            representation_id BLOB(16) NOT NULL CHECK(length(representation_id) = 16),
            page_number INTEGER NOT NULL CHECK(page_number >= 1),
            start_offset INTEGER NOT NULL CHECK(start_offset >= 0),
            end_offset INTEGER NOT NULL CHECK(end_offset >= start_offset),
            content_hash BLOB(32) NOT NULL CHECK(length(content_hash) = 32),
            PRIMARY KEY(representation_id, page_number),
            FOREIGN KEY(representation_id) REFERENCES source_representations(representation_id)
        ) WITHOUT ROWID;

        CREATE INDEX idx_source_representation_pages_offset
            ON source_representation_pages(representation_id, start_offset, end_offset);

        UPDATE schema_metadata
        SET schema_version = {SOURCE_PAGE_MAP_SCHEMA_VERSION},
            last_migration_id = '{SOURCE_PAGE_MAP_MIGRATION_ID}',
            minimum_reader_version = {SOURCE_PAGE_MAP_SCHEMA_VERSION}
        WHERE singleton_id = 1;

        PRAGMA user_version = {SOURCE_PAGE_MAP_SCHEMA_VERSION};
        COMMIT;
        """
    )


def _migrate_schema_v16_to_v17(connection: sqlite3.Connection) -> None:
    """Add retained DOCX structure maps and durable structure-anchor links."""
    connection.executescript(
        f"""
        BEGIN IMMEDIATE;

        CREATE TABLE source_representation_structures (
            structure_id BLOB(16) PRIMARY KEY CHECK(length(structure_id) = 16),
            representation_id BLOB(16) NOT NULL CHECK(length(representation_id) = 16),
            structure_index INTEGER NOT NULL CHECK(structure_index >= 0),
            structure_type TEXT NOT NULL CHECK(structure_type IN (
                'paragraph', 'heading', 'list_item', 'table', 'table_row', 'table_cell'
            )),
            path TEXT NOT NULL CHECK(length(path) > 0),
            parent_structure_id BLOB(16) NULL CHECK(
                parent_structure_id IS NULL OR length(parent_structure_id) = 16
            ),
            start_offset INTEGER NOT NULL CHECK(start_offset >= 0),
            end_offset INTEGER NOT NULL CHECK(end_offset >= start_offset),
            content_hash BLOB(32) NOT NULL CHECK(length(content_hash) = 32),
            metadata_json TEXT NOT NULL CHECK(json_valid(metadata_json)),
            UNIQUE(representation_id, structure_index),
            UNIQUE(representation_id, path),
            FOREIGN KEY(representation_id) REFERENCES source_representations(representation_id),
            FOREIGN KEY(parent_structure_id) REFERENCES source_representation_structures(structure_id)
        ) WITHOUT ROWID;

        CREATE INDEX idx_source_representation_structures_range
            ON source_representation_structures(
                representation_id, start_offset, end_offset, structure_index
            );
        CREATE INDEX idx_source_representation_structures_type
            ON source_representation_structures(
                representation_id, structure_type, structure_index
            );

        CREATE TABLE source_anchor_structures (
            anchor_id BLOB(16) PRIMARY KEY CHECK(length(anchor_id) = 16),
            structure_id BLOB(16) NOT NULL UNIQUE CHECK(length(structure_id) = 16),
            FOREIGN KEY(anchor_id) REFERENCES source_anchors(anchor_id),
            FOREIGN KEY(structure_id) REFERENCES source_representation_structures(structure_id)
        ) WITHOUT ROWID;

        UPDATE schema_metadata
        SET schema_version = {SOURCE_DOCUMENT_STRUCTURE_SCHEMA_VERSION},
            last_migration_id = '{SOURCE_DOCUMENT_STRUCTURE_MIGRATION_ID}',
            minimum_reader_version = {SOURCE_DOCUMENT_STRUCTURE_SCHEMA_VERSION}
        WHERE singleton_id = 1;

        PRAGMA user_version = {SOURCE_DOCUMENT_STRUCTURE_SCHEMA_VERSION};
        COMMIT;
        """
    )


def _migrate_schema_v17_to_v18(connection: sqlite3.Connection) -> None:
    """Add durable hierarchical large-source analysis state and provenance graph."""
    connection.executescript(
        f"""
        BEGIN IMMEDIATE;

        CREATE TABLE source_analyses (
            analysis_id BLOB(16) PRIMARY KEY CHECK(length(analysis_id) = 16),
            job_id BLOB(16) NOT NULL UNIQUE CHECK(length(job_id) = 16),
            source_id BLOB(16) NOT NULL CHECK(length(source_id) = 16),
            representation_id BLOB(16) NOT NULL CHECK(length(representation_id) = 16),
            question TEXT NOT NULL CHECK(length(question) > 0),
            state TEXT NOT NULL CHECK(state IN (
                'running', 'partial', 'completed'
            )),
            model_signature_id BLOB(16) NOT NULL CHECK(length(model_signature_id) = 16),
            pipeline_version TEXT NOT NULL CHECK(length(pipeline_version) > 0),
            effective_context_limit INTEGER NOT NULL CHECK(effective_context_limit > 0),
            output_reserve INTEGER NOT NULL CHECK(output_reserve > 0),
            safety_margin INTEGER NOT NULL CHECK(safety_margin >= 0),
            token_estimator TEXT NOT NULL CHECK(length(token_estimator) > 0),
            max_hierarchy_depth INTEGER NOT NULL CHECK(max_hierarchy_depth >= 1),
            total_map_units INTEGER NOT NULL DEFAULT 0 CHECK(total_map_units >= 0),
            completed_map_units INTEGER NOT NULL DEFAULT 0 CHECK(completed_map_units >= 0),
            failed_map_units INTEGER NOT NULL DEFAULT 0 CHECK(failed_map_units >= 0),
            coverage REAL NOT NULL DEFAULT 0.0 CHECK(coverage >= 0.0 AND coverage <= 1.0),
            final_artifact_id BLOB(16) NULL CHECK(
                final_artifact_id IS NULL OR length(final_artifact_id) = 16
            ),
            created_at_us INTEGER NOT NULL,
            updated_at_us INTEGER NOT NULL CHECK(updated_at_us >= created_at_us),
            FOREIGN KEY(job_id) REFERENCES jobs(job_id),
            FOREIGN KEY(source_id) REFERENCES sources(source_id),
            FOREIGN KEY(representation_id) REFERENCES source_representations(representation_id),
            FOREIGN KEY(model_signature_id) REFERENCES model_signatures(model_signature_id),
            FOREIGN KEY(final_artifact_id) REFERENCES source_analysis_artifacts(artifact_id),
            CHECK(output_reserve + safety_margin < effective_context_limit),
            CHECK(completed_map_units + failed_map_units <= total_map_units),
            CHECK(state != 'completed' OR (
                total_map_units > 0
                AND completed_map_units = total_map_units
                AND failed_map_units = 0
                AND coverage = 1.0
                AND final_artifact_id IS NOT NULL
            ))
        ) WITHOUT ROWID;

        CREATE INDEX idx_source_analyses_source
            ON source_analyses(source_id, created_at_us, analysis_id);
        CREATE INDEX idx_source_analyses_state
            ON source_analyses(state, updated_at_us);

        CREATE TABLE source_analysis_work_items (
            work_item_id BLOB(16) PRIMARY KEY CHECK(length(work_item_id) = 16),
            analysis_id BLOB(16) NOT NULL CHECK(length(analysis_id) = 16),
            stage TEXT NOT NULL CHECK(stage IN ('map', 'reduce', 'final')),
            level INTEGER NOT NULL CHECK(level >= 0),
            ordinal INTEGER NOT NULL CHECK(ordinal >= 0),
            state TEXT NOT NULL CHECK(state IN ('pending', 'completed', 'failed', 'split')),
            idempotency_key BLOB(32) NOT NULL UNIQUE CHECK(length(idempotency_key) = 32),
            attempt_count INTEGER NOT NULL DEFAULT 0 CHECK(attempt_count >= 0),
            created_at_us INTEGER NOT NULL,
            updated_at_us INTEGER NOT NULL CHECK(updated_at_us >= created_at_us),
            UNIQUE(analysis_id, stage, level, ordinal),
            FOREIGN KEY(analysis_id) REFERENCES source_analyses(analysis_id)
        ) WITHOUT ROWID;

        CREATE INDEX idx_source_analysis_work_pending
            ON source_analysis_work_items(analysis_id, stage, state, level, ordinal);

        CREATE TABLE source_analysis_artifacts (
            artifact_id BLOB(16) PRIMARY KEY CHECK(length(artifact_id) = 16),
            analysis_id BLOB(16) NOT NULL CHECK(length(analysis_id) = 16),
            work_item_id BLOB(16) NOT NULL UNIQUE CHECK(length(work_item_id) = 16),
            artifact_kind TEXT NOT NULL CHECK(artifact_kind IN ('map', 'reduce', 'final')),
            level INTEGER NOT NULL CHECK(level >= 0),
            ordinal INTEGER NOT NULL CHECK(ordinal >= 0),
            content_json TEXT NOT NULL CHECK(json_valid(content_json)),
            content_hash BLOB(32) NOT NULL CHECK(length(content_hash) = 32),
            processing_run_id BLOB(16) NOT NULL UNIQUE CHECK(length(processing_run_id) = 16),
            created_at_us INTEGER NOT NULL,
            UNIQUE(analysis_id, artifact_kind, level, ordinal),
            FOREIGN KEY(analysis_id) REFERENCES source_analyses(analysis_id),
            FOREIGN KEY(work_item_id) REFERENCES source_analysis_work_items(work_item_id),
            FOREIGN KEY(processing_run_id) REFERENCES processing_runs(processing_run_id)
        ) WITHOUT ROWID;

        CREATE INDEX idx_source_analysis_artifacts_level
            ON source_analysis_artifacts(analysis_id, artifact_kind, level, ordinal);

        CREATE TABLE source_analysis_work_inputs (
            work_item_id BLOB(16) NOT NULL CHECK(length(work_item_id) = 16),
            ordinal INTEGER NOT NULL CHECK(ordinal >= 0),
            input_kind TEXT NOT NULL CHECK(input_kind IN ('source_anchor', 'artifact')),
            source_anchor_id BLOB(16) NULL CHECK(
                source_anchor_id IS NULL OR length(source_anchor_id) = 16
            ),
            artifact_id BLOB(16) NULL CHECK(
                artifact_id IS NULL OR length(artifact_id) = 16
            ),
            PRIMARY KEY(work_item_id, ordinal),
            FOREIGN KEY(work_item_id) REFERENCES source_analysis_work_items(work_item_id),
            FOREIGN KEY(source_anchor_id) REFERENCES source_anchors(anchor_id),
            FOREIGN KEY(artifact_id) REFERENCES source_analysis_artifacts(artifact_id),
            CHECK(
                (input_kind = 'source_anchor' AND source_anchor_id IS NOT NULL AND artifact_id IS NULL)
                OR
                (input_kind = 'artifact' AND artifact_id IS NOT NULL AND source_anchor_id IS NULL)
            )
        ) WITHOUT ROWID;

        CREATE INDEX idx_source_analysis_inputs_anchor
            ON source_analysis_work_inputs(source_anchor_id)
            WHERE source_anchor_id IS NOT NULL;
        CREATE INDEX idx_source_analysis_inputs_artifact
            ON source_analysis_work_inputs(artifact_id)
            WHERE artifact_id IS NOT NULL;

        UPDATE schema_metadata
        SET schema_version = {SOURCE_ANALYSIS_SCHEMA_VERSION},
            last_migration_id = '{SOURCE_ANALYSIS_MIGRATION_ID}',
            minimum_reader_version = {SOURCE_ANALYSIS_SCHEMA_VERSION}
        WHERE singleton_id = 1;

        PRAGMA user_version = {SOURCE_ANALYSIS_SCHEMA_VERSION};
        COMMIT;
        """
    )


def _migrate_schema_v18_to_v19(connection: sqlite3.Connection) -> None:
    """Add frozen source-analysis extraction snapshots and canonical promotion backlinks."""
    connection.executescript(
        f"""
        BEGIN IMMEDIATE;

        CREATE TABLE source_extraction_result_snapshots (
            processing_run_id BLOB(16) PRIMARY KEY CHECK(length(processing_run_id) = 16),
            analysis_id BLOB(16) NOT NULL CHECK(length(analysis_id) = 16),
            final_artifact_id BLOB(16) NOT NULL CHECK(length(final_artifact_id) = 16),
            model_json TEXT NOT NULL CHECK(json_valid(model_json)),
            evidence_json TEXT NOT NULL CHECK(json_valid(evidence_json)),
            proposals_json TEXT NOT NULL CHECK(json_valid(proposals_json)),
            created_at_us INTEGER NOT NULL,
            FOREIGN KEY(processing_run_id) REFERENCES processing_runs(processing_run_id),
            FOREIGN KEY(analysis_id) REFERENCES source_analyses(analysis_id),
            FOREIGN KEY(final_artifact_id) REFERENCES source_analysis_artifacts(artifact_id)
        ) WITHOUT ROWID;

        CREATE INDEX idx_source_extraction_snapshots_analysis
            ON source_extraction_result_snapshots(analysis_id, created_at_us);

        CREATE TABLE source_analysis_knowledge_origins (
            provenance_id BLOB(16) PRIMARY KEY CHECK(length(provenance_id) = 16),
            analysis_id BLOB(16) NOT NULL CHECK(length(analysis_id) = 16),
            final_artifact_id BLOB(16) NOT NULL CHECK(length(final_artifact_id) = 16),
            extraction_run_id BLOB(16) NOT NULL CHECK(length(extraction_run_id) = 16),
            created_at_us INTEGER NOT NULL,
            FOREIGN KEY(provenance_id) REFERENCES provenance_records(provenance_id),
            FOREIGN KEY(analysis_id) REFERENCES source_analyses(analysis_id),
            FOREIGN KEY(final_artifact_id) REFERENCES source_analysis_artifacts(artifact_id),
            FOREIGN KEY(extraction_run_id) REFERENCES processing_runs(processing_run_id)
        ) WITHOUT ROWID;

        CREATE INDEX idx_source_analysis_knowledge_origins_analysis
            ON source_analysis_knowledge_origins(analysis_id, final_artifact_id);

        UPDATE schema_metadata
        SET schema_version = {SOURCE_KNOWLEDGE_SCHEMA_VERSION},
            last_migration_id = '{SOURCE_KNOWLEDGE_MIGRATION_ID}',
            minimum_reader_version = {SOURCE_KNOWLEDGE_SCHEMA_VERSION}
        WHERE singleton_id = 1;

        PRAGMA user_version = {SOURCE_KNOWLEDGE_SCHEMA_VERSION};
        COMMIT;
        """
    )


def _verify_schema_v19(connection: sqlite3.Connection) -> None:
    application_id = int(connection.execute("PRAGMA application_id").fetchone()[0])
    user_version = int(connection.execute("PRAGMA user_version").fetchone()[0])
    if application_id != ATHENA_APPLICATION_ID:
        raise DatabaseCompatibilityError("ATHENA application_id verification failed.")
    if user_version != SCHEMA_VERSION:
        raise DatabaseCompatibilityError("ATHENA schema version verification failed.")

    metadata = connection.execute(
        "SELECT schema_version, storage_layout_version, blob_format_version, "
        "last_migration_id, minimum_reader_version "
        "FROM schema_metadata WHERE singleton_id = 1"
    ).fetchone()
    expected = (
        SCHEMA_VERSION,
        STORAGE_LAYOUT_VERSION,
        BLOB_FORMAT_VERSION,
        SOURCE_KNOWLEDGE_MIGRATION_ID,
        SCHEMA_VERSION,
    )
    if metadata is None or tuple(metadata) != expected:
        raise DatabaseCompatibilityError("ATHENA schema_metadata verification failed.")

    required_tables = {
        "knowledge_units", "knowledge_unit_revisions", "claims", "claim_revisions",
        "claim_evidence", "provenance_inputs", "model_signatures", "processing_runs",
        "semantic_review_items", "semantic_merge_review_payloads",
        "extraction_result_snapshots", "search_fts", "search_index_state",
        "search_embeddings", "search_embedding_state", "blob_records", "sources",
        "source_representations", "source_representation_pages",
        "source_representation_structures", "source_anchor_structures",
        "chunking_profiles", "source_anchors", "jobs", "checkpoints",
        "source_analyses", "source_analysis_work_items", "source_analysis_artifacts",
        "source_analysis_work_inputs", "source_extraction_result_snapshots",
        "source_analysis_knowledge_origins",
    }
    missing_tables = required_tables.difference(_user_tables(connection))
    if missing_tables:
        missing = ", ".join(sorted(missing_tables))
        raise DatabaseCompatibilityError(f"ATHENA semantic schema is incomplete: {missing}.")
    if connection.execute("PRAGMA foreign_key_check").fetchall():
        raise DatabaseCompatibilityError("ATHENA foreign-key verification failed.")


def _verify_schema_v18(connection: sqlite3.Connection) -> None:
    application_id = int(connection.execute("PRAGMA application_id").fetchone()[0])
    user_version = int(connection.execute("PRAGMA user_version").fetchone()[0])
    if application_id != ATHENA_APPLICATION_ID:
        raise DatabaseCompatibilityError("ATHENA application_id verification failed.")
    if user_version != SOURCE_ANALYSIS_SCHEMA_VERSION:
        raise DatabaseCompatibilityError("ATHENA schema version verification failed.")

    metadata = connection.execute(
        "SELECT schema_version, storage_layout_version, blob_format_version, "
        "last_migration_id, minimum_reader_version "
        "FROM schema_metadata WHERE singleton_id = 1"
    ).fetchone()
    expected = (
        SOURCE_ANALYSIS_SCHEMA_VERSION,
        STORAGE_LAYOUT_VERSION,
        BLOB_FORMAT_VERSION,
        SOURCE_ANALYSIS_MIGRATION_ID,
        SOURCE_ANALYSIS_SCHEMA_VERSION,
    )
    if metadata is None or tuple(metadata) != expected:
        raise DatabaseCompatibilityError("ATHENA schema_metadata verification failed.")

    required_tables = {
        "knowledge_units", "knowledge_unit_revisions", "claims", "claim_revisions",
        "claim_evidence", "provenance_inputs", "model_signatures", "processing_runs",
        "semantic_review_items", "semantic_merge_review_payloads",
        "extraction_result_snapshots", "search_fts", "search_index_state",
        "search_embeddings", "search_embedding_state", "blob_records", "sources",
        "source_representations", "source_representation_pages",
        "source_representation_structures", "source_anchor_structures",
        "chunking_profiles", "source_anchors", "jobs", "checkpoints",
        "source_analyses", "source_analysis_work_items", "source_analysis_artifacts",
        "source_analysis_work_inputs",
    }
    missing_tables = required_tables.difference(_user_tables(connection))
    if missing_tables:
        missing = ", ".join(sorted(missing_tables))
        raise DatabaseCompatibilityError(f"ATHENA semantic schema is incomplete: {missing}.")
    if connection.execute("PRAGMA foreign_key_check").fetchall():
        raise DatabaseCompatibilityError("ATHENA foreign-key verification failed.")


def _verify_schema_v17(connection: sqlite3.Connection) -> None:
    application_id = int(connection.execute("PRAGMA application_id").fetchone()[0])
    user_version = int(connection.execute("PRAGMA user_version").fetchone()[0])
    if application_id != ATHENA_APPLICATION_ID:
        raise DatabaseCompatibilityError("ATHENA application_id verification failed.")
    if user_version != SOURCE_DOCUMENT_STRUCTURE_SCHEMA_VERSION:
        raise DatabaseCompatibilityError("ATHENA schema version verification failed.")

    metadata = connection.execute(
        "SELECT schema_version, storage_layout_version, blob_format_version, "
        "last_migration_id, minimum_reader_version "
        "FROM schema_metadata WHERE singleton_id = 1"
    ).fetchone()
    expected = (
        SOURCE_DOCUMENT_STRUCTURE_SCHEMA_VERSION,
        STORAGE_LAYOUT_VERSION,
        BLOB_FORMAT_VERSION,
        SOURCE_DOCUMENT_STRUCTURE_MIGRATION_ID,
        SOURCE_DOCUMENT_STRUCTURE_SCHEMA_VERSION,
    )
    if metadata is None or tuple(metadata) != expected:
        raise DatabaseCompatibilityError("ATHENA schema_metadata verification failed.")

    required_tables = {
        "knowledge_units", "knowledge_unit_revisions", "claims", "claim_revisions",
        "claim_evidence", "provenance_inputs", "model_signatures", "processing_runs",
        "semantic_review_items", "semantic_merge_review_payloads",
        "extraction_result_snapshots", "search_fts", "search_index_state",
        "search_embeddings", "search_embedding_state", "blob_records", "sources",
        "source_representations", "source_representation_pages",
        "source_representation_structures", "source_anchor_structures",
        "chunking_profiles", "source_anchors", "jobs", "checkpoints",
    }
    missing_tables = required_tables.difference(_user_tables(connection))
    if missing_tables:
        missing = ", ".join(sorted(missing_tables))
        raise DatabaseCompatibilityError(f"ATHENA semantic schema is incomplete: {missing}.")
    if connection.execute("PRAGMA foreign_key_check").fetchall():
        raise DatabaseCompatibilityError("ATHENA foreign-key verification failed.")


def _verify_schema_v16(connection: sqlite3.Connection) -> None:
    application_id = int(connection.execute("PRAGMA application_id").fetchone()[0])
    user_version = int(connection.execute("PRAGMA user_version").fetchone()[0])
    if application_id != ATHENA_APPLICATION_ID:
        raise DatabaseCompatibilityError("ATHENA application_id verification failed.")
    if user_version != SOURCE_PAGE_MAP_SCHEMA_VERSION:
        raise DatabaseCompatibilityError("ATHENA schema version verification failed.")

    metadata = connection.execute(
        "SELECT schema_version, storage_layout_version, blob_format_version, "
        "last_migration_id, minimum_reader_version "
        "FROM schema_metadata WHERE singleton_id = 1"
    ).fetchone()
    expected = (
        SOURCE_PAGE_MAP_SCHEMA_VERSION,
        STORAGE_LAYOUT_VERSION,
        BLOB_FORMAT_VERSION,
        SOURCE_PAGE_MAP_MIGRATION_ID,
        SOURCE_PAGE_MAP_SCHEMA_VERSION,
    )
    if metadata is None or tuple(metadata) != expected:
        raise DatabaseCompatibilityError("ATHENA schema_metadata verification failed.")

    required_tables = {
        "knowledge_units", "knowledge_unit_revisions", "claims", "claim_revisions",
        "claim_evidence", "provenance_inputs", "model_signatures", "processing_runs",
        "semantic_review_items", "semantic_merge_review_payloads",
        "extraction_result_snapshots", "search_fts", "search_index_state",
        "search_embeddings", "search_embedding_state", "blob_records", "sources",
        "source_representations", "source_representation_pages", "chunking_profiles",
        "source_anchors", "jobs", "checkpoints",
    }
    missing_tables = required_tables.difference(_user_tables(connection))
    if missing_tables:
        missing = ", ".join(sorted(missing_tables))
        raise DatabaseCompatibilityError(f"ATHENA semantic schema is incomplete: {missing}.")
    if connection.execute("PRAGMA foreign_key_check").fetchall():
        raise DatabaseCompatibilityError("ATHENA foreign-key verification failed.")

def _verify_schema_v15(connection: sqlite3.Connection) -> None:
    application_id = int(connection.execute("PRAGMA application_id").fetchone()[0])
    user_version = int(connection.execute("PRAGMA user_version").fetchone()[0])

    if application_id != ATHENA_APPLICATION_ID:
        raise DatabaseCompatibilityError("ATHENA application_id verification failed.")
    if user_version != DURABLE_JOBS_SCHEMA_VERSION:
        raise DatabaseCompatibilityError("ATHENA schema version verification failed.")

    metadata = connection.execute(
        "SELECT schema_version, storage_layout_version, blob_format_version, "
        "last_migration_id, minimum_reader_version "
        "FROM schema_metadata WHERE singleton_id = 1"
    ).fetchone()
    expected = (
        DURABLE_JOBS_SCHEMA_VERSION,
        STORAGE_LAYOUT_VERSION,
        BLOB_FORMAT_VERSION,
        DURABLE_JOBS_MIGRATION_ID,
        DURABLE_JOBS_SCHEMA_VERSION,
    )
    if metadata is None or tuple(metadata) != expected:
        raise DatabaseCompatibilityError("ATHENA schema_metadata verification failed.")

    required_tables = {
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
        "sources",
        "source_representations",
        "chunking_profiles",
        "source_anchors",
        "jobs",
        "checkpoints",
    }
    missing_tables = required_tables.difference(_user_tables(connection))
    if missing_tables:
        missing = ", ".join(sorted(missing_tables))
        raise DatabaseCompatibilityError(f"ATHENA semantic schema is incomplete: {missing}.")

    foreign_key_failures = connection.execute("PRAGMA foreign_key_check").fetchall()
    if foreign_key_failures:
        raise DatabaseCompatibilityError("ATHENA foreign-key verification failed.")
