# -*- coding: utf-8 -*-
"""
Comparing and porting settings between DIFFERENT software versions.

A normal diff compares two bins of one version with one XDF — comparing bytes
is enough there. Here the versions differ (e.g. 430069 and MS43X001), each has
its own XDF, and addresses are not guaranteed to match.

So parameters are matched **by name**, and what is compared and ported are
**physical values**, not raw bytes. This matters: 430069 and MS43X001 have more
than a hundred parameters with different conversion formulas, and a byte-wise
copy would silently change the value.

Porting chain for one parameter:

    raw from A --formula A--> physical value --inverse formula B--> raw for B

Every step checks:
  * whether the parameter exists in the target XDF;
  * whether the map sizes match;
  * whether the formula is invertible (linear — analytically, non-linear 8/16
    bit — by searching the nearest integer, wider — refused);
  * whether the result fits the bit width and signedness of the target field;
  * the quantisation error after rounding.

Anything that fails a check is not written to the target file and is listed in
the report with the reason.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence, Tuple

from .binfile import BinFile, Reader, format_number
from .i18n import t
from .xdf import OUT_TEXT, Item, XdfFile

# Row statuses (stable codes; show them via status_label()).
ST_OK = "same"
ST_DIFF = "different"
ST_ONLY_A = "missing in B"
ST_ONLY_B = "missing in A"
ST_SHAPE = "different shape"
ST_UNREADABLE = "unreadable"

# Port plan statuses.
# The program writes nothing to the firmware — it only builds a plan, and the
# user makes the edits by hand in TunerPro (more reliable). "Safe" comes in two
# kinds: a full byte-level match (copy 1:1) and a name-only match (port the
# physical value by hand). Everything else is a warning explaining what is wrong.
P_SAFE_BYTES = "safe: byte match"
P_SAFE_NAME = "safe: name match"
P_WARN = "warning"


def status_label(code: str) -> str:
    """User-facing text for an ST_* / P_* status code."""
    return {
        ST_OK: t("same"),
        ST_DIFF: t("different"),
        ST_ONLY_A: t("missing in B"),
        ST_ONLY_B: t("missing in A"),
        ST_SHAPE: t("different shape"),
        ST_UNREADABLE: t("unreadable"),
        P_SAFE_BYTES: t("safe: byte match"),
        P_SAFE_NAME: t("safe: name match"),
        P_WARN: t("warning"),
    }.get(code, code)


# Reasons phys_to_raw() can refuse a value.
def _reason_no_target() -> str:
    return t("the parameter has no data in the target firmware")


def _reason_not_invertible() -> str:
    return t("the formula cannot be inverted for a field wider than 16 bits")


def _reason_range() -> str:
    return t("the value does not fit the bit width of the field")


# MS43X001 renamed some parameters compared to 430069:
# ip_iga_ron_98_pl_ivvt__n__maf became ip_iga_ron98_pl__n__maf, and the VANOS
# maps tco_1/tco_2 became ron98/e85 (flex-fuel was added). So matching works in
# three steps: exact name -> normalised name -> ranked candidates, from which a
# human picks.

# Noise tokens: present in one version, absent in the other, meaningless
_NOISE_TOKEN = re.compile(r"^(?:ivvt|iv)\d*$")


def normalize_title(title: str) -> str:
    """Canonical name form for matching versions.

    'ip_iga_ron_98_pl_ivvt__n__maf' -> 'ip_iga_ron98_pl__n__maf'

    Exactly two things happen: a numeric tail is glued to the previous token
    (ron_98 -> ron98) and the noise tokens ivvt/iv are dropped. Nothing
    "semantic" is guessed here — that is what candidate ranking is for.
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
    """Ranked match candidates. The map shape must match."""
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
    """Matches parameter names between two software versions."""

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
        """Return (name in the target version, how it was found)."""
        if title in self.items_dst:
            return title, t("exact name match")
        norm = normalize_title(title)
        dst = self._norm_dst.get(norm, [])
        src = self._norm_src.get(norm, [])
        # accept only if the match is unambiguous on both sides
        if len(dst) == 1 and len(src) == 1:
            return dst[0], t("matched after name normalisation ({src} -> {dst})", src=title, dst=dst[0])
        if len(dst) > 1:
            return None, t("several parameters match the normalised name")
        return None, ""


def scaling_notes(item_a: Item, item_b: Item) -> List[str]:
    """Notes on format differences between parameters with the same name."""
    notes: List[str] = []
    eq_a, eq_b = item_a.value_equation, item_b.value_equation
    if eq_a.source != eq_b.source:
        notes.append(t("different formulas: A \"{a}\", B \"{b}\"", a=eq_a.source, b=eq_b.source))
        # If the factors differ by exactly 10/100/1000 times, it is almost
        # certainly a typo in one of the XDFs, not a real format change.
        a_slope, b_slope = eq_a.linear[0], eq_b.linear[0]
        if a_slope and b_slope and eq_a.is_linear and eq_b.is_linear:
            ratio = b_slope / a_slope
            for power in (10.0, 100.0, 1000.0):
                if abs(ratio - power) < 1e-6 or abs(ratio - 1 / power) < 1e-9:
                    notes.append(t(
                        "the factors differ by exactly {power:g} times — looks like "
                        "a typo in one of the XDFs, check by hand before porting",
                        power=power))
                    break
    if item_a.data.size_bits != item_b.data.size_bits:
        notes.append(t("different bit width: {a} and {b} bits",
                       a=item_a.data.size_bits, b=item_b.data.size_bits))
    if item_a.data.signed != item_b.data.signed:
        notes.append(t("different signedness"))
    if item_a.address != item_b.address:
        notes.append(t("different addresses: 0x{a:X} and 0x{b:X}", a=item_a.address, b=item_b.address))
    return notes


def _int_range(size_bits: int, signed: bool) -> Tuple[int, int]:
    if signed:
        half = 1 << (size_bits - 1)
        return -half, half - 1
    return 0, (1 << size_bits) - 1


def phys_to_raw(item: Item, phys: float) -> Tuple[Optional[int], str]:
    """Physical value -> raw integer for this parameter.

    Returns (value, refusal reason). Linear formulas are inverted
    analytically, non-linear narrow fields by searching the nearest value.
    """
    data = item.data
    if data is None:
        return None, _reason_no_target()
    eq = item.value_equation
    lo, hi = _int_range(data.size_bits, data.signed)

    raw = eq.invert(phys)
    if raw is None:
        if data.size_bits > 16:
            return None, _reason_not_invertible()
        best, best_err = None, None
        for candidate in range(lo, hi + 1):
            err = abs(eq.apply(candidate) - phys)
            if best_err is None or err < best_err:
                best, best_err = candidate, err
        return best, ""

    rounded = int(round(raw))
    if rounded < lo or rounded > hi:
        return None, _reason_range()
    return rounded, ""


# ---------------------------------------------------------------------------
# Comparing two versions by name
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
        return t("{changed} of {total} cells differ, delta {lo}…{hi}",
                 changed=self.changed_cells, total=self.total_cells,
                 lo=format_number(self.delta_min, dec, otype),
                 hi=format_number(self.delta_max, dec, otype))

    @property
    def status_label(self) -> str:
        return status_label(self.status)


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
    """Compare two firmware files of different versions, matching parameters by name."""
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
                    notes=[t("{a} vs {b}", a=item_a.shape_str, b=item_b.shape_str)],
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
                    notes=[t("text: \"{a}\" -> \"{b}\"", a=text_a, b=text_b)],
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
# Settings port plan
# ---------------------------------------------------------------------------


@dataclass
class PortEntry:
    title: str                       # name of the parameter you changed in version A
    status: str
    item_src: Optional[Item] = None
    item_dst: Optional[Item] = None
    dst_title: str = ""
    candidates: List[Tuple[str, float]] = field(default_factory=list)
    phys_tuned: List[float] = field(default_factory=list)          # your value
    phys_target_before: List[float] = field(default_factory=list)  # what the target has now
    total_cells: int = 0
    match_bits: List[str] = field(default_factory=list)   # what matched (for "safe")
    warn_bits: List[str] = field(default_factory=list)    # what is wrong (for a warning)

    @property
    def safe(self) -> bool:
        return self.status in (P_SAFE_BYTES, P_SAFE_NAME)

    def detail(self) -> str:
        """Tooltip text: what matched or what is wrong."""
        if self.safe:
            return t("Match: ") + "; ".join(self.match_bits)
        return t("Problem: ") + "; ".join(self.warn_bits)

    @property
    def status_label(self) -> str:
        return status_label(self.status)

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
            return t("your value: {value}", value=tuned)
        before = fmt(self.phys_target_before)
        return t("your value: {value}   (target now: {before})", value=tuned, before=before)


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
    """Build a PLAN for porting your edits to firmware of another version.

    Writes nothing: it only shows which of your edits can be ported one-to-one
    and which need manual work. The user edits in TunerPro.

    bin_stock  — stock of the source version (reference for finding edits)
    bin_tuned  — your tuned firmware of the same version
    bin_target — firmware of the target version to port into

    Statuses:
      * safe by bytes — the name matches AND address, size and format are
        identical: the value can be copied 1:1;
      * safe by name — the name matches but the format differs: port the
        physical value by hand (TunerPro shows the physical meaning);
      * warning — not found by name (removed/renamed) or size/type differ:
        sort it out by hand.
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
            continue  # you did not touch this parameter

        entry = PortEntry(title=title, status=P_WARN, item_src=item_src)
        entry.phys_tuned = r_tuned.values(item_src) or []
        entry.total_cells = len(entry.phys_tuned)

        # --- look up the target version strictly by exact name ------------
        item_dst = items_dst.get(title)
        if item_dst is None:
            entry.status = P_WARN
            entry.candidates = match_candidates(item_src, items_dst)
            if entry.candidates:
                names = ", ".join(name for name, _ in entry.candidates[:4])
                entry.warn_bits.append(t(
                    "the target version has no parameter with this name; "
                    "similar ones (check by hand): {names}", names=names))
            else:
                entry.warn_bits.append(t(
                    "the target version has no parameter with this name and nothing "
                    "similar — the function was most likely removed"))
            plan.entries.append(entry)
            continue

        entry.item_dst = item_dst
        entry.dst_title = item_dst.title
        entry.phys_target_before = r_target.values(item_dst) or []

        # --- format comparison --------------------------------------------
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
            entry.warn_bits.append(t("text field — port by hand"))
            plan.entries.append(entry)
            continue
        if not same_shape:
            entry.status = P_WARN
            entry.warn_bits.append(t("map size differs: {a} vs {b}",
                                     a=item_src.shape_str, b=item_dst.shape_str))
            plan.entries.append(entry)
            continue

        # name and size match — already safe; find out how safe
        if same_addr and same_size and same_eq:
            entry.status = P_SAFE_BYTES
            entry.match_bits.append(t("name, address, size and formula are identical — "
                                      "can be copied 1:1"))
        else:
            entry.status = P_SAFE_NAME
            entry.match_bits.append(t("name and map size match"))
            if not same_eq:
                entry.match_bits.append(t(
                    "the formula differs (A \"{a}\", B \"{b}\") — port the physical "
                    "value, not the bytes",
                    a=item_src.value_equation.source, b=item_dst.value_equation.source))
            if not same_addr and d_src and d_dst:
                entry.match_bits.append(t("different addresses: 0x{a:X} → 0x{b:X}",
                                          a=d_src.address, b=d_dst.address))
            if not same_size and d_src and d_dst:
                entry.match_bits.append(t("different bit width: {a} → {b} bits",
                                          a=d_src.size_bits, b=d_dst.size_bits))

        plan.entries.append(entry)

    # order: safe by bytes first, then by name, then warnings
    order = {P_SAFE_BYTES: 0, P_SAFE_NAME: 1, P_WARN: 2}
    plan.entries.sort(key=lambda e: (order.get(e.status, 3), e.title))
    return plan
