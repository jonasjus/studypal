"""`study pomo watch`: a live countdown for the running Pomodoro.

Keys: space/n start the next focus block · p pause/resume · s stop and log · q (or Ctrl+C) leave
the view with the run still going. Leaving is safe: the run is saved, and finished blocks are
logged by whatever looks next.
"""

from __future__ import annotations

import sys
import time as clock
from contextlib import AbstractContextManager, nullcontext
from datetime import datetime
from pathlib import Path

from rich.console import Console, Group
from rich.live import Live
from rich.text import Text

from . import notifier
from .config import Config
from .logic.pomodoro import PomodoroRun, PomoPhase, phase_length, remaining
from .logic.stats import format_minutes
from .storage import Store, StorageError


class KeyReader(AbstractContextManager):
    """Single key presses without Enter (POSIX terminals)."""

    def __enter__(self) -> KeyReader:
        import termios
        import tty

        self.fd = sys.stdin.fileno()
        self.saved = termios.tcgetattr(self.fd)
        tty.setcbreak(self.fd)
        return self

    def __exit__(self, *exc: object) -> None:
        import termios

        termios.tcsetattr(self.fd, termios.TCSADRAIN, self.saved)

    def read(self, timeout: float) -> str | None:
        import select

        ready, _, _ = select.select([sys.stdin], [], [], timeout)
        return sys.stdin.read(1) if ready else None


def _keys() -> AbstractContextManager:
    if not sys.stdin.isatty():
        return nullcontext(None)
    try:
        import termios  # noqa: F401  (not on Windows)
    except ImportError:
        return nullcontext(None)
    return KeyReader()


def phase_message(run: PomodoroRun, cfg: Config) -> tuple[str, str] | None:
    """What to tell you when the run moves into `run.phase` on its own."""
    if run.phase.is_break:
        length = phase_length(run.phase, cfg.pomodoro)
        minutes = int(length.total_seconds() // 60) if length else 0
        kind = "long" if run.phase is PomoPhase.LONG_BREAK else "short"
        return f"Focus block {run.completed} done", f"Logged. Take a {minutes}-minute {kind} break."
    if run.phase is PomoPhase.READY:
        return "Break's over", "Start the next focus block when you're ready."
    return None


def view(run: PomodoroRun, store: Store, cfg: Config, now: datetime, logged_minutes: int, keys: bool) -> Group:
    course = store.get_course(run.course_id)
    topic = store.get_topic(run.topic_id) if run.topic_id else None
    color = course.color if course else ""

    head = Text("  ")
    head.append(run.phase.label, style="bold")
    if run.phase is PomoPhase.FOCUS:
        head.append(f" · block {run.completed + 1}", style="dim")
    if run.paused:
        head.append("  paused", style="yellow")
    head.append("    ")
    head.append(course.code if course else "", style=f"bold {color}")
    if topic:
        head.append(f" · {topic.title}", style="dim")

    left = remaining(run, now, cfg.pomodoro)
    length = phase_length(run.phase, cfg.pomodoro)
    clock_line = Text("  ")
    bar = Text("  ")
    if left is not None and length:
        mins, secs = divmod(int(left.total_seconds()), 60)
        clock_line.append(f"{mins:02d}:{secs:02d}", style="bold")
        width = 36
        filled = round((1 - left / length) * width)
        bar.append("━" * filled, style=color if run.phase is PomoPhase.FOCUS else "green")
        bar.append("─" * (width - filled), style="dim")
    else:
        clock_line.append("Ready for the next focus block", style="bold")

    tally = Text(f"  {run.completed} block{'s' if run.completed != 1 else ''} finished this run"
                 f" · {format_minutes(logged_minutes)} logged", style="dim")
    lines = [Text(), head, Text(), clock_line, bar, Text(), tally]
    if keys:
        start_word = "skip break" if run.phase.is_break else "next focus"
        lines.append(Text(f"  space {start_word} · p {'resume' if run.paused else 'pause'} · s stop and log · q leave running",
                          style="dim"))
    return Group(*lines)


def watch(db_path: Path, cfg: Config) -> None:
    console = Console(highlight=False)
    store = Store(db_path, exam_time=cfg.default_exam_time)
    try:
        run, _ = store.settle_pomodoro(settings=cfg.pomodoro)
        if run is None:
            raise StorageError("No Pomodoro running. Start one with `study pomo start COURSE`.")
        logged_minutes = 0
        farewell = "Left the view; the Pomodoro keeps running. Back to it with `study pomo watch`."
        with _keys() as keys, Live(console=console, refresh_per_second=4, transient=True) as live:
            while True:
                now = datetime.now()
                before = run
                run, logged = store.settle_pomodoro(now, cfg.pomodoro)
                if run is None:
                    farewell = "The Pomodoro was stopped somewhere else."
                    break
                logged_minutes += sum(s.minutes for s in logged)
                if run.phase is not before.phase and (msg := phase_message(run, cfg)):
                    notifier.send(*msg)
                    console.bell()
                live.update(view(run, store, cfg, now, logged_minutes, keys is not None))

                key = keys.read(0.25) if keys else (clock.sleep(0.25) or None)
                if key in (" ", "n") and run.phase is not PomoPhase.FOCUS:
                    run, _ = store.pomodoro_next(settings=cfg.pomodoro)
                elif key == "p":
                    action = store.resume_pomodoro if run.paused else store.pause_pomodoro
                    run, _ = action(settings=cfg.pomodoro)
                elif key == "s":
                    stopped = store.stop_pomodoro(settings=cfg.pomodoro)
                    total = logged_minutes + sum(s.minutes for s in stopped)
                    farewell = f"Pomodoro stopped. {format_minutes(total)} logged in this view."
                    break
                elif key == "q":
                    break
    except KeyboardInterrupt:
        farewell = "Left the view; the Pomodoro keeps running. Back to it with `study pomo watch`."
    finally:
        store.close()
    console.print(farewell)
