"""Unit tests for the OpenCode SQLite database adapter."""

from __future__ import annotations

import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from ai_session_vault.opencode import extract_opencode_sessions
from ai_session_vault.session import derive_session_id, turn_count
from ai_session_vault.transcript import render_transcript


class OpenCodeAdapterTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.db_path = self.tmp / "opencode.db"
        self.output_dir = self.tmp / "sessions"
        self._setup_mock_db()

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _setup_mock_db(self) -> None:
        con = sqlite3.connect(str(self.db_path))
        cur = con.cursor()
        cur.execute("""
            CREATE TABLE session (
                id text PRIMARY KEY,
                project_id text NOT NULL,
                title text NOT NULL,
                directory text NOT NULL,
                time_created integer NOT NULL,
                time_updated integer NOT NULL
            );
        """)
        cur.execute("""
            CREATE TABLE message (
                id text PRIMARY KEY,
                session_id text NOT NULL,
                time_created integer NOT NULL,
                time_updated integer NOT NULL,
                data text NOT NULL
            );
        """)
        cur.execute("""
            CREATE TABLE part (
                id text PRIMARY KEY,
                message_id text NOT NULL,
                session_id text NOT NULL,
                time_created integer NOT NULL,
                time_updated integer NOT NULL,
                data text NOT NULL
            );
        """)

        # Insert 2 sessions
        cur.execute(
            "INSERT INTO session VALUES (?, ?, ?, ?, ?, ?)",
            ("ses_001", "proj_1", "Test Session 1", "/test/dir", 1000000, 1005000),
        )
        cur.execute(
            "INSERT INTO session VALUES (?, ?, ?, ?, ?, ?)",
            ("ses_002", "proj_1", "Test Session 2", "/test/dir", 2000000, 2005000),
        )

        # Messages for session 1
        cur.execute(
            "INSERT INTO message VALUES (?, ?, ?, ?, ?)",
            ("msg_001", "ses_001", 1001000, 1001000, json.dumps({"role": "user"})),
        )
        cur.execute(
            "INSERT INTO message VALUES (?, ?, ?, ?, ?)",
            ("msg_002", "ses_001", 1002000, 1002000, json.dumps({"role": "assistant"})),
        )

        # Parts for message 1 (user)
        cur.execute(
            "INSERT INTO part VALUES (?, ?, ?, ?, ?, ?)",
            ("prt_001", "msg_001", "ses_001", 1001000, 1001000, json.dumps({"type": "text", "text": "Hello OpenCode"})),
        )

        # Parts for message 2 (assistant): reasoning + tool + text
        cur.execute(
            "INSERT INTO part VALUES (?, ?, ?, ?, ?, ?)",
            ("prt_002", "msg_002", "ses_001", 1002000, 1002000, json.dumps({"type": "reasoning", "text": "Thinking about greeting"})),
        )
        cur.execute(
            "INSERT INTO part VALUES (?, ?, ?, ?, ?, ?)",
            ("prt_003", "msg_002", "ses_001", 1002050, 1002050, json.dumps({"type": "tool", "tool": "greet", "state": {"status": "completed"}})),
        )
        cur.execute(
            "INSERT INTO part VALUES (?, ?, ?, ?, ?, ?)",
            ("prt_004", "msg_002", "ses_001", 1002100, 1002100, json.dumps({"type": "text", "text": "Hello human!"})),
        )

        con.commit()
        con.close()

    def test_extract_creates_jsonl_files(self) -> None:
        exported = extract_opencode_sessions(self.db_path, self.output_dir)
        self.assertEqual(len(exported), 2)
        target1 = self.output_dir / "ses_001.jsonl"
        target2 = self.output_dir / "ses_002.jsonl"
        self.assertTrue(target1.exists())
        self.assertTrue(target2.exists())

    def test_extracted_session_content_and_turn_count(self) -> None:
        extract_opencode_sessions(self.db_path, self.output_dir)
        target1 = self.output_dir / "ses_001.jsonl"

        lines = [json.loads(line) for line in target1.read_text(encoding="utf-8").splitlines() if line.strip()]
        self.assertEqual(len(lines), 2)

        user_msg = lines[0]
        self.assertEqual(user_msg["role"], "user")
        self.assertEqual(user_msg["sessionId"], "ses_001")
        self.assertEqual(user_msg["content"], "Hello OpenCode")

        asst_msg = lines[1]
        self.assertEqual(asst_msg["role"], "assistant")
        self.assertEqual(asst_msg["content"], "Hello human!")
        self.assertEqual(asst_msg["thinking"], "Thinking about greeting")
        self.assertEqual(asst_msg["tool_calls"], [{"name": "greet"}])

        # Test interoperability with core session utilities
        from ai_session_vault.session import IdentifiedSession
        identified = IdentifiedSession.from_file(target1, "opencode")
        self.assertEqual(identified.session_id, "ses_001")
        self.assertEqual(turn_count(target1), 2)

    def test_transcript_rendering_of_opencode_session(self) -> None:
        extract_opencode_sessions(self.db_path, self.output_dir)
        target1 = self.output_dir / "ses_001.jsonl"
        transcript = render_transcript(target1)

        self.assertIn("user: Hello OpenCode", transcript)
        self.assertIn("assistant: Hello human!", transcript)

    def test_incremental_extraction_skips_unchanged_files(self) -> None:
        extract_opencode_sessions(self.db_path, self.output_dir)
        target1 = self.output_dir / "ses_001.jsonl"
        mtime_initial = target1.stat().st_mtime

        # Running again without updates should reuse existing file
        exported_second = extract_opencode_sessions(self.db_path, self.output_dir)
        self.assertEqual(len(exported_second), 2)
        self.assertEqual(target1.stat().st_mtime, mtime_initial)

    def test_missing_db_returns_empty_list(self) -> None:
        result = extract_opencode_sessions(self.tmp / "absent.db", self.output_dir)
        self.assertEqual(result, [])
