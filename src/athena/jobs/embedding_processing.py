"""Durable, resumable SourceChunk embedding-index worker."""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from typing import cast

from athena.jobs.lease_guard import blocking_operation_lease_seconds
from athena.jobs.models import (
    CheckpointRecord,
    JobPriority,
    JobRecord,
    JobState,
    WaitingReason,
)
from athena.jobs.repository import JobLeaseError, JobTransitionError
from athena.jobs.service import DurableJobService
from athena.model.adapters.lm_studio import (
    ModelProviderError,
    ProviderProtocolError,
    ProviderUnavailableError,
)
from athena.retrieval.archive import (
    ArchiveEmbeddingCursorKey,
    ArchiveEmbeddingGenerationChangedError,
    ArchiveEmbeddingVisibilityChangedError,
    ArchiveSearchError,
    ArchiveSemanticSearchService,
)

_PIPELINE_VERSION = "archive-embedding-rebuild-v1"
_INDEX_KIND = "archive_source_chunks"
_STAGE_BATCH = "batch"
_STAGE_FINALIZE = "finalize"
_STAGE_COMPLETE = "complete"
_ALLOWED_STAGES = frozenset({_STAGE_BATCH, _STAGE_FINALIZE, _STAGE_COMPLETE})


class EmbeddingRebuildJobError(RuntimeError):
    """Raised when an embedding.rebuild job cannot continue safely."""


@dataclass(frozen=True, slots=True)
class EmbeddingRebuildStepResult:
    """One durable embedding rebuild boundary."""

    job: JobRecord
    completed_stage: str | None
    checkpoint: CheckpointRecord | None
    model_id: str
    target_chunk_generation: int
    indexed_document_count: int
    total_document_count: int
    dimensions: int | None
    done: bool
    waiting: bool



@dataclass(frozen=True, slots=True)
class _Cursor:
    model_id: str
    target_chunk_generation: int
    batch_size: int
    next_stage: str
    indexed_document_count: int = 0
    total_document_count: int = 0
    dimensions: int | None = None
    target_visibility_commit_seq: int | None = None
    resume_after: ArchiveEmbeddingCursorKey | None = None


class DurableEmbeddingRebuildWorker:
    """Build SourceChunk embeddings in restart-safe, model-scoped batches."""

    def __init__(
        self,
        *,
        jobs: DurableJobService,
        semantic: ArchiveSemanticSearchService,
    ) -> None:
        self.jobs = jobs
        self.semantic = semantic

    def enqueue(
        self,
        model_id: str,
        *,
        priority: JobPriority = JobPriority.BACKGROUND,
        batch_size: int = 32,
    ) -> JobRecord:
        """Queue a rebuild pinned to the current SourceChunk generation."""
        normalized_model_id = model_id.strip()
        if not normalized_model_id:
            raise ValueError("Embedding model id must not be empty.")
        if not 1 <= batch_size <= 256:
            raise ValueError("Embedding rebuild batch_size must be between 1 and 256.")
        generation = self.semantic.chunk_store.current_generation()
        return self.jobs.create(
            job_type="embedding.rebuild",
            priority=priority,
            requested_scope={"index_kind": _INDEX_KIND},
            pinned_configuration={
                "batch_size": batch_size,
                "index_kind": _INDEX_KIND,
                "model_id": normalized_model_id,
                "pipeline_version": _PIPELINE_VERSION,
                "target_chunk_generation": generation,
            },
        )

    def run_to_boundary(
        self,
        job_id: uuid.UUID,
        *,
        worker_id: str,
        lease_seconds: int = 120,
    ) -> EmbeddingRebuildStepResult:
        """Acquire a queued rebuild and run until completed or waiting."""
        leased = self.jobs.acquire(
            job_id,
            worker_id=worker_id,
            lease_seconds=lease_seconds,
        )
        if leased.lease_token is None:
            raise EmbeddingRebuildJobError("Embedding worker acquired no lease token.")
        lease_token = leased.lease_token
        previous: tuple[str | None, int, int] | None = None
        while True:
            result = self.step(
                job_id,
                lease_token=lease_token,
                extend_seconds=lease_seconds,
            )
            if result.done or result.waiting:
                return result
            marker = (
                result.completed_stage,
                result.indexed_document_count,
                result.total_document_count,
            )
            if marker == previous:
                raise EmbeddingRebuildJobError(
                    "Embedding rebuild made no progress across consecutive durable steps."
                )
            previous = marker

    def step(
        self,
        job_id: uuid.UUID,
        *,
        lease_token: bytes,
        extend_seconds: int = 120,
    ) -> EmbeddingRebuildStepResult:
        """Execute one restart-safe batch/finalization boundary."""
        if extend_seconds <= 0:
            raise ValueError("extend_seconds must be positive.")
        job = self.jobs.get(job_id)
        cursor = self._cursor(job)
        if job.state is JobState.CANCEL_REQUESTED:
            cancelled = self.jobs.acknowledge_cancel(
                job_id,
                lease_token=lease_token,
            )
            return self._result(
                cancelled,
                cursor,
                completed_stage=None,
                checkpoint=None,
                done=True,
                waiting=False,
            )
        if job.state is not JobState.RUNNING:
            raise JobTransitionError(
                f"embedding.rebuild job {job_id} is not running ({job.state.value!r})."
            )

        self.jobs.heartbeat(
            job_id,
            lease_token=lease_token,
            extend_seconds=extend_seconds,
        )
        try:
            self._assert_generation_current(cursor)
            if cursor.next_stage == _STAGE_BATCH:
                return self._batch(
                    job_id,
                    lease_token=lease_token,
                    extend_seconds=extend_seconds,
                    cursor=cursor,
                )
            if cursor.next_stage == _STAGE_FINALIZE:
                return self._finalize(
                    job_id,
                    lease_token=lease_token,
                    extend_seconds=extend_seconds,
                    cursor=cursor,
                )
            if cursor.next_stage == _STAGE_COMPLETE:
                completed = self.jobs.complete(job_id, lease_token=lease_token)
                return self._result(
                    completed,
                    cursor,
                    completed_stage=_STAGE_COMPLETE,
                    checkpoint=None,
                    done=True,
                    waiting=False,
                )
        except ArchiveEmbeddingGenerationChangedError:
            waiting = self.jobs.wait(
                job_id,
                lease_token=lease_token,
                reason=WaitingReason.DEPENDENCY,
            )
            return self._result(
                waiting,
                cursor,
                completed_stage="generation_stale",
                checkpoint=None,
                done=False,
                waiting=True,
            )
        except ArchiveEmbeddingVisibilityChangedError:
            waiting = self.jobs.wait(
                job_id,
                lease_token=lease_token,
                reason=WaitingReason.DEPENDENCY,
            )
            return self._result(
                waiting,
                cursor,
                completed_stage="visibility_stale",
                checkpoint=None,
                done=False,
                waiting=True,
            )
        except ProviderUnavailableError:
            waiting = self.jobs.wait(
                job_id,
                lease_token=lease_token,
                reason=WaitingReason.NETWORK,
            )
            return self._result(
                waiting,
                cursor,
                completed_stage="provider_unavailable",
                checkpoint=None,
                done=False,
                waiting=True,
            )
        except ProviderProtocolError:
            waiting = self.jobs.wait(
                job_id,
                lease_token=lease_token,
                reason=WaitingReason.DEPENDENCY,
            )
            return self._result(
                waiting,
                cursor,
                completed_stage="provider_protocol",
                checkpoint=None,
                done=False,
                waiting=True,
            )
        except ModelProviderError:
            waiting = self.jobs.wait(
                job_id,
                lease_token=lease_token,
                reason=WaitingReason.RESOURCE,
            )
            return self._result(
                waiting,
                cursor,
                completed_stage="provider_resource",
                checkpoint=None,
                done=False,
                waiting=True,
            )
        except (JobLeaseError, JobTransitionError):
            raise
        except ArchiveSearchError as exc:
            try:
                self.jobs.fail(
                    job_id,
                    lease_token=lease_token,
                    blocked_reason=f"embedding_rebuild:{type(exc).__name__}",
                )
            except JobLeaseError:
                pass
            raise EmbeddingRebuildJobError(str(exc)) from exc

        raise EmbeddingRebuildJobError(
            f"Unsupported embedding-rebuild stage {cursor.next_stage!r}."
        )


    def _batch(
        self,
        job_id: uuid.UUID,
        *,
        lease_token: bytes,
        extend_seconds: int,
        cursor: _Cursor,
    ) -> EmbeddingRebuildStepResult:
        plan = self.semantic.prepare_rebuild_batch(
            cursor.model_id,
            target_chunk_generation=cursor.target_chunk_generation,
            target_visibility_commit_seq=cursor.target_visibility_commit_seq,
            resume_after=cursor.resume_after,
            indexed_document_count=cursor.indexed_document_count,
            total_document_count=(
                cursor.total_document_count
                if cursor.target_visibility_commit_seq is not None
                else None
            ),
            expected_dimensions=cursor.dimensions,
            limit=cursor.batch_size,
        )

        if not plan.items:
            if not plan.complete:
                raise EmbeddingRebuildJobError(
                    "Embedding rebuild planner reached no provider work "
                    "without completing the pinned snapshot."
                )
            return self._finalize(
                job_id,
                lease_token=lease_token,
                extend_seconds=extend_seconds,
                cursor=_Cursor(
                    model_id=cursor.model_id,
                    target_chunk_generation=cursor.target_chunk_generation,
                    batch_size=cursor.batch_size,
                    next_stage=_STAGE_FINALIZE,
                    indexed_document_count=plan.indexed_document_count,
                    total_document_count=plan.total_document_count,
                    dimensions=plan.expected_dimensions,
                    target_visibility_commit_seq=(
                        plan.target_visibility_commit_seq
                    ),
                    resume_after=plan.next_cursor,
                ),
            )

        provider_lease_seconds = blocking_operation_lease_seconds(
            timeout_seconds=getattr(
                self.semantic.provider,
                "generation_timeout_seconds",
                None,
            ),
            base_extend_seconds=extend_seconds,
        )
        self.jobs.heartbeat(
            job_id,
            lease_token=lease_token,
            extend_seconds=provider_lease_seconds,
        )

        vectors = self.semantic.provider.embed(
            model_id=cursor.model_id,
            texts=[item.embedding_input for item in plan.items],
        )

        self.jobs.heartbeat(
            job_id,
            lease_token=lease_token,
            extend_seconds=extend_seconds,
        )
        progress = self.semantic.commit_rebuild_batch(
            plan,
            vectors,
        )
        next_stage = (
            _STAGE_FINALIZE
            if progress.complete
            else _STAGE_BATCH
        )
        checkpoint = self.jobs.checkpoint(
            job_id,
            lease_token=lease_token,
            current_stage=(
                "embedding_batches_ready"
                if progress.complete
                else "embedding_batch_committed"
            ),
            progress_state={
                "indexed_documents": progress.indexed_document_count,
                "total_documents": progress.total_document_count,
            },
            last_confirmed_input={
                "batch_documents": len(plan.items),
                "model_id": cursor.model_id,
                "target_chunk_generation": cursor.target_chunk_generation,
                "target_visibility_commit_seq": (
                    progress.target_visibility_commit_seq
                ),
            },
            last_confirmed_output={
                "dimensions": progress.dimensions,
                "indexed_documents": progress.indexed_document_count,
            },
            resume_metadata=self._resume_payload(
                cursor,
                next_stage=next_stage,
                indexed_document_count=progress.indexed_document_count,
                total_document_count=progress.total_document_count,
                dimensions=progress.dimensions,
                target_visibility_commit_seq=(
                    progress.target_visibility_commit_seq
                ),
                resume_after=progress.next_cursor,
            ),
        )
        current = self.jobs.get(job_id)
        return EmbeddingRebuildStepResult(
            job=current,
            completed_stage=_STAGE_BATCH,
            checkpoint=checkpoint,
            model_id=cursor.model_id,
            target_chunk_generation=cursor.target_chunk_generation,
            indexed_document_count=progress.indexed_document_count,
            total_document_count=progress.total_document_count,
            dimensions=progress.dimensions,
            done=False,
            waiting=False,
        )

    def _finalize(
        self,
        job_id: uuid.UUID,
        *,
        lease_token: bytes,
        extend_seconds: int,
        cursor: _Cursor,
    ) -> EmbeddingRebuildStepResult:
        self.jobs.heartbeat(
            job_id,
            lease_token=lease_token,
            extend_seconds=extend_seconds,
        )
        status = self.semantic.finalize_resumable_rebuild(
            cursor.model_id,
            target_chunk_generation=cursor.target_chunk_generation,
            target_visibility_commit_seq=cursor.target_visibility_commit_seq,
            expected_document_count=(
                cursor.total_document_count
                if cursor.target_visibility_commit_seq is not None
                else None
            ),
            expected_dimensions=cursor.dimensions,
        )

        checkpoint = self.jobs.checkpoint(
            job_id,
            lease_token=lease_token,
            current_stage="embedding_index_current",
            progress_state={
                "indexed_documents": status.document_count,
                "total_documents": status.document_count,
            },
            last_confirmed_input={
                "model_id": cursor.model_id,
                "target_chunk_generation": cursor.target_chunk_generation,
                "target_visibility_commit_seq": (
                    status.indexed_visibility_commit_seq
                ),
            },
            last_confirmed_output={
                "current": status.current,
                "dimensions": status.dimensions,
                "document_count": status.document_count,
                "indexed_chunk_generation": (
                    status.indexed_chunk_generation
                ),
                "indexed_visibility_commit_seq": (
                    status.indexed_visibility_commit_seq
                ),
            },
            resume_metadata=self._resume_payload(
                cursor,
                next_stage=_STAGE_COMPLETE,
                indexed_document_count=status.document_count,
                total_document_count=status.document_count,
                dimensions=status.dimensions,
                target_visibility_commit_seq=(
                    status.indexed_visibility_commit_seq
                ),
                resume_after=cursor.resume_after,
            ),
        )
        current = self.jobs.get(job_id)
        return EmbeddingRebuildStepResult(
            job=current,
            completed_stage=_STAGE_FINALIZE,
            checkpoint=checkpoint,
            model_id=cursor.model_id,
            target_chunk_generation=cursor.target_chunk_generation,
            indexed_document_count=status.document_count,
            total_document_count=status.document_count,
            dimensions=status.dimensions,
            done=False,
            waiting=False,
        )

    def _assert_generation_current(self, cursor: _Cursor) -> None:
        if (
            self.semantic.chunk_store.current_generation()
            != cursor.target_chunk_generation
        ):
            raise ArchiveEmbeddingGenerationChangedError(
                "SourceChunks changed relative to the job's pinned generation."
            )
        if (
            cursor.target_visibility_commit_seq is not None
            and self.semantic.lexical.current_visibility_commit_seq()
            != cursor.target_visibility_commit_seq
        ):
            raise ArchiveEmbeddingVisibilityChangedError(
                "Canonical archive visibility changed relative to the "
                "job's pinned snapshot."
            )

    def _cursor(self, job: JobRecord) -> _Cursor:
        self._validate_job_contract(job)
        config = _require_json_object(
            job.pinned_configuration_json,
            "pinned_configuration",
        )
        model_id = _require_string(config, "model_id")
        generation = _require_int(
            config,
            "target_chunk_generation",
            minimum=0,
        )
        batch_size = _require_int(
            config,
            "batch_size",
            minimum=1,
            maximum=256,
        )

        if job.last_checkpoint_id is None:
            return _Cursor(
                model_id=model_id,
                target_chunk_generation=generation,
                batch_size=batch_size,
                next_stage=_STAGE_BATCH,
            )

        checkpoint = self.jobs.get_checkpoint(
            job.last_checkpoint_id
        )
        resume = _require_json_object(
            checkpoint.resume_metadata_json,
            "resume_metadata",
        )
        if (
            _require_string(resume, "pipeline_version")
            != _PIPELINE_VERSION
        ):
            raise EmbeddingRebuildJobError(
                "Checkpoint pipeline version does not match job."
            )
        if _require_string(resume, "model_id") != model_id:
            raise EmbeddingRebuildJobError(
                "Checkpoint model_id does not match job."
            )
        if (
            _require_int(
                resume,
                "target_chunk_generation",
                minimum=0,
            )
            != generation
        ):
            raise EmbeddingRebuildJobError(
                "Checkpoint target chunk generation does not match job."
            )

        next_stage = _require_string(
            resume,
            "next_stage",
        )
        if next_stage not in _ALLOWED_STAGES:
            raise EmbeddingRebuildJobError(
                "Checkpoint contains unsupported "
                f"next_stage {next_stage!r}."
            )

        indexed = _require_int(
            resume,
            "indexed_document_count",
            minimum=0,
        )
        total = _require_int(
            resume,
            "total_document_count",
            minimum=0,
        )

        dimensions_value = resume.get("dimensions")
        dimensions = None
        if dimensions_value is not None:
            if (
                isinstance(dimensions_value, bool)
                or not isinstance(dimensions_value, int)
            ):
                raise EmbeddingRebuildJobError(
                    "Checkpoint dimensions must be an integer."
                )
            if dimensions_value <= 0:
                raise EmbeddingRebuildJobError(
                    "Checkpoint dimensions must be positive."
                )
            dimensions = dimensions_value

        visibility_value = resume.get(
            "target_visibility_commit_seq"
        )
        target_visibility_commit_seq: int | None = None
        if visibility_value is not None:
            if (
                isinstance(visibility_value, bool)
                or not isinstance(visibility_value, int)
                or visibility_value < 0
            ):
                raise EmbeddingRebuildJobError(
                    "Checkpoint target_visibility_commit_seq "
                    "must be a non-negative integer."
                )
            target_visibility_commit_seq = visibility_value

        resume_after_value = resume.get("resume_after")
        resume_after: ArchiveEmbeddingCursorKey | None = None
        if resume_after_value is not None:
            if not isinstance(resume_after_value, dict):
                raise EmbeddingRebuildJobError(
                    "Checkpoint resume_after must be an object."
                )
            expected_cursor_keys = {
                "representation_id",
                "chunking_profile_id",
                "chunk_index",
                "chunk_id",
            }
            if set(resume_after_value) != expected_cursor_keys:
                raise EmbeddingRebuildJobError(
                    "Checkpoint resume_after has unexpected fields."
                )
            try:
                representation_id = uuid.UUID(
                    str(resume_after_value["representation_id"])
                )
                chunking_profile_id = uuid.UUID(
                    str(resume_after_value["chunking_profile_id"])
                )
                chunk_id = uuid.UUID(
                    str(resume_after_value["chunk_id"])
                )
            except (ValueError, TypeError, AttributeError) as exc:
                raise EmbeddingRebuildJobError(
                    "Checkpoint resume_after UUID is invalid."
                ) from exc
            chunk_index_value = resume_after_value["chunk_index"]
            if (
                isinstance(chunk_index_value, bool)
                or not isinstance(chunk_index_value, int)
                or chunk_index_value < 0
            ):
                raise EmbeddingRebuildJobError(
                    "Checkpoint resume_after chunk_index is invalid."
                )
            resume_after = ArchiveEmbeddingCursorKey(
                representation_id=representation_id,
                chunking_profile_id=chunking_profile_id,
                chunk_index=chunk_index_value,
                chunk_id=chunk_id,
            )

        if (
            target_visibility_commit_seq is None
            and resume_after is not None
        ):
            raise EmbeddingRebuildJobError(
                "Legacy embedding checkpoint cannot contain "
                "a keyset cursor without a visibility fence."
            )

        # A pre-A-06 checkpoint may already say COMPLETE although its published
        # index has no visibility watermark. Re-run idempotent finalization once
        # so the upgraded job cannot complete with a permanently stale v3 state.
        if (
            target_visibility_commit_seq is None
            and next_stage == _STAGE_COMPLETE
        ):
            next_stage = _STAGE_FINALIZE

        return _Cursor(
            model_id=model_id,
            target_chunk_generation=generation,
            batch_size=batch_size,
            next_stage=next_stage,
            indexed_document_count=indexed,
            total_document_count=total,
            dimensions=dimensions,
            target_visibility_commit_seq=(
                target_visibility_commit_seq
            ),
            resume_after=resume_after,
        )


    def _validate_job_contract(self, job: JobRecord) -> None:
        if job.job_type != "embedding.rebuild":
            raise EmbeddingRebuildJobError(
                f"Job {job.job_id} is {job.job_type!r}, not 'embedding.rebuild'."
            )
        scope = _require_json_object(job.requested_scope_json, "requested_scope")
        if scope != {"index_kind": _INDEX_KIND}:
            raise EmbeddingRebuildJobError(
                "embedding.rebuild job has an unsupported requested scope."
            )
        config = _require_json_object(job.pinned_configuration_json, "pinned_configuration")
        expected_keys = {
            "batch_size",
            "index_kind",
            "model_id",
            "pipeline_version",
            "target_chunk_generation",
        }
        if set(config) != expected_keys:
            raise EmbeddingRebuildJobError(
                "embedding.rebuild pinned_configuration has unexpected fields."
            )
        if config.get("index_kind") != _INDEX_KIND:
            raise EmbeddingRebuildJobError("embedding.rebuild index_kind is unsupported.")
        if config.get("pipeline_version") != _PIPELINE_VERSION:
            raise EmbeddingRebuildJobError(
                "embedding.rebuild pipeline version is unsupported."
            )

    def _resume_payload(
        self,
        cursor: _Cursor,
        *,
        next_stage: str,
        indexed_document_count: int,
        total_document_count: int,
        dimensions: int | None,
        target_visibility_commit_seq: int,
        resume_after: ArchiveEmbeddingCursorKey | None,
    ) -> dict[str, object]:
        return {
            "batch_size": cursor.batch_size,
            "dimensions": dimensions,
            "indexed_document_count": indexed_document_count,
            "model_id": cursor.model_id,
            "next_stage": next_stage,
            "pipeline_version": _PIPELINE_VERSION,
            "resume_after": (
                None
                if resume_after is None
                else {
                    "representation_id": str(
                        resume_after.representation_id
                    ),
                    "chunking_profile_id": str(
                        resume_after.chunking_profile_id
                    ),
                    "chunk_index": resume_after.chunk_index,
                    "chunk_id": str(resume_after.chunk_id),
                }
            ),
            "target_chunk_generation": (
                cursor.target_chunk_generation
            ),
            "target_visibility_commit_seq": (
                target_visibility_commit_seq
            ),
            "total_document_count": total_document_count,
        }

    @staticmethod
    def _result(
        job: JobRecord,
        cursor: _Cursor,
        *,
        completed_stage: str | None,
        checkpoint: CheckpointRecord | None,
        done: bool,
        waiting: bool,
    ) -> EmbeddingRebuildStepResult:
        return EmbeddingRebuildStepResult(
            job=job,
            completed_stage=completed_stage,
            checkpoint=checkpoint,
            model_id=cursor.model_id,
            target_chunk_generation=cursor.target_chunk_generation,
            indexed_document_count=cursor.indexed_document_count,
            total_document_count=cursor.total_document_count,
            dimensions=cursor.dimensions,
            done=done,
            waiting=waiting,
        )


def _require_json_object(value: str | None, label: str) -> dict[str, object]:
    if value is None:
        raise EmbeddingRebuildJobError(f"embedding.rebuild requires {label}.")
    try:
        decoded = json.loads(value)
    except json.JSONDecodeError as exc:
        raise EmbeddingRebuildJobError(f"embedding.rebuild {label} is invalid JSON.") from exc
    if not isinstance(decoded, dict) or not all(
        isinstance(key, str) for key in decoded
    ):
        raise EmbeddingRebuildJobError(
            f"embedding.rebuild {label} must be a JSON object with string keys."
        )
    return cast(dict[str, object], decoded)


def _require_string(payload: dict[str, object], key: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value.strip():
        raise EmbeddingRebuildJobError(f"embedding.rebuild {key} must be a non-empty string.")
    return value


def _require_int(
    payload: dict[str, object],
    key: str,
    *,
    minimum: int,
    maximum: int | None = None,
) -> int:
    value = payload.get(key)
    if isinstance(value, bool) or not isinstance(value, int):
        raise EmbeddingRebuildJobError(f"embedding.rebuild {key} must be an integer.")
    if value < minimum or (maximum is not None and value > maximum):
        raise EmbeddingRebuildJobError(f"embedding.rebuild {key} is outside its valid range.")
    return value
