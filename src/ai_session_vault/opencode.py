"""OpenCode SQLite database adapter.

OpenCode stores its session history in a local SQLite database (typically at
``~/.local/share/opencode/opencode.db``). This adapter extracts individual
sessions incrementally into standard JSONL session files, allowing them to be
indexed, searched, and versioned by ``ai-session-vault``.

Two database layouts are supported:

* **v2** (current): ``session_v2`` plus ``session_message``. Every message row
  carries a JSON ``data`` document; assistant turns keep their text, reasoning
  and tool parts together in a ``content`` array.
* **v1** (legacy): ``session``, ``message`` and ``part`` tables, where parts
  are separate rows joined to messages by ``message_id``.

The v2 layout wins whenever it holds sessions; databases written before the
migration fall back to v1.
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

#: Message types in the v2 schema that belong to the conversation. Everything
#: else (``idle``, ``model-switched``, ``shell``) is bookkeeping for the UI.
V2_CONVERSATION_TYPES = frozenset({"user", "assistant", "system", "synthetic", "compaction"})

#: Upper bound for a single tool result kept in the exported record, so that a
#: chatty command cannot bloat the vault.
MAX_TOOL_OUTPUT = 4000


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

    uri = f"file:{db_file.resolve()}?mode=ro"
    try:
        con = sqlite3.connect(uri, uri=True)
    except Exception:
        con = sqlite3.connect(str(db_file))

    try:
        cur = con.cursor()
        if _has_v2_sessions(cur):
            return _export_v2_sessions(cur, out_dir, force)
        return _export_v1_sessions(cur, out_dir, force)
    finally:
        con.close()


# ------------------------------------------------------------------ schema

def _table_names(cur: sqlite3.Cursor) -> set[str]:
    cur.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
    return {row[0] for row in cur.fetchall()}


def _has_v2_sessions(cur: sqlite3.Cursor) -> bool:
    """Return True when the v2 tables exist and carry at least one session."""
    if not {"session_v2", "session_message"} <= _table_names(cur):
        return False
    cur.execute("SELECT 1 FROM session_v2 LIMIT 1")
    return cur.fetchone() is not None


# ------------------------------------------------------------- extraction

def _export_v2_sessions(cur: sqlite3.Cursor, out_dir: Path, force: bool) -> list[Path]:
    cur.execute(
        "SELECT id, time_created, time_updated FROM session_v2 ORDER BY time_updated ASC"
    )
    exported: list[Path] = []
    for s_id, t_created, t_updated in cur.fetchall():
        target_file = out_dir / f"{s_id}.jsonl"
        mtime_sec = _mtime_seconds(t_created, t_updated)
        if not force and _is_current(target_file, mtime_sec):
            exported.append(target_file)
            continue

        records = _v2_records(cur, s_id)
        _write_records(target_file, records, mtime_sec)
        exported.append(target_file)
    return exported


def _export_v1_sessions(cur: sqlite3.Cursor, out_dir: Path, force: bool) -> list[Path]:
    cur.execute(
        "SELECT id, time_created, time_updated FROM session ORDER BY time_updated ASC"
    )
    exported: list[Path] = []
    for s_id, t_created, t_updated in cur.fetchall():
        target_file = out_dir / f"{s_id}.jsonl"
        mtime_sec = _mtime_seconds(t_created, t_updated)
        if not force and _is_current(target_file, mtime_sec):
            exported.append(target_file)
            continue

        records = _v1_records(cur, s_id)
        _write_records(target_file, records, mtime_sec)
        exported.append(target_file)
    return exported


def _v2_records(cur: sqlite3.Cursor, session_id: str) -> list[dict[str, Any]]:
    cur.execute(
        "SELECT id, type, time_created, data FROM session_message "
        "WHERE session_id = ? ORDER BY seq ASC",
        (session_id,),
    )
    records: list[dict[str, Any]] = []
    for m_id, m_type, m_time, m_data_str in cur.fetchall():
        data = _parse_object(m_data_str)
        if data is None:
            continue
        record = _v2_record(m_id, session_id, m_type, m_time, data)
        if record is not None:
            records.append(record)
    return records


def _v2_record(
    message_id: str,
    session_id: str,
    message_type: str,
    row_time: int,
    data: dict[str, Any],
) -> dict[str, Any] | None:
    """Convert one ``session_message`` row into a vault record."""
    if message_type not in V2_CONVERSATION_TYPES:
        return None

    tool_calls: list[dict[str, Any]] = []
    if message_type == "assistant":
        content, thinking, tool_calls = _assistant_parts(data)
        role = "assistant"
    elif message_type == "user":
        content, thinking = _as_text(data.get("text")), ""
        role = "user"
    elif message_type == "compaction":
        content, thinking = _as_text(data.get("summary") or data.get("text")), ""
        role = "system"
    else:  # system / synthetic
        content, thinking = _as_text(data.get("text")), ""
        role = "system"

    if not content and not thinking and not tool_calls:
        return None

    return {
        "id": message_id,
        "sessionId": session_id,
        "role": role,
        "type": role,
        "time": _message_time(data) or row_time,
        "content": content,
        "thinking": thinking,
        "tool_calls": tool_calls,
    }


def _assistant_parts(data: dict[str, Any]) -> tuple[str, str, list[dict[str, Any]]]:
    """Split the assistant ``content`` array into text, reasoning and tools."""
    texts: list[str] = []
    reasonings: list[str] = []
    tool_calls: list[dict[str, Any]] = []

    blocks = data.get("content")
    if not isinstance(blocks, list):
        return "", "", []

    for block in blocks:
        if not isinstance(block, dict):
            continue
        block_type = block.get("type")
        if block_type == "text":
            text = _as_text(block.get("text"))
            if text:
                texts.append(text)
        elif block_type == "reasoning":
            text = _as_text(block.get("text"))
            if text:
                reasonings.append(text)
        elif block_type == "tool":
            tool_calls.append(_tool_call(block))

    return "\n".join(texts), "\n".join(reasonings), tool_calls


def _tool_call(block: dict[str, Any]) -> dict[str, Any]:
    state = block.get("state") if isinstance(block.get("state"), dict) else {}
    call: dict[str, Any] = {"name": block.get("name") or "unknown"}

    tool_input = state.get("input")
    if tool_input:
        call["input"] = tool_input

    output = _tool_output(state)
    if output:
        call["output"] = output[:MAX_TOOL_OUTPUT]
    return call


def _tool_output(state: dict[str, Any]) -> str:
    if state.get("status") == "error":
        error = _as_text(state.get("error"))
        if error:
            return error
    content = state.get("content")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        text = "\n".join(
            _as_text(block.get("text"))
            for block in content
            if isinstance(block, dict)
        )
        if text.strip():
            return text
    return ""


def _v1_records(cur: sqlite3.Cursor, session_id: str) -> list[dict[str, Any]]:
    cur.execute(
        "SELECT id, time_created, data FROM message "
        "WHERE session_id = ? ORDER BY time_created ASC",
        (session_id,),
    )
    msgs = cur.fetchall()

    cur.execute(
        "SELECT message_id, data FROM part WHERE session_id = ?",
        (session_id,),
    )
    parts = cur.fetchall()

    parts_by_msg: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for m_id, p_data_str in parts:
        p_data = _parse_object(p_data_str)
        if p_data is not None:
            parts_by_msg[m_id].append(p_data)

    records: list[dict[str, Any]] = []
    for m_id, m_time, m_data_str in msgs:
        m_data = _parse_object(m_data_str) or {}
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

        records.append(
            {
                "id": m_id,
                "sessionId": session_id,
                "role": role,
                "type": role,
                "time": m_time,
                "content": "\n".join(texts) if texts else "",
                "thinking": "\n".join(reasonings) if reasonings else "",
                "tool_calls": tool_calls,
            }
        )
    return records


# ----------------------------------------------------------------- helpers

def _parse_object(raw: Any) -> dict[str, Any] | None:
    try:
        data = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return None
    return data if isinstance(data, dict) else None


def _as_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False)
    return str(value)


def _message_time(data: dict[str, Any]) -> int | None:
    time_field = data.get("time")
    if isinstance(time_field, dict):
        created = time_field.get("created")
        if isinstance(created, (int, float)):
            return int(created)
    return None


def _mtime_seconds(created: int | None, updated: int | None) -> float:
    return (updated or created or 0) / 1000.0


def _is_current(target_file: Path, mtime_sec: float) -> bool:
    if not target_file.exists():
        return False
    try:
        return target_file.stat().st_mtime >= mtime_sec
    except OSError:
        return False


def _write_records(target_file: Path, records: list[dict[str, Any]], mtime_sec: float) -> None:
    with target_file.open("w", encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")

    try:
        if mtime_sec > 0:
            os.utime(target_file, (mtime_sec, mtime_sec))
    except OSError:
        pass
