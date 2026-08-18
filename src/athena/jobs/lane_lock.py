"""Cross-process ownership lock for long-lived scheduler lanes."""

from __future__ import annotations

import importlib
import os
from collections.abc import Callable
from pathlib import Path
from typing import BinaryIO, cast


class SchedulerLaneOwnershipError(RuntimeError):
    """Raised when a long-lived scheduler lane already has a process owner."""


class SchedulerLaneProcessLock:
    """Hold one OS-released advisory lock for a scheduler process lifetime."""

    def __init__(
        self,
        *,
        path: Path,
        handle: BinaryIO,
    ) -> None:
        self.path = path
        self._handle: BinaryIO | None = handle

    @classmethod
    def acquire(
        cls,
        path: Path,
        *,
        lane_name: str,
    ) -> SchedulerLaneProcessLock:
        normalized_lane = lane_name.strip()
        if not normalized_lane:
            raise ValueError("Scheduler lane name must not be empty.")

        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            handle = path.open("a+b")
        except OSError as exc:
            raise SchedulerLaneOwnershipError(
                f"Scheduler {normalized_lane} lane lock cannot be opened."
            ) from exc

        try:
            handle.seek(0, os.SEEK_END)
            if handle.tell() == 0:
                handle.write(b"\0")
                handle.flush()
            handle.seek(0)
        except OSError as exc:
            handle.close()
            raise SchedulerLaneOwnershipError(
                f"Scheduler {normalized_lane} lane lock cannot be initialized."
            ) from exc

        try:
            _lock_nonblocking(handle)
        except OSError as exc:
            handle.close()
            raise SchedulerLaneOwnershipError(
                f"Scheduler {normalized_lane} lane already has a live process owner."
            ) from exc

        return cls(
            path=path,
            handle=handle,
        )

    def close(self) -> None:
        """Release process ownership by closing the locked file handle."""
        handle = self._handle
        if handle is None:
            return
        self._handle = None
        handle.close()


def _lock_nonblocking(handle: BinaryIO) -> None:
    if os.name == "nt":
        msvcrt = importlib.import_module("msvcrt")
        locking = cast(
            Callable[[int, int, int], object],
            vars(msvcrt)["locking"],
        )
        mode = cast(int, vars(msvcrt)["LK_NBLCK"])
        locking(handle.fileno(), mode, 1)
        return

    if os.name == "posix":
        fcntl = importlib.import_module("fcntl")
        flock = cast(
            Callable[[int, int], object],
            vars(fcntl)["flock"],
        )
        exclusive = cast(int, vars(fcntl)["LOCK_EX"])
        nonblocking = cast(int, vars(fcntl)["LOCK_NB"])
        flock(handle.fileno(), exclusive | nonblocking)
        return

    raise OSError(
        f"Unsupported platform for scheduler lane locking: {os.name!r}."
    )
