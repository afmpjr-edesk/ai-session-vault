"""Unit tests for transcript rendering."""

import tempfile
import unittest
from pathlib import Path

from ai_session_vault import transcript


def _render(lines: list[str]) -> str:
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "session.jsonl"
        path.write_text("".join(lines), encoding="utf-8")
        return transcript.render_transcript(path)


class TranscriptTests(unittest.TestCase):
    def test_string_content_renders(self) -> None:
        out = _render(
            [
                '{"type": "user", "message": {"role": "user", "content": "hello"}}\n',
                '{"type": "assistant", "message": {"role": "assistant", "content": "hi there"}}\n',
            ]
        )
        self.assertIn("user: hello", out)
        self.assertIn("assistant: hi there", out)

    def test_block_content_renders_text(self) -> None:
        out = _render(
            [
                '{"type": "assistant", "message": {"role": "assistant", '
                '"content": [{"type": "text", "text": "block text"}]}}\n'
            ]
        )
        self.assertIn("block text", out)

    def test_malformed_line_is_skipped(self) -> None:
        out = _render(["not json\n", '{"type": "user", "message": {"role": "user", "content": "ok"}}\n'])
        self.assertIn("ok", out)
        self.assertNotIn("not json", out)

    def test_unescapes_backslashes(self) -> None:
        out = _render(['{"type": "user", "message": {"role": "user", "content": "line1\\nline2"}}\n'])
        self.assertIn("line1\nline2", out)

    def test_missing_role_falls_back_to_type(self) -> None:
        out = _render(['{"type": "user", "message": {"content": "no role"}}\n'])
        self.assertIn("user: no role", out)


if __name__ == "__main__":
    unittest.main()