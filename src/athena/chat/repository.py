"""Transactional persistence for standard archived chats."""

from __future__ import annotations

import hashlib
import json
import sqlite3
import uuid

from athena.chat.models import ChatMessage, ChatSummary, ChatThread, MessageType
from athena.chat.send_identity import (
    SendOperationState,
    SendOperationStatus,
    assistant_message_id_for_operation,
    user_message_id_for_operation,
)
from athena.common.ids import new_uuid7, uuid_from_blob, uuid_to_blob
from athena.common.time import utc_now_us
from athena.storage.database import SQLiteDatabase


class ChatNotFoundError(LookupError):
    """Raised when a requested chat does not exist."""


class ActorNotFoundError(LookupError):
    """Raised when a requested actor does not exist or is inactive."""


class UnsupportedArchiveModeError(ValueError):
    """Raised when this persistent repository cannot safely handle a mode."""


class ChatRepository:
    """Minimal v1 chat repository used by Vertical Slice 1.

    Only ``standard`` chats are accepted here. ``temporary`` requires TTL and
    lifecycle machinery; ``do_not_store`` must not route its full payload into
    persistent storage. Those modes are introduced by their dedicated slices.
    """

    def __init__(self, database: SQLiteDatabase) -> None:
        self.database = database

    def find_active_actor(
        self,
        *,
        actor_type: str,
        display_name: str | None = None,
    ) -> uuid.UUID | None:
        row = self.database.connection.execute(
            """
            SELECT actor_id
            FROM actors
            WHERE actor_type = ?
              AND display_name IS ?
              AND active = 1
            ORDER BY created_at_us ASC, actor_id ASC
            LIMIT 1
            """,
            (actor_type, display_name),
        ).fetchone()
        if row is None:
            return None
        return uuid_from_blob(bytes(row["actor_id"]))

    def create_actor(self, *, actor_type: str, display_name: str | None = None) -> uuid.UUID:
        actor_id = new_uuid7()
        created_at_us = utc_now_us()

        with self.database.write_transaction() as connection:
            connection.execute(
                """
                INSERT INTO actors (
                    actor_id, actor_type, display_name, plugin_id, created_at_us, active
                ) VALUES (?, ?, ?, NULL, ?, 1)
                """,
                (uuid_to_blob(actor_id), actor_type, display_name, created_at_us),
            )

        return actor_id

    def create_chat(
        self,
        *,
        actor_id: uuid.UUID,
        archive_mode: str = "standard",
        chat_id: uuid.UUID | None = None,
    ) -> uuid.UUID:
        if archive_mode != "standard":
            raise UnsupportedArchiveModeError(
                "Vertical Slice 1 persists only standard chats. Temporary and "
                "do_not_store modes require their dedicated lifecycle paths."
            )

        resolved_chat_id = (
            chat_id
            if chat_id is not None
            else new_uuid7()
        )

        with self.database.write_transaction() as connection:
            self._require_active_actor(
                connection,
                actor_id,
            )

            if chat_id is not None:
                existing = connection.execute(
                    """
                    SELECT 1
                    FROM chats
                    WHERE chat_id = ?
                    """,
                    (
                        uuid_to_blob(
                            resolved_chat_id
                        ),
                    ),
                ).fetchone()

                if existing is not None:
                    self._require_standard_chat(
                        connection,
                        resolved_chat_id,
                    )
                    return resolved_chat_id

            commit_id = new_uuid7()
            provenance_id = new_uuid7()
            created_at_us = utc_now_us()

            commit_seq = self._insert_commit(
                connection,
                commit_id=commit_id,
                actor_id=actor_id,
                operation_type="chat.create",
                committed_at_us=created_at_us,
            )

            self._insert_entity(
                connection,
                entity_id=resolved_chat_id,
                entity_type="chat",
                actor_id=actor_id,
                created_at_us=created_at_us,
                commit_seq=commit_seq,
            )

            connection.execute(
                """
                INSERT INTO chats (
                    chat_id,
                    started_at_us,
                    ended_at_us,
                    archive_mode,
                    lifecycle_state,
                    protection_scope_id
                ) VALUES (?, ?, NULL, ?, 'active', NULL)
                """,
                (
                    uuid_to_blob(
                        resolved_chat_id
                    ),
                    created_at_us,
                    archive_mode,
                ),
            )

            self._insert_provenance(
                connection,
                provenance_id=provenance_id,
                entity_id=resolved_chat_id,
                revision_id=None,
                operation="chat.create",
                actor_id=actor_id,
                created_at_us=created_at_us,
            )

            connection.execute(
                """
                INSERT INTO commit_changes (
                    commit_seq,
                    entity_id,
                    revision_id,
                    change_type
                ) VALUES (?, ?, NULL, 'create')
                """,
                (
                    commit_seq,
                    uuid_to_blob(
                        resolved_chat_id
                    ),
                ),
            )

        return resolved_chat_id

    def append_message(
        self,
        *,
        chat_id: uuid.UUID,
        actor_id: uuid.UUID,
        message_type: MessageType,
        content: str,
        content_format: str = "text/plain",
        message_id: uuid.UUID | None = None,
    ) -> ChatMessage:
        resolved_message_id = (
            message_id
            if message_id is not None
            else new_uuid7()
        )
        revision_id = new_uuid7()
        provenance_id = new_uuid7()
        commit_id = new_uuid7()
        created_at_us = utc_now_us()
        payload_hash = _message_payload_hash(content, content_format)

        with self.database.write_transaction() as connection:
            self._require_active_actor(connection, actor_id)
            self._require_standard_chat(connection, chat_id)

            next_sequence = int(
                connection.execute(
                    """
                    SELECT COALESCE(MAX(sequence_no), 0) + 1
                    FROM chat_messages
                    WHERE chat_id = ?
                    """,
                    (uuid_to_blob(chat_id),),
                ).fetchone()[0]
            )

            commit_seq = self._insert_commit(
                connection,
                commit_id=commit_id,
                actor_id=actor_id,
                operation_type="chat_message.create",
                committed_at_us=created_at_us,
            )
            self._insert_entity(
                connection,
                entity_id=resolved_message_id,
                entity_type="chat_message",
                actor_id=actor_id,
                created_at_us=created_at_us,
                commit_seq=commit_seq,
            )
            self._insert_provenance(
                connection,
                provenance_id=provenance_id,
                entity_id=resolved_message_id,
                revision_id=revision_id,
                operation="chat_message.create",
                actor_id=actor_id,
                created_at_us=created_at_us,
            )
            connection.execute(
                """
                INSERT INTO revisions (
                    revision_id,
                    entity_id,
                    revision_no,
                    parent_revision_id,
                    created_at_us,
                    created_by_actor_id,
                    provenance_id,
                    schema_version,
                    payload_hash,
                    change_kind,
                    commit_id
                ) VALUES (?, ?, 1, NULL, ?, ?, ?, 1, ?, 'create', ?)
                """,
                (
                    uuid_to_blob(revision_id),
                    uuid_to_blob(resolved_message_id),
                    created_at_us,
                    uuid_to_blob(actor_id),
                    uuid_to_blob(provenance_id),
                    payload_hash,
                    uuid_to_blob(commit_id),
                ),
            )
            connection.execute(
                """
                INSERT INTO entity_heads (
                    entity_id, current_revision_id, current_revision_no
                ) VALUES (?, ?, 1)
                """,
                (uuid_to_blob(resolved_message_id), uuid_to_blob(revision_id)),
            )
            connection.execute(
                """
                INSERT INTO chat_messages (
                    message_id, chat_id, sequence_no, message_type, actor_id
                ) VALUES (?, ?, ?, ?, ?)
                """,
                (
                    uuid_to_blob(resolved_message_id),
                    uuid_to_blob(chat_id),
                    next_sequence,
                    message_type.value,
                    uuid_to_blob(actor_id),
                ),
            )
            connection.execute(
                """
                INSERT INTO chat_message_revisions (
                    revision_id, content, content_format, protected_payload_id
                ) VALUES (?, ?, ?, NULL)
                """,
                (uuid_to_blob(revision_id), content, content_format),
            )
            connection.execute(
                """
                INSERT INTO commit_changes (
                    commit_seq, entity_id, revision_id, change_type
                ) VALUES (?, ?, ?, 'create')
                """,
                (commit_seq, uuid_to_blob(resolved_message_id), uuid_to_blob(revision_id)),
            )

        return ChatMessage(
            message_id=resolved_message_id,
            chat_id=chat_id,
            sequence_no=next_sequence,
            message_type=message_type,
            actor_id=actor_id,
            created_at_us=created_at_us,
            revision_id=revision_id,
            content=content,
            content_format=content_format,
        )

    def inspect_send_operation(
        self,
        *,
        chat_id: uuid.UUID,
        operation_id: uuid.UUID,
        expected_content: str,
    ) -> SendOperationStatus:
        """Inspect durable send state without performing a mutation."""
        connection = self.database.connection
        self._require_standard_chat(
            connection,
            chat_id,
        )

        user_message_id = (
            user_message_id_for_operation(
                operation_id
            )
        )
        assistant_message_id = (
            assistant_message_id_for_operation(
                operation_id
            )
        )

        rows = connection.execute(
            """
            SELECT
                m.message_id,
                m.chat_id,
                m.sequence_no,
                m.message_type,
                m.actor_id,
                r.created_at_us,
                r.revision_id,
                mr.content,
                mr.content_format
            FROM chat_messages AS m
            JOIN entity_heads AS h
              ON h.entity_id = m.message_id
            JOIN revisions AS r
              ON r.revision_id = h.current_revision_id
            JOIN chat_message_revisions AS mr
              ON mr.revision_id = r.revision_id
            WHERE m.message_id IN (?, ?)
            """,
            (
                uuid_to_blob(
                    user_message_id
                ),
                uuid_to_blob(
                    assistant_message_id
                ),
            ),
        ).fetchall()

        messages = {
            message.message_id: message
            for message in (
                self._message_from_row(row)
                for row in rows
            )
        }

        user_message = messages.get(
            user_message_id
        )
        assistant_message = messages.get(
            assistant_message_id
        )

        if (
            user_message is None
            and assistant_message is None
        ):
            state = SendOperationState.ABSENT
        elif user_message is None:
            state = SendOperationState.CONFLICT
        elif (
            user_message.chat_id != chat_id
            or user_message.message_type
            is not MessageType.USER
            or user_message.content
            != expected_content
        ):
            state = SendOperationState.CONFLICT
        elif assistant_message is None:
            state = SendOperationState.INCOMPLETE
        elif (
            assistant_message.chat_id != chat_id
            or assistant_message.message_type
            is not MessageType.ASSISTANT
            or assistant_message.sequence_no
            != user_message.sequence_no + 1
        ):
            state = SendOperationState.CONFLICT
        else:
            state = SendOperationState.COMPLETE

        return SendOperationStatus(
            chat_id=chat_id,
            operation_id=operation_id,
            user_message_id=user_message_id,
            assistant_message_id=(
                assistant_message_id
            ),
            state=state,
        )

    def list_chats(
        self,
        *,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[ChatSummary, ...]:
        if limit < 1 or limit > 500:
            raise ValueError("Chat list limit must be between 1 and 500.")
        if offset < 0:
            raise ValueError("Chat list offset must be zero or greater.")

        rows = self.database.connection.execute(
            """
            SELECT
                c.chat_id,
                c.started_at_us,
                c.ended_at_us,
                c.archive_mode,
                c.lifecycle_state,
                COUNT(m.message_id) AS message_count
            FROM chats AS c
            LEFT JOIN chat_messages AS m
              ON m.chat_id = c.chat_id
            WHERE c.lifecycle_state != 'deleted'
            GROUP BY
                c.chat_id,
                c.started_at_us,
                c.ended_at_us,
                c.archive_mode,
                c.lifecycle_state
            ORDER BY c.started_at_us DESC, c.chat_id DESC
            LIMIT ? OFFSET ?
            """,
            (limit, offset),
        ).fetchall()

        return tuple(
            ChatSummary(
                chat_id=uuid_from_blob(bytes(row["chat_id"])),
                started_at_us=int(row["started_at_us"]),
                ended_at_us=(
                    int(row["ended_at_us"]) if row["ended_at_us"] is not None else None
                ),
                archive_mode=str(row["archive_mode"]),
                lifecycle_state=str(row["lifecycle_state"]),
                message_count=int(row["message_count"]),
            )
            for row in rows
        )

    def load_chat(self, chat_id: uuid.UUID) -> ChatThread:
        connection = self.database.connection
        chat_row = connection.execute(
            """
            SELECT chat_id, started_at_us, ended_at_us, archive_mode, lifecycle_state
            FROM chats
            WHERE chat_id = ?
              AND lifecycle_state != 'deleted'
            """,
            (uuid_to_blob(chat_id),),
        ).fetchone()
        if chat_row is None:
            raise ChatNotFoundError(str(chat_id))

        message_rows = connection.execute(
            """
            SELECT
                m.message_id,
                m.chat_id,
                m.sequence_no,
                m.message_type,
                m.actor_id,
                r.created_at_us,
                r.revision_id,
                mr.content,
                mr.content_format
            FROM chat_messages AS m
            JOIN entity_heads AS h
              ON h.entity_id = m.message_id
            JOIN revisions AS r
              ON r.revision_id = h.current_revision_id
            JOIN chat_message_revisions AS mr
              ON mr.revision_id = r.revision_id
            WHERE m.chat_id = ?
            ORDER BY m.sequence_no ASC
            """,
            (uuid_to_blob(chat_id),),
        ).fetchall()

        messages = tuple(self._message_from_row(row) for row in message_rows)
        return ChatThread(
            chat_id=uuid_from_blob(bytes(chat_row["chat_id"])),
            started_at_us=int(chat_row["started_at_us"]),
            ended_at_us=(
                int(chat_row["ended_at_us"])
                if chat_row["ended_at_us"] is not None
                else None
            ),
            archive_mode=str(chat_row["archive_mode"]),
            lifecycle_state=str(chat_row["lifecycle_state"]),
            messages=messages,
        )

    @staticmethod
    def _message_from_row(row: sqlite3.Row) -> ChatMessage:
        actor_blob = row["actor_id"]
        return ChatMessage(
            message_id=uuid_from_blob(bytes(row["message_id"])),
            chat_id=uuid_from_blob(bytes(row["chat_id"])),
            sequence_no=int(row["sequence_no"]),
            message_type=MessageType(str(row["message_type"])),
            actor_id=uuid_from_blob(bytes(actor_blob)) if actor_blob is not None else None,
            created_at_us=int(row["created_at_us"]),
            revision_id=uuid_from_blob(bytes(row["revision_id"])),
            content=str(row["content"]) if row["content"] is not None else None,
            content_format=(
                str(row["content_format"])
                if row["content_format"] is not None
                else None
            ),
        )

    @staticmethod
    def _require_active_actor(connection: sqlite3.Connection, actor_id: uuid.UUID) -> None:
        row = connection.execute(
            "SELECT active FROM actors WHERE actor_id = ?",
            (uuid_to_blob(actor_id),),
        ).fetchone()
        if row is None or int(row["active"]) != 1:
            raise ActorNotFoundError(str(actor_id))

    @staticmethod
    def _require_standard_chat(connection: sqlite3.Connection, chat_id: uuid.UUID) -> None:
        row = connection.execute(
            "SELECT archive_mode, lifecycle_state "
            "FROM chats WHERE chat_id = ?",
            (uuid_to_blob(chat_id),),
        ).fetchone()
        if row is None:
            raise ChatNotFoundError(str(chat_id))
        if str(row["lifecycle_state"]) == "deleted":
            raise ChatNotFoundError(str(chat_id))
        if str(row["archive_mode"]) != "standard":
            raise UnsupportedArchiveModeError(
                "This repository path only accepts standard archived chats."
            )

    @staticmethod
    def _insert_commit(
        connection: sqlite3.Connection,
        *,
        commit_id: uuid.UUID,
        actor_id: uuid.UUID,
        operation_type: str,
        committed_at_us: int,
    ) -> int:
        cursor = connection.execute(
            """
            INSERT INTO commit_records (
                commit_id, committed_at_us, actor_id, operation_type, reason
            ) VALUES (?, ?, ?, ?, NULL)
            """,
            (
                uuid_to_blob(commit_id),
                committed_at_us,
                uuid_to_blob(actor_id),
                operation_type,
            ),
        )
        if cursor.lastrowid is None:
            raise RuntimeError("SQLite did not return a commit sequence.")
        return int(cursor.lastrowid)

    @staticmethod
    def _insert_entity(
        connection: sqlite3.Connection,
        *,
        entity_id: uuid.UUID,
        entity_type: str,
        actor_id: uuid.UUID,
        created_at_us: int,
        commit_seq: int,
    ) -> None:
        entity_blob = uuid_to_blob(entity_id)
        actor_blob = uuid_to_blob(actor_id)
        connection.execute(
            """
            INSERT INTO entity_registry (
                entity_id,
                entity_type,
                domain,
                created_at_us,
                created_by_actor_id,
                lifecycle_state,
                protection_scope_id,
                schema_version
            ) VALUES (?, ?, 'raw_archive', ?, ?, 'active', NULL, 1)
            """,
            (entity_blob, entity_type, created_at_us, actor_blob),
        )
        connection.execute(
            """
            INSERT INTO entity_state_history (
                entity_id,
                valid_from_commit_seq,
                valid_to_commit_seq,
                lifecycle_state,
                protection_scope_id,
                changed_by_actor_id,
                reason
            ) VALUES (?, ?, NULL, 'active', NULL, ?, NULL)
            """,
            (entity_blob, commit_seq, actor_blob),
        )

    @staticmethod
    def _insert_provenance(
        connection: sqlite3.Connection,
        *,
        provenance_id: uuid.UUID,
        entity_id: uuid.UUID,
        revision_id: uuid.UUID | None,
        operation: str,
        actor_id: uuid.UUID,
        created_at_us: int,
    ) -> None:
        connection.execute(
            """
            INSERT INTO provenance_records (
                provenance_id,
                subject_entity_id,
                subject_revision_id,
                operation,
                actor_id,
                created_at_us,
                model_signature_id,
                processing_run_id,
                reason,
                protection_scope_id
            ) VALUES (?, ?, ?, ?, ?, ?, NULL, NULL, NULL, NULL)
            """,
            (
                uuid_to_blob(provenance_id),
                uuid_to_blob(entity_id),
                uuid_to_blob(revision_id) if revision_id is not None else None,
                operation,
                uuid_to_blob(actor_id),
                created_at_us,
            ),
        )


def _message_payload_hash(content: str, content_format: str) -> bytes:
    # For this payload shape (string-only fields), Python's sorted compact JSON
    # encoding is the RFC 8785 canonical representation. A general JCS encoder
    # will be introduced before payloads can contain numeric/object extensions.
    canonical_payload = json.dumps(
        {"content": content, "content_format": content_format},
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(canonical_payload).digest()
