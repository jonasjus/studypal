"""Sample courses for `study --demo`, laid out around today so every part of the UI has something to show."""

from __future__ import annotations

import atexit
import os
import shutil
import tempfile
from datetime import datetime, time, timedelta
from pathlib import Path

from .models import Course, Deadline, DeadlineKind, Priority, Session, Source, Topic, TopicStatus, WeakSpot
from .storage import Store

NS, IP, RV, CF = TopicStatus.NOT_STARTED, TopicStatus.IN_PROGRESS, TopicStatus.REVIEWED, TopicStatus.CONFIDENT

# (code, name, cram start offset, exam offset, [(topic, status, confidence, studied days ago or None)])
COURSES = [
    ("DAT255", "Data Engineering", -25, 2, [
        ("Batch vs stream processing", CF, 5, 3), ("Spark internals", RV, 4, 2), ("Data modelling", RV, 4, 6),
        ("Kafka", IP, 3, 1), ("Orchestration with Airflow", RV, 3, 4), ("Data quality", NS, 1, None),
    ]),
    ("STK310", "Statistical Inference", -10, 24, [
        ("Likelihood", CF, 5, 2), ("Sufficiency", CF, 4, 5), ("Exponential families", RV, 4, 3),
        ("Hypothesis testing", RV, 3, 1), ("Bayesian inference", IP, 2, 0), ("Bootstrap", NS, 1, None),
    ]),
    ("INF301", "Machine Learning", -20, 12, [
        ("Linear models", CF, 5, 9), ("Regularisation", RV, 4, 8), ("Kernels and SVMs", IP, 2, 1),
        ("Trees and boosting", IP, 3, 4), ("Probabilistic models", NS, 1, None), ("Model selection", RV, 3, 11),
        ("Neural networks", NS, 1, None), ("Unsupervised learning", NS, 1, None),
    ]),
    ("INF395", "Deep Learning", 3, 40, [
        ("Backpropagation", IP, 2, 6), ("CNNs", NS, 1, None), ("Transformers", NS, 1, None),
    ]),
]

WEAK = [
    ("INF301", "Kernels and SVMs", "Can't derive the dual form of the SVM without notes", Priority.HIGH, 6),
    ("INF301", "Model selection", "Mixing up when to use nested cross-validation", Priority.MED, 3),
    ("STK310", "Sufficiency", "Factorisation theorem proofs", Priority.HIGH, 2),
    ("DAT255", "Kafka", "Exactly-once semantics", Priority.MED, 8),
    ("STK310", "Bayesian inference", "Conjugate priors beyond beta-binomial", Priority.LOW, 1),
]

# (course code, source title, author, [(chapter, title, topic, sections, read up to, optional sections)])
READING = [
    ("INF301", "Pattern Recognition and Machine Learning", "Bishop", [
        ("3", "Linear Models for Regression", "Linear models", "3.1-3.5", 5, ["3.4"]),
        ("6", "Kernel Methods", "Kernels and SVMs", "6.1-6.4", 2, ["6.4"]),
        ("7", "Sparse Kernel Machines", "Kernels and SVMs", "7.1-7.2", 0, ["7.2"]),
        ("14", "Combining Models", "Trees and boosting", "14.1-14.5", 3, []),
    ]),
    ("INF301", "Lecture notes", "", [
        ("5", "Model selection", "Model selection", "5.1-5.3", 3, []),
    ]),
    ("STK310", "Statistical Inference", "Casella & Berger", [
        ("6", "Principles of Data Reduction", "Sufficiency", "6.1-6.4", 2, ["6.4"]),
        ("7", "Point Estimation", "Likelihood", "7.1-7.3", 3, []),
        ("8", "Hypothesis Testing", "Hypothesis testing", "8.1-8.3", 1, []),
    ]),
]

# (course code or None, title, kind, due offset in hours, done)
DEADLINES = [
    ("INF301", "Problem set 4", DeadlineKind.ASSIGNMENT, 30, False),
    ("STK310", "Mandatory assignment 2", DeadlineKind.ASSIGNMENT, 5 * 24 + 3, False),
    ("DAT255", "Pipeline project report", DeadlineKind.ASSIGNMENT, -20, False),
    ("INF301", "Problem set 3", DeadlineKind.ASSIGNMENT, -6 * 24, True),
    (None, "Thesis outline to supervisor", DeadlineKind.MILESTONE, 15 * 24, False),
]


def seed(store: Store, now: datetime | None = None) -> None:
    now = (now or datetime.now()).replace(second=0, microsecond=0)
    today = now.date()
    topic_ids: dict[tuple[str, str], int] = {}
    started: set[tuple[str, str]] = set()  # sessions go to topics studied in the last week, so older ones stay stale
    courses: dict[str, Course] = {}

    for code, name, start, exam, topics in COURSES:
        course = store.add_course(Course(name, code, today + timedelta(days=start), today + timedelta(days=exam),
                                         color=store.next_color()))
        courses[code] = course
        for title, status, confidence, ago in topics:
            t = store.add_topic(Topic(course.id, title, status, confidence,
                                      today - timedelta(days=ago) if ago is not None else None))
            topic_ids[(code, title)] = t.id
            if ago is not None and ago < 7:
                started.add((code, title))

    for code, topic, text, priority, ago in WEAK:
        store.add_weak_spot(WeakSpot(courses[code].id, text, priority, topic_ids[(code, topic)],
                                     created_at=now - timedelta(days=ago)))

    from .logic.reading import parse_section_ranges

    for code, title, author, chapters in READING:
        source = store.add_source(Source(courses[code].id, title, author))
        for number, chapter_title, topic, ranges, read_up_to, optional in chapters:
            numbers = parse_section_ranges(ranges, number)
            store.add_chapter(source.id, number, chapter_title, numbers, topic_ids[(code, topic)])
            listed = {sec.number: sec for _, chs in store.reading_list(courses[code].id) for _, ss in chs for sec in ss
                      if sec.number in numbers}
            store.set_required([listed[n].id for n in optional], False)
            read = [listed[n].id for n in numbers[:read_up_to] if n not in optional]
            # Ticked directly so the demo topics keep the statuses and study dates chosen above
            # (ticking through the store would count the reading as studying them today).
            for section_id in read:
                store.conn.execute("update section set read = 1, read_at = ? where id = ?",
                                   ((now - timedelta(days=2)).isoformat(timespec="minutes"), section_id))

    for code, title, kind, hours, done in DEADLINES:
        due = (now + timedelta(hours=hours)).replace(minute=0)
        store.add_deadline(Deadline(title, due, kind, courses[code].id if code else None, done))

    # Two weeks of study sessions, heavier on the courses with exams coming up.
    pattern = [("DAT255", 90), ("INF301", 60), ("STK310", 45), ("INF301", 50), ("DAT255", 75), ("STK310", 30)]
    for day in range(14, -1, -1):
        d = today - timedelta(days=day)
        if d.weekday() == 5 and day > 6:  # a Saturday off
            continue
        for i, (code, minutes) in enumerate(pattern[day % 3: day % 3 + 2 + (day % 2)]):
            start = datetime.combine(d, time(9 + 3 * i, 15))
            if start > now:
                continue
            titles = sorted(t for (c, t) in started if c == code)
            topic = titles[(day + i) % len(titles)]
            store.log_session(Session(courses[code].id, start, minutes + (day % 4) * 5, topic_ids[(code, topic)]))


def temporary_store_path() -> Path:
    """A fresh database in a temp folder that's removed when the program exits."""
    folder = Path(tempfile.mkdtemp(prefix="study-demo-"))
    atexit.register(shutil.rmtree, folder, True)
    path = folder / "study.db"
    os.environ["STUDY_DB"] = str(path)
    return path
