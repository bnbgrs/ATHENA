from __future__ import annotations

from athena.chat.provenance import (
    contains_reserved_provenance_line,
    strip_canonical_promotion_trace,
    strip_durable_provenance_manifest,
    strip_model_facing_assistant_trace,
    strip_turn_local_grounding_markers,
)


def test_strip_durable_manifest_removes_only_system_suffix() -> None:
    content = (
        "Berlin is one answer. [CTX-001]\n\n"
        'ATHENA_PROVENANCE {"athena_provenance_version":2,"evidence":[]}'
    )

    assert strip_durable_provenance_manifest(content) == (
        "Berlin is one answer. [CTX-001]"
    )


def test_strip_durable_manifest_does_not_remove_inline_discussion() -> None:
    content = "The term ATHENA_PROVENANCE is discussed here. [MODEL-PRIOR]"

    assert strip_durable_provenance_manifest(content) == content


def test_reserved_manifest_detection_is_line_scoped() -> None:
    assert contains_reserved_provenance_line(
        'ATHENA_PROVENANCE {"fake":true} [MODEL-PRIOR]'
    )
    assert not contains_reserved_provenance_line(
        "The term ATHENA_PROVENANCE is reserved. [MODEL-PRIOR]"
    )



def test_strip_turn_local_grounding_markers_removes_all_ctx_marker_forms() -> None:
    content = (
        "Canonical [CTX-001], "
        "user [USER-STATEMENT:CTX-002], "
        "conversation [CONVERSATION:CTX-003], "
        "source [SOURCE:CTX-004], "
        "research [RESEARCH:CTX-005], "
        "news [NEWS:CTX-006], "
        "inference [INFERENCE:CTX-007,CTX-008]. "
        "[MODEL-PRIOR] [UNKNOWN]"
    )

    cleaned = strip_turn_local_grounding_markers(
        content
    )

    assert "CTX-" not in cleaned
    assert "[MODEL-PRIOR]" in cleaned
    assert "[UNKNOWN]" in cleaned


def test_model_facing_assistant_trace_removes_manifest_and_turn_local_markers() -> None:
    content = (
        "Athenafalke uses 7319 [CTX-001].\n\n"
        'ATHENA_PROVENANCE '
        '{"athena_provenance_version":3,"evidence":[]}'
    )

    assert strip_model_facing_assistant_trace(
        content
    ) == "Athenafalke uses 7319."


def test_durable_manifest_helper_itself_still_preserves_inline_ctx_marker() -> None:
    content = (
        "Athenafalke uses 7319 [CTX-001].\n\n"
        'ATHENA_PROVENANCE '
        '{"athena_provenance_version":3,"evidence":[]}'
    )

    assert strip_durable_provenance_manifest(
        content
    ) == "Athenafalke uses 7319 [CTX-001]."



def test_canonical_promotion_trace_removes_all_grounding_control_annotations() -> None:
    content = (
        "Canonical fact [CTX-001]. "
        "Source fact [SOURCE:CTX-002]. "
        "Research fact [RESEARCH:CTX-003]. "
        "News fact [NEWS:CTX-004]. "
        "Combined fact [INFERENCE:CTX-001]. "
        "Prior fact [MODEL-PRIOR]. "
        "Missing fact [UNKNOWN].\n\n"
        'ATHENA_PROVENANCE '
        '{"athena_provenance_version":3,"evidence":[]}'
    )

    cleaned = strip_canonical_promotion_trace(
        content
    )

    assert cleaned == (
        "Canonical fact. "
        "Source fact. "
        "Research fact. "
        "News fact. "
        "Combined fact. "
        "Prior fact. "
        "Missing fact."
    )

    assert "CTX-" not in cleaned
    assert "ATHENA_PROVENANCE" not in cleaned
    assert "[MODEL-PRIOR]" not in cleaned
    assert "[UNKNOWN]" not in cleaned
