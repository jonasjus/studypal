from __future__ import annotations

import csv
from pathlib import Path

import pytest
from typer.testing import CliRunner

from study.cli import app
from study.storage import Store

runner = CliRunner()


@pytest.fixture(autouse=True)
def isolated(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    db = tmp_path / "study.db"
    monkeypatch.setenv("STUDY_DB", str(db))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "cfg"))
    monkeypatch.setenv("STUDY_NOTIFIER", "print")
    monkeypatch.setenv("COLUMNS", "120")
    return db


def study(*args: str, ok: bool = True) -> str:
    result = runner.invoke(app, list(args))
    if ok:
        assert result.exit_code == 0, result.output
    else:
        assert result.exit_code != 0, result.output
    return result.output


@pytest.fixture
def course() -> None:
    study("add", "course", "Machine Learning", "INF301", "--exam", "+20d", "--cram-start", "-10d")
    study("add", "topic", "inf", "Kernels and SVMs")


def test_add_and_log_round_trip(isolated: Path, course: None) -> None:
    out = study("log", "INF301", "1h30m", "--topic", "kernels", "--note", "Bishop ch. 7")
    assert "Logged 1h 30m on INF301 · Kernels and SVMs" in out
    with Store(isolated) as s:
        [session] = s.list_sessions()
        assert (session.minutes, session.note) == (90, "Bishop ch. 7")
        assert s.list_topics()[0].last_studied is not None


def test_weak_spot_shortcut_and_priorities(isolated: Path, course: None) -> None:
    assert "high-priority" in study("weak", "inf", "Dual form derivation", "--priority", "high")
    assert "med-priority" in study("add", "weak", "inf", "Margins", "-p", "medium")
    with Store(isolated) as s:
        assert [w.description for w in s.list_weak_spots()] == ["Dual form derivation", "Margins"]


def test_status_and_due(course: None) -> None:
    study("add", "deadline", "Problem set 4", "+1d 14:00", "--course", "inf")
    out = study("status")
    assert "INF301" in out and "Machine Learning" in out and "% done" in out and "this week" in out
    out = study("due")
    assert "Problem set 4" in out and "INF301 exam" in out
    assert "INF301 exam" not in study("due", "--within", "5")


def test_errors_are_messages_not_tracebacks(course: None) -> None:
    out = study("log", "bio", "30", ok=False)
    assert "No course matches 'bio'" in out and "Traceback" not in out
    assert "Can't read 'soon'" in study("log", "inf", "soon", ok=False)
    assert "already a course" in study("add", "course", "X", "inf301", "-e", "+3d", ok=False)
    assert "isn't a status" in study("add", "topic", "inf", "X", "--status", "done", ok=False)
    assert "isn't a colour" in study("add", "course", "Y", "Y1", "-e", "+3d", "--color", "red", ok=False)


def test_bad_config_is_reported(isolated: Path) -> None:
    cfg = isolated.parent / "cfg" / "study"
    cfg.mkdir(parents=True)
    (cfg / "config.toml").write_text('[study]\nweek_start = "funday"\n')
    assert "isn't a weekday" in study("status", ok=False)


def test_notify_sends_once(course: None) -> None:
    study("add", "deadline", "Problem set 4", "+1d 14:00", "--course", "inf")
    assert "Would send: INF301: Problem set 4" in study("notify", "--dry-run")
    first = study("notify")
    assert "[notification] INF301: Problem set 4 is due tomorrow" in first
    assert study("notify") == ""  # already sent: nothing, and silent for cron


def test_export_markdown_and_csv(tmp_path: Path, course: None) -> None:
    study("log", "inf", "45", "-t", "kernels")
    md = study("export")
    assert md.startswith("# Study export") and "## INF301 · Machine Learning" in md and "| Kernels and SVMs |" in md
    out_dir = tmp_path / "csv"
    study("export", "--format", "csv", "--output", str(out_dir))
    assert sorted(p.name for p in out_dir.iterdir()) == [
        "courses.csv", "deadlines.csv", "reading.csv", "sessions.csv", "topics.csv", "weak_spots.csv"]
    rows = list(csv.DictReader((out_dir / "sessions.csv").open()))
    assert rows[0]["minutes"] == "45"
    assert "isn't a format" in study("export", "-f", "pdf", ok=False)


def test_pomodoro_commands(isolated: Path, course: None) -> None:
    assert "No Pomodoro running" in study("pomo")
    assert "25 minutes of focus" in study("pomo", "start", "inf", "-t", "kernels", "--background")
    assert "Focus" in study("pomo")
    assert "paused" in study("pomo", "pause")
    assert "already running" in study("pomo", "start", "inf", "-b", ok=False)
    study("pomo", "resume")
    assert "Nothing new to log" in study("pomo", "stop")  # under a minute of focus
    assert "No Pomodoro" in study("pomo", "stop", ok=False)


def test_demo_uses_a_throwaway_database(isolated: Path) -> None:
    out = study("--demo", "status")
    assert "Demo mode" in out and "Machine Learning" in out
    assert not isolated.exists()  # the real database was never touched


def test_reading_commands(tmp_path: Path, course: None) -> None:
    toc = tmp_path / "toc.txt"
    toc.write_text("6 Kernel Methods\n6.1 Dual Representations ..... 293\n6.2 Constructing Kernels\n")
    assert "2 sections" in study("add", "source", "inf", "Bishop PRML", "--author", "Bishop", "--toc", str(toc))
    assert "3 new sections" in study("add", "chapter", "inf", "7", "Sparse Kernel Machines", "-s", "1-3", "--topic", "kernels")
    assert "2/5 needed sections read" in study("read", "inf", "6.1", "7.1")
    assert "No section 9.9" in study("read", "inf", "9.9", ok=False)
    out = study("reading", "inf")
    assert "[x] 6.1  Dual Representations" in out and "→ Kernels and SVMs" in out
    md = study("export")
    assert "### Reading" in md and "- [x] 6.1 Dual Representations" in md
