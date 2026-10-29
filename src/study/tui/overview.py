"""The overview: deadlines, subjects with their cram timelines, weak spots and this week's study time.

Keys act on the course you're looking at: the highlighted subject, or the course of the
highlighted deadline or weak spot.
"""

from __future__ import annotations

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.screen import Screen
from textual.widgets import Footer, ListView, Static

from .. import dashboard
from ..dashboard import Dashboard
from ..models import Deadline, WeakSpot
from .actions import CourseActions
from .widgets import CourseRow, Row, VimList, WeekChart, deadline_row, empty_row, weak_row


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
    ]

    def __init__(self) -> None:
        super().__init__()
        self.dash: Dashboard | None = None

    def compose(self) -> ComposeResult:
        yield Static(id="topbar")
        with Horizontal(id="overview"):
            with Vertical(id="left"):
                yield VimList(id="courses", classes="pane")
            with Vertical(id="right"):
                yield VimList(id="deadlines", classes="pane")
                yield VimList(id="weak", classes="pane")
                yield Static(id="week", classes="pane")
        yield Footer()

    async def on_mount(self) -> None:
        self.query_one("#courses").border_title = "Subjects"
        self.query_one("#deadlines").border_title = "Upcoming deadlines"
        self.query_one("#weak").border_title = "Weak spots"
        self.query_one("#week").border_title = "This week"
        await self.reload()
        self.query_one("#courses").focus()

    async def on_screen_resume(self) -> None:
        await self.reload()

    # ----- data -----

    async def reload(self) -> None:
        app = self.app
        self.dash = dash = dashboard.build(app.store, app.cfg)
        courses = {s.course.id: s.course for s in dash.courses}

        await self._fill("#courses", [
            Row(CourseRow(s, i if i <= 9 else None), s.course.id) for i, s in enumerate(dash.courses, start=1)
        ] or [empty_row("No courses yet. Press a to add your first one.")])

        await self._fill("#deadlines", [
            Row(deadline_row(d, dash.now, courses.get(d.course_id)), d) for d in dash.deadlines
        ] or [empty_row("Nothing due. Press a here to add a deadline.")])

        await self._fill("#weak", [
            Row(weak_row(w, dash.now, courses.get(w.course_id)), w) for w in dash.weak_spots
        ] or [empty_row("No open weak spots.")])

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

    def action_toggle(self) -> None:
        focused = self.focused
        item = focused.current if isinstance(focused, VimList) else None
        if isinstance(item, Deadline):
            self.toggle_deadline(item)
        elif isinstance(item, WeakSpot):
            self.toggle_weak(item)
        else:
            self.app.notify("Space marks a deadline done or a weak spot resolved. Tab to one of those panes first.")
