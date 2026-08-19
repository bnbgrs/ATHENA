"""Asynchronous Core API refresh boundary for the ATHENA desktop shell."""

from __future__ import annotations

from dataclasses import dataclass
from queue import Empty, SimpleQueue
from typing import Protocol

from PySide6.QtCore import QMetaObject, QObject, QRunnable, Qt, QThreadPool, Signal, Slot

from athena.api.client import CoreApiClientError
from athena.api.contracts import (
    ChatSummaryResponse,
    HealthResponse,
    ModelResponse,
    ProviderHealthResponse,
)


class CoreApiGateway(Protocol):
    """Minimal read surface consumed by the desktop status controller."""

    def health(self) -> HealthResponse: ...

    def provider_health(self) -> ProviderHealthResponse: ...

    def list_models(self) -> tuple[ModelResponse, ...]: ...

    def list_chats(self, *, limit: int = 50) -> tuple[ChatSummaryResponse, ...]: ...


@dataclass(frozen=True, slots=True)
class DesktopApiSnapshot:
    """One coherent read snapshot rendered by the desktop shell."""

    health: HealthResponse
    provider: ProviderHealthResponse | None
    models: tuple[ModelResponse, ...]
    chats: tuple[ChatSummaryResponse, ...]
    chat_error: str | None = None
    model_error: str | None = None

    @property
    def loaded_model(self) -> ModelResponse | None:
        return next((model for model in self.models if model.loaded), None)


@dataclass(frozen=True, slots=True)
class _RefreshOutcome:
    snapshot: DesktopApiSnapshot | None = None
    error: str | None = None

    def __post_init__(self) -> None:
        if (self.snapshot is None) == (self.error is None):
            raise ValueError("Refresh outcome requires exactly one result kind.")


def _chat_snapshot(
    gateway: CoreApiGateway,
    *,
    chat_limit: int,
) -> tuple[tuple[ChatSummaryResponse, ...], str | None]:
    try:
        return gateway.list_chats(limit=chat_limit), None
    except CoreApiClientError as exc:
        return (), str(exc)
    except Exception:
        return (), "ATHENA chat status refresh failed."


def _model_snapshot(
    gateway: CoreApiGateway,
) -> tuple[ProviderHealthResponse | None, tuple[ModelResponse, ...], str | None]:
    try:
        provider = gateway.provider_health()
    except CoreApiClientError as exc:
        return None, (), str(exc)
    except Exception:
        return None, (), "ATHENA model provider status refresh failed."

    try:
        return provider, gateway.list_models(), None
    except CoreApiClientError as exc:
        return provider, (), str(exc)
    except Exception:
        return provider, (), "ATHENA model list refresh failed."


def _collect_snapshot(
    gateway: CoreApiGateway,
    *,
    chat_limit: int,
) -> DesktopApiSnapshot:
    health = gateway.health()
    chats, chat_error = _chat_snapshot(gateway, chat_limit=chat_limit)
    provider, models, model_error = _model_snapshot(gateway)
    return DesktopApiSnapshot(
        health=health,
        provider=provider,
        models=models,
        chats=chats,
        chat_error=chat_error,
        model_error=model_error,
    )


class _RefreshTask(QRunnable):
    """Collect one API snapshot in a pool thread and queue delivery to the UI."""

    def __init__(
        self,
        *,
        gateway: CoreApiGateway,
        chat_limit: int,
        outcomes: SimpleQueue[_RefreshOutcome],
        receiver: QObject,
    ) -> None:
        super().__init__()
        self.gateway = gateway
        self.chat_limit = chat_limit
        self.outcomes = outcomes
        self.receiver = receiver

        # The controller retains this runnable until the queued UI delivery
        # completes. Do not let QThreadPool delete the native runnable first.
        self.setAutoDelete(False)

    @Slot()
    def run(self) -> None:
        try:
            snapshot = _collect_snapshot(
                self.gateway,
                chat_limit=self.chat_limit,
            )
        except CoreApiClientError as exc:
            outcome = _RefreshOutcome(error=str(exc))
        except Exception:
            outcome = _RefreshOutcome(
                error="ATHENA Core status refresh failed."
            )
        else:
            outcome = _RefreshOutcome(snapshot=snapshot)

        # SimpleQueue is the only cross-thread data boundary. No UI QObject
        # state is mutated from this worker thread.
        self.outcomes.put(outcome)

        queued = QMetaObject.invokeMethod(
            self.receiver,
            "_drain_worker_outcome",
            Qt.ConnectionType.QueuedConnection,
        )

        if not queued:
            raise RuntimeError(
                "ATHENA desktop could not queue the API refresh result."
            )


class DesktopApiController(QObject):
    """Run Core API reads off the Qt UI thread and publish immutable snapshots."""

    snapshot_ready = Signal(object)
    connection_failed = Signal(str)
    refresh_state_changed = Signal(bool)

    def __init__(
        self,
        gateway: CoreApiGateway,
        *,
        thread_pool: QThreadPool | None = None,
        chat_limit: int = 50,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)

        if not 1 <= chat_limit <= 200:
            raise ValueError(
                "Desktop chat limit must be between 1 and 200."
            )

        self.gateway = gateway
        self.thread_pool = thread_pool or QThreadPool.globalInstance()
        self.chat_limit = chat_limit

        self._refreshing = False
        self._outcomes: SimpleQueue[_RefreshOutcome] = SimpleQueue()
        self._active_task: _RefreshTask | None = None

    @property
    def refreshing(self) -> bool:
        return self._refreshing

    @Slot()
    def refresh(self) -> None:
        if self._refreshing:
            return

        task = _RefreshTask(
            gateway=self.gateway,
            chat_limit=self.chat_limit,
            outcomes=self._outcomes,
            receiver=self,
        )

        self._active_task = task
        self._refreshing = True
        self.refresh_state_changed.emit(True)
        self.thread_pool.start(task)

    @Slot()
    def _drain_worker_outcome(self) -> None:
        try:
            try:
                outcome = self._outcomes.get_nowait()
            except Empty:
                self.connection_failed.emit(
                    "ATHENA Core status refresh result was lost."
                )
                return

            if outcome.snapshot is not None:
                self.snapshot_ready.emit(outcome.snapshot)
                return

            assert outcome.error is not None
            self.connection_failed.emit(outcome.error)
        finally:
            self._finish_refresh()

    def _finish_refresh(self) -> None:
        self._active_task = None
        self._refreshing = False
        self.refresh_state_changed.emit(False)