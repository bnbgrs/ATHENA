"""SQLite row-to-record mapping for durable Exhaustive Research state."""

from __future__ import annotations

import sqlite3

from athena.common.ids import uuid_from_blob
from athena.research.models import (
    ResearchCandidateEligibility,
    ResearchCandidateRecord,
    ResearchCandidateSetRecord,
    ResearchCandidateSetState,
    ResearchMode,
    ResearchResultRecord,
    ResearchScopeRecord,
    ResearchScopeState,
    ResearchSynthesisArtifactRecord,
    ResearchSynthesisEvidenceRecord,
    ResearchSynthesisInputKind,
    ResearchSynthesisStage,
    ResearchSynthesisWorkInputRecord,
    ResearchSynthesisWorkItemRecord,
    ResearchSynthesisWorkState,
    ResearchWorkItemRecord,
    ResearchWorkState,
)


def _scope_from_row(row: sqlite3.Row) -> ResearchScopeRecord:
    return ResearchScopeRecord(
        scope_id=uuid_from_blob(bytes(row["scope_id"])),
        job_id=uuid_from_blob(bytes(row["job_id"])),
        mode=ResearchMode(str(row["mode"])),
        query_text=str(row["query_text"]),
        domains_json=str(row["domains_json"]),
        project_ids_json=str(row["project_ids_json"]),
        source_types_json=str(row["source_types_json"]),
        explicit_source_ids_json=str(row["explicit_source_ids_json"]),
        time_start_us=(
            int(row["time_start_us"]) if row["time_start_us"] is not None else None
        ),
        time_end_us=(
            int(row["time_end_us"]) if row["time_end_us"] is not None else None
        ),
        internet_scope_json=(
            str(row["internet_scope_json"])
            if row["internet_scope_json"] is not None
            else None
        ),
        coverage_target=float(row["coverage_target"]),
        snapshot_commit_seq=int(row["snapshot_commit_seq"]),
        model_id=str(row["model_id"]) if row["model_id"] is not None else None,
        model_signature_id=(
            uuid_from_blob(bytes(row["model_signature_id"]))
            if row["model_signature_id"] is not None
            else None
        ),
        model_signature_sha256=(
            bytes(row["model_signature_sha256"])
            if row["model_signature_sha256"] is not None
            else None
        ),
        effective_context_limit=(
            int(row["effective_context_limit"])
            if row["effective_context_limit"] is not None
            else None
        ),
        output_reserve=(
            int(row["output_reserve"]) if row["output_reserve"] is not None else None
        ),
        safety_margin=(
            int(row["safety_margin"]) if row["safety_margin"] is not None else None
        ),
        token_estimator=(
            str(row["token_estimator"]) if row["token_estimator"] is not None else None
        ),
        max_hierarchy_depth=(
            int(row["max_hierarchy_depth"])
            if row["max_hierarchy_depth"] is not None
            else None
        ),
        state=ResearchScopeState(str(row["state"])),
        candidate_total=int(row["candidate_total"]),
        processed_count=int(row["processed_count"]),
        successful_count=int(row["successful_count"]),
        irrelevant_count=int(row["irrelevant_count"]),
        failed_count=int(row["failed_count"]),
        unavailable_count=int(row["unavailable_count"]),
        excluded_count=int(row["excluded_count"]),
        coverage_ratio=float(row["coverage_ratio"]),
        created_at_us=int(row["created_at_us"]),
        updated_at_us=int(row["updated_at_us"]),
    )

def _candidate_set_from_row(row: sqlite3.Row) -> ResearchCandidateSetRecord:
    return ResearchCandidateSetRecord(
        candidate_set_id=uuid_from_blob(bytes(row["candidate_set_id"])),
        scope_id=uuid_from_blob(bytes(row["scope_id"])),
        snapshot_commit_seq=int(row["snapshot_commit_seq"]),
        state=ResearchCandidateSetState(str(row["state"])),
        candidate_total=int(row["candidate_total"]),
        eligible_count=int(row["eligible_count"]),
        excluded_count=int(row["excluded_count"]),
        created_at_us=int(row["created_at_us"]),
        frozen_at_us=(
            int(row["frozen_at_us"]) if row["frozen_at_us"] is not None else None
        ),
    )

def _candidate_from_row(row: sqlite3.Row) -> ResearchCandidateRecord:
    return ResearchCandidateRecord(
        candidate_id=uuid_from_blob(bytes(row["candidate_id"])),
        candidate_set_id=uuid_from_blob(bytes(row["candidate_set_id"])),
        source_id=uuid_from_blob(bytes(row["source_id"])),
        ordinal=int(row["ordinal"]),
        content_sha256=bytes(row["content_sha256"]),
        eligibility=ResearchCandidateEligibility(str(row["eligibility_state"])),
        duplicate_of_candidate_id=(
            uuid_from_blob(bytes(row["duplicate_of_candidate_id"]))
            if row["duplicate_of_candidate_id"] is not None
            else None
        ),
        created_at_us=int(row["created_at_us"]),
    )

def _work_item_from_row(row: sqlite3.Row) -> ResearchWorkItemRecord:
    return ResearchWorkItemRecord(
        work_item_id=uuid_from_blob(bytes(row["work_item_id"])),
        scope_id=uuid_from_blob(bytes(row["scope_id"])),
        candidate_id=uuid_from_blob(bytes(row["candidate_id"])),
        state=ResearchWorkState(str(row["state"])),
        idempotency_key=bytes(row["idempotency_key"]),
        source_processing_job_id=(
            uuid_from_blob(bytes(row["source_processing_job_id"]))
            if row["source_processing_job_id"] is not None
            else None
        ),
        source_analysis_job_id=(
            uuid_from_blob(bytes(row["source_analysis_job_id"]))
            if row["source_analysis_job_id"] is not None
            else None
        ),
        attempt_count=int(row["attempt_count"]),
        created_at_us=int(row["created_at_us"]),
        updated_at_us=int(row["updated_at_us"]),
    )

def _synthesis_work_item_from_row(
    row: sqlite3.Row,
) -> ResearchSynthesisWorkItemRecord:
    return ResearchSynthesisWorkItemRecord(
        work_item_id=uuid_from_blob(bytes(row["work_item_id"])),
        scope_id=uuid_from_blob(bytes(row["scope_id"])),
        stage=ResearchSynthesisStage(str(row["stage"])),
        level=int(row["level"]),
        ordinal=int(row["ordinal"]),
        state=ResearchSynthesisWorkState(str(row["state"])),
        idempotency_key=bytes(row["idempotency_key"]),
        pipeline_version=str(row["pipeline_version"]),
        prompt_template_id=str(row["prompt_template_id"]),
        prompt_template_version=str(row["prompt_template_version"]),
        attempt_count=int(row["attempt_count"]),
        created_at_us=int(row["created_at_us"]),
        updated_at_us=int(row["updated_at_us"]),
    )

def _synthesis_work_input_from_row(
    row: sqlite3.Row,
) -> ResearchSynthesisWorkInputRecord:
    return ResearchSynthesisWorkInputRecord(
        work_item_id=uuid_from_blob(bytes(row["work_item_id"])),
        ordinal=int(row["ordinal"]),
        input_kind=ResearchSynthesisInputKind(str(row["input_kind"])),
        source_analysis_artifact_id=(
            uuid_from_blob(bytes(row["source_analysis_artifact_id"]))
            if row["source_analysis_artifact_id"] is not None
            else None
        ),
        research_synthesis_artifact_id=(
            uuid_from_blob(bytes(row["research_synthesis_artifact_id"]))
            if row["research_synthesis_artifact_id"] is not None
            else None
        ),
    )

def _synthesis_artifact_from_row(
    row: sqlite3.Row,
) -> ResearchSynthesisArtifactRecord:
    return ResearchSynthesisArtifactRecord(
        artifact_id=uuid_from_blob(bytes(row["artifact_id"])),
        scope_id=uuid_from_blob(bytes(row["scope_id"])),
        work_item_id=uuid_from_blob(bytes(row["work_item_id"])),
        artifact_kind=ResearchSynthesisStage(str(row["artifact_kind"])),
        level=int(row["level"]),
        ordinal=int(row["ordinal"]),
        content_json=str(row["content_json"]),
        content_hash=bytes(row["content_hash"]),
        processing_run_id=uuid_from_blob(bytes(row["processing_run_id"])),
        created_at_us=int(row["created_at_us"]),
    )

def _synthesis_evidence_from_row(
    row: sqlite3.Row,
) -> ResearchSynthesisEvidenceRecord:
    return ResearchSynthesisEvidenceRecord(
        artifact_id=uuid_from_blob(bytes(row["artifact_id"])),
        work_item_id=uuid_from_blob(bytes(row["work_item_id"])),
        output_kind=str(row["output_kind"]),
        output_ordinal=int(row["output_ordinal"]),
        input_ordinal=int(row["input_ordinal"]),
    )

def _research_result_from_row(row: sqlite3.Row) -> ResearchResultRecord:
    return ResearchResultRecord(
        result_id=uuid_from_blob(bytes(row["result_id"])),
        scope_id=uuid_from_blob(bytes(row["scope_id"])),
        final_artifact_id=(
            uuid_from_blob(bytes(row["final_artifact_id"]))
            if row["final_artifact_id"] is not None
            else None
        ),
        content_json=str(row["content_json"]),
        content_hash=bytes(row["content_hash"]),
        snapshot_commit_seq=int(row["snapshot_commit_seq"]),
        model_signature_id=(
            uuid_from_blob(bytes(row["model_signature_id"]))
            if row["model_signature_id"] is not None
            else None
        ),
        synthesis_pipeline_version=str(row["synthesis_pipeline_version"]),
        candidate_total=int(row["candidate_total"]),
        processed_count=int(row["processed_count"]),
        successful_count=int(row["successful_count"]),
        irrelevant_count=int(row["irrelevant_count"]),
        failed_count=int(row["failed_count"]),
        unavailable_count=int(row["unavailable_count"]),
        excluded_count=int(row["excluded_count"]),
        coverage_ratio=float(row["coverage_ratio"]),
        problem_sources_json=str(row["problem_sources_json"]),
        created_at_us=int(row["created_at_us"]),
    )
