from __future__ import annotations

from collections.abc import Iterator, Mapping, Sequence
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
    ) -> Mapping[str, Any]:
        del model_id, messages, json_schema
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
                        "confidence": 0.95,
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
        assert len(accepted.contradiction_pairs) == 1

        first_knowledge = knowledge.load_current(accepted.knowledge_ids[0])
        assert first_knowledge.revision.payload.body == "Berlin ist die Hauptstadt von Deutschland."
        inputs = knowledge.list_provenance_inputs(first_knowledge.revision.provenance_id)
        assert len(inputs) == 1
        first_claim = claims.load_current(accepted.claim_ids[0])
        evidence = claims.list_evidence(first_claim.claim_id)
        assert {item.evidence_role.value for item in evidence} == {"originates", "contradicts"}

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
