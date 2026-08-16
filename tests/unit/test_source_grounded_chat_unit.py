from __future__ import annotations

import hashlib
import json
import uuid
from collections.abc import Iterator, Sequence

import pytest

from athena.chat.generation import ChatGenerationService
from athena.chat.repository import ChatRepository
from athena.chat.service import ChatService
from athena.chat.source_grounding import SourceGroundedChatService
from athena.model.domain import (
    ModelChatMessage,
    ModelInfo,
    ProviderHealth,
    ProviderHealthStatus,
)
from athena.model.provenance import ModelRunRepository
from athena.retrieval.archive import ArchiveHybridSearchResult
from athena.retrieval.context_package import ContextPackageService
from athena.retrieval.degradation import SemanticRetrievalUnavailableError
from athena.retrieval.source_context import SourceContextBuilderService
from athena.source.models import SourceAnchorRecord, SourceAnchorType
from athena.storage.database import SQLiteDatabase


class FakeProvider:
    provider_id = "lm_studio"

    def __init__(self) -> None:
        self.requests: list[tuple[ModelChatMessage, ...]] = []

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
        assert model_id == "primary"
        assert max_output_tokens == 1000
        assert reasoning_mode == "off"
        self.requests.append(tuple(messages))
        yield "The source mentions Berlin. [SOURCE:CTX-001]"


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
            context_capacity=2048,
            quantization=None,
            loaded=True,
            vision=False,
            trained_for_tool_use=False,
            loaded_context_length=2048,
        )


class FakeArchiveRetrieval:
    def __init__(
        self,
        result: ArchiveHybridSearchResult,
        *,
        fail_semantic: bool = False,
    ) -> None:
        self.result = result
        self.fail_semantic = fail_semantic
        self.calls: list[tuple[str, str, int]] = []
        self.lexical_calls: list[tuple[str, int]] = []

    def search(self, query: str, *, model_id: str, limit: int):
        self.calls.append((query, model_id, limit))
        if self.fail_semantic:
            raise SemanticRetrievalUnavailableError(
                "archive_semantic_unavailable"
            )
        return (self.result,)

    def search_lexical(self, query: str, *, limit: int):
        self.lexical_calls.append((query, limit))
        return (self.result,)


class FakeAnchors:
    def __init__(self, result: ArchiveHybridSearchResult) -> None:
        self.result = result
        self.calls: list[tuple[uuid.UUID, int, int]] = []
        self.anchor_id = uuid.uuid4()
        self.record: SourceAnchorRecord | None = None
        self.text = ""

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
        self.text = text
        self.record = SourceAnchorRecord(
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
        return self.record

    def verify(self, anchor_id: uuid.UUID) -> SourceAnchorRecord:
        assert anchor_id == self.anchor_id
        assert self.record is not None
        return self.record

    def read_text(self, anchor_id: uuid.UUID) -> str:
        assert anchor_id == self.anchor_id
        return self.text


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


def _runtime(
    tmp_path,
    archive_result: ArchiveHybridSearchResult,
    *,
    semantic_fail: bool = False,
):
    database = SQLiteDatabase(tmp_path / "athena.db")
    database.start()
    chat = ChatService(ChatRepository(database))
    provider = FakeProvider()
    anchors = FakeAnchors(archive_result)
    embedding = FakeEmbeddingProvider()
    retrieval = FakeArchiveRetrieval(
        archive_result,
        fail_semantic=semantic_fail,
    )
    runs = ModelRunRepository(database)
    service = SourceGroundedChatService(
        chat_generation=ChatGenerationService(chat, provider),
        embedding_provider=embedding,  # type: ignore[arg-type]
        archive_retrieval=retrieval,  # type: ignore[arg-type]
        context_builder=SourceContextBuilderService(anchors),  # type: ignore[arg-type]
        context_packages=ContextPackageService(database),
        model_runs=runs,
    )
    return database, chat, provider, anchors, embedding, retrieval, service


def test_source_grounded_chat_uses_persistent_anchor_identity_not_chunk_identity(tmp_path) -> None:
    archive_result = _archive_result()
    (
        database,
        chat,
        provider,
        anchors,
        embedding,
        retrieval,
        service,
    ) = _runtime(tmp_path, archive_result)
    try:
        chat_id = chat.create_chat()
        result = service.send_message(
            chat_id=chat_id,
            content="What does my source say about Berlin?",
            requested_model_id="primary",
            requested_embedding_model_id="embed-model",
            output_reserve=1000,
            safety_margin=100,
        )

        assert embedding.requests == ["embed-model"]
        assert retrieval.calls[0][0] == "What does my source say about Berlin?"
        assert retrieval.calls[0][1] == "embed-model"
        assert len(result.context.items) == 1
        context_item = result.context.items[0]
        assert context_item.anchor_id == anchors.anchor_id
        assert str(archive_result.chunk_id) not in result.context.rendered_text
        assert "chunk_id" not in result.context.rendered_text

        contract = result.generation.grounding_report
        assert contract is not None
        assert contract.source_context_ids == ("CTX-001",)

        refs = result.context_package.included_refs
        source_ref = next(item for item in refs if item.ref_id == "CTX-001")
        assert source_ref.entity_type == "source_anchor"
        assert source_ref.entity_id == anchors.anchor_id
        assert source_ref.revision_id is None
        assert source_ref.entity_id != archive_result.chunk_id

        assert provider.requests
        assert tuple(
            (item.role, item.content)
            for item in provider.requests[0]
        ) == tuple(
            (item.role, item.content)
            for item in result.context_package.model_messages()
        )
        assert result.processing_run.status == "succeeded"
    finally:
        database.stop()


def test_source_chat_retrieval_override_preserves_current_user_semantics(tmp_path) -> None:
    archive_result = _archive_result()

    (
        database,
        chat,
        _provider,
        _anchors,
        _embedding,
        retrieval,
        service,
    ) = _runtime(
        tmp_path,
        archive_result,
    )

    try:
        chat_id = chat.create_chat()

        retrieval_query = (
            "What does my imported source say about Berlin?\n"
            "And why?"
        )

        result = service.send_message(
            chat_id=chat_id,
            content="And why?",
            retrieval_query=retrieval_query,
            requested_model_id="primary",
            requested_embedding_model_id="embed-model",
            output_reserve=1000,
            safety_margin=100,
        )

        assert (
            retrieval.calls[0][0]
            == retrieval_query
        )

        # SourceContext presented to the model retains the real user query.
        assert result.context.query == "And why?"
        assert (
            result.generation.user_message.content
            == "And why?"
        )

        run_snapshot = json.loads(
            result.processing_run.input_snapshot_json
        )

        assert (
            run_snapshot["retrieval_query_override"]
            == retrieval_query
        )

    finally:
        database.stop()


def test_source_grounded_chat_rejects_invalid_budget_before_retrieval(tmp_path) -> None:
    archive_result = _archive_result()
    database, chat, _provider, _anchors, embedding, retrieval, service = _runtime(
        tmp_path, archive_result
    )
    try:
        chat_id = chat.create_chat()
        with pytest.raises(ValueError, match="Context token budget"):
            service.send_message(
                chat_id=chat_id,
                content="Berlin?",
                max_context_tokens=50,
            )
        assert embedding.requests == []
        assert retrieval.calls == []
    finally:
        database.stop()


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


def test_source_chat_uses_verified_lexical_fallback_on_semantic_outage(
    tmp_path,
) -> None:
    archive_result = _archive_result()
    (
        database,
        chat,
        _provider,
        _anchors,
        _embedding,
        retrieval,
        service,
    ) = _runtime(
        tmp_path,
        archive_result,
        semantic_fail=True,
    )

    try:
        chat_id = chat.create_chat()
        result = service.send_message(
            chat_id=chat_id,
            content="What code is assigned to Project Borealis?",
            requested_model_id="primary",
            requested_embedding_model_id="embed-model",
            output_reserve=1000,
            safety_margin=100,
        )

        assert len(retrieval.calls) == 1
        assert len(retrieval.lexical_calls) == 1
        assert len(result.context.items) == 1
        assert result.embedding_model is not None
        assert result.embedding_model.backend_model_id == "embed-model"

        configuration = json.loads(
            result.context_package.model_signature.context_configuration_json
            or "{}"
        )
        assert configuration["retrieval_mode"] == "lexical_fallback"
        assert (
            configuration["retrieval_warning"]
            == "archive_semantic_unavailable"
        )
        assert configuration["embedding_model_id"] == "embed-model"
    finally:
        database.stop()
