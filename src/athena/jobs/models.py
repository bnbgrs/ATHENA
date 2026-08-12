"""Persistent job and checkpoint value objects."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from enum import Enum, IntEnum


class JobPriority(IntEnum):
    """Stable ATHENA priority classes; lower values run first."""

    DATA_SAFETY = 0
    INTERACTIVE = 1
    TIME_CRITICAL = 2
    NORMAL = 3
    BACKGROUND = 4
    MAINTENANCE = 5


class JobState(str, Enum):
    """Normative durable job states."""

    QUEUED = "queued"
    WAITING = "waiting"
    RUNNING = "running"
    PAUSED = "paused"
    CANCEL_REQUESTED = "cancel_requested"
    CANCELLED = "cancelled"
    FAILED = "failed"
    COMPLETED = "completed"

    @property
    def terminal(self) -> bool:
        return self in {self.CANCELLED, self.FAILED, self.COMPLETED}


class WaitingReason(str, Enum):
    """Machine-readable reasons for the generic waiting state."""

    RESOURCE = "waiting_resource"
    STORAGE = "waiting_storage"
    NETWORK = "waiting_network"
    DEPENDENCY = "waiting_dependency"
    SCHEDULE = "waiting_schedule"
    USER = "waiting_user"
    BACKOFF = "waiting_backoff"


@dataclass(frozen=True, slots=True)
class JobRecord:
    job_id: uuid.UUID
    job_type: str
    created_at_us: int
    created_by_actor_id: uuid.UUID
    priority: JobPriority
    state: JobState
    requested_scope_json: str | None
    processing_run_id: uuid.UUID | None
    current_stage: str | None
    last_checkpoint_id: uuid.UUID | None
    retry_count: int
    next_run_at_us: int | None
    blocked_reason: str | None
    pinned_configuration_json: str | None
    protection_scope_id: uuid.UUID | None
    protected_payload_id: uuid.UUID | None
    worker_id: str | None
    lease_token: bytes | None
    lease_acquired_at_us: int | None
    lease_expires_at_us: int | None
    heartbeat_at_us: int | None
    fencing_sequence: int
    updated_at_us: int

    @property
    def uri(self) -> str:
        return f"operational://job/{self.job_id}"


@dataclass(frozen=True, slots=True)
class CheckpointRecord:
    checkpoint_id: uuid.UUID
    job_id: uuid.UUID
    processing_stage_id: uuid.UUID | None
    created_at_us: int
    progress_state_json: str | None
    last_confirmed_input_json: str | None
    last_confirmed_output_json: str | None
    resume_metadata_json: str | None
    commit_id: uuid.UUID | None
    protection_scope_id: uuid.UUID | None
    protected_payload_id: uuid.UUID | None
    fencing_sequence: int

    @property
    def uri(self) -> str:
        return f"operational://checkpoint/{self.checkpoint_id}"
