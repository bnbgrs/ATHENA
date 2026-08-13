"""Persistent value objects for hierarchical large-source analysis."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from enum import Enum


class SourceAnalysisState(str, Enum):
    """Durable state of one source analysis."""

    RUNNING = "running"
    PARTIAL = "partial"
    COMPLETED = "completed"


class AnalysisStage(str, Enum):
    """Hierarchical work stages."""

    MAP = "map"
    REDUCE = "reduce"
    FINAL = "final"


class AnalysisWorkState(str, Enum):
    """Durable state of one idempotent semantic work unit."""

    PENDING = "pending"
    COMPLETED = "completed"
    FAILED = "failed"
    SPLIT = "split"


class AnalysisInputKind(str, Enum):
    """Kinds of immutable inputs accepted by an analysis work unit."""

    SOURCE_ANCHOR = "source_anchor"
    ARTIFACT = "artifact"


@dataclass(frozen=True, slots=True)
class SourceAnalysisRecord:
    analysis_id: uuid.UUID
    job_id: uuid.UUID
    source_id: uuid.UUID
    representation_id: uuid.UUID
    question: str
    state: SourceAnalysisState
    model_signature_id: uuid.UUID
    pipeline_version: str
    effective_context_limit: int
    output_reserve: int
    safety_margin: int
    token_estimator: str
    max_hierarchy_depth: int
    total_map_units: int
    completed_map_units: int
    failed_map_units: int
    coverage: float
    final_artifact_id: uuid.UUID | None
    created_at_us: int
    updated_at_us: int


@dataclass(frozen=True, slots=True)
class SourceAnalysisWorkItem:
    work_item_id: uuid.UUID
    analysis_id: uuid.UUID
    stage: AnalysisStage
    level: int
    ordinal: int
    state: AnalysisWorkState
    idempotency_key: bytes
    attempt_count: int
    created_at_us: int
    updated_at_us: int


@dataclass(frozen=True, slots=True)
class SourceAnalysisArtifact:
    artifact_id: uuid.UUID
    analysis_id: uuid.UUID
    work_item_id: uuid.UUID
    artifact_kind: AnalysisStage
    level: int
    ordinal: int
    content_json: str
    content_hash: bytes
    processing_run_id: uuid.UUID
    created_at_us: int


@dataclass(frozen=True, slots=True)
class SourceAnalysisWorkInput:
    work_item_id: uuid.UUID
    ordinal: int
    input_kind: AnalysisInputKind
    source_anchor_id: uuid.UUID | None
    artifact_id: uuid.UUID | None
