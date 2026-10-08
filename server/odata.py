#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The OData query subset SensorThings 1.1 requires (spec v0.1 §10).

Separate from the HTTP layer because every interesting bug in query handling is a
bug in evaluation, not in routing, and evaluation can be tested without a socket.

## The rule that shapes this module

**An unsupported query option is an error, never silence.** A client that sends
`$filter=result gt 0.4` and gets back every reading has been told something false: it
cannot distinguish "no filtering happened" from "nothing matched the filter", and a map
or a chart built on that shows wrong data with no indication of it. QGIS in particular
will happily render whatever it is handed. So anything this module cannot evaluate
raises `BadRequest` or `NotSupported`, and the HTTP layer turns that into a 400 or a
501 with the offending text quoted back.

That is a deliberate departure from being liberal in what we accept. A read-only
service has exactly one job, and quietly answering a different question than the one
asked is the worst way to fail at it.

## What is supported

* `$top`, `$skip`, `$count`, `$orderby`, `$select`, `$expand`, `$filter`.
* In `$filter`: `eq ne gt ge lt le`, `and or not`, parentheses, the arithmetic-free
  comparison of a property path against a literal or another property path, and the
  functions `substringof`, `startswith`, `endswith`, `contains`, `year`, `month`, `day`,
  `hour`, `minute`, `second`, `round`, `floor`, `ceiling`, `length`, `tolower`,
  `toupper`, `trim`, `indexof`, `concat`, `now`.
* Literals: numbers, single-quoted strings (with `''` escaping), `true`, `false`,
  `null`, and bare ISO-8601 timestamps, which OData 4.0 writes unquoted.
* Property paths across one navigation level, `Datastream/name`, resolved against the
  expanded document when `$expand` supplied it.

Everything else — `$apply`, lambda operators, geospatial functions, arithmetic — is
`NotSupported`, by name, so the gap is legible instead of mysterious.
"""
from __future__ import annotations

import datetime as _dt
import re
from dataclasses import dataclass

UTC = _dt.timezone.utc

#: The largest page a client may ask for. A server that honours `$top=10000000`
#: against a season of readings has handed its memory to whoever can type a URL.
MAX_TOP = 10_000
#: What a client gets when it asks for no particular number.
DEFAULT_TOP = 100


class QueryError(Exception):
    """Base for anything wrong with a query, carrying the text to quote back."""

    status = 400

    def __init__(self, message: str, offending: str | None = None):
        super().__init__(message)
        self.message = message
        self.offending = offending


class BadRequest(QueryError):
    """The query is malformed — a syntax error, a bad number, an unknown operator."""

    status = 400


class NotSupported(QueryError):
    """The query is valid OData that this service does not implement.

    A separate class from `BadRequest` because the distinction matters to whoever is
    holding the client: 400 means *fix your query*, 501 means *this server cannot do
    that, and it is not your fault*.
    """

    status = 501


# ------------------------------------------------------------------- tokenising

_TOKEN = re.compile(r"""
      (?P<ws>\s+)
    | (?P<lparen>\()
    | (?P<rparen>\))
    | (?P<comma>,)
    | (?P<string>'(?:[^']|'')*')
    | (?P<datetime>\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2}))
    | (?P<date>\d{4}-\d{2}-\d{2})
    | (?P<number>-?\d+\.\d+(?:[eE][+-]?\d+)?|-?\d+(?:[eE][+-]?\d+)?)
    | (?P<name>[A-Za-z_@][A-Za-z0-9_.@]*(?:/[A-Za-z_@][A-Za-z0-9_.@]*)*)
""", re.VERBOSE)

_LOGICAL = {"and", "or", "not"}
_COMPARISON = {"eq", "ne", "gt", "ge", "lt", "le"}
#: Named here only so the error message can say *why* it is refused.
_ARITHMETIC = {"add", "sub", "mul", "div", "mod"}


@dataclass(frozen=True, slots=True)
class Token:
    kind: str
    text: str


def tokenise(expr: str) -> list[Token]:
    out: list[Token] = []
    pos = 0
    while pos < len(expr):
        m = _TOKEN.match(expr, pos)
        if m is None:
            raise BadRequest("could not parse the filter expression", expr[pos:pos + 20])
        pos = m.end()
        kind = m.lastgroup
        if kind == "ws":
            continue
        out.append(Token(kind, m.group()))
    return out


# ---------------------------------------------------------------------- parsing
#
# Recursive descent, lowest precedence first: or < and < not < comparison < primary.
# OData's precedence, which is also everyone's precedence.


@dataclass(frozen=True, slots=True)
class Literal:
    value: object


@dataclass(frozen=True, slots=True)
class Path:
    segments: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class Call:
    name: str
    args: tuple


@dataclass(frozen=True, slots=True)
class Compare:
    op: str
    left: object
    right: object


@dataclass(frozen=True, slots=True)
class And:
    left: object
    right: object


@dataclass(frozen=True, slots=True)
class Or:
    left: object
    right: object


@dataclass(frozen=True, slots=True)
class Not:
    operand: object


class _Parser:

    def __init__(self, tokens: list[Token], source: str):
        self.tokens = tokens
        self.source = source
        self.i = 0

    def peek(self) -> Token | None:
        return self.tokens[self.i] if self.i < len(self.tokens) else None

    def take(self) -> Token:
        tok = self.peek()
        if tok is None:
            raise BadRequest("the filter expression ends unexpectedly", self.source)
        self.i += 1
        return tok

    def expect(self, kind: str) -> Token:
        tok = self.take()
        if tok.kind != kind:
            raise BadRequest(f"expected {kind}", tok.text)
        return tok

    def at_word(self, word: str) -> bool:
        tok = self.peek()
        return tok is not None and tok.kind == "name" and tok.text.lower() == word

    def parse(self):
        node = self.parse_or()
        if self.peek() is not None:
            raise BadRequest("unexpected text after the filter expression",
                             self.peek().text)
        return node

    def parse_or(self):
        node = self.parse_and()
        while self.at_word("or"):
            self.take()
            node = Or(node, self.parse_and())
        return node

    def parse_and(self):
        node = self.parse_not()
        while self.at_word("and"):
            self.take()
            node = And(node, self.parse_not())
        return node

    def parse_not(self):
        if self.at_word("not"):
            self.take()
            return Not(self.parse_not())
        return self.parse_comparison()

    def parse_comparison(self):
        left = self.parse_primary()
        tok = self.peek()
        if tok is not None and tok.kind == "name":
            word = tok.text.lower()
            if word in _COMPARISON:
                self.take()
                return Compare(word, left, self.parse_primary())
            if word in _ARITHMETIC:
                raise NotSupported(
                    "arithmetic in $filter is not implemented; compare a property "
                    "against a literal instead", tok.text)
        return left

    def parse_primary(self):
        tok = self.take()
        if tok.kind == "lparen":
            node = self.parse_or()
            self.expect("rparen")
            return node
        if tok.kind == "string":
            return Literal(tok.text[1:-1].replace("''", "'"))
        if tok.kind == "number":
            text = tok.text
            return Literal(float(text) if ("." in text or "e" in text.lower())
                           else int(text))
        if tok.kind in ("datetime", "date"):
            return Literal(_parse_time(tok.text))
        if tok.kind == "name":
            word = tok.text.lower()
            if word == "true":
                return Literal(True)
            if word == "false":
                return Literal(False)
            if word == "null":
                return Literal(None)
            nxt = self.peek()
            if nxt is not None and nxt.kind == "lparen":
                return self.parse_call(tok.text)
            if word in _LOGICAL or word in _COMPARISON:
                raise BadRequest(f"'{tok.text}' needs an operand before it", tok.text)
            return Path(tuple(tok.text.split("/")))
        raise BadRequest("unexpected token in the filter expression", tok.text)

    def parse_call(self, name: str):
        self.expect("lparen")
        args = []
        if self.peek() is not None and self.peek().kind != "rparen":
            args.append(self.parse_or())
            while self.peek() is not None and self.peek().kind == "comma":
                self.take()
                args.append(self.parse_or())
        self.expect("rparen")
        lowered = name.lower()
        if lowered not in _FUNCTIONS:
            raise NotSupported(f"the function '{name}' is not implemented", name)
        return Call(lowered, tuple(args))


def parse_filter(expr: str):
    """Parse a `$filter` expression into a tree, or raise."""
    if not expr.strip():
        raise BadRequest("$filter is empty")
    return _Parser(tokenise(expr), expr).parse()


# -------------------------------------------------------------------- evaluation

def _parse_time(text: str):
    """An ISO-8601 instant, or a date meaning midnight UTC."""
    raw = text
    if len(text) == 10:
        text += "T00:00:00+00:00"
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        when = _dt.datetime.fromisoformat(text)
    except ValueError as exc:
        raise BadRequest(f"not a valid timestamp: {raw}", raw) from exc
    return when if when.tzinfo else when.replace(tzinfo=UTC)


def _coerce_pair(left, right):
    """Make two values comparable, or leave them alone.

    The only coercion that matters: a `$filter` datetime literal parses to a
    `datetime`, while the document it is compared against holds an ISO string, because
    that is what goes out on the wire. Comparing those as-is raises `TypeError`, and
    comparing them as strings is subtly wrong the moment two offsets differ — the same
    instant written `...T12:00:00Z` and `...T13:00:00+01:00` is one value with two
    lexicographically different spellings. Parsing wins.
    """
    if isinstance(left, _dt.datetime) and isinstance(right, str):
        return left, _try_time(right)
    if isinstance(right, _dt.datetime) and isinstance(left, str):
        return _try_time(left), right
    return left, right


def _try_time(text: str):
    try:
        return _parse_time(text.split("/")[0])      # an interval's start (§2)
    except BadRequest:
        return text


_FUNCTIONS: dict[str, int | None] = {
    "substringof": 2, "startswith": 2, "endswith": 2, "contains": 2,
    "indexof": 2, "concat": 2, "length": 1, "tolower": 1, "toupper": 1,
    "trim": 1, "year": 1, "month": 1, "day": 1, "hour": 1, "minute": 1,
    "second": 1, "round": 1, "floor": 1, "ceiling": 1, "now": 0,
}


def _as_time(value):
    if isinstance(value, _dt.datetime):
        return value
    if isinstance(value, str):
        got = _try_time(value)
        if isinstance(got, _dt.datetime):
            return got
    raise BadRequest(f"expected a timestamp, got {value!r}")


def _as_text(value):
    if value is None:
        return ""
    return value if isinstance(value, str) else str(value)


def _as_number(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise BadRequest(f"expected a number, got {value!r}")
    return value


def _call(node: Call, doc: dict):
    name = node.name
    arity = _FUNCTIONS[name]
    if arity is not None and len(node.args) != arity:
        raise BadRequest(f"{name} takes {arity} argument(s), got {len(node.args)}")
    args = [evaluate(a, doc) for a in node.args]
    if name == "now":
        return _dt.datetime.now(tz=UTC)
    if name == "substringof":
        return _as_text(args[0]) in _as_text(args[1])
    if name == "contains":
        return _as_text(args[1]) in _as_text(args[0])
    if name == "startswith":
        return _as_text(args[0]).startswith(_as_text(args[1]))
    if name == "endswith":
        return _as_text(args[0]).endswith(_as_text(args[1]))
    if name == "indexof":
        return _as_text(args[0]).find(_as_text(args[1]))
    if name == "concat":
        return _as_text(args[0]) + _as_text(args[1])
    if name == "length":
        return len(_as_text(args[0]))
    if name == "tolower":
        return _as_text(args[0]).lower()
    if name == "toupper":
        return _as_text(args[0]).upper()
    if name == "trim":
        return _as_text(args[0]).strip()
    if name in ("year", "month", "day", "hour", "minute", "second"):
        return getattr(_as_time(args[0]), name)
    if name == "round":
        # OData rounds half away from zero; Python's round() is half-to-even, so
        # round(0.5) is 0 and a client comparing against 1 gets a wrong answer.
        value = _as_number(args[0])
        return int(value + (0.5 if value >= 0 else -0.5))
    if name == "floor":
        import math
        return math.floor(_as_number(args[0]))
    if name == "ceiling":
        import math
        return math.ceil(_as_number(args[0]))
    raise NotSupported(f"the function '{name}' is not implemented", name)


def resolve_path(doc: dict, segments: tuple[str, ...]):
    """Follow a property path through a serialized document.

    Missing is `None`, which is what OData says and also the only workable answer: a
    `Datastream/name` filter on an Observation that was not `$expand`ed has no value
    to compare, and the alternative to `None` is failing a request that is arguably
    well formed. The HTTP layer warns about that case instead — see `app.py`.
    """
    cursor: object = doc
    for seg in segments:
        if isinstance(cursor, dict):
            if seg in cursor:
                cursor = cursor[seg]
                continue
            # SensorThings spells the id `@iot.id`; clients and humans both write
            # `id`, and refusing that is pedantry with no upside.
            if seg == "id" and "@iot.id" in cursor:
                cursor = cursor["@iot.id"]
                continue
            return None
        return None
    return cursor


def evaluate(node, doc: dict):
    """Evaluate one node against one serialized document."""
    if isinstance(node, Literal):
        return node.value
    if isinstance(node, Path):
        return resolve_path(doc, node.segments)
    if isinstance(node, Call):
        return _call(node, doc)
    if isinstance(node, Not):
        return not evaluate(node.operand, doc)
    if isinstance(node, And):
        return bool(evaluate(node.left, doc)) and bool(evaluate(node.right, doc))
    if isinstance(node, Or):
        return bool(evaluate(node.left, doc)) or bool(evaluate(node.right, doc))
    if isinstance(node, Compare):
        left = evaluate(node.left, doc)
        right = evaluate(node.right, doc)
        return _compare(node.op, left, right)
    raise BadRequest(f"cannot evaluate {type(node).__name__}")


def _compare(op: str, left, right) -> bool:
    if op == "eq":
        return _eq(left, right)
    if op == "ne":
        return not _eq(left, right)
    left, right = _coerce_pair(left, right)
    if left is None or right is None:
        # Ordering against null is false in OData, not an error. A reading with no
        # result must not match `result gt 0.4` *or* `result le 0.4`.
        return False
    try:
        if op == "gt":
            return left > right
        if op == "ge":
            return left >= right
        if op == "lt":
            return left < right
        if op == "le":
            return left <= right
    except TypeError as exc:
        raise BadRequest(
            f"cannot compare {type(left).__name__} with {type(right).__name__}"
        ) from exc
    raise BadRequest(f"unknown operator '{op}'", op)


def _eq(left, right) -> bool:
    left, right = _coerce_pair(left, right)
    if left is None or right is None:
        return left is None and right is None
    try:
        return bool(left == right)
    except TypeError:
        return False


def matches(tree, doc: dict) -> bool:
    return bool(evaluate(tree, doc))
