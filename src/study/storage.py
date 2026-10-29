"""SQLite storage. The only module that knows about SQL.

Every method that changes data commits before it returns, so nothing is ever waiting
to be saved. Dates are stored as ISO strings in local time ("2026-12-10", "2026-12-10T09:00").
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import date, datetime, time
from pathlib import Path

from .logic import pomodoro as pomo
from .logic.pomodoro import PomodoroRun, PomodoroSettings, PomoPhase
from .models import (
    COURSE_COLORS,
    ActiveTimer,
    Course,
    Deadline,
    DeadlineKind,
    Priority,
    Session,
    Topic,
    TopicStatus,
    WeakSpot,
)


class StorageError(Exception):
    """Something the user asked for can't be done (unknown course, duplicate code, ...)."""


# Each entry upgrades the schema by one version; PRAGMA user_version records how far we are.
MIGRATIONS: list[str] = [
    """
    create table course (
        id          integer primary key,
        name        text not null,
        code        text not null unique collate nocase,
        cram_start  text not null,
        exam_date   text not null,
        color       text not null,
        notes       text not null default '',
        check (exam_date >= cram_start)
    );

    create table topic (
        id            integer primary key,
        course_id     integer not null references course(id) on delete cascade,
        title         text not null,
        status        text not null default 'not_started'
                      check (status in ('not_started', 'in_progress', 'reviewed', 'confident')),
        confidence    integer not null default 1 check (confidence between 1 and 5),
        last_studied  text
    );
    create index topic_course on topic(course_id);

    create table weak_spot (
        id           integer primary key,
        course_id    integer not null references course(id) on delete cascade,
        topic_id     integer references topic(id) on delete set null,
        description  text not null,
        priority     text not null default 'med' check (priority in ('low', 'med', 'high')),
        created_at   text not null,
        resolved     integer not null default 0,
        resolved_at  text
    );
    create index weak_spot_course on weak_spot(course_id);

    create table deadline (
        id              integer primary key,
        course_id       integer references course(id) on delete cascade,
        title           text not null,
        due_at          text not null,
        kind            text not null default 'assignment' check (kind in ('exam', 'assignment', 'milestone')),
        done            integer not null default 0,
        is_course_exam  integer not null default 0
    );
    create index deadline_due on deadline(due_at);
    create unique index deadline_one_exam_per_course on deadline(course_id) where is_course_exam = 1;

    create table session (
        id          integer primary key,
        course_id   integer not null references course(id) on delete cascade,
        topic_id    integer references topic(id) on delete set null,
        started_at  text not null,
        minutes     integer not null check (minutes > 0),
        note        text not null default ''
    );
    create index session_started on session(started_at);

    -- One row per alert already sent. due_at is part of the key, so moving a deadline re-arms its alerts.
    create table sent_notification (
        deadline_id  integer not null references deadline(id) on delete cascade,
        threshold    text not null,
        due_at       text not null,
        sent_at      text not null,
        primary key (deadline_id, threshold, due_at)
    );

    -- At most one running study timer.
    create table active_timer (
        id          integer primary key check (id = 1),
        course_id   integer not null references course(id) on delete cascade,
        topic_id    integer references topic(id) on delete set null,
        started_at  text not null
    );
    """,
    """
    -- At most one Pomodoro run. Times keep seconds so countdowns stay exact.
    create table pomodoro_run (
        id                integer primary key check (id = 1),
        course_id         integer not null references course(id) on delete cascade,
        topic_id          integer references topic(id) on delete set null,
        phase             text not null check (phase in ('focus', 'short_break', 'long_break', 'ready')),
        phase_started_at  text not null,
        block_started_at  text not null,
        completed         integer not null default 0,
        paused_at         text,
        note              text not null default ''
    );
    """,
    """
    -- Small preferences chosen inside the app (the theme), as opposed to config.toml.
    create table setting (
        key    text primary key,
        value  text not null
    );
    """,
]


def _d(value: str | None) -> date | None:
    return date.fromisoformat(value) if value else None


def _dt(value: str | None) -> datetime | None:
    return datetime.fromisoformat(value) if value else None


def _iso(value: date | datetime | None) -> str | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.replace(second=0, microsecond=0).isoformat(timespec="minutes")
    return value.isoformat()


class Store:
    def __init__(self, path: Path | str, exam_time: time = time(9, 0)) -> None:
        self.path = Path(path)
        self.exam_time = exam_time
        if str(path) != ":memory:":
            self.path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(path), detect_types=0, isolation_level=None)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("pragma foreign_keys = on")
        self.conn.execute("pragma busy_timeout = 3000")  # the TUI and `study notify` may overlap
        if str(path) != ":memory:":
            self.conn.execute("pragma journal_mode = wal")
        self._migrate()

    def close(self) -> None:
        self.conn.close()

    def __enter__(self) -> Store:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    @contextmanager
    def _tx(self) -> Iterator[sqlite3.Connection]:
        self.conn.execute("begin immediate")
        try:
            yield self.conn
        except BaseException:
            self.conn.execute("rollback")
            raise
        else:
            self.conn.execute("commit")

    def _migrate(self) -> None:
        version = self.conn.execute("pragma user_version").fetchone()[0]
        for i, script in enumerate(MIGRATIONS[version:], start=version + 1):
            with self._tx() as c:
                for statement in script.split(";"):
                    if statement.strip():
                        c.execute(statement)
                c.execute(f"pragma user_version = {i}")

    @property
    def schema_version(self) -> int:
        return self.conn.execute("pragma user_version").fetchone()[0]

    # ---------- courses ----------

    @staticmethod
    def _course(r: sqlite3.Row) -> Course:
        return Course(
            id=r["id"], name=r["name"], code=r["code"], cram_start=_d(r["cram_start"]),
            exam_date=_d(r["exam_date"]), color=r["color"], notes=r["notes"],
        )

    def next_color(self) -> str:
        """The first palette colour no course uses yet (cycles once all are taken)."""
        used = [r[0] for r in self.conn.execute("select color from course order by id")]
        for color in COURSE_COLORS:
            if color not in used:
                return color
        return COURSE_COLORS[len(used) % len(COURSE_COLORS)]

    def add_course(self, course: Course) -> Course:
        """Adds the course and its exam deadline (which then follows the course's exam date)."""
        self._check_course(course)
        try:
            with self._tx() as c:
                cur = c.execute(
                    "insert into course (name, code, cram_start, exam_date, color, notes) values (?, ?, ?, ?, ?, ?)",
                    (course.name.strip(), course.code.strip(), _iso(course.cram_start), _iso(course.exam_date),
                     course.color, course.notes),
                )
                course.id = cur.lastrowid
                c.execute(
                    "insert into deadline (course_id, title, due_at, kind, is_course_exam) values (?, ?, ?, 'exam', 1)",
                    (course.id, f"{course.code.strip()} exam", _iso(datetime.combine(course.exam_date, self.exam_time))),
                )
        except sqlite3.IntegrityError as e:
            raise StorageError(self._integrity_message(e, course.code)) from None
        return course

    def update_course(self, course: Course) -> Course:
        self._check_course(course)
        if course.id is None:
            raise StorageError("Can't update a course that hasn't been saved.")
        try:
            with self._tx() as c:
                cur = c.execute(
                    "update course set name = ?, code = ?, cram_start = ?, exam_date = ?, color = ?, notes = ? where id = ?",
                    (course.name.strip(), course.code.strip(), _iso(course.cram_start), _iso(course.exam_date),
                     course.color, course.notes, course.id),
                )
                if cur.rowcount == 0:
                    raise StorageError("That course no longer exists.")
                # Keep the exam deadline's date in step, keeping whatever time of day it has.
                row = c.execute(
                    "select id, due_at from deadline where course_id = ? and is_course_exam = 1", (course.id,)
                ).fetchone()
                if row:
                    old = datetime.fromisoformat(row["due_at"])
                    c.execute(
                        "update deadline set due_at = ?, title = ? where id = ?",
                        (_iso(datetime.combine(course.exam_date, old.time())), f"{course.code.strip()} exam", row["id"]),
                    )
        except sqlite3.IntegrityError as e:
            raise StorageError(self._integrity_message(e, course.code)) from None
        return course

    @staticmethod
    def _check_course(course: Course) -> None:
        if not course.name.strip() or not course.code.strip():
            raise StorageError("A course needs both a name and a short code.")
        if course.exam_date < course.cram_start:
            raise StorageError("The exam date can't be before the cram start date.")

    @staticmethod
    def _integrity_message(e: sqlite3.IntegrityError, code: str) -> str:
        if "course.code" in str(e):
            return f"There's already a course with the code {code.strip()!r}."
        return f"That change isn't allowed: {e}"

    def delete_course(self, course_id: int) -> None:
        """Deletes the course with all its topics, weak spots, deadlines and sessions."""
        with self._tx() as c:
            c.execute("delete from course where id = ?", (course_id,))

    def get_course(self, course_id: int) -> Course | None:
        r = self.conn.execute("select * from course where id = ?", (course_id,)).fetchone()
        return self._course(r) if r else None

    def list_courses(self) -> list[Course]:
        """Courses in exam order: soonest exam first."""
        return [self._course(r) for r in self.conn.execute("select * from course order by exam_date, code")]

    def find_course(self, ref: str) -> Course:
        """Look a course up by code, name, or an unambiguous prefix of either (case-insensitive)."""
        ref = ref.strip().lower()
        courses = self.list_courses()
        for match in (
            lambda c: c.code.lower() == ref or c.name.lower() == ref,
            lambda c: c.code.lower().startswith(ref) or c.name.lower().startswith(ref),
        ):
            found = [c for c in courses if match(c)]
            if len(found) == 1:
                return found[0]
            if len(found) > 1:
                names = ", ".join(c.code for c in found)
                raise StorageError(f"{ref!r} matches more than one course ({names}). Use the full code.")
        known = ", ".join(c.code for c in courses) or "none yet"
        raise StorageError(f"No course matches {ref!r}. Courses: {known}.")

    # ---------- topics ----------

    @staticmethod
    def _topic(r: sqlite3.Row) -> Topic:
        return Topic(
            id=r["id"], course_id=r["course_id"], title=r["title"], status=TopicStatus(r["status"]),
            confidence=r["confidence"], last_studied=_d(r["last_studied"]),
        )

    def add_topic(self, topic: Topic) -> Topic:
        self._check_topic(topic)
        with self._tx() as c:
            cur = c.execute(
                "insert into topic (course_id, title, status, confidence, last_studied) values (?, ?, ?, ?, ?)",
                (topic.course_id, topic.title.strip(), topic.status.value, topic.confidence, _iso(topic.last_studied)),
            )
            topic.id = cur.lastrowid
        return topic

    def update_topic(self, topic: Topic) -> Topic:
        self._check_topic(topic)
        with self._tx() as c:
            c.execute(
                "update topic set title = ?, status = ?, confidence = ?, last_studied = ? where id = ?",
                (topic.title.strip(), topic.status.value, topic.confidence, _iso(topic.last_studied), topic.id),
            )
        return topic

    @staticmethod
    def _check_topic(topic: Topic) -> None:
        if not topic.title.strip():
            raise StorageError("A topic needs a title.")
        if not 1 <= topic.confidence <= 5:
            raise StorageError("Confidence goes from 1 to 5.")

    def adjust_confidence(self, topic_id: int, delta: int) -> Topic:
        """Nudge confidence up or down, staying within 1–5."""
        with self._tx() as c:
            c.execute(
                "update topic set confidence = max(1, min(5, confidence + ?)) where id = ?", (delta, topic_id)
            )
        return self.get_topic(topic_id)  # type: ignore[return-value]

    def delete_topic(self, topic_id: int) -> None:
        with self._tx() as c:
            c.execute("delete from topic where id = ?", (topic_id,))

    def get_topic(self, topic_id: int) -> Topic | None:
        r = self.conn.execute("select * from topic where id = ?", (topic_id,)).fetchone()
        return self._topic(r) if r else None

    def list_topics(self, course_id: int | None = None) -> list[Topic]:
        if course_id is None:
            rows = self.conn.execute("select * from topic order by course_id, id")
        else:
            rows = self.conn.execute("select * from topic where course_id = ? order by id", (course_id,))
        return [self._topic(r) for r in rows]

    def find_topic(self, course_id: int, ref: str) -> Topic:
        ref = ref.strip().lower()
        topics = self.list_topics(course_id)
        exact = [t for t in topics if t.title.lower() == ref]
        found = exact or [t for t in topics if t.title.lower().startswith(ref)]
        if len(found) == 1:
            return found[0]
        if not found:
            raise StorageError(f"No topic in that course matches {ref!r}.")
        raise StorageError(f"{ref!r} matches more than one topic: {', '.join(t.title for t in found)}.")

    # ---------- weak spots ----------

    @staticmethod
    def _weak(r: sqlite3.Row) -> WeakSpot:
        return WeakSpot(
            id=r["id"], course_id=r["course_id"], topic_id=r["topic_id"], description=r["description"],
            priority=Priority(r["priority"]), created_at=_dt(r["created_at"]), resolved=bool(r["resolved"]),
            resolved_at=_dt(r["resolved_at"]),
        )

    def add_weak_spot(self, weak: WeakSpot) -> WeakSpot:
        if not weak.description.strip():
            raise StorageError("Describe the weak spot in a few words.")
        with self._tx() as c:
            cur = c.execute(
                "insert into weak_spot (course_id, topic_id, description, priority, created_at, resolved, resolved_at)"
                " values (?, ?, ?, ?, ?, ?, ?)",
                (weak.course_id, weak.topic_id, weak.description.strip(), weak.priority.value, _iso(weak.created_at),
                 int(weak.resolved), _iso(weak.resolved_at)),
            )
            weak.id = cur.lastrowid
        return weak

    def update_weak_spot(self, weak: WeakSpot) -> WeakSpot:
        if not weak.description.strip():
            raise StorageError("Describe the weak spot in a few words.")
        with self._tx() as c:
            c.execute(
                "update weak_spot set topic_id = ?, description = ?, priority = ?, resolved = ?, resolved_at = ? where id = ?",
                (weak.topic_id, weak.description.strip(), weak.priority.value, int(weak.resolved),
                 _iso(weak.resolved_at), weak.id),
            )
        return weak

    def toggle_weak_spot(self, weak_id: int, now: datetime | None = None) -> WeakSpot:
        """Resolve an open weak spot, or reopen a resolved one."""
        now = now or datetime.now()
        with self._tx() as c:
            c.execute(
                "update weak_spot set resolved = 1 - resolved,"
                " resolved_at = case when resolved = 0 then ? else null end where id = ?",
                (_iso(now), weak_id),
            )
        return self.get_weak_spot(weak_id)  # type: ignore[return-value]

    def delete_weak_spot(self, weak_id: int) -> None:
        with self._tx() as c:
            c.execute("delete from weak_spot where id = ?", (weak_id,))

    def get_weak_spot(self, weak_id: int) -> WeakSpot | None:
        r = self.conn.execute("select * from weak_spot where id = ?", (weak_id,)).fetchone()
        return self._weak(r) if r else None

    def list_weak_spots(self, course_id: int | None = None, include_resolved: bool = False) -> list[WeakSpot]:
        """Open weak spots first by priority (high first), then oldest first."""
        sql = "select * from weak_spot where 1 = 1"
        args: list[object] = []
        if course_id is not None:
            sql += " and course_id = ?"
            args.append(course_id)
        if not include_resolved:
            sql += " and resolved = 0"
        sql += (" order by resolved, case priority when 'high' then 0 when 'med' then 1 else 2 end, created_at, id")
        return [self._weak(r) for r in self.conn.execute(sql, args)]

    # ---------- deadlines ----------

    @staticmethod
    def _deadline(r: sqlite3.Row) -> Deadline:
        return Deadline(
            id=r["id"], course_id=r["course_id"], title=r["title"], due_at=_dt(r["due_at"]),
            kind=DeadlineKind(r["kind"]), done=bool(r["done"]), is_course_exam=bool(r["is_course_exam"]),
        )

    def add_deadline(self, deadline: Deadline) -> Deadline:
        if not deadline.title.strip():
            raise StorageError("A deadline needs a title.")
        with self._tx() as c:
            cur = c.execute(
                "insert into deadline (course_id, title, due_at, kind, done) values (?, ?, ?, ?, ?)",
                (deadline.course_id, deadline.title.strip(), _iso(deadline.due_at), deadline.kind.value,
                 int(deadline.done)),
            )
            deadline.id = cur.lastrowid
        return deadline

    def update_deadline(self, deadline: Deadline) -> Deadline:
        if not deadline.title.strip():
            raise StorageError("A deadline needs a title.")
        if deadline.is_course_exam and deadline.course_id is not None:
            course = self.get_course(deadline.course_id)
            if course and deadline.due_at.date() < course.cram_start:
                raise StorageError(f"The exam can't be before {course.code}'s cram start "
                                   f"({course.cram_start:%d.%m.%Y}).")
        with self._tx() as c:
            c.execute(
                "update deadline set course_id = ?, title = ?, due_at = ?, kind = ?, done = ? where id = ?",
                (deadline.course_id, deadline.title.strip(), _iso(deadline.due_at), deadline.kind.value,
                 int(deadline.done), deadline.id),
            )
            if deadline.is_course_exam and deadline.course_id is not None:
                # Moving the exam deadline moves the course's exam date with it.
                c.execute("update course set exam_date = ? where id = ?",
                          (_iso(deadline.due_at.date()), deadline.course_id))
        return deadline

    def toggle_deadline(self, deadline_id: int) -> Deadline:
        with self._tx() as c:
            c.execute("update deadline set done = 1 - done where id = ?", (deadline_id,))
        return self.get_deadline(deadline_id)  # type: ignore[return-value]

    def delete_deadline(self, deadline_id: int) -> None:
        r = self.conn.execute("select is_course_exam from deadline where id = ?", (deadline_id,)).fetchone()
        if r and r["is_course_exam"]:
            raise StorageError("A course's exam deadline goes away with the course. Edit or delete the course instead.")
        with self._tx() as c:
            c.execute("delete from deadline where id = ?", (deadline_id,))

    def get_deadline(self, deadline_id: int) -> Deadline | None:
        r = self.conn.execute("select * from deadline where id = ?", (deadline_id,)).fetchone()
        return self._deadline(r) if r else None

    def list_deadlines(self, course_id: int | None = None, include_done: bool = False) -> list[Deadline]:
        """Soonest first. Overdue deadlines that aren't done are included (they sort first)."""
        sql = "select * from deadline where 1 = 1"
        args: list[object] = []
        if course_id is not None:
            sql += " and course_id = ?"
            args.append(course_id)
        if not include_done:
            sql += " and done = 0"
        sql += " order by due_at, id"
        return [self._deadline(r) for r in self.conn.execute(sql, args)]

    # ---------- sessions ----------

    @staticmethod
    def _session(r: sqlite3.Row) -> Session:
        return Session(
            id=r["id"], course_id=r["course_id"], topic_id=r["topic_id"], started_at=_dt(r["started_at"]),
            minutes=r["minutes"], note=r["note"],
        )

    def log_session(self, session: Session) -> Session:
        """Record study time. Also marks the topic as studied that day and moves it to 'in progress'."""
        if session.minutes <= 0:
            raise StorageError("A session needs at least one minute.")
        with self._tx() as c:
            self._insert_session(c, session)
        return session

    @staticmethod
    def _insert_session(c: sqlite3.Connection, session: Session) -> None:
        cur = c.execute(
            "insert into session (course_id, topic_id, started_at, minutes, note) values (?, ?, ?, ?, ?)",
            (session.course_id, session.topic_id, _iso(session.started_at), session.minutes, session.note.strip()),
        )
        session.id = cur.lastrowid
        if session.topic_id is not None:
            c.execute(
                "update topic set last_studied = max(coalesce(last_studied, ''), ?),"
                " status = case status when 'not_started' then 'in_progress' else status end where id = ?",
                (_iso(session.started_at.date()), session.topic_id),
            )

    def update_session(self, session: Session) -> Session:
        if session.minutes <= 0:
            raise StorageError("A session needs at least one minute.")
        with self._tx() as c:
            c.execute(
                "update session set topic_id = ?, started_at = ?, minutes = ?, note = ? where id = ?",
                (session.topic_id, _iso(session.started_at), session.minutes, session.note.strip(), session.id),
            )
        return session

    def get_session(self, session_id: int) -> Session | None:
        r = self.conn.execute("select * from session where id = ?", (session_id,)).fetchone()
        return self._session(r) if r else None

    def delete_session(self, session_id: int) -> None:
        with self._tx() as c:
            c.execute("delete from session where id = ?", (session_id,))

    def list_sessions(
        self, course_id: int | None = None, since: datetime | None = None, until: datetime | None = None,
        limit: int | None = None,
    ) -> list[Session]:
        """Newest first."""
        sql = "select * from session where 1 = 1"
        args: list[object] = []
        if course_id is not None:
            sql += " and course_id = ?"
            args.append(course_id)
        if since is not None:
            sql += " and started_at >= ?"
            args.append(_iso(since))
        if until is not None:
            sql += " and started_at < ?"
            args.append(_iso(until))
        sql += " order by started_at desc, id desc"
        if limit is not None:
            sql += " limit ?"
            args.append(limit)
        return [self._session(r) for r in self.conn.execute(sql, args)]

    def total_minutes(self, course_id: int | None = None) -> int:
        if course_id is None:
            row = self.conn.execute("select coalesce(sum(minutes), 0) from session").fetchone()
        else:
            row = self.conn.execute("select coalesce(sum(minutes), 0) from session where course_id = ?", (course_id,)).fetchone()
        return int(row[0])

    # ---------- the running timer ----------

    def start_timer(self, course_id: int, topic_id: int | None = None, now: datetime | None = None) -> ActiveTimer:
        if self.get_timer() is not None:
            raise StorageError("A study timer is already running. Stop it first.")
        if self.get_pomodoro() is not None:
            raise StorageError("A Pomodoro is running. Stop it before starting a plain timer.")
        timer = ActiveTimer(course_id=course_id, topic_id=topic_id, started_at=(now or datetime.now()).replace(microsecond=0))
        with self._tx() as c:
            c.execute(
                "insert into active_timer (id, course_id, topic_id, started_at) values (1, ?, ?, ?)",
                (course_id, topic_id, timer.started_at.isoformat(timespec="seconds")),
            )
        return timer

    def get_timer(self) -> ActiveTimer | None:
        r = self.conn.execute("select * from active_timer where id = 1").fetchone()
        if not r:
            return None
        return ActiveTimer(course_id=r["course_id"], topic_id=r["topic_id"], started_at=_dt(r["started_at"]))

    def stop_timer(self, now: datetime | None = None, note: str = "") -> Session | None:
        """Stop the running timer and log it. Returns None (and logs nothing) if it ran under a minute."""
        timer = self.get_timer()
        if timer is None:
            raise StorageError("No study timer is running.")
        minutes = round(((now or datetime.now()) - timer.started_at).total_seconds() / 60)
        session = None
        if minutes >= 1:
            session = Session(course_id=timer.course_id, topic_id=timer.topic_id, started_at=timer.started_at,
                              minutes=minutes, note=note)
        # Clearing the timer and logging the session happen together, so neither can be lost.
        with self._tx() as c:
            c.execute("delete from active_timer where id = 1")
            if session is not None:
                self._insert_session(c, session)
        return session

    def cancel_timer(self) -> None:
        with self._tx() as c:
            c.execute("delete from active_timer where id = 1")

    # ---------- Pomodoro ----------
    # Every method settles the run first: focus blocks that have finished since the last look are
    # logged as sessions in the same transaction that saves the run, so a block is logged exactly once.

    def get_pomodoro(self) -> PomodoroRun | None:
        r = self.conn.execute("select * from pomodoro_run where id = 1").fetchone()
        if not r:
            return None
        return PomodoroRun(
            course_id=r["course_id"], topic_id=r["topic_id"], phase=PomoPhase(r["phase"]),
            phase_started_at=_dt(r["phase_started_at"]), block_started_at=_dt(r["block_started_at"]),
            completed=r["completed"], paused_at=_dt(r["paused_at"]), note=r["note"],
        )

    @staticmethod
    def _write_pomodoro(c: sqlite3.Connection, run: PomodoroRun) -> None:
        def ts(value: datetime | None) -> str | None:
            return value.isoformat(timespec="seconds") if value else None

        c.execute(
            "insert or replace into pomodoro_run"
            " (id, course_id, topic_id, phase, phase_started_at, block_started_at, completed, paused_at, note)"
            " values (1, ?, ?, ?, ?, ?, ?, ?, ?)",
            (run.course_id, run.topic_id, run.phase.value, ts(run.phase_started_at), ts(run.block_started_at),
             run.completed, ts(run.paused_at), run.note),
        )

    def _log_blocks(self, c: sqlite3.Connection, run: PomodoroRun, blocks: list[pomo.FinishedBlock]) -> list[Session]:
        sessions = []
        for b in blocks:
            note = f"Pomodoro {b.number}" + (" (stopped early)" if b.partial else "") + (f" · {run.note}" if run.note else "")
            session = Session(course_id=run.course_id, topic_id=run.topic_id, started_at=b.started_at,
                              minutes=b.minutes, note=note)
            self._insert_session(c, session)
            sessions.append(session)
        return sessions

    def start_pomodoro(self, course_id: int, topic_id: int | None = None, now: datetime | None = None,
                       note: str = "") -> PomodoroRun:
        if self.get_pomodoro() is not None:
            raise StorageError("A Pomodoro is already running. Stop it first.")
        if self.get_timer() is not None:
            raise StorageError("A study timer is running. Stop it before starting a Pomodoro.")
        run = pomo.start(course_id, now or datetime.now(), topic_id, note.strip())
        with self._tx() as c:
            self._write_pomodoro(c, run)
        return run

    def _change_pomodoro(self, now: datetime, settings: PomodoroSettings, change=None) -> tuple[PomodoroRun | None, list[Session]]:
        run = self.get_pomodoro()
        if run is None:
            return None, []
        settled, blocks = pomo.advance(run, now, settings)
        if change is not None:
            settled = change(settled)
        if settled == run and not blocks:
            return run, []
        with self._tx() as c:
            # Re-read inside the transaction: another process may have settled this run a moment ago.
            current = self.get_pomodoro()
            if current != run:
                return current, []
            self._write_pomodoro(c, settled)
            sessions = self._log_blocks(c, settled, blocks)
        return settled, sessions

    def settle_pomodoro(self, now: datetime | None = None,
                        settings: PomodoroSettings = PomodoroSettings()) -> tuple[PomodoroRun | None, list[Session]]:
        """Log any focus blocks that have finished. Returns the current run and the sessions just logged."""
        return self._change_pomodoro(now or datetime.now(), settings)

    def pomodoro_next(self, now: datetime | None = None,
                      settings: PomodoroSettings = PomodoroSettings()) -> tuple[PomodoroRun, list[Session]]:
        """Start the next focus block (also skips the rest of a break)."""
        now = now or datetime.now()
        run, sessions = self._change_pomodoro(now, settings, lambda r: pomo.next_focus(r, now))
        if run is None:
            raise StorageError("No Pomodoro is running.")
        return run, sessions

    def pause_pomodoro(self, now: datetime | None = None,
                       settings: PomodoroSettings = PomodoroSettings()) -> tuple[PomodoroRun, list[Session]]:
        now = now or datetime.now()
        run, sessions = self._change_pomodoro(now, settings, lambda r: pomo.pause(r, now))
        if run is None:
            raise StorageError("No Pomodoro is running.")
        return run, sessions

    def resume_pomodoro(self, now: datetime | None = None,
                        settings: PomodoroSettings = PomodoroSettings()) -> tuple[PomodoroRun, list[Session]]:
        now = now or datetime.now()
        run, sessions = self._change_pomodoro(now, settings, lambda r: pomo.resume(r, now))
        if run is None:
            raise StorageError("No Pomodoro is running.")
        return run, sessions

    def stop_pomodoro(self, now: datetime | None = None,
                      settings: PomodoroSettings = PomodoroSettings()) -> list[Session]:
        """End the run, logging finished blocks and the part of a block in progress (a minute or more)."""
        with self._tx() as c:
            # Read inside the transaction so a concurrent settle can't make us log a block twice.
            run = self.get_pomodoro()
            if run is None:
                raise StorageError("No Pomodoro is running.")
            blocks = pomo.stop(run, now or datetime.now(), settings)
            c.execute("delete from pomodoro_run where id = 1")
            return self._log_blocks(c, run, blocks)

    # ---------- settings ----------

    def get_setting(self, key: str, default: str | None = None) -> str | None:
        r = self.conn.execute("select value from setting where key = ?", (key,)).fetchone()
        return r["value"] if r else default

    def set_setting(self, key: str, value: str) -> None:
        with self._tx() as c:
            c.execute("insert into setting (key, value) values (?, ?)"
                      " on conflict (key) do update set value = excluded.value", (key, value))

    # ---------- notifications already sent ----------

    def sent_keys(self) -> set[tuple[int, str, datetime]]:
        """(deadline id, threshold, due_at) for every alert sent so far."""
        return {
            (r["deadline_id"], r["threshold"], datetime.fromisoformat(r["due_at"]))
            for r in self.conn.execute("select deadline_id, threshold, due_at from sent_notification")
        }

    def mark_sent(self, deadline_id: int, thresholds: list[str], due_at: datetime, now: datetime | None = None) -> None:
        now = now or datetime.now()
        with self._tx() as c:
            c.executemany(
                "insert or ignore into sent_notification (deadline_id, threshold, due_at, sent_at) values (?, ?, ?, ?)",
                [(deadline_id, t, _iso(due_at), _iso(now)) for t in thresholds],
            )
