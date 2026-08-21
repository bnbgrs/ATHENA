from __future__ import annotations

import inspect

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QApplication, QLabel, QPushButton

from athena.api.contracts import (
    HealthResponse,
    ModelResponse,
    ProviderHealthResponse,
)
from athena.desktop.api_controller import DesktopApiSnapshot
from athena.desktop.window import AthenaMainWindow


def _model(
    model_id: str,
    *,
    loaded: bool,
    context: int = 65_536,
    model_type: str = "llm",
) -> ModelResponse:
    return ModelResponse(
        provider="lm_studio",
        backend_model_id=model_id,
        display_name=model_id,
        model_type=model_type,
        context_capacity=context,
        quantization="Q4",
        loaded=loaded,
        vision=False,
        trained_for_tool_use=True,
        loaded_context_length=context if loaded else None,
    )


def _snapshot() -> DesktopApiSnapshot:
    return DesktopApiSnapshot(
        health=HealthResponse(api_version="v1", core_status="ok", detail=None),
        provider=ProviderHealthResponse(
            provider="lm_studio",
            status="ready",
            detail=None,
        ),
        models=(
            _model("loaded-llm", loaded=True),
            _model("available-llm", loaded=False),
            _model(
                "embedding",
                loaded=True,
                context=8192,
                model_type="embedding",
            ),
        ),
        chats=(),
    )


def _app() -> QApplication:
    return QApplication.instance() or QApplication([])


def test_loaded_model_is_visually_green_and_available_model_is_not() -> None:
    app = _app()
    window = AthenaMainWindow(api_controller=None)
    try:
        window.apply_api_snapshot(_snapshot())
        loaded = window.model_selector.findData("loaded-llm")
        available = window.model_selector.findData("available-llm")
        assert loaded >= 0
        assert available >= 0

        loaded_color = window.model_selector.itemData(
            loaded,
            Qt.ItemDataRole.ForegroundRole,
        )
        available_color = window.model_selector.itemData(
            available,
            Qt.ItemDataRole.ForegroundRole,
        )
        assert isinstance(loaded_color, QColor)
        assert loaded_color.name().upper() == "#63D98B"
        assert isinstance(available_color, QColor)
        assert available_color.name().upper() != "#63D98B"
    finally:
        window.close()
        app.processEvents()


def test_ctx_slider_and_numeric_entry_stay_synchronized() -> None:
    app = _app()
    window = AthenaMainWindow(api_controller=None)
    try:
        window.apply_api_snapshot(_snapshot())
        assert window.context_slider.maximum() == 65_536
        assert window.context_spin.maximum() == 65_536
        assert window.context_slider.value() == window.context_spin.value()

        window.context_spin.setValue(49_152)
        assert window.context_slider.value() == 49_152
        assert window._effective_context_limit() == 49_152

        window.context_slider.setValue(32_768)
        assert window.context_spin.value() == 32_768
        assert window._effective_context_limit() == 32_768
    finally:
        window.close()
        app.processEvents()


def test_max_output_uses_full_context_budget_and_supports_precise_entry() -> None:
    app = _app()
    window = AthenaMainWindow(api_controller=None)
    try:
        window.apply_api_snapshot(_snapshot())
        expected_max = 65_536 - 256
        assert window.max_output_spin.maximum() == expected_max
        assert window.max_output_slider.maximum() == expected_max

        window.max_output_spin.setValue(32_768)
        assert window.max_output_slider.value() == 32_768
        assert window._max_output_tokens() == 32_768

        window.max_output_slider.setValue(24_576)
        assert window.max_output_spin.value() == 24_576
        assert window._max_output_tokens() == 24_576

        window.context_spin.setValue(16_384)
        assert window.max_output_spin.maximum() == 16_384 - 256
        assert window.max_output_slider.maximum() == 16_384 - 256
        assert window.max_output_spin.value() <= 16_384 - 256
    finally:
        window.close()
        app.processEvents()


def test_thinking_state_is_textually_unambiguous() -> None:
    app = _app()
    window = AthenaMainWindow(api_controller=None)
    try:
        window.apply_api_snapshot(_snapshot())
        assert window.thinking_checkbox.isChecked() is False
        assert "OFF" in window.thinking_checkbox.text()
        assert "DISABLED" in window.thinking_checkbox.text()

        window.thinking_checkbox.setChecked(True)
        assert "ON" in window.thinking_checkbox.text()
        assert "ALLOWED" in window.thinking_checkbox.text()
        assert window._thinking_enabled() is True
    finally:
        window.close()
        app.processEvents()


def test_chat_and_inspector_text_support_mouse_and_keyboard_selection() -> None:
    app = _app()
    window = AthenaMainWindow(api_controller=None)
    try:
        window.apply_api_snapshot(_snapshot())

        flags = window.inspector_provenance.textInteractionFlags()
        assert flags & Qt.TextInteractionFlag.TextSelectableByMouse
        assert flags & Qt.TextInteractionFlag.TextSelectableByKeyboard

        message_id = "11111111-1111-1111-1111-111111111111"
        revision_id = "22222222-2222-2222-2222-222222222222"
        widget = window._message_widget(
            role="assistant",
            content="select and copy this",
            created_at_us=1,
            sequence_no=1,
            message_id=message_id,
            revision_id=revision_id,
        )
        labels = widget.findChildren(QLabel)
        assert labels
        body = next(label for label in labels if label.text() == "select and copy this")
        body_flags = body.textInteractionFlags()
        assert body_flags & Qt.TextInteractionFlag.TextSelectableByMouse
        assert body_flags & Qt.TextInteractionFlag.TextSelectableByKeyboard
        copy_button = widget.findChild(QPushButton, "copyMessageButton")
        assert copy_button is not None
        assert widget.property("messageId") == message_id
        assert widget.property("messageRevisionId") == revision_id
        assert copy_button.property("messageId") == message_id
        assert copy_button.property("messageRevisionId") == revision_id
    finally:
        window.close()
        app.processEvents()


def test_delete_confirmation_uses_silent_no_icon_dialog() -> None:
    source = inspect.getsource(AthenaMainWindow.apply_chat_deletion_preview)
    assert "QMessageBox.warning" not in source
    assert "QMessageBox.Icon.NoIcon" in source
    assert "StandardButton.Cancel" in source
