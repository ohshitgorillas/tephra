---
name: tephra
description: >
  Append, read, and amend a topic-based markdown journal in an Obsidian-style
  vault via the `tephra` CLI. Use when user says "log this", "add to tephra",
  "/tephra", "what did I do on <date>", "find <term> in the log", or after any
  non-trivial change to system state, infra, config, or code outside a git
  repo. Never edit topic files directly — the CLI handles atomic writes,
  locking, and per-write git auto-commits.
---

Tool for keeping a topic-organized development journal as Obsidian-style markdown. Each topic is a single file (`Topic.md`); files may live in the vault root or in a folder (`<vault>/<Folder>/<Topic>.md`). Entries are H2 sections (`## YYYY-MM-DD HH:MM — Title`) sorted newest-first. Every CLI write auto-commits to the vault git repo. Direct edits in the Obsidian GUI are auto-captured to git on next CLI invocation.

## When and what to log

- After any non-trivial change to system state, infra, config, or code.
- One entry per topic, per day per change. Group related changes; don't bundle unrelated ones.
- Skip: pure read ops, throwaway exploration, trivial fixes already captured in git, the act of logging.
- **CRITICAL**: Contents are stored in plain text. DO NOT ENTER SENSITIVE INFORMATION.

## How to log

- Be terse, concise, accurate.
- Lead with what changed. Then files. Then why if non-obvious.
- Backticks for paths, commands, identifiers. HTML-tag-looking tokens (`<name>`, `<HOST>`) are auto-backticked on insert.
- Match existing entries in the same topic — check `tephra last -T TOPIC` or `tephra within 3d -T TOPIC` first.
- No marketing voice. No "successfully". No restating the title.
- Cross-link prior entries with `--related` only when the link is *causally direct* (see below). Before writing a new entry, run `tephra find TERM` for the subsystem(s) the change touches; pass each *directly related* prior entry as `--related "Topic#YYYY-MM-DD [HH:MM] — Title"`. The flag is repeatable. Refs are validated — invalid anchors are rejected.

### When to add a related link

Link only if you can state a causal sentence: "this entry **<does X>** to the thing the prior entry **<created / broke / tuned / started>**." If the sentence doesn't form, don't link. Allowed cases:

- **Origin** — prior entry created the exact thing this entry modifies, fixes, extends, or removes.
- **Bug → fix** — prior entry documented the symptom this entry resolves.
- **Tuning chain** — prior entry set the same knob (value, threshold, policy, jail, alert) this entry adjusts. Same knob, not same subsystem.
- **Continuation** — prior entry is an earlier step in the same incident, migration, or refactor arc.

Anti-patterns — do **not** link:

- ❌ Same file, unrelated concern (compose edit for service A → unrelated compose edit for service B in same file).
- ❌ Same subsystem, causally independent (two unrelated fail2ban tweaks weeks apart).
- ❌ Same date, no causal tie.
- ❌ "Reader might find it interesting" / "touches adjacent subsystem" — Obsidian search and backlinks handle discovery; `Related` is reserved for causal chain.
- ❌ Topic-level kinship without entry-level kinship (both entries are about Storage ≠ related).

Default when uncertain: **no link**. Tangential ≠ related. A bare entry with no `--related` is correct output when nothing causally upstream exists.

## Add new entry

```sh
tephra add -T TOPIC -t "Brief title" -e "What changed, which files, why if non-obvious."
```

- `-T` is required and must be a known topic (see `tephra topic list`).
- Bare `-T Topic` resolves to the configured default folder (see `tephra config show`). Override with `-T Folder:Topic`.
- For read commands only (`show`, `find`, `within`, `list`, `last`): `-T Folder:` (trailing colon, no topic) scopes to all topics in `Folder`. Write/existence commands reject this form.
- Title: imperative, ≤60 chars.
- Entry: factual + terse. What changed → files touched → why (only if non-obvious).
- Title collision on same date in same topic = error. Pick distinct title or use `amend`/`addend`.

Multi-line body:

```sh
tephra add -T TOPIC -t "Title" -e $'line1\nline2'
some-cmd | tephra add -T TOPIC -t "Title" -e -
```

`-e` is repeatable — each value becomes a separate paragraph (joined with a blank line, in CLI order):

```sh
tephra add -T TOPIC -t "Title" \
  -e "First paragraph." \
  -e "Second paragraph."
```

At most one `-e` may be `-` (stdin is read once). Empty `-e ""` slots are dropped (so `addend -e "" --related ...` still extends the Related line without adding a paragraph). Same `-e` flag and join semantics apply on `amend` and `addend`.

Cross-link to other entries with `--related`:

```sh
tephra add -T O11y -t "Title" -e "body" \
  --related "Bittorrent#2026-04-24 — peer port metric"
```

`--related` is repeatable. Anchor format: `Topic#YYYY-MM-DD [HH:MM] — Title`. Refs are validated against the target topic file (exact match required).

Record authorship with `--author NAME`:

```sh
tephra add -T TOPIC -t "Title" -e "body" --author clod
```

Appends an `_author: NAME_` line at the bottom of the entry (below any Related line). Parsed as metadata: excluded from the `body` field, surfaced as `author` in `--json`, and not searched by `find`. On `amend`/`addend` the existing author is preserved unless `--author` overrides it. Use the agent's name (`clod`) for agent-written entries, `atom` for hand-written ones.

## Topic management

```sh
tephra topic list [-F FOLDER]   # known topics (default folder unless -F)
tephra topic add NAME [-F FOLDER]
tephra folder list              # vault subdirectories
```

Topics cannot be added implicitly via `add` — the topic file must already exist.

## Edit / extend / fix

Default target = newest entry in the topic. Pass `-d YYYY-MM-DD -t "Title"` (or `-d YYYYMMDD` / `-d MMDD`) to target a specific one.

| Op | Command |
|----|---------|
| Append paragraph | `tephra addend -T TOPIC -e "more context"` |
| Append paragraph + extend Related line | `tephra addend -T TOPIC -e "..." --related "Topic#anchor"` |
| Replace body, keep heading + Related | `tephra amend -T TOPIC -e "new body"` |
| Replace body + rewrite Related | `tephra amend -T TOPIC -e "..." --related "Topic#anchor"` |
| Rename | `tephra retitle -T TOPIC -d 2026-04-28 -t "Old" --to "New"` |
| Delete | `tephra rm -T TOPIC -d 2026-04-28 -t "Title"` |
| Preview delete | `tephra rm -T TOPIC -d 2026-04-28 -t "Title" -n` |
| Revert last commit | `tephra undo` |

`amend` / `addend` use the same repeatable `-e`/`--entry` as `add`. Pass `-e -` to read body from stdin.

## Read

Cross-topic by default. Pass `-T TOPIC` to restrict to one topic, or `-T Folder:` to restrict to all topics in a folder.

| Op | Command | JSON |
|----|---------|------|
| Entries on a date | `tephra show YYYY-MM-DD` | `--json` |
| Date (MMDD) | `tephra show 0428` (most recent past) | `--json` |
| Search | `tephra find TERM [TERM ...]` (case-insensitive; multiple terms = AND; `--in {title,body,both}`, `--limit N`, `--within DURATION`) | `--json` |
| Within DURATION | `tephra within DURATION` (units: s/m/h/d/w; e.g. 30m, 12h, 7d, 2w) | `--json` |
| Index | `tephra list` (headings only) | `--json` |
| Newest | `tephra last` | `--json` |

Prefer `--json` when piping into another tool or parsing programmatically.

## When to read

Reach for the log to answer questions about prior work. Map prompt shape to command:

| Prompt shape | Command |
|--------------|---------|
| "changes to wireguard over the last 2 weeks" | `tephra find "wireguard" --within 2w --json` |
| "nginx broke overnight" | `tephra find "nginx" --within 12h` |
| "summarize yesterday's work" | `tephra show YYYY-MM-DD` (yesterday's date) |
| "what did I last do to X?" | `tephra find "X"` then take newest match |
| "see the most recent entry" | `tephra last` |
| "did I ever fix Z?" | `tephra find "Z"` |

Use `--json` when feeding output back into reasoning — the structured `{topic, date, time, title, body, related}` shape is easier to summarize than raw markdown.

## Repo introspection

```sh
tephra log [N]      # commit history (default 20)
tephra diff [REF]   # git show REF (default HEAD)
```

## Hard rules

- Never `echo >>` to a topic file, `sed -i`, or otherwise touch files directly. Direct edits get captured on next CLI run, but you lose the structured commit message.
- Never invent dates. Tool sets today.
- Never delete entries to "clean up" unless explicitly told. Use `amend` to correct content; use `rm` only when an entry is wrong/duplicate and the user has authorized removal.
- `undo` reverts only the most recent commit. For older fixes: `git -C "$(tephra config path)" revert <sha>` against the vault repo.
- Before `add`: search today with `tephra within 1d` or `tephra find TERM --within 1d`. If a same-day same-topic entry already covers this change, `addend` to it instead of creating a new one.
- Before `add` (separate pass, looking further back): `tephra find` for the subsystem. Pass only *causally direct* prior entries as `--related` (see "When to add a related link"). Tangential matches — same file, same subsystem, same date with no causal tie — must be skipped. A wrong link is worse than no link: it pollutes the graph.
- Never include sensitive information.

## Failure modes

- `Entry 'X' already exists on YYYY-MM-DD in topic '...'` → title collision. Pick distinct title or `addend` to extend the existing one.
- `No entry 'X' on YYYY-MM-DD in topic '...'` → wrong title, date, or topic. Run `tephra list -T TOPIC` to find correct title.
- `Unknown topic '...'. Known: ...` → typo or missing topic. Run `tephra topic list`; create with `tephra topic add NAME` if needed.
- `Related ref: no entry '...'` → cross-link target doesn't exist. Verify with `tephra find` or `tephra list -T TOPIC`.
- `No entries` → empty topic; `add` first.

## Vault location

The vault path is stored in `$XDG_CONFIG_HOME/tephra/vault` (typically `~/.config/tephra/vault`). Set with `tephra config vault PATH`; inspect with `tephra config show`. Default if unset: `$XDG_DATA_HOME/tephra/vault` (typically `~/.local/share/tephra/vault`).

The default folder for `-T Topic` is stored at `$XDG_CONFIG_HOME/tephra/default_folder`. Set with `tephra config default-folder NAME`; clear with empty string (writes go to vault root).

## Auto-sync

Optional. When enabled and the vault repo has an `origin` remote, every CLI write op runs `git pull --rebase --autostash` before the local commit and `git push` after.

```sh
tephra config auto-sync on        # enable
tephra config auto-sync off       # disable
```

- **Pull conflict:** the write is aborted and the repo is left mid-rebase. Subsequent tephra writes refuse to run until you finish the rebase manually:
  ```sh
  git -C "$(tephra config path)" status
  git -C "$(tephra config path)" rebase --continue   # or --abort
  ```
- **Network failure on pull:** warns to stderr, continues with the local commit. Offline use keeps working; the next successful sync reconciles.
- **Push failure:** warns to stderr; the local commit is preserved. The next write op's pre-pull + push will reconcile.
- **No `origin` remote / auto-sync off:** behaves identically to no-sync mode (no-op).

Optional Prometheus textfile metric:

```sh
tephra config sync-metric /var/lib/node_exporter/textfile_collector/tephra_sync.prom
tephra config sync-metric ""       # disable
```

Emits `tephra_sync_status` (1 clean, 0 conflict/push failure) and `tephra_sync_last_attempt` (Unix timestamp), atomically (tmp + rename) on every sync attempt.
