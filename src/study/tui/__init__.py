"""The full-screen TUI (arrives in stage 3). Until then, `study` shows the status summary."""

from __future__ import annotations


def run_tui() -> None:
    from rich.console import Console

    from ..cli import status

    status()
    Console(stderr=True).print("[dim]The full-screen dashboard arrives in stage 3; this is `study status` for now.[/]")
