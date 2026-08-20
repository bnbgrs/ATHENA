from __future__ import annotations

import hashlib
import json
import uuid
from collections.abc import Callable
from dataclasses import replace

from athena.chat.generation import ChatGenerationResult
from athena.chat.grounding import GroundingContract
from athena.chat.models import ChatMessage, ChatThread, MessageType
from athena.chat.unified import UnifiedLocalChatService
from athena.knowledge.models import EpistemicStatus
from athena.model.adapters.lm_studio import ModelProviderError
from athena.model.domain import ModelInfo
from athena.model.provenance import ModelSignature, ProcessingRun
from athena.retrieval.archive import ArchiveHybridSearchResult
from athena.retrieval.context import ContextBuilderService, estimate_tokens
from athena.retrieval.context_package import ContextPackageService
from athena.retrieval.evidence import (
    EvidenceClass,
    MemoryEvidenceClassification,
    MemoryEvidenceSelection,
)
from athena.retrieval.hybrid import HybridSearchResult
from athena.retrieval.search import SearchEntityType
from athena.retrieval.source_context import (
    SourceContextBuilderService,
    SourceContextIntegrityError,
    _render_source_context,
)
from athena.source.models import SourceAnchorRecord, SourceAnchorType


class FakeEmbeddingProvider:
    def __init__(self, *, fail: bool = False) -> None:
        self.requests: list[str | None] = []
        self.fail = fail

    def resolve_model(self, requested_model_id: str | None = None) -> ModelInfo:
        self.requests.append(requested_model_id)
        if self.fail:
            raise ModelProviderError(
                "synthetic embedding discovery failure"
            )
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


class FakeMemoryHybrid:
    def __init__(self) -> None:
        self.calls: list[
            tuple[
                str,
                str,
                int,
                SearchEntityType | None,
            ]
        ] = []
        self.lexical_calls: list[
            tuple[
                str,
                int,
                SearchEntityType | None,
            ]
        ] = []

        self.knowledge_result = HybridSearchResult(
            entity_id=uuid.uuid4(),
            revision_id=uuid.uuid4(),
            entity_type=SearchEntityType.KNOWLEDGE,
            title="Stored capital",
            text="Berlin ist die Hauptstadt von Deutschland.",
            score=0.98,
            lexical_score=0.9,
            semantic_score=1.0,
            authority_score=1.0,
            contradiction_count=1,
            duplicate_count=0,
        )

        # Same semantic statement as the KnowledgeUnit. The Unified canonical
        # merge must retain one representative rather than spending bounded
        # context on a duplicate Claim.
        self.duplicate_claim = HybridSearchResult(
            entity_id=uuid.uuid4(),
            revision_id=uuid.uuid4(),
            entity_type=SearchEntityType.CLAIM,
            title=None,
            text="Berlin ist die Hauptstadt von Deutschland!",
            score=0.94,
            lexical_score=0.8,
            semantic_score=0.9,
            authority_score=0.88,
            contradiction_count=1,
            duplicate_count=0,
        )

        self.irrelevant_chat = HybridSearchResult(
            entity_id=uuid.uuid4(),
            revision_id=uuid.uuid4(),
            entity_type=SearchEntityType.CHAT_MESSAGE,
            title="Old chat",
            text="Antworte genau mit: ATHENA End-to-End-Test erfolgreich.",
            score=1.0,
            lexical_score=1.0,
            semantic_score=1.0,
            authority_score=0.68,
            contradiction_count=0,
            duplicate_count=0,
        )

    def search(
        self,
        query: str,
        *,
        model_id: str,
        limit: int,
        entity_type: SearchEntityType | None = None,
    ):
        self.calls.append(
            (
                query,
                model_id,
                limit,
                entity_type,
            )
        )

        if entity_type is SearchEntityType.KNOWLEDGE:
            return (self.knowledge_result,)

        if entity_type is SearchEntityType.CLAIM:
            return (self.duplicate_claim,)

        # This branch exists specifically to catch a regression back to an
        # untyped Unified query: the irrelevant chat record would outrank the
        # canonical fixture.
        return (
            self.irrelevant_chat,
            self.knowledge_result,
            self.duplicate_claim,
        )

    def search_lexical(
        self,
        query: str,
        *,
        limit: int,
        entity_type: SearchEntityType | None = None,
    ):
        self.lexical_calls.append(
            (
                query,
                limit,
                entity_type,
            )
        )

        if entity_type is SearchEntityType.KNOWLEDGE:
            return (self.knowledge_result,)

        if entity_type is SearchEntityType.CLAIM:
            return (self.duplicate_claim,)

        return (
            self.irrelevant_chat,
            self.knowledge_result,
            self.duplicate_claim,
        )


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
                    epistemic_status=EpistemicStatus.ASSERTED,
                )
                for item in results
            ),
        )


class FakePersonalMemory:
    def context_candidates(
        self,
        *,
        scope_kind=None,
        scope_entity_id=None,
        limit: int = 32,
    ):
        del scope_kind, scope_entity_id, limit
        return ()


def archive_result() -> ArchiveHybridSearchResult:
    text = "The imported archive says Berlin has a major central station."
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
        source_name="berlin.txt",
        source_uri="file:///berlin.txt",
        text=text,
        score=0.95,
        lexical_score=0.9,
        semantic_score=1.0,
    )


class FakeArchiveRetrieval:
    def __init__(self, result: ArchiveHybridSearchResult) -> None:
        self.result = result
        self.calls: list[tuple[str, str, int]] = []
        self.lexical_calls: list[tuple[str, int]] = []

    def search(self, query: str, *, model_id: str, limit: int):
        self.calls.append((query, model_id, limit))
        return (self.result,)

    def search_lexical(self, query: str, *, limit: int):
        self.lexical_calls.append((query, limit))
        return (self.result,)


class FakeAnchors:
    def __init__(self, result: ArchiveHybridSearchResult) -> None:
        self.result = result
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

    def add_user_message(
        self,
        *,
        chat_id: uuid.UUID,
        content: str,
    ) -> ChatMessage:
        message = ChatMessage(
            message_id=uuid.uuid4(),
            chat_id=chat_id,
            sequence_no=len(self.messages) + 1,
            message_type=MessageType.USER,
            actor_id=uuid.uuid4(),
            created_at_us=1,
            revision_id=uuid.uuid4(),
            content=content,
            content_format="text/plain",
        )
        self.messages = (*self.messages, message)
        return message


class FakeContextPackages:
    def __init__(self) -> None:
        self.current = 40
        self.phases: list[str] = []

    def current_commit_seq(self) -> int:
        return self.current

    def assert_snapshot_current(
        self,
        expected_commit_seq: int,
        *,
        phase: str,
    ) -> None:
        assert expected_commit_seq == self.current
        self.phases.append(phase)

    def assert_user_commit_follows(
        self,
        previous_commit_seq: int,
        user_message: ChatMessage,
    ) -> int:
        assert previous_commit_seq == self.current
        assert user_message.message_type is MessageType.USER
        self.current += 1
        return self.current

    def build_from_sections(self, **kwargs):
        return ContextPackageService.build_from_sections(**kwargs)


class FakeModelRuns:
    def __init__(self) -> None:
        self.runs: dict[uuid.UUID, ProcessingRun] = {}

    def get_or_create_signature(
        self,
        *,
        model: ModelInfo,
        generation_parameters,
        context_configuration=None,
    ) -> ModelSignature:
        return ModelSignature(
            model_signature_id=uuid.uuid4(),
            provider=model.provider,
            model_identifier=model.backend_model_id,
            model_revision=None,
            quantization=model.quantization,
            generation_parameters_json=json.dumps(
                generation_parameters,
                sort_keys=True,
                separators=(",", ":"),
            ),
            context_configuration_json=(
                json.dumps(
                    context_configuration,
                    sort_keys=True,
                    separators=(",", ":"),
                )
                if context_configuration is not None
                else None
            ),
            signature_hash=b"s" * 32,
            created_at_us=1,
        )

    def start_run(
        self,
        *,
        run_type: str,
        trigger_actor_id: uuid.UUID,
        pipeline_version: str,
        input_snapshot,
        configuration,
        model_signature_id: uuid.UUID | None,
        prompt_template_id: str | None,
        prompt_template_version: str | None,
    ) -> ProcessingRun:
        run = ProcessingRun(
            processing_run_id=uuid.uuid4(),
            run_type=run_type,
            started_at_us=1,
            finished_at_us=None,
            status="running",
            trigger_actor_id=trigger_actor_id,
            pipeline_version=pipeline_version,
            input_snapshot_json=json.dumps(input_snapshot, sort_keys=True),
            configuration_hash=b"c" * 32,
            model_signature_id=model_signature_id,
            prompt_template_id=prompt_template_id,
            prompt_template_version=prompt_template_version,
            error_detail=None,
        )
        self.runs[run.processing_run_id] = run
        return run

    def finish_run(
        self,
        processing_run_id: uuid.UUID,
        *,
        status: str,
        error_detail: str | None = None,
    ) -> ProcessingRun:
        run = replace(
            self.runs[processing_run_id],
            finished_at_us=2,
            status=status,
            error_detail=error_detail,
        )
        self.runs[processing_run_id] = run
        return run


class FakeChatGeneration:
    def __init__(self) -> None:
        self.chat = FakeChatStore()
        self.calls: list[dict[str, object]] = []
        self.model = ModelInfo(
            provider="lm_studio",
            backend_model_id="primary",
            display_name="primary",
            model_type="llm",
            context_capacity=32768,
            quantization="Q4_K_S",
            loaded=True,
            vision=False,
            trained_for_tool_use=False,
            loaded_context_length=8192,
        )

    def select_model(self, requested_model_id: str | None = None) -> ModelInfo:
        assert requested_model_id in {None, "primary"}
        return self.model

    def send_context_package(
        self,
        *,
        chat_id: uuid.UUID,
        user_message: ChatMessage,
        context_package,
        on_delta: Callable[[str], None] | None = None,
        grounding_contract: GroundingContract | None = None,
        on_before_provider_call: Callable[[], None] | None = None,
    ) -> ChatGenerationResult:
        del on_delta

        if on_before_provider_call is not None:
            on_before_provider_call()

        self.calls.append(
            {
                "chat_id": chat_id,
                "user_message": user_message,
                "context_package": context_package,
                "grounding_contract": grounding_contract,
            }
        )

        assistant = ChatMessage(
            message_id=uuid.uuid4(),
            chat_id=chat_id,
            sequence_no=user_message.sequence_no + 1,
            message_type=MessageType.ASSISTANT,
            actor_id=None,
            created_at_us=2,
            revision_id=uuid.uuid4(),
            content="answer",
            content_format="text/plain",
        )
        return ChatGenerationResult(
            user_message=user_message,
            assistant_message=assistant,
            model=self.model,
        )


def test_unified_local_chat_composes_memory_and_source_evidence_once() -> None:
    source = archive_result()
    generation = FakeChatGeneration()
    embedding = FakeEmbeddingProvider()
    memory_hybrid = FakeMemoryHybrid()
    archive = FakeArchiveRetrieval(source)
    anchors = FakeAnchors(source)
    packages = FakeContextPackages()
    runs = FakeModelRuns()

    service = UnifiedLocalChatService(
        chat_generation=generation,  # type: ignore[arg-type]
        embedding_provider=embedding,  # type: ignore[arg-type]
        hybrid_retrieval=memory_hybrid,  # type: ignore[arg-type]
        memory_context_builder=ContextBuilderService(),
        evidence_policy=FakeEvidencePolicy(),  # type: ignore[arg-type]
        personal_memory=FakePersonalMemory(),  # type: ignore[arg-type]
        archive_retrieval=archive,  # type: ignore[arg-type]
        source_context_builder=SourceContextBuilderService(anchors),  # type: ignore[arg-type]
        context_packages=packages,  # type: ignore[arg-type]
        model_runs=runs,  # type: ignore[arg-type]
    )

    result = service.send_message(
        chat_id=uuid.uuid4(),
        content="Was wei\\u00df ATHENA lokal \\u00fcber Berlin?",
        requested_model_id="primary",
        requested_embedding_model_id="embed-model",
        max_memory_context_tokens=500,
        max_source_context_tokens=500,
        output_reserve=1000,
        safety_margin=100,
    )

    assert embedding.requests == ["embed-model"]
    assert len(memory_hybrid.calls) == 2
    assert {
        call[3]
        for call in memory_hybrid.calls
    } == {
        SearchEntityType.KNOWLEDGE,
        SearchEntityType.CLAIM,
    }
    assert all(
        call[3] is not None
        for call in memory_hybrid.calls
    )
    assert len(archive.calls) == 1

    # The duplicate Claim is consolidated into the higher-authority
    # KnowledgeUnit; the irrelevant chat record is never admitted.
    assert len(result.memory_context.items) == 1
    assert result.memory_context.items[0].context_id == "CTX-001"
    assert (
        result.memory_context.items[0].entity_type
        is SearchEntityType.KNOWLEDGE
    )
    assert (
        result.memory_context.items[0].text
        == "Berlin ist die Hauptstadt von Deutschland."
    )
    assert all(
        item.entity_type is not SearchEntityType.CHAT_MESSAGE
        for item in result.memory_context.items
    )

    assert len(result.source_context.items) == 1
    assert result.source_context.items[0].context_id == "CTX-002"
    assert result.source_context.items[0].anchor_id == anchors.anchor_id

    assert len(generation.calls) == 1
    call = generation.calls[0]
    contract = call["grounding_contract"]
    assert isinstance(contract, GroundingContract)
    assert contract.allowed_context_ids == ("CTX-001", "CTX-002")
    assert tuple(
        item.evidence_class for item in contract.evidence_refs
    ) == (
        EvidenceClass.CANONICAL,
        EvidenceClass.SOURCE,
    )

    package = result.context_package
    assert package.snapshot_commit_seq == 41
    assert package.sections[0].name == "unified_local_context"
    assert "ATHENA LOCAL MEMORY / KNOWLEDGE CONTEXT" in package.sections[0].content
    assert "ATHENA RAW ARCHIVE CONTEXT" in package.sections[0].content

    ref_by_id = {
        item.ref_id: item
        for item in package.included_refs
    }
    assert ref_by_id["CTX-001"].entity_type == "knowledge"
    assert ref_by_id["CTX-002"].entity_type == "source_anchor"
    assert ref_by_id["CTX-002"].entity_id == anchors.anchor_id
    assert ref_by_id["CTX-002"].revision_id is None
    assert "CURRENT-USER" in ref_by_id

    excluded = package.excluded_candidate_summary
    assert excluded.retrieval_candidate_count == 2
    assert excluded.retrieval_included_count == 2
    assert excluded.retrieval_excluded_count == 0

    assert result.processing_run.status == "succeeded"
    assert result.processing_run.run_type == "chat.unified_local_context_package"
    assert (
        result.processing_run.pipeline_version
        == "unified-local-chat-context-package-v1"
    )
    assert result.processing_run.prompt_template_id == "unified-local-grounding"

    assert packages.phases == [
        "post-unified-local-context-build",
        "immediately-before-primary-model-call",
    ]



def test_unified_retrieval_override_preserves_current_user_semantics() -> None:
    source = archive_result()
    generation = FakeChatGeneration()
    embedding = FakeEmbeddingProvider()
    memory_hybrid = FakeMemoryHybrid()
    archive = FakeArchiveRetrieval(source)
    anchors = FakeAnchors(source)
    packages = FakeContextPackages()
    runs = FakeModelRuns()

    service = UnifiedLocalChatService(
        chat_generation=generation,  # type: ignore[arg-type]
        embedding_provider=embedding,  # type: ignore[arg-type]
        hybrid_retrieval=memory_hybrid,  # type: ignore[arg-type]
        memory_context_builder=ContextBuilderService(),
        evidence_policy=FakeEvidencePolicy(),  # type: ignore[arg-type]
        personal_memory=FakePersonalMemory(),  # type: ignore[arg-type]
        archive_retrieval=archive,  # type: ignore[arg-type]
        source_context_builder=SourceContextBuilderService(anchors),  # type: ignore[arg-type]
        context_packages=packages,  # type: ignore[arg-type]
        model_runs=runs,  # type: ignore[arg-type]
    )

    retrieval_query = (
        "What do local knowledge and imported sources "
        "say about Berlin?\n"
        "And why?"
    )

    result = service.send_message(
        chat_id=uuid.uuid4(),
        content="And why?",
        retrieval_query=retrieval_query,
        requested_model_id="primary",
        requested_embedding_model_id="embed-model",
        max_memory_context_tokens=500,
        max_source_context_tokens=500,
        output_reserve=1000,
        safety_margin=100,
    )

    assert archive.calls[0][0] == retrieval_query

    assert all(
        call[0] == retrieval_query
        for call in memory_hybrid.calls
    )

    # Both model-facing context bundles preserve the real current turn.
    assert result.memory_context.query == "And why?"
    assert result.source_context.query == "And why?"

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


def test_unified_canonical_merge_preserves_contradictions_and_deduplicates() -> None:
    from athena.chat.unified import _merge_canonical_results

    berlin_knowledge = HybridSearchResult(
        entity_id=uuid.uuid4(),
        revision_id=uuid.uuid4(),
        entity_type=SearchEntityType.KNOWLEDGE,
        title="Hauptstadt von Deutschland",
        text="Berlin ist die Hauptstadt von Deutschland.",
        score=0.98,
        lexical_score=0.9,
        semantic_score=1.0,
        authority_score=1.0,
        contradiction_count=1,
        duplicate_count=0,
    )
    berlin_claim = HybridSearchResult(
        entity_id=uuid.uuid4(),
        revision_id=uuid.uuid4(),
        entity_type=SearchEntityType.CLAIM,
        title=None,
        text="Berlin ist die Hauptstadt von Deutschland.",
        score=0.95,
        lexical_score=0.85,
        semantic_score=0.95,
        authority_score=0.88,
        contradiction_count=1,
        duplicate_count=0,
    )
    munich_knowledge = HybridSearchResult(
        entity_id=uuid.uuid4(),
        revision_id=uuid.uuid4(),
        entity_type=SearchEntityType.KNOWLEDGE,
        title="Hauptstadt von Deutschland",
        text="M\\u00fcnchen ist die Hauptstadt von Deutschland.",
        score=0.97,
        lexical_score=0.88,
        semantic_score=0.98,
        authority_score=1.0,
        contradiction_count=1,
        duplicate_count=0,
    )

    merged = _merge_canonical_results(
        (berlin_knowledge, munich_knowledge),
        (berlin_claim,),
        limit=8,
    )

    assert len(merged) == 2

    by_text = {
        item.text: item
        for item in merged
    }

    assert set(by_text) == {
        "Berlin ist die Hauptstadt von Deutschland.",
        "M\\u00fcnchen ist die Hauptstadt von Deutschland.",
    }

    berlin = by_text[
        "Berlin ist die Hauptstadt von Deutschland."
    ]

    assert berlin.entity_type is SearchEntityType.KNOWLEDGE
    assert berlin.entity_id == berlin_knowledge.entity_id
    assert berlin.contradiction_count == 1
    assert berlin.duplicate_count == 1


def test_unified_canonical_merge_rejects_chat_results() -> None:
    from athena.chat.unified import _merge_canonical_results

    chat = HybridSearchResult(
        entity_id=uuid.uuid4(),
        revision_id=uuid.uuid4(),
        entity_type=SearchEntityType.CHAT_MESSAGE,
        title="Old chat",
        text="Historical conversation text.",
        score=1.0,
        lexical_score=1.0,
        semantic_score=1.0,
        authority_score=0.68,
        contradiction_count=0,
        duplicate_count=0,
    )

    try:
        _merge_canonical_results(
            (chat,),
            (),
            limit=8,
        )
    except ValueError as exc:
        assert "non-canonical" in str(exc)
    else:
        raise AssertionError(
            "Unified canonical merge admitted a chat result."
        )


def test_source_context_verifier_rejects_ctx_zero() -> None:
    source = archive_result()
    anchors = FakeAnchors(source)
    builder = SourceContextBuilderService(anchors)

    valid = builder.build_from_hybrid(
        query="Berlin",
        results=(source,),
        max_estimated_tokens=500,
        max_items=1,
    )

    assert len(valid.items) == 1

    invalid_items = (
        replace(
            valid.items[0],
            context_id="CTX-000",
        ),
    )

    rendered = _render_source_context(
        query=valid.query,
        mode=valid.mode,
        items=invalid_items,
    )

    invalid = replace(
        valid,
        items=invalid_items,
        rendered_text=rendered,
        estimated_tokens=estimate_tokens(
            rendered
        ),
    )

    try:
        builder.verify_bundle(invalid)
    except SourceContextIntegrityError as exc:
        assert "CTX-001 and CTX-999" in str(exc)
    else:
        raise AssertionError(
            "Source context verifier accepted CTX-000."
        )


def test_source_context_verifier_rejects_ctx_1000_after_999() -> None:
    source = archive_result()
    anchors = FakeAnchors(source)
    builder = SourceContextBuilderService(anchors)

    valid = builder.build_from_hybrid(
        query="Berlin",
        results=(source,),
        max_estimated_tokens=500,
        max_items=1,
    )

    assert len(valid.items) == 1

    # Duplicate the otherwise valid durable item so the old verifier would
    # construct CTX-999, CTX-1000 as its own expected sequence.
    invalid_items = (
        replace(
            valid.items[0],
            context_id="CTX-999",
        ),
        replace(
            valid.items[0],
            context_id="CTX-1000",
        ),
    )

    rendered = _render_source_context(
        query=valid.query,
        mode=valid.mode,
        items=invalid_items,
    )

    invalid = replace(
        valid,
        items=invalid_items,
        rendered_text=rendered,
        estimated_tokens=estimate_tokens(
            rendered
        ),
    )

    try:
        builder.verify_bundle(invalid)
    except SourceContextIntegrityError as exc:
        assert (
            "CTX-NNN" in str(exc)
            or "CTX-999" in str(exc)
        )
    else:
        raise AssertionError(
            "Source context verifier accepted CTX-1000."
        )


def test_unified_chat_degrades_both_domains_when_embedding_model_is_unavailable() -> None:
    source = archive_result()
    generation = FakeChatGeneration()
    embedding = FakeEmbeddingProvider(
        fail=True
    )
    memory_hybrid = FakeMemoryHybrid()
    archive = FakeArchiveRetrieval(
        source
    )
    anchors = FakeAnchors(
        source
    )
    packages = FakeContextPackages()
    runs = FakeModelRuns()

    service = UnifiedLocalChatService(
        chat_generation=generation,  # type: ignore[arg-type]
        embedding_provider=embedding,  # type: ignore[arg-type]
        hybrid_retrieval=memory_hybrid,  # type: ignore[arg-type]
        memory_context_builder=ContextBuilderService(),
        evidence_policy=FakeEvidencePolicy(),  # type: ignore[arg-type]
        personal_memory=FakePersonalMemory(),  # type: ignore[arg-type]
        archive_retrieval=archive,  # type: ignore[arg-type]
        source_context_builder=SourceContextBuilderService(
            anchors
        ),  # type: ignore[arg-type]
        context_packages=packages,  # type: ignore[arg-type]
        model_runs=runs,  # type: ignore[arg-type]
    )

    result = service.send_message(
        chat_id=uuid.uuid4(),
        content="What code is assigned to Project Borealis?",
        requested_model_id="primary",
        requested_embedding_model_id="missing-embed",
        max_memory_context_tokens=500,
        max_source_context_tokens=500,
        output_reserve=1000,
        safety_margin=100,
    )

    assert embedding.requests == [
        "missing-embed"
    ]
    assert archive.calls == []
    assert len(
        archive.lexical_calls
    ) == 1
    assert memory_hybrid.calls == []
    assert {
        call[2]
        for call in memory_hybrid.lexical_calls
    } == {
        SearchEntityType.KNOWLEDGE,
        SearchEntityType.CLAIM,
    }
    assert result.embedding_model is None
    assert len(generation.calls) == 1

    configuration = json.loads(
        result.context_package.model_signature.context_configuration_json
        or "{}"
    )
    assert (
        configuration["memory_retrieval_mode"]
        == "lexical_fallback"
    )
    assert (
        configuration["source_retrieval_mode"]
        == "lexical_fallback"
    )
    assert (
        configuration["retrieval_warnings"]
        == ["embedding_model_unavailable"]
    )
    assert configuration["embedding_model_id"] is None


def _conflict_grounding_fixture():
    source = archive_result()
    generation = FakeChatGeneration()
    embedding = FakeEmbeddingProvider()
    memory_hybrid = FakeMemoryHybrid()
    archive = FakeArchiveRetrieval(source)
    anchors = FakeAnchors(source)
    packages = FakeContextPackages()
    runs = FakeModelRuns()

    service = UnifiedLocalChatService(
        chat_generation=generation,  # type: ignore[arg-type]
        embedding_provider=embedding,  # type: ignore[arg-type]
        hybrid_retrieval=memory_hybrid,  # type: ignore[arg-type]
        memory_context_builder=ContextBuilderService(),
        evidence_policy=FakeEvidencePolicy(),  # type: ignore[arg-type]
        personal_memory=FakePersonalMemory(),  # type: ignore[arg-type]
        archive_retrieval=archive,  # type: ignore[arg-type]
        source_context_builder=SourceContextBuilderService(
            anchors
        ),  # type: ignore[arg-type]
        context_packages=packages,  # type: ignore[arg-type]
        model_runs=runs,  # type: ignore[arg-type]
    )
    return service, generation, memory_hybrid, archive


def test_unified_local_chat_exposes_epistemic_conflict_metadata_to_model() -> None:
    service, generation, _memory_hybrid, _archive = (
        _conflict_grounding_fixture()
    )

    service.send_message(
        chat_id=uuid.uuid4(),
        content="Was weiß ATHENA über die Hauptstadt Deutschlands?",
        requested_model_id="primary",
        requested_embedding_model_id="embed",
    )

    package = generation.calls[-1]["context_package"]
    system_text = package.sections[0].content

    assert "ATHENA EPISTEMIC INTERPRETATION" in system_text
    assert "ATHENA RESPONSE LANGUAGE" in system_text
    assert (
        "Respond in the same natural language as the current user message"
        in system_text
    )
    assert "Canonical means stored/accepted in ATHENA" in system_text
    assert "`asserted` means an assertion is stored" in system_text
    assert "ATHENA CANONICAL EPISTEMIC METADATA" in system_text
    assert '"epistemic_status": "asserted"' in system_text
    assert '"contradiction_count": 1' in system_text
    assert (
        '"contradiction_count_is_conflict_signal_not_truth_score": true'
        in system_text
    )

    configuration = json.loads(
        package.model_signature.context_configuration_json or "{}"
    )
    assert configuration["epistemic_grounding_version"] == 1
    assert configuration["response_language_policy_version"] == 1
    assert configuration["retrieval_query_policy_version"] == 1
    assert configuration["retrieval_query_mode"] == "current_message"


def test_unified_local_chat_contextualizes_short_followup_retrieval() -> None:
    service, generation, memory_hybrid, archive = (
        _conflict_grounding_fixture()
    )
    chat_id = uuid.uuid4()
    previous = "Was weiß ATHENA über die Hauptstadt Deutschlands?"
    current = "was davon ist richtig?"
    generation.chat.add_user_message(
        chat_id=chat_id,
        content=previous,
    )

    service.send_message(
        chat_id=chat_id,
        content=current,
        requested_model_id="primary",
        requested_embedding_model_id="embed",
    )

    expected_query = previous + "\n" + current

    assert memory_hybrid.calls
    assert {call[0] for call in memory_hybrid.calls} == {expected_query}
    assert {call[3] for call in memory_hybrid.calls} == {
        SearchEntityType.KNOWLEDGE,
        SearchEntityType.CLAIM,
    }
    assert archive.calls
    assert {call[0] for call in archive.calls} == {expected_query}

    package = generation.calls[-1]["context_package"]
    configuration = json.loads(
        package.model_signature.context_configuration_json or "{}"
    )
    assert configuration["retrieval_query_mode"] == (
        "previous_user_plus_current"
    )
    assert package.sections[-1].content == current


def test_unified_local_chat_explicit_retrieval_override_wins_over_followup() -> None:
    service, generation, memory_hybrid, archive = (
        _conflict_grounding_fixture()
    )
    chat_id = uuid.uuid4()
    generation.chat.add_user_message(
        chat_id=chat_id,
        content="Was weiß ATHENA über die Hauptstadt Deutschlands?",
    )

    explicit_query = "Deutschland Hauptstadt Konflikt"
    service.send_message(
        chat_id=chat_id,
        content="was davon ist richtig?",
        retrieval_query=explicit_query,
        requested_model_id="primary",
        requested_embedding_model_id="embed",
    )

    assert memory_hybrid.calls
    assert {call[0] for call in memory_hybrid.calls} == {explicit_query}
    assert archive.calls
    assert {call[0] for call in archive.calls} == {explicit_query}

    package = generation.calls[-1]["context_package"]
    configuration = json.loads(
        package.model_signature.context_configuration_json or "{}"
    )
    assert configuration["retrieval_query_mode"] == "explicit_override"
