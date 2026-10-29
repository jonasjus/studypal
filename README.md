# study

A calm, keyboard-driven terminal study tracker for exam season. Keep courses, topics, weak spots,
deadlines and study sessions in one place, and see at a glance whether you're keeping pace with a
cram timeline per course.

```
● INF301  Machine Learning   exam in 12 days · Tue 10 Nov
  ━━━━━━━━━━━━━━━━━━━━╍╍╍╍╍╍╍╍╍╍╍╍┃────────────────────  38% done · 62% of cram time used · behind by 25%
  8 topics · 3 stale · 2 weak spots · 5h 15m this week
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

Run `study` on its own (here with `--demo` data):

```
  study  Thursday 29 October                                                               11h 15m this week
 █ ▲ 1 overdue: Pipeline project report (DAT255) overdue by 20h 23m
 ╭─ Subjects ──────────────────────────────────────────────────╮ ╭─ Upcoming deadlines ───────────────────╮
 │ ▊                                                           │ │ ▊ OVERDUE   Pipeline project … DAT255  │
 │ ▊1 ● DAT255  Data Engineering                           2d  │ │   1d 5h     Problem set 4      INF301  │
 │ ▊  ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━╍╍╍╍╍╍╍╍╍╍╍╍╍┃────    │ │   1d 14h    DAT255 exam        DAT255  │
 │ ▊  67% done · 93% of cram time used · behind by 26%         │ │   5d 2h     Mandatory assignm… STK310  │
 │ ▊  6 topics · 1 weak spot · 3h 15m this week                │ │   11d 14h   INF301 exam        INF301  │
 │ ▊                                                           │ │   14d 23h   Thesis outline to supe… —  │
 │                                                             │ │   23d 14h   STK310 exam        STK310  │
 │  2 ● INF301  Machine Learning                          12d  │ │   39d 14h   INF395 exam        INF395  │
 │    ━━━━━━━━━━━━━━━━━━━━╍╍╍╍╍╍╍╍╍╍╍╍┃────────────────────    │ │                                        │
 │    38% done · 62% of cram time used · behind by 25%         │ │                                        │
 │    8 topics · 3 stale · 2 weak spots · 5h 15m this week     │ ╰─────────────────────────────── 8 open ─╯
 │                                                             │ ╭─ Weak spots ───────────────────────────╮
 │                                                             │ │ ▊ ▲ Can't derive the dual form of      │
 │  3 ● STK310  Statistical Inference                     24d  │ │ ▊ the SVM without notes  INF301 ·      │
 │    ━━━━━┃━━━━━━━──────  67% done · 29% of cram time used    │ │ ▊ 6d                                ▅▅ │
 │    6 topics · 2 weak spots · 2h 45m this week               │ │   ▲ Factorisation theorem proofs       │
 │                                                             │ │   STK310 · 2d                          │
 │                                                             │ ╰─────────────────────────────── 5 open ─╯
 │  4 ● INF395  Deep Learning                             40d  │ ╭─ This week ────────────────────────────╮
 │    ────────────────  0% done · cramming starts in 3 days    │ │ Mon ████████████████████████ 4h        │
 │    3 topics · 0m this week                                  │ │ Tue ████████████ 1h 55m                │
 │                                                             │ │ Wed █████████████████ 2h 50m           │
 │                                                             │ │ Thu ███████████████ 2h 30m             │
 │                                                             │ │ Fri                                    │
 │                                                             │ │ Sat                                    │
 │                                                             │ │ Sun                                    │
 │                                                             │ │ 11h 15m this week                      │
 ╰─────────────────────────────────────────────────────────────╯ ╰────────────────────────────────────────╯
 a Add  l Log  w Weak spot  s Timer  p Pomodoro  e Edit  d Delete  / Filter  q Quit  ? Help
```

The overview shows every subject with its cram timeline, upcoming deadlines (red under 48 hours,
yellow under a week, overdue flagged), open weak spots, and this week's study time per day.
`enter` or a number opens a subject:

```
  study  Thursday 29 October
 █ ▲ 1 overdue: Pipeline project report (DAT255) overdue by 20h 23m
  ● INF301  Machine Learning                                                    exam in 12 days · Tue 10 Nov
 ╭─ Cram timeline ──────────────────────────────────────────────────────────────────────────────────────────╮
 │  ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━╍╍╍╍╍╍╍╍╍╍╍╍╍╍╍╍╍╍╍╍╍╍╍╍╍┃──────────────────────────────────────  │
 │  ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━╍╍╍╍╍╍╍╍╍╍╍╍╍╍╍╍╍╍╍╍╍╍╍╍╍┃──────────────────────────────────────  │
 │  Fri 9 Oct                                                      ▲ today                 exam Tue 10 Nov  │
 │                                                                                                          │
 │  38% done · 62% of cram time used · behind by 25%                                                        │
 ╰──────────────────────────────────────────────────────────────────────────────────────────────────────────╯
 ╭─ Topics · 3/8 done ─────────────────────────────────────────╮ ╭─ Weak spots ───────────────────────────╮
 │ ▊ ◆  Linear models    confident    ●●●●●    9d ago · stale  │ │ ▊ ▲ Can't derive the dual form of      │
 │   ●  Regularisation   reviewed     ●●●●○    8d ago · stale  │ │ ▊ the SVM without notes  Kernels    ▄▄ │
 │   ◐  Kernels and SVMs in progress  ●●○○○         yesterday  │ │ ▊ and SVMs · 6d                        │
 │   ◐  Trees and boost… in progress  ●●●○○             today  │ ╰────────────────────────────────────────╯
 │   ○  Probabilistic m… not started  ●○○○○             never  │ ╭─ Deadlines ────────────────────────────╮
 │   ●  Model selection  reviewed     ●●●○○   11d ago · stale  │ │ ▊ 1d 5h     Problem set 4              │
 │   ○  Neural networks  not started  ●○○○○             never  │ │   11d 14h   INF301 exam                │
 │   ○  Unsupervised le… not started  ●○○○○             never  │ │                                        │
 │                                                             │ ╰────────────────────────────────────────╯
 │                                                             │ ╭─ Recent sessions ──────────────────────╮
 │                                                             │ │ ▊ Thu 29 Oct 12:15       1h  Trees…    │
 │                                                             │ │   Wed 28 Oct 15:15      55m  Trees…    │
 │                                                             │ │   Wed 28 Oct 09:15    1h 5m  Trees…    │
 │                                                             │ │   Tue 27 Oct 12:15       1h  Trees… ▁▁ │
 │                                                             │ │   Mon 26 Oct 12:15   1h 15m  Kerne…    │
 │                                                             │ │   Sun 25 Oct 09:15       1h  Kerne…    │
 │                                                             │ │   Sat 24 Oct 12:15      55m  Kerne…    │
 │                                                             │ │   Fri 23 Oct 12:15   1h 10m  Trees…    │
 ╰─────────────────────────────────────────────────────────────╯ ╰───── 5h 15m this week · 17h 50m total ─╯
 esc Back  [ ] Prev/next  a Add  l Log  s Timer  p Pomodoro  e Edit  d Delete  / Filter  q Quit  ? Help
```

Anything overdue or due within 24 hours stays in a banner at the top until it's done. On launch,
and whenever another deadline comes within the warning window (2 days by default), a toast lists
what's coming up. While the dashboard is open it also sends the same desktop alerts as
`study notify`, so you get them even without the scheduled job; they're never sent twice.

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
| `space` | mark a deadline done / resolve a weak spot | same; on a topic, move it to the next status |
| `e` / `d` | edit / delete what's highlighted (`d` asks first) | same; `E` edits the course |
| `+` / `-` | | change the highlighted topic's confidence |
| `/` | filter every pane by text (`esc` clears) | same |
| `T` | pick a colour theme | same |
| `esc`, `[` / `]` | clear the filter | back (or clear the filter) · previous / next subject |
| `r` | reading list of the current course | same; from a topic, at its chapter |
| `G` | sync with git now | same |
| `?` / `q` | help / quit | same |

## Reading list

Each course can have a reading list: books or notes, with chapters and sections to tick off.
Press `r` in the dashboard (on a subject's topic it opens at that topic's chapter), or use the CLI.

```
▾ Pattern Recognition and Machine Learning · Bishop                 8/13 +0/3 optional  ━━━━━━──
  ▾ 6  Kernel Methods  → Kernels and SVMs                                   1/3 +0/1 optional  ━━───
      [ ] 6.1
      [x] 6.2
      ( ) 6.4  optional
```

- **Needed or optional.** Sections are needed by default; `o` makes a section (or a whole chapter)
  optional. Progress only counts needed sections, so optional reading never makes you look behind.
- **Adding sections.** `a` adds a chapter with sections by range: `6.1-6.5, 6.7`, or `1-5` inside
  chapter 6. `i` pastes a table of contents: lines like `6.1 Dual representations ..... 293` become
  sections (page numbers and dot leaders are dropped). Sections already on the list are kept.
- **Linked to topics.** `t` links a chapter, or a single section, to a topic. The topic then shows
  `read 3/5` on the subject page. Reading a section counts as studying its topic that day, and when
  all of a not-started topic's needed reading is read, the topic moves to *in progress*.

| Key | Reading list |
|---|---|
| `space` | tick a section read; on a chapter, all its needed sections |
| `o` | needed ⇄ optional |
| `enter` | fold a chapter or book |
| `a` / `i` / `b` | add sections by range · paste contents · add a book or notes |
| `t` / `e` / `d` | link to a topic · edit · delete |

```sh
study add source INF301 "Pattern Recognition and ML" --author Bishop --toc contents.txt
study add chapter INF301 6 "Kernel methods" --sections 1-5 --topic kernels
study read INF301 6.1 6.3-6.5
study reading INF301
```

## Themes

Press `T` in the dashboard (or run `study theme`) to pick a colour theme: moving through the list
previews it, `enter` keeps it. The default, **terminal**, uses your terminal's own colours and
background. The others paint their own: Gruvbox dark and light, Nord, Dracula, Catppuccin Mocha and
Latte, Tokyo Night, Solarized dark and light, Rosé Pine, One Dark and Monokai.

Warning colours and course accents follow the theme: a course on one of the default colours is drawn
in that theme's matching shade, so a blue course stays blue but becomes gruvbox blue. A colour you set
yourself is kept. The choice applies to the dashboard; CLI output keeps your terminal's colours.

```sh
study theme                 # list them
study theme gruvbox         # use one
```

## Commands

```sh
study                                   # the full-screen dashboard
study status                            # every course with its cram timeline, plus this week's hours
study due [--within 7] [--all]          # deadlines, soonest first; overdue flagged

study add course "Machine Learning" INF301 --exam 10.12 --cram-start 01.11
study add topic INF301 "Kernels and SVMs" [--status reviewed] [--confidence 3]
study add weak INF301 "Dual form derivation" [--priority high] [--topic kernels]
study add deadline "Problem set 4" "fri 14:00" --course INF301 [--type assignment|exam|milestone]

study log INF301 1h30m [--topic kernels] [--note "Bishop ch. 7"] [--at "today 09:00"]
study weak INF301 "Dual form derivation" --priority high      # shortcut for add weak

study export --format md [-o study.md]  # one readable document (printed if no -o)
study export --format csv [-o folder]   # one CSV per table
study sync [--init URL] [--status]      # git sync between devices (see below)
study notify [--dry-run]                # send deadline notifications that are due (see below)
```

Courses can be named by code, name, or an unambiguous prefix of either (`inf`, `machine`).
Topics work the same way within a course.

Dates are day-month-year: `10.12.2026`, `10-12-2026`, `10/12/26`, `10.12` (the next 10 December),
`today`, `tomorrow`, `+3d`, `+2w`, `-5d`, `fri`. Year-first `2026-12-10` works too. Add a time with a
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

## Syncing between devices with git

Like Obsidian Git: your data goes into a git repository you push to a private remote (GitHub,
GitLab, your own server), and each device pulls the others' changes.

```sh
# First device: make an empty private repo on GitHub, then
study sync --init git@github.com:YOU/study-data.git

# Every other device (its existing data is merged in, not replaced)
study sync --init git@github.com:YOU/study-data.git
```

After that:

- `study` pulls and merges when it starts (turn off with `pull_on_start = false` under `[sync]`).
- `G` in the dashboard, or `study sync`, commits your changes, pulls and merges, then pushes.
- `study sync --no-push` pulls only; `study sync --status` shows what hasn't been synced yet.

How merging works: the database itself isn't committed (git can't merge binary files). A sync writes
your data as text, one file per table and one line per item, in `~/.local/share/study/sync/data/`,
and merges item by item. Edits to different things on two devices both survive. If the same thing
changed on both, the newer change wins. If one device deleted something the other edited, the edit is
kept, and a course another device still added to comes back. A chapter added on both devices is
combined, and two different courses with the same code get the second one renamed (`INF301-2`).

Offline is fine: a sync without network commits locally and pushes next time. git uses your usual
credentials (SSH key or credential helper) and never stops to ask for a password.

If you choose SSH keys per folder (`includeIf "gitdir:..."` in `~/.gitconfig`), note the sync repo
lives in `~/.local/share/study/sync`, outside your project folders. Give it the right key once:

```sh
git -C ~/.local/share/study/sync config core.sshCommand "ssh -i ~/.ssh/YOUR_KEY"
``` A running timer or
Pomodoro stays on the device it was started on.

## Your data

Everything is in one SQLite file (`study --version` shows where). Back it up by copying that file,
or keep a readable copy with `study export --format md -o study-backup.md`. To start over, move the
file away; `study` creates a fresh one.

## Development

```sh
uv venv --python 3.11 .venv
uv pip install -e ".[dev]"
.venv/bin/pytest
```
