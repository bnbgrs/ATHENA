from __future__ import annotations

import uuid
from collections.abc import Iterator, Sequence
from pathlib import Path

import pytest

from athena.chat.generation import ChatGenerationService
from athena.chat.models import MessageType
from athena.chat.repository import ChatRepository
from athena.chat.service import ChatService
from athena.model.domain import (
    ModelChatMessage,
    ModelInfo,
    ProviderHealth,
    ProviderHealthStatus,
)
from athena.model.provenance import ModelSignature
from athena.retrieval.context import ContextBuilderService
from athena.retrieval.context_package import (
    ContextPackageBudget,
    ContextPackageService,
    ContextTokenEstimates,
)
from athena.storage.database import SQLiteDatabase


class FakeProvider:
    provider_id = "lm_studio"

    def __init__(self) -> None:
        self.requests: list[tuple[str, tuple[ModelChatMessage, ...]]] = []

    def health(self) -> ProviderHealth:
        return ProviderHealth(ProviderHealthStatus.READY)

    def discover_models(self) -> tuple[ModelInfo, ...]:
        return (
            ModelInfo(
                provider="lm_studio",
                backend_model_id="primary",
                display_name="primary",
                model_type="llm",
                context_capacity=32768,
                quantization="Q4_K_M",
                loaded=True,
                vision=False,
                trained_for_tool_use=False,
                loaded_context_length=4096,
            ),
        )

    def stream_chat(
        self,
        *,
        model_id: str,
        messages: Sequence[ModelChatMessage],
        max_output_tokens: int | None = None,
        reasoning_mode: str | None = None,
    ) -> Iterator[str]:
        assert max_output_tokens == 1000
        assert reasoning_mode == "off"
        self.requests.append((model_id, tuple(messages)))
        yield "Package answer"


def _signature() -> ModelSignature:
    return ModelSignature(
        model_signature_id=uuid.uuid4(),
        provider="lm_studio",
        model_identifier="primary",
        model_revision=None,
        quantization="Q4_K_M",
        generation_parameters_json=(
            '{"max_output_tokens":1000,"reasoning_mode":"off"}'
        ),
        context_configuration_json='{"context_package_version":1}',
        signature_hash=b"s" * 32,
        created_at_us=1,
    )


def _database(tmp_path: Path) -> SQLiteDatabase:
    database = SQLiteDatabase(tmp_path / "athena.db")
    database.start()
    return database


def _package(current, *, snapshot_commit_seq: int):
    context = ContextBuilderService().build_from_ranked(
        query=current.content or "Current request",
        results=(),
        max_estimated_tokens=300,
    )
    return ContextPackageService.build(
        model_signature=_signature(),
        context=context,
        system_text="PACKAGE SYSTEM",
        prior_messages=(),
        current_user_message=current,
        budget=ContextPackageBudget(
            effective_context_limit=4096,
            context_budget=300,
            output_reserve=1000,
            safety_margin=200,
        ),
        token_estimates=ContextTokenEstimates(
            conversation_tokens=0,
            current_user_tokens=10,
            system_tokens=10,
            context_tokens=context.estimated_tokens,
            estimated_input_tokens=20,
            estimated_total_tokens=1220,
        ),
        snapshot_commit_seq=snapshot_commit_seq,
        retrieval_candidate_count=0,
        memory_candidate_count=0,
    )


def test_context_package_generation_uses_only_package_messages(tmp_path) -> None:
    database = _database(tmp_path)
    try:
        chat = ChatService(ChatRepository(database))
        chat_id = chat.create_chat()
        chat.add_user_message(chat_id=chat_id, content="Hidden historical user turn")
        chat.add_assistant_message(
            chat_id=chat_id,
            content="Hidden historical assistant turn",
            provider_id="lm_studio",
            model_id="old",
        )
        current = chat.add_user_message(chat_id=chat_id, content="Current request")
        package = _package(current, snapshot_commit_seq=4)

        provider = FakeProvider()
        service = ChatGenerationService(chat, provider)
        guard_calls: list[bool] = []
        result = service.send_context_package(
            chat_id=chat_id,
            user_message=current,
            context_package=package,
            on_before_provider_call=lambda: guard_calls.append(True),
        )

        assert guard_calls == [True]
        assert provider.requests == [("primary", package.model_messages())]
        flattened = "\n".join(message.content for message in provider.requests[0][1])
        assert "Hidden historical user turn" not in flattened
        assert "Hidden historical assistant turn" not in flattened
        assert result.user_message.message_id == current.message_id
        assert result.assistant_message.message_type is MessageType.ASSISTANT
    finally:
        database.stop()


def test_context_package_guard_runs_before_provider_stream(tmp_path) -> None:
    database = _database(tmp_path)
    try:
        chat = ChatService(ChatRepository(database))
        chat_id = chat.create_chat()
        current = chat.add_user_message(chat_id=chat_id, content="Current request")
        package = _package(current, snapshot_commit_seq=2)

        provider = FakeProvider()
        service = ChatGenerationService(chat, provider)

        def reject() -> None:
            raise RuntimeError("snapshot drift")

        with pytest.raises(RuntimeError, match="snapshot drift"):
            service.send_context_package(
                chat_id=chat_id,
                user_message=current,
                context_package=package,
                on_before_provider_call=reject,
            )

        assert provider.requests == []
        thread = chat.load_chat(chat_id)
        assert thread.messages[-1].message_id == current.message_id
    finally:
        database.stop()
