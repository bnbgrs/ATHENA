from __future__ import annotations

import json
import uuid
from dataclasses import replace
from types import SimpleNamespace

import pytest

from athena.jobs.models import JobPriority, JobRecord, JobState, WaitingReason
from athena.jobs.source_analysis import DurableSourceAnalysisWorker
from athena.jobs.source_extraction import DurableSourceHierarchicalExtractionWorker
from athena.knowledge.source_extraction import HIERARCHICAL_PIPELINE_VERSION
from athena.knowledge.source_hierarchical_models import SourceExtractionStage
from athena.model.adapters.lm_studio import ModelProviderError, ProviderUnavailableError
from athena.source.analysis_models import AnalysisStage
from athena.source.analysis_service import PIPELINE_VERSION


class _FakeJobs:
    def __init__(self, job: JobRecord) -> None:
        self.job = job
        self.wait_reason: WaitingReason | None = None
        self.checkpoint_stage: str | None = None

    def get(self, job_id: uuid.UUID) -> JobRecord:
        assert job_id == self.job.job_id
        return self.job

    def heartbeat(
        self,
        job_id: uuid.UUID,
        *,
        lease_token: bytes,
        extend_seconds: int,
    ) -> JobRecord:
        assert job_id == self.job.job_id
        assert lease_token == b"lease"
        assert extend_seconds > 0
        return self.job

    def get_checkpoint(self, checkpoint_id: uuid.UUID) -> SimpleNamespace:
        assert checkpoint_id == self.job.last_checkpoint_id
        return SimpleNamespace(
            resume_metadata_json=json.dumps(
                {
                    "pipeline_version": PIPELINE_VERSION,
                    "map_planned": True,
                }
            )
        )

    def checkpoint(
        self,
        job_id: uuid.UUID,
        *,
        current_stage: str,
        **kwargs: object,
    ) -> SimpleNamespace:
        del kwargs
        assert job_id == self.job.job_id
        self.checkpoint_stage = current_stage
        return SimpleNamespace()

    def wait(
        self,
        job_id: uuid.UUID,
        *,
        lease_token: bytes,
        reason: WaitingReason,
        **kwargs: object,
    ) -> JobRecord:
        del kwargs
        assert job_id == self.job.job_id
        assert lease_token == b"lease"
        self.wait_reason = reason
        self.job = replace(
            self.job,
            state=JobState.WAITING,
            blocked_reason=reason.value,
            lease_token=None,
        )
        return self.job


class _AnalysisRepository:
    def __init__(self) -> None:
        self.analysis = SimpleNamespace(
            analysis_id=uuid.uuid4(),
            state=SimpleNamespace(value="running"),
            total_map_units=1,
            completed_map_units=0,
            failed_map_units=0,
            coverage=0.0,
        )
        self.pending = SimpleNamespace(
            work_item_id=uuid.uuid4(),
            stage=AnalysisStage.MAP,
        )

    def get_analysis_for_job(self, job_id: uuid.UUID) -> SimpleNamespace:
        del job_id
        return self.analysis

    def get_analysis(self, analysis_id: uuid.UUID) -> SimpleNamespace:
        assert analysis_id == self.analysis.analysis_id
        return self.analysis

    def next_pending(self, analysis_id: uuid.UUID) -> SimpleNamespace:
        assert analysis_id == self.analysis.analysis_id
        return self.pending


class _AnalysisService:
    def __init__(self, *, error_stage: str, error: ModelProviderError) -> None:
        self.repository = _AnalysisRepository()
        self.error_stage = error_stage
        self.error = error

    def assert_model_unchanged(self, job: JobRecord, analysis: object) -> object:
        del job, analysis
        if self.error_stage == "model":
            raise self.error
        return object()

    def prepare_call(self, analysis: object, pending: object) -> object:
        del analysis, pending
        return object()

    def execute_call(self, **kwargs: object) -> object:
        del kwargs
        if self.error_stage == "execute":
            raise self.error
        raise AssertionError("execute_call should not succeed in this regression test")


class _ExtractionRepository:
    def __init__(self) -> None:
        self.extraction = SimpleNamespace(
            extraction_id=uuid.uuid4(),
            analysis_id=uuid.uuid4(),
            state=SimpleNamespace(value="running"),
            total_batches=1,
            completed_batches=0,
            failed_batches=0,
            model_signature_id=uuid.uuid4(),
            final_work_artifact_id=None,
        )
        self.pending = SimpleNamespace(
            work_item_id=uuid.uuid4(),
            stage=SourceExtractionStage.BATCH,
        )

    def get_extraction_for_job(self, job_id: uuid.UUID) -> SimpleNamespace:
        del job_id
        return self.extraction

    def get_extraction(self, extraction_id: uuid.UUID) -> SimpleNamespace:
        assert extraction_id == self.extraction.extraction_id
        return self.extraction

    def list_work_items(self, extraction_id: uuid.UUID, *, stage: object) -> tuple[()]:
        assert extraction_id == self.extraction.extraction_id
        assert stage is SourceExtractionStage.FINAL
        return ()

    def next_pending(self, extraction_id: uuid.UUID) -> SimpleNamespace:
        assert extraction_id == self.extraction.extraction_id
        return self.pending


class _ExtractionService:
    def __init__(self, *, error_stage: str, error: ModelProviderError) -> None:
        self.repository = _ExtractionRepository()
        self.error_stage = error_stage
        self.error = error

    def ensure_planned(self, extraction: object) -> None:
        del extraction
        return None

    def assert_model_unchanged(self, job: JobRecord, extraction: object) -> object:
        del job, extraction
        if self.error_stage == "model":
            raise self.error
        return object()

    def prepare_call(self, extraction: object, pending: object) -> object:
        del extraction, pending
        return object()

    def execute_call(self, **kwargs: object) -> object:
        del kwargs
        if self.error_stage == "execute":
            raise self.error
        raise AssertionError("execute_call should not succeed in this regression test")


def _job(job_type: str) -> JobRecord:
    pinned = (
        {"pipeline_version": HIERARCHICAL_PIPELINE_VERSION}
        if job_type == "source.extract"
        else {"pipeline_version": PIPELINE_VERSION}
    )
    return JobRecord(
        job_id=uuid.uuid4(),
        job_type=job_type,
        created_at_us=1,
        created_by_actor_id=uuid.uuid4(),
        priority=JobPriority.NORMAL,
        state=JobState.RUNNING,
        requested_scope_json="{}",
        processing_run_id=None,
        current_stage=None,
        last_checkpoint_id=uuid.uuid4(),
        retry_count=0,
        next_run_at_us=None,
        blocked_reason=None,
        pinned_configuration_json=json.dumps(pinned),
        protection_scope_id=None,
        protected_payload_id=None,
        worker_id="test-worker",
        lease_token=b"lease",
        lease_acquired_at_us=1,
        lease_expires_at_us=10_000_000,
        heartbeat_at_us=1,
        fencing_sequence=1,
        updated_at_us=1,
    )


@pytest.mark.parametrize("error_stage", ["model", "execute"])
def test_source_analysis_provider_unavailable_waits_for_network(error_stage: str) -> None:
    job = _job("source.analyze")
    jobs = _FakeJobs(job)
    service = _AnalysisService(
        error_stage=error_stage,
        error=ProviderUnavailableError("provider offline"),
    )
    worker = DurableSourceAnalysisWorker(jobs=jobs, service=service)  # type: ignore[arg-type]

    result = worker.step(job.job_id, lease_token=b"lease")

    assert result.waiting is True
    assert result.job.state is JobState.WAITING
    assert result.job.blocked_reason == WaitingReason.NETWORK.value
    assert jobs.wait_reason is WaitingReason.NETWORK
    assert jobs.checkpoint_stage == "analysis_waiting_network"


def test_source_analysis_non_transient_provider_error_still_waits_for_user() -> None:
    job = _job("source.analyze")
    jobs = _FakeJobs(job)
    service = _AnalysisService(
        error_stage="execute",
        error=ModelProviderError("invalid provider response"),
    )
    worker = DurableSourceAnalysisWorker(jobs=jobs, service=service)  # type: ignore[arg-type]

    result = worker.step(job.job_id, lease_token=b"lease")

    assert result.waiting is True
    assert result.job.blocked_reason == WaitingReason.USER.value
    assert jobs.wait_reason is WaitingReason.USER
    assert jobs.checkpoint_stage == "analysis_waiting_user"


@pytest.mark.parametrize("error_stage", ["model", "execute"])
def test_source_extraction_provider_unavailable_waits_for_network(error_stage: str) -> None:
    job = _job("source.extract")
    jobs = _FakeJobs(job)
    service = _ExtractionService(
        error_stage=error_stage,
        error=ProviderUnavailableError("provider offline"),
    )
    worker = DurableSourceHierarchicalExtractionWorker(  # type: ignore[arg-type]
        jobs=jobs,
        service=service,
    )

    result = worker.step(job.job_id, lease_token=b"lease")

    assert result.waiting is True
    assert result.job.state is JobState.WAITING
    assert result.job.blocked_reason == WaitingReason.NETWORK.value
    assert jobs.wait_reason is WaitingReason.NETWORK
    assert jobs.checkpoint_stage == "extraction_waiting_network"


def test_source_extraction_non_transient_provider_error_still_waits_for_user() -> None:
    job = _job("source.extract")
    jobs = _FakeJobs(job)
    service = _ExtractionService(
        error_stage="model",
        error=ModelProviderError("invalid provider response"),
    )
    worker = DurableSourceHierarchicalExtractionWorker(  # type: ignore[arg-type]
        jobs=jobs,
        service=service,
    )

    result = worker.step(job.job_id, lease_token=b"lease")

    assert result.waiting is True
    assert result.job.blocked_reason == WaitingReason.USER.value
    assert jobs.wait_reason is WaitingReason.USER
    assert jobs.checkpoint_stage == "extraction_waiting_user"
