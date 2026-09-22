"""Unit tests for vault operations (init, add, commit, log, status)."""

import subprocess
import tempfile
import unittest
from pathlib import Path

from ai_session_vault.config import VaultConfig
from ai_session_vault.vault import Vault


class VaultTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.vault = Vault.init(self.tmp / "vault")

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _git(self, *args: str) -> str:
        return subprocess.run(
            ["git", "-C", str(self.vault.root), *args],
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()

    def test_init_creates_git_repo_and_config(self) -> None:
        self.assertTrue((self.vault.root / ".git").exists())
        self.assertTrue((self.vault.root / VaultConfig.CONFIG_FILENAME).exists())

    def test_add_session_stores_snapshot_and_meta(self) -> None:
        src = self.tmp / "session.jsonl"
        src.write_text('{"type": "user", "message": {"role": "user", "content": "hi"}}\n', encoding="utf-8")
        self.vault.add_session(src, runtime="claude")
        sessions = list(self.vault.sessions())
        self.assertEqual(len(sessions), 1)
        stored = sessions[0]
        self.assertTrue(stored.path.exists())
        self.assertTrue(stored.meta_path().exists())
        self.assertEqual(stored.meta()["runtime"], "claude")

    def test_add_idempotent_same_content(self) -> None:
        src = self.tmp / "session.jsonl"
        src.write_text('{"type": "user", "message": {"role": "user", "content": "hi"}}\n', encoding="utf-8")
        self.vault.add_session(src, runtime="claude")
        self.vault.add_session(src, runtime="claude")
        self.assertEqual(len(list(self.vault.sessions())), 1)

    def test_commit_records_git_history(self) -> None:
        src = self.tmp / "session.jsonl"
        src.write_text('{"type": "user", "message": {"role": "user", "content": "hi"}}\n', encoding="utf-8")
        self.vault.add_session(src, runtime="claude")
        self.vault.commit("initial snapshot")
        self.assertIn("initial snapshot", self._git("log", "--oneline", "-3"))

    def test_log_lists_commits(self) -> None:
        src = self.tmp / "session.jsonl"
        src.write_text('{"type": "user", "message": {"role": "user", "content": "hi"}}\n', encoding="utf-8")
        self.vault.add_session(src, runtime="claude")
        self.vault.commit("first")
        self.vault.add_session(src, runtime="claude")
        entries = self.vault.log()
        self.assertGreaterEqual(len(entries), 1)


if __name__ == "__main__":
    unittest.main()