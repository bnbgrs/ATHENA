from __future__ import annotations

import json
import logging
from pathlib import Path

import pytest

from athena.backup.service import BackupRestoreError
from athena.config.settings import AthenaSettings
from athena.core.application import AthenaApplication


def _app(
    tmp_path: Path,
) -> AthenaApplication:
    app = AthenaApplication(
        settings=AthenaSettings(
            local_root=(
                tmp_path
                / "runtime"
            ),
        )
    )

    app.start()
    return app


def _snapshot_with_source(
    app: AthenaApplication,
    tmp_path: Path,
):
    source_path = (
        tmp_path
        / "source.txt"
    )

    source_path.write_text(
        "backup verification evidence",
        encoding="utf-8",
    )

    app.sources.capture_file(
        source_path
    )

    target = (
        tmp_path
        / "backup"
    )

    snapshot = (
        app.backup.create_snapshot(
            target_root=target,
        )
    )

    manifest_path = (
        target
        / snapshot.relative_path
        / "manifest.json"
    )

    manifest = json.loads(
        manifest_path.read_text(
            encoding="utf-8"
        )
    )

    return (
        target,
        snapshot,
        manifest,
    )


def test_light_verification_persists_timestamp_and_audit_event(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    app = _app(
        tmp_path
    )

    try:
        (
            _target,
            snapshot,
            _manifest,
        ) = _snapshot_with_source(
            app,
            tmp_path,
        )

        caplog.set_level(
            logging.INFO,
            logger=(
                "athena.backup.service"
            ),
        )

        verified = (
            app.backup.verify_light(
                snapshot.snapshot_id
            )
        )

        assert (
            verified.verification_status
            == "verified_light"
        )

        row = (
            app.database.connection.execute(
                """
                SELECT last_verified_at_us
                FROM backup_snapshots
                WHERE snapshot_id = ?
                """,
                (
                    snapshot.snapshot_id.bytes,
                ),
            ).fetchone()
        )

        assert row is not None
        assert row[0] is not None

        assert any(
            getattr(
                record,
                "event",
                None,
            )
            == (
                "backup."
                "verification_light_completed"
            )
            for record in caplog.records
        )

    finally:
        app.stop()


def test_light_rejects_missing_backup_object_and_marks_snapshot_failed(
    tmp_path: Path,
) -> None:
    app = _app(
        tmp_path
    )

    try:
        (
            target,
            snapshot,
            manifest,
        ) = _snapshot_with_source(
            app,
            tmp_path,
        )

        object_path = (
            target
            / manifest[
                "objects"
            ][0]["object_path"]
        )

        object_path.unlink()

        with pytest.raises(
            BackupRestoreError,
            match="Light verification",
        ):
            app.backup.verify_light(
                snapshot.snapshot_id
            )

        row = (
            app.database.connection.execute(
                """
                SELECT
                    verification_status,
                    last_verified_at_us
                FROM backup_snapshots
                WHERE snapshot_id = ?
                """,
                (
                    snapshot.snapshot_id.bytes,
                ),
            ).fetchone()
        )

        assert row is not None

        assert (
            row[
                "verification_status"
            ]
            == "failed"
        )

        assert (
            row[
                "last_verified_at_us"
            ]
            is not None
        )

    finally:
        app.stop()


def test_deep_detects_same_length_object_corruption_that_light_cannot_hash(
    tmp_path: Path,
) -> None:
    app = _app(
        tmp_path
    )

    try:
        (
            target,
            snapshot,
            manifest,
        ) = _snapshot_with_source(
            app,
            tmp_path,
        )

        object_path = (
            target
            / manifest[
                "objects"
            ][0]["object_path"]
        )

        original = (
            object_path.read_bytes()
        )

        assert original

        corrupted = bytearray(
            original
        )

        corrupted[0] ^= 0x01

        object_path.write_bytes(
            bytes(corrupted)
        )

        assert (
            object_path.stat().st_size
            == len(original)
        )

        light = (
            app.backup.verify_light(
                snapshot.snapshot_id
            )
        )

        assert (
            light.verification_status
            == "verified_light"
        )

        with pytest.raises(
            BackupRestoreError,
            match="Deep verification",
        ):
            app.backup.verify_deep(
                snapshot.snapshot_id
            )

        row = (
            app.database.connection.execute(
                """
                SELECT
                    verification_status,
                    last_verified_at_us
                FROM backup_snapshots
                WHERE snapshot_id = ?
                """,
                (
                    snapshot.snapshot_id.bytes,
                ),
            ).fetchone()
        )

        assert row is not None

        assert (
            row[
                "verification_status"
            ]
            == "failed"
        )

        assert (
            row[
                "last_verified_at_us"
            ]
            is not None
        )

    finally:
        app.stop()


def test_deep_verification_performs_isolated_restore_smoke(
    tmp_path: Path,
) -> None:
    app = _app(
        tmp_path
    )

    try:
        (
            _target,
            snapshot,
            _manifest,
        ) = _snapshot_with_source(
            app,
            tmp_path,
        )

        verified = (
            app.backup.verify_deep(
                snapshot.snapshot_id
            )
        )

        assert (
            verified.verification_status
            == "verified_deep"
        )

        row = (
            app.database.connection.execute(
                """
                SELECT last_verified_at_us
                FROM backup_snapshots
                WHERE snapshot_id = ?
                """,
                (
                    snapshot.snapshot_id.bytes,
                ),
            ).fetchone()
        )

        assert row is not None
        assert row[0] is not None

        leftovers = tuple(
            app.paths.local_root.parent.glob(
                "athena-backup-deep-verify-*"
            )
        )

        assert leftovers == ()

    finally:
        app.stop()


def test_light_verification_never_downgrades_deep_status(
    tmp_path: Path,
) -> None:
    app = _app(
        tmp_path
    )

    try:
        (
            _target,
            snapshot,
            _manifest,
        ) = _snapshot_with_source(
            app,
            tmp_path,
        )

        deep = (
            app.backup.verify_deep(
                snapshot.snapshot_id
            )
        )

        assert (
            deep.verification_status
            == "verified_deep"
        )

        light = (
            app.backup.verify_light(
                snapshot.snapshot_id
            )
        )

        assert (
            light.verification_status
            == "verified_deep"
        )

    finally:
        app.stop()
