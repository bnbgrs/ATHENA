"""Cross-process serialization for one backup target."""

from __future__ import annotations

import importlib
import os
from contextlib import contextmanager
from pathlib import Path
from typing import BinaryIO, Iterator


class BackupTargetBusyError(RuntimeError):
    """Raised when another process owns the backup-target lock."""


def _lock_windows(handle: BinaryIO) -> None:
    module = importlib.import_module("msvcrt")

    if os.fstat(handle.fileno()).st_size == 0:
        handle.seek(0)
        handle.write(b"\0")
        handle.flush()
        os.fsync(handle.fileno())

    handle.seek(0)

    try:
        module.locking(
            handle.fileno(),
            module.LK_NBLCK,
            1,
        )
    except OSError as exc:
        raise BackupTargetBusyError(
            "Backup target is busy in another process."
        ) from exc


def _unlock_windows(handle: BinaryIO) -> None:
    module = importlib.import_module("msvcrt")
    handle.seek(0)
    module.locking(
        handle.fileno(),
        module.LK_UNLCK,
        1,
    )


def _lock_posix(handle: BinaryIO) -> None:
    module = importlib.import_module("fcntl")

    try:
        module.flock(
            handle.fileno(),
            module.LOCK_EX | module.LOCK_NB,
        )
    except OSError as exc:
        raise BackupTargetBusyError(
            "Backup target is busy in another process."
        ) from exc


def _unlock_posix(handle: BinaryIO) -> None:
    module = importlib.import_module("fcntl")
    module.flock(
        handle.fileno(),
        module.LOCK_UN,
    )


@contextmanager
def backup_target_lock(target_root: Path) -> Iterator[None]:
    if not target_root.is_dir():
        raise RuntimeError(
            f"Backup target is unavailable: {target_root}"
        )

    lock_path = target_root / ".athena-backup.lock"
    handle = lock_path.open("a+b")

    locked = False

    try:
        if os.name == "nt":
            _lock_windows(handle)
        else:
            _lock_posix(handle)

        locked = True
        yield

    finally:
        if locked:
            if os.name == "nt":
                _unlock_windows(handle)
            else:
                _unlock_posix(handle)

        handle.close()
