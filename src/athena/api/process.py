"""Dedicated long-lived ATHENA Core API process for desktop clients."""

from __future__ import annotations

import argparse
import hashlib
import importlib
import os
import sys
import tempfile
import threading
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import BinaryIO, cast

from athena.api.executor import (
    CoreDomainExecutor,
    CoreDomainExecutorError,
    SerializedCoreApiSurface,
)
from athena.api.server import CoreApiServer, CoreApiServerError
from athena.config.settings import AthenaSettings, ConfigurationError
from athena.core.application import ApplicationState, AthenaApplication

_POLL_INTERVAL_SECONDS = 0.25
_RUNTIME_DIRECTORY_NAME = "core-api"
_LOCK_DIRECTORY_NAME = "athena-core-api-locks"


class CoreApiProcessError(RuntimeError):
    """Raised when the dedicated desktop Core process cannot run safely."""


class CoreApiProcessOwnershipError(CoreApiProcessError):
    """Raised when another process already owns the desktop Core lifecycle."""


class _CoreApiProcessLock:
    """Hold one OS-released advisory lock for a desktop Core process lifetime."""

    def __init__(self, *, path: Path, handle: BinaryIO) -> None:
        self.path = path
        self._handle: BinaryIO | None = handle

    @classmethod
    def acquire(cls, local_root: Path) -> _CoreApiProcessLock:
        path = _ownership_lock_path(local_root)
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            handle = path.open("a+b")
        except OSError as exc:
            raise CoreApiProcessOwnershipError(
                "ATHENA desktop Core ownership lock cannot be opened."
            ) from exc

        try:
            handle.seek(0, os.SEEK_END)
            if handle.tell() == 0:
                handle.write(b"\0")
                handle.flush()
            handle.seek(0)
            _lock_nonblocking(handle)
        except OSError as exc:
            handle.close()
            raise CoreApiProcessOwnershipError(
                "ATHENA desktop Core already has a live process owner."
            ) from exc

        return cls(path=path, handle=handle)

    def close(self) -> None:
        handle = self._handle
        if handle is None:
            return
        self._handle = None
        handle.close()


class CoreApiProcess:
    """Own ATHENA Core, its loopback API server, and single-process ownership."""

    def __init__(self, *, settings: AthenaSettings, port: int = 0) -> None:
        if not 0 <= port <= 65535:
            raise ValueError("ATHENA Core API port must be between 0 and 65535.")
        self.settings = settings
        self.port = port
        self.app = AthenaApplication(settings=settings)
        self.executor = CoreDomainExecutor(self.app)
        self.api_surface = SerializedCoreApiSurface(
            self.app.api,
            self.executor,
        )
        self.runtime_root = self.app.paths.temp_root / _RUNTIME_DIRECTORY_NAME
        self._shutdown_requested = threading.Event()
        self.server = CoreApiServer(
            facade=self.api_surface,
            runtime_root=self.runtime_root,
            port=port,
            shutdown_callback=self.request_shutdown,
        )
        self._ownership: _CoreApiProcessLock | None = None

    @property
    def running(self) -> bool:
        return self.executor.running and self.server.running

    def start(self) -> None:
        if self.running:
            return
        if self._ownership is not None:
            raise CoreApiProcessError("ATHENA desktop Core startup is already in progress.")
        if self.app.state is not ApplicationState.STOPPED:
            raise CoreApiProcessError(
                f"ATHENA desktop Core cannot start from state {self.app.state.value!r}."
            )

        ownership = _CoreApiProcessLock.acquire(self.settings.local_root)
        self._ownership = ownership
        self._shutdown_requested.clear()

        try:
            self.executor.start()
            self.server.start()
        except Exception:
            self._rollback_startup()
            raise

    def stop(self) -> None:
        failures: list[Exception] = []

        try:
            self.server.stop()
        except Exception as exc:
            failures.append(exc)

        try:
            self.executor.stop()
        except Exception as exc:
            failures.append(exc)

        ownership = self._ownership
        self._ownership = None
        if ownership is not None:
            try:
                ownership.close()
            except Exception as exc:
                failures.append(exc)

        if failures:
            raise CoreApiProcessError(
                "ATHENA desktop Core did not stop cleanly."
            ) from failures[0]

    def request_shutdown(self) -> None:
        """Request an orderly stop from the authenticated local control API."""
        self._shutdown_requested.set()

    def wait(self, *, stop_event: threading.Event | None = None) -> int:
        """Wait for an internal or caller-provided stop request."""
        try:
            while True:
                if self._shutdown_requested.wait(_POLL_INTERVAL_SECONDS):
                    return 0
                if stop_event is not None and stop_event.is_set():
                    return 0
        except KeyboardInterrupt:
            return 130

    def run(self, *, stop_event: threading.Event | None = None) -> int:
        self.start()
        try:
            return self.wait(stop_event=stop_event)
        finally:
            self.stop()

    def _rollback_startup(self) -> None:
        try:
            self.server.stop()
        except Exception:
            pass

        try:
            self.executor.stop()
        except Exception:
            pass

        ownership = self._ownership
        self._ownership = None
        if ownership is not None:
            ownership.close()


def _ownership_lock_path(local_root: Path) -> Path:
    normalized_root = os.path.normcase(str(local_root.resolve(strict=False)))
    digest = hashlib.sha256(normalized_root.encode("utf-8")).hexdigest()[:24]
    return Path(tempfile.gettempdir()) / _LOCK_DIRECTORY_NAME / f"{digest}.lock"


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

    raise OSError(f"Unsupported platform for Core API locking: {os.name!r}.")


def _port_argument(value: str) -> int:
    try:
        port = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("port must be an integer") from exc
    if not 0 <= port <= 65535:
        raise argparse.ArgumentTypeError("port must be between 0 and 65535")
    return port


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m athena.api.process",
        description="Run the dedicated loopback-only ATHENA Core API process.",
    )
    parser.add_argument(
        "--port",
        type=_port_argument,
        default=0,
        help="Loopback TCP port; 0 chooses a free ephemeral port.",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    try:
        settings = AthenaSettings.from_environment()
        process = CoreApiProcess(settings=settings, port=args.port)
        process.start()
    except (
        ConfigurationError,
        CoreApiProcessError,
        CoreApiServerError,
        CoreDomainExecutorError,
        OSError,
    ) as exc:
        print(f"ATHENA Core API error: {exc}", file=sys.stderr)
        return 2

    try:
        port = process.server.port
        if port is None:
            raise CoreApiProcessError("ATHENA Core API started without a published port.")
        print(f"ATHENA Core API ready on 127.0.0.1:{port}", flush=True)
        print(f"Discovery: {process.server.runtime.discovery_path}", flush=True)
        return process.wait()
    finally:
        process.stop()


if __name__ == "__main__":
    raise SystemExit(main())
