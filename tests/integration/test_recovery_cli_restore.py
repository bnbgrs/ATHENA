from __future__ import annotations

import os
import sqlite3
import subprocess
import sys
from pathlib import Path

from athena.config.settings import AthenaSettings
from athena.core.application import AthenaApplication


def _create_completed_backup(
    tmp_path: Path,
) -> tuple[Path, Path, bytes]:
    runtime = tmp_path / "live-runtime"
    backup_root = tmp_path / "backup-medium"

    app = AthenaApplication(
        settings=AthenaSettings(
            local_root=runtime,
        )
    )
    app.start()

    try:
        chat_id = app.chat.create_chat()
        app.chat.add_user_message(
            chat_id=chat_id,
            content=(
                "SLICE16E_DISASTER_RESTORE_CANARY "
                "must survive the isolated restore."
            ),
        )

        snapshot = app.backup.create_snapshot(
            target_root=backup_root,
        )

        app.backup.verify_deep(
            snapshot.snapshot_id
        )

    finally:
        app.stop()

    snapshot_root = (
        backup_root
        / snapshot.relative_path
    )

    database_path = (
        runtime
        / "state"
        / "athena.db"
    )

    original_database = database_path.read_bytes()

    return (
        runtime,
        snapshot_root,
        original_database,
    )


def _run_recovery_process(
    *,
    module: str,
    arguments: tuple[str, ...],
    live_root: Path,
) -> subprocess.CompletedProcess[str]:
    environment = os.environ.copy()
    environment["ATHENA_LOCAL_ROOT"] = str(
        live_root.resolve()
    )

    return subprocess.run(
        [
            sys.executable,
            "-m",
            module,
            *arguments,
        ],
        text=True,
        capture_output=True,
        check=False,
        env=environment,
    )


def _assert_restored_database(
    destination: Path,
) -> None:
    marker = (
        destination
        / "state"
        / "restore.complete"
    )
    database_path = (
        destination
        / "state"
        / "athena.db"
    )

    assert marker.is_file()
    assert database_path.is_file()

    connection = sqlite3.connect(
        database_path
    )

    try:
        assert (
            connection.execute(
                "PRAGMA integrity_check"
            ).fetchone()[0]
            == "ok"
        )

        assert (
            connection.execute(
                "PRAGMA foreign_key_check"
            ).fetchall()
            == []
        )

        row = connection.execute(
            """
            SELECT content
            FROM chat_message_revisions
            WHERE content LIKE ?
            """,
            (
                "%SLICE16E_DISASTER_RESTORE_CANARY%",
            ),
        ).fetchone()

        assert row is not None

    finally:
        connection.close()


def test_minimal_recovery_module_imports_no_normal_runtime_services(
    tmp_path: Path,
) -> None:
    del tmp_path

    code = r"""
import sys

import athena.recovery_cli

forbidden = (
    "athena.core.application",
    "athena.model.adapters.lm_studio",
    "athena.model.adapters.lm_studio_embeddings",
    "athena.news.service",
    "athena.security.service",
)

loaded = [
    name
    for name in forbidden
    if name in sys.modules
]

if loaded:
    raise SystemExit(
        "forbidden recovery imports: "
        + ", ".join(loaded)
    )
"""

    completed = subprocess.run(
        [
            sys.executable,
            "-c",
            code,
        ],
        text=True,
        capture_output=True,
        check=False,
    )

    assert completed.returncode == 0, (
        completed.stdout
        + completed.stderr
    )


def test_dedicated_recovery_cli_restores_with_corrupt_live_database(
    tmp_path: Path,
) -> None:
    (
        live_root,
        snapshot_root,
        _original_database,
    ) = _create_completed_backup(
        tmp_path
    )

    live_database = (
        live_root
        / "state"
        / "athena.db"
    )

    corrupt_bytes = (
        b"SLICE16E_CORRUPT_LIVE_DATABASE_"
        b"DO_NOT_OPEN_OR_REPAIR"
    )

    live_database.write_bytes(
        corrupt_bytes
    )

    destination = (
        tmp_path
        / "dedicated-recovery"
    )

    completed = _run_recovery_process(
        module="athena.recovery_cli",
        arguments=(
            "restore-path",
            str(snapshot_root.resolve()),
            str(destination.resolve()),
        ),
        live_root=live_root,
    )

    assert completed.returncode == 0, (
        completed.stdout
        + completed.stderr
    )

    assert (
        "Normal ATHENA Core startup was bypassed."
        in completed.stdout
    )
    assert (
        "configured live athena.db was not opened"
        in completed.stdout
    )

    assert live_database.read_bytes() == corrupt_bytes

    _assert_restored_database(
        destination
    )


def test_normal_cli_restore_path_bridge_bypasses_corrupt_live_database(
    tmp_path: Path,
) -> None:
    (
        live_root,
        snapshot_root,
        _original_database,
    ) = _create_completed_backup(
        tmp_path
    )

    live_database = (
        live_root
        / "state"
        / "athena.db"
    )

    corrupt_bytes = (
        b"SLICE16E_CORRUPT_NORMAL_CLI_DATABASE_"
        b"MUST_REMAIN_UNCHANGED"
    )

    live_database.write_bytes(
        corrupt_bytes
    )

    destination = (
        tmp_path
        / "normal-cli-bridge"
    )

    completed = _run_recovery_process(
        module="athena",
        arguments=(
            "backup",
            "restore-path",
            str(snapshot_root.resolve()),
            str(destination.resolve()),
        ),
        live_root=live_root,
    )

    assert completed.returncode == 0, (
        completed.stdout
        + completed.stderr
    )

    assert (
        "Normal ATHENA Core startup was bypassed."
        in completed.stdout
    )

    assert live_database.read_bytes() == corrupt_bytes

    _assert_restored_database(
        destination
    )


def test_recovery_restore_rejects_live_root_overlap_without_opening_live_db(
    tmp_path: Path,
) -> None:
    (
        live_root,
        snapshot_root,
        _original_database,
    ) = _create_completed_backup(
        tmp_path
    )

    live_database = (
        live_root
        / "state"
        / "athena.db"
    )

    corrupt_bytes = (
        b"SLICE16E_OVERLAP_CORRUPT_DATABASE"
    )

    live_database.write_bytes(
        corrupt_bytes
    )

    overlapping_destination = (
        live_root
        / "restored-inside-live-root"
    )

    completed = _run_recovery_process(
        module="athena.recovery_cli",
        arguments=(
            "restore-path",
            str(snapshot_root.resolve()),
            str(overlapping_destination.resolve()),
        ),
        live_root=live_root,
    )

    assert completed.returncode == 2

    assert (
        "Restore destination must be isolated from live ATHENA roots."
        in completed.stderr
    )

    assert not overlapping_destination.exists()
    assert live_database.read_bytes() == corrupt_bytes
