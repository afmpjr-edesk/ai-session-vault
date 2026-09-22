"""Reversible redaction of secrets before content is shared or published.

Two complementary mechanisms:

* **low-entropy filter** — flags strings that *look* machine-generated (long
  mixes of letters, digits and punctuation) even when we have no pattern for
  them. This is the "global secret filter".
* **placeholder dictionary** — maps a secret to a deterministic ``[REDACTED:x]``
  token. The placeholder is what gets shared; the mapping can be persisted in a
  0600 file for later restoration, so redaction is reversible for the owner.

Model note: the vault itself keeps raw session snapshots locally (private on
the machine by default). Redaction is the sharing gateway — run it on a copy
before publishing or pushing so plain-text credentials never leave the machine.
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

# Matches long random-looking runs: letters+digits+`_-` of 24+ characters.
_LOW_ENTROPY = re.compile(r"[A-Za-z0-9_\-]{24,}")

# Known credential-bearing formats.
_PATTERNS = [
    re.compile(r"sk-[A-Za-z0-9_\-]{10,}"),
    re.compile(r"gh[pousr]_[A-Za-z0-9]{20,}"),
    re.compile(r"AKIA[0-9A-Z]{16}"),
    re.compile(r"Bearer\s+[A-Za-z0-9._\-]{20,}"),
    re.compile(r"xox[baprs]-[A-Za-z0-9_\-]{10,}"),
]


def low_entropy_hits(text: str, min_length: int = 24) -> list[str]:
    """Return substrings that look machine-generated (random tokens)."""
    hits: list[str] = []
    for match in _LOW_ENTROPY.findall(text):
        if len(match) >= min_length:
            hits.append(match)
    for pattern in _PATTERNS:
        hits.extend(pattern.findall(text))
    # De-duplicate, preserving order.
    seen: set[str] = set()
    unique: list[str] = []
    for hit in hits:
        if hit not in seen:
            seen.add(hit)
            unique.append(hit)
    return unique


class Redactor:
    """Finds secrets in text and replaces them with deterministic placeholders."""

    def __init__(self, min_length: int = 24, dictionary: "RedactionDict | None" = None) -> None:
        self.min_length = min_length
        self.dictionary = dictionary or RedactionDict()

    def placeholder(self, secret: str) -> str:
        digest = hashlib.sha256(secret.encode("utf-8")).hexdigest()[:12]
        return f"[REDACTED:{digest}]"

    def redact(self, text: str) -> str:
        """Replace candidate secrets with placeholders and record the mapping."""
        out = text
        for secret in low_entropy_hits(text, min_length=self.min_length):
            placeholder = self.placeholder(secret)
            self.dictionary.add(secret, placeholder)
            out = out.replace(secret, placeholder)
        return out


class RedactionDict:
    """Ordered mapping secret -> placeholder, persisted to a 0600 JSON file."""

    def __init__(self) -> None:
        self._data: dict[str, str] = {}

    def add(self, secret: str, placeholder: str) -> None:
        self._data[secret] = placeholder

    def resolve(self, secret: str) -> str:
        return self._data[secret]

    def mapping(self) -> dict[str, str]:
        return dict(self._data)

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(self._data, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        path.chmod(0o600)

    @classmethod
    def load(cls, path: Path) -> "RedactionDict":
        rdict = cls()
        if path.is_file():
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                data = {}
            if isinstance(data, dict):
                rdict._data = {str(k): str(v) for k, v in data.items()}
        return rdict