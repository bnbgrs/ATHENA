"""Text-level helpers for ATHENA's durable chat provenance envelope."""

from __future__ import annotations

import re

DURABLE_PROVENANCE_LABEL = "ATHENA_PROVENANCE"

_RESERVED_PROVENANCE_LINE_PATTERN = re.compile(
    rf"(?m)^\s*{DURABLE_PROVENANCE_LABEL}(?:\s|$)"
)
_DURABLE_PROVENANCE_SUFFIX_PATTERN = re.compile(
    rf"\n\n{DURABLE_PROVENANCE_LABEL} (?P<payload>\{{[^\n]*\}})\s*$"
)


def contains_reserved_provenance_line(text: str) -> bool:
    """Return whether model-authored text attempts to use ATHENA's reserved label."""

    return _RESERVED_PROVENANCE_LINE_PATTERN.search(text) is not None


def strip_durable_provenance_manifest(text: str) -> str:
    """Remove one system-appended durable provenance suffix from assistant text.

    The canonical archived assistant message retains the manifest. This helper is
    for derived/model-facing projections where the internal envelope must not be
    recursively treated as conversational or semantic content.
    """

    match = _DURABLE_PROVENANCE_SUFFIX_PATTERN.search(text)
    if match is None:
        return text
    return text[: match.start()].rstrip()
