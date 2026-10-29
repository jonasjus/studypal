"""Two devices syncing through a bare git repo standing in for GitHub."""

from __future__ import annotations

import subprocess
import time
from datetime import date, datetime, timedelta
from pathlib import Path

import pytest

from study import sync
from study.logic.merge import merge3
from study.models import Chapter, Course, Deadline, Session, Source, Topic
from study.storage import Store


class Device:
    def __init__(self, root: Path, name: str) -> None:
        self.store = Store(root / name / "study.db")
        self.repo = root / name / "sync"

    def init(self, url: str | None) -> sync.SyncResult:
        return sync.init(self.store, url, repo=self.repo)

    def sync(self, push: bool = True) -> sync.SyncResult:
        return sync.sync(self.store, push=push, repo=self.repo)

    def git(self, *args: str) -> str:
        return subprocess.run(["git", *args], cwd=self.repo, capture_output=True, text=True, check=True).stdout


@pytest.fixture
def remote(tmp_path: Path) -> str:
    path = tmp_path / "remote.git"
    subprocess.run(["git", "init", "--quiet", "--bare", "-b", "main", str(path)], check=True)
    return str(path)


@pytest.fixture
def laptop(tmp_path: Path) -> Device:
    return Device(tmp_path, "laptop")


@pytest.fixture
def desktop(tmp_path: Path) -> Device:
    return Device(tmp_path, "desktop")


def course(store: Store, code: str = "INF301") -> Course:
    return store.add_course(Course("Machine Learning", code, date(2026, 11, 1), date(2026, 12, 10)))


def codes(store: Store) -> list[str]:
    return sorted(c.code for c in store.list_courses())


def tick() -> None:
    time.sleep(0.01)  # updated_at has millisecond resolution


def test_second_device_gets_everything(remote: str, laptop: Device, desktop: Device) -> None:
    c = course(laptop.store)
    t = laptop.store.add_topic(Topic(c.id, "Kernels"))
    src = laptop.store.add_source(Source(c.id, "Bishop"))
    laptop.store.add_chapter(src.id, "6", "Kernel methods", ["6.1", "6.2"], topic_id=t.id)
    laptop.store.log_session(Session(c.id, datetime(2026, 11, 5, 9, 0), 45, t.id))
    first = laptop.init(remote)
    assert first.pushed

    result = desktop.init(remote)
    assert result.pulled >= 1
    assert codes(desktop.store) == ["INF301"]
    [dc] = desktop.store.list_courses()
    assert [x.title for x in desktop.store.list_topics(dc.id)] == ["Kernels"]
    assert desktop.store.reading_by_topic(dc.id)  # links survive by uid
    assert desktop.store.total_minutes() == 45
    assert len(desktop.store.list_deadlines()) == 1  # the exam deadline came along, not duplicated


def test_edits_to_different_things_merge(remote: str, laptop: Device, desktop: Device) -> None:
    c = course(laptop.store)
    laptop.init(remote)
    desktop.init(remote)

    c.notes = "Exam is oral"
    laptop.store.update_course(c)
    dc = desktop.store.list_courses()[0]
    desktop.store.add_topic(Topic(dc.id, "Trees"))

    laptop.sync()
    result = desktop.sync()  # desktop has to merge: both changed since the last shared version
    assert result.pulled == 1 and result.pushed  # the laptop's note
    laptop.sync()
    for device in (laptop, desktop):
        [cc] = device.store.list_courses()
        assert cc.notes == "Exam is oral"
        assert [t.title for t in device.store.list_topics(cc.id)] == ["Trees"]


def test_same_thing_changed_on_both_newer_wins(remote: str, laptop: Device, desktop: Device) -> None:
    c = course(laptop.store)
    laptop.init(remote)
    desktop.init(remote)
    c.notes = "laptop"
    laptop.store.update_course(c)
    tick()
    dc = desktop.store.list_courses()[0]
    dc.notes = "desktop, later"
    desktop.store.update_course(dc)

    laptop.sync()
    result = desktop.sync()
    assert result.report.both_changed == 1
    laptop.sync()
    assert laptop.store.list_courses()[0].notes == desktop.store.list_courses()[0].notes == "desktop, later"


def test_deleted_here_edited_there_keeps_the_edit(remote: str, laptop: Device, desktop: Device) -> None:
    c = course(laptop.store)
    laptop.store.add_topic(Topic(c.id, "Kernels"))
    laptop.init(remote)
    desktop.init(remote)

    laptop.store.delete_topic(laptop.store.list_topics()[0].id)
    t = desktop.store.list_topics()[0]
    t.confidence = 4
    desktop.store.update_topic(t)

    laptop.sync()
    desktop.sync()
    laptop.sync()
    assert [x.confidence for x in laptop.store.list_topics()] == [4]


def test_course_deleted_while_other_device_added_to_it_comes_back(remote: str, laptop: Device, desktop: Device) -> None:
    course(laptop.store)
    laptop.init(remote)
    desktop.init(remote)
    laptop.store.delete_course(laptop.store.list_courses()[0].id)
    dc = desktop.store.list_courses()[0]
    desktop.store.add_topic(Topic(dc.id, "Added on the desktop"))

    laptop.sync()
    result = desktop.sync()
    assert result.report.restored >= 1
    laptop.sync()
    assert codes(laptop.store) == ["INF301"]
    assert [t.title for t in laptop.store.list_topics()] == ["Added on the desktop"]


def test_two_devices_with_their_own_data_join_up(remote: str, laptop: Device, desktop: Device) -> None:
    course(laptop.store, "INF301")
    course(desktop.store, "INF301")  # set up separately before syncing: same code, different course
    course(desktop.store, "STK310")
    laptop.init(remote)
    result = desktop.init(remote)  # unrelated histories, merged
    laptop.sync()
    assert result.report.renamed == ["INF301-2"]
    assert codes(laptop.store) == codes(desktop.store) == ["INF301", "INF301-2", "STK310"]


def test_same_chapter_added_on_both_is_combined(remote: str, laptop: Device, desktop: Device) -> None:
    c = course(laptop.store)
    laptop.store.add_source(Source(c.id, "Bishop"))
    laptop.init(remote)
    desktop.init(remote)
    src_l = laptop.store.list_sources(c.id)[0]
    laptop.store.add_chapter(src_l.id, "6", "Kernel methods", ["6.1", "6.2"])
    laptop.store.mark_read(c.id, ["6.1"])
    dc = desktop.store.list_courses()[0]
    src_d = desktop.store.list_sources(dc.id)[0]
    desktop.store.add_chapter(src_d.id, "6", "", ["6.1", "6.3"])

    laptop.sync()
    desktop.sync()
    laptop.sync()
    for device in (laptop, desktop):
        [(_, chapters)] = device.store.reading_list(device.store.list_courses()[0].id)
        [(chapter, sections)] = chapters
        assert [s.number for s in sections] == ["6.1", "6.2", "6.3"]
        assert [s.number for s in sections if s.read] == ["6.1"]  # the read copy of 6.1 won


def test_running_timer_and_ids_survive_a_sync(remote: str, laptop: Device, desktop: Device) -> None:
    c = course(laptop.store)
    laptop.init(remote)
    laptop.store.start_timer(c.id)
    desktop.init(remote)
    desktop.store.add_topic(Topic(desktop.store.list_courses()[0].id, "Trees"))
    desktop.sync()
    laptop.sync()
    assert laptop.store.get_timer().course_id == c.id
    assert laptop.store.list_courses()[0].id == c.id


def test_sent_alerts_are_shared(remote: str, laptop: Device, desktop: Device) -> None:
    c = course(laptop.store)
    d = laptop.store.add_deadline(Deadline("Problem set", datetime(2026, 11, 20, 23, 59), course_id=c.id))
    laptop.store.mark_sent(d.id, ["7d"], d.due_at)
    laptop.init(remote)
    desktop.init(remote)
    [dd] = [x for x in desktop.store.list_deadlines() if x.title == "Problem set"]
    assert (dd.id, "7d", dd.due_at) in desktop.store.sent_keys()  # the desktop won't send it again


def test_offline_still_commits_locally(tmp_path: Path, laptop: Device) -> None:
    course(laptop.store)
    result = laptop.init(str(tmp_path / "does-not-exist.git"))
    assert result.offline and result.committed and not result.pushed
    assert "changes" in laptop.git("log", "--oneline")


def test_history_keeps_both_devices_commits(remote: str, laptop: Device, desktop: Device) -> None:
    c = course(laptop.store)
    laptop.init(remote)
    desktop.init(remote)
    c.notes = "x"
    laptop.store.update_course(c)
    desktop.store.add_topic(Topic(desktop.store.list_courses()[0].id, "Trees"))
    laptop.sync()
    desktop.sync()
    log = desktop.git("log", "--oneline")
    assert "merge on" in log and log.count("changes on") >= 3


def test_status(remote: str, laptop: Device) -> None:
    assert not sync.status(laptop.store, repo=laptop.repo).set_up
    c = course(laptop.store)
    laptop.init(remote)
    st = sync.status(laptop.store, repo=laptop.repo)
    assert st.set_up and st.remote == remote and not st.unsynced_local and st.ahead == 0
    c.notes = "changed"
    laptop.store.update_course(c)
    assert sync.status(laptop.store, repo=laptop.repo).unsynced_local


def test_sync_without_setup_explains(laptop: Device) -> None:
    with pytest.raises(sync.SyncError, match="study sync --init"):
        laptop.sync()


def test_merge3_rules() -> None:
    base = {"course": {"a": {"uid": "a", "updated": "1", "code": "A"}}}
    ours = {"course": {"a": {"uid": "a", "updated": "2", "code": "A2"}}}
    theirs = {"course": {"a": {"uid": "a", "updated": "1", "code": "A"}, "b": {"uid": "b", "updated": "1", "code": "B"}}}
    merged, report = merge3(base, ours, theirs)
    assert {u: r["code"] for u, r in merged["course"].items()} == {"a": "A2", "b": "B"}
    assert report.both_changed == 0
    # A deletion on one side with no edit on the other wins.
    merged, _ = merge3(base, {"course": {}}, base)
    assert merged["course"] == {}


def test_git_errors_say_what_went_wrong() -> None:
    denied = ("git@github.com: Permission denied (publickey).\nfatal: Could not read from remote repository.\n\n"
              "Please make sure you have the correct access rights\nand the repository exists.\n")
    text = sync.explain(denied)
    assert text.startswith("Permission denied (publickey). Could not read from remote repository")
    assert "core.sshCommand" in text and "and the repository exists" not in text
    missing = "ERROR: Repository not found.\nfatal: Could not read from remote repository.\n"
    assert sync.explain(missing).startswith("Repository not found. Could not read from remote repository. Check the URL")
