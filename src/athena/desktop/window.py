"""Native Qt Widgets shell for ATHENA."""

from __future__ import annotations

from PySide6.QtCore import Qt, QTimer, Slot
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QPushButton,
    QSizePolicy,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from athena.desktop.api_controller import DesktopApiController, DesktopApiSnapshot
from athena.desktop.ascii_panel import AsciiPanel

_NAVIGATION = (
    "CHAT",
    "KNOWLEDGE",
    "RESEARCH",
    "AGENTS",
    "FILES",
    "TASKS",
)
_REFRESH_INTERVAL_MS = 5_000


class MetricRow(QWidget):
    """Compact two-line metric with an addressable value label."""

    def __init__(self, label: str, value: str) -> None:
        super().__init__()
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 2, 0, 4)
        layout.setSpacing(1)

        name = QLabel(label)
        name.setProperty("role", "dim")
        self.value_label = QLabel(value)
        self.value_label.setProperty("role", "metric")
        layout.addWidget(name)
        layout.addWidget(self.value_label)

    def set_value(self, value: str) -> None:
        self.value_label.setText(value)


class AthenaMainWindow(QMainWindow):
    """Three-zone desktop shell with no direct Core or persistence dependency."""

    def __init__(self, api_controller: DesktopApiController | None = None) -> None:
        super().__init__()
        self.setObjectName("athenaMainWindow")
        self.setWindowTitle("ATHENA")
        self.resize(1440, 900)
        self.setMinimumSize(1180, 720)

        self.api_controller = api_controller
        self.navigation = QListWidget()
        self.pages = QStackedWidget()
        self.ascii_panel = AsciiPanel()
        self.page_title = QLabel("CHAT")
        self.status_text = QLabel("LOCAL · CORE DISCONNECTED · INTERNET OFF · TOR OFF")
        self.prompt_input = QLineEdit()
        self.send_button = QPushButton("→")
        self.local_model_metric = MetricRow("LOCAL MODEL", "not connected")
        self.context_metric = MetricRow("CONTEXT", "—")
        self.core_metric = MetricRow("CORE", "disconnected")
        self.provider_metric = MetricRow("PROVIDER", "LM Studio")
        self.model_metric = MetricRow("MODEL", "—")
        self.chat_metric = MetricRow("CHATS", "—")
        self.connection_detail = QLabel("Awaiting Core API")
        self.connection_detail.setProperty("role", "muted")
        self.connection_detail.setWordWrap(True)

        self.refresh_timer = QTimer(self)
        self.refresh_timer.setInterval(_REFRESH_INTERVAL_MS)
        self.refresh_timer.timeout.connect(self.refresh_core_status)

        self._build()
        self.navigation.setCurrentRow(0)
        self._connect_api_controller()

    def _build(self) -> None:
        root = QWidget()
        root_layout = QVBoxLayout(root)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)

        workspace = QWidget()
        workspace_layout = QHBoxLayout(workspace)
        workspace_layout.setContentsMargins(0, 0, 0, 0)
        workspace_layout.setSpacing(0)

        workspace_layout.addWidget(self._build_rail())
        workspace_layout.addWidget(self._build_center(), 1)
        workspace_layout.addWidget(self._build_context_panel())

        root_layout.addWidget(workspace, 1)
        root_layout.addWidget(self._build_status_bar())
        self.setCentralWidget(root)

    def _build_rail(self) -> QWidget:
        rail = QFrame()
        rail.setObjectName("rail")
        rail.setFixedWidth(228)

        layout = QVBoxLayout(rail)
        layout.setContentsMargins(18, 20, 18, 14)
        layout.setSpacing(10)

        wordmark_row = QHBoxLayout()
        wordmark = QLabel("ATHENA")
        wordmark.setObjectName("wordmark")
        status_dot = QLabel("●")
        status_dot.setProperty("accent", "true")
        status_dot.setToolTip("Desktop shell active")
        wordmark_row.addWidget(wordmark)
        wordmark_row.addStretch(1)
        wordmark_row.addWidget(status_dot)
        layout.addLayout(wordmark_row)

        self.navigation.setObjectName("navigation")
        self.navigation.setSpacing(0)
        self.navigation.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.navigation.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.navigation.setFixedHeight(222)
        for name in _NAVIGATION:
            self.navigation.addItem(QListWidgetItem(name))
        self.navigation.currentRowChanged.connect(self._select_page)
        layout.addWidget(self.navigation)

        layout.addSpacing(8)
        layout.addWidget(_section_label("SYSTEM"))
        layout.addWidget(self.local_model_metric)
        layout.addWidget(self.context_metric)
        layout.addWidget(MetricRow("VRAM", "—"))

        network = QLabel("INTERNET [ OFF ]   TOR [ OFF ]")
        network.setProperty("role", "metric")
        layout.addWidget(network)

        layout.addStretch(1)
        layout.addWidget(_section_label("PALLAS"))
        pallas = QLabel("Encrypted · Local\nlocked")
        pallas.setProperty("role", "muted")
        layout.addWidget(pallas)
        layout.addWidget(self.ascii_panel)
        return rail

    def _build_center(self) -> QWidget:
        center = QFrame()
        center.setObjectName("conversation")
        layout = QVBoxLayout(center)
        layout.setContentsMargins(34, 26, 34, 0)
        layout.setSpacing(0)

        self.page_title.setObjectName("pageTitle")
        layout.addWidget(self.page_title)
        layout.addSpacing(28)

        for name in _NAVIGATION:
            self.pages.addWidget(self._build_page(name))
        layout.addWidget(self.pages, 1)
        layout.addWidget(self._build_composer())
        return center

    def _build_page(self, name: str) -> QWidget:
        page = QWidget()
        page.setObjectName(f"page{name.title()}")
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 24)
        layout.setSpacing(12)

        if name == "CHAT":
            speaker = QLabel("ATHENA")
            speaker.setObjectName("speaker")
            message = QLabel(
                "Desktop shell ready. Core communication remains isolated behind "
                "the local API boundary."
            )
            message.setObjectName("message")
            message.setWordWrap(True)
            message.setMaximumWidth(760)
            self.connection_detail.setMaximumWidth(720)
            layout.addWidget(speaker)
            layout.addWidget(message)
            layout.addWidget(self.connection_detail)
        else:
            marker = QLabel(f"{name} · FOUNDATION")
            marker.setObjectName("speaker")
            message = QLabel("This workspace is intentionally empty until its domain API is wired.")
            message.setObjectName("message")
            message.setWordWrap(True)
            message.setMaximumWidth(720)
            layout.addWidget(marker)
            layout.addWidget(message)

        layout.addStretch(1)
        return page

    def _build_composer(self) -> QWidget:
        composer = QFrame()
        composer.setObjectName("composer")
        layout = QHBoxLayout(composer)
        layout.setContentsMargins(0, 10, 0, 12)
        layout.setSpacing(8)

        prompt = QLabel("›")
        prompt.setProperty("accent", "true")
        self.prompt_input.setObjectName("promptInput")
        self.prompt_input.setPlaceholderText("Ask ATHENA anything…")
        self.prompt_input.setDisabled(True)
        self.prompt_input.setToolTip("Chat transport is enabled in the next desktop slice.")

        self.send_button.setObjectName("sendButton")
        self.send_button.setDisabled(True)
        self.send_button.setToolTip("Chat transport is enabled in the next desktop slice.")

        layout.addWidget(prompt)
        layout.addWidget(self.prompt_input, 1)
        layout.addWidget(self.send_button)
        return composer

    def _build_context_panel(self) -> QWidget:
        panel = QFrame()
        panel.setObjectName("contextPanel")
        panel.setFixedWidth(286)

        layout = QVBoxLayout(panel)
        layout.setContentsMargins(20, 24, 20, 18)
        layout.setSpacing(9)

        layout.addWidget(_section_label("CONTEXT"))
        layout.addWidget(MetricRow("CURRENT PROJECT", "ATHENA"))
        layout.addWidget(MetricRow("CURRENT TOPIC", "Desktop UI"))
        layout.addWidget(self.chat_metric)
        layout.addWidget(MetricRow("SOURCES", "—"))
        layout.addSpacing(18)

        layout.addWidget(_section_label("ACTIVE"))
        layout.addWidget(self.core_metric)
        layout.addWidget(MetricRow("RESEARCH", "idle"))
        layout.addWidget(MetricRow("SYNTHESIS", "idle"))
        layout.addSpacing(18)

        layout.addWidget(_section_label("MODEL"))
        layout.addWidget(self.provider_metric)
        layout.addWidget(self.model_metric)
        layout.addWidget(MetricRow("TOKENS/S", "—"))
        layout.addStretch(1)
        return panel

    def _build_status_bar(self) -> QWidget:
        bar = QFrame()
        bar.setObjectName("statusBar")
        bar.setFixedHeight(24)
        layout = QHBoxLayout(bar)
        layout.setContentsMargins(18, 0, 18, 0)
        self.status_text.setObjectName("statusText")
        layout.addWidget(self.status_text)
        layout.addStretch(1)
        return bar

    def _connect_api_controller(self) -> None:
        controller = self.api_controller
        if controller is None:
            return
        controller.setParent(self)
        controller.snapshot_ready.connect(self.apply_api_snapshot)
        controller.connection_failed.connect(self.apply_api_failure)
        QTimer.singleShot(0, self.refresh_core_status)
        self.refresh_timer.start()

    @Slot()
    def refresh_core_status(self) -> None:
        controller = self.api_controller
        if controller is not None:
            controller.refresh()

    @Slot(object)
    def apply_api_snapshot(self, snapshot: object) -> None:
        if not isinstance(snapshot, DesktopApiSnapshot):
            return

        loaded_model = snapshot.loaded_model
        model_name = loaded_model.display_name if loaded_model is not None else "none loaded"
        context = loaded_model.loaded_context_length if loaded_model is not None else None

        self.core_metric.set_value(snapshot.health.core_status)
        provider_status = (
            snapshot.provider.status if snapshot.provider is not None else "unavailable"
        )
        self.provider_metric.set_value(provider_status)
        self.local_model_metric.set_value(model_name)
        self.model_metric.set_value(model_name)
        self.context_metric.set_value(_format_context(context))
        self.chat_metric.set_value(
            "unavailable" if snapshot.chat_error is not None else str(len(snapshot.chats))
        )

        detail = f"Core connected · provider {provider_status}."
        degraded: list[str] = []
        if snapshot.chat_error is not None:
            degraded.append("chat status")
        if snapshot.model_error is not None:
            degraded.append("model runtime")
        if degraded:
            detail += f" Degraded: {', '.join(degraded)}."
        else:
            detail += f" {len(snapshot.chats)} chats available."
        self.connection_detail.setText(detail)
        self.status_text.setText(
            "LOCAL · CORE READY · KNOWLEDGE READY · INTERNET OFF · TOR OFF"
        )

    @Slot(str)
    def apply_api_failure(self, message: str) -> None:
        self.core_metric.set_value("disconnected")
        self.local_model_metric.set_value("not connected")
        self.model_metric.set_value("—")
        self.context_metric.set_value("—")
        self.chat_metric.set_value("—")
        self.connection_detail.setText(message)
        self.status_text.setText("LOCAL · CORE DISCONNECTED · INTERNET OFF · TOR OFF")

    def _select_page(self, index: int) -> None:
        if not 0 <= index < self.pages.count():
            return
        self.pages.setCurrentIndex(index)
        name = _NAVIGATION[index]
        self.page_title.setText(name)
        self.ascii_panel.set_context(name)


def _format_context(value: int | None) -> str:
    if value is None:
        return "—"
    return f"{value:,}".replace(",", " ")


def _section_label(text: str) -> QLabel:
    label = QLabel(text)
    label.setProperty("role", "section")
    return label


def navigation_names() -> tuple[str, ...]:
    """Expose the stable shell navigation contract for tests and future routing."""
    return _NAVIGATION
