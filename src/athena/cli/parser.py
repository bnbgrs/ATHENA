"""Argument parsing boundary for the ATHENA command-line interface."""

from __future__ import annotations

import argparse
import json
import uuid
from pathlib import Path

from athena.jobs.models import JobPriority, WaitingReason
from athena.jobs.scheduler import (
    SchedulerLane,
)
from athena.knowledge.models import (
    ClaimKind,
    EpistemicStatus,
    KnowledgeKind,
)
from athena.memory.models import (
    MemoryKind,
    MemoryScopeKind,
    MemorySensitivity,
)
from athena.operations.cli import (
    add_operational_parsers,
)
from athena.version import __version__


def _uuid_argument(value: str) -> uuid.UUID:
    try:
        return uuid.UUID(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"invalid UUID: {value!r}") from exc

def _json_object_argument(value: str) -> dict[str, object]:
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError as exc:
        raise argparse.ArgumentTypeError(f"invalid JSON object: {exc.msg}") from exc
    if not isinstance(parsed, dict):
        raise argparse.ArgumentTypeError("value must be a JSON object")
    return parsed

def _lease_token_argument(value: str) -> bytes:
    try:
        token = bytes.fromhex(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("lease token must be hexadecimal") from exc
    if len(token) != 32:
        raise argparse.ArgumentTypeError("lease token must encode exactly 32 bytes")
    return token

def _waiting_reason_argument(value: str) -> WaitingReason:
    try:
        return WaitingReason(value)
    except ValueError as exc:
        allowed = ", ".join(item.value for item in WaitingReason)
        raise argparse.ArgumentTypeError(
            f"invalid waiting reason {value!r}; choose one of: {allowed}"
        ) from exc

def _knowledge_kind_argument(value: str) -> KnowledgeKind:
    try:
        return KnowledgeKind(value)
    except ValueError as exc:
        allowed = ", ".join(item.value for item in KnowledgeKind)
        raise argparse.ArgumentTypeError(
            f"invalid knowledge kind {value!r}; choose one of: {allowed}"
        ) from exc

def _memory_kind_argument(value: str) -> MemoryKind:
    try:
        return MemoryKind(value)
    except ValueError as exc:
        allowed = ", ".join(item.value for item in MemoryKind)
        raise argparse.ArgumentTypeError(
            f"invalid memory kind {value!r}; choose one of: {allowed}"
        ) from exc

def _memory_scope_kind_argument(value: str) -> MemoryScopeKind:
    try:
        return MemoryScopeKind(value)
    except ValueError as exc:
        allowed = ", ".join(item.value for item in MemoryScopeKind)
        raise argparse.ArgumentTypeError(
            f"invalid memory scope {value!r}; choose one of: {allowed}"
        ) from exc

def _memory_sensitivity_argument(value: str) -> MemorySensitivity:
    try:
        return MemorySensitivity(value)
    except ValueError as exc:
        allowed = ", ".join(item.value for item in MemorySensitivity)
        raise argparse.ArgumentTypeError(
            f"invalid memory sensitivity {value!r}; choose one of: {allowed}"
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
        help=(
            "Persist a user message and normally stream a local model reply. "
            "Unambiguous explicit Personal Memory commands are handled locally."
        ),
    )
    send_parser.add_argument("chat_id", type=_uuid_argument)
    send_parser.add_argument("content", help="Message text. Quote text containing spaces.")
    send_parser.add_argument(
        "--model",
        dest="model_id",
        help="Exact LM Studio model identifier. Required if multiple LLMs are loaded.",
    )
    send_parser.add_argument(
        "--memory",
        action="store_true",
        help="Retrieve bounded local memory before calling the Primary Model.",
    )
    send_parser.add_argument(
        "--sources",
        action="store_true",
        help=(
            "Retrieve imported Raw Archive sources, materialize persistent "
            "SourceAnchors, and require source-grounded citations."
        ),
    )
    send_parser.add_argument(
        "--adaptive",
        action="store_true",
        help=(
            "Automatically choose the smallest mature local chat path: direct, "
            "Memory/Knowledge, Prior Research, News/Evidence, Raw Archive, "
            "or unified local retrieval. Planner v2 performs no additional "
            "routing-model call."
        ),
    )
    send_parser.add_argument(
        "--embedding-model",
        dest="embedding_model_id",
        help="Exact LM Studio embedding model identifier for --memory or --sources.",
    )
    send_parser.add_argument(
        "--memory-max-tokens",
        type=int,
        default=1200,
        help="Estimated-token budget for retrieved memory (128-64000).",
    )
    send_parser.add_argument(
        "--memory-max-items",
        type=int,
        default=8,
        help="Maximum retrieved memory items (1-100).",
    )
    send_parser.add_argument(
        "--memory-max-preferences",
        type=int,
        default=8,
        help="Maximum Personal Memory USER PREFERENCE items (0-100).",
    )
    send_parser.add_argument(
        "--memory-scope-kind",
        type=_memory_scope_kind_argument,
        help="Optional current Personal Memory scope kind for scoped preferences.",
    )
    send_parser.add_argument(
        "--memory-scope-id",
        type=_uuid_argument,
        help="Exact current scope entity ID for project/workflow/client Memory.",
    )
    send_parser.add_argument(
        "--memory-context-limit",
        type=int,
        help=(
            "Fail-closed effective Primary Model context limit. Defaults to the "
            "loaded LM Studio context when reported."
        ),
    )
    send_parser.add_argument(
        "--memory-output-reserve",
        type=int,
        default=2048,
        help="Reserved output tokens kept free before the model call.",
    )
    send_parser.add_argument(
        "--memory-safety-margin",
        type=int,
        default=256,
        help="Additional estimated-token safety margin for provider overhead.",
    )
    send_parser.add_argument(
        "--source-max-tokens",
        type=int,
        default=1200,
        help="Estimated-token budget for retrieved source evidence (128-64000).",
    )
    send_parser.add_argument(
        "--source-max-items",
        type=int,
        default=8,
        help="Maximum retrieved source items (1-100).",
    )
    model_prior_group = send_parser.add_mutually_exclusive_group()
    model_prior_group.add_argument(
        "--memory-allow-model-prior",
        dest="memory_allow_model_prior",
        action="store_true",
        default=None,
        help=(
            "Explicitly allow labeled [MODEL-PRIOR] facts in grounded memory "
            "answers. This is the default for memory chat."
        ),
    )
    model_prior_group.add_argument(
        "--memory-no-model-prior",
        dest="memory_allow_model_prior",
        action="store_false",
        help=(
            "Disable Primary Model prior knowledge for this memory answer; "
            "retrieved evidence and [UNKNOWN] remain available."
        ),
    )
    source_prior_group = send_parser.add_mutually_exclusive_group()
    source_prior_group.add_argument(
        "--source-allow-model-prior",
        dest="source_allow_model_prior",
        action="store_true",
        default=None,
        help=(
            "Explicitly allow labeled [MODEL-PRIOR] facts in source-grounded "
            "answers. This is the default for source chat."
        ),
    )
    source_prior_group.add_argument(
        "--source-no-model-prior",
        dest="source_allow_model_prior",
        action="store_false",
        help=(
            "Disable Primary Model prior knowledge for this source-grounded "
            "answer; source evidence and [UNKNOWN] remain available."
        ),
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

    memory_parser = commands.add_parser(
        "memory",
        help="Explicit-user Personal Memory commands.",
    )
    memory_commands = memory_parser.add_subparsers(
        dest="memory_command",
        required=True,
    )

    memory_remember = memory_commands.add_parser(
        "remember",
        help="Persist one explicit user preference without calling a model.",
    )
    memory_remember.add_argument("content")
    memory_remember.add_argument(
        "--kind", type=_memory_kind_argument, default=MemoryKind.OTHER
    )
    memory_remember.add_argument(
        "--scope-kind", type=_memory_scope_kind_argument, default=MemoryScopeKind.GLOBAL
    )
    memory_remember.add_argument("--scope-id", type=_uuid_argument)
    memory_remember.add_argument(
        "--sensitivity",
        type=_memory_sensitivity_argument,
        default=MemorySensitivity.NORMAL,
    )

    memory_show = memory_commands.add_parser("show", help="Show one Personal Memory head.")
    memory_show.add_argument("memory_id", type=_uuid_argument)

    memory_history = memory_commands.add_parser(
        "history", help="Show immutable revisions of one Personal Memory entry."
    )
    memory_history.add_argument("memory_id", type=_uuid_argument)

    memory_list = memory_commands.add_parser("list", help="List active Personal Memory.")
    memory_list.add_argument("--limit", type=int, default=50)
    memory_list.add_argument(
        "--include-inactive", action="store_true", help="Also show disabled entries."
    )

    memory_revise = memory_commands.add_parser(
        "revise", help="Create a new explicit-user revision of Personal Memory."
    )
    memory_revise.add_argument("memory_id", type=_uuid_argument)
    memory_revise.add_argument("content")
    memory_revise.add_argument("--kind", type=_memory_kind_argument)
    memory_revise.add_argument("--scope-kind", type=_memory_scope_kind_argument)
    memory_revise.add_argument("--scope-id", type=_uuid_argument)
    memory_revise.add_argument("--sensitivity", type=_memory_sensitivity_argument)

    for command_name, help_text in (
        ("confirm", "Confirm the current Personal Memory entry."),
        ("disable", "Disable one Personal Memory entry."),
        ("enable", "Re-enable one disabled Personal Memory entry."),
        ("delete", "Logically delete one Personal Memory entry."),
    ):
        command = memory_commands.add_parser(command_name, help=help_text)
        command.add_argument("memory_id", type=_uuid_argument)

    memory_reset = memory_commands.add_parser(
        "reset", help="Logically delete all Personal Memory without touching Knowledge/Archive."
    )
    memory_reset.add_argument(
        "--yes",
        action="store_true",
        help="Required confirmation for the destructive bulk reset.",
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

    extract_source_analysis = extract_commands.add_parser(
        "source-analysis",
        help="Generate grounded Knowledge/Claim proposals from one completed source analysis.",
    )
    extract_source_analysis.add_argument("analysis_id", type=_uuid_argument)
    extract_source_analysis.add_argument("--model", dest="model_id")
    extract_source_analysis.add_argument("--context-limit", type=int)
    extract_source_analysis.add_argument("--output-reserve", type=int)
    extract_source_analysis.add_argument("--safety-margin", type=int)
    extract_source_analysis.add_argument(
        "--accept",
        action="store_true",
        help="After displaying the grounded proposal set, ask for explicit user acceptance.",
    )

    extract_accept_source_run = extract_commands.add_parser(
        "accept-source-run",
        help="Load and accept one frozen successful source-analysis extraction run without calling the model again.",
    )
    extract_accept_source_run.add_argument("processing_run_id", type=_uuid_argument)

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

    source_parser = commands.add_parser(
        "source",
        help="Source capture, retained representation, and Derived State commands.",
    )
    source_commands = source_parser.add_subparsers(
        dest="source_command",
        required=True,
    )
    source_import = source_commands.add_parser(
        "import",
        help="Capture one local file into the immutable Raw Archive.",
    )
    source_import.add_argument("path", type=Path)
    source_show = source_commands.add_parser(
        "show",
        help="Show one captured Source and its BlobRecord.",
    )
    source_show.add_argument("source_id", type=_uuid_argument)
    source_verify = source_commands.add_parser(
        "verify",
        help="Stream and verify the stored original bytes for one Source.",
    )
    source_verify.add_argument("source_id", type=_uuid_argument)
    source_list = source_commands.add_parser(
        "list",
        help="List recently captured Sources.",
    )
    source_list.add_argument(
        "--limit",
        type=int,
        default=50,
        help="Maximum number of Sources to print (1-500).",
    )
    source_represent_text = source_commands.add_parser(
        "represent-text",
        help="Build a deterministic retained UTF-8 text representation from one TXT/Markdown Source.",
    )
    source_represent_text.add_argument("source_id", type=_uuid_argument)
    source_represent_pdf = source_commands.add_parser(
        "represent-pdf",
        help="Build retained native PDF text plus a stable page-offset map.",
    )
    source_represent_pdf.add_argument("source_id", type=_uuid_argument)
    source_represent_docx = source_commands.add_parser(
        "represent-docx",
        help="Build retained DOCX text plus a stable technical structure map.",
    )
    source_represent_docx.add_argument("source_id", type=_uuid_argument)
    source_represent_html = source_commands.add_parser(
        "represent-html",
        help="Build cleaned retained HTML text plus a stable DOM-derived structure map.",
    )
    source_represent_html.add_argument("source_id", type=_uuid_argument)
    source_representation_show = source_commands.add_parser(
        "representation-show",
        help="Show one immutable SourceRepresentation and its BlobRecord.",
    )
    source_representation_show.add_argument("representation_id", type=_uuid_argument)
    source_representation_verify = source_commands.add_parser(
        "representation-verify",
        help="Verify the stored bytes of one SourceRepresentation.",
    )
    source_representation_verify.add_argument("representation_id", type=_uuid_argument)
    source_representation_read = source_commands.add_parser(
        "representation-read",
        help="Print one verified UTF-8 text SourceRepresentation.",
    )
    source_representation_read.add_argument("representation_id", type=_uuid_argument)
    source_representation_list = source_commands.add_parser(
        "representation-list",
        help="List retained representations for one Source.",
    )
    source_representation_list.add_argument("source_id", type=_uuid_argument)
    source_representation_list.add_argument(
        "--limit",
        type=int,
        default=50,
        help="Maximum number of representations to print (1-500).",
    )
    source_representation_pages = source_commands.add_parser(
        "representation-pages",
        help="List retained PDF page-map offsets for one SourceRepresentation.",
    )
    source_representation_pages.add_argument("representation_id", type=_uuid_argument)
    source_representation_structures = source_commands.add_parser(
        "representation-structures",
        help="List retained document structure for DOCX/HTML SourceRepresentations.",
    )
    source_representation_structures.add_argument("representation_id", type=_uuid_argument)
    source_chunk_text = source_commands.add_parser(
        "chunk-text",
        help="Build a deterministic Derived SourceChunk set from one retained text representation.",
    )
    source_chunk_text.add_argument("representation_id", type=_uuid_argument)
    source_chunk_show = source_commands.add_parser(
        "chunk-show",
        help="Show one reconstructible Derived SourceChunk.",
    )
    source_chunk_show.add_argument("chunk_id", type=_uuid_argument)
    source_chunk_verify = source_commands.add_parser(
        "chunk-verify",
        help="Verify one SourceChunk against its retained SourceRepresentation.",
    )
    source_chunk_verify.add_argument("chunk_id", type=_uuid_argument)
    source_chunk_read = source_commands.add_parser(
        "chunk-read",
        help="Print the exact text slice stored for one SourceChunk.",
    )
    source_chunk_read.add_argument("chunk_id", type=_uuid_argument)
    source_chunk_list = source_commands.add_parser(
        "chunk-list",
        help="List Derived SourceChunks for one SourceRepresentation.",
    )
    source_chunk_list.add_argument("representation_id", type=_uuid_argument)
    source_chunk_list.add_argument(
        "--limit",
        type=int,
        default=500,
        help="Maximum number of chunks to print (1-5000).",
    )
    source_anchor_from_chunk = source_commands.add_parser(
        "anchor-from-chunk",
        help="Materialize a durable text SourceAnchor from one verified Derived SourceChunk.",
    )
    source_anchor_from_chunk.add_argument("chunk_id", type=_uuid_argument)
    source_anchor_from_structure = source_commands.add_parser(
        "anchor-from-structure",
        help="Materialize a durable structured_path/table_cell SourceAnchor.",
    )
    source_anchor_from_structure.add_argument("structure_id", type=_uuid_argument)
    source_anchor_create_text = source_commands.add_parser(
        "anchor-create-text",
        help="Materialize a durable text SourceAnchor from a retained representation range.",
    )
    source_anchor_create_text.add_argument("representation_id", type=_uuid_argument)
    source_anchor_create_text.add_argument("start_offset", type=int)
    source_anchor_create_text.add_argument("end_offset", type=int)
    source_anchor_show = source_commands.add_parser(
        "anchor-show",
        help="Show one persistent SourceAnchor.",
    )
    source_anchor_show.add_argument("anchor_id", type=_uuid_argument)
    source_anchor_verify = source_commands.add_parser(
        "anchor-verify",
        help="Verify one SourceAnchor against its retained SourceRepresentation.",
    )
    source_anchor_verify.add_argument("anchor_id", type=_uuid_argument)
    source_anchor_read = source_commands.add_parser(
        "anchor-read",
        help="Print the exact retained text referenced by one SourceAnchor.",
    )
    source_anchor_read.add_argument("anchor_id", type=_uuid_argument)
    source_anchor_list = source_commands.add_parser(
        "anchor-list",
        help="List persistent SourceAnchors for one Source.",
    )
    source_anchor_list.add_argument("source_id", type=_uuid_argument)
    source_anchor_list.add_argument(
        "--limit", type=int, default=500, help="Maximum number of anchors to print (1-5000)."
    )
    source_search = source_commands.add_parser(
        "search",
        help="Search current Derived SourceChunks with stable Source/Representation anchors.",
    )
    source_search.add_argument("query", help="Archive retrieval query.")
    source_search.add_argument(
        "--limit",
        type=int,
        default=20,
        help="Maximum number of archive results (1-200).",
    )
    source_search.add_argument(
        "--source",
        dest="archive_source_id",
        type=_uuid_argument,
        help="Restrict retrieval to one Source.",
    )
    source_search.add_argument(
        "--representation",
        dest="archive_representation_id",
        type=_uuid_argument,
        help="Restrict retrieval to one retained SourceRepresentation.",
    )
    source_search.add_argument(
        "--rebuild",
        action="store_true",
        help="Rebuild archive FTS from current SourceChunks before searching.",
    )
    source_search.add_argument(
        "--hybrid",
        action="store_true",
        help="Fuse archive FTS with local semantic embeddings.",
    )
    source_search.add_argument(
        "--embedding-model",
        help="LM Studio embedding model id for --hybrid.",
    )
    source_embedding_status = source_commands.add_parser(
        "search-embedding-status",
        help="Show semantic-index status for Derived SourceChunks.",
    )
    source_embedding_status.add_argument("--model", dest="embedding_model")
    source_embedding_rebuild = source_commands.add_parser(
        "search-embedding-rebuild",
        help="Rebuild semantic vectors for current Derived SourceChunks.",
    )
    source_embedding_rebuild.add_argument("--model", dest="embedding_model")

    job_parser = commands.add_parser(
        "job",
        help="Durable background-job and checkpoint commands.",
    )
    job_commands = job_parser.add_subparsers(dest="job_command", required=True)
    job_create = job_commands.add_parser(
        "create",
        help="Create one durable queued job from a registered job type.",
    )
    job_create.add_argument("job_type")
    job_create.add_argument(
        "--priority",
        type=int,
        choices=range(0, 6),
        default=int(JobPriority.NORMAL),
        help="Priority class 0=data_safety through 5=maintenance.",
    )
    job_create.add_argument("--scope-json", type=_json_object_argument)
    job_create.add_argument("--config-json", type=_json_object_argument)
    job_show = job_commands.add_parser("show", help="Show one durable job.")
    job_show.add_argument("job_id", type=_uuid_argument)
    job_list = job_commands.add_parser("list", help="List durable jobs.")
    job_list.add_argument("--limit", type=int, default=100)
    job_acquire = job_commands.add_parser(
        "acquire",
        help="Acquire a time-limited worker lease and fencing sequence.",
    )
    job_acquire.add_argument("job_id", type=_uuid_argument)
    job_acquire.add_argument("--worker", required=True)
    job_acquire.add_argument("--lease-seconds", type=int, default=60)
    job_heartbeat = job_commands.add_parser(
        "heartbeat",
        help="Renew a live worker lease.",
    )
    job_heartbeat.add_argument("job_id", type=_uuid_argument)
    job_heartbeat.add_argument("lease_token", type=_lease_token_argument)
    job_heartbeat.add_argument("--extend-seconds", type=int, default=60)
    job_checkpoint = job_commands.add_parser(
        "checkpoint",
        help="Persist one confirmed checkpoint under the current worker fence.",
    )
    job_checkpoint.add_argument("job_id", type=_uuid_argument)
    job_checkpoint.add_argument("lease_token", type=_lease_token_argument)
    job_checkpoint.add_argument("--stage")
    job_checkpoint.add_argument("--progress-json", type=_json_object_argument)
    job_checkpoint.add_argument("--input-json", type=_json_object_argument)
    job_checkpoint.add_argument("--output-json", type=_json_object_argument)
    job_checkpoint.add_argument("--resume-json", type=_json_object_argument)
    job_checkpoint.add_argument("--commit-id", type=_uuid_argument)
    job_checkpoints = job_commands.add_parser(
        "checkpoints",
        help="List confirmed checkpoints for one job.",
    )
    job_checkpoints.add_argument("job_id", type=_uuid_argument)
    job_complete = job_commands.add_parser("complete", help="Complete a leased job.")
    job_complete.add_argument("job_id", type=_uuid_argument)
    job_complete.add_argument("lease_token", type=_lease_token_argument)
    job_wait = job_commands.add_parser(
        "wait",
        help="Release a live lease into a persistent waiting state.",
    )
    job_wait.add_argument("job_id", type=_uuid_argument)
    job_wait.add_argument("lease_token", type=_lease_token_argument)
    job_wait.add_argument("reason", type=_waiting_reason_argument)
    job_wait.add_argument("--next-run-at-us", type=int)
    job_wake = job_commands.add_parser(
        "wake",
        help="Return a waiting job to the durable queue.",
    )
    job_wake.add_argument("job_id", type=_uuid_argument)
    job_cancel = job_commands.add_parser(
        "cancel",
        help="Cancel an idle job or request cancellation from its current worker.",
    )
    job_cancel.add_argument("job_id", type=_uuid_argument)
    job_cancel_ack = job_commands.add_parser(
        "cancel-ack",
        help="Acknowledge a running job's cancellation under its live lease.",
    )
    job_cancel_ack.add_argument("job_id", type=_uuid_argument)
    job_cancel_ack.add_argument("lease_token", type=_lease_token_argument)
    job_pause = job_commands.add_parser(
        "pause",
        help="Pause an idle queued/waiting job at a safe boundary.",
    )
    job_pause.add_argument("job_id", type=_uuid_argument)
    job_resume = job_commands.add_parser("resume", help="Resume a paused job.")
    job_resume.add_argument("job_id", type=_uuid_argument)
    job_source_process = job_commands.add_parser(
        "source-process",
        help="Queue one reproducibly configured durable source.process job.",
    )
    job_source_process.add_argument("source_id", type=_uuid_argument)
    job_source_process.add_argument(
        "--priority",
        type=int,
        choices=range(0, 6),
        default=int(JobPriority.NORMAL),
    )
    job_source_step = job_commands.add_parser(
        "source-step",
        help="Execute one durable source-processing stage under an existing lease.",
    )
    job_source_step.add_argument("job_id", type=_uuid_argument)
    job_source_step.add_argument("lease_token", type=_lease_token_argument)
    job_source_step.add_argument("--extend-seconds", type=int, default=120)
    job_run_source = job_commands.add_parser(
        "run-source",
        help="Acquire and run a queued source.process job to a terminal state.",
    )
    job_run_source.add_argument("job_id", type=_uuid_argument)
    job_run_source.add_argument("--worker", default="athena-cli-source-worker")
    job_run_source.add_argument("--lease-seconds", type=int, default=120)
    job_source_analyze = job_commands.add_parser(
        "source-analyze",
        help="Queue hierarchical durable analysis of one processed source.",
    )
    job_source_analyze.add_argument("source_id", type=_uuid_argument)
    job_source_analyze.add_argument("question")
    job_source_analyze.add_argument("--model", dest="model_id")
    job_source_analyze.add_argument("--context-limit", type=int)
    job_source_analyze.add_argument("--output-reserve", type=int)
    job_source_analyze.add_argument("--safety-margin", type=int)
    job_source_analyze.add_argument("--max-depth", type=int, default=12)
    job_source_analyze.add_argument(
        "--priority",
        type=int,
        choices=range(0, 6),
        default=int(JobPriority.NORMAL),
    )
    job_analysis_step = job_commands.add_parser(
        "analysis-step",
        help="Execute one durable source-analysis boundary under an existing lease.",
    )
    job_analysis_step.add_argument("job_id", type=_uuid_argument)
    job_analysis_step.add_argument("lease_token", type=_lease_token_argument)
    job_analysis_step.add_argument("--extend-seconds", type=int, default=120)
    job_run_analysis = job_commands.add_parser(
        "run-analysis",
        help="Acquire and run a queued source.analyze job until completed or waiting.",
    )
    job_run_analysis.add_argument("job_id", type=_uuid_argument)
    job_run_analysis.add_argument("--worker", default="athena-cli-analysis-worker")
    job_run_analysis.add_argument("--lease-seconds", type=int, default=120)
    job_analysis_show = job_commands.add_parser(
        "analysis-show", help="Show one persistent source analysis."
    )
    job_analysis_show.add_argument("analysis_id", type=_uuid_argument)
    job_analysis_artifacts = job_commands.add_parser(
        "analysis-artifacts", help="List persistent artifacts for one source analysis."
    )
    job_analysis_artifacts.add_argument("analysis_id", type=_uuid_argument)
    job_source_extract = job_commands.add_parser(
        "source-extract",
        help="Queue durable hierarchical Knowledge extraction for one completed source analysis.",
    )
    job_source_extract.add_argument("analysis_id", type=_uuid_argument)
    job_source_extract.add_argument("--model", dest="model_id")
    job_source_extract.add_argument("--context-limit", type=int)
    job_source_extract.add_argument("--output-reserve", type=int)
    job_source_extract.add_argument("--safety-margin", type=int)
    job_source_extract.add_argument("--max-depth", type=int, default=16)
    job_source_extract.add_argument(
        "--priority",
        type=int,
        choices=range(0, 6),
        default=int(JobPriority.NORMAL),
    )
    job_extraction_step = job_commands.add_parser(
        "extraction-step",
        help="Execute one durable hierarchical source-extraction boundary under an existing lease.",
    )
    job_extraction_step.add_argument("job_id", type=_uuid_argument)
    job_extraction_step.add_argument("lease_token", type=_lease_token_argument)
    job_extraction_step.add_argument("--extend-seconds", type=int, default=120)
    job_run_extraction = job_commands.add_parser(
        "run-extraction",
        help="Acquire and run a queued source.extract job until completed or waiting.",
    )
    job_run_extraction.add_argument("job_id", type=_uuid_argument)
    job_run_extraction.add_argument("--worker", default="athena-cli-extraction-worker")
    job_run_extraction.add_argument("--lease-seconds", type=int, default=120)
    job_extraction_show = job_commands.add_parser(
        "extraction-show", help="Show one persistent hierarchical source extraction."
    )
    job_extraction_show.add_argument("extraction_id", type=_uuid_argument)
    job_extraction_artifacts = job_commands.add_parser(
        "extraction-artifacts",
        help="List persistent artifacts for one hierarchical source extraction.",
    )
    job_extraction_artifacts.add_argument("extraction_id", type=_uuid_argument)
    job_embedding_rebuild = job_commands.add_parser(
        "embedding-rebuild",
        help="Queue a durable SourceChunk embedding rebuild pinned to current generation.",
    )
    job_embedding_rebuild.add_argument("--model", required=True)
    job_embedding_rebuild.add_argument(
        "--batch-size",
        type=int,
        default=32,
        help="Provider batch size (1-256).",
    )
    job_embedding_rebuild.add_argument(
        "--priority",
        type=int,
        choices=range(0, 6),
        default=int(JobPriority.BACKGROUND),
    )
    job_embedding_step = job_commands.add_parser(
        "embedding-step",
        help="Execute one durable embedding batch/finalization boundary.",
    )
    job_embedding_step.add_argument("job_id", type=_uuid_argument)
    job_embedding_step.add_argument("lease_token", type=_lease_token_argument)
    job_embedding_step.add_argument("--extend-seconds", type=int, default=120)
    job_run_embedding = job_commands.add_parser(
        "run-embedding",
        help="Acquire and run a queued embedding.rebuild job until completed or waiting.",
    )
    job_run_embedding.add_argument("job_id", type=_uuid_argument)
    job_run_embedding.add_argument("--worker", default="athena-cli-embedding-worker")
    job_run_embedding.add_argument("--lease-seconds", type=int, default=120)
    job_scheduler_once = job_commands.add_parser(
        "scheduler-once",
        help="Select and dispatch at most one eligible durable job.",
    )
    job_scheduler_once.add_argument("--worker", default="athena-scheduler")
    job_scheduler_drain = job_commands.add_parser(
        "scheduler-drain",
        help="Process currently eligible supported jobs until the queue is idle.",
    )
    job_scheduler_drain.add_argument("--worker", default="athena-scheduler")
    job_scheduler_drain.add_argument("--max-jobs", type=int, default=100)
    job_scheduler_run = job_commands.add_parser(
        "scheduler-run",
        help="Run the low-frequency durable scheduler loop until interrupted.",
    )
    job_scheduler_run.add_argument("--worker", default="athena-scheduler")
    job_scheduler_run.add_argument(
        "--max-ticks",
        type=int,
        help="Optional bounded tick count for diagnostics/tests.",
    )
    job_scheduler_run.add_argument(
        "--lane",
        choices=(
            "supervisor",
            SchedulerLane.ALL.value,
            SchedulerLane.CONTROL.value,
            SchedulerLane.PROVIDER.value,
        ),
        default="supervisor",
        help=(
            "Scheduler execution lane. The default supervisor runs one "
            "provider lane and one control lane in separate processes."
        ),
    )
    job_scheduler_run.add_argument(
        "--supervised-child",
        action="store_true",
        help=argparse.SUPPRESS,
    )
    job_scheduler_run.add_argument(
        "--started-file",
        type=Path,
        help=argparse.SUPPRESS,
    )
    job_scheduler_run.add_argument(
        "--ready-file",
        type=Path,
        help=argparse.SUPPRESS,
    )
    job_scheduler_run.add_argument(
        "--supervisor-watchdog",
        action="store_true",
        help=argparse.SUPPRESS,
    )
    job_commands.add_parser(
        "recover",
        help="Recover only jobs whose worker lease has expired.",
    )

    add_operational_parsers(commands)

    model_parser = commands.add_parser("model", help="Local model provider commands.")
    model_commands = model_parser.add_subparsers(dest="model_command", required=True)
    model_commands.add_parser("status", help="Check LM Studio provider health.")
    model_commands.add_parser("list", help="List models discovered from LM Studio.")

    return parser
