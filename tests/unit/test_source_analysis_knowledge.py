from __future__ import annotations

import json
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest

from athena.config.settings import AthenaSettings
from athena.core.application import AthenaApplication
from athena.knowledge.extraction_models import CONTRADICTION_AUDIT_SCHEMA_ID
from athena.knowledge.source_acceptance import SourceProposalAcceptanceError
from athena.knowledge.source_extraction import (
    SOURCE_EXTRACTION_SCHEMA_ID,
    SourceExtractionError,
)
from athena.model.domain import (
    ModelChatMessage,
    ModelInfo,
    ProviderHealth,
    ProviderHealthStatus,
)
from athena.source.analysis_models import SourceAnalysisState

_SOURCE_TEXT = (
    "Berlin ist die Hauptstadt von Deutschland. "
    "Die Quelle nennt Berlin ausdrücklich als Hauptstadt Deutschlands."
)
_QUOTE = "Berlin ist die Hauptstadt von Deutschland."


class FakeSourceKnowledgeProvider:
    provider_id = "fake"

    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple[ModelChatMessage, ...], int | None]] = []
        self.extraction_payload: Mapping[str, Any] = self._default_extraction_payload()
        self.audit_payload: Mapping[str, Any] = {
            "assessments": []
        }

    def health(self) -> ProviderHealth:
        return ProviderHealth(ProviderHealthStatus.READY)

    def discover_models(self) -> tuple[ModelInfo, ...]:
        return (
            ModelInfo(
                provider="fake",
                backend_model_id="fake-primary",
                display_name="Fake Primary",
                model_type="llm",
                context_capacity=32768,
                quantization="Q4_K_M",
                loaded=True,
                vision=False,
                trained_for_tool_use=False,
                loaded_context_length=32768,
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
        del json_schema
        assert model_id == "fake-primary"
        self.calls.append((schema_id, tuple(messages), max_output_tokens))
        if schema_id == SOURCE_EXTRACTION_SCHEMA_ID:
            return self.extraction_payload
        if schema_id == CONTRADICTION_AUDIT_SCHEMA_ID:
            return self.audit_payload
        if "_map_" in schema_id:
            return {
                "relevant": True,
                "summary": "Die Quelle nennt Berlin als Hauptstadt Deutschlands.",
                "findings": ["Berlin ist die Hauptstadt von Deutschland."],
                "contradictions": [],
                "uncertainty": "",
            }
        return {
            "summary": "Berlin wird als Hauptstadt Deutschlands genannt.",
            "findings": ["Berlin ist die Hauptstadt von Deutschland."],
            "contradictions": [],
            "uncertainty": "",
        }

    @staticmethod
    def _default_extraction_payload() -> Mapping[str, Any]:
        return {
            "knowledge_units": [
                {
                    "source_sequence_no": 1,
                    "source_quote": _QUOTE,
                    "knowledge_kind": "fact",
                    "title": "Hauptstadt Deutschlands",
                    "body": _QUOTE,
                    "epistemic_status": "asserted",
                    "confidence": 1.0,
                }
            ],
            "claims": [
                {
                    "source_sequence_no": 1,
                    "source_quote": _QUOTE,
                    "claim_kind": "factual_assertion",
                    "statement": _QUOTE,
                    "epistemic_status": "asserted",
                    "confidence": 1.0,
                }
            ],
            "relations": [],
            "merge_candidates": [],
        }


def _app(tmp_path: Path) -> tuple[AthenaApplication, FakeSourceKnowledgeProvider]:
    app = AthenaApplication(settings=AthenaSettings(local_root=tmp_path / "runtime"))
    app.start()
    provider = FakeSourceKnowledgeProvider()
    app.source_analysis_service.provider = provider
    app.chat_generation.provider = provider
    app.source_extraction.provider = provider
    return app, provider


def _source(app: AthenaApplication, tmp_path: Path, *, text: str = _SOURCE_TEXT):
    path = tmp_path / "source.txt"
    path.write_text(text, encoding="utf-8", newline="")
    source = app.sources.capture_file(path).source
    representation = app.source_text.build(source.source_id).result.representation
    chunks = app.source_chunks.build_default(representation.representation_id).chunks
    assert chunks
    return source, representation, chunks


def _completed_analysis(app: AthenaApplication, provider: FakeSourceKnowledgeProvider, tmp_path: Path):
    source, representation, chunks = _source(app, tmp_path)
    assert len(chunks) == 1
    job = app.source_analysis.enqueue(
        source.source_id,
        question="Was sagt die Quelle über die Hauptstadt Deutschlands?",
        requested_model_id="fake-primary",
        context_limit=6000,
        output_reserve=1000,
        safety_margin=300,
        max_hierarchy_depth=8,
    )
    result = app.source_analysis.run_to_completion(job.job_id, worker_id="source-knowledge-test")
    assert result.done is True
    assert result.analysis is not None
    assert result.analysis.state is SourceAnalysisState.COMPLETED
    assert result.analysis.final_artifact_id is not None
    provider.calls.clear()
    return result.analysis, source, representation


def test_completed_analysis_extracts_grounded_proposals_without_canonical_writes(tmp_path: Path) -> None:
    app, provider = _app(tmp_path)
    try:
        analysis, _source_record, _representation = _completed_analysis(app, provider, tmp_path)

        result = app.source_extraction.extract_analysis(
            analysis_id=analysis.analysis_id,
            requested_model_id="fake-primary",
            context_limit=8000,
            output_reserve=2048,
            safety_margin=500,
        )

        assert result.processing_run.status == "succeeded"
        assert len(result.evidence) == 1
        assert result.proposals.knowledge_units[0].source_quote == _QUOTE
        assert result.proposals.claims[0].source_quote == _QUOTE
        assert len(provider.calls) == 1
        schema_id, messages, output_cap = provider.calls[0]
        assert schema_id == SOURCE_EXTRACTION_SCHEMA_ID
        assert output_cap == 2048
        assert "FINAL_ANALYSIS_INTERPRETATION_UNTRUSTED" in messages[1].content
        assert "SOURCE_EVIDENCE_UNTRUSTED" in messages[1].content
        assert str(result.evidence[0].anchor_id) not in messages[1].content
        assert app.database.connection.execute("SELECT COUNT(*) FROM knowledge_units").fetchone()[0] == 0
        assert app.database.connection.execute("SELECT COUNT(*) FROM claims").fetchone()[0] == 0
        snapshot_count = app.database.connection.execute(
            "SELECT COUNT(*) FROM source_extraction_result_snapshots"
        ).fetchone()[0]
        assert snapshot_count == 1
    finally:
        app.stop()


def test_source_extraction_rejects_invented_sequence_and_marks_run_failed(tmp_path: Path) -> None:
    app, provider = _app(tmp_path)
    try:
        analysis, _source_record, _representation = _completed_analysis(app, provider, tmp_path)
        provider.extraction_payload = {
            "knowledge_units": [],
            "claims": [
                {
                    "source_sequence_no": 99,
                    "source_quote": _QUOTE,
                    "claim_kind": "factual_assertion",
                    "statement": _QUOTE,
                    "epistemic_status": "asserted",
                    "confidence": 1.0,
                }
            ],
            "relations": [],
            "merge_candidates": [],
        }

        with pytest.raises(ValueError, match="does not exist"):
            app.source_extraction.extract_analysis(
                analysis_id=analysis.analysis_id,
                requested_model_id="fake-primary",
                context_limit=8000,
                output_reserve=2048,
                safety_margin=500,
            )

        row = app.database.connection.execute(
            "SELECT status, error_detail FROM processing_runs "
            "WHERE run_type = 'source_knowledge_extraction' ORDER BY started_at_us DESC LIMIT 1"
        ).fetchone()
        assert row is not None and row["status"] == "failed"
        assert row["error_detail"] == "ExtractionValidationError"
        assert app.database.connection.execute("SELECT COUNT(*) FROM knowledge_units").fetchone()[0] == 0
        assert app.database.connection.execute("SELECT COUNT(*) FROM claims").fetchone()[0] == 0
    finally:
        app.stop()


def test_source_extraction_rejects_non_verbatim_quote(tmp_path: Path) -> None:
    app, provider = _app(tmp_path)
    try:
        analysis, _source_record, _representation = _completed_analysis(app, provider, tmp_path)
        provider.extraction_payload = {
            "knowledge_units": [],
            "claims": [
                {
                    "source_sequence_no": 1,
                    "source_quote": "Berlin ist Europas größte Hauptstadt.",
                    "claim_kind": "factual_assertion",
                    "statement": "Berlin ist Europas größte Hauptstadt.",
                    "epistemic_status": "asserted",
                    "confidence": 0.5,
                }
            ],
            "relations": [],
            "merge_candidates": [],
        }

        with pytest.raises(ValueError, match="exact contiguous quote"):
            app.source_extraction.extract_analysis(
                analysis_id=analysis.analysis_id,
                requested_model_id="fake-primary",
                context_limit=8000,
                output_reserve=2048,
                safety_margin=500,
            )
    finally:
        app.stop()


def test_incomplete_analysis_is_rejected_before_provider_call(tmp_path: Path) -> None:
    app, provider = _app(tmp_path)
    try:
        source, _representation, _chunks = _source(app, tmp_path)
        job = app.source_analysis.enqueue(
            source.source_id,
            question="Was sagt die Quelle?",
            requested_model_id="fake-primary",
            context_limit=6000,
            output_reserve=1000,
            safety_margin=300,
        )
        leased = app.jobs.acquire(job.job_id, worker_id="partial", lease_seconds=120)
        assert leased.lease_token is not None
        initialized = app.source_analysis.step(job.job_id, lease_token=leased.lease_token)
        assert initialized.analysis is not None
        provider.calls.clear()

        with pytest.raises(SourceExtractionError, match="Only a completed source analysis"):
            app.source_extraction.extract_analysis(
                analysis_id=initialized.analysis.analysis_id,
                requested_model_id="fake-primary",
            )
        assert provider.calls == []
    finally:
        app.stop()


def test_source_extraction_snapshot_round_trips_without_model_call(tmp_path: Path) -> None:
    app, provider = _app(tmp_path)
    try:
        analysis, _source_record, _representation = _completed_analysis(app, provider, tmp_path)
        result = app.source_extraction.extract_analysis(
            analysis_id=analysis.analysis_id,
            requested_model_id="fake-primary",
            context_limit=8000,
            output_reserve=2048,
            safety_margin=500,
        )
        provider.calls.clear()

        loaded = app.source_extraction_snapshots.load(result.processing_run.processing_run_id)

        assert provider.calls == []
        assert loaded.analysis_id == result.analysis_id
        assert loaded.final_artifact_id == result.final_artifact_id
        assert loaded.model_signature == result.model_signature
        assert loaded.processing_run == result.processing_run
        assert loaded.proposals == result.proposals
        assert loaded.evidence == result.evidence
    finally:
        app.stop()


def test_acceptance_creates_canonical_entities_with_anchor_and_analysis_provenance(tmp_path: Path) -> None:
    app, provider = _app(tmp_path)
    try:
        analysis, _source_record, _representation = _completed_analysis(app, provider, tmp_path)
        extracted = app.source_extraction.extract_analysis(
            analysis_id=analysis.analysis_id,
            requested_model_id="fake-primary",
            context_limit=8000,
            output_reserve=2048,
            safety_margin=500,
        )
        plan = app.source_proposal_acceptance.preflight(extracted)

        accepted = app.source_proposal_acceptance.accept_all(extracted, expected_plan=plan)

        assert len(accepted.knowledge_created_ids) == 1
        assert len(accepted.claim_created_ids) == 1
        assert accepted.knowledge_reused_ids == ()
        assert accepted.claim_reused_ids == ()
        assert app.database.connection.execute("SELECT COUNT(*) FROM knowledge_units").fetchone()[0] == 1
        assert app.database.connection.execute("SELECT COUNT(*) FROM claims").fetchone()[0] == 1
        origins = app.database.connection.execute(
            "SELECT analysis_id, final_artifact_id, extraction_run_id "
            "FROM source_analysis_knowledge_origins"
        ).fetchall()
        assert len(origins) == 2
        assert {bytes(row["analysis_id"]) for row in origins} == {analysis.analysis_id.bytes}
        assert {bytes(row["final_artifact_id"]) for row in origins} == {
            analysis.final_artifact_id.bytes
        }
        assert {bytes(row["extraction_run_id"]) for row in origins} == {
            extracted.processing_run.processing_run_id.bytes
        }
        knowledge = app.knowledge_repository.load_current(accepted.knowledge_ids[0])
        inputs = app.knowledge_repository.list_provenance_inputs(knowledge.revision.provenance_id)
        assert len(inputs) == 1
        assert inputs[0].input_entity_id == extracted.evidence[0].anchor_id
        claim_evidence = app.claim_repository.list_evidence(accepted.claim_ids[0])
        assert len(claim_evidence) == 1
        assert claim_evidence[0].anchor_id == extracted.evidence[0].anchor_id
    finally:
        app.stop()


def test_second_source_acceptance_reuses_exact_canonical_duplicates(tmp_path: Path) -> None:
    app, provider = _app(tmp_path)
    try:
        analysis, _source_record, _representation = _completed_analysis(app, provider, tmp_path)
        extracted = app.source_extraction.extract_analysis(
            analysis_id=analysis.analysis_id,
            requested_model_id="fake-primary",
            context_limit=8000,
            output_reserve=2048,
            safety_margin=500,
        )
        first = app.source_proposal_acceptance.accept_all(extracted)
        plan = app.source_proposal_acceptance.preflight(extracted)
        assert all(item.action.value == "reuse_canonical" for item in plan.knowledge)
        assert all(item.action.value == "reuse_canonical" for item in plan.claims)

        second = app.source_proposal_acceptance.accept_all(extracted, expected_plan=plan)

        assert second.knowledge_ids == first.knowledge_ids
        assert second.claim_ids == first.claim_ids
        assert second.knowledge_created_ids == ()
        assert second.claim_created_ids == ()
        assert len(second.knowledge_reused_ids) == 1
        assert len(second.claim_reused_ids) == 1
        assert app.database.connection.execute("SELECT COUNT(*) FROM knowledge_units").fetchone()[0] == 1
        assert app.database.connection.execute("SELECT COUNT(*) FROM claims").fetchone()[0] == 1
    finally:
        app.stop()


def test_acceptance_revalidates_complete_final_anchor_set(tmp_path: Path) -> None:
    app, provider = _app(tmp_path)
    try:
        # Force two source anchors so a tampered frozen result can omit one of them.
        long_text = (_SOURCE_TEXT + " ") * 40
        source, _representation, chunks = _source(app, tmp_path, text=long_text)
        assert len(chunks) > 1
        job = app.source_analysis.enqueue(
            source.source_id,
            question="Was sagt die Quelle?",
            requested_model_id="fake-primary",
            context_limit=6000,
            output_reserve=1000,
            safety_margin=300,
        )
        analysis_result = app.source_analysis.run_to_completion(job.job_id, worker_id="multi-anchor")
        assert analysis_result.analysis is not None
        provider.calls.clear()
        # Use empty proposals to isolate frozen-evidence revalidation.
        provider.extraction_payload = {
            "knowledge_units": [],
            "claims": [],
            "relations": [],
            "merge_candidates": [],
        }
        extracted = app.source_extraction.extract_analysis(
            analysis_id=analysis_result.analysis.analysis_id,
            requested_model_id="fake-primary",
            context_limit=20000,
            output_reserve=2048,
            safety_margin=500,
        )
        assert len(extracted.evidence) > 1
        offsets = [
            app.source_anchors.get(item.anchor_id).start_offset for item in extracted.evidence
        ]
        assert all(offset is not None for offset in offsets)
        assert offsets == sorted(offsets)
        shortened = extracted.evidence[:-1]
        run_snapshot = json.loads(extracted.processing_run.input_snapshot_json)
        run_snapshot["evidence"] = [
            {
                "sequence_no": item.sequence_no,
                "anchor_id": str(item.anchor_id),
                "quoted_hash": item.quoted_hash.hex(),
            }
            for item in shortened
        ]
        frozen_evidence = {
            "items": [
                {
                    "sequence_no": item.sequence_no,
                    "anchor_id": str(item.anchor_id),
                    "quoted_hash": item.quoted_hash.hex(),
                }
                for item in shortened
            ]
        }
        with app.database.write_transaction() as connection:
            connection.execute(
                "UPDATE processing_runs SET input_snapshot_json = ? WHERE processing_run_id = ?",
                (
                    json.dumps(run_snapshot, sort_keys=True, separators=(",", ":")),
                    extracted.processing_run.processing_run_id.bytes,
                ),
            )
            connection.execute(
                "UPDATE source_extraction_result_snapshots SET evidence_json = ? "
                "WHERE processing_run_id = ?",
                (
                    json.dumps(frozen_evidence, sort_keys=True, separators=(",", ":")),
                    extracted.processing_run.processing_run_id.bytes,
                ),
            )
        tampered = app.source_extraction_snapshots.load(
            extracted.processing_run.processing_run_id
        )

        with pytest.raises(SourceProposalAcceptanceError, match="complete Final provenance"):
            app.source_proposal_acceptance.preflight(tampered)
    finally:
        app.stop()


def test_bounded_extraction_context_fails_before_model_call(tmp_path: Path) -> None:
    app, provider = _app(tmp_path)
    try:
        analysis, _source_record, _representation = _completed_analysis(app, provider, tmp_path)
        provider.calls.clear()

        with pytest.raises(SourceExtractionError, match="does not fit the bounded extraction context"):
            app.source_extraction.extract_analysis(
                analysis_id=analysis.analysis_id,
                requested_model_id="fake-primary",
                context_limit=900,
                output_reserve=512,
                safety_margin=128,
            )
        assert provider.calls == []
        extraction_runs = app.database.connection.execute(
            "SELECT COUNT(*) FROM processing_runs WHERE run_type = 'source_knowledge_extraction'"
        ).fetchone()[0]
        assert extraction_runs == 0
    finally:
        app.stop()


def test_source_claim_contradiction_is_audited_and_queued_for_review(tmp_path: Path) -> None:
    app, provider = _app(tmp_path)
    try:
        analysis, _source_record, _representation = _completed_analysis(app, provider, tmp_path)
        provider.extraction_payload = {
            "knowledge_units": [],
            "claims": [
                {
                    "source_sequence_no": 1,
                    "source_quote": _QUOTE,
                    "claim_kind": "factual_assertion",
                    "statement": "Berlin ist die Hauptstadt von Deutschland.",
                    "epistemic_status": "asserted",
                    "confidence": 1.0,
                },
                {
                    "source_sequence_no": 1,
                    "source_quote": _QUOTE,
                    "claim_kind": "factual_assertion",
                    "statement": "Berlin ist nicht die Hauptstadt von Deutschland.",
                    "epistemic_status": "asserted",
                    "confidence": 0.5,
                },
            ],
            "relations": [],
            "merge_candidates": [],
        }
        provider.audit_payload = {
            "assessments": [
                {
                    "left_claim_index": 0,
                    "right_claim_index": 1,
                    "relationship": "contradicts",
                    "confidence": 0.99,
                    "reason": "Die Aussagen widersprechen sich direkt.",
                }
            ]
        }

        extracted = app.source_extraction.extract_analysis(
            analysis_id=analysis.analysis_id,
            requested_model_id="fake-primary",
            context_limit=8000,
            output_reserve=2048,
            safety_margin=500,
        )
        assert [call[0] for call in provider.calls] == [
            SOURCE_EXTRACTION_SCHEMA_ID,
            CONTRADICTION_AUDIT_SCHEMA_ID,
        ]
        assert extracted.proposals.relations[0].relation_type == "contradicts"
        rows = app.database.connection.execute(
            "SELECT run_type, status, input_snapshot_json FROM processing_runs "
            "WHERE run_type IN ('source_knowledge_extraction', "
            "'source_knowledge_extraction_claim_audit')"
        ).fetchall()
        by_type = {str(row["run_type"]): row for row in rows}
        assert {
            "source_knowledge_extraction",
            "source_knowledge_extraction_claim_audit",
        } <= set(by_type)
        for run_type in (
            "source_knowledge_extraction",
            "source_knowledge_extraction_claim_audit",
        ):
            row = by_type[run_type]
            assert row["status"] == "succeeded"
            snapshot = json.loads(str(row["input_snapshot_json"]))
            package = snapshot["context_package"]
            assert package["snapshot_commit_seq"] >= 0
            assert package["structured_output"]["schema_id"] in {
                SOURCE_EXTRACTION_SCHEMA_ID, CONTRADICTION_AUDIT_SCHEMA_ID
            }

        accepted = app.source_proposal_acceptance.accept_all(extracted)
        assert len(accepted.contradiction_review_ids) == 1
        row = app.database.connection.execute(
            "SELECT review_type, status FROM semantic_review_items WHERE review_id = ?",
            (accepted.contradiction_review_ids[0].bytes,),
        ).fetchone()
        assert row is not None
        assert row["review_type"] == "contradiction"
        assert row["status"] == "pending"
    finally:
        app.stop()


def test_near_duplicate_blocks_until_user_explicitly_keeps_source_proposal_separate(
    tmp_path: Path,
) -> None:
    app, provider = _app(tmp_path)
    try:
        first_text = "Berlin ist die Hauptstadt von Deutschland und Sitz der Bundesregierung."
        second_text = (
            "Berlin ist die Hauptstadt von Deutschland und außerdem Sitz der Bundesregierung."
        )
        source, _representation, chunks = _source(
            app,
            tmp_path,
            text=f"{first_text} {second_text}",
        )
        assert len(chunks) == 1
        job = app.source_analysis.enqueue(
            source.source_id,
            question="Was sagt die Quelle über Berlin?",
            requested_model_id="fake-primary",
            context_limit=6000,
            output_reserve=1000,
            safety_margin=300,
        )
        analyzed = app.source_analysis.run_to_completion(job.job_id, worker_id="near-dup")
        assert analyzed.analysis is not None
        provider.calls.clear()
        provider.extraction_payload = {
            "knowledge_units": [
                {
                    "source_sequence_no": 1,
                    "source_quote": first_text,
                    "knowledge_kind": "fact",
                    "title": "Berlin",
                    "body": first_text,
                    "epistemic_status": "asserted",
                    "confidence": 1.0,
                }
            ],
            "claims": [],
            "relations": [],
            "merge_candidates": [],
        }
        first = app.source_extraction.extract_analysis(
            analysis_id=analyzed.analysis.analysis_id,
            requested_model_id="fake-primary",
            context_limit=8000,
            output_reserve=2048,
            safety_margin=500,
        )
        app.source_proposal_acceptance.accept_all(first)

        provider.extraction_payload = {
            "knowledge_units": [
                {
                    "source_sequence_no": 1,
                    "source_quote": second_text,
                    "knowledge_kind": "fact",
                    "title": "Berlin",
                    "body": second_text,
                    "epistemic_status": "asserted",
                    "confidence": 1.0,
                }
            ],
            "claims": [],
            "relations": [],
            "merge_candidates": [],
        }
        second = app.source_extraction.extract_analysis(
            analysis_id=analyzed.analysis.analysis_id,
            requested_model_id="fake-primary",
            context_limit=8000,
            output_reserve=2048,
            safety_margin=500,
        )
        plan = app.source_proposal_acceptance.preflight(second)
        assert plan.has_unresolved_merge_candidates is True
        assert len(plan.merge_candidates) == 1
        assert plan.merge_candidates[0].similarity >= 0.93

        with pytest.raises(SourceProposalAcceptanceError, match="explicit keep-separate"):
            app.source_proposal_acceptance.accept_all(second, expected_plan=plan)

        accepted = app.source_proposal_acceptance.accept_all(
            second,
            expected_plan=plan,
            keep_separate_near_duplicates=True,
        )
        assert len(accepted.knowledge_created_ids) == 1
        assert app.database.connection.execute("SELECT COUNT(*) FROM knowledge_units").fetchone()[0] == 2
    finally:
        app.stop()


def test_acceptance_rejects_proposal_set_changed_after_frozen_snapshot(tmp_path: Path) -> None:
    app, provider = _app(tmp_path)
    try:
        analysis, _source_record, _representation = _completed_analysis(app, provider, tmp_path)
        extracted = app.source_extraction.extract_analysis(
            analysis_id=analysis.analysis_id,
            requested_model_id="fake-primary",
            context_limit=8000,
            output_reserve=2048,
            safety_margin=500,
        )
        changed_claim = replace(
            extracted.proposals.claims[0],
            statement="Manipulierte Aussage nach der Modellvalidierung.",
        )
        changed_proposals = replace(extracted.proposals, claims=(changed_claim,))
        tampered = replace(extracted, proposals=changed_proposals)

        with pytest.raises(SourceProposalAcceptanceError, match="frozen validated snapshot"):
            app.source_proposal_acceptance.preflight(tampered)
    finally:
        app.stop()


def test_source_extractor_cannot_bypass_dedicated_relation_audit(tmp_path: Path) -> None:
    app, provider = _app(tmp_path)
    try:
        analysis, _source_record, _representation = _completed_analysis(app, provider, tmp_path)
        provider.extraction_payload = {
            "knowledge_units": [
                {
                    "source_sequence_no": 1,
                    "source_quote": _QUOTE,
                    "knowledge_kind": "fact",
                    "title": "Hauptstadt",
                    "body": _QUOTE,
                    "epistemic_status": "asserted",
                    "confidence": 1.0,
                }
            ],
            "claims": [
                {
                    "source_sequence_no": 1,
                    "source_quote": _QUOTE,
                    "claim_kind": "factual_assertion",
                    "statement": _QUOTE,
                    "epistemic_status": "asserted",
                    "confidence": 1.0,
                }
            ],
            "relations": [
                {
                    "left_type": "knowledge",
                    "left_index": 0,
                    "relation_type": "contains_claim",
                    "right_type": "claim",
                    "right_index": 0,
                    "confidence": 1.0,
                }
            ],
            "merge_candidates": [],
        }

        with pytest.raises(SourceExtractionError, match="leave relations empty"):
            app.source_extraction.extract_analysis(
                analysis_id=analysis.analysis_id,
                requested_model_id="fake-primary",
                context_limit=8000,
                output_reserve=2048,
                safety_margin=500,
            )
        row = app.database.connection.execute(
            "SELECT status FROM processing_runs "
            "WHERE run_type = 'source_knowledge_extraction' ORDER BY started_at_us DESC LIMIT 1"
        ).fetchone()
        assert row is not None and row["status"] == "failed"
    finally:
        app.stop()



def test_source_acceptance_rolls_back_atomically_on_mid_commit_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from athena.knowledge.claim_repository import ClaimRepository

    app, provider = _app(tmp_path)
    try:
        analysis, _source_record, _representation = _completed_analysis(app, provider, tmp_path)
        extracted = app.source_extraction.extract_analysis(
            analysis_id=analysis.analysis_id,
            requested_model_id="fake-primary",
            context_limit=8000,
            output_reserve=2048,
            safety_margin=500,
        )

        def fail_claim_payload(*args: object, **kwargs: object) -> None:
            del args, kwargs
            raise RuntimeError("synthetic source acceptance failure")

        monkeypatch.setattr(
            ClaimRepository,
            "_insert_payload",
            staticmethod(fail_claim_payload),
        )
        with pytest.raises(RuntimeError, match="synthetic source acceptance failure"):
            app.source_proposal_acceptance.accept_all(extracted)

        connection = app.database.connection
        assert connection.execute("SELECT COUNT(*) FROM knowledge_units").fetchone()[0] == 0
        assert connection.execute("SELECT COUNT(*) FROM claims").fetchone()[0] == 0
        assert connection.execute(
            "SELECT COUNT(*) FROM source_analysis_knowledge_origins"
        ).fetchone()[0] == 0
        assert connection.execute(
            "SELECT COUNT(*) FROM commit_records WHERE operation_type = 'source_analysis.proposal_set.accept'"
        ).fetchone()[0] == 0
    finally:
        app.stop()
