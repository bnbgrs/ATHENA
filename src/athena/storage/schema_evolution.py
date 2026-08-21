"""ATHENA SQLite schema bootstrap and additive migrations."""

from __future__ import annotations

import json
import sqlite3

from athena.storage.schema_contract import (
    ARCHIVE_REPLICATION_MIGRATION_ID as ARCHIVE_REPLICATION_MIGRATION_ID,
)
from athena.storage.schema_contract import (
    ARCHIVE_REPLICATION_SCHEMA_VERSION as ARCHIVE_REPLICATION_SCHEMA_VERSION,
)
from athena.storage.schema_contract import (
    BACKUP_RETENTION_MIGRATION_ID as BACKUP_RETENTION_MIGRATION_ID,
)
from athena.storage.schema_contract import (
    BACKUP_RETENTION_SCHEMA_VERSION as BACKUP_RETENTION_SCHEMA_VERSION,
)
from athena.storage.schema_contract import BLOB_FORMAT_VERSION as BLOB_FORMAT_VERSION
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
from athena.storage.schema_contract import DURABLE_JOBS_MIGRATION_ID as DURABLE_JOBS_MIGRATION_ID
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
from athena.storage.schema_contract import KNOWLEDGE_SCHEMA_VERSION as KNOWLEDGE_SCHEMA_VERSION
from athena.storage.schema_contract import LEGACY_SCHEMA_VERSION as LEGACY_SCHEMA_VERSION
from athena.storage.schema_contract import (
    LOCAL_EMBEDDINGS_MIGRATION_ID as LOCAL_EMBEDDINGS_MIGRATION_ID,
)
from athena.storage.schema_contract import (
    LOCAL_EMBEDDINGS_SCHEMA_VERSION as LOCAL_EMBEDDINGS_SCHEMA_VERSION,
)
from athena.storage.schema_contract import LOCAL_FTS_SCHEMA_VERSION as LOCAL_FTS_SCHEMA_VERSION
from athena.storage.schema_contract import (
    LOCAL_FTS_SEARCH_MIGRATION_ID as LOCAL_FTS_SEARCH_MIGRATION_ID,
)
from athena.storage.schema_contract import MERGE_REVIEW_MIGRATION_ID as MERGE_REVIEW_MIGRATION_ID
from athena.storage.schema_contract import (
    MERGE_REVIEW_MULTI_TARGET_MIGRATION_ID as MERGE_REVIEW_MULTI_TARGET_MIGRATION_ID,
)
from athena.storage.schema_contract import (
    MERGE_REVIEW_MULTI_TARGET_SCHEMA_VERSION as MERGE_REVIEW_MULTI_TARGET_SCHEMA_VERSION,
)
from athena.storage.schema_contract import (
    MERGE_REVIEW_SCHEMA_VERSION as MERGE_REVIEW_SCHEMA_VERSION,
)
from athena.storage.schema_contract import MODEL_RUNS_MIGRATION_ID as MODEL_RUNS_MIGRATION_ID
from athena.storage.schema_contract import MODEL_RUNS_SCHEMA_VERSION as MODEL_RUNS_SCHEMA_VERSION
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
from athena.storage.schema_contract import PROVENANCE_SCHEMA_VERSION as PROVENANCE_SCHEMA_VERSION
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
from athena.storage.schema_contract import REVIEW_QUEUE_MIGRATION_ID as REVIEW_QUEUE_MIGRATION_ID
from athena.storage.schema_contract import (
    REVIEW_QUEUE_SCHEMA_VERSION as REVIEW_QUEUE_SCHEMA_VERSION,
)
from athena.storage.schema_contract import (
    SOURCE_ANALYSIS_MIGRATION_ID as SOURCE_ANALYSIS_MIGRATION_ID,
)
from athena.storage.schema_contract import (
    SOURCE_ANALYSIS_SCHEMA_VERSION as SOURCE_ANALYSIS_SCHEMA_VERSION,
)
from athena.storage.schema_contract import SOURCE_ANCHOR_MIGRATION_ID as SOURCE_ANCHOR_MIGRATION_ID
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
from athena.storage.schema_contract import STORAGE_LAYOUT_VERSION as STORAGE_LAYOUT_VERSION
from athena.storage.schema_contract import DatabaseCompatibilityError as DatabaseCompatibilityError
from athena.storage.schema_contract import _user_tables as _user_tables
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
from athena.storage.schema_verification import _verify_schema_v28 as _verify_schema_v28
from athena.storage.schema_verification import _verify_schema_v30 as _verify_schema_v30
from athena.storage.schema_verification import _verify_schema_v31 as _verify_schema_v31
from athena.storage.schema_verification import _verify_schema_v32 as _verify_schema_v32
from athena.storage.schema_verification import _verify_schema_v33 as _verify_schema_v33
from athena.storage.schema_verification import _verify_schema_v34 as _verify_schema_v34
from athena.storage.schema_verification import _verify_schema_v35 as _verify_schema_v35
from athena.storage.schema_verification import _verify_schema_v36 as _verify_schema_v36
from athena.storage.schema_verification import _verify_schema_v38 as _verify_schema_v38


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


def _migrate_schema_v19_to_v20(connection: sqlite3.Connection) -> None:
    """Add durable hierarchical source-extraction work state and immutable evidence slots."""
    connection.executescript(
        f"""
        BEGIN IMMEDIATE;

        CREATE TABLE source_extractions (
            extraction_id BLOB(16) PRIMARY KEY CHECK(length(extraction_id) = 16),
            job_id BLOB(16) NOT NULL UNIQUE CHECK(length(job_id) = 16),
            analysis_id BLOB(16) NOT NULL CHECK(length(analysis_id) = 16),
            final_artifact_id BLOB(16) NOT NULL CHECK(length(final_artifact_id) = 16),
            state TEXT NOT NULL CHECK(state IN ('running', 'partial', 'completed')),
            model_signature_id BLOB(16) NOT NULL CHECK(length(model_signature_id) = 16),
            pipeline_version TEXT NOT NULL CHECK(length(pipeline_version) > 0),
            effective_context_limit INTEGER NOT NULL CHECK(effective_context_limit > 0),
            output_reserve INTEGER NOT NULL CHECK(output_reserve > 0),
            safety_margin INTEGER NOT NULL CHECK(safety_margin >= 0),
            token_estimator TEXT NOT NULL CHECK(length(token_estimator) > 0),
            prompt_template_id TEXT NOT NULL CHECK(length(prompt_template_id) > 0),
            prompt_template_version TEXT NOT NULL CHECK(length(prompt_template_version) > 0),
            max_hierarchy_depth INTEGER NOT NULL CHECK(max_hierarchy_depth >= 1),
            total_batches INTEGER NOT NULL DEFAULT 0 CHECK(total_batches >= 0),
            completed_batches INTEGER NOT NULL DEFAULT 0 CHECK(completed_batches >= 0),
            failed_batches INTEGER NOT NULL DEFAULT 0 CHECK(failed_batches >= 0),
            final_work_artifact_id BLOB(16) NULL CHECK(
                final_work_artifact_id IS NULL OR length(final_work_artifact_id) = 16
            ),
            created_at_us INTEGER NOT NULL,
            updated_at_us INTEGER NOT NULL CHECK(updated_at_us >= created_at_us),
            FOREIGN KEY(job_id) REFERENCES jobs(job_id),
            FOREIGN KEY(analysis_id) REFERENCES source_analyses(analysis_id),
            FOREIGN KEY(final_artifact_id) REFERENCES source_analysis_artifacts(artifact_id),
            FOREIGN KEY(model_signature_id) REFERENCES model_signatures(model_signature_id),
            FOREIGN KEY(final_work_artifact_id) REFERENCES source_extraction_artifacts(artifact_id),
            CHECK(output_reserve + safety_margin < effective_context_limit),
            CHECK(completed_batches + failed_batches <= total_batches),
            CHECK(state != 'completed' OR (
                total_batches > 0
                AND completed_batches = total_batches
                AND failed_batches = 0
                AND final_work_artifact_id IS NOT NULL
            ))
        ) WITHOUT ROWID;

        CREATE INDEX idx_source_extractions_analysis
            ON source_extractions(analysis_id, created_at_us, extraction_id);
        CREATE INDEX idx_source_extractions_state
            ON source_extractions(state, updated_at_us);

        CREATE TABLE source_extraction_evidence (
            extraction_id BLOB(16) NOT NULL CHECK(length(extraction_id) = 16),
            sequence_no INTEGER NOT NULL CHECK(sequence_no >= 1),
            source_anchor_id BLOB(16) NOT NULL CHECK(length(source_anchor_id) = 16),
            quoted_hash BLOB(32) NOT NULL CHECK(length(quoted_hash) = 32),
            PRIMARY KEY(extraction_id, sequence_no),
            UNIQUE(extraction_id, source_anchor_id),
            FOREIGN KEY(extraction_id) REFERENCES source_extractions(extraction_id),
            FOREIGN KEY(source_anchor_id) REFERENCES source_anchors(anchor_id)
        ) WITHOUT ROWID;

        CREATE INDEX idx_source_extraction_evidence_anchor
            ON source_extraction_evidence(source_anchor_id, extraction_id);

        CREATE TABLE source_extraction_work_items (
            work_item_id BLOB(16) PRIMARY KEY CHECK(length(work_item_id) = 16),
            extraction_id BLOB(16) NOT NULL CHECK(length(extraction_id) = 16),
            stage TEXT NOT NULL CHECK(stage IN ('batch', 'merge', 'audit', 'final')),
            level INTEGER NOT NULL CHECK(level >= 0),
            ordinal INTEGER NOT NULL CHECK(ordinal >= 0),
            state TEXT NOT NULL CHECK(state IN ('pending', 'completed', 'failed', 'split')),
            idempotency_key BLOB(32) NOT NULL UNIQUE CHECK(length(idempotency_key) = 32),
            attempt_count INTEGER NOT NULL DEFAULT 0 CHECK(attempt_count >= 0),
            created_at_us INTEGER NOT NULL,
            updated_at_us INTEGER NOT NULL CHECK(updated_at_us >= created_at_us),
            UNIQUE(extraction_id, stage, level, ordinal),
            FOREIGN KEY(extraction_id) REFERENCES source_extractions(extraction_id)
        ) WITHOUT ROWID;

        CREATE INDEX idx_source_extraction_work_pending
            ON source_extraction_work_items(extraction_id, stage, state, level, ordinal);

        CREATE TABLE source_extraction_artifacts (
            artifact_id BLOB(16) PRIMARY KEY CHECK(length(artifact_id) = 16),
            extraction_id BLOB(16) NOT NULL CHECK(length(extraction_id) = 16),
            work_item_id BLOB(16) NOT NULL UNIQUE CHECK(length(work_item_id) = 16),
            artifact_kind TEXT NOT NULL CHECK(artifact_kind IN ('batch', 'merge', 'audit', 'final')),
            level INTEGER NOT NULL CHECK(level >= 0),
            ordinal INTEGER NOT NULL CHECK(ordinal >= 0),
            content_json TEXT NOT NULL CHECK(json_valid(content_json)),
            content_hash BLOB(32) NOT NULL CHECK(length(content_hash) = 32),
            processing_run_id BLOB(16) NOT NULL UNIQUE CHECK(length(processing_run_id) = 16),
            created_at_us INTEGER NOT NULL,
            UNIQUE(extraction_id, artifact_kind, level, ordinal),
            FOREIGN KEY(extraction_id) REFERENCES source_extractions(extraction_id),
            FOREIGN KEY(work_item_id) REFERENCES source_extraction_work_items(work_item_id),
            FOREIGN KEY(processing_run_id) REFERENCES processing_runs(processing_run_id)
        ) WITHOUT ROWID;

        CREATE INDEX idx_source_extraction_artifacts_level
            ON source_extraction_artifacts(extraction_id, artifact_kind, level, ordinal);

        CREATE TABLE source_extraction_work_inputs (
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
            FOREIGN KEY(work_item_id) REFERENCES source_extraction_work_items(work_item_id),
            FOREIGN KEY(source_anchor_id) REFERENCES source_anchors(anchor_id),
            FOREIGN KEY(artifact_id) REFERENCES source_extraction_artifacts(artifact_id),
            CHECK(
                (input_kind = 'source_anchor' AND source_anchor_id IS NOT NULL AND artifact_id IS NULL)
                OR
                (input_kind = 'artifact' AND artifact_id IS NOT NULL AND source_anchor_id IS NULL)
            )
        ) WITHOUT ROWID;

        CREATE INDEX idx_source_extraction_inputs_anchor
            ON source_extraction_work_inputs(source_anchor_id)
            WHERE source_anchor_id IS NOT NULL;
        CREATE INDEX idx_source_extraction_inputs_artifact
            ON source_extraction_work_inputs(artifact_id)
            WHERE artifact_id IS NOT NULL;

        UPDATE schema_metadata
        SET schema_version = {HIERARCHICAL_SOURCE_EXTRACTION_SCHEMA_VERSION},
            last_migration_id = '{HIERARCHICAL_SOURCE_EXTRACTION_MIGRATION_ID}',
            minimum_reader_version = {HIERARCHICAL_SOURCE_EXTRACTION_SCHEMA_VERSION}
        WHERE singleton_id = 1;

        PRAGMA user_version = {HIERARCHICAL_SOURCE_EXTRACTION_SCHEMA_VERSION};
        COMMIT;
        """
    )


def _migrate_schema_v20_to_v21(connection: sqlite3.Connection) -> None:
    """Add canonical Personal Memory identities and immutable revisions."""
    connection.executescript(
        f"""
        BEGIN IMMEDIATE;

        CREATE TABLE personal_memory_entries (
            memory_id BLOB(16) PRIMARY KEY CHECK(length(memory_id) = 16),
            FOREIGN KEY(memory_id) REFERENCES entity_registry(entity_id)
        ) WITHOUT ROWID;

        CREATE TABLE personal_memory_revisions (
            revision_id BLOB(16) PRIMARY KEY CHECK(length(revision_id) = 16),
            memory_kind TEXT NOT NULL CHECK(memory_kind IN (
                'response_style',
                'language_preference',
                'detail_preference',
                'workflow_preference',
                'model_preference',
                'tool_preference',
                'recurring_setting',
                'interaction_preference',
                'other'
            )),
            content TEXT NOT NULL CHECK(length(trim(content)) > 0),
            scope_entity_id BLOB(16) NULL CHECK(
                scope_entity_id IS NULL OR length(scope_entity_id) = 16
            ),
            scope_kind TEXT NOT NULL CHECK(scope_kind IN (
                'global', 'project', 'workflow', 'client'
            )),
            learning_mode TEXT NOT NULL CHECK(learning_mode IN (
                'explicit_user', 'model_inferred', 'imported'
            )),
            sensitivity TEXT NOT NULL CHECK(sensitivity IN (
                'normal', 'sensitive', 'protected'
            )),
            confidence REAL NULL CHECK(
                confidence IS NULL OR (confidence >= 0.0 AND confidence <= 1.0)
            ),
            last_confirmed_at_us INTEGER NULL CHECK(
                last_confirmed_at_us IS NULL OR last_confirmed_at_us >= 0
            ),
            protected_payload_id BLOB(16) NULL CHECK(
                protected_payload_id IS NULL OR length(protected_payload_id) = 16
            ),
            FOREIGN KEY(revision_id) REFERENCES revisions(revision_id),
            CHECK(
                (scope_kind = 'global' AND scope_entity_id IS NULL)
                OR
                (scope_kind != 'global' AND scope_entity_id IS NOT NULL)
            ),
            CHECK(learning_mode != 'explicit_user' OR confidence IS NULL),
            CHECK(sensitivity != 'protected' OR protected_payload_id IS NOT NULL)
        ) WITHOUT ROWID;

        CREATE INDEX idx_personal_memory_scope
            ON personal_memory_revisions(scope_kind, scope_entity_id);
        CREATE INDEX idx_personal_memory_kind
            ON personal_memory_revisions(memory_kind);

        UPDATE schema_metadata
        SET schema_version = {PERSONAL_MEMORY_SCHEMA_VERSION},
            last_migration_id = '{PERSONAL_MEMORY_MIGRATION_ID}',
            minimum_reader_version = {PERSONAL_MEMORY_SCHEMA_VERSION}
        WHERE singleton_id = 1;

        PRAGMA user_version = {PERSONAL_MEMORY_SCHEMA_VERSION};
        COMMIT;
        """
    )


def _migrate_schema_v21_to_v22(connection: sqlite3.Connection) -> None:
    """Add snapshot-frozen Exhaustive Research scope, candidates, and coverage state."""
    connection.executescript(
        f"""
        BEGIN IMMEDIATE;

        CREATE TABLE research_scopes (
            scope_id BLOB(16) PRIMARY KEY CHECK(length(scope_id) = 16),
            job_id BLOB(16) NOT NULL UNIQUE CHECK(length(job_id) = 16),
            mode TEXT NOT NULL CHECK(mode IN (
                'local_exhaustive', 'scoped_project', 'local_plus_web',
                'historical_backfill', 'delta'
            )),
            query_text TEXT NOT NULL CHECK(length(trim(query_text)) > 0),
            domains_json TEXT NOT NULL CHECK(
                json_valid(domains_json) AND json_type(domains_json) = 'array'
            ),
            project_ids_json TEXT NOT NULL CHECK(
                json_valid(project_ids_json) AND json_type(project_ids_json) = 'array'
            ),
            source_types_json TEXT NOT NULL CHECK(
                json_valid(source_types_json) AND json_type(source_types_json) = 'array'
            ),
            explicit_source_ids_json TEXT NOT NULL CHECK(
                json_valid(explicit_source_ids_json)
                AND json_type(explicit_source_ids_json) = 'array'
            ),
            time_start_us INTEGER NULL CHECK(time_start_us IS NULL OR time_start_us >= 0),
            time_end_us INTEGER NULL CHECK(time_end_us IS NULL OR time_end_us >= 0),
            internet_scope_json TEXT NULL CHECK(
                internet_scope_json IS NULL
                OR (json_valid(internet_scope_json) AND json_type(internet_scope_json) = 'object')
            ),
            coverage_target REAL NOT NULL CHECK(
                coverage_target > 0.0 AND coverage_target <= 1.0
            ),
            snapshot_commit_seq INTEGER NOT NULL CHECK(snapshot_commit_seq >= 0),
            state TEXT NOT NULL CHECK(state IN (
                'discovering', 'frozen', 'running', 'partial', 'completed', 'cancelled'
            )),
            candidate_total INTEGER NOT NULL DEFAULT 0 CHECK(candidate_total >= 0),
            processed_count INTEGER NOT NULL DEFAULT 0 CHECK(processed_count >= 0),
            successful_count INTEGER NOT NULL DEFAULT 0 CHECK(successful_count >= 0),
            irrelevant_count INTEGER NOT NULL DEFAULT 0 CHECK(irrelevant_count >= 0),
            failed_count INTEGER NOT NULL DEFAULT 0 CHECK(failed_count >= 0),
            unavailable_count INTEGER NOT NULL DEFAULT 0 CHECK(unavailable_count >= 0),
            excluded_count INTEGER NOT NULL DEFAULT 0 CHECK(excluded_count >= 0),
            coverage_ratio REAL NOT NULL DEFAULT 0.0 CHECK(
                coverage_ratio >= 0.0 AND coverage_ratio <= 1.0
            ),
            created_at_us INTEGER NOT NULL,
            updated_at_us INTEGER NOT NULL CHECK(updated_at_us >= created_at_us),
            FOREIGN KEY(job_id) REFERENCES jobs(job_id),
            CHECK(time_end_us IS NULL OR time_start_us IS NULL OR time_end_us >= time_start_us),
            CHECK(processed_count = (
                successful_count + irrelevant_count + failed_count + unavailable_count
            )),
            CHECK(candidate_total >= processed_count + excluded_count)
        ) WITHOUT ROWID;

        CREATE INDEX idx_research_scopes_state
            ON research_scopes(state, updated_at_us);
        CREATE INDEX idx_research_scopes_snapshot
            ON research_scopes(snapshot_commit_seq, created_at_us);

        CREATE TABLE research_candidate_sets (
            candidate_set_id BLOB(16) PRIMARY KEY CHECK(length(candidate_set_id) = 16),
            scope_id BLOB(16) NOT NULL UNIQUE CHECK(length(scope_id) = 16),
            snapshot_commit_seq INTEGER NOT NULL CHECK(snapshot_commit_seq >= 0),
            state TEXT NOT NULL CHECK(state IN ('building', 'frozen')),
            candidate_total INTEGER NOT NULL DEFAULT 0 CHECK(candidate_total >= 0),
            eligible_count INTEGER NOT NULL DEFAULT 0 CHECK(eligible_count >= 0),
            excluded_count INTEGER NOT NULL DEFAULT 0 CHECK(excluded_count >= 0),
            created_at_us INTEGER NOT NULL,
            frozen_at_us INTEGER NULL CHECK(
                frozen_at_us IS NULL OR frozen_at_us >= created_at_us
            ),
            FOREIGN KEY(scope_id) REFERENCES research_scopes(scope_id),
            CHECK(candidate_total = eligible_count + excluded_count),
            CHECK(state != 'frozen' OR frozen_at_us IS NOT NULL)
        ) WITHOUT ROWID;

        CREATE TABLE research_candidates (
            candidate_id BLOB(16) PRIMARY KEY CHECK(length(candidate_id) = 16),
            candidate_set_id BLOB(16) NOT NULL CHECK(length(candidate_set_id) = 16),
            source_id BLOB(16) NOT NULL CHECK(length(source_id) = 16),
            ordinal INTEGER NOT NULL CHECK(ordinal >= 0),
            content_sha256 BLOB(32) NOT NULL CHECK(length(content_sha256) = 32),
            eligibility_state TEXT NOT NULL CHECK(eligibility_state IN (
                'eligible', 'excluded_duplicate'
            )),
            duplicate_of_candidate_id BLOB(16) NULL CHECK(
                duplicate_of_candidate_id IS NULL OR length(duplicate_of_candidate_id) = 16
            ),
            created_at_us INTEGER NOT NULL,
            UNIQUE(candidate_set_id, source_id),
            UNIQUE(candidate_set_id, ordinal),
            FOREIGN KEY(candidate_set_id)
                REFERENCES research_candidate_sets(candidate_set_id),
            FOREIGN KEY(source_id) REFERENCES sources(source_id),
            FOREIGN KEY(duplicate_of_candidate_id)
                REFERENCES research_candidates(candidate_id),
            CHECK(
                (eligibility_state = 'eligible' AND duplicate_of_candidate_id IS NULL)
                OR
                (
                    eligibility_state = 'excluded_duplicate'
                    AND duplicate_of_candidate_id IS NOT NULL
                )
            )
        ) WITHOUT ROWID;

        CREATE INDEX idx_research_candidates_set_eligibility
            ON research_candidates(candidate_set_id, eligibility_state, ordinal);
        CREATE INDEX idx_research_candidates_source
            ON research_candidates(source_id, candidate_set_id);

        CREATE TABLE research_work_items (
            work_item_id BLOB(16) PRIMARY KEY CHECK(length(work_item_id) = 16),
            scope_id BLOB(16) NOT NULL CHECK(length(scope_id) = 16),
            candidate_id BLOB(16) NOT NULL UNIQUE CHECK(length(candidate_id) = 16),
            state TEXT NOT NULL CHECK(state IN (
                'pending', 'successful', 'irrelevant', 'failed', 'unavailable'
            )),
            idempotency_key BLOB(32) NOT NULL UNIQUE CHECK(length(idempotency_key) = 32),
            source_analysis_job_id BLOB(16) NULL CHECK(
                source_analysis_job_id IS NULL OR length(source_analysis_job_id) = 16
            ),
            attempt_count INTEGER NOT NULL DEFAULT 0 CHECK(attempt_count >= 0),
            created_at_us INTEGER NOT NULL,
            updated_at_us INTEGER NOT NULL CHECK(updated_at_us >= created_at_us),
            FOREIGN KEY(scope_id) REFERENCES research_scopes(scope_id),
            FOREIGN KEY(candidate_id) REFERENCES research_candidates(candidate_id),
            FOREIGN KEY(source_analysis_job_id) REFERENCES jobs(job_id)
        ) WITHOUT ROWID;

        CREATE INDEX idx_research_work_scope_state
            ON research_work_items(scope_id, state, created_at_us);

        UPDATE schema_metadata
        SET schema_version = {EXHAUSTIVE_RESEARCH_SCHEMA_VERSION},
            last_migration_id = '{EXHAUSTIVE_RESEARCH_MIGRATION_ID}',
            minimum_reader_version = {EXHAUSTIVE_RESEARCH_SCHEMA_VERSION}
        WHERE singleton_id = 1;

        PRAGMA user_version = {EXHAUSTIVE_RESEARCH_SCHEMA_VERSION};
        COMMIT;
        """
    )


def _migrate_schema_v22_to_v23(connection: sqlite3.Connection) -> None:
    """Add durable Research child orchestration and pinned model-contract state."""
    connection.executescript(
        f"""
        BEGIN IMMEDIATE;

        ALTER TABLE research_work_items
            ADD COLUMN source_processing_job_id BLOB(16) NULL
            REFERENCES jobs(job_id)
            CHECK(
                source_processing_job_id IS NULL
                OR length(source_processing_job_id) = 16
            );

        ALTER TABLE research_scopes ADD COLUMN model_id TEXT NULL;
        ALTER TABLE research_scopes
            ADD COLUMN model_signature_id BLOB(16) NULL
            REFERENCES model_signatures(model_signature_id)
            CHECK(
                model_signature_id IS NULL OR length(model_signature_id) = 16
            );
        ALTER TABLE research_scopes
            ADD COLUMN model_signature_sha256 BLOB(32) NULL
            CHECK(
                model_signature_sha256 IS NULL
                OR length(model_signature_sha256) = 32
            );
        ALTER TABLE research_scopes
            ADD COLUMN effective_context_limit INTEGER NULL
            CHECK(
                effective_context_limit IS NULL OR effective_context_limit > 0
            );
        ALTER TABLE research_scopes
            ADD COLUMN output_reserve INTEGER NULL
            CHECK(output_reserve IS NULL OR output_reserve > 0);
        ALTER TABLE research_scopes
            ADD COLUMN safety_margin INTEGER NULL
            CHECK(safety_margin IS NULL OR safety_margin >= 0);
        ALTER TABLE research_scopes ADD COLUMN token_estimator TEXT NULL;
        ALTER TABLE research_scopes
            ADD COLUMN max_hierarchy_depth INTEGER NULL
            CHECK(
                max_hierarchy_depth IS NULL OR max_hierarchy_depth >= 1
            );

        CREATE UNIQUE INDEX uq_jobs_research_child_identity
            ON jobs(
                job_type,
                json_extract(requested_scope_json, '$.research_work_item_id')
            )
            WHERE job_type IN ('source.process', 'source.analyze')
              AND json_extract(
                    requested_scope_json,
                    '$.research_work_item_id'
                  ) IS NOT NULL;

        CREATE UNIQUE INDEX uq_research_work_source_processing_job
            ON research_work_items(source_processing_job_id)
            WHERE source_processing_job_id IS NOT NULL;

        CREATE UNIQUE INDEX uq_research_work_source_analysis_job
            ON research_work_items(source_analysis_job_id)
            WHERE source_analysis_job_id IS NOT NULL;

        CREATE INDEX idx_research_scope_model_signature
            ON research_scopes(model_signature_id)
            WHERE model_signature_id IS NOT NULL;

        UPDATE schema_metadata
        SET schema_version = {RESEARCH_ORCHESTRATION_SCHEMA_VERSION},
            last_migration_id = '{RESEARCH_ORCHESTRATION_MIGRATION_ID}',
            minimum_reader_version = {RESEARCH_ORCHESTRATION_SCHEMA_VERSION}
        WHERE singleton_id = 1;

        PRAGMA user_version = {RESEARCH_ORCHESTRATION_SCHEMA_VERSION};
        COMMIT;
        """
    )


def _migrate_schema_v23_to_v24(connection: sqlite3.Connection) -> None:
    """Add durable hierarchical Research synthesis, evidence links, and ResearchResult."""
    connection.executescript(
        f"""
        BEGIN IMMEDIATE;

        CREATE TABLE research_synthesis_work_items (
            work_item_id BLOB(16) PRIMARY KEY CHECK(length(work_item_id) = 16),
            scope_id BLOB(16) NOT NULL CHECK(length(scope_id) = 16),
            stage TEXT NOT NULL CHECK(stage IN ('reduce', 'final')),
            level INTEGER NOT NULL CHECK(level >= 0),
            ordinal INTEGER NOT NULL CHECK(ordinal >= 0),
            state TEXT NOT NULL CHECK(state IN ('pending', 'completed', 'split')),
            idempotency_key BLOB(32) NOT NULL UNIQUE CHECK(length(idempotency_key) = 32),
            pipeline_version TEXT NOT NULL CHECK(length(pipeline_version) > 0),
            prompt_template_id TEXT NOT NULL CHECK(length(prompt_template_id) > 0),
            prompt_template_version TEXT NOT NULL CHECK(length(prompt_template_version) > 0),
            attempt_count INTEGER NOT NULL DEFAULT 0 CHECK(attempt_count >= 0),
            created_at_us INTEGER NOT NULL,
            updated_at_us INTEGER NOT NULL CHECK(updated_at_us >= created_at_us),
            FOREIGN KEY(scope_id) REFERENCES research_scopes(scope_id)
        ) WITHOUT ROWID;

        CREATE INDEX idx_research_synthesis_work_scope_state
            ON research_synthesis_work_items(
                scope_id, state, level, ordinal, work_item_id
            );

        CREATE TABLE research_synthesis_artifacts (
            artifact_id BLOB(16) PRIMARY KEY CHECK(length(artifact_id) = 16),
            scope_id BLOB(16) NOT NULL CHECK(length(scope_id) = 16),
            work_item_id BLOB(16) NOT NULL UNIQUE CHECK(length(work_item_id) = 16),
            artifact_kind TEXT NOT NULL CHECK(artifact_kind IN ('reduce', 'final')),
            level INTEGER NOT NULL CHECK(level >= 0),
            ordinal INTEGER NOT NULL CHECK(ordinal >= 0),
            content_json TEXT NOT NULL,
            content_hash BLOB(32) NOT NULL CHECK(length(content_hash) = 32),
            processing_run_id BLOB(16) NOT NULL UNIQUE
                CHECK(length(processing_run_id) = 16),
            created_at_us INTEGER NOT NULL,
            UNIQUE(artifact_id, work_item_id),
            FOREIGN KEY(scope_id) REFERENCES research_scopes(scope_id),
            FOREIGN KEY(work_item_id)
                REFERENCES research_synthesis_work_items(work_item_id),
            FOREIGN KEY(processing_run_id)
                REFERENCES processing_runs(processing_run_id)
        ) WITHOUT ROWID;

        CREATE INDEX idx_research_synthesis_artifacts_scope
            ON research_synthesis_artifacts(
                scope_id, level, ordinal, artifact_id
            );

        CREATE TABLE research_synthesis_work_inputs (
            work_item_id BLOB(16) NOT NULL CHECK(length(work_item_id) = 16),
            ordinal INTEGER NOT NULL CHECK(ordinal >= 0),
            input_kind TEXT NOT NULL CHECK(input_kind IN (
                'source_analysis_artifact',
                'research_synthesis_artifact'
            )),
            source_analysis_artifact_id BLOB(16) NULL CHECK(
                source_analysis_artifact_id IS NULL
                OR length(source_analysis_artifact_id) = 16
            ),
            research_synthesis_artifact_id BLOB(16) NULL CHECK(
                research_synthesis_artifact_id IS NULL
                OR length(research_synthesis_artifact_id) = 16
            ),
            PRIMARY KEY(work_item_id, ordinal),
            FOREIGN KEY(work_item_id)
                REFERENCES research_synthesis_work_items(work_item_id),
            FOREIGN KEY(source_analysis_artifact_id)
                REFERENCES source_analysis_artifacts(artifact_id),
            FOREIGN KEY(research_synthesis_artifact_id)
                REFERENCES research_synthesis_artifacts(artifact_id),
            CHECK(
                (
                    input_kind = 'source_analysis_artifact'
                    AND source_analysis_artifact_id IS NOT NULL
                    AND research_synthesis_artifact_id IS NULL
                )
                OR
                (
                    input_kind = 'research_synthesis_artifact'
                    AND source_analysis_artifact_id IS NULL
                    AND research_synthesis_artifact_id IS NOT NULL
                )
            )
        ) WITHOUT ROWID;

        CREATE INDEX idx_research_synthesis_inputs_source_artifact
            ON research_synthesis_work_inputs(source_analysis_artifact_id)
            WHERE source_analysis_artifact_id IS NOT NULL;

        CREATE INDEX idx_research_synthesis_inputs_research_artifact
            ON research_synthesis_work_inputs(research_synthesis_artifact_id)
            WHERE research_synthesis_artifact_id IS NOT NULL;

        CREATE TABLE research_synthesis_output_evidence (
            artifact_id BLOB(16) NOT NULL CHECK(length(artifact_id) = 16),
            work_item_id BLOB(16) NOT NULL CHECK(length(work_item_id) = 16),
            output_kind TEXT NOT NULL CHECK(output_kind IN (
                'finding', 'contradiction'
            )),
            output_ordinal INTEGER NOT NULL CHECK(output_ordinal >= 0),
            input_ordinal INTEGER NOT NULL CHECK(input_ordinal >= 0),
            PRIMARY KEY(
                artifact_id, output_kind, output_ordinal, input_ordinal
            ),
            FOREIGN KEY(artifact_id, work_item_id)
                REFERENCES research_synthesis_artifacts(
                    artifact_id, work_item_id
                ),
            FOREIGN KEY(work_item_id, input_ordinal)
                REFERENCES research_synthesis_work_inputs(
                    work_item_id, ordinal
                )
        ) WITHOUT ROWID;

        CREATE INDEX idx_research_synthesis_evidence_input
            ON research_synthesis_output_evidence(
                work_item_id, input_ordinal, artifact_id
            );

        CREATE TABLE research_results (
            result_id BLOB(16) PRIMARY KEY CHECK(length(result_id) = 16),
            scope_id BLOB(16) NOT NULL UNIQUE CHECK(length(scope_id) = 16),
            final_artifact_id BLOB(16) NULL UNIQUE CHECK(
                final_artifact_id IS NULL OR length(final_artifact_id) = 16
            ),
            content_json TEXT NOT NULL,
            content_hash BLOB(32) NOT NULL CHECK(length(content_hash) = 32),
            snapshot_commit_seq INTEGER NOT NULL CHECK(snapshot_commit_seq >= 0),
            model_signature_id BLOB(16) NULL CHECK(
                model_signature_id IS NULL OR length(model_signature_id) = 16
            ),
            synthesis_pipeline_version TEXT NOT NULL
                CHECK(length(synthesis_pipeline_version) > 0),
            candidate_total INTEGER NOT NULL CHECK(candidate_total >= 0),
            processed_count INTEGER NOT NULL CHECK(processed_count >= 0),
            successful_count INTEGER NOT NULL CHECK(successful_count >= 0),
            irrelevant_count INTEGER NOT NULL CHECK(irrelevant_count >= 0),
            failed_count INTEGER NOT NULL CHECK(failed_count >= 0),
            unavailable_count INTEGER NOT NULL CHECK(unavailable_count >= 0),
            excluded_count INTEGER NOT NULL CHECK(excluded_count >= 0),
            coverage_ratio REAL NOT NULL CHECK(
                coverage_ratio >= 0.0 AND coverage_ratio <= 1.0
            ),
            problem_sources_json TEXT NOT NULL,
            created_at_us INTEGER NOT NULL,
            FOREIGN KEY(scope_id) REFERENCES research_scopes(scope_id),
            FOREIGN KEY(final_artifact_id)
                REFERENCES research_synthesis_artifacts(artifact_id),
            FOREIGN KEY(model_signature_id)
                REFERENCES model_signatures(model_signature_id),
            CHECK(
                processed_count
                = successful_count
                + irrelevant_count
                + failed_count
                + unavailable_count
            ),
            CHECK(candidate_total >= processed_count + excluded_count)
        ) WITHOUT ROWID;

        CREATE INDEX idx_research_results_model_signature
            ON research_results(model_signature_id)
            WHERE model_signature_id IS NOT NULL;

        UPDATE schema_metadata
        SET schema_version = {RESEARCH_SYNTHESIS_SCHEMA_VERSION},
            last_migration_id = '{RESEARCH_SYNTHESIS_MIGRATION_ID}',
            minimum_reader_version = {RESEARCH_SYNTHESIS_SCHEMA_VERSION}
        WHERE singleton_id = 1;

        PRAGMA user_version = {RESEARCH_SYNTHESIS_SCHEMA_VERSION};
        COMMIT;
        """
    )


def _migrate_schema_v24_to_v25(connection: sqlite3.Connection) -> None:
    """Add Research promotion, external access, resources, and verified backup state."""
    connection.executescript(
        f"""
        BEGIN IMMEDIATE;

        CREATE TABLE research_promotion_sets (
            proposal_set_id BLOB(16) PRIMARY KEY CHECK(length(proposal_set_id) = 16),
            result_id BLOB(16) NOT NULL UNIQUE CHECK(length(result_id) = 16),
            result_content_hash BLOB(32) NOT NULL CHECK(length(result_content_hash) = 32),
            state TEXT NOT NULL CHECK(state IN ('pending', 'completed')),
            created_at_us INTEGER NOT NULL,
            updated_at_us INTEGER NOT NULL CHECK(updated_at_us >= created_at_us),
            FOREIGN KEY(result_id) REFERENCES research_results(result_id)
        ) WITHOUT ROWID;

        CREATE TABLE research_promotion_items (
            proposal_id BLOB(16) PRIMARY KEY CHECK(length(proposal_id) = 16),
            proposal_set_id BLOB(16) NOT NULL CHECK(length(proposal_set_id) = 16),
            ordinal INTEGER NOT NULL CHECK(ordinal >= 0),
            proposal_type TEXT NOT NULL
                CHECK(proposal_type IN ('knowledge', 'claim', 'contradiction')),
            payload_json TEXT NOT NULL,
            evidence_kind TEXT NOT NULL
                CHECK(evidence_kind IN ('summary', 'finding', 'contradiction')),
            evidence_ordinal INTEGER NULL CHECK(
                evidence_ordinal IS NULL OR evidence_ordinal >= 0
            ),
            source_analysis_artifact_ids_json TEXT NOT NULL,
            state TEXT NOT NULL CHECK(state IN ('pending', 'accepted', 'rejected')),
            accepted_entity_id BLOB(16) NULL CHECK(
                accepted_entity_id IS NULL OR length(accepted_entity_id) = 16
            ),
            accepted_revision_id BLOB(16) NULL CHECK(
                accepted_revision_id IS NULL OR length(accepted_revision_id) = 16
            ),
            created_at_us INTEGER NOT NULL,
            decided_at_us INTEGER NULL CHECK(
                decided_at_us IS NULL OR decided_at_us >= created_at_us
            ),
            UNIQUE(proposal_set_id, ordinal),
            FOREIGN KEY(proposal_set_id)
                REFERENCES research_promotion_sets(proposal_set_id),
            FOREIGN KEY(accepted_entity_id) REFERENCES entity_registry(entity_id),
            FOREIGN KEY(accepted_revision_id) REFERENCES revisions(revision_id),
            CHECK(
                (state = 'accepted'
                 AND accepted_entity_id IS NOT NULL
                 AND accepted_revision_id IS NOT NULL
                 AND decided_at_us IS NOT NULL)
                OR
                (state = 'rejected'
                 AND accepted_entity_id IS NULL
                 AND accepted_revision_id IS NULL
                 AND decided_at_us IS NOT NULL)
                OR
                (state = 'pending'
                 AND accepted_entity_id IS NULL
                 AND accepted_revision_id IS NULL
                 AND decided_at_us IS NULL)
            ),
            CHECK(
                (evidence_kind = 'summary' AND evidence_ordinal IS NULL)
                OR
                (evidence_kind IN ('finding', 'contradiction')
                 AND evidence_ordinal IS NOT NULL)
            )
        ) WITHOUT ROWID;

        CREATE INDEX idx_research_promotion_items_state
            ON research_promotion_items(proposal_set_id, state, ordinal);

        CREATE TABLE research_knowledge_origins (
            origin_id BLOB(16) PRIMARY KEY CHECK(length(origin_id) = 16),
            subject_revision_id BLOB(16) NOT NULL CHECK(length(subject_revision_id) = 16),
            subject_entity_id BLOB(16) NOT NULL CHECK(length(subject_entity_id) = 16),
            result_id BLOB(16) NOT NULL CHECK(length(result_id) = 16),
            proposal_id BLOB(16) NOT NULL UNIQUE CHECK(length(proposal_id) = 16),
            acceptance_commit_id BLOB(16) NOT NULL UNIQUE
                CHECK(length(acceptance_commit_id) = 16),
            final_artifact_id BLOB(16) NOT NULL CHECK(length(final_artifact_id) = 16),
            source_analysis_artifact_ids_json TEXT NOT NULL,
            source_anchor_ids_json TEXT NOT NULL,
            source_ids_json TEXT NOT NULL,
            created_at_us INTEGER NOT NULL,
            FOREIGN KEY(subject_revision_id) REFERENCES revisions(revision_id),
            FOREIGN KEY(subject_entity_id) REFERENCES entity_registry(entity_id),
            FOREIGN KEY(result_id) REFERENCES research_results(result_id),
            FOREIGN KEY(proposal_id) REFERENCES research_promotion_items(proposal_id),
            FOREIGN KEY(acceptance_commit_id) REFERENCES commit_records(commit_id),
            FOREIGN KEY(final_artifact_id)
                REFERENCES research_synthesis_artifacts(artifact_id)
        ) WITHOUT ROWID;

        CREATE INDEX idx_research_knowledge_origins_result
            ON research_knowledge_origins(result_id, subject_entity_id);

        CREATE TABLE external_access_authorizations (
            authorization_id BLOB(16) PRIMARY KEY CHECK(length(authorization_id) = 16),
            actor_id BLOB(16) NOT NULL CHECK(length(actor_id) = 16),
            purpose TEXT NOT NULL CHECK(length(purpose) > 0),
            allowed_hosts_json TEXT NOT NULL,
            privacy_route TEXT NOT NULL CHECK(
                privacy_route IN ('tor_preferred', 'tor', 'direct_explicit')
            ),
            origin TEXT NOT NULL CHECK(origin = 'explicit_user'),
            expires_at_us INTEGER NOT NULL,
            revoked_at_us INTEGER NULL,
            created_at_us INTEGER NOT NULL,
            FOREIGN KEY(actor_id) REFERENCES actors(actor_id),
            CHECK(expires_at_us > created_at_us),
            CHECK(revoked_at_us IS NULL OR revoked_at_us >= created_at_us)
        ) WITHOUT ROWID;

        CREATE TABLE external_access_events (
            event_id BLOB(16) PRIMARY KEY CHECK(length(event_id) = 16),
            authorization_id BLOB(16) NOT NULL CHECK(length(authorization_id) = 16),
            request_url_hash BLOB(32) NOT NULL CHECK(length(request_url_hash) = 32),
            destination_host TEXT NOT NULL CHECK(length(destination_host) > 0),
            method TEXT NOT NULL CHECK(method IN ('GET')),
            privacy_route TEXT NOT NULL CHECK(
                privacy_route IN ('tor_preferred', 'tor', 'direct_explicit')
            ),
            outcome TEXT NOT NULL CHECK(
                outcome IN ('captured', 'failed', 'denied')
            ),
            reason_code TEXT NULL,
            response_bytes INTEGER NULL CHECK(
                response_bytes IS NULL OR response_bytes >= 0
            ),
            source_id BLOB(16) NULL CHECK(
                source_id IS NULL OR length(source_id) = 16
            ),
            created_at_us INTEGER NOT NULL,
            FOREIGN KEY(authorization_id)
                REFERENCES external_access_authorizations(authorization_id),
            FOREIGN KEY(source_id) REFERENCES sources(source_id)
        ) WITHOUT ROWID;

        CREATE INDEX idx_external_access_events_authorization
            ON external_access_events(authorization_id, created_at_us);

        CREATE TABLE external_source_captures (
            source_id BLOB(16) PRIMARY KEY CHECK(length(source_id) = 16),
            authorization_id BLOB(16) NOT NULL CHECK(length(authorization_id) = 16),
            access_event_id BLOB(16) NOT NULL UNIQUE CHECK(length(access_event_id) = 16),
            provenance_url TEXT NOT NULL CHECK(length(provenance_url) > 0),
            captured_at_us INTEGER NOT NULL,
            FOREIGN KEY(source_id) REFERENCES sources(source_id),
            FOREIGN KEY(authorization_id)
                REFERENCES external_access_authorizations(authorization_id),
            FOREIGN KEY(access_event_id) REFERENCES external_access_events(event_id)
        ) WITHOUT ROWID;

        CREATE TABLE resource_policy (
            singleton_id INTEGER PRIMARY KEY CHECK(singleton_id = 1),
            mode TEXT NOT NULL CHECK(
                mode IN ('balanced', 'quiet', 'performance', 'pause_background')
            ),
            ram_headroom_bytes INTEGER NOT NULL CHECK(ram_headroom_bytes >= 0),
            disk_headroom_bytes INTEGER NOT NULL CHECK(disk_headroom_bytes >= 0),
            gpu_background_threshold REAL NOT NULL CHECK(
                gpu_background_threshold >= 0.0
                AND gpu_background_threshold <= 1.0
            ),
            updated_at_us INTEGER NOT NULL,
            updated_by_actor_id BLOB(16) NULL CHECK(
                updated_by_actor_id IS NULL OR length(updated_by_actor_id) = 16
            ),
            FOREIGN KEY(updated_by_actor_id) REFERENCES actors(actor_id)
        );

        INSERT INTO resource_policy (
            singleton_id, mode, ram_headroom_bytes, disk_headroom_bytes,
            gpu_background_threshold, updated_at_us, updated_by_actor_id
        ) VALUES (
            1, 'balanced', 1073741824, 1073741824, 0.85,
            CAST(strftime('%s','now') AS INTEGER) * 1000000, NULL
        );

        CREATE TABLE resource_runtime_snapshots (
            snapshot_id BLOB(16) PRIMARY KEY CHECK(length(snapshot_id) = 16),
            captured_at_us INTEGER NOT NULL,
            ram_total_bytes INTEGER NULL CHECK(
                ram_total_bytes IS NULL OR ram_total_bytes >= 0
            ),
            ram_available_bytes INTEGER NULL CHECK(
                ram_available_bytes IS NULL OR ram_available_bytes >= 0
            ),
            disk_free_bytes INTEGER NOT NULL CHECK(disk_free_bytes >= 0),
            cpu_load_fraction REAL NULL CHECK(
                cpu_load_fraction IS NULL OR
                (cpu_load_fraction >= 0.0 AND cpu_load_fraction <= 1.0)
            ),
            gpu_utilization_fraction REAL NULL CHECK(
                gpu_utilization_fraction IS NULL OR
                (gpu_utilization_fraction >= 0.0 AND gpu_utilization_fraction <= 1.0)
            ),
            vram_total_bytes INTEGER NULL CHECK(
                vram_total_bytes IS NULL OR vram_total_bytes >= 0
            ),
            vram_available_bytes INTEGER NULL CHECK(
                vram_available_bytes IS NULL OR vram_available_bytes >= 0
            ),
            model_loaded INTEGER NULL CHECK(model_loaded IN (0, 1)),
            degraded_metrics_json TEXT NOT NULL
        ) WITHOUT ROWID;

        CREATE INDEX idx_resource_runtime_snapshots_time
            ON resource_runtime_snapshots(captured_at_us DESC);

        CREATE TABLE backup_targets (
            target_id BLOB(16) PRIMARY KEY CHECK(length(target_id) = 16),
            root_path TEXT NOT NULL UNIQUE CHECK(length(root_path) > 0),
            status TEXT NOT NULL CHECK(status IN ('active', 'offline', 'retired')),
            created_at_us INTEGER NOT NULL,
            created_by_actor_id BLOB(16) NOT NULL CHECK(
                length(created_by_actor_id) = 16
            ),
            FOREIGN KEY(created_by_actor_id) REFERENCES actors(actor_id)
        ) WITHOUT ROWID;

        CREATE TABLE backup_snapshots (
            snapshot_id BLOB(16) PRIMARY KEY CHECK(length(snapshot_id) = 16),
            target_id BLOB(16) NOT NULL CHECK(length(target_id) = 16),
            state TEXT NOT NULL CHECK(state IN ('creating', 'complete', 'failed')),
            verification_status TEXT NOT NULL CHECK(
                verification_status IN (
                    'unverified', 'verified_light', 'verified_deep', 'failed'
                )
            ),
            relative_path TEXT NOT NULL CHECK(length(relative_path) > 0),
            snapshot_commit_seq INTEGER NULL CHECK(
                snapshot_commit_seq IS NULL OR snapshot_commit_seq >= 0
            ),
            schema_version INTEGER NULL CHECK(
                schema_version IS NULL OR schema_version >= 1
            ),
            db_sha256 BLOB(32) NULL CHECK(
                db_sha256 IS NULL OR length(db_sha256) = 32
            ),
            manifest_sha256 BLOB(32) NULL CHECK(
                manifest_sha256 IS NULL OR length(manifest_sha256) = 32
            ),
            object_count INTEGER NOT NULL CHECK(object_count >= 0),
            created_at_us INTEGER NOT NULL,
            completed_at_us INTEGER NULL CHECK(
                completed_at_us IS NULL OR completed_at_us >= created_at_us
            ),
            failure_detail TEXT NULL,
            FOREIGN KEY(target_id) REFERENCES backup_targets(target_id),
            CHECK(
                (state = 'complete'
                 AND verification_status IN ('verified_light', 'verified_deep')
                 AND snapshot_commit_seq IS NOT NULL
                 AND schema_version IS NOT NULL
                 AND db_sha256 IS NOT NULL
                 AND manifest_sha256 IS NOT NULL
                 AND completed_at_us IS NOT NULL)
                OR state != 'complete'
            )
        ) WITHOUT ROWID;

        CREATE INDEX idx_backup_snapshots_target_time
            ON backup_snapshots(target_id, created_at_us DESC);

        CREATE TABLE backup_snapshot_pins (
            snapshot_id BLOB(16) NOT NULL CHECK(length(snapshot_id) = 16),
            blob_id BLOB(16) NOT NULL CHECK(length(blob_id) = 16),
            pinned_at_us INTEGER NOT NULL,
            PRIMARY KEY(snapshot_id, blob_id),
            FOREIGN KEY(snapshot_id) REFERENCES backup_snapshots(snapshot_id),
            FOREIGN KEY(blob_id) REFERENCES blob_records(blob_id)
        ) WITHOUT ROWID;

        UPDATE schema_metadata
        SET schema_version = {CONSOLIDATED_OPERATIONS_SCHEMA_VERSION},
            last_migration_id = '{CONSOLIDATED_OPERATIONS_MIGRATION_ID}',
            minimum_reader_version = {CONSOLIDATED_OPERATIONS_SCHEMA_VERSION}
        WHERE singleton_id = 1;

        PRAGMA user_version = {CONSOLIDATED_OPERATIONS_SCHEMA_VERSION};
        COMMIT;
        """
    )


def _migrate_schema_v28_to_v29(
    connection: sqlite3.Connection,
) -> None:
    """Add exact terminal-source backlinks for hierarchical synthesis outputs."""
    if connection.in_transaction:
        raise RuntimeError(
            "Precise Research provenance migration requires no active transaction."
        )

    _verify_schema_v28(connection)

    try:
        connection.executescript(
            f"""
            BEGIN IMMEDIATE;

            CREATE TABLE research_synthesis_output_source_evidence (
                artifact_id BLOB(16) NOT NULL
                    CHECK(length(artifact_id) = 16),
                output_kind TEXT NOT NULL
                    CHECK(output_kind IN ('finding', 'contradiction')),
                output_ordinal INTEGER NOT NULL
                    CHECK(output_ordinal >= 0),
                source_analysis_artifact_id BLOB(16) NOT NULL
                    CHECK(length(source_analysis_artifact_id) = 16),
                PRIMARY KEY(
                    artifact_id,
                    output_kind,
                    output_ordinal,
                    source_analysis_artifact_id
                ),
                FOREIGN KEY(artifact_id)
                    REFERENCES research_synthesis_artifacts(artifact_id),
                FOREIGN KEY(source_analysis_artifact_id)
                    REFERENCES source_analysis_artifacts(artifact_id)
            ) WITHOUT ROWID;

            CREATE INDEX idx_research_synthesis_source_evidence_source
                ON research_synthesis_output_source_evidence(
                    source_analysis_artifact_id,
                    artifact_id,
                    output_kind,
                    output_ordinal
                );

            UPDATE schema_metadata
            SET schema_version = {
                    PRECISE_RESEARCH_PROVENANCE_SCHEMA_VERSION
                },
                last_migration_id = '{
                    PRECISE_RESEARCH_PROVENANCE_MIGRATION_ID
                }',
                minimum_reader_version = {
                    PRECISE_RESEARCH_PROVENANCE_SCHEMA_VERSION
                }
            WHERE singleton_id = 1;

            PRAGMA user_version = {
                PRECISE_RESEARCH_PROVENANCE_SCHEMA_VERSION
            };

            COMMIT;
            """
        )
    except BaseException:
        connection.rollback()
        raise


def _migrate_schema_v30_to_v31(
    connection: sqlite3.Connection,
) -> None:
    """Add restart-safe Raw Archive replication outbox and watermark."""
    if connection.in_transaction:
        raise RuntimeError(
            "Archive replication migration requires no active transaction."
        )

    _verify_schema_v30(connection)

    try:
        connection.executescript(
            f"""
            BEGIN IMMEDIATE;

            CREATE TABLE archive_replication_outbox (
                outbox_seq INTEGER PRIMARY KEY AUTOINCREMENT,
                blob_id BLOB(16) NOT NULL UNIQUE
                    CHECK(length(blob_id) = 16),
                target_role TEXT NOT NULL
                    CHECK(target_role = 'archive_root'),
                state TEXT NOT NULL
                    CHECK(state IN ('pending', 'verified')),
                attempt_count INTEGER NOT NULL DEFAULT 0
                    CHECK(attempt_count >= 0),
                created_at_us INTEGER NOT NULL,
                last_attempt_at_us INTEGER NULL,
                last_error_code TEXT NULL,
                last_error_detail TEXT NULL,
                verified_at_us INTEGER NULL,
                FOREIGN KEY(blob_id)
                    REFERENCES blob_records(blob_id),
                CHECK(
                    (state = 'pending' AND verified_at_us IS NULL)
                    OR
                    (state = 'verified' AND verified_at_us IS NOT NULL)
                )
            );

            CREATE INDEX idx_archive_replication_outbox_state
                ON archive_replication_outbox(
                    state,
                    outbox_seq
                );

            CREATE TABLE archive_replication_watermark (
                singleton_id INTEGER PRIMARY KEY
                    CHECK(singleton_id = 1),
                contiguous_verified_seq INTEGER NOT NULL
                    CHECK(contiguous_verified_seq >= 0),
                updated_at_us INTEGER NOT NULL
            );

            INSERT INTO archive_replication_watermark (
                singleton_id,
                contiguous_verified_seq,
                updated_at_us
            ) VALUES (
                1,
                0,
                CAST(strftime('%s','now') AS INTEGER) * 1000000
            );

            CREATE TRIGGER trg_blob_records_archive_replication_outbox
            AFTER INSERT ON blob_records
            WHEN NEW.storage_area = 'spool'
            BEGIN
                INSERT OR IGNORE INTO archive_replication_outbox (
                    blob_id,
                    target_role,
                    state,
                    attempt_count,
                    created_at_us,
                    last_attempt_at_us,
                    last_error_code,
                    last_error_detail,
                    verified_at_us
                ) VALUES (
                    NEW.blob_id,
                    'archive_root',
                    'pending',
                    0,
                    NEW.created_at_us,
                    NULL,
                    NULL,
                    NULL,
                    NULL
                );
            END;

            INSERT OR IGNORE INTO archive_replication_outbox (
                blob_id,
                target_role,
                state,
                attempt_count,
                created_at_us,
                last_attempt_at_us,
                last_error_code,
                last_error_detail,
                verified_at_us
            )
            SELECT
                blob_id,
                'archive_root',
                'pending',
                0,
                created_at_us,
                NULL,
                NULL,
                NULL,
                NULL
            FROM blob_records
            WHERE storage_area = 'spool'
            ORDER BY created_at_us, blob_id;

            UPDATE schema_metadata
            SET schema_version = {
                    ARCHIVE_REPLICATION_SCHEMA_VERSION
                },
                last_migration_id = '{
                    ARCHIVE_REPLICATION_MIGRATION_ID
                }',
                minimum_reader_version = {
                    ARCHIVE_REPLICATION_SCHEMA_VERSION
                }
            WHERE singleton_id = 1;

            PRAGMA user_version = {
                ARCHIVE_REPLICATION_SCHEMA_VERSION
            };

            COMMIT;
            """
        )
    except BaseException:
        connection.rollback()
        raise


def _migrate_schema_v31_to_v32(
    connection: sqlite3.Connection,
) -> None:
    """Add Protected-Content key hierarchy and encrypted payload envelopes."""
    if connection.in_transaction:
        raise RuntimeError(
            "Protected Content migration requires no active transaction."
        )

    _verify_schema_v31(connection)

    try:
        connection.executescript(
            f"""
            BEGIN IMMEDIATE;

            CREATE TABLE key_slots (
                key_slot_id BLOB(16) PRIMARY KEY
                    CHECK(length(key_slot_id) = 16),
                slot_type TEXT NOT NULL
                    CHECK(slot_type IN (
                        'password',
                        'recovery',
                        'os_secret'
                    )),
                kdf_algorithm TEXT NULL
                    CHECK(
                        kdf_algorithm IS NULL
                        OR kdf_algorithm = 'argon2id'
                    ),
                kdf_parameters_json TEXT NULL,
                salt BLOB NULL,
                wrap_algorithm TEXT NOT NULL
                    CHECK(
                        wrap_algorithm = 'AES-256-GCM'
                    ),
                wrap_nonce BLOB NOT NULL
                    CHECK(length(wrap_nonce) = 12),
                wrapped_root_key BLOB NOT NULL
                    CHECK(length(wrapped_root_key) = 48),
                created_at_us INTEGER NOT NULL,
                retired_at_us INTEGER NULL,
                status TEXT NOT NULL
                    CHECK(status IN (
                        'active',
                        'retired'
                    )),
                CHECK(
                    (
                        slot_type = 'password'
                        AND kdf_algorithm = 'argon2id'
                        AND kdf_parameters_json IS NOT NULL
                        AND salt IS NOT NULL
                        AND length(salt) >= 16
                    )
                    OR
                    slot_type IN (
                        'recovery',
                        'os_secret'
                    )
                ),
                CHECK(
                    (
                        status = 'active'
                        AND retired_at_us IS NULL
                    )
                    OR
                    (
                        status = 'retired'
                        AND retired_at_us IS NOT NULL
                    )
                )
            ) WITHOUT ROWID;

            CREATE UNIQUE INDEX
                uq_key_slots_active_password
            ON key_slots(slot_type)
            WHERE
                slot_type = 'password'
                AND status = 'active';

            CREATE TABLE protection_scopes (
                protection_scope_id BLOB(16)
                    PRIMARY KEY
                    CHECK(
                        length(protection_scope_id) = 16
                    ),
                lifecycle_state TEXT NOT NULL
                    CHECK(lifecycle_state IN (
                        'active',
                        'retired',
                        'pending_delete'
                    )),
                created_at_us INTEGER NOT NULL,
                current_scope_key_id BLOB(16) NULL
                    CHECK(
                        current_scope_key_id IS NULL
                        OR
                        length(current_scope_key_id) = 16
                    ),
                neutral_label TEXT NULL
                    CHECK(
                        neutral_label IS NULL
                        OR
                        length(neutral_label) <= 128
                    ),
                FOREIGN KEY(
                    current_scope_key_id,
                    protection_scope_id
                ) REFERENCES protection_scope_keys(
                    scope_key_id,
                    protection_scope_id
                )
            ) WITHOUT ROWID;

            CREATE TABLE protection_scope_keys (
                scope_key_id BLOB(16)
                    PRIMARY KEY
                    CHECK(length(scope_key_id) = 16),
                protection_scope_id BLOB(16)
                    NOT NULL
                    CHECK(
                        length(protection_scope_id) = 16
                    ),
                key_version INTEGER NOT NULL
                    CHECK(key_version >= 1),
                wrap_algorithm TEXT NOT NULL
                    CHECK(
                        wrap_algorithm = 'AES-256-GCM'
                    ),
                wrap_nonce BLOB NOT NULL
                    CHECK(length(wrap_nonce) = 12),
                wrapped_scope_key BLOB NOT NULL
                    CHECK(length(wrapped_scope_key) = 48),
                created_at_us INTEGER NOT NULL,
                retired_at_us INTEGER NULL,
                status TEXT NOT NULL
                    CHECK(status IN (
                        'active',
                        'retired'
                    )),
                UNIQUE(
                    protection_scope_id,
                    key_version
                ),
                UNIQUE(
                    scope_key_id,
                    protection_scope_id
                ),
                FOREIGN KEY(protection_scope_id)
                    REFERENCES protection_scopes(
                        protection_scope_id
                    ),
                CHECK(
                    (
                        status = 'active'
                        AND retired_at_us IS NULL
                    )
                    OR
                    (
                        status = 'retired'
                        AND retired_at_us IS NOT NULL
                    )
                )
            ) WITHOUT ROWID;

            CREATE INDEX
                idx_protection_scope_keys_scope
            ON protection_scope_keys(
                protection_scope_id,
                key_version
            );

            CREATE TABLE protected_payloads (
                protected_payload_id BLOB(16)
                    PRIMARY KEY
                    CHECK(
                        length(protected_payload_id) = 16
                    ),
                protection_scope_id BLOB(16)
                    NOT NULL
                    CHECK(
                        length(protection_scope_id) = 16
                    ),
                scope_key_id BLOB(16)
                    NOT NULL
                    CHECK(length(scope_key_id) = 16),
                cipher_suite TEXT NOT NULL
                    CHECK(
                        cipher_suite = 'AES-256-GCM'
                    ),
                ciphertext BLOB NOT NULL
                    CHECK(length(ciphertext) >= 16),
                nonce BLOB NOT NULL
                    CHECK(length(nonce) = 12),
                wrapped_dek BLOB NOT NULL
                    CHECK(length(wrapped_dek) = 48),
                dek_wrap_nonce BLOB NOT NULL
                    CHECK(length(dek_wrap_nonce) = 12),
                aad_version INTEGER NOT NULL
                    CHECK(aad_version >= 1),
                ciphertext_hash BLOB(32)
                    NOT NULL
                    CHECK(
                        length(ciphertext_hash) = 32
                    ),
                created_at_us INTEGER NOT NULL,
                FOREIGN KEY(protection_scope_id)
                    REFERENCES protection_scopes(
                        protection_scope_id
                    ),
                FOREIGN KEY(
                    scope_key_id,
                    protection_scope_id
                ) REFERENCES protection_scope_keys(
                    scope_key_id,
                    protection_scope_id
                )
            ) WITHOUT ROWID;

            CREATE INDEX
                idx_protected_payloads_scope
            ON protected_payloads(
                protection_scope_id,
                created_at_us,
                protected_payload_id
            );

            CREATE TABLE protected_blob_envelopes (
                blob_id BLOB(16)
                    PRIMARY KEY
                    CHECK(length(blob_id) = 16),
                protection_scope_id BLOB(16)
                    NOT NULL
                    CHECK(
                        length(protection_scope_id) = 16
                    ),
                scope_key_id BLOB(16)
                    NOT NULL
                    CHECK(length(scope_key_id) = 16),
                wrapped_dek BLOB NOT NULL
                    CHECK(length(wrapped_dek) = 48),
                dek_wrap_nonce BLOB NOT NULL
                    CHECK(length(dek_wrap_nonce) = 12),
                nonce_prefix BLOB NOT NULL
                    CHECK(length(nonce_prefix) = 8),
                chunk_size INTEGER NOT NULL
                    CHECK(chunk_size > 0),
                cipher_suite TEXT NOT NULL
                    CHECK(
                        cipher_suite = 'AES-256-GCM'
                    ),
                format_version INTEGER NOT NULL
                    CHECK(format_version >= 1),
                FOREIGN KEY(blob_id)
                    REFERENCES blob_records(blob_id),
                FOREIGN KEY(protection_scope_id)
                    REFERENCES protection_scopes(
                        protection_scope_id
                    ),
                FOREIGN KEY(
                    scope_key_id,
                    protection_scope_id
                ) REFERENCES protection_scope_keys(
                    scope_key_id,
                    protection_scope_id
                )
            ) WITHOUT ROWID;

            UPDATE schema_metadata
            SET schema_version = {
                    PROTECTED_CONTENT_SCHEMA_VERSION
                },
                last_migration_id = '{
                    PROTECTED_CONTENT_MIGRATION_ID
                }',
                minimum_reader_version = {
                    PROTECTED_CONTENT_SCHEMA_VERSION
                }
            WHERE singleton_id = 1;

            PRAGMA user_version = {
                PROTECTED_CONTENT_SCHEMA_VERSION
            };

            COMMIT;
            """
        )

    except BaseException:
        connection.rollback()
        raise


def _migrate_schema_v32_to_v33(
    connection: sqlite3.Connection,
) -> None:
    """Enable encrypted BlobRecords and Protected Source membership."""
    if connection.in_transaction:
        raise RuntimeError(
            "Protected Source/Blob migration requires no active transaction."
        )

    _verify_schema_v32(connection)

    previous_foreign_keys = int(
        connection.execute("PRAGMA foreign_keys").fetchone()[0]
    )
    previous_legacy_alter = int(
        connection.execute("PRAGMA legacy_alter_table").fetchone()[0]
    )
    connection.execute("PRAGMA foreign_keys = OFF")
    connection.execute("PRAGMA legacy_alter_table = ON")

    try:
        connection.executescript(
            f"""
            BEGIN IMMEDIATE;

            DROP TRIGGER
                trg_blob_records_archive_replication_outbox;

            ALTER TABLE blob_records
                RENAME TO blob_records_v32;

            CREATE TABLE blob_records (
                blob_id BLOB(16) PRIMARY KEY
                    CHECK(length(blob_id) = 16),
                byte_length INTEGER NOT NULL
                    CHECK(byte_length >= 0),
                media_type TEXT NULL,
                storage_area TEXT NOT NULL
                    CHECK(storage_area IN ('archive', 'spool')),
                storage_locator TEXT NOT NULL
                    CHECK(length(storage_locator) > 0),
                integrity_sha256 BLOB(32) NOT NULL
                    CHECK(length(integrity_sha256) = 32),
                encryption_state TEXT NOT NULL
                    CHECK(encryption_state IN ('none', 'protected_v1')),
                created_at_us INTEGER NOT NULL,
                verified_at_us INTEGER NOT NULL,
                UNIQUE(integrity_sha256, byte_length, encryption_state),
                UNIQUE(storage_area, storage_locator),
                FOREIGN KEY(blob_id)
                    REFERENCES entity_registry(entity_id)
            ) WITHOUT ROWID;

            INSERT INTO blob_records (
                blob_id,
                byte_length,
                media_type,
                storage_area,
                storage_locator,
                integrity_sha256,
                encryption_state,
                created_at_us,
                verified_at_us
            )
            SELECT
                blob_id,
                byte_length,
                media_type,
                storage_area,
                storage_locator,
                integrity_sha256,
                encryption_state,
                created_at_us,
                verified_at_us
            FROM blob_records_v32;

            DROP TABLE blob_records_v32;

            CREATE TRIGGER
                trg_blob_records_archive_replication_outbox
            AFTER INSERT ON blob_records
            WHEN NEW.storage_area = 'spool'
            BEGIN
                INSERT OR IGNORE INTO archive_replication_outbox (
                    blob_id,
                    target_role,
                    state,
                    attempt_count,
                    created_at_us,
                    last_attempt_at_us,
                    last_error_code,
                    last_error_detail,
                    verified_at_us
                ) VALUES (
                    NEW.blob_id,
                    'archive_root',
                    'pending',
                    0,
                    NEW.created_at_us,
                    NULL,
                    NULL,
                    NULL,
                    NULL
                );
            END;

            CREATE TABLE protected_sources (
                source_id BLOB(16) PRIMARY KEY
                    CHECK(length(source_id) = 16),
                protection_scope_id BLOB(16) NOT NULL
                    CHECK(length(protection_scope_id) = 16),
                protected_metadata_payload_id BLOB(16) NOT NULL UNIQUE
                    CHECK(length(protected_metadata_payload_id) = 16),
                created_at_us INTEGER NOT NULL,
                FOREIGN KEY(source_id)
                    REFERENCES sources(source_id),
                FOREIGN KEY(protection_scope_id)
                    REFERENCES protection_scopes(protection_scope_id),
                FOREIGN KEY(protected_metadata_payload_id)
                    REFERENCES protected_payloads(protected_payload_id)
            ) WITHOUT ROWID;

            CREATE INDEX idx_protected_sources_scope
            ON protected_sources(
                protection_scope_id,
                created_at_us,
                source_id
            );

            UPDATE schema_metadata
            SET schema_version = {
                    PROTECTED_SOURCE_BLOB_SCHEMA_VERSION
                },
                last_migration_id = '{
                    PROTECTED_SOURCE_BLOB_MIGRATION_ID
                }',
                minimum_reader_version = {
                    PROTECTED_SOURCE_BLOB_SCHEMA_VERSION
                }
            WHERE singleton_id = 1;

            PRAGMA user_version = {
                PROTECTED_SOURCE_BLOB_SCHEMA_VERSION
            };

            COMMIT;
            """
        )
    except BaseException:
        connection.rollback()
        raise
    finally:
        connection.execute(
            "PRAGMA legacy_alter_table = " + str(previous_legacy_alter)
        )
        connection.execute(
            "PRAGMA foreign_keys = " + str(previous_foreign_keys)
        )

    if connection.execute("PRAGMA foreign_key_check").fetchall():
        raise DatabaseCompatibilityError(
            "Protected Source/Blob migration produced invalid foreign keys."
        )


def _migrate_schema_v33_to_v34(
    connection: sqlite3.Connection,
) -> None:
    """Add restart-safe copy-on-write protection transitions for existing Sources."""
    if connection.in_transaction:
        raise RuntimeError(
            "Source protection transition migration requires no active transaction."
        )

    _verify_schema_v33(connection)

    try:
        connection.executescript(
            f"""
            BEGIN IMMEDIATE;

            CREATE TABLE source_protection_transitions (
                transition_id BLOB(16) PRIMARY KEY
                    CHECK(length(transition_id) = 16),
                source_id BLOB(16) NOT NULL UNIQUE
                    CHECK(length(source_id) = 16),
                protection_scope_id BLOB(16) NOT NULL
                    CHECK(length(protection_scope_id) = 16),
                old_blob_id BLOB(16) NOT NULL UNIQUE
                    CHECK(length(old_blob_id) = 16),
                target_blob_id BLOB(16) NULL UNIQUE
                    CHECK(
                        target_blob_id IS NULL
                        OR length(target_blob_id) = 16
                    ),
                protected_metadata_payload_id BLOB(16) NULL UNIQUE
                    CHECK(
                        protected_metadata_payload_id IS NULL
                        OR length(protected_metadata_payload_id) = 16
                    ),
                state TEXT NOT NULL
                    CHECK(state IN ('pending', 'prepared', 'sanitized')),
                created_at_us INTEGER NOT NULL,
                updated_at_us INTEGER NOT NULL
                    CHECK(updated_at_us >= created_at_us),
                FOREIGN KEY(source_id)
                    REFERENCES sources(source_id),
                FOREIGN KEY(protection_scope_id)
                    REFERENCES protection_scopes(protection_scope_id),
                FOREIGN KEY(old_blob_id)
                    REFERENCES blob_records(blob_id),
                FOREIGN KEY(target_blob_id)
                    REFERENCES blob_records(blob_id),
                FOREIGN KEY(protected_metadata_payload_id)
                    REFERENCES protected_payloads(protected_payload_id),
                CHECK(
                    (
                        state = 'pending'
                        AND target_blob_id IS NULL
                        AND protected_metadata_payload_id IS NULL
                    )
                    OR
                    (
                        state IN ('prepared', 'sanitized')
                        AND target_blob_id IS NOT NULL
                        AND protected_metadata_payload_id IS NOT NULL
                    )
                )
            ) WITHOUT ROWID;

            CREATE INDEX idx_source_protection_transitions_state
            ON source_protection_transitions(
                state,
                updated_at_us,
                transition_id
            );

            CREATE TRIGGER
                trg_source_protection_transition_block_blob_reuse
            BEFORE INSERT ON sources
            WHEN EXISTS (
                SELECT 1
                FROM source_protection_transitions AS t
                WHERE t.old_blob_id = NEW.blob_id
            )
            BEGIN
                SELECT RAISE(
                    ABORT,
                    'source protection transition active: blob reuse blocked'
                );
            END;

            CREATE TRIGGER
                trg_source_protection_transition_block_source_update
            BEFORE UPDATE ON sources
            WHEN EXISTS (
                SELECT 1
                FROM source_protection_transitions AS t
                WHERE t.source_id = OLD.source_id
                  AND NOT (
                      t.state = 'prepared'
                      AND t.target_blob_id IS NOT NULL
                      AND NEW.blob_id = t.target_blob_id
                      AND NEW.original_name IS NULL
                      AND NEW.original_modified_at_us IS NULL
                      AND NEW.mime_type = 'application/octet-stream'
                      AND NEW.source_uri IS NULL
                      AND NEW.content_sha256 = (
                          SELECT b.integrity_sha256
                          FROM blob_records AS b
                          WHERE b.blob_id = t.target_blob_id
                      )
                      AND NEW.source_type = OLD.source_type
                      AND NEW.created_at_us = OLD.created_at_us
                      AND NEW.acquired_at_us = OLD.acquired_at_us
                      AND NEW.lifecycle_state = OLD.lifecycle_state
                      AND NEW.provenance_id = OLD.provenance_id
                  )
            )
            BEGIN
                SELECT RAISE(
                    ABORT,
                    'source protection transition active: source update blocked'
                );
            END;

            CREATE TRIGGER
                trg_source_protection_transition_block_source_delete
            BEFORE DELETE ON sources
            WHEN EXISTS (
                SELECT 1
                FROM source_protection_transitions AS t
                WHERE t.source_id = OLD.source_id
            )
            BEGIN
                SELECT RAISE(
                    ABORT,
                    'source protection transition active: source delete blocked'
                );
            END;

            CREATE TRIGGER
                trg_source_protection_transition_block_representation
            BEFORE INSERT ON source_representations
            WHEN EXISTS (
                SELECT 1
                FROM source_protection_transitions AS t
                WHERE t.source_id = NEW.source_id
                   OR t.old_blob_id = NEW.blob_id
            )
            BEGIN
                SELECT RAISE(
                    ABORT,
                    'source protection transition active: representation blocked'
                );
            END;

            CREATE TRIGGER
                trg_source_protection_transition_block_old_blob_update
            BEFORE UPDATE ON blob_records
            WHEN EXISTS (
                SELECT 1
                FROM source_protection_transitions AS t
                WHERE t.old_blob_id = OLD.blob_id
            )
            BEGIN
                SELECT RAISE(
                    ABORT,
                    'source protection transition active: old blob update blocked'
                );
            END;

            CREATE TRIGGER
                trg_source_protection_transition_block_old_blob_delete
            BEFORE DELETE ON blob_records
            WHEN EXISTS (
                SELECT 1
                FROM source_protection_transitions AS t
                WHERE t.old_blob_id = OLD.blob_id
            )
            BEGIN
                SELECT RAISE(
                    ABORT,
                    'source protection transition active: old blob delete blocked'
                );
            END;

            UPDATE schema_metadata
            SET schema_version = {
                    SOURCE_PROTECTION_TRANSITION_SCHEMA_VERSION
                },
                last_migration_id = '{
                    SOURCE_PROTECTION_TRANSITION_MIGRATION_ID
                }',
                minimum_reader_version = {
                    SOURCE_PROTECTION_TRANSITION_SCHEMA_VERSION
                }
            WHERE singleton_id = 1;

            PRAGMA user_version = {
                SOURCE_PROTECTION_TRANSITION_SCHEMA_VERSION
            };

            COMMIT;
            """
        )
    except BaseException:
        connection.rollback()
        raise


def _migrate_schema_v34_to_v35(
    connection: sqlite3.Connection,
) -> None:
    """Add durable backup-target identity, retention, and verification state."""
    if connection.in_transaction:
        raise RuntimeError(
            "Backup retention migration requires no active transaction."
        )

    _verify_schema_v34(connection)

    duplicate_creating = connection.execute(
        """
        SELECT target_id
        FROM backup_snapshots
        WHERE state = 'creating'
        GROUP BY target_id
        HAVING COUNT(*) > 1
        LIMIT 1
        """
    ).fetchone()

    if duplicate_creating is not None:
        raise DatabaseCompatibilityError(
            "Multiple creating backup snapshots exist for one target."
        )

    target_columns = {
        str(row[1])
        for row in connection.execute(
            "PRAGMA table_info(backup_targets)"
        )
    }
    snapshot_columns = {
        str(row[1])
        for row in connection.execute(
            "PRAGMA table_info(backup_snapshots)"
        )
    }

    expected_target_additions = {
        "identity_initialized",
        "retention_daily",
        "retention_weekly",
        "retention_monthly",
        "retention_yearly",
    }
    expected_snapshot_additions = {
        "last_verified_at_us",
        "pruned_at_us",
    }

    target_present = expected_target_additions & target_columns
    snapshot_present = expected_snapshot_additions & snapshot_columns

    if target_present and target_present != expected_target_additions:
        raise DatabaseCompatibilityError(
            "Backup target retention migration is partially present."
        )

    if snapshot_present and snapshot_present != expected_snapshot_additions:
        raise DatabaseCompatibilityError(
            "Backup snapshot retention migration is partially present."
        )

    try:
        connection.execute("BEGIN IMMEDIATE")

        if not expected_target_additions.issubset(target_columns):
            connection.execute(
                """
                ALTER TABLE backup_targets
                ADD COLUMN identity_initialized INTEGER NOT NULL DEFAULT 0
                CHECK(identity_initialized IN (0, 1))
                """
            )
            connection.execute(
                """
                ALTER TABLE backup_targets
                ADD COLUMN retention_daily INTEGER NOT NULL DEFAULT 7
                CHECK(retention_daily >= 0)
                """
            )
            connection.execute(
                """
                ALTER TABLE backup_targets
                ADD COLUMN retention_weekly INTEGER NOT NULL DEFAULT 4
                CHECK(retention_weekly >= 0)
                """
            )
            connection.execute(
                """
                ALTER TABLE backup_targets
                ADD COLUMN retention_monthly INTEGER NOT NULL DEFAULT 12
                CHECK(retention_monthly >= 0)
                """
            )
            connection.execute(
                """
                ALTER TABLE backup_targets
                ADD COLUMN retention_yearly INTEGER NOT NULL DEFAULT 5
                CHECK(retention_yearly >= 0)
                """
            )

        if not expected_snapshot_additions.issubset(snapshot_columns):
            connection.execute(
                """
                ALTER TABLE backup_snapshots
                ADD COLUMN last_verified_at_us INTEGER NULL
                """
            )
            connection.execute(
                """
                ALTER TABLE backup_snapshots
                ADD COLUMN pruned_at_us INTEGER NULL
                """
            )

        connection.execute(
            """
            UPDATE backup_snapshots
            SET last_verified_at_us = completed_at_us
            WHERE state = 'complete'
              AND verification_status IN (
                  'verified_light',
                  'verified_deep'
              )
              AND last_verified_at_us IS NULL
            """
        )

        connection.execute(
            """
            CREATE UNIQUE INDEX IF NOT EXISTS
                uq_backup_snapshots_one_creating_per_target
            ON backup_snapshots(target_id)
            WHERE state = 'creating'
            """
        )

        connection.execute(
            """
            CREATE INDEX IF NOT EXISTS
                idx_backup_snapshots_target_retention
            ON backup_snapshots(
                target_id,
                pruned_at_us,
                completed_at_us DESC,
                snapshot_id
            )
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
                BACKUP_RETENTION_SCHEMA_VERSION,
                BACKUP_RETENTION_MIGRATION_ID,
                BACKUP_RETENTION_SCHEMA_VERSION,
            ),
        )

        connection.execute(
            f"PRAGMA user_version = {BACKUP_RETENTION_SCHEMA_VERSION}"
        )
        connection.execute("COMMIT")

    except BaseException:
        connection.rollback()
        raise


def _migrate_schema_v35_to_v36(
    connection: sqlite3.Connection,
) -> None:
    """Add the durable payload-free deletion ledger and backup watermarks."""
    if connection.in_transaction:
        raise RuntimeError(
            "Deletion ledger migration requires no active transaction."
        )

    _verify_schema_v35(
        connection
    )

    tables = set(
        _user_tables(
            connection
        )
    )

    ledger_columns = (
        {
            str(row[1])
            for row in connection.execute(
                "PRAGMA table_info(deletion_ledger)"
            )
        }
        if "deletion_ledger" in tables
        else set()
    )

    required_ledger_columns = {
        "ledger_seq",
        "deletion_id",
        "entity_id",
        "entity_type",
        "deleted_at_us",
        "deletion_commit_seq",
        "deleted_by_actor_id",
    }

    if (
        ledger_columns
        and not required_ledger_columns.issubset(
            ledger_columns
        )
    ):
        raise DatabaseCompatibilityError(
            "Deletion ledger migration is partially present."
        )

    target_columns = {
        str(row[1])
        for row in connection.execute(
            "PRAGMA table_info(backup_targets)"
        )
    }

    snapshot_columns = {
        str(row[1])
        for row in connection.execute(
            "PRAGMA table_info(backup_snapshots)"
        )
    }

    try:
        connection.execute(
            "BEGIN IMMEDIATE"
        )

        if "deletion_ledger" not in tables:
            connection.execute(
                """
                CREATE TABLE deletion_ledger (
                    ledger_seq INTEGER PRIMARY KEY AUTOINCREMENT,
                    deletion_id BLOB(16) NOT NULL UNIQUE
                        CHECK(length(deletion_id) = 16),
                    entity_id BLOB(16) NOT NULL
                        CHECK(length(entity_id) = 16),
                    entity_type TEXT NOT NULL
                        CHECK(length(entity_type) > 0),
                    deleted_at_us INTEGER NOT NULL
                        CHECK(deleted_at_us >= 0),
                    deletion_commit_seq INTEGER NOT NULL
                        CHECK(deletion_commit_seq > 0),
                    deleted_by_actor_id BLOB(16) NOT NULL
                        CHECK(length(deleted_by_actor_id) = 16)
                )
                """
            )

        connection.execute(
            """
            CREATE UNIQUE INDEX IF NOT EXISTS
                uq_deletion_ledger_entity
            ON deletion_ledger(entity_id)
            """
        )

        connection.execute(
            """
            CREATE INDEX IF NOT EXISTS
                idx_deletion_ledger_deleted_at
            ON deletion_ledger(
                deleted_at_us,
                ledger_seq
            )
            """
        )

        if (
            "deletion_ledger_watermark"
            not in target_columns
        ):
            connection.execute(
                """
                ALTER TABLE backup_targets
                ADD COLUMN deletion_ledger_watermark
                    INTEGER NOT NULL DEFAULT 0
                    CHECK(deletion_ledger_watermark >= 0)
                """
            )

        if (
            "deletion_ledger_watermark"
            not in snapshot_columns
        ):
            connection.execute(
                """
                ALTER TABLE backup_snapshots
                ADD COLUMN deletion_ledger_watermark
                    INTEGER NOT NULL DEFAULT 0
                    CHECK(deletion_ledger_watermark >= 0)
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
                DELETION_LEDGER_SCHEMA_VERSION,
                DELETION_LEDGER_MIGRATION_ID,
                DELETION_LEDGER_SCHEMA_VERSION,
            ),
        )

        connection.execute(
            f"PRAGMA user_version = "
            f"{DELETION_LEDGER_SCHEMA_VERSION}"
        )

        connection.execute(
            "COMMIT"
        )

    except BaseException:
        connection.rollback()
        raise


def _migrate_schema_v36_to_v37(
    connection: sqlite3.Connection,
) -> None:
    """Remove historical free-text operational errors without changing identity."""
    if connection.in_transaction:
        raise RuntimeError(
            "Operational-error sanitization migration "
            "requires no active transaction."
        )

    _verify_schema_v36(
        connection
    )

    try:
        connection.execute(
            "BEGIN IMMEDIATE"
        )

        for table, column in (
            _PERSISTED_ERROR_SCALAR_FIELDS
        ):
            rows = connection.execute(
                f"""
                SELECT DISTINCT "{column}"
                FROM "{table}"
                WHERE "{column}" IS NOT NULL
                """
            ).fetchall()

            for row in rows:
                original = str(
                    row[0]
                )

                sanitized_error = (
                    _sanitize_persisted_error_value(
                        original
                    )
                )

                if sanitized_error == original:
                    continue

                connection.execute(
                    f"""
                    UPDATE "{table}"
                    SET "{column}" = ?
                    WHERE "{column}" = ?
                    """,
                    (
                        sanitized_error,
                        original,
                    ),
                )

        checkpoint_rows = connection.execute(
            """
            SELECT
                c.checkpoint_id,
                j.job_type,
                c.last_confirmed_output_json
            FROM checkpoints AS c
            JOIN jobs AS j
              ON j.job_id = c.job_id
            WHERE c.last_confirmed_output_json IS NOT NULL
            """
        ).fetchall()

        for row in checkpoint_rows:
            job_type = str(
                row[1]
            )

            raw = str(
                row[2]
            )

            try:
                payload = json.loads(
                    raw
                )
            except json.JSONDecodeError as exc:
                raise DatabaseCompatibilityError(
                    "Historical checkpoint output "
                    "contains invalid JSON."
                ) from exc

            sanitized_payload, changed = (
                _sanitize_checkpoint_error_payload(
                    job_type=job_type,
                    value=payload,
                )
            )

            if not changed:
                continue

            connection.execute(
                """
                UPDATE checkpoints
                SET last_confirmed_output_json = ?
                WHERE checkpoint_id = ?
                """,
                (
                    _canonical_migration_json(
                        sanitized_payload
                    ),
                    row[0],
                ),
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
                OPERATIONAL_ERROR_SANITIZATION_SCHEMA_VERSION,
                OPERATIONAL_ERROR_SANITIZATION_MIGRATION_ID,
                OPERATIONAL_ERROR_SANITIZATION_SCHEMA_VERSION,
            ),
        )

        connection.execute(
            f"PRAGMA user_version = "
            f"{OPERATIONAL_ERROR_SANITIZATION_SCHEMA_VERSION}"
        )

        connection.execute(
            "COMMIT"
        )

    except BaseException:
        connection.rollback()
        raise


def _migrate_schema_v38_to_v39(
    connection: sqlite3.Connection,
) -> None:
    """Add Protected Source semantic and representation transition state."""
    if connection.in_transaction:
        raise RuntimeError(
            "Protected Source semantic migration "
            "requires no active transaction."
        )

    _verify_schema_v38(
        connection
    )

    try:
        connection.execute(
            "BEGIN IMMEDIATE"
        )

        connection.execute(
            """
            CREATE TABLE
            source_protected_semantic_payloads (
                source_id BLOB(16) NOT NULL
                    CHECK(length(source_id) = 16),

                semantic_kind TEXT NOT NULL
                    CHECK(length(trim(semantic_kind)) > 0),

                entity_id BLOB(16) NOT NULL
                    CHECK(length(entity_id) = 16),

                protection_scope_id BLOB(16) NOT NULL
                    CHECK(length(protection_scope_id) = 16),

                protected_payload_id BLOB(16) NOT NULL UNIQUE
                    CHECK(length(protected_payload_id) = 16),

                payload_version INTEGER NOT NULL
                    CHECK(payload_version >= 1),

                created_at_us INTEGER NOT NULL
                    CHECK(created_at_us >= 0),

                PRIMARY KEY(
                    source_id,
                    semantic_kind,
                    entity_id
                ),

                FOREIGN KEY(source_id)
                    REFERENCES sources(source_id),

                FOREIGN KEY(protection_scope_id)
                    REFERENCES protection_scopes(
                        protection_scope_id
                    ),

                FOREIGN KEY(protected_payload_id)
                    REFERENCES protected_payloads(
                        protected_payload_id
                    )
            ) WITHOUT ROWID
            """
        )

        connection.execute(
            """
            CREATE INDEX
            idx_source_protected_semantic_scope
            ON source_protected_semantic_payloads(
                protection_scope_id,
                source_id,
                semantic_kind,
                entity_id
            )
            """
        )

        connection.execute(
            """
            CREATE INDEX
            idx_source_protected_semantic_entity
            ON source_protected_semantic_payloads(
                semantic_kind,
                entity_id,
                source_id
            )
            """
        )

        connection.execute(
            """
            CREATE TABLE
            source_protection_representation_blobs (
                transition_id BLOB(16) NOT NULL
                    CHECK(length(transition_id) = 16),

                representation_id BLOB(16) NOT NULL
                    CHECK(length(representation_id) = 16),

                old_blob_id BLOB(16) NOT NULL
                    CHECK(length(old_blob_id) = 16),

                target_blob_id BLOB(16) NULL
                    CHECK(
                        target_blob_id IS NULL
                        OR length(target_blob_id) = 16
                    ),

                state TEXT NOT NULL
                    CHECK(
                        state IN (
                            'pending',
                            'prepared',
                            'swapped'
                        )
                    ),

                created_at_us INTEGER NOT NULL
                    CHECK(created_at_us >= 0),

                updated_at_us INTEGER NOT NULL
                    CHECK(updated_at_us >= created_at_us),

                PRIMARY KEY(
                    transition_id,
                    representation_id
                ),

                FOREIGN KEY(transition_id)
                    REFERENCES source_protection_transitions(
                        transition_id
                    ),

                FOREIGN KEY(representation_id)
                    REFERENCES source_representations(
                        representation_id
                    ),

                FOREIGN KEY(old_blob_id)
                    REFERENCES blob_records(blob_id),

                FOREIGN KEY(target_blob_id)
                    REFERENCES blob_records(blob_id),

                CHECK(
                    (
                        state = 'pending'
                        AND target_blob_id IS NULL
                    )
                    OR
                    (
                        state IN (
                            'prepared',
                            'swapped'
                        )
                        AND target_blob_id IS NOT NULL
                    )
                )
            ) WITHOUT ROWID
            """
        )

        connection.execute(
            """
            CREATE INDEX
            idx_source_protection_representation_state
            ON source_protection_representation_blobs(
                transition_id,
                state,
                representation_id
            )
            """
        )

        connection.execute(
            """
            CREATE INDEX
            idx_source_protection_representation_old_blob
            ON source_protection_representation_blobs(
                old_blob_id,
                transition_id,
                representation_id
            )
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
                PROTECTED_SOURCE_SEMANTIC_SCHEMA_VERSION,
                PROTECTED_SOURCE_SEMANTIC_MIGRATION_ID,
                PROTECTED_SOURCE_SEMANTIC_SCHEMA_VERSION,
            ),
        )

        connection.execute(
            f"PRAGMA user_version = "
            f"{PROTECTED_SOURCE_SEMANTIC_SCHEMA_VERSION}"
        )

        connection.execute(
            "COMMIT"
        )

    except BaseException:
        connection.rollback()
        raise


def _migrate_schema_v39_to_v40(
    connection: sqlite3.Connection,
) -> None:
    """Persist exact structured Grounded-chat replay receipts."""
    connection.execute(
        "BEGIN IMMEDIATE"
    )

    try:
        connection.execute(
            """
            CREATE TABLE grounded_response_receipts (
                operation_id BLOB(16) NOT NULL
                    CHECK(length(operation_id) = 16),

                chat_id BLOB(16) NOT NULL
                    CHECK(length(chat_id) = 16),

                processing_run_id BLOB(16) NOT NULL
                    CHECK(length(processing_run_id) = 16),

                payload_json TEXT NOT NULL
                    CHECK(length(payload_json) > 1),

                payload_sha256 TEXT NOT NULL
                    CHECK(length(payload_sha256) = 64),

                format_version INTEGER NOT NULL
                    CHECK(format_version = 1),

                created_at_us INTEGER NOT NULL
                    CHECK(created_at_us >= 0),

                PRIMARY KEY(operation_id),

                FOREIGN KEY(chat_id)
                    REFERENCES chats(chat_id)
                    ON DELETE CASCADE
            ) WITHOUT ROWID
            """
        )

        connection.execute(
            """
            CREATE INDEX
            idx_grounded_response_receipts_chat
            ON grounded_response_receipts(
                chat_id,
                created_at_us,
                operation_id
            )
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
                GROUNDED_RESPONSE_RECEIPT_SCHEMA_VERSION,
                GROUNDED_RESPONSE_RECEIPT_MIGRATION_ID,
                GROUNDED_RESPONSE_RECEIPT_SCHEMA_VERSION,
            ),
        )

        connection.execute(
            f"PRAGMA user_version = "
            f"{GROUNDED_RESPONSE_RECEIPT_SCHEMA_VERSION}"
        )

        connection.execute(
            "COMMIT"
        )

    except BaseException:
        connection.rollback()
        raise


# Preserve historical private evolution import/pickle identities.
_create_schema_v1.__module__ = "athena.storage.schema"
_migrate_schema_v1_to_v2.__module__ = "athena.storage.schema"
_migrate_schema_v2_to_v3.__module__ = "athena.storage.schema"
_migrate_schema_v3_to_v4.__module__ = "athena.storage.schema"
_migrate_schema_v4_to_v5.__module__ = "athena.storage.schema"
_migrate_schema_v5_to_v6.__module__ = "athena.storage.schema"
_migrate_schema_v6_to_v7.__module__ = "athena.storage.schema"
_migrate_schema_v7_to_v8.__module__ = "athena.storage.schema"
_migrate_schema_v8_to_v9.__module__ = "athena.storage.schema"
_migrate_schema_v9_to_v10.__module__ = "athena.storage.schema"
_migrate_schema_v10_to_v11.__module__ = "athena.storage.schema"
_migrate_schema_v11_to_v12.__module__ = "athena.storage.schema"
_migrate_schema_v12_to_v13.__module__ = "athena.storage.schema"
_migrate_schema_v13_to_v14.__module__ = "athena.storage.schema"
_migrate_schema_v14_to_v15.__module__ = "athena.storage.schema"
_migrate_schema_v15_to_v16.__module__ = "athena.storage.schema"
_migrate_schema_v16_to_v17.__module__ = "athena.storage.schema"
_migrate_schema_v17_to_v18.__module__ = "athena.storage.schema"
_migrate_schema_v18_to_v19.__module__ = "athena.storage.schema"
_migrate_schema_v19_to_v20.__module__ = "athena.storage.schema"
_migrate_schema_v20_to_v21.__module__ = "athena.storage.schema"
_migrate_schema_v21_to_v22.__module__ = "athena.storage.schema"
_migrate_schema_v22_to_v23.__module__ = "athena.storage.schema"
_migrate_schema_v23_to_v24.__module__ = "athena.storage.schema"
_migrate_schema_v24_to_v25.__module__ = "athena.storage.schema"
_migrate_schema_v28_to_v29.__module__ = "athena.storage.schema"
_migrate_schema_v30_to_v31.__module__ = "athena.storage.schema"
_migrate_schema_v31_to_v32.__module__ = "athena.storage.schema"
_migrate_schema_v32_to_v33.__module__ = "athena.storage.schema"
_migrate_schema_v33_to_v34.__module__ = "athena.storage.schema"
_migrate_schema_v34_to_v35.__module__ = "athena.storage.schema"
_migrate_schema_v35_to_v36.__module__ = "athena.storage.schema"
_migrate_schema_v36_to_v37.__module__ = "athena.storage.schema"
_migrate_schema_v38_to_v39.__module__ = "athena.storage.schema"
_migrate_schema_v39_to_v40.__module__ = "athena.storage.schema"
