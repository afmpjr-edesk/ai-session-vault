"""Unit tests for the CLI dispatcher (subcommand wiring only)."""

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from ai_session_vault import cli


class CliDispatchTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_no_args_returns_usage_error_code(self) -> None:
        with patch("sys.argv", ["asv"]):
            result = cli.main()
        self.assertEqual(result, 2)

    def test_init_subcommand_creates_vault(self) -> None:
        vault_dir = self.tmp / "vault"
        with patch("sys.argv", ["asv", "init", str(vault_dir)]):
            result = cli.main()
        self.assertEqual(result, 0)
        self.assertTrue((vault_dir / ".git").exists())

    def test_version_flag_succeeds(self) -> None:
        with patch("sys.argv", ["asv", "--version"]):
            result = cli.main()
        self.assertEqual(result, 0)

    def test_resolve_vault_prefers_cwd_when_it_is_a_vault(self) -> None:
        from pathlib import Path as _Path

        vault_dir = self.tmp / "vault"
        cli.Vault.init(vault_dir)
        with patch("ai_session_vault.cli.Path.cwd", return_value=vault_dir):
            vault = cli._resolve_vault(None)
        self.assertEqual(vault.root, vault_dir.resolve())

    def test_resolve_vault_falls_back_to_default_when_cwd_is_not_vault(self) -> None:
        with patch("ai_session_vault.cli.Path.cwd", return_value=self.tmp):
            vault = cli._resolve_vault(None)
        self.assertEqual(vault.root, cli.DEFAULT_VAULT.resolve())

    def test_config_set_path_persists_in_vault_json(self) -> None:
        from io import StringIO

        vault_dir = self.tmp / "vault"
        cli.Vault.init(vault_dir)
        with patch("sys.argv", ["asv", "config", "set", "paths.claude", "*.jsonl", "--vault", str(vault_dir)]):
            result = cli.main()
        self.assertEqual(result, 0)
        config = cli.VaultConfig.load(vault_dir / "vault.json")
        self.assertEqual(config.get_path("claude"), "*.jsonl")

    def test_config_get_prints_the_stored_pattern(self) -> None:
        from io import StringIO

        vault_dir = self.tmp / "vault"
        cli.Vault.init(vault_dir)
        with patch("sys.argv", ["asv", "config", "set", "paths.claude", "custom/*.jsonl", "--vault", str(vault_dir)]):
            cli.main()
        with patch("sys.argv", ["asv", "config", "get", "paths.claude", "--vault", str(vault_dir)]):
            out = StringIO()
            with patch("sys.stdout", out):
                result = cli.main()
        self.assertEqual(result, 0)
        self.assertIn("custom/*.jsonl", out.getvalue())

    def test_config_get_missing_key_returns_error(self) -> None:
        vault_dir = self.tmp / "vault"
        cli.Vault.init(vault_dir)
        with patch("sys.argv", ["asv", "config", "get", "paths.doesnotexist", "--vault", str(vault_dir)]):
            result = cli.main()
        self.assertEqual(result, 2)

    def test_discover_lists_matching_session_files(self) -> None:
        from io import StringIO

        vault_dir = self.tmp / "vault"
        cli.Vault.init(vault_dir)
        session_dir = self.tmp / "sessions"
        session_dir.mkdir()
        (session_dir / "aaa.jsonl").write_text('{"type": "user", "message": {"role": "user", "content": "hi"}}\n', encoding="utf-8")
        with patch("sys.argv", ["asv", "config", "set", "paths.codex", str(session_dir / "*.jsonl"), "--vault", str(vault_dir)]):
            cli.main()
        with patch("sys.argv", ["asv", "discover", "--runtime", "codex", "--vault", str(vault_dir)]):
            out = StringIO()
            with patch("sys.stdout", out):
                result = cli.main()
        self.assertEqual(result, 0)
        self.assertIn("codex", out.getvalue())
        self.assertIn(str(session_dir / "aaa.jsonl"), out.getvalue())

    def test_sync_subcommand_adds_and_commits(self) -> None:
        from io import StringIO

        vault_dir = self.tmp / "vault"
        cli.Vault.init(vault_dir)
        session_dir = self.tmp / "sessions"
        session_dir.mkdir()
        (session_dir / "sync_sample.jsonl").write_text('{"type": "user", "message": {"role": "user", "content": "hi"}}\n', encoding="utf-8")
        with patch("sys.argv", ["asv", "config", "set", "paths.claude", str(session_dir / "*.jsonl"), "--vault", str(vault_dir)]):
            cli.main()

        out = StringIO()
        with patch("sys.stdout", out), patch("sys.argv", ["asv", "sync", "--runtime", "claude", "--vault", str(vault_dir), "--json"]):
            result = cli.main()
        self.assertEqual(result, 0)
        self.assertIn('"discovered": 1', out.getvalue())
        self.assertIn('"added": 1', out.getvalue())

    def test_config_set_storage_repack_persists(self) -> None:
        from io import StringIO

        vault_dir = self.tmp / "vault"
        cli.Vault.init(vault_dir)
        with patch("sys.argv", ["asv", "config", "set", "storage.repack.enabled", "false", "--vault", str(vault_dir)]):
            result = cli.main()
        self.assertEqual(result, 0)

        out = StringIO()
        with patch("sys.stdout", out), patch("sys.argv", ["asv", "config", "get", "storage.repack.enabled", "--vault", str(vault_dir)]):
            result = cli.main()
        self.assertEqual(result, 0)
        self.assertIn("False", out.getvalue())

    def test_status_reports_storage_health(self) -> None:
        from io import StringIO

        vault_dir = self.tmp / "vault"
        cli.Vault.init(vault_dir)
        out = StringIO()
        with patch("sys.stdout", out), patch("sys.argv", ["asv", "status", "--vault", str(vault_dir)]):
            result = cli.main()
        self.assertEqual(result, 0)
        self.assertIn("storage:", out.getvalue())


if __name__ == "__main__":
    unittest.main()