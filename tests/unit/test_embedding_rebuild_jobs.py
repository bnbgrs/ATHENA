from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

import pytest

from athena.common.time import utc_now_us
from athena.config.settings import AthenaSettings
from athena.core.application import AthenaApplication
from athena.jobs.embedding_processing import (
    DurableEmbeddingRebuildWorker,
    EmbeddingRebuildJobError,
)
from athena.jobs.models import JobState
from athena.jobs.repository import JobLeaseError
from athena.model.adapters.lm_studio import ProviderUnavailableError
from athena.retrieval.archive import ArchiveSemanticSearchService


@dataclass
class FakeEmbeddingProvider:
    calls: list[tuple[str, ...]] = field(default_factory=list)
    before_return: Callable[[], None] | None = None
    generation_timeout_seconds: float | None = None

    def embed(self, *, model_id: str, texts):
        captured = tuple(texts)
        self.calls.append(captured)
        if self.before_return is not None:
            callback = self.before_return
            self.before_return = None
            callback()
        return tuple((1.0, float((len(text) % 7) + 1), 0.5) for text in captured)


@dataclass
class UnavailableEmbeddingProvider:
    calls: int = 0

    def embed(self, *, model_id: str, texts):
        self.calls += 1
        raise ProviderUnavailableError("LM Studio unavailable in test")


def _app(root: Path) -> AthenaApplication:
    app = AthenaApplication(settings=AthenaSettings(local_root=root))
    app.start()
    return app


def _build_chunks(app: AthenaApplication, tmp_path: Path, text: str):
    source_file = tmp_path / "embedding-source.md"
    source_file.write_text(text, encoding="utf-8", newline="")
    captured = app.sources.capture_file(source_file)
    represented = app.source_text.build(captured.source.source_id)
    built = app.source_chunks.build_default(
        represented.result.representation.representation_id
    )
    return represented.result.representation, built


def _worker(app: AthenaApplication, provider) -> DurableEmbeddingRebuildWorker:
    semantic = ArchiveSemanticSearchService(
        lexical=app.archive_search,
        provider=provider,
        batch_size=2,
    )
    return DurableEmbeddingRebuildWorker(jobs=app.jobs, semantic=semantic)


def test_embedding_rebuild_resumes_committed_batches_after_crash(tmp_path) -> None:
    app = _app(tmp_path / "runtime")
    _representation, built = _build_chunks(
        app,
        tmp_path,
        "Berlin durable embedding marker.\n\n" + ("batch payload words " * 320),
    )
    assert len(built.chunks) >= 3
    provider = FakeEmbeddingProvider()
    worker = _worker(app, provider)
    job = worker.enqueue("fake-embed", batch_size=1)
    leased_a = app.jobs.acquire(job.job_id, worker_id="embed-a", lease_seconds=60)
    assert leased_a.lease_token is not None

    first = worker.step(job.job_id, lease_token=leased_a.lease_token)
    assert first.completed_stage == "batch"
    assert first.indexed_document_count == 1
    assert len(provider.calls) == 1
    first_input = provider.calls[0]

    crashed = app.jobs.get(job.job_id)
    assert crashed.lease_expires_at_us is not None
    recovered = app.jobs.recover_startup(now_us=crashed.lease_expires_at_us + 1)
    assert recovered and recovered[0].state is JobState.QUEUED
    leased_b = app.jobs.acquire(
        job.job_id,
        worker_id="embed-b",
        lease_seconds=60,
        now_us=crashed.lease_expires_at_us + 2,
    )
    assert leased_b.lease_token is not None

    result = worker.step(job.job_id, lease_token=leased_b.lease_token)
    while not result.done:
        result = worker.step(job.job_id, lease_token=leased_b.lease_token)

    assert result.job.state is JobState.COMPLETED
    assert provider.calls.count(first_input) == 1
    status = worker.semantic.status("fake-embed")
    assert status is not None and status.current
    assert status.document_count == len(built.chunks)
    checkpoints = app.jobs.checkpoints(job.job_id)
    assert checkpoints[0].fencing_sequence == 1
    assert all(item.fencing_sequence == 2 for item in checkpoints[1:])
    app.stop()


def test_provider_outage_releases_job_to_waiting_and_can_resume(tmp_path) -> None:
    app = _app(tmp_path / "runtime")
    _build_chunks(app, tmp_path, "Provider outage embedding marker.\n")
    unavailable = UnavailableEmbeddingProvider()
    worker = _worker(app, unavailable)
    job = worker.enqueue("fake-embed", batch_size=4)
    leased = app.jobs.acquire(job.job_id, worker_id="embed-a", lease_seconds=60)
    assert leased.lease_token is not None

    waiting = worker.step(job.job_id, lease_token=leased.lease_token)

    assert waiting.waiting is True
    assert waiting.job.state is JobState.WAITING
    assert waiting.job.blocked_reason == "waiting_network"
    assert unavailable.calls == 1
    assert app.jobs.checkpoints(job.job_id) == ()

    app.jobs.wake(job.job_id)
    provider = FakeEmbeddingProvider()
    resumed_worker = _worker(app, provider)
    completed = resumed_worker.run_to_boundary(
        job.job_id,
        worker_id="embed-b",
        lease_seconds=60,
    )
    assert completed.done is True
    assert completed.job.state is JobState.COMPLETED
    assert completed.job.fencing_sequence == 2
    assert resumed_worker.semantic.status("fake-embed").current  # type: ignore[union-attr]
    app.stop()


def test_generation_change_during_provider_call_waits_dependency(tmp_path) -> None:
    app = _app(tmp_path / "runtime")
    representation, _built = _build_chunks(
        app,
        tmp_path,
        "Generation drift marker.\n\n" + ("generation payload " * 120),
    )
    original_generation = app.source_chunk_store.current_generation()
    provider = FakeEmbeddingProvider(
        before_return=lambda: app.source_chunks.build_default(
            representation.representation_id
        )
    )
    worker = _worker(app, provider)
    job = worker.enqueue("fake-embed", batch_size=2)
    leased = app.jobs.acquire(job.job_id, worker_id="embed-a", lease_seconds=60)
    assert leased.lease_token is not None

    result = worker.step(job.job_id, lease_token=leased.lease_token)

    assert result.waiting is True
    assert result.completed_stage == "generation_stale"
    assert result.job.state is JobState.WAITING
    assert result.job.blocked_reason == "waiting_dependency"
    assert app.source_chunk_store.current_generation() > original_generation
    status = worker.semantic.status("fake-embed")
    assert status is None or not status.current
    app.stop()


def test_finalize_is_idempotent_after_crash_before_checkpoint(tmp_path, monkeypatch) -> None:
    app = _app(tmp_path / "runtime")
    _build_chunks(app, tmp_path, "Finalize crash marker.\n")
    provider = FakeEmbeddingProvider()
    worker = _worker(app, provider)
    job = worker.enqueue("fake-embed", batch_size=32)
    leased_a = app.jobs.acquire(job.job_id, worker_id="embed-a", lease_seconds=60)
    assert leased_a.lease_token is not None

    batch = worker.step(job.job_id, lease_token=leased_a.lease_token)
    assert batch.completed_stage == "batch"
    assert len(provider.calls) == 1

    original_checkpoint = app.jobs.checkpoint

    def crash_after_publish(*args, **kwargs):
        if kwargs.get("current_stage") == "embedding_index_current":
            raise JobLeaseError("simulated crash after derived index publication")
        return original_checkpoint(*args, **kwargs)

    monkeypatch.setattr(app.jobs, "checkpoint", crash_after_publish)
    with pytest.raises(JobLeaseError, match="simulated crash"):
        worker.step(job.job_id, lease_token=leased_a.lease_token)
    monkeypatch.setattr(app.jobs, "checkpoint", original_checkpoint)
    published = worker.semantic.status("fake-embed")
    assert published is not None and published.current

    crashed = app.jobs.get(job.job_id)
    assert crashed.lease_expires_at_us is not None
    app.jobs.recover_startup(now_us=crashed.lease_expires_at_us + 1)
    leased_b = app.jobs.acquire(
        job.job_id,
        worker_id="embed-b",
        lease_seconds=60,
        now_us=crashed.lease_expires_at_us + 2,
    )
    assert leased_b.lease_token is not None
    finalized = worker.step(job.job_id, lease_token=leased_b.lease_token)
    assert finalized.completed_stage == "finalize"
    completed = worker.step(job.job_id, lease_token=leased_b.lease_token)
    assert completed.done is True
    assert completed.job.state is JobState.COMPLETED
    assert len(provider.calls) == 1
    app.stop()


def test_embedding_worker_rejects_generic_unpinned_job(tmp_path) -> None:
    app = _app(tmp_path / "runtime")
    worker = _worker(app, FakeEmbeddingProvider())
    job = app.jobs.create(job_type="embedding.rebuild")
    leased = app.jobs.acquire(job.job_id, worker_id="embed", lease_seconds=60)
    assert leased.lease_token is not None

    with pytest.raises(EmbeddingRebuildJobError, match="requested_scope"):
        worker.step(job.job_id, lease_token=leased.lease_token)

    assert app.jobs.get(job.job_id).state is JobState.RUNNING
    app.stop()


def test_embedding_rebuild_uses_keyset_progress_without_quadratic_rewalk(
    tmp_path,
    monkeypatch,
) -> None:
    app = _app(tmp_path / "runtime")
    _representation, built = _build_chunks(
        app,
        tmp_path,
        "A06 keyset planner marker.\n\n"
        + ("planner payload words " * 1200),
    )
    assert len(built.chunks) >= 8

    def forbidden_full_text_read(*args, **kwargs):
        del args, kwargs
        raise AssertionError(
            "A-06 snapshot verification must not materialize full retained text."
        )

    monkeypatch.setattr(
        app.source_text,
        "read_text",
        forbidden_full_text_read,
    )

    full_build_verifications = 0
    original_verify = (
        app.source_chunks.verify_current_profile_build
    )

    def counted_verify(*args, **kwargs):
        nonlocal full_build_verifications
        full_build_verifications += 1
        return original_verify(*args, **kwargs)

    monkeypatch.setattr(
        app.source_chunks,
        "verify_current_profile_build",
        counted_verify,
    )

    provider = FakeEmbeddingProvider()
    worker = _worker(app, provider)
    job = worker.enqueue(
        "fake-embed",
        batch_size=1,
    )

    completed = worker.run_to_boundary(
        job.job_id,
        worker_id="embed-keyset",
        lease_seconds=60,
    )

    assert completed.done is True
    assert completed.job.state is JobState.COMPLETED
    assert sum(len(call) for call in provider.calls) == len(
        built.chunks
    )
    # One full retained-evidence verification pins the snapshot and one
    # final verification gates publication, independent of chunk count.
    assert full_build_verifications == 2
    app.stop()


def test_visibility_change_during_provider_call_waits_dependency(
    tmp_path,
) -> None:
    app = _app(tmp_path / "runtime")
    _representation, built = _build_chunks(
        app,
        tmp_path,
        "Visibility drift during embedding provider call.\n",
    )
    assert built.chunks

    source_id = built.chunks[0].source_id
    preview = app.lifecycle_deletion.preview(source_id)
    original_generation = (
        app.source_chunk_store.current_generation()
    )

    provider = FakeEmbeddingProvider(
        before_return=lambda: app.lifecycle_deletion.delete(
            source_id,
            preview_digest=preview.preview_digest,
        )
    )
    worker = _worker(app, provider)
    job = worker.enqueue(
        "fake-embed",
        batch_size=2,
    )
    leased = app.jobs.acquire(
        job.job_id,
        worker_id="embed-a",
        lease_seconds=60,
    )
    assert leased.lease_token is not None

    result = worker.step(
        job.job_id,
        lease_token=leased.lease_token,
    )

    assert result.waiting is True
    assert result.completed_stage == "visibility_stale"
    assert result.job.state is JobState.WAITING
    assert result.job.blocked_reason == "waiting_dependency"
    assert (
        app.source_chunk_store.current_generation()
        == original_generation
    )
    status = worker.semantic.status("fake-embed")
    assert status is None or not status.current
    app.stop()

def test_embedding_provider_call_extends_lease_before_blocking_boundary(
    tmp_path,
) -> None:
    app = _app(tmp_path / "provider-lease-runtime")
    try:
        _representation, built = _build_chunks(
            app,
            tmp_path,
            "Embedding provider lease guard marker.\n\n"
            + ("lease payload " * 400),
        )
        assert built.chunks

        provider = FakeEmbeddingProvider(
            generation_timeout_seconds=5.0,
        )
        worker = _worker(app, provider)
        job = worker.enqueue(
            "fake-embed",
            batch_size=1,
        )
        leased = app.jobs.acquire(
            job.job_id,
            worker_id="provider-lease",
            lease_seconds=1,
        )
        assert leased.lease_token is not None

        def assert_provider_lease_is_protected() -> None:
            current = app.jobs.get(job.job_id)
            assert current.lease_expires_at_us is not None
            now_us = utc_now_us()
            assert current.lease_expires_at_us > now_us + 4_000_000

            recovered = app.jobs.recover_startup(
                now_us=now_us + 2_000_000
            )
            assert job.job_id not in {
                item.job_id
                for item in recovered
            }

        provider.before_return = assert_provider_lease_is_protected

        result = worker.step(
            job.job_id,
            lease_token=leased.lease_token,
            extend_seconds=1,
        )

        assert result.completed_stage == "batch"
        assert result.job.state is JobState.RUNNING
        assert len(provider.calls) == 1
    finally:
        app.stop()
