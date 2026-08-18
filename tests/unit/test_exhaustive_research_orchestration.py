from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field
from pathlib import Path

import pytest

from athena.common.time import utc_now_us
from athena.config.settings import AthenaSettings
from athena.core.application import AthenaApplication
from athena.jobs.models import JobState, WaitingReason
from athena.model.domain import ModelChatMessage, ModelInfo
from athena.research.models import ResearchScopeState, ResearchWorkState


@dataclass
class _ResearchProvider:
    quantization: str = "Q4"
    calls: list[tuple[str, tuple[ModelChatMessage, ...]]] = field(default_factory=list)

    @property
    def provider_id(self) -> str:
        return "fake"

    def discover_models(self) -> tuple[ModelInfo, ...]:
        return (
            ModelInfo(
                provider="fake",
                backend_model_id="research-primary",
                display_name="Research Primary",
                model_type="llm",
                context_capacity=2_000,
                loaded_context_length=2_000,
                quantization=self.quantization,
                loaded=True,
                vision=False,
                trained_for_tool_use=False,
            ),
        )

    def generate_structured(
        self,
        *,
        model_id: str,
        messages: tuple[ModelChatMessage, ...],
        schema_id: str,
        json_schema,
        max_output_tokens: int | None = None,
    ):
        del json_schema, max_output_tokens
        assert model_id == "research-primary"
        self.calls.append((schema_id, messages))
        text = "\n".join(message.content for message in messages)
        if "map" in schema_id:
            relevant = "NO_RELEVANT_EVIDENCE" not in text
            return {
                "relevant": relevant,
                "summary": "map summary",
                "findings": ["supported finding"] if relevant else [],
                "contradictions": [],
                "uncertainty": "",
            }
        return {
            "summary": "synthesis summary",
            "findings": ["supported finding"],
            "contradictions": [],
            "uncertainty": "",
        }

    def stream_chat(self, *, model_id: str, messages):
        del model_id, messages
        yield "unused"


def _app(root: Path) -> tuple[AthenaApplication, _ResearchProvider]:
    app = AthenaApplication(settings=AthenaSettings(local_root=root))
    app.start()
    provider = _ResearchProvider()
    app.source_analysis_service.provider = provider
    return app, provider


def _capture(app: AthenaApplication, path: Path, text: str):
    path.write_text(text, encoding="utf-8", newline="")
    return app.sources.capture_file(path).source


def _preprocess(app: AthenaApplication, source_id) -> None:
    job = app.source_processing.enqueue(source_id)
    result = app.source_processing.run_to_completion(
        job.job_id,
        worker_id="research-preprocess",
    )
    assert result.done is True


def _acquire_parent(
    app: AthenaApplication,
    job_id,
    *,
    worker: str = "research-parent",
):
    current = app.jobs.get(job_id)
    if current.state is JobState.WAITING:
        app.jobs.wake(job_id)
    current = app.jobs.get(job_id)
    assert current.state is JobState.QUEUED
    leased = app.jobs.acquire(job_id, worker_id=worker, lease_seconds=120)
    assert leased.lease_token is not None
    return leased.lease_token


def _advance_parent_until_wait(
    app: AthenaApplication,
    job_id,
    *,
    worker: str = "research-parent",
    max_steps: int = 50,
):
    lease_token = _acquire_parent(app, job_id, worker=worker)
    for _ in range(max_steps):
        result = app.research_worker.step(
            job_id,
            lease_token=lease_token,
            extend_seconds=120,
        )
        if result.waiting or result.done:
            return result
    raise AssertionError("Research parent did not reach a wait/terminal boundary.")


def _run_queued_children(app: AthenaApplication, job_id) -> None:
    scope = app.research.initialize(job_id)
    for work in app.research_repository.list_work_items(scope.scope_id):
        if work.source_processing_job_id is not None:
            child = app.jobs.get(work.source_processing_job_id)
            if child.state is JobState.QUEUED:
                result = app.source_processing.run_to_completion(
                    child.job_id,
                    worker_id="research-source-child",
                )
                assert result.done is True
        refreshed = app.research_repository.get_work_item(work.work_item_id)
        if refreshed.source_analysis_job_id is not None:
            child = app.jobs.get(refreshed.source_analysis_job_id)
            if child.state is JobState.QUEUED:
                result = app.source_analysis.run_to_completion(
                    child.job_id,
                    worker_id="research-analysis-child",
                )
                assert result.done is True


def _drive_to_synthesis_wait(
    app: AthenaApplication,
    job_id,
    *,
    limit: int = 100,
):
    for _ in range(limit):
        result = _advance_parent_until_wait(app, job_id)
        if result.completed_stage == "awaiting_synthesis":
            return result
        _run_queued_children(app, job_id)
    raise AssertionError("Research did not reach awaiting_synthesis.")


def test_research_orchestrates_processing_analysis_and_honest_coverage(
    tmp_path: Path,
) -> None:
    app, _provider = _app(tmp_path / "runtime")
    raw = _capture(app, tmp_path / "raw.txt", "raw relevant evidence")
    ready = _capture(
        app,
        tmp_path / "ready.txt",
        "NO_RELEVANT_EVIDENCE but still process this source",
    )
    _preprocess(app, ready.source_id)

    job = app.research.enqueue_local(query="Find the relevant evidence.")
    final = _drive_to_synthesis_wait(app, job.job_id)

    scope = app.research.initialize(job.job_id)
    work = app.research_repository.list_work_items(scope.scope_id)
    coverage = app.research.coverage(job.job_id)

    assert final.job.state is JobState.WAITING
    assert final.job.blocked_reason == WaitingReason.DEPENDENCY.value
    assert scope.state is ResearchScopeState.RUNNING
    assert len(work) == 2
    assert {item.state for item in work} == {
        ResearchWorkState.SUCCESSFUL,
        ResearchWorkState.IRRELEVANT,
    }
    raw_work = next(
        item
        for item in work
        if app.research_repository.get_candidate(item.candidate_id).source_id
        == raw.source_id
    )
    ready_work = next(
        item
        for item in work
        if app.research_repository.get_candidate(item.candidate_id).source_id
        == ready.source_id
    )
    assert raw_work.source_processing_job_id is not None
    assert ready_work.source_processing_job_id is None
    assert all(item.source_analysis_job_id is not None for item in work)
    assert coverage.coverage_ratio == 1.0
    assert coverage.successful_count == 1
    assert coverage.irrelevant_count == 1
    assert scope.model_signature_id is not None
    for item in work:
        assert item.source_analysis_job_id is not None
        child = app.source_analysis_service.pinned_configuration(
            app.jobs.get(item.source_analysis_job_id)
        )
        assert child.model_signature_id == scope.model_signature_id
    app.stop()


def test_crash_after_child_enqueue_before_link_recovers_single_orphan(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app, _provider = _app(tmp_path / "runtime")
    _capture(app, tmp_path / "source.txt", "crash recovery evidence")
    job = app.research.enqueue_local(query="Crash recovery research.")
    leased = app.jobs.acquire(job.job_id, worker_id="crash-parent", lease_seconds=60)
    assert leased.lease_token is not None

    for expected in ("initialize", "candidate_freeze", "running"):
        result = app.research_worker.step(
            job.job_id,
            lease_token=leased.lease_token,
            extend_seconds=60,
        )
        assert result.completed_stage == expected

    scope = app.research.initialize(job.job_id)
    work = app.research_repository.list_work_items(scope.scope_id)
    assert len(work) == 1
    work_item = work[0]

    original = app.research_repository.link_source_processing_job_fenced

    def crash_before_link(*args, **kwargs):
        raise RuntimeError("simulated hard boundary after child enqueue")

    monkeypatch.setattr(
        app.research_repository,
        "link_source_processing_job_fenced",
        crash_before_link,
    )
    with pytest.raises(RuntimeError, match="simulated hard boundary"):
        app.research_worker.step(
            job.job_id,
            lease_token=leased.lease_token,
            extend_seconds=60,
        )
    monkeypatch.setattr(
        app.research_repository,
        "link_source_processing_job_fenced",
        original,
    )

    child_rows = app.database.connection.execute(
        """
        SELECT job_id FROM jobs
        WHERE job_type = 'source.process'
          AND json_extract(requested_scope_json, '$.research_work_item_id') = ?
        """,
        (str(work_item.work_item_id),),
    ).fetchall()
    assert len(child_rows) == 1
    assert (
        app.research_repository.get_work_item(
            work_item.work_item_id
        ).source_processing_job_id
        is None
    )

    crashed = app.jobs.get(job.job_id)
    assert crashed.lease_expires_at_us is not None
    app.jobs.recover_startup(now_us=crashed.lease_expires_at_us + 1)
    resumed = app.jobs.acquire(
        job.job_id,
        worker_id="crash-parent-resumed",
        lease_seconds=60,
        now_us=crashed.lease_expires_at_us + 2,
    )
    assert resumed.lease_token is not None
    result = app.research_worker.step(
        job.job_id,
        lease_token=resumed.lease_token,
        extend_seconds=60,
    )
    assert result.waiting is True
    linked = app.research_repository.get_work_item(work_item.work_item_id)
    assert linked.source_processing_job_id is not None

    child_rows = app.database.connection.execute(
        """
        SELECT job_id FROM jobs
        WHERE job_type = 'source.process'
          AND json_extract(requested_scope_json, '$.research_work_item_id') = ?
        """,
        (str(work_item.work_item_id),),
    ).fetchall()
    assert len(child_rows) == 1
    app.stop()


def test_model_drift_between_candidates_waits_user_without_mixed_child(
    tmp_path: Path,
) -> None:
    app, provider = _app(tmp_path / "runtime")
    first = _capture(app, tmp_path / "a.txt", "first relevant source")
    second = _capture(app, tmp_path / "b.txt", "second relevant source")
    _preprocess(app, first.source_id)
    _preprocess(app, second.source_id)
    job = app.research.enqueue_local(query="Use one pinned model.")

    first_wait = _advance_parent_until_wait(app, job.job_id)
    assert first_wait.completed_stage == "waiting_source_analysis"
    _run_queued_children(app, job.job_id)

    lease_token = _acquire_parent(app, job.job_id, worker="drift-parent")
    classified = app.research_worker.step(
        job.job_id,
        lease_token=lease_token,
        extend_seconds=120,
    )
    assert classified.completed_stage == "source_analysis_classified"

    provider.quantization = "Q5"
    drifted = app.research_worker.step(
        job.job_id,
        lease_token=lease_token,
        extend_seconds=120,
    )
    assert drifted.waiting is True
    assert drifted.job.state is JobState.WAITING
    assert drifted.job.blocked_reason == WaitingReason.USER.value

    scope = app.research.initialize(job.job_id)
    work = app.research_repository.list_work_items(scope.scope_id)
    assert sum(item.state is ResearchWorkState.SUCCESSFUL for item in work) == 1
    analysis_children = [
        item.source_analysis_job_id
        for item in work
        if item.source_analysis_job_id is not None
    ]
    assert len(analysis_children) == 1
    app.stop()


def test_failed_analysis_child_lowers_coverage(tmp_path: Path) -> None:
    app, _provider = _app(tmp_path / "runtime")
    source = _capture(app, tmp_path / "source.txt", "failure evidence")
    _preprocess(app, source.source_id)
    job = app.research.enqueue_local(query="Failure must stay visible.")

    waiting = _advance_parent_until_wait(app, job.job_id)
    assert waiting.completed_stage == "waiting_source_analysis"
    scope = app.research.initialize(job.job_id)
    work = app.research_repository.list_work_items(scope.scope_id)
    assert len(work) == 1 and work[0].source_analysis_job_id is not None
    child_id = work[0].source_analysis_job_id
    assert child_id is not None
    leased_child = app.jobs.acquire(
        child_id,
        worker_id="forced-analysis-failure",
        lease_seconds=60,
    )
    assert leased_child.lease_token is not None
    app.jobs.fail(
        child_id,
        lease_token=leased_child.lease_token,
        blocked_reason="forced_test_failure",
    )

    result = _drive_to_synthesis_wait(app, job.job_id)
    assert result.completed_stage == "awaiting_synthesis"
    coverage = app.research.coverage(job.job_id)
    assert coverage.failed_count == 1
    assert coverage.successful_count == 0
    assert coverage.coverage_ratio == 0.0
    app.stop()


def test_missing_raw_blob_is_unavailable_not_irrelevant(tmp_path: Path) -> None:
    app, _provider = _app(tmp_path / "runtime")
    source = _capture(app, tmp_path / "source.txt", "offline archive evidence")
    stored = app.sources.verify(source.source_id)
    stored.unlink()

    job = app.research.enqueue_local(query="Unavailable must stay visible.")
    result = _drive_to_synthesis_wait(app, job.job_id)
    assert result.completed_stage == "awaiting_synthesis"

    scope = app.research.initialize(job.job_id)
    work = app.research_repository.list_work_items(scope.scope_id)
    assert len(work) == 1
    assert work[0].state is ResearchWorkState.UNAVAILABLE
    assert work[0].source_processing_job_id is None
    assert work[0].source_analysis_job_id is None
    coverage = app.research.coverage(job.job_id)
    assert coverage.unavailable_count == 1
    assert coverage.irrelevant_count == 0
    assert coverage.coverage_ratio == 0.0
    app.stop()


def test_cancel_preserves_confirmed_work_and_never_claims_complete(
    tmp_path: Path,
) -> None:
    app, _provider = _app(tmp_path / "runtime")
    first = _capture(app, tmp_path / "a.txt", "first cancel evidence")
    second = _capture(app, tmp_path / "b.txt", "second cancel evidence")
    _preprocess(app, first.source_id)
    _preprocess(app, second.source_id)
    job = app.research.enqueue_local(query="Cancel after one source.")

    waiting = _advance_parent_until_wait(app, job.job_id)
    assert waiting.completed_stage == "waiting_source_analysis"
    _run_queued_children(app, job.job_id)

    lease_token = _acquire_parent(app, job.job_id, worker="cancel-parent")
    classified = app.research_worker.step(
        job.job_id,
        lease_token=lease_token,
        extend_seconds=120,
    )
    assert classified.completed_stage == "source_analysis_classified"

    requested = app.research.cancel(job.job_id)
    assert requested.state is JobState.CANCEL_REQUESTED
    cancelled = app.research_worker.step(
        job.job_id,
        lease_token=lease_token,
        extend_seconds=120,
    )
    assert cancelled.done is True
    assert cancelled.job.state is JobState.CANCELLED

    scope = app.research.initialize(job.job_id)
    assert scope.state is ResearchScopeState.PARTIAL
    work = app.research_repository.list_work_items(scope.scope_id)
    assert sum(item.state is ResearchWorkState.SUCCESSFUL for item in work) == 1
    assert sum(item.state is ResearchWorkState.PENDING for item in work) == 1
    app.stop()


def test_scheduler_drives_research_dependency_polling_to_synthesis_without_retry_budget(
    tmp_path: Path,
) -> None:
    app, _provider = _app(tmp_path / "runtime")
    first = _capture(app, tmp_path / "a.txt", "scheduler alpha evidence")
    second = _capture(app, tmp_path / "b.txt", "scheduler beta evidence")
    job = app.research.enqueue_local(
        query="Scheduler research.",
        explicit_source_ids=(first.source_id, second.source_id),
    )
    now_us = utc_now_us()

    for ordinal in range(100):
        tick = app.job_scheduler.tick(
            worker_id=f"research-scheduler-{ordinal % 2}",
            now_us=now_us,
        )
        parent = app.jobs.get(job.job_id)
        if (
            parent.state is JobState.WAITING
            and parent.blocked_reason == WaitingReason.DEPENDENCY.value
            and parent.current_stage == "research_awaiting_synthesis"
            and parent.next_run_at_us is not None
        ):
            break

        if tick.idle:
            due = [
                waiting.next_run_at_us
                for waiting in app.jobs.waiting(limit=200)
                if waiting.next_run_at_us is not None
            ]
            if due:
                now_us = max(now_us + 1, min(due) + 1)
            else:
                now_us += 1_000_000
        else:
            # A dispatched job may have created immediately eligible child work.
            # Keep simulated time before the parent's dependency poll deadline so
            # the scheduler gets the same immediate next tick as production.
            now_us += 1
    else:
        raise AssertionError("Scheduler did not drive Research to awaiting_synthesis.")

    parent = app.jobs.get(job.job_id)
    assert parent.retry_count == 0
    scope = app.research.initialize(job.job_id)
    work = app.research_repository.list_work_items(scope.scope_id)
    coverage = app.research.coverage(job.job_id)

    assert scope.state is ResearchScopeState.RUNNING
    assert len(work) == 2
    assert all(item.state is ResearchWorkState.SUCCESSFUL for item in work)
    assert all(item.source_processing_job_id is not None for item in work)
    assert all(item.source_analysis_job_id is not None for item in work)
    assert coverage.processed_count == 2
    assert coverage.successful_count == 2
    assert coverage.failed_count == 0
    assert coverage.unavailable_count == 0
    assert coverage.coverage_ratio == 1.0
    app.stop()


def test_research_child_identity_unique_index_blocks_duplicate_jobs(
    tmp_path: Path,
) -> None:
    app, _provider = _app(tmp_path / "runtime")
    source = _capture(app, tmp_path / "source.txt", "unique child identity")
    job = app.research.enqueue_local(query="Child identity.")
    scope = app.research.initialize(job.job_id)
    app.research.freeze_candidates(job.job_id)
    work = app.research_repository.list_work_items(scope.scope_id)
    assert len(work) == 1

    first = app.source_processing.enqueue(
        source.source_id,
        research_work_item_id=work[0].work_item_id,
    )
    with pytest.raises(sqlite3.IntegrityError):
        app.source_processing.enqueue(
            source.source_id,
            research_work_item_id=work[0].work_item_id,
        )

    rows = app.database.connection.execute(
        """
        SELECT job_id FROM jobs
        WHERE job_type = 'source.process'
          AND json_extract(requested_scope_json, '$.research_work_item_id') = ?
        """,
        (str(work[0].work_item_id),),
    ).fetchall()
    assert len(rows) == 1
    assert bytes(rows[0]["job_id"]) == first.job_id.bytes
    app.stop()


def test_research_parent_does_not_consume_retry_budget_for_waiting_child(
    tmp_path: Path,
) -> None:
    app, _provider = _app(
        tmp_path / "runtime"
    )

    _capture(
        app,
        tmp_path / "source.txt",
        "Research child retry ownership evidence.",
    )

    job = app.research.enqueue_local(
        query="Exercise child retry ownership."
    )

    waiting = _advance_parent_until_wait(
        app,
        job.job_id,
    )

    assert waiting.completed_stage == "waiting_source_processing"
    assert waiting.job.blocked_reason == WaitingReason.DEPENDENCY.value
    assert waiting.job.retry_count == 0

    scope = app.research.initialize(
        job.job_id
    )

    work = app.research_repository.list_work_items(
        scope.scope_id
    )

    assert len(work) == 1
    assert work[0].source_processing_job_id is not None

    child_id = work[0].source_processing_job_id
    assert child_id is not None

    child = app.jobs.get(
        child_id
    )

    assert child.state is JobState.QUEUED

    leased_child = app.jobs.acquire(
        child_id,
        worker_id="research-child-retry-owner",
        lease_seconds=60,
    )

    assert leased_child.lease_token is not None

    child_waiting = app.jobs.wait(
        child_id,
        lease_token=leased_child.lease_token,
        reason=WaitingReason.NETWORK,
    )

    assert child_waiting.retry_count == 0

    scheduled_child, retry_at = (
        app.job_scheduler._schedule_retry_if_allowed(
            child_waiting,
            utc_now_us(),
        )
    )

    assert retry_at is not None
    assert scheduled_child.retry_count == 1
    assert scheduled_child.blocked_reason == WaitingReason.NETWORK.value

    parent_before = app.jobs.get(
        job.job_id
    )

    assert parent_before.retry_count == 0

    lease_token = _acquire_parent(
        app,
        job.job_id,
        worker="research-parent-child-retry",
    )

    reconciled = app.research_worker.step(
        job.job_id,
        lease_token=lease_token,
        extend_seconds=120,
    )

    assert reconciled.waiting is True
    assert reconciled.job.state is JobState.WAITING
    assert (
        reconciled.job.blocked_reason
        == WaitingReason.DEPENDENCY.value
    )
    assert reconciled.job.retry_count == 0

    child_after = app.jobs.get(
        child_id
    )

    assert child_after.retry_count == 1
    assert child_after.blocked_reason == WaitingReason.NETWORK.value

    app.stop()
