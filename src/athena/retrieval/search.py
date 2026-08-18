"""Deterministic local full-text retrieval over current ATHENA heads."""

from __future__ import annotations

import re
import sqlite3
import uuid
from dataclasses import dataclass
from enum import Enum

from athena.chat.provenance import (
    strip_model_facing_assistant_trace,
    strip_turn_local_grounding_markers,
)
from athena.common.time import utc_now_us
from athena.storage.database import SQLiteDatabase


class SearchError(ValueError):
    """Raised when a local search request is invalid or cannot be executed safely."""


class SearchEntityType(str, Enum):
    KNOWLEDGE = "knowledge"
    CLAIM = "claim"
    CHAT_MESSAGE = "chat_message"


@dataclass(frozen=True, slots=True)
class SearchResult:
    entity_id: uuid.UUID
    revision_id: uuid.UUID
    entity_type: SearchEntityType
    title: str | None
    snippet: str
    text: str
    score: float
    contradiction_count: int


class LocalSearchService:
    """Current-head FTS5 search with a reconstructible derived index.

    The FTS index is not canonical state. A projection-specific commit
    watermark tracks only text/visibility changes that can affect this index.
    Normal reads catch up changed entities incrementally; complete rebuilds are
    reserved for explicit maintenance and recovery. Protected payloads remain
    excluded from this unprotected search path.
    """

    def __init__(self, database: SQLiteDatabase) -> None:
        self.database = database

    def rebuild(self) -> int:
        """Rebuild the complete derived FTS index and return indexed row count."""
        with self.database.write_transaction() as connection:
            return self._rebuild_in_transaction(connection)

    def search(
        self,
        query: str,
        *,
        limit: int = 20,
        entity_type: SearchEntityType | None = None,
    ) -> tuple[SearchResult, ...]:
        if not 1 <= limit <= 200:
            raise SearchError("Search limit must be between 1 and 200.")

        fts_query = _safe_fts_query(query)
        self._ensure_current()

        clauses = ["search_fts MATCH ?"]
        parameters: list[object] = [fts_query]
        if entity_type is not None:
            clauses.append("entity_type = ?")
            parameters.append(entity_type.value)
        parameters.append(limit)

        sql = f"""
            SELECT
                entity_id,
                revision_id,
                entity_type,
                NULLIF(title, '') AS title,
                snippet(search_fts, 4, '[', ']', ' … ', 18) AS snippet,
                body AS full_text,
                -bm25(search_fts, 0.0, 0.0, 0.0, 2.0, 1.0) AS score,
                CASE
                    WHEN entity_type = 'claim' THEN (
                        SELECT count(*)
                        FROM claim_evidence AS ce
                        WHERE lower(hex(ce.claim_id)) = search_fts.entity_id
                          AND ce.evidence_role = 'contradicts'
                    )
                    ELSE 0
                END AS contradiction_count
            FROM search_fts
            WHERE {' AND '.join(clauses)}
            ORDER BY
                bm25(search_fts, 0.0, 0.0, 0.0, 2.0, 1.0) ASC,
                entity_type ASC,
                entity_id ASC
            LIMIT ?
        """
        try:
            rows = self.database.connection.execute(sql, tuple(parameters)).fetchall()
        except sqlite3.OperationalError as exc:
            raise SearchError("SQLite rejected the normalized FTS query.") from exc

        return tuple(self._row_to_result(row) for row in rows)

    def indexed_commit_seq(self) -> int:
        row = self.database.connection.execute(
            """
            SELECT indexed_commit_seq
            FROM search_index_state
            WHERE singleton_id = 1
            """
        ).fetchone()
        if row is None:
            raise SearchError("Search index state is missing.")
        return int(row["indexed_commit_seq"])

    def _ensure_current(self) -> None:
        current_commit_seq = (
            current_search_projection_commit_seq(
                self.database.connection
            )
        )
        indexed_commit_seq = self.indexed_commit_seq()

        if indexed_commit_seq >= current_commit_seq:
            return

        with self.database.write_transaction() as connection:
            # Re-check after obtaining the writer lock. Canonical writers are
            # blocked while this bounded Derived-State delta is projected.
            current_commit_seq = (
                current_search_projection_commit_seq(
                    connection
                )
            )

            row = connection.execute(
                """
                SELECT indexed_commit_seq
                FROM search_index_state
                WHERE singleton_id = 1
                """
            ).fetchone()

            if row is None:
                raise SearchError(
                    "Search index state is missing."
                )

            indexed_commit_seq = int(
                row["indexed_commit_seq"]
            )

            if indexed_commit_seq >= current_commit_seq:
                return

            self._refresh_in_transaction(
                connection,
                after_commit_seq=indexed_commit_seq,
                through_commit_seq=current_commit_seq,
            )

    def _refresh_in_transaction(
        self,
        connection: sqlite3.Connection,
        *,
        after_commit_seq: int,
        through_commit_seq: int,
    ) -> int:
        """Project only searchable entities changed in the commit interval."""

        if after_commit_seq < 0:
            raise SearchError(
                "Search index watermark must not be negative."
            )

        if through_commit_seq < after_commit_seq:
            raise SearchError(
                "Search refresh watermark moved backwards."
            )

        changed_rows = connection.execute(
            """
            SELECT DISTINCT cc.entity_id
            FROM commit_changes AS cc
            WHERE cc.commit_seq > ?
              AND cc.commit_seq <= ?
              AND cc.change_type IN (
                    'create',
                    'revise',
                    'deleted'
              )
              AND (
                    EXISTS (
                        SELECT 1
                        FROM knowledge_units AS k
                        WHERE k.knowledge_id = cc.entity_id
                    )
                    OR EXISTS (
                        SELECT 1
                        FROM claims AS c
                        WHERE c.claim_id = cc.entity_id
                    )
                    OR EXISTS (
                        SELECT 1
                        FROM chat_messages AS m
                        WHERE m.message_id = cc.entity_id
                    )
              )
            ORDER BY cc.entity_id
            """,
            (
                after_commit_seq,
                through_commit_seq,
            ),
        ).fetchall()

        for changed_row in changed_rows:
            entity_blob = bytes(
                changed_row["entity_id"]
            )
            entity_hex = entity_blob.hex()

            # An entity has at most one current FTS projection. Delete only
            # that entity, never the complete corpus.
            connection.execute(
                """
                DELETE FROM search_fts
                WHERE entity_id = ?
                """,
                (entity_hex,),
            )

            projection = connection.execute(
                """
                SELECT
                    'knowledge' AS entity_type,
                    lower(hex(k.knowledge_id)) AS entity_id,
                    lower(hex(h.current_revision_id)) AS revision_id,
                    COALESCE(kr.title, '') AS title,
                    kr.body AS body,
                    NULL AS message_type
                FROM knowledge_units AS k
                JOIN entity_registry AS e
                  ON e.entity_id = k.knowledge_id
                JOIN entity_heads AS h
                  ON h.entity_id = k.knowledge_id
                JOIN knowledge_unit_revisions AS kr
                  ON kr.revision_id = h.current_revision_id
                WHERE k.knowledge_id = ?
                  AND e.lifecycle_state = 'active'
                  AND kr.protected_payload_id IS NULL
                  AND kr.body IS NOT NULL
                  AND length(trim(kr.body)) > 0

                UNION ALL

                SELECT
                    'claim' AS entity_type,
                    lower(hex(c.claim_id)) AS entity_id,
                    lower(hex(h.current_revision_id)) AS revision_id,
                    '' AS title,
                    cr.statement AS body,
                    NULL AS message_type
                FROM claims AS c
                JOIN entity_registry AS e
                  ON e.entity_id = c.claim_id
                JOIN entity_heads AS h
                  ON h.entity_id = c.claim_id
                JOIN claim_revisions AS cr
                  ON cr.revision_id = h.current_revision_id
                WHERE c.claim_id = ?
                  AND e.lifecycle_state = 'active'
                  AND cr.protected_payload_id IS NULL
                  AND cr.statement IS NOT NULL
                  AND length(trim(cr.statement)) > 0

                UNION ALL

                SELECT
                    'chat_message' AS entity_type,
                    lower(hex(m.message_id)) AS entity_id,
                    lower(hex(h.current_revision_id)) AS revision_id,
                    'Chat message ' || CAST(m.sequence_no AS TEXT) AS title,
                    mr.content AS body,
                    m.message_type AS message_type
                FROM chat_messages AS m
                JOIN chats AS ch
                  ON ch.chat_id = m.chat_id
                JOIN entity_registry AS e
                  ON e.entity_id = m.message_id
                JOIN entity_heads AS h
                  ON h.entity_id = m.message_id
                JOIN chat_message_revisions AS mr
                  ON mr.revision_id = h.current_revision_id
                WHERE m.message_id = ?
                  AND e.lifecycle_state = 'active'
                  AND ch.lifecycle_state = 'active'
                  AND ch.archive_mode = 'standard'
                  AND mr.protected_payload_id IS NULL
                  AND mr.content IS NOT NULL
                  AND length(trim(mr.content)) > 0
                """,
                (
                    entity_blob,
                    entity_blob,
                    entity_blob,
                ),
            ).fetchone()

            # Deleted or otherwise non-visible entities intentionally have no
            # replacement FTS row.
            if projection is None:
                continue

            entity_type = str(
                projection["entity_type"]
            )
            body = str(
                projection["body"]
            )

            if entity_type == "chat_message":
                body = _searchable_chat_text(
                    str(
                        projection[
                            "message_type"
                        ]
                    ),
                    body,
                )

            connection.execute(
                """
                INSERT INTO search_fts (
                    entity_id,
                    revision_id,
                    entity_type,
                    title,
                    body
                ) VALUES (?, ?, ?, ?, ?)
                """,
                (
                    str(
                        projection[
                            "entity_id"
                        ]
                    ),
                    str(
                        projection[
                            "revision_id"
                        ]
                    ),
                    entity_type,
                    str(
                        projection[
                            "title"
                        ]
                    ),
                    body,
                ),
            )

        updated = connection.execute(
            """
            UPDATE search_index_state
            SET indexed_commit_seq = ?,
                rebuilt_at_us = ?
            WHERE singleton_id = 1
            """,
            (
                through_commit_seq,
                utc_now_us(),
            ),
        )

        if updated.rowcount != 1:
            raise SearchError(
                "Search index state is missing."
            )

        return len(changed_rows)

    def _rebuild_in_transaction(self, connection: sqlite3.Connection) -> int:
        connection.execute("DELETE FROM search_fts")

        # Only current, active and unprotected canonical Knowledge heads.
        connection.execute(
            """
            INSERT INTO search_fts (
                entity_id, revision_id, entity_type, title, body
            )
            SELECT
                lower(hex(k.knowledge_id)),
                lower(hex(h.current_revision_id)),
                'knowledge',
                COALESCE(kr.title, ''),
                kr.body
            FROM knowledge_units AS k
            JOIN entity_registry AS e
              ON e.entity_id = k.knowledge_id
            JOIN entity_heads AS h
              ON h.entity_id = k.knowledge_id
            JOIN knowledge_unit_revisions AS kr
              ON kr.revision_id = h.current_revision_id
            WHERE e.lifecycle_state = 'active'
              AND kr.protected_payload_id IS NULL
              AND kr.body IS NOT NULL
              AND length(trim(kr.body)) > 0
            """
        )

        # Only current, active and unprotected canonical Claim heads.
        connection.execute(
            """
            INSERT INTO search_fts (
                entity_id, revision_id, entity_type, title, body
            )
            SELECT
                lower(hex(c.claim_id)),
                lower(hex(h.current_revision_id)),
                'claim',
                '',
                cr.statement
            FROM claims AS c
            JOIN entity_registry AS e
              ON e.entity_id = c.claim_id
            JOIN entity_heads AS h
              ON h.entity_id = c.claim_id
            JOIN claim_revisions AS cr
              ON cr.revision_id = h.current_revision_id
            WHERE e.lifecycle_state = 'active'
              AND cr.protected_payload_id IS NULL
              AND cr.statement IS NOT NULL
              AND length(trim(cr.statement)) > 0
            """
        )

        # Archived current chat-message revisions remain searchable as raw
        # conversation history. System-appended ATHENA_PROVENANCE envelopes are
        # deliberately excluded from this Derived State so internal traceability
        # metadata cannot become semantic retrieval content or embedding input.
        chat_rows = connection.execute(
            """
            SELECT
                lower(hex(m.message_id)) AS entity_id,
                lower(hex(h.current_revision_id)) AS revision_id,
                m.message_type,
                'Chat message ' || CAST(m.sequence_no AS TEXT) AS title,
                mr.content AS body
            FROM chat_messages AS m
            JOIN chats AS ch
              ON ch.chat_id = m.chat_id
            JOIN entity_registry AS e
              ON e.entity_id = m.message_id
            JOIN entity_heads AS h
              ON h.entity_id = m.message_id
            JOIN chat_message_revisions AS mr
              ON mr.revision_id = h.current_revision_id
            WHERE e.lifecycle_state = 'active'
              AND ch.lifecycle_state = 'active'
              AND ch.archive_mode = 'standard'
              AND mr.protected_payload_id IS NULL
              AND mr.content IS NOT NULL
              AND length(trim(mr.content)) > 0
            ORDER BY m.message_id
            """
        ).fetchall()
        connection.executemany(
            """
            INSERT INTO search_fts (
                entity_id, revision_id, entity_type, title, body
            ) VALUES (?, ?, 'chat_message', ?, ?)
            """,
            (
                (
                    str(row["entity_id"]),
                    str(row["revision_id"]),
                    str(row["title"]),
                    _searchable_chat_text(
                        str(row["message_type"]),
                        str(row["body"]),
                    ),
                )
                for row in chat_rows
            ),
        )

        indexed_commit_seq = (
            current_search_projection_commit_seq(
                connection
            )
        )
        connection.execute(
            """
            UPDATE search_index_state
            SET indexed_commit_seq = ?, rebuilt_at_us = ?
            WHERE singleton_id = 1
            """,
            (indexed_commit_seq, utc_now_us()),
        )
        row = connection.execute("SELECT count(*) AS n FROM search_fts").fetchone()
        if row is None:
            raise SearchError("Search index count failed.")
        return int(row["n"])

    @staticmethod
    def _row_to_result(row: sqlite3.Row) -> SearchResult:
        entity_type = SearchEntityType(str(row["entity_type"]))
        return SearchResult(
            entity_id=_uuid_from_hex(row["entity_id"]),
            revision_id=_uuid_from_hex(row["revision_id"]),
            entity_type=entity_type,
            title=None if row["title"] is None else str(row["title"]),
            snippet=str(row["snippet"]),
            text=str(row["full_text"]),
            score=float(row["score"]),
            contradiction_count=int(row["contradiction_count"]),
        )


def current_search_projection_commit_seq(
    connection: sqlite3.Connection,
) -> int:
    """Return the newest commit that can change the unprotected search corpus."""

    row = connection.execute(
        """
        SELECT COALESCE(MAX(cc.commit_seq), 0) AS commit_seq
        FROM commit_changes AS cc
        WHERE cc.change_type IN (
            'create',
            'revise',
            'deleted'
        )
          AND (
                EXISTS (
                    SELECT 1
                    FROM knowledge_units AS k
                    WHERE k.knowledge_id = cc.entity_id
                )
                OR EXISTS (
                    SELECT 1
                    FROM claims AS c
                    WHERE c.claim_id = cc.entity_id
                )
                OR EXISTS (
                    SELECT 1
                    FROM chat_messages AS m
                    WHERE m.message_id = cc.entity_id
                )
          )
        """
    ).fetchone()

    if row is None:
        return 0

    return int(
        row["commit_seq"]
    )


def _searchable_chat_text(
    message_type: str,
    text: str,
) -> str:
    if message_type == "assistant":
        return strip_model_facing_assistant_trace(text)

    return strip_turn_local_grounding_markers(text)


def _safe_fts_query(query: str) -> str:
    tokens = re.findall(r"\w+", query, flags=re.UNICODE)
    if not tokens:
        raise SearchError("Search query must contain at least one letter or digit.")
    # Quoted terms prevent user input from being interpreted as FTS operators.
    return " OR ".join(f'"{token.replace(chr(34), chr(34) * 2)}"' for token in tokens)


def _uuid_from_hex(value: object) -> uuid.UUID:
    if not isinstance(value, str):
        raise SearchError("Search index contains an invalid UUID.")
    try:
        return uuid.UUID(hex=value)
    except ValueError as exc:
        raise SearchError("Search index contains an invalid UUID.") from exc
