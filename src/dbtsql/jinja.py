"""Mask Jinja so SQL tooling sees plain SQL at the same character offsets.

An expression `{{ ... }}` becomes an identifier of `j`s, so `from {{ ref('x') }}`
still reads as `from <name>`. A statement `{% ... %}` and a comment `{# ... #}`
become spaces. Newlines stay where they were, so lines and offsets in the
masked text are the lines and offsets of the source.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

_CLOSE = {"{{": "}}", "{%": "%}", "{#": "#}"}
_WORD = re.compile(r"[A-Za-z_]\w*")


@dataclass(frozen=True)
class Tag:
    """One Jinja tag. `end` is exclusive."""

    kind: str  # "expr", "stmt", or "comment"
    start: int
    end: int
    body: str

    @property
    def keyword(self) -> str:
        """The first word of a statement: `if`, `for`, `macro`, `endmacro`, ..."""

        found = _WORD.search(self.body)
        return found.group(0).lower() if found else ""


@dataclass(frozen=True)
class Masked:
    text: str
    tags: tuple[Tag, ...]

    def in_tag(self, offset: int) -> bool:
        return any(tag.start <= offset < tag.end for tag in self.tags)


def _kind(raw: str) -> str:
    return {"{{": "expr", "{%": "stmt", "{#": "comment"}[raw[:2]]


def _body(raw: str) -> str:
    return raw[2:-2].strip("-+ \t\r\n")


def _blank(raw: str) -> str:
    return "".join(ch if ch == "\n" else " " for ch in raw)


def _identifier(raw: str) -> str:
    """`j`s up to the first newline, then blanks, so the width never changes."""

    first, newline, rest = raw.partition("\n")
    return "j" * len(first) + newline + _blank(rest)


def _tag_end(source: str, start: int) -> int:
    """End of the tag opened at `start`. A quoted `}}` inside it does not close it."""

    close = _CLOSE[source[start : start + 2]]
    index = start + 2
    quote = None
    while index < len(source):
        char = source[index]
        if quote is not None:
            if char == "\\":
                index += 1
            elif char == quote:
                quote = None
        elif char in "'\"" and close != "#}":
            quote = char
        elif source.startswith(close, index):
            return index + 2
        index += 1
    return len(source)


def _tag_starts(source: str):
    index = source.find("{")
    while 0 <= index < len(source) - 1:
        if source[index : index + 2] in _CLOSE:
            end = _tag_end(source, index)
            yield index, end
            index = source.find("{", end)
        else:
            index = source.find("{", index + 1)


def mask(source: str) -> Masked:
    pieces: list[str] = []
    tags: list[Tag] = []
    cursor = 0
    for start, end in _tag_starts(source):
        raw = source[start:end]
        kind = _kind(raw)
        tags.append(Tag(kind, start, end, _body(raw)))
        pieces.append(source[cursor:start])
        pieces.append(_identifier(raw) if kind == "expr" else _blank(raw))
        cursor = end
    pieces.append(source[cursor:])
    return Masked("".join(pieces), tuple(tags))
