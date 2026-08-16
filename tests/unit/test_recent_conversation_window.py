from __future__ import annotations

import json
from collections.abc import Iterator, Sequence
from pathlib import Path

import pytest

from athena.chat.generation import ChatGenerationService
from athena.chat.memory import MemoryAugmentedChatService
from athena.chat.repository import ChatRepository
from athena.chat.service import ChatService
from athena.model.domain import (
    ModelChatMessage,
    ModelInfo,
    ProviderHealth,
    ProviderHealthStatus,
)
from athena.model.provenance import ModelRunRepository
from athena.retrieval.context import ContextBuilderService
from athena.retrieval.context_package import ContextPackageService
from athena.retrieval.evidence import MemoryEvidencePolicy
from athena.retrieval.hybrid import HybridSearchResult
from athena.retrieval.search import SearchEntityType
from athena.storage.database import SQLiteDatabase


class FakeProvider:
    provider_id = "lm_studio"

    def __init__(self, answer: str) -> None:
        self.answer = answer
        self.requests: list[tuple[str, tuple[ModelChatMessage, ...]]] = []

    def health(self) -> ProviderHealth:
        return ProviderHealth(ProviderHealthStatus.READY)

    def discover_models(self) -> tuple[ModelInfo, ...]:
        return (
            ModelInfo(
                provider="lm_studio",
                backend_model_id="primary-test",
                display_name="primary-test",
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
        yield self.answer


class FakeEmbeddingProvider:
    def resolve_model(self, requested_model_id: str | None = None) -> ModelInfo:
        return ModelInfo(
            provider="lm_studio",
            backend_model_id=requested_model_id or "embed-test",
            display_name="embed-test",
            model_type="embedding",
            context_capacity=2048,
            quantization="Q4_K_M",
            loaded=True,
            vision=False,
            trained_for_tool_use=False,
            loaded_context_length=2048,
        )


class FakeHybrid:
    def __init__(self, results: tuple[HybridSearchResult, ...] = ()) -> None:
        self.results = results

    def search(
        self,
        query: str,
        *,
        model_id: str,
        limit: int,
    ) -> tuple[HybridSearchResult, ...]:
        return self.results


class FakePersonalMemory:
    def context_candidates(
        self,
        *,
        scope_kind=None,
        scope_entity_id=None,
        limit: int = 32,
    ):
        return ()


def _database(tmp_path: Path) -> SQLiteDatabase:
    database = SQLiteDatabase(tmp_path / "athena.db")
    database.start()
    return database


def _service(
    database: SQLiteDatabase,
    chat: ChatService,
    provider: FakeProvider,
    hybrid: FakeHybrid,
) -> MemoryAugmentedChatService:
    return MemoryAugmentedChatService(
        chat_generation=ChatGenerationService(chat, provider),
        embedding_provider=FakeEmbeddingProvider(),  # type: ignore[arg-type]
        hybrid_retrieval=hybrid,  # type: ignore[arg-type]
        context_builder=ContextBuilderService(),
        context_packages=ContextPackageService(database),
        evidence_policy=MemoryEvidencePolicy(database),
        personal_memory=FakePersonalMemory(),  # type: ignore[arg-type]
        model_runs=ModelRunRepository(database),
    )


def _add_turn(
    chat: ChatService,
    chat_id,
    *,
    user_text: str,
    assistant_text: str,
):
    user = chat.add_user_message(chat_id=chat_id, content=user_text)
    assistant = chat.add_assistant_message(
        chat_id=chat_id,
        content=assistant_text,
        provider_id="lm_studio",
        model_id="history-model",
    )
    return user, assistant


def test_recent_conversation_window_is_turn_bounded_and_accounted(tmp_path) -> None:
    database = _database(tmp_path)
    try:
        chat = ChatService(ChatRepository(database))
        chat_id = chat.create_chat()

        history = []
        for index in range(6):
            history.extend(
                _add_turn(
                    chat,
                    chat_id,
                    user_text=f"user-{index}",
                    assistant_text=f"assistant-{index}",
                )
            )

        provider = FakeProvider("Antwort. [MODEL-PRIOR]")
        result = _service(
            database,
            chat,
            provider,
            FakeHybrid(),
        ).send_message(
            chat_id=chat_id,
            content="Aktuelle Frage",
            requested_model_id="primary-test",
            requested_embedding_model_id="embed-test",
            max_recent_conversation_turns=2,
            max_context_tokens=500,
            output_reserve=1000,
            safety_margin=200,
        )

        package = result.context_package
        conversation_sections = tuple(
            section for section in package.sections if section.name == "conversation"
        )
        assert tuple(section.content for section in conversation_sections) == (
            "user-4",
            "user-5",
        )

        expected_ids = {
            history[-4].message_id,
            history[-2].message_id,
        }
        included_history_ids = {
            item.entity_id
            for item in package.included_refs
            if item.ref_id.startswith("CHAT-HIST-")
        }
        assert included_history_ids == expected_ids

        summary = package.excluded_candidate_summary
        assert summary.conversation_candidate_count == 12
        assert summary.conversation_included_count == 2
        assert summary.conversation_excluded_count == 10

        snapshot = json.loads(result.processing_run.input_snapshot_json)
        snapshot_summary = snapshot["excluded_candidate_summary"]
        assert snapshot_summary["conversation_candidate_count"] == 12
        assert snapshot_summary["conversation_included_count"] == 2
        assert snapshot_summary["conversation_excluded_count"] == 10

        assert provider.requests == [
            ("primary-test", package.model_messages())
        ]
        flattened = "\n".join(message.content for message in provider.requests[0][1])
        assert "user-0" not in flattened
        assert "assistant-0" not in flattened
        assert "assistant-4" not in flattened
        assert "assistant-5" not in flattened
    finally:
        database.stop()


def test_large_old_chat_does_not_consume_direct_context_budget(tmp_path) -> None:
    database = _database(tmp_path)
    try:
        chat = ChatService(ChatRepository(database))
        chat_id = chat.create_chat()

        old_payload = "OLD-ARCHIVE " * 1200
        for index in range(10):
            _add_turn(
                chat,
                chat_id,
                user_text=f"old-user-{index} {old_payload}",
                assistant_text=f"old-assistant-{index} {old_payload}",
            )

        _add_turn(
            chat,
            chat_id,
            user_text="recent-user-0",
            assistant_text="recent-assistant-0",
        )
        _add_turn(
            chat,
            chat_id,
            user_text="recent-user-1",
            assistant_text="recent-assistant-1",
        )

        provider = FakeProvider("Antwort. [MODEL-PRIOR]")
        result = _service(
            database,
            chat,
            provider,
            FakeHybrid(),
        ).send_message(
            chat_id=chat_id,
            content="Neue kurze Frage",
            requested_model_id="primary-test",
            requested_embedding_model_id="embed-test",
            max_recent_conversation_turns=2,
            max_context_tokens=500,
            output_reserve=1000,
            safety_margin=200,
        )

        assert result.budget.estimated_total_tokens <= 4096
        assert result.context_package.token_estimates.conversation_tokens < 100

        summary = result.context_package.excluded_candidate_summary
        assert summary.conversation_candidate_count == 24
        assert summary.conversation_included_count == 2
        assert summary.conversation_excluded_count == 22

        sent = "\n".join(message.content for message in provider.requests[0][1])
        assert "OLD-ARCHIVE" not in sent
        assert "recent-user-0" in sent
        assert "recent-user-1" in sent
        assert "recent-assistant-0" not in sent
        assert "recent-assistant-1" not in sent
    finally:
        database.stop()


def test_older_turn_can_return_via_retrieval_without_direct_window_replay(tmp_path) -> None:
    database = _database(tmp_path)
    try:
        chat = ChatService(ChatRepository(database))
        chat_id = chat.create_chat()

        old_user, _old_assistant = _add_turn(
            chat,
            chat_id,
            user_text="Mein Projektcode ist ORION-17.",
            assistant_text="Verstanden.",
        )

        for index in range(3):
            _add_turn(
                chat,
                chat_id,
                user_text=f"recent-user-{index}",
                assistant_text=f"recent-assistant-{index}",
            )

        old_result = HybridSearchResult(
            entity_id=old_user.message_id,
            revision_id=old_user.revision_id,
            entity_type=SearchEntityType.CHAT_MESSAGE,
            title=None,
            text=old_user.content or "",
            score=0.03,
            lexical_score=0.016,
            semantic_score=0.014,
            authority_score=0.68,
            contradiction_count=0,
            duplicate_count=0,
        )

        provider = FakeProvider(
            "Der gespeicherte Benutzerhinweis lautet ORION-17. "
            "[USER-STATEMENT:CTX-001]"
        )
        result = _service(
            database,
            chat,
            provider,
            FakeHybrid((old_result,)),
        ).send_message(
            chat_id=chat_id,
            content="Wie lautete mein alter Projektcode?",
            requested_model_id="primary-test",
            requested_embedding_model_id="embed-test",
            max_recent_conversation_turns=1,
            max_context_tokens=800,
            output_reserve=1000,
            safety_margin=200,
        )

        assert result.context.items
        assert result.context.items[0].entity_id == old_user.message_id

        direct_history_ids = {
            item.entity_id
            for item in result.context_package.included_refs
            if item.ref_id.startswith("CHAT-HIST-")
        }
        assert old_user.message_id not in direct_history_ids

        retrieved_refs = tuple(
            item
            for item in result.context_package.included_refs
            if item.ref_id == "CTX-001"
        )
        assert len(retrieved_refs) == 1
        assert retrieved_refs[0].entity_id == old_user.message_id
        assert retrieved_refs[0].revision_id == old_user.revision_id

        summary = result.context_package.excluded_candidate_summary
        assert summary.conversation_candidate_count == 8
        assert summary.conversation_included_count == 1
        assert summary.conversation_excluded_count == 7

        sent = provider.requests[0][1]
        system_text = sent[0].content
        assert "ORION-17" in system_text
        direct_conversation_text = "\n".join(
            section.content
            for section in result.context_package.sections
            if section.name == "conversation"
        )
        assert "ORION-17" not in direct_conversation_text
        assert "recent-assistant-2" not in direct_conversation_text
    finally:
        database.stop()


def test_recent_conversation_turn_limit_rejects_zero_before_retrieval(tmp_path) -> None:
    database = _database(tmp_path)
    try:
        chat = ChatService(ChatRepository(database))
        chat_id = chat.create_chat()
        provider = FakeProvider("unused [MODEL-PRIOR]")
        hybrid = FakeHybrid()

        with pytest.raises(ValueError, match="Recent conversation turns"):
            _service(database, chat, provider, hybrid).send_message(
                chat_id=chat_id,
                content="test",
                requested_model_id="primary-test",
                max_recent_conversation_turns=0,
            )

        assert hybrid.results == ()
        assert provider.requests == []
    finally:
        database.stop()
