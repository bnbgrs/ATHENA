from __future__ import annotations

import os
from pathlib import Path

import pytest

import athena.storage.durable_fs as durable_fs


def test_posix_replace_syncs_both_changed_parent_directories(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source_parent = tmp_path / "source"
    destination_parent = tmp_path / "destination"
    source_parent.mkdir()
    destination_parent.mkdir()

    source = source_parent / "payload.partial"
    destination = destination_parent / "payload.bin"
    source.write_bytes(b"durable payload")

    events: list[tuple[str, Path]] = []
    real_replace = os.replace

    def tracked_replace(
        old: str | bytes | os.PathLike[str] | os.PathLike[bytes],
        new: str | bytes | os.PathLike[str] | os.PathLike[bytes],
    ) -> None:
        events.append(
            ("replace", Path(old))
        )
        real_replace(
            old,
            new,
        )

    def tracked_fsync_directory(path: Path) -> None:
        events.append(
            ("fsync", Path(path))
        )

    monkeypatch.setattr(
        durable_fs,
        "_is_windows",
        lambda: False,
    )
    monkeypatch.setattr(
        durable_fs.os,
        "replace",
        tracked_replace,
    )
    monkeypatch.setattr(
        durable_fs,
        "fsync_directory",
        tracked_fsync_directory,
    )

    durable_fs.durable_replace(
        source,
        destination,
    )

    assert destination.read_bytes() == b"durable payload"
    assert not source.exists()

    assert events == [
        ("replace", source),
        ("fsync", destination_parent),
        ("fsync", source_parent),
    ]


def test_posix_same_directory_replace_syncs_parent_once(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "payload.partial"
    destination = tmp_path / "payload.bin"

    source.write_bytes(b"new")
    destination.write_bytes(b"old")

    synced: list[Path] = []
    real_replace = os.replace

    monkeypatch.setattr(
        durable_fs,
        "_is_windows",
        lambda: False,
    )
    monkeypatch.setattr(
        durable_fs.os,
        "replace",
        real_replace,
    )
    monkeypatch.setattr(
        durable_fs,
        "fsync_directory",
        lambda path: synced.append(Path(path)),
    )

    durable_fs.durable_replace(
        source,
        destination,
    )

    assert destination.read_bytes() == b"new"
    assert synced == [tmp_path]


def test_windows_route_uses_write_through_primitive(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "source.partial"
    destination = tmp_path / "destination.bin"

    called: list[tuple[Path, Path]] = []

    monkeypatch.setattr(
        durable_fs,
        "_is_windows",
        lambda: True,
    )
    monkeypatch.setattr(
        durable_fs,
        "_windows_replace_write_through",
        lambda old, new: called.append(
            (Path(old), Path(new))
        ),
    )

    def forbidden_replace(*args: object, **kwargs: object) -> None:
        raise AssertionError(
            "Windows durable publication must not fall back to os.replace."
        )

    monkeypatch.setattr(
        durable_fs.os,
        "replace",
        forbidden_replace,
    )

    durable_fs.durable_replace(
        source,
        destination,
    )

    assert called == [
        (source, destination)
    ]


@pytest.mark.skipif(
    os.name != "nt",
    reason="Windows MoveFileExW behavior",
)
def test_windows_write_through_replaces_existing_file(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source.partial"
    destination = tmp_path / "destination.bin"

    source.write_bytes(b"replacement")
    destination.write_bytes(b"old")

    durable_fs.durable_replace(
        source,
        destination,
    )

    assert not source.exists()
    assert destination.read_bytes() == b"replacement"


@pytest.mark.skipif(
    os.name != "nt",
    reason="Windows MoveFileExW directory behavior",
)
def test_windows_write_through_moves_directory(
    tmp_path: Path,
) -> None:
    source = tmp_path / "staging"
    destination = tmp_path / "published"

    source.mkdir()
    (source / "marker.txt").write_text(
        "durable directory",
        encoding="utf-8",
    )

    durable_fs.durable_replace(
        source,
        destination,
    )

    assert not source.exists()
    assert (
        destination
        / "marker.txt"
    ).read_text(
        encoding="utf-8"
    ) == "durable directory"



def test_posix_durable_mkdir_syncs_each_new_parent_entry(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target = tmp_path / "one" / "two" / "three"
    synced: list[Path] = []

    monkeypatch.setattr(
        durable_fs,
        "_is_windows",
        lambda: False,
    )
    monkeypatch.setattr(
        durable_fs,
        "fsync_directory",
        lambda path: synced.append(Path(path)),
    )

    durable_fs.durable_mkdir(
        target,
        parents=True,
        exist_ok=True,
    )

    assert target.is_dir()

    assert synced == [
        tmp_path,
        tmp_path / "one",
        tmp_path / "one" / "two",
    ]


def test_durable_mkdir_rejects_existing_non_directory(
    tmp_path: Path,
) -> None:
    target = tmp_path / "not-a-directory"

    target.write_text(
        "file",
        encoding="utf-8",
    )

    with pytest.raises(FileExistsError):
        durable_fs.durable_mkdir(
            target,
            parents=True,
            exist_ok=True,
        )


def test_windows_durable_mkdir_routes_new_levels_through_write_through_move(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target = tmp_path / "one" / "two"

    moved: list[
        tuple[Path, Path]
    ] = []

    def tracked_move(
        source: Path,
        destination: Path,
    ) -> None:
        moved.append(
            (
                Path(source),
                Path(destination),
            )
        )

        source.rename(
            destination
        )

    monkeypatch.setattr(
        durable_fs,
        "_is_windows",
        lambda: True,
    )

    monkeypatch.setattr(
        durable_fs,
        "_windows_replace_write_through",
        tracked_move,
    )

    durable_fs.durable_mkdir(
        target,
        parents=True,
        exist_ok=True,
    )

    assert target.is_dir()

    assert [
        destination
        for _, destination in moved
    ] == [
        tmp_path / "one",
        tmp_path / "one" / "two",
    ]


@pytest.mark.skipif(
    os.name != "nt",
    reason="Windows MoveFileExW durable directory creation",
)
def test_windows_durable_mkdir_creates_nested_tree(
    tmp_path: Path,
) -> None:
    target = (
        tmp_path
        / "first"
        / "second"
        / "third"
    )

    durable_fs.durable_mkdir(
        target,
        parents=True,
        exist_ok=True,
    )

    assert target.is_dir()

    durable_fs.durable_mkdir(
        target,
        parents=True,
        exist_ok=True,
    )

    assert target.is_dir()
