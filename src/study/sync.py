"""Syncing study's data through a git repository, the way Obsidian Git syncs a vault.

The database itself never goes into git (git can't merge binary files). Instead a sync writes the
data as text, one file per table and one row per line, sorted by each row's stable id:

    sync/
      data/course.jsonl  data/topic.jsonl  ...  data/sent.jsonl

A sync then:
  1. exports the database and commits any local changes,
  2. fetches the remote,
  3. merges row by row against the last shared version (see logic/merge.py) and commits the merge,
  4. loads the result back into the database,
  5. pushes (skipped for the pull on start).

Steps 1, 3 and 4 run inside one database write lock, so nothing typed in the meantime is lost;
the network steps (2 and 5) run outside it. The running timer and Pomodoro stay on each device.
"""

from __future__ import annotations

import json
import os
import socket
import sqlite3
import subprocess
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from . import paths
from .logic.merge import LINKS, TABLES, Dataset, MergeReport, changed_rows, empty, merge3, repair
from .storage import Store

# Fields stored for each table (besides uid, updated and links).
FIELDS: dict[str, list[str]] = {
    "course": ["name", "code", "cram_start", "exam_date", "color", "notes"],
    "topic": ["title", "status", "confidence", "last_studied"],
    "source": ["title", "author", "position"],
    "chapter": ["number", "title", "position"],
    "section": ["number", "title", "required", "read", "read_at", "position"],
    "weak_spot": ["description", "priority", "created_at", "resolved", "resolved_at"],
    "deadline": ["title", "due_at", "kind", "done", "is_course_exam"],
    "session": ["started_at", "minutes", "note"],
}
DATA_DIR = "data"
README = """# study data

Synced by `study sync`. Each file holds one table, one row per line, so changes from different
devices merge row by row. Don't edit these by hand while study is syncing.
"""


class SyncError(Exception):
    """Something went wrong talking to git; the message says what."""


@dataclass
class SyncResult:
    pulled: int = 0  # items changed by what came in from other devices
    pushed: bool = False
    committed: bool = False  # local changes were committed
    offline: str = ""  # why the remote couldn't be reached, if it couldn't
    report: MergeReport = field(default_factory=MergeReport)

    def summary(self) -> str:
        parts = []
        if self.offline:
            parts.append(f"Couldn't reach the remote ({self.offline}); local changes are committed and will go up next time")
        if self.pulled:
            parts.append(f"pulled {self.pulled} change{'s' if self.pulled != 1 else ''} from other devices")
        if self.pushed:
            parts.append("pushed your changes")
        if not parts:
            parts.append("already up to date")
        text = "; ".join(parts)
        notes = self.report.notes()
        return (text[0].upper() + text[1:]) + "." + (" " + "; ".join(n[0].upper() + n[1:] for n in notes) + "." if notes else "")


def repo_dir(store: Store | None = None) -> Path:
    """The sync repo sits next to the database it syncs, so a demo or test database never touches yours."""
    db = Path(store.path) if store is not None and str(store.path) != ":memory:" else paths.db_path()
    return db.parent / "sync"


def is_set_up(repo: Path) -> bool:
    return (repo / ".git").exists()


# ---------- database <-> dataset ----------

def export_dataset(conn: sqlite3.Connection) -> Dataset:
    uids: dict[str, dict[int, str]] = {}
    data = empty()
    for table in TABLES:
        if table == "sent":
            continue
        rows = conn.execute(f"select * from {table}").fetchall()
        uids[table] = {r["id"]: r["uid"] for r in rows}
        for r in rows:
            row = {"uid": r["uid"], "updated": r["updated_at"]}
            row.update({f: r[f] for f in FIELDS[table]})
            for link, (parent, _) in LINKS[table].items():
                local_id = r[f"{link}_id"]
                row[link] = uids[parent].get(local_id) if local_id is not None else None
            data[table][r["uid"]] = row
    for r in conn.execute("select * from sent_notification"):
        deadline = uids["deadline"].get(r["deadline_id"])
        if deadline:
            key = f"{deadline}|{r['threshold']}|{r['due_at']}"
            data["sent"][key] = {"uid": key, "deadline": deadline, "threshold": r["threshold"],
                                 "due_at": r["due_at"], "sent_at": r["sent_at"]}
    return data


def apply_dataset(conn: sqlite3.Connection, data: Dataset) -> None:
    """Make the database hold exactly `data`. Rows keep their local ids, so a running timer stays valid.
    Must run inside a transaction."""
    conn.execute("pragma defer_foreign_keys = on")
    # Deletions first, children before parents (a deleted parent's children are gone from `data` too).
    conn.execute("delete from sent_notification")
    for table in reversed([t for t in TABLES if t != "sent"]):
        keep = set(data[table])
        for (row_id, uid) in conn.execute(f"select id, uid from {table}").fetchall():
            if uid not in keep:
                conn.execute(f"delete from {table} where id = ?", (row_id,))
    ids: dict[str, dict[str, int]] = {}
    for table in TABLES:
        if table == "sent":
            continue
        local = {uid: row_id for row_id, uid in conn.execute(f"select id, uid from {table}")}
        columns = FIELDS[table] + [f"{link}_id" for link in LINKS[table]] + ["updated_at"]
        # Existing rows first, then new ones, so a renamed course code is free before a new course takes it.
        rows = sorted(data[table].items(), key=lambda item: item[0] not in local)
        for uid, row in rows:
            values = [row.get(f) for f in FIELDS[table]]
            values += [ids[parent].get(row.get(link)) if row.get(link) else None
                       for link, (parent, _) in LINKS[table].items()]
            values.append(row.get("updated"))
            if uid in local:
                sets = ", ".join(f"{c} = ?" for c in columns)
                conn.execute(f"update {table} set {sets} where id = ?", (*values, local[uid]))
            else:
                marks = ", ".join("?" * (len(columns) + 1))
                cur = conn.execute(f"insert into {table} ({', '.join(columns)}, uid) values ({marks})", (*values, uid))
                local[uid] = cur.lastrowid
        ids[table] = local
    for row in data["sent"].values():
        deadline_id = ids["deadline"].get(row["deadline"])
        if deadline_id is not None:
            conn.execute("insert or ignore into sent_notification (deadline_id, threshold, due_at, sent_at) values (?, ?, ?, ?)",
                         (deadline_id, row["threshold"], row["due_at"], row["sent_at"]))


# ---------- dataset <-> files ----------

def write_dataset(repo: Path, data: Dataset) -> None:
    folder = repo / DATA_DIR
    folder.mkdir(parents=True, exist_ok=True)
    for table in TABLES:
        lines = [json.dumps(row, sort_keys=True, ensure_ascii=False) for _, row in sorted(data[table].items())]
        (folder / f"{table}.jsonl").write_text("".join(line + "\n" for line in lines), encoding="utf-8")


def _parse(text: str, where: str) -> dict[str, dict]:
    rows = {}
    for n, line in enumerate(text.splitlines(), start=1):
        if line.strip():
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                raise SyncError(f"{where} line {n} isn't valid. It may have been edited by hand or left mid-merge.") from None
            rows[row["uid"]] = row
    return rows


def read_dataset(repo: Path) -> Dataset:
    data = empty()
    for table in TABLES:
        path = repo / DATA_DIR / f"{table}.jsonl"
        if path.exists():
            data[table] = _parse(path.read_text(encoding="utf-8"), f"{DATA_DIR}/{table}.jsonl")
    return data


def read_dataset_at(git: Git, commit: str | None) -> Dataset:
    data = empty()
    if commit is None:
        return data
    for table in TABLES:
        text = git.run("show", f"{commit}:{DATA_DIR}/{table}.jsonl", check=False)
        if text is not None:
            data[table] = _parse(text, f"{DATA_DIR}/{table}.jsonl at {commit[:8]}")
    return data


# ---------- git ----------

def explain(output: str) -> str:
    """git's reason for failing, without the boilerplate, plus a hint for the common cases."""
    lines = [line.strip() for line in output.strip().splitlines() if line.strip()]
    useful = [line.removeprefix("fatal: ").removeprefix("error: ").removeprefix("ERROR: ").rstrip(".")
              for line in lines
              if line.startswith(("fatal:", "error:", "ERROR:")) or "Permission denied" in line]
    text = (". ".join(dict.fromkeys(useful)) or (lines[-1] if lines else "no details")).replace("git@github.com: ", "")
    if "Permission denied (publickey)" in output:
        text += (". GitHub didn't accept the SSH key git used here. If you pick keys per folder (includeIf in "
                 "~/.gitconfig), the sync repo is outside those folders; set its key with: git -C <sync folder> "
                 "config core.sshCommand \"ssh -i ~/.ssh/<your key>\"")
    elif "Repository not found" in output or "repository not found" in output:
        text += ". Check the URL, that the repo exists on GitHub, and that your key's account can see it"
    return text


class Git:
    def __init__(self, repo: Path) -> None:
        self.repo = repo

    def run(self, *args: str, check: bool = True, timeout: float = 30) -> str | None:
        env = {**os.environ, "GIT_TERMINAL_PROMPT": "0", "LC_ALL": "C"}  # never stop to ask for a password
        try:
            done = subprocess.run(["git", *args], cwd=self.repo, capture_output=True, text=True, timeout=timeout, env=env)
        except FileNotFoundError:
            raise SyncError("git isn't installed (or isn't on the PATH).") from None
        except subprocess.TimeoutExpired:
            raise SyncError(f"git {args[0]} took longer than {int(timeout)} seconds") from None
        if done.returncode != 0:
            if not check:
                return None
            raise SyncError(f"git {args[0]} failed: {explain(done.stderr or done.stdout)}")
        return done.stdout

    def commit(self, message: str) -> None:
        identity = []
        if not (self.run("config", "user.email", check=False) or "").strip():
            identity = ["-c", "user.name=study", "-c", f"user.email=study@{socket.gethostname()}"]
        self.run(*identity, "commit", "--quiet", "--no-verify", "-m", message)

    def has_staged_changes(self) -> bool:
        return self.run("diff", "--cached", "--quiet", check=False) is None

    def branch(self) -> str:
        return (self.run("symbolic-ref", "--short", "HEAD", check=False) or "main").strip()

    def remote_url(self) -> str | None:
        return (self.run("remote", "get-url", "origin", check=False) or "").strip() or None

    def ref_exists(self, ref: str) -> bool:
        return self.run("rev-parse", "--verify", "--quiet", ref, check=False) is not None

    def ahead_behind(self, ref: str) -> tuple[int, int]:
        out = (self.run("rev-list", "--left-right", "--count", f"HEAD...{ref}") or "0 0").split()
        return int(out[0]), int(out[1])


# ---------- sync ----------

def _commit_message(kind: str) -> str:
    return f"study: {kind} on {socket.gethostname()}, {datetime.now():%d.%m.%Y %H:%M}"


def init(store: Store, url: str | None = None, repo: Path | None = None) -> SyncResult:
    """Make the sync repo (if it isn't there yet), point it at `url`, and do a first sync."""
    repo = repo or repo_dir(store)
    repo.mkdir(parents=True, exist_ok=True)
    git = Git(repo)
    if not is_set_up(repo):
        git.run("init", "--quiet", "-b", "main")
        (repo / "README.md").write_text(README, encoding="utf-8")
    if url:
        if git.remote_url():
            git.run("remote", "set-url", "origin", url)
        else:
            git.run("remote", "add", "origin", url)
    return sync(store, push=True, repo=repo)


def sync(store: Store, push: bool = True, repo: Path | None = None) -> SyncResult:
    repo = repo or repo_dir(store)
    if not is_set_up(repo):
        raise SyncError("Sync isn't set up yet. Run study sync --init <url of a private git repo>.")
    git = Git(repo)
    result = SyncResult()
    branch = git.branch()
    remote = git.remote_url()
    fetched = False
    if remote:
        try:
            git.run("fetch", "--quiet", "origin", timeout=30)
            fetched = True
        except SyncError as e:
            result.offline = str(e)

    remote_ref = f"origin/{branch}"
    with store.sync_lock() as conn:
        local = export_dataset(conn)
        write_dataset(repo, local)
        git.run("add", "--all")
        if git.has_staged_changes() or not git.ref_exists("HEAD"):
            git.commit(_commit_message("changes"))
            result.committed = True
        if fetched and git.ref_exists(remote_ref):
            ahead, behind = git.ahead_behind(remote_ref)
            if behind:
                if ahead == 0:
                    git.run("merge", "--quiet", "--ff-only", remote_ref)
                else:
                    base = (git.run("merge-base", "HEAD", remote_ref, check=False) or "").strip() or None
                    merged, result.report = merge3(read_dataset_at(git, base), read_dataset_at(git, "HEAD"),
                                                   read_dataset_at(git, remote_ref))
                    # Record a real merge (so both histories are kept), but with our merged files as its content.
                    git.run("merge", "--quiet", "--no-ff", "--no-commit", "--allow-unrelated-histories", "-s", "ours",
                            remote_ref)
                    write_dataset(repo, merged)
                    git.run("add", "--all")
                    git.commit(_commit_message("merge"))
                data = read_dataset(repo)
                repair(data, [], MergeReport())  # in case the remote's files came from an older study
                apply_dataset(conn, data)
                result.pulled = changed_rows(local, data)

    if push and fetched:
        if not git.ref_exists(remote_ref) or git.ahead_behind(remote_ref)[0] > 0:
            try:
                git.run("push", "--quiet", "-u", "origin", branch, timeout=60)
                result.pushed = True
            except SyncError as e:
                result.offline = str(e)
    store.set_setting("last_sync", datetime.now().isoformat(timespec="seconds"))
    return result


@dataclass
class SyncStatus:
    set_up: bool
    remote: str | None = None
    branch: str = ""
    last_sync: str | None = None
    unsynced_local: bool = False  # changes in the database not yet committed
    ahead: int = 0  # commits not pushed (as of the last fetch)
    behind: int = 0  # remote commits not pulled (as of the last fetch)


def status(store: Store, repo: Path | None = None) -> SyncStatus:
    repo = repo or repo_dir(store)
    if not is_set_up(repo):
        return SyncStatus(False)
    git = Git(repo)
    st = SyncStatus(True, git.remote_url(), git.branch(), store.get_setting("last_sync"))
    current = export_dataset(store.conn)
    committed = read_dataset_at(git, "HEAD") if git.ref_exists("HEAD") else empty()
    st.unsynced_local = current != committed
    if git.ref_exists(f"origin/{st.branch}"):
        st.ahead, st.behind = git.ahead_behind(f"origin/{st.branch}")
    return st
