"""Session model and JSONL parsing.

Sessions are JSONL files where each line is one JSON record. We treat the
format tolerance as a first-class concern: agent runtimes write different
shapes, so all parsing here must degrade gracefully on malformed input.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterator

SESSION_ID_FIELDS = ("sessionId", "session_id", "uuid", "conversationId")
NESTED_ID_CONTAINERS = ("payload", "message")
MAX_SESSION_ID = 64


def iter_records(path: Path) -> Iterator[dict[str, Any]]:
    """Yield each JSON object found on a line of a JSONL file.

    Malformed lines are skipped silently; empty lines are ignored.
    """
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
                yield record


def sha256_file(path: Path) -> str:
    """Return the hex SHA-256 of the raw file bytes."""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def turn_count(path: Path) -> int:
    """Count message-bearing records in a session file.

    A record counts as a turn if it has a ``message`` key with a ``role``, a
    top-level ``role`` field, or a ``payload``/``message`` object with a
    ``role`` (codex ``response_item`` records nest ``role`` in ``payload``).
    Antigravity records count if their type is ``USER_INPUT`` or
    ``PLANNER_RESPONSE``, or source is ``USER_EXPLICIT`` or ``MODEL``.
    Malformed lines never count.
    """
    count = 0
    for record in iter_records(path):
        message = record.get("message")
        if isinstance(message, dict) and message.get("role"):
            count += 1
            continue
        if record.get("role"):
            count += 1
            continue
        payload = record.get("payload")
        if isinstance(payload, dict) and payload.get("role"):
            count += 1
            continue
        rec_type = record.get("type")
        if rec_type in ("USER_INPUT", "PLANNER_RESPONSE"):
            count += 1
            continue
        if record.get("source") in ("USER_EXPLICIT", "MODEL"):
            count += 1
            continue
    return count


def derive_session_id(path: Path, embedded_id: str | None) -> str:
    """Calculate a stable, short session identifier.

    Priority: a session identifier embedded in the file (first field from
    ``SESSION_ID_FIELDS``), then an ancestor directory matching a UUID pattern
    (for runtimes like Antigravity that store transcripts in ``brain/<uuid>/...``),
    then the filename (minus extension). The result is sanitised to a safe slug;
    a blank result falls back to a digest of the absolute path. Long values are
    capped at ``MAX_SESSION_ID`` characters — long enough to keep UUIDs (36 chars)
    intact.
    """
    if embedded_id:
        slug = re.sub(r"[^a-zA-Z0-9._-]", "-", embedded_id)
        if slug:
            return slug[:MAX_SESSION_ID]
    if path.stem in ("transcript", "transcript_full"):
        for part in reversed(path.parts[:-1]):
            if re.match(r"^[0-9a-fA-F-]{36}$", part):
                return part[:MAX_SESSION_ID]
    base = path.stem
    slug = re.sub(r"[^a-zA-Z0-9._-]", "-", base)
    if slug:
        return slug[:MAX_SESSION_ID]
    return hashlib.sha256(str(path.absolute()).encode("utf-8")).hexdigest()[:12]


def _first_embedded_id(path: Path) -> str | None:
    """Return the first session identifier embedded in the file, if any.

    Some runtimes nest the identifier inside a container object: codex writes
    ``{"type": "session_meta", "payload": {"session_id": "..."}}`` and claude
    messages keep ``sessionId`` at the top level. The search looks at top-level
    fields first, then inside ``payload``/``message`` objects, so codex and
    claude files are both handled regardless of shape.
    """
    for record in iter_records(path):
        for key in SESSION_ID_FIELDS:
            value = record.get(key)
            if isinstance(value, str) and value:
                return value
        for container_name in NESTED_ID_CONTAINERS:
            container = record.get(container_name)
            if not isinstance(container, dict):
                continue
            for key in SESSION_ID_FIELDS:
                value = container.get(key)
                if isinstance(value, str) and value:
                    return value
    return None


def session_meta(path: Path, runtime: str, session_id: str) -> dict[str, Any]:
    """Build a metadata sidecar dict for a session file."""
    turns = turn_count(path)
    return {
        "runtime": runtime,
        "session_id": session_id,
        "turns": turns,
        "bytes": path.stat().st_size,
        "sha256": sha256_file(path),
        "source": str(path.absolute()),
        "mtime": int(path.stat().st_mtime),
    }


@dataclass(frozen=True)
class IdentifiedSession:
    """A session file together with its calculated identifier."""

    path: Path
    runtime: str
    session_id: str

    @classmethod
    def from_file(cls, path: Path, runtime: str) -> "IdentifiedSession":
        return cls(
            path=path,
            runtime=runtime,
            session_id=derive_session_id(path, _first_embedded_id(path)),
        )

    @property
    def filename(self) -> str:
        return f"{self.session_id}.jsonl"

    def meta(self) -> dict[str, Any]:
        return session_meta(self.path, self.runtime, self.session_id)