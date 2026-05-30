"""Read-only commands: show, find, within, list, last, log, diff."""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime, timedelta

from .dates import parse_date_arg
from .related import find_related_line, split_related_links
from .store import (
    AUTHOR_PAT,
    Entry,
    RELATED_PAT,
    parse_entries,
    read_default_folder,
    read_lines,
    topic_path,
    vault_dir,
)
from .topics import list_topics, validate_topic


@dataclass
class HydratedEntry:
    """An ``Entry`` plus the body lines belonging to it."""

    entry: Entry
    body: list[str]
    folder: str | None = None


def _hydrate(topic: str, lines: list[str], folder: str | None) -> list[HydratedEntry]:
    return [
        HydratedEntry(e, lines[e.start + 1 : e.end], folder)
        for e in parse_entries(topic, lines)
    ]


def _sort_key(h: HydratedEntry) -> tuple[str, str]:
    return (h.entry.date, h.entry.time or "")


def _resolve_scope(
    folder: str | None, topic: str | None
) -> list[tuple[str | None, str]]:
    """Expand ``(folder, topic)`` into a list of ``(folder, topic)`` pairs.

    With a topic, scope is that one topic in the resolved folder. Without
    a topic, scope is all topics in ``folder`` (or the default folder if
    no folder was given).
    """
    if topic is not None:
        return [(folder, topic)]
    target_folder = folder if folder is not None else read_default_folder()
    return [(target_folder, t) for t in list_topics(target_folder)]


def _all_entries(folder: str | None, topic: str | None) -> list[HydratedEntry]:
    """Return entries for the resolved scope, sorted newest first."""
    out: list[HydratedEntry] = []
    for f, t in _resolve_scope(folder, topic):
        path = topic_path(t, f)
        if not os.path.isfile(path):
            continue
        out.extend(_hydrate(t, read_lines(path), f))
    out.sort(key=_sort_key, reverse=True)
    return out


def _find_author_line(body: list[str]) -> int | None:
    for i, line in enumerate(body):
        if AUTHOR_PAT.match(line):
            return i
    return None


def _body_content(body: list[str]) -> list[str]:
    """Return body with trailing Related and author lines stripped."""
    cut = len(body)
    a = _find_author_line(body)
    if a is not None:
        cut = min(cut, a)
    r = find_related_line(body[:cut])
    if r is not None:
        cut = min(cut, r)
    out = list(body[:cut])
    while out and not out[-1].strip():
        out.pop()
    return out


def _related_links(body: list[str]) -> list[str]:
    idx = find_related_line(body)
    if idx is None:
        return []
    m = RELATED_PAT.match(body[idx])
    if not m:
        return []
    return split_related_links(m.group(1))


def _author(body: list[str]) -> str | None:
    idx = _find_author_line(body)
    if idx is None:
        return None
    m = AUTHOR_PAT.match(body[idx])
    return m.group(1) if m else None


def _entry_label(h: HydratedEntry) -> str:
    if h.folder:
        return f"{h.folder}:{h.entry.topic}"
    return h.entry.topic


def _entry_dict(h: HydratedEntry) -> dict:
    return {
        "folder": h.folder,
        "topic": h.entry.topic,
        "date": h.entry.date,
        "time": h.entry.time,
        "title": h.entry.title,
        "body": "".join(_body_content(h.body)).strip(),
        "related": _related_links(h.body),
        "author": _author(h.body),
    }


def _print_entry(h: HydratedEntry) -> None:
    ts = f" {h.entry.time}" if h.entry.time else ""
    print(f"[{_entry_label(h)}] ## {h.entry.date}{ts} — {h.entry.title}")
    text = "".join(h.body).rstrip()
    if text:
        print(text)


def _validate_scope(folder: str | None, topic: str | None) -> None:
    """Validate folder/topic pair if topic is specified."""
    if topic is None:
        return
    validate_topic(folder, topic)


_DURATION_UNITS = {
    "s": "seconds",
    "m": "minutes",
    "h": "hours",
    "d": "days",
    "w": "weeks",
}
_DURATION_RE = re.compile(r"^(\d+)([smhdw])$")


def parse_duration(spec: str) -> timedelta:
    """Parse a duration string like ``30m``, ``12h``, ``4d``, ``2w``."""
    m = _DURATION_RE.match(spec)
    if not m:
        sys.exit(
            f"Invalid duration {spec!r}. Use N followed by s/m/h/d/w "
            "(e.g. 30m, 12h, 4d, 2w)."
        )
    n, unit = int(m.group(1)), m.group(2)
    if n == 0:
        sys.exit(f"Duration must be > 0, got {spec!r}")
    return timedelta(**{_DURATION_UNITS[unit]: n})


def _entry_datetime(h: HydratedEntry) -> datetime:
    t = h.entry.time or "00:00"
    return datetime.strptime(f"{h.entry.date} {t}", "%Y-%m-%d %H:%M")


def cmd_show(
    date_arg: str, folder: str | None, topic: str | None, json_out: bool
) -> None:
    """Print all entries on a given date (across topics, or one topic)."""
    _validate_scope(folder, topic)
    target = parse_date_arg(date_arg)
    matches = [h for h in _all_entries(folder, topic) if h.entry.date == target]
    if json_out:
        print(json.dumps([_entry_dict(h) for h in matches], indent=2))
        return
    if not matches:
        sys.exit(f"No entries on {target}")
    for i, h in enumerate(matches):
        if i > 0:
            print()
        _print_entry(h)


def _find_haystack(h: HydratedEntry, field: str) -> str:
    """Return the lowercased haystack for ``cmd_find`` based on ``field`` scope."""
    if field == "title":
        return h.entry.title.lower()
    body = "".join(_body_content(h.body))
    if field == "body":
        return body.lower()
    return (h.entry.title + "\n" + body).lower()


def _matches_find(
    h: HydratedEntry, terms_lower: list[str], cutoff: datetime | None, field: str
) -> bool:
    """Predicate for ``cmd_find``: all terms match (AND) within optional time window."""
    if cutoff is not None and _entry_datetime(h) < cutoff:
        return False
    haystack = _find_haystack(h, field)
    return all(t in haystack for t in terms_lower)


def _collect_find_matches(
    folder: str | None,
    topic: str | None,
    terms: list[str],
    cutoff: datetime | None,
    field: str,
    limit: int | None,
) -> list[HydratedEntry]:
    terms_lower = [t.lower() for t in terms]
    matches = [
        h
        for h in _all_entries(folder, topic)
        if _matches_find(h, terms_lower, cutoff, field)
    ]
    if limit is not None and limit >= 0:
        matches = matches[:limit]
    return matches


def cmd_find(
    terms: list[str],
    folder: str | None,
    topic: str | None,
    json_out: bool,
    cutoff: datetime | None,
    field: str = "both",
    limit: int | None = None,
) -> None:
    """Print entries matching all terms (case-insensitive AND), newest first."""
    _validate_scope(folder, topic)
    matches = _collect_find_matches(folder, topic, terms, cutoff, field, limit)
    if json_out:
        print(json.dumps([_entry_dict(h) for h in matches], indent=2))
        return
    if not matches:
        sys.exit(f"No entries matching {' '.join(repr(t) for t in terms)}")
    for i, h in enumerate(matches):
        if i > 0:
            print()
        _print_entry(h)


def cmd_within(
    duration: str, folder: str | None, topic: str | None, json_out: bool
) -> None:
    """Print entries within the last ``duration`` (e.g. ``12h``, ``4d``)."""
    _validate_scope(folder, topic)
    cutoff = datetime.now() - parse_duration(duration)
    matches = [h for h in _all_entries(folder, topic) if _entry_datetime(h) >= cutoff]
    if json_out:
        print(json.dumps([_entry_dict(h) for h in matches], indent=2))
        return
    if not matches:
        print(f"No entries within {duration}")
        return
    for i, h in enumerate(matches):
        if i > 0:
            print()
        _print_entry(h)


def cmd_list(folder: str | None, topic: str | None, json_out: bool) -> None:
    """Print all entry headings (no bodies)."""
    _validate_scope(folder, topic)
    entries = _all_entries(folder, topic)
    if json_out:
        out = [
            {
                "folder": h.folder,
                "topic": h.entry.topic,
                "date": h.entry.date,
                "time": h.entry.time,
                "title": h.entry.title,
            }
            for h in entries
        ]
        print(json.dumps(out, indent=2))
        return
    if not entries:
        print("No entries")
        return
    for h in entries:
        ts = f" {h.entry.time}" if h.entry.time else ""
        print(f"[{_entry_label(h)}] {h.entry.date}{ts} — {h.entry.title}")


def cmd_last(folder: str | None, topic: str | None, json_out: bool) -> None:
    """Print the newest entry (across topics, or one topic)."""
    _validate_scope(folder, topic)
    entries = _all_entries(folder, topic)
    if not entries:
        sys.exit("No entries")
    h = entries[0]
    if json_out:
        print(json.dumps(_entry_dict(h), indent=2))
        return
    _print_entry(h)


def _ensure_repo() -> str:
    repo = vault_dir()
    if not os.path.isdir(os.path.join(repo, ".git")):
        sys.exit(f"No git repo in vault {repo}")
    return repo


def cmd_log(n: int) -> None:
    """Print the last ``n`` commits from the vault repo."""
    repo = _ensure_repo()
    subprocess.run(["git", "-C", repo, "log", f"-{n}", "--oneline"], check=True)


def cmd_diff(ref: str) -> None:
    """``git show REF`` for the vault repo."""
    repo = _ensure_repo()
    subprocess.run(["git", "-C", repo, "show", ref], check=True)
