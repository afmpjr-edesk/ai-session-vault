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


class OpenCodeV2AdapterTests(unittest.TestCase):
    """Coverage for the session_v2/session_message schema used by OpenCode v2."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.db_path = self.tmp / "opencode.db"
        self.output_dir = self.tmp / "sessions"
        self._setup_v2_db()

    def tearDown(self) -> None:
        self._tmp.cleanup()

    @staticmethod
    def _create_v2_tables(cur: sqlite3.Cursor) -> None:
        cur.execute("""
            CREATE TABLE session_v2 (
                id text PRIMARY KEY,
                project_id text NOT NULL,
                title text NOT NULL,
                directory text NOT NULL,
                time_created integer NOT NULL,
                time_updated integer NOT NULL
            );
        """)
        cur.execute("""
            CREATE TABLE session_message (
                id text PRIMARY KEY,
                session_id text NOT NULL,
                type text NOT NULL,
                seq integer NOT NULL,
                time_created integer NOT NULL,
                time_updated integer NOT NULL,
                data text NOT NULL
            );
        """)

    @staticmethod
    def _insert_message(
        cur: sqlite3.Cursor,
        session_id: str,
        seq: int,
        msg_type: str,
        data: dict,
        created: int,
    ) -> None:
        cur.execute(
            "INSERT INTO session_message VALUES (?, ?, ?, ?, ?, ?, ?)",
            (f"msg_{session_id}_{seq}", session_id, msg_type, seq, created, created, json.dumps(data)),
        )

    def _setup_v2_db(self) -> None:
        con = sqlite3.connect(str(self.db_path))
        cur = con.cursor()
        self._create_v2_tables(cur)

        cur.execute(
            "INSERT INTO session_v2 VALUES (?, ?, ?, ?, ?, ?)",
            ("ses_v2_001", "proj_1", "Cache refactor", "/work/repo", 3000000, 3005000),
        )
        cur.execute(
            "INSERT INTO session_v2 VALUES (?, ?, ?, ?, ?, ?)",
            ("ses_v2_002", "proj_1", "Small chat", "/work/repo", 4000000, 4005000),
        )

        self._insert_message(
            cur,
            "ses_v2_001",
            1,
            "user",
            {"time": {"created": 3001000}, "text": "Refactor the cache layer", "files": []},
            3001000,
        )
        self._insert_message(
            cur,
            "ses_v2_001",
            2,
            "assistant",
            {
                "time": {"created": 3002000},
                "agent": "build",
                "model": {"providerID": "opencode", "id": "some-model"},
                "content": [
                    {"type": "reasoning", "text": "Plan the refactor"},
                    {
                        "type": "tool",
                        "name": "read",
                        "state": {
                            "status": "completed",
                            "input": {"path": "cache.py"},
                            "content": [{"type": "text", "text": "def get(key): ..."}],
                        },
                    },
                    {"type": "text", "text": "Done"},
                ],
            },
            3002000,
        )
        self._insert_message(
            cur,
            "ses_v2_001",
            3,
            "idle",
            {"time": {"created": 3003000}, "outcome": "succeeded"},
            3003000,
        )
        self._insert_message(
            cur,
            "ses_v2_001",
            4,
            "model-switched",
            {"time": {"created": 3003500}, "model": {"id": "b"}, "previous": {"id": "a"}},
            3003500,
        )
        self._insert_message(
            cur,
            "ses_v2_001",
            5,
            "compaction",
            {"status": "completed", "reason": "auto", "summary": "## Objective\n- Refactor cache"},
            3004000,
        )

        self._insert_message(
            cur,
            "ses_v2_002",
            1,
            "system",
            {"time": {"created": 4001000}, "text": "The available tools have changed."},
            4001000,
        )
        self._insert_message(
            cur,
            "ses_v2_002",
            2,
            "synthetic",
            {"time": {"created": 4002000}, "text": "Continue if you have next steps."},
            4002000,
        )
        self._insert_message(
            cur,
            "ses_v2_002",
            3,
            "assistant",
            {
                "time": {"created": 4003000},
                "content": [{"type": "text", "text": "Nothing to do."}],
                "finish": "stop",
            },
            4003000,
        )

        con.commit()
        con.close()

    def _read_jsonl(self, session_id: str) -> list[dict]:
        target = self.output_dir / f"{session_id}.jsonl"
        return [json.loads(line) for line in target.read_text(encoding="utf-8").splitlines() if line.strip()]

    def test_extract_v2_creates_one_file_per_session(self) -> None:
        exported = extract_opencode_sessions(self.db_path, self.output_dir)
        self.assertEqual(len(exported), 2)
        self.assertTrue((self.output_dir / "ses_v2_001.jsonl").exists())
        self.assertTrue((self.output_dir / "ses_v2_002.jsonl").exists())

    def test_v2_user_and_assistant_records(self) -> None:
        extract_opencode_sessions(self.db_path, self.output_dir)
        lines = self._read_jsonl("ses_v2_001")

        user_msg = lines[0]
        self.assertEqual(user_msg["role"], "user")
        self.assertEqual(user_msg["sessionId"], "ses_v2_001")
        self.assertEqual(user_msg["content"], "Refactor the cache layer")

        asst_msg = lines[1]
        self.assertEqual(asst_msg["role"], "assistant")
        self.assertEqual(asst_msg["content"], "Done")
        self.assertEqual(asst_msg["thinking"], "Plan the refactor")
        self.assertEqual(asst_msg["tool_calls"][0]["name"], "read")
        self.assertEqual(asst_msg["tool_calls"][0]["input"], {"path": "cache.py"})
        self.assertIn("def get", asst_msg["tool_calls"][0]["output"])

    def test_v2_compaction_summary_is_kept_as_system_record(self) -> None:
        extract_opencode_sessions(self.db_path, self.output_dir)
        lines = self._read_jsonl("ses_v2_001")
        compaction = lines[-1]
        self.assertEqual(compaction["role"], "system")
        self.assertIn("## Objective", compaction["content"])

    def test_v2_skips_bookkeeping_message_types(self) -> None:
        extract_opencode_sessions(self.db_path, self.output_dir)
        types = [record["type"] for record in self._read_jsonl("ses_v2_001")]
        self.assertNotIn("idle", types)
        self.assertNotIn("model-switched", types)
        self.assertEqual(len(types), 3)

    def test_v2_system_and_synthetic_records(self) -> None:
        extract_opencode_sessions(self.db_path, self.output_dir)
        lines = self._read_jsonl("ses_v2_002")
        self.assertEqual([record["role"] for record in lines], ["system", "system", "assistant"])
        self.assertEqual(lines[1]["content"], "Continue if you have next steps.")

    def test_v2_turn_count(self) -> None:
        extract_opencode_sessions(self.db_path, self.output_dir)
        self.assertEqual(turn_count(self.output_dir / "ses_v2_001.jsonl"), 3)
        self.assertEqual(turn_count(self.output_dir / "ses_v2_002.jsonl"), 3)

    def test_v2_transcript_rendering(self) -> None:
        extract_opencode_sessions(self.db_path, self.output_dir)
        transcript = render_transcript(self.output_dir / "ses_v2_001.jsonl")
        self.assertIn("user: Refactor the cache layer", transcript)
        self.assertIn("assistant: Done", transcript)

    def test_v2_incremental_extraction_skips_unchanged_files(self) -> None:
        extract_opencode_sessions(self.db_path, self.output_dir)
        target = self.output_dir / "ses_v2_001.jsonl"
        mtime_initial = target.stat().st_mtime

        exported_second = extract_opencode_sessions(self.db_path, self.output_dir)
        self.assertEqual(len(exported_second), 2)
        self.assertEqual(target.stat().st_mtime, mtime_initial)

    def test_v2_preferred_over_legacy_tables(self) -> None:
        con = sqlite3.connect(str(self.db_path))
        cur = con.cursor()
        cur.execute("""
            CREATE TABLE session (
                id text PRIMARY KEY, project_id text NOT NULL, title text NOT NULL,
                directory text NOT NULL, time_created integer NOT NULL, time_updated integer NOT NULL
            );
        """)
        cur.execute("""
            CREATE TABLE message (
                id text PRIMARY KEY, session_id text NOT NULL,
                time_created integer NOT NULL, time_updated integer NOT NULL, data text NOT NULL
            );
        """)
        cur.execute("CREATE TABLE part (id text PRIMARY KEY, message_id text NOT NULL, session_id text NOT NULL, time_created integer NOT NULL, time_updated integer NOT NULL, data text NOT NULL);")
        cur.execute(
            "INSERT INTO session VALUES (?, ?, ?, ?, ?, ?)",
            ("ses_v2_001", "proj_1", "Legacy copy", "/work/repo", 3000000, 3005000),
        )
        cur.execute(
            "INSERT INTO message VALUES (?, ?, ?, ?, ?)",
            ("msg_legacy", "ses_v2_001", 3001000, 3001000, json.dumps({"role": "user"})),
        )
        cur.execute(
            "INSERT INTO part VALUES (?, ?, ?, ?, ?, ?)",
            ("prt_legacy", "msg_legacy", "ses_v2_001", 3001000, 3001000, json.dumps({"type": "text", "text": "legacy copy"})),
        )
        con.commit()
        con.close()

        extract_opencode_sessions(self.db_path, self.output_dir)
        contents = [record["content"] for record in self._read_jsonl("ses_v2_001")]
        self.assertNotIn("legacy copy", contents)
        self.assertIn("Refactor the cache layer", contents)

    def test_empty_v2_tables_fall_back_to_legacy(self) -> None:
        con = sqlite3.connect(str(self.db_path))
        cur = con.cursor()
        cur.execute("DELETE FROM session_message")
        cur.execute("DELETE FROM session_v2")
        cur.execute("""
            CREATE TABLE session (
                id text PRIMARY KEY, project_id text NOT NULL, title text NOT NULL,
                directory text NOT NULL, time_created integer NOT NULL, time_updated integer NOT NULL
            );
        """)
        cur.execute("""
            CREATE TABLE message (
                id text PRIMARY KEY, session_id text NOT NULL,
                time_created integer NOT NULL, time_updated integer NOT NULL, data text NOT NULL
            );
        """)
        cur.execute("CREATE TABLE part (id text PRIMARY KEY, message_id text NOT NULL, session_id text NOT NULL, time_created integer NOT NULL, time_updated integer NOT NULL, data text NOT NULL);")
        cur.execute(
            "INSERT INTO session VALUES (?, ?, ?, ?, ?, ?)",
            ("ses_legacy", "proj_1", "Legacy only", "/work/repo", 1000000, 1005000),
        )
        cur.execute(
            "INSERT INTO message VALUES (?, ?, ?, ?, ?)",
            ("msg_legacy", "ses_legacy", 1001000, 1001000, json.dumps({"role": "user"})),
        )
        cur.execute(
            "INSERT INTO part VALUES (?, ?, ?, ?, ?, ?)",
            ("prt_legacy", "msg_legacy", "ses_legacy", 1001000, 1001000, json.dumps({"type": "text", "text": "old world"})),
        )
        con.commit()
        con.close()

        exported = extract_opencode_sessions(self.db_path, self.output_dir)
        self.assertEqual(len(exported), 1)
        self.assertEqual(self._read_jsonl("ses_legacy")[0]["content"], "old world")
