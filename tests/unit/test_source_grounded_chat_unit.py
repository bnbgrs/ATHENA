from __future__ import annotations

import hashlib
import uuid
from collections.abc import Callable

import pytest

from athena.chat.generation import ChatGenerationResult
from athena.chat.grounding import GroundingContract
from athena.chat.models import ChatMessage, MessageType
from athena.chat.source_grounding import SourceGroundedChatService
from athena.model.domain import ModelInfo
from athena.retrieval.archive import ArchiveHybridSearchResult
from athena.retrieval.evidence import EvidenceClass
from athena.retrieval.source_context import SourceContextBuilderService
from athena.source.models import SourceAnchorRecord, SourceAnchorType


class FakeEmbeddingProvider:
    def __init__(self) -> None:
        self.requests: list[str | None] = []

    def resolve_model(self, requested_model_id: str | None = None) -> ModelInfo:
        self.requests.append(requested_model_id)
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


class FakeArchiveRetrieval:
    def __init__(self, result: ArchiveHybridSearchResult) -> None:
        self.result = result
        self.calls: list[tuple[str, str, int]] = []

    def search(self, query: str, *, model_id: str, limit: int):
        self.calls.append((query, model_id, limit))
        return (self.result,)


class FakeAnchors:
    def __init__(self, result: ArchiveHybridSearchResult) -> None:
        self.result = result
        self.calls: list[tuple[uuid.UUID, int, int]] = []
        self.anchor_id = uuid.uuid4()

    def materialize_text_range(
        self,
        representation_id: uuid.UUID,
        *,
        start_offset: int,
        end_offset: int,
    ) -> SourceAnchorRecord:
        self.calls.append((representation_id, start_offset, end_offset))
        text = self.result.text[
            start_offset - self.result.start_anchor_value :
            end_offset - self.result.start_anchor_value
        ]
        return SourceAnchorRecord(
            anchor_id=self.anchor_id,
            source_id=self.result.source_id,
            representation_id=representation_id,
            anchor_type=SourceAnchorType.TEXT_RANGE,
            start_offset=start_offset,
            end_offset=end_offset,
            page_start=None,
            page_end=None,
            start_time_ms=None,
            end_time_ms=None,
            geometry_json=None,
            quoted_hash=hashlib.sha256(text.encode("utf-8")).digest(),
            created_at_us=1,
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
        return ChatGenerationResult(user_message=user, assistant_message=assistant, model=model)


def _archive_result() -> ArchiveHybridSearchResult:
    text = "Berlin appears in this imported source."
    return ArchiveHybridSearchResult(
        chunk_id=uuid.uuid4(),
        source_id=uuid.uuid4(),
        representation_id=uuid.uuid4(),
        chunk_index=0,
        chunking_profile_id=uuid.uuid4(),
        start_anchor_value=0,
        end_anchor_value=len(text),
        content_hash=hashlib.sha256(text.encode("utf-8")).digest(),
        build_signature=b"b" * 32,
        source_name="source.txt",
        source_uri="file:///source.txt",
        text=text,
        score=0.95,
        lexical_score=0.9,
        semantic_score=1.0,
    )


def test_source_grounded_chat_uses_persistent_anchor_identity_not_chunk_identity() -> None:
    archive_result = _archive_result()
    anchors = FakeAnchors(archive_result)
    context_builder = SourceContextBuilderService(anchors)  # type: ignore[arg-type]
    embedding = FakeEmbeddingProvider()
    retrieval = FakeArchiveRetrieval(archive_result)
    generation = FakeChatGeneration()
    service = SourceGroundedChatService(
        chat_generation=generation,  # type: ignore[arg-type]
        embedding_provider=embedding,  # type: ignore[arg-type]
        archive_retrieval=retrieval,  # type: ignore[arg-type]
        context_builder=context_builder,
    )

    result = service.send_message(
        chat_id=uuid.uuid4(),
        content="What does my source say about Berlin?",
        requested_model_id="primary",
        requested_embedding_model_id="embed-model",
    )

    assert embedding.requests == ["embed-model"]
    assert retrieval.calls[0][0] == "What does my source say about Berlin?"
    assert retrieval.calls[0][1] == "embed-model"
    assert len(result.context.items) == 1
    context_item = result.context.items[0]
    assert context_item.anchor_id == anchors.anchor_id
    assert str(archive_result.chunk_id) not in result.context.rendered_text
    assert "chunk_id" not in result.context.rendered_text

    call = generation.calls[0]
    contract = call["grounding_contract"]
    assert isinstance(contract, GroundingContract)
    assert contract.allowed_context_ids == ("CTX-001",)
    evidence = contract.evidence_refs[0]
    assert evidence.evidence_class is EvidenceClass.SOURCE
    assert evidence.entity_type == "source_anchor"
    assert evidence.entity_id == anchors.anchor_id
    assert evidence.revision_id is None
    assert evidence.source_id == archive_result.source_id
    assert evidence.representation_id == archive_result.representation_id
    assert evidence.quoted_hash == archive_result.content_hash
    assert evidence.entity_id != archive_result.chunk_id


def test_source_grounded_chat_rejects_invalid_budget_before_retrieval() -> None:
    archive_result = _archive_result()
    anchors = FakeAnchors(archive_result)
    embedding = FakeEmbeddingProvider()
    retrieval = FakeArchiveRetrieval(archive_result)
    generation = FakeChatGeneration()
    service = SourceGroundedChatService(
        chat_generation=generation,  # type: ignore[arg-type]
        embedding_provider=embedding,  # type: ignore[arg-type]
        archive_retrieval=retrieval,  # type: ignore[arg-type]
        context_builder=SourceContextBuilderService(anchors),  # type: ignore[arg-type]
    )

    with pytest.raises(ValueError, match="Context token budget"):
        service.send_message(
            chat_id=uuid.uuid4(),
            content="Berlin?",
            max_context_tokens=50,
        )

    assert embedding.requests == []
    assert retrieval.calls == []
    assert generation.calls == []


def test_source_grounded_cli_arguments_are_explicit_and_separate_from_memory() -> None:
    from athena.__main__ import build_parser

    chat_id = uuid.uuid4()
    args = build_parser().parse_args(
        [
            "chat",
            "send",
            str(chat_id),
            "Question",
            "--sources",
            "--embedding-model",
            "nomic",
            "--source-max-tokens",
            "2400",
            "--source-max-items",
            "12",
            "--source-no-model-prior",
        ]
    )

    assert args.sources is True
    assert args.memory is False
    assert args.embedding_model_id == "nomic"
    assert args.source_max_tokens == 2400
    assert args.source_max_items == 12
    assert args.source_allow_model_prior is False
