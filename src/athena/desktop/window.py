"""Native Qt Widgets shell for ATHENA."""

from __future__ import annotations

from datetime import datetime

from PySide6.QtCore import QPoint, QSize, Qt, QTimer, Slot
from PySide6.QtGui import QColor, QKeySequence, QPainter, QPaintEvent, QPen, QShortcut
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from athena.api.contracts import ChatThreadResponse
from athena.desktop.api_controller import DesktopApiController, DesktopApiSnapshot
from athena.desktop.ascii_panel import AsciiPanel
from athena.desktop.theme import BORDER, ORANGE, TEXT_DIM, TEXT_MUTED

_NAVIGATION = ("CHAT", "KNOWLEDGE", "RESEARCH", "JOBS", "FILES", "SYSTEM")
_REFRESH_INTERVAL_MS = 5_000


class MetricRow(QWidget):
    """Compact single-line system or inspector metric."""

    def __init__(self, label: str, value: str) -> None:
        super().__init__()
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 3, 0, 3)
        layout.setSpacing(16)
        name = QLabel(label)
        name.setProperty("role", "dim")
        self.value_label = QLabel(value)
        self.value_label.setProperty("role", "metric")
        self.value_label.setAlignment(
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
        )
        layout.addWidget(name)
        layout.addStretch(1)
        layout.addWidget(self.value_label)

    def set_value(self, value: str) -> None:
        self.value_label.setText(value)


class PallasVisualPlaceholder(QWidget):
    """Native 9:16 slot reserved for the future reactive ASCII renderer."""

    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("pallasVisualPlaceholder")
        self.setFixedSize(207, 368)
        self.setToolTip(
            "Native 9:16 placeholder for the future reactive PALLAS ASCII renderer"
        )

    def paintEvent(self, event: QPaintEvent) -> None:  # noqa: N802
        super().paintEvent(event)

        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, False)

        width = self.width()
        height = self.height()

        painter.fillRect(self.rect(), QColor("#070707"))
        painter.setPen(QPen(QColor("#242424"), 1))
        painter.drawRect(0, 0, width - 1, height - 1)

        corner = 13
        inset = 8
        painter.setPen(QPen(QColor("#555551"), 1))
        painter.drawLine(inset, inset, inset + corner, inset)
        painter.drawLine(inset, inset, inset, inset + corner)
        painter.drawLine(width - inset, inset, width - inset - corner, inset)
        painter.drawLine(width - inset, inset, width - inset, inset + corner)
        painter.drawLine(inset, height - inset, inset + corner, height - inset)
        painter.drawLine(inset, height - inset, inset, height - inset - corner)
        painter.drawLine(
            width - inset,
            height - inset,
            width - inset - corner,
            height - inset,
        )
        painter.drawLine(
            width - inset,
            height - inset,
            width - inset,
            height - inset - corner,
        )

        font = painter.font()
        font.setFamily("Cascadia Mono")
        font.setPixelSize(11)
        font.setBold(False)
        painter.setFont(font)

        painter.setPen(QColor("#AAA9A4"))
        painter.drawText(15, 27, "REACTIVE ASCII")

        ratio = "9:16"
        ratio_width = painter.fontMetrics().horizontalAdvance(ratio)
        painter.drawText(width - 15 - ratio_width, 27, ratio)

        center_x = width // 2
        center_y = height // 2
        painter.setPen(QPen(QColor("#30302E"), 1))
        painter.drawLine(center_x, 58, center_x, height - 58)
        painter.drawLine(30, center_y, width - 30, center_y)

        box_size = 62
        half = box_size // 2
        painter.setPen(QPen(QColor("#777772"), 1))
        painter.drawRect(
            center_x - half,
            center_y - half,
            box_size,
            box_size,
        )

        painter.setPen(QColor("#F2F1ED"))
        label = "PALLAS"
        label_width = painter.fontMetrics().horizontalAdvance(label)
        painter.drawText(
            center_x - (label_width // 2),
            center_y - 5,
            label,
        )

        painter.setPen(QColor("#F26A21"))
        marker = "■"
        marker_width = painter.fontMetrics().horizontalAdvance(marker)
        painter.drawText(
            center_x - (marker_width // 2),
            center_y + 17,
            marker,
        )

        painter.setPen(QColor("#6F6F6B"))
        footer = "RENDERER PENDING"
        footer_width = painter.fontMetrics().horizontalAdvance(footer)
        painter.drawText(
            center_x - (footer_width // 2),
            height - 28,
            footer,
        )

        painter.end()


class EvidenceRail(QWidget):
    """Local provenance rail beside the currently inspected answer."""

    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("evidenceRail")
        self.setMinimumWidth(150)
        self.setMaximumWidth(168)
        self.setMinimumHeight(320)

    def paintEvent(self, event: QPaintEvent) -> None:  # noqa: N802
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, False)
        x_label = 18
        x_line = 60
        x_trunk = self.width() - 38
        y_sources = (70, 118, 166)
        y_claim = 238
        y_knowledge = 294
        muted_pen = QPen(QColor(BORDER), 1)
        active_pen = QPen(QColor(ORANGE), 1)

        painter.setPen(muted_pen)
        for y in y_sources:
            painter.drawLine(QPoint(x_line, y), QPoint(x_trunk, y))
        painter.drawLine(QPoint(x_trunk, y_sources[0]), QPoint(x_trunk, y_sources[-1]))
        painter.drawLine(QPoint(x_trunk, y_sources[-1]), QPoint(x_trunk, y_claim))
        painter.drawLine(QPoint(x_trunk, y_claim), QPoint(x_trunk, y_knowledge))

        painter.setPen(active_pen)
        painter.drawLine(QPoint(x_line, y_sources[0]), QPoint(x_trunk, y_sources[0]))
        painter.drawLine(QPoint(x_trunk, y_sources[0]), QPoint(x_trunk, y_claim))
        painter.drawLine(QPoint(x_trunk, y_claim), QPoint(x_trunk, y_knowledge))

        painter.setPen(Qt.PenStyle.NoPen)
        for index, y in enumerate(y_sources):
            painter.setBrush(QColor(ORANGE if index == 0 else TEXT_DIM))
            painter.drawRect(x_trunk - 2, y - 2, 4, 4)
        painter.setBrush(QColor(ORANGE))
        painter.drawRect(x_trunk - 3, y_claim - 3, 6, 6)
        painter.drawRect(x_trunk - 3, y_knowledge - 3, 6, 6)

        painter.setPen(QColor(ORANGE))
        painter.drawText(x_label, y_sources[0] + 5, "S03")
        painter.drawText(x_label, y_claim + 5, "C04")
        painter.drawText(x_label, y_knowledge + 5, "K17")
        painter.setPen(QColor(TEXT_MUTED))
        painter.drawText(x_label, y_sources[1] + 5, "S07")
        painter.drawText(x_label, y_sources[2] + 5, "S11")
        painter.end()


class AthenaMainWindow(QMainWindow):
    """Three-zone evidence workbench over ATHENA's local Core API boundary."""

    def __init__(self, api_controller: DesktopApiController | None = None) -> None:
        super().__init__()
        self.setObjectName("athenaMainWindow")
        self.setWindowTitle("ATHENA")
        self.resize(1660, 980)
        self.setMinimumSize(1320, 780)

        self.api_controller = api_controller
        self.navigation = QListWidget()
        self.pages = QStackedWidget()
        self.ascii_panel = AsciiPanel()
        self.pallas_visual = PallasVisualPlaceholder()
        self.page_title = QLabel("CHAT")
        self.status_text = QLabel("LOCAL / CORE DISCONNECTED")
        self.prompt_input = QLineEdit()
        self.send_button = QPushButton("CTRL+ENTER")
        self.local_model_metric = MetricRow("MODEL", "not connected")
        self.context_metric = MetricRow("CTX", "—")
        self.core_metric = MetricRow("CORE", "disconnected")
        self.provider_metric = MetricRow("PROVIDER", "LM Studio")
        self.model_metric = MetricRow("MODEL", "—")
        self.chat_metric = MetricRow("CHATS", "—")
        self.current_chat_id: str | None = None
        self._core_ready = False
        self._chat_busy = False
        self.chat_scroll = QScrollArea()
        self.chat_messages_widget = QWidget()
        self.chat_messages_layout = QVBoxLayout(self.chat_messages_widget)
        self.evidence_rail = EvidenceRail()
        self.evidence_chain = QFrame()
        self.inspector_object_id = QLabel("CHAT / NONE")
        self.inspector_heading = QLabel("No conversation selected")
        self.inspector_message_count = MetricRow("MESSAGES", "0")
        self.inspector_mode = MetricRow("MODE", "DIRECT")
        self.inspector_provenance = QLabel(
            "Direct chat does not fabricate provenance. Source, evidence, claim and "
            "knowledge relationships appear here only when a grounded response provides them."
        )
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
        root.setObjectName("root")
        layout = QHBoxLayout(root)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self._build_rail())
        layout.addWidget(self._build_center(), 1)
        layout.addWidget(self._build_inspector())
        self.setCentralWidget(root)

    def _build_rail(self) -> QWidget:
        rail = QFrame()
        rail.setObjectName("rail")
        rail.setFixedWidth(252)
        layout = QVBoxLayout(rail)
        layout.setContentsMargins(22, 24, 18, 20)
        layout.setSpacing(14)

        wordmark = QLabel("A T H E N A")
        wordmark.setObjectName("wordmark")
        layout.addWidget(wordmark)

        local_row = QHBoxLayout()
        local_row.setSpacing(8)
        ready_square = QLabel("■")
        ready_square.setProperty("accent", "true")
        ready_square.setObjectName("statusSquare")
        self.status_text.setObjectName("localStatus")
        local_row.addWidget(ready_square)
        local_row.addWidget(self.status_text)
        local_row.addStretch(1)
        layout.addLayout(local_row)
        layout.addWidget(_rule())

        self.navigation.setObjectName("navigation")
        self.navigation.setSpacing(0)
        self.navigation.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.navigation.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.navigation.setFixedHeight(232)
        for index, name in enumerate(_NAVIGATION, start=1):
            item = QListWidgetItem(f"{index:02d}   {name}")
            item.setSizeHint(QSize(188, 38))
            self.navigation.addItem(item)
        self.navigation.currentRowChanged.connect(self._select_page)
        layout.addWidget(self.navigation)
        layout.addWidget(_rule())
        layout.addWidget(_section_label("PALLAS"))

        pallas_row = QHBoxLayout()
        pallas_row.setContentsMargins(0, 4, 0, 4)
        pallas_row.addStretch(1)
        pallas_row.addWidget(self.pallas_visual)
        pallas_row.addStretch(1)
        layout.addLayout(pallas_row)

        layout.addStretch(1)
        layout.addWidget(_rule())

        net = QLabel("NET    ■ ONLINE\nTOR    □ OFF")
        net.setObjectName("networkState")
        layout.addWidget(net)
        layout.addWidget(_rule())
        layout.addWidget(self.local_model_metric)
        layout.addWidget(MetricRow("VRAM", "—"))
        layout.addWidget(self.context_metric)
        return rail

    def _build_center(self) -> QWidget:
        center = QFrame()
        center.setObjectName("conversation")
        layout = QVBoxLayout(center)
        layout.setContentsMargins(38, 28, 36, 20)
        layout.setSpacing(0)

        header = QHBoxLayout()
        breadcrumb = QLabel("ATHENA  >  ")
        breadcrumb.setObjectName("breadcrumb")
        self.page_title.setObjectName("pageTitle")
        header.addWidget(breadcrumb)
        header.addWidget(self.page_title)
        header.addStretch(1)
        keyboard = QLabel("CTRL+K  COMMAND")
        keyboard.setObjectName("keyboardHint")
        header.addWidget(keyboard)
        layout.addLayout(header)
        layout.addWidget(_rule())
        layout.addSpacing(30)

        for name in _NAVIGATION:
            self.pages.addWidget(self._build_page(name))
        layout.addWidget(self.pages, 1)
        layout.addWidget(self._build_command_input())
        return center

    def _build_page(self, name: str) -> QWidget:
        page = QWidget()
        page.setObjectName(f"page{name.title()}")
        if name != "CHAT":
            layout = QVBoxLayout(page)
            layout.setContentsMargins(0, 0, 0, 28)
            layout.setSpacing(16)
            label = QLabel(name)
            label.setObjectName("speaker")
            message = QLabel(
                "This workspace is present in the desktop shell. Its domain controls "
                "remain hidden until the corresponding local API surface is connected."
            )
            message.setObjectName("message")
            message.setWordWrap(True)
            message.setMaximumWidth(820)
            layout.addWidget(label)
            layout.addWidget(message)
            layout.addStretch(1)
            return page

        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 24)
        layout.setSpacing(0)

        conversation_row = QHBoxLayout()
        conversation_row.setSpacing(18)

        self.chat_messages_widget.setObjectName("chatMessages")
        self.chat_messages_layout.setContentsMargins(0, 0, 8, 0)
        self.chat_messages_layout.setSpacing(0)
        self.chat_messages_layout.addStretch(1)

        self.chat_scroll.setObjectName("chatScroll")
        self.chat_scroll.setWidgetResizable(True)
        self.chat_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.chat_scroll.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        self.chat_scroll.setWidget(self.chat_messages_widget)

        self.evidence_rail.setVisible(False)

        conversation_row.addWidget(self.chat_scroll, 1)
        conversation_row.addWidget(self.evidence_rail)
        layout.addLayout(conversation_row, 1)

        layout.addSpacing(14)
        layout.addWidget(_rule())
        layout.addSpacing(14)

        self.evidence_chain = self._build_evidence_chain()
        layout.addWidget(self.evidence_chain)

        self._render_empty_chat(
            "Connect to ATHENA Core to load a conversation."
        )
        return page

    def _build_evidence_chain(self) -> QFrame:
        chain = QFrame()
        chain.setObjectName("evidenceChain")

        layout = QHBoxLayout(chain)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(16)

        title = QLabel("EVIDENCE CHAIN")
        title.setObjectName("chainTitle")
        state = QLabel("DIRECT CHAT / PROVENANCE NOT ATTACHED")
        state.setObjectName("chainState")

        layout.addWidget(title)
        layout.addWidget(state)
        layout.addStretch(1)
        return chain

    def _build_command_input(self) -> QWidget:
        composer = QFrame()
        composer.setObjectName("composer")
        composer.setFixedHeight(58)

        layout = QHBoxLayout(composer)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)

        prompt = QLabel(">")
        prompt.setObjectName("promptMarker")
        self.prompt_input.setObjectName("promptInput")
        self.prompt_input.setPlaceholderText("Ask ATHENA")
        self.prompt_input.setDisabled(True)
        self.prompt_input.setToolTip(
            "Direct chat becomes available when ATHENA Core and a local model are ready."
        )
        self.prompt_input.returnPressed.connect(self._submit_prompt)

        self._send_return_shortcut = QShortcut(
            QKeySequence("Ctrl+Return"),
            self,
        )
        self._send_return_shortcut.activated.connect(
            self._submit_prompt
        )

        self._send_enter_shortcut = QShortcut(
            QKeySequence("Ctrl+Enter"),
            self,
        )
        self._send_enter_shortcut.activated.connect(
            self._submit_prompt
        )

        attach = QLabel("ATTACH")
        attach.setObjectName("commandMeta")
        tools = QLabel("TOOLS")
        tools.setObjectName("commandMeta")

        self.send_button.setObjectName("sendButton")
        self.send_button.setText("SEND")
        self.send_button.setToolTip("Send message ? Ctrl+Enter")
        self.send_button.setDisabled(True)
        self.send_button.clicked.connect(self._submit_prompt)

        layout.addWidget(prompt)
        layout.addWidget(self.prompt_input, 1)
        layout.addWidget(attach)
        layout.addWidget(tools)
        layout.addWidget(self.send_button)
        return composer

    def _build_inspector(self) -> QWidget:
        panel = QFrame()
        panel.setObjectName("inspector")
        panel.setFixedWidth(388)

        layout = QVBoxLayout(panel)
        layout.setContentsMargins(24, 24, 24, 20)
        layout.setSpacing(10)

        inspector = QLabel("INSPECTOR")
        inspector.setObjectName("inspectorTitle")
        layout.addWidget(inspector)
        layout.addWidget(_rule())

        self.inspector_object_id.setObjectName("objectId")
        layout.addWidget(self.inspector_object_id)

        self.inspector_heading.setObjectName("inspectorHeading")
        self.inspector_heading.setWordWrap(True)
        layout.addWidget(self.inspector_heading)

        layout.addSpacing(4)
        layout.addWidget(self.inspector_message_count)
        layout.addWidget(self.inspector_mode)

        layout.addSpacing(8)
        layout.addWidget(_rule())
        layout.addWidget(_section_label("PROVENANCE"))

        self.inspector_provenance.setObjectName("inspectorBody")
        self.inspector_provenance.setWordWrap(True)
        layout.addWidget(self.inspector_provenance)

        layout.addStretch(1)
        layout.addWidget(_rule())

        job_header = QLabel("JOBS / API NOT CONNECTED")
        job_header.setObjectName("jobHeader")
        layout.addWidget(job_header)

        job_meta = QLabel(
            "Autonomous job state will appear here when the desktop jobs API is available."
        )
        job_meta.setObjectName("jobMeta")
        job_meta.setWordWrap(True)
        layout.addWidget(job_meta)
        return panel

    def _connect_api_controller(self) -> None:
        controller = self.api_controller
        if controller is None:
            return

        controller.setParent(self)
        controller.snapshot_ready.connect(self.apply_api_snapshot)
        controller.connection_failed.connect(self.apply_api_failure)
        controller.chat_loaded.connect(self.apply_chat_loaded)
        controller.chat_sent.connect(self.apply_chat_sent)
        controller.chat_operation_failed.connect(self.apply_chat_operation_failure)
        controller.chat_busy_changed.connect(self.apply_chat_busy)

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
        model_name = (
            loaded_model.display_name
            if loaded_model is not None
            else "none loaded"
        )
        context = (
            loaded_model.loaded_context_length
            if loaded_model is not None
            else None
        )
        self.core_metric.set_value(snapshot.health.core_status)

        provider_status = (
            snapshot.provider.status
            if snapshot.provider is not None
            else "unavailable"
        )
        self.provider_metric.set_value(provider_status)
        self.local_model_metric.set_value(model_name)
        self.model_metric.set_value(model_name)
        self.context_metric.set_value(_format_context(context))
        self.chat_metric.set_value(
            "unavailable"
            if snapshot.chat_error is not None
            else str(len(snapshot.chats))
        )

        self._core_ready = (
            snapshot.health.core_status in {"ok", "ready", "running"}
            and provider_status == "ready"
            and loaded_model is not None
        )
        self.status_text.setText("LOCAL / READY")

        if snapshot.chat_error is not None:
            self.connection_detail.setText(snapshot.chat_error)
        elif not self._core_ready:
            self.connection_detail.setText(
                "ATHENA Core is connected, but no ready local model is loaded."
            )
        else:
            self.connection_detail.setText(
                f"Core connected · {len(snapshot.chats)} chats available."
            )

        if self.current_chat_id is None and snapshot.chats:
            self.current_chat_id = snapshot.chats[0].chat_id
            controller = self.api_controller
            if controller is not None and not controller.chat_busy:
                controller.load_chat(self.current_chat_id)
        elif self.current_chat_id is None and not snapshot.chats:
            self._render_empty_chat(
                "No conversation yet. Type below to start a persistent direct chat."
            )
            self._update_inspector_for_empty_chat()

        self._sync_composer_enabled()

    @Slot(str)
    def apply_api_failure(self, message: str) -> None:
        self._core_ready = False
        self.core_metric.set_value("disconnected")
        self.local_model_metric.set_value("not connected")
        self.model_metric.set_value("—")
        self.context_metric.set_value("—")
        self.chat_metric.set_value("—")
        self.connection_detail.setText(message)
        self.status_text.setText("LOCAL / CORE DISCONNECTED")
        self._sync_composer_enabled()

    @Slot(object)
    def apply_chat_loaded(self, thread: object) -> None:
        if not isinstance(thread, ChatThreadResponse):
            return
        self.current_chat_id = thread.chat_id
        self._render_chat_thread(thread)

    @Slot(object)
    def apply_chat_sent(self, thread: object) -> None:
        if not isinstance(thread, ChatThreadResponse):
            return
        self.current_chat_id = thread.chat_id
        self.prompt_input.clear()
        self._render_chat_thread(thread)
        QTimer.singleShot(0, self.refresh_core_status)

    @Slot(str, str)
    def apply_chat_operation_failure(
        self,
        operation: str,
        message: str,
    ) -> None:
        detail = (
            f"Direct chat {operation} failed: {message}. "
            "ATHENA did not retry the mutation automatically."
        )
        self.connection_detail.setText(detail)
        self.status_text.setText("LOCAL / CHAT ERROR")
        self.inspector_object_id.setText("CHAT / ERROR")
        self.inspector_heading.setText(
            f"Direct chat {operation} failed"
        )
        self.inspector_provenance.setText(detail)

    @Slot(bool)
    def apply_chat_busy(self, busy: bool) -> None:
        self._chat_busy = busy
        self.send_button.setText("WORKING" if busy else "SEND")
        self._sync_composer_enabled()

    @Slot()
    def _submit_prompt(self) -> None:
        controller = self.api_controller
        if (
            controller is None
            or not self._core_ready
            or self._chat_busy
        ):
            return

        content = self.prompt_input.text().strip()
        if not content:
            return

        controller.send_message(
            chat_id=self.current_chat_id,
            content=content,
        )

    def _sync_composer_enabled(self) -> None:
        enabled = (
            self.api_controller is not None
            and self._core_ready
            and not self._chat_busy
        )
        self.prompt_input.setEnabled(enabled)
        self.send_button.setEnabled(enabled)

    def _render_empty_chat(self, message: str) -> None:
        self._clear_chat_messages()
        label = QLabel(message)
        label.setObjectName("emptyChatState")
        label.setWordWrap(True)
        label.setMaximumWidth(760)
        self.chat_messages_layout.addWidget(label)
        self.chat_messages_layout.addStretch(1)

    def _render_chat_thread(self, thread: ChatThreadResponse) -> None:
        self._clear_chat_messages()

        if not thread.messages:
            self._render_empty_chat(
                "This conversation is empty. Type below to send the first message."
            )
        else:
            for message in thread.messages:
                self.chat_messages_layout.addWidget(
                    self._message_widget(
                        role=message.message_type,
                        content=message.content,
                        created_at_us=message.created_at_us,
                        sequence_no=message.sequence_no,
                    )
                )
            self.chat_messages_layout.addStretch(1)

        self.inspector_object_id.setText(
            f"CHAT / {thread.chat_id[:8].upper()}"
        )
        self.inspector_heading.setText("Persistent direct conversation")
        self.inspector_message_count.set_value(str(len(thread.messages)))
        self.inspector_mode.set_value("DIRECT")
        self.inspector_provenance.setText(
            "No grounded provenance is attached to ordinary direct chat. "
            "ATHENA will populate source → evidence → claim → knowledge here "
            "only for responses that actually carry those relationships."
        )
        self.evidence_rail.setVisible(False)

        bar = self.chat_scroll.verticalScrollBar()
        QTimer.singleShot(0, lambda: bar.setValue(bar.maximum()))

    def _message_widget(
        self,
        *,
        role: str,
        content: str | None,
        created_at_us: int,
        sequence_no: int,
    ) -> QWidget:
        container = QWidget()
        container.setObjectName("chatMessage")

        layout = QVBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 18)
        layout.setSpacing(8)

        role_upper = role.upper()
        display_role = (
            "YOU"
            if role == "user"
            else "ATHENA"
            if role == "assistant"
            else role_upper
        )

        timestamp = _format_message_time(created_at_us)
        meta = QLabel(
            f"{display_role}  /  {timestamp}  /  {sequence_no:04d}"
        )
        meta.setObjectName("userMeta" if role == "user" else "speaker")

        body = QLabel(content or "")
        body.setObjectName(
            "userMessage" if role == "user" else "message"
        )
        body.setTextFormat(Qt.TextFormat.PlainText)
        body.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        body.setWordWrap(True)
        body.setMaximumWidth(860)

        layout.addWidget(meta)
        layout.addWidget(body)
        layout.addWidget(_rule())
        return container

    def _clear_chat_messages(self) -> None:
        while self.chat_messages_layout.count():
            item = self.chat_messages_layout.takeAt(0)
            if item is None:
                break
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

    def _update_inspector_for_empty_chat(self) -> None:
        self.inspector_object_id.setText("CHAT / NEW")
        self.inspector_heading.setText(
            "Ready for a persistent direct conversation"
        )
        self.inspector_message_count.set_value("0")
        self.inspector_mode.set_value("DIRECT")
        self.inspector_provenance.setText(
            "No provenance object is selected. Direct chat does not invent "
            "source relationships."
        )
        self.evidence_rail.setVisible(False)

    def _select_page(self, index: int) -> None:
        if not 0 <= index < self.pages.count():
            return
        self.pages.setCurrentIndex(index)
        name = _NAVIGATION[index]
        self.page_title.setText(name)
        self.ascii_panel.set_context(name)


def _format_message_time(created_at_us: int) -> str:
    try:
        return datetime.fromtimestamp(
            created_at_us / 1_000_000
        ).strftime("%H:%M")
    except (OverflowError, OSError, ValueError):
        return "—"


def _format_context(value: int | None) -> str:
    if value is None:
        return "—"
    return f"{value:,}".replace(",", " ")


def _section_label(text: str) -> QLabel:
    label = QLabel(text)
    label.setProperty("role", "section")
    return label


def _rule() -> QFrame:
    line = QFrame()
    line.setObjectName("rule")
    line.setFrameShape(QFrame.Shape.HLine)
    line.setFixedHeight(1)
    return line


def _arrow_label() -> QLabel:
    label = QLabel("─→")
    label.setObjectName("chainArrow")
    label.setAlignment(Qt.AlignmentFlag.AlignCenter)
    return label


def _rich_chain(text: str) -> QLabel:
    label = QLabel(text)
    label.setObjectName("chainColumn")
    label.setTextFormat(Qt.TextFormat.RichText)
    label.setWordWrap(True)
    return label


def navigation_names() -> tuple[str, ...]:
    """Expose the stable shell navigation contract for tests and future routing."""
    return _NAVIGATION
