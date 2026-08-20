from __future__ import annotations

from PySide6.QtWidgets import QApplication, QFrame, QWidget

from athena.api.contracts import (
    ChatSummaryResponse,
    HealthResponse,
    ModelResponse,
    ProviderHealthResponse,
)
from athena.desktop.api_controller import DesktopApiSnapshot
from athena.desktop.app import create_application
from athena.desktop.ascii_panel import ascii_scene
from athena.desktop.theme import APP_STYLESHEET, ORANGE
from athena.desktop.window import AthenaMainWindow, navigation_names


def _app() -> QApplication:
    return create_application(["athena-desktop-test"])


def _snapshot() -> DesktopApiSnapshot:
    return DesktopApiSnapshot(
        health=HealthResponse(api_version="v1", core_status="running", detail=None),
        provider=ProviderHealthResponse(provider="lm_studio", status="ready", detail=None),
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
        chats=(
            ChatSummaryResponse(
                chat_id="chat-1",
                started_at_us=1,
                ended_at_us=None,
                archive_mode="standard",
                lifecycle_state="active",
                message_count=2,
            ),
        ),
    )


def test_theme_keeps_the_restrained_athena_palette() -> None:
    assert "#060606" in APP_STYLESHEET
    assert ORANGE == "#F26A21"
    assert "gradient" not in APP_STYLESHEET.casefold()
    assert "#0000ff" not in APP_STYLESHEET.casefold()


def test_ascii_scene_tracks_semantic_context_without_randomness() -> None:
    assert ascii_scene("knowledge architecture") == ascii_scene("knowledge architecture")
    assert ascii_scene("knowledge architecture") != ascii_scene("research sources")
    assert ascii_scene("idle") != ascii_scene("research sources")


def test_shell_exposes_expected_primary_navigation() -> None:
    assert navigation_names() == (
        "CHAT",
        "KNOWLEDGE",
        "RESEARCH",
        "JOBS",
        "FILES",
        "SYSTEM",
        "SETTINGS",
    )


def test_shell_builds_three_zone_layout_and_switches_pages() -> None:
    app = _app()
    window = AthenaMainWindow()
    try:
        assert window.windowTitle() == "ATHENA"
        assert window.navigation.count() == 7
        nav_rows_height = sum(
            window.navigation.sizeHintForRow(index)
            for index in range(window.navigation.count())
        )
        assert nav_rows_height <= window.navigation.height()
        assert window.pages.count() == 7
        assert window.pages.currentIndex() == 0
        assert window.prompt_input.isEnabled() is False
        assert window.send_button.isEnabled() is False
        assert window.findChild(QFrame, "inspector") is not None
        assert window.findChild(QWidget, "evidenceRail") is not None
        assert window.findChild(QFrame, "evidenceChain") is not None
        pallas = window.findChild(QWidget, "pallasVisualPlaceholder")
        assert pallas is not None
        assert pallas.width() * 16 == pallas.height() * 9
        assert pallas.width() >= 200

        window.navigation.setCurrentRow(2)
        app.processEvents()

        assert window.pages.currentIndex() == 2
        assert window.page_title.text() == "RESEARCH"
        assert "o" in window.ascii_panel.toPlainText()
    finally:
        window.close()


def test_shell_renders_connected_and_disconnected_api_state() -> None:
    _app()
    window = AthenaMainWindow()
    try:
        window.apply_api_snapshot(_snapshot())

        assert window.core_metric.value_label.text() == "running"
        assert window.provider_metric.value_label.text() == "ready"
        assert window.model_metric.value_label.text() == "Qwen Test"
        assert window.context_metric.value_label.text() == "48 000"
        assert window.chat_metric.value_label.text() == "1"
        assert window.status_text.text() == "LOCAL / READY"

        window.apply_api_failure("ATHENA Core is unavailable.")

        assert window.core_metric.value_label.text() == "disconnected"
        assert window.model_metric.value_label.text() == "—"
        assert "CORE DISCONNECTED" in window.status_text.text()
    finally:
        window.close()
