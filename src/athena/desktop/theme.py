"""Visual constants for the ATHENA desktop shell."""
# ATHENA_V4914_UX_HARDENING

from __future__ import annotations

BACKGROUND = "#060606"
PANEL = "#0B0B0B"
PANEL_RAISED = "#101010"
BORDER = "#222222"
TEXT = "#F2F1ED"
TEXT_MUTED = "#AAA9A4"
TEXT_DIM = "#6F6F6B"
ORANGE = "#F26A21"

APP_STYLESHEET = f"""
QWidget {{
    background: {BACKGROUND};
    color: {TEXT};
    font-family: "Segoe UI Variable", "Segoe UI", sans-serif;
    font-size: 16px;
}}
QMainWindow {{ background: {BACKGROUND}; }}
QLabel {{ background: transparent; }}
QFrame#rail {{
    background: #090909;
    border: none;
    border-right: 1px solid {BORDER};
}}
QFrame#conversation {{ background: {BACKGROUND}; border: none; }}
QFrame#inspector {{
    background: #090909;
    border: none;
    border-left: 1px solid {BORDER};
}}
QFrame#rule {{ background: #202020; border: none; max-height: 1px; }}
QLabel#wordmark {{ color: {TEXT}; font-size: 17px; font-weight: 600; }}
QLabel#statusSquare {{ color: {ORANGE}; font-size: 10px; }}
QLabel#localStatus,
QLabel#networkState,
QLabel#breadcrumb,
QLabel#pageTitle,
QLabel#keyboardHint,
QLabel#userMeta,
QLabel#speaker,
QLabel#chainTitle,
QLabel#chainColumn,
QLabel#chainArrow,
QLabel#commandMeta,
QLabel#inspectorTitle,
QLabel#objectId,
QLabel#inspectorBody,
QLabel#monoBlock,
QLabel#jobHeader,
QLabel#jobMeta {{
    font-family: "Cascadia Mono", "Consolas", monospace;
}}
QLabel#localStatus {{ color: {TEXT_MUTED}; font-size: 12px; }}
QLabel[accent="true"] {{ color: {ORANGE}; }}
QLabel[role="section"] {{
    color: {TEXT_MUTED};
    font-family: "Cascadia Mono", "Consolas", monospace;
    font-size: 12px;
    font-weight: 600;
}}
QLabel[role="metric"] {{
    color: {TEXT};
    font-family: "Cascadia Mono", "Consolas", monospace;
    font-size: 12px;
}}
QLabel[role="muted"] {{ color: {TEXT_MUTED}; font-size: 13px; }}
QLabel[role="monoMuted"] {{
    color: {TEXT_MUTED};
    font-family: "Cascadia Mono", "Consolas", monospace;
    font-size: 11px;
}}
QLabel[role="dim"] {{
    color: {TEXT_DIM};
    font-family: "Cascadia Mono", "Consolas", monospace;
    font-size: 11px;
}}
QWidget#pallasVisualPlaceholder {{
    background: transparent;
    border: none;
}}
QListWidget#navigation {{
    background: transparent;
    border: none;
    outline: none;
    padding: 0;
}}
QListWidget#navigation::item {{
    color: {TEXT_MUTED};
    background: transparent;
    border: none;
    border-left: 1px solid transparent;
    padding: 8px 6px 8px 10px;
    margin: 0;
    font-family: "Cascadia Mono", "Consolas", monospace;
    font-size: 14px;
}}
QListWidget#navigation::item:selected {{
    color: {TEXT};
    background: transparent;
    border-left: 1px solid {ORANGE};
}}
QListWidget#navigation::item:hover {{ color: {TEXT}; background: {PANEL_RAISED}; }}
QPlainTextEdit#asciiPanel {{
    background: transparent;
    color: {TEXT_DIM};
    border: none;
    padding: 6px 0 0 0;
    selection-background-color: {ORANGE};
    selection-color: {BACKGROUND};
    font-family: "Cascadia Mono", "Consolas", monospace;
    font-size: 10px;
}}
QLabel#networkState {{ color: {TEXT_MUTED}; font-size: 12px; }}
QLabel#breadcrumb {{ color: {TEXT_MUTED}; font-size: 12px; }}
QLabel#pageTitle {{ color: {TEXT}; font-size: 14px; font-weight: 600; }}
QLabel#keyboardHint {{ color: #5F5F5B; font-size: 10px; }}
QLabel#userMeta {{ color: {ORANGE}; font-size: 12px; font-weight: 600; }}
QLabel#userMessage {{ color: {TEXT}; font-size: 18px; }}
QLabel#speaker {{ color: {ORANGE}; font-size: 12px; font-weight: 600; }}
QLabel#message,
QLabel#richMessage {{ color: {TEXT}; font-size: 18px; }}
QLabel#richMessage span.active,
QLabel#chainColumn span.active,
QLabel#inspectorBody span.active {{ color: {ORANGE}; }}
QLabel#richMessage span.cite {{ color: {TEXT_MUTED}; }}
QWidget#evidenceRail {{ background: transparent; border-left: 1px solid #1D1D1D; }}
QFrame#evidenceChain {{ background: transparent; border: none; }}
QLabel#chainTitle {{ color: {TEXT_MUTED}; font-size: 13px; font-weight: 600; }}
QLabel#chainColumn {{ color: {TEXT_MUTED}; font-size: 12px; }}
QLabel#chainArrow {{ color: {TEXT_DIM}; font-size: 14px; }}
QFrame#composer {{
    background: transparent;
    border: none;
    border-top: 1px solid {BORDER};
}}
QLabel#promptMarker {{
    color: {TEXT};
    font-family: "Cascadia Mono", "Consolas", monospace;
    font-size: 18px;
}}
QLineEdit#promptInput {{
    background: transparent;
    color: {TEXT};
    border: none;
    padding: 12px 4px;
    font-size: 16px;
}}
QLineEdit#promptInput:disabled {{ color: {TEXT_DIM}; }}
QLabel#commandMeta {{ color: {TEXT_DIM}; font-size: 10px; padding: 0 8px; }}
QPushButton#groundButton {{
    background: transparent;
    color: {TEXT_DIM};
    border: 1px solid {BORDER};
    padding: 5px 8px;
    font-family: "Cascadia Mono", "Consolas", monospace;
    font-size: 10px;
}}
QPushButton#groundButton:checked {{
    color: {ORANGE};
    border-color: {ORANGE};
}}
QPushButton#groundButton:disabled {{
    color: {TEXT_DIM};
    border-color: {BORDER};
}}
QPushButton#sendButton {{
    background: transparent;
    color: {TEXT_DIM};
    border: none;
    padding: 10px 0 10px 10px;
    font-family: "Cascadia Mono", "Consolas", monospace;
    font-size: 10px;
}}
QPushButton#sendButton:disabled {{ color: {TEXT_DIM}; }}
QLabel#inspectorTitle {{ color: {TEXT}; font-size: 15px; font-weight: 600; }}
QLabel#objectId {{ color: {ORANGE}; font-size: 13px; font-weight: 600; }}
QLabel#inspectorHeading {{ color: {TEXT}; font-size: 17px; font-weight: 500; }}
QLabel#inspectorBody,
QLabel#monoBlock {{ color: {TEXT_MUTED}; font-size: 12px; }}
QLabel#jobHeader {{ color: {ORANGE}; font-size: 11px; }}
QLabel#jobMeta {{ color: {TEXT_MUTED}; font-size: 11px; }}
QProgressBar#jobProgress {{
    background: {PANEL_RAISED};
    color: {TEXT_MUTED};
    border: none;
    height: 9px;
    text-align: right;
    font-family: "Cascadia Mono", "Consolas", monospace;
    font-size: 9px;
}}
QProgressBar#jobProgress::chunk {{ background: {ORANGE}; border: none; }}
QScrollBar:vertical {{ background: transparent; width: 7px; margin: 0; }}
QScrollBar::handle:vertical {{ background: {BORDER}; min-height: 28px; }}
QScrollBar::add-line:vertical,
QScrollBar::sub-line:vertical {{ height: 0; }}
QScrollArea#chatScroll {{
    background: transparent;
    border: none;
}}
QScrollArea#chatScroll > QWidget > QWidget {{
    background: transparent;
}}
QWidget#chatMessages {{
    background: transparent;
}}
QWidget#chatMessage {{
    background: transparent;
}}
QPushButton#rememberMessageButton,
QPushButton#addKnowledgeButton {{
    background: transparent;
    color: {TEXT_DIM};
    border: none;
    padding: 3px 5px;
    font-family: "Cascadia Mono", "Consolas", monospace;
    font-size: 9px;
}}
QPushButton#rememberMessageButton:hover,
QPushButton#addKnowledgeButton:hover {{
    color: {ORANGE};
}}
QPushButton#rememberMessageButton:disabled,
QPushButton#addKnowledgeButton:disabled {{
    color: #4D4D49;
}}
QLabel#emptyChatState {{
    color: {TEXT_DIM};
    font-size: 16px;
}}
QLabel#chainState {{
    color: {TEXT_DIM};
    font-family: "Cascadia Mono", "Consolas", monospace;
    font-size: 11px;
}}
QFrame#sessionControls {{
    background: transparent;
    border: none;
    min-height: 34px;
}}
QLabel#sessionLabel,
QLabel#sessionValue {{
    color: {TEXT_DIM};
    font-family: "Cascadia Mono", "Consolas", monospace;
    font-size: 10px;
}}
QLabel#sessionValue {{
    color: {TEXT_MUTED};
    min-width: 58px;
}}
QComboBox#chatSelector,
QComboBox#modelSelector {{
    background: #090909;
    color: {TEXT_MUTED};
    border: 1px solid {BORDER};
    border-radius: 0;
    padding: 5px 24px 5px 7px;
    font-family: "Cascadia Mono", "Consolas", monospace;
    font-size: 10px;
}}
QComboBox#chatSelector:hover,
QComboBox#modelSelector:hover {{
    border-color: #3A3A38;
    color: {TEXT};
}}
QComboBox#chatSelector::drop-down,
QComboBox#modelSelector::drop-down {{
    border: none;
    width: 18px;
}}
QComboBox QAbstractItemView {{
    background: #090909;
    color: {TEXT};
    border: 1px solid {BORDER};
    selection-background-color: {PANEL_RAISED};
    selection-color: {TEXT};
    outline: none;
}}
QSlider#contextSlider::groove:horizontal {{
    background: {BORDER};
    height: 2px;
}}
QSlider#contextSlider::sub-page:horizontal {{
    background: #555551;
    height: 2px;
}}
QSlider#contextSlider::handle:horizontal {{
    background: {ORANGE};
    border: none;
    width: 6px;
    margin: -5px 0;
}}
QPushButton#deleteChatButton {{
    background: transparent;
    color: {TEXT_DIM};
    border: 1px solid {BORDER};
    border-radius: 0;
    padding: 5px 7px;
    font-family: "Cascadia Mono", "Consolas", monospace;
    font-size: 9px;
}}
QPushButton#deleteChatButton:hover {{
    color: {ORANGE};
    border-color: #3A3A38;
}}
QPushButton#deleteChatButton:disabled,
QComboBox#chatSelector:disabled,
QComboBox#modelSelector:disabled {{
    color: #4D4D49;
}}

QPushButton#newChatButton {{
    background: transparent;
    color: {TEXT};
    border: 1px solid {BORDER};
    border-radius: 0;
    padding: 5px 9px;
    font-family: "Cascadia Mono", "Consolas", monospace;
    font-size: 9px;
}}
QPushButton#newChatButton:hover {{
    color: {ORANGE};
    border-color: #3A3A38;
}}
QLabel#settingsLabel,
QLabel#settingsValue,
QLabel#settingsHelp {{
    font-family: "Cascadia Mono", "Consolas", monospace;
}}
QLabel#settingsLabel {{
    color: {TEXT_DIM};
    font-size: 10px;
    min-width: 160px;
}}
QLabel#settingsValue {{
    color: {TEXT};
    font-size: 10px;
}}
QLabel#settingsHelp {{
    color: {TEXT_MUTED};
    font-size: 10px;
}}
QSpinBox#maxOutputTokens,
QDoubleSpinBox#temperatureSpin {{
    background: #090909;
    color: {TEXT};
    border: 1px solid {BORDER};
    border-radius: 0;
    padding: 5px 7px;
    min-width: 110px;
    font-family: "Cascadia Mono", "Consolas", monospace;
    font-size: 10px;
}}
QCheckBox#thinkingToggle {{
    color: {TEXT};
    spacing: 8px;
    font-family: "Cascadia Mono", "Consolas", monospace;
    font-size: 10px;
}}
QCheckBox#thinkingToggle::indicator {{
    width: 12px;
    height: 12px;
    border: 1px solid {BORDER};
    background: #090909;
}}
QCheckBox#thinkingToggle::indicator:checked {{
    background: {ORANGE};
}}


QLabel {{
    selection-background-color: {ORANGE};
    selection-color: {BACKGROUND};
}}
QSpinBox#contextSpin,
QSpinBox#maxOutputTokens {{
    min-width: 138px;
}}
QSlider#maxOutputSlider::groove:horizontal {{
    background: {BORDER};
    height: 2px;
}}
QSlider#maxOutputSlider::sub-page:horizontal {{
    background: #555551;
    height: 2px;
}}
QSlider#maxOutputSlider::handle:horizontal {{
    background: {ORANGE};
    border: none;
    width: 6px;
    margin: -5px 0;
}}
QCheckBox#thinkingToggle {{
    min-width: 250px;
    color: {TEXT_MUTED};
}}
QCheckBox#thinkingToggle:checked {{
    color: {ORANGE};
    font-weight: 600;
}}
QPushButton#inspectorCopyButton {{
    background: transparent;
    color: {TEXT_DIM};
    border: 1px solid {BORDER};
    border-radius: 0;
    padding: 3px 7px;
    font-family: "Cascadia Mono", "Consolas", monospace;
    font-size: 9px;
}}
QPushButton#inspectorCopyButton:hover {{
    color: {ORANGE};
    border-color: #3A3A38;
}}
QFrame#evidenceChain {{
    background: #080808;
    border: 1px solid #171717;
}}
QFrame#knowledgeReviewPanel {{
    background: #080808;
    border: 1px solid #1B1B1B;
}}
QLabel#knowledgeReviewTitle,
QLabel#knowledgeReviewState,
QLabel#knowledgeReviewItemTitle,
QLabel#knowledgeReviewItemBody {{
    font-family: "Cascadia Mono", "Consolas", monospace;
}}
QLabel#knowledgeReviewTitle {{
    color: {TEXT};
    font-size: 11px;
    font-weight: 600;
}}
QLabel#knowledgeReviewState {{
    color: {ORANGE};
    font-size: 10px;
}}
QFrame#knowledgeReviewItem {{
    background: #090909;
    border: 1px solid #171717;
}}
QLabel#knowledgeReviewItemTitle {{
    color: {TEXT_MUTED};
    font-size: 10px;
    font-weight: 600;
}}
QLabel#knowledgeReviewItemBody {{
    color: {TEXT};
    font-size: 11px;
}}
QScrollArea#knowledgeReviewScroll {{
    background: transparent;
    border: none;
}}
QScrollArea#knowledgeReviewScroll > QWidget > QWidget {{
    background: transparent;
}}
QPushButton#knowledgeReviewCloseButton,
QPushButton#knowledgeMergeButton {{
    background: transparent;
    color: {TEXT_DIM};
    border: 1px solid {BORDER};
    border-radius: 0;
    padding: 3px 7px;
    font-family: "Cascadia Mono", "Consolas", monospace;
    font-size: 9px;
}}
QPushButton#knowledgeReviewCloseButton:hover,
QPushButton#knowledgeMergeButton:hover {{
    color: {ORANGE};
    border-color: #3A3A38;
}}
QPushButton#knowledgeReviewCloseButton:disabled,
QPushButton#knowledgeMergeButton:disabled {{
    color: #4D4D49;
}}

"""
