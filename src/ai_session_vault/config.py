"""Vault configuration.

A vault is a directory holding a ``vault.json`` config file and a git
repository (see ``vault.py``). The config records which agent runtimes the
vault knows about, where their session files live, and basic behaviour flags.
"""

from __future__ import annotations

import glob
import json
import os
from pathlib import Path
from typing import Any

CONFIG_FILENAME = "vault.json"

DEFAULT_PATHS: list[dict[str, str]] = [
    {"runtime": "claude", "annotation": "Claude Code", "pattern": "~/.claude/projects/*/*.jsonl"},
    {"runtime": "codex", "annotation": "Codex CLI", "pattern": "~/.codex/sessions/**/*.jsonl"},
    {
        "runtime": "antigravity",
        "annotation": "Antigravity",
        "pattern": "~/.gemini/antigravity/brain/*/.system_generated/logs/transcript.jsonl",
    },
    {
        "runtime": "opencode",
        "annotation": "OpenCode",
        "pattern": "~/.local/share/opencode/sessions/*.jsonl",
    },
]

DEFAULT_IGNORE: tuple[str, ...] = ()

DEFAULT_STORAGE_REPACK: dict[str, Any] = {
    "enabled": True,
    "loose_objects": 512,
    "loose_bytes": 64 * 1024 * 1024,
}


def expand_pattern(pattern: str) -> list[Path]:
    """Expand a ``~``-prefixed glob into the real session files it matches.

    Recursive ``**`` globs and single ``*`` are honoured; non-file matches
    (directories, absent paths) are excluded. Returns a sorted list.
    """
    expanded = os.path.expanduser(pattern)
    matches = [Path(item) for item in glob.glob(expanded, recursive=True)]
    return sorted(item for item in matches if item.is_file())


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
                "paths": [dict(entry) for entry in DEFAULT_PATHS],
                "ignore": list(DEFAULT_IGNORE),
                "storage": {"repack": dict(DEFAULT_STORAGE_REPACK)},
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

    def get_path(self, runtime: str) -> str | None:
        return self.runtime_patterns().get(runtime)

    def set_path(self, runtime: str, pattern: str) -> None:
        """Set or replace the session path pattern for a runtime."""
        paths = self.raw.setdefault("paths", [])
        for entry in paths:
            if entry.get("runtime") == runtime:
                entry["pattern"] = pattern
                break
        else:
            annotation = runtime.capitalize()
            paths.append({"runtime": runtime, "annotation": annotation, "pattern": pattern})

    def has_runtime(self, runtime: str) -> bool:
        return any(entry.get("runtime") == runtime for entry in self.raw.get("paths", []))

    @property
    def storage_repack(self) -> dict[str, Any]:
        """Return the effective storage repack settings, falling back to defaults."""
        storage = self.raw.get("storage")
        if not isinstance(storage, dict):
            storage = {}
        repack = storage.get("repack")
        if not isinstance(repack, dict):
            repack = {}
        return {
            "enabled": bool(repack.get("enabled", DEFAULT_STORAGE_REPACK["enabled"])),
            "loose_objects": int(repack.get("loose_objects", DEFAULT_STORAGE_REPACK["loose_objects"])),
            "loose_bytes": int(repack.get("loose_bytes", DEFAULT_STORAGE_REPACK["loose_bytes"])),
        }


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