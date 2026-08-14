from __future__ import annotations

from collections.abc import Iterator, Mapping, Sequence
from dataclasses import replace
from typing import Any

import pytest

from athena.chat.generation import ChatGenerationService
from athena.chat.repository import ChatRepository
from athena.chat.service import ChatService
from athena.knowledge.acceptance_service import ProposalAcceptanceService
from athena.knowledge.claim_repository import ClaimRepository
from athena.knowledge.extraction_models import (
    CONTRADICTION_AUDIT_SCHEMA_ID,
    EXTRACTION_SCHEMA_ID,
)
from athena.knowledge.extraction_service import ChatKnowledgeExtractionService
from athena.knowledge.repository import KnowledgeRepository
from athena.knowledge.review_service import ReviewService
from athena.model.domain import ModelChatMessage, ModelInfo, ProviderHealth, ProviderHealthStatus
from athena.model.provenance import ModelRunRepository
from athena.storage.database import SQLiteDatabase


class FakeProvider:
    provider_id = "fake"

    def health(self) -> ProviderHealth:
        return ProviderHealth(ProviderHealthStatus.READY)

    def discover_models(self) -> tuple[ModelInfo, ...]:
        return (
            ModelInfo(
                provider="fake",
                backend_model_id="fake/model",
                display_name="Fake Model",
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
        del model_id, messages, json_schema, max_output_tokens
        if schema_id == EXTRACTION_SCHEMA_ID:
            return {
                "knowledge_units": [
                    {
                        "source_sequence_no": 1,
                        "source_quote": "Berlin ist die Hauptstadt von Deutschland.",
                        "knowledge_kind": "fact",
                        "title": "Hauptstadt Berlin",
                        "body": "Berlin ist die Hauptstadt von Deutschland.",
                        "epistemic_status": "asserted",
                        "confidence": 1.0,
                    },
                    {
                        "source_sequence_no": 2,
                        "source_quote": "München ist die Hauptstadt von Deutschland.",
                        "knowledge_kind": "fact",
                        "title": "Hauptstadt München",
                        "body": "München ist die Hauptstadt von Deutschland.",
                        "epistemic_status": "asserted",
                        "confidence": 1.0,
                    },
                ],
                "claims": [
                    {
                        "source_sequence_no": 1,
                        "source_quote": "Berlin ist die Hauptstadt von Deutschland.",
                        "claim_kind": "factual_assertion",
                        "statement": "Berlin ist die Hauptstadt von Deutschland.",
                        "epistemic_status": "asserted",
                        "confidence": 1.0,
                    },
                    {
                        "source_sequence_no": 2,
                        "source_quote": "München ist die Hauptstadt von Deutschland.",
                        "claim_kind": "factual_assertion",
                        "statement": "München ist die Hauptstadt von Deutschland.",
                        "epistemic_status": "asserted",
                        "confidence": 1.0,
                    },
                ],
                "relations": [],
                "merge_candidates": [],
            }
        if schema_id == CONTRADICTION_AUDIT_SCHEMA_ID:
            return {
                "assessments": [
                    {
                        "left_claim_index": 0,
                        "right_claim_index": 1,
                        "relationship": "contradicts",
                        "confidence": 1.0,
                        "reason": "Both cannot be the capital under the same scope.",
                    }
                ]
            }
        raise AssertionError(schema_id)


def _services(tmp_path):
    database = SQLiteDatabase(tmp_path / "athena.db")
    database.start()
    chat = ChatService(ChatRepository(database))
    provider = FakeProvider()
    extraction = ChatKnowledgeExtractionService(
        chat=chat,
        chat_generation=ChatGenerationService(chat, provider),
        provider=provider,
        runs=ModelRunRepository(database),
    )
    knowledge = KnowledgeRepository(database)
    claims = ClaimRepository(database)
    acceptance = ProposalAcceptanceService(
        database=database,
        chat=chat,
        knowledge=knowledge,
        claims=claims,
        reviews=ReviewService(database),
    )
    return database, chat, extraction, knowledge, claims, acceptance


def _extracted(tmp_path):
    database, chat, extraction, knowledge, claims, acceptance = _services(tmp_path)
    chat_id = chat.create_chat()
    chat.add_user_message(
        chat_id=chat_id,
        content="Berlin ist die Hauptstadt von Deutschland.",
    )
    chat.add_user_message(
        chat_id=chat_id,
        content="München ist die Hauptstadt von Deutschland.",
    )
    result = extraction.extract_chat(chat_id=chat_id)
    return database, result, knowledge, claims, acceptance


def test_accept_all_atomically_creates_grounded_canonical_entities(tmp_path) -> None:
    database, result, knowledge, claims, acceptance = _extracted(tmp_path)
    try:
        accepted = acceptance.accept_all(result)

        assert len(accepted.knowledge_ids) == 2
        assert len(accepted.claim_ids) == 2
        assert accepted.contradiction_pairs == ()
        assert len(accepted.contradiction_review_ids) == 1

        first_knowledge = knowledge.load_current(accepted.knowledge_ids[0])
        assert first_knowledge.revision.payload.body == "Berlin ist die Hauptstadt von Deutschland."
        inputs = knowledge.list_provenance_inputs(first_knowledge.revision.provenance_id)
        assert len(inputs) == 1
        first_claim = claims.load_current(accepted.claim_ids[0])
        evidence = claims.list_evidence(first_claim.claim_id)
        assert {item.evidence_role.value for item in evidence} == {"originates"}

        provenance = database.connection.execute(
            "SELECT model_signature_id, processing_run_id FROM provenance_records "
            "WHERE provenance_id = ?",
            (first_knowledge.revision.provenance_id.bytes,),
        ).fetchone()
        assert provenance is not None
        assert bytes(provenance["model_signature_id"]) == result.model_signature.model_signature_id.bytes
        assert bytes(provenance["processing_run_id"]) == result.processing_run.processing_run_id.bytes
    finally:
        database.stop()


def test_accept_all_rolls_back_the_whole_set_on_mid_commit_failure(tmp_path, monkeypatch) -> None:
    database, result, _knowledge, _claims, acceptance = _extracted(tmp_path)
    original = ClaimRepository._insert_payload

    def fail_claim_payload(*args, **kwargs):
        del args, kwargs
        raise RuntimeError("synthetic acceptance failure")

    monkeypatch.setattr(ClaimRepository, "_insert_payload", staticmethod(fail_claim_payload))
    try:
        with pytest.raises(RuntimeError, match="synthetic acceptance failure"):
            acceptance.accept_all(result)
        knowledge_count = database.connection.execute("SELECT COUNT(*) FROM knowledge_units").fetchone()[0]
        claim_count = database.connection.execute("SELECT COUNT(*) FROM claims").fetchone()[0]
        assert knowledge_count == 0
        assert claim_count == 0
    finally:
        monkeypatch.setattr(ClaimRepository, "_insert_payload", original)
        database.stop()


def test_second_acceptance_reuses_exact_canonical_duplicates(tmp_path) -> None:
    database, result, knowledge, claims, acceptance = _extracted(tmp_path)
    try:
        first = acceptance.accept_all(result)
        second_result = result
        plan = acceptance.preflight(second_result)

        assert all(item.action.value == "reuse_canonical" for item in plan.knowledge)
        assert all(item.action.value == "reuse_canonical" for item in plan.claims)

        second = acceptance.accept_all(second_result, expected_plan=plan)
        assert second.knowledge_ids == first.knowledge_ids
        assert second.claim_ids == first.claim_ids
        assert second.knowledge_created_ids == ()
        assert second.claim_created_ids == ()
        assert len(second.knowledge_reused_ids) == 2
        assert len(second.claim_reused_ids) == 2
        assert second.contradiction_pairs == ()
        assert second.contradiction_pairs_reused == ()
        assert len(second.contradiction_review_ids) == 1

        knowledge_count = database.connection.execute(
            "SELECT COUNT(*) FROM knowledge_units"
        ).fetchone()[0]
        claim_count = database.connection.execute("SELECT COUNT(*) FROM claims").fetchone()[0]
        assert knowledge_count == 2
        assert claim_count == 2

        reused_provenance = database.connection.execute(
            "SELECT COUNT(*) FROM provenance_records "
            "WHERE operation IN ('knowledge.duplicate.reused', 'claim.duplicate.reused')"
        ).fetchone()[0]
        assert reused_provenance == 4
    finally:
        database.stop()


def test_dedup_preflight_surfaces_near_duplicate_and_blocks_acceptance(tmp_path) -> None:
    database, result, _knowledge, _claims, acceptance = _extracted(tmp_path)
    try:
        first = acceptance.accept_all(result)
        first_knowledge = first.knowledge_ids[0]
        current = database.connection.execute(
            """
            SELECT h.current_revision_id
            FROM entity_heads AS h
            WHERE h.entity_id = ?
            """,
            (first_knowledge.bytes,),
        ).fetchone()
        assert current is not None

        # Modify only canonical text enough to be non-exact but still textually near.
        database.connection.execute(
            "UPDATE knowledge_unit_revisions SET body = ? WHERE revision_id = ?",
            (
                "Berlin ist die Hauptstadt Deutschlands.",
                current["current_revision_id"],
            ),
        )
        database.connection.commit()

        plan = acceptance.preflight(result)
        assert plan.merge_candidates
        with pytest.raises(ValueError, match="near-duplicates"):
            acceptance.accept_all(result, expected_plan=plan)
    finally:
        database.stop()


def test_acceptance_reuses_duplicate_knowledge_proposal_within_same_run(tmp_path) -> None:
    database, result, _knowledge, _claims, acceptance = _extracted(tmp_path)
    try:
        duplicate = result.proposals.knowledge_units[0]
        proposals = replace(
            result.proposals,
            knowledge_units=(duplicate, duplicate),
            claims=(),
            relations=(),
        )
        duplicate_result = replace(result, proposals=proposals)

        plan = acceptance.preflight(duplicate_result)
        assert plan.knowledge[0].action.value == "create"
        assert plan.knowledge[1].action.value == "reuse_proposal"

        accepted = acceptance.accept_all(duplicate_result, expected_plan=plan)

        assert len(accepted.knowledge_ids) == 2
        assert accepted.knowledge_ids[0] == accepted.knowledge_ids[1]
        assert len(accepted.knowledge_created_ids) == 1
        assert len(accepted.knowledge_reused_ids) == 1

        knowledge_count = database.connection.execute(
            "SELECT COUNT(*) FROM knowledge_units"
        ).fetchone()[0]
        assert knowledge_count == 1
    finally:
        database.stop()
