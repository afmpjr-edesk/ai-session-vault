# ADR-001 — Versioning session files with git

## Status

Accepted and implemented (PR #4). Proposal date: 2026-09-22; implementation date: 2026-09-27. Authors: Rafael (software-architect) and Igor (tech-lead-orchestrator).

## Context

`ai-session-vault` snapshots agent sessions as plain JSONL. Every `asv add`
copies the **whole** session file into
`sessions/<runtime>/<id>.jsonl` (`vault.py:131` `add_session`), and every
`asv commit` stages everything and creates a normal git commit
(`vault.py:146` `commit`). The result is that history stores a full copy of
the session per changed version, and git keeps every copy.

Real workloads measured on this machine:

| session store | typical file | largest file |
| --- | --- | --- |
| codex rollouts (`~/.codex/sessions/**/*.jsonl`) | ~100 KB – 2 MB | 19.2 MB |
| claude sessions (`~/.claude/projects/**/*.jsonl`) | tens of MB | 168 MB |

A vault can hold thousands of sessions, and each session accrues a new full
copy on every change. The question this ADR answers: how should the vault
version these files so history stays compact, revisionable and diffable while
honouring the hard constraint — **Python 3.12 stdlib only, local-first, no
daemon, a vault is just a git repo, no mandatory git-lfs client at runtime and
no third-party dependencies**?

### What was measured (this machine, git 2.55.0, Python 3.12.14)

Three real session files were snapshotted through **12 change cycles** per
file, replicating `asv add`/`commit` behaviour exactly (full-file copy per
cycle, then `git add -A` + `git commit`). Each cycle appended one real
session line to the evolving source (the dominant runtime pattern: JSONL
sessions grow by appending).

| metric | status quo (plain JSONL) | PoC: gzip clean/smudge filter |
| --- | --- | --- |
| raw files used | 161 KB, 19.2 MB, 168 MB | same |
| worktree `sessions/` bytes after 12 cycles | 187,318,272 | 187,318,272 |
| `.git` **loose** state (what `asv` leaves today) | **1.34 GiB** | 1.06 GiB |
| `.git` after clean pack (`git repack -adq` + `prune-packed`) | **85.6 MiB** | 85.8 MiB |
| zlib:gzip compression ratio of the raw files | claude 51.5% | codex 17–24% |

Per-file packed footprints (12 versions each, on-disk in the pack):

| file | total on-disk (12 versions) | per extra version (delta) |
| --- | --- | --- |
| claude_big (12 × 168 MB = 2.0 GB of blobs) | 86.3 MB | ≈ 5 KB |
| codex_big (12 × 19 MB = 230 MB of blobs) | 3.36 MB | ≈ 0.5 KB |
| codex_med (12 × 161 KB) | 41 KB | ≈ 23 B |

An adversarial case was also measured: one commit that scattered-rewrites 2%
of the characters of the 168 MB file (a crude model of runtime compaction /
in-place rewrite). The new version is stored as a **12.8 MB delta** — i.e.
marginal cost per rewritten version jumps from ~KB to ~MB as soon as sessions
are re-written rather than appended.

Three findings drive this decision:

1. **Git's native delta compression already solves the growth problem
   completely — but only once objects are packed.** 12 full copies of a
   168 MB file weigh 2.0 GB of blobs, but pack to 86.3 MB (= one compressed
   base + ~5 KB deltas). The same holds for codex (230 MB → 3.36 MB).
2. **The cost is the loose-object window.** `asv` never packs, and git's own
   auto-gc (`git gc --auto`, default `gc.auto=6700` loose objects) will not
   fire until thousands of objects accumulate — while each MB-scale loose
   blob is a full zlib copy. Measured: **1.34 GiB loose vs 85.6 MiB packed,
   a ~16× difference on just 36 commits.** This is the entire "history grows
   fast" problem; it is an operational shortcoming, not a format one.
3. **A gzip clean/smudge filter buys almost nothing.** At pack steady state
   the filter gains are nil (85.6 vs 85.8 MiB; on the 168 MB file deltas
   already converge to the same base; `codex_med` is even *worse* packed with
   the filter: 68 KB vs 41 KB). It trims only the loose window by ~20%
   (1.34 → 1.06 GiB) at the price of coupling and unreadable diffs (below).

Operational observation: on this git version a bare `git gc` left **three
overlapping packs (171.2 MiB size-pack, 360 in-pack entries for 180 distinct
objects)** for the same workload, i.e. *worse* than a single explicit
`git repack -adq` (85.6 MiB). The vault should therefore call an explicit
repack, not rely on `git gc`'s defaults.

### Findability constraint

`asv find` reads the stored snapshot as plain text (`cli.py:234`), `asv show`
renders it (`cli.py:226`), `export_session` hands out the stored path
(`vault.py:179`), and `asv secrets` operates on the file. Any storage change
that stops the working-tree file from being plain, read-only JSONL breaks all
of these, or forces a decode step on every read.

## Decision drivers

- History stays **compact**, **revisionable** and **diffable** with plain git
  tools.
- A vault must remain **plain-readable** (vault = git repo, copy/tar/push it
  and it works; `git diff`, `git log -p`, `git blame`, any git UI work).
- **stdlib-only**, local-first, no daemon, no runtime git-lfs client.
- `find`/`show`/`export_session`/`secrets` keep reading plain files with no
  extra steps.
- Simple, deterministic, reversible behaviour over clever heuristics; honours
  the project's "no lock-in" principle (README, `docs/01_usage.md`).

## Options considered

### (a) Status quo, rely on git pack/delta

What: keep committing full plain JSONL snapshots and hope git handles it.
Fit: partially — git handles it perfectly *after* a repack, but nothing ever
repacks by default fast enough for MB-scale blobs (measured 1.34 GiB loose
after 12 cycles). Pros: zero code change, ideal interoperability. Cons: no
determinism in when history compresses; brief-but-huge growth bursts.

### (b) gzip via clean/smudge filters (`.gitattributes` + `git -c filter…`)

What: store gzip-compressed blobs; the working tree stays plain because git
decompresses on checkout (`smudge`).
Fit: fails the "no lock-in / plain format" driver. Pros: stdlib-feasible (the
PoC used two ~5-line Python scripts), trims the loose window ~20%. Cons:
**no measurable steady-state gain** (85.6 vs 85.8 MiB packed; `codex_med`
packed *worse*, 68 vs 41 KB); `git diff`/`git log -p` show compressed bytes;
a fresh `git clone`/`git checkout` outside a filter-configured checkout fails
(`required`) or yields binary files — an exact git-lfs-style coupling, only
without git-lfs's remote benefits; round-trip depends on filter availability.
`asv find/show/export` would only keep working while the filter config is
present, and start reading binary garbage otherwise (the "extra step" the
findability constraint forbids).

### (c) Append-only journal (chunk/interleave store)

What: vault keeps one append-only record journal per session instead of
per-version full snapshots; git versions the single growing file; `show`
replays and must bound a point-in-time.
Fit: technically coherent but a large redesign with no payoff against the
measured data — git already packs appended full snapshots into the same ~5 KB
deltas the journal would produce (finding 1), so the journal only "wins" for
in-place rewrites, where it makes point-in-time `show`/`export`/deletion and
`asv status` semantics genuinely harder (replay markers, record offsets,
compaction). Pros: smallest possible deltas for rewrite-heavy sessions. Cons:
breaks the "snapshot per change" model the CLI and docs expose; high effort.
Definitely not the default.

### (d) git-lfs pointer files

What: commit tiny pointer files; blobs go to an LFS store.
Fit: violates the constraint outright (runtime `git-lfs` client becomes
mandatory for `add`/`show`/`find`), and pointer files break the plain-JSONL
readers unless every read goes through an LFS checkout. Also remote-oriented
where the vault is deliberately local. Rejected.

### (e) Snapshot pruning / retention policy

What: keep only N versions, squash or drop old ones.
Fit: saves storage by *deleting history*, which is the product's core promise
("keeps full history in git", README "Why"). Rejected as a default; may be a
future manual escape hatch at most.

## Decision

**Keep the current content model — one byte-identical plain JSONL snapshot
per version (`vault.py:131` unchanged) — and add a vault-owned packing
maintenance step so history is kept packed on a deterministic, size-driven
schedule instead of never.**

Concretely, the follow-up implementation PR should:

1. **Add storage configuration keys** in `src/ai_session_vault/config.py`
   (`VaultConfig.default()` + per-vault `vault.json`):
   - `storage.repack.enabled` (default `true`),
   - `storage.repack.loose_objects` (default e.g. 512),
   - `storage.repack.loose_bytes` (default e.g. 64 MiB).
2. **Pack after commit** in `src/ai_session_vault/vault.py`
   (`Vault.commit`, `vault.py:146`): after a commit that actually recorded
   changes, read `git count-objects -vH`; when loose `count` or loose `size`
   exceeds the configured threshold, run `git repack -adq` then
   `git prune-packed` through the existing `_git` helper. When there is
   nothing to commit, do nothing. Maintenance is best-effort: failures are
   surfaced as warnings, never as commit failures (history must never break
   because a repack failed).
3. **Report it** (optional but cheap): `Vault.status` (`vault.py:162`) may
   include loose-object count/bytes so `asv status` can show "history packed"
   vs "needs repack".
4. **Do not touch** `add_session`, the snapshot layout, `find`, `show`,
   `export_session` or `secrets`. The working tree remains plain JSONL, so all
   readers and all git tooling keep working unchanged (zero lock-in).

Justification against the data: this removes the entire measured problem
(1.34 GiB loose, the 16× blow-up) with a few lines in the commit path;
steady-state size is already optimal (≈ one compressed base + ~5 KB deltas
per appended version — identical to what a journal or gzip filter would
produce, findings 1–3); and it is the only option that keeps the vault a
trivially portable, plain-text git repo.

## Consequences

### Code touched

- `src/ai_session_vault/config.py` — new `storage.repack.*` keys with
  defaults; versioned in `vault.json` like existing config.
- `src/ai_session_vault/vault.py` — `commit()` gains the post-commit
  maintenance call; a small helper (e.g. `_maybe_repack()`) parses
  `count-objects -vH`; `status()` may gain loose metrics.
- `src/ai_session_vault/cli.py` — only if status output changes (no logic
  change otherwise; `find`/`show`/`export` untouched).
- `tests/` — new unit tests (TDD, stdlib `unittest`, alongside the existing
  57): config defaults exist; `commit` invokes `git repack -adq` when the
  loose threshold is crossed; no repack below threshold; repack skipped when
  there is nothing to commit; `storage.repack.enabled=false` disables it;
  `count-objects` output parsing incl. empty/`git 2.55` multi-pack shapes.
- `docs/01_usage.md` + `README.md` — a short "Storage and history sizing"
  section: the model (plain snapshots, git packs them), the default
  thresholds, how to tune/disable, and a note on `core.bigFileThreshold`.

### Migration for existing vaults

None required — the snapshot format is unchanged. On the first `asv commit`
after upgrade, any vault above the loose threshold is packed automatically. A
one-time manual `git -C <vault> repack -adq` remains the documented way to
compress a very large legacy vault immediately.

### Operational notes and risks

- A full `repack -adq` pauses on very large vaults; thresholds default so the
  step runs rarely, and `storage.repack.enabled` is the escape hatch for
  operators who prefer an external cron/`git maintenance` schedule.
- git's own default `git gc --auto` is intentionally *not* relied upon
  (measured: fires too late for MB blobs; and bare `git gc` on this git
  version produced duplicate overlapping packs). The vault triggers an
  explicit repack on its own cadence.
- Files approaching git's `core.bigFileThreshold` (512 MB) are neither
  delta-compressed nor compressed by git, so a session that large would fall
  back to full-copy-per-version regardless of this ADR. Noted for the docs;
  no constraint-compliant remedy exists today (a journal would be the only
  one, and it is rejected for now).

## Alternatives explicitly rejected and why

- **(b) gzip clean/smudge filter** — measured no benefit at pack steady
  state (85.6 vs 85.8 MiB; `codex_med` worse: 68 vs 41 KB), only a ~20% loose
  trim, at the cost of binary `git diff`, clone/checkout coupling, and
  breaking the plain-JSONL reader contract. The filter is the definition of
  lock-in the project forbids.
- **(c) append-only journal** — git deltas on appended full snapshots already
  match the journal's ~5 KB marginals (finding 1); the journal only helps
  in-place rewrites, where it complicates `show`/`export` point-in-time
  semantics, deletion and `status` for a large redesign. Revisit only if
  rewrite-heavy, 100 MB+ sessions become the norm.
- **(d) git-lfs** — requires a runtime `git-lfs` client (violates the
  stdlib/local constraint) and turns the working tree reads into LFS-managed
  ones, breaking `find`/`show`/`export` without extra plumbing. Also oriented
  at remotes the vault deliberately does not have.
- **(e) pruning / retention squash** — deletes history, which is opposed
  to the product's core promise. Not a default under any circumstances.

## Appendix — reproducing the measurements

Environment: Arch Linux (Omarchy), git 2.55.0, Python 3.12.14. Real files:
`~/.claude/projects/-home-afmpjr/*.jsonl` (168 MB example) and
`~/.codex/sessions/2026/09/**/*.jsonl` (19 MB and 161 KB examples). The full
automated harness used for the spike is not part of the repo; the essential,
reproducible commands are:

```bash
# 1. seed: copy 3 real files; extract one real 'append' line per file
# 2. simulate 12 asv-style cycles: full copy + git add -A + git commit,
#    appending one line to the evolving source between cycles
# 3. measure loose state (what asv leaves today)
git -C $REPO count-objects -vH        # -> count/size = loose objects
du -sh $REPO/.git
# 4. measure packed steady state (clean, deduplicated)
git -C $REPO repack -adq && git -C $REPO prune-packed
git -C $REPO count-objects -vH        # -> in-pack/size-pack
# 5. per-file footprints, deltas and delta bases
git rev-list --objects --all | grep 'sessions/.*\.jsonl'
git cat-file --batch-check='%(objectname) %(objectsize) %(objectsize:disk) %(deltabase)'
# 6. gzip filter PoC demanded this plumbing (result: no steady-state gain)
#    .gitattributes:  sessions/**/*.jsonl filter=asvgz
#    filter.asvgz.clean=python3 gz_clean.py   (gzip.compress(..., mtime=0))
#    filter.asvgz.smudge=python3 gz_smudge.py (gzip.decompress)
```

Key figures embedded above come from `git count-objects -vH`,
`git cat-file --batch-check` and per-pack verification; the loose↔packed
numbers were reproduced twice during the spike. Caveats: absolute pack bytes
shift a little with git version and repack flags; the *ratios and the shape*
of the conclusion (loose blow-up ≫ packed steady state; filter gains ≈ nil;
rewrites ≫ appends) reproduce across the runs performed.