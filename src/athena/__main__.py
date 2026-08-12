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
from athena.knowledge.extraction_snapshot import ExtractionSnapshotNotFoundError
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
from athena.knowledge.review_service import ReviewError
from athena.knowledge.service import (
    ChatMessageSequenceError,
    UnsupportedKnowledgeSourceError,
)
from athena.model.adapters.lm_studio import ModelProviderError
from athena.retrieval.context import ContextBuilderError
from athena.retrieval.search import SearchEntityType, SearchError
from athena.retrieval.semantic import SemanticSearchError
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

    extract_accept_run = extract_commands.add_parser(
        "accept-run",
        help="Load and accept one frozen successful extraction run without calling the model again.",
    )
    extract_accept_run.add_argument("processing_run_id", type=_uuid_argument)

    review_parser = commands.add_parser(
        "review",
        help="Persistent semantic review queue.",
    )
    review_commands = review_parser.add_subparsers(dest="review_command", required=True)

    review_list = review_commands.add_parser("list", help="List pending review items.")
    review_list.add_argument("--type", dest="review_type", choices=("contradiction", "merge_candidate"))
    review_list.add_argument("--limit", type=int, default=100)

    review_show = review_commands.add_parser("show", help="Show one semantic review item.")
    review_show.add_argument("review_id", type=_uuid_argument)

    review_accept = review_commands.add_parser("accept", help="Accept one pending review item.")
    review_accept.add_argument("review_id", type=_uuid_argument)

    review_reject = review_commands.add_parser("reject", help="Reject one pending review item.")
    review_reject.add_argument("review_id", type=_uuid_argument)

    review_merge = review_commands.add_parser(
        "merge",
        help="Resolve a merge candidate by reusing the displayed canonical target.",
    )
    review_merge.add_argument("review_id", type=_uuid_argument)

    review_keep_separate = review_commands.add_parser(
        "keep-separate",
        help="Resolve a merge candidate by keeping the proposal as a separate canonical entity.",
    )
    review_keep_separate.add_argument("review_id", type=_uuid_argument)

    review_accept_all = review_commands.add_parser(
        "accept-all",
        help="Batch-accept pending review items at or above a confidence threshold.",
    )
    review_accept_all.add_argument(
        "--type",
        dest="review_type",
        choices=("contradiction",),
        default="contradiction",
    )
    review_accept_all.add_argument("--min-confidence", type=float, default=0.0)

    search_parser = commands.add_parser(
        "search",
        help="Search current local Knowledge, Claims, and archived chat messages.",
    )
    search_parser.add_argument("query", help="Local full-text search query.")
    search_parser.add_argument(
        "--type",
        dest="search_type",
        choices=("knowledge", "claim", "chat_message"),
        help="Optional entity-type filter.",
    )
    search_parser.add_argument(
        "--limit",
        type=int,
        default=20,
        help="Maximum number of results (1-200).",
    )
    search_parser.add_argument(
        "--rebuild",
        action="store_true",
        help="Force a complete rebuild of the derived FTS index before searching.",
    )

    search_parser.add_argument(
        "--raw",
        action="store_true",
        help="Show raw FTS results without consolidation or retrieval ranking.",
    )

    search_parser.add_argument(
        "--hybrid",
        action="store_true",
        help="Fuse lexical retrieval with local semantic embeddings.",
    )
    search_parser.add_argument(
        "--embedding-model",
        help="LM Studio embedding model id. Auto-selects only when unambiguous.",
    )


    context_parser = commands.add_parser(
        "context",
        help="Build bounded provenance-preserving context from local retrieval.",
    )
    context_commands = context_parser.add_subparsers(
        dest="context_command",
        required=True,
    )
    context_build = context_commands.add_parser(
        "build",
        help="Build model-facing JSON context without calling the Primary Model.",
    )
    context_build.add_argument("query", help="Retrieval query.")
    context_build.add_argument(
        "--type",
        dest="context_type",
        choices=("knowledge", "claim", "chat_message"),
        help="Optional entity-type filter.",
    )
    context_build.add_argument(
        "--hybrid",
        action="store_true",
        help="Use lexical + semantic hybrid retrieval.",
    )
    context_build.add_argument(
        "--embedding-model",
        help="LM Studio embedding model id for --hybrid.",
    )
    context_build.add_argument(
        "--max-tokens",
        type=int,
        default=1200,
        help="Deterministic estimated-token budget (128-64000).",
    )
    context_build.add_argument(
        "--max-items",
        type=int,
        default=8,
        help="Maximum context items (1-100).",
    )

    embedding_parser = commands.add_parser(
        "embedding",
        help="Local infrastructure-embedding index commands.",
    )
    embedding_commands = embedding_parser.add_subparsers(
        dest="embedding_command",
        required=True,
    )
    embedding_commands.add_parser(
        "models",
        help="List embedding models visible through LM Studio.",
    )
    embedding_status = embedding_commands.add_parser(
        "status",
        help="Show the local semantic-index status for an embedding model.",
    )
    embedding_status.add_argument("--model", dest="embedding_model")
    embedding_rebuild = embedding_commands.add_parser(
        "rebuild",
        help="Rebuild the reconstructible local semantic index.",
    )
    embedding_rebuild.add_argument("--model", dest="embedding_model")

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


def _run_extract_command(app: AthenaApplication, args: argparse.Namespace) -> int:
    if args.extract_command == "chat":
        result = app.extraction.extract_chat(
            chat_id=args.chat_id,
            requested_model_id=args.model_id,
        )
        _print_extraction(result)
        print(f"Frozen extraction run: {result.processing_run.processing_run_id}")
        if not args.accept:
            return 0
        return _accept_extraction_result(app, result)

    if args.extract_command == "accept-run":
        try:
            result = app.extraction_snapshots.load(args.processing_run_id)
        except ExtractionSnapshotNotFoundError as exc:
            print(f"ATHENA extraction snapshot error: {exc}", file=sys.stderr)
            return 2
        print("Loaded frozen extraction proposal snapshot; Primary Model was not called.")
        _print_extraction(result)
        return _accept_extraction_result(app, result)

    raise RuntimeError(f"Unsupported extraction command: {args.extract_command!r}")


def _print_review_item(item: object) -> None:
    from athena.knowledge.review_service import ReviewItem

    if not isinstance(item, ReviewItem):
        raise TypeError("Expected ReviewItem.")
    print(f"Review: {item.review_id}")
    print(f"Type: {item.review_type}")
    print(f"Status: {item.status.value}")
    print(f"Confidence: {item.confidence:.3f}")
    print(f"Reason: {item.reason}")
    print(f"ProcessingRun: {item.processing_run_id}")
    print(f"ModelSignature: {item.model_signature_id}")
    print(f"Left: {item.left_entity_id} revision={item.left_revision_id}")
    print(f"Right: {item.right_entity_id} revision={item.right_revision_id}")
    if item.decision_actor_id is not None:
        print(f"Decision actor: {item.decision_actor_id}")
    if item.decision_reason is not None:
        print(f"Decision reason: {item.decision_reason}")


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
            f"current_commit_seq={status.current_commit_seq}"
        )
        return 0

    if args.embedding_command == "rebuild":
        status = app.semantic_search.rebuild(model_id)
        print(
            f"Embedding index rebuilt: model={model_id} "
            f"documents={status.document_count} dimensions={status.dimensions} "
            f"commit_seq={status.indexed_commit_seq}"
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
                f"lexical={hybrid_result.lexical_score:.4f} "
                f"semantic={hybrid_result.semantic_score:.4f} "
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
                SemanticSearchError,
            ) as exc:
                print(f"ATHENA context error: {exc}", file=sys.stderr)
                return 2

        if args.command == "search":
            try:
                return _run_search_command(app, args)
            except (SearchError, ModelProviderError) as exc:
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
