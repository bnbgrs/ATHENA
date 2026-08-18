"""Durable worker for hierarchical source Knowledge extraction."""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass

from athena.chat.generation import ModelSelectionError
from athena.jobs.models import CheckpointRecord, JobPriority, JobRecord, JobState, WaitingReason
from athena.jobs.repository import JobLeaseError, JobTransitionError
from athena.jobs.service import DurableJobService
from athena.knowledge.source_extraction import HIERARCHICAL_PIPELINE_VERSION
from athena.knowledge.source_hierarchical_models import (
    SourceExtractionStage,
    SourceHierarchicalExtractionRecord,
    SourceHierarchicalExtractionWorkItem,
)
from athena.knowledge.source_hierarchical_repository import (
    SourceHierarchicalExtractionFenceError,
)
from athena.knowledge.source_hierarchical_service import (
    SourceHierarchicalExtractionInputTooLargeError,
    SourceHierarchicalExtractionModelDriftError,
    SourceHierarchicalExtractionOutputError,
    SourceHierarchicalExtractionService,
)
from athena.model.adapters.lm_studio import (
    ModelProviderError,
    ProviderContextLimitError,
    ProviderUnavailableError,
)


class SourceHierarchicalExtractionJobError(RuntimeError):
    """Raised when a source.extract job cannot be resumed safely."""


@dataclass(frozen=True, slots=True)
class SourceHierarchicalExtractionStepResult:
    """One confirmed durable boundary of hierarchical source extraction."""

    job: JobRecord
    extraction: SourceHierarchicalExtractionRecord | None
    completed_stage: str | None
    checkpoint: CheckpointRecord | None
    artifact_id: uuid.UUID | None
    processing_run_id: uuid.UUID | None
    done: bool
    waiting: bool


class DurableSourceHierarchicalExtractionWorker:
    """Execute source.extract jobs as fenced semantic boundaries."""

    def __init__(
        self,
        *,
        jobs: DurableJobService,
        service: SourceHierarchicalExtractionService,
    ) -> None:
        self.jobs = jobs
        self.service = service

    def enqueue(
        self,
        analysis_id: uuid.UUID,
        *,
        requested_model_id: str | None = None,
        priority: JobPriority = JobPriority.NORMAL,
        context_limit: int | None = None,
        output_reserve: int | None = None,
        safety_margin: int | None = None,
        max_hierarchy_depth: int = 16,
    ) -> JobRecord:
        return self.service.enqueue(
            analysis_id,
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
    ) -> SourceHierarchicalExtractionStepResult:
        leased = self.jobs.acquire(job_id, worker_id=worker_id, lease_seconds=lease_seconds)
        if leased.lease_token is None:
            raise SourceHierarchicalExtractionJobError(
                "Hierarchical extraction worker acquired no lease token."
            )
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
            raise SourceHierarchicalExtractionJobError(
                "Hierarchical extraction exceeded the maximum safe durable boundary count."
            )
        except (JobLeaseError, JobTransitionError):
            raise
        except Exception as exc:
            try:
                self.jobs.fail(
                    job_id,
                    lease_token=lease_token,
                    blocked_reason=f"source_extraction:{type(exc).__name__}",
                )
            except JobLeaseError:
                pass
            if isinstance(exc, SourceHierarchicalExtractionJobError):
                raise
            raise SourceHierarchicalExtractionJobError(
                f"Hierarchical source extraction failed: {type(exc).__name__}: {exc}"
            ) from exc

    def step(
        self,
        job_id: uuid.UUID,
        *,
        lease_token: bytes,
        extend_seconds: int = 120,
    ) -> SourceHierarchicalExtractionStepResult:
        if extend_seconds <= 0:
            raise ValueError("extend_seconds must be positive.")
        job = self.jobs.get(job_id)
        self._validate_job(job)
        if job.state is JobState.CANCEL_REQUESTED:
            return self._cancel(job, lease_token)
        if job.state is not JobState.RUNNING:
            raise JobTransitionError(
                f"source.extract job {job_id} is not running ({job.state.value!r})."
            )
        job = self.jobs.heartbeat(
            job_id,
            lease_token=lease_token,
            extend_seconds=extend_seconds,
        )

        extraction = self.service.repository.get_extraction_for_job(job_id)
        if extraction is None:
            extraction = self.service.initialize_extraction(job)
            checkpoint = self._checkpoint(
                job,
                lease_token,
                extraction,
                current_stage="extraction_initialized",
                last_input={"analysis_id": str(extraction.analysis_id)},
                last_output={"extraction_id": str(extraction.extraction_id)},
            )
            return self._result(
                job_id,
                extraction,
                "initialize",
                checkpoint,
                artifact_id=None,
                processing_run_id=None,
            )

        if extraction.state.value == "completed":
            completed = self.jobs.complete(job_id, lease_token=lease_token)
            final_artifact = (
                self.service.repository.get_artifact(extraction.final_work_artifact_id)
                if extraction.final_work_artifact_id is not None
                else None
            )
            return SourceHierarchicalExtractionStepResult(
                job=completed,
                extraction=extraction,
                completed_stage="complete",
                checkpoint=None,
                artifact_id=extraction.final_work_artifact_id,
                processing_run_id=(
                    final_artifact.processing_run_id if final_artifact is not None else None
                ),
                done=True,
                waiting=False,
            )

        planned = self.service.ensure_planned(extraction)
        if planned is not None:
            refreshed = self.service.repository.get_extraction(extraction.extraction_id)
            checkpoint = self._checkpoint(
                job,
                lease_token,
                refreshed,
                current_stage=f"extraction_{planned}",
                last_input={"extraction_id": str(refreshed.extraction_id)},
                last_output={"planned": planned},
            )
            return self._result(
                job_id,
                refreshed,
                planned,
                checkpoint,
                artifact_id=None,
                processing_run_id=None,
            )

        final_items = self.service.repository.list_work_items(
            extraction.extraction_id, stage=SourceExtractionStage.FINAL
        )
        if len(final_items) > 1:
            raise SourceHierarchicalExtractionJobError(
                "Hierarchical extraction has more than one Final work item."
            )
        if final_items:
            final_artifact = self.service.repository.artifact_for_work_item(
                final_items[0].work_item_id
            )
            if final_artifact is not None:
                return self._finalize(
                    job,
                    lease_token,
                    extraction,
                    final_items[0],
                    resumed=True,
                )

        pending = self.service.repository.next_pending(extraction.extraction_id)
        if pending is None:
            raise SourceHierarchicalExtractionJobError(
                "Hierarchical extraction has no pending work and is not completed."
            )

        if pending.stage is SourceExtractionStage.FINAL:
            return self._finalize(
                job,
                lease_token,
                extraction,
                pending,
                resumed=False,
            )

        try:
            model = self.service.assert_model_unchanged(job, extraction)
        except ProviderUnavailableError as exc:
            return self._wait_network(job, lease_token, extraction, exc)
        except (
            SourceHierarchicalExtractionModelDriftError,
            ModelSelectionError,
            ModelProviderError,
        ) as exc:
            return self._wait_user(job, lease_token, extraction, exc)

        try:
            prepared = self.service.prepare_call(extraction, pending)
        except SourceHierarchicalExtractionInputTooLargeError as exc:
            return self._wait_user(job, lease_token, extraction, exc)

        try:
            artifact = self.service.execute_call(
                job=job,
                lease_token=lease_token,
                extraction=extraction,
                model=model,
                prepared=prepared,
                extend_seconds=extend_seconds,
            )
        except ProviderContextLimitError as exc:
            return self._wait_user(job, lease_token, extraction, exc)
        except ProviderUnavailableError as exc:
            return self._wait_network(job, lease_token, extraction, exc)
        except (
            ModelProviderError,
            SourceHierarchicalExtractionOutputError,
        ) as exc:
            return self._wait_user(job, lease_token, extraction, exc)
        except SourceHierarchicalExtractionFenceError as exc:
            raise JobLeaseError(str(exc)) from exc

        refreshed = self.service.repository.get_extraction(extraction.extraction_id)
        checkpoint = self._checkpoint(
            job,
            lease_token,
            refreshed,
            current_stage=f"extraction_{pending.stage.value}_committed",
            last_input={
                "work_item_id": str(pending.work_item_id),
                "stage": pending.stage.value,
            },
            last_output={
                "artifact_id": str(artifact.artifact_id),
                "processing_run_id": str(artifact.processing_run_id),
            },
        )
        return self._result(
            job_id,
            refreshed,
            pending.stage.value,
            checkpoint,
            artifact_id=artifact.artifact_id,
            processing_run_id=artifact.processing_run_id,
        )

    def _finalize(
        self,
        job: JobRecord,
        lease_token: bytes,
        extraction: SourceHierarchicalExtractionRecord,
        work_item: SourceHierarchicalExtractionWorkItem,
        *,
        resumed: bool,
    ) -> SourceHierarchicalExtractionStepResult:
        result = self.service.finalize(
            job=job,
            lease_token=lease_token,
            extraction=extraction,
            work_item=work_item,
        )
        refreshed = self.service.repository.get_extraction(extraction.extraction_id)
        final_artifact = self.service.repository.artifact_for_work_item(work_item.work_item_id)
        assert final_artifact is not None
        checkpoint = self._checkpoint(
            job,
            lease_token,
            refreshed,
            current_stage=(
                "extraction_final_resumed" if resumed else "extraction_final_committed"
            ),
            last_input={"work_item_id": str(work_item.work_item_id)},
            last_output={
                "artifact_id": str(final_artifact.artifact_id),
                "processing_run_id": str(result.processing_run.processing_run_id),
            },
        )
        return self._result(
            job.job_id,
            refreshed,
            "final",
            checkpoint,
            artifact_id=final_artifact.artifact_id,
            processing_run_id=result.processing_run.processing_run_id,
        )

    def _wait_network(
        self,
        job: JobRecord,
        lease_token: bytes,
        extraction: SourceHierarchicalExtractionRecord,
        exc: Exception,
    ) -> SourceHierarchicalExtractionStepResult:
        checkpoint = self._checkpoint(
            job,
            lease_token,
            extraction,
            current_stage="extraction_waiting_network",
            last_input={"extraction_id": str(extraction.extraction_id)},
            last_output={"error": type(exc).__name__},
        )
        waiting = self.jobs.wait(
            job.job_id,
            lease_token=lease_token,
            reason=WaitingReason.NETWORK,
        )
        return SourceHierarchicalExtractionStepResult(
            job=waiting,
            extraction=extraction,
            completed_stage=None,
            checkpoint=checkpoint,
            artifact_id=None,
            processing_run_id=None,
            done=False,
            waiting=True,
        )

    def _wait_user(
        self,
        job: JobRecord,
        lease_token: bytes,
        extraction: SourceHierarchicalExtractionRecord,
        exc: Exception,
    ) -> SourceHierarchicalExtractionStepResult:
        checkpoint = self._checkpoint(
            job,
            lease_token,
            extraction,
            current_stage="extraction_waiting_user",
            last_input={"extraction_id": str(extraction.extraction_id)},
            last_output={"error": type(exc).__name__},
        )
        waiting = self.jobs.wait(
            job.job_id,
            lease_token=lease_token,
            reason=WaitingReason.USER,
        )
        return SourceHierarchicalExtractionStepResult(
            job=waiting,
            extraction=extraction,
            completed_stage=None,
            checkpoint=checkpoint,
            artifact_id=None,
            processing_run_id=None,
            done=False,
            waiting=True,
        )

    def _cancel(
        self, job: JobRecord, lease_token: bytes
    ) -> SourceHierarchicalExtractionStepResult:
        extraction = self.service.repository.get_extraction_for_job(job.job_id)
        cancelled = self.jobs.acknowledge_cancel(job.job_id, lease_token=lease_token)
        return SourceHierarchicalExtractionStepResult(
            job=cancelled,
            extraction=extraction,
            completed_stage="cancel",
            checkpoint=None,
            artifact_id=None,
            processing_run_id=None,
            done=True,
            waiting=False,
        )

    def _checkpoint(
        self,
        job: JobRecord,
        lease_token: bytes,
        extraction: SourceHierarchicalExtractionRecord,
        *,
        current_stage: str,
        last_input: dict[str, object],
        last_output: dict[str, object],
    ) -> CheckpointRecord:
        return self.jobs.checkpoint(
            job.job_id,
            lease_token=lease_token,
            current_stage=current_stage,
            progress_state={
                "pipeline_version": HIERARCHICAL_PIPELINE_VERSION,
                "extraction_id": str(extraction.extraction_id),
                "state": extraction.state.value,
                "total_batches": extraction.total_batches,
                "completed_batches": extraction.completed_batches,
                "failed_batches": extraction.failed_batches,
            },
            last_confirmed_input=last_input,
            last_confirmed_output=last_output,
            resume_metadata={
                "pipeline_version": HIERARCHICAL_PIPELINE_VERSION,
                "model_signature_id": str(extraction.model_signature_id),
            },
        )

    def _result(
        self,
        job_id: uuid.UUID,
        extraction: SourceHierarchicalExtractionRecord,
        completed_stage: str,
        checkpoint: CheckpointRecord,
        *,
        artifact_id: uuid.UUID | None,
        processing_run_id: uuid.UUID | None,
    ) -> SourceHierarchicalExtractionStepResult:
        return SourceHierarchicalExtractionStepResult(
            job=self.jobs.get(job_id),
            extraction=extraction,
            completed_stage=completed_stage,
            checkpoint=checkpoint,
            artifact_id=artifact_id,
            processing_run_id=processing_run_id,
            done=False,
            waiting=False,
        )

    @staticmethod
    def _validate_job(job: JobRecord) -> None:
        if job.job_type != "source.extract":
            raise SourceHierarchicalExtractionJobError(
                f"Expected source.extract job, got {job.job_type!r}."
            )
        if job.pinned_configuration_json is None:
            raise SourceHierarchicalExtractionJobError(
                "source.extract job has no pinned configuration."
            )
        try:
            config = json.loads(job.pinned_configuration_json)
        except json.JSONDecodeError as exc:
            raise SourceHierarchicalExtractionJobError(
                "source.extract pinned configuration is invalid JSON."
            ) from exc
        if not isinstance(config, dict) or config.get("pipeline_version") != HIERARCHICAL_PIPELINE_VERSION:
            raise SourceHierarchicalExtractionJobError(
                "source.extract job uses another pipeline version."
            )
