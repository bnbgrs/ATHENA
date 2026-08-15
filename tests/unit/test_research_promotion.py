from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

import pytest

from athena.common.time import utc_now_us
from athena.config.settings import AthenaSettings
from athena.core.application import AthenaApplication
from athena.jobs.models import JobState
from athena.knowledge.models import ClaimDraft, ClaimKind, EpistemicStatus
from athena.model.domain import ModelChatMessage, ModelInfo
from athena.research.promotion import (
    ResearchPromotionError,
    ResearchProposalState,
    ResearchProposalType,
)


@dataclass
class _Provider:
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
                context_capacity=4000,
                loaded_context_length=4000,
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
        text = "\n".join(message.content for message in messages)
        if schema_id.startswith("athena_research_synthesis_"):
            refs = sorted(set(re.findall(r"INPUT-\d{3}", text)))
            return {
                "summary": "durable research summary",
                "findings": [
                    {"text": "durable finding", "evidence_refs": refs}
                ],
                "contradictions": [],
                "uncertainty": "bounded",
            }
        if "map" in schema_id:
            return {
                "relevant": True,
                "summary": "map",
                "findings": ["source finding"],
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


def _run_to_terminal(app: AthenaApplication, job_id) -> None:
    now = utc_now_us()
    for index in range(200):
        result = app.job_scheduler.tick(
            worker_id=f"promotion-test-{index}",
            now_us=now,
        )
        job = app.jobs.get(job_id)
        if job.state.terminal:
            assert job.state is JobState.COMPLETED
            return
        if result.idle:
            due = [
                item.next_run_at_us
                for item in app.jobs.waiting(limit=256)
                if item.next_run_at_us is not None
            ]
            now = min(due) + 1 if due else utc_now_us()
        else:
            now = utc_now_us()
    raise AssertionError("Research did not complete.")


def test_research_proposals_require_explicit_acceptance_and_keep_lineage(
    tmp_path: Path,
) -> None:
    app = AthenaApplication(settings=AthenaSettings(local_root=tmp_path / "runtime"))
    app.start()
    provider = _Provider()
    app.source_analysis_service.provider = provider
    app.research_synthesis.provider = provider

    source_path = tmp_path / "source.txt"
    source_path.write_text("evidence for durable research", encoding="utf-8")
    source = app.sources.capture_file(source_path).source
    job = app.research.enqueue_local(
        query="What does the evidence say?",
        explicit_source_ids=(source.source_id,),
        requested_model_id="research-primary",
    )
    _run_to_terminal(app, job.job_id)
    scope = app.research_repository.get_scope_for_job(job.job_id)
    assert scope is not None
    result = app.research_repository.get_result_for_scope(scope.scope_id)
    assert result is not None

    before_commit = app.research_repository.current_commit_seq()
    before_knowledge = len(app.knowledge_repository.list_current())
    before_claims = len(app.claim_repository.list_current())

    proposal_set = app.research_promotion.create_proposals(result.result_id)
    proposals = app.research_promotion.list_proposals(proposal_set.proposal_set_id)
    assert [item.proposal_type for item in proposals] == [
        ResearchProposalType.KNOWLEDGE,
        ResearchProposalType.CLAIM,
    ]
    assert app.research_repository.current_commit_seq() == before_commit
    assert len(app.knowledge_repository.list_current()) == before_knowledge
    assert len(app.claim_repository.list_current()) == before_claims

    knowledge_acceptance = app.research_promotion.accept(proposals[0].proposal_id)
    claim_acceptance = app.research_promotion.accept(proposals[1].proposal_id)
    assert knowledge_acceptance.entity_id != claim_acceptance.entity_id
    assert app.research_promotion.accept(proposals[0].proposal_id) == knowledge_acceptance
    assert app.research_promotion.accept(proposals[1].proposal_id) == claim_acceptance

    assert len(app.knowledge_repository.list_current()) == before_knowledge + 1
    assert len(app.claim_repository.list_current()) == before_claims + 1
    claim_evidence = app.claim_repository.list_evidence(claim_acceptance.entity_id)
    assert claim_evidence
    assert all(item.anchor_id is not None for item in claim_evidence)

    origins = app.database.connection.execute(
        """
        SELECT result_id, source_analysis_artifact_ids_json,
               source_anchor_ids_json, source_ids_json
        FROM research_knowledge_origins
        ORDER BY subject_entity_id
        """
    ).fetchall()
    assert len(origins) == 2
    assert all(bytes(row["result_id"]) == result.result_id.bytes for row in origins)

    stored = app.research_promotion.list_proposals(proposal_set.proposal_set_id)
    assert all(item.state is ResearchProposalState.ACCEPTED for item in stored)
    app.stop()


def test_research_acceptance_rejects_tampered_frozen_payload(tmp_path: Path) -> None:
    app = AthenaApplication(settings=AthenaSettings(local_root=tmp_path / "runtime-tamper"))
    app.start()
    provider = _Provider()
    app.source_analysis_service.provider = provider
    app.research_synthesis.provider = provider
    source_path = tmp_path / "tamper-source.txt"
    source_path.write_text("evidence for tamper test", encoding="utf-8")
    source = app.sources.capture_file(source_path).source
    job = app.research.enqueue_local(
        query="What does the evidence say?",
        explicit_source_ids=(source.source_id,),
        requested_model_id="research-primary",
    )
    _run_to_terminal(app, job.job_id)
    scope = app.research_repository.get_scope_for_job(job.job_id)
    assert scope is not None
    result = app.research_repository.get_result_for_scope(scope.scope_id)
    assert result is not None
    proposal_set = app.research_promotion.create_proposals(result.result_id)
    proposal = app.research_promotion.list_proposals(proposal_set.proposal_set_id)[1]
    with app.database.write_transaction() as connection:
        connection.execute(
            "UPDATE research_promotion_items SET payload_json = ? WHERE proposal_id = ?",
            ('{"claim_kind":"observation","epistemic_status":"supported","statement":"tampered"}', proposal.proposal_id.bytes),
        )
    with pytest.raises(ResearchPromotionError, match="payload changed"):
        app.research_promotion.accept(proposal.proposal_id)
    assert app.claim_repository.list_current() == ()
    app.stop()


def test_second_identical_research_result_reuses_exact_canonical_entities(
    tmp_path: Path,
) -> None:
    app = AthenaApplication(settings=AthenaSettings(local_root=tmp_path / "runtime-reuse"))
    app.start()
    provider = _Provider()
    app.source_analysis_service.provider = provider
    app.research_synthesis.provider = provider
    source_path = tmp_path / "reuse-source.txt"
    source_path.write_text("evidence for exact research reuse", encoding="utf-8")
    source = app.sources.capture_file(source_path).source

    accepted_ids = []
    for _index in range(2):
        job = app.research.enqueue_local(
            query="What does the evidence say?",
            explicit_source_ids=(source.source_id,),
            requested_model_id="research-primary",
        )
        _run_to_terminal(app, job.job_id)
        scope = app.research_repository.get_scope_for_job(job.job_id)
        assert scope is not None
        result = app.research_repository.get_result_for_scope(scope.scope_id)
        assert result is not None
        proposal_set = app.research_promotion.create_proposals(result.result_id)
        proposals = app.research_promotion.list_proposals(proposal_set.proposal_set_id)
        accepted_ids.append(
            tuple(app.research_promotion.accept(item.proposal_id).entity_id for item in proposals)
        )

    assert accepted_ids[0] == accepted_ids[1]
    assert len(app.knowledge_repository.list_current()) == 1
    assert len(app.claim_repository.list_current()) == 1
    origins = app.database.connection.execute(
        "SELECT COUNT(*) FROM research_knowledge_origins"
    ).fetchone()
    assert origins is not None and int(origins[0]) == 4
    app.stop()

def test_research_acceptance_reverifies_anchor_inside_write_boundary(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app = AthenaApplication(settings=AthenaSettings(local_root=tmp_path / "runtime-reverify"))
    app.start()
    provider = _Provider()
    app.source_analysis_service.provider = provider
    app.research_synthesis.provider = provider
    source_path = tmp_path / "reverify-source.txt"
    source_path.write_text("evidence for boundary revalidation", encoding="utf-8")
    source = app.sources.capture_file(source_path).source
    job = app.research.enqueue_local(
        query="What does the evidence say?",
        explicit_source_ids=(source.source_id,),
        requested_model_id="research-primary",
    )
    _run_to_terminal(app, job.job_id)
    scope = app.research_repository.get_scope_for_job(job.job_id)
    assert scope is not None
    result = app.research_repository.get_result_for_scope(scope.scope_id)
    assert result is not None
    proposal_set = app.research_promotion.create_proposals(result.result_id)
    proposal = app.research_promotion.list_proposals(proposal_set.proposal_set_id)[1]

    original_verify = app.source_anchors.verify
    calls = 0

    def boundary_verify(anchor_id):
        nonlocal calls
        calls += 1
        if calls >= 2:
            raise RuntimeError("synthetic anchor change at write boundary")
        return original_verify(anchor_id)

    monkeypatch.setattr(app.source_anchors, "verify", boundary_verify)
    with pytest.raises(RuntimeError, match="write boundary"):
        app.research_promotion.accept(proposal.proposal_id)
    assert calls >= 2
    assert app.claim_repository.list_current() == ()
    stored = app.research_promotion.list_proposals(proposal_set.proposal_set_id)[1]
    assert stored.state is ResearchProposalState.PENDING
    app.stop()


class _ContradictionProvider(_Provider):
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
        text = "\n".join(message.content for message in messages)
        if schema_id.startswith("athena_research_synthesis_"):
            refs = sorted(set(re.findall(r"INPUT-\d{3}", text)))
            return {
                "summary": "the supplied sources disagree on the launch date",
                "findings": [],
                "contradictions": [
                    {
                        "text": "sources report incompatible launch dates",
                        "evidence_refs": refs,
                    }
                ],
                "uncertainty": "the conflict is unresolved",
            }
        if "map" in schema_id:
            return {
                "relevant": True,
                "summary": "map",
                "findings": ["source date evidence"],
                "contradictions": [],
                "uncertainty": "",
            }
        return {
            "summary": "source synthesis",
            "findings": ["source date evidence"],
            "contradictions": [],
            "uncertainty": "",
        }


def test_research_contradiction_stays_review_only_and_cannot_be_accepted(
    tmp_path: Path,
) -> None:
    app = AthenaApplication(settings=AthenaSettings(local_root=tmp_path / "runtime-contradiction"))
    app.start()
    provider = _ContradictionProvider()
    app.source_analysis_service.provider = provider
    app.research_synthesis.provider = provider
    first_path = tmp_path / "date-a.txt"
    second_path = tmp_path / "date-b.txt"
    first_path.write_text("launch date is 15 September 2026", encoding="utf-8")
    second_path.write_text("launch date is 18 September 2026", encoding="utf-8")
    first = app.sources.capture_file(first_path).source
    second = app.sources.capture_file(second_path).source
    job = app.research.enqueue_local(
        query="What is the launch date?",
        explicit_source_ids=(first.source_id, second.source_id),
        requested_model_id="research-primary",
    )
    _run_to_terminal(app, job.job_id)
    scope = app.research_repository.get_scope_for_job(job.job_id)
    assert scope is not None
    result = app.research_repository.get_result_for_scope(scope.scope_id)
    assert result is not None
    proposal_set = app.research_promotion.create_proposals(result.result_id)
    proposals = app.research_promotion.list_proposals(proposal_set.proposal_set_id)
    contradiction = next(
        item for item in proposals if item.proposal_type is ResearchProposalType.CONTRADICTION
    )
    before_claims = len(app.claim_repository.list_current())
    with pytest.raises(ResearchPromotionError, match="review-only"):
        app.research_promotion.accept(contradiction.proposal_id)
    assert len(app.claim_repository.list_current()) == before_claims
    rejected = app.research_promotion.reject(contradiction.proposal_id)
    assert rejected.state is ResearchProposalState.REJECTED
    app.stop()


class _NearDuplicateProvider(_Provider):
    def generate_structured(
        self,
        *,
        model_id: str,
        messages: tuple[ModelChatMessage, ...],
        schema_id: str,
        json_schema,
        max_output_tokens: int | None = None,
    ):
        result = super().generate_structured(
            model_id=model_id,
            messages=messages,
            schema_id=schema_id,
            json_schema=json_schema,
            max_output_tokens=max_output_tokens,
        )
        if schema_id.startswith("athena_research_synthesis_"):
            result["findings"] = [
                {
                    "text": "The project launch date is September 16 2026",
                    "evidence_refs": result["findings"][0]["evidence_refs"],
                }
            ]
        return result


def test_research_near_duplicate_requires_explicit_keep_separate_decision(
    tmp_path: Path,
) -> None:
    app = AthenaApplication(settings=AthenaSettings(local_root=tmp_path / "runtime-near"))
    app.start()
    provider = _Provider()
    app.source_analysis_service.provider = provider
    app.research_synthesis.provider = provider
    source_path = tmp_path / "near-source.txt"
    source_path.write_text("evidence for near duplicate test", encoding="utf-8")
    source = app.sources.capture_file(source_path).source

    first_job = app.research.enqueue_local(
        query="What does the evidence say?",
        explicit_source_ids=(source.source_id,),
        requested_model_id="research-primary",
    )
    _run_to_terminal(app, first_job.job_id)
    first_scope = app.research_repository.get_scope_for_job(first_job.job_id)
    assert first_scope is not None
    first_result = app.research_repository.get_result_for_scope(first_scope.scope_id)
    assert first_result is not None
    first_set = app.research_promotion.create_proposals(first_result.result_id)
    first_claim = next(
        item
        for item in app.research_promotion.list_proposals(first_set.proposal_set_id)
        if item.proposal_type is ResearchProposalType.CLAIM
    )
    # Replace the initially simple synthetic finding with a longer canonical
    # claim so the second finding can be a conservative near-duplicate.
    with app.database.write_transaction() as connection:
        connection.execute(
            """
            UPDATE research_promotion_items
            SET payload_json = ?
            WHERE proposal_id = ?
            """,
            (
                '{"claim_kind":"observation","epistemic_status":"supported",'
                '"statement":"The project launch date is September 15 2026"}',
                first_claim.proposal_id.bytes,
            ),
        )
    # Tampering is intentionally rejected; create the canonical comparator
    # through the normal Claim service instead.
    app.research_promotion.reject(first_claim.proposal_id)
    canonical = app.claim_repository.create_claim(
        actor_id=app.chat.ensure_local_user(),
        draft=ClaimDraft(
            claim_kind=ClaimKind.OBSERVATION,
            statement="The project launch date is September 15 2026",
            epistemic_status=EpistemicStatus.SUPPORTED,
        ),
        reason="explicit test canonical comparator",
    )
    assert canonical.claim_id is not None

    near = _NearDuplicateProvider()
    app.source_analysis_service.provider = near
    app.research_synthesis.provider = near
    second_job = app.research.enqueue_local(
        query="What does the evidence say now?",
        explicit_source_ids=(source.source_id,),
        requested_model_id="research-primary",
    )
    _run_to_terminal(app, second_job.job_id)
    second_scope = app.research_repository.get_scope_for_job(second_job.job_id)
    assert second_scope is not None
    second_result = app.research_repository.get_result_for_scope(second_scope.scope_id)
    assert second_result is not None
    second_set = app.research_promotion.create_proposals(second_result.result_id)
    second_claim = next(
        item
        for item in app.research_promotion.list_proposals(second_set.proposal_set_id)
        if item.proposal_type is ResearchProposalType.CLAIM
    )
    with pytest.raises(ResearchPromotionError, match="near-duplicates"):
        app.research_promotion.accept(second_claim.proposal_id)
    assert app.research_promotion._proposal(second_claim.proposal_id).state is ResearchProposalState.PENDING
    app.stop()
