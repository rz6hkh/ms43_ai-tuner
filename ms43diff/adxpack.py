# -*- coding: utf-8 -*-
"""
The logger definition pack: ADX files (and the community patchlist XDF) from the
MS4X Wiki, downloaded on request into the user folder and never bundled - they
belong to their authors.

    <user folder>/adx/*.adx, *.xdf     the pack (plus any ADX the owner adds)

The file list is read from the wiki pages each time, so new versions appear by
themselves. Each file is fetched through Special:FilePath.
"""

from __future__ import annotations

import os
import re
import urllib.error
import urllib.parse
from typing import Any, Callable, Dict, List, Optional

from .i18n import t

PAGES = ("Logger_Definition_Files", "MS43X_Custom_Firmware", "TunerPro_MS43_Community_Patchlist")
_FILE_LINK = re.compile(r'title=File:([^"&#]+\.(?:adx|xdf))"', re.IGNORECASE)


def folder() -> str:
    from . import wikicache

    return os.path.join(os.path.dirname(wikicache.user_dir()), "adx")


def _wanted(name: str) -> bool:
    """MS43 logger definitions and the newest MS43 patchlist; not MS42, not firmware XDFs."""
    low = name.lower()
    if low.endswith(".adx"):
        return "ms43" in low
    return "community_patchlist" in low and "ms43" in low


def listing(fetch: Optional[Callable[[str, int], str]] = None, timeout: int = 30) -> List[str]:
    """File names linked from the wiki pages (newest patchlist only)."""
    from . import wikicache

    fetch = fetch or wikicache._fetch
    names: List[str] = []
    for page in PAGES:
        html = fetch(wikicache.page_url(page), timeout)
        for m in _FILE_LINK.finditer(html):
            name = urllib.parse.unquote(m.group(1)).replace(" ", "_")
            if _wanted(name) and name not in names:
                names.append(name)
    patchlists = [n for n in names if n.lower().endswith(".xdf")]
    if len(patchlists) > 1:
        keep = max(patchlists, key=_version_key)
        names = [n for n in names if not n.lower().endswith(".xdf") or n == keep]
    return names


def _version_key(name: str):
    m = re.search(r"v(\d+(?:\.\d+)*)", name)
    return tuple(int(x) for x in m.group(1).split(".")) if m else (0,)


def file_url(name: str) -> str:
    from . import wikicache

    return wikicache.BASE + "Special:FilePath/" + urllib.parse.quote(name)


def download(progress: Optional[Callable[[int, int, str], None]] = None,
             fetch_bytes: Optional[Callable[[str, int], bytes]] = None,
             fetch: Optional[Callable[[str, int], str]] = None, timeout: int = 30) -> Dict[str, Any]:
    """Download the pack. A file that fails keeps its old copy."""
    target = folder()
    os.makedirs(target, exist_ok=True)
    fetch_bytes = fetch_bytes or _fetch_bytes
    names = listing(fetch, timeout)
    got, errors = [], []
    for i, name in enumerate(names, 1):
        if progress:
            progress(i, len(names), name)
        try:
            data = fetch_bytes(file_url(name), timeout)
            if not _looks_right(name, data):
                raise ValueError(t("not an ADX/XDF file (the site answered something else)"))
            tmp = os.path.join(target, name + ".tmp")
            with open(tmp, "wb") as fh:
                fh.write(data)
            os.replace(tmp, os.path.join(target, name))
            got.append(name)
        except (urllib.error.URLError, OSError, ValueError) as exc:
            errors.append((name, str(exc)))
    return {"folder": target, "files": got, "errors": errors, "listed": names}


def _fetch_bytes(url: str, timeout: int) -> bytes:
    import urllib.request

    from . import wikicache

    req = urllib.request.Request(url, headers={"User-Agent": wikicache.USER_AGENT})
    with urllib.request.urlopen(req, timeout=timeout) as res:
        return res.read()


def _looks_right(name: str, data: bytes) -> bool:
    head = data[:400].lstrip(b"\xef\xbb\xbf").lstrip().lower()
    if name.lower().endswith(".adx"):
        return head.startswith(b"<adxformat") or b"<adxformat" in head
    return b"<xdfformat" in head


def files() -> List[Dict[str, Any]]:
    """The pack on disk: every ADX with what it asks of the ECU, and the patchlist."""
    from .logcheck import adx_summary

    target = folder()
    out: List[Dict[str, Any]] = []
    if not os.path.isdir(target):
        return out
    for name in sorted(os.listdir(target)):
        path = os.path.join(target, name)
        if name.lower().endswith(".adx"):
            try:
                out.append({"name": name, "path": path, "type": "adx", **adx_summary(path)})
            except Exception as exc:  # noqa: BLE001 - a broken file is listed with its error
                out.append({"name": name, "path": path, "type": "adx", "error": str(exc)})
        elif name.lower().endswith(".xdf"):
            out.append({"name": name, "path": path, "type": "patchlist"})
    return out


BUILTIN_STANDARD = "MS43_Standard_0B03_AI-Tuner.adx"


def builtin_dir() -> str:
    """The program's own ADX (inside a PyInstaller .exe: under sys._MEIPASS)."""
    import sys

    base = getattr(sys, "_MEIPASS", None)
    if base and os.path.isdir(os.path.join(base, "ms43diff", "adxdata")):
        return os.path.join(base, "ms43diff", "adxdata")
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), "adxdata")


def standard_adx() -> str:
    """The standard request 0B 03 ADX (the fallback): one the owner put into the pack folder,
    else the program's own (layout inferred from recordings, hypotheses marked "(?)")."""
    for f in files():
        if f["type"] == "adx" and f.get("request") == "0B 03":
            return f["path"]
    path = os.path.join(builtin_dir(), BUILTIN_STANDARD)
    return path if os.path.isfile(path) else ""


def recommend(firmware_id: str, engine: str) -> str:
    """The ADX of the pack that fits: the MS43X one for X001, else the newest extended one
    for the engine (M54B22/B25/B30)."""
    pack = [f for f in files() if f["type"] == "adx" and not f.get("error")]
    if "43X" in (firmware_id or "").upper():
        for f in pack:
            if "43x" in f["name"].lower():
                return f["path"]
    engine = (engine or "").upper().replace(" ", "")
    same = [f for f in pack if engine and engine in f["name"].upper().replace("_", "")]
    if same:
        return max(same, key=lambda f: _version_key(f["name"]))["path"]
    return ""


def engine_of(*texts: str) -> str:
    """M54B30 / M54B25 / M54B22 / M52TUB28 found in the car model or the file names."""
    for text in texts:
        m = re.search(r"M5[24](?:TU)?B\d\d", (text or "").upper().replace(" ", ""))
        if m:
            return m.group(0)
    return ""
