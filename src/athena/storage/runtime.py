"""Runtime filesystem bootstrap service."""

from __future__ import annotations

import os
import secrets
from pathlib import Path

from athena.storage.paths import RuntimePaths


class RuntimePathError(RuntimeError):
    """Raised when required local runtime storage is unusable."""


class RuntimeLayoutService:
    """Create and validate ATHENA's required local runtime directories.

    Stopping this service never deletes data. Runtime directories can contain
    non-reconstructible state, so cleanup belongs to explicit maintenance
    operations rather than application shutdown.
    """

    name = "runtime-layout"

    def __init__(self, paths: RuntimePaths) -> None:
        self.paths = paths

    def start(self) -> None:
        for directory in self.paths.required_local_directories:
            self._ensure_directory(directory)

        self._verify_writable(self.paths.state_root)
        self._verify_writable(self.paths.spool_root)
        self._verify_writable(self.paths.derived_root)
        self._verify_writable(self.paths.log_root)
        self._verify_writable(self.paths.temp_root)

    def stop(self) -> None:
        # Deliberately a no-op: persistent state must survive application stop.
        return

    @staticmethod
    def _ensure_directory(path: Path) -> None:
        try:
            path.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise RuntimePathError(
                f"Cannot create ATHENA runtime directory {str(path)!r}."
            ) from exc

        if not path.is_dir():
            raise RuntimePathError(
                f"ATHENA runtime path is not a directory: {str(path)!r}."
            )

    @staticmethod
    def _verify_writable(path: Path) -> None:
        probe = path / f".athena-write-probe-{os.getpid()}-{secrets.token_hex(4)}"

        try:
            with probe.open("xb") as handle:
                handle.write(b"ATHENA")
                handle.flush()
                os.fsync(handle.fileno())
        except OSError as exc:
            raise RuntimePathError(
                f"ATHENA runtime directory is not writable: {str(path)!r}."
            ) from exc
        finally:
            try:
                probe.unlink(missing_ok=True)
            except OSError as exc:
                # A failed probe cleanup is itself evidence that the directory
                # is not healthy enough for durable ATHENA state.
                if probe.exists():
                    raise RuntimePathError(
                        f"ATHENA could not clean its write probe in "
                        f"{str(path)!r}."
                    ) from exc
