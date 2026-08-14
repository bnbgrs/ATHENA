from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path

import pytest

from athena.config.settings import AthenaSettings
from athena.core.application import AthenaApplication
from athena.jobs.models import JobState
from athena.model.domain import ModelChatMessage, ModelInfo
from athena.research.models import (
    ResearchScopeState,
    ResearchSynthesisInputKind,
    ResearchSynthesisStage,
    ResearchSynthesisWorkState,
)
from athena.research.repository import ResearchFenceError, ResearchStateError

SYNTHESIS_PIPELINE = "exhaustive-research-synthesis-v1"
SYNTHESIS_PROMPT_ID = "athena.research_synthesis"
SYNTHESIS_PROMPT_VERSION = "1"


@dataclass
class _ResearchProvider:
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
                context_capacity=2_000,
                loaded_context_length=2_000,
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
            "summary": "source synthesis summary",
            "findings": ["supported finding"],
            "contradictions": [],
            "uncertainty": "",
        }

    def stream_chat(self, *, model_id: str, messages):
        del model_id, messages
        yield "unused"


def _app(root: Path) -> AthenaApplication:
    app = AthenaApplication(settings=AthenaSettings(local_root=root))
    app.start()
    app.source_analysis_service.provider = _ResearchProvider()
    return app


def _capture(app: AthenaApplication, path: Path, text: str):
    path.write_text(text, encoding="utf-8", newline="")
    return app.sources.capture_file(path).source


def _acquire_parent(app: AthenaApplication, job_id):
    current = app.jobs.get(job_id)
    if current.state is JobState.WAITING:
        app.jobs.wake(job_id)
    leased = app.jobs.acquire(
        job_id,
        worker_id="research-synthesis-parent",
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
                    worker_id="research-synthesis-source-child",
                )
                assert result.done is True
        refreshed = app.research_repository.get_work_item(work.work_item_id)
        if refreshed.source_analysis_job_id is not None:
            child = app.jobs.get(refreshed.source_analysis_job_id)
            if child.state is JobState.QUEUED:
                result = app.source_analysis.run_to_completion(
                    child.job_id,
                    worker_id="research-synthesis-analysis-child",
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


def _start_synthesis_run(
    app: AthenaApplication,
    *,
    scope,
    work_item_id,
):
    assert scope.model_signature_id is not None
    return app.model_runs.start_run(
        run_type="research_synthesis_final",
        trigger_actor_id=app.chat.ensure_local_user(),
        pipeline_version=SYNTHESIS_PIPELINE,
        input_snapshot={
            "scope_id": str(scope.scope_id),
            "work_item_id": str(work_item_id),
        },
        configuration={
            "prompt_template_id": SYNTHESIS_PROMPT_ID,
            "prompt_template_version": SYNTHESIS_PROMPT_VERSION,
        },
        model_signature_id=scope.model_signature_id,
        prompt_template_id=SYNTHESIS_PROMPT_ID,
        prompt_template_version=SYNTHESIS_PROMPT_VERSION,
    )


def _plan_single_final(app: AthenaApplication, job_id):
    scope = app.research.initialize(job_id)
    source_artifacts = (
        app.research_repository.successful_source_analysis_final_artifact_ids(
            scope.scope_id
        )
    )
    assert source_artifacts
    lease_token = _acquire_parent(app, job_id)
    work = app.research_repository.create_synthesis_work_item_fenced(
        scope.scope_id,
        parent_job_id=job_id,
        lease_token=lease_token,
        stage=ResearchSynthesisStage.FINAL,
        level=0,
        ordinal=0,
        inputs=tuple(
            (
                ResearchSynthesisInputKind.SOURCE_ANALYSIS_ARTIFACT,
                artifact_id,
            )
            for artifact_id in source_artifacts
        ),
        descriptor={
            "kind": "final",
            "source_artifacts": [str(item) for item in source_artifacts],
        },
        pipeline_version=SYNTHESIS_PIPELINE,
        prompt_template_id=SYNTHESIS_PROMPT_ID,
        prompt_template_version=SYNTHESIS_PROMPT_VERSION,
    )
    return scope, source_artifacts, lease_token, work


def test_synthesis_work_is_idempotent_and_rejects_irrelevant_source_artifact(
    tmp_path: Path,
) -> None:
    app = _app(tmp_path / "runtime")
    _capture(app, tmp_path / "relevant.txt", "relevant durable evidence")
    _capture(
        app,
        tmp_path / "irrelevant.txt",
        "NO_RELEVANT_EVIDENCE but analyze this source",
    )
    job = app.research.enqueue_local(query="Find all relevant evidence.")
    _drive_to_synthesis_wait(app, job.job_id)

    scope, source_artifacts, lease_token, work = _plan_single_final(
        app,
        job.job_id,
    )
    repeated = app.research_repository.create_synthesis_work_item_fenced(
        scope.scope_id,
        parent_job_id=job.job_id,
        lease_token=lease_token,
        stage=ResearchSynthesisStage.FINAL,
        level=0,
        ordinal=0,
        inputs=tuple(
            (
                ResearchSynthesisInputKind.SOURCE_ANALYSIS_ARTIFACT,
                artifact_id,
            )
            for artifact_id in source_artifacts
        ),
        descriptor={
            "kind": "final",
            "source_artifacts": [str(item) for item in source_artifacts],
        },
        pipeline_version=SYNTHESIS_PIPELINE,
        prompt_template_id=SYNTHESIS_PROMPT_ID,
        prompt_template_version=SYNTHESIS_PROMPT_VERSION,
    )
    assert repeated.work_item_id == work.work_item_id
    assert len(app.research_repository.list_synthesis_work_items(scope.scope_id)) == 1

    irrelevant = next(
        item
        for item in app.research_repository.list_work_items(scope.scope_id)
        if item.state.value == "irrelevant"
    )
    assert irrelevant.source_analysis_job_id is not None
    analysis = app.source_analysis_repository.get_analysis_for_job(
        irrelevant.source_analysis_job_id
    )
    assert analysis is not None and analysis.final_artifact_id is not None
    with pytest.raises(
        ResearchStateError,
        match="not the completed FINAL artifact of SUCCESSFUL",
    ):
        app.research_repository.create_synthesis_work_item_fenced(
            scope.scope_id,
            parent_job_id=job.job_id,
            lease_token=lease_token,
            stage=ResearchSynthesisStage.REDUCE,
            level=0,
            ordinal=1,
            inputs=(
                (
                    ResearchSynthesisInputKind.SOURCE_ANALYSIS_ARTIFACT,
                    analysis.final_artifact_id,
                ),
            ),
            descriptor={"kind": "invalid-irrelevant-input"},
            pipeline_version=SYNTHESIS_PIPELINE,
            prompt_template_id=SYNTHESIS_PROMPT_ID,
            prompt_template_version=SYNTHESIS_PROMPT_VERSION,
        )

    app.jobs.yield_job(job.job_id, lease_token=lease_token)
    app.stop()


def test_artifact_evidence_result_and_scope_completion_are_durable(
    tmp_path: Path,
) -> None:
    app = _app(tmp_path / "runtime")
    _capture(app, tmp_path / "source.txt", "durable supported evidence")
    job = app.research.enqueue_local(query="Synthesize durable evidence.")
    _drive_to_synthesis_wait(app, job.job_id)
    scope, source_artifacts, lease_token, work = _plan_single_final(
        app,
        job.job_id,
    )

    run = _start_synthesis_run(
        app,
        scope=scope,
        work_item_id=work.work_item_id,
    )
    app.research_repository.begin_synthesis_attempt_fenced(
        work.work_item_id,
        parent_job_id=job.job_id,
        lease_token=lease_token,
    )
    content = {
        "summary": "research summary",
        "findings": ["research finding"],
        "contradictions": ["research contradiction"],
        "uncertainty": "bounded uncertainty",
    }
    with pytest.raises(
        ResearchStateError,
        match="requires at least one explicit durable input backlink",
    ):
        app.research_repository.commit_synthesis_artifact_fenced(
            work_item_id=work.work_item_id,
            parent_job_id=job.job_id,
            lease_token=lease_token,
            content=content,
            processing_run_id=run.processing_run_id,
            evidence=(),
        )

    artifact = app.research_repository.commit_synthesis_artifact_fenced(
        work_item_id=work.work_item_id,
        parent_job_id=job.job_id,
        lease_token=lease_token,
        content=content,
        processing_run_id=run.processing_run_id,
        evidence=(
            ("finding", 0, 0),
            ("contradiction", 0, 0),
        ),
    )
    assert (
        app.research_repository.get_synthesis_work_item(work.work_item_id).state
        is ResearchSynthesisWorkState.COMPLETED
    )
    assert app.model_runs.load_run(run.processing_run_id).status == "succeeded"
    assert set(
        app.research_repository.source_analysis_artifact_ids_for_synthesis_artifact(
            artifact.artifact_id
        )
    ) == set(source_artifacts)
    assert set(
        app.research_repository.source_analysis_artifact_ids_for_synthesis_output(
            artifact.artifact_id,
            output_kind="finding",
            output_ordinal=0,
        )
    ) == set(source_artifacts)
    anchors = app.source_analysis_repository.source_anchor_ids_for_artifact(
        source_artifacts[0]
    )
    assert anchors

    knowledge_before = int(
        app.database.connection.execute(
            "SELECT COUNT(*) FROM knowledge_units"
        ).fetchone()[0]
    )
    claims_before = int(
        app.database.connection.execute(
            "SELECT COUNT(*) FROM claims"
        ).fetchone()[0]
    )
    result = app.research_repository.finalize_result_fenced(
        scope.scope_id,
        parent_job_id=job.job_id,
        lease_token=lease_token,
        semantic_content=content,
        final_artifact_id=artifact.artifact_id,
        synthesis_pipeline_version=SYNTHESIS_PIPELINE,
    )
    payload = json.loads(result.content_json)
    assert result.final_artifact_id == artifact.artifact_id
    assert result.successful_count == 1
    assert result.coverage_ratio == 1.0
    assert payload["coverage"]["successful_count"] == 1
    assert payload["coverage"]["coverage_ratio"] == 1.0
    assert payload["problem_sources"] == []
    assert payload["snapshot_commit_seq"] == scope.snapshot_commit_seq
    assert (
        app.research_repository.get_scope(scope.scope_id).state
        is ResearchScopeState.COMPLETED
    )
    assert app.research_repository.get_result_for_scope(scope.scope_id) == result
    assert int(
        app.database.connection.execute(
            "SELECT COUNT(*) FROM knowledge_units"
        ).fetchone()[0]
    ) == knowledge_before
    assert int(
        app.database.connection.execute(
            "SELECT COUNT(*) FROM claims"
        ).fetchone()[0]
    ) == claims_before

    completed = app.jobs.complete(
        job.job_id,
        lease_token=lease_token,
    )
    assert completed.state is JobState.COMPLETED
    app.stop()


def test_cancel_requested_parent_cannot_commit_semantic_artifact(
    tmp_path: Path,
) -> None:
    app = _app(tmp_path / "runtime")
    _capture(app, tmp_path / "source.txt", "cancel boundary evidence")
    job = app.research.enqueue_local(query="Cancel before synthesis commit.")
    _drive_to_synthesis_wait(app, job.job_id)
    scope, _source_artifacts, lease_token, work = _plan_single_final(
        app,
        job.job_id,
    )
    run = _start_synthesis_run(
        app,
        scope=scope,
        work_item_id=work.work_item_id,
    )
    app.research_repository.begin_synthesis_attempt_fenced(
        work.work_item_id,
        parent_job_id=job.job_id,
        lease_token=lease_token,
    )
    cancelled = app.jobs.request_cancel(job.job_id)
    assert cancelled.state is JobState.CANCEL_REQUESTED

    with pytest.raises(
        ResearchFenceError,
        match="cancel_requested is not commit-capable",
    ):
        app.research_repository.commit_synthesis_artifact_fenced(
            work_item_id=work.work_item_id,
            parent_job_id=job.job_id,
            lease_token=lease_token,
            content={
                "summary": "must not persist",
                "findings": ["must not persist"],
                "contradictions": [],
                "uncertainty": "",
            },
            processing_run_id=run.processing_run_id,
            evidence=(("finding", 0, 0),),
        )
    assert (
        app.research_repository.synthesis_artifact_for_work_item(
            work.work_item_id
        )
        is None
    )
    assert app.model_runs.load_run(run.processing_run_id).status == "running"
    app.model_runs.finish_run(
        run.processing_run_id,
        status="cancelled",
        error_detail="parent cancel requested before semantic commit",
    )
    app.research_repository.mark_scope_state_fenced(
        scope.scope_id,
        parent_job_id=job.job_id,
        lease_token=lease_token,
        state=ResearchScopeState.PARTIAL,
    )
    final_job = app.jobs.acknowledge_cancel(
        job.job_id,
        lease_token=lease_token,
    )
    assert final_job.state is JobState.CANCELLED
    assert (
        app.research_repository.get_scope(scope.scope_id).state
        is ResearchScopeState.PARTIAL
    )
    assert app.research_repository.get_result_for_scope(scope.scope_id) is None
    app.stop()

def _split_children(source_artifacts):
    assert len(source_artifacts) >= 4
    kind = ResearchSynthesisInputKind.SOURCE_ANALYSIS_ARTIFACT
    return (
        (
            1,
            0,
            (
                (kind, source_artifacts[0]),
                (kind, source_artifacts[1]),
            ),
            {"group": 0},
        ),
        (
            1,
            1,
            (
                (kind, source_artifacts[2]),
                (kind, source_artifacts[3]),
            ),
            {"group": 1},
        ),
    )


def test_synthesis_split_is_atomic_convergent_and_idempotent(
    tmp_path: Path,
) -> None:
    app = _app(tmp_path / "runtime")
    for index in range(4):
        _capture(
            app,
            tmp_path / f"source-{index}.txt",
            f"distinct relevant evidence {index}",
        )
    job = app.research.enqueue_local(query="Merge all durable evidence.")
    _drive_to_synthesis_wait(app, job.job_id)
    scope, source_artifacts, lease_token, parent = _plan_single_final(
        app,
        job.job_id,
    )
    assert len(source_artifacts) == 4
    children_spec = _split_children(source_artifacts)

    children = app.research_repository.split_synthesis_work_item_fenced(
        parent.work_item_id,
        parent_job_id=job.job_id,
        lease_token=lease_token,
        children=children_spec,
    )
    assert len(children) == 2
    assert all(
        child.stage is ResearchSynthesisStage.REDUCE
        and child.state is ResearchSynthesisWorkState.PENDING
        and child.level == 1
        for child in children
    )
    assert (
        app.research_repository.get_synthesis_work_item(parent.work_item_id).state
        is ResearchSynthesisWorkState.SPLIT
    )
    assert len(
        app.research_repository.list_synthesis_work_items(scope.scope_id)
    ) == 3

    repeated = app.research_repository.split_synthesis_work_item_fenced(
        parent.work_item_id,
        parent_job_id=job.job_id,
        lease_token=lease_token,
        children=children_spec,
    )
    assert tuple(item.work_item_id for item in repeated) == tuple(
        item.work_item_id for item in children
    )
    assert len(
        app.research_repository.list_synthesis_work_items(scope.scope_id)
    ) == 3

    with pytest.raises(
        ResearchStateError,
        match="outside its parent",
    ):
        app.research_repository.split_synthesis_work_item_fenced(
            parent.work_item_id,
            parent_job_id=job.job_id,
            lease_token=lease_token,
            children=(
                (
                    1,
                    0,
                    (
                        (
                            ResearchSynthesisInputKind.SOURCE_ANALYSIS_ARTIFACT,
                            source_artifacts[0],
                        ),
                        (
                            ResearchSynthesisInputKind.SOURCE_ANALYSIS_ARTIFACT,
                            source_artifacts[1],
                        ),
                    ),
                    {"group": 0},
                ),
                (
                    1,
                    1,
                    (
                        (
                            ResearchSynthesisInputKind.SOURCE_ANALYSIS_ARTIFACT,
                            source_artifacts[2],
                        ),
                        (
                            ResearchSynthesisInputKind.RESEARCH_SYNTHESIS_ARTIFACT,
                            source_artifacts[3],
                        ),
                    ),
                    {"group": "invalid-kind"},
                ),
            ),
        )

    app.jobs.yield_job(job.job_id, lease_token=lease_token)
    app.stop()


def test_synthesis_split_rolls_back_children_if_parent_supersede_aborts(
    tmp_path: Path,
) -> None:
    app = _app(tmp_path / "runtime")
    for index in range(4):
        _capture(
            app,
            tmp_path / f"crash-source-{index}.txt",
            f"crash-safe relevant evidence {index}",
        )
    job = app.research.enqueue_local(query="Crash-safe synthesis split.")
    _drive_to_synthesis_wait(app, job.job_id)
    scope, source_artifacts, lease_token, parent = _plan_single_final(
        app,
        job.job_id,
    )
    children_spec = _split_children(source_artifacts)

    with app.database.write_transaction() as connection:
        connection.execute(
            """
            CREATE TRIGGER abort_research_synthesis_split
            BEFORE UPDATE OF state ON research_synthesis_work_items
            WHEN NEW.state = 'split'
            BEGIN
                SELECT RAISE(ABORT, 'simulated split crash');
            END
            """
        )

    with pytest.raises(sqlite3.IntegrityError, match="simulated split crash"):
        app.research_repository.split_synthesis_work_item_fenced(
            parent.work_item_id,
            parent_job_id=job.job_id,
            lease_token=lease_token,
            children=children_spec,
        )

    assert (
        app.research_repository.get_synthesis_work_item(parent.work_item_id).state
        is ResearchSynthesisWorkState.PENDING
    )
    assert len(
        app.research_repository.list_synthesis_work_items(scope.scope_id)
    ) == 1

    with app.database.write_transaction() as connection:
        connection.execute("DROP TRIGGER abort_research_synthesis_split")

    children = app.research_repository.split_synthesis_work_item_fenced(
        parent.work_item_id,
        parent_job_id=job.job_id,
        lease_token=lease_token,
        children=children_spec,
    )
    assert len(children) == 2
    assert (
        app.research_repository.get_synthesis_work_item(parent.work_item_id).state
        is ResearchSynthesisWorkState.SPLIT
    )
    assert len(
        app.research_repository.list_synthesis_work_items(scope.scope_id)
    ) == 3

    app.jobs.yield_job(job.job_id, lease_token=lease_token)
    app.stop()
