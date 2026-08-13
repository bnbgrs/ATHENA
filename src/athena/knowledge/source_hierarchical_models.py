"""Persistent value objects for durable hierarchical source Knowledge extraction."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from enum import Enum


class SourceHierarchicalExtractionState(str, Enum):
    """Durable state of one hierarchical source extraction."""

    RUNNING = "running"
    PARTIAL = "partial"
    COMPLETED = "completed"


class SourceExtractionStage(str, Enum):
    """Durable hierarchical extraction stages."""

    BATCH = "batch"
    MERGE = "merge"
    AUDIT = "audit"
    FINAL = "final"


class SourceExtractionWorkState(str, Enum):
    """Durable state of one idempotent extraction work unit."""

    PENDING = "pending"
    COMPLETED = "completed"
    FAILED = "failed"
    SPLIT = "split"


class SourceExtractionInputKind(str, Enum):
    """Immutable input kinds for hierarchical extraction work."""

    SOURCE_ANCHOR = "source_anchor"
    ARTIFACT = "artifact"


@dataclass(frozen=True, slots=True)
class SourceHierarchicalExtractionRecord:
    extraction_id: uuid.UUID
    job_id: uuid.UUID
    analysis_id: uuid.UUID
    final_artifact_id: uuid.UUID
    state: SourceHierarchicalExtractionState
    model_signature_id: uuid.UUID
    pipeline_version: str
    effective_context_limit: int
    output_reserve: int
    safety_margin: int
    token_estimator: str
    prompt_template_id: str
    prompt_template_version: str
    max_hierarchy_depth: int
    total_batches: int
    completed_batches: int
    failed_batches: int
    final_work_artifact_id: uuid.UUID | None
    created_at_us: int
    updated_at_us: int

    @property
    def input_budget(self) -> int:
        return self.effective_context_limit - self.output_reserve - self.safety_margin


@dataclass(frozen=True, slots=True)
class SourceHierarchicalExtractionEvidence:
    extraction_id: uuid.UUID
    sequence_no: int
    source_anchor_id: uuid.UUID
    quoted_hash: bytes


@dataclass(frozen=True, slots=True)
class SourceHierarchicalExtractionWorkItem:
    work_item_id: uuid.UUID
    extraction_id: uuid.UUID
    stage: SourceExtractionStage
    level: int
    ordinal: int
    state: SourceExtractionWorkState
    idempotency_key: bytes
    attempt_count: int
    created_at_us: int
    updated_at_us: int


@dataclass(frozen=True, slots=True)
class SourceHierarchicalExtractionArtifact:
    artifact_id: uuid.UUID
    extraction_id: uuid.UUID
    work_item_id: uuid.UUID
    artifact_kind: SourceExtractionStage
    level: int
    ordinal: int
    content_json: str
    content_hash: bytes
    processing_run_id: uuid.UUID
    created_at_us: int


@dataclass(frozen=True, slots=True)
class SourceHierarchicalExtractionWorkInput:
    work_item_id: uuid.UUID
    ordinal: int
    input_kind: SourceExtractionInputKind
    source_anchor_id: uuid.UUID | None
    artifact_id: uuid.UUID | None
