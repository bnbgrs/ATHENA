"""Durable daily backup scheduling and execution."""

from __future__ import annotations

import json
import logging
import uuid
from pathlib import Path

from athena.backup.service import BackupRestoreError, BackupService
from athena.backup.target_lock import BackupTargetBusyError, backup_target_lock
from athena.common.ids import uuid_from_blob
from athena.common.time import utc_now_us
from athena.jobs.models import JobPriority, JobRecord, JobState, WaitingReason
from athena.jobs.service import DurableJobService

logger = logging.getLogger(__name__)

BACKUP_CREATE_JOB_TYPE = "backup.create"

_PIPELINE_VERSION = "backup-scheduler-v1"
_DAY_US = 86_400_000_000
_HOUR_US = 3_600_000_000
_DEFAULT_QUIET_HOUR_UTC = 3
_DEFAULT_RETRY_SECONDS = 5 * 60
_DEFAULT_LEASE_EXTENSION_SECONDS = 15 * 60
_JOB_SCAN_LIMIT = 4096


class BackupJobError(RuntimeError):
    """Raised when a durable scheduled backup cannot continue safely."""


def daily_backup_slot_us(
    now_us: int,
    *,
    quiet_hour_utc: int = _DEFAULT_QUIET_HOUR_UTC,
) -> int:
    """Return the most recent deterministic daily UTC backup slot."""
    if isinstance(now_us, bool) or not isinstance(now_us, int):
        raise TypeError("now_us must be an integer.")
    if not 0 <= quiet_hour_utc <= 23:
        raise ValueError("quiet_hour_utc must be between 0 and 23.")

    day_start_us = (now_us // _DAY_US) * _DAY_US
    slot_us = day_start_us + quiet_hour_utc * _HOUR_US

    if slot_us > now_us:
        slot_us -= _DAY_US

    return slot_us


class DurableBackupWorker:
    """Schedule and execute one verified daily backup per active target."""

    def __init__(
        self,
        *,
        jobs: DurableJobService,
        backup: BackupService,
        quiet_hour_utc: int = _DEFAULT_QUIET_HOUR_UTC,
        retry_seconds: int = _DEFAULT_RETRY_SECONDS,
        lease_extension_seconds: int = _DEFAULT_LEASE_EXTENSION_SECONDS,
    ) -> None:
        if not 0 <= quiet_hour_utc <= 23:
            raise ValueError(
                "Backup quiet_hour_utc must be between 0 and 23."
            )
        if retry_seconds <= 0:
            raise ValueError(
                "Backup retry_seconds must be positive."
            )
        if lease_extension_seconds <= 0:
            raise ValueError(
                "Backup lease_extension_seconds must be positive."
            )

        self.jobs = jobs
        self.backup = backup
        self.quiet_hour_utc = quiet_hour_utc
        self.retry_seconds = retry_seconds
        self.lease_extension_seconds = lease_extension_seconds

    def schedule_due(
        self,
        *,
        now_us: int | None = None,
    ) -> tuple[JobRecord, ...]:
        """Persist catch-up work for every due and currently available target."""
        now = utc_now_us() if now_us is None else now_us
        scheduled: list[JobRecord] = []

        rows = self.backup.database.connection.execute(
            """
            SELECT target_id, root_path, status
            FROM backup_targets
            WHERE status <> 'retired'
            ORDER BY target_id
            """
        ).fetchall()

        for row in rows:
            target_id = uuid_from_blob(bytes(row[0]))
            root_path = Path(str(row[1]))

            try:
                current_target = self.backup.target_status(target_id)
            except BackupTargetBusyError:
                continue
            except BackupRestoreError as exc:
                logger.error(
                    "Backup scheduler rejected target identity/state",
                    extra={
                        "event": "backup.scheduler_target_rejected",
                        "target_id": str(target_id),
                        "error_type": type(exc).__name__,
                    },
                )
                continue

            if current_target.status != "active":
                continue

            due_slot_us = self._due_slot_us(
                target_id,
                now_us=now,
            )

            if due_slot_us is None:
                continue

            try:
                with backup_target_lock(root_path):
                    if self._has_active_target_job(target_id):
                        continue

                    if self._has_job_for_slot(
                        target_id,
                        due_slot_us,
                    ):
                        continue

                    scheduled.append(
                        self.jobs.create(
                            job_type=BACKUP_CREATE_JOB_TYPE,
                            priority=JobPriority.DATA_SAFETY,
                            requested_scope={
                                "schedule_slot_us": due_slot_us,
                                "target_id": str(target_id),
                            },
                            pinned_configuration={
                                "pipeline_version": _PIPELINE_VERSION,
                                "quiet_hour_utc": self.quiet_hour_utc,
                            },
                        )
                    )
            except BackupTargetBusyError:
                # A manual backup, another scheduler, retention, verify, or
                # restore currently owns this target. The next scheduler tick
                # re-evaluates whether a catch-up backup is still required.
                continue

        return tuple(scheduled)

    def process_leased(
        self,
        job: JobRecord,
    ) -> JobRecord:
        """Execute one idempotent scheduled backup job."""
        if job.job_type != BACKUP_CREATE_JOB_TYPE:
            raise BackupJobError(
                f"Unexpected backup job type {job.job_type!r}."
            )

        lease_token = job.lease_token

        if lease_token is None:
            raise BackupJobError(
                f"Backup job {job.job_id} has no live lease token."
            )

        if job.state is JobState.CANCEL_REQUESTED:
            return self.jobs.acknowledge_cancel(
                job.job_id,
                lease_token=lease_token,
            )

        if job.state is not JobState.RUNNING:
            raise BackupJobError(
                f"Backup job {job.job_id} is not running."
            )

        target_id, schedule_slot_us = self._job_scope(job)

        # A manual backup may have completed after this job was queued.
        # Treat that restore point as satisfying the same daily slot rather
        # than creating a redundant second snapshot.
        latest_success_us = self._latest_success_us(target_id)

        if (
            latest_success_us is not None
            and latest_success_us >= schedule_slot_us
        ):
            return self.jobs.complete(
                job.job_id,
                lease_token=lease_token,
            )

        try:
            target = self.backup.target_status(target_id)
        except BackupTargetBusyError:
            return self._wait(
                job,
                lease_token=lease_token,
                reason=WaitingReason.BACKOFF,
            )
        except BackupRestoreError as exc:
            raise BackupJobError(
                f"Backup target {target_id} failed identity validation."
            ) from exc

        if target.status != "active":
            return self._wait(
                job,
                lease_token=lease_token,
                reason=WaitingReason.STORAGE,
            )

        # Give filesystem work a larger durable lease window. If a very large
        # backup still exceeds it, target locking prevents overlap and the job
        # remains idempotent because a completed snapshot satisfies its slot.
        self.jobs.heartbeat(
            job.job_id,
            lease_token=lease_token,
            extend_seconds=self.lease_extension_seconds,
        )

        try:
            snapshot = self.backup.create_snapshot(
                target_id=target_id,
            )
        except BackupTargetBusyError:
            return self._wait(
                job,
                lease_token=lease_token,
                reason=WaitingReason.BACKOFF,
            )
        except (BackupRestoreError, OSError) as exc:
            try:
                refreshed = self.backup.target_status(target_id)
            except BackupTargetBusyError:
                return self._wait(
                    job,
                    lease_token=lease_token,
                    reason=WaitingReason.BACKOFF,
                )
            except BackupRestoreError:
                refreshed = None

            if refreshed is not None and refreshed.status == "offline":
                return self._wait(
                    job,
                    lease_token=lease_token,
                    reason=WaitingReason.STORAGE,
                )

            raise BackupJobError(
                f"Scheduled backup for target {target_id} failed safely."
            ) from exc

        self.jobs.checkpoint(
            job.job_id,
            lease_token=lease_token,
            current_stage="backup_snapshot_complete",
            progress_state={
                "schedule_slot_us": schedule_slot_us,
                "snapshot_id": str(snapshot.snapshot_id),
                "target_id": str(target_id),
                "verification_status": snapshot.verification_status,
            },
            last_confirmed_output={
                "snapshot_id": str(snapshot.snapshot_id),
            },
        )

        return self.jobs.complete(
            job.job_id,
            lease_token=lease_token,
        )

    def _due_slot_us(
        self,
        target_id: uuid.UUID,
        *,
        now_us: int,
    ) -> int | None:
        slot_us = daily_backup_slot_us(
            now_us,
            quiet_hour_utc=self.quiet_hour_utc,
        )

        latest_success_us = self._latest_success_us(target_id)

        if latest_success_us is None:
            return slot_us

        if latest_success_us < slot_us:
            return slot_us

        return None

    def _latest_success_us(
        self,
        target_id: uuid.UUID,
    ) -> int | None:
        row = self.backup.database.connection.execute(
            """
            SELECT MAX(completed_at_us)
            FROM backup_snapshots
            WHERE target_id = ?
              AND state = 'complete'
              AND verification_status IN (
                  'verified_light',
                  'verified_deep'
              )
              AND pruned_at_us IS NULL
            """,
            (target_id.bytes,),
        ).fetchone()

        if row is None or row[0] is None:
            return None

        return int(row[0])

    def _has_active_target_job(
        self,
        target_id: uuid.UUID,
    ) -> bool:
        for job in self.jobs.active_for_type(
            BACKUP_CREATE_JOB_TYPE,
            limit=_JOB_SCAN_LIMIT,
        ):
            candidate_target, _ = self._job_scope(job)

            if candidate_target == target_id:
                return True

        return False

    def _has_job_for_slot(
        self,
        target_id: uuid.UUID,
        slot_us: int,
    ) -> bool:
        for job in self.jobs.list(limit=_JOB_SCAN_LIMIT):
            if job.job_type != BACKUP_CREATE_JOB_TYPE:
                continue

            candidate_target, candidate_slot = self._job_scope(job)

            if (
                candidate_target == target_id
                and candidate_slot == slot_us
            ):
                return True

        return False

    def _job_scope(
        self,
        job: JobRecord,
    ) -> tuple[uuid.UUID, int]:
        raw = job.requested_scope_json

        if raw is None:
            raise BackupJobError(
                f"Backup job {job.job_id} has no requested scope."
            )

        try:
            payload = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise BackupJobError(
                f"Backup job {job.job_id} has invalid scope JSON."
            ) from exc

        if not isinstance(payload, dict):
            raise BackupJobError(
                f"Backup job {job.job_id} scope must be an object."
            )

        target_raw = payload.get("target_id")
        slot_raw = payload.get("schedule_slot_us")

        if not isinstance(target_raw, str):
            raise BackupJobError(
                f"Backup job {job.job_id} has no target_id."
            )

        if (
            isinstance(slot_raw, bool)
            or not isinstance(slot_raw, int)
        ):
            raise BackupJobError(
                f"Backup job {job.job_id} has no valid schedule slot."
            )

        try:
            target_id = uuid.UUID(target_raw)
        except ValueError as exc:
            raise BackupJobError(
                f"Backup job {job.job_id} target_id is invalid."
            ) from exc

        return target_id, slot_raw

    def _wait(
        self,
        job: JobRecord,
        *,
        lease_token: bytes,
        reason: WaitingReason,
    ) -> JobRecord:
        now_us = utc_now_us()

        return self.jobs.wait(
            job.job_id,
            lease_token=lease_token,
            reason=reason,
            next_run_at_us=(
                now_us
                + self.retry_seconds * 1_000_000
            ),
            now_us=now_us,
        )
