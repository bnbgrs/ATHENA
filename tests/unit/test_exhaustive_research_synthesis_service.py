from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path

import pytest

import athena.research.synthesis_service as synthesis_module
from athena.config.settings import AthenaSettings
from athena.core.application import AthenaApplication
from athena.jobs.models import JobState
from athena.model.domain import ModelChatMessage, ModelInfo
from athena.research.models import (
    ResearchSynthesisInputKind,
    ResearchSynthesisStage,
    ResearchSynthesisWorkState,
)
from athena.research.synthesis_service import (
    PIPELINE_VERSION,
    PROMPT_TEMPLATE_ID,
    PROMPT_TEMPLATE_VERSION,
    ResearchSynthesisInputTooLargeError,
    ResearchSynthesisOutputError,
    ResearchSynthesisService,
)
from athena.source.analysis_service import SourceAnalysisModelDriftError


@dataclass
class _SynthesisProvider:
    quantization: str = "Q4"
    invalid_research_ref: bool = False
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
        if schema_id.startswith("athena_research_synthesis_"):
            refs = sorted(set(re.findall(r"INPUT-\d{3}", text)))
            if self.invalid_research_ref:
                refs = ["INPUT-999"]
            return {
                "summary": "research synthesis summary",
                "findings": [
                    {
                        "text": "combined research finding",
                        "evidence_refs": refs,
                    }
                ],
                "contradictions": [
                    {
                        "text": "preserved disagreement",
                        "evidence_refs": refs,
                    }
                ],
                "uncertainty": "bounded to supplied artifacts",
            }
        if "map" in schema_id:
            return {
                "relevant": True,
                "summary": "map summary",
                "findings": ["supported source finding"],
                "contradictions": [],
                "uncertainty": "",
            }
        return {
            "summary": "source synthesis summary",
            "findings": ["supported source finding"],
            "contradictions": [],
            "uncertainty": "",
        }

    def stream_chat(self, *, model_id: str, messages):
        del model_id, messages
        yield "unused"


def _app(root: Path) -> tuple[AthenaApplication, _SynthesisProvider]:
    app = AthenaApplication(settings=AthenaSettings(local_root=root))
    app.start()
    provider = _SynthesisProvider()
    app.source_analysis_service.provider = provider
    return app, provider


def _capture(app: AthenaApplication, path: Path, text: str):
    path.write_text(text, encoding="utf-8", newline="")
    return app.sources.capture_file(path).source


def _acquire_parent(app: AthenaApplication, job_id):
    current = app.jobs.get(job_id)
    if current.state is JobState.WAITING:
        app.jobs.wake(job_id)
    leased = app.jobs.acquire(
        job_id,
        worker_id="research-synthesis-service-parent",
        lease_seconds=120,
    )
    assert leased.lease_token is not None
    return leased.lease_token


def _advance_parent_until_wait(
    app: AthenaApplication,
    job_id,
    *,
    max_steps: int = 50,
):
    lease_token = _acquire_parent(app, job_id)
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
                    worker_id="research-synthesis-service-source-child",
                )
                assert result.done is True
        refreshed = app.research_repository.get_work_item(work.work_item_id)
        if refreshed.source_analysis_job_id is not None:
            child = app.jobs.get(refreshed.source_analysis_job_id)
            if child.state is JobState.QUEUED:
                result = app.source_analysis.run_to_completion(
                    child.job_id,
                    worker_id="research-synthesis-service-analysis-child",
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


def _prepare_research(
    tmp_path: Path,
    *,
    source_count: int,
):
    app, provider = _app(tmp_path / "runtime")
    for index in range(source_count):
        _capture(
            app,
            tmp_path / f"source-{index}.txt",
            f"distinct relevant evidence {index}",
        )
    job = app.research.enqueue_local(query="Aggregate all relevant evidence.")
    waiting = _drive_to_synthesis_wait(app, job.job_id)
    assert waiting.completed_stage == "awaiting_synthesis"
    scope = app.research.initialize(job.job_id)
    lease_token = _acquire_parent(app, job.job_id)
    service = ResearchSynthesisService(
        repository=app.research_repository,
        source_analysis=app.source_analysis_service,
    )
    return app, provider, job, scope, lease_token, service


def test_context_package_call_persists_output_evidence_and_no_canonical_write(
    tmp_path: Path,
) -> None:
    app, provider, job, scope, lease_token, service = _prepare_research(
        tmp_path,
        source_count=2,
    )
    source_artifacts = (
        app.research_repository.successful_source_analysis_final_artifact_ids(
            scope.scope_id
        )
    )
    commit_before = app.research_repository.current_commit_seq()

    work = service.plan_next_synthesis(
        scope,
        parent_job_id=job.job_id,
        lease_token=lease_token,
    )
    prepared = service.prepare_call(scope, work)
    assert tuple(item.ref_id for item in prepared.inputs) == (
        "INPUT-001",
        "INPUT-002",
    )

    artifact = service.execute_call(
        scope=scope,
        parent_job_id=job.job_id,
        lease_token=lease_token,
        prepared=prepared,
        extend_seconds=120,
    )

    assert provider.calls[-1][0] == "athena_research_synthesis_final_v1"
    content = json.loads(artifact.content_json)
    assert content == {
        "contradictions": ["preserved disagreement"],
        "findings": ["combined research finding"],
        "summary": "research synthesis summary",
        "uncertainty": "bounded to supplied artifacts",
    }
    evidence = app.research_repository.synthesis_evidence_for_artifact(
        artifact.artifact_id
    )
    assert {
        (item.output_kind, item.output_ordinal, item.input_ordinal)
        for item in evidence
    } == {
        ("finding", 0, 0),
        ("finding", 0, 1),
        ("contradiction", 0, 0),
        ("contradiction", 0, 1),
    }
    assert (
        app.research_repository.source_analysis_artifact_ids_for_synthesis_output(
            artifact.artifact_id,
            output_kind="finding",
            output_ordinal=0,
        )
        == tuple(sorted(source_artifacts, key=lambda item: item.bytes))
    )

    run = app.model_runs.load_run(artifact.processing_run_id)
    snapshot = json.loads(run.input_snapshot_json)
    package = snapshot["context_package"]
    assert snapshot["research_snapshot_commit_seq"] == scope.snapshot_commit_seq
    assert snapshot["context_snapshot_commit_seq"] == package["snapshot_commit_seq"]
    assert [item["ref_id"] for item in package["included_refs"]] == [
        "INPUT-001",
        "INPUT-002",
    ]
    assert {
        item["entity_type"] for item in package["included_refs"]
    } == {"source_analysis_artifact"}
    assert package["structured_output"]["schema_id"] == (
        "athena_research_synthesis_final_v1"
    )
    assert run.model_signature_id == scope.model_signature_id
    assert run.pipeline_version == PIPELINE_VERSION
    assert run.prompt_template_id == PROMPT_TEMPLATE_ID
    assert run.prompt_template_version == PROMPT_TEMPLATE_VERSION
    assert app.research_repository.current_commit_seq() == commit_before

    app.jobs.yield_job(job.job_id, lease_token=lease_token)
    app.stop()


def test_unknown_model_evidence_ref_fails_closed_without_artifact(
    tmp_path: Path,
) -> None:
    app, provider, job, scope, lease_token, service = _prepare_research(
        tmp_path,
        source_count=2,
    )
    provider.invalid_research_ref = True
    work = service.plan_next_synthesis(
        scope,
        parent_job_id=job.job_id,
        lease_token=lease_token,
    )
    prepared = service.prepare_call(scope, work)

    with pytest.raises(
        ResearchSynthesisOutputError,
        match="unknown evidence ref",
    ):
        service.execute_call(
            scope=scope,
            parent_job_id=job.job_id,
            lease_token=lease_token,
            prepared=prepared,
            extend_seconds=120,
        )

    refreshed = app.research_repository.get_synthesis_work_item(
        work.work_item_id
    )
    assert refreshed.state is ResearchSynthesisWorkState.PENDING
    assert refreshed.attempt_count == 1
    assert (
        app.research_repository.synthesis_artifact_for_work_item(
            work.work_item_id
        )
        is None
    )
    run_status = app.database.connection.execute(
        """
        SELECT status
        FROM processing_runs
        WHERE run_type = 'research_synthesis_final'
        ORDER BY started_at_us DESC
        LIMIT 1
        """
    ).fetchone()
    assert run_status is not None
    assert str(run_status["status"]) == "failed"

    app.jobs.yield_job(job.job_id, lease_token=lease_token)
    app.stop()


def test_split_carries_singleton_leaf_into_next_final(
    tmp_path: Path,
) -> None:
    app, _provider, job, scope, lease_token, service = _prepare_research(
        tmp_path,
        source_count=3,
    )
    source_artifacts = (
        app.research_repository.successful_source_analysis_final_artifact_ids(
            scope.scope_id
        )
    )
    first_final = service.plan_next_synthesis(
        scope,
        parent_job_id=job.job_id,
        lease_token=lease_token,
    )
    children = service.split_synthesis_work(
        scope,
        first_final,
        parent_job_id=job.job_id,
        lease_token=lease_token,
    )
    assert len(children) == 1
    child = children[0]
    assert child.stage is ResearchSynthesisStage.REDUCE
    assert child.state is ResearchSynthesisWorkState.PENDING
    assert (
        app.research_repository.get_synthesis_work_item(
            first_final.work_item_id
        ).state
        is ResearchSynthesisWorkState.SPLIT
    )

    child_prepared = service.prepare_call(scope, child)
    child_artifact = service.execute_call(
        scope=scope,
        parent_job_id=job.job_id,
        lease_token=lease_token,
        prepared=child_prepared,
        extend_seconds=120,
    )
    next_final = service.plan_next_synthesis(
        scope,
        parent_job_id=job.job_id,
        lease_token=lease_token,
    )
    next_inputs = app.research_repository.synthesis_inputs_for_work_item(
        next_final.work_item_id
    )
    resolved = {
        (
            item.input_kind,
            item.source_analysis_artifact_id
            if item.input_kind
            is ResearchSynthesisInputKind.SOURCE_ANALYSIS_ARTIFACT
            else item.research_synthesis_artifact_id,
        )
        for item in next_inputs
    }
    consumed_by_child = {
        item.source_analysis_artifact_id
        for item in app.research_repository.synthesis_inputs_for_work_item(
            child.work_item_id
        )
    }
    singleton = next(
        item
        for item in source_artifacts
        if item not in consumed_by_child
    )
    assert resolved == {
        (
            ResearchSynthesisInputKind.SOURCE_ANALYSIS_ARTIFACT,
            singleton,
        ),
        (
            ResearchSynthesisInputKind.RESEARCH_SYNTHESIS_ARTIFACT,
            child_artifact.artifact_id,
        ),
    }
    assert next_final.level > child.level

    app.jobs.yield_job(job.job_id, lease_token=lease_token)
    app.stop()


def test_budget_overflow_is_detected_before_provider_call_and_can_split(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app, provider, job, scope, lease_token, service = _prepare_research(
        tmp_path,
        source_count=4,
    )
    work = service.plan_next_synthesis(
        scope,
        parent_job_id=job.job_id,
        lease_token=lease_token,
    )
    research_calls_before = len(
        [
            schema_id
            for schema_id, _messages in provider.calls
            if schema_id.startswith("athena_research_synthesis_")
        ]
    )
    assert scope.effective_context_limit is not None
    monkeypatch.setattr(
        synthesis_module,
        "estimate_structured_request_tokens",
        lambda *_args, **_kwargs: scope.effective_context_limit,
    )
    with pytest.raises(
        ResearchSynthesisInputTooLargeError,
        match="exceeds pinned input budget",
    ):
        service.prepare_call(scope, work)
    research_calls_after = len(
        [
            schema_id
            for schema_id, _messages in provider.calls
            if schema_id.startswith("athena_research_synthesis_")
        ]
    )
    assert research_calls_after == research_calls_before

    children = service.split_synthesis_work(
        scope,
        work,
        parent_job_id=job.job_id,
        lease_token=lease_token,
    )
    assert len(children) == 2
    assert all(
        child.stage is ResearchSynthesisStage.REDUCE
        and child.state is ResearchSynthesisWorkState.PENDING
        for child in children
    )

    app.jobs.yield_job(job.job_id, lease_token=lease_token)
    app.stop()


def test_research_synthesis_rejects_model_signature_drift_before_call(
    tmp_path: Path,
) -> None:
    app, provider, job, scope, lease_token, service = _prepare_research(
        tmp_path,
        source_count=2,
    )
    provider.quantization = "Q5"

    with pytest.raises(SourceAnalysisModelDriftError):
        service.assert_model_unchanged(scope)

    assert not any(
        schema_id.startswith("athena_research_synthesis_")
        for schema_id, _messages in provider.calls
    )
    app.jobs.yield_job(job.job_id, lease_token=lease_token)
    app.stop()
