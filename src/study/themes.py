"""Colour themes.

"terminal" (the default) uses the terminal's own palette and background. The others paint their own
background. Every theme also says which colours mean warning, urgent, done and info, and gives eight
course accents: a course using one of the default course colours shows that theme's matching accent,
so a blue course stays blue but becomes gruvbox blue. A colour you set yourself is always kept.

The active theme is module state: `set_active` switches it, and the rendering code reads it.
"""

from __future__ import annotations

from dataclasses import dataclass

from .models import COURSE_COLORS


@dataclass(frozen=True)
class Palette:
    name: str
    label: str
    textual: str  # Textual theme name
    warning: str  # behind / due within a week
    error: str  # overdue / due within 48 hours / high priority
    success: str  # confident
    info: str  # reviewed, confidence dots, bars
    accents: tuple[str, ...] = COURSE_COLORS  # same order as models.COURSE_COLORS
    dark: bool = True

    def course_color(self, color: str) -> str:
        try:
            return self.accents[COURSE_COLORS.index(color.lower())]
        except ValueError:
            return color


THEMES: tuple[Palette, ...] = (
    Palette("terminal", "Terminal (your terminal's colours)", "study", "yellow", "red", "green", "blue"),
    Palette("gruvbox", "Gruvbox dark", "gruvbox", "#fabd2f", "#fb4934", "#b8bb26", "#83a598",
            ("#83a598", "#fe8019", "#8ec07c", "#d3869b", "#fabd2f", "#b8bb26", "#fb4934", "#a89984")),
    Palette("gruvbox-light", "Gruvbox light", "gruvbox-light", "#b57614", "#9d0006", "#79740e", "#076678",
            ("#076678", "#af3a03", "#427b58", "#8f3f71", "#b57614", "#79740e", "#9d0006", "#7c6f64"), dark=False),
    Palette("nord", "Nord", "nord", "#EBCB8B", "#BF616A", "#A3BE8C", "#81A1C1",
            ("#88C0D0", "#D08770", "#8FBCBB", "#B48EAD", "#EBCB8B", "#A3BE8C", "#BF616A", "#81A1C1")),
    Palette("dracula", "Dracula", "dracula", "#F1FA8C", "#FF5555", "#50FA7B", "#8BE9FD",
            ("#8BE9FD", "#FFB86C", "#50FA7B", "#BD93F9", "#F1FA8C", "#FF79C6", "#FF5555", "#6272A4")),
    Palette("catppuccin-mocha", "Catppuccin Mocha", "catppuccin-mocha", "#F9E2AF", "#F38BA8", "#A6E3A1", "#89B4FA",
            ("#89B4FA", "#FAB387", "#94E2D5", "#CBA6F7", "#F9E2AF", "#A6E3A1", "#F5C2E7", "#9399B2")),
    Palette("catppuccin-latte", "Catppuccin Latte", "catppuccin-latte", "#DF8E1D", "#D20F39", "#40A02B", "#1E66F5",
            ("#1E66F5", "#FE640B", "#179299", "#8839EF", "#DF8E1D", "#40A02B", "#EA76CB", "#7C7F93"), dark=False),
    Palette("tokyo-night", "Tokyo Night", "tokyo-night", "#E0AF68", "#F7768E", "#9ECE6A", "#7AA2F7",
            ("#7AA2F7", "#FF9E64", "#73DACA", "#BB9AF7", "#E0AF68", "#9ECE6A", "#F7768E", "#A9B1D6")),
    Palette("solarized-dark", "Solarized dark", "solarized-dark", "#b58900", "#dc322f", "#859900", "#268bd2",
            ("#268bd2", "#cb4b16", "#2aa198", "#6c71c4", "#b58900", "#859900", "#d33682", "#93a1a1")),
    Palette("solarized-light", "Solarized light", "solarized-light", "#b58900", "#dc322f", "#859900", "#268bd2",
            ("#268bd2", "#cb4b16", "#2aa198", "#6c71c4", "#b58900", "#859900", "#d33682", "#586e75"), dark=False),
    Palette("rose-pine", "Rosé Pine", "rose-pine", "#f6c177", "#eb6f92", "#9ccfd8", "#c4a7e7",
            ("#9ccfd8", "#f6c177", "#3e8fb0", "#c4a7e7", "#ea9a97", "#a3be8c", "#eb6f92", "#908caa")),
    Palette("one-dark", "One Dark", "atom-one-dark", "#E5C07B", "#E06C75", "#98C379", "#61AFEF",
            ("#61AFEF", "#D19A66", "#56B6C2", "#C678DD", "#E5C07B", "#98C379", "#E06C75", "#ABB2BF")),
    Palette("monokai", "Monokai", "monokai", "#E6DB74", "#F92672", "#A6E22E", "#66D9EF",
            ("#66D9EF", "#FD971F", "#A6E22E", "#AE81FF", "#E6DB74", "#F92672", "#FD5FF0", "#75715E")),
)

BY_NAME = {p.name: p for p in THEMES}
DEFAULT = THEMES[0]
_active: Palette = DEFAULT


def get(name: str | None) -> Palette:
    return BY_NAME.get((name or "").strip().lower(), DEFAULT)


def active() -> Palette:
    return _active


def set_active(palette: Palette) -> None:
    global _active
    _active = palette


def course_color(color: str) -> str:
    """The colour to draw a course in under the active theme."""
    return _active.course_color(color)
