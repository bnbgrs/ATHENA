"""Cross-process serialization for physical ATHENA data mutation."""

from __future__ import annotations

import importlib
import os
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import BinaryIO


class RuntimeDataLockError(RuntimeError):
    """Runtime data mutation lock cannot be established safely."""


class _ThreadState(threading.local):
    def __init__(self) -> None:
        self.depths: dict[str, int] = {}


_LOCAL_LOCK = threading.RLock()
_THREAD_STATE = _ThreadState()


def _lock_windows(
    handle: BinaryIO,
) -> None:
    module = importlib.import_module(
        "msvcrt"
    )

    if os.fstat(
        handle.fileno()
    ).st_size == 0:
        handle.seek(0)
        handle.write(
            b"\0"
        )
        handle.flush()
        os.fsync(
            handle.fileno()
        )

    handle.seek(0)

    module.locking(
        handle.fileno(),
        module.LK_LOCK,
        1,
    )


def _unlock_windows(
    handle: BinaryIO,
) -> None:
    module = importlib.import_module(
        "msvcrt"
    )

    handle.seek(0)

    module.locking(
        handle.fileno(),
        module.LK_UNLCK,
        1,
    )


def _lock_posix(
    handle: BinaryIO,
) -> None:
    module = importlib.import_module(
        "fcntl"
    )

    module.flock(
        handle.fileno(),
        module.LOCK_EX,
    )


def _unlock_posix(
    handle: BinaryIO,
) -> None:
    module = importlib.import_module(
        "fcntl"
    )

    module.flock(
        handle.fileno(),
        module.LOCK_UN,
    )


@contextmanager
def runtime_data_lock(
    state_root: Path | None,
) -> Iterator[None]:
    """Serialize operations that may create, move, or delete Raw Archive bytes."""

    if state_root is None:
        yield
        return

    requested = (
        state_root.expanduser()
    )

    requested.mkdir(
        parents=True,
        exist_ok=True,
    )

    if (
        requested.is_symlink()
        or not requested.is_dir()
    ):
        raise RuntimeDataLockError(
            "ATHENA state root is unavailable "
            "for runtime mutation locking."
        )

    root = requested.resolve()

    key = os.path.normcase(
        str(
            root
        )
    )

    with _LOCAL_LOCK:
        depth = (
            _THREAD_STATE.depths.get(
                key,
                0,
            )
        )

        if depth > 0:
            _THREAD_STATE.depths[
                key
            ] = depth + 1

            try:
                yield

            finally:
                remaining = (
                    _THREAD_STATE.depths[
                        key
                    ]
                    - 1
                )

                if remaining:
                    _THREAD_STATE.depths[
                        key
                    ] = remaining
                else:
                    _THREAD_STATE.depths.pop(
                        key,
                        None,
                    )

            return

        lock_path = (
            root
            / ".athena-runtime-data.lock"
        )

        try:
            handle = lock_path.open(
                "a+b"
            )
        except OSError as exc:
            raise RuntimeDataLockError(
                "ATHENA runtime mutation lock "
                "file cannot be opened."
            ) from exc

        locked = False

        try:
            try:
                if os.name == "nt":
                    _lock_windows(
                        handle
                    )
                else:
                    _lock_posix(
                        handle
                    )

            except OSError as exc:
                raise RuntimeDataLockError(
                    "ATHENA runtime mutation lock "
                    "cannot be acquired."
                ) from exc

            locked = True

            _THREAD_STATE.depths[
                key
            ] = 1

            yield

        finally:
            _THREAD_STATE.depths.pop(
                key,
                None,
            )

            if locked:
                try:
                    if os.name == "nt":
                        _unlock_windows(
                            handle
                        )
                    else:
                        _unlock_posix(
                            handle
                        )

                except OSError as exc:
                    raise RuntimeDataLockError(
                        "ATHENA runtime mutation lock "
                        "could not be released cleanly."
                    ) from exc

            handle.close()
