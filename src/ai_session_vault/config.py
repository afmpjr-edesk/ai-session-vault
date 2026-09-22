"""Vault configuration.

A vault is a directory holding a ``vault.json`` config file and a git
repository (see ``vault.py``). The config records which agent runtimes the
vault knows about, where their session files live, and basic behaviour flags.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

CONFIG_FILENAME = "vault.json"

DEFAULT_PATHS: list[dict[str, str]] = [
    {"runtime": "claude", "annotation": "Claude Code", "pattern": "~/.claude/projects/*/agent-logs/*.jsonl"},
    {"runtime": "opencode", "annotation": "OpenCode", "pattern": "~/.local/share/opencode/storage/session/*.jsonl"},
    {"runtime": "codex", "annotation": "Codex CLI", "pattern": "~/.codex/sessions/*.jsonl"},
]

DEFAULT_IGNORE = ("~/.claude/projects/.git",)


class VaultConfig:
    """Thin wrapper over the JSON config file with sensible defaults."""

    CONFIG_FILENAME = CONFIG_FILENAME

    def __init__(self, raw: dict[str, Any] | None = None) -> None:
        self.raw: dict[str, Any] = raw if raw is not None else {}

    @classmethod
    def default(cls) -> "VaultConfig":
        return cls(
            {
                "version": 1,
                "vault_dir": os.path.expanduser("~/.ai-session-vault"),
                "runtimes": [
                    {"runtime": entry["runtime"], "annotation": entry["annotation"]}
                    for entry in DEFAULT_PATHS
                ],
                "paths": DEFAULT_PATHS,
                "ignore": list(DEFAULT_IGNORE),
            }
        )

    @classmethod
    def load(cls, path: Path) -> "VaultConfig":
        if path.is_file():
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                data = None
        else:
            data = None
        config = cls.default() if data is None else cls(data)
        config.path = path
        return config

    def save(self, path: Path | None = None) -> None:
        target = path or getattr(self, "path", None)
        if target is None:
            raise ValueError("no config path set")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(
            json.dumps(self.raw, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )

    def vault_dir(self) -> Path:
        return Path(self.raw.get("vault_dir", "~/.ai-session-vault")).expanduser()

    def runtime_patterns(self) -> dict[str, str]:
        return {entry["runtime"]: entry["pattern"] for entry in self.raw.get("paths", [])}

    def has_runtime(self, runtime: str) -> bool:
        return any(entry.get("runtime") == runtime for entry in self.raw.get("paths", []))


class RuntimeRegistry:
    """Resolve runtime names against the configured path entries."""

    def __init__(self, paths: list[dict[str, str]]) -> None:
        self._paths = paths

    def patterns(self) -> dict[str, str]:
        return {entry["runtime"]: entry["pattern"] for entry in self._paths}

    def all(self) -> list[dict[str, str]]:
        return list(self._paths)

    def get(self, runtime: str) -> dict[str, str] | None:
        for entry in self._paths:
            if entry["runtime"] == runtime:
                return entry
        return None