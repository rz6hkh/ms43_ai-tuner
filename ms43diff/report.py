# -*- coding: utf-8 -*-
"""
Report generation: console, HTML, Markdown, CSV, JSON.

The HTML report is self-contained (no external files), with table search,
highlighting of the change sign and a heat map for 2D tables.
"""

from __future__ import annotations

import csv
import html
import json
import os
from datetime import datetime
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

from . import heatmap, names
from .binfile import Reader, format_number
from .compare import (
    PATCH_APPLIED,
    PATCH_MODIFIED,
    PATCH_NOT_APPLIED,
    PATCH_OUT_OF_FILE,
    PATCH_PARTIAL,
    Change,
    CompareResult,
    PatchStatus,
)
from .crossdiff import (
    ST_DIFF,
    ST_ONLY_A,
    ST_ONLY_B,
    CrossResult,
    CrossRow,
    PortEntry,
    PortPlan,
)
from .i18n import get_lang, t
from .xdf import OUT_TEXT, Item, XdfFile

# ---------------------------------------------------------------------------
# Common helpers
# ---------------------------------------------------------------------------


def item_categories(xdf: XdfFile, item: Item) -> str:
    return ", ".join(names.category(name) for name in xdf.category_names(item))


def _now() -> str:
    return datetime.now().strftime(t("%Y-%m-%d %H:%M"))


# ---------------------------------------------------------------------------
# Hints from the offline MS4X Wiki copy
# ---------------------------------------------------------------------------


def wiki_sections(title: str):
    """Wiki sections that mention the parameter (empty without a cache)."""
    try:
        from . import wikicache

        if not wikicache.available():
            return []
        return wikicache.sections_for(title)
    except Exception:  # noqa: BLE001 - the reference must not break the report
        return []


def value_meanings(title: str) -> Dict[int, str]:
    """Switch value meanings from the wiki: {0: '...', 1: '...'}."""
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
    """(value, what it means) pairs for specific values of the parameter.

    This answers the question "it was 4, now it is 1 — what changed".
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
        meaning = translate_wiki(meaning) if meaning else t("the reference has no such value")
        out.append((str(key), meaning))
    return out


def wiki_notes_text(title: str, max_chars: int = 900) -> List[str]:
    """Text block "what the wiki says about it" for console output."""
    sections = wiki_sections(title)
    if not sections:
        return []
    out = ["", t("─── MS4X Wiki ───")]
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
        out.append(t("  ({n} more mentions: ms43diff wiki --param {title})",
                     n=len(sections) - 2, title=title))
    return out


def _focused(section, title: str) -> str:
    """Only the part of the section about the parameter (original, English)."""
    try:
        from . import wikicache

        return wikicache.focused_text(section, title)
    except Exception:  # noqa: BLE001
        return section.text


def translate_wiki(text: str) -> str:
    """Translate a piece of wiki text in Russian mode (verified + machine)."""
    try:
        from . import wikitrans

        return wikitrans.translate_block(text)
    except Exception:  # noqa: BLE001 - translation must not break the report
        return text


def _focused_ru(section, title: str) -> str:
    return translate_wiki(_focused(section, title))


def wiki_notes_html(title: str) -> str:
    sections = wiki_sections(title)
    if not sections:
        return ""
    parts = ["<details><summary>"
             + _esc(t("what MS4X Wiki says ({n})", n=len(sections)))
             + "</summary><div class='wikibox'>"]
    for section in sections[:3]:
        parts.append(f"<div class='wikihead'>{_esc(section.page)} / "
                     f"{_esc(section.heading)}</div>")
        text = _focused(section, title)
        if len(text) > 2200:
            text = text[:2200].rsplit(" ", 1)[0] + " …"
        shown = translate_wiki(text)
        for line in shown.split("\n"):
            if line.strip():
                parts.append(f"<p class='wikitext'>{_esc(line.strip())}</p>")
        for warning in section.caution_lines[:3]:
            parts.append(f"<p class='wikiwarn'>⚠ {_esc(translate_wiki(warning))}</p>")
        if shown != text:
            parts.append("<details class='orig'><summary>"
                         + _esc(t("original (English)")) + "</summary>")
            for line in text.split("\n"):
                if line.strip():
                    parts.append(f"<p class='wikitext'>{_esc(line.strip())}</p>")
            parts.append("</details>")
        parts.append(f"<p class='small'><a href='{_esc(section.url)}'>"
                     f"{_esc(section.url)}</a></p>")
    parts.append("</div></details>")
    return "".join(parts)


def change_row(xdf: XdfFile, change: Change) -> Dict[str, str]:
    """One report row as a dict — shared by all formats."""
    item = change.item
    info = names.explain(item.title, item.description)
    units = names.unit(item.value_units)
    dec = item.value_decimals
    otype = item.value_output_type
    return {
        "title": item.title,
        "name": info["name"],
        "decoded": info["decoded"],
        "desc": info["desc"],
        "desc_orig": info["desc_en"],
        "note": info["note"],
        "tune": info["tune"],
        "category": item_categories(xdf, item),
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
        "scaling": item.value_equation.describe(units),
    }


# ---------------------------------------------------------------------------
# Console
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
    add(t("  MS43 FIRMWARE COMPARISON"))
    add("═" * 78)
    add(t("XDF          : {title}  (v{version}, {author})", title=result.xdf.title,
          version=result.xdf.file_version, author=result.xdf.author))
    add(t("File A       : {name}  ({kb} KB)", name=result.bin_a.name, kb=result.bin_a.size_kb))
    add(t("File B       : {name}  ({kb} KB)", name=result.bin_b.name, kb=result.bin_b.size_kb))
    add(t("Offset       : A {a} / B {b}", a=result.reader_a.offset.label,
          b=result.reader_b.offset.label))
    if result.size_mismatch:
        add(t("WARNING: the files differ in size, the smaller one is compared."))
    for tag, reader in (("A", result.reader_a), ("B", result.reader_b)):
        warning = reader.version_warning()
        if warning:
            add(t("WARNING ({tag}): {text}", tag=tag, text=warning))
    add("")
    add(t("Parameters changed  : {n}", n=result.changed_params))
    add(t("Parameters same     : {n}", n=result.identical))
    if result.byte_blocks:
        add(t("Bytes changed       : {n} in {blocks} blocks",
              n=result.total_bytes_changed, blocks=len(result.byte_blocks)))
        code = result.code_blocks
        if code:
            add(t("Blocks outside XDF  : {n} ({bytes} bytes) — code edits/patches",
                  n=len(code), bytes=sum(b.length for b in code)))
    if result.skipped:
        add(t("Skipped             : {n} (address outside the file)", n=len(result.skipped)))
    add("")

    if not result.changes:
        add(t("No differences found in the parameters described by the XDF."))
        return "\n".join(out)

    # group by category
    by_cat: Dict[str, List[Change]] = {}
    for change in result.changes:
        cat = item_categories(result.xdf, change.item)
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
                add(t("... showing {shown} of {total}. Use --limit 0 to show everything.",
                      shown=shown, total=result.changed_params))
                return "\n".join(out)
            shown += 1
            row = change_row(result.xdf, change)
            add(f"• {row['title']}")
            add(f"    {row['name']}")
            if row["desc"]:
                add(t("    Description: {text}", text=row["desc"]))
            if show_english and row["desc_orig"]:
                add(t("    Original: {text}", text=row["desc_orig"]))
            unit_suffix = f" {row['units']}" if row["units"] else ""
            add(t("    Value: {value}", value=row["summary"] + unit_suffix))
            add(t("    Type: {shape} | XDF address {address} | file {offset} | {scaling}",
                  shape=row["shape"], address=row["address"], offset=row["offset"],
                  scaling=row["scaling"]))
            # Meaning of the specific numbers: "was 4 = …, now 1 = …"
            if change.is_scalar and change.cells:
                for value, meaning in explain_values(
                    row["title"], change.cells[0].val_a, change.cells[0].val_b
                ):
                    add(f"      {value} = {meaning}")
                for step in after_change_steps(row["title"]):
                    add(t("    After the change: {step}", step=step))
            if row["note"]:
                add(t("    What it is: {text}", text=row["note"]))
            if row["tune"]:
                add(t("    How to tune: {text}", text=row["tune"]))
            for line in wiki_notes_text(row["title"], max_chars=500):
                add(f"  {line}")
            if verbose and not change.is_scalar:
                add(_cells_block(change, indent="      "))
            add("")

    if result.code_blocks:
        add(_LINE)
        add(t("  CHANGES OUTSIDE THE DESCRIBED PARAMETERS (code / patches)"))
        add(_LINE)
        for block in result.code_blocks[:40]:
            add(t("  0x{start:06X}–0x{end:06X}  ({n} bytes)", start=block.start,
                  end=block.end, n=block.length))
        if len(result.code_blocks) > 40:
            add(t("  ... and {n} more blocks", n=len(result.code_blocks) - 40))
        add("")

    return "\n".join(out)


def _cells_block(change: Change, indent: str = "  ", max_cells: int = 40) -> str:
    item = change.item
    dec = item.value_decimals
    otype = item.value_output_type
    lines = [indent + t("changed cells:")]
    for cell in change.cells[:max_cells]:
        pos = f"[{cell.row}][{cell.col}]" if item.rows > 1 and item.cols > 1 else f"[{max(cell.row, cell.col)}]"
        a = format_number(cell.val_a, dec, otype)
        b = format_number(cell.val_b, dec, otype)
        d = format_number(cell.delta, dec, otype)
        sign = "+" if cell.delta > 0 else ""
        lines.append(f"{indent}  {pos:>10}  {a:>10} -> {b:>10}   ({sign}{d})")
    if len(change.cells) > max_cells:
        lines.append(indent + t("  ... and {n} more cells", n=len(change.cells) - max_cells))
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Printing one map
# ---------------------------------------------------------------------------


def render_table(reader: Reader, item: Item, reader_b: Optional[Reader] = None) -> str:
    """Print a map with its axes; with reader_b — next to the delta."""
    xdf = reader.xdf
    info = names.explain(item.title, item.description)
    units = names.unit(item.value_units)
    dec = item.value_decimals
    otype = item.value_output_type

    out: List[str] = []
    out.append("═" * 78)
    out.append(f"  {item.title}")
    out.append("═" * 78)
    out.append(t("Decoded     : {text}", text=info["name"]))
    if info["decoded"] != info["name"]:
        out.append(t("Dictionary  : {text}", text=info["decoded"]))
    out.append(t("Type        : {kind} | {shape}", kind=info["kind"], shape=item.shape_str))
    out.append(t("Category    : {text}", text=item_categories(xdf, item)))
    if info["desc"]:
        out.append(t("Description : {text}", text=info["desc"]))
    if info["desc_en"]:
        out.append(t("Original    : {text}", text=info["desc_en"]))
    if info["note"]:
        out.append(t("Purpose     : {text}", text=info["note"]))
    if info["tune"]:
        out.append(t("How to tune : {text}", text=info["tune"]))
    data = item.data
    if data is not None and data.address is not None:
        out.append(t(
            "Address     : XDF 0x{address:X} -> file 0x{offset:X}, {bits} bits, {sign}, {order}",
            address=data.address, offset=reader.file_offset(data.address),
            bits=data.size_bits, sign=t("signed") if data.signed else t("unsigned"),
            order="little-endian" if data.lsb_first else "big-endian"))
    out.append(t("Units       : {text}", text=units or "—"))
    out.append(t("Scale       : {text}", text=item.value_equation.describe(units)))
    for line in wiki_notes_text(item.title):
        out.append(line)
    out.append("")

    values = reader.matrix(item)
    if values is None:
        out.append(t("Could not read the values (address outside the file)."))
        return "\n".join(out)

    values_b = reader_b.matrix(item) if reader_b is not None else None
    x_axis = reader.axis_values(item, "x")
    y_axis = reader.axis_values(item, "y")

    x_units = names.unit(item.axis_x.units) if item.axis_x else ""
    y_units = names.unit(item.axis_y.units) if item.axis_y else ""

    cols = item.cols
    rows = item.rows

    # axis captions: names from the object name, units from the XDF itself
    y_name, x_name = names.axis_names(item.title)
    if cols > 1 and rows == 1 and y_name and not x_name:
        y_name, x_name = "", y_name  # a 1D table along columns has one axis

    def axis_caption(name: str, units: str, fallback: str) -> str:
        caption = name or fallback
        if units and units.lower() not in caption.lower():
            caption += f" [{units}]"
        return caption

    def fmt(v: float) -> str:
        return format_number(v, dec, otype)

    # header
    col_labels = []
    for c in range(cols):
        if x_axis and c < len(x_axis):
            col_labels.append(format_number(x_axis[c], item.axis_x.decimals if item.axis_x else 0, 1))
        else:
            col_labels.append(str(c))
    width = max(9, max((len(s) for s in col_labels), default=6) + 1)
    row_label_w = 10

    if rows > 1:
        out.append(t("Rows    (Y): {text}", text=axis_caption(y_name, y_units, t("index"))))
    if cols > 1:
        out.append(t("Columns (X): {text}", text=axis_caption(x_name, x_units, t("index"))))
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
        out.append(t("* — the value differs in the second file (the value from B is shown)"))
    return "\n".join(out)


# ---------------------------------------------------------------------------
# CSV / JSON / Markdown
# ---------------------------------------------------------------------------

def csv_fields() -> List[Tuple[str, str]]:
    return [
        ("title", t("XDF name")),
        ("name", t("Name")),
        ("category", t("Category")),
        ("desc", t("Description")),
        ("desc_orig", t("Description (original)")),
        ("shape", t("Type")),
        ("units", t("Units")),
        ("address", t("XDF address")),
        ("offset", t("File offset")),
        ("changed", t("Cells changed")),
        ("summary", t("Before -> After")),
        ("delta_min", t("Delta min")),
        ("delta_max", t("Delta max")),
        ("delta_avg", t("Delta avg")),
        ("pct", t("Max change, %")),
        ("scaling", t("Scale")),
        ("note", t("What it is")),
        ("tune", t("How to tune")),
    ]


def write_csv(result: CompareResult, path: str) -> None:
    with open(path, "w", encoding="utf-8-sig", newline="") as fh:
        writer = csv.writer(fh, delimiter=";")
        fields = csv_fields()
        writer.writerow([title for _, title in fields])
        for change in result.changes:
            row = change_row(result.xdf, change)
            writer.writerow([row.get(key, "") for key, _ in fields])


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
    lines.append(t("# MS43 firmware comparison"))
    lines.append("")
    lines.append(f"* **A:** `{result.bin_a.name}`")
    lines.append(f"* **B:** `{result.bin_b.name}`")
    lines.append(f"* **XDF:** {result.xdf.title} (v{result.xdf.file_version})")
    lines.append(t("* **Parameters changed:** {n}", n=result.changed_params))
    lines.append(t("* **Bytes changed:** {n}", n=result.total_bytes_changed))
    lines.append("")

    by_cat: Dict[str, List[Change]] = {}
    for change in result.changes:
        by_cat.setdefault(item_categories(result.xdf, change.item), []).append(change)

    for cat in sorted(by_cat, key=lambda c: (-len(by_cat[c]), c)):
        lines.append(f"## {cat}")
        lines.append("")
        lines.append(t("| Parameter | What it is | Before → After | Units |"))
        lines.append("|---|---|---|---|")
        for change in by_cat[cat]:
            row = change_row(result.xdf, change)
            desc = row["desc"] or row["name"]
            desc = desc.replace("|", "\\|").replace("\n", " ")
            lines.append(
                f"| `{row['title']}` | {desc} | {row['summary']} | {row['units']} |"
            )
        lines.append("")

    if result.code_blocks:
        lines.append(t("## Edits outside XDF maps (code / patches)"))
        lines.append("")
        lines.append(t("| Offset | Length |"))
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
<html lang="{lang}"><head><meta charset="utf-8">
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
    return html.escape(str(text) if text is not None else "", quote=False)


def _html_head(title: str) -> str:
    return _HTML_HEAD.format(title=_esc(title), lang=get_lang())


def _stat(value, label: str) -> str:
    return f"<div class='stat'><b>{_esc(value)}</b><span>{_esc(label)}</span></div>"


def _th(*labels: str) -> str:
    return "".join(f"<th>{_esc(label)}</th>" for label in labels)


def _search_box(placeholder: str) -> str:
    return f"<input type='search' id='q' placeholder='{html.escape(placeholder)}'>"


# ---------------------------------------------------------------------------
# HTML heat map
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
    """A map as a coloured table.

    Without a second file — coloured by value (sequential scale).
    With two files — coloured by the size of the change (diverging scale, zero
    neutral), the cell shows the new value and the delta.
    """
    before = reader.matrix(item)
    if not before:
        return "<p class='small'>" + _esc(t("Could not read the values.")) + "</p>"
    after = reader_b.matrix(item) if reader_b is not None else None
    dec, otype = item.value_decimals, item.value_output_type
    units = names.unit(item.value_units)

    x_labels = _axis_labels(reader, item, "x")
    y_labels = _axis_labels(reader, item, "y")
    y_name, x_name = names.axis_names(item.title)
    x_units = names.unit(item.axis_x.units) if item.axis_x else ""
    y_units = names.unit(item.axis_y.units) if item.axis_y else ""

    parts: List[str] = ["<div class='mapwrap'>"]
    caption = []
    if item.rows > 1:
        caption.append(_esc(t("rows — {name}", name=y_name or t("index")))
                       + (f" [{_esc(y_units)}]" if y_units else ""))
    if item.cols > 1:
        caption.append(_esc(t("columns — {name}", name=x_name or t("index")))
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
                    title = t("was {a}, now {b} {units}", a=format_number(a, dec, otype),
                              b=main, units=units)
                else:
                    extra = ""
                    title = t("{value} {units} — unchanged", value=main, units=units)
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

    # legend
    if after is not None:
        stops = heatmap.delta_legend_stops(scale)
        legend_title = t("change, {units}", units=units) if units else t("change")
    else:
        stops = heatmap.legend_stops(low, high)
        legend_title = t("value, {units}", units=units) if units else t("value")
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
    parts: List[str] = [_html_head(title)]
    add = parts.append

    add("<h1>" + _esc(t("MS43 firmware comparison")) + "</h1>")
    add(
        f"<div class='meta'>A: <code>{_esc(result.bin_a.name)}</code> "
        f"({result.bin_a.size_kb} {_esc(t('KB'))}) &nbsp;↔&nbsp; "
        f"B: <code>{_esc(result.bin_b.name)}</code> ({result.bin_b.size_kb} {_esc(t('KB'))})<br>"
        f"XDF: {_esc(result.xdf.title)} v{_esc(result.xdf.file_version)} · "
        f"{_esc(result.xdf.author)} · "
        + _esc(t("offset {label}", label=result.reader_a.offset.label)) + "<br>"
        + _esc(t("Report created {date}", date=_now())) + "</div>"
    )

    add("<div class='stats'>")
    add(_stat(result.changed_params, t("parameters changed")))
    add(_stat(result.identical, t("parameters same")))
    add(_stat(result.total_bytes_changed, t("bytes changed")))
    add(_stat(len(result.code_blocks), t("code edit blocks")))
    add("</div>")

    add(_search_box(t("Search parameters, descriptions, addresses…")))

    by_cat: Dict[str, List[Change]] = {}
    for change in result.changes:
        by_cat.setdefault(item_categories(result.xdf, change.item), []).append(change)

    for cat in sorted(by_cat, key=lambda c: (-len(by_cat[c]), c)):
        changes = by_cat[cat]
        add(f"<section><h2>{_esc(cat)} <span class='badge'>{len(changes)}</span></h2>")
        add("<div class='wrap'><table><thead><tr>"
            + _th(t("Parameter"), t("What it is"), t("Before → After"), "Δ", t("Address"))
            + "</tr></thead><tbody>")
        for change in changes:
            row = change_row(result.xdf, change)
            delta_cls = ""
            if change.max_pct > 0:
                delta_cls = "pos"
            elif change.max_pct < 0:
                delta_cls = "neg"
            delta_txt = row["pct"] + " %" if row["pct"] else "—"

            desc_html = _esc(row["desc"] or row["name"])
            extra = ""
            if row["desc"] and row["name"] and row["desc"] != row["name"]:
                extra = f"<div class='small'>{_esc(row['name'])}</div>"
            if row["note"]:
                extra += ("<div class='tune'><b>" + _esc(t("What it does:")) + "</b> "
                          + _esc(row["note"]) + "</div>")
            if row["tune"]:
                extra += ("<div class='tune'><b>" + _esc(t("How to tune:")) + "</b> "
                          + _esc(row["tune"]) + "</div>")
            if row["desc_orig"]:
                extra += f"<div class='small'>EN: {_esc(row['desc_orig'])}</div>"
            if change.is_scalar and change.cells:
                pairs = explain_values(row["title"], change.cells[0].val_a,
                                       change.cells[0].val_b)
                if pairs:
                    extra += ("<div class='values'><b>" + _esc(t("What the values mean:"))
                              + "</b><ul>")
                    for value, meaning in pairs:
                        extra += f"<li><code>{_esc(value)}</code> — {_esc(meaning)}</li>"
                    extra += "</ul></div>"
                steps = after_change_steps(row["title"])
                if steps:
                    extra += ("<div class='tune'><b>" + _esc(t("After the change:"))
                              + "</b><ul>"
                              + "".join(f"<li>{_esc(s)}</li>" for s in steps)
                              + "</ul></div>")
            extra += wiki_notes_html(change.item.title)

            add(
                "<tr>"
                f"<td><code>{_esc(row['title'])}</code>"
                f"<div class='small'>{_esc(row['shape'])} · {_esc(row['scaling'])}</div></td>"
                f"<td>{desc_html}{extra}</td>"
                f"<td>{_esc(row['summary'])} <span class='small'>{_esc(row['units'])}</span>"
                "<div class='small'>" + _esc(t("{n} cells changed", n=row["changed"]))
                + "</div></td>"
                f"<td class='{delta_cls}'>{_esc(delta_txt)}</td>"
                f"<td><code>{_esc(row['address'])}</code>"
                "<div class='small'>" + _esc(t("file {offset}", offset=row["offset"]))
                + "</div></td>"
                "</tr>"
            )

            # The map itself goes into a separate full-width row: it is
            # unreadable in a narrow column, and it is what the report is for.
            if change.item.cell_count > 1 and change.item.value_output_type != OUT_TEXT:
                opened = " open" if change.item.cell_count <= 256 else ""
                add(
                    f"<tr class='maprow'><td colspan='5'>"
                    f"<details{opened}><summary>"
                    + _esc(t("map {shape} — {changed} of {total} cells changed",
                             shape=change.item.shape_str, changed=change.changed_cells,
                             total=change.total_cells))
                    + "</summary>"
                    + render_map_html(result.reader_a, change.item, result.reader_b)
                    + "</details></td></tr>"
                )
        add("</tbody></table></div></section>")

    if result.code_blocks:
        add("<section><h2>" + _esc(t("Edits outside XDF maps (code / patches)"))
            + f" <span class='badge'>{len(result.code_blocks)}</span></h2>")
        add("<div class='wrap'><table><thead><tr>"
            + _th(t("Offset"), t("Length, bytes"), t("Comment"))
            + "</tr></thead><tbody>")
        note = _esc(t("not described in the XDF — probably a machine code edit"))
        for block in result.code_blocks:
            add(
                f"<tr><td><code>0x{block.start:06X}–0x{block.end:06X}</code></td>"
                f"<td>{block.length}</td>"
                f"<td class='small'>{note}</td></tr>"
            )
        add("</tbody></table></div></section>")

    add(_HTML_TAIL)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write("\n".join(parts))


# ---------------------------------------------------------------------------
# Patch report
# ---------------------------------------------------------------------------

_PATCH_MARK = {
    PATCH_APPLIED: "[+]",
    PATCH_NOT_APPLIED: "[ ]",
    PATCH_PARTIAL: "[~]",
    PATCH_MODIFIED: "[?]",
    PATCH_OUT_OF_FILE: "[x]",
}


# ---------------------------------------------------------------------------
# Comparing different software versions
# ---------------------------------------------------------------------------


def _row_name(title: str, description: str = "") -> str:
    info = names.explain(title, description)
    return info["name"]


def cross_console_report(result: CrossResult, limit: int = 60) -> str:
    out: List[str] = []
    add = out.append
    add("═" * 78)
    add(t("  DIFFERENT SOFTWARE VERSIONS (parameters matched by name)"))
    add("═" * 78)
    add(f"A: {result.bin_a.name}")
    add(t("   XDF {title} v{version}, software {fw}", title=result.xdf_a.title,
          version=result.xdf_a.file_version, fw=result.reader_a.firmware_id() or "?"))
    add(f"B: {result.bin_b.name}")
    add(t("   XDF {title} v{version}, software {fw}", title=result.xdf_b.title,
          version=result.xdf_b.file_version, fw=result.reader_b.firmware_id() or "?"))
    add("")
    add(t("Same value      : {n}", n=result.identical))
    add(t("Different       : {n}", n=len(result.different)))
    add(t("Only in A       : {n}", n=len(result.only_a)))
    add(t("Only in B       : {n}", n=len(result.only_b)))
    if result.problems:
        add(t("Problems        : {n}", n=len(result.problems)))
    add("")
    add(t("Physical values are compared, not bytes: conversion formulas may differ"))
    add(t("between software versions."))
    add("")

    shown = 0
    for row in result.different:
        if limit and shown >= limit:
            add(t("... showing {shown} of {total}. Use --limit 0 for the full list.",
                  shown=shown, total=len(result.different)))
            break
        shown += 1
        item = row.item
        units = names.unit(item.value_units) if item else ""
        add(f"• {row.title}")
        add(f"    {_row_name(row.title, item.description if item else '')}")
        add(f"    {row.summary()} {units}".rstrip())
        for note in row.notes:
            add(f"    ! {note}")
        add("")

    if result.only_a:
        add(_LINE)
        add(t("  ONLY IN A ({n}) — the target version has no such settings", n=len(result.only_a)))
        add(_LINE)
        for row in result.only_a[:30]:
            add(f"  {row.title}  — {_row_name(row.title)}")
        if len(result.only_a) > 30:
            add(t("  ... and {n} more", n=len(result.only_a) - 30))
        add("")
    if result.only_b:
        add(_LINE)
        add(t("  ONLY IN B ({n}) — new settings of the target version", n=len(result.only_b)))
        add(_LINE)
        for row in result.only_b[:30]:
            add(f"  {row.title}  — {_row_name(row.title)}")
        if len(result.only_b) > 30:
            add(t("  ... and {n} more", n=len(result.only_b) - 30))
        add("")
    return "\n".join(out)


def write_cross_html(result: CrossResult, path: str) -> None:
    title = t("MS43: {a} ↔ {b} (different versions)", a=result.bin_a.name, b=result.bin_b.name)
    parts: List[str] = [_html_head(title)]
    add = parts.append
    add("<h1>" + _esc(t("Different software versions")) + "</h1>")
    add(
        f"<div class='meta'>A: <code>{_esc(result.bin_a.name)}</code> · "
        f"{_esc(result.xdf_a.title)} · "
        + _esc(t("software {fw}", fw=result.reader_a.firmware_id() or "?")) + "<br>"
        f"B: <code>{_esc(result.bin_b.name)}</code> · "
        f"{_esc(result.xdf_b.title)} · "
        + _esc(t("software {fw}", fw=result.reader_b.firmware_id() or "?")) + "<br>"
        + _esc(t("Parameters are matched by name; physical values are compared.")) + "<br>"
        + _esc(t("Report created {date}", date=_now())) + "</div>"
    )
    add("<div class='stats'>")
    add(_stat(len(result.different), t("different")))
    add(_stat(result.identical, t("same")))
    add(_stat(len(result.only_a), t("only in A")))
    add(_stat(len(result.only_b), t("only in B")))
    add("</div>")
    add(_search_box(t("Search…")))

    def table(rows: List[CrossRow], heading: str) -> None:
        if not rows:
            return
        add(f"<section><h2>{_esc(heading)} <span class='badge'>{len(rows)}</span></h2>")
        add("<div class='wrap'><table><thead><tr>"
            + _th(t("Parameter"), t("What it is"), t("Values"), t("Notes"))
            + "</tr></thead><tbody>")
        for row in rows:
            item = row.item
            units = names.unit(item.value_units) if item else ""
            notes = "<br>".join(_esc(n) for n in row.notes)
            add(
                f"<tr><td><code>{_esc(row.title)}</code></td>"
                f"<td>{_esc(_row_name(row.title, item.description if item else ''))}</td>"
                f"<td>{_esc(row.summary())} <span class='small'>{_esc(units)}</span></td>"
                f"<td class='small'>{notes}</td></tr>"
            )
        add("</tbody></table></div></section>")

    table(result.different, t("Different"))
    table(result.only_a, t("Only in A"))
    table(result.only_b, t("Only in B"))
    table(result.problems, t("Problems"))
    add(_HTML_TAIL)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write("\n".join(parts))


# ---------------------------------------------------------------------------
# Settings port plan
# ---------------------------------------------------------------------------


def _port_warning() -> str:
    return t("IMPORTANT: the program only builds a plan and writes nothing to the "
             "firmware. Make all edits by hand in TunerPro and recalculate the "
             "checksums there.")


def port_console_report(plan: PortPlan, limit: int = 0, verbose: bool = False) -> str:
    out: List[str] = []
    add = out.append
    add("═" * 78)
    add(t("  SETTINGS PORT PLAN BETWEEN SOFTWARE VERSIONS"))
    add("═" * 78)
    add(t("Source stock          : {name}", name=plan.bin_stock.name))
    add(t("Your tune             : {name}", name=plan.bin_tuned.name))
    add(t("Source XDF            : {title} v{version}", title=plan.xdf_src.title,
          version=plan.xdf_src.file_version))
    add(t("Target firmware       : {name}", name=plan.bin_target.name))
    add(t("Target XDF            : {title} v{version}", title=plan.xdf_dst.title,
          version=plan.xdf_dst.file_version))
    add("")
    add(t("Parameters you changed : {n}", n=len(plan.entries)))
    add(t("Safe (by bytes)        : {n}", n=len(plan.safe_bytes)))
    add(t("Safe (by name)         : {n}", n=len(plan.safe_name)))
    add(t("With a warning         : {n}", n=len(plan.warned)))
    add("")
    add(_port_warning())
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
                add(t("  ... showing {shown} of {total}", shown=shown, total=len(entries)))
                break
            shown += 1
            item = entry.item_dst or entry.item_src
            units = names.unit(item.value_units) if item else ""
            add(f"• {entry.title}  — {entry.status_label}")
            add(f"    {_row_name(entry.title, item.description if item else '')}")
            add(f"    {entry.summary()} {units}".rstrip())
            add(f"    {entry.detail()}")
            add("")

    block(t("SAFE — can be ported one-to-one"), plan.safe_bytes)
    block(t("SAFE BY NAME — port the physical value by hand"), plan.safe_name)
    block(t("WARNING — sort it out by hand"), plan.warned)
    add(t("Everything is ported by hand in TunerPro — the program only shows the plan."))
    return "\n".join(out)


def write_port_html(plan: PortPlan, path: str) -> None:
    title = t("Settings port: {src} → {dst}", src=plan.xdf_src.title, dst=plan.xdf_dst.title)
    parts: List[str] = [_html_head(title)]
    add = parts.append
    add("<h1>" + _esc(t("Settings port plan between software versions")) + "</h1>")
    add(
        "<div class='meta'>"
        + _esc(t("Source stock:")) + f" <code>{_esc(plan.bin_stock.name)}</code><br>"
        + _esc(t("Your tune:")) + f" <code>{_esc(plan.bin_tuned.name)}</code> "
        f"({_esc(plan.xdf_src.title)})<br>"
        + _esc(t("Target:")) + f" <code>{_esc(plan.bin_target.name)}</code> "
        f"({_esc(plan.xdf_dst.title)})<br>"
        + _esc(t("Report created {date}", date=_now())) + "</div>"
    )
    add("<div class='tune'><b>" + _esc(t(
        "The program only builds a plan and writes nothing to the firmware. Make all "
        "edits by hand in TunerPro and recalculate the checksums there.")) + "</b></div>")
    add("<div class='stats'>")
    add(_stat(len(plan.safe_bytes), t("safe by bytes")))
    add(_stat(len(plan.safe_name), t("safe by name")))
    add(_stat(len(plan.warned), t("with a warning")))
    add("</div>")
    add(_search_box(t("Search…")))

    def table(entries: List[PortEntry], heading: str) -> None:
        if not entries:
            return
        add(f"<section><h2>{_esc(heading)} <span class='badge'>{len(entries)}</span></h2>")
        add("<div class='wrap'><table><thead><tr>"
            + _th(t("Parameter"), t("What it is"), t("Values"), t("What matched / what is wrong"))
            + "</tr></thead><tbody>")
        for entry in entries:
            item = entry.item_dst or entry.item_src
            units = names.unit(item.value_units) if item else ""
            bits = entry.match_bits if entry.safe else entry.warn_bits
            detail = "<br>".join(_esc(b) for b in bits)
            add(
                f"<tr><td><code>{_esc(entry.title)}</code>"
                f"<div class='small'>{_esc(entry.status_label)}</div></td>"
                f"<td>{_esc(_row_name(entry.title, item.description if item else ''))}</td>"
                f"<td>{_esc(entry.summary())} <span class='small'>{_esc(units)}</span></td>"
                f"<td class='small'>{detail}</td></tr>"
            )
        add("</tbody></table></div></section>")

    table(plan.safe_bytes, t("Safe — can be ported one-to-one"))
    table(plan.safe_name, t("Safe by name — port the physical value by hand"))
    table(plan.warned, t("With a warning — sort it out by hand"))
    add(_HTML_TAIL)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write("\n".join(parts))


def write_port_csv(plan: PortPlan, path: str) -> None:
    with open(path, "w", encoding="utf-8-sig", newline="") as fh:
        writer = csv.writer(fh, delimiter=";")
        writer.writerow(
            [t("XDF name"), t("Status"), t("Name"), t("Units"), t("Your value"),
             t("Target now"), t("Name in target"), t("What matched / what is wrong")]
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
                    entry.status_label,
                    _row_name(entry.title, item.description if item else ""),
                    names.unit(item.value_units) if item else "",
                    rng(entry.phys_tuned),
                    rng(entry.phys_target_before),
                    entry.dst_title,
                    " | ".join(bits),
                ]
            )


# ---------------------------------------------------------------------------
# Tuning a map from a wideband log
# ---------------------------------------------------------------------------


def vetune_console_report(reader: Reader, result) -> str:
    item = result.item
    dec, otype = item.value_decimals, item.value_output_type
    units = names.unit(item.value_units)
    out: List[str] = []
    add = out.append
    add("═" * 78)
    add(t("  MAP TUNING FROM A WIDEBAND LOG"))
    add("═" * 78)
    add(t("Map          : {title}", title=item.title))
    add(f"               {names.explain(item.title, item.description)['name']}")
    add(t("Mode         : {mode}", mode=result.mode))
    add(t("Log samples  : {total}, used {used}", total=result.total_samples,
          used=result.used_samples))
    for reason, count in result.skipped.items():
        if count:
            add(t("               dropped \"{reason}\": {n}", reason=reason, n=count))
    add(t("Coverage     : {pct:.0f}% of map cells", pct=result.coverage * 100))
    add(t("Changed      : {n} of {total} cells", n=result.touched_cells, total=item.cell_count))
    add("")
    for note in result.notes:
        add(f"! {note}")
    if result.notes:
        add("")

    y_labels = _axis_labels(reader, item, "y")
    x_labels = _axis_labels(reader, item, "x")
    width = max(9, max((len(s) for s in x_labels), default=6) + 2)

    add(t("Correction, % (how much to add to VE; empty — not enough data)"))
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
    add(t("Samples per cell (more is more reliable)"))
    add(" " * 10 + "".join(f"{lbl:>{width}}" for lbl in x_labels))
    for r in range(item.rows):
        cells = [f"{result.samples_at(r, c) or '':>{width}}" for c in range(item.cols)]
        add(f"{y_labels[r]:>9} |" + "".join(cells))
    add("")
    add(t("New values ({units})", units=units or t("units")))
    add(" " * 10 + "".join(f"{lbl:>{width}}" for lbl in x_labels))
    for r in range(item.rows):
        cells = [f"{format_number(result.new[r][c], dec, otype):>{width}}"
                 for c in range(item.cols)]
        add(f"{y_labels[r]:>9} |" + "".join(cells))
    add("")
    add(t("· — there is data, but too little or too scattered; the cell is left alone"))

    # Guidance comes primarily from the offline MS4X Wiki copy: it describes
    # this in more detail and with more authority than any of our notes.
    guidance = _wiki_guidance(item.title)
    if guidance:
        add("")
        add("═" * 78)
        add(t("  WHAT THE MS4X WIKI SAYS ABOUT IT"))
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
    """Correction map: colour — how much it went up/down, number of samples below."""
    item = result.item
    x_labels = _axis_labels(reader, item, "x")
    y_labels = _axis_labels(reader, item, "y")
    y_name, x_name = names.axis_names(item.title)
    x_units = names.unit(item.axis_x.units) if item.axis_x else ""
    y_units = names.unit(item.axis_y.units) if item.axis_y else ""

    scale = max((abs(result.correction_percent(r, c))
                 for r in range(item.rows) for c in range(item.cols)), default=1.0) or 1.0

    parts = ["<div class='mapwrap'>"]
    parts.append(
        "<div class='small mapcap'>" + _esc(t("rows — {name}", name=y_name or t("index")))
        + (f" [{_esc(y_units)}]" if y_units else "")
        + " · " + _esc(t("columns — {name}", name=x_name or t("index")))
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
            title = t("was {old}, will be {new}; samples {n}",
                      old=format_number(result.old[r][c], item.value_decimals, 1),
                      new=format_number(result.new[r][c], item.value_decimals, 1), n=samples)
            sub = f"<span class='d'>{samples}</span>" if samples else ""
            parts.append(
                f"<td style='background:{heatmap.hex_color(bg)};"
                f"color:{heatmap.hex_color(fg)}' title='{_esc(title)}'>"
                f"{_esc(main)}{sub}</td>"
            )
        parts.append("</tr>")
    parts.append("</tbody></table>")
    parts.append("<div class='legend'><span class='small'>" + _esc(t("correction, %:")) + "</span>")
    for value, rgb in heatmap.delta_legend_stops(scale):
        fg = heatmap.text_color(rgb)
        parts.append(
            f"<span class='chip' style='background:{heatmap.hex_color(rgb)};"
            f"color:{heatmap.hex_color(fg)}'>{value:+.1f}</span>"
        )
    parts.append("</div><div class='small'>" + _esc(t(
        "the small number in a cell is how many log samples landed there")) + "</div></div>")
    return "".join(parts)


def write_vetune_html(reader: Reader, result, path: str, log_name: str = "") -> None:
    item = result.item
    info = names.explain(item.title, item.description)
    title = t("Map tuning {title}", title=item.title)
    parts: List[str] = [_html_head(title)]
    add = parts.append
    add("<h1>" + _esc(t("Map tuning from a wideband log")) + "</h1>")
    add(
        "<div class='meta'>" + _esc(t("Map:")) + f" <code>{_esc(item.title)}</code> — "
        f"{_esc(info['name'])}<br>"
        + _esc(t("Firmware:")) + f" <code>{_esc(reader.bin.name)}</code>"
        + (("<br>" + _esc(t("Log:")) + f" <code>{_esc(log_name)}</code>") if log_name else "")
        + "<br>" + _esc(t("Report created {date}", date=_now())) + "</div>"
    )
    add("<div class='stats'>")
    add(_stat(result.used_samples, t("samples used")))
    add(_stat(result.total_samples, t("samples in the log")))
    add(_stat(f"{result.coverage * 100:.0f}%", t("map coverage")))
    add(_stat(result.touched_cells, t("cells changed")))
    add("</div>")
    for note in result.notes:
        add("<div class='tune'><b>" + _esc(t("Attention:")) + f"</b> {_esc(note)}</div>")
    add("<section><h2>" + _esc(t("Proposed correction")) + "</h2>")
    add(_tune_map_html(reader, result))
    add("</section>")
    add("<section><h2>" + _esc(t("The map now")) + "</h2>")
    add("<div class='small'>" + _esc(t("Coloured by value — the map before the edit.")) + "</div>")
    add(render_map_html(reader, item))
    add("</section>")

    guidance = _wiki_guidance(item.title)
    if guidance:
        add("<section><h2>" + _esc(t("What the MS4X Wiki says about it"))
            + f" <span class='badge'>{len(guidance)}</span></h2>")
        add("<div class='wikibox'>")
        for section in guidance[:6]:
            add(f"<div class='wikihead'>{_esc(section.page)} / "
                f"{_esc(section.heading)}</div>")
            shown = translate_wiki(section.text)
            for line in shown.split("\n"):
                if line.strip():
                    add(f"<p class='wikitext'>{_esc(line.strip())}</p>")
            for warning in section.caution_lines[:4]:
                add(f"<p class='wikiwarn'>⚠ {_esc(translate_wiki(warning))}</p>")
            if shown == section.text:
                add(f"<p class='small'><a href='{_esc(section.url)}'>"
                    f"{_esc(section.url)}</a></p>")
                continue
            add("<details class='orig'><summary>" + _esc(t("original (English)")) + "</summary>")
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
    out.append(t("  PATCHES: {title}", title=patchlist.title))
    out.append(t("  Firmware: {name}", name=binf.name))
    out.append("═" * 78)
    applied = [s for s in statuses if s.state == PATCH_APPLIED]
    out.append(t("Applied {n} of {total}", n=len(applied), total=len(statuses)))
    out.append("")

    by_cat: Dict[str, List[PatchStatus]] = {}
    for status in statuses:
        cat_names = ([patchlist.category_name(c) for c in status.patch.categories]
                     or [t("<no category>")])
        cat = ", ".join(names.category(n) for n in cat_names)
        by_cat.setdefault(cat, []).append(status)

    for cat in sorted(by_cat):
        out.append(_LINE)
        out.append(f"  {cat.upper()}")
        out.append(_LINE)
        for status in by_cat[cat]:
            mark = _PATCH_MARK.get(status.state, "[?]")
            out.append(f"{mark} {status.patch.title}  — {status.label}")
            desc = names.description(status.patch.description)
            if desc:
                out.append(f"     {desc}")
            for detail in status.details[:3]:
                out.append(f"     ! {detail}")
        out.append("")
    return "\n".join(out)
