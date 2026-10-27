"""The scored units of a dbt SQL file, and their cyclomatic complexity.

A model's units are its top-level CTEs and the final select, named `main`.
A model without CTEs is one `main`. A file that defines Jinja macros, tests,
or materializations has one unit per definition instead.

Decision points, one each:
  SQL    WHEN, AND, OR (not the AND of BETWEEN), WHERE, HAVING, QUALIFY,
         and a call to IFF, COALESCE, NVL, NVL2, IFNULL, or DECODE.
  Jinja  {% if %}, {% elif %}, {% for %}, an inline `if` in {{ }}, and each
         `and` / `or` inside a tag.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from dbtsql.jinja import Masked, Tag, mask
from dbtsql.tokens import Token, closing, line_of, tokenize

_SQL_DECISIONS = {"WHEN", "OR", "WHERE", "HAVING", "QUALIFY"}
_BRANCHING_CALLS = {"IFF", "COALESCE", "NVL", "NVL2", "IFNULL", "DECODE"}
_JINJA_BRANCHES = {"if", "elif", "for"}
_DEFINITIONS = {"macro": "endmacro", "test": "endtest", "materialization": "endmaterialization"}
_JINJA_LOGIC = re.compile(r"\b(and|or)\b")
_JINJA_INLINE_IF = re.compile(r"\bif\b")
_DEFINED_NAME = re.compile(r"^\s*\w+\s+([A-Za-z_]\w*)")


@dataclass(frozen=True)
class Unit:
    """One scored unit. Offsets are character offsets; `end` is exclusive."""

    name: str
    kind: str  # "cte", "main", or "macro"
    start: int
    end: int
    start_line: int
    end_line: int
    complexity: int


@dataclass(frozen=True)
class Parsed:
    source: str
    masked: Masked
    tokens: list[Token] | None
    units: list[Unit]


def namespace(path: str) -> str:
    """The model or macro file name. dbt keeps model names unique per project."""

    return Path(path).stem


def is_between_and(tokens: list[Token], index: int) -> bool:
    depth = tokens[index].depth
    for previous in reversed(tokens[:index]):
        if previous.depth != depth:
            continue
        if previous.type == "BETWEEN":
            return True
        if previous.type in {"AND", "OR", "WHERE", "ON", "WHEN", "THEN", "HAVING", "QUALIFY"}:
            return False
    return False


def _is_decision(tokens: list[Token], index: int) -> bool:
    token = tokens[index]
    if token.jinja:
        return False
    if token.word in _SQL_DECISIONS:
        return True
    if token.type == "AND":
        return not is_between_and(tokens, index)
    following = tokens[index + 1] if index + 1 < len(tokens) else None
    return token.word in _BRANCHING_CALLS and following is not None and following.type == "L_PAREN"


def _jinja_decisions(tag: Tag) -> int:
    if tag.kind == "comment":
        return 0
    count = len(_JINJA_LOGIC.findall(tag.body))
    if tag.kind == "stmt":
        return count + (1 if tag.keyword in _JINJA_BRANCHES else 0)
    return count + len(_JINJA_INLINE_IF.findall(tag.body))


def complexity(parsed: Parsed, start: int, end: int) -> int:
    total = 1
    tokens = parsed.tokens or []
    for index, token in enumerate(tokens):
        if start <= token.start < end and _is_decision(tokens, index):
            total += 1
    for tag in parsed.masked.tags:
        if start <= tag.start < end:
            total += _jinja_decisions(tag)
    return total


def _unit(parsed: Parsed, name: str, kind: str, start: int, end: int) -> Unit:
    return Unit(
        name=name,
        kind=kind,
        start=start,
        end=end,
        start_line=line_of(parsed.source, start),
        end_line=line_of(parsed.source, max(start, end - 1)),
        complexity=complexity(parsed, start, end),
    )


def _definitions(parsed: Parsed) -> list[Unit]:
    found: list[Unit] = []
    open_tag: Tag | None = None
    for tag in parsed.masked.tags:
        if tag.kind != "stmt":
            continue
        if open_tag is None and tag.keyword in _DEFINITIONS:
            open_tag = tag
        elif open_tag is not None and tag.keyword == _DEFINITIONS[open_tag.keyword]:
            named = _DEFINED_NAME.match(open_tag.body)
            name = named.group(1) if named else open_tag.keyword
            found.append(_unit(parsed, name, "macro", open_tag.start, tag.end))
            open_tag = None
    return found


def _sql(tokens: list[Token]) -> list[Token]:
    return [token for token in tokens if not token.jinja]


def _cte_end(tokens: list[Token], index: int) -> int | None:
    """From a CTE name, the index of the paren that closes its body."""

    for current in range(index + 1, len(tokens)):
        token = tokens[current]
        if token.type == "L_PAREN" and tokens[current - 1].type == "ALIAS":
            return closing(tokens, current)
        if token.depth == 0 and token.type in {"SELECT", "COMMA"}:
            return None
    return None


def _ctes(parsed: Parsed, tokens: list[Token]) -> tuple[list[Unit], int]:
    """Top-level CTEs, and the index of the first token after them."""

    found: list[Unit] = []
    if not tokens or tokens[0].type != "WITH":
        return found, 0
    index = 1
    if index < len(tokens) and tokens[index].word == "RECURSIVE":
        index += 1
    while index < len(tokens):
        name = tokens[index]
        end = _cte_end(tokens, index)
        if end is None:
            break
        found.append(_unit(parsed, name.text, "cte", name.start, tokens[end].end))
        index = end + 1
        if index < len(tokens) and tokens[index].type == "COMMA":
            index += 1
            continue
        break
    return found, index


def _model(parsed: Parsed) -> list[Unit]:
    if parsed.tokens is None:
        text = parsed.source
        start = len(text) - len(text.lstrip())
        return [_unit(parsed, "main", "main", start, len(text.rstrip()))] if text.strip() else []
    tokens = _sql(parsed.tokens)
    if not tokens:
        return []
    found, index = _ctes(parsed, tokens)
    if index < len(tokens):
        found.append(_unit(parsed, "main", "main", tokens[index].start, tokens[-1].end))
    return found


def parse(source: str) -> Parsed:
    masked = mask(source)
    parsed = Parsed(source, masked, tokenize(masked), [])
    units = _definitions(parsed) or _model(parsed)
    return Parsed(source, masked, parsed.tokens, units)


def units(source: str) -> list[Unit]:
    return parse(source).units
