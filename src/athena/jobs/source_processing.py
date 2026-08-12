"""Durable, resumable source-processing worker."""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from typing import Any

from athena.jobs.models import CheckpointRecord, JobPriority, JobRecord, JobState
from athena.jobs.repository import JobLeaseError, JobTransitionError
from athena.jobs.service import DurableJobService
from athena.source.chunking_service import SourceChunkBuildResult, SourceChunkingService
from athena.source.docx_representation_service import SourceDocxRepresentationService
from athena.source.html_representation_service import SourceHtmlRepresentationService
from athena.source.models import (
    RepresentationRetentionState,
    SourceRepresentationRecord,
    SourceRepresentationType,
)
from athena.source.pdf_representation_service import SourcePdfRepresentationService
from athena.source.representation_service import SourceTextRepresentationService
from athena.source.service import SourceCaptureService

_PIPELINE_VERSION = "source-process-v1"
_TEXT_PARSER_ID = "athena.native_text"
_TEXT_PARSER_VERSION = "1"
_TEXT_OPTIONS: dict[str, object] = {
    "encoding": "utf-8-strict",
    "line_endings": "lf",
    "unicode_normalization": "none",
    "utf8_bom": "strip",
}
_STAGE_VERIFY = "verify"
_STAGE_REPRESENT = "represent"
_STAGE_CHUNK = "chunk"
_STAGE_FINALIZE = "finalize"
_ALLOWED_STAGES = frozenset(
    {_STAGE_VERIFY, _STAGE_REPRESENT, _STAGE_CHUNK, _STAGE_FINALIZE}
)
_TOTAL_WORK_STAGES = 3


class SourceProcessingJobError(RuntimeError):
    """Raised when a source.process job cannot be resumed safely."""


@dataclass(frozen=True, slots=True)
class SourceProcessingStepResult:
    """One durable stage boundary produced by the source-processing worker."""

    job: JobRecord
    completed_stage: str | None
    checkpoint: CheckpointRecord | None
    representation_id: uuid.UUID | None
    chunk_count: int | None
    done: bool


@dataclass(frozen=True, slots=True)
class _Cursor:
    source_id: uuid.UUID
    next_stage: str
    representation_id: uuid.UUID | None = None
    build_signature: bytes | None = None
    chunk_count: int | None = None


class DurableSourceProcessingWorker:
    """Run ``source.process`` jobs through restart-safe deterministic stages."""

    def __init__(
        self,
        *,
        jobs: DurableJobService,
        sources: SourceCaptureService,
        source_text: SourceTextRepresentationService,
        source_pdf: SourcePdfRepresentationService,
        source_docx: SourceDocxRepresentationService,
        source_html: SourceHtmlRepresentationService,
        source_chunks: SourceChunkingService,
    ) -> None:
        self.jobs = jobs
        self.sources = sources
        self.source_text = source_text
        self.source_pdf = source_pdf
        self.source_docx = source_docx
        self.source_html = source_html
        self.source_chunks = source_chunks

    def enqueue(
        self,
        source_id: uuid.UUID,
        *,
        priority: JobPriority = JobPriority.NORMAL,
    ) -> JobRecord:
        """Queue one reproducibly configured source-processing job."""
        self.sources.get(source_id)
        return self.jobs.create(
            job_type="source.process",
            priority=priority,
            requested_scope={"source_id": str(source_id)},
            pinned_configuration={
                "pipeline_version": _PIPELINE_VERSION,
                "text_parser": f"{_TEXT_PARSER_ID}@{_TEXT_PARSER_VERSION}",
                "pdf_parser": self.source_pdf.parser_signature,
                "docx_parser": self.source_docx.parser_signature,
                "html_parser": self.source_html.parser_signature,
                "chunking_profile": "default",
                "embedding_policy": "deferred",
            },
        )

    def run_to_completion(
        self,
        job_id: uuid.UUID,
        *,
        worker_id: str,
        lease_seconds: int = 120,
    ) -> SourceProcessingStepResult:
        """Acquire a queued job and run safe stages until it becomes terminal."""
        leased = self.jobs.acquire(
            job_id,
            worker_id=worker_id,
            lease_seconds=lease_seconds,
        )
        if leased.lease_token is None:
            raise SourceProcessingJobError("Source worker acquired no lease token.")
        lease_token = leased.lease_token
        last_result: SourceProcessingStepResult | None = None
        try:
            # The current v1 pipeline needs at most verify, represent, chunk,
            # one optional derived repair, and finalize. The guard prevents a
            # corrupt cursor from becoming an unbounded worker loop.
            for _ in range(8):
                last_result = self.step(
                    job_id,
                    lease_token=lease_token,
                    extend_seconds=lease_seconds,
                )
                if last_result.done:
                    return last_result
            raise SourceProcessingJobError(
                "Source processing exceeded the maximum safe stage count."
            )
        except (JobLeaseError, JobTransitionError):
            raise
        except Exception as exc:
            try:
                self.jobs.fail(
                    job_id,
                    lease_token=lease_token,
                    blocked_reason=_failure_reason(exc),
                )
            except JobLeaseError:
                # A lost/expired fence must be recovered by normal startup
                # recovery; the stale worker must not mutate the job further.
                pass
            if isinstance(exc, SourceProcessingJobError):
                raise
            raise SourceProcessingJobError(
                f"Source processing failed: {type(exc).__name__}: {exc}"
            ) from exc

    def step(
        self,
        job_id: uuid.UUID,
        *,
        lease_token: bytes,
        extend_seconds: int = 120,
    ) -> SourceProcessingStepResult:
        """Execute exactly one restart-safe source-processing stage."""
        if extend_seconds <= 0:
            raise ValueError("extend_seconds must be positive.")
        job = self.jobs.get(job_id)
        self._validate_job_contract(job)
        if job.state is JobState.CANCEL_REQUESTED:
            cancelled = self.jobs.acknowledge_cancel(
                job_id,
                lease_token=lease_token,
            )
            return SourceProcessingStepResult(
                job=cancelled,
                completed_stage=None,
                checkpoint=None,
                representation_id=None,
                chunk_count=None,
                done=True,
            )
        if job.state is not JobState.RUNNING:
            raise JobTransitionError(
                f"source.process job {job_id} is not running ({job.state.value!r})."
            )

        # Validate ownership and extend the fence before starting potentially
        # expensive I/O. Every checkpoint validates the same lease again.
        job = self.jobs.heartbeat(
            job_id,
            lease_token=lease_token,
            extend_seconds=extend_seconds,
        )
        cursor = self._cursor(job)

        try:
            if cursor.next_stage == _STAGE_VERIFY:
                return self._verify(job_id, lease_token, cursor)
            if cursor.next_stage == _STAGE_REPRESENT:
                return self._represent(job_id, lease_token, cursor)
            if cursor.next_stage == _STAGE_CHUNK:
                return self._chunk(job_id, lease_token, cursor)
            if cursor.next_stage == _STAGE_FINALIZE:
                return self._finalize(job_id, lease_token, cursor)
        except (JobLeaseError, JobTransitionError, SourceProcessingJobError):
            raise
        except Exception as exc:
            raise SourceProcessingJobError(
                f"Stage {cursor.next_stage!r} failed: {type(exc).__name__}: {exc}"
            ) from exc
        raise SourceProcessingJobError(
            f"Unsupported source-processing stage {cursor.next_stage!r}."
        )

    def _verify(
        self,
        job_id: uuid.UUID,
        lease_token: bytes,
        cursor: _Cursor,
    ) -> SourceProcessingStepResult:
        path = self.sources.verify(cursor.source_id)
        source, blob = self.sources.get(cursor.source_id)
        checkpoint = self.jobs.checkpoint(
            job_id,
            lease_token=lease_token,
            current_stage="source_verified",
            progress_state={"completed_stages": 1, "total_stages": _TOTAL_WORK_STAGES},
            last_confirmed_input={"source_id": str(cursor.source_id)},
            last_confirmed_output={
                "blob_id": str(blob.blob_id),
                "byte_length": blob.byte_length,
                "source_sha256": source.content_sha256.hex(),
                "verified_path_name": path.name,
            },
            resume_metadata=self._resume_payload(
                source_id=cursor.source_id,
                next_stage=_STAGE_REPRESENT,
            ),
        )
        return self._after_checkpoint(
            job_id,
            checkpoint=checkpoint,
            completed_stage=_STAGE_VERIFY,
            representation_id=None,
            chunk_count=None,
        )

    def _represent(
        self,
        job_id: uuid.UUID,
        lease_token: bytes,
        cursor: _Cursor,
    ) -> SourceProcessingStepResult:
        source, _blob = self.sources.get(cursor.source_id)
        is_pdf = self.source_pdf.supports(source)
        is_docx = self.source_docx.supports(source)
        is_html = self.source_html.supports(source)
        representation = self._compatible_representation(
            cursor.source_id,
            is_pdf=is_pdf,
            is_docx=is_docx,
            is_html=is_html,
        )
        reused_representation = representation is not None
        if representation is None:
            if is_pdf:
                built_pdf = self.source_pdf.build(cursor.source_id)
                representation = built_pdf.result.representation
            elif is_docx:
                built_docx = self.source_docx.build(cursor.source_id)
                representation = built_docx.result.representation
            elif is_html:
                built_html = self.source_html.build(cursor.source_id)
                representation = built_html.result.representation
            else:
                built_text = self.source_text.build(cursor.source_id)
                representation = built_text.result.representation
        self.source_text.verify(representation.representation_id)
        if is_pdf:
            self.source_pdf.verify_page_map(representation.representation_id)
        if is_docx:
            self.source_docx.verify_structure_map(representation.representation_id)
        if is_html:
            self.source_html.verify_structure_map(representation.representation_id)
        checkpoint = self.jobs.checkpoint(
            job_id,
            lease_token=lease_token,
            current_stage="representation_ready",
            progress_state={"completed_stages": 2, "total_stages": _TOTAL_WORK_STAGES},
            last_confirmed_input={"source_id": str(cursor.source_id)},
            last_confirmed_output={
                "representation_id": str(representation.representation_id),
                "representation_sha256": representation.content_hash.hex(),
                "reused_representation": reused_representation,
            },
            resume_metadata=self._resume_payload(
                source_id=cursor.source_id,
                next_stage=_STAGE_CHUNK,
                representation_id=representation.representation_id,
            ),
        )
        return self._after_checkpoint(
            job_id,
            checkpoint=checkpoint,
            completed_stage=_STAGE_REPRESENT,
            representation_id=representation.representation_id,
            chunk_count=None,
        )

    def _chunk(
        self,
        job_id: uuid.UUID,
        lease_token: bytes,
        cursor: _Cursor,
    ) -> SourceProcessingStepResult:
        representation_id = self._require_representation(cursor)
        self._verify_cursor_representation(cursor.source_id, representation_id)
        built = self.source_chunks.build_default(representation_id)
        checkpoint = self._checkpoint_chunks(
            job_id,
            lease_token,
            cursor.source_id,
            representation_id,
            built,
            repaired=False,
        )
        return self._after_checkpoint(
            job_id,
            checkpoint=checkpoint,
            completed_stage=_STAGE_CHUNK,
            representation_id=representation_id,
            chunk_count=len(built.chunks),
        )

    def _finalize(
        self,
        job_id: uuid.UUID,
        lease_token: bytes,
        cursor: _Cursor,
    ) -> SourceProcessingStepResult:
        representation_id = self._require_representation(cursor)
        text = self._verify_cursor_representation(cursor.source_id, representation_id)
        chunks = self.source_chunks.list_for_representation(representation_id, limit=5000)
        derived_valid = True
        if text and not chunks:
            derived_valid = False
        elif chunks:
            try:
                verified = tuple(self.source_chunks.verify(item.chunk_id) for item in chunks)
            except Exception:
                derived_valid = False
            else:
                if "".join(item.chunk_text for item in verified) != text:
                    derived_valid = False
                if cursor.build_signature is None:
                    derived_valid = False
                elif any(
                    item.build_signature != cursor.build_signature for item in verified
                ):
                    derived_valid = False
                if cursor.chunk_count is not None and len(verified) != cursor.chunk_count:
                    derived_valid = False

        if not derived_valid:
            built = self.source_chunks.build_default(representation_id)
            checkpoint = self._checkpoint_chunks(
                job_id,
                lease_token,
                cursor.source_id,
                representation_id,
                built,
                repaired=True,
            )
            return self._after_checkpoint(
                job_id,
                checkpoint=checkpoint,
                completed_stage="derived_repair",
                representation_id=representation_id,
                chunk_count=len(built.chunks),
            )

        completed = self.jobs.complete(job_id, lease_token=lease_token)
        return SourceProcessingStepResult(
            job=completed,
            completed_stage=_STAGE_FINALIZE,
            checkpoint=None,
            representation_id=representation_id,
            chunk_count=len(chunks),
            done=True,
        )

    def _checkpoint_chunks(
        self,
        job_id: uuid.UUID,
        lease_token: bytes,
        source_id: uuid.UUID,
        representation_id: uuid.UUID,
        built: SourceChunkBuildResult,
        *,
        repaired: bool,
    ) -> CheckpointRecord:
        return self.jobs.checkpoint(
            job_id,
            lease_token=lease_token,
            current_stage="chunks_ready",
            progress_state={"completed_stages": 3, "total_stages": _TOTAL_WORK_STAGES},
            last_confirmed_input={"representation_id": str(representation_id)},
            last_confirmed_output={
                "build_signature": built.build_signature.hex(),
                "chunk_count": len(built.chunks),
                "derived_repair": repaired,
                "lexical_search_index": "current",
                "embedding_index": "deferred",
            },
            resume_metadata=self._resume_payload(
                source_id=source_id,
                next_stage=_STAGE_FINALIZE,
                representation_id=representation_id,
                build_signature=built.build_signature,
                chunk_count=len(built.chunks),
            ),
        )

    def _after_checkpoint(
        self,
        job_id: uuid.UUID,
        *,
        checkpoint: CheckpointRecord,
        completed_stage: str,
        representation_id: uuid.UUID | None,
        chunk_count: int | None,
    ) -> SourceProcessingStepResult:
        job = self.jobs.get(job_id)
        if job.state is JobState.CANCEL_REQUESTED:
            if job.lease_token is None:
                raise JobLeaseError("Cancel-requested job unexpectedly lost its lease.")
            job = self.jobs.acknowledge_cancel(
                job_id,
                lease_token=job.lease_token,
            )
            return SourceProcessingStepResult(
                job=job,
                completed_stage=completed_stage,
                checkpoint=checkpoint,
                representation_id=representation_id,
                chunk_count=chunk_count,
                done=True,
            )
        return SourceProcessingStepResult(
            job=job,
            completed_stage=completed_stage,
            checkpoint=checkpoint,
            representation_id=representation_id,
            chunk_count=chunk_count,
            done=False,
        )

    def _cursor(self, job: JobRecord) -> _Cursor:
        source_id = self._source_id_from_scope(job)
        if job.last_checkpoint_id is None:
            return _Cursor(source_id=source_id, next_stage=_STAGE_VERIFY)
        checkpoint = self.jobs.get_checkpoint(job.last_checkpoint_id)
        if checkpoint.job_id != job.job_id:
            raise SourceProcessingJobError("Job checkpoint belongs to another job.")
        payload = _json_object(checkpoint.resume_metadata_json, "resume_metadata")
        if payload.get("pipeline_version") != _PIPELINE_VERSION:
            raise SourceProcessingJobError("Checkpoint pipeline_version is incompatible.")
        if payload.get("source_id") != str(source_id):
            raise SourceProcessingJobError("Checkpoint source_id disagrees with job scope.")
        next_stage = payload.get("next_stage")
        if not isinstance(next_stage, str) or next_stage not in _ALLOWED_STAGES:
            raise SourceProcessingJobError("Checkpoint next_stage is invalid.")
        representation_id = _optional_uuid(payload.get("representation_id"), "representation_id")
        build_signature = _optional_hash(payload.get("build_signature"), "build_signature")
        chunk_count = _optional_nonnegative_int(payload.get("chunk_count"), "chunk_count")
        if next_stage in {_STAGE_CHUNK, _STAGE_FINALIZE} and representation_id is None:
            raise SourceProcessingJobError(
                "Checkpoint requires representation_id for the next stage."
            )
        if next_stage == _STAGE_FINALIZE and build_signature is None:
            raise SourceProcessingJobError(
                "Finalize checkpoint requires a chunk build signature."
            )
        return _Cursor(
            source_id=source_id,
            next_stage=next_stage,
            representation_id=representation_id,
            build_signature=build_signature,
            chunk_count=chunk_count,
        )

    def _validate_job_contract(self, job: JobRecord) -> None:
        if job.job_type != "source.process":
            raise SourceProcessingJobError(
                f"Job {job.job_id} has type {job.job_type!r}, not 'source.process'."
            )
        config = _json_object(job.pinned_configuration_json, "pinned_configuration")
        legacy_expected = {
            "pipeline_version": _PIPELINE_VERSION,
            "text_parser": f"{_TEXT_PARSER_ID}@{_TEXT_PARSER_VERSION}",
            "chunking_profile": "default",
            "embedding_policy": "deferred",
        }
        pdf_expected = {
            **legacy_expected,
            "pdf_parser": self.source_pdf.parser_signature,
        }
        docx_expected = {
            **pdf_expected,
            "docx_parser": self.source_docx.parser_signature,
        }
        current_expected = {
            **docx_expected,
            "html_parser": self.source_html.parser_signature,
        }
        if config not in (legacy_expected, pdf_expected, docx_expected, current_expected):
            raise SourceProcessingJobError(
                "source.process pinned configuration is missing or incompatible."
            )
        source_id = self._source_id_from_scope(job)
        source, _blob = self.sources.get(source_id)
        if self.source_pdf.supports(source) and config == legacy_expected:
            raise SourceProcessingJobError(
                "Legacy source.process job did not pin a PDF parser and cannot process PDFs."
            )
        if self.source_docx.supports(source) and config not in (docx_expected, current_expected):
            raise SourceProcessingJobError(
                "Legacy source.process job did not pin a DOCX parser and cannot process DOCX."
            )
        if self.source_html.supports(source) and config != current_expected:
            raise SourceProcessingJobError(
                "Legacy source.process job did not pin an HTML parser and cannot process HTML."
            )
        self._source_id_from_scope(job)

    @staticmethod
    def _source_id_from_scope(job: JobRecord) -> uuid.UUID:
        scope = _json_object(job.requested_scope_json, "requested_scope")
        value = scope.get("source_id")
        if not isinstance(value, str):
            raise SourceProcessingJobError("source.process scope requires source_id.")
        try:
            return uuid.UUID(value)
        except ValueError as exc:
            raise SourceProcessingJobError(
                "source.process scope contains an invalid source_id."
            ) from exc

    def _compatible_representation(
        self, source_id: uuid.UUID, *, is_pdf: bool, is_docx: bool, is_html: bool
    ) -> SourceRepresentationRecord | None:
        if sum((is_pdf, is_docx, is_html)) > 1:
            raise SourceProcessingJobError("Source format detection is ambiguous.")
        if is_pdf:
            expected_type = SourceRepresentationType.EXTRACTED_TEXT
            expected_parser_id = self.source_pdf.parser_id
            expected_parser_version = self.source_pdf.parser_version
            expected_options = self.source_pdf.parser_options
        elif is_docx:
            expected_type = SourceRepresentationType.NORMALIZED_TEXT
            expected_parser_id = self.source_docx.parser_id
            expected_parser_version = self.source_docx.parser_version
            expected_options = self.source_docx.parser_options
        elif is_html:
            expected_type = SourceRepresentationType.NORMALIZED_TEXT
            expected_parser_id = self.source_html.parser_id
            expected_parser_version = self.source_html.parser_version
            expected_options = self.source_html.parser_options
        else:
            expected_type = SourceRepresentationType.NORMALIZED_TEXT
            expected_parser_id = _TEXT_PARSER_ID
            expected_parser_version = _TEXT_PARSER_VERSION
            expected_options = _TEXT_OPTIONS

        for representation, _blob in self.source_text.list_for_source(source_id, limit=100):
            if representation.representation_type is not expected_type:
                continue
            if representation.retention_state is not RepresentationRetentionState.RETAINED:
                continue
            if representation.parser_id != expected_parser_id:
                continue
            if representation.parser_version != expected_parser_version:
                continue
            try:
                options = json.loads(representation.options_json)
            except json.JSONDecodeError as exc:
                raise SourceProcessingJobError(
                    "Retained representation has invalid parser options JSON."
                ) from exc
            if options != expected_options:
                continue
            self.source_text.verify(representation.representation_id)
            if is_pdf:
                self.source_pdf.verify_page_map(representation.representation_id)
            if is_docx:
                self.source_docx.verify_structure_map(representation.representation_id)
            if is_html:
                self.source_html.verify_structure_map(representation.representation_id)
            return representation
        return None

    def _verify_cursor_representation(
        self,
        source_id: uuid.UUID,
        representation_id: uuid.UUID,
    ) -> str:
        representation, _blob = self.source_text.get(representation_id)
        if representation.source_id != source_id:
            raise SourceProcessingJobError(
                "Checkpoint representation belongs to a different Source."
            )
        if representation.retention_state is not RepresentationRetentionState.RETAINED:
            raise SourceProcessingJobError(
                "Checkpoint representation is not retained persistent state."
            )
        text = self.source_text.read_text(representation_id)
        if representation.parser_id == self.source_pdf.parser_id:
            self.source_pdf.verify_page_map(representation_id)
        if representation.parser_id == self.source_docx.parser_id:
            self.source_docx.verify_structure_map(representation_id)
        if representation.parser_id == self.source_html.parser_id:
            self.source_html.verify_structure_map(representation_id)
        return text

    @staticmethod
    def _require_representation(cursor: _Cursor) -> uuid.UUID:
        if cursor.representation_id is None:
            raise SourceProcessingJobError("Resume cursor has no representation_id.")
        return cursor.representation_id

    @staticmethod
    def _resume_payload(
        *,
        source_id: uuid.UUID,
        next_stage: str,
        representation_id: uuid.UUID | None = None,
        build_signature: bytes | None = None,
        chunk_count: int | None = None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "pipeline_version": _PIPELINE_VERSION,
            "source_id": str(source_id),
            "next_stage": next_stage,
        }
        if representation_id is not None:
            payload["representation_id"] = str(representation_id)
        if build_signature is not None:
            payload["build_signature"] = build_signature.hex()
        if chunk_count is not None:
            payload["chunk_count"] = chunk_count
        return payload


def _json_object(value: str | None, label: str) -> dict[str, Any]:
    if value is None:
        raise SourceProcessingJobError(f"source.process {label} is missing.")
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError as exc:
        raise SourceProcessingJobError(
            f"source.process {label} contains invalid JSON."
        ) from exc
    if not isinstance(parsed, dict):
        raise SourceProcessingJobError(f"source.process {label} must be a JSON object.")
    return parsed


def _optional_uuid(value: object, label: str) -> uuid.UUID | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise SourceProcessingJobError(f"Checkpoint {label} must be a UUID string.")
    try:
        return uuid.UUID(value)
    except ValueError as exc:
        raise SourceProcessingJobError(f"Checkpoint {label} is invalid.") from exc


def _optional_hash(value: object, label: str) -> bytes | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise SourceProcessingJobError(f"Checkpoint {label} must be hexadecimal.")
    try:
        raw = bytes.fromhex(value)
    except ValueError as exc:
        raise SourceProcessingJobError(f"Checkpoint {label} is invalid hexadecimal.") from exc
    if len(raw) != 32:
        raise SourceProcessingJobError(f"Checkpoint {label} must contain 32 bytes.")
    return raw


def _optional_nonnegative_int(value: object, label: str) -> int | None:
    if value is None:
        return None
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise SourceProcessingJobError(
            f"Checkpoint {label} must be a non-negative integer."
        )
    return value


def _failure_reason(exc: Exception) -> str:
    detail = f"{type(exc).__name__}: {exc}"
    return detail[:1000]
