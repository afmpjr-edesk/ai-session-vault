"""OpenCode SQLite database adapter.

OpenCode stores its session history in a local SQLite database (typically at
``~/.local/share/opencode/opencode.db``). This adapter extracts individual
sessions incrementally into standard JSONL session files, allowing them to be
indexed, searched, and versioned by ``ai-session-vault``.
"""

from __future__ import annotations

import json
import os
import sqlite3
from collections import defaultdict
from pathlib import Path
from typing import Any

DEFAULT_OPENCODE_DB = Path.home() / ".local" / "share" / "opencode" / "opencode.db"
DEFAULT_OPENCODE_SESSIONS_DIR = Path.home() / ".local" / "share" / "opencode" / "sessions"


def extract_opencode_sessions(
    db_path: Path | str | None = None,
    output_dir: Path | str | None = None,
    force: bool = False,
) -> list[Path]:
    """Extract sessions from an OpenCode SQLite database into JSONL files.

    Extraction is incremental: if a session's target JSONL file exists and its
    modification timestamp is at or newer than the session's ``time_updated``,
    it is skipped unless ``force`` is True.

    Returns the list of exported JSONL paths.
    """
    db_file = Path(os.path.expanduser(str(db_path))) if db_path else DEFAULT_OPENCODE_DB
    out_dir = Path(os.path.expanduser(str(output_dir))) if output_dir else DEFAULT_OPENCODE_SESSIONS_DIR

    if not db_file.exists():
        return []

    out_dir.mkdir(parents=True, exist_ok=True)
    exported_files: list[Path] = []

    uri = f"file:{db_file.resolve()}?mode=ro"
    try:
        con = sqlite3.connect(uri, uri=True)
    except Exception:
        con = sqlite3.connect(str(db_file))

    try:
        cur = con.cursor()
        cur.execute(
            "SELECT id, title, directory, time_created, time_updated "
            "FROM session ORDER BY time_updated ASC"
        )
        sessions = cur.fetchall()

        for s_id, title, directory, t_created, t_updated in sessions:
            target_file = out_dir / f"{s_id}.jsonl"
            mtime_sec = (t_updated or t_created or 0) / 1000.0

            if not force and target_file.exists():
                try:
                    if target_file.stat().st_mtime >= mtime_sec:
                        exported_files.append(target_file)
                        continue
                except OSError:
                    pass

            cur.execute(
                "SELECT id, time_created, data FROM message "
                "WHERE session_id = ? ORDER BY time_created ASC",
                (s_id,),
            )
            msgs = cur.fetchall()

            cur.execute(
                "SELECT message_id, data FROM part WHERE session_id = ?",
                (s_id,),
            )
            parts = cur.fetchall()

            parts_by_msg: dict[str, list[dict[str, Any]]] = defaultdict(list)
            for m_id, p_data_str in parts:
                try:
                    p_data = json.loads(p_data_str)
                    if isinstance(p_data, dict):
                        parts_by_msg[m_id].append(p_data)
                except (json.JSONDecodeError, TypeError):
                    continue

            records: list[dict[str, Any]] = []
            for m_id, m_time, m_data_str in msgs:
                try:
                    m_data = json.loads(m_data_str)
                except (json.JSONDecodeError, TypeError):
                    m_data = {}

                role = m_data.get("role", "agent")
                p_list = parts_by_msg.get(m_id, [])

                texts = [
                    p["text"]
                    for p in p_list
                    if p.get("type") == "text" and isinstance(p.get("text"), str)
                ]
                reasonings = [
                    p["text"]
                    for p in p_list
                    if p.get("type") == "reasoning" and isinstance(p.get("text"), str)
                ]
                tool_calls = [
                    {"name": p.get("tool", "unknown")}
                    for p in p_list
                    if p.get("type") == "tool"
                ]

                record: dict[str, Any] = {
                    "id": m_id,
                    "sessionId": s_id,
                    "role": role,
                    "type": role,
                    "time": m_time,
                    "content": "\n".join(texts) if texts else "",
                    "thinking": "\n".join(reasonings) if reasonings else "",
                    "tool_calls": tool_calls,
                }
                records.append(record)

            with target_file.open("w", encoding="utf-8") as handle:
                for rec in records:
                    handle.write(json.dumps(rec, ensure_ascii=False) + "\n")

            try:
                if mtime_sec > 0:
                    os.utime(target_file, (mtime_sec, mtime_sec))
            except OSError:
                pass

            exported_files.append(target_file)

    finally:
        con.close()

    return exported_files
