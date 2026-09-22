# AGENTS.md — ai-session-vault

Local-first version control for AI agent sessions (JSONL) on top of Git.

## Project principles

- **Local-first**: all state lives on the machine (JSONL files + sidecars + Git). Nothing leaves the machine by default.
- **Open formats**: plain JSONL plus JSON sidecar metadata; Git is the versioning mechanism.
- **No lock-in**: trivial migration via `git` or file copy; session formats are registered in the runtime registry.
- **Secrets**: reversible low-entropy filter stays out of the repository; no sensitive values are committed in plain text.

## Conventions

- **British English everywhere** (code, identifiers, docstrings, docs, scripts, commit messages). The sole exception is `AI_HANDOFF.md`, which is written in the user's language (Portuguese).
- Python 3.12+ stdlib only (zero third-party runtime dependencies).
- TDD: write the test before (or alongside) the implementation; suite lives in `tests/` (unittest).
- Layout: `src/ai_session_vault/` is the package; `scripts/` holds operations; `docs/` holds guides.
- CLI contract: short subcommands, `--json` for automation, human-readable output for a terminal.

## Mandatory validation

- `./scripts/test.sh` — runs the full test suite.
- When adding a new subcommand: update `docs/01_usage.md`.

See also `/home/afmpjr/AGENTS.md` (global guidelines) and `/home/afmpjr/AI_ONBOARDING.md` (session protocol).