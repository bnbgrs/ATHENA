from __future__ import annotations

import uuid
from collections.abc import Callable

from athena.chat.generation import ChatGenerationResult
from athena.chat.grounding import GroundingContract
from athena.chat.memory import MemoryAugmentedChatService
from athena.chat.models import ChatMessage, MessageType
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


class FakeChatGeneration:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    def send_message(
        self,
        *,
        chat_id: uuid.UUID,
        content: str,
        requested_model_id: str | None = None,
        on_delta: Callable[[str], None] | None = None,
        retrieved_context: str | None = None,
        grounding_contract: GroundingContract | None = None,
    ) -> ChatGenerationResult:
        self.calls.append(
            {
                "chat_id": chat_id,
                "content": content,
                "requested_model_id": requested_model_id,
                "retrieved_context": retrieved_context,
                "grounding_contract": grounding_contract,
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
        model = ModelInfo(
            provider="lm_studio",
            backend_model_id="primary",
            display_name="primary",
            model_type="llm",
            context_capacity=32768,
            quantization=None,
            loaded=True,
            vision=False,
            trained_for_tool_use=False,
        )
        return ChatGenerationResult(
            user_message=user,
            assistant_message=assistant,
            model=model,
        )


def _service(generation: FakeChatGeneration, hybrid: FakeHybrid):
    return MemoryAugmentedChatService(
        chat_generation=generation,  # type: ignore[arg-type]
        embedding_provider=FakeEmbeddingProvider(),  # type: ignore[arg-type]
        hybrid_retrieval=hybrid,  # type: ignore[arg-type]
        context_builder=ContextBuilderService(),
        evidence_policy=FakeEvidencePolicy(),  # type: ignore[arg-type]
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
    )

    assert hybrid.queries == ["Was ist die Hauptstadt Deutschlands?"]
    assert result.embedding_model.backend_model_id == "embed"
    assert result.evidence_selection.policy_id == "typed-provenance-v1"
    assert len(result.context.items) == 1
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


def test_memory_chat_can_explicitly_disable_model_prior() -> None:
    generation = FakeChatGeneration()
    hybrid = FakeHybrid()
    service = _service(generation, hybrid)

    service.send_message(
        chat_id=uuid.uuid4(),
        content="test",
        allow_model_prior=False,
    )

    contract = generation.calls[0]["grounding_contract"]
    assert isinstance(contract, GroundingContract)
    assert contract.allow_model_prior is False


def test_memory_chat_rejects_invalid_budget_before_retrieval() -> None:
    import pytest

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
