"""SQL tokens of masked text, with paren depth and a Jinja flag."""

from __future__ import annotations

from dataclasses import dataclass

from sqlglot.dialects.dialect import Dialect
from sqlglot.errors import TokenError

from dbtsql.jinja import Masked

DIALECT = "snowflake"


@dataclass(frozen=True)
class Token:
    """One token. `end` is exclusive. `depth` counts the parens around it."""

    type: str
    text: str
    start: int
    end: int
    line: int
    depth: int
    jinja: bool

    @property
    def word(self) -> str:
        return self.text.upper()


def tokenize(masked: Masked) -> list[Token] | None:
    """Tokens in source order, or None when the text is not SQL the tokenizer reads."""

    try:
        raw = Dialect.get_or_raise(DIALECT).tokenize(masked.text)
    except TokenError:
        return None
    found: list[Token] = []
    depth = 0
    for token in raw:
        name = token.token_type.name
        if name == "R_PAREN":
            depth = max(0, depth - 1)
        found.append(
            Token(
                type=name,
                text=token.text,
                start=token.start,
                end=token.end + 1,
                line=token.line,
                depth=depth,
                jinja=masked.in_tag(token.start),
            )
        )
        if name == "L_PAREN":
            depth += 1
    return found


def closing(tokens: list[Token], index: int) -> int:
    """Index of the paren that closes the one at `index`, or the last token."""

    depth = tokens[index].depth
    for current in range(index + 1, len(tokens)):
        if tokens[current].type == "R_PAREN" and tokens[current].depth == depth:
            return current
    return len(tokens) - 1


def line_of(text: str, offset: int) -> int:
    return text.count("\n", 0, offset) + 1
