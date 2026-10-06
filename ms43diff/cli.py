# -*- coding: utf-8 -*-
"""
Командная строка ms43diff.

    python -m ms43diff diff  A.bin B.bin -x def.xdf --html отчёт.html
    python -m ms43diff show  -x def.xdf -b A.bin id_n_max_mt__gear
    python -m ms43diff find  -x def.xdf "отсечка"
    python -m ms43diff list  -x def.xdf -b A.bin --category Зажигание
    python -m ms43diff dump  -x def.xdf -b A.bin -o значения.csv
    python -m ms43diff patches -x patchlist.xdf -b A.bin
    python -m ms43diff info  -x def.xdf -b A.bin
"""

from __future__ import annotations

import argparse
import csv
import os
import re
import sys
from typing import Iterable, List, Optional, Sequence

from . import __version__, report, ru
from .binfile import BinFile, Reader, format_number
from .compare import check_patches, compare_bins, compare_many
from .crossdiff import build_port_plan, cross_compare
from .xdf import Item, XdfFile


# ---------------------------------------------------------------------------


def _force_utf8() -> None:
    """В Windows-консоли по умолчанию cp866 — русский текст ломается.

    Мало переключить поток Python: надо ещё перевести саму консоль в UTF-8,
    иначе в classic conhost вместо букв будут кракозябры.
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
    # Чтобы не писать -x с длинным путём каждый раз, можно один раз задать
    # переменную окружения MS43_XDF (см. ms43.bat).
    if not path:
        path = os.environ.get("MS43_XDF", "")
    if not path:
        raise SystemExit(
            "Не указан XDF: добавьте -x путь\\к\\файлу.xdf "
            "или задайте переменную окружения MS43_XDF."
        )
    if not os.path.isfile(path):
        raise SystemExit(f"Не найден XDF-файл: {path}")
    return XdfFile(path)


def _load_bin(path: str) -> BinFile:
    if not os.path.isfile(path):
        raise SystemExit(f"Не найден BIN-файл: {path}")
    return BinFile(path)


def _matches(item: Item, xdf: XdfFile, pattern: Optional[re.Pattern],
             category: Optional[str]) -> bool:
    if category:
        cats = [ru.category_ru(n) for n in xdf.category_names(item)]
        cats += xdf.category_names(item)
        if not any(category.lower() in c.lower() for c in cats):
            return False
    if pattern:
        haystack = " ".join(
            [
                item.title,
                item.description,
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

    # предупреждение о несовпадении версии ПО важно даже в тихом режиме
    for tag, reader in (("A", result.reader_a), ("B", result.reader_b)):
        warning = reader.version_warning()
        if warning and args.quiet:
            print(f"ВНИМАНИЕ ({tag}): {warning}", file=sys.stderr)

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
        _echo(f"HTML-отчёт: {os.path.abspath(args.html)}")
    if args.csv:
        report.write_csv(result, args.csv)
        _echo(f"CSV-отчёт: {os.path.abspath(args.csv)}")
    if args.json:
        report.write_json(result, args.json)
        _echo(f"JSON-отчёт: {os.path.abspath(args.json)}")
    if args.md:
        report.write_markdown(result, args.md)
        _echo(f"Markdown-отчёт: {os.path.abspath(args.md)}")
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
        _echo(f"PDF не создан: {exc}")
        return
    _echo(f"PDF-отчёт: {os.path.abspath(path)}")


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
        _echo(f"Ничего не найдено по запросу: {args.name}")
        return 1
    if len(targets) > args.max:
        _echo(f"Найдено {len(targets)} совпадений, показываю первые {args.max}.")
        _echo("Уточните запрос или увеличьте --max.\n")
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
            _echo(f"... и другие. Всего совпадений больше {args.limit}, "
                  f"уточните запрос или укажите --limit 0.")
            break
        info = ru.explain(item.title, item.description)
        cats = report.item_categories_ru(xdf, item)
        line = f"{item.title}"
        _echo(line)
        _echo(f"    {info['name']}   [{item.shape_str}, {cats}]")
        if info["desc"]:
            _echo(f"    {info['desc']}")
        if reader is not None:
            summary = reader.summary(item)
            units = ru.unit_ru(item.value_units)
            if summary is not None:
                _echo(f"    значение: {summary} {units}".rstrip())
        addr = item.address
        if addr is not None:
            _echo(f"    адрес XDF 0x{addr:X}")
        _echo("")
    if not found:
        _echo("Ничего не найдено.")
        return 1
    _echo(f"Найдено: {found}")
    return 0


# ---------------------------------------------------------------------------
# list
# ---------------------------------------------------------------------------


def cmd_list(args: argparse.Namespace) -> int:
    xdf = _load_xdf(args.xdf)
    reader = Reader(xdf, _load_bin(args.bin)) if args.bin else None
    pattern = _compile(args.filter)

    if args.categories:
        _echo("Категории в этом XDF:")
        counts = {}
        for item in xdf.readable_items(include_axes=True):
            for name in xdf.category_names(item):
                counts[name] = counts.get(name, 0) + 1
        for name in sorted(counts, key=lambda n: (-counts[n], n)):
            _echo(f"  {counts[name]:>5}  {ru.category_ru(name)}   ({name})")
        return 0

    rows = 0
    for item in xdf.readable_items(include_axes=args.include_axes):
        if not _matches(item, xdf, pattern, args.category):
            continue
        rows += 1
        if args.limit and rows > args.limit:
            _echo(f"... показаны первые {args.limit}. Используйте --limit 0 для полного списка.")
            break
        value = ""
        if reader is not None:
            summary = reader.summary(item)
            if summary is not None:
                value = f"{summary} {ru.unit_ru(item.value_units)}".strip()
        name = ru.PARAM_RU.get(item.title, {}).get("ru") or ru.name_ru(item.title)
        _echo(f"{item.title:<44} {item.shape_str:<10} {value:<28} {name}")
    if not rows:
        _echo("Ничего не найдено.")
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
            ["Имя в XDF", "Название", "Категория", "Описание (RU)", "Тип",
             "Значение", "Единицы", "Адрес XDF", "Смещение", "Масштаб"]
        )
        for item in xdf.readable_items(include_axes=args.include_axes):
            if not _matches(item, xdf, pattern, args.category):
                continue
            summary = reader.summary(item)
            if summary is None:
                continue
            count += 1
            info = ru.explain(item.title, item.description)
            units = ru.unit_ru(item.value_units)
            offset = reader.item_offset(item)
            writer.writerow(
                [
                    item.title,
                    info["name"],
                    report.item_categories_ru(xdf, item),
                    info["desc"],
                    item.shape_str,
                    summary,
                    units,
                    f"0x{item.address:X}" if item.address is not None else "",
                    f"0x{offset:X}" if offset is not None else "",
                    item.value_equation.describe_ru(units),
                ]
            )
    _echo(f"Выгружено {count} параметров в {os.path.abspath(args.out)}")
    return 0


# ---------------------------------------------------------------------------
# xdiff — сравнение разных версий ПО
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
        _echo(f"HTML-отчёт: {os.path.abspath(args.html)}")
    return 0


# ---------------------------------------------------------------------------
# port — перенос настроек между версиями
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
        _echo(f"HTML-отчёт: {os.path.abspath(args.html)}")
    if args.csv:
        report.write_port_csv(plan, args.csv)
        _echo(f"CSV-отчёт: {os.path.abspath(args.csv)}")
    if args.pdf:
        _write_pdf(lambda p: _pdf().write_port_pdf(plan, p), args.pdf)
    return 0


# ---------------------------------------------------------------------------
# wiki — офлайн-справочник MS4X
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
    _wrap_echo(wikitrans.translate_block(text))
    if english:
        _echo("     оригинал (English):")
        _wrap_echo(text, indent="       ")
    _echo(f"     {section.url}")
    _echo("")


def cmd_wiki(args: argparse.Namespace) -> int:
    from . import wikicache

    if args.download:
        _echo("Качаю страницы MS4X Wiki (нужен доступ к ms4x.net, возможно через VPN)…")

        def progress(i, n, name):
            _echo(f"  [{i}/{n}] {name}")

        result = wikicache.download(progress=progress)
        _echo("")
        _echo(f"Загружено страниц: {result['pages']}")
        _echo(f"Кэш: {result['path']}")
        for name, err in result["errors"]:
            _echo(f"  не удалось: {name} — {err}")
        return 0

    if not wikicache.available():
        _echo("Локального справочника нет. Выполните на машине с доступом к сайту:")
        _echo("    ms43diff wiki --download")
        return 1

    info = wikicache.meta()
    if args.list:
        _echo(f"Справочник MS4X Wiki, снимок от {info.get('fetched', '?')}")
        _echo(f"Источник: {info.get('source')}   Папка: {info.get('folder')}")
        _echo("")
        for name, title, count in wikicache.page_names():
            _echo(f"  {count:>4} разделов   {title}   ({name})")
        return 0

    if args.cautions:
        from . import wikitrans

        sections = wikicache.cautions(args.page)
        _echo("═" * 78)
        _echo("  ПРЕДУПРЕЖДЕНИЯ ИЗ MS4X WIKI — «как не убить ничего»")
        _echo("═" * 78)
        _echo("")
        for section in sections:
            _echo(f"• {section.page} / {section.heading}")
            for line in section.caution_lines:
                _wrap_echo(wikitrans.translate_line(line), indent="    ")
                if args.english:
                    _wrap_echo(line, indent="      EN: ")
            _echo(f"    {section.url}")
            _echo("")
        _echo(f"Всего: {sum(len(s.caution_lines) for s in sections)} предупреждений")
        return 0

    if args.param:
        sections = wikicache.sections_for(args.param)
        if not sections:
            _echo(f"В справочнике нет упоминаний параметра {args.param}.")
            return 1
        meanings = wikicache.value_meanings(args.param)
        if meanings:
            from . import wikitrans

            _echo(f"Значения параметра {args.param}:")
            for key in sorted(meanings):
                _echo(f"  {key} = {wikitrans.translate_line(meanings[key])}")
            _echo("")
        _echo(f"Что MS4X Wiki пишет про {args.param} (перевод):")
        _echo("")
        for section in sections:
            _print_section(section, param=args.param, english=args.english)
        return 0

    if args.page:
        page = wikicache.page(args.page)
        if page is None:
            _echo(f"Страница «{args.page}» не найдена. Список: ms43diff wiki --list")
            return 1
        _echo("═" * 78)
        _echo(f"  {page.title}")
        _echo(f"  {page.url}   (снимок {page.fetched})")
        _echo("═" * 78)
        _echo("")
        for section in page.sections:
            _print_section(section, english=args.english)
        return 0

    if args.query:
        sections = wikicache.search(args.query, limit=args.limit)
        if not sections:
            _echo("Ничего не найдено.")
            return 1
        _echo(f"Найдено разделов: {len(sections)}")
        _echo("")
        for section in sections:
            _print_section(section, english=args.english)
        return 0

    _echo("Справочник MS4X Wiki (локальная копия).")
    _echo(f"Снимок от {info.get('fetched', '?')}, страниц: {len(wikicache.load())}, "
          f"параметров связано: {len(wikicache.index_parameters())}")
    _echo("")
    _echo("  ms43diff wiki --list              список страниц")
    _echo("  ms43diff wiki \"lambda\"            поиск по тексту")
    _echo("  ms43diff wiki --page Siemens_MS43 показать страницу целиком")
    _echo("  ms43diff wiki --param c_conf_cat  что вики пишет про параметр")
    _echo("  ms43diff wiki --cautions          все предупреждения")
    _echo("  ms43diff wiki --download          обновить копию с сайта")
    return 0


# ---------------------------------------------------------------------------
# patches
# ---------------------------------------------------------------------------


def cmd_patches(args: argparse.Namespace) -> int:
    patchlist = _load_xdf(args.xdf)
    if not patchlist.patches:
        _echo(f"В файле {os.path.basename(args.xdf)} нет записей <XDFPATCH>. "
              f"Для этой команды нужен patchlist-XDF (например "
              f"Siemens_MS43_MS430069_Community_Patchlist_*.xdf).")
        return 1
    binf = _load_bin(args.bin)
    statuses = check_patches(patchlist, binf)
    if args.only_applied:
        statuses = [s for s in statuses if s.state == "применён"]
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
    _echo(f"Название      : {xdf.title}")
    _echo(f"Версия файла  : {xdf.file_version}")
    _echo(f"Автор         : {xdf.author}")
    if xdf.description:
        _echo(f"Описание      : {xdf.description}")
    sign = "-" if xdf.base_subtract else "+"
    _echo(f"BASEOFFSET    : {sign}0x{xdf.base_offset:X}")
    _echo(f"Размер региона: 0x{xdf.region_size:X} ({xdf.region_size // 1024} КБ)")
    _echo(f"Категорий     : {len(xdf.categories)}")

    tables = sum(1 for i in xdf.items if i.kind == "table")
    consts = sum(1 for i in xdf.items if i.kind == "constant")
    axes = sum(1 for i in xdf.items if i.is_axis_definition)
    _echo(f"Объектов      : {len(xdf.items)}  (таблиц {tables}, констант {consts}, "
          f"из них осей {axes})")
    _echo(f"Патчей        : {len(xdf.patches)}")
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
    _echo(f"  Прошивка: {binf.name}")
    _echo("─" * 78)
    _echo(f"Размер        : {len(binf)} байт ({binf.size_kb} КБ)")
    _echo(f"Смещение      : {reader.offset.label}, попадание {reader.offset.fit * 100:.1f}%")
    _echo(f"Читается      : {ok} из {total} объектов")

    # шапка калибровки — по ней видно версию прошивки
    header = binf.slice(reader.file_offset(0x0), 0x60)
    if header:
        text = "".join(chr(b) if 32 <= b < 127 else "." for b in header)
        _echo(f"Шапка калибр. : {text}")
    _echo(f"Версия ПО     : {reader.firmware_id() or 'не определена'}")
    warning = reader.version_warning()
    if warning:
        _echo("")
        _echo(f"ВНИМАНИЕ: {warning}")
    return 0


# ---------------------------------------------------------------------------
# multi
# ---------------------------------------------------------------------------


def cmd_multi(args: argparse.Namespace) -> int:
    xdf = _load_xdf(args.xdf)
    bins = [_load_bin(p) for p in args.bins]
    if len(bins) < 2:
        raise SystemExit("Нужно минимум два .bin файла")
    items, table, readers = compare_many(
        xdf, bins, include_axes=args.include_axes,
        include_checksums=not args.no_checksums
    )
    pattern = _compile(args.filter)
    items = [i for i in items if _matches(i, xdf, pattern, args.category)]

    names = [b.name for b in bins]
    widths = [max(18, min(28, len(n))) for n in names]

    _echo("═" * 78)
    _echo("  СРАВНЕНИЕ НЕСКОЛЬКИХ ПРОШИВОК")
    _echo("═" * 78)
    for idx, name in enumerate(names, 1):
        _echo(f"  {idx}. {name}  ({bins[idx-1].size_kb} КБ)")
    _echo("")
    header = f"{'Параметр':<40}" + "".join(f"{str(i+1):>{w}}" for i, w in enumerate(widths))
    _echo(header)
    _echo("─" * len(header))

    shown = 0
    for item in items:
        if args.limit and shown >= args.limit:
            _echo(f"... показано {shown} из {len(items)}")
            break
        shown += 1
        cells = table[item.title]
        line = f"{item.title:<40}" + "".join(
            f"{(c or '—'):>{w}}" for c, w in zip(cells, widths)
        )
        _echo(line)
        name = ru.PARAM_RU.get(item.title, {}).get("ru") or ru.name_ru(item.title)
        _echo(f"    {name}")
    _echo("")
    _echo(f"Всего различающихся параметров: {len(items)}")
    return 0


# ---------------------------------------------------------------------------


def cmd_vetune(args: argparse.Namespace) -> int:
    from . import vetune

    headers, rows = vetune.read_log(args.log)
    guessed = vetune.guess_columns(headers)
    chosen = {
        "rpm": args.col_rpm or guessed.get("rpm"),
        "load": args.col_load or guessed.get("load"),
        "lambda": args.col_lambda or guessed.get("lambda"),
        "target": args.col_target or guessed.get("target"),
        "trim": args.col_trim or guessed.get("trim"),
        "coolant": args.col_coolant or guessed.get("coolant"),
    }

    if args.columns:
        _echo(f"Столбцов в логе: {len(headers)}, строк: {len(rows)}")
        _echo("")
        for name in headers:
            roles = [role for role, value in chosen.items() if value == name]
            mark = ("  <- " + ", ".join(roles)) if roles else ""
            _echo(f"  {name}{mark}")
        _echo("")
        _echo("Если распознано неверно, укажите вручную: "
              "--col-rpm / --col-load / --col-lambda / --col-target")
        return 0

    missing = [role for role in ("rpm", "load", "lambda") if not chosen[role]]
    if missing:
        _echo("Не удалось найти в логе столбцы: " + ", ".join(missing))
        _echo("Посмотрите список: ms43diff vetune ЛОГ -b ПРОШИВКА -m КАРТА --columns")
        return 1

    xdf = _load_xdf(args.xdf)
    binf = _load_bin(args.bin)
    reader = Reader(xdf, binf)
    item = xdf.by_title(args.map_name)
    if item is None:
        pattern = _compile(args.map_name)
        candidates = [i for i in xdf.readable_items(include_axes=False)
                      if pattern and pattern.search(i.title) and i.cell_count > 1]
        if len(candidates) == 1:
            item = candidates[0]
        elif candidates:
            _echo("Уточните карту, подходит несколько:")
            for candidate in candidates[:20]:
                _echo(f"  {candidate.title}   ({candidate.shape_str})")
            return 1
    if item is None:
        _echo(f"Карта «{args.map_name}» не найдена в этом XDF.")
        return 1

    columns = vetune.LogColumns(
        rpm=chosen["rpm"], load=chosen["load"], lam=chosen["lambda"],
        target=chosen["target"], trim=chosen["trim"], coolant=chosen["coolant"],
    )
    result = vetune.analyse(
        reader, item, rows, columns,
        mode=args.mode, fuel=args.fuel, target_lambda=args.target,
        min_samples=args.min_samples, max_spread=args.max_spread,
        max_step=args.max_step, delay_samples=args.delay,
        min_coolant=args.min_coolant, smooth=not args.no_smooth,
        steady_rpm=args.steady_rpm, steady_load=args.steady_load,
    )
    _echo(report.vetune_console_report(reader, result))

    if args.html:
        report.write_vetune_html(reader, result, args.html,
                                 log_name=os.path.basename(args.log))
        _echo(f"HTML-отчёт: {os.path.abspath(args.html)}")

    if args.write:
        if os.path.abspath(args.write) == os.path.abspath(args.bin):
            raise SystemExit("Отказ: нельзя писать поверх исходной прошивки.")
        if os.path.exists(args.write) and not args.force:
            raise SystemExit(f"Файл {args.write} уже есть. Добавьте --force.")
        info = vetune.write_tuned_bin(reader, item, result, args.write)
        _echo("")
        _echo(f"Записано ячеек: {info['cells']}"
              + (f", не влезло: {info['clipped']}" if info["clipped"] else ""))
        _echo(f"Новый файл: {os.path.abspath(info['path'])}")
        _echo("")
        _echo("КОНТРОЛЬНЫЕ СУММЫ НЕ ПЕРЕСЧИТАНЫ — сделайте это в TunerPro.")
    return 0


def cmd_gui(args: argparse.Namespace) -> int:
    from .gui import run

    return run()


def cmd_mcp(args: argparse.Namespace) -> int:
    from .mcpserver import serve

    return serve(args.xdf, args.bin)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="ms43diff",
        description="Сравнение прошивок Siemens MS43 (BMW M52TU/M54) "
                    "по XDF-описанию с расшифровкой на русском.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("--version", action="version", version=f"ms43diff {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    def add_common(p):
        p.add_argument("-x", "--xdf",
                       help="файл описания .xdf (можно задать переменной MS43_XDF)")
        p.add_argument("--include-axes", action="store_true",
                       help="учитывать таблицы опорных точек осей (ldp_*)")
        p.add_argument("--filter", help="регулярное выражение по имени/описанию")
        p.add_argument("--category", help="фильтр по категории (рус. или англ.)")

    # diff
    p = sub.add_parser("diff", help="сравнить две прошивки")
    add_common(p)
    p.add_argument("bin_a", help="первая прошивка (например, сток)")
    p.add_argument("bin_b", help="вторая прошивка (например, тюнинг)")
    p.add_argument("--html", help="сохранить HTML-отчёт")
    p.add_argument("--csv", help="сохранить CSV-отчёт")
    p.add_argument("--json", help="сохранить JSON-отчёт")
    p.add_argument("--md", help="сохранить Markdown-отчёт")
    p.add_argument("--pdf", help="сохранить PDF-отчёт (с цветными картами)")
    p.add_argument("--no-maps", action="store_true",
                   help="не рисовать карты в PDF (короче и легче)")
    p.add_argument("-l", "--limit", type=int, default=60,
                   help="сколько параметров печатать в консоль (0 — все)")
    p.add_argument("-v", "--verbose", action="store_true",
                   help="показывать изменённые ячейки карт")
    p.add_argument("--english", action="store_true", help="показывать оригинал описания")
    p.add_argument("--no-checksums", action="store_true",
                   help="не показывать изменения контрольных сумм")
    p.add_argument("--no-raw", action="store_true", help="не делать побайтовый скан")
    p.add_argument("--gap", type=int, default=8,
                   help="склеивать блоки байтов, разделённые не более чем N байтами")
    p.add_argument("-q", "--quiet", action="store_true", help="только файлы отчётов")
    p.set_defaults(func=cmd_diff)

    # show
    p = sub.add_parser("show", help="показать одну карту/константу с осями")
    p.add_argument("-x", "--xdf", help="файл описания .xdf (можно задать переменной MS43_XDF)")
    p.add_argument("-b", "--bin", required=True)
    p.add_argument("name", help="имя параметра или часть имени (регулярка)")
    p.add_argument("-c", "--compare", help="вторая прошивка — отметить отличия")
    p.add_argument("--max", type=int, default=5, help="максимум карт за раз")
    p.add_argument("--pdf", help="сохранить карты в PDF с раскраской")
    p.set_defaults(func=cmd_show)

    # find
    p = sub.add_parser("find", help="искать параметры по русскому или английскому тексту")
    add_common(p)
    p.add_argument("query", help="что ищем")
    p.add_argument("-b", "--bin", help="показать заодно значения из прошивки")
    p.add_argument("-l", "--limit", type=int, default=40)
    p.set_defaults(func=cmd_find)

    # list
    p = sub.add_parser("list", help="перечислить параметры")
    add_common(p)
    p.add_argument("-b", "--bin", help="показать значения из прошивки")
    p.add_argument("-l", "--limit", type=int, default=100)
    p.add_argument("--categories", action="store_true", help="вывести список категорий")
    p.set_defaults(func=cmd_list)

    # dump
    p = sub.add_parser("dump", help="выгрузить все значения прошивки в CSV")
    add_common(p)
    p.add_argument("-b", "--bin", required=True)
    p.add_argument("-o", "--out", default="ms43_dump.csv")
    p.set_defaults(func=cmd_dump)

    # xdiff
    p = sub.add_parser("xdiff", help="сравнить прошивки РАЗНЫХ версий ПО (два XDF)")
    p.add_argument("bin_a")
    p.add_argument("bin_b")
    p.add_argument("-A", "--xdf-a", required=True, help="XDF для первой прошивки")
    p.add_argument("-B", "--xdf-b", required=True, help="XDF для второй прошивки")
    p.add_argument("--include-axes", action="store_true")
    p.add_argument("--checksums", action="store_true", help="учитывать контрольные суммы")
    p.add_argument("--filter")
    p.add_argument("--category")
    p.add_argument("--html")
    p.add_argument("-l", "--limit", type=int, default=60)
    p.add_argument("-q", "--quiet", action="store_true")
    p.set_defaults(func=cmd_xdiff)

    # port
    p = sub.add_parser("port",
                       help="план переноса правок в прошивку другой версии ПО (без записи)")
    p.add_argument("stock", help="сток исходной версии (эталон)")
    p.add_argument("tuned", help="ваша доработанная прошивка той же версии")
    p.add_argument("target", help="прошивка целевой версии, куда переносим")
    p.add_argument("-A", "--xdf-src", required=True, help="XDF исходной версии")
    p.add_argument("-B", "--xdf-dst", required=True, help="XDF целевой версии")
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
    p = sub.add_parser("wiki", help="офлайн-справочник MS4X Wiki")
    p.add_argument("query", nargs="?", help="что искать в справочнике")
    p.add_argument("--download", action="store_true",
                   help="скачать/обновить копию сайта (нужен доступ к ms4x.net)")
    p.add_argument("--list", action="store_true", help="список страниц")
    p.add_argument("--page", help="показать страницу целиком")
    p.add_argument("--param", help="что вики пишет про этот параметр XDF")
    p.add_argument("--cautions", action="store_true",
                   help="все предупреждения «как не убить ничего»")
    p.add_argument("--english", action="store_true",
                   help="показывать ещё и оригинал на английском")
    p.add_argument("-l", "--limit", type=int, default=15)
    p.set_defaults(func=cmd_wiki)

    # vetune
    p = sub.add_parser("vetune", help="откатать карту по логу ШЛЗ")
    p.add_argument("log", help="CSV-лог с широкополосным зондом")
    p.add_argument("-x", "--xdf", help="файл описания .xdf")
    p.add_argument("-b", "--bin", required=True, help="прошивка")
    p.add_argument("-m", "--map", required=True, dest="map_name",
                   help="имя карты наполнения (например ip_map_ve_1__map__n)")
    p.add_argument("--mode", choices=("lambda", "trim", "both"), default="lambda",
                   help="откуда брать поправку")
    p.add_argument("--fuel", choices=tuple(("gasoline", "e85", "e10", "methanol")),
                   default="gasoline")
    p.add_argument("--target", type=float, default=1.0,
                   help="целевая лямбда, если её нет в логе")
    p.add_argument("--min-samples", type=int, default=8,
                   help="сколько точек нужно в ячейке, чтобы её трогать")
    p.add_argument("--max-step", type=float, default=0.25,
                   help="максимальная поправка за проход (0.25 = ±25%%)")
    p.add_argument("--max-spread", type=float, default=0.06,
                   help="предельный разброс внутри ячейки")
    p.add_argument("--delay", type=int, default=0,
                   help="сдвиг показаний зонда, отсчётов")
    p.add_argument("--no-smooth", action="store_true", help="не сглаживать")
    p.add_argument("--steady-rpm", type=float, default=250.0,
                   help="макс. скачок оборотов между отсчётами (больше — точка "
                        "считается переходной и отбрасывается)")
    p.add_argument("--steady-load", type=float, default=8.0,
                   help="макс. скачок нагрузки между отсчётами")
    p.add_argument("--min-coolant", type=float, default=70.0,
                   help="не брать точки холоднее этой температуры ОЖ")
    p.add_argument("--col-rpm"), p.add_argument("--col-load")
    p.add_argument("--col-lambda"), p.add_argument("--col-target")
    p.add_argument("--col-trim"), p.add_argument("--col-coolant")
    p.add_argument("--html", help="сохранить наглядный отчёт")
    p.add_argument("--write", help="записать новую карту в НОВЫЙ .bin")
    p.add_argument("--force", action="store_true")
    p.add_argument("--columns", action="store_true",
                   help="только показать, какие столбцы нашлись в логе")
    p.set_defaults(func=cmd_vetune)

    # gui
    p = sub.add_parser("gui", help="запустить оконный интерфейс")
    p.set_defaults(func=cmd_gui)

    # mcp
    p = sub.add_parser("mcp", help="запустить MCP-сервер для нейросети (stdio)")
    p.add_argument("-x", "--xdf", help="файл описания .xdf")
    p.add_argument("-b", "--bin", help="файл прошивки .bin")
    p.set_defaults(func=cmd_mcp)

    # patches
    p = sub.add_parser("patches", help="проверить, какие патчи применены")
    p.add_argument("-x", "--xdf", help="patchlist .xdf (можно задать переменной MS43_XDF)")
    p.add_argument("-b", "--bin", required=True)
    p.add_argument("--only-applied", action="store_true")
    p.set_defaults(func=cmd_patches)

    # info
    p = sub.add_parser("info", help="сведения о XDF и прошивке")
    p.add_argument("-x", "--xdf", help="файл описания .xdf (можно задать переменной MS43_XDF)")
    p.add_argument("-b", "--bin")
    p.set_defaults(func=cmd_info)

    # multi
    p = sub.add_parser("multi", help="сравнить сразу несколько прошивок таблицей")
    add_common(p)
    p.add_argument("bins", nargs="+")
    p.add_argument("-l", "--limit", type=int, default=80)
    p.add_argument("--no-checksums", action="store_true")
    p.set_defaults(func=cmd_multi)

    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    _force_utf8()
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
