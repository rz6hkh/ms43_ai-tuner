# -*- coding: utf-8 -*-
"""
Human-readable names, descriptions, categories and units of XDF objects in the
current UI language.

Russian mode delegates to ``ru.py`` (hand-made Russian layer). English mode
works from the XDF itself: titles and descriptions there are already English,
so we only decode abbreviations in names (``ip_iga_ron_98_pl_ivvt__n__maf`` ->
"[MAP] ignition angle, RON 98, part load, VANOS — rows: engine speed; columns:
air mass flow") and clean up units.

Every other module calls this one instead of ``ru.py`` directly.
"""

from __future__ import annotations

import re
from typing import Dict, Optional, Tuple

from . import keywords, ru
from .i18n import is_ru, t

# Prefix -> (short label, explanation). Same meaning as ru.PREFIX_RU.
PREFIX_EN: Dict[str, Tuple[str, str]] = {
    "c": ("CONST", "calibration constant, edited in TunerPro"),
    "ip": ("MAP", "table WITH interpolation between points"),
    "id": ("TABLE", "table WITHOUT interpolation (picked by index)"),
    "ldp": ("AXIS", "list of breakpoints — the axis of another map"),
    "ldpm": ("AXIS", "shared list of breakpoints"),
    "lc": ("SWITCH", "logical calibration constant (usually 0/1)"),
    "cal": ("CS", "calibration checksum"),
    "schw": ("THRESH", "threshold"),
    "t": ("TABLE", "table"),
}

# Our own English expansions for the most common name tokens. Checked first,
# so names stay readable even where the Siemens glossary is not bundled.
TOKEN_EN: Dict[str, str] = {
    "n": "engine speed",
    "vs": "vehicle speed",
    "maf": "air mass flow (load)",
    "hfm": "air flow meter (HFM)",
    "tco": "coolant temperature",
    "tia": "intake air temperature",
    "toil": "oil temperature",
    "tam": "ambient temperature",
    "teg": "exhaust gas temperature",
    "tmot": "engine temperature",
    "temp": "temperature",
    "amp": "ambient pressure",
    "vb": "battery voltage",
    "iga": "ignition angle",
    "ign": "ignition",
    "ti": "injection time",
    "tq": "torque",
    "tqi": "indicated torque",
    "lam": "lambda",
    "lamb": "lambda",
    "ls": "lambda sensor",
    "lsh": "lambda sensor heater",
    "pl": "part load",
    "fl": "full load",
    "wot": "wide open throttle",
    "is": "idle",
    "ivvt": "VANOS",
    "vanos": "VANOS",
    "ron": "RON",
    "max": "maximum",
    "min": "minimum",
    "mt": "manual gearbox",
    "at": "automatic gearbox",
    "fac": "factor",
    "sp": "setpoint",
    "gr": "gear ratio",
    "gear": "gear",
    "ch": "catalyst heating",
    "puc": "overrun fuel cut-off",
    "knk": "knock",
    "ckp": "crankshaft",
    "cam": "camshaft",
    "in": "intake",
    "ex": "exhaust",
    "thr": "throttle",
    "pvs": "pedal position",
    "tps": "throttle position",
    "rel": "relative",
    "add": "additive",
    "mul": "multiplicative",
    "cor": "correction",
    "dif": "difference",
    "thd": "threshold",
    "ad": "adaptation",
    "st": "start",
    "ast": "after start",
    "wup": "warm-up",
    "dly": "delay",
}

# Typos in the original glossary (kept there verbatim to match the wiki).
_GLOSSARY_FIXES = {
    "coolent": "coolant", "tempature": "temperature", "maxiumum": "maximum",
    "minumum": "minimum", "lamda": "lambda", "controler": "controller",
    "infinetly": "infinitely", "reseach": "research", "diffrence": "difference",
    "ambeint": "ambient",
}
_NUMERIC = re.compile(r"^\d+$")


def _fix_glossary(text: str) -> str:
    return " ".join(_GLOSSARY_FIXES.get(w.lower(), w) for w in text.split(" "))


# ---------------------------------------------------------------------------
# English implementations
# ---------------------------------------------------------------------------

def _token_en(token: str) -> str:
    if _NUMERIC.match(token):
        return token
    low = token.lower()
    if low in TOKEN_EN:
        return TOKEN_EN[low]
    official = keywords.en(token)
    return _fix_glossary(official) if official else token


def _tokens_en(tokens) -> str:
    return ", ".join(w for w in (_token_en(tok) for tok in tokens) if w)


def _axis_names_en(title: str) -> Tuple[str, str]:
    if not title or "__" not in title:
        return "", ""
    parts = [p for p in title.split("__")[1:] if p]
    if not parts:
        return "", ""
    if len(parts) == 1:
        return _tokens_en(parts[0].split("_")), ""
    return _tokens_en(parts[-2].split("_")), _tokens_en(parts[-1].split("_"))


def _name_en(title: str) -> str:
    if not title:
        return ""
    head = title.split("__")[0]
    tokens = [tok for tok in head.split("_") if tok]
    prefix = tokens[0] if tokens and tokens[0] in PREFIX_EN else ""
    if prefix:
        tokens = tokens[1:]
    body = _tokens_en(tokens)
    label = PREFIX_EN.get(prefix, ("", ""))[0]
    text = f"[{label}] {body}" if label else body
    y_name, x_name = _axis_names_en(title)
    if y_name and x_name:
        text += f" — rows: {y_name}; columns: {x_name}"
    elif y_name:
        text += f" — axis: {y_name}"
    return text


def _kind_en(title: str) -> str:
    head = title.split("__")[0] if title else ""
    prefix = head.split("_")[0] if head else ""
    return PREFIX_EN.get(prefix, ("", "object"))[1]


# ---------------------------------------------------------------------------
# Public API (language-aware)
# ---------------------------------------------------------------------------

def unit(units: str) -> str:
    if (units or "").strip() in ("-", "--"):
        return ""  # "-" marks a dimensionless value
    if is_ru():
        return ru.unit_ru(units)
    if not units:
        return ""
    key = units.strip()
    # junk units like "6", "8" occur in auto-generated XDFs
    return "" if key.isdigit() else key


def category(name: str) -> str:
    return ru.category_ru(name) if is_ru() else name


def description(text: str) -> str:
    """XDF description in the UI language (Russian is a rough translation)."""
    return ru.description_ru(text) if is_ru() else (text or "").strip()


def axis_names(title: str) -> Tuple[str, str]:
    """(row axis label, column axis label) decoded from the object name."""
    return ru.axis_names_ru(title) if is_ru() else _axis_names_en(title)


def decode(title: str) -> str:
    """Object name decoded through the abbreviation dictionary."""
    return ru.name_ru(title) if is_ru() else _name_en(title)


def curated_name(title: str) -> Optional[str]:
    """Hand-verified name, if there is one (Russian mode only)."""
    if not is_ru():
        return None
    entry = ru.PARAM_RU.get(title)
    return entry.get("ru") if entry else None


def name(title: str) -> str:
    return curated_name(title) or decode(title)


def explain(title: str, desc: str = "") -> Dict[str, str]:
    """Everything we know about an object, in the UI language."""
    if is_ru():
        info = ru.explain(title, desc)
        info["curated"] = t("yes") if title in ru.PARAM_RU else t("no")
        return info
    return {
        "name": _name_en(title),
        "decoded": _name_en(title),
        "kind": _kind_en(title),
        "desc": (desc or "").strip(),
        "desc_en": "",  # the description already is the original
        "note": "",
        "tune": "",
        "curated": t("no"),
    }
