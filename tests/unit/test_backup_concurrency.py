from __future__ import annotations

import sqlite3
import subprocess
import sys
import time
import uuid
from pathlib import Path

import pytest

from athena.backup.target_lock import (
    BackupTargetBusyError,
    backup_target_lock,
)
from athena.config.settings import AthenaSettings
from athena.core.application import AthenaApplication
from athena.source.models import BlobStorageArea


def _app(
    local_root: Path,
    *,
    archive_root: Path | None = None,
) -> AthenaApplication:
    app = AthenaApplication(
        settings=AthenaSettings(
            local_root=local_root,
            archive_root=archive_root,
        )
    )

    app.start()
    return app


def _wait_for_file(
    path: Path,
    *,
    process: subprocess.Popen[str],
    timeout_seconds: float = 15.0,
) -> None:
    deadline = (
        time.monotonic()
        + timeout_seconds
    )

    while time.monotonic() < deadline:
        if path.is_file():
            return

        if process.poll() is not None:
            stdout, stderr = (
                process.communicate()
            )

            pytest.fail(
                "Child process exited before readiness.\n"
                f"stdout:\n{stdout}\n"
                f"stderr:\n{stderr}"
            )

        time.sleep(0.05)

    process.kill()

    stdout, stderr = (
        process.communicate()
    )

    pytest.fail(
        "Timed out waiting for child readiness.\n"
        f"stdout:\n{stdout}\n"
        f"stderr:\n{stderr}"
    )


def _finish_child(
    process: subprocess.Popen[str],
    *,
    release_path: Path,
    timeout_seconds: float = 20.0,
) -> tuple[str, str]:
    release_path.write_text(
        "release\n",
        encoding="ascii",
    )

    try:
        stdout, stderr = (
            process.communicate(
                timeout=timeout_seconds
            )
        )
    except subprocess.TimeoutExpired:
        process.kill()

        stdout, stderr = (
            process.communicate()
        )

        pytest.fail(
            "Child process did not terminate.\n"
            f"stdout:\n{stdout}\n"
            f"stderr:\n{stderr}"
        )

    assert process.returncode == 0, (
        f"Child failed with {process.returncode}.\n"
        f"stdout:\n{stdout}\n"
        f"stderr:\n{stderr}"
    )

    return stdout, stderr


_BACKUP_RACE_CHILD = r"""
from __future__ import annotations

import sys
import time
from pathlib import Path

from athena.config.settings import AthenaSettings
from athena.core.application import AthenaApplication
from athena.source.models import BlobStorageArea

runtime = Path(sys.argv[1])
backup_root = Path(sys.argv[2])
ready = Path(sys.argv[3])
release = Path(sys.argv[4])

app = AthenaApplication(
    settings=AthenaSettings(
        local_root=runtime,
    )
)

app.start()

try:
    original_verify = app.blob_store.verify_blob
    blocked_once = False

    def blocking_verify_blob(
        *,
        storage_area,
        storage_locator,
        expected_sha256,
        expected_length,
        progress_callback=None,
    ):
        global blocked_once

        if (
            not blocked_once
            and storage_area
            is BlobStorageArea.SPOOL
        ):
            blocked_once = True

            ready.write_text(
                "pins-committed\n",
                encoding="ascii",
            )

            deadline = (
                time.monotonic()
                + 20.0
            )

            while not release.is_file():
                if time.monotonic() >= deadline:
                    raise RuntimeError(
                        "Timed out waiting for race release."
                    )

                time.sleep(0.05)

        return original_verify(
            storage_area=storage_area,
            storage_locator=storage_locator,
            expected_sha256=expected_sha256,
            expected_length=expected_length,
            progress_callback=progress_callback,
        )

    app.blob_store.verify_blob = blocking_verify_blob

    snapshot = app.backup.create_snapshot(
        target_root=backup_root,
    )

    print(
        f"SNAPSHOT_ID={snapshot.snapshot_id}",
        flush=True,
    )

finally:
    app.stop()
"""


_LOCK_CHILD = r"""
from __future__ import annotations

import sys
import time
from pathlib import Path

from athena.backup.target_lock import backup_target_lock

target = Path(sys.argv[1])
ready = Path(sys.argv[2])
release = Path(sys.argv[3])

target.mkdir(
    parents=True,
    exist_ok=True,
)

with backup_target_lock(target):
    ready.write_text(
        "locked\n",
        encoding="ascii",
    )

    deadline = (
        time.monotonic()
        + 20.0
    )

    while not release.is_file():
        if time.monotonic() >= deadline:
            raise RuntimeError(
                "Timed out waiting for lock release."
            )

        time.sleep(0.05)
"""


def test_snapshot_pins_are_committed_before_blob_copy_and_released_after_completion(
    tmp_path: Path,
) -> None:
    runtime = tmp_path / "runtime"
    archive_root = tmp_path / "archive"
    backup_root = tmp_path / "backup"

    ready = tmp_path / "backup-ready"
    release = tmp_path / "backup-release"

    original = (
        tmp_path
        / "pin-window.bin"
    )

    payload = (
        b"SLICE14E_PIN_WINDOW_"
        b"7D51CBAA"
    )

    original.write_bytes(
        payload
    )

    app = _app(
        runtime,
        archive_root=archive_root,
    )

    process: (
        subprocess.Popen[str]
        | None
    ) = None

    try:
        captured = (
            app.sources.capture_file(
                original
            )
        )

        source_id = (
            captured.source.source_id
        )

        blob_id = (
            captured.blob.blob_id
        )

        assert (
            captured.blob.storage_area
            is BlobStorageArea.SPOOL
        )

        spool_path = (
            app.blob_store.resolve_blob_path(
                storage_area=(
                    BlobStorageArea.SPOOL
                ),
                storage_locator=(
                    captured.blob.storage_locator
                ),
            )
        )

        assert (
            spool_path.read_bytes()
            == payload
        )

        process = subprocess.Popen(
            [
                sys.executable,
                "-c",
                _BACKUP_RACE_CHILD,
                str(runtime),
                str(backup_root),
                str(ready),
                str(release),
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )

        _wait_for_file(
            ready,
            process=process,
        )

        # READY is emitted from Blob verification.
        # Therefore the SQLite snapshot already exists
        # and its Blob pin must already be durable.
        pin_row = (
            app.database.connection.execute(
                """
                SELECT snapshot_id
                FROM backup_snapshot_pins
                WHERE blob_id = ?
                """,
                (
                    blob_id.bytes,
                ),
            ).fetchone()
        )

        assert pin_row is not None

        pinned_snapshot_id = (
            uuid.UUID(
                bytes=bytes(
                    pin_row[
                        "snapshot_id"
                    ]
                )
            )
        )

        snapshot_state = (
            app.database.connection.execute(
                """
                SELECT state
                FROM backup_snapshots
                WHERE snapshot_id = ?
                """,
                (
                    pinned_snapshot_id.bytes,
                ),
            ).fetchone()
        )

        assert snapshot_state is not None
        assert (
            snapshot_state["state"]
            == "creating"
        )

        # The live source remains unchanged while the
        # backup owns the runtime mutation lock.
        source_row = (
            app.database.connection.execute(
                """
                SELECT blob_id
                FROM sources
                WHERE source_id = ?
                """,
                (
                    source_id.bytes,
                ),
            ).fetchone()
        )

        assert source_row is not None

        assert (
            bytes(
                source_row["blob_id"]
            )
            == blob_id.bytes
        )

        assert spool_path.is_file()

        assert (
            spool_path.read_bytes()
            == payload
        )

        release.write_text(
            "release\n",
            encoding="ascii",
        )

        stdout, _stderr = (
            _finish_child(
                process,
                release_path=release,
            )
        )

        process = None

        snapshot_lines = [
            line
            for line
            in stdout.splitlines()
            if line.startswith(
                "SNAPSHOT_ID="
            )
        ]

        assert len(
            snapshot_lines
        ) == 1

        completed_snapshot_id = (
            uuid.UUID(
                snapshot_lines[
                    0
                ].split(
                    "=",
                    1,
                )[1]
            )
        )

        assert (
            completed_snapshot_id
            == pinned_snapshot_id
        )

        completed = (
            app.backup.get_snapshot(
                completed_snapshot_id
            )
        )

        assert (
            completed.state
            == "complete"
        )

        # Pins protect only the in-progress backup.
        # Completion releases them.
        assert (
            app.database.connection.execute(
                """
                SELECT 1
                FROM backup_snapshot_pins
                WHERE snapshot_id = ?
                """,
                (
                    completed_snapshot_id.bytes,
                ),
            ).fetchone()
            is None
        )

        verified = (
            app.backup.verify_deep(
                completed_snapshot_id
            )
        )

        assert (
            verified.verification_status
            == "verified_deep"
        )

        restored_root = (
            tmp_path
            / "restored"
        )

        app.backup.restore_to(
            completed_snapshot_id,
            destination_root=(
                restored_root
            ),
        )

        restored_db = (
            sqlite3.connect(
                restored_root
                / "state"
                / "athena.db"
            )
        )

        restored_db.row_factory = (
            sqlite3.Row
        )

        try:
            restored_source = (
                restored_db.execute(
                    """
                    SELECT blob_id
                    FROM sources
                    WHERE source_id = ?
                    """,
                    (
                        source_id.bytes,
                    ),
                ).fetchone()
            )

            assert (
                restored_source
                is not None
            )

            restored_blob = (
                restored_db.execute(
                    """
                    SELECT
                        storage_area,
                        storage_locator
                    FROM blob_records
                    WHERE blob_id = ?
                    """,
                    (
                        bytes(
                            restored_source[
                                "blob_id"
                            ]
                        ),
                    ),
                ).fetchone()
            )

            assert (
                restored_blob
                is not None
            )

            assert (
                restored_blob[
                    "storage_area"
                ]
                == "spool"
            )

            restored_path = (
                restored_root
                / "state"
                / "spool"
                / str(
                    restored_blob[
                        "storage_locator"
                    ]
                )
            )

            assert (
                restored_path.read_bytes()
                == payload
            )

        finally:
            restored_db.close()

    finally:
        if process is not None:
            release.write_text(
                "release\n",
                encoding="ascii",
            )

            try:
                process.communicate(
                    timeout=5
                )

            except subprocess.TimeoutExpired:
                process.kill()
                process.communicate()

        app.stop()




def test_backup_target_lock_is_cross_process_and_released_after_process_exit(
    tmp_path: Path,
) -> None:
    target = (
        tmp_path
        / "backup-target"
    )

    ready = (
        tmp_path
        / "lock-ready"
    )

    release = (
        tmp_path
        / "lock-release"
    )

    process = subprocess.Popen(
        [
            sys.executable,
            "-c",
            _LOCK_CHILD,
            str(target),
            str(ready),
            str(release),
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )

    try:
        _wait_for_file(
            ready,
            process=process,
        )

        with pytest.raises(
            BackupTargetBusyError
        ):
            with backup_target_lock(
                target
            ):
                pass

        _finish_child(
            process,
            release_path=release,
        )

        # OS lock ownership disappears with the child process.
        with backup_target_lock(
            target
        ):
            pass

    finally:
        if process.poll() is None:
            release.write_text(
                "release\n",
                encoding="ascii",
            )

            try:
                process.communicate(
                    timeout=5
                )
            except subprocess.TimeoutExpired:
                process.kill()
                process.communicate()
