"""Persistent domain models for Exhaustive Research foundation state."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from enum import Enum


class ResearchMode(str, Enum):
    LOCAL_EXHAUSTIVE = "local_exhaustive"
    SCOPED_PROJECT = "scoped_project"
    LOCAL_PLUS_WEB = "local_plus_web"
    HISTORICAL_BACKFILL = "historical_backfill"
    DELTA = "delta"


class ResearchScopeState(str, Enum):
    DISCOVERING = "discovering"
    FROZEN = "frozen"
    RUNNING = "running"
    PARTIAL = "partial"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


class ResearchCandidateSetState(str, Enum):
    BUILDING = "building"
    FROZEN = "frozen"


class ResearchCandidateEligibility(str, Enum):
    ELIGIBLE = "eligible"
    EXCLUDED_DUPLICATE = "excluded_duplicate"


class ResearchWorkState(str, Enum):
    PENDING = "pending"
    SUCCESSFUL = "successful"
    IRRELEVANT = "irrelevant"
    FAILED = "failed"
    UNAVAILABLE = "unavailable"

    @property
    def terminal(self) -> bool:
        return self is not self.PENDING


@dataclass(frozen=True, slots=True)
class ResearchScopeRecord:
    scope_id: uuid.UUID
    job_id: uuid.UUID
    mode: ResearchMode
    query_text: str
    domains_json: str
    project_ids_json: str
    source_types_json: str
    explicit_source_ids_json: str
    time_start_us: int | None
    time_end_us: int | None
    internet_scope_json: str | None
    coverage_target: float
    snapshot_commit_seq: int
    model_id: str | None
    model_signature_id: uuid.UUID | None
    model_signature_sha256: bytes | None
    effective_context_limit: int | None
    output_reserve: int | None
    safety_margin: int | None
    token_estimator: str | None
    max_hierarchy_depth: int | None
    state: ResearchScopeState
    candidate_total: int
    processed_count: int
    successful_count: int
    irrelevant_count: int
    failed_count: int
    unavailable_count: int
    excluded_count: int
    coverage_ratio: float
    created_at_us: int
    updated_at_us: int


@dataclass(frozen=True, slots=True)
class ResearchCandidateSetRecord:
    candidate_set_id: uuid.UUID
    scope_id: uuid.UUID
    snapshot_commit_seq: int
    state: ResearchCandidateSetState
    candidate_total: int
    eligible_count: int
    excluded_count: int
    created_at_us: int
    frozen_at_us: int | None


@dataclass(frozen=True, slots=True)
class ResearchCandidateRecord:
    candidate_id: uuid.UUID
    candidate_set_id: uuid.UUID
    source_id: uuid.UUID
    ordinal: int
    content_sha256: bytes
    eligibility: ResearchCandidateEligibility
    duplicate_of_candidate_id: uuid.UUID | None
    created_at_us: int


@dataclass(frozen=True, slots=True)
class ResearchWorkItemRecord:
    work_item_id: uuid.UUID
    scope_id: uuid.UUID
    candidate_id: uuid.UUID
    state: ResearchWorkState
    idempotency_key: bytes
    source_processing_job_id: uuid.UUID | None
    source_analysis_job_id: uuid.UUID | None
    attempt_count: int
    created_at_us: int
    updated_at_us: int


@dataclass(frozen=True, slots=True)
class ResearchCoverage:
    candidate_total: int
    processed_count: int
    successful_count: int
    irrelevant_count: int
    failed_count: int
    unavailable_count: int
    excluded_count: int
    eligible_count: int
    coverage_ratio: float



class ResearchSynthesisStage(str, Enum):
    REDUCE = "reduce"
    FINAL = "final"


class ResearchSynthesisWorkState(str, Enum):
    PENDING = "pending"
    COMPLETED = "completed"
    SPLIT = "split"

    @property
    def terminal(self) -> bool:
        return self is not self.PENDING


class ResearchSynthesisInputKind(str, Enum):
    SOURCE_ANALYSIS_ARTIFACT = "source_analysis_artifact"
    RESEARCH_SYNTHESIS_ARTIFACT = "research_synthesis_artifact"


@dataclass(frozen=True, slots=True)
class ResearchSynthesisWorkItemRecord:
    work_item_id: uuid.UUID
    scope_id: uuid.UUID
    stage: ResearchSynthesisStage
    level: int
    ordinal: int
    state: ResearchSynthesisWorkState
    idempotency_key: bytes
    pipeline_version: str
    prompt_template_id: str
    prompt_template_version: str
    attempt_count: int
    created_at_us: int
    updated_at_us: int


@dataclass(frozen=True, slots=True)
class ResearchSynthesisWorkInputRecord:
    work_item_id: uuid.UUID
    ordinal: int
    input_kind: ResearchSynthesisInputKind
    source_analysis_artifact_id: uuid.UUID | None
    research_synthesis_artifact_id: uuid.UUID | None


@dataclass(frozen=True, slots=True)
class ResearchSynthesisArtifactRecord:
    artifact_id: uuid.UUID
    scope_id: uuid.UUID
    work_item_id: uuid.UUID
    artifact_kind: ResearchSynthesisStage
    level: int
    ordinal: int
    content_json: str
    content_hash: bytes
    processing_run_id: uuid.UUID
    created_at_us: int


@dataclass(frozen=True, slots=True)
class ResearchSynthesisEvidenceRecord:
    artifact_id: uuid.UUID
    work_item_id: uuid.UUID
    output_kind: str
    output_ordinal: int
    input_ordinal: int


@dataclass(frozen=True, slots=True)
class ResearchResultRecord:
    result_id: uuid.UUID
    scope_id: uuid.UUID
    final_artifact_id: uuid.UUID | None
    content_json: str
    content_hash: bytes
    snapshot_commit_seq: int
    model_signature_id: uuid.UUID | None
    synthesis_pipeline_version: str
    candidate_total: int
    processed_count: int
    successful_count: int
    irrelevant_count: int
    failed_count: int
    unavailable_count: int
    excluded_count: int
    coverage_ratio: float
    problem_sources_json: str
    created_at_us: int
