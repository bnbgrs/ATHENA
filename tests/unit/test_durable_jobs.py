from __future__ import annotations

from pathlib import Path

import pytest

from athena.config.settings import AthenaSettings
from athena.core.application import AthenaApplication
from athena.jobs.models import JobPriority, JobState, WaitingReason
from athena.jobs.repository import JobLeaseError, JobTransitionError
from athena.jobs.service import InvalidJobPayloadError, UnsupportedJobTypeError


def _app(root: Path) -> AthenaApplication:
    app = AthenaApplication(settings=AthenaSettings(local_root=root))
    app.start()
    return app


def test_durable_job_survives_restart_with_canonical_pinned_payload(tmp_path) -> None:
    first = _app(tmp_path)
    job = first.jobs.create(
        job_type="source.process",
        priority=JobPriority.BACKGROUND,
        requested_scope={"z": 2, "a": 1},
        pinned_configuration={"pipeline_version": 1, "chunking": "paragraph_char_v1"},
    )
    first.stop()

    second = _app(tmp_path)
    loaded = second.jobs.get(job.job_id)

    assert loaded.state is JobState.QUEUED
    assert loaded.priority is JobPriority.BACKGROUND
    assert loaded.requested_scope_json == '{"a":1,"z":2}'
    assert loaded.pinned_configuration_json == (
        '{"chunking":"paragraph_char_v1","pipeline_version":1}'
    )
    assert loaded.uri == f"operational://job/{job.job_id}"
    second.stop()


def test_job_type_registry_and_json_fail_closed(tmp_path) -> None:
    app = _app(tmp_path)

    with pytest.raises(UnsupportedJobTypeError):
        app.jobs.create(job_type="plugin.untrusted")

    with pytest.raises(InvalidJobPayloadError):
        app.jobs.create(
            job_type="source.process",
            requested_scope={"bad": float("nan")},
        )

    assert app.jobs.list() == ()
    app.stop()


def test_lease_checkpoint_and_completion_are_durable_and_fenced(tmp_path) -> None:
    app = _app(tmp_path)
    job = app.jobs.create(job_type="source.process")
    leased = app.jobs.acquire(job.job_id, worker_id="worker-a", lease_seconds=60, now_us=100)
    assert leased.state is JobState.RUNNING
    assert leased.lease_token is not None
    assert leased.fencing_sequence == 1

    checkpoint = app.jobs.checkpoint(
        job.job_id,
        lease_token=leased.lease_token,
        current_stage="representation",
        progress_state={"completed_units": 3},
        last_confirmed_input={"source_id": "source-1"},
        resume_metadata={"next_unit": 4},
        now_us=101,
    )
    assert checkpoint.fencing_sequence == 1
    assert checkpoint.progress_state_json == '{"completed_units":3}'
    assert app.jobs.get(job.job_id).last_checkpoint_id == checkpoint.checkpoint_id

    completed = app.jobs.complete(
        job.job_id,
        lease_token=leased.lease_token,
        now_us=102,
    )
    assert completed.state is JobState.COMPLETED
    assert completed.lease_token is None

    with pytest.raises(JobTransitionError):
        app.jobs.acquire(job.job_id, worker_id="worker-b", now_us=103)

    app.stop()


def test_heartbeat_clamps_backward_clock_and_never_shortens_lease(tmp_path) -> None:
    app = _app(tmp_path)
    job = app.jobs.create(job_type="source.process")
    leased = app.jobs.acquire(
        job.job_id,
        worker_id="worker-a",
        lease_seconds=60,
        now_us=2_000_000,
    )
    assert leased.lease_token is not None
    assert leased.lease_acquired_at_us == 2_000_000
    assert leased.lease_expires_at_us == 62_000_000

    heartbeat = app.jobs.heartbeat(
        job.job_id,
        lease_token=leased.lease_token,
        extend_seconds=10,
        now_us=1_000_000,
    )

    assert heartbeat.heartbeat_at_us == 2_000_000
    assert heartbeat.lease_expires_at_us == 62_000_000
    app.stop()


def test_checkpoint_listing_preserves_commit_order_when_timestamps_tie(tmp_path) -> None:
    app = _app(tmp_path)
    job = app.jobs.create(job_type="source.process")
    leased = app.jobs.acquire(
        job.job_id,
        worker_id="worker-a",
        lease_seconds=60,
        now_us=1_000_000,
    )
    assert leased.lease_token is not None

    first = app.jobs.checkpoint(
        job.job_id,
        lease_token=leased.lease_token,
        current_stage="first",
        resume_metadata={"next_stage": "first"},
        now_us=1_000_001,
    )
    second = app.jobs.checkpoint(
        job.job_id,
        lease_token=leased.lease_token,
        current_stage="second",
        resume_metadata={"next_stage": "second"},
        now_us=1_000_001,
    )

    checkpoints = app.jobs.checkpoints(job.job_id)
    assert [item.checkpoint_id for item in checkpoints] == [
        first.checkpoint_id,
        second.checkpoint_id,
    ]
    assert [item.created_at_us for item in checkpoints] == [1_000_001, 1_000_002]
    app.stop()


def test_expired_lease_recovery_requeues_and_rejects_zombie_worker(tmp_path) -> None:
    app = _app(tmp_path)
    job = app.jobs.create(job_type="source.process")
    first_lease = app.jobs.acquire(
        job.job_id,
        worker_id="worker-old",
        lease_seconds=1,
        now_us=1_000_000,
    )
    assert first_lease.lease_token is not None

    recovered = app.jobs.recover_startup(now_us=2_000_001)
    assert [item.job_id for item in recovered] == [job.job_id]
    assert recovered[0].state is JobState.QUEUED
    assert recovered[0].blocked_reason == "recovered_after_expired_lease"

    second_lease = app.jobs.acquire(
        job.job_id,
        worker_id="worker-new",
        lease_seconds=60,
        now_us=2_000_002,
    )
    assert second_lease.lease_token is not None
    assert second_lease.fencing_sequence == 2

    with pytest.raises(JobLeaseError):
        app.jobs.checkpoint(
            job.job_id,
            lease_token=first_lease.lease_token,
            current_stage="zombie-write",
            progress_state={"should": "fail"},
            now_us=2_000_003,
        )

    checkpoint = app.jobs.checkpoint(
        job.job_id,
        lease_token=second_lease.lease_token,
        current_stage="safe-write",
        progress_state={"accepted": True},
        now_us=2_000_003,
    )
    assert checkpoint.fencing_sequence == 2
    app.stop()


def test_startup_automatically_recovers_only_expired_leases(tmp_path) -> None:
    first = _app(tmp_path)
    expired = first.jobs.create(job_type="source.process")
    live = first.jobs.create(job_type="integrity.sweep")
    first.job_repository.acquire_lease(
        job_id=expired.job_id,
        worker_id="dead-worker",
        lease_token=b"a" * 32,
        lease_duration_us=1,
        now_us=1,
    )
    first.job_repository.acquire_lease(
        job_id=live.job_id,
        worker_id="live-worker",
        lease_token=b"b" * 32,
        lease_duration_us=10**18,
        now_us=1,
    )
    first.stop()

    second = _app(tmp_path)
    assert second.jobs.get(expired.job_id).state is JobState.QUEUED
    live_loaded = second.jobs.get(live.job_id)
    assert live_loaded.state is JobState.RUNNING
    assert live_loaded.worker_id == "live-worker"
    second.stop()


def test_pause_resume_and_cooperative_cancel(tmp_path) -> None:
    app = _app(tmp_path)
    idle = app.jobs.create(job_type="search.rebuild")
    paused = app.jobs.pause(idle.job_id)
    assert paused.state is JobState.PAUSED
    resumed = app.jobs.resume(idle.job_id)
    assert resumed.state is JobState.QUEUED
    cancelled_idle = app.jobs.request_cancel(idle.job_id)
    assert cancelled_idle.state is JobState.CANCELLED

    running = app.jobs.create(job_type="source.process")
    leased = app.jobs.acquire(
        running.job_id,
        worker_id="worker",
        lease_seconds=60,
        now_us=100,
    )
    assert leased.lease_token is not None
    requested = app.jobs.request_cancel(running.job_id)
    assert requested.state is JobState.CANCEL_REQUESTED
    acknowledged = app.jobs.acknowledge_cancel(
        running.job_id,
        lease_token=leased.lease_token,
        now_us=101,
    )
    assert acknowledged.state is JobState.CANCELLED
    app.stop()

def test_waiting_state_requires_reason_and_can_wake(tmp_path) -> None:
    app = _app(tmp_path)
    job = app.jobs.create(job_type="source.process")
    leased = app.jobs.acquire(
        job.job_id,
        worker_id="worker",
        lease_seconds=60,
        now_us=100,
    )
    assert leased.lease_token is not None

    waiting = app.jobs.wait(
        job.job_id,
        lease_token=leased.lease_token,
        reason=WaitingReason.STORAGE,
        next_run_at_us=500,
        now_us=101,
    )
    assert waiting.state is JobState.WAITING
    assert waiting.blocked_reason == "waiting_storage"
    assert waiting.next_run_at_us == 500
    assert waiting.lease_token is None

    queued = app.jobs.wake(job.job_id)
    assert queued.state is JobState.QUEUED
    assert queued.blocked_reason is None
    assert queued.next_run_at_us is None
    app.stop()



def test_dependency_wait_wakes_when_due_without_consuming_retry_budget(tmp_path) -> None:
    app = _app(tmp_path)
    job = app.jobs.create(job_type="research.exhaustive")
    leased = app.jobs.acquire(
        job.job_id,
        worker_id="research-parent",
        lease_seconds=60,
        now_us=100,
    )
    assert leased.lease_token is not None

    waiting = app.jobs.wait(
        job.job_id,
        lease_token=leased.lease_token,
        reason=WaitingReason.DEPENDENCY,
        next_run_at_us=500,
        now_us=101,
    )
    assert waiting.state is JobState.WAITING
    assert waiting.blocked_reason == WaitingReason.DEPENDENCY.value
    assert waiting.next_run_at_us == 500
    assert waiting.retry_count == 0

    assert app.jobs.wake_due_waiting(now_us=499) == ()
    still_waiting = app.jobs.get(job.job_id)
    assert still_waiting.state is JobState.WAITING
    assert still_waiting.retry_count == 0

    woken = app.jobs.wake_due_waiting(now_us=500)
    assert [item.job_id for item in woken] == [job.job_id]

    queued = app.jobs.get(job.job_id)
    assert queued.state is JobState.QUEUED
    assert queued.blocked_reason is None
    assert queued.next_run_at_us == 500
    assert queued.retry_count == 0
    app.stop()



def test_one_hundred_queued_jobs_survive_restart(tmp_path) -> None:
    first = _app(tmp_path)
    created_ids = {
        first.jobs.create(
            job_type="integrity.sweep",
            priority=JobPriority.MAINTENANCE,
            requested_scope={"ordinal": ordinal},
        ).job_id
        for ordinal in range(100)
    }
    first.stop()

    second = _app(tmp_path)
    loaded = second.job_repository.list(states=(JobState.QUEUED,), limit=200)
    assert len(loaded) == 100
    assert {job.job_id for job in loaded} == created_ids
    second.stop()

