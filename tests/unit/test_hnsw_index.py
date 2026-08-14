from __future__ import annotations

import json
import math
from pathlib import Path

from athena.retrieval.hnsw import HnswIndexStore


class FakeHnswBackend:
    def __init__(self, dimensions: int, path: Path | None) -> None:
        self._dimensions = dimensions
        self._vectors: dict[int, tuple[float, ...]] = {}
        if path is not None:
            payload = json.loads(path.read_text(encoding="utf-8"))
            self._dimensions = int(payload["dimensions"])
            self._vectors = {
                int(key): tuple(float(value) for value in vector)
                for key, vector in payload["vectors"].items()
            }

    @property
    def size(self) -> int:
        return len(self._vectors)

    @property
    def dimensions(self) -> int:
        return self._dimensions

    def add(self, key: int, vector) -> None:
        self._vectors[key] = tuple(float(value) for value in vector)

    def search(self, vector, limit: int) -> tuple[tuple[int, float], ...]:
        query = tuple(float(value) for value in vector)
        scored: list[tuple[int, float]] = []
        for key, candidate in self._vectors.items():
            similarity = math.fsum(
                left * right for left, right in zip(query, candidate, strict=True)
            )
            scored.append((key, 1.0 - similarity))
        scored.sort(key=lambda item: (item[1], item[0]))
        return tuple(scored[:limit])

    def save(self, path: Path) -> None:
        path.write_text(
            json.dumps(
                {
                    "dimensions": self._dimensions,
                    "vectors": self._vectors,
                },
                sort_keys=True,
            ),
            encoding="utf-8",
        )


def _factory(dimensions: int, path: Path | None) -> FakeHnswBackend:
    return FakeHnswBackend(dimensions, path)


def test_hnsw_sidecar_build_search_and_delete(tmp_path) -> None:
    store = HnswIndexStore(
        tmp_path / "hnsw",
        namespace="knowledge",
        reference_size=16,
        backend_factory=_factory,
    )
    refs = (bytes(range(16)), bytes(range(16, 32)))
    store.build(
        model_id="embed::profile",
        snapshot=7,
        dimensions=3,
        entries=(
            (refs[0], (1.0, 0.0, 0.0)),
            (refs[1], (0.0, 1.0, 0.0)),
        ),
    )

    assert store.ready(
        model_id="embed::profile",
        snapshot=7,
        dimensions=3,
        document_count=2,
    )
    matches = store.search(
        (1.0, 0.0, 0.0),
        model_id="embed::profile",
        snapshot=7,
        dimensions=3,
        document_count=2,
        limit=2,
    )
    assert tuple(item.reference for item in matches) == refs
    assert matches[0].similarity == 1.0

    assert store.delete(model_id="embed::profile") == 2
    assert not store.ready(
        model_id="embed::profile",
        snapshot=7,
        dimensions=3,
        document_count=2,
    )


def test_hnsw_rebuild_replaces_older_snapshot(tmp_path) -> None:
    store = HnswIndexStore(
        tmp_path / "hnsw",
        namespace="archive",
        reference_size=16,
        backend_factory=_factory,
    )
    reference = b"x" * 16
    store.build(
        model_id="embed",
        snapshot=3,
        dimensions=2,
        entries=((reference, (1.0, 0.0)),),
    )
    store.build(
        model_id="embed",
        snapshot=4,
        dimensions=2,
        entries=((reference, (0.0, 1.0)),),
    )

    assert not store.ready(
        model_id="embed",
        snapshot=3,
        dimensions=2,
        document_count=1,
    )
    assert store.ready(
        model_id="embed",
        snapshot=4,
        dimensions=2,
        document_count=1,
    )


def test_hnsw_ref_corruption_is_not_reported_ready(tmp_path) -> None:
    store = HnswIndexStore(
        tmp_path / "hnsw",
        namespace="knowledge",
        reference_size=16,
        backend_factory=_factory,
    )
    store.build(
        model_id="embed",
        snapshot=1,
        dimensions=2,
        entries=((b"a" * 16, (1.0, 0.0)),),
    )
    refs_path = next((tmp_path / "hnsw").glob("*.refs"))
    refs_path.write_bytes(b"broken")

    assert not store.ready(
        model_id="embed",
        snapshot=1,
        dimensions=2,
        document_count=1,
    )


def test_usearch_backend_converts_vectors_to_numpy_float32(monkeypatch) -> None:
    import types

    import numpy as np

    import athena.retrieval.hnsw as hnsw_module

    class FakeMatch:
        key = 7
        distance = 0.25

    class FakeIndex:
        def __init__(self, *, ndim: int, **_kwargs) -> None:
            self.ndim = ndim
            self._size = 0

        def __len__(self) -> int:
            return self._size

        def add(self, key: int, vector) -> None:
            assert key == 7
            assert isinstance(vector, np.ndarray)
            assert vector.dtype == np.float32
            self._size += 1

        def search(self, vector, limit: int):
            assert isinstance(vector, np.ndarray)
            assert vector.dtype == np.float32
            assert limit == 1
            return (FakeMatch(),)

        def save(self, _path: str) -> None:
            return None

    fake_module = types.SimpleNamespace(Index=FakeIndex)
    monkeypatch.setattr(
        hnsw_module.importlib,
        "import_module",
        lambda _name: fake_module,
    )

    backend = hnsw_module._USearchBackend(3, None)
    backend.add(7, (1.0, 0.0, 0.0))

    assert backend.search((1.0, 0.0, 0.0), 1) == ((7, 0.25),)


def test_usearch_backend_restores_without_memory_mapping(monkeypatch, tmp_path) -> None:
    import types

    import athena.retrieval.hnsw as hnsw_module

    index_path = tmp_path / "persisted.usearch"
    index_path.write_bytes(b"test")
    calls: list[tuple[str, bool]] = []

    class FakeRestoredIndex:
        ndim = 3

        def __len__(self) -> int:
            return 1

        def search(self, _vector, _limit: int):
            return ()

        def save(self, _path: str) -> None:
            return None

    class FakeIndex:
        @staticmethod
        def restore(path: str, *, view: bool):
            calls.append((path, view))
            return FakeRestoredIndex()

    fake_module = types.SimpleNamespace(Index=FakeIndex)
    monkeypatch.setattr(
        hnsw_module.importlib,
        "import_module",
        lambda _name: fake_module,
    )

    backend = hnsw_module._USearchBackend(3, index_path)

    assert backend.size == 1
    assert backend.dimensions == 3
    assert calls == [(str(index_path), False)]
