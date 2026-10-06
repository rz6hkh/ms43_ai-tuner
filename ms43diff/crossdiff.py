# -*- coding: utf-8 -*-
"""
Сравнение и перенос настроек между РАЗНЫМИ версиями ПО.

Обычный diff сравнивает два бина одной версии по одному XDF — там достаточно
сличить байты. Здесь задача другая: версии разные (например, 430069 и MS43X001),
у каждой свой XDF, и совпадение адресов не гарантировано.

Поэтому параметры сопоставляются **по имени**, а сравниваются и переносятся
**физические величины**, а не сырые байты. Это принципиально: у 430069 и
MS43X001 больше сотни параметров с разными формулами пересчёта, и побайтовое
копирование молча изменило бы значение.

Цепочка переноса одного параметра:

    сырое из A --формула A--> физическая величина --обратная формула B--> сырое для B

На каждом шаге проверяется:
  * есть ли параметр в целевом XDF;
  * совпадают ли размеры карты;
  * обратима ли формула (линейная — аналитически, нелинейная 8/16 бит —
    перебором ближайшего целого, шире — отказ);
  * влезает ли результат в разрядность и знаковость целевого поля;
  * какова ошибка квантования после округления.

Всё, что не прошло проверку, в целевой файл не пишется и попадает в отчёт
с причиной.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence, Tuple

from .binfile import BinFile, Reader, format_number
from .xdf import OUT_TEXT, Item, XdfFile

# Статусы строк
ST_OK = "совпадает"
ST_DIFF = "отличается"
ST_ONLY_A = "нет в B"
ST_ONLY_B = "нет в A"
ST_SHAPE = "разная форма"
ST_UNREADABLE = "не читается"

# Статусы плана переноса.
# Программа ничего не пишет в прошивку — она только строит план, а правки
# пользователь вносит руками в TunerPro (так надёжнее). «Безопасно» бывает
# двух видов: полное совпадение по байтам (можно копировать 1:1) и совпадение
# только по имени (перенести физическую величину руками). Всё остальное — под
# предупреждением с пояснением, что именно не так.
P_SAFE_BYTES = "безопасно: совпадение по байтам"
P_SAFE_NAME = "безопасно: совпадение по имени"
P_WARN = "предупреждение"


# MS43X001 переименовал часть параметров относительно 430069:
# ip_iga_ron_98_pl_ivvt__n__maf стал ip_iga_ron98_pl__n__maf, а карты VANOS
# tco_1/tco_2 — ron98/e85 (там появился flex-fuel). Поэтому сопоставление идёт
# в три приёма: точное имя -> нормализованное имя -> ранжированные кандидаты,
# среди которых выбирает человек.

# Токены-шум: в одной версии их пишут, в другой нет, на смысл не влияют
_NOISE_TOKEN = re.compile(r"^(?:ivvt|iv)\d*$")


def normalize_title(title: str) -> str:
    """Каноническая форма имени для сопоставления версий.

    'ip_iga_ron_98_pl_ivvt__n__maf' -> 'ip_iga_ron98_pl__n__maf'

    Делается ровно две вещи: цифровой хвост приклеивается к предыдущему токену
    (ron_98 -> ron98) и выбрасываются токены-шум ivvt/iv. Ничего
    «семантического» здесь не угадывается — за это отвечает подбор кандидатов.
    """
    parts = title.split("__")
    out_parts: List[str] = []
    for part in parts:
        tokens = [t for t in part.split("_") if t]
        merged: List[str] = []
        for tok in tokens:
            if tok.isdigit() and merged and not merged[-1].isdigit():
                merged[-1] += tok
            else:
                merged.append(tok)
        merged = [t for t in merged if not _NOISE_TOKEN.match(t)]
        out_parts.append("_".join(merged))
    return "__".join(out_parts)


def _token_set(title: str) -> set:
    return {t for t in normalize_title(title).replace("__", "_").split("_") if t}


def match_candidates(
    item_src: Item, items_dst: Dict[str, Item], limit: int = 5
) -> List[Tuple[str, float]]:
    """Ранжированные кандидаты на соответствие. Форма карты обязана совпадать."""
    src_tokens = _token_set(item_src.title)
    src_shape = (item_src.rows, item_src.cols)
    src_cats = set(item_src.categories)
    scored: List[Tuple[float, str]] = []
    for title, item in items_dst.items():
        if (item.rows, item.cols) != src_shape:
            continue
        tokens = _token_set(title)
        union = src_tokens | tokens
        if not union:
            continue
        score = len(src_tokens & tokens) / len(union)
        if src_cats and set(item.categories) & src_cats:
            score += 0.15
        if item.address == item_src.address:
            score += 0.10
        if score >= 0.4:
            scored.append((score, title))
    scored.sort(key=lambda pair: (-pair[0], pair[1]))
    return [(title, round(score, 3)) for score, title in scored[:limit]]


class TitleMatcher:
    """Сопоставляет имена параметров двух версий ПО."""

    def __init__(self, items_src: Dict[str, Item], items_dst: Dict[str, Item]):
        self.items_src = items_src
        self.items_dst = items_dst
        self._norm_dst: Dict[str, List[str]] = {}
        for title in items_dst:
            self._norm_dst.setdefault(normalize_title(title), []).append(title)
        self._norm_src: Dict[str, List[str]] = {}
        for title in items_src:
            self._norm_src.setdefault(normalize_title(title), []).append(title)

    def match(self, title: str) -> Tuple[Optional[str], str]:
        """Вернуть (имя в целевой версии, как найдено)."""
        if title in self.items_dst:
            return title, "точное совпадение имени"
        norm = normalize_title(title)
        dst = self._norm_dst.get(norm, [])
        src = self._norm_src.get(norm, [])
        # принимаем только если соответствие однозначно с обеих сторон
        if len(dst) == 1 and len(src) == 1:
            return dst[0], f"совпало после нормализации имени ({title} -> {dst[0]})"
        if len(dst) > 1:
            return None, "нормализованному имени соответствует несколько параметров"
        return None, ""


def scaling_notes(item_a: Item, item_b: Item) -> List[str]:
    """Замечания о различиях формата между одноимёнными параметрами."""
    notes: List[str] = []
    eq_a, eq_b = item_a.value_equation, item_b.value_equation
    if eq_a.source != eq_b.source:
        notes.append(f"разные формулы: A «{eq_a.source}», B «{eq_b.source}»")
        # Если коэффициенты отличаются ровно в 10/100/1000 раз — это почти
        # наверняка опечатка в одном из XDF, а не настоящее изменение формата.
        a_slope, b_slope = eq_a.linear[0], eq_b.linear[0]
        if a_slope and b_slope and eq_a.is_linear and eq_b.is_linear:
            ratio = b_slope / a_slope
            for power in (10.0, 100.0, 1000.0):
                if abs(ratio - power) < 1e-6 or abs(ratio - 1 / power) < 1e-9:
                    notes.append(
                        f"коэффициенты различаются ровно в {power:g} раз — "
                        f"похоже на опечатку в одном из XDF, проверьте вручную, "
                        f"прежде чем переносить"
                    )
                    break
    if item_a.data.size_bits != item_b.data.size_bits:
        notes.append(
            f"разная разрядность: {item_a.data.size_bits} и {item_b.data.size_bits} бит"
        )
    if item_a.data.signed != item_b.data.signed:
        notes.append("разная знаковость")
    if item_a.address != item_b.address:
        notes.append(f"разные адреса: 0x{item_a.address:X} и 0x{item_b.address:X}")
    return notes


def _int_range(size_bits: int, signed: bool) -> Tuple[int, int]:
    if signed:
        half = 1 << (size_bits - 1)
        return -half, half - 1
    return 0, (1 << size_bits) - 1


def phys_to_raw(item: Item, phys: float) -> Tuple[Optional[int], str]:
    """Физическая величина -> сырое целое для этого параметра.

    Возвращает (значение, причина отказа). Для линейных формул считается
    аналитически, для нелинейных узких полей — перебором ближайшего.
    """
    data = item.data
    if data is None:
        return None, P_NO_TARGET
    eq = item.value_equation
    lo, hi = _int_range(data.size_bits, data.signed)

    raw = eq.invert(phys)
    if raw is None:
        if data.size_bits > 16:
            return None, P_NOT_INVERTIBLE
        best, best_err = None, None
        for candidate in range(lo, hi + 1):
            err = abs(eq.apply(candidate) - phys)
            if best_err is None or err < best_err:
                best, best_err = candidate, err
        return best, ""

    rounded = int(round(raw))
    if rounded < lo or rounded > hi:
        return None, P_RANGE
    return rounded, ""


# ---------------------------------------------------------------------------
# Сравнение двух версий по именам
# ---------------------------------------------------------------------------


@dataclass
class CrossRow:
    title: str
    status: str
    item_a: Optional[Item] = None
    item_b: Optional[Item] = None
    vals_a: List[float] = field(default_factory=list)
    vals_b: List[float] = field(default_factory=list)
    changed_cells: int = 0
    total_cells: int = 0
    notes: List[str] = field(default_factory=list)

    @property
    def item(self) -> Optional[Item]:
        return self.item_a or self.item_b

    @property
    def delta_min(self) -> float:
        return min(self._deltas, default=0.0)

    @property
    def delta_max(self) -> float:
        return max(self._deltas, default=0.0)

    @property
    def _deltas(self) -> List[float]:
        return [b - a for a, b in zip(self.vals_a, self.vals_b) if a != b]

    def summary(self) -> str:
        item = self.item
        if item is None:
            return ""
        dec, otype = item.value_decimals, item.value_output_type
        if self.status in (ST_ONLY_A, ST_ONLY_B):
            vals = self.vals_a or self.vals_b
            if not vals:
                return ""
            if len(vals) == 1:
                return format_number(vals[0], dec, otype)
            return f"{format_number(min(vals), dec, otype)}…{format_number(max(vals), dec, otype)}"
        if self.total_cells == 1 and self.vals_a and self.vals_b:
            a = format_number(self.vals_a[0], dec, otype)
            b = format_number(self.vals_b[0], dec, otype)
            return f"{a} -> {b}"
        return (
            f"отличается {self.changed_cells} из {self.total_cells} ячеек, "
            f"дельта {format_number(self.delta_min, dec, otype)}…"
            f"{format_number(self.delta_max, dec, otype)}"
        )


@dataclass
class CrossResult:
    xdf_a: XdfFile
    xdf_b: XdfFile
    bin_a: BinFile
    bin_b: BinFile
    reader_a: Reader
    reader_b: Reader
    rows: List[CrossRow] = field(default_factory=list)
    identical: int = 0

    @property
    def different(self) -> List[CrossRow]:
        return [r for r in self.rows if r.status == ST_DIFF]

    @property
    def only_a(self) -> List[CrossRow]:
        return [r for r in self.rows if r.status == ST_ONLY_A]

    @property
    def only_b(self) -> List[CrossRow]:
        return [r for r in self.rows if r.status == ST_ONLY_B]

    @property
    def problems(self) -> List[CrossRow]:
        return [r for r in self.rows if r.status in (ST_SHAPE, ST_UNREADABLE)]


def cross_compare(
    xdf_a: XdfFile,
    bin_a: BinFile,
    xdf_b: XdfFile,
    bin_b: BinFile,
    include_axes: bool = False,
    include_checksums: bool = False,
    only_differences: bool = True,
    tolerance: float = 1e-9,
) -> CrossResult:
    """Сравнить две прошивки разных версий, сопоставляя параметры по имени."""
    reader_a = Reader(xdf_a, bin_a)
    reader_b = Reader(xdf_b, bin_b)
    result = CrossResult(xdf_a, xdf_b, bin_a, bin_b, reader_a, reader_b)

    items_a = {i.title: i for i in xdf_a.readable_items(include_axes=include_axes)}
    items_b = {i.title: i for i in xdf_b.readable_items(include_axes=include_axes)}

    if not include_checksums:
        for pool in (items_a, items_b):
            for title in [t for t in pool if t.startswith("cal_") or "cks" in t]:
                pool.pop(title, None)

    for title in sorted(set(items_a) | set(items_b)):
        item_a = items_a.get(title)
        item_b = items_b.get(title)

        if item_a is None or item_b is None:
            item = item_a or item_b
            reader = reader_a if item_a is not None else reader_b
            vals = reader.values(item) or []
            row = CrossRow(
                title=title,
                status=ST_ONLY_A if item_b is None else ST_ONLY_B,
                item_a=item_a,
                item_b=item_b,
                vals_a=vals if item_a is not None else [],
                vals_b=vals if item_b is not None else [],
                total_cells=len(vals),
            )
            result.rows.append(row)
            continue

        if (item_a.rows, item_a.cols) != (item_b.rows, item_b.cols):
            result.rows.append(
                CrossRow(
                    title=title,
                    status=ST_SHAPE,
                    item_a=item_a,
                    item_b=item_b,
                    notes=[f"{item_a.shape_str} против {item_b.shape_str}"],
                )
            )
            continue

        if item_a.value_output_type == OUT_TEXT or item_b.value_output_type == OUT_TEXT:
            text_a = reader_a.text(item_a) or ""
            text_b = reader_b.text(item_b) or ""
            if text_a == text_b:
                result.identical += 1
                if only_differences:
                    continue
            result.rows.append(
                CrossRow(
                    title=title,
                    status=ST_DIFF if text_a != text_b else ST_OK,
                    item_a=item_a,
                    item_b=item_b,
                    total_cells=1,
                    changed_cells=1 if text_a != text_b else 0,
                    notes=[f"текст: «{text_a}» -> «{text_b}»"],
                )
            )
            continue

        vals_a = reader_a.values(item_a)
        vals_b = reader_b.values(item_b)
        if vals_a is None or vals_b is None:
            result.rows.append(
                CrossRow(title=title, status=ST_UNREADABLE, item_a=item_a, item_b=item_b)
            )
            continue

        changed = sum(1 for a, b in zip(vals_a, vals_b) if abs(a - b) > tolerance)
        notes = scaling_notes(item_a, item_b)

        if not changed:
            result.identical += 1
            if only_differences:
                continue

        result.rows.append(
            CrossRow(
                title=title,
                status=ST_DIFF if changed else ST_OK,
                item_a=item_a,
                item_b=item_b,
                vals_a=vals_a,
                vals_b=vals_b,
                changed_cells=changed,
                total_cells=len(vals_a),
                notes=notes,
            )
        )
    return result


# ---------------------------------------------------------------------------
# План переноса настроек
# ---------------------------------------------------------------------------


@dataclass
class PortEntry:
    title: str                       # имя параметра, который вы изменили в версии A
    status: str
    item_src: Optional[Item] = None
    item_dst: Optional[Item] = None
    dst_title: str = ""
    candidates: List[Tuple[str, float]] = field(default_factory=list)
    phys_tuned: List[float] = field(default_factory=list)          # ваше значение
    phys_target_before: List[float] = field(default_factory=list)  # что в целевой сейчас
    total_cells: int = 0
    match_bits: List[str] = field(default_factory=list)   # чем совпало (для «безопасно»)
    warn_bits: List[str] = field(default_factory=list)    # что не так (для предупреждения)

    @property
    def safe(self) -> bool:
        return self.status in (P_SAFE_BYTES, P_SAFE_NAME)

    def detail(self) -> str:
        """Что показать во всплывающем окне: чем совпало или что не так."""
        if self.safe:
            return "Совпадение: " + "; ".join(self.match_bits)
        return "Проблема: " + "; ".join(self.warn_bits)

    def summary(self) -> str:
        item = self.item_dst or self.item_src
        if item is None:
            return ""
        dec, otype = item.value_decimals, item.value_output_type

        def fmt(values: List[float]) -> str:
            if not values:
                return "—"
            if len(values) == 1:
                return format_number(values[0], dec, otype)
            return (f"{format_number(min(values), dec, otype)}…"
                    f"{format_number(max(values), dec, otype)}")

        tuned = fmt(self.phys_tuned)
        if not self.item_dst:
            return f"ваше значение: {tuned}"
        before = fmt(self.phys_target_before)
        return f"ваше значение: {tuned}   (в целевой сейчас: {before})"


@dataclass
class PortPlan:
    xdf_src: XdfFile
    xdf_dst: XdfFile
    bin_stock: BinFile
    bin_tuned: BinFile
    bin_target: BinFile
    entries: List[PortEntry] = field(default_factory=list)

    @property
    def safe(self) -> List[PortEntry]:
        return [e for e in self.entries if e.safe]

    @property
    def warned(self) -> List[PortEntry]:
        return [e for e in self.entries if not e.safe]

    @property
    def safe_bytes(self) -> List[PortEntry]:
        return [e for e in self.entries if e.status == P_SAFE_BYTES]

    @property
    def safe_name(self) -> List[PortEntry]:
        return [e for e in self.entries if e.status == P_SAFE_NAME]


def build_port_plan(
    xdf_src: XdfFile,
    bin_stock: BinFile,
    bin_tuned: BinFile,
    xdf_dst: XdfFile,
    bin_target: BinFile,
    include_axes: bool = False,
    include_checksums: bool = False,
) -> PortPlan:
    """Построить ПЛАН переноса ваших правок в прошивку другой версии.

    Ничего не пишет: только показывает, что из ваших правок можно перенести
    один в один, а что придётся разбирать руками. Правит пользователь в TunerPro.

    bin_stock  — сток исходной версии (эталон, относительно него ищутся правки)
    bin_tuned  — ваша доработанная прошивка той же версии
    bin_target — прошивка целевой версии, куда переносим

    Статусы:
      * безопасно по байтам — имя совпадает И адрес, размер, формат идентичны:
        значение можно скопировать 1:1;
      * безопасно по имени — имя совпадает, но формат отличается: переносить
        физическую величину руками (в TunerPro виден физический смысл);
      * предупреждение — по имени не нашлось (вырезан/переименован) либо
        размер/тип не совпадают: разбираться вручную.
    """
    r_stock = Reader(xdf_src, bin_stock)
    r_tuned = Reader(xdf_src, bin_tuned)
    r_target = Reader(xdf_dst, bin_target)

    plan = PortPlan(xdf_src, xdf_dst, bin_stock, bin_tuned, bin_target)
    items_dst = {i.title: i for i in xdf_dst.readable_items(include_axes=True)}

    for item_src in xdf_src.readable_items(include_axes=include_axes):
        title = item_src.title
        if not include_checksums and (title.startswith("cal_") or "cks" in title):
            continue

        raw_stock = r_stock.raw_bytes(item_src)
        raw_tuned = r_tuned.raw_bytes(item_src)
        if raw_stock is None or raw_tuned is None or raw_stock == raw_tuned:
            continue  # этот параметр вы не трогали

        entry = PortEntry(title=title, status=P_WARN, item_src=item_src)
        entry.phys_tuned = r_tuned.values(item_src) or []
        entry.total_cells = len(entry.phys_tuned)

        # --- поиск в целевой версии строго по точному имени -----------------
        item_dst = items_dst.get(title)
        if item_dst is None:
            entry.status = P_WARN
            entry.candidates = match_candidates(item_src, items_dst)
            if entry.candidates:
                names = ", ".join(t for t, _ in entry.candidates[:4])
                entry.warn_bits.append(
                    f"в целевой версии нет параметра с таким именем; "
                    f"похожие (проверить вручную): {names}"
                )
            else:
                entry.warn_bits.append(
                    "в целевой версии нет параметра с таким именем и похожих не "
                    "нашлось — скорее всего функцию вырезали"
                )
            plan.entries.append(entry)
            continue

        entry.item_dst = item_dst
        entry.dst_title = item_dst.title
        entry.phys_target_before = r_target.values(item_dst) or []

        # --- сравнение формата --------------------------------------------
        same_shape = (item_src.rows, item_src.cols) == (item_dst.rows, item_dst.cols)
        is_text = (item_src.value_output_type == OUT_TEXT
                   or item_dst.value_output_type == OUT_TEXT)
        d_src, d_dst = item_src.data, item_dst.data
        same_addr = (d_src and d_dst and d_src.address == d_dst.address)
        same_size = (d_src and d_dst and d_src.size_bits == d_dst.size_bits
                     and d_src.signed == d_dst.signed)
        same_eq = (item_src.value_equation.source == item_dst.value_equation.source)

        if is_text:
            entry.status = P_WARN
            entry.warn_bits.append("текстовое поле — переносить вручную")
            plan.entries.append(entry)
            continue
        if not same_shape:
            entry.status = P_WARN
            entry.warn_bits.append(
                f"размер карты отличается: {item_src.shape_str} против "
                f"{item_dst.shape_str}"
            )
            plan.entries.append(entry)
            continue

        # имя совпало и размер совпал — это уже безопасно; уточняем, насколько
        if same_addr and same_size and same_eq:
            entry.status = P_SAFE_BYTES
            entry.match_bits.append("имя, адрес, размер и формула идентичны — "
                                    "можно копировать 1:1")
        else:
            entry.status = P_SAFE_NAME
            entry.match_bits.append("имя и размер карты совпадают")
            if not same_eq:
                entry.match_bits.append(
                    f"формула отличается (A «{item_src.value_equation.source}», "
                    f"B «{item_dst.value_equation.source}») — переносить "
                    f"физическую величину, а не байты")
            if not same_addr and d_src and d_dst:
                entry.match_bits.append(
                    f"разные адреса: 0x{d_src.address:X} → 0x{d_dst.address:X}")
            if not same_size and d_src and d_dst:
                entry.match_bits.append(
                    f"разная разрядность: {d_src.size_bits} → {d_dst.size_bits} бит")

        plan.entries.append(entry)

    # сортировка: сначала безопасные по байтам, потом по имени, потом предупреждения
    order = {P_SAFE_BYTES: 0, P_SAFE_NAME: 1, P_WARN: 2}
    plan.entries.sort(key=lambda e: (order.get(e.status, 3), e.title))
    return plan
