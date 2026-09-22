"""Unit tests for vault configuration loading and validation."""

import tempfile
import unittest
from pathlib import Path

from ai_session_vault.config import DEFAULT_PATHS, RuntimeRegistry, VaultConfig, expand_pattern


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
        self.assertIn("codex", names)

    def test_default_paths_use_real_session_locations(self) -> None:
        patterns = {entry["runtime"]: entry["pattern"] for entry in DEFAULT_PATHS}
        self.assertEqual(
            patterns["claude"],
            "~/.claude/projects/*/*.jsonl",
        )
        self.assertEqual(
            patterns["codex"],
            "~/.codex/sessions/**/*.jsonl",
        )

    def test_default_paths_no_longer_include_opencode(self) -> None:
        names = {entry["runtime"] for entry in DEFAULT_PATHS}
        self.assertNotIn("opencode", names)

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

    def test_expand_pattern_expands_tilde_and_returns_files(self) -> None:
        directory = self.tmp / "logs"
        directory.mkdir()
        (directory / "a.jsonl").write_text("x\n", encoding="utf-8")
        (directory / "sub").mkdir()
        (directory / "sub" / "b.jsonl").write_text("y\n", encoding="utf-8")
        matches = expand_pattern(str(directory / "**" / "*.jsonl"))
        self.assertEqual([p.name for p in matches], ["a.jsonl", "b.jsonl"])

    def test_set_path_adds_and_replaces_runtime_entry(self) -> None:
        config = VaultConfig.default()
        config.set_path("claude", "/custom/path/*.jsonl")
        self.assertEqual(config.get_path("claude"), "/custom/path/*.jsonl")
        config.set_path("opencode", "~/.config/opencode/*.jsonl")
        self.assertEqual(config.get_path("opencode"), "~/.config/opencode/*.jsonl")
        self.assertIn("opencode", config.runtime_patterns())


if __name__ == "__main__":
    unittest.main()