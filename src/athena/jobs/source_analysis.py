"""Durable worker for hierarchical large-source Primary Model analysis."""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass

from athena.chat.generation import ModelSelectionError
from athena.jobs.models import CheckpointRecord, JobPriority, JobRecord, JobState, WaitingReason
from athena.jobs.repository import JobLeaseError, JobTransitionError
from athena.jobs.service import DurableJobService
from athena.model.adapters.lm_studio import (
    ModelProviderError,
    ProviderContextLimitError,
    ProviderOutputLimitError,
    ProviderUnavailableError,
)
from athena.source.analysis_models import (
    AnalysisStage,
    SourceAnalysisRecord,
    SourceAnalysisWorkItem,
)
from athena.source.analysis_repository import SourceAnalysisFenceError
from athena.source.analysis_service import (
    PIPELINE_VERSION,
    SourceAnalysisConfigurationError,
    SourceAnalysisInputTooLargeError,
    SourceAnalysisModelDriftError,
    SourceAnalysisOutputError,
    SourceAnalysisService,
)


class SourceAnalysisJobError(RuntimeError):
    """Raised when a source.analyze job cannot be resumed safely."""


@dataclass(frozen=True, slots=True)
class SourceAnalysisStepResult:
    """One confirmed durable boundary of source analysis work."""

    job: JobRecord
    analysis: SourceAnalysisRecord | None
    completed_stage: str | None
    checkpoint: CheckpointRecord | None
    artifact_id: uuid.UUID | None
    done: bool
    waiting: bool


class DurableSourceAnalysisWorker:
    """Execute source.analyze jobs as small fenced semantic commits."""

    def __init__(
        self, *, jobs: DurableJobService, service: SourceAnalysisService
    ) -> None:
        self.jobs = jobs
        self.service = service

    def enqueue(
        self,
        source_id: uuid.UUID,
        *,
        question: str,
        requested_model_id: str | None = None,
        priority: JobPriority = JobPriority.NORMAL,
        context_limit: int | None = None,
        output_reserve: int | None = None,
        safety_margin: int | None = None,
        max_hierarchy_depth: int = 12,
    ) -> JobRecord:
        return self.service.enqueue(
            source_id,
            question=question,
            requested_model_id=requested_model_id,
            priority=priority,
            context_limit=context_limit,
            output_reserve=output_reserve,
            safety_margin=safety_margin,
            max_hierarchy_depth=max_hierarchy_depth,
        )

    def run_to_completion(
        self,
        job_id: uuid.UUID,
        *,
        worker_id: str,
        lease_seconds: int = 120,
    ) -> SourceAnalysisStepResult:
        leased = self.jobs.acquire(job_id, worker_id=worker_id, lease_seconds=lease_seconds)
        if leased.lease_token is None:
            raise SourceAnalysisJobError("Source analysis worker acquired no lease token.")
        lease_token = leased.lease_token
        try:
            for _ in range(100_000):
                result = self.step(
                    job_id,
                    lease_token=lease_token,
                    extend_seconds=lease_seconds,
                )
                if result.done or result.waiting:
                    return result
            raise SourceAnalysisJobError(
                "Source analysis exceeded the maximum safe durable boundary count."
            )
        except (JobLeaseError, JobTransitionError):
            raise
        except Exception as exc:
            try:
                self.jobs.fail(
                    job_id,
                    lease_token=lease_token,
                    blocked_reason=f"source_analysis:{type(exc).__name__}",
                )
            except JobLeaseError:
                pass
            if isinstance(exc, SourceAnalysisJobError):
                raise
            raise SourceAnalysisJobError(
                f"Source analysis failed: {type(exc).__name__}: {exc}"
            ) from exc

    def step(
        self,
        job_id: uuid.UUID,
        *,
        lease_token: bytes,
        extend_seconds: int = 120,
    ) -> SourceAnalysisStepResult:
        if extend_seconds <= 0:
            raise ValueError("extend_seconds must be positive.")
        job = self.jobs.get(job_id)
        self._validate_job(job)
        if job.state is JobState.CANCEL_REQUESTED:
            return self._cancel(job, lease_token)
        if job.state is not JobState.RUNNING:
            raise JobTransitionError(
                f"source.analyze job {job_id} is not running ({job.state.value!r})."
            )
        job = self.jobs.heartbeat(
            job_id,
            lease_token=lease_token,
            extend_seconds=extend_seconds,
        )

        analysis = self.service.repository.get_analysis_for_job(job_id)
        if analysis is None:
            analysis = self.service.initialize_analysis(job)
            checkpoint = self._checkpoint(
                job,
                lease_token,
                analysis,
                current_stage="analysis_initialized",
                map_planned=False,
                last_input={"source_id": str(analysis.source_id)},
                last_output={"analysis_id": str(analysis.analysis_id)},
            )
            return self._result(
                job_id,
                analysis,
                "initialize",
                checkpoint,
                artifact_id=None,
            )

        if not self._map_planned(job):
            map_plan = self.service.plan_map(analysis)
            analysis = self.service.repository.get_analysis(analysis.analysis_id)
            checkpoint = self._checkpoint(
                job,
                lease_token,
                analysis,
                current_stage="analysis_map_planned",
                map_planned=True,
                last_input={"representation_id": str(analysis.representation_id)},
                last_output={"map_work_items": len(map_plan)},
            )
            return self._result(
                job_id,
                analysis,
                "map_plan",
                checkpoint,
                artifact_id=None,
            )

        analysis = self.service.repository.get_analysis(analysis.analysis_id)
        if analysis.state.value == "completed":
            completed = self.jobs.complete(job_id, lease_token=lease_token)
            return SourceAnalysisStepResult(
                job=completed,
                analysis=analysis,
                completed_stage="complete",
                checkpoint=None,
                artifact_id=analysis.final_artifact_id,
                done=True,
                waiting=False,
            )

        pending = self.service.repository.next_pending(analysis.analysis_id)
        if pending is None:
            synthesis_plan = self.service.plan_next_synthesis(analysis)
            checkpoint = self._checkpoint(
                job,
                lease_token,
                analysis,
                current_stage="analysis_synthesis_planned",
                map_planned=True,
                last_input={"leaf_artifacts": len(self.service.repository.leaf_artifacts(analysis.analysis_id))},
                last_output={
                    "work_item_id": str(synthesis_plan.work_item_id),
                    "stage": synthesis_plan.stage.value,
                    "level": synthesis_plan.level,
                },
            )
            return self._result(
                job_id,
                analysis,
                "synthesis_plan",
                checkpoint,
                artifact_id=None,
            )

        try:
            model = self.service.assert_model_unchanged(job, analysis)
        except ProviderUnavailableError as exc:
            return self._wait_network(job, lease_token, analysis, exc)
        except (
            SourceAnalysisModelDriftError,
            ModelSelectionError,
        ) as exc:
            return self._wait_user(job, lease_token, analysis, exc)
        except ModelProviderError as exc:
            return self._wait_user(job, lease_token, analysis, exc)

        try:
            prepared = self.service.prepare_call(analysis, pending)
        except SourceAnalysisInputTooLargeError:
            return self._split_pending(job, lease_token, analysis, pending)

        try:
            artifact = self.service.execute_call(
                job=job,
                lease_token=lease_token,
                analysis=analysis,
                model=model,
                prepared=prepared,
                extend_seconds=extend_seconds,
            )
        except ProviderContextLimitError:
            return self._split_pending(job, lease_token, analysis, pending)
        except ProviderOutputLimitError:
            return self._split_pending(job, lease_token, analysis, pending)
        except ProviderUnavailableError as exc:
            return self._wait_network(job, lease_token, analysis, exc)
        except (ModelProviderError, SourceAnalysisOutputError) as exc:
            return self._wait_user(job, lease_token, analysis, exc)
        except SourceAnalysisFenceError as exc:
            raise JobLeaseError(str(exc)) from exc

        refreshed = self.service.repository.get_analysis(analysis.analysis_id)
        checkpoint = self._checkpoint(
            job,
            lease_token,
            refreshed,
            current_stage=f"analysis_{pending.stage.value}_committed",
            map_planned=True,
            last_input={"work_item_id": str(pending.work_item_id)},
            last_output={"artifact_id": str(artifact.artifact_id)},
        )
        if refreshed.state.value == "completed":
            completed = self.jobs.complete(job_id, lease_token=lease_token)
            return SourceAnalysisStepResult(
                job=completed,
                analysis=refreshed,
                completed_stage=pending.stage.value,
                checkpoint=checkpoint,
                artifact_id=artifact.artifact_id,
                done=True,
                waiting=False,
            )
        return self._result(
            job_id,
            refreshed,
            pending.stage.value,
            checkpoint,
            artifact_id=artifact.artifact_id,
        )

    def _split_pending(
        self,
        job: JobRecord,
        lease_token: bytes,
        analysis: SourceAnalysisRecord,
        pending: SourceAnalysisWorkItem,
    ) -> SourceAnalysisStepResult:
        try:
            if pending.stage is AnalysisStage.MAP:
                children = self.service.split_map_work(
                    job=job,
                    lease_token=lease_token,
                    analysis=analysis,
                    work_item=pending,
                )
            else:
                children = self.service.split_synthesis_work(
                    job=job,
                    lease_token=lease_token,
                    analysis=analysis,
                    work_item=pending,
                )
        except SourceAnalysisFenceError as exc:
            raise JobLeaseError(str(exc)) from exc
        except SourceAnalysisConfigurationError as exc:
            return self._wait_user(job, lease_token, analysis, exc)
        refreshed = self.service.repository.get_analysis(analysis.analysis_id)
        checkpoint = self._checkpoint(
            job,
            lease_token,
            refreshed,
            current_stage="analysis_work_split",
            map_planned=True,
            last_input={"work_item_id": str(pending.work_item_id)},
            last_output={"child_work_items": [str(item.work_item_id) for item in children]},
        )
        return self._result(
            job.job_id,
            refreshed,
            "split",
            checkpoint,
            artifact_id=None,
        )

    def _wait_network(
        self,
        job: JobRecord,
        lease_token: bytes,
        analysis: SourceAnalysisRecord,
        exc: Exception,
    ) -> SourceAnalysisStepResult:
        checkpoint = self._checkpoint(
            job,
            lease_token,
            analysis,
            current_stage="analysis_waiting_network",
            map_planned=True,
            last_input=None,
            last_output={"reason": type(exc).__name__, "detail": type(exc).__name__},
        )
        waiting = self.jobs.wait(
            job.job_id,
            lease_token=lease_token,
            reason=WaitingReason.NETWORK,
        )
        return SourceAnalysisStepResult(
            job=waiting,
            analysis=self.service.repository.get_analysis(analysis.analysis_id),
            completed_stage="waiting_network",
            checkpoint=checkpoint,
            artifact_id=None,
            done=False,
            waiting=True,
        )

    def _wait_user(
        self,
        job: JobRecord,
        lease_token: bytes,
        analysis: SourceAnalysisRecord,
        exc: Exception,
    ) -> SourceAnalysisStepResult:
        checkpoint = self._checkpoint(
            job,
            lease_token,
            analysis,
            current_stage="analysis_waiting_user",
            map_planned=True,
            last_input=None,
            last_output={"reason": type(exc).__name__, "detail": type(exc).__name__},
        )
        waiting = self.jobs.wait(
            job.job_id,
            lease_token=lease_token,
            reason=WaitingReason.USER,
        )
        return SourceAnalysisStepResult(
            job=waiting,
            analysis=self.service.repository.get_analysis(analysis.analysis_id),
            completed_stage="waiting_user",
            checkpoint=checkpoint,
            artifact_id=None,
            done=False,
            waiting=True,
        )

    def _cancel(self, job: JobRecord, lease_token: bytes) -> SourceAnalysisStepResult:
        analysis = self.service.repository.get_analysis_for_job(job.job_id)
        if analysis is not None:
            try:
                analysis = self.service.repository.mark_partial(
                    analysis.analysis_id,
                    job_id=job.job_id,
                    lease_token=lease_token,
                )
            except SourceAnalysisFenceError as exc:
                raise JobLeaseError(str(exc)) from exc
        cancelled = self.jobs.acknowledge_cancel(job.job_id, lease_token=lease_token)
        return SourceAnalysisStepResult(
            job=cancelled,
            analysis=analysis,
            completed_stage="cancel",
            checkpoint=None,
            artifact_id=None,
            done=True,
            waiting=False,
        )

    def _checkpoint(
        self,
        job: JobRecord,
        lease_token: bytes,
        analysis: SourceAnalysisRecord,
        *,
        current_stage: str,
        map_planned: bool,
        last_input: dict[str, object] | None,
        last_output: dict[str, object] | None,
    ) -> CheckpointRecord:
        return self.jobs.checkpoint(
            job.job_id,
            lease_token=lease_token,
            current_stage=current_stage,
            progress_state={
                "total_map_units": analysis.total_map_units,
                "completed_map_units": analysis.completed_map_units,
                "failed_map_units": analysis.failed_map_units,
                "coverage": analysis.coverage,
            },
            last_confirmed_input=last_input,
            last_confirmed_output=last_output,
            resume_metadata={
                "pipeline_version": PIPELINE_VERSION,
                "analysis_id": str(analysis.analysis_id),
                "map_planned": map_planned,
            },
        )

    def _map_planned(self, job: JobRecord) -> bool:
        if job.last_checkpoint_id is None:
            return False
        checkpoint = self.jobs.get_checkpoint(job.last_checkpoint_id)
        if checkpoint.resume_metadata_json is None:
            return False
        try:
            value = json.loads(checkpoint.resume_metadata_json)
        except json.JSONDecodeError as exc:
            raise SourceAnalysisJobError("Analysis checkpoint resume metadata is invalid JSON.") from exc
        if not isinstance(value, dict):
            raise SourceAnalysisJobError("Analysis checkpoint resume metadata must be an object.")
        if value.get("pipeline_version") != PIPELINE_VERSION:
            raise SourceAnalysisJobError("Analysis checkpoint pipeline version drifted.")
        return value.get("map_planned") is True

    @staticmethod
    def _validate_job(job: JobRecord) -> None:
        if job.job_type != "source.analyze":
            raise SourceAnalysisJobError(
                f"Job {job.job_id} is {job.job_type!r}, not 'source.analyze'."
            )
        if job.pinned_configuration_json is None or job.requested_scope_json is None:
            raise SourceAnalysisJobError("source.analyze job is missing its pinned contract.")

    def _result(
        self,
        job_id: uuid.UUID,
        analysis: SourceAnalysisRecord,
        stage: str,
        checkpoint: CheckpointRecord,
        *,
        artifact_id: uuid.UUID | None,
    ) -> SourceAnalysisStepResult:
        return SourceAnalysisStepResult(
            job=self.jobs.get(job_id),
            analysis=analysis,
            completed_stage=stage,
            checkpoint=checkpoint,
            artifact_id=artifact_id,
            done=False,
            waiting=False,
        )
