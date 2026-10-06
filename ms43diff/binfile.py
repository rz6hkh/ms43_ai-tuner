"""
Чтение значений из .bin по описанию XDF.

Тонкости, проверенные на реальном стоковом MS430069 (E39 M54B30):

  * XDF на 512K объявляет BASEOFFSET 0x70000 — калибровочная зона это
    последние 64 КБ образа. XDF на 64K объявляет BASEOFFSET 0.
    Класс BinFile умеет подобрать смещение сам (auto), чтобы один и тот же
    XDF работал и с 64K-дампом, и с полным 512K.
  * mmedtypeflags бит 0x01 = знаковое, бит 0x02 = little-endian.
    Пример: c_gr_rax_sp @ 0x706A2 = EE 02 -> 0x02EE = 750 -> x0.003906 = 2.93
    (главная пара E39 530i) — сходится.
  * outputtype 4 = ASCII-строка (например «430069.DAT» в шапке калибровки).
"""

from __future__ import annotations

import os
import re
import struct
from dataclasses import dataclass
from typing import Dict, List, Optional, Sequence, Tuple

from .xdf import OUT_HEX, OUT_INT, OUT_TEXT, Axis, Item, XdfFile


class BinFile:
    """Образ прошивки в памяти."""

    def __init__(self, path: str, data: Optional[bytes] = None):
        self.path = os.path.abspath(path)
        self.name = os.path.basename(path)
        if data is None:
            with open(path, "rb") as fh:
                data = fh.read()
        self.data = data

    def __len__(self) -> int:
        return len(self.data)

    @property
    def size_kb(self) -> int:
        return len(self.data) // 1024

    def slice(self, offset: int, length: int) -> Optional[bytes]:
        if offset < 0 or offset + length > len(self.data):
            return None
        return self.data[offset : offset + length]

    def __repr__(self) -> str:  # pragma: no cover
        return f"BinFile({self.name!r}, {self.size_kb} КБ)"


# ---------------------------------------------------------------------------


@dataclass
class OffsetChoice:
    offset: int
    subtract: bool
    fit: float          # доля объектов XDF, попавших внутрь файла
    declared: bool      # это то, что написано в самом XDF?

    @property
    def label(self) -> str:
        sign = "-" if self.subtract else "+"
        tag = "как в XDF" if self.declared else "подобрано автоматически"
        return f"{sign}0x{self.offset:X} ({tag})"


def resolve_offset(xdf: XdfFile, binf: BinFile) -> OffsetChoice:
    """Подобрать смещение так, чтобы максимум объектов XDF попал в файл.

    Кандидаты: объявленный в XDF, ноль, «хвост» файла в 64 КБ и обычные
    для MS43 значения. Побеждает тот, при котором в границы файла попадает
    наибольшая доля объектов.
    """
    addresses = []
    for item in xdf.readable_items(include_axes=True):
        data = item.data
        if data and data.address is not None:
            addresses.append((data.address, data.byte_length))
    if not addresses:
        return OffsetChoice(xdf.base_offset, xdf.base_subtract, 1.0, True)

    candidates: List[Tuple[int, bool]] = [(xdf.base_offset, xdf.base_subtract)]
    for extra in (0, 0x70000, 0x8000, len(binf) - 0x10000):
        if extra >= 0:
            candidates.append((extra, False))
    if xdf.base_offset:
        candidates.append((xdf.base_offset, True))

    best: Optional[OffsetChoice] = None
    seen = set()
    for offset, subtract in candidates:
        key = (offset, subtract)
        if key in seen:
            continue
        seen.add(key)
        hits = 0
        for addr, length in addresses:
            pos = addr - offset if subtract else addr + offset
            if 0 <= pos and pos + length <= len(binf):
                hits += 1
        fit = hits / len(addresses)
        declared = offset == xdf.base_offset and subtract == xdf.base_subtract
        choice = OffsetChoice(offset, subtract, fit, declared)
        # при равном результате предпочитаем объявленный в XDF
        if best is None or fit > best.fit + 1e-9 or (abs(fit - best.fit) < 1e-9 and declared):
            best = choice
    assert best is not None
    return best


# ---------------------------------------------------------------------------


class Reader:
    """Пара «описание + прошивка»: достаёт значения объектов XDF из .bin."""

    def __init__(self, xdf: XdfFile, binf: BinFile, offset: Optional[OffsetChoice] = None):
        self.xdf = xdf
        self.bin = binf
        self.offset = offset or resolve_offset(xdf, binf)
        self._axis_cache: Dict[int, Optional[List[float]]] = {}

    # ------------------------------------------------------------------
    def file_offset(self, address: int) -> int:
        if self.offset.subtract:
            return address - self.offset.offset
        return address + self.offset.offset

    def item_offset(self, item: Item) -> Optional[int]:
        data = item.data
        if data is None or data.address is None:
            return None
        return self.file_offset(data.address)

    def in_range(self, item: Item) -> bool:
        pos = self.item_offset(item)
        if pos is None:
            return False
        data = item.data
        return pos >= 0 and pos + data.byte_length <= len(self.bin)

    # ------------------------------------------------------------------
    def raw_bytes(self, item: Item) -> Optional[bytes]:
        """Непрерывный кусок файла, покрывающий объект (для быстрого сравнения)."""
        pos = self.item_offset(item)
        if pos is None:
            return None
        return self.bin.slice(pos, item.data.byte_length)

    def raw_values(self, item: Item) -> Optional[List[int]]:
        """Список сырых целых значений (по строкам)."""
        data = item.data
        pos = self.item_offset(item)
        if data is None or pos is None:
            return None
        out: List[int] = []
        nbytes = data.elem_bytes
        order = "little" if data.lsb_first else "big"
        for r in range(max(1, data.rowcount)):
            for c in range(max(1, data.colcount)):
                off = pos + r * data.row_stride + c * data.col_stride
                chunk = self.bin.slice(off, nbytes)
                if chunk is None:
                    return None
                if data.is_float and nbytes in (4, 8):
                    fmt = ("<" if data.lsb_first else ">") + ("f" if nbytes == 4 else "d")
                    out.append(struct.unpack(fmt, chunk)[0])
                else:
                    out.append(int.from_bytes(chunk, order, signed=data.signed))
        return out

    def values(self, item: Item) -> Optional[List[float]]:
        """Физические значения после применения формулы пересчёта."""
        raws = self.raw_values(item)
        if raws is None:
            return None
        eq = item.value_equation
        if eq.is_identity:
            return [float(v) for v in raws]
        return [eq.apply(v) for v in raws]

    def matrix(self, item: Item) -> Optional[List[List[float]]]:
        vals = self.values(item)
        if vals is None:
            return None
        cols = item.cols
        return [vals[r * cols : (r + 1) * cols] for r in range(item.rows)]

    def raw_matrix(self, item: Item) -> Optional[List[List[int]]]:
        vals = self.raw_values(item)
        if vals is None:
            return None
        cols = item.cols
        return [vals[r * cols : (r + 1) * cols] for r in range(item.rows)]

    def text(self, item: Item) -> Optional[str]:
        raw = self.raw_bytes(item)
        if raw is None:
            return None
        return "".join(chr(b) if 32 <= b < 127 else "." for b in raw)

    # ------------------------------------------------------------------
    def axis_values(self, item: Item, which: str) -> Optional[List[float]]:
        """Значения оси X или Y.

        Порядок поиска:
          1. ось ссылается на другую таблицу (embedinfo linkobjid) — читаем её;
          2. у оси есть собственный адрес — читаем напрямую;
          3. остаются статические LABEL-ы из самого XDF.
        """
        axis: Optional[Axis] = item.axis_x if which == "x" else item.axis_y
        if axis is None:
            return None
        want = axis.index_count or (item.cols if which == "x" else item.rows)

        if axis.link_id:
            linked = self._linked_axis(axis.link_id)
            if linked:
                return linked[:want] if want else linked

        if axis.embedded.has_data:
            vals = self.values(Item(kind="table", axis_z=axis))
            if vals:
                return vals[:want] if want else vals

        if axis.labels:
            return list(axis.labels[:want]) if want else list(axis.labels)
        return None

    def _linked_axis(self, uid: int) -> Optional[List[float]]:
        if uid in self._axis_cache:
            return self._axis_cache[uid]
        target = self.xdf.by_uid(uid)
        vals = self.values(target) if target is not None else None
        self._axis_cache[uid] = vals
        return vals

    # ------------------------------------------------------------------
    # ------------------------------------------------------------------
    def firmware_id(self) -> Optional[str]:
        """Версия ПО из шапки калибровки, например «430069» или «43X001».

        В начале калибровочной зоны MS43 лежит строка вида «...430069.DAT».
        """
        header = self.bin.slice(self.file_offset(0), 0x80)
        if not header:
            return None
        text = "".join(chr(b) if 32 <= b < 127 else " " for b in header)
        match = re.search(r"([0-9A-Z]{6})\.DAT", text)
        return match.group(1) if match else None

    def version_warning(self) -> Optional[str]:
        """Предупредить, если прошивка не от того ПО, что описывает XDF.

        Сравнивать 430056 по описанию для 430069 бессмысленно: адреса поедут
        и в отчёте будут тысячи мнимых «изменений».
        """
        fw = self.firmware_id()
        if not fw:
            return None
        title = (self.xdf.title or "").upper().replace("MS", "")
        if not title:
            return None
        if fw.upper() in (self.xdf.title or "").upper() or title in fw.upper():
            return None
        return (
            f"версия ПО в прошивке — {fw}, а XDF описывает {self.xdf.title}. "
            f"Адреса почти наверняка не совпадают, результат будет мусорным. "
            f"Возьмите XDF для {fw}."
        )

    def format_value(self, item: Item, value: float) -> str:
        return format_number(value, item.value_decimals, item.value_output_type)

    def summary(self, item: Item) -> Optional[str]:
        """Короткая сводка значения: скаляр — число, карта — min..max/среднее."""
        if item.value_output_type == OUT_TEXT:
            return self.text(item)
        vals = self.values(item)
        if not vals:
            return None
        dec = item.value_decimals
        otype = item.value_output_type
        if len(vals) == 1:
            return format_number(vals[0], dec, otype)
        lo, hi = min(vals), max(vals)
        avg = sum(vals) / len(vals)
        if lo == hi:
            return f"все {format_number(lo, dec, otype)}"
        return (
            f"{format_number(lo, dec, otype)}…{format_number(hi, dec, otype)}"
            f" (ср. {format_number(avg, dec, otype)})"
        )


def format_number(value: float, decimals: int = 2, output_type: int = 1) -> str:
    if output_type == OUT_HEX:
        try:
            return f"0x{int(round(value)):X}"
        except (ValueError, OverflowError):
            return str(value)
    if output_type == OUT_INT:
        try:
            return str(int(round(value)))
        except (ValueError, OverflowError):
            return str(value)
    decimals = max(0, min(int(decimals or 0), 8))
    text = f"{value:.{decimals}f}"
    if text in ("-0", "-0.0", "-0.00", "-0.000"):
        text = text[1:]
    return text


def load_bins(paths: Sequence[str]) -> List[BinFile]:
    return [BinFile(p) for p in paths]
