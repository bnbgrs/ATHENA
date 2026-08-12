"""Persistence for immutable retained SourceRepresentations."""

from __future__ import annotations

import json
import sqlite3
import uuid

from athena.common.ids import new_uuid7, uuid_from_blob, uuid_to_blob
from athena.common.time import utc_now_us
from athena.source.models import (
    BlobRecord,
    BlobStorageArea,
    RepresentationRetentionState,
    SourceRepresentationRecord,
    SourceRepresentationType,
    TextRepresentationResult,
)
from athena.source.representation_store import StoredRepresentationBlob
from athena.storage.database import SQLiteDatabase


class SourceRepresentationNotFoundError(LookupError):
    """Raised when a requested SourceRepresentation does not exist."""


class SourceRepresentationActorError(LookupError):
    """Raised when the representation actor is unknown or inactive."""


class SourceRepresentationRepository:
    """Persist immutable retained representations and their concrete provenance."""

    def __init__(self, database: SQLiteDatabase) -> None:
        self.database = database

    def create_retained_text(
        self,
        *,
        actor_id: uuid.UUID,
        source_id: uuid.UUID,
        processing_run_id: uuid.UUID,
        stored_blob: StoredRepresentationBlob | None,
        existing_blob: BlobRecord | None,
        content_hash: bytes,
        parser_id: str,
        parser_version: str,
        options: dict[str, object],
    ) -> TextRepresentationResult:
        if (stored_blob is None) == (existing_blob is None):
            raise ValueError("Exactly one of stored_blob or existing_blob is required.")

        now_us = utc_now_us()
        representation_id = new_uuid7()
        representation_provenance_id = new_uuid7()
        commit_id = new_uuid7()
        options_json = json.dumps(
            options,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )

        with self.database.write_transaction() as connection:
            self._require_active_actor(connection, actor_id)
            source_blob_id = self._require_source(connection, source_id)
            self._require_running_run(connection, processing_run_id)

            if existing_blob is not None:
                byte_length = existing_blob.byte_length
            else:
                assert stored_blob is not None
                byte_length = stored_blob.byte_length

            current_blob = self._find_blob_by_integrity(
                connection,
                integrity_sha256=content_hash,
                byte_length=byte_length,
            )
            reused_blob = current_blob is not None
            blob_provenance_id: uuid.UUID | None = None
            if current_blob is not None:
                blob = current_blob
            elif existing_blob is not None:
                # The caller observed a blob before the transaction, but it vanished.
                # BlobRecords are immutable and currently have no delete path, so fail closed.
                raise RuntimeError("Previously observed immutable BlobRecord disappeared.")
            else:
                assert stored_blob is not None
                blob_id = new_uuid7()
                blob_provenance_id = new_uuid7()
                blob = BlobRecord(
                    blob_id=blob_id,
                    byte_length=stored_blob.byte_length,
                    media_type="text/plain; charset=utf-8",
                    storage_area=stored_blob.storage_area,
                    storage_locator=stored_blob.storage_locator,
                    integrity_sha256=stored_blob.content_sha256,
                    encryption_state="none",
                    created_at_us=now_us,
                    verified_at_us=now_us,
                )

            commit_seq = self._insert_commit(
                connection,
                commit_id=commit_id,
                actor_id=actor_id,
                operation_type="source.representation.text.create",
                committed_at_us=now_us,
            )

            if not reused_blob:
                assert blob_provenance_id is not None
                self._insert_entity(
                    connection,
                    entity_id=blob.blob_id,
                    entity_type="blob_record",
                    actor_id=actor_id,
                    created_at_us=now_us,
                    commit_seq=commit_seq,
                )
                self._insert_provenance(
                    connection,
                    provenance_id=blob_provenance_id,
                    entity_id=blob.blob_id,
                    operation="blob.representation.store",
                    actor_id=actor_id,
                    created_at_us=now_us,
                    processing_run_id=processing_run_id,
                )
                connection.execute(
                    """
                    INSERT INTO blob_records (
                        blob_id, byte_length, media_type, storage_area,
                        storage_locator, integrity_sha256, encryption_state,
                        created_at_us, verified_at_us
                    ) VALUES (?, ?, ?, ?, ?, ?, 'none', ?, ?)
                    """,
                    (
                        uuid_to_blob(blob.blob_id),
                        blob.byte_length,
                        blob.media_type,
                        blob.storage_area.value,
                        blob.storage_locator,
                        blob.integrity_sha256,
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
                    (commit_seq, uuid_to_blob(blob.blob_id)),
                )

            self._insert_entity(
                connection,
                entity_id=representation_id,
                entity_type="source_representation",
                actor_id=actor_id,
                created_at_us=now_us,
                commit_seq=commit_seq,
            )
            self._insert_provenance(
                connection,
                provenance_id=representation_provenance_id,
                entity_id=representation_id,
                operation="source.representation.text.create",
                actor_id=actor_id,
                created_at_us=now_us,
                processing_run_id=processing_run_id,
            )
            connection.executemany(
                """
                INSERT INTO provenance_inputs (
                    provenance_id, input_entity_id, input_revision_id,
                    input_role, ordinal
                ) VALUES (?, ?, NULL, ?, ?)
                """,
                (
                    (
                        uuid_to_blob(representation_provenance_id),
                        uuid_to_blob(source_id),
                        "source",
                        0,
                    ),
                    (
                        uuid_to_blob(representation_provenance_id),
                        uuid_to_blob(source_blob_id),
                        "source_blob",
                        1,
                    ),
                ),
            )
            connection.execute(
                """
                INSERT INTO source_representations (
                    representation_id,
                    source_id,
                    representation_type,
                    blob_id,
                    processing_run_id,
                    content_hash,
                    retention_state,
                    media_type,
                    parser_id,
                    parser_version,
                    options_json,
                    created_at_us,
                    provenance_id
                ) VALUES (?, ?, 'normalized_text', ?, ?, ?, 'retained', ?, ?, ?, ?, ?, ?)
                """,
                (
                    uuid_to_blob(representation_id),
                    uuid_to_blob(source_id),
                    uuid_to_blob(blob.blob_id),
                    uuid_to_blob(processing_run_id),
                    content_hash,
                    "text/plain; charset=utf-8",
                    parser_id,
                    parser_version,
                    options_json,
                    now_us,
                    uuid_to_blob(representation_provenance_id),
                ),
            )
            connection.execute(
                """
                UPDATE sources
                SET lifecycle_state = 'ready'
                WHERE source_id = ?
                """,
                (uuid_to_blob(source_id),),
            )
            connection.execute(
                """
                INSERT INTO commit_changes (
                    commit_seq, entity_id, revision_id, change_type
                ) VALUES (?, ?, NULL, 'create')
                """,
                (commit_seq, uuid_to_blob(representation_id)),
            )
            connection.execute(
                """
                INSERT INTO commit_changes (
                    commit_seq, entity_id, revision_id, change_type
                ) VALUES (?, ?, NULL, 'update')
                """,
                (commit_seq, uuid_to_blob(source_id)),
            )
            updated_run = connection.execute(
                """
                UPDATE processing_runs
                SET finished_at_us = ?, status = 'succeeded', error_detail = NULL
                WHERE processing_run_id = ? AND status = 'running'
                """,
                (now_us, uuid_to_blob(processing_run_id)),
            )
            if updated_run.rowcount != 1:
                raise ValueError("ProcessingRun stopped being writable during representation commit.")

        representation = SourceRepresentationRecord(
            representation_id=representation_id,
            source_id=source_id,
            representation_type=SourceRepresentationType.NORMALIZED_TEXT,
            blob_id=blob.blob_id,
            processing_run_id=processing_run_id,
            content_hash=content_hash,
            retention_state=RepresentationRetentionState.RETAINED,
            media_type="text/plain; charset=utf-8",
            parser_id=parser_id,
            parser_version=parser_version,
            options_json=options_json,
            created_at_us=now_us,
            provenance_id=representation_provenance_id,
        )
        return TextRepresentationResult(
            representation=representation,
            blob=blob,
            reused_blob=reused_blob,
        )

    def get(self, representation_id: uuid.UUID) -> tuple[SourceRepresentationRecord, BlobRecord]:
        row = self.database.connection.execute(
            """
            SELECT
                r.representation_id,
                r.source_id,
                r.representation_type,
                r.blob_id,
                r.processing_run_id,
                r.content_hash,
                r.retention_state,
                r.media_type AS representation_media_type,
                r.parser_id,
                r.parser_version,
                r.options_json,
                r.created_at_us AS representation_created_at_us,
                r.provenance_id,
                b.byte_length,
                b.media_type AS blob_media_type,
                b.storage_area,
                b.storage_locator,
                b.integrity_sha256,
                b.encryption_state,
                b.created_at_us AS blob_created_at_us,
                b.verified_at_us
            FROM source_representations AS r
            JOIN blob_records AS b ON b.blob_id = r.blob_id
            WHERE r.representation_id = ?
            """,
            (uuid_to_blob(representation_id),),
        ).fetchone()
        if row is None:
            raise SourceRepresentationNotFoundError(str(representation_id))
        return self._representation_from_row(row), self._blob_from_row(row)

    def list_for_source(
        self,
        source_id: uuid.UUID,
        *,
        limit: int = 50,
    ) -> tuple[tuple[SourceRepresentationRecord, BlobRecord], ...]:
        if limit < 1 or limit > 500:
            raise ValueError("Representation list limit must be between 1 and 500.")
        rows = self.database.connection.execute(
            """
            SELECT
                r.representation_id,
                r.source_id,
                r.representation_type,
                r.blob_id,
                r.processing_run_id,
                r.content_hash,
                r.retention_state,
                r.media_type AS representation_media_type,
                r.parser_id,
                r.parser_version,
                r.options_json,
                r.created_at_us AS representation_created_at_us,
                r.provenance_id,
                b.byte_length,
                b.media_type AS blob_media_type,
                b.storage_area,
                b.storage_locator,
                b.integrity_sha256,
                b.encryption_state,
                b.created_at_us AS blob_created_at_us,
                b.verified_at_us
            FROM source_representations AS r
            JOIN blob_records AS b ON b.blob_id = r.blob_id
            WHERE r.source_id = ?
            ORDER BY r.created_at_us DESC, r.representation_id DESC
            LIMIT ?
            """,
            (uuid_to_blob(source_id), limit),
        ).fetchall()
        return tuple((self._representation_from_row(row), self._blob_from_row(row)) for row in rows)

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
                blob_id, byte_length, media_type AS blob_media_type,
                storage_area, storage_locator, integrity_sha256,
                encryption_state, created_at_us AS blob_created_at_us,
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
        return SourceRepresentationRepository._blob_from_row(row)

    @staticmethod
    def _representation_from_row(row: sqlite3.Row) -> SourceRepresentationRecord:
        return SourceRepresentationRecord(
            representation_id=uuid_from_blob(bytes(row["representation_id"])),
            source_id=uuid_from_blob(bytes(row["source_id"])),
            representation_type=SourceRepresentationType(str(row["representation_type"])),
            blob_id=uuid_from_blob(bytes(row["blob_id"])),
            processing_run_id=uuid_from_blob(bytes(row["processing_run_id"])),
            content_hash=bytes(row["content_hash"]),
            retention_state=RepresentationRetentionState(str(row["retention_state"])),
            media_type=str(row["representation_media_type"]),
            parser_id=str(row["parser_id"]),
            parser_version=str(row["parser_version"]),
            options_json=str(row["options_json"]),
            created_at_us=int(row["representation_created_at_us"]),
            provenance_id=uuid_from_blob(bytes(row["provenance_id"])),
        )

    @staticmethod
    def _blob_from_row(row: sqlite3.Row) -> BlobRecord:
        return BlobRecord(
            blob_id=uuid_from_blob(bytes(row["blob_id"])),
            byte_length=int(row["byte_length"]),
            media_type=(str(row["blob_media_type"]) if row["blob_media_type"] is not None else None),
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
            raise SourceRepresentationActorError(str(actor_id))

    @staticmethod
    def _require_source(connection: sqlite3.Connection, source_id: uuid.UUID) -> uuid.UUID:
        row = connection.execute(
            "SELECT blob_id FROM sources WHERE source_id = ?",
            (uuid_to_blob(source_id),),
        ).fetchone()
        if row is None:
            raise SourceRepresentationNotFoundError(f"Source {source_id} not found.")
        return uuid_from_blob(bytes(row["blob_id"]))

    @staticmethod
    def _require_running_run(connection: sqlite3.Connection, processing_run_id: uuid.UUID) -> None:
        row = connection.execute(
            "SELECT status FROM processing_runs WHERE processing_run_id = ?",
            (uuid_to_blob(processing_run_id),),
        ).fetchone()
        if row is None or str(row["status"]) != "running":
            raise ValueError("SourceRepresentation requires its running ProcessingRun.")

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
            (uuid_to_blob(commit_id), committed_at_us, uuid_to_blob(actor_id), operation_type),
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
                entity_id, entity_type, domain, created_at_us,
                created_by_actor_id, lifecycle_state, protection_scope_id,
                schema_version
            ) VALUES (?, ?, 'raw_archive', ?, ?, 'active', NULL, 1)
            """,
            (entity_blob, entity_type, created_at_us, actor_blob),
        )
        connection.execute(
            """
            INSERT INTO entity_state_history (
                entity_id, valid_from_commit_seq, valid_to_commit_seq,
                lifecycle_state, protection_scope_id, changed_by_actor_id, reason
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
        processing_run_id: uuid.UUID,
    ) -> None:
        connection.execute(
            """
            INSERT INTO provenance_records (
                provenance_id, subject_entity_id, subject_revision_id,
                operation, actor_id, created_at_us, model_signature_id,
                processing_run_id, reason, protection_scope_id
            ) VALUES (?, ?, NULL, ?, ?, ?, NULL, ?, NULL, NULL)
            """,
            (
                uuid_to_blob(provenance_id),
                uuid_to_blob(entity_id),
                operation,
                uuid_to_blob(actor_id),
                created_at_us,
                uuid_to_blob(processing_run_id),
            ),
        )
