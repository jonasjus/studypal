"""Rich renderables shared by the CLI (and reused inside the TUI).

Colours come from the terminal's own palette (red, yellow, dim) plus one accent per course,
and nothing sets a background, so output reads on light and dark themes alike.
"""

from __future__ import annotations

from datetime import datetime

from rich.console import Group, RenderableType
from rich.table import Table
from rich.text import Text

from .dashboard import CourseSummary, Dashboard
from .logic.countdown import Urgency, countdown, describe_days, urgency
from .logic.pomodoro import PomodoroRun, PomodoroSettings, PomoPhase, remaining
from .logic.stats import format_minutes
from .logic.timeline import Cell, CramProgress, Phase, timeline_cells
from .models import Course, Deadline

URGENCY_STYLE = {
    Urgency.OVERDUE: "bold red",
    Urgency.CRITICAL: "red",
    Urgency.SOON: "yellow",
    Urgency.LATER: "",
    Urgency.DONE: "dim",
}
BEHIND_STYLE = "yellow"
MUTED = "dim"

BAR_CHARS = {Cell.DONE: "━", Cell.BEHIND: "╍", Cell.TODO: "─"}  # behind is dashed so it shows without colour too
MARKER = "┃"
SPARKS = " ▁▂▃▄▅▆▇█"


def timeline(progress: CramProgress, color: str, width: int = 30) -> Text:
    """The cram timeline as one line: done in the course colour, the behind gap in yellow, the rest dim,
    and a bold marker for today."""
    cells, marker = timeline_cells(progress, width)
    text = Text()
    for i, cell in enumerate(cells):
        if i == marker and progress.phase in (Phase.CRAMMING, Phase.EXAM_DAY):
            text.append(MARKER, style="bold")
        elif cell is Cell.DONE:
            text.append(BAR_CHARS[cell], style=color)
        elif cell is Cell.BEHIND:
            text.append(BAR_CHARS[cell], style=BEHIND_STYLE)
        else:
            text.append(BAR_CHARS[cell], style=MUTED)
    return text


def progress_words(p: CramProgress) -> Text:
    done = f"{round(p.done * 100)}% done"
    if p.topic_count == 0:
        return Text("no topics yet", style=MUTED)
    if p.phase is Phase.BEFORE:
        return Text(f"{done} · cramming starts {describe_days(p.days_left - p.days_total)}", style=MUTED)
    if p.phase is Phase.AFTER:
        return Text(f"{done} · exam was {describe_days(p.days_left)}", style=MUTED)
    text = Text(f"{done} · {round(p.elapsed * 100)}% of cram time used")
    if p.is_behind:
        text.append(f" · behind by {round(p.behind * 100)}%", style=BEHIND_STYLE)
    return text


def exam_words(course: Course, p: CramProgress) -> str:
    if p.days_left < 0:
        return f"exam was {describe_days(p.days_left)}"
    when = "today" if p.days_left == 0 else describe_days(p.days_left)
    return f"exam {when} · {course.exam_date:%a} {course.exam_date.day} {course.exam_date:%b}"


def course_block(s: CourseSummary, width: int = 30) -> RenderableType:
    c = s.course
    head = Text()
    head.append("● ", style=c.color)
    head.append(c.code, style=f"bold {c.color}")
    head.append(f"  {c.name}")
    head.append(f"   {exam_words(c, s.progress)}", style=MUTED)

    line = Text("  ")
    line.append_text(timeline(s.progress, c.color, width))
    line.append("  ")
    line.append_text(progress_words(s.progress))

    facts = [f"{len(s.topics)} topic{'s' if len(s.topics) != 1 else ''}"]
    if s.stale_topics:
        facts.append(f"{s.stale_topics} stale")
    if s.open_weak:
        facts.append(f"{s.open_weak} weak spot{'s' if s.open_weak != 1 else ''}")
    facts.append(f"{format_minutes(s.week_minutes)} this week")
    return Group(head, line, Text("  " + " · ".join(facts), style=MUTED))


def when_text(d: Deadline, now: datetime) -> Text:
    u = urgency(d.due_at, now, d.done)
    if u is Urgency.DONE:
        return Text("done", style=URGENCY_STYLE[u])
    if u is Urgency.OVERDUE:
        return Text(f"OVERDUE {countdown(d.due_at, now).removeprefix('overdue by ')}", style=URGENCY_STYLE[u])
    return Text(countdown(d.due_at, now), style=URGENCY_STYLE[u])


def deadlines_table(deadlines: list[Deadline], dash: Dashboard) -> Table:
    table = Table(box=None, pad_edge=False, show_edge=False, header_style="dim", padding=(0, 2, 0, 0))
    table.add_column("When", no_wrap=True)
    table.add_column("Due", no_wrap=True, style=MUTED)
    table.add_column("Deadline")
    table.add_column("Course", no_wrap=True)
    table.add_column("Type", style=MUTED, no_wrap=True)
    for d in deadlines:
        course = dash.course(d.course_id)
        table.add_row(
            when_text(d, dash.now),
            f"{d.due_at:%a} {d.due_at.day:>2} {d.due_at:%b %H:%M}",
            Text(d.title, style="dim strike" if d.done else ""),
            Text(course.code, style=course.color) if course else Text("—", style=MUTED),
            d.kind.value,
        )
    return table


def week_chart(dash: Dashboard) -> Text:
    """'Mon ▃  Tue █  ...' scaled to the busiest day, with the week's total."""
    peak = max(dash.week_minutes) or 1
    text = Text()
    for day, minutes in zip(dash.week_days, dash.week_minutes):
        level = 0 if minutes == 0 else max(1, round(minutes / peak * (len(SPARKS) - 1)))
        style = "bold" if day == dash.today else MUTED if day > dash.today else ""
        text.append(f"{day:%a} ", style=style if day == dash.today else MUTED)
        text.append(SPARKS[level] if minutes else "·", style=style)
        text.append("  ")
    text.append(f"{format_minutes(sum(dash.week_minutes))} this week", style="bold")
    return text


def active_timer_line(dash: Dashboard, settings: PomodoroSettings) -> Text | None:
    if dash.pomodoro:
        return pomodoro_line(dash.pomodoro, dash, settings)
    if dash.timer:
        course = dash.course(dash.timer.course_id)
        running = dash.now - dash.timer.started_at
        text = Text("Timer running ", style="bold")
        text.append(f"{format_minutes(int(running.total_seconds() // 60))} · {course.code if course else ''}")
        return text
    return None


def pomodoro_line(run: PomodoroRun, dash: Dashboard, settings: PomodoroSettings) -> Text:
    course = dash.course(run.course_id)
    left = remaining(run, dash.now, settings)
    text = Text(f"Pomodoro · {run.phase.label}", style="bold")
    if run.paused:
        text.append(" (paused)", style="yellow")
    if left is not None:
        mins, secs = divmod(int(left.total_seconds()), 60)
        text.append(f" · {mins:02d}:{secs:02d} left")
    elif run.phase is PomoPhase.READY:
        text.append(" · run `study pomo next` to start the next focus block", style=MUTED)
    text.append(f" · {course.code if course else ''} · {run.completed} done", style=MUTED)
    return text
