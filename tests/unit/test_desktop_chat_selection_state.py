from __future__ import annotations

from PySide6.QtCore import QThreadPool
from PySide6.QtTest import QSignalSpy
from PySide6.QtWidgets import QApplication

from athena.api.contracts import (
    ChatSummaryResponse,
    ChatThreadResponse,
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

CHAT_A = "11111111-1111-1111-1111-111111111111"
CHAT_B = "22222222-2222-2222-2222-222222222222"
CHAT_C = "33333333-3333-3333-3333-333333333333"


def _app() -> QApplication:
    return create_application(
        ["athena-desktop-chat-selection-test"]
    )


def _thread(chat_id: str) -> ChatThreadResponse:
    return ChatThreadResponse(
        chat_id=chat_id,
        started_at_us=1,
        ended_at_us=None,
        archive_mode="standard",
        lifecycle_state="active",
        messages=(),
    )


def _summary(
    chat_id: str,
    *,
    message_count: int = 1,
) -> ChatSummaryResponse:
    return ChatSummaryResponse(
        chat_id=chat_id,
        started_at_us=1,
        ended_at_us=None,
        archive_mode="standard",
        lifecycle_state="active",
        message_count=message_count,
    )


def _snapshot(
    *chat_ids: str,
    chat_error: str | None = None,
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
        models=(
            ModelResponse(
                provider="lm_studio",
                backend_model_id="test-model",
                display_name="Test Model",
                model_type="llm",
                context_capacity=32_768,
                quantization=None,
                loaded=True,
                vision=False,
                trained_for_tool_use=False,
                loaded_context_length=32_768,
            ),
        ),
        chats=tuple(
            _summary(chat_id)
            for chat_id in chat_ids
        ),
        chat_error=chat_error,
    )


class _WindowController:
    def __init__(self) -> None:
        self.loads: list[str] = []
        self.direct_sends: list[tuple[str | None, str]] = []

    def load_chat(
        self,
        chat_id: str,
    ) -> None:
        self.loads.append(chat_id)

    def send_message(
        self,
        *,
        chat_id: str | None,
        content: str,
        **_kwargs: object,
    ) -> None:
        self.direct_sends.append(
            (chat_id, content)
        )


def _window_with_two_chats() -> tuple[
    QApplication,
    AthenaMainWindow,
    _WindowController,
]:
    app = _app()

    window = AthenaMainWindow(
        api_controller=None
    )

    controller = _WindowController()
    window.api_controller = controller  # type: ignore[assignment]

    window.apply_api_snapshot(
        _snapshot(
            CHAT_A,
            CHAT_B,
        )
    )

    window.apply_chat_loaded(
        _thread(CHAT_A)
    )

    return app, window, controller


def _select_chat(
    window: AthenaMainWindow,
    chat_id: str,
) -> None:
    index = window.chat_selector.findData(
        chat_id
    )

    assert index >= 0

    window.chat_selector.setCurrentIndex(
        index
    )

    window._on_chat_selected(
        index
    )


def test_selected_chat_is_pending_until_load_commits() -> None:
    app, window, controller = (
        _window_with_two_chats()
    )

    try:
        assert window.current_chat_id == CHAT_A
        assert window.loaded_chat_id == CHAT_A
        assert window.selected_chat_id == CHAT_A
        assert window.pending_chat_id is None

        _select_chat(
            window,
            CHAT_B,
        )

        assert controller.loads == [CHAT_B]
        assert window.current_chat_id == CHAT_A
        assert window.loaded_chat_id == CHAT_A
        assert window.selected_chat_id == CHAT_B
        assert window.pending_chat_id == CHAT_B
        assert window.chat_selector.currentData() == CHAT_B

        window.apply_chat_loaded(
            _thread(CHAT_B)
        )

        assert window.current_chat_id == CHAT_B
        assert window.loaded_chat_id == CHAT_B
        assert window.selected_chat_id == CHAT_B
        assert window.pending_chat_id is None
        assert window.chat_selector.currentData() == CHAT_B
    finally:
        window.close()
        app.processEvents()


def test_failed_chat_load_rolls_selector_back() -> None:
    app, window, controller = (
        _window_with_two_chats()
    )

    try:
        _select_chat(
            window,
            CHAT_B,
        )

        assert controller.loads == [CHAT_B]
        assert window.pending_chat_id == CHAT_B
        assert window.chat_selector.currentData() == CHAT_B

        window.apply_chat_operation_failure(
            "load",
            "synthetic failure",
        )

        assert window.current_chat_id == CHAT_A
        assert window.loaded_chat_id == CHAT_A
        assert window.selected_chat_id == CHAT_A
        assert window.pending_chat_id is None
        assert window.chat_selector.currentData() == CHAT_A

        assert (
            window.inspector_heading.text()
            == "Chat loading failed"
        )
    finally:
        window.close()
        app.processEvents()


def test_snapshot_during_pending_load_preserves_intent() -> None:
    app, window, controller = (
        _window_with_two_chats()
    )

    try:
        _select_chat(
            window,
            CHAT_B,
        )

        assert controller.loads == [CHAT_B]

        window.apply_api_snapshot(
            _snapshot(
                CHAT_A,
                CHAT_B,
                CHAT_C,
            )
        )

        assert window.current_chat_id == CHAT_A
        assert window.loaded_chat_id == CHAT_A
        assert window.selected_chat_id == CHAT_B
        assert window.pending_chat_id == CHAT_B
        assert window.chat_selector.currentData() == CHAT_B
    finally:
        window.close()
        app.processEvents()


def test_snapshot_missing_loaded_chat_does_not_claim_new_chat() -> None:
    app, window, _controller = (
        _window_with_two_chats()
    )

    try:
        window.apply_api_snapshot(
            _snapshot(
                CHAT_B,
                CHAT_C,
            )
        )

        assert window.current_chat_id == CHAT_A
        assert window.loaded_chat_id == CHAT_A
        assert window.selected_chat_id == CHAT_A
        assert window.pending_chat_id is None
        assert window.chat_selector.currentData() == CHAT_A

        index = window.chat_selector.findData(
            CHAT_A
        )

        assert index >= 0
        assert "CURRENT" in window.chat_selector.itemText(
            index
        )
    finally:
        window.close()
        app.processEvents()


def test_chat_list_failure_preserves_loaded_chat() -> None:
    app, window, _controller = (
        _window_with_two_chats()
    )

    try:
        window.apply_api_snapshot(
            _snapshot(
                chat_error="Chat list unavailable.",
            )
        )

        assert window.current_chat_id == CHAT_A
        assert window.loaded_chat_id == CHAT_A
        assert window.selected_chat_id == CHAT_A
        assert window.pending_chat_id is None
        assert window.chat_selector.currentData() == CHAT_A
    finally:
        window.close()
        app.processEvents()


def test_snapshot_does_not_cancel_pending_load_from_new_chat() -> None:
    app = _app()

    window = AthenaMainWindow(
        api_controller=None
    )

    controller = _WindowController()
    window.api_controller = controller  # type: ignore[assignment]

    try:
        window.apply_api_snapshot(
            _snapshot(
                CHAT_A,
                CHAT_B,
            )
        )

        assert window.current_chat_id is None
        assert window.loaded_chat_id is None
        assert window.pending_chat_id is None

        _select_chat(
            window,
            CHAT_B,
        )

        assert window.current_chat_id is None
        assert window.loaded_chat_id is None
        assert window.selected_chat_id == CHAT_B
        assert window.pending_chat_id == CHAT_B

        window.apply_api_snapshot(
            _snapshot(
                CHAT_A,
                CHAT_B,
            )
        )

        assert window.current_chat_id is None
        assert window.loaded_chat_id is None
        assert window.selected_chat_id == CHAT_B
        assert window.pending_chat_id == CHAT_B
        assert window.chat_selector.currentData() == CHAT_B
    finally:
        window.close()
        app.processEvents()


def test_new_chat_clears_all_chat_selection_identities() -> None:
    app, window, _controller = (
        _window_with_two_chats()
    )

    try:
        index = window.chat_selector.findData(
            None
        )

        assert index >= 0

        window.chat_selector.setCurrentIndex(
            index
        )

        window._on_chat_selected(
            index
        )

        assert window.current_chat_id is None
        assert window.loaded_chat_id is None
        assert window.selected_chat_id is None
        assert window.pending_chat_id is None
        assert window.chat_selector.currentData() is None
    finally:
        window.close()
        app.processEvents()


def test_stale_mismatched_loaded_signal_does_not_commit_switch() -> None:
    app, window, controller = (
        _window_with_two_chats()
    )

    try:
        _select_chat(
            window,
            CHAT_B,
        )

        assert controller.loads == [CHAT_B]
        assert window.pending_chat_id == CHAT_B

        window.apply_chat_loaded(
            _thread(CHAT_C)
        )

        assert window.current_chat_id == CHAT_A
        assert window.loaded_chat_id == CHAT_A
        assert window.selected_chat_id == CHAT_B
        assert window.pending_chat_id == CHAT_B
        assert window.chat_selector.currentData() == CHAT_B
    finally:
        window.close()
        app.processEvents()


def test_successful_send_commits_new_chat_identity() -> None:
    app = _app()

    window = AthenaMainWindow(
        api_controller=None
    )

    try:
        window.apply_chat_sent(
            _thread(CHAT_C)
        )

        assert window.current_chat_id == CHAT_C
        assert window.loaded_chat_id == CHAT_C
        assert window.selected_chat_id == CHAT_C
        assert window.pending_chat_id is None
        assert window.chat_selector.currentData() == CHAT_C
    finally:
        window.close()
        app.processEvents()


def test_pending_switch_blocks_composer_and_direct_submit() -> None:
    app, window, controller = (
        _window_with_two_chats()
    )

    try:
        assert window.prompt_input.isEnabled() is True

        _select_chat(
            window,
            CHAT_B,
        )

        assert window.pending_chat_id == CHAT_B
        assert window.prompt_input.isEnabled() is False
        assert window.send_button.isEnabled() is False
        assert window.chat_selector.isEnabled() is False
        assert window.new_chat_button.isEnabled() is False

        window.prompt_input.setText(
            "must not send to A or B while switch is pending"
        )
        window._submit_prompt()

        assert controller.direct_sends == []
    finally:
        window.close()
        app.processEvents()


class _MismatchedLoadGateway:
    def load_chat(
        self,
        _chat_id: str,
    ) -> ChatThreadResponse:
        return _thread(CHAT_C)


def test_controller_rejects_mismatched_chat_load_result() -> None:
    app = _app()

    pool = QThreadPool()
    pool.setMaxThreadCount(1)

    controller = DesktopApiController(
        _MismatchedLoadGateway(),  # type: ignore[arg-type]
        thread_pool=pool,
    )

    loaded_spy = QSignalSpy(
        controller.chat_loaded
    )

    failed_spy = QSignalSpy(
        controller.chat_operation_failed
    )

    controller.load_chat(
        CHAT_B
    )

    assert pool.waitForDone(
        2_000
    )

    app.processEvents()

    assert loaded_spy.count() == 0
    assert failed_spy.count() == 1

    failure = failed_spy.at(0)

    assert failure[0] == "load"
    assert failure[1] == "ATHENA chat operation failed."

    assert pool.waitForDone(
        2_000
    )
