"""Unit tests for the reversible secret redaction filter."""

import json
import tempfile
import unittest
from pathlib import Path

from ai_session_vault.redact import RedactionDict, Redactor, low_entropy_hits


class LowEntropyTests(unittest.TestCase):
    def test_recognises_long_random_tokens(self) -> None:
        hits = list(low_entropy_hits("api key sk-abcdefghijklmnopqrstuvwxyz1234567890 end"))
        self.assertTrue(hits)

    def test_ignores_ordinary_text(self) -> None:
        hits = list(low_entropy_hits("the quick brown fox jumps over the lazy dog"))
        self.assertEqual(hits, [])

    def test_min_length_respected(self) -> None:
        hits = list(low_entropy_hits("short-token-yes-no", min_length=40))
        self.assertEqual(hits, [])


class RedactorTests(unittest.TestCase):
    def test_redact_replaces_tokens_with_placeholder(self) -> None:
        redactor = Redactor()
        out = redactor.redact("header sk-abcdefghijklmnopqrstuvwxyz1234567890 tail")
        self.assertNotIn("sk-abcdefghijklmnopqrstuvwxyz1234567890", out)
        self.assertIn(redactor.placeholder("sk-abcdefghijklmnopqrstuvwxyz1234567890"), out)

    def test_redact_leaves_clean_text_alone(self) -> None:
        redactor = Redactor()
        out = redactor.redact("plain conversation text")
        self.assertEqual(out, "plain conversation text")

    def test_placeholder_is_deterministic(self) -> None:
        redactor = Redactor()
        first = redactor.placeholder("sk-secretvalue-example")
        second = redactor.placeholder("sk-secretvalue-example")
        self.assertEqual(first, second)

    def test_placeholder_format(self) -> None:
        redactor = Redactor()
        self.assertRegex(redactor.placeholder("sk-whatever"), r"^\[REDACTED:[0-9a-f]{12}\]$")


class RedactionDictTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_save_load_roundtrip(self) -> None:
        path = self.tmp / "dict.json"
        rdict = RedactionDict()
        rdict.add("sk-secret", "[REDACTED:abcd]")
        rdict.save(path)
        loaded = RedactionDict.load(path)
        self.assertEqual(loaded.resolve("sk-secret"), "[REDACTED:abcd]")

    def test_file_permissions_restrictive(self) -> None:
        path = self.tmp / "dict.json"
        RedactionDict().save(path)
        mode = path.stat().st_mode & 0o777
        self.assertTrue(mode <= 0o600)

    def test_add_then_resolve_roundtrip(self) -> None:
        rdict = RedactionDict()
        rdict.add("super-sensitive-value", "[REDACTED:00112233aabb]")
        self.assertEqual(rdict.resolve("super-sensitive-value"), "[REDACTED:00112233aabb]")


if __name__ == "__main__":
    unittest.main()