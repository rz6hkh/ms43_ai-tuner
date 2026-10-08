# -*- coding: utf-8 -*-
"""
ms43diff command line.

    python -m ms43diff diff  A.bin B.bin -x def.xdf --html report.html
    python -m ms43diff show  -x def.xdf -b A.bin id_n_max_mt__gear
    python -m ms43diff find  -x def.xdf "rev limit"
    python -m ms43diff list  -x def.xdf -b A.bin --category Ignition
    python -m ms43diff dump  -x def.xdf -b A.bin -o values.csv
    python -m ms43diff patches -x patchlist.xdf -b A.bin
    python -m ms43diff info  -x def.xdf -b A.bin

Add --lang en or --lang ru to choose the output language.
"""

from __future__ import annotations

import argparse
import csv
import os
import re
import sys
from typing import Iterable, List, Optional, Sequence

from . import __version__, names, report, ru
from .binfile import BinFile, Reader, format_number
from .compare import PATCH_APPLIED, check_patches, compare_bins, compare_many
from .crossdiff import build_port_plan, cross_compare
from .i18n import LANGS, set_lang, t
from .xdf import Item, XdfFile


# ---------------------------------------------------------------------------


def _force_utf8() -> None:
    """The Windows console defaults to a legacy code page that breaks non-ASCII text.

    Switching the Python stream is not enough: the console itself must be set
    to UTF-8, otherwise classic conhost prints garbage.
    """
    if os.name == "nt":
        try:
            import ctypes

            ctypes.windll.kernel32.SetConsoleOutputCP(65001)
            ctypes.windll.kernel32.SetConsoleCP(65001)
        except Exception:
            pass
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass


def _echo(text: str) -> None:
    print(text)


def _load_xdf(path: Optional[str]) -> XdfFile:
    # To avoid passing a long -x path every time, set the MS43_XDF
    # environment variable once.
    if not path:
        path = os.environ.get("MS43_XDF", "")
    if not path:
        raise SystemExit(t("No XDF given: add -x path\\to\\file.xdf "
                           "or set the MS43_XDF environment variable."))
    if not os.path.isfile(path):
        raise SystemExit(t("XDF file not found: {path}", path=path))
    return XdfFile(path)


def _load_bin(path: str) -> BinFile:
    if not os.path.isfile(path):
        raise SystemExit(t("BIN file not found: {path}", path=path))
    return BinFile(path)


def _matches(item: Item, xdf: XdfFile, pattern: Optional[re.Pattern],
             category: Optional[str]) -> bool:
    if category:
        cats = [names.category(n) for n in xdf.category_names(item)]
        cats += [ru.category_ru(n) for n in xdf.category_names(item)]
        cats += xdf.category_names(item)
        if not any(category.lower() in c.lower() for c in cats):
            return False
    if pattern:
        # search both languages, whatever the UI language is
        haystack = " ".join(
            [
                item.title,
                item.description,
                names.decode(item.title),
                ru.name_ru(item.title),
                ru.description_ru(item.description),
                ru.PARAM_RU.get(item.title, {}).get("ru", ""),
            ]
        )
        if not pattern.search(haystack):
            return False
    return True


def _compile(pattern: Optional[str]) -> Optional[re.Pattern]:
    if not pattern:
        return None
    try:
        return re.compile(pattern, re.IGNORECASE)
    except re.error:
        return re.compile(re.escape(pattern), re.IGNORECASE)


# ---------------------------------------------------------------------------
# diff
# ---------------------------------------------------------------------------


def cmd_diff(args: argparse.Namespace) -> int:
    xdf = _load_xdf(args.xdf)
    bin_a = _load_bin(args.bin_a)
    bin_b = _load_bin(args.bin_b)

    result = compare_bins(
        xdf,
        bin_a,
        bin_b,
        include_axes=args.include_axes,
        include_checksums=not args.no_checksums,
        raw_scan=not args.no_raw,
        max_gap=args.gap,
    )

    pattern = _compile(args.filter)
    if pattern or args.category:
        result.changes = [
            c for c in result.changes if _matches(c.item, xdf, pattern, args.category)
        ]

    # a software version mismatch warning matters even in quiet mode
    for tag, reader in (("A", result.reader_a), ("B", result.reader_b)):
        warning = reader.version_warning()
        if warning and args.quiet:
            print(t("WARNING ({tag}): {text}", tag=tag, text=warning), file=sys.stderr)

    if not args.quiet:
        _echo(
            report.console_report(
                result,
                limit=args.limit,
                verbose=args.verbose,
                show_english=args.english,
            )
        )

    if args.html:
        report.write_html(result, args.html)
        _echo(t("HTML report: {path}", path=os.path.abspath(args.html)))
    if args.csv:
        report.write_csv(result, args.csv)
        _echo(t("CSV report: {path}", path=os.path.abspath(args.csv)))
    if args.json:
        report.write_json(result, args.json)
        _echo(t("JSON report: {path}", path=os.path.abspath(args.json)))
    if args.md:
        report.write_markdown(result, args.md)
        _echo(t("Markdown report: {path}", path=os.path.abspath(args.md)))
    if args.pdf:
        _write_pdf(lambda p: _pdf().write_compare_pdf(result, p, with_maps=not args.no_maps),
                   args.pdf)

    return 0


def _pdf():
    from . import pdfreport

    return pdfreport


def _write_pdf(builder, path: str) -> None:
    from .pdfreport import PdfUnavailable

    try:
        builder(path)
    except PdfUnavailable as exc:
        _echo(t("PDF not created: {error}", error=exc))
        return
    _echo(t("PDF report: {path}", path=os.path.abspath(path)))


# ---------------------------------------------------------------------------
# show
# ---------------------------------------------------------------------------


def cmd_show(args: argparse.Namespace) -> int:
    xdf = _load_xdf(args.xdf)
    binf = _load_bin(args.bin)
    reader = Reader(xdf, binf)
    reader_b = None
    if args.compare:
        reader_b = Reader(xdf, _load_bin(args.compare))

    targets: List[Item] = []
    exact = xdf.by_title(args.name)
    if exact is not None:
        targets.append(exact)
    else:
        pattern = _compile(args.name)
        for item in xdf.readable_items(include_axes=True):
            if pattern and pattern.search(item.title):
                targets.append(item)
        if not targets:
            for item in xdf.readable_items(include_axes=True):
                if _matches(item, xdf, pattern, None):
                    targets.append(item)

    if not targets:
        _echo(t("Nothing found for: {query}", query=args.name))
        return 1
    if len(targets) > args.max:
        _echo(t("{n} matches found, showing the first {max}.", n=len(targets), max=args.max))
        _echo(t("Refine the query or raise --max.") + "\n")
        targets = targets[: args.max]

    for item in targets:
        _echo(report.render_table(reader, item, reader_b))
        _echo("")
    if args.pdf:
        _write_pdf(lambda p: _pdf().write_map_pdf(reader, targets, p, reader_b), args.pdf)
    return 0


# ---------------------------------------------------------------------------
# find
# ---------------------------------------------------------------------------


def cmd_find(args: argparse.Namespace) -> int:
    xdf = _load_xdf(args.xdf)
    pattern = _compile(args.query)
    reader = Reader(xdf, _load_bin(args.bin)) if args.bin else None

    found = 0
    for item in xdf.readable_items(include_axes=args.include_axes):
        if not _matches(item, xdf, pattern, args.category):
            continue
        found += 1
        if args.limit and found > args.limit:
            _echo(t("... and more. Over {n} matches, refine the query or use --limit 0.",
                    n=args.limit))
            break
        info = names.explain(item.title, item.description)
        cats = report.item_categories(xdf, item)
        line = f"{item.title}"
        _echo(line)
        _echo(f"    {info['name']}   [{item.shape_str}, {cats}]")
        if info["desc"]:
            _echo(f"    {info['desc']}")
        if reader is not None:
            summary = reader.summary(item)
            units = names.unit(item.value_units)
            if summary is not None:
                _echo(t("    value: {value}", value=f"{summary} {units}".rstrip()))
        addr = item.address
        if addr is not None:
            _echo(t("    XDF address 0x{addr:X}", addr=addr))
        _echo("")
    if not found:
        _echo(t("Nothing found."))
        return 1
    _echo(t("Found: {n}", n=found))
    return 0


# ---------------------------------------------------------------------------
# list
# ---------------------------------------------------------------------------


def cmd_list(args: argparse.Namespace) -> int:
    xdf = _load_xdf(args.xdf)
    reader = Reader(xdf, _load_bin(args.bin)) if args.bin else None
    pattern = _compile(args.filter)

    if args.categories:
        _echo(t("Categories in this XDF:"))
        counts = {}
        for item in xdf.readable_items(include_axes=True):
            for name in xdf.category_names(item):
                counts[name] = counts.get(name, 0) + 1
        for name in sorted(counts, key=lambda n: (-counts[n], n)):
            _echo(f"  {counts[name]:>5}  {names.category(name)}   ({name})")
        return 0

    rows = 0
    for item in xdf.readable_items(include_axes=args.include_axes):
        if not _matches(item, xdf, pattern, args.category):
            continue
        rows += 1
        if args.limit and rows > args.limit:
            _echo(t("... showing the first {n}. Use --limit 0 for the full list.", n=args.limit))
            break
        value = ""
        if reader is not None:
            summary = reader.summary(item)
            if summary is not None:
                value = f"{summary} {names.unit(item.value_units)}".strip()
        name = names.name(item.title)
        _echo(f"{item.title:<44} {item.shape_str:<10} {value:<28} {name}")
    if not rows:
        _echo(t("Nothing found."))
        return 1
    return 0


# ---------------------------------------------------------------------------
# dump
# ---------------------------------------------------------------------------


def cmd_dump(args: argparse.Namespace) -> int:
    xdf = _load_xdf(args.xdf)
    binf = _load_bin(args.bin)
    reader = Reader(xdf, binf)
    pattern = _compile(args.filter)

    count = 0
    with open(args.out, "w", encoding="utf-8-sig", newline="") as fh:
        writer = csv.writer(fh, delimiter=";")
        writer.writerow(
            [t("XDF name"), t("Name"), t("Category"), t("Description"), t("Type"),
             t("Value"), t("Units"), t("XDF address"), t("Offset"), t("Scale")]
        )
        for item in xdf.readable_items(include_axes=args.include_axes):
            if not _matches(item, xdf, pattern, args.category):
                continue
            summary = reader.summary(item)
            if summary is None:
                continue
            count += 1
            info = names.explain(item.title, item.description)
            units = names.unit(item.value_units)
            offset = reader.item_offset(item)
            writer.writerow(
                [
                    item.title,
                    info["name"],
                    report.item_categories(xdf, item),
                    info["desc"],
                    item.shape_str,
                    summary,
                    units,
                    f"0x{item.address:X}" if item.address is not None else "",
                    f"0x{offset:X}" if offset is not None else "",
                    item.value_equation.describe(units),
                ]
            )
    _echo(t("Exported {n} parameters to {path}", n=count, path=os.path.abspath(args.out)))
    return 0


# ---------------------------------------------------------------------------
# xdiff — comparing different software versions
# ---------------------------------------------------------------------------


def cmd_xdiff(args: argparse.Namespace) -> int:
    xdf_a = _load_xdf(args.xdf_a)
    xdf_b = _load_xdf(args.xdf_b)
    bin_a = _load_bin(args.bin_a)
    bin_b = _load_bin(args.bin_b)

    result = cross_compare(
        xdf_a, bin_a, xdf_b, bin_b,
        include_axes=args.include_axes,
        include_checksums=args.checksums,
    )
    pattern = _compile(args.filter)
    if pattern or args.category:
        keep = []
        for row in result.rows:
            item = row.item
            if item is not None and _matches(item, xdf_a, pattern, args.category):
                keep.append(row)
        result.rows = keep

    if not args.quiet:
        _echo(report.cross_console_report(result, limit=args.limit))
    if args.html:
        report.write_cross_html(result, args.html)
        _echo(t("HTML report: {path}", path=os.path.abspath(args.html)))
    return 0


# ---------------------------------------------------------------------------
# port — porting settings between versions
# ---------------------------------------------------------------------------


def cmd_port(args: argparse.Namespace) -> int:
    xdf_src = _load_xdf(args.xdf_src)
    xdf_dst = _load_xdf(args.xdf_dst)
    plan = build_port_plan(
        xdf_src,
        _load_bin(args.stock),
        _load_bin(args.tuned),
        xdf_dst,
        _load_bin(args.target),
        include_axes=args.include_axes,
        include_checksums=args.checksums,
    )

    if not args.quiet:
        _echo(report.port_console_report(plan, limit=args.limit, verbose=args.verbose))
    if args.html:
        report.write_port_html(plan, args.html)
        _echo(t("HTML report: {path}", path=os.path.abspath(args.html)))
    if args.csv:
        report.write_port_csv(plan, args.csv)
        _echo(t("CSV report: {path}", path=os.path.abspath(args.csv)))
    if args.pdf:
        _write_pdf(lambda p: _pdf().write_port_pdf(plan, p), args.pdf)
    return 0


# ---------------------------------------------------------------------------
# wiki — offline MS4X reference
# ---------------------------------------------------------------------------


def _wrap_echo(text: str, indent: str = "     ", width: int = 100) -> None:
    for line in text.split("\n"):
        line = line.strip()
        if not line:
            continue
        while len(line) > width:
            cut = line.rfind(" ", 0, width)
            cut = cut if cut > 40 else width
            _echo(f"{indent}{line[:cut]}")
            line = line[cut:].lstrip()
        _echo(f"{indent}{line}")


def _print_section(section, param: Optional[str] = None, english: bool = False) -> None:
    from . import wikicache, wikitrans

    _echo(f"  ── {section.page} / {section.heading}")
    text = wikicache.focused_text(section, param) if param else section.text
    shown = wikitrans.translate_block(text)
    _wrap_echo(shown)
    if english and shown != text:
        _echo(t("     original (English):"))
        _wrap_echo(text, indent="       ")
    _echo(f"     {section.url}")
    _echo("")


def cmd_wiki(args: argparse.Namespace) -> int:
    from . import wikicache

    if args.download:
        _echo(t("Downloading MS4X Wiki pages (needs access to ms4x.net)…"))

        def progress(i, n, name, stage="pages"):
            if stage == "listing":
                _echo(t("Reading the list of pages on the site…"))
            else:
                _echo(f"  [{i}/{n}] {name}")

        result = wikicache.download(progress=progress)
        _echo("")
        _echo(t("Pages downloaded: {n}", n=result["pages"]))
        for name, err in result["errors"]:
            _echo(t("  failed: {name} — {error}", name=name, error=err))
        if not result["written"]:
            _echo(t("Nothing was downloaded; the reference was not changed."))
            _echo(wikicache.offline_hint())
            return 1
        _echo(t("Cache: {path}", path=result["path"]))
        if result["added"]:
            _echo(t("New MS43 pages found on the site and added: {list}",
                    list=", ".join(result["added"])))
        if result["skipped"]:
            _echo(t("New pages not about the MS43, skipped: {n}", n=len(result["skipped"])))
        return 0

    if args.import_file:
        try:
            result = wikicache.import_file(args.import_file)
        except (OSError, ValueError) as exc:
            _echo(str(exc))
            return 1
        _echo(t("Reference imported: {n} pages → {path}", n=result["pages"], path=result["path"]))
        return 0

    if not wikicache.available():
        _echo(t("There is no local reference. On a machine with access to the site run:"))
        _echo("    ms43diff wiki --download")

    info = wikicache.meta()
    if args.list:
        _echo(t("MS4X Wiki reference, snapshot of {date}", date=info.get("fetched", "?")))
        _echo(t("Source: {source}   Folder: {folder}", source=info.get("source"),
                folder=info.get("folder")))
        _echo("")
        for name, title, count in wikicache.page_names():
            _echo(t("  {n:>4} sections   {title}   ({name})", n=count, title=title, name=name))
        return 0

    if args.cautions:
        from . import wikitrans

        sections = wikicache.cautions(args.page)
        _echo("═" * 78)
        _echo(t("  MS4X WIKI WARNINGS — \"how not to break anything\""))
        _echo("═" * 78)
        _echo("")
        for section in sections:
            _echo(f"• {section.page} / {section.heading}")
            for line in section.caution_lines:
                shown = wikitrans.translate_line(line)
                _wrap_echo(shown, indent="    ")
                if args.english and shown != line:
                    _wrap_echo(line, indent="      EN: ")
            _echo(f"    {section.url}")
            _echo("")
        _echo(t("Total: {n} warnings", n=sum(len(s.caution_lines) for s in sections)))
        return 0

    if args.param:
        sections = wikicache.sections_for(args.param)
        if not sections:
            _echo(t("The reference does not mention parameter {name}.", name=args.param))
            return 1
        meanings = wikicache.value_meanings(args.param)
        if meanings:
            from . import wikitrans

            _echo(t("Values of parameter {name}:", name=args.param))
            for key in sorted(meanings):
                _echo(f"  {key} = {wikitrans.translate_line(meanings[key])}")
            _echo("")
        _echo(t("What the MS4X Wiki says about {name}:", name=args.param))
        _echo("")
        for section in sections:
            _print_section(section, param=args.param, english=args.english)
        return 0

    if args.page:
        page = wikicache.page(args.page)
        if page is None:
            _echo(t("Page \"{name}\" not found. List: ms43diff wiki --list", name=args.page))
            return 1
        _echo("═" * 78)
        _echo(f"  {page.title}")
        _echo(t("  {url}   (snapshot {date})", url=page.url, date=page.fetched))
        _echo("═" * 78)
        _echo("")
        for section in page.sections:
            _print_section(section, english=args.english)
        return 0

    if args.query:
        sections = wikicache.search(args.query, limit=args.limit)
        if not sections:
            _echo(t("Nothing found."))
            return 1
        _echo(t("Sections found: {n}", n=len(sections)))
        _echo("")
        for section in sections:
            _print_section(section, english=args.english)
        return 0

    _echo(t("MS4X Wiki reference (local copy)."))
    _echo(t("Snapshot of {date}, pages: {pages}, parameters linked: {params}",
            date=info.get("fetched", "?"), pages=len(wikicache.load()),
            params=len(wikicache.index_parameters())))
    _echo("")
    _echo(t("  ms43diff wiki --list              list of pages"))
    _echo(t("  ms43diff wiki \"lambda\"            full-text search"))
    _echo(t("  ms43diff wiki --page Siemens_MS43 show a whole page"))
    _echo(t("  ms43diff wiki --param c_conf_cat  what the wiki says about a parameter"))
    _echo(t("  ms43diff wiki --cautions          all warnings"))
    _echo(t("  ms43diff wiki --download          update the copy from the site"))
    return 0


# ---------------------------------------------------------------------------
# patches
# ---------------------------------------------------------------------------


def cmd_patches(args: argparse.Namespace) -> int:
    patchlist = _load_xdf(args.xdf)
    if not patchlist.patches:
        _echo(t("{file} has no <XDFPATCH> entries. This command needs a patchlist XDF "
                "(e.g. Siemens_MS43_MS430069_Community_Patchlist_*.xdf).",
                file=os.path.basename(args.xdf)))
        return 1
    binf = _load_bin(args.bin)
    statuses = check_patches(patchlist, binf)
    if args.only_applied:
        statuses = [s for s in statuses if s.state == PATCH_APPLIED]
    _echo(report.patches_report(statuses, patchlist, binf))
    return 0


# ---------------------------------------------------------------------------
# info
# ---------------------------------------------------------------------------


def cmd_info(args: argparse.Namespace) -> int:
    xdf = _load_xdf(args.xdf)
    _echo("═" * 78)
    _echo(f"  XDF: {os.path.basename(xdf.path)}")
    _echo("═" * 78)
    _echo(t("Title         : {text}", text=xdf.title))
    _echo(t("File version  : {text}", text=xdf.file_version))
    _echo(t("Author        : {text}", text=xdf.author))
    if xdf.description:
        _echo(t("Description   : {text}", text=xdf.description))
    sign = "-" if xdf.base_subtract else "+"
    _echo(f"BASEOFFSET    : {sign}0x{xdf.base_offset:X}")
    _echo(t("Region size   : 0x{size:X} ({kb} KB)", size=xdf.region_size,
            kb=xdf.region_size // 1024))
    _echo(t("Categories    : {n}", n=len(xdf.categories)))

    tables = sum(1 for i in xdf.items if i.kind == "table")
    consts = sum(1 for i in xdf.items if i.kind == "constant")
    axes = sum(1 for i in xdf.items if i.is_axis_definition)
    _echo(t("Objects       : {n}  (tables {tables}, constants {consts}, of them axes {axes})",
            n=len(xdf.items), tables=tables, consts=consts, axes=axes))
    _echo(t("Patches       : {n}", n=len(xdf.patches)))
    _echo("")

    if not args.bin:
        return 0

    binf = _load_bin(args.bin)
    reader = Reader(xdf, binf)
    total = 0
    ok = 0
    for item in xdf.readable_items(include_axes=True):
        total += 1
        if reader.in_range(item):
            ok += 1
    _echo("─" * 78)
    _echo(t("  Firmware: {name}", name=binf.name))
    _echo("─" * 78)
    _echo(t("Size          : {n} bytes ({kb} KB)", n=len(binf), kb=binf.size_kb))
    _echo(t("Offset        : {label}, fit {pct:.1f}%", label=reader.offset.label,
            pct=reader.offset.fit * 100))
    _echo(t("Readable      : {ok} of {total} objects", ok=ok, total=total))

    # the calibration header shows the firmware version
    header = binf.slice(reader.file_offset(0x0), 0x60)
    if header:
        text = "".join(chr(b) if 32 <= b < 127 else "." for b in header)
        _echo(t("Calib. header : {text}", text=text))
    _echo(t("Software      : {fw}", fw=reader.firmware_id() or t("unknown")))
    warning = reader.version_warning()
    if warning:
        _echo("")
        _echo(t("WARNING: {text}", text=warning))
    return 0


# ---------------------------------------------------------------------------
# multi
# ---------------------------------------------------------------------------


def cmd_multi(args: argparse.Namespace) -> int:
    xdf = _load_xdf(args.xdf)
    bins = [_load_bin(p) for p in args.bins]
    if len(bins) < 2:
        raise SystemExit(t("At least two .bin files are needed"))
    items, table, readers = compare_many(
        xdf, bins, include_axes=args.include_axes,
        include_checksums=not args.no_checksums
    )
    pattern = _compile(args.filter)
    items = [i for i in items if _matches(i, xdf, pattern, args.category)]

    bin_names = [b.name for b in bins]
    widths = [max(18, min(28, len(n))) for n in bin_names]

    _echo("═" * 78)
    _echo(t("  COMPARING SEVERAL FIRMWARE FILES"))
    _echo("═" * 78)
    for idx, name in enumerate(bin_names, 1):
        _echo(f"  {idx}. {name}  ({bins[idx-1].size_kb} {t('KB')})")
    _echo("")
    header = f"{t('Parameter'):<40}" + "".join(f"{str(i+1):>{w}}" for i, w in enumerate(widths))
    _echo(header)
    _echo("─" * len(header))

    shown = 0
    for item in items:
        if args.limit and shown >= args.limit:
            _echo(t("... showing {shown} of {total}", shown=shown, total=len(items)))
            break
        shown += 1
        cells = table[item.title]
        line = f"{item.title:<40}" + "".join(
            f"{(c or '—'):>{w}}" for c, w in zip(cells, widths)
        )
        _echo(line)
        _echo(f"    {names.name(item.title)}")
    _echo("")
    _echo(t("Differing parameters in total: {n}", n=len(items)))
    return 0


# ---------------------------------------------------------------------------


def cmd_gui(args: argparse.Namespace) -> int:
    from .webui import run

    return run()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="ms43diff",
        description=t("Compare Siemens MS43 (BMW M52TU/M54) firmware using an XDF "
                      "definition, with decoded parameter names."),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("--version", action="version", version=f"ms43diff {__version__}")
    parser.add_argument("--lang", choices=LANGS,
                        help=t("interface language (default: saved setting or system language)"))
    sub = parser.add_subparsers(dest="command", required=True)
    xdf_help = t(".xdf definition file (can be set with the MS43_XDF variable)")

    def add_common(p):
        p.add_argument("-x", "--xdf", help=xdf_help)
        p.add_argument("--include-axes", action="store_true",
                       help=t("include axis breakpoint tables (ldp_*)"))
        p.add_argument("--filter", help=t("regular expression on name/description"))
        p.add_argument("--category", help=t("category filter (English or Russian)"))

    # diff
    p = sub.add_parser("diff", help=t("compare two firmware files"))
    add_common(p)
    p.add_argument("bin_a", help=t("first firmware (e.g. stock)"))
    p.add_argument("bin_b", help=t("second firmware (e.g. tune)"))
    p.add_argument("--html", help=t("save an HTML report"))
    p.add_argument("--csv", help=t("save a CSV report"))
    p.add_argument("--json", help=t("save a JSON report"))
    p.add_argument("--md", help=t("save a Markdown report"))
    p.add_argument("--pdf", help=t("save a PDF report (with coloured maps)"))
    p.add_argument("--no-maps", action="store_true",
                   help=t("do not draw maps in the PDF (shorter and lighter)"))
    p.add_argument("-l", "--limit", type=int, default=60,
                   help=t("how many parameters to print to the console (0 — all)"))
    p.add_argument("-v", "--verbose", action="store_true",
                   help=t("show changed map cells"))
    p.add_argument("--english", action="store_true",
                   help=t("show the original description"))
    p.add_argument("--no-checksums", action="store_true",
                   help=t("do not show checksum changes"))
    p.add_argument("--no-raw", action="store_true", help=t("skip the byte-by-byte scan"))
    p.add_argument("--gap", type=int, default=8,
                   help=t("merge byte blocks separated by at most N bytes"))
    p.add_argument("-q", "--quiet", action="store_true", help=t("report files only"))
    p.set_defaults(func=cmd_diff)

    # show
    p = sub.add_parser("show", help=t("show one map/constant with its axes"))
    p.add_argument("-x", "--xdf", help=xdf_help)
    p.add_argument("-b", "--bin", required=True)
    p.add_argument("name", help=t("parameter name or part of it (regex)"))
    p.add_argument("-c", "--compare", help=t("second firmware — mark the differences"))
    p.add_argument("--max", type=int, default=5, help=t("maximum maps at a time"))
    p.add_argument("--pdf", help=t("save the maps to a coloured PDF"))
    p.set_defaults(func=cmd_show)

    # find
    p = sub.add_parser("find", help=t("search parameters by English or Russian text"))
    add_common(p)
    p.add_argument("query", help=t("what to search for"))
    p.add_argument("-b", "--bin", help=t("also show the values from the firmware"))
    p.add_argument("-l", "--limit", type=int, default=40)
    p.set_defaults(func=cmd_find)

    # list
    p = sub.add_parser("list", help=t("list parameters"))
    add_common(p)
    p.add_argument("-b", "--bin", help=t("show the values from the firmware"))
    p.add_argument("-l", "--limit", type=int, default=100)
    p.add_argument("--categories", action="store_true", help=t("list the categories"))
    p.set_defaults(func=cmd_list)

    # dump
    p = sub.add_parser("dump", help=t("export all firmware values to CSV"))
    add_common(p)
    p.add_argument("-b", "--bin", required=True)
    p.add_argument("-o", "--out", default="ms43_dump.csv")
    p.set_defaults(func=cmd_dump)

    # xdiff
    p = sub.add_parser("xdiff", help=t("compare firmware of DIFFERENT software versions (two XDFs)"))
    p.add_argument("bin_a")
    p.add_argument("bin_b")
    p.add_argument("-A", "--xdf-a", required=True, help=t("XDF for the first firmware"))
    p.add_argument("-B", "--xdf-b", required=True, help=t("XDF for the second firmware"))
    p.add_argument("--include-axes", action="store_true")
    p.add_argument("--checksums", action="store_true", help=t("include checksums"))
    p.add_argument("--filter")
    p.add_argument("--category")
    p.add_argument("--html")
    p.add_argument("-l", "--limit", type=int, default=60)
    p.add_argument("-q", "--quiet", action="store_true")
    p.set_defaults(func=cmd_xdiff)

    # port
    p = sub.add_parser("port",
                       help=t("plan for porting edits to firmware of another version (no writing)"))
    p.add_argument("stock", help=t("stock of the source version (reference)"))
    p.add_argument("tuned", help=t("your tuned firmware of the same version"))
    p.add_argument("target", help=t("firmware of the target version to port into"))
    p.add_argument("-A", "--xdf-src", required=True, help=t("XDF of the source version"))
    p.add_argument("-B", "--xdf-dst", required=True, help=t("XDF of the target version"))
    p.add_argument("--html")
    p.add_argument("--csv")
    p.add_argument("--pdf")
    p.add_argument("--include-axes", action="store_true")
    p.add_argument("--checksums", action="store_true")
    p.add_argument("-l", "--limit", type=int, default=0)
    p.add_argument("-v", "--verbose", action="store_true")
    p.add_argument("-q", "--quiet", action="store_true")
    p.set_defaults(func=cmd_port)

    # wiki
    p = sub.add_parser("wiki", help=t("offline MS4X Wiki reference"))
    p.add_argument("query", nargs="?", help=t("what to search for in the reference"))
    p.add_argument("--download", action="store_true",
                   help=t("download/update the copy of the site (needs access to ms4x.net)"))
    p.add_argument("--import", dest="import_file", metavar="FILE",
                   help=t("use a reference file (ms4x_wiki.json) copied from another computer"))
    p.add_argument("--list", action="store_true", help=t("list of pages"))
    p.add_argument("--page", help=t("show a whole page"))
    p.add_argument("--param", help=t("what the wiki says about this XDF parameter"))
    p.add_argument("--cautions", action="store_true",
                   help=t("all \"how not to break anything\" warnings"))
    p.add_argument("--english", action="store_true",
                   help=t("also show the English original"))
    p.add_argument("-l", "--limit", type=int, default=15)
    p.set_defaults(func=cmd_wiki)

    # gui
    p = sub.add_parser("gui", help=t("start the window interface"))
    p.set_defaults(func=cmd_gui)

    # patches
    p = sub.add_parser("patches", help=t("check which patches are applied"))
    p.add_argument("-x", "--xdf", help=t("patchlist .xdf (can be set with the MS43_XDF variable)"))
    p.add_argument("-b", "--bin", required=True)
    p.add_argument("--only-applied", action="store_true")
    p.set_defaults(func=cmd_patches)

    # info
    p = sub.add_parser("info", help=t("information about the XDF and the firmware"))
    p.add_argument("-x", "--xdf", help=xdf_help)
    p.add_argument("-b", "--bin")
    p.set_defaults(func=cmd_info)

    # multi
    p = sub.add_parser("multi", help=t("compare several firmware files in one table"))
    add_common(p)
    p.add_argument("bins", nargs="+")
    p.add_argument("-l", "--limit", type=int, default=80)
    p.add_argument("--no-checksums", action="store_true")
    p.set_defaults(func=cmd_multi)

    return parser


def _preselect_lang(argv: Optional[Sequence[str]]) -> None:
    """Apply --lang before the parser is built: help texts are translated."""
    pre = argparse.ArgumentParser(add_help=False)
    pre.add_argument("--lang", choices=LANGS)
    known, _ = pre.parse_known_args(list(argv) if argv is not None else None)
    if known.lang:
        set_lang(known.lang)


def main(argv: Optional[Sequence[str]] = None) -> int:
    _force_utf8()
    _preselect_lang(argv)
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
