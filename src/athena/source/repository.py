"""Transactional persistence for Raw Archive Sources and BlobRecords."""

from __future__ import annotations

import sqlite3
import uuid

from athena.common.ids import new_uuid7, uuid_from_blob, uuid_to_blob
from athena.common.time import utc_now_us
from athena.source.blob_store import PreparedBlob
from athena.source.models import (
    BlobRecord,
    BlobStorageArea,
    SourceCaptureResult,
    SourceLifecycleState,
    SourceRecord,
    SourceType,
)
from athena.storage.database import SQLiteDatabase


class SourceNotFoundError(LookupError):
    """Raised when a requested Source does not exist."""


class SourceActorError(LookupError):
    """Raised when the capture actor does not exist or is inactive."""


class SourceRepository:
    """Persist immutable source captures after physical bytes are verified."""

    def __init__(self, database: SQLiteDatabase) -> None:
        self.database = database

    def capture_file(
        self,
        *,
        actor_id: uuid.UUID,
        original_name: str,
        source_uri: str,
        prepared_blob: PreparedBlob,
        source_type: SourceType = SourceType.FILE,
    ) -> SourceCaptureResult:
        now_us = utc_now_us()
        source_id = new_uuid7()
        source_provenance_id = new_uuid7()
        commit_id = new_uuid7()
        operation_type = f"source.capture.{source_type.value}"

        with self.database.write_transaction() as connection:
            self._require_active_actor(connection, actor_id)
            existing_blob = self._find_blob_by_integrity(
                connection,
                integrity_sha256=prepared_blob.integrity_sha256,
                byte_length=prepared_blob.byte_length,
            )
            reused_blob = existing_blob is not None
            if existing_blob is None:
                blob_id = new_uuid7()
                blob_provenance_id = new_uuid7()
            else:
                blob_id = existing_blob.blob_id
                blob_provenance_id = None

            commit_seq = self._insert_commit(
                connection,
                commit_id=commit_id,
                actor_id=actor_id,
                operation_type=operation_type,
                committed_at_us=now_us,
            )

            if existing_blob is None:
                self._insert_entity(
                    connection,
                    entity_id=blob_id,
                    entity_type="blob_record",
                    actor_id=actor_id,
                    created_at_us=now_us,
                    commit_seq=commit_seq,
                )
                assert blob_provenance_id is not None
                self._insert_provenance(
                    connection,
                    provenance_id=blob_provenance_id,
                    entity_id=blob_id,
                    operation="blob.capture",
                    actor_id=actor_id,
                    created_at_us=now_us,
                )
                connection.execute(
                    """
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
                    ) VALUES (?, ?, ?, ?, ?, ?, 'none', ?, ?)
                    """,
                    (
                        uuid_to_blob(blob_id),
                        prepared_blob.byte_length,
                        prepared_blob.media_type,
                        prepared_blob.storage_area.value,
                        prepared_blob.storage_locator,
                        prepared_blob.integrity_sha256,
                        now_us,
                        now_us,
                    ),
                )
                connection.execute(
                    """
                    INSERT INTO commit_changes (
                        commit_seq, entity_id, revision_id, change_type
                    ) VALUES (?, ?, NULL, 'create')
                    """,
                    (commit_seq, uuid_to_blob(blob_id)),
                )

            self._insert_entity(
                connection,
                entity_id=source_id,
                entity_type="source",
                actor_id=actor_id,
                created_at_us=now_us,
                commit_seq=commit_seq,
            )
            self._insert_provenance(
                connection,
                provenance_id=source_provenance_id,
                entity_id=source_id,
                operation=operation_type,
                actor_id=actor_id,
                created_at_us=now_us,
            )
            connection.execute(
                """
                INSERT INTO sources (
                    source_id,
                    source_type,
                    created_at_us,
                    acquired_at_us,
                    original_name,
                    original_modified_at_us,
                    mime_type,
                    blob_id,
                    content_sha256,
                    source_uri,
                    lifecycle_state,
                    provenance_id
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'captured', ?)
                """,
                (
                    uuid_to_blob(source_id),
                    source_type.value,
                    now_us,
                    now_us,
                    original_name,
                    prepared_blob.source_modified_at_us,
                    prepared_blob.media_type,
                    uuid_to_blob(blob_id),
                    prepared_blob.integrity_sha256,
                    source_uri,
                    uuid_to_blob(source_provenance_id),
                ),
            )
            connection.execute(
                """
                INSERT INTO commit_changes (
                    commit_seq, entity_id, revision_id, change_type
                ) VALUES (?, ?, NULL, 'create')
                """,
                (commit_seq, uuid_to_blob(source_id)),
            )

        source = SourceRecord(
            source_id=source_id,
            source_type=source_type,
            created_at_us=now_us,
            acquired_at_us=now_us,
            original_name=original_name,
            original_modified_at_us=prepared_blob.source_modified_at_us,
            mime_type=prepared_blob.media_type,
            blob_id=blob_id,
            content_sha256=prepared_blob.integrity_sha256,
            source_uri=source_uri,
            lifecycle_state=SourceLifecycleState.CAPTURED,
            provenance_id=source_provenance_id,
        )
        blob = existing_blob or BlobRecord(
            blob_id=blob_id,
            byte_length=prepared_blob.byte_length,
            media_type=prepared_blob.media_type,
            storage_area=prepared_blob.storage_area,
            storage_locator=prepared_blob.storage_locator,
            integrity_sha256=prepared_blob.integrity_sha256,
            encryption_state="none",
            created_at_us=now_us,
            verified_at_us=now_us,
        )
        return SourceCaptureResult(source=source, blob=blob, reused_blob=reused_blob)

    def find_blob_by_integrity(
        self,
        *,
        integrity_sha256: bytes,
        byte_length: int,
    ) -> BlobRecord | None:
        return self._find_blob_by_integrity(
            self.database.connection,
            integrity_sha256=integrity_sha256,
            byte_length=byte_length,
        )

    def get(self, source_id: uuid.UUID) -> tuple[SourceRecord, BlobRecord]:
        row = self.database.connection.execute(
            """
            SELECT
                s.source_id,
                s.source_type,
                s.created_at_us AS source_created_at_us,
                s.acquired_at_us,
                s.original_name,
                s.original_modified_at_us,
                s.mime_type,
                s.blob_id,
                s.content_sha256,
                s.source_uri,
                s.lifecycle_state,
                s.provenance_id,
                b.byte_length,
                b.media_type AS blob_media_type,
                b.storage_area,
                b.storage_locator,
                b.integrity_sha256,
                b.encryption_state,
                b.created_at_us AS blob_created_at_us,
                b.verified_at_us
            FROM sources AS s
            JOIN blob_records AS b ON b.blob_id = s.blob_id
            WHERE s.source_id = ?
            """,
            (uuid_to_blob(source_id),),
        ).fetchone()
        if row is None:
            raise SourceNotFoundError(str(source_id))
        return self._source_from_row(row), self._blob_from_row(row)

    def list(self, *, limit: int = 50) -> tuple[tuple[SourceRecord, BlobRecord], ...]:
        if limit < 1 or limit > 500:
            raise ValueError("Source list limit must be between 1 and 500.")
        rows = self.database.connection.execute(
            """
            SELECT
                s.source_id,
                s.source_type,
                s.created_at_us AS source_created_at_us,
                s.acquired_at_us,
                s.original_name,
                s.original_modified_at_us,
                s.mime_type,
                s.blob_id,
                s.content_sha256,
                s.source_uri,
                s.lifecycle_state,
                s.provenance_id,
                b.byte_length,
                b.media_type AS blob_media_type,
                b.storage_area,
                b.storage_locator,
                b.integrity_sha256,
                b.encryption_state,
                b.created_at_us AS blob_created_at_us,
                b.verified_at_us
            FROM sources AS s
            JOIN blob_records AS b ON b.blob_id = s.blob_id
            ORDER BY s.acquired_at_us DESC, s.source_id DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
        return tuple((self._source_from_row(row), self._blob_from_row(row)) for row in rows)

    @staticmethod
    def _find_blob_by_integrity(
        connection: sqlite3.Connection,
        *,
        integrity_sha256: bytes,
        byte_length: int,
    ) -> BlobRecord | None:
        row = connection.execute(
            """
            SELECT
                blob_id,
                byte_length,
                media_type AS blob_media_type,
                storage_area,
                storage_locator,
                integrity_sha256,
                encryption_state,
                created_at_us AS blob_created_at_us,
                verified_at_us
            FROM blob_records
            WHERE integrity_sha256 = ?
              AND byte_length = ?
              AND encryption_state = 'none'
            """,
            (integrity_sha256, byte_length),
        ).fetchone()
        if row is None:
            return None
        return SourceRepository._blob_from_row(row)

    @staticmethod
    def _source_from_row(row: sqlite3.Row) -> SourceRecord:
        return SourceRecord(
            source_id=uuid_from_blob(bytes(row["source_id"])),
            source_type=SourceType(str(row["source_type"])),
            created_at_us=int(row["source_created_at_us"]),
            acquired_at_us=int(row["acquired_at_us"]),
            original_name=(
                str(row["original_name"]) if row["original_name"] is not None else None
            ),
            original_modified_at_us=(
                int(row["original_modified_at_us"])
                if row["original_modified_at_us"] is not None
                else None
            ),
            mime_type=str(row["mime_type"]) if row["mime_type"] is not None else None,
            blob_id=uuid_from_blob(bytes(row["blob_id"])),
            content_sha256=bytes(row["content_sha256"]),
            source_uri=str(row["source_uri"]) if row["source_uri"] is not None else None,
            lifecycle_state=SourceLifecycleState(str(row["lifecycle_state"])),
            provenance_id=uuid_from_blob(bytes(row["provenance_id"])),
        )

    @staticmethod
    def _blob_from_row(row: sqlite3.Row) -> BlobRecord:
        return BlobRecord(
            blob_id=uuid_from_blob(bytes(row["blob_id"])),
            byte_length=int(row["byte_length"]),
            media_type=(
                str(row["blob_media_type"])
                if row["blob_media_type"] is not None
                else None
            ),
            storage_area=BlobStorageArea(str(row["storage_area"])),
            storage_locator=str(row["storage_locator"]),
            integrity_sha256=bytes(row["integrity_sha256"]),
            encryption_state=str(row["encryption_state"]),
            created_at_us=int(row["blob_created_at_us"]),
            verified_at_us=int(row["verified_at_us"]),
        )

    @staticmethod
    def _require_active_actor(connection: sqlite3.Connection, actor_id: uuid.UUID) -> None:
        row = connection.execute(
            "SELECT active FROM actors WHERE actor_id = ?",
            (uuid_to_blob(actor_id),),
        ).fetchone()
        if row is None or int(row["active"]) != 1:
            raise SourceActorError(str(actor_id))

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
            ) VALUES (?, ?, NULL, ?, ?, ?, NULL, NULL, NULL, NULL)
            """,
            (
                uuid_to_blob(provenance_id),
                uuid_to_blob(entity_id),
                operation,
                uuid_to_blob(actor_id),
                created_at_us,
            ),
        )
