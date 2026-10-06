# -*- coding: utf-8 -*-
"""Public ms43diff edition: the Siemens abbreviation glossary (derived from the
MS4X Wiki) is not included. Names are decoded with our own dictionaries in
ru.py and names.py. The full glossary is in the private build."""
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
