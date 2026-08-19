from __future__ import annotations

import os
import shutil
from pathlib import Path

import pytest

from athena.common.time import utc_now_us
from athena.config.settings import AthenaSettings
from athena.core.application import AthenaApplication
from athena.source.blob_store import (
    ORPHAN_BLOB_SAFETY_HORIZON_US,
)
from athena.source.models import BlobStorageArea


def _app(
    tmp_path: Path,
    *,
    archive_root: Path | None = None,
    startup_maintenance: bool = False,
) -> AthenaApplication:
    app = AthenaApplication(
        settings=AthenaSettings(
            local_root=tmp_path / "runtime",
            archive_root=archive_root,
        )
    )
    app.start(
        run_startup_maintenance=startup_maintenance
    )
    return app


def _age_before_horizon(
    path: Path,
    *,
    now_us: int,
) -> None:
    old_us = (
        now_us
        - ORPHAN_BLOB_SAFETY_HORIZON_US
        - 5_000_000
    )
    old_ns = max(1, old_us * 1_000)
    os.utime(
        path,
        ns=(old_ns, old_ns),
    )


@pytest.mark.parametrize(
    "use_archive",
    [False, True],
)
def test_reconciliation_deletes_old_unreferenced_blob_publication(
    tmp_path: Path,
    use_archive: bool,
) -> None:
    archive_root = (
        tmp_path / "archive"
        if use_archive
        else None
    )
    if archive_root is not None:
        archive_root.mkdir()

    app = _app(
        tmp_path,
        archive_root=archive_root,
    )

    try:
        source_file = tmp_path / "orphan.bin"
        source_file.write_bytes(
            b"A-07 orphan publication"
        )

        prepared = app.blob_store.capture_file(
            source_file
        )
        orphan_path = app.blob_store.resolve_blob_path(
            storage_area=prepared.storage_area,
            storage_locator=prepared.storage_locator,
        )

        assert orphan_path.is_file()
        assert (
            app.database.connection.execute(
                "SELECT COUNT(*) FROM blob_records"
            ).fetchone()[0]
            == 0
        )

        now_us = utc_now_us()
        _age_before_horizon(
            orphan_path,
            now_us=now_us,
        )

        result = app.sources.reconcile_orphaned_blobs(
            now_us=now_us
        )

        assert result.deleted_orphan_count == 1
        assert result.unsafe_candidate_count == 0
        assert not orphan_path.exists()
    finally:
        app.stop()


def test_reconciliation_preserves_recent_unreferenced_publication(
    tmp_path: Path,
) -> None:
    app = _app(tmp_path)

    try:
        source_file = tmp_path / "recent.bin"
        source_file.write_bytes(
            b"A-07 recent orphan publication"
        )

        prepared = app.blob_store.capture_file(
            source_file
        )
        path = app.blob_store.resolve_blob_path(
            storage_area=prepared.storage_area,
            storage_locator=prepared.storage_locator,
        )

        result = app.sources.reconcile_orphaned_blobs(
            now_us=utc_now_us()
        )

        assert result.deleted_orphan_count == 0
        assert result.recent_unreferenced_count == 1
        assert path.is_file()
    finally:
        app.stop()


def test_reconciliation_preserves_referenced_locator_in_both_roots(
    tmp_path: Path,
) -> None:
    archive_root = tmp_path / "archive"
    archive_root.mkdir()
    app = _app(
        tmp_path,
        archive_root=archive_root,
    )

    try:
        source_file = tmp_path / "referenced.bin"
        source_file.write_bytes(
            b"A-07 referenced transfer replica"
        )

        captured = app.sources.capture_file(
            source_file
        )
        assert (
            captured.blob.storage_area
            is BlobStorageArea.ARCHIVE
        )

        archive_path = app.blob_store.resolve_blob_path(
            storage_area=BlobStorageArea.ARCHIVE,
            storage_locator=captured.blob.storage_locator,
        )
        spool_path = app.blob_store.resolve_blob_path(
            storage_area=BlobStorageArea.SPOOL,
            storage_locator=captured.blob.storage_locator,
        )
        spool_path.parent.mkdir(
            parents=True,
            exist_ok=True,
        )
        shutil.copy2(
            archive_path,
            spool_path,
        )

        now_us = utc_now_us()
        _age_before_horizon(
            archive_path,
            now_us=now_us,
        )
        _age_before_horizon(
            spool_path,
            now_us=now_us,
        )

        result = app.sources.reconcile_orphaned_blobs(
            now_us=now_us
        )

        assert result.deleted_orphan_count == 0
        assert result.referenced_blob_count == 2
        assert archive_path.is_file()
        assert spool_path.is_file()
    finally:
        app.stop()


def test_reconciliation_fails_closed_for_corrupt_orphan_candidate(
    tmp_path: Path,
) -> None:
    app = _app(tmp_path)

    try:
        source_file = tmp_path / "corrupt.bin"
        source_file.write_bytes(
            b"A-07 correct orphan bytes"
        )

        prepared = app.blob_store.capture_file(
            source_file
        )
        path = app.blob_store.resolve_blob_path(
            storage_area=prepared.storage_area,
            storage_locator=prepared.storage_locator,
        )
        path.write_bytes(
            b"A-07 corrupted after publication"
        )

        now_us = utc_now_us()
        _age_before_horizon(
            path,
            now_us=now_us,
        )

        result = app.sources.reconcile_orphaned_blobs(
            now_us=now_us
        )

        assert result.deleted_orphan_count == 0
        assert result.unsafe_candidate_count == 1
        assert path.is_file()
    finally:
        app.stop()


def test_offline_archive_does_not_block_spool_orphan_recovery(
    tmp_path: Path,
) -> None:
    archive_root = tmp_path / "offline-archive"
    app = _app(
        tmp_path,
        archive_root=archive_root,
    )

    try:
        source_file = tmp_path / "offline.bin"
        source_file.write_bytes(
            b"A-07 offline archive fallback"
        )

        prepared = app.blob_store.capture_file(
            source_file
        )
        assert (
            prepared.storage_area
            is BlobStorageArea.SPOOL
        )

        path = app.blob_store.resolve_blob_path(
            storage_area=prepared.storage_area,
            storage_locator=prepared.storage_locator,
        )

        now_us = utc_now_us()
        _age_before_horizon(
            path,
            now_us=now_us,
        )

        result = app.sources.reconcile_orphaned_blobs(
            now_us=now_us
        )

        assert result.archive_root_unavailable
        assert result.deleted_orphan_count == 1
        assert not path.exists()
    finally:
        app.stop()


def test_startup_maintenance_recovers_old_crash_window_orphan(
    tmp_path: Path,
) -> None:
    first = _app(tmp_path)

    source_file = tmp_path / "startup.bin"
    source_file.write_bytes(
        b"A-07 interrupted capture publication"
    )

    prepared = first.blob_store.capture_file(
        source_file
    )
    orphan_path = first.blob_store.resolve_blob_path(
        storage_area=prepared.storage_area,
        storage_locator=prepared.storage_locator,
    )

    now_us = utc_now_us()
    _age_before_horizon(
        orphan_path,
        now_us=now_us,
    )
    first.stop()

    assert orphan_path.is_file()

    second = _app(
        tmp_path,
        startup_maintenance=True,
    )
    try:
        assert not orphan_path.exists()
        assert (
            second.database.connection.execute(
                "SELECT COUNT(*) FROM blob_records"
            ).fetchone()[0]
            == 0
        )
    finally:
        second.stop()
