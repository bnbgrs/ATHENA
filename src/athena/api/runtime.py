"""Ephemeral local-discovery state for the ATHENA Core API."""

from __future__ import annotations

import hmac
import json
import os
import secrets
from dataclasses import dataclass
from pathlib import Path

from athena.api.contracts import API_VERSION
from athena.storage.durable_fs import durable_replace

_LOOPBACK_HOST = "127.0.0.1"
_DISCOVERY_FILE = "core-api.json"
_TOKEN_FILE = "core-api.token"
_PRIVATE_MODE = 0o600


class ApiRuntimeError(RuntimeError):
    """Raised when local API bootstrap state cannot be published safely."""


@dataclass(frozen=True, slots=True)
class ApiDiscovery:
    """Non-secret endpoint metadata read by a local ATHENA client."""

    api_version: str
    host: str
    port: int
    token_path: str
    process_id: int

    def to_dict(self) -> dict[str, str | int]:
        return {
            "api_version": self.api_version,
            "host": self.host,
            "port": self.port,
            "token_path": self.token_path,
            "process_id": self.process_id,
        }


class LocalApiRuntime:
    """Manage one process-local API token and its discovery metadata."""

    def __init__(self, runtime_root: Path) -> None:
        self.runtime_root = Path(runtime_root)
        self.discovery_path = self.runtime_root / _DISCOVERY_FILE
        self.token_path = self.runtime_root / _TOKEN_FILE
        self._token: str | None = None

    def publish(self, *, port: int) -> ApiDiscovery:
        """Publish a fresh loopback endpoint and private bootstrap token."""
        if not 1 <= port <= 65535:
            raise ValueError("Local ATHENA API port must be between 1 and 65535.")

        self._validate_runtime_root()
        token = secrets.token_urlsafe(48)
        discovery = ApiDiscovery(
            api_version=API_VERSION,
            host=_LOOPBACK_HOST,
            port=port,
            token_path=str(self.token_path),
            process_id=os.getpid(),
        )

        try:
            _write_private_text(self.token_path, token + "\n")
            _write_private_text(
                self.discovery_path,
                json.dumps(
                    discovery.to_dict(),
                    sort_keys=True,
                    separators=(",", ":"),
                )
                + "\n",
            )
        except Exception:
            self.clear()
            raise

        self._token = token
        return discovery

    def authenticate(self, presented_token: str) -> bool:
        """Validate one client token without timing-sensitive equality."""
        token = self._token
        if token is None or not presented_token:
            return False
        return hmac.compare_digest(token, presented_token)

    def clear(self) -> None:
        """Remove ephemeral client bootstrap state and forget the token."""
        self._token = None
        for path in (self.discovery_path, self.token_path):
            try:
                path.unlink(missing_ok=True)
            except OSError as exc:
                raise ApiRuntimeError(
                    f"Cannot remove ATHENA API runtime file {str(path)!r}."
                ) from exc

    def _validate_runtime_root(self) -> None:
        root = self.runtime_root
        if root.is_symlink():
            raise ApiRuntimeError(
                f"ATHENA API runtime root must not be a symlink: {str(root)!r}."
            )
        try:
            root.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise ApiRuntimeError(
                f"Cannot create ATHENA API runtime root {str(root)!r}."
            ) from exc
        if not root.is_dir():
            raise ApiRuntimeError(
                f"ATHENA API runtime root is not a directory: {str(root)!r}."
            )


def _write_private_text(path: Path, content: str) -> None:
    staging = path.with_name(f".{path.name}.{secrets.token_hex(8)}.partial")
    encoded = content.encode("utf-8")

    try:
        descriptor = os.open(
            staging,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL,
            _PRIVATE_MODE,
        )
        try:
            with os.fdopen(descriptor, "wb", closefd=True) as handle:
                handle.write(encoded)
                handle.flush()
                os.fsync(handle.fileno())
        except Exception:
            try:
                os.close(descriptor)
            except OSError:
                pass
            raise

        try:
            os.chmod(staging, _PRIVATE_MODE)
        except OSError as exc:
            raise ApiRuntimeError(
                f"Cannot restrict ATHENA API runtime file {str(path)!r}."
            ) from exc

        durable_replace(staging, path)
    except OSError as exc:
        raise ApiRuntimeError(
            f"Cannot publish ATHENA API runtime file {str(path)!r}."
        ) from exc
    finally:
        try:
            staging.unlink(missing_ok=True)
        except OSError:
            pass
