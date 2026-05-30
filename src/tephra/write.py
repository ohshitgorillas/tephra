"""Write commands: add, amend, addend, retitle, rm, undo."""

from __future__ import annotations

import os
import re
import subprocess
import sys

from .dates import now_time, parse_date_arg, today_iso
from .related import (
    find_related_line,
    format_related_line,
    parse_link_arg,
    split_related_links,
    validate_link,
)
from .store import (
    AUTHOR_PAT,
    Entry,
    RELATED_PAT,
    find_entry,
    git_snapshot,
    insertion_point,
    parse_entries,
    read_lines,
    topic_path,
    vault_dir,
    write_lines,
    write_lock,
)
from .topics import iter_all_topic_paths, validate_topic


def _label(folder: str | None, topic: str) -> str:
    return f"{folder}:{topic}" if folder else topic


_HTML_TAG_PAT = re.compile(r"(?<!`)<([a-zA-Z][A-Za-z0-9_-]*)>(?!`)")


def _backtick_html_tags_in_line(line: str) -> str:
    """Wrap bare ``<htmltag>`` tokens in backticks (skip already-backticked)."""
    return _HTML_TAG_PAT.sub(r"`<\1>`", line)


def auto_backtick_html_tags(text: str) -> str:
    """Apply auto-backticking to body text, skipping fenced code blocks."""
    out: list[str] = []
    inside = False
    for line in text.splitlines():
        if line.startswith("```") or line.startswith("~~~"):
            inside = not inside
            out.append(line)
        elif inside:
            out.append(line)
        else:
            out.append(_backtick_html_tags_in_line(line))
    return "\n".join(out)


def _resolve_target(
    topic: str, lines: list[str], date_arg: str | None, title: str | None
) -> Entry:
    """Locate a target entry in ``topic`` for amend/addend.

    With ``-d`` and ``-t``, locate that exact entry. Otherwise return the
    newest entry in the topic file. Exits on miss.
    """
    if date_arg or title:
        if not (date_arg and title):
            sys.exit("--date and --title must be used together")
        date = parse_date_arg(date_arg)
        found = find_entry(topic, lines, date, title)
        if found is None:
            sys.exit(f"No entry '{title}' on {date} in topic '{topic}'")
        return found
    entries = parse_entries(topic, lines)
    if not entries:
        sys.exit(f"No entries in topic '{topic}'")
    return entries[0]


def _format_author_line(name: str) -> str:
    return f"_author: {name}_"


def _build_block(
    date: str,
    time: str,
    title: str,
    body: str,
    related_line: str | None,
    author: str | None,
) -> list[str]:
    """Build the lines for a new entry, ready to splice into a topic file."""
    out: list[str] = [f"## {date} {time} — {title}\n", "\n"]
    body = auto_backtick_html_tags(body).strip("\n")
    if body:
        for line in body.splitlines():
            out.append(line + "\n")
        out.append("\n")
    if related_line:
        out.append(related_line + "\n")
        out.append("\n")
    if author:
        out.append(_format_author_line(author) + "\n")
        out.append("\n")
    return out


def insert_entry(
    folder: str | None,
    topic: str,
    title: str,
    body: str,
    related_refs: list[str] | None,
    author: str | None = None,
) -> None:
    """Add a new entry at the top of ``topic.md``."""
    validate_topic(folder, topic)
    related_line = format_related_line(related_refs) if related_refs else None
    path = topic_path(topic, folder)
    date = today_iso()
    time = now_time()
    label = _label(folder, topic)
    with write_lock():
        if not os.path.isfile(path):
            sys.exit(f"Topic file missing at {path}")
        lines = read_lines(path)
        if find_entry(topic, lines, date, title) is not None:
            sys.exit(
                f"Entry '{title}' already exists on {date} in topic '{label}'. "
                f"Use a different title or `tephra amend`/`addend`."
            )
        block = _build_block(date, time, title, body, related_line, author)
        pos = insertion_point(lines)
        if pos > 0 and lines[pos - 1].strip() != "":
            block = ["\n"] + block
        lines = lines[:pos] + block + lines[pos:]
        write_lines(path, lines)
        git_snapshot(f"add: [{label}] {title}")
    print(f"Added: [{label}] {date} ({time}) — {title}")


def _entry_body_lines(lines: list[str], entry: Entry) -> list[str]:
    """Return the body lines of ``entry``."""
    return lines[entry.start + 1 : entry.end]


def _strip_trailing_blanks(lines: list[str]) -> list[str]:
    while lines and not lines[-1].strip():
        lines.pop()
    return lines


def _existing_related(body_lines: list[str]) -> str | None:
    """Return the existing ``**Related:**`` line (no trailing newline) or None."""
    for line in body_lines:
        if RELATED_PAT.match(line):
            return line.rstrip("\n")
    return None


def _existing_author(body_lines: list[str]) -> str | None:
    """Return the existing author name, or None."""
    for line in body_lines:
        m = AUTHOR_PAT.match(line)
        if m:
            return m.group(1)
    return None


def _build_body_block(
    body_text: str, related_line: str | None, author: str | None
) -> list[str]:
    """Build the new-body section (leading blank, content, optional Related/author lines)."""
    out: list[str] = ["\n"]
    body = auto_backtick_html_tags(body_text).strip("\n")
    if body:
        for line in body.splitlines():
            out.append(line + "\n")
        out.append("\n")
    if related_line:
        out.append(related_line + "\n")
        out.append("\n")
    if author:
        out.append(_format_author_line(author) + "\n")
        out.append("\n")
    return out


def cmd_amend(
    folder: str | None,
    topic: str,
    new_text: str,
    date_arg: str | None = None,
    title: str | None = None,
    related_refs: list[str] | None = None,
    author: str | None = None,
) -> None:
    """Replace the body of an entry, preserving the heading.

    Existing Related and author lines are preserved unless overridden by
    ``related_refs`` or ``author``.
    """
    validate_topic(folder, topic)
    new_related_line = format_related_line(related_refs) if related_refs else None
    path = topic_path(topic, folder)
    label = _label(folder, topic)
    with write_lock():
        lines = read_lines(path)
        entry = _resolve_target(topic, lines, date_arg, title)
        body_lines = _entry_body_lines(lines, entry)
        related_line = (
            new_related_line
            if new_related_line is not None
            else _existing_related(body_lines)
        )
        author_name = author if author is not None else _existing_author(body_lines)
        new_body = _build_body_block(new_text, related_line, author_name)
        lines = lines[: entry.start + 1] + new_body + lines[entry.end :]
        write_lines(path, lines)
        git_snapshot(f"amend: [{label}] {entry.title}")
    print(f"Amended: [{label}] {entry.date} — {entry.title}")


def _split_body_at_meta(
    body: list[str],
) -> tuple[list[str], list[str], str | None]:
    """Return ``(content_before_meta, existing_related_links, existing_author)``."""
    author_name: str | None = None
    cut = len(body)
    for i, line in enumerate(body):
        m = AUTHOR_PAT.match(line)
        if m:
            author_name = m.group(1)
            cut = min(cut, i)
            break
    head = body[:cut]
    related_idx = find_related_line(head)
    if related_idx is None:
        return list(head), [], author_name
    m = RELATED_PAT.match(head[related_idx])
    links = split_related_links(m.group(1)) if m else []
    return list(head[:related_idx]), links, author_name


def _append_paragraph(content: list[str], paragraph: str) -> list[str]:
    """Append ``paragraph`` (auto-backticked) to ``content`` with separating blank."""
    text = auto_backtick_html_tags(paragraph).strip("\n")
    if not text:
        return content
    out = _strip_trailing_blanks(content)
    out.append("\n")
    for line in text.splitlines():
        out.append(line + "\n")
    out.append("\n")
    return out


def _merge_related_links(existing: list[str], refs: list[str]) -> list[str]:
    """Return ``existing`` extended with validated refs, deduped (order-preserving)."""
    new_links: list[str] = []
    for ref in refs:
        folder_r, topic_r, date_r, time_r, title_r = parse_link_arg(ref)
        anchor = validate_link(folder_r, topic_r, date_r, time_r, title_r)
        head = f"{folder_r}:{topic_r}" if folder_r else topic_r
        new_links.append(f"[[{head}#{anchor}]]")
    out = list(existing)
    seen = set(out)
    for link in new_links:
        if link not in seen:
            out.append(link)
            seen.add(link)
    return out


def _related_tail(links: list[str]) -> list[str]:
    """Return the lines for a Related-line tail, or [] if no links."""
    if not links:
        return []
    return ["**Related:** " + ", ".join(links) + "\n", "\n"]


def _author_tail(name: str | None) -> list[str]:
    if not name:
        return []
    return [_format_author_line(name) + "\n", "\n"]


def cmd_addend(
    folder: str | None,
    topic: str,
    new_text: str,
    date_arg: str | None = None,
    title: str | None = None,
    related_refs: list[str] | None = None,
    author: str | None = None,
) -> None:
    """Append a paragraph to an entry's body (above any Related/author lines).

    If ``related_refs`` is given, each ref is appended to the existing
    Related line (deduped). If ``author`` is given, the author line is
    set/replaced; otherwise the existing author is preserved.
    """
    validate_topic(folder, topic)
    path = topic_path(topic, folder)
    label = _label(folder, topic)
    with write_lock():
        lines = read_lines(path)
        entry = _resolve_target(topic, lines, date_arg, title)
        content, links, existing_author = _split_body_at_meta(
            _entry_body_lines(lines, entry)
        )
        content = _append_paragraph(content, new_text)
        if related_refs:
            links = _merge_related_links(links, related_refs)
        author_name = author if author is not None else existing_author
        new_body = content + _related_tail(links) + _author_tail(author_name)
        if not new_body or new_body[-1].strip():
            new_body.append("\n")
        lines = lines[: entry.start + 1] + new_body + lines[entry.end :]
        write_lines(path, lines)
        git_snapshot(f"addend: [{label}] {entry.title}")
    print(f"Added to: [{label}] {entry.date} — {entry.title}")


def cmd_retitle(
    folder: str | None,
    topic: str,
    date_arg: str,
    old_title: str,
    new_title: str,
) -> None:
    """Rename an entry in place, preserving date and time. Also rewrites
    inbound ``[[...]]`` links across the vault so cross-references don't rot.
    """
    validate_topic(folder, topic)
    date = parse_date_arg(date_arg)
    path = topic_path(topic, folder)
    label = _label(folder, topic)
    with write_lock():
        lines = read_lines(path)
        entry = find_entry(topic, lines, date, old_title)
        if entry is None:
            sys.exit(f"No entry '{old_title}' on {date} in topic '{label}'")
        ts = f" {entry.time}" if entry.time else ""
        lines[entry.start] = f"## {entry.date}{ts} — {new_title}\n"
        write_lines(path, lines)
        link_count, file_count = _rewrite_inbound_links(
            folder, topic, date, old_title, new_title
        )
        link_word = "link" if link_count == 1 else "links"
        topic_word = "topic" if file_count == 1 else "topics"
        suffix = (
            f" ({link_count} {link_word} in {file_count} {topic_word})"
            if link_count
            else ""
        )
        git_snapshot(f"retitle: [{label}] {old_title} -> {new_title}{suffix}")
    print(f"Retitled: [{label}] {old_title} -> {new_title}{suffix}")


def _rewrite_inbound_links(
    folder: str | None,
    topic: str,
    date: str,
    old_title: str,
    new_title: str,
) -> tuple[int, int]:
    """Swap title in every ``[[...#date [time] — old_title]]`` across the vault.

    Bare ``[[Topic#...]]`` matches only rewrite in files within the same folder
    as the retitled topic (bare references resolve folder-locally).
    Folder-qualified ``[[Folder:Topic#...]]`` matches rewrite vault-wide.
    """
    date_re = re.escape(date)
    title_re = re.escape(old_title)
    qualified_head = f"{folder}:{topic}" if folder else topic
    qualified_pat = re.compile(
        rf"\[\[{re.escape(qualified_head)}#({date_re}(?: \d{{2}}:\d{{2}})?) — {title_re}\]\]"
    )
    bare_pat = re.compile(
        rf"\[\[{re.escape(topic)}#({date_re}(?: \d{{2}}:\d{{2}})?) — {title_re}\]\]"
    )
    qualified_repl = rf"[[{qualified_head}#\1 — {new_title}]]"
    bare_repl = rf"[[{topic}#\1 — {new_title}]]"

    total_links = 0
    files_touched = 0
    for f, _t, abs_path in iter_all_topic_paths():
        try:
            with open(abs_path, encoding="utf-8") as fh:
                text = fh.read()
        except OSError:
            continue
        new_text, q_count = qualified_pat.subn(qualified_repl, text)
        b_count = 0
        if f == folder:
            new_text, b_count = bare_pat.subn(bare_repl, new_text)
        delta = q_count + b_count
        if delta == 0:
            continue
        write_lines(abs_path, new_text.splitlines(keepends=True))
        total_links += delta
        files_touched += 1
    return total_links, files_touched


def cmd_rm(
    folder: str | None,
    topic: str,
    date_arg: str,
    title: str,
    dry_run: bool = False,
) -> None:
    """Delete an entry from a topic file."""
    validate_topic(folder, topic)
    date = parse_date_arg(date_arg)
    path = topic_path(topic, folder)
    label = _label(folder, topic)

    def _impl() -> None:
        lines = read_lines(path)
        entry = find_entry(topic, lines, date, title)
        if entry is None:
            sys.exit(f"No entry '{title}' on {date} in topic '{label}'")
        new_lines = lines[: entry.start] + lines[entry.end :]
        if dry_run:
            print(f"Would remove '{title}' on {date} from topic '{label}'")
            print("--- entry content ---")
            print("".join(lines[entry.start : entry.end]).rstrip())
            return
        write_lines(path, new_lines)
        git_snapshot(f"rm: [{label}] {title}")
        print(f"Removed '{title}' on {date} from topic '{label}'")

    if dry_run:
        _impl()
    else:
        with write_lock():
            _impl()


def cmd_undo() -> None:
    """Revert the most recent commit in the vault repo."""
    repo = vault_dir()
    if not os.path.isdir(os.path.join(repo, ".git")):
        sys.exit(f"No git repo in vault {repo} — nothing to undo")
    head_subj = subprocess.run(
        ["git", "-C", repo, "log", "-1", "--format=%s"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    with write_lock():
        subprocess.run(
            ["git", "-C", repo, "revert", "HEAD", "--no-edit"],
            check=True,
        )
    print(f"Undid: {head_subj}")
