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

    def test_parse_count_objects(self) -> None:
        raw = "count: 12\nsize: 48\nin-pack: 100\npacks: 2\nsize-pack: 250\n"
        metrics = self.vault._parse_count_objects(raw)
        self.assertEqual(metrics["count"], 12)
        self.assertEqual(metrics["size"], 48)
        self.assertEqual(metrics["in-pack"], 100)

    def test_status_includes_storage_metrics(self) -> None:
        src = self.tmp / "session.jsonl"
        src.write_text('{"type": "user", "message": {"role": "user", "content": "hi"}}\n', encoding="utf-8")
        self.vault.add_session(src, runtime="claude")
        self.vault.commit("first")
        status = self.vault.status()
        self.assertIn("loose_objects", status)
        self.assertIn("loose_kib", status)
        self.assertIn("needs_repack", status)
        self.assertFalse(status["needs_repack"])

    def test_repack_triggers_when_loose_objects_exceed_threshold(self) -> None:
        # Configure a tiny threshold of 1 loose object
        self.vault.config.raw.setdefault("storage", {})["repack"] = {
            "enabled": True,
            "loose_objects": 1,
            "loose_bytes": 1024,
        }
        self.vault.config.save(self.vault.root / VaultConfig.CONFIG_FILENAME)

        src = self.tmp / "session.jsonl"
        src.write_text('{"type": "user", "message": {"role": "user", "content": "hi"}}\n', encoding="utf-8")
        self.vault.add_session(src, runtime="claude")
        self.vault.commit("first")

        # After commit with repack threshold=1, loose objects should be packed
        metrics = self.vault._parse_count_objects(self.vault._git("count-objects", "-v"))
        self.assertEqual(metrics.get("count", 0), 0)
        self.assertGreater(metrics.get("in-pack", 0), 0)

    def test_repack_skipped_when_disabled(self) -> None:
        self.vault.config.raw.setdefault("storage", {})["repack"] = {
            "enabled": False,
            "loose_objects": 1,
            "loose_bytes": 1024,
        }
        self.vault.config.save(self.vault.root / VaultConfig.CONFIG_FILENAME)

        src = self.tmp / "session.jsonl"
        src.write_text('{"type": "user", "message": {"role": "user", "content": "hi"}}\n', encoding="utf-8")
        self.vault.add_session(src, runtime="claude")
        self.vault.commit("first")

        # Repack disabled -> loose objects remain
        metrics = self.vault._parse_count_objects(self.vault._git("count-objects", "-v"))
        self.assertGreater(metrics.get("count", 0), 0)

    def test_discover_and_sync(self) -> None:
        source_dir = self.tmp / "source_sessions"
        source_dir.mkdir()
        src_file = source_dir / "my_session.jsonl"
        src_file.write_text('{"type": "user", "message": {"role": "user", "content": "test sync"}}\n', encoding="utf-8")

        self.vault.config.set_path("claude", str(source_dir / "*.jsonl"))
        self.vault.config.save(self.vault.root / VaultConfig.CONFIG_FILENAME)

        discovered = self.vault.discover(runtime="claude")
        self.assertEqual(len(discovered), 1)
        self.assertEqual(discovered[0][0], "claude")

        res = self.vault.sync(runtime="claude")
        self.assertEqual(res["discovered"], 1)
        self.assertEqual(res["added"], 1)
        self.assertTrue(bool(res["commit"]))

        # Second sync is idempotent
        res2 = self.vault.sync(runtime="claude")
        self.assertEqual(res2["discovered"], 1)
        self.assertEqual(res2["commit"], "")  # Nothing to commit


if __name__ == "__main__":
    unittest.main()