"""Text search over stored sessions.

Search runs over the *text* of each session (raw JSONL lines), which is the
same thing a human would grep for. No index, no daemon: the vault is just
files and git, so ``rg``/``grep`` work against the same data.

The module exposes a tiny pure function so it stays unit-testable without a
filesystem, alongside a streaming line-by-line file search helper.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path


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


def search_file(
    path: Path,
    query: str,
    case_sensitive: bool = False,
    max_snippets: int = 5,
    context_chars: int = 40,
) -> tuple[int, list[str]]:
    """Search a session file line by line without loading the entire file in RAM.

    Returns ``(match_count, snippets)`` where ``snippets`` contains up to
    ``max_snippets`` context windows surrounding the matches.
    """
    needle = query if case_sensitive else query.lower()
    if not needle:
        return 0, []

    total_matches = 0
    snippets: list[str] = []

    with path.open("r", encoding="utf-8", errors="replace") as handle:
        for line in handle:
            haystack = line if case_sensitive else line.lower()
            start = 0
            while True:
                offset = haystack.find(needle, start)
                if offset == -1:
                    break
                total_matches += 1
                if len(snippets) < max_snippets:
                    snippet_start = max(0, offset - context_chars)
                    snippet_end = min(len(line), offset + len(query) + context_chars)
                    snippet = line[snippet_start:snippet_end].replace("\n", " ").strip()
                    snippets.append(snippet)
                start = offset + len(query)

    return total_matches, snippets