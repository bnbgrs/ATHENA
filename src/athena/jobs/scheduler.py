"""Persistent ATHENA job scheduler and worker dispatch orchestration."""

from __future__ import annotations

import hashlib
import logging
import time
import uuid
from dataclasses import dataclass

from athena.common.time import utc_now_us
from athena.jobs.embedding_processing import (
    DurableEmbeddingRebuildWorker,
    EmbeddingRebuildJobError,
)
from athena.jobs.models import JobRecord, JobState, WaitingReason
from athena.jobs.repository import JobLeaseError, JobTransitionError
from athena.jobs.service import DurableJobService
from athena.jobs.source_analysis import DurableSourceAnalysisWorker, SourceAnalysisJobError
from athena.jobs.source_processing import (
    DurableSourceProcessingWorker,
    SourceProcessingJobError,
)

logger = logging.getLogger(__name__)

_SUPPORTED_JOB_TYPES = frozenset({"source.process", "embedding.rebuild", "source.analyze"})
_AUTO_RETRY_REASONS = frozenset(
    {
        WaitingReason.NETWORK.value,
        WaitingReason.RESOURCE.value,
        WaitingReason.STORAGE.value,
        WaitingReason.BACKOFF.value,
    }
)


class JobSchedulerError(RuntimeError):
    """Raised when scheduler orchestration cannot continue safely."""


@dataclass(frozen=True, slots=True)
class SchedulerPolicy:
    """Bounded v1 scheduling policy with deterministic retry/fairness behavior."""

    lease_seconds: int = 120
    candidate_limit: int = 128
    max_boundaries_per_dispatch: int = 8
    fairness_aging_seconds: int = 30 * 60
    retry_base_seconds: int = 5
    retry_max_seconds: int = 5 * 60
    retry_budget: int = 5
    retry_jitter_fraction: float = 0.20
    idle_poll_seconds: float = 5.0

    def __post_init__(self) -> None:
        if self.lease_seconds <= 0:
            raise ValueError("Scheduler lease_seconds must be positive.")
        if self.candidate_limit <= 0:
            raise ValueError("Scheduler candidate_limit must be positive.")
        if self.max_boundaries_per_dispatch <= 0:
            raise ValueError("Scheduler max_boundaries_per_dispatch must be positive.")
        if self.fairness_aging_seconds <= 0:
            raise ValueError("Scheduler fairness_aging_seconds must be positive.")
        if self.retry_base_seconds <= 0:
            raise ValueError("Scheduler retry_base_seconds must be positive.")
        if self.retry_max_seconds < self.retry_base_seconds:
            raise ValueError(
                "Scheduler retry_max_seconds must be >= retry_base_seconds."
            )
        if self.retry_budget < 0:
            raise ValueError("Scheduler retry_budget must not be negative.")
        if not 0.0 <= self.retry_jitter_fraction <= 0.50:
            raise ValueError(
                "Scheduler retry_jitter_fraction must be between 0.0 and 0.50."
            )
        if self.idle_poll_seconds <= 0:
            raise ValueError("Scheduler idle_poll_seconds must be positive.")


@dataclass(frozen=True, slots=True)
class SchedulerTickResult:
    """Observable result of one scheduler tick."""

    recovered_jobs: int
    scheduled_retries: int
    woken_jobs: int
    selected_job_id: uuid.UUID | None
    selected_job_type: str | None
    action: str
    final_state: JobState | None
    fencing_sequence: int | None
    retry_at_us: int | None = None

    @property
    def idle(self) -> bool:
        return self.selected_job_id is None


@dataclass(frozen=True, slots=True)
class SchedulerRunResult:
    """Aggregate result for a bounded queue-drain operation."""

    ticks: int
    dispatched_jobs: int
    completed_jobs: int
    waiting_jobs: int
    failed_jobs: int
    yielded_jobs: int
    idle: bool


class DurableJobScheduler:
    """Select persistent jobs, acquire fenced leases, and dispatch known workers."""

    def __init__(
        self,
        *,
        jobs: DurableJobService,
        source_worker: DurableSourceProcessingWorker,
        embedding_worker: DurableEmbeddingRebuildWorker,
        analysis_worker: DurableSourceAnalysisWorker | None = None,
        policy: SchedulerPolicy | None = None,
    ) -> None:
        self.jobs = jobs
        self.source_worker = source_worker
        self.embedding_worker = embedding_worker
        self.analysis_worker = analysis_worker
        self.policy = policy or SchedulerPolicy()

    @property
    def supported_job_types(self) -> frozenset[str]:
        return _SUPPORTED_JOB_TYPES

    def tick(
        self,
        *,
        worker_id: str,
        now_us: int | None = None,
    ) -> SchedulerTickResult:
        """Run one durable scheduler selection/dispatch cycle."""
        normalized_worker_id = worker_id.strip()
        if not normalized_worker_id:
            raise ValueError("Scheduler worker_id must not be empty.")
        now = utc_now_us() if now_us is None else now_us

        recovered = self.jobs.recover_startup(now_us=now)
        scheduled_retries = self._schedule_orphaned_retry_waiters(now)
        woken = self.jobs.wake_due_waiting(now_us=now)

        candidates = self.jobs.eligible_queued(
            now_us=now,
            job_types=_SUPPORTED_JOB_TYPES,
            limit=self.policy.candidate_limit,
        )
        ranked = sorted(candidates, key=lambda job: self._rank_key(job, now))

        leased: JobRecord | None = None
        for candidate in ranked:
            try:
                leased = self.jobs.acquire(
                    candidate.job_id,
                    worker_id=normalized_worker_id,
                    lease_seconds=self.policy.lease_seconds,
                    now_us=now,
                )
                break
            except JobTransitionError:
                # Another scheduler may have won the same persistent queue row.
                continue

        if leased is None:
            return SchedulerTickResult(
                recovered_jobs=len(recovered),
                scheduled_retries=scheduled_retries,
                woken_jobs=len(woken),
                selected_job_id=None,
                selected_job_type=None,
                action="idle",
                final_state=None,
                fencing_sequence=None,
            )
        if leased.lease_token is None:
            raise JobSchedulerError(
                f"Scheduler acquired job {leased.job_id} without a lease token."
            )

        logger.info(
            "Scheduler dispatched durable job",
            extra={
                "event": "jobs.scheduler_dispatched",
                "job_id": str(leased.job_id),
                "job_type": leased.job_type,
                "worker_id": normalized_worker_id,
                "fencing_sequence": leased.fencing_sequence,
            },
        )
        try:
            action, current = self._dispatch(leased)
        except JobLeaseError:
            # Lease expiry/loss is an expected distributed-scheduler race, not
            # a reason to terminate the long-lived scheduler process. Fencing
            # has already prevented the stale worker from committing its job
            # checkpoint; report the persisted state and continue next tick.
            current = self.jobs.get(leased.job_id)
            action = "lost_lease"
            logger.warning(
                "Scheduler worker lost durable job lease",
                extra={
                    "event": "jobs.scheduler_lease_lost",
                    "job_id": str(leased.job_id),
                    "job_type": leased.job_type,
                    "worker_id": normalized_worker_id,
                    "fencing_sequence": leased.fencing_sequence,
                },
            )
        retry_at_us: int | None = None
        if current.state is JobState.WAITING:
            current, retry_at_us = self._schedule_retry_if_allowed(current, now)
            action = "waiting"

        return SchedulerTickResult(
            recovered_jobs=len(recovered),
            scheduled_retries=scheduled_retries,
            woken_jobs=len(woken),
            selected_job_id=current.job_id,
            selected_job_type=current.job_type,
            action=action,
            final_state=current.state,
            fencing_sequence=current.fencing_sequence,
            retry_at_us=retry_at_us,
        )

    def drain(
        self,
        *,
        worker_id: str,
        max_jobs: int = 100,
    ) -> SchedulerRunResult:
        """Process currently eligible work until idle or a bounded job count is reached."""
        if max_jobs <= 0:
            raise ValueError("Scheduler max_jobs must be positive.")
        ticks = 0
        dispatched = 0
        completed = 0
        waiting = 0
        failed = 0
        yielded = 0
        idle = False

        while dispatched < max_jobs:
            result = self.tick(worker_id=worker_id)
            ticks += 1
            if result.idle:
                idle = True
                break
            dispatched += 1
            if result.final_state is JobState.COMPLETED:
                completed += 1
            elif result.final_state is JobState.WAITING:
                waiting += 1
            elif result.final_state is JobState.FAILED:
                failed += 1
            elif result.action == "yielded":
                yielded += 1

        return SchedulerRunResult(
            ticks=ticks,
            dispatched_jobs=dispatched,
            completed_jobs=completed,
            waiting_jobs=waiting,
            failed_jobs=failed,
            yielded_jobs=yielded,
            idle=idle,
        )

    def run_loop(
        self,
        *,
        worker_id: str,
        max_ticks: int | None = None,
    ) -> SchedulerRunResult:
        """Run a low-frequency persistent scheduler loop until interrupted/bounded."""
        if max_ticks is not None and max_ticks <= 0:
            raise ValueError("Scheduler max_ticks must be positive when provided.")
        ticks = 0
        dispatched = 0
        completed = 0
        waiting = 0
        failed = 0
        yielded = 0
        last_idle = False

        while max_ticks is None or ticks < max_ticks:
            result = self.tick(worker_id=worker_id)
            ticks += 1
            last_idle = result.idle
            if result.idle:
                time.sleep(self.policy.idle_poll_seconds)
                continue
            dispatched += 1
            if result.final_state is JobState.COMPLETED:
                completed += 1
            elif result.final_state is JobState.WAITING:
                waiting += 1
            elif result.final_state is JobState.FAILED:
                failed += 1
            elif result.action == "yielded":
                yielded += 1

        return SchedulerRunResult(
            ticks=ticks,
            dispatched_jobs=dispatched,
            completed_jobs=completed,
            waiting_jobs=waiting,
            failed_jobs=failed,
            yielded_jobs=yielded,
            idle=last_idle,
        )

    def _dispatch(self, leased: JobRecord) -> tuple[str, JobRecord]:
        lease_token = leased.lease_token
        if lease_token is None:
            raise JobSchedulerError("Dispatch requires a live lease token.")
        try:
            if leased.job_type == "source.process":
                return self._dispatch_source(leased.job_id, lease_token)
            if leased.job_type == "embedding.rebuild":
                return self._dispatch_embedding(leased.job_id, lease_token)
            if leased.job_type == "source.analyze":
                if self.analysis_worker is None:
                    raise JobSchedulerError("No source.analyze worker is configured.")
                return self._dispatch_analysis(leased.job_id, lease_token)
            raise JobSchedulerError(
                f"No scheduler dispatcher registered for {leased.job_type!r}."
            )
        except (JobLeaseError, JobTransitionError):
            raise
        except (
            SourceProcessingJobError,
            EmbeddingRebuildJobError,
            SourceAnalysisJobError,
        ) as exc:
            return "failed", self._fail_if_still_leased(
                leased.job_id,
                lease_token,
                reason=f"scheduler_dispatch:{type(exc).__name__}",
            )
        except Exception as exc:
            return "failed", self._fail_if_still_leased(
                leased.job_id,
                lease_token,
                reason=f"scheduler_unexpected:{type(exc).__name__}",
            )

    def _dispatch_source(
        self,
        job_id: uuid.UUID,
        lease_token: bytes,
    ) -> tuple[str, JobRecord]:
        for _ in range(self.policy.max_boundaries_per_dispatch):
            result = self.source_worker.step(
                job_id,
                lease_token=lease_token,
                extend_seconds=self.policy.lease_seconds,
            )
            if result.done:
                return "completed", result.job
        return self._yield_at_boundary(job_id, lease_token)

    def _dispatch_embedding(
        self,
        job_id: uuid.UUID,
        lease_token: bytes,
    ) -> tuple[str, JobRecord]:
        for _ in range(self.policy.max_boundaries_per_dispatch):
            result = self.embedding_worker.step(
                job_id,
                lease_token=lease_token,
                extend_seconds=self.policy.lease_seconds,
            )
            if result.done:
                return "completed", result.job
            if result.waiting:
                return "waiting", result.job
        return self._yield_at_boundary(job_id, lease_token)

    def _dispatch_analysis(
        self,
        job_id: uuid.UUID,
        lease_token: bytes,
    ) -> tuple[str, JobRecord]:
        if self.analysis_worker is None:
            raise JobSchedulerError("No source.analyze worker is configured.")
        for _ in range(self.policy.max_boundaries_per_dispatch):
            result = self.analysis_worker.step(
                job_id,
                lease_token=lease_token,
                extend_seconds=self.policy.lease_seconds,
            )
            if result.done:
                return "completed", result.job
            if result.waiting:
                return "waiting", result.job
        return self._yield_at_boundary(job_id, lease_token)

    def _yield_at_boundary(
        self,
        job_id: uuid.UUID,
        lease_token: bytes,
    ) -> tuple[str, JobRecord]:
        current = self.jobs.get(job_id)
        if current.state is JobState.CANCEL_REQUESTED:
            if current.job_type == "source.process":
                source_result = self.source_worker.step(
                    job_id,
                    lease_token=lease_token,
                    extend_seconds=self.policy.lease_seconds,
                )
                return "cancelled", source_result.job
            if current.job_type == "embedding.rebuild":
                embedding_result = self.embedding_worker.step(
                    job_id,
                    lease_token=lease_token,
                    extend_seconds=self.policy.lease_seconds,
                )
                return "cancelled", embedding_result.job
            if current.job_type == "source.analyze":
                if self.analysis_worker is None:
                    raise JobSchedulerError("No source.analyze worker is configured.")
                analysis_result = self.analysis_worker.step(
                    job_id,
                    lease_token=lease_token,
                    extend_seconds=self.policy.lease_seconds,
                )
                return "cancelled", analysis_result.job
        yielded = self.jobs.yield_job(job_id, lease_token=lease_token)
        return "yielded", yielded

    def _fail_if_still_leased(
        self,
        job_id: uuid.UUID,
        lease_token: bytes,
        *,
        reason: str,
    ) -> JobRecord:
        try:
            return self.jobs.fail(
                job_id,
                lease_token=lease_token,
                blocked_reason=reason,
            )
        except JobLeaseError:
            return self.jobs.get(job_id)

    def _schedule_orphaned_retry_waiters(self, now_us: int) -> int:
        scheduled = 0
        waiting_jobs = self.jobs.waiting(limit=self.policy.candidate_limit)
        for job in waiting_jobs:
            if job.blocked_reason not in _AUTO_RETRY_REASONS:
                continue
            if job.next_run_at_us is not None:
                continue
            updated, _retry_at = self._schedule_retry_if_allowed(job, now_us)
            if (
                updated.next_run_at_us is not None
                or updated.blocked_reason == WaitingReason.USER.value
            ):
                scheduled += 1
        return scheduled

    def _schedule_retry_if_allowed(
        self,
        job: JobRecord,
        now_us: int,
    ) -> tuple[JobRecord, int | None]:
        if job.state is not JobState.WAITING:
            return job, None
        if job.blocked_reason not in _AUTO_RETRY_REASONS:
            return job, job.next_run_at_us
        if job.next_run_at_us is not None:
            return job, job.next_run_at_us

        delay_us = self._retry_delay_us(job)
        retry_at = now_us + delay_us
        scheduled = self.jobs.schedule_retry(
            job.job_id,
            next_run_at_us=retry_at,
            max_retries=self.policy.retry_budget,
            now_us=now_us,
        )
        return scheduled, scheduled.next_run_at_us

    def _retry_delay_us(self, job: JobRecord) -> int:
        exponent = min(job.retry_count, 30)
        raw_seconds: int = min(
            int(self.policy.retry_max_seconds),
            int(self.policy.retry_base_seconds) * (2 ** int(exponent)),
        )
        jitter = self.policy.retry_jitter_fraction
        if jitter == 0:
            return raw_seconds * 1_000_000
        digest = hashlib.sha256(
            job.job_id.bytes + job.retry_count.to_bytes(8, "big", signed=False)
        ).digest()
        fraction = int.from_bytes(digest[:8], "big") / float(2**64 - 1)
        multiplier = (1.0 - jitter) + (2.0 * jitter * fraction)
        return max(1, int(raw_seconds * multiplier * 1_000_000))

    def _rank_key(self, job: JobRecord, now_us: int) -> tuple[int, int, int, bytes]:
        age_us = max(0, now_us - job.created_at_us)
        aging_steps = age_us // (self.policy.fairness_aging_seconds * 1_000_000)
        base_priority = int(job.priority)
        if base_priority == 0:
            effective_priority = 0
        else:
            # P0 remains reserved for data-safety. Aging can promote old work
            # through the remaining classes so background jobs cannot starve.
            effective_priority = max(1, base_priority - int(aging_steps))
        eligible_at = job.next_run_at_us or job.created_at_us
        return (
            effective_priority,
            eligible_at,
            job.created_at_us,
            job.job_id.bytes,
        )
