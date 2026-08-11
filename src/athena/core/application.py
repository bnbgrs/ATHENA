"""ATHENA application lifecycle coordinator."""

from __future__ import annotations

import logging
from enum import Enum

from athena.chat.repository import ChatRepository
from athena.chat.service import ChatService
from athena.config.settings import AthenaSettings
from athena.core.services import LifecycleService, ServiceManager
from athena.observability.health import HealthService
from athena.observability.logging import configure_logging
from athena.storage.database import SQLiteDatabase
from athena.storage.paths import RuntimePaths
from athena.storage.runtime import RuntimeLayoutService

logger = logging.getLogger(__name__)


class ApplicationState(str, Enum):
    """Lifecycle states of the local ATHENA Core."""

    STOPPED = "stopped"
    STARTING = "starting"
    RUNNING = "running"
    STOPPING = "stopping"
    FAILED = "failed"


class AthenaApplication:
    """Failure-aware Phase-0 ATHENA Core."""

    def __init__(
        self,
        settings: AthenaSettings | None = None,
        services: tuple[LifecycleService, ...] = (),
    ) -> None:
        self.settings = settings or AthenaSettings.from_environment()
        self.paths = RuntimePaths.from_settings(self.settings)
        self.state = ApplicationState.STOPPED
        self.health = HealthService()
        self.database = SQLiteDatabase(self.paths.database_path)
        self.chat_repository = ChatRepository(self.database)
        self.chat = ChatService(self.chat_repository)

        bootstrap_services: tuple[LifecycleService, ...] = (
            RuntimeLayoutService(self.paths),
            self.database,
        )
        self.services = ServiceManager(bootstrap_services + services)

    def start(self) -> None:
        """Start ATHENA and all registered services safely."""
        if self.state is ApplicationState.RUNNING:
            return
        if self.state is not ApplicationState.STOPPED:
            raise RuntimeError(
                f"Cannot start ATHENA from state {self.state.value!r}."
            )

        self.state = ApplicationState.STARTING
        self.health.mark_starting()
        configure_logging(self.settings.numeric_log_level)

        logger.info("ATHENA Core starting", extra={"event": "core.starting"})

        try:
            self.services.start_all()
        except Exception as exc:
            self.state = ApplicationState.FAILED
            self.health.mark_failed(str(exc))
            logger.exception(
                "ATHENA Core startup failed",
                extra={"event": "core.start_failed"},
            )
            raise

        self.state = ApplicationState.RUNNING
        self.health.mark_ok()
        logger.info("ATHENA Core running", extra={"event": "core.running"})

    def stop(self) -> None:
        """Stop ATHENA and all registered services safely."""
        if self.state is ApplicationState.STOPPED:
            return
        if self.state not in {
            ApplicationState.RUNNING,
            ApplicationState.FAILED,
        }:
            raise RuntimeError(
                f"Cannot stop ATHENA from state {self.state.value!r}."
            )

        self.state = ApplicationState.STOPPING
        self.health.mark_stopping()
        logger.info("ATHENA Core stopping", extra={"event": "core.stopping"})

        try:
            self.services.stop_all()
        except Exception as exc:
            self.state = ApplicationState.FAILED
            self.health.mark_failed(str(exc))
            logger.exception(
                "ATHENA Core shutdown failed",
                extra={"event": "core.stop_failed"},
            )
            raise

        self.state = ApplicationState.STOPPED
        self.health.mark_stopped()
        logger.info("ATHENA Core stopped", extra={"event": "core.stopped"})
