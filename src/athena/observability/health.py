"""Minimal Core health model."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class HealthStatus(str, Enum):
    STOPPED = "stopped"
    STARTING = "starting"
    OK = "ok"


@dataclass(frozen=True, slots=True)
class HealthSnapshot:
    status: HealthStatus


class HealthService:
    """In-memory Phase-0 health service."""

    def __init__(self) -> None:
        self._status = HealthStatus.STOPPED

    def mark_starting(self) -> None:
        self._status = HealthStatus.STARTING

    def mark_ok(self) -> None:
        self._status = HealthStatus.OK

    def mark_stopped(self) -> None:
        self._status = HealthStatus.STOPPED

    def snapshot(self) -> HealthSnapshot:
        return HealthSnapshot(status=self._status)
