"""Persistent reconstructible HNSW sidecars for semantic candidate search."""

from __future__ import annotations

import hashlib
import importlib
import os
import uuid
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

import numpy as np

_HNSW_FORMAT_VERSION = 1
_DEFAULT_CONNECTIVITY = 16
_DEFAULT_EXPANSION_ADD = 128
_DEFAULT_EXPANSION_SEARCH = 64


class HnswIndexError(RuntimeError):
    """Raised when a reconstructible HNSW sidecar cannot be used safely."""


@dataclass(frozen=True, slots=True)
class HnswMatch:
    reference: bytes
    similarity: float


class _HnswBackend(Protocol):
    @property
    def size(self) -> int: ...

    @property
    def dimensions(self) -> int: ...

    def add(self, key: int, vector: Sequence[float]) -> None: ...

    def search(self, vector: Sequence[float], limit: int) -> tuple[tuple[int, float], ...]: ...

    def save(self, path: Path) -> None: ...


BackendFactory = Callable[[int, Path | None], _HnswBackend]


class HnswIndexStore:
    """Own one model/snapshot-scoped USearch HNSW index plus fixed-size refs."""

    def __init__(
        self,
        root: Path,
        *,
        namespace: str,
        reference_size: int,
        backend_factory: BackendFactory | None = None,
    ) -> None:
        normalized_namespace = namespace.strip()
        if not normalized_namespace or not normalized_namespace.replace("-", "").isalnum():
            raise ValueError("HNSW namespace must be a simple non-empty identifier.")
        if reference_size <= 0:
            raise ValueError("HNSW reference size must be positive.")
        self.root = root
        self.namespace = normalized_namespace
        self.reference_size = reference_size
        self._backend_factory = backend_factory or _usearch_backend_factory

    def ready(
        self,
        *,
        model_id: str,
        snapshot: int,
        dimensions: int,
        document_count: int,
    ) -> bool:
        if snapshot < 0 or dimensions <= 0 or document_count < 0:
            return False
        if document_count == 0:
            return True
        index_path, refs_path = self._paths(model_id=model_id, snapshot=snapshot)
        if not index_path.is_file() or not refs_path.is_file():
            return False
        try:
            if refs_path.stat().st_size != document_count * self.reference_size:
                return False
            backend = self._backend_factory(dimensions, index_path)
            return backend.size == document_count and backend.dimensions == dimensions
        except (OSError, RuntimeError, ValueError, ImportError):
            return False

    def build(
        self,
        *,
        model_id: str,
        snapshot: int,
        dimensions: int,
        entries: Sequence[tuple[bytes, Sequence[float]]],
    ) -> tuple[Path, Path] | None:
        if snapshot < 0:
            raise HnswIndexError("HNSW snapshot must not be negative.")
        if dimensions <= 0:
            raise HnswIndexError("HNSW dimensions must be positive.")
        if not entries:
            self._remove_model_files(model_id=model_id, keep_snapshot=None)
            return None

        backend = self._backend_factory(dimensions, None)
        references = bytearray()
        for key, (reference, vector) in enumerate(entries, start=1):
            if len(reference) != self.reference_size:
                raise HnswIndexError("HNSW reference has an invalid fixed size.")
            if len(vector) != dimensions:
                raise HnswIndexError("HNSW vector dimensions are inconsistent.")
            backend.add(key, vector)
            references.extend(reference)

        if backend.size != len(entries) or backend.dimensions != dimensions:
            raise HnswIndexError("HNSW backend did not retain the complete index.")

        self.root.mkdir(parents=True, exist_ok=True)
        index_path, refs_path = self._paths(model_id=model_id, snapshot=snapshot)
        suffix = uuid.uuid4().hex
        index_temp = index_path.with_name(f".{index_path.name}.{suffix}.tmp")
        refs_temp = refs_path.with_name(f".{refs_path.name}.{suffix}.tmp")
        try:
            backend.save(index_temp)
            with refs_temp.open("wb") as handle:
                handle.write(references)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(refs_temp, refs_path)
            os.replace(index_temp, index_path)
        finally:
            index_temp.unlink(missing_ok=True)
            refs_temp.unlink(missing_ok=True)

        self._remove_model_files(model_id=model_id, keep_snapshot=snapshot)
        if not self.ready(
            model_id=model_id,
            snapshot=snapshot,
            dimensions=dimensions,
            document_count=len(entries),
        ):
            raise HnswIndexError("Published HNSW sidecar failed validation.")
        return index_path, refs_path

    def search(
        self,
        query_vector: Sequence[float],
        *,
        model_id: str,
        snapshot: int,
        dimensions: int,
        document_count: int,
        limit: int,
    ) -> tuple[HnswMatch, ...]:
        if not 1 <= limit:
            raise HnswIndexError("HNSW search limit must be positive.")
        if document_count == 0:
            return ()
        if len(query_vector) != dimensions:
            raise HnswIndexError("HNSW query dimensions differ from the index.")
        if not self.ready(
            model_id=model_id,
            snapshot=snapshot,
            dimensions=dimensions,
            document_count=document_count,
        ):
            raise HnswIndexError("HNSW sidecar is missing, stale, or invalid.")

        index_path, refs_path = self._paths(model_id=model_id, snapshot=snapshot)
        backend = self._backend_factory(dimensions, index_path)
        raw_matches = backend.search(query_vector, min(limit, document_count))
        matches: list[HnswMatch] = []
        with refs_path.open("rb") as references:
            for key, distance in raw_matches:
                if not 1 <= key <= document_count:
                    raise HnswIndexError("HNSW returned an out-of-range reference key.")
                references.seek((key - 1) * self.reference_size)
                reference = references.read(self.reference_size)
                if len(reference) != self.reference_size:
                    raise HnswIndexError("HNSW reference sidecar is truncated.")
                similarity = max(-1.0, min(1.0, 1.0 - distance))
                matches.append(HnswMatch(reference=reference, similarity=similarity))
        return tuple(matches)

    def delete(self, *, model_id: str) -> int:
        """Delete only reconstructible HNSW sidecars for one embedding space."""
        return self._remove_model_files(model_id=model_id, keep_snapshot=None)

    def _paths(self, *, model_id: str, snapshot: int) -> tuple[Path, Path]:
        normalized_model_id = model_id.strip()
        if not normalized_model_id:
            raise HnswIndexError("HNSW model id must not be empty.")
        digest = hashlib.sha256(normalized_model_id.encode("utf-8")).hexdigest()[:24]
        stem = (
            f"v{_HNSW_FORMAT_VERSION}-{self.namespace}-{digest}-snapshot-{snapshot}"
        )
        return self.root / f"{stem}.usearch", self.root / f"{stem}.refs"

    def _remove_model_files(self, *, model_id: str, keep_snapshot: int | None) -> int:
        normalized_model_id = model_id.strip()
        if not normalized_model_id:
            raise HnswIndexError("HNSW model id must not be empty.")
        if not self.root.exists():
            return 0
        digest = hashlib.sha256(normalized_model_id.encode("utf-8")).hexdigest()[:24]
        prefix = f"v{_HNSW_FORMAT_VERSION}-{self.namespace}-{digest}-snapshot-"
        keep_names: set[str] = set()
        if keep_snapshot is not None:
            index_path, refs_path = self._paths(
                model_id=normalized_model_id,
                snapshot=keep_snapshot,
            )
            keep_names = {index_path.name, refs_path.name}
        removed = 0
        for path in self.root.iterdir():
            if path.name.startswith(prefix) and path.name not in keep_names:
                path.unlink(missing_ok=True)
                removed += 1
        return removed


class _USearchBackend:
    def __init__(self, dimensions: int, path: Path | None) -> None:
        try:
            module = importlib.import_module("usearch.index")
            index_type = module.__dict__.get("Index")
            if index_type is None:
                raise AttributeError("usearch.index.Index is unavailable")
        except (ImportError, AttributeError) as exc:
            raise HnswIndexError(
                "USearch is required for ATHENA HNSW retrieval. "
                "Install the pinned project dependencies."
            ) from exc
        if path is None:
            self._index = index_type(
                ndim=dimensions,
                metric="cos",
                dtype="f32",
                connectivity=_DEFAULT_CONNECTIVITY,
                expansion_add=_DEFAULT_EXPANSION_ADD,
                expansion_search=_DEFAULT_EXPANSION_SEARCH,
            )
        else:
            restored = index_type.restore(str(path), view=False)
            if restored is None:
                raise HnswIndexError("USearch did not restore the persisted HNSW index.")
            self._index = restored

    @property
    def size(self) -> int:
        return int(len(self._index))

    @property
    def dimensions(self) -> int:
        return int(self._index.ndim)

    def add(self, key: int, vector: Sequence[float]) -> None:
        packed = np.asarray(vector, dtype=np.float32)
        self._index.add(key, packed)

    def search(self, vector: Sequence[float], limit: int) -> tuple[tuple[int, float], ...]:
        packed = np.asarray(vector, dtype=np.float32)
        matches = self._index.search(packed, limit)
        return tuple((int(match.key), float(match.distance)) for match in matches)

    def save(self, path: Path) -> None:
        self._index.save(str(path))


def _usearch_backend_factory(dimensions: int, path: Path | None) -> _HnswBackend:
    return _USearchBackend(dimensions, path)
