"""The Textual app: screens, the theme, the top bar and the once-a-second tick."""

from __future__ import annotations

import os
from datetime import datetime

from rich.table import Table
from rich.text import Text
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.screen import ModalScreen
from textual.theme import BUILTIN_THEMES, Theme
from textual.widgets import Static

from .. import notifier, themes
from ..config import Config
from ..logic.pomodoro import PomoPhase, remaining
from ..logic.stats import format_minutes
from ..pomo_watch import phase_message
from ..render import accent, warning
from ..storage import Store

HELP = """\
[b]Overview[/b]
  enter        open the highlighted subject (or the course of a deadline / weak spot)
  1–9          open subject 1–9 directly
  tab          next pane          j / k, ↑ / ↓   move
  a            add: a course (Subjects), a deadline (Deadlines), a weak spot (Weak spots)
  t            add a topic to the current course
  space        mark a deadline done / a weak spot resolved

[b]Subject[/b]
  esc          back to the overview          [ / ]   previous / next subject
  a            add to the focused pane: topic, weak spot, deadline, or log a session

[b]Anywhere[/b] (acts on the current course; on a subject, also the highlighted topic)
  l            log study time                w   note a weak spot
  s            start the timer; s again stops it and logs the session
  p            start a Pomodoro; while running, pause / resume
  n            next focus block (or skip the break)      P   stop the Pomodoro and log it
  e / d        edit / delete what's highlighted (E on a subject edits the course)
  + / -        change a topic's confidence   space on a topic   next status
  /            filter the lists (esc clears) T   pick a colour theme
  ?            this help                     q   quit

Every change is saved immediately. A running timer or Pomodoro keeps going if you quit.
"""


class HelpScreen(ModalScreen[None]):
    BINDINGS = [Binding("escape,question_mark,q", "dismiss", "Close")]

    def compose(self) -> ComposeResult:
        with Vertical(id="help"):
            yield Static(Text.from_markup(HELP))
            yield Static("esc to close", id="form-hint")


def _terminal_is_light() -> bool:
    """COLORFGBG ('15;0' = light text on dark) is set by many terminals; assume dark otherwise."""
    parts = os.environ.get("COLORFGBG", "").split(";")
    try:
        return int(parts[-1]) in (7, 15)
    except ValueError:
        return False


def study_theme() -> Theme:
    """Built on Textual's ANSI themes so the terminal's own background and colours show through."""
    base = BUILTIN_THEMES["ansi-light" if _terminal_is_light() else "ansi-dark"]
    variables = dict(base.variables)
    variables.update({
        "border": "ansi_blue",
        "border-blurred": "ansi_bright_black",  # muted grey on light and dark terminals alike
        "footer-key-foreground": "ansi_blue",
    })
    return Theme(
        name="study", ansi=True, dark=base.dark, primary=base.primary, secondary=base.secondary,
        warning="ansi_yellow", error="ansi_red", success="ansi_green", accent=base.accent,
        foreground=base.foreground, background=base.background, surface=base.surface, panel=base.panel,
        boost=base.boost, variables=variables,
    )


# Textual ships gruvbox dark only.
GRUVBOX_LIGHT = Theme(
    name="gruvbox-light", dark=False,
    primary="#076678", secondary="#427b58", accent="#af3a03",
    warning="#b57614", error="#9d0006", success="#79740e",
    foreground="#3c3836", background="#fbf1c7", surface="#f2e5bc", panel="#ebdbb2",
)


class StudyApp(App):
    CSS_PATH = "study.tcss"
    TITLE = "study"
    ENABLE_COMMAND_PALETTE = False
    BINDINGS = [
        Binding("T", "pick_theme", "Theme"),
        Binding("q", "quit", "Quit"),
        Binding("question_mark", "help", "Help", key_display="?"),
    ]

    def __init__(self, store: Store, cfg: Config) -> None:
        super().__init__()
        self.store = store
        self.cfg = cfg
        self._last_phase: PomoPhase | None = None

    def on_mount(self) -> None:
        self.register_theme(study_theme())
        self.register_theme(GRUVBOX_LIGHT)
        self.apply_theme(self.store.get_setting("theme", themes.DEFAULT.name))
        from .overview import OverviewScreen

        self.push_screen(OverviewScreen())
        run = self.store.get_pomodoro()
        self._last_phase = run.phase if run else None
        self.set_interval(1, self.tick)
        self.set_interval(30, self.refresh_everything)

    # ----- shared by screens -----

    def open_subject(self, course_id: int) -> None:
        from .subject import SubjectScreen

        self.push_screen(SubjectScreen(course_id))

    def refresh_everything(self) -> None:
        for screen in self.screen_stack:  # screens under a dialog too, so a theme preview shows through
            reload = getattr(screen, "reload", None)
            if reload is not None:
                self.call_later(reload)

    # ----- themes -----

    def apply_theme(self, name: str | None) -> None:
        palette = themes.get(name)
        themes.set_active(palette)
        self.theme = palette.textual
        self.refresh_everything()

    def action_pick_theme(self) -> None:
        from .dialogs import ThemePicker

        current = themes.active().name

        def keep(name: str | None) -> None:
            if name is not None:
                self.store.set_setting("theme", name)
                self.notify(f"Theme: {themes.get(name).label}.")

        self.push_screen(ThemePicker(current), keep)

    def action_help(self) -> None:
        self.push_screen(HelpScreen())

    def topbar(self, week_minutes: list[int] | None = None) -> Table:
        now = datetime.now()
        grid = Table.grid(expand=True)
        grid.add_column()
        grid.add_column(justify="right")
        left = Text("study", style="bold")
        left.append(f"  {now:%A} {now.day} {now:%B}", style="dim")
        grid.add_row(left, self._timer_text(now, week_minutes))
        return grid

    def _timer_text(self, now: datetime, week_minutes: list[int] | None) -> Text:
        run = self.store.get_pomodoro()
        if run:
            course = self.store.get_course(run.course_id)
            text = Text(f"Pomodoro · {run.phase.label}", style="bold")
            left = remaining(run, now, self.cfg.pomodoro)
            if run.paused:
                text.append(" · paused", style=warning())
            if left is not None:
                mins, secs = divmod(int(left.total_seconds()), 60)
                text.append(f" {mins:02d}:{secs:02d}")
            elif run.phase is PomoPhase.READY:
                text.append(" · press n for the next block", style=warning())
            if course:
                text.append(f"  {course.code}", style=accent(course))
            return text
        timer = self.store.get_timer()
        if timer:
            course = self.store.get_course(timer.course_id)
            text = Text("Timer ", style="bold")
            text.append(format_minutes(int((now - timer.started_at).total_seconds() // 60)))
            if course:
                text.append(f"  {course.code}", style=accent(course))
            text.append("  s to stop", style="dim")
            return text
        if week_minutes is not None:
            return Text(f"{format_minutes(sum(week_minutes))} this week", style="dim")
        return Text("")

    # ----- every second -----

    def tick(self) -> None:
        run, logged = self.store.settle_pomodoro(settings=self.cfg.pomodoro)
        phase = run.phase if run else None
        if run is not None and phase is not self._last_phase and self._last_phase is not None:
            if message := phase_message(run, self.cfg):
                title, body = message
                self.notify(body, title=title, timeout=8)
                self.bell()
                notifier.send(title, body)
        self._last_phase = phase
        if logged:
            self.refresh_everything()
        update = getattr(self.screen, "update_topbar", None)
        if update is not None:
            update()
