from __future__ import annotations

import json
import uuid
from collections.abc import Callable

import pytest

from athena.chat.generation import ChatGenerationResult
from athena.chat.grounding import GroundingContract
from athena.chat.memory import MemoryAugmentedChatService
from athena.chat.models import ChatMessage, ChatThread, MessageType
from athena.memory.models import (
    MemoryKind,
    MemoryLearningMode,
    MemoryScopeKind,
    MemorySensitivity,
    PersonalMemoryDraft,
    PersonalMemoryRevision,
    PersonalMemorySnapshot,
)
from athena.model.domain import ModelInfo
from athena.retrieval.context import ContextBuilderService
from athena.retrieval.evidence import (
    EvidenceClass,
    MemoryEvidenceClassification,
    MemoryEvidenceSelection,
)
from athena.retrieval.hybrid import HybridSearchResult
from athena.retrieval.search import SearchEntityType


class FakeEmbeddingProvider:
    def resolve_model(self, requested_model_id: str | None = None) -> ModelInfo:
        return ModelInfo(
            provider="lm_studio",
            backend_model_id=requested_model_id or "embed",
            display_name="embed",
            model_type="embedding",
            context_capacity=None,
            quantization=None,
            loaded=True,
            vision=None,
            trained_for_tool_use=None,
        )


class FakeHybrid:
    def __init__(self) -> None:
        self.queries: list[str] = []
        self.result = HybridSearchResult(
            entity_id=uuid.uuid4(),
            revision_id=uuid.uuid4(),
            entity_type=SearchEntityType.KNOWLEDGE,
            title="Stored fact",
            text="Berlin ist die Hauptstadt von Deutschland.",
            score=0.95,
            lexical_score=0.8,
            semantic_score=1.0,
            authority_score=1.0,
            contradiction_count=1,
            duplicate_count=2,
        )

    def search(self, query: str, *, model_id: str, limit: int):
        self.queries.append(query)
        return (self.result,)


class FakeEvidencePolicy:
    def classify(
        self,
        results: tuple[HybridSearchResult, ...],
    ) -> MemoryEvidenceSelection:
        return MemoryEvidenceSelection(
            policy_id="typed-provenance-v1",
            results=results,
            classifications=tuple(
                MemoryEvidenceClassification(
                    entity_id=item.entity_id,
                    revision_id=item.revision_id,
                    entity_type=item.entity_type,
                    evidence_class=EvidenceClass.CANONICAL,
                    message_type=None,
                )
                for item in results
            ),
        )


class FakeChatStore:
    def __init__(self) -> None:
        self.messages: tuple[ChatMessage, ...] = ()

    def load_chat(self, chat_id: uuid.UUID) -> ChatThread:
        return ChatThread(
            chat_id=chat_id,
            started_at_us=1,
            ended_at_us=None,
            archive_mode="archive",
            lifecycle_state="active",
            messages=self.messages,
        )


class FakeChatGeneration:
    def __init__(self, *, loaded_context_length: int = 4096) -> None:
        self.calls: list[dict[str, object]] = []
        self.chat = FakeChatStore()
        self.model = ModelInfo(
            provider="lm_studio",
            backend_model_id="primary",
            display_name="primary",
            model_type="llm",
            context_capacity=32768,
            quantization=None,
            loaded=True,
            vision=False,
            trained_for_tool_use=False,
            loaded_context_length=loaded_context_length,
        )

    def select_model(self, requested_model_id: str | None = None) -> ModelInfo:
        if requested_model_id not in {None, self.model.backend_model_id}:
            raise ValueError("unknown model")
        return self.model

    def send_message(
        self,
        *,
        chat_id: uuid.UUID,
        content: str,
        requested_model_id: str | None = None,
        on_delta: Callable[[str], None] | None = None,
        retrieved_context: str | None = None,
        grounding_contract: GroundingContract | None = None,
        max_output_tokens: int | None = None,
        reasoning_mode: str | None = None,
    ) -> ChatGenerationResult:
        self.calls.append(
            {
                "chat_id": chat_id,
                "content": content,
                "requested_model_id": requested_model_id,
                "retrieved_context": retrieved_context,
                "grounding_contract": grounding_contract,
                "max_output_tokens": max_output_tokens,
                "reasoning_mode": reasoning_mode,
            }
        )
        user = ChatMessage(
            message_id=uuid.uuid4(),
            chat_id=chat_id,
            sequence_no=1,
            message_type=MessageType.USER,
            actor_id=None,
            created_at_us=1,
            revision_id=uuid.uuid4(),
            content=content,
            content_format="text/plain",
        )
        assistant = ChatMessage(
            message_id=uuid.uuid4(),
            chat_id=chat_id,
            sequence_no=2,
            message_type=MessageType.ASSISTANT,
            actor_id=None,
            created_at_us=2,
            revision_id=uuid.uuid4(),
            content="answer",
            content_format="text/plain",
        )
        return ChatGenerationResult(
            user_message=user,
            assistant_message=assistant,
            model=self.model,
        )


class FakePersonalMemory:
    def __init__(self, snapshots: tuple[PersonalMemorySnapshot, ...] = ()) -> None:
        self.snapshots = snapshots
        self.calls: list[tuple[MemoryScopeKind | None, uuid.UUID | None, int]] = []

    def context_candidates(
        self,
        *,
        scope_kind: MemoryScopeKind | None = None,
        scope_entity_id: uuid.UUID | None = None,
        limit: int = 32,
    ) -> tuple[PersonalMemorySnapshot, ...]:
        self.calls.append((scope_kind, scope_entity_id, limit))
        return self.snapshots


def _memory(content: str) -> PersonalMemorySnapshot:
    memory_id = uuid.uuid4()
    return PersonalMemorySnapshot(
        memory_id=memory_id,
        lifecycle_state="active",
        revision=PersonalMemoryRevision(
            memory_id=memory_id,
            revision_id=uuid.uuid4(),
            revision_no=1,
            created_at_us=1,
            created_by_actor_id=uuid.uuid4(),
            provenance_id=uuid.uuid4(),
            payload=PersonalMemoryDraft(
                memory_kind=MemoryKind.RESPONSE_STYLE,
                content=content,
                scope_kind=MemoryScopeKind.GLOBAL,
                learning_mode=MemoryLearningMode.EXPLICIT_USER,
                sensitivity=MemorySensitivity.NORMAL,
                last_confirmed_at_us=1,
            ),
        ),
    )


def _service(
    generation: FakeChatGeneration,
    hybrid: FakeHybrid,
    memory: FakePersonalMemory | None = None,
):
    return MemoryAugmentedChatService(
        chat_generation=generation,  # type: ignore[arg-type]
        embedding_provider=FakeEmbeddingProvider(),  # type: ignore[arg-type]
        hybrid_retrieval=hybrid,  # type: ignore[arg-type]
        context_builder=ContextBuilderService(),
        evidence_policy=FakeEvidencePolicy(),  # type: ignore[arg-type]
        personal_memory=memory or FakePersonalMemory(),  # type: ignore[arg-type]
    )


def test_memory_chat_retrieves_and_passes_typed_bounded_ephemeral_context() -> None:
    generation = FakeChatGeneration()
    hybrid = FakeHybrid()
    service = _service(generation, hybrid)

    result = service.send_message(
        chat_id=uuid.uuid4(),
        content="Was ist die Hauptstadt Deutschlands?",
        requested_model_id="primary",
        requested_embedding_model_id="embed",
        max_context_tokens=800,
        max_context_items=4,
        output_reserve=1000,
        safety_margin=200,
    )

    assert hybrid.queries == ["Was ist die Hauptstadt Deutschlands?"]
    assert result.embedding_model.backend_model_id == "embed"
    assert result.evidence_selection.policy_id == "typed-provenance-v1"
    assert len(result.context.items) == 1
    assert result.budget.effective_context_limit == 4096
    assert result.budget.estimated_total_tokens <= 4096
    passed_context = generation.calls[0]["retrieved_context"]
    assert isinstance(passed_context, str)
    assert '"entity_id"' in passed_context
    assert '"contradiction_count": 1' in passed_context
    assert "Berlin ist die Hauptstadt von Deutschland." in passed_context
    contract = generation.calls[0]["grounding_contract"]
    assert isinstance(contract, GroundingContract)
    assert contract.allowed_context_ids == ("CTX-001",)
    assert contract.evidence_refs[0].entity_type == "knowledge"
    assert contract.evidence_refs[0].evidence_class is EvidenceClass.CANONICAL
    assert contract.evidence_refs[0].entity_id == result.context.items[0].entity_id
    assert contract.evidence_refs[0].revision_id == result.context.items[0].revision_id
    assert contract.allow_model_prior is True
    assert generation.calls[0]["requested_model_id"] == "primary"
    assert generation.calls[0]["max_output_tokens"] == 1000
    assert generation.calls[0]["reasoning_mode"] == "off"


def test_memory_chat_includes_personal_memory_as_user_preference() -> None:
    generation = FakeChatGeneration()
    hybrid = FakeHybrid()
    memory = FakePersonalMemory((_memory("Antworte kurz."),))
    service = _service(generation, hybrid, memory)

    result = service.send_message(
        chat_id=uuid.uuid4(),
        content="Antworte diesmal ausführlich.",
        output_reserve=1000,
        safety_margin=200,
    )

    payload = json.loads(result.context.rendered_text)
    assert payload["user_preferences"][0]["label"] == "USER PREFERENCE"
    assert payload["user_preferences"][0]["content"] == "Antworte kurz."
    assert payload["query"] == "Antworte diesmal ausführlich."
    assert "overrides USER PREFERENCE" in payload["policy"]


def test_memory_chat_forwards_exact_personal_memory_scope() -> None:
    generation = FakeChatGeneration()
    hybrid = FakeHybrid()
    memory = FakePersonalMemory()
    service = _service(generation, hybrid, memory)
    project_id = uuid.uuid4()

    service.send_message(
        chat_id=uuid.uuid4(),
        content="test",
        memory_scope_kind=MemoryScopeKind.PROJECT,
        memory_scope_entity_id=project_id,
        output_reserve=1000,
        safety_margin=200,
    )

    assert memory.calls[0][:2] == (MemoryScopeKind.PROJECT, project_id)


def test_memory_chat_can_explicitly_disable_model_prior() -> None:
    generation = FakeChatGeneration()
    hybrid = FakeHybrid()
    service = _service(generation, hybrid)

    service.send_message(
        chat_id=uuid.uuid4(),
        content="test",
        allow_model_prior=False,
        output_reserve=1000,
        safety_margin=200,
    )

    contract = generation.calls[0]["grounding_contract"]
    assert isinstance(contract, GroundingContract)
    assert contract.allow_model_prior is False


def test_memory_chat_rejects_invalid_budget_before_retrieval() -> None:
    generation = FakeChatGeneration()
    hybrid = FakeHybrid()
    service = _service(generation, hybrid)

    with pytest.raises(ValueError, match="Context token budget"):
        service.send_message(
            chat_id=uuid.uuid4(),
            content="test",
            max_context_tokens=50,
        )

    assert hybrid.queries == []
    assert generation.calls == []


def test_memory_chat_rejects_request_above_loaded_context_before_retrieval() -> None:
    generation = FakeChatGeneration(loaded_context_length=2048)
    hybrid = FakeHybrid()
    service = _service(generation, hybrid)

    with pytest.raises(ValueError, match="currently loaded LM Studio context"):
        service.send_message(
            chat_id=uuid.uuid4(),
            content="test",
            effective_context_limit=4096,
        )

    assert hybrid.queries == []
    assert generation.calls == []


def test_memory_chat_fails_closed_when_fixed_input_leaves_no_context_room() -> None:
    generation = FakeChatGeneration(loaded_context_length=1200)
    hybrid = FakeHybrid()
    service = _service(generation, hybrid)

    with pytest.raises(ValueError, match="insufficient room"):
        service.send_message(
            chat_id=uuid.uuid4(),
            content="lange aktuelle Anweisung " * 100,
            output_reserve=700,
            safety_margin=200,
        )

    assert hybrid.queries == []
    assert generation.calls == []
