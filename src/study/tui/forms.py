"""Small forms shown over the current screen. Enter saves, Esc cancels."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import Any

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.screen import ModalScreen
from textual.widgets import Input, Label, Select, Static


@dataclass
class Field:
    name: str
    label: str
    value: str = ""
    placeholder: str = ""
    options: Sequence[tuple[str, Any]] | None = None  # a Select instead of a text box
    optional: bool = False


@dataclass
class FormSpec:
    title: str
    fields: list[Field]
    # Gets the values by field name; returns an error message to show, or None when they're fine.
    check: Callable[[dict[str, Any]], str | None] = field(default=lambda values: None)
    hint: str = "enter save · esc cancel"


class FormModal(ModalScreen[dict[str, Any] | None]):
    BINDINGS = [Binding("escape", "cancel", "Cancel", show=False)]

    def __init__(self, spec: FormSpec) -> None:
        super().__init__()
        self.spec = spec

    def compose(self) -> ComposeResult:
        with Vertical(id="form"):
            yield Label(self.spec.title, id="form-title")
            for f in self.spec.fields:
                yield Label(f.label + (" (optional)" if f.optional else ""), classes="form-label")
                if f.options is not None:
                    yield Select(list(f.options), value=f.value if f.value != "" else Select.NULL,
                                 allow_blank=f.optional, id=f"f-{f.name}")
                else:
                    yield Input(value=f.value, placeholder=f.placeholder, id=f"f-{f.name}")
            yield Static("", id="form-error")
            yield Static(self.spec.hint, id="form-hint")

    def on_mount(self) -> None:
        first = self.query("Input, Select").first()
        first.focus()

    def values(self) -> dict[str, Any]:
        out: dict[str, Any] = {}
        for f in self.spec.fields:
            widget = self.query_one(f"#f-{f.name}")
            if isinstance(widget, Select):
                out[f.name] = None if widget.value is Select.NULL else widget.value
            else:
                out[f.name] = widget.value.strip()
        return out

    def on_input_submitted(self, event: Input.Submitted) -> None:
        event.stop()
        self.submit()

    def submit(self) -> None:
        values = self.values()
        missing = [f.label for f in self.spec.fields if not f.optional and values[f.name] in ("", None)]
        error = f"{missing[0]} is needed." if missing else self.spec.check(values)
        if error:
            self.query_one("#form-error", Static).update(error)
            return
        self.dismiss(values)

    def action_cancel(self) -> None:
        self.dismiss(None)
