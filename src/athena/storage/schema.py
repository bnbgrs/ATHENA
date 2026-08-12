"""ATHENA SQLite schema bootstrap, additive migrations, and compatibility checks."""

from __future__ import annotations

import sqlite3

ATHENA_APPLICATION_ID = 1_096_042_574  # ASCII "ATHN" / 0x4154484E
LEGACY_SCHEMA_VERSION = 1
KNOWLEDGE_SCHEMA_VERSION = 2
PROVENANCE_SCHEMA_VERSION = 3
MODEL_RUNS_SCHEMA_VERSION = 4
SCHEMA_VERSION = 5
STORAGE_LAYOUT_VERSION = 1
BLOB_FORMAT_VERSION = 1
KNOWLEDGE_CORE_MIGRATION_ID = "0002_knowledge_core"
PROVENANCE_INPUTS_MIGRATION_ID = "0003_provenance_inputs"
MODEL_RUNS_MIGRATION_ID = "0004_model_signatures_processing_runs"
REVIEW_QUEUE_MIGRATION_ID = "0005_semantic_review_queue"


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

    _configure_connection(connection)
    _verify_schema_v5(connection)


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
        SET schema_version = {SCHEMA_VERSION},
            last_migration_id = '{REVIEW_QUEUE_MIGRATION_ID}',
            minimum_reader_version = {SCHEMA_VERSION}
        WHERE singleton_id = 1;

        PRAGMA user_version = {SCHEMA_VERSION};
        COMMIT;
        """
    )


def _verify_schema_v5(connection: sqlite3.Connection) -> None:
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
        REVIEW_QUEUE_MIGRATION_ID,
        SCHEMA_VERSION,
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
    }
    missing_tables = required_tables.difference(_user_tables(connection))
    if missing_tables:
        missing = ", ".join(sorted(missing_tables))
        raise DatabaseCompatibilityError(f"ATHENA semantic schema is incomplete: {missing}.")

    foreign_key_failures = connection.execute("PRAGMA foreign_key_check").fetchall()
    if foreign_key_failures:
        raise DatabaseCompatibilityError("ATHENA foreign-key verification failed.")
