# Build: `study` — a terminal study tracker for exam season

## Context

I'm a Data Science master's student preparing for exams. I want a fast, keyboard-driven
tool I can open in a terminal to see where I stand, log what I've done, note what I'm
weak on, and keep deadlines in view. It should feel calm and clean, not cluttered.

## Tech stack

- Python 3.11+
- Textual for the TUI, Typer for CLI subcommands, Rich for non-interactive output
- SQLite (via the standard library `sqlite3` or SQLModel) for storage
- Data stored in `~/.local/share/study/study.db` (respect `XDG_DATA_HOME`)
- Config in `~/.config/study/config.toml` (respect `XDG_CONFIG_HOME`)
- Packaged with `pyproject.toml` so it installs with `pipx install .` and runs as `study`

## Data model

- **Course**: name, short code, cram start date, exam date, color, notes
- **Topic**: belongs to a course; title, status (not started / in progress / reviewed / confident),
  confidence 1–5, last studied date
- **Weak spot**: belongs to a course (optionally a topic); description, priority (low/med/high),
  created date, resolved flag + resolved date
- **Deadline**: belongs to a course or is standalone; title, due datetime, type
  (exam / assignment / milestone), done flag
- **Session**: course (+ optional topic), start, duration in minutes, short note
- **Sent notification**: deadline id, threshold, sent timestamp (so alerts never repeat)

## TUI (run `study` with no arguments)

### Overview pane (default screen)

A dashboard showing all subjects at a glance:

1. **Upcoming deadlines**: sorted by date, with countdown ("in 3d 4h"), color-coded:
   red < 48h, yellow < 7 days, overdue clearly flagged
2. **Subjects**: one row per course showing:
   - A **cram timeline line** running from cram start date to exam date, with a marker
     for today (how far into the cramming period I am) and a filled portion for how much
     material is done (% topics reviewed or confident). If the "done" fill is behind the
     "today" marker, color the gap as a warning so I can see at a glance that I'm falling behind
   - Days until exam and hours studied this week
3. **Weak spots**: open items across all subjects, sorted by priority, then age
4. **This week**: total study time per day as a small bar chart or sparkline

### Subject pane (press Enter on a subject)

A full-screen detail view for one subject:

- Header with the subject name, exam countdown, and a larger version of the cram timeline
- Topics list with status, confidence, and days since last studied (stale topics highlighted)
- That subject's weak spots and deadlines
- Recent sessions and total time studied
- `esc` returns to the overview; `[` / `]` jump to the previous/next subject

### Keybindings (show them in a footer)

- `a` add (context-aware: topic, weak spot, deadline, depending on focused pane)
- `e` edit, `d` delete (with confirmation), `space` toggle done/resolved
- `+` / `-` adjust topic confidence
- `s` start a study session timer for the selected subject/topic; `s` again stops and logs it
- `enter` open subject pane, `esc` back to overview
- `/` filter, `tab` switch panes, `?` help screen, `q` quit
- Vim-style `j`/`k` navigation alongside arrow keys

## Notifications

- **In the TUI**: show a toast on launch and while running when a deadline is within the
  warning window, and a persistent banner for anything overdue or due within 24h
- **Desktop notifications**: use `desktop-notifier` (or `notify-send` on Linux /
  `osascript` on macOS as a fallback) so I get alerts even when the TUI is closed
- Add a `study notify` subcommand that checks deadlines and sends any due notifications,
  designed to be run from cron/launchd/systemd timer; document how to set this up in the README
- Default warning thresholds: 7 days, 2 days, and 1 day before, plus the morning of;
  configurable in the config file
- Track which notifications have already been sent so the same alert never fires twice

## CLI subcommands (for quick use without opening the TUI)

- `study add course|topic|weak|deadline ...`
- `study log <course> <minutes> [--topic ...] [--note ...]`
- `study weak <course> "description" [--priority high]`
- `study due` — list upcoming deadlines
- `study status` — compact Rich summary of all courses, including a text cram timeline per course
- `study notify` — send any pending deadline notifications
- `study export --format md|csv` — export everything for backup or review

## Design guidelines

- Clean and minimal: generous spacing, one accent color per course, muted borders
- Respect the terminal's light/dark theme; no hardcoded white or black backgrounds
- Never lose data: write immediately on every change, no explicit save step
- Fast startup (under ~300 ms); no network access

## Quality

- Type hints throughout; separate the storage layer from the UI
- pytest tests for the data layer, date/countdown logic, cram timeline calculation,
  and notification threshold/deduplication logic
- A `--demo` flag that seeds a temporary database with sample courses so I can try the UI
- A short README with install steps, screenshots-as-text, the keybinding list,
  and notification scheduling setup

## How to work

Build in stages and check in with me after each one:

1. Data model + storage + tests
2. CLI subcommands (including `notify`)
3. TUI overview pane (read-only)
4. Subject pane, editing, and the session timer
5. In-TUI notifications and polish
Before starting, propose the project layout and ask me anything that's unclear.
