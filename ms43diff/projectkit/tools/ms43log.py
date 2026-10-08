# -*- coding: utf-8 -*-
"""
Load and inspect TunerPro data logs (CSV) from an MS43 ECU.

    python ms43log.py LOG.csv                    # channels, duration, rate, stuck channels
    python ms43log.py LOG.csv --events           # knock events (grouped) and protection flags
    python ms43log.py LOG.csv --rows             # the same, every row
    python ms43log.py LOG.csv --scatter          # rpm x ignition load, knock marked (PNG)
    python ms43log.py LOG.csv --plot "Engine Speed,Knock Correction Average"   # time series (PNG)

Charts go to analysis/<log name>_<what>.png unless --out is given.

As a library:
    from ms43log import load
    df = load("logs/run1.csv")        # pandas DataFrame, ON/OFF -> 1/0, time in seconds
    df.attrs["units"]                  # {"Coolant Temperature": "°C", ...}

TunerPro writes a title line ("TunerPro Engine data log recorded on ..."), then the header
(the first column is the row number), then the rows. Older logs may be cp1252.
Sign convention on MS43: a NEGATIVE "Knock Correction" means ignition was pulled.
"""

from __future__ import annotations

import argparse
import io
import os
import sys

import pandas as pd

KNOCK_PREFIX = "Knock Correction Cyl"


def _read_text(path: str) -> str:
    with open(path, "rb") as fh:
        raw = fh.read()
    for enc in ("utf-8-sig", "cp1251"):   # TunerPro writes ANSI; cp1251 keeps Cyrillic readable
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("latin-1")


def load(path: str) -> pd.DataFrame:
    """A TunerPro log as a DataFrame (numeric where possible)."""
    lines = _read_text(path).splitlines()
    start = 0
    while start < len(lines) and "," not in lines[start]:
        start += 1                       # skip the title line(s)
    df = pd.read_csv(io.StringIO("\n".join(lines[start:])), sep=",", skipinitialspace=True,
                     dtype=str)
    units = {}
    if len(df) and str(df.iloc[0, 0]).strip().lower().startswith("sample"):
        # the second header line holds the units: "Seconds", "Coolant Temperature (°C)"…
        for col, text in zip(df.columns, df.iloc[0]):
            if isinstance(text, str) and "(" in text and text.endswith(")"):
                units[str(col).strip()] = text[text.rfind("(") + 1:-1]
        df = df.iloc[1:].reset_index(drop=True)
    first = df.columns[0]
    if not str(first).strip() or str(first).startswith("Unnamed"):
        df = df.drop(columns=[first])    # TunerPro's row number
    # the unnamed column after the trailing comma goes; a named channel that is empty in
    # every row stays (and is listed), so scripts do not fail with a KeyError
    df = df[[c for c in df.columns if not (str(c).startswith("Unnamed") and df[c].isna().all())]]
    df.columns = [str(c).strip() for c in df.columns]
    for col in df.columns:
        series = df[col]
        if pd.api.types.is_numeric_dtype(series):
            continue
        text = series.dropna().astype(str).str.strip().str.upper()
        if len(text) and text.isin(["ON", "OFF"]).all():
            df[col] = series.astype(str).str.strip().str.upper().map({"ON": 1, "OFF": 0})
            continue
        number = pd.to_numeric(series, errors="coerce")
        if number.notna().sum() >= 0.9 * series.notna().sum():
            df[col] = number
    df = df.copy()                       # one block instead of a fragmented frame
    df.attrs["units"] = units
    df.attrs["empty"] = [c for c in df.columns if df[c].isna().all()]
    return df


LOAD_IGN = "Engine Load Ignition"           # the load the ignition maps use
FLAGS = ("Engine Misfire", "Engine Misfire Cylinder Cut", "VANOS Limp Home", "Flex Fuel Limp Home",
         "Over Boost Protection", "Engine Overheating Light", "Check Engine Light",
         "Engine Malfunction Light", "Torque Intervention AMT", "Torque Intervention ASR",
         "Torque Intervention Gear", "Torque Intervention Limit", "Torque Intervention MSR",
         "Trailing Throttle Fuel Cut")
CONTEXT = ("Time", "Engine Speed", "Vehicle Speed", "Current Gear (Calculated)",
           "Accelerator Pedal Position", "Throttle Body Position", LOAD_IGN, "Engine Load MAF",
           "Ignition Angle Average", "Intake Air Temperature", "Coolant Temperature")


def knock_columns(df: pd.DataFrame) -> list:
    return [c for c in df.columns if c.startswith(KNOCK_PREFIX)]


def _knock_mask(df: pd.DataFrame) -> pd.Series:
    mask = pd.Series(False, index=df.index)
    for col in knock_columns(df):
        mask |= df[col] < 0
    return mask


def knock_rows(df: pd.DataFrame) -> pd.DataFrame:
    """Every row with ignition pulled on any cylinder."""
    keep = [c for c in CONTEXT if c in df.columns] + knock_columns(df)
    return df.loc[_knock_mask(df), keep]


def knock_events(df: pd.DataFrame, gap: int = 2) -> pd.DataFrame:
    """Consecutive knock rows (allowing `gap` clean rows inside) grouped into events."""
    mask = _knock_mask(df)
    idx = list(df.index[mask])
    groups, current = [], []
    for i in idx:
        if current and i - current[-1] > gap + 1:
            groups.append(current)
            current = []
        current.append(i)
    if current:
        groups.append(current)
    out = []
    for g in groups:
        part = df.loc[g[0]:g[-1]]
        row = {"start": part["Time"].iloc[0] if "Time" in part else g[0],
               "end": part["Time"].iloc[-1] if "Time" in part else g[-1], "rows": len(g)}
        for col, name in (("Engine Speed", "rpm"), (LOAD_IGN, "load_ign"),
                          ("Throttle Body Position", "throttle"), ("Vehicle Speed", "speed")):
            if col in part:
                row[name] = f"{part[col].min():g}..{part[col].max():g}"
        if "Intake Air Temperature" in part:
            row["iat_max"] = part["Intake Air Temperature"].max()
        for col in knock_columns(df):
            deepest = part[col].min()
            if deepest < 0:
                row["cyl" + col.rsplit(" ", 1)[-1]] = deepest
        out.append(row)
    return pd.DataFrame(out)


def flag_rows(df: pd.DataFrame) -> pd.DataFrame:
    """Rows where any protection / limp / intervention flag is set."""
    flags = [c for c in FLAGS if c in df.columns]
    mask = pd.Series(False, index=df.index)
    for col in flags:
        mask |= df[col] > 0
    keep = [c for c in CONTEXT if c in df.columns] + flags
    return df.loc[mask, keep]


def stuck_channels(df: pd.DataFrame) -> list:
    """Numeric channels that never change (unplugged sensors, unused flags, logging issues)."""
    return [c for c in df.columns if pd.api.types.is_numeric_dtype(df[c]) and df[c].nunique() == 1]


def summary(df: pd.DataFrame) -> str:
    out = [f"rows: {len(df)}"]
    if "Time" in df.columns and len(df) > 1:
        dur = float(df["Time"].iloc[-1] - df["Time"].iloc[0])
        out.append(f"duration: {dur:.1f} s, rate: {len(df) / dur:.1f} Hz" if dur else "duration: 0 s")
    for col in ("Engine Speed", "Vehicle Speed", LOAD_IGN, "Coolant Temperature", "Oil Temperature",
                "Intake Air Temperature"):
        if col in df.columns:
            out.append(f"{col}: {df[col].min():g} .. {df[col].max():g}")
    if knock_columns(df):
        out.append(f"knock rows: {int(_knock_mask(df).sum())}, events: {len(knock_events(df))}")
    else:
        out.append("no knock channels in this log")
    out.append(f"rows with protection/intervention flags: {len(flag_rows(df))}")
    if df.attrs.get("empty"):
        out.append("EMPTY in every row (not logged or not decoded): " + ", ".join(df.attrs["empty"]))
    stuck = stuck_channels(df)
    if stuck:
        out.append("never change (check before trusting): " + ", ".join(stuck))
    out.append("channels: " + ", ".join(df.columns))
    return "\n".join(out)


def _out_path(log: str, what: str, out: str = "") -> str:
    if out:
        return out
    name = os.path.splitext(os.path.basename(log))[0]
    return os.path.join("analysis", f"{name}_{what}.png")


def plot(df: pd.DataFrame, channels: list, out: str) -> str:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    x = df["Time"] if "Time" in df.columns else df.index
    fig, axes = plt.subplots(len(channels), 1, figsize=(12, 2.2 * len(channels)), sharex=True)
    axes = [axes] if len(channels) == 1 else axes
    for ax, ch in zip(axes, channels):
        ax.plot(x, df[ch], linewidth=0.9)
        ax.set_ylabel(ch, fontsize=8)
        ax.grid(alpha=0.3)
    axes[-1].set_xlabel("Time, s")
    fig.tight_layout()
    os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
    fig.savefig(out, dpi=110)
    return out


def scatter(df: pd.DataFrame, out: str, x: str = "Engine Speed", y: str = LOAD_IGN) -> str:
    """rpm x load of every row; knock rows in red, sized by the deepest correction."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    mask = _knock_mask(df)
    fig, ax = plt.subplots(figsize=(10, 6))
    ax.scatter(df.loc[~mask, x], df.loc[~mask, y], s=6, alpha=0.4, label="no knock")
    if mask.any():
        depth = (-df.loc[mask, knock_columns(df)].min(axis=1)).clip(lower=0.5)
        ax.scatter(df.loc[mask, x], df.loc[mask, y], s=depth * 25, color="red", alpha=0.7,
                   label="knock (size = deepest retard)")
    ax.set_xlabel(x)
    ax.set_ylabel(y)
    ax.grid(alpha=0.3)
    ax.legend()
    fig.tight_layout()
    os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
    fig.savefig(out, dpi=110)
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[1])
    ap.add_argument("log")
    ap.add_argument("--events", action="store_true", help="knock events (grouped) and flag rows")
    ap.add_argument("--rows", action="store_true", help="every knock row")
    ap.add_argument("--scatter", action="store_true", help="rpm x ignition load, knock marked")
    ap.add_argument("--plot", help="comma-separated channel names (time series)")
    ap.add_argument("--out", default="", help="PNG path (default analysis/<log>_<what>.png)")
    args = ap.parse_args()
    df = load(args.log)
    with pd.option_context("display.max_rows", None, "display.max_columns", None,
                           "display.width", 250):
        if args.events:
            ev = knock_events(df)
            print(f"knock events: {len(ev)}")
            if len(ev):
                print(ev.to_string(index=False))
            fl = flag_rows(df)
            print(f"\nrows with protection/intervention flags: {len(fl)}")
            if len(fl):
                print(fl.to_string())
        elif args.rows:
            print(knock_rows(df).to_string())
        elif args.scatter:
            print(scatter(df, _out_path(args.log, "scatter", args.out)))
        elif args.plot:
            channels = [c.strip() for c in args.plot.split(",")]
            print(plot(df, channels, _out_path(args.log, "plot", args.out)))
        else:
            print(summary(df))
    return 0


if __name__ == "__main__":
    sys.exit(main())
