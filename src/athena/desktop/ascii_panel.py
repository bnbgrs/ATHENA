"""Small deterministic visual-state surface for the ATHENA shell."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QTextCharFormat, QTextCursor
from PySide6.QtWidgets import QPlainTextEdit

from athena.desktop.theme import ORANGE

_IDLE = (
    "        .        ",
    "    .---+---.    ",
    "  .     |     .  ",
    "-----.  |  .-----",
    "     '---+---'    ",
    "        .        ",
)

_RESEARCH = (
    " .----.      .   ",
    " |    +------o   ",
    " o----+---.      ",
    "      |   +---o  ",
    "  .---o---'      ",
    "  '--------------",
)

_ARCHITECTURE = (
    " +------+  +---+ ",
    " |      +--+   | ",
    " +--+---+  +---+ ",
    "    |      /     ",
    " +--+-----+      ",
    " +--------+      ",
)


def ascii_scene(context: str) -> tuple[str, ...]:
    """Return a compact motif derived from a semantic context label."""
    normalized = context.casefold()
    if "research" in normalized or "source" in normalized:
        return _RESEARCH
    if "architect" in normalized or "knowledge" in normalized:
        return _ARCHITECTURE
    return _IDLE


class AsciiPanel(QPlainTextEdit):
    """Render ATHENA's compact visual state without becoming a terminal widget."""

    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("asciiPanel")
        self.setReadOnly(True)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setFixedHeight(134)
        self.set_context("idle")

    def set_context(self, context: str) -> None:
        scene = ascii_scene(context)
        self.setPlainText("\n".join(scene))
        self._accent_center()

    def _accent_center(self) -> None:
        document = self.document()
        cursor = QTextCursor(document)
        text = document.toPlainText()
        center = text.find("+")
        if center < 0:
            return

        cursor.setPosition(center)
        cursor.movePosition(QTextCursor.MoveOperation.Right, QTextCursor.MoveMode.KeepAnchor, 1)
        char_format = QTextCharFormat()
        char_format.setForeground(QColor(ORANGE))
        cursor.mergeCharFormat(char_format)
