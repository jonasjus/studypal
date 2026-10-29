"""Rows and small widgets for the TUI. Renderables size themselves to the space they get."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from rich.console import Console, ConsoleOptions, RenderResult
from rich.table import Table
from rich.text import Text
from textual.binding import Binding
from textual.widgets import ListItem, ListView, Static

from ..dashboard import CourseSummary
from ..logic.countdown import Urgency, countdown, urgency
from ..logic.stats import days_since, format_minutes
from ..logic.reading import ReadingProgress
from ..logic.timeline import CramProgress, Phase
from ..models import Course, Deadline, Priority, Session, Topic, TopicStatus, WeakSpot
from .. import themes
from ..render import MUTED, accent, exam_words, progress_words, timeline, urgency_style, warning

STATUS_GLYPH = {
    TopicStatus.NOT_STARTED: "○",
    TopicStatus.IN_PROGRESS: "◐",
    TopicStatus.REVIEWED: "●",
    TopicStatus.CONFIDENT: "◆",
}


def priority_style(priority: Priority) -> str:
    p = themes.active()
    return {Priority.HIGH: p.error, Priority.MED: p.warning, Priority.LOW: MUTED}[priority]


def status_style(status: TopicStatus) -> str:
    p = themes.active()
    return {
        TopicStatus.NOT_STARTED: MUTED,
        TopicStatus.IN_PROGRESS: p.warning,
        TopicStatus.REVIEWED: p.info,
        TopicStatus.CONFIDENT: p.success,
    }[status]


class VimList(ListView):
    """A ListView that also moves with j/k."""

    BINDINGS = [
        Binding("j", "cursor_down", "Down", show=False),
        Binding("k", "cursor_up", "Up", show=False),
    ]

    @property
    def current(self) -> Any:
        item = self.highlighted_child
        return getattr(item, "data", None)


class Row(ListItem):
    """A list row that remembers what it shows."""

    def __init__(self, renderable: Any, data: Any = None) -> None:
        super().__init__(Static(renderable))
        self.data = data


def empty_row(message: str) -> Row:
    return Row(Text(message, style=MUTED), None)


# ---------- courses ----------

class CourseRow:
    def __init__(self, summary: CourseSummary, number: int | None) -> None:
        self.s = summary
        self.number = number

    def __rich_console__(self, console: Console, options: ConsoleOptions) -> RenderResult:
        width = options.max_width
        s, c = self.s, self.s.course
        head = Table.grid(expand=True)
        head.add_column(no_wrap=True, overflow="ellipsis")
        head.add_column(justify="right", style=MUTED, no_wrap=True)
        name = Text()
        name.append(f"{self.number} " if self.number else "  ", style=MUTED)
        name.append("● ", style=accent(c))
        name.append(c.code, style=f"bold {accent(c)}")
        name.append(f"  {c.name}")
        head.add_row(name, exam_words(c, s.progress) if width >= 60 else f"{s.progress.days_left}d")
        yield head

        words = progress_words(s.progress)
        side = width - 4 - words.cell_len - 2
        if side >= 16:
            line = Text("  ")
            line.append_text(timeline(s.progress, accent(c), side))
            line.append("  ")
            line.append_text(words)
            yield line
        else:
            yield Text("  ").append_text(timeline(s.progress, accent(c), max(8, width - 4)))
            yield Text("  ").append_text(words)

        facts = [f"{len(s.topics)} topic{'s' if len(s.topics) != 1 else ''}"]
        if s.stale_topics:
            facts.append(f"{s.stale_topics} stale")
        if s.open_weak:
            facts.append(f"{s.open_weak} weak spot{'s' if s.open_weak != 1 else ''}")
        if s.reading.required:
            facts.append(f"reading {s.reading.read}/{s.reading.required}")
        facts.append(f"{format_minutes(s.week_minutes)} this week")
        yield Text("  " + " · ".join(facts), style=MUTED, overflow="ellipsis", no_wrap=True)


def done_row(s: CourseSummary) -> Text:
    """A finished subject: one quiet line."""
    c = s.course
    text = Text()
    text.append("✓ ", style=themes.active().success)
    text.append(c.code, style=f"bold {accent(c)}")
    text.append(f"  {c.name}")
    text.append(f"   exam {c.exam_date:%d.%m.%Y} · {format_minutes(s.total_minutes)} studied · "
                f"{round(s.progress.done * 100)}% done", style=MUTED)
    return text


class BigTimeline:
    """The subject screen's timeline: a thicker bar with dates underneath and today marked."""

    def __init__(self, course: Course, progress: CramProgress, today: date) -> None:
        self.course, self.p, self.today = course, progress, today

    def __rich_console__(self, console: Console, options: ConsoleOptions) -> RenderResult:
        width = max(20, options.max_width)
        bar = timeline(self.p, accent(self.course), width)
        yield bar
        yield bar
        start = f"{self.course.cram_start:%a} {self.course.cram_start.day} {self.course.cram_start:%b}"
        end = f"exam {self.course.exam_date:%a} {self.course.exam_date.day} {self.course.exam_date:%b}"
        labels = [" "] * width
        for i, ch in enumerate(start):
            labels[i] = ch
        for i, ch in enumerate(end):
            labels[width - len(end) + i] = ch
        if self.p.phase in (Phase.CRAMMING, Phase.EXAM_DAY):
            marker = min(width - 1, max(0, round(self.p.elapsed * (width - 1))))
            word = "▲ today"
            pos = min(max(marker, len(start) + 1), width - len(end) - len(word) - 1)
            if pos > len(start) and pos + len(word) < width - len(end):
                for i, ch in enumerate(word):
                    labels[pos + i] = ch
        yield Text("".join(labels), style=MUTED)
        yield Text()
        yield progress_words(self.p)


# ---------- deadlines, weak spots, topics, sessions ----------

class DeadlineRow:
    """Countdown, title, due date and course; the date is left out when the pane is narrow."""

    def __init__(self, d: Deadline, now: datetime, course: Course | None, show_course: bool = True) -> None:
        self.args = (d, now, course, show_course)

    def __rich_console__(self, console: Console, options: ConsoleOptions) -> RenderResult:
        yield deadline_row(*self.args, show_date=options.max_width >= 64)


def deadline_row(d: Deadline, now: datetime, course: Course | None, show_course: bool = True,
                 show_date: bool = True) -> Table:
    u = urgency(d.due_at, now, d.done)
    grid = Table.grid(expand=True, padding=(0, 1))
    grid.add_column(width=9 if not show_date else 12, no_wrap=True)
    grid.add_column(ratio=1, no_wrap=True, overflow="ellipsis")
    if show_course:
        grid.add_column(no_wrap=True, justify="right")
    when = Text("OVERDUE", style=urgency_style(u)) if u is Urgency.OVERDUE else Text(
        countdown(d.due_at, now).removeprefix("in "), style=urgency_style(u))
    title = Text(d.title, style="dim strike" if d.done else "")
    if show_date:
        title.append(f"  {d.due_at:%a} {d.due_at.day} {d.due_at:%b %H:%M}", style=MUTED)
    cells = [when, title]
    if show_course:
        cells.append(Text(course.code, style=accent(course)) if course else Text("—", style=MUTED))
    grid.add_row(*cells)
    return grid


def weak_row(w: WeakSpot, now: datetime, course: Course | None, topic: Topic | None = None) -> Text:
    text = Text()
    text.append("▲ " if w.priority is Priority.HIGH else "● ", style=priority_style(w.priority))
    text.append(w.description, style="dim strike" if w.resolved else "")
    extra = []
    if course:
        extra.append(course.code)
    if topic:
        extra.append(topic.title)
    age = days_since(w.created_at.date(), now.date())
    extra.append("today" if age == 0 else f"{age}d")
    text.append("  " + " · ".join(extra), style=MUTED)
    return text


def topic_row(t: Topic, today: date, stale_after: int, reading: ReadingProgress | None = None) -> Table:
    glyph, style = STATUS_GLYPH[t.status], status_style(t.status)
    grid = Table.grid(expand=True, padding=(0, 1))
    grid.add_column(width=2, no_wrap=True)
    grid.add_column(ratio=1, no_wrap=True, overflow="ellipsis")
    grid.add_column(width=12, no_wrap=True)
    grid.add_column(width=6, no_wrap=True)
    grid.add_column(width=10, no_wrap=True, justify="right")
    grid.add_column(width=16, no_wrap=True, justify="right")
    since = days_since(t.last_studied, today)
    if since is None:
        studied = Text("never", style=MUTED)
    else:
        label = "today" if since == 0 else "yesterday" if since == 1 else f"{since}d ago"
        studied = Text(f"{label} · stale", style=warning()) if since >= stale_after else Text(label, style=MUTED)
    grid.add_row(
        Text(glyph, style=style),
        Text(t.title),
        Text(t.status.label, style=style),
        Text("●" * t.confidence + "○" * (5 - t.confidence), style=themes.active().info),
        reading_cell(reading),
        studied,
    )
    return grid


def reading_cell(reading: ReadingProgress | None) -> Text:
    """'read 3/5' for a topic with reading linked to it; green once it's all read."""
    if reading is None or not reading.required:
        return Text("")
    return Text(f"read {reading.read}/{reading.required}",
                style=themes.active().success if reading.complete else MUTED)


def session_row(s: Session, topic: Topic | None) -> Text:
    text = Text(f"{s.started_at:%a} {s.started_at.day:>2} {s.started_at:%b %H:%M}  ", style=MUTED,
                no_wrap=True, overflow="ellipsis")
    text.append(f"{format_minutes(s.minutes):>7}", style="bold")
    bits = [b for b in (topic.title if topic else "", s.note) if b]
    if bits:
        text.append("  " + " · ".join(bits))
    return text


class WeekChart:
    """One line per day: a bar scaled to the busiest day, and the time."""

    def __init__(self, days: list[date], minutes: list[int], today: date) -> None:
        self.days, self.minutes, self.today = days, minutes, today

    def __rich_console__(self, console: Console, options: ConsoleOptions) -> RenderResult:
        bar_room = max(4, options.max_width - 14)
        peak = max(self.minutes) or 1
        for day, mins in zip(self.days, self.minutes):
            style = "bold" if day == self.today else MUTED if day > self.today else ""
            line = Text(f"{day:%a} ", style=style)
            length = round(mins / peak * bar_room) if mins else 0
            line.append("█" * max(length, 1 if mins else 0), style=themes.active().info if day <= self.today else MUTED)
            line.append(f" {format_minutes(mins)}" if mins else (" ·" if day <= self.today else ""), style=style or MUTED)
            yield line
        yield Text(f"{format_minutes(sum(self.minutes))} this week", style="bold")
