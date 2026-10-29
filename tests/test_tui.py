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
