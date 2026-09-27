"""Unit tests for session parsing and metadata extraction."""

import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from ai_session_vault import session


def _write_sessions(tmp: Path, lines: list[dict]) -> Path:
    path = tmp / "session.jsonl"
    path.write_text(
        "".join(json.dumps(line, separators=(",", ":")) + "\n" for line in lines),
        encoding="utf-8",
    )
    return path


class SessionParsingTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_iter_records_yields_valid_json_lines_only(self) -> None:
        path = self.tmp / "mixed.jsonl"
        path.write_text('{"a": 1}\nnot json\n{"b": 2}\n', encoding="utf-8")
        records = list(session.iter_records(path))
        self.assertEqual(records, [{"a": 1}, {"b": 2}])

    def test_sha256_of_file(self) -> None:
        path = self.tmp / "data.jsonl"
        path.write_text('{"x": 1}\n', encoding="utf-8")
        expected = hashlib.sha256(b'{"x": 1}\n').hexdigest()
        self.assertEqual(session.sha256_file(path), expected)

    def test_turn_count_counts_message_records(self) -> None:
        path = _write_sessions(
            self.tmp,
            [
                {"type": "user", "message": {"role": "user", "content": "hi"}},
                {"type": "assistant", "message": {"role": "assistant", "content": "hello"}},
                {"type": "user", "message": {"role": "user", "content": "again"}},
            ],
        )
        self.assertEqual(session.turn_count(path), 3)

    def test_turn_count_counts_codex_payload_records(self) -> None:
        path = _write_sessions(
            self.tmp,
            [
                {"type": "session_meta", "payload": {"session_id": "abc"}},
                {"type": "response_item", "payload": {"type": "message", "role": "user", "content": "hi"}},
                {"type": "response_item", "payload": {"type": "message", "role": "assistant", "content": "hi"}},
            ],
        )
        self.assertEqual(session.turn_count(path), 2)

    def test_first_embedded_id_finds_nested_codex_payload(self) -> None:
        path = _write_sessions(
            self.tmp,
            [
                {"type": "session_meta", "payload": {"session_id": "01a0761e-8f99"}},
            ],
        )
        self.assertEqual(session._first_embedded_id(path), "01a0761e-8f99")

    def test_derive_session_id_extracts_codex_payload_id(self) -> None:
        path = _write_sessions(
            self.tmp,
            [
                {"type": "session_meta", "payload": {"session_id": "01a0761e-8f99-7442-8b07-12fcd5f07e1c"}},
            ],
        )
        self.assertEqual(
            session.derive_session_id(path, session._first_embedded_id(path)),
            "01a0761e-8f99-7442-8b07-12fcd5f07e1c",
        )

    def test_turn_count_skips_malformed_lines(self) -> None:
        path = self.tmp / "bad.jsonl"
        path.write_text('{"type": "user", "message": {"role": "user", "content": "one"}}\nnot json\n{}\n', encoding="utf-8")
        self.assertEqual(session.turn_count(path), 1)

    def test_derive_session_id_uses_embedded_id(self) -> None:
        self.assertEqual(
            session.derive_session_id(Path("/tmp/x.jsonl"), "MY-UUID"),
            "MY-UUID",
        )

    def test_derive_session_id_uses_embedded_id_even_with_filename(self) -> None:
        self.assertEqual(
            session.derive_session_id(Path("/tmp/other-name.jsonl"), "EMBEDDED-ID"),
            "EMBEDDED-ID",
        )

    def test_derive_session_id_shortens_long_values(self) -> None:
        self.assertEqual(
            session.derive_session_id(Path("/tmp/x.jsonl"), "A" * 100),
            "A" * 64,
        )

    def test_derive_session_id_keeps_uuid_untouched(self) -> None:
        uuid_ = "1dbb8ce4-0e5d-4c5e-a017-d12f12a29d98"
        self.assertEqual(session.derive_session_id(Path("/tmp/x.jsonl"), uuid_), uuid_)

    def test_derive_session_id_falls_back_to_filename_stem(self) -> None:
        path = Path("/tmp/abc-123.jsonl")
        # No embedded identifier -> use the sanitised filename stem.
        self.assertEqual(session.derive_session_id(path, None), "abc-123")

    def test_derive_session_id_sanitises_filename_stem(self) -> None:
        path = Path("/tmp/my session/file!.jsonl")
        # Only the filename stem is used, then sanitised.
        self.assertEqual(session.derive_session_id(path, None), "file-")

    def test_meta_snapshot_includes_source_and_counts(self) -> None:
        path = _write_sessions(
            self.tmp,
            [
                {"type": "user", "message": {"role": "user", "content": "hi"}},
                {"type": "assistant", "message": {"role": "assistant", "content": "bye"}},
            ],
        )
        meta = session.session_meta(path, runtime="claude", session_id="abc")
        self.assertEqual(meta["runtime"], "claude")
        self.assertEqual(meta["session_id"], "abc")
        self.assertEqual(meta["turns"], 2)
        self.assertEqual(meta["sha256"], session.sha256_file(path))
        self.assertEqual(meta["bytes"], path.stat().st_size)

    def test_derive_session_id_extracts_antigravity_ancestor_uuid(self) -> None:
        path = Path(
            "/home/user/.gemini/antigravity/brain/ea28cd4a-12ac-4e67-80fc-f1be811b9b8f/.system_generated/logs/transcript.jsonl"
        )
        self.assertEqual(
            session.derive_session_id(path, None),
            "ea28cd4a-12ac-4e67-80fc-f1be811b9b8f",
        )

    def test_turn_count_counts_antigravity_records(self) -> None:
        path = _write_sessions(
            self.tmp,
            [
                {"step_index": 0, "type": "USER_INPUT", "source": "USER_EXPLICIT", "content": "hello"},
                {"step_index": 1, "type": "PLANNER_RESPONSE", "source": "MODEL", "content": "response"},
                {"step_index": 2, "type": "CHECKPOINT", "source": "SYSTEM"},
            ],
        )
        self.assertEqual(session.turn_count(path), 2)


if __name__ == "__main__":
    unittest.main()