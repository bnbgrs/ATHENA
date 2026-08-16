from __future__ import annotations

import json
import uuid
from collections.abc import Callable
from dataclasses import replace

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
from athena.model.provenance import ModelSignature, ProcessingRun
from athena.retrieval.context import ContextBuilderService
from athena.retrieval.context_package import ContextPackageService
from athena.retrieval.degradation import SemanticRetrievalUnavailableError
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
    def __init__(self, *, fail_semantic: bool = False) -> None:
        self.queries: list[str] = []
        self.lexical_queries: list[str] = []
        self.fail_semantic = fail_semantic
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
        del model_id, limit
        self.queries.append(query)
        if self.fail_semantic:
            raise SemanticRetrievalUnavailableError(
                "knowledge_semantic_unavailable"
            )
        return (self.result,)

    def search_lexical(
        self,
        query: str,
        *,
        limit: int,
        entity_type: SearchEntityType | None = None,
    ):
        del limit, entity_type
        self.lexical_queries.append(query)
        return (
            replace(
                self.result,
                semantic_score=0.0,
            ),
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


    def add_user_message(self, *, chat_id: uuid.UUID, content: str) -> ChatMessage:
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

    def assert_snapshot_current(self, expected_commit_seq: int, *, phase: str) -> None:
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

    def build(self, **kwargs):
        return ContextPackageService.build(**kwargs)


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
        if on_before_provider_call is not None:
            on_before_provider_call()
        max_output_tokens, reasoning_mode = context_package.generation_controls()
        model_messages = context_package.model_messages()
        self.calls.append(
            {
                "chat_id": chat_id,
                "content": user_message.content,
                "requested_model_id": context_package.model_signature.model_identifier,
                "retrieved_context": model_messages[0].content,
                "grounding_contract": grounding_contract,
                "max_output_tokens": max_output_tokens,
                "reasoning_mode": reasoning_mode,
                "context_package": context_package,
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
    *,
    embedding_provider=None,
):
    return MemoryAugmentedChatService(
        chat_generation=generation,  # type: ignore[arg-type]
        embedding_provider=(
            embedding_provider or FakeEmbeddingProvider()
        ),  # type: ignore[arg-type]
        hybrid_retrieval=hybrid,  # type: ignore[arg-type]
        context_builder=ContextBuilderService(),
        context_packages=FakeContextPackages(),  # type: ignore[arg-type]
        evidence_policy=FakeEvidencePolicy(),  # type: ignore[arg-type]
        personal_memory=memory or FakePersonalMemory(),  # type: ignore[arg-type]
        model_runs=FakeModelRuns(),  # type: ignore[arg-type]
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
    assert result.context_package.snapshot_commit_seq == 41
    assert result.processing_run.status == "succeeded"
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


def test_memory_chat_retrieval_override_preserves_current_user_semantics() -> None:
    generation = FakeChatGeneration()
    hybrid = FakeHybrid()
    service = _service(
        generation,
        hybrid,
    )

    retrieval_query = (
        "Welche Hauptstadt hat Deutschland?\n"
        "Und warum?"
    )

    result = service.send_message(
        chat_id=uuid.uuid4(),
        content="Und warum?",
        retrieval_query=retrieval_query,
        requested_model_id="primary",
        requested_embedding_model_id="embed",
        max_context_tokens=800,
        output_reserve=1000,
        safety_margin=200,
    )

    assert hybrid.queries == [
        retrieval_query
    ]

    payload = json.loads(
        result.context.rendered_text
    )

    # Model-facing context still reflects the exact current user turn.
    assert payload["query"] == "Und warum?"
    assert (
        result.generation.user_message.content
        == "Und warum?"
    )

    run_snapshot = json.loads(
        result.processing_run.input_snapshot_json
    )

    # Technical retrieval expansion is durable and auditable separately.
    assert (
        run_snapshot["retrieval_query_override"]
        == retrieval_query
    )


def test_memory_chat_canonical_only_retrieval_filters_chat_messages() -> None:
    generation = FakeChatGeneration()
    hybrid = FakeHybrid()

    hybrid.result = replace(
        hybrid.result,
        entity_type=SearchEntityType.CHAT_MESSAGE,
        title=None,
        text="Earlier assistant answer about Athenafalke 7319.",
    )

    service = _service(
        generation,
        hybrid,
    )

    result = service.send_message(
        chat_id=uuid.uuid4(),
        content="Welche Kennzahl verwendet Athenafalke?",
        canonical_only_retrieval=True,
        requested_model_id="primary",
        requested_embedding_model_id="embed",
        max_context_tokens=800,
        max_context_items=4,
        output_reserve=1000,
        safety_margin=200,
    )

    assert len(result.evidence_selection.results) == 0
    assert result.context.items == ()

    configuration = json.loads(
        result.context_package.model_signature.context_configuration_json
        or "{}"
    )

    assert (
        configuration["canonical_only_retrieval"]
        is True
    )


def test_memory_chat_default_retrieval_preserves_chat_message_candidates() -> None:
    generation = FakeChatGeneration()
    hybrid = FakeHybrid()

    hybrid.result = replace(
        hybrid.result,
        entity_type=SearchEntityType.CHAT_MESSAGE,
        title=None,
        text="Earlier conversation record.",
    )

    service = _service(
        generation,
        hybrid,
    )

    result = service.send_message(
        chat_id=uuid.uuid4(),
        content="Was haben wir im Chat besprochen?",
        requested_model_id="primary",
        requested_embedding_model_id="embed",
        max_context_tokens=800,
        max_context_items=4,
        output_reserve=1000,
        safety_margin=200,
    )

    assert len(result.evidence_selection.results) == 1

    assert (
        result.evidence_selection.results[0].entity_type
        is SearchEntityType.CHAT_MESSAGE
    )

    configuration = json.loads(
        result.context_package.model_signature.context_configuration_json
        or "{}"
    )

    assert (
        configuration["canonical_only_retrieval"]
        is False
    )


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


def test_memory_chat_uses_lexical_fallback_when_semantic_runtime_fails() -> None:
    generation = FakeChatGeneration()
    hybrid = FakeHybrid(
        fail_semantic=True
    )
    service = _service(
        generation,
        hybrid,
    )

    result = service.send_message(
        chat_id=uuid.uuid4(),
        content="What code is assigned to Project Borealis?",
        requested_model_id="primary",
        requested_embedding_model_id="embed-model",
        max_context_tokens=800,
        max_context_items=4,
        output_reserve=1000,
        safety_margin=200,
    )

    assert hybrid.queries == [
        "What code is assigned to Project Borealis?"
    ]
    assert hybrid.lexical_queries == [
        "What code is assigned to Project Borealis?"
    ]
    assert result.embedding_model is not None
    assert result.embedding_model.backend_model_id == "embed-model"
    assert len(result.context.items) == 1
    assert len(generation.calls) == 1

    configuration = json.loads(
        result.context_package.model_signature.context_configuration_json
        or "{}"
    )
    assert configuration["retrieval_mode"] == "lexical_fallback"
    assert (
        configuration["retrieval_warning"]
        == "knowledge_semantic_unavailable"
    )
    assert configuration["embedding_model_id"] == "embed-model"


def test_memory_grounded_history_excludes_prior_assistant_evidence_text() -> None:
    generation = FakeChatGeneration()
    hybrid = FakeHybrid()

    chat_id = uuid.uuid4()

    earlier_user = ChatMessage(
        message_id=uuid.uuid4(),
        chat_id=chat_id,
        sequence_no=1,
        message_type=MessageType.USER,
        actor_id=uuid.uuid4(),
        created_at_us=1,
        revision_id=uuid.uuid4(),
        content="Earlier Project Atlas question",
        content_format="text/plain",
    )

    earlier_assistant = ChatMessage(
        message_id=uuid.uuid4(),
        chat_id=chat_id,
        sequence_no=2,
        message_type=MessageType.ASSISTANT,
        actor_id=None,
        created_at_us=2,
        revision_id=uuid.uuid4(),
        content=(
            "Project Atlas has News code 1301 "
            "[NEWS:CTX-001].\n\n"
            "ATHENA_PROVENANCE "
            '{"athena_provenance_version":3,'
            '"evidence":[]}'
        ),
        content_format="text/plain",
    )

    generation.chat.messages = (
        earlier_user,
        earlier_assistant,
    )

    service = _service(
        generation,
        hybrid,
    )

    result = service.send_message(
        chat_id=chat_id,
        content=(
            "Was weisst du noch "
            "ueber Project Atlas?"
        ),
        requested_model_id="primary",
        requested_embedding_model_id="embed",
        max_context_tokens=800,
        max_context_items=4,
        output_reserve=1000,
        safety_margin=200,
        allow_model_prior=False,
    )

    model_messages = (
        result.context_package
        .model_messages()
    )

    assert any(
        item.role == "user"
        and item.content
        == "Earlier Project Atlas question"
        for item in model_messages
    )

    assert all(
        item.role != "assistant"
        for item in model_messages
    )

    assert all(
        "1301" not in item.content
        for item in model_messages
    )

    config = json.loads(
        result.context_package
        .model_signature
        .context_configuration_json
        or "{}"
    )

    assert (
        config[
            "conversation_history_policy"
        ]
        == "grounded_user_only"
    )

    snapshot = json.loads(
        result.processing_run
        .input_snapshot_json
    )

    counts = snapshot[
        "excluded_candidate_summary"
    ]

    assert (
        counts[
            "conversation_candidate_count"
        ]
        == 2
    )

    assert (
        counts[
            "conversation_included_count"
        ]
        == 1
    )

    assert (
        counts[
            "conversation_excluded_count"
        ]
        == 1
    )
