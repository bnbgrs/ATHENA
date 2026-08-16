"""Grounded chat over durable prior ATHENA Research results."""

from __future__ import annotations

import uuid
from collections.abc import Callable
from dataclasses import dataclass

from athena.chat.direct import (
    _estimate_persisted_messages,
    _prior_chat_sections,
    _resolve_context_limit,
    _select_recent_conversation_window,
)
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
from athena.chat.models import ChatMessage
from athena.model.provenance import ModelRunRepository, ProcessingRun
from athena.retrieval.context import ContextBuilderError, estimate_tokens
from athena.retrieval.context_package import (
    ContextIncludedRef,
    ContextPackage,
    ContextPackageBudget,
    ContextPackageService,
    ContextSection,
    ContextTokenEstimates,
    ExcludedCandidateSummary,
)
from athena.retrieval.evidence import EvidenceClass
from athena.retrieval.prior_research import (
    PriorResearchContextBuilderService,
    PriorResearchContextBundle,
    PriorResearchSearchService,
)

_DEFAULT_RECENT_CONVERSATION_TURNS = 8
_MAX_RECENT_CONVERSATION_TURNS = 100
_DEFAULT_OUTPUT_RESERVE = 2048
_DEFAULT_SAFETY_MARGIN = 256
_MESSAGE_WRAPPER_ESTIMATE = 6
_MIN_CONTEXT_BUDGET = 128


@dataclass(frozen=True, slots=True)
class ResearchContextBudgetReport:
    effective_context_limit: int
    estimated_input_tokens: int
    context_tokens: int
    output_reserve: int
    safety_margin: int
    estimated_total_tokens: int


@dataclass(frozen=True, slots=True)
class ResearchGroundedChatResult:
    generation: ChatGenerationResult
    context: PriorResearchContextBundle
    context_package: ContextPackage
    processing_run: ProcessingRun
    budget: ResearchContextBudgetReport


class ResearchGroundedChatService:
    """Retrieve prior Research and call exactly one Primary Model."""

    def __init__(
        self,
        *,
        chat_generation: ChatGenerationService,
        retrieval: PriorResearchSearchService,
        context_builder: PriorResearchContextBuilderService,
        context_packages: ContextPackageService,
        model_runs: ModelRunRepository,
    ) -> None:
        self.chat_generation = chat_generation
        self.retrieval = retrieval
        self.context_builder = context_builder
        self.context_packages = context_packages
        self.model_runs = model_runs

    def send_message(
        self,
        *,
        chat_id: uuid.UUID,
        content: str,
        retrieval_query: str | None = None,
        requested_model_id: str | None = None,
        max_context_tokens: int = 1200,
        max_context_items: int = 8,
        max_recent_conversation_turns: int = (
            _DEFAULT_RECENT_CONVERSATION_TURNS
        ),
        effective_context_limit: int | None = None,
        output_reserve: int = _DEFAULT_OUTPUT_RESERVE,
        safety_margin: int = _DEFAULT_SAFETY_MARGIN,
        allow_model_prior: bool = True,
        on_delta: Callable[[str], None] | None = None,
    ) -> ResearchGroundedChatResult:
        if not 128 <= max_context_tokens <= 64_000:
            raise ContextBuilderError(
                "Prior Research context token budget "
                "must be between 128 and 64000."
            )

        if not 1 <= max_context_items <= 100:
            raise ContextBuilderError(
                "Prior Research context max-items "
                "must be between 1 and 100."
            )

        if not (
            1
            <= max_recent_conversation_turns
            <= _MAX_RECENT_CONVERSATION_TURNS
        ):
            raise ContextBuilderError(
                "Recent conversation turns "
                "must be between 1 and 100."
            )

        if output_reserve < 1:
            raise ContextBuilderError(
                "Output reserve must be positive."
            )

        if safety_margin < 0:
            raise ContextBuilderError(
                "Safety margin must not be negative."
            )

        search_query = content

        if retrieval_query is not None:
            search_query = retrieval_query.strip()

            if not search_query:
                raise ContextBuilderError(
                    "Retrieval query override "
                    "must not be empty."
                )

        model = self.chat_generation.select_model(
            requested_model_id
        )

        context_limit = _resolve_context_limit(
            model=model,
            requested_limit=effective_context_limit,
        )

        candidate_limit = min(
            100,
            max(
                20,
                max_context_items * 8,
            ),
        )

        results = self.retrieval.search(
            search_query,
            limit=candidate_limit,
        )

        context_budget = max_context_tokens

        context: (
            PriorResearchContextBundle
            | None
        ) = None

        grounding_contract: (
            GroundingContract
            | None
        ) = None

        recent_messages: tuple[
            ChatMessage,
            ...
        ] = ()

        prior_sections: tuple[
            ContextSection,
            ...
        ] = ()

        prior_refs: tuple[
            ContextIncludedRef,
            ...
        ] = ()

        conversation_tokens = 0

        current_user_tokens = (
            estimate_tokens(
                content
            )
            + _MESSAGE_WRAPPER_ESTIMATE
        )

        system_text = ""
        estimated_input_tokens = 0
        estimated_total_tokens = 0

        retrieval_snapshot_commit_seq = (
            self.context_packages.current_commit_seq()
        )

        for _ in range(8):
            context = self.context_builder.build(
                query=content,
                results=results,
                max_estimated_tokens=context_budget,
                max_items=max_context_items,
            )

            self.context_builder.verify_bundle(
                context
            )

            thread = self.chat_generation.chat.load_chat(
                chat_id
            )

            recent_messages = _select_recent_conversation_window(
                thread.messages,
                max_turns=max_recent_conversation_turns,
                include_assistant=False,
            )

            (
                prior_sections,
                prior_refs,
            ) = _prior_chat_sections(
                recent_messages
            )

            conversation_tokens = _estimate_persisted_messages(
                recent_messages
            )

            grounding_contract = self._grounding_contract(
                context=context,
                allow_model_prior=allow_model_prior,
            )

            system_text = (
                render_grounding_instructions(
                    grounding_contract
                )
                + "ATHENA PRIOR RESEARCH CONTEXT\n"
                + context.rendered_text
            )

            estimated_input_tokens = (
                conversation_tokens
                + current_user_tokens
                + estimate_tokens(
                    system_text
                )
            )

            estimated_total_tokens = (
                estimated_input_tokens
                + output_reserve
                + safety_margin
            )

            if estimated_total_tokens <= context_limit:
                break

            overflow = (
                estimated_total_tokens
                - context_limit
            )

            next_budget = (
                context_budget
                - overflow
                - 8
            )

            if next_budget < _MIN_CONTEXT_BUDGET:
                raise ContextBuilderError(
                    "Prior Research context cannot "
                    "be reduced enough to preserve "
                    "output reserve and safety margin."
                )

            context_budget = next_budget
        else:
            raise RuntimeError(
                "Prior Research Context Builder "
                "budget convergence failed."
            )

        assert context is not None
        assert grounding_contract is not None

        self.context_packages.assert_snapshot_current(
            retrieval_snapshot_commit_seq,
            phase="post-prior-research-context-build",
        )

        context_configuration = {
            "context_package_version": 1,
            "mode": "prior_research_chat",
            "effective_context_limit": context_limit,
            "context_budget": context_budget,
            "max_context_items": max_context_items,
            "max_recent_conversation_turns": (
                max_recent_conversation_turns
            ),
            "safety_margin": safety_margin,
            "conversation_history_policy": "grounded_user_only",
            "grounding_retry_policy": GROUNDING_RETRY_POLICY,
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

        user_message = self.chat_generation.chat.add_user_message(
            chat_id=chat_id,
            content=content,
        )

        package_snapshot_commit_seq = (
            self.context_packages.assert_user_commit_follows(
                retrieval_snapshot_commit_seq,
                user_message,
            )
        )

        research_refs = tuple(
            ContextIncludedRef(
                ref_id=item.context_id,
                entity_type="research_result",
                entity_id=item.result_id,
                revision_id=None,
            )
            for item in context.items
        )

        current_ref = ContextIncludedRef(
            ref_id="CURRENT-USER",
            entity_type="chat_message",
            entity_id=user_message.message_id,
            revision_id=user_message.revision_id,
        )

        sections = (
            ContextSection(
                name="prior_research_context",
                role="system",
                content=system_text,
                included_ref_ids=tuple(
                    item.ref_id
                    for item in research_refs
                ),
            ),
            *prior_sections,
            ContextSection(
                name="current_user",
                role="user",
                content=content,
                included_ref_ids=(
                    current_ref.ref_id,
                ),
            ),
        )

        package = self.context_packages.build_from_sections(
            model_signature=signature,
            budget=ContextPackageBudget(
                effective_context_limit=context_limit,
                context_budget=context_budget,
                output_reserve=output_reserve,
                safety_margin=safety_margin,
            ),
            sections=sections,
            included_refs=(
                *research_refs,
                *prior_refs,
                current_ref,
            ),
            excluded_candidate_summary=ExcludedCandidateSummary(
                retrieval_candidate_count=len(results),
                retrieval_included_count=len(
                    context.items
                ),
                retrieval_excluded_count=(
                    len(results)
                    - len(context.items)
                ),
                memory_candidate_count=0,
                memory_included_count=0,
                memory_excluded_count=0,
                conversation_candidate_count=len(
                    thread.messages
                ),
                conversation_included_count=len(
                    recent_messages
                ),
                conversation_excluded_count=(
                    len(thread.messages)
                    - len(recent_messages)
                ),
            ),
            token_estimates=ContextTokenEstimates(
                conversation_tokens=conversation_tokens,
                current_user_tokens=current_user_tokens,
                system_tokens=estimate_tokens(
                    system_text
                ),
                context_tokens=context.estimated_tokens,
                estimated_input_tokens=estimated_input_tokens,
                estimated_total_tokens=estimated_total_tokens,
            ),
            snapshot_commit_seq=package_snapshot_commit_seq,
        )

        budget_report = ResearchContextBudgetReport(
            effective_context_limit=context_limit,
            estimated_input_tokens=estimated_input_tokens,
            context_tokens=context.estimated_tokens,
            output_reserve=output_reserve,
            safety_margin=safety_margin,
            estimated_total_tokens=estimated_total_tokens,
        )

        if user_message.actor_id is None:
            raise RuntimeError(
                "Persisted user message has "
                "no actor for ProcessingRun."
            )

        run_snapshot = package.run_snapshot()

        if retrieval_query is not None:
            run_snapshot = {
                **run_snapshot,
                "retrieval_query_override": search_query,
            }

        processing_run = self.model_runs.start_run(
            run_type="chat.research_context_package",
            trigger_actor_id=user_message.actor_id,
            pipeline_version="research-chat-context-package-v1",
            input_snapshot=run_snapshot,
            configuration=context_configuration,
            model_signature_id=signature.model_signature_id,
            prompt_template_id="research-grounding",
            prompt_template_version="1",
        )

        def before_provider() -> None:
            self.context_packages.assert_snapshot_current(
                package.snapshot_commit_seq,
                phase=(
                    "immediately-before-primary-model-call"
                ),
            )

            self.context_builder.verify_bundle(
                context
            )

        try:
            generation = self.chat_generation.send_context_package(
                chat_id=chat_id,
                user_message=user_message,
                context_package=package,
                on_delta=on_delta,
                grounding_contract=grounding_contract,
                on_before_provider_call=before_provider,
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
                error_detail=(
                    f"{type(exc).__name__}: {exc}"
                )[:4000],
            )
            raise

        processing_run = self.model_runs.finish_run(
            processing_run.processing_run_id,
            status="succeeded",
        )

        return ResearchGroundedChatResult(
            generation=generation,
            context=context,
            context_package=package,
            processing_run=processing_run,
            budget=budget_report,
        )

    @staticmethod
    def _grounding_contract(
        *,
        context: PriorResearchContextBundle,
        allow_model_prior: bool,
    ) -> GroundingContract:
        evidence_refs = tuple(
            GroundingEvidenceRef(
                context_id=item.context_id,
                entity_type="research_result",
                entity_id=item.result_id,
                revision_id=None,
                evidence_class=EvidenceClass.RESEARCH,
                research_scope_id=item.scope_id,
                research_final_artifact_id=(
                    item.final_artifact_id
                ),
                research_content_hash=item.content_hash,
            )
            for item in context.items
        )

        return GroundingContract(
            evidence_refs=evidence_refs,
            allow_model_prior=allow_model_prior,
        )
