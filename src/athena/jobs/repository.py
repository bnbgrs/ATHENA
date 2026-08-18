"""Transactional persistence for durable jobs and checkpoints."""

from __future__ import annotations

import json
import sqlite3
import uuid
from collections.abc import Callable, Iterable

from athena.common.ids import new_uuid7, uuid_from_blob, uuid_to_blob
from athena.common.time import utc_now_us
from athena.jobs.models import (
    CheckpointRecord,
    JobPriority,
    JobRecord,
    JobState,
    WaitingReason,
)
from athena.storage.database import SQLiteDatabase

CanonicalJobWriteFence = Callable[[sqlite3.Connection], None]
ProtectedOperationalPayloadWriter = Callable[[sqlite3.Connection, bytes], uuid.UUID]


class JobNotFoundError(LookupError):
    """Raised when a durable job does not exist."""


class CheckpointNotFoundError(LookupError):
    """Raised when a durable checkpoint does not exist."""


class JobLeaseError(RuntimeError):
    """Raised when a worker does not own the current live lease."""


class JobTransitionError(RuntimeError):
    """Raised for invalid durable job-state transitions."""


class JobSourceProtectionFenceError(JobTransitionError):
    """Raised when a new job depends on a protected or transitioning Source."""


class JobRepository:
    """Low-level durable job state with transactional fencing."""

    def __init__(self, database: SQLiteDatabase) -> None:
        self.database = database

    def create(
        self,
        *,
        job_type: str,
        actor_id: uuid.UUID,
        priority: JobPriority,
        requested_scope_json: str | None,
        pinned_configuration_json: str | None,
        next_run_at_us: int | None = None,
    ) -> JobRecord:
        job_id = new_uuid7()
        now_us = utc_now_us()
        with self.database.write_transaction() as connection:
            self._require_active_actor(connection, actor_id)
            _require_unprotected_job_dependencies(
                connection,
                requested_scope_json,
            )
            connection.execute(
                """
                INSERT INTO jobs (
                    job_id, job_type, created_at_us, created_by_actor_id,
                    priority, state, requested_scope_json, processing_run_id,
                    current_stage, last_checkpoint_id, retry_count,
                    next_run_at_us, blocked_reason, pinned_configuration_json,
                    protection_scope_id, protected_payload_id, worker_id,
                    lease_token, lease_acquired_at_us, lease_expires_at_us,
                    heartbeat_at_us, fencing_sequence, updated_at_us
                ) VALUES (
                    ?, ?, ?, ?, ?, 'queued', ?, NULL,
                    NULL, NULL, 0, ?, NULL, ?,
                    NULL, NULL, NULL, NULL, NULL, NULL,
                    NULL, 0, ?
                )
                """,
                (
                    uuid_to_blob(job_id),
                    job_type,
                    now_us,
                    uuid_to_blob(actor_id),
                    int(priority),
                    requested_scope_json,
                    next_run_at_us,
                    pinned_configuration_json,
                    now_us,
                ),
            )
        return self.get(job_id)

    def get(self, job_id: uuid.UUID) -> JobRecord:
        row = self.database.connection.execute(
            "SELECT * FROM jobs WHERE job_id = ?",
            (uuid_to_blob(job_id),),
        ).fetchone()
        if row is None:
            raise JobNotFoundError(str(job_id))
        return _job_from_row(row)

    def list(
        self,
        *,
        states: Iterable[JobState] | None = None,
        limit: int = 100,
    ) -> tuple[JobRecord, ...]:
        if limit <= 0:
            raise ValueError("Job list limit must be positive.")
        state_values = tuple(state.value for state in states or ())
        if state_values:
            placeholders = ", ".join("?" for _ in state_values)
            rows = self.database.connection.execute(
                f"""
                SELECT * FROM jobs
                WHERE state IN ({placeholders})
                ORDER BY priority ASC,
                         COALESCE(next_run_at_us, created_at_us) ASC,
                         created_at_us ASC,
                         job_id ASC
                LIMIT ?
                """,
                (*state_values, limit),
            ).fetchall()
        else:
            rows = self.database.connection.execute(
                """
                SELECT * FROM jobs
                ORDER BY created_at_us DESC, job_id DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return tuple(_job_from_row(row) for row in rows)

    def list_eligible_queued(
        self,
        *,
        now_us: int,
        job_types: Iterable[str] | None = None,
        limit: int = 128,
    ) -> tuple[JobRecord, ...]:
        """Return currently eligible queued jobs without claiming ownership."""
        if limit <= 0:
            raise ValueError("Eligible job limit must be positive.")
        type_values = tuple(job_types or ())
        params: list[object] = [now_us]
        type_clause = ""
        if type_values:
            placeholders = ", ".join("?" for _ in type_values)
            type_clause = f" AND job_type IN ({placeholders})"
            params.extend(type_values)
        params.append(limit)
        rows = self.database.connection.execute(
            f"""
            SELECT * FROM jobs
            WHERE state = 'queued'
              AND (next_run_at_us IS NULL OR next_run_at_us <= ?)
              {type_clause}
            ORDER BY priority ASC,
                     COALESCE(next_run_at_us, created_at_us) ASC,
                     created_at_us ASC,
                     job_id ASC
            LIMIT ?
            """,
            tuple(params),
        ).fetchall()
        return tuple(_job_from_row(row) for row in rows)


    def list_nonterminal_by_type(
        self,
        *,
        job_type: str,
        limit: int = 16,
    ) -> tuple[JobRecord, ...]:
        """Return durable nonterminal jobs of one exact registered type."""
        normalized_type = job_type.strip()
        if not normalized_type:
            raise ValueError("job_type must not be empty.")
        if limit <= 0:
            raise ValueError("Job lookup limit must be positive.")

        rows = self.database.connection.execute(
            """
            SELECT *
            FROM jobs
            WHERE job_type = ?
              AND state IN (
                  'queued',
                  'waiting',
                  'running',
                  'paused',
                  'cancel_requested'
              )
            ORDER BY created_at_us ASC, job_id ASC
            LIMIT ?
            """,
            (
                normalized_type,
                limit,
            ),
        ).fetchall()

        return tuple(
            _job_from_row(row)
            for row in rows
        )

    def list_waiting(self, *, limit: int = 128) -> tuple[JobRecord, ...]:
        """Return waiting jobs in deterministic oldest-first order."""
        if limit <= 0:
            raise ValueError("Waiting job limit must be positive.")
        rows = self.database.connection.execute(
            """
            SELECT * FROM jobs
            WHERE state = 'waiting'
            ORDER BY COALESCE(next_run_at_us, updated_at_us) ASC,
                     updated_at_us ASC, job_id ASC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
        return tuple(_job_from_row(row) for row in rows)

    def wake_due_waiting(
        self,
        *,
        now_us: int | None = None,
    ) -> tuple[JobRecord, ...]:
        """Wake timed retry/dependency waiters whose next run is due."""
        now = utc_now_us() if now_us is None else now_us
        woken_ids: list[uuid.UUID] = []
        with self.database.write_transaction() as connection:
            rows = connection.execute(
                """
                SELECT job_id
                FROM jobs
                WHERE state = 'waiting'
                  AND blocked_reason IN (
                      'waiting_resource', 'waiting_storage', 'waiting_network',
                      'waiting_schedule', 'waiting_dependency', 'waiting_backoff'
                  )
                  AND next_run_at_us IS NOT NULL
                  AND next_run_at_us <= ?
                ORDER BY next_run_at_us ASC, created_at_us ASC, job_id ASC
                """,
                (now,),
            ).fetchall()
            for row in rows:
                job_id = uuid_from_blob(bytes(row["job_id"]))
                connection.execute(
                    """
                    UPDATE jobs
                    SET state = 'queued', blocked_reason = NULL,
                        next_run_at_us = CASE
                            WHEN blocked_reason = 'waiting_dependency'
                            THEN next_run_at_us
                            ELSE NULL
                        END,
                        updated_at_us = ?
                    WHERE job_id = ? AND state = 'waiting'
                    """,
                    (now, uuid_to_blob(job_id)),
                )
                woken_ids.append(job_id)
        return tuple(self.get(job_id) for job_id in woken_ids)

    def schedule_retry(
        self,
        job_id: uuid.UUID,
        *,
        next_run_at_us: int,
        max_retries: int,
        now_us: int | None = None,
    ) -> JobRecord:
        """Assign bounded automatic retry timing to a retryable waiting job."""
        if max_retries < 0:
            raise ValueError("max_retries must not be negative.")
        now = utc_now_us() if now_us is None else now_us
        if next_run_at_us <= now:
            raise ValueError("Retry time must be in the future.")
        with self.database.write_transaction() as connection:
            row = self._require_job_row(connection, job_id)
            state = JobState(str(row["state"]))
            if state is not JobState.WAITING:
                raise JobTransitionError(
                    f"Job {job_id} cannot schedule retry from state {state.value!r}."
                )
            reason = str(row["blocked_reason"])
            retryable = {
                WaitingReason.NETWORK.value,
                WaitingReason.RESOURCE.value,
                WaitingReason.STORAGE.value,
                WaitingReason.BACKOFF.value,
            }
            if reason not in retryable:
                raise JobTransitionError(
                    f"Job {job_id} waiting reason {reason!r} is not timer-retryable."
                )
            # Multiple scheduler processes may observe the same waiter before
            # either has assigned its backoff. Re-read under BEGIN IMMEDIATE
            # and make retry scheduling idempotent so one failure consumes
            # exactly one retry-budget slot.
            if row["next_run_at_us"] is not None:
                return _job_from_row(row)
            retry_count = int(row["retry_count"])
            if retry_count >= max_retries:
                connection.execute(
                    """
                    UPDATE jobs
                    SET blocked_reason = 'waiting_user', next_run_at_us = NULL,
                        updated_at_us = ?
                    WHERE job_id = ?
                    """,
                    (now, uuid_to_blob(job_id)),
                )
            else:
                connection.execute(
                    """
                    UPDATE jobs
                    SET retry_count = ?, next_run_at_us = ?, updated_at_us = ?
                    WHERE job_id = ?
                    """,
                    (retry_count + 1, next_run_at_us, now, uuid_to_blob(job_id)),
                )
        return self.get(job_id)

    def acquire_lease(
        self,
        *,
        job_id: uuid.UUID,
        worker_id: str,
        lease_token: bytes,
        lease_duration_us: int,
        now_us: int | None = None,
    ) -> JobRecord:
        if len(lease_token) != 32:
            raise ValueError("Job lease tokens must contain exactly 32 bytes.")
        if not worker_id.strip():
            raise ValueError("worker_id must not be empty.")
        if lease_duration_us <= 0:
            raise ValueError("lease_duration_us must be positive.")
        now = utc_now_us() if now_us is None else now_us
        expires = now + lease_duration_us

        with self.database.write_transaction() as connection:
            row = self._require_job_row(connection, job_id)
            state = JobState(str(row["state"]))
            if state is not JobState.QUEUED:
                raise JobTransitionError(
                    f"Job {job_id} cannot acquire a lease from state {state.value!r}."
                )
            next_run_at = row["next_run_at_us"]
            if next_run_at is not None and int(next_run_at) > now:
                raise JobTransitionError(f"Job {job_id} is not eligible yet.")
            fencing_sequence = int(row["fencing_sequence"]) + 1
            connection.execute(
                """
                UPDATE jobs
                SET state = 'running', worker_id = ?, lease_token = ?,
                    lease_acquired_at_us = ?, lease_expires_at_us = ?,
                    heartbeat_at_us = ?, fencing_sequence = ?,
                    blocked_reason = NULL, updated_at_us = ?
                WHERE job_id = ?
                """,
                (
                    worker_id,
                    lease_token,
                    now,
                    expires,
                    now,
                    fencing_sequence,
                    now,
                    uuid_to_blob(job_id),
                ),
            )
        return self.get(job_id)

    def heartbeat(
        self,
        *,
        job_id: uuid.UUID,
        lease_token: bytes,
        extend_by_us: int,
        now_us: int | None = None,
    ) -> JobRecord:
        if extend_by_us <= 0:
            raise ValueError("extend_by_us must be positive.")
        now = utc_now_us() if now_us is None else now_us
        with self.database.write_transaction() as connection:
            row = self._require_live_lease(connection, job_id, lease_token, now)
            state = JobState(str(row["state"]))
            if state not in {JobState.RUNNING, JobState.CANCEL_REQUESTED}:
                raise JobLeaseError(
                    f"Job {job_id} is not heartbeat-eligible in state {state.value!r}."
                )

            lease_acquired_at = row["lease_acquired_at_us"]
            lease_expires_at = row["lease_expires_at_us"]
            heartbeat_at = row["heartbeat_at_us"]
            if lease_acquired_at is None or lease_expires_at is None:
                raise JobLeaseError(f"Job {job_id} has incomplete lease timestamps.")

            effective_now = max(
                now,
                int(lease_acquired_at),
                (
                    int(heartbeat_at)
                    if heartbeat_at is not None
                    else int(lease_acquired_at)
                ),
            )
            next_expires_at = max(
                int(lease_expires_at),
                effective_now + extend_by_us,
            )
            connection.execute(
                """
                UPDATE jobs
                SET heartbeat_at_us = ?, lease_expires_at_us = ?, updated_at_us = ?
                WHERE job_id = ?
                """,
                (
                    effective_now,
                    next_expires_at,
                    effective_now,
                    uuid_to_blob(job_id),
                ),
            )
        return self.get(job_id)

    def require_live_write_fence(
        self,
        connection: sqlite3.Connection,
        *,
        job_id: uuid.UUID,
        lease_token: bytes,
        now_us: int | None = None,
    ) -> None:
        """Fence one canonical write inside its active transaction."""
        if not connection.in_transaction:
            raise RuntimeError(
                "Canonical job write fence requires an active transaction."
            )

        now = utc_now_us() if now_us is None else now_us
        row = self._require_live_lease(
            connection,
            job_id,
            lease_token,
            now,
        )
        state = JobState(str(row["state"]))

        if state is not JobState.RUNNING:
            raise JobLeaseError(
                f"Job {job_id} cannot publish canonical state "
                f"in state {state.value!r}."
            )

    def add_checkpoint(
        self,
        *,
        job_id: uuid.UUID,
        lease_token: bytes,
        processing_stage_id: uuid.UUID | None,
        progress_state_json: str | None,
        last_confirmed_input_json: str | None,
        last_confirmed_output_json: str | None,
        resume_metadata_json: str | None,
        commit_id: uuid.UUID | None,
        current_stage: str | None,
        now_us: int | None = None,
    ) -> CheckpointRecord:
        now = utc_now_us() if now_us is None else now_us
        checkpoint_id = new_uuid7()
        with self.database.write_transaction() as connection:
            row = self._require_live_lease(connection, job_id, lease_token, now)
            state = JobState(str(row["state"]))
            if state is not JobState.RUNNING:
                raise JobLeaseError(
                    f"Job {job_id} cannot checkpoint in state {state.value!r}."
                )
            if commit_id is not None:
                commit_row = connection.execute(
                    "SELECT 1 FROM commit_records WHERE commit_id = ?",
                    (uuid_to_blob(commit_id),),
                ).fetchone()
                if commit_row is None:
                    raise ValueError(
                        "Checkpoint commit_id must reference an existing durable commit."
                    )
            fencing_sequence = int(row["fencing_sequence"])
            # Windows can expose the same microsecond timestamp to consecutive
            # checkpoint commits. Keep the persisted per-job ordering strict so
            # list_checkpoints() never falls back to random UUIDv7 tie bits.
            previous = connection.execute(
                """
                SELECT MAX(created_at_us) AS created_at_us
                FROM checkpoints
                WHERE job_id = ?
                """,
                (uuid_to_blob(job_id),),
            ).fetchone()
            previous_created_at_us = (
                None if previous is None or previous["created_at_us"] is None
                else int(previous["created_at_us"])
            )
            checkpoint_created_at_us = (
                now
                if previous_created_at_us is None
                else max(now, previous_created_at_us + 1)
            )
            connection.execute(
                """
                INSERT INTO checkpoints (
                    checkpoint_id, job_id, processing_stage_id, created_at_us,
                    progress_state_json, last_confirmed_input_json,
                    last_confirmed_output_json, resume_metadata_json, commit_id,
                    protection_scope_id, protected_payload_id, fencing_sequence
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, NULL, ?)
                """,
                (
                    uuid_to_blob(checkpoint_id),
                    uuid_to_blob(job_id),
                    _maybe_uuid_blob(processing_stage_id),
                    checkpoint_created_at_us,
                    progress_state_json,
                    last_confirmed_input_json,
                    last_confirmed_output_json,
                    resume_metadata_json,
                    _maybe_uuid_blob(commit_id),
                    fencing_sequence,
                ),
            )
            connection.execute(
                """
                UPDATE jobs
                SET last_checkpoint_id = ?, current_stage = ?, updated_at_us = ?
                WHERE job_id = ?
                """,
                (
                    uuid_to_blob(checkpoint_id),
                    current_stage,
                    checkpoint_created_at_us,
                    uuid_to_blob(job_id),
                ),
            )
        return self.get_checkpoint(checkpoint_id)

    def get_checkpoint(self, checkpoint_id: uuid.UUID) -> CheckpointRecord:
        row = self.database.connection.execute(
            "SELECT * FROM checkpoints WHERE checkpoint_id = ?",
            (uuid_to_blob(checkpoint_id),),
        ).fetchone()
        if row is None:
            raise CheckpointNotFoundError(str(checkpoint_id))
        return _checkpoint_from_row(row)

    def list_checkpoints(self, job_id: uuid.UUID) -> tuple[CheckpointRecord, ...]:
        self.get(job_id)
        rows = self.database.connection.execute(
            """
            SELECT * FROM checkpoints
            WHERE job_id = ?
            ORDER BY created_at_us ASC, checkpoint_id ASC
            """,
            (uuid_to_blob(job_id),),
        ).fetchall()
        return tuple(_checkpoint_from_row(row) for row in rows)

    def wait(
        self,
        *,
        job_id: uuid.UUID,
        lease_token: bytes,
        reason: WaitingReason,
        next_run_at_us: int | None = None,
        now_us: int | None = None,
    ) -> JobRecord:
        now = utc_now_us() if now_us is None else now_us
        with self.database.write_transaction() as connection:
            row = self._require_live_lease(connection, job_id, lease_token, now)
            state = JobState(str(row["state"]))
            if state is not JobState.RUNNING:
                raise JobTransitionError(
                    f"Job {job_id} cannot wait from state {state.value!r}."
                )
            connection.execute(
                """
                UPDATE jobs
                SET state = 'waiting', blocked_reason = ?, next_run_at_us = ?,
                    worker_id = NULL, lease_token = NULL,
                    lease_acquired_at_us = NULL, lease_expires_at_us = NULL,
                    heartbeat_at_us = NULL, updated_at_us = ?
                WHERE job_id = ?
                """,
                (reason.value, next_run_at_us, now, uuid_to_blob(job_id)),
            )
        return self.get(job_id)

    def wake(self, job_id: uuid.UUID) -> JobRecord:
        now = utc_now_us()
        with self.database.write_transaction() as connection:
            row = self._require_job_row(connection, job_id)
            state = JobState(str(row["state"]))
            if state is not JobState.WAITING:
                raise JobTransitionError(
                    f"Job {job_id} cannot wake from state {state.value!r}."
                )
            connection.execute(
                """
                UPDATE jobs
                SET state = 'queued', blocked_reason = NULL, next_run_at_us = NULL,
                    updated_at_us = ?
                WHERE job_id = ?
                """,
                (now, uuid_to_blob(job_id)),
            )
        return self.get(job_id)

    def request_cancel(self, job_id: uuid.UUID) -> JobRecord:
        now = utc_now_us()
        with self.database.write_transaction() as connection:
            row = self._require_job_row(connection, job_id)
            self._request_cancel_row(
                connection,
                row=row,
                now_us=now,
            )
        return self.get(job_id)

    def fence_source_dependencies(
        self,
        connection: sqlite3.Connection,
        *,
        source_id: uuid.UUID,
        now_us: int | None = None,
    ) -> tuple[uuid.UUID, ...]:
        """Fence every nonterminal durable job that depends on one Source."""
        if not connection.in_transaction:
            raise RuntimeError(
                "Source dependency fencing requires an active transaction."
            )

        now = utc_now_us() if now_us is None else now_us

        rows = connection.execute(
            """
            SELECT *
            FROM jobs
            WHERE state IN (
                'queued',
                'waiting',
                'running',
                'paused',
                'cancel_requested'
            )
            ORDER BY created_at_us ASC, job_id ASC
            """
        ).fetchall()

        fenced_ids: list[uuid.UUID] = []

        for row in rows:
            dependencies = _job_source_dependency_ids(
                connection,
                _maybe_text(
                    row["requested_scope_json"]
                ),
            )

            if source_id not in dependencies:
                continue

            job_id = uuid_from_blob(
                bytes(
                    row["job_id"]
                )
            )

            self._request_cancel_row(
                connection,
                row=row,
                now_us=now,
            )

            fenced_ids.append(
                job_id
            )

        return tuple(
            fenced_ids
        )

    def protect_source_dependency_payloads(
        self,
        connection: sqlite3.Connection,
        *,
        source_id: uuid.UUID,
        protection_scope_id: uuid.UUID,
        payload_writer: ProtectedOperationalPayloadWriter,
        now_us: int | None = None,
    ) -> tuple[
        tuple[uuid.UUID, ...],
        tuple[uuid.UUID, ...],
    ]:
        """Fence and protect durable operational state for one Source."""
        if not connection.in_transaction:
            raise RuntimeError(
                "Protected operational-state cutover "
                "requires an active transaction."
            )

        now = (
            utc_now_us()
            if now_us is None
            else now_us
        )

        self.fence_source_dependencies(
            connection,
            source_id=source_id,
            now_us=now,
        )

        rows = connection.execute(
            """
            SELECT *
            FROM jobs
            ORDER BY created_at_us ASC,
                     job_id ASC
            """
        ).fetchall()

        migrated: list[
            uuid.UUID
        ] = []

        blockers: list[
            uuid.UUID
        ] = []

        for row in rows:
            requested_scope = _maybe_text(
                row[
                    "requested_scope_json"
                ]
            )

            # A row already migrated to a protected
            # payload has no public requested scope
            # left and therefore needs no second pass.
            if requested_scope is None:
                continue

            dependencies = (
                _job_source_dependency_ids(
                    connection,
                    requested_scope,
                )
            )

            if source_id not in dependencies:
                continue

            job_id = uuid_from_blob(
                bytes(
                    row["job_id"]
                )
            )

            current = connection.execute(
                """
                SELECT *
                FROM jobs
                WHERE job_id = ?
                """,
                (
                    uuid_to_blob(
                        job_id
                    ),
                ),
            ).fetchone()

            if current is None:
                raise JobNotFoundError(
                    str(job_id)
                )

            state = JobState(
                str(
                    current["state"]
                )
            )

            if (
                state
                is JobState.CANCEL_REQUESTED
            ):
                # The worker still owns its lease.
                # Keep its scope intact until it has
                # acknowledged cancellation (or lease
                # recovery terminalizes it), otherwise
                # worker contract validation can fail
                # before the cancel branch is reached.
                blockers.append(
                    job_id
                )
                continue

            if not state.terminal:
                raise JobTransitionError(
                    f"Source dependency fence left "
                    f"job {job_id} nonterminal in "
                    f"state {state.value!r}."
                )

            self._protect_checkpoint_payloads(
                connection,
                job_id=job_id,
                protection_scope_id=(
                    protection_scope_id
                ),
                payload_writer=(
                    payload_writer
                ),
            )

            self._protect_job_payload(
                connection,
                row=current,
                protection_scope_id=(
                    protection_scope_id
                ),
                payload_writer=(
                    payload_writer
                ),
                now_us=now,
            )

            migrated.append(
                job_id
            )

        return (
            tuple(migrated),
            tuple(blockers),
        )

    def _protect_job_payload(
        self,
        connection: sqlite3.Connection,
        *,
        row: sqlite3.Row,
        protection_scope_id: uuid.UUID,
        payload_writer: ProtectedOperationalPayloadWriter,
        now_us: int,
    ) -> None:
        job_id = uuid_from_blob(
            bytes(
                row["job_id"]
            )
        )

        stored_scope = _maybe_uuid(
            row[
                "protection_scope_id"
            ]
        )

        stored_payload = _maybe_uuid(
            row[
                "protected_payload_id"
            ]
        )

        if (
            stored_scope is not None
            or stored_payload is not None
        ):
            if (
                stored_scope
                == protection_scope_id
                and stored_payload
                is not None
            ):
                return

            raise JobTransitionError(
                f"Job {job_id} has inconsistent "
                "Protected Content ownership."
            )

        payload = (
            _protected_operational_json(
                payload_type=(
                    "athena.job.operational.v1"
                ),
                values={
                    "requested_scope_json": (
                        _maybe_text(
                            row[
                                "requested_scope_json"
                            ]
                        )
                    ),
                    "pinned_configuration_json": (
                        _maybe_text(
                            row[
                                "pinned_configuration_json"
                            ]
                        )
                    ),
                    "blocked_reason": (
                        _maybe_text(
                            row[
                                "blocked_reason"
                            ]
                        )
                    ),
                },
            )
        )

        protected_payload_id = (
            payload_writer(
                connection,
                payload,
            )
        )

        updated = connection.execute(
            """
            UPDATE jobs
            SET requested_scope_json = NULL,
                pinned_configuration_json = NULL,
                blocked_reason = NULL,
                protection_scope_id = ?,
                protected_payload_id = ?,
                updated_at_us = ?
            WHERE job_id = ?
              AND protection_scope_id IS NULL
              AND protected_payload_id IS NULL
            """,
            (
                uuid_to_blob(
                    protection_scope_id
                ),
                uuid_to_blob(
                    protected_payload_id
                ),
                now_us,
                uuid_to_blob(
                    job_id
                ),
            ),
        )

        if updated.rowcount != 1:
            raise JobTransitionError(
                f"Job {job_id} lost its "
                "operational-state cutover fence."
            )

    def _protect_checkpoint_payloads(
        self,
        connection: sqlite3.Connection,
        *,
        job_id: uuid.UUID,
        protection_scope_id: uuid.UUID,
        payload_writer: ProtectedOperationalPayloadWriter,
    ) -> None:
        rows = connection.execute(
            """
            SELECT *
            FROM checkpoints
            WHERE job_id = ?
            ORDER BY created_at_us ASC,
                     checkpoint_id ASC
            """,
            (
                uuid_to_blob(
                    job_id
                ),
            ),
        ).fetchall()

        for row in rows:
            checkpoint_id = uuid_from_blob(
                bytes(
                    row[
                        "checkpoint_id"
                    ]
                )
            )

            stored_scope = _maybe_uuid(
                row[
                    "protection_scope_id"
                ]
            )

            stored_payload = _maybe_uuid(
                row[
                    "protected_payload_id"
                ]
            )

            if (
                stored_scope is not None
                or stored_payload is not None
            ):
                if (
                    stored_scope
                    == protection_scope_id
                    and stored_payload
                    is not None
                ):
                    continue

                raise JobTransitionError(
                    f"Checkpoint "
                    f"{checkpoint_id} has "
                    "inconsistent Protected "
                    "Content ownership."
                )

            payload = (
                _protected_operational_json(
                    payload_type=(
                        "athena.checkpoint."
                        "operational.v1"
                    ),
                    values={
                        "progress_state_json": (
                            _maybe_text(
                                row[
                                    "progress_state_json"
                                ]
                            )
                        ),
                        "last_confirmed_input_json": (
                            _maybe_text(
                                row[
                                    "last_confirmed_input_json"
                                ]
                            )
                        ),
                        "last_confirmed_output_json": (
                            _maybe_text(
                                row[
                                    "last_confirmed_output_json"
                                ]
                            )
                        ),
                        "resume_metadata_json": (
                            _maybe_text(
                                row[
                                    "resume_metadata_json"
                                ]
                            )
                        ),
                    },
                )
            )

            protected_payload_id = (
                payload_writer(
                    connection,
                    payload,
                )
            )

            updated = connection.execute(
                """
                UPDATE checkpoints
                SET progress_state_json = NULL,
                    last_confirmed_input_json = NULL,
                    last_confirmed_output_json = NULL,
                    resume_metadata_json = NULL,
                    protection_scope_id = ?,
                    protected_payload_id = ?
                WHERE checkpoint_id = ?
                  AND protection_scope_id IS NULL
                  AND protected_payload_id IS NULL
                """,
                (
                    uuid_to_blob(
                        protection_scope_id
                    ),
                    uuid_to_blob(
                        protected_payload_id
                    ),
                    uuid_to_blob(
                        checkpoint_id
                    ),
                ),
            )

            if updated.rowcount != 1:
                raise JobTransitionError(
                    f"Checkpoint "
                    f"{checkpoint_id} lost its "
                    "operational-state "
                    "cutover fence."
                )

    def _request_cancel_row(
        self,
        connection: sqlite3.Connection,
        *,
        row: sqlite3.Row,
        now_us: int,
    ) -> JobState:
        job_id = uuid_from_blob(
            bytes(
                row["job_id"]
            )
        )

        state = JobState(
            str(
                row["state"]
            )
        )

        if state.terminal:
            raise JobTransitionError(
                f"Terminal job {job_id} cannot be cancelled again."
            )

        if state in {
            JobState.QUEUED,
            JobState.WAITING,
            JobState.PAUSED,
        }:
            target = JobState.CANCELLED

            self._update_state_and_clear_lease(
                connection,
                job_id,
                target,
                now_us,
            )

            return target

        if state is JobState.RUNNING:
            target = JobState.CANCEL_REQUESTED

            connection.execute(
                """
                UPDATE jobs
                SET state = ?,
                    updated_at_us = ?
                WHERE job_id = ?
                """,
                (
                    target.value,
                    now_us,
                    uuid_to_blob(
                        job_id
                    ),
                ),
            )

            return target

        if state is JobState.CANCEL_REQUESTED:
            return state

        raise JobTransitionError(
            f"Job {job_id} cannot be cancelled from {state.value!r}."
        )

    def pause(self, job_id: uuid.UUID) -> JobRecord:
        now = utc_now_us()
        with self.database.write_transaction() as connection:
            row = self._require_job_row(connection, job_id)
            state = JobState(str(row["state"]))
            if state not in {JobState.QUEUED, JobState.WAITING}:
                raise JobTransitionError(
                    "Step-1 pause is safe only before a worker owns the job; running "
                    "worker-coordinated pause arrives with the scheduler slice."
                )
            self._update_state_and_clear_lease(
                connection, job_id, JobState.PAUSED, now
            )
        return self.get(job_id)

    def resume(self, job_id: uuid.UUID) -> JobRecord:
        now = utc_now_us()
        with self.database.write_transaction() as connection:
            row = self._require_job_row(connection, job_id)
            state = JobState(str(row["state"]))
            if state is not JobState.PAUSED:
                raise JobTransitionError(
                    f"Job {job_id} cannot resume from state {state.value!r}."
                )
            connection.execute(
                """
                UPDATE jobs
                SET state = 'queued', blocked_reason = NULL, next_run_at_us = NULL,
                    updated_at_us = ?
                WHERE job_id = ?
                """,
                (now, uuid_to_blob(job_id)),
            )
        return self.get(job_id)

    def yield_job(
        self,
        *,
        job_id: uuid.UUID,
        lease_token: bytes,
        next_run_at_us: int | None = None,
        now_us: int | None = None,
    ) -> JobRecord:
        """Release one live job back to queued at a confirmed safe boundary."""
        now = utc_now_us() if now_us is None else now_us
        with self.database.write_transaction() as connection:
            row = self._require_live_lease(connection, job_id, lease_token, now)
            state = JobState(str(row["state"]))
            if state is not JobState.RUNNING:
                raise JobTransitionError(
                    f"Job {job_id} cannot yield from state {state.value!r}."
                )
            connection.execute(
                """
                UPDATE jobs
                SET state = 'queued', blocked_reason = NULL,
                    next_run_at_us = ?, worker_id = NULL, lease_token = NULL,
                    lease_acquired_at_us = NULL, lease_expires_at_us = NULL,
                    heartbeat_at_us = NULL, updated_at_us = ?
                WHERE job_id = ?
                """,
                (next_run_at_us, now, uuid_to_blob(job_id)),
            )
        return self.get(job_id)

    def complete(
        self,
        *,
        job_id: uuid.UUID,
        lease_token: bytes,
        now_us: int | None = None,
    ) -> JobRecord:
        now = utc_now_us() if now_us is None else now_us
        with self.database.write_transaction() as connection:
            row = self._require_live_lease(connection, job_id, lease_token, now)
            state = JobState(str(row["state"]))
            if state is not JobState.RUNNING:
                raise JobTransitionError(
                    f"Job {job_id} cannot complete from state {state.value!r}."
                )
            self._update_state_and_clear_lease(
                connection, job_id, JobState.COMPLETED, now
            )
        return self.get(job_id)

    def acknowledge_cancel(
        self,
        *,
        job_id: uuid.UUID,
        lease_token: bytes,
        now_us: int | None = None,
    ) -> JobRecord:
        now = utc_now_us() if now_us is None else now_us
        with self.database.write_transaction() as connection:
            row = self._require_live_lease(connection, job_id, lease_token, now)
            state = JobState(str(row["state"]))
            if state is not JobState.CANCEL_REQUESTED:
                raise JobTransitionError(
                    f"Job {job_id} has no cancel request to acknowledge."
                )
            self._update_state_and_clear_lease(
                connection, job_id, JobState.CANCELLED, now
            )
        return self.get(job_id)

    def fail(
        self,
        *,
        job_id: uuid.UUID,
        lease_token: bytes,
        blocked_reason: str,
        now_us: int | None = None,
    ) -> JobRecord:
        now = utc_now_us() if now_us is None else now_us
        with self.database.write_transaction() as connection:
            self._require_live_lease(connection, job_id, lease_token, now)
            connection.execute(
                """
                UPDATE jobs
                SET state = 'failed', blocked_reason = ?, worker_id = NULL,
                    lease_token = NULL, lease_acquired_at_us = NULL,
                    lease_expires_at_us = NULL, heartbeat_at_us = NULL,
                    updated_at_us = ?
                WHERE job_id = ?
                """,
                (blocked_reason, now, uuid_to_blob(job_id)),
            )
        return self.get(job_id)

    def recover_expired_leases(self, *, now_us: int | None = None) -> tuple[JobRecord, ...]:
        now = utc_now_us() if now_us is None else now_us
        recovered_ids: list[uuid.UUID] = []
        with self.database.write_transaction() as connection:
            rows = connection.execute(
                """
                SELECT job_id, state
                FROM jobs
                WHERE state IN ('running', 'cancel_requested')
                  AND lease_expires_at_us IS NOT NULL
                  AND lease_expires_at_us <= ?
                ORDER BY lease_expires_at_us ASC, job_id ASC
                """,
                (now,),
            ).fetchall()
            for row in rows:
                job_id = uuid_from_blob(bytes(row["job_id"]))
                state = JobState(str(row["state"]))
                if state is JobState.CANCEL_REQUESTED:
                    target = JobState.CANCELLED
                    reason = "recovered_cancel_after_expired_lease"
                else:
                    target = JobState.QUEUED
                    reason = "recovered_after_expired_lease"
                connection.execute(
                    """
                    UPDATE jobs
                    SET state = ?, blocked_reason = ?, worker_id = NULL,
                        lease_token = NULL, lease_acquired_at_us = NULL,
                        lease_expires_at_us = NULL, heartbeat_at_us = NULL,
                        updated_at_us = ?
                    WHERE job_id = ?
                    """,
                    (target.value, reason, now, uuid_to_blob(job_id)),
                )
                recovered_ids.append(job_id)
        return tuple(self.get(job_id) for job_id in recovered_ids)

    @staticmethod
    def _require_active_actor(connection: sqlite3.Connection, actor_id: uuid.UUID) -> None:
        row = connection.execute(
            "SELECT active FROM actors WHERE actor_id = ?",
            (uuid_to_blob(actor_id),),
        ).fetchone()
        if row is None or int(row["active"]) != 1:
            raise ValueError(f"Actor {actor_id} does not exist or is inactive.")

    @staticmethod
    def _require_job_row(
        connection: sqlite3.Connection, job_id: uuid.UUID
    ) -> sqlite3.Row:
        row = connection.execute(
            "SELECT * FROM jobs WHERE job_id = ?",
            (uuid_to_blob(job_id),),
        ).fetchone()
        if row is None:
            raise JobNotFoundError(str(job_id))
        if not isinstance(row, sqlite3.Row):
            raise TypeError("Job query did not return sqlite3.Row.")
        return row

    def _require_live_lease(
        self,
        connection: sqlite3.Connection,
        job_id: uuid.UUID,
        lease_token: bytes,
        now_us: int,
    ) -> sqlite3.Row:
        row = self._require_job_row(connection, job_id)
        stored_token = row["lease_token"]
        expires_at = row["lease_expires_at_us"]
        if stored_token is None or bytes(stored_token) != lease_token:
            raise JobLeaseError(f"Worker does not own the current lease for job {job_id}.")
        if expires_at is None or int(expires_at) <= now_us:
            raise JobLeaseError(f"Lease for job {job_id} has expired.")
        return row

    @staticmethod
    def _update_state_and_clear_lease(
        connection: sqlite3.Connection,
        job_id: uuid.UUID,
        state: JobState,
        now_us: int,
    ) -> None:
        connection.execute(
            """
            UPDATE jobs
            SET state = ?, worker_id = NULL, lease_token = NULL,
                lease_acquired_at_us = NULL, lease_expires_at_us = NULL,
                heartbeat_at_us = NULL, updated_at_us = ?
            WHERE job_id = ?
            """,
            (state.value, now_us, uuid_to_blob(job_id)),
        )



def _require_unprotected_job_dependencies(
    connection: sqlite3.Connection,
    requested_scope_json: str | None,
) -> None:
    source_ids = _job_source_dependency_ids(
        connection,
        requested_scope_json,
    )

    for source_id in source_ids:
        source_blob = uuid_to_blob(
            source_id
        )

        guarded = connection.execute(
            """
            SELECT 1
            FROM source_protection_transitions
            WHERE source_id = ?

            UNION ALL

            SELECT 1
            FROM protected_sources
            WHERE source_id = ?

            LIMIT 1
            """,
            (
                source_blob,
                source_blob,
            ),
        ).fetchone()

        if guarded is not None:
            raise JobSourceProtectionFenceError(
                "Durable job creation is blocked because "
                "a referenced Source is protected or "
                "has an active protection transition."
            )


def _job_source_dependency_ids(
    connection: sqlite3.Connection,
    requested_scope_json: str | None,
) -> frozenset[uuid.UUID]:
    if requested_scope_json is None:
        return frozenset()

    try:
        payload = json.loads(
            requested_scope_json
        )
    except json.JSONDecodeError as exc:
        raise ValueError(
            "Durable job requested scope must be valid JSON."
        ) from exc

    if not isinstance(
        payload,
        dict,
    ):
        return frozenset()

    source_ids: set[
        uuid.UUID
    ] = set()

    direct_source_id = _scope_uuid(
        payload.get(
            "source_id"
        ),
        field_name="source_id",
    )

    if direct_source_id is not None:
        source_ids.add(
            direct_source_id
        )

    explicit_source_ids = payload.get(
        "explicit_source_ids"
    )

    if explicit_source_ids is not None:
        if not isinstance(
            explicit_source_ids,
            list,
        ):
            raise ValueError(
                "Durable job explicit_source_ids "
                "must be a JSON array."
            )

        for value in explicit_source_ids:
            source_id = _scope_uuid(
                value,
                field_name=(
                    "explicit_source_ids"
                ),
            )

            if source_id is None:
                raise ValueError(
                    "Durable job explicit_source_ids "
                    "must not contain null."
                )

            source_ids.add(
                source_id
            )

    representation_id = _scope_uuid(
        payload.get(
            "representation_id"
        ),
        field_name="representation_id",
    )

    if representation_id is not None:
        row = connection.execute(
            """
            SELECT source_id
            FROM source_representations
            WHERE representation_id = ?
            """,
            (
                uuid_to_blob(
                    representation_id
                ),
            ),
        ).fetchone()

        if row is not None:
            source_ids.add(
                uuid_from_blob(
                    bytes(
                        row["source_id"]
                    )
                )
            )

    analysis_id = _scope_uuid(
        payload.get(
            "analysis_id"
        ),
        field_name="analysis_id",
    )

    if analysis_id is not None:
        row = connection.execute(
            """
            SELECT source_id
            FROM source_analyses
            WHERE analysis_id = ?
            """,
            (
                uuid_to_blob(
                    analysis_id
                ),
            ),
        ).fetchone()

        if row is not None:
            source_ids.add(
                uuid_from_blob(
                    bytes(
                        row["source_id"]
                    )
                )
            )

    return frozenset(
        source_ids
    )


def _scope_uuid(
    value: object,
    *,
    field_name: str,
) -> uuid.UUID | None:
    if value is None:
        return None

    if not isinstance(
        value,
        str,
    ):
        raise ValueError(
            f"Durable job {field_name} must be a UUID string."
        )

    try:
        return uuid.UUID(
            value
        )
    except ValueError as exc:
        raise ValueError(
            f"Durable job {field_name} must be a valid UUID."
        ) from exc


def _protected_operational_json(
    *,
    payload_type: str,
    values: dict[str, str | None],
) -> bytes:
    return json.dumps(
        {
            "payload_type": payload_type,
            "version": 1,
            "values": values,
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")

def _job_from_row(row: sqlite3.Row) -> JobRecord:
    return JobRecord(
        job_id=uuid_from_blob(bytes(row["job_id"])),
        job_type=str(row["job_type"]),
        created_at_us=int(row["created_at_us"]),
        created_by_actor_id=uuid_from_blob(bytes(row["created_by_actor_id"])),
        priority=JobPriority(int(row["priority"])),
        state=JobState(str(row["state"])),
        requested_scope_json=_maybe_text(row["requested_scope_json"]),
        processing_run_id=_maybe_uuid(row["processing_run_id"]),
        current_stage=_maybe_text(row["current_stage"]),
        last_checkpoint_id=_maybe_uuid(row["last_checkpoint_id"]),
        retry_count=int(row["retry_count"]),
        next_run_at_us=_maybe_int(row["next_run_at_us"]),
        blocked_reason=_maybe_text(row["blocked_reason"]),
        pinned_configuration_json=_maybe_text(row["pinned_configuration_json"]),
        protection_scope_id=_maybe_uuid(row["protection_scope_id"]),
        protected_payload_id=_maybe_uuid(row["protected_payload_id"]),
        worker_id=_maybe_text(row["worker_id"]),
        lease_token=None if row["lease_token"] is None else bytes(row["lease_token"]),
        lease_acquired_at_us=_maybe_int(row["lease_acquired_at_us"]),
        lease_expires_at_us=_maybe_int(row["lease_expires_at_us"]),
        heartbeat_at_us=_maybe_int(row["heartbeat_at_us"]),
        fencing_sequence=int(row["fencing_sequence"]),
        updated_at_us=int(row["updated_at_us"]),
    )


def _checkpoint_from_row(row: sqlite3.Row) -> CheckpointRecord:
    return CheckpointRecord(
        checkpoint_id=uuid_from_blob(bytes(row["checkpoint_id"])),
        job_id=uuid_from_blob(bytes(row["job_id"])),
        processing_stage_id=_maybe_uuid(row["processing_stage_id"]),
        created_at_us=int(row["created_at_us"]),
        progress_state_json=_maybe_text(row["progress_state_json"]),
        last_confirmed_input_json=_maybe_text(row["last_confirmed_input_json"]),
        last_confirmed_output_json=_maybe_text(row["last_confirmed_output_json"]),
        resume_metadata_json=_maybe_text(row["resume_metadata_json"]),
        commit_id=_maybe_uuid(row["commit_id"]),
        protection_scope_id=_maybe_uuid(row["protection_scope_id"]),
        protected_payload_id=_maybe_uuid(row["protected_payload_id"]),
        fencing_sequence=int(row["fencing_sequence"]),
    )


def _maybe_uuid(value: object) -> uuid.UUID | None:
    if value is None:
        return None
    if not isinstance(value, (bytes, bytearray, memoryview)):
        raise TypeError("Expected a SQLite BLOB value for UUID conversion.")
    return uuid_from_blob(bytes(value))


def _maybe_uuid_blob(value: uuid.UUID | None) -> bytes | None:
    return None if value is None else uuid_to_blob(value)


def _maybe_text(value: object) -> str | None:
    return None if value is None else str(value)


def _maybe_int(value: object) -> int | None:
    if value is None:
        return None
    if not isinstance(value, int):
        raise TypeError("Expected a SQLite INTEGER value.")
    return value
