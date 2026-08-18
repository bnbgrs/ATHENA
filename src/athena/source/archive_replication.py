
"""Durable verified replication from local spool to the Raw Archive root."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

from athena.common.ids import uuid_from_blob, uuid_to_blob
from athena.common.time import utc_now_us
from athena.lifecycle.runtime_lock import runtime_data_lock
from athena.source.blob_store import (
    ArchiveStorageUnavailableError,
    BlobStore,
    BlobStoreError,
)
from athena.source.models import BlobRecord, BlobStorageArea
from athena.storage.database import SQLiteDatabase


class ArchiveReplicationError(RuntimeError):
    """Base error for durable Archive replication."""


class ArchiveReplicationInvariantError(ArchiveReplicationError):
    """Raised when durable replication state is internally inconsistent."""


class ArchiveReplicationState(str, Enum):
    PENDING = "pending"
    VERIFIED = "verified"


@dataclass(frozen=True, slots=True)
class ArchiveReplicationRecord:
    outbox_seq: int
    blob: BlobRecord
    target_role: str
    state: ArchiveReplicationState
    attempt_count: int
    created_at_us: int
    last_attempt_at_us: int | None
    last_error_code: str | None
    last_error_detail: str | None
    verified_at_us: int | None


@dataclass(frozen=True, slots=True)
class ArchiveReplicationStatus:
    pending_count: int
    verified_count: int
    contiguous_verified_seq: int
    max_outbox_seq: int


@dataclass(frozen=True, slots=True)
class ArchiveSyncResult:
    attempted: int
    verified: int
    failed: int
    cleaned_spool_replicas: int
    cleanup_failures: int
    blocked_reason: str | None
    status: ArchiveReplicationStatus


class ArchiveReplicationRepository:
    """Persist Outbox attempts and atomically confirm replication watermarks."""

    def __init__(
        self,
        database: SQLiteDatabase,
    ) -> None:
        self.database = database

    def list_pending(
        self,
        *,
        limit: int = 100,
    ) -> tuple[ArchiveReplicationRecord, ...]:
        self._validate_limit(limit)

        rows = self.database.connection.execute(
            self._record_query()
            + """
            WHERE o.state = 'pending'
            ORDER BY o.outbox_seq
            LIMIT ?
            """,
            (limit,),
        ).fetchall()

        return tuple(
            self._record_from_row(row)
            for row in rows
        )

    def list_verified(
        self,
        *,
        limit: int = 500,
    ) -> tuple[ArchiveReplicationRecord, ...]:
        self._validate_limit(limit)

        rows = self.database.connection.execute(
            self._record_query()
            + """
            WHERE o.state = 'verified'
            ORDER BY o.outbox_seq DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()

        return tuple(
            self._record_from_row(row)
            for row in rows
        )

    def get(
        self,
        outbox_seq: int,
    ) -> ArchiveReplicationRecord:
        row = self.database.connection.execute(
            self._record_query()
            + """
            WHERE o.outbox_seq = ?
            """,
            (outbox_seq,),
        ).fetchone()

        if row is None:
            raise LookupError(
                f"Archive replication outbox row {outbox_seq} does not exist."
            )

        return self._record_from_row(row)

    def mark_attempt(
        self,
        outbox_seq: int,
        *,
        now_us: int | None = None,
    ) -> ArchiveReplicationRecord:
        now = (
            utc_now_us()
            if now_us is None
            else now_us
        )

        with self.database.write_transaction() as connection:
            cursor = connection.execute(
                """
                UPDATE archive_replication_outbox
                SET attempt_count = attempt_count + 1,
                    last_attempt_at_us = ?,
                    last_error_code = NULL,
                    last_error_detail = NULL
                WHERE outbox_seq = ?
                  AND state = 'pending'
                """,
                (
                    now,
                    outbox_seq,
                ),
            )

            if cursor.rowcount != 1:
                raise ArchiveReplicationInvariantError(
                    "Archive replication attempt requires "
                    "one pending Outbox row."
                )

        return self.get(
            outbox_seq
        )

    def record_failure(
        self,
        outbox_seq: int,
        *,
        error_code: str,
        error_detail: str,
    ) -> ArchiveReplicationRecord:
        normalized_code = error_code.strip()
        normalized_detail = error_detail.strip()

        if not normalized_code:
            raise ValueError(
                "Archive replication error_code must not be empty."
            )

        with self.database.write_transaction() as connection:
            cursor = connection.execute(
                """
                UPDATE archive_replication_outbox
                SET last_error_code = ?,
                    last_error_detail = ?
                WHERE outbox_seq = ?
                  AND state = 'pending'
                """,
                (
                    normalized_code[:200],
                    normalized_detail[:2000],
                    outbox_seq,
                ),
            )

            if cursor.rowcount != 1:
                raise ArchiveReplicationInvariantError(
                    "Archive replication failure requires "
                    "one pending Outbox row."
                )

        return self.get(
            outbox_seq
        )

    def confirm_verified(
        self,
        outbox_seq: int,
        *,
        now_us: int | None = None,
    ) -> ArchiveReplicationRecord:
        """Atomically promote BlobRecord and advance contiguous watermark."""
        now = (
            utc_now_us()
            if now_us is None
            else now_us
        )

        with self.database.write_transaction() as connection:
            row = connection.execute(
                """
                SELECT
                    o.blob_id,
                    o.state,
                    b.storage_area
                FROM archive_replication_outbox AS o
                JOIN blob_records AS b
                  ON b.blob_id = o.blob_id
                WHERE o.outbox_seq = ?
                """,
                (outbox_seq,),
            ).fetchone()

            if row is None:
                raise ArchiveReplicationInvariantError(
                    "Archive replication Outbox row disappeared."
                )

            state = ArchiveReplicationState(
                str(row["state"])
            )

            if state is ArchiveReplicationState.VERIFIED:
                self._advance_watermark(
                    connection,
                    now_us=now,
                )
            else:
                storage_area = BlobStorageArea(
                    str(row["storage_area"])
                )

                if storage_area is not BlobStorageArea.SPOOL:
                    raise ArchiveReplicationInvariantError(
                        "Pending Archive replication does not "
                        "reference a spool BlobRecord."
                    )

                blob_id = uuid_from_blob(
                    bytes(row["blob_id"])
                )

                blob_cursor = connection.execute(
                    """
                    UPDATE blob_records
                    SET storage_area = 'archive',
                        verified_at_us = ?
                    WHERE blob_id = ?
                      AND storage_area = 'spool'
                    """,
                    (
                        now,
                        uuid_to_blob(blob_id),
                    ),
                )

                if blob_cursor.rowcount != 1:
                    raise ArchiveReplicationInvariantError(
                        "BlobRecord storage promotion lost its "
                        "expected spool state."
                    )

                outbox_cursor = connection.execute(
                    """
                    UPDATE archive_replication_outbox
                    SET state = 'verified',
                        verified_at_us = ?,
                        last_error_code = NULL,
                        last_error_detail = NULL
                    WHERE outbox_seq = ?
                      AND state = 'pending'
                    """,
                    (
                        now,
                        outbox_seq,
                    ),
                )

                if outbox_cursor.rowcount != 1:
                    raise ArchiveReplicationInvariantError(
                        "Archive replication Outbox confirmation "
                        "lost its pending state."
                    )

                self._advance_watermark(
                    connection,
                    now_us=now,
                )

        return self.get(
            outbox_seq
        )

    def status(
        self,
    ) -> ArchiveReplicationStatus:
        counts = self.database.connection.execute(
            """
            SELECT
                COALESCE(
                    SUM(CASE WHEN state = 'pending' THEN 1 ELSE 0 END),
                    0
                ) AS pending_count,
                COALESCE(
                    SUM(CASE WHEN state = 'verified' THEN 1 ELSE 0 END),
                    0
                ) AS verified_count,
                COALESCE(MAX(outbox_seq), 0) AS max_outbox_seq
            FROM archive_replication_outbox
            """
        ).fetchone()

        watermark = self.database.connection.execute(
            """
            SELECT contiguous_verified_seq
            FROM archive_replication_watermark
            WHERE singleton_id = 1
            """
        ).fetchone()

        if counts is None or watermark is None:
            raise ArchiveReplicationInvariantError(
                "Archive replication status is incomplete."
            )

        return ArchiveReplicationStatus(
            pending_count=int(
                counts["pending_count"]
            ),
            verified_count=int(
                counts["verified_count"]
            ),
            contiguous_verified_seq=int(
                watermark["contiguous_verified_seq"]
            ),
            max_outbox_seq=int(
                counts["max_outbox_seq"]
            ),
        )

    @staticmethod
    def _advance_watermark(
        connection: sqlite3.Connection,
        *,
        now_us: int,
    ) -> None:
        pending = connection.execute(
            """
            SELECT MIN(outbox_seq) AS first_pending
            FROM archive_replication_outbox
            WHERE state = 'pending'
            """
        ).fetchone()

        maximum = connection.execute(
            """
            SELECT COALESCE(MAX(outbox_seq), 0) AS maximum
            FROM archive_replication_outbox
            """
        ).fetchone()

        current = connection.execute(
            """
            SELECT contiguous_verified_seq
            FROM archive_replication_watermark
            WHERE singleton_id = 1
            """
        ).fetchone()

        if (
            pending is None
            or maximum is None
            or current is None
        ):
            raise ArchiveReplicationInvariantError(
                "Archive replication watermark state is incomplete."
            )

        first_pending = pending["first_pending"]

        candidate = (
            int(maximum["maximum"])
            if first_pending is None
            else int(first_pending) - 1
        )

        previous = int(
            current["contiguous_verified_seq"]
        )

        if candidate < previous:
            raise ArchiveReplicationInvariantError(
                "Archive replication watermark attempted to move backwards."
            )

        connection.execute(
            """
            UPDATE archive_replication_watermark
            SET contiguous_verified_seq = ?,
                updated_at_us = ?
            WHERE singleton_id = 1
            """,
            (
                candidate,
                now_us,
            ),
        )

    @staticmethod
    def _validate_limit(
        limit: int,
    ) -> None:
        if not 1 <= limit <= 1000:
            raise ValueError(
                "Archive replication limit must be between 1 and 1000."
            )

    @staticmethod
    def _record_query() -> str:
        return """
        SELECT
            o.outbox_seq,
            o.target_role,
            o.state,
            o.attempt_count,
            o.created_at_us,
            o.last_attempt_at_us,
            o.last_error_code,
            o.last_error_detail,
            o.verified_at_us,
            b.blob_id,
            b.byte_length,
            b.media_type AS blob_media_type,
            b.storage_area,
            b.storage_locator,
            b.integrity_sha256,
            b.encryption_state,
            b.created_at_us AS blob_created_at_us,
            b.verified_at_us AS blob_verified_at_us
        FROM archive_replication_outbox AS o
        JOIN blob_records AS b
          ON b.blob_id = o.blob_id
        """

    @staticmethod
    def _record_from_row(
        row: sqlite3.Row,
    ) -> ArchiveReplicationRecord:
        blob = BlobRecord(
            blob_id=uuid_from_blob(
                bytes(row["blob_id"])
            ),
            byte_length=int(
                row["byte_length"]
            ),
            media_type=(
                str(row["blob_media_type"])
                if row["blob_media_type"] is not None
                else None
            ),
            storage_area=BlobStorageArea(
                str(row["storage_area"])
            ),
            storage_locator=str(
                row["storage_locator"]
            ),
            integrity_sha256=bytes(
                row["integrity_sha256"]
            ),
            encryption_state=str(
                row["encryption_state"]
            ),
            created_at_us=int(
                row["blob_created_at_us"]
            ),
            verified_at_us=int(
                row["blob_verified_at_us"]
            ),
        )

        return ArchiveReplicationRecord(
            outbox_seq=int(
                row["outbox_seq"]
            ),
            blob=blob,
            target_role=str(
                row["target_role"]
            ),
            state=ArchiveReplicationState(
                str(row["state"])
            ),
            attempt_count=int(
                row["attempt_count"]
            ),
            created_at_us=int(
                row["created_at_us"]
            ),
            last_attempt_at_us=(
                int(row["last_attempt_at_us"])
                if row["last_attempt_at_us"] is not None
                else None
            ),
            last_error_code=(
                str(row["last_error_code"])
                if row["last_error_code"] is not None
                else None
            ),
            last_error_detail=(
                str(row["last_error_detail"])
                if row["last_error_detail"] is not None
                else None
            ),
            verified_at_us=(
                int(row["verified_at_us"])
                if row["verified_at_us"] is not None
                else None
            ),
        )


class ArchiveReplicationService:
    """Replicate durable spool blobs without ever making target trust implicit."""

    def __init__(
        self,
        *,
        repository: ArchiveReplicationRepository,
        blob_store: BlobStore,
        runtime_lock_root: Path | None = None,
    ) -> None:
        self.repository = repository
        self.blob_store = blob_store
        self.runtime_lock_root = runtime_lock_root

    def status(
        self,
    ) -> ArchiveReplicationStatus:
        return self.repository.status()

    def sync_pending(
        self,
        *,
        limit: int = 100,
    ) -> ArchiveSyncResult:
        with runtime_data_lock(self.runtime_lock_root):
            if not 1 <= limit <= 1000:
                raise ValueError(
                    "Archive sync limit must be between 1 and 1000."
                )

            archive_root = (
                self.blob_store.paths.archive_root
            )

            if archive_root is None:
                return ArchiveSyncResult(
                    attempted=0,
                    verified=0,
                    failed=0,
                    cleaned_spool_replicas=0,
                    cleanup_failures=0,
                    blocked_reason="archive_root_unconfigured",
                    status=self.repository.status(),
                )

            if not archive_root.is_dir():
                return ArchiveSyncResult(
                    attempted=0,
                    verified=0,
                    failed=0,
                    cleaned_spool_replicas=0,
                    cleanup_failures=0,
                    blocked_reason="archive_root_unavailable",
                    status=self.repository.status(),
                )

            cleaned, cleanup_failures = (
                self.cleanup_verified_spool_duplicates(
                    limit=limit
                )
            )

            attempted = 0
            verified = 0
            failed = 0
            blocked_reason: str | None = None

            for record in self.repository.list_pending(
                limit=limit
            ):
                attempted += 1

                record = self.repository.mark_attempt(
                    record.outbox_seq
                )

                try:
                    self.blob_store.replicate_spool_blob_to_archive(
                        storage_locator=record.blob.storage_locator,
                        expected_sha256=record.blob.integrity_sha256,
                        expected_length=record.blob.byte_length,
                    )
                except ArchiveStorageUnavailableError as exc:
                    self.repository.record_failure(
                        record.outbox_seq,
                        error_code=type(exc).__name__,
                        error_detail=type(exc).__name__,
                    )
                    failed += 1
                    blocked_reason = "archive_root_unavailable"
                    break
                except BlobStoreError as exc:
                    self.repository.record_failure(
                        record.outbox_seq,
                        error_code=type(exc).__name__,
                        error_detail=type(exc).__name__,
                    )
                    failed += 1
                    continue

                confirmed = self.repository.confirm_verified(
                    record.outbox_seq
                )

                verified += 1

                try:
                    was_cleaned = (
                        self._cleanup_verified_spool_replica_if_unpinned(
                            confirmed
                        )
                    )
                except BlobStoreError:
                    cleanup_failures += 1
                else:
                    if was_cleaned:
                        cleaned += 1

            return ArchiveSyncResult(
                attempted=attempted,
                verified=verified,
                failed=failed,
                cleaned_spool_replicas=cleaned,
                cleanup_failures=cleanup_failures,
                blocked_reason=blocked_reason,
                status=self.repository.status(),
            )

    def _cleanup_verified_spool_replica_if_unpinned(
        self,
        record: ArchiveReplicationRecord,
    ) -> bool:
        """Delete a verified spool duplicate only while no backup pin can race in."""
        # BEGIN IMMEDIATE serializes this check with BackupService's
        # backup_snapshot_pins insertion transaction. Once a pin is committed,
        # physical cleanup cannot pass this point until that pin is released.
        with self.repository.database.write_transaction() as connection:
            pinned = connection.execute(
                """
                SELECT 1
                FROM backup_snapshot_pins
                WHERE blob_id = ?
                LIMIT 1
                """,
                (
                    uuid_to_blob(
                        record.blob.blob_id
                    ),
                ),
            ).fetchone()

            if pinned is not None:
                return False

            return (
                self.blob_store
                .cleanup_verified_spool_replica(
                    storage_locator=(
                        record.blob.storage_locator
                    ),
                    expected_sha256=(
                        record.blob.integrity_sha256
                    ),
                    expected_length=(
                        record.blob.byte_length
                    ),
                )
            )

    def cleanup_verified_spool_duplicates(
        self,
        *,
        limit: int = 500,
    ) -> tuple[int, int]:
        """Reconcile crashes after DB confirmation but before spool deletion."""
        with runtime_data_lock(self.runtime_lock_root):
            cleaned = 0
            failures = 0

            for record in self.repository.list_verified(
                limit=limit
            ):
                try:
                    was_cleaned = (
                        self._cleanup_verified_spool_replica_if_unpinned(
                            record
                        )
                    )
                except BlobStoreError:
                    failures += 1
                else:
                    if was_cleaned:
                        cleaned += 1

            return cleaned, failures
