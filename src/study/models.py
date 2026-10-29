"""Plain data types for everything study stores. No I/O here."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from enum import StrEnum


class TopicStatus(StrEnum):
    NOT_STARTED = "not_started"
    IN_PROGRESS = "in_progress"
    REVIEWED = "reviewed"
    CONFIDENT = "confident"

    @property
    def label(self) -> str:
        return self.value.replace("_", " ")

    @property
    def is_done(self) -> bool:
        """Counts toward the 'material done' fill of the cram timeline."""
        return self in (TopicStatus.REVIEWED, TopicStatus.CONFIDENT)


class Priority(StrEnum):
    LOW = "low"
    MED = "med"
    HIGH = "high"

    @property
    def rank(self) -> int:
        """Higher is more urgent."""
        return {"low": 0, "med": 1, "high": 2}[self.value]


class DeadlineKind(StrEnum):
    EXAM = "exam"
    ASSIGNMENT = "assignment"
    MILESTONE = "milestone"


# One accent per course. Mid-tone colours that read on both light and dark terminals.
COURSE_COLORS: tuple[str, ...] = (
    "#5b8def",  # blue
    "#e07a5f",  # coral
    "#3ba99c",  # teal
    "#b07fe0",  # violet
    "#d9a930",  # amber
    "#6fae5a",  # green
    "#e0679a",  # pink
    "#7d8ba3",  # slate
)


@dataclass
class Course:
    name: str
    code: str
    cram_start: date
    exam_date: date
    color: str = COURSE_COLORS[0]
    notes: str = ""
    id: int | None = None


@dataclass
class Topic:
    course_id: int
    title: str
    status: TopicStatus = TopicStatus.NOT_STARTED
    confidence: int = 1
    last_studied: date | None = None
    id: int | None = None


@dataclass
class WeakSpot:
    course_id: int
    description: str
    priority: Priority = Priority.MED
    topic_id: int | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now().replace(second=0, microsecond=0))
    resolved: bool = False
    resolved_at: datetime | None = None
    id: int | None = None


@dataclass
class Deadline:
    title: str
    due_at: datetime
    kind: DeadlineKind = DeadlineKind.ASSIGNMENT
    course_id: int | None = None
    done: bool = False
    # The exam deadline that every course gets automatically; it follows the course's exam date.
    is_course_exam: bool = False
    id: int | None = None


@dataclass
class Session:
    course_id: int
    started_at: datetime
    minutes: int
    topic_id: int | None = None
    note: str = ""
    id: int | None = None


@dataclass
class SentNotification:
    deadline_id: int
    threshold: str
    due_at: datetime
    sent_at: datetime


@dataclass
class ActiveTimer:
    """A study session that has started but not been logged yet. Survives quitting the TUI."""

    course_id: int
    started_at: datetime
    topic_id: int | None = None


@dataclass
class Source:
    """Something to read for a course: a textbook, lecture notes, a paper."""

    course_id: int
    title: str
    author: str = ""
    id: int | None = None


@dataclass
class Chapter:
    source_id: int
    number: str  # "6", "A"
    title: str = ""
    topic_id: int | None = None  # the topic this chapter's sections count toward
    id: int | None = None


@dataclass
class Section:
    chapter_id: int
    number: str  # "6.1"
    title: str = ""
    required: bool = True  # part of what you need to read; optional sections don't count toward progress
    read: bool = False
    read_at: datetime | None = None
    topic_id: int | None = None  # set to link just this section to a different topic than its chapter
    id: int | None = None
