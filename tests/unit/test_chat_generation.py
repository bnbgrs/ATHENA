from __future__ import annotations

import uuid
from collections.abc import Iterator, Sequence
from pathlib import Path

import pytest

from athena.chat.generation import ChatGenerationService, ModelSelectionError
from athena.chat.grounding import (
    GroundingContract,
    GroundingEvidenceRef,
    GroundingViolation,
)
from athena.chat.models import MessageType
from athena.chat.repository import ChatRepository
from athena.chat.service import ChatService
from athena.model.domain import ModelChatMessage, ModelInfo, ProviderHealth, ProviderHealthStatus
from athena.storage.database import SQLiteDatabase


class FakeProvider:
    provider_id = "lm_studio"

    def __init__(self, models: tuple[ModelInfo, ...], chunks: tuple[str, ...]) -> None:
        self.models = models
        self.chunks = chunks
        self.requests: list[tuple[str, tuple[ModelChatMessage, ...]]] = []

    def health(self) -> ProviderHealth:
        return ProviderHealth(ProviderHealthStatus.READY)

    def discover_models(self) -> tuple[ModelInfo, ...]:
        return self.models

    def stream_chat(
        self,
        *,
        model_id: str,
        messages: Sequence[ModelChatMessage],
    ) -> Iterator[str]:
        self.requests.append((model_id, tuple(messages)))
        yield from self.chunks


def _model(model_id: str = "example/model", *, loaded: bool = True) -> ModelInfo:
    return ModelInfo(
        provider="lm_studio",
        backend_model_id=model_id,
        display_name=model_id,
        model_type="llm",
        context_capacity=32768,
        quantization="Q4_K_M",
        loaded=loaded,
        vision=False,
        trained_for_tool_use=False,
    )


def _chat_service(tmp_path: Path) -> tuple[SQLiteDatabase, ChatService]:
    database = SQLiteDatabase(tmp_path / "athena.db")
    database.start()
    return database, ChatService(ChatRepository(database))


def test_streamed_reply_is_persisted_only_after_completion(tmp_path) -> None:
    database, chat = _chat_service(tmp_path)
    try:
        chat_id = chat.create_chat()
        provider = FakeProvider((_model(),), ("Hello", " world"))
        service = ChatGenerationService(chat, provider)
        visible: list[str] = []

        result = service.send_message(
            chat_id=chat_id,
            content="Say hello",
            on_delta=visible.append,
        )

        assert visible == ["Hello", " world"]
        assert result.assistant_message.content == "Hello world"
        thread = chat.load_chat(chat_id)
        assert [message.message_type for message in thread.messages] == [
            MessageType.USER,
            MessageType.ASSISTANT,
        ]
        assert [message.content for message in thread.messages] == [
            "Say hello",
            "Hello world",
        ]
        assert provider.requests == [
            (
                "example/model",
                (ModelChatMessage(role="user", content="Say hello"),),
            )
        ]
    finally:
        database.stop()


def test_second_turn_uses_athena_persisted_history(tmp_path) -> None:
    database, chat = _chat_service(tmp_path)
    try:
        chat_id = chat.create_chat()
        provider = FakeProvider((_model(),), ("First answer",))
        service = ChatGenerationService(chat, provider)
        service.send_message(chat_id=chat_id, content="First question")

        provider.chunks = ("Second answer",)
        service.send_message(chat_id=chat_id, content="Second question")

        _, history = provider.requests[-1]
        assert history == (
            ModelChatMessage(role="user", content="First question"),
            ModelChatMessage(role="assistant", content="First answer"),
            ModelChatMessage(role="user", content="Second question"),
        )
    finally:
        database.stop()


def test_cancelled_stream_does_not_persist_partial_assistant(tmp_path) -> None:
    database, chat = _chat_service(tmp_path)
    try:
        chat_id = chat.create_chat()
        provider = FakeProvider((_model(),), ("partial", " never seen"))
        service = ChatGenerationService(chat, provider)

        def cancel_on_first_delta(_chunk: str) -> None:
            raise KeyboardInterrupt

        with pytest.raises(KeyboardInterrupt):
            service.send_message(
                chat_id=chat_id,
                content="Cancel this",
                on_delta=cancel_on_first_delta,
            )

        thread = chat.load_chat(chat_id)
        assert len(thread.messages) == 1
        assert thread.messages[0].message_type is MessageType.USER
        assert thread.messages[0].content == "Cancel this"
    finally:
        database.stop()


def test_multiple_loaded_models_require_explicit_selection(tmp_path) -> None:
    database, chat = _chat_service(tmp_path)
    try:
        provider = FakeProvider((_model("one"), _model("two")), ("unused",))
        service = ChatGenerationService(chat, provider)

        with pytest.raises(ModelSelectionError, match="Multiple loaded LLMs"):
            service.select_model()

        assert service.select_model("two").backend_model_id == "two"
    finally:
        database.stop()


def test_unloaded_explicit_model_is_rejected(tmp_path) -> None:
    database, chat = _chat_service(tmp_path)
    try:
        provider = FakeProvider((_model("cold", loaded=False),), ("unused",))
        service = ChatGenerationService(chat, provider)

        with pytest.raises(ModelSelectionError, match="not loaded"):
            service.select_model("cold")
    finally:
        database.stop()


def test_retrieved_context_is_ephemeral_system_input_not_persisted(tmp_path) -> None:
    database, chat = _chat_service(tmp_path)
    try:
        chat_id = chat.create_chat()
        provider = FakeProvider((_model(),), ("Grounded answer",))
        service = ChatGenerationService(chat, provider)

        service.send_message(
            chat_id=chat_id,
            content="What is remembered?",
            retrieved_context='{"items":[{"text":"stored evidence"}]}',
        )

        _, model_messages = provider.requests[-1]
        assert model_messages[0].role == "system"
        assert "untrusted evidence" in model_messages[0].content
        assert '"stored evidence"' in model_messages[0].content
        assert model_messages[1] == ModelChatMessage(
            role="user",
            content="What is remembered?",
        )

        thread = chat.load_chat(chat_id)
        assert [message.message_type for message in thread.messages] == [
            MessageType.USER,
            MessageType.ASSISTANT,
        ]
        assert all(message.content != model_messages[0].content for message in thread.messages)
    finally:
        database.stop()


def test_grounded_answer_is_validated_before_assistant_persistence(tmp_path) -> None:
    database, chat = _chat_service(tmp_path)
    try:
        chat_id = chat.create_chat()
        provider = FakeProvider((_model(),), ("Unsupported answer [CTX-999]",))
        service = ChatGenerationService(chat, provider)

        with pytest.raises(GroundingViolation, match="not supplied"):
            service.send_message(
                chat_id=chat_id,
                content="What is remembered?",
                retrieved_context='{"items":[{"context_id":"CTX-001"}]}',
                grounding_contract=GroundingContract(
                    evidence_refs=(
                        GroundingEvidenceRef(
                            context_id="CTX-001",
                            entity_type="knowledge",
                            entity_id=uuid.uuid4(),
                            revision_id=uuid.uuid4(),
                        ),
                    ),
                ),
            )

        thread = chat.load_chat(chat_id)
        assert [message.message_type for message in thread.messages] == [
            MessageType.USER,
        ]
    finally:
        database.stop()


def test_valid_grounded_answer_persists_with_grounding_report(tmp_path) -> None:
    database, chat = _chat_service(tmp_path)
    try:
        chat_id = chat.create_chat()
        provider = FakeProvider((_model(),), ("Stored evidence. [CTX-001]",))
        service = ChatGenerationService(chat, provider)

        result = service.send_message(
            chat_id=chat_id,
            content="What is remembered?",
            retrieved_context='{"items":[{"context_id":"CTX-001"}]}',
            grounding_contract=GroundingContract(
                evidence_refs=(
                    GroundingEvidenceRef(
                        context_id="CTX-001",
                        entity_type="knowledge",
                        entity_id=uuid.uuid4(),
                        revision_id=uuid.uuid4(),
                    ),
                ),
            ),
        )

        assert result.grounding_report is not None
        assert result.grounding_report.cited_context_ids == ("CTX-001",)
        assert "ATHENA_PROVENANCE" in result.assistant_message.content
        assert '"context_id":"CTX-001"' in result.assistant_message.content
        thread = chat.load_chat(chat_id)
        assert [message.message_type for message in thread.messages] == [
            MessageType.USER,
            MessageType.ASSISTANT,
        ]
    finally:
        database.stop()


def test_persisted_provenance_envelope_is_not_replayed_as_model_history(tmp_path) -> None:
    database, chat = _chat_service(tmp_path)
    try:
        chat_id = chat.create_chat()
        chat.add_user_message(chat_id=chat_id, content="First question")
        chat.add_assistant_message(
            chat_id=chat_id,
            content=(
                "First grounded answer. [MODEL-PRIOR]\n\n"
                'ATHENA_PROVENANCE {"athena_provenance_version":2,"evidence":[],"uses_model_prior":true}'
            ),
            provider_id="lm_studio",
            model_id="example/model",
        )
        provider = FakeProvider((_model(),), ("Second answer",))
        service = ChatGenerationService(chat, provider)

        service.send_message(chat_id=chat_id, content="Second question")

        _, history = provider.requests[-1]
        assert history == (
            ModelChatMessage(role="user", content="First question"),
            ModelChatMessage(
                role="assistant",
                content="First grounded answer. [MODEL-PRIOR]",
            ),
            ModelChatMessage(role="user", content="Second question"),
        )
        persisted = chat.load_chat(chat_id)
        assert "ATHENA_PROVENANCE" in (persisted.messages[1].content or "")
    finally:
        database.stop()
