"""
Safe evaluator for XDF conversion formulas (<MATH equation="...">).

TunerPro stores the "raw flash value -> physical value" conversion as an
expression, for example:

    0.75*X-48.0          (coolant temperature, 1 bit = 0.75 °C, offset -48)
    0.0234375*X          (ignition angle)
    X*0.003906           (gear ratio)

Variable names come from <VAR id="..."> and are not always "X": auto-generated
XDFs contain "X0", "X00", "X000" (a generator artefact).

This is a small recursive-descent parser so that eval() is NEVER called on data
from someone else's file.

TunerPro logger definitions (.adx) also use bitwise operators ("X&8191") and
formulas over other channels ("(TI*RPM)/1200"), hence &, |, <<, >> and
Equation.evaluate() with several variables. "^" stays a power, as in XDF.
"""

from __future__ import annotations

import math
import re
from typing import Callable, Dict, Optional, Tuple

from .i18n import t

_TOKEN_RE = re.compile(
    r"""
    \s*(?:
        (?P<num>(?:\d+\.\d*|\.\d+|\d+)(?:[eE][+-]?\d+)?)
      | (?P<hex>0[xX][0-9a-fA-F]+)
      | (?P<ident>[A-Za-z_][A-Za-z_0-9]*)
      | (?P<op>\*\*|<<|>>|[-+*/%^(),&|])
    )
    """,
    re.VERBOSE,
)

# Functions allowed in XDF expressions.
_FUNCS: Dict[str, Callable[..., float]] = {
    "abs": abs,
    "sqrt": math.sqrt,
    "exp": math.exp,
    "ln": math.log,
    "log": math.log10,
    "log10": math.log10,
    "sin": math.sin,
    "cos": math.cos,
    "tan": math.tan,
    "asin": math.asin,
    "acos": math.acos,
    "atan": math.atan,
    "floor": math.floor,
    "ceil": math.ceil,
    "round": lambda v: float(round(v)),
    "min": min,
    "max": max,
    "pow": math.pow,
}

_CONSTS = {"pi": math.pi, "e": math.e}


class MathError(ValueError):
    """The formula could not be parsed or evaluated."""


class _Token:
    __slots__ = ("kind", "text", "pos")

    def __init__(self, kind: str, text: str, pos: int):
        self.kind = kind
        self.text = text
        self.pos = pos

    def __repr__(self) -> str:  # pragma: no cover - debugging
        return f"<{self.kind}:{self.text}>"


def _tokenize(src: str):
    tokens = []
    pos = 0
    while pos < len(src):
        if src[pos].isspace():
            pos += 1
            continue
        m = _TOKEN_RE.match(src, pos)
        if not m or m.end() == m.start():
            raise MathError(t("unexpected character {ch!r} at position {pos} in formula {src!r}",
                              ch=src[pos], pos=pos, src=src))
        pos = m.end()
        if m.group("num") is not None:
            tokens.append(_Token("num", m.group("num"), m.start()))
        elif m.group("hex") is not None:
            tokens.append(_Token("hex", m.group("hex"), m.start()))
        elif m.group("ident") is not None:
            tokens.append(_Token("ident", m.group("ident"), m.start()))
        else:
            tokens.append(_Token("op", m.group("op"), m.start()))
    return tokens


class _Parser:
    """bor := band ('|' band)*
    band := shift ('&' shift)*
    shift := expr (('<<'|'>>') expr)*
    expr := term (('+'|'-') term)*
    term := unary (('*'|'/'|'%') unary)*
    unary := ('+'|'-') unary | power
    power := atom ('^' unary)?          # right-associative
    atom := num | ident | ident '(' args ')' | '(' expr ')'
    """

    def __init__(self, tokens, variables: Dict[str, float], src: str):
        self.t = tokens
        self.i = 0
        self.vars = variables
        self.src = src

    def peek(self) -> Optional[_Token]:
        return self.t[self.i] if self.i < len(self.t) else None

    def take(self) -> _Token:
        tok = self.peek()
        if tok is None:
            raise MathError(t("formula {src!r} ends unexpectedly", src=self.src))
        self.i += 1
        return tok

    def accept_op(self, *ops) -> Optional[str]:
        tok = self.peek()
        if tok is not None and tok.kind == "op" and tok.text in ops:
            self.i += 1
            return tok.text
        return None

    def parse(self) -> float:
        value = self.bor()
        if self.peek() is not None:
            raise MathError(t("extra characters at the end of formula {src!r}", src=self.src))
        return value

    def bor(self) -> float:
        value = self.band()
        while self.accept_op("|"):
            value = float(_int(value, self.src) | _int(self.band(), self.src))
        return value

    def band(self) -> float:
        value = self.shift()
        while self.accept_op("&"):
            value = float(_int(value, self.src) & _int(self.shift(), self.src))
        return value

    def shift(self) -> float:
        value = self.expr()
        while True:
            op = self.accept_op("<<", ">>")
            if op is None:
                return value
            n = _int(self.expr(), self.src)
            if not 0 <= n < 64:
                raise MathError(t("bad shift {n} in formula {src!r}", n=n, src=self.src))
            value = float(_int(value, self.src) << n if op == "<<" else _int(value, self.src) >> n)

    def expr(self) -> float:
        value = self.term()
        while True:
            op = self.accept_op("+", "-")
            if op is None:
                return value
            rhs = self.term()
            value = value + rhs if op == "+" else value - rhs

    def term(self) -> float:
        value = self.unary()
        while True:
            op = self.accept_op("*", "/", "%")
            if op is None:
                return value
            rhs = self.unary()
            if op == "*":
                value = value * rhs
            elif op == "/":
                if rhs == 0:
                    raise MathError(t("division by zero"))
                value = value / rhs
            else:
                if rhs == 0:
                    raise MathError(t("modulo by zero"))
                value = math.fmod(value, rhs)

    def unary(self) -> float:
        op = self.accept_op("+", "-")
        if op == "-":
            return -self.unary()
        if op == "+":
            return self.unary()
        return self.power()

    def power(self) -> float:
        base = self.atom()
        if self.accept_op("^", "**"):
            return math.pow(base, self.unary())
        return base

    def atom(self) -> float:
        tok = self.take()
        if tok.kind == "num":
            return float(tok.text)
        if tok.kind == "hex":
            return float(int(tok.text, 16))
        if tok.kind == "op" and tok.text == "(":
            value = self.bor()
            close = self.take()
            if not (close.kind == "op" and close.text == ")"):
                raise MathError(t("missing closing bracket in {src!r}", src=self.src))
            return value
        if tok.kind == "ident":
            name = tok.text
            nxt = self.peek()
            if nxt is not None and nxt.kind == "op" and nxt.text == "(":
                self.i += 1
                args = []
                if not (self.peek() and self.peek().kind == "op" and self.peek().text == ")"):
                    args.append(self.bor())
                    while self.accept_op(","):
                        args.append(self.bor())
                close = self.take()
                if not (close.kind == "op" and close.text == ")"):
                    raise MathError(t("missing closing bracket of function {name} in {src!r}",
                                       name=name, src=self.src))
                fn = _FUNCS.get(name.lower())
                if fn is None:
                    raise MathError(t("unknown function {name!r}", name=name))
                return float(fn(*args))
            # variable
            if name in self.vars:
                return float(self.vars[name])
            lowered = name.lower()
            for key, val in self.vars.items():
                if key.lower() == lowered:
                    return float(val)
            if lowered in _CONSTS:
                return _CONSTS[lowered]
            raise MathError(t("unknown variable {name!r} in formula {src!r}", name=name, src=self.src))
        raise MathError(t("unexpected {tok!r} in formula {src!r}", tok=tok.text, src=self.src))


def _int(value: float, src: str) -> int:
    """Operand of a bitwise operator: must be a whole number."""
    if value != int(value):
        raise MathError(t("bitwise operator on a fraction in formula {src!r}", src=src))
    return int(value)


class Equation:
    """A compiled (tokenized) conversion formula."""

    __slots__ = ("source", "var_names", "_tokens", "_linear", "_broken")

    def __init__(self, source: str, var_names=None):
        self.source = (source or "X").strip() or "X"
        self.var_names = list(var_names or [])
        self._broken: Optional[str] = None
        try:
            self._tokens = _tokenize(self.source)
        except MathError as exc:
            self._tokens = []
            self._broken = str(exc)
        self._linear: Optional[Tuple[float, float]] = None

    # ------------------------------------------------------------------
    def __call__(self, raw: float) -> float:
        return self.apply(raw)

    @property
    def error(self) -> Optional[str]:
        """Why the formula cannot be used, or None. A broken formula reads as
        the raw value, so writing through it must be refused."""
        if self._broken:
            return self._broken
        try:
            probe = {name: 1.0 for name in self.var_names}
            probe["X"] = 1.0
            self.evaluate(probe)
        except MathError as exc:
            return str(exc)
        except (ValueError, OverflowError, ZeroDivisionError):
            return None  # fine in general, fails only for this probe value
        return None

    def evaluate(self, variables: Dict[str, float]) -> float:
        """Evaluate with named variables; raises MathError on any problem."""
        if self._broken:
            raise MathError(self._broken)
        try:
            return _Parser(list(self._tokens), variables, self.source).parse()
        except (ValueError, OverflowError, ZeroDivisionError) as exc:
            if isinstance(exc, MathError):
                raise
            raise MathError(str(exc)) from exc

    def apply(self, raw: float) -> float:
        """Raw flash value -> physical value (the raw value if the formula fails)."""
        variables = {name: raw for name in self.var_names} if self.var_names else {}
        variables.setdefault("X", raw)
        variables.setdefault("x", raw)
        try:
            return self.evaluate(variables)
        except MathError:
            return float(raw)

    # ------------------------------------------------------------------
    @property
    def is_identity(self) -> bool:
        a, b = self.linear
        return a == 1.0 and b == 0.0

    @property
    def linear(self) -> Tuple[float, float]:
        """For a linear formula return (a, b) such that phys = a*raw + b.

        Found numerically from two points; for non-linear formulas this is an
        approximation, so check is_linear as well.
        """
        if self._linear is None:
            y0 = self.apply(0.0)
            y1 = self.apply(1.0)
            self._linear = (y1 - y0, y0)
        return self._linear

    @property
    def is_linear(self) -> bool:
        a, b = self.linear
        for probe in (2.0, 10.0, 100.0, 255.0):
            expected = a * probe + b
            got = self.apply(probe)
            if not math.isclose(expected, got, rel_tol=1e-6, abs_tol=1e-9):
                return False
        return True

    def invert(self, phys: float) -> Optional[float]:
        """Physical value -> raw value (linear formulas only)."""
        if not self.is_linear:
            return None
        a, b = self.linear
        if a == 0:
            return None
        return (phys - b) / a

    def describe(self, units: str = "") -> str:
        """Human-readable scale: "1 bit = 0.75 °C, offset -48 °C"."""
        a, b = self.linear
        if not self.is_linear:
            return t("non-linear formula: {src}", src=self.source)
        unit = f" {units}" if units and units != "-" else ""
        parts = [t("1 bit = {value}", value=_fmt(a) + unit)]
        if b:
            parts.append(t("offset {value}", value=_fmt(b) + unit))
        return ", ".join(parts)

    def __repr__(self) -> str:  # pragma: no cover
        return f"Equation({self.source!r})"


def _fmt(value: float) -> str:
    if value == int(value):
        return str(int(value))
    return f"{value:.10g}"


IDENTITY = Equation("X")
