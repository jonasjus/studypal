"""The Textual app: screens, the theme, the top bar and the once-a-second tick."""

from __future__ import annotations

import os
from datetime import datetime, timedelta

from rich.table import Table
from rich.text import Text
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.screen import ModalScreen
from textual.theme import BUILTIN_THEMES, Theme
from textual.widgets import Static

from .. import alerts, notifier, themes
from ..config import Config
from ..logic.countdown import countdown
from ..logic.notify import banner_groups, within
from ..logic.pomodoro import PomoPhase, remaining
from ..models import Deadline
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
  r            reading list for the current course (from a topic: jumps to its chapter)
  ?            this help                     q   quit

[b]Reading list[/b]
  space        tick a section read · on a chapter: all its needed sections
  o            needed ⇄ optional (section, or a whole chapter)     enter   fold a chapter or book
  a            add sections by range: chapter 6, sections 6.1-6.5, 6.7 (or 1-5)
  i            paste a table of contents      b   add a book or notes
  t            link a chapter (or one section) to a topic; the topic shows "read 3/5"

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
        Binding("T", "pick_theme", "Theme", show=False),
        Binding("q", "quit", "Quit"),
        Binding("question_mark", "help", "Help", key_display="?"),
    ]

    def __init__(self, store: Store, cfg: Config) -> None:
        super().__init__()
        self.store = store
        self.cfg = cfg
        self._last_phase: PomoPhase | None = None
        self._toasted: set[tuple[int, datetime]] = set()  # deadlines already toasted this session

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
        self.set_interval(60, self.every_minute)

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

    # ----- deadline warnings -----

    def _label(self, d: Deadline, now: datetime, codes: dict[int, str]) -> str:
        code = codes.get(d.course_id) if d.course_id is not None else None
        return f"{d.title}{f' ({code})' if code else ''} {countdown(d.due_at, now)}"

    def banner(self) -> Text | None:
        """Anything overdue or due within 24 hours. Shown on every screen until it's dealt with."""
        now = datetime.now()
        overdue, soon = banner_groups(self.store.list_deadlines(), now)
        if not overdue and not soon:
            return None
        palette = themes.active()
        codes = {c.id: c.code for c in self.store.list_courses()}
        text = Text()
        for group, heading, style in ((overdue, f"{len(overdue)} overdue", palette.error),
                                      (soon, "Due within 24 hours", palette.warning)):
            if not group:
                continue
            if text:
                text.append("     ")
            text.append(f"▲ {heading}: ", style=f"bold {style}")
            names = [self._label(d, now, codes) for d in group[:3]]
            if len(group) > 3:
                names.append(f"and {len(group) - 3} more")
            text.append(" · ".join(names))
        return text

    def show_banner(self, screen) -> None:
        for widget in screen.query("#banner").results(Static):
            text = self.banner()
            widget.display = text is not None
            if text is not None:
                widget.update(text)

    def toast_new_deadlines(self, launching: bool = False) -> None:
        """A toast for deadlines that have come inside the warning window since the last one."""
        now = datetime.now()
        near = [d for d in within(self.store.list_deadlines(), now, self.cfg.toast_window)
                if (d.id, d.due_at) not in self._toasted]
        if not near:
            return
        self._toasted |= {(d.id, d.due_at) for d in near}
        codes = {c.id: c.code for c in self.store.list_courses()}
        lines = [self._label(d, now, codes) for d in near[:4]]
        if len(near) > 4:
            lines.append(f"and {len(near) - 4} more")
        urgent = any(d.due_at - now <= timedelta(hours=24) for d in near)
        self.notify("\n".join(lines), title="Coming up" if launching else "Deadline getting close",
                    severity="error" if urgent else "warning", timeout=12)

    def every_minute(self, launching: bool = False) -> None:
        self.toast_new_deadlines(launching)
        self.send_desktop_alerts()

    def send_desktop_alerts(self) -> None:
        """The same alerts `study notify` sends, so they arrive while the dashboard is open even without the
        scheduled job. Runs in a thread (showing a notification can take a moment) with its own connection."""
        path, cfg = self.store.path, self.cfg

        def work() -> None:
            with Store(path, exam_time=cfg.default_exam_time) as store:
                alerts.send_due(store, cfg)

        self.run_worker(work, thread=True, exclusive=True, group="desktop-alerts")

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
