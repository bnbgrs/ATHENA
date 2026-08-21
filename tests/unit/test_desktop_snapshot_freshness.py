from __future__ import annotations

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
from athena.desktop.api_controller import (
    DesktopApiController,
    DesktopApiSnapshot,
)
from athena.desktop.app import create_application
from athena.desktop.window import AthenaMainWindow


def _app() -> QApplication:
    return create_application(
        ["athena-desktop-snapshot-freshness-test"]
    )


def _pool() -> QThreadPool:
    pool = QThreadPool()
    pool.setMaxThreadCount(1)
    return pool


def _chat(
    chat_id: str = "chat-a",
) -> ChatSummaryResponse:
    return ChatSummaryResponse(
        chat_id=chat_id,
        started_at_us=1,
        ended_at_us=None,
        archive_mode="standard",
        lifecycle_state="active",
        message_count=2,
    )


def _model(
    model_id: str = "qwen-test",
) -> ModelResponse:
    return ModelResponse(
        provider="lm_studio",
        backend_model_id=model_id,
        display_name="Qwen Test",
        model_type="llm",
        context_capacity=128_000,
        quantization="Q4",
        loaded=True,
        vision=False,
        trained_for_tool_use=True,
        loaded_context_length=48_000,
    )


class _Gateway:
    def __init__(self) -> None:
        self.chat_fail = False
        self.provider_fail = False
        self.model_fail = False
        self.chats: tuple[
            ChatSummaryResponse,
            ...,
        ] = (_chat(),)
        self.provider = ProviderHealthResponse(
            provider="lm_studio",
            status="ready",
            detail=None,
        )
        self.models: tuple[
            ModelResponse,
            ...,
        ] = (_model(),)

    def health(self) -> HealthResponse:
        return HealthResponse(
            api_version="v1",
            core_status="ok",
            detail=None,
        )

    def provider_health(self) -> ProviderHealthResponse:
        if self.provider_fail:
            raise CoreApiClientError(
                "LM Studio provider unavailable."
            )
        return self.provider

    def list_models(self) -> tuple[ModelResponse, ...]:
        if self.model_fail:
            raise CoreApiClientError(
                "Model list unavailable."
            )
        return self.models

    def list_chats(
        self,
        *,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[ChatSummaryResponse, ...]:
        if self.chat_fail:
            raise CoreApiClientError(
                "Chat list unavailable."
            )
        return self.chats[
            offset : offset + limit
        ]


def _refresh(
    app: QApplication,
    pool: QThreadPool,
    controller: DesktopApiController,
    spy: QSignalSpy,
) -> DesktopApiSnapshot:
    before = spy.count()

    controller.refresh()

    assert pool.waitForDone(2_000)
    app.processEvents()

    assert spy.count() == before + 1

    snapshot = spy.at(before)[0]

    assert isinstance(
        snapshot,
        DesktopApiSnapshot,
    )

    return snapshot


def _window_snapshot(
    *,
    chat_error: str | None = None,
    model_error: str | None = None,
    chat_freshness: str | None = None,
    model_freshness: str | None = None,
) -> DesktopApiSnapshot:
    return DesktopApiSnapshot(
        health=HealthResponse(
            api_version="v1",
            core_status="ok",
            detail=None,
        ),
        provider=ProviderHealthResponse(
            provider="lm_studio",
            status="ready",
            detail=None,
        ),
        models=(_model(),),
        chats=(_chat(),),
        chat_error=chat_error,
        model_error=model_error,
        chat_freshness=chat_freshness,  # type: ignore[arg-type]
        model_freshness=model_freshness,  # type: ignore[arg-type]
    )


def test_initial_optional_failures_are_unavailable() -> None:
    app = _app()
    gateway = _Gateway()
    gateway.chat_fail = True
    gateway.provider_fail = True
    pool = _pool()
    controller = DesktopApiController(
        gateway,  # type: ignore[arg-type]
        thread_pool=pool,
    )
    spy = QSignalSpy(
        controller.snapshot_ready
    )

    snapshot = _refresh(
        app,
        pool,
        controller,
        spy,
    )

    assert snapshot.chats == ()
    assert snapshot.models == ()
    assert snapshot.provider is None
    assert snapshot.resolved_chat_freshness == "unavailable"
    assert snapshot.resolved_model_freshness == "unavailable"


def test_failed_chat_refresh_reuses_last_good_snapshot() -> None:
    app = _app()
    gateway = _Gateway()
    pool = _pool()
    controller = DesktopApiController(
        gateway,  # type: ignore[arg-type]
        thread_pool=pool,
    )
    spy = QSignalSpy(
        controller.snapshot_ready
    )

    first = _refresh(
        app,
        pool,
        controller,
        spy,
    )

    assert first.resolved_chat_freshness == "fresh"
    assert first.chats == (_chat(),)

    gateway.chat_fail = True

    second = _refresh(
        app,
        pool,
        controller,
        spy,
    )

    assert second.chat_error == "Chat list unavailable."
    assert second.resolved_chat_freshness == "stale"
    assert second.chats == first.chats
    assert second.resolved_model_freshness == "fresh"


def test_fresh_empty_chat_snapshot_replaces_previous_cache() -> None:
    app = _app()
    gateway = _Gateway()
    pool = _pool()
    controller = DesktopApiController(
        gateway,  # type: ignore[arg-type]
        thread_pool=pool,
    )
    spy = QSignalSpy(
        controller.snapshot_ready
    )

    first = _refresh(
        app,
        pool,
        controller,
        spy,
    )

    assert first.chats == (_chat(),)

    gateway.chats = ()

    empty = _refresh(
        app,
        pool,
        controller,
        spy,
    )

    assert empty.chats == ()
    assert empty.resolved_chat_freshness == "fresh"

    gateway.chat_fail = True

    stale_empty = _refresh(
        app,
        pool,
        controller,
        spy,
    )

    assert stale_empty.chats == ()
    assert stale_empty.resolved_chat_freshness == "stale"


def test_provider_failure_reuses_last_good_model_snapshot() -> None:
    app = _app()
    gateway = _Gateway()
    pool = _pool()
    controller = DesktopApiController(
        gateway,  # type: ignore[arg-type]
        thread_pool=pool,
    )
    spy = QSignalSpy(
        controller.snapshot_ready
    )

    first = _refresh(
        app,
        pool,
        controller,
        spy,
    )

    gateway.provider_fail = True

    second = _refresh(
        app,
        pool,
        controller,
        spy,
    )

    assert second.model_error == "LM Studio provider unavailable."
    assert second.resolved_model_freshness == "stale"
    assert second.provider == first.provider
    assert second.models == first.models


def test_model_list_failure_keeps_current_provider_and_old_models() -> None:
    app = _app()
    gateway = _Gateway()
    pool = _pool()
    controller = DesktopApiController(
        gateway,  # type: ignore[arg-type]
        thread_pool=pool,
    )
    spy = QSignalSpy(
        controller.snapshot_ready
    )

    first = _refresh(
        app,
        pool,
        controller,
        spy,
    )

    gateway.provider = ProviderHealthResponse(
        provider="lm_studio",
        status="ready",
        detail="new provider status",
    )
    gateway.model_fail = True

    second = _refresh(
        app,
        pool,
        controller,
        spy,
    )

    assert second.model_error == "Model list unavailable."
    assert second.resolved_model_freshness == "stale"
    assert second.provider == gateway.provider
    assert second.provider != first.provider
    assert second.models == first.models


def test_window_marks_stale_chat_list_without_blocking_chat() -> None:
    app = _app()
    window = AthenaMainWindow(
        api_controller=None
    )
    window.api_controller = object()

    try:
        window.apply_api_snapshot(
            _window_snapshot()
        )

        assert window.prompt_input.isEnabled() is True
        assert window.chat_metric.value_label.text() == "1"

        window.apply_api_snapshot(
            _window_snapshot(
                chat_error="Chat list unavailable.",
                chat_freshness="stale",
                model_freshness="fresh",
            )
        )

        assert window.chat_metric.value_label.text() == "1 · STALE"
        assert window.chat_selector.findData("chat-a") >= 0
        assert window.prompt_input.isEnabled() is True
        assert "Chat list STALE" in window.connection_detail.text()
    finally:
        window.close()
        app.processEvents()


def test_window_blocks_chat_when_model_snapshot_is_stale() -> None:
    app = _app()
    window = AthenaMainWindow(
        api_controller=None
    )
    window.api_controller = object()

    try:
        window.apply_api_snapshot(
            _window_snapshot()
        )

        assert window.prompt_input.isEnabled() is True
        assert window.model_selector.findData("qwen-test") >= 0

        window.apply_api_snapshot(
            _window_snapshot(
                model_error="Model list unavailable.",
                chat_freshness="fresh",
                model_freshness="stale",
            )
        )

        assert (
            window.model_metric.value_label.text()
            == "Qwen Test · STALE"
        )
        assert window.model_selector.findData("qwen-test") >= 0
        assert window.prompt_input.isEnabled() is False
        assert window.send_button.isEnabled() is False
        assert window.status_text.text() == "LOCAL / MODEL ERROR"
        assert "Model status STALE" in window.connection_detail.text()
    finally:
        window.close()
        app.processEvents()
