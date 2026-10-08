# -*- coding: utf-8 -*-
"""
TunerPro data logs (CSV) for the window and the MCP tools — plain Python, no pandas.

A log lives in the project's logs/ folder together with a small binding file
(<log>.ms43log.json) that says which firmware was in the car when it was
recorded. The binding is required: a log only says something about the
firmware it was recorded on, so the map overlay reads exactly that firmware
(checked by its SHA-1) and an edit of another firmware citing the log is a
red flag in the Edits screen.

TunerPro writes a title line, then the header (first column = row number,
then "Time"), then a units row ("Sample #, Seconds, ...(°C)"), then the rows,
each with a trailing comma. Flags are ON/OFF. On MS43 a NEGATIVE knock
correction means ignition was pulled; the ECU then restores it slowly, so a
row with retard is not necessarily a row where knock was detected. Detected
knock ("onset") is where a cylinder's correction becomes more negative.
"""

from __future__ import annotations

import csv
import datetime as _dt
import hashlib
import io
import json
import math
import os
import shutil
import struct
from array import array
from typing import Any, Dict, List, Optional, Sequence, Tuple

from .i18n import t

NAN = float("nan")
BINDING_SUFFIX = ".ms43log.json"
KNOCK_PREFIX = "Knock Correction Cyl"
TIME = "Time"
RPM = "Engine Speed"
LOAD_IGN = "Engine Load Ignition"
LOAD_MAF = "Engine Load MAF"
COOLANT = "Coolant Temperature"
THROTTLE = ("Throttle Body Position", "Accelerator Pedal Position")
OVERRUN = "Trailing Throttle Fuel Cut"
FLAGS = ("Engine Misfire", "Engine Misfire Cylinder Cut", "VANOS Limp Home", "Flex Fuel Limp Home",
         "Over Boost Protection", "Engine Overheating Light", "Check Engine Light",
         "Engine Malfunction Light", "Torque Intervention AMT", "Torque Intervention ASR",
         "Torque Intervention Gear", "Torque Intervention Limit", "Torque Intervention MSR",
         "Trailing Throttle Fuel Cut")
# Flags that are normal driving, not a fault (still listed, never alarming).
FLAGS_NORMAL = ("Trailing Throttle Fuel Cut", "Torque Intervention Gear")

# Signals that move all the time while driving; constant = suspicious.
FAST_CHANNELS = (RPM, "Engine Load", "Throttle Body Position", "Accelerator Pedal Position",
                 "Mass Air Flow", "Injection Time", "Ignition Angle", "Vehicle Speed",
                 "VANOS Angle", "Short Term Fuel Trim", "Fuel Injector Duty Cycle")

WARM_COOLANT = 80.0          # °C: below this the engine is not warm
STEADY_RATE = 40.0           # %/s: faster throttle movement is a transient
ONSET_STEP = 0.1             # ° deeper than the previous row = knock detected

# Map axis tokens (from the object name, "ip_iga_...__n__maf") -> log channel.
AXIS_CHANNELS = {
    "n": (RPM,), "n_32": (RPM,), "n_vim": (RPM,),
    "maf": (LOAD_IGN, LOAD_MAF), "maf_iv": (LOAD_MAF, LOAD_IGN), "rf": (LOAD_MAF, LOAD_IGN),
    "tco": (COOLANT,), "tia": ("Intake Air Temperature",), "toil": ("Oil Temperature",),
    "vs": ("Vehicle Speed",), "pvs": ("Accelerator Pedal Position",),
    "tps": ("Throttle Body Position",), "map": ("Manifold Pressure", "Intake Manifold Pressure"),
}


class LogError(ValueError):
    """A log that cannot be used; the text is shown as is."""


# ---------------------------------------------------------------------------
# Reading
# ---------------------------------------------------------------------------

class Log:
    """Columns of numbers (NaN where empty); ON/OFF become 1/0."""

    def __init__(self, path: str):
        self.path = os.path.abspath(path)
        self.name = os.path.basename(path)
        self.title = ""
        self.columns: List[str] = []
        self.units: Dict[str, str] = {}
        self.data: Dict[str, array] = {}
        self.skipped: List[str] = []         # text columns that are not numbers
        self.n = 0
        self._read()

    def _read(self) -> None:
        with open(self.path, "rb") as fh:
            raw = fh.read()
        text = None
        for enc in ("utf-8-sig", "cp1251"):
            try:
                text = raw.decode(enc)
                break
            except UnicodeDecodeError:
                continue
        if text is None:
            text = raw.decode("latin-1")
        lines = text.splitlines()
        start = 0
        while start < len(lines) and "," not in lines[start] and ";" not in lines[start]:
            start += 1
        if start:
            self.title = lines[0].strip()
        if start >= len(lines):
            raise LogError(t("This does not look like a TunerPro log (no header line)."))
        delim = ";" if lines[start].count(";") > lines[start].count(",") else ","
        reader = csv.reader(io.StringIO("\n".join(lines[start:])), delimiter=delim)
        header = [h.strip() for h in next(reader)]
        rows = [r for r in reader if any(cell.strip() for cell in r)]
        if rows and rows[0] and rows[0][0].strip().lower().startswith("sample"):
            for name, cell in zip(header, rows[0]):
                cell = cell.strip()
                if cell.endswith(")") and "(" in cell:
                    self.units[name] = cell[cell.rfind("(") + 1:-1]
                elif name == TIME and cell.lower().startswith("second"):
                    self.units[name] = "s"
            rows = rows[1:]
        keep = [i for i, h in enumerate(header) if h and not (i == 0 and h.lower() in ("", "sample #"))]
        cols: Dict[str, List[float]] = {}
        for i in keep:
            name = header[i]
            if name in cols:
                continue
            values: List[float] = []
            bad = 0
            for r in rows:
                cell = r[i].strip() if i < len(r) else ""
                if not cell:
                    values.append(NAN)
                    continue
                up = cell.upper()
                if up == "ON":
                    values.append(1.0)
                elif up == "OFF":
                    values.append(0.0)
                else:
                    try:
                        values.append(float(cell.replace(",", ".") if delim == ";" else cell))
                    except ValueError:
                        values.append(NAN)
                        bad += 1
            if rows and bad > 0.1 * len(rows):
                self.skipped.append(name)
                continue
            cols[name] = values
        if not cols:
            raise LogError(t("No numeric channels in this log."))
        self.columns = list(cols)
        self.data = {k: array("d", v) for k, v in cols.items()}
        self.n = len(rows)
        if TIME not in self.data:
            self.data[TIME] = array("d", (i * 0.05 for i in range(self.n)))
            self.columns.insert(0, TIME)

    def col(self, name: str) -> Optional[array]:
        return self.data.get(name)

    def has(self, name: str) -> bool:
        return name in self.data

    def find(self, name: str) -> Optional[str]:
        """A channel by exact or case-insensitive name."""
        if name in self.data:
            return name
        low = name.strip().lower()
        for col in self.columns:
            if col.lower() == low:
                return col
        return None

    @property
    def time(self) -> array:
        return self.data[TIME]


_CACHE: Dict[str, Tuple[float, Log]] = {}


def load(path: str) -> Log:
    stamp = os.path.getmtime(path)
    key = os.path.abspath(path)
    hit = _CACHE.get(key)
    if hit and hit[0] == stamp:
        return hit[1]
    log = Log(path)
    _CACHE[key] = (stamp, log)
    return log


def _ok(v: float) -> bool:
    return not math.isnan(v)


def fmt(v: float, nd: int = 2) -> str:
    if not _ok(v):
        return ""
    text = f"{v:.{nd}f}"
    if nd > 0:
        text = text.rstrip("0").rstrip(".")
    return "0" if text in ("-0", "") else text


# ---------------------------------------------------------------------------
# Knock, flags, quality
# ---------------------------------------------------------------------------

def knock_columns(log: Log) -> List[str]:
    return [c for c in log.columns if c.startswith(KNOCK_PREFIX)]


def cylinder(col: str) -> str:
    return col.rsplit(" ", 1)[-1]


def knock_rows(log: Log) -> Tuple[List[bool], List[bool]]:
    """(retard active, knock detected) per row."""
    cols = [log.data[c] for c in knock_columns(log)]
    retard = [False] * log.n
    onset = [False] * log.n
    for data in cols:
        prev = 0.0
        for i in range(log.n):
            v = data[i]
            if not _ok(v):
                continue
            if v < 0:
                retard[i] = True
                if v < prev - ONSET_STEP + 1e-9:
                    onset[i] = True
            prev = v
    return retard, onset


def knock_events(log: Log, gap: int = 2) -> List[Dict[str, Any]]:
    """Rows with retard grouped into events (up to `gap` clean rows inside)."""
    retard, onset = knock_rows(log)
    groups: List[List[int]] = []
    for i, on in enumerate(retard):
        if not on:
            continue
        if groups and i - groups[-1][-1] <= gap + 1:
            groups[-1].append(i)
        else:
            groups.append([i])
    tm = log.time
    out = []
    for g in groups:
        a, b = g[0], g[-1]
        ev: Dict[str, Any] = {"start": tm[a], "end": tm[b], "row_from": a, "row_to": b,
                              "rows": len(g), "detections": sum(onset[a:b + 1])}
        for name, key in ((RPM, "rpm"), (LOAD_IGN, "load_ign"), (THROTTLE[0], "throttle"),
                          ("Intake Air Temperature", "iat"), (COOLANT, "coolant")):
            col = log.col(name)
            if col is not None:
                vals = [col[i] for i in range(a, b + 1) if _ok(col[i])]
                if vals:
                    ev[key] = (min(vals), max(vals))
        worst: Dict[str, float] = {}
        for c in knock_columns(log):
            data = log.data[c]
            deepest = min((data[i] for i in range(a, b + 1) if _ok(data[i])), default=0.0)
            if deepest < 0:
                worst[cylinder(c)] = deepest
        ev["cylinders"] = worst
        out.append(ev)
    return out


def flag_summary(log: Log) -> List[Dict[str, Any]]:
    """Flags that were ON at least once: rows and first time."""
    out = []
    for name in FLAGS:
        col = log.col(name)
        if col is None:
            continue
        rows = [i for i in range(log.n) if _ok(col[i]) and col[i] > 0]
        if rows:
            out.append({"flag": name, "rows": len(rows), "first": log.time[rows[0]],
                        "normal": name in FLAGS_NORMAL})
    return out


def quality(log: Log) -> Dict[str, Any]:
    """Duration, sample rate, gaps in time, channels that never change."""
    tm = [v for v in log.time if _ok(v)]
    dur = (tm[-1] - tm[0]) if len(tm) > 1 else 0.0
    steps = sorted(b - a for a, b in zip(tm, tm[1:]) if b > a)
    median = steps[len(steps) // 2] if steps else 0.0
    gaps = []
    if median:
        for i in range(1, len(tm)):
            if tm[i] - tm[i - 1] > max(5 * median, 0.5):
                gaps.append((tm[i - 1], tm[i]))
    stuck, constant, empty = [], [], []
    for c in log.columns:
        if c == TIME:
            continue
        vals = {v for v in log.data[c] if _ok(v)}
        if not vals:
            empty.append(c)              # no value in any row: decoding or logging problem
            continue
        if c.startswith(KNOCK_PREFIX) or c in FLAGS:
            continue                     # all zero / all OFF is normal for these
        if len(vals) <= 1:
            # a fast signal that never moves while the engine runs is a logging or
            # sensor problem; slow or unused ones (temperatures, trims, switches) are not
            (stuck if any(c.startswith(f) for f in FAST_CHANNELS) else constant).append(c)
    return {"rows": log.n, "duration": dur, "rate": (len(tm) - 1) / dur if dur else 0.0,
            "median_step": median, "gaps": gaps, "stuck": stuck, "constant": constant,
            "empty": empty,
            "skipped": list(log.skipped)}


# ---------------------------------------------------------------------------
# Filters: which rows are fair evidence
# ---------------------------------------------------------------------------

FILTERS = ("warm", "steady", "no_overrun", "closed_loop")
LAMBDA_CONTROL = "Lambda Control"     # "Lambda Control 1/2": closed loop on (ON) / off


def _throttle(log: Log) -> Optional[str]:
    for name in THROTTLE:
        if log.has(name):
            return name
    return None


def row_filter(log: Log, filters: Sequence[str]) -> Tuple[List[bool], Dict[str, Any]]:
    """Rows kept by the filters and, per filter, how many it dropped (or why it could not run)."""
    keep = [True] * log.n
    stats: Dict[str, Any] = {}
    tm = log.time
    for name in filters:
        dropped = 0
        if name == "warm":
            col = log.col(COOLANT)
            if col is None:
                stats[name] = t("no channel {name}", name=COOLANT)
                continue
            for i in range(log.n):
                if keep[i] and not (_ok(col[i]) and col[i] >= WARM_COOLANT):
                    keep[i] = False
                    dropped += 1
        elif name == "steady":
            ch = _throttle(log)
            if ch is None:
                stats[name] = t("no throttle channel")
                continue
            col = log.data[ch]
            for i in range(log.n):
                lo, hi = max(0, i - 2), min(log.n - 1, i + 2)
                span = tm[hi] - tm[lo]
                if span <= 0 or not (_ok(col[hi]) and _ok(col[lo])):
                    continue
                if abs(col[hi] - col[lo]) / span > STEADY_RATE and keep[i]:
                    keep[i] = False
                    dropped += 1
        elif name == "no_overrun":
            col = log.col(OVERRUN)
            if col is None:
                stats[name] = t("no channel {name}", name=OVERRUN)
                continue
            for i in range(log.n):
                if keep[i] and _ok(col[i]) and col[i] > 0:
                    keep[i] = False
                    dropped += 1
        elif name == "closed_loop":
            cols = [log.data[c] for c in log.columns if c.startswith(LAMBDA_CONTROL)]
            if not cols:
                stats[name] = t("no channel {name}", name=LAMBDA_CONTROL + " 1/2")
                continue
            for i in range(log.n):
                if keep[i] and not any(_ok(c[i]) and c[i] > 0 for c in cols):
                    keep[i] = False
                    dropped += 1
        else:
            raise LogError(t("Unknown filter: {name}", name=name))
        stats[name] = dropped
    return keep, stats


# ---------------------------------------------------------------------------
# A log over a firmware map
# ---------------------------------------------------------------------------

def axis_tokens(title: str) -> Tuple[str, str]:
    """(row token, column token) from an object name like ip_iga_...__n__maf."""
    parts = [p for p in (title or "").split("__")[1:] if p]
    if not parts:
        return "", ""
    if len(parts) == 1:
        return parts[0], ""
    return parts[-2], parts[-1]


def trim_channels(log: Log) -> List[str]:
    """Fuel trim channels (what the "average per cell" view is mostly for)."""
    return [c for c in log.columns if "Fuel Trim" in c or "Lambda Integrator" in c]


def guess_channels(log: Log, title: str, y_units: str = "", x_units: str = "") -> Tuple[str, str]:
    """Log channels for the map's row and column axes (empty when unknown)."""
    out = []
    for token, units in zip(axis_tokens(title), (y_units, x_units)):
        found = ""
        for name in AXIS_CHANNELS.get(token, ()):
            if log.has(name):
                found = name
                break
        if not found and units:
            same = [c for c in log.columns if log.units.get(c, "").lower() == units.lower()]
            found = same[0] if len(same) == 1 else ""
        out.append(found)
    return out[0], out[1]


def _nearest(breaks: Sequence[float], v: float) -> Tuple[int, bool]:
    """Index of the nearest breakpoint and whether v was outside the axis."""
    lo, hi = min(breaks), max(breaks)
    outside = v < lo or v > hi
    best, dist = 0, float("inf")
    for k, b in enumerate(breaks):
        d = abs(b - v)
        if d < dist:
            best, dist = k, d
    return best, outside


def map_hits(log: Log, y_breaks: Optional[Sequence[float]], x_breaks: Optional[Sequence[float]],
             y_channel: str, x_channel: str, keep: Optional[List[bool]] = None,
             value_channel: str = "") -> Dict[str, Any]:
    """Per map cell: rows that sat there, knock detections, deepest retard, cylinders,
    and (with value_channel, e.g. a fuel trim) the mean, min and max of that channel.

    A row goes to the nearest breakpoint on each axis (the ECU interpolates
    between neighbours, so a row also influences the cells around it).
    """
    rows = len(y_breaks) if y_breaks else 1
    cols = len(x_breaks) if x_breaks else 1
    ycol = log.col(y_channel) if y_breaks else None
    xcol = log.col(x_channel) if x_breaks else None
    if y_breaks and ycol is None:
        raise LogError(t("The log has no channel \"{name}\".", name=y_channel))
    if x_breaks and xcol is None:
        raise LogError(t("The log has no channel \"{name}\".", name=x_channel))
    vcol = log.col(value_channel) if value_channel else None
    if value_channel and vcol is None:
        raise LogError(t("The log has no channel \"{name}\".", name=value_channel))
    retard, onset = knock_rows(log)
    kcols = [(cylinder(c), log.data[c]) for c in knock_columns(log)]
    grid = [[{"n": 0, "knock": 0, "retard": 0, "worst": 0.0, "cyl": set(), "t": [],
              "vn": 0, "vsum": 0.0, "vmin": NAN, "vmax": NAN}
             for _ in range(cols)] for _ in range(rows)]
    used = outside = 0
    for i in range(log.n):
        if keep is not None and not keep[i]:
            continue
        r = c = 0
        out = False
        if ycol is not None:
            if not _ok(ycol[i]):
                continue
            r, o = _nearest(y_breaks, ycol[i])
            out |= o
        if xcol is not None:
            if not _ok(xcol[i]):
                continue
            c, o = _nearest(x_breaks, xcol[i])
            out |= o
        used += 1
        outside += out
        cell = grid[r][c]
        cell["n"] += 1
        if vcol is not None and _ok(vcol[i]):
            v = vcol[i]
            cell["vn"] += 1
            cell["vsum"] += v
            cell["vmin"] = v if not _ok(cell["vmin"]) else min(cell["vmin"], v)
            cell["vmax"] = v if not _ok(cell["vmax"]) else max(cell["vmax"], v)
        if retard[i]:
            cell["retard"] += 1
            for cyl, data in kcols:
                v = data[i]
                if _ok(v) and v < 0:
                    cell["worst"] = min(cell["worst"], v)
                    if onset[i]:
                        cell["cyl"].add(cyl)
        if onset[i]:
            cell["knock"] += 1
            if len(cell["t"]) < 5:
                cell["t"].append(round(log.time[i], 2))
    for line in grid:
        for cell in line:
            cell["cyl"] = sorted(cell["cyl"])
            cell["mean"] = cell["vsum"] / cell["vn"] if cell["vn"] else NAN
    return {"grid": grid, "rows_used": used, "outside": outside, "value_channel": value_channel}


# ---------------------------------------------------------------------------
# Binding a log to the firmware it was recorded on
# ---------------------------------------------------------------------------

def sha1_file(path: str) -> str:
    h = hashlib.sha1()
    with open(path, "rb") as fh:
        for block in iter(lambda: fh.read(1 << 16), b""):
            h.update(block)
    return h.hexdigest()


def binding_path(log_path: str) -> str:
    return log_path + BINDING_SUFFIX


def read_binding(log_path: str) -> Optional[Dict[str, Any]]:
    try:
        with open(binding_path(log_path), encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) and data.get("bin_sha1") else None


CONDITION_KEYS = ("where", "fuel", "air_temp", "complaint", "changed")
WHERE = ("public_road", "closed_road", "track", "dyno")


def conditions(binding: Optional[Dict[str, Any]]) -> Dict[str, str]:
    """The owner's structured note of a log: where, fuel, air temperature, the complaint,
    what changed since the previous log, free text ("note")."""
    b = binding or {}
    c = b.get("conditions") if isinstance(b.get("conditions"), dict) else {}
    out = {k: str(c.get(k) or "").strip()[:300] for k in CONDITION_KEYS}
    if out["where"] not in WHERE:
        out["where"] = ""
    out["note"] = str(b.get("note") or "").strip()[:500]
    return out


def missing_conditions(binding: Optional[Dict[str, Any]]) -> List[str]:
    c = conditions(binding)
    return [k for k in ("where", "fuel", "complaint", "changed") if not c[k]]


def set_conditions(log_path: str, data: Dict[str, Any]) -> Dict[str, str]:
    """Edit the note of a bound log (any time after it was added)."""
    binding = read_binding(log_path)
    if binding is None:
        raise LogError(t("This log has no binding to a firmware; add it again on the Logs screen."))
    c = conditions({"conditions": data, "note": data.get("note", "")})
    binding["conditions"] = {k: c[k] for k in CONDITION_KEYS}
    binding["note"] = c["note"]
    with open(binding_path(log_path), "w", encoding="utf-8") as fh:
        json.dump(binding, fh, ensure_ascii=False, indent=1)
    return c


def binding_status(binding: Optional[Dict[str, Any]]) -> str:
    """"" when the bound firmware is there unchanged, otherwise why not."""
    if not binding:
        return t("not bound to a firmware")
    path = binding.get("bin", "")
    if not path or not os.path.isfile(path):
        return t("the bound firmware file is missing: {path}", path=path)
    if sha1_file(path) != binding.get("bin_sha1"):
        return t("the bound firmware file has changed since the log was added")
    xdf = binding.get("xdf", "")
    if not xdf or not os.path.isfile(xdf):
        return t("the XDF of the bound firmware is missing: {path}", path=xdf)
    return ""


def _free_path(folder: str, base: str, ext: str, src: str = "") -> str:
    dest = os.path.join(folder, base + ext)
    k = 2
    while os.path.exists(dest) and os.path.abspath(dest) != os.path.abspath(src):
        dest = os.path.join(folder, f"{base}_{k}{ext}")
        k += 1
    return dest


def add_log(src: str, logs_dir: str, bin_path: str, xdf_path: str, note: str = "",
            adx_path: str = "") -> str:
    """Copy a log into the project and bind it. Returns the path of the CSV.

    A TunerPro .xdl (raw packets) is decoded with its ADX into a CSV in
    TunerPro's export layout; the .xdl itself is kept in logs/raw/ so it can
    be decoded again (e.g. with a corrected ADX).
    """
    if not os.path.isfile(bin_path):
        raise LogError(t("Choose the firmware that was in the car."))
    if not os.path.isfile(xdf_path):
        raise LogError(t("Choose the XDF for that firmware."))
    os.makedirs(logs_dir, exist_ok=True)
    base, ext = os.path.splitext(os.path.basename(src))
    extra: Dict[str, Any] = {}
    if ext.lower() == ".xdl":
        from . import adx

        if not adx_path or not os.path.isfile(adx_path):
            raise LogError(t("A TunerPro .xdl log needs the ADX it was recorded with."))
        dest = _free_path(logs_dir, base, ".csv")
        raw_dir = os.path.join(logs_dir, "raw")
        os.makedirs(raw_dir, exist_ok=True)
        raw = _free_path(raw_dir, os.path.splitext(os.path.basename(dest))[0], ".xdl")
        try:
            info = adx.xdl_to_csv(src, adx_path, dest)
        except (adx.AdxError, OSError, struct.error) as exc:
            raise LogError(str(exc)) from exc
        shutil.copyfile(src, raw)
        load(dest)
        extra = {"adx": os.path.abspath(adx_path), "raw": os.path.relpath(raw, logs_dir),
                 "decoder": adx.DECODER_VERSION,
                 "decoded_rows": info["rows"], "bad_packets": info["bad_packets"]}
    else:
        load(src)                                     # refuse a file that is not a log
        dest = _free_path(logs_dir, base, ext or ".csv", src)
        if os.path.abspath(dest) != os.path.abspath(src):
            shutil.copyfile(src, dest)
    bind(dest, bin_path, xdf_path, note, {"source": os.path.abspath(src), **extra})
    return dest


def bind(log_path: str, bin_path: str, xdf_path: str, note: str = "",
         extra: Optional[Dict[str, Any]] = None) -> None:
    """Write the binding of a log to the firmware that was in the car."""
    binding = {"bin": os.path.abspath(bin_path), "bin_sha1": sha1_file(bin_path),
               "xdf": os.path.abspath(xdf_path),
               "added": _dt.datetime.now().strftime("%Y-%m-%d %H:%M"), "note": note,
               **(extra or {})}
    with open(binding_path(log_path), "w", encoding="utf-8") as fh:
        json.dump(binding, fh, ensure_ascii=False, indent=1)


def redecode_status(log_path: str) -> str:
    """"" when the log is current; "old" when an older decoder made it and the raw file
    is there to decode it again."""
    from .adx import DECODER_VERSION

    binding = read_binding(log_path) or {}
    raw = binding.get("raw")
    if not raw or not binding.get("adx"):
        return ""
    if binding.get("decoder", 1) >= DECODER_VERSION:
        return ""
    raw_path = os.path.join(os.path.dirname(log_path), raw)
    return "old" if os.path.isfile(raw_path) else ""


def redecode(log_path: str, adx_path: str = "") -> Dict[str, Any]:
    """Decode a log again from its raw file (.xdl or the logger's .jsonl)."""
    from . import adx as adxmod

    binding = read_binding(log_path)
    if not binding or not binding.get("raw"):
        raise LogError(t("This log has no raw file to decode again."))
    raw_path = os.path.join(os.path.dirname(log_path), binding["raw"])
    adx_path = adx_path or binding.get("adx", "")
    if not os.path.isfile(raw_path):
        raise LogError(t("The raw file is missing: {path}", path=raw_path))
    if not os.path.isfile(adx_path):
        raise LogError(t("The ADX is missing: {path}", path=adx_path))
    try:
        if raw_path.lower().endswith(".jsonl"):
            info = adxmod.jsonl_to_csv(raw_path, adx_path, log_path)
        else:
            info = adxmod.xdl_to_csv(raw_path, adx_path, log_path)
    except (adxmod.AdxError, OSError, struct.error) as exc:
        raise LogError(str(exc)) from exc
    binding.update(adx=os.path.abspath(adx_path), decoder=adxmod.DECODER_VERSION,
                   decoded_rows=info["rows"],
                   redecoded=_dt.datetime.now().strftime("%Y-%m-%d %H:%M"))
    with open(binding_path(log_path), "w", encoding="utf-8") as fh:
        json.dump(binding, fh, ensure_ascii=False, indent=1)
    _CACHE.pop(os.path.abspath(log_path), None)
    return info


def list_logs(logs_dir: str) -> List[str]:
    if not logs_dir or not os.path.isdir(logs_dir):
        return []
    return sorted(os.path.join(logs_dir, f) for f in os.listdir(logs_dir)
                  if f.lower().endswith(".csv"))


def resolve(logs_dir: str, name: str) -> str:
    """A log in the project by its file name (no paths from outside)."""
    name = os.path.basename((name or "").strip())
    path = os.path.join(logs_dir, name)
    if not name or not os.path.isfile(path):
        names = ", ".join(os.path.basename(p) for p in list_logs(logs_dir)) or "—"
        raise LogError(t("No log \"{name}\" in the project. Logs: {names}", name=name, names=names))
    return path


# ---------------------------------------------------------------------------
# Fuel trims, update rates, implausible values (for log_info)
# ---------------------------------------------------------------------------

STFT = "Short Term Fuel Trim Bank {b}"
LTFT_MUL = "Long Term Fuel Trim Multiplicative Bank {b}"
LTFT_ADD = "Long Term Fuel Trim Additive Bank {b}"
INJ = "Injection Time Bank {b}"
MAF = "Mass Air Flow"
MAF_BANDS = ((0, 30), (30, 60), (60, 120), (120, 250), (250, 10_000))


def _segments(log: Log, mask: List[bool], min_s: float = 0.5) -> List[Tuple[float, float]]:
    out, start = [], None
    tm = log.time
    for i, on in enumerate(mask + [False]):
        if on and start is None:
            start = i
        elif not on and start is not None:
            a, b = tm[start], tm[i - 1]
            if b - a >= min_s:
                out.append((a, b))
            start = None
    return out


def _closed(log: Log, bank: int) -> List[bool]:
    col = log.col(f"{LAMBDA_CONTROL} {bank}") or log.col(f"{LAMBDA_CONTROL} 1")
    if col is None:
        return [True] * log.n
    return [_ok(v) and v > 0 for v in col]


def trim_report(log: Log, limits: Optional[Tuple[float, float]] = None) -> Dict[str, Any]:
    """Short-term trims at their limits, bank difference at idle, by airflow, long-term trims.

    `limits` = (min, max) from the firmware (c_lam_min / c_lam_max); a trim within half a
    percent of a limit counts as pinned there (the log shows e.g. 27.73 for 28 %).
    """
    out: Dict[str, Any] = {"banks": {}, "limits": limits}
    for b in (1, 2):
        col = log.col(STFT.format(b=b))
        if col is None:
            continue
        closed = _closed(log, b)
        vals = [col[i] for i in range(log.n) if closed[i] and _ok(col[i])]
        bank: Dict[str, Any] = {"closed_rows": len(vals)}
        if vals:
            lo, hi = (limits if limits else (min(vals), max(vals)))
            top = [closed[i] and _ok(col[i]) and col[i] >= hi - 0.5 for i in range(log.n)]
            bottom = [closed[i] and _ok(col[i]) and col[i] <= lo + 0.5 for i in range(log.n)]
            n = len(vals)
            bank.update(mean=sum(vals) / n, min=min(vals), max=max(vals),
                        at_max=sum(top) / n, at_min=sum(bottom) / n,
                        max_segments=_segments(log, top), min_segments=_segments(log, bottom))
        for name, key in ((LTFT_MUL, "ltft_mul"), (LTFT_ADD, "ltft_add")):
            lt = log.col(name.format(b=b))
            if lt is not None:
                seq = [v for v in lt if _ok(v)]
                if seq:
                    bank[key] = (seq[0], seq[-1])
        out["banks"][b] = bank
    s1, s2 = log.col(STFT.format(b=1)), log.col(STFT.format(b=2))
    if s1 is not None and s2 is not None:
        c1, c2 = _closed(log, 1), _closed(log, 2)
        idle = log.col("Idle")
        speed = log.col("Vehicle Speed")
        rows = [i for i in range(log.n) if c1[i] and c2[i] and _ok(s1[i]) and _ok(s2[i])
                and ((idle is not None and _ok(idle[i]) and idle[i] > 0)
                     or (idle is None and speed is not None and _ok(speed[i]) and speed[i] == 0))]
        if rows:
            idle_info: Dict[str, Any] = {"rows": len(rows),
                                         "stft": (sum(s1[i] for i in rows) / len(rows),
                                                  sum(s2[i] for i in rows) / len(rows))}
            i1, i2 = log.col(INJ.format(b=1)), log.col(INJ.format(b=2))
            if i1 is not None and i2 is not None:
                ok = [i for i in rows if _ok(i1[i]) and _ok(i2[i])]
                if ok:
                    idle_info["inj"] = (sum(i1[i] for i in ok) / len(ok), sum(i2[i] for i in ok) / len(ok))
            out["idle"] = idle_info
        maf = log.col(MAF)
        if maf is not None:
            bands = []
            for lo, hi in MAF_BANDS:
                rows = [i for i in range(log.n) if c1[i] and c2[i] and _ok(maf[i]) and lo <= maf[i] < hi
                        and _ok(s1[i]) and _ok(s2[i])]
                if len(rows) >= 10:
                    bands.append({"band": (lo, hi), "rows": len(rows),
                                  "stft": (sum(s1[i] for i in rows) / len(rows),
                                           sum(s2[i] for i in rows) / len(rows))})
            out["maf_bands"] = bands
    return out


def update_periods(log: Log, min_changes: int = 3) -> List[Dict[str, Any]]:
    """Channels whose value changes much less often than the rows come (e.g. the vehicle
    speed once per second at 20 Hz): typical seconds between changes, distinct values."""
    tm = log.time
    q = quality(log)
    step = q["median_step"] or 0.05
    out = []
    for c in log.columns:
        if c == TIME:
            continue
        col = log.data[c]
        changes = []
        prev = None
        for i in range(log.n):
            v = col[i]
            if not _ok(v):
                continue
            if prev is not None and v != prev:
                changes.append(tm[i])
            prev = v
        if len(changes) < min_changes:
            continue
        gaps = sorted(b - a for a, b in zip(changes, changes[1:]))
        if not gaps:
            continue
        median = gaps[len(gaps) // 2]
        distinct = len({v for v in col if _ok(v)})
        if median >= max(0.4, 5 * step) and distinct >= 5:     # switches change rarely anyway
            out.append({"channel": c, "period": median, "distinct": distinct})
    return out


# Limits an atmospheric M5x cannot exceed: above them a value is a sensor or logging artefact.
PLAUSIBLE = {MAF: 800.0, "Engine Load MAF": 900.0, LOAD_IGN: 900.0, "Engine Load Injection": 900.0,
             RPM: 7800.0, "Intake Air Temperature": 110.0, COOLANT: 130.0}


def implausible(log: Log) -> List[Dict[str, Any]]:
    """Rows above the plausible limits and single-row spikes on the load channels."""
    out = []
    tm = log.time
    for name, limit in PLAUSIBLE.items():
        col = log.col(name)
        if col is None:
            continue
        rows = [i for i in range(log.n) if _ok(col[i]) and col[i] > limit]
        spikes = []
        if name != COOLANT and name != "Intake Air Temperature":
            for i in range(1, log.n - 1):
                a, v, b = col[i - 1], col[i], col[i + 1]
                if _ok(a) and _ok(v) and _ok(b) and v > 1.5 * max(a, b) and v - max(a, b) > 100:
                    spikes.append(i)
        if rows or spikes:
            out.append({"channel": name, "limit": limit, "units": log.units.get(name, ""),
                        "above": [(round(tm[i], 2), col[i]) for i in rows[:30]], "above_n": len(rows),
                        "spikes": [(round(tm[i], 2), col[i]) for i in spikes[:30]],
                        "spikes_n": len(spikes)})
    return out


# ---------------------------------------------------------------------------
# Driving modes: idle, full-throttle pulls, limiter, knock weighted by time
# ---------------------------------------------------------------------------

PEDAL = "Accelerator Pedal Position"
SPEED = "Vehicle Speed"


def _mean(col, rows) -> Optional[float]:
    vals = [col[i] for i in rows if _ok(col[i])]
    return sum(vals) / len(vals) if vals else None


def _rows(log: Log, a: float, b: float) -> List[int]:
    tm = log.time
    return [i for i in range(log.n) if a <= tm[i] <= b]


def idle_segments(log: Log, min_s: float = 3.0) -> List[Dict[str, Any]]:
    """Idle at a standstill: per segment rpm spread, idle actuator, ignition, trims, injection."""
    idle = log.col("Idle")
    speed, pedal = log.col(SPEED), log.col(PEDAL)
    mask = []
    for i in range(log.n):
        if idle is not None and _ok(idle[i]):
            on = idle[i] > 0
        else:
            on = pedal is not None and _ok(pedal[i]) and pedal[i] <= 1
        if speed is not None and _ok(speed[i]) and speed[i] > 0:
            on = False
        mask.append(on)
    out = []
    rpm = log.col(RPM)
    for a, b in _segments(log, mask, min_s):
        rows = _rows(log, a, b)
        seg: Dict[str, Any] = {"start": a, "end": b}
        if rpm is not None:
            vals = [rpm[i] for i in rows if _ok(rpm[i])]
            if vals:
                m = sum(vals) / len(vals)
                seg["rpm"] = (m, min(vals), max(vals),
                              math.sqrt(sum((v - m) ** 2 for v in vals) / len(vals)))
        for key, name in (("iac", "Idle Actuator PWM"), ("ign", "Ignition Angle Average"),
                          ("stft1", STFT.format(b=1)), ("stft2", STFT.format(b=2)),
                          ("inj1", INJ.format(b=1)), ("inj2", INJ.format(b=2)), ("coolant", COOLANT)):
            col = log.col(name)
            if col is not None:
                seg[key] = _mean(col, rows)
        out.append(seg)
    return out


def full_throttle_mask(log: Log) -> Tuple[List[bool], float]:
    """Rows at (nearly) full pedal: 90 % of the largest pedal value in the log."""
    pedal = log.col(PEDAL) or log.col(THROTTLE[0])
    if pedal is None:
        return [False] * log.n, 0.0
    top = max((v for v in pedal if _ok(v)), default=0.0)
    if top < 30:
        return [False] * log.n, top
    return [_ok(v) and v >= 0.9 * top for v in pedal], top


def pulls(log: Log, car: Optional[Dict[str, Any]] = None, min_s: float = 1.0) -> List[Dict[str, Any]]:
    """Full-throttle segments: rpm, the gear (from the car's ratios), rpm rate per 1000 rpm band,
    knock, and a profile by rpm band."""
    from . import car as carmod

    mask, _top = full_throttle_mask(log)
    rpm, speed = log.col(RPM), log.col(SPEED)
    tm = log.time
    retard, onset = knock_rows(log)
    kcols = [(cylinder(c), log.data[c]) for c in knock_columns(log)]
    out = []
    for a, b in _segments(log, mask, min_s):
        rows = _rows(log, a, b)
        p: Dict[str, Any] = {"start": a, "end": b, "rows": len(rows)}
        if rpm is not None:
            r = [rpm[i] for i in rows if _ok(rpm[i])]
            if r:
                p["rpm"] = (r[0], r[-1], max(r))
            # rpm rate in every 1000-rpm band crossed
            rates = []
            for lo in range(1000, 8000, 1000):
                ins = [i for i in rows if _ok(rpm[i]) and lo <= rpm[i] < lo + 1000]
                if len(ins) >= 3 and tm[ins[-1]] > tm[ins[0]]:
                    rates.append((lo, (rpm[ins[-1]] - rpm[ins[0]]) / (tm[ins[-1]] - tm[ins[0]])))
            p["rates"] = rates
        if speed is not None:
            s = [speed[i] for i in rows if _ok(speed[i])]
            if s:
                p["speed"] = (s[0], s[-1])
        if car and rpm is not None and speed is not None:
            guesses = [carmod.gear_for(rpm[i], speed[i], car) for i in rows
                       if _ok(rpm[i]) and _ok(speed[i])]
            guesses = [g for g in guesses if g]
            if guesses:
                gears = sorted(g[0] for g in guesses)
                gear = gears[len(gears) // 2]
                errs = sorted(abs(g[1]) for g in guesses if g[0] == gear)
                p["gear"] = (gear, errs[len(errs) // 2] if errs else None)
        p["knock_rows"] = sum(1 for i in rows if retard[i])
        p["detections"] = sum(1 for i in rows if onset[i])
        deepest = {}
        for cyl, col in kcols:
            d = min((col[i] for i in rows if _ok(col[i])), default=0.0)
            if d < 0:
                deepest[cyl] = d
        p["cylinders"] = deepest
        profile = []
        if rpm is not None:
            for lo in range(1000, 8000, 1000):
                ins = [i for i in rows if _ok(rpm[i]) and lo <= rpm[i] < lo + 1000]
                if not ins:
                    continue
                band: Dict[str, Any] = {"band": lo, "rows": len(ins)}
                for key, name in (("load", LOAD_IGN), ("maf", "Mass Air Flow"),
                                  ("ign", "Ignition Angle Average"), ("vanos_in", "VANOS Angle Intake"),
                                  ("vanos_ex", "VANOS Angle Exhaust"), ("iat", "Intake Air Temperature")):
                    col = log.col(name)
                    if col is not None:
                        band[key] = _mean(col, ins)
                profile.append(band)
        p["profile"] = profile
        out.append(p)
    return out


def limiter(log: Log) -> Optional[Dict[str, Any]]:
    """Rows near the highest rpm of the log (>= 5500): how long, sawtooth, injector duty."""
    rpm = log.col(RPM)
    if rpm is None:
        return None
    top = max((v for v in rpm if _ok(v)), default=0.0)
    if top < 5500:
        return None
    mask = [_ok(v) and v >= top - 200 for v in rpm]
    rows = [i for i, m in enumerate(mask) if m]
    peaks = sum(1 for i in range(1, log.n - 1)
                if mask[i] and _ok(rpm[i - 1]) and _ok(rpm[i + 1]) and rpm[i] > rpm[i - 1] and rpm[i] >= rpm[i + 1])
    duty = log.col("Fuel Injector Duty Cycle")
    return {"top": top, "rows": len(rows), "segments": _segments(log, mask, 0.0),
            "peaks": peaks, "duty_max": max((duty[i] for i in rows if _ok(duty[i])), default=None)
            if duty is not None else None}


def knock_by_mode(log: Log) -> Dict[str, Any]:
    """Share of rows with retard per cylinder: full throttle vs warm part load; detections/min."""
    full, _top = full_throttle_mask(log)
    retard, onset = knock_rows(log)
    rpm = log.col(RPM)
    coolant = log.col(COOLANT)
    step = quality(log)["median_step"] or 0.05
    out: Dict[str, Any] = {}
    for mode, sel in (("full", lambda i: full[i]),
                      ("part", lambda i: not full[i] and (rpm is None or (_ok(rpm[i]) and rpm[i] > 1200))
                       and (coolant is None or (_ok(coolant[i]) and coolant[i] >= WARM_COOLANT)))):
        rows = [i for i in range(log.n) if sel(i)]
        if not rows:
            continue
        seconds = len(rows) * step
        per_cyl = {}
        for c in knock_columns(log):
            col = log.data[c]
            n = sum(1 for i in rows if _ok(col[i]) and col[i] < 0)
            per_cyl[cylinder(c)] = n / len(rows)
        out[mode] = {"rows": len(rows), "seconds": seconds,
                     "retard_share": sum(1 for i in rows if retard[i]) / len(rows),
                     "per_cylinder": per_cyl,
                     "detections_per_min": sum(1 for i in rows if onset[i]) / (seconds / 60.0)
                     if seconds else 0.0}
    return out
