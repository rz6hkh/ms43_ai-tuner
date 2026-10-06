# -*- coding: utf-8 -*-
"""
Volumetric efficiency (VE) map tuning from a wideband lambda log.

The idea is simple. The ECU estimates how much air entered the cylinder and
injects fuel for that amount. If the real mixture is leaner than the target,
there was actually more air than the ECU thought, and the VE map must go up.
And vice versa.

    correction = measured_lambda / target_lambda
    new_value = old_value × correction

Details that make the naive calculation lie:

  * **Closed loop.** With lambda control active the ECU has already adjusted
    the fuel, so the VE error shows up in the fuel trims, not in lambda. Hence
    the `trim` mode: the correction is taken from the trims. The `both` mode
    multiplies the two — right when the loop is closed but the sensor still
    shows a residual error.
  * **Transients.** On sharp throttle the sensor lags the event by the gas
    travel time, and acceleration enrichment distorts the picture. So by
    default only steady-state points are used: rpm and load change rates are
    limited.
  * **Sensor delay.** Shift the log back by N samples (`--delay`), otherwise
    the correction smears over neighbouring cells.
  * **Too little data.** A cell with three samples means nothing. Cells with
    few samples are left alone rather than filled with garbage.

The tool calculates and shows — whether to write it to the firmware is your call.
"""

from __future__ import annotations

import csv
import math
import os
import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence, Tuple

from .binfile import Reader
from .i18n import t
from .xdf import Item

# ---------------------------------------------------------------------------
# Reading the log
# ---------------------------------------------------------------------------

# Usual channel names in TunerPro/MS4x logs and popular wideband controllers.
# Matching is case-insensitive, by substring.
COLUMN_HINTS: Dict[str, Sequence[str]] = {
    "rpm": ("engine speed", "rpm", "\bn\b", "drehzahl", "nmot"),
    "load": ("mass air flow", "maf", "load", "map", "manifold", "rl", "füllung",
             "fuellung", "charge"),
    "lambda": ("wideband", "wb lambda", "afr", "lambda", "lsu", "o2", "aem",
               "innovate", "zeitronix"),
    "target": ("target lambda", "lambda target", "lam_sp", "commanded",
               "soll", "target afr"),
    "trim": ("trim", "adaptation", "fuel correction", "ltft", "stft", "lam_i",
             "integrator"),
    "tps": ("throttle", "tps", "pedal", "pvs"),
    "coolant": ("coolant", "tco", "water temp"),
    "time": ("time", "timestamp", "seconds", "zeit"),
}

# Stoichiometric ratios for converting AFR to lambda
STOICH = {
    "gasoline": 14.7,
    "e85": 9.765,
    "e10": 14.13,
    "methanol": 6.4,
}


class LogError(ValueError):
    """Something is wrong with the log."""


@dataclass
class LogColumns:
    rpm: str
    load: str
    lam: str
    target: Optional[str] = None
    trim: Optional[str] = None
    tps: Optional[str] = None
    coolant: Optional[str] = None
    time: Optional[str] = None


def _norm(name: str) -> str:
    return re.sub(r"[\s_\-\[\]()]+", " ", (name or "").strip().lower())


def guess_columns(headers: Sequence[str]) -> Dict[str, Optional[str]]:
    """Guess which log column is which."""
    normalized = {h: _norm(h) for h in headers}
    out: Dict[str, Optional[str]] = {}
    for role, hints in COLUMN_HINTS.items():
        best: Optional[str] = None
        best_score = 0
        for header, low in normalized.items():
            for hint in hints:
                if hint in low:
                    # a longer match beats a shorter one
                    score = len(hint) + (5 if low == hint else 0)
                    if score > best_score:
                        best, best_score = header, score
        out[role] = best
    return out


def read_log(path: str, delimiter: Optional[str] = None) -> Tuple[List[str], List[Dict[str, float]]]:
    """Read a CSV log. Returns (headers, rows of float values)."""
    if not os.path.isfile(path):
        raise LogError(t("Log file not found: {path}", path=path))
    with open(path, "r", encoding="utf-8-sig", errors="replace", newline="") as fh:
        sample = fh.read(8192)
        fh.seek(0)
        if delimiter is None:
            try:
                delimiter = csv.Sniffer().sniff(sample, delimiters=",;\t").delimiter
            except csv.Error:
                delimiter = ","
        reader = csv.reader(fh, delimiter=delimiter)
        rows = list(reader)
    if not rows:
        raise LogError(t("The log is empty"))

    # the header is the first line with at least one non-numeric field
    header_idx = 0
    for idx, row in enumerate(rows[:5]):
        if any(not _is_number(cell) for cell in row if cell.strip()):
            header_idx = idx
            break
    headers = [h.strip() for h in rows[header_idx]]

    data: List[Dict[str, float]] = []
    for row in rows[header_idx + 1:]:
        if not any(cell.strip() for cell in row):
            continue
        record: Dict[str, float] = {}
        for name, cell in zip(headers, row):
            value = _to_float(cell)
            if value is not None:
                record[name] = value
        if record:
            data.append(record)
    if not data:
        raise LogError(t("No numeric rows found in the log"))
    return headers, data


def _is_number(text: str) -> bool:
    return _to_float(text) is not None


def _to_float(text: str) -> Optional[float]:
    text = (text or "").strip().replace(",", ".")
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def to_lambda(value: float, fuel: str = "gasoline") -> float:
    """Convert a wideband reading to lambda.

    Controllers output lambda (around 1), AFR (around 14.7) or a 0-5 V voltage.
    We tell them apart by magnitude: more reliable than trusting the channel name.
    """
    if value <= 0:
        return 0.0
    if 0.4 <= value <= 1.6:
        return value                      # already lambda
    stoich = STOICH.get(fuel, STOICH["gasoline"])
    if 5.0 <= value <= 30.0:
        return value / stoich             # AFR
    return value                          # leave as is, the user decides


# ---------------------------------------------------------------------------
# Analysis result
# ---------------------------------------------------------------------------


@dataclass
class CellStat:
    row: int
    col: int
    samples: int = 0
    weight: float = 0.0
    _sum: float = 0.0
    _sum_sq: float = 0.0

    def add(self, correction: float, weight: float = 1.0) -> None:
        self.samples += 1
        self.weight += weight
        self._sum += correction * weight
        self._sum_sq += correction * correction * weight

    @property
    def mean(self) -> float:
        return self._sum / self.weight if self.weight else 1.0

    @property
    def spread(self) -> float:
        """RMS spread of the correction within the cell."""
        if self.weight <= 0:
            return 0.0
        mean = self.mean
        var = max(0.0, self._sum_sq / self.weight - mean * mean)
        return math.sqrt(var)


@dataclass
class TuneResult:
    item: Item
    old: List[List[float]]
    new: List[List[float]]
    correction: List[List[float]]          # multiplier, 1.0 = unchanged
    stats: Dict[Tuple[int, int], CellStat] = field(default_factory=dict)
    used_samples: int = 0
    total_samples: int = 0
    skipped: Dict[str, int] = field(default_factory=dict)
    mode: str = "lambda"
    notes: List[str] = field(default_factory=list)
    y_role: str = "rpm"
    x_role: str = "load"

    @property
    def touched_cells(self) -> int:
        return sum(1 for r in range(len(self.old))
                   for c in range(len(self.old[0]))
                   if self.new[r][c] != self.old[r][c])

    @property
    def coverage(self) -> float:
        total = len(self.old) * len(self.old[0]) if self.old else 0
        covered = sum(1 for s in self.stats.values() if s.samples)
        return covered / total if total else 0.0

    def samples_at(self, row: int, col: int) -> int:
        stat = self.stats.get((row, col))
        return stat.samples if stat else 0

    def correction_percent(self, row: int, col: int) -> float:
        pct = (self.correction[row][col] - 1.0) * 100.0
        return 0.0 if abs(pct) < 0.05 else pct   # no "-0.0 %" in tables


# ---------------------------------------------------------------------------
# Main calculation
# ---------------------------------------------------------------------------


def _bracket(axis: Sequence[float], value: float) -> Tuple[int, int, float]:
    """Indices of the neighbouring axis nodes and the weight of the right one (bilinear)."""
    if not axis:
        return 0, 0, 0.0
    if len(axis) == 1:
        return 0, 0, 0.0
    ascending = axis[-1] >= axis[0]
    points = list(axis) if ascending else list(reversed(axis))
    if value <= points[0]:
        idx = 0
        t = 0.0
    elif value >= points[-1]:
        idx = len(points) - 2
        t = 1.0
    else:
        idx = 0
        for i in range(len(points) - 1):
            if points[i] <= value <= points[i + 1]:
                idx = i
                break
        span = points[idx + 1] - points[idx]
        t = (value - points[idx]) / span if span else 0.0
    lo, hi = idx, idx + 1
    if not ascending:
        lo, hi = len(axis) - 1 - lo, len(axis) - 1 - hi
    return lo, hi, t


def detect_axis_roles(reader: Reader, item: Item) -> Tuple[str, str]:
    """Which axis is which: returns the roles (rows, columns).

    "rpm on rows" cannot be assumed: ip_map_ve_1__map__n has manifold pressure
    on rows and rpm on columns, ip_iga_ron98_pl__n__maf the other way round.
    Look at the axis units first, then at the name tokens.
    """

    def role_of(units: str, token: str) -> Optional[str]:
        low = (units or "").strip().lower()
        if low in ("rpm", "1/min"):
            return "rpm"
        if low in ("hpa", "kpa", "mbar", "bar", "kg/h", "mg/stk", "%", "mg/hub"):
            return "load"
        token = (token or "").lower()
        if token in ("n", "n32", "n_32", "nmot"):
            return "rpm"
        if token in ("map", "maf", "load", "ve", "rl", "pq", "maf_kgh"):
            return "load"
        return None

    parts = item.title.split("__")[1:] if "__" in item.title else []
    y_token = parts[-2] if len(parts) >= 2 else (parts[0] if parts else "")
    x_token = parts[-1] if len(parts) >= 2 else ""

    y_units = item.axis_y.units if item.axis_y else ""
    x_units = item.axis_x.units if item.axis_x else ""
    y_role = role_of(y_units, y_token)
    x_role = role_of(x_units, x_token)

    if y_role and not x_role:
        x_role = "load" if y_role == "rpm" else "rpm"
    elif x_role and not y_role:
        y_role = "load" if x_role == "rpm" else "rpm"
    elif not y_role and not x_role:
        # last resort: rpm axes usually end well above a thousand
        y_axis = reader.axis_values(item, "y") or [0]
        x_axis = reader.axis_values(item, "x") or [0]
        if max(x_axis) > max(y_axis):
            y_role, x_role = "load", "rpm"
        else:
            y_role, x_role = "rpm", "load"
    elif y_role == x_role:
        # both look the same — trust the one with explicit units
        if (x_units or "").lower() in ("rpm", "1/min"):
            y_role = "load"
        else:
            x_role = "load" if y_role == "rpm" else "rpm"
    return y_role, x_role


def analyse(
    reader: Reader,
    item: Item,
    log_rows: Sequence[Dict[str, float]],
    columns: LogColumns,
    *,
    mode: str = "lambda",
    fuel: str = "gasoline",
    target_lambda: float = 1.0,
    min_samples: int = 8,
    max_spread: float = 0.06,
    max_step: float = 0.25,
    delay_samples: int = 0,
    steady_rpm: float = 250.0,
    steady_load: float = 8.0,
    min_coolant: Optional[float] = 70.0,
    smooth: bool = True,
) -> TuneResult:
    """Calculate the map correction from the log.

    mode: 'lambda' — sensor only; 'trim' — fuel trims only;
          'both' — multiply them (closed loop with a residual error).
    max_step: never move a cell by more than this fraction in one pass.
    """
    old = reader.matrix(item)
    if not old:
        raise LogError(t("Could not read the map from the firmware"))
    rows, cols = item.rows, item.cols
    y_axis = reader.axis_values(item, "y") or list(range(rows))
    x_axis = reader.axis_values(item, "x") or list(range(cols))

    # Axis roles are detected, not assumed: ip_map_ve_1__map__n has pressure on
    # rows and rpm on columns, ip_iga_ron98_pl__n__maf the other way round.
    y_role, x_role = detect_axis_roles(reader, item)

    stats: Dict[Tuple[int, int], CellStat] = {}
    k_channels = t("required channels missing")
    k_transient = t("transient")
    k_cold = t("cold engine")
    k_range = t("sensor reading out of range")
    skipped: Dict[str, int] = {k_channels: 0, k_transient: 0, k_cold: 0, k_range: 0}
    used = 0

    prev_rpm: Optional[float] = None
    prev_load: Optional[float] = None

    for idx, row in enumerate(log_rows):
        rpm = row.get(columns.rpm)
        load = row.get(columns.load)
        # sensor readings are shifted: exhaust gas does not reach the sensor instantly
        source = log_rows[idx + delay_samples] if 0 <= idx + delay_samples < len(log_rows) else None
        lam_raw = source.get(columns.lam) if source else None

        if rpm is None or load is None or lam_raw is None:
            skipped[k_channels] += 1
            continue

        if min_coolant is not None and columns.coolant:
            coolant = row.get(columns.coolant)
            if coolant is not None and coolant < min_coolant:
                skipped[k_cold] += 1
                continue

        if prev_rpm is not None and prev_load is not None:
            if abs(rpm - prev_rpm) > steady_rpm or abs(load - prev_load) > steady_load:
                prev_rpm, prev_load = rpm, load
                skipped[k_transient] += 1
                continue
        prev_rpm, prev_load = rpm, load

        measured = to_lambda(lam_raw, fuel)
        if not (0.4 <= measured <= 1.6):
            skipped[k_range] += 1
            continue

        target = target_lambda
        if columns.target:
            candidate = row.get(columns.target)
            if candidate:
                target = to_lambda(candidate, fuel)
        if target <= 0:
            target = target_lambda

        correction = 1.0
        if mode in ("lambda", "both"):
            correction *= measured / target
        if mode in ("trim", "both") and columns.trim:
            trim = row.get(columns.trim)
            if trim is not None:
                # trims come in percent (±10) or as fractions (±0.1)
                factor = 1.0 + (trim / 100.0 if abs(trim) > 1.5 else trim)
                if factor > 0:
                    correction *= factor

        y_value = rpm if y_role == "rpm" else load
        x_value = rpm if x_role == "rpm" else load
        r_lo, r_hi, ty = _bracket(y_axis, y_value)
        c_lo, c_hi, tx = _bracket(x_axis, x_value)
        for r, wy in ((r_lo, 1 - ty), (r_hi, ty)):
            for c, wx in ((c_lo, 1 - tx), (c_hi, tx)):
                weight = wy * wx
                if weight <= 0 or not (0 <= r < rows and 0 <= c < cols):
                    continue
                stats.setdefault((r, c), CellStat(r, c)).add(correction, weight)
        used += 1

    # --- collect the correction per cell ---
    factor = [[1.0 for _ in range(cols)] for _ in range(rows)]
    for (r, c), stat in stats.items():
        if stat.samples < min_samples:
            continue
        if stat.spread > max_spread:
            continue
        value = stat.mean
        value = max(1.0 - max_step, min(1.0 + max_step, value))
        factor[r][c] = value

    if smooth:
        factor = _smooth(factor, stats, min_samples)

    new = [[old[r][c] * factor[r][c] for c in range(cols)] for r in range(rows)]

    result = TuneResult(
        item=item, old=old, new=new, correction=factor, stats=stats,
        used_samples=used, total_samples=len(log_rows), skipped=skipped, mode=mode,
        y_role=y_role, x_role=x_role,
    )
    result.notes.extend(_advise(result, columns, mode, max_step))
    return result


def _advise(result: "TuneResult", columns: LogColumns, mode: str,
            max_step: float) -> List[str]:
    """Remarks "as an experienced tuner would look at this run".

    Decides nothing for the user, but spells out what most often leads to a
    garbage result or a broken engine.
    """
    notes: List[str] = []
    item = result.item
    min_needed = 32

    if result.used_samples < min_needed:
        notes.append(t(
            "Only {n} usable samples — too few for any conclusion. You need a warm "
            "run holding steady operating points, not a single drive.",
            n=result.used_samples))
    if result.coverage < 0.3:
        notes.append(t(
            "The log covered {pct:.0f}% of the map cells. Uncovered cells are left "
            "alone — that is correct, but the map is only partly tuned. Log the "
            "missing areas in separate runs.", pct=result.coverage * 100))
    if mode == "lambda" and not columns.trim:
        notes.append(t(
            "The \"by sensor\" mode is only valid in open loop (full load). At part "
            "load the ECU adjusts the mixture itself and the VE error goes into the "
            "fuel trims — then you need the trim or both mode and a trim channel "
            "in the log."))
    if columns.trim and mode == "lambda":
        notes.append(t(
            "The log has a fuel trim channel, but it is not used. "
            "For closed loop try --mode both."))

    extreme = [
        (r, c) for r in range(item.rows) for c in range(item.cols)
        if abs(result.correction_percent(r, c)) >= max_step * 100 - 0.01
        and result.new[r][c] != result.old[r][c]
    ]
    if extreme:
        notes.append(t(
            "{n} cells hit the correction limit of ±{pct:.0f}%. This does not mean "
            "\"raise the limit\" — it means the airflow model is systematically off: "
            "check the MAF/MAP calibration, injector flow and fuel pressure before "
            "bending the map.", n=len(extreme), pct=max_step * 100))

    lean_big = [
        (r, c) for r in range(item.rows) for c in range(item.cols)
        if result.correction_percent(r, c) >= 10.0
    ]
    if lean_big:
        notes.append(t(
            "In {n} cells the engine ran more than 10% lean. If this is a high-load "
            "area, do not drive like this: a lean mixture under load kills pistons "
            "and the catalyst faster than knock.", n=len(lean_big)))

    noisy = [key for key, stat in result.stats.items()
             if stat.samples >= 8 and stat.spread > 0.05]
    if noisy:
        notes.append(t(
            "In {n} cells the correction spread is large — the data there is "
            "contradictory. Usually transients, a cold engine or an unaccounted "
            "sensor delay (try --delay 2…6).", n=len(noisy)))

    if columns.coolant is None:
        notes.append(t(
            "No coolant temperature channel in the log — cold-engine samples were "
            "not filtered out. Warm-up distorts the mixture, the result may drift."))
    if columns.target is None:
        notes.append(t(
            "No target lambda in the log, the --target value is used. At full load "
            "the ECU targets enrichment (usually 0.85…0.90), and with a target of "
            "1.0 the program would suggest leaning the engine where enrichment is "
            "intentional."))
    return notes


def _smooth(factor: List[List[float]], stats: Dict[Tuple[int, int], CellStat],
            min_samples: int) -> List[List[float]]:
    """Light 3×3 smoothing over cells that have data.

    Cells without data neither take part nor change: smearing the correction
    over areas the car never visited is a sure way to get a flat spot.
    """
    rows, cols = len(factor), len(factor[0])
    out = [row[:] for row in factor]
    for r in range(rows):
        for c in range(cols):
            stat = stats.get((r, c))
            if not stat or stat.samples < min_samples:
                continue
            total = 0.0
            weight = 0.0
            for dr in (-1, 0, 1):
                for dc in (-1, 0, 1):
                    rr, cc = r + dr, c + dc
                    if not (0 <= rr < rows and 0 <= cc < cols):
                        continue
                    neighbour = stats.get((rr, cc))
                    if not neighbour or neighbour.samples < min_samples:
                        continue
                    w = 4.0 if (dr == 0 and dc == 0) else 1.0
                    total += factor[rr][cc] * w
                    weight += w
            if weight:
                out[r][c] = total / weight
    return out


# ---------------------------------------------------------------------------
# Writing the result
# ---------------------------------------------------------------------------


def write_tuned_bin(reader: Reader, item: Item, result: TuneResult,
                    out_path: str) -> Dict:
    """Write the new map to a NEW .bin. The source file is not touched."""
    from .crossdiff import phys_to_raw

    data = bytearray(reader.bin.data)
    base = reader.item_offset(item)
    d = item.data
    if base is None or d is None:
        raise LogError(t("The map has no address in this file"))

    order = "little" if d.lsb_first else "big"
    cols = max(1, d.colcount)
    written = 0
    clipped = 0
    for r in range(item.rows):
        for c in range(item.cols):
            value = result.new[r][c]
            raw, reason = phys_to_raw(item, value)
            if raw is None:
                clipped += 1
                continue
            idx = r * cols + c
            rr, cc = divmod(idx, cols)
            off = base + rr * d.row_stride + cc * d.col_stride
            if off < 0 or off + d.elem_bytes > len(data):
                continue
            data[off:off + d.elem_bytes] = int(raw).to_bytes(
                d.elem_bytes, order, signed=d.signed)
            written += 1

    with open(out_path, "wb") as fh:
        fh.write(data)
    return {"path": out_path, "cells": written, "clipped": clipped,
            "size": len(data)}
