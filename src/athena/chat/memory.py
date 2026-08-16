"""Retrieval-augmented persistent chat orchestration."""

from __future__ import annotations

import uuid
from collections.abc import Callable
from dataclasses import dataclass

from athena.chat.generation import (
    GROUNDING_RETRY_POLICY,
    ChatGenerationResult,
    ChatGenerationService,
)
from athena.chat.grounding import (
    GroundingContract,
    GroundingEvidenceRef,
    render_grounding_instructions,
)
from athena.chat.models import ChatMessage, MessageType
from athena.memory.models import MemoryScopeKind
from athena.memory.service import PersonalMemoryService
from athena.model.adapters.lm_studio_embeddings import LMStudioEmbeddingProvider
from athena.model.domain import ModelInfo
from athena.model.provenance import ModelRunRepository, ProcessingRun
from athena.retrieval.context import (
    ContextBuilderError,
    ContextBuilderService,
    ContextBundle,
    estimate_tokens,
)
from athena.retrieval.context_package import (
    ContextPackage,
    ContextPackageBudget,
    ContextPackageService,
    ContextTokenEstimates,
)
from athena.retrieval.degradation import (
    LEXICAL_FALLBACK_RETRIEVAL_MODE,
    SemanticRetrievalUnavailableError,
    resolve_embedding_model_for_retrieval,
)
from athena.retrieval.evidence import MemoryEvidencePolicy, MemoryEvidenceSelection
from athena.retrieval.hybrid import HybridRetrievalService
from athena.retrieval.search import SearchEntityType

_MIN_CONTEXT_BUDGET = 128
_MAX_CONTEXT_BUDGET = 64_000
_MAX_CONTEXT_ITEMS = 100
_MAX_MEMORY_ITEMS = 100
_DEFAULT_RECENT_CONVERSATION_TURNS = 8
_MAX_RECENT_CONVERSATION_TURNS = 100
_DEFAULT_OUTPUT_RESERVE = 2048
_DEFAULT_SAFETY_MARGIN = 256
_MESSAGE_WRAPPER_ESTIMATE = 6
_CONTEXT_PACKAGE_VERSION = 1
_CONTEXT_BUILDER_VERSION = 2


@dataclass(frozen=True, slots=True)
class ContextBudgetReport:
    """Deterministic accounting for one memory-augmented chat model call."""

    effective_context_limit: int
    estimated_input_tokens: int
    context_tokens: int
    output_reserve: int
    safety_margin: int
    estimated_total_tokens: int


@dataclass(frozen=True, slots=True)
class MemoryChatGenerationResult:
    """One completed chat turn plus its reconstructible context contract."""

    generation: ChatGenerationResult
    context: ContextBundle
    context_package: ContextPackage
    processing_run: ProcessingRun
    embedding_model: ModelInfo | None
    evidence_selection: MemoryEvidenceSelection
    budget: ContextBudgetReport


class MemoryAugmentedChatService:
    """Retrieve evidence, build one pinned ContextPackage, then call Primary Model."""

    def __init__(
        self,
        *,
        chat_generation: ChatGenerationService,
        embedding_provider: LMStudioEmbeddingProvider,
        hybrid_retrieval: HybridRetrievalService,
        context_builder: ContextBuilderService,
        context_packages: ContextPackageService,
        evidence_policy: MemoryEvidencePolicy,
        personal_memory: PersonalMemoryService,
        model_runs: ModelRunRepository,
    ) -> None:
        self.chat_generation = chat_generation
        self.embedding_provider = embedding_provider
        self.hybrid_retrieval = hybrid_retrieval
        self.context_builder = context_builder
        self.context_packages = context_packages
        self.evidence_policy = evidence_policy
        self.personal_memory = personal_memory
        self.model_runs = model_runs

    def send_message(
        self,
        *,
        chat_id: uuid.UUID,
        content: str,
        retrieval_query: str | None = None,
        canonical_only_retrieval: bool = False,
        requested_model_id: str | None = None,
        requested_embedding_model_id: str | None = None,
        max_context_tokens: int = 1200,
        max_context_items: int = 8,
        max_memory_items: int = 8,
        max_recent_conversation_turns: int = _DEFAULT_RECENT_CONVERSATION_TURNS,
        memory_scope_kind: MemoryScopeKind | None = None,
        memory_scope_entity_id: uuid.UUID | None = None,
        effective_context_limit: int | None = None,
        output_reserve: int = _DEFAULT_OUTPUT_RESERVE,
        safety_margin: int = _DEFAULT_SAFETY_MARGIN,
        allow_model_prior: bool = True,
        on_delta: Callable[[str], None] | None = None,
    ) -> MemoryChatGenerationResult:
        self._validate_request(
            max_context_tokens=max_context_tokens,
            max_context_items=max_context_items,
            max_memory_items=max_memory_items,
            max_recent_conversation_turns=max_recent_conversation_turns,
            output_reserve=output_reserve,
            safety_margin=safety_margin,
        )

        search_query = content
        if retrieval_query is not None:
            search_query = retrieval_query.strip()
            if not search_query:
                raise ContextBuilderError(
                    "Retrieval query override must not be empty."
                )

        model = self.chat_generation.select_model(requested_model_id)
        context_limit = self._resolve_context_limit(
            model=model,
            requested_limit=effective_context_limit,
        )

        # Pin canonical state before reading any model-facing history or retrieval
        # evidence. Any canonical drift before the current-user write fails closed.
        retrieval_snapshot_commit_seq = self.context_packages.current_commit_seq()
        thread = self.chat_generation.chat.load_chat(chat_id)
        recent_messages = _select_recent_conversation_window(
            thread.messages,
            max_turns=max_recent_conversation_turns,
            include_assistant=False,
        )
        conversation_tokens = _estimate_persisted_messages(recent_messages)
        current_user_tokens = estimate_tokens(content) + _MESSAGE_WRAPPER_ESTIMATE
        fixed_input_tokens = conversation_tokens + current_user_tokens
        available_for_context = (
            context_limit - fixed_input_tokens - output_reserve - safety_margin
        )
        if available_for_context < _MIN_CONTEXT_BUDGET:
            raise ContextBuilderError(
                "Current conversation plus output reserve and safety margin leave "
                "insufficient room for a bounded ATHENA context."
            )
        context_budget = min(max_context_tokens, available_for_context)

        memories = self.personal_memory.context_candidates(
            scope_kind=memory_scope_kind,
            scope_entity_id=memory_scope_entity_id,
            limit=max(32, max_memory_items),
        )

        embedding_resolution = resolve_embedding_model_for_retrieval(
            self.embedding_provider,
            requested_embedding_model_id,
        )
        embedding_model = embedding_resolution.model
        retrieval_mode = embedding_resolution.mode
        retrieval_warning = embedding_resolution.warning

        candidate_limit = min(200, max(40, max_context_items * 8))

        if embedding_model is None:
            results = self.hybrid_retrieval.search_lexical(
                search_query,
                limit=candidate_limit,
            )
        else:
            try:
                results = self.hybrid_retrieval.search(
                    search_query,
                    model_id=embedding_model.backend_model_id,
                    limit=candidate_limit,
                )
            except SemanticRetrievalUnavailableError as exc:
                retrieval_mode = LEXICAL_FALLBACK_RETRIEVAL_MODE
                retrieval_warning = exc.reason_code
                results = self.hybrid_retrieval.search_lexical(
                    search_query,
                    limit=candidate_limit,
                )

        if canonical_only_retrieval:
            results = tuple(
                item
                for item in results
                if item.entity_type
                in {
                    SearchEntityType.KNOWLEDGE,
                    SearchEntityType.CLAIM,
                }
            )

        evidence_selection = self.evidence_policy.classify(results)

        context: ContextBundle | None = None
        grounding_contract: GroundingContract | None = None
        estimated_input_tokens = 0
        system_text = ""

        for _ in range(8):
            context = self.context_builder.build_from_hybrid(
                query=content,
                results=evidence_selection.results,
                personal_memory=memories,
                max_estimated_tokens=context_budget,
                max_items=max_context_items,
                max_memory_items=max_memory_items,
            )
            grounding_contract = self._grounding_contract(
                context=context,
                evidence_selection=evidence_selection,
                allow_model_prior=allow_model_prior,
            )
            system_text = (
                render_grounding_instructions(grounding_contract)
                + context.rendered_text
            )
            estimated_input_tokens = fixed_input_tokens + estimate_tokens(system_text)
            total = estimated_input_tokens + output_reserve + safety_margin
            if total <= context_limit:
                break
            overflow = total - context_limit
            next_budget = context_budget - overflow - 8
            if next_budget < _MIN_CONTEXT_BUDGET:
                raise ContextBuilderError(
                    "Context cannot be reduced enough to preserve output reserve and "
                    "safety margin for the active model context."
                )
            context_budget = next_budget
        else:
            raise RuntimeError("Context Builder budget convergence failed.")

        assert context is not None
        assert grounding_contract is not None
        budget_report = ContextBudgetReport(
            effective_context_limit=context_limit,
            estimated_input_tokens=estimated_input_tokens,
            context_tokens=context.estimated_tokens,
            output_reserve=output_reserve,
            safety_margin=safety_margin,
            estimated_total_tokens=(
                estimated_input_tokens + output_reserve + safety_margin
            ),
        )
        if budget_report.estimated_total_tokens > context_limit:
            raise RuntimeError("ATHENA attempted to exceed the active context budget.")

        self.context_packages.assert_snapshot_current(
            retrieval_snapshot_commit_seq,
            phase="post-context-build",
        )

        context_configuration = {
            "context_package_version": _CONTEXT_PACKAGE_VERSION,
            "context_builder_version": _CONTEXT_BUILDER_VERSION,
            "effective_context_limit": context_limit,
            "context_budget": context_budget,
            "max_context_items": max_context_items,
            "max_memory_items": max_memory_items,
            "max_recent_conversation_turns": max_recent_conversation_turns,
            "safety_margin": safety_margin,
            "conversation_history_policy": "grounded_user_only",
            "grounding_retry_policy": GROUNDING_RETRY_POLICY,
            "embedding_model_id": (
                None
                if embedding_model is None
                else embedding_model.backend_model_id
            ),
            "retrieval_mode": retrieval_mode,
            "retrieval_warning": retrieval_warning,
            "evidence_policy_id": evidence_selection.policy_id,
            "canonical_only_retrieval": canonical_only_retrieval,
            "allow_model_prior": allow_model_prior,
        }
        signature = self.model_runs.get_or_create_signature(
            model=model,
            generation_parameters={
                "max_output_tokens": output_reserve,
                "reasoning_mode": "off",
            },
            context_configuration=context_configuration,
        )

        # Persist the exact current instruction only after retrieval is complete so
        # it cannot retrieve itself. The commit guard allows exactly this one new
        # canonical commit and rejects every other drift.
        user_message = self.chat_generation.chat.add_user_message(
            chat_id=chat_id,
            content=content,
        )
        package_snapshot_commit_seq = self.context_packages.assert_user_commit_follows(
            retrieval_snapshot_commit_seq,
            user_message,
        )

        token_estimates = ContextTokenEstimates(
            conversation_tokens=conversation_tokens,
            current_user_tokens=current_user_tokens,
            system_tokens=estimate_tokens(system_text),
            context_tokens=context.estimated_tokens,
            estimated_input_tokens=estimated_input_tokens,
            estimated_total_tokens=budget_report.estimated_total_tokens,
        )
        package = self.context_packages.build(
            model_signature=signature,
            context=context,
            system_text=system_text,
            prior_messages=recent_messages,
            current_user_message=user_message,
            budget=ContextPackageBudget(
                effective_context_limit=context_limit,
                context_budget=context_budget,
                output_reserve=output_reserve,
                safety_margin=safety_margin,
            ),
            token_estimates=token_estimates,
            snapshot_commit_seq=package_snapshot_commit_seq,
            retrieval_candidate_count=len(evidence_selection.results),
            memory_candidate_count=len(memories),
            conversation_candidate_count=len(thread.messages),
        )

        if user_message.actor_id is None:
            raise RuntimeError("Persisted user message has no actor for ProcessingRun.")

        run_snapshot = package.run_snapshot()
        if retrieval_query is not None:
            run_snapshot = {
                **run_snapshot,
                "retrieval_query_override": search_query,
            }

        processing_run = self.model_runs.start_run(
            run_type="chat.memory_context_package",
            trigger_actor_id=user_message.actor_id,
            pipeline_version="memory-chat-context-package-v1",
            input_snapshot=run_snapshot,
            configuration=context_configuration,
            model_signature_id=signature.model_signature_id,
            prompt_template_id="memory-grounding",
            prompt_template_version="1",
        )

        try:
            generation = self.chat_generation.send_context_package(
                chat_id=chat_id,
                user_message=user_message,
                context_package=package,
                on_delta=on_delta,
                grounding_contract=grounding_contract,
                on_before_provider_call=lambda: (
                    self.context_packages.assert_snapshot_current(
                        package.snapshot_commit_seq,
                        phase="immediately-before-primary-model-call",
                    )
                ),
            )
        except KeyboardInterrupt:
            self.model_runs.finish_run(
                processing_run.processing_run_id,
                status="cancelled",
            )
            raise
        except Exception as exc:
            self.model_runs.finish_run(
                processing_run.processing_run_id,
                status="failed",
                error_detail=f"{type(exc).__name__}: {exc}"[:4000],
            )
            raise

        processing_run = self.model_runs.finish_run(
            processing_run.processing_run_id,
            status="succeeded",
        )
        return MemoryChatGenerationResult(
            generation=generation,
            context=context,
            context_package=package,
            processing_run=processing_run,
            embedding_model=embedding_model,
            evidence_selection=evidence_selection,
            budget=budget_report,
        )

    @staticmethod
    def _validate_request(
        *,
        max_context_tokens: int,
        max_context_items: int,
        max_memory_items: int,
        max_recent_conversation_turns: int,
        output_reserve: int,
        safety_margin: int,
    ) -> None:
        if not _MIN_CONTEXT_BUDGET <= max_context_tokens <= _MAX_CONTEXT_BUDGET:
            raise ContextBuilderError(
                "Context token budget must be between 128 and 64000."
            )
        if not 1 <= max_context_items <= _MAX_CONTEXT_ITEMS:
            raise ContextBuilderError("Context max-items must be between 1 and 100.")
        if not 0 <= max_memory_items <= _MAX_MEMORY_ITEMS:
            raise ContextBuilderError(
                "Context max-memory-items must be between 0 and 100."
            )
        if not 1 <= max_recent_conversation_turns <= _MAX_RECENT_CONVERSATION_TURNS:
            raise ContextBuilderError(
                "Recent conversation turns must be between 1 and 100."
            )
        if output_reserve < 1:
            raise ContextBuilderError("Output reserve must be positive.")
        if safety_margin < 0:
            raise ContextBuilderError("Safety margin must not be negative.")

    @staticmethod
    def _resolve_context_limit(
        *,
        model: ModelInfo,
        requested_limit: int | None,
    ) -> int:
        reported_effective = model.loaded_context_length
        if requested_limit is None:
            if reported_effective is None:
                raise ContextBuilderError(
                    "Active model did not report its loaded runtime context; provide an "
                    "explicit effective context limit instead of assuming the model maximum."
                )
            return reported_effective
        if requested_limit < 1:
            raise ContextBuilderError("Effective context limit must be positive.")
        if (
            model.context_capacity is not None
            and requested_limit > model.context_capacity
        ):
            raise ContextBuilderError(
                "Requested effective context limit exceeds the model maximum capacity."
            )
        if (
            model.loaded_context_length is not None
            and requested_limit > model.loaded_context_length
        ):
            raise ContextBuilderError(
                "Requested effective context limit exceeds the currently loaded "
                "LM Studio context."
            )
        return requested_limit

    @staticmethod
    def _grounding_contract(
        *,
        context: ContextBundle,
        evidence_selection: MemoryEvidenceSelection,
        allow_model_prior: bool,
    ) -> GroundingContract:
        evidence_refs: list[GroundingEvidenceRef] = []
        for item in context.items:
            classification = evidence_selection.classification_for(
                entity_type=item.entity_type,
                entity_id=item.entity_id,
                revision_id=item.revision_id,
            )
            evidence_refs.append(
                GroundingEvidenceRef(
                    context_id=item.context_id,
                    entity_type=item.entity_type.value,
                    entity_id=item.entity_id,
                    revision_id=item.revision_id,
                    evidence_class=classification.evidence_class,
                )
            )
        return GroundingContract(
            evidence_refs=tuple(evidence_refs),
            allow_model_prior=allow_model_prior,
        )


def _select_recent_conversation_window(
    messages: tuple[ChatMessage, ...],
    *,
    max_turns: int,
    include_assistant: bool = True,
) -> tuple[ChatMessage, ...]:
    """Select recent conversation with optional Assistant projection.

    Direct chat retains complete conversational history by default.

    Grounded paths exclude historical Assistant prose so a prior generated
    answer cannot silently become evidence under a later grounding contract.
    Historical User turns remain available for conversational continuity.
    """

    if not 1 <= max_turns <= _MAX_RECENT_CONVERSATION_TURNS:
        raise ContextBuilderError(
            "Recent conversation turns must be between 1 and 100."
        )

    if not messages:
        return ()

    selected_reversed: list[ChatMessage] = []
    user_turns = 0

    for message in reversed(messages):
        if message.message_type is MessageType.USER:
            selected_reversed.append(
                message
            )

            user_turns += 1

            if user_turns >= max_turns:
                break

            continue

        if message.message_type is MessageType.ASSISTANT:
            if include_assistant:
                selected_reversed.append(
                    message
                )

            continue

        # Preserve unexpected message kinds so downstream validation
        # continues to fail closed rather than hiding invalid state.
        selected_reversed.append(
            message
        )

    return tuple(
        reversed(
            selected_reversed
        )
    )


def _estimate_persisted_messages(messages: tuple[ChatMessage, ...]) -> int:
    total = 0
    for message in messages:
        if message.content is not None:
            total += estimate_tokens(message.content) + _MESSAGE_WRAPPER_ESTIMATE
    return total
