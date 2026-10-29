"""The `study` command. With no subcommand it opens the TUI."""

from __future__ import annotations

import re
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime, time, timedelta
from pathlib import Path
from typing import Annotated, NoReturn, Optional

import typer
from rich.console import Console
from rich.text import Text

from . import config as config_mod
from . import paths
from .config import Config, ConfigError
from .logic.dates import DateParseError, parse_date, parse_datetime, parse_minutes
from .models import COURSE_COLORS, Course, Deadline, DeadlineKind, Priority, Session, Topic, TopicStatus, WeakSpot
from .storage import Store, StorageError

console = Console(highlight=False)
err = Console(stderr=True, highlight=False)

app = typer.Typer(
    add_completion=False,
    rich_markup_mode="rich",
    context_settings={"help_option_names": ["-h", "--help"]},
    help="A calm terminal study tracker. Run [bold]study[/] on its own to open the dashboard.",
)
add_app = typer.Typer(help="Add a course, topic, weak spot or deadline.", no_args_is_help=True)
pomo_app = typer.Typer(help="Pomodoro timer. Each finished focus block is logged as a study session.")
app.add_typer(add_app, name="add")
app.add_typer(pomo_app, name="pomo")

ASSIGNMENT_TIME = time(23, 59)  # deadlines given without a time are due at the end of the day


# ---------- shared helpers ----------

def fail(message: str) -> NoReturn:
    err.print(f"[red]{message}[/]")
    raise typer.Exit(1)


def load_config() -> Config:
    try:
        return config_mod.load()
    except ConfigError as e:
        fail(f"Problem in {paths.config_path()}: {e}")


@contextmanager
def opened() -> Iterator[tuple[Store, Config]]:
    """Open the database, settle any Pomodoro that has moved on, and turn expected errors into messages."""
    cfg = load_config()
    store = Store(paths.db_path(), exam_time=cfg.default_exam_time)
    try:
        _, logged = store.settle_pomodoro(settings=cfg.pomodoro)
        for s in logged:
            console.print(f"[dim]Logged {s.note}: {s.minutes} min.[/]")
        yield store, cfg
    except (StorageError, DateParseError) as e:
        fail(str(e))
    finally:
        store.close()


def choice(enum_type, value: str, what: str):
    try:
        return enum_type(value.strip().lower().replace(" ", "_"))
    except ValueError:
        options = ", ".join(e.value for e in enum_type)
        raise StorageError(f"{value!r} isn't a {what}. Choose one of: {options}.") from None


def resolve_topic(store: Store, course: Course, ref: str | None) -> Topic | None:
    return store.find_topic(course.id, ref) if ref else None


# ---------- top level ----------

@app.callback(invoke_without_command=True)
def main_callback(
    ctx: typer.Context,
    demo: Annotated[bool, typer.Option("--demo", help="Use a temporary database filled with sample courses.")] = False,
) -> None:
    if demo:
        from . import demo as demo_mod

        path = demo_mod.temporary_store_path()
        cfg = load_config()
        with Store(path, exam_time=cfg.default_exam_time) as store:
            demo_mod.seed(store)
        err.print("[dim]Demo mode: sample data in a temporary database. Nothing you change is kept.[/]")
    if ctx.invoked_subcommand is None:
        from .tui import run_tui

        run_tui()


@app.command()
def status() -> None:
    """Where you stand: every course with its cram timeline, plus this week's study time."""
    from . import dashboard
    from .render import active_timer_line, course_block, week_chart

    with opened() as (store, cfg):
        dash = dashboard.build(store, cfg)
    console.print()
    if not dash.courses:
        console.print("No courses yet. Add one with [bold]study add course \"Machine Learning\" INF301 --exam 2026-12-10[/].")
        return
    for summary in dash.courses:
        console.print(course_block(summary, width=32))
        console.print()
    console.print(week_chart(dash))
    if line := active_timer_line(dash, cfg.pomodoro):
        console.print(line)
    urgent = [d for d in dash.deadlines if d.due_at - dash.now < timedelta(days=2)]
    if urgent:
        console.print(Text(f"{len(urgent)} deadline{'s' if len(urgent) != 1 else ''} within 48 hours or overdue. "
                           "Run study due.", style="yellow"))
    console.print()


@app.command()
def due(
    all_: Annotated[bool, typer.Option("--all", "-a", help="Include deadlines already done.")] = False,
    within: Annotated[Optional[int], typer.Option("--within", "-w", help="Only the next N days (overdue always shown).")] = None,
) -> None:
    """List upcoming deadlines, soonest first."""
    from . import dashboard
    from .render import deadlines_table

    with opened() as (store, cfg):
        dash = dashboard.build(store, cfg)
        deadlines = store.list_deadlines(include_done=all_)
    if within is not None:
        deadlines = [d for d in deadlines if d.due_at - dash.now < timedelta(days=within)]
    if not deadlines:
        console.print("Nothing due." if within is None else f"Nothing due in the next {within} days.")
        return
    console.print()
    console.print(deadlines_table(deadlines, dash))
    console.print()


@app.command("log")
def log_session(
    course: Annotated[str, typer.Argument(help="Course code or name.")],
    minutes: Annotated[str, typer.Argument(help="How long, e.g. 45, 90m or 1h30m.")],
    topic: Annotated[Optional[str], typer.Option("--topic", "-t", help="Topic studied.")] = None,
    note: Annotated[str, typer.Option("--note", "-n", help="A short note.")] = "",
    at: Annotated[Optional[str], typer.Option("--at", help="When you started, e.g. 'today 09:00'. Default: just now.")] = None,
) -> None:
    """Log a study session you've just finished."""
    with opened() as (store, _):
        c = store.find_course(course)
        t = resolve_topic(store, c, topic)
        mins = parse_minutes(minutes)
        now = datetime.now().replace(second=0, microsecond=0)
        start = parse_datetime(at, now, now.time()) if at else now - timedelta(minutes=mins)
        store.log_session(Session(c.id, start, mins, t.id if t else None, note))
        total = store.total_minutes(c.id)
    from .logic.stats import format_minutes

    where = f"{c.code} · {t.title}" if t else c.code
    console.print(f"Logged {format_minutes(mins)} on {where}. {format_minutes(total)} on {c.code} in total.")


@app.command()
def weak(
    course: Annotated[str, typer.Argument(help="Course code or name.")],
    description: Annotated[str, typer.Argument(help="What you're weak on, in a few words.")],
    priority: Annotated[str, typer.Option("--priority", "-p", help="low, med or high.")] = "med",
    topic: Annotated[Optional[str], typer.Option("--topic", "-t", help="Topic it belongs to.")] = None,
) -> None:
    """Note a weak spot to come back to."""
    add_weak(course, description, priority, topic)


# ---------- study add ... ----------

@add_app.command("course")
def add_course(
    name: Annotated[str, typer.Argument(help="Full name, e.g. 'Machine Learning'.")],
    code: Annotated[str, typer.Argument(help="Short code, e.g. INF301.")],
    exam: Annotated[str, typer.Option("--exam", "-e", help="Exam date, e.g. 2026-12-10 or 12-10.")],
    cram_start: Annotated[str, typer.Option("--cram-start", "-s", help="When cramming starts. Default: today.")] = "today",
    color: Annotated[Optional[str], typer.Option("--color", help="Accent colour as #rrggbb. Default: the next unused one.")] = None,
    notes: Annotated[str, typer.Option("--notes", help="Anything to remember about the course.")] = "",
) -> None:
    """Add a course. Its exam is added as a deadline automatically."""
    with opened() as (store, _):
        today = datetime.now().date()
        if color and not re.fullmatch(r"#[0-9a-fA-F]{6}", color):
            raise StorageError(f"{color!r} isn't a colour. Use #rrggbb, e.g. {COURSE_COLORS[2]}.")
        c = store.add_course(Course(name, code, parse_date(cram_start, today), parse_date(exam, today),
                                    color or store.next_color(), notes))
    console.print(Text.assemble("Added ", (c.code, f"bold {c.color}"), f" ({c.name}), exam on {c.exam_date:%a %d %b %Y}."))


@add_app.command("topic")
def add_topic(
    course: Annotated[str, typer.Argument(help="Course code or name.")],
    title: Annotated[str, typer.Argument(help="Topic title.")],
    status: Annotated[str, typer.Option("--status", help="not_started, in_progress, reviewed or confident.")] = "not_started",
    confidence: Annotated[int, typer.Option("--confidence", "-c", min=1, max=5, help="1 to 5.")] = 1,
) -> None:
    """Add a topic to a course."""
    with opened() as (store, _):
        c = store.find_course(course)
        t = store.add_topic(Topic(c.id, title, choice(TopicStatus, status, "status"), confidence))
    console.print(f"Added topic {t.title!r} to {c.code}.")


@add_app.command("weak")
def add_weak(
    course: Annotated[str, typer.Argument(help="Course code or name.")],
    description: Annotated[str, typer.Argument(help="What you're weak on.")],
    priority: Annotated[str, typer.Option("--priority", "-p", help="low, med or high.")] = "med",
    topic: Annotated[Optional[str], typer.Option("--topic", "-t", help="Topic it belongs to.")] = None,
) -> None:
    """Add a weak spot (same as `study weak`)."""
    with opened() as (store, _):
        c = store.find_course(course)
        t = resolve_topic(store, c, topic)
        p = choice(Priority, {"medium": "med"}.get(priority.lower(), priority), "priority")
        store.add_weak_spot(WeakSpot(c.id, description, p, t.id if t else None))
        open_count = len(store.list_weak_spots(c.id))
    console.print(f"Noted a {p.value}-priority weak spot for {c.code}. {open_count} open.")


@add_app.command("deadline")
def add_deadline(
    title: Annotated[str, typer.Argument(help="What's due.")],
    due_at: Annotated[str, typer.Argument(metavar="DUE", help="When, e.g. 'fri 14:00', 2026-12-01, +3d. Default time 23:59.")],
    course: Annotated[Optional[str], typer.Option("--course", "-c", help="Course it belongs to (leave out for standalone).")] = None,
    kind: Annotated[str, typer.Option("--type", help="exam, assignment or milestone.")] = "assignment",
) -> None:
    """Add a deadline."""
    from .logic.countdown import countdown

    with opened() as (store, cfg):
        k = choice(DeadlineKind, kind, "deadline type")
        c = store.find_course(course) if course else None
        now = datetime.now()
        due = parse_datetime(due_at, now, cfg.default_exam_time if k is DeadlineKind.EXAM else ASSIGNMENT_TIME)
        d = store.add_deadline(Deadline(title, due, k, c.id if c else None))
    console.print(f"Added {d.kind.value} {d.title!r}, due {d.due_at:%a %d %b %H:%M} ({countdown(d.due_at, now)}).")


@app.command()
def theme(
    name: Annotated[Optional[str], typer.Argument(help="Theme to use, e.g. gruvbox. Leave out to list them.")] = None,
) -> None:
    """List the dashboard's colour themes, or pick one (also: T inside the dashboard)."""
    from . import themes

    with opened() as (store, _):
        current = store.get_setting("theme", themes.DEFAULT.name)
        if name is None:
            for p in themes.THEMES:
                line = Text("● " if p.name == current else "  ", style="bold")
                line.append(f"{p.name:<18}", style="bold" if p.name == current else "")
                line.append(f"{p.label:<36}", style="dim")
                for color in p.accents:
                    line.append("■ ", style=color)
                console.print(line)
            return
        key = name.strip().lower()
        if key not in themes.BY_NAME:
            raise StorageError(f"There's no theme called {name!r}. Run study theme to see them all.")
        store.set_setting("theme", key)
    console.print(f"The dashboard will use {themes.BY_NAME[key].label}.")


# ---------- notify / export ----------

@app.command()
def notify(
    dry_run: Annotated[bool, typer.Option("--dry-run", help="Show what would be sent without sending or recording it.")] = False,
) -> None:
    """Send any deadline notifications that are due. Made to run from cron, launchd or a systemd timer."""
    from . import notifier
    from .logic.notify import pending_alerts

    with opened() as (store, cfg):
        now = datetime.now()
        codes = {c.id: c.code for c in store.list_courses()}
        alerts = pending_alerts(store.list_deadlines(), now, cfg.thresholds, cfg.morning_time, store.sent_keys(), codes)
        failed = 0
        for a in alerts:
            if dry_run:
                console.print(f"Would send: {a.title} ({a.body})")
                continue
            if notifier.send(a.title, a.body):
                store.mark_sent(a.deadline.id, list(a.covers), a.deadline.due_at, now)
                console.print(f"Sent: {a.title}")
            else:
                failed += 1
    if failed:
        fail(f"{failed} notification{'s' if failed != 1 else ''} couldn't be shown. They'll be retried next run.")


@app.command()
def export(
    fmt: Annotated[str, typer.Option("--format", "-f", help="md or csv.")] = "md",
    output: Annotated[Optional[Path], typer.Option("--output", "-o",
                      help="File for md (default: print it), folder for csv (default: study-export-DATE).")] = None,
) -> None:
    """Export everything for backup or review."""
    from . import export as export_mod

    fmt = fmt.lower()
    if fmt not in ("md", "csv"):
        fail(f"{fmt!r} isn't a format study can export. Use md or csv.")
    with opened() as (store, _):
        if fmt == "md":
            text = export_mod.to_markdown(store)
            if output is None:
                console.out(text, end="")
                return
            output.write_text(text, encoding="utf-8")
            console.print(f"Wrote {output}.")
        else:
            folder = output or Path(f"study-export-{datetime.now():%Y-%m-%d}")
            files = export_mod.to_csv(store, folder)
            console.print(f"Wrote {len(files)} CSV files to {folder}/.")


# ---------- study pomo ... ----------

@pomo_app.callback(invoke_without_command=True)
def pomo_status(ctx: typer.Context) -> None:
    """Show the running Pomodoro."""
    if ctx.invoked_subcommand is not None:
        return
    from . import dashboard
    from .render import pomodoro_line

    with opened() as (store, cfg):
        dash = dashboard.build(store, cfg)
    if dash.pomodoro is None:
        console.print("No Pomodoro running. Start one with [bold]study pomo start COURSE[/].")
    else:
        console.print(pomodoro_line(dash.pomodoro, dash, cfg.pomodoro))


@pomo_app.command("start")
def pomo_start(
    course: Annotated[str, typer.Argument(help="Course code or name.")],
    topic: Annotated[Optional[str], typer.Option("--topic", "-t", help="Topic you're working on.")] = None,
    note: Annotated[str, typer.Option("--note", "-n", help="Added to every logged block.")] = "",
    background: Annotated[bool, typer.Option("--background", "-b", help="Start it and return; watch later with `study pomo watch`.")] = False,
) -> None:
    """Start a Pomodoro run and watch the countdown."""
    with opened() as (store, cfg):
        c = store.find_course(course)
        t = resolve_topic(store, c, topic)
        store.start_pomodoro(c.id, t.id if t else None, note=note)
    minutes = int(cfg.pomodoro.focus.total_seconds() // 60)
    console.print(f"Pomodoro started on {c.code}{' · ' + t.title if t else ''}: {minutes} minute{'s' if minutes != 1 else ''} of focus.")
    if not background:
        pomo_watch()


@pomo_app.command("watch")
def pomo_watch() -> None:
    """Show a live countdown with a notification at each phase change. Leaving the view keeps the run going."""
    from .pomo_watch import watch

    cfg = load_config()
    try:
        watch(paths.db_path(), cfg)
    except StorageError as e:
        fail(str(e))


def _pomo_action(action: str) -> None:
    from .render import pomodoro_line
    from . import dashboard

    with opened() as (store, cfg):
        run, logged = getattr(store, action)(settings=cfg.pomodoro)
        for s in logged:
            console.print(f"[dim]Logged {s.note}: {s.minutes} min.[/]")
        console.print(pomodoro_line(run, dashboard.build(store, cfg), cfg.pomodoro))


@pomo_app.command("next")
def pomo_next() -> None:
    """Start the next focus block (or skip the rest of a break)."""
    _pomo_action("pomodoro_next")


@pomo_app.command("pause")
def pomo_pause() -> None:
    """Pause the countdown. Paused time is never logged."""
    _pomo_action("pause_pomodoro")


@pomo_app.command("resume")
def pomo_resume() -> None:
    """Carry on after a pause."""
    _pomo_action("resume_pomodoro")


@pomo_app.command("stop")
def pomo_stop() -> None:
    """End the run. Logs finished blocks, plus the focus time of a block in progress."""
    from .logic.stats import format_minutes

    with opened() as (store, cfg):
        logged = store.stop_pomodoro(settings=cfg.pomodoro)
    if logged:
        for s in logged:
            console.print(f"Logged {s.note}: {s.minutes} min.")
        console.print(f"Pomodoro stopped. {format_minutes(sum(s.minutes for s in logged))} logged just now.")
    else:
        console.print("Pomodoro stopped. Nothing new to log.")


def main() -> None:
    app()
