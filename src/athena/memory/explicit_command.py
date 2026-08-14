"""Deterministic explicit-user Personal Memory command recognition."""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass

from athena.memory.models import MemoryKind, MemoryScopeKind


class ExplicitMemoryCommandError(ValueError):
    """Raised when an explicit Memory command cannot be routed safely."""


@dataclass(frozen=True, slots=True)
class ExplicitMemoryIntent:
    """One conservative direct-user Personal Memory intent."""

    memory_content: str
    memory_kind: MemoryKind
    scope_kind: MemoryScopeKind
    scope_entity_id: uuid.UUID | None


_GENERAL_COMMAND_PATTERNS = (
    re.compile(
        r"^\s*(?:bitte\s+)?(?:merke\s+dir|speichere)\s*"
        r"(?:,\s*)?(?:dass\s+|:\s*)(?P<body>.+?)\s*$",
        re.IGNORECASE,
    ),
    re.compile(
        r"^\s*(?:please\s+)?(?:remember|save)\s*"
        r"(?:that\s+|:\s*)(?P<body>.+?)\s*$",
        re.IGNORECASE,
    ),
    re.compile(
        r"^\s*ab\s+jetzt\s+(?P<body>.+?)\s*$",
        re.IGNORECASE,
    ),
    re.compile(
        r"^\s*from\s+now\s+on\s*,?\s*(?P<body>.+?)\s*$",
        re.IGNORECASE,
    ),
)

_PROJECT_COMMAND_PATTERNS = (
    re.compile(
        r"^\s*f[üu]r\s+dieses\s+projekt\s+"
        r"(?:m[öo]chte\s+ich|will\s+ich)\s+(?P<body>.+?)\s*$",
        re.IGNORECASE,
    ),
    re.compile(
        r"^\s*for\s+this\s+project\s+"
        r"(?:i\s+want|i\s+prefer)\s+(?P<body>.+?)\s*$",
        re.IGNORECASE,
    ),
)

_PREFERENCE_PATTERNS = (
    re.compile(r"\bbevorzug\w*", re.IGNORECASE),
    re.compile(r"\bm[öo]chte\b", re.IGNORECASE),
    re.compile(r"\bmoechte\b", re.IGNORECASE),
    re.compile(r"\bbitte\b", re.IGNORECASE),
    re.compile(r"\bsoll\w*", re.IGNORECASE),
    re.compile(r"\bimmer\b", re.IGNORECASE),
    re.compile(r"\bnie\b", re.IGNORECASE),
    re.compile(r"\bkeine?\b", re.IGNORECASE),
    re.compile(r"\bnicht\b", re.IGNORECASE),
    re.compile(r"\bprefer\w*", re.IGNORECASE),
    re.compile(r"\bwant\b", re.IGNORECASE),
    re.compile(r"\bplease\b", re.IGNORECASE),
    re.compile(r"\bshould\b", re.IGNORECASE),
    re.compile(r"\balways\b", re.IGNORECASE),
    re.compile(r"\bnever\b", re.IGNORECASE),
    re.compile(r"\bdo\s+not\b", re.IGNORECASE),
    re.compile(r"\bdon't\b", re.IGNORECASE),
)

# These patterns identify the object of collaboration with ATHENA. Value-only
# adjectives such as "kurz", "detailliert", "deutsch" or "englisch" are
# deliberately absent: they may classify the MemoryKind only after the command
# has independently been established as a collaboration preference.
_COLLABORATION_PATTERNS = (
    re.compile(r"\bantwort\w*", re.IGNORECASE),
    re.compile(r"\bschreib\w*", re.IGNORECASE),
    re.compile(r"\bmarkdown\b", re.IGNORECASE),
    re.compile(r"\btabell\w*", re.IGNORECASE),
    re.compile(r"\bsprache\w*", re.IGNORECASE),
    re.compile(r"\brückfrag\w*", re.IGNORECASE),
    re.compile(r"\brueckfrag\w*", re.IGNORECASE),
    re.compile(r"\bmodell\w*", re.IGNORECASE),
    re.compile(r"\bprovider\w*", re.IGNORECASE),
    re.compile(r"\btools?\b", re.IGNORECASE),
    re.compile(r"\bwerkzeug\w*", re.IGNORECASE),
    re.compile(r"\bworkflow\w*", re.IGNORECASE),
    re.compile(r"\barbeitsablauf\w*", re.IGNORECASE),
    re.compile(r"\bexport\w*", re.IGNORECASE),
    re.compile(r"\bpfad\w*", re.IGNORECASE),
    re.compile(r"\bgit\b", re.IGNORECASE),
    re.compile(r"\bcommit\w*", re.IGNORECASE),
    re.compile(r"\btests?\b", re.IGNORECASE),
    re.compile(r"\bprüf\w*", re.IGNORECASE),
    re.compile(r"\bpruef\w*", re.IGNORECASE),
    re.compile(r"\banswers?\b", re.IGNORECASE),
    re.compile(r"\brepl(?:y|ies)\b", re.IGNORECASE),
    re.compile(r"\bwrite\b", re.IGNORECASE),
    re.compile(r"\btables?\b", re.IGNORECASE),
    re.compile(r"\blanguage\w*", re.IGNORECASE),
    re.compile(r"\bmodels?\b", re.IGNORECASE),
    re.compile(r"\bpaths?\b", re.IGNORECASE),
)


def is_explicit_persistence_command(content: str) -> bool:
    """Return whether text uses one of the explicit local-persistence forms."""
    original = content.strip()
    if not original:
        return False
    patterns = _PROJECT_COMMAND_PATTERNS + _GENERAL_COMMAND_PATTERNS
    return any(pattern.match(original) is not None for pattern in patterns)


def parse_explicit_personal_memory_command(
    content: str,
    *,
    scope_kind: MemoryScopeKind | None = None,
    scope_entity_id: uuid.UUID | None = None,
) -> ExplicitMemoryIntent | None:
    """Recognize only explicit collaboration-preference commands.

    The parser is intentionally conservative. It never calls a model and never
    treats an arbitrary factual "remember/save" request as Personal Memory.
    """
    original = content.strip()
    if not original:
        return None

    body: str | None = None
    project_scoped = False
    for pattern in _PROJECT_COMMAND_PATTERNS:
        match = pattern.match(original)
        if match is not None:
            body = match.group("body").strip()
            project_scoped = True
            break

    if body is None:
        for pattern in _GENERAL_COMMAND_PATTERNS:
            match = pattern.match(original)
            if match is not None:
                body = match.group("body").strip()
                break

    if body is None or not body:
        return None
    if not _is_collaboration_preference(original):
        return None

    if project_scoped:
        if scope_kind is not MemoryScopeKind.PROJECT or scope_entity_id is None:
            raise ExplicitMemoryCommandError(
                "Project-scoped Personal Memory command requires "
                "--memory-scope-kind project and --memory-scope-id."
            )
        resolved_scope_kind = MemoryScopeKind.PROJECT
        resolved_scope_entity_id = scope_entity_id
    else:
        resolved_scope_kind = scope_kind or MemoryScopeKind.GLOBAL
        if resolved_scope_kind is MemoryScopeKind.GLOBAL:
            if scope_entity_id is not None:
                raise ExplicitMemoryCommandError(
                    "Global Personal Memory command must not have --memory-scope-id."
                )
            resolved_scope_entity_id = None
        else:
            if scope_entity_id is None:
                raise ExplicitMemoryCommandError(
                    "Scoped Personal Memory command requires --memory-scope-id."
                )
            resolved_scope_entity_id = scope_entity_id

    return ExplicitMemoryIntent(
        memory_content=body,
        memory_kind=_infer_memory_kind(original),
        scope_kind=resolved_scope_kind,
        scope_entity_id=resolved_scope_entity_id,
    )


def _is_collaboration_preference(content: str) -> bool:
    return _matches_any(content, _PREFERENCE_PATTERNS) and _matches_any(
        content,
        _COLLABORATION_PATTERNS,
    )


def _matches_any(content: str, patterns: tuple[re.Pattern[str], ...]) -> bool:
    return any(pattern.search(content) is not None for pattern in patterns)


def _infer_memory_kind(content: str) -> MemoryKind:
    normalized = content.casefold()
    language_markers = (
        "sprache",
        "deutsch",
        "englisch",
        "language",
        "german",
        "english",
    )
    detail_markers = (
        "kurz",
        "knapp",
        "ausführ",
        "ausfuehr",
        "detaill",
        "concise",
        "brief",
        "detail",
    )
    workflow_markers = (
        "workflow",
        "arbeitsablauf",
        "export",
        "pfad",
        "path",
        "git",
        "commit",
        "test",
        "prüf",
        "pruef",
    )
    response_markers = (
        "antwort",
        "schreib",
        "markdown",
        "tabelle",
        "format",
        "answer",
        "reply",
        "write",
        "table",
    )
    if any(marker in normalized for marker in language_markers):
        return MemoryKind.LANGUAGE_PREFERENCE
    if any(marker in normalized for marker in detail_markers):
        return MemoryKind.DETAIL_PREFERENCE
    if any(marker in normalized for marker in ("rückfrag", "rueckfrag")):
        return MemoryKind.INTERACTION_PREFERENCE
    if any(marker in normalized for marker in ("modell", "provider", "model")):
        return MemoryKind.MODEL_PREFERENCE
    if any(marker in normalized for marker in ("tool", "werkzeug", "python")):
        return MemoryKind.TOOL_PREFERENCE
    if any(marker in normalized for marker in workflow_markers):
        return MemoryKind.WORKFLOW_PREFERENCE
    if any(marker in normalized for marker in response_markers):
        return MemoryKind.RESPONSE_STYLE
    return MemoryKind.OTHER
