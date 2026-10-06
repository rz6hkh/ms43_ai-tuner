# -*- coding: utf-8 -*-
"""
Формирование отчётов: консоль, HTML, Markdown, CSV, JSON.

HTML-отчёт самодостаточный (без внешних файлов), с поиском по таблице,
подсветкой знака изменения и тепловой картой для 2D-таблиц.
"""

from __future__ import annotations

import csv
import html
import json
import os
from datetime import datetime
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

from . import heatmap, ru
from .binfile import Reader, format_number
from .compare import Change, CompareResult, PatchStatus
from .crossdiff import (
    ST_DIFF,
    ST_ONLY_A,
    ST_ONLY_B,
    CrossResult,
    CrossRow,
    PortEntry,
    PortPlan,
)
from .xdf import OUT_TEXT, Item, XdfFile

# ---------------------------------------------------------------------------
# Общие помощники
# ---------------------------------------------------------------------------


def item_categories_ru(xdf: XdfFile, item: Item) -> str:
    return ", ".join(ru.category_ru(name) for name in xdf.category_names(item))


# ---------------------------------------------------------------------------
# Подсказки из офлайн-копии MS4X Wiki
# ---------------------------------------------------------------------------


def wiki_sections(title: str):
    """Разделы вики, где упоминается параметр (пусто, если кэша нет)."""
    try:
        from . import wikicache

        if not wikicache.available():
            return []
        return wikicache.sections_for(title)
    except Exception:  # noqa: BLE001 - справочник не должен ломать отчёт
        return []


def value_meanings(title: str) -> Dict[int, str]:
    """Расшифровка значений переключателя из вики: {0: '...', 1: '...'}."""
    try:
        from . import wikicache

        if not wikicache.available():
            return {}
        return wikicache.value_meanings(title)
    except Exception:  # noqa: BLE001
        return {}


def after_change_steps(title: str) -> List[str]:
    try:
        from . import wikicache

        if not wikicache.available():
            return []
        return [translate_wiki(step) for step in wikicache.procedure_for(title)]
    except Exception:  # noqa: BLE001
        return []


def explain_values(title: str, *values: Optional[float]) -> List[Tuple[str, str]]:
    """Пары (значение, что оно значит) для конкретных чисел параметра.

    Именно это отвечает на вопрос «было 4, стало 1 — и что поменялось».
    """
    meanings = value_meanings(title)
    if not meanings:
        return []
    out: List[Tuple[str, str]] = []
    seen = set()
    for value in values:
        if value is None:
            continue
        try:
            key = int(round(float(value)))
        except (TypeError, ValueError):
            continue
        if key in seen:
            continue
        seen.add(key)
        meaning = meanings.get(key)
        meaning = translate_wiki(meaning) if meaning else "в справочнике такого значения нет"
        out.append((str(key), meaning))
    return out


def wiki_notes_text(title: str, max_chars: int = 900) -> List[str]:
    """Текстовый блок «что об этом пишет вики» для консольного вывода."""
    sections = wiki_sections(title)
    if not sections:
        return []
    out = ["", "─── MS4X Wiki (перевод) ───"]
    for section in sections[:2]:
        out.append(f"  {section.page} / {section.heading}")
        text = _focused_ru(section, title)
        if len(text) > max_chars:
            text = text[:max_chars].rsplit(" ", 1)[0] + " …"
        for line in text.split("\n"):
            line = line.strip()
            if not line:
                continue
            while len(line) > 92:
                cut = line.rfind(" ", 0, 92)
                cut = cut if cut > 40 else 92
                out.append(f"    {line[:cut]}")
                line = line[cut:].lstrip()
            out.append(f"    {line}")
        for warning in section.caution_lines[:2]:
            out.append(f"    ⚠ {translate_wiki(warning)[:320]}")
        out.append(f"    {section.url}")
    if len(sections) > 2:
        out.append(f"  (ещё {len(sections) - 2} упоминаний: "
                   f"ms43diff wiki --param {title})")
    return out


def _focused(section, title: str) -> str:
    """Только относящийся к параметру кусок раздела (оригинал, англ.)."""
    try:
        from . import wikicache

        return wikicache.focused_text(section, title)
    except Exception:  # noqa: BLE001
        return section.text


def translate_wiki(text: str) -> str:
    """Перевести кусок текста вики на русский (выверенно + машинно)."""
    try:
        from . import wikitrans

        return wikitrans.translate_block(text)
    except Exception:  # noqa: BLE001 - перевод не должен ломать отчёт
        return text


def _focused_ru(section, title: str) -> str:
    return translate_wiki(_focused(section, title))


def wiki_notes_html(title: str) -> str:
    sections = wiki_sections(title)
    if not sections:
        return ""
    parts = ["<details><summary>что пишет MS4X Wiki "
             f"({len(sections)}) — перевод</summary><div class='wikibox'>"]
    for section in sections[:3]:
        parts.append(f"<div class='wikihead'>{_esc(section.page)} / "
                     f"{_esc(section.heading)}</div>")
        text = _focused(section, title)
        if len(text) > 2200:
            text = text[:2200].rsplit(" ", 1)[0] + " …"
        russian = translate_wiki(text)
        for line in russian.split("\n"):
            if line.strip():
                parts.append(f"<p class='wikitext'>{_esc(line.strip())}</p>")
        for warning in section.caution_lines[:3]:
            parts.append(f"<p class='wikiwarn'>⚠ {_esc(translate_wiki(warning))}</p>")
        parts.append("<details class='orig'><summary>оригинал (English)</summary>")
        for line in text.split("\n"):
            if line.strip():
                parts.append(f"<p class='wikitext'>{_esc(line.strip())}</p>")
        parts.append("</details>")
        parts.append(f"<p class='small'><a href='{_esc(section.url)}'>"
                     f"{_esc(section.url)}</a></p>")
    parts.append("</div></details>")
    return "".join(parts)


def change_row(xdf: XdfFile, change: Change) -> Dict[str, str]:
    """Одна строка отчёта в виде словаря — общая для всех форматов."""
    item = change.item
    info = ru.explain(item.title, item.description)
    units = ru.unit_ru(item.value_units)
    dec = item.value_decimals
    otype = item.value_output_type
    return {
        "title": item.title,
        "name_ru": info["name"],
        "decoded": info["decoded"],
        "desc_ru": info["desc"],
        "desc_en": info["desc_en"],
        "note": info["note"],
        "tune": info["tune"],
        "category": item_categories_ru(xdf, item),
        "shape": item.shape_str,
        "units": units,
        "address": f"0x{item.address:X}" if item.address is not None else "",
        "offset": f"0x{change.offset_a:X}",
        "changed": f"{change.changed_cells}/{change.total_cells}",
        "summary": change.summary(dec, otype),
        "delta_min": format_number(change.delta_min, dec, otype),
        "delta_max": format_number(change.delta_max, dec, otype),
        "delta_avg": format_number(change.delta_avg, dec, otype),
        "pct": f"{change.max_pct:+.1f}" if change.max_pct else "",
        "scaling": item.value_equation.describe_ru(units),
    }


# ---------------------------------------------------------------------------
# Консоль
# ---------------------------------------------------------------------------

_LINE = "─" * 78


def console_report(
    result: CompareResult,
    limit: int = 0,
    verbose: bool = False,
    show_english: bool = False,
) -> str:
    out: List[str] = []
    add = out.append

    add("═" * 78)
    add("  СРАВНЕНИЕ ПРОШИВОК MS43")
    add("═" * 78)
    add(f"Описание XDF : {result.xdf.title}  (v{result.xdf.file_version}, {result.xdf.author})")
    add(f"Файл A       : {result.bin_a.name}  ({result.bin_a.size_kb} КБ)")
    add(f"Файл B       : {result.bin_b.name}  ({result.bin_b.size_kb} КБ)")
    add(f"Смещение     : A {result.reader_a.offset.label} / B {result.reader_b.offset.label}")
    if result.size_mismatch:
        add("ВНИМАНИЕ: файлы разного размера, сравниваются по меньшему.")
    for tag, reader in (("A", result.reader_a), ("B", result.reader_b)):
        warning = reader.version_warning()
        if warning:
            add(f"ВНИМАНИЕ ({tag}): {warning}")
    add("")
    add(f"Параметров изменено : {result.changed_params}")
    add(f"Параметров совпало  : {result.identical}")
    if result.byte_blocks:
        add(
            f"Байт изменено       : {result.total_bytes_changed} "
            f"в {len(result.byte_blocks)} блоках"
        )
        code = result.code_blocks
        if code:
            add(
                f"Блоков вне карт XDF : {len(code)} "
                f"({sum(b.length for b in code)} байт) — это правки кода/патчи"
            )
    if result.skipped:
        add(f"Пропущено           : {len(result.skipped)} (адрес вне файла)")
    add("")

    if not result.changes:
        add("Различий в параметрах, описанных XDF, не найдено.")
        return "\n".join(out)

    # группировка по категориям
    by_cat: Dict[str, List[Change]] = {}
    for change in result.changes:
        cat = item_categories_ru(result.xdf, change.item)
        by_cat.setdefault(cat, []).append(change)

    shown = 0
    for cat in sorted(by_cat, key=lambda c: (-len(by_cat[c]), c)):
        changes = by_cat[cat]
        add(_LINE)
        add(f"  {cat.upper()}  ({len(changes)})")
        add(_LINE)
        for change in changes:
            if limit and shown >= limit:
                add("")
                add(f"... показано {shown} из {result.changed_params}. "
                    f"Используйте --limit 0, чтобы вывести всё.")
                return "\n".join(out)
            shown += 1
            row = change_row(result.xdf, change)
            add(f"• {row['title']}")
            add(f"    {row['name_ru']}")
            if row["desc_ru"]:
                add(f"    Описание: {row['desc_ru']}")
            if show_english and row["desc_en"]:
                add(f"    Оригинал: {row['desc_en']}")
            unit_suffix = f" {row['units']}" if row["units"] else ""
            add(f"    Значение: {row['summary']}{unit_suffix}")
            add(
                f"    Тип: {row['shape']} | адрес XDF {row['address']} "
                f"| файл {row['offset']} | {row['scaling']}"
            )
            # Расшифровка конкретных чисел: «было 4 = …, стало 1 = …»
            if change.is_scalar and change.cells:
                for value, meaning in explain_values(
                    row["title"], change.cells[0].val_a, change.cells[0].val_b
                ):
                    add(f"      {value} = {meaning}")
                for step in after_change_steps(row["title"]):
                    add(f"    После изменения: {step}")
            if row["note"]:
                add(f"    Что это: {row['note']}")
            if row["tune"]:
                add(f"    Как крутить: {row['tune']}")
            for line in wiki_notes_text(row["title"], max_chars=500):
                add(f"  {line}")
            if verbose and not change.is_scalar:
                add(_cells_block(change, indent="      "))
            add("")

    if result.code_blocks:
        add(_LINE)
        add("  ИЗМЕНЕНИЯ ВНЕ ОПИСАННЫХ ПАРАМЕТРОВ (код / патчи)")
        add(_LINE)
        for block in result.code_blocks[:40]:
            add(f"  0x{block.start:06X}–0x{block.end:06X}  ({block.length} байт)")
        if len(result.code_blocks) > 40:
            add(f"  ... и ещё {len(result.code_blocks) - 40} блоков")
        add("")

    return "\n".join(out)


def _cells_block(change: Change, indent: str = "  ", max_cells: int = 40) -> str:
    item = change.item
    dec = item.value_decimals
    otype = item.value_output_type
    lines = [f"{indent}изменённые ячейки:"]
    for cell in change.cells[:max_cells]:
        pos = f"[{cell.row}][{cell.col}]" if item.rows > 1 and item.cols > 1 else f"[{max(cell.row, cell.col)}]"
        a = format_number(cell.val_a, dec, otype)
        b = format_number(cell.val_b, dec, otype)
        d = format_number(cell.delta, dec, otype)
        sign = "+" if cell.delta > 0 else ""
        lines.append(f"{indent}  {pos:>10}  {a:>10} -> {b:>10}   ({sign}{d})")
    if len(change.cells) > max_cells:
        lines.append(f"{indent}  ... и ещё {len(change.cells) - max_cells} ячеек")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Печать одной карты
# ---------------------------------------------------------------------------


def render_table(reader: Reader, item: Item, reader_b: Optional[Reader] = None) -> str:
    """Красиво напечатать карту с осями; при reader_b — рядом с дельтой."""
    xdf = reader.xdf
    info = ru.explain(item.title, item.description)
    units = ru.unit_ru(item.value_units)
    dec = item.value_decimals
    otype = item.value_output_type

    out: List[str] = []
    out.append("═" * 78)
    out.append(f"  {item.title}")
    out.append("═" * 78)
    out.append(f"Расшифровка : {info['name']}")
    if info["decoded"] != info["name"]:
        out.append(f"По словарю  : {info['decoded']}")
    out.append(f"Тип         : {info['kind']} | {item.shape_str}")
    out.append(f"Категория   : {item_categories_ru(xdf, item)}")
    if info["desc"]:
        out.append(f"Описание    : {info['desc']}")
    if info["desc_en"]:
        out.append(f"Оригинал    : {info['desc_en']}")
    if info["note"]:
        out.append(f"Что делает  : {info['note']}")
    if info["tune"]:
        out.append(f"Как крутить : {info['tune']}")
    data = item.data
    if data is not None and data.address is not None:
        out.append(
            f"Адрес       : XDF 0x{data.address:X} -> файл 0x{reader.file_offset(data.address):X}"
            f", {data.size_bits} бит, "
            f"{'со знаком' if data.signed else 'без знака'}, "
            f"{'little-endian' if data.lsb_first else 'big-endian'}"
        )
    out.append(f"Единицы     : {units or '—'}")
    out.append(f"Масштаб     : {item.value_equation.describe_ru(units)}")
    for line in wiki_notes_text(item.title):
        out.append(line)
    out.append("")

    values = reader.matrix(item)
    if values is None:
        out.append("Не удалось прочитать значения (адрес вне файла).")
        return "\n".join(out)

    values_b = reader_b.matrix(item) if reader_b is not None else None
    x_axis = reader.axis_values(item, "x")
    y_axis = reader.axis_values(item, "y")

    x_units = ru.unit_ru(item.axis_x.units) if item.axis_x else ""
    y_units = ru.unit_ru(item.axis_y.units) if item.axis_y else ""

    cols = item.cols
    rows = item.rows

    # подписи осей: сначала из имени, единицы — из самого XDF
    y_name, x_name = ru.axis_names_ru(item.title)
    if cols > 1 and rows == 1 and y_name and not x_name:
        y_name, x_name = "", y_name  # у 1D-таблицы по столбцам ось одна

    def axis_caption(name: str, units: str, fallback: str) -> str:
        caption = name or fallback
        if units and units.lower() not in caption.lower():
            caption += f" [{units}]"
        return caption

    def fmt(v: float) -> str:
        return format_number(v, dec, otype)

    # шапка
    col_labels = []
    for c in range(cols):
        if x_axis and c < len(x_axis):
            col_labels.append(format_number(x_axis[c], item.axis_x.decimals if item.axis_x else 0, 1))
        else:
            col_labels.append(str(c))
    width = max(9, max((len(s) for s in col_labels), default=6) + 1)
    row_label_w = 10

    if rows > 1:
        out.append(f"Строки  (Y): {axis_caption(y_name, y_units, 'индекс')}")
    if cols > 1:
        out.append(f"Столбцы (X): {axis_caption(x_name, x_units, 'индекс')}")
        out.append("")
        header = " " * row_label_w + "".join(f"{lbl:>{width}}" for lbl in col_labels)
        out.append(header)
        out.append(" " * row_label_w + "-" * (width * cols))

    for r in range(rows):
        if y_axis and r < len(y_axis):
            label = format_number(y_axis[r], item.axis_y.decimals if item.axis_y else 0, 1)
        else:
            label = str(r)
        cells = []
        for c in range(cols):
            a = values[r][c]
            if values_b is None:
                cells.append(f"{fmt(a):>{width}}")
            else:
                b = values_b[r][c]
                if a == b:
                    cells.append(f"{fmt(a):>{width}}")
                else:
                    cells.append(f"{fmt(b) + '*':>{width}}")
        out.append(f"{label:>{row_label_w - 1}} |" + "".join(cells))

    if values_b is not None:
        out.append("")
        out.append("* — значение отличается во втором файле (показано значение из B)")
    return "\n".join(out)


# ---------------------------------------------------------------------------
# CSV / JSON / Markdown
# ---------------------------------------------------------------------------

CSV_FIELDS = [
    ("title", "Имя в XDF"),
    ("name_ru", "Название"),
    ("category", "Категория"),
    ("desc_ru", "Описание (RU)"),
    ("desc_en", "Описание (EN)"),
    ("shape", "Тип"),
    ("units", "Единицы"),
    ("address", "Адрес XDF"),
    ("offset", "Смещение в файле"),
    ("changed", "Изменено ячеек"),
    ("summary", "Было -> Стало"),
    ("delta_min", "Дельта мин"),
    ("delta_max", "Дельта макс"),
    ("delta_avg", "Дельта средн"),
    ("pct", "Макс. изменение, %"),
    ("scaling", "Масштаб"),
    ("note", "Что это"),
    ("tune", "Как крутить"),
]


def write_csv(result: CompareResult, path: str) -> None:
    with open(path, "w", encoding="utf-8-sig", newline="") as fh:
        writer = csv.writer(fh, delimiter=";")
        writer.writerow([title for _, title in CSV_FIELDS])
        for change in result.changes:
            row = change_row(result.xdf, change)
            writer.writerow([row.get(key, "") for key, _ in CSV_FIELDS])


def write_json(result: CompareResult, path: str) -> None:
    payload = {
        "xdf": {
            "path": result.xdf.path,
            "title": result.xdf.title,
            "version": result.xdf.file_version,
        },
        "bin_a": {"path": result.bin_a.path, "size": len(result.bin_a)},
        "bin_b": {"path": result.bin_b.path, "size": len(result.bin_b)},
        "offset_a": result.reader_a.offset.label,
        "offset_b": result.reader_b.offset.label,
        "stats": {
            "changed": result.changed_params,
            "identical": result.identical,
            "bytes_changed": result.total_bytes_changed,
            "blocks": len(result.byte_blocks),
            "code_blocks": len(result.code_blocks),
        },
        "changes": [],
        "code_blocks": [
            {"start": f"0x{b.start:X}", "end": f"0x{b.end:X}", "length": b.length}
            for b in result.code_blocks
        ],
    }
    for change in result.changes:
        row = change_row(result.xdf, change)
        item = change.item
        dec, otype = item.value_decimals, item.value_output_type
        row["cells"] = [
            {
                "row": c.row,
                "col": c.col,
                "raw_a": c.raw_a,
                "raw_b": c.raw_b,
                "a": format_number(c.val_a, dec, otype),
                "b": format_number(c.val_b, dec, otype),
                "delta": format_number(c.delta, dec, otype),
            }
            for c in change.cells
        ]
        payload["changes"].append(row)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, ensure_ascii=False, indent=2)


def write_markdown(result: CompareResult, path: str) -> None:
    lines: List[str] = []
    lines.append(f"# Сравнение прошивок MS43")
    lines.append("")
    lines.append(f"* **A:** `{result.bin_a.name}`")
    lines.append(f"* **B:** `{result.bin_b.name}`")
    lines.append(f"* **XDF:** {result.xdf.title} (v{result.xdf.file_version})")
    lines.append(f"* **Изменено параметров:** {result.changed_params}")
    lines.append(f"* **Изменено байт:** {result.total_bytes_changed}")
    lines.append("")

    by_cat: Dict[str, List[Change]] = {}
    for change in result.changes:
        by_cat.setdefault(item_categories_ru(result.xdf, change.item), []).append(change)

    for cat in sorted(by_cat, key=lambda c: (-len(by_cat[c]), c)):
        lines.append(f"## {cat}")
        lines.append("")
        lines.append("| Параметр | Что это | Было → Стало | Ед. |")
        lines.append("|---|---|---|---|")
        for change in by_cat[cat]:
            row = change_row(result.xdf, change)
            desc = row["desc_ru"] or row["name_ru"]
            desc = desc.replace("|", "\\|").replace("\n", " ")
            lines.append(
                f"| `{row['title']}` | {desc} | {row['summary']} | {row['units']} |"
            )
        lines.append("")

    if result.code_blocks:
        lines.append("## Правки вне карт XDF (код / патчи)")
        lines.append("")
        lines.append("| Смещение | Длина |")
        lines.append("|---|---|")
        for block in result.code_blocks:
            lines.append(f"| 0x{block.start:06X}–0x{block.end:06X} | {block.length} |")
        lines.append("")

    with open(path, "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines))


# ---------------------------------------------------------------------------
# HTML
# ---------------------------------------------------------------------------

_HTML_HEAD = """<!doctype html>
<html lang="ru"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title}</title>
<style>
:root{{--bg:#ffffff;--fg:#1b1f24;--muted:#5c6672;--line:#e3e7eb;--card:#f7f9fb;
--pos:#0a7f3f;--neg:#b3261e;--accent:#0b5cad;}}
@media (prefers-color-scheme: dark){{:root{{--bg:#12161a;--fg:#e6eaee;--muted:#9aa5b1;
--line:#2a3239;--card:#1a2027;--pos:#4ade80;--neg:#f87171;--accent:#60a5fa;}}}}
*{{box-sizing:border-box}}
body{{margin:0;padding:24px;background:var(--bg);color:var(--fg);
font:15px/1.55 -apple-system,Segoe UI,Roboto,Helvetica,Arial,sans-serif}}
h1{{font-size:24px;margin:0 0 4px}} h2{{font-size:18px;margin:32px 0 8px;
border-bottom:1px solid var(--line);padding-bottom:6px}}
.meta{{color:var(--muted);font-size:13px;margin-bottom:20px}}
.stats{{display:flex;flex-wrap:wrap;gap:10px;margin:16px 0 24px}}
.stat{{background:var(--card);border:1px solid var(--line);border-radius:10px;
padding:10px 16px;min-width:130px}}
.stat b{{display:block;font-size:22px}} .stat span{{color:var(--muted);font-size:12px}}
input[type=search]{{width:100%;max-width:460px;padding:9px 12px;border:1px solid var(--line);
border-radius:8px;background:var(--card);color:var(--fg);font-size:14px;margin-bottom:16px}}
.wrap{{overflow-x:auto}}
table{{border-collapse:collapse;width:100%;font-size:13.5px}}
th,td{{border-bottom:1px solid var(--line);padding:8px 10px;text-align:left;vertical-align:top}}
th{{background:var(--card);position:sticky;top:0;font-weight:600;font-size:12.5px;
text-transform:uppercase;letter-spacing:.03em;color:var(--muted)}}
tr:hover td{{background:var(--card)}}
code{{font:12.5px/1.4 ui-monospace,Consolas,monospace;background:var(--card);
padding:1px 5px;border-radius:4px}}
.pos{{color:var(--pos);font-weight:600}} .neg{{color:var(--neg);font-weight:600}}
.small{{color:var(--muted);font-size:12px}}
.tune{{background:var(--card);border-left:3px solid var(--accent);padding:6px 10px;
margin-top:6px;border-radius:0 6px 6px 0;font-size:12.5px}}
.badge{{display:inline-block;padding:1px 7px;border-radius:20px;background:var(--card);
border:1px solid var(--line);font-size:11.5px;color:var(--muted)}}
details{{margin-top:8px}}
summary{{cursor:pointer;color:var(--accent);font-size:12.5px;user-select:none}}
tr.maprow td{{padding:0 10px 14px;border-bottom:1px solid var(--line)}}
tr.maprow:hover td{{background:transparent}}
.wikibox{{background:var(--card);border:1px solid var(--line);border-radius:8px;
padding:8px 12px;margin-top:6px;max-height:520px;overflow:auto}}
section>.wikibox{{max-height:none}}
.wikihead{{font-weight:600;font-size:12px;margin:6px 0 3px;color:var(--accent)}}
.wikitext{{margin:3px 0;font-size:12px;line-height:1.45}}
.wikiwarn{{margin:5px 0;font-size:12px;padding:5px 8px;border-radius:5px;
background:rgba(200,80,40,.12);border-left:3px solid #c8502a}}
.values{{background:var(--card);border-left:3px solid var(--pos);padding:6px 10px;
margin-top:6px;border-radius:0 6px 6px 0;font-size:12.5px}}
.values ul,.tune ul{{margin:4px 0 0;padding-left:20px}}
.values li,.tune li{{margin:2px 0}}
details.orig{{margin:4px 0 8px}}
details.orig summary{{font-size:11.5px;color:var(--muted)}}
details.orig .wikitext{{color:var(--muted);font-size:11.5px}}
.mapwrap{{margin:10px 0 4px;overflow-x:auto}}
.mapcap{{margin-bottom:6px}}
table.map{{border-collapse:separate;border-spacing:1px;width:auto;font:11.5px/1.15
ui-monospace,Consolas,monospace;table-layout:fixed}}
table.map th{{background:transparent;color:var(--muted);font-weight:600;
text-transform:none;letter-spacing:0;padding:2px 4px;text-align:right;
position:static;font-size:11px;white-space:nowrap}}
table.map th.ylab{{text-align:right;padding-right:6px}}
table.map th.corner{{background:transparent}}
table.map td{{padding:3px 5px;text-align:right;border:0;border-radius:3px;
min-width:44px;white-space:nowrap}}
table.map td .d{{display:block;font-size:9.5px;opacity:.85}}
.legend{{display:flex;flex-wrap:wrap;align-items:center;gap:3px;margin-top:6px}}
.legend .chip{{padding:2px 7px;border-radius:3px;font:11px ui-monospace,Consolas,monospace}}
.legend .small{{margin-right:6px}}
@media print{{
  body{{padding:0}} th{{position:static}}
  section{{break-inside:avoid}} details{{display:block}} details>summary{{display:none}}
  .mapwrap{{overflow:visible}} input[type=search]{{display:none}}
}}
</style></head><body>
"""

_HTML_TAIL = """
<script>
const q=document.getElementById('q');
if(q){q.addEventListener('input',()=>{
 const v=q.value.toLowerCase().trim();
 document.querySelectorAll('tbody tr').forEach(tr=>{
   tr.style.display = !v || tr.innerText.toLowerCase().includes(v) ? '' : 'none';});
 document.querySelectorAll('section').forEach(s=>{
   const any=[...s.querySelectorAll('tbody tr')].some(tr=>tr.style.display!=='none');
   s.style.display = any ? '' : 'none';});
});}
</script></body></html>
"""


def _esc(text: str) -> str:
    return html.escape(text or "", quote=False)


# ---------------------------------------------------------------------------
# Тепловая карта в HTML
# ---------------------------------------------------------------------------


def _axis_labels(reader: Reader, item: Item, which: str) -> List[str]:
    axis = item.axis_x if which == "x" else item.axis_y
    count = item.cols if which == "x" else item.rows
    values = reader.axis_values(item, which)
    if not values:
        return [str(i) for i in range(count)]
    decimals = axis.decimals if axis else 0
    return [format_number(v, decimals, 1) for v in values[:count]]


def render_map_html(reader: Reader, item: Item,
                    reader_b: Optional[Reader] = None) -> str:
    """Карта как цветная таблица.

    Без второго файла — раскраска по значению (последовательная шкала).
    С двумя файлами — раскраска по величине изменения (расходящаяся шкала,
    ноль нейтральный), в ячейке новое значение и дельта.
    """
    before = reader.matrix(item)
    if not before:
        return "<p class='small'>Не удалось прочитать значения.</p>"
    after = reader_b.matrix(item) if reader_b is not None else None
    dec, otype = item.value_decimals, item.value_output_type
    units = ru.unit_ru(item.value_units)

    x_labels = _axis_labels(reader, item, "x")
    y_labels = _axis_labels(reader, item, "y")
    y_name, x_name = ru.axis_names_ru(item.title)
    x_units = ru.unit_ru(item.axis_x.units) if item.axis_x else ""
    y_units = ru.unit_ru(item.axis_y.units) if item.axis_y else ""

    parts: List[str] = ["<div class='mapwrap'>"]
    caption = []
    if item.rows > 1:
        caption.append(f"строки — {_esc(y_name or 'индекс')}"
                       + (f" [{_esc(y_units)}]" if y_units else ""))
    if item.cols > 1:
        caption.append(f"столбцы — {_esc(x_name or 'индекс')}"
                       + (f" [{_esc(x_units)}]" if x_units else ""))
    if caption:
        parts.append(f"<div class='small mapcap'>{' · '.join(caption)}</div>")

    parts.append("<table class='map'><thead><tr><th class='corner'></th>")
    for label in x_labels:
        parts.append(f"<th>{_esc(label)}</th>")
    parts.append("</tr></thead><tbody>")

    if after is not None:
        scale = heatmap.delta_scale(before, after)
    else:
        low, high = heatmap.value_range(before)

    for r in range(item.rows):
        parts.append(f"<tr><th class='ylab'>{_esc(y_labels[r])}</th>")
        for c in range(item.cols):
            a = before[r][c]
            if after is not None:
                b = after[r][c]
                delta = b - a
                bg = heatmap.delta_color(delta, scale)
                fg = heatmap.text_color(bg)
                main = format_number(b, dec, otype)
                if delta:
                    sign = "+" if delta > 0 else ""
                    extra = (f"<span class='d'>{sign}"
                             f"{_esc(format_number(delta, dec, otype))}</span>")
                    title = (f"было {format_number(a, dec, otype)}, "
                             f"стало {main} {units}")
                else:
                    extra = ""
                    title = f"{main} {units} — без изменений"
            else:
                bg = heatmap.value_color(a, low, high)
                fg = heatmap.text_color(bg)
                main = format_number(a, dec, otype)
                extra = ""
                title = f"{main} {units}"
            parts.append(
                f"<td style='background:{heatmap.hex_color(bg)};"
                f"color:{heatmap.hex_color(fg)}' title='{_esc(title)}'>"
                f"{_esc(main)}{extra}</td>"
            )
        parts.append("</tr>")
    parts.append("</tbody></table>")

    # шкала
    if after is not None:
        stops = heatmap.delta_legend_stops(scale)
        legend_title = f"изменение, {units}" if units else "изменение"
    else:
        stops = heatmap.legend_stops(low, high)
        legend_title = f"значение, {units}" if units else "значение"
    parts.append(f"<div class='legend'><span class='small'>{_esc(legend_title)}:</span>")
    for value, rgb in stops:
        fg = heatmap.text_color(rgb)
        parts.append(
            f"<span class='chip' style='background:{heatmap.hex_color(rgb)};"
            f"color:{heatmap.hex_color(fg)}'>"
            f"{_esc(format_number(value, dec, otype))}</span>"
        )
    parts.append("</div></div>")
    return "".join(parts)


def write_html(result: CompareResult, path: str) -> None:
    title = f"MS43: {result.bin_a.name} ↔ {result.bin_b.name}"
    parts: List[str] = [_HTML_HEAD.format(title=_esc(title))]
    add = parts.append

    add(f"<h1>Сравнение прошивок MS43</h1>")
    add(
        f"<div class='meta'>A: <code>{_esc(result.bin_a.name)}</code> "
        f"({result.bin_a.size_kb} КБ) &nbsp;↔&nbsp; "
        f"B: <code>{_esc(result.bin_b.name)}</code> ({result.bin_b.size_kb} КБ)<br>"
        f"XDF: {_esc(result.xdf.title)} v{_esc(result.xdf.file_version)} · "
        f"{_esc(result.xdf.author)} · смещение {_esc(result.reader_a.offset.label)}<br>"
        f"Отчёт создан {datetime.now():%d.%m.%Y %H:%M}</div>"
    )

    add("<div class='stats'>")
    add(f"<div class='stat'><b>{result.changed_params}</b><span>параметров изменено</span></div>")
    add(f"<div class='stat'><b>{result.identical}</b><span>параметров совпало</span></div>")
    add(f"<div class='stat'><b>{result.total_bytes_changed}</b><span>байт изменено</span></div>")
    add(f"<div class='stat'><b>{len(result.code_blocks)}</b><span>блоков правок кода</span></div>")
    add("</div>")

    add("<input type='search' id='q' placeholder='Поиск по параметрам, описаниям, адресам…'>")

    by_cat: Dict[str, List[Change]] = {}
    for change in result.changes:
        by_cat.setdefault(item_categories_ru(result.xdf, change.item), []).append(change)

    for cat in sorted(by_cat, key=lambda c: (-len(by_cat[c]), c)):
        changes = by_cat[cat]
        add(f"<section><h2>{_esc(cat)} <span class='badge'>{len(changes)}</span></h2>")
        add("<div class='wrap'><table><thead><tr>"
            "<th>Параметр</th><th>Что это</th><th>Было → Стало</th>"
            "<th>Δ</th><th>Адрес</th></tr></thead><tbody>")
        for change in changes:
            row = change_row(result.xdf, change)
            delta_cls = ""
            if change.max_pct > 0:
                delta_cls = "pos"
            elif change.max_pct < 0:
                delta_cls = "neg"
            delta_txt = row["pct"] + " %" if row["pct"] else "—"

            desc_html = _esc(row["desc_ru"] or row["name_ru"])
            extra = ""
            if row["desc_ru"] and row["name_ru"] and row["desc_ru"] != row["name_ru"]:
                extra = f"<div class='small'>{_esc(row['name_ru'])}</div>"
            if row["note"]:
                extra += f"<div class='tune'><b>Что делает:</b> {_esc(row['note'])}</div>"
            if row["tune"]:
                extra += f"<div class='tune'><b>Как крутить:</b> {_esc(row['tune'])}</div>"
            if row["desc_en"]:
                extra += f"<div class='small'>EN: {_esc(row['desc_en'])}</div>"
            if change.is_scalar and change.cells:
                pairs = explain_values(row["title"], change.cells[0].val_a,
                                       change.cells[0].val_b)
                if pairs:
                    extra += "<div class='values'><b>Что означают значения:</b><ul>"
                    for value, meaning in pairs:
                        extra += f"<li><code>{_esc(value)}</code> — {_esc(meaning)}</li>"
                    extra += "</ul></div>"
                steps = after_change_steps(row["title"])
                if steps:
                    extra += ("<div class='tune'><b>После изменения нужно:</b><ul>"
                              + "".join(f"<li>{_esc(s)}</li>" for s in steps)
                              + "</ul></div>")
            extra += wiki_notes_html(change.item.title)

            add(
                "<tr>"
                f"<td><code>{_esc(row['title'])}</code>"
                f"<div class='small'>{_esc(row['shape'])} · {_esc(row['scaling'])}</div></td>"
                f"<td>{desc_html}{extra}</td>"
                f"<td>{_esc(row['summary'])} <span class='small'>{_esc(row['units'])}</span>"
                f"<div class='small'>изменено {_esc(row['changed'])} яч.</div></td>"
                f"<td class='{delta_cls}'>{_esc(delta_txt)}</td>"
                f"<td><code>{_esc(row['address'])}</code>"
                f"<div class='small'>файл {_esc(row['offset'])}</div></td>"
                "</tr>"
            )

            # Саму карту кладём отдельной строкой во всю ширину: в узкой
            # колонке её невозможно читать, а ради неё отчёт и делается.
            if change.item.cell_count > 1 and change.item.value_output_type != OUT_TEXT:
                opened = " open" if change.item.cell_count <= 256 else ""
                add(
                    f"<tr class='maprow'><td colspan='5'>"
                    f"<details{opened}><summary>карта "
                    f"{_esc(change.item.shape_str)} — изменено "
                    f"{change.changed_cells} из {change.total_cells} ячеек</summary>"
                    + render_map_html(result.reader_a, change.item, result.reader_b)
                    + "</details></td></tr>"
                )
        add("</tbody></table></div></section>")

    if result.code_blocks:
        add("<section><h2>Правки вне карт XDF (код / патчи) "
            f"<span class='badge'>{len(result.code_blocks)}</span></h2>")
        add("<div class='wrap'><table><thead><tr><th>Смещение</th><th>Длина, байт</th>"
            "<th>Комментарий</th></tr></thead><tbody>")
        for block in result.code_blocks:
            add(
                f"<tr><td><code>0x{block.start:06X}–0x{block.end:06X}</code></td>"
                f"<td>{block.length}</td>"
                f"<td class='small'>не описано в XDF — вероятно, правка машинного кода</td></tr>"
            )
        add("</tbody></table></div></section>")

    add(_HTML_TAIL)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write("\n".join(parts))


# ---------------------------------------------------------------------------
# Отчёт по патчам
# ---------------------------------------------------------------------------

_PATCH_MARK = {
    "применён": "[+]",
    "не применён": "[ ]",
    "частично": "[~]",
    "изменён": "[?]",
    "вне файла": "[x]",
}


# ---------------------------------------------------------------------------
# Сравнение разных версий ПО
# ---------------------------------------------------------------------------


def _row_name(title: str, description: str = "") -> str:
    info = ru.explain(title, description)
    return info["name"]


def cross_console_report(result: CrossResult, limit: int = 60) -> str:
    out: List[str] = []
    add = out.append
    add("═" * 78)
    add("  СРАВНЕНИЕ РАЗНЫХ ВЕРСИЙ ПО (сопоставление по именам параметров)")
    add("═" * 78)
    add(f"A: {result.bin_a.name}")
    add(f"   XDF {result.xdf_a.title} v{result.xdf_a.file_version}, "
        f"версия ПО {result.reader_a.firmware_id() or '?'}")
    add(f"B: {result.bin_b.name}")
    add(f"   XDF {result.xdf_b.title} v{result.xdf_b.file_version}, "
        f"версия ПО {result.reader_b.firmware_id() or '?'}")
    add("")
    add(f"Совпадает по значению : {result.identical}")
    add(f"Отличается            : {len(result.different)}")
    add(f"Есть только в A       : {len(result.only_a)}")
    add(f"Есть только в B       : {len(result.only_b)}")
    if result.problems:
        add(f"Проблемных            : {len(result.problems)}")
    add("")
    add("Сравниваются физические величины, а не байты: у разных версий ПО")
    add("формулы пересчёта могут отличаться.")
    add("")

    shown = 0
    for row in result.different:
        if limit and shown >= limit:
            add(f"... показано {shown} из {len(result.different)}. "
                f"Используйте --limit 0 для полного списка.")
            break
        shown += 1
        item = row.item
        units = ru.unit_ru(item.value_units) if item else ""
        add(f"• {row.title}")
        add(f"    {_row_name(row.title, item.description if item else '')}")
        add(f"    {row.summary()} {units}".rstrip())
        for note in row.notes:
            add(f"    ! {note}")
        add("")

    if result.only_a:
        add(_LINE)
        add(f"  ЕСТЬ ТОЛЬКО В A ({len(result.only_a)}) — в целевой версии этих настроек нет")
        add(_LINE)
        for row in result.only_a[:30]:
            add(f"  {row.title}  — {_row_name(row.title)}")
        if len(result.only_a) > 30:
            add(f"  ... и ещё {len(result.only_a) - 30}")
        add("")
    if result.only_b:
        add(_LINE)
        add(f"  ЕСТЬ ТОЛЬКО В B ({len(result.only_b)}) — новые настройки целевой версии")
        add(_LINE)
        for row in result.only_b[:30]:
            add(f"  {row.title}  — {_row_name(row.title)}")
        if len(result.only_b) > 30:
            add(f"  ... и ещё {len(result.only_b) - 30}")
        add("")
    return "\n".join(out)


def write_cross_html(result: CrossResult, path: str) -> None:
    title = f"MS43: {result.bin_a.name} ↔ {result.bin_b.name} (разные версии)"
    parts: List[str] = [_HTML_HEAD.format(title=_esc(title))]
    add = parts.append
    add("<h1>Сравнение разных версий ПО</h1>")
    add(
        f"<div class='meta'>A: <code>{_esc(result.bin_a.name)}</code> · "
        f"{_esc(result.xdf_a.title)} · ПО {_esc(result.reader_a.firmware_id() or '?')}<br>"
        f"B: <code>{_esc(result.bin_b.name)}</code> · "
        f"{_esc(result.xdf_b.title)} · ПО {_esc(result.reader_b.firmware_id() or '?')}<br>"
        f"Параметры сопоставлены по именам; сравниваются физические величины.<br>"
        f"Отчёт создан {datetime.now():%d.%m.%Y %H:%M}</div>"
    )
    add("<div class='stats'>")
    add(f"<div class='stat'><b>{len(result.different)}</b><span>отличается</span></div>")
    add(f"<div class='stat'><b>{result.identical}</b><span>совпадает</span></div>")
    add(f"<div class='stat'><b>{len(result.only_a)}</b><span>только в A</span></div>")
    add(f"<div class='stat'><b>{len(result.only_b)}</b><span>только в B</span></div>")
    add("</div>")
    add("<input type='search' id='q' placeholder='Поиск…'>")

    def table(rows: List[CrossRow], heading: str) -> None:
        if not rows:
            return
        add(f"<section><h2>{_esc(heading)} <span class='badge'>{len(rows)}</span></h2>")
        add("<div class='wrap'><table><thead><tr><th>Параметр</th><th>Что это</th>"
            "<th>Значения</th><th>Замечания</th></tr></thead><tbody>")
        for row in rows:
            item = row.item
            units = ru.unit_ru(item.value_units) if item else ""
            notes = "<br>".join(_esc(n) for n in row.notes)
            add(
                f"<tr><td><code>{_esc(row.title)}</code></td>"
                f"<td>{_esc(_row_name(row.title, item.description if item else ''))}</td>"
                f"<td>{_esc(row.summary())} <span class='small'>{_esc(units)}</span></td>"
                f"<td class='small'>{notes}</td></tr>"
            )
        add("</tbody></table></div></section>")

    table(result.different, "Отличаются")
    table(result.only_a, "Есть только в A")
    table(result.only_b, "Есть только в B")
    table(result.problems, "Проблемные")
    add(_HTML_TAIL)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write("\n".join(parts))


# ---------------------------------------------------------------------------
# План переноса настроек
# ---------------------------------------------------------------------------

_PORT_WARNING = (
    "ВАЖНО: программа только строит план и ничего не пишет в прошивку. Все "
    "правки вносите руками в TunerPro; контрольные суммы пересчитайте там же."
)


def port_console_report(plan: PortPlan, limit: int = 0, verbose: bool = False) -> str:
    out: List[str] = []
    add = out.append
    add("═" * 78)
    add("  ПЛАН ПЕРЕНОСА НАСТРОЕК МЕЖДУ ВЕРСИЯМИ ПО")
    add("═" * 78)
    add(f"Сток исходной версии : {plan.bin_stock.name}")
    add(f"Ваш тюнинг           : {plan.bin_tuned.name}")
    add(f"XDF исходной версии  : {plan.xdf_src.title} v{plan.xdf_src.file_version}")
    add(f"Целевая прошивка     : {plan.bin_target.name}")
    add(f"XDF целевой версии   : {plan.xdf_dst.title} v{plan.xdf_dst.file_version}")
    add("")
    add(f"Вы изменили параметров : {len(plan.entries)}")
    add(f"Безопасно (по байтам)  : {len(plan.safe_bytes)}")
    add(f"Безопасно (по имени)   : {len(plan.safe_name)}")
    add(f"Под предупреждением    : {len(plan.warned)}")
    add("")
    add(_PORT_WARNING)
    add("")

    def block(title: str, entries):
        if not entries:
            return
        add(_LINE)
        add(f"  {title} ({len(entries)})")
        add(_LINE)
        shown = 0
        for entry in entries:
            if limit and shown >= limit:
                add(f"  ... показано {shown} из {len(entries)}")
                break
            shown += 1
            item = entry.item_dst or entry.item_src
            units = ru.unit_ru(item.value_units) if item else ""
            add(f"• {entry.title}  — {entry.status}")
            add(f"    {_row_name(entry.title, item.description if item else '')}")
            add(f"    {entry.summary()} {units}".rstrip())
            add(f"    {entry.detail()}")
            add("")

    block("БЕЗОПАСНО — можно перенести один в один", plan.safe_bytes)
    block("БЕЗОПАСНО ПО ИМЕНИ — переносить физическую величину руками", plan.safe_name)
    block("ПРЕДУПРЕЖДЕНИЕ — разбирайтесь вручную", plan.warned)
    add("Всё переносится руками в TunerPro — программа только показывает план.")
    return "\n".join(out)


def write_port_html(plan: PortPlan, path: str) -> None:
    title = f"Перенос настроек: {plan.xdf_src.title} → {plan.xdf_dst.title}"
    parts: List[str] = [_HTML_HEAD.format(title=_esc(title))]
    add = parts.append
    add("<h1>План переноса настроек между версиями ПО</h1>")
    add(
        f"<div class='meta'>"
        f"Сток исходной: <code>{_esc(plan.bin_stock.name)}</code><br>"
        f"Ваш тюнинг: <code>{_esc(plan.bin_tuned.name)}</code> "
        f"({_esc(plan.xdf_src.title)})<br>"
        f"Целевая: <code>{_esc(plan.bin_target.name)}</code> "
        f"({_esc(plan.xdf_dst.title)})<br>"
        f"Отчёт создан {datetime.now():%d.%m.%Y %H:%M}</div>"
    )
    add("<div class='tune'><b>Программа только строит план и ничего не пишет в "
        "прошивку. Все правки вносите руками в TunerPro; контрольные суммы "
        "пересчитайте там же.</b></div>")
    add("<div class='stats'>")
    add(f"<div class='stat'><b>{len(plan.safe_bytes)}</b><span>безопасно по байтам</span></div>")
    add(f"<div class='stat'><b>{len(plan.safe_name)}</b><span>безопасно по имени</span></div>")
    add(f"<div class='stat'><b>{len(plan.warned)}</b><span>под предупреждением</span></div>")
    add("</div>")
    add("<input type='search' id='q' placeholder='Поиск…'>")

    def table(entries: List[PortEntry], heading: str) -> None:
        if not entries:
            return
        add(f"<section><h2>{_esc(heading)} <span class='badge'>{len(entries)}</span></h2>")
        add("<div class='wrap'><table><thead><tr><th>Параметр</th><th>Что это</th>"
            "<th>Значения</th><th>Чем совпало / что не так</th>"
            "</tr></thead><tbody>")
        for entry in entries:
            item = entry.item_dst or entry.item_src
            units = ru.unit_ru(item.value_units) if item else ""
            bits = entry.match_bits if entry.safe else entry.warn_bits
            detail = "<br>".join(_esc(b) for b in bits)
            add(
                f"<tr><td><code>{_esc(entry.title)}</code>"
                f"<div class='small'>{_esc(entry.status)}</div></td>"
                f"<td>{_esc(_row_name(entry.title, item.description if item else ''))}</td>"
                f"<td>{_esc(entry.summary())} <span class='small'>{_esc(units)}</span></td>"
                f"<td class='small'>{detail}</td></tr>"
            )
        add("</tbody></table></div></section>")

    table(plan.safe_bytes, "Безопасно — можно перенести один в один")
    table(plan.safe_name, "Безопасно по имени — переносить физическую величину руками")
    table(plan.warned, "Под предупреждением — разбирайтесь вручную")
    add(_HTML_TAIL)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write("\n".join(parts))


def write_port_csv(plan: PortPlan, path: str) -> None:
    with open(path, "w", encoding="utf-8-sig", newline="") as fh:
        writer = csv.writer(fh, delimiter=";")
        writer.writerow(
            ["Имя в XDF", "Статус", "Название", "Единицы", "Ваше значение",
             "В целевой сейчас", "Имя в целевой", "Чем совпало / что не так"]
        )
        for entry in plan.entries:
            item = entry.item_dst or entry.item_src
            dec = item.value_decimals if item else 2
            otype = item.value_output_type if item else 1

            def rng(values):
                if not values:
                    return ""
                if len(values) == 1:
                    return format_number(values[0], dec, otype)
                return (f"{format_number(min(values), dec, otype)}…"
                        f"{format_number(max(values), dec, otype)}")

            bits = entry.match_bits if entry.safe else entry.warn_bits
            writer.writerow(
                [
                    entry.title,
                    entry.status,
                    _row_name(entry.title, item.description if item else ""),
                    ru.unit_ru(item.value_units) if item else "",
                    rng(entry.phys_tuned),
                    rng(entry.phys_target_before),
                    entry.dst_title,
                    " | ".join(bits),
                ]
            )


# ---------------------------------------------------------------------------
# Откатка карты по логу ШЛЗ
# ---------------------------------------------------------------------------


def vetune_console_report(reader: Reader, result) -> str:
    item = result.item
    dec, otype = item.value_decimals, item.value_output_type
    units = ru.unit_ru(item.value_units)
    out: List[str] = []
    add = out.append
    add("═" * 78)
    add("  ОТКАТКА КАРТЫ ПО ЛОГУ ШЛЗ")
    add("═" * 78)
    add(f"Карта        : {item.title}")
    add(f"               {ru.explain(item.title, item.description)['name']}")
    add(f"Режим        : {result.mode}")
    add(f"Точек в логе : {result.total_samples}, использовано {result.used_samples}")
    for reason, count in result.skipped.items():
        if count:
            add(f"               отброшено «{reason}»: {count}")
    add(f"Покрытие     : {result.coverage * 100:.0f}% ячеек карты")
    add(f"Изменено     : {result.touched_cells} из {item.cell_count} ячеек")
    add("")
    for note in result.notes:
        add(f"! {note}")
    if result.notes:
        add("")

    y_labels = _axis_labels(reader, item, "y")
    x_labels = _axis_labels(reader, item, "x")
    width = max(9, max((len(s) for s in x_labels), default=6) + 2)

    add("Поправка, % (сколько добавить к наполнению; пусто — данных не хватило)")
    add(" " * 10 + "".join(f"{lbl:>{width}}" for lbl in x_labels))
    add(" " * 10 + "-" * (width * item.cols))
    for r in range(item.rows):
        cells = []
        for c in range(item.cols):
            pct = result.correction_percent(r, c)
            samples = result.samples_at(r, c)
            if result.new[r][c] == result.old[r][c]:
                cells.append(f"{('·' if samples else ''):>{width}}")
            else:
                cells.append(f"{pct:>+{width}.1f}")
        add(f"{y_labels[r]:>9} |" + "".join(cells))
    add("")
    add("Точек в ячейке (чем больше, тем надёжнее)")
    add(" " * 10 + "".join(f"{lbl:>{width}}" for lbl in x_labels))
    for r in range(item.rows):
        cells = [f"{result.samples_at(r, c) or '':>{width}}" for c in range(item.cols)]
        add(f"{y_labels[r]:>9} |" + "".join(cells))
    add("")
    add(f"Новые значения ({units or 'ед.'})")
    add(" " * 10 + "".join(f"{lbl:>{width}}" for lbl in x_labels))
    for r in range(item.rows):
        cells = [f"{format_number(result.new[r][c], dec, otype):>{width}}"
                 for c in range(item.cols)]
        add(f"{y_labels[r]:>9} |" + "".join(cells))
    add("")
    add("· — данные есть, но их мало или разброс велик, ячейка не тронута")

    # Пояснения берём прежде всего из офлайн-копии MS4X Wiki: там это описано
    # подробнее и авторитетнее, чем в любых наших заметках.
    guidance = _wiki_guidance(item.title)
    if guidance:
        add("")
        add("═" * 78)
        add("  ЧТО ОБ ЭТОМ ПИШЕТ MS4X WIKI (перевод)")
        add("═" * 78)
        for section in guidance[:4]:
            add("")
            add(f"  ── {section.page} / {section.heading}")
            text = section.text
            if len(text) > 1200:
                text = text[:1200].rsplit(" ", 1)[0] + " …"
            for line in translate_wiki(text).split("\n"):
                line = line.strip()
                if not line:
                    continue
                while len(line) > 92:
                    cut = line.rfind(" ", 0, 92)
                    cut = cut if cut > 40 else 92
                    add(f"     {line[:cut]}")
                    line = line[cut:].lstrip()
                add(f"     {line}")
            for warning in section.caution_lines[:3]:
                add(f"     ⚠ {translate_wiki(warning)[:300]}")
            add(f"     {section.url}")
    return "\n".join(out)


def _wiki_guidance(title: str):
    try:
        from . import wikicache

        if not wikicache.available():
            return []
        return wikicache.guidance_for_map(title)
    except Exception:  # noqa: BLE001
        return []


def _tune_map_html(reader: Reader, result) -> str:
    """Карта поправок: цвет — насколько подняли/опустили, снизу число точек."""
    item = result.item
    x_labels = _axis_labels(reader, item, "x")
    y_labels = _axis_labels(reader, item, "y")
    y_name, x_name = ru.axis_names_ru(item.title)
    x_units = ru.unit_ru(item.axis_x.units) if item.axis_x else ""
    y_units = ru.unit_ru(item.axis_y.units) if item.axis_y else ""

    scale = max((abs(result.correction_percent(r, c))
                 for r in range(item.rows) for c in range(item.cols)), default=1.0) or 1.0

    parts = ["<div class='mapwrap'>"]
    parts.append(
        f"<div class='small mapcap'>строки — {_esc(y_name or 'индекс')}"
        + (f" [{_esc(y_units)}]" if y_units else "")
        + f" · столбцы — {_esc(x_name or 'индекс')}"
        + (f" [{_esc(x_units)}]" if x_units else "")
        + "</div>"
    )
    parts.append("<table class='map'><thead><tr><th class='corner'></th>")
    for label in x_labels:
        parts.append(f"<th>{_esc(label)}</th>")
    parts.append("</tr></thead><tbody>")
    for r in range(item.rows):
        parts.append(f"<tr><th class='ylab'>{_esc(y_labels[r])}</th>")
        for c in range(item.cols):
            pct = result.correction_percent(r, c)
            samples = result.samples_at(r, c)
            touched = result.new[r][c] != result.old[r][c]
            if touched:
                bg = heatmap.delta_color(pct, scale)
                main = f"{pct:+.1f}%"
            else:
                bg = (238, 238, 238)
                main = "·" if samples else ""
            fg = heatmap.text_color(bg)
            title = (f"было {format_number(result.old[r][c], item.value_decimals, 1)}, "
                     f"станет {format_number(result.new[r][c], item.value_decimals, 1)}; "
                     f"точек {samples}")
            sub = f"<span class='d'>{samples}</span>" if samples else ""
            parts.append(
                f"<td style='background:{heatmap.hex_color(bg)};"
                f"color:{heatmap.hex_color(fg)}' title='{_esc(title)}'>"
                f"{_esc(main)}{sub}</td>"
            )
        parts.append("</tr>")
    parts.append("</tbody></table>")
    parts.append("<div class='legend'><span class='small'>поправка, %:</span>")
    for value, rgb in heatmap.delta_legend_stops(scale):
        fg = heatmap.text_color(rgb)
        parts.append(
            f"<span class='chip' style='background:{heatmap.hex_color(rgb)};"
            f"color:{heatmap.hex_color(fg)}'>{value:+.1f}</span>"
        )
    parts.append("</div><div class='small'>маленькая цифра в ячейке — "
                 "сколько точек лога туда попало</div></div>")
    return "".join(parts)


def write_vetune_html(reader: Reader, result, path: str, log_name: str = "") -> None:
    item = result.item
    info = ru.explain(item.title, item.description)
    title = f"Откатка карты {item.title}"
    parts: List[str] = [_HTML_HEAD.format(title=_esc(title))]
    add = parts.append
    add("<h1>Откатка карты по логу ШЛЗ</h1>")
    add(
        f"<div class='meta'>Карта: <code>{_esc(item.title)}</code> — "
        f"{_esc(info['name'])}<br>"
        f"Прошивка: <code>{_esc(reader.bin.name)}</code>"
        + (f"<br>Лог: <code>{_esc(log_name)}</code>" if log_name else "")
        + f"<br>Отчёт создан {datetime.now():%d.%m.%Y %H:%M}</div>"
    )
    add("<div class='stats'>")
    add(f"<div class='stat'><b>{result.used_samples}</b><span>точек использовано</span></div>")
    add(f"<div class='stat'><b>{result.total_samples}</b><span>точек в логе</span></div>")
    add(f"<div class='stat'><b>{result.coverage * 100:.0f}%</b><span>покрытие карты</span></div>")
    add(f"<div class='stat'><b>{result.touched_cells}</b><span>ячеек изменено</span></div>")
    add("</div>")
    for note in result.notes:
        add(f"<div class='tune'><b>Внимание:</b> {_esc(note)}</div>")
    add("<section><h2>Предлагаемая поправка</h2>")
    add(_tune_map_html(reader, result))
    add("</section>")
    add("<section><h2>Карта сейчас</h2>")
    add("<div class='small'>Цвет по значению — как карта выглядит до правки.</div>")
    add(render_map_html(reader, item))
    add("</section>")

    guidance = _wiki_guidance(item.title)
    if guidance:
        add("<section><h2>Что об этом пишет MS4X Wiki (перевод) "
            f"<span class='badge'>{len(guidance)}</span></h2>")
        add("<div class='wikibox'>")
        for section in guidance[:6]:
            add(f"<div class='wikihead'>{_esc(section.page)} / "
                f"{_esc(section.heading)}</div>")
            for line in translate_wiki(section.text).split("\n"):
                if line.strip():
                    add(f"<p class='wikitext'>{_esc(line.strip())}</p>")
            for warning in section.caution_lines[:4]:
                add(f"<p class='wikiwarn'>⚠ {_esc(translate_wiki(warning))}</p>")
            add("<details class='orig'><summary>оригинал (English)</summary>")
            for line in section.text.split("\n"):
                if line.strip():
                    add(f"<p class='wikitext'>{_esc(line.strip())}</p>")
            add("</details>")
            add(f"<p class='small'><a href='{_esc(section.url)}'>"
                f"{_esc(section.url)}</a></p>")
        add("</div></section>")
    add(_HTML_TAIL)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write("\n".join(parts))


def patches_report(statuses: Sequence[PatchStatus], patchlist: XdfFile, binf) -> str:
    out: List[str] = []
    out.append("═" * 78)
    out.append(f"  ПАТЧИ: {patchlist.title}")
    out.append(f"  Прошивка: {binf.name}")
    out.append("═" * 78)
    applied = [s for s in statuses if s.state == "применён"]
    out.append(f"Применено {len(applied)} из {len(statuses)}")
    out.append("")

    by_cat: Dict[str, List[PatchStatus]] = {}
    for status in statuses:
        names = [patchlist.category_name(c) for c in status.patch.categories] or ["<без категории>"]
        cat = ", ".join(ru.category_ru(n) for n in names)
        by_cat.setdefault(cat, []).append(status)

    for cat in sorted(by_cat):
        out.append(_LINE)
        out.append(f"  {cat.upper()}")
        out.append(_LINE)
        for status in by_cat[cat]:
            mark = _PATCH_MARK.get(status.state, "[?]")
            out.append(f"{mark} {status.patch.title}  — {status.state}")
            desc = ru.description_ru(status.patch.description)
            if desc:
                out.append(f"     {desc}")
            for detail in status.details[:3]:
                out.append(f"     ! {detail}")
        out.append("")
    return "\n".join(out)
