# -*- coding: utf-8 -*-
"""
Error log shared by the window interfaces.

A windowed .exe has no visible stderr, so every error — especially while saving
a PDF — goes to %APPDATA%\\ms43diff\\ms43diff.log, a file the user can send.
"""

from __future__ import annotations

import datetime
import os
import sys
import traceback


def log_path() -> str:
    base = os.environ.get("APPDATA") or os.path.expanduser("~")
    folder = os.path.join(base, "ms43diff")
    try:
        os.makedirs(folder, exist_ok=True)
    except OSError:
        folder = os.path.dirname(os.path.abspath(sys.argv[0]))
    return os.path.join(folder, "ms43diff.log")


def log_write(text: str) -> str:
    path = log_path()
    try:
        with open(path, "a", encoding="utf-8") as fh:
            fh.write(f"\n===== {datetime.datetime.now():%Y-%m-%d %H:%M:%S} =====\n")
            fh.write(text.rstrip() + "\n")
    except OSError:
        pass
    return path


def log_exc(where: str) -> str:
    """Write the current exception to the log. Returns the log path."""
    return log_write(f"[{where}]\n" + traceback.format_exc())
