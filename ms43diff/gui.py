# -*- coding: utf-8 -*-
"""
ms43diff window interface (tkinter, no third-party libraries).

Tabs:

  1. Compare            — two bins of one software version, one XDF
  2. Different versions — two bins of different versions, each with its XDF
  3. Settings port      — plan for porting edits to another version (no writing)
  4. Patches            — which patchlist patches are applied
  5. Browse             — search a parameter and see its whole map
  6. VE tuning          — VE map correction from a wideband lambda log
  7. Reference          — offline MS4X Wiki

File paths are picked in dialogs, nothing depends on the current folder. The
last used files and the UI language are remembered in the settings file
(%APPDATA%\\ms43diff\\settings.json) so they need not be picked every time.
Changing the language rebuilds the window; chosen files are kept.

Heavy work (parsing a 3.5 MB XDF, comparing) runs in a worker thread so the
window does not freeze.
"""

from __future__ import annotations

import os
import queue
import sys
import threading
import traceback
from typing import Callable, Dict, List, Optional

import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from . import __version__, heatmap, i18n, mcpinstall, names, report, ru
from .binfile import BinFile, Reader, format_number
from .compare import PATCH_APPLIED, PATCH_NOT_APPLIED, PATCH_PARTIAL, check_patches, compare_bins
from .crossdiff import (
    P_SAFE_BYTES,
    P_SAFE_NAME,
    P_WARN,
    ST_DIFF,
    ST_ONLY_A,
    ST_ONLY_B,
    build_port_plan,
    cross_compare,
)
from .i18n import LANG_MENU, LANG_NAMES, LANGS, get_lang, set_lang, t
from .xdf import XdfFile


def app_title() -> str:
    return t("MS43 AI-Tuner {version} — BMW MS43 firmware comparison", version=__version__)


def xdf_types() -> list:
    return [(t("TunerPro definitions"), "*.xdf"), (t("All files"), "*.*")]


def bin_types() -> list:
    return [(t("Firmware files"), "*.bin"), (t("All files"), "*.*")]


# ---------------------------------------------------------------------------
# Error log (shared with the web interface, see applog.py)
# ---------------------------------------------------------------------------
from .applog import log_exc, log_path, log_write  # noqa: E402,F401


# ---------------------------------------------------------------------------
# Settings (shared with i18n: one settings.json for files and language)
# ---------------------------------------------------------------------------


def load_settings() -> Dict[str, str]:
    return i18n.load_settings()


def save_settings(data: Dict[str, str]) -> None:
    i18n.save_settings(**data)


# ---------------------------------------------------------------------------
# Parsed XDF cache — parsing 3.5 MB takes about a second
# ---------------------------------------------------------------------------

_XDF_CACHE: Dict[str, tuple] = {}


def load_xdf_cached(path: str) -> XdfFile:
    try:
        stamp = os.path.getmtime(path)
    except OSError:
        stamp = 0.0
    cached = _XDF_CACHE.get(path)
    if cached and cached[0] == stamp:
        return cached[1]
    parsed = XdfFile(path)
    _XDF_CACHE[path] = (stamp, parsed)
    return parsed


# ---------------------------------------------------------------------------
# Small widgets
# ---------------------------------------------------------------------------


class FileRow(ttk.Frame):
    """A "label — path — Browse" row."""

    def __init__(self, master, label: str, key: str, settings: Dict[str, str],
                 types=None, hint: str = ""):
        super().__init__(master)
        self.key = key
        self.settings = settings
        self.types = types or bin_types()
        self.var = tk.StringVar(value=settings.get(key, ""))

        ttk.Label(self, text=label, width=22, anchor="w").grid(row=0, column=0, sticky="w")
        entry = ttk.Entry(self, textvariable=self.var)
        entry.grid(row=0, column=1, sticky="ew", padx=(0, 6))
        ttk.Button(self, text=t("Browse…"), width=10, command=self.browse).grid(row=0, column=2)
        ttk.Button(self, text="✕", width=3, command=lambda: self.var.set("")).grid(
            row=0, column=3, padx=(4, 0)
        )
        self.columnconfigure(1, weight=1)
        if hint:
            ttk.Label(self, text=hint, foreground="#777").grid(
                row=1, column=1, sticky="w", pady=(0, 4)
            )

    def browse(self) -> None:
        start = os.path.dirname(self.var.get()) or self.settings.get("last_dir", "")
        path = filedialog.askopenfilename(
            title=t("Choose a file"), filetypes=self.types, initialdir=start or None
        )
        if path:
            self.var.set(path)
            self.settings[self.key] = path
            self.settings["last_dir"] = os.path.dirname(path)
            save_settings(self.settings)

    @property
    def path(self) -> str:
        return self.var.get().strip().strip('"')

    def remember(self) -> None:
        if self.path:
            self.settings[self.key] = self.path
            self.settings["last_dir"] = os.path.dirname(self.path)


class ResultTable(ttk.Frame):
    """Result table with a filter."""

    def __init__(self, master, columns: List[tuple], on_open: Optional[Callable] = None):
        super().__init__(master)
        self.on_open = on_open
        self._all_rows: List[tuple] = []

        top = ttk.Frame(self)
        top.pack(fill="x", pady=(0, 4))
        ttk.Label(top, text=t("Filter:")).pack(side="left")
        self.filter_var = tk.StringVar()
        self.filter_var.trace_add("write", lambda *_: self.apply_filter())
        ttk.Entry(top, textvariable=self.filter_var, width=40).pack(side="left", padx=6)
        self.count_label = ttk.Label(top, text="")
        self.count_label.pack(side="left", padx=10)

        holder = ttk.Frame(self)
        holder.pack(fill="both", expand=True)
        names = [c[0] for c in columns]
        self.tree = ttk.Treeview(holder, columns=names, show="headings", selectmode="browse")
        for name, title, width in columns:
            self.tree.heading(name, text=title,
                              command=lambda n=name: self.sort_by(n))
            self.tree.column(name, width=width, anchor="w", stretch=True)
        vs = ttk.Scrollbar(holder, orient="vertical", command=self.tree.yview)
        hs = ttk.Scrollbar(holder, orient="horizontal", command=self.tree.xview)
        self.tree.configure(yscrollcommand=vs.set, xscrollcommand=hs.set)
        self.tree.grid(row=0, column=0, sticky="nsew")
        vs.grid(row=0, column=1, sticky="ns")
        hs.grid(row=1, column=0, sticky="ew")
        holder.rowconfigure(0, weight=1)
        holder.columnconfigure(0, weight=1)

        self.tree.tag_configure("ok", foreground="#0a7f3f")
        self.tree.tag_configure("warn", foreground="#b06000")
        self.tree.tag_configure("bad", foreground="#b3261e")
        self._sort_desc = False
        if on_open:
            self.tree.bind("<Double-1>", lambda e: self._open())

        # Treeview cells cannot be selected, so copying is wired by hand:
        # Ctrl+C copies the parameter name (first column), right click opens a
        # menu. The name goes to the system clipboard via clipboard_append.
        self.tree.bind("<Control-c>", lambda e: self._copy_name())
        self.tree.bind("<Control-C>", lambda e: self._copy_name())
        self.tree.bind("<Button-3>", self._context_menu)
        self._menu = tk.Menu(self, tearoff=0)
        self._menu.add_command(label=t("Copy name"), command=self._copy_name)
        self._menu.add_command(label=t("Copy row (all columns)"),
                               command=self._copy_row)

    def _open(self) -> None:
        item = self.tree.focus()
        if item and self.on_open:
            self.on_open(self.tree.item(item, "values"))

    def _to_clipboard(self, text: str) -> None:
        self.clipboard_clear()
        self.clipboard_append(text)

    def _copy_name(self) -> None:
        values = self.selected_values()
        if values:
            self._to_clipboard(str(values[0]))

    def _copy_row(self) -> None:
        values = self.selected_values()
        if values:
            self._to_clipboard("\t".join(str(v) for v in values))

    def _context_menu(self, event) -> None:
        row = self.tree.identify_row(event.y)
        if row:
            self.tree.focus(row)
            self.tree.selection_set(row)
            self._menu.tk_popup(event.x_root, event.y_root)

    def set_rows(self, rows: List[tuple], tags: Optional[List[str]] = None) -> None:
        self._all_rows = [(r, (tags[i],) if tags else ()) for i, r in enumerate(rows)]
        self.apply_filter()

    def apply_filter(self) -> None:
        needle = self.filter_var.get().lower().strip()
        self.tree.delete(*self.tree.get_children())
        shown = 0
        for values, tag in self._all_rows:
            if needle and needle not in " ".join(str(v) for v in values).lower():
                continue
            self.tree.insert("", "end", values=values, tags=tag)
            shown += 1
        total = len(self._all_rows)
        self.count_label.config(
            text=(t("showing {shown} of {total}", shown=shown, total=total) if shown != total
                  else t("rows: {n}", n=total))
        )

    def sort_by(self, column: str) -> None:
        names = list(self.tree["columns"])
        idx = names.index(column)
        self._sort_desc = not self._sort_desc

        def key(pair):
            value = pair[0][idx]
            try:
                return (0, float(str(value).replace(",", ".").split()[0]))
            except (ValueError, IndexError):
                return (1, str(value).lower())

        self._all_rows.sort(key=key, reverse=self._sort_desc)
        self.apply_filter()

    def selected_values(self) -> Optional[tuple]:
        item = self.tree.focus()
        return self.tree.item(item, "values") if item else None


class TextWindow(tk.Toplevel):
    """A window with monospaced text (map, report)."""

    def __init__(self, master, title: str, text: str):
        super().__init__(master)
        self.title(title)
        self.geometry("1100x700")
        frame = ttk.Frame(self, padding=6)
        frame.pack(fill="both", expand=True)
        widget = tk.Text(frame, wrap="none", font=("Consolas", 10))
        vs = ttk.Scrollbar(frame, orient="vertical", command=widget.yview)
        hs = ttk.Scrollbar(frame, orient="horizontal", command=widget.xview)
        widget.configure(yscrollcommand=vs.set, xscrollcommand=hs.set)
        widget.grid(row=0, column=0, sticky="nsew")
        vs.grid(row=0, column=1, sticky="ns")
        hs.grid(row=1, column=0, sticky="ew")
        frame.rowconfigure(0, weight=1)
        frame.columnconfigure(0, weight=1)
        widget.insert("1.0", text)
        widget.configure(state="disabled")
        ttk.Button(self, text=t("Close"), command=self.destroy).pack(pady=6)


def wiki_sections_for(title: str) -> List:
    """Reference sections about the parameter (empty without a cache)."""
    try:
        from . import wikicache

        if not wikicache.available():
            return []
        return wikicache.guidance_for_map(title)
    except Exception:  # noqa: BLE001 - the reference must not break the window
        return []


def fill_wiki_text(widget: tk.Text, title: str, header: str = "") -> int:
    """Put everything the wiki knows about the parameter into a text widget."""
    widget.configure(state="normal")
    widget.delete("1.0", "end")
    sections = wiki_sections_for(title)
    if header:
        widget.insert("end", header + "\n\n", "head")
    if not sections:
        widget.insert(
            "end",
            t("Nothing about this parameter in the local reference.\n"
              "If the reference is not downloaded yet: the \"Reference\" tab, "
              "the \"Update from site\" button.\n"),
        )
        widget.configure(state="disabled")
        return 0
    from . import wikicache, wikitrans

    meanings = wikicache.value_meanings(title)
    if meanings:
        widget.insert("end", t("What the values mean") + "\n", "head")
        for key in sorted(meanings):
            widget.insert("end", f"  {key} — {wikitrans.translate_line(meanings[key])}\n")
        widget.insert("end", "\n")
    steps = wikicache.procedure_for(title)
    if steps:
        widget.insert("end", t("After the change") + "\n", "head")
        for step in steps:
            widget.insert("end", f"  • {wikitrans.translate_line(step)}\n", "warn")
        widget.insert("end", "\n")

    for section in sections:
        widget.insert("end", f"{section.page} / {section.heading}\n", "head")
        english = wikicache.focused_text(section, title)
        # the translated text comes first; the original goes below, greyed out
        shown = wikitrans.translate_block(english)
        for line in shown.split("\n"):
            if line.strip():
                widget.insert("end", line.strip() + "\n")
        for warning in section.caution_lines[:4]:
            widget.insert("end", "⚠ " + wikitrans.translate_line(warning) + "\n", "warn")
        if shown != english:
            widget.insert("end", "\n" + t("original (English):") + "\n", "dim")
            for line in english.split("\n"):
                if line.strip():
                    widget.insert("end", line.strip() + "\n", "dim")
        widget.insert("end", section.url + "\n\n", "url")
    widget.configure(state="disabled")
    return len(sections)


class WikiWindow(tk.Toplevel):
    """What the reference says about a specific parameter."""

    def __init__(self, master, title: str):
        super().__init__(master)
        self.title(t("Reference — {name}", name=title))
        self.geometry("980x700")
        frame = ttk.Frame(self, padding=6)
        frame.pack(fill="both", expand=True)
        widget = tk.Text(frame, wrap="word", font=("", 10), padx=10, pady=8)
        vs = ttk.Scrollbar(frame, orient="vertical", command=widget.yview)
        widget.configure(yscrollcommand=vs.set)
        widget.pack(side="left", fill="both", expand=True)
        vs.pack(side="right", fill="y")
        widget.tag_configure("head", font=("", 11, "bold"), foreground="#0b5cad",
                             spacing1=8, spacing3=4)
        widget.tag_configure("warn", background="#ffe9e2", spacing1=3, spacing3=3)
        widget.tag_configure("url", foreground="#0b5cad", spacing3=8)
        widget.tag_configure("dim", foreground="#999")
        fill_wiki_text(widget, title, header=title)
        ttk.Button(self, text=t("Close"), command=self.destroy).pack(pady=6)


class MapWindow(tk.Toplevel):
    """A map as a heat table: colour carries the meaning, numbers refine it.

    Three modes: values from A, values from B, and the difference. The
    difference uses a diverging scale with a neutral zero, so what the tuner
    raised or lowered is visible without reading the numbers.
    """

    CELL_W = 62
    CELL_H = 34
    LABEL_W = 66
    HEAD_H = 24

    def __init__(self, master, reader: Reader, item, reader_b: Optional[Reader] = None):
        super().__init__(master)
        self.reader = reader
        self.reader_b = reader_b
        self.item = item
        self.title(item.title)
        self.geometry("1180x760")

        self.before = reader.matrix(item) or []
        self.after = reader_b.matrix(item) if reader_b is not None else None
        self.dec = item.value_decimals
        self.otype = item.value_output_type
        self.units = names.unit(item.value_units)

        info = names.explain(item.title, item.description)
        head = ttk.Frame(self, padding=(10, 8))
        head.pack(fill="x")
        ttk.Label(head, text=item.title, font=("Consolas", 11, "bold")).pack(anchor="w")
        ttk.Label(head, text=info["name"], font=("", 10)).pack(anchor="w")
        if info["desc"]:
            ttk.Label(head, text=info["desc"], foreground="#555",
                      wraplength=1120, justify="left").pack(anchor="w")
        for key, label in (("note", t("What it does")), ("tune", t("How to tune"))):
            if info[key]:
                ttk.Label(head, text=f"{label}: {info[key]}", foreground="#0b5cad",
                          wraplength=1120, justify="left").pack(anchor="w", pady=(2, 0))
        data = item.data
        if data is not None and data.address is not None:
            ttk.Label(
                head,
                text=t("{shape} · XDF address 0x{address:X} · file 0x{offset:X} · {scaling}",
                       shape=item.shape_str, address=data.address,
                       offset=reader.file_offset(data.address),
                       scaling=item.value_equation.describe(self.units)),
                foreground="#777",
            ).pack(anchor="w", pady=(2, 0))

        bar = ttk.Frame(self, padding=(10, 4))
        bar.pack(fill="x")
        self.mode = tk.StringVar(value="delta" if self.after else "a")
        if self.after:
            for value, text in (("delta", t("difference")), ("a", t("values A")),
                                ("b", t("values B"))):
                ttk.Radiobutton(bar, text=text, value=value, variable=self.mode,
                                command=self.draw).pack(side="left", padx=(0, 10))
        ttk.Button(bar, text=t("As text"), command=self._show_text).pack(side="left", padx=6)
        ttk.Button(bar, text=t("Save PDF…"), command=self._save_pdf).pack(side="left")
        sections = wiki_sections_for(item.title)
        if sections:
            ttk.Button(bar, text=t("Reference ({n})", n=len(sections)),
                       command=self._show_wiki).pack(side="left", padx=6)
        self.hint = ttk.Label(bar, text="", foreground="#555")
        self.hint.pack(side="left", padx=14)

        warnings = [line for s in sections for line in s.caution_lines]
        if warnings:
            ttk.Label(self, text="⚠ " + warnings[0], foreground="#b3261e",
                      wraplength=1140, justify="left",
                      padding=(10, 2)).pack(fill="x")

        holder = ttk.Frame(self)
        holder.pack(fill="both", expand=True, padx=10, pady=(4, 4))
        self.canvas = tk.Canvas(holder, background="#ffffff", highlightthickness=0)
        vs = ttk.Scrollbar(holder, orient="vertical", command=self.canvas.yview)
        hs = ttk.Scrollbar(holder, orient="horizontal", command=self.canvas.xview)
        self.canvas.configure(yscrollcommand=vs.set, xscrollcommand=hs.set)
        self.canvas.grid(row=0, column=0, sticky="nsew")
        vs.grid(row=0, column=1, sticky="ns")
        hs.grid(row=1, column=0, sticky="ew")
        holder.rowconfigure(0, weight=1)
        holder.columnconfigure(0, weight=1)
        self.canvas.bind("<Motion>", self._on_motion)

        self.legend = tk.Canvas(self, height=34, background="#ffffff",
                                highlightthickness=0)
        self.legend.pack(fill="x", padx=10, pady=(0, 8))

        self.x_labels = self._labels("x")
        self.y_labels = self._labels("y")
        self.draw()

    # ------------------------------------------------------------------
    def _labels(self, which: str) -> List[str]:
        axis = self.item.axis_x if which == "x" else self.item.axis_y
        count = self.item.cols if which == "x" else self.item.rows
        values = self.reader.axis_values(self.item, which)
        if not values:
            return [str(i) for i in range(count)]
        decimals = axis.decimals if axis else 0
        return [format_number(v, decimals, 1) for v in values[:count]]

    def _fmt(self, value: float) -> str:
        return format_number(value, self.dec, self.otype)

    def draw(self) -> None:
        self.canvas.delete("all")
        rows, cols = self.item.rows, self.item.cols
        mode = self.mode.get()
        matrix = self.after if (mode == "b" and self.after) else self.before

        if mode == "delta" and self.after:
            scale = heatmap.delta_scale(self.before, self.after)
            low = high = 0.0
        else:
            scale = 0.0
            low, high = heatmap.value_range(matrix)

        for c in range(cols):
            x = self.LABEL_W + c * self.CELL_W
            self.canvas.create_text(x + self.CELL_W - 5, self.HEAD_H - 7,
                                    text=self.x_labels[c], anchor="e",
                                    font=("", 8), fill="#666")
        for r in range(rows):
            y = self.HEAD_H + r * self.CELL_H
            self.canvas.create_text(self.LABEL_W - 6, y + self.CELL_H / 2,
                                    text=self.y_labels[r], anchor="e",
                                    font=("", 8), fill="#666")
            for c in range(cols):
                a = self.before[r][c]
                b = self.after[r][c] if self.after else a
                if mode == "delta" and self.after:
                    delta = b - a
                    rgb = heatmap.delta_color(delta, scale)
                    main = self._fmt(b)
                    sub = ("" if not delta else
                           ("+" if delta > 0 else "") + self._fmt(delta))
                else:
                    value = b if mode == "b" else a
                    rgb = heatmap.value_color(value, low, high)
                    main = self._fmt(value)
                    sub = ""
                x = self.LABEL_W + c * self.CELL_W
                fill = heatmap.hex_color(rgb)
                fg = heatmap.hex_color(heatmap.text_color(rgb))
                self.canvas.create_rectangle(x, y, x + self.CELL_W - 2,
                                             y + self.CELL_H - 2,
                                             fill=fill, outline=fill,
                                             tags=(f"cell:{r}:{c}",))
                if sub:
                    self.canvas.create_text(x + self.CELL_W - 6, y + 10, text=main,
                                            anchor="e", font=("", 8), fill=fg)
                    self.canvas.create_text(x + self.CELL_W - 6, y + 23, text=sub,
                                            anchor="e", font=("", 7), fill=fg)
                else:
                    self.canvas.create_text(x + self.CELL_W - 6,
                                            y + self.CELL_H / 2, text=main,
                                            anchor="e", font=("", 8), fill=fg)

        width = self.LABEL_W + cols * self.CELL_W + 10
        height = self.HEAD_H + rows * self.CELL_H + 10
        self.canvas.configure(scrollregion=(0, 0, width, height))
        self._draw_legend(mode, scale, low, high)

    def _draw_legend(self, mode: str, scale: float, low: float, high: float) -> None:
        self.legend.delete("all")
        if mode == "delta" and self.after:
            stops = heatmap.delta_legend_stops(scale)
            caption = t("change")
        else:
            stops = heatmap.legend_stops(low, high)
            caption = t("value")
        if self.units:
            caption += f", {self.units}"
        self.legend.create_text(4, 17, text=caption + ":", anchor="w",
                                font=("", 8), fill="#666")
        x = 4 + 8 * len(caption) + 14
        for value, rgb in stops:
            fill = heatmap.hex_color(rgb)
            self.legend.create_rectangle(x, 6, x + 74, 28, fill=fill, outline=fill)
            self.legend.create_text(x + 37, 17, text=self._fmt(value),
                                    font=("", 8),
                                    fill=heatmap.hex_color(heatmap.text_color(rgb)))
            x += 76

    def _on_motion(self, event) -> None:
        cx = self.canvas.canvasx(event.x)
        cy = self.canvas.canvasy(event.y)
        c = int((cx - self.LABEL_W) // self.CELL_W)
        r = int((cy - self.HEAD_H) // self.CELL_H)
        if not (0 <= r < self.item.rows and 0 <= c < self.item.cols):
            self.hint.config(text="")
            return
        a = self.before[r][c]
        text = (f"[{self.y_labels[r]} × {self.x_labels[c]}]  "
                f"{self._fmt(a)} {self.units}")
        if self.after:
            b = self.after[r][c]
            delta = b - a
            sign = "+" if delta > 0 else ""
            text = (f"[{self.y_labels[r]} × {self.x_labels[c]}]  "
                    + t("was {a} → now {b} ({delta}) {units}", a=self._fmt(a), b=self._fmt(b),
                        delta=sign + self._fmt(delta), units=self.units))
        self.hint.config(text=text)

    def _show_text(self) -> None:
        TextWindow(self, self.item.title,
                   report.render_table(self.reader, self.item, self.reader_b))

    def _show_wiki(self) -> None:
        WikiWindow(self, self.item.title)

    def _save_pdf(self) -> None:
        from .pdfreport import PdfUnavailable, write_map_pdf

        path = filedialog.asksaveasfilename(
            title=t("Save the map as PDF"), defaultextension=".pdf",
            initialfile=f"{self.item.title}.pdf",
            filetypes=[("PDF", "*.pdf")],
        )
        if not path:
            return
        try:
            write_map_pdf(self.reader, [self.item], path, self.reader_b)
        except PdfUnavailable as exc:
            messagebox.showerror(t("PDF unavailable"), str(exc))
            return
        if messagebox.askyesno(t("Done"), t("Saved:\n{path}\n\nOpen it?", path=path)):
            os.startfile(path)  # noqa: S606


class ChoiceDialog(tk.Toplevel):
    """Choosing the matching parameter in the target version."""

    def __init__(self, master, title: str, candidates: List[tuple], all_titles: List[str]):
        super().__init__(master)
        self.title(t("Choose a match"))
        self.geometry("760x520")
        self.result: Optional[str] = None
        self.transient(master)
        self.grab_set()

        pad = ttk.Frame(self, padding=10)
        pad.pack(fill="both", expand=True)
        ttk.Label(pad, text=t("Parameter of the source version:"), foreground="#777").pack(anchor="w")
        ttk.Label(pad, text=title, font=("Consolas", 11, "bold")).pack(anchor="w", pady=(0, 8))
        ttk.Label(
            pad,
            text=t("Choose what to port it to in the target firmware.\n"
                   "On top — similar names with the same map size."),
            justify="left",
        ).pack(anchor="w", pady=(0, 8))

        search_var = tk.StringVar()
        row = ttk.Frame(pad)
        row.pack(fill="x", pady=(0, 6))
        ttk.Label(row, text=t("Search:")).pack(side="left")
        ttk.Entry(row, textvariable=search_var).pack(side="left", fill="x", expand=True, padx=6)

        self.listbox = tk.Listbox(pad, font=("Consolas", 10))
        self.listbox.pack(fill="both", expand=True)

        cand_titles = [name for name, _ in candidates]
        self._candidates = candidates
        self._all = all_titles

        def refill(*_):
            needle = search_var.get().lower().strip()
            self.listbox.delete(0, "end")
            self._items: List[str] = []
            for name, score in candidates:
                if needle and needle not in name.lower():
                    continue
                self.listbox.insert("end", t("★ {name}   (similarity {score:.2f})",
                                             name=name, score=score))
                self._items.append(name)
            for name in all_titles:
                if name in cand_titles:
                    continue
                if needle and needle not in name.lower():
                    continue
                self.listbox.insert("end", f"   {name}")
                self._items.append(name)
                self._items.append(t)

        search_var.trace_add("write", refill)
        refill()

        buttons = ttk.Frame(pad)
        buttons.pack(fill="x", pady=(8, 0))
        ttk.Button(buttons, text=t("Choose"), command=self._choose).pack(side="left")
        ttk.Button(buttons, text=t("Skip parameter"),
                   command=self._skip).pack(side="left", padx=6)
        ttk.Button(buttons, text=t("Cancel"), command=self.destroy).pack(side="right")
        self.listbox.bind("<Double-1>", lambda e: self._choose())

    def _choose(self) -> None:
        sel = self.listbox.curselection()
        if not sel:
            return
        self.result = self._items[sel[0]]
        self.destroy()

    def _skip(self) -> None:
        self.result = ""
        self.destroy()


class McpDialog(tk.Toplevel):
    """Connect the MCP server to Claude Desktop: pick the XDF and the firmware."""

    def __init__(self, app: "App"):
        super().__init__(app)
        self.app = app
        self.title(t("Connect to Claude Desktop"))
        self.geometry("820x330")
        self.transient(app)

        pad = ttk.Frame(self, padding=12)
        pad.pack(fill="both", expand=True)
        ttk.Label(
            pad, justify="left", wraplength=780,
            text=t("The AI assistant in Claude Desktop will be able to read this firmware "
                   "and the MS4X Wiki through ms43diff (read-only). Claude Desktop's "
                   "config is edited for you; other servers and settings are kept, and a "
                   ".bak copy is saved."),
        ).pack(anchor="w", pady=(0, 10))

        settings = app.settings
        for key, fallback in (("mcp_xdf", "cmp_xdf"), ("mcp_bin", "cmp_b")):
            if not settings.get(key) and settings.get(fallback):
                settings[key] = settings[fallback]
        self.xdf_row = FileRow(pad, t("XDF definition"), "mcp_xdf", settings, xdf_types())
        self.xdf_row.pack(fill="x", pady=3)
        self.bin_row = FileRow(pad, t("Firmware"), "mcp_bin", settings)
        self.bin_row.pack(fill="x", pady=3)

        current = mcpinstall.status()
        state = (t("Now: connected") if current else t("Now: not connected"))
        ttk.Label(pad, text=state + "   ·   " + mcpinstall.config_path(),
                  foreground="#777").pack(anchor="w", pady=(8, 0))

        buttons = ttk.Frame(pad)
        buttons.pack(fill="x", pady=(12, 0))
        ttk.Button(buttons, text=t("Connect"), command=self._install).pack(side="left")
        ttk.Button(buttons, text=t("Cancel"), command=self.destroy).pack(side="right")

    def _install(self) -> None:
        xdf, bin_path = self.xdf_row.path, self.bin_row.path
        if not (xdf and bin_path):
            messagebox.showwarning(t("Files missing"), t("Choose the XDF and the firmware."),
                                   parent=self)
            return
        self.xdf_row.remember()
        self.bin_row.remember()
        save_settings(self.app.settings)
        try:
            info = mcpinstall.install(xdf, bin_path)
        except mcpinstall.InstallError as exc:
            messagebox.showerror(t("AI assistant"), str(exc), parent=self)
            return
        log_write(f"[mcp] installed into {info['config']}")
        messagebox.showinfo(t("AI assistant"), mcpinstall.install_message(info), parent=self)
        self.destroy()


# ---------------------------------------------------------------------------
# Main window
# ---------------------------------------------------------------------------


def _descendants(widget) -> list:
    out = []
    for child in widget.winfo_children():
        out.append(child)
        out.extend(_descendants(child))
    return out


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.geometry("1280x820")
        self.minsize(1000, 620)
        self.settings = load_settings()
        self._queue: "queue.Queue" = queue.Queue()

        try:
            ttk.Style().theme_use("vista")
        except tk.TclError:
            pass

        self._build_ui()
        log_write(f"[start] ms43-ai-tuner {__version__}, lang={get_lang()}, "
                  f"frozen={getattr(sys, 'frozen', False)}, python={sys.version.split()[0]}")
        self._poll_id = self.after(120, self._poll)
        self.protocol("WM_DELETE_WINDOW", self._on_close)

    def _build_ui(self, tab_index: int = 0) -> None:
        """Build (or rebuild after a language change) the whole window."""
        self.title(app_title())
        self._build_menu()
        self.notebook = ttk.Notebook(self)
        self.notebook.pack(fill="both", expand=True, padx=8, pady=(8, 0))

        self._build_compare_tab()
        self._build_cross_tab()
        self._build_port_tab()
        self._build_patch_tab()
        self._build_browse_tab()
        self._build_vetune_tab()
        self._build_wiki_tab()

        statusbar = ttk.Frame(self)
        statusbar.pack(fill="x")
        self.status = ttk.Label(statusbar, text=t("Ready"), anchor="w", padding=(10, 5))
        self.status.pack(side="left", fill="x", expand=True)
        ttk.Button(statusbar, text=t("Show log"), command=self._open_log).pack(
            side="right", padx=6, pady=2)
        try:
            self.notebook.select(tab_index)
        except tk.TclError:
            pass

    def _build_menu(self) -> None:
        menubar = tk.Menu(self)
        lang_menu = tk.Menu(menubar, tearoff=0)
        self._lang_var = tk.StringVar(value=get_lang())
        for code in LANGS:
            lang_menu.add_radiobutton(label=LANG_NAMES[code], value=code,
                                      variable=self._lang_var,
                                      command=lambda c=code: self._switch_lang(c))
        menubar.add_cascade(label=LANG_MENU, menu=lang_menu)
        ai_menu = tk.Menu(menubar, tearoff=0)
        ai_menu.add_command(label=t("Connect to Claude Desktop…"), command=self._mcp_install)
        ai_menu.add_command(label=t("Disconnect from Claude Desktop"),
                            command=self._mcp_uninstall)
        menubar.add_cascade(label=t("AI assistant"), menu=ai_menu)
        self.config(menu=menubar)

    def _switch_lang(self, lang: str) -> None:
        """Apply a new UI language by rebuilding the window; files are kept."""
        if lang == get_lang():
            return
        for widget in _descendants(self):
            if isinstance(widget, FileRow):
                widget.remember()
        try:
            tab_index = self.notebook.index("current")
        except tk.TclError:
            tab_index = 0
        set_lang(lang)
        self.settings["lang"] = lang
        save_settings(self.settings)
        for child in self.winfo_children():
            child.destroy()
        self._build_ui(tab_index)
        self.set_status(t("Language changed. Results were cleared — run them again."))

    # ------------------------------------------------------------------
    def _mcp_install(self) -> None:
        McpDialog(self)

    def _mcp_uninstall(self) -> None:
        if not messagebox.askyesno(
                t("AI assistant"),
                t("Remove the ms43diff server from Claude Desktop? Other servers "
                  "and settings are not touched.")):
            return
        try:
            info = mcpinstall.uninstall()
        except mcpinstall.InstallError as exc:
            messagebox.showerror(t("AI assistant"), str(exc))
            return
        messagebox.showinfo(t("AI assistant"), mcpinstall.uninstall_message(info))

    def _open_log(self) -> None:
        path = log_path()
        if not os.path.isfile(path):
            log_write("[log] empty file created from the button")
        try:
            os.startfile(path)  # noqa: S606
        except (OSError, AttributeError):
            messagebox.showinfo(t("Log"), t("Log file:\n{path}", path=path))

    # ------------------------------------------------------------------
    def _on_close(self) -> None:
        save_settings(self.settings)
        self.destroy()

    def destroy(self) -> None:
        # cancel the pending call, otherwise Tcl complains "invalid command name"
        poll_id = getattr(self, "_poll_id", None)
        if poll_id is not None:
            try:
                self.after_cancel(poll_id)
            except tk.TclError:
                pass
            self._poll_id = None
        super().destroy()

    def set_status(self, text: str) -> None:
        self.status.config(text=text)
        self.update_idletasks()

    def run_async(self, work: Callable, done: Callable, busy: str) -> None:
        """Run a long operation in a thread, hand the result back to the UI thread."""
        self.set_status(busy)
        self.config(cursor="watch")

        def worker():
            try:
                self._queue.put((done, work(), None))
            except Exception as exc:  # noqa: BLE001 - shown to the user
                self._queue.put((done, None, (exc, traceback.format_exc())))

        threading.Thread(target=worker, daemon=True).start()

    def _poll(self) -> None:
        try:
            while True:
                done, result, error = self._queue.get_nowait()
                self.config(cursor="")
                if error is not None:
                    exc, trace = error
                    self.set_status(t("Error"))
                    path = log_write("[background]\n" + trace)
                    messagebox.showerror(
                        t("Error"),
                        t("{error}\n\nDetails were written to the log:\n{path}",
                          error=exc, path=path),
                    )
                else:
                    done(result)
        except queue.Empty:
            pass
        self._poll_id = self.after(120, self._poll)

    def report_callback_exception(self, exc, val, tb):
        """Catch any error in tkinter handlers (buttons, events).

        A windowed .exe has no visible stderr, so the error goes to the log and
        the user is shown its path — so there is something to send.
        """
        text = "".join(traceback.format_exception(exc, val, tb))
        path = log_write("[ui]\n" + text)
        try:
            messagebox.showerror(
                t("Error"),
                t("{error}\n\nDetails were written to the log:\n{path}", error=val, path=path),
            )
        except Exception:  # noqa: BLE001
            pass

    # ------------------------------------------------------------------
    @staticmethod
    def _section(parent, text: str) -> ttk.Frame:
        frame = ttk.LabelFrame(parent, text=text, padding=10)
        frame.pack(fill="x", padx=10, pady=(10, 0))
        return frame

    def _ask_save(self, default: str, kind: str = "html") -> str:
        types = {
            "html": [(t("HTML page"), "*.html")],
            "csv": [(t("CSV for Excel"), "*.csv")],
            "pdf": [(t("PDF document"), "*.pdf")],
            "bin": [(t("Firmware files"), "*.bin")],
        }[kind]
        start = self.settings.get("last_out_dir", "")
        path = filedialog.asksaveasfilename(
            title=t("Save as"), defaultextension=f".{kind}",
            initialfile=default, filetypes=types, initialdir=start or None
        )
        if path:
            self.settings["last_out_dir"] = os.path.dirname(path)
            save_settings(self.settings)
        return path

    # ==================================================================
    # Tab 1: comparing one version
    # ==================================================================
    def _build_compare_tab(self) -> None:
        tab = ttk.Frame(self.notebook)
        self.notebook.add(tab, text="  " + t("Comparison") + "  ")

        box = self._section(tab, t("Files (the same software version)"))
        self.cmp_xdf = FileRow(box, t("XDF definition"), "cmp_xdf", self.settings, xdf_types())
        self.cmp_xdf.pack(fill="x", pady=3)
        self.cmp_a = FileRow(box, t("Firmware A (stock)"), "cmp_a", self.settings)
        self.cmp_a.pack(fill="x", pady=3)
        self.cmp_b = FileRow(box, t("Firmware B (tune)"), "cmp_b", self.settings)

        controls = ttk.Frame(tab, padding=(10, 8))
        controls.pack(fill="x")
        self.cmp_axes = tk.BooleanVar(value=False)
        self.cmp_cks = tk.BooleanVar(value=True)
        ttk.Checkbutton(controls, text=t("include axes (ldp_*)"),
                        variable=self.cmp_axes).pack(side="left")
        ttk.Checkbutton(controls, text=t("show checksums"),
                        variable=self.cmp_cks).pack(side="left", padx=12)
        ttk.Button(controls, text=t("Compare"), command=self._do_compare).pack(side="left", padx=12)
        ttk.Button(controls, text=t("Save HTML"),
                   command=lambda: self._save_report("html")).pack(side="left")
        ttk.Button(controls, text=t("Save CSV"),
                   command=lambda: self._save_report("csv")).pack(side="left", padx=6)
        ttk.Button(controls, text=t("Save PDF"),
                   command=lambda: self._save_report("pdf")).pack(side="left")
        ttk.Label(controls, text=t("double-click a row — the map with highlighting"),
                  foreground="#777").pack(side="left", padx=10)

        self.cmp_summary = ttk.Label(tab, text="", padding=(10, 0), foreground="#555")
        self.cmp_summary.pack(fill="x")

        panes = ttk.PanedWindow(tab, orient="vertical")
        panes.pack(fill="both", expand=True, padx=10, pady=10)
        top = ttk.Frame(panes)
        bottom = ttk.Frame(panes)
        panes.add(top, weight=3)
        panes.add(bottom, weight=2)

        self.cmp_table = ResultTable(
            top,
            [("param", t("Parameter"), 250), ("name", t("What it is"), 330),
             ("value", t("Before → After"), 230), ("units", t("Units"), 70),
             ("cells", t("Cells"), 70), ("cat", t("Category"), 170),
             ("addr", t("Address"), 90)],
            on_open=self._open_compare_detail,
        )
        self.cmp_table.pack(fill="both", expand=True)
        self.cmp_table.tree.bind("<<TreeviewSelect>>", lambda e: self._compare_wiki())

        ttk.Label(bottom, text=t("What the parameter is, what the values mean "
                                 "and what MS4X Wiki says"),
                  foreground="#555").pack(anchor="w", pady=(4, 2))
        holder = ttk.Frame(bottom)
        holder.pack(fill="both", expand=True)
        self.cmp_wiki = tk.Text(holder, wrap="word", font=("", 9),
                                padx=8, pady=6, height=10)
        vs = ttk.Scrollbar(holder, orient="vertical", command=self.cmp_wiki.yview)
        self.cmp_wiki.configure(yscrollcommand=vs.set, state="disabled")
        self.cmp_wiki.pack(side="left", fill="both", expand=True)
        vs.pack(side="right", fill="y")
        self.cmp_wiki.tag_configure("head", font=("", 10, "bold"),
                                    foreground="#0b5cad", spacing1=6, spacing3=3)
        self.cmp_wiki.tag_configure("warn", background="#ffe9e2",
                                    spacing1=2, spacing3=2)
        self.cmp_wiki.tag_configure("url", foreground="#0b5cad", spacing3=6)
        self.cmp_wiki.tag_configure("dim", foreground="#999")
        self._cmp_result = None

    def _do_compare(self) -> None:
        xdf_path, a, b = self.cmp_xdf.path, self.cmp_a.path, self.cmp_b.path
        if not (xdf_path and a and b):
            messagebox.showwarning(t("Files missing"),
                                   t("Choose the XDF and both firmware files."))
            return
        for row in (self.cmp_xdf, self.cmp_a, self.cmp_b):
            row.remember()
        save_settings(self.settings)
        # Read tkinter variables HERE: they must not be touched from the worker
        # thread — Tcl does not survive that.
        with_axes = self.cmp_axes.get()
        with_cks = self.cmp_cks.get()

        def work():
            xdf = load_xdf_cached(xdf_path)
            return compare_bins(
                xdf, BinFile(a), BinFile(b),
                include_axes=with_axes,
                include_checksums=with_cks,
            )

        self.run_async(work, self._show_compare, t("Comparing…"))

    def _show_compare(self, result) -> None:
        self._cmp_result = result
        rows, tags = [], []
        for change in result.changes:
            data = report.change_row(result.xdf, change)
            rows.append((data["title"], data["name"], data["summary"],
                         data["units"], data["changed"], data["category"],
                         data["address"]))
            tags.append("ok" if change.max_pct > 0 else
                        "bad" if change.max_pct < 0 else "warn")
        self.cmp_table.set_rows(rows, tags)

        warn = ""
        for tag, reader in (("A", result.reader_a), ("B", result.reader_b)):
            message = reader.version_warning()
            if message:
                warn += "   " + t("WARNING ({tag}): {text}", tag=tag, text=message)
        self.cmp_summary.config(
            text=t("Parameters changed: {changed} · same: {same} · bytes changed: {bytes} · "
                   "code edit blocks: {blocks}", changed=result.changed_params,
                   same=result.identical, bytes=result.total_bytes_changed,
                   blocks=len(result.code_blocks)) + warn
        )
        self.set_status(t("Done: {n} changes", n=result.changed_params))

    def _compare_wiki(self) -> None:
        values = self.cmp_table.selected_values()
        if not values:
            return
        header = f"{values[0]} — {values[1]}\n" + t("before → after: {value}",
                                                     value=f"{values[2]} {values[3]}")
        fill_wiki_text(self.cmp_wiki, values[0], header=header.rstrip())

    def _open_compare_detail(self, values) -> None:
        if not self._cmp_result:
            return
        title = values[0]
        item = self._cmp_result.xdf.by_title(title)
        if item is None:
            return
        if item.cell_count > 1:
            MapWindow(self, self._cmp_result.reader_a, item, self._cmp_result.reader_b)
        else:
            TextWindow(self, title, report.render_table(
                self._cmp_result.reader_a, item, self._cmp_result.reader_b))

    def _save_report(self, kind: str) -> None:
        if not self._cmp_result:
            messagebox.showinfo(t("No data"), t("Run the comparison first."))
            return
        path = self._ask_save(t("ms43_report") + "." + kind, kind)
        if not path:
            return
        log_write(f"[save report] format={kind}, file={path}")
        try:
            if kind == "html":
                report.write_html(self._cmp_result, path)
            elif kind == "pdf":
                from .pdfreport import PdfUnavailable, write_compare_pdf

                try:
                    write_compare_pdf(self._cmp_result, path)
                except PdfUnavailable as exc:
                    messagebox.showerror(
                        t("PDF unavailable"),
                        t("{error}\n\nLog: {path}", error=exc,
                          path=log_write("[PDF unavailable] " + str(exc))))
                    return
            else:
                report.write_csv(self._cmp_result, path)
        except Exception as exc:  # noqa: BLE001 - show the reason and log it
            lp = log_exc(f"saving {kind}")
            messagebox.showerror(
                t("Could not save"),
                t("{error}\n\nDetails were written to the log:\n{path}", error=exc, path=lp))
            return
        if not os.path.isfile(path):
            lp = log_write(f"[saving {kind}] the function returned but no file appeared: {path}")
            messagebox.showerror(t("File not created"),
                                 t("The file did not appear: {path}\nLog: {log}", path=path, log=lp))
            return
        self.set_status(t("Saved: {path}", path=path))
        log_write(f"[save report] success, {os.path.getsize(path)} bytes")
        if messagebox.askyesno(t("Done"), t("Report saved:\n{path}\n\nOpen it?", path=path)):
            os.startfile(path)  # noqa: S606 - a file we have just created

    # ==================================================================
    # Tab 2: different versions
    # ==================================================================
    def _build_cross_tab(self) -> None:
        tab = ttk.Frame(self.notebook)
        self.notebook.add(tab, text="  " + t("Different versions") + "  ")

        note = ttk.Label(
            tab,
            text=t("Here each firmware has its own XDF. Parameters are matched by name,\n"
                   "physical values are compared, not bytes — conversion formulas and\n"
                   "addresses may differ between software versions."),
            padding=(10, 8), foreground="#555", justify="left",
        )
        note.pack(fill="x")

        box = self._section(tab, t("Firmware A"))
        self.x_xdf_a = FileRow(box, t("XDF of version A"), "x_xdf_a", self.settings, xdf_types())
        self.x_xdf_a.pack(fill="x", pady=3)
        self.x_bin_a = FileRow(box, t("Firmware A"), "x_bin_a", self.settings)
        self.x_bin_a.pack(fill="x", pady=3)

        box = self._section(tab, t("Firmware B"))
        self.x_xdf_b = FileRow(box, t("XDF of version B"), "x_xdf_b", self.settings, xdf_types())
        self.x_xdf_b.pack(fill="x", pady=3)
        self.x_bin_b = FileRow(box, t("Firmware B"), "x_bin_b", self.settings)
        self.x_bin_b.pack(fill="x", pady=3)

        controls = ttk.Frame(tab, padding=(10, 8))
        controls.pack(fill="x")
        ttk.Button(controls, text=t("Compare"), command=self._do_cross).pack(side="left")
        ttk.Button(controls, text=t("Save HTML"),
                   command=self._save_cross).pack(side="left", padx=8)
        self.cross_summary = ttk.Label(tab, text="", padding=(10, 0), foreground="#555")
        self.cross_summary.pack(fill="x")

        self.cross_table = ResultTable(
            tab,
            [("param", t("Parameter"), 250), ("status", t("Status"), 110),
             ("name", t("What it is"), 320), ("value", "A → B", 220),
             ("units", t("Units"), 70), ("notes", t("Notes"), 380)],
        )
        self.cross_table.pack(fill="both", expand=True, padx=10, pady=10)
        self._cross_result = None

    def _do_cross(self) -> None:
        paths = [self.x_xdf_a.path, self.x_bin_a.path,
                 self.x_xdf_b.path, self.x_bin_b.path]
        if not all(paths):
            messagebox.showwarning(t("Files missing"),
                                   t("Choose both XDFs and both firmware files."))
            return
        for row in (self.x_xdf_a, self.x_bin_a, self.x_xdf_b, self.x_bin_b):
            row.remember()
        save_settings(self.settings)

        def work():
            return cross_compare(
                load_xdf_cached(paths[0]), BinFile(paths[1]),
                load_xdf_cached(paths[2]), BinFile(paths[3]),
                only_differences=True,
            )

        self.run_async(work, self._show_cross, t("Comparing different versions…"))

    def _show_cross(self, result) -> None:
        self._cross_result = result
        rows, tags = [], []
        for row in result.rows:
            item = row.item
            units = names.unit(item.value_units) if item else ""
            name = names.explain(row.title, item.description if item else "")["name"]
            rows.append((row.title, row.status_label, name, row.summary(), units,
                         " | ".join(row.notes)))
            tags.append({ST_DIFF: "warn", ST_ONLY_A: "bad",
                         ST_ONLY_B: "ok"}.get(row.status, ""))
        self.cross_table.set_rows(rows, tags)
        self.cross_summary.config(
            text=t("Different: {diff} · same: {same} · only in A: {a} · only in B: {b}",
                   diff=len(result.different), same=result.identical,
                   a=len(result.only_a), b=len(result.only_b))
        )
        self.set_status(t("Done"))

    def _save_cross(self) -> None:
        if not self._cross_result:
            messagebox.showinfo(t("No data"), t("Run the comparison first."))
            return
        path = self._ask_save(t("ms43_versions") + ".html", "html")
        if path:
            report.write_cross_html(self._cross_result, path)
            self.set_status(t("Saved: {path}", path=path))
            if messagebox.askyesno(t("Done"), t("Report saved:\n{path}\n\nOpen it?", path=path)):
                os.startfile(path)  # noqa: S606

    # ==================================================================
    # Tab 3: settings port
    # ==================================================================
    def _build_port_tab(self) -> None:
        tab = ttk.Frame(self.notebook)
        self.notebook.add(tab, text="  " + t("Settings port") + "  ")

        ttk.Label(
            tab,
            text=t("Builds a PLAN for porting your edits to firmware of another software "
                   "version and writes nothing.\n"
                   "Edits are found as the difference between the source version stock "
                   "and your firmware.\n"
                   "\"Safe\" means a byte match (copy 1:1) or a name match "
                   "(port the value by hand).\n"
                   "Everything else gets a warning. Make all edits by hand in TunerPro."),
            padding=(10, 8), foreground="#a05000", justify="left",
        ).pack(fill="x")

        box = self._section(tab, t("Source version (port from)"))
        self.p_xdf_src = FileRow(box, t("Source version XDF"), "p_xdf_src",
                                 self.settings, xdf_types())
        self.p_xdf_src.pack(fill="x", pady=3)
        self.p_stock = FileRow(box, t("Source version stock"), "p_stock", self.settings,
                               hint=t("reference: your edits are found against it"))
        self.p_stock.pack(fill="x", pady=3)
        self.p_tuned = FileRow(box, t("Your firmware"), "p_tuned", self.settings)
        self.p_tuned.pack(fill="x", pady=3)

        box = self._section(tab, t("Target version (port to)"))
        self.p_xdf_dst = FileRow(box, t("Target version XDF"), "p_xdf_dst",
                                 self.settings, xdf_types())
        self.p_xdf_dst.pack(fill="x", pady=3)
        self.p_target = FileRow(box, t("Target firmware"), "p_target", self.settings)
        self.p_target.pack(fill="x", pady=3)

        controls = ttk.Frame(tab, padding=(10, 8))
        controls.pack(fill="x")
        ttk.Button(controls, text=t("Build the plan"),
                   command=self._do_port).pack(side="left")
        ttk.Button(controls, text=t("Save HTML report"),
                   command=lambda: self._save_port("html")).pack(side="left", padx=8)
        ttk.Button(controls, text=t("Save CSV"),
                   command=lambda: self._save_port("csv")).pack(side="left")
        ttk.Label(controls, text=t("the program only shows the plan; you edit by hand "
                                   "in TunerPro. Double-click a row for details"),
                  foreground="#777").pack(side="left", padx=10)

        self.port_summary = ttk.Label(tab, text="", padding=(10, 0), foreground="#555")
        self.port_summary.pack(fill="x")

        self.port_table = ResultTable(
            tab,
            [("param", t("Source parameter"), 240), ("status", t("Status"), 210),
             ("dst", t("Target parameter"), 220), ("name", t("What it is"), 250),
             ("value", t("Values"), 260),
             ("detail", t("What matched / what is wrong"), 420)],
            on_open=self._show_port_detail,
        )
        self.port_table.pack(fill="both", expand=True, padx=10, pady=10)
        self._port_plan = None

    def _do_port(self) -> None:
        paths = [self.p_xdf_src.path, self.p_stock.path, self.p_tuned.path,
                 self.p_xdf_dst.path, self.p_target.path]
        if not all(paths):
            messagebox.showwarning(
                t("Files missing"),
                t("Needed: the source version XDF, its stock, your firmware,\n"
                  "the target version XDF and the target firmware.")
            )
            return
        for row in (self.p_xdf_src, self.p_stock, self.p_tuned,
                    self.p_xdf_dst, self.p_target):
            row.remember()
        save_settings(self.settings)

        def work():
            return build_port_plan(
                load_xdf_cached(paths[0]), BinFile(paths[1]), BinFile(paths[2]),
                load_xdf_cached(paths[3]), BinFile(paths[4]),
            )

        self.run_async(work, self._show_port, t("Building the port plan…"))

    def _show_port(self, plan) -> None:
        self._port_plan = plan
        rows, tags = [], []
        for entry in plan.entries:
            item = entry.item_dst or entry.item_src
            units = names.unit(item.value_units) if item else ""
            name = names.explain(entry.title, item.description if item else "")["name"]
            bits = entry.match_bits if entry.safe else entry.warn_bits
            rows.append((entry.title, entry.status_label, entry.dst_title or "—", name,
                         f"{entry.summary()} {units}".strip(), " | ".join(bits)))
            tags.append({P_SAFE_BYTES: "ok", P_SAFE_NAME: "ok",
                         P_WARN: "bad"}.get(entry.status, "bad"))
        self.port_table.set_rows(rows, tags)
        self.port_summary.config(
            text=t("You changed: {n} · safe by bytes: {bytes} · safe by name: {name} · "
                   "with a warning: {warned}", n=len(plan.entries), bytes=len(plan.safe_bytes),
                   name=len(plan.safe_name), warned=len(plan.warned))
        )
        self.set_status(t("Plan ready: {safe} safe, {warned} with a warning",
                          safe=len(plan.safe), warned=len(plan.warned)))

    def _show_port_detail(self, values) -> None:
        if not self._port_plan:
            return
        title = values[0]
        entry = next((e for e in self._port_plan.entries if e.title == title), None)
        if entry is None:
            return
        item = entry.item_dst or entry.item_src
        units = names.unit(item.value_units) if item else ""
        info = names.explain(entry.title, item.description if item else "")
        lines = [
            f"{entry.title}",
            f"{info['name']}",
            "",
            t("Status: {text}", text=entry.status_label),
            t("Your value: {value}", value=f"{entry.summary()} {units}".rstrip()),
        ]
        if entry.dst_title and entry.dst_title != entry.title:
            lines.append(t("Name in the target version: {name}", name=entry.dst_title))
        lines.append("")
        if entry.safe:
            lines.append(t("What matched:"))
            for b in entry.match_bits:
                lines.append(f"  • {b}")
            lines.append("")
            if entry.status == P_SAFE_BYTES:
                lines.append(t("Can be ported one-to-one: enter the same value in TunerPro "
                               "into the parameter with the same name."))
            else:
                lines.append(t("Port the PHYSICAL value (what TunerPro shows), not the raw "
                               "bytes — the format differs in the target version."))
        else:
            lines.append(t("What is wrong:"))
            for b in entry.warn_bits:
                lines.append(f"  • {b}")
            lines.append("")
            lines.append(t("This cannot be ported automatically — sort it out by hand."))
        messagebox.showinfo(t("Port — {name}", name=entry.title), "\n".join(lines))

    def _save_port(self, kind: str) -> None:
        if not self._port_plan:
            messagebox.showinfo(t("No data"), t("Build the plan first."))
            return
        path = self._ask_save(t("ms43_port") + "." + kind, kind)
        if not path:
            return
        if kind == "html":
            report.write_port_html(self._port_plan, path)
        else:
            report.write_port_csv(self._port_plan, path)
        self.set_status(t("Saved: {path}", path=path))
        if messagebox.askyesno(t("Done"), t("Report saved:\n{path}\n\nOpen it?", path=path)):
            os.startfile(path)  # noqa: S606

    # ==================================================================
    # Tab 4: patches
    # ==================================================================
    def _build_patch_tab(self) -> None:
        tab = ttk.Frame(self.notebook)
        self.notebook.add(tab, text="  " + t("Patches") + "  ")

        box = self._section(tab, t("Files"))
        self.pt_xdf = FileRow(box, "Patchlist XDF", "pt_xdf", self.settings, xdf_types(),
                              hint=t("e.g. Siemens_MS43_MS430069_Community_Patchlist_*.xdf"))
        self.pt_xdf.pack(fill="x", pady=3)
        self.pt_bin = FileRow(box, t("Firmware"), "pt_bin", self.settings)
        self.pt_bin.pack(fill="x", pady=3)

        controls = ttk.Frame(tab, padding=(10, 8))
        controls.pack(fill="x")
        ttk.Button(controls, text=t("Check"), command=self._do_patches).pack(side="left")
        self.patch_summary = ttk.Label(tab, text="", padding=(10, 0), foreground="#555")
        self.patch_summary.pack(fill="x")

        self.patch_table = ResultTable(
            tab,
            [("state", t("Status"), 130), ("title", t("Patch"), 340),
             ("cat", t("Category"), 240), ("desc", t("Description"), 620)],
        )
        self.patch_table.pack(fill="both", expand=True, padx=10, pady=10)

    def _do_patches(self) -> None:
        xdf_path, bin_path = self.pt_xdf.path, self.pt_bin.path
        if not (xdf_path and bin_path):
            messagebox.showwarning(t("Files missing"),
                                   t("Choose the patchlist XDF and the firmware."))
            return
        self.pt_xdf.remember()
        self.pt_bin.remember()
        save_settings(self.settings)

        def work():
            patchlist = load_xdf_cached(xdf_path)
            if not patchlist.patches:
                raise ValueError(t("This XDF has no <XDFPATCH> entries. A patchlist "
                                   "file is needed, not a regular definition."))
            return patchlist, check_patches(patchlist, BinFile(bin_path))

        self.run_async(work, self._show_patches, t("Checking patches…"))

    def _show_patches(self, payload) -> None:
        patchlist, statuses = payload
        rows, tags = [], []
        for status in statuses:
            cat_names = [patchlist.category_name(c) for c in status.patch.categories]
            cat = ", ".join(names.category(n) for n in cat_names) or "—"
            rows.append((status.label, status.patch.title, cat,
                         names.description(status.patch.description)))
            tags.append({PATCH_APPLIED: "ok", PATCH_NOT_APPLIED: "",
                         PATCH_PARTIAL: "warn"}.get(status.state, "bad"))
        self.patch_table.set_rows(rows, tags)
        applied = sum(1 for s in statuses if s.state == PATCH_APPLIED)
        self.patch_summary.config(text=t("Applied {n} of {total}", n=applied, total=len(statuses)))
        self.set_status(t("Done"))

    # ==================================================================
    # Tab 5: browse
    # ==================================================================
    def _build_browse_tab(self) -> None:
        tab = ttk.Frame(self.notebook)
        self.notebook.add(tab, text="  " + t("Browse") + "  ")

        box = self._section(tab, t("Files"))
        self.br_xdf = FileRow(box, t("XDF definition"), "br_xdf", self.settings, xdf_types())
        self.br_xdf.pack(fill="x", pady=3)
        self.br_bin = FileRow(box, t("Firmware"), "br_bin", self.settings)
        self.br_bin.pack(fill="x", pady=3)

        controls = ttk.Frame(tab, padding=(10, 8))
        controls.pack(fill="x")
        ttk.Label(controls, text=t("Search:")).pack(side="left")
        self.br_query = tk.StringVar()
        entry = ttk.Entry(controls, textvariable=self.br_query, width=40)
        entry.pack(side="left", padx=6)
        entry.bind("<Return>", lambda e: self._do_browse())
        ttk.Button(controls, text=t("Find"), command=self._do_browse).pack(side="left")
        ttk.Label(controls, text=t("English or Russian: rev limit, knock, lambda…"),
                  foreground="#777").pack(side="left", padx=10)

        panes = ttk.PanedWindow(tab, orient="vertical")
        panes.pack(fill="both", expand=True, padx=10, pady=10)
        top = ttk.Frame(panes)
        bottom = ttk.Frame(panes)
        panes.add(top, weight=3)
        panes.add(bottom, weight=2)

        self.browse_table = ResultTable(
            top,
            [("param", t("Parameter"), 260), ("name", t("What it is"), 380),
             ("shape", t("Type"), 90), ("value", t("Value"), 220),
             ("units", t("Units"), 70), ("cat", t("Category"), 200),
             ("addr", t("Address"), 90)],
            on_open=self._open_browse_detail,
        )
        self.browse_table.pack(fill="both", expand=True)
        # selecting a row shows what the wiki says about it right away —
        # the whole point is not having to go to the site
        self.browse_table.tree.bind("<<TreeviewSelect>>",
                                    lambda e: self._browse_wiki())

        ttk.Label(bottom, text=t("MS4X Wiki reference for the selected parameter"),
                  foreground="#555").pack(anchor="w", pady=(4, 2))
        holder = ttk.Frame(bottom)
        holder.pack(fill="both", expand=True)
        self.browse_wiki = tk.Text(holder, wrap="word", font=("", 9),
                                   padx=8, pady=6, height=10)
        vs = ttk.Scrollbar(holder, orient="vertical", command=self.browse_wiki.yview)
        self.browse_wiki.configure(yscrollcommand=vs.set, state="disabled")
        self.browse_wiki.pack(side="left", fill="both", expand=True)
        vs.pack(side="right", fill="y")
        self.browse_wiki.tag_configure("head", font=("", 10, "bold"),
                                       foreground="#0b5cad", spacing1=6, spacing3=3)
        self.browse_wiki.tag_configure("warn", background="#ffe9e2",
                                       spacing1=2, spacing3=2)
        self.browse_wiki.tag_configure("url", foreground="#0b5cad", spacing3=6)
        self.browse_wiki.tag_configure("dim", foreground="#999")
        self._browse_reader = None

    def _do_browse(self) -> None:
        xdf_path, bin_path = self.br_xdf.path, self.br_bin.path
        if not (xdf_path and bin_path):
            messagebox.showwarning(t("Files missing"), t("Choose the XDF and the firmware."))
            return
        self.br_xdf.remember()
        self.br_bin.remember()
        save_settings(self.settings)
        needle = self.br_query.get().lower().strip()

        def work():
            xdf = load_xdf_cached(xdf_path)
            reader = Reader(xdf, BinFile(bin_path))
            found = []
            for item in xdf.readable_items(include_axes=True):
                info = names.explain(item.title, item.description)
                haystack = " ".join(
                    [item.title, item.description, info["name"], info["decoded"],
                     info["desc"], ru.name_ru(item.title)]
                ).lower()
                if needle and needle not in haystack:
                    continue
                found.append((item, info, reader.summary(item)))
                if len(found) >= 2000:
                    break
            return reader, found

        self.run_async(work, self._show_browse, t("Searching…"))

    def _show_browse(self, payload) -> None:
        reader, found = payload
        self._browse_reader = reader
        rows = []
        for item, info, summary in found:
            rows.append((
                item.title, info["name"], item.shape_str, summary or "",
                names.unit(item.value_units),
                report.item_categories(reader.xdf, item),
                f"0x{item.address:X}" if item.address is not None else "",
            ))
        self.browse_table.set_rows(rows)
        self.set_status(t("Found: {n}  (double-click — show the map)", n=len(rows)))

    def _browse_wiki(self) -> None:
        values = self.browse_table.selected_values()
        if not values:
            return
        title = values[0]
        header = f"{title} — {values[1]}"
        if values[3]:
            header += "\n" + t("now in the firmware: {value}",
                                value=f"{values[3]} {values[4]}".rstrip())
        fill_wiki_text(self.browse_wiki, title, header=header)

    def _open_browse_detail(self, values) -> None:
        if not self._browse_reader:
            return
        item = self._browse_reader.xdf.by_title(values[0])
        if item is None:
            return
        if item.cell_count > 1:
            MapWindow(self, self._browse_reader, item)
        else:
            TextWindow(self, values[0], report.render_table(self._browse_reader, item))


    # ==================================================================
    # Tab 6: VE tuning from a wideband log
    # ==================================================================
    def _build_vetune_tab(self) -> None:
        tab = ttk.Frame(self.notebook)
        self.notebook.add(tab, text="  " + t("VE tuning") + "  ")

        ttk.Label(
            tab,
            text=t("Calculates a VE map correction from a wideband lambda log:\n"
                   "if the mixture is leaner than the target, there was more air than the ECU thought.\n"
                   "Cells with too few samples are left alone. Explanations and\n"
                   "warnings come from the offline MS4X Wiki copy."),
            padding=(10, 8), foreground="#555", justify="left",
        ).pack(fill="x")

        box = self._section(tab, t("Files"))
        self.v_xdf = FileRow(box, t("XDF definition"), "v_xdf", self.settings, xdf_types())
        self.v_xdf.pack(fill="x", pady=3)
        self.v_bin = FileRow(box, t("Firmware"), "v_bin", self.settings)
        self.v_bin.pack(fill="x", pady=3)
        self.v_log = FileRow(box, t("Log (CSV)"), "v_log", self.settings,
                             [(t("Logs"), "*.csv;*.txt"), (t("All files"), "*.*")],
                             hint=t("TunerPro export or your wideband controller file"))
        self.v_log.pack(fill="x", pady=3)

        box = self._section(tab, t("Settings"))
        row = ttk.Frame(box)
        row.pack(fill="x", pady=3)
        ttk.Label(row, text=t("Map"), width=22, anchor="w").pack(side="left")
        self.v_map = tk.StringVar()
        self.v_map_box = ttk.Combobox(row, textvariable=self.v_map, width=48)
        self.v_map_box.pack(side="left", padx=(0, 6))
        ttk.Button(row, text=t("Find maps"), command=self._fill_maps).pack(side="left")

        row = ttk.Frame(box)
        row.pack(fill="x", pady=3)
        ttk.Label(row, text=t("Mode"), width=22, anchor="w").pack(side="left")
        self.v_mode = tk.StringVar(value="lambda")
        ttk.Combobox(row, textvariable=self.v_mode, width=12, state="readonly",
                     values=("lambda", "trim", "both")).pack(side="left")
        ttk.Label(row, text=t("target lambda")).pack(side="left", padx=(16, 4))
        self.v_target = tk.StringVar(value="1.00")
        ttk.Entry(row, textvariable=self.v_target, width=7).pack(side="left")
        ttk.Label(row, text=t("min. samples per cell")).pack(side="left", padx=(16, 4))
        self.v_min = tk.StringVar(value="8")
        ttk.Entry(row, textvariable=self.v_min, width=6).pack(side="left")
        ttk.Label(row, text=t("max. correction, %")).pack(side="left", padx=(16, 4))
        self.v_step = tk.StringVar(value="25")
        ttk.Entry(row, textvariable=self.v_step, width=6).pack(side="left")
        ttk.Label(row, text=t("sensor delay")).pack(side="left", padx=(16, 4))
        self.v_delay = tk.StringVar(value="0")
        ttk.Entry(row, textvariable=self.v_delay, width=5).pack(side="left")

        controls = ttk.Frame(tab, padding=(10, 8))
        controls.pack(fill="x")
        ttk.Button(controls, text=t("Log columns"),
                   command=self._show_log_columns).pack(side="left")
        ttk.Button(controls, text=t("Calculate correction"),
                   command=self._do_vetune).pack(side="left", padx=8)
        ttk.Button(controls, text=t("HTML report"),
                   command=self._save_vetune_html).pack(side="left")
        ttk.Button(controls, text=t("Write a new .bin…"),
                   command=self._write_vetune).pack(side="left", padx=16)

        self.v_summary = ttk.Label(tab, text="", padding=(10, 0), foreground="#555",
                                   wraplength=1200, justify="left")
        self.v_summary.pack(fill="x")

        holder = ttk.Frame(tab)
        holder.pack(fill="both", expand=True, padx=10, pady=8)
        self.v_text = tk.Text(holder, wrap="none", font=("Consolas", 9))
        vs = ttk.Scrollbar(holder, orient="vertical", command=self.v_text.yview)
        hs = ttk.Scrollbar(holder, orient="horizontal", command=self.v_text.xview)
        self.v_text.configure(yscrollcommand=vs.set, xscrollcommand=hs.set)
        self.v_text.grid(row=0, column=0, sticky="nsew")
        vs.grid(row=0, column=1, sticky="ns")
        hs.grid(row=1, column=0, sticky="ew")
        holder.rowconfigure(0, weight=1)
        holder.columnconfigure(0, weight=1)
        self._vetune = None
        self._vetune_reader = None

    def _fill_maps(self) -> None:
        if not self.v_xdf.path:
            messagebox.showwarning(t("No XDF"), t("Choose the XDF file first."))
            return
        xdf = load_xdf_cached(self.v_xdf.path)
        map_names = [i.title for i in xdf.readable_items(include_axes=False)
                     if i.rows > 1 and i.cols > 1]
        preferred = [n for n in map_names if "_ve" in n or "maf_tab" in n or "_map_" in n]
        self.v_map_box["values"] = preferred + [n for n in map_names if n not in preferred]
        if preferred and not self.v_map.get():
            self.v_map.set(preferred[0])
        self.set_status(t("2D maps found: {n}", n=len(map_names)))

    def _read_log_or_warn(self):
        from . import vetune

        if not self.v_log.path:
            messagebox.showwarning(t("No log"), t("Choose the CSV log file."))
            return None
        try:
            return vetune.read_log(self.v_log.path)
        except vetune.LogError as exc:
            messagebox.showerror(t("The log cannot be read"), str(exc))
            return None

    def _show_log_columns(self) -> None:
        from . import vetune

        payload = self._read_log_or_warn()
        if not payload:
            return
        headers, rows = payload
        guessed = vetune.guess_columns(headers)
        lines = [t("Columns: {cols}, rows: {rows}", cols=len(headers), rows=len(rows)), ""]
        for name in headers:
            roles = [role for role, value in guessed.items() if value == name]
            lines.append(f"  {name}" + ("   <- " + ", ".join(roles) if roles else ""))
        TextWindow(self, t("Log columns"), "\n".join(lines))

    def _do_vetune(self) -> None:
        from . import vetune

        if not (self.v_xdf.path and self.v_bin.path and self.v_log.path):
            messagebox.showwarning(t("Files missing"),
                                   t("The XDF, the firmware and the log are needed."))
            return
        if not self.v_map.get():
            messagebox.showwarning(t("No map chosen"),
                                   t("Press \"Find maps\" and choose a map."))
            return
        for row in (self.v_xdf, self.v_bin, self.v_log):
            row.remember()
        save_settings(self.settings)

        xdf_path, bin_path, log_path = self.v_xdf.path, self.v_bin.path, self.v_log.path
        map_name = self.v_map.get()
        mode = self.v_mode.get()
        target = _as_float(self.v_target.get(), 1.0)
        min_samples = int(_as_float(self.v_min.get(), 8))
        max_step = _as_float(self.v_step.get(), 25.0) / 100.0
        delay = int(_as_float(self.v_delay.get(), 0))

        def work():
            xdf = load_xdf_cached(xdf_path)
            item = xdf.by_title(map_name)
            if item is None:
                raise ValueError(t("Map \"{name}\" not found in the XDF", name=map_name))
            reader = Reader(xdf, BinFile(bin_path))
            headers, rows = vetune.read_log(log_path)
            guessed = vetune.guess_columns(headers)
            missing = [r for r in ("rpm", "load", "lambda") if not guessed.get(r)]
            if missing:
                raise ValueError(
                    t("These columns were not found in the log: {cols}. Press \"Log columns\" "
                      "to see what is there.", cols=", ".join(missing))
                )
            columns = vetune.LogColumns(
                rpm=guessed["rpm"], load=guessed["load"], lam=guessed["lambda"],
                target=guessed.get("target"), trim=guessed.get("trim"),
                coolant=guessed.get("coolant"),
            )
            result = vetune.analyse(
                reader, item, rows, columns, mode=mode, target_lambda=target,
                min_samples=min_samples, max_step=max_step, delay_samples=delay,
            )
            return reader, result

        self.run_async(work, self._show_vetune, t("Calculating the correction…"))

    def _show_vetune(self, payload) -> None:
        reader, result = payload
        self._vetune = result
        self._vetune_reader = reader
        self.v_text.delete("1.0", "end")
        self.v_text.insert("1.0", report.vetune_console_report(reader, result))
        warn = "   ".join(result.notes[:2])
        self.v_summary.config(
            text=t("Used {used} of {total} samples · coverage {pct:.0f}% · {n} cells changed",
                   used=result.used_samples, total=result.total_samples,
                   pct=result.coverage * 100, n=result.touched_cells)
                 + (f"\n{warn}" if warn else "")
        )
        self.set_status(t("Correction calculated"))

    def _save_vetune_html(self) -> None:
        if not self._vetune:
            messagebox.showinfo(t("No data"), t("Calculate the correction first."))
            return
        path = self._ask_save(t("ms43_ve_tuning") + ".html", "html")
        if not path:
            return
        report.write_vetune_html(self._vetune_reader, self._vetune, path,
                                 log_name=os.path.basename(self.v_log.path))
        if messagebox.askyesno(t("Done"), t("Saved:\n{path}\n\nOpen it?", path=path)):
            os.startfile(path)  # noqa: S606

    def _write_vetune(self) -> None:
        from . import vetune

        if not self._vetune:
            messagebox.showinfo(t("No data"), t("Calculate the correction first."))
            return
        if not messagebox.askokcancel(
            t("Confirmation"),
            t("A NEW firmware file with the changed map will be created.\n"
              "The source file is not changed.\n\n"
              "Cells to change: {n}\n\n"
              "IMPORTANT: checksums are not recalculated — do it in TunerPro.",
              n=self._vetune.touched_cells),
            icon="warning",
        ):
            return
        base = os.path.splitext(os.path.basename(self.v_bin.path))[0]
        path = self._ask_save(f"{base}_ve.bin", "bin")
        if not path:
            return
        if os.path.abspath(path) == os.path.abspath(self.v_bin.path):
            messagebox.showerror(t("Refused"), t("Cannot write over the source firmware."))
            return
        info = vetune.write_tuned_bin(self._vetune_reader, self._vetune.item,
                                      self._vetune, path)
        messagebox.showinfo(
            t("Done"),
            t("Cells written: {n}\nFile: {path}\n\nChecksums were NOT recalculated.",
              n=info["cells"], path=path)
        )

    # ==================================================================
    # Tab 7: MS4X Wiki reference
    # ==================================================================
    def _build_wiki_tab(self) -> None:
        tab = ttk.Frame(self.notebook)
        self.notebook.add(tab, text="  " + t("Reference") + "  ")

        top = ttk.Frame(tab, padding=(10, 8))
        top.pack(fill="x")
        self.w_status = ttk.Label(top, text="", foreground="#555")
        self.w_status.pack(anchor="w")

        row = ttk.Frame(tab, padding=(10, 4))
        row.pack(fill="x")
        ttk.Label(row, text=t("Search:")).pack(side="left")
        self.w_query = tk.StringVar()
        entry = ttk.Entry(row, textvariable=self.w_query, width=44)
        entry.pack(side="left", padx=6)
        entry.bind("<Return>", lambda e: self._wiki_search())
        ttk.Button(row, text=t("Find"), command=self._wiki_search).pack(side="left")
        ttk.Button(row, text=t("All warnings"),
                   command=self._wiki_cautions).pack(side="left", padx=8)
        ttk.Button(row, text=t("Update from site"),
                   command=self._wiki_download).pack(side="left")
        ttk.Label(row, text=t("works offline; updating needs access to ms4x.net"),
                  foreground="#777").pack(side="left", padx=10)

        panes = ttk.PanedWindow(tab, orient="horizontal")
        panes.pack(fill="both", expand=True, padx=10, pady=8)
        left = ttk.Frame(panes)
        right = ttk.Frame(panes)
        panes.add(left, weight=1)
        panes.add(right, weight=3)

        self.w_list = tk.Listbox(left, font=("", 9))
        self.w_list.pack(fill="both", expand=True)
        self.w_list.bind("<<ListboxSelect>>", lambda e: self._wiki_select())

        self.w_text = tk.Text(right, wrap="word", font=("", 10), padx=8, pady=6)
        vs = ttk.Scrollbar(right, orient="vertical", command=self.w_text.yview)
        self.w_text.configure(yscrollcommand=vs.set)
        self.w_text.pack(side="left", fill="both", expand=True)
        vs.pack(side="right", fill="y")
        self.w_text.tag_configure("head", font=("", 11, "bold"), foreground="#0b5cad")
        self.w_text.tag_configure("warn", background="#ffe9e2")
        self.w_text.tag_configure("url", foreground="#0b5cad")
        self.w_text.tag_configure("dim", foreground="#999")

        self._wiki_sections: List = []
        self._wiki_refresh_status()
        self._wiki_show_pages()

    def _wiki_refresh_status(self) -> None:
        from . import wikicache

        if not wikicache.available():
            self.w_status.config(
                text=t("There is no local copy of the reference. Press \"Update from site\" "
                       "(needs access to ms4x.net).")
            )
            return
        info = wikicache.meta()
        self.w_status.config(
            text=t("MS4X Wiki, snapshot of {date} · pages {pages} · parameters linked {params} · "
                   "source {source}", date=info.get("fetched", "?"),
                   pages=len(wikicache.load()), params=len(wikicache.index_parameters()),
                   source=info.get("source"))
        )

    def _wiki_show_pages(self) -> None:
        from . import wikicache

        self.w_list.delete(0, "end")
        self._wiki_sections = []
        for page in wikicache.load():
            for section in page.sections:
                self._wiki_sections.append(section)
                self.w_list.insert("end", f"{page.title} / {section.heading}")

    def _wiki_search(self) -> None:
        from . import wikicache

        query = self.w_query.get().strip()
        if not query:
            self._wiki_show_pages()
            return
        sections = wikicache.search(query, limit=200)
        self.w_list.delete(0, "end")
        self._wiki_sections = sections
        for section in sections:
            self.w_list.insert("end", f"{section.page} / {section.heading}")
        self.set_status(t("Sections found: {n}", n=len(sections)))

    def _wiki_cautions(self) -> None:
        from . import wikicache

        sections = wikicache.cautions()
        self.w_list.delete(0, "end")
        self._wiki_sections = sections
        for section in sections:
            self.w_list.insert("end", f"⚠ {section.page} / {section.heading}")
        self.set_status(
            t("Sections with warnings: {n}, lines: {lines}", n=len(sections),
              lines=sum(len(s.caution_lines) for s in sections))
        )

    def _wiki_select(self) -> None:
        selection = self.w_list.curselection()
        if not selection or selection[0] >= len(self._wiki_sections):
            return
        from . import wikitrans

        section = self._wiki_sections[selection[0]]
        self.w_text.delete("1.0", "end")
        self.w_text.insert("end", f"{section.page} / {section.heading}\n\n", "head")
        cautions = set(section.caution_lines)
        translated = False
        for line in section.text.split("\n"):
            if not line.strip():
                continue
            tag = "warn" if line.strip() in cautions else ""
            shown = wikitrans.translate_line(line.strip())
            translated = translated or shown != line.strip()
            self.w_text.insert("end", shown + "\n\n", tag)
        if translated:
            self.w_text.insert("end", t("original (English):") + "\n\n", "dim")
            for line in section.text.split("\n"):
                if line.strip():
                    self.w_text.insert("end", line.strip() + "\n\n", "dim")
        self.w_text.insert("end", section.url + "\n", "url")

    def _wiki_download(self) -> None:
        from . import wikicache

        if not messagebox.askokcancel(
            t("Updating the reference"),
            t("The program will download pages from ms4x.net into the local copy.\n"
              "It needs access to the site.\n\nContinue?"),
        ):
            return

        def work():
            return wikicache.download()

        def done(result):
            wikicache.load(force=True)
            self._wiki_refresh_status()
            self._wiki_show_pages()
            errors = "\n".join(f"{n}: {e[:60]}" for n, e in result["errors"])
            messagebox.showinfo(
                t("Done"),
                t("Pages downloaded: {n}\nCache: {path}", n=result["pages"], path=result["path"])
                + ("\n\n" + t("Failed:") + f"\n{errors}" if errors else "")
            )

        self.run_async(work, done, t("Downloading the reference…"))


def _as_float(text: str, default: float) -> float:
    try:
        return float(str(text).replace(",", "."))
    except (TypeError, ValueError):
        return default


def run() -> int:
    app = App()
    app.mainloop()
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(run())
