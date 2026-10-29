"""The full-screen TUI: `study` with no arguments."""

from __future__ import annotations


def run_tui() -> None:
    from .. import config, paths
    from ..config import ConfigError
    from ..storage import Store

    try:
        cfg = config.load()
    except ConfigError as e:
        raise SystemExit(f"Problem in {paths.config_path()}: {e}") from None
    store = Store(paths.db_path(), exam_time=cfg.default_exam_time)
    try:
        from .app import StudyApp

        StudyApp(store, cfg).run()
    finally:
        store.close()
