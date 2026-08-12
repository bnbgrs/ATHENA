"""Command-line launcher for ATHENA."""

from __future__ import annotations

import argparse
import sys
import uuid
from collections.abc import Sequence

from athena.chat.generation import ModelSelectionError, UnsupportedChatHistoryError
from athena.chat.models import ChatThread
from athena.chat.repository import ChatNotFoundError
from athena.chat.service import EmptyMessageError
from athena.config.settings import ConfigurationError
from athena.core.application import AthenaApplication
from athena.knowledge.claim_repository import ClaimNotFoundError, ClaimRelationError
from athena.knowledge.extraction_models import ChatExtractionResult
from athena.knowledge.models import (
    ClaimKind,
    ClaimSnapshot,
    EpistemicStatus,
    KnowledgeKind,
    KnowledgeUnitSnapshot,
)
from athena.knowledge.repository import (
    KnowledgeActorError,
    KnowledgeConflictError,
    KnowledgeNotFoundError,
    KnowledgeSourceError,
)
from athena.knowledge.service import (
    ChatMessageSequenceError,
    UnsupportedKnowledgeSourceError,
)
from athena.model.adapters.lm_studio import ModelProviderError
from athena.version import __version__


def _uuid_argument(value: str) -> uuid.UUID:
    try:
        return uuid.UUID(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"invalid UUID: {value!r}") from exc


def _knowledge_kind_argument(value: str) -> KnowledgeKind:
    try:
        return KnowledgeKind(value)
    except ValueError as exc:
        allowed = ", ".join(item.value for item in KnowledgeKind)
        raise argparse.ArgumentTypeError(
            f"invalid knowledge kind {value!r}; choose one of: {allowed}"
        ) from exc


def _claim_kind_argument(value: str) -> ClaimKind:
    try:
        return ClaimKind(value)
    except ValueError as exc:
        allowed = ", ".join(item.value for item in ClaimKind)
        raise argparse.ArgumentTypeError(
            f"invalid claim kind {value!r}; choose one of: {allowed}"
        ) from exc


def _epistemic_status_argument(value: str) -> EpistemicStatus:
    try:
        return EpistemicStatus(value)
    except ValueError as exc:
        allowed = ", ".join(item.value for item in EpistemicStatus)
        raise argparse.ArgumentTypeError(
            f"invalid epistemic status {value!r}; choose one of: {allowed}"
        ) from exc


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="athena",
        description="ATHENA local-first personal knowledge system",
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"ATHENA {__version__}",
    )
    parser.add_argument(
        "--show-paths",
        action="store_true",
        help="Print resolved ATHENA runtime paths.",
    )

    commands = parser.add_subparsers(dest="command")
    chat_parser = commands.add_parser("chat", help="Persistent chat commands.")
    chat_commands = chat_parser.add_subparsers(dest="chat_command", required=True)

    chat_commands.add_parser("new", help="Create a new persistent chat.")

    add_parser = chat_commands.add_parser("add", help="Append a local user message.")
    add_parser.add_argument("chat_id", type=_uuid_argument)
    add_parser.add_argument("content", help="Message text. Quote text containing spaces.")

    send_parser = chat_commands.add_parser(
        "send",
        help="Persist a user message, stream a local model reply, then save it.",
    )
    send_parser.add_argument("chat_id", type=_uuid_argument)
    send_parser.add_argument("content", help="Message text. Quote text containing spaces.")
    send_parser.add_argument(
        "--model",
        dest="model_id",
        help="Exact LM Studio model identifier. Required if multiple LLMs are loaded.",
    )

    show_parser = chat_commands.add_parser("show", help="Load and print a persistent chat.")
    show_parser.add_argument("chat_id", type=_uuid_argument)

    list_parser = chat_commands.add_parser("list", help="List recent persistent chats.")
    list_parser.add_argument(
        "--limit",
        type=int,
        default=50,
        help="Maximum number of chats to print (1-500).",
    )

    knowledge_parser = commands.add_parser(
        "knowledge",
        help="Canonical versioned KnowledgeUnit commands.",
    )
    knowledge_commands = knowledge_parser.add_subparsers(
        dest="knowledge_command",
        required=True,
    )

    promote_parser = knowledge_commands.add_parser(
        "promote",
        help="Explicitly promote one exact chat message to canonical Knowledge.",
    )
    promote_parser.add_argument("chat_id", type=_uuid_argument)
    promote_parser.add_argument("sequence_no", type=int)
    promote_parser.add_argument("--kind", type=_knowledge_kind_argument, required=True)
    promote_parser.add_argument("--title")
    promote_parser.add_argument(
        "--status",
        type=_epistemic_status_argument,
        default=EpistemicStatus.ASSERTED,
    )

    knowledge_show = knowledge_commands.add_parser(
        "show",
        help="Show the current revision and provenance inputs of a KnowledgeUnit.",
    )
    knowledge_show.add_argument("knowledge_id", type=_uuid_argument)

    knowledge_history = knowledge_commands.add_parser(
        "history",
        help="Show all immutable revisions of a KnowledgeUnit.",
    )
    knowledge_history.add_argument("knowledge_id", type=_uuid_argument)

    knowledge_revise = knowledge_commands.add_parser(
        "revise",
        help="Create a new direct-user revision of an existing KnowledgeUnit.",
    )
    knowledge_revise.add_argument("knowledge_id", type=_uuid_argument)
    knowledge_revise.add_argument("body", help="Replacement body text.")
    knowledge_revise.add_argument("--title")
    knowledge_revise.add_argument("--kind", type=_knowledge_kind_argument)
    knowledge_revise.add_argument("--status", type=_epistemic_status_argument)

    knowledge_list = knowledge_commands.add_parser(
        "list",
        help="List current KnowledgeUnit heads.",
    )
    knowledge_list.add_argument(
        "--limit",
        type=int,
        default=50,
        help="Maximum number of KnowledgeUnits to print (1-500).",
    )

    claim_parser = commands.add_parser(
        "claim",
        help="Canonical versioned Claim and contradiction commands.",
    )
    claim_commands = claim_parser.add_subparsers(dest="claim_command", required=True)

    claim_promote = claim_commands.add_parser(
        "promote",
        help="Explicitly promote one exact chat message to a canonical Claim.",
    )
    claim_promote.add_argument("chat_id", type=_uuid_argument)
    claim_promote.add_argument("sequence_no", type=int)
    claim_promote.add_argument("--kind", type=_claim_kind_argument, required=True)
    claim_promote.add_argument(
        "--status",
        type=_epistemic_status_argument,
        default=EpistemicStatus.ASSERTED,
    )
    claim_promote.add_argument("--valid-from-us", type=int)
    claim_promote.add_argument("--valid-to-us", type=int)

    claim_show = claim_commands.add_parser(
        "show",
        help="Show the current Claim revision, provenance inputs, and evidence links.",
    )
    claim_show.add_argument("claim_id", type=_uuid_argument)

    claim_history = claim_commands.add_parser(
        "history",
        help="Show all immutable revisions of a Claim.",
    )
    claim_history.add_argument("claim_id", type=_uuid_argument)

    claim_revise = claim_commands.add_parser(
        "revise",
        help="Create a new direct-user revision of an existing Claim.",
    )
    claim_revise.add_argument("claim_id", type=_uuid_argument)
    claim_revise.add_argument("statement", help="Replacement natural-language statement.")
    claim_revise.add_argument("--kind", type=_claim_kind_argument)
    claim_revise.add_argument("--status", type=_epistemic_status_argument)

    claim_contradict = claim_commands.add_parser(
        "contradict",
        help="Explicitly link two Claims as reciprocal contradictions.",
    )
    claim_contradict.add_argument("left_claim_id", type=_uuid_argument)
    claim_contradict.add_argument("right_claim_id", type=_uuid_argument)

    claim_list = claim_commands.add_parser("list", help="List current Claim heads.")
    claim_list.add_argument(
        "--limit",
        type=int,
        default=50,
        help="Maximum number of Claims to print (1-500).",
    )

    extract_parser = commands.add_parser(
        "extract",
        help="Primary Model extraction proposals; no canonical writes yet.",
    )
    extract_commands = extract_parser.add_subparsers(
        dest="extract_command",
        required=True,
    )
    extract_chat = extract_commands.add_parser(
        "chat",
        help="Generate validated Knowledge/Claim proposals from a persistent chat.",
    )
    extract_chat.add_argument("chat_id", type=_uuid_argument)
    extract_chat.add_argument(
        "--model",
        dest="model_id",
        help="Exact loaded LM Studio model identifier when more than one LLM is loaded.",
    )
    extract_chat.add_argument(
        "--accept",
        action="store_true",
        help="After displaying the exact validated proposal set, ask for explicit user acceptance and atomically commit it.",
    )

    model_parser = commands.add_parser("model", help="Local model provider commands.")
    model_commands = model_parser.add_subparsers(dest="model_command", required=True)
    model_commands.add_parser("status", help="Check LM Studio provider health.")
    model_commands.add_parser("list", help="List models discovered from LM Studio.")

    return parser


def _print_paths(app: AthenaApplication) -> None:
    print(f"Local root: {app.paths.local_root}")
    print(f"State root: {app.paths.state_root}")
    print(f"Database: {app.paths.database_path}")
    print(f"Spool root: {app.paths.spool_root}")
    print(f"Derived root: {app.paths.derived_root}")
    print(f"Log root: {app.paths.log_root}")
    print(f"Temp root: {app.paths.temp_root}")
    print(
        "Archive root: "
        + (str(app.paths.archive_root) if app.paths.archive_root else "<unset>")
    )
    print(
        "Backup root: "
        + (str(app.paths.backup_root) if app.paths.backup_root else "<unset>")
    )
    print(
        "Projection root: "
        + (str(app.paths.projection_root) if app.paths.projection_root else "<unset>")
    )


def _print_chat(thread: ChatThread) -> None:
    print(f"Chat: {thread.chat_id}")
    print(f"State: {thread.lifecycle_state}")
    print(f"Archive mode: {thread.archive_mode}")
    print(f"Messages: {len(thread.messages)}")
    for message in thread.messages:
        content = message.content if message.content is not None else "<protected>"
        print(f"[{message.sequence_no}] {message.message_type.value}: {content}")


def _print_knowledge(app: AthenaApplication, snapshot: KnowledgeUnitSnapshot) -> None:
    revision = snapshot.revision
    payload = revision.payload
    print(f"Knowledge: {snapshot.knowledge_id}")
    print(f"State: {snapshot.lifecycle_state}")
    print(f"Revision: {revision.revision_no} ({revision.revision_id})")
    print(f"Kind: {payload.knowledge_kind.value}")
    print(f"Status: {payload.epistemic_status.value}")
    print(f"Title: {payload.title if payload.title is not None else '<none>'}")
    print(f"Body: {payload.body}")
    inputs = app.knowledge.provenance_inputs(revision.provenance_id)
    print(f"Provenance inputs: {len(inputs)}")
    for item in inputs:
        revision_text = (
            str(item.input_revision_id)
            if item.input_revision_id is not None
            else "<entity-only>"
        )
        print(
            f"[{item.ordinal}] role={item.input_role} "
            f"entity={item.input_entity_id} revision={revision_text}"
        )


def _print_claim(app: AthenaApplication, snapshot: ClaimSnapshot) -> None:
    revision = snapshot.revision
    payload = revision.payload
    print(f"Claim: {snapshot.claim_id}")
    print(f"State: {snapshot.lifecycle_state}")
    print(f"Revision: {revision.revision_no} ({revision.revision_id})")
    print(f"Kind: {payload.claim_kind.value}")
    print(f"Status: {payload.epistemic_status.value}")
    print(f"Statement: {payload.statement}")
    print(f"Valid from us: {payload.valid_from_us if payload.valid_from_us is not None else '<open>'}")
    print(f"Valid to us: {payload.valid_to_us if payload.valid_to_us is not None else '<open>'}")
    inputs = app.claims.provenance_inputs(revision.provenance_id)
    print(f"Provenance inputs: {len(inputs)}")
    for item in inputs:
        revision_text = (
            str(item.input_revision_id)
            if item.input_revision_id is not None
            else "<entity-only>"
        )
        print(
            f"[{item.ordinal}] role={item.input_role} "
            f"entity={item.input_entity_id} revision={revision_text}"
        )
    evidence = app.claims.evidence(snapshot.claim_id)
    print(f"Evidence links: {len(evidence)}")
    for index, evidence_item in enumerate(evidence):
        print(
            f"[{index}] role={evidence_item.evidence_role.value} "
            f"message={evidence_item.message_id if evidence_item.message_id is not None else '<none>'} "
            f"entity={evidence_item.evidence_entity_id if evidence_item.evidence_entity_id is not None else '<none>'} "
            f"revision={evidence_item.evidence_revision_id if evidence_item.evidence_revision_id is not None else '<none>'}"
        )


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
        print("Assistant: ", end="", flush=True)
        try:
            result = app.chat_generation.send_message(
                chat_id=args.chat_id,
                content=args.content,
                requested_model_id=args.model_id,
                on_delta=lambda chunk: print(chunk, end="", flush=True),
            )
        except KeyboardInterrupt:
            print()
            print(
                "Generation cancelled. User message remains saved; "
                "partial assistant text was not persisted.",
                file=sys.stderr,
            )
            return 130
        print()
        print(f"Model: {result.model.backend_model_id}")
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


def _print_extraction(result: ChatExtractionResult) -> None:
    proposals = result.proposals
    print(f"Extraction run: {result.processing_run.processing_run_id}")
    print(f"Run status: {result.processing_run.status}")
    print(f"Model: {result.model.backend_model_id}")
    print(f"Model signature: {result.model_signature.model_signature_id}")
    print(f"Knowledge proposals: {len(proposals.knowledge_units)}")
    for index, proposal in enumerate(proposals.knowledge_units):
        title = proposal.title if proposal.title is not None else "<none>"
        print(
            f"[K{index}] source=[{proposal.source_sequence_no}] "
            f"kind={proposal.knowledge_kind.value} "
            f"status={proposal.epistemic_status.value} "
            f"confidence={proposal.confidence:.3f} title={title} "
            f"quote={proposal.source_quote!r} body={proposal.body}"
        )
    print(f"Claim proposals: {len(proposals.claims)}")
    for index, claim_proposal in enumerate(proposals.claims):
        print(
            f"[C{index}] source=[{claim_proposal.source_sequence_no}] "
            f"kind={claim_proposal.claim_kind.value} "
            f"status={claim_proposal.epistemic_status.value} "
            f"confidence={claim_proposal.confidence:.3f} "
            f"quote={claim_proposal.source_quote!r} "
            f"statement={claim_proposal.statement}"
        )
    print(f"Relation proposals: {len(proposals.relations)}")
    for index, relation in enumerate(proposals.relations):
        print(
            f"[R{index}] {relation.left_type.value}[{relation.left_index}] "
            f"--{relation.relation_type}--> "
            f"{relation.right_type.value}[{relation.right_index}] "
            f"confidence={relation.confidence:.3f}"
        )
    print(f"Merge candidates: {len(proposals.merge_candidates)}")
    for index, candidate in enumerate(proposals.merge_candidates):
        print(
            f"[M{index}] {candidate.proposal_type.value}[{candidate.proposal_index}] "
            f"confidence={candidate.confidence:.3f} reason={candidate.reason}"
        )
    print("Canonical writes: 0 (proposal-only)")


def _run_extract_command(app: AthenaApplication, args: argparse.Namespace) -> int:
    if args.extract_command == "chat":
        result = app.extraction.extract_chat(
            chat_id=args.chat_id,
            requested_model_id=args.model_id,
        )
        _print_extraction(result)
        if not args.accept:
            return 0

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
            print("Acceptance blocked: resolve canonical merge candidates first.")
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
        return 0

    raise RuntimeError(f"Unsupported extraction command: {args.extract_command!r}")


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

    try:
        app = AthenaApplication()
    except ConfigurationError as exc:
        print(f"ATHENA configuration error: {exc}", file=sys.stderr)
        return 2

    try:
        app.start()

        if args.command == "chat":
            try:
                return _run_chat_command(app, args)
            except (
                ChatNotFoundError,
                EmptyMessageError,
                ModelProviderError,
                ModelSelectionError,
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
        if app.state.value != "stopped":
            app.stop()


if __name__ == "__main__":
    raise SystemExit(main())
