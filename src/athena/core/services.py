"""Service lifecycle primitives for the ATHENA Core."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from athena.core.errors import ShutdownError, StartupError


@runtime_checkable
class LifecycleService(Protocol):
    """Minimal contract for a service managed by the ATHENA Core."""

    @property
    def name(self) -> str:
        """Stable diagnostic name for the service."""
        ...

    def start(self) -> None:
        """Start the service."""
        ...

    def stop(self) -> None:
        """Stop the service."""
        ...


@dataclass(frozen=True, slots=True)
class ServiceFailure:
    """A service plus the exception raised by a lifecycle operation."""

    service_name: str
    error: Exception


class ServiceManager:
    """Starts services in order and stops them in reverse order.

    Startup is transactional at the service-lifecycle level: if service N
    fails, every service successfully started before it is stopped again.
    """

    def __init__(self, services: tuple[LifecycleService, ...] = ()) -> None:
        self._services = services
        self._started: list[LifecycleService] = []

    @property
    def started_service_names(self) -> tuple[str, ...]:
        return tuple(service.name for service in self._started)

    def start_all(self) -> None:
        if self._started:
            return

        for service in self._services:
            try:
                service.start()
            except Exception as exc:
                rollback_failures = self._stop_started_best_effort()
                suffix = ""
                if rollback_failures:
                    failed_names = ", ".join(
                        failure.service_name for failure in rollback_failures
                    )
                    suffix = f" Rollback also failed for: {failed_names}."
                raise StartupError(
                    f"Failed to start service {service.name!r}.{suffix}"
                ) from exc
            self._started.append(service)

    def stop_all(self) -> None:
        failures = self._stop_started_best_effort()
        if failures:
            failed_names = ", ".join(
                failure.service_name for failure in failures
            )
            raise ShutdownError(
                f"Failed to stop one or more services: {failed_names}."
            )

    def _stop_started_best_effort(self) -> tuple[ServiceFailure, ...]:
        failures: list[ServiceFailure] = []

        while self._started:
            service = self._started.pop()
            try:
                service.stop()
            except Exception as exc:
                failures.append(
                    ServiceFailure(service_name=service.name, error=exc)
                )

        return tuple(failures)
