"""Mutation sites in dbt SQL.

Each site replaces one token, or a short run of tokens, outside Jinja:

  comparison  = <-> !=, <> -> =, > -> >=, >= -> >, < -> <=, <= -> <
  logical     AND <-> OR (not the AND of BETWEEN)
  arithmetic  + <-> -, * <-> / (binary only, so `select *` stays)
  null        IS NULL -> IS NOT NULL, IS NOT NULL -> IS NULL
  negation    NOT IN / NOT LIKE / NOT EXISTS / NOT BETWEEN lose the NOT;
              IN -> NOT IN
  aggregate   MIN <-> MAX, DISTINCT deleted
  order       ASC <-> DESC
  join        LEFT [OUTER] -> INNER, INNER -> LEFT, bare JOIN -> LEFT JOIN
  constant    TRUE <-> FALSE, 0 <-> 1

Offsets are UTF-8 byte offsets into the source, as mutator expects.
"""

from __future__ import annotations

from dataclasses import dataclass

from dbtsql.tokens import Token
from dbtsql.units import is_between_and, parse

_SWAPS = {
    "EQ": ("!=", "comparison"),
    "NEQ": ("=", "comparison"),
    "GT": (">=", "comparison"),
    "GTE": (">", "comparison"),
    "LT": ("<=", "comparison"),
    "LTE": ("<", "comparison"),
    "OR": ("and", "logical"),
    "TRUE": ("false", "constant"),
    "FALSE": ("true", "constant"),
    "ASC": ("desc", "order"),
    "DESC": ("asc", "order"),
    "DISTINCT": ("", "aggregate"),
}
_ARITHMETIC = {"PLUS": "-", "DASH": "+", "STAR": "/", "SLASH": "*"}
_VALUES = {"VAR", "IDENTIFIER", "NUMBER", "STRING", "R_PAREN", "NULL", "TRUE", "FALSE"}
_NEGATABLE = {"IN", "LIKE", "ILIKE", "EXISTS", "BETWEEN", "RLIKE"}
_JOIN_SIDES = {"LEFT", "RIGHT", "INNER", "FULL", "CROSS", "OUTER", "NATURAL", "SEMI", "ANTI", "ASOF"}
_EXTREMES = {"MIN": "max", "MAX": "min"}


@dataclass(frozen=True)
class RawSite:
    line: int
    start: int
    end: int
    original: str
    mutant: str
    category: str


class _Sites:
    def __init__(self, source: str, tokens: list[Token]):
        self.source = source
        self.tokens = tokens
        self.found: list[RawSite] = []

    def at(self, index: int) -> Token | None:
        if 0 <= index < len(self.tokens):
            return self.tokens[index]
        return None

    def add(self, first: Token, last: Token, mutant: str, category: str) -> None:
        original = self.source[first.start : last.end]
        if mutant == original or mutant == original.lower():
            return
        self.found.append(
            RawSite(
                line=first.line,
                start=len(self.source[: first.start].encode("utf-8")),
                end=len(self.source[: last.end].encode("utf-8")),
                original=original,
                mutant=mutant,
                category=category,
            )
        )

    def visit(self, index: int) -> None:
        token = self.tokens[index]
        before = self.at(index - 1)
        after = self.at(index + 1)
        if token.type in _SWAPS:
            mutant, category = _SWAPS[token.type]
            self.add(token, token, mutant, category)
        elif token.type == "AND" and not is_between_and(self.tokens, index):
            self.add(token, token, "or", "logical")
        elif token.type in _ARITHMETIC and before is not None and before.type in _VALUES:
            self.add(token, token, _ARITHMETIC[token.type], "arithmetic")
        elif token.word in _EXTREMES and after is not None and after.type == "L_PAREN":
            self.add(token, token, _EXTREMES[token.word], "aggregate")
        else:
            self.visit_words(token, before, after)

    def visit_words(self, token: Token, before: Token | None, after: Token | None) -> None:
        if token.type == "IS" and after is not None and after.type == "NULL":
            self.add(token, token, "is not", "null")
        elif token.type == "NOT" and before is not None and before.type == "IS":
            self.add(before, token, "is", "null")
        elif token.type == "NOT" and after is not None and after.type in _NEGATABLE:
            self.add(token, after, after.text.lower(), "negation")
        elif token.type == "IN" and not (before is not None and before.type == "NOT"):
            self.add(token, token, "not in", "negation")
        elif token.type == "NUMBER" and token.text in {"0", "1"}:
            self.add(token, token, "1" if token.text == "0" else "0", "constant")
        else:
            self.visit_join(token, before, after)

    def visit_join(self, token: Token, before: Token | None, after: Token | None) -> None:
        if token.type == "LEFT" and after is not None and after.type == "OUTER":
            self.add(token, after, "inner", "join")
        elif token.type == "LEFT" and after is not None and after.type == "JOIN":
            self.add(token, token, "inner", "join")
        elif token.type == "INNER":
            self.add(token, token, "left", "join")
        elif token.type == "JOIN" and (before is None or before.type not in _JOIN_SIDES):
            self.add(token, token, "left join", "join")


def discover(source: str) -> list[RawSite]:
    """Sites in source order."""

    parsed = parse(source)
    tokens = [token for token in parsed.tokens or [] if not token.jinja]
    sites = _Sites(source, tokens)
    for index in range(len(tokens)):
        sites.visit(index)
    return sorted(sites.found, key=lambda site: (site.line, site.start, site.end))
