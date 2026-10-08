# -*- coding: utf-8 -*-
"""
MCP tools for TunerPro logs in the project (the "Logs" screen of the window).

Every log is bound to the firmware that was in the car when it was recorded
(tplog.add_log). The tools read the log row by row, group knock into events,
and lay the log over a map of THAT firmware, so a proposed change can cite
the exact cells. log_show opens the same view in the window for the owner.
"""

from __future__ import annotations

import os
from typing import Any, Dict, List, Optional, Sequence

from . import names, tplog
from .binfile import BinFile, Reader, format_number
from .i18n import t
from .mcpedits import WORKSPACE

DEFAULT_FILTERS = ("warm", "steady", "no_overrun")
ROWS_PER_CALL = 600
CONTEXT = (tplog.RPM, "Vehicle Speed", "Current Gear (Calculated)", "Accelerator Pedal Position",
           "Throttle Body Position", tplog.LOAD_IGN, tplog.LOAD_MAF, "Ignition Angle Average",
           "Intake Air Temperature", tplog.COOLANT)


def _ws():
    ws = WORKSPACE.get()
    if ws is None:
        raise ValueError(t("Logs work only through the live server of the open window."))
    return ws


def _logs_dir(ws) -> str:
    folder = ws.logs_dir()
    if not folder:
        raise ValueError(t("There is no project yet: the owner creates it on the AI assistant "
                           "screen of the window, then adds logs on the Logs screen."))
    return folder


def _bound(path: str):
    """(binding, problem) of a log; problem is "" when the firmware is usable."""
    binding = tplog.read_binding(path)
    return binding, tplog.binding_status(binding)


def _filters(raw: Any, value_channel: str = "") -> List[str]:
    if raw is None:
        # a fuel trim only means something while the lambda control is closed-loop
        trims = value_channel and ("Fuel Trim" in value_channel or "Lambda" in value_channel)
        return list(DEFAULT_FILTERS) + (["closed_loop"] if trims else [])
    if isinstance(raw, str):
        raw = [p.strip() for p in raw.split(",") if p.strip()]
    return [str(f) for f in raw]


def overlay(ws, log_path: str, title: str, y_channel: str = "", x_channel: str = "",
            filters: Sequence[str] = DEFAULT_FILTERS, value_channel: str = "") -> Dict[str, Any]:
    """A log over a map of the firmware it was recorded on (shared with the window)."""
    binding, problem = _bound(log_path)
    if problem:
        raise tplog.LogError(t("The log cannot be laid over a map: {why}. Bind it to the firmware "
                               "that was in the car (Logs screen).", why=problem))
    reader = Reader(ws.xdf(binding["xdf"]), BinFile(binding["bin"]))
    item = reader.xdf.by_title(title)
    if item is None:
        raise tplog.LogError(t("Parameter \"{name}\" not found in the XDF.", name=title))
    if item.cell_count <= 1:
        raise tplog.LogError(t("{name} is a single value, not a map.", name=title))
    log = tplog.load(log_path)
    y_breaks = reader.axis_values(item, "y") if item.rows > 1 else None
    x_breaks = reader.axis_values(item, "x") if item.cols > 1 else None
    if (item.rows > 1 and not y_breaks) or (item.cols > 1 and not x_breaks):
        raise tplog.LogError(t("{name} has no axis values in the XDF.", name=title))
    gy, gx = tplog.guess_channels(log, title, item.axis_y.units if item.axis_y else "",
                                  item.axis_x.units if item.axis_x else "")
    y_channel = (log.find(y_channel) if y_channel else "") or gy
    x_channel = (log.find(x_channel) if x_channel else "") or gx
    if y_breaks and not y_channel:
        raise tplog.LogError(t("Which log channel is the row axis of {name}? Give y_channel.",
                               name=title))
    if x_breaks and not x_channel:
        raise tplog.LogError(t("Which log channel is the column axis of {name}? Give x_channel.",
                               name=title))
    if value_channel:
        found = log.find(value_channel)
        if not found:
            raise tplog.LogError(t("The log has no channel \"{name}\".", name=value_channel))
        value_channel = found
    keep, stats = tplog.row_filter(log, filters)
    hits = tplog.map_hits(log, y_breaks, x_breaks, y_channel, x_channel, keep, value_channel)
    return {"log": log, "binding": binding, "reader": reader, "item": item,
            "matrix": reader.matrix(item), "y_breaks": y_breaks or [], "x_breaks": x_breaks or [],
            "y_channel": y_channel if y_breaks else "", "x_channel": x_channel if x_breaks else "",
            "filters": list(filters), "filter_stats": stats,
            "value_units": log.units.get(value_channel, "") if value_channel else "", **hits}


def compare(ws, before: str, after: str, title: str, y_channel: str = "", x_channel: str = "",
            filters: Sequence[str] = DEFAULT_FILTERS, value_channel: str = "") -> Dict[str, Any]:
    """Two logs (before / after a flash) over the same map, cell by cell."""
    a = overlay(ws, before, title, y_channel, x_channel, filters, value_channel)
    b = overlay(ws, after, title, a["y_channel"] or y_channel, a["x_channel"] or x_channel,
                filters, value_channel)
    if (a["y_breaks"], a["x_breaks"]) != (b["y_breaks"], b["x_breaks"]):
        raise tplog.LogError(t("The axes of {name} differ between the two firmware files; the "
                               "logs cannot be compared cell by cell.", name=title))
    return {"before": a, "after": b}


def _range(pair) -> str:
    lo, hi = pair
    return tplog.fmt(lo, 1) if lo == hi else f"{tplog.fmt(lo, 1)}..{tplog.fmt(hi, 1)}"


def event_lines(log: tplog.Log) -> List[str]:
    out = []
    for k, ev in enumerate(tplog.knock_events(log), 1):
        parts = [t("#{n} {start}-{end} s ({rows} rows, knock detected {det}x)", n=k,
                   start=tplog.fmt(ev["start"]), end=tplog.fmt(ev["end"]), rows=ev["rows"],
                   det=ev["detections"])]
        thr_units = log.units.get(tplog.THROTTLE[0], "")
        for key, label in (("rpm", "rpm"), ("load_ign", "load_ign"),
                           ("throttle", f"throttle {thr_units}".rstrip()),
                           ("iat", "IAT"), ("coolant", "coolant")):
            if key in ev:
                parts.append(f"{label} {_range(ev[key])}")
        cyl = ", ".join(f"cyl{c} {tplog.fmt(v)}°" for c, v in sorted(ev["cylinders"].items()))
        parts.append(t("deepest: {list}", list=cyl))
        out.append("  " + "; ".join(parts))
    return out


_WHERE_TEXT = {"public_road": "public road", "closed_road": "closed road section",
               "track": "track", "dyno": "dyno"}


def _condition_lines(binding) -> List[str]:
    c = tplog.conditions(binding)
    labels = (("where", t("Where")), ("fuel", t("Fuel")), ("air_temp", t("Air temperature")),
              ("complaint", t("What bothers the owner")),
              ("changed", t("Changed since the previous log")), ("note", t("Note")))
    out = [t("Owner's note on the conditions:")]
    for key, label in labels:
        val = _WHERE_TEXT.get(c[key], c[key]) if key == "where" else c[key]
        if val:
            out.append(f"  {label}: {val}")
    missing = tplog.missing_conditions(binding)
    if missing:
        out.append("  " + t("NOT FILLED IN: {list} — ask the owner before judging this log (they can "
                            "fill it in on the Logs screen, Conditions).",
                            list=", ".join(dict(labels)[k] for k in missing)))
    return out


# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------

def tool_log_list(args: Dict) -> str:
    ws = _ws()
    folder = _logs_dir(ws)
    paths = tplog.list_logs(folder)
    if not paths:
        root = os.path.dirname(folder)
        loose = [f for f in os.listdir(root) if f.lower().endswith((".xdl", ".csv"))] \
            if os.path.isdir(root) else []
        hint = ("\n" + t("Log files lying in the project folder are not used: {list}. Add them on "
                         "the Logs screen and say which firmware was in the car.",
                         list=", ".join(sorted(loose)[:20]))) if loose else ""
        return t("No logs in the project yet. The owner adds a TunerPro log on the Logs screen "
                 "and says which firmware was in the car.") + hint
    out = [t("Logs in {folder}:", folder=folder)]
    for path in paths:
        binding, problem = _bound(path)
        try:
            q = tplog.quality(tplog.load(path))
            info = t("{rows} rows, {dur} s, {rate} Hz", rows=q["rows"], dur=tplog.fmt(q["duration"], 1),
                     rate=tplog.fmt(q["rate"], 1))
        except (OSError, tplog.LogError) as exc:
            info = t("unreadable: {error}", error=exc)
        fw = os.path.basename(binding["bin"]) if binding else "—"
        state = t("firmware {name}", name=fw) + (f" — {problem}" if problem else "")
        if tplog.redecode_status(path) == "old":
            state += " — " + t("DECODED BY AN OLDER DECODER: ask the owner to press Decode again "
                               "on the Logs screen before trusting it")
        c = tplog.conditions(binding)
        brief = "; ".join(v for v in (_WHERE_TEXT.get(c["where"], ""), c["fuel"], c["changed"] and
                                      t("changed: {what}", what=c["changed"]), c["note"]) if v)
        miss = tplog.missing_conditions(binding) if binding else []
        state += " — " + (t("note: {text}", text=brief) if brief else t("no note"))
        if miss:
            state += " " + t("(conditions not filled in: ask before judging)")
        out.append(f"- {os.path.basename(path)}: {info}; {state}")
    return "\n".join(out)


def tool_log_info(args: Dict) -> str:
    ws = _ws()
    path = tplog.resolve(_logs_dir(ws), args.get("log", ""))
    log = tplog.load(path)
    binding, problem = _bound(path)
    q = tplog.quality(log)
    out = [t("Log {name}", name=log.name)]
    if log.title:
        out.append(log.title)
    out.append(t("Recorded on firmware: {name}", name=os.path.basename(binding["bin"]) if binding else "—")
               + (f" — {problem}" if problem else ""))
    if tplog.redecode_status(path) == "old":
        out.append(t("DECODED BY AN OLDER DECODER: ask the owner to press Decode again "
                     "on the Logs screen before trusting it"))
    out += _condition_lines(binding)
    out.append(t("{rows} rows, {dur} s, {rate} Hz (median step {step} s)", rows=q["rows"],
                 dur=tplog.fmt(q["duration"], 1), rate=tplog.fmt(q["rate"], 1),
                 step=tplog.fmt(q["median_step"], 3)))
    for a, b in q["gaps"][:20]:
        out.append(t("GAP in the recording: {a} -> {b} s", a=tplog.fmt(a), b=tplog.fmt(b)))
    if q["empty"]:
        out.append(t("EMPTY in every row (not logged or not decoded — do not use): {list}",
                     list=", ".join(q["empty"])))
    if q["stuck"]:
        out.append(t("Never change (check before trusting): {list}", list=", ".join(q["stuck"])))
    if q["constant"]:
        out.append(t("Constant in this log (normal for slow or unused signals): {list}",
                     list=", ".join(q["constant"])))
    if q["skipped"]:
        out.append(t("Text columns skipped: {list}", list=", ".join(q["skipped"])))
    events = event_lines(log)
    out.append("")
    out.append(t("Knock events (all of them, unfiltered): {n}", n=len(events)))
    out.extend(events)
    flags = tplog.flag_summary(log)
    out.append("")
    out.append(t("Flags that were ON: {n}", n=len(flags)))
    for f in flags:
        out.append("  " + t("{flag}: {rows} rows, first at {first} s", flag=f["flag"], rows=f["rows"],
                            first=tplog.fmt(f["first"])) + (t(" (normal driving)") if f["normal"] else ""))
    out += _trim_lines(log, _trim_limits(ws, binding) if not problem else None)
    slow = tplog.update_periods(log)
    if slow:
        out.append("")
        out.append(t("Channels that update much slower than the rows (values computed from them, "
                     "like acceleration or the gear from the speed, are step-wise):"))
        for d in slow:
            out.append("  " + t("{ch}: about every {s} s, {n} different values", ch=d["channel"],
                                s=tplog.fmt(d["period"], 1), n=d["distinct"]))
    odd = tplog.implausible(log)
    if odd:
        out.append("")
        out.append(t("Physically implausible values (an atmospheric M5x cannot do this — sensor or "
                     "logging artefacts; do not draw map conclusions from these rows):"))
        for d in odd:
            parts = []
            if d["above_n"]:
                parts.append(t("{n} rows above {lim}: {list}", n=d["above_n"], lim=tplog.fmt(d["limit"]),
                               list=", ".join(f"{tplog.fmt(tm)} s ({tplog.fmt(v)})" for tm, v in d["above"][:8])))
            if d["spikes_n"]:
                parts.append(t("{n} one-row spikes: {list}", n=d["spikes_n"],
                               list=", ".join(f"{tplog.fmt(tm)} s ({tplog.fmt(v)})" for tm, v in d["spikes"][:8])))
            out.append(f"  {d['channel']}: " + "; ".join(parts))
    _, stats = tplog.row_filter(log, DEFAULT_FILTERS)
    out.append("")
    out.append(t("Rows the map filters drop: {stats}", stats=", ".join(f"{k}: {v}" for k, v in stats.items())))
    out.append("")
    out.append(t("Channels ({n}):", n=len(log.columns)))
    out.append(", ".join(f"{c} [{log.units[c]}]" if log.units.get(c) else c for c in log.columns))
    return "\n".join(out)


def _trim_limits(ws, binding) -> Optional[tuple]:
    """(c_lam_min, c_lam_max) of the firmware the log was recorded on."""
    try:
        reader = Reader(ws.xdf(binding["xdf"]), BinFile(binding["bin"]))
        lo = reader.xdf.by_title("c_lam_min")
        hi = reader.xdf.by_title("c_lam_max")
        if lo is None or hi is None:
            return None
        return float(reader.values(lo)[0]), float(reader.values(hi)[0])
    except Exception:  # noqa: BLE001 - the limits are a refinement, not a requirement
        return None


def _trim_lines(log: tplog.Log, limits: Optional[tuple]) -> List[str]:
    rep = tplog.trim_report(log, limits)
    if not rep["banks"]:
        return []
    out = ["", t("Fuel trims (closed loop only; > 0 = the ECU adds fuel, the mixture was lean):")]
    out.append("  " + (t("limits from the firmware: c_lam_min {lo} %, c_lam_max {hi} %",
                         lo=tplog.fmt(limits[0], 1), hi=tplog.fmt(limits[1], 1)) if limits else
                       t("limits not read from the firmware: pinned = at the extreme seen in the log")))
    seg = lambda s: ", ".join(f"{tplog.fmt(a, 1)}-{tplog.fmt(b, 1)} s" for a, b in s[:10]) + \
        (" …" if len(s) > 10 else "")  # noqa: E731
    for b, d in sorted(rep["banks"].items()):
        if not d.get("closed_rows"):
            out.append("  " + t("bank {b}: no closed-loop rows", b=b))
            continue
        out.append("  " + t("bank {b}: STFT mean {mean} %, {lo}..{hi} %; at the upper limit {top} % of "
                            "the time, at the lower {bottom} %", b=b, mean=tplog.fmt(d["mean"], 1),
                            lo=tplog.fmt(d["min"], 1), hi=tplog.fmt(d["max"], 1),
                            top=tplog.fmt(100 * d["at_max"], 1), bottom=tplog.fmt(100 * d["at_min"], 1)))
        if d["max_segments"]:
            out.append("    " + t("PINNED at the upper limit: {list}", list=seg(d["max_segments"])))
        if d["min_segments"]:
            out.append("    " + t("PINNED at the lower limit: {list}", list=seg(d["min_segments"])))
        for key, label in (("ltft_mul", "LTFT mult. %"), ("ltft_add", "LTFT add. ms")):
            if key in d:
                out.append("    " + t("{label}: start {a}, end {b}", label=label,
                                      a=tplog.fmt(d[key][0], 2), b=tplog.fmt(d[key][1], 2)))
    if rep.get("idle"):
        i = rep["idle"]
        line = t("idle ({n} rows): STFT bank 1 {a} %, bank 2 {b} %", n=i["rows"],
                 a=tplog.fmt(i["stft"][0], 1), b=tplog.fmt(i["stft"][1], 1))
        if "inj" in i:
            line += "; " + t("injection time bank 1 {a} ms, bank 2 {b} ms", a=tplog.fmt(i["inj"][0], 2),
                             b=tplog.fmt(i["inj"][1], 2))
        out.append("  " + line)
    for band in rep.get("maf_bands", []):
        lo, hi = band["band"]
        out.append("  " + t("airflow {lo}-{hi} kg/h ({n} rows): STFT bank 1 {a} %, bank 2 {b} %",
                            lo=lo, hi=hi if hi < 10_000 else "…", n=band["rows"],
                            a=tplog.fmt(band["stft"][0], 1), b=tplog.fmt(band["stft"][1], 1)))
    return out


def tool_log_rows(args: Dict) -> str:
    ws = _ws()
    path = tplog.resolve(_logs_dir(ws), args.get("log", ""))
    log = tplog.load(path)
    wanted = args.get("channels") or []
    if isinstance(wanted, str):
        wanted = [c.strip() for c in wanted.split(",") if c.strip()]
    if wanted:
        cols, missing = [], []
        for name in wanted:
            found = log.find(name)
            (cols if found else missing).append(found or name)
        if missing:
            return t("No such channel(s): {list}. Call log_info for the channel list.",
                     list=", ".join(missing))
    else:
        cols = [c for c in CONTEXT if log.has(c)] + tplog.knock_columns(log)
    if tplog.TIME not in cols:
        cols.insert(0, tplog.TIME)
    tm = log.time
    start = float(args.get("from", tm[0] if log.n else 0))
    end = float(args.get("to", tm[-1] if log.n else 0))
    every = max(1, int(args.get("every") or 1))
    idx = [i for i in range(log.n) if start <= tm[i] <= end][::every]
    more = len(idx) > ROWS_PER_CALL
    idx = idx[:ROWS_PER_CALL]
    out = [",".join(["row"] + cols)]
    for i in idx:
        out.append(",".join([str(i)] + [tplog.fmt(log.data[c][i], 3) for c in cols]))
    if more:
        out.append(t("… limit of {n} rows reached: call again with from={next}.",
                     n=ROWS_PER_CALL, next=tplog.fmt(tm[idx[-1] + 1], 3)))
    return "\n".join(out)


def _header(ov: Dict[str, Any], what: str) -> List[str]:
    item = ov["item"]
    yu = names.unit(item.axis_y.units) if item.axis_y else ""
    xu = names.unit(item.axis_x.units) if item.axis_x else ""
    out = [what]
    out.append(t("Rows: {y} = {yc}; columns: {x} = {xc}. A row counts at the nearest breakpoint; "
                 "the ECU interpolates, so neighbours are affected too.",
                 y=yu or "-", yc=ov["y_channel"] or "-", x=xu or "-", xc=ov["x_channel"] or "-"))
    stats = ", ".join(f"{k}: {v}" for k, v in ov["filter_stats"].items()) or "—"
    out.append(t("Filters {list} dropped rows: {stats}. Rows used: {n}, outside the axes "
                 "(clamped to the edge): {out}.", list=",".join(ov["filters"]) or "—", stats=stats,
                 n=ov["rows_used"], out=ov["outside"]))
    return out


def _where(ov: Dict[str, Any], r: int, c: int) -> str:
    where = []
    if ov["y_breaks"]:
        where.append(f"{ov['y_channel']}={tplog.fmt(ov['y_breaks'][r])}")
    if ov["x_breaks"]:
        where.append(f"{ov['x_channel']}={tplog.fmt(ov['x_breaks'][c])}")
    return f"[{r},{c}] " + " ".join(where)


def _cell_text(ov: Dict[str, Any], cell: Dict[str, Any]) -> str:
    text = t("rows {n}", n=cell["n"])
    if ov["value_channel"] and cell["vn"]:
        text += "; " + t("{ch} mean {mean} (min {lo}, max {hi}) {units}", ch=ov["value_channel"],
                         mean=tplog.fmt(cell["mean"]), lo=tplog.fmt(cell["vmin"]),
                         hi=tplog.fmt(cell["vmax"]), units=ov["value_units"]).rstrip()
    if cell["retard"]:
        text += "; " + t("knock {k} (cyl {cyl}), retard rows {rr}, deepest {w}°",
                         k=cell["knock"], cyl=",".join(cell["cyl"]) or "-", rr=cell["retard"],
                         w=tplog.fmt(cell["worst"]))
        if cell["t"]:
            text += "; " + t("at {list} s", list=", ".join(tplog.fmt(v) for v in cell["t"]))
    return text


def tool_log_map_hits(args: Dict) -> str:
    ws = _ws()
    path = tplog.resolve(_logs_dir(ws), args.get("log", ""))
    value = args.get("value_channel", "")
    ov = overlay(ws, path, args.get("map", ""), args.get("y_channel", ""),
                 args.get("x_channel", ""), _filters(args.get("filters"), value), value)
    item = ov["item"]
    dec = max(item.value_decimals, 1)
    units = names.unit(item.value_units)
    out = _header(ov, t("{log} over {map} of {firmware} (the firmware the log was recorded on).",
                        log=os.path.basename(path), map=item.title,
                        firmware=os.path.basename(ov["binding"]["bin"])))
    out.append(t("knock = rows where a correction got deeper (knock detected); retard = rows with "
                 "any negative correction (also the slow recovery after an event)."))
    out.append("")
    lines = 0
    for r, row in enumerate(ov["grid"]):
        for c, cell in enumerate(row):
            if not cell["n"]:
                continue
            out.append(_where(ov, r, c) + ": " + t("map {value} {units}", value=format_number(
                ov["matrix"][r][c], dec, 1), units=units).rstrip() + "; " + _cell_text(ov, cell))
            lines += 1
    if not lines:
        out.append(t("No rows of this log fall on the map with these filters."))
    return "\n".join(out)


def tool_log_compare(args: Dict) -> str:
    ws = _ws()
    folder = _logs_dir(ws)
    before = tplog.resolve(folder, args.get("before", ""))
    after = tplog.resolve(folder, args.get("after", ""))
    value = args.get("value_channel", "")
    cmp_ = compare(ws, before, after, args.get("map", ""), args.get("y_channel", ""),
                   args.get("x_channel", ""), _filters(args.get("filters"), value), value)
    a, b = cmp_["before"], cmp_["after"]
    item = a["item"]
    dec = max(item.value_decimals, 1)
    units = names.unit(item.value_units)
    out = _header(a, t("{map}: BEFORE {a} (firmware {fa}) vs AFTER {b} (firmware {fb}).",
                       map=item.title, a=os.path.basename(before), b=os.path.basename(after),
                       fa=os.path.basename(a["binding"]["bin"]),
                       fb=os.path.basename(b["binding"]["bin"])))
    out.append(t("Rows used after: {n}, outside the axes: {out}.", n=b["rows_used"], out=b["outside"]))
    out.append(t("A cell visited in only one of the logs says nothing about the change there."))
    out.append("")
    lines = 0
    for r, row in enumerate(a["grid"]):
        for c, ca in enumerate(row):
            cb = b["grid"][r][c]
            va, vb = a["matrix"][r][c], b["matrix"][r][c]
            if not (ca["n"] or cb["n"]) and va == vb:
                continue
            map_text = format_number(va, dec, 1) if va == vb else \
                f"{format_number(va, dec, 1)} -> {format_number(vb, dec, 1)}"
            out.append(_where(a, r, c) + ": " + t("map {value} {units}", value=map_text,
                                                  units=units).rstrip())
            out.append("    " + t("before: {text}", text=_cell_text(a, ca) if ca["n"] else t("not visited")))
            out.append("    " + t("after:  {text}", text=_cell_text(b, cb) if cb["n"] else t("not visited")))
            lines += 1
    if not lines:
        out.append(t("No rows of this log fall on the map with these filters."))
    return "\n".join(out)


def tool_log_show(args: Dict) -> str:
    ws = _ws()
    path = tplog.resolve(_logs_dir(ws), args.get("log", ""))
    view = {"log": os.path.basename(path)}
    if args.get("compare"):
        view["compare"] = os.path.basename(tplog.resolve(_logs_dir(ws), args["compare"]))
    for key in ("map", "from", "to", "y_channel", "x_channel", "value_channel"):
        if args.get(key) not in (None, ""):
            view[key] = args[key]
    if args.get("filters") is not None:
        view["filters"] = _filters(args.get("filters"), args.get("value_channel", ""))
    ws.show_log(view)
    return t("The log is open in the window (Logs screen) for the owner.")


def evidence_for(name: str) -> Dict[str, Any]:
    """{"log", "bin_sha1"} for edit_propose(evidence_log=...)."""
    ws = _ws()
    path = tplog.resolve(_logs_dir(ws), name)
    binding, problem = _bound(path)
    if problem and not binding:
        raise ValueError(t("The log {name} is not bound to a firmware; the owner binds it on the "
                           "Logs screen.", name=name))
    return {"log": os.path.basename(path), "bin_sha1": binding["bin_sha1"]}


_LOG = {"type": "string", "description": "log file name in the project's logs/ (see log_list)"}
_FILTERS = {"type": "array", "items": {"type": "string", "enum": list(tplog.FILTERS)},
            "description": "rows to drop: warm = coolant below 80 °C, steady = throttle moving "
                           "faster than 40 %/s, no_overrun = fuel cut on, closed_loop = lambda "
                           "control off. Default: warm, steady, no_overrun (+ closed_loop when "
                           "value_channel is a fuel trim); [] = every row."}
_VALUE = {"type": "string", "description": "also average this channel per cell, e.g. a fuel "
                                           "trim (log_info lists the channels)"}

TOOLS: List[Dict[str, Any]] = [
    {
        "name": "log_list",
        "description": "TunerPro logs in the project, each with the firmware it was recorded on "
                       "and whether that firmware file is still there unchanged.",
        "inputSchema": {"type": "object", "properties": {}},
        "_fn": tool_log_list,
    },
    {
        "name": "log_info",
        "description": "One log: rate, gaps, dead channels, EVERY knock event (time, rpm, load, "
                       "throttle, IAT, deepest retard per cylinder), flags, channel list with units.",
        "inputSchema": {"type": "object", "properties": {"log": _LOG}, "required": ["log"]},
        "_fn": tool_log_info,
    },
    {
        "name": "log_rows",
        "description": f"Rows of a log as CSV (up to {ROWS_PER_CALL} per call; page with from/to). "
                       "Default channels: rpm, speed, gear, pedal, throttle, loads, ignition, IAT, "
                       "coolant and knock corrections.",
        "inputSchema": {"type": "object", "properties": {
            "log": _LOG, "from": {"type": "number", "description": "seconds"},
            "to": {"type": "number", "description": "seconds"},
            "channels": {"type": "array", "items": {"type": "string"}},
            "every": {"type": "integer", "description": "take every Nth row (default 1)"}},
            "required": ["log"]},
        "_fn": tool_log_rows,
    },
    {
        "name": "log_map_hits",
        "description": "Lay a log over a map of the firmware it was recorded on: per cell the map "
                       "value, rows spent there, knock detections and cylinders, retard rows, deepest "
                       "retard and times. Axis channels are guessed from the map name (n -> Engine "
                       "Speed, maf -> Engine Load Ignition for ignition maps); override with "
                       "y_channel/x_channel. Cite these cells in edit_propose.",
        "inputSchema": {"type": "object", "properties": {
            "log": _LOG, "map": {"type": "string", "description": "map name from the XDF"},
            "y_channel": {"type": "string"}, "x_channel": {"type": "string"},
            "value_channel": _VALUE, "filters": _FILTERS}, "required": ["log", "map"]},
        "_fn": tool_log_map_hits,
    },
    {
        "name": "log_compare",
        "description": "Two logs over the same map, cell by cell: BEFORE and AFTER a flash (each "
                       "over the firmware it was recorded on, so a changed map value shows as "
                       "old -> new). Use it to check whether a change worked: knock gone, new "
                       "knock, trims moved. Only cells visited in both logs say something.",
        "inputSchema": {"type": "object", "properties": {
            "before": _LOG, "after": _LOG, "map": {"type": "string"},
            "y_channel": {"type": "string"}, "x_channel": {"type": "string"},
            "value_channel": _VALUE, "filters": _FILTERS},
            "required": ["before", "after", "map"]},
        "_fn": tool_log_compare,
    },
    {
        "name": "log_show",
        "description": "Open a log in the program window (Logs screen) for the owner: optionally "
                       "over a map, zoomed to from/to seconds.",
        "inputSchema": {"type": "object", "properties": {
            "log": _LOG, "map": {"type": "string"}, "from": {"type": "number"},
            "to": {"type": "number"}, "y_channel": {"type": "string"},
            "x_channel": {"type": "string"}, "value_channel": _VALUE, "filters": _FILTERS,
            "compare": {"type": "string", "description": "a second log: show before/after"}},
            "required": ["log"]},
        "_fn": tool_log_show,
    },
]


# ---------------------------------------------------------------------------
# firmware_diff: what one firmware changes against another (same XDF)
# ---------------------------------------------------------------------------

def _firmware_ref(ws, ref: str):
    """(label, firmware path, XDF path) for "A", "B", "other" or a project log's firmware."""
    ref = (ref or "").strip()
    roles = {"a": ("bin_a", "xdf"), "b": ("bin_b", "xdf"), "other": ("bin2", "xdf2")}
    if ref.lower() in roles:
        role, xdf_role = roles[ref.lower()]
        path, xdf = ws.paths.get(role, ""), ws.paths.get(xdf_role, "")
        if not (path and xdf):
            raise ValueError(t("Firmware {ref} is not chosen in the window.", ref=ref))
        return f"{ref.upper()} ({os.path.basename(path)})", path, xdf
    path = tplog.resolve(_logs_dir(ws), ref)
    binding, problem = _bound(path)
    if problem:
        raise ValueError(t("The firmware of {log} cannot be used: {why}", log=ref, why=problem))
    return (t("the firmware of {log} ({name})", log=os.path.basename(path),
              name=os.path.basename(binding["bin"])), binding["bin"], binding["xdf"])


def tool_firmware_diff(args: Dict) -> str:
    from .compare import compare_bins

    ws = _ws()
    la, pa, xa = _firmware_ref(ws, args.get("a", "A"))
    lb, pb, xb = _firmware_ref(ws, args.get("b", "B"))
    if os.path.abspath(xa) != os.path.abspath(xb):
        raise ValueError(t("The two firmware files use different XDFs; compare different software "
                           "versions on the window's Different versions screen."))
    result = compare_bins(ws.xdf(xa), BinFile(pa), BinFile(pb), include_checksums=False)
    for label, reader in ((la, result.reader_a), (lb, result.reader_b)):
        warn = reader.version_warning()
        if warn:
            return t("{label}: {warning}", label=label, warning=warn)
    max_cells = int(args.get("max_cells") or 12)
    out = [t("{a} -> {b}: {n} parameters changed, {same} the same.", a=la, b=lb,
             n=len(result.changes), same=result.identical)]
    for ch in result.changes:
        item = ch.item
        dec = max(item.value_decimals, 1)
        units = names.unit(item.value_units)
        head = f"- {item.title} — {names.name(item.title)}"
        if ch.text_a is not None or ch.text_b is not None:
            out.append(head + f": '{ch.text_a}' -> '{ch.text_b}'")
            continue
        if item.cell_count == 1:
            out.append(head + f": {format_number(ch.vals_a[0], dec, 1)} -> "
                       f"{format_number(ch.vals_b[0], dec, 1)} {units}".rstrip())
            continue
        out.append(head + ": " + t("{changed} of {total} cells changed, by {lo}..{hi} {units}",
                                   changed=ch.changed_cells, total=ch.total_cells,
                                   lo=format_number(ch.delta_min, dec, 1),
                                   hi=format_number(ch.delta_max, dec, 1), units=units).rstrip())
        ys = result.reader_a.axis_values(item, "y") or []
        xs = result.reader_a.axis_values(item, "x") or []
        for cell in ch.cells[:max_cells]:
            where = []
            if item.rows > 1 and cell.row < len(ys):
                where.append(tplog.fmt(ys[cell.row]))
            if item.cols > 1 and cell.col < len(xs):
                where.append(tplog.fmt(xs[cell.col]))
            at = "×".join(where) or f"[{cell.row},{cell.col}]"
            out.append(f"    {at}: {format_number(cell.val_a, dec, 1)} -> {format_number(cell.val_b, dec, 1)}")
        if len(ch.cells) > max_cells:
            out.append("    " + t("… and {n} more", n=len(ch.cells) - max_cells))
    unlabeled = [b for b in result.byte_blocks if not b.labels]
    if unlabeled:
        out.append(t("Bytes changed outside any XDF parameter (program code, patches, checksums): "
                     "{n} block(s), e.g. {list}", n=len(unlabeled),
                     list=", ".join(f"0x{b.start:05X}-0x{b.end - 1:05X}" for b in unlabeled[:8])))
    return "\n".join(out)


TOOLS.append({
    "name": "firmware_diff",
    "description": "What one firmware changes against another of the same software version: every "
                   "changed parameter and map, before -> after in XDF units, the changed cells with "
                   "their axis values, and bytes changed outside the XDF (code, patches). a and b: "
                   "\"A\", \"B\", \"other\" (the files chosen in the window) or a project log name "
                   "(the firmware that log was recorded on). Use it to know what a tune changed "
                   "before judging knock or trims.",
    "inputSchema": {"type": "object", "properties": {
        "a": {"type": "string", "description": "A, B, other, or a log name (default A)"},
        "b": {"type": "string", "description": "A, B, other, or a log name (default B)"},
        "max_cells": {"type": "integer", "description": "changed cells listed per map (default 12)"}}},
    "_fn": tool_firmware_diff,
})


from .car import GEARBOXES as _GEARBOXES  # noqa: E402 - used in a tool description

_GEARBOX_KEYS = tuple(_GEARBOXES)


def _project(ws) -> str:
    return os.path.dirname(_logs_dir(ws))


def _car(ws) -> Dict[str, Any]:
    from . import car as carmod

    return carmod.load(_project(ws))


def _car_changed(ws) -> None:
    """The car went into the rules: regenerate them (the window's AI screen does it)."""
    ai = getattr(ws, "ai", None)
    if ai is not None and hasattr(ai, "refresh_rules"):
        ai.refresh_rules()
    if hasattr(ws, "notify"):
        ws.notify()


def tool_car_info(args: Dict) -> str:
    from . import car as carmod

    data = _car(_ws())
    out = [t("The car (\"not confirmed\" = ask, never assume; \"proposed\" = usable, but say it "
             "is not confirmed):"), carmod.rules_text(data)]
    speeds = carmod.speeds_per_1000(data)
    if speeds:
        out.append(t("Speed at 1000 rpm: {list}", list=", ".join(
            t("gear {g}: {v} km/h", g=g, v=tplog.fmt(v, 1)) for g, v in speeds)))
    else:
        out.append(t("The gear cannot be computed from rpm and speed yet: run car_calibrate on "
                     "the logs, or ask the owner for the gearbox, final drive and tyres."))
    if data["proposals"]:
        out.append(t("Waiting for the owner to accept in the window (AI assistant screen, Car): {list}",
                     list=", ".join(p["field"] for p in data["proposals"])))
    return "\n".join(out)


def tool_car_calibrate(args: Dict) -> str:
    from . import car as carmod

    ws = _ws()
    folder = _logs_dir(ws)
    names = args.get("logs") or []
    paths = [tplog.resolve(folder, n) for n in names] if names else tplog.list_logs(folder)
    data = _car(ws)
    result = carmod.calibrate(paths, data)
    out = carmod.calibration_text(result, data)
    proposed = carmod.apply_calibration(_project(ws), result)
    if proposed:
        _car_changed(ws)
        out.append(t("Proposed to the owner (to accept in the window): {list}", list=", ".join(proposed)))
    return "\n".join(out)


def tool_car_propose(args: Dict) -> str:
    from . import car as carmod

    ws = _ws()
    field = str(args.get("field") or "")
    reason = str(args.get("reason") or "").strip()
    if not reason:
        raise ValueError(t("Say where the value comes from (reason)."))
    carmod.propose(_project(ws), field, args.get("value"), "Claude", reason)
    _car_changed(ws)
    return t("Proposed: {field}. The owner accepts or rejects it in the window (AI assistant "
             "screen, Car); until then it counts as not confirmed.", field=field)


TOOLS.append({
    "name": "car_info",
    "description": "The owner's car profile: gearbox and ratios, final drive, tyres, speed per 1000 "
                   "rpm per gear (measured from the logs), where the vehicle speed comes from "
                   "(wheelspin!), what was removed or changed, fuel. Each value is confirmed, "
                   "proposed (not confirmed yet) or unknown.",
    "inputSchema": {"type": "object", "properties": {}},
    "_fn": tool_car_info,
})
TOOLS.append({
    "name": "car_calibrate",
    "description": "Measure the speed per 1000 rpm in each gear from steady driving in the logs, "
                   "find the gearbox by the steps between gears, check the final drive, tyres and "
                   "the logged speed (c_vs_fac) and the ECU's own gear recognition. Proposes the "
                   "values to the owner; nothing is confirmed without them.",
    "inputSchema": {"type": "object", "properties": {
        "logs": {"type": "array", "items": {"type": "string"},
                 "description": "log names (default: all logs of the project)"}}},
    "_fn": tool_car_calibrate,
})
TOOLS.append({
    "name": "car_propose",
    "description": "Propose one value of the car profile from what the owner told you or what "
                   "you found (the owner accepts it in the window; never type it for them). "
                   "Fields: model, gearbox (" + ", ".join(_GEARBOX_KEYS)
                   + " or free text), ratios (\"4.21 2.49 1.66 1.24 1.00\"), final_drive, tire "
                   "(\"205/55 R16\"), circumference (m), speed_sensor (abs_front, abs_rear, "
                   "differential, gearbox), modifications (list of: sap, cat, rear_o2, ccv_vent, "
                   "smf, intake, exhaust, cams, injectors, maf), mods_other, fuel, notes.",
    "inputSchema": {"type": "object", "properties": {
        "field": {"type": "string"},
        "value": {"description": "the value (text, number or list)"},
        "reason": {"type": "string", "description": "where it comes from (the owner said …, the log …)"}},
        "required": ["field", "value", "reason"]},
    "_fn": tool_car_propose,
})


def tool_log_modes(args: Dict) -> str:
    from . import car as carmod

    ws = _ws()
    path = tplog.resolve(_logs_dir(ws), args.get("log", ""))
    log = tplog.load(path)
    car = _car(ws)
    f = tplog.fmt
    out = [t("Log {name}: driving modes", name=log.name)]

    idle = tplog.idle_segments(log)
    out.append("")
    out.append(t("Idle at a standstill: {n} segment(s)", n=len(idle)))
    for s in idle[:30]:
        parts = [f"{f(s['start'], 1)}-{f(s['end'], 1)} s"]
        if "rpm" in s:
            m, lo, hi, sd = s["rpm"]
            parts.append(t("rpm {m} ({lo}..{hi}, spread ±{sd})", m=f(m, 0), lo=f(lo, 0), hi=f(hi, 0),
                           sd=f(sd, 0)))
        for key, label in (("iac", "IAC %"), ("ign", "ign °"), ("stft1", "STFT1 %"), ("stft2", "STFT2 %"),
                           ("inj1", "inj1 ms"), ("inj2", "inj2 ms"), ("coolant", "coolant °C")):
            if s.get(key) is not None:
                parts.append(f"{label} {f(s[key], 2 if key.startswith('inj') else 1)}")
        out.append("  " + "; ".join(parts))

    out.append("")
    _, top = tplog.full_throttle_mask(log)
    pulls = tplog.pulls(log, car)
    out.append(t("Full-throttle pulls (pedal >= 90 % of the log's maximum {top}, longer than 1 s): {n}",
                 top=f(top, 1), n=len(pulls)))
    if pulls and not carmod.speeds_per_1000(car):
        out.append("  " + t("The gear is not computed: the car profile has no gear ratios, final drive "
                            "or tyres. Ask the owner; never assume a gearbox."))
    if car.get("speed_sensor") in ("abs_rear", "differential", "gearbox"):
        out.append("  " + t("The speed comes from the driven wheels or the gearbox: wheelspin does not "
                            "show as rpm rising against the speed."))
    for p in pulls:
        line = [f"{f(p['start'], 1)}-{f(p['end'], 1)} s"]
        if "rpm" in p:
            line.append(t("rpm {a} -> {b} (max {m})", a=f(p["rpm"][0], 0), b=f(p["rpm"][1], 0),
                          m=f(p["rpm"][2], 0)))
        if "speed" in p:
            line.append(t("speed {a} -> {b} km/h", a=f(p["speed"][0], 0), b=f(p["speed"][1], 0)))
        if "gear" in p:
            g, err = p["gear"]
            line.append(t("gear {g} (rpm/speed off by {e} %)", g=g, e=f(100 * (err or 0), 1)))
        line.append(t("knock: {rows} rows, {det} detections", rows=p["knock_rows"], det=p["detections"]))
        if p["cylinders"]:
            line.append(t("deepest: {list}", list=", ".join(
                f"cyl{c} {f(v)}°" for c, v in sorted(p["cylinders"].items()))))
        out.append("  " + "; ".join(line))
        if p.get("rates"):
            out.append("    " + t("rpm rate: {list}", list=", ".join(
                f"{lo}-{lo + 1000}: {f(r, 0)} rpm/s" for lo, r in p["rates"])))
        for b in p.get("profile", []):
            vals = [f"{label} {f(b[key], 1)}" for key, label in
                    (("load", "load"), ("maf", "MAF kg/h"), ("ign", "ign °"), ("vanos_in", "VANOS in"),
                     ("vanos_ex", "VANOS ex"), ("iat", "IAT °C")) if b.get(key) is not None]
            out.append("    " + f"{b['band']}-{b['band'] + 1000} ({b['rows']}): " + ", ".join(vals))

    lim = tplog.limiter(log)
    out.append("")
    if lim:
        out.append(t("Near the top rpm {top}: {rows} rows, {peaks} rpm peaks (sawtooth), injector duty "
                     "max {duty} %", top=f(lim["top"], 0), rows=lim["rows"], peaks=lim["peaks"],
                     duty=f(lim["duty_max"], 1) if lim["duty_max"] is not None else "—"))
        out.append("  " + ", ".join(f"{f(a, 1)}-{f(b, 1)} s" for a, b in lim["segments"][:15]))
    else:
        out.append(t("The rpm never came near the limiter (max below 5500)."))

    km = tplog.knock_by_mode(log)
    out.append("")
    out.append(t("Knock weighted by time (share of rows with retard):"))
    for mode, label in (("full", t("full throttle")), ("part", t("warm part load"))):
        d = km.get(mode)
        if not d:
            out.append("  " + t("{mode}: no rows", mode=label))
            continue
        cyl = ", ".join(f"cyl{c} {f(100 * v, 1)} %" for c, v in sorted(d["per_cylinder"].items()))
        out.append("  " + t("{mode}: {s} s, any cylinder {share} % of the rows, {det} detections per "
                            "minute; {cyl}", mode=label, s=f(d["seconds"], 0),
                            share=f(100 * d["retard_share"], 1), det=f(d["detections_per_min"], 1),
                            cyl=cyl))
    return "\n".join(out)


TOOLS.append({
    "name": "log_modes",
    "description": "A log split by driving mode: idle segments (rpm spread, idle actuator, ignition, "
                   "trims and injection per bank), full-throttle pulls (gear from the car profile, rpm "
                   "rate per 1000-rpm band, knock, load/MAF/ignition/VANOS profile), time near the "
                   "limiter, and knock weighted by time for full throttle vs part load.",
    "inputSchema": {"type": "object", "properties": {
        "log": {"type": "string", "description": "log file name (see log_list)"}},
        "required": ["log"]},
    "_fn": tool_log_modes,
})


def tool_logger_info(args: Dict) -> str:
    from .webui import modes

    ws = _ws()
    role = str(args.get("firmware") or "bin_a")
    a = modes._adx_view(ws, role)
    out = [t("Logger definition (ADX): {name}", name=a.get("name") or "—")]
    if a.get("request"):
        out.append("  " + t("data request {req}, {n} channels, base rate {baud}, fast rate: {fast}",
                            req=a["request"], n=a.get("channels"), baud=a.get("baud"),
                            fast=t("yes") if a.get("fast") else t("no")))
    if a.get("check"):
        out.append("  " + t("fits the firmware: {state} — {text}", state=a["check"]["state"],
                            text=a["check"]["text"]))
    out.append(t("Firmware in the window ({role}): {fw}; engine: {engine}", role=role,
                 fw=a.get("firmware") or "?", engine=a.get("engine") or "?"))
    pack = a.get("pack") or []
    out.append(t("ADX pack ({folder}): {list}", folder=a.get("pack_folder"),
                 list=", ".join(f"{p['name']} ({p['request']})" for p in pack) or "—"))
    out.append(t("Suggested: {name}; standard (0B 03) fallback: {std}",
                 name=a.get("recommended") or "—", std=a.get("standard") or t("none")))
    test = getattr(ws, "logger_test", None)
    if test:
        out.append("")
        out.append(t("Last \"Check the connection\": {result}", result=t("works, mode {mode}", mode=test.get("mode"))
                     if test.get("ok") else t("failed: {error}", error=test.get("error"))))
        if test.get("ident"):
            out.append("  ident: " + str(test["ident"].get("text") or test["ident"].get("hex")))
        for step in test.get("steps") or []:
            mark = {True: "OK", False: "NO"}.get(step.get("ok"), "--")
            out.append(f"  [{mark}] {step.get('text')}")
        if test.get("journal_file"):
            out.append("  " + t("journal: logs/{file}", file=test["journal_file"]))
    rec = getattr(ws, "recorder", None)
    if rec is not None:
        st = rec.status
        out.append("")
        out.append(t("Recorder: {state}, mode {mode}, {rows} rows, {rate} Hz, missed {errors}, "
                     "reconnects {rec}", state=st.get("state"), mode=st.get("mode") or "—",
                     rows=st.get("rows"), rate=st.get("rate"), errors=st.get("errors"),
                     rec=st.get("reconnects")))
        if st.get("message"):
            out.append("  " + str(st["message"]))
    return "\n".join(out)


TOOLS.append({
    "name": "logger_info",
    "description": "The window's own logger: the chosen ADX (data request 0B 03 standard / 0B B0 "
                   "extended, fast rate), whether the firmware in the car supports it (logging "
                   "patch, MS43X), the ADX pack and the suggested ADX, the last \"Check the "
                   "connection\" (ident, each step, the mode a recording uses, the journal file) "
                   "and the recorder state. Read-only: only the owner connects and records.",
    "inputSchema": {"type": "object", "properties": {
        "firmware": {"type": "string", "description": "bin_a (default), bin_b or bin2: the firmware in the car"}}},
    "_fn": tool_logger_info,
})
