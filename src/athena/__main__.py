"""Command-line launcher for ATHENA."""

from __future__ import annotations

import argparse
import hashlib
import os
import subprocess
import sys
import tempfile
import threading
import time
from collections.abc import Sequence
from pathlib import Path

from athena.chat.adaptive import AdaptiveChatResult
from athena.chat.generation import ModelSelectionError, UnsupportedChatHistoryError
from athena.chat.memory import MemoryChatGenerationResult
from athena.chat.repository import ChatNotFoundError
from athena.chat.service import EmptyMessageError
from athena.chat.source_grounding import SourceGroundedChatResult
from athena.chat.unified import UnifiedLocalChatResult
from athena.cli.parser import build_parser
from athena.cli.render import (
    _print_chat,
    _print_claim,
    _print_embedding_rebuild_result,
    _print_extraction,
    _print_job,
    _print_knowledge,
    _print_paths,
    _print_personal_memory,
    _print_review_item,
    _print_scheduler_run,
    _print_scheduler_tick,
    _print_source_analysis_result,
    _print_source_anchor,
    _print_source_extraction,
    _print_source_extraction_job_result,
    _print_source_processing_result,
    _print_source_record,
    _print_source_representation_record,
)
from athena.config.settings import ConfigurationError
from athena.core.application import AthenaApplication
from athena.jobs.embedding_processing import (
    EmbeddingRebuildJobError,
)
from athena.jobs.lane_lock import (
    SchedulerLaneOwnershipError,
    SchedulerLaneProcessLock,
)
from athena.jobs.models import JobPriority
from athena.jobs.repository import (
    CheckpointNotFoundError,
    JobLeaseError,
    JobNotFoundError,
    JobTransitionError,
)
from athena.jobs.scheduler import (
    JobSchedulerError,
    SchedulerLane,
)
from athena.jobs.source_analysis import SourceAnalysisJobError
from athena.jobs.source_extraction import (
    SourceHierarchicalExtractionJobError,
)
from athena.jobs.source_processing import (
    SourceProcessingJobError,
)
from athena.knowledge.claim_repository import ClaimNotFoundError, ClaimRelationError
from athena.knowledge.extraction_models import ChatExtractionResult
from athena.knowledge.extraction_snapshot import ExtractionSnapshotNotFoundError
from athena.knowledge.repository import (
    KnowledgeActorError,
    KnowledgeConflictError,
    KnowledgeNotFoundError,
    KnowledgeSourceError,
)
from athena.knowledge.review_service import ReviewError
from athena.knowledge.service import (
    ChatMessageSequenceError,
    UnsupportedKnowledgeSourceError,
)
from athena.knowledge.source_extraction import (
    SourceAnalysisExtractionResult,
    SourceExtractionSnapshotNotFoundError,
)
from athena.memory.explicit_command import is_explicit_persistence_command
from athena.memory.repository import (
    PersonalMemoryActorError,
    PersonalMemoryConflictError,
    PersonalMemoryLifecycleError,
    PersonalMemoryNotFoundError,
    PersonalMemoryProtectionError,
)
from athena.model.adapters.lm_studio import ModelProviderError
from athena.operations.cli import (
    OperationalCommandError,
    run_operational_command,
)
from athena.retrieval.archive import ArchiveSearchError
from athena.retrieval.context import ContextBuilderError
from athena.retrieval.degradation import (
    SemanticRetrievalUnavailableError,
)
from athena.retrieval.search import SearchEntityType, SearchError
from athena.retrieval.semantic import SemanticSearchError
from athena.source.analysis_repository import SourceAnalysisNotFoundError
from athena.source.anchor_repository import SourceAnchorNotFoundError
from athena.source.anchor_service import SourceAnchorIntegrityError
from athena.source.blob_store import BlobStoreError
from athena.source.chunk_store import (
    SourceChunkNotFoundError,
    SourceChunkStoreError,
)
from athena.source.chunking_service import SourceChunkIntegrityError
from athena.source.repository import SourceActorError, SourceNotFoundError
from athena.source.representation_repository import SourceRepresentationNotFoundError
from athena.source.representation_store import TextRepresentationError
from athena.version import __version__


def _run_chat_command(app: AthenaApplication, args: argparse.Namespace) -> int:
    if args.chat_command == "new":
        chat_id = app.chat.create_chat()
        print(f"Chat created: {chat_id}")
        return 0

    if args.chat_command == "add":
        message = app.chat.add_user_message(
            chat_id=args.chat_id,
            content=args.content,
        )
        print(f"Message saved: {message.message_id}")
        print(f"Chat: {message.chat_id}")
        print(f"Sequence: {message.sequence_no}")
        return 0

    if args.chat_command == "send":
        if args.adaptive and (args.memory or args.sources):
            print(
                "ATHENA chat error: --adaptive cannot be combined with "
                "manual --memory or --sources routing.",
                file=sys.stderr,
            )
            return 2
        if (
            ((args.memory and args.sources) or args.adaptive)
            and args.memory_allow_model_prior is not None
            and args.source_allow_model_prior is not None
            and args.memory_allow_model_prior != args.source_allow_model_prior
        ):
            print(
                "ATHENA chat error: combined/adaptive retrieval received "
                "conflicting model-prior policies.",
                file=sys.stderr,
            )
            return 2
        if (
            not (args.memory or args.sources or args.adaptive)
            and args.embedding_model_id is not None
        ):
            print(
                "ATHENA chat error: --embedding-model requires --memory, "
                "--sources, or --adaptive.",
                file=sys.stderr,
            )
            return 2
        if (
            not (args.memory or args.adaptive)
            and args.memory_allow_model_prior is not None
        ):
            print(
                "ATHENA chat error: memory model-prior options require "
                "--memory or --adaptive.",
                file=sys.stderr,
            )
            return 2
        if (
            not (args.sources or args.adaptive)
            and args.source_allow_model_prior is not None
        ):
            print(
                "ATHENA chat error: source model-prior options require "
                "--sources or --adaptive.",
                file=sys.stderr,
            )
            return 2

        if not args.sources:
            explicit_memory = app.personal_memory.remember_explicit_chat_command(
                chat_id=args.chat_id,
                content=args.content,
                scope_kind=args.memory_scope_kind,
                scope_entity_id=args.memory_scope_id,
            )
            if explicit_memory is not None:
                revision = explicit_memory.memory_revision
                intent = explicit_memory.intent
                scope = intent.scope_kind.value
                if intent.scope_entity_id is not None:
                    scope = f"{scope}:{intent.scope_entity_id}"
                print(
                    "Personal Memory created from explicit chat command: "
                    f"{revision.memory_id}"
                )
                print(
                    f"User message saved: {explicit_memory.user_message.message_id}"
                )
                print(f"Revision: {revision.revision_no} ({revision.revision_id})")
                print(f"Kind: {intent.memory_kind.value}")
                print(f"Scope: {scope}")
                print(f"Content: {intent.memory_content}")
                print("Actor: user")
                print("Model signature: <none>")
                print("Primary Model calls: 0")
                print("Canonical Knowledge writes: 0")
                print("Canonical Claim writes: 0")
                return 0

            if is_explicit_persistence_command(args.content):
                user_message = app.chat.add_user_message(
                    chat_id=args.chat_id,
                    content=args.content,
                )
                print(
                    "ATHENA persistence routing: explicit save request is not "
                    "a clear Personal Memory collaboration preference.",
                    file=sys.stderr,
                )
                print(
                    "No Personal Memory or canonical Knowledge/Claim write was "
                    "performed.",
                    file=sys.stderr,
                )
                print(
                    "Natural-language Knowledge save routing is not implemented "
                    "in this slice.",
                    file=sys.stderr,
                )
                print(f"User message saved: {user_message.message_id}")
                print("Primary Model calls: 0")
                print("Personal Memory writes: 0")
                print("Canonical Knowledge writes: 0")
                print("Canonical Claim writes: 0")
                return 2

        print("Assistant: ", end="", flush=True)
        adaptive_result: AdaptiveChatResult | None = None
        memory_result: MemoryChatGenerationResult | None = None
        source_result: SourceGroundedChatResult | None = None
        unified_result: UnifiedLocalChatResult | None = None
        try:
            if args.adaptive:
                adaptive_allow_model_prior = True
                if args.memory_allow_model_prior is not None:
                    adaptive_allow_model_prior = args.memory_allow_model_prior
                if args.source_allow_model_prior is not None:
                    adaptive_allow_model_prior = args.source_allow_model_prior

                adaptive_result = app.adaptive_chat.send_message(
                    chat_id=args.chat_id,
                    content=args.content,
                    requested_model_id=args.model_id,
                    requested_embedding_model_id=args.embedding_model_id,
                    max_memory_context_tokens=args.memory_max_tokens,
                    max_memory_context_items=args.memory_max_items,
                    max_memory_items=args.memory_max_preferences,
                    max_source_context_tokens=args.source_max_tokens,
                    max_source_context_items=args.source_max_items,
                    memory_scope_kind=args.memory_scope_kind,
                    memory_scope_entity_id=args.memory_scope_id,
                    effective_context_limit=args.memory_context_limit,
                    output_reserve=args.memory_output_reserve,
                    safety_margin=args.memory_safety_margin,
                    allow_model_prior=adaptive_allow_model_prior,
                    on_delta=lambda chunk: print(chunk, end="", flush=True),
                )
                result = adaptive_result.generation

                # Preserve the concrete delegated result for the common
                # diagnostics below. Adaptive routing must expose the same
                # retrieval/context observability as selecting that hardened
                # chat path explicitly.
                memory_result = adaptive_result.memory_result
                source_result = adaptive_result.source_result
                unified_result = adaptive_result.unified_result
            elif args.memory and args.sources:
                unified_allow_model_prior = True
                if args.memory_allow_model_prior is not None:
                    unified_allow_model_prior = args.memory_allow_model_prior
                if args.source_allow_model_prior is not None:
                    unified_allow_model_prior = args.source_allow_model_prior

                unified_result = app.unified_local_chat.send_message(
                    chat_id=args.chat_id,
                    content=args.content,
                    requested_model_id=args.model_id,
                    requested_embedding_model_id=args.embedding_model_id,
                    max_memory_context_tokens=args.memory_max_tokens,
                    max_memory_context_items=args.memory_max_items,
                    max_memory_items=args.memory_max_preferences,
                    max_source_context_tokens=args.source_max_tokens,
                    max_source_context_items=args.source_max_items,
                    memory_scope_kind=args.memory_scope_kind,
                    memory_scope_entity_id=args.memory_scope_id,
                    effective_context_limit=args.memory_context_limit,
                    output_reserve=args.memory_output_reserve,
                    safety_margin=args.memory_safety_margin,
                    allow_model_prior=unified_allow_model_prior,
                    on_delta=lambda chunk: print(chunk, end="", flush=True),
                )
                result = unified_result.generation
            elif args.memory:
                memory_result = app.memory_chat.send_message(
                    chat_id=args.chat_id,
                    content=args.content,
                    requested_model_id=args.model_id,
                    requested_embedding_model_id=args.embedding_model_id,
                    max_context_tokens=args.memory_max_tokens,
                    max_context_items=args.memory_max_items,
                    max_memory_items=args.memory_max_preferences,
                    memory_scope_kind=args.memory_scope_kind,
                    memory_scope_entity_id=args.memory_scope_id,
                    effective_context_limit=args.memory_context_limit,
                    output_reserve=args.memory_output_reserve,
                    safety_margin=args.memory_safety_margin,
                    allow_model_prior=(
                        True
                        if args.memory_allow_model_prior is None
                        else args.memory_allow_model_prior
                    ),
                    on_delta=lambda chunk: print(chunk, end="", flush=True),
                )
                result = memory_result.generation
            elif args.sources:
                source_result = app.source_grounded_chat.send_message(
                    chat_id=args.chat_id,
                    content=args.content,
                    requested_model_id=args.model_id,
                    requested_embedding_model_id=args.embedding_model_id,
                    max_context_tokens=args.source_max_tokens,
                    max_context_items=args.source_max_items,
                    allow_model_prior=(
                        True
                        if args.source_allow_model_prior is None
                        else args.source_allow_model_prior
                    ),
                    on_delta=lambda chunk: print(chunk, end="", flush=True),
                )
                result = source_result.generation
            else:
                direct_result = app.direct_chat.send_message(
                    chat_id=args.chat_id,
                    content=args.content,
                    requested_model_id=args.model_id,
                    on_delta=lambda chunk: print(chunk, end="", flush=True),
                )
                result = direct_result.generation
        except KeyboardInterrupt:
            print()
            print(
                "Generation cancelled. User message remains saved if generation "
                "had already started; partial assistant text was not persisted.",
                file=sys.stderr,
            )
            return 130
        print()
        print(f"Model: {result.model.backend_model_id}")
        if adaptive_result is not None:
            plan = adaptive_result.plan
            print(
                "Adaptive retrieval: "
                f"mode={plan.mode.value} "
                f"reason={plan.reason.value} "
                f"probe={'yes' if plan.probe_query is not None else 'no'} "
                f"canonical_hit={plan.canonical_probe_hit} "
                f"research_hit={plan.research_probe_hit} "
                f"news_hit={plan.news_probe_hit} "
                f"archive_hit={plan.archive_probe_hit} "
                f"contextualized={adaptive_result.contextualized} "
                f"anchor="
                f"{adaptive_result.context_anchor_message_id or '<none>'}"
            )
            for warning in plan.warnings:
                print(
                    f"Adaptive retrieval warning: {warning}",
                    file=sys.stderr,
                )

            grounding = result.grounding_report
            if grounding is not None:
                cited = ", ".join(
                    grounding.cited_context_ids
                ) or "<none>"
                print(
                    "Grounding: "
                    f"cited={cited} "
                    f"canonical={len(grounding.canonical_context_ids)} "
                    f"user_statements="
                    f"{len(grounding.user_statement_context_ids)} "
                    f"conversation="
                    f"{len(grounding.conversation_context_ids)} "
                    f"sources={len(grounding.source_context_ids)} "
                    f"research={len(grounding.research_context_ids)} "
                    f"news={len(grounding.news_context_ids)} "
                    f"inference={grounding.uses_inference} "
                    f"model_prior={grounding.uses_model_prior} "
                    f"unknown={grounding.uses_unknown}"
                )
        if unified_result is not None:
            unified_embedding_label = (
                unified_result.embedding_model.backend_model_id
                if unified_result.embedding_model is not None
                else "<lexical-fallback>"
            )
            print(
                "Unified local context: "
                f"memory_items={len(unified_result.memory_context.items)} "
                f"memory_preferences="
                f"{len(unified_result.memory_context.memory_items)} "
                f"source_items={len(unified_result.source_context.items)} "
                f"embedding_model={unified_embedding_label}"
            )
            print(
                "Unified context budgets: "
                f"memory={unified_result.budget.memory_context_budget} "
                f"source={unified_result.budget.source_context_budget} "
                f"input={unified_result.budget.estimated_input_tokens} "
                f"output_reserve={unified_result.budget.output_reserve} "
                f"safety_margin={unified_result.budget.safety_margin} "
                f"total={unified_result.budget.estimated_total_tokens}/"
                f"{unified_result.budget.effective_context_limit}"
            )
            memory_ids = ", ".join(
                item.context_id
                for item in unified_result.memory_context.items
            ) or "<none>"
            source_refs = ", ".join(
                f"{item.context_id}={item.anchor_id}"
                for item in unified_result.source_context.items
            ) or "<none>"
            print(f"Unified memory context IDs: {memory_ids}")
            print(f"Unified source context anchors: {source_refs}")

            evidence_counts = ", ".join(
                f"{evidence_class.value}:{count}"
                for evidence_class, count
                in unified_result.evidence_selection.counts
            ) or "<none>"
            print(
                "Unified memory evidence: "
                f"policy={unified_result.evidence_selection.policy_id} "
                f"classes={evidence_counts}"
            )

            grounding = result.grounding_report
            if grounding is not None:
                cited = ", ".join(grounding.cited_context_ids) or "<none>"
                print(
                    "Grounding: "
                    f"cited={cited} "
                    f"canonical={len(grounding.canonical_context_ids)} "
                    f"user_statements="
                    f"{len(grounding.user_statement_context_ids)} "
                    f"conversation="
                    f"{len(grounding.conversation_context_ids)} "
                    f"sources={len(grounding.source_context_ids)} "
                    f"inference={grounding.uses_inference} "
                    f"model_prior={grounding.uses_model_prior} "
                    f"unknown={grounding.uses_unknown}"
                )

        if memory_result is not None:
            memory_embedding_label = (
                memory_result.embedding_model.backend_model_id
                if memory_result.embedding_model is not None
                else "<lexical-fallback>"
            )
            print(
                "Memory context: "
                f"preferences={len(memory_result.context.memory_items)} "
                f"preferences_omitted={memory_result.context.omitted_memory_count} "
                f"items={len(memory_result.context.items)} "
                f"omitted={memory_result.context.omitted_count} "
                f"estimated_tokens={memory_result.context.estimated_tokens}/"
                f"{memory_result.context.max_estimated_tokens} "
                f"embedding_model={memory_embedding_label}"
            )
            print(
                "Context budget: "
                f"input={memory_result.budget.estimated_input_tokens} "
                f"output_reserve={memory_result.budget.output_reserve} "
                f"safety_margin={memory_result.budget.safety_margin} "
                f"total={memory_result.budget.estimated_total_tokens}/"
                f"{memory_result.budget.effective_context_limit}"
            )
            if memory_result.context.items:
                ids = ", ".join(
                    item.context_id for item in memory_result.context.items
                )
                print(f"Memory context IDs: {ids}")
            evidence_counts = ", ".join(
                f"{evidence_class.value}:{count}"
                for evidence_class, count in memory_result.evidence_selection.counts
            ) or "<none>"
            print(
                "Memory evidence: "
                f"policy={memory_result.evidence_selection.policy_id} "
                f"classes={evidence_counts}"
            )
            grounding = result.grounding_report
            if grounding is not None:
                cited = ", ".join(grounding.cited_context_ids) or "<none>"
                print(
                    "Grounding: "
                    f"cited={cited} "
                    f"canonical={len(grounding.canonical_context_ids)} "
                    f"user_statements={len(grounding.user_statement_context_ids)} "
                    f"conversation={len(grounding.conversation_context_ids)} "
                    f"sources={len(grounding.source_context_ids)} "
                    f"inference={grounding.uses_inference} "
                    f"model_prior={grounding.uses_model_prior} "
                    f"unknown={grounding.uses_unknown}"
                )
        if source_result is not None:
            source_embedding_label = (
                source_result.embedding_model.backend_model_id
                if source_result.embedding_model is not None
                else "<lexical-fallback>"
            )
            print(
                "Source context: "
                f"items={len(source_result.context.items)} "
                f"omitted={source_result.context.omitted_count} "
                f"estimated_tokens={source_result.context.estimated_tokens}/"
                f"{source_result.context.max_estimated_tokens} "
                f"embedding_model={source_embedding_label}"
            )
            if source_result.context.items:
                refs = ", ".join(
                    f"{item.context_id}={item.anchor_id}"
                    for item in source_result.context.items
                )
                print(f"Source context anchors: {refs}")
            grounding = result.grounding_report
            if grounding is not None:
                cited = ", ".join(grounding.cited_context_ids) or "<none>"
                print(
                    "Grounding: "
                    f"cited={cited} "
                    f"canonical={len(grounding.canonical_context_ids)} "
                    f"user_statements={len(grounding.user_statement_context_ids)} "
                    f"conversation={len(grounding.conversation_context_ids)} "
                    f"sources={len(grounding.source_context_ids)} "
                    f"inference={grounding.uses_inference} "
                    f"model_prior={grounding.uses_model_prior} "
                    f"unknown={grounding.uses_unknown}"
                )
        print(f"Assistant message saved: {result.assistant_message.message_id}")
        return 0

    if args.chat_command == "show":
        _print_chat(app.chat.load_chat(args.chat_id))
        return 0

    if args.chat_command == "list":
        summaries = app.chat.list_chats(limit=args.limit)
        if not summaries:
            print("No persistent chats.")
            return 0
        for summary in summaries:
            print(
                f"{summary.chat_id}  state={summary.lifecycle_state}  "
                f"messages={summary.message_count}"
            )
        return 0

    raise RuntimeError(f"Unsupported chat command: {args.chat_command!r}")


def _run_knowledge_command(app: AthenaApplication, args: argparse.Namespace) -> int:
    if args.knowledge_command == "promote":
        revision = app.knowledge.promote_chat_message(
            chat_id=args.chat_id,
            sequence_no=args.sequence_no,
            knowledge_kind=args.kind,
            title=args.title,
            epistemic_status=args.status,
        )
        print(f"Knowledge created: {revision.knowledge_id}")
        print(f"Revision: {revision.revision_no} ({revision.revision_id})")
        print(f"Provenance: {revision.provenance_id}")
        return 0

    if args.knowledge_command == "show":
        _print_knowledge(app, app.knowledge.load(args.knowledge_id))
        return 0

    if args.knowledge_command == "history":
        revisions = app.knowledge.history(args.knowledge_id)
        print(f"Knowledge: {args.knowledge_id}")
        print(f"Revisions: {len(revisions)}")
        for revision in revisions:
            inputs = app.knowledge.provenance_inputs(revision.provenance_id)
            print(
                f"[{revision.revision_no}] revision={revision.revision_id} "
                f"kind={revision.payload.knowledge_kind.value} "
                f"status={revision.payload.epistemic_status.value} "
                f"inputs={len(inputs)} body={revision.payload.body}"
            )
        return 0

    if args.knowledge_command == "revise":
        revision = app.knowledge.revise(
            knowledge_id=args.knowledge_id,
            body=args.body,
            title=args.title,
            knowledge_kind=args.kind,
            epistemic_status=args.status,
        )
        print(f"Knowledge revised: {revision.knowledge_id}")
        print(f"Revision: {revision.revision_no} ({revision.revision_id})")
        print(f"Provenance: {revision.provenance_id}")
        return 0

    if args.knowledge_command == "list":
        snapshots = app.knowledge.list(limit=args.limit)
        if not snapshots:
            print("No canonical KnowledgeUnits.")
            return 0
        for snapshot in snapshots:
            revision = snapshot.revision
            title = revision.payload.title or "<untitled>"
            print(
                f"{snapshot.knowledge_id}  rev={revision.revision_no}  "
                f"kind={revision.payload.knowledge_kind.value}  title={title}"
            )
        return 0

    raise RuntimeError(f"Unsupported knowledge command: {args.knowledge_command!r}")




def _run_memory_command(app: AthenaApplication, args: argparse.Namespace) -> int:
    if args.memory_command == "remember":
        revision = app.personal_memory.remember(
            content=args.content,
            memory_kind=args.kind,
            scope_kind=args.scope_kind,
            scope_entity_id=args.scope_id,
            sensitivity=args.sensitivity,
        )
        print(f"Personal Memory created: {revision.memory_id}")
        print(f"Revision: {revision.revision_no} ({revision.revision_id})")
        print(f"Provenance: {revision.provenance_id}")
        print("Actor: user")
        print("Model signature: <none>")
        return 0

    if args.memory_command == "show":
        _print_personal_memory(app.personal_memory.load(args.memory_id))
        return 0

    if args.memory_command == "history":
        revisions = app.personal_memory.history(args.memory_id)
        print(f"Memory: {args.memory_id}")
        print(f"Revisions: {len(revisions)}")
        for revision in revisions:
            payload = revision.payload
            scope = payload.scope_kind.value
            if payload.scope_entity_id is not None:
                scope = f"{scope}:{payload.scope_entity_id}"
            print(
                f"[{revision.revision_no}] revision={revision.revision_id} "
                f"kind={payload.memory_kind.value} scope={scope} "
                f"sensitivity={payload.sensitivity.value} content={payload.content}"
            )
        return 0

    if args.memory_command == "list":
        snapshots = app.personal_memory.list(
            limit=args.limit, include_inactive=args.include_inactive
        )
        if not snapshots:
            print("No active Personal Memory.")
            return 0
        for snapshot in snapshots:
            payload = snapshot.revision.payload
            scope = payload.scope_kind.value
            if payload.scope_entity_id is not None:
                scope = f"{scope}:{payload.scope_entity_id}"
            print(
                f"{snapshot.memory_id}  state={snapshot.lifecycle_state} "
                f"rev={snapshot.revision.revision_no} kind={payload.memory_kind.value} "
                f"scope={scope} content={payload.content}"
            )
        return 0

    if args.memory_command == "revise":
        revision = app.personal_memory.revise(
            memory_id=args.memory_id,
            content=args.content,
            memory_kind=args.kind,
            scope_kind=args.scope_kind,
            scope_entity_id=args.scope_id,
            sensitivity=args.sensitivity,
        )
        print(f"Personal Memory revised: {revision.memory_id}")
        print(f"Revision: {revision.revision_no} ({revision.revision_id})")
        print(f"Provenance: {revision.provenance_id}")
        return 0

    if args.memory_command == "confirm":
        revision = app.personal_memory.confirm(args.memory_id)
        print(f"Personal Memory confirmed: {revision.memory_id}")
        print(f"Revision: {revision.revision_no} ({revision.revision_id})")
        return 0

    if args.memory_command in {"disable", "enable", "delete"}:
        operation = getattr(app.personal_memory, args.memory_command)
        commit_id = operation(args.memory_id)
        print(f"Personal Memory {args.memory_command}: {args.memory_id}")
        print(f"Commit: {commit_id if commit_id is not None else '<no-op>'}")
        return 0

    if args.memory_command == "reset":
        if not args.yes:
            print("Personal Memory reset requires --yes. Canonical writes: 0")
            return 2
        result = app.personal_memory.reset()
        print(f"Personal Memory reset: {result.deleted_count} entries")
        print(f"Commit: {result.commit_id if result.commit_id is not None else '<none>'}")
        print("Knowledge/Raw Archive writes: 0")
        return 0

    raise RuntimeError(f"Unsupported memory command: {args.memory_command!r}")

def _run_claim_command(app: AthenaApplication, args: argparse.Namespace) -> int:
    if args.claim_command == "promote":
        revision = app.claims.promote_chat_message(
            chat_id=args.chat_id,
            sequence_no=args.sequence_no,
            claim_kind=args.kind,
            epistemic_status=args.status,
            valid_from_us=args.valid_from_us,
            valid_to_us=args.valid_to_us,
        )
        print(f"Claim created: {revision.claim_id}")
        print(f"Revision: {revision.revision_no} ({revision.revision_id})")
        print(f"Provenance: {revision.provenance_id}")
        return 0

    if args.claim_command == "show":
        _print_claim(app, app.claims.load(args.claim_id))
        return 0

    if args.claim_command == "history":
        revisions = app.claims.history(args.claim_id)
        print(f"Claim: {args.claim_id}")
        print(f"Revisions: {len(revisions)}")
        for revision in revisions:
            print(
                f"[{revision.revision_no}] revision={revision.revision_id} "
                f"kind={revision.payload.claim_kind.value} "
                f"status={revision.payload.epistemic_status.value} "
                f"statement={revision.payload.statement}"
            )
        return 0

    if args.claim_command == "revise":
        revision = app.claims.revise(
            claim_id=args.claim_id,
            statement=args.statement,
            claim_kind=args.kind,
            epistemic_status=args.status,
        )
        print(f"Claim revised: {revision.claim_id}")
        print(f"Revision: {revision.revision_no} ({revision.revision_id})")
        print(f"Provenance: {revision.provenance_id}")
        return 0

    if args.claim_command == "contradict":
        left, right = app.claims.mark_contradiction(
            left_claim_id=args.left_claim_id,
            right_claim_id=args.right_claim_id,
        )
        print(f"Contradiction linked: {args.left_claim_id} <-> {args.right_claim_id}")
        print(f"Left provenance: {left.provenance_id}")
        print(f"Right provenance: {right.provenance_id}")
        return 0

    if args.claim_command == "list":
        snapshots = app.claims.list(limit=args.limit)
        if not snapshots:
            print("No canonical Claims.")
            return 0
        for snapshot in snapshots:
            revision = snapshot.revision
            print(
                f"{snapshot.claim_id}  rev={revision.revision_no}  "
                f"kind={revision.payload.claim_kind.value}  "
                f"status={revision.payload.epistemic_status.value}  "
                f"statement={revision.payload.statement}"
            )
        return 0

    raise RuntimeError(f"Unsupported claim command: {args.claim_command!r}")




def _accept_extraction_result(
    app: AthenaApplication,
    result: ChatExtractionResult,
) -> int:
    plan = app.proposal_acceptance.preflight(result)
    knowledge_reuse = sum(1 for item in plan.knowledge if item.action.value != "create")
    claim_reuse = sum(1 for item in plan.claims if item.action.value != "create")
    print(
        "Dedup preflight: "
        f"knowledge_create={len(plan.knowledge) - knowledge_reuse} "
        f"knowledge_reuse={knowledge_reuse} "
        f"claim_create={len(plan.claims) - claim_reuse} "
        f"claim_reuse={claim_reuse}"
    )
    if plan.merge_candidates:
        print(f"Canonical merge candidates: {len(plan.merge_candidates)}")
        for index, candidate in enumerate(plan.merge_candidates):
            print(
                f"[DM{index}] {candidate.proposal_type.value}[{candidate.proposal_index}] "
                f"~ {candidate.existing_entity_id} similarity={candidate.similarity:.3f} "
                f"reason={candidate.reason}"
            )
        review_ids = app.proposal_acceptance.queue_merge_reviews(result, plan)
        print("Acceptance blocked: persistent merge review required.")
        for review_id in review_ids:
            print(f"  MERGE REVIEW -> {review_id}")
        print("Use 'athena review show <id>' then choose 'merge' or 'keep-separate'.")
        print(
            "After resolving reviews, run: "
            f"athena extract accept-run {result.processing_run.processing_run_id}"
        )
        return 2

    answer = input("Accept ALL displayed proposals after deduplication? [y/N] ").strip().lower()
    if answer not in {"y", "yes"}:
        print("Acceptance cancelled. Canonical writes: 0")
        return 0

    accepted = app.proposal_acceptance.accept_all(result, expected_plan=plan)
    print(f"Canonical commit: {accepted.commit_id}")
    print(
        f"Knowledge resolved: {len(accepted.knowledge_ids)} "
        f"(created={len(accepted.knowledge_created_ids)} "
        f"reused={len(accepted.knowledge_reused_ids)})"
    )
    for knowledge_id in accepted.knowledge_ids:
        print(f"  K -> {knowledge_id}")
    print(
        f"Claims resolved: {len(accepted.claim_ids)} "
        f"(created={len(accepted.claim_created_ids)} "
        f"reused={len(accepted.claim_reused_ids)})"
    )
    for claim_id in accepted.claim_ids:
        print(f"  C -> {claim_id}")
    print(f"Contradictions committed: {len(accepted.contradiction_pairs)}")
    print(f"Contradictions reused: {len(accepted.contradiction_pairs_reused)}")
    print(f"Contradictions queued for review: {len(accepted.contradiction_review_ids)}")
    if accepted.contradiction_review_ids:
        print("All model-proposed contradictions require review in Step 7.")
        for review_id in accepted.contradiction_review_ids:
            print(f"  REVIEW -> {review_id}")
    return 0




def _accept_source_extraction_result(
    app: AthenaApplication,
    result: SourceAnalysisExtractionResult,
) -> int:
    plan = app.source_proposal_acceptance.preflight(result)
    knowledge_reuse = sum(1 for item in plan.knowledge if item.action.value != "create")
    claim_reuse = sum(1 for item in plan.claims if item.action.value != "create")
    print(
        "Dedup preflight: "
        f"knowledge_create={len(plan.knowledge) - knowledge_reuse} "
        f"knowledge_reuse={knowledge_reuse} "
        f"claim_create={len(plan.claims) - claim_reuse} "
        f"claim_reuse={claim_reuse}"
    )
    keep_separate = False
    if plan.merge_candidates:
        print(f"Canonical near-duplicate candidates: {len(plan.merge_candidates)}")
        for index, candidate in enumerate(plan.merge_candidates):
            print(
                f"[DM{index}] {candidate.proposal_type.value}[{candidate.proposal_index}] "
                f"~ {candidate.existing_entity_id} similarity={candidate.similarity:.3f} "
                f"reason={candidate.reason}"
            )
        answer = input(
            "Keep ALL displayed near-duplicate proposals separate and continue? [y/N] "
        ).strip().lower()
        if answer not in {"y", "yes"}:
            print("Acceptance blocked. Canonical writes: 0")
            return 2
        keep_separate = True

    answer = input("Accept ALL displayed grounded source proposals? [y/N] ").strip().lower()
    if answer not in {"y", "yes"}:
        print("Acceptance cancelled. Canonical writes: 0")
        return 0

    accepted = app.source_proposal_acceptance.accept_all(
        result,
        expected_plan=plan,
        keep_separate_near_duplicates=keep_separate,
    )
    print(f"Canonical commit: {accepted.commit_id}")
    print(
        f"Knowledge resolved: {len(accepted.knowledge_ids)} "
        f"(created={len(accepted.knowledge_created_ids)} reused={len(accepted.knowledge_reused_ids)})"
    )
    for knowledge_id in accepted.knowledge_ids:
        print(f"  K -> {knowledge_id}")
    print(
        f"Claims resolved: {len(accepted.claim_ids)} "
        f"(created={len(accepted.claim_created_ids)} reused={len(accepted.claim_reused_ids)})"
    )
    for claim_id in accepted.claim_ids:
        print(f"  C -> {claim_id}")
    print(f"Contradictions queued for review: {len(accepted.contradiction_review_ids)}")
    for review_id in accepted.contradiction_review_ids:
        print(f"  REVIEW -> {review_id}")
    return 0


def _run_extract_command(app: AthenaApplication, args: argparse.Namespace) -> int:
    if args.extract_command == "chat":
        chat_result = app.extraction.extract_chat(
            chat_id=args.chat_id,
            requested_model_id=args.model_id,
        )
        _print_extraction(chat_result)
        print(f"Frozen extraction run: {chat_result.processing_run.processing_run_id}")
        if not args.accept:
            return 0
        return _accept_extraction_result(app, chat_result)

    if args.extract_command == "accept-run":
        try:
            frozen_chat_result = app.extraction_snapshots.load(args.processing_run_id)
        except ExtractionSnapshotNotFoundError as exc:
            print(f"ATHENA extraction snapshot error: {exc}", file=sys.stderr)
            return 2
        print("Loaded frozen extraction proposal snapshot; Primary Model was not called.")
        _print_extraction(frozen_chat_result)
        return _accept_extraction_result(app, frozen_chat_result)

    if args.extract_command == "source-analysis":
        source_result = app.source_extraction.extract_analysis(
            analysis_id=args.analysis_id,
            requested_model_id=args.model_id,
            context_limit=args.context_limit,
            output_reserve=args.output_reserve,
            safety_margin=args.safety_margin,
        )
        _print_source_extraction(source_result)
        print(f"Frozen source extraction run: {source_result.processing_run.processing_run_id}")
        if not args.accept:
            return 0
        return _accept_source_extraction_result(app, source_result)

    if args.extract_command == "accept-source-run":
        try:
            frozen_source_result = app.source_extraction_snapshots.load(args.processing_run_id)
        except SourceExtractionSnapshotNotFoundError as exc:
            print(f"ATHENA source extraction snapshot error: {exc}", file=sys.stderr)
            return 2
        print("Loaded frozen source extraction proposal snapshot; Primary Model was not called.")
        _print_source_extraction(frozen_source_result)
        return _accept_source_extraction_result(app, frozen_source_result)

    raise RuntimeError(f"Unsupported extraction command: {args.extract_command!r}")




def _run_review_command(app: AthenaApplication, args: argparse.Namespace) -> int:
    if args.review_command == "list":
        items = app.reviews.list_pending(
            review_type=args.review_type,
            limit=args.limit,
        )
        print(f"Pending reviews: {len(items)}")
        print("Policy: all model-proposed contradictions require review.")
        for item in items:
            print(
                f"{item.review_id} type={item.review_type} "
                f"confidence={item.confidence:.3f} "
                f"left={item.left_entity_id} right={item.right_entity_id}"
            )
        return 0

    if args.review_command == "show":
        item = app.reviews.get(args.review_id)
        _print_review_item(item)
        if item.review_type == "merge_candidate":
            details = app.reviews.merge_details(args.review_id)
            print(f"Proposal type: {details.proposal_type.value}")
            print(f"Proposal index: {details.proposal_index}")
            print(f"Proposal text: {details.proposal_text}")
            print(f"Proposal kind: {details.proposal_kind}")
            print(f"Proposal status: {details.proposal_epistemic_status}")
            print(f"Similarity: {details.similarity:.3f}")
            print(f"Canonical target: {details.existing_entity_id}")
            print(f"Canonical target revision: {details.existing_revision_id}")
            print(f"Merge decision: {details.decision or '<pending>'}")
        return 0

    actor_id = app.chat.ensure_local_user()

    if args.review_command == "accept":
        item = app.reviews.accept(args.review_id, actor_id=actor_id)
        print(f"Review accepted: {item.review_id}")
        return 0

    if args.review_command == "reject":
        item = app.reviews.reject(args.review_id, actor_id=actor_id)
        print(f"Review rejected: {item.review_id}")
        return 0

    if args.review_command == "merge":
        item = app.reviews.resolve_merge(
            args.review_id,
            actor_id=actor_id,
            decision="merge",
        )
        print(f"Merge review resolved: {item.review_id} -> merge")
        print("Rerun the original extraction acceptance to apply the decision atomically.")
        return 0

    if args.review_command == "keep-separate":
        item = app.reviews.resolve_merge(
            args.review_id,
            actor_id=actor_id,
            decision="keep_separate",
        )
        print(f"Merge review resolved: {item.review_id} -> keep_separate")
        print("Rerun the original extraction acceptance to apply the decision atomically.")
        return 0

    if args.review_command == "accept-all":
        review_ids = app.reviews.accept_all(
            actor_id=actor_id,
            review_type=args.review_type,
            min_confidence=args.min_confidence,
        )
        print(f"Reviews accepted: {len(review_ids)}")
        for review_id in review_ids:
            print(f"  REVIEW -> {review_id}")
        return 0

    raise RuntimeError(f"Unsupported review command: {args.review_command!r}")




def _resolve_embedding_model_id(
    app: AthenaApplication,
    requested_model_id: str | None,
) -> str:
    model = app.embedding_provider.resolve_model(requested_model_id)
    return model.backend_model_id


def _run_embedding_command(app: AthenaApplication, args: argparse.Namespace) -> int:
    if args.embedding_command == "models":
        models = app.embedding_provider.discover_embedding_models()
        print(f"Embedding models: {len(models)}")
        for model in models:
            state = "loaded" if model.loaded else "available"
            quant = "" if model.quantization is None else f" quant={model.quantization}"
            print(
                f"- {model.backend_model_id} [{state}] "
                f"display={model.display_name!r}{quant}"
            )
        return 0

    model_id = _resolve_embedding_model_id(app, args.embedding_model)

    if args.embedding_command == "status":
        status = app.semantic_search.status(model_id)
        if status is None:
            print(f"Embedding index: absent model={model_id}")
            return 0
        print(
            f"Embedding index: model={model_id} current={status.current} "
            f"documents={status.document_count} dimensions={status.dimensions} "
            f"indexed_commit_seq={status.indexed_commit_seq} "
            f"current_commit_seq={status.current_commit_seq} "
            f"hnsw_ready={status.hnsw_ready}"
        )
        return 0

    if args.embedding_command == "rebuild":
        status = app.semantic_search.rebuild(model_id)
        print(
            f"Embedding index rebuilt: model={model_id} "
            f"documents={status.document_count} dimensions={status.dimensions} "
            f"commit_seq={status.indexed_commit_seq} hnsw_ready={status.hnsw_ready}"
        )
        return 0

    raise RuntimeError(
        f"Unsupported embedding command: {args.embedding_command!r}"
    )


def _run_context_command(app: AthenaApplication, args: argparse.Namespace) -> int:
    if args.context_command != "build":
        raise RuntimeError(f"Unsupported context command: {args.context_command!r}")

    entity_type = (
        None
        if args.context_type is None
        else SearchEntityType(args.context_type)
    )
    candidate_limit = min(200, max(40, args.max_items * 8))

    if args.hybrid:
        model_id = _resolve_embedding_model_id(app, args.embedding_model)
        hybrid_results = app.hybrid_retrieval.search(
            args.query,
            model_id=model_id,
            limit=candidate_limit,
            entity_type=entity_type,
        )
        bundle = app.context_builder.build_from_hybrid(
            query=args.query,
            results=hybrid_results,
            max_estimated_tokens=args.max_tokens,
            max_items=args.max_items,
        )
        model_suffix = f" embedding_model={model_id}"
    else:
        ranked_results = app.retrieval.search(
            args.query,
            limit=candidate_limit,
            entity_type=entity_type,
        )
        bundle = app.context_builder.build_from_ranked(
            query=args.query,
            results=ranked_results,
            max_estimated_tokens=args.max_tokens,
            max_items=args.max_items,
        )
        model_suffix = ""

    print(
        f"Context bundle: mode={bundle.mode} items={len(bundle.items)} "
        f"omitted={bundle.omitted_count} "
        f"estimated_tokens={bundle.estimated_tokens}/"
        f"{bundle.max_estimated_tokens}{model_suffix}"
    )
    print(bundle.rendered_text)
    return 0

def _run_search_command(app: AthenaApplication, args: argparse.Namespace) -> int:
    if args.rebuild:
        count = app.search.rebuild()
        print(f"Search index rebuilt: {count} current unprotected documents")

    entity_type = (
        None
        if args.search_type is None
        else SearchEntityType(args.search_type)
    )

    if args.hybrid:
        if args.raw:
            print(
                "ATHENA search error: --hybrid and --raw cannot be combined.",
                file=sys.stderr,
            )
            return 2
        model_id = _resolve_embedding_model_id(app, args.embedding_model)
        hybrid_results = app.hybrid_retrieval.search(
            args.query,
            model_id=model_id,
            limit=args.limit,
            entity_type=entity_type,
        )
        print(
            f"Hybrid retrieval results: {len(hybrid_results)} "
            f"embedding_model={model_id}"
        )
        for index, hybrid_result in enumerate(hybrid_results, start=1):
            title = (
                ""
                if hybrid_result.title is None
                else f" title={hybrid_result.title!r}"
            )
            print(
                f"[{index}] type={hybrid_result.entity_type.value} "
                f"entity={hybrid_result.entity_id} "
                f"revision={hybrid_result.revision_id} "
                f"score={hybrid_result.score:.4f} "
                f"lexical_rrf={hybrid_result.lexical_score:.4f} "
                f"semantic_rrf={hybrid_result.semantic_score:.4f} "
                f"authority={hybrid_result.authority_score:.2f} "
                f"contradictions={hybrid_result.contradiction_count} "
                f"duplicates={hybrid_result.duplicate_count}{title}"
            )
            print(f"    {hybrid_result.text}")
        return 0

    if args.raw:
        raw_results = app.search.search(
            args.query,
            limit=args.limit,
            entity_type=entity_type,
        )
        print(f"Raw search results: {len(raw_results)}")
        for index, raw_result in enumerate(raw_results, start=1):
            title = (
                ""
                if raw_result.title is None
                else f" title={raw_result.title!r}"
            )
            print(
                f"[{index}] type={raw_result.entity_type.value} "
                f"entity={raw_result.entity_id} revision={raw_result.revision_id} "
                f"fts_score={raw_result.score:.6f} "
                f"contradictions={raw_result.contradiction_count}{title}"
            )
            print(f"    {raw_result.snippet}")
        return 0

    ranked_results = app.retrieval.search(
        args.query,
        limit=args.limit,
        entity_type=entity_type,
    )
    print(f"Retrieval results: {len(ranked_results)}")
    for index, ranked_result in enumerate(ranked_results, start=1):
        title = (
            ""
            if ranked_result.title is None
            else f" title={ranked_result.title!r}"
        )
        print(
            f"[{index}] type={ranked_result.entity_type.value} "
            f"entity={ranked_result.entity_id} revision={ranked_result.revision_id} "
            f"score={ranked_result.score:.4f} "
            f"lexical={ranked_result.lexical_score:.4f} "
            f"authority={ranked_result.authority_score:.2f} "
            f"contradictions={ranked_result.contradiction_count} "
            f"duplicates={ranked_result.duplicate_count}{title}"
        )
        print(f"    {ranked_result.snippet}")
    return 0








def _run_source_command(app: AthenaApplication, args: argparse.Namespace) -> int:
    if args.source_command == "import":
        result = app.sources.capture_file(args.path)
        print(f"Source captured: {result.source.source_id}")
        print(f"State: {result.source.lifecycle_state.value}")
        print(f"Blob: {result.blob.blob_id} reused={'yes' if result.reused_blob else 'no'}")
        print(f"Bytes: {result.blob.byte_length}")
        print(f"SHA-256: {result.source.content_sha256.hex()}")
        print(f"MIME: {result.source.mime_type or '<unknown>'}")
        print(
            f"Storage: {result.blob.storage_area.value}:"
            f"{result.blob.storage_locator}"
        )
        return 0

    if args.source_command == "show":
        source, blob = app.sources.get(args.source_id)
        _print_source_record(source, blob)
        return 0

    if args.source_command == "verify":
        source, blob = app.sources.get(args.source_id)
        path = app.sources.verify(args.source_id)
        print(
            f"Source verified: {source.source_id} "
            f"bytes={blob.byte_length} sha256={blob.integrity_sha256.hex()}"
        )
        print(f"Stored at: {path}")
        return 0

    if args.source_command == "list":
        sources = app.sources.list(limit=args.limit)
        if not sources:
            print("No captured Sources.")
            return 0
        for source, blob in sources:
            print(
                f"{source.source_id}  state={source.lifecycle_state.value} "
                f"type={source.source_type.value} bytes={blob.byte_length} "
                f"blob={blob.blob_id} name={source.original_name!r}"
            )
        return 0

    if args.source_command == "represent-text":
        build = app.source_text.build(args.source_id)
        representation = build.result.representation
        blob = build.result.blob
        print(f"Representation created: {representation.representation_id}")
        print(f"Source: {representation.source_id}")
        print(f"Type: {representation.representation_type.value}")
        print(f"Retention: {representation.retention_state.value}")
        print(f"ProcessingRun: {build.processing_run.processing_run_id}")
        print(f"Run status: {build.processing_run.status}")
        print(f"Blob: {blob.blob_id} reused={'yes' if build.result.reused_blob else 'no'}")
        print(f"Bytes: {blob.byte_length}")
        print(f"SHA-256: {representation.content_hash.hex()}")
        print(f"Storage: {blob.storage_area.value}:{blob.storage_locator}")
        return 0

    if args.source_command == "represent-pdf":
        pdf_build = app.source_pdf.build(args.source_id)
        representation = pdf_build.result.representation
        blob = pdf_build.result.blob
        print(f"Representation created: {representation.representation_id}")
        print(f"Source: {representation.source_id}")
        print(f"Type: {representation.representation_type.value}")
        print(f"Retention: {representation.retention_state.value}")
        print(f"ProcessingRun: {pdf_build.processing_run.processing_run_id}")
        print(f"Run status: {pdf_build.processing_run.status}")
        print(f"Parser: {representation.parser_id}@{representation.parser_version}")
        print(f"Pages: {len(pdf_build.pages)}")
        print(f"Blob: {blob.blob_id} reused={'yes' if pdf_build.result.reused_blob else 'no'}")
        print(f"Bytes: {blob.byte_length}")
        print(f"SHA-256: {representation.content_hash.hex()}")
        print(f"Storage: {blob.storage_area.value}:{blob.storage_locator}")
        return 0

    if args.source_command == "represent-docx":
        docx_build = app.source_docx.build(args.source_id)
        representation = docx_build.result.representation
        blob = docx_build.result.blob
        print(f"Representation created: {representation.representation_id}")
        print(f"Source: {representation.source_id}")
        print(f"Type: {representation.representation_type.value}")
        print(f"Retention: {representation.retention_state.value}")
        print(f"ProcessingRun: {docx_build.processing_run.processing_run_id}")
        print(f"Run status: {docx_build.processing_run.status}")
        print(f"Parser: {representation.parser_id}@{representation.parser_version}")
        print(f"Structures: {len(docx_build.structures)}")
        print(f"Blob: {blob.blob_id} reused={'yes' if docx_build.result.reused_blob else 'no'}")
        print(f"Bytes: {blob.byte_length}")
        print(f"SHA-256: {representation.content_hash.hex()}")
        print(f"Storage: {blob.storage_area.value}:{blob.storage_locator}")
        return 0

    if args.source_command == "represent-html":
        html_build = app.source_html.build(args.source_id)
        representation = html_build.result.representation
        blob = html_build.result.blob
        print(f"Representation created: {representation.representation_id}")
        print(f"Source: {representation.source_id}")
        print(f"Type: {representation.representation_type.value}")
        print(f"Retention: {representation.retention_state.value}")
        print(f"ProcessingRun: {html_build.processing_run.processing_run_id}")
        print(f"Run status: {html_build.processing_run.status}")
        print(f"Parser: {representation.parser_id}@{representation.parser_version}")
        print(f"Structures: {len(html_build.structures)}")
        print(f"Blob: {blob.blob_id} reused={'yes' if html_build.result.reused_blob else 'no'}")
        print(f"Bytes: {blob.byte_length}")
        print(f"SHA-256: {representation.content_hash.hex()}")
        print(f"Storage: {blob.storage_area.value}:{blob.storage_locator}")
        return 0

    if args.source_command == "representation-show":
        representation, blob = app.source_text.get(args.representation_id)
        _print_source_representation_record(representation, blob)
        return 0

    if args.source_command == "representation-verify":
        representation, blob = app.source_text.get(args.representation_id)
        path = app.source_text.verify(args.representation_id)
        print(
            f"Representation verified: {representation.representation_id} "
            f"bytes={blob.byte_length} sha256={representation.content_hash.hex()}"
        )
        print(f"Stored at: {path}")
        return 0

    if args.source_command == "representation-read":
        print(app.source_text.read_text(args.representation_id), end="")
        return 0

    if args.source_command == "representation-list":
        representations = app.source_text.list_for_source(
            args.source_id,
            limit=args.limit,
        )
        if not representations:
            print("No SourceRepresentations.")
            return 0
        for representation, blob in representations:
            print(
                f"{representation.representation_id}  "
                f"type={representation.representation_type.value} "
                f"retention={representation.retention_state.value} "
                f"bytes={blob.byte_length} blob={blob.blob_id} "
                f"run={representation.processing_run_id}"
            )
        return 0

    if args.source_command == "representation-pages":
        pages = app.source_text.list_pages(args.representation_id)
        if not pages:
            print("No retained page map for this SourceRepresentation.")
            return 0
        print(f"Representation pages: {len(pages)}")
        for page in pages:
            print(
                f"page={page.page_number} range={page.start_offset}:{page.end_offset} "
                f"sha256={page.content_hash.hex()}"
            )
        return 0

    if args.source_command == "representation-structures":
        structures = app.source_text.list_structures(args.representation_id)
        if not structures:
            print("No retained structure map for this SourceRepresentation.")
            return 0
        print(f"Representation structures: {len(structures)}")
        for item in structures:
            print(
                f"structure={item.structure_id} index={item.structure_index} "
                f"type={item.structure_type.value} path={item.path!r} "
                f"parent={item.parent_structure_id or '<none>'} "
                f"range={item.start_offset}:{item.end_offset} "
                f"sha256={item.content_hash.hex()} metadata={item.metadata_json}"
            )
        return 0

    if args.source_command == "chunk-text":
        chunk_build = app.source_chunks.build_default(args.representation_id)
        print(
            f"Chunk build completed: "
            f"{chunk_build.processing_run.processing_run_id}"
        )
        print(f"Run status: {chunk_build.processing_run.status}")
        print(f"Chunking profile: {chunk_build.profile.chunking_profile_id}")
        print(
            f"Profile: {chunk_build.profile.algorithm}@"
            f"{chunk_build.profile.profile_version} "
            f"target={chunk_build.profile.target_size} "
            f"overlap={chunk_build.profile.overlap_size}"
        )
        print(f"Build signature: {chunk_build.build_signature.hex()}")
        print(f"Chunks: {len(chunk_build.chunks)}")
        for chunk in chunk_build.chunks:
            print(
                f"{chunk.chunk_id} index={chunk.chunk_index} "
                f"range={chunk.start_anchor_value}:{chunk.end_anchor_value} "
                f"sha256={chunk.content_hash.hex()} uri={chunk.uri}"
            )
        return 0

    if args.source_command == "chunk-show":
        chunk = app.source_chunks.get(args.chunk_id)
        print(f"Chunk: {chunk.chunk_id}")
        print(f"URI: {chunk.uri}")
        print(f"Source: {chunk.source_id}")
        print(f"Representation: {chunk.representation_id}")
        print(f"Index: {chunk.chunk_index}")
        print(f"Profile: {chunk.chunking_profile_id}")
        print(f"Range: {chunk.start_anchor_value}:{chunk.end_anchor_value}")
        print(f"SHA-256: {chunk.content_hash.hex()}")
        print(f"ProcessingRun: {chunk.processing_run_id}")
        print(f"Build signature: {chunk.build_signature.hex()}")
        return 0

    if args.source_command == "chunk-verify":
        chunk = app.source_chunks.verify(args.chunk_id)
        print(
            f"Chunk verified: {chunk.chunk_id} index={chunk.chunk_index} "
            f"range={chunk.start_anchor_value}:{chunk.end_anchor_value} "
            f"sha256={chunk.content_hash.hex()}"
        )
        return 0

    if args.source_command == "chunk-read":
        chunk = app.source_chunks.verify(args.chunk_id)
        print(chunk.chunk_text, end="")
        return 0

    if args.source_command == "chunk-list":
        chunks = app.source_chunks.list_for_representation(
            args.representation_id,
            limit=args.limit,
        )
        if not chunks:
            print("No SourceChunks.")
            return 0
        for chunk in chunks:
            print(
                f"{chunk.chunk_id} index={chunk.chunk_index} "
                f"range={chunk.start_anchor_value}:{chunk.end_anchor_value} "
                f"profile={chunk.chunking_profile_id} run={chunk.processing_run_id}"
            )
        return 0

    if args.source_command == "anchor-from-chunk":
        anchor = app.source_anchors.materialize_chunk(args.chunk_id)
        _print_source_anchor(anchor)
        return 0

    if args.source_command == "anchor-from-structure":
        anchor = app.source_anchors.materialize_structure(args.structure_id)
        _print_source_anchor(anchor)
        print(f"Structure: {args.structure_id}")
        return 0

    if args.source_command == "anchor-create-text":
        anchor = app.source_anchors.materialize_text_range(
            args.representation_id,
            start_offset=args.start_offset,
            end_offset=args.end_offset,
        )
        _print_source_anchor(anchor)
        return 0

    if args.source_command == "anchor-show":
        _print_source_anchor(app.source_anchors.get(args.anchor_id))
        return 0

    if args.source_command == "anchor-verify":
        anchor = app.source_anchors.verify(args.anchor_id)
        print(
            f"SourceAnchor verified: {anchor.anchor_id} "
            f"source={anchor.source_id} representation={anchor.representation_id} "
            f"range={anchor.start_offset}:{anchor.end_offset} "
            f"quoted_sha256={anchor.quoted_hash.hex() if anchor.quoted_hash else '<none>'}"
        )
        return 0

    if args.source_command == "anchor-read":
        print(app.source_anchors.read_text(args.anchor_id), end="")
        return 0

    if args.source_command == "anchor-list":
        anchors = app.source_anchors.list_for_source(args.source_id, limit=args.limit)
        if not anchors:
            print("No SourceAnchors.")
            return 0
        for anchor in anchors:
            print(
                f"{anchor.anchor_id} type={anchor.anchor_type.value} "
                f"representation={anchor.representation_id} "
                f"range={anchor.start_offset}:{anchor.end_offset} "
                f"quoted_sha256={anchor.quoted_hash.hex() if anchor.quoted_hash else '<none>'}"
            )
        return 0

    if args.source_command == "search":
        if args.rebuild:
            count = app.archive_search.rebuild()
            print(f"Archive FTS rebuilt: {count} SourceChunks")
        if args.hybrid:
            model_id = _resolve_embedding_model_id(app, args.embedding_model)
            hybrid_results = app.archive_hybrid_retrieval.search(
                args.query,
                model_id=model_id,
                limit=args.limit,
                source_id=args.archive_source_id,
                representation_id=args.archive_representation_id,
            )
            print(
                f"Archive hybrid results: {len(hybrid_results)} "
                f"embedding_model={model_id}"
            )
            for index, hybrid_result in enumerate(hybrid_results, start=1):
                print(
                    f"[{index}] chunk={hybrid_result.chunk_id} "
                    f"source={hybrid_result.source_id} "
                    f"representation={hybrid_result.representation_id} "
                    f"index={hybrid_result.chunk_index} "
                    f"range={hybrid_result.start_anchor_value}:"
                    f"{hybrid_result.end_anchor_value} "
                    f"score={hybrid_result.score:.4f} "
                    f"lexical_rrf={hybrid_result.lexical_score:.4f} "
                    f"semantic_rrf={hybrid_result.semantic_score:.4f} "
                    f"sha256={hybrid_result.content_hash.hex()}"
                )
                print(f"    source_name={hybrid_result.source_name!r}")
                print(f"    {hybrid_result.text}")
            return 0

        archive_results = app.archive_search.search(
            args.query,
            limit=args.limit,
            source_id=args.archive_source_id,
            representation_id=args.archive_representation_id,
        )
        print(f"Archive search results: {len(archive_results)}")
        for index, archive_result in enumerate(archive_results, start=1):
            print(
                f"[{index}] chunk={archive_result.chunk_id} "
                f"source={archive_result.source_id} "
                f"representation={archive_result.representation_id} "
                f"index={archive_result.chunk_index} "
                f"range={archive_result.start_anchor_value}:"
                f"{archive_result.end_anchor_value} "
                f"fts_score={archive_result.score:.6f} "
                f"sha256={archive_result.content_hash.hex()}"
            )
            print(f"    source_name={archive_result.source_name!r}")
            print(f"    {archive_result.snippet}")
        return 0

    if args.source_command == "search-embedding-status":
        model_id = _resolve_embedding_model_id(app, args.embedding_model)
        status = app.archive_semantic_search.status(model_id)
        if status is None:
            print(f"Archive embedding index: absent model={model_id}")
            return 0
        print(
            f"Archive embedding index: model={model_id} current={status.current} "
            f"documents={status.document_count} dimensions={status.dimensions} "
            f"indexed_chunk_generation={status.indexed_chunk_generation} "
            f"current_chunk_generation={status.current_chunk_generation} "
            f"hnsw_ready={status.hnsw_ready}"
        )
        return 0

    if args.source_command == "search-embedding-rebuild":
        model_id = _resolve_embedding_model_id(app, args.embedding_model)
        status = app.archive_semantic_search.rebuild(model_id)
        print(
            f"Archive embedding index rebuilt: model={model_id} "
            f"documents={status.document_count} dimensions={status.dimensions} "
            f"chunk_generation={status.indexed_chunk_generation} "
            f"hnsw_ready={status.hnsw_ready}"
        )
        return 0

    raise RuntimeError(f"Unsupported source command: {args.source_command!r}")
















_SCHEDULER_SUPERVISOR_LANES = (
    SchedulerLane.CONTROL,
    SchedulerLane.PROVIDER,
)
_SCHEDULER_PARENT_LOST_EXIT_CODE = 70
_SCHEDULER_CHILD_START_TIMEOUT_SECONDS = 10.0
_SCHEDULER_CHILD_READY_TIMEOUT_SECONDS = 30.0 * 60.0


def _start_scheduler_supervisor_watchdog() -> None:
    """Terminate a scheduler child immediately when its supervisor pipe closes."""

    def watch_parent() -> None:
        try:
            while os.read(sys.stdin.fileno(), 1):
                pass
        except (OSError, ValueError):
            pass
        os._exit(_SCHEDULER_PARENT_LOST_EXIT_CODE)

    thread = threading.Thread(
        target=watch_parent,
        name="athena-scheduler-supervisor-watchdog",
        daemon=True,
    )
    thread.start()


def _scheduler_run_owned_lanes(
    lane: SchedulerLane,
) -> tuple[SchedulerLane, ...]:
    normalized_lane = SchedulerLane(lane)
    if normalized_lane is SchedulerLane.ALL:
        return _SCHEDULER_SUPERVISOR_LANES
    return (normalized_lane,)


def _scheduler_lane_lock_root(
    app: AthenaApplication,
) -> Path:
    """Return a runtime-specific lock root outside ATHENA canonical/runtime state."""
    local_root = str(app.paths.local_root.resolve())
    if os.name == "nt":
        local_root = os.path.normcase(local_root)
    runtime_key = hashlib.sha256(
        local_root.encode("utf-8")
    ).hexdigest()
    return (
        Path(tempfile.gettempdir())
        / "athena-scheduler-lanes"
        / runtime_key
    )


def _acquire_scheduler_run_lane_locks(
    app: AthenaApplication,
    lane: SchedulerLane,
) -> tuple[SchedulerLaneProcessLock, ...]:
    locks: list[SchedulerLaneProcessLock] = []
    lock_root = _scheduler_lane_lock_root(app)
    try:
        for owned_lane in _scheduler_run_owned_lanes(lane):
            locks.append(
                SchedulerLaneProcessLock.acquire(
                    lock_root / f"{owned_lane.value}.lock",
                    lane_name=owned_lane.value,
                )
            )
    except Exception:
        for lock in reversed(locks):
            lock.close()
        raise
    return tuple(locks)


def _scheduler_lane_command(
    args: argparse.Namespace,
    lane: SchedulerLane,
    *,
    supervised_child: bool,
    started_file: Path,
    ready_file: Path,
) -> list[str]:
    command = [
        sys.executable,
        "-m",
        "athena",
        "job",
        "scheduler-run",
        "--worker",
        f"{args.worker}-{lane.value}",
        "--lane",
        lane.value,
        "--started-file",
        str(started_file),
        "--ready-file",
        str(ready_file),
    ]
    if supervised_child:
        command.append("--supervised-child")
    command.append("--supervisor-watchdog")
    if args.max_ticks is not None:
        command.extend(
            [
                "--max-ticks",
                str(args.max_ticks),
            ]
        )
    return command


def _stop_scheduler_children(
    children: list[tuple[SchedulerLane, subprocess.Popen[bytes]]],
) -> None:
    for _lane, process in children:
        if process.poll() is None:
            process.terminate()

    for _lane, process in children:
        if process.poll() is not None:
            continue
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)


def _wait_scheduler_child_started(
    lane: SchedulerLane,
    process: subprocess.Popen[bytes],
    started_file: Path,
    *,
    timeout_seconds: float = _SCHEDULER_CHILD_START_TIMEOUT_SECONDS,
) -> None:
    """Require proof that the supervised child entered its startup boundary."""
    if timeout_seconds <= 0:
        raise ValueError(
            "Scheduler child start timeout must be positive."
        )

    deadline = time.monotonic() + timeout_seconds

    while not started_file.is_file():
        returncode = process.poll()

        if returncode is not None:
            raise JobSchedulerError(
                f"Scheduler {lane.value} lane exited with code "
                f"{returncode} before entering startup."
            )

        remaining = deadline - time.monotonic()

        if remaining <= 0:
            raise JobSchedulerError(
                f"Scheduler {lane.value} lane did not enter startup "
                f"within {timeout_seconds:g} seconds."
            )

        time.sleep(
            min(0.05, remaining)
        )


def _wait_scheduler_child_ready(
    lane: SchedulerLane,
    process: subprocess.Popen[bytes],
    ready_file: Path,
    *,
    timeout_seconds: float = _SCHEDULER_CHILD_READY_TIMEOUT_SECONDS,
) -> None:
    if timeout_seconds <= 0:
        raise ValueError(
            "Scheduler child readiness timeout must be positive."
        )

    deadline = time.monotonic() + timeout_seconds

    while not ready_file.is_file():
        returncode = process.poll()
        if returncode is not None:
            raise JobSchedulerError(
                f"Scheduler {lane.value} lane exited with code "
                f"{returncode} before becoming ready."
            )

        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise JobSchedulerError(
                f"Scheduler {lane.value} lane did not become ready "
                f"within {timeout_seconds:g} seconds."
            )

        time.sleep(
            min(0.05, remaining)
        )


def _run_scheduler_supervisor(args: argparse.Namespace) -> int:
    children: list[
        tuple[SchedulerLane, subprocess.Popen[bytes]]
    ] = []

    try:
        with tempfile.TemporaryDirectory(
            prefix="athena-scheduler-supervisor-"
        ) as temporary_directory:
            ready_root = Path(temporary_directory)

            control_started = ready_root / "control.started"
            control_ready = ready_root / "control.ready"
            control = subprocess.Popen(
                _scheduler_lane_command(
                    args,
                    SchedulerLane.CONTROL,
                    supervised_child=False,
                    started_file=control_started,
                    ready_file=control_ready,
                ),
                stdin=subprocess.PIPE,
            )
            children.append((SchedulerLane.CONTROL, control))
            _wait_scheduler_child_started(
                SchedulerLane.CONTROL,
                control,
                control_started,
            )
            _wait_scheduler_child_ready(
                SchedulerLane.CONTROL,
                control,
                control_ready,
            )

            provider_started = ready_root / "provider.started"
            provider_ready = ready_root / "provider.ready"
            provider = subprocess.Popen(
                _scheduler_lane_command(
                    args,
                    SchedulerLane.PROVIDER,
                    supervised_child=True,
                    started_file=provider_started,
                    ready_file=provider_ready,
                ),
                stdin=subprocess.PIPE,
            )
            children.append((SchedulerLane.PROVIDER, provider))
            _wait_scheduler_child_started(
                SchedulerLane.PROVIDER,
                provider,
                provider_started,
            )
            _wait_scheduler_child_ready(
                SchedulerLane.PROVIDER,
                provider,
                provider_ready,
            )

            print(
                "Scheduler supervisor lanes started: "
                + ", ".join(
                    f"{lane.value}=pid:{process.pid}"
                    for lane, process in children
                ),
                flush=True,
            )

            while True:
                states = [
                    (lane, process, process.poll())
                    for lane, process in children
                ]

                failed = [
                    (lane, returncode)
                    for lane, _process, returncode in states
                    if returncode not in (None, 0)
                ]
                if failed:
                    _stop_scheduler_children(children)
                    lane, returncode = failed[0]
                    raise JobSchedulerError(
                        "Scheduler "
                        f"{lane.value} lane exited with code "
                        f"{returncode}."
                    )

                if (
                    args.max_ticks is not None
                    and all(
                        returncode == 0
                        for _lane, _process, returncode in states
                    )
                ):
                    print(
                        "Scheduler supervisor lanes completed: "
                        "control, provider",
                        flush=True,
                    )
                    return 0

                if args.max_ticks is None:
                    clean_exit = next(
                        (
                            lane
                            for lane, _process, returncode in states
                            if returncode == 0
                        ),
                        None,
                    )
                    if clean_exit is not None:
                        _stop_scheduler_children(children)
                        raise JobSchedulerError(
                            "Long-lived scheduler "
                            f"{clean_exit.value} lane exited unexpectedly."
                        )

                time.sleep(0.05)

    except KeyboardInterrupt:
        _stop_scheduler_children(children)
        print("Scheduler supervisor interrupted.")
        return 130
    except OSError as exc:
        _stop_scheduler_children(children)
        raise JobSchedulerError(
            "Scheduler supervisor could not start both lanes."
        ) from exc
    except Exception:
        _stop_scheduler_children(children)
        raise


def _run_job_command(app: AthenaApplication, args: argparse.Namespace) -> int:
    if args.job_command == "create":
        job = app.jobs.create(
            job_type=args.job_type,
            priority=JobPriority(args.priority),
            requested_scope=args.scope_json,
            pinned_configuration=args.config_json,
        )
        _print_job(job)
        return 0

    if args.job_command == "show":
        _print_job(app.jobs.get(args.job_id))
        return 0

    if args.job_command == "list":
        jobs = app.jobs.list(limit=args.limit)
        if not jobs:
            print("No durable jobs.")
            return 0
        for job in jobs:
            print(
                f"{job.job_id} state={job.state.value} priority={int(job.priority)} "
                f"type={job.job_type} stage={job.current_stage or '<none>'} "
                f"checkpoint={job.last_checkpoint_id or '<none>'}"
            )
        return 0

    if args.job_command == "acquire":
        job = app.jobs.acquire(
            args.job_id,
            worker_id=args.worker,
            lease_seconds=args.lease_seconds,
        )
        if job.lease_token is None:
            raise JobLeaseError("Lease acquisition returned no lease token.")
        print(f"Job leased: {job.job_id}")
        print(f"State: {job.state.value}")
        print(f"Worker: {job.worker_id}")
        print(f"Lease token: {job.lease_token.hex()}")
        print(f"Lease expires us: {job.lease_expires_at_us}")
        print(f"Fencing sequence: {job.fencing_sequence}")
        return 0

    if args.job_command == "heartbeat":
        job = app.jobs.heartbeat(
            args.job_id,
            lease_token=args.lease_token,
            extend_seconds=args.extend_seconds,
        )
        print(
            f"Job heartbeat renewed: {job.job_id} "
            f"lease_expires_us={job.lease_expires_at_us} "
            f"fence={job.fencing_sequence}"
        )
        return 0

    if args.job_command == "checkpoint":
        checkpoint = app.jobs.checkpoint(
            args.job_id,
            lease_token=args.lease_token,
            current_stage=args.stage,
            progress_state=args.progress_json,
            last_confirmed_input=args.input_json,
            last_confirmed_output=args.output_json,
            resume_metadata=args.resume_json,
            commit_id=args.commit_id,
        )
        print(f"Checkpoint: {checkpoint.checkpoint_id}")
        print(f"URI: {checkpoint.uri}")
        print(f"Job: {checkpoint.job_id}")
        print(f"Fencing sequence: {checkpoint.fencing_sequence}")
        print(f"Progress: {checkpoint.progress_state_json or '<none>'}")
        return 0

    if args.job_command == "checkpoints":
        checkpoints = app.jobs.checkpoints(args.job_id)
        if not checkpoints:
            print("No checkpoints.")
            return 0
        for checkpoint in checkpoints:
            print(
                f"{checkpoint.checkpoint_id} job={checkpoint.job_id} "
                f"created_at_us={checkpoint.created_at_us} "
                f"fence={checkpoint.fencing_sequence} "
                f"progress={checkpoint.progress_state_json or '<none>'} "
                f"resume={checkpoint.resume_metadata_json or '<none>'}"
            )
        return 0

    if args.job_command == "complete":
        job = app.jobs.complete(args.job_id, lease_token=args.lease_token)
        print(f"Job completed: {job.job_id}")
        return 0

    if args.job_command == "wait":
        job = app.jobs.wait(
            args.job_id,
            lease_token=args.lease_token,
            reason=args.reason,
            next_run_at_us=args.next_run_at_us,
        )
        print(
            f"Job waiting: {job.job_id} reason={job.blocked_reason} "
            f"next_run_at_us={job.next_run_at_us or '<none>'}"
        )
        return 0

    if args.job_command == "wake":
        job = app.jobs.wake(args.job_id)
        print(f"Job queued: {job.job_id}")
        return 0

    if args.job_command == "cancel":
        job = app.jobs.request_cancel(args.job_id)
        print(f"Job cancellation state: {job.job_id} state={job.state.value}")
        return 0

    if args.job_command == "cancel-ack":
        job = app.jobs.acknowledge_cancel(
            args.job_id, lease_token=args.lease_token
        )
        print(f"Job cancelled: {job.job_id}")
        return 0

    if args.job_command == "pause":
        job = app.jobs.pause(args.job_id)
        print(f"Job paused: {job.job_id}")
        return 0

    if args.job_command == "resume":
        job = app.jobs.resume(args.job_id)
        print(f"Job resumed: {job.job_id} state={job.state.value}")
        return 0

    if args.job_command == "source-process":
        job = app.source_processing.enqueue(
            args.source_id,
            priority=JobPriority(args.priority),
        )
        _print_job(job)
        return 0

    if args.job_command == "source-step":
        source_result = app.source_processing.step(
            args.job_id,
            lease_token=args.lease_token,
            extend_seconds=args.extend_seconds,
        )
        _print_source_processing_result(source_result)
        return 0

    if args.job_command == "run-source":
        source_result = app.source_processing.run_to_completion(
            args.job_id,
            worker_id=args.worker,
            lease_seconds=args.lease_seconds,
        )
        _print_source_processing_result(source_result)
        return 0

    if args.job_command == "source-analyze":
        job = app.source_analysis.enqueue(
            args.source_id,
            question=args.question,
            requested_model_id=args.model_id,
            priority=JobPriority(args.priority),
            context_limit=args.context_limit,
            output_reserve=args.output_reserve,
            safety_margin=args.safety_margin,
            max_hierarchy_depth=args.max_depth,
        )
        _print_job(job)
        return 0

    if args.job_command == "analysis-step":
        analysis_result = app.source_analysis.step(
            args.job_id,
            lease_token=args.lease_token,
            extend_seconds=args.extend_seconds,
        )
        _print_source_analysis_result(analysis_result)
        return 0

    if args.job_command == "run-analysis":
        analysis_result = app.source_analysis.run_to_completion(
            args.job_id,
            worker_id=args.worker,
            lease_seconds=args.lease_seconds,
        )
        _print_source_analysis_result(analysis_result)
        return 0

    if args.job_command == "analysis-show":
        analysis = app.source_analysis_repository.get_analysis(args.analysis_id)
        print(f"Analysis: {analysis.analysis_id}")
        print(f"Job: {analysis.job_id}")
        print(f"Source: {analysis.source_id}")
        print(f"Representation: {analysis.representation_id}")
        print(f"State: {analysis.state.value}")
        print(f"Coverage: {analysis.coverage:.6f}")
        print(
            "Map units: "
            f"{analysis.completed_map_units}/{analysis.total_map_units} "
            f"failed={analysis.failed_map_units}"
        )
        print(f"Model signature: {analysis.model_signature_id}")
        print(f"Context limit: {analysis.effective_context_limit}")
        print(f"Output reserve: {analysis.output_reserve}")
        print(f"Safety margin: {analysis.safety_margin}")
        print(f"Token estimator: {analysis.token_estimator}")
        print(f"Final artifact: {analysis.final_artifact_id or '<none>'}")
        return 0

    if args.job_command == "analysis-artifacts":
        artifacts = app.source_analysis_repository.list_artifacts(args.analysis_id)
        if not artifacts:
            print("No source-analysis artifacts.")
            return 0
        for artifact in artifacts:
            anchor_ids = app.source_analysis_repository.source_anchor_ids_for_artifact(
                artifact.artifact_id
            )
            print(
                f"{artifact.artifact_id} kind={artifact.artifact_kind.value} "
                f"level={artifact.level} ordinal={artifact.ordinal} "
                f"run={artifact.processing_run_id} anchors="
                + ",".join(str(anchor_id) for anchor_id in anchor_ids)
            )
            print(artifact.content_json)
        return 0

    if args.job_command == "source-extract":
        job = app.source_hierarchical_extraction.enqueue(
            args.analysis_id,
            requested_model_id=args.model_id,
            priority=JobPriority(args.priority),
            context_limit=args.context_limit,
            output_reserve=args.output_reserve,
            safety_margin=args.safety_margin,
            max_hierarchy_depth=args.max_depth,
        )
        _print_job(job)
        return 0

    if args.job_command == "extraction-step":
        extraction_result = app.source_hierarchical_extraction.step(
            args.job_id,
            lease_token=args.lease_token,
            extend_seconds=args.extend_seconds,
        )
        _print_source_extraction_job_result(extraction_result)
        return 0

    if args.job_command == "run-extraction":
        extraction_result = app.source_hierarchical_extraction.run_to_completion(
            args.job_id,
            worker_id=args.worker,
            lease_seconds=args.lease_seconds,
        )
        _print_source_extraction_job_result(extraction_result)
        return 0

    if args.job_command == "extraction-show":
        extraction = app.source_hierarchical_extraction_repository.get_extraction(
            args.extraction_id
        )
        print(f"Extraction: {extraction.extraction_id}")
        print(f"Job: {extraction.job_id}")
        print(f"Analysis: {extraction.analysis_id}")
        print(f"Analysis Final artifact: {extraction.final_artifact_id}")
        print(f"State: {extraction.state.value}")
        print(
            "Batches: "
            f"{extraction.completed_batches}/{extraction.total_batches} "
            f"failed={extraction.failed_batches}"
        )
        print(f"Model signature: {extraction.model_signature_id}")
        print(f"Context limit: {extraction.effective_context_limit}")
        print(f"Output reserve: {extraction.output_reserve}")
        print(f"Safety margin: {extraction.safety_margin}")
        print(f"Token estimator: {extraction.token_estimator}")
        print(f"Final work artifact: {extraction.final_work_artifact_id or '<none>'}")
        return 0

    if args.job_command == "extraction-artifacts":
        extraction_artifacts = app.source_hierarchical_extraction_repository.list_artifacts(
            args.extraction_id
        )
        if not extraction_artifacts:
            print("No hierarchical source-extraction artifacts.")
            return 0
        for extraction_artifact in extraction_artifacts:
            print(
                f"{extraction_artifact.artifact_id} "
                f"kind={extraction_artifact.artifact_kind.value} "
                f"level={extraction_artifact.level} ordinal={extraction_artifact.ordinal} "
                f"run={extraction_artifact.processing_run_id}"
            )
            print(extraction_artifact.content_json)
        return 0

    if args.job_command == "embedding-rebuild":
        job = app.embedding_rebuild.enqueue(
            args.model,
            priority=JobPriority(args.priority),
            batch_size=args.batch_size,
        )
        _print_job(job)
        return 0

    if args.job_command == "embedding-step":
        embedding_result = app.embedding_rebuild.step(
            args.job_id,
            lease_token=args.lease_token,
            extend_seconds=args.extend_seconds,
        )
        _print_embedding_rebuild_result(embedding_result)
        return 0

    if args.job_command == "run-embedding":
        embedding_result = app.embedding_rebuild.run_to_boundary(
            args.job_id,
            worker_id=args.worker,
            lease_seconds=args.lease_seconds,
        )
        _print_embedding_rebuild_result(embedding_result)
        return 0

    if args.job_command == "scheduler-once":
        scheduler_result = app.job_scheduler.tick(worker_id=args.worker)
        _print_scheduler_tick(scheduler_result)
        return 0

    if args.job_command == "scheduler-drain":
        scheduler_run = app.job_scheduler.drain(
            worker_id=args.worker,
            max_jobs=args.max_jobs,
        )
        _print_scheduler_run(scheduler_run)
        return 0

    if args.job_command == "scheduler-run":
        if args.lane == "supervisor":
            raise JobSchedulerError(
                "Scheduler supervisor must be launched before "
                "AthenaApplication startup."
            )

        lane = SchedulerLane(args.lane)
        try:
            scheduler_run = app.job_scheduler.run_loop(
                worker_id=args.worker,
                max_ticks=args.max_ticks,
                lane=lane,
            )
        except KeyboardInterrupt:
            print("Scheduler interrupted.")
            return 130
        _print_scheduler_run(scheduler_run)
        return 0

    if args.job_command == "recover":
        recovered = app.jobs.recover_startup()
        print(f"Recovered jobs: {len(recovered)}")
        for job in recovered:
            print(f"{job.job_id} state={job.state.value} reason={job.blocked_reason}")
        return 0

    raise RuntimeError(f"Unsupported job command: {args.job_command!r}")


def _run_model_command(app: AthenaApplication, args: argparse.Namespace) -> int:
    if args.model_command == "status":
        health = app.model_provider.health()
        print(f"Provider: {app.model_provider.provider_id}")
        print(f"Status: {health.status.value}")
        print(f"Endpoint: {app.model_provider.base_url}")
        if health.detail:
            print(f"Detail: {health.detail}")
        return 0 if health.status.value == "ready" else 1

    if args.model_command == "list":
        models = app.model_provider.discover_models()
        if not models:
            print("No models reported by LM Studio.")
            return 0
        for model in models:
            context = str(model.context_capacity) if model.context_capacity else "unknown"
            quantization = model.quantization or "unknown"
            loaded = "yes" if model.loaded else "no"
            print(
                f"{model.backend_model_id}  type={model.model_type}  loaded={loaded}  "
                f"context={context}  quantization={quantization}"
            )
        return 0

    raise RuntimeError(f"Unsupported model command: {args.model_command!r}")


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    if (
        args.command == "backup"
        and args.backup_command == "restore-path"
    ):
        from athena.recovery_cli import run_restore_path

        return run_restore_path(
            args.snapshot_root,
            destination_root=args.destination_root,
        )

    if (
        args.command == "job"
        and args.job_command == "scheduler-run"
        and args.supervisor_watchdog
        and (
            args.lane
            not in {
                SchedulerLane.CONTROL.value,
                SchedulerLane.PROVIDER.value,
            }
            or args.ready_file is None
        )
    ):
        print(
            "ATHENA job error: --supervisor-watchdog is reserved for "
            "supervisor-owned control/provider children.",
            file=sys.stderr,
        )
        return 2

    if (
        args.command == "job"
        and args.job_command == "scheduler-run"
        and args.supervisor_watchdog
    ):
        _start_scheduler_supervisor_watchdog()

    if (
        args.command == "job"
        and args.job_command == "scheduler-run"
        and args.supervised_child
        and (
            args.lane != SchedulerLane.PROVIDER.value
            or args.ready_file is None
        )
    ):
        print(
            "ATHENA job error: --supervised-child is reserved for "
            "provider-lane supervisor children.",
            file=sys.stderr,
        )
        return 2

    if (
        args.command == "job"
        and args.job_command == "scheduler-run"
        and args.lane == "supervisor"
    ):
        try:
            return _run_scheduler_supervisor(args)
        except JobSchedulerError as exc:
            print(f"ATHENA job error: {exc}", file=sys.stderr)
            return 2

    try:
        app = AthenaApplication()
    except ConfigurationError as exc:
        print(f"ATHENA configuration error: {exc}", file=sys.stderr)
        return 2

    scheduler_lane_locks: tuple[SchedulerLaneProcessLock, ...] = ()
    if (
        args.command == "job"
        and args.job_command == "scheduler-run"
    ):
        try:
            scheduler_lane_locks = _acquire_scheduler_run_lane_locks(
                app,
                SchedulerLane(args.lane),
            )
        except SchedulerLaneOwnershipError as exc:
            print(f"ATHENA job error: {exc}", file=sys.stderr)
            return 2

    if (
        args.command == "job"
        and args.job_command == "scheduler-run"
        and args.started_file is not None
    ):
        args.started_file.write_text(
            "started\n",
            encoding="utf-8",
        )

    try:
        supervised_scheduler_child = (
            args.command == "job"
            and args.job_command == "scheduler-run"
            and bool(args.supervised_child)
        )
        app.start(
            run_startup_maintenance=not supervised_scheduler_child
        )
        if (
            args.command == "job"
            and args.job_command == "scheduler-run"
            and args.ready_file is not None
        ):
            args.ready_file.write_text(
                "ready\n",
                encoding="utf-8",
            )

        if args.command == "chat":
            try:
                return _run_chat_command(app, args)
            except (
                ArchiveSearchError,
                ChatNotFoundError,
                EmptyMessageError,
                ModelProviderError,
                ModelSelectionError,
                SemanticSearchError,
                SourceAnchorIntegrityError,
                SourceRepresentationNotFoundError,
                TextRepresentationError,
                UnsupportedChatHistoryError,
                ValueError,
            ) as exc:
                print(f"ATHENA chat error: {exc}", file=sys.stderr)
                return 2

        if args.command == "knowledge":
            try:
                return _run_knowledge_command(app, args)
            except (
                ChatNotFoundError,
                ChatMessageSequenceError,
                KnowledgeActorError,
                KnowledgeConflictError,
                KnowledgeNotFoundError,
                KnowledgeSourceError,
                UnsupportedKnowledgeSourceError,
                ValueError,
            ) as exc:
                print(f"ATHENA knowledge error: {exc}", file=sys.stderr)
                return 2

        if args.command == "memory":
            try:
                return _run_memory_command(app, args)
            except (
                PersonalMemoryActorError,
                PersonalMemoryConflictError,
                PersonalMemoryLifecycleError,
                PersonalMemoryNotFoundError,
                PersonalMemoryProtectionError,
                ValueError,
            ) as exc:
                print(f"ATHENA Personal Memory error: {exc}", file=sys.stderr)
                return 2

        if args.command == "claim":
            try:
                return _run_claim_command(app, args)
            except (
                ChatNotFoundError,
                ChatMessageSequenceError,
                ClaimNotFoundError,
                ClaimRelationError,
                KnowledgeActorError,
                KnowledgeConflictError,
                KnowledgeSourceError,
                UnsupportedKnowledgeSourceError,
                ValueError,
            ) as exc:
                print(f"ATHENA claim error: {exc}", file=sys.stderr)
                return 2

        if args.command == "extract":
            try:
                return _run_extract_command(app, args)
            except (
                ChatNotFoundError,
                ModelProviderError,
                ModelSelectionError,
                ValueError,
            ) as exc:
                print(f"ATHENA extraction error: {exc}", file=sys.stderr)
                return 2

        if args.command == "review":
            try:
                return _run_review_command(app, args)
            except (ReviewError, ValueError) as exc:
                print(f"ATHENA review error: {exc}", file=sys.stderr)
                return 2

        if args.command == "context":
            try:
                return _run_context_command(app, args)
            except (
                ContextBuilderError,
                ModelProviderError,
                SearchError,
                SemanticRetrievalUnavailableError,
                SemanticSearchError,
            ) as exc:
                print(f"ATHENA context error: {exc}", file=sys.stderr)
                return 2

        if args.command == "search":
            try:
                return _run_search_command(app, args)
            except (
                SearchError,
                ModelProviderError,
                SemanticRetrievalUnavailableError,
            ) as exc:
                print(f"ATHENA search error: {exc}", file=sys.stderr)
                return 2
            except SemanticSearchError as exc:
                print(f"ATHENA search error: {exc}", file=sys.stderr)
                return 2

        if args.command == "embedding":
            try:
                return _run_embedding_command(app, args)
            except ModelProviderError as exc:
                print(f"ATHENA embedding error: {exc}", file=sys.stderr)
                return 2
            except SemanticSearchError as exc:
                print(f"ATHENA embedding error: {exc}", file=sys.stderr)
                return 2

        if args.command == "job":
            try:
                return _run_job_command(app, args)
            except (
                CheckpointNotFoundError,
                JobLeaseError,
                JobNotFoundError,
                JobTransitionError,
                JobSchedulerError,
                EmbeddingRebuildJobError,
                SourceProcessingJobError,
                SourceAnalysisJobError,
                SourceHierarchicalExtractionJobError,
                SourceAnalysisNotFoundError,
                ModelProviderError,
                ModelSelectionError,
                ValueError,
            ) as exc:
                print(f"ATHENA job error: {exc}", file=sys.stderr)
                return 2

        if args.command == "source":
            try:
                return _run_source_command(app, args)
            except (
                BlobStoreError,
                SourceActorError,
                SourceAnchorNotFoundError,
                SourceAnchorIntegrityError,
                SourceNotFoundError,
                SourceRepresentationNotFoundError,
                SourceChunkNotFoundError,
                SourceChunkStoreError,
                SourceChunkIntegrityError,
                ArchiveSearchError,
                ModelProviderError,
                SemanticRetrievalUnavailableError,
                TextRepresentationError,
                ValueError,
            ) as exc:
                print(f"ATHENA source error: {exc}", file=sys.stderr)
                return 2

        if args.command in {"research", "external", "resource", "backup", "delete"}:
            try:
                return run_operational_command(app, args)
            except OperationalCommandError as exc:
                print(f"ATHENA operational error: {exc}", file=sys.stderr)
                return 2

        if args.command == "model":
            try:
                return _run_model_command(app, args)
            except ModelProviderError as exc:
                print(f"ATHENA model provider error: {exc}", file=sys.stderr)
                return 2

        health = app.health.snapshot()
        print(f"ATHENA {__version__}")
        print(f"Core state: {app.state.value}")
        print(f"Health: {health.status.value}")

        if args.show_paths:
            _print_paths(app)

        return 0
    finally:
        try:
            if app.state.value != "stopped":
                app.stop()
        finally:
            for scheduler_lane_lock in reversed(
                scheduler_lane_locks
            ):
                scheduler_lane_lock.close()


if __name__ == "__main__":
    raise SystemExit(main())
