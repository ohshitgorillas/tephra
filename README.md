# tephra

A small CLI for keeping a topic-organized development log as a directory of Markdown files. Each topic is its own file (`Topic.md`), with entries organized as `## YYYY-MM-DD HH:MM — Title` headings sorted newest-first. Every CLI write auto-commits to a private git repo in the vault directory, so nothing is lost and bad writes can be reverted.

The format is hand-editable in any text editor and renders cleanly in [Obsidian](https://obsidian.md/), where wikilinks (`[[Topic#anchor]]`) double as cross-references between entries.

## Why tephra

I keep a log to track homelab changes. `git` doesn't fit (`/` would be an absurd repo) and the changes I care about span multiple systems anyway. Any significant configuration changes, package installations, etc. were recorded in `~/devlog.md`.

Enter Claude Code: agents work faster than I can, but getting them to log their actions consistently was insanely frustrating. Despite explicit instructions in `CLAUDE.md`, agents would freestyle the format, create duplicate date headers or simply enter the wrong date, append instead of prepend, etc. It took no less than five frustrated prompts per session to keep the devlog consistent.

Getting information out of the log for agents was its own hurdle: `grep` doesn't work when entires span multiple lines, so your choices are to either copy-paste by hand or dump the whole file and burn context on noise.

`tephra` fixes both ends. Agents and humans alike get a simple CLI for maintaining and referencing the document.

## What tephra provides

- A clean, simple CLI for keeping and reading a timestamped log.
- Optional `**Related:**` line per entry holding `[[Topic#anchor]]` wikilinks to specific cross-topic entries. Cross-link targets are validated on insert.
- Optional `_author: NAME_` line per entry recording who wrote it, set with `--author`. Treated as metadata: kept out of the body and out of `find` searches.
- Atomic writes (tempfile + `os.replace`), so a crash mid-write cannot leave a file corrupt.
- A file lock around every write, so concurrent `tephra` invocations on the same host serialize cleanly instead of clobbering each other.
- A private git repo at the vault root that auto-commits every CLI write. Direct edits to topic files (with Obsidian, `vim`, `sed`, an editor plugin, whatever) are detected on the next CLI invocation and committed as `manual edit (captured)`, so nothing slips past the history.
- Read commands (`show`, `find`, `within`, `list`, `last`) with optional `--json` output, suitable for piping into other tools or AI agents. Cross-topic by default; `-T TOPIC` filters.
- Edit commands (`amend`, `addend`, `retitle`, `rm`) that target the newest entry in a topic by default, or any entry via `--date` + `--title`.
- An `undo` command that wraps `git revert HEAD` on the data repo, so even a bad write is recoverable without reaching into git directly.

## What tephra doesn't provide

Encryption. Bring your own, or avoid entering sensitive data.

## Install

From PyPI:

```sh
pipx install tephra        # recommended (isolated venv, on PATH)
# or
pip install --user tephra
```

From a clone of this repo (editable, for hacking on tephra itself):

```sh
python -m venv ~/.local/share/tephra-venv
~/.local/share/tephra-venv/bin/pip install -e .
ln -s ~/.local/share/tephra-venv/bin/tephra ~/.local/bin/tephra
```

Editable install: changes to the source take effect immediately.

## Usage

Create a topic (only way to add topics — `add` will refuse unknown topics):

```sh
tephra topic add Notes
tephra topic list
```

Add a new entry under a topic:

```sh
tephra add -T Notes -t "Brief title" -e "What changed, files touched, why."
```

`-e` is repeatable for multi-paragraph bodies (joined on blank lines, in CLI order):

```sh
tephra add -T Notes -t "Two paragraphs" \
  -e "First paragraph." \
  -e "Second paragraph."
```

Cross-link to other entries with `--related` (repeatable, validated):

```sh
tephra add -T O11y -t "Title" -e "body" \
  --related "Bittorrent#2026-04-24 — peer port metric"
```

Record who wrote an entry with `--author NAME`. It appends an `_author: NAME_` line at the bottom of the entry (below any Related line), kept out of the body text and excluded from `find` searches but surfaced as `author` in `--json`. Works on `add`/`amend`/`addend`; `amend` and `addend` preserve an existing author unless `--author` overrides it.

```sh
tephra add -T O11y -t "Title" -e "body" --author clod
```

Read commands (cross-topic by default; pass `-T TOPIC` to restrict to one topic, or `-T Folder:` to restrict to all topics in a folder):

```sh
tephra show 2026-04-28          # entries on a date
tephra show 0428                # MMDD: most recent past 04-28
tephra find "wireguard"         # case-insensitive substring search
tephra find wg peer             # multiple terms = AND (all must match)
tephra find "wg" --within 7d    # ... restricted to last 7 days (units: s/m/h/d/w)
tephra find "wg" --in title     # restrict match to title (or body, or both [default])
tephra find "wg" --limit 5      # cap to N newest matches
tephra within 7d                # last 7 days (units: s/m/h/d/w; e.g. 30m, 12h, 2w)
tephra list                     # headings only, no bodies
tephra last                     # newest entry
```

Edit commands (default to newest entry in the topic; pass `-d` + `-t` to target a specific one):

```sh
tephra amend -T TOPIC -e "new body"                          # replace body; preserves Related
tephra amend -T TOPIC -e "new body" --related "Topic#anchor" # rewrite Related
tephra add -T TOPIC -t "Title" -e "body" --author clod       # record author
tephra addend -T TOPIC -e "extra para"                       # append paragraph above any Related
tephra addend -T TOPIC -e "" --related "Topic#anchor"        # extend Related only (deduped)
tephra retitle -T TOPIC -d 2026-04-28 -t "Old" --to "New"
tephra rm -T TOPIC -d 2026-04-28 -t "Title"
tephra rm -T TOPIC -d 2026-04-28 -t "Title" -n               # dry-run preview
```

`amend` and `addend` accept the same repeatable `-e`/`--entry` as `add`. `-d DATE` accepts `YYYY-MM-DD`, `YYYYMMDD`, or `MMDD`. There is no `edit` subcommand — open the topic file in your editor of choice (Obsidian GUI, vim, etc.); direct edits are auto-captured to git on the next CLI invocation.

Repo commands:

```sh
tephra log [N]                  # last N commits (default 20)
tephra diff [REF]               # git show REF (default HEAD)
tephra undo                     # revert last commit in data repo
tephra manual-commit "MSG"      # commit pending manual edits with custom message
```

Multi-line bodies from a shell are easiest with `$'...\n...'` quoting, or by passing `-` as the body and piping in stdin:

```sh
tephra add -T TOPIC -t "Title" -e $'first line\nsecond line'
some-command | tephra add -T TOPIC -t "Title" -e -
tephra amend -T TOPIC - < new_body.txt
```

`--json` output is available on `show`, `find`, `within`, `list`, and `last`.

## Configuration

The vault path is stored in `$XDG_CONFIG_HOME/tephra/vault` (typically `~/.config/tephra/vault`):

```sh
tephra config vault /path/to/your/vault   # set
tephra config show                        # inspect resolved path
```

Default if unset: `$XDG_DATA_HOME/tephra/vault` (typically `~/.local/share/tephra/vault`).

## Data layout

```
<vault>/
├── Topic1.md          # one file per topic, H1 + H2 entries
├── Topic2.md
├── ...
├── .git/              # auto-commit history
└── .tephra.lock       # advisory write lock
```

Each topic file looks like:

```markdown
# Topic1

## 2026-04-28 14:32 — newer entry

Body.

**Related:** [[Topic2#2026-04-27 — earlier entry]]
_author: clod_

## 2026-04-27 09:15 — older entry

Body.
```

Each CLI write produces one commit with a message like `add: [Topic] TITLE`, `amend: [Topic] TITLE`, `rm: [Topic] TITLE`. Direct edits are committed as `manual edit (captured)` on the next invocation, or with a custom message via `tephra manual-commit "MSG"` before the next CLI write.

## Obsidian integration

The vault is a normal directory of markdown files — point Obsidian at it and entries render with working wikilinks (`[[Topic#anchor]]`). The `.obsidian/` directory Obsidian creates inside the vault is independent of `tephra`; you may want to gitignore `.obsidian/workspace.json` to avoid noisy auto-commits of UI state.

## Recovery

The git repo at the vault root is the source of truth for history. If a write went wrong:

```sh
tephra undo                            # revert most recent commit
tephra log                             # commit history
tephra diff <ref>                      # inspect a past version
git -C "$(tephra config path)" revert <ref>   # selectively undo any past commit
```

## For AI agents

See [`src/tephra/skills/tephra/SKILL.md`](src/tephra/skills/tephra/SKILL.md) for an AI-optimized reference covering when to log, command tables, style guidance, and failure modes. The file is a Claude Code skill (loaded by Claude Code's skill discovery via the YAML frontmatter) but is human-readable as a regular markdown reference.

The skill ships inside the installed package. To drop it into a Claude Code project (or your user-wide skills dir) without cloning the repo:

```sh
tephra skill --install                # writes to $CLAUDE_PROJECT_DIR/.claude/skills/tephra/SKILL.md
                                      # (falls back to ~/.claude/skills/tephra/SKILL.md)
tephra skill --install ~/.claude      # explicit target dir
tephra skill                          # cat to stdout (pipe wherever you want)
tephra skill --path                   # print the bundled file path
```

## License

MIT — see [`LICENSE`](LICENSE).
