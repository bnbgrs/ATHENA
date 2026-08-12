"""Deterministic local full-text retrieval over current ATHENA heads."""

from __future__ import annotations

import re
import sqlite3
import uuid
from dataclasses import dataclass
from enum import Enum

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

    The FTS index is not canonical state. A commit-sequence watermark detects
    canonical changes and causes a deterministic full rebuild before querying.
    Protected payloads are excluded from this unprotected search path.
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
        current_commit_seq = self._current_commit_seq(self.database.connection)
        if self.indexed_commit_seq() >= current_commit_seq:
            return

        with self.database.write_transaction() as connection:
            # Re-check after obtaining the writer lock.
            current_commit_seq = self._current_commit_seq(connection)
            row = connection.execute(
                """
                SELECT indexed_commit_seq
                FROM search_index_state
                WHERE singleton_id = 1
                """
            ).fetchone()
            if row is None:
                raise SearchError("Search index state is missing.")
            if int(row["indexed_commit_seq"]) < current_commit_seq:
                self._rebuild_in_transaction(connection)

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

        # Archived current chat-message revisions are searchable as raw history.
        connection.execute(
            """
            INSERT INTO search_fts (
                entity_id, revision_id, entity_type, title, body
            )
            SELECT
                lower(hex(m.message_id)),
                lower(hex(h.current_revision_id)),
                'chat_message',
                'Chat message ' || CAST(m.sequence_no AS TEXT),
                mr.content
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
            """
        )

        indexed_commit_seq = self._current_commit_seq(connection)
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
    def _current_commit_seq(connection: sqlite3.Connection) -> int:
        row = connection.execute(
            "SELECT COALESCE(MAX(commit_seq), 0) AS commit_seq FROM commit_records"
        ).fetchone()
        if row is None:
            return 0
        return int(row["commit_seq"])

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
