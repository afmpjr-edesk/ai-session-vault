"""Human-readable rendering of agent session JSONL files.

The goal is a lossy-but-faithful text summary: something you can skim, grep,
paste into a review, or hand to a teammate — not a lossless replay. For lossless
access the raw JSONL snapshot always stays in the vault.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterable


def _content_text(content: Any) -> str:
    """Extract a string from the possible ``content`` shapes used by agents."""
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for block in content:
            if isinstance(block, str):
                parts.append(block)
            elif isinstance(block, dict):
                text = block.get("text") or block.get("content") or block.get("input")
                if isinstance(text, str):
                    parts.append(text)
                elif isinstance(text, dict):
                    parts.append(json.dumps(text, ensure_ascii=False))
        return "\n".join(parts)
    if isinstance(content, dict):
        return json.dumps(content, ensure_ascii=False)
    return str(content)


def _truncate(text: str, limit: int = 4000) -> str:
    if len(text) <= limit:
        return text
    return text[:limit] + "\n[... truncated ...]"


def render_record(record: dict[str, Any]) -> str | None:
    """Render a single JSONL record to one or more text lines, or None to skip."""
    message = record.get("message")
    if not isinstance(message, dict):
        return None

    title = "user" if record.get("type") == "user" else None
    role = message.get("role") or title or record.get("type") or "agent"
    content = _content_text(message.get("content"))
    if not content:
        tool_use = message.get("tool_use")
        if isinstance(tool_use, dict) and tool_use.get("name"):
            content = f"[tool: {tool_use['name']}]"
        else:
            return None

    label = str(role).strip()
    return f"{label}: {_truncate(content)}"


def render_transcript(path: Path, max_records: int | None = None) -> str:
    """Render a JSONL session file as readable text, one line per message."""
    lines: list[str] = []
    with path.open("r", encoding="utf-8", errors="replace") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue
            if max_records is not None and len(lines) >= max_records:
                break
            if isinstance(record, dict):
                text = render_record(record)
                if text is not None:
                    lines.append(text)
    return "\n".join(lines)


def iter_record_text(path: Path) -> Iterable[str]:
    """Yield each rendered record line without building the whole string."""
    with path.open("r", encoding="utf-8", errors="replace") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(record, dict):
                text = render_record(record)
                if text is not None:
                    yield text