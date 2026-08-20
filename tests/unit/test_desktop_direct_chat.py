from __future__ import annotations

import threading

from PySide6.QtCore import Qt, QThreadPool
from PySide6.QtTest import QSignalSpy, QTest
from PySide6.QtWidgets import QApplication, QLabel

from athena.api.client import CoreApiClientError
from athena.api.contracts import (
    ChatMessageResponse,
    ChatSummaryResponse,
    ChatThreadResponse,
    HealthResponse,
    ModelResponse,
    ProviderHealthResponse,
)
from athena.desktop.api_controller import DesktopApiController, DesktopApiSnapshot
from athena.desktop.app import create_application
from athena.desktop.window import AthenaMainWindow

CHAT_ID = "11111111-1111-1111-1111-111111111111"


def _thread(*, with_messages: bool = True) -> ChatThreadResponse:
    messages: tuple[ChatMessageResponse, ...] = ()
    if with_messages:
        messages = (
            ChatMessageResponse(
                message_id="22222222-2222-2222-2222-222222222222",
                chat_id=CHAT_ID,
                sequence_no=1,
                message_type="user",
                actor_id="33333333-3333-3333-3333-333333333333",
                created_at_us=1_777_000_000_000_000,
                revision_id="44444444-4444-4444-4444-444444444444",
                content="hello from desktop",
                content_format="text/plain",
            ),
            ChatMessageResponse(
                message_id="55555555-5555-5555-5555-555555555555",
                chat_id=CHAT_ID,
                sequence_no=2,
                message_type="assistant",
                actor_id="66666666-6666-6666-6666-666666666666",
                created_at_us=1_777_000_001_000_000,
                revision_id="77777777-7777-7777-7777-777777777777",
                content="hello from ATHENA",
                content_format="text/plain",
            ),
        )
    return ChatThreadResponse(
        chat_id=CHAT_ID,
        started_at_us=1,
        ended_at_us=None,
        archive_mode="standard",
        lifecycle_state="active",
        messages=messages,
    )


class _Gateway:
    def __init__(self, *, fail_send: bool = False) -> None:
        self.fail_send = fail_send
        self.created = 0
        self.sent: list[tuple[str, str]] = []
        self.loaded: list[str] = []
        self.thread_ids: list[int] = []

    def _record(self) -> None:
        self.thread_ids.append(threading.get_ident())

    def health(self) -> HealthResponse:
        self._record()
        return HealthResponse(api_version="v1", core_status="ok", detail=None)

    def provider_health(self) -> ProviderHealthResponse:
        self._record()
        return ProviderHealthResponse(
            provider="lm_studio",
            status="ready",
            detail=None,
        )

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
        assert limit == 50
        return ()

    def create_chat(self) -> ChatThreadResponse:
        self._record()
        self.created += 1
        return _thread(with_messages=False)

    def load_chat(self, chat_id: str) -> ChatThreadResponse:
        self._record()
        self.loaded.append(chat_id)
        return _thread(with_messages=False)

    def send_chat_message(
        self,
        chat_id: str,
        *,
        content: str,
        model_id: str | None = None,
        effective_context_limit: int | None = None,
        max_output_tokens: int | None = None,
        temperature: float | None = None,
        thinking_enabled: bool | None = None,
    ) -> ChatThreadResponse:
        self._record()
        del (
            model_id,
            effective_context_limit,
            max_output_tokens,
            temperature,
            thinking_enabled,
        )
        self.sent.append((chat_id, content))
        if self.fail_send:
            raise CoreApiClientError(
                "response lost",
                code="core_unavailable",
                retryable=True,
            )
        return _thread(with_messages=True)

def _app() -> QApplication:
    return create_application(["athena-desktop-direct-chat-test"])


def _pool() -> QThreadPool:
    pool = QThreadPool()
    pool.setMaxThreadCount(1)
    return pool


def _ready_snapshot() -> DesktopApiSnapshot:
    return DesktopApiSnapshot(
        health=HealthResponse(api_version="v1", core_status="ok", detail=None),
        provider=ProviderHealthResponse(
            provider="lm_studio",
            status="ready",
            detail=None,
        ),
        models=(
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
        ),
        chats=(),
    )


def test_controller_creates_and_sends_direct_chat_off_ui_thread() -> None:
    app = _app()
    gateway = _Gateway()
    pool = _pool()
    controller = DesktopApiController(gateway, thread_pool=pool)
    sent_spy = QSignalSpy(controller.chat_sent)
    main_thread = threading.get_ident()

    controller.send_message(chat_id=None, content="hello from desktop")

    assert pool.waitForDone(2_000)
    app.processEvents()

    assert sent_spy.count() == 1
    assert gateway.created == 1
    assert gateway.sent == [(CHAT_ID, "hello from desktop")]
    assert gateway.thread_ids
    assert all(thread_id != main_thread for thread_id in gateway.thread_ids)


def test_controller_reconciles_ambiguous_send_without_retrying_mutation() -> None:
    app = _app()
    gateway = _Gateway(fail_send=True)
    pool = _pool()
    controller = DesktopApiController(gateway, thread_pool=pool)
    error_spy = QSignalSpy(controller.chat_operation_failed)
    loaded_spy = QSignalSpy(controller.chat_loaded)

    controller.send_message(chat_id=CHAT_ID, content="hello from desktop")

    assert pool.waitForDone(2_000)
    app.processEvents()

    assert gateway.sent == [(CHAT_ID, "hello from desktop")]
    assert gateway.loaded == [CHAT_ID]
    assert error_spy.count() == 1
    assert loaded_spy.count() == 1


def test_window_enables_composer_and_renders_persisted_thread() -> None:
    app = _app()
    gateway = _Gateway()
    pool = _pool()
    controller = DesktopApiController(gateway, thread_pool=pool)
    window = AthenaMainWindow(api_controller=controller)

    try:
        window.apply_api_snapshot(_ready_snapshot())

        assert window.prompt_input.isEnabled() is True
        assert window.send_button.isEnabled() is True

        window.prompt_input.setText("hello from desktop")
        window._submit_prompt()

        assert pool.waitForDone(2_000)
        app.processEvents()

        assert gateway.sent == [(CHAT_ID, "hello from desktop")]
        assert window.current_chat_id == CHAT_ID
        assert window.prompt_input.text() == ""

        rendered = {
            label.text()
            for label in window.chat_messages_widget.findChildren(QLabel)
        }
        assert "hello from desktop" in rendered
        assert "hello from ATHENA" in rendered
        assert window.evidence_rail.isVisible() is False
        assert "provenance" in window.inspector_provenance.text().casefold()
    finally:
        window.close()
        assert pool.waitForDone(2_000)


def test_window_ctrl_enter_submits_direct_chat() -> None:
    app = _app()
    gateway = _Gateway()
    pool = _pool()
    controller = DesktopApiController(
        gateway,
        thread_pool=pool,
    )
    window = AthenaMainWindow(api_controller=controller)

    try:
        window.show()
        window.apply_api_snapshot(_ready_snapshot())

        assert window.prompt_input.isEnabled() is True
        assert window.send_button.isEnabled() is True
        assert window.send_button.text() == "SEND"

        window.prompt_input.setFocus()
        window.prompt_input.setText("keyboard send works")
        app.processEvents()

        QTest.keyClick(
            window.prompt_input,
            Qt.Key.Key_Return,
            Qt.KeyboardModifier.ControlModifier,
        )

        assert pool.waitForDone(2_000)
        app.processEvents()

        assert gateway.sent == [
            (CHAT_ID, "keyboard send works"),
        ]
        assert window.prompt_input.text() == ""
    finally:
        window.close()
        assert pool.waitForDone(2_000)
