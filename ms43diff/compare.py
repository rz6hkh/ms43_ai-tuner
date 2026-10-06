# -*- coding: utf-8 -*-
"""
Движок сравнения: находит различия между двумя прошивками.

Работает в двух режимах, которые дополняют друг друга:

  * по XDF   — сравнение осмысленных параметров (константы и карты)
               с пересчётом в физические величины;
  * по байтам — «сырой» diff всего файла с разбиением на непрерывные
               блоки. Блоки, попавшие в известные параметры, помечаются;
               остальные — это правки кода (патчи), их XDF не описывает.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

from .binfile import BinFile, Reader, format_number
from .xdf import OUT_TEXT, Item, Patch, XdfFile


@dataclass
class CellChange:
    row: int
    col: int
    raw_a: int
    raw_b: int
    val_a: float
    val_b: float

    @property
    def delta(self) -> float:
        return self.val_b - self.val_a

    @property
    def pct(self) -> Optional[float]:
        if self.val_a == 0:
            return None
        return (self.val_b - self.val_a) / abs(self.val_a) * 100.0


@dataclass
class Change:
    """Различие в одном параметре XDF."""

    item: Item
    offset_a: int
    offset_b: int
    cells: List[CellChange] = field(default_factory=list)
    total_cells: int = 1
    vals_a: List[float] = field(default_factory=list)
    vals_b: List[float] = field(default_factory=list)
    text_a: Optional[str] = None
    text_b: Optional[str] = None

    # ------------------------------------------------------------------
    @property
    def title(self) -> str:
        return self.item.title

    @property
    def changed_cells(self) -> int:
        return len(self.cells)

    @property
    def changed_share(self) -> float:
        return self.changed_cells / self.total_cells if self.total_cells else 0.0

    @property
    def deltas(self) -> List[float]:
        return [c.delta for c in self.cells]

    @property
    def delta_min(self) -> float:
        return min(self.deltas) if self.cells else 0.0

    @property
    def delta_max(self) -> float:
        return max(self.deltas) if self.cells else 0.0

    @property
    def delta_avg(self) -> float:
        return sum(self.deltas) / len(self.cells) if self.cells else 0.0

    @property
    def abs_delta_max(self) -> float:
        return max((abs(d) for d in self.deltas), default=0.0)

    @property
    def max_pct(self) -> float:
        best = 0.0
        for cell in self.cells:
            pct = cell.pct
            if pct is not None and abs(pct) > abs(best):
                best = pct
        return best

    @property
    def is_scalar(self) -> bool:
        return self.total_cells == 1

    def summary(self, decimals: int, output_type: int) -> str:
        """Короткая строка «было -> стало» для отчёта."""
        if self.text_a is not None or self.text_b is not None:
            return f"{self.text_a!r} -> {self.text_b!r}"
        if self.is_scalar and self.cells:
            cell = self.cells[0]
            a = format_number(cell.val_a, decimals, output_type)
            b = format_number(cell.val_b, decimals, output_type)
            delta = format_number(cell.delta, decimals, output_type)
            sign = "+" if cell.delta > 0 else ""
            return f"{a} -> {b} ({sign}{delta})"
        lo = format_number(self.delta_min, decimals, output_type)
        hi = format_number(self.delta_max, decimals, output_type)
        return (
            f"изменено {self.changed_cells} из {self.total_cells} ячеек, "
            f"дельта {lo}…{hi}"
        )


@dataclass
class ByteBlock:
    """Непрерывный блок различающихся байтов."""

    start: int
    end: int                      # не включительно
    labels: List[str] = field(default_factory=list)

    @property
    def length(self) -> int:
        return self.end - self.start

    @property
    def explained(self) -> bool:
        return bool(self.labels)


@dataclass
class CompareResult:
    xdf: XdfFile
    bin_a: BinFile
    bin_b: BinFile
    reader_a: Reader
    reader_b: Reader
    changes: List[Change] = field(default_factory=list)
    identical: int = 0
    skipped: List[Tuple[str, str]] = field(default_factory=list)
    byte_blocks: List[ByteBlock] = field(default_factory=list)
    total_bytes_changed: int = 0
    size_mismatch: bool = False

    @property
    def changed_params(self) -> int:
        return len(self.changes)

    @property
    def code_blocks(self) -> List[ByteBlock]:
        """Изменения вне известных параметров — правки кода/патчи."""
        return [b for b in self.byte_blocks if not b.explained]


# ---------------------------------------------------------------------------


def compare_bins(
    xdf: XdfFile,
    bin_a: BinFile,
    bin_b: BinFile,
    include_axes: bool = False,
    include_checksums: bool = True,
    max_gap: int = 8,
    raw_scan: bool = True,
) -> CompareResult:
    """Сравнить две прошивки по описанию XDF.

    max_gap — сколько одинаковых байт склеивать внутри одного блока
    при сыром сравнении (чтобы не дробить одну правку на десятки кусков).
    """
    reader_a = Reader(xdf, bin_a)
    reader_b = Reader(xdf, bin_b)

    result = CompareResult(
        xdf=xdf,
        bin_a=bin_a,
        bin_b=bin_b,
        reader_a=reader_a,
        reader_b=reader_b,
        size_mismatch=len(bin_a) != len(bin_b),
    )

    for item in xdf.readable_items(include_axes=include_axes):
        if not include_checksums and _is_checksum(item):
            continue
        raw_a = reader_a.raw_bytes(item)
        raw_b = reader_b.raw_bytes(item)
        if raw_a is None or raw_b is None:
            result.skipped.append((item.title, "адрес вне границ файла"))
            continue
        if raw_a == raw_b:
            result.identical += 1
            continue

        change = _build_change(item, reader_a, reader_b)
        if change is None:
            result.skipped.append((item.title, "не удалось прочитать значения"))
            continue
        if not change.cells and change.text_a is None:
            # байты разные, но после пересчёта значения совпали (мёртвые биты)
            result.identical += 1
            continue
        result.changes.append(change)

    if raw_scan:
        result.byte_blocks = _byte_blocks(bin_a, bin_b, max_gap=max_gap)
        result.total_bytes_changed = sum(b.length for b in result.byte_blocks)
        _label_blocks(result.byte_blocks, xdf, reader_a)

    result.changes.sort(key=_change_sort_key)
    return result


def _change_sort_key(change: Change):
    # сначала скаляры с большим относительным изменением, потом карты
    return (-abs(change.max_pct), -change.changed_share, change.item.title)


def _is_checksum(item: Item) -> bool:
    title = item.title.lower()
    return title.startswith("cal_") or "cks" in title or "checksum" in title


def _build_change(item: Item, reader_a: Reader, reader_b: Reader) -> Optional[Change]:
    off_a = reader_a.item_offset(item)
    off_b = reader_b.item_offset(item)
    if off_a is None or off_b is None:
        return None

    if item.value_output_type == OUT_TEXT:
        return Change(
            item=item,
            offset_a=off_a,
            offset_b=off_b,
            total_cells=1,
            text_a=reader_a.text(item),
            text_b=reader_b.text(item),
        )

    raw_a = reader_a.raw_values(item)
    raw_b = reader_b.raw_values(item)
    if raw_a is None or raw_b is None:
        return None
    vals_a = reader_a.values(item) or []
    vals_b = reader_b.values(item) or []
    if len(vals_a) != len(vals_b):
        return None

    cols = item.cols
    cells: List[CellChange] = []
    for idx, (ra, rb) in enumerate(zip(raw_a, raw_b)):
        if ra == rb:
            continue
        cells.append(
            CellChange(
                row=idx // cols,
                col=idx % cols,
                raw_a=ra,
                raw_b=rb,
                val_a=vals_a[idx],
                val_b=vals_b[idx],
            )
        )

    return Change(
        item=item,
        offset_a=off_a,
        offset_b=off_b,
        cells=cells,
        total_cells=len(raw_a),
        vals_a=vals_a,
        vals_b=vals_b,
    )


# ---------------------------------------------------------------------------
# Сырое побайтовое сравнение
# ---------------------------------------------------------------------------


def _byte_blocks(bin_a: BinFile, bin_b: BinFile, max_gap: int = 8) -> List[ByteBlock]:
    a, b = bin_a.data, bin_b.data
    n = min(len(a), len(b))
    blocks: List[ByteBlock] = []
    start: Optional[int] = None
    gap = 0
    for i in range(n):
        if a[i] != b[i]:
            if start is None:
                start = i
            gap = 0
        elif start is not None:
            gap += 1
            if gap > max_gap:
                blocks.append(ByteBlock(start, i - gap + 1))
                start = None
                gap = 0
    if start is not None:
        blocks.append(ByteBlock(start, n - gap))
    if len(a) != len(b):
        blocks.append(ByteBlock(n, max(len(a), len(b))))
    return blocks


def _label_blocks(blocks: List[ByteBlock], xdf: XdfFile, reader: Reader) -> None:
    """Пометить, какие блоки покрыты известными параметрами XDF."""
    spans: List[Tuple[int, int, str]] = []
    for item in xdf.readable_items(include_axes=True):
        off = reader.item_offset(item)
        data = item.data
        if off is None or data is None:
            continue
        spans.append((off, off + data.byte_length, item.title))
    spans.sort()

    import bisect

    starts = [s[0] for s in spans]
    for block in blocks:
        idx = bisect.bisect_right(starts, block.end) - 1
        # смотрим немного назад, объекты могут перекрываться
        for j in range(max(0, idx - 40), min(len(spans), idx + 2)):
            s, e, title = spans[j]
            if s < block.end and e > block.start:
                if title not in block.labels:
                    block.labels.append(title)
            if len(block.labels) >= 6:
                break


# ---------------------------------------------------------------------------
# Патчи из community patchlist
# ---------------------------------------------------------------------------


@dataclass
class PatchStatus:
    patch: Patch
    state: str          # 'применён' | 'не применён' | 'частично' | 'изменён' | 'вне файла'
    details: List[str] = field(default_factory=list)


def check_patches(patchlist: XdfFile, binf: BinFile) -> List[PatchStatus]:
    """Определить, какие патчи из patchlist применены к прошивке."""
    out: List[PatchStatus] = []
    for patch in patchlist.patches:
        applied = 0
        base = 0
        other = 0
        missing = 0
        details: List[str] = []
        for entry in patch.entries:
            off = patchlist.file_offset(entry.address)
            length = max(len(entry.patch_data), len(entry.base_data), entry.size)
            chunk = binf.slice(off, length)
            if chunk is None:
                missing += 1
                details.append(f"{entry.name}: 0x{off:X} вне файла")
                continue
            if entry.patch_data and chunk[: len(entry.patch_data)] == entry.patch_data:
                applied += 1
            elif entry.base_data and chunk[: len(entry.base_data)] == entry.base_data:
                base += 1
            else:
                other += 1
                details.append(
                    f"{entry.name}: 0x{off:X} = {chunk[:8].hex().upper()} "
                    f"(ожидалось {entry.patch_data[:8].hex().upper() or '—'} "
                    f"или {entry.base_data[:8].hex().upper() or '—'})"
                )
        total = len(patch.entries)
        if missing == total and total:
            state = "вне файла"
        elif applied == total and total:
            state = "применён"
        elif base == total and total:
            state = "не применён"
        elif applied and (base or other):
            state = "частично"
        elif other:
            state = "изменён"
        else:
            state = "не применён"
        out.append(PatchStatus(patch=patch, state=state, details=details))
    return out


# ---------------------------------------------------------------------------
# Сравнение нескольких прошивок сразу
# ---------------------------------------------------------------------------


def compare_many(
    xdf: XdfFile,
    bins: Sequence[BinFile],
    include_axes: bool = False,
    include_checksums: bool = True,
) -> Tuple[List[Item], Dict[str, List[Optional[str]]], List[Reader]]:
    """Матрица «параметр × прошивка» только по строкам, где есть различия."""
    readers = [Reader(xdf, b) for b in bins]
    items: List[Item] = []
    table: Dict[str, List[Optional[str]]] = {}
    for item in xdf.readable_items(include_axes=include_axes):
        if not include_checksums and _is_checksum(item):
            continue
        raws = [r.raw_bytes(item) for r in readers]
        if any(x is None for x in raws):
            continue
        if len(set(raws)) == 1:
            continue
        items.append(item)
        table[item.title] = [r.summary(item) for r in readers]
    return items, table, readers
