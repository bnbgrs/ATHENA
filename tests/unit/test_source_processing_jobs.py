from __future__ import annotations

import json
from pathlib import Path

import pytest

from athena.config.settings import AthenaSettings
from athena.core.application import AthenaApplication
from athena.jobs.models import JobState
from athena.jobs.repository import JobLeaseError
from athena.jobs.source_processing import SourceProcessingJobError


def _app(root: Path) -> AthenaApplication:
    app = AthenaApplication(settings=AthenaSettings(local_root=root))
    app.start()
    return app


def _capture(app: AthenaApplication, tmp_path: Path, text: str):
    path = tmp_path / "durable-source.md"
    path.write_text(text, encoding="utf-8", newline="")
    return app.sources.capture_file(path)


def test_source_process_job_runs_end_to_end_and_survives_restart(tmp_path) -> None:
    root = tmp_path / "runtime"
    first = _app(root)
    captured = _capture(
        first,
        tmp_path,
        "Durable worker Berlin marker.\n\n" + ("chunk words " * 180),
    )
    job = first.source_processing.enqueue(captured.source.source_id)

    result = first.source_processing.run_to_completion(
        job.job_id,
        worker_id="source-worker",
        lease_seconds=60,
    )

    assert result.done is True
    assert result.job.state is JobState.COMPLETED
    assert result.representation_id is not None
    assert result.chunk_count is not None and result.chunk_count >= 2
    checkpoints = first.jobs.checkpoints(job.job_id)
    assert len(checkpoints) == 5
    assert [
        json.loads(item.resume_metadata_json or "{}")["next_stage"]
        for item in checkpoints
    ] == ["represent", "chunk", "chunk_batch", "chunk_publish", "finalize"]
    hits = first.archive_search.search("Berlin marker")
    assert hits and hits[0].source_id == captured.source.source_id
    representation_id = result.representation_id
    first.stop()

    second = _app(root)
    loaded = second.jobs.get(job.job_id)
    assert loaded.state is JobState.COMPLETED
    second.source_text.verify(representation_id)
    chunks = second.source_chunks.list_for_representation(representation_id)
    assert chunks
    assert second.archive_search.search("Berlin marker")
    second.stop()


def test_crash_after_representation_commit_reuses_retained_representation(
    tmp_path, monkeypatch
) -> None:
    app = _app(tmp_path / "runtime")
    captured = _capture(app, tmp_path, "Crash-safe representation marker.\n")
    job = app.source_processing.enqueue(captured.source.source_id)
    leased = app.jobs.acquire(job.job_id, worker_id="worker-a", lease_seconds=60)
    assert leased.lease_token is not None

    first = app.source_processing.step(
        job.job_id,
        lease_token=leased.lease_token,
        extend_seconds=60,
    )
    assert first.completed_stage == "verify"

    original_checkpoint = app.jobs.checkpoint

    def crash_before_representation_checkpoint(*args, **kwargs):
        if kwargs.get("current_stage") == "representation_ready":
            raise JobLeaseError("simulated worker crash after representation commit")
        return original_checkpoint(*args, **kwargs)

    monkeypatch.setattr(app.jobs, "checkpoint", crash_before_representation_checkpoint)
    with pytest.raises(JobLeaseError, match="simulated worker crash"):
        app.source_processing.step(
            job.job_id,
            lease_token=leased.lease_token,
            extend_seconds=60,
        )
    monkeypatch.setattr(app.jobs, "checkpoint", original_checkpoint)

    representations = app.source_text.list_for_source(captured.source.source_id)
    assert len(representations) == 1
    representation_id = representations[0][0].representation_id
    current = app.jobs.get(job.job_id)
    assert current.current_stage == "source_verified"

    crashed = app.jobs.get(job.job_id)
    assert crashed.lease_expires_at_us is not None
    recovered = app.jobs.recover_startup(now_us=crashed.lease_expires_at_us + 1)
    assert recovered[0].state is JobState.QUEUED
    second_lease = app.jobs.acquire(
        job.job_id,
        worker_id="worker-b",
        lease_seconds=60,
        now_us=crashed.lease_expires_at_us + 2,
    )
    assert second_lease.lease_token is not None
    resumed = app.source_processing.step(
        job.job_id,
        lease_token=second_lease.lease_token,
        extend_seconds=60,
    )
    assert resumed.completed_stage == "represent"
    assert resumed.representation_id == representation_id
    assert len(app.source_text.list_for_source(captured.source.source_id)) == 1
    assert resumed.checkpoint is not None
    output = json.loads(resumed.checkpoint.last_confirmed_output_json or "{}")
    assert output["reused_representation"] is True
    app.stop()


def test_finalize_repairs_lost_derived_chunks_from_retained_representation(tmp_path) -> None:
    app = _app(tmp_path / "runtime")
    captured = _capture(
        app,
        tmp_path,
        "Repairable derived marker.\n\n" + ("payload " * 220),
    )
    job = app.source_processing.enqueue(captured.source.source_id)
    leased = app.jobs.acquire(job.job_id, worker_id="worker", lease_seconds=120)
    assert leased.lease_token is not None

    app.source_processing.step(job.job_id, lease_token=leased.lease_token)
    represented = app.source_processing.step(job.job_id, lease_token=leased.lease_token)
    planned = app.source_processing.step(job.job_id, lease_token=leased.lease_token)
    staged = app.source_processing.step(job.job_id, lease_token=leased.lease_token)
    published = app.source_processing.step(job.job_id, lease_token=leased.lease_token)
    assert represented.representation_id is not None
    assert planned.completed_stage == "chunk_plan"
    assert staged.completed_stage == "chunk_batch"
    assert published.completed_stage == "chunk_publish"

    search_db = app.paths.derived_root / "search.db"
    assert search_db.exists()
    search_db.unlink()

    repaired = app.source_processing.step(job.job_id, lease_token=leased.lease_token)
    assert repaired.done is False
    assert repaired.completed_stage == "derived_repair_planned"
    assert repaired.checkpoint is not None
    output = json.loads(repaired.checkpoint.last_confirmed_output_json or "{}")
    assert output["derived_repair"] is True

    app.source_processing.step(job.job_id, lease_token=leased.lease_token)
    republished = app.source_processing.step(job.job_id, lease_token=leased.lease_token)
    assert republished.completed_stage == "derived_repair"
    assert app.source_chunks.list_for_representation(represented.representation_id)

    completed = app.source_processing.step(job.job_id, lease_token=leased.lease_token)
    assert completed.done is True
    assert completed.job.state is JobState.COMPLETED
    assert app.archive_search.search("Repairable derived marker")
    app.stop()


def test_source_worker_rejects_generic_unpinned_source_process_job(tmp_path) -> None:
    app = _app(tmp_path / "runtime")
    job = app.jobs.create(job_type="source.process")
    leased = app.jobs.acquire(job.job_id, worker_id="worker", lease_seconds=60)
    assert leased.lease_token is not None

    with pytest.raises(SourceProcessingJobError, match="pinned_configuration"):
        app.source_processing.step(job.job_id, lease_token=leased.lease_token)

    assert app.jobs.get(job.job_id).state is JobState.RUNNING
    app.stop()
