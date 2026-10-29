"""One subject in full: its timeline, topics, weak spots, deadlines and recent sessions."""

from __future__ import annotations

import asyncio

from datetime import datetime

from rich.table import Table
from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.screen import Screen
from textual.widgets import Footer, Input, Static

from ..logic.stats import format_minutes, minutes_between, week_range
from ..logic.timeline import cram_progress
from ..models import Deadline, Topic, WeakSpot
from ..render import MUTED, accent, exam_words
from .actions import CourseActions, matches
from .widgets import BigTimeline, Row, VimList, DeadlineRow, empty_row, session_row, topic_row, weak_row


class SubjectScreen(CourseActions, Screen):
    BINDINGS = [
        Binding("escape", "back", "Back"),
        Binding("left_square_bracket", "step(-1)", "Prev/next", key_display="[ ]"),
        Binding("right_square_bracket", "step(1)", "Next subject", show=False),
        Binding("a", "add", "Add"),
        Binding("l", "quick_log", "Log"),
        Binding("w", "add_weak", "Weak spot", show=False),
        Binding("s", "toggle_timer", "Timer"),
        Binding("p", "pomodoro", "Pomodoro"),
        Binding("n", "pomodoro_next", "Next block", show=False),
        Binding("P", "pomodoro_stop", "Stop Pomodoro", show=False),
        Binding("space", "toggle", "Done / next status", show=False),
        Binding("e", "edit", "Edit"),
        Binding("E", "edit_course", "Edit course", show=False),
        Binding("d", "delete", "Delete"),
        Binding("plus,equals_sign", "confidence(1)", "Confidence +", show=False, key_display="+"),
        Binding("minus", "confidence(-1)", "Confidence -", show=False, key_display="-"),
        Binding("slash", "filter", "Filter", key_display="/"),
        Binding("r", "reading", "Reading"),
    ]

    def __init__(self, course_id: int) -> None:
        super().__init__()
        self.course_id = course_id
        self.filter_text = ""
        self._reload_lock = asyncio.Lock()  # typing a filter fires reloads faster than they finish

    def compose(self) -> ComposeResult:
        yield Static(id="topbar")
        yield Static(id="banner")
        yield Static(id="subject-head")
        yield Static(id="big-timeline", classes="pane")
        with Horizontal(id="subject"):
            yield VimList(id="topics", classes="pane")
            with Vertical(id="subject-side"):
                yield VimList(id="s-weak", classes="pane")
                yield VimList(id="s-deadlines", classes="pane")
                yield VimList(id="sessions", classes="pane")
        yield Input(id="filter", placeholder="Filter topics, weak spots, deadlines and sessions (esc clears)")
        yield Footer()

    async def on_mount(self) -> None:
        self.query_one("#big-timeline").border_title = "Cram timeline"
        self.query_one("#s-weak").border_title = "Weak spots"
        self.query_one("#s-deadlines").border_title = "Deadlines"
        await self.reload()
        self.query_one("#topics").focus()

    async def on_screen_resume(self) -> None:
        await self.reload()

    # ----- data -----

    async def reload(self) -> None:
        async with self._reload_lock:
            await self._reload()

    async def _reload(self) -> None:
        store, cfg = self.app.store, self.app.cfg
        course = store.get_course(self.course_id)
        if course is None:  # deleted elsewhere
            self.app.pop_screen()
            return
        now = datetime.now()
        topics = store.list_topics(course.id)
        topics_by_id = {t.id: t for t in topics}
        progress = cram_progress(course, topics, now.date())

        head = Table.grid(expand=True)
        head.add_column()
        head.add_column(justify="right")
        name = Text()
        name.append("● ", style=accent(course))
        name.append(course.code, style=f"bold {accent(course)}")
        name.append(f"  {course.name}", style="bold")
        head.add_row(name, Text(exam_words(course, progress), style="bold" if progress.days_left <= 7 else MUTED))
        if course.notes:
            head.add_row(Text(course.notes, style=MUTED), "")
        self.query_one("#subject-head", Static).update(head)
        self.query_one("#big-timeline", Static).update(BigTimeline(course, progress, now.date()))

        q = self.filter_text
        none = "Nothing matches the filter." if q else None
        reading = store.reading_by_topic(course.id)
        await self._fill("#topics", [
            Row(topic_row(t, now.date(), cfg.stale_after_days, reading.get(t.id)), t) for t in topics
            if matches(q, t.title, t.status.label)
        ] or [empty_row(none or "No topics yet. Press a to add one.")])
        done = sum(1 for t in topics if t.status.is_done)
        self.query_one("#topics").border_title = f"Topics · {done}/{len(topics)} done"
        total = store.reading_progress(course.id)
        self.query_one("#topics").border_subtitle = (
            f"reading {total.read}/{total.required} · r opens the list" if total.required else "r for the reading list")

        weak = store.list_weak_spots(course.id)
        await self._fill("#s-weak", [
            Row(weak_row(w, now, None, topics_by_id.get(w.topic_id)), w) for w in weak
            if matches(q, w.description, topics_by_id[w.topic_id].title if w.topic_id in topics_by_id else "")
        ] or [empty_row(none or "No open weak spots.")])

        deadlines = store.list_deadlines(course.id)
        await self._fill("#s-deadlines", [
            Row(DeadlineRow(d, now, None, show_course=False), d) for d in deadlines
            if matches(q, d.title, d.kind.value)
        ] or [empty_row(none or "Nothing due.")])

        sessions = store.list_sessions(course.id, limit=30)
        start, end = week_range(now.date(), cfg.week_start)
        week = minutes_between(store.list_sessions(course.id, since=start, until=end), start, end)
        await self._fill("#sessions", [
            Row(session_row(s, topics_by_id.get(s.topic_id)), s) for s in sessions
            if matches(q, s.note, topics_by_id[s.topic_id].title if s.topic_id in topics_by_id else "")
        ] or [empty_row(none or "No sessions yet. Press l to log one, or s to start the timer.")])
        sessions_pane = self.query_one("#sessions")
        sessions_pane.border_title = "Recent sessions"
        sessions_pane.border_subtitle = f"{format_minutes(week)} this week · {format_minutes(store.total_minutes(course.id))} total"
        self.update_topbar()

    async def _fill(self, selector: str, rows: list[Row]) -> None:
        lv = self.query_one(selector, VimList)
        keep = lv.index or 0
        await lv.clear()
        await lv.extend(rows)
        lv.index = min(keep, len(rows) - 1)

    def update_topbar(self) -> None:
        for bar in self.query("#topbar").results(Static):  # nothing to update until the screen is built
            bar.update(self.app.topbar())
        self.app.show_banner(self)

    # ----- what the keys act on -----

    def current_course_id(self) -> int | None:
        return self.course_id

    def current_topic_id(self) -> int | None:
        topics = self.query_one("#topics", VimList)
        if self.focused is topics and isinstance(topics.current, Topic):
            return topics.current.id
        return None

    # ----- actions -----

    async def action_back(self) -> None:
        box = self.query_one("#filter", Input)
        if box.has_class("-shown"):  # esc clears the filter first
            box.value = ""
            box.remove_class("-shown")
            self.filter_text = ""
            await self.reload()
            self.query_one("#topics").focus()
            return
        self.app.pop_screen()

    def _highlighted(self):
        focused = self.focused
        return focused.current if isinstance(focused, VimList) else None

    def action_edit(self) -> None:
        item = self._highlighted()
        if item is None:
            self.action_edit_course()
        else:
            self.edit_item(item)

    def action_reading(self) -> None:
        from .reading import ReadingScreen

        self.app.push_screen(ReadingScreen(self.course_id, focus_topic=self.current_topic_id()))

    def action_edit_course(self) -> None:
        course = self.app.store.get_course(self.course_id)
        if course:
            self.edit_course(course)

    def action_delete(self) -> None:
        self.delete_item(self._highlighted())

    def action_confidence(self, delta: int) -> None:
        item = self._highlighted()
        if isinstance(item, Topic):
            self.adjust_confidence(item, delta)
        else:
            self.app.notify("+ and - change a topic's confidence. Highlight a topic first.")

    def action_filter(self) -> None:
        box = self.query_one("#filter", Input)
        box.add_class("-shown")
        box.focus()

    async def on_input_changed(self, event: Input.Changed) -> None:
        if event.input.id == "filter":
            self.filter_text = event.value.strip()
            await self.reload()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id == "filter":
            self.query_one("#topics").focus()

    async def action_step(self, delta: int) -> None:
        ids = [c.id for c in self.app.store.list_courses()]
        if self.course_id not in ids:
            return
        self.course_id = ids[(ids.index(self.course_id) + delta) % len(ids)]
        for lv in self.query(VimList):
            lv.index = 0
        await self.reload()

    def action_add(self) -> None:
        pane = self.focused.id if self.focused else "topics"
        if pane == "s-weak":
            self.action_add_weak()
        elif pane == "s-deadlines":
            self.add_deadline(self.course_id)
        elif pane == "sessions":
            self.action_quick_log()
        else:
            self.action_add_topic()

    def action_toggle(self) -> None:
        focused = self.focused
        item = focused.current if isinstance(focused, VimList) else None
        if isinstance(item, Deadline):
            self.toggle_deadline(item)
        elif isinstance(item, WeakSpot):
            self.toggle_weak(item)
        elif isinstance(item, Topic):
            self.cycle_status(item)
        else:
            self.app.notify("Space moves a topic to its next status, marks a deadline done or resolves a weak spot.")
