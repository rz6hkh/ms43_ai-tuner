"""
Парсер XDF-описаний TunerPro (версии формата 1.60-1.80).

Поддерживается всё, что реально встречается в определениях MS4x Dev Team
для Siemens MS43:

  * XDFHEADER   — BASEOFFSET, DEFAULTS, REGION, список CATEGORY
  * XDFCONSTANT — одиночная величина (скаляр)
  * XDFTABLE    — 1D/2D карта с осями X/Y и данными Z
  * XDFAXIS     — ось: либо статические LABEL-ы, либо ссылка на другую
                  таблицу через <embedinfo linkobjid="...">
  * XDFPATCH    — патч (набор XDFPATCHENTRY с базовыми и пропатченными байтами)
  * XDFFLAG / XDFCHECKSUM — читаются «как есть», если попадутся

Разбор ленивый только в части вычислений; сам XML читается целиком —
файл на 3.5 МБ парсится примерно за секунду.
"""

from __future__ import annotations

import os
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from typing import Dict, Iterator, List, Optional, Sequence

from .mathexpr import Equation

# ---------------------------------------------------------------------------
# Битовые флаги EMBEDDEDDATA (mmedtypeflags)
# ---------------------------------------------------------------------------
FLAG_SIGNED = 0x01      # значение со знаком
FLAG_LSB_FIRST = 0x02   # little-endian (у C167 в MS43 — всегда так)
FLAG_FLOAT = 0x10000    # IEEE float (в MS43 не встречается, но поддержим)

# Значения <outputtype>
OUT_FLOAT = 1
OUT_HEX = 2
OUT_INT = 3
OUT_TEXT = 4


def parse_int(text, default=0) -> int:
    """'0x70000' / '458752' / '-32' / None -> int."""
    if text is None:
        return default
    text = str(text).strip()
    if not text:
        return default
    try:
        if text.lower().startswith(("0x", "-0x", "+0x")):
            return int(text, 16)
        return int(text, 10)
    except ValueError:
        try:
            return int(float(text))
        except ValueError:
            return default


def _text(elem: Optional[ET.Element], tag: str, default: str = "") -> str:
    if elem is None:
        return default
    child = elem.find(tag)
    if child is None or child.text is None:
        return default
    return child.text.strip()


def _num(elem: Optional[ET.Element], tag: str, default=None):
    raw = _text(elem, tag, "")
    if raw == "":
        return default
    try:
        return float(raw)
    except ValueError:
        return default


# ---------------------------------------------------------------------------


@dataclass
class Embedded:
    """Описание того, где и как значение лежит в бинарнике."""

    address: Optional[int] = None
    size_bits: int = 8
    rowcount: int = 1
    colcount: int = 1
    type_flags: int = 0
    major_stride_bits: int = 0
    minor_stride_bits: int = 0

    @property
    def signed(self) -> bool:
        return bool(self.type_flags & FLAG_SIGNED)

    @property
    def lsb_first(self) -> bool:
        return bool(self.type_flags & FLAG_LSB_FIRST)

    @property
    def is_float(self) -> bool:
        return bool(self.type_flags & FLAG_FLOAT)

    @property
    def elem_bytes(self) -> int:
        return max(1, self.size_bits // 8)

    @property
    def count(self) -> int:
        return max(1, self.rowcount) * max(1, self.colcount)

    @property
    def row_stride(self) -> int:
        """Шаг между строками в байтах."""
        if self.major_stride_bits > 0:
            return self.major_stride_bits // 8
        return self.elem_bytes * max(1, self.colcount)

    @property
    def col_stride(self) -> int:
        if self.minor_stride_bits > 0:
            return self.minor_stride_bits // 8
        return self.elem_bytes

    @property
    def byte_length(self) -> int:
        rows = max(1, self.rowcount)
        cols = max(1, self.colcount)
        return (rows - 1) * self.row_stride + (cols - 1) * self.col_stride + self.elem_bytes

    @property
    def has_data(self) -> bool:
        """У статических осей (LABEL-ы) адреса нет, а major stride = -32."""
        return self.address is not None and self.major_stride_bits >= 0

    @classmethod
    def from_elem(cls, elem: Optional[ET.Element], defaults: "Defaults") -> "Embedded":
        if elem is None:
            return cls(size_bits=defaults.size_bits, type_flags=defaults.type_flags)
        addr = elem.get("mmedaddress")
        return cls(
            address=parse_int(addr, None) if addr is not None else None,
            size_bits=parse_int(elem.get("mmedelementsizebits"), defaults.size_bits),
            rowcount=parse_int(elem.get("mmedrowcount"), 1) or 1,
            colcount=parse_int(elem.get("mmedcolcount"), 1) or 1,
            type_flags=parse_int(elem.get("mmedtypeflags"), defaults.type_flags),
            major_stride_bits=parse_int(elem.get("mmedmajorstridebits"), 0),
            minor_stride_bits=parse_int(elem.get("mmedminorstridebits"), 0),
        )


@dataclass
class Defaults:
    size_bits: int = 8
    sig_digits: int = 2
    output_type: int = OUT_FLOAT
    signed: bool = False
    lsb_first: bool = False
    is_float: bool = False

    @property
    def type_flags(self) -> int:
        flags = 0
        if self.signed:
            flags |= FLAG_SIGNED
        if self.lsb_first:
            flags |= FLAG_LSB_FIRST
        if self.is_float:
            flags |= FLAG_FLOAT
        return flags


@dataclass
class Axis:
    """Ось карты (x, y) или сами данные (z)."""

    axis_id: str = "z"
    embedded: Embedded = field(default_factory=Embedded)
    units: str = ""
    index_count: int = 0
    decimals: int = 2
    output_type: int = OUT_FLOAT
    equation: Equation = field(default_factory=lambda: Equation("X"))
    labels: List[float] = field(default_factory=list)
    link_id: Optional[int] = None       # <embedinfo linkobjid="0x...">
    link_type: int = 0
    min_value: Optional[float] = None
    max_value: Optional[float] = None


@dataclass
class Item:
    """Общий предок константы и таблицы — всё, что можно достать из .bin."""

    kind: str                       # 'constant' | 'table'
    unique_id: int = 0
    title: str = ""
    description: str = ""
    categories: List[int] = field(default_factory=list)
    vis_level: int = 1
    flags: int = 0

    # только для констант
    embedded: Optional[Embedded] = None
    units: str = ""
    decimals: int = 2
    output_type: int = OUT_FLOAT
    equation: Equation = field(default_factory=lambda: Equation("X"))
    range_low: Optional[float] = None
    range_high: Optional[float] = None

    # только для таблиц
    axis_x: Optional[Axis] = None
    axis_y: Optional[Axis] = None
    axis_z: Optional[Axis] = None

    # ------------------------------------------------------------------
    @property
    def data(self) -> Optional[Embedded]:
        """EMBEDDEDDATA, в котором лежат собственно значения."""
        if self.kind == "constant":
            return self.embedded
        return self.axis_z.embedded if self.axis_z else None

    @property
    def address(self) -> Optional[int]:
        d = self.data
        return d.address if d else None

    @property
    def rows(self) -> int:
        d = self.data
        return max(1, d.rowcount) if d else 1

    @property
    def cols(self) -> int:
        d = self.data
        return max(1, d.colcount) if d else 1

    @property
    def cell_count(self) -> int:
        return self.rows * self.cols

    @property
    def shape_str(self) -> str:
        if self.kind == "constant":
            return "скаляр"
        r, c = self.rows, self.cols
        if r == 1 and c == 1:
            return "скаляр"
        if r == 1 or c == 1:
            return f"1D×{max(r, c)}"
        return f"2D {r}×{c}"

    @property
    def value_units(self) -> str:
        if self.kind == "constant":
            return self.units
        return self.axis_z.units if self.axis_z else ""

    @property
    def value_equation(self) -> Equation:
        if self.kind == "constant":
            return self.equation
        return self.axis_z.equation if self.axis_z else Equation("X")

    @property
    def value_decimals(self) -> int:
        if self.kind == "constant":
            return self.decimals
        return self.axis_z.decimals if self.axis_z else 2

    @property
    def value_output_type(self) -> int:
        if self.kind == "constant":
            return self.output_type
        return self.axis_z.output_type if self.axis_z else OUT_FLOAT

    @property
    def is_axis_definition(self) -> bool:
        """ldp_*/ldpm_* — это таблицы опорных точек осей, а не «настройки»."""
        return self.title.startswith(("ldp_", "ldpm_"))


@dataclass
class PatchEntry:
    name: str = ""
    address: int = 0
    size: int = 0
    patch_data: bytes = b""
    base_data: bytes = b""


@dataclass
class Patch:
    unique_id: int = 0
    title: str = ""
    description: str = ""
    categories: List[int] = field(default_factory=list)
    entries: List[PatchEntry] = field(default_factory=list)


# ---------------------------------------------------------------------------


class XdfFile:
    """Разобранный .xdf."""

    def __init__(self, path: str):
        self.path = os.path.abspath(path)
        self.title = ""
        self.description = ""
        self.author = ""
        self.file_version = ""
        self.base_offset = 0
        self.base_subtract = False
        self.region_size = 0
        self.defaults = Defaults()
        self.categories: Dict[int, str] = {}
        self.items: List[Item] = []
        self.patches: List[Patch] = []
        self._by_uid: Dict[int, Item] = {}
        self._by_title: Dict[str, Item] = {}
        self._parse()

    # ------------------------------------------------------------------
    def _parse(self) -> None:
        try:
            tree = ET.parse(self.path)
        except ET.ParseError as exc:
            raise ValueError(f"не удалось разобрать XDF {self.path}: {exc}") from exc
        root = tree.getroot()

        header = root.find("XDFHEADER")
        if header is not None:
            self.title = _text(header, "deftitle")
            self.description = _text(header, "description")
            self.author = _text(header, "author")
            self.file_version = _text(header, "fileversion")

            base = header.find("BASEOFFSET")
            if base is not None:
                self.base_offset = parse_int(base.get("offset"), 0)
                self.base_subtract = parse_int(base.get("subtract"), 0) == 1

            defaults = header.find("DEFAULTS")
            if defaults is not None:
                self.defaults = Defaults(
                    size_bits=parse_int(defaults.get("datasizeinbits"), 8),
                    sig_digits=parse_int(defaults.get("sigdigits"), 2),
                    output_type=parse_int(defaults.get("outputtype"), OUT_FLOAT),
                    signed=parse_int(defaults.get("signed"), 0) == 1,
                    lsb_first=parse_int(defaults.get("lsbfirst"), 0) == 1,
                    is_float=parse_int(defaults.get("float"), 0) == 1,
                )

            region = header.find("REGION")
            if region is not None:
                self.region_size = parse_int(region.get("size"), 0)

            for cat in header.findall("CATEGORY"):
                idx = parse_int(cat.get("index"), -1)
                if idx >= 0:
                    self.categories[idx] = cat.get("name", "") or ""

        for elem in root:
            tag = elem.tag.upper()
            if tag == "XDFCONSTANT":
                self._add(self._parse_constant(elem))
            elif tag == "XDFTABLE":
                self._add(self._parse_table(elem))
            elif tag == "XDFPATCH":
                self.patches.append(self._parse_patch(elem))

    def _add(self, item: Item) -> None:
        self.items.append(item)
        if item.unique_id:
            self._by_uid.setdefault(item.unique_id, item)
        if item.title:
            self._by_title.setdefault(item.title, item)

    # ------------------------------------------------------------------
    @staticmethod
    def _categories_of(elem: ET.Element) -> List[int]:
        out = []
        for mem in elem.findall("CATEGORYMEM"):
            # TunerPro хранит категорию как index+1, 0 = «нет категории»
            cat = parse_int(mem.get("category"), 0)
            if cat > 0:
                out.append(cat - 1)
        return out

    @staticmethod
    def _equation_of(elem: Optional[ET.Element]) -> Equation:
        if elem is None:
            return Equation("X")
        math_elem = elem.find("MATH")
        if math_elem is None:
            return Equation("X")
        names = [v.get("id", "") for v in math_elem.findall("VAR") if v.get("id")]
        return Equation(math_elem.get("equation", "X"), names)

    def _parse_constant(self, elem: ET.Element) -> Item:
        item = Item(
            kind="constant",
            unique_id=parse_int(elem.get("uniqueid"), 0),
            title=_text(elem, "title"),
            description=_text(elem, "description"),
            categories=self._categories_of(elem),
            vis_level=parse_int(elem.get("vislevel"), 1),
            flags=parse_int(elem.get("flags"), 0),
            embedded=Embedded.from_elem(elem.find("EMBEDDEDDATA"), self.defaults),
            units=_text(elem, "units"),
            decimals=int(_num(elem, "decimalpl", self.defaults.sig_digits) or 0),
            output_type=int(_num(elem, "outputtype", self.defaults.output_type) or OUT_FLOAT),
            equation=self._equation_of(elem),
            range_low=_num(elem, "rangelow"),
            range_high=_num(elem, "rangehigh"),
        )
        return item

    def _parse_axis(self, elem: ET.Element) -> Axis:
        axis = Axis(
            axis_id=(elem.get("id") or "z").lower(),
            embedded=Embedded.from_elem(elem.find("EMBEDDEDDATA"), self.defaults),
            units=_text(elem, "units"),
            index_count=int(_num(elem, "indexcount", 0) or 0),
            decimals=int(_num(elem, "decimalpl", self.defaults.sig_digits) or 0),
            output_type=int(_num(elem, "outputtype", self.defaults.output_type) or OUT_FLOAT),
            equation=self._equation_of(elem),
            min_value=_num(elem, "min"),
            max_value=_num(elem, "max"),
        )
        info = elem.find("embedinfo")
        if info is not None:
            axis.link_type = parse_int(info.get("type"), 0)
            link = info.get("linkobjid")
            if link is not None:
                axis.link_id = parse_int(link, 0) or None
        for label in elem.findall("LABEL"):
            try:
                axis.labels.append(float(label.get("value", "0")))
            except ValueError:
                axis.labels.append(0.0)
        return axis

    def _parse_table(self, elem: ET.Element) -> Item:
        item = Item(
            kind="table",
            unique_id=parse_int(elem.get("uniqueid"), 0),
            title=_text(elem, "title"),
            description=_text(elem, "description"),
            categories=self._categories_of(elem),
            vis_level=parse_int(elem.get("vislevel"), 1),
            flags=parse_int(elem.get("flags"), 0),
        )
        for axis_elem in elem.findall("XDFAXIS"):
            axis = self._parse_axis(axis_elem)
            if axis.axis_id == "x":
                item.axis_x = axis
            elif axis.axis_id == "y":
                item.axis_y = axis
            else:
                item.axis_z = axis
        return item

    def _parse_patch(self, elem: ET.Element) -> Patch:
        patch = Patch(
            unique_id=parse_int(elem.get("uniqueid"), 0),
            title=_text(elem, "title"),
            description=_text(elem, "description"),
            categories=self._categories_of(elem),
        )
        for entry in elem.findall("XDFPATCHENTRY"):
            try:
                pdata = bytes.fromhex(entry.get("patchdata", "") or "")
            except ValueError:
                pdata = b""
            try:
                bdata = bytes.fromhex(entry.get("basedata", "") or "")
            except ValueError:
                bdata = b""
            patch.entries.append(
                PatchEntry(
                    name=entry.get("name", "") or "",
                    address=parse_int(entry.get("address"), 0),
                    size=parse_int(entry.get("datasize"), len(pdata)),
                    patch_data=pdata,
                    base_data=bdata,
                )
            )
        return patch

    # ------------------------------------------------------------------
    # доступ
    # ------------------------------------------------------------------
    def by_uid(self, uid: int) -> Optional[Item]:
        return self._by_uid.get(uid)

    def by_title(self, title: str) -> Optional[Item]:
        return self._by_title.get(title)

    def category_name(self, index: int) -> str:
        return self.categories.get(index, f"Категория 0x{index:X}")

    def category_names(self, item: Item) -> List[str]:
        return [self.category_name(c) for c in item.categories] or ["<без категории>"]

    def readable_items(self, include_axes: bool = False) -> Iterator[Item]:
        """Все объекты, у которых есть адрес в бинарнике."""
        for item in self.items:
            data = item.data
            if data is None or not data.has_data:
                continue
            if not include_axes and item.is_axis_definition:
                continue
            yield item

    # ------------------------------------------------------------------
    def file_offset(self, address: int, offset_override: Optional[int] = None) -> int:
        """Адрес из XDF -> смещение в файле."""
        base = self.base_offset if offset_override is None else offset_override
        return address - base if self.base_subtract else address + base

    def __repr__(self) -> str:  # pragma: no cover
        return (
            f"XdfFile({self.title!r}, v{self.file_version}, "
            f"{len(self.items)} объектов, {len(self.patches)} патчей)"
        )


def load(path: str) -> XdfFile:
    return XdfFile(path)


def load_many(paths: Sequence[str]) -> List[XdfFile]:
    return [XdfFile(p) for p in paths]
