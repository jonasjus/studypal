"""Where study keeps its data and config, following the XDG base directory spec."""

from __future__ import annotations

import os
from pathlib import Path

APP = "study"


def _xdg(var: str, fallback: str) -> Path:
    value = os.environ.get(var, "").strip()
    # The spec says relative paths are invalid and must be ignored.
    if value and os.path.isabs(value):
        return Path(value)
    return Path.home() / fallback


def data_dir() -> Path:
    return _xdg("XDG_DATA_HOME", ".local/share") / APP


def config_dir() -> Path:
    return _xdg("XDG_CONFIG_HOME", ".config") / APP


def db_path() -> Path:
    """The database file. STUDY_DB overrides it (used by --demo and tests)."""
    override = os.environ.get("STUDY_DB", "").strip()
    return Path(override) if override else data_dir() / "study.db"


def config_path() -> Path:
    return config_dir() / "config.toml"
