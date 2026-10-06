# -*- coding: utf-8 -*-
"""Публичная версия ms43diff: глоссарий сокращений Siemens (производное от
MS4X Wiki) в комплект не входит. Расшифровка имён работает по собственному
словарю в ru.py. Полный глоссарий — в приватной сборке."""
from __future__ import annotations
from typing import Dict, Optional, Tuple

WIKI_URL = "https://www.ms4x.net/index.php?title=Siemens_Keyword_Translation"
KEYWORDS: Dict[str, Tuple[str, str]] = {}


def lookup(token: str) -> Optional[Tuple[str, str]]:
    return None


def ru(token: str) -> Optional[str]:
    return None


def en(token: str) -> Optional[str]:
    return None
