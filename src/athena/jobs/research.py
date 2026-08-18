"""Durable parent orchestrator for Exhaustive Research source work."""

from __future__ import annotations

import json
import sqlite3
import uuid
from dataclasses import dataclass

from athena.chat.generation import ModelSelectionError
from athena.common.time import utc_now_us
from athena.jobs.models import CheckpointRecord, JobRecord, JobState, WaitingReason
from athena.jobs.repository import JobTransitionError
from athena.jobs.service import DurableJobService
from athena.jobs.source_processing import DurableSourceProcessingWorker
from athena.model.adapters.lm_studio import (
    ModelProviderError,
    ProviderContextLimitError,
    ProviderOutputLimitError,
    ProviderUnavailableError,
)
from athena.research.models import (
    ResearchCandidateRecord,
    ResearchCoverage,
    ResearchScopeRecord,
    ResearchScopeState,
    ResearchSynthesisStage,
    ResearchSynthesisWorkItemRecord,
    ResearchSynthesisWorkState,
    ResearchWorkItemRecord,
    ResearchWorkState,
)
from athena.research.repository import (
    ResearchNotFoundError,
    ResearchRepository,
)
from athena.research.service import PIPELINE_VERSION, ResearchService
from athena.research.synthesis_service import (
    PIPELINE_VERSION as SYNTHESIS_PIPELINE_VERSION,
)
from athena.research.synthesis_service import (
    ResearchSynthesisConfigurationError,
    ResearchSynthesisInputTooLargeError,
    ResearchSynthesisOutputError,
    ResearchSynthesisService,
)
from athena.source.analysis_models import AnalysisStage, SourceAnalysisState
from athena.source.analysis_service import (
    AnalysisPinnedConfiguration,
    SourceAnalysisConfigurationError,
    SourceAnalysisModelDriftError,
)
from athena.source.blob_store import BlobIntegrityError, BlobStoreError


class ResearchJobError(RuntimeError):
    """Raised when durable Exhaustive Research cannot safely advance."""


@dataclass(frozen=True, slots=True)
class ResearchStepResult:
    job: JobRecord
    scope: ResearchScopeRecord | None
    work_item: ResearchWorkItemRecord | None
    completed_stage: str | None
    checkpoint: CheckpointRecord | None
    child_job_id: uuid.UUID | None
    done: bool
    waiting: bool


class DurableResearchWorker:
    """Coordinate source processing and SourceAnalysis without duplicating either engine."""

    def __init__(
        self,
        *,
        jobs: DurableJobService,
        service: ResearchService,
        source_processing: DurableSourceProcessingWorker,
        synthesis: ResearchSynthesisService,
    ) -> None:
        self.jobs = jobs
        self.service = service
        self.repository: ResearchRepository = service.repository
        self.source_processing = source_processing
        self.source_analysis = service.source_analysis
        self.synthesis = synthesis

    def step(
        self,
        job_id: uuid.UUID,
        *,
        lease_token: bytes,
        extend_seconds: int = 120,
    ) -> ResearchStepResult:
        if extend_seconds <= 0:
            raise ValueError("extend_seconds must be positive.")
        job = self.jobs.get(job_id)
        self._validate_job(job)
        if job.state is JobState.CANCEL_REQUESTED:
            return self._cancel(job, lease_token)
        if job.state is not JobState.RUNNING:
            raise JobTransitionError(
                f"research.exhaustive job {job_id} is not running ({job.state.value!r})."
            )
        job = self.jobs.heartbeat(
            job_id,
            lease_token=lease_token,
            extend_seconds=extend_seconds,
        )

        scope = self.repository.get_scope_for_job(job_id)
        if scope is None:
            scope = self.service.initialize(job_id)
            checkpoint = self._checkpoint(
                job,
                lease_token,
                scope,
                current_stage="research_initialized",
                work_item=None,
                child_job_id=None,
                detail={"scope_id": str(scope.scope_id)},
            )
            return self._result(
                job_id, scope, None, "initialize", checkpoint, child_job_id=None
            )

        try:
            self.repository.get_candidate_set(scope.scope_id)
        except ResearchNotFoundError:
            candidate_set = self.service.freeze_candidates(job_id)
            scope = self.repository.get_scope(scope.scope_id)
            checkpoint = self._checkpoint(
                job,
                lease_token,
                scope,
                current_stage="research_candidates_frozen",
                work_item=None,
                child_job_id=None,
                detail={
                    "candidate_set_id": str(candidate_set.candidate_set_id),
                    "candidate_total": candidate_set.candidate_total,
                    "eligible_count": candidate_set.eligible_count,
                    "excluded_count": candidate_set.excluded_count,
                },
            )
            return self._result(
                job_id,
                scope,
                None,
                "candidate_freeze",
                checkpoint,
                child_job_id=None,
            )

        if scope.state is ResearchScopeState.COMPLETED:
            return self._complete_persisted_result(
                job,
                lease_token,
                scope,
                stage="result_recovered",
            )

        if scope.state is ResearchScopeState.FROZEN:
            scope = self.repository.mark_scope_state_fenced(
                scope.scope_id,
                parent_job_id=job_id,
                lease_token=lease_token,
                state=ResearchScopeState.RUNNING,
            )
            checkpoint = self._checkpoint(
                job,
                lease_token,
                scope,
                current_stage="research_running",
                work_item=None,
                child_job_id=None,
                detail={"state": scope.state.value},
            )
            return self._result(
                job_id, scope, None, "running", checkpoint, child_job_id=None
            )
        if scope.state is not ResearchScopeState.RUNNING:
            raise ResearchJobError(
                f"Research scope cannot advance from state {scope.state.value!r}."
            )

        work_item = self.repository.next_pending_work(scope.scope_id)
        if work_item is None:
            return self._advance_synthesis(
                job,
                lease_token,
                scope,
                extend_seconds=extend_seconds,
            )

        candidate = self.repository.get_candidate(work_item.candidate_id)

        if work_item.source_analysis_job_id is not None:
            return self._reconcile_analysis_child(
                job, lease_token, scope, work_item
            )

        # If a processing child is already linked, reconcile it before relying on
        # externally-created readiness. This avoids leaving queued redundant work.
        if work_item.source_processing_job_id is not None:
            process_child = self.jobs.get(work_item.source_processing_job_id)
            if process_child.state is JobState.COMPLETED:
                if not self._source_ready(candidate.source_id):
                    return self._commit_work_state(
                        job,
                        lease_token,
                        scope,
                        work_item,
                        ResearchWorkState.FAILED,
                        stage="source_processing_incomplete",
                        child_job_id=process_child.job_id,
                    )
            elif process_child.state in {JobState.FAILED, JobState.CANCELLED}:
                return self._commit_work_state(
                    job,
                    lease_token,
                    scope,
                    work_item,
                    ResearchWorkState.FAILED,
                    stage="source_processing_failed",
                    child_job_id=process_child.job_id,
                )
            else:
                return self._wait_on_child(
                    job,
                    lease_token,
                    scope,
                    work_item,
                    process_child,
                    stage="waiting_source_processing",
                )

        if not self._source_ready(candidate.source_id):
            availability = self._raw_source_availability(candidate.source_id)
            if availability is ResearchWorkState.FAILED:
                return self._commit_work_state(
                    job,
                    lease_token,
                    scope,
                    work_item,
                    ResearchWorkState.FAILED,
                    stage="source_integrity_failed",
                )
            if availability is ResearchWorkState.UNAVAILABLE:
                return self._commit_work_state(
                    job,
                    lease_token,
                    scope,
                    work_item,
                    ResearchWorkState.UNAVAILABLE,
                    stage="source_unavailable",
                )
            process_child = self._ensure_processing_child(
                job, lease_token, work_item, candidate
            )
            if process_child.state is JobState.COMPLETED:
                if not self._source_ready(candidate.source_id):
                    return self._commit_work_state(
                        job,
                        lease_token,
                        scope,
                        work_item,
                        ResearchWorkState.FAILED,
                        stage="source_processing_incomplete",
                        child_job_id=process_child.job_id,
                    )
            elif process_child.state in {JobState.FAILED, JobState.CANCELLED}:
                return self._commit_work_state(
                    job,
                    lease_token,
                    scope,
                    work_item,
                    ResearchWorkState.FAILED,
                    stage="source_processing_failed",
                    child_job_id=process_child.job_id,
                )
            else:
                return self._wait_on_child(
                    job,
                    lease_token,
                    scope,
                    work_item,
                    process_child,
                    stage="waiting_source_processing",
                )

        try:
            config = self.service.ensure_model_contract(
                job.job_id,
                parent_job_id=job.job_id,
                lease_token=lease_token,
            )
        except ProviderUnavailableError as exc:
            return self._wait_reason(
                job,
                lease_token,
                scope,
                work_item,
                WaitingReason.NETWORK,
                stage="research_model_unavailable",
                detail=type(exc).__name__,
            )
        except (ModelSelectionError, SourceAnalysisModelDriftError) as exc:
            return self._wait_reason(
                job,
                lease_token,
                scope,
                work_item,
                WaitingReason.USER,
                stage="research_model_drift",
                detail=type(exc).__name__,
            )
        except ModelProviderError as exc:
            return self._wait_reason(
                job,
                lease_token,
                scope,
                work_item,
                WaitingReason.USER,
                stage="research_model_error",
                detail=type(exc).__name__,
            )

        analysis_child = self._ensure_analysis_child(
            job,
            lease_token,
            scope,
            work_item,
            candidate,
            config,
        )
        refreshed = self.repository.get_work_item(work_item.work_item_id)
        return self._reconcile_analysis_child(
            job,
            lease_token,
            scope,
            refreshed,
            child=analysis_child,
        )


    def _advance_synthesis(
        self,
        job: JobRecord,
        lease_token: bytes,
        scope: ResearchScopeRecord,
        *,
        extend_seconds: int,
    ) -> ResearchStepResult:
        refreshed_scope = self.repository.get_scope(scope.scope_id)
        persisted_result = self.repository.get_result_for_scope(scope.scope_id)
        if persisted_result is not None:
            if refreshed_scope.state is not ResearchScopeState.COMPLETED:
                raise ResearchJobError(
                    "ResearchResult exists without a completed ResearchScope."
                )
            return self._complete_persisted_result(
                job,
                lease_token,
                refreshed_scope,
                stage="result_recovered",
            )

        synthesis_work = self.repository.list_synthesis_work_items(scope.scope_id)
        if (
            job.current_stage != "research_awaiting_synthesis"
            and not synthesis_work
        ):
            checkpoint = self._checkpoint(
                job,
                lease_token,
                refreshed_scope,
                current_stage="research_awaiting_synthesis",
                work_item=None,
                child_job_id=None,
                detail={
                    "reason": "all_eligible_source_work_terminal",
                    "final_synthesis": "not_started",
                },
            )
            waiting = self.jobs.wait(
                job.job_id,
                lease_token=lease_token,
                reason=WaitingReason.DEPENDENCY,
                next_run_at_us=utc_now_us(),
            )
            return ResearchStepResult(
                job=waiting,
                scope=self.repository.get_scope(scope.scope_id),
                work_item=None,
                completed_stage="awaiting_synthesis",
                checkpoint=checkpoint,
                child_job_id=None,
                done=False,
                waiting=True,
            )

        coverage = self.repository.coverage(scope.scope_id)
        if coverage.successful_count == 0:
            semantic_content = _deterministic_no_success_content(coverage)
            self.repository.finalize_result_fenced(
                scope.scope_id,
                parent_job_id=job.job_id,
                lease_token=lease_token,
                semantic_content=semantic_content,
                final_artifact_id=None,
                synthesis_pipeline_version=SYNTHESIS_PIPELINE_VERSION,
            )
            completed_scope = self.repository.get_scope(scope.scope_id)
            return self._complete_persisted_result(
                job,
                lease_token,
                completed_scope,
                stage="result_finalized",
            )

        completed_finals = tuple(
            item
            for item in self.repository.list_synthesis_work_items(scope.scope_id)
            if item.stage is ResearchSynthesisStage.FINAL
            and item.state is ResearchSynthesisWorkState.COMPLETED
        )
        if len(completed_finals) > 1:
            raise ResearchJobError(
                "Research synthesis has more than one completed FINAL work item."
            )
        if completed_finals:
            final_work = completed_finals[0]
            final_artifact = self.repository.synthesis_artifact_for_work_item(
                final_work.work_item_id
            )
            if final_artifact is None:
                raise ResearchJobError(
                    "Completed Research FINAL work lost its immutable artifact."
                )
            semantic_content = _semantic_content_from_final_artifact(
                final_artifact.content_json
            )
            self.repository.finalize_result_fenced(
                scope.scope_id,
                parent_job_id=job.job_id,
                lease_token=lease_token,
                semantic_content=semantic_content,
                final_artifact_id=final_artifact.artifact_id,
                synthesis_pipeline_version=SYNTHESIS_PIPELINE_VERSION,
            )
            completed_scope = self.repository.get_scope(scope.scope_id)
            return self._complete_persisted_result(
                job,
                lease_token,
                completed_scope,
                stage="result_finalized",
            )

        try:
            self.service.ensure_model_contract(
                job.job_id,
                parent_job_id=job.job_id,
                lease_token=lease_token,
            )
        except ProviderUnavailableError as exc:
            return self._wait_reason(
                job,
                lease_token,
                refreshed_scope,
                None,
                WaitingReason.NETWORK,
                stage="research_synthesis_model_unavailable",
                detail=type(exc).__name__,
            )
        except (ModelSelectionError, SourceAnalysisModelDriftError) as exc:
            return self._wait_reason(
                job,
                lease_token,
                refreshed_scope,
                None,
                WaitingReason.USER,
                stage="research_synthesis_model_drift",
                detail=type(exc).__name__,
            )
        except ModelProviderError as exc:
            return self._wait_reason(
                job,
                lease_token,
                refreshed_scope,
                None,
                WaitingReason.USER,
                stage="research_synthesis_model_error",
                detail=type(exc).__name__,
            )

        work = self.synthesis.plan_next_synthesis(
            refreshed_scope,
            parent_job_id=job.job_id,
            lease_token=lease_token,
        )
        try:
            prepared = self.synthesis.prepare_call(refreshed_scope, work)
        except ResearchSynthesisInputTooLargeError:
            return self._split_synthesis_boundary(
                job,
                lease_token,
                refreshed_scope,
                work,
                reason="estimated_context_overflow",
            )
        except ResearchSynthesisConfigurationError as exc:
            raise ResearchJobError(str(exc)) from exc

        try:
            artifact = self.synthesis.execute_call_with_coverage_repair(
                scope=refreshed_scope,
                parent_job_id=job.job_id,
                lease_token=lease_token,
                prepared=prepared,
                extend_seconds=extend_seconds,
            )
        except ResearchSynthesisInputTooLargeError:
            return self._split_synthesis_boundary(
                job,
                lease_token,
                refreshed_scope,
                work,
                reason="coverage_repair_context_overflow",
            )
        except ProviderContextLimitError:
            return self._split_synthesis_boundary(
                job,
                lease_token,
                refreshed_scope,
                work,
                reason="provider_context_overflow",
            )
        except ProviderOutputLimitError:
            return self._split_synthesis_boundary(
                job,
                lease_token,
                refreshed_scope,
                work,
                reason="provider_output_overflow",
            )
        except ProviderUnavailableError as exc:
            return self._wait_reason(
                job,
                lease_token,
                refreshed_scope,
                None,
                WaitingReason.NETWORK,
                stage="research_synthesis_provider_unavailable",
                detail=type(exc).__name__,
            )
        except SourceAnalysisModelDriftError as exc:
            return self._wait_reason(
                job,
                lease_token,
                refreshed_scope,
                None,
                WaitingReason.USER,
                stage="research_synthesis_model_drift",
                detail=type(exc).__name__,
            )
        except ResearchSynthesisOutputError as exc:
            return self._wait_reason(
                job,
                lease_token,
                refreshed_scope,
                None,
                WaitingReason.USER,
                stage="research_synthesis_output_invalid",
                detail=type(exc).__name__,
            )
        except ModelProviderError as exc:
            return self._wait_reason(
                job,
                lease_token,
                refreshed_scope,
                None,
                WaitingReason.USER,
                stage="research_synthesis_model_error",
                detail=type(exc).__name__,
            )

        refreshed_scope = self.repository.get_scope(scope.scope_id)
        checkpoint = self._checkpoint(
            job,
            lease_token,
            refreshed_scope,
            current_stage="research_synthesis_artifact_committed",
            work_item=None,
            child_job_id=None,
            detail={
                "synthesis_work_item_id": str(work.work_item_id),
                "artifact_id": str(artifact.artifact_id),
                "synthesis_stage": artifact.artifact_kind.value,
                "level": artifact.level,
                "ordinal": artifact.ordinal,
            },
        )
        return self._result(
            job.job_id,
            refreshed_scope,
            None,
            "synthesis_artifact",
            checkpoint,
            child_job_id=None,
        )

    def _split_synthesis_boundary(
        self,
        job: JobRecord,
        lease_token: bytes,
        scope: ResearchScopeRecord,
        work: ResearchSynthesisWorkItemRecord,
        *,
        reason: str,
    ) -> ResearchStepResult:
        try:
            children = self.synthesis.split_synthesis_work(
                scope,
                work,
                parent_job_id=job.job_id,
                lease_token=lease_token,
            )
        except ResearchSynthesisConfigurationError as exc:
            return self._wait_reason(
                job,
                lease_token,
                scope,
                None,
                WaitingReason.USER,
                stage="research_synthesis_budget_blocked",
                detail=type(exc).__name__,
            )
        checkpoint = self._checkpoint(
            job,
            lease_token,
            self.repository.get_scope(scope.scope_id),
            current_stage="research_synthesis_split",
            work_item=None,
            child_job_id=None,
            detail={
                "reason": reason,
                "synthesis_work_item_id": str(work.work_item_id),
                "child_work_item_ids": [
                    str(child.work_item_id) for child in children
                ],
            },
        )
        return self._result(
            job.job_id,
            self.repository.get_scope(scope.scope_id),
            None,
            "synthesis_split",
            checkpoint,
            child_job_id=None,
        )

    def _complete_persisted_result(
        self,
        job: JobRecord,
        lease_token: bytes,
        scope: ResearchScopeRecord,
        *,
        stage: str,
    ) -> ResearchStepResult:
        result = self.repository.get_result_for_scope(scope.scope_id)
        if result is None:
            raise ResearchJobError(
                "Completed ResearchScope has no durable ResearchResult."
            )
        checkpoint = self._checkpoint(
            job,
            lease_token,
            scope,
            current_stage=f"research_{stage}",
            work_item=None,
            child_job_id=None,
            detail={
                "result_id": str(result.result_id),
                "final_artifact_id": (
                    str(result.final_artifact_id)
                    if result.final_artifact_id is not None
                    else None
                ),
            },
        )
        completed = self.jobs.complete(
            job.job_id,
            lease_token=lease_token,
        )
        return ResearchStepResult(
            job=completed,
            scope=self.repository.get_scope(scope.scope_id),
            work_item=None,
            completed_stage=stage,
            checkpoint=checkpoint,
            child_job_id=None,
            done=True,
            waiting=False,
        )

    def _ensure_processing_child(
        self,
        job: JobRecord,
        lease_token: bytes,
        work_item: ResearchWorkItemRecord,
        candidate: ResearchCandidateRecord,
    ) -> JobRecord:
        child_id = work_item.source_processing_job_id
        if child_id is None:
            child_id = self.repository.find_child_job_for_work_item(
                work_item.work_item_id,
                job_type="source.process",
            )
        if child_id is None:
            try:
                child = self.source_processing.enqueue(
                    candidate.source_id,
                    priority=job.priority,
                    research_work_item_id=work_item.work_item_id,
                )
                child_id = child.job_id
            except sqlite3.IntegrityError:
                child_id = self.repository.find_child_job_for_work_item(
                    work_item.work_item_id,
                    job_type="source.process",
                )
                if child_id is None:
                    raise
        self.repository.link_source_processing_job_fenced(
            work_item.work_item_id,
            parent_job_id=job.job_id,
            lease_token=lease_token,
            child_job_id=child_id,
        )
        return self.jobs.get(child_id)

    def _ensure_analysis_child(
        self,
        job: JobRecord,
        lease_token: bytes,
        scope: ResearchScopeRecord,
        work_item: ResearchWorkItemRecord,
        candidate: ResearchCandidateRecord,
        config: AnalysisPinnedConfiguration,
    ) -> JobRecord:
        child_id = work_item.source_analysis_job_id
        if child_id is None:
            child_id = self.repository.find_child_job_for_work_item(
                work_item.work_item_id,
                job_type="source.analyze",
            )
        if child_id is None:
            try:
                child = self.source_analysis.enqueue_pinned(
                    candidate.source_id,
                    question=scope.query_text,
                    config=config,
                    priority=job.priority,
                    research_work_item_id=work_item.work_item_id,
                )
                child_id = child.job_id
            except sqlite3.IntegrityError:
                child_id = self.repository.find_child_job_for_work_item(
                    work_item.work_item_id,
                    job_type="source.analyze",
                )
                if child_id is None:
                    raise
        self.repository.link_source_analysis_job_fenced(
            work_item.work_item_id,
            parent_job_id=job.job_id,
            lease_token=lease_token,
            child_job_id=child_id,
        )
        return self.jobs.get(child_id)

    def _reconcile_analysis_child(
        self,
        job: JobRecord,
        lease_token: bytes,
        scope: ResearchScopeRecord,
        work_item: ResearchWorkItemRecord,
        *,
        child: JobRecord | None = None,
    ) -> ResearchStepResult:
        child_id = work_item.source_analysis_job_id
        if child is None:
            if child_id is None:
                raise ResearchJobError("Analysis reconciliation has no child job.")
            child = self.jobs.get(child_id)
        if child.state is JobState.COMPLETED:
            state = self._classify_completed_analysis(child.job_id)
            return self._commit_work_state(
                job,
                lease_token,
                scope,
                work_item,
                state,
                stage="source_analysis_classified",
                child_job_id=child.job_id,
            )
        if child.state in {JobState.FAILED, JobState.CANCELLED}:
            return self._commit_work_state(
                job,
                lease_token,
                scope,
                work_item,
                ResearchWorkState.FAILED,
                stage="source_analysis_failed",
                child_job_id=child.job_id,
            )
        return self._wait_on_child(
            job,
            lease_token,
            scope,
            work_item,
            child,
            stage="waiting_source_analysis",
        )

    def _classify_completed_analysis(
        self,
        child_job_id: uuid.UUID,
    ) -> ResearchWorkState:
        analysis = self.source_analysis.repository.get_analysis_for_job(child_job_id)
        if (
            analysis is None
            or analysis.state is not SourceAnalysisState.COMPLETED
            or analysis.coverage != 1.0
            or analysis.final_artifact_id is None
        ):
            return ResearchWorkState.FAILED
        map_artifacts = self.source_analysis.repository.list_artifacts(
            analysis.analysis_id,
            kind=AnalysisStage.MAP,
        )
        if not map_artifacts:
            return ResearchWorkState.FAILED
        relevance: list[bool] = []
        for artifact in map_artifacts:
            try:
                payload = json.loads(artifact.content_json)
            except json.JSONDecodeError:
                return ResearchWorkState.FAILED
            value = payload.get("relevant") if isinstance(payload, dict) else None
            if not isinstance(value, bool):
                return ResearchWorkState.FAILED
            relevance.append(value)
        return (
            ResearchWorkState.SUCCESSFUL
            if any(relevance)
            else ResearchWorkState.IRRELEVANT
        )

    def _source_ready(self, source_id: uuid.UUID) -> bool:
        try:
            self.source_analysis.processed_representation_id(source_id)
        except SourceAnalysisConfigurationError:
            return False
        return True

    def _raw_source_availability(
        self,
        source_id: uuid.UUID,
    ) -> ResearchWorkState | None:
        try:
            self.source_processing.sources.verify(source_id)
        except BlobIntegrityError:
            return ResearchWorkState.FAILED
        except BlobStoreError:
            return ResearchWorkState.UNAVAILABLE
        return None

    def _commit_work_state(
        self,
        job: JobRecord,
        lease_token: bytes,
        scope: ResearchScopeRecord,
        work_item: ResearchWorkItemRecord,
        state: ResearchWorkState,
        *,
        stage: str,
        child_job_id: uuid.UUID | None = None,
    ) -> ResearchStepResult:
        committed = self.repository.mark_work_state_fenced(
            work_item.work_item_id,
            parent_job_id=job.job_id,
            lease_token=lease_token,
            state=state,
        )
        refreshed_scope = self.repository.get_scope(scope.scope_id)
        checkpoint = self._checkpoint(
            job,
            lease_token,
            refreshed_scope,
            current_stage=stage,
            work_item=committed,
            child_job_id=child_job_id,
            detail={"work_state": committed.state.value},
        )
        return self._result(
            job.job_id,
            refreshed_scope,
            committed,
            stage,
            checkpoint,
            child_job_id=child_job_id,
        )

    def _wait_on_child(
        self,
        job: JobRecord,
        lease_token: bytes,
        scope: ResearchScopeRecord,
        work_item: ResearchWorkItemRecord,
        child: JobRecord,
        *,
        stage: str,
    ) -> ResearchStepResult:
        return self._wait_reason(
            job,
            lease_token,
            scope,
            work_item,
            _child_wait_reason(child),
            stage=stage,
            detail=f"{child.job_type}:{child.state.value}:{child.blocked_reason}",
            child_job_id=child.job_id,
        )

    def _wait_reason(
        self,
        job: JobRecord,
        lease_token: bytes,
        scope: ResearchScopeRecord,
        work_item: ResearchWorkItemRecord | None,
        reason: WaitingReason,
        *,
        stage: str,
        detail: str,
        child_job_id: uuid.UUID | None = None,
    ) -> ResearchStepResult:
        checkpoint = self._checkpoint(
            job,
            lease_token,
            scope,
            current_stage=stage,
            work_item=work_item,
            child_job_id=child_job_id,
            detail={"reason": reason.value, "detail": detail[:500]},
        )
        dependency_retry_at = (
            utc_now_us() + 5_000_000
            if reason is WaitingReason.DEPENDENCY
            else None
        )
        waiting = self.jobs.wait(
            job.job_id,
            lease_token=lease_token,
            reason=reason,
            next_run_at_us=dependency_retry_at,
        )
        return ResearchStepResult(
            job=waiting,
            scope=self.repository.get_scope(scope.scope_id),
            work_item=work_item,
            completed_stage=stage,
            checkpoint=checkpoint,
            child_job_id=child_job_id,
            done=False,
            waiting=True,
        )

    def _cancel(
        self,
        job: JobRecord,
        lease_token: bytes,
    ) -> ResearchStepResult:
        scope = self.repository.get_scope_for_job(job.job_id)
        if scope is not None:
            scope = self.repository.mark_scope_state_fenced(
                scope.scope_id,
                parent_job_id=job.job_id,
                lease_token=lease_token,
                state=ResearchScopeState.PARTIAL,
            )
            for work in self.repository.list_work_items(scope.scope_id):
                for child_id in (
                    work.source_processing_job_id,
                    work.source_analysis_job_id,
                ):
                    if child_id is None:
                        continue
                    child = self.jobs.get(child_id)
                    if child.state.terminal:
                        continue
                    try:
                        self.jobs.request_cancel(child_id)
                    except JobTransitionError:
                        current = self.jobs.get(child_id)
                        if not current.state.terminal:
                            raise
        cancelled = self.jobs.acknowledge_cancel(
            job.job_id,
            lease_token=lease_token,
        )
        return ResearchStepResult(
            job=cancelled,
            scope=scope,
            work_item=None,
            completed_stage="cancel",
            checkpoint=None,
            child_job_id=None,
            done=True,
            waiting=False,
        )

    def _checkpoint(
        self,
        job: JobRecord,
        lease_token: bytes,
        scope: ResearchScopeRecord,
        *,
        current_stage: str,
        work_item: ResearchWorkItemRecord | None,
        child_job_id: uuid.UUID | None,
        detail: dict[str, object],
    ) -> CheckpointRecord:
        coverage = self.repository.coverage(scope.scope_id)
        return self.jobs.checkpoint(
            job.job_id,
            lease_token=lease_token,
            current_stage=current_stage,
            progress_state={
                "candidate_total": coverage.candidate_total,
                "eligible_count": coverage.eligible_count,
                "processed_count": coverage.processed_count,
                "successful_count": coverage.successful_count,
                "irrelevant_count": coverage.irrelevant_count,
                "failed_count": coverage.failed_count,
                "unavailable_count": coverage.unavailable_count,
                "excluded_count": coverage.excluded_count,
                "coverage_ratio": coverage.coverage_ratio,
            },
            last_confirmed_input=(
                {
                    "work_item_id": str(work_item.work_item_id),
                    "candidate_id": str(work_item.candidate_id),
                }
                if work_item is not None
                else None
            ),
            last_confirmed_output={
                **detail,
                **(
                    {"child_job_id": str(child_job_id)}
                    if child_job_id is not None
                    else {}
                ),
            },
            resume_metadata={
                "pipeline_version": PIPELINE_VERSION,
                "scope_id": str(scope.scope_id),
                "snapshot_commit_seq": scope.snapshot_commit_seq,
            },
        )

    @staticmethod
    def _validate_job(job: JobRecord) -> None:
        if job.job_type != "research.exhaustive":
            raise ResearchJobError(
                f"Job {job.job_id} is {job.job_type!r}, not 'research.exhaustive'."
            )
        if job.pinned_configuration_json is None or job.requested_scope_json is None:
            raise ResearchJobError(
                "research.exhaustive job is missing its pinned contract."
            )

    def _result(
        self,
        job_id: uuid.UUID,
        scope: ResearchScopeRecord,
        work_item: ResearchWorkItemRecord | None,
        stage: str,
        checkpoint: CheckpointRecord,
        *,
        child_job_id: uuid.UUID | None,
    ) -> ResearchStepResult:
        return ResearchStepResult(
            job=self.jobs.get(job_id),
            scope=scope,
            work_item=work_item,
            completed_stage=stage,
            checkpoint=checkpoint,
            child_job_id=child_job_id,
            done=False,
            waiting=False,
        )



def _deterministic_no_success_content(
    coverage: ResearchCoverage,
) -> dict[str, object]:
    fully_irrelevant = (
        coverage.eligible_count > 0
        and coverage.irrelevant_count == coverage.eligible_count
        and coverage.failed_count == 0
        and coverage.unavailable_count == 0
    )
    if fully_irrelevant:
        return {
            "summary": (
                "All eligible sources were processed successfully but no relevant "
                "evidence was found for the frozen ResearchScope."
            ),
            "findings": [],
            "contradictions": [],
            "uncertainty": "",
        }
    uncertainty = (
        "Semantic synthesis has no successful source evidence. Coverage remains "
        "explicitly bounded by failed or unavailable eligible sources."
        if coverage.failed_count > 0 or coverage.unavailable_count > 0
        else "Semantic synthesis has no successful source evidence."
    )
    return {
        "summary": "No successful source evidence was available for semantic synthesis.",
        "findings": [],
        "contradictions": [],
        "uncertainty": uncertainty,
    }


def _semantic_content_from_final_artifact(raw: str) -> dict[str, object]:
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ResearchJobError(
            "Research FINAL synthesis artifact contains invalid JSON."
        ) from exc
    expected = {"summary", "findings", "contradictions", "uncertainty"}
    if not isinstance(payload, dict) or set(payload) != expected:
        raise ResearchJobError(
            "Research FINAL synthesis artifact has an invalid semantic shape."
        )
    if not isinstance(payload["summary"], str) or not isinstance(
        payload["uncertainty"], str
    ):
        raise ResearchJobError(
            "Research FINAL synthesis artifact text fields are invalid."
        )
    for field in ("findings", "contradictions"):
        values = payload[field]
        if not isinstance(values, list) or any(
            not isinstance(item, str) for item in values
        ):
            raise ResearchJobError(
                f"Research FINAL synthesis artifact field {field!r} is invalid."
            )
    return {
        "summary": payload["summary"],
        "findings": list(payload["findings"]),
        "contradictions": list(payload["contradictions"]),
        "uncertainty": payload["uncertainty"],
    }

def _child_wait_reason(child: JobRecord) -> WaitingReason:
    """A Research parent waits on dependency ownership, never child retry state."""
    del child
    return WaitingReason.DEPENDENCY
