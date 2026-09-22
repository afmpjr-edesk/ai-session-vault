"""The vault: a git repository that stores session snapshots and sidecars.

Layout of a vault root::

    <vault>/
      vault.json          # VaultConfig
      .git/               # git repository driving versioning
      sessions/
        <runtime>/<session_id>.jsonl        # snapshot of the session
        <runtime>/<session_id>.jsonl.meta   # metadata sidecar (JSON)

Concurrency is deliberately simple: the vault never writes in the background
and has no daemon. Every mutation is a discrete CLI action that runs git
directly via subprocess, so the history is always observable with plain git.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

from ai_session_vault.config import CONFIG_FILENAME, VaultConfig
from ai_session_vault.session import IdentifiedSession

SESSION_SUBDIR = "sessions"


class GitError(RuntimeError):
    """Raised when a git command fails."""


@dataclass(frozen=True)
class StoredSession:
    """A session snapshot stored inside the vault."""

    root: Path
    runtime: str
    session_id: str

    @property
    def filename(self) -> str:
        return f"{self.session_id}.jsonl"

    @property
    def path(self) -> Path:
        return self.root / SESSION_SUBDIR / self.runtime / self.filename

    def meta_path(self) -> Path:
        return self.path.with_suffix(self.path.suffix + ".meta")

    def meta(self) -> dict:
        return json.loads(self.meta_path().read_text(encoding="utf-8"))

    def relative(self) -> Path:
        return self.path.relative_to(self.root)


class Vault:
    """Versioned store of session snapshots backed by git."""

    def __init__(self, root: Path, config: VaultConfig | None = None) -> None:
        self.root = root.resolve()
        self.config = config or VaultConfig.load(self.root / CONFIG_FILENAME)

    @classmethod
    def init(cls, root: Path) -> "Vault":
        root.mkdir(parents=True, exist_ok=True)
        config = VaultConfig.default()
        config.raw["vault_dir"] = str(root)
        config.save(root / CONFIG_FILENAME)
        vault = cls(root, config)
        (root / SESSION_SUBDIR).mkdir(exist_ok=True)
        if not (root / ".git").exists():
            vault._git("init", "--quiet")
            if not vault._user_configured():
                vault._git("config", "user.name", "ai-session-vault")
                vault._git("config", "user.email", "vault@local")
            (root / ".gitignore").write_text("*.log\n", encoding="utf-8")
        return vault

    @classmethod
    def open(cls, root: Path) -> "Vault":
        config = VaultConfig.load(root / CONFIG_FILENAME)
        return cls(root, config)

    # ------------------------------------------------------------------ git

    def _git(self, *args: str) -> str:
        result = subprocess.run(
            ["git", "-C", str(self.root), *args],
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            raise GitError(f"git {' '.join(args)} failed: {result.stderr.strip()}")
        return result.stdout

    def _user_configured(self) -> bool:
        try:
            self._git("config", "user.name")
            return True
        except GitError:
            return False

    # ------------------------------------------------------------- sessions

    def session_dir(self, runtime: str) -> Path:
        (self.root / SESSION_SUBDIR / runtime).mkdir(parents=True, exist_ok=True)
        return self.root / SESSION_SUBDIR / runtime

    def sessions(self) -> list[StoredSession]:
        """List every stored session snapshot."""
        found: list[StoredSession] = []
        base = self.root / SESSION_SUBDIR
        if not base.exists():
            return found
        for runtime_dir in sorted(base.iterdir()):
            if not runtime_dir.is_dir():
                continue
            for path in sorted(runtime_dir.glob("*.jsonl")):
                session_id = path.stem
                found.append(
                    StoredSession(self.root, runtime_dir.name, session_id)
                )
        return found

    def add_session(self, source: Path, runtime: str) -> StoredSession:
        """Snapshot a session file into the vault (idempotent by content)."""
        identified = IdentifiedSession.from_file(source, runtime)
        target_dir = self.session_dir(runtime)
        target = target_dir / identified.filename
        target_dir.mkdir(parents=True, exist_ok=True)
        if not target.exists() or target.read_bytes() != source.read_bytes():
            shutil.copyfile(source, target)
            meta = identified.meta()
            (target.with_suffix(target.suffix + ".meta")).write_text(
                json.dumps(meta, indent=2, ensure_ascii=False) + "\n",
                encoding="utf-8",
            )
        return StoredSession(self.root, runtime, identified.session_id)

    def commit(self, message: str) -> str:
        """Stage all vault changes and create a commit. Returns the SHA."""
        self._git("add", "-A")
        if not self._git("status", "--porcelain"):
            return ""
        self._git("commit", "--quiet", "-m", message)
        return self._git("rev-parse", "HEAD").strip()

    def log(self, max_count: int = 30) -> list[str]:
        """Return recent commit lines as human-readable strings."""
        try:
            output = self._git("log", f"--max-count={max_count}", "--pretty=format:%h %ad %s", "--date=short")
        except GitError:
            return []
        return [line for line in output.splitlines() if line.strip()]

    def status(self) -> dict:
        """Summarise vault state for the status subcommand."""
        sessions = self.sessions()
        try:
            porcelain = self._git("status", "--porcelain")
        except GitError:
            porcelain = ""
        return {
            "root": str(self.root),
            "session_count": len(sessions),
            "runtimes": sorted({s.runtime for s in sessions}),
            "dirty": bool(porcelain.strip()),
            "porcelain": porcelain.strip(),
        }

    # -------------------------------------------------------------- exports

    def export_session(self, session_id: str) -> StoredSession:
        """Return a stored session by id, raising KeyError when missing."""
        for candidate in self.sessions():
            if candidate.session_id == session_id:
                return candidate
        raise KeyError(session_id)