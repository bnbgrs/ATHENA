from __future__ import annotations

import json
from pathlib import Path

import pytest

from athena.config.settings import AthenaSettings
from athena.core.application import AthenaApplication
from athena.jobs.models import JobState
from athena.jobs.repository import JobLeaseError
from athena.source.chunk_store import SourceChunkNotFoundError


def _app(root: Path) -> AthenaApplication:
    app = AthenaApplication(settings=AthenaSettings(local_root=root))
    app.start()
    return app


def _large_source(tmp_path: Path, *, sections: int = 100) -> Path:
    path = tmp_path / "large-source.md"
    blocks = [
        f"## Section {index:03d}\nATHENA_LARGE_SECTION_{index:03d} " + ("payload " * 140)
        for index in range(sections)
    ]
    path.write_text("\n\n".join(blocks), encoding="utf-8", newline="")
    return path


def _lease_to_plan(app: AthenaApplication, source_id, *, worker: str = "large-worker"):
    job = app.source_processing.enqueue(source_id)
    leased = app.jobs.acquire(job.job_id, worker_id=worker, lease_seconds=120)
    assert leased.lease_token is not None
    app.source_processing.step(job.job_id, lease_token=leased.lease_token)
    represented = app.source_processing.step(job.job_id, lease_token=leased.lease_token)
    planned = app.source_processing.step(job.job_id, lease_token=leased.lease_token)
    assert represented.representation_id is not None
    assert planned.completed_stage == "chunk_plan"
    assert planned.chunk_count is not None and planned.chunk_count > 32
    return job, leased.lease_token, represented.representation_id, planned


def test_large_source_batches_are_invisible_until_atomic_publish(tmp_path: Path) -> None:
    app = _app(tmp_path / "runtime")
    source_path = _large_source(tmp_path, sections=100)
    captured = app.sources.capture_file(source_path)
    job, lease_token, representation_id, planned = _lease_to_plan(
        app, captured.source.source_id
    )
    generation_before = app.source_chunks.store.current_generation()

    first_batch = app.source_processing.step(job.job_id, lease_token=lease_token)
    assert first_batch.completed_stage == "chunk_batch"
    assert first_batch.checkpoint is not None
    progress = json.loads(first_batch.checkpoint.progress_state_json or "{}")
    assert progress["confirmed_chunks"] == 32
    assert progress["total_chunks"] == planned.chunk_count
    assert app.source_chunks.store.count_for_representation(representation_id) == 0
    assert app.source_chunks.store.current_generation() == generation_before
    assert not app.archive_search.search("ATHENA_LARGE_SECTION_099")

    result = first_batch
    for _ in range(100):
        result = app.source_processing.step(job.job_id, lease_token=lease_token)
        if result.done:
            break
    assert result.done is True
    assert result.job.state is JobState.COMPLETED
    assert app.source_chunks.store.count_for_representation(representation_id) == planned.chunk_count
    assert app.source_chunks.store.current_generation() == generation_before + 1
    hits = app.archive_search.search("ATHENA_LARGE_SECTION_099")
    assert hits and hits[0].source_id == captured.source.source_id

    checkpoints = app.jobs.checkpoints(job.job_id)
    batch_progress = [
        json.loads(item.progress_state_json or "{}")
        for item in checkpoints
        if item.progress_state_json and "confirmed_chunks" in item.progress_state_json
    ]
    confirmed = [int(item["confirmed_chunks"]) for item in batch_progress]
    assert confirmed[0] == 0
    assert confirmed[-1] == planned.chunk_count
    assert confirmed == sorted(set(confirmed))
    app.stop()


def test_crash_after_staged_batch_commit_replays_unconfirmed_batch_without_duplicates(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    app = _app(tmp_path / "runtime")
    source_path = _large_source(tmp_path, sections=80)
    captured = app.sources.capture_file(source_path)
    job, lease_token, representation_id, planned = _lease_to_plan(
        app, captured.source.source_id,
        worker="worker-a",
    )

    original_checkpoint = app.jobs.checkpoint

    def crash_before_batch_checkpoint(*args, **kwargs):
        if kwargs.get("current_stage") == "chunks_staging":
            raise JobLeaseError("simulated crash after staged batch commit")
        return original_checkpoint(*args, **kwargs)

    monkeypatch.setattr(app.jobs, "checkpoint", crash_before_batch_checkpoint)
    with pytest.raises(JobLeaseError, match="simulated crash"):
        app.source_processing.step(job.job_id, lease_token=lease_token)
    monkeypatch.setattr(app.jobs, "checkpoint", original_checkpoint)

    cursor_payload = json.loads(
        app.jobs.get_checkpoint(app.jobs.get(job.job_id).last_checkpoint_id).resume_metadata_json
        or "{}"
    )
    build_signature = bytes.fromhex(cursor_payload["build_signature"])
    assert app.source_chunks.store.staged_chunk_count(build_signature) == 32
    assert app.source_chunks.store.count_for_representation(representation_id) == 0

    crashed = app.jobs.get(job.job_id)
    assert crashed.lease_expires_at_us is not None
    recovered = app.jobs.recover_startup(now_us=crashed.lease_expires_at_us + 1)
    assert recovered and recovered[0].state is JobState.QUEUED
    second = app.jobs.acquire(
        job.job_id,
        worker_id="worker-b",
        lease_seconds=120,
        now_us=crashed.lease_expires_at_us + 2,
    )
    assert second.lease_token is not None

    replayed = app.source_processing.step(job.job_id, lease_token=second.lease_token)
    assert replayed.completed_stage == "chunk_batch"
    assert replayed.checkpoint is not None
    replay_progress = json.loads(replayed.checkpoint.progress_state_json or "{}")
    assert replay_progress["confirmed_chunks"] == 32
    assert app.source_chunks.store.staged_chunk_count(build_signature) == 32

    result = replayed
    for _ in range(100):
        result = app.source_processing.step(job.job_id, lease_token=second.lease_token)
        if result.done:
            break
    assert result.done is True
    assert app.source_chunks.store.count_for_representation(representation_id) == planned.chunk_count
    app.source_chunks.verify_current_build(
        representation_id,
        expected_build_signature=bytes.fromhex(
            json.loads(app.jobs.checkpoints(job.job_id)[-1].resume_metadata_json or "{}")[
                "build_signature"
            ]
        ),
        expected_chunk_count=planned.chunk_count,
    )
    app.stop()


def test_loss_of_derived_staging_restarts_from_durable_plan_boundary(tmp_path: Path) -> None:
    app = _app(tmp_path / "runtime")
    source_path = _large_source(tmp_path, sections=75)
    captured = app.sources.capture_file(source_path)
    job, lease_token, representation_id, planned = _lease_to_plan(
        app, captured.source.source_id
    )
    first_batch = app.source_processing.step(job.job_id, lease_token=lease_token)
    assert first_batch.completed_stage == "chunk_batch"

    search_db = app.paths.derived_root / "search.db"
    assert search_db.exists()
    search_db.unlink()

    repaired = app.source_processing.step(job.job_id, lease_token=lease_token)
    assert repaired.completed_stage == "derived_staging_repair"
    assert repaired.checkpoint is not None
    resume = json.loads(repaired.checkpoint.resume_metadata_json or "{}")
    assert resume["next_stage"] == "chunk_batch"
    assert resume["next_chunk_index"] == 0
    assert resume["repairing"] is True
    assert app.source_chunks.store.count_for_representation(representation_id) == 0

    result = repaired
    for _ in range(100):
        result = app.source_processing.step(job.job_id, lease_token=lease_token)
        if result.done:
            break
    assert result.done is True
    assert result.chunk_count == planned.chunk_count
    assert app.archive_search.search("ATHENA_LARGE_SECTION_074")
    app.stop()


def test_cancelled_large_source_discards_unpublished_staging_and_keeps_retained_text(
    tmp_path: Path,
) -> None:
    app = _app(tmp_path / "runtime")
    source_path = _large_source(tmp_path, sections=70)
    captured = app.sources.capture_file(source_path)
    job, lease_token, representation_id, _planned = _lease_to_plan(
        app, captured.source.source_id
    )
    staged = app.source_processing.step(job.job_id, lease_token=lease_token)
    assert staged.completed_stage == "chunk_batch"
    cursor = json.loads(staged.checkpoint.resume_metadata_json or "{}")
    build_signature = bytes.fromhex(cursor["build_signature"])
    assert app.source_chunks.store.staged_chunk_count(build_signature) == 32

    requested = app.jobs.request_cancel(job.job_id)
    assert requested.state is JobState.CANCEL_REQUESTED
    cancelled = app.source_processing.step(job.job_id, lease_token=lease_token)
    assert cancelled.done is True
    assert cancelled.job.state is JobState.CANCELLED
    assert app.source_chunks.store.count_for_representation(representation_id) == 0
    with pytest.raises(SourceChunkNotFoundError):
        app.source_chunks.store.get_staged_build(build_signature)
    app.source_text.verify(representation_id)
    assert app.source_text.read_text(representation_id).startswith("## Section 000")
    app.stop()


def test_loss_of_derived_staging_immediately_before_publish_replans_safely(
    tmp_path: Path,
) -> None:
    app = _app(tmp_path / "runtime")
    source_path = _large_source(tmp_path, sections=70)
    captured = app.sources.capture_file(source_path)
    job, lease_token, representation_id, planned = _lease_to_plan(
        app, captured.source.source_id
    )

    staged = app.source_processing.step(job.job_id, lease_token=lease_token)
    while staged.completed_stage == "chunk_batch":
        resume = json.loads(staged.checkpoint.resume_metadata_json or "{}")
        if resume["next_stage"] == "chunk_publish":
            break
        staged = app.source_processing.step(job.job_id, lease_token=lease_token)
    assert staged.checkpoint is not None
    assert json.loads(staged.checkpoint.resume_metadata_json or "{}")["next_stage"] == (
        "chunk_publish"
    )

    search_db = app.paths.derived_root / "search.db"
    search_db.unlink()

    repaired = app.source_processing.step(job.job_id, lease_token=lease_token)
    assert repaired.completed_stage == "derived_staging_repair"
    assert repaired.checkpoint is not None
    resume = json.loads(repaired.checkpoint.resume_metadata_json or "{}")
    assert resume["next_stage"] == "chunk_batch"
    assert resume["next_chunk_index"] == 0
    assert resume["repairing"] is True

    result = repaired
    for _ in range(100):
        result = app.source_processing.step(job.job_id, lease_token=lease_token)
        if result.done:
            break
    assert result.done is True
    assert result.chunk_count == planned.chunk_count
    assert app.source_chunks.store.count_for_representation(representation_id) == planned.chunk_count
    app.stop()


def test_publish_commit_before_checkpoint_is_idempotent_across_lease_recovery(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    app = _app(tmp_path / "runtime")
    source_path = _large_source(tmp_path, sections=70)
    captured = app.sources.capture_file(source_path)
    job, lease_token, representation_id, planned = _lease_to_plan(
        app,
        captured.source.source_id,
        worker="publisher-a",
    )

    staged = app.source_processing.step(job.job_id, lease_token=lease_token)
    while staged.completed_stage == "chunk_batch":
        resume = json.loads(staged.checkpoint.resume_metadata_json or "{}")
        if resume["next_stage"] == "chunk_publish":
            break
        staged = app.source_processing.step(job.job_id, lease_token=lease_token)
    assert staged.checkpoint is not None
    assert json.loads(staged.checkpoint.resume_metadata_json or "{}")["next_stage"] == (
        "chunk_publish"
    )

    generation_before = app.source_chunks.store.current_generation()
    original_checkpoint = app.jobs.checkpoint

    def crash_before_publish_checkpoint(*args, **kwargs):
        if kwargs.get("current_stage") == "chunks_ready":
            raise JobLeaseError("simulated crash after atomic chunk publication")
        return original_checkpoint(*args, **kwargs)

    monkeypatch.setattr(app.jobs, "checkpoint", crash_before_publish_checkpoint)
    with pytest.raises(JobLeaseError, match="after atomic chunk publication"):
        app.source_processing.step(job.job_id, lease_token=lease_token)
    monkeypatch.setattr(app.jobs, "checkpoint", original_checkpoint)

    assert app.source_chunks.store.current_generation() == generation_before + 1
    assert app.source_chunks.store.count_for_representation(representation_id) == planned.chunk_count

    crashed = app.jobs.get(job.job_id)
    assert crashed.lease_expires_at_us is not None
    app.jobs.recover_startup(now_us=crashed.lease_expires_at_us + 1)
    second = app.jobs.acquire(
        job.job_id,
        worker_id="publisher-b",
        lease_seconds=120,
        now_us=crashed.lease_expires_at_us + 2,
    )
    assert second.lease_token is not None

    replayed = app.source_processing.step(job.job_id, lease_token=second.lease_token)
    assert replayed.completed_stage == "chunk_publish"
    assert replayed.done is False
    assert app.source_chunks.store.current_generation() == generation_before + 1
    assert app.source_chunks.store.count_for_representation(representation_id) == planned.chunk_count

    completed = app.source_processing.step(job.job_id, lease_token=second.lease_token)
    assert completed.done is True
    assert completed.job.state is JobState.COMPLETED
    assert app.source_chunks.store.current_generation() == generation_before + 1
    app.stop()
