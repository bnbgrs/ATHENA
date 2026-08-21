"""ATHENA SQLite schema verification boundary."""

from __future__ import annotations

import json
import sqlite3

from athena.news.schema import (
    verify_news_schema_v26,
    verify_news_schema_v27,
    verify_news_schema_v28,
    verify_news_schema_v30,
)
from athena.storage.schema_contract import (
    ARCHIVE_REPLICATION_MIGRATION_ID as ARCHIVE_REPLICATION_MIGRATION_ID,
)
from athena.storage.schema_contract import (
    ARCHIVE_REPLICATION_SCHEMA_VERSION as ARCHIVE_REPLICATION_SCHEMA_VERSION,
)
from athena.storage.schema_contract import ATHENA_APPLICATION_ID as ATHENA_APPLICATION_ID
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
from athena.storage.schema_contract import NEWS_SYSTEM_MIGRATION_ID as NEWS_SYSTEM_MIGRATION_ID
from athena.storage.schema_contract import NEWS_SYSTEM_SCHEMA_VERSION as NEWS_SYSTEM_SCHEMA_VERSION
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
    SOURCE_ANALYSIS_MIGRATION_ID as SOURCE_ANALYSIS_MIGRATION_ID,
)
from athena.storage.schema_contract import (
    SOURCE_ANALYSIS_SCHEMA_VERSION as SOURCE_ANALYSIS_SCHEMA_VERSION,
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
from athena.storage.schema_contract import STORAGE_LAYOUT_VERSION as STORAGE_LAYOUT_VERSION
from athena.storage.schema_contract import DatabaseCompatibilityError as DatabaseCompatibilityError
from athena.storage.schema_contract import _user_tables as _user_tables
from athena.storage.schema_error_sanitization import (
    _PERSISTED_ERROR_SCALAR_FIELDS as _PERSISTED_ERROR_SCALAR_FIELDS,
)
from athena.storage.schema_error_sanitization import (
    _sanitize_checkpoint_error_payload as _sanitize_checkpoint_error_payload,
)
from athena.storage.schema_error_sanitization import (
    _sanitize_persisted_error_value as _sanitize_persisted_error_value,
)


def _verify_schema_v37(
    connection: sqlite3.Connection,
    *,
    schema_version: int = (
        OPERATIONAL_ERROR_SANITIZATION_SCHEMA_VERSION
    ),
    migration_id: str = (
        OPERATIONAL_ERROR_SANITIZATION_MIGRATION_ID
    ),
) -> None:
    _verify_schema_v36(
        connection,
        schema_version=schema_version,
        migration_id=migration_id,
    )

    for table, column in (
        _PERSISTED_ERROR_SCALAR_FIELDS
    ):
        rows = connection.execute(
            f"""
            SELECT "{column}"
            FROM "{table}"
            WHERE "{column}" IS NOT NULL
            """
        ).fetchall()

        for row in rows:
            value = str(
                row[0]
            )

            if (
                _sanitize_persisted_error_value(
                    value
                )
                != value
            ):
                raise DatabaseCompatibilityError(
                    "ATHENA contains unsanitized "
                    "operational error persistence."
                )

    checkpoint_rows = connection.execute(
        """
        SELECT
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
            row[0]
        )

        try:
            payload = json.loads(
                str(
                    row[1]
                )
            )
        except json.JSONDecodeError as exc:
            raise DatabaseCompatibilityError(
                "ATHENA checkpoint output is invalid JSON."
            ) from exc

        _sanitized, changed = (
            _sanitize_checkpoint_error_payload(
                job_type=job_type,
                value=payload,
            )
        )

        if changed:
            raise DatabaseCompatibilityError(
                "ATHENA contains unsanitized "
                "checkpoint error persistence."
            )

    if connection.execute(
        "PRAGMA foreign_key_check"
    ).fetchall():
        raise DatabaseCompatibilityError(
            "ATHENA foreign-key verification failed."
        )


def _verify_schema_v39(
    connection: sqlite3.Connection,
    *,
    schema_version: int = (
        PROTECTED_SOURCE_SEMANTIC_SCHEMA_VERSION
    ),
    migration_id: str = (
        PROTECTED_SOURCE_SEMANTIC_MIGRATION_ID
    ),
) -> None:
    _verify_schema_v38(
        connection,
        schema_version=schema_version,
        migration_id=migration_id,
    )

    required_tables = {
        "source_protected_semantic_payloads",
        "source_protection_representation_blobs",
    }

    tables = set(
        _user_tables(
            connection
        )
    )

    if not required_tables.issubset(
        tables
    ):
        raise DatabaseCompatibilityError(
            "ATHENA Protected Source semantic "
            "schema is incomplete."
        )

    semantic_columns = {
        str(row[1])
        for row
        in connection.execute(
            """
            PRAGMA table_info(
                source_protected_semantic_payloads
            )
            """
        )
    }

    expected_semantic_columns = {
        "source_id",
        "semantic_kind",
        "entity_id",
        "protection_scope_id",
        "protected_payload_id",
        "payload_version",
        "created_at_us",
    }

    if not expected_semantic_columns.issubset(
        semantic_columns
    ):
        raise DatabaseCompatibilityError(
            "ATHENA Protected Source semantic "
            "payload columns are incomplete."
        )

    transition_columns = {
        str(row[1])
        for row
        in connection.execute(
            """
            PRAGMA table_info(
                source_protection_representation_blobs
            )
            """
        )
    }

    expected_transition_columns = {
        "transition_id",
        "representation_id",
        "old_blob_id",
        "target_blob_id",
        "state",
        "created_at_us",
        "updated_at_us",
    }

    if not expected_transition_columns.issubset(
        transition_columns
    ):
        raise DatabaseCompatibilityError(
            "ATHENA Protected Source representation "
            "transition columns are incomplete."
        )

    indexes = {
        str(row[0])
        for row
        in connection.execute(
            """
            SELECT name
            FROM sqlite_master
            WHERE type = 'index'
              AND name IN (
                  'idx_source_protected_semantic_scope',
                  'idx_source_protected_semantic_entity',
                  'idx_source_protection_representation_state',
                  'idx_source_protection_representation_old_blob'
              )
            """
        )
    }

    expected_indexes = {
        "idx_source_protected_semantic_scope",
        "idx_source_protected_semantic_entity",
        "idx_source_protection_representation_state",
        "idx_source_protection_representation_old_blob",
    }

    if indexes != expected_indexes:
        raise DatabaseCompatibilityError(
            "ATHENA Protected Source semantic "
            "indexes are incomplete."
        )

    semantic_foreign_keys = {
        (
            str(row[3]),
            str(row[2]),
            str(row[4]),
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

    expected_semantic_foreign_keys = {
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
    }

    if not expected_semantic_foreign_keys.issubset(
        semantic_foreign_keys
    ):
        raise DatabaseCompatibilityError(
            "ATHENA Protected Source semantic "
            "foreign keys are incomplete."
        )

    transition_foreign_keys = {
        (
            str(row[3]),
            str(row[2]),
            str(row[4]),
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

    expected_transition_foreign_keys = {
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
    }

    if not expected_transition_foreign_keys.issubset(
        transition_foreign_keys
    ):
        raise DatabaseCompatibilityError(
            "ATHENA Protected Source representation "
            "foreign keys are incomplete."
        )

    invalid_semantic = connection.execute(
        """
        SELECT COUNT(*)
        FROM source_protected_semantic_payloads
        WHERE length(source_id) != 16
           OR length(trim(semantic_kind)) = 0
           OR length(entity_id) != 16
           OR length(protection_scope_id) != 16
           OR length(protected_payload_id) != 16
           OR payload_version < 1
           OR created_at_us < 0
        """
    ).fetchone()

    invalid_transitions = connection.execute(
        """
        SELECT COUNT(*)
        FROM source_protection_representation_blobs
        WHERE length(transition_id) != 16
           OR length(representation_id) != 16
           OR length(old_blob_id) != 16
           OR (
               target_blob_id IS NOT NULL
               AND length(target_blob_id) != 16
           )
           OR state NOT IN (
               'pending',
               'prepared',
               'swapped'
           )
           OR created_at_us < 0
           OR updated_at_us < created_at_us
           OR (
               state = 'pending'
               AND target_blob_id IS NOT NULL
           )
           OR (
               state IN (
                   'prepared',
                   'swapped'
               )
               AND target_blob_id IS NULL
           )
        """
    ).fetchone()

    if (
        invalid_semantic is None
        or invalid_transitions is None
        or int(
            invalid_semantic[0]
        )
        != 0
        or int(
            invalid_transitions[0]
        )
        != 0
    ):
        raise DatabaseCompatibilityError(
            "ATHENA Protected Source semantic "
            "state contains invalid records."
        )

    if connection.execute(
        "PRAGMA foreign_key_check"
    ).fetchall():
        raise DatabaseCompatibilityError(
            "ATHENA foreign-key verification failed."
        )


def _verify_schema_v38(
    connection: sqlite3.Connection,
    *,
    schema_version: int = (
        OPERATIONAL_ERROR_PHYSICAL_CLEANUP_SCHEMA_VERSION
    ),
    migration_id: str = (
        OPERATIONAL_ERROR_PHYSICAL_CLEANUP_MIGRATION_ID
    ),
) -> None:
    _verify_schema_v37(
        connection,
        schema_version=schema_version,
        migration_id=migration_id,
    )


def _verify_schema_v36(
    connection: sqlite3.Connection,
    *,
    schema_version: int = DELETION_LEDGER_SCHEMA_VERSION,
    migration_id: str = DELETION_LEDGER_MIGRATION_ID,
) -> None:
    _verify_schema_v35(
        connection,
        schema_version=schema_version,
        migration_id=migration_id,
    )

    if (
        "deletion_ledger"
        not in _user_tables(
            connection
        )
    ):
        raise DatabaseCompatibilityError(
            "ATHENA deletion ledger table is missing."
        )

    columns = {
        str(row[1])
        for row in connection.execute(
            "PRAGMA table_info(deletion_ledger)"
        )
    }

    required = {
        "ledger_seq",
        "deletion_id",
        "entity_id",
        "entity_type",
        "deleted_at_us",
        "deletion_commit_seq",
        "deleted_by_actor_id",
    }

    if not required.issubset(
        columns
    ):
        raise DatabaseCompatibilityError(
            "ATHENA deletion ledger schema is incomplete."
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

    if (
        "deletion_ledger_watermark"
        not in target_columns
        or "deletion_ledger_watermark"
        not in snapshot_columns
    ):
        raise DatabaseCompatibilityError(
            "ATHENA backup deletion-ledger "
            "watermark schema is incomplete."
        )

    indexes = {
        str(row[0])
        for row in connection.execute(
            """
            SELECT name
            FROM sqlite_master
            WHERE type = 'index'
              AND name IN (
                  'uq_deletion_ledger_entity',
                  'idx_deletion_ledger_deleted_at'
              )
            """
        )
    }

    if indexes != {
        "uq_deletion_ledger_entity",
        "idx_deletion_ledger_deleted_at",
    }:
        raise DatabaseCompatibilityError(
            "ATHENA deletion ledger indexes are incomplete."
        )

    invalid_ledger = connection.execute(
        """
        SELECT COUNT(*)
        FROM deletion_ledger
        WHERE ledger_seq <= 0
           OR length(deletion_id) != 16
           OR length(entity_id) != 16
           OR length(entity_type) = 0
           OR deleted_at_us < 0
           OR deletion_commit_seq <= 0
           OR length(deleted_by_actor_id) != 16
        """
    ).fetchone()

    if (
        invalid_ledger is None
        or int(
            invalid_ledger[0]
        ) != 0
    ):
        raise DatabaseCompatibilityError(
            "ATHENA deletion ledger contains invalid records."
        )

    invalid_targets = connection.execute(
        """
        SELECT COUNT(*)
        FROM backup_targets
        WHERE deletion_ledger_watermark < 0
        """
    ).fetchone()

    invalid_snapshots = connection.execute(
        """
        SELECT COUNT(*)
        FROM backup_snapshots
        WHERE deletion_ledger_watermark < 0
        """
    ).fetchone()

    if (
        invalid_targets is None
        or invalid_snapshots is None
        or int(invalid_targets[0]) != 0
        or int(invalid_snapshots[0]) != 0
    ):
        raise DatabaseCompatibilityError(
            "ATHENA deletion ledger watermark is invalid."
        )

    if connection.execute(
        "PRAGMA foreign_key_check"
    ).fetchall():
        raise DatabaseCompatibilityError(
            "ATHENA foreign-key verification failed."
        )


def _verify_schema_v35(
    connection: sqlite3.Connection,
    *,
    schema_version: int = BACKUP_RETENTION_SCHEMA_VERSION,
    migration_id: str = BACKUP_RETENTION_MIGRATION_ID,
) -> None:
    _verify_schema_v34(
        connection,
        schema_version=schema_version,
        migration_id=migration_id,
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

    if not {
        "identity_initialized",
        "retention_daily",
        "retention_weekly",
        "retention_monthly",
        "retention_yearly",
    }.issubset(target_columns):
        raise DatabaseCompatibilityError(
            "ATHENA backup-target retention schema is incomplete."
        )

    if not {
        "last_verified_at_us",
        "pruned_at_us",
    }.issubset(snapshot_columns):
        raise DatabaseCompatibilityError(
            "ATHENA backup-snapshot retention schema is incomplete."
        )

    indexes = {
        str(row[0])
        for row in connection.execute(
            """
            SELECT name
            FROM sqlite_master
            WHERE type = 'index'
              AND name IN (
                  'uq_backup_snapshots_one_creating_per_target',
                  'idx_backup_snapshots_target_retention'
              )
            """
        )
    }

    if indexes != {
        "uq_backup_snapshots_one_creating_per_target",
        "idx_backup_snapshots_target_retention",
    }:
        raise DatabaseCompatibilityError(
            "ATHENA backup retention indexes are incomplete."
        )

    invalid_policy = connection.execute(
        """
        SELECT COUNT(*)
        FROM backup_targets
        WHERE identity_initialized NOT IN (0, 1)
           OR retention_daily < 0
           OR retention_weekly < 0
           OR retention_monthly < 0
           OR retention_yearly < 0
        """
    ).fetchone()

    if invalid_policy is None or int(invalid_policy[0]) != 0:
        raise DatabaseCompatibilityError(
            "ATHENA backup target policy is invalid."
        )

    invalid_verified = connection.execute(
        """
        SELECT COUNT(*)
        FROM backup_snapshots
        WHERE state = 'complete'
          AND verification_status IN (
              'verified_light',
              'verified_deep'
          )
          AND last_verified_at_us IS NULL
        """
    ).fetchone()

    if invalid_verified is None or int(invalid_verified[0]) != 0:
        raise DatabaseCompatibilityError(
            "A completed backup lacks its verification timestamp."
        )

    invalid_pruned = connection.execute(
        """
        SELECT COUNT(*)
        FROM backup_snapshots
        WHERE pruned_at_us IS NOT NULL
          AND (
              completed_at_us IS NULL
              OR pruned_at_us < completed_at_us
          )
        """
    ).fetchone()

    if invalid_pruned is None or int(invalid_pruned[0]) != 0:
        raise DatabaseCompatibilityError(
            "A pruned backup has an invalid prune timestamp."
        )

    duplicate_creating = connection.execute(
        """
        SELECT COUNT(*)
        FROM (
            SELECT target_id
            FROM backup_snapshots
            WHERE state = 'creating'
            GROUP BY target_id
            HAVING COUNT(*) > 1
        )
        """
    ).fetchone()

    if duplicate_creating is None or int(duplicate_creating[0]) != 0:
        raise DatabaseCompatibilityError(
            "Multiple creating backups exist for one target."
        )

    if connection.execute("PRAGMA foreign_key_check").fetchall():
        raise DatabaseCompatibilityError(
            "ATHENA foreign-key verification failed."
        )


def _verify_schema_v34(
    connection: sqlite3.Connection,
    *,
    schema_version: int = SOURCE_PROTECTION_TRANSITION_SCHEMA_VERSION,
    migration_id: str = SOURCE_PROTECTION_TRANSITION_MIGRATION_ID,
) -> None:
    application_id = int(
        connection.execute("PRAGMA application_id").fetchone()[0]
    )
    user_version = int(
        connection.execute("PRAGMA user_version").fetchone()[0]
    )
    if (
        application_id != ATHENA_APPLICATION_ID
        or user_version != schema_version
    ):
        raise DatabaseCompatibilityError(
            "ATHENA Source protection transition schema version verification failed."
        )

    metadata = connection.execute(
        "SELECT schema_version, "
        "storage_layout_version, "
        "blob_format_version, "
        "last_migration_id, "
        "minimum_reader_version "
        "FROM schema_metadata "
        "WHERE singleton_id = 1"
    ).fetchone()
    expected = (
        schema_version,
        STORAGE_LAYOUT_VERSION,
        BLOB_FORMAT_VERSION,
        migration_id,
        schema_version,
    )
    if metadata is None or tuple(metadata) != expected:
        raise DatabaseCompatibilityError(
            "ATHENA Source protection transition schema_metadata verification failed."
        )

    _verify_schema_v31_compatible(connection)

    required_tables = {
        "key_slots",
        "protection_scopes",
        "protection_scope_keys",
        "protected_payloads",
        "protected_blob_envelopes",
        "protected_sources",
        "source_protection_transitions",
    }
    missing = required_tables.difference(_user_tables(connection))
    if missing:
        raise DatabaseCompatibilityError(
            "ATHENA Source protection transition schema is incomplete: "
            + ", ".join(sorted(missing))
            + "."
        )

    required_columns = {
        "key_slots": {
            "key_slot_id",
            "slot_type",
            "kdf_algorithm",
            "kdf_parameters_json",
            "salt",
            "wrap_algorithm",
            "wrap_nonce",
            "wrapped_root_key",
            "created_at_us",
            "retired_at_us",
            "status",
        },
        "protection_scopes": {
            "protection_scope_id",
            "lifecycle_state",
            "created_at_us",
            "current_scope_key_id",
            "neutral_label",
        },
        "protection_scope_keys": {
            "scope_key_id",
            "protection_scope_id",
            "key_version",
            "wrap_algorithm",
            "wrap_nonce",
            "wrapped_scope_key",
            "created_at_us",
            "retired_at_us",
            "status",
        },
        "protected_payloads": {
            "protected_payload_id",
            "protection_scope_id",
            "scope_key_id",
            "cipher_suite",
            "ciphertext",
            "nonce",
            "wrapped_dek",
            "dek_wrap_nonce",
            "aad_version",
            "ciphertext_hash",
            "created_at_us",
        },
        "protected_blob_envelopes": {
            "blob_id",
            "protection_scope_id",
            "scope_key_id",
            "wrapped_dek",
            "dek_wrap_nonce",
            "nonce_prefix",
            "chunk_size",
            "cipher_suite",
            "format_version",
        },
        "protected_sources": {
            "source_id",
            "protection_scope_id",
            "protected_metadata_payload_id",
            "created_at_us",
        },
        "source_protection_transitions": {
            "transition_id",
            "source_id",
            "protection_scope_id",
            "old_blob_id",
            "target_blob_id",
            "protected_metadata_payload_id",
            "state",
            "created_at_us",
            "updated_at_us",
        },
    }
    for table_name, columns in required_columns.items():
        actual = {
            str(row[1])
            for row in connection.execute(
                f"PRAGMA table_info({table_name})"
            )
        }
        if not columns.issubset(actual):
            raise DatabaseCompatibilityError(
                f"ATHENA table {table_name!r} is incomplete."
            )

    scope_columns = {
        str(row[1])
        for row in connection.execute(
            "PRAGMA table_info(protection_scopes)"
        )
    }
    if {"locked", "unlocked", "is_unlocked"} & scope_columns:
        raise DatabaseCompatibilityError(
            "ProtectionScope lock state must never be persisted."
        )

    password_index = connection.execute(
        """
        SELECT name
        FROM sqlite_master
        WHERE type = 'index'
          AND name = 'uq_key_slots_active_password'
        """
    ).fetchone()
    if password_index is None:
        raise DatabaseCompatibilityError(
            "ATHENA active-password-slot uniqueness index is missing."
        )

    blob_sql_row = connection.execute(
        """
        SELECT sql
        FROM sqlite_master
        WHERE type = 'table'
          AND name = 'blob_records'
        """
    ).fetchone()
    if blob_sql_row is None or "protected_v1" not in str(blob_sql_row[0]):
        raise DatabaseCompatibilityError(
            "ATHENA BlobRecord schema does not allow Protected Blobs."
        )

    missing_envelope = connection.execute(
        """
        SELECT COUNT(*)
        FROM blob_records AS b
        JOIN entity_registry AS be
          ON be.entity_id = b.blob_id
        LEFT JOIN protected_blob_envelopes AS e
          ON e.blob_id = b.blob_id
        LEFT JOIN protection_scopes AS scope
          ON scope.protection_scope_id =
             be.protection_scope_id
        WHERE b.encryption_state = 'protected_v1'
          AND e.blob_id IS NULL
          AND NOT (
              be.entity_type = 'blob_record'
              AND be.lifecycle_state = 'deleted'
              AND be.protection_scope_id IS NOT NULL
              AND scope.lifecycle_state = 'pending_delete'
              AND scope.current_scope_key_id IS NULL
              AND NOT EXISTS (
                  SELECT 1
                  FROM protection_scope_keys AS key
                  WHERE key.protection_scope_id =
                        be.protection_scope_id
              )
              AND NOT EXISTS (
                  SELECT 1
                  FROM protected_payloads AS payload
                  WHERE payload.protection_scope_id =
                        be.protection_scope_id
              )
              AND NOT EXISTS (
                  SELECT 1
                  FROM protected_blob_envelopes AS envelope
                  WHERE envelope.protection_scope_id =
                        be.protection_scope_id
              )
              AND NOT EXISTS (
                  SELECT 1
                  FROM protected_sources AS protected_source
                  WHERE protected_source.protection_scope_id =
                        be.protection_scope_id
              )
              AND NOT EXISTS (
                  SELECT 1
                  FROM source_protection_transitions AS transition
                  WHERE transition.protection_scope_id =
                        be.protection_scope_id
              )
              AND NOT EXISTS (
                  SELECT 1
                  FROM sources AS source
                  JOIN entity_registry AS source_entity
                    ON source_entity.entity_id =
                       source.source_id
                  WHERE source.blob_id = b.blob_id
                    AND source_entity.lifecycle_state
                        != 'deleted'
              )
          )
        """
    ).fetchone()
    if missing_envelope is None or int(missing_envelope[0]) != 0:
        raise DatabaseCompatibilityError(
            "A Protected Blob is missing its encrypted envelope."
        )

    invalid_source = connection.execute(
        """
        SELECT COUNT(*)
        FROM protected_sources AS ps
        JOIN sources AS s ON s.source_id = ps.source_id
        JOIN blob_records AS b ON b.blob_id = s.blob_id
        JOIN protected_blob_envelopes AS e ON e.blob_id = b.blob_id
        JOIN protected_payloads AS p
          ON p.protected_payload_id = ps.protected_metadata_payload_id
        JOIN entity_registry AS se ON se.entity_id = s.source_id
        JOIN entity_registry AS be ON be.entity_id = b.blob_id
        WHERE
            s.original_name IS NOT NULL
            OR s.original_modified_at_us IS NOT NULL
            OR s.source_uri IS NOT NULL
            OR s.mime_type != 'application/octet-stream'
            OR b.media_type != 'application/octet-stream'
            OR b.encryption_state != 'protected_v1'
            OR e.protection_scope_id != ps.protection_scope_id
            OR p.protection_scope_id != ps.protection_scope_id
            OR se.protection_scope_id != ps.protection_scope_id
            OR be.protection_scope_id != ps.protection_scope_id
        """
    ).fetchone()
    if invalid_source is None or int(invalid_source[0]) != 0:
        raise DatabaseCompatibilityError(
            "Protected Source public metadata or scope linkage is inconsistent."
        )

    invalid_transition = connection.execute(
        """
        SELECT COUNT(*)
        FROM source_protection_transitions AS t
        JOIN sources AS s ON s.source_id = t.source_id
        JOIN blob_records AS old_b ON old_b.blob_id = t.old_blob_id
        JOIN protection_scopes AS scope
          ON scope.protection_scope_id = t.protection_scope_id
        LEFT JOIN protected_sources AS ps ON ps.source_id = t.source_id
        LEFT JOIN blob_records AS target_b ON target_b.blob_id = t.target_blob_id
        LEFT JOIN protected_blob_envelopes AS e
          ON e.blob_id = t.target_blob_id
        LEFT JOIN protected_payloads AS p
          ON p.protected_payload_id = t.protected_metadata_payload_id
        WHERE
            ps.source_id IS NOT NULL
            OR old_b.encryption_state != 'none'
            OR scope.lifecycle_state != 'active'
            OR (
                t.state IN ('pending', 'prepared')
                AND (
                    s.blob_id != t.old_blob_id
                    OR s.original_name IS NULL
                    OR s.source_uri IS NULL
                    OR (
                        SELECT COUNT(*)
                        FROM sources AS refs
                        WHERE refs.blob_id = t.old_blob_id
                    ) != 1
                )
            )
            OR (
                t.state = 'sanitized'
                AND (
                    target_b.blob_id IS NULL
                    OR s.blob_id != t.target_blob_id
                    OR s.original_name IS NOT NULL
                    OR s.original_modified_at_us IS NOT NULL
                    OR s.source_uri IS NOT NULL
                    OR s.mime_type != 'application/octet-stream'
                    OR s.content_sha256 != target_b.integrity_sha256
                    OR (
                        SELECT COUNT(*)
                        FROM sources AS refs
                        WHERE refs.blob_id = t.old_blob_id
                    ) != 0
                )
            )
            OR (
                t.state IN ('prepared', 'sanitized')
                AND (
                    target_b.blob_id IS NULL
                    OR target_b.encryption_state != 'protected_v1'
                    OR e.blob_id IS NULL
                    OR e.protection_scope_id != t.protection_scope_id
                    OR p.protected_payload_id IS NULL
                    OR p.protection_scope_id != t.protection_scope_id
                )
            )
            OR (
                SELECT COUNT(*)
                FROM source_representations AS r
                WHERE r.source_id = t.source_id
                   OR r.blob_id = t.old_blob_id
            ) != 0
        """
    ).fetchone()
    if invalid_transition is None or int(invalid_transition[0]) != 0:
        raise DatabaseCompatibilityError(
            "A Source protection transition violates its durable safety invariants."
        )

    expected_triggers = {
        "trg_source_protection_transition_block_blob_reuse",
        "trg_source_protection_transition_block_source_update",
        "trg_source_protection_transition_block_source_delete",
        "trg_source_protection_transition_block_representation",
        "trg_source_protection_transition_block_old_blob_update",
        "trg_source_protection_transition_block_old_blob_delete",
    }
    actual_triggers = {
        str(row[0])
        for row in connection.execute(
            """
            SELECT name
            FROM sqlite_master
            WHERE type = 'trigger'
              AND name LIKE 'trg_source_protection_transition_%'
            """
        )
    }
    if actual_triggers != expected_triggers:
        raise DatabaseCompatibilityError(
            "ATHENA Source protection transition guards are incomplete."
        )

    invalid_active_scope = connection.execute(
        """
        SELECT COUNT(*)
        FROM protection_scopes AS s
        LEFT JOIN protection_scope_keys AS k
          ON k.scope_key_id = s.current_scope_key_id
         AND k.protection_scope_id = s.protection_scope_id
        WHERE s.lifecycle_state = 'active'
          AND (
              s.current_scope_key_id IS NULL
              OR k.scope_key_id IS NULL
          )
        """
    ).fetchone()
    if invalid_active_scope is None or int(invalid_active_scope[0]) != 0:
        raise DatabaseCompatibilityError(
            "An active ProtectionScope has no valid current Scope Key."
        )

    if connection.execute("PRAGMA foreign_key_check").fetchall():
        raise DatabaseCompatibilityError(
            "ATHENA foreign-key verification failed."
        )


def _verify_schema_v33(
    connection: sqlite3.Connection,
) -> None:
    application_id = int(
        connection.execute("PRAGMA application_id").fetchone()[0]
    )
    user_version = int(
        connection.execute("PRAGMA user_version").fetchone()[0]
    )
    if (
        application_id != ATHENA_APPLICATION_ID
        or user_version != PROTECTED_SOURCE_BLOB_SCHEMA_VERSION
    ):
        raise DatabaseCompatibilityError(
            "ATHENA Protected Source/Blob schema version verification failed."
        )

    metadata = connection.execute(
        "SELECT schema_version, "
        "storage_layout_version, "
        "blob_format_version, "
        "last_migration_id, "
        "minimum_reader_version "
        "FROM schema_metadata "
        "WHERE singleton_id = 1"
    ).fetchone()
    expected = (
        PROTECTED_SOURCE_BLOB_SCHEMA_VERSION,
        STORAGE_LAYOUT_VERSION,
        BLOB_FORMAT_VERSION,
        PROTECTED_SOURCE_BLOB_MIGRATION_ID,
        PROTECTED_SOURCE_BLOB_SCHEMA_VERSION,
    )
    if metadata is None or tuple(metadata) != expected:
        raise DatabaseCompatibilityError(
            "ATHENA Protected Source/Blob schema metadata verification failed."
        )

    _verify_schema_v31_compatible(connection)
    required_tables = {
        "key_slots",
        "protection_scopes",
        "protection_scope_keys",
        "protected_payloads",
        "protected_blob_envelopes",
        "protected_sources",
    }
    missing = required_tables.difference(_user_tables(connection))
    if missing:
        raise DatabaseCompatibilityError(
            "ATHENA Protected Source/Blob schema is incomplete: "
            + ", ".join(sorted(missing))
            + "."
        )

    protected_source_columns = {
        str(row[1])
        for row in connection.execute("PRAGMA table_info(protected_sources)")
    }
    if not {
        "source_id",
        "protection_scope_id",
        "protected_metadata_payload_id",
        "created_at_us",
    }.issubset(protected_source_columns):
        raise DatabaseCompatibilityError(
            "ATHENA protected_sources schema is incomplete."
        )

    blob_sql_row = connection.execute(
        """
        SELECT sql
        FROM sqlite_master
        WHERE type = 'table'
          AND name = 'blob_records'
        """
    ).fetchone()
    if blob_sql_row is None or "protected_v1" not in str(blob_sql_row[0]):
        raise DatabaseCompatibilityError(
            "ATHENA BlobRecord schema does not allow Protected Blobs."
        )

    missing_envelope = connection.execute(
        """
        SELECT COUNT(*)
        FROM blob_records AS b
        LEFT JOIN protected_blob_envelopes AS e
          ON e.blob_id = b.blob_id
        WHERE b.encryption_state = 'protected_v1'
          AND e.blob_id IS NULL
        """
    ).fetchone()
    if missing_envelope is None or int(missing_envelope[0]) != 0:
        raise DatabaseCompatibilityError(
            "A Protected Blob is missing its encrypted envelope."
        )

    invalid_source = connection.execute(
        """
        SELECT COUNT(*)
        FROM protected_sources AS ps
        JOIN sources AS s ON s.source_id = ps.source_id
        JOIN blob_records AS b ON b.blob_id = s.blob_id
        JOIN protected_blob_envelopes AS e ON e.blob_id = b.blob_id
        JOIN protected_payloads AS p
          ON p.protected_payload_id = ps.protected_metadata_payload_id
        JOIN entity_registry AS se ON se.entity_id = s.source_id
        JOIN entity_registry AS be ON be.entity_id = b.blob_id
        WHERE
            s.original_name IS NOT NULL
            OR s.original_modified_at_us IS NOT NULL
            OR s.source_uri IS NOT NULL
            OR s.mime_type != 'application/octet-stream'
            OR b.media_type != 'application/octet-stream'
            OR b.encryption_state != 'protected_v1'
            OR e.protection_scope_id != ps.protection_scope_id
            OR p.protection_scope_id != ps.protection_scope_id
            OR se.protection_scope_id != ps.protection_scope_id
            OR be.protection_scope_id != ps.protection_scope_id
        """
    ).fetchone()
    if invalid_source is None or int(invalid_source[0]) != 0:
        raise DatabaseCompatibilityError(
            "Protected Source public metadata or scope linkage is inconsistent."
        )

    invalid_active_scope = connection.execute(
        """
        SELECT COUNT(*)
        FROM protection_scopes AS s
        LEFT JOIN protection_scope_keys AS k
          ON k.scope_key_id = s.current_scope_key_id
         AND k.protection_scope_id = s.protection_scope_id
        WHERE s.lifecycle_state = 'active'
          AND (
              s.current_scope_key_id IS NULL
              OR k.scope_key_id IS NULL
          )
        """
    ).fetchone()
    if invalid_active_scope is None or int(invalid_active_scope[0]) != 0:
        raise DatabaseCompatibilityError(
            "An active ProtectionScope has no valid current Scope Key."
        )

    if connection.execute("PRAGMA foreign_key_check").fetchall():
        raise DatabaseCompatibilityError(
            "ATHENA foreign-key verification failed."
        )


def _verify_schema_v32(
    connection: sqlite3.Connection,
) -> None:
    application_id = int(
        connection.execute(
            "PRAGMA application_id"
        ).fetchone()[0]
    )

    user_version = int(
        connection.execute(
            "PRAGMA user_version"
        ).fetchone()[0]
    )

    if application_id != ATHENA_APPLICATION_ID:
        raise DatabaseCompatibilityError(
            "ATHENA application_id verification failed."
        )

    if (
        user_version
        != PROTECTED_CONTENT_SCHEMA_VERSION
    ):
        raise DatabaseCompatibilityError(
            "ATHENA schema version verification failed."
        )

    metadata = connection.execute(
        "SELECT schema_version, "
        "storage_layout_version, "
        "blob_format_version, "
        "last_migration_id, "
        "minimum_reader_version "
        "FROM schema_metadata "
        "WHERE singleton_id = 1"
    ).fetchone()

    expected = (
        PROTECTED_CONTENT_SCHEMA_VERSION,
        STORAGE_LAYOUT_VERSION,
        BLOB_FORMAT_VERSION,
        PROTECTED_CONTENT_MIGRATION_ID,
        PROTECTED_CONTENT_SCHEMA_VERSION,
    )

    if (
        metadata is None
        or tuple(metadata) != expected
    ):
        raise DatabaseCompatibilityError(
            "ATHENA schema_metadata verification failed."
        )

    _verify_schema_v31_compatible(
        connection
    )

    required_tables = {
        "key_slots",
        "protection_scopes",
        "protection_scope_keys",
        "protected_payloads",
        "protected_blob_envelopes",
    }

    missing_tables = (
        required_tables.difference(
            _user_tables(
                connection
            )
        )
    )

    if missing_tables:
        raise DatabaseCompatibilityError(
            "ATHENA Protected Content schema "
            "is incomplete: "
            + ", ".join(
                sorted(
                    missing_tables
                )
            )
            + "."
        )

    scope_columns = {
        str(row[1])
        for row in connection.execute(
            """
            PRAGMA table_info(
                protection_scopes
            )
            """
        )
    }

    required_scope_columns = {
        "protection_scope_id",
        "lifecycle_state",
        "created_at_us",
        "current_scope_key_id",
        "neutral_label",
    }

    if not (
        required_scope_columns
        .issubset(
            scope_columns
        )
    ):
        raise DatabaseCompatibilityError(
            "ATHENA ProtectionScope schema "
            "is incomplete."
        )

    if (
        {
            "locked",
            "unlocked",
            "is_unlocked",
        }
        & scope_columns
    ):
        raise DatabaseCompatibilityError(
            "ProtectionScope lock state "
            "must never be persisted."
        )

    slot_columns = {
        str(row[1])
        for row in connection.execute(
            "PRAGMA table_info(key_slots)"
        )
    }

    if not {
        "key_slot_id",
        "slot_type",
        "kdf_algorithm",
        "kdf_parameters_json",
        "salt",
        "wrap_algorithm",
        "wrap_nonce",
        "wrapped_root_key",
        "created_at_us",
        "retired_at_us",
        "status",
    }.issubset(
        slot_columns
    ):
        raise DatabaseCompatibilityError(
            "ATHENA key-slot schema is incomplete."
        )

    scope_key_columns = {
        str(row[1])
        for row in connection.execute(
            """
            PRAGMA table_info(
                protection_scope_keys
            )
            """
        )
    }

    if not {
        "scope_key_id",
        "protection_scope_id",
        "key_version",
        "wrap_algorithm",
        "wrap_nonce",
        "wrapped_scope_key",
        "created_at_us",
        "retired_at_us",
        "status",
    }.issubset(
        scope_key_columns
    ):
        raise DatabaseCompatibilityError(
            "ATHENA ProtectionScope-key "
            "schema is incomplete."
        )

    payload_columns = {
        str(row[1])
        for row in connection.execute(
            """
            PRAGMA table_info(
                protected_payloads
            )
            """
        )
    }

    if not {
        "protected_payload_id",
        "protection_scope_id",
        "scope_key_id",
        "cipher_suite",
        "ciphertext",
        "nonce",
        "wrapped_dek",
        "dek_wrap_nonce",
        "aad_version",
        "ciphertext_hash",
        "created_at_us",
    }.issubset(
        payload_columns
    ):
        raise DatabaseCompatibilityError(
            "ATHENA protected-payload "
            "schema is incomplete."
        )

    envelope_columns = {
        str(row[1])
        for row in connection.execute(
            """
            PRAGMA table_info(
                protected_blob_envelopes
            )
            """
        )
    }

    if not {
        "blob_id",
        "protection_scope_id",
        "scope_key_id",
        "wrapped_dek",
        "dek_wrap_nonce",
        "nonce_prefix",
        "chunk_size",
        "cipher_suite",
        "format_version",
    }.issubset(
        envelope_columns
    ):
        raise DatabaseCompatibilityError(
            "ATHENA protected-blob-envelope "
            "schema is incomplete."
        )

    password_index = (
        connection.execute(
            """
            SELECT name
            FROM sqlite_master
            WHERE type = 'index'
              AND name =
                  'uq_key_slots_active_password'
            """
        ).fetchone()
    )

    if password_index is None:
        raise DatabaseCompatibilityError(
            "ATHENA active-password-slot "
            "uniqueness index is missing."
        )

    invalid_active_scope = (
        connection.execute(
            """
            SELECT COUNT(*)
            FROM protection_scopes AS s
            LEFT JOIN protection_scope_keys AS k
              ON
                k.scope_key_id
                = s.current_scope_key_id
              AND
                k.protection_scope_id
                = s.protection_scope_id
            WHERE
                s.lifecycle_state = 'active'
                AND (
                    s.current_scope_key_id
                    IS NULL
                    OR
                    k.scope_key_id IS NULL
                )
            """
        ).fetchone()
    )

    if (
        invalid_active_scope is None
        or int(
            invalid_active_scope[0]
        )
        != 0
    ):
        raise DatabaseCompatibilityError(
            "An active ProtectionScope has "
            "no valid current Scope Key."
        )

    if connection.execute(
        "PRAGMA foreign_key_check"
    ).fetchall():
        raise DatabaseCompatibilityError(
            "ATHENA foreign-key verification failed."
        )


def _verify_schema_v31(
    connection: sqlite3.Connection,
) -> None:
    application_id = int(
        connection.execute(
            "PRAGMA application_id"
        ).fetchone()[0]
    )

    user_version = int(
        connection.execute(
            "PRAGMA user_version"
        ).fetchone()[0]
    )

    if application_id != ATHENA_APPLICATION_ID:
        raise DatabaseCompatibilityError(
            "ATHENA application_id verification failed."
        )

    if (
        user_version
        != ARCHIVE_REPLICATION_SCHEMA_VERSION
    ):
        raise DatabaseCompatibilityError(
            "ATHENA schema version verification failed."
        )

    metadata = connection.execute(
        "SELECT schema_version, "
        "storage_layout_version, "
        "blob_format_version, "
        "last_migration_id, "
        "minimum_reader_version "
        "FROM schema_metadata "
        "WHERE singleton_id = 1"
    ).fetchone()

    expected = (
        ARCHIVE_REPLICATION_SCHEMA_VERSION,
        STORAGE_LAYOUT_VERSION,
        BLOB_FORMAT_VERSION,
        ARCHIVE_REPLICATION_MIGRATION_ID,
        ARCHIVE_REPLICATION_SCHEMA_VERSION,
    )

    if (
        metadata is None
        or tuple(metadata) != expected
    ):
        raise DatabaseCompatibilityError(
            "ATHENA schema_metadata verification failed."
        )

    _verify_schema_v31_compatible(
        connection
    )


def _verify_schema_v31_compatible(
    connection: sqlite3.Connection,
) -> None:
    _verify_schema_v24_compatible(
        connection
    )

    required_tables = {
        "research_synthesis_output_source_evidence",
        "archive_replication_outbox",
        "archive_replication_watermark",
    }

    missing_tables = (
        required_tables.difference(
            _user_tables(
                connection
            )
        )
    )

    if missing_tables:
        raise DatabaseCompatibilityError(
            "ATHENA archive replication schema "
            "is incomplete: "
            + ", ".join(
                sorted(
                    missing_tables
                )
            )
            + "."
        )

    outbox_columns = {
        str(row[1])
        for row in connection.execute(
            """
            PRAGMA table_info(
                archive_replication_outbox
            )
            """
        )
    }

    required_outbox_columns = {
        "outbox_seq",
        "blob_id",
        "target_role",
        "state",
        "attempt_count",
        "created_at_us",
        "last_attempt_at_us",
        "last_error_code",
        "last_error_detail",
        "verified_at_us",
    }

    if not (
        required_outbox_columns
        .issubset(
            outbox_columns
        )
    ):
        raise DatabaseCompatibilityError(
            "ATHENA archive replication "
            "outbox is incomplete."
        )

    trigger = (
        connection.execute(
            """
            SELECT name
            FROM sqlite_master
            WHERE type = 'trigger'
              AND name =
                'trg_blob_records_archive_replication_outbox'
            """
        ).fetchone()
    )

    if trigger is None:
        raise DatabaseCompatibilityError(
            "ATHENA archive replication "
            "enqueue trigger is missing."
        )

    watermark = (
        connection.execute(
            """
            SELECT contiguous_verified_seq
            FROM archive_replication_watermark
            WHERE singleton_id = 1
            """
        ).fetchone()
    )

    if watermark is None:
        raise DatabaseCompatibilityError(
            "ATHENA archive replication "
            "watermark is missing."
        )

    invalid_state = (
        connection.execute(
            """
            SELECT COUNT(*)
            FROM archive_replication_outbox AS o
            JOIN blob_records AS b
              ON b.blob_id = o.blob_id
            WHERE
                (
                    o.state = 'pending'
                    AND
                    b.storage_area != 'spool'
                )
                OR
                (
                    o.state = 'verified'
                    AND
                    b.storage_area != 'archive'
                )
            """
        ).fetchone()
    )

    if (
        invalid_state is None
        or int(
            invalid_state[0]
        )
        != 0
    ):
        raise DatabaseCompatibilityError(
            "ATHENA archive replication state "
            "disagrees with BlobRecord "
            "storage state."
        )

    precise_columns = {
        str(row[1])
        for row in connection.execute(
            """
            PRAGMA table_info(
                research_synthesis_output_source_evidence
            )
            """
        )
    }

    if not {
        "artifact_id",
        "output_kind",
        "output_ordinal",
        "source_analysis_artifact_id",
    }.issubset(
        precise_columns
    ):
        raise DatabaseCompatibilityError(
            "ATHENA precise Research synthesis "
            "provenance is incomplete."
        )

    try:
        verify_news_schema_v30(
            connection
        )

    except RuntimeError as exc:
        raise DatabaseCompatibilityError(
            str(
                exc
            )
        ) from exc

    if connection.execute(
        "PRAGMA foreign_key_check"
    ).fetchall():
        raise DatabaseCompatibilityError(
            "ATHENA foreign-key verification failed."
        )


def _verify_schema_v30(
    connection: sqlite3.Connection,
) -> None:
    application_id = int(
        connection.execute(
            "PRAGMA application_id"
        ).fetchone()[0]
    )

    user_version = int(
        connection.execute(
            "PRAGMA user_version"
        ).fetchone()[0]
    )

    if application_id != ATHENA_APPLICATION_ID:
        raise DatabaseCompatibilityError(
            "ATHENA application_id verification failed."
        )

    if (
        user_version
        != NEWS_EVENT_ELIGIBILITY_SCHEMA_VERSION
    ):
        raise DatabaseCompatibilityError(
            "ATHENA schema version verification failed."
        )

    metadata = connection.execute(
        "SELECT schema_version, "
        "storage_layout_version, "
        "blob_format_version, "
        "last_migration_id, "
        "minimum_reader_version "
        "FROM schema_metadata "
        "WHERE singleton_id = 1"
    ).fetchone()

    expected = (
        NEWS_EVENT_ELIGIBILITY_SCHEMA_VERSION,
        STORAGE_LAYOUT_VERSION,
        BLOB_FORMAT_VERSION,
        NEWS_EVENT_ELIGIBILITY_MIGRATION_ID,
        NEWS_EVENT_ELIGIBILITY_SCHEMA_VERSION,
    )

    if (
        metadata is None
        or tuple(metadata) != expected
    ):
        raise DatabaseCompatibilityError(
            "ATHENA schema_metadata verification failed."
        )

    _verify_schema_v24_compatible(connection)

    if (
        "research_synthesis_output_source_evidence"
        not in _user_tables(connection)
    ):
        raise DatabaseCompatibilityError(
            "ATHENA precise Research synthesis "
            "provenance table is missing."
        )

    provenance_columns = {
        str(row[1])
        for row in connection.execute(
            "PRAGMA table_info("
            "research_synthesis_output_source_evidence"
            ")"
        )
    }

    required_provenance_columns = {
        "artifact_id",
        "output_kind",
        "output_ordinal",
        "source_analysis_artifact_id",
    }

    if not required_provenance_columns.issubset(
        provenance_columns
    ):
        raise DatabaseCompatibilityError(
            "ATHENA precise Research synthesis "
            "provenance is incomplete."
        )

    try:
        verify_news_schema_v30(connection)
    except RuntimeError as exc:
        raise DatabaseCompatibilityError(
            str(exc)
        ) from exc

    if connection.execute(
        "PRAGMA foreign_key_check"
    ).fetchall():
        raise DatabaseCompatibilityError(
            "ATHENA foreign-key verification failed."
        )


def _verify_schema_v29(connection: sqlite3.Connection) -> None:
    application_id = int(
        connection.execute("PRAGMA application_id").fetchone()[0]
    )
    user_version = int(
        connection.execute("PRAGMA user_version").fetchone()[0]
    )

    if application_id != ATHENA_APPLICATION_ID:
        raise DatabaseCompatibilityError(
            "ATHENA application_id verification failed."
        )

    if user_version != PRECISE_RESEARCH_PROVENANCE_SCHEMA_VERSION:
        raise DatabaseCompatibilityError(
            "ATHENA schema version verification failed."
        )

    metadata = connection.execute(
        "SELECT schema_version, storage_layout_version, "
        "blob_format_version, last_migration_id, "
        "minimum_reader_version "
        "FROM schema_metadata WHERE singleton_id = 1"
    ).fetchone()

    expected = (
        PRECISE_RESEARCH_PROVENANCE_SCHEMA_VERSION,
        STORAGE_LAYOUT_VERSION,
        BLOB_FORMAT_VERSION,
        PRECISE_RESEARCH_PROVENANCE_MIGRATION_ID,
        PRECISE_RESEARCH_PROVENANCE_SCHEMA_VERSION,
    )

    if metadata is None or tuple(metadata) != expected:
        raise DatabaseCompatibilityError(
            "ATHENA schema_metadata verification failed."
        )

    _verify_schema_v24_compatible(connection)

    if (
        "research_synthesis_output_source_evidence"
        not in _user_tables(connection)
    ):
        raise DatabaseCompatibilityError(
            "ATHENA precise Research synthesis provenance table is missing."
        )

    columns = {
        str(row[1])
        for row in connection.execute(
            "PRAGMA table_info("
            "research_synthesis_output_source_evidence"
            ")"
        )
    }

    required_columns = {
        "artifact_id",
        "output_kind",
        "output_ordinal",
        "source_analysis_artifact_id",
    }

    if not required_columns.issubset(columns):
        raise DatabaseCompatibilityError(
            "ATHENA precise Research synthesis provenance is incomplete."
        )

    try:
        verify_news_schema_v28(connection)
    except RuntimeError as exc:
        raise DatabaseCompatibilityError(str(exc)) from exc

    if connection.execute("PRAGMA foreign_key_check").fetchall():
        raise DatabaseCompatibilityError(
            "ATHENA foreign-key verification failed."
        )


def _verify_schema_v28(connection: sqlite3.Connection) -> None:
    application_id = int(connection.execute("PRAGMA application_id").fetchone()[0])
    user_version = int(connection.execute("PRAGMA user_version").fetchone()[0])
    if application_id != ATHENA_APPLICATION_ID:
        raise DatabaseCompatibilityError("ATHENA application_id verification failed.")
    if user_version != NEWS_OPERATIONAL_SCHEMA_VERSION:
        raise DatabaseCompatibilityError("ATHENA schema version verification failed.")
    metadata = connection.execute(
        "SELECT schema_version, storage_layout_version, blob_format_version, "
        "last_migration_id, minimum_reader_version FROM schema_metadata WHERE singleton_id = 1"
    ).fetchone()
    expected = (NEWS_OPERATIONAL_SCHEMA_VERSION, STORAGE_LAYOUT_VERSION, BLOB_FORMAT_VERSION,
                NEWS_OPERATIONAL_MIGRATION_ID, NEWS_OPERATIONAL_SCHEMA_VERSION)
    if metadata is None or tuple(metadata) != expected:
        raise DatabaseCompatibilityError("ATHENA schema_metadata verification failed.")
    _verify_schema_v24_compatible(connection)
    try:
        verify_news_schema_v28(connection)
    except RuntimeError as exc:
        raise DatabaseCompatibilityError(str(exc)) from exc
    if connection.execute("PRAGMA foreign_key_check").fetchall():
        raise DatabaseCompatibilityError("ATHENA foreign-key verification failed.")


def _verify_schema_v27(connection: sqlite3.Connection) -> None:
    application_id = int(connection.execute("PRAGMA application_id").fetchone()[0])
    user_version = int(connection.execute("PRAGMA user_version").fetchone()[0])
    if application_id != ATHENA_APPLICATION_ID:
        raise DatabaseCompatibilityError("ATHENA application_id verification failed.")
    if user_version != NEWS_EVENT_STRUCTURE_SCHEMA_VERSION:
        raise DatabaseCompatibilityError("ATHENA schema version verification failed.")

    metadata = connection.execute(
        "SELECT schema_version, storage_layout_version, blob_format_version, "
        "last_migration_id, minimum_reader_version "
        "FROM schema_metadata WHERE singleton_id = 1"
    ).fetchone()
    expected = (
        NEWS_EVENT_STRUCTURE_SCHEMA_VERSION,
        STORAGE_LAYOUT_VERSION,
        BLOB_FORMAT_VERSION,
        NEWS_EVENT_STRUCTURE_MIGRATION_ID,
        NEWS_EVENT_STRUCTURE_SCHEMA_VERSION,
    )
    if metadata is None or tuple(metadata) != expected:
        raise DatabaseCompatibilityError("ATHENA schema_metadata verification failed.")

    required_operational_tables = {
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
    }
    missing_tables = required_operational_tables.difference(_user_tables(connection))
    if missing_tables:
        missing = ", ".join(sorted(missing_tables))
        raise DatabaseCompatibilityError(
            f"ATHENA consolidated operational schema is incomplete: {missing}."
        )
    _verify_schema_v24_compatible(connection)
    try:
        verify_news_schema_v27(connection)
    except RuntimeError as exc:
        raise DatabaseCompatibilityError(str(exc)) from exc
    if connection.execute("PRAGMA foreign_key_check").fetchall():
        raise DatabaseCompatibilityError("ATHENA foreign-key verification failed.")


def _verify_schema_v26(connection: sqlite3.Connection) -> None:
    application_id = int(connection.execute("PRAGMA application_id").fetchone()[0])
    user_version = int(connection.execute("PRAGMA user_version").fetchone()[0])
    if application_id != ATHENA_APPLICATION_ID:
        raise DatabaseCompatibilityError("ATHENA application_id verification failed.")
    if user_version != NEWS_SYSTEM_SCHEMA_VERSION:
        raise DatabaseCompatibilityError("ATHENA schema version verification failed.")

    metadata = connection.execute(
        "SELECT schema_version, storage_layout_version, blob_format_version, "
        "last_migration_id, minimum_reader_version "
        "FROM schema_metadata WHERE singleton_id = 1"
    ).fetchone()
    expected = (
        NEWS_SYSTEM_SCHEMA_VERSION,
        STORAGE_LAYOUT_VERSION,
        BLOB_FORMAT_VERSION,
        NEWS_SYSTEM_MIGRATION_ID,
        NEWS_SYSTEM_SCHEMA_VERSION,
    )
    if metadata is None or tuple(metadata) != expected:
        raise DatabaseCompatibilityError("ATHENA schema_metadata verification failed.")

    required_operational_tables = {
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
    }
    missing_tables = required_operational_tables.difference(_user_tables(connection))
    if missing_tables:
        missing = ", ".join(sorted(missing_tables))
        raise DatabaseCompatibilityError(
            f"ATHENA consolidated operational schema is incomplete: {missing}."
        )
    _verify_schema_v24_compatible(connection)
    try:
        verify_news_schema_v26(connection)
    except RuntimeError as exc:
        raise DatabaseCompatibilityError(str(exc)) from exc
    if connection.execute("PRAGMA foreign_key_check").fetchall():
        raise DatabaseCompatibilityError("ATHENA foreign-key verification failed.")


def _verify_schema_v25(connection: sqlite3.Connection) -> None:
    application_id = int(connection.execute("PRAGMA application_id").fetchone()[0])
    user_version = int(connection.execute("PRAGMA user_version").fetchone()[0])
    if application_id != ATHENA_APPLICATION_ID:
        raise DatabaseCompatibilityError("ATHENA application_id verification failed.")
    if user_version != CONSOLIDATED_OPERATIONS_SCHEMA_VERSION:
        raise DatabaseCompatibilityError("ATHENA schema version verification failed.")

    metadata = connection.execute(
        "SELECT schema_version, storage_layout_version, blob_format_version, "
        "last_migration_id, minimum_reader_version "
        "FROM schema_metadata WHERE singleton_id = 1"
    ).fetchone()
    expected = (
        CONSOLIDATED_OPERATIONS_SCHEMA_VERSION,
        STORAGE_LAYOUT_VERSION,
        BLOB_FORMAT_VERSION,
        CONSOLIDATED_OPERATIONS_MIGRATION_ID,
        CONSOLIDATED_OPERATIONS_SCHEMA_VERSION,
    )
    if metadata is None or tuple(metadata) != expected:
        raise DatabaseCompatibilityError("ATHENA schema_metadata verification failed.")

    required_tables = {
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
    }
    missing_tables = required_tables.difference(_user_tables(connection))
    if missing_tables:
        missing = ", ".join(sorted(missing_tables))
        raise DatabaseCompatibilityError(
            f"ATHENA consolidated operational schema is incomplete: {missing}."
        )
    _verify_schema_v24_compatible(connection)
    if connection.execute("PRAGMA foreign_key_check").fetchall():
        raise DatabaseCompatibilityError("ATHENA foreign-key verification failed.")


def _verify_schema_v24_compatible(connection: sqlite3.Connection) -> None:
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
        "source_analysis_knowledge_origins", "source_extractions",
        "source_extraction_evidence", "source_extraction_work_items",
        "source_extraction_artifacts", "source_extraction_work_inputs",
        "personal_memory_entries", "personal_memory_revisions",
        "research_scopes", "research_candidate_sets", "research_candidates",
        "research_work_items", "research_synthesis_work_items",
        "research_synthesis_work_inputs", "research_synthesis_artifacts",
        "research_synthesis_output_evidence", "research_results",
    }
    missing_tables = required_tables.difference(_user_tables(connection))
    if missing_tables:
        missing = ", ".join(sorted(missing_tables))
        raise DatabaseCompatibilityError(
            f"ATHENA v24 semantic foundation is incomplete: {missing}."
        )


def _verify_schema_v24(connection: sqlite3.Connection) -> None:
    application_id = int(connection.execute("PRAGMA application_id").fetchone()[0])
    user_version = int(connection.execute("PRAGMA user_version").fetchone()[0])
    if application_id != ATHENA_APPLICATION_ID:
        raise DatabaseCompatibilityError("ATHENA application_id verification failed.")
    if user_version != RESEARCH_SYNTHESIS_SCHEMA_VERSION:
        raise DatabaseCompatibilityError("ATHENA schema version verification failed.")

    metadata = connection.execute(
        "SELECT schema_version, storage_layout_version, blob_format_version, "
        "last_migration_id, minimum_reader_version "
        "FROM schema_metadata WHERE singleton_id = 1"
    ).fetchone()
    expected = (
        RESEARCH_SYNTHESIS_SCHEMA_VERSION,
        STORAGE_LAYOUT_VERSION,
        BLOB_FORMAT_VERSION,
        RESEARCH_SYNTHESIS_MIGRATION_ID,
        RESEARCH_SYNTHESIS_SCHEMA_VERSION,
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
        "source_analysis_knowledge_origins", "source_extractions",
        "source_extraction_evidence", "source_extraction_work_items",
        "source_extraction_artifacts", "source_extraction_work_inputs",
        "personal_memory_entries", "personal_memory_revisions",
        "research_scopes", "research_candidate_sets", "research_candidates",
        "research_work_items", "research_synthesis_work_items",
        "research_synthesis_work_inputs", "research_synthesis_artifacts",
        "research_synthesis_output_evidence", "research_results",
    }
    missing_tables = required_tables.difference(_user_tables(connection))
    if missing_tables:
        missing = ", ".join(sorted(missing_tables))
        raise DatabaseCompatibilityError(
            f"ATHENA semantic schema is incomplete: {missing}."
        )

    synthesis_input_columns = {
        str(row[1])
        for row in connection.execute(
            "PRAGMA table_info(research_synthesis_work_inputs)"
        )
    }
    if not {
        "input_kind",
        "source_analysis_artifact_id",
        "research_synthesis_artifact_id",
    }.issubset(synthesis_input_columns):
        raise DatabaseCompatibilityError(
            "ATHENA Research synthesis input provenance is incomplete."
        )

    result_columns = {
        str(row[1])
        for row in connection.execute("PRAGMA table_info(research_results)")
    }
    if not {
        "final_artifact_id",
        "content_json",
        "content_hash",
        "snapshot_commit_seq",
        "model_signature_id",
        "synthesis_pipeline_version",
        "candidate_total",
        "processed_count",
        "successful_count",
        "irrelevant_count",
        "failed_count",
        "unavailable_count",
        "excluded_count",
        "coverage_ratio",
        "problem_sources_json",
    }.issubset(result_columns):
        raise DatabaseCompatibilityError(
            "ATHENA ResearchResult persistence is incomplete."
        )

    if connection.execute("PRAGMA foreign_key_check").fetchall():
        raise DatabaseCompatibilityError("ATHENA foreign-key verification failed.")


def _verify_schema_v23(connection: sqlite3.Connection) -> None:
    application_id = int(connection.execute("PRAGMA application_id").fetchone()[0])
    user_version = int(connection.execute("PRAGMA user_version").fetchone()[0])
    if application_id != ATHENA_APPLICATION_ID:
        raise DatabaseCompatibilityError("ATHENA application_id verification failed.")
    if user_version != RESEARCH_ORCHESTRATION_SCHEMA_VERSION:
        raise DatabaseCompatibilityError("ATHENA schema version verification failed.")

    metadata = connection.execute(
        "SELECT schema_version, storage_layout_version, blob_format_version, "
        "last_migration_id, minimum_reader_version "
        "FROM schema_metadata WHERE singleton_id = 1"
    ).fetchone()
    expected = (
        RESEARCH_ORCHESTRATION_SCHEMA_VERSION,
        STORAGE_LAYOUT_VERSION,
        BLOB_FORMAT_VERSION,
        RESEARCH_ORCHESTRATION_MIGRATION_ID,
        RESEARCH_ORCHESTRATION_SCHEMA_VERSION,
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
        "source_analysis_knowledge_origins", "source_extractions",
        "source_extraction_evidence", "source_extraction_work_items",
        "source_extraction_artifacts", "source_extraction_work_inputs",
        "personal_memory_entries", "personal_memory_revisions",
        "research_scopes", "research_candidate_sets", "research_candidates",
        "research_work_items",
    }
    missing_tables = required_tables.difference(_user_tables(connection))
    if missing_tables:
        missing = ", ".join(sorted(missing_tables))
        raise DatabaseCompatibilityError(
            f"ATHENA semantic schema is incomplete: {missing}."
        )

    scope_columns = {
        str(row[1])
        for row in connection.execute("PRAGMA table_info(research_scopes)")
    }
    if not {
        "model_id",
        "model_signature_id",
        "model_signature_sha256",
        "effective_context_limit",
        "output_reserve",
        "safety_margin",
        "token_estimator",
        "max_hierarchy_depth",
    }.issubset(scope_columns):
        raise DatabaseCompatibilityError(
            "ATHENA research_scopes orchestration columns are incomplete."
        )

    work_columns = {
        str(row[1])
        for row in connection.execute("PRAGMA table_info(research_work_items)")
    }
    if "source_processing_job_id" not in work_columns:
        raise DatabaseCompatibilityError(
            "ATHENA research_work_items child orchestration is incomplete."
        )
    if connection.execute("PRAGMA foreign_key_check").fetchall():
        raise DatabaseCompatibilityError("ATHENA foreign-key verification failed.")


def _verify_schema_v22(connection: sqlite3.Connection) -> None:
    application_id = int(connection.execute("PRAGMA application_id").fetchone()[0])
    user_version = int(connection.execute("PRAGMA user_version").fetchone()[0])
    if application_id != ATHENA_APPLICATION_ID:
        raise DatabaseCompatibilityError("ATHENA application_id verification failed.")
    if user_version != EXHAUSTIVE_RESEARCH_SCHEMA_VERSION:
        raise DatabaseCompatibilityError("ATHENA schema version verification failed.")

    metadata = connection.execute(
        "SELECT schema_version, storage_layout_version, blob_format_version, "
        "last_migration_id, minimum_reader_version "
        "FROM schema_metadata WHERE singleton_id = 1"
    ).fetchone()
    expected = (
        EXHAUSTIVE_RESEARCH_SCHEMA_VERSION,
        STORAGE_LAYOUT_VERSION,
        BLOB_FORMAT_VERSION,
        EXHAUSTIVE_RESEARCH_MIGRATION_ID,
        EXHAUSTIVE_RESEARCH_SCHEMA_VERSION,
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
        "source_analysis_knowledge_origins", "source_extractions",
        "source_extraction_evidence", "source_extraction_work_items",
        "source_extraction_artifacts", "source_extraction_work_inputs",
        "personal_memory_entries", "personal_memory_revisions",
        "research_scopes", "research_candidate_sets", "research_candidates",
        "research_work_items",
    }
    missing_tables = required_tables.difference(_user_tables(connection))
    if missing_tables:
        missing = ", ".join(sorted(missing_tables))
        raise DatabaseCompatibilityError(
            f"ATHENA semantic schema is incomplete: {missing}."
        )
    if connection.execute("PRAGMA foreign_key_check").fetchall():
        raise DatabaseCompatibilityError("ATHENA foreign-key verification failed.")


def _verify_schema_v21(connection: sqlite3.Connection) -> None:
    application_id = int(connection.execute("PRAGMA application_id").fetchone()[0])
    user_version = int(connection.execute("PRAGMA user_version").fetchone()[0])
    if application_id != ATHENA_APPLICATION_ID:
        raise DatabaseCompatibilityError("ATHENA application_id verification failed.")
    if user_version != PERSONAL_MEMORY_SCHEMA_VERSION:
        raise DatabaseCompatibilityError("ATHENA schema version verification failed.")

    metadata = connection.execute(
        "SELECT schema_version, storage_layout_version, blob_format_version, "
        "last_migration_id, minimum_reader_version "
        "FROM schema_metadata WHERE singleton_id = 1"
    ).fetchone()
    expected = (
        PERSONAL_MEMORY_SCHEMA_VERSION,
        STORAGE_LAYOUT_VERSION,
        BLOB_FORMAT_VERSION,
        PERSONAL_MEMORY_MIGRATION_ID,
        PERSONAL_MEMORY_SCHEMA_VERSION,
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
        "source_analysis_knowledge_origins", "source_extractions",
        "source_extraction_evidence", "source_extraction_work_items",
        "source_extraction_artifacts", "source_extraction_work_inputs",
        "personal_memory_entries", "personal_memory_revisions",
    }
    missing_tables = required_tables.difference(_user_tables(connection))
    if missing_tables:
        missing = ", ".join(sorted(missing_tables))
        raise DatabaseCompatibilityError(f"ATHENA semantic schema is incomplete: {missing}.")
    if connection.execute("PRAGMA foreign_key_check").fetchall():
        raise DatabaseCompatibilityError("ATHENA foreign-key verification failed.")


def _verify_schema_v20(connection: sqlite3.Connection) -> None:
    application_id = int(connection.execute("PRAGMA application_id").fetchone()[0])
    user_version = int(connection.execute("PRAGMA user_version").fetchone()[0])
    if application_id != ATHENA_APPLICATION_ID:
        raise DatabaseCompatibilityError("ATHENA application_id verification failed.")
    if user_version != HIERARCHICAL_SOURCE_EXTRACTION_SCHEMA_VERSION:
        raise DatabaseCompatibilityError("ATHENA schema version verification failed.")

    metadata = connection.execute(
        "SELECT schema_version, storage_layout_version, blob_format_version, "
        "last_migration_id, minimum_reader_version "
        "FROM schema_metadata WHERE singleton_id = 1"
    ).fetchone()
    expected = (
        HIERARCHICAL_SOURCE_EXTRACTION_SCHEMA_VERSION,
        STORAGE_LAYOUT_VERSION,
        BLOB_FORMAT_VERSION,
        HIERARCHICAL_SOURCE_EXTRACTION_MIGRATION_ID,
        HIERARCHICAL_SOURCE_EXTRACTION_SCHEMA_VERSION,
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
        "source_analysis_knowledge_origins", "source_extractions",
        "source_extraction_evidence", "source_extraction_work_items",
        "source_extraction_artifacts", "source_extraction_work_inputs",
    }
    missing_tables = required_tables.difference(_user_tables(connection))
    if missing_tables:
        missing = ", ".join(sorted(missing_tables))
        raise DatabaseCompatibilityError(f"ATHENA semantic schema is incomplete: {missing}.")
    if connection.execute("PRAGMA foreign_key_check").fetchall():
        raise DatabaseCompatibilityError("ATHENA foreign-key verification failed.")


def _verify_schema_v19(connection: sqlite3.Connection) -> None:
    application_id = int(connection.execute("PRAGMA application_id").fetchone()[0])
    user_version = int(connection.execute("PRAGMA user_version").fetchone()[0])
    if application_id != ATHENA_APPLICATION_ID:
        raise DatabaseCompatibilityError("ATHENA application_id verification failed.")
    if user_version != SOURCE_KNOWLEDGE_SCHEMA_VERSION:
        raise DatabaseCompatibilityError("ATHENA schema version verification failed.")

    metadata = connection.execute(
        "SELECT schema_version, storage_layout_version, blob_format_version, "
        "last_migration_id, minimum_reader_version "
        "FROM schema_metadata WHERE singleton_id = 1"
    ).fetchone()
    expected = (
        SOURCE_KNOWLEDGE_SCHEMA_VERSION,
        STORAGE_LAYOUT_VERSION,
        BLOB_FORMAT_VERSION,
        SOURCE_KNOWLEDGE_MIGRATION_ID,
        SOURCE_KNOWLEDGE_SCHEMA_VERSION,
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


# Preserve historical private verifier import/pickle identities.
_verify_schema_v15.__module__ = "athena.storage.schema"
_verify_schema_v16.__module__ = "athena.storage.schema"
_verify_schema_v17.__module__ = "athena.storage.schema"
_verify_schema_v18.__module__ = "athena.storage.schema"
_verify_schema_v19.__module__ = "athena.storage.schema"
_verify_schema_v20.__module__ = "athena.storage.schema"
_verify_schema_v21.__module__ = "athena.storage.schema"
_verify_schema_v22.__module__ = "athena.storage.schema"
_verify_schema_v23.__module__ = "athena.storage.schema"
_verify_schema_v24.__module__ = "athena.storage.schema"
_verify_schema_v24_compatible.__module__ = "athena.storage.schema"
_verify_schema_v25.__module__ = "athena.storage.schema"
_verify_schema_v26.__module__ = "athena.storage.schema"
_verify_schema_v27.__module__ = "athena.storage.schema"
_verify_schema_v28.__module__ = "athena.storage.schema"
_verify_schema_v29.__module__ = "athena.storage.schema"
_verify_schema_v30.__module__ = "athena.storage.schema"
_verify_schema_v31.__module__ = "athena.storage.schema"
_verify_schema_v31_compatible.__module__ = "athena.storage.schema"
_verify_schema_v32.__module__ = "athena.storage.schema"
_verify_schema_v33.__module__ = "athena.storage.schema"
_verify_schema_v34.__module__ = "athena.storage.schema"
_verify_schema_v35.__module__ = "athena.storage.schema"
_verify_schema_v36.__module__ = "athena.storage.schema"
_verify_schema_v37.__module__ = "athena.storage.schema"
_verify_schema_v38.__module__ = "athena.storage.schema"
_verify_schema_v39.__module__ = "athena.storage.schema"


def _verify_schema_v40(
    connection: sqlite3.Connection,
) -> None:
    """Verify durable Grounded-response receipt persistence."""
    _verify_schema_v39(
        connection,
        schema_version=(
            GROUNDED_RESPONSE_RECEIPT_SCHEMA_VERSION
        ),
        migration_id=(
            GROUNDED_RESPONSE_RECEIPT_MIGRATION_ID
        ),
    )

    tables = set(
        _user_tables(
            connection
        )
    )

    if "grounded_response_receipts" not in tables:
        raise DatabaseCompatibilityError(
            "ATHENA Grounded response receipt schema is missing."
        )

    columns = {
        str(row[1])
        for row in connection.execute(
            """
            PRAGMA table_info(
                grounded_response_receipts
            )
            """
        )
    }

    expected_columns = {
        "operation_id",
        "chat_id",
        "processing_run_id",
        "payload_json",
        "payload_sha256",
        "format_version",
        "created_at_us",
    }

    if not expected_columns.issubset(
        columns
    ):
        raise DatabaseCompatibilityError(
            "ATHENA Grounded response receipt columns are incomplete."
        )

    indexes = {
        str(row[0])
        for row in connection.execute(
            """
            SELECT name
            FROM sqlite_master
            WHERE type = 'index'
              AND name = 'idx_grounded_response_receipts_chat'
            """
        )
    }

    if indexes != {
        "idx_grounded_response_receipts_chat"
    }:
        raise DatabaseCompatibilityError(
            "ATHENA Grounded response receipt index is missing."
        )

    foreign_keys = {
        (
            str(row[3]),
            str(row[2]),
            str(row[4]),
            str(row[6]).upper(),
        )
        for row in connection.execute(
            """
            PRAGMA foreign_key_list(
                grounded_response_receipts
            )
            """
        )
    }

    if (
        "chat_id",
        "chats",
        "chat_id",
        "CASCADE",
    ) not in foreign_keys:
        raise DatabaseCompatibilityError(
            "ATHENA Grounded response receipt chat foreign key is missing."
        )

    invalid = connection.execute(
        """
        SELECT COUNT(*)
        FROM grounded_response_receipts
        WHERE length(operation_id) != 16
           OR length(chat_id) != 16
           OR length(processing_run_id) != 16
           OR length(payload_json) <= 1
           OR length(payload_sha256) != 64
           OR format_version != 1
           OR created_at_us < 0
        """
    ).fetchone()

    if (
        invalid is None
        or int(invalid[0]) != 0
    ):
        raise DatabaseCompatibilityError(
            "ATHENA Grounded response receipt rows are invalid."
        )

    if connection.execute(
        "PRAGMA foreign_key_check"
    ).fetchall():
        raise DatabaseCompatibilityError(
            "ATHENA foreign-key verification failed."
        )


_verify_schema_v40.__module__ = "athena.storage.schema"
