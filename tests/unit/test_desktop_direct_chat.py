from __future__ import annotations

import threading
import uuid
from typing import Literal

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
from athena.chat.send_identity import (
    assistant_message_id_for_operation,
    chat_id_for_operation,
)
from athena.desktop.api_controller import (
    DesktopApiController,
    DesktopApiSnapshot,
)
from athena.desktop.app import create_application
from athena.desktop.window import AthenaMainWindow

CHAT_ID = "11111111-1111-1111-1111-111111111111"

_SendOutcome = Literal[
    "success",
    "response_lost_complete",
    "response_lost_incomplete",
    "response_lost_absent",
    "response_lost_conflict",
]


def _thread(
    *,
    chat_id: str,
    operation_id: str | None,
    content: str,
    state: Literal[
        "absent",
        "incomplete",
        "complete",
        "conflict",
    ],
) -> ChatThreadResponse:
    messages: tuple[
        ChatMessageResponse,
        ...,
    ] = ()

    if state != "absent":
        if operation_id is None:
            raise AssertionError(
                "Persisted send state requires operation identity."
            )

        operation_uuid = uuid.UUID(
            operation_id
        )

        user_content = (
            "different durable content"
            if state == "conflict"
            else content
        )

        user_message = ChatMessageResponse(
            message_id=str(
                operation_uuid
            ),
            chat_id=chat_id,
            sequence_no=1,
            message_type="user",
            actor_id=(
                "33333333-3333-4333-8333-333333333333"
            ),
            created_at_us=1_777_000_000_000_000,
            revision_id=(
                "44444444-4444-4444-8444-444444444444"
            ),
            content=user_content,
            content_format="text/plain",
        )

        messages = (
            user_message,
        )

        if state in {
            "complete",
            "conflict",
        }:
            messages = (
                user_message,
                ChatMessageResponse(
                    message_id=str(
                        assistant_message_id_for_operation(
                            operation_uuid
                        )
                    ),
                    chat_id=chat_id,
                    sequence_no=2,
                    message_type="assistant",
                    actor_id=(
                        "66666666-6666-4666-8666-666666666666"
                    ),
                    created_at_us=1_777_000_001_000_000,
                    revision_id=(
                        "77777777-7777-4777-8777-777777777777"
                    ),
                    content="hello from ATHENA",
                    content_format="text/plain",
                ),
            )

    return ChatThreadResponse(
        chat_id=chat_id,
        started_at_us=1,
        ended_at_us=None,
        archive_mode="standard",
        lifecycle_state="active",
        messages=messages,
    )


class _Gateway:
    def __init__(
        self,
        *,
        send_outcome: _SendOutcome = "success",
        create_response_lost: bool = False,
    ) -> None:
        self.send_outcome = send_outcome
        self.create_response_lost = create_response_lost
        self.created: list[
            str | None
        ] = []
        self.sent: list[
            tuple[
                str,
                str,
                str | None,
            ]
        ] = []
        self.loaded: list[str] = []
        self.thread_ids: list[int] = []
        self.threads: dict[
            str,
            ChatThreadResponse,
        ] = {}

    def _record(self) -> None:
        self.thread_ids.append(
            threading.get_ident()
        )

    def health(self) -> HealthResponse:
        self._record()

        return HealthResponse(
            api_version="v1",
            core_status="ok",
            detail=None,
        )

    def provider_health(
        self,
    ) -> ProviderHealthResponse:
        self._record()

        return ProviderHealthResponse(
            provider="lm_studio",
            status="ready",
            detail=None,
        )

    def list_models(
        self,
    ) -> tuple[ModelResponse, ...]:
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

    def list_chats(
        self,
        *,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[
        ChatSummaryResponse,
        ...,
    ]:
        self._record()

        assert limit == 50
        assert offset >= 0

        return ()

    def create_chat(
        self,
        chat_id: str | None = None,
    ) -> ChatThreadResponse:
        self._record()

        resolved_chat_id = (
            CHAT_ID
            if chat_id is None
            else chat_id
        )

        self.created.append(
            chat_id
        )

        thread = _thread(
            chat_id=resolved_chat_id,
            operation_id=None,
            content="",
            state="absent",
        )

        self.threads[
            resolved_chat_id
        ] = thread

        if self.create_response_lost:
            self.create_response_lost = False

            raise CoreApiClientError(
                "create response lost",
                code="core_unavailable",
                retryable=True,
            )

        return thread

    def load_chat(
        self,
        chat_id: str,
    ) -> ChatThreadResponse:
        self._record()

        self.loaded.append(
            chat_id
        )

        thread = self.threads.get(
            chat_id
        )

        if thread is None:
            raise CoreApiClientError(
                "Chat not found.",
                status=404,
                code="chat_not_found",
                retryable=False,
            )

        return thread

    def send_chat_message(
        self,
        chat_id: str,
        *,
        content: str,
        model_id: str | None = None,
        operation_id: str | None = None,
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

        self.sent.append(
            (
                chat_id,
                content,
                operation_id,
            )
        )

        if operation_id is None:
            raise AssertionError(
                "Desktop Direct send did not provide operation identity."
            )

        state: Literal[
            "absent",
            "incomplete",
            "complete",
            "conflict",
        ]

        if self.send_outcome == "success":
            state = "complete"
        elif self.send_outcome == "response_lost_complete":
            state = "complete"
        elif self.send_outcome == "response_lost_incomplete":
            state = "incomplete"
        elif self.send_outcome == "response_lost_conflict":
            state = "conflict"
        else:
            state = "absent"

        thread = _thread(
            chat_id=chat_id,
            operation_id=operation_id,
            content=content,
            state=state,
        )

        self.threads[
            chat_id
        ] = thread

        if self.send_outcome != "success":
            raise CoreApiClientError(
                "response lost",
                code="core_unavailable",
                retryable=True,
            )

        return thread


def _app() -> QApplication:
    return create_application(
        [
            "athena-desktop-direct-chat-test",
        ]
    )


def _pool() -> QThreadPool:
    pool = QThreadPool()

    pool.setMaxThreadCount(
        1
    )

    return pool


def _ready_snapshot() -> DesktopApiSnapshot:
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


def test_controller_creates_stable_chat_and_sends_off_ui_thread() -> None:
    app = _app()
    gateway = _Gateway()
    pool = _pool()

    controller = DesktopApiController(
        gateway,
        thread_pool=pool,
    )

    sent_spy = QSignalSpy(
        controller.chat_sent
    )

    error_spy = QSignalSpy(
        controller.chat_operation_failed
    )

    main_thread = threading.get_ident()

    controller.send_message(
        chat_id=None,
        content="hello from desktop",
    )

    assert pool.waitForDone(
        2_000
    )

    app.processEvents()

    assert sent_spy.count() == 1
    assert error_spy.count() == 0
    assert len(gateway.sent) == 1

    sent_chat_id, content, operation_id = (
        gateway.sent[0]
    )

    assert content == "hello from desktop"
    assert operation_id is not None

    expected_chat_id = str(
        chat_id_for_operation(
            uuid.UUID(
                operation_id
            )
        )
    )

    assert sent_chat_id == expected_chat_id

    assert gateway.created == [
        expected_chat_id,
    ]

    assert gateway.thread_ids

    assert all(
        thread_id != main_thread
        for thread_id in gateway.thread_ids
    )


def test_controller_recovers_lost_new_chat_create_response_without_retry() -> None:
    app = _app()

    gateway = _Gateway(
        create_response_lost=True
    )

    pool = _pool()

    controller = DesktopApiController(
        gateway,
        thread_pool=pool,
    )

    sent_spy = QSignalSpy(
        controller.chat_sent
    )

    error_spy = QSignalSpy(
        controller.chat_operation_failed
    )

    controller.send_message(
        chat_id=None,
        content="hello from desktop",
    )

    assert pool.waitForDone(
        2_000
    )

    app.processEvents()

    assert sent_spy.count() == 1
    assert error_spy.count() == 0
    assert len(gateway.created) == 1
    assert len(gateway.sent) == 1

    sent_chat_id, _content, operation_id = (
        gateway.sent[0]
    )

    assert operation_id is not None

    expected_chat_id = str(
        chat_id_for_operation(
            uuid.UUID(
                operation_id
            )
        )
    )

    assert sent_chat_id == expected_chat_id

    assert gateway.created == [
        expected_chat_id,
    ]

    assert gateway.loaded == [
        expected_chat_id,
    ]


def test_controller_reconciles_complete_lost_send_as_success() -> None:
    app = _app()

    gateway = _Gateway(
        send_outcome="response_lost_complete"
    )

    pool = _pool()

    controller = DesktopApiController(
        gateway,
        thread_pool=pool,
    )

    sent_spy = QSignalSpy(
        controller.chat_sent
    )

    loaded_spy = QSignalSpy(
        controller.chat_loaded
    )

    error_spy = QSignalSpy(
        controller.chat_operation_failed
    )

    controller.send_message(
        chat_id=CHAT_ID,
        content="hello from desktop",
    )

    assert pool.waitForDone(
        2_000
    )

    app.processEvents()

    assert len(gateway.sent) == 1

    assert gateway.loaded == [
        CHAT_ID,
    ]

    assert sent_spy.count() == 1
    assert loaded_spy.count() == 0
    assert error_spy.count() == 0


def test_controller_keeps_incomplete_lost_send_fail_closed() -> None:
    app = _app()

    gateway = _Gateway(
        send_outcome="response_lost_incomplete"
    )

    pool = _pool()

    controller = DesktopApiController(
        gateway,
        thread_pool=pool,
    )

    sent_spy = QSignalSpy(
        controller.chat_sent
    )

    loaded_spy = QSignalSpy(
        controller.chat_loaded
    )

    error_spy = QSignalSpy(
        controller.chat_operation_failed
    )

    controller.send_message(
        chat_id=CHAT_ID,
        content="hello from desktop",
    )

    assert pool.waitForDone(
        2_000
    )

    app.processEvents()

    assert len(gateway.sent) == 1

    assert gateway.loaded == [
        CHAT_ID,
    ]

    assert sent_spy.count() == 0
    assert loaded_spy.count() == 1
    assert error_spy.count() == 1

    assert (
        "Automatic re-execution is blocked"
        in error_spy.at(0)[1]
    )


def test_controller_detects_conflicting_lost_send_state() -> None:
    app = _app()

    gateway = _Gateway(
        send_outcome="response_lost_conflict"
    )

    pool = _pool()

    controller = DesktopApiController(
        gateway,
        thread_pool=pool,
    )

    sent_spy = QSignalSpy(
        controller.chat_sent
    )

    error_spy = QSignalSpy(
        controller.chat_operation_failed
    )

    controller.send_message(
        chat_id=CHAT_ID,
        content="hello from desktop",
    )

    assert pool.waitForDone(
        2_000
    )

    app.processEvents()

    assert len(gateway.sent) == 1

    assert gateway.loaded == [
        CHAT_ID,
    ]

    assert sent_spy.count() == 0
    assert error_spy.count() == 1

    assert (
        "conflicting durable message identity"
        in error_spy.at(0)[1]
    )


def test_controller_absent_lost_send_does_not_retry_post() -> None:
    app = _app()

    gateway = _Gateway(
        send_outcome="response_lost_absent"
    )

    pool = _pool()

    controller = DesktopApiController(
        gateway,
        thread_pool=pool,
    )

    sent_spy = QSignalSpy(
        controller.chat_sent
    )

    error_spy = QSignalSpy(
        controller.chat_operation_failed
    )

    controller.send_message(
        chat_id=CHAT_ID,
        content="hello from desktop",
    )

    assert pool.waitForDone(
        2_000
    )

    app.processEvents()

    assert len(gateway.sent) == 1

    assert gateway.loaded == [
        CHAT_ID,
    ]

    assert sent_spy.count() == 0
    assert error_spy.count() == 1


def test_window_enables_composer_and_renders_persisted_thread() -> None:
    app = _app()
    gateway = _Gateway()
    pool = _pool()

    controller = DesktopApiController(
        gateway,
        thread_pool=pool,
    )

    window = AthenaMainWindow(
        api_controller=controller
    )

    try:
        window.apply_api_snapshot(
            _ready_snapshot()
        )

        assert (
            window.prompt_input.isEnabled()
            is True
        )

        assert (
            window.send_button.isEnabled()
            is True
        )

        window.prompt_input.setText(
            "hello from desktop"
        )

        window._submit_prompt()

        assert pool.waitForDone(
            2_000
        )

        app.processEvents()

        assert len(gateway.sent) == 1

        sent_chat_id, content, operation_id = (
            gateway.sent[0]
        )

        assert content == "hello from desktop"
        assert operation_id is not None

        assert (
            window.current_chat_id
            == sent_chat_id
        )

        assert (
            window.prompt_input.text()
            == ""
        )

        rendered = {
            label.text()
            for label
            in window.chat_messages_widget.findChildren(
                QLabel
            )
        }

        assert (
            "hello from desktop"
            in rendered
        )

        assert (
            "hello from ATHENA"
            in rendered
        )

        assert (
            window.evidence_rail.isVisible()
            is False
        )

        assert (
            "provenance"
            in window.inspector_provenance.text().casefold()
        )

    finally:
        window.close()

        assert pool.waitForDone(
            2_000
        )


def test_window_ctrl_enter_submits_direct_chat() -> None:
    app = _app()
    gateway = _Gateway()
    pool = _pool()

    controller = DesktopApiController(
        gateway,
        thread_pool=pool,
    )

    window = AthenaMainWindow(
        api_controller=controller
    )

    try:
        window.show()

        window.apply_api_snapshot(
            _ready_snapshot()
        )

        assert (
            window.prompt_input.isEnabled()
            is True
        )

        assert (
            window.send_button.isEnabled()
            is True
        )

        assert (
            window.send_button.text()
            == "SEND"
        )

        window.prompt_input.setFocus()

        window.prompt_input.setText(
            "keyboard send works"
        )

        app.processEvents()

        QTest.keyClick(
            window.prompt_input,
            Qt.Key.Key_Return,
            Qt.KeyboardModifier.ControlModifier,
        )

        assert pool.waitForDone(
            2_000
        )

        app.processEvents()

        assert len(gateway.sent) == 1

        sent_chat_id, content, operation_id = (
            gateway.sent[0]
        )

        assert content == "keyboard send works"
        assert operation_id is not None

        assert (
            window.current_chat_id
            == sent_chat_id
        )

        assert (
            window.prompt_input.text()
            == ""
        )

    finally:
        window.close()

        assert pool.waitForDone(
            2_000
        )
