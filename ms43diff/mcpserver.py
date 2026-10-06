# -*- coding: utf-8 -*-
"""
ms43diff MCP server: gives an AI assistant the firmware data and the wiki
knowledge base.

Why. Dumping the whole knowledge base into a chat clogs the context and the
model starts "forgetting" the beginning. Here the knowledge stays OUTSIDE the
context: the model keeps only a short list of tools in mind and asks for facts
(a parameter value, a wiki article, warnings) on demand, always fresh. Nothing
to forget or go stale — the knowledge lives in the tool, not in model memory.

Protocol. MCP over stdio is JSON-RPC 2.0, one message per line. Implemented by
hand without third-party libraries: the .exe stays small and we control the
protocol fully. Logs go to stderr only — stdout carries the protocol and must
not receive anything else.

Read-only. The server never writes to the firmware — it analyses and explains,
and the user edits in TunerPro. Firmware and XDF are given as command line
arguments (--bin, --xdf). Tool descriptions are in English (they are read by
the model); tool results follow the UI language (--lang).
"""

from __future__ import annotations

import contextvars
import json
import sys
import traceback
from typing import Any, Callable, Dict, List, Optional

from . import __version__, names, wikicache, wikitrans
from .binfile import BinFile, Reader, format_number
from .i18n import get_lang, t
from .xdf import OUT_TEXT, Item, XdfFile

PROTOCOL_VERSION = "2024-11-05"
SERVER_NAME = "ms43diff"


def _log(*parts: Any) -> None:
    print("[ms43-ai-tuner-mcp]", *parts, file=sys.stderr, flush=True)


# ---------------------------------------------------------------------------
# State: firmware + XDF, loaded lazily on first use
# ---------------------------------------------------------------------------


class Firmware:
    def __init__(self, xdf_path: Optional[str], bin_path: Optional[str]):
        self.xdf_path = xdf_path
        self.bin_path = bin_path
        self._xdf: Optional[XdfFile] = None
        self._bin: Optional[BinFile] = None
        self._reader: Optional[Reader] = None

    @property
    def reader(self) -> Reader:
        if self._reader is None:
            if not self.xdf_path or not self.bin_path:
                raise ValueError(t("Firmware and/or XDF not set. Start the server with "
                                   "--xdf PATH.xdf --bin PATH.bin"))
            self._xdf = XdfFile(self.xdf_path)
            self._bin = BinFile(self.bin_path)
            self._reader = Reader(self._xdf, self._bin)
            _log(f"loaded: {self._xdf.title} v{self._xdf.file_version}, "
                 f"{self._bin.name}, software {self._reader.firmware_id()}")
        return self._reader

    @property
    def xdf(self) -> XdfFile:
        self.reader  # warm up
        return self._xdf  # type: ignore[return-value]


STATE: Optional[Firmware] = None
# The firmware of the server answering the current request; the HTTP server
# (mcphttp.py) runs several servers in one process, each with its own files.
CURRENT: "contextvars.ContextVar[Optional[Firmware]]" = contextvars.ContextVar(
    "ms43diff_firmware", default=None)


# ---------------------------------------------------------------------------
# Building a human-readable dossier for a parameter
# ---------------------------------------------------------------------------


def _wiki_block(title: str, translate: bool = True) -> List[str]:
    if not wikicache.available():
        return []
    out: List[str] = []
    meanings = wikicache.value_meanings(title)
    if meanings:
        out.append(t("Switch values:"))
        for key in sorted(meanings):
            text = meanings[key]
            out.append(f"  {key} = {wikitrans.translate_line(text) if translate else text}")
    steps = wikicache.procedure_for(title)
    if steps:
        out.append(t("After the change:"))
        for step in steps:
            out.append(f"  • {wikitrans.translate_line(step) if translate else step}")
    sections = wikicache.sections_for(title)
    for section in sections[:3]:
        out.append("")
        out.append(f"[{section.page} / {section.heading}]")
        english = wikicache.focused_text(section, title)
        body = wikitrans.translate_block(english) if translate else english
        out.append(body.strip())
        for warning in section.caution_lines[:3]:
            w = wikitrans.translate_line(warning) if translate else warning
            out.append(f"⚠ {w}")
        out.append(t("source: {url}", url=section.url))
    if len(sections) > 3:
        out.append(t("({n} more mentions in the wiki)", n=len(sections) - 3))
    return out


def dossier(title: str, translate: bool = True) -> str:
    """Full parameter dossier: value from the firmware + everything from the wiki."""
    fw = _require_state()
    item = fw.xdf.by_title(title)
    if item is None:
        # try as a substring
        matches = [i.title for i in fw.xdf.readable_items(include_axes=True)
                   if title.lower() in i.title.lower()][:20]
        hint = ("\n" + t("Similar names: {names}", names=", ".join(matches))) if matches else ""
        return t("Parameter \"{name}\" not found in the XDF.", name=title) + hint

    reader = fw.reader
    info = names.explain(item.title, item.description)
    units = names.unit(item.value_units)
    out: List[str] = []
    out.append(f"# {item.title}")
    out.append(t("Name: {text}", text=info["name"]))
    out.append(t("Type: {kind} ({shape})", kind=info["kind"], shape=item.shape_str))
    out.append(t("Category: {text}", text=", ".join(
        names.category(n) for n in fw.xdf.category_names(item))))
    if info["desc"]:
        out.append(t("Description: {text}", text=info["desc"]))
    if info["desc_en"]:
        out.append(t("Original: {text}", text=info["desc_en"]))
    if info["note"]:
        out.append(t("What it does: {text}", text=info["note"]))
    if info["tune"]:
        out.append(t("How to tune: {text}", text=info["tune"]))

    data = item.data
    if data is not None and data.address is not None:
        out.append(t(
            "Address: XDF 0x{address:X} → file 0x{offset:X}, {bits} bits, {sign}, {order}",
            address=data.address, offset=reader.file_offset(data.address),
            bits=data.size_bits, sign=t("signed") if data.signed else t("unsigned"),
            order="little-endian" if data.lsb_first else "big-endian"))
    out.append(t("Units: {text}", text=units or "—"))
    out.append(t("Scale: {text}", text=item.value_equation.describe(units)))

    summary = reader.summary(item)
    if summary is not None:
        out.append(t("Value in the firmware: {value}", value=f"{summary} {units}".rstrip()))

    wiki = _wiki_block(item.title, translate=translate)
    if wiki:
        out.append("")
        out.append(t("## MS4X Wiki reference"))
        out.extend(wiki)
    return "\n".join(out)


def map_text(title: str, max_cells: int = 400) -> str:
    """A map with its axes, as numbers."""
    fw = _require_state()
    item = fw.xdf.by_title(title)
    if item is None:
        return t("Map \"{name}\" not found.", name=title)
    reader = fw.reader
    matrix = reader.matrix(item)
    if not matrix:
        return t("Could not read \"{name}\" (address outside the file?).", name=title)
    if item.cell_count > max_cells:
        return t("Map {shape} is too big to print ({n} cells). Use get_param for a summary.",
                 shape=item.shape_str, n=item.cell_count)

    dec, otype = item.value_decimals, item.value_output_type
    units = names.unit(item.value_units)
    y_name, x_name = names.axis_names(item.title)
    x = reader.axis_values(item, "x") or list(range(item.cols))
    y = reader.axis_values(item, "y") or list(range(item.rows))

    def fnum(v, d=1):
        return format_number(v, d, 1)

    out = [f"# {item.title} — {names.explain(item.title, item.description)['name']}"]
    out.append(t("values in {units}; rows — {rows}; columns — {cols}",
                 units=units or t("units"), rows=y_name or t("index"),
                 cols=x_name or t("index")))
    header = "        " + " ".join(f"{fnum(v):>8}" for v in x[:item.cols])
    out.append(header)
    for r in range(item.rows):
        ylab = fnum(y[r]) if r < len(y) else str(r)
        cells = " ".join(f"{format_number(matrix[r][c], dec, otype):>8}"
                         for c in range(item.cols))
        out.append(f"{ylab:>7} {cells}")
    return "\n".join(out)


def _require_state() -> Firmware:
    current = CURRENT.get()
    if current is not None:
        return current
    if STATE is None:
        raise ValueError(t("The server has no firmware loaded."))
    return STATE


# ---------------------------------------------------------------------------
# MCP tools
# ---------------------------------------------------------------------------


def tool_firmware_info(_args: Dict) -> str:
    fw = _require_state()
    reader = fw.reader
    xdf = fw.xdf
    lines = [
        t("Firmware: {name}", name=fw._bin.name),
        t("Software version: {fw}", fw=reader.firmware_id() or "?"),
        f"XDF: {xdf.title} v{xdf.file_version} ({xdf.author})",
        t("Offset: {label}", label=reader.offset.label),
        t("Objects in the XDF: {n}", n=len(xdf.items)),
    ]
    warning = reader.version_warning()
    if warning:
        lines.append(t("WARNING: {text}", text=warning))
    if wikicache.available():
        info = wikicache.meta()
        lines.append(t("MS4X Wiki reference: snapshot {date}, {n} pages",
                       date=info.get("fetched", "?"), n=len(wikicache.load())))
    return "\n".join(lines)


def tool_list_categories(_args: Dict) -> str:
    fw = _require_state()
    counts: Dict[str, int] = {}
    for item in fw.xdf.readable_items(include_axes=False):
        for name in fw.xdf.category_names(item):
            counts[name] = counts.get(name, 0) + 1
    lines = [t("Categories (number of parameters):")]
    for name in sorted(counts, key=lambda n: (-counts[n], n)):
        lines.append(f"  {counts[name]:>4}  {names.category(name)}  ({name})")
    return "\n".join(lines)


def tool_list_params(args: Dict) -> str:
    fw = _require_state()
    category = (args.get("category") or "").lower()
    needle = (args.get("filter") or "").lower()
    limit = int(args.get("limit") or 60)
    reader = fw.reader
    out: List[str] = []
    count = 0
    for item in fw.xdf.readable_items(include_axes=False):
        cats = [names.category(n) for n in fw.xdf.category_names(item)] + \
               fw.xdf.category_names(item)
        if category and not any(category in c.lower() for c in cats):
            continue
        name = names.explain(item.title, item.description)["name"]
        hay = f"{item.title} {name} {item.description}".lower()
        if needle and needle not in hay:
            continue
        count += 1
        if count > limit:
            out.append(t("… there is more, showing the first {n}. Refine the filter.", n=limit))
            break
        value = reader.summary(item)
        out.append(f"{item.title}  [{item.shape_str}]  "
                   f"{value or ''} {names.unit(item.value_units)}".rstrip()
                   + f"  — {name}")
    if not out:
        return t("Nothing found for these filters.")
    return "\n".join(out)


def tool_get_param(args: Dict) -> str:
    name = args.get("name") or ""
    if not name:
        return t("Give name — the parameter name.")
    return dossier(name, translate=bool(args.get("translate", True)))


def tool_read_map(args: Dict) -> str:
    name = args.get("name") or ""
    if not name:
        return t("Give name — the map name.")
    return map_text(name, max_cells=int(args.get("max_cells") or 400))


def tool_explain_value(args: Dict) -> str:
    name = args.get("name") or ""
    value = args.get("value")
    if not name or value is None:
        return t("Give name and value.")
    if not wikicache.available():
        return t("The reference is not loaded.")
    meanings = wikicache.value_meanings(name)
    if not meanings:
        return t("The wiki has no value meanings for {name}.", name=name)
    try:
        key = int(round(float(value)))
    except (TypeError, ValueError):
        return t("value must be a number.")
    text = meanings.get(key)
    if text is None:
        avail = ", ".join(str(k) for k in sorted(meanings))
        return t("The wiki has no value {key} for {name}. Available: {avail}",
                 key=key, name=name, avail=avail)
    shown = wikitrans.translate_line(text)
    if shown == text:
        return f"{name} = {key}: {text}"
    return f"{name} = {key}: {shown}\n" + t("(original: {text})", text=text)


def tool_search_wiki(args: Dict) -> str:
    query = args.get("query") or ""
    if not query:
        return t("Give query.")
    if not wikicache.available():
        return t("The reference is not loaded. Update it: ms43diff wiki --download")
    limit = int(args.get("limit") or 8)
    sections = wikicache.search(query, limit=limit)
    if not sections:
        return t("Nothing found.")
    translate = bool(args.get("translate", True))
    out: List[str] = []
    for section in sections:
        out.append(f"## {section.page} / {section.heading}")
        body = wikitrans.translate_block(section.text) if translate else section.text
        if len(body) > 1500:
            body = body[:1500].rsplit(" ", 1)[0] + " …"
        out.append(body.strip())
        out.append(t("source: {url}", url=section.url))
        out.append("")
    return "\n".join(out)


def tool_wiki_page(args: Dict) -> str:
    name = args.get("name") or ""
    if not wikicache.available():
        return t("The reference is not loaded.")
    page = wikicache.page(name)
    if page is None:
        avail = ", ".join(n for n, _, _ in wikicache.page_names())
        return t("Page not found. Available: {avail}", avail=avail)
    translate = bool(args.get("translate", True))
    out = [f"# {page.title}", page.url, ""]
    for section in page.sections:
        out.append(f"## {section.heading}")
        body = wikitrans.translate_block(section.text) if translate else section.text
        out.append(body.strip())
        out.append("")
    return "\n".join(out)


def tool_cautions(args: Dict) -> str:
    if not wikicache.available():
        return t("The reference is not loaded.")
    sections = wikicache.cautions(args.get("page"))
    translate = bool(args.get("translate", True))
    out = [t("MS4X Wiki warnings (\"how not to break anything\"):"), ""]
    for section in sections:
        out.append(f"• {section.page} / {section.heading}")
        for warning in section.caution_lines:
            w = wikitrans.translate_line(warning) if translate else warning
            out.append(f"  ⚠ {w}")
        out.append(f"  {section.url}")
    return "\n".join(out)


# Tool descriptions for tools/list. English on purpose: they are read by the
# model, not by the user, and English descriptions work best for tool choice.
TOOLS: List[Dict[str, Any]] = [
    {
        "name": "firmware_info",
        "description": "Loaded firmware details: software version, XDF, offset, and a "
                       "warning if the XDF does not match the software version.",
        "inputSchema": {"type": "object", "properties": {}},
        "_fn": tool_firmware_info,
    },
    {
        "name": "list_categories",
        "description": "Parameter categories (Ignition, VANOS, Injection, etc.) with the "
                       "number of parameters in each.",
        "inputSchema": {"type": "object", "properties": {}},
        "_fn": tool_list_categories,
    },
    {
        "name": "list_params",
        "description": "Parameters with their values from the firmware. Filter by category "
                       "and by a substring of the name/description.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "category": {"type": "string", "description": "category (English or Russian)"},
                "filter": {"type": "string", "description": "substring of the name/description"},
                "limit": {"type": "integer", "description": "how many to return (default 60)"},
            },
        },
        "_fn": tool_list_params,
    },
    {
        "name": "get_param",
        "description": "Full parameter dossier: readable name, value from the firmware, "
                       "scale, address, description, MS4X Wiki article, value meanings and "
                       "warnings. The main tool for understanding a setting.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "parameter name, e.g. c_conf_cat"},
                "translate": {"type": "boolean",
                              "description": "translate the wiki in Russian mode (default yes)"},
            },
            "required": ["name"],
        },
        "_fn": tool_get_param,
    },
    {
        "name": "read_map",
        "description": "A map (table) with its axes as numbers: real values from the "
                       "firmware by rpm and load.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "max_cells": {"type": "integer"},
            },
            "required": ["name"],
        },
        "_fn": tool_read_map,
    },
    {
        "name": "explain_value",
        "description": "What a specific switch value means, e.g. \"c_conf_cat = 4\", "
                       "according to the wiki.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "value": {"type": "number"},
            },
            "required": ["name", "value"],
        },
        "_fn": tool_explain_value,
    },
    {
        "name": "search_wiki",
        "description": "Full-text search in the offline MS4X Wiki copy.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "limit": {"type": "integer"},
                "translate": {"type": "boolean"},
            },
            "required": ["query"],
        },
        "_fn": tool_search_wiki,
    },
    {
        "name": "wiki_page",
        "description": "A whole MS4X Wiki page by name (e.g. Siemens_MS43).",
        "inputSchema": {
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "translate": {"type": "boolean"},
            },
            "required": ["name"],
        },
        "_fn": tool_wiki_page,
    },
    {
        "name": "cautions",
        "description": "All wiki warnings — what must not be broken. Can be limited to "
                       "one page.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "page": {"type": "string"},
                "translate": {"type": "boolean"},
            },
        },
        "_fn": tool_cautions,
    },
]

_TOOL_BY_NAME: Dict[str, Callable[[Dict], str]] = {tool["name"]: tool["_fn"] for tool in TOOLS}


# ---------------------------------------------------------------------------
# JSON-RPC 2.0 over stdio
# ---------------------------------------------------------------------------


def _result(request_id: Any, result: Any) -> Dict:
    return {"jsonrpc": "2.0", "id": request_id, "result": result}


def _error(request_id: Any, code: int, message: str) -> Dict:
    return {"jsonrpc": "2.0", "id": request_id, "error": {"code": code, "message": message}}


def handle(message: Dict) -> Optional[Dict]:
    """Handle one JSON-RPC message. None if no response is needed."""
    method = message.get("method")
    request_id = message.get("id")
    params = message.get("params") or {}

    if method == "initialize":
        client_version = params.get("protocolVersion") or PROTOCOL_VERSION
        return _result(request_id, {
            "protocolVersion": client_version,
            "capabilities": {"tools": {"listChanged": False}},
            "serverInfo": {"name": SERVER_NAME, "version": __version__},
        })

    if method in ("notifications/initialized", "initialized"):
        return None  # a notification, no response

    if method == "ping":
        return _result(request_id, {})

    if method == "tools/list":
        tools = [{k: v for k, v in tool.items() if not k.startswith("_")} for tool in TOOLS]
        return _result(request_id, {"tools": tools})

    if method == "tools/call":
        name = params.get("name")
        arguments = params.get("arguments") or {}
        fn = _TOOL_BY_NAME.get(name)
        if fn is None:
            return _error(request_id, -32602, f"Unknown tool: {name}")
        try:
            text = fn(arguments)
            return _result(request_id, {
                "content": [{"type": "text", "text": text}],
                "isError": False,
            })
        except Exception as exc:  # noqa: BLE001 - return the error as a result, keep serving
            _log("tool error", name, exc)
            _log(traceback.format_exc())
            return _result(request_id, {
                "content": [{"type": "text", "text": t("Error: {error}", error=exc)}],
                "isError": True,
            })

    if request_id is not None:
        return _error(request_id, -32601, f"Method not supported: {method}")
    return None


def serve(xdf_path: Optional[str], bin_path: Optional[str]) -> int:
    """Run the MCP server stdio loop."""
    global STATE
    STATE = Firmware(xdf_path, bin_path)

    # The protocol is strictly UTF-8. The client starts the server as a
    # subprocess, and on Windows the default stream encoding may be a legacy
    # code page: without this, non-ASCII answers fail with UnicodeEncodeError.
    for stream in (sys.stdin, sys.stdout):
        try:
            stream.reconfigure(encoding="utf-8", newline="\n")
        except (AttributeError, ValueError):
            pass

    _log(f"ms43diff MCP {__version__} started, lang={get_lang()}. "
         f"XDF={xdf_path or '-'} BIN={bin_path or '-'}")

    stdin = sys.stdin
    stdout = sys.stdout
    for raw in stdin:
        line = raw.strip()
        if not line:
            continue
        try:
            message = json.loads(line)
        except ValueError:
            _log("not JSON:", line[:120])
            continue
        try:
            response = handle(message)
        except Exception as exc:  # noqa: BLE001
            _log("handling failed:", exc)
            response = _error(message.get("id"), -32603, str(exc))
        if response is not None:
            stdout.write(json.dumps(response, ensure_ascii=False) + "\n")
            stdout.flush()
    _log("stdin closed, exiting")
    return 0
