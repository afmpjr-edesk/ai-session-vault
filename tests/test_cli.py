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


if __name__ == "__main__":
    unittest.main()