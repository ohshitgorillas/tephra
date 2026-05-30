"""Command-line interface: argparse subcommands dispatched to read/write helpers."""

from __future__ import annotations

import argparse
import sys
from datetime import datetime

from . import __version__
from .read import (
    cmd_diff,
    cmd_find,
    cmd_last,
    cmd_list,
    cmd_log,
    cmd_show,
    cmd_within,
    parse_duration,
)
from .skill import cmd_skill_install, cmd_skill_path, cmd_skill_print
from .store import capture_manual_edits, cmd_manual_commit
from .topics import (
    cmd_config_auto_sync,
    cmd_config_default_folder,
    cmd_config_path,
    cmd_config_show,
    cmd_config_sync_metric,
    cmd_config_vault,
    cmd_folder_list,
    cmd_topic_add,
    cmd_topic_list,
    parse_topic_arg,
)
from .write import (
    cmd_addend,
    cmd_amend,
    cmd_retitle,
    cmd_rm,
    cmd_undo,
    insert_entry,
)


def _resolve_bodies(entries: list[str]) -> str:
    """Resolve a list of ``-e/--entry`` values into a single body string.

    At most one ``-`` is permitted (stdin is read once and substituted in
    place). Empty values are silently dropped from the join, so a single
    ``-e ""`` produces an empty body (matching the legacy single-flag
    behavior, which downstream callers like ``addend`` use to extend the
    Related line without adding a paragraph). Non-empty values are joined
    with a single blank line between them, producing distinct paragraphs.
    """
    if not entries:
        sys.exit("at least one -e/--entry value is required")
    stdin_slots = sum(1 for e in entries if e == "-")
    if stdin_slots > 1:
        sys.exit("only one -e/--entry value may be `-` (stdin is read once)")
    stdin_value = sys.stdin.read() if stdin_slots == 1 else ""
    pieces = [stdin_value if raw == "-" else raw for raw in entries]
    return "\n\n".join(p for p in pieces if p)


def _parse_topic(arg: str | None) -> tuple[str | None, str | None]:
    """Parse a ``-T`` value into ``(folder, topic)``. ``None`` arg → both None."""
    if arg is None:
        return None, None
    return parse_topic_arg(arg)


def _add_write_subparsers(sub: argparse._SubParsersAction) -> None:
    body_help = (
        "paragraph body; repeat for multiple paragraphs joined with a blank line "
        "(use `-` for stdin)"
    )

    p_add = sub.add_parser("add", help="add new entry to a topic")
    p_add.add_argument("-T", "--topic", required=True)
    p_add.add_argument("-t", "--title", required=True)
    p_add.add_argument(
        "-e",
        "--entry",
        required=True,
        action="append",
        default=[],
        metavar="BODY",
        help=body_help,
    )
    p_add.add_argument(
        "--related",
        action="append",
        default=[],
        metavar="REF",
        help="cross-link: 'Topic#YYYY-MM-DD [HH:MM] — Title' (repeatable)",
    )
    p_add.add_argument(
        "--author",
        metavar="NAME",
        help="author name appended as '_author: NAME_' line at bottom of entry",
    )

    p_amend = sub.add_parser(
        "amend", help="replace body of entry (newest in topic by default)"
    )
    p_amend.add_argument("-T", "--topic", required=True)
    p_amend.add_argument(
        "-e",
        "--entry",
        required=True,
        action="append",
        default=[],
        metavar="BODY",
        help=body_help,
    )
    p_amend.add_argument("-d", "--date")
    p_amend.add_argument("-t", "--title")
    p_amend.add_argument(
        "--related",
        action="append",
        default=[],
        metavar="REF",
        help="rewrite Related line with these refs (repeatable)",
    )
    p_amend.add_argument(
        "--author",
        metavar="NAME",
        help="rewrite author line with NAME (default: preserve existing)",
    )

    p_addend = sub.add_parser(
        "addend", help="append paragraph to entry (newest in topic by default)"
    )
    p_addend.add_argument("-T", "--topic", required=True)
    p_addend.add_argument(
        "-e",
        "--entry",
        required=True,
        action="append",
        default=[],
        metavar="BODY",
        help=body_help,
    )
    p_addend.add_argument("-d", "--date")
    p_addend.add_argument("-t", "--title")
    p_addend.add_argument(
        "--related",
        action="append",
        default=[],
        metavar="REF",
        help="append refs to Related line, deduped (repeatable)",
    )
    p_addend.add_argument(
        "--author",
        metavar="NAME",
        help="set/replace author line with NAME (default: preserve existing)",
    )

    p_retitle = sub.add_parser("retitle", help="rename existing entry")
    p_retitle.add_argument("-T", "--topic", required=True)
    p_retitle.add_argument("-d", "--date", required=True)
    p_retitle.add_argument("-t", "--title", required=True, help="current title")
    p_retitle.add_argument("--to", required=True, help="new title", dest="new_title")

    p_rm = sub.add_parser("rm", help="delete entry from a topic")
    p_rm.add_argument("-T", "--topic", required=True)
    p_rm.add_argument("-d", "--date", required=True)
    p_rm.add_argument("-t", "--title", required=True)
    p_rm.add_argument(
        "-n",
        "--dry-run",
        action="store_true",
        help="print what would be removed without writing",
    )


def _add_read_subparsers(sub: argparse._SubParsersAction) -> None:
    p_show = sub.add_parser("show", help="print entries on a date")
    p_show.add_argument("date", metavar="DATE", help="YYYY-MM-DD, YYYYMMDD, or MMDD")
    p_show.add_argument("-T", "--topic", help="restrict to a single topic")
    p_show.add_argument("--json", action="store_true", dest="json_out")

    p_find = sub.add_parser(
        "find",
        help="search entries (case-insensitive; multiple terms = AND)",
    )
    p_find.add_argument(
        "term",
        nargs="+",
        help="one or more terms; all must match (AND)",
    )
    p_find.add_argument("-T", "--topic")
    p_find.add_argument("--json", action="store_true", dest="json_out")
    p_find.add_argument(
        "--in",
        dest="field",
        choices=("title", "body", "both"),
        default="both",
        help="which field to search (default: both)",
    )
    p_find.add_argument(
        "--limit",
        type=int,
        metavar="N",
        help="cap output to N newest matches",
    )
    p_find.add_argument(
        "--within",
        metavar="DURATION",
        help="restrict to entries within the last DURATION (e.g. 30m, 12h, 2d, 2w)",
    )

    p_within = sub.add_parser(
        "within",
        help="entries within the last DURATION (e.g. 30m, 12h, 4d, 2w)",
    )
    p_within.add_argument("duration", metavar="DURATION")
    p_within.add_argument("-T", "--topic")
    p_within.add_argument("--json", action="store_true", dest="json_out")

    p_list = sub.add_parser("list", help="print all entry headings (no bodies)")
    p_list.add_argument("-T", "--topic")
    p_list.add_argument("--json", action="store_true", dest="json_out")

    p_last = sub.add_parser("last", help="print newest entry")
    p_last.add_argument("-T", "--topic")
    p_last.add_argument("--json", action="store_true", dest="json_out")


def _add_topic_subparsers(sub: argparse._SubParsersAction) -> None:
    p_topic = sub.add_parser("topic", help="topic management")
    topic_sub = p_topic.add_subparsers(dest="topic_cmd", metavar="SUBCOMMAND")
    p_tlist = topic_sub.add_parser("list", help="print known topics")
    p_tlist.add_argument(
        "-F", "--folder", help="folder to list (default: configured default folder)"
    )
    p_tadd = topic_sub.add_parser("add", help="create a new topic file")
    p_tadd.add_argument("name")
    p_tadd.add_argument(
        "-F",
        "--folder",
        help="folder to create in (default: configured default folder)",
    )


def _add_folder_subparsers(sub: argparse._SubParsersAction) -> None:
    p_folder = sub.add_parser("folder", help="folder management")
    folder_sub = p_folder.add_subparsers(dest="folder_cmd", metavar="SUBCOMMAND")
    folder_sub.add_parser("list", help="print folder names (vault subdirectories)")


def _add_config_subparsers(sub: argparse._SubParsersAction) -> None:
    p_config = sub.add_parser("config", help="vault location configuration")
    config_sub = p_config.add_subparsers(dest="config_cmd", metavar="SUBCOMMAND")
    p_vault = config_sub.add_parser("vault", help="set the vault path")
    p_vault.add_argument("path", help="vault directory")
    p_default_folder = config_sub.add_parser(
        "default-folder",
        help="set or clear the default folder (use empty string to clear)",
    )
    p_default_folder.add_argument(
        "folder", help="folder name (empty string clears default → vault root)"
    )
    p_auto_sync = config_sub.add_parser(
        "auto-sync",
        help="enable/disable git pull --rebase before, push after every write",
    )
    p_auto_sync.add_argument("value", choices=("on", "off"))
    p_sync_metric = config_sub.add_parser(
        "sync-metric",
        help="set or clear the Prometheus textfile output for sync status",
    )
    p_sync_metric.add_argument(
        "path", help="output path (empty string clears, disabling the metric)"
    )
    config_sub.add_parser("show", help="print resolved vault path + source")
    config_sub.add_parser(
        "path", help="print resolved vault path only (for shell scripting)"
    )


def _add_skill_subparser(sub: argparse._SubParsersAction) -> None:
    p_skill = sub.add_parser(
        "skill",
        help="print or install the bundled Claude Code skill file",
    )
    g = p_skill.add_mutually_exclusive_group()
    g.add_argument(
        "--install",
        nargs="?",
        const="",
        metavar="DIR",
        help=(
            "write SKILL.md to DIR/skills/tephra/SKILL.md "
            "(default DIR: $CLAUDE_PROJECT_DIR/.claude or ~/.claude)"
        ),
    )
    g.add_argument(
        "--path",
        action="store_true",
        help="print the on-disk path of the bundled SKILL.md and exit",
    )


def _add_repo_subparsers(sub: argparse._SubParsersAction) -> None:
    p_log = sub.add_parser("log", help="show vault repo commit history")
    p_log.add_argument("n", nargs="?", type=int, default=20)

    p_diff = sub.add_parser("diff", help="show vault repo commit diff")
    p_diff.add_argument("ref", nargs="?", default="HEAD")

    sub.add_parser("undo", help="revert last commit in the vault repo")

    p_manual = sub.add_parser(
        "manual-commit",
        help="commit pending vault edits with a custom message",
    )
    p_manual.add_argument("message", help="commit message")


def build_parser() -> argparse.ArgumentParser:
    """Construct the argparse top-level parser with every subcommand attached."""
    parser = argparse.ArgumentParser(
        prog="tephra",
        description="Topic-based markdown journal CLI for Obsidian-style vaults.",
    )
    parser.add_argument(
        "--version", action="version", version=f"%(prog)s {__version__}"
    )
    sub = parser.add_subparsers(dest="cmd", metavar="COMMAND")
    _add_write_subparsers(sub)
    _add_read_subparsers(sub)
    _add_topic_subparsers(sub)
    _add_folder_subparsers(sub)
    _add_config_subparsers(sub)
    _add_skill_subparser(sub)
    _add_repo_subparsers(sub)
    return parser


def _resolve_find_cutoff(args: argparse.Namespace) -> datetime | None:
    """Translate ``--within`` on ``find`` into a datetime cutoff."""
    if getattr(args, "within", None) is not None:
        return datetime.now() - parse_duration(args.within)
    return None


def _dispatch_topic(args: argparse.Namespace, parser: argparse.ArgumentParser) -> None:
    if args.topic_cmd == "list":
        cmd_topic_list(args.folder)
    elif args.topic_cmd == "add":
        cmd_topic_add(args.name, args.folder)
    else:
        parser.parse_args([args.cmd, "--help"])


def _dispatch_folder(args: argparse.Namespace, parser: argparse.ArgumentParser) -> None:
    if args.folder_cmd == "list":
        cmd_folder_list()
    else:
        parser.parse_args([args.cmd, "--help"])


def _dispatch_config(args: argparse.Namespace, parser: argparse.ArgumentParser) -> None:
    if args.config_cmd == "vault":
        cmd_config_vault(args.path)
    elif args.config_cmd == "default-folder":
        cmd_config_default_folder(args.folder or None)
    elif args.config_cmd == "auto-sync":
        cmd_config_auto_sync(args.value)
    elif args.config_cmd == "sync-metric":
        cmd_config_sync_metric(args.path)
    elif args.config_cmd == "show":
        cmd_config_show()
    elif args.config_cmd == "path":
        cmd_config_path()
    else:
        parser.parse_args([args.cmd, "--help"])


def _dispatch_skill(args: argparse.Namespace, _parser: argparse.ArgumentParser) -> None:
    if args.path:
        cmd_skill_path()
    elif args.install is not None:
        cmd_skill_install(args.install or None)
    else:
        cmd_skill_print()


_GROUP_DISPATCHERS = {
    "topic": _dispatch_topic,
    "folder": _dispatch_folder,
    "config": _dispatch_config,
    "skill": _dispatch_skill,
}


def _dispatch_topic_aware(args: argparse.Namespace) -> None:
    """Dispatch every command that takes a ``-T`` topic argument."""
    folder, topic = _parse_topic(getattr(args, "topic", None))
    topic_required = {"add", "amend", "addend", "retitle", "rm"}
    if args.cmd in topic_required and topic is None:
        sys.exit(
            f"-T 'Folder:' (folder-only) not allowed for '{args.cmd}'; "
            f"supply 'Folder:Topic' or 'Topic'"
        )
    write_topic: str = topic if topic is not None else ""
    dispatch = {
        "add": lambda: insert_entry(
            folder,
            write_topic,
            args.title,
            _resolve_bodies(args.entry),
            args.related or None,
            args.author,
        ),
        "amend": lambda: cmd_amend(
            folder,
            write_topic,
            _resolve_bodies(args.entry),
            args.date,
            args.title,
            args.related or None,
            args.author,
        ),
        "addend": lambda: cmd_addend(
            folder,
            write_topic,
            _resolve_bodies(args.entry),
            args.date,
            args.title,
            args.related or None,
            args.author,
        ),
        "retitle": lambda: cmd_retitle(
            folder, write_topic, args.date, args.title, args.new_title
        ),
        "rm": lambda: cmd_rm(folder, write_topic, args.date, args.title, args.dry_run),
        "show": lambda: cmd_show(args.date, folder, topic, args.json_out),
        "find": lambda: cmd_find(
            args.term,
            folder,
            topic,
            args.json_out,
            _resolve_find_cutoff(args),
            args.field,
            args.limit,
        ),
        "within": lambda: cmd_within(args.duration, folder, topic, args.json_out),
        "list": lambda: cmd_list(folder, topic, args.json_out),
        "last": lambda: cmd_last(folder, topic, args.json_out),
        "log": lambda: cmd_log(args.n),
        "diff": lambda: cmd_diff(args.ref),
        "undo": cmd_undo,
        "manual-commit": lambda: cmd_manual_commit(args.message),
    }
    dispatch[args.cmd]()


def main() -> None:
    """Capture manual vault edits, then dispatch the requested subcommand."""
    parser = build_parser()
    args = parser.parse_args()
    if args.cmd not in {"manual-commit", "skill"}:
        capture_manual_edits()
    if args.cmd is None:
        parser.print_help()
        return
    group = _GROUP_DISPATCHERS.get(args.cmd)
    if group is not None:
        group(args, parser)
        return
    _dispatch_topic_aware(args)


if __name__ == "__main__":
    main()
