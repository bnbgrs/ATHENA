from __future__ import annotations

from athena.chat.provenance import (
    contains_reserved_provenance_line,
    strip_durable_provenance_manifest,
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
