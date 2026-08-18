"""Deterministic SourceChunk generation from retained text representations."""

from __future__ import annotations

import hashlib
import json
import uuid
from bisect import bisect_right
from dataclasses import dataclass

from athena.chat.service import ChatService
from athena.common.ids import new_uuid7
from athena.common.time import utc_now_us
from athena.model.provenance import ModelRunRepository, ProcessingRun
from athena.source.chunk_store import (
    SourceChunkNotFoundError,
    SourceChunkPlanRecord,
    SourceChunkRecord,
    SourceChunkStore,
    StagedSourceChunkRecord,
)
from athena.source.chunking_repository import ChunkingProfile, ChunkingProfileRepository
from athena.source.models import (
    SourceRepresentationStructureRecord,
    SourceRepresentationType,
)
from athena.source.representation_service import SourceTextRepresentationService

_PIPELINE_VERSION = "source-chunking-v1"


class SourceChunkIntegrityError(RuntimeError):
    """Raised when a derived chunk no longer matches its retained representation."""


class SourceChunkStagingLostError(SourceChunkIntegrityError):
    """Raised when reconstructible unpublished large-source staging disappeared."""


@dataclass(frozen=True, slots=True)
class SourceChunkBuildResult:
    profile: ChunkingProfile
    processing_run: ProcessingRun
    build_signature: bytes
    chunks: tuple[SourceChunkRecord, ...]


@dataclass(frozen=True, slots=True)
class SourceChunkStagingPlanResult:
    """Deterministic unpublished plan for a potentially large representation."""

    profile: ChunkingProfile
    build_signature: bytes
    chunk_count: int


@dataclass(frozen=True, slots=True)
class SourceChunkStagingBatchResult:
    """One atomically staged, but still unpublished, chunk batch."""

    build_signature: bytes
    start_index: int
    next_index: int
    total_chunks: int
    batch_count: int


@dataclass(frozen=True, slots=True)
class SourceChunkPublishResult:
    """Published result of a complete staged SourceChunk build."""

    profile: ChunkingProfile
    processing_run: ProcessingRun
    build_signature: bytes
    chunk_count: int


class SourceChunkingService:
    """Build reconstructible paragraph-aware chunks without mutating Raw Archive state."""

    def __init__(
        self,
        *,
        source_text: SourceTextRepresentationService,
        profiles: ChunkingProfileRepository,
        store: SourceChunkStore,
        runs: ModelRunRepository,
        chat: ChatService,
    ) -> None:
        self.source_text = source_text
        self.profiles = profiles
        self.store = store
        self.runs = runs
        self.chat = chat

    def build_default(self, representation_id: uuid.UUID) -> SourceChunkBuildResult:
        representation, blob = self.source_text.get(representation_id)
        if representation.representation_type not in {
            SourceRepresentationType.NORMALIZED_TEXT,
            SourceRepresentationType.EXTRACTED_TEXT,
        }:
            raise ValueError(
                "Source chunking requires a retained normalized_text or extracted_text representation."
            )
        path = self.source_text.verify(representation_id)
        structures = self.source_text.list_structures(representation_id)
        if representation.parser_id in {"athena.native_docx", "athena.native_html"} and not structures:
            format_name = "DOCX" if representation.parser_id == "athena.native_docx" else "HTML"
            raise SourceChunkIntegrityError(
                f"Native {format_name} representation is missing its retained structure map."
            )
        profile = (
            self.profiles.get_or_create_document_default()
            if structures
            else self.profiles.get_or_create_default()
        )
        build_signature = _build_signature(
            representation_id=representation_id,
            representation_hash=representation.content_hash,
            profile=profile,
        )
        actor_id = self.chat.ensure_local_user()
        run = self.runs.start_run(
            run_type="source_chunk_build",
            trigger_actor_id=actor_id,
            pipeline_version=_PIPELINE_VERSION,
            input_snapshot={
                "source_id": str(representation.source_id),
                "representation_id": str(representation.representation_id),
                "representation_sha256": representation.content_hash.hex(),
                "representation_byte_length": blob.byte_length,
            },
            configuration={
                "chunking_profile_id": str(profile.chunking_profile_id),
                "algorithm": profile.algorithm,
                "tokenizer": profile.tokenizer,
                "target_size": profile.target_size,
                "overlap_size": profile.overlap_size,
                "structure_rules": json.loads(profile.structure_rules_json),
                "profile_version": profile.profile_version,
                "build_signature": build_signature.hex(),
            },
            model_signature_id=None,
            prompt_template_id=None,
            prompt_template_version=None,
        )

        try:
            text = path.read_text(encoding="utf-8")
            if structures:
                _verify_structure_spans(text, structures)
                units, structure_boundaries = _document_structure_units(text, structures)
                spans = _chunk_spans(
                    text,
                    target_size=profile.target_size or 1200,
                    units=units,
                    preferred_boundaries=structure_boundaries,
                )
            else:
                spans = _chunk_spans(text, target_size=profile.target_size or 1200)
            created_at_us = utc_now_us()
            chunks = tuple(
                SourceChunkRecord(
                    chunk_id=new_uuid7(),
                    source_id=representation.source_id,
                    representation_id=representation.representation_id,
                    chunk_index=index,
                    chunking_profile_id=profile.chunking_profile_id,
                    start_anchor_value=start,
                    end_anchor_value=end,
                    content_hash=hashlib.sha256(text[start:end].encode("utf-8")).digest(),
                    processing_run_id=run.processing_run_id,
                    build_signature=build_signature,
                    chunk_text=text[start:end],
                    created_at_us=created_at_us,
                )
                for index, (start, end) in enumerate(spans)
            )
            self.store.replace_build(
                representation_id=representation.representation_id,
                chunking_profile_id=profile.chunking_profile_id,
                build_signature=build_signature,
                processing_run_id=run.processing_run_id,
                created_at_us=created_at_us,
                chunks=chunks,
            )
            finished = self.runs.finish_run(run.processing_run_id, status="succeeded")
            return SourceChunkBuildResult(
                profile=profile,
                processing_run=finished,
                build_signature=build_signature,
                chunks=chunks,
            )
        except Exception as exc:
            current = self.runs.load_run(run.processing_run_id)
            if current.status == "running":
                self.runs.finish_run(
                    run.processing_run_id,
                    status="failed",
                    error_detail=type(exc).__name__,
                )
            raise

    def prepare_staged_default(
        self,
        representation_id: uuid.UUID,
    ) -> SourceChunkStagingPlanResult:
        """Prepare a deterministic offset plan without changing the visible chunk build."""
        representation, _blob = self.source_text.get(representation_id)
        profile, text, spans = self._profile_text_and_spans(representation_id)
        build_signature = _build_signature(
            representation_id=representation_id,
            representation_hash=representation.content_hash,
            profile=profile,
        )
        plan: list[SourceChunkPlanRecord] = []
        previous_char_end = 0
        byte_cursor = 0
        for index, (start, end) in enumerate(spans):
            if start != previous_char_end:
                raise SourceChunkIntegrityError(
                    "Large-source plan is not contiguous in representation coordinates."
                )
            fragment_bytes = text[start:end].encode("utf-8")
            plan.append(
                SourceChunkPlanRecord(
                    chunk_index=index,
                    start_anchor_value=start,
                    end_anchor_value=end,
                    start_byte_offset=byte_cursor,
                    end_byte_offset=byte_cursor + len(fragment_bytes),
                    content_hash=hashlib.sha256(fragment_bytes).digest(),
                )
            )
            byte_cursor += len(fragment_bytes)
            previous_char_end = end
        if byte_cursor != len(text.encode("utf-8")):
            raise SourceChunkIntegrityError(
                "Large-source plan byte coverage disagrees with retained representation."
            )
        self.store.prepare_staged_build(
            source_id=representation.source_id,
            representation_id=representation.representation_id,
            chunking_profile_id=profile.chunking_profile_id,
            build_signature=build_signature,
            representation_hash=representation.content_hash,
            plan=tuple(plan),
            created_at_us=utc_now_us(),
        )
        return SourceChunkStagingPlanResult(
            profile=profile,
            build_signature=build_signature,
            chunk_count=len(plan),
        )

    def stage_staged_default_batch(
        self,
        representation_id: uuid.UUID,
        *,
        build_signature: bytes,
        start_index: int,
        batch_size: int,
    ) -> SourceChunkStagingBatchResult:
        """Stage one bounded batch using persisted UTF-8 byte offsets from the plan."""
        if start_index < 0:
            raise ValueError("Large-source batch start_index must not be negative.")
        if not 1 <= batch_size <= 4096:
            raise ValueError("Large-source batch_size must be between 1 and 4096.")
        representation, _blob = self.source_text.get(representation_id)
        path = self.source_text.verify(representation_id)
        try:
            staged = self.store.get_staged_build(build_signature)
        except SourceChunkNotFoundError as exc:
            raise SourceChunkStagingLostError(
                "Unpublished large-source staging is missing and must restart from its plan boundary."
            ) from exc
        if staged.representation_id != representation_id:
            raise SourceChunkIntegrityError(
                "Staged large-source build belongs to a different representation."
            )
        if staged.representation_hash != representation.content_hash:
            raise SourceChunkIntegrityError(
                "Staged large-source build references a different representation hash."
            )
        if start_index > staged.total_chunks:
            raise SourceChunkIntegrityError(
                "Large-source resume index exceeds the deterministic chunk plan."
            )
        if self.store.staged_prefix_count(build_signature, start_index) != start_index:
            raise SourceChunkStagingLostError(
                "Previously confirmed unpublished chunk staging is missing."
            )
        plan = self.store.list_staged_plan(
            build_signature,
            start_index=start_index,
            limit=batch_size,
        )
        expected_indexes = tuple(range(start_index, start_index + len(plan)))
        if tuple(item.chunk_index for item in plan) != expected_indexes:
            raise SourceChunkIntegrityError(
                "Large-source staged plan is missing a contiguous batch range."
            )
        profile = self.profiles.get(staged.chunking_profile_id)
        created_at_us = utc_now_us()
        chunks: list[StagedSourceChunkRecord] = []
        with path.open("rb") as handle:
            for item in plan:
                handle.seek(item.start_byte_offset)
                raw = handle.read(item.end_byte_offset - item.start_byte_offset)
                if len(raw) != item.end_byte_offset - item.start_byte_offset:
                    raise SourceChunkIntegrityError(
                        "Retained representation ended before a planned chunk byte range."
                    )
                try:
                    text = raw.decode("utf-8")
                except UnicodeDecodeError as exc:
                    raise SourceChunkIntegrityError(
                        "Planned chunk byte range is not valid retained UTF-8 text."
                    ) from exc
                if len(text) != item.end_anchor_value - item.start_anchor_value:
                    raise SourceChunkIntegrityError(
                        "Planned byte range disagrees with codepoint anchor length."
                    )
                actual_hash = hashlib.sha256(raw).digest()
                if actual_hash != item.content_hash:
                    raise SourceChunkIntegrityError(
                        "Planned chunk hash disagrees with retained representation bytes."
                    )
                chunks.append(
                    StagedSourceChunkRecord(
                        chunk_id=new_uuid7(),
                        source_id=representation.source_id,
                        representation_id=representation.representation_id,
                        chunk_index=item.chunk_index,
                        chunking_profile_id=profile.chunking_profile_id,
                        start_anchor_value=item.start_anchor_value,
                        end_anchor_value=item.end_anchor_value,
                        content_hash=item.content_hash,
                        build_signature=build_signature,
                        chunk_text=text,
                        created_at_us=created_at_us,
                    )
                )
        next_index = self.store.stage_chunk_batch(
            build_signature=build_signature,
            start_index=start_index,
            chunks=tuple(chunks),
        )
        return SourceChunkStagingBatchResult(
            build_signature=build_signature,
            start_index=start_index,
            next_index=next_index,
            total_chunks=staged.total_chunks,
            batch_count=len(chunks),
        )

    def discard_staged_default(self, build_signature: bytes) -> None:
        """Discard reconstructible unpublished staging, for example after cancellation."""
        self.store.discard_staged_build(build_signature)

    def publish_staged_default(
        self,
        representation_id: uuid.UUID,
        *,
        build_signature: bytes,
        expected_chunk_count: int,
    ) -> SourceChunkPublishResult:
        """Publish a fully staged build atomically; partial staging never becomes searchable."""
        representation, blob = self.source_text.get(representation_id)
        profile = self._default_profile_for_representation(representation_id)
        current = self.store.current_build(representation_id, profile.chunking_profile_id)
        if current is not None and current.build_signature == build_signature:
            run = self.runs.load_run(current.processing_run_id)
            if run.status != "succeeded" or current.chunk_count != expected_chunk_count:
                raise SourceChunkIntegrityError(
                    "Published large-source build metadata is inconsistent."
                )
            return SourceChunkPublishResult(
                profile=profile,
                processing_run=run,
                build_signature=build_signature,
                chunk_count=current.chunk_count,
            )
        try:
            staged = self.store.get_staged_build(build_signature)
        except SourceChunkNotFoundError as exc:
            raise SourceChunkStagingLostError(
                "Unpublished large-source staging disappeared before publication."
            ) from exc
        if staged.representation_id != representation_id:
            raise SourceChunkIntegrityError(
                "Staged build belongs to a different retained representation."
            )
        if staged.total_chunks != expected_chunk_count:
            raise SourceChunkIntegrityError(
                "Staged build chunk count disagrees with the durable resume cursor."
            )
        if self.store.staged_chunk_count(build_signature) != expected_chunk_count:
            raise SourceChunkIntegrityError(
                "Cannot publish an incomplete large-source staged build."
            )
        digest = hashlib.sha256()
        expected_index = 0
        expected_start = 0
        for chunk in self.store.iter_staged_chunks(build_signature):
            if chunk.chunk_index != expected_index or chunk.start_anchor_value != expected_start:
                raise SourceChunkIntegrityError(
                    "Staged large-source chunks contain an index/range gap or overlap."
                )
            raw = chunk.chunk_text.encode("utf-8")
            if len(chunk.chunk_text) != chunk.end_anchor_value - chunk.start_anchor_value:
                raise SourceChunkIntegrityError(
                    "Staged large-source chunk anchor length is invalid."
                )
            if hashlib.sha256(raw).digest() != chunk.content_hash:
                raise SourceChunkIntegrityError(
                    "Staged large-source chunk hash is invalid."
                )
            digest.update(raw)
            expected_index += 1
            expected_start = chunk.end_anchor_value
        if expected_index != expected_chunk_count or digest.digest() != representation.content_hash:
            raise SourceChunkIntegrityError(
                "Staged large-source chunks do not reproduce the retained representation hash."
            )
        actor_id = self.chat.ensure_local_user()
        run = self.runs.start_run(
            run_type="source_chunk_build",
            trigger_actor_id=actor_id,
            pipeline_version="source-chunking-v2-batched",
            input_snapshot={
                "source_id": str(representation.source_id),
                "representation_id": str(representation.representation_id),
                "representation_sha256": representation.content_hash.hex(),
                "representation_byte_length": blob.byte_length,
            },
            configuration={
                "chunking_profile_id": str(profile.chunking_profile_id),
                "algorithm": profile.algorithm,
                "tokenizer": profile.tokenizer,
                "target_size": profile.target_size,
                "overlap_size": profile.overlap_size,
                "structure_rules": json.loads(profile.structure_rules_json),
                "profile_version": profile.profile_version,
                "build_signature": build_signature.hex(),
                "publication": "atomic_staged_publish",
            },
            model_signature_id=None,
            prompt_template_id=None,
            prompt_template_version=None,
        )
        # Finish run metadata before publication. This ordering guarantees that
        # visible SourceChunks never point at a non-succeeded ProcessingRun,
        # even though athena.db and Derived search.db cannot share one txn.
        finished = self.runs.finish_run(run.processing_run_id, status="succeeded")
        published_count = self.store.publish_staged_build(
            build_signature=build_signature,
            processing_run_id=finished.processing_run_id,
            created_at_us=utc_now_us(),
        )
        if published_count != expected_chunk_count:
            raise SourceChunkIntegrityError(
                "Published large-source chunk count changed during atomic publication."
            )
        return SourceChunkPublishResult(
            profile=profile,
            processing_run=finished,
            build_signature=build_signature,
            chunk_count=published_count,
        )


    def verify_current_build(
        self,
        representation_id: uuid.UUID,
        *,
        expected_build_signature: bytes,
        expected_chunk_count: int,
    ) -> int:
        """Stream-verify an arbitrarily large visible build against retained SHA-256."""
        profile = self._default_profile_for_representation(representation_id)
        return self.verify_current_profile_build(
            representation_id,
            chunking_profile_id=profile.chunking_profile_id,
            expected_build_signature=expected_build_signature,
            expected_chunk_count=expected_chunk_count,
        )

    def verify_current_profile_build(
        self,
        representation_id: uuid.UUID,
        *,
        chunking_profile_id: uuid.UUID,
        expected_build_signature: bytes,
        expected_chunk_count: int,
    ) -> int:
        """Stream-verify one exact current profile build against retained evidence."""
        representation, _blob = self.source_text.get(representation_id)
        self.source_text.verify(representation_id)
        profile = self.profiles.get(chunking_profile_id)
        derived_signature = _build_signature(
            representation_id=representation.representation_id,
            representation_hash=representation.content_hash,
            profile=profile,
        )
        if derived_signature != expected_build_signature:
            raise SourceChunkIntegrityError(
                "Expected SourceChunk build signature disagrees with retained inputs."
            )
        current = self.store.current_build(representation_id, chunking_profile_id)
        if current is None:
            raise SourceChunkIntegrityError("Current SourceChunk build is missing.")
        if current.build_signature != expected_build_signature:
            raise SourceChunkIntegrityError("Current SourceChunk build signature is stale.")
        if current.chunk_count != expected_chunk_count:
            raise SourceChunkIntegrityError("Current SourceChunk count is incomplete.")
        run = self.runs.load_run(current.processing_run_id)
        if run.status != "succeeded":
            raise SourceChunkIntegrityError(
                "Current SourceChunk build references a non-succeeded ProcessingRun."
            )

        digest = hashlib.sha256()
        expected_index = 0
        expected_start = 0
        for chunk in self.store.iter_for_representation(
            representation_id,
            chunking_profile_id=chunking_profile_id,
        ):
            if chunk.chunk_index != expected_index:
                raise SourceChunkIntegrityError(
                    "Current SourceChunk indexes are not contiguous."
                )
            if chunk.source_id != representation.source_id:
                raise SourceChunkIntegrityError("Current SourceChunk source_id is invalid.")
            if chunk.processing_run_id != current.processing_run_id:
                raise SourceChunkIntegrityError(
                    "Current SourceChunk processing_run_id disagrees with its build."
                )
            if chunk.start_anchor_value != expected_start:
                raise SourceChunkIntegrityError(
                    "Current SourceChunk ranges contain a gap or overlap."
                )
            if (
                chunk.end_anchor_value - chunk.start_anchor_value
                != len(chunk.chunk_text)
            ):
                raise SourceChunkIntegrityError(
                    "Current SourceChunk codepoint range disagrees with its text."
                )
            raw = chunk.chunk_text.encode("utf-8")
            if hashlib.sha256(raw).digest() != chunk.content_hash:
                raise SourceChunkIntegrityError(
                    "Current SourceChunk content hash is invalid."
                )
            if chunk.build_signature != expected_build_signature:
                raise SourceChunkIntegrityError(
                    "Current SourceChunk has a stale build signature."
                )
            digest.update(raw)
            expected_start = chunk.end_anchor_value
            expected_index += 1

        if expected_index != expected_chunk_count:
            raise SourceChunkIntegrityError("Current SourceChunk stream ended early.")
        if digest.digest() != representation.content_hash:
            raise SourceChunkIntegrityError(
                "Concatenated SourceChunks do not reproduce the retained representation hash."
            )
        return expected_index
    def _default_profile_for_representation(
        self,
        representation_id: uuid.UUID,
    ) -> ChunkingProfile:
        representation, _blob = self.source_text.get(representation_id)
        structures = self.source_text.list_structures(representation_id)
        if representation.parser_id in {"athena.native_docx", "athena.native_html"} and not structures:
            format_name = "DOCX" if representation.parser_id == "athena.native_docx" else "HTML"
            raise SourceChunkIntegrityError(
                f"Native {format_name} representation is missing its retained structure map."
            )
        return (
            self.profiles.get_or_create_document_default()
            if structures
            else self.profiles.get_or_create_default()
        )

    def _profile_text_and_spans(
        self,
        representation_id: uuid.UUID,
    ) -> tuple[ChunkingProfile, str, tuple[tuple[int, int], ...]]:
        representation, _blob = self.source_text.get(representation_id)
        if representation.representation_type not in {
            SourceRepresentationType.NORMALIZED_TEXT,
            SourceRepresentationType.EXTRACTED_TEXT,
        }:
            raise ValueError(
                "Source chunking requires a retained normalized_text or extracted_text representation."
            )
        path = self.source_text.verify(representation_id)
        structures = self.source_text.list_structures(representation_id)
        profile = self._default_profile_for_representation(representation_id)
        text = path.read_text(encoding="utf-8")
        if structures:
            _verify_structure_spans(text, structures)
            units, structure_boundaries = _document_structure_units(text, structures)
            spans = _chunk_spans(
                text,
                target_size=profile.target_size or 1200,
                units=units,
                preferred_boundaries=structure_boundaries,
            )
        else:
            spans = _chunk_spans(text, target_size=profile.target_size or 1200)
        return profile, text, spans

    def get(self, chunk_id: uuid.UUID) -> SourceChunkRecord:
        return self.store.get(chunk_id)

    def list_for_representation(
        self,
        representation_id: uuid.UUID,
        *,
        limit: int = 500,
    ) -> tuple[SourceChunkRecord, ...]:
        self.source_text.get(representation_id)
        chunks = self.store.list_for_representation(representation_id, limit=limit)
        if chunks:
            run = self.runs.load_run(chunks[0].processing_run_id)
            if run.status != "succeeded":
                raise SourceChunkIntegrityError(
                    "Current SourceChunk build references a non-succeeded ProcessingRun."
                )
        return chunks

    def verify(self, chunk_id: uuid.UUID) -> SourceChunkRecord:
        chunk = self.store.get(chunk_id)
        representation, _ = self.source_text.get(chunk.representation_id)
        if representation.source_id != chunk.source_id:
            raise SourceChunkIntegrityError("SourceChunk source_id disagrees with its representation.")
        profile = self.profiles.get(chunk.chunking_profile_id)
        expected_build_signature = _build_signature(
            representation_id=representation.representation_id,
            representation_hash=representation.content_hash,
            profile=profile,
        )
        if chunk.build_signature != expected_build_signature:
            raise SourceChunkIntegrityError("SourceChunk build signature is invalid.")
        run = self.runs.load_run(chunk.processing_run_id)
        if run.status != "succeeded":
            raise SourceChunkIntegrityError("SourceChunk references a non-succeeded ProcessingRun.")

        text = self.source_text.read_text(chunk.representation_id)
        if not 0 <= chunk.start_anchor_value <= chunk.end_anchor_value <= len(text):
            raise SourceChunkIntegrityError("SourceChunk anchor range is outside the representation.")
        expected_text = text[chunk.start_anchor_value : chunk.end_anchor_value]
        if chunk.chunk_text != expected_text:
            raise SourceChunkIntegrityError("SourceChunk text disagrees with its representation slice.")
        expected_hash = hashlib.sha256(expected_text.encode("utf-8")).digest()
        if chunk.content_hash != expected_hash:
            raise SourceChunkIntegrityError("SourceChunk content hash verification failed.")
        return chunk


def _build_signature(
    *,
    representation_id: uuid.UUID,
    representation_hash: bytes,
    profile: ChunkingProfile,
) -> bytes:
    payload = {
        "pipeline_version": _PIPELINE_VERSION,
        "representation_id": str(representation_id),
        "representation_sha256": representation_hash.hex(),
        "chunking_profile_id": str(profile.chunking_profile_id),
        "configuration_hash": profile.configuration_hash.hex(),
    }
    canonical = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )
    return hashlib.sha256(canonical.encode("utf-8")).digest()


def _chunk_spans(
    text: str,
    *,
    target_size: int,
    units: tuple[tuple[int, int], ...] | None = None,
    preferred_boundaries: tuple[int, ...] = (),
) -> tuple[tuple[int, int], ...]:
    """Return contiguous exact-text spans, preferring supplied structure boundaries."""
    if target_size <= 0:
        raise ValueError("target_size must be positive.")
    if not text:
        return ()

    active_units = units if units is not None else _paragraph_units(text)
    spans: list[tuple[int, int]] = []
    current_start: int | None = None
    current_end: int | None = None

    for unit_start, unit_end in active_units:
        if unit_end - unit_start > target_size:
            if current_start is not None and current_end is not None:
                spans.append((current_start, current_end))
                current_start = current_end = None
            spans.extend(
                _split_long_span(
                    text,
                    unit_start,
                    unit_end,
                    target_size,
                    preferred_boundaries=preferred_boundaries,
                )
            )
            continue

        if current_start is None:
            current_start, current_end = unit_start, unit_end
            continue

        assert current_end is not None
        if unit_end - current_start <= target_size:
            current_end = unit_end
        else:
            spans.append((current_start, current_end))
            current_start, current_end = unit_start, unit_end

    if current_start is not None and current_end is not None:
        spans.append((current_start, current_end))

    if spans and spans[0][0] != 0:
        raise RuntimeError("Chunking failed to cover the representation from offset zero.")
    if spans and spans[-1][1] != len(text):
        raise RuntimeError("Chunking failed to cover the representation through EOF.")
    for left, right in zip(spans, spans[1:], strict=False):
        if left[1] != right[0]:
            raise RuntimeError("Chunking produced a gap or overlap in exact-text coverage.")
    return tuple(spans)


def _verify_structure_spans(
    text: str,
    structures: tuple[SourceRepresentationStructureRecord, ...],
) -> None:
    if tuple(item.structure_index for item in structures) != tuple(range(len(structures))):
        raise SourceChunkIntegrityError(
            "Retained document structure indexes are not contiguous from zero."
        )
    known_ids: set[uuid.UUID] = set()
    for item in structures:
        if item.parent_structure_id is not None and item.parent_structure_id not in known_ids:
            raise SourceChunkIntegrityError(
                "Retained document structure parent does not precede its child."
            )
        if not 0 <= item.start_offset <= item.end_offset <= len(text):
            raise SourceChunkIntegrityError(
                "Retained document structure range is outside the representation."
            )
        actual_hash = hashlib.sha256(
            text[item.start_offset : item.end_offset].encode("utf-8")
        ).digest()
        if actual_hash != item.content_hash:
            raise SourceChunkIntegrityError(
                "Retained document structure hash disagrees with its representation."
            )
        known_ids.add(item.structure_id)


def _document_structure_units(
    text: str,
    structures: tuple[SourceRepresentationStructureRecord, ...],
) -> tuple[tuple[tuple[int, int], ...], tuple[int, ...]]:
    top_level_starts = tuple(
        sorted(
            {
                item.start_offset
                for item in structures
                if item.parent_structure_id is None
            }
        )
    )
    if not top_level_starts or top_level_starts[0] != 0:
        raise SourceChunkIntegrityError(
            "Retained document structure does not cover the representation from offset zero."
        )
    unit_boundaries = (*top_level_starts, len(text))
    units = tuple(
        (start, end)
        for start, end in zip(unit_boundaries[:-1], unit_boundaries[1:], strict=True)
        if start < end
    )
    if not units or units[0][0] != 0 or units[-1][1] != len(text):
        raise SourceChunkIntegrityError(
            "Retained document structure does not provide contiguous top-level coverage."
        )
    structure_boundaries = tuple(
        sorted(
            {
                offset
                for item in structures
                for offset in (item.start_offset, item.end_offset)
                if 0 < offset < len(text)
            }
        )
    )
    return units, structure_boundaries


def _paragraph_units(text: str) -> tuple[tuple[int, int], ...]:
    units: list[tuple[int, int]] = []
    start = 0
    index = 0
    while index < len(text):
        if text[index] == "\n":
            run_end = index + 1
            while run_end < len(text) and text[run_end] == "\n":
                run_end += 1
            if run_end - index >= 2:
                units.append((start, run_end))
                start = run_end
            index = run_end
        else:
            index += 1
    if start < len(text):
        units.append((start, len(text)))
    if not units:
        units.append((0, len(text)))
    return tuple(units)


def _split_long_span(
    text: str,
    start: int,
    end: int,
    target_size: int,
    *,
    preferred_boundaries: tuple[int, ...] = (),
) -> list[tuple[int, int]]:
    result: list[tuple[int, int]] = []
    cursor = start
    while end - cursor > target_size:
        hard_end = cursor + target_size
        cut = _preferred_cut(
            text,
            cursor,
            hard_end,
            preferred_boundaries=preferred_boundaries,
        )
        if cut <= cursor:
            cut = hard_end
        result.append((cursor, cut))
        cursor = cut
    if cursor < end:
        result.append((cursor, end))
    return result


def _preferred_cut(
    text: str,
    start: int,
    hard_end: int,
    *,
    preferred_boundaries: tuple[int, ...] = (),
) -> int:
    if preferred_boundaries:
        boundary_index = bisect_right(preferred_boundaries, hard_end) - 1
        if boundary_index >= 0:
            boundary = preferred_boundaries[boundary_index]
            if boundary > start:
                return boundary
    for needle in ("\n", " ", "\t"):
        position = text.rfind(needle, start + 1, hard_end + 1)
        if position > start:
            return position + 1
    return hard_end
