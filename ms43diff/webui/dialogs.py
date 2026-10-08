# -*- coding: utf-8 -*-
"""
Native Open/Save dialogs for the web interface.

The page runs in a browser, which never reveals real file paths, so dialogs are
shown by the program itself. tkinter is not thread-safe, so a single dedicated
thread owns the (hidden, topmost) Tk root and runs every dialog; HTTP handler
threads hand requests over through a queue and wait for the answer.
"""

from __future__ import annotations

import os
import queue
import threading
from typing import Callable, List, Optional, Tuple

FileTypes = List[Tuple[str, str]]


class DialogThread:
    def __init__(self) -> None:
        self._jobs: "queue.Queue" = queue.Queue()
        self._thread: Optional[threading.Thread] = None
        self._lock = threading.Lock()

    def _ensure(self) -> None:
        with self._lock:
            if self._thread is None or not self._thread.is_alive():
                self._thread = threading.Thread(target=self._loop, name="dialogs", daemon=True)
                self._thread.start()

    def _loop(self) -> None:
        import tkinter as tk
        from tkinter import filedialog

        root = tk.Tk()
        root.withdraw()
        while True:
            job, answer = self._jobs.get()
            try:
                root.attributes("-topmost", True)
                root.lift()
                root.focus_force()
                answer.put(("ok", job(root, filedialog)))
            except Exception as exc:  # noqa: BLE001 - reported to the caller
                answer.put(("error", exc))

    def _run(self, job: Callable) -> str:
        self._ensure()
        answer: "queue.Queue" = queue.Queue()
        self._jobs.put((job, answer))
        status, value = answer.get()
        if status == "error":
            raise value
        return value or ""

    def open_file(self, title: str, types: FileTypes, initial: str = "") -> str:
        start = os.path.dirname(initial) if initial else ""

        def job(root, filedialog):
            return filedialog.askopenfilename(parent=root, title=title, filetypes=types,
                                              initialdir=start or None)

        return self._run(job)

    def pick_folder(self, title: str, initial: str = "") -> str:
        def job(root, filedialog):
            return filedialog.askdirectory(parent=root, title=title, initialdir=initial or None,
                                           mustexist=False)

        return self._run(job)

    def save_file(self, title: str, types: FileTypes, default_name: str,
                  initial_dir: str = "") -> str:
        ext = os.path.splitext(default_name)[1]

        def job(root, filedialog):
            return filedialog.asksaveasfilename(parent=root, title=title, filetypes=types,
                                                defaultextension=ext,
                                                initialfile=default_name,
                                                initialdir=initial_dir or None)

        return self._run(job)


DIALOGS = DialogThread()
