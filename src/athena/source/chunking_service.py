"""Deterministic SourceChunk generation from retained text representations."""

from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import dataclass

from athena.chat.service import ChatService
from athena.common.ids import new_uuid7
from athena.common.time import utc_now_us
from athena.model.provenance import ModelRunRepository, ProcessingRun
from athena.source.chunk_store import SourceChunkRecord, SourceChunkStore
from athena.source.chunking_repository import ChunkingProfile, ChunkingProfileRepository
from athena.source.models import SourceRepresentationType
from athena.source.representation_service import SourceTextRepresentationService

_PIPELINE_VERSION = "source-chunking-v1"


class SourceChunkIntegrityError(RuntimeError):
    """Raised when a derived chunk no longer matches its retained representation."""


@dataclass(frozen=True, slots=True)
class SourceChunkBuildResult:
    profile: ChunkingProfile
    processing_run: ProcessingRun
    build_signature: bytes
    chunks: tuple[SourceChunkRecord, ...]


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
        profile = self.profiles.get_or_create_default()
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
                    error_detail=f"{type(exc).__name__}: {exc}",
                )
            raise

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


def _chunk_spans(text: str, *, target_size: int) -> tuple[tuple[int, int], ...]:
    """Return contiguous exact-text spans, preferring paragraph/line/space boundaries."""
    if target_size <= 0:
        raise ValueError("target_size must be positive.")
    if not text:
        return ()

    units = _paragraph_units(text)
    spans: list[tuple[int, int]] = []
    current_start: int | None = None
    current_end: int | None = None

    for unit_start, unit_end in units:
        if unit_end - unit_start > target_size:
            if current_start is not None and current_end is not None:
                spans.append((current_start, current_end))
                current_start = current_end = None
            spans.extend(_split_long_span(text, unit_start, unit_end, target_size))
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
) -> list[tuple[int, int]]:
    result: list[tuple[int, int]] = []
    cursor = start
    while end - cursor > target_size:
        hard_end = cursor + target_size
        cut = _preferred_cut(text, cursor, hard_end)
        if cut <= cursor:
            cut = hard_end
        result.append((cursor, cut))
        cursor = cut
    if cursor < end:
        result.append((cursor, end))
    return result


def _preferred_cut(text: str, start: int, hard_end: int) -> int:
    for needle in ("\n", " ", "\t"):
        position = text.rfind(needle, start + 1, hard_end + 1)
        if position > start:
            return position + 1
    return hard_end
