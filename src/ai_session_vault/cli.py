"""Command-line interface for ai-session-vault.

Subcommands follow a simple contract: short names, human output by default,
``--json`` for automation. Every subcommand that touches the vault resolves
its own ``--vault`` argument, falling back to the vault directory recorded in
the vault config when the current directory is itself a vault.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from ai_session_vault import __version__
from ai_session_vault.config import DEFAULT_STORAGE_REPACK, VaultConfig, expand_pattern
from ai_session_vault.search import search_file, search_text
from ai_session_vault.vault import GitError, Vault

DEFAULT_VAULT = Path("~/.ai-session-vault").expanduser()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="asv",
        description="Local-first version control for AI agent sessions.",
    )
    parser.add_argument("--version", action="version", version=f"asv {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    p_init = sub.add_parser("init", help="initialise a new vault")
    p_init.add_argument("vault_dir", nargs="?", default=str(DEFAULT_VAULT))

    p_add = sub.add_parser("add", help="snapshot a session file into the vault")
    p_add.add_argument("session_file", type=Path)
    p_add.add_argument("--runtime", required=True, help="e.g. claude, opencode, codex")
    p_add.add_argument("--vault", type=Path, default=None)

    p_commit = sub.add_parser("commit", help="commit pending vault changes")
    p_commit.add_argument("--vault", type=Path, default=None)
    p_commit.add_argument("-m", "--message", default=None)

    p_log = sub.add_parser("log", help="show recent vault commits")
    p_log.add_argument("--vault", type=Path, default=None)
    p_log.add_argument("--max", type=int, default=30)

    p_status = sub.add_parser("status", help="show vault status")
    p_status.add_argument("--vault", type=Path, default=None)
    p_status.add_argument("--json", action="store_true")

    p_show = sub.add_parser("show", help="render a stored session as text")
    p_show.add_argument("session_id")
    p_show.add_argument("--vault", type=Path, default=None)
    p_show.add_argument("--max-records", type=int, default=None)

    p_find = sub.add_parser("find", help="search stored sessions")
    p_find.add_argument("query")
    p_find.add_argument("--vault", type=Path, default=None)
    p_find.add_argument("--case-sensitive", action="store_true")
    p_find.add_argument("--json", action="store_true")

    p_secrets = sub.add_parser("secrets", help="manage the redaction dictionary")
    sec_sub = p_secrets.add_subparsers(dest="secrets_command", required=False)
    p_scan = sec_sub.add_parser("scan", help="scan a session file for candidate secrets")
    p_scan.add_argument("session_file", type=Path)
    p_scan.add_argument("--json", action="store_true")
    p_redact = sec_sub.add_parser("redact", help="redact a session file to stdout")
    p_redact.add_argument("session_file", type=Path)
    p_redact.add_argument(
        "--dict", type=Path, default=None,
        help="JSON file (0600) where the secret->placeholder mapping is persisted",
    )

    p_discover = sub.add_parser(
        "discover",
        help="list session files matching the vault's configured runtime paths",
    )
    p_discover.add_argument("--runtime", default=None, help="restrict to one runtime (e.g. claude, codex)")
    p_discover.add_argument("--json", action="store_true")
    p_discover.add_argument("--vault", type=Path, default=None)

    p_sync = sub.add_parser(
        "sync",
        help="discover, snapshot, and commit updated sessions in one step",
    )
    p_sync.add_argument("--runtime", "-r", default=None, help="restrict to one runtime (e.g. claude, codex, antigravity)")
    p_sync.add_argument("-m", "--message", default=None, help="custom commit message")
    p_sync.add_argument("--json", action="store_true", help="output JSON")
    p_sync.add_argument("--vault", type=Path, default=None)

    p_config = sub.add_parser("config", help="read or set vault configuration")
    config_sub = p_config.add_subparsers(dest="config_command", required=True)
    p_config_set = config_sub.add_parser("set", help="set a configuration value")
    p_config_set.add_argument("key", help="dotted key, e.g. paths.claude")
    p_config_set.add_argument("value")
    p_config_set.add_argument("--vault", type=Path, default=None)
    p_config_get = config_sub.add_parser("get", help="print a configuration value")
    p_config_get.add_argument("key", default="", nargs="?")
    p_config_get.add_argument("--vault", type=Path, default=None)

    return parser


def _resolve_vault(vault_opt: Path | None) -> Vault:
    if vault_opt is not None:
        return Vault.open(vault_opt)
    # If the current directory is a vault root, use it; otherwise default.
    cwd = Path.cwd()
    if (cwd / VaultConfig.CONFIG_FILENAME).exists():
        return Vault.open(cwd)
    return Vault.open(DEFAULT_VAULT)


def _cmd_init(args: argparse.Namespace) -> int:
    Vault.init(Path(args.vault_dir))
    print(f"initialised vault at {args.vault_dir}")
    return 0


def _cmd_add(args: argparse.Namespace) -> int:
    vault = _resolve_vault(args.vault)
    stored = vault.add_session(args.session_file, args.runtime)
    print(f"snapshotted session {stored.session_id} ({args.runtime})")
    return 0


def _cmd_commit(args: argparse.Namespace) -> int:
    try:
        vault = _resolve_vault(args.vault)
        message = args.message or "snapshot: ai-session-vault"
        added = vault.commit(message)
    except GitError as exc:
        print(f"asv: error: {exc}", file=sys.stderr)
        return 1
    if added:
        print(f"committed {added[:8]}")
    else:
        print("nothing to commit")
    return 0


def _cmd_log(args: argparse.Namespace) -> int:
    vault = _resolve_vault(args.vault)
    for line in vault.log(max_count=args.max):
        print(line)
    return 0


def _cmd_discover(args: argparse.Namespace) -> int:
    vault = _resolve_vault(args.vault)
    items: list[dict] = []
    found: list[Path] = []
    for runtime, pattern in vault.config.runtime_patterns().items():
        if args.runtime and runtime != args.runtime:
            continue
        for path in expand_pattern(pattern):
            found.append(path)
            items.append({"runtime": runtime, "path": str(path)})
    if args.json:
        print(json.dumps({"patterns": items, "count": len(items)}, indent=2))
        return 0
    if not found:
        print("no session files matched the configured paths")
        return 0
    for item in items:
        print(f"{item['runtime']:<8} {item['path']}")
    return 0


def _cmd_sync(args: argparse.Namespace) -> int:
    vault = _resolve_vault(args.vault)
    try:
        res = vault.sync(runtime=args.runtime, message=args.message)
    except GitError as exc:
        print(f"asv: error: {exc}", file=sys.stderr)
        return 1
    if args.json:
        print(json.dumps(res, indent=2))
        return 0
    print(f"discovered: {res['discovered']} session file(s)")
    print(f"added:      {res['added']} session(s)")
    if res["commit"]:
        print(f"committed:  {res['commit'][:8]}")
    else:
        print("committed:  nothing to commit (already up to date)")
    return 0


def _cmd_config(args: argparse.Namespace) -> int:
    vault = _resolve_vault(args.vault)
    if args.config_command == "set":
        key = args.key
        if key.startswith("paths."):
            runtime = key.split(".", 1)[1]
            vault.config.set_path(runtime, args.value)
            vault.config.save(vault.root / VaultConfig.CONFIG_FILENAME)
            print(f"set {key} = {args.value}")
            return 0
        if key.startswith("storage.repack."):
            field = key.split(".", 2)[2]
            storage = vault.config.raw.setdefault("storage", {})
            repack = storage.setdefault("repack", dict(DEFAULT_STORAGE_REPACK))
            if field == "enabled":
                repack["enabled"] = args.value.lower() in ("true", "1", "yes")
            elif field in ("loose_objects", "loose_bytes"):
                try:
                    repack[field] = int(args.value)
                except ValueError:
                    print(f"asv: error: value for {key!r} must be an integer", file=sys.stderr)
                    return 2
            else:
                print(f"asv: error: unsupported config key {key!r}", file=sys.stderr)
                return 2
            vault.config.save(vault.root / VaultConfig.CONFIG_FILENAME)
            print(f"set {key} = {args.value}")
            return 0
        if key == "vault_dir":
            vault.config.raw["vault_dir"] = args.value
            vault.config.save(vault.root / VaultConfig.CONFIG_FILENAME)
            print(f"set {key} = {args.value}")
            return 0
        print(f"asv: error: unsupported config key {key!r}", file=sys.stderr)
        return 2

    # config get
    if not args.key:
        print(json.dumps(vault.config.raw, indent=2, ensure_ascii=False))
        return 0
    if args.key.startswith("paths."):
        runtime = args.key.split(".", 1)[1]
        value = vault.config.get_path(runtime)
        if value is None:
            print(f"asv: error: no such key {args.key!r}", file=sys.stderr)
            return 2
        print(value)
        return 0
    node: Any = vault.config.raw
    for part in args.key.split("."):
        if isinstance(node, dict) and part in node:
            node = node[part]
        else:
            print(f"asv: error: no such key {args.key!r}", file=sys.stderr)
            return 2
    print(node)
    return 0


def _cmd_status(args: argparse.Namespace) -> int:
    vault = _resolve_vault(args.vault)
    status = vault.status()
    if args.json:
        print(json.dumps(status, indent=2))
        return 0
    print(f"vault:      {status['root']}")
    print(f"sessions:   {status['session_count']}")
    print(f"runtimes:   {', '.join(status['runtimes']) or '-'}")
    print(f"dirty:      {'yes' if status['dirty'] else 'no'}")
    if "loose_objects" in status:
        packed_str = "repack recommended" if status.get("needs_repack") else "healthy"
        print(f"storage:    {status['loose_objects']} loose objects ({status.get('loose_kib', 0)} KiB) [{packed_str}]")
    return 0


def _cmd_show(args: argparse.Namespace) -> int:
    from ai_session_vault.transcript import render_transcript

    vault = _resolve_vault(args.vault)
    try:
        stored = vault.export_session(args.session_id)
    except KeyError:
        print(f"asv: error: no session with id {args.session_id}", file=sys.stderr)
        return 1
    print(render_transcript(stored.path, max_records=args.max_records))
    return 0


def _cmd_find(args: argparse.Namespace) -> int:
    vault = _resolve_vault(args.vault)
    results: list[dict] = []
    for stored in vault.sessions():
        matches, snippets = search_file(
            stored.path,
            args.query,
            case_sensitive=args.case_sensitive,
            max_snippets=5,
        )
        if not matches:
            continue
        results.append(
            {
                "session_id": stored.session_id,
                "runtime": stored.runtime,
                "matches": matches,
                "snippets": snippets,
            }
        )
    if args.json:
        print(json.dumps(results, indent=2))
        return 0
    for item in results:
        print(f"{item['session_id']} [{item['runtime']}] ({item['matches']} matches)")
        for snippet in item["snippets"]:
            print(f"    {snippet}")
    return 0


def _cmd_secrets(args: argparse.Namespace) -> int:
    if args.secrets_command == "scan":
        from ai_session_vault.redact import low_entropy_hits

        text = args.session_file.read_text(encoding="utf-8", errors="replace")
        hits = list(dict.fromkeys(low_entropy_hits(text)))
        if args.json:
            print(json.dumps({"hits": hits}, indent=2))
            return 0
        for hit in hits:
            print(hit)
        return 0
    if args.secrets_command == "redact":
        from ai_session_vault.redact import Redactor

        text = args.session_file.read_text(encoding="utf-8", errors="replace")
        redactor = Redactor()
        print(redactor.redact(text), end="")
        if args.dict:
            redactor.dictionary.save(args.dict)
        return 0
    print("asv: error: unknown secrets subcommand", file=sys.stderr)
    return 2


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    if argv is None:
        argv = sys.argv[1:]
    if not argv:
        parser.print_usage(sys.stderr)
        return 2
    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:
        # Mutation-free exits (e.g. --help, --version) have already printed.
        return int(exc.code or 0)
    handlers = {
        "init": _cmd_init,
        "add": _cmd_add,
        "commit": _cmd_commit,
        "log": _cmd_log,
        "status": _cmd_status,
        "show": _cmd_show,
        "find": _cmd_find,
        "secrets": _cmd_secrets,
        "discover": _cmd_discover,
        "config": _cmd_config,
        "sync": _cmd_sync,
    }
    return handlers[args.command](args)


if __name__ == "__main__":
    raise SystemExit(main())