"""Vault location, file I/O, parsing, git ops, locking."""

from __future__ import annotations

import contextlib
import fcntl
import os
import re
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass
from typing import Iterator

ENTRY_PAT = re.compile(r"^## (\d{4}-\d{2}-\d{2})(?: (\d{2}:\d{2}))? — (.+?)\s*$")
H1_PAT = re.compile(r"^# (.+?)\s*$")
RELATED_PAT = re.compile(r"^\*\*Related:\*\*\s*(.+?)\s*$")
AUTHOR_PAT = re.compile(r"^_author:\s*(.+?)_\s*$")
_FENCE_PAT = re.compile(r"^(?:```|~~~)")


def config_path() -> str:
    """Return the path to the per-user vault-pointer config file."""
    xdg = os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config")
    return os.path.join(xdg, "tephra", "vault")


def default_folder_path() -> str:
    """Return the path to the per-user default-folder config file."""
    xdg = os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config")
    return os.path.join(xdg, "tephra", "default_folder")


def auto_sync_config_path() -> str:
    """Return the path to the per-user auto-sync toggle config file."""
    xdg = os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config")
    return os.path.join(xdg, "tephra", "auto_sync")


def sync_metric_config_path() -> str:
    """Return the path to the per-user sync-metric path config file."""
    xdg = os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config")
    return os.path.join(xdg, "tephra", "sync_metric_path")


def _read_config_vault() -> str | None:
    """Return the vault path stored in the config file, or None if absent."""
    path = config_path()
    if not os.path.isfile(path):
        return None
    try:
        with open(path, encoding="utf-8") as f:
            value = f.read().strip()
    except OSError:
        return None
    return os.path.expanduser(value) if value else None


def read_default_folder() -> str | None:
    """Return the configured default folder, or None if unset (= root vault)."""
    path = default_folder_path()
    if not os.path.isfile(path):
        return None
    try:
        with open(path, encoding="utf-8") as f:
            value = f.read().strip()
    except OSError:
        return None
    return value or None


def read_auto_sync() -> bool:
    """Return True iff auto-sync is enabled in the user config."""
    path = auto_sync_config_path()
    if not os.path.isfile(path):
        return False
    try:
        with open(path, encoding="utf-8") as f:
            return f.read().strip().lower() == "on"
    except OSError:
        return False


def read_sync_metric_path() -> str | None:
    """Return the configured sync-metric output path, or None if unset."""
    path = sync_metric_config_path()
    if not os.path.isfile(path):
        return None
    try:
        with open(path, encoding="utf-8") as f:
            value = f.read().strip()
    except OSError:
        return None
    return os.path.expanduser(value) if value else None


def write_auto_sync(on: bool) -> None:
    """Persist the auto-sync toggle (``on``/``off``) in the user config file."""
    cfg = auto_sync_config_path()
    os.makedirs(os.path.dirname(cfg), exist_ok=True)
    with open(cfg, "w", encoding="utf-8") as f:
        f.write("on\n" if on else "off\n")


def write_sync_metric_path(path: str | None) -> None:
    """Persist the sync-metric output path. Pass None/empty to clear."""
    cfg = sync_metric_config_path()
    os.makedirs(os.path.dirname(cfg), exist_ok=True)
    if not path:
        if os.path.isfile(cfg):
            os.unlink(cfg)
        return
    with open(cfg, "w", encoding="utf-8") as f:
        f.write(path + "\n")


def vault_source() -> tuple[str, str]:
    """Return ``(resolved_vault_path, source)`` for diagnostic output."""
    cfg = _read_config_vault()
    if cfg:
        return cfg, f"config file ({config_path()})"
    xdg = os.environ.get("XDG_DATA_HOME") or os.path.expanduser("~/.local/share")
    return os.path.join(xdg, "tephra", "vault"), "default"


def vault_dir() -> str:
    """Return the configured vault directory.

    Resolution order:
      1. Path stored in ``$XDG_CONFIG_HOME/tephra/vault`` (or ``~/.config/...``)
      2. ``$XDG_DATA_HOME/tephra/vault`` (or ``~/.local/share/...``)
    """
    return vault_source()[0]


def write_config_vault(path: str) -> None:
    """Persist ``path`` as the vault location in the user config file."""
    target = os.path.expanduser(path)
    cfg = config_path()
    os.makedirs(os.path.dirname(cfg), exist_ok=True)
    with open(cfg, "w", encoding="utf-8") as f:
        f.write(target + "\n")


def write_config_default_folder(folder: str | None) -> None:
    """Persist ``folder`` as the default folder. Pass None/empty to clear."""
    cfg = default_folder_path()
    os.makedirs(os.path.dirname(cfg), exist_ok=True)
    if not folder:
        if os.path.isfile(cfg):
            os.unlink(cfg)
        return
    with open(cfg, "w", encoding="utf-8") as f:
        f.write(folder + "\n")


def lockfile() -> str:
    """Return the path to the per-vault lockfile."""
    return os.path.join(vault_dir(), ".tephra.lock")


def folder_dir(folder: str | None) -> str:
    """Return the directory that holds topic files for ``folder``.

    ``None`` (or empty) = vault root. Otherwise ``<vault>/<folder>``.
    """
    if not folder:
        return vault_dir()
    return os.path.join(vault_dir(), folder)


def topic_path(topic: str, folder: str | None = None) -> str:
    """Return the markdown file path for ``topic`` (no validation)."""
    return os.path.join(folder_dir(folder), f"{topic}.md")


def ensure_vault() -> None:
    """Create the vault directory if absent."""
    os.makedirs(vault_dir(), exist_ok=True)


@contextlib.contextmanager
def write_lock() -> Iterator[None]:
    """Hold an exclusive flock for the duration of a read-modify-write op."""
    ensure_vault()
    path = lockfile()
    fd = os.open(path, os.O_RDWR | os.O_CREAT, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        yield
    finally:
        fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)


def read_lines(path: str) -> list[str]:
    """Return file contents as a list of lines (with newlines)."""
    with open(path, encoding="utf-8") as f:
        return f.readlines()


def write_lines(path: str, lines: list[str]) -> None:
    """Atomic write via tempfile + rename in the same directory."""
    d = os.path.dirname(path) or "."
    os.makedirs(d, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".tephra.", dir=d)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.writelines(lines)
        os.replace(tmp, path)
    except Exception:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise


def compute_outside_fence(lines: list[str]) -> list[bool]:
    """Per-line booleans: True iff the line is outside any fenced code block."""
    out: list[bool] = []
    inside = False
    for line in lines:
        if _FENCE_PAT.match(line):
            out.append(False)
            inside = not inside
        else:
            out.append(not inside)
    return out


@dataclass
class Entry:
    """One H2-delimited entry inside a topic file."""

    topic: str
    date: str
    time: str | None
    title: str
    start: int
    end: int


def parse_entries(topic: str, lines: list[str]) -> list[Entry]:
    """Return all entries in ``lines`` for ``topic``."""
    outside = compute_outside_fence(lines)
    starts: list[tuple[int, str, str | None, str]] = []
    for i, line in enumerate(lines):
        if not outside[i]:
            continue
        m = ENTRY_PAT.match(line)
        if m:
            starts.append((i, m.group(1), m.group(2), m.group(3)))
    entries: list[Entry] = []
    for idx, (start, date, time_str, title) in enumerate(starts):
        end = starts[idx + 1][0] if idx + 1 < len(starts) else len(lines)
        entries.append(Entry(topic, date, time_str, title, start, end))
    return entries


def find_entry(topic: str, lines: list[str], date: str, title: str) -> Entry | None:
    """Return the entry matching ``date`` and ``title`` exactly, or None."""
    for e in parse_entries(topic, lines):
        if e.date == date and e.title == title:
            return e
    return None


def find_first_entry(lines: list[str]) -> int | None:
    """Index of the first H2 entry in ``lines``, or None."""
    outside = compute_outside_fence(lines)
    for i, line in enumerate(lines):
        if outside[i] and ENTRY_PAT.match(line):
            return i
    return None


def find_h1_end(lines: list[str]) -> int:
    """Return the line index immediately after the H1 block.

    Treats the H1 block as the first ``# Foo`` line plus a single trailing
    blank line if present. If no H1 is present, returns 0.
    """
    if not lines:
        return 0
    if not H1_PAT.match(lines[0]):
        return 0
    if len(lines) > 1 and not lines[1].strip():
        return 2
    return 1


def insertion_point(lines: list[str]) -> int:
    """Line index where a new entry should be inserted (above first H2)."""
    first = find_first_entry(lines)
    if first is not None:
        return first
    return find_h1_end(lines)


def _git(repo: str, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-C", repo, *args],
        check=check,
        capture_output=True,
        text=True,
    )


def init_repo(repo: str) -> None:
    """Init a git repo at ``repo`` if absent. Sets a local identity if missing."""
    os.makedirs(repo, exist_ok=True)
    if os.path.isdir(os.path.join(repo, ".git")):
        return
    _git(repo, "init", "-q", "-b", "main")
    if not _git(repo, "config", "user.email", check=False).stdout.strip():
        _git(repo, "config", "user.email", "tephra@localhost")
        _git(repo, "config", "user.name", "tephra")


def _origin_exists(repo: str) -> bool:
    """Return True iff the vault repo has a remote named ``origin``."""
    return _git(repo, "remote", "get-url", "origin", check=False).returncode == 0


def _rebase_in_progress(repo: str) -> bool:
    """Return True iff a git rebase is partway through in ``repo``."""
    git_dir = os.path.join(repo, ".git")
    return any(
        os.path.isdir(os.path.join(git_dir, d))
        for d in ("rebase-merge", "rebase-apply")
    )


def _has_unmerged_paths(repo: str) -> bool:
    """Return True iff the index has unmerged entries (stash-pop or merge conflicts)."""
    res = _git(repo, "ls-files", "--unmerged", check=False)
    return bool(res.stdout.strip())


def _abort_on_pending_conflict(repo: str) -> None:
    """Exit if a rebase is mid-flight or unmerged paths exist; otherwise return."""
    if not (_rebase_in_progress(repo) or _has_unmerged_paths(repo)):
        return
    sys.exit(
        f"tephra: vault {repo} has unresolved sync conflict. Resolve before retrying:\n"
        f"  git -C {repo} status\n"
        f"  # rebase in progress: git -C {repo} rebase --continue   # or --abort\n"
        f"  # stash-pop conflict: edit conflict markers, git add -A, git stash drop"
    )


def _pull_rebase(repo: str) -> bool:
    """Run ``git pull --rebase --autostash``.

    Returns True on clean pull. On rebase or stash-pop conflict, exits
    non-zero with a resolution hint and leaves the repo in the conflicted
    state. On network/other failure, prints a warning to stderr and
    returns False (caller continues with local commit).
    """
    res = _git(repo, "pull", "--rebase", "--autostash", check=False)
    if res.returncode != 0 and not (
        _rebase_in_progress(repo) or _has_unmerged_paths(repo)
    ):
        print(
            f"warning: tephra auto-sync pull failed (continuing offline): "
            f"{res.stderr.strip() or res.stdout.strip()}",
            file=sys.stderr,
        )
        return False
    if _rebase_in_progress(repo) or _has_unmerged_paths(repo):
        sys.stderr.write(res.stdout)
        sys.stderr.write(res.stderr)
        _write_sync_metric(False)
        _abort_on_pending_conflict(repo)
    return True


def _push(repo: str) -> bool:
    """Push HEAD to origin, setting upstream on first push.

    Returns True on success, False on failure (caller warns and continues).
    """
    upstream = _git(
        repo, "rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}", check=False
    )
    if upstream.returncode != 0:
        push = _git(repo, "push", "-u", "origin", "HEAD", check=False)
    else:
        push = _git(repo, "push", check=False)
    if push.returncode != 0:
        print(
            f"warning: tephra auto-sync push failed (local commit kept): "
            f"{push.stderr.strip() or push.stdout.strip()}",
            file=sys.stderr,
        )
        return False
    return True


def _write_sync_metric(ok: bool) -> None:
    """Atomically write Prometheus textfile gauges for the last sync attempt."""
    path = read_sync_metric_path()
    if not path:
        return
    vault = vault_dir().replace("\\", "\\\\").replace('"', '\\"')
    timestamp = int(time.time())
    content = (
        "# HELP tephra_sync_status 1 if last sync clean, 0 if conflict or push failure\n"
        "# TYPE tephra_sync_status gauge\n"
        f'tephra_sync_status{{vault="{vault}"}} {1 if ok else 0}\n'
        "# HELP tephra_sync_last_attempt Unix timestamp of last sync attempt\n"
        "# TYPE tephra_sync_last_attempt gauge\n"
        f'tephra_sync_last_attempt{{vault="{vault}"}} {timestamp}\n'
    )
    try:
        directory = os.path.dirname(path) or "."
        os.makedirs(directory, exist_ok=True)
        fd, tmp = tempfile.mkstemp(prefix=".tephra_sync.", dir=directory)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(content)
            os.replace(tmp, path)
        except Exception:
            if os.path.exists(tmp):
                os.unlink(tmp)
            raise
    except OSError as e:
        print(f"warning: tephra metric write failed: {e}", file=sys.stderr)


def _stage_and_commit(repo: str, message: str) -> bool:
    """Stage everything and commit with ``message``. Return True if a commit was made."""
    _git(repo, "add", "-A")
    cached = _git(repo, "diff", "--cached", "--quiet", check=False)
    if cached.returncode == 0:
        return False
    _git(repo, "commit", "-q", "-m", message)
    return True


def _sync_aware_commit(repo: str, message: str) -> bool:
    """Pre-pull (if sync on), stage+commit, post-push (if sync on, and a commit was made).

    Returns True if a commit was created, False if the working tree was clean.
    Pull conflicts exit non-zero. Network/push failures warn but return normally.
    """
    sync_enabled = read_auto_sync() and _origin_exists(repo)
    pull_ok = True
    if sync_enabled:
        _abort_on_pending_conflict(repo)
        pull_ok = _pull_rebase(repo)
    committed = _stage_and_commit(repo, message)
    if not committed:
        if sync_enabled:
            _write_sync_metric(pull_ok)
        return False
    if sync_enabled:
        push_ok = _push(repo)
        _write_sync_metric(pull_ok and push_ok)
    return True


def capture_manual_edits() -> None:
    """Commit any uncommitted vault changes as 'manual edit (captured)'.

    Auto-syncs (pull/push) when enabled and a commit will be made.
    """
    repo = vault_dir()
    if not os.path.isdir(os.path.join(repo, ".git")):
        return
    try:
        diff = _git(repo, "diff", "--quiet", "HEAD", check=False)
        untracked = _git(
            repo, "ls-files", "--others", "--exclude-standard", check=False
        ).stdout.strip()
        if diff.returncode == 0 and not untracked:
            return
        if _sync_aware_commit(repo, "manual edit (captured)"):
            print(f"note: captured manual edit in {repo}", file=sys.stderr)
    except (subprocess.CalledProcessError, FileNotFoundError) as e:
        print(f"warning: capture_manual_edits failed: {e}", file=sys.stderr)


def cmd_manual_commit(message: str) -> None:
    """Stage all vault changes and commit with ``message``. Exit non-zero if clean."""
    repo = vault_dir()
    init_repo(repo)
    try:
        if not _sync_aware_commit(repo, message):
            sys.exit("nothing to commit")
        print(f"committed manual edit: {message}")
    except (subprocess.CalledProcessError, FileNotFoundError) as e:
        sys.exit(f"manual-commit failed: {e}")


def git_snapshot(message: str) -> None:
    """Stage everything in the vault and commit. Best-effort; no-op if clean."""
    repo = vault_dir()
    try:
        init_repo(repo)
        _sync_aware_commit(repo, message)
    except (subprocess.CalledProcessError, FileNotFoundError) as e:
        print(f"warning: git snapshot failed: {e}", file=sys.stderr)
