"""Visual constants for the ATHENA desktop shell."""

from __future__ import annotations

BACKGROUND = "#050505"
PANEL = "#0D0D0D"
PANEL_RAISED = "#111111"
BORDER = "#242424"
TEXT = "#F3F3F1"
TEXT_MUTED = "#949494"
TEXT_DIM = "#606060"
ORANGE = "#FF6A00"

APP_STYLESHEET = f"""
QWidget {{
    background: {BACKGROUND};
    color: {TEXT};
    font-family: "Segoe UI", "Inter", sans-serif;
    font-size: 14px;
}}
QMainWindow {{
    background: {BACKGROUND};
}}
QFrame#rail,
QFrame#contextPanel {{
    background: {PANEL};
    border: none;
}}
QFrame#rail {{
    border-right: 1px solid {BORDER};
}}
QFrame#contextPanel {{
    border-left: 1px solid {BORDER};
}}
QLabel#wordmark {{
    color: {TEXT};
    font-size: 18px;
    font-weight: 600;
}}
QLabel[role="section"] {{
    color: {TEXT_MUTED};
    font-size: 10px;
    font-weight: 600;
}}
QLabel[role="metric"] {{
    color: {TEXT};
    font-family: "Cascadia Mono", "Consolas", monospace;
    font-size: 11px;
}}
QLabel[role="muted"] {{
    color: {TEXT_MUTED};
}}
QLabel[role="dim"] {{
    color: {TEXT_DIM};
}}
QLabel[accent="true"] {{
    color: {ORANGE};
}}
QListWidget#navigation {{
    background: transparent;
    border: none;
    outline: none;
    padding: 0;
}}
QListWidget#navigation::item {{
    color: {TEXT_MUTED};
    border: none;
    border-left: 2px solid transparent;
    padding: 8px 8px 8px 12px;
    margin: 1px 0;
}}
QListWidget#navigation::item:selected {{
    color: {TEXT};
    background: transparent;
    border-left: 2px solid {ORANGE};
}}
QListWidget#navigation::item:hover {{
    color: {TEXT};
    background: {PANEL_RAISED};
}}
QPlainTextEdit#asciiPanel {{
    background: {BACKGROUND};
    color: {TEXT_MUTED};
    border: 1px solid {BORDER};
    border-radius: 4px;
    padding: 8px;
    selection-background-color: {ORANGE};
    selection-color: {BACKGROUND};
    font-family: "Cascadia Mono", "Consolas", monospace;
    font-size: 10px;
}}
QFrame#conversation {{
    background: {BACKGROUND};
    border: none;
}}
QLabel#pageTitle {{
    color: {TEXT};
    font-size: 13px;
    font-weight: 600;
}}
QLabel#speaker {{
    color: {TEXT_MUTED};
    font-size: 10px;
    font-weight: 600;
}}
QLabel#message {{
    color: {TEXT};
    font-size: 16px;
}}
QFrame#composer {{
    background: {PANEL};
    border-top: 1px solid {BORDER};
}}
QLineEdit#promptInput {{
    background: transparent;
    color: {TEXT};
    border: none;
    padding: 10px 4px;
    font-size: 15px;
}}
QLineEdit#promptInput:disabled {{
    color: {TEXT_DIM};
}}
QPushButton#sendButton {{
    background: transparent;
    color: {ORANGE};
    border: 1px solid {ORANGE};
    border-radius: 4px;
    min-width: 34px;
    min-height: 28px;
}}
QPushButton#sendButton:disabled {{
    color: {TEXT_DIM};
    border-color: {BORDER};
}}
QFrame#statusBar {{
    background: {BACKGROUND};
    border-top: 1px solid {BORDER};
}}
QLabel#statusText {{
    color: {TEXT_MUTED};
    font-family: "Cascadia Mono", "Consolas", monospace;
    font-size: 10px;
}}
QScrollBar:vertical {{
    background: {BACKGROUND};
    width: 7px;
    margin: 0;
}}
QScrollBar::handle:vertical {{
    background: {BORDER};
    min-height: 24px;
    border-radius: 3px;
}}
QScrollBar::add-line:vertical,
QScrollBar::sub-line:vertical {{
    height: 0;
}}
"""
