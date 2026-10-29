"""Drive the TUI with Textual's pilot: press keys, then check what was saved."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from datetime import date, timedelta

import pytest

from study import config, demo
from study.models import Course, Topic
from study.storage import Store
from study.tui.app import HelpScreen, StudyApp
from study.tui.forms import FormModal
from study.tui.overview import OverviewScreen
from study.tui.subject import SubjectScreen

SIZE = (150, 46)


@pytest.fixture(autouse=True)
def quiet_notifications(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("STUDY_NOTIFIER", "print")


def run(store: Store, script: Callable[[StudyApp, object], Awaitable[None]]) -> None:
    async def main() -> None:
        app = StudyApp(store, config.default_config())
        async with app.run_test(size=SIZE) as pilot:
            await pilot.pause()
            await script(app, pilot)

    asyncio.run(main())


@pytest.fixture
def demo_store(store: Store) -> Store:
    demo.seed(store)
    return store


async def type_and_enter(pilot, text: str) -> None:
    await pilot.press(*list(text))
    await pilot.press("enter")
    await pilot.pause()


def test_overview_lists_courses_in_exam_order(demo_store: Store) -> None:
    async def script(app, pilot):
        assert isinstance(app.screen, OverviewScreen)
        assert [s.course.code for s in app.screen.dash.courses] == ["DAT255", "INF301", "STK310", "INF395"]
        assert app.screen.current_course_id() == demo_store.find_course("DAT255").id

    run(demo_store, script)


def test_enter_and_number_keys_open_subjects(demo_store: Store) -> None:
    async def script(app, pilot):
        await pilot.press("j", "enter")
        await pilot.pause()
        assert isinstance(app.screen, SubjectScreen) and app.screen.course_id == demo_store.find_course("INF301").id
        await pilot.press("right_square_bracket")
        await pilot.pause()
        assert app.screen.course_id == demo_store.find_course("STK310").id
        await pilot.press("escape", "4")
        await pilot.pause()
        assert app.screen.course_id == demo_store.find_course("INF395").id

    run(demo_store, script)


def test_deadline_pane_keys_act_on_that_deadlines_course(demo_store: Store) -> None:
    async def script(app, pilot):
        await pilot.press("tab")  # Upcoming deadlines; first row is the overdue DAT255 report
        await pilot.pause()
        deadline = app.screen.focused.current
        assert app.screen.current_course_id() == deadline.course_id
        await pilot.press("space")
        await pilot.pause()
        assert demo_store.get_deadline(deadline.id).done
        # Done deadlines leave the list, so the highlight is now on the next one.
        highlighted = app.screen.focused.current
        assert highlighted.id != deadline.id
        await pilot.press("enter")
        await pilot.pause()
        assert isinstance(app.screen, SubjectScreen)
        assert app.screen.course_id == highlighted.course_id  # opened that deadline's course

    run(demo_store, script)


def test_quick_log_from_the_overview(demo_store: Store) -> None:
    inf = demo_store.find_course("INF301")
    before = demo_store.total_minutes(inf.id)

    async def script(app, pilot):
        await pilot.press("j", "l")
        await pilot.pause()
        assert isinstance(app.screen, FormModal)
        await type_and_enter(pilot, "1h15m")
        assert demo_store.total_minutes(inf.id) == before + 75

    run(demo_store, script)


def test_form_shows_errors_and_esc_cancels(demo_store: Store) -> None:
    before = demo_store.total_minutes()

    async def script(app, pilot):
        await pilot.press("l")
        await type_and_enter(pilot, "soon")
        assert isinstance(app.screen, FormModal)
        assert "Use minutes" in str(app.screen.query_one("#form-error").render())
        await pilot.press("escape")
        await pilot.pause()
        assert isinstance(app.screen, OverviewScreen)

    run(demo_store, script)
    assert demo_store.total_minutes() == before


def test_weak_spot_from_the_overview_goes_to_the_highlighted_course(demo_store: Store) -> None:
    stk = demo_store.find_course("STK310")

    async def script(app, pilot):
        await pilot.press("j", "j", "w")  # third subject
        await pilot.pause()
        await type_and_enter(pilot, "Rao-Blackwell")
        assert any(w.description == "Rao-Blackwell" for w in demo_store.list_weak_spots(stk.id))

    run(demo_store, script)


def test_timer_starts_and_stops_on_the_current_course(demo_store: Store) -> None:
    async def script(app, pilot):
        await pilot.press("j", "s")
        await pilot.pause()
        timer = demo_store.get_timer()
        assert timer is not None and timer.course_id == demo_store.find_course("INF301").id
        await pilot.press("s")
        await pilot.pause()
        assert demo_store.get_timer() is None  # under a minute: stopped without logging

    run(demo_store, script)


def test_pomodoro_on_a_highlighted_topic(demo_store: Store) -> None:
    async def script(app, pilot):
        await pilot.press("2")  # INF301
        await pilot.pause()
        await pilot.press("j", "p")
        await pilot.pause()
        run_ = demo_store.get_pomodoro()
        assert run_ is not None and run_.topic_id == demo_store.list_topics(run_.course_id)[1].id
        await pilot.press("p")
        await pilot.pause()
        assert demo_store.get_pomodoro().paused
        await pilot.press("P")
        await pilot.pause()
        assert demo_store.get_pomodoro() is None

    run(demo_store, script)


def test_add_course_and_topic_from_an_empty_start(store: Store) -> None:
    async def script(app, pilot):
        await pilot.press("a")
        await pilot.pause()
        for value in ("Machine Learning", "INF301"):
            await pilot.press(*list(value))
            await pilot.press("tab")
        await pilot.press("tab")  # keep "today" for cram start
        await type_and_enter(pilot, "+30d")
        [course] = store.list_courses()
        assert course.code == "INF301" and course.exam_date == date.today() + timedelta(days=30)
        await pilot.press("t")
        await type_and_enter(pilot, "Kernels")
        assert [t.title for t in store.list_topics(course.id)] == ["Kernels"]

    run(store, script)


def test_subject_add_is_context_aware(store: Store) -> None:
    course = store.add_course(Course("Statistics", "ST", date.today() - timedelta(days=5), date.today() + timedelta(days=20)))
    store.add_topic(Topic(course.id, "Likelihood"))

    async def script(app, pilot):
        await pilot.press("enter")
        await pilot.pause()
        await pilot.press("a")
        await type_and_enter(pilot, "Sufficiency")
        await pilot.press("tab", "a")  # weak spots pane
        await pilot.pause()
        await type_and_enter(pilot, "Factorisation theorem")
        await pilot.press("tab", "a")  # deadlines pane
        await pilot.pause()
        await pilot.press(*list("Mandatory 1"), "tab", *list("+3d"), "enter")
        await pilot.pause()

    run(store, script)
    assert [t.title for t in store.list_topics(course.id)] == ["Likelihood", "Sufficiency"]
    assert [w.description for w in store.list_weak_spots(course.id)] == ["Factorisation theorem"]
    assert "Mandatory 1" in [d.title for d in store.list_deadlines(course.id)]


def test_help_opens_and_closes(store: Store) -> None:
    async def script(app, pilot):
        await pilot.press("question_mark")
        await pilot.pause()
        assert isinstance(app.screen, HelpScreen)
        await pilot.press("escape")
        await pilot.pause()
        assert isinstance(app.screen, OverviewScreen)

    run(store, script)


# ---------- stage 4: editing, deleting, filtering, themes ----------

def test_confidence_and_status_keys_on_topics(store: Store) -> None:
    course = store.add_course(Course("Statistics", "ST", date.today() - timedelta(days=5), date.today() + timedelta(days=20)))
    topic = store.add_topic(Topic(course.id, "Likelihood", confidence=3))

    async def script(app, pilot):
        await pilot.press("enter")
        await pilot.pause()
        await pilot.press("plus", "plus", "plus")  # stops at 5
        await pilot.pause()
        assert store.get_topic(topic.id).confidence == 5
        await pilot.press("minus")
        await pilot.press("space", "space")  # not started -> in progress -> reviewed
        await pilot.pause()

    run(store, script)
    t = store.get_topic(topic.id)
    assert t.confidence == 4 and t.status.value == "reviewed"


def test_edit_topic_form_saves_changes(store: Store) -> None:
    course = store.add_course(Course("Statistics", "ST", date.today() - timedelta(days=5), date.today() + timedelta(days=20)))
    topic = store.add_topic(Topic(course.id, "Likelyhood"))

    async def script(app, pilot):
        await pilot.press("enter")
        await pilot.pause()
        await pilot.press("e")
        await pilot.pause()
        assert isinstance(app.screen, FormModal)
        await pilot.press(*list("Likelihood"), "enter")  # the title starts selected, so typing replaces it
        await pilot.pause()

    run(store, script)
    assert store.get_topic(topic.id).title == "Likelihood"


def test_editing_the_course_moves_its_exam_deadline(store: Store) -> None:
    course = store.add_course(Course("Statistics", "ST", date.today() - timedelta(days=5), date.today() + timedelta(days=20)))
    new_exam = date.today() + timedelta(days=25)

    async def script(app, pilot):
        await pilot.press("e")  # highlighted subject
        await pilot.pause()
        assert isinstance(app.screen, FormModal)
        exam = app.screen.query_one("#f-exam")
        exam.value = new_exam.isoformat()
        await pilot.click("#f-exam")
        await pilot.press("enter")
        await pilot.pause()

    run(store, script)
    assert store.get_course(course.id).exam_date == new_exam
    exam = next(d for d in store.list_deadlines() if d.is_course_exam)
    assert exam.due_at.date() == new_exam


def test_delete_asks_first_and_n_keeps_it(demo_store: Store) -> None:
    before = len(demo_store.list_courses())

    async def script(app, pilot):
        await pilot.press("d")
        await pilot.pause()
        assert "Delete DAT255" in str(app.screen.query_one("#form-title").render())
        await pilot.press("n")
        await pilot.pause()
        assert len(demo_store.list_courses()) == before
        await pilot.press("d", "y")
        await pilot.pause()

    run(demo_store, script)
    assert [c.code for c in demo_store.list_courses()] == ["INF301", "STK310", "INF395"]


def test_course_exam_deadline_cannot_be_deleted_from_the_tui(demo_store: Store) -> None:
    async def script(app, pilot):
        await pilot.press("tab")
        lv = app.screen.focused
        exam_index = next(i for i, row in enumerate(lv.children) if getattr(row.data, "is_course_exam", False))
        lv.index = exam_index
        await pilot.press("d")
        await pilot.pause()
        assert isinstance(app.screen, OverviewScreen)  # no confirmation; a warning instead

    run(demo_store, script)
    assert len([d for d in demo_store.list_deadlines() if d.is_course_exam]) == 4


def test_filter_narrows_lists_and_esc_clears_it(demo_store: Store) -> None:
    async def script(app, pilot):
        await pilot.press("slash", *list("stk"))
        await pilot.pause()
        courses = app.screen.query_one("#courses")
        assert [row.data for row in courses.children] == [demo_store.find_course("STK310").id]
        deadlines = app.screen.query_one("#deadlines")
        assert all(row.data.course_id == demo_store.find_course("STK310").id for row in deadlines.children)
        await pilot.press("enter", "escape")
        await pilot.pause()
        assert len(app.screen.query_one("#courses").children) == 4

    run(demo_store, script)


def test_delete_a_session_from_the_subject_screen(demo_store: Store) -> None:
    inf = demo_store.find_course("INF301")
    newest = demo_store.list_sessions(inf.id, limit=1)[0]

    async def script(app, pilot):
        await pilot.press("2")
        await pilot.pause()
        app.screen.query_one("#sessions").focus()
        await pilot.press("d", "y")
        await pilot.pause()

    run(demo_store, script)
    assert newest.id not in [s.id for s in demo_store.list_sessions(inf.id)]


def test_theme_picker_previews_saves_and_cancels(store: Store) -> None:
    from study import themes

    async def script(app, pilot):
        await pilot.press("T", "j")  # Gruvbox dark is second
        await pilot.pause()
        assert app.theme == "gruvbox"  # previewed
        await pilot.press("enter")
        await pilot.pause()
        assert store.get_setting("theme") == "gruvbox"
        await pilot.press("T", "j", "j")
        await pilot.pause()
        assert app.theme == "nord"
        await pilot.press("escape")  # put the old one back
        await pilot.pause()
        assert app.theme == "gruvbox" and themes.active().name == "gruvbox"

    run(store, script)
    assert store.get_setting("theme") == "gruvbox"
    themes.set_active(themes.DEFAULT)


def test_saved_theme_is_used_on_start(store: Store) -> None:
    from study import themes

    store.set_setting("theme", "gruvbox-light")

    async def script(app, pilot):
        assert app.theme == "gruvbox-light" and themes.active().name == "gruvbox-light"

    run(store, script)
    themes.set_active(themes.DEFAULT)


# ---------- stage 5: in-app deadline warnings ----------

def test_banner_shows_overdue_and_due_within_a_day(store: Store) -> None:
    from datetime import datetime

    from study.models import Deadline

    now = datetime.now()
    store.add_deadline(Deadline("Old report", now - timedelta(hours=3)))
    store.add_deadline(Deadline("Problem set", now + timedelta(hours=5)))

    async def script(app, pilot):
        await pilot.pause()
        banner = app.screen.query_one("#banner")
        text = str(banner.render())
        assert banner.display and "1 overdue: Old report" in text and "Due within 24 hours: Problem set" in text

    run(store, script)


def test_no_banner_when_nothing_is_urgent(store: Store) -> None:
    async def script(app, pilot):
        await pilot.pause()
        assert not app.screen.query_one("#banner").display

    run(store, script)


def test_toasts_on_launch_then_only_for_new_deadlines(store: Store) -> None:
    from datetime import datetime

    from study.models import Deadline

    now = datetime.now()
    store.add_deadline(Deadline("Problem set", now + timedelta(hours=30)))
    store.add_deadline(Deadline("Far away", now + timedelta(days=9)))

    async def script(app, pilot):
        await pilot.pause()
        [launch] = list(app._notifications)
        assert launch.title == "Coming up" and "Problem set" in launch.message and "Far away" not in launch.message
        app.every_minute()
        await pilot.pause()  # notify() posts a message; the toast exists once it's handled
        assert len(app._notifications) == 1  # nothing new, no new toast
        store.add_deadline(Deadline("Peer review", datetime.now() + timedelta(hours=10)))
        app.every_minute()
        await pilot.pause()
        latest = list(app._notifications)[-1]
        assert latest.title == "Deadline getting close" and "Peer review" in latest.message
        assert "Problem set" not in latest.message and latest.severity == "error"

    run(store, script)


# ---------- reading list ----------

def _reading_store(store: Store):
    from study.models import Source

    course = store.add_course(Course("Machine Learning", "INF301", date.today() - timedelta(days=5),
                                     date.today() + timedelta(days=20)))
    kernels = store.add_topic(Topic(course.id, "Kernels"))
    store.add_topic(Topic(course.id, "Trees"))
    source = store.add_source(Source(course.id, "Bishop"))
    store.add_chapter(source.id, "6", "Kernel methods", ["6.1", "6.2", "6.3"], topic_id=kernels.id)
    return course, kernels, source


def test_r_on_a_topic_opens_the_reading_list_at_its_chapter(store: Store) -> None:
    from study.models import Chapter
    from study.tui.reading import ReadingScreen

    course, kernels, _ = _reading_store(store)

    async def script(app, pilot):
        await pilot.press("enter")  # the course
        await pilot.pause()
        await pilot.press("r")  # Kernels is highlighted
        await pilot.pause()
        assert isinstance(app.screen, ReadingScreen)
        current = app.screen.query_one("#reading").current
        assert isinstance(current, Chapter) and current.topic_id == kernels.id

    run(store, script)


def test_ticking_sections_and_whole_chapters(store: Store) -> None:
    from study.tui.reading import ReadingScreen

    course, kernels, _ = _reading_store(store)

    async def script(app, pilot):
        app.push_screen(ReadingScreen(course.id))
        await pilot.pause()
        lv = app.screen.query_one("#reading")
        lv.index = 2  # source, chapter 6, then 6.1
        await pilot.press("space")
        await pilot.pause()
        assert store.reading_progress(course.id).read == 1
        await pilot.press("j", "o")  # 6.2 becomes optional
        await pilot.pause()
        lv.index = 1  # chapter row
        await pilot.press("space")  # every needed section
        await pilot.pause()
        p = store.reading_progress(course.id)
        assert (p.read, p.required, p.optional) == (2, 2, 1)
        assert store.get_topic(kernels.id).status.value == "in_progress"  # all its needed reading done

    run(store, script)


def test_add_sections_by_range_and_paste_contents(store: Store) -> None:
    from study.tui.reading import ReadingScreen, TocModal

    course, _, _ = _reading_store(store)

    async def script(app, pilot):
        app.push_screen(ReadingScreen(course.id))
        await pilot.pause()
        await pilot.press("a")
        await pilot.pause()
        app.screen.query_one("#f-number").value = "7"
        app.screen.query_one("#f-sections").value = "1-3"
        app.screen.query_one("#f-sections").focus()
        await pilot.press("enter")
        await pilot.pause()
        await pilot.press("i")
        await pilot.pause()
        assert isinstance(app.screen, TocModal)
        app.screen.query_one("#toc-text").text = "14 Combining Models\n14.1 Bayesian model averaging ...... 654\n14.2 Committees  655\n"
        await pilot.press("ctrl+s")
        await pilot.pause()

    run(store, script)
    numbers = [s.number for _, chs in store.reading_list(course.id) for _, ss in chs for s in ss]
    assert numbers == ["6.1", "6.2", "6.3", "7.1", "7.2", "7.3", "14.1", "14.2"]
    chapter14 = store.reading_list(course.id)[0][1][2][0]
    assert chapter14.title == "Combining Models"


def test_link_a_chapter_to_a_topic_and_fold_it(store: Store) -> None:
    from study.tui.reading import ReadingScreen

    course, kernels, _ = _reading_store(store)
    trees = store.find_topic(course.id, "Trees")

    async def script(app, pilot):
        app.push_screen(ReadingScreen(course.id))
        await pilot.pause()
        lv = app.screen.query_one("#reading")
        lv.index = 1
        await pilot.press("t")
        await pilot.pause()
        app.screen.query_one("#f-topic").value = trees.id
        app.screen.submit()
        await pilot.pause()
        assert len(app.screen.query_one("#reading").children) == 5  # source, chapter, 3 sections
        app.screen.query_one("#reading").index = 1
        await pilot.press("enter")  # fold the chapter
        await pilot.pause()
        assert len(app.screen.query_one("#reading").children) == 2

    run(store, script)
    assert store.reading_by_topic(course.id).keys() == {trees.id}


# ---------- git sync ----------

def test_pull_on_start_and_sync_key(tmp_path, store: Store) -> None:
    import subprocess

    from study import sync

    remote = tmp_path / "remote.git"
    subprocess.run(["git", "init", "--quiet", "--bare", "-b", "main", str(remote)], check=True)
    course = store.add_course(Course("Machine Learning", "INF301", date.today(), date.today() + timedelta(days=20)))
    sync.init(store, str(remote))  # this device; its repo sits next to its database

    other = Store(tmp_path / "other" / "study.db")
    sync.init(other, str(remote))
    other.add_topic(Topic(other.list_courses()[0].id, "Added on the other device"))
    sync.sync(other)

    async def script(app, pilot):
        for _ in range(100):  # the pull on start runs in a thread
            await pilot.pause(0.05)
            if store.list_topics(course.id):
                break
        assert [t.title for t in store.list_topics(course.id)] == ["Added on the other device"]
        store.add_topic(Topic(course.id, "Added here"))
        await pilot.press("G")
        for _ in range(100):
            await pilot.pause(0.05)
            if not app.workers or all(w.is_finished for w in app.workers):
                break

    run(store, script)
    sync.sync(other)
    assert sorted(t.title for t in other.list_topics()) == ["Added here", "Added on the other device"]
    other.close()


def test_sync_key_without_setup_explains(store: Store) -> None:
    async def script(app, pilot):
        await pilot.press("G")
        await pilot.pause()
        assert any("study sync --init" in n.message for n in app._notifications)

    run(store, script)
