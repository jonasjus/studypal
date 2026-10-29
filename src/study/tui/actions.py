"""Actions shared by the overview and the subject screen. Each one works on the screen's current course:
on the overview that's the highlighted subject, or the course of the highlighted deadline or weak spot."""

from __future__ import annotations

from datetime import datetime, time, timedelta
from typing import TYPE_CHECKING, Any

from ..logic.dates import DateParseError, parse_date, parse_datetime, parse_minutes
from ..logic.stats import format_minutes
from ..models import Course, Deadline, DeadlineKind, Priority, Session, Topic, WeakSpot
from ..storage import StorageError
from .forms import Field, FormModal, FormSpec

if TYPE_CHECKING:
    from .app import StudyApp

ASSIGNMENT_TIME = time(23, 59)


def minutes_or_none(text: str) -> int | None:
    try:
        return parse_minutes(text)
    except DateParseError:
        return None


class CourseActions:
    """Mixed into screens. A screen supplies `current_course_id`, `current_topic_id` and `reload`."""

    app: StudyApp

    # ----- supplied by the screen -----

    def current_course_id(self) -> int | None:
        raise NotImplementedError

    def current_topic_id(self) -> int | None:
        return None

    async def reload(self) -> None:
        raise NotImplementedError

    # ----- helpers -----

    def _course(self) -> Course | None:
        cid = self.current_course_id()
        course = self.app.store.get_course(cid) if cid is not None else None
        if course is None:
            self.app.notify("Add a course first: press a in the Subjects pane.", severity="warning")
        return course

    def _done(self, message: str | None = None) -> None:
        if message:
            self.app.notify(message)
        self.app.refresh_everything()

    def _try(self, fn, *args: Any, **kwargs: Any) -> Any:
        try:
            return fn(*args, **kwargs)
        except (StorageError, DateParseError) as e:
            self.app.notify(str(e), severity="error")
            return None

    def _topic_options(self, course: Course) -> list[tuple[str, int]]:
        return [(t.title, t.id) for t in self.app.store.list_topics(course.id)]

    # ----- timers -----

    def action_toggle_timer(self) -> None:
        store = self.app.store
        if store.get_timer() is not None:
            try:
                session = store.stop_timer()
            except StorageError as e:
                self.app.notify(str(e), severity="error")
                return
            if session is None:
                self._done("Timer stopped. It ran under a minute, so nothing was logged.")
            else:
                course = store.get_course(session.course_id)
                self._done(f"Logged {format_minutes(session.minutes)} on {course.code if course else 'the course'}.")
            return
        course = self._course()
        if course and self._try(store.start_timer, course.id, self.current_topic_id()):
            self._done(f"Timer started on {course.code}. Press s again to stop and log it.")

    def action_pomodoro(self) -> None:
        """Start a Pomodoro on the current course, or pause/resume the one that's running."""
        store, settings = self.app.store, self.app.cfg.pomodoro
        run = store.get_pomodoro()
        if run is None:
            course = self._course()
            if course and self._try(store.start_pomodoro, course.id, self.current_topic_id()):
                minutes = int(settings.focus.total_seconds() // 60)
                self._done(f"Pomodoro started on {course.code}: {minutes} minutes of focus.")
            return
        if run.paused:
            self._try(store.resume_pomodoro, settings=settings)
            self._done("Pomodoro resumed.")
        else:
            self._try(store.pause_pomodoro, settings=settings)
            self._done("Pomodoro paused. Paused time isn't logged.")

    def action_pomodoro_next(self) -> None:
        store = self.app.store
        if store.get_pomodoro() is None:
            self.app.notify("No Pomodoro running. Press p to start one.", severity="warning")
            return
        if self._try(store.pomodoro_next, settings=self.app.cfg.pomodoro):
            self._done("Next focus block started.")

    def action_pomodoro_stop(self) -> None:
        store = self.app.store
        if store.get_pomodoro() is None:
            self.app.notify("No Pomodoro running.", severity="warning")
            return
        logged = self._try(store.stop_pomodoro, settings=self.app.cfg.pomodoro)
        if logged is not None:
            minutes = sum(s.minutes for s in logged)
            self._done(f"Pomodoro stopped. Logged {format_minutes(minutes)}." if minutes else "Pomodoro stopped.")

    # ----- quick adds for the current course -----

    def action_quick_log(self) -> None:
        course = self._course()
        if not course:
            return
        spec = FormSpec(
            title=f"Log study time · {course.code}",
            fields=[
                Field("minutes", "How long", placeholder="45, 90m or 1h30m"),
                Field("topic", "Topic", options=self._topic_options(course), optional=True,
                      value=self.current_topic_id() or ""),
                Field("note", "Note", optional=True),
            ],
            check=lambda v: None if (minutes_or_none(v["minutes"]) or 0) > 0 else "Use minutes, like 45, or 1h30m.",
        )

        def save(values: dict | None) -> None:
            if values is None:
                return
            minutes = minutes_or_none(values["minutes"]) or 0
            start = datetime.now().replace(second=0, microsecond=0)
            if self._try(self.app.store.log_session,
                         Session(course.id, start - timedelta(minutes=minutes), minutes, values["topic"], values["note"])):
                self._done(f"Logged {format_minutes(minutes)} on {course.code}.")

        self.app.push_screen(FormModal(spec), save)

    def action_add_weak(self) -> None:
        course = self._course()
        if not course:
            return
        spec = FormSpec(
            title=f"New weak spot · {course.code}",
            fields=[
                Field("description", "What's weak", placeholder="e.g. Deriving the SVM dual"),
                Field("priority", "Priority", value="med", options=[("High", "high"), ("Medium", "med"), ("Low", "low")]),
                Field("topic", "Topic", options=self._topic_options(course), optional=True,
                      value=self.current_topic_id() or ""),
            ],
        )

        def save(values: dict | None) -> None:
            if values and self._try(self.app.store.add_weak_spot,
                                    WeakSpot(course.id, values["description"], Priority(values["priority"]), values["topic"])):
                self._done(f"Weak spot noted for {course.code}.")

        self.app.push_screen(FormModal(spec), save)

    def action_add_topic(self) -> None:
        course = self._course()
        if not course:
            return
        spec = FormSpec(title=f"New topic · {course.code}", fields=[Field("title", "Topic", placeholder="e.g. Kernels and SVMs")])

        def save(values: dict | None) -> None:
            if values and self._try(self.app.store.add_topic, Topic(course.id, values["title"])):
                self._done(f"Added {values['title']!r} to {course.code}.")

        self.app.push_screen(FormModal(spec), save)

    def add_deadline(self, course_id: int | None) -> None:
        courses = self.app.store.list_courses()
        now = datetime.now()

        def check(v: dict) -> str | None:
            try:
                parse_datetime(v["due"], now, now.time())
            except DateParseError as e:
                return str(e)
            return None

        spec = FormSpec(
            title="New deadline",
            fields=[
                Field("title", "What's due", placeholder="e.g. Problem set 4"),
                Field("due", "Due", placeholder="fri 14:00, 2026-12-01, +3d (no time = 23:59)"),
                Field("course", "Course", options=[(f"{c.code} · {c.name}", c.id) for c in courses], optional=True,
                      value=course_id if course_id is not None else ""),
                Field("kind", "Type", value="assignment",
                      options=[("Assignment", "assignment"), ("Milestone", "milestone"), ("Exam", "exam")]),
            ],
            check=check,
        )

        def save(values: dict | None) -> None:
            if values is None:
                return
            kind = DeadlineKind(values["kind"])
            default = self.app.cfg.default_exam_time if kind is DeadlineKind.EXAM else ASSIGNMENT_TIME
            due = parse_datetime(values["due"], datetime.now(), default)
            if self._try(self.app.store.add_deadline, Deadline(values["title"], due, kind, values["course"])):
                self._done(f"Added {values['title']!r}, due {due:%a %d %b %H:%M}.")

        self.app.push_screen(FormModal(spec), save)

    def add_course(self) -> None:
        today = datetime.now().date()

        def check(v: dict) -> str | None:
            try:
                start = parse_date(v["cram_start"] or "today", today)
                exam = parse_date(v["exam"], today)
            except DateParseError as e:
                return str(e)
            return "The exam can't be before cramming starts." if exam < start else None

        spec = FormSpec(
            title="New course",
            fields=[
                Field("name", "Name", placeholder="e.g. Machine Learning"),
                Field("code", "Short code", placeholder="e.g. INF301"),
                Field("cram_start", "Cramming starts", value="today", placeholder="today, 11-01, +3d"),
                Field("exam", "Exam date", placeholder="2026-12-10, 12-10, +3w"),
            ],
            check=check,
        )

        def save(values: dict | None) -> None:
            if values is None:
                return
            store = self.app.store
            course = Course(values["name"], values["code"], parse_date(values["cram_start"] or "today", today),
                            parse_date(values["exam"], today), store.next_color())
            if self._try(store.add_course, course):
                self._done(f"Added {course.code}. Its exam is on your deadline list.")

        self.app.push_screen(FormModal(spec), save)

    # ----- ticking things off -----

    def toggle_deadline(self, deadline: Deadline) -> None:
        d = self._try(self.app.store.toggle_deadline, deadline.id)
        if d:
            self._done(f"{d.title}: {'done' if d.done else 'not done'}.")

    def toggle_weak(self, weak: WeakSpot) -> None:
        w = self._try(self.app.store.toggle_weak_spot, weak.id)
        if w:
            self._done("Weak spot resolved." if w.resolved else "Weak spot reopened.")
