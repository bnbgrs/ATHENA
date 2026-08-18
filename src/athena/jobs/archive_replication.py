
"""Durable scheduler worker for verified Raw Archive replication."""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass

from athena.common.time import utc_now_us
from athena.jobs.models import (
    CheckpointRecord,
    JobPriority,
    JobRecord,
    JobState,
    WaitingReason,
)
from athena.jobs.repository import JobTransitionError
from athena.jobs.service import DurableJobService
from athena.source.archive_replication import (
    ArchiveReplicationService,
)
from athena.source.blob_store import (
    ArchiveStorageUnavailableError,
    BlobStoreError,
)
from athena.source.models import BlobStorageArea

ARCHIVE_REPLICATION_JOB_TYPE = "archive.replicate"

_PIPELINE_VERSION = "archive-replication-v1"
_STAGE_SYNC = "archive_sync"
_STORAGE_RETRY_SECONDS = 60
_CLEANUP_SCAN_LIMIT = 1000


class ArchiveReplicationJobError(RuntimeError):
    """Raised when durable Archive replication cannot proceed safely."""


@dataclass(frozen=True, slots=True)
class ArchiveReplicationStepResult:
    """Result of one confirmed safe Archive-replication boundary."""

    job: JobRecord
    checkpoint: CheckpointRecord | None
    outbox_seq: int | None
    verified: bool
    cleaned_spool_replica: bool
    waiting: bool
    done: bool


class _LeaseHeartbeat:
    """Renew a fenced job lease while large filesystem I/O is streaming."""

    def __init__(
        self,
        *,
        jobs: DurableJobService,
        job_id: uuid.UUID,
        lease_token: bytes,
        extend_seconds: int,
    ) -> None:
        self.jobs = jobs
        self.job_id = job_id
        self.lease_token = lease_token
        self.extend_seconds = extend_seconds

        self.interval_us = max(
            1_000_000,
            extend_seconds
            * 1_000_000
            // 3,
        )

        self.last_heartbeat_us = 0

    def force(self) -> JobRecord:
        now_us = utc_now_us()

        current = self.jobs.heartbeat(
            self.job_id,
            lease_token=self.lease_token,
            extend_seconds=self.extend_seconds,
            now_us=now_us,
        )

        self.last_heartbeat_us = max(
            now_us,
            current.heartbeat_at_us
            or now_us,
        )

        return current

    def __call__(self) -> None:
        now_us = utc_now_us()

        if (
            self.last_heartbeat_us != 0
            and (
                now_us
                - self.last_heartbeat_us
            )
            < self.interval_us
        ):
            return

        self.force()


class DurableArchiveReplicationWorker:
    """Move pending spool blobs to Archive Root through durable boundaries."""

    def __init__(
        self,
        *,
        jobs: DurableJobService,
        replication: ArchiveReplicationService,
        storage_retry_seconds: int = _STORAGE_RETRY_SECONDS,
    ) -> None:
        if storage_retry_seconds <= 0:
            raise ValueError(
                "Archive storage retry seconds "
                "must be positive."
            )

        self.jobs = jobs
        self.replication = replication
        self.storage_retry_seconds = (
            storage_retry_seconds
        )

    def enqueue(self) -> JobRecord:
        """Create P0 data-safety work for pending Archive replication."""
        return self.jobs.create(
            job_type=ARCHIVE_REPLICATION_JOB_TYPE,
            priority=JobPriority.DATA_SAFETY,
            requested_scope={
                "target_role": "archive_root",
            },
            pinned_configuration={
                "pipeline_version": (
                    _PIPELINE_VERSION
                ),
                "storage_retry_seconds": (
                    self.storage_retry_seconds
                ),
            },
        )

    def reconcile_pending(
        self,
    ) -> JobRecord | None:
        """Keep pending Outbox work attached to persistent scheduler state."""
        active = self.jobs.active_for_type(
            ARCHIVE_REPLICATION_JOB_TYPE,
            limit=16,
        )

        if active:
            current = active[0]

            if (
                current.state
                is JobState.WAITING
                and current.blocked_reason
                == WaitingReason.STORAGE.value
                and self._archive_available()
            ):
                try:
                    return self.jobs.wake(
                        current.job_id
                    )
                except JobTransitionError:
                    # Another scheduler may have observed the same storage
                    # reconnect and won the wake transition.
                    return self.jobs.get(
                        current.job_id
                    )

            return current

        status = self.replication.status()

        if status.pending_count == 0:
            return None

        # archive_root=None is a valid local-only deployment. The Outbox
        # remains visible/durable without creating permanent P0 retry churn.
        if not self._archive_configured():
            return None

        return self.enqueue()

    def step(
        self,
        job_id: uuid.UUID,
        *,
        lease_token: bytes,
        extend_seconds: int = 120,
    ) -> ArchiveReplicationStepResult:
        """Execute one BlobRecord replication boundary."""
        if extend_seconds <= 0:
            raise ValueError(
                "extend_seconds must be positive."
            )

        job = self.jobs.get(
            job_id
        )

        self._validate_job_contract(
            job
        )

        if (
            job.state
            is JobState.CANCEL_REQUESTED
        ):
            cancelled = (
                self.jobs.acknowledge_cancel(
                    job_id,
                    lease_token=lease_token,
                )
            )

            return ArchiveReplicationStepResult(
                job=cancelled,
                checkpoint=None,
                outbox_seq=None,
                verified=False,
                cleaned_spool_replica=False,
                waiting=False,
                done=True,
            )

        heartbeat = _LeaseHeartbeat(
            jobs=self.jobs,
            job_id=job_id,
            lease_token=lease_token,
            extend_seconds=extend_seconds,
        )

        heartbeat.force()

        pending = (
            self.replication.repository
            .list_pending(
                limit=1
            )
        )

        if not pending:
            return self._finish_after_cleanup(
                job_id=job_id,
                lease_token=lease_token,
                heartbeat=heartbeat,
            )

        if not self._archive_available():
            return self._wait_for_storage(
                job_id=job_id,
                lease_token=lease_token,
                checkpoint=None,
                outbox_seq=None,
                verified=False,
                cleaned=False,
            )

        record = (
            self.replication.repository
            .mark_attempt(
                pending[0].outbox_seq
            )
        )

        try:
            (
                self.replication.blob_store
                .replicate_spool_blob_to_archive(
                    storage_locator=(
                        record.blob.storage_locator
                    ),
                    expected_sha256=(
                        record.blob.integrity_sha256
                    ),
                    expected_length=(
                        record.blob.byte_length
                    ),
                    progress_callback=heartbeat,
                )
            )

        except ArchiveStorageUnavailableError as exc:
            heartbeat.force()

            (
                self.replication.repository
                .record_failure(
                    record.outbox_seq,
                    error_code=(
                        type(exc).__name__
                    ),
                    error_detail=type(exc).__name__,
                )
            )

            return self._wait_for_storage(
                job_id=job_id,
                lease_token=lease_token,
                checkpoint=None,
                outbox_seq=record.outbox_seq,
                verified=False,
                cleaned=False,
            )

        except BlobStoreError as exc:
            heartbeat.force()

            (
                self.replication.repository
                .record_failure(
                    record.outbox_seq,
                    error_code=(
                        type(exc).__name__
                    ),
                    error_detail=type(exc).__name__,
                )
            )

            current = self.jobs.get(
                job_id
            )

            if (
                current.state
                is JobState.CANCEL_REQUESTED
            ):
                return self._acknowledge_cancel(
                    job_id=job_id,
                    lease_token=lease_token,
                    outbox_seq=record.outbox_seq,
                )

            # Integrity conflicts are not overwritten and are not hammered
            # automatically. User action must resolve the external conflict.
            waiting = self.jobs.wait(
                job_id,
                lease_token=lease_token,
                reason=WaitingReason.USER,
            )

            return ArchiveReplicationStepResult(
                job=waiting,
                checkpoint=None,
                outbox_seq=record.outbox_seq,
                verified=False,
                cleaned_spool_replica=False,
                waiting=True,
                done=False,
            )

        # Finish the current data-safety unit after a cancellation request:
        # copied bytes are not authoritative until target verification and
        # the BlobRecord/Outbox transaction have both committed.
        heartbeat.force()

        confirmed = (
            self.replication.repository
            .confirm_verified(
                record.outbox_seq
            )
        )

        status = (
            self.replication.status()
        )

        checkpoint = self.jobs.checkpoint(
            job_id,
            lease_token=lease_token,
            current_stage=_STAGE_SYNC,
            progress_state={
                "outbox_seq": (
                    confirmed.outbox_seq
                ),
                "pending_count": (
                    status.pending_count
                ),
                "contiguous_verified_seq": (
                    status.contiguous_verified_seq
                ),
                "max_outbox_seq": (
                    status.max_outbox_seq
                ),
            },
            last_confirmed_input={
                "outbox_seq": (
                    confirmed.outbox_seq
                ),
                "blob_id": str(
                    confirmed.blob.blob_id
                ),
                "storage_locator": (
                    confirmed.blob.storage_locator
                ),
            },
            last_confirmed_output={
                "storage_area": (
                    confirmed.blob.storage_area.value
                ),
                "integrity_sha256": (
                    confirmed.blob
                    .integrity_sha256
                    .hex()
                ),
                "byte_length": (
                    confirmed.blob.byte_length
                ),
            },
            resume_metadata={
                "pipeline_version": (
                    _PIPELINE_VERSION
                ),
                "next_action": (
                    "cleanup_then_continue"
                ),
            },
        )

        cleaned = False

        try:
            cleaned = (
                self.replication.blob_store
                .cleanup_verified_spool_replica(
                    storage_locator=(
                        confirmed.blob.storage_locator
                    ),
                    expected_sha256=(
                        confirmed.blob.integrity_sha256
                    ),
                    expected_length=(
                        confirmed.blob.byte_length
                    ),
                    progress_callback=heartbeat,
                )
            )

        except ArchiveStorageUnavailableError:
            return self._wait_for_storage(
                job_id=job_id,
                lease_token=lease_token,
                checkpoint=checkpoint,
                outbox_seq=confirmed.outbox_seq,
                verified=True,
                cleaned=False,
            )

        except BlobStoreError:
            current = heartbeat.force()

            if (
                current.state
                is JobState.CANCEL_REQUESTED
            ):
                return self._acknowledge_cancel(
                    job_id=job_id,
                    lease_token=lease_token,
                    outbox_seq=confirmed.outbox_seq,
                    checkpoint=checkpoint,
                    verified=True,
                )

            waiting = self.jobs.wait(
                job_id,
                lease_token=lease_token,
                reason=WaitingReason.USER,
            )

            return ArchiveReplicationStepResult(
                job=waiting,
                checkpoint=checkpoint,
                outbox_seq=confirmed.outbox_seq,
                verified=True,
                cleaned_spool_replica=False,
                waiting=True,
                done=False,
            )

        current = heartbeat.force()

        if (
            current.state
            is JobState.CANCEL_REQUESTED
        ):
            return self._acknowledge_cancel(
                job_id=job_id,
                lease_token=lease_token,
                outbox_seq=confirmed.outbox_seq,
                checkpoint=checkpoint,
                verified=True,
                cleaned=cleaned,
            )

        # Completion deliberately happens on the following boundary. That
        # boundary also reconciles a crash between DB confirmation and unlink.
        return ArchiveReplicationStepResult(
            job=current,
            checkpoint=checkpoint,
            outbox_seq=confirmed.outbox_seq,
            verified=True,
            cleaned_spool_replica=cleaned,
            waiting=False,
            done=False,
        )

    def _finish_after_cleanup(
        self,
        *,
        job_id: uuid.UUID,
        lease_token: bytes,
        heartbeat: _LeaseHeartbeat,
    ) -> ArchiveReplicationStepResult:
        cleaned = False

        for record in (
            self.replication.repository
            .list_verified(
                limit=_CLEANUP_SCAN_LIMIT
            )
        ):
            spool_path = (
                self.replication.blob_store
                .resolve_blob_path(
                    storage_area=(
                        BlobStorageArea.SPOOL
                    ),
                    storage_locator=(
                        record.blob.storage_locator
                    ),
                )
            )

            if not spool_path.exists():
                continue

            try:
                was_cleaned = (
                    self.replication.blob_store
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
                        progress_callback=heartbeat,
                    )
                )

            except ArchiveStorageUnavailableError:
                return self._wait_for_storage(
                    job_id=job_id,
                    lease_token=lease_token,
                    checkpoint=None,
                    outbox_seq=record.outbox_seq,
                    verified=True,
                    cleaned=cleaned,
                )

            except BlobStoreError:
                current = heartbeat.force()

                if (
                    current.state
                    is JobState.CANCEL_REQUESTED
                ):
                    return self._acknowledge_cancel(
                        job_id=job_id,
                        lease_token=lease_token,
                        outbox_seq=record.outbox_seq,
                        verified=True,
                        cleaned=cleaned,
                    )

                waiting = self.jobs.wait(
                    job_id,
                    lease_token=lease_token,
                    reason=WaitingReason.USER,
                )

                return ArchiveReplicationStepResult(
                    job=waiting,
                    checkpoint=None,
                    outbox_seq=record.outbox_seq,
                    verified=True,
                    cleaned_spool_replica=cleaned,
                    waiting=True,
                    done=False,
                )

            cleaned = (
                cleaned
                or was_cleaned
            )

        current = heartbeat.force()

        if (
            current.state
            is JobState.CANCEL_REQUESTED
        ):
            return self._acknowledge_cancel(
                job_id=job_id,
                lease_token=lease_token,
                outbox_seq=None,
                verified=True,
                cleaned=cleaned,
            )

        completed = self.jobs.complete(
            job_id,
            lease_token=lease_token,
        )

        return ArchiveReplicationStepResult(
            job=completed,
            checkpoint=None,
            outbox_seq=None,
            verified=True,
            cleaned_spool_replica=cleaned,
            waiting=False,
            done=True,
        )

    def _wait_for_storage(
        self,
        *,
        job_id: uuid.UUID,
        lease_token: bytes,
        checkpoint: CheckpointRecord | None,
        outbox_seq: int | None,
        verified: bool,
        cleaned: bool,
    ) -> ArchiveReplicationStepResult:
        current = self.jobs.get(
            job_id
        )

        if (
            current.state
            is JobState.CANCEL_REQUESTED
        ):
            return self._acknowledge_cancel(
                job_id=job_id,
                lease_token=lease_token,
                outbox_seq=outbox_seq,
                checkpoint=checkpoint,
                verified=verified,
                cleaned=cleaned,
            )

        retry_at_us = (
            utc_now_us()
            + self.storage_retry_seconds
            * 1_000_000
        )

        waiting = self.jobs.wait(
            job_id,
            lease_token=lease_token,
            reason=WaitingReason.STORAGE,
            next_run_at_us=retry_at_us,
        )

        return ArchiveReplicationStepResult(
            job=waiting,
            checkpoint=checkpoint,
            outbox_seq=outbox_seq,
            verified=verified,
            cleaned_spool_replica=cleaned,
            waiting=True,
            done=False,
        )

    def _acknowledge_cancel(
        self,
        *,
        job_id: uuid.UUID,
        lease_token: bytes,
        outbox_seq: int | None,
        checkpoint: CheckpointRecord | None = None,
        verified: bool = False,
        cleaned: bool = False,
    ) -> ArchiveReplicationStepResult:
        cancelled = (
            self.jobs.acknowledge_cancel(
                job_id,
                lease_token=lease_token,
            )
        )

        return ArchiveReplicationStepResult(
            job=cancelled,
            checkpoint=checkpoint,
            outbox_seq=outbox_seq,
            verified=verified,
            cleaned_spool_replica=cleaned,
            waiting=False,
            done=True,
        )

    def _archive_configured(
        self,
    ) -> bool:
        return (
            self.replication.blob_store
            .paths.archive_root
            is not None
        )

    def _archive_available(
        self,
    ) -> bool:
        root = (
            self.replication.blob_store
            .paths.archive_root
        )

        return (
            root is not None
            and root.is_dir()
        )

    @staticmethod
    def _validate_job_contract(
        job: JobRecord,
    ) -> None:
        if (
            job.job_type
            != ARCHIVE_REPLICATION_JOB_TYPE
        ):
            raise ArchiveReplicationJobError(
                "Archive worker received "
                "the wrong durable job type."
            )

        if (
            job.priority
            is not JobPriority.DATA_SAFETY
        ):
            raise ArchiveReplicationJobError(
                "Archive replication must remain "
                "P0 data-safety work."
            )

        if (
            job.pinned_configuration_json
            is None
        ):
            raise ArchiveReplicationJobError(
                "Archive replication job has "
                "no pinned configuration."
            )

        try:
            configuration = json.loads(
                job.pinned_configuration_json
            )
        except json.JSONDecodeError as exc:
            raise ArchiveReplicationJobError(
                "Archive replication job configuration "
                "is invalid JSON."
            ) from exc

        if (
            not isinstance(
                configuration,
                dict,
            )
            or configuration.get(
                "pipeline_version"
            )
            != _PIPELINE_VERSION
        ):
            raise ArchiveReplicationJobError(
                "Archive replication pipeline "
                "version is incompatible."
            )
