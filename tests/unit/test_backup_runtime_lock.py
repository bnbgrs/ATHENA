from __future__ import annotations

import subprocess
import sys
import time
import uuid
from pathlib import Path

import pytest

from athena.config.settings import AthenaSettings
from athena.core.application import AthenaApplication

_BACKUP_CHILD = r"""
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
    original_verify = (
        app.blob_store.verify_blob
    )

    blocked = False

    def blocking_verify_blob(
        *,
        storage_area,
        storage_locator,
        expected_sha256,
        expected_length,
        progress_callback=None,
    ):
        global blocked

        if (
            not blocked
            and storage_area
            is BlobStorageArea.SPOOL
        ):
            blocked = True

            ready.write_text(
                "backup-critical-section\n",
                encoding="ascii",
            )

            deadline = (
                time.monotonic()
                + 20.0
            )

            while not release.is_file():
                if (
                    time.monotonic()
                    >= deadline
                ):
                    raise RuntimeError(
                        "Timed out waiting "
                        "for backup release."
                    )

                time.sleep(0.05)

        return original_verify(
            storage_area=storage_area,
            storage_locator=storage_locator,
            expected_sha256=expected_sha256,
            expected_length=expected_length,
            progress_callback=progress_callback,
        )

    app.blob_store.verify_blob = (
        blocking_verify_blob
    )

    snapshot = (
        app.backup.create_snapshot(
            target_root=backup_root,
        )
    )

    print(
        f"SNAPSHOT_ID={snapshot.snapshot_id}",
        flush=True,
    )

finally:
    app.stop()
"""


_RUNTIME_LOCK_PROBE_CHILD = r"""
from __future__ import annotations

import sys
from pathlib import Path

from athena.lifecycle.runtime_lock import (
    runtime_data_lock,
)


state_root = Path(sys.argv[1])
acquired = Path(sys.argv[2])

with runtime_data_lock(
    state_root
):
    acquired.write_text(
        "acquired\n",
        encoding="ascii",
    )
"""


def _app(
    local_root: Path,
) -> AthenaApplication:
    app = AthenaApplication(
        settings=AthenaSettings(
            local_root=local_root,
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

    while (
        time.monotonic()
        < deadline
    ):
        if path.is_file():
            return

        if process.poll() is not None:
            stdout, stderr = (
                process.communicate()
            )

            pytest.fail(
                "Child exited before readiness.\n"
                f"stdout:\n{stdout}\n"
                f"stderr:\n{stderr}"
            )

        time.sleep(0.05)

    process.kill()

    stdout, stderr = (
        process.communicate()
    )

    pytest.fail(
        "Timed out waiting for child.\n"
        f"stdout:\n{stdout}\n"
        f"stderr:\n{stderr}"
    )


def _communicate(
    process: subprocess.Popen[str],
    *,
    timeout_seconds: float = 20.0,
) -> tuple[str, str]:
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
            "Child process timed out.\n"
            f"stdout:\n{stdout}\n"
            f"stderr:\n{stderr}"
        )

    assert process.returncode == 0, (
        f"Child failed with "
        f"{process.returncode}.\n"
        f"stdout:\n{stdout}\n"
        f"stderr:\n{stderr}"
    )

    return (
        stdout,
        stderr,
    )


def test_backup_snapshot_holds_runtime_data_lock_across_pin_window(
    tmp_path: Path,
) -> None:
    runtime = (
        tmp_path
        / "runtime"
    )

    backup_root = (
        tmp_path
        / "backup"
    )

    source_path = (
        tmp_path
        / "runtime-lock-source.txt"
    )

    backup_ready = (
        tmp_path
        / "backup-ready"
    )

    backup_release = (
        tmp_path
        / "backup-release"
    )

    probe_acquired = (
        tmp_path
        / "probe-acquired"
    )

    payload = (
        b"ATHENA_BACKUP_RUNTIME_LOCK_"
        b"REGRESSION_7F2E"
    )

    source_path.write_bytes(
        payload
    )

    app = _app(
        runtime
    )

    backup_process: (
        subprocess.Popen[str]
        | None
    ) = None

    probe_process: (
        subprocess.Popen[str]
        | None
    ) = None

    try:
        captured = (
            app.sources.capture_file(
                source_path
            )
        )

        assert (
            app.backup.runtime_lock_root
            == app.paths.state_root
        )

        old_blob_id = (
            captured.blob.blob_id
        )

        backup_process = (
            subprocess.Popen(
                [
                    sys.executable,
                    "-c",
                    _BACKUP_CHILD,
                    str(runtime),
                    str(backup_root),
                    str(backup_ready),
                    str(backup_release),
                ],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
        )

        _wait_for_file(
            backup_ready,
            process=backup_process,
        )

        # The backup child is now after the SQLite
        # snapshot and after pin creation, but before
        # physical Blob copying has completed.
        pin = (
            app.database.connection.execute(
                """
                SELECT snapshot_id
                FROM backup_snapshot_pins
                WHERE blob_id = ?
                """,
                (
                    old_blob_id.bytes,
                ),
            ).fetchone()
        )

        assert pin is not None

        snapshot_id = uuid.UUID(
            bytes=bytes(
                pin["snapshot_id"]
            )
        )

        # Any operation using the shared runtime data
        # lock -- including Source protection -- must
        # block until the backup critical section exits.
        probe_process = (
            subprocess.Popen(
                [
                    sys.executable,
                    "-c",
                    _RUNTIME_LOCK_PROBE_CHILD,
                    str(
                        app.paths.state_root
                    ),
                    str(
                        probe_acquired
                    ),
                ],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
        )

        # Give the probe enough time to start and try
        # the cross-process lock. It must still be
        # blocked while BackupService owns it.
        deadline = (
            time.monotonic()
            + 2.0
        )

        while (
            time.monotonic()
            < deadline
            and probe_process.poll()
            is None
            and not probe_acquired.exists()
        ):
            time.sleep(0.05)

        assert (
            probe_process.poll()
            is None
        )

        assert not (
            probe_acquired.exists()
        )

        backup_release.write_text(
            "release\n",
            encoding="ascii",
        )

        stdout, _stderr = (
            _communicate(
                backup_process
            )
        )

        backup_process = None

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

        assert (
            uuid.UUID(
                snapshot_lines[
                    0
                ].split(
                    "=",
                    1,
                )[1]
            )
            == snapshot_id
        )

        _wait_for_file(
            probe_acquired,
            process=probe_process,
        )

        _communicate(
            probe_process
        )

        probe_process = None

        assert (
            probe_acquired.read_text(
                encoding="ascii"
            )
            == "acquired\n"
        )

        snapshot = (
            app.backup.get_snapshot(
                snapshot_id
            )
        )

        assert (
            snapshot.state
            == "complete"
        )

        assert (
            app.database.connection.execute(
                """
                SELECT COUNT(*)
                FROM backup_snapshot_pins
                WHERE snapshot_id = ?
                """,
                (
                    snapshot_id.bytes,
                ),
            ).fetchone()[0]
            == 0
        )

    finally:
        backup_release.write_text(
            "release\n",
            encoding="ascii",
        )

        for process in (
            probe_process,
            backup_process,
        ):
            if process is None:
                continue

            try:
                process.communicate(
                    timeout=3.0
                )
            except subprocess.TimeoutExpired:
                process.kill()
                process.communicate()

        app.stop()
