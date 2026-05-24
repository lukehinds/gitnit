"""Copyable text widget for GitNit."""

from __future__ import annotations

from rich.markup import escape
from textual.app import ComposeResult
from textual.widget import Widget
from textual.widgets import Static


class CopyableText(Widget):
    """A text block that can be copied to clipboard with a keybinding."""

    DEFAULT_CSS = """
    CopyableText {
        height: auto;
    }

    CopyableText .panel-content {
        height: auto;
        min-height: 1;
    }
    """

    def __init__(self, text: str = "", title: str = "", **kwargs) -> None:
        super().__init__(**kwargs)
        self._text = text
        self._title = title

    def compose(self) -> ComposeResult:
        if self._title:
            yield Static(self._title, classes="panel-title")
        yield Static(escape(self._text), classes="panel-content", id="copyable-content")

    def update_text(self, text: str) -> None:
        self._text = text
        try:
            content = self.query_one("#copyable-content", Static)
            content.update(escape(text))
        except Exception:
            pass

    @property
    def text(self) -> str:
        return self._text

    def copy_to_clipboard(self) -> bool:
        """Copy text to system clipboard. Returns True on success."""
        if self._text and self.app:
            self.app.copy_to_clipboard(self._text)
            return True
        return False
