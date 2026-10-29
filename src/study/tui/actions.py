"""Actions shared by the overview and the subject screen. Each one works on the screen's current course:
on the overview that's the highlighted subject, or the course of the highlighted deadline or weak spot."""

from __future__ import annotations

from datetime import datetime, time, timedelta
from typing import TYPE_CHECKING, Any

from ..logic.dates import DateParseError, format_date, format_datetime, parse_date, parse_datetime, parse_minutes
from ..logic.stats import format_minutes
from ..models import COURSE_COLORS, Course, Deadline, DeadlineKind, Priority, Session, Topic, TopicStatus, WeakSpot
from ..storage import StorageError
from .dialogs import ConfirmModal
from .forms import Field, FormModal, FormSpec

if TYPE_CHECKING:
    from .app import StudyApp

ASSIGNMENT_TIME = time(23, 59)
COLOR_NAMES = ("Blue", "Coral", "Teal", "Violet", "Amber", "Green", "Pink", "Slate")
STATUS_ORDER = list(TopicStatus)


def minutes_or_none(text: str) -> int | None:
    try:
        return parse_minutes(text)
    except DateParseError:
        return None


def matches(query: str, *texts: str | None) -> bool:
    """Case-insensitive: every word of the filter appears somewhere in the row's text."""
    hay = " ".join(t for t in texts if t).lower()
    return all(word in hay for word in query.lower().split())


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
                Field("due", "Due", placeholder="fri 14:00, 01.12.2026, +3d (no time = 23:59)"),
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
                Field("cram_start", "Cramming starts", value="today", placeholder="today, 01.11, +3d"),
                Field("exam", "Exam date", placeholder="10.12.2026, 10.12, +3w"),
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

    def cycle_status(self, topic: Topic) -> None:
        """Move a topic to its next status: not started → in progress → reviewed → confident → not started."""
        topic.status = STATUS_ORDER[(STATUS_ORDER.index(topic.status) + 1) % len(STATUS_ORDER)]
        if self._try(self.app.store.update_topic, topic):
            self._done(f"{topic.title}: {topic.status.label}.")

    def adjust_confidence(self, topic: Topic, delta: int) -> None:
        t = self._try(self.app.store.adjust_confidence, topic.id, delta)
        if t:
            self._done(f"{t.title}: confidence {t.confidence}/5.")

    # ----- edit -----

    def edit_item(self, item: Any) -> None:
        store = self.app.store
        if isinstance(item, int):
            item = store.get_course(item)
        editors = {Course: self.edit_course, Topic: self.edit_topic, WeakSpot: self.edit_weak,
                   Deadline: self.edit_deadline, Session: self.edit_session}
        editor = editors.get(type(item))
        if editor is None:
            self.app.notify("Highlight something to edit first.", severity="warning")
            return
        editor(item)

    def _date_check(self, *names: str, optional: tuple[str, ...] = ()):
        today = datetime.now().date()

        def check(v: dict) -> str | None:
            for name in names:
                if name in optional and not v[name]:
                    continue
                try:
                    parse_date(v[name], today)
                except DateParseError as e:
                    return str(e)
            return None

        return check

    def edit_course(self, course: Course) -> None:
        colors = list(zip(COLOR_NAMES, COURSE_COLORS))
        if course.color not in COURSE_COLORS:
            colors.append((f"Custom {course.color}", course.color))
        today = datetime.now().date()
        spec = FormSpec(
            title=f"Edit {course.code}",
            fields=[
                Field("name", "Name", course.name),
                Field("code", "Short code", course.code),
                Field("cram_start", "Cramming starts", format_date(course.cram_start)),
                Field("exam", "Exam date", format_date(course.exam_date)),
                Field("color", "Colour", course.color, options=colors),
                Field("notes", "Notes", course.notes, optional=True),
            ],
            check=self._date_check("cram_start", "exam"),
        )

        def save(v: dict | None) -> None:
            if v is None:
                return
            course.name, course.code, course.color, course.notes = v["name"], v["code"], v["color"], v["notes"]
            course.cram_start, course.exam_date = parse_date(v["cram_start"], today), parse_date(v["exam"], today)
            if self._try(self.app.store.update_course, course):
                self._done(f"Saved {course.code}.")

        self.app.push_screen(FormModal(spec), save)

    def edit_topic(self, topic: Topic) -> None:
        today = datetime.now().date()
        spec = FormSpec(
            title="Edit topic",
            fields=[
                Field("title", "Topic", topic.title),
                Field("status", "Status", topic.status.value, options=[(s.label.capitalize(), s.value) for s in TopicStatus]),
                Field("confidence", "Confidence", str(topic.confidence), options=[(f"{n}/5", str(n)) for n in range(1, 6)]),
                Field("last", "Last studied", format_date(topic.last_studied) if topic.last_studied else "",
                      placeholder="e.g. today, -3d, 02.11.2026", optional=True),
            ],
            check=self._date_check("last", optional=("last",)),
        )

        def save(v: dict | None) -> None:
            if v is None:
                return
            topic.title, topic.status, topic.confidence = v["title"], TopicStatus(v["status"]), int(v["confidence"])
            topic.last_studied = parse_date(v["last"], today) if v["last"] else None
            if self._try(self.app.store.update_topic, topic):
                self._done(f"Saved {topic.title!r}.")

        self.app.push_screen(FormModal(spec), save)

    def edit_weak(self, weak: WeakSpot) -> None:
        spec = FormSpec(
            title="Edit weak spot",
            fields=[
                Field("description", "What's weak", weak.description),
                Field("priority", "Priority", weak.priority.value,
                      options=[("High", "high"), ("Medium", "med"), ("Low", "low")]),
                Field("topic", "Topic", weak.topic_id or "",
                      options=[(t.title, t.id) for t in self.app.store.list_topics(weak.course_id)], optional=True),
            ],
        )

        def save(v: dict | None) -> None:
            if v is None:
                return
            weak.description, weak.priority, weak.topic_id = v["description"], Priority(v["priority"]), v["topic"]
            if self._try(self.app.store.update_weak_spot, weak):
                self._done("Saved the weak spot.")

        self.app.push_screen(FormModal(spec), save)

    def edit_deadline(self, deadline: Deadline) -> None:
        now = datetime.now()
        fields = [
            Field("title", "What's due", deadline.title),
            Field("due", "Due", format_datetime(deadline.due_at), placeholder="fri 14:00, 01.12.2026 09:00"),
        ]
        if not deadline.is_course_exam:  # the course's own exam stays tied to its course
            fields += [
                Field("course", "Course", deadline.course_id or "", optional=True,
                      options=[(f"{c.code} · {c.name}", c.id) for c in self.app.store.list_courses()]),
                Field("kind", "Type", deadline.kind.value,
                      options=[("Assignment", "assignment"), ("Milestone", "milestone"), ("Exam", "exam")]),
            ]

        def check(v: dict) -> str | None:
            try:
                parse_datetime(v["due"], now, deadline.due_at.time())
            except DateParseError as e:
                return str(e)
            return None

        def save(v: dict | None) -> None:
            if v is None:
                return
            deadline.title = v["title"]
            deadline.due_at = parse_datetime(v["due"], datetime.now(), deadline.due_at.time())
            if not deadline.is_course_exam:
                deadline.course_id, deadline.kind = v["course"], DeadlineKind(v["kind"])
            if self._try(self.app.store.update_deadline, deadline):
                self._done(f"Saved {deadline.title!r}.")

        self.app.push_screen(FormModal(FormSpec("Edit deadline", fields, check)), save)

    def edit_session(self, session: Session) -> None:
        now = datetime.now()
        spec = FormSpec(
            title="Edit session",
            fields=[
                Field("minutes", "How long", str(session.minutes), placeholder="45, 90m or 1h30m"),
                Field("start", "Started", format_datetime(session.started_at)),
                Field("topic", "Topic", session.topic_id or "", optional=True,
                      options=[(t.title, t.id) for t in self.app.store.list_topics(session.course_id)]),
                Field("note", "Note", session.note, optional=True),
            ],
        )

        def check(v: dict) -> str | None:
            if (minutes_or_none(v["minutes"]) or 0) <= 0:
                return "Use minutes, like 45, or 1h30m."
            try:
                parse_datetime(v["start"], now, session.started_at.time())
            except DateParseError as e:
                return str(e)
            return None

        spec.check = check

        def save(v: dict | None) -> None:
            if v is None:
                return
            session.minutes = minutes_or_none(v["minutes"]) or session.minutes
            session.started_at = parse_datetime(v["start"], datetime.now(), session.started_at.time())
            session.topic_id, session.note = v["topic"], v["note"]
            if self._try(self.app.store.update_session, session):
                self._done("Saved the session.")

        self.app.push_screen(FormModal(spec), save)

    # ----- delete -----

    def delete_item(self, item: Any) -> None:
        store = self.app.store
        if isinstance(item, int):
            item = store.get_course(item)
        if isinstance(item, Course):
            topics = store.list_topics(item.id)
            weak = store.list_weak_spots(item.id, include_resolved=True)
            deadlines = store.list_deadlines(item.id, include_done=True)
            sessions = store.list_sessions(item.id)
            detail = (f"This also deletes its {len(topics)} topics, {len(weak)} weak spots, {len(deadlines)} deadlines "
                      f"and {len(sessions)} sessions ({format_minutes(sum(s.minutes for s in sessions))} of study). "
                      "There's no undo. study export makes a copy first.")
            title, action = f"Delete {item.code} · {item.name}?", lambda: store.delete_course(item.id)
        elif isinstance(item, Topic):
            title, detail = f"Delete the topic {item.title!r}?", "Its sessions and weak spots stay, without a topic."
            action = lambda: store.delete_topic(item.id)  # noqa: E731
        elif isinstance(item, WeakSpot):
            title, detail, action = f"Delete the weak spot {item.description!r}?", "", lambda: store.delete_weak_spot(item.id)
        elif isinstance(item, Deadline):
            if item.is_course_exam:
                self.app.notify("A course's exam goes with the course. Press e on it to move the date instead.",
                                severity="warning")
                return
            title, detail, action = f"Delete the deadline {item.title!r}?", "", lambda: store.delete_deadline(item.id)
        elif isinstance(item, Session):
            title = f"Delete the {format_minutes(item.minutes)} session from {item.started_at:%a %d %b %H:%M}?"
            detail, action = "", lambda: store.delete_session(item.id)
        else:
            self.app.notify("Highlight something to delete first.", severity="warning")
            return

        def answer(yes: bool | None) -> None:
            if yes and self._try(action) is None:
                self._done("Deleted.")

        self.app.push_screen(ConfirmModal(title, detail), answer)

