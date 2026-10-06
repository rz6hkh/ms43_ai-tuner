# -*- coding: utf-8 -*-
"""
Local HTTP server behind the web interface.

Only 127.0.0.1 is bound, on a free port. Every /api call must carry the random
session token (header X-Token) and a Host header pointing at that address, so
other web pages open in the same browser cannot talk to the program.

The page (static/) is plain HTML/CSS/JS. It asks for data with POST /api/<name>
and JSON bodies; everything heavy (parsing, comparing, reports) is done here
by the same code the CLI and the reports use.
"""

from __future__ import annotations

import json
import os
import re
import secrets
import sys
import threading
import time
import traceback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Callable, Dict, List, Optional

from .. import __version__, heatmap, i18n, names, report
from ..applog import log_write
from ..binfile import BinFile, Reader, format_number
from ..compare import CompareResult, compare_bins
from ..i18n import get_lang, set_lang, t
from ..xdf import OUT_TEXT, XdfFile
from .dialogs import DIALOGS

STATIC = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")
_CONTENT_TYPES = {".html": "text/html; charset=utf-8", ".css": "text/css; charset=utf-8",
                  ".js": "application/javascript; charset=utf-8", ".svg": "image/svg+xml"}

# project roles -> settings keys (and the old window's keys used as a fallback)
ROLES = {
    "xdf": ("proj_xdf", "cmp_xdf"),
    "bin_a": ("proj_bin_a", "cmp_a"),
    "bin_b": ("proj_bin_b", "cmp_b"),
    "xdf2": ("proj_xdf2", "x_xdf_b"),
    "bin2": ("proj_bin2", "x_bin_b"),
    "patchlist": ("proj_patchlist", "pt_xdf"),
    "velog": ("proj_velog", "v_log"),
}
XDF_ROLES = {"xdf", "xdf2", "patchlist"}
BIN_ROLES = ("bin_a", "bin_b", "bin2")


class ApiError(Exception):
    """A problem to show to the user as is (no traceback)."""


# ---------------------------------------------------------------------------
# State
# ---------------------------------------------------------------------------

class State:
    def __init__(self) -> None:
        self.settings = i18n.load_settings()
        self.paths: Dict[str, str] = {}
        for role, (key, old) in ROLES.items():
            path = self.settings.get(key) or self.settings.get(old) or ""
            self.paths[role] = path if path and os.path.isfile(path) else ""
        self._xdf_cache: Dict[str, tuple] = {}
        self.compare: Optional[CompareResult] = None
        self.lock = threading.Lock()
        self._ai = None

    @property
    def ai(self):
        if self._ai is None:
            from .ai import AiManager

            self._ai = AiManager(self)
        return self._ai

    def reader(self, role: str) -> Reader:
        """A Reader for a project firmware with the matching XDF (cached)."""
        if role not in BIN_ROLES:
            raise ApiError(f"unknown role {role}")
        xdf_role = "xdf2" if role == "bin2" else "xdf"
        xdf_path, bin_path = self.paths.get(xdf_role), self.paths.get(role)
        if not (xdf_path and bin_path):
            raise ApiError(t("Choose the XDF and the firmware in the project first."))
        key = (xdf_path, bin_path, os.path.getmtime(xdf_path), os.path.getmtime(bin_path))
        cache = self.__dict__.setdefault("_readers", {})
        if cache.get(role, (None,))[0] != key:
            cache[role] = (key, Reader(self.xdf(xdf_path), BinFile(bin_path)))
        return cache[role][1]

    def save(self) -> None:
        values = {ROLES[role][0]: path for role, path in self.paths.items()}
        self.settings.update(values)
        i18n.save_settings(**values)

    def xdf(self, path: str) -> XdfFile:
        stamp = os.path.getmtime(path)
        cached = self._xdf_cache.get(path)
        if cached and cached[0] == stamp:
            return cached[1]
        parsed = XdfFile(path)
        self._xdf_cache[path] = (stamp, parsed)
        return parsed

    def set_path(self, role: str, path: str) -> None:
        if role not in ROLES:
            raise ApiError(f"unknown role {role}")
        self.paths[role] = path
        if role in ("xdf", "bin_a", "bin_b"):
            self.compare = None
        self.save()


def _xdf_for(state: State, role: str) -> Optional[XdfFile]:
    xdf_role = "xdf2" if role == "bin2" else "xdf"
    path = state.paths.get(xdf_role)
    if path and os.path.isfile(path):
        try:
            return state.xdf(path)
        except Exception:  # noqa: BLE001 - shown on the XDF card instead
            return None
    return None


def file_info(state: State, role: str) -> Dict[str, Any]:
    path = state.paths.get(role, "")
    info: Dict[str, Any] = {"role": role, "path": path, "name": os.path.basename(path)}
    if not path:
        return info
    if not os.path.isfile(path):
        info["error"] = t("File not found")
        return info
    try:
        if role == "velog":
            info["meta"] = f"{max(1, os.path.getsize(path) // 1024)} {t('KB')}"
            return info
        if role in XDF_ROLES:
            xdf = state.xdf(path)
            info["tag"] = xdf.title
            if role == "patchlist":
                info["meta"] = t("{n} patches", n=len(xdf.patches))
                if not xdf.patches:
                    info["warning"] = t("This XDF has no <XDFPATCH> entries. A patchlist file is "
                                        "needed, not a regular definition.")
                return info
            info["meta"] = t("{n} parameters · {c} categories",
                             n=sum(1 for _ in xdf.readable_items()), c=len(xdf.categories))
            return info
        binf = BinFile(path)
        info["meta"] = f"{binf.size_kb} {t('KB')}"
        xdf = _xdf_for(state, role)
        if xdf is not None:
            reader = Reader(xdf, binf)
            info["tag"] = reader.firmware_id() or "?"
            info["meta"] += " · " + t("offset {label}", label=reader.offset.label)
            warning = reader.version_warning()
            if warning:
                info["warning"] = warning
            else:
                info["ok"] = True
        else:
            info["tag"] = _header_id(binf)
    except Exception as exc:  # noqa: BLE001 - shown on the card
        info["error"] = str(exc)
    return info


def _header_id(binf: BinFile) -> str:
    text = "".join(chr(b) if 32 <= b < 127 else " " for b in binf.data[-0x10000:][:0x80])
    match = re.search(r"([0-9A-Z]{6})\.DAT", text)
    return match.group(1) if match else ""


# ---------------------------------------------------------------------------
# Compare
# ---------------------------------------------------------------------------

def _range_text(values: List[float], dec: int, otype: int) -> str:
    if not values:
        return "—"
    lo, hi = min(values), max(values)
    if lo == hi:
        return format_number(lo, dec, otype)
    return f"{format_number(lo, dec, otype)}…{format_number(hi, dec, otype)}"


def _signed(value: float, dec: int, otype: int) -> str:
    text = format_number(value, dec, otype)
    return ("+" + text) if value > 0 else text.replace("-", "−")


def change_json(result: CompareResult, change) -> Dict[str, Any]:
    item = change.item
    dec, otype = item.value_decimals, item.value_output_type
    units = names.unit(item.value_units)
    info = names.explain(item.title, item.description)
    is_text = change.text_a is not None or change.text_b is not None
    if is_text:
        a, b, delta, direction = change.text_a or "", change.text_b or "", t("text"), "text"
    else:
        a = _range_text(change.vals_a, dec, otype)
        b = _range_text(change.vals_b, dec, otype)
        lo, hi = change.delta_min, change.delta_max
        if lo == hi:
            delta = _signed(lo, dec, otype)
        else:
            delta = f"{_signed(lo, dec, otype)}…{_signed(hi, dec, otype)}"
        if units:
            delta += f" {units}"
        direction = "up" if abs(hi) >= abs(lo) and hi > 0 else ("down" if lo < 0 else "up")
    kind = t("Constant") if item.cell_count == 1 else t("Map {shape}", shape=item.shape_str)
    return {
        "title": item.title,
        "name": info["name"],
        "desc": info["desc"] if info["desc"] != info["name"] else "",
        "kind": kind,
        "a": a, "b": b, "units": units, "delta": delta, "dir": direction,
        "cells": (t("{changed} of {total} cells changed", changed=change.changed_cells,
                    total=change.total_cells) if change.total_cells > 1 else ""),
        "has_map": item.cell_count > 1 and item.value_output_type != OUT_TEXT,
        "address": f"0x{item.address:X}" if item.address is not None else "",
    }


def compare_json(state: State) -> Dict[str, Any]:
    result = state.compare
    if result is None:
        raise ApiError(t("Run the comparison first."))
    groups: Dict[str, List] = {}
    for change in result.changes:
        groups.setdefault(report.item_categories(result.xdf, change.item), []).append(change)
    categories = [
        {"name": cat, "items": [change_json(result, c) for c in groups[cat]]}
        for cat in sorted(groups, key=lambda c: (-len(groups[c]), c))
    ]
    warnings = []
    if result.size_mismatch:
        warnings.append(t("WARNING: the files differ in size, the smaller one is compared."))
    for tag, reader in (("A", result.reader_a), ("B", result.reader_b)):
        message = reader.version_warning()
        if message:
            warnings.append(t("WARNING ({tag}): {text}", tag=tag, text=message))
    return {
        "a": result.bin_a.name, "b": result.bin_b.name,
        "xdf": f"{result.xdf.title} v{result.xdf.file_version}",
        "stats": {"changed": result.changed_params, "identical": result.identical,
                  "bytes": result.total_bytes_changed, "code": len(result.code_blocks)},
        "warnings": warnings,
        "categories": categories,
        "code_blocks": [
            {"range": f"0x{b.start:06X}–0x{b.end:06X}", "length": b.length}
            for b in result.code_blocks
        ],
    }


# ---------------------------------------------------------------------------
# Parameter details and maps
# ---------------------------------------------------------------------------

def _find_change(state: State, title: str):
    if state.compare is None:
        return None
    for change in state.compare.changes:
        if change.item.title == title:
            return change
    return None


def param_json(state: State, title: str, source: str = "cmp",
               role: str = "bin_a") -> Dict[str, Any]:
    """Parameter details. source: "cmp" (A vs B), "read" (one firmware), "xdf" (no values)."""
    result = state.compare if source == "cmp" else None
    reader = state.reader(role) if source == "read" else None
    if result is not None:
        xdf = result.xdf
    elif reader is not None:
        xdf = reader.xdf
    else:
        xdf = _xdf_for(state, role)
    if xdf is None:
        raise ApiError(t("Choose the XDF first."))
    item = xdf.by_title(title)
    if item is None:
        raise ApiError(t("Parameter \"{name}\" not found in the XDF.", name=title))
    info = names.explain(item.title, item.description)
    units = names.unit(item.value_units)
    dec, otype = item.value_decimals, item.value_output_type
    out: Dict[str, Any] = {
        "title": item.title, "name": info["name"], "desc": info["desc"],
        "desc_orig": info["desc_en"], "note": info["note"], "tune": info["tune"],
        "kind": t("Constant") if item.cell_count == 1 else t("Map {shape}", shape=item.shape_str),
        "units": units, "has_map": item.cell_count > 1 and item.value_output_type != OUT_TEXT,
    }
    change = _find_change(state, title) if source == "cmp" else None
    values_for_meaning: List[float] = []
    if change is not None:
        out["a"] = change.text_a if change.text_a is not None else _range_text(change.vals_a, dec, otype)
        out["b"] = change.text_b if change.text_b is not None else _range_text(change.vals_b, dec, otype)
        if change.is_scalar and change.cells:
            values_for_meaning = [change.cells[0].val_a, change.cells[0].val_b]
    elif result is not None:
        summary = result.reader_a.summary(item)
        out["a"] = out["b"] = summary or "—"
        values = result.reader_a.values(item) or []
        if len(values) == 1:
            values_for_meaning = values
    elif reader is not None:
        out["value"] = reader.summary(item) or "—"
        values = reader.values(item) or []
        if len(values) == 1:
            values_for_meaning = values
    out["meanings"] = [[v, m] for v, m in report.explain_values(title, *values_for_meaning)]
    out["steps"] = report.after_change_steps(title)

    facts = [[t("Category"), report.item_categories(xdf, item)]]
    data = item.data
    if data is not None and data.address is not None:
        facts.append([t("XDF address"), f"0x{data.address:X}"])
        any_reader = result.reader_a if result is not None else reader
        if any_reader is not None:
            facts.append([t("File offset"), f"0x{any_reader.file_offset(data.address):X}"])
        facts.append([t("Format"), t("{bits} bits, {sign}, {order}", bits=data.size_bits,
                                     sign=t("signed") if data.signed else t("unsigned"),
                                     order="little-endian" if data.lsb_first else "big-endian")])
    facts.append([t("Scale"), item.value_equation.describe(units)])
    out["facts"] = facts

    wiki, warnings = [], []
    for section in report.wiki_sections(title)[:3]:
        text = report._focused(section, title)
        if len(text) > 2500:
            text = text[:2500].rsplit(" ", 1)[0] + " …"
        shown = report.translate_wiki(text)
        wiki.append({"head": f"{section.page} / {section.heading}", "text": shown,
                     "orig": text if shown != text else "", "url": section.url})
        warnings += [report.translate_wiki(w) for w in section.caution_lines[:3]]
    out["wiki"] = wiki
    out["warnings"] = list(dict.fromkeys(warnings))
    return out


def _labels(reader: Reader, item, which: str) -> List[str]:
    axis = item.axis_x if which == "x" else item.axis_y
    count = item.cols if which == "x" else item.rows
    values = reader.axis_values(item, which)
    if not values:
        return [str(i) for i in range(count)]
    decimals = axis.decimals if axis else 0
    return [format_number(v, decimals, 1) for v in values[:count]]


def map_json(state: State, title: str, mode: str, source: str = "cmp",
             role: str = "bin_a") -> Dict[str, Any]:
    if source == "read":
        one = state.reader(role)
        item = one.xdf.by_title(title)
        if item is None:
            raise ApiError(t("Parameter \"{name}\" not found in the XDF.", name=title))
        before = after = one.matrix(item)
        mode, label_reader = "a", one
    else:
        result = state.compare
        if result is None:
            raise ApiError(t("Run the comparison first."))
        item = result.xdf.by_title(title)
        if item is None:
            raise ApiError(t("Parameter \"{name}\" not found in the XDF.", name=title))
        before = result.reader_a.matrix(item)
        after = result.reader_b.matrix(item)
        label_reader = result.reader_a
    if not before or not after:
        raise ApiError(t("Could not read the values."))
    dec, otype = item.value_decimals, item.value_output_type
    units = names.unit(item.value_units)
    rows: List[List[Dict[str, Any]]] = []
    if mode == "delta":
        scale = heatmap.delta_scale(before, after)
        for r in range(item.rows):
            row = []
            for c in range(item.cols):
                a, b = before[r][c], after[r][c]
                d = b - a
                cell: Dict[str, Any] = {"v": format_number(b, dec, otype)}
                if d:
                    rgb = heatmap.delta_color(d, scale)
                    cell.update(d=_signed(d, dec, otype), bg=heatmap.hex_color(rgb),
                                fg=heatmap.hex_color(heatmap.text_color(rgb)),
                                tip=t("was {a}, now {b} {units}", a=format_number(a, dec, otype),
                                      b=cell["v"], units=units))
                row.append(cell)
            rows.append(row)
        stops = heatmap.delta_legend_stops(scale)
        legend_title = t("change, {units}", units=units) if units else t("change")
    else:
        matrix = after if mode == "b" else before
        low, high = heatmap.value_range(matrix)
        for r in range(item.rows):
            row = []
            for c in range(item.cols):
                rgb = heatmap.value_color(matrix[r][c], low, high)
                row.append({"v": format_number(matrix[r][c], dec, otype),
                            "bg": heatmap.hex_color(rgb),
                            "fg": heatmap.hex_color(heatmap.text_color(rgb))})
            rows.append(row)
        stops = heatmap.legend_stops(low, high)
        legend_title = t("value, {units}", units=units) if units else t("value")
    y_name, x_name = names.axis_names(item.title)
    if item.cols > 1 and item.rows == 1 and y_name and not x_name:
        y_name, x_name = "", y_name
    x_units = names.unit(item.axis_x.units) if item.axis_x else ""
    y_units = names.unit(item.axis_y.units) if item.axis_y else ""
    caption = []
    if item.rows > 1:
        caption.append(t("rows — {name}", name=y_name or t("index"))
                       + (f" [{y_units}]" if y_units else ""))
    if item.cols > 1:
        caption.append(t("columns — {name}", name=x_name or t("index"))
                       + (f" [{x_units}]" if x_units else ""))
    return {
        "x": _labels(label_reader, item, "x"),
        "y": _labels(label_reader, item, "y") if item.rows > 1 else [""],
        "rows": rows, "caption": " · ".join(caption), "legend_title": legend_title,
        "legend": [{"v": format_number(v, dec, otype), "bg": heatmap.hex_color(rgb),
                    "fg": heatmap.hex_color(heatmap.text_color(rgb))} for v, rgb in stops],
    }


# ---------------------------------------------------------------------------
# Strings for the page
# ---------------------------------------------------------------------------

_T_CALL = re.compile(r"""\bT\(\s*"((?:[^"\\]|\\.)*)"\s*[,)]""")


def page_keys() -> List[str]:
    """Every T("...") key used in app.js (the page translates through these)."""
    with open(os.path.join(STATIC, "app.js"), encoding="utf-8") as fh:
        source = fh.read()
    return sorted({json.loads(f'"{m}"') for m in _T_CALL.findall(source)})


def page_strings() -> Dict[str, str]:
    # keys come from app.js; selftest checks each of them has a translation
    return {key: i18n.t(key) for key in page_keys()}


# ---------------------------------------------------------------------------
# API
# ---------------------------------------------------------------------------

def _file_types(role: str):
    if role == "velog":
        return [(t("Logs"), "*.csv;*.txt;*.log"), (t("All files"), "*.*")]
    if role in XDF_ROLES:
        return [(t("TunerPro definitions"), "*.xdf"), (t("All files"), "*.*")]
    return [(t("Firmware files"), "*.bin"), (t("All files"), "*.*")]


def api_state(state: State, body: Dict) -> Dict:
    return {
        "version": __version__, "lang": get_lang(),
        "langs": [{"code": c, "name": i18n.LANG_NAMES[c]} for c in i18n.LANGS],
        "files": {role: file_info(state, role) for role in ROLES},
        "has_compare": state.compare is not None,
    }


_PICKING = threading.Lock()


def api_pick(state: State, body: Dict) -> Dict:
    role = body.get("role", "")
    if role not in ROLES:
        raise ApiError(f"unknown role {role}")
    current = state.paths.get(role) or state.settings.get("last_dir", "")
    titles = {"xdf": t("Choose the XDF definition"), "xdf2": t("Choose the XDF definition"),
              "bin_a": t("Choose firmware A"), "bin_b": t("Choose firmware B"),
              "bin2": t("Choose the firmware of the other version"),
              "patchlist": t("Choose the patchlist XDF"), "velog": t("Choose the wideband log (CSV)")}
    if not _PICKING.acquire(blocking=False):
        return api_state(state, body)   # a dialog is already open
    try:
        path = DIALOGS.open_file(titles[role], _file_types(role), current)
    finally:
        _PICKING.release()
    if path:
        state.set_path(role, os.path.normpath(path))
        state.settings["last_dir"] = os.path.dirname(path)
        i18n.save_settings(last_dir=os.path.dirname(path))
    return api_state(state, body)


def api_clear(state: State, body: Dict) -> Dict:
    state.set_path(body.get("role", ""), "")
    return api_state(state, body)


def api_compare(state: State, body: Dict) -> Dict:
    if not body.get("cached") or state.compare is None:
        xdf, a, b = state.paths["xdf"], state.paths["bin_a"], state.paths["bin_b"]
        if not (xdf and a and b):
            raise ApiError(t("Choose the XDF and both firmware files."))
        with state.lock:
            state.compare = compare_bins(state.xdf(xdf), BinFile(a), BinFile(b))
    return compare_json(state)


def api_param(state: State, body: Dict) -> Dict:
    return param_json(state, body.get("title", ""), body.get("source", "cmp"),
                      body.get("role", "bin_a"))


def api_map(state: State, body: Dict) -> Dict:
    return map_json(state, body.get("title", ""), body.get("mode", "delta"),
                    body.get("source", "cmp"), body.get("role", "bin_a"))


def _export_type(kind: str):
    return {"html": (t("HTML page"), "*.html"), "csv": (t("CSV for Excel"), "*.csv"),
            "pdf": (t("PDF document"), "*.pdf")}[kind]


def api_export(state: State, body: Dict) -> Dict:
    kind = body.get("kind", "html")
    if state.compare is None:
        raise ApiError(t("Run the comparison first."))
    if kind not in ("html", "csv", "pdf"):
        raise ApiError(f"unknown format {kind}")
    default = t("ms43_report") + "." + kind
    path = DIALOGS.save_file(t("Save as"), [_export_type(kind)], default,
                             state.settings.get("last_out_dir", ""))
    if not path:
        return {"path": ""}
    state.settings["last_out_dir"] = os.path.dirname(path)
    i18n.save_settings(last_out_dir=os.path.dirname(path))
    if kind == "html":
        report.write_html(state.compare, path)
    elif kind == "csv":
        report.write_csv(state.compare, path)
    else:
        from ..pdfreport import PdfUnavailable, write_compare_pdf

        try:
            write_compare_pdf(state.compare, path)
        except PdfUnavailable as exc:
            raise ApiError(str(exc)) from exc
    log_write(f"[web] saved {kind}: {path}")
    return {"path": path}


def api_open(state: State, body: Dict) -> Dict:
    path = body.get("path", "")
    if not path or not os.path.isfile(path):
        raise ApiError(t("File not found"))
    if sys.platform == "win32":
        os.startfile(path)  # noqa: S606 - a file we have just written
    else:
        import webbrowser

        webbrowser.open("file://" + os.path.abspath(path))
    return {}


def api_lang(state: State, body: Dict) -> Dict:
    set_lang(body.get("lang"), remember=True)
    return {"lang": get_lang()}


def api_log(state: State, body: Dict) -> Dict:
    from ..applog import log_path

    path = log_path()
    if not os.path.isfile(path):
        log_write("[log] empty file created from the button")
    return api_open(state, {"path": path})


# ---- AI assistant -----------------------------------------------------------

def _ai_call(fn):
    """Run an AI-mode action, turn its expected errors into ApiError, return the new state."""
    from .. import mcpinstall
    from .ai import AiError

    def wrapper(state: State, body: Dict) -> Dict:
        try:
            extra = fn(state, body) or {}
        except (AiError, mcpinstall.InstallError) as exc:
            raise ApiError(str(exc)) from exc
        out = state.ai.describe()
        out.update(extra)
        return out
    return wrapper


@_ai_call
def api_ai_state(state, body):
    return {}


@_ai_call
def api_ai_add(state, body):
    state.ai.add()


@_ai_call
def api_ai_update(state, body):
    state.ai.update(body.get("name", ""), body.get("changes") or {})


@_ai_call
def api_ai_remove(state, body):
    state.ai.remove(body.get("name", ""))


@_ai_call
def api_ai_start(state, body):
    state.ai.start(body.get("name", ""))


@_ai_call
def api_ai_stop(state, body):
    state.ai.stop(body.get("name", ""))


@_ai_call
def api_ai_check(state, body):
    return {"check": state.ai.check(body.get("name", ""))}


@_ai_call
def api_ai_code(state, body):
    state.ai.code_register(body.get("name", ""), bool(body.get("register", True)))


@_ai_call
def api_desk_install(state, body):
    return {"message": state.ai.desktop_install(body.get("name", ""), body.get("role", ""),
                                                body.get("lang", ""))}


@_ai_call
def api_desk_remove(state, body):
    return {"message": state.ai.desktop_remove(body.get("name", ""))}


@_ai_call
def api_desk_check(state, body):
    from .. import mcpinstall

    return {"check": mcpinstall.check_entry(body.get("name", ""))}


def _mode_call(name: str):
    """Wrap a modes.py function: expected problems become ApiError."""
    def wrapper(state: State, body: Dict) -> Dict:
        from . import modes
        from ..pdfreport import PdfUnavailable
        from ..vetune import LogError

        try:
            return getattr(modes, name)(state, body)
        except (modes.ModeError, PdfUnavailable, LogError) as exc:
            raise ApiError(str(exc)) from exc
    return wrapper


_MODE_CALLS = ("browse", "cross", "port", "patches", "ve_setup", "ve_run", "ve_save",
               "wiki", "wiki_section", "wiki_download", "save_report")

API: Dict[str, Callable[[State, Dict], Dict]] = {
    "state": api_state, "pick": api_pick, "clear": api_clear, "compare": api_compare,
    "param": api_param, "map": api_map, "export": api_export, "open": api_open,
    "lang": api_lang, "log": api_log,
    "ai_state": api_ai_state, "ai_add": api_ai_add, "ai_update": api_ai_update,
    "ai_remove": api_ai_remove, "ai_start": api_ai_start, "ai_stop": api_ai_stop,
    "ai_check": api_ai_check, "ai_code": api_ai_code,
    "desk_install": api_desk_install, "desk_remove": api_desk_remove,
    "desk_check": api_desk_check,
    **{name: _mode_call(name) for name in _MODE_CALLS},
}


# ---------------------------------------------------------------------------
# HTTP
# ---------------------------------------------------------------------------

class Server(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, state: State):
        super().__init__(("127.0.0.1", 0), Handler)
        self.state = state
        self.token = secrets.token_urlsafe(24)
        self.last_seen = time.monotonic()
        self.bye_at: Optional[float] = None

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.server_address[1]}/?t={self.token}"


class Handler(BaseHTTPRequestHandler):
    server: Server

    def log_message(self, fmt, *args):  # quiet: no console in the window build
        pass

    def _host_ok(self) -> bool:
        return self.headers.get("Host", "") == f"127.0.0.1:{self.server.server_address[1]}"

    def _send(self, code: int, body: bytes, ctype: str) -> None:
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        try:
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError):
            pass  # the window was closed while we were answering

    def _json(self, code: int, data: Any) -> None:
        self._send(code, json.dumps(data, ensure_ascii=False).encode("utf-8"),
                   "application/json; charset=utf-8")

    def do_GET(self) -> None:  # noqa: N802
        if not self._host_ok():
            return self._send(403, b"forbidden", "text/plain")
        path = self.path.split("?", 1)[0]
        if path == "/":
            path = "/index.html"
        name = os.path.basename(path)
        file = os.path.join(STATIC, name)
        if path != "/" + name or not os.path.isfile(file):
            return self._send(404, b"not found", "text/plain")
        with open(file, "rb") as fh:
            body = fh.read()
        if name == "index.html":
            self.server.bye_at = None   # the page is back (a reload, not a close)
            boot = json.dumps({"token": self.server.token, "lang": get_lang(),
                               "strings": page_strings()}, ensure_ascii=False)
            body = body.replace(b"/*BOOT*/null", boot.replace("</", "<\\/").encode("utf-8"))
            body = body.replace(b'lang="en"', f'lang="{get_lang()}"'.encode())
        self._send(200, body, _CONTENT_TYPES.get(os.path.splitext(name)[1], "text/plain"))

    def do_POST(self) -> None:  # noqa: N802
        if not self._host_ok() or self.headers.get("X-Token") != self.server.token:
            return self._send(403, b"forbidden", "text/plain")
        name = self.path.split("?", 1)[0].rsplit("/", 1)[-1]
        length = int(self.headers.get("Content-Length") or 0)
        try:
            body = json.loads(self.rfile.read(length) or b"{}")
        except ValueError:
            body = {}
        self.server.last_seen = time.monotonic()
        if name != "bye":
            self.server.bye_at = None   # any call means the page is still open
        if name == "ping":
            return self._json(200, {})
        if name == "bye":
            self.server.bye_at = time.monotonic()
            return self._json(200, {})
        fn = API.get(name)
        if fn is None:
            return self._json(404, {"error": f"unknown call {name}"})
        try:
            return self._json(200, fn(self.server.state, body))
        except ApiError as exc:
            return self._json(400, {"error": str(exc)})
        except Exception as exc:  # noqa: BLE001 - logged and shown
            path = log_write(f"[web api {name}]\n" + traceback.format_exc())
            return self._json(500, {"error": t("{error}\n\nDetails were written to the log:\n{path}",
                                               error=exc, path=path)})


# ---------------------------------------------------------------------------
# Running
# ---------------------------------------------------------------------------

def start(state: Optional[State] = None) -> Server:
    server = Server(state or State())
    threading.Thread(target=server.serve_forever, name="http", daemon=True).start()
    return server


def run(open_browser: bool = True) -> int:
    """Start the server, open the window and wait until it is closed."""
    from .launcher import open_window

    server = start()
    log_write(f"[start] ms43diff web {__version__}, lang={get_lang()}, "
              f"frozen={getattr(sys, 'frozen', False)}, url=127.0.0.1:{server.server_address[1]}")
    process = open_window(server.url) if open_browser else None
    started = time.monotonic()
    try:
        while True:
            time.sleep(0.5)
            now = time.monotonic()
            if process is not None and process.poll() is not None:
                if now - started > 5:
                    break          # our Edge window was closed
                process = None     # Edge handed the URL to another instance
            if process is None:
                # browser mode: the page says "bye" on close and pings while open
                if server.bye_at is not None and now - server.bye_at > 4:
                    break
                if now - server.last_seen > 600 and now - started > 600:
                    break
    except KeyboardInterrupt:
        pass
    if server.state._ai is not None:
        server.state._ai.stop_all()
    server.shutdown()
    return 0
