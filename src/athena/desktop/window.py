"""Native Qt Widgets shell for ATHENA."""
# ATHENA_V4913_SETTINGS_STATE
# ATHENA_V4914_UX_HARDENING

from __future__ import annotations

from datetime import datetime

from PySide6.QtCore import QPoint, QSize, Qt, QTimer, Slot
from PySide6.QtGui import (
    QColor,
    QKeySequence,
    QPainter,
    QPaintEvent,
    QPen,
    QResizeEvent,
    QShortcut,
)
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSlider,
    QSpinBox,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from athena.api.contracts import (
    CanonicalMergeReviewResponse,
    ChatThreadResponse,
    DeletionPreviewResponse,
    GroundedChatResponse,
    KnowledgeMergeReviewResponse,
    KnowledgeReviewResponse,
    MessageKnowledgeExtractionResponse,
    ModelResponse,
    RememberedChatMessageResponse,
)
from athena.desktop.api_controller import DesktopApiController, DesktopApiSnapshot
from athena.desktop.ascii_panel import AsciiPanel
from athena.desktop.theme import BORDER, ORANGE, TEXT_DIM, TEXT_MUTED

_NAVIGATION = ("CHAT", "KNOWLEDGE", "RESEARCH", "JOBS", "FILES", "SYSTEM", "SETTINGS")
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


class _AutoHeightMessageLabel(QLabel):
    # Word-wrapped chat text that cannot be vertically compressed.

    def __init__(
        self,
        text: str = "",
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(text, parent)
        self.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Minimum,
        )

    def resizeEvent(self, event: QResizeEvent) -> None:  # noqa: N802
        super().resizeEvent(event)
        self._sync_minimum_height(event.size().width())

    def _sync_minimum_height(self, width: int) -> None:
        if width <= 0 or not self.wordWrap():
            return

        required_height = self.heightForWidth(width)
        if required_height <= 0:
            return

        if self.minimumHeight() != required_height:
            self.setMinimumHeight(required_height)
            self.updateGeometry()


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
        self.ground_button = QPushButton("GROUND")
        self.send_button = QPushButton("CTRL+ENTER")
        self.chat_selector = QComboBox()
        self.model_selector = QComboBox()
        self.context_slider = QSlider(Qt.Orientation.Horizontal)
        self.context_value_label = QLabel("—")
        self.delete_chat_button = QPushButton("DELETE")
        self.new_chat_button = QPushButton("NEW CHAT")
        self.context_spin = QSpinBox()
        self.max_output_slider = QSlider(Qt.Orientation.Horizontal)
        self.max_output_spin = QSpinBox()
        self.temperature_spin = QDoubleSpinBox()
        self.thinking_checkbox = QCheckBox("OFF — REASONING DISABLED")
        self.settings_model_value = QLabel("—")
        self._models_by_id: dict[str, ModelResponse] = {}
        self._context_by_model: dict[str, int] = {}
        self._max_output_by_model: dict[str, int] = {}
        self._temperature_by_model: dict[str, float] = {}
        self._thinking_by_model: dict[str, bool] = {}
        self._remembered_message_revisions: set[tuple[str, str]] = set()
        self._knowledge_extraction: MessageKnowledgeExtractionResponse | None = None
        self._knowledge_review: KnowledgeReviewResponse | None = None
        self._knowledge_review_chat_id: str | None = None
        self._knowledge_review_request: tuple[str, str, str] | None = None
        self._transient_failures: dict[str, list[tuple[int, str, str]]] = {}
        self._last_rendered_sequence = 0
        self._core_transport_ready = False
        self._provider_ready = False
        self._last_model_error: str | None = None
        self.local_model_metric = MetricRow("MODEL", "not connected")
        self.context_metric = MetricRow("CTX", "—")
        self.core_metric = MetricRow("CORE", "disconnected")
        self.provider_metric = MetricRow("PROVIDER", "LM Studio")
        self.model_metric = MetricRow("MODEL", "—")
        self.chat_metric = MetricRow("CHATS", "—")
        self.current_chat_id: str | None = None
        self.loaded_chat_id: str | None = None
        self.selected_chat_id: str | None = None
        self.pending_chat_id: str | None = None
        self._core_ready = False
        self._chat_busy = False
        self._chat_follow_tail = True
        self._chat_scroll_programmatic = False
        self._chat_slider_active = False
        self.chat_scroll = QScrollArea()
        self.inspector_scroll = QScrollArea()
        self.chat_messages_widget = QWidget()
        self.chat_messages_layout = QVBoxLayout(self.chat_messages_widget)
        self.evidence_rail = EvidenceRail()
        self.evidence_chain = QFrame()
        self.knowledge_review_panel = QFrame()
        self.knowledge_review_state = QLabel("IDLE")
        self.knowledge_review_close_button = QPushButton("CLOSE")
        self.knowledge_review_scroll = QScrollArea()
        self.knowledge_review_content = QWidget()
        self.knowledge_review_items = QVBoxLayout(self.knowledge_review_content)
        self.evidence_chain_state = QLabel(
            "DIRECT / PROVENANCE NOT ATTACHED"
        )
        self.inspector_object_id = QLabel("CHAT / NONE")
        self.inspector_heading = QLabel("No conversation selected")
        self.inspector_message_count = MetricRow("MESSAGES", "0")
        self.inspector_mode = MetricRow("MODE", "DIRECT")
        self.inspector_provenance = QLabel(
            "Direct chat does not fabricate provenance. Source, evidence, claim and "
            "knowledge relationships appear here only when a grounded response provides them."
        )
        self.inspector_copy_button = QPushButton("COPY")
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
        for label in root.findChildren(QLabel):
            _make_label_selectable(label)

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
        self.navigation.setFixedHeight(240)
        for index, name in enumerate(_NAVIGATION, start=1):
            item = QListWidgetItem(f"{index:02d}   {name}")
            item.setSizeHint(QSize(188, 34))
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
        if name == "SETTINGS":
            return self._build_settings_page(page)
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
        controls = self._build_chat_controls()
        layout.addWidget(controls)
        layout.addSpacing(12)

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

        chat_bar = self.chat_scroll.verticalScrollBar()
        chat_bar.rangeChanged.connect(
            self._on_chat_scroll_range_changed
        )
        chat_bar.valueChanged.connect(
            self._on_chat_scroll_value_changed
        )
        chat_bar.sliderPressed.connect(
            self._on_chat_scroll_slider_pressed
        )
        chat_bar.sliderReleased.connect(
            self._on_chat_scroll_slider_released
        )

        self.evidence_rail.setVisible(False)

        conversation_row.addWidget(self.chat_scroll, 1)
        conversation_row.addWidget(self.evidence_rail)
        layout.addLayout(conversation_row, 1)

        layout.addSpacing(12)
        layout.addWidget(self._build_knowledge_review_panel())

        layout.addSpacing(14)
        layout.addWidget(_rule())
        layout.addSpacing(14)

        self.evidence_chain = self._build_evidence_chain()
        layout.addWidget(self.evidence_chain)

        self._render_empty_chat(
            "Connect to ATHENA Core to load a conversation."
        )
        return page
    def _build_chat_controls(self) -> QWidget:
        controls = QFrame()
        controls.setObjectName("sessionControls")
        layout = QHBoxLayout(controls)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        chat_label = QLabel("CHAT")
        chat_label.setObjectName("sessionLabel")
        layout.addWidget(chat_label)
        layout.addWidget(self.chat_selector, 1)
        layout.addWidget(self.new_chat_button)
        layout.addWidget(self.delete_chat_button)
        layout.addSpacing(10)

        model_label = QLabel("MODEL")
        model_label.setObjectName("sessionLabel")
        layout.addWidget(model_label)
        layout.addWidget(self.model_selector, 1)
        return controls
    def _apply_control_snapshot(self, snapshot: DesktopApiSnapshot) -> None:
        llms = tuple(model for model in snapshot.models if model.model_type == "llm")
        previous_model = self._selected_model_id()
        self._models_by_id = {model.backend_model_id: model for model in llms}

        self.model_selector.blockSignals(True)
        try:
            self.model_selector.clear()
            for model in llms:
                state = "LOADED" if model.loaded else "AVAILABLE"
                self.model_selector.addItem(
                    f"{model.display_name} · {state}",
                    model.backend_model_id,
                )
                index = self.model_selector.count() - 1
                self.model_selector.setItemData(
                    index,
                    QColor("#63D98B" if model.loaded else TEXT_DIM),
                    Qt.ItemDataRole.ForegroundRole,
                )
                self.model_selector.setItemData(
                    index,
                    (
                        "Loaded in LM Studio and ready for chat"
                        if model.loaded
                        else "Available in LM Studio but not currently loaded"
                    ),
                    Qt.ItemDataRole.ToolTipRole,
                )
            if llms:
                loaded = next((model for model in llms if model.loaded), None)
                target_model = (
                    previous_model
                    if previous_model in self._models_by_id
                    else loaded.backend_model_id
                    if loaded is not None
                    else llms[0].backend_model_id
                )
                target_index = self.model_selector.findData(target_model)
                self.model_selector.setCurrentIndex(max(0, target_index))
        finally:
            self.model_selector.blockSignals(False)

        committed_chat_id = self._committed_chat_id()
        selector_target = (
            self.pending_chat_id
            if self.pending_chat_id is not None
            else committed_chat_id
        )

        self.chat_selector.blockSignals(True)
        try:
            self.chat_selector.clear()
            self.chat_selector.addItem("NEW CHAT", None)

            for chat in snapshot.chats:
                suffix = "MSG" if chat.message_count == 1 else "MSGS"
                self.chat_selector.addItem(
                    f"{chat.chat_id[:8].upper()} · {chat.message_count} {suffix}",
                    chat.chat_id,
                )

            target_index = self.chat_selector.findData(
                selector_target
            )

            if selector_target is not None and target_index < 0:
                fallback_state = (
                    "LOADING"
                    if selector_target == self.pending_chat_id
                    else "CURRENT"
                )
                self.chat_selector.addItem(
                    f"{selector_target[:8].upper()} · {fallback_state}",
                    selector_target,
                )
                target_index = self.chat_selector.count() - 1

            self.chat_selector.setCurrentIndex(
                max(0, target_index)
            )
            self.selected_chat_id = selector_target
        finally:
            self.chat_selector.blockSignals(False)

        self._configure_context_for_selected_model()
        selected = self._selected_model()
        self.model_selector.setStyleSheet(
            "color: #63D98B;"
            if selected is not None and selected.loaded
            else f"color: {TEXT_MUTED};"
            if selected is not None
            else ""
        )
    def _build_settings_page(self, page: QWidget) -> QWidget:
        layout = QVBoxLayout(page)
        layout.setContentsMargins(8, 0, 18, 28)
        layout.setSpacing(18)

        title = QLabel("LOCAL MODEL / INFERENCE SETTINGS")
        title.setObjectName("speaker")
        layout.addWidget(title)

        intro = QLabel(
            "Per-model session controls. CTX is the total request context. "
            "Both CTX and MAX OUTPUT can be set precisely in the numeric fields "
            "or adjusted with their sliders."
        )
        intro.setObjectName("settingsHelp")
        intro.setWordWrap(True)
        layout.addWidget(intro)
        layout.addWidget(_rule())

        model_row = QHBoxLayout()
        model_row.addWidget(QLabel("MODEL"))
        self.settings_model_value.setObjectName("settingsValue")
        model_row.addWidget(self.settings_model_value, 1)
        layout.addLayout(model_row)

        ctx_row = QHBoxLayout()
        ctx_label = QLabel("CTX")
        ctx_label.setObjectName("settingsLabel")
        ctx_row.addWidget(ctx_label)
        ctx_row.addWidget(self.context_slider, 1)
        ctx_row.addWidget(self.context_spin)
        layout.addLayout(ctx_row)

        output_row = QHBoxLayout()
        output_label = QLabel("MAX OUTPUT TOKENS")
        output_label.setObjectName("settingsLabel")
        output_row.addWidget(output_label)
        output_row.addWidget(self.max_output_slider, 1)
        output_row.addWidget(self.max_output_spin)
        layout.addLayout(output_row)

        temperature_row = QHBoxLayout()
        temperature_label = QLabel("TEMPERATURE")
        temperature_label.setObjectName("settingsLabel")
        temperature_row.addWidget(temperature_label)
        temperature_row.addStretch(1)
        temperature_row.addWidget(self.temperature_spin)
        layout.addLayout(temperature_row)

        thinking_row = QHBoxLayout()
        thinking_label = QLabel("THINKING")
        thinking_label.setObjectName("settingsLabel")
        thinking_row.addWidget(thinking_label)
        thinking_row.addStretch(1)
        thinking_row.addWidget(self.thinking_checkbox)
        layout.addLayout(thinking_row)

        note = QLabel(
            "THINKING OFF sends reasoning_effort=none. THINKING ON allows the "
            "selected model/provider to use reasoning when supported. MAX OUTPUT "
            "is bounded by the selected CTX minus ATHENA's safety reserve because "
            "LM Studio discovery does not expose a separate per-model output ceiling."
        )
        note.setObjectName("settingsHelp")
        note.setWordWrap(True)
        layout.addWidget(note)
        layout.addStretch(1)
        return page

    def _selected_model_id(self) -> str | None:
        value = self.model_selector.currentData()
        return value if isinstance(value, str) and value else None

    def _selected_model(self) -> ModelResponse | None:
        model_id = self._selected_model_id()
        if model_id is None:
            return None
        return self._models_by_id.get(model_id)

    def _effective_context_limit(self) -> int | None:
        model = self._selected_model()
        if model is None:
            return None
        runtime_limit = model.loaded_context_length or model.context_capacity
        if runtime_limit is None:
            return None
        return self.context_spin.value()

    def _max_output_tokens(self) -> int | None:
        if self._selected_model() is None:
            return None
        return self.max_output_spin.value()

    def _temperature(self) -> float | None:
        if self._selected_model() is None:
            return None
        return float(self.temperature_spin.value())

    def _thinking_enabled(self) -> bool | None:
        if self._selected_model() is None:
            return None
        return self.thinking_checkbox.isChecked()

    def _update_ready_state(self) -> None:
        model = self._selected_model()
        self._core_ready = (
            self._core_transport_ready
            and self._provider_ready
            and model is not None
            and model.loaded
        )
        if self._core_ready:
            self.status_text.setText("LOCAL / READY")
        elif self._last_model_error is not None:
            self.status_text.setText("LOCAL / MODEL ERROR")
        elif not self._provider_ready:
            self.status_text.setText("LOCAL / PROVIDER UNAVAILABLE")
        elif model is None:
            self.status_text.setText("LOCAL / MODEL REQUIRED")
        else:
            self.status_text.setText("LOCAL / MODEL NOT LOADED")

    def _configure_context_for_selected_model(self) -> None:
        model = self._selected_model()
        controls = (
            self.context_slider,
            self.context_spin,
            self.max_output_slider,
            self.max_output_spin,
            self.temperature_spin,
            self.thinking_checkbox,
        )
        for control in controls:
            control.blockSignals(True)
        try:
            if model is None:
                self.settings_model_value.setText("—")
                self.settings_model_value.setStyleSheet("")
                self.context_slider.setRange(1, 1)
                self.context_spin.setRange(1, 1)
                self.context_slider.setValue(1)
                self.context_spin.setValue(1)
                self.context_value_label.setText("—")
                self.context_metric.set_value("—")
                self.max_output_slider.setRange(1, 1)
                self.max_output_spin.setRange(1, 1)
                self.max_output_slider.setValue(1)
                self.max_output_spin.setValue(1)
                self.temperature_spin.setValue(0.7)
                self.thinking_checkbox.setChecked(False)
                self.thinking_checkbox.setText("OFF — REASONING DISABLED")
                return

            state = "LOADED" if model.loaded else "AVAILABLE / NOT LOADED"
            self.settings_model_value.setText(f"{model.display_name} · {state}")
            self.settings_model_value.setStyleSheet(
                "color: #63D98B;" if model.loaded else f"color: {TEXT_MUTED};"
            )

            runtime_limit = model.loaded_context_length or model.context_capacity
            if runtime_limit is None:
                self.context_slider.setRange(1, 1)
                self.context_spin.setRange(1, 1)
                self.context_slider.setValue(1)
                self.context_spin.setValue(1)
                self.context_value_label.setText("AUTO")
                self.context_metric.set_value("AUTO")
                output_max = 131_072
            else:
                minimum = min(4096, runtime_limit)
                context_step = min(1024, runtime_limit)
                context_page = min(8192, runtime_limit)
                self.context_slider.setRange(minimum, runtime_limit)
                self.context_slider.setSingleStep(context_step)
                self.context_slider.setPageStep(context_page)
                self.context_spin.setRange(minimum, runtime_limit)
                self.context_spin.setSingleStep(context_step)

                remembered = self._context_by_model.get(model.backend_model_id)
                target = runtime_limit if remembered is None else remembered
                target = max(minimum, min(target, runtime_limit))
                self.context_slider.setValue(target)
                self.context_spin.setValue(target)
                self._context_by_model[model.backend_model_id] = target
                formatted = _format_context(target)
                self.context_value_label.setText(formatted)
                self.context_metric.set_value(formatted)
                output_max = max(1, target - 256)

            self.max_output_slider.setRange(1, output_max)
            self.max_output_slider.setSingleStep(min(256, output_max))
            self.max_output_slider.setPageStep(min(2048, output_max))
            self.max_output_spin.setRange(1, output_max)
            self.max_output_spin.setSingleStep(min(256, output_max))

            remembered_output = self._max_output_by_model.get(model.backend_model_id)
            output_target = (
                min(8192, output_max)
                if remembered_output is None
                else max(1, min(remembered_output, output_max))
            )
            self.max_output_slider.setValue(output_target)
            self.max_output_spin.setValue(output_target)
            self._max_output_by_model[model.backend_model_id] = output_target

            temperature = self._temperature_by_model.get(model.backend_model_id, 0.7)
            self.temperature_spin.setValue(temperature)
            self._temperature_by_model[model.backend_model_id] = temperature

            thinking = self._thinking_by_model.get(model.backend_model_id, False)
            self.thinking_checkbox.setChecked(thinking)
            self.thinking_checkbox.setText(
                "ON — MODEL REASONING ALLOWED"
                if thinking
                else "OFF — REASONING DISABLED"
            )
            self._thinking_by_model[model.backend_model_id] = thinking
        finally:
            for control in controls:
                control.blockSignals(False)

    def _on_model_selected(self, _index: int) -> None:
        self._configure_context_for_selected_model()
        model = self._selected_model()
        if model is not None:
            self.local_model_metric.set_value(model.display_name)
            self.model_metric.set_value(model.display_name)
            self.model_selector.setStyleSheet(
                "color: #63D98B;" if model.loaded else f"color: {TEXT_MUTED};"
            )
        else:
            self.local_model_metric.set_value("none selected")
            self.model_metric.set_value("—")
            self.model_selector.setStyleSheet("")
        self._update_ready_state()
        self._sync_composer_enabled()

    def _on_context_changed(self, value: int) -> None:
        model_id = self._selected_model_id()
        if model_id is None:
            return

        if self.context_spin.value() != value:
            self.context_spin.blockSignals(True)
            try:
                self.context_spin.setValue(value)
            finally:
                self.context_spin.blockSignals(False)

        self._context_by_model[model_id] = value
        formatted = _format_context(value)
        self.context_value_label.setText(formatted)
        self.context_metric.set_value(formatted)
        self._apply_output_ceiling(value)

    def _on_context_spin_changed(self, value: int) -> None:
        if self.context_slider.value() != value:
            self.context_slider.blockSignals(True)
            try:
                self.context_slider.setValue(value)
            finally:
                self.context_slider.blockSignals(False)
        self._on_context_changed(value)

    def _apply_output_ceiling(self, context_value: int) -> None:
        output_max = max(1, context_value - 256)
        current = min(self.max_output_spin.value(), output_max)

        self.max_output_slider.blockSignals(True)
        self.max_output_spin.blockSignals(True)
        try:
            self.max_output_slider.setMaximum(output_max)
            self.max_output_spin.setMaximum(output_max)
            self.max_output_slider.setValue(current)
            self.max_output_spin.setValue(current)
        finally:
            self.max_output_slider.blockSignals(False)
            self.max_output_spin.blockSignals(False)

        model_id = self._selected_model_id()
        if model_id is not None:
            self._max_output_by_model[model_id] = current

    def _on_max_output_changed(self, value: int) -> None:
        if self.max_output_slider.value() != value:
            self.max_output_slider.blockSignals(True)
            try:
                self.max_output_slider.setValue(value)
            finally:
                self.max_output_slider.blockSignals(False)
        model_id = self._selected_model_id()
        if model_id is not None:
            self._max_output_by_model[model_id] = value

    def _on_max_output_slider_changed(self, value: int) -> None:
        if self.max_output_spin.value() != value:
            self.max_output_spin.blockSignals(True)
            try:
                self.max_output_spin.setValue(value)
            finally:
                self.max_output_spin.blockSignals(False)
        model_id = self._selected_model_id()
        if model_id is not None:
            self._max_output_by_model[model_id] = value

    def _on_temperature_changed(self, value: float) -> None:
        model_id = self._selected_model_id()
        if model_id is not None:
            self._temperature_by_model[model_id] = float(value)

    def _on_thinking_changed(self, checked: bool) -> None:
        self.thinking_checkbox.setText(
            "ON — MODEL REASONING ALLOWED"
            if checked
            else "OFF — REASONING DISABLED"
        )
        self.thinking_checkbox.setToolTip(
            "Thinking is ON: the selected model may reason if it supports reasoning."
            if checked
            else "Thinking is OFF: ATHENA explicitly disables reasoning for this request."
        )
        model_id = self._selected_model_id()
        if model_id is not None:
            self._thinking_by_model[model_id] = checked

    def _transient_key(self) -> str:
        return self.current_chat_id or "__NEW_CHAT__"

    def _remember_transient_failure(self, operation: str, message: str) -> None:
        key = self._transient_key()
        records = self._transient_failures.setdefault(key, [])
        record = (self._last_rendered_sequence, operation, message)
        if record not in records:
            records.append(record)

    def _append_transient_failures_for_sequence(
        self,
        key: str,
        sequence_no: int,
    ) -> None:
        for anchor, operation, message in self._transient_failures.get(key, []):
            if anchor == sequence_no:
                self._append_chat_operation_failure(
                    operation=operation,
                    message=message,
                )

    def _append_new_chat_transient_failures(self) -> None:
        for _anchor, operation, message in self._transient_failures.get(
            "__NEW_CHAT__", []
        ):
            self._append_chat_operation_failure(
                operation=operation,
                message=message,
            )

    def _committed_chat_id(self) -> str | None:
        return (
            self.loaded_chat_id
            if self.loaded_chat_id is not None
            else self.current_chat_id
        )

    def _set_chat_selector_identity(
        self,
        chat_id: str | None,
        *,
        fallback_state: str,
    ) -> None:
        self.chat_selector.blockSignals(True)
        try:
            index = self.chat_selector.findData(chat_id)

            if index < 0:
                if chat_id is None:
                    self.chat_selector.insertItem(
                        0,
                        "NEW CHAT",
                        None,
                    )
                    index = 0
                else:
                    self.chat_selector.addItem(
                        f"{chat_id[:8].upper()} · {fallback_state}",
                        chat_id,
                    )
                    index = self.chat_selector.count() - 1

            self.chat_selector.setCurrentIndex(index)
        finally:
            self.chat_selector.blockSignals(False)

        self.selected_chat_id = chat_id

    def _commit_loaded_chat_identity(
        self,
        chat_id: str,
    ) -> None:
        self.current_chat_id = chat_id
        self.loaded_chat_id = chat_id
        self.pending_chat_id = None
        self._set_chat_selector_identity(
            chat_id,
            fallback_state="CURRENT",
        )
        self._sync_composer_enabled()

    def _rollback_pending_chat_selection(self) -> None:
        self.pending_chat_id = None
        self._set_chat_selector_identity(
            self._committed_chat_id(),
            fallback_state="CURRENT",
        )
        self._sync_composer_enabled()

    def _enter_new_chat_state(
        self,
        *,
        clear_transient: bool,
        message: str = "New persistent conversation. Type below to send the first message.",
    ) -> None:
        self.current_chat_id = None
        self.loaded_chat_id = None
        self.selected_chat_id = None
        self.pending_chat_id = None
        self._last_rendered_sequence = 0
        self._clear_knowledge_review()
        if clear_transient:
            self._transient_failures.pop("__NEW_CHAT__", None)
        self._set_chat_selector_identity(
            None,
            fallback_state="NEW",
        )
        self._render_empty_chat(message)
        self._append_new_chat_transient_failures()
        self._update_inspector_for_empty_chat()
        self._sync_composer_enabled()

    def _start_new_chat(self) -> None:
        if self._chat_busy or self.pending_chat_id is not None:
            return
        self._enter_new_chat_state(clear_transient=True)

    def _on_chat_selected(self, index: int) -> None:
        if index < 0:
            return

        if self._chat_busy:
            self._rollback_pending_chat_selection()
            return

        value = self.chat_selector.itemData(index)

        if value is None:
            self._enter_new_chat_state(clear_transient=True)
            return

        if not isinstance(value, str) or not value:
            self._rollback_pending_chat_selection()
            return

        committed_chat_id = self._committed_chat_id()

        if value == committed_chat_id:
            self.pending_chat_id = None
            self.selected_chat_id = value
            self._sync_composer_enabled()
            return

        controller = self.api_controller
        if controller is None:
            self._rollback_pending_chat_selection()
            return

        self.selected_chat_id = value
        self.pending_chat_id = value
        self._sync_composer_enabled()
        controller.load_chat(value)

    def _request_chat_deletion(self) -> None:
        controller = self.api_controller
        if (
            controller is None
            or self.current_chat_id is None
            or self._chat_busy
            or self.pending_chat_id is not None
        ):
            return
        controller.preview_chat_deletion(self.current_chat_id)

    def apply_chat_deletion_preview(self, preview: object) -> None:
        if not isinstance(preview, DeletionPreviewResponse):
            return
        if preview.entity_id != self.current_chat_id:
            self.apply_chat_operation_failure(
                "preview_delete",
                "Deletion preview belongs to another chat",
            )
            return

        owned_messages = sum(
            item.count
            for item in preview.dependencies
            if item.relation == "chat.owned_message"
        )
        message_word = "message" if owned_messages == 1 else "messages"

        dialog = QMessageBox(self)
        dialog.setWindowTitle("Delete chat")
        dialog.setIcon(QMessageBox.Icon.NoIcon)
        dialog.setText(
            f"Delete this persistent chat and its {owned_messages} {message_word}?\n\n"
            "ATHENA will use its canonical deletion ledger. This action is "
            "not retried automatically and cannot be undone from the desktop."
        )
        dialog.setStandardButtons(
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel
        )
        dialog.setDefaultButton(QMessageBox.StandardButton.Cancel)
        dialog.setEscapeButton(QMessageBox.StandardButton.Cancel)
        answer = QMessageBox.StandardButton(dialog.exec())
        if answer != QMessageBox.StandardButton.Yes:
            return

        controller = self.api_controller
        if controller is None:
            return
        chat_id = preview.entity_id
        digest = preview.preview_digest
        QTimer.singleShot(
            0,
            lambda: controller.delete_chat(
                chat_id,
                preview_digest=digest,
            ),
        )

    def apply_chat_deleted(self, chat_id: str) -> None:
        if chat_id == self.current_chat_id:
            self._transient_failures.pop(chat_id, None)
        self._enter_new_chat_state(
            clear_transient=True,
            message="Conversation deleted. Ready for a new chat.",
        )
        self.connection_detail.setText(
            "Chat deletion committed through ATHENA lifecycle deletion."
        )
        QTimer.singleShot(0, self.refresh_core_status)
    def _build_knowledge_review_panel(self) -> QFrame:
        panel = self.knowledge_review_panel
        panel.setObjectName("knowledgeReviewPanel")
        panel.setVisible(False)
        panel.setMinimumHeight(170)
        panel.setMaximumHeight(320)

        layout = QVBoxLayout(panel)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(8)

        header = QHBoxLayout()
        header.setContentsMargins(0, 0, 0, 0)
        header.setSpacing(8)
        title = QLabel("KNOWLEDGE REVIEW")
        title.setObjectName("knowledgeReviewTitle")
        self.knowledge_review_state.setObjectName("knowledgeReviewState")
        self.knowledge_review_close_button.setObjectName("knowledgeReviewCloseButton")
        self.knowledge_review_close_button.setToolTip("Close Knowledge review")
        self.knowledge_review_close_button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.knowledge_review_close_button.clicked.connect(
            self._close_knowledge_review
        )
        header.addWidget(title)
        header.addWidget(self.knowledge_review_state)
        header.addStretch(1)
        header.addWidget(self.knowledge_review_close_button)
        layout.addLayout(header)

        self.knowledge_review_items.setContentsMargins(0, 0, 6, 0)
        self.knowledge_review_items.setSpacing(8)
        self.knowledge_review_items.addStretch(1)

        self.knowledge_review_scroll.setObjectName("knowledgeReviewScroll")
        self.knowledge_review_scroll.setWidgetResizable(True)
        self.knowledge_review_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.knowledge_review_scroll.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        self.knowledge_review_scroll.setWidget(self.knowledge_review_content)
        layout.addWidget(self.knowledge_review_scroll, 1)
        return panel

    def _build_evidence_chain(self) -> QFrame:
        chain = QFrame()
        chain.setObjectName("evidenceChain")

        layout = QHBoxLayout(chain)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(16)

        title = QLabel("EVIDENCE CHAIN")
        title.setObjectName("chainTitle")
        self.evidence_chain_state.setObjectName("chainState")

        layout.addWidget(title)
        layout.addWidget(self.evidence_chain_state)
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

        self.ground_button.setObjectName("groundButton")
        self.ground_button.setCheckable(True)
        self.ground_button.setChecked(False)
        self.ground_button.setDisabled(True)
        self.ground_button.setToolTip(
            "Ground this turn in local Knowledge and Raw Archive evidence."
        )

        self.send_button.setObjectName("sendButton")
        self.send_button.setText("SEND")
        self.send_button.setToolTip("Send message ? Ctrl+Enter")
        self.send_button.setDisabled(True)
        self.send_button.clicked.connect(self._submit_prompt)

        self.chat_selector.setObjectName("chatSelector")
        self.chat_selector.setMinimumWidth(150)
        self.chat_selector.activated.connect(self._on_chat_selected)
        self.model_selector.setObjectName("modelSelector")
        self.model_selector.setMinimumWidth(180)
        self.model_selector.activated.connect(self._on_model_selected)
        self.context_slider.setObjectName("contextSlider")
        self.context_slider.setMinimumWidth(130)
        self.context_slider.valueChanged.connect(self._on_context_changed)
        self.delete_chat_button.setObjectName("deleteChatButton")
        self.delete_chat_button.setToolTip(
            "Preview and logically delete the selected persistent chat"
        )
        self.delete_chat_button.clicked.connect(self._request_chat_deletion)
        self.new_chat_button.setObjectName("newChatButton")
        self.new_chat_button.setToolTip("Start a new empty chat session")
        self.new_chat_button.clicked.connect(self._start_new_chat)
        self.context_spin.setObjectName("contextSpin")
        self.context_spin.setMinimumWidth(138)
        self.context_spin.setAccelerated(True)
        self.context_spin.setKeyboardTracking(False)
        self.context_spin.setToolTip("Enter the exact CTX token budget")
        self.context_spin.valueChanged.connect(self._on_context_spin_changed)

        self.max_output_slider.setObjectName("maxOutputSlider")
        self.max_output_slider.setMinimumWidth(180)
        self.max_output_slider.setToolTip(
            "Adjust MAX OUTPUT; use the numeric field for an exact token value"
        )
        self.max_output_slider.valueChanged.connect(
            self._on_max_output_slider_changed
        )

        self.max_output_spin.setObjectName("maxOutputTokens")
        self.max_output_spin.setMinimumWidth(138)
        self.max_output_spin.setAccelerated(True)
        self.max_output_spin.setKeyboardTracking(False)
        self.max_output_spin.setSingleStep(256)
        self.max_output_spin.setToolTip("Enter the exact MAX OUTPUT token budget")
        self.max_output_spin.valueChanged.connect(self._on_max_output_changed)
        self.temperature_spin.setObjectName("temperatureSpin")
        self.temperature_spin.setDecimals(2)
        self.temperature_spin.setRange(0.0, 2.0)
        self.temperature_spin.setSingleStep(0.05)
        self.temperature_spin.setValue(0.7)
        self.temperature_spin.valueChanged.connect(self._on_temperature_changed)
        self.thinking_checkbox.setObjectName("thinkingToggle")
        self.thinking_checkbox.setToolTip(
            "Thinking is OFF: ATHENA explicitly disables reasoning for this request."
        )
        self.thinking_checkbox.toggled.connect(self._on_thinking_changed)

        layout.addWidget(prompt)
        layout.addWidget(self.prompt_input, 1)
        layout.addWidget(attach)
        layout.addWidget(self.ground_button)
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
        provenance_header = QHBoxLayout()
        provenance_header.setContentsMargins(0, 0, 0, 0)
        provenance_header.setSpacing(8)
        provenance_header.addWidget(_section_label("PROVENANCE"))
        provenance_header.addStretch(1)
        self.inspector_copy_button.setObjectName("inspectorCopyButton")
        self.inspector_copy_button.setToolTip("Copy inspector provenance")
        self.inspector_copy_button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.inspector_copy_button.clicked.connect(
            lambda _checked=False: QApplication.clipboard().setText(
                self.inspector_provenance.text()
            )
        )
        provenance_header.addWidget(self.inspector_copy_button)
        layout.addLayout(provenance_header)

        self.inspector_provenance.setObjectName("inspectorBody")
        self.inspector_provenance.setWordWrap(True)
        self.inspector_provenance.setAlignment(
            Qt.AlignmentFlag.AlignTop
            | Qt.AlignmentFlag.AlignLeft
        )
        self.inspector_provenance.setSizePolicy(
            QSizePolicy.Policy.Preferred,
            QSizePolicy.Policy.Maximum,
        )

        inspector_content = QWidget()
        inspector_content.setObjectName("inspectorScrollContent")
        inspector_content_layout = QVBoxLayout(inspector_content)
        inspector_content_layout.setContentsMargins(0, 0, 8, 0)
        inspector_content_layout.setSpacing(0)
        inspector_content_layout.addWidget(
            self.inspector_provenance
        )
        inspector_content_layout.addStretch(1)

        self.inspector_scroll.setObjectName("inspectorScroll")
        self.inspector_scroll.setWidgetResizable(True)
        self.inspector_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.inspector_scroll.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        self.inspector_scroll.setVerticalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAsNeeded
        )
        self.inspector_scroll.setWidget(inspector_content)
        layout.addWidget(self.inspector_scroll, 1)

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
        controller.grounded_chat_sent.connect(
            self.apply_grounded_chat_sent
        )
        controller.chat_deletion_preview_ready.connect(
            self.apply_chat_deletion_preview
        )
        controller.chat_deleted.connect(self.apply_chat_deleted)
        controller.message_remembered.connect(self.apply_message_remembered)
        controller.knowledge_extraction_ready.connect(
            self.apply_knowledge_extraction_ready
        )
        controller.knowledge_review_ready.connect(self.apply_knowledge_review_ready)
        controller.knowledge_merge_review_ready.connect(
            self.apply_knowledge_merge_review_ready
        )
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

        self._apply_control_snapshot(snapshot)
        chat_freshness = snapshot.resolved_chat_freshness
        model_freshness = snapshot.resolved_model_freshness

        loaded_model = self._selected_model()
        model_name = (
            loaded_model.display_name
            if loaded_model is not None
            else "none loaded"
        )
        context = self._effective_context_limit()
        self.core_metric.set_value(snapshot.health.core_status)

        provider_status = (
            snapshot.provider.status
            if snapshot.provider is not None
            else "unavailable"
        )

        model_metric_value = (
            model_name
            if model_freshness == "fresh"
            else f"{model_name} · STALE"
            if model_freshness == "stale"
            else "UNAVAILABLE"
        )
        chat_metric_value = (
            str(len(snapshot.chats))
            if chat_freshness == "fresh"
            else f"{len(snapshot.chats)} · STALE"
            if chat_freshness == "stale"
            else "UNAVAILABLE"
        )

        self.provider_metric.set_value(provider_status)
        self.local_model_metric.set_value(model_metric_value)
        self.model_metric.set_value(model_metric_value)
        self.context_metric.set_value(_format_context(context))
        self.chat_metric.set_value(chat_metric_value)

        self._core_transport_ready = snapshot.health.core_status in {
            "ok",
            "ready",
            "running",
        }
        self._provider_ready = (
            provider_status == "ready"
            and model_freshness == "fresh"
        )
        self._last_model_error = snapshot.model_error
        self._update_ready_state()

        if snapshot.chat_error is not None:
            chat_state = (
                "STALE"
                if chat_freshness == "stale"
                else "UNAVAILABLE"
            )
            self.connection_detail.setText(
                f"Chat list {chat_state} · {snapshot.chat_error}"
            )
        elif snapshot.model_error is not None:
            model_state = (
                "STALE"
                if model_freshness == "stale"
                else "UNAVAILABLE"
            )
            self.connection_detail.setText(
                f"Model status {model_state} · {snapshot.model_error}"
            )
        elif not self._provider_ready:
            self.connection_detail.setText(
                "ATHENA Core is connected, but LM Studio is unavailable."
            )
        elif loaded_model is None:
            self.connection_detail.setText(
                "ATHENA Core is connected, but no local LLM is available."
            )
        elif not loaded_model.loaded:
            self.connection_detail.setText(
                "Selected model is available in LM Studio but is not loaded."
            )
        else:
            self.connection_detail.setText(
                f"Core connected · {len(snapshot.chats)} chats available."
            )

        if (
            self._committed_chat_id() is None
            and self.pending_chat_id is None
        ):
            self._enter_new_chat_state(
                clear_transient=False,
                message=(
                    "New persistent conversation. Type below to send the first message."
                ),
            )

        self._sync_composer_enabled()
    @Slot(str)
    def apply_api_failure(self, message: str) -> None:
        self._core_ready = False
        self._core_transport_ready = False
        self._provider_ready = False
        self._last_model_error = None
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

        if (
            self.pending_chat_id is not None
            and thread.chat_id != self.pending_chat_id
        ):
            return

        self._commit_loaded_chat_identity(
            thread.chat_id
        )
        self._render_chat_thread(thread)

    @Slot(object)
    def apply_chat_sent(self, thread: object) -> None:
        if not isinstance(thread, ChatThreadResponse):
            return
        self._commit_loaded_chat_identity(
            thread.chat_id
        )
        self.prompt_input.clear()
        self._render_chat_thread(thread)
        QTimer.singleShot(0, self.refresh_core_status)

    @Slot(object)
    def apply_grounded_chat_sent(self, response: object) -> None:
        if not isinstance(response, GroundedChatResponse):
            return

        self._commit_loaded_chat_identity(
            response.thread.chat_id
        )
        self.prompt_input.clear()
        self._render_chat_thread(
            response.thread,
            assistant_display_override=response.assistant_text,
        )

        self.inspector_object_id.setText(
            f"RUN / {response.processing_run_id[:8].upper()}"
        )
        self.inspector_heading.setText(
            "Grounded local response"
        )
        self.inspector_message_count.set_value(
            str(len(response.thread.messages))
        )
        self.inspector_mode.set_value("GROUNDED LOCAL")
        self.inspector_provenance.setText(
            _grounded_inspector_text(response)
        )
        self.evidence_chain_state.setText(
            _grounded_chain_summary(response)
        )

        # The old rail is a static illustration. Keep it hidden rather than
        # presenting decorative topology as real provenance.
        self.evidence_rail.setVisible(False)

        cited_count = sum(
            1 for item in response.evidence if item.cited
        )
        suffix = "" if cited_count == 1 else "s"
        self.connection_detail.setText(
            "Grounded local turn completed · "
            f"{cited_count} cited evidence item{suffix}."
        )
        QTimer.singleShot(0, self.refresh_core_status)

    @Slot(object)
    def apply_message_remembered(self, response: object) -> None:
        if not isinstance(response, RememberedChatMessageResponse):
            return
        if response.chat_id != self.current_chat_id:
            self.apply_chat_operation_failure(
                "remember",
                "Remember result belongs to another chat",
            )
            return
        self._remembered_message_revisions.add(
            (response.message_id, response.message_revision_id)
        )
        self._sync_message_action_buttons()
        self.connection_detail.setText(
            "Message remembered · memory " + response.memory_id[:8].upper() + "."
        )

    @Slot(object)
    def apply_knowledge_extraction_ready(self, response: object) -> None:
        if not isinstance(response, MessageKnowledgeExtractionResponse):
            return

        request = self._knowledge_review_request
        response_identity = (
            response.chat_id,
            response.message_id,
            response.message_revision_id,
        )

        if request is None or response_identity != request:
            return

        if response.chat_id != self.current_chat_id:
            self._clear_knowledge_review()
            return

        self._knowledge_review_chat_id = response.chat_id
        self._knowledge_extraction = response
        self._knowledge_review = None
        self._render_knowledge_review_panel()
        self.knowledge_review_panel.setVisible(True)
        self.inspector_object_id.setText(
            f"RUN / {response.processing_run_id[:8].upper()}"
        )
        self.inspector_heading.setText("Knowledge extraction review")
        self.inspector_mode.set_value("KNOWLEDGE REVIEW")
        self.inspector_provenance.setText(
            "Frozen extraction from persisted chat message "
            f"{response.message_id[:8].upper()} revision "
            f"{response.message_revision_id[:8].upper()}. "
            "Canonical Knowledge is unchanged until an explicit acceptance step."
        )
        self.connection_detail.setText(
            "Knowledge extraction complete · canonical deduplication preflight pending."
        )

        run_id = response.processing_run_id
        QTimer.singleShot(
            0,
            lambda: self._prepare_knowledge_review_if_active(run_id),
        )

    @Slot(object)
    def apply_knowledge_review_ready(self, response: object) -> None:
        if not isinstance(response, KnowledgeReviewResponse):
            return
        extraction = self._knowledge_extraction
        if (
            extraction is None
            or response.processing_run_id != extraction.processing_run_id
        ):
            return
        self._knowledge_review = response
        self._render_knowledge_review_panel()
        self.knowledge_review_panel.setVisible(True)
        if response.ready_to_accept:
            detail = "Knowledge review complete · proposal set is ready for explicit acceptance."
        elif response.blocked_reason == "canonical_merge_candidates":
            detail = "Knowledge review requires explicit canonical merge decisions."
        elif response.blocked_reason == "extractor_merge_candidates":
            detail = "Knowledge review is blocked by extractor merge candidates."
        else:
            detail = "Knowledge review is blocked pending explicit resolution."
        self.connection_detail.setText(detail)

    @Slot(object)
    def apply_knowledge_merge_review_ready(self, response: object) -> None:
        if not isinstance(response, KnowledgeMergeReviewResponse):
            return
        extraction = self._knowledge_extraction
        if extraction is None:
            return
        self.knowledge_review_state.setText(
            "MERGE DECISION SAVED / REFRESHING PREFLIGHT"
        )
        self.connection_detail.setText(
            "Merge decision saved · "
            + (response.decision or response.status).replace("_", " ").upper()
            + "."
        )
        run_id = extraction.processing_run_id
        QTimer.singleShot(
            0,
            lambda: self._prepare_knowledge_review_if_active(run_id),
        )

    @Slot(str, str)
    def apply_chat_operation_failure(
        self,
        operation: str,
        message: str,
    ) -> None:
        if operation == "load":
            self._rollback_pending_chat_selection()

        knowledge_operations = {
            "extract_knowledge",
            "prepare_knowledge_review",
            "load_merge_review",
            "resolve_merge_review",
        }

        if (
            operation in knowledge_operations
            and self._knowledge_review_request is None
            and self._knowledge_extraction is None
        ):
            return

        operation_label = (
            "Grounded chat"
            if operation == "send_grounded"
            else "Chat deletion"
            if operation in {"preview_delete", "delete"}
            else "Remember"
            if operation == "remember"
            else "Chat loading"
            if operation == "load"
            else "Knowledge extraction"
            if operation == "extract_knowledge"
            else "Knowledge review"
            if operation in {
                "prepare_knowledge_review",
                "load_merge_review",
                "resolve_merge_review",
            }
            else "Direct chat"
        )
        retry_note = (
            " ATHENA did not retry the mutation DELETE automatically."
            if operation == "delete"
            else " ATHENA did not retry the mutation POST automatically."
            if operation in {
                "send",
                "send_grounded",
                "remember",
                "extract_knowledge",
                "prepare_knowledge_review",
                "resolve_merge_review",
            }
            else ""
        )
        detail = f"{operation_label} failed: {message}.{retry_note}"
        self.connection_detail.setText(detail)
        self.status_text.setText("LOCAL / CHAT ERROR")
        self.inspector_object_id.setText("CHAT / ERROR")
        self.inspector_heading.setText(
            f"{operation_label} failed"
        )
        self.inspector_provenance.setText(detail)
        if operation in {
            "extract_knowledge",
            "prepare_knowledge_review",
            "load_merge_review",
            "resolve_merge_review",
        }:
            self.knowledge_review_panel.setVisible(True)
            self.knowledge_review_state.setText("ERROR / " + operation.upper())
        if operation in {"send", "send_grounded"}:
            self._remember_transient_failure(operation, message)
            self._append_chat_operation_failure(
                operation=operation,
                message=message,
            )
            self._schedule_chat_tail_follow(force=True)
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
            or self.pending_chat_id is not None
        ):
            return

        content = self.prompt_input.text().strip()
        if not content:
            return

        if self.ground_button.isChecked():
            controller.send_grounded_message(
                chat_id=self.current_chat_id,
                content=content,
                model_id=self._selected_model_id(),
                effective_context_limit=self._effective_context_limit(),
                max_output_tokens=self._max_output_tokens(),
                temperature=self._temperature(),
                thinking_enabled=self._thinking_enabled(),
            )
        else:
            controller.send_message(
                chat_id=self.current_chat_id,
                content=content,
                model_id=self._selected_model_id(),
                effective_context_limit=self._effective_context_limit(),
                max_output_tokens=self._max_output_tokens(),
                temperature=self._temperature(),
                thinking_enabled=self._thinking_enabled(),
            )

    @Slot(int, int)
    def _on_chat_scroll_range_changed(
        self,
        _minimum: int,
        _maximum: int,
    ) -> None:
        if self._chat_follow_tail and not self._chat_slider_active:
            self._schedule_chat_tail_follow()

    @Slot(int)
    def _on_chat_scroll_value_changed(self, value: int) -> None:
        if self._chat_scroll_programmatic:
            return
        bar = self.chat_scroll.verticalScrollBar()
        self._chat_follow_tail = (
            bar.maximum() - value <= 24
        )

    @Slot()
    def _on_chat_scroll_slider_pressed(self) -> None:
        self._chat_slider_active = True

    @Slot()
    def _on_chat_scroll_slider_released(self) -> None:
        self._chat_slider_active = False
        bar = self.chat_scroll.verticalScrollBar()
        self._chat_follow_tail = (
            bar.maximum() - bar.value() <= 24
        )

    def _scroll_chat_to_bottom(self) -> None:
        if (
            not self._chat_follow_tail
            or self._chat_slider_active
        ):
            return
        bar = self.chat_scroll.verticalScrollBar()
        self._chat_scroll_programmatic = True
        try:
            bar.setValue(bar.maximum())
        finally:
            self._chat_scroll_programmatic = False

    def _schedule_chat_tail_follow(
        self,
        *,
        force: bool = False,
    ) -> None:
        if force:
            self._chat_follow_tail = True
        if (
            not self._chat_follow_tail
            or self._chat_slider_active
        ):
            return
        # rangeChanged keeps following while wrapped QLabel geometry settles.
        QTimer.singleShot(0, self._scroll_chat_to_bottom)

    def _append_chat_operation_failure(
        self,
        *,
        operation: str,
        message: str,
    ) -> None:
        container = QWidget()
        container.setObjectName("chatOperationFailure")

        layout = QVBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 18)
        layout.setSpacing(8)

        meta = QLabel("ATHENA  /  ERROR  /  NOT PERSISTED")
        meta.setObjectName("speaker")
        _make_label_selectable(meta)

        if operation == "send_grounded":
            summary = "GROUNDING FAILED / NO ASSISTANT MESSAGE PERSISTED"
        else:
            summary = "CHAT SEND FAILED / NO ASSISTANT MESSAGE PERSISTED"

        rendered = f"{summary}\n{message}"
        body = _AutoHeightMessageLabel(rendered)
        body.setObjectName("message")
        body.setTextFormat(Qt.TextFormat.PlainText)
        _make_label_selectable(body)
        body.setWordWrap(True)

        copy_button = QPushButton("⧉")
        copy_button.setObjectName("copyMessageButton")
        copy_button.setAccessibleName("Copy chat error")
        copy_button.setToolTip("Copy error")
        copy_button.setFlat(True)
        copy_button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        copy_button.setFixedSize(26, 22)
        copy_button.setStyleSheet(
            "QPushButton { border: none; background: transparent; color: "
            + TEXT_MUTED
            + "; padding: 0; } "
            "QPushButton:hover { color: "
            + ORANGE
            + "; }"
        )
        copy_button.clicked.connect(
            lambda _checked=False, text=rendered: (
                QApplication.clipboard().setText(text)
            )
        )

        header = QHBoxLayout()
        header.setContentsMargins(0, 0, 0, 0)
        header.setSpacing(8)
        header.addWidget(meta)
        header.addStretch(1)
        header.addWidget(copy_button)

        layout.addLayout(header)
        layout.addWidget(body)
        layout.addWidget(_rule())

        insert_index = max(
            0,
            self.chat_messages_layout.count() - 1,
        )
        self.chat_messages_layout.insertWidget(
            insert_index,
            container,
        )

    def _sync_composer_enabled(self) -> None:
        enabled = (
            self.api_controller is not None
            and self._core_ready
            and not self._chat_busy
            and self.pending_chat_id is None
        )
        self.prompt_input.setEnabled(enabled)
        self.ground_button.setEnabled(enabled)
        self.send_button.setEnabled(enabled)
        controls_available = (
            self.api_controller is not None
            and not self._chat_busy
            and self.pending_chat_id is None
        )
        self.chat_selector.setEnabled(controls_available)
        self.delete_chat_button.setEnabled(
            controls_available and self.current_chat_id is not None
        )
        model_available = controls_available and self._selected_model() is not None
        self.model_selector.setEnabled(
            controls_available and self.model_selector.count() > 0
        )
        self.new_chat_button.setEnabled(controls_available)
        model = self._selected_model()
        context_known = (
            model is not None
            and (model.loaded_context_length or model.context_capacity) is not None
        )
        self.context_slider.setEnabled(model_available and context_known)
        self.context_spin.setEnabled(model_available and context_known)
        self.max_output_slider.setEnabled(model_available)
        self.max_output_spin.setEnabled(model_available)
        self.temperature_spin.setEnabled(model_available)
        self.thinking_checkbox.setEnabled(model_available)
        self._sync_message_action_buttons()

    def _sync_message_action_buttons(self) -> None:
        controls_available = (
            self.api_controller is not None
            and self.current_chat_id is not None
            and not self._chat_busy
            and self.pending_chat_id is None
        )
        for button in self.chat_messages_widget.findChildren(
            QPushButton,
            "rememberMessageButton",
        ):
            message_id = button.property("messageId")
            revision_id = button.property("messageRevisionId")
            remembered = (
                isinstance(message_id, str)
                and isinstance(revision_id, str)
                and (message_id, revision_id) in self._remembered_message_revisions
            )
            button.setText("REMEMBERED" if remembered else "REMEMBER")
            button.setEnabled(controls_available and not remembered)
        for button in self.chat_messages_widget.findChildren(
            QPushButton,
            "addKnowledgeButton",
        ):
            button.setEnabled(controls_available and self._core_ready)
        for button in self.knowledge_review_panel.findChildren(
            QPushButton,
            "knowledgeMergeButton",
        ):
            button.setEnabled(controls_available)
    def _render_empty_chat(self, message: str) -> None:
        self._clear_chat_messages()
        label = QLabel(message)
        label.setObjectName("emptyChatState")
        label.setWordWrap(True)
        _make_label_selectable(label)
        self.chat_messages_layout.addWidget(label)
        self.chat_messages_layout.addStretch(1)

    def _render_chat_thread(
        self,
        thread: ChatThreadResponse,
        *,
        assistant_display_override: str | None = None,
    ) -> None:
        self._clear_chat_messages()
        if self._knowledge_review_chat_id != thread.chat_id:
            self._clear_knowledge_review()
        self._last_rendered_sequence = 0
        transient_key = thread.chat_id

        override_sequence: int | None = None
        if assistant_display_override is not None:
            override_sequence = next(
                (
                    message.sequence_no
                    for message in reversed(thread.messages)
                    if message.message_type == "assistant"
                ),
                None,
            )
            if override_sequence is None:
                raise ValueError(
                    "Grounded response has no assistant message."
                )

        if not thread.messages:
            self._render_empty_chat(
                "This conversation is empty. Type below to send the first message."
            )
        else:
            for message in thread.messages:
                display_content = message.content
                if (
                    assistant_display_override is not None
                    and message.sequence_no == override_sequence
                ):
                    display_content = assistant_display_override

                self.chat_messages_layout.addWidget(
                    self._message_widget(
                        role=message.message_type,
                        content=display_content,
                        created_at_us=message.created_at_us,
                        sequence_no=message.sequence_no,
                        message_id=message.message_id,
                        revision_id=message.revision_id,
                    )
                )
                self._last_rendered_sequence = max(
                    self._last_rendered_sequence,
                    message.sequence_no,
                )
                self._append_transient_failures_for_sequence(
                    transient_key,
                    message.sequence_no,
                )
            self.chat_messages_layout.addStretch(1)

        self.inspector_object_id.setText(
            f"CHAT / {thread.chat_id[:8].upper()}"
        )
        self.inspector_heading.setText("Persistent conversation · local history")
        self.inspector_message_count.set_value(str(len(thread.messages)))
        self.inspector_mode.set_value("DIRECT")
        self.inspector_provenance.setText(
            "No grounded provenance is attached to ordinary direct chat. "
            "ATHENA will populate source → evidence → claim → knowledge here "
            "only for responses that actually carry those relationships."
        )
        self.evidence_rail.setVisible(False)
        self.evidence_chain_state.setText(
            "DIRECT / PROVENANCE NOT ATTACHED"
        )

        self._schedule_chat_tail_follow(force=True)
    def _message_widget(
        self,
        *,
        role: str,
        content: str | None,
        created_at_us: int,
        sequence_no: int,
        message_id: str,
        revision_id: str,
    ) -> QWidget:
        container = QWidget()
        container.setObjectName("chatMessage")
        container.setProperty("messageId", message_id)
        container.setProperty("messageRevisionId", revision_id)
        container.setProperty("messageSequence", sequence_no)
        container.setProperty("messageRole", role)

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

        header = QHBoxLayout()
        header.setContentsMargins(0, 0, 0, 0)
        header.setSpacing(8)

        meta = QLabel(
            f"{display_role}  /  {timestamp}  /  {sequence_no:04d}"
        )
        meta.setObjectName("userMeta" if role == "user" else "speaker")
        _make_label_selectable(meta)

        copy_button = QPushButton("⧉")
        copy_button.setObjectName("copyMessageButton")
        copy_button.setProperty("messageSequence", sequence_no)
        copy_button.setProperty("messageRole", role)
        copy_button.setProperty("messageId", message_id)
        copy_button.setProperty("messageRevisionId", revision_id)
        copy_button.setAccessibleName(
            f"Copy {display_role.lower()} message"
        )
        copy_button.setToolTip("Copy message")
        copy_button.setFlat(True)
        copy_button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        copy_button.setFixedSize(26, 22)
        copy_button.setStyleSheet(
            "QPushButton { border: none; background: transparent; color: "
            + TEXT_MUTED
            + "; padding: 0; } "
            "QPushButton:hover { color: "
            + ORANGE
            + "; }"
        )
        copy_text = content or ""
        copy_button.clicked.connect(
            lambda _checked=False, text=copy_text: (
                QApplication.clipboard().setText(text)
            )
        )

        remember_button = QPushButton("REMEMBER")
        remember_button.setObjectName("rememberMessageButton")
        remember_button.setProperty("messageId", message_id)
        remember_button.setProperty("messageRevisionId", revision_id)
        remember_button.setProperty("messageSequence", sequence_no)
        remember_button.setProperty("messageRole", role)
        remember_button.setToolTip("Store this exact persisted message in Personal Memory")
        remember_button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        remember_button.clicked.connect(
            lambda _checked=False, mid=message_id, rid=revision_id: (
                self._remember_message(mid, rid)
            )
        )

        knowledge_button = QPushButton("ADD TO KNOWLEDGE")
        knowledge_button.setObjectName("addKnowledgeButton")
        knowledge_button.setProperty("messageId", message_id)
        knowledge_button.setProperty("messageRevisionId", revision_id)
        knowledge_button.setProperty("messageSequence", sequence_no)
        knowledge_button.setProperty("messageRole", role)
        knowledge_button.setToolTip(
            "Extract Knowledge proposals from this exact persisted message"
        )
        knowledge_button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        knowledge_button.clicked.connect(
            lambda _checked=False, mid=message_id, rid=revision_id: (
                self._extract_message_knowledge(mid, rid)
            )
        )

        header.addWidget(meta)
        header.addStretch(1)
        header.addWidget(remember_button)
        header.addWidget(knowledge_button)
        header.addWidget(copy_button)

        body = _AutoHeightMessageLabel(copy_text)
        body.setObjectName(
            "userMessage" if role == "user" else "message"
        )
        body.setTextFormat(Qt.TextFormat.PlainText)
        _make_label_selectable(body)
        body.setWordWrap(True)

        layout.addLayout(header)
        layout.addWidget(body)
        layout.addWidget(_rule())
        return container

    def _remember_message(self, message_id: str, revision_id: str) -> None:
        controller = self.api_controller
        chat_id = self.current_chat_id
        if (
            controller is None
            or chat_id is None
            or self._chat_busy
            or self.pending_chat_id is not None
        ):
            return
        controller.remember_message(
            chat_id=chat_id,
            message_id=message_id,
            revision_id=revision_id,
        )

    def _extract_message_knowledge(self, message_id: str, revision_id: str) -> None:
        controller = self.api_controller
        chat_id = self.current_chat_id
        if (
            controller is None
            or chat_id is None
            or self._chat_busy
            or self.pending_chat_id is not None
            or not self._core_ready
        ):
            return
        self._knowledge_review_request = (
            chat_id,
            message_id,
            revision_id,
        )
        self._knowledge_review_chat_id = chat_id
        self._knowledge_extraction = None
        self._knowledge_review = None
        self.knowledge_review_panel.setVisible(True)
        self.knowledge_review_state.setText("EXTRACTING / SELECTED MESSAGE")
        controller.extract_message_knowledge(
            chat_id=chat_id,
            message_id=message_id,
            revision_id=revision_id,
            model_id=self._selected_model_id(),
            effective_context_limit=self._effective_context_limit(),
            max_output_tokens=self._max_output_tokens(),
        )

    def _prepare_knowledge_review_if_active(
        self,
        processing_run_id: str,
    ) -> None:
        controller = self.api_controller
        extraction = self._knowledge_extraction

        if (
            controller is None
            or self._knowledge_review_request is None
            or extraction is None
            or extraction.processing_run_id != processing_run_id
        ):
            return

        controller.prepare_knowledge_review(
            processing_run_id
        )

    def _close_knowledge_review(self) -> None:
        self._clear_knowledge_review()
        if self.current_chat_id is not None:
            self.inspector_object_id.setText(
                f"CHAT / {self.current_chat_id[:8].upper()}"
            )
            self.inspector_heading.setText("Persistent conversation · local history")
            self.inspector_mode.set_value("DIRECT")
            self.inspector_provenance.setText(
                "No Knowledge proposal is selected. Direct chat does not invent "
                "source relationships."
            )

    def _clear_knowledge_review(self) -> None:
        self._knowledge_review_request = None
        self._knowledge_review_chat_id = None
        self._knowledge_extraction = None
        self._knowledge_review = None
        self.knowledge_review_panel.setVisible(False)
        self.knowledge_review_state.setText("IDLE")
        self._clear_knowledge_review_items()

    def _clear_knowledge_review_items(self) -> None:
        while self.knowledge_review_items.count():
            item = self.knowledge_review_items.takeAt(0)
            if item is None:
                break
            widget = item.widget()
            if widget is not None:
                widget.setParent(None)
                widget.deleteLater()
        self.knowledge_review_items.addStretch(1)

    def _add_knowledge_review_item(
        self,
        *,
        title: str,
        body: str,
    ) -> None:
        card = QFrame()
        card.setObjectName("knowledgeReviewItem")
        layout = QVBoxLayout(card)
        layout.setContentsMargins(10, 8, 10, 8)
        layout.setSpacing(4)
        heading = QLabel(title)
        heading.setObjectName("knowledgeReviewItemTitle")
        text = QLabel(body)
        text.setObjectName("knowledgeReviewItemBody")
        text.setTextFormat(Qt.TextFormat.PlainText)
        text.setWordWrap(True)
        _make_label_selectable(text)
        layout.addWidget(heading)
        layout.addWidget(text)
        insert_index = max(0, self.knowledge_review_items.count() - 1)
        self.knowledge_review_items.insertWidget(insert_index, card)

    def _add_canonical_merge_candidate(
        self,
        candidate: CanonicalMergeReviewResponse,
    ) -> None:
        card = QFrame()
        card.setObjectName("knowledgeReviewItem")
        layout = QVBoxLayout(card)
        layout.setContentsMargins(10, 8, 10, 8)
        layout.setSpacing(6)

        prefix = "K" if candidate.proposal_type == "knowledge" else "C"
        heading = QLabel(
            f"{prefix}{candidate.proposal_index:02d} / POSSIBLE CANONICAL DUPLICATE "
            f"/ {candidate.similarity:.0%}"
        )
        heading.setObjectName("knowledgeReviewItemTitle")
        detail = QLabel(
            f"Existing {candidate.existing_entity_id[:8].upper()} · {candidate.reason}"
        )
        detail.setObjectName("knowledgeReviewItemBody")
        detail.setWordWrap(True)
        _make_label_selectable(detail)

        actions = QHBoxLayout()
        actions.setContentsMargins(0, 0, 0, 0)
        actions.setSpacing(6)
        merge_button = QPushButton("MERGE")
        merge_button.setObjectName("knowledgeMergeButton")
        merge_button.setProperty("reviewId", candidate.review_id)
        merge_button.setProperty("decision", "merge")
        merge_button.clicked.connect(
            lambda _checked=False, rid=candidate.review_id: (
                self._resolve_knowledge_merge(rid, "merge")
            )
        )
        separate_button = QPushButton("KEEP SEPARATE")
        separate_button.setObjectName("knowledgeMergeButton")
        separate_button.setProperty("reviewId", candidate.review_id)
        separate_button.setProperty("decision", "keep_separate")
        separate_button.clicked.connect(
            lambda _checked=False, rid=candidate.review_id: (
                self._resolve_knowledge_merge(rid, "keep_separate")
            )
        )
        actions.addWidget(merge_button)
        actions.addWidget(separate_button)
        actions.addStretch(1)

        layout.addWidget(heading)
        layout.addWidget(detail)
        layout.addLayout(actions)
        insert_index = max(0, self.knowledge_review_items.count() - 1)
        self.knowledge_review_items.insertWidget(insert_index, card)

    def _resolve_knowledge_merge(self, review_id: str, decision: str) -> None:
        controller = self.api_controller
        if controller is None or self._chat_busy:
            return
        if decision not in {"merge", "keep_separate"}:
            return
        self.knowledge_review_state.setText("SAVING MERGE DECISION")
        controller.resolve_knowledge_merge_review(
            review_id,
            decision=decision,
        )

    def _render_knowledge_review_panel(self) -> None:
        extraction = self._knowledge_extraction
        if extraction is None:
            return
        self._clear_knowledge_review_items()

        self._add_knowledge_review_item(
            title=(
                f"RUN {extraction.processing_run_id[:8].upper()} / "
                f"MODEL {extraction.model_id}"
            ),
            body=(
                f"Message {extraction.message_id[:8].upper()} · "
                f"{len(extraction.knowledge_units)} Knowledge · "
                f"{len(extraction.claims)} Claims · "
                f"{len(extraction.relations)} Relations"
            ),
        )

        for knowledge_proposal in extraction.knowledge_units:
            heading = (
                f"K{knowledge_proposal.proposal_index:02d} / "
                f"{knowledge_proposal.knowledge_kind.upper()} / "
                f"{knowledge_proposal.confidence:.0%}"
            )
            title = (
                knowledge_proposal.title.strip()
                if knowledge_proposal.title
                else ""
            )
            body = (
                knowledge_proposal.body
                if not title
                else f"{title}\n{knowledge_proposal.body}"
            )
            self._add_knowledge_review_item(title=heading, body=body)

        for claim_proposal in extraction.claims:
            self._add_knowledge_review_item(
                title=(
                    f"C{claim_proposal.proposal_index:02d} / "
                    f"{claim_proposal.claim_kind.upper()} / "
                    f"{claim_proposal.confidence:.0%}"
                ),
                body=claim_proposal.statement,
            )

        if extraction.relations:
            relation_lines = tuple(
                f"{relation.left_type[0].upper()}{relation.left_index:02d} "
                f"{relation.relation_type.upper()} "
                f"{relation.right_type[0].upper()}{relation.right_index:02d} "
                f"/ {relation.confidence:.0%}"
                for relation in extraction.relations
            )
            self._add_knowledge_review_item(
                title="RELATIONS",
                body="\n".join(relation_lines),
            )

        if extraction.extractor_merge_candidates:
            lines = tuple(
                f"{merge_candidate.proposal_type.upper()} "
                f"{merge_candidate.proposal_index:02d} / "
                f"{merge_candidate.reason} / {merge_candidate.confidence:.0%}"
                for merge_candidate in extraction.extractor_merge_candidates
            )
            self._add_knowledge_review_item(
                title="EXTRACTOR MERGE CANDIDATES / BLOCKING",
                body="\n".join(lines),
            )

        review = self._knowledge_review
        if review is None:
            self.knowledge_review_state.setText("PREFLIGHT / PENDING")
            return

        decision_lines = tuple(
            f"K{knowledge_decision.proposal_index:02d}  "
            f"{knowledge_decision.action.replace('_', ' ').upper()}"
            + (
                f"  → {knowledge_decision.existing_entity_id[:8].upper()}"
                if knowledge_decision.existing_entity_id is not None
                else ""
            )
            for knowledge_decision in review.knowledge_decisions
        ) + tuple(
            f"C{claim_decision.proposal_index:02d}  "
            f"{claim_decision.action.replace('_', ' ').upper()}"
            + (
                f"  → {claim_decision.existing_entity_id[:8].upper()}"
                if claim_decision.existing_entity_id is not None
                else ""
            )
            for claim_decision in review.claim_decisions
        )
        if decision_lines:
            self._add_knowledge_review_item(
                title="CANONICAL PREFLIGHT",
                body="\n".join(decision_lines),
            )

        for candidate in review.canonical_merge_candidates:
            self._add_canonical_merge_candidate(candidate)

        if review.ready_to_accept:
            self.knowledge_review_state.setText("REVIEW COMPLETE / READY")
        elif review.blocked_reason == "canonical_merge_candidates":
            self.knowledge_review_state.setText("DECISION REQUIRED / CANONICAL MERGE")
        elif review.blocked_reason == "extractor_merge_candidates":
            self.knowledge_review_state.setText("BLOCKED / EXTRACTOR MERGE")
        else:
            self.knowledge_review_state.setText("BLOCKED / REVIEW REQUIRED")

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
            "Ready for a new persistent conversation"
        )
        self.inspector_message_count.set_value("0")
        self.inspector_mode.set_value("DIRECT")
        self.inspector_provenance.setText(
            "No provenance object is selected. Direct chat does not invent "
            "source relationships."
        )
        self.evidence_rail.setVisible(False)
        self.evidence_chain_state.setText(
            "DIRECT / PROVENANCE NOT ATTACHED"
        )

    def _select_page(self, index: int) -> None:
        if not 0 <= index < self.pages.count():
            return
        self.pages.setCurrentIndex(index)
        name = _NAVIGATION[index]
        self.page_title.setText(name)
        self.ascii_panel.set_context(name)


def _clip_inspector_text(
    value: str,
    *,
    limit: int = 180,
) -> str:
    normalized = " ".join(value.split())
    if len(normalized) <= limit:
        return normalized
    return normalized[: limit - 1].rstrip() + "…"


def _grounded_chain_summary(
    response: GroundedChatResponse,
) -> str:
    counts: dict[str, int] = {}
    for item in response.evidence:
        counts[item.evidence_class] = (
            counts.get(item.evidence_class, 0) + 1
        )

    parts = [
        f"{len(response.grounding.cited_context_ids)} CITED"
    ]
    for evidence_class in (
        "canonical",
        "source",
        "research",
        "news",
        "user_statement",
        "conversation_record",
    ):
        count = counts.get(evidence_class, 0)
        if count:
            parts.append(
                f"{evidence_class.upper()} {count}"
            )

    if response.personal_memory:
        parts.append(
            f"MEMORY {len(response.personal_memory)}"
        )

    return "GROUND / " + " / ".join(parts)


def _grounded_inspector_text(
    response: GroundedChatResponse,
) -> str:
    lines = [
        "Grounding validated by ATHENA.",
        (
            f"CITED {len(response.grounding.cited_context_ids)}"
            f" / CONTEXT {len(response.evidence)}"
        ),
    ]

    flags: list[str] = []
    if response.grounding.uses_inference:
        flags.append("INFERENCE")
    if response.grounding.uses_model_prior:
        flags.append("MODEL PRIOR")
    if response.grounding.uses_unknown:
        flags.append("UNKNOWN")
    if flags:
        lines.append("FLAGS  " + " / ".join(flags))

    for item in response.evidence:
        lines.append("")
        state = "CITED" if item.cited else "CONTEXT"
        lines.append(
            f"{item.context_id}  "
            f"{item.evidence_class.upper()} / "
            f"{item.entity_type.upper()}  {state}"
        )

        if item.epistemic_status is not None:
            lines.append(
                "STATUS  " + item.epistemic_status.upper()
            )

        if item.evidence_class == "source":
            source_parts: list[str] = []
            if item.source_name:
                source_parts.append(item.source_name)
            if item.page_start is not None:
                if (
                    item.page_end is not None
                    and item.page_end != item.page_start
                ):
                    source_parts.append(
                        f"pp. {item.page_start}–{item.page_end}"
                    )
                else:
                    source_parts.append(
                        f"p. {item.page_start}"
                    )
            if (
                item.start_offset is not None
                and item.end_offset is not None
            ):
                source_parts.append(
                    f"{item.start_offset}:{item.end_offset}"
                )
            if source_parts:
                lines.append(" · ".join(source_parts))
        elif item.title:
            lines.append(item.title)

        lines.append(_clip_inspector_text(item.text))

    if response.personal_memory:
        lines.extend(
            (
                "",
                "PERSONAL MEMORY / CONTEXT ONLY",
                "Not promoted to factual evidence.",
            )
        )
        for memory_item in response.personal_memory:
            lines.append(
                f"{memory_item.context_id}  {memory_item.memory_kind.upper()}"
            )
            lines.append(
                _clip_inspector_text(memory_item.content)
            )

    return "\n".join(lines)


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


def _make_label_selectable(label: QLabel) -> None:
    label.setTextInteractionFlags(
        label.textInteractionFlags()
        | Qt.TextInteractionFlag.TextSelectableByMouse
        | Qt.TextInteractionFlag.TextSelectableByKeyboard
    )


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
