from __future__ import annotations

from study import themes
from study.models import COURSE_COLORS


def test_every_theme_has_eight_accents_and_a_textual_theme() -> None:
    from textual.theme import BUILTIN_THEMES

    for p in themes.THEMES:
        assert len(p.accents) == len(COURSE_COLORS), p.name
        assert p.textual in BUILTIN_THEMES or p.textual in ("study", "gruvbox-light"), p.name


def test_default_course_colours_map_to_the_theme_and_custom_ones_stay() -> None:
    gruvbox = themes.get("gruvbox")
    assert gruvbox.course_color(COURSE_COLORS[0]) == "#83a598"  # blue -> gruvbox blue
    assert gruvbox.course_color("#123456") == "#123456"
    assert themes.get("terminal").course_color(COURSE_COLORS[3]) == COURSE_COLORS[3]


def test_unknown_names_fall_back_to_the_terminal_theme() -> None:
    assert themes.get("nope") is themes.DEFAULT and themes.get(None) is themes.DEFAULT
    assert themes.get(" Gruvbox ").name == "gruvbox"


def test_cli_theme_command(tmp_path, monkeypatch) -> None:
    from typer.testing import CliRunner

    from study.cli import app
    from study.storage import Store

    monkeypatch.setenv("STUDY_DB", str(tmp_path / "s.db"))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "cfg"))
    runner = CliRunner()
    assert "Gruvbox light" in runner.invoke(app, ["theme"]).output
    assert runner.invoke(app, ["theme", "gruvbox-light"]).exit_code == 0
    assert runner.invoke(app, ["theme", "solarised"]).exit_code == 1
    with Store(tmp_path / "s.db") as s:
        assert s.get_setting("theme") == "gruvbox-light"
