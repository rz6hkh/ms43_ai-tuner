# -*- coding: utf-8 -*-
"""
Opening the interface window.

On Windows the page opens in Microsoft Edge "app mode" (--app): a plain window
without tabs or an address bar, so it looks like a normal program. A separate
Edge profile in %LOCALAPPDATA%\\ms43diff\\edge makes Edge start a process of our
own, so closing the window ends that process and the program can exit.

Without Edge the default browser is used; the page then tells the server when
it is closed (and sends a heartbeat), see server.py.
"""

from __future__ import annotations

import os
import subprocess
import sys
import webbrowser
from typing import List, Optional


def find_edge() -> Optional[str]:
    if sys.platform != "win32":
        return None
    candidates: List[str] = []
    for var in ("PROGRAMFILES(X86)", "PROGRAMFILES", "LOCALAPPDATA"):
        base = os.environ.get(var)
        if base:
            candidates.append(os.path.join(base, "Microsoft", "Edge", "Application", "msedge.exe"))
    for path in candidates:
        if os.path.isfile(path):
            return path
    return None


def open_window(url: str) -> Optional[subprocess.Popen]:
    """Open the UI. Returns the Edge process if we own one, else None."""
    edge = find_edge()
    if edge:
        profile = os.path.join(os.environ.get("LOCALAPPDATA") or os.path.expanduser("~"),
                               "ms43diff", "edge")
        os.makedirs(profile, exist_ok=True)
        try:
            return subprocess.Popen([
                edge, f"--app={url}", f"--user-data-dir={profile}",
                "--window-size=1440,900", "--no-first-run",
                "--no-default-browser-check", "--disable-features=Translate",
            ])
        except OSError:
            pass
    webbrowser.open(url)
    return None
