from __future__ import annotations

import json
import uuid
from collections.abc import Iterator, Mapping, Sequence
from typing import Any

import pytest

from athena.chat.generation import ChatGenerationService
from athena.chat.repository import ChatRepository
from athena.chat.service import ChatService
from athena.knowledge.extraction_models import (
    CONTRADICTION_AUDIT_SCHEMA_ID,
    EXTRACTION_SCHEMA_ID,
    ExtractionValidationError,
    extraction_json_schema,
    parse_extraction_proposals,
)
from athena.knowledge.extraction_service import (
    ChatKnowledgeExtractionService,
    ExtractionMessageNotFoundError,
    ExtractionMessageRevisionMismatchError,
)
from athena.model.domain import ModelChatMessage, ModelInfo, ProviderHealth, ProviderHealthStatus
from athena.model.provenance import ModelRunRepository
from athena.storage.database import SQLiteDatabase


class FakeStructuredProvider:
    provider_id = "fake"

    def __init__(
        self,
        extraction_payload: Mapping[str, Any],
        contradiction_payload: Mapping[str, Any] | None = None,
    ) -> None:
        self.extraction_payload = extraction_payload
        self.contradiction_payload = contradiction_payload
        self.calls: list[tuple[str, Sequence[ModelChatMessage]]] = []

    def health(self) -> ProviderHealth:
        return ProviderHealth(ProviderHealthStatus.READY)

    def discover_models(self) -> tuple[ModelInfo, ...]:
        return (
            ModelInfo(
                provider=self.provider_id,
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
        del model_id, json_schema, max_output_tokens
        self.calls.append((schema_id, messages))
        if schema_id == EXTRACTION_SCHEMA_ID:
            return self.extraction_payload
        if schema_id == CONTRADICTION_AUDIT_SCHEMA_ID and self.contradiction_payload is not None:
            return self.contradiction_payload
        raise AssertionError(f"Unexpected schema request: {schema_id}")


def _service(
    database: SQLiteDatabase,
    provider: FakeStructuredProvider,
) -> tuple[ChatService, ChatKnowledgeExtractionService]:
    chat = ChatService(ChatRepository(database))
    generation = ChatGenerationService(chat, provider)
    extraction = ChatKnowledgeExtractionService(
        chat=chat,
        chat_generation=generation,
        provider=provider,
        runs=ModelRunRepository(database),
    )
    return chat, extraction


def _valid_payload() -> Mapping[str, Any]:
    return {
        "knowledge_units": [
            {
                "source_sequence_no": 1,
                "source_quote": "The project uses SQLite for local transactional state.",
                "knowledge_kind": "fact",
                "title": "Project database",
                "body": "The project uses SQLite for local transactional state.",
                "epistemic_status": "asserted",
                "confidence": 0.95,
            }
        ],
        "claims": [
            {
                "source_sequence_no": 1,
                "source_quote": "The project uses SQLite",
                "claim_kind": "factual_assertion",
                "statement": "The project uses SQLite.",
                "epistemic_status": "asserted",
                "confidence": 0.9,
            }
        ],
        "relations": [
            {
                "left_type": "knowledge",
                "left_index": 0,
                "relation_type": "contains_claim",
                "right_type": "claim",
                "right_index": 0,
                "confidence": 0.9,
            }
        ],
        "merge_candidates": [],
    }


def test_extraction_returns_grounded_proposals_without_canonical_writes(tmp_path) -> None:
    database = SQLiteDatabase(tmp_path / "athena.db")
    database.start()
    provider = FakeStructuredProvider(_valid_payload())
    chat, extraction = _service(database, provider)
    chat_id = chat.create_chat()
    chat.add_user_message(
        chat_id=chat_id,
        content="The project uses SQLite for local transactional state.",
    )

    result = extraction.extract_chat(chat_id=chat_id)

    assert result.processing_run.status == "succeeded"
    assert result.model_signature.model_identifier == "fake/model"
    assert result.proposals.knowledge_units[0].source_sequence_no == 1
    assert result.proposals.knowledge_units[0].source_quote.startswith("The project uses")
    assert result.proposals.claims[0].statement == "The project uses SQLite."
    assert provider.calls[0][0] == EXTRACTION_SCHEMA_ID
    assert "[1] user:" in provider.calls[0][1][1].content

    connection = database.connection
    assert connection.execute("SELECT COUNT(*) FROM knowledge_units").fetchone()[0] == 0
    assert connection.execute("SELECT COUNT(*) FROM claims").fetchone()[0] == 0
    assert connection.execute("SELECT COUNT(*) FROM model_signatures").fetchone()[0] == 1
    run = connection.execute("SELECT status FROM processing_runs").fetchone()
    assert run is not None
    assert run["status"] == "succeeded"
    database.stop()


def test_extraction_rejects_invented_source_sequence_and_marks_run_failed(tmp_path) -> None:
    database = SQLiteDatabase(tmp_path / "athena.db")
    database.start()
    payload = dict(_valid_payload())
    payload["knowledge_units"] = []
    payload["claims"] = [
        {
            "source_sequence_no": 99,
            "source_quote": "Invented source.",
            "claim_kind": "factual_assertion",
            "statement": "Invented source.",
            "epistemic_status": "asserted",
            "confidence": 0.5,
        }
    ]
    provider = FakeStructuredProvider(payload)
    chat, extraction = _service(database, provider)
    chat_id = chat.create_chat()
    chat.add_user_message(chat_id=chat_id, content="Only one source message exists.")

    with pytest.raises(ExtractionValidationError, match="does not exist"):
        extraction.extract_chat(chat_id=chat_id)

    connection = database.connection
    run = connection.execute("SELECT status, error_detail FROM processing_runs").fetchone()
    assert run is not None
    assert run["status"] == "failed"
    assert run["error_detail"] == "ExtractionValidationError"
    assert connection.execute("SELECT COUNT(*) FROM knowledge_units").fetchone()[0] == 0
    assert connection.execute("SELECT COUNT(*) FROM claims").fetchone()[0] == 0
    database.stop()


def test_extraction_rejects_source_quote_not_present_in_cited_message(tmp_path) -> None:
    database = SQLiteDatabase(tmp_path / "athena.db")
    database.start()
    payload = dict(_valid_payload())
    payload["knowledge_units"] = []
    payload["claims"] = [
        {
            "source_sequence_no": 1,
            "source_quote": "SQLite is the world's most popular database.",
            "claim_kind": "factual_assertion",
            "statement": "SQLite is the world's most popular database.",
            "epistemic_status": "asserted",
            "confidence": 0.5,
        }
    ]
    provider = FakeStructuredProvider(payload)
    chat, extraction = _service(database, provider)
    chat_id = chat.create_chat()
    chat.add_user_message(
        chat_id=chat_id,
        content="The project uses SQLite for local transactional state.",
    )

    with pytest.raises(ExtractionValidationError, match="exact contiguous quote"):
        extraction.extract_chat(chat_id=chat_id)

    run = database.connection.execute(
        "SELECT status, error_detail FROM processing_runs"
    ).fetchone()
    assert run is not None
    assert run["status"] == "failed"
    assert run["error_detail"] == "ExtractionValidationError"
    database.stop()


def test_every_claim_pair_is_audited_and_contradiction_is_added(tmp_path) -> None:
    database = SQLiteDatabase(tmp_path / "athena.db")
    database.start()
    extraction_payload = {
        "knowledge_units": [],
        "claims": [
            {
                "source_sequence_no": 1,
                "source_quote": "Berlin ist die Hauptstadt von Deutschland.",
                "claim_kind": "factual_assertion",
                "statement": "Berlin ist die Hauptstadt von Deutschland.",
                "epistemic_status": "asserted",
                "confidence": 0.95,
            },
            {
                "source_sequence_no": 2,
                "source_quote": "München ist die Hauptstadt von Deutschland.",
                "claim_kind": "factual_assertion",
                "statement": "München ist die Hauptstadt von Deutschland.",
                "epistemic_status": "asserted",
                "confidence": 0.95,
            },
        ],
        "relations": [],
        "merge_candidates": [],
    }
    audit_payload = {
        "assessments": [
            {
                "left_claim_index": 0,
                "right_claim_index": 1,
                "relationship": "contradicts",
                "confidence": 0.99,
                "reason": "Both assign the same singular capital role to different cities.",
            }
        ]
    }
    provider = FakeStructuredProvider(extraction_payload, audit_payload)
    chat, extraction = _service(database, provider)
    chat_id = chat.create_chat()
    chat.add_user_message(chat_id=chat_id, content="Berlin ist die Hauptstadt von Deutschland.")
    chat.add_user_message(chat_id=chat_id, content="München ist die Hauptstadt von Deutschland.")

    result = extraction.extract_chat(chat_id=chat_id)

    assert [call[0] for call in provider.calls] == [
        EXTRACTION_SCHEMA_ID,
        CONTRADICTION_AUDIT_SCHEMA_ID,
    ]
    rows = database.connection.execute(
        "SELECT run_type, status, input_snapshot_json FROM processing_runs "
        "WHERE run_type IN ('knowledge_extraction', 'knowledge_extraction_claim_audit')"
    ).fetchall()
    by_type = {str(row["run_type"]): row for row in rows}
    assert set(by_type) == {"knowledge_extraction", "knowledge_extraction_claim_audit"}
    for row in by_type.values():
        assert row["status"] == "succeeded"
        snapshot = json.loads(str(row["input_snapshot_json"]))
        package = snapshot["context_package"]
        assert package["snapshot_commit_seq"] >= 0
        assert package["model_signature"]["model_signature_id"]
        assert package["structured_output"]["schema_id"] in {
            EXTRACTION_SCHEMA_ID, CONTRADICTION_AUDIT_SCHEMA_ID
        }

    contradiction = result.proposals.relations[0]
    assert contradiction.left_index == 0
    assert contradiction.right_index == 1
    assert contradiction.relation_type == "contradicts"
    assert contradiction.confidence == pytest.approx(0.99)
    assert database.connection.execute("SELECT COUNT(*) FROM claims").fetchone()[0] == 0
    database.stop()


def test_incomplete_claim_pair_audit_marks_run_failed(tmp_path) -> None:
    database = SQLiteDatabase(tmp_path / "athena.db")
    database.start()
    extraction_payload = {
        "knowledge_units": [],
        "claims": [
            {
                "source_sequence_no": index,
                "source_quote": f"Claim {index}.",
                "claim_kind": "factual_assertion",
                "statement": f"Claim {index}.",
                "epistemic_status": "asserted",
                "confidence": 0.8,
            }
            for index in (1, 2, 3)
        ],
        "relations": [],
        "merge_candidates": [],
    }
    audit_payload = {
        "assessments": [
            {
                "left_claim_index": 0,
                "right_claim_index": 1,
                "relationship": "compatible_or_unknown",
                "confidence": 0.6,
                "reason": "No direct incompatibility.",
            }
        ]
    }
    provider = FakeStructuredProvider(extraction_payload, audit_payload)
    chat, extraction = _service(database, provider)
    chat_id = chat.create_chat()
    for index in (1, 2, 3):
        chat.add_user_message(chat_id=chat_id, content=f"Claim {index}.")

    with pytest.raises(ExtractionValidationError, match="every unordered pair"):
        extraction.extract_chat(chat_id=chat_id)

    run = database.connection.execute("SELECT status FROM processing_runs").fetchone()
    assert run is not None
    assert run["status"] == "failed"
    database.stop()


def test_message_scoped_extraction_uses_only_selected_stable_revision(tmp_path) -> None:
    database = SQLiteDatabase(tmp_path / "athena.db")
    database.start()
    payload = {
        "knowledge_units": [
            {
                "source_sequence_no": 2,
                "source_quote": "The selected message uses SQLite.",
                "knowledge_kind": "fact",
                "title": "Selected database fact",
                "body": "The selected message uses SQLite.",
                "epistemic_status": "asserted",
                "confidence": 0.95,
            }
        ],
        "claims": [],
        "relations": [],
        "merge_candidates": [],
    }
    provider = FakeStructuredProvider(payload)
    chat, extraction = _service(database, provider)

    try:
        chat_id = chat.create_chat()
        first = chat.add_user_message(
            chat_id=chat_id,
            content="This message must not enter the scoped extraction.",
        )
        selected = chat.add_user_message(
            chat_id=chat_id,
            content="The selected message uses SQLite.",
        )

        result = extraction.extract_message(
            chat_id=chat_id,
            message_id=selected.message_id,
            revision_id=selected.revision_id,
        )

        assert result.processing_run.status == "succeeded"
        assert result.proposals.knowledge_units[0].source_sequence_no == 2
        assert len(provider.calls) == 1
        prompt = provider.calls[0][1][1].content
        assert "[2] user:" in prompt
        assert selected.content in prompt
        assert first.content not in prompt

        row = database.connection.execute(
            "SELECT input_snapshot_json FROM processing_runs "
            "WHERE run_type = 'knowledge_extraction'"
        ).fetchone()
        assert row is not None
        snapshot = json.loads(str(row["input_snapshot_json"]))
        assert snapshot["messages"] == [
            {
                "sequence_no": selected.sequence_no,
                "message_id": str(selected.message_id),
                "revision_id": str(selected.revision_id),
                "message_type": "user",
            }
        ]
    finally:
        database.stop()


def test_message_scoped_extraction_rejects_message_from_outside_chat(tmp_path) -> None:
    database = SQLiteDatabase(tmp_path / "athena.db")
    database.start()
    provider = FakeStructuredProvider(_valid_payload())
    chat, extraction = _service(database, provider)

    try:
        chat_id = chat.create_chat()
        message = chat.add_user_message(
            chat_id=chat_id,
            content="Only this persisted message exists.",
        )

        with pytest.raises(
            ExtractionMessageNotFoundError,
            match="has no message",
        ):
            extraction.extract_message(
                chat_id=chat_id,
                message_id=uuid.uuid4(),
                revision_id=message.revision_id,
            )

        assert provider.calls == []
        assert (
            database.connection.execute(
                "SELECT COUNT(*) FROM processing_runs"
            ).fetchone()[0]
            == 0
        )
    finally:
        database.stop()


def test_message_scoped_extraction_rejects_stale_revision_before_model_call(
    tmp_path,
) -> None:
    database = SQLiteDatabase(tmp_path / "athena.db")
    database.start()
    provider = FakeStructuredProvider(_valid_payload())
    chat, extraction = _service(database, provider)

    try:
        chat_id = chat.create_chat()
        message = chat.add_user_message(
            chat_id=chat_id,
            content="Only this persisted message exists.",
        )

        with pytest.raises(
            ExtractionMessageRevisionMismatchError,
            match="revision is stale",
        ):
            extraction.extract_message(
                chat_id=chat_id,
                message_id=message.message_id,
                revision_id=uuid.uuid4(),
            )

        assert provider.calls == []
        assert (
            database.connection.execute(
                "SELECT COUNT(*) FROM processing_runs"
            ).fetchone()[0]
            == 0
        )
    finally:
        database.stop()


def test_extraction_schema_excludes_attributed_opinion() -> None:
    schema = extraction_json_schema()
    claim_enum = schema["properties"]["claims"]["items"]["properties"]["claim_kind"]["enum"]

    assert "factual_assertion" in claim_enum
    assert "attributed_opinion" not in claim_enum


def test_parser_rejects_attributed_opinion_until_attribution_is_bindable() -> None:
    payload = {
        "knowledge_units": [],
        "claims": [
            {
                "source_sequence_no": 1,
                "source_quote": "Berlin ist die Hauptstadt von Deutschland.",
                "claim_kind": "attributed_opinion",
                "statement": "Berlin ist die Hauptstadt von Deutschland.",
                "epistemic_status": "asserted",
                "confidence": 0.95,
            }
        ],
        "relations": [],
        "merge_candidates": [],
    }

    with pytest.raises(ExtractionValidationError, match="attributed_opinion"):
        parse_extraction_proposals(
            payload,
            source_messages={1: "Berlin ist die Hauptstadt von Deutschland."},
        )


def test_extraction_prompt_preserves_source_language_and_disallows_unbound_attribution(
    tmp_path,
) -> None:
    database = SQLiteDatabase(tmp_path / "athena.db")
    database.start()
    provider = FakeStructuredProvider(_valid_payload())
    chat_service, extraction_service = _service(database, provider)

    try:
        chat_id = chat_service.create_chat()
        chat_service.add_user_message(
            chat_id=chat_id,
            content="Berlin ist die Hauptstadt von Deutschland.",
        )
        prompt = extraction_service._build_prompt(
            chat_service.load_chat(chat_id).messages
        )
    finally:
        database.stop()

    assert "attributed_opinion kind is unavailable" in prompt.system_message
    assert "Preserve the source language" in prompt.system_message
