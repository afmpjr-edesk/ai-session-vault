# Usage guide

`asv` (ai-session-vault) is a local-first version control tool for AI agent
sessions. It snapshots JSONL session files into a vault backed by a git
repository, so every conversation is findable, continuable, and versioned —
with no hub, no daemon, and no account.

## Install

From source (development):

```bash
./scripts/setup.sh
source .venv/bin/activate
asv --help
```

Quick test without installing:

```bash
PYTHONPATH=src python -m ai_session_vault --help
```

## Quick start

```bash
# 1. Initialise a vault
asv init ~/.ai-session-vault

# 2. (Optional) see which session files the vault knows about
asv discover

# 3. Snapshot a session file into the vault
asv add --runtime claude --vault ~/.ai-session-vault \
    ~/.claude/projects/some-project/abc123.jsonl

# 4. Commit the snapshot to the vault's git history
asv commit --vault ~/.ai-session-vault -m "first snapshot"

# 5. Browse, search, read
asv log   --vault ~/.ai-session-vault
asv status --vault ~/.ai-session-vault
asv show <session_id> --vault ~/.ai-session-vault
asv find "retry the api" --vault ~/.ai-session-vault
```

If you run the commands from inside a vault directory, the `--vault` flag is
not required.

## Subcommands

| Command | Purpose |
| --- | --- |
| `init [DIR]` | Initialise a new vault (git repo + config). |
| `add --runtime <R> FILE` | Snapshot a session file into the vault (idempotent by content). |
| `commit [-m MSG]` | Stage all vault changes and create a commit. |
| `log [--max N]` | Show recent commits. |
| `status` | Show vault location, session count, runtimes, dirty state. |
| `show SESSION_ID` | Render a session as readable text. |
| `find QUERY` | Search stored sessions (shows session + snippets). |
| `discover [--runtime R]` | Expand each runtime's path glob into real session files. |
| `config set KEY VALUE` | Set a config value (e.g. `paths.claude`). |
| `config get [KEY]` | Print a config value or the whole config without a key. |
| `secrets scan FILE` | List candidate secrets in a session file. |
| `secrets redact FILE` | Print the file with secrets replaced by `[REDACTED:sha]`. |

## Session paths

Each runtime has a default glob stored in `vault.json` under `paths`, pointing
at real session-file locations:

| Runtime | Default glob |
| --- | --- |
| claude | `~/.claude/projects/*/*.jsonl` |
| codex | `~/.codex/sessions/**/*.jsonl` |

`discover` expands these globs into the session files currently on disk, which
is handy before running `add` or to sanity-check a custom glob:

```bash
asv discover                 # all runtimes
asv discover --runtime codex # just one
```

Override a runtime's glob per vault — useful when runtimes keep sessions in a
non-standard place:

```bash
asv config set paths.codex "~/.codex/archive/**/*.jsonl"
asv config get paths.codex     # -> ~/.codex/archive/**/*.jsonl
asv config get                 # full config as JSON
```

Session identifiers come from the file when possible, with a stable fallback:
claude writes `sessionId` at the top level of each record; codex nests
`session_id` inside the `payload` of the `session_meta` record — both are
detected. UUIDs are kept intact.

## Secrets handling

`asv` treats secrets as a first-class concern, but stays reversible:

* `secrets scan` flags low-entropy strings (long random-looking tokens) and
  known credential formats (`sk-…`, `ghp_…`, `AKIA…`, Bearer tokens, Slack
  tokens).
* `secrets redact` replaces matches with deterministic `[REDACTED:<sha256:12>]`
  placeholders, so the same secret always maps to the same placeholder.
* `--dict FILE` persists the secret->placeholder mapping to a JSON file
  written with mode `0600`; the placeholder is what gets shared, and the owner
  can restore the original text offline from the dict.

Note on the model: a vault snapshot keeps the raw session bytes locally —
the vault is private on your machine by default. Redaction is the *sharing
gateway*: before you publish, push, or hand a session to someone, run
`secrets redact` (with `--dict`) to produce a version whose secrets are
replaced by placeholders. That keeps the optimistic "share anything" workflow
without committing plain-text credentials to a remote.

## Vault layout

```
<vault>/
  vault.json                     # configuration (JSON)
  .git/                          # the versioning engine
  sessions/
    <runtime>/<session_id>.jsonl        # session snapshot
    <runtime>/<session_id>.jsonl.meta   # metadata sidecar (JSON)
```

Every commit is a normal git commit, so any git tool works against the vault
(`git log`, `git show`, `git bundle create`, …).

## Design principles

* **Local-first** — all state lives on the machine; nothing is sent anywhere.
* **Open formats** — plain JSONL + JSON sidecars; git is the versioning engine.
* **No lock-in** — a vault is a directory you can copy, tar, or push with git.
* **No daemon** — every operation is an explicit CLI action; nothing runs in
  the background.
* **Tolerant parsing** — sessions from different runtimes (Claude, OpenCode,
  Codex, …) may have different JSON shapes (claude top-level `sessionId`,
  codex nested `payload.session_id`); malformed lines are skipped, never
  fatal.
* **Configurable paths** — default globs are verified against real runtimes;
  each vault may override them per runtime (`config set paths.<runtime>`).