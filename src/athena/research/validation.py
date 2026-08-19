"""Pure validation and canonicalization for durable Research state."""

from __future__ import annotations

import json
import uuid
from collections.abc import Mapping, Sequence
from typing import Any

from athena.research.errors import ResearchStateError


def _required_text(value: str, field: str) -> str:
    normalized = value.strip()
    if not normalized:
        raise ResearchStateError(f"{field} must not be empty.")
    return normalized

def _canonical_json_value(value: Any) -> str:
    try:
        return json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
    except (TypeError, ValueError) as exc:
        raise ResearchStateError(
            "Research synthesis state must be finite canonical JSON."
        ) from exc

def _canonical_json_object(value: Mapping[str, Any]) -> str:
    return _canonical_json_value(dict(value))

def _validated_synthesis_source_evidence(
    content: Mapping[str, Any],
    evidence: Sequence[tuple[str, int, uuid.UUID]],
) -> tuple[tuple[str, int, uuid.UUID], ...]:
    outputs: dict[str, list[Any]] = {}

    for field, kind in (
        ("findings", "finding"),
        ("contradictions", "contradiction"),
    ):
        value = content.get(field)
        if not isinstance(value, list):
            raise ResearchStateError(
                f"Research synthesis content field {field!r} must be an array."
            )
        outputs[kind] = value

    normalized: set[tuple[str, int, uuid.UUID]] = set()

    for kind, output_ordinal, source_artifact_id in evidence:
        if kind not in outputs:
            raise ResearchStateError(
                f"Unsupported Research synthesis source-evidence "
                f"output kind {kind!r}."
            )

        if (
            output_ordinal < 0
            or output_ordinal >= len(outputs[kind])
        ):
            raise ResearchStateError(
                "Research synthesis source-evidence output ordinal "
                "is out of range."
            )

        if not isinstance(source_artifact_id, uuid.UUID):
            raise ResearchStateError(
                "Research synthesis terminal source backlink "
                "must be a UUID."
            )

        normalized.add(
            (
                kind,
                output_ordinal,
                source_artifact_id,
            )
        )

    expected_outputs = {
        (kind, output_ordinal)
        for kind, values in outputs.items()
        for output_ordinal in range(len(values))
    }

    covered_outputs = {
        (kind, output_ordinal)
        for kind, output_ordinal, _source_id in normalized
    }

    if covered_outputs != expected_outputs:
        raise ResearchStateError(
            "Every Research synthesis finding and contradiction "
            "requires at least one terminal SourceAnalysis backlink."
        )

    return tuple(
        sorted(
            normalized,
            key=lambda item: (
                item[0],
                item[1],
                item[2].bytes,
            ),
        )
    )

def _validated_synthesis_evidence(
    content: Mapping[str, Any],
    evidence: Sequence[tuple[str, int, int]],
) -> tuple[tuple[str, int, int], ...]:
    outputs: dict[str, list[Any]] = {}
    for field, kind in (
        ("findings", "finding"),
        ("contradictions", "contradiction"),
    ):
        value = content.get(field)
        if not isinstance(value, list):
            raise ResearchStateError(
                f"Research synthesis content field {field!r} must be an array."
            )
        outputs[kind] = value

    normalized: set[tuple[str, int, int]] = set()
    for kind, output_ordinal, input_ordinal in evidence:
        if kind not in outputs:
            raise ResearchStateError(
                f"Unsupported Research synthesis evidence output kind {kind!r}."
            )
        if output_ordinal < 0 or output_ordinal >= len(outputs[kind]):
            raise ResearchStateError(
                "Research synthesis evidence output ordinal is out of range."
            )
        if input_ordinal < 0:
            raise ResearchStateError(
                "Research synthesis evidence input ordinal must not be negative."
            )
        normalized.add((kind, output_ordinal, input_ordinal))

    expected_outputs = {
        (kind, output_ordinal)
        for kind, values in outputs.items()
        for output_ordinal in range(len(values))
    }
    covered_outputs = {
        (kind, output_ordinal)
        for kind, output_ordinal, _input_ordinal in normalized
    }
    if covered_outputs != expected_outputs:
        raise ResearchStateError(
            "Every Research synthesis finding and contradiction requires at least "
            "one explicit durable input backlink."
        )
    return tuple(
        sorted(
            normalized,
            key=lambda item: (item[0], item[1], item[2]),
        )
    )

def _json_string_array(raw: str, field: str) -> tuple[str, ...]:
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ResearchStateError(f"{field} contains invalid JSON.") from exc
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        raise ResearchStateError(f"{field} must be a JSON string array.")
    return tuple(value)
