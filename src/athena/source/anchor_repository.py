"""Persistent SourceAnchor storage for durable source evidence."""

from __future__ import annotations

import sqlite3
import uuid

from athena.common.ids import new_uuid7, uuid_from_blob, uuid_to_blob
from athena.common.time import utc_now_us
from athena.source.models import SourceAnchorRecord, SourceAnchorType
from athena.storage.database import SQLiteDatabase


class SourceAnchorNotFoundError(LookupError):
    """Raised when a SourceAnchor does not exist."""


class SourceAnchorRepository:
    """Persist stable anchors independently of reconstructible SourceChunks."""

    def __init__(self, database: SQLiteDatabase) -> None:
        self.database = database

    def materialize_text_range(
        self,
        *,
        actor_id: uuid.UUID,
        source_id: uuid.UUID,
        representation_id: uuid.UUID,
        start_offset: int,
        end_offset: int,
        quoted_hash: bytes,
        page_start: int | None = None,
        page_end: int | None = None,
    ) -> SourceAnchorRecord:
        if start_offset < 0 or end_offset <= start_offset:
            raise ValueError("Text SourceAnchor requires 0 <= start_offset < end_offset.")
        if len(quoted_hash) != 32:
            raise ValueError("quoted_hash must be a 32-byte SHA-256 digest.")
        if (page_start is None) != (page_end is None):
            raise ValueError("Text SourceAnchor page range must provide both endpoints or neither.")
        if page_start is not None and page_end is not None:
            if page_start < 1 or page_end < page_start:
                raise ValueError("Text SourceAnchor page range is invalid.")

        with self.database.write_transaction() as connection:
            self._require_active_actor(connection, actor_id)
            self._require_representation(connection, source_id, representation_id)
            existing = self._find_exact(
                connection,
                source_id=source_id,
                representation_id=representation_id,
                start_offset=start_offset,
                end_offset=end_offset,
                quoted_hash=quoted_hash,
            )
            if existing is not None:
                return existing

            now_us = utc_now_us()
            anchor_id = new_uuid7()
            provenance_id = new_uuid7()
            commit_id = new_uuid7()
            cursor = connection.execute(
                """
                INSERT INTO commit_records (
                    commit_id, committed_at_us, actor_id, operation_type, reason
                ) VALUES (?, ?, ?, 'source.anchor.text.materialize', NULL)
                """,
                (uuid_to_blob(commit_id), now_us, uuid_to_blob(actor_id)),
            )
            if cursor.lastrowid is None:
                raise RuntimeError("SQLite did not return a commit sequence.")
            commit_seq = int(cursor.lastrowid)
            anchor_blob = uuid_to_blob(anchor_id)
            actor_blob = uuid_to_blob(actor_id)
            connection.execute(
                """
                INSERT INTO entity_registry (
                    entity_id, entity_type, domain, created_at_us,
                    created_by_actor_id, lifecycle_state, protection_scope_id,
                    schema_version
                ) VALUES (?, 'source_anchor', 'raw_archive', ?, ?, 'active', NULL, 1)
                """,
                (anchor_blob, now_us, actor_blob),
            )
            connection.execute(
                """
                INSERT INTO entity_state_history (
                    entity_id, valid_from_commit_seq, valid_to_commit_seq,
                    lifecycle_state, protection_scope_id, changed_by_actor_id, reason
                ) VALUES (?, ?, NULL, 'active', NULL, ?, NULL)
                """,
                (anchor_blob, commit_seq, actor_blob),
            )
            connection.execute(
                """
                INSERT INTO source_anchors (
                    anchor_id, source_id, representation_id, anchor_type,
                    start_offset, end_offset, page_start, page_end,
                    start_time_ms, end_time_ms, geometry_json, quoted_hash
                ) VALUES (?, ?, ?, 'text_range', ?, ?, ?, ?, NULL, NULL, NULL, ?)
                """,
                (
                    anchor_blob,
                    uuid_to_blob(source_id),
                    uuid_to_blob(representation_id),
                    start_offset,
                    end_offset,
                    page_start,
                    page_end,
                    quoted_hash,
                ),
            )
            connection.execute(
                """
                INSERT INTO provenance_records (
                    provenance_id, subject_entity_id, subject_revision_id,
                    operation, actor_id, created_at_us, model_signature_id,
                    processing_run_id, reason, protection_scope_id
                ) VALUES (?, ?, NULL, 'source.anchor.text.materialize', ?, ?, NULL, NULL, NULL, NULL)
                """,
                (uuid_to_blob(provenance_id), anchor_blob, actor_blob, now_us),
            )
            connection.executemany(
                """
                INSERT INTO provenance_inputs (
                    provenance_id, input_entity_id, input_revision_id, input_role, ordinal
                ) VALUES (?, ?, NULL, ?, ?)
                """,
                (
                    (uuid_to_blob(provenance_id), uuid_to_blob(source_id), "source", 0),
                    (
                        uuid_to_blob(provenance_id),
                        uuid_to_blob(representation_id),
                        "source_representation",
                        1,
                    ),
                ),
            )
            connection.execute(
                """
                INSERT INTO commit_changes (commit_seq, entity_id, revision_id, change_type)
                VALUES (?, ?, NULL, 'create')
                """,
                (commit_seq, anchor_blob),
            )
            return SourceAnchorRecord(
                anchor_id=anchor_id,
                source_id=source_id,
                representation_id=representation_id,
                anchor_type=SourceAnchorType.TEXT_RANGE,
                start_offset=start_offset,
                end_offset=end_offset,
                page_start=page_start,
                page_end=page_end,
                start_time_ms=None,
                end_time_ms=None,
                geometry_json=None,
                quoted_hash=quoted_hash,
                created_at_us=now_us,
            )

    def materialize_structure(
        self,
        *,
        actor_id: uuid.UUID,
        structure_id: uuid.UUID,
    ) -> SourceAnchorRecord:
        with self.database.write_transaction() as connection:
            self._require_active_actor(connection, actor_id)
            structure = connection.execute(
                """
                SELECT s.structure_id, s.representation_id, s.structure_type,
                       s.start_offset, s.end_offset, s.content_hash, r.source_id
                FROM source_representation_structures AS s
                JOIN source_representations AS r
                  ON r.representation_id = s.representation_id
                WHERE s.structure_id = ?
                  AND r.retention_state = 'retained'
                """,
                (uuid_to_blob(structure_id),),
            ).fetchone()
            if structure is None:
                raise LookupError("Retained SourceRepresentation structure not found.")
            start_offset = int(structure["start_offset"])
            end_offset = int(structure["end_offset"])
            if end_offset <= start_offset:
                raise ValueError("Cannot materialize an empty document structure anchor.")
            source_id = uuid_from_blob(bytes(structure["source_id"]))
            representation_id = uuid_from_blob(bytes(structure["representation_id"]))
            quoted_hash = bytes(structure["content_hash"])
            structure_type = str(structure["structure_type"])
            anchor_type = (
                SourceAnchorType.TABLE_CELL
                if structure_type == "table_cell"
                else SourceAnchorType.STRUCTURED_PATH
            )

            existing = connection.execute(
                """
                SELECT a.*, e.created_at_us
                FROM source_anchor_structures AS link
                JOIN source_anchors AS a ON a.anchor_id = link.anchor_id
                JOIN entity_registry AS e ON e.entity_id = a.anchor_id
                WHERE link.structure_id = ?
                """,
                (uuid_to_blob(structure_id),),
            ).fetchone()
            if existing is not None:
                return _anchor_from_row(existing)

            now_us = utc_now_us()
            anchor_id = new_uuid7()
            provenance_id = new_uuid7()
            commit_id = new_uuid7()
            cursor = connection.execute(
                """
                INSERT INTO commit_records (
                    commit_id, committed_at_us, actor_id, operation_type, reason
                ) VALUES (?, ?, ?, 'source.anchor.structure.materialize', NULL)
                """,
                (uuid_to_blob(commit_id), now_us, uuid_to_blob(actor_id)),
            )
            if cursor.lastrowid is None:
                raise RuntimeError("SQLite did not return a commit sequence.")
            commit_seq = int(cursor.lastrowid)
            anchor_blob = uuid_to_blob(anchor_id)
            actor_blob = uuid_to_blob(actor_id)
            connection.execute(
                """
                INSERT INTO entity_registry (
                    entity_id, entity_type, domain, created_at_us,
                    created_by_actor_id, lifecycle_state, protection_scope_id,
                    schema_version
                ) VALUES (?, 'source_anchor', 'raw_archive', ?, ?, 'active', NULL, 1)
                """,
                (anchor_blob, now_us, actor_blob),
            )
            connection.execute(
                """
                INSERT INTO entity_state_history (
                    entity_id, valid_from_commit_seq, valid_to_commit_seq,
                    lifecycle_state, protection_scope_id, changed_by_actor_id, reason
                ) VALUES (?, ?, NULL, 'active', NULL, ?, NULL)
                """,
                (anchor_blob, commit_seq, actor_blob),
            )
            connection.execute(
                """
                INSERT INTO source_anchors (
                    anchor_id, source_id, representation_id, anchor_type,
                    start_offset, end_offset, page_start, page_end,
                    start_time_ms, end_time_ms, geometry_json, quoted_hash
                ) VALUES (?, ?, ?, ?, ?, ?, NULL, NULL, NULL, NULL, NULL, ?)
                """,
                (
                    anchor_blob,
                    uuid_to_blob(source_id),
                    uuid_to_blob(representation_id),
                    anchor_type.value,
                    start_offset,
                    end_offset,
                    quoted_hash,
                ),
            )
            connection.execute(
                """
                INSERT INTO source_anchor_structures (anchor_id, structure_id)
                VALUES (?, ?)
                """,
                (anchor_blob, uuid_to_blob(structure_id)),
            )
            connection.execute(
                """
                INSERT INTO provenance_records (
                    provenance_id, subject_entity_id, subject_revision_id,
                    operation, actor_id, created_at_us, model_signature_id,
                    processing_run_id, reason, protection_scope_id
                ) VALUES (
                    ?, ?, NULL, 'source.anchor.structure.materialize', ?, ?,
                    NULL, NULL, NULL, NULL
                )
                """,
                (uuid_to_blob(provenance_id), anchor_blob, actor_blob, now_us),
            )
            connection.executemany(
                """
                INSERT INTO provenance_inputs (
                    provenance_id, input_entity_id, input_revision_id, input_role, ordinal
                ) VALUES (?, ?, NULL, ?, ?)
                """,
                (
                    (uuid_to_blob(provenance_id), uuid_to_blob(source_id), "source", 0),
                    (
                        uuid_to_blob(provenance_id),
                        uuid_to_blob(representation_id),
                        "source_representation",
                        1,
                    ),
                ),
            )
            connection.execute(
                """
                INSERT INTO commit_changes (commit_seq, entity_id, revision_id, change_type)
                VALUES (?, ?, NULL, 'create')
                """,
                (commit_seq, anchor_blob),
            )
            return SourceAnchorRecord(
                anchor_id=anchor_id,
                source_id=source_id,
                representation_id=representation_id,
                anchor_type=anchor_type,
                start_offset=start_offset,
                end_offset=end_offset,
                page_start=None,
                page_end=None,
                start_time_ms=None,
                end_time_ms=None,
                geometry_json=None,
                quoted_hash=quoted_hash,
                created_at_us=now_us,
            )

    def structure_id_for_anchor(self, anchor_id: uuid.UUID) -> uuid.UUID | None:
        row = self.database.connection.execute(
            "SELECT structure_id FROM source_anchor_structures WHERE anchor_id = ?",
            (uuid_to_blob(anchor_id),),
        ).fetchone()
        if row is None:
            return None
        return uuid_from_blob(bytes(row["structure_id"]))

    def get(self, anchor_id: uuid.UUID) -> SourceAnchorRecord:
        row = self.database.connection.execute(
            """
            SELECT a.*, e.created_at_us
            FROM source_anchors AS a
            JOIN entity_registry AS e ON e.entity_id = a.anchor_id
            WHERE a.anchor_id = ?
            """,
            (uuid_to_blob(anchor_id),),
        ).fetchone()
        if row is None:
            raise SourceAnchorNotFoundError(f"SourceAnchor {anchor_id} not found.")
        return _anchor_from_row(row)

    def list_for_source(self, source_id: uuid.UUID, *, limit: int = 500) -> tuple[SourceAnchorRecord, ...]:
        if not 1 <= limit <= 5000:
            raise ValueError("Anchor list limit must be between 1 and 5000.")
        rows = self.database.connection.execute(
            """
            SELECT a.*, e.created_at_us
            FROM source_anchors AS a
            JOIN entity_registry AS e ON e.entity_id = a.anchor_id
            WHERE a.source_id = ?
            ORDER BY e.created_at_us, a.anchor_id
            LIMIT ?
            """,
            (uuid_to_blob(source_id), limit),
        ).fetchall()
        return tuple(_anchor_from_row(row) for row in rows)

    @staticmethod
    def _require_active_actor(connection: sqlite3.Connection, actor_id: uuid.UUID) -> None:
        row = connection.execute(
            "SELECT active FROM actors WHERE actor_id = ?",
            (uuid_to_blob(actor_id),),
        ).fetchone()
        if row is None or int(row["active"]) != 1:
            raise LookupError(f"Active actor {actor_id} not found.")

    @staticmethod
    def _require_representation(
        connection: sqlite3.Connection,
        source_id: uuid.UUID,
        representation_id: uuid.UUID,
    ) -> None:
        row = connection.execute(
            """
            SELECT retention_state
            FROM source_representations
            WHERE representation_id = ? AND source_id = ?
            """,
            (uuid_to_blob(representation_id), uuid_to_blob(source_id)),
        ).fetchone()
        if row is None:
            raise LookupError("SourceRepresentation does not belong to Source.")
        if str(row["retention_state"]) != "retained":
            raise ValueError("Durable SourceAnchor requires a retained SourceRepresentation.")

    @staticmethod
    def _find_exact(
        connection: sqlite3.Connection,
        *,
        source_id: uuid.UUID,
        representation_id: uuid.UUID,
        start_offset: int,
        end_offset: int,
        quoted_hash: bytes,
    ) -> SourceAnchorRecord | None:
        row = connection.execute(
            """
            SELECT a.*, e.created_at_us
            FROM source_anchors AS a
            JOIN entity_registry AS e ON e.entity_id = a.anchor_id
            WHERE a.source_id = ? AND a.representation_id = ?
              AND a.anchor_type = 'text_range'
              AND a.start_offset = ? AND a.end_offset = ? AND a.quoted_hash = ?
            """,
            (
                uuid_to_blob(source_id),
                uuid_to_blob(representation_id),
                start_offset,
                end_offset,
                quoted_hash,
            ),
        ).fetchone()
        return None if row is None else _anchor_from_row(row)


def _anchor_from_row(row: sqlite3.Row) -> SourceAnchorRecord:
    return SourceAnchorRecord(
        anchor_id=uuid_from_blob(bytes(row["anchor_id"])),
        source_id=uuid_from_blob(bytes(row["source_id"])),
        representation_id=(
            uuid_from_blob(bytes(row["representation_id"]))
            if row["representation_id"] is not None
            else None
        ),
        anchor_type=SourceAnchorType(str(row["anchor_type"])),
        start_offset=int(row["start_offset"]) if row["start_offset"] is not None else None,
        end_offset=int(row["end_offset"]) if row["end_offset"] is not None else None,
        page_start=int(row["page_start"]) if row["page_start"] is not None else None,
        page_end=int(row["page_end"]) if row["page_end"] is not None else None,
        start_time_ms=(int(row["start_time_ms"]) if row["start_time_ms"] is not None else None),
        end_time_ms=int(row["end_time_ms"]) if row["end_time_ms"] is not None else None,
        geometry_json=str(row["geometry_json"]) if row["geometry_json"] is not None else None,
        quoted_hash=bytes(row["quoted_hash"]) if row["quoted_hash"] is not None else None,
        created_at_us=int(row["created_at_us"]),
    )
