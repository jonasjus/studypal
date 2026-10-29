# study

A calm, keyboard-driven terminal study tracker for exam season. Keep courses, topics, weak spots,
deadlines and study sessions in one place, and see at a glance whether you're keeping pace with a
cram timeline per course.

```
● INF301  Machine Learning   exam in 12 days · Tue 10 Nov
  ━━━━━━━━━━━━━━━━━━━━━━━━╍╍╍╍╍╍╍╍┃────────────────────  38% done · 62% of cram time used · behind by 25%
  8 topics · 2 weak spots · 5h 15m this week
```

The line runs from the day cramming starts to the exam. `┃` is today; the solid part is how much
material is reviewed or confident; the dashed yellow stretch is how far you're behind.

## Install

Needs Python 3.11 or newer.

```sh
pipx install .
study --demo status      # try it on sample data first
```

Your data lives in `~/.local/share/study/study.db` and settings in `~/.config/study/config.toml`
(both follow `XDG_DATA_HOME` / `XDG_CONFIG_HOME`). Every change is written straight away; there's
no save step.

## The dashboard

Run `study` on its own. The overview shows every subject with its cram timeline, upcoming
deadlines (red under 48 hours, yellow under a week, overdue flagged), open weak spots, and this
week's study time per day.

Keys act on the course you're looking at: the highlighted subject, or the course of the
highlighted deadline or weak spot. So you can go straight from "Problem set 4 is due tomorrow" to
logging time or starting a Pomodoro on that course.

| Key | Overview | Subject |
|---|---|---|
| `enter` / `1`–`9` | open the subject (or the deadline's / weak spot's course) | |
| `tab`, `j` / `k`, arrows | move between and within panes | same |
| `a` | add a course, deadline or weak spot (depends on the pane) | add a topic, weak spot, deadline, or log time |
| `t` | add a topic to the current course | |
| `l` | log study time on the current course | same, for the highlighted topic |
| `w` | note a weak spot | same |
| `s` | start the timer; `s` again stops and logs it | same, on the highlighted topic |
| `p` / `n` / `P` | Pomodoro: start, pause/resume · next block · stop and log | same |
| `space` | mark a deadline done / resolve a weak spot | same |
| `esc`, `[` / `]` | | back · previous / next subject |
| `?` / `q` | help / quit | same |

## Commands

```sh
study                                   # the full-screen dashboard
study status                            # every course with its cram timeline, plus this week's hours
study due [--within 7] [--all]          # deadlines, soonest first; overdue flagged

study add course "Machine Learning" INF301 --exam 12-10 --cram-start 11-01
study add topic INF301 "Kernels and SVMs" [--status reviewed] [--confidence 3]
study add weak INF301 "Dual form derivation" [--priority high] [--topic kernels]
study add deadline "Problem set 4" "fri 14:00" --course INF301 [--type assignment|exam|milestone]

study log INF301 1h30m [--topic kernels] [--note "Bishop ch. 7"] [--at "today 09:00"]
study weak INF301 "Dual form derivation" --priority high      # shortcut for add weak

study export --format md [-o study.md]  # one readable document (printed if no -o)
study export --format csv [-o folder]   # one CSV per table
study notify [--dry-run]                # send deadline notifications that are due (see below)
```

Courses can be named by code, name, or an unambiguous prefix of either (`inf`, `machine`).
Topics work the same way within a course.

Dates: `2026-12-10`, `12-10`, `today`, `tomorrow`, `+3d`, `+2w`, `-5d`, `fri`. Add a time with a
space: `"fri 14:00"`. Deadlines without a time are due at 23:59; exams at 09:00. Each course's exam
is added as a deadline automatically and moves when you change the exam date.

## Pomodoro

```sh
study pomo start INF301 --topic kernels   # starts a run and shows a live countdown
study pomo                                 # where the run is
study pomo watch                           # back to the live countdown
study pomo next | pause | resume | stop
```

Every finished 25-minute focus block is logged as a study session automatically, even if you closed
the terminal in the meantime: the run is saved, and the next `study` command (or the `notify` job)
logs any blocks that finished. Breaks start by themselves; the next focus block waits for you, so
time away from the desk is never logged. Stopping in the middle of a block logs the minutes you
did. Pause time is never counted.

In the live view: `space` next focus block or skip the break · `p` pause/resume · `s` stop and log ·
`q` leave the view (the run keeps going). You get a desktop notification and a terminal bell when a
focus block or a break ends.

## Deadline notifications

`study notify` sends a desktop notification when a deadline reaches a warning threshold: by default
7 days, 2 days and 1 day before, and on the morning of the due day. Each alert is sent once. If
several thresholds passed while your computer was asleep, you get one alert, not a burst. Moving a
deadline re-arms its alerts. Run it on a schedule so alerts arrive while the dashboard is closed.

Find the full path first: `which study` (with pipx usually `~/.local/bin/study`).

### macOS (launchd)

Save as `~/Library/LaunchAgents/local.study.notify.plist`, replacing the path:

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>local.study.notify</string>
  <key>ProgramArguments</key>
  <array>
    <string>/Users/YOU/.local/bin/study</string>
    <string>notify</string>
  </array>
  <key>StartInterval</key><integer>900</integer>
  <key>RunAtLoad</key><true/>
  <key>StandardErrorPath</key><string>/tmp/study-notify.log</string>
</dict>
</plist>
```

```sh
launchctl load ~/Library/LaunchAgents/local.study.notify.plist
```

On macOS notifications are shown through `osascript`, so they appear as coming from Script Editor.
If none show up, allow notifications for Script Editor in System Settings → Notifications.

### Linux (systemd user timer)

`~/.config/systemd/user/study-notify.service`:

```ini
[Unit]
Description=study deadline notifications

[Service]
Type=oneshot
ExecStart=%h/.local/bin/study notify
```

`~/.config/systemd/user/study-notify.timer`:

```ini
[Unit]
Description=Check study deadlines every 15 minutes

[Timer]
OnCalendar=*:0/15
Persistent=true

[Install]
WantedBy=timers.target
```

```sh
systemctl --user enable --now study-notify.timer
```

### cron

```
*/15 * * * * $HOME/.local/bin/study notify
```

cron jobs may not see your desktop session. If notifications don't appear, use the systemd timer,
or add `DISPLAY=:0 DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/$(id -u)/bus` before the command.

To check a setup without real notifications: `STUDY_NOTIFIER=print study notify --dry-run`.

## Configuration

Everything is optional; these are the defaults. `~/.config/study/config.toml`:

```toml
[notifications]
thresholds = ["7d", "2d", "1d", "morning"]   # "morning" = morning of the due day
morning_time = "08:00"
toast_window = "2d"                           # in-app toasts for deadlines this close

[pomodoro]
focus = "25m"
short_break = "5m"
long_break = "15m"
long_break_every = 4

[study]
week_start = "monday"
stale_after_days = 7                          # highlight topics not studied for this long
default_exam_time = "09:00"
```

## Development

```sh
uv venv --python 3.11 .venv
uv pip install -e ".[dev]"
.venv/bin/pytest
```
