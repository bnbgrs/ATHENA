"""ATHENA application lifecycle coordinator."""

from __future__ import annotations

from enum import Enum

from athena.config.settings import AthenaSettings
from athena.observability.health import HealthService
from athena.observability.logging import configure_logging


class ApplicationState(str, Enum):
    """Lifecycle states of the local ATHENA Core."""

    STOPPED = "stopped"
    STARTING = "starting"
    RUNNING = "running"
    STOPPING = "stopping"


class AthenaApplication:
    """Minimal Phase-0 ATHENA Core.

    Product/domain services will be attached here incrementally through
    later vertical slices. Phase 0 deliberately contains no knowledge,
    model, storage, network, or background-job logic.
    """

    def __init__(self, settings: AthenaSettings | None = None) -> None:
        self.settings = settings or AthenaSettings.from_environment()
        self.state = ApplicationState.STOPPED
        self.health = HealthService()

    def start(self) -> None:
        """Start the application safely and idempotently."""
        if self.state is ApplicationState.RUNNING:
            return
        if self.state is not ApplicationState.STOPPED:
            raise RuntimeError(f"Cannot start ATHENA from state {self.state.value!r}.")

        self.state = ApplicationState.STARTING
        configure_logging(self.settings.log_level)
        self.health.mark_starting()

        # Later slices attach concrete services here only after their own
        # initialization has succeeded.
        self.state = ApplicationState.RUNNING
        self.health.mark_ok()

    def stop(self) -> None:
        """Stop the application safely and idempotently."""
        if self.state is ApplicationState.STOPPED:
            return
        if self.state is not ApplicationState.RUNNING:
            raise RuntimeError(f"Cannot stop ATHENA from state {self.state.value!r}.")

        self.state = ApplicationState.STOPPING

        # Later slices shut down concrete services here in reverse order.
        self.health.mark_stopped()
        self.state = ApplicationState.STOPPED
