# -*- coding: utf-8 -*-
"""
MCP-сервер ms43diff: отдаёт данные прошивки и базу знаний вики нейросети.

Зачем это нужно. Если скинуть всю базу в чат, она забьёт контекст, и нейросеть
начнёт «забывать» начало. Здесь база лежит СНАРУЖИ контекста: нейросеть держит
в голове только короткий список инструментов, а факты (значение параметра,
статью вики, предупреждения) запрашивает по требованию и получает свежими.
Забыть или устареть нечему — знание в утилите, а не в памяти модели.

Протокол. MCP поверх stdio — это JSON-RPC 2.0, по одному сообщению на строку.
Реализован вручную, без сторонних библиотек: так .exe остаётся лёгким, а мы
полностью контролируем протокол. Логи идут только в stderr — stdout занят
протоколом, туда нельзя писать ничего лишнего.

Только чтение. Сервер ничего не пишет в прошивку — он анализирует и объясняет,
а правки пользователь вносит руками в TunerPro. Прошивка и XDF задаются
аргументами командной строки (--bin, --xdf), нейросеть работает по ним.
"""

from __future__ import annotations

import json
import sys
import traceback
from typing import Any, Callable, Dict, List, Optional

from . import __version__, ru, wikicache, wikitrans
from .binfile import BinFile, Reader, format_number
from .xdf import OUT_TEXT, Item, XdfFile

PROTOCOL_VERSION = "2024-11-05"
SERVER_NAME = "ms43diff"


def _log(*parts: Any) -> None:
    print("[ms43diff-mcp]", *parts, file=sys.stderr, flush=True)


# ---------------------------------------------------------------------------
# Состояние: прошивка + XDF, загружаются лениво при первом обращении
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
                raise ValueError(
                    "Не заданы прошивка и/или XDF. Запустите сервер с "
                    "--xdf ПУТЬ.xdf --bin ПУТЬ.bin"
                )
            self._xdf = XdfFile(self.xdf_path)
            self._bin = BinFile(self.bin_path)
            self._reader = Reader(self._xdf, self._bin)
            _log(f"загружено: {self._xdf.title} v{self._xdf.file_version}, "
                 f"{self._bin.name}, версия ПО {self._reader.firmware_id()}")
        return self._reader

    @property
    def xdf(self) -> XdfFile:
        self.reader  # прогреть
        return self._xdf  # type: ignore[return-value]


STATE: Optional[Firmware] = None


# ---------------------------------------------------------------------------
# Сборка человеко-читаемого досье по параметру
# ---------------------------------------------------------------------------


def _wiki_block(title: str, translate: bool = True) -> List[str]:
    if not wikicache.available():
        return []
    out: List[str] = []
    meanings = wikicache.value_meanings(title)
    if meanings:
        out.append("Значения переключателя:")
        for key in sorted(meanings):
            text = meanings[key]
            out.append(f"  {key} = {wikitrans.translate_line(text) if translate else text}")
    steps = wikicache.procedure_for(title)
    if steps:
        out.append("После изменения нужно:")
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
        out.append(f"источник: {section.url}")
    if len(sections) > 3:
        out.append(f"(ещё {len(sections) - 3} упоминаний в вики)")
    return out


def dossier(title: str, translate: bool = True) -> str:
    """Полное досье по параметру: значение из прошивки + вся вики."""
    fw = _require_state()
    item = fw.xdf.by_title(title)
    if item is None:
        # попробуем как подстроку
        matches = [i.title for i in fw.xdf.readable_items(include_axes=True)
                   if title.lower() in i.title.lower()][:20]
        hint = ("\nПохожие имена: " + ", ".join(matches)) if matches else ""
        return f"Параметр «{title}» в XDF не найден.{hint}"

    reader = fw.reader
    info = ru.explain(item.title, item.description)
    units = ru.unit_ru(item.value_units)
    out: List[str] = []
    out.append(f"# {item.title}")
    out.append(f"Название: {info['name']}")
    out.append(f"Тип: {info['kind']} ({item.shape_str})")
    out.append(f"Категория: {', '.join(ru.category_ru(n) for n in fw.xdf.category_names(item))}")
    if info["desc"]:
        out.append(f"Описание: {info['desc']}")
    if info["desc_en"]:
        out.append(f"Оригинал: {info['desc_en']}")
    if info["note"]:
        out.append(f"Что делает: {info['note']}")
    if info["tune"]:
        out.append(f"Как крутить: {info['tune']}")

    data = item.data
    if data is not None and data.address is not None:
        out.append(
            f"Адрес: XDF 0x{data.address:X} → файл 0x{reader.file_offset(data.address):X}, "
            f"{data.size_bits} бит, "
            f"{'со знаком' if data.signed else 'без знака'}, "
            f"{'little-endian' if data.lsb_first else 'big-endian'}"
        )
    out.append(f"Единицы: {units or '—'}")
    out.append(f"Масштаб: {item.value_equation.describe_ru(units)}")

    summary = reader.summary(item)
    if summary is not None:
        out.append(f"Значение в прошивке: {summary} {units}".rstrip())

    wiki = _wiki_block(item.title, translate=translate)
    if wiki:
        out.append("")
        out.append("## Справочник MS4X Wiki")
        out.extend(wiki)
    return "\n".join(out)


def map_text(title: str, max_cells: int = 400) -> str:
    """Карта с осями в числах."""
    fw = _require_state()
    item = fw.xdf.by_title(title)
    if item is None:
        return f"Карта «{title}» не найдена."
    reader = fw.reader
    matrix = reader.matrix(item)
    if not matrix:
        return f"Не удалось прочитать «{title}» (адрес вне файла?)."
    if item.cell_count > max_cells:
        return (f"Карта {item.shape_str} слишком большая для вывода "
                f"({item.cell_count} ячеек). Используйте get_param для сводки.")

    dec, otype = item.value_decimals, item.value_output_type
    units = ru.unit_ru(item.value_units)
    y_name, x_name = ru.axis_names_ru(item.title)
    x = reader.axis_values(item, "x") or list(range(item.cols))
    y = reader.axis_values(item, "y") or list(range(item.rows))

    def fnum(v, d=1):
        return format_number(v, d, 1)

    out = [f"# {item.title} — {ru.explain(item.title, item.description)['name']}"]
    out.append(f"значения в {units or 'ед.'}; "
               f"строки — {y_name or 'индекс'}; столбцы — {x_name or 'индекс'}")
    header = "        " + " ".join(f"{fnum(v):>8}" for v in x[:item.cols])
    out.append(header)
    for r in range(item.rows):
        ylab = fnum(y[r]) if r < len(y) else str(r)
        cells = " ".join(f"{format_number(matrix[r][c], dec, otype):>8}"
                         for c in range(item.cols))
        out.append(f"{ylab:>7} {cells}")
    return "\n".join(out)


def _require_state() -> Firmware:
    if STATE is None:
        raise ValueError("Сервер не инициализирован прошивкой.")
    return STATE


# ---------------------------------------------------------------------------
# Инструменты MCP
# ---------------------------------------------------------------------------


def tool_firmware_info(_args: Dict) -> str:
    fw = _require_state()
    reader = fw.reader
    xdf = fw.xdf
    lines = [
        f"Прошивка: {fw._bin.name}",
        f"Версия ПО: {reader.firmware_id() or '?'}",
        f"XDF: {xdf.title} v{xdf.file_version} ({xdf.author})",
        f"Смещение: {reader.offset.label}",
        f"Объектов в XDF: {len(xdf.items)}",
    ]
    warning = reader.version_warning()
    if warning:
        lines.append(f"ВНИМАНИЕ: {warning}")
    if wikicache.available():
        info = wikicache.meta()
        lines.append(f"Справочник MS4X Wiki: снимок {info.get('fetched', '?')}, "
                     f"{len(wikicache.load())} страниц")
    return "\n".join(lines)


def tool_list_categories(_args: Dict) -> str:
    fw = _require_state()
    counts: Dict[str, int] = {}
    for item in fw.xdf.readable_items(include_axes=False):
        for name in fw.xdf.category_names(item):
            counts[name] = counts.get(name, 0) + 1
    lines = ["Категории (число параметров):"]
    for name in sorted(counts, key=lambda n: (-counts[n], n)):
        lines.append(f"  {counts[name]:>4}  {ru.category_ru(name)}  ({name})")
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
        cats = [ru.category_ru(n) for n in fw.xdf.category_names(item)] + \
               fw.xdf.category_names(item)
        if category and not any(category in c.lower() for c in cats):
            continue
        name = ru.explain(item.title, item.description)["name"]
        hay = f"{item.title} {name} {item.description}".lower()
        if needle and needle not in hay:
            continue
        count += 1
        if count > limit:
            out.append(f"… ещё есть, показаны первые {limit}. Уточните filter.")
            break
        value = reader.summary(item)
        out.append(f"{item.title}  [{item.shape_str}]  "
                   f"{value or ''} {ru.unit_ru(item.value_units)}".rstrip()
                   + f"  — {name}")
    if not out:
        return "Ничего не найдено по заданным фильтрам."
    return "\n".join(out)


def tool_get_param(args: Dict) -> str:
    name = args.get("name") or ""
    if not name:
        return "Укажите name — имя параметра."
    return dossier(name, translate=bool(args.get("translate", True)))


def tool_read_map(args: Dict) -> str:
    name = args.get("name") or ""
    if not name:
        return "Укажите name — имя карты."
    return map_text(name, max_cells=int(args.get("max_cells") or 400))


def tool_explain_value(args: Dict) -> str:
    name = args.get("name") or ""
    value = args.get("value")
    if not name or value is None:
        return "Укажите name и value."
    if not wikicache.available():
        return "Справочник не загружен."
    meanings = wikicache.value_meanings(name)
    if not meanings:
        return f"Для {name} в вики нет расшифровки значений."
    try:
        key = int(round(float(value)))
    except (TypeError, ValueError):
        return "value должно быть числом."
    text = meanings.get(key)
    if text is None:
        avail = ", ".join(str(k) for k in sorted(meanings))
        return f"Значения {key} у {name} в вики нет. Есть: {avail}"
    return f"{name} = {key}: {wikitrans.translate_line(text)}\n(оригинал: {text})"


def tool_search_wiki(args: Dict) -> str:
    query = args.get("query") or ""
    if not query:
        return "Укажите query."
    if not wikicache.available():
        return "Справочник не загружен. Обновите: ms43diff wiki --download"
    limit = int(args.get("limit") or 8)
    sections = wikicache.search(query, limit=limit)
    if not sections:
        return "Ничего не найдено."
    translate = bool(args.get("translate", True))
    out: List[str] = []
    for section in sections:
        out.append(f"## {section.page} / {section.heading}")
        body = wikitrans.translate_block(section.text) if translate else section.text
        if len(body) > 1500:
            body = body[:1500].rsplit(" ", 1)[0] + " …"
        out.append(body.strip())
        out.append(f"источник: {section.url}")
        out.append("")
    return "\n".join(out)


def tool_wiki_page(args: Dict) -> str:
    name = args.get("name") or ""
    if not wikicache.available():
        return "Справочник не загружен."
    page = wikicache.page(name)
    if page is None:
        avail = ", ".join(n for n, _, _ in wikicache.page_names())
        return f"Страница не найдена. Есть: {avail}"
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
        return "Справочник не загружен."
    sections = wikicache.cautions(args.get("page"))
    translate = bool(args.get("translate", True))
    out = ["Предупреждения MS4X Wiki («как не убить ничего»):", ""]
    for section in sections:
        out.append(f"• {section.page} / {section.heading}")
        for warning in section.caution_lines:
            w = wikitrans.translate_line(warning) if translate else warning
            out.append(f"  ⚠ {w}")
        out.append(f"  {section.url}")
    return "\n".join(out)


# описание инструментов для tools/list
TOOLS: List[Dict[str, Any]] = [
    {
        "name": "firmware_info",
        "description": "Сведения о загруженной прошивке: версия ПО, XDF, смещение, "
                       "предупреждение о несовпадении версии.",
        "inputSchema": {"type": "object", "properties": {}},
        "_fn": tool_firmware_info,
    },
    {
        "name": "list_categories",
        "description": "Список категорий параметров (Зажигание, VANOS, Впрыск и т.д.) "
                       "с числом параметров в каждой.",
        "inputSchema": {"type": "object", "properties": {}},
        "_fn": tool_list_categories,
    },
    {
        "name": "list_params",
        "description": "Список параметров с их значениями из прошивки. Можно фильтровать "
                       "по категории и по подстроке имени/описания.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "category": {"type": "string", "description": "категория (рус. или англ.)"},
                "filter": {"type": "string", "description": "подстрока имени/описания"},
                "limit": {"type": "integer", "description": "сколько вернуть (по умолч. 60)"},
            },
        },
        "_fn": tool_list_params,
    },
    {
        "name": "get_param",
        "description": "Полное досье по параметру: русское название, значение из прошивки, "
                       "масштаб, адрес, описание, статья MS4X Wiki, расшифровка значений "
                       "и предупреждения. Главный инструмент для разбора настройки.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "имя параметра, напр. c_conf_cat"},
                "translate": {"type": "boolean", "description": "переводить вики (по умолч. да)"},
            },
            "required": ["name"],
        },
        "_fn": tool_get_param,
    },
    {
        "name": "read_map",
        "description": "Карта (таблица) с осями в числах: реальные значения из прошивки "
                       "по оборотам и нагрузке.",
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
        "description": "Что означает конкретное значение переключателя, напр. "
                       "«c_conf_cat = 4» по данным вики.",
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
        "description": "Полнотекстовый поиск по офлайн-копии MS4X Wiki (перевод на русский).",
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
        "description": "Целая страница MS4X Wiki по имени (напр. Siemens_MS43).",
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
        "description": "Все предупреждения из вики — что нельзя ломать. Можно ограничить "
                       "одной страницей.",
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

_TOOL_BY_NAME: Dict[str, Callable[[Dict], str]] = {t["name"]: t["_fn"] for t in TOOLS}


# ---------------------------------------------------------------------------
# JSON-RPC 2.0 по stdio
# ---------------------------------------------------------------------------


def _result(request_id: Any, result: Any) -> Dict:
    return {"jsonrpc": "2.0", "id": request_id, "result": result}


def _error(request_id: Any, code: int, message: str) -> Dict:
    return {"jsonrpc": "2.0", "id": request_id, "error": {"code": code, "message": message}}


def handle(message: Dict) -> Optional[Dict]:
    """Обработать одно JSON-RPC сообщение. None — если ответ не нужен."""
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
        return None  # уведомление, ответа не требует

    if method == "ping":
        return _result(request_id, {})

    if method == "tools/list":
        tools = [{k: v for k, v in t.items() if not k.startswith("_")} for t in TOOLS]
        return _result(request_id, {"tools": tools})

    if method == "tools/call":
        name = params.get("name")
        arguments = params.get("arguments") or {}
        fn = _TOOL_BY_NAME.get(name)
        if fn is None:
            return _error(request_id, -32602, f"Неизвестный инструмент: {name}")
        try:
            text = fn(arguments)
            return _result(request_id, {
                "content": [{"type": "text", "text": text}],
                "isError": False,
            })
        except Exception as exc:  # noqa: BLE001 - отдаём ошибку как результат, не роняем сервер
            _log("ошибка инструмента", name, exc)
            _log(traceback.format_exc())
            return _result(request_id, {
                "content": [{"type": "text", "text": f"Ошибка: {exc}"}],
                "isError": True,
            })

    if request_id is not None:
        return _error(request_id, -32601, f"Метод не поддерживается: {method}")
    return None


def serve(xdf_path: Optional[str], bin_path: Optional[str]) -> int:
    """Запустить stdio-цикл MCP-сервера."""
    global STATE
    STATE = Firmware(xdf_path, bin_path)

    # Протокол — строго UTF-8. Клиент запускает сервер как подпроцесс, и под
    # Windows поток по умолчанию бывает cp1251: без этого кириллица в ответах
    # упадёт с UnicodeEncodeError.
    for stream in (sys.stdin, sys.stdout):
        try:
            stream.reconfigure(encoding="utf-8", newline="\n")
        except (AttributeError, ValueError):
            pass

    _log(f"ms43diff MCP {__version__} запущен. "
         f"XDF={xdf_path or '—'} BIN={bin_path or '—'}")

    stdin = sys.stdin
    stdout = sys.stdout
    for raw in stdin:
        line = raw.strip()
        if not line:
            continue
        try:
            message = json.loads(line)
        except ValueError:
            _log("не JSON:", line[:120])
            continue
        try:
            response = handle(message)
        except Exception as exc:  # noqa: BLE001
            _log("сбой обработки:", exc)
            response = _error(message.get("id"), -32603, str(exc))
        if response is not None:
            stdout.write(json.dumps(response, ensure_ascii=False) + "\n")
            stdout.flush()
    _log("stdin закрыт, выходим")
    return 0
