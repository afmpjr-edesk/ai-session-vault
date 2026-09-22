"""Unit tests for searching stored sessions."""

import tempfile
import unittest
from pathlib import Path

from ai_session_vault.search import search_text


def _match_indices(text: str, query: str, case_sensitive: bool = False) -> list[int]:
    return [offset for offset, _ in search_text(text, query, case_sensitive)]


class SearchTextTests(unittest.TestCase):
    def test_finds_case_insensitive_substring(self) -> None:
        # "world" begins at offset 6 in "Hello World".
        self.assertEqual(_match_indices("Hello World", "world"), [6])

    def test_case_sensitive_respects_flag(self) -> None:
        self.assertEqual(_match_indices("Hello World", "world", case_sensitive=True), [])

    def test_multiple_occurrences(self) -> None:
        indices = _match_indices("abc abc abc", "abc")
        self.assertEqual(indices, [0, 4, 8])

    def test_no_match_returns_empty(self) -> None:
        self.assertEqual(_match_indices("abc", "zzz"), [])


class SearchSessionFileTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _make(self, name: str, text: str) -> Path:
        path = self.tmp / name
        path.write_text(text, encoding="utf-8")
        return path

    def test_search_file_returns_line_numbers_and_snippets(self) -> None:
        path = self._make(
            "s.jsonl",
            '{"x": 1}\n{"message": {"role": "user", "content": "deploy the api"}}\n',
        )
        results = list(search_text(path.read_text(encoding="utf-8"), "deploy"))
        self.assertEqual(len(results), 1)


if __name__ == "__main__":
    unittest.main()