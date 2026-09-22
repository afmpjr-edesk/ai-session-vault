"""Text search over stored sessions.

Search runs over the *text* of each session (raw JSONL lines), which is the
same thing a human would grep for. No index, no daemon: the vault is just
files and git, so ``rg``/``grep`` work against the same data.

The module exposes a tiny pure function so it stays unit-testable without a
filesystem.
"""

from __future__ import annotations

from collections.abc import Iterator


def search_text(text: str, query: str, case_sensitive: bool = False) -> Iterator[tuple[int, int]]:
    """Yield ``(offset, length)`` of every match of ``query`` in ``text``.

    Offsets are character offsets in the input ``text``.
    """
    haystack = text if case_sensitive else text.lower()
    needle = query if case_sensitive else query.lower()
    if not needle:
        return
    start = 0
    while True:
        offset = haystack.find(needle, start)
        if offset == -1:
            break
        yield offset, len(query)
        start = offset + len(query)