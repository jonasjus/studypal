"""The overview: deadlines, subjects with their cram timelines, weak spots and this week's study time.

Keys act on the course you're looking at: the highlighted subject, or the course of the
highlighted deadline or weak spot.
"""

from __future__ import annotations

import asyncio

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.screen import Screen
from textual.widgets import Footer, Input, ListView, Static

from .. import dashboard
from ..dashboard import Dashboard
from ..models import Deadline, WeakSpot
from .actions import CourseActions, matches
from .widgets import CourseRow, Row, VimList, WeekChart, DeadlineRow, empty_row, weak_row


class OverviewScreen(CourseActions, Screen):
    BINDINGS = [
        Binding("enter", "open_current", "Open", show=False),
        *[Binding(str(n), f"open_number({n})", f"Course {n}", show=False) for n in range(1, 10)],
        Binding("a", "add", "Add"),
        Binding("t", "add_topic", "Topic", show=False),
        Binding("l", "quick_log", "Log"),
        Binding("w", "add_weak", "Weak spot"),
        Binding("s", "toggle_timer", "Timer"),
        Binding("p", "pomodoro", "Pomodoro"),
        Binding("n", "pomodoro_next", "Next block", show=False),
        Binding("P", "pomodoro_stop", "Stop Pomodoro", show=False),
        Binding("space", "toggle", "Done", show=False),
        Binding("e", "edit", "Edit"),
        Binding("d", "delete", "Delete"),
        Binding("slash", "filter", "Filter", key_display="/"),
        Binding("escape", "clear_filter", "Clear filter", show=False),
    ]

    def __init__(self) -> None:
        super().__init__()
        self.dash: Dashboard | None = None
        self.filter_text = ""
        self._reload_lock = asyncio.Lock()  # typing a filter fires reloads faster than they finish

    def compose(self) -> ComposeResult:
        yield Static(id="topbar")
        yield Static(id="banner")
        with Horizontal(id="overview"):
            with Vertical(id="left"):
                yield VimList(id="courses", classes="pane")
            with Vertical(id="right"):
                yield VimList(id="deadlines", classes="pane")
                yield VimList(id="weak", classes="pane")
                yield Static(id="week", classes="pane")
        yield Input(id="filter", placeholder="Filter subjects, deadlines and weak spots (esc clears)")
        yield Footer()

    async def on_mount(self) -> None:
        self.query_one("#courses").border_title = "Subjects"
        self.query_one("#deadlines").border_title = "Upcoming deadlines"
        self.query_one("#weak").border_title = "Weak spots"
        self.query_one("#week").border_title = "This week"
        await self.reload()
        self.query_one("#courses").focus()
        # The launch toast goes on this screen, once it's showing (the overview is mounted once per run).
        self.app.call_after_refresh(self.app.every_minute, True)

    async def on_screen_resume(self) -> None:
        await self.reload()

    # ----- data -----

    async def reload(self) -> None:
        async with self._reload_lock:
            await self._reload()

    async def _reload(self) -> None:
        app = self.app
        self.dash = dash = dashboard.build(app.store, app.cfg)
        courses = {s.course.id: s.course for s in dash.courses}
        q = self.filter_text

        def code(course_id: int | None) -> str:
            return courses[course_id].code if course_id in courses else ""

        # Numbers 1-9 always follow the unfiltered order, so a course keeps its number while filtering.
        numbered = [(i, s) for i, s in enumerate(dash.courses, start=1)]
        await self._fill("#courses", [
            Row(CourseRow(s, i if i <= 9 else None), s.course.id) for i, s in numbered
            if matches(q, s.course.code, s.course.name)
        ] or [empty_row("No subjects match the filter." if q else "No courses yet. Press a to add your first one.")])

        await self._fill("#deadlines", [
            Row(DeadlineRow(d, dash.now, courses.get(d.course_id)), d) for d in dash.deadlines
            if matches(q, d.title, code(d.course_id), d.kind.value)
        ] or [empty_row("No deadlines match the filter." if q else "Nothing due. Press a here to add a deadline.")])

        await self._fill("#weak", [
            Row(weak_row(w, dash.now, courses.get(w.course_id)), w) for w in dash.weak_spots
            if matches(q, w.description, code(w.course_id), w.priority.value)
        ] or [empty_row("No weak spots match the filter." if q else "No open weak spots.")])

        self.query_one("#week", Static).update(WeekChart(dash.week_days, dash.week_minutes, dash.today))
        self.query_one("#deadlines").border_subtitle = f"{len(dash.deadlines)} open"
        self.query_one("#weak").border_subtitle = f"{len(dash.weak_spots)} open"
        self.update_topbar()

    async def _fill(self, selector: str, rows: list[Row]) -> None:
        lv = self.query_one(selector, VimList)
        keep = lv.index or 0
        await lv.clear()
        await lv.extend(rows)
        lv.index = min(keep, len(rows) - 1)

    def update_topbar(self) -> None:
        if self.dash is None:
            return
        for bar in self.query("#topbar").results(Static):  # nothing to update until the screen is built
            bar.update(self.app.topbar(self.dash.week_minutes))
        self.app.show_banner(self)

    # ----- which course the keys act on -----

    def current_course_id(self) -> int | None:
        focused = self.focused
        if isinstance(focused, VimList) and focused.id in ("deadlines", "weak"):
            item = focused.current
            if isinstance(item, (Deadline, WeakSpot)) and item.course_id is not None:
                return item.course_id
        courses = self.query_one("#courses", VimList)
        return courses.current if isinstance(courses.current, int) else None

    # ----- actions -----

    def action_open_current(self) -> None:
        cid = self.current_course_id()
        if cid is not None:
            self.app.open_subject(cid)

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        event.stop()
        self.action_open_current()

    def action_open_number(self, n: int) -> None:
        if self.dash and 1 <= n <= len(self.dash.courses):
            self.app.open_subject(self.dash.courses[n - 1].course.id)

    def action_add(self) -> None:
        pane = self.focused.id if self.focused else "courses"
        if pane == "deadlines":
            self.add_deadline(self.current_course_id())
        elif pane == "weak":
            self.action_add_weak()
        else:
            self.add_course()

    # ----- edit, delete, filter -----

    def _highlighted(self):
        focused = self.focused
        if isinstance(focused, VimList):
            return focused.current
        return self.query_one("#courses", VimList).current

    def action_edit(self) -> None:
        self.edit_item(self._highlighted())

    def action_delete(self) -> None:
        self.delete_item(self._highlighted())

    def action_filter(self) -> None:
        box = self.query_one("#filter", Input)
        box.add_class("-shown")
        box.focus()

    async def action_clear_filter(self) -> None:
        box = self.query_one("#filter", Input)
        if not box.has_class("-shown"):
            return
        box.value = ""
        box.remove_class("-shown")
        self.filter_text = ""
        await self.reload()
        self.query_one("#courses").focus()

    async def on_input_changed(self, event: Input.Changed) -> None:
        if event.input.id == "filter":
            self.filter_text = event.value.strip()
            await self.reload()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id == "filter":
            self.query_one("#courses").focus()

    def action_toggle(self) -> None:
        focused = self.focused
        item = focused.current if isinstance(focused, VimList) else None
        if isinstance(item, Deadline):
            self.toggle_deadline(item)
        elif isinstance(item, WeakSpot):
            self.toggle_weak(item)
        else:
            self.app.notify("Space marks a deadline done or a weak spot resolved. Tab to one of those panes first.")
