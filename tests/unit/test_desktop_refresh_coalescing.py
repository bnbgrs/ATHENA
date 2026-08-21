from __future__ import annotations

from PySide6.QtCore import QRunnable
from PySide6.QtTest import QSignalSpy
from PySide6.QtWidgets import QApplication

from athena.api.client import CoreApiClientError
from athena.api.contracts import (
    ChatSummaryResponse,
    HealthResponse,
    ModelResponse,
    ProviderHealthResponse,
)
from athena.desktop.api_controller import DesktopApiController, DesktopApiSnapshot
from athena.desktop.app import create_application


class _ManualPool:
    def __init__(self) -> None:
        self.tasks: list[QRunnable] = []

    def start(self, task: QRunnable) -> None:
        self.tasks.append(task)


class _Gateway:
    def __init__(self) -> None:
        self.version = 1
        self.fail_core = False

    def health(self) -> HealthResponse:
        if self.fail_core:
            raise CoreApiClientError("ATHENA Core is unavailable.")
        return HealthResponse(
            api_version="v1",
            core_status="ok",
            detail=None,
        )

    def provider_health(self) -> ProviderHealthResponse:
        return ProviderHealthResponse(
            provider="lm_studio",
            status="ready",
            detail=None,
        )

    def list_models(self) -> tuple[ModelResponse, ...]:
        return (
            ModelResponse(
                provider="lm_studio",
                backend_model_id="qwen-test",
                display_name="Qwen Test",
                model_type="llm",
                context_capacity=128_000,
                quantization="Q4",
                loaded=True,
                vision=False,
                trained_for_tool_use=True,
                loaded_context_length=48_000,
            ),
        )

    def list_chats(
        self,
        *,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[ChatSummaryResponse, ...]:
        assert limit == 50
        if offset:
            return ()
        return (
            ChatSummaryResponse(
                chat_id=f"chat-{self.version}",
                started_at_us=self.version,
                ended_at_us=None,
                archive_mode="standard",
                lifecycle_state="active",
                message_count=self.version,
            ),
        )


def _app() -> QApplication:
    return create_application(
        ["athena-desktop-refresh-coalescing-test"]
    )


def _run_next(
    pool: _ManualPool,
    app: QApplication,
) -> None:
    assert pool.tasks
    task = pool.tasks.pop(0)
    task.run()
    app.processEvents()


def test_refresh_requests_while_busy_coalesce_into_one_follow_up() -> None:
    app = _app()
    gateway = _Gateway()
    pool = _ManualPool()
    controller = DesktopApiController(
        gateway,  # type: ignore[arg-type]
        thread_pool=pool,  # type: ignore[arg-type]
    )
    snapshots = QSignalSpy(controller.snapshot_ready)
    states = QSignalSpy(controller.refresh_state_changed)

    controller.refresh()
    controller.refresh()
    controller.refresh()

    assert controller.refreshing is True
    assert len(pool.tasks) == 1
    assert states.count() == 1
    assert states.at(0)[0] is True

    _run_next(pool, app)

    assert snapshots.count() == 1
    assert len(pool.tasks) == 1
    assert controller.refreshing is True
    assert states.count() == 1

    gateway.version = 2
    _run_next(pool, app)

    assert snapshots.count() == 2
    snapshot = snapshots.at(1)[0]
    assert isinstance(snapshot, DesktopApiSnapshot)
    assert snapshot.chats[0].chat_id == "chat-2"

    assert pool.tasks == []
    assert controller.refreshing is False
    assert states.count() == 2
    assert states.at(0)[0] is True
    assert states.at(1)[0] is False


def test_failed_refresh_still_runs_coalesced_follow_up() -> None:
    app = _app()
    gateway = _Gateway()
    gateway.fail_core = True
    pool = _ManualPool()
    controller = DesktopApiController(
        gateway,  # type: ignore[arg-type]
        thread_pool=pool,  # type: ignore[arg-type]
    )
    failures = QSignalSpy(controller.connection_failed)
    snapshots = QSignalSpy(controller.snapshot_ready)
    states = QSignalSpy(controller.refresh_state_changed)

    controller.refresh()
    controller.refresh()

    assert len(pool.tasks) == 1

    _run_next(pool, app)

    assert failures.count() == 1
    assert snapshots.count() == 0
    assert len(pool.tasks) == 1
    assert controller.refreshing is True
    assert states.count() == 1

    gateway.fail_core = False
    gateway.version = 2
    _run_next(pool, app)

    assert snapshots.count() == 1
    snapshot = snapshots.at(0)[0]
    assert isinstance(snapshot, DesktopApiSnapshot)
    assert snapshot.chats[0].chat_id == "chat-2"

    assert controller.refreshing is False
    assert pool.tasks == []
    assert states.count() == 2
    assert states.at(0)[0] is True
    assert states.at(1)[0] is False
