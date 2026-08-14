from __future__ import annotations

from collections.abc import Iterator, Sequence
from pathlib import Path

from athena.chat.generation import ChatGenerationService
from athena.chat.source_grounding import SourceGroundedChatService
from athena.config.settings import AthenaSettings
from athena.core.application import AthenaApplication
from athena.model.domain import (
    ModelChatMessage,
    ModelInfo,
    ProviderHealth,
    ProviderHealthStatus,
)
from athena.retrieval.archive import (
    ArchiveHybridRetrievalService,
    ArchiveSemanticSearchService,
)
from athena.retrieval.source_context import SourceContextBuilderService


class FakeEmbeddingProvider:
    def resolve_model(self, requested_model_id: str | None = None) -> ModelInfo:
        return ModelInfo(
            provider="lm_studio",
            backend_model_id=requested_model_id or "fake-embed",
            display_name="fake-embed",
            model_type="embedding",
            context_capacity=None,
            quantization=None,
            loaded=True,
            vision=None,
            trained_for_tool_use=None,
        )

    def embed(self, *, model_id: str, texts):
        vectors = []
        for text in texts:
            lowered = text.casefold()
            vectors.append(
                (
                    1.0 if "berlin" in lowered else 0.0,
                    1.0 if "source" in lowered or "quelle" in lowered else 0.0,
                    0.25,
                )
            )
        return tuple(vectors)


class ScriptedProvider:
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
                backend_model_id="primary",
                display_name="primary",
                model_type="llm",
                context_capacity=32768,
                quantization=None,
                loaded=True,
                vision=False,
                loaded_context_length=32768,
                trained_for_tool_use=False,
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
        self.requests.append((model_id, tuple(messages)))
        yield self.answer


def _started_app(tmp_path: Path) -> AthenaApplication:
    app = AthenaApplication(settings=AthenaSettings(local_root=tmp_path / "local"))
    app.start()
    return app


def test_source_grounded_chat_persists_anchor_and_survives_rechunk_restart(tmp_path) -> None:
    app = _started_app(tmp_path)
    original = tmp_path / "source-grounded.md"
    original.write_text(
        "ATHENA source grounding E2E.\nBerlin appears in this imported source.\n",
        encoding="utf-8",
        newline="",
    )
    captured = app.sources.capture_file(original)
    represented = app.source_text.build(captured.source.source_id)
    representation_id = represented.result.representation.representation_id
    first_build = app.source_chunks.build_default(representation_id)
    first_chunk_ids = {chunk.chunk_id for chunk in first_build.chunks}

    embedding = FakeEmbeddingProvider()
    semantic = ArchiveSemanticSearchService(
        lexical=app.archive_search,
        provider=embedding,  # type: ignore[arg-type]
    )
    archive = ArchiveHybridRetrievalService(app.archive_search, semantic)
    scripted = ScriptedProvider(
        "The imported source explicitly mentions Berlin. [SOURCE:CTX-001]"
    )
    generation = ChatGenerationService(app.chat, scripted)  # type: ignore[arg-type]
    source_chat = SourceGroundedChatService(
        chat_generation=generation,
        embedding_provider=embedding,  # type: ignore[arg-type]
        archive_retrieval=archive,
        context_builder=SourceContextBuilderService(app.source_anchors),
        context_packages=app.context_packages,
        model_runs=app.model_runs,
    )
    chat_id = app.chat.create_chat()

    result = source_chat.send_message(
        chat_id=chat_id,
        content="What does my imported source say about Berlin?",
        requested_embedding_model_id="fake-embed",
        allow_model_prior=False,
    )

    assert len(result.context.items) == 1
    context_item = result.context.items[0]
    anchor_id = context_item.anchor_id
    assert context_item.source_id == captured.source.source_id
    assert context_item.representation_id == representation_id
    assert app.source_anchors.verify(anchor_id).anchor_id == anchor_id
    assert all(str(chunk_id) not in result.context.rendered_text for chunk_id in first_chunk_ids)
    assert "chunk_id" not in result.context.rendered_text

    assistant_content = result.generation.assistant_message.content or ""
    assert "[SOURCE:CTX-001]" in assistant_content
    assert f'"anchor_id":"{anchor_id}"' in assistant_content
    assert f'"source_id":"{captured.source.source_id}"' in assistant_content
    assert f'"representation_id":"{representation_id}"' in assistant_content
    assert "chunk_id" not in assistant_content

    second_build = app.source_chunks.build_default(representation_id)
    second_chunk_ids = {chunk.chunk_id for chunk in second_build.chunks}
    assert first_chunk_ids.isdisjoint(second_chunk_ids)
    assert app.source_anchors.verify(anchor_id).anchor_id == anchor_id
    app.stop()

    restarted = _started_app(tmp_path)
    try:
        assert restarted.source_anchors.verify(anchor_id).anchor_id == anchor_id
        assert restarted.source_anchors.read_text(anchor_id) == context_item.text
        persisted = restarted.chat.load_chat(chat_id)
        persisted_answer = persisted.messages[-1].content or ""
        assert f'"anchor_id":"{anchor_id}"' in persisted_answer
        assert "chunk_id" not in persisted_answer
    finally:
        restarted.stop()
