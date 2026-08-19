from __future__ import annotations

import threading

from PySide6.QtCore import QThreadPool
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


class _Gateway:
    def __init__(
        self,
        *,
        core_fail: bool = False,
        chat_fail: bool = False,
        model_fail: bool = False,
    ) -> None:
        self.core_fail = core_fail
        self.chat_fail = chat_fail
        self.model_fail = model_fail
        self.thread_ids: list[int] = []

    def _record(self) -> None:
        self.thread_ids.append(threading.get_ident())

    def health(self) -> HealthResponse:
        self._record()
        if self.core_fail:
            raise CoreApiClientError("ATHENA Core is unavailable.")
        return HealthResponse(api_version="v1", core_status="ok", detail=None)

    def provider_health(self) -> ProviderHealthResponse:
        self._record()
        if self.model_fail:
            raise CoreApiClientError("LM Studio is unavailable.")
        return ProviderHealthResponse(provider="lm_studio", status="ready", detail=None)

    def list_models(self) -> tuple[ModelResponse, ...]:
        self._record()
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

    def list_chats(self, *, limit: int = 50) -> tuple[ChatSummaryResponse, ...]:
        self._record()
        if self.chat_fail:
            raise CoreApiClientError("Chat status is unavailable.")
        assert limit == 50
        return (
            ChatSummaryResponse(
                chat_id="chat-1",
                started_at_us=1,
                ended_at_us=None,
                archive_mode="standard",
                lifecycle_state="active",
                message_count=2,
            ),
        )


def _app() -> QApplication:
    return create_application(["athena-desktop-controller-test"])


def _pool() -> QThreadPool:
    pool = QThreadPool()
    pool.setMaxThreadCount(1)
    return pool


def test_controller_refresh_runs_gateway_off_ui_thread() -> None:
    app = _app()
    gateway = _Gateway()
    pool = _pool()
    controller = DesktopApiController(gateway, thread_pool=pool)
    spy = QSignalSpy(controller.snapshot_ready)
    main_thread = threading.get_ident()

    controller.refresh()

    assert pool.waitForDone(2_000)
    app.processEvents()
    assert spy.count() == 1
    snapshot = spy.at(0)[0]
    assert isinstance(snapshot, DesktopApiSnapshot)
    assert snapshot.health.core_status == "ok"
    assert snapshot.loaded_model is not None
    assert snapshot.loaded_model.display_name == "Qwen Test"
    assert gateway.thread_ids
    assert all(thread_id != main_thread for thread_id in gateway.thread_ids)
    assert pool.waitForDone(2_000)


def test_controller_reports_safe_core_failure() -> None:
    app = _app()
    gateway = _Gateway(core_fail=True)
    pool = _pool()
    controller = DesktopApiController(gateway, thread_pool=pool)
    spy = QSignalSpy(controller.connection_failed)

    controller.refresh()

    assert pool.waitForDone(2_000)
    app.processEvents()
    assert spy.count() == 1
    assert spy.at(0)[0] == "ATHENA Core is unavailable."


def test_controller_keeps_core_connected_when_optional_status_fails() -> None:
    app = _app()
    gateway = _Gateway(chat_fail=True, model_fail=True)
    pool = _pool()
    controller = DesktopApiController(gateway, thread_pool=pool)
    spy = QSignalSpy(controller.snapshot_ready)

    controller.refresh()

    assert pool.waitForDone(2_000)
    app.processEvents()
    assert spy.count() == 1
    snapshot = spy.at(0)[0]
    assert isinstance(snapshot, DesktopApiSnapshot)
    assert snapshot.health.core_status == "ok"
    assert snapshot.provider is None
    assert snapshot.models == ()
    assert snapshot.chats == ()
    assert snapshot.chat_error == "Chat status is unavailable."
    assert snapshot.model_error == "LM Studio is unavailable."
    assert pool.waitForDone(2_000)
