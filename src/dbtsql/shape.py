"""The normalized tree dryer compares.

Keywords, operators, and called function names stay. Column and table names
become `id`, literals become `str` or `num`, and a Jinja expression becomes
`jinja`. Parens nest. Each level splits at clause keywords, and each clause
splits at commas, so two CTEs that differ by one column still share most
subtrees.
"""

from __future__ import annotations

from dbtsql.tokens import Token
from dbtsql.units import Parsed, Unit

_CLAUSES = {
    "SELECT",
    "FROM",
    "WHERE",
    "GROUP_BY",
    "HAVING",
    "QUALIFY",
    "ORDER_BY",
    "PARTITION_BY",
    "JOIN",
    "LEFT",
    "RIGHT",
    "INNER",
    "FULL",
    "CROSS",
    "ON",
    "UNION",
    "LIMIT",
}
_NAMES = {"VAR", "IDENTIFIER"}


def _atom(tokens: list[Token], index: int) -> str:
    token = tokens[index]
    if token.jinja:
        return "jinja"
    following = tokens[index + 1] if index + 1 < len(tokens) else None
    if token.type in _NAMES:
        if following is not None and following.type == "L_PAREN":
            return token.word
        return "id"
    if token.type == "STRING":
        return "str"
    if token.type == "NUMBER":
        return "num"
    return token.type


def _level(tokens: list[Token], start: int, end: int) -> list:
    """Clauses of tokens[start:end], each a list of comma-separated items."""

    clauses: list[list] = []
    item: list = []
    clause: list = [item]
    index = start
    while index < end:
        token = tokens[index]
        if token.type in _CLAUSES and token.depth == tokens[start].depth and any(clause[0]):
            clauses.append(clause)
            item = []
            clause = [item]
        if token.type == "COMMA":
            item = []
            clause.append(item)
        elif token.type == "L_PAREN":
            close = _close(tokens, index, end)
            item.append(["PAREN", *_level(tokens, index + 1, close)])
            index = close
        else:
            item.append(_atom(tokens, index))
        index += 1
    clauses.append(clause)
    return [[*(entry for entry in each if entry)] for each in clauses]


def _close(tokens: list[Token], index: int, end: int) -> int:
    depth = tokens[index].depth
    for current in range(index + 1, end):
        if tokens[current].type == "R_PAREN" and tokens[current].depth == depth:
            return current
    return end


def tree(parsed: Parsed, unit: Unit) -> list:
    tokens = [token for token in parsed.tokens or [] if unit.start <= token.start < unit.end]
    if not tokens:
        return []
    return _level(tokens, 0, len(tokens))
