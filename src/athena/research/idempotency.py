"""Deterministic identity keys for durable Research work."""

from __future__ import annotations

import hashlib
import uuid
from collections.abc import Mapping, Sequence
from typing import Any

from athena.research.models import (
    ResearchSynthesisInputKind,
    ResearchSynthesisStage,
)
from athena.research.validation import _canonical_json_value


def _synthesis_work_idempotency_key(
    *,
    scope_id: uuid.UUID,
    stage: ResearchSynthesisStage,
    level: int,
    ordinal: int,
    inputs: Sequence[tuple[ResearchSynthesisInputKind, uuid.UUID]],
    descriptor: Mapping[str, Any],
    pipeline_version: str,
    prompt_template_id: str,
    prompt_template_version: str,
) -> bytes:
    identity = {
        "scope_id": str(scope_id),
        "stage": stage.value,
        "level": level,
        "ordinal": ordinal,
        "inputs": [
            {"kind": kind.value, "id": str(ref_id)}
            for kind, ref_id in inputs
        ],
        "descriptor": dict(descriptor),
        "pipeline_version": pipeline_version,
        "prompt_template_id": prompt_template_id,
        "prompt_template_version": prompt_template_version,
    }
    digest = hashlib.sha256()
    digest.update(b"athena.exhaustive-research.synthesis-work.v1\0")
    digest.update(_canonical_json_value(identity).encode("utf-8"))
    return digest.digest()

def _work_idempotency_key(
    *,
    scope_id: uuid.UUID,
    source_id: uuid.UUID,
    content_sha256: bytes,
) -> bytes:
    digest = hashlib.sha256()
    digest.update(b"athena.exhaustive-research.work.v1\0")
    digest.update(scope_id.bytes)
    digest.update(source_id.bytes)
    digest.update(content_sha256)
    return digest.digest()
