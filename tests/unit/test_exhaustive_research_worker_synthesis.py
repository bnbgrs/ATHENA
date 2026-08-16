from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path

import pytest

from athena.common.time import utc_now_us
from athena.config.settings import AthenaSettings
from athena.core.application import AthenaApplication
from athena.jobs.models import JobState
from athena.model.adapters.lm_studio import ProviderOutputLimitError
from athena.model.domain import ModelChatMessage, ModelInfo
from athena.research.models import (
    ResearchScopeState,
    ResearchSynthesisStage,
    ResearchSynthesisWorkState,
)


@dataclass
class _WorkerProvider:
    research_output_limit_failures: int = 0
    research_validation_output_limit_failures: int = 0
    calls: list[tuple[str, tuple[ModelChatMessage, ...]]] = field(
        default_factory=list
    )

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
                context_capacity=4_000,
                loaded_context_length=4_000,
                quantization="Q4",
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
        if schema_id.startswith("athena_research_synthesis_"):
            if self.research_output_limit_failures > 0:
                self.research_output_limit_failures -= 1
                raise ProviderOutputLimitError(
                    "configured output-token limit reached"
                )
            granular_refs = re.findall(
                r"INPUT-\d{3}-(?:FINDING|CONTRADICTION)-\d{3}",
                text,
            )
            direct_refs = re.findall(
                r"(INPUT-\d{3}) kind=source_analysis_artifact",
                text,
            )
            refs = sorted(
                set(granular_refs + direct_refs)
            )
            assert refs
            if self.research_validation_output_limit_failures > 0:
                self.research_validation_output_limit_failures -= 1
                return {
                    "summary": "x" * 4000,
                    "findings": [
                        {
                            "text": "bounded research finding",
                            "evidence_refs": refs,
                        }
                    ],
                    "contradictions": [],
                    "uncertainty": "",
                }
            return {
                "summary": "worker research synthesis",
                "findings": [
                    {
                        "text": "worker combined finding",
                        "evidence_refs": refs,
                    }
                ],
                "contradictions": [],
                "uncertainty": "bounded to durable source analyses",
            }
        if "map" in schema_id:
            relevant = "NO_RELEVANT_EVIDENCE" not in text
            return {
                "relevant": relevant,
                "summary": "map summary",
                "findings": ["source finding"] if relevant else [],
                "contradictions": [],
                "uncertainty": "",
            }
        return {
            "summary": "source synthesis",
            "findings": ["source finding"],
            "contradictions": [],
            "uncertainty": "",
        }

    def stream_chat(self, *, model_id: str, messages):
        del model_id, messages
        yield "unused"


def _app(root: Path) -> tuple[AthenaApplication, _WorkerProvider]:
    app = AthenaApplication(settings=AthenaSettings(local_root=root))
    app.start()
    provider = _WorkerProvider()
    app.source_analysis_service.provider = provider
    app.research_synthesis.provider = provider
    return app, provider


def _capture(app: AthenaApplication, path: Path, text: str):
    path.write_text(text, encoding="utf-8", newline="")
    return app.sources.capture_file(path).source


def _tick_until(
    app: AthenaApplication,
    job_id,
    *,
    predicate,
    max_ticks: int = 200,
):
    now = utc_now_us()
    last = None
    for index in range(max_ticks):
        last = app.job_scheduler.tick(
            worker_id=f"research-b2-scheduler-{index}",
            now_us=now,
        )
        current = app.jobs.get(job_id)
        if predicate(current):
            return last, current
        if last.idle:
            due = [
                item.next_run_at_us
                for item in app.jobs.waiting(limit=256)
                if item.next_run_at_us is not None
            ]
            if due:
                now = max(utc_now_us(), min(due) + 1)
            else:
                now = utc_now_us()
        else:
            now = utc_now_us()
    raise AssertionError("Scheduler did not reach the requested Research boundary.")


def _run_to_terminal(app: AthenaApplication, job_id):
    _last, current = _tick_until(
        app,
        job_id,
        predicate=lambda job: job.state.terminal,
    )
    return current


def _run_to_synthesis_wait(app: AthenaApplication, job_id):
    _last, current = _tick_until(
        app,
        job_id,
        predicate=lambda job: (
            job.state is JobState.WAITING
            and job.current_stage == "research_awaiting_synthesis"
        ),
    )
    return current


def test_scheduler_only_research_reaches_result_with_context_provenance(
    tmp_path: Path,
) -> None:
    app, provider = _app(tmp_path / "runtime")
    _capture(app, tmp_path / "relevant.txt", "relevant evidence alpha")
    _capture(
        app,
        tmp_path / "irrelevant.txt",
        "NO_RELEVANT_EVIDENCE source beta",
    )
    job = app.research.enqueue_local(query="Aggregate all relevant evidence.")
    waiting = _run_to_synthesis_wait(app, job.job_id)
    assert waiting.next_run_at_us is not None
    commit_before_synthesis = app.research_repository.current_commit_seq()

    completed = _run_to_terminal(app, job.job_id)

    assert completed.state is JobState.COMPLETED
    scope = app.research_repository.get_scope_for_job(job.job_id)
    assert scope is not None
    assert scope.state is ResearchScopeState.COMPLETED
    result = app.research_repository.get_result_for_scope(scope.scope_id)
    assert result is not None
    assert result.final_artifact_id is not None
    payload = json.loads(result.content_json)
    assert payload["findings"] == ["worker combined finding"]
    assert payload["coverage"] == {
        "candidate_total": 2,
        "processed_count": 2,
        "successful_count": 1,
        "irrelevant_count": 1,
        "failed_count": 0,
        "unavailable_count": 0,
        "excluded_count": 0,
        "eligible_count": 2,
        "coverage_ratio": 1.0,
    }
    assert payload["problem_sources"] == []

    final_artifact = app.research_repository.get_synthesis_artifact(
        result.final_artifact_id
    )
    run = app.model_runs.load_run(final_artifact.processing_run_id)
    snapshot = json.loads(run.input_snapshot_json)
    assert snapshot["research_snapshot_commit_seq"] == scope.snapshot_commit_seq
    package = snapshot["context_package"]
    assert package["structured_output"]["schema_id"] == (
        "athena_research_synthesis_final_v1"
    )
    assert {
        ref["entity_type"] for ref in package["included_refs"]
    } == {"source_analysis_artifact"}
    assert run.model_signature_id == scope.model_signature_id
    assert any(
        schema_id.startswith("athena_research_synthesis_")
        for schema_id, _messages in provider.calls
    )
    assert app.research_repository.current_commit_seq() == commit_before_synthesis
    app.stop()


def test_research_output_token_limit_splits_and_recovers(
    tmp_path: Path,
) -> None:
    app, provider = _app(tmp_path / "runtime")
    for index in range(4):
        _capture(
            app,
            tmp_path / f"source-{index}.txt",
            f"relevant research evidence {index}",
        )

    job = app.research.enqueue_local(
        query="Aggregate all relevant evidence."
    )
    _run_to_synthesis_wait(app, job.job_id)
    provider.research_output_limit_failures = 1

    completed = _run_to_terminal(app, job.job_id)

    assert completed.state is JobState.COMPLETED
    assert provider.research_output_limit_failures == 0

    scope = app.research_repository.get_scope_for_job(job.job_id)
    assert scope is not None
    synthesis_work = app.research_repository.list_synthesis_work_items(
        scope.scope_id
    )
    assert any(
        item.state is ResearchSynthesisWorkState.SPLIT
        for item in synthesis_work
    )
    assert any(
        item.stage is ResearchSynthesisStage.REDUCE
        and item.state is ResearchSynthesisWorkState.COMPLETED
        for item in synthesis_work
    )

    result = app.research_repository.get_result_for_scope(scope.scope_id)
    assert result is not None
    assert result.final_artifact_id is not None
    app.stop()


def test_research_valid_complete_output_above_estimator_reserve_is_accepted(
    tmp_path: Path,
) -> None:
    app, provider = _app(tmp_path / "runtime")
    for index in range(4):
        _capture(
            app,
            tmp_path / f"validation-source-{index}.txt",
            f"relevant validation evidence {index}",
        )

    job = app.research.enqueue_local(
        query="Aggregate all relevant evidence."
    )
    _run_to_synthesis_wait(app, job.job_id)
    provider.research_validation_output_limit_failures = 1

    completed = _run_to_terminal(app, job.job_id)

    assert completed.state is JobState.COMPLETED
    assert provider.research_validation_output_limit_failures == 0

    scope = app.research_repository.get_scope_for_job(job.job_id)
    assert scope is not None
    synthesis_work = app.research_repository.list_synthesis_work_items(
        scope.scope_id
    )
    assert not any(
        item.state is ResearchSynthesisWorkState.SPLIT
        for item in synthesis_work
    )

    result = app.research_repository.get_result_for_scope(scope.scope_id)
    assert result is not None
    assert result.final_artifact_id is not None
    app.stop()


def test_research_two_input_output_limit_uses_singleton_compression_and_recovers(
    tmp_path: Path,
) -> None:
    app, provider = _app(tmp_path / "runtime")
    for index in range(2):
        _capture(
            app,
            tmp_path / f"two-input-source-{index}.txt",
            f"relevant two-input evidence {index}",
        )

    job = app.research.enqueue_local(
        query="Aggregate both relevant evidence sources."
    )
    _run_to_synthesis_wait(app, job.job_id)
    provider.research_output_limit_failures = 1

    completed = _run_to_terminal(app, job.job_id)

    assert completed.state is JobState.COMPLETED
    assert provider.research_output_limit_failures == 0

    scope = app.research_repository.get_scope_for_job(job.job_id)
    assert scope is not None
    synthesis_work = app.research_repository.list_synthesis_work_items(
        scope.scope_id
    )

    singleton_reduces = [
        item
        for item in synthesis_work
        if item.stage is ResearchSynthesisStage.REDUCE
        and len(
            app.research_repository.synthesis_inputs_for_work_item(
                item.work_item_id
            )
        )
        == 1
    ]
    assert len(singleton_reduces) == 2
    assert all(
        item.state is ResearchSynthesisWorkState.COMPLETED
        for item in singleton_reduces
    )

    result = app.research_repository.get_result_for_scope(scope.scope_id)
    assert result is not None
    assert result.final_artifact_id is not None
    app.stop()


def test_legacy_awaiting_synthesis_wait_is_auto_woken_and_finalizes_without_model(
    tmp_path: Path,
) -> None:
    app, provider = _app(tmp_path / "runtime")
    source = _capture(
        app,
        tmp_path / "unavailable.txt",
        "archive bytes will be removed",
    )
    stored = app.sources.verify(source.source_id)
    stored.unlink()
    job = app.research.enqueue_local(query="Keep unavailable coverage honest.")
    commit_before = app.research_repository.current_commit_seq()

    waiting = _run_to_synthesis_wait(app, job.job_id)
    assert waiting.next_run_at_us is not None

    with app.database.write_transaction() as connection:
        connection.execute(
            "UPDATE jobs SET next_run_at_us = NULL WHERE job_id = ?",
            (job.job_id.bytes,),
        )

    tick = app.job_scheduler.tick(
        worker_id="legacy-research-synthesis-resume",
        now_us=utc_now_us(),
    )
    completed = app.jobs.get(job.job_id)
    assert tick.woken_jobs >= 1
    assert completed.state is JobState.COMPLETED

    scope = app.research_repository.get_scope_for_job(job.job_id)
    assert scope is not None and scope.state is ResearchScopeState.COMPLETED
    result = app.research_repository.get_result_for_scope(scope.scope_id)
    assert result is not None
    assert result.final_artifact_id is None
    payload = json.loads(result.content_json)
    assert payload["coverage"]["successful_count"] == 0
    assert payload["coverage"]["unavailable_count"] == 1
    assert payload["coverage"]["coverage_ratio"] == 0.0
    assert payload["problem_sources"] == [
        {
            "candidate_ordinal": 0,
            "source_id": str(source.source_id),
            "state": "unavailable",
        }
    ]
    assert not any(
        schema_id.startswith("athena_research_synthesis_")
        for schema_id, _messages in provider.calls
    )
    assert app.research_repository.current_commit_seq() == commit_before
    app.stop()


def test_result_commit_survives_crash_before_parent_job_complete(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app, _provider = _app(tmp_path / "runtime")
    _capture(app, tmp_path / "source.txt", "durable crash recovery evidence")
    job = app.research.enqueue_local(query="Crash after durable result commit.")

    _run_to_synthesis_wait(app, job.job_id)
    app.jobs.wake(job.job_id)
    leased = app.jobs.acquire(
        job.job_id,
        worker_id="result-crash-parent",
        lease_seconds=120,
    )
    assert leased.lease_token is not None

    artifact_boundary = app.research_worker.step(
        job.job_id,
        lease_token=leased.lease_token,
        extend_seconds=120,
    )
    assert artifact_boundary.completed_stage == "synthesis_artifact"
    assert artifact_boundary.done is False

    original_complete = app.jobs.complete

    def crash_before_job_complete(*args, **kwargs):
        raise RuntimeError("simulated crash after ResearchResult commit")

    monkeypatch.setattr(app.jobs, "complete", crash_before_job_complete)
    with pytest.raises(
        RuntimeError,
        match="simulated crash after ResearchResult commit",
    ):
        app.research_worker.step(
            job.job_id,
            lease_token=leased.lease_token,
            extend_seconds=120,
        )
    monkeypatch.setattr(app.jobs, "complete", original_complete)

    scope = app.research_repository.get_scope_for_job(job.job_id)
    assert scope is not None
    assert scope.state is ResearchScopeState.COMPLETED
    durable_result = app.research_repository.get_result_for_scope(
        scope.scope_id
    )
    assert durable_result is not None
    still_running = app.jobs.get(job.job_id)
    assert still_running.state is JobState.RUNNING
    assert still_running.lease_expires_at_us is not None

    recovery_now = still_running.lease_expires_at_us + 1
    app.jobs.recover_startup(now_us=recovery_now)
    resumed = app.jobs.acquire(
        job.job_id,
        worker_id="result-crash-resumed",
        lease_seconds=120,
        now_us=recovery_now + 1,
    )
    assert resumed.lease_token is not None
    resumed_result = app.research_worker.step(
        job.job_id,
        lease_token=resumed.lease_token,
        extend_seconds=120,
    )
    assert resumed_result.done is True
    assert resumed_result.job.state is JobState.COMPLETED

    after = app.research_repository.get_result_for_scope(scope.scope_id)
    assert after is not None
    assert after.result_id == durable_result.result_id
    result_count = app.database.connection.execute(
        "SELECT COUNT(*) FROM research_results WHERE scope_id = ?",
        (scope.scope_id.bytes,),
    ).fetchone()[0]
    artifact_count = app.database.connection.execute(
        "SELECT COUNT(*) FROM research_synthesis_artifacts WHERE scope_id = ?",
        (scope.scope_id.bytes,),
    ).fetchone()[0]
    assert result_count == 1
    assert artifact_count == 1
    app.stop()
