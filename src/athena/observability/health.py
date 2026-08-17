"""Core health model."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class HealthStatus(str, Enum):
    STOPPED = "stopped"
    STARTING = "starting"
    RECOVERY_REQUIRED = "recovery_required"
    OK = "ok"
    STOPPING = "stopping"
    FAILED = "failed"


@dataclass(frozen=True, slots=True)
class HealthSnapshot:
    status: HealthStatus
    detail: str | None = None


class HealthService:
    """In-memory bootstrap health service."""

    def __init__(self) -> None:
        self._status = HealthStatus.STOPPED
        self._detail: str | None = None

    def mark_starting(self) -> None:
        self._set(HealthStatus.STARTING)

    def mark_ok(self) -> None:
        self._set(HealthStatus.OK)

    def mark_recovery_required(self, detail: str) -> None:
        self._set(HealthStatus.RECOVERY_REQUIRED, detail)

    def mark_stopping(self) -> None:
        self._set(HealthStatus.STOPPING)

    def mark_stopped(self) -> None:
        self._set(HealthStatus.STOPPED)

    def mark_failed(self, detail: str) -> None:
        self._set(HealthStatus.FAILED, detail)

    def snapshot(self) -> HealthSnapshot:
        return HealthSnapshot(status=self._status, detail=self._detail)

    def _set(self, status: HealthStatus, detail: str | None = None) -> None:
        self._status = status
        self._detail = detail
