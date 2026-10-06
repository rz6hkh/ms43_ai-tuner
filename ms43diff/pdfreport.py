# -*- coding: utf-8 -*-
"""
PDF report export (reportlab).

The only external dependency in the whole project, and only for this file: if
reportlab is not installed, everything else keeps working and the export
command says so plainly.

Maps are drawn as vectors with the same colours as the HTML and the program
window (the heatmap module), so a printed report looks like the screen.
Landscape pages: maps are wide, 16 columns do not fit a portrait page.

Cyrillic: out of the box reportlab only does latin-1, so a system Windows TTF
font is used. If none is found we fall back to the built-in Helvetica and warn
that Russian text may not render.
"""

from __future__ import annotations

import os
from typing import List, Optional, Sequence, Tuple

from . import heatmap, names
from .binfile import Reader, format_number
from .compare import Change, CompareResult
from .crossdiff import PortPlan
from .i18n import t
from .xdf import OUT_TEXT, Item, XdfFile

try:  # reportlab is optional — everything but this module works without it
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4, landscape
    from reportlab.lib.units import mm
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    from reportlab.pdfgen import canvas as pdfcanvas

    HAVE_REPORTLAB = True
except ImportError:  # pragma: no cover
    HAVE_REPORTLAB = False


class PdfUnavailable(RuntimeError):
    """reportlab is not installed."""


# Font candidates: regular and bold
_FONT_CANDIDATES: Sequence[Tuple[str, str, str]] = (
    ("DejaVuSans", "DejaVuSans.ttf", "DejaVuSans-Bold.ttf"),
    ("SegoeUI", "segoeui.ttf", "segoeuib.ttf"),
    ("Arial", "arial.ttf", "arialbd.ttf"),
    ("Tahoma", "tahoma.ttf", "tahomabd.ttf"),
    ("Verdana", "verdana.ttf", "verdanab.ttf"),
)

_FONT_DIRS = (
    os.path.join(os.environ.get("WINDIR", r"C:\Windows"), "Fonts"),
    os.path.join(os.environ.get("LOCALAPPDATA", ""), "Microsoft", "Windows", "Fonts"),
    "/usr/share/fonts/truetype/dejavu",
    "/Library/Fonts",
)

_registered: Optional[Tuple[str, str]] = None


def _register_font() -> Tuple[str, str]:
    """Pick a font with Cyrillic. Returns (regular, bold)."""
    global _registered
    if _registered is not None:
        return _registered
    for name, regular, bold in _FONT_CANDIDATES:
        for folder in _FONT_DIRS:
            if not folder:
                continue
            reg_path = os.path.join(folder, regular)
            if not os.path.isfile(reg_path):
                continue
            try:
                pdfmetrics.registerFont(TTFont(name, reg_path))
            except Exception:  # noqa: BLE001 - a broken font file must not break the report
                continue
            bold_path = os.path.join(folder, bold)
            bold_name = name
            if os.path.isfile(bold_path):
                try:
                    pdfmetrics.registerFont(TTFont(name + "-Bold", bold_path))
                    bold_name = name + "-Bold"
                except Exception:  # noqa: BLE001
                    bold_name = name
            _registered = (name, bold_name)
            return _registered
    _registered = ("Helvetica", "Helvetica-Bold")
    return _registered


# ---------------------------------------------------------------------------


class _Page:
    """Simple top-down layout with automatic page breaks."""

    MARGIN = 12 * mm

    def __init__(self, path: str, title: str, subtitle: str = ""):
        self.font, self.bold = _register_font()
        self.width, self.height = landscape(A4)
        self.c = pdfcanvas.Canvas(path, pagesize=landscape(A4))
        self.c.setTitle(title)
        self.title = title
        self.subtitle = subtitle
        self.page_no = 0
        self.y = 0.0
        self._new_page(first=True)

    # ------------------------------------------------------------------
    def _new_page(self, first: bool = False) -> None:
        if not first:
            self._footer()
            self.c.showPage()
        self.page_no += 1
        self.y = self.height - self.MARGIN
        if self.page_no > 1:
            self.c.setFont(self.font, 7)
            self.c.setFillColorRGB(0.55, 0.55, 0.55)
            self.c.drawString(self.MARGIN, self.height - self.MARGIN + 3 * mm, self.title)
            self.y -= 2 * mm

    def _footer(self) -> None:
        self.c.setFont(self.font, 7)
        self.c.setFillColorRGB(0.55, 0.55, 0.55)
        self.c.drawRightString(self.width - self.MARGIN, self.MARGIN - 5 * mm,
                               t("page {n}", n=self.page_no))

    def need(self, height: float) -> None:
        if self.y - height < self.MARGIN:
            self._new_page()

    # ------------------------------------------------------------------
    def heading(self, text: str, size: int = 13, gap: float = 5 * mm) -> None:
        self.need(size + gap)
        self.c.setFont(self.bold, size)
        self.c.setFillColorRGB(0.1, 0.12, 0.14)
        self.c.drawString(self.MARGIN, self.y - size, text)
        self.y -= size + gap

    def text(self, content: str, size: int = 8.5, indent: float = 0.0,
             gray: float = 0.25, gap: float = 1.6 * mm) -> None:
        max_width = self.width - 2 * self.MARGIN - indent
        for line in self._wrap(content, size, max_width):
            self.need(size + gap)
            self.c.setFont(self.font, size)
            self.c.setFillColorRGB(gray, gray, gray)
            self.c.drawString(self.MARGIN + indent, self.y - size, line)
            self.y -= size + gap

    def _wrap(self, content: str, size: float, max_width: float) -> List[str]:
        out: List[str] = []
        for paragraph in str(content).split("\n"):
            words = paragraph.split()
            if not words:
                out.append("")
                continue
            line = words[0]
            for word in words[1:]:
                probe = line + " " + word
                if self.c.stringWidth(probe, self.font, size) <= max_width:
                    line = probe
                else:
                    out.append(line)
                    line = word
            out.append(line)
        return out

    def rule(self, gap: float = 3 * mm) -> None:
        self.need(gap * 2)
        self.c.setStrokeColorRGB(0.85, 0.87, 0.89)
        self.c.setLineWidth(0.4)
        self.c.line(self.MARGIN, self.y, self.width - self.MARGIN, self.y)
        self.y -= gap

    def save(self) -> None:
        self._footer()
        self.c.save()


# ---------------------------------------------------------------------------


def _axis_labels(reader: Reader, item: Item, which: str) -> List[str]:
    axis = item.axis_x if which == "x" else item.axis_y
    count = item.cols if which == "x" else item.rows
    values = reader.axis_values(item, which)
    if not values:
        return [str(i) for i in range(count)]
    decimals = axis.decimals if axis else 0
    return [format_number(v, decimals, 1) for v in values[:count]]


def _draw_map(page: _Page, reader: Reader, item: Item,
              reader_b: Optional[Reader] = None) -> None:
    """Draw a map with the same colours as the HTML and the window."""
    before = reader.matrix(item)
    if not before:
        return
    after = reader_b.matrix(item) if reader_b is not None else None
    dec, otype = item.value_decimals, item.value_output_type
    units = names.unit(item.value_units)

    x_labels = _axis_labels(reader, item, "x")
    y_labels = _axis_labels(reader, item, "y")
    y_name, x_name = names.axis_names(item.title)

    rows, cols = item.rows, item.cols
    avail = page.width - 2 * page.MARGIN
    label_w = 16 * mm
    cell_w = min(16 * mm, max(8 * mm, (avail - label_w) / max(1, cols)))
    cell_h = 5.6 * mm if after is None else 6.6 * mm
    table_h = rows * cell_h + 6 * mm
    page.need(table_h + 16 * mm)

    caption = []
    if rows > 1:
        caption.append(t("rows — {name}", name=y_name or t("index")))
    if cols > 1:
        caption.append(t("columns — {name}", name=x_name or t("index")))
    if caption:
        page.text(" · ".join(caption), size=7.5, gray=0.45, gap=1.2 * mm)

    top = page.y
    # header with the X axis values
    page.c.setFont(page.font, 6)
    page.c.setFillColorRGB(0.45, 0.45, 0.45)
    for c in range(cols):
        x = page.MARGIN + label_w + c * cell_w
        page.c.drawRightString(x + cell_w - 1.2 * mm, top - 3.2 * mm, x_labels[c])
    top -= 4.6 * mm

    if after is not None:
        scale = heatmap.delta_scale(before, after)
        low = high = 0.0
    else:
        scale = 0.0
        low, high = heatmap.value_range(before)

    for r in range(rows):
        y = top - (r + 1) * cell_h
        page.c.setFont(page.font, 6)
        page.c.setFillColorRGB(0.45, 0.45, 0.45)
        page.c.drawRightString(page.MARGIN + label_w - 1.5 * mm,
                               y + cell_h / 2 - 1.8, y_labels[r])
        for c in range(cols):
            a = before[r][c]
            if after is not None:
                b = after[r][c]
                delta = b - a
                rgb = heatmap.delta_color(delta, scale)
                main = format_number(b, dec, otype)
                sub = ("" if not delta else
                       ("+" if delta > 0 else "") + format_number(delta, dec, otype))
            else:
                rgb = heatmap.value_color(a, low, high)
                main = format_number(a, dec, otype)
                sub = ""
            x = page.MARGIN + label_w + c * cell_w
            page.c.setFillColorRGB(*[v / 255 for v in rgb])
            page.c.rect(x, y, cell_w - 0.5, cell_h - 0.5, stroke=0, fill=1)
            fg = heatmap.text_color(rgb)
            page.c.setFillColorRGB(*[v / 255 for v in fg])
            if sub:
                page.c.setFont(page.font, 5.6)
                page.c.drawRightString(x + cell_w - 1.2 * mm, y + cell_h - 2.9 * mm, main)
                page.c.setFont(page.font, 4.8)
                page.c.drawRightString(x + cell_w - 1.2 * mm, y + 1.0 * mm, sub)
            else:
                page.c.setFont(page.font, 5.8)
                page.c.drawRightString(x + cell_w - 1.2 * mm,
                                       y + cell_h / 2 - 1.9, main)
    page.y = top - rows * cell_h - 2 * mm

    # legend
    stops = (heatmap.delta_legend_stops(scale) if after is not None
             else heatmap.legend_stops(low, high))
    label = (t("change") if after is not None else t("value")) + (f", {units}" if units else "")
    page.need(8 * mm)
    page.c.setFont(page.font, 6.5)
    page.c.setFillColorRGB(0.45, 0.45, 0.45)
    page.c.drawString(page.MARGIN, page.y - 4 * mm, label + ":")
    x = page.MARGIN + page.c.stringWidth(label + ":", page.font, 6.5) + 2 * mm
    for value, rgb in stops:
        chip_w = 13 * mm
        page.c.setFillColorRGB(*[v / 255 for v in rgb])
        page.c.rect(x, page.y - 5.2 * mm, chip_w - 0.6 * mm, 4.4 * mm, stroke=0, fill=1)
        fg = heatmap.text_color(rgb)
        page.c.setFillColorRGB(*[v / 255 for v in fg])
        page.c.setFont(page.font, 5.8)
        page.c.drawCentredString(x + (chip_w - 0.6 * mm) / 2, page.y - 4.1 * mm,
                                 format_number(value, dec, otype))
        x += chip_w
    page.y -= 8 * mm


# ---------------------------------------------------------------------------


def write_compare_pdf(result: CompareResult, path: str, with_maps: bool = True) -> None:
    """PDF report comparing two firmware files of the same version."""
    if not HAVE_REPORTLAB:
        raise PdfUnavailable(_no_reportlab())
    title = t("MS43 firmware comparison: {a} / {b}", a=result.bin_a.name, b=result.bin_b.name)
    page = _Page(path, title)

    page.heading(t("MS43 firmware comparison"), size=16, gap=4 * mm)
    page.text(f"A: {result.bin_a.name}  ({result.bin_a.size_kb} {t('KB')})", gray=0.3)
    page.text(f"B: {result.bin_b.name}  ({result.bin_b.size_kb} {t('KB')})", gray=0.3)
    page.text(f"XDF: {result.xdf.title} v{result.xdf.file_version} · "
              f"{result.xdf.author} · "
              + t("offset {label}", label=result.reader_a.offset.label), gray=0.45)
    page.text(t("Report created {date}", date=_now()), gray=0.55)
    for tag, reader in (("A", result.reader_a), ("B", result.reader_b)):
        warning = reader.version_warning()
        if warning:
            page.text(t("WARNING ({tag}): {text}", tag=tag, text=warning), gray=0.0)
    page.y -= 2 * mm
    page.text(
        t("Parameters changed: {changed}    Same: {same}    Bytes changed: {bytes}    "
          "Code edit blocks: {blocks}", changed=result.changed_params,
          same=result.identical, bytes=result.total_bytes_changed,
          blocks=len(result.code_blocks)),
        size=9.5, gray=0.15,
    )
    page.rule()

    by_cat = {}
    for change in result.changes:
        by_cat.setdefault(item_categories(result.xdf, change.item), []).append(change)

    for cat in sorted(by_cat, key=lambda c: (-len(by_cat[c]), c)):
        page.heading(f"{cat}  ({len(by_cat[cat])})", size=11, gap=3 * mm)
        for change in by_cat[cat]:
            row = change_row(result.xdf, change)
            page.need(22 * mm)
            page.c.setFont(page.bold, 9)
            page.c.setFillColorRGB(0.08, 0.1, 0.12)
            page.c.drawString(page.MARGIN, page.y - 9, row["title"])
            page.y -= 12
            page.text(row["name"], size=8.5, gray=0.2)
            if row["desc"]:
                page.text(row["desc"], size=8, gray=0.35)
            unit_suffix = f" {row['units']}" if row["units"] else ""
            page.text(t("Value: {value}", value=row["summary"] + unit_suffix), size=8.5, gray=0.1)
            page.text(
                t("{shape} · XDF address {address} · file {offset} · {scaling}",
                  shape=row["shape"], address=row["address"], offset=row["offset"],
                  scaling=row["scaling"]), size=7.5, gray=0.5,
            )
            if row["note"]:
                page.text(t("What it does: {text}", text=row["note"]), size=8, indent=4 * mm, gray=0.3)
            if row["tune"]:
                page.text(t("How to tune: {text}", text=row["tune"]), size=8, indent=4 * mm, gray=0.3)
            if (with_maps and change.item.cell_count > 1
                    and change.item.value_output_type != OUT_TEXT):
                page.y -= 1 * mm
                _draw_map(page, result.reader_a, change.item, result.reader_b)
            page.y -= 2 * mm

    if result.code_blocks:
        page.heading(t("Edits outside XDF maps (code / patches)"), size=11)
        for block in result.code_blocks:
            page.text(t("0x{start:06X}–0x{end:06X}   {n} bytes", start=block.start,
                        end=block.end, n=block.length),
                      size=8, gray=0.3)
    page.save()


def write_map_pdf(reader: Reader, items: Sequence[Item], path: str,
                  reader_b: Optional[Reader] = None) -> None:
    """PDF with one or more complete maps."""
    if not HAVE_REPORTLAB:
        raise PdfUnavailable(_no_reportlab())
    title = t("MS43 maps: {names}", names=", ".join(i.title for i in items[:3]))
    page = _Page(path, title)
    for item in items:
        info = names.explain(item.title, item.description)
        page.heading(item.title, size=12, gap=2.5 * mm)
        page.text(info["name"], size=9, gray=0.15)
        if info["desc"]:
            page.text(info["desc"], size=8, gray=0.35)
        if info["note"]:
            page.text(t("What it does: {text}", text=info["note"]), size=8, gray=0.3)
        if info["tune"]:
            page.text(t("How to tune: {text}", text=info["tune"]), size=8, gray=0.3)
        data = item.data
        if data is not None and data.address is not None:
            page.text(
                t("{shape} · XDF address 0x{address:X} · file 0x{offset:X} · {scaling}",
                  shape=item.shape_str, address=data.address,
                  offset=reader.file_offset(data.address),
                  scaling=item.value_equation.describe(names.unit(item.value_units))),
                size=7.5, gray=0.5,
            )
        page.y -= 1.5 * mm
        _draw_map(page, reader, item, reader_b)
        page.rule()
    page.save()


def write_port_pdf(plan: PortPlan, path: str) -> None:
    """PDF of the settings port plan between software versions."""
    if not HAVE_REPORTLAB:
        raise PdfUnavailable(_no_reportlab())
    page = _Page(path, t("MS43 settings port plan"))
    page.heading(t("Settings port plan between software versions"), size=16, gap=4 * mm)
    page.text(t("Source stock: {name}", name=plan.bin_stock.name), gray=0.3)
    page.text(t("Your tune: {name}  ({xdf})", name=plan.bin_tuned.name, xdf=plan.xdf_src.title),
              gray=0.3)
    page.text(t("Target firmware: {name}  ({xdf})", name=plan.bin_target.name,
                xdf=plan.xdf_dst.title), gray=0.3)
    page.text(t("Report created {date}", date=_now()), gray=0.55)
    page.y -= 2 * mm
    page.text(
        t("The program only builds a plan and writes nothing to the firmware. Make all "
          "edits by hand in TunerPro and recalculate the checksums there."),
        size=9, gray=0.0,
    )
    page.y -= 2 * mm
    page.text(
        t("Safe by bytes: {bytes}    Safe by name: {name}    With a warning: {warned}",
          bytes=len(plan.safe_bytes), name=len(plan.safe_name), warned=len(plan.warned)),
        size=9.5, gray=0.15,
    )
    page.rule()

    for heading, entries in (
        (t("Safe — can be ported one-to-one"), plan.safe_bytes),
        (t("Safe by name — port the physical value by hand"), plan.safe_name),
        (t("With a warning — sort it out by hand"), plan.warned),
    ):
        if not entries:
            continue
        page.heading(f"{heading}  ({len(entries)})", size=11, gap=3 * mm)
        for entry in entries:
            item = entry.item_dst or entry.item_src
            page.need(14 * mm)
            page.c.setFont(page.bold, 9)
            page.c.setFillColorRGB(0.08, 0.1, 0.12)
            page.c.drawString(page.MARGIN, page.y - 9, entry.title)
            page.y -= 12
            page.text(names.explain(entry.title, item.description if item else "")["name"],
                      size=8.5, gray=0.2)
            units = names.unit(item.value_units) if item else ""
            page.text(f"{entry.summary()} {units}".strip(), size=8.5, gray=0.1)
            if entry.dst_title and entry.dst_title != entry.title:
                page.text(t("in the target version: {name}", name=entry.dst_title), size=8, gray=0.4)
            for bit in (entry.match_bits if entry.safe else entry.warn_bits):
                page.text(f"• {bit}", size=7.5, indent=4 * mm, gray=0.4)
            page.y -= 1.5 * mm
    page.save()


def _no_reportlab() -> str:
    return t("reportlab is not installed. Run: python -m pip install reportlab")


# imported last: report pulls in pdfreport only on demand
from .report import _now, change_row, item_categories  # noqa: E402
