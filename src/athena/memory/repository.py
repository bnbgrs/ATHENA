"""Transactional persistence for canonical ATHENA Personal Memory."""

from __future__ import annotations

import hashlib
import json
import sqlite3
import uuid

from athena.common.ids import new_uuid7, uuid_from_blob, uuid_to_blob
from athena.common.time import utc_now_us
from athena.lifecycle.deletion import (
    PERSONAL_MEMORY_ENTITY_TYPE,
    record_deletion,
)
from athena.memory.models import (
    MemoryKind,
    MemoryLearningMode,
    MemoryScopeKind,
    MemorySensitivity,
    PersonalMemoryDraft,
    PersonalMemoryResetResult,
    PersonalMemoryRevision,
    PersonalMemorySnapshot,
)
from athena.storage.database import SQLiteDatabase


class PersonalMemoryNotFoundError(LookupError):
    """Raised when a requested Personal-Memory entry does not exist."""


class PersonalMemoryConflictError(RuntimeError):
    """Raised when a write is based on a stale Personal-Memory revision."""


class PersonalMemoryActorError(LookupError):
    """Raised when the requested write actor does not exist or is inactive."""


class PersonalMemoryProtectionError(ValueError):
    """Raised when protected memory would otherwise be persisted as plaintext."""


class PersonalMemoryLifecycleError(ValueError):
    """Raised for unsupported or invalid lifecycle transitions."""


class PersonalMemoryRepository:
    """Versioned Personal-Memory repository with explicit user provenance."""

    def __init__(self, database: SQLiteDatabase) -> None:
        self.database = database

    def create(
        self,
        *,
        actor_id: uuid.UUID,
        draft: PersonalMemoryDraft,
        reason: str | None = None,
    ) -> PersonalMemoryRevision:
        self._require_unprotected_payload(draft)
        memory_id = new_uuid7()
        revision_id = new_uuid7()
        provenance_id = new_uuid7()
        commit_id = new_uuid7()
        created_at_us = utc_now_us()
        payload_hash = _memory_payload_hash(draft)

        with self.database.write_transaction() as connection:
            self._require_user_actor(connection, actor_id)
            commit_seq = self._insert_commit(
                connection,
                commit_id=commit_id,
                actor_id=actor_id,
                operation_type="personal_memory.create",
                committed_at_us=created_at_us,
                reason=reason,
            )
            self._insert_entity(
                connection,
                memory_id=memory_id,
                actor_id=actor_id,
                created_at_us=created_at_us,
                commit_seq=commit_seq,
                reason=reason,
            )
            self._insert_provenance(
                connection,
                provenance_id=provenance_id,
                memory_id=memory_id,
                revision_id=revision_id,
                operation="personal_memory.create",
                actor_id=actor_id,
                created_at_us=created_at_us,
                reason=reason,
            )
            self._insert_revision(
                connection,
                memory_id=memory_id,
                revision_id=revision_id,
                revision_no=1,
                parent_revision_id=None,
                actor_id=actor_id,
                provenance_id=provenance_id,
                commit_id=commit_id,
                created_at_us=created_at_us,
                payload_hash=payload_hash,
                change_kind="create",
            )
            connection.execute(
                """
                INSERT INTO entity_heads (
                    entity_id, current_revision_id, current_revision_no
                ) VALUES (?, ?, 1)
                """,
                (uuid_to_blob(memory_id), uuid_to_blob(revision_id)),
            )
            connection.execute(
                "INSERT INTO personal_memory_entries (memory_id) VALUES (?)",
                (uuid_to_blob(memory_id),),
            )
            self._insert_payload(connection, revision_id=revision_id, draft=draft)
            self._insert_commit_change(
                connection,
                commit_seq=commit_seq,
                memory_id=memory_id,
                revision_id=revision_id,
                change_type="create",
            )

        return PersonalMemoryRevision(
            memory_id=memory_id,
            revision_id=revision_id,
            revision_no=1,
            created_at_us=created_at_us,
            created_by_actor_id=actor_id,
            provenance_id=provenance_id,
            payload=draft,
        )

    def revise(
        self,
        *,
        actor_id: uuid.UUID,
        memory_id: uuid.UUID,
        expected_revision_id: uuid.UUID,
        draft: PersonalMemoryDraft,
        reason: str | None = None,
        operation: str = "personal_memory.revise",
        change_kind: str = "revise",
    ) -> PersonalMemoryRevision:
        self._require_unprotected_payload(draft)
        revision_id = new_uuid7()
        provenance_id = new_uuid7()
        commit_id = new_uuid7()
        created_at_us = utc_now_us()
        payload_hash = _memory_payload_hash(draft)

        with self.database.write_transaction() as connection:
            self._require_user_actor(connection, actor_id)
            current_revision_id, current_revision_no, lifecycle_state = self._require_current_head(
                connection,
                memory_id=memory_id,
            )
            if lifecycle_state == "deleted":
                raise PersonalMemoryNotFoundError(str(memory_id))
            if current_revision_id != expected_revision_id:
                raise PersonalMemoryConflictError(
                    "Personal Memory changed since it was loaded; refusing a lost update."
                )

            next_revision_no = current_revision_no + 1
            commit_seq = self._insert_commit(
                connection,
                commit_id=commit_id,
                actor_id=actor_id,
                operation_type=operation,
                committed_at_us=created_at_us,
                reason=reason,
            )
            self._insert_provenance(
                connection,
                provenance_id=provenance_id,
                memory_id=memory_id,
                revision_id=revision_id,
                operation=operation,
                actor_id=actor_id,
                created_at_us=created_at_us,
                reason=reason,
            )
            self._insert_revision(
                connection,
                memory_id=memory_id,
                revision_id=revision_id,
                revision_no=next_revision_no,
                parent_revision_id=current_revision_id,
                actor_id=actor_id,
                provenance_id=provenance_id,
                commit_id=commit_id,
                created_at_us=created_at_us,
                payload_hash=payload_hash,
                change_kind=change_kind,
            )
            self._insert_payload(connection, revision_id=revision_id, draft=draft)
            updated = connection.execute(
                """
                UPDATE entity_heads
                SET current_revision_id = ?, current_revision_no = ?
                WHERE entity_id = ? AND current_revision_id = ?
                """,
                (
                    uuid_to_blob(revision_id),
                    next_revision_no,
                    uuid_to_blob(memory_id),
                    uuid_to_blob(expected_revision_id),
                ),
            )
            if updated.rowcount != 1:
                raise PersonalMemoryConflictError(
                    "Personal Memory head changed during update; refusing a lost update."
                )
            self._insert_commit_change(
                connection,
                commit_seq=commit_seq,
                memory_id=memory_id,
                revision_id=revision_id,
                change_type=change_kind,
            )

        return PersonalMemoryRevision(
            memory_id=memory_id,
            revision_id=revision_id,
            revision_no=next_revision_no,
            created_at_us=created_at_us,
            created_by_actor_id=actor_id,
            provenance_id=provenance_id,
            payload=draft,
        )

    def load_current(
        self,
        memory_id: uuid.UUID,
        *,
        include_deleted: bool = False,
    ) -> PersonalMemorySnapshot:
        row = self.database.connection.execute(
            """
            SELECT
                e.lifecycle_state,
                r.revision_id,
                r.revision_no,
                r.created_at_us,
                r.created_by_actor_id,
                r.provenance_id,
                mr.memory_kind,
                mr.content,
                mr.scope_entity_id,
                mr.scope_kind,
                mr.learning_mode,
                mr.sensitivity,
                mr.confidence,
                mr.last_confirmed_at_us
            FROM personal_memory_entries AS m
            JOIN entity_registry AS e ON e.entity_id = m.memory_id
            JOIN entity_heads AS h ON h.entity_id = m.memory_id
            JOIN revisions AS r ON r.revision_id = h.current_revision_id
            JOIN personal_memory_revisions AS mr ON mr.revision_id = r.revision_id
            WHERE m.memory_id = ?
            """,
            (uuid_to_blob(memory_id),),
        ).fetchone()
        if row is None or (not include_deleted and str(row["lifecycle_state"]) == "deleted"):
            raise PersonalMemoryNotFoundError(str(memory_id))
        return PersonalMemorySnapshot(
            memory_id=memory_id,
            lifecycle_state=str(row["lifecycle_state"]),
            revision=self._revision_from_row(memory_id, row),
        )

    def list_current(
        self,
        *,
        limit: int = 50,
        include_inactive: bool = False,
    ) -> tuple[PersonalMemorySnapshot, ...]:
        if not 1 <= limit <= 500:
            raise ValueError("limit must be between 1 and 500.")
        state_sql = "e.lifecycle_state = 'active'"
        if include_inactive:
            state_sql = "e.lifecycle_state IN ('active', 'inactive')"
        rows = self.database.connection.execute(
            f"""
            SELECT
                m.memory_id,
                e.lifecycle_state,
                r.revision_id,
                r.revision_no,
                r.created_at_us,
                r.created_by_actor_id,
                r.provenance_id,
                mr.memory_kind,
                mr.content,
                mr.scope_entity_id,
                mr.scope_kind,
                mr.learning_mode,
                mr.sensitivity,
                mr.confidence,
                mr.last_confirmed_at_us
            FROM personal_memory_entries AS m
            JOIN entity_registry AS e ON e.entity_id = m.memory_id
            JOIN entity_heads AS h ON h.entity_id = m.memory_id
            JOIN revisions AS r ON r.revision_id = h.current_revision_id
            JOIN personal_memory_revisions AS mr ON mr.revision_id = r.revision_id
            WHERE {state_sql}
            ORDER BY r.created_at_us DESC, m.memory_id DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
        return tuple(
            PersonalMemorySnapshot(
                memory_id=uuid_from_blob(bytes(row["memory_id"])),
                lifecycle_state=str(row["lifecycle_state"]),
                revision=self._revision_from_row(
                    uuid_from_blob(bytes(row["memory_id"])), row
                ),
            )
            for row in rows
        )

    def list_revisions(self, memory_id: uuid.UUID) -> tuple[PersonalMemoryRevision, ...]:
        exists = self.database.connection.execute(
            "SELECT 1 FROM personal_memory_entries WHERE memory_id = ?",
            (uuid_to_blob(memory_id),),
        ).fetchone()
        if exists is None:
            raise PersonalMemoryNotFoundError(str(memory_id))
        rows = self.database.connection.execute(
            """
            SELECT
                r.revision_id,
                r.revision_no,
                r.created_at_us,
                r.created_by_actor_id,
                r.provenance_id,
                mr.memory_kind,
                mr.content,
                mr.scope_entity_id,
                mr.scope_kind,
                mr.learning_mode,
                mr.sensitivity,
                mr.confidence,
                mr.last_confirmed_at_us
            FROM revisions AS r
            JOIN personal_memory_revisions AS mr ON mr.revision_id = r.revision_id
            WHERE r.entity_id = ?
            ORDER BY r.revision_no ASC
            """,
            (uuid_to_blob(memory_id),),
        ).fetchall()
        return tuple(self._revision_from_row(memory_id, row) for row in rows)

    def set_lifecycle_state(
        self,
        *,
        actor_id: uuid.UUID,
        memory_id: uuid.UUID,
        lifecycle_state: str,
        reason: str | None = None,
    ) -> uuid.UUID | None:
        if lifecycle_state not in {"active", "inactive", "deleted"}:
            raise PersonalMemoryLifecycleError(
                "Personal Memory lifecycle_state must be active, inactive, or deleted."
            )
        created_at_us = utc_now_us()
        commit_id = new_uuid7()
        with self.database.write_transaction() as connection:
            self._require_user_actor(connection, actor_id)
            row = connection.execute(
                """
                SELECT e.lifecycle_state
                FROM personal_memory_entries AS m
                JOIN entity_registry AS e ON e.entity_id = m.memory_id
                WHERE m.memory_id = ?
                """,
                (uuid_to_blob(memory_id),),
            ).fetchone()
            if row is None:
                raise PersonalMemoryNotFoundError(str(memory_id))
            current = str(row["lifecycle_state"])
            if current == "deleted" and lifecycle_state != "deleted":
                raise PersonalMemoryLifecycleError(
                    "Deleted Personal Memory cannot be reactivated by the v1 memory path."
                )
            if current == lifecycle_state:
                return None

            operation = {
                "active": "personal_memory.enable",
                "inactive": "personal_memory.disable",
                "deleted": "personal_memory.delete",
            }[lifecycle_state]
            commit_seq = self._insert_commit(
                connection,
                commit_id=commit_id,
                actor_id=actor_id,
                operation_type=operation,
                committed_at_us=created_at_us,
                reason=reason,
            )
            self._transition_state(
                connection,
                memory_id=memory_id,
                lifecycle_state=lifecycle_state,
                actor_id=actor_id,
                commit_seq=commit_seq,
                reason=reason,
            )
            self._insert_commit_change(
                connection,
                commit_seq=commit_seq,
                memory_id=memory_id,
                revision_id=None,
                change_type=lifecycle_state,
            )

            if lifecycle_state == "deleted":
                record_deletion(
                    connection,
                    entity_id=memory_id,
                    entity_type=PERSONAL_MEMORY_ENTITY_TYPE,
                    deleted_at_us=created_at_us,
                    deletion_commit_seq=commit_seq,
                    deleted_by_actor_id=actor_id,
                )

        return commit_id

    def reset_all(
        self,
        *,
        actor_id: uuid.UUID,
        reason: str | None = None,
    ) -> PersonalMemoryResetResult:
        created_at_us = utc_now_us()
        commit_id = new_uuid7()
        with self.database.write_transaction() as connection:
            self._require_user_actor(connection, actor_id)
            rows = connection.execute(
                """
                SELECT m.memory_id
                FROM personal_memory_entries AS m
                JOIN entity_registry AS e ON e.entity_id = m.memory_id
                WHERE e.lifecycle_state IN ('active', 'inactive')
                ORDER BY m.memory_id
                """
            ).fetchall()
            memory_ids = tuple(uuid_from_blob(bytes(row["memory_id"])) for row in rows)
            if not memory_ids:
                return PersonalMemoryResetResult(commit_id=None, deleted_count=0)

            commit_seq = self._insert_commit(
                connection,
                commit_id=commit_id,
                actor_id=actor_id,
                operation_type="personal_memory.reset",
                committed_at_us=created_at_us,
                reason=reason,
            )
            for memory_id in memory_ids:
                self._transition_state(
                    connection,
                    memory_id=memory_id,
                    lifecycle_state="deleted",
                    actor_id=actor_id,
                    commit_seq=commit_seq,
                    reason=reason,
                )
                self._insert_commit_change(
                    connection,
                    commit_seq=commit_seq,
                    memory_id=memory_id,
                    revision_id=None,
                    change_type="reset",
                )
                record_deletion(
                    connection,
                    entity_id=memory_id,
                    entity_type=PERSONAL_MEMORY_ENTITY_TYPE,
                    deleted_at_us=created_at_us,
                    deletion_commit_seq=commit_seq,
                    deleted_by_actor_id=actor_id,
                )

        return PersonalMemoryResetResult(
            commit_id=commit_id,
            deleted_count=len(memory_ids),
        )

    @staticmethod
    def _require_unprotected_payload(draft: PersonalMemoryDraft) -> None:
        if draft.sensitivity is MemorySensitivity.PROTECTED:
            raise PersonalMemoryProtectionError(
                "Protected Personal Memory requires the Protected Content path; "
                "refusing plaintext persistence."
            )

    @staticmethod
    def _require_user_actor(connection: sqlite3.Connection, actor_id: uuid.UUID) -> None:
        row = connection.execute(
            "SELECT actor_type, active FROM actors WHERE actor_id = ?",
            (uuid_to_blob(actor_id),),
        ).fetchone()
        if row is None or int(row["active"]) != 1 or str(row["actor_type"]) != "user":
            raise PersonalMemoryActorError(str(actor_id))

    @staticmethod
    def _require_current_head(
        connection: sqlite3.Connection,
        *,
        memory_id: uuid.UUID,
    ) -> tuple[uuid.UUID, int, str]:
        row = connection.execute(
            """
            SELECT h.current_revision_id, h.current_revision_no, e.lifecycle_state
            FROM personal_memory_entries AS m
            JOIN entity_heads AS h ON h.entity_id = m.memory_id
            JOIN entity_registry AS e ON e.entity_id = m.memory_id
            WHERE m.memory_id = ?
            """,
            (uuid_to_blob(memory_id),),
        ).fetchone()
        if row is None:
            raise PersonalMemoryNotFoundError(str(memory_id))
        return (
            uuid_from_blob(bytes(row["current_revision_id"])),
            int(row["current_revision_no"]),
            str(row["lifecycle_state"]),
        )

    @staticmethod
    def _insert_commit(
        connection: sqlite3.Connection,
        *,
        commit_id: uuid.UUID,
        actor_id: uuid.UUID,
        operation_type: str,
        committed_at_us: int,
        reason: str | None,
    ) -> int:
        cursor = connection.execute(
            """
            INSERT INTO commit_records (
                commit_id, committed_at_us, actor_id, operation_type, reason
            ) VALUES (?, ?, ?, ?, ?)
            """,
            (
                uuid_to_blob(commit_id),
                committed_at_us,
                uuid_to_blob(actor_id),
                operation_type,
                reason,
            ),
        )
        if cursor.lastrowid is None:
            raise RuntimeError("SQLite did not return a commit sequence.")
        return int(cursor.lastrowid)

    @staticmethod
    def _insert_entity(
        connection: sqlite3.Connection,
        *,
        memory_id: uuid.UUID,
        actor_id: uuid.UUID,
        created_at_us: int,
        commit_seq: int,
        reason: str | None,
    ) -> None:
        entity_blob = uuid_to_blob(memory_id)
        actor_blob = uuid_to_blob(actor_id)
        connection.execute(
            """
            INSERT INTO entity_registry (
                entity_id, entity_type, domain, created_at_us, created_by_actor_id,
                lifecycle_state, protection_scope_id, schema_version
            ) VALUES (?, 'personal_memory_entry', 'personal_memory', ?, ?, 'active', NULL, 1)
            """,
            (entity_blob, created_at_us, actor_blob),
        )
        connection.execute(
            """
            INSERT INTO entity_state_history (
                entity_id, valid_from_commit_seq, valid_to_commit_seq,
                lifecycle_state, protection_scope_id, changed_by_actor_id, reason
            ) VALUES (?, ?, NULL, 'active', NULL, ?, ?)
            """,
            (entity_blob, commit_seq, actor_blob, reason),
        )

    @staticmethod
    def _insert_provenance(
        connection: sqlite3.Connection,
        *,
        provenance_id: uuid.UUID,
        memory_id: uuid.UUID,
        revision_id: uuid.UUID,
        operation: str,
        actor_id: uuid.UUID,
        created_at_us: int,
        reason: str | None,
    ) -> None:
        connection.execute(
            """
            INSERT INTO provenance_records (
                provenance_id, subject_entity_id, subject_revision_id, operation,
                actor_id, created_at_us, model_signature_id, processing_run_id,
                reason, protection_scope_id
            ) VALUES (?, ?, ?, ?, ?, ?, NULL, NULL, ?, NULL)
            """,
            (
                uuid_to_blob(provenance_id),
                uuid_to_blob(memory_id),
                uuid_to_blob(revision_id),
                operation,
                uuid_to_blob(actor_id),
                created_at_us,
                reason,
            ),
        )

    @staticmethod
    def _insert_revision(
        connection: sqlite3.Connection,
        *,
        memory_id: uuid.UUID,
        revision_id: uuid.UUID,
        revision_no: int,
        parent_revision_id: uuid.UUID | None,
        actor_id: uuid.UUID,
        provenance_id: uuid.UUID,
        commit_id: uuid.UUID,
        created_at_us: int,
        payload_hash: bytes,
        change_kind: str,
    ) -> None:
        connection.execute(
            """
            INSERT INTO revisions (
                revision_id, entity_id, revision_no, parent_revision_id,
                created_at_us, created_by_actor_id, provenance_id, schema_version,
                payload_hash, change_kind, commit_id
            ) VALUES (?, ?, ?, ?, ?, ?, ?, 1, ?, ?, ?)
            """,
            (
                uuid_to_blob(revision_id),
                uuid_to_blob(memory_id),
                revision_no,
                uuid_to_blob(parent_revision_id) if parent_revision_id is not None else None,
                created_at_us,
                uuid_to_blob(actor_id),
                uuid_to_blob(provenance_id),
                payload_hash,
                change_kind,
                uuid_to_blob(commit_id),
            ),
        )

    @staticmethod
    def _insert_payload(
        connection: sqlite3.Connection,
        *,
        revision_id: uuid.UUID,
        draft: PersonalMemoryDraft,
    ) -> None:
        connection.execute(
            """
            INSERT INTO personal_memory_revisions (
                revision_id, memory_kind, content, scope_entity_id, scope_kind,
                learning_mode, sensitivity, confidence, last_confirmed_at_us,
                protected_payload_id
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, NULL)
            """,
            (
                uuid_to_blob(revision_id),
                draft.memory_kind.value,
                draft.content,
                uuid_to_blob(draft.scope_entity_id) if draft.scope_entity_id is not None else None,
                draft.scope_kind.value,
                draft.learning_mode.value,
                draft.sensitivity.value,
                draft.confidence,
                draft.last_confirmed_at_us,
            ),
        )

    @staticmethod
    def _insert_commit_change(
        connection: sqlite3.Connection,
        *,
        commit_seq: int,
        memory_id: uuid.UUID,
        revision_id: uuid.UUID | None,
        change_type: str,
    ) -> None:
        connection.execute(
            """
            INSERT INTO commit_changes (commit_seq, entity_id, revision_id, change_type)
            VALUES (?, ?, ?, ?)
            """,
            (
                commit_seq,
                uuid_to_blob(memory_id),
                uuid_to_blob(revision_id) if revision_id is not None else None,
                change_type,
            ),
        )

    @staticmethod
    def _transition_state(
        connection: sqlite3.Connection,
        *,
        memory_id: uuid.UUID,
        lifecycle_state: str,
        actor_id: uuid.UUID,
        commit_seq: int,
        reason: str | None,
    ) -> None:
        entity_blob = uuid_to_blob(memory_id)
        connection.execute(
            """
            UPDATE entity_state_history
            SET valid_to_commit_seq = ?
            WHERE entity_id = ? AND valid_to_commit_seq IS NULL
            """,
            (commit_seq, entity_blob),
        )
        connection.execute(
            """
            INSERT INTO entity_state_history (
                entity_id, valid_from_commit_seq, valid_to_commit_seq,
                lifecycle_state, protection_scope_id, changed_by_actor_id, reason
            ) VALUES (?, ?, NULL, ?, NULL, ?, ?)
            """,
            (
                entity_blob,
                commit_seq,
                lifecycle_state,
                uuid_to_blob(actor_id),
                reason,
            ),
        )
        connection.execute(
            "UPDATE entity_registry SET lifecycle_state = ? WHERE entity_id = ?",
            (lifecycle_state, entity_blob),
        )

    @staticmethod
    def _revision_from_row(memory_id: uuid.UUID, row: sqlite3.Row) -> PersonalMemoryRevision:
        scope_entity_id = (
            uuid_from_blob(bytes(row["scope_entity_id"]))
            if row["scope_entity_id"] is not None
            else None
        )
        return PersonalMemoryRevision(
            memory_id=memory_id,
            revision_id=uuid_from_blob(bytes(row["revision_id"])),
            revision_no=int(row["revision_no"]),
            created_at_us=int(row["created_at_us"]),
            created_by_actor_id=uuid_from_blob(bytes(row["created_by_actor_id"])),
            provenance_id=uuid_from_blob(bytes(row["provenance_id"])),
            payload=PersonalMemoryDraft(
                memory_kind=MemoryKind(str(row["memory_kind"])),
                content=str(row["content"]),
                scope_entity_id=scope_entity_id,
                scope_kind=MemoryScopeKind(str(row["scope_kind"])),
                learning_mode=MemoryLearningMode(str(row["learning_mode"])),
                sensitivity=MemorySensitivity(str(row["sensitivity"])),
                confidence=float(row["confidence"]) if row["confidence"] is not None else None,
                last_confirmed_at_us=(
                    int(row["last_confirmed_at_us"])
                    if row["last_confirmed_at_us"] is not None
                    else None
                ),
            ),
        )


def _memory_payload_hash(draft: PersonalMemoryDraft) -> bytes:
    canonical_payload = json.dumps(
        {
            "confidence": draft.confidence,
            "content": draft.content,
            "last_confirmed_at_us": draft.last_confirmed_at_us,
            "learning_mode": draft.learning_mode.value,
            "memory_kind": draft.memory_kind.value,
            "scope_entity_id": str(draft.scope_entity_id) if draft.scope_entity_id else None,
            "scope_kind": draft.scope_kind.value,
            "sensitivity": draft.sensitivity.value,
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(canonical_payload).digest()
