# -*- coding: utf-8 -*-
"""
Firmware edits: a draft of changes, checked, previewed and written to a NEW file.

The AI (through MCP) or the user collects changes in a draft. Nothing touches a
file until the user presses "Create .bin" in the window; there is no MCP tool
for that. Writing is the exact mirror of reading (binfile.Reader): the same
address, strides, byte order and sign.

Kinds of change:
    value   one constant                       {"value": 2.93}
    cells   chosen cells of a map              {"cells": [{"row": 2, "col": 5, "value": 21.0}, ...]}
    region  a block of a map                   {"op": "add"|"mul"|"set", "amount": 1.5,
                                                "row_from": 3, "row_to": 7, "col_from": 0, "col_to": 4}
    patch   a patch from the Patchlist XDF     {"enable": true}

Cells and regions can also be addressed by axis values instead of indices
("y": 4000, "x": 300 / "y_from", "y_to", "x_from", "x_to"); they must hit
axis breakpoints.

Guards (writing is refused when any fails):
  * the XDF base offset must be the one the XDF declares (no guessing on write),
    and the firmware software version must match the XDF;
  * the conversion formula must be valid and the value must fit the field
    after rounding to a raw step (the value that will really land is shown);
  * a patch is applied only over its original bytes and never overlaps a map
    edit; a patch outside the file needs the full 512 KB image;
  * after writing, the file is read back and must differ from the original in
    exactly the planned bytes.
"""

from __future__ import annotations

import datetime as _dt
import hashlib
import json
import os
import re
import struct
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from . import names
from .binfile import BinFile, Reader, format_number
from .i18n import t
from .xdf import OUT_TEXT, Item, XdfFile

KINDS = ("value", "cells", "region", "patch")
REGION_OPS = ("add", "mul", "set")
_VERSION_RE = re.compile(r"_v(\d+)$")


class EditError(ValueError):
    """A change that cannot be accepted; the text is shown as is."""


@dataclass
class Change:
    id: int
    kind: str
    target: str                 # parameter or patch title
    args: Dict[str, Any]
    reason: str
    source: str = "ai"          # "ai" | "user"
    created: str = ""
    # the log the change relies on: {"log": name, "bin_sha1": firmware it was recorded on}
    evidence: Dict[str, Any] = field(default_factory=dict)


@dataclass
class CellPlan:
    row: int
    col: int
    old: float                  # physical value now
    asked: float                # what was requested
    new: float                  # what really lands after rounding
    raw_old: int
    raw_new: int
    y: Optional[float] = None   # row axis value (rpm, load…), if the map has one
    x: Optional[float] = None   # column axis value


@dataclass
class ChangePlan:
    change: Change
    ok: bool = True
    error: str = ""
    red: List[str] = field(default_factory=list)       # why this needs a typed confirmation
    notes: List[str] = field(default_factory=list)
    cells: List[CellPlan] = field(default_factory=list)
    writes: List[Tuple[int, bytes, bytes]] = field(default_factory=list)  # (offset, old, new)
    item: Optional[Item] = None

    @property
    def changed_cells(self) -> int:
        return sum(1 for c in self.cells if c.raw_new != c.raw_old)


@dataclass
class DraftPlan:
    plans: List[ChangePlan]
    blockers: List[str]          # problems with the whole draft (writing refused)
    writes: Dict[int, Tuple[int, int]]   # file offset -> (old byte, new byte)
    needs_full_image: bool
    file_size: int

    @property
    def ok(self) -> bool:
        return not self.blockers and all(p.ok for p in self.plans)

    @property
    def red(self) -> bool:
        return any(p.red for p in self.plans if p.ok)

    def byte_runs(self) -> List[Tuple[int, bytes, bytes]]:
        """Changed bytes merged into contiguous runs: (offset, old, new)."""
        runs: List[Tuple[int, bytearray, bytearray]] = []
        for off in sorted(self.writes):
            old, new = self.writes[off]
            if old == new:
                continue
            if runs and runs[-1][0] + len(runs[-1][1]) == off:
                runs[-1][1].append(old)
                runs[-1][2].append(new)
            else:
                runs.append((off, bytearray([old]), bytearray([new])))
        return [(o, bytes(a), bytes(b)) for o, a, b in runs]


# ---------------------------------------------------------------------------
# Raw value encoding (mirror of Reader.raw_values)
# ---------------------------------------------------------------------------

def _int_range(size_bits: int, signed: bool) -> Tuple[int, int]:
    if signed:
        half = 1 << (size_bits - 1)
        return -half, half - 1
    return 0, (1 << size_bits) - 1


def _cell_offset(reader: Reader, item: Item, row: int, col: int) -> int:
    data = item.data
    return reader.item_offset(item) + row * data.row_stride + col * data.col_stride


def _encode(item: Item, raw: float) -> bytes:
    data = item.data
    nbytes = data.elem_bytes
    if data.is_float and nbytes in (4, 8):
        fmt = ("<" if data.lsb_first else ">") + ("f" if nbytes == 4 else "d")
        return struct.pack(fmt, raw)
    order = "little" if data.lsb_first else "big"
    return int(raw).to_bytes(nbytes, order, signed=data.signed)


def to_raw(item: Item, phys: float) -> Tuple[float, float]:
    """Physical value -> (raw value to store, physical value that really lands).

    Raises EditError when the value does not fit the field.
    """
    data = item.data
    eq = item.value_equation
    if eq.error:
        raise EditError(t("The conversion formula of {name} is broken ({error}); "
                          "writing through it is refused.", name=item.title, error=eq.error))
    if data.is_float and data.elem_bytes in (4, 8):
        raw = eq.invert(phys)
        if raw is None:
            raise EditError(t("The formula of {name} cannot be inverted.", name=item.title))
        return raw, eq.apply(raw)
    lo, hi = _int_range(data.size_bits, data.signed)
    raw = eq.invert(phys)
    if raw is None:
        if data.size_bits > 16:
            raise EditError(t("The formula of {name} cannot be inverted.", name=item.title))
        best = min(range(lo, hi + 1), key=lambda c: abs(eq.apply(c) - phys))
        return float(best), eq.apply(best)
    rounded = int(round(raw))
    if rounded < lo or rounded > hi:
        fmt = lambda v: format_number(v, item.value_decimals, 1)  # noqa: E731
        ends = sorted((eq.apply(lo), eq.apply(hi)))
        units = names.unit(item.value_units)
        raise EditError(t("{value} does not fit {name}: the field holds {low}…{high}.",
                          value=fmt(phys), name=item.title, low=fmt(ends[0]),
                          high=fmt(ends[1]) + (" " + units if units else "")))
    return float(rounded), eq.apply(rounded)


# ---------------------------------------------------------------------------
# Safety classification
# ---------------------------------------------------------------------------

_IGNITION = re.compile(r"^(ip|id|c)_iga", re.I)
_KNOCK = re.compile(r"knk|knock", re.I)
_LIMITS = re.compile(r"^(id|c|ip)_(n_max|vs_max|n_lim)", re.I)
_LAMBDA = re.compile(r"lam|afr", re.I)
_PROTECT_PATCH = re.compile(r"disable|delete|remove|off\b|knock|limp|protection|monitor", re.I)


def red_flags(item: Optional[Item], plan: ChangePlan) -> List[str]:
    """Reasons a change needs a typed confirmation (engine-risk categories)."""
    flags: List[str] = []
    if not plan.writes:
        return flags            # nothing changes, nothing to confirm
    if plan.change.kind == "patch":
        if _PROTECT_PATCH.search(plan.change.target) and plan.change.args.get("enable", True):
            flags.append(t("the patch switches off a function or a protection"))
        return flags
    if item is None or not plan.cells:
        return flags
    raised = any(c.new > c.old for c in plan.cells)
    lowered = any(c.new < c.old for c in plan.cells)
    title = item.title
    if _IGNITION.search(title) and raised:
        flags.append(t("more ignition advance"))
    if _KNOCK.search(title):
        flags.append(t("changes knock control"))
    if _LIMITS.search(title) and raised:
        flags.append(t("raises a speed or rev limit"))
    if _LAMBDA.search(title) and (raised or lowered) and ("fl" in title.lower() or "wot" in title.lower()):
        flags.append(t("changes the full-load mixture"))
    return flags


# ---------------------------------------------------------------------------
# The draft
# ---------------------------------------------------------------------------

class Draft:
    """Changes for one firmware file, kept on disk next to the settings."""

    def __init__(self, store_dir: str, bin_path: str):
        self.bin_path = os.path.abspath(bin_path)
        key = hashlib.sha1(self.bin_path.lower().encode("utf-8")).hexdigest()[:16]
        self.path = os.path.join(store_dir, f"draft_{key}.json")
        self.changes: List[Change] = []
        self._next = 1
        self._load()

    def _load(self) -> None:
        try:
            with open(self.path, encoding="utf-8") as fh:
                data = json.load(fh)
        except (OSError, ValueError):
            return
        if data.get("bin") != self.bin_path:
            return
        fields = set(Change.__dataclass_fields__)
        self.changes = [Change(**{k: v for k, v in c.items() if k in fields})
                        for c in data.get("changes", [])]
        self._next = max([c.id for c in self.changes] + [0]) + 1

    def save(self) -> None:
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        tmp = self.path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump({"bin": self.bin_path, "changes": [asdict(c) for c in self.changes]},
                      fh, ensure_ascii=False, indent=1)
        os.replace(tmp, self.path)

    def add(self, kind: str, target: str, args: Dict[str, Any], reason: str,
            source: str = "ai", evidence: Optional[Dict[str, Any]] = None) -> Change:
        if kind not in KINDS:
            raise EditError(t("Unknown kind of change {kind!r}; use one of: {kinds}.",
                              kind=kind, kinds=", ".join(KINDS)))
        if not (target or "").strip():
            raise EditError(t("Say which parameter or patch to change."))
        if not (reason or "").strip():
            raise EditError(t("Every change needs a reason: why it is made."))
        change = Change(id=self._next, kind=kind, target=target.strip(), args=dict(args or {}),
                        reason=reason.strip(), source=source,
                        created=_dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                        evidence=dict(evidence or {}))
        self._next += 1
        self.changes.append(change)
        self.save()
        return change

    def remove(self, change_id: int) -> bool:
        before = len(self.changes)
        self.changes = [c for c in self.changes if c.id != change_id]
        self.save()
        return len(self.changes) != before

    def clear(self) -> None:
        self.changes = []
        self.save()


# ---------------------------------------------------------------------------
# Planning: what each change does to the bytes
# ---------------------------------------------------------------------------

def _axis_index(values: Optional[List[float]], wanted: float, what: str, item: Item) -> int:
    if not values:
        raise EditError(t("{name} has no {axis} axis values; address cells by index.",
                          name=item.title, axis=what))
    for i, v in enumerate(values):
        if abs(v - wanted) <= max(1e-6, abs(v) * 1e-6):
            return i
    shown = ", ".join(format_number(v, 2, 1) for v in values)
    raise EditError(t("{value} is not a breakpoint of the {axis} axis of {name}. Breakpoints: {list}",
                      value=format_number(wanted, 2, 1), axis=what, name=item.title, list=shown))


def _index(spec: Dict[str, Any], idx_key: str, val_key: str, axis: Optional[List[float]],
           what: str, item: Item, limit: int, default: Optional[int] = None) -> int:
    if spec.get(idx_key) is not None:
        i = int(spec[idx_key])
    elif spec.get(val_key) is not None:
        i = _axis_index(axis, float(spec[val_key]), what, item)
    elif default is not None:
        i = default
    else:
        raise EditError(t("Give {a} (index) or {b} (axis value).", a=idx_key, b=val_key))
    if not 0 <= i < limit:
        raise EditError(t("{key} = {value} is outside {name} (0…{last}).",
                          key=idx_key, value=i, name=item.title, last=limit - 1))
    return i


def _plan_item_change(reader: Reader, change: Change, plan: ChangePlan) -> None:
    item = reader.xdf.by_title(change.target)
    if item is None:
        raise EditError(t("Parameter \"{name}\" not found in the XDF.", name=change.target))
    plan.item = item
    if item.value_output_type == OUT_TEXT:
        raise EditError(t("{name} is text; text fields are not edited.", name=item.title))
    if not reader.in_range(item):
        raise EditError(t("{name} lies outside this file.", name=item.title))
    matrix = reader.matrix(item)
    raws = reader.raw_matrix(item)
    if matrix is None or raws is None:
        raise EditError(t("Could not read the values."))
    rows, cols = item.rows, item.cols
    x = reader.axis_values(item, "x")
    y = reader.axis_values(item, "y")
    targets: Dict[Tuple[int, int], float] = {}
    args = change.args

    if change.kind == "value":
        if item.cell_count != 1:
            raise EditError(t("{name} is a map {shape}; use \"cells\" or \"region\".",
                              name=item.title, shape=item.shape_str))
        if args.get("value") is None:
            raise EditError(t("Give value."))
        targets[(0, 0)] = float(args["value"])
    elif change.kind == "cells":
        cells = args.get("cells") or []
        if not cells:
            raise EditError(t("Give cells: a list of {{row, col, value}}."))
        for cell in cells:
            r = _index(cell, "row", "y", y, t("row"), item, rows, 0 if rows == 1 else None)
            c = _index(cell, "col", "x", x, t("column"), item, cols, 0 if cols == 1 else None)
            if cell.get("value") is None:
                raise EditError(t("Every cell needs a value."))
            targets[(r, c)] = float(cell["value"])
    else:  # region
        op = args.get("op")
        if op not in REGION_OPS:
            raise EditError(t("op must be one of: {ops}.", ops=", ".join(REGION_OPS)))
        if args.get("amount") is None:
            raise EditError(t("Give amount."))
        amount = float(args["amount"])
        r0 = _index(args, "row_from", "y_from", y, t("row"), item, rows, 0)
        r1 = _index(args, "row_to", "y_to", y, t("row"), item, rows, rows - 1)
        c0 = _index(args, "col_from", "x_from", x, t("column"), item, cols, 0)
        c1 = _index(args, "col_to", "x_to", x, t("column"), item, cols, cols - 1)
        if r0 > r1 or c0 > c1:
            raise EditError(t("The region is empty: check from/to."))
        for r in range(r0, r1 + 1):
            for c in range(c0, c1 + 1):
                old = matrix[r][c]
                targets[(r, c)] = (old + amount if op == "add" else
                                   old * amount if op == "mul" else amount)

    for (r, c), asked in sorted(targets.items()):
        raw_new, landed = to_raw(item, asked)
        old = matrix[r][c]
        plan.cells.append(CellPlan(r, c, old, asked, landed, int(raws[r][c]), int(raw_new),
                                   y[r] if y and r < len(y) and rows > 1 else None,
                                   x[c] if x and c < len(x) and cols > 1 else None))
        if int(raw_new) != int(raws[r][c]) or item.data.is_float:
            off = _cell_offset(reader, item, r, c)
            old_bytes = reader.bin.slice(off, item.data.elem_bytes) or b""
            new_bytes = _encode(item, raw_new)
            if new_bytes != old_bytes:
                plan.writes.append((off, old_bytes, new_bytes))
    dec = item.value_decimals
    rounded = [c for c in plan.cells
               if format_number(c.new, dec, 1) != format_number(c.asked, dec, 1)]
    if rounded:
        worst = max(rounded, key=lambda c: abs(c.new - c.asked))
        plan.notes.append(t("Rounded to the raw step: asked {asked}, will be {new} {units} "
                            "(largest difference).",
                            asked=format_number(worst.asked, max(item.value_decimals, 3), 1),
                            new=format_number(worst.new, max(item.value_decimals, 3), 1),
                            units=names.unit(item.value_units)))
    if not plan.writes:
        plan.notes.append(t("The values are already like this — nothing to write."))
    # axis tables are shared: list every map that uses this one
    users = [other.title for other in reader.xdf.items
             for ax in (other.axis_x, other.axis_y) if ax is not None and ax.link_id == item.unique_id]
    if users:
        plan.notes.append(t("This is an axis shared by {n} maps: {list}. All of them change.",
                            n=len(users), list=", ".join(sorted(set(users)))))
        if plan.writes:
            plan.red.append(t("changes an axis shared by other maps"))


def _plan_patch(binf: BinFile, patchlist: Optional[XdfFile], change: Change, plan: ChangePlan) -> None:
    if patchlist is None:
        raise EditError(t("Choose the Patchlist XDF in the project to use patches."))
    patch = next((p for p in patchlist.patches if p.title == change.target), None)
    if patch is None:
        raise EditError(t("Patch \"{name}\" not found in the patchlist.", name=change.target))
    enable = bool(change.args.get("enable", True))
    for entry in patch.entries:
        off = patchlist.file_offset(entry.address)
        want = entry.patch_data if enable else entry.base_data
        expect = entry.base_data if enable else entry.patch_data
        if not want:
            raise EditError(t("The patch has no {what} bytes for {name}.",
                              what=t("patched") if enable else t("original"), name=entry.name))
        chunk = binf.slice(off, len(want))
        if chunk is None:
            raise EditError(t("The patch writes at 0x{off:X}, outside this {kb} KB file. "
                              "Patches change program code: use the full 512 KB image.",
                              off=off, kb=binf.size_kb))
        if chunk == want:
            continue
        if expect and chunk != expect[:len(chunk)]:
            raise EditError(t("At 0x{off:X} the file has {got}, not the expected {exp}: the "
                              "patch is not written over unknown bytes.",
                              off=off, got=chunk.hex().upper(), exp=expect.hex().upper()))
        plan.writes.append((off, chunk, want))
    if not plan.writes:
        plan.notes.append(t("The patch is already in this state — nothing to write."))


def cell_label(cell: CellPlan) -> str:
    """"[8,9] 3200×500" — indices plus the axis values when known."""
    axes = "×".join(format_number(v, 0 if float(v).is_integer() else 2, 1)
                    for v in (cell.y, cell.x) if v is not None)
    return f"[{cell.row},{cell.col}]" + (f" {axes}" if axes else "")


def plan_draft(reader: Reader, draft: Draft, patchlist: Optional[XdfFile] = None) -> DraftPlan:
    """Check every change and work out the bytes. Never writes anything."""
    blockers: List[str] = []
    if not reader.offset.declared:
        blockers.append(t("The XDF offset was guessed ({label}), not taken from the XDF: "
                          "writing is refused. Use an XDF that matches this file.",
                          label=reader.offset.label))
    warning = reader.version_warning()
    if warning:
        blockers.append(t("Software version mismatch: {text}", text=warning))
    plans: List[ChangePlan] = []
    writes: Dict[int, Tuple[int, int]] = {}
    owner: Dict[int, int] = {}
    needs_full = False
    bin_sha1 = hashlib.sha1(reader.bin.data).hexdigest()
    for change in draft.changes:
        plan = ChangePlan(change=change)
        ev = change.evidence or {}
        if ev.get("bin_sha1") and ev["bin_sha1"] != bin_sha1:
            plan.red.append(t("relies on the log {log}, recorded on ANOTHER firmware",
                              log=ev.get("log", "?")))
        try:
            if change.kind == "patch":
                _plan_patch(reader.bin, patchlist, change, plan)
                # patches change program code: flash the full image
                needs_full = needs_full or bool(plan.writes)
            else:
                _plan_item_change(reader, change, plan)
        except EditError as exc:
            plan.ok, plan.error = False, str(exc)
        plan.red = sorted(set(plan.red + red_flags(plan.item, plan)))
        if plan.ok:
            for off, old, new in plan.writes:
                for i, b in enumerate(new):
                    pos = off + i
                    prev = owner.get(pos)
                    if prev is not None and prev != change.id:
                        prev_change = next(c for c in draft.changes if c.id == prev)
                        if "patch" in (prev_change.kind, change.kind):
                            plan.ok = False
                            plan.error = t("Overlaps change #{n} at 0x{off:X}: a patch and another "
                                           "edit must not touch the same bytes.", n=prev, off=pos)
                            break
                        plan.notes.append(t("Overrides change #{n} at 0x{off:X}.", n=prev, off=pos))
                    owner[pos] = change.id
                    writes[pos] = (writes.get(pos, (old[i], 0))[0], b)
                if not plan.ok:
                    break
        plans.append(plan)
    if not draft.changes:
        blockers.append(t("The draft is empty."))
    return DraftPlan(plans, blockers, writes, needs_full, len(reader.bin))


# ---------------------------------------------------------------------------
# Writing
# ---------------------------------------------------------------------------

def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def next_version_path(bin_path: str) -> str:
    """name.bin -> name_v1.bin; name_v3.bin -> name_v4.bin (first free number)."""
    folder, base = os.path.split(os.path.abspath(bin_path))
    stem, ext = os.path.splitext(base)
    match = _VERSION_RE.search(stem)
    root = stem[:match.start()] if match else stem
    n = int(match.group(1)) + 1 if match else 1
    while os.path.exists(os.path.join(folder, f"{root}_v{n}{ext or '.bin'}")):
        n += 1
    return os.path.join(folder, f"{root}_v{n}{ext or '.bin'}")


def write_new_bin(reader: Reader, draft: Draft, patchlist: Optional[XdfFile] = None,
                  confirm_red: bool = False) -> Dict[str, Any]:
    """Create name_vN.bin and name_vN.changes.txt. Returns paths and checksums."""
    plan = plan_draft(reader, draft, patchlist)
    problems = plan.blockers + [f"#{p.change.id} {p.change.target}: {p.error}"
                                for p in plan.plans if not p.ok]
    if problems:
        raise EditError(t("Writing refused:\n{list}", list="\n".join(problems)))
    if plan.red and not confirm_red:
        raise EditError(t("The draft has risky changes; confirm them first."))
    original = bytes(reader.bin.data)
    data = bytearray(original)
    for off, (_old, new) in plan.writes.items():
        data[off] = new
    out_path = next_version_path(reader.bin.path)
    with open(out_path, "xb") as fh:          # never overwrites
        fh.write(data)
    with open(out_path, "rb") as fh:
        back = fh.read()
    diff = {i for i in range(len(original)) if back[i] != original[i]} if len(back) == len(original) else None
    planned = {off for off, (old, new) in plan.writes.items() if old != new}
    if diff != planned:
        os.remove(out_path)
        raise EditError(t("Read-back check failed: the written file differs from the plan. "
                          "Nothing was kept."))
    notes_path = os.path.splitext(out_path)[0] + ".changes.txt"
    with open(notes_path, "w", encoding="utf-8") as fh:
        fh.write(changes_text(reader, plan, out_path, sha256(original), sha256(back)))
    return {"path": out_path, "notes": notes_path, "sha256": sha256(back),
            "bytes": len(planned), "changes": len(plan.plans)}


def changes_text(reader: Reader, plan: DraftPlan, out_path: str, sha_src: str, sha_new: str) -> str:
    """The change log written next to the new firmware (like TunerPro's history)."""
    out = [t("MS43 AI-Tuner — firmware changes"),
           t("Created     : {when}", when=_dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")),
           t("Source      : {name}  sha256 {sha}", name=os.path.basename(reader.bin.path), sha=sha_src),
           t("New file    : {name}  sha256 {sha}", name=os.path.basename(out_path), sha=sha_new),
           t("XDF         : {title} v{ver}", title=reader.xdf.title, ver=reader.xdf.file_version),
           t("Bytes changed: {n}", n=sum(1 for o, n in plan.writes.values() if o != n)),
           ""]
    if plan.needs_full_image:
        out.append(t("Flash the FULL 512 KB image: the changes include program code (patches)."))
    else:
        out.append(t("Calibration-only flash is enough (no program code changed)."))
    out.append(t("Checksums: recalculated by MS4X Flasher when flashing."))
    out.append("")
    for p in plan.plans:
        c = p.change
        out.append(f"#{c.id} [{c.kind}] {c.target}  ({c.source}, {c.created})")
        out.append(t("  Why: {text}", text=c.reason))
        if c.evidence.get("log"):
            out.append(t("  Evidence log: {name}", name=c.evidence["log"]))
        for flag in p.red:
            out.append(t("  RISK: {text}", text=flag))
        if p.item is not None and p.cells:
            dec = max(p.item.value_decimals, 2)
            units = names.unit(p.item.value_units)
            changed = [cell for cell in p.cells if cell.raw_new != cell.raw_old]
            out.append(t("  Cells changed: {n} of {total}", n=len(changed), total=len(p.cells)))
            for cell in changed[:200]:
                out.append(f"    {cell_label(cell)}: {format_number(cell.old, dec, 1)} -> "
                           f"{format_number(cell.new, dec, 1)} {units}".rstrip())
            if len(changed) > 200:
                out.append(t("    … and {n} more", n=len(changed) - 200))
        for off, old, new in p.writes[:50]:
            out.append(f"    0x{off:05X}: {old.hex().upper()} -> {new.hex().upper()}")
        for note in p.notes:
            out.append(f"  * {note}")
        out.append("")
    return "\n".join(out)


def apply_to_bytes(original: bytes, plan: DraftPlan) -> bytes:
    """The draft applied in memory (for previews)."""
    data = bytearray(original)
    for off, (_old, new) in plan.writes.items():
        data[off] = new
    return bytes(data)
