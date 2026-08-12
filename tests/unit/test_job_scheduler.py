from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from athena.common.time import utc_now_us
from athena.config.settings import AthenaSettings
from athena.core.application import AthenaApplication
from athena.jobs.embedding_processing import DurableEmbeddingRebuildWorker
from athena.jobs.models import JobPriority, JobState, WaitingReason
from athena.jobs.scheduler import DurableJobScheduler, SchedulerPolicy
from athena.model.adapters.lm_studio import ProviderUnavailableError
from athena.retrieval.archive import ArchiveSemanticSearchService


@dataclass
class FakeEmbeddingProvider:
    calls: list[tuple[str, ...]] = field(default_factory=list)

    def embed(self, *, model_id: str, texts):
        captured = tuple(texts)
        self.calls.append(captured)
        return tuple((1.0, float((len(text) % 7) + 1), 0.5) for text in captured)


@dataclass
class UnavailableEmbeddingProvider:
    calls: int = 0

    def embed(self, *, model_id: str, texts):
        self.calls += 1
        raise ProviderUnavailableError("provider offline")


def _app(root: Path) -> AthenaApplication:
    app = AthenaApplication(settings=AthenaSettings(local_root=root))
    app.start()
    return app


def _capture_source(app: AthenaApplication, path: Path, text: str):
    path.write_text(text, encoding="utf-8", newline="")
    return app.sources.capture_file(path).source


def _embedding_scheduler(
    app: AthenaApplication,
    provider,
    *,
    policy: SchedulerPolicy,
) -> tuple[DurableJobScheduler, DurableEmbeddingRebuildWorker]:
    semantic = ArchiveSemanticSearchService(
        lexical=app.archive_search,
        provider=provider,
        batch_size=2,
    )
    embedding = DurableEmbeddingRebuildWorker(jobs=app.jobs, semantic=semantic)
    scheduler = DurableJobScheduler(
        jobs=app.jobs,
        source_worker=app.source_processing,
        embedding_worker=embedding,
        policy=policy,
    )
    return scheduler, embedding


def test_scheduler_dispatches_source_process_to_completion(tmp_path) -> None:
    app = _app(tmp_path / "runtime")
    source = _capture_source(
        app,
        tmp_path / "scheduler-source.md",
        "ATHENA scheduler source completion marker.\n",
    )
    job = app.source_processing.enqueue(source.source_id)

    tick = app.job_scheduler.tick(worker_id="scheduler-a")

    assert tick.selected_job_id == job.job_id
    assert tick.selected_job_type == "source.process"
    assert tick.action == "completed"
    assert tick.final_state is JobState.COMPLETED
    assert tick.fencing_sequence == 1
    assert len(app.jobs.checkpoints(job.job_id)) == 3
    app.stop()


def test_scheduler_ignores_registered_job_types_without_dispatcher(tmp_path) -> None:
    app = _app(tmp_path / "runtime")
    unsupported = app.jobs.create(
        job_type="integrity.sweep",
        priority=JobPriority.DATA_SAFETY,
    )
    source = _capture_source(
        app,
        tmp_path / "supported.md",
        "Supported scheduler source.\n",
    )
    supported = app.source_processing.enqueue(
        source.source_id,
        priority=JobPriority.NORMAL,
    )

    tick = app.job_scheduler.tick(worker_id="scheduler-a")

    assert tick.selected_job_id == supported.job_id
    assert app.jobs.get(unsupported.job_id).state is JobState.QUEUED
    app.stop()


def test_fairness_aging_promotes_old_background_work_but_not_to_p0(tmp_path) -> None:
    app = _app(tmp_path / "runtime")
    old_source = _capture_source(app, tmp_path / "old.md", "Old source.\n")
    new_source = _capture_source(app, tmp_path / "new.md", "New source.\n")
    old_job = app.source_processing.enqueue(
        old_source.source_id,
        priority=JobPriority.BACKGROUND,
    )
    new_job = app.source_processing.enqueue(
        new_source.source_id,
        priority=JobPriority.INTERACTIVE,
    )
    now = utc_now_us()
    aging_us = app.job_scheduler.policy.fairness_aging_seconds * 1_000_000
    with app.database.write_transaction() as connection:
        connection.execute(
            "UPDATE jobs SET created_at_us = ? WHERE job_id = ?",
            (now - 4 * aging_us, old_job.job_id.bytes),
        )

    tick = app.job_scheduler.tick(worker_id="scheduler-a", now_us=now)

    assert tick.selected_job_id == old_job.job_id
    assert app.jobs.get(new_job.job_id).state is JobState.QUEUED
    app.stop()


def test_large_embedding_job_yields_at_checkpoint_boundary_and_resumes(tmp_path) -> None:
    app = _app(tmp_path / "runtime")
    source = _capture_source(
        app,
        tmp_path / "embedding.md",
        "Scheduler embedding marker.\n\n" + ("batch payload " * 500),
    )
    represented = app.source_text.build(source.source_id)
    built = app.source_chunks.build_default(
        represented.result.representation.representation_id
    )
    assert len(built.chunks) >= 3
    provider = FakeEmbeddingProvider()
    scheduler, embedding = _embedding_scheduler(
        app,
        provider,
        policy=SchedulerPolicy(max_boundaries_per_dispatch=1),
    )
    job = embedding.enqueue("fake-embed", batch_size=1)

    first = scheduler.tick(worker_id="scheduler-a")
    first_call = provider.calls[0]

    assert first.selected_job_id == job.job_id
    assert first.action == "yielded"
    assert first.final_state is JobState.QUEUED
    assert first.fencing_sequence == 1

    drained = scheduler.drain(worker_id="scheduler-b", max_jobs=20)

    assert drained.completed_jobs == 1
    final = app.jobs.get(job.job_id)
    assert final.state is JobState.COMPLETED
    assert final.fencing_sequence > 1
    assert provider.calls.count(first_call) == 1
    status = embedding.semantic.status("fake-embed")
    assert status is not None and status.current
    app.stop()


def test_network_wait_gets_backoff_wakes_due_and_exhausts_retry_budget(tmp_path) -> None:
    app = _app(tmp_path / "runtime")
    source = _capture_source(app, tmp_path / "network.md", "Network retry marker.\n")
    represented = app.source_text.build(source.source_id)
    app.source_chunks.build_default(represented.result.representation.representation_id)
    provider = UnavailableEmbeddingProvider()
    policy = SchedulerPolicy(
        max_boundaries_per_dispatch=1,
        retry_base_seconds=1,
        retry_max_seconds=2,
        retry_budget=1,
        retry_jitter_fraction=0,
    )
    scheduler, embedding = _embedding_scheduler(app, provider, policy=policy)
    job = embedding.enqueue("fake-embed", batch_size=1)
    now = utc_now_us()

    first = scheduler.tick(worker_id="scheduler-a", now_us=now)
    waiting = app.jobs.get(job.job_id)

    assert first.action == "waiting"
    assert waiting.state is JobState.WAITING
    assert waiting.blocked_reason == WaitingReason.NETWORK.value
    assert waiting.retry_count == 1
    assert waiting.next_run_at_us == now + 1_000_000

    before_due = scheduler.tick(
        worker_id="scheduler-a",
        now_us=waiting.next_run_at_us - 1,
    )
    assert before_due.idle
    assert app.jobs.get(job.job_id).state is JobState.WAITING

    second = scheduler.tick(
        worker_id="scheduler-b",
        now_us=waiting.next_run_at_us + 1,
    )
    exhausted = app.jobs.get(job.job_id)

    assert second.woken_jobs == 1
    assert second.action == "waiting"
    assert exhausted.state is JobState.WAITING
    assert exhausted.blocked_reason == WaitingReason.USER.value
    assert exhausted.next_run_at_us is None
    assert exhausted.retry_count == 1
    assert provider.calls == 2
    app.stop()


def test_scheduler_repairs_waiter_if_process_died_before_backoff_was_assigned(tmp_path) -> None:
    app = _app(tmp_path / "runtime")
    job = app.jobs.create(job_type="embedding.rebuild")
    leased = app.jobs.acquire(job.job_id, worker_id="worker", lease_seconds=60)
    assert leased.lease_token is not None
    app.jobs.wait(
        job.job_id,
        lease_token=leased.lease_token,
        reason=WaitingReason.NETWORK,
    )
    now = utc_now_us()

    tick = app.job_scheduler.tick(worker_id="scheduler-a", now_us=now)
    repaired = app.jobs.get(job.job_id)

    assert tick.scheduled_retries == 1
    assert repaired.state is JobState.WAITING
    assert repaired.next_run_at_us is not None
    assert repaired.next_run_at_us > now
    assert repaired.retry_count == 1
    app.stop()
