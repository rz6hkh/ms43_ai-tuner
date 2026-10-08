# -*- coding: utf-8 -*-
"""
The car profile of a tuning project (car.json in the project folder).

Facts a log cannot tell and Claude must not guess: the gearbox, the final
drive, the tyres, where the vehicle speed comes from, what was removed or
changed, the fuel. They go into the rules of the project ("The car") and into
the log analysis (the gear from rpm and speed).

What the calculations really need is the speed per 1000 rpm in each gear. It
is measured from the logs (steady driving, see calibrate) and checked against
the gearbox, final drive and tyres the owner picked from lists, so nobody has
to type ratios to three decimals.

Every value has a state: confirmed (the owner entered or accepted it),
proposed (by Claude or by the log calibration, with its source; used, but
marked "not confirmed") or unknown.
"""

from __future__ import annotations

import json
import math
import os
import re
from typing import Any, Dict, List, Optional, Sequence, Tuple

from .i18n import t

CAR_FILE = "car.json"
SPEED_SENSORS = ("unknown", "abs_front", "abs_rear", "differential", "gearbox")
MODELS = ("E30", "E34", "E36", "E39", "E46", "E53 X5", "E85 Z4", "Z3")

# Typical ratios (forum and parts data, not BMW documents): the log calibration checks them.
GEARBOXES: Dict[str, Dict[str, Any]] = {
    "zf_s5d_320z": {"name": "ZF S5D 320Z / 310Z", "use": "E46 330i, E39 528i/530i, E36 328i",
                    "ratios": [4.21, 2.49, 1.66, 1.24, 1.00]},
    "getrag_s5d_250g": {"name": "Getrag 220/5 · S5D 200G / 250G",
                        "use": "E36 318i/318is/323i/325i/328i, E46 (M4x, M5x)",
                        "ratios": [4.23, 2.52, 1.66, 1.22, 1.00]},
    "getrag_240": {"name": "Getrag 240/5", "use": "E30 320i (M20), 318i/318is (M40, M42)",
                   "ratios": [3.72, 2.02, 1.32, 1.00, 0.81]},
    "getrag_220_4": {"name": "Getrag 220 (4-speed)", "use": "E30 316/318i",
                     "ratios": [3.76, 2.04, 1.32, 1.00]},
    "zf_gs6_37bz": {"name": "ZF GS6-37BZ (6-speed)", "use": "E46 330i ZHP, E60/E83 6-speed",
                    "ratios": [4.35, 2.50, 1.67, 1.23, 1.00, 0.85]},
    "getrag_260": {"name": "Getrag 260/5", "use": "E30 325i (M20), E28/E34",
                   "ratios": [3.83, 2.20, 1.40, 1.00, 0.81]},
    "getrag_265_cr": {"name": "Getrag 265/5 dogleg", "use": "E28/E34 close ratio",
                      "ratios": [3.72, 2.40, 1.77, 1.26, 1.00]},
    "gm_5l40e": {"name": "GM 5L40-E / A5S 360R (automatic)", "use": "E46, E39, E53",
                 "ratios": [3.42, 2.21, 1.60, 1.00, 0.75]},
    "zf_5hp19": {"name": "ZF 5HP19 (automatic)", "use": "E39, E46",
                 "ratios": [3.67, 2.00, 1.41, 1.00, 0.74]},
}
FINAL_DRIVES = (2.79, 2.93, 3.07, 3.15, 3.23, 3.38, 3.46, 3.64, 3.73, 3.91, 4.10)
MODS = {
    "sap": "secondary air pump removed",
    "cat": "catalysts removed",
    "rear_o2": "rear O2 sensors removed",
    "ccv_vent": "crankcase ventilation vented to atmosphere",
    "smf": "single-mass flywheel",
    "intake": "intake changed",
    "exhaust": "exhaust manifold / exhaust changed",
    "cams": "camshafts changed",
    "injectors": "injectors changed",
    "maf": "MAF sensor changed",
}
FIELDS = ("model", "gearbox", "ratios", "final_drive", "tire", "circumference", "speed_sensor",
          "modifications", "mods_other", "fuel", "notes", "per_1000")

_TIRE = re.compile(r"(\d{3})\s*/\s*(\d{2})\s*Z?R\s*(\d{2})", re.IGNORECASE)


def _float(value: Any) -> Optional[float]:
    try:
        v = float(str(value).replace(",", ".").strip())
    except (TypeError, ValueError):
        return None
    return v if v > 0 else None


def _numbers(raw: Any, limit: float, message: str) -> List[float]:
    if isinstance(raw, str):
        raw = [p for p in re.split(r"[\s;/]+", raw.replace(",", ".")) if p]
    out = []
    for part in raw or []:
        v = _float(part)
        if v is None or v > limit:
            raise ValueError(message)
        out.append(round(v, 3))
    return out


def tire_circumference(size: str) -> Optional[float]:
    """Rolling circumference in metres from "205/55 R16" (a little less than the geometric one)."""
    m = _TIRE.search(size or "")
    if not m:
        return None
    width, aspect, rim = int(m.group(1)), int(m.group(2)), int(m.group(3))
    diameter = rim * 25.4 + 2 * width * aspect / 100.0
    return round(math.pi * diameter / 1000.0 * 0.97, 3)


def normalize_value(field: str, value: Any) -> Any:
    """One field, cleaned; raises ValueError with a readable message."""
    if field in ("model", "gearbox", "tire", "mods_other", "fuel", "notes"):
        return str(value or "").strip()[:500]
    if field == "ratios":
        ratios = _numbers(value, 10, t("Gear ratios must be numbers like 4.21 2.49 1.67 1.24 1.00."))
        if ratios and ratios != sorted(ratios, reverse=True):
            raise ValueError(t("Gear ratios go from 1st gear down: the first is the largest."))
        return ratios
    if field == "per_1000":
        speeds = _numbers(value, 120, t("Speeds per 1000 rpm must be numbers like 9.2 15.5 23.1."))
        if speeds and speeds != sorted(speeds):
            raise ValueError(t("Speeds per 1000 rpm go from 1st gear up: the first is the smallest."))
        return speeds
    if field in ("final_drive", "circumference"):
        return _float(value)
    if field == "speed_sensor":
        sensor = str(value or "unknown")
        return sensor if sensor in SPEED_SENSORS else "unknown"
    if field == "modifications":
        if isinstance(value, str):
            value = [v for v in re.split(r"[\s,;]+", value) if v]
        return [m for m in (value or []) if m in MODS]
    raise ValueError(t("Unknown car field: {field}", field=field))


def _empty(field: str, value: Any) -> bool:
    return value in (None, "", [], "unknown")


def normalize(data: Dict[str, Any]) -> Dict[str, Any]:
    """The whole profile, cleaned (old files without states count as confirmed)."""
    out: Dict[str, Any] = {f: normalize_value(f, data.get(f)) for f in FIELDS}
    if out["gearbox"] in GEARBOXES and not out["ratios"]:
        out["ratios"] = list(GEARBOXES[out["gearbox"]]["ratios"])
    proposals = []
    for p in data.get("proposals") or []:
        try:
            if p.get("field") in FIELDS:
                proposals.append({"field": p["field"], "value": normalize_value(p["field"], p.get("value")),
                                  "source": str(p.get("source") or "")[:200],
                                  "reason": str(p.get("reason") or "")[:500]})
        except (ValueError, AttributeError, TypeError):
            continue
    out["proposals"] = proposals
    return out


def load(folder: str) -> Dict[str, Any]:
    try:
        with open(os.path.join(folder, CAR_FILE), encoding="utf-8") as fh:
            return normalize(json.load(fh))
    except (OSError, ValueError, TypeError):
        return normalize({})


def _write(folder: str, car: Dict[str, Any]) -> Dict[str, Any]:
    with open(os.path.join(folder, CAR_FILE), "w", encoding="utf-8") as fh:
        json.dump(car, fh, ensure_ascii=False, indent=1)
    return car


def save(folder: str, data: Dict[str, Any]) -> Dict[str, Any]:
    """The owner's form: every value in it is confirmed; proposals for a field the owner
    set are settled."""
    old = load(folder)
    data = {k: v for k, v in data.items() if k in FIELDS}
    car = normalize({**old, **data, "proposals": old["proposals"]})
    typed = "ratios" in data and car["ratios"] != old["ratios"]
    if car["gearbox"] in GEARBOXES and car["gearbox"] != old["gearbox"] and not typed:
        car["ratios"] = list(GEARBOXES[car["gearbox"]]["ratios"])
    car["proposals"] = [p for p in car["proposals"] if _empty(p["field"], car[p["field"]])]
    return _write(folder, car)


def propose(folder: str, field: str, value: Any, source: str, reason: str = "") -> Dict[str, Any]:
    """A value for the owner to accept (from Claude or the log calibration)."""
    if field not in FIELDS:
        raise ValueError(t("Unknown car field: {field}", field=field))
    car = load(folder)
    value = normalize_value(field, value)
    car["proposals"] = [p for p in car["proposals"] if p["field"] != field]
    car["proposals"].append({"field": field, "value": value, "source": source[:200],
                             "reason": reason[:500]})
    return _write(folder, car)


def settle(folder: str, field: str, accept: bool) -> Dict[str, Any]:
    """Accept (the value becomes confirmed) or reject the proposal for a field."""
    car = load(folder)
    for p in car["proposals"]:
        if p["field"] == field and accept:
            car[field] = p["value"]
            if field == "gearbox" and p["value"] in GEARBOXES:
                car["ratios"] = list(GEARBOXES[p["value"]]["ratios"])
    car["proposals"] = [p for p in car["proposals"] if p["field"] != field]
    return _write(folder, car)


def effective(car: Dict[str, Any]) -> Dict[str, Any]:
    """Values to compute with: confirmed ones, else proposed ones. "_state" says which."""
    out = {f: car.get(f) for f in FIELDS}
    state = {f: ("unknown" if _empty(f, out[f]) else "confirmed") for f in FIELDS}
    for p in car.get("proposals") or []:
        if state[p["field"]] == "unknown":
            out[p["field"]] = p["value"]
            state[p["field"]] = "proposed"
            if p["field"] == "gearbox" and p["value"] in GEARBOXES and _empty("ratios", out["ratios"]):
                out["ratios"] = list(GEARBOXES[p["value"]]["ratios"])
                state["ratios"] = "proposed"
    out["_state"] = state
    return out


def circumference(car: Dict[str, Any]) -> Optional[float]:
    return car.get("circumference") or tire_circumference(car.get("tire", ""))


def speeds_per_1000(car: Dict[str, Any]) -> List[Tuple[int, float]]:
    """km/h at 1000 rpm in every gear: measured from the logs when known, else from the
    ratios, final drive and tyres; empty when neither is there."""
    car = car if "_state" in car else effective(car)
    if car.get("per_1000"):
        return [(i + 1, v) for i, v in enumerate(car["per_1000"])]
    circ = circumference(car)
    if not (car.get("ratios") and car.get("final_drive") and circ):
        return []
    return [(i + 1, 60.0 * circ / (r * car["final_drive"]))
            for i, r in enumerate(car["ratios"])]


def gear_for(rpm: float, speed: float, car: Dict[str, Any]) -> Optional[Tuple[int, float]]:
    """(gear, error as a fraction) from rpm and speed; None without the data or when standing."""
    table = speeds_per_1000(car)
    if not table or speed < 5 or rpm < 500:
        return None
    per_1000 = speed / rpm * 1000.0
    gear, ref = min(table, key=lambda g: abs(g[1] - per_1000))
    return gear, (per_1000 - ref) / ref


SENSOR_TEXT = {
    "unknown": "not confirmed",
    "abs_front": "ABS ring of the front (not driven) wheels — road speed; wheelspin shows as rpm "
                 "rising against the speed",
    "abs_rear": "ABS ring of the rear (driven) wheels — wheel speed; during wheelspin it rises "
                "with the rpm and does not show the slip",
    "differential": "the rear differential (driven wheels) — wheel speed; during wheelspin it "
                    "rises with the rpm and does not show the slip",
    "gearbox": "the gearbox output — shows neither wheelspin nor clutch slip",
}


def _shown(field: str, value: Any) -> str:
    if field == "gearbox":
        box = GEARBOXES.get(value)
        return f"{box['name']} (typical ratios)" if box else str(value)
    if field in ("ratios",):
        return " / ".join(f"{r:g}" for r in value)
    if field == "per_1000":
        return ", ".join(f"gear {i + 1}: {v:g} km/h" for i, v in enumerate(value))
    if field == "speed_sensor":
        return SENSOR_TEXT.get(value, str(value))
    if field == "modifications":
        return "; ".join(MODS[m] for m in value)
    if isinstance(value, float):
        return f"{value:g}"
    return str(value)


def rules_text(car: Dict[str, Any]) -> str:
    """The "The car" section of the project rules (English, like the rest of the rules)."""
    nc = "*not confirmed — ask the owner, never assume a typical value*"
    eff = effective(car)
    sources = {p["field"]: p["source"] for p in car.get("proposals") or []}

    def val(field: str) -> str:
        state = eff["_state"][field]
        if state == "unknown":
            return nc
        text = _shown(field, eff[field])
        if state == "proposed":
            text += f" *(proposed, source: {sources.get(field) or '?'}; not confirmed by the owner)*"
        return text

    mods = []
    if eff["_state"]["modifications"] != "unknown":
        mods.append(val("modifications"))
    if eff["mods_other"]:
        mods.append(val("mods_other"))
    circ = circumference(eff)
    lines = [
        f"- Car: {val('model')}",
        f"- Gearbox: {val('gearbox')}; ratios: {val('ratios')}",
        f"- Final drive: {val('final_drive')}",
        f"- Tyres: {val('tire')}" + (f" (rolling circumference about {circ:.3f} m)" if circ else ""),
        f"- Speed per 1000 rpm, measured from the logs: {val('per_1000')}",
        f"- Vehicle speed comes from: {val('speed_sensor')}",
        f"- Removed or changed: {'; '.join(mods) if mods else nc}",
        f"- Fuel: {val('fuel')}",
    ]
    if eff.get("notes"):
        lines.append(f"- Notes: {val('notes')}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Calibration from the logs
# ---------------------------------------------------------------------------

def steady_ratios(log) -> Tuple[List[float], float]:
    """km/h per 1000 rpm in rows of steady driving in gear, and the time of one row.

    The logged speed may update only about once a second (whole km/h) and lags
    behind the rpm, so a row counts only when, over the 1.5 s before it and 0.5 s
    after, the rpm stayed within 3 % and the speed within 1 km/h + 2 % (no
    acceleration, no clutch); speed >= 15 km/h and rpm >= 1200."""
    from . import tplog

    rpm, speed = log.col(tplog.RPM), log.col("Vehicle Speed")
    step = tplog.quality(log)["median_step"] or 0.05
    if rpm is None or speed is None:
        return [], step
    tm = log.time
    out = []
    a = b = 0
    n = log.n
    for i in range(n):
        v, r = speed[i], rpm[i]
        if not (tplog._ok(v) and tplog._ok(r)) or v < 15 or r < 1200:
            continue
        while a < i and tm[a] < tm[i] - 1.5:
            a += 1
        b = max(b, i)
        while b + 1 < n and tm[b + 1] <= tm[i] + 0.5:
            b += 1
        rs = [rpm[k] for k in range(a, b + 1) if tplog._ok(rpm[k])]
        vs = [speed[k] for k in range(a, b + 1) if tplog._ok(speed[k])]
        if len(rs) < 5 or not vs or (max(rs) - min(rs)) / r > 0.03 \
                or max(vs) - min(vs) > 1.0 + 0.02 * v:
            continue
        out.append(sum(vs) / len(vs) / (sum(rs) / len(rs)) * 1000.0)
    return out, step


def clusters(values: Sequence[float], step: float, min_seconds: float = 4.0) -> List[Dict[str, Any]]:
    """Groups of close values (a gap of more than 3 % starts a new group): one per gear,
    kept when there are at least min_seconds of steady driving in it."""
    vals = sorted(values)
    groups: List[List[float]] = []
    for v in vals:
        if groups and v - groups[-1][-1] <= 0.03 * v:
            groups[-1].append(v)
        else:
            groups.append([v])
    return [{"per_1000": round(g[len(g) // 2], 2), "seconds": round(len(g) * step, 1)}
            for g in groups if len(g) * step >= min_seconds]


def match(measured: Sequence[float]) -> List[Dict[str, Any]]:
    """Gearboxes whose steps between gears explain the measured speeds per 1000 rpm, best
    first. Scale-free: the final drive, the tyres and a wrong speed signal only change the
    common factor k (speed per 1000 rpm = k / ratio), never the steps."""
    out = []
    if len(measured) < 2:
        return out
    for key, box in GEARBOXES.items():
        ratios = box["ratios"]
        best = None
        for anchor in range(len(ratios)):
            k0 = measured[0] * ratios[anchor]
            gears = [min(range(len(ratios)), key=lambda j: abs(math.log(k0 / ratios[j] / m)))
                     for m in measured]
            if len(set(gears)) != len(gears) or gears != sorted(gears):
                continue
            ks = sorted(m * ratios[g] for m, g in zip(measured, gears))
            k = ks[len(ks) // 2]
            err = max(abs(k / ratios[g] - m) / m for m, g in zip(measured, gears))
            if best is None or err < best["error"]:
                best = {"gearbox": key, "gears": [g + 1 for g in gears], "k": k, "error": err}
        if best and best["error"] <= 0.03:
            out.append(best)
    out.sort(key=lambda b: b["error"])
    return out


def speed_check(k: float, car: Dict[str, Any]) -> Dict[str, Any]:
    """Compare the measured factor k (km/h per 1000 rpm times the gear ratio) with the final
    drive and tyres: the final drive they imply, and how far the logged speed is off when
    both are known (a wrong c_vs_fac, other tyres or a wrong final drive)."""
    eff = car if "_state" in car else effective(car)
    circ = circumference(eff)
    out: Dict[str, Any] = {}
    if circ:
        implied = 60.0 * circ / k
        out["implied_final_drive"] = round(implied, 2)
        out["nearest_final_drive"] = min(FINAL_DRIVES, key=lambda f: abs(f - implied))
        if eff.get("final_drive"):
            out["speed_error"] = (k - 60.0 * circ / eff["final_drive"]) / (60.0 * circ / eff["final_drive"])
    return out


def ecu_gears(log, measured: Sequence[float]) -> Dict[float, Optional[int]]:
    """What the ECU itself calls each measured gear (the log channel Current Gear
    (Calculated)): the most common value in the rows of that gear."""
    from . import tplog

    gear_col = log.col("Current Gear (Calculated)")
    rpm, speed = log.col(tplog.RPM), log.col("Vehicle Speed")
    out: Dict[float, Optional[int]] = {}
    if gear_col is None or rpm is None or speed is None:
        return out
    for m in measured:
        counts: Dict[int, int] = {}
        for i in range(log.n):
            if tplog._ok(rpm[i]) and tplog._ok(speed[i]) and rpm[i] >= 1200 and speed[i] >= 15 \
                    and abs(speed[i] / rpm[i] * 1000.0 - m) <= 0.03 * m and tplog._ok(gear_col[i]):
                g = int(round(gear_col[i]))
                counts[g] = counts.get(g, 0) + 1
        out[m] = max(counts, key=counts.get) if counts else None
    return out


def calibrate(paths: Sequence[str], car: Dict[str, Any]) -> Dict[str, Any]:
    """Measure the speed per 1000 rpm in each gear from the logs and match it with the
    gearbox catalogue. Returns {"gears", "matches", "ecu", "logs", "samples"}."""
    from . import tplog

    values: List[float] = []
    used, loaded, steps = [], [], []
    for path in paths:
        try:
            log = tplog.load(path)
        except (OSError, tplog.LogError):
            continue
        ratios, step = steady_ratios(log)
        values += ratios
        if ratios:
            used.append(os.path.basename(path))
            loaded.append(log)
            steps.append(step)
    step = sorted(steps)[len(steps) // 2] if steps else 0.05
    gears = clusters(values, step)
    measured = [g["per_1000"] for g in gears]
    matches = match(measured)
    for m in matches:
        m.update(speed_check(m["k"], car))
    ecu: Dict[float, Optional[int]] = {}
    for log in loaded:
        for m, g in ecu_gears(log, measured).items():
            if g is not None and ecu.get(m) is None:
                ecu[m] = g
    return {"gears": gears, "matches": matches, "ecu": ecu, "logs": used,
            "seconds": round(len(values) * step, 1)}


def apply_calibration(folder: str, result: Dict[str, Any]) -> List[str]:
    """Turn a calibration into proposals for the owner; returns what was proposed (English
    field names) — nothing is confirmed without the owner."""
    car = load(folder)
    eff = effective(car)
    source = t("logs: {list}", list=", ".join(result["logs"]))
    proposed = []
    best = result["matches"][0] if result["matches"] else None
    if best:
        box = GEARBOXES[best["gearbox"]]
        per_1000 = [round(best["k"] / r, 2) for r in box["ratios"]]
        if per_1000 != car["per_1000"]:
            propose(folder, "per_1000", per_1000, source,
                    t("steady driving in gears {gears}; the other gears from the steps of {box}",
                      gears=", ".join(map(str, best["gears"])), box=box["name"]))
            proposed.append("per_1000")
        if eff["_state"]["gearbox"] != "confirmed":
            propose(folder, "gearbox", best["gearbox"], source,
                    t("the steps between the measured gears fit within {err} %",
                      err=f"{best['error'] * 100:.1f}"))
            proposed.append("gearbox")
        if eff["_state"]["final_drive"] != "confirmed" and best.get("nearest_final_drive"):
            propose(folder, "final_drive", best["nearest_final_drive"], source,
                    t("{fd} from the tyres, if the logged speed is right",
                      fd=f"{best['implied_final_drive']:g}"))
            proposed.append("final_drive")
    return proposed


def calibration_text(result: Dict[str, Any], car: Dict[str, Any]) -> List[str]:
    """The calibration for Claude and the window (translated)."""
    out = [t("Steady driving found: {s} s in {logs}.", s=result["seconds"],
             logs=", ".join(result["logs"]) or "—")]
    if not result["gears"]:
        out.append(t("Not enough steady driving to measure the gears. Ask the owner for a short "
                     "calibration drive: 5-10 s at a steady speed in each gear (on a public road "
                     "too, within the rules), then add the log."))
        return out
    out.append(t("Measured speed per 1000 rpm: {list}", list=", ".join(
        t("{v} km/h ({s} s)", v=g["per_1000"], s=g["seconds"]) for g in result["gears"])))
    if not result["matches"]:
        out.append(t("No gearbox of the catalogue fits the steps between these gears; ask the "
                     "owner which gearbox it is."))
        return out
    for m in result["matches"][:3]:
        box = GEARBOXES[m["gearbox"]]
        line = t("{box}: gears {gears}, within {err} %", box=box["name"],
                 gears=", ".join(map(str, m["gears"])), err=f"{m['error'] * 100:.1f}")
        if m.get("implied_final_drive"):
            line += "; " + t("with these tyres the final drive would be {fd}",
                             fd=m["implied_final_drive"])
        out.append("  " + line)
    best = result["matches"][0]
    err = best.get("speed_error")
    if err is not None and abs(err) > 0.03:
        out.append(t("The logged speed is {p} % off the final drive and tyres of the profile: "
                     "c_vs_fac (pulses per km), the tyres or the final drive is not what the "
                     "profile says. Everything computed from the speed is off by as much.",
                     p=f"{err * 100:+.1f}"))
    measured = [g["per_1000"] for g in result["gears"]]
    wrong = [(m, result["ecu"].get(m)) for m, ours in zip(measured, best["gears"])
             if result["ecu"].get(m) is not None and result["ecu"].get(m) != ours]
    if wrong:
        out.append(t("The ECU's own gear recognition (Current Gear (Calculated), id_gear__n_vs_cru) "
                     "disagrees: {list}. Maps by gear (id_n_max_mt__gear, boost or ignition by "
                     "gear) then use the wrong gear.",
                     list=", ".join(t("{v} km/h per 1000 rpm: ECU says {g}", v=m, g=g) for m, g in wrong)))
    return out
