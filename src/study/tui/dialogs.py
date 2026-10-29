"""Confirmation before deleting, and the theme picker."""

from __future__ import annotations

from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.screen import ModalScreen
from textual.widgets import Label, ListView, Static

from .. import themes
from .widgets import Row, VimList


class ConfirmModal(ModalScreen[bool]):
    BINDINGS = [
        Binding("y", "answer(True)", "Delete", show=False),
        Binding("n,escape", "answer(False)", "Keep", show=False),
    ]

    def __init__(self, title: str, detail: str = "", yes: str = "delete") -> None:
        super().__init__()
        self.title_text, self.detail, self.yes = title, detail, yes

    def compose(self) -> ComposeResult:
        with Vertical(id="form"):
            yield Label(self.title_text, id="form-title")
            if self.detail:
                yield Static(self.detail, classes="confirm-detail")
            yield Static(f"y {self.yes} · n or esc keep it", id="form-hint")

    def action_answer(self, answer: bool) -> None:
        self.dismiss(answer)


def theme_row(p: themes.Palette) -> Text:
    text = Text(f"{p.label:<38}")
    for color in p.accents:
        text.append("■ ", style=color)
    text.append("  ")
    for color, word in ((p.success, "done"), (p.warning, "soon"), (p.error, "late")):
        text.append(word, style=color)
        text.append(" ")
    return text


class ThemePicker(ModalScreen[str | None]):
    """Moving through the list previews each theme; enter keeps it, esc puts the old one back."""

    BINDINGS = [Binding("escape", "cancel", "Cancel", show=False)]

    def __init__(self, current: str) -> None:
        super().__init__()
        self.original = current

    def compose(self) -> ComposeResult:
        with Vertical(id="picker"):
            yield Label("Theme", id="form-title")
            yield VimList(*[Row(theme_row(p), p.name) for p in themes.THEMES], id="theme-list")
            yield Static("↑↓ / j k preview · enter keep · esc cancel", id="form-hint")

    def on_mount(self) -> None:
        names = [p.name for p in themes.THEMES]
        lv = self.query_one("#theme-list", VimList)
        lv.index = names.index(self.original) if self.original in names else 0
        lv.focus()

    def on_list_view_highlighted(self, event: ListView.Highlighted) -> None:
        if event.item is not None:
            self.app.apply_theme(event.item.data)

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        event.stop()
        self.dismiss(event.item.data)

    def action_cancel(self) -> None:
        self.app.apply_theme(self.original)
        self.dismiss(None)
