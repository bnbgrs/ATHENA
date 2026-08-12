from __future__ import annotations

from pathlib import Path

from athena.common.time import utc_now_us
from athena.config.settings import AthenaSettings
from athena.core.application import AthenaApplication
from athena.jobs.models import JobState, WaitingReason
from athena.jobs.repository import JobLeaseError


def _app(root: Path) -> AthenaApplication:
    app = AthenaApplication(settings=AthenaSettings(local_root=root))
    app.start()
    return app


def _capture_source(app: AthenaApplication, path: Path, text: str):
    path.write_text(text, encoding="utf-8", newline="")
    return app.sources.capture_file(path).source


def test_hundred_queued_jobs_survive_restart_without_loss(tmp_path) -> None:
    root = tmp_path / "runtime"
    first = _app(root)
    job_ids = {
        first.jobs.create(job_type="integrity.sweep").job_id for _ in range(100)
    }
    assert len(job_ids) == 100
    first.stop()

    second = _app(root)
    visible = {job.job_id: job for job in second.jobs.list(limit=200)}

    assert job_ids <= visible.keys()
    assert all(visible[job_id].state is JobState.QUEUED for job_id in job_ids)
    second.stop()


def test_retry_schedule_is_idempotent_for_competing_schedulers(tmp_path) -> None:
    app = _app(tmp_path / "runtime")
    job = app.jobs.create(job_type="embedding.rebuild")
    leased = app.jobs.acquire(job.job_id, worker_id="retry-owner", lease_seconds=60)
    assert leased.lease_token is not None
    waiting = app.jobs.wait(
        job.job_id,
        lease_token=leased.lease_token,
        reason=WaitingReason.NETWORK,
    )
    assert waiting.retry_count == 0
    now = utc_now_us()

    first = app.jobs.schedule_retry(
        job.job_id,
        next_run_at_us=now + 10_000_000,
        max_retries=5,
        now_us=now,
    )
    second = app.jobs.schedule_retry(
        job.job_id,
        next_run_at_us=now + 20_000_000,
        max_retries=5,
        now_us=now,
    )

    assert first.retry_count == 1
    assert second.retry_count == 1
    assert second.next_run_at_us == first.next_run_at_us
    assert second.blocked_reason == WaitingReason.NETWORK.value
    app.stop()


def test_scheduler_survives_lost_lease_and_reports_persisted_state(
    tmp_path,
    monkeypatch,
) -> None:
    app = _app(tmp_path / "runtime")
    source = _capture_source(
        app,
        tmp_path / "lease-loss.md",
        "ATHENA scheduler lost lease reliability marker.\n",
    )
    job = app.source_processing.enqueue(source.source_id)

    def lose_lease(job_id, *, lease_token, extend_seconds=120):
        current = app.jobs.get(job_id)
        assert current.lease_expires_at_us is not None
        recovered = app.jobs.recover_startup(
            now_us=current.lease_expires_at_us + 1
        )
        assert recovered and recovered[0].job_id == job_id
        raise JobLeaseError("simulated expired fence")

    monkeypatch.setattr(app.source_processing, "step", lose_lease)

    tick = app.job_scheduler.tick(worker_id="scheduler-lost-lease")

    assert tick.selected_job_id == job.job_id
    assert tick.action == "lost_lease"
    assert tick.final_state is JobState.QUEUED
    recovered_job = app.jobs.get(job.job_id)
    assert recovered_job.state is JobState.QUEUED
    assert recovered_job.worker_id is None
    assert recovered_job.lease_token is None
    app.stop()


def test_cancel_at_safe_boundary_keeps_confirmed_representation_only(tmp_path) -> None:
    app = _app(tmp_path / "runtime")
    source = _capture_source(
        app,
        tmp_path / "cancel.md",
        "ATHENA confirmed output survives cancellation.\n",
    )
    job = app.source_processing.enqueue(source.source_id)
    leased = app.jobs.acquire(job.job_id, worker_id="cancel-worker", lease_seconds=60)
    assert leased.lease_token is not None

    verified = app.source_processing.step(
        job.job_id,
        lease_token=leased.lease_token,
    )
    represented = app.source_processing.step(
        job.job_id,
        lease_token=leased.lease_token,
    )
    assert verified.completed_stage == "verify"
    assert represented.completed_stage == "represent"
    assert represented.representation_id is not None
    representation_id = represented.representation_id
    checkpoints_before_cancel = app.jobs.checkpoints(job.job_id)
    assert len(checkpoints_before_cancel) == 2

    requested = app.jobs.request_cancel(job.job_id)
    assert requested.state is JobState.CANCEL_REQUESTED
    cancelled = app.source_processing.step(
        job.job_id,
        lease_token=leased.lease_token,
    )

    assert cancelled.done is True
    assert cancelled.job.state is JobState.CANCELLED
    assert app.jobs.checkpoints(job.job_id) == checkpoints_before_cancel
    assert app.source_text.read_text(representation_id).startswith("ATHENA confirmed")
    assert app.source_chunks.list_for_representation(representation_id) == ()
    app.stop()


def test_source_pipeline_recovers_after_total_derived_database_loss(tmp_path) -> None:
    root = tmp_path / "runtime"
    first = _app(root)
    source = _capture_source(
        first,
        tmp_path / "derived-loss.md",
        "ATHENA_VS5_DERIVED_LOSS_RECOVERY_TOKEN Berlin.\n",
    )
    first_job = first.source_processing.enqueue(source.source_id)
    first_tick = first.job_scheduler.tick(worker_id="scheduler-before-loss")
    assert first_tick.selected_job_id == first_job.job_id
    assert first_tick.final_state is JobState.COMPLETED
    representations = first.source_text.list_for_source(source.source_id)
    assert len(representations) == 1
    representation_id = representations[0][0].representation_id
    assert first.archive_search.search("ATHENA_VS5_DERIVED_LOSS_RECOVERY_TOKEN")
    first.stop()

    search_db = root / "derived" / "search.db"
    assert search_db.exists()
    search_db.unlink()

    second = _app(root)
    assert second.source_text.read_text(representation_id).startswith(
        "ATHENA_VS5_DERIVED_LOSS_RECOVERY_TOKEN"
    )
    assert second.source_chunks.list_for_representation(representation_id) == ()

    repair_job = second.source_processing.enqueue(source.source_id)
    repaired_tick = second.job_scheduler.tick(worker_id="scheduler-after-loss")

    assert repaired_tick.selected_job_id == repair_job.job_id
    assert repaired_tick.final_state is JobState.COMPLETED
    representations_after = second.source_text.list_for_source(source.source_id)
    assert [item[0].representation_id for item in representations_after] == [
        representation_id
    ]
    assert second.source_chunks.list_for_representation(representation_id)
    hits = second.archive_search.search("ATHENA_VS5_DERIVED_LOSS_RECOVERY_TOKEN")
    assert hits and hits[0].source_id == source.source_id
    second.stop()
