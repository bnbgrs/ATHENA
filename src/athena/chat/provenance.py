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

_TURN_LOCAL_GROUNDING_MARKER_PATTERN = re.compile(
    r"(?:"
    r"\[(?:USER-STATEMENT:|CONVERSATION:|SOURCE:|RESEARCH:|NEWS:)?CTX-\d{3}\]"
    r"|\[INFERENCE:\s*CTX-\d{3}"
    r"(?:\s*,\s*CTX-\d{3})*\s*\]"
    r")"
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



def strip_turn_local_grounding_markers(text: str) -> str:
    """Remove ephemeral grounding markers from a derived historical projection.

    CTX identifiers are valid only inside the grounding contract of the turn
    that created them. Persisted chat content remains unchanged; this helper is
    only for later model-facing or Derived-State projections.
    """

    cleaned = _TURN_LOCAL_GROUNDING_MARKER_PATTERN.sub(
        "",
        text,
    )

    # Remove punctuation/spacing artifacts left when one or more citations were
    # attached to ordinary prose. Preserve line structure and semantic text.
    cleaned = re.sub(
        r"[ \t]+([,.;:!?])",
        r"\1",
        cleaned,
    )
    cleaned = re.sub(
        r",\s*([.!?])",
        r"\1",
        cleaned,
    )
    cleaned = re.sub(
        r"[ \t]{2,}",
        " ",
        cleaned,
    )
    cleaned = re.sub(
        r"[ \t]+\n",
        "\n",
        cleaned,
    )

    return cleaned.strip()


def strip_model_facing_assistant_trace(text: str) -> str:
    """Project archived assistant text without reusable ATHENA trace tokens."""

    return strip_turn_local_grounding_markers(
        strip_durable_provenance_manifest(text)
    )



def strip_canonical_promotion_trace(text: str) -> str:
    """Project assistant prose into canonical semantic content.

    Canonical Knowledge and Claims must not persist turn-local grounding
    identifiers, model-control provenance markers, or the durable technical
    provenance envelope. The original chat revision remains the stable
    provenance input for the canonical entity.
    """

    cleaned = strip_model_facing_assistant_trace(text)

    cleaned = re.sub(
        r"\[(?:MODEL-PRIOR|UNKNOWN)\]",
        "",
        cleaned,
    )

    cleaned = re.sub(
        r"[ \t]+([,.;:!?])",
        r"\1",
        cleaned,
    )

    cleaned = re.sub(
        r",\s*([.!?])",
        r"\1",
        cleaned,
    )

    cleaned = re.sub(
        r"[ \t]{2,}",
        " ",
        cleaned,
    )

    cleaned = re.sub(
        r"[ \t]+\n",
        "\n",
        cleaned,
    )

    return cleaned.strip()
