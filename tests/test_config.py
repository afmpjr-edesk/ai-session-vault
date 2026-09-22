"""Unit tests for vault configuration loading and validation."""

import tempfile
import unittest
from pathlib import Path

from ai_session_vault.config import DEFAULT_PATHS, RuntimeRegistry, VaultConfig


class VaultConfigTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_default_config_has_vault_dir(self) -> None:
        config = VaultConfig.default()
        self.assertIn("vault_dir", config.raw)

    def test_default_paths_cover_known_runtimes(self) -> None:
        names = {entry["runtime"] for entry in DEFAULT_PATHS}
        self.assertIn("claude", names)
        self.assertIn("opencode", names)
        self.assertIn("codex", names)

    def test_load_missing_file_returns_default(self) -> None:
        config = VaultConfig.load(self.tmp / "nope.json")
        self.assertIn("vault_dir", config.raw)

    def test_save_then_load_roundtrip(self) -> None:
        path = self.tmp / "vault.json"
        config = VaultConfig.default()
        config.raw["custom_key"] = 42
        config.save(path)
        reloaded = VaultConfig.load(path)
        self.assertEqual(reloaded.raw["custom_key"], 42)

    def test_runtime_registry_resolves_known_runtime(self) -> None:
        registry = RuntimeRegistry(DEFAULT_PATHS)
        self.assertTrue(
            any(entry["runtime"] == "claude" for entry in registry.all())
        )


if __name__ == "__main__":
    unittest.main()