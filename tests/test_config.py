from __future__ import annotations

from datetime import time, timedelta
from pathlib import Path

import pytest

from study import config, paths
from study.config import ConfigError


def test_missing_file_gives_defaults(tmp_path: Path) -> None:
    cfg = config.load(tmp_path / "nope.toml")
    assert [t.key for t in cfg.thresholds] == ["7d", "2d", "1d", "morning"]
    assert cfg.morning_time == time(8, 0) and cfg.week_start == 0 and cfg.stale_after_days == 7


def test_reads_every_setting(tmp_path: Path) -> None:
    path = tmp_path / "config.toml"
    path.write_text(
        '[notifications]\nthresholds = ["3d", "12h", "morning", "3d"]\nmorning_time = "07:30"\ntoast_window = "36h"\n'
        '[study]\nweek_start = "Sunday"\nstale_after_days = 5\ndefault_exam_time = "14:00"\n'
    )
    cfg = config.load(path)
    assert [t.key for t in cfg.thresholds] == ["3d", "12h", "morning"]
    assert cfg.thresholds[1].before == timedelta(hours=12)
    assert cfg.morning_time == time(7, 30) and cfg.toast_window == timedelta(hours=36)
    assert cfg.week_start == 6 and cfg.stale_after_days == 5 and cfg.default_exam_time == time(14, 0)


@pytest.mark.parametrize(
    ("toml", "message"),
    [
        ('[notifications]\nthresholds = ["soon"]', "isn't a duration"),
        ('[notifications]\nthresholds = "7d"', "must be a list"),
        ('[notifications]\nmorning_time = "8am"', "isn't a time"),
        ('[study]\nweek_start = "funday"', "isn't a weekday"),
        ('[study]\nstale_after_days = 0', "1 or more"),
        ("not toml [", "isn't valid TOML"),
    ],
)
def test_bad_values_explain_themselves(tmp_path: Path, toml: str, message: str) -> None:
    path = tmp_path / "config.toml"
    path.write_text(toml)
    with pytest.raises(ConfigError, match=message):
        config.load(path)


def test_xdg_paths(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "cfg"))
    monkeypatch.delenv("STUDY_DB", raising=False)
    assert paths.db_path() == tmp_path / "data" / "study" / "study.db"
    assert paths.config_path() == tmp_path / "cfg" / "study" / "config.toml"
    monkeypatch.setenv("XDG_DATA_HOME", "relative/path")  # invalid per the spec: ignored
    assert paths.db_path() == Path.home() / ".local/share/study/study.db"
    monkeypatch.setenv("STUDY_DB", str(tmp_path / "demo.db"))
    assert paths.db_path() == tmp_path / "demo.db"
