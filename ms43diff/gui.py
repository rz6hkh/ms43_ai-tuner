# -*- coding: utf-8 -*-
"""
Оконный интерфейс ms43diff (tkinter, без сторонних библиотек).

Пять вкладок:

  1. Сравнение          — два бина одной версии ПО по одному XDF
  2. Разные версии      — два бина разных версий, каждый со своим XDF
  3. Перенос настроек   — план переноса правок в другую версию ПО (без записи)
  4. Патчи              — какие патчи из patchlist применены
  5. Просмотр           — поиск параметра и его карта целиком

Пути к файлам выбираются в диалогах, никакой привязки к текущей папке нет.
Последние использованные файлы запоминаются в
%APPDATA%\\ms43diff\\settings.json, чтобы не тыкать их каждый раз заново.

Тяжёлые операции (разбор XDF на 3.5 МБ, сравнение) выполняются в отдельном
потоке, чтобы окно не подвисало.
"""

from __future__ import annotations

import json
import os
import queue
import sys
import threading
import traceback
from typing import Callable, Dict, List, Optional

import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from . import __version__, heatmap, report, ru
from .binfile import BinFile, Reader, format_number
from .compare import check_patches, compare_bins
from .crossdiff import (
    P_SAFE_BYTES,
    P_SAFE_NAME,
    P_WARN,
    build_port_plan,
    cross_compare,
)
from .xdf import XdfFile

APP_TITLE = f"ms43diff {__version__} — сравнение прошивок BMW MS43"

XDF_TYPES = [("Определения TunerPro", "*.xdf"), ("Все файлы", "*.*")]
BIN_TYPES = [("Прошивки", "*.bin"), ("Все файлы", "*.*")]


# ---------------------------------------------------------------------------
# Журнал ошибок
# ---------------------------------------------------------------------------
# Окно (windowed .exe) не показывает stderr, поэтому все ошибки — особенно при
# сохранении PDF — пишем в файл, который пользователь может прислать.


def log_path() -> str:
    base = os.environ.get("APPDATA") or os.path.expanduser("~")
    folder = os.path.join(base, "ms43diff")
    try:
        os.makedirs(folder, exist_ok=True)
    except OSError:
        folder = os.path.dirname(os.path.abspath(sys.argv[0]))
    return os.path.join(folder, "ms43diff.log")


def log_write(text: str) -> str:
    import datetime

    path = log_path()
    try:
        with open(path, "a", encoding="utf-8") as fh:
            fh.write(f"\n===== {datetime.datetime.now():%Y-%m-%d %H:%M:%S} =====\n")
            fh.write(text.rstrip() + "\n")
    except OSError:
        pass
    return path


def log_exc(where: str) -> str:
    """Записать текущее исключение в журнал. Вернуть путь к журналу."""
    return log_write(f"[{where}]\n" + traceback.format_exc())


# ---------------------------------------------------------------------------
# Настройки
# ---------------------------------------------------------------------------


def _settings_path() -> str:
    base = os.environ.get("APPDATA") or os.path.expanduser("~")
    folder = os.path.join(base, "ms43diff")
    os.makedirs(folder, exist_ok=True)
    return os.path.join(folder, "settings.json")


def load_settings() -> Dict[str, str]:
    try:
        with open(_settings_path(), "r", encoding="utf-8") as fh:
            data = json.load(fh)
            return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def save_settings(data: Dict[str, str]) -> None:
    try:
        with open(_settings_path(), "w", encoding="utf-8") as fh:
            json.dump(data, fh, ensure_ascii=False, indent=2)
    except OSError:
        pass


# ---------------------------------------------------------------------------
# Кэш разобранных XDF — парсинг 3.5 МБ занимает около секунды
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
# Мелкие виджеты
# ---------------------------------------------------------------------------


class FileRow(ttk.Frame):
    """Строка «подпись — путь — Обзор»."""

    def __init__(self, master, label: str, key: str, settings: Dict[str, str],
                 types=BIN_TYPES, hint: str = ""):
        super().__init__(master)
        self.key = key
        self.settings = settings
        self.types = types
        self.var = tk.StringVar(value=settings.get(key, ""))

        ttk.Label(self, text=label, width=22, anchor="w").grid(row=0, column=0, sticky="w")
        entry = ttk.Entry(self, textvariable=self.var)
        entry.grid(row=0, column=1, sticky="ew", padx=(0, 6))
        ttk.Button(self, text="Обзор…", width=10, command=self.browse).grid(row=0, column=2)
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
            title="Выберите файл", filetypes=self.types, initialdir=start or None
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
    """Таблица результатов с фильтром."""

    def __init__(self, master, columns: List[tuple], on_open: Optional[Callable] = None):
        super().__init__(master)
        self.on_open = on_open
        self._all_rows: List[tuple] = []

        top = ttk.Frame(self)
        top.pack(fill="x", pady=(0, 4))
        ttk.Label(top, text="Фильтр:").pack(side="left")
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

        # Treeview не даёт выделять текст в ячейках, поэтому копирование
        # вешаем сами: Ctrl+C — имя параметра (первый столбец), правый клик —
        # меню. Имя кладётся в системный буфер через clipboard_append.
        self.tree.bind("<Control-c>", lambda e: self._copy_name())
        self.tree.bind("<Control-C>", lambda e: self._copy_name())
        self.tree.bind("<Button-3>", self._context_menu)
        self._menu = tk.Menu(self, tearoff=0)
        self._menu.add_command(label="Копировать имя", command=self._copy_name)
        self._menu.add_command(label="Копировать строку (все столбцы)",
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
            text=f"показано {shown} из {total}" if shown != total else f"строк: {total}"
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
    """Окно с моноширинным текстом (карта, отчёт)."""

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
        ttk.Button(self, text="Закрыть", command=self.destroy).pack(pady=6)


def wiki_sections_for(title: str) -> List:
    """Разделы справочника про параметр (пусто, если кэша нет)."""
    try:
        from . import wikicache

        if not wikicache.available():
            return []
        return wikicache.guidance_for_map(title)
    except Exception:  # noqa: BLE001 - справочник не должен ломать окно
        return []


def fill_wiki_text(widget: tk.Text, title: str, header: str = "") -> int:
    """Вывести в текстовый виджет всё, что вики знает про параметр."""
    widget.configure(state="normal")
    widget.delete("1.0", "end")
    sections = wiki_sections_for(title)
    if header:
        widget.insert("end", header + "\n\n", "head")
    if not sections:
        widget.insert(
            "end",
            "В локальном справочнике про этот параметр ничего не нашлось.\n"
            "Если справочник ещё не скачан — вкладка «Справочник», "
            "кнопка «Обновить с сайта».\n",
        )
        widget.configure(state="disabled")
        return 0
    from . import wikicache, wikitrans

    meanings = wikicache.value_meanings(title)
    if meanings:
        widget.insert("end", "Что означают значения\n", "head")
        for key in sorted(meanings):
            widget.insert("end", f"  {key} — {wikitrans.translate_line(meanings[key])}\n")
        widget.insert("end", "\n")
    steps = wikicache.procedure_for(title)
    if steps:
        widget.insert("end", "После изменения нужно\n", "head")
        for step in steps:
            widget.insert("end", f"  • {wikitrans.translate_line(step)}\n", "warn")
        widget.insert("end", "\n")

    for section in sections:
        widget.insert("end", f"{section.page} / {section.heading}\n", "head")
        english = wikicache.focused_text(section, title)
        cautions = set(section.caution_lines)
        # русский текст — основной; оригинал показываем ниже, серым
        for line in wikitrans.translate_block(english).split("\n"):
            if line.strip():
                widget.insert("end", line.strip() + "\n")
        for warning in section.caution_lines[:4]:
            widget.insert("end", "⚠ " + wikitrans.translate_line(warning) + "\n", "warn")
        widget.insert("end", "\nоригинал (English):\n", "dim")
        for line in english.split("\n"):
            if line.strip():
                widget.insert("end", line.strip() + "\n", "dim")
        widget.insert("end", section.url + "\n\n", "url")
    widget.configure(state="disabled")
    return len(sections)


class WikiWindow(tk.Toplevel):
    """Что справочник пишет про конкретный параметр."""

    def __init__(self, master, title: str):
        super().__init__(master)
        self.title(f"Справочник — {title}")
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
        ttk.Button(self, text="Закрыть", command=self.destroy).pack(pady=6)


class MapWindow(tk.Toplevel):
    """Карта как тепловая таблица: цвет несёт смысл, цифры уточняют.

    Три режима: значения из A, значения из B и разница. Разница красится
    расходящейся шкалой с нейтральным нулём — так сразу видно, что тюнер
    поднял, а что опустил, без вглядывания в цифры.
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
        self.units = ru.unit_ru(item.value_units)

        info = ru.explain(item.title, item.description)
        head = ttk.Frame(self, padding=(10, 8))
        head.pack(fill="x")
        ttk.Label(head, text=item.title, font=("Consolas", 11, "bold")).pack(anchor="w")
        ttk.Label(head, text=info["name"], font=("", 10)).pack(anchor="w")
        if info["desc"]:
            ttk.Label(head, text=info["desc"], foreground="#555",
                      wraplength=1120, justify="left").pack(anchor="w")
        for key, label in (("note", "Что делает"), ("tune", "Как крутить")):
            if info[key]:
                ttk.Label(head, text=f"{label}: {info[key]}", foreground="#0b5cad",
                          wraplength=1120, justify="left").pack(anchor="w", pady=(2, 0))
        data = item.data
        if data is not None and data.address is not None:
            ttk.Label(
                head,
                text=(f"{item.shape_str} · адрес XDF 0x{data.address:X} · "
                      f"файл 0x{reader.file_offset(data.address):X} · "
                      f"{item.value_equation.describe_ru(self.units)}"),
                foreground="#777",
            ).pack(anchor="w", pady=(2, 0))

        bar = ttk.Frame(self, padding=(10, 4))
        bar.pack(fill="x")
        self.mode = tk.StringVar(value="delta" if self.after else "a")
        if self.after:
            for value, text in (("delta", "разница"), ("a", "значения A"), ("b", "значения B")):
                ttk.Radiobutton(bar, text=text, value=value, variable=self.mode,
                                command=self.draw).pack(side="left", padx=(0, 10))
        ttk.Button(bar, text="Текстом", command=self._show_text).pack(side="left", padx=6)
        ttk.Button(bar, text="Сохранить PDF…", command=self._save_pdf).pack(side="left")
        sections = wiki_sections_for(item.title)
        if sections:
            ttk.Button(bar, text=f"Справочник ({len(sections)})",
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
            caption = "изменение"
        else:
            stops = heatmap.legend_stops(low, high)
            caption = "значение"
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
                    f"было {self._fmt(a)} → стало {self._fmt(b)} "
                    f"({sign}{self._fmt(delta)}) {self.units}")
        self.hint.config(text=text)

    def _show_text(self) -> None:
        TextWindow(self, self.item.title,
                   report.render_table(self.reader, self.item, self.reader_b))

    def _show_wiki(self) -> None:
        WikiWindow(self, self.item.title)

    def _save_pdf(self) -> None:
        from .pdfreport import PdfUnavailable, write_map_pdf

        path = filedialog.asksaveasfilename(
            title="Сохранить карту в PDF", defaultextension=".pdf",
            initialfile=f"{self.item.title}.pdf",
            filetypes=[("PDF", "*.pdf")],
        )
        if not path:
            return
        try:
            write_map_pdf(self.reader, [self.item], path, self.reader_b)
        except PdfUnavailable as exc:
            messagebox.showerror("PDF недоступен", str(exc))
            return
        if messagebox.askyesno("Готово", f"Сохранено:\n{path}\n\nОткрыть?"):
            os.startfile(path)  # noqa: S606


class ChoiceDialog(tk.Toplevel):
    """Выбор соответствия параметра в целевой версии."""

    def __init__(self, master, title: str, candidates: List[tuple], all_titles: List[str]):
        super().__init__(master)
        self.title("Выбор соответствия")
        self.geometry("760x520")
        self.result: Optional[str] = None
        self.transient(master)
        self.grab_set()

        pad = ttk.Frame(self, padding=10)
        pad.pack(fill="both", expand=True)
        ttk.Label(pad, text=f"Параметр исходной версии:", foreground="#777").pack(anchor="w")
        ttk.Label(pad, text=title, font=("Consolas", 11, "bold")).pack(anchor="w", pady=(0, 8))
        ttk.Label(
            pad,
            text="Выберите, во что его перенести в целевой прошивке.\n"
                 "Сверху — похожие по имени и совпадающие по размеру карты.",
            justify="left",
        ).pack(anchor="w", pady=(0, 8))

        search_var = tk.StringVar()
        row = ttk.Frame(pad)
        row.pack(fill="x", pady=(0, 6))
        ttk.Label(row, text="Поиск:").pack(side="left")
        ttk.Entry(row, textvariable=search_var).pack(side="left", fill="x", expand=True, padx=6)

        self.listbox = tk.Listbox(pad, font=("Consolas", 10))
        self.listbox.pack(fill="both", expand=True)

        cand_titles = [t for t, _ in candidates]
        self._candidates = candidates
        self._all = all_titles

        def refill(*_):
            needle = search_var.get().lower().strip()
            self.listbox.delete(0, "end")
            self._items: List[str] = []
            for t, score in candidates:
                if needle and needle not in t.lower():
                    continue
                self.listbox.insert("end", f"★ {t}   (похожесть {score:.2f})")
                self._items.append(t)
            for t in all_titles:
                if t in cand_titles:
                    continue
                if needle and needle not in t.lower():
                    continue
                self.listbox.insert("end", f"   {t}")
                self._items.append(t)

        search_var.trace_add("write", refill)
        refill()

        buttons = ttk.Frame(pad)
        buttons.pack(fill="x", pady=(8, 0))
        ttk.Button(buttons, text="Выбрать", command=self._choose).pack(side="left")
        ttk.Button(buttons, text="Пропустить параметр",
                   command=self._skip).pack(side="left", padx=6)
        ttk.Button(buttons, text="Отмена", command=self.destroy).pack(side="right")
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


# ---------------------------------------------------------------------------
# Основное окно
# ---------------------------------------------------------------------------


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title(APP_TITLE)
        self.geometry("1280x820")
        self.minsize(1000, 620)
        self.settings = load_settings()
        self._queue: "queue.Queue" = queue.Queue()

        try:
            ttk.Style().theme_use("vista")
        except tk.TclError:
            pass

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
        self.status = ttk.Label(statusbar, text="Готово", anchor="w", padding=(10, 5))
        self.status.pack(side="left", fill="x", expand=True)
        ttk.Button(statusbar, text="Показать журнал", command=self._open_log).pack(
            side="right", padx=6, pady=2)

        log_write(f"[запуск] ms43diff-gui {__version__}, "
                  f"frozen={getattr(sys, 'frozen', False)}, python={sys.version.split()[0]}")
        self._poll_id = self.after(120, self._poll)
        self.protocol("WM_DELETE_WINDOW", self._on_close)

    def _open_log(self) -> None:
        path = log_path()
        if not os.path.isfile(path):
            log_write("[журнал] создан пустой файл по кнопке")
        try:
            os.startfile(path)  # noqa: S606
        except OSError:
            messagebox.showinfo("Журнал", f"Файл журнала:\n{path}")

    # ------------------------------------------------------------------
    def _on_close(self) -> None:
        save_settings(self.settings)
        self.destroy()

    def destroy(self) -> None:
        # снимаем отложенный вызов, иначе Tcl ругается на «invalid command name»
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
        """Выполнить долгую операцию в потоке, результат вернуть в UI-поток."""
        self.set_status(busy)
        self.config(cursor="watch")

        def worker():
            try:
                self._queue.put((done, work(), None))
            except Exception as exc:  # noqa: BLE001 - показываем пользователю
                self._queue.put((done, None, (exc, traceback.format_exc())))

        threading.Thread(target=worker, daemon=True).start()

    def _poll(self) -> None:
        try:
            while True:
                done, result, error = self._queue.get_nowait()
                self.config(cursor="")
                if error is not None:
                    exc, trace = error
                    self.set_status("Ошибка")
                    path = log_write("[фоновая операция]\n" + trace)
                    messagebox.showerror(
                        "Ошибка",
                        f"{exc}\n\nПодробности записаны в журнал:\n{path}",
                    )
                else:
                    done(result)
        except queue.Empty:
            pass
        self._poll_id = self.after(120, self._poll)

    def report_callback_exception(self, exc, val, tb):
        """Перехват любых ошибок в обработчиках tkinter (кнопки, события).

        В оконном .exe stderr не виден, поэтому пишем в журнал и показываем
        пользователю путь к нему — чтобы было что прислать.
        """
        text = "".join(traceback.format_exception(exc, val, tb))
        path = log_write("[интерфейс]\n" + text)
        try:
            messagebox.showerror(
                "Ошибка",
                f"{val}\n\nПодробности записаны в журнал:\n{path}",
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
            "html": [("HTML-страница", "*.html")],
            "csv": [("CSV для Excel", "*.csv")],
            "pdf": [("PDF-документ", "*.pdf")],
            "bin": [("Прошивка", "*.bin")],
        }[kind]
        start = self.settings.get("last_out_dir", "")
        path = filedialog.asksaveasfilename(
            title="Сохранить как", defaultextension=f".{kind}",
            initialfile=default, filetypes=types, initialdir=start or None
        )
        if path:
            self.settings["last_out_dir"] = os.path.dirname(path)
            save_settings(self.settings)
        return path

    # ==================================================================
    # Вкладка 1: сравнение одной версии
    # ==================================================================
    def _build_compare_tab(self) -> None:
        tab = ttk.Frame(self.notebook)
        self.notebook.add(tab, text="  Сравнение  ")

        box = self._section(tab, "Файлы (одна и та же версия ПО)")
        self.cmp_xdf = FileRow(box, "Описание XDF", "cmp_xdf", self.settings, XDF_TYPES)
        self.cmp_xdf.pack(fill="x", pady=3)
        self.cmp_a = FileRow(box, "Прошивка A (сток)", "cmp_a", self.settings)
        self.cmp_a.pack(fill="x", pady=3)
        self.cmp_b = FileRow(box, "Прошивка B (тюнинг)", "cmp_b", self.settings)
        self.cmp_b.pack(fill="x", pady=3)

        controls = ttk.Frame(tab, padding=(10, 8))
        controls.pack(fill="x")
        self.cmp_axes = tk.BooleanVar(value=False)
        self.cmp_cks = tk.BooleanVar(value=True)
        ttk.Checkbutton(controls, text="учитывать оси (ldp_*)",
                        variable=self.cmp_axes).pack(side="left")
        ttk.Checkbutton(controls, text="показывать контрольные суммы",
                        variable=self.cmp_cks).pack(side="left", padx=12)
        ttk.Button(controls, text="Сравнить", command=self._do_compare).pack(side="left", padx=12)
        ttk.Button(controls, text="Сохранить HTML",
                   command=lambda: self._save_report("html")).pack(side="left")
        ttk.Button(controls, text="Сохранить CSV",
                   command=lambda: self._save_report("csv")).pack(side="left", padx=6)
        ttk.Button(controls, text="Сохранить PDF",
                   command=lambda: self._save_report("pdf")).pack(side="left")
        ttk.Label(controls, text="двойной клик по строке — карта с подсветкой",
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
            [("param", "Параметр", 250), ("name", "Что это", 330),
             ("value", "Было → Стало", 230), ("units", "Ед.", 70),
             ("cells", "Ячеек", 70), ("cat", "Категория", 170),
             ("addr", "Адрес", 90)],
            on_open=self._open_compare_detail,
        )
        self.cmp_table.pack(fill="both", expand=True)
        self.cmp_table.tree.bind("<<TreeviewSelect>>", lambda e: self._compare_wiki())

        ttk.Label(bottom, text="Что это за параметр, что означают значения "
                               "и что пишет MS4X Wiki",
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
            messagebox.showwarning("Не хватает файлов",
                                   "Выберите XDF и обе прошивки.")
            return
        for row in (self.cmp_xdf, self.cmp_a, self.cmp_b):
            row.remember()
        save_settings(self.settings)
        # Значения переменных tkinter читаем ЗДЕСЬ: из рабочего потока к ним
        # обращаться нельзя — Tcl это не переживает.
        with_axes = self.cmp_axes.get()
        with_cks = self.cmp_cks.get()

        def work():
            xdf = load_xdf_cached(xdf_path)
            return compare_bins(
                xdf, BinFile(a), BinFile(b),
                include_axes=with_axes,
                include_checksums=with_cks,
            )

        self.run_async(work, self._show_compare, "Сравниваю…")

    def _show_compare(self, result) -> None:
        self._cmp_result = result
        rows, tags = [], []
        for change in result.changes:
            data = report.change_row(result.xdf, change)
            rows.append((data["title"], data["name_ru"], data["summary"],
                         data["units"], data["changed"], data["category"],
                         data["address"]))
            tags.append("ok" if change.max_pct > 0 else
                        "bad" if change.max_pct < 0 else "warn")
        self.cmp_table.set_rows(rows, tags)

        warn = ""
        for tag, reader in (("A", result.reader_a), ("B", result.reader_b)):
            message = reader.version_warning()
            if message:
                warn += f"   ВНИМАНИЕ ({tag}): {message}"
        self.cmp_summary.config(
            text=f"Изменено параметров: {result.changed_params} · "
                 f"совпало: {result.identical} · "
                 f"изменено байт: {result.total_bytes_changed} · "
                 f"блоков правок кода: {len(result.code_blocks)}{warn}"
        )
        self.set_status(f"Готово: {result.changed_params} изменений")

    def _compare_wiki(self) -> None:
        values = self.cmp_table.selected_values()
        if not values:
            return
        header = f"{values[0]} — {values[1]}\nбыло → стало: {values[2]} {values[3]}"
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
            messagebox.showinfo("Нет данных", "Сначала выполните сравнение.")
            return
        path = self._ask_save("ms43_otchet." + kind, kind)
        if not path:
            return
        log_write(f"[сохранение отчёта] формат={kind}, файл={path}")
        try:
            if kind == "html":
                report.write_html(self._cmp_result, path)
            elif kind == "pdf":
                from .pdfreport import PdfUnavailable, write_compare_pdf

                try:
                    write_compare_pdf(self._cmp_result, path)
                except PdfUnavailable as exc:
                    messagebox.showerror(
                        "PDF недоступен",
                        f"{exc}\n\nЖурнал: {log_write('[PDF недоступен] ' + str(exc))}")
                    return
            else:
                report.write_csv(self._cmp_result, path)
        except Exception as exc:  # noqa: BLE001 - показываем причину и пишем в журнал
            lp = log_exc(f"сохранение {kind}")
            messagebox.showerror(
                "Не удалось сохранить",
                f"{exc}\n\nПодробности записаны в журнал:\n{lp}")
            return
        if not os.path.isfile(path):
            lp = log_write(f"[сохранение {kind}] функция отработала, но файл не появился: {path}")
            messagebox.showerror("Файл не создан",
                                 f"Файл не появился: {path}\nЖурнал: {lp}")
            return
        self.set_status(f"Сохранено: {path}")
        log_write(f"[сохранение отчёта] успех, {os.path.getsize(path)} байт")
        if messagebox.askyesno("Готово", f"Отчёт сохранён:\n{path}\n\nОткрыть?"):
            os.startfile(path)  # noqa: S606 - файл создали только что сами

    # ==================================================================
    # Вкладка 2: разные версии
    # ==================================================================
    def _build_cross_tab(self) -> None:
        tab = ttk.Frame(self.notebook)
        self.notebook.add(tab, text="  Разные версии  ")

        note = ttk.Label(
            tab,
            text="Здесь у каждой прошивки свой XDF. Параметры сопоставляются по именам,\n"
                 "сравниваются физические величины, а не байты — у разных версий ПО\n"
                 "формулы пересчёта и адреса могут отличаться.",
            padding=(10, 8), foreground="#555", justify="left",
        )
        note.pack(fill="x")

        box = self._section(tab, "Прошивка A")
        self.x_xdf_a = FileRow(box, "XDF версии A", "x_xdf_a", self.settings, XDF_TYPES)
        self.x_xdf_a.pack(fill="x", pady=3)
        self.x_bin_a = FileRow(box, "Прошивка A", "x_bin_a", self.settings)
        self.x_bin_a.pack(fill="x", pady=3)

        box = self._section(tab, "Прошивка B")
        self.x_xdf_b = FileRow(box, "XDF версии B", "x_xdf_b", self.settings, XDF_TYPES)
        self.x_xdf_b.pack(fill="x", pady=3)
        self.x_bin_b = FileRow(box, "Прошивка B", "x_bin_b", self.settings)
        self.x_bin_b.pack(fill="x", pady=3)

        controls = ttk.Frame(tab, padding=(10, 8))
        controls.pack(fill="x")
        ttk.Button(controls, text="Сравнить", command=self._do_cross).pack(side="left")
        ttk.Button(controls, text="Сохранить HTML",
                   command=self._save_cross).pack(side="left", padx=8)
        self.cross_summary = ttk.Label(tab, text="", padding=(10, 0), foreground="#555")
        self.cross_summary.pack(fill="x")

        self.cross_table = ResultTable(
            tab,
            [("param", "Параметр", 250), ("status", "Статус", 110),
             ("name", "Что это", 320), ("value", "A → B", 220),
             ("units", "Ед.", 70), ("notes", "Замечания", 380)],
        )
        self.cross_table.pack(fill="both", expand=True, padx=10, pady=10)
        self._cross_result = None

    def _do_cross(self) -> None:
        paths = [self.x_xdf_a.path, self.x_bin_a.path,
                 self.x_xdf_b.path, self.x_bin_b.path]
        if not all(paths):
            messagebox.showwarning("Не хватает файлов",
                                   "Выберите оба XDF и обе прошивки.")
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

        self.run_async(work, self._show_cross, "Сравниваю разные версии…")

    def _show_cross(self, result) -> None:
        self._cross_result = result
        rows, tags = [], []
        for row in result.rows:
            item = row.item
            units = ru.unit_ru(item.value_units) if item else ""
            name = ru.explain(row.title, item.description if item else "")["name"]
            rows.append((row.title, row.status, name, row.summary(), units,
                         " | ".join(row.notes)))
            tags.append({"отличается": "warn", "нет в B": "bad",
                         "нет в A": "ok"}.get(row.status, ""))
        self.cross_table.set_rows(rows, tags)
        self.cross_summary.config(
            text=f"Отличается: {len(result.different)} · совпадает: {result.identical} · "
                 f"только в A: {len(result.only_a)} · только в B: {len(result.only_b)}"
        )
        self.set_status("Готово")

    def _save_cross(self) -> None:
        if not self._cross_result:
            messagebox.showinfo("Нет данных", "Сначала выполните сравнение.")
            return
        path = self._ask_save("ms43_versii.html", "html")
        if path:
            report.write_cross_html(self._cross_result, path)
            self.set_status(f"Сохранено: {path}")
            if messagebox.askyesno("Готово", f"Отчёт сохранён:\n{path}\n\nОткрыть?"):
                os.startfile(path)  # noqa: S606

    # ==================================================================
    # Вкладка 3: перенос настроек
    # ==================================================================
    def _build_port_tab(self) -> None:
        tab = ttk.Frame(self.notebook)
        self.notebook.add(tab, text="  Перенос настроек  ")

        ttk.Label(
            tab,
            text="Строит ПЛАН переноса ваших правок в прошивку другой версии ПО и "
                 "ничего не пишет.\n"
                 "Правки определяются как разница между стоком исходной версии и вашей "
                 "прошивкой.\n"
                 "«Безопасно» — совпадение по байтам (копировать 1:1) или по имени "
                 "(переносить величину руками).\n"
                 "Остальное под предупреждением. Все правки вносите руками в TunerPro.",
            padding=(10, 8), foreground="#a05000", justify="left",
        ).pack(fill="x")

        box = self._section(tab, "Исходная версия (откуда переносим)")
        self.p_xdf_src = FileRow(box, "XDF исходной версии", "p_xdf_src",
                                 self.settings, XDF_TYPES)
        self.p_xdf_src.pack(fill="x", pady=3)
        self.p_stock = FileRow(box, "Сток исходной версии", "p_stock", self.settings,
                               hint="эталон: относительно него ищутся ваши правки")
        self.p_stock.pack(fill="x", pady=3)
        self.p_tuned = FileRow(box, "Ваша прошивка", "p_tuned", self.settings)
        self.p_tuned.pack(fill="x", pady=3)

        box = self._section(tab, "Целевая версия (куда переносим)")
        self.p_xdf_dst = FileRow(box, "XDF целевой версии", "p_xdf_dst",
                                 self.settings, XDF_TYPES)
        self.p_xdf_dst.pack(fill="x", pady=3)
        self.p_target = FileRow(box, "Целевая прошивка", "p_target", self.settings)
        self.p_target.pack(fill="x", pady=3)

        controls = ttk.Frame(tab, padding=(10, 8))
        controls.pack(fill="x")
        ttk.Button(controls, text="Построить план",
                   command=self._do_port).pack(side="left")
        ttk.Button(controls, text="Сохранить отчёт HTML",
                   command=lambda: self._save_port("html")).pack(side="left", padx=8)
        ttk.Button(controls, text="Сохранить CSV",
                   command=lambda: self._save_port("csv")).pack(side="left")
        ttk.Label(controls, text="программа только показывает план; правите руками "
                                 "в TunerPro. Двойной клик по строке — подробности",
                  foreground="#777").pack(side="left", padx=10)

        self.port_summary = ttk.Label(tab, text="", padding=(10, 0), foreground="#555")
        self.port_summary.pack(fill="x")

        self.port_table = ResultTable(
            tab,
            [("param", "Параметр исходной", 240), ("status", "Статус", 210),
             ("dst", "Параметр целевой", 220), ("name", "Что это", 250),
             ("value", "Значения", 260),
             ("detail", "Чем совпало / что не так", 420)],
            on_open=self._show_port_detail,
        )
        self.port_table.pack(fill="both", expand=True, padx=10, pady=10)
        self._port_plan = None

    def _do_port(self) -> None:
        paths = [self.p_xdf_src.path, self.p_stock.path, self.p_tuned.path,
                 self.p_xdf_dst.path, self.p_target.path]
        if not all(paths):
            messagebox.showwarning(
                "Не хватает файлов",
                "Нужны: XDF исходной версии, её сток, ваша прошивка,\n"
                "XDF целевой версии и целевая прошивка."
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

        self.run_async(work, self._show_port, "Строю план переноса…")

    def _show_port(self, plan) -> None:
        self._port_plan = plan
        rows, tags = [], []
        for entry in plan.entries:
            item = entry.item_dst or entry.item_src
            units = ru.unit_ru(item.value_units) if item else ""
            name = ru.explain(entry.title, item.description if item else "")["name"]
            bits = entry.match_bits if entry.safe else entry.warn_bits
            rows.append((entry.title, entry.status, entry.dst_title or "—", name,
                         f"{entry.summary()} {units}".strip(), " | ".join(bits)))
            tags.append({P_SAFE_BYTES: "ok", P_SAFE_NAME: "ok",
                         P_WARN: "bad"}.get(entry.status, "bad"))
        self.port_table.set_rows(rows, tags)
        self.port_summary.config(
            text=f"Вы изменили: {len(plan.entries)} · "
                 f"безопасно по байтам: {len(plan.safe_bytes)} · "
                 f"безопасно по имени: {len(plan.safe_name)} · "
                 f"под предупреждением: {len(plan.warned)}"
        )
        self.set_status(f"План готов: {len(plan.safe)} безопасных, "
                        f"{len(plan.warned)} под предупреждением")

    def _show_port_detail(self, values) -> None:
        if not self._port_plan:
            return
        title = values[0]
        entry = next((e for e in self._port_plan.entries if e.title == title), None)
        if entry is None:
            return
        item = entry.item_dst or entry.item_src
        units = ru.unit_ru(item.value_units) if item else ""
        info = ru.explain(entry.title, item.description if item else "")
        lines = [
            f"{entry.title}",
            f"{info['name']}",
            "",
            f"Статус: {entry.status}",
            f"Ваше значение: {entry.summary()} {units}".rstrip(),
        ]
        if entry.dst_title and entry.dst_title != entry.title:
            lines.append(f"Имя в целевой версии: {entry.dst_title}")
        lines.append("")
        if entry.safe:
            lines.append("Чем совпало:")
            for b in entry.match_bits:
                lines.append(f"  • {b}")
            lines.append("")
            if entry.status == P_SAFE_BYTES:
                lines.append("Можно перенести один в один: впишите то же значение "
                             "в TunerPro в одноимённый параметр.")
            else:
                lines.append("Переносите ФИЗИЧЕСКУЮ величину (то, что показывает "
                             "TunerPro), а не сырые байты — формат в целевой версии "
                             "отличается.")
        else:
            lines.append("Что не так:")
            for b in entry.warn_bits:
                lines.append(f"  • {b}")
            lines.append("")
            lines.append("Автоматически такое не переносится — разбирайтесь вручную.")
        messagebox.showinfo(f"Перенос — {entry.title}", "\n".join(lines))

    def _save_port(self, kind: str) -> None:
        if not self._port_plan:
            messagebox.showinfo("Нет данных", "Сначала постройте план.")
            return
        path = self._ask_save("ms43_perenos." + kind, kind)
        if not path:
            return
        if kind == "html":
            report.write_port_html(self._port_plan, path)
        else:
            report.write_port_csv(self._port_plan, path)
        self.set_status(f"Сохранено: {path}")
        if messagebox.askyesno("Готово", f"Отчёт сохранён:\n{path}\n\nОткрыть?"):
            os.startfile(path)  # noqa: S606

    # ==================================================================
    # Вкладка 4: патчи
    # ==================================================================
    def _build_patch_tab(self) -> None:
        tab = ttk.Frame(self.notebook)
        self.notebook.add(tab, text="  Патчи  ")

        box = self._section(tab, "Файлы")
        self.pt_xdf = FileRow(box, "Patchlist XDF", "pt_xdf", self.settings, XDF_TYPES,
                              hint="например Siemens_MS43_MS430069_Community_Patchlist_*.xdf")
        self.pt_xdf.pack(fill="x", pady=3)
        self.pt_bin = FileRow(box, "Прошивка", "pt_bin", self.settings)
        self.pt_bin.pack(fill="x", pady=3)

        controls = ttk.Frame(tab, padding=(10, 8))
        controls.pack(fill="x")
        ttk.Button(controls, text="Проверить", command=self._do_patches).pack(side="left")
        self.patch_summary = ttk.Label(tab, text="", padding=(10, 0), foreground="#555")
        self.patch_summary.pack(fill="x")

        self.patch_table = ResultTable(
            tab,
            [("state", "Статус", 130), ("title", "Патч", 340),
             ("cat", "Категория", 240), ("desc", "Описание", 620)],
        )
        self.patch_table.pack(fill="both", expand=True, padx=10, pady=10)

    def _do_patches(self) -> None:
        xdf_path, bin_path = self.pt_xdf.path, self.pt_bin.path
        if not (xdf_path and bin_path):
            messagebox.showwarning("Не хватает файлов",
                                   "Выберите patchlist XDF и прошивку.")
            return
        self.pt_xdf.remember()
        self.pt_bin.remember()
        save_settings(self.settings)

        def work():
            patchlist = load_xdf_cached(xdf_path)
            if not patchlist.patches:
                raise ValueError(
                    "В этом XDF нет записей <XDFPATCH>. Нужен patchlist-файл, "
                    "а не обычное определение."
                )
            return patchlist, check_patches(patchlist, BinFile(bin_path))

        self.run_async(work, self._show_patches, "Проверяю патчи…")

    def _show_patches(self, payload) -> None:
        patchlist, statuses = payload
        rows, tags = [], []
        for status in statuses:
            names = [patchlist.category_name(c) for c in status.patch.categories]
            cat = ", ".join(ru.category_ru(n) for n in names) or "—"
            rows.append((status.state, status.patch.title, cat,
                         ru.description_ru(status.patch.description)))
            tags.append({"применён": "ok", "не применён": "",
                         "частично": "warn"}.get(status.state, "bad"))
        self.patch_table.set_rows(rows, tags)
        applied = sum(1 for s in statuses if s.state == "применён")
        self.patch_summary.config(text=f"Применено {applied} из {len(statuses)}")
        self.set_status("Готово")

    # ==================================================================
    # Вкладка 5: просмотр
    # ==================================================================
    def _build_browse_tab(self) -> None:
        tab = ttk.Frame(self.notebook)
        self.notebook.add(tab, text="  Просмотр  ")

        box = self._section(tab, "Файлы")
        self.br_xdf = FileRow(box, "Описание XDF", "br_xdf", self.settings, XDF_TYPES)
        self.br_xdf.pack(fill="x", pady=3)
        self.br_bin = FileRow(box, "Прошивка", "br_bin", self.settings)
        self.br_bin.pack(fill="x", pady=3)

        controls = ttk.Frame(tab, padding=(10, 8))
        controls.pack(fill="x")
        ttk.Label(controls, text="Искать:").pack(side="left")
        self.br_query = tk.StringVar()
        entry = ttk.Entry(controls, textvariable=self.br_query, width=40)
        entry.pack(side="left", padx=6)
        entry.bind("<Return>", lambda e: self._do_browse())
        ttk.Button(controls, text="Найти", command=self._do_browse).pack(side="left")
        ttk.Label(controls, text="можно по-русски: отсечка, детонация, лямбда…",
                  foreground="#777").pack(side="left", padx=10)

        panes = ttk.PanedWindow(tab, orient="vertical")
        panes.pack(fill="both", expand=True, padx=10, pady=10)
        top = ttk.Frame(panes)
        bottom = ttk.Frame(panes)
        panes.add(top, weight=3)
        panes.add(bottom, weight=2)

        self.browse_table = ResultTable(
            top,
            [("param", "Параметр", 260), ("name", "Что это", 380),
             ("shape", "Тип", 90), ("value", "Значение", 220),
             ("units", "Ед.", 70), ("cat", "Категория", 200),
             ("addr", "Адрес", 90)],
            on_open=self._open_browse_detail,
        )
        self.browse_table.pack(fill="both", expand=True)
        # выделили строку — сразу показываем, что про неё пишет вики:
        # ради этого всё и затевалось, чтобы не бегать на сайт
        self.browse_table.tree.bind("<<TreeviewSelect>>",
                                    lambda e: self._browse_wiki())

        ttk.Label(bottom, text="Справочник MS4X Wiki по выделенному параметру",
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
            messagebox.showwarning("Не хватает файлов", "Выберите XDF и прошивку.")
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
                info = ru.explain(item.title, item.description)
                haystack = " ".join(
                    [item.title, item.description, info["name"], info["decoded"],
                     info["desc"]]
                ).lower()
                if needle and needle not in haystack:
                    continue
                found.append((item, info, reader.summary(item)))
                if len(found) >= 2000:
                    break
            return reader, found

        self.run_async(work, self._show_browse, "Ищу…")

    def _show_browse(self, payload) -> None:
        reader, found = payload
        self._browse_reader = reader
        rows = []
        for item, info, summary in found:
            rows.append((
                item.title, info["name"], item.shape_str, summary or "",
                ru.unit_ru(item.value_units),
                report.item_categories_ru(reader.xdf, item),
                f"0x{item.address:X}" if item.address is not None else "",
            ))
        self.browse_table.set_rows(rows)
        self.set_status(f"Найдено: {len(rows)}  (двойной клик — показать карту)")

    def _browse_wiki(self) -> None:
        values = self.browse_table.selected_values()
        if not values:
            return
        title = values[0]
        header = f"{title} — {values[1]}"
        if values[3]:
            header += f"\nсейчас в прошивке: {values[3]} {values[4]}".rstrip()
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
    # Вкладка 6: откатка карты по логу ШЛЗ
    # ==================================================================
    def _build_vetune_tab(self) -> None:
        tab = ttk.Frame(self.notebook)
        self.notebook.add(tab, text="  Откатка по ШЛЗ  ")

        ttk.Label(
            tab,
            text="Считает поправку к карте наполнения по логу широкополосного зонда:\n"
                 "если смесь беднее заданной — воздуха было больше, чем думал блок.\n"
                 "Ячейки, куда попало мало точек, не трогаются. Пояснения и\n"
                 "предупреждения берутся из офлайн-копии MS4X Wiki.",
            padding=(10, 8), foreground="#555", justify="left",
        ).pack(fill="x")

        box = self._section(tab, "Файлы")
        self.v_xdf = FileRow(box, "Описание XDF", "v_xdf", self.settings, XDF_TYPES)
        self.v_xdf.pack(fill="x", pady=3)
        self.v_bin = FileRow(box, "Прошивка", "v_bin", self.settings)
        self.v_bin.pack(fill="x", pady=3)
        self.v_log = FileRow(box, "Лог (CSV)", "v_log", self.settings,
                             [("Логи", "*.csv;*.txt"), ("Все файлы", "*.*")],
                             hint="экспорт из TunerPro или файл вашего ШЛЗ")
        self.v_log.pack(fill="x", pady=3)

        box = self._section(tab, "Настройки")
        row = ttk.Frame(box)
        row.pack(fill="x", pady=3)
        ttk.Label(row, text="Карта", width=22, anchor="w").pack(side="left")
        self.v_map = tk.StringVar()
        self.v_map_box = ttk.Combobox(row, textvariable=self.v_map, width=48)
        self.v_map_box.pack(side="left", padx=(0, 6))
        ttk.Button(row, text="Найти карты", command=self._fill_maps).pack(side="left")

        row = ttk.Frame(box)
        row.pack(fill="x", pady=3)
        ttk.Label(row, text="Режим", width=22, anchor="w").pack(side="left")
        self.v_mode = tk.StringVar(value="lambda")
        ttk.Combobox(row, textvariable=self.v_mode, width=12, state="readonly",
                     values=("lambda", "trim", "both")).pack(side="left")
        ttk.Label(row, text="целевая лямбда").pack(side="left", padx=(16, 4))
        self.v_target = tk.StringVar(value="1.00")
        ttk.Entry(row, textvariable=self.v_target, width=7).pack(side="left")
        ttk.Label(row, text="мин. точек в ячейке").pack(side="left", padx=(16, 4))
        self.v_min = tk.StringVar(value="8")
        ttk.Entry(row, textvariable=self.v_min, width=6).pack(side="left")
        ttk.Label(row, text="макс. поправка, %").pack(side="left", padx=(16, 4))
        self.v_step = tk.StringVar(value="25")
        ttk.Entry(row, textvariable=self.v_step, width=6).pack(side="left")
        ttk.Label(row, text="задержка зонда").pack(side="left", padx=(16, 4))
        self.v_delay = tk.StringVar(value="0")
        ttk.Entry(row, textvariable=self.v_delay, width=5).pack(side="left")

        controls = ttk.Frame(tab, padding=(10, 8))
        controls.pack(fill="x")
        ttk.Button(controls, text="Столбцы лога",
                   command=self._show_log_columns).pack(side="left")
        ttk.Button(controls, text="Посчитать поправку",
                   command=self._do_vetune).pack(side="left", padx=8)
        ttk.Button(controls, text="Отчёт HTML",
                   command=self._save_vetune_html).pack(side="left")
        ttk.Button(controls, text="Записать новый .bin…",
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
            messagebox.showwarning("Нет XDF", "Сначала выберите файл XDF.")
            return
        xdf = load_xdf_cached(self.v_xdf.path)
        names = [i.title for i in xdf.readable_items(include_axes=False)
                 if i.rows > 1 and i.cols > 1]
        preferred = [n for n in names if "_ve" in n or "maf_tab" in n or "_map_" in n]
        self.v_map_box["values"] = preferred + [n for n in names if n not in preferred]
        if preferred and not self.v_map.get():
            self.v_map.set(preferred[0])
        self.set_status(f"Найдено двумерных карт: {len(names)}")

    def _read_log_or_warn(self):
        from . import vetune

        if not self.v_log.path:
            messagebox.showwarning("Нет лога", "Выберите CSV-файл лога.")
            return None
        try:
            return vetune.read_log(self.v_log.path)
        except vetune.LogError as exc:
            messagebox.showerror("Лог не читается", str(exc))
            return None

    def _show_log_columns(self) -> None:
        from . import vetune

        payload = self._read_log_or_warn()
        if not payload:
            return
        headers, rows = payload
        guessed = vetune.guess_columns(headers)
        lines = [f"Столбцов: {len(headers)}, строк: {len(rows)}", ""]
        for name in headers:
            roles = [role for role, value in guessed.items() if value == name]
            lines.append(f"  {name}" + ("   <- " + ", ".join(roles) if roles else ""))
        TextWindow(self, "Столбцы лога", "\n".join(lines))

    def _do_vetune(self) -> None:
        from . import vetune

        if not (self.v_xdf.path and self.v_bin.path and self.v_log.path):
            messagebox.showwarning("Не хватает файлов",
                                   "Нужны XDF, прошивка и лог.")
            return
        if not self.v_map.get():
            messagebox.showwarning("Не выбрана карта",
                                   "Нажмите «Найти карты» и выберите карту.")
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
                raise ValueError(f"Карта «{map_name}» не найдена в XDF")
            reader = Reader(xdf, BinFile(bin_path))
            headers, rows = vetune.read_log(log_path)
            guessed = vetune.guess_columns(headers)
            missing = [r for r in ("rpm", "load", "lambda") if not guessed.get(r)]
            if missing:
                raise ValueError(
                    "В логе не нашлись столбцы: " + ", ".join(missing)
                    + ". Нажмите «Столбцы лога», чтобы посмотреть, что там есть."
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

        self.run_async(work, self._show_vetune, "Считаю поправку…")

    def _show_vetune(self, payload) -> None:
        reader, result = payload
        self._vetune = result
        self._vetune_reader = reader
        self.v_text.delete("1.0", "end")
        self.v_text.insert("1.0", report.vetune_console_report(reader, result))
        warn = "   ".join(result.notes[:2])
        self.v_summary.config(
            text=f"Использовано {result.used_samples} из {result.total_samples} точек · "
                 f"покрытие {result.coverage * 100:.0f}% · "
                 f"изменено {result.touched_cells} ячеек"
                 + (f"\n{warn}" if warn else "")
        )
        self.set_status("Поправка посчитана")

    def _save_vetune_html(self) -> None:
        if not self._vetune:
            messagebox.showinfo("Нет данных", "Сначала посчитайте поправку.")
            return
        path = self._ask_save("ms43_otkatka.html", "html")
        if not path:
            return
        report.write_vetune_html(self._vetune_reader, self._vetune, path,
                                 log_name=os.path.basename(self.v_log.path))
        if messagebox.askyesno("Готово", f"Сохранено:\n{path}\n\nОткрыть?"):
            os.startfile(path)  # noqa: S606

    def _write_vetune(self) -> None:
        from . import vetune

        if not self._vetune:
            messagebox.showinfo("Нет данных", "Сначала посчитайте поправку.")
            return
        if not messagebox.askokcancel(
            "Подтверждение",
            f"Будет создан НОВЫЙ файл прошивки с изменённой картой.\n"
            f"Исходный файл не меняется.\n\n"
            f"Ячеек к изменению: {self._vetune.touched_cells}\n\n"
            f"ВАЖНО: контрольные суммы не пересчитываются — сделайте это в TunerPro.",
            icon="warning",
        ):
            return
        base = os.path.splitext(os.path.basename(self.v_bin.path))[0]
        path = self._ask_save(f"{base}_ve.bin", "bin")
        if not path:
            return
        if os.path.abspath(path) == os.path.abspath(self.v_bin.path):
            messagebox.showerror("Отказ", "Нельзя писать поверх исходной прошивки.")
            return
        info = vetune.write_tuned_bin(self._vetune_reader, self._vetune.item,
                                      self._vetune, path)
        messagebox.showinfo(
            "Готово",
            f"Записано ячеек: {info['cells']}\nФайл: {path}\n\n"
            f"Контрольные суммы НЕ пересчитаны."
        )

    # ==================================================================
    # Вкладка 7: справочник MS4X Wiki
    # ==================================================================
    def _build_wiki_tab(self) -> None:
        from . import wikicache

        tab = ttk.Frame(self.notebook)
        self.notebook.add(tab, text="  Справочник  ")

        top = ttk.Frame(tab, padding=(10, 8))
        top.pack(fill="x")
        self.w_status = ttk.Label(top, text="", foreground="#555")
        self.w_status.pack(anchor="w")

        row = ttk.Frame(tab, padding=(10, 4))
        row.pack(fill="x")
        ttk.Label(row, text="Поиск:").pack(side="left")
        self.w_query = tk.StringVar()
        entry = ttk.Entry(row, textvariable=self.w_query, width=44)
        entry.pack(side="left", padx=6)
        entry.bind("<Return>", lambda e: self._wiki_search())
        ttk.Button(row, text="Найти", command=self._wiki_search).pack(side="left")
        ttk.Button(row, text="Все предупреждения",
                   command=self._wiki_cautions).pack(side="left", padx=8)
        ttk.Button(row, text="Обновить с сайта",
                   command=self._wiki_download).pack(side="left")
        ttk.Label(row, text="работает без интернета; обновление требует доступа к ms4x.net",
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
                text="Локальной копии справочника нет. Нажмите «Обновить с сайта» "
                     "(нужен доступ к ms4x.net, возможно через VPN)."
            )
            return
        info = wikicache.meta()
        self.w_status.config(
            text=f"MS4X Wiki, снимок от {info.get('fetched', '?')} · "
                 f"страниц {len(wikicache.load())} · "
                 f"параметров связано {len(wikicache.index_parameters())} · "
                 f"источник {info.get('source')}"
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
        self.set_status(f"Найдено разделов: {len(sections)}")

    def _wiki_cautions(self) -> None:
        from . import wikicache

        sections = wikicache.cautions()
        self.w_list.delete(0, "end")
        self._wiki_sections = sections
        for section in sections:
            self.w_list.insert("end", f"⚠ {section.page} / {section.heading}")
        self.set_status(
            f"Разделов с предупреждениями: {len(sections)}, "
            f"строк: {sum(len(s.caution_lines) for s in sections)}"
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
        for line in section.text.split("\n"):
            if not line.strip():
                continue
            tag = "warn" if line.strip() in cautions else ""
            self.w_text.insert("end", wikitrans.translate_line(line.strip()) + "\n\n", tag)
        self.w_text.insert("end", "оригинал (English):\n\n", "dim")
        for line in section.text.split("\n"):
            if line.strip():
                self.w_text.insert("end", line.strip() + "\n\n", "dim")
        self.w_text.insert("end", section.url + "\n", "url")

    def _wiki_download(self) -> None:
        from . import wikicache

        if not messagebox.askokcancel(
            "Обновление справочника",
            "Программа скачает страницы с ms4x.net в локальную копию.\n"
            "Нужен доступ к сайту (у многих — только через VPN).\n\nПродолжить?",
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
                "Готово",
                f"Загружено страниц: {result['pages']}\n"
                f"Кэш: {result['path']}"
                + (f"\n\nНе удалось:\n{errors}" if errors else "")
            )

        self.run_async(work, done, "Качаю справочник…")


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
