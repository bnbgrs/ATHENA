from __future__ import annotations

import json
import re
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest

from athena.common.time import utc_now_us
from athena.config.settings import AthenaSettings
from athena.core.application import AthenaApplication
from athena.jobs.models import JobState
from athena.knowledge.source_extraction import SOURCE_EXTRACTION_SCHEMA_ID
from athena.knowledge.source_hierarchical_models import (
    SourceExtractionStage,
    SourceHierarchicalExtractionState,
)
from athena.knowledge.source_hierarchical_service import MERGE_SCHEMA_ID, PAIR_AUDIT_SCHEMA_ID
from athena.model.domain import ModelChatMessage, ModelInfo, ProviderHealth, ProviderHealthStatus
from athena.source.analysis_models import SourceAnalysisState


@dataclass
class FakeHierarchicalExtractionProvider:
    context_capacity: int = 6000
    quantization: str = "Q4"
    generation_timeout_seconds: float = 300.0
    deduplicate_claims: bool = False
    invalid_grounding: bool = False
    calls: list[tuple[str, tuple[ModelChatMessage, ...], int | None]] = field(default_factory=list)
    controlled_calls: list[dict[str, Any]] = field(default_factory=list)

    @property
    def provider_id(self) -> str:
        return "fake"

    @property
    def controlled_structured_transport_id(self) -> str:
        return "fake_controlled_structured_v1"

    def health(self) -> ProviderHealth:
        return ProviderHealth(ProviderHealthStatus.READY)

    def discover_models(self) -> tuple[ModelInfo, ...]:
        return (
            ModelInfo(
                provider="fake",
                backend_model_id="fake-primary",
                display_name="Fake Primary",
                model_type="llm",
                context_capacity=self.context_capacity,
                quantization=self.quantization,
                loaded=True,
                vision=False,
                trained_for_tool_use=False,
            ),
        )

    def stream_chat(
        self,
        *,
        model_id: str,
        messages: Sequence[ModelChatMessage],
    ) -> Iterator[str]:
        del model_id, messages
        yield "unused"

    def generate_structured(
        self,
        *,
        model_id: str,
        messages: Sequence[ModelChatMessage],
        schema_id: str,
        json_schema: Mapping[str, Any],
        max_output_tokens: int | None = None,
    ) -> Mapping[str, Any]:
        assert model_id == "fake-primary"
        captured = tuple(messages)
        self.calls.append((schema_id, captured, max_output_tokens))
        if schema_id == SOURCE_EXTRACTION_SCHEMA_ID:
            user = captured[-1].content
            matches = re.findall(
                r"\[(\d+)\]\n(.*?)\n\[/EVIDENCE_\1\]",
                user,
                flags=re.DOTALL,
            )
            assert matches
            sequence_text, evidence_text = matches[0]
            quote = evidence_text.strip()[:96]
            assert quote
            if self.invalid_grounding:
                quote = "THIS QUOTE DOES NOT OCCUR IN THE SELECTED SOURCE EVIDENCE"
            return {
                "knowledge_units": [],
                "claims": [
                    {
                        "source_sequence_no": int(sequence_text),
                        "source_quote": quote,
                        "claim_kind": "factual_assertion",
                        "statement": quote,
                        "epistemic_status": "asserted",
                        "confidence": 1.0,
                    }
                ],
                "relations": [],
                "merge_candidates": [],
            }
        if schema_id == MERGE_SCHEMA_ID:
            claim_indexes = sorted(
                {int(item) for item in re.findall(r"\[C(\d+)\]", captured[-1].content)}
            )
            claim_duplicates = []
            if self.deduplicate_claims and len(claim_indexes) > 1:
                claim_duplicates = [
                    {
                        "keep_index": claim_indexes[0],
                        "member_indexes": claim_indexes,
                    }
                ]
            return {"knowledge_duplicates": [], "claim_duplicates": claim_duplicates}
        if schema_id == PAIR_AUDIT_SCHEMA_ID:
            assessments_schema = json_schema["properties"]["assessments"]
            pair_count = int(assessments_schema["minItems"])
            return {
                "assessments": [
                    {
                        "pair_no": pair_no,
                        "relationship": "compatible_or_unknown",
                        "confidence": 1.0,
                        "reason": "No contradiction is established by the supplied pair.",
                    }
                    for pair_no in range(1, pair_count + 1)
                ]
            }
        if "_map_" in schema_id:
            return {
                "relevant": True,
                "summary": "Relevant source evidence.",
                "findings": ["Relevant finding."],
                "contradictions": [],
                "uncertainty": "",
            }
        return {
            "summary": "Synthesis of all relevant source evidence.",
            "findings": ["Relevant finding."],
            "contradictions": [],
            "uncertainty": "",
        }

    def generate_controlled_structured(
        self,
        *,
        model_id: str,
        messages: Sequence[ModelChatMessage],
        schema_id: str,
        json_schema: Mapping[str, Any],
        reasoning_mode: str,
        context_length: int,
        max_output_tokens: int,
        temperature: float,
        top_p: float,
        top_k: int,
        min_p: float,
        repeat_penalty: float,
    ) -> Mapping[str, Any]:
        self.controlled_calls.append(
            {
                "reasoning_mode": reasoning_mode,
                "context_length": context_length,
                "max_output_tokens": max_output_tokens,
                "temperature": temperature,
                "top_p": top_p,
                "top_k": top_k,
                "min_p": min_p,
                "repeat_penalty": repeat_penalty,
            }
        )
        return self.generate_structured(
            model_id=model_id,
            messages=messages,
            schema_id=schema_id,
            json_schema=json_schema,
            max_output_tokens=max_output_tokens,
        )


def _app(root: Path) -> tuple[AthenaApplication, FakeHierarchicalExtractionProvider]:
    app = AthenaApplication(settings=AthenaSettings(local_root=root))
    app.start()
    provider = FakeHierarchicalExtractionProvider()
    app.chat_generation.provider = provider
    app.source_analysis_service.provider = provider
    app.source_extraction.provider = provider
    app.source_hierarchical_extraction_service.provider = provider
    return app, provider


def _large_text(*, sections: int = 8, payload_words: int = 130) -> str:
    return "\n\n".join(
        f"FACT_{index:03d}: value {index}. " + (f"payload{index:03d} " * payload_words)
        for index in range(sections)
    )


def _completed_analysis(
    app: AthenaApplication,
    tmp_path: Path,
):
    path = tmp_path / "hierarchical-extraction-source.txt"
    path.write_text(_large_text(), encoding="utf-8", newline="")
    source = app.sources.capture_file(path).source
    representation = app.source_text.build(source.source_id).result.representation
    chunks = app.source_chunks.build_default(representation.representation_id).chunks
    assert len(chunks) >= 4
    analysis_job = app.source_analysis.enqueue(
        source.source_id,
        question="Extract the substantive FACT values.",
        requested_model_id="fake-primary",
        context_limit=3500,
        output_reserve=400,
        safety_margin=100,
        max_hierarchy_depth=12,
    )
    result = app.source_analysis.run_to_completion(
        analysis_job.job_id,
        worker_id="hierarchical-extraction-analysis",
    )
    assert result.done is True
    assert result.analysis is not None
    assert result.analysis.state is SourceAnalysisState.COMPLETED
    return result.analysis, chunks


def _enqueue_extraction(app: AthenaApplication, analysis_id):
    return app.source_hierarchical_extraction.enqueue(
        analysis_id,
        requested_model_id="fake-primary",
        context_limit=3000,
        output_reserve=500,
        safety_margin=100,
        max_hierarchy_depth=12,
    )


def test_hierarchical_extraction_batches_merges_audits_and_freezes_without_canonical_writes(
    tmp_path: Path,
) -> None:
    app, provider = _app(tmp_path / "runtime")
    try:
        analysis, chunks = _completed_analysis(app, tmp_path)
        provider.calls.clear()
        job = _enqueue_extraction(app, analysis.analysis_id)

        result = app.source_hierarchical_extraction.run_to_completion(
            job.job_id,
            worker_id="hierarchical-extraction",
        )

        assert result.done is True
        assert result.waiting is False
        assert result.extraction is not None
        extraction = app.source_hierarchical_extraction_repository.get_extraction(
            result.extraction.extraction_id
        )
        assert extraction.state is SourceHierarchicalExtractionState.COMPLETED
        assert extraction.total_batches >= 2
        assert extraction.completed_batches == extraction.total_batches
        evidence = app.source_hierarchical_extraction_repository.evidence(extraction.extraction_id)
        assert len(evidence) == len(chunks)

        batch_artifacts = app.source_hierarchical_extraction_repository.list_artifacts(
            extraction.extraction_id, artifact_kind=SourceExtractionStage.BATCH
        )
        merge_artifacts = app.source_hierarchical_extraction_repository.list_artifacts(
            extraction.extraction_id, artifact_kind=SourceExtractionStage.MERGE
        )
        audit_artifacts = app.source_hierarchical_extraction_repository.list_artifacts(
            extraction.extraction_id, artifact_kind=SourceExtractionStage.AUDIT
        )
        final_artifacts = app.source_hierarchical_extraction_repository.list_artifacts(
            extraction.extraction_id, artifact_kind=SourceExtractionStage.FINAL
        )
        assert len(batch_artifacts) == extraction.total_batches
        assert merge_artifacts
        assert audit_artifacts
        assert len(final_artifacts) == 1

        extraction_calls = [item for item in provider.calls if item[0] == SOURCE_EXTRACTION_SCHEMA_ID]
        merge_calls = [item for item in provider.calls if item[0] == MERGE_SCHEMA_ID]
        audit_calls = [item for item in provider.calls if item[0] == PAIR_AUDIT_SCHEMA_ID]
        assert len(extraction_calls) == extraction.total_batches
        assert merge_calls
        assert audit_calls
        assert all(output_cap == 500 for _schema, _messages, output_cap in provider.calls)
        assert provider.controlled_calls
        assert all(
            call == {
                "reasoning_mode": "off",
                "context_length": 3000,
                "max_output_tokens": 500,
                "temperature": 0.0,
                "top_p": 0.95,
                "top_k": 40,
                "min_p": 0.05,
                "repeat_penalty": 1.1,
            }
            for call in provider.controlled_calls
        )
        pinned = json.loads(job.pinned_configuration_json or "{}")
        assert pinned["provider_transport"] == "fake_controlled_structured_v1"
        assert pinned["reasoning_mode"] == "off"
        assert pinned["structured_contract_version"] == "athena.controlled_structured_json/1"
        assert pinned["provider_instance_policy"] == "initial_context_then_runtime_instance_reuse_v1"
        assert pinned["structured_validation"] == "athena_stage_parser_v1"
        assert all(
            messages[-1].content.rstrip().endswith("/no_think")
            for schema_id, messages, _output_cap in provider.calls
            if schema_id in {SOURCE_EXTRACTION_SCHEMA_ID, MERGE_SCHEMA_ID, PAIR_AUDIT_SCHEMA_ID}
        )
        semantic_runs = app.database.connection.execute(
            "SELECT input_snapshot_json FROM processing_runs "
            "WHERE run_type IN ('source_knowledge_extraction_batch', "
            "'source_knowledge_extraction_merge', 'source_knowledge_extraction_audit')"
        ).fetchall()
        assert semantic_runs
        assert all(
            int(json.loads(str(row["input_snapshot_json"]))["estimated_input_tokens"])
            <= extraction.input_budget
            for row in semantic_runs
        )

        canonical_knowledge = app.database.connection.execute(
            "SELECT COUNT(*) FROM knowledge_units"
        ).fetchone()[0]
        canonical_claims = app.database.connection.execute(
            "SELECT COUNT(*) FROM claims"
        ).fetchone()[0]
        assert canonical_knowledge == 0
        assert canonical_claims == 0
        snapshot_count = app.database.connection.execute(
            "SELECT COUNT(*) FROM source_extraction_result_snapshots"
        ).fetchone()[0]
        assert snapshot_count == 1

        calls_before_acceptance = len(provider.calls)
        frozen = app.source_extraction_snapshots.load(final_artifacts[0].processing_run_id)
        plan = app.source_proposal_acceptance.preflight(frozen)
        accepted = app.source_proposal_acceptance.accept_all(frozen, expected_plan=plan)
        assert accepted.claim_ids
        assert len(provider.calls) == calls_before_acceptance

        signature_ids = {
            row["model_signature_id"]
            for row in app.database.connection.execute(
                "SELECT model_signature_id FROM processing_runs "
                "WHERE run_type LIKE 'source_knowledge_extraction%' "
                "AND model_signature_id IS NOT NULL"
            ).fetchall()
        }
        assert len(signature_ids) == 1
    finally:
        app.stop()


def test_final_artifact_crash_resumes_snapshot_without_new_model_call(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app, provider = _app(tmp_path / "runtime")
    try:
        analysis, _chunks = _completed_analysis(app, tmp_path)
        provider.calls.clear()
        job = _enqueue_extraction(app, analysis.analysis_id)
        leased = app.jobs.acquire(job.job_id, worker_id="final-crash", lease_seconds=120)
        assert leased.lease_token is not None

        original_save = app.source_extraction_snapshots.save
        crashed = False

        def crash_after_final_artifact(result):
            nonlocal crashed
            crashed = True
            raise RuntimeError("simulated crash after Final artifact")

        for _ in range(500):
            extraction = app.source_hierarchical_extraction_repository.get_extraction_for_job(job.job_id)
            if extraction is not None:
                final_items = app.source_hierarchical_extraction_repository.list_work_items(
                    extraction.extraction_id, stage=SourceExtractionStage.FINAL
                )
                if final_items:
                    pending = app.source_hierarchical_extraction_repository.next_pending(
                        extraction.extraction_id
                    )
                    if pending is not None and pending.stage is SourceExtractionStage.FINAL:
                        monkeypatch.setattr(app.source_extraction_snapshots, "save", crash_after_final_artifact)
                        with pytest.raises(RuntimeError, match="simulated crash after Final artifact"):
                            app.source_hierarchical_extraction.step(
                                job.job_id,
                                lease_token=leased.lease_token,
                            )
                        break
            step = app.source_hierarchical_extraction.step(
                job.job_id,
                lease_token=leased.lease_token,
            )
            assert step.waiting is False
        else:
            raise AssertionError("Final extraction work was never reached")

        assert crashed is True
        extraction = app.source_hierarchical_extraction_repository.get_extraction_for_job(job.job_id)
        assert extraction is not None
        assert extraction.state is not SourceHierarchicalExtractionState.COMPLETED
        final_items = app.source_hierarchical_extraction_repository.list_work_items(
            extraction.extraction_id, stage=SourceExtractionStage.FINAL
        )
        assert len(final_items) == 1
        persisted_final = app.source_hierarchical_extraction_repository.artifact_for_work_item(
            final_items[0].work_item_id
        )
        assert persisted_final is not None
        calls_before_resume = len(provider.calls)

        monkeypatch.setattr(app.source_extraction_snapshots, "save", original_save)
        resumed = app.source_hierarchical_extraction.step(
            job.job_id,
            lease_token=leased.lease_token,
        )
        assert resumed.completed_stage == "final"
        assert resumed.waiting is False
        assert len(provider.calls) == calls_before_resume
        extraction = app.source_hierarchical_extraction_repository.get_extraction(
            extraction.extraction_id
        )
        assert extraction.state is SourceHierarchicalExtractionState.COMPLETED
        assert app.database.connection.execute(
            "SELECT COUNT(*) FROM source_extraction_result_snapshots"
        ).fetchone()[0] == 1

        finished = app.source_hierarchical_extraction.step(
            job.job_id,
            lease_token=leased.lease_token,
        )
        assert finished.done is True
        assert finished.job.state is JobState.COMPLETED
        assert len(provider.calls) == calls_before_resume
    finally:
        app.stop()


def test_model_drift_waits_for_user_without_replaying_completed_batch(tmp_path: Path) -> None:
    app, provider = _app(tmp_path / "runtime")
    try:
        analysis, _chunks = _completed_analysis(app, tmp_path)
        provider.calls.clear()
        job = _enqueue_extraction(app, analysis.analysis_id)
        leased = app.jobs.acquire(job.job_id, worker_id="model-drift", lease_seconds=120)
        assert leased.lease_token is not None

        initialized = app.source_hierarchical_extraction.step(
            job.job_id, lease_token=leased.lease_token
        )
        assert initialized.completed_stage == "initialize"
        planned = app.source_hierarchical_extraction.step(
            job.job_id, lease_token=leased.lease_token
        )
        assert planned.completed_stage == "batch_plan"
        first_batch = app.source_hierarchical_extraction.step(
            job.job_id, lease_token=leased.lease_token
        )
        assert first_batch.completed_stage == "batch"
        assert first_batch.extraction is not None
        completed_before_drift = first_batch.extraction.completed_batches
        assert completed_before_drift == 1
        calls_before_drift = len(provider.calls)

        provider.quantization = "Q5"
        waiting = app.source_hierarchical_extraction.step(
            job.job_id, lease_token=leased.lease_token
        )
        assert waiting.waiting is True
        assert waiting.job.state is JobState.WAITING
        assert waiting.job.blocked_reason == "waiting_user"
        extraction = app.source_hierarchical_extraction_repository.get_extraction(
            first_batch.extraction.extraction_id
        )
        assert extraction.completed_batches == completed_before_drift
        assert len(provider.calls) == calls_before_drift
    finally:
        app.stop()


def test_reasoning_mode_tamper_waits_for_user_without_replaying_completed_batch(
    tmp_path: Path,
) -> None:
    app, provider = _app(tmp_path / "runtime")
    try:
        analysis, _chunks = _completed_analysis(app, tmp_path)
        provider.calls.clear()
        provider.controlled_calls.clear()
        job = _enqueue_extraction(app, analysis.analysis_id)
        leased = app.jobs.acquire(job.job_id, worker_id="reasoning-drift", lease_seconds=120)
        assert leased.lease_token is not None

        assert app.source_hierarchical_extraction.step(
            job.job_id, lease_token=leased.lease_token
        ).completed_stage == "initialize"
        assert app.source_hierarchical_extraction.step(
            job.job_id, lease_token=leased.lease_token
        ).completed_stage == "batch_plan"
        first_batch = app.source_hierarchical_extraction.step(
            job.job_id, lease_token=leased.lease_token
        )
        assert first_batch.completed_stage == "batch"
        calls_before = len(provider.calls)

        pinned = json.loads(job.pinned_configuration_json or "{}")
        pinned["reasoning_mode"] = "on"
        app.database.connection.execute(
            "UPDATE jobs SET pinned_configuration_json = ? WHERE job_id = ?",
            (json.dumps(pinned, sort_keys=True, separators=(",", ":")), job.job_id.bytes),
        )
        app.database.connection.commit()

        waiting = app.source_hierarchical_extraction.step(
            job.job_id, lease_token=leased.lease_token
        )
        assert waiting.waiting is True
        assert waiting.job.state is JobState.WAITING
        assert waiting.job.blocked_reason == "waiting_user"
        assert len(provider.calls) == calls_before
    finally:
        app.stop()


def test_invalid_grounding_output_waits_for_user_without_committing_batch(
    tmp_path: Path,
) -> None:
    app, provider = _app(tmp_path / "runtime")
    try:
        analysis, _chunks = _completed_analysis(app, tmp_path)
        provider.calls.clear()
        provider.controlled_calls.clear()
        provider.invalid_grounding = True
        job = _enqueue_extraction(app, analysis.analysis_id)
        leased = app.jobs.acquire(job.job_id, worker_id="grounding-failure", lease_seconds=120)
        assert leased.lease_token is not None

        assert app.source_hierarchical_extraction.step(
            job.job_id, lease_token=leased.lease_token
        ).completed_stage == "initialize"
        assert app.source_hierarchical_extraction.step(
            job.job_id, lease_token=leased.lease_token
        ).completed_stage == "batch_plan"

        waiting = app.source_hierarchical_extraction.step(
            job.job_id, lease_token=leased.lease_token
        )
        assert waiting.waiting is True
        assert waiting.job.state is JobState.WAITING
        assert waiting.job.blocked_reason == "waiting_user"
        assert waiting.extraction is not None
        assert app.source_hierarchical_extraction_repository.list_artifacts(
            waiting.extraction.extraction_id,
            artifact_kind=SourceExtractionStage.BATCH,
        ) == ()
    finally:
        app.stop()


def test_scheduler_dispatches_source_extract_to_completion(tmp_path: Path) -> None:
    app, provider = _app(tmp_path / "runtime")
    try:
        analysis, _chunks = _completed_analysis(app, tmp_path)
        provider.calls.clear()
        job = _enqueue_extraction(app, analysis.analysis_id)

        drained = app.job_scheduler.drain(worker_id="hierarchical-extraction-scheduler", max_jobs=20)

        assert drained.completed_jobs == 1
        assert app.jobs.get(job.job_id).state is JobState.COMPLETED
        extraction = app.source_hierarchical_extraction_repository.get_extraction_for_job(job.job_id)
        assert extraction is not None
        assert extraction.state is SourceHierarchicalExtractionState.COMPLETED
    finally:
        app.stop()


def test_cross_batch_semantic_dedup_keeps_original_grounded_proposal_text(tmp_path: Path) -> None:
    app, provider = _app(tmp_path / "runtime")
    try:
        analysis, _chunks = _completed_analysis(app, tmp_path)
        provider.calls.clear()
        provider.deduplicate_claims = True
        job = _enqueue_extraction(app, analysis.analysis_id)

        result = app.source_hierarchical_extraction.run_to_completion(
            job.job_id, worker_id="semantic-dedup"
        )

        assert result.done is True
        assert result.extraction is not None
        extraction = app.source_hierarchical_extraction_repository.get_extraction(
            result.extraction.extraction_id
        )
        batch_artifacts = app.source_hierarchical_extraction_repository.list_artifacts(
            extraction.extraction_id, artifact_kind=SourceExtractionStage.BATCH
        )
        assert len(batch_artifacts) >= 2
        first_batch = app.source_hierarchical_extraction_service.proposals_from_artifact(
            batch_artifacts[0]
        )
        assert len(first_batch.claims) == 1
        final_artifact = app.source_hierarchical_extraction_repository.get_artifact(
            extraction.final_work_artifact_id
        )
        frozen = app.source_extraction_snapshots.load(final_artifact.processing_run_id)
        assert len(frozen.proposals.claims) == 1
        assert frozen.proposals.claims[0] == first_batch.claims[0]
    finally:
        app.stop()


def test_restart_does_not_replay_completed_extraction_batch(tmp_path: Path) -> None:
    root = tmp_path / "runtime"
    app, provider = _app(root)
    analysis, _chunks = _completed_analysis(app, tmp_path)
    provider.calls.clear()
    job = _enqueue_extraction(app, analysis.analysis_id)
    leased = app.jobs.acquire(job.job_id, worker_id="before-restart", lease_seconds=120)
    assert leased.lease_token is not None
    initialized = app.source_hierarchical_extraction.step(
        job.job_id, lease_token=leased.lease_token
    )
    assert initialized.completed_stage == "initialize"
    planned = app.source_hierarchical_extraction.step(
        job.job_id, lease_token=leased.lease_token
    )
    assert planned.completed_stage == "batch_plan"
    first = app.source_hierarchical_extraction.step(
        job.job_id, lease_token=leased.lease_token
    )
    assert first.completed_stage == "batch"
    assert first.extraction is not None
    extraction_id = first.extraction.extraction_id
    total_batches = first.extraction.total_batches
    assert total_batches >= 2
    first_artifact = app.source_hierarchical_extraction_repository.list_artifacts(
        extraction_id, artifact_kind=SourceExtractionStage.BATCH
    )[0]
    current_job = app.jobs.get(job.job_id)
    assert current_job.lease_expires_at_us is not None
    recovery_time_us = current_job.lease_expires_at_us + 1
    app.stop()

    resumed_app, resumed_provider = _app(root)
    try:
        resumed_app.jobs.recover_startup(now_us=recovery_time_us)
        resumed_provider.calls.clear()
        resumed = resumed_app.source_hierarchical_extraction.run_to_completion(
            job.job_id, worker_id="after-restart"
        )
        assert resumed.done is True
        extraction = resumed_app.source_hierarchical_extraction_repository.get_extraction(
            extraction_id
        )
        assert extraction.state is SourceHierarchicalExtractionState.COMPLETED
        persisted_first = resumed_app.source_hierarchical_extraction_repository.get_artifact(
            first_artifact.artifact_id
        )
        assert persisted_first.content_hash == first_artifact.content_hash
        extraction_calls = [
            item for item in resumed_provider.calls if item[0] == SOURCE_EXTRACTION_SCHEMA_ID
        ]
        assert len(extraction_calls) == total_batches - 1
    finally:
        resumed_app.stop()

def test_hierarchical_extraction_extends_lease_before_provider_call(
    tmp_path: Path,
    monkeypatch,
) -> None:
    app, provider = _app(tmp_path / "provider-lease-runtime")
    try:
        analysis, _chunks = _completed_analysis(
            app,
            tmp_path,
        )
        provider.calls.clear()
        provider.controlled_calls.clear()
        provider.generation_timeout_seconds = 5.0

        job = _enqueue_extraction(
            app,
            analysis.analysis_id,
        )
        original = provider.generate_controlled_structured
        checked_calls = 0

        def guarded_call(*args, **kwargs):
            nonlocal checked_calls
            checked_calls += 1

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
            return original(*args, **kwargs)

        monkeypatch.setattr(
            provider,
            "generate_controlled_structured",
            guarded_call,
        )

        result = app.source_hierarchical_extraction.run_to_completion(
            job.job_id,
            worker_id="hierarchical-provider-lease",
            lease_seconds=1,
        )

        assert result.done is True
        assert result.job.state is JobState.COMPLETED
        assert checked_calls >= 1
    finally:
        app.stop()
