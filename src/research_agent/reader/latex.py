"""Read a LaTeX submission's text without running TeX (SDD-MD-10).

A multi-file submission keeps its body in files the root pulls in with
`\\input` and `\\include`. `resolve_submission` picks the root and inlines
those files textually: relative paths only, `.tex` implied, at most
`MAX_INPUT_DEPTH` levels, nothing expanded or executed. The lexical helpers
here are shared with `reader.extract`, which must skip the same commented
text this module skips.
"""

from __future__ import annotations

import bisect
import posixpath
import re
from collections.abc import Callable, Mapping

__all__ = [
    "MAX_INPUT_DEPTH",
    "MAX_RESOLVED_CHARS",
    "brace_group",
    "hidden_by_comment",
    "resolve_submission",
]

MAX_INPUT_DEPTH = 8
# A bound on inlined text, so a file included from many places cannot
# multiply the submission without limit.
MAX_RESOLVED_CHARS = 16 * 1024 * 1024

_INPUT = re.compile(
    r"\\(?:input|include)(?![A-Za-z@])[ \t]*"
    r"(?:\{(?P<braced>[^{}\n]+)\}|(?P<bare>[^\s{}%\\]+))"
)
_DOCUMENTCLASS = re.compile(r"^[ \t]*\\document(?:class|style)\b", re.MULTILINE)
_BEGIN_DOCUMENT = re.compile(r"\\begin\{document\}")
# A `%` after an even run of backslashes (none, or `\\` line breaks) starts a
# comment; `\%` is a literal percent sign.
_LINE_COMMENT = re.compile(r"(?<!\\)(?:\\\\)*(%[^\n]*)")
_HIDDEN_REGION = re.compile(
    r"\\begin\{comment\}.*?(?:\\end\{comment\}|\Z)"
    r"|\\iffalse(?![A-Za-z@]).*?(?:\\fi(?![A-Za-z@])|\Z)",
    re.DOTALL,
)


def brace_group(text: str, start: int) -> int | None:
    """The index just past the group opened by `text[start] == "{"`.

    Escaped braces do not count. An unbalanced group returns `None`.
    """

    if start >= len(text) or text[start] != "{":
        return None
    depth = 0
    index = start
    while index < len(text):
        char = text[index]
        if char == "\\":
            index += 2
            continue
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return index + 1
        index += 1
    return None


class _Spans:
    """Disjoint, ordered spans with a containment test."""

    def __init__(self) -> None:
        self.starts: list[int] = []
        self.ends: list[int] = []

    def add(self, start: int, end: int) -> None:
        self.starts.append(start)
        self.ends.append(end)

    def __contains__(self, position: int) -> bool:
        slot = bisect.bisect_right(self.starts, position) - 1
        return slot >= 0 and position < self.ends[slot]


def hidden_by_comment(text: str) -> Callable[[int], bool]:
    """A predicate: is the character at a position commented out?

    Covers `%` line comments, `comment` environments and `\\iffalse` blocks
    (up to the first `\\fi`). Spans are found once, so a test costs a
    bisection however long the line.
    """

    comments = _Spans()
    for match in _LINE_COMMENT.finditer(text):
        comments.add(match.start(1), match.end(1))
    regions = _Spans()
    position = 0
    while (region := _HIDDEN_REGION.search(text, position)) is not None:
        if region.start() in comments:
            position = region.start() + 1
            continue
        regions.add(region.start(), region.end())
        position = max(region.end(), region.start() + 1)
    return lambda position: position in comments or position in regions


def _normalized(name: str) -> str:
    return posixpath.normpath(name.replace("\\", "/")).lstrip("/")


def _target(files: Mapping[str, str], including: str, reference: str) -> str | None:
    reference = reference.strip()
    if not reference or reference.startswith("/"):
        return None
    if not reference.lower().endswith(".tex"):
        reference += ".tex"
    # TeX resolves from the directory it runs in, the submission root; the
    # including file's own directory is the common author expectation.
    for directory in ("", posixpath.dirname(including)):
        candidate = posixpath.normpath(posixpath.join(directory, reference))
        if candidate == ".." or candidate.startswith("../"):
            continue
        if candidate in files:
            return candidate
    return None


def _inline(files: Mapping[str, str], root: str) -> str:
    budget = [MAX_RESOLVED_CHARS - len(files[root])]

    def expand(name: str, depth: int, stack: frozenset[str]) -> str:
        text = files[name]
        hidden = hidden_by_comment(text)
        parts: list[str] = []
        cursor = 0
        for match in _INPUT.finditer(text):
            if depth >= MAX_INPUT_DEPTH or hidden(match.start()):
                continue
            reference = match.group("braced") or match.group("bare") or ""
            target = _target(files, name, reference)
            if target is None or target in stack:
                continue
            if len(files[target]) > budget[0]:
                continue
            budget[0] -= len(files[target])
            parts.append(text[cursor : match.start()])
            parts.append(expand(target, depth + 1, stack | {target}))
            cursor = match.end()
        parts.append(text[cursor:])
        return "".join(parts)

    return expand(root, 0, frozenset({root}))


def resolve_submission(files: Mapping[str, str]) -> str | None:
    """One submission's LaTeX with its `\\input` and `\\include` files inlined.

    *files* maps each `.tex` member's path in the submission to its decoded
    text. The root is a file that declares `\\documentclass` or begins a
    document; when several do (a standalone figure beside the paper), the
    one whose resolved text is longest, then the first by name. With no
    such file, every file is a candidate. Returns `None` for no files.
    """

    normalized = {_normalized(name): text for name, text in files.items()}
    if not normalized:
        return None
    roots = [
        name
        for name, text in normalized.items()
        if _DOCUMENTCLASS.search(text) or _BEGIN_DOCUMENT.search(text)
    ] or list(normalized)
    best: str | None = None
    for name in sorted(roots):
        resolved = _inline(normalized, name)
        if best is None or len(resolved) > len(best):
            best = resolved
    return best
