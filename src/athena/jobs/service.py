"""Application-facing durable job use cases."""

from __future__ import annotations

import json
import secrets
import sqlite3
import uuid
from collections.abc import Callable, Mapping
from typing import Any

from athena.chat.service import ChatService
from athena.jobs.models import (
    CheckpointRecord,
    JobPriority,
    JobRecord,
    WaitingReason,
)
from athena.jobs.repository import JobRepository


class UnsupportedJobTypeError(ValueError):
    """Raised when a caller tries to persist an unregistered job type."""


class InvalidJobPayloadError(ValueError):
    """Raised when durable job JSON cannot be canonicalized safely."""


class DurableJobService:
    """Validated durable job orchestration without an in-memory queue."""

    BUILTIN_JOB_TYPES = frozenset(
        {
            "archive.replicate",
            "backup.create",
            "source.process",
            "source.analyze",
            "source.extract",
            "source.represent",
            "source.chunk",
            "search.rebuild",
            "embedding.rebuild",
            "integrity.sweep",
            "research.exhaustive",
        }
    )

    def __init__(self, repository: JobRepository, chat: ChatService) -> None:
        self.repository = repository
        self.chat = chat

    def create(
        self,
        *,
        job_type: str,
        priority: JobPriority = JobPriority.NORMAL,
        requested_scope: Mapping[str, Any] | None = None,
        pinned_configuration: Mapping[str, Any] | None = None,
        next_run_at_us: int | None = None,
    ) -> JobRecord:
        if job_type not in self.BUILTIN_JOB_TYPES:
            raise UnsupportedJobTypeError(
                f"Unregistered ATHENA job type {job_type!r}."
            )
        actor_id = self.chat.ensure_local_user()
        return self.repository.create(
            job_type=job_type,
            actor_id=actor_id,
            priority=priority,
            requested_scope_json=_canonical_json(requested_scope),
            pinned_configuration_json=_canonical_json(pinned_configuration),
            next_run_at_us=next_run_at_us,
        )


    def active_for_type(
        self,
        job_type: str,
        *,
        limit: int = 16,
    ) -> tuple[JobRecord, ...]:
        """Return nonterminal jobs for one registered durable job type."""
        if job_type not in self.BUILTIN_JOB_TYPES:
            raise UnsupportedJobTypeError(
                f"Unregistered ATHENA job type {job_type!r}."
            )
        return self.repository.list_nonterminal_by_type(
            job_type=job_type,
            limit=limit,
        )

    def acquire(
        self,
        job_id: uuid.UUID,
        *,
        worker_id: str,
        lease_seconds: int = 60,
        now_us: int | None = None,
    ) -> JobRecord:
        return self.repository.acquire_lease(
            job_id=job_id,
            worker_id=worker_id,
            lease_token=secrets.token_bytes(32),
            lease_duration_us=lease_seconds * 1_000_000,
            now_us=now_us,
        )

    def heartbeat(
        self,
        job_id: uuid.UUID,
        *,
        lease_token: bytes,
        extend_seconds: int = 60,
        now_us: int | None = None,
    ) -> JobRecord:
        return self.repository.heartbeat(
            job_id=job_id,
            lease_token=lease_token,
            extend_by_us=extend_seconds * 1_000_000,
            now_us=now_us,
        )

    def canonical_write_fence(
        self,
        job_id: uuid.UUID,
        *,
        lease_token: bytes,
    ) -> Callable[[sqlite3.Connection], None]:
        """Return a lease fence for one canonical write transaction."""

        def fence(connection: sqlite3.Connection) -> None:
            self.repository.require_live_write_fence(
                connection,
                job_id=job_id,
                lease_token=lease_token,
            )

        return fence

    def checkpoint(
        self,
        job_id: uuid.UUID,
        *,
        lease_token: bytes,
        current_stage: str | None,
        progress_state: Mapping[str, Any] | None = None,
        last_confirmed_input: Mapping[str, Any] | None = None,
        last_confirmed_output: Mapping[str, Any] | None = None,
        resume_metadata: Mapping[str, Any] | None = None,
        processing_stage_id: uuid.UUID | None = None,
        commit_id: uuid.UUID | None = None,
        now_us: int | None = None,
    ) -> CheckpointRecord:
        return self.repository.add_checkpoint(
            job_id=job_id,
            lease_token=lease_token,
            processing_stage_id=processing_stage_id,
            progress_state_json=_canonical_json(progress_state),
            last_confirmed_input_json=_canonical_json(last_confirmed_input),
            last_confirmed_output_json=_canonical_json(last_confirmed_output),
            resume_metadata_json=_canonical_json(resume_metadata),
            commit_id=commit_id,
            current_stage=current_stage,
            now_us=now_us,
        )

    def recover_startup(self, *, now_us: int | None = None) -> tuple[JobRecord, ...]:
        """Recover only expired leases; live worker leases are never stolen."""
        return self.repository.recover_expired_leases(now_us=now_us)

    def get(self, job_id: uuid.UUID) -> JobRecord:
        return self.repository.get(job_id)

    def list(self, *, limit: int = 100) -> tuple[JobRecord, ...]:
        return self.repository.list(limit=limit)

    def eligible_queued(
        self,
        *,
        now_us: int,
        job_types: set[str] | frozenset[str] | None = None,
        limit: int = 128,
    ) -> tuple[JobRecord, ...]:
        return self.repository.list_eligible_queued(
            now_us=now_us,
            job_types=job_types,
            limit=limit,
        )

    def waiting(self, *, limit: int = 128) -> tuple[JobRecord, ...]:
        return self.repository.list_waiting(limit=limit)

    def wake_due_waiting(
        self,
        *,
        now_us: int | None = None,
    ) -> tuple[JobRecord, ...]:
        return self.repository.wake_due_waiting(now_us=now_us)

    def schedule_retry(
        self,
        job_id: uuid.UUID,
        *,
        next_run_at_us: int,
        max_retries: int,
        now_us: int | None = None,
    ) -> JobRecord:
        return self.repository.schedule_retry(
            job_id,
            next_run_at_us=next_run_at_us,
            max_retries=max_retries,
            now_us=now_us,
        )

    def yield_job(
        self,
        job_id: uuid.UUID,
        *,
        lease_token: bytes,
        next_run_at_us: int | None = None,
        now_us: int | None = None,
    ) -> JobRecord:
        return self.repository.yield_job(
            job_id=job_id,
            lease_token=lease_token,
            next_run_at_us=next_run_at_us,
            now_us=now_us,
        )

    def checkpoints(self, job_id: uuid.UUID) -> tuple[CheckpointRecord, ...]:
        return self.repository.list_checkpoints(job_id)

    def get_checkpoint(self, checkpoint_id: uuid.UUID) -> CheckpointRecord:
        return self.repository.get_checkpoint(checkpoint_id)

    def fail(
        self,
        job_id: uuid.UUID,
        *,
        lease_token: bytes,
        blocked_reason: str,
        now_us: int | None = None,
    ) -> JobRecord:
        return self.repository.fail(
            job_id=job_id,
            lease_token=lease_token,
            blocked_reason=blocked_reason,
            now_us=now_us,
        )

    def wait(
        self,
        job_id: uuid.UUID,
        *,
        lease_token: bytes,
        reason: WaitingReason,
        next_run_at_us: int | None = None,
        now_us: int | None = None,
    ) -> JobRecord:
        return self.repository.wait(
            job_id=job_id,
            lease_token=lease_token,
            reason=reason,
            next_run_at_us=next_run_at_us,
            now_us=now_us,
        )

    def wake(self, job_id: uuid.UUID) -> JobRecord:
        return self.repository.wake(job_id)

    def request_cancel(self, job_id: uuid.UUID) -> JobRecord:
        return self.repository.request_cancel(job_id)

    def pause(self, job_id: uuid.UUID) -> JobRecord:
        return self.repository.pause(job_id)

    def resume(self, job_id: uuid.UUID) -> JobRecord:
        return self.repository.resume(job_id)

    def complete(
        self,
        job_id: uuid.UUID,
        *,
        lease_token: bytes,
        now_us: int | None = None,
    ) -> JobRecord:
        return self.repository.complete(
            job_id=job_id,
            lease_token=lease_token,
            now_us=now_us,
        )

    def acknowledge_cancel(
        self,
        job_id: uuid.UUID,
        *,
        lease_token: bytes,
        now_us: int | None = None,
    ) -> JobRecord:
        return self.repository.acknowledge_cancel(
            job_id=job_id,
            lease_token=lease_token,
            now_us=now_us,
        )


def _canonical_json(value: Mapping[str, Any] | None) -> str | None:
    if value is None:
        return None
    try:
        return json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
    except (TypeError, ValueError) as exc:
        raise InvalidJobPayloadError("Job payload must be finite canonical JSON.") from exc
