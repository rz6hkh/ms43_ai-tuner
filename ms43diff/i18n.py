# -*- coding: utf-8 -*-
"""
User interface language (English / Russian).

Every user-visible string in the code is written in English and wrapped in
``t()``::

    t("Compare")                          # -> "Сравнение" in Russian mode
    t("{n} differences found", n=12)      # placeholders are filled after lookup

Russian texts live in ``locale_ru.py`` (English text -> Russian text). A string
missing from the catalog falls back to English, so the UI never breaks;
``selftest.py`` scans the sources and fails if any ``t()`` key lacks a
translation.

Language is chosen in this order:
  1. ``set_lang()`` (``--lang`` option, GUI menu);
  2. environment variable ``MS43DIFF_LANG`` (``en`` / ``ru``);
  3. ``lang`` in the settings file (saved by the GUI);
  4. the operating system language (Russian -> ``ru``, anything else -> ``en``).
"""

from __future__ import annotations

import contextvars
import json
import locale
import os
import sys
from typing import Any, Dict, Optional

LANGS = ("en", "ru")
LANG_NAMES = {"en": "English", "ru": "Русский"}
# Menu caption shown in both languages, so it can be found whatever is active.
LANG_MENU = "Language / Язык"

_lang: Optional[str] = None
# A per-request override (e.g. one MCP server answering in Russian while the
# window is in English). Unset means "use the process language".
_lang_override: "contextvars.ContextVar[Optional[str]]" = contextvars.ContextVar(
    "ms43diff_lang", default=None)


# ---------------------------------------------------------------------------
# Settings file (%APPDATA%\ms43diff\settings.json, ~/.config/ms43diff/...)
# ---------------------------------------------------------------------------

def settings_path() -> str:
    if sys.platform == "win32":
        base = os.environ.get("APPDATA") or os.path.expanduser("~")
    else:
        base = os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config")
    return os.path.join(base, "ms43diff", "settings.json")


def load_settings() -> Dict[str, Any]:
    try:
        with open(settings_path(), encoding="utf-8") as fh:
            data = json.load(fh)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def save_settings(**values: Any) -> None:
    """Merge ``values`` into the settings file. Errors are ignored: settings
    are a convenience and must never break the program."""
    data = load_settings()
    data.update(values)
    path = settings_path()
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(data, fh, ensure_ascii=False, indent=2)
    except OSError:
        pass


# ---------------------------------------------------------------------------
# Language
# ---------------------------------------------------------------------------

def _normalize(value: Optional[str]) -> Optional[str]:
    if not value:
        return None
    value = value.strip().lower()[:2]
    return value if value in LANGS else None


def _system_lang() -> str:
    if sys.platform == "win32":
        try:
            import ctypes

            lang_id = ctypes.windll.kernel32.GetUserDefaultUILanguage()
            # primary language id 0x19 = Russian
            return "ru" if (lang_id & 0x3FF) == 0x19 else "en"
        except Exception:  # noqa: BLE001 - any failure means "unknown"
            pass
    for var in ("LC_ALL", "LC_MESSAGES", "LANG"):
        if os.environ.get(var):
            return "ru" if os.environ[var].lower().startswith("ru") else "en"
    try:
        loc = locale.getlocale()[0] or ""
    except ValueError:
        loc = ""
    return "ru" if loc.lower().startswith("ru") else "en"


def detect_lang() -> str:
    return (_normalize(os.environ.get("MS43DIFF_LANG"))
            or _normalize(load_settings().get("lang"))
            or _system_lang())


def get_lang() -> str:
    global _lang
    override = _lang_override.get()
    if override:
        return override
    if _lang is None:
        _lang = detect_lang()
    return _lang


def set_lang(lang: Optional[str], remember: bool = False) -> str:
    """Switch the language for this process; ``remember`` also saves it."""
    global _lang
    norm = _normalize(lang)
    if norm is None:
        return get_lang()
    _lang = norm
    if remember:
        save_settings(lang=norm)
    return norm


def lang_override(lang: Optional[str]):
    """Use ``lang`` for the current thread/context; returns a token for reset."""
    return _lang_override.set(_normalize(lang))


def reset_lang_override(token) -> None:
    _lang_override.reset(token)


def is_ru() -> bool:
    return get_lang() == "ru"


# ---------------------------------------------------------------------------
# Translation
# ---------------------------------------------------------------------------

def t(message: str, /, **kwargs: Any) -> str:
    """Translate ``message`` to the current language, then fill placeholders."""
    if get_lang() == "ru":
        from .locale_ru import RU

        message = RU.get(message, message)
    return message.format(**kwargs) if kwargs else message


def plural(n: int, one: str, few: str, many: str) -> str:
    """Russian plural form for ``n`` (1 файл, 2 файла, 5 файлов)."""
    n = abs(n)
    if n % 10 == 1 and n % 100 != 11:
        return one
    if 2 <= n % 10 <= 4 and not 12 <= n % 100 <= 14:
        return few
    return many
