"""
Безопасный вычислитель формул пересчёта (<MATH equation="...">) из XDF.

TunerPro хранит преобразование «сырое значение из флеша -> физическая величина»
в виде выражения, например:

    0.75*X-48.0          (температура ОЖ, 1 бит = 0.75 °C, смещение -48)
    0.0234375*X          (угол опережения зажигания)
    X*0.003906           (передаточное отношение)

Имена переменных берутся из <VAR id="..."> и не всегда равны "X":
в автогенерированном XDF встречаются "X0", "X00", "X000" (артефакт генератора).

Здесь написан собственный рекурсивный парсер, чтобы НЕ звать eval() на данных
из чужого файла.
"""

from __future__ import annotations

import math
import re
from typing import Callable, Dict, Optional, Tuple

_TOKEN_RE = re.compile(
    r"""
    \s*(?:
        (?P<num>(?:\d+\.\d*|\.\d+|\d+)(?:[eE][+-]?\d+)?)
      | (?P<hex>0[xX][0-9a-fA-F]+)
      | (?P<ident>[A-Za-z_][A-Za-z_0-9]*)
      | (?P<op>\*\*|[-+*/%^(),])
    )
    """,
    re.VERBOSE,
)

# Функции, разрешённые в выражениях XDF.
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
    """Формула не разобралась или не посчиталась."""


class _Token:
    __slots__ = ("kind", "text", "pos")

    def __init__(self, kind: str, text: str, pos: int):
        self.kind = kind
        self.text = text
        self.pos = pos

    def __repr__(self) -> str:  # pragma: no cover - отладка
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
            raise MathError(f"непонятный символ {src[pos]!r} в позиции {pos} формулы {src!r}")
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
    """expr := term (('+'|'-') term)*
    term := unary (('*'|'/'|'%') unary)*
    unary := ('+'|'-') unary | power
    power := atom ('^' unary)?          # правоассоциативно
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
            raise MathError(f"формула {self.src!r} обрывается неожиданно")
        self.i += 1
        return tok

    def accept_op(self, *ops) -> Optional[str]:
        tok = self.peek()
        if tok is not None and tok.kind == "op" and tok.text in ops:
            self.i += 1
            return tok.text
        return None

    def parse(self) -> float:
        value = self.expr()
        if self.peek() is not None:
            raise MathError(f"лишние символы в конце формулы {self.src!r}")
        return value

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
                    raise MathError("деление на ноль")
                value = value / rhs
            else:
                if rhs == 0:
                    raise MathError("остаток от деления на ноль")
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
            value = self.expr()
            close = self.take()
            if not (close.kind == "op" and close.text == ")"):
                raise MathError(f"нет закрывающей скобки в {self.src!r}")
            return value
        if tok.kind == "ident":
            name = tok.text
            nxt = self.peek()
            if nxt is not None and nxt.kind == "op" and nxt.text == "(":
                self.i += 1
                args = []
                if not (self.peek() and self.peek().kind == "op" and self.peek().text == ")"):
                    args.append(self.expr())
                    while self.accept_op(","):
                        args.append(self.expr())
                close = self.take()
                if not (close.kind == "op" and close.text == ")"):
                    raise MathError(f"нет закрывающей скобки у функции {name} в {self.src!r}")
                fn = _FUNCS.get(name.lower())
                if fn is None:
                    raise MathError(f"неизвестная функция {name!r}")
                return float(fn(*args))
            # переменная
            if name in self.vars:
                return float(self.vars[name])
            lowered = name.lower()
            for key, val in self.vars.items():
                if key.lower() == lowered:
                    return float(val)
            if lowered in _CONSTS:
                return _CONSTS[lowered]
            raise MathError(f"неизвестная переменная {name!r} в формуле {self.src!r}")
        raise MathError(f"не ожидали {tok.text!r} в формуле {self.src!r}")


class Equation:
    """Скомпилированная (разобранная на токены) формула пересчёта."""

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

    def apply(self, raw: float) -> float:
        """Сырое значение из флеша -> физическая величина."""
        if self._broken:
            return float(raw)
        variables = {name: raw for name in self.var_names} if self.var_names else {}
        variables.setdefault("X", raw)
        variables.setdefault("x", raw)
        try:
            return _Parser(list(self._tokens), variables, self.source).parse()
        except MathError:
            return float(raw)
        except (ValueError, OverflowError, ZeroDivisionError):
            return float(raw)

    # ------------------------------------------------------------------
    @property
    def is_identity(self) -> bool:
        a, b = self.linear
        return a == 1.0 and b == 0.0

    @property
    def linear(self) -> Tuple[float, float]:
        """Если формула линейна, вернуть (a, b) для phys = a*raw + b.

        Определяется численно по трём точкам; для нелинейных формул вернётся
        приближение, поэтому смотрите ещё и is_linear.
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
        """Физическая величина -> сырое значение (только для линейных формул)."""
        if not self.is_linear:
            return None
        a, b = self.linear
        if a == 0:
            return None
        return (phys - b) / a

    def describe_ru(self, units: str = "") -> str:
        """Человеко-читаемое описание масштаба: «1 бит = 0.75 °C, смещение -48»."""
        a, b = self.linear
        if not self.is_linear:
            return f"нелинейная формула: {self.source}"
        unit = f" {units}" if units and units != "-" else ""
        parts = [f"1 бит = {_fmt(a)}{unit}"]
        if b:
            parts.append(f"смещение {_fmt(b)}{unit}")
        return ", ".join(parts)

    def __repr__(self) -> str:  # pragma: no cover
        return f"Equation({self.source!r})"


def _fmt(value: float) -> str:
    if value == int(value):
        return str(int(value))
    return f"{value:.10g}"


IDENTITY = Equation("X")
