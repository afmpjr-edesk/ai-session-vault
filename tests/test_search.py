"""Unit tests for searching stored sessions."""

import tempfile
import unittest
from pathlib import Path

from ai_session_vault.search import search_file, search_text


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

    def test_search_file_streaming_finds_matches_and_snippets(self) -> None:
        path = self._make(
            "stream.jsonl",
            '{"line": 1, "text": "alpha beta gamma"}\n'
            '{"line": 2, "text": "delta beta epsilon"}\n'
            '{"line": 3, "text": "zeta eta theta"}\n',
        )
        count, snippets = search_file(path, "beta")
        self.assertEqual(count, 2)
        self.assertEqual(len(snippets), 2)
        self.assertTrue(any("alpha beta gamma" in s for s in snippets))
        self.assertTrue(any("delta beta epsilon" in s for s in snippets))

    def test_search_file_empty_query_returns_zero(self) -> None:
        path = self._make("empty.jsonl", '{"a": 1}\n')
        count, snippets = search_file(path, "")
        self.assertEqual(count, 0)
        self.assertEqual(snippets, [])

    def test_search_file_respects_max_snippets(self) -> None:
        path = self._make("multi.jsonl", "match\nmatch\nmatch\nmatch\n")
        count, snippets = search_file(path, "match", max_snippets=2)
        self.assertEqual(count, 4)
        self.assertEqual(len(snippets), 2)


if __name__ == "__main__":
    unittest.main()