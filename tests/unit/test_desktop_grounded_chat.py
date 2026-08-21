from __future__ import annotations

import threading

from PySide6.QtCore import QThreadPool
from PySide6.QtTest import QSignalSpy
from PySide6.QtWidgets import QApplication, QLabel, QPushButton

from athena.api.client import CoreApiClientError
from athena.api.contracts import (
    ChatMessageResponse,
    ChatSummaryResponse,
    ChatThreadResponse,
    GroundedChatResponse,
    GroundedEvidenceResponse,
    GroundedMemoryResponse,
    GroundingResponse,
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

CHAT_ID = "11111111-1111-1111-1111-111111111111"


def _thread() -> ChatThreadResponse:
    return ChatThreadResponse(
        chat_id=CHAT_ID,
        started_at_us=1,
        ended_at_us=None,
        archive_mode="standard",
        lifecycle_state="active",
        messages=(
            ChatMessageResponse(
                message_id="22222222-2222-2222-2222-222222222222",
                chat_id=CHAT_ID,
                sequence_no=1,
                message_type="user",
                actor_id="33333333-3333-3333-3333-333333333333",
                created_at_us=1_777_000_000_000_000,
                revision_id="44444444-4444-4444-4444-444444444444",
                content="ground this",
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
                content=(
                    "grounded answer [CTX-001] "
                    "[SOURCE:CTX-002]"
                ),
                content_format="text/plain",
            ),
        ),
    )


def _grounded() -> GroundedChatResponse:
    return GroundedChatResponse(
        thread=_thread(),
        assistant_text=(
            "grounded answer [CTX-001] [SOURCE:CTX-002]"
        ),
        evidence=(
            GroundedEvidenceResponse(
                context_id="CTX-001",
                evidence_class="canonical",
                entity_type="knowledge",
                entity_id="88888888-8888-8888-8888-888888888888",
                revision_id="99999999-9999-9999-9999-999999999999",
                title="Stored fact",
                text="A canonical local fact.",
                cited=True,
                epistemic_status="asserted",
                source_id=None,
                representation_id=None,
                source_name=None,
                source_uri=None,
                start_offset=None,
                end_offset=None,
                page_start=None,
                page_end=None,
                quoted_sha256=None,
                truncated=False,
            ),
            GroundedEvidenceResponse(
                context_id="CTX-002",
                evidence_class="source",
                entity_type="source_anchor",
                entity_id="aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
                revision_id=None,
                title="source.pdf",
                text="Exact retained source excerpt.",
                cited=True,
                epistemic_status=None,
                source_id="bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb",
                representation_id=(
                    "cccccccc-cccc-cccc-cccc-cccccccccccc"
                ),
                source_name="source.pdf",
                source_uri="file:///source.pdf",
                start_offset=120,
                end_offset=149,
                page_start=3,
                page_end=3,
                quoted_sha256="ab" * 32,
                truncated=False,
            ),
        ),
        personal_memory=(
            GroundedMemoryResponse(
                context_id="MEM-001",
                memory_id="dddddddd-dddd-dddd-dddd-dddddddddddd",
                revision_id="eeeeeeee-eeee-eeee-eeee-eeeeeeeeeeee",
                memory_kind="preference",
                scope_kind="global",
                scope_entity_id=None,
                content="Prefer concise answers.",
            ),
        ),
        grounding=GroundingResponse(
            cited_context_ids=("CTX-001", "CTX-002"),
            canonical_context_ids=("CTX-001",),
            user_statement_context_ids=(),
            conversation_context_ids=(),
            source_context_ids=("CTX-002",),
            research_context_ids=(),
            news_context_ids=(),
            invalid_context_ids=(),
            uses_inference=False,
            uses_model_prior=False,
            uses_unknown=False,
            has_provenance_marker=True,
        ),
        processing_run_id="ffffffff-ffff-ffff-ffff-ffffffffffff",
        model_id="qwen-test",
        embedding_model_id="embed-test",
    )


class _Gateway:
    def __init__(self, *, fail_grounded: bool = False) -> None:
        self.fail_grounded = fail_grounded
        self.created = 0
        self.direct_sent: list[tuple[str, str]] = []
        self.grounded_sent: list[tuple[str, str]] = []
        self.loaded: list[str] = []
        self.thread_ids: list[int] = []

    def _record(self) -> None:
        self.thread_ids.append(threading.get_ident())

    def health(self) -> HealthResponse:
        self._record()
        return HealthResponse(
            api_version="v1",
            core_status="ok",
            detail=None,
        )

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

    def list_chats(
        self,
        *,
        limit: int = 50,
    ) -> tuple[ChatSummaryResponse, ...]:
        self._record()
        assert limit == 50
        return ()

    def create_chat(self) -> ChatThreadResponse:
        self._record()
        self.created += 1
        return ChatThreadResponse(
            chat_id=CHAT_ID,
            started_at_us=1,
            ended_at_us=None,
            archive_mode="standard",
            lifecycle_state="active",
            messages=(),
        )

    def load_chat(self, chat_id: str) -> ChatThreadResponse:
        self._record()
        self.loaded.append(chat_id)
        return _thread()

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
        self.direct_sent.append((chat_id, content))
        return _thread()
    def send_unified_local_chat_message(
        self,
        chat_id: str,
        *,
        content: str,
        model_id: str | None = None,
        embedding_model_id: str | None = None,
        effective_context_limit: int | None = None,
        max_output_tokens: int | None = None,
        temperature: float | None = None,
        thinking_enabled: bool | None = None,
    ) -> GroundedChatResponse:
        self._record()
        del (
            model_id,
            embedding_model_id,
            effective_context_limit,
            max_output_tokens,
            temperature,
            thinking_enabled,
        )
        self.grounded_sent.append((chat_id, content))
        if self.fail_grounded:
            raise CoreApiClientError(
                "response lost",
                code="core_unavailable",
                retryable=True,
            )
        return _grounded()

def _app() -> QApplication:
    return create_application(
        ["athena-desktop-grounded-chat-test"]
    )


def _pool() -> QThreadPool:
    pool = QThreadPool()
    pool.setMaxThreadCount(1)
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


def test_controller_sends_grounded_chat_off_ui_thread() -> None:
    app = _app()
    gateway = _Gateway()
    pool = _pool()
    controller = DesktopApiController(
        gateway,
        thread_pool=pool,
    )
    spy = QSignalSpy(controller.grounded_chat_sent)
    main_thread = threading.get_ident()

    controller.send_grounded_message(
        chat_id=None,
        content="ground this",
    )

    assert pool.waitForDone(2_000)
    app.processEvents()

    assert spy.count() == 1
    assert gateway.created == 1
    assert gateway.grounded_sent == [(CHAT_ID, "ground this")]
    assert gateway.direct_sent == []
    assert gateway.thread_ids
    assert all(
        thread_id != main_thread
        for thread_id in gateway.thread_ids
    )


def test_controller_reconciles_grounded_failure_without_retry() -> None:
    app = _app()
    gateway = _Gateway(fail_grounded=True)
    pool = _pool()
    controller = DesktopApiController(
        gateway,
        thread_pool=pool,
    )
    error_spy = QSignalSpy(
        controller.chat_operation_failed
    )
    loaded_spy = QSignalSpy(controller.chat_loaded)
    signal_order: list[str] = []
    controller.chat_loaded.connect(
        lambda _thread: signal_order.append("loaded")
    )
    controller.chat_operation_failed.connect(
        lambda _operation, _message: signal_order.append("error")
    )

    controller.send_grounded_message(
        chat_id=CHAT_ID,
        content="ground this",
    )

    assert pool.waitForDone(2_000)
    app.processEvents()

    assert gateway.grounded_sent == [(CHAT_ID, "ground this")]
    assert gateway.loaded == [CHAT_ID]
    assert error_spy.count() == 1
    assert loaded_spy.count() == 1
    assert signal_order == ["loaded", "error"]


def test_window_ground_toggle_renders_real_evidence() -> None:
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
        window.apply_api_snapshot(_ready_snapshot())

        assert window.ground_button.isEnabled() is True
        assert window.ground_button.isChecked() is False

        window.ground_button.setChecked(True)
        window.prompt_input.setText("ground this")
        window._submit_prompt()

        assert pool.waitForDone(2_000)
        app.processEvents()

        assert gateway.direct_sent == []
        assert gateway.grounded_sent == [(CHAT_ID, "ground this")]
        assert window.current_chat_id == CHAT_ID
        assert window.prompt_input.text() == ""
        assert window.inspector_mode.value_label.text() == (
            "GROUNDED LOCAL"
        )

        inspector = window.inspector_provenance.text()
        assert "CTX-001" in inspector
        assert "CANONICAL / KNOWLEDGE" in inspector
        assert "STATUS  ASSERTED" in inspector
        assert "CTX-002" in inspector
        assert "SOURCE / SOURCE_ANCHOR" in inspector
        assert "source.pdf" in inspector
        assert "PERSONAL MEMORY / CONTEXT ONLY" in inspector
        assert "Not promoted to factual evidence." in inspector

        chain = window.evidence_chain_state.text()
        assert chain.startswith("GROUND / 2 CITED")
        assert "CANONICAL 1" in chain
        assert "SOURCE 1" in chain
        assert "MEMORY 1" in chain

        rendered = {
            label.text()
            for label in window.chat_messages_widget.findChildren(
                QLabel
            )
        }
        assert (
            "grounded answer [CTX-001] [SOURCE:CTX-002]"
            in rendered
        )
        assert all(
            "ATHENA_PROVENANCE" not in text
            for text in rendered
        )
        assert window.evidence_rail.isVisible() is False
    finally:
        window.close()
        assert pool.waitForDone(2_000)


def test_controller_grounded_send_is_single_flight() -> None:
    app = _app()
    gateway = _Gateway()
    pool = _pool()
    controller = DesktopApiController(
        gateway,
        thread_pool=pool,
    )

    controller.send_grounded_message(
        chat_id=CHAT_ID,
        content="first",
    )
    controller.send_grounded_message(
        chat_id=CHAT_ID,
        content="second",
    )

    assert pool.waitForDone(2_000)
    app.processEvents()

    assert gateway.grounded_sent == [(CHAT_ID, "first")]
    assert controller.chat_busy is False


def test_window_grounded_failure_is_visible_and_not_persisted() -> None:
    app = _app()
    gateway = _Gateway(fail_grounded=True)
    pool = _pool()
    controller = DesktopApiController(
        gateway,
        thread_pool=pool,
    )
    window = AthenaMainWindow(api_controller=controller)

    try:
        window.apply_api_snapshot(_ready_snapshot())
        window.ground_button.setChecked(True)
        window.prompt_input.setText("ground this")
        window._submit_prompt()

        assert pool.waitForDone(2_000)
        app.processEvents()

        assert gateway.grounded_sent == [(CHAT_ID, "ground this")]
        assert gateway.loaded == [CHAT_ID]
        assert window.inspector_object_id.text() == "CHAT / ERROR"
        assert window.inspector_heading.text() == "Grounded chat failed"

        rendered = [
            label.text()
            for label in window.chat_messages_widget.findChildren(
                QLabel
            )
        ]
        assert any(
            "NO ASSISTANT MESSAGE PERSISTED" in text
            for text in rendered
        )
        assert any("response lost" in text for text in rendered)
        assert all(
            "ATHENA_PROVENANCE" not in text
            for text in rendered
        )
    finally:
        window.close()
        assert pool.waitForDone(2_000)


def test_chat_scroll_tail_follow_respects_manual_scroll() -> None:
    app = _app()
    window = AthenaMainWindow()

    try:
        window.show()
        window.resize(1320, 780)
        window.chat_messages_widget.setMinimumHeight(4_000)
        window._schedule_chat_tail_follow(force=True)
        app.processEvents()

        bar = window.chat_scroll.verticalScrollBar()
        assert bar.maximum() > 0
        assert bar.value() == bar.maximum()

        bar.setValue(0)
        app.processEvents()
        assert window._chat_follow_tail is False

        previous_value = bar.value()
        window.chat_messages_widget.setMinimumHeight(5_000)
        app.processEvents()

        assert bar.value() == previous_value
        assert window._chat_follow_tail is False

        window._schedule_chat_tail_follow(force=True)
        app.processEvents()

        assert bar.value() == bar.maximum()
        assert window._chat_follow_tail is True
    finally:
        window.close()


def test_inspector_provenance_has_working_scrollbar() -> None:
    app = _app()
    window = AthenaMainWindow()

    try:
        window.show()
        window.resize(1320, 780)
        window.inspector_provenance.setText(
            "\n".join(
                f"CTX-{index:03d}  CANONICAL / KNOWLEDGE  CONTEXT"
                for index in range(1, 180)
            )
        )
        for _ in range(5):
            app.processEvents()

        bar = window.inspector_scroll.verticalScrollBar()
        assert window.inspector_scroll.isVisible() is True
        assert bar.maximum() > 0

        bar.setValue(bar.maximum())
        app.processEvents()

        assert bar.value() == bar.maximum()
    finally:
        window.close()


def test_each_chat_message_has_one_click_copy_button() -> None:
    app = _app()
    window = AthenaMainWindow()

    try:
        window._render_chat_thread(_thread())
        app.processEvents()

        buttons = window.chat_messages_widget.findChildren(
            QPushButton,
            "copyMessageButton",
        )
        assert len(buttons) == 2

        by_sequence = {
            int(button.property("messageSequence")): button
            for button in buttons
        }
        assert set(by_sequence) == {1, 2}

        by_sequence[1].click()
        assert QApplication.clipboard().text() == "ground this"

        by_sequence[2].click()
        assert QApplication.clipboard().text() == (
            "grounded answer [CTX-001] [SOURCE:CTX-002]"
        )
    finally:
        window.close()


def test_chat_message_body_expands_to_full_wrapped_height() -> None:
    app = _app()
    window = AthenaMainWindow()

    long_answer = (
        "ATHENA speichert widersprüchliche Aussagen zur Hauptstadt "
        "Deutschlands. Berlin und München stehen als getrennte lokale "
        "Behauptungen im aktuellen Kontext. "
        * 16
    )

    try:
        window.show()
        window.resize(1680, 960)

        widget = window._message_widget(
            role="assistant",
            content=long_answer,
            created_at_us=1_700_000_000_000_000,
            sequence_no=999,
            message_id="33333333-3333-3333-3333-333333333333",
            revision_id="44444444-4444-4444-4444-444444444444",
        )
        insert_index = max(
            0,
            window.chat_messages_layout.count() - 1,
        )
        window.chat_messages_layout.insertWidget(
            insert_index,
            widget,
        )

        for _ in range(12):
            app.processEvents()

        bodies = [
            label
            for label in widget.findChildren(QLabel)
            if label.objectName() == "message"
        ]
        assert len(bodies) == 1
        body = bodies[0]
        assert body.maximumWidth() > 860

        required_height = body.heightForWidth(body.width())
        assert required_height > 0
        assert body.minimumHeight() == required_height
        assert body.height() + 2 >= required_height

        window.resize(1240, 820)
        for _ in range(12):
            app.processEvents()

        required_after_resize = body.heightForWidth(body.width())
        assert required_after_resize > 0
        assert body.minimumHeight() == required_after_resize
        assert body.height() + 2 >= required_after_resize
    finally:
        window.close()
