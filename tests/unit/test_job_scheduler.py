from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from athena.common.time import utc_now_us
from athena.config.settings import AthenaSettings
from athena.core.application import AthenaApplication
from athena.jobs import scheduler as scheduler_module
from athena.jobs.capabilities import CONTROL_LANE_JOB_TYPES
from athena.jobs.embedding_processing import DurableEmbeddingRebuildWorker
from athena.jobs.models import JobPriority, JobState, WaitingReason
from athena.jobs.scheduler import (
    DurableJobScheduler,
    SchedulerLane,
    SchedulerPolicy,
)
from athena.model.adapters.lm_studio import ProviderUnavailableError
from athena.news.models import NEWS_JOB_TYPE, NEWS_PERIOD_JOB_TYPE
from athena.resources.manager import AdmissionDecision
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


@dataclass
class ToggleInteractiveResources:
    active: bool = False

    def admit(self, job):
        del job
        return AdmissionDecision(True, None, 0)

    def should_yield_to_interactive(self, job):
        del job
        return self.active


@dataclass
class InteractiveTriggerEmbeddingProvider:
    resources: ToggleInteractiveResources
    calls: list[tuple[str, ...]] = field(default_factory=list)
    triggered: bool = False

    def embed(self, *, model_id: str, texts):
        del model_id
        captured = tuple(texts)
        self.calls.append(captured)
        if not self.triggered:
            self.triggered = True
            self.resources.active = True
        return tuple(
            (1.0, float((len(text) % 7) + 1), 0.5)
            for text in captured
        )


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
    assert len(app.jobs.checkpoints(job.job_id)) == 5
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

def test_due_dependency_parent_does_not_starve_queued_child(tmp_path) -> None:
    app = _app(tmp_path / "runtime")
    parent = app.jobs.create(
        job_type="research.exhaustive",
        priority=JobPriority.BACKGROUND,
        requested_scope={"mode": "regression-test"},
        pinned_configuration={"pipeline": "regression-test"},
    )
    source = _capture_source(
        app,
        tmp_path / "dependency-child.md",
        "Dependency child scheduling regression marker.\n",
    )
    child = app.source_processing.enqueue(
        source.source_id,
        priority=JobPriority.BACKGROUND,
    )
    now = utc_now_us()
    aging_us = app.job_scheduler.policy.fairness_aging_seconds * 1_000_000
    with app.database.write_transaction() as connection:
        connection.execute(
            "UPDATE jobs SET created_at_us = ? WHERE job_id = ?",
            (now - 4 * aging_us, parent.job_id.bytes),
        )

    leased = app.jobs.acquire(
        parent.job_id,
        worker_id="research-parent",
        lease_seconds=60,
        now_us=now,
    )
    assert leased.lease_token is not None

    due_at = now + 5_000_000
    waiting = app.jobs.wait(
        parent.job_id,
        lease_token=leased.lease_token,
        reason=WaitingReason.DEPENDENCY,
        next_run_at_us=due_at,
        now_us=now,
    )
    assert waiting.state is JobState.WAITING

    tick = app.job_scheduler.tick(
        worker_id="scheduler-a",
        now_us=due_at,
    )

    assert tick.woken_jobs == 1
    assert tick.selected_job_id == child.job_id
    assert tick.selected_job_type == "source.process"
    assert app.jobs.get(child.job_id).state is JobState.COMPLETED

    queued_parent = app.jobs.get(parent.job_id)
    assert queued_parent.state is JobState.QUEUED
    assert queued_parent.next_run_at_us == due_at
    app.stop()

def test_running_gpu_job_yields_at_next_boundary_for_interactive_chat(
    tmp_path,
) -> None:
    app = _app(tmp_path / "interactive-yield-runtime")
    source = _capture_source(
        app,
        tmp_path / "interactive-yield.md",
        "Interactive priority boundary marker.\n\n"
        + ("large background embedding payload " * 700),
    )
    represented = app.source_text.build(source.source_id)
    built = app.source_chunks.build_default(
        represented.result.representation.representation_id
    )
    assert len(built.chunks) >= 3

    resources = ToggleInteractiveResources()
    provider = InteractiveTriggerEmbeddingProvider(resources)
    semantic = ArchiveSemanticSearchService(
        lexical=app.archive_search,
        provider=provider,
        batch_size=1,
    )
    embedding = DurableEmbeddingRebuildWorker(
        jobs=app.jobs,
        semantic=semantic,
    )
    scheduler = DurableJobScheduler(
        jobs=app.jobs,
        source_worker=app.source_processing,
        embedding_worker=embedding,
        resources=resources,
        policy=SchedulerPolicy(
            max_boundaries_per_dispatch=8,
        ),
    )
    job = embedding.enqueue(
        "interactive-yield-embed",
        batch_size=1,
    )

    first = scheduler.tick(worker_id="background-worker")

    assert first.selected_job_id == job.job_id
    assert first.action == "yielded_interactive"
    assert first.final_state is JobState.QUEUED
    assert len(provider.calls) == 1

    resources.active = False

    resumed = scheduler.drain(
        worker_id="background-worker-resumed",
        max_jobs=20,
    )

    assert resumed.completed_jobs == 1
    assert app.jobs.get(job.job_id).state is JobState.COMPLETED
    app.stop()

def test_control_lane_skips_provider_bound_jobs(
    tmp_path,
) -> None:
    app = _app(tmp_path / "control-lane-runtime")
    try:
        provider_job = app.jobs.create(
            job_type="embedding.rebuild",
            priority=JobPriority.DATA_SAFETY,
        )
        source = _capture_source(
            app,
            tmp_path / "control-lane-source.md",
            "Control lane source processing marker.\n",
        )
        control_job = app.source_processing.enqueue(
            source.source_id,
            priority=JobPriority.NORMAL,
        )

        tick = app.job_scheduler.tick(
            worker_id="control-lane",
            lane=SchedulerLane.CONTROL,
        )

        assert tick.selected_job_id == control_job.job_id
        assert tick.final_state is JobState.COMPLETED
        assert app.jobs.get(provider_job.job_id).state is JobState.QUEUED
    finally:
        app.stop()


def test_provider_lane_skips_control_jobs(
    tmp_path,
) -> None:
    app = _app(tmp_path / "provider-lane-runtime")
    try:
        embedding_source = _capture_source(
            app,
            tmp_path / "provider-lane-embedding.md",
            "Provider lane embedding marker.\n\n"
            + ("provider payload " * 500),
        )
        represented = app.source_text.build(
            embedding_source.source_id
        )
        built = app.source_chunks.build_default(
            represented.result.representation.representation_id
        )
        assert len(built.chunks) >= 2

        control_source = _capture_source(
            app,
            tmp_path / "provider-lane-control.md",
            "Provider lane must not dispatch this source job.\n",
        )
        control_job = app.source_processing.enqueue(
            control_source.source_id,
            priority=JobPriority.DATA_SAFETY,
        )

        provider = FakeEmbeddingProvider()
        scheduler, embedding = _embedding_scheduler(
            app,
            provider,
            policy=SchedulerPolicy(
                max_boundaries_per_dispatch=1,
            ),
        )
        provider_job = embedding.enqueue(
            "provider-lane-embed",
            batch_size=1,
            priority=JobPriority.BACKGROUND,
        )

        tick = scheduler.tick(
            worker_id="provider-lane",
            lane=SchedulerLane.PROVIDER,
        )

        assert tick.selected_job_id == provider_job.job_id
        assert tick.action == "yielded"
        assert len(provider.calls) == 1
        assert app.jobs.get(control_job.job_id).state is JobState.QUEUED
    finally:
        app.stop()

def test_news_jobs_are_provider_lane_only(
    tmp_path,
) -> None:
    app = _app(tmp_path / "news-lane-runtime")
    try:
        provider_types = app.job_scheduler.job_types_for_lane(
            SchedulerLane.PROVIDER
        )
        control_types = app.job_scheduler.job_types_for_lane(
            SchedulerLane.CONTROL
        )

        assert NEWS_JOB_TYPE in provider_types
        assert NEWS_PERIOD_JOB_TYPE in provider_types
        assert NEWS_JOB_TYPE not in control_types
        assert NEWS_PERIOD_JOB_TYPE not in control_types
    finally:
        app.stop()

def test_provider_lane_skips_global_housekeeping(
    tmp_path,
    monkeypatch,
) -> None:
    app = _app(tmp_path / "provider-housekeeping-runtime")
    try:
        def forbidden(*args, **kwargs):
            del args, kwargs
            raise AssertionError(
                "Provider lane must not own global scheduler housekeeping."
            )

        monkeypatch.setattr(
            app.backup_worker,
            "schedule_due",
            forbidden,
        )
        monkeypatch.setattr(
            app.news,
            "schedule_due",
            forbidden,
        )
        monkeypatch.setattr(
            app.news,
            "reconcile_dependencies",
            forbidden,
        )
        monkeypatch.setattr(
            app.jobs,
            "recover_startup",
            forbidden,
        )
        monkeypatch.setattr(
            app.archive_replication_worker,
            "reconcile_pending",
            forbidden,
        )
        monkeypatch.setattr(
            app.job_scheduler,
            "_schedule_orphaned_retry_waiters",
            forbidden,
        )
        monkeypatch.setattr(
            app.jobs,
            "wake_due_waiting",
            forbidden,
        )
        monkeypatch.setattr(
            app.job_scheduler,
            "_wake_legacy_research_synthesis_waiters",
            forbidden,
        )

        result = app.job_scheduler.tick(
            worker_id="provider-housekeeping",
            lane=SchedulerLane.PROVIDER,
        )

        assert result.idle is True
        assert result.recovered_jobs == 0
        assert result.scheduled_retries == 0
        assert result.woken_jobs == 0
    finally:
        app.stop()


def test_worker_start_can_skip_global_startup_maintenance(
    tmp_path,
    monkeypatch,
) -> None:
    app = AthenaApplication(
        settings=AthenaSettings(
            local_root=tmp_path / "worker-start-runtime"
        )
    )

    def forbidden(*args, **kwargs):
        del args, kwargs
        raise AssertionError(
            "Supervised worker start must skip global startup maintenance."
        )

    monkeypatch.setattr(
        app.backup,
        "recover_incomplete",
        forbidden,
    )
    monkeypatch.setattr(
        app.backup,
        "sync_all_deletion_ledgers",
        forbidden,
    )
    monkeypatch.setattr(
        app.jobs,
        "recover_startup",
        forbidden,
    )

    app.start(
        run_startup_maintenance=False,
    )
    try:
        assert app.news.profile()["name"] == "default"
    finally:
        app.stop()

def test_future_supported_job_type_fails_closed_to_provider_lane(
    tmp_path,
    monkeypatch,
) -> None:
    app = _app(tmp_path / "future-lane-runtime")
    try:
        future_job_type = "future.provider-bound"
        monkeypatch.setattr(
            scheduler_module,
            "_SUPPORTED_JOB_TYPES",
            scheduler_module._SUPPORTED_JOB_TYPES
            | frozenset({future_job_type}),
        )

        supported = app.job_scheduler.supported_job_types
        control = app.job_scheduler.job_types_for_lane(
            SchedulerLane.CONTROL
        )
        provider = app.job_scheduler.job_types_for_lane(
            SchedulerLane.PROVIDER
        )

        assert control == supported & CONTROL_LANE_JOB_TYPES
        assert provider == supported - control
        assert control.isdisjoint(provider)
        assert control | provider == supported
        assert future_job_type in provider
        assert future_job_type not in control
    finally:
        app.stop()
