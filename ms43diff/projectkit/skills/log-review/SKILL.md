---
name: log-review
description: Analyse an MS43 TunerPro log completely — every knock event, lean spike and protection flag with time, rpm and load — and chart it. Use whenever the owner gives a log or asks "what does the log say".
---

# Reviewing an MS43 log

Logs are TunerPro CSVs in `logs/`, added by the owner on the **Logs** screen of the window.
Each one is bound to the firmware that was in the car (`<log>.ms43log.json`). If a log in
`logs/` has no binding, or `log_list` says the bound firmware is missing or changed, ask the
owner which firmware was in the car before judging anything — a log only says something
about the firmware it was recorded on.

Start with the `ms43` tools — they read every row and need no Python:

- `log_list` — the logs, their firmware and the owner's note on the conditions;
- `log_info` — the conditions note, rate, gaps, empty and slow channels, **every** knock
  event, flags, fuel trims at their limits, implausible values, channels;
- `log_modes` — the log split by mode: idle segments, full-throttle pulls (gear from the car
  profile, rpm rate, knock, load/ignition/VANOS by rpm), the limiter, knock weighted by time
  for full throttle vs part load;
- `car_info` — the owner's car: gearbox, final drive, tyres, speed per 1000 rpm, where the
  speed comes from; `car_calibrate` when the speeds are not measured yet;
- `log_rows` — the rows themselves, for a time range and chosen channels (page through it);
- `log_map_hits` — the log laid over a map of its firmware: per cell the map value, rows
  spent there, knock detections and cylinders, retard rows, deepest retard, times. Default
  filters drop a cold engine, throttle transients and overrun; say which filters you used.
  "knock" = the correction got deeper (knock detected); "retard" also counts the slow
  recovery afterwards, which lands in cells where no knock happened;
- `log_map_hits` with `value_channel` — any channel averaged per cell (fuel trims: see
  `fuel-trims`);
- `log_compare` — two logs over the same map, BEFORE and AFTER a flash: knock gone, new
  knock, trims moved; only cells visited in both logs count;
- `log_show` — open the same view in the window for the owner (map, time range, a second
  log to compare).

For charts and deeper statistics use the bundled Python, never by reading the CSV into the
conversation (a 10-minute log is millions of tokens):

```
{python} tools/ms43log.py logs/RUN.csv              # channels, duration, rate, knock row count
{python} tools/ms43log.py logs/RUN.csv --events     # knock events (grouped) and flags
{python} tools/ms43log.py logs/RUN.csv --scatter    # rpm x ignition load, knock marked
{python} tools/ms43log.py logs/RUN.csv --plot "Engine Speed,Knock Correction Average" --out analysis/RUN_knock.png
```

For anything else write a script in `analysis/` that does `from ms43log import load`
(add `tools/` to `sys.path`), and look at the PNG charts you produce. Files in `analysis/`
whose name contains the log name (`RUN_*.png`, `RUN_*.md`) appear on the Logs screen next to
the log.

Before judging the log, know the conditions: if `log_info` says the note is not filled in,
ask where it was recorded, the fuel, what bothers the owner and what changed since the
previous log (the owner can fill it in on the Logs screen, Conditions).

Before judging the log, know what the firmware in the car changed against the stock (or the
previous) file: `firmware_diff` with the log's name as `a` or `b`.

## Checklist — go through all of it, every time

1. **The run itself.** Duration, sample rate (TunerPro gives about 20 Hz), rpm and load
   ranges, coolant and oil temperature, `Vehicle Speed` and `Current Gear (Calculated)`.
   - Check how often each channel really updates (`log_info`: slow channels) before computing
     anything from it — `Vehicle Speed` may change only once a second, so the gear or
     acceleration from it is step-wise. Take the gear from `log_modes` (car profile), and
     mind where the speed comes from: a sensor on the driven wheels does not show wheelspin.
   - Cold engine (coolant < 80 °C): no ignition or fuel conclusions.
   - Revving at standstill (Vehicle Speed 0) and throttle blips are transients: report
     them, but draw no map conclusions from them.
   - Sanity: flag channels that never change and physically impossible spikes (e.g. load
     far above what an NA M54 can reach, ~1000 mg/stk) as sensor or logging issues.
   - The `Full Load` flag can be set well below wide-open throttle — check pedal and
     throttle angle.
2. **Knock, per cylinder.** `Knock Correction Cyl 1…6` — a NEGATIVE value means the ECU
   pulled ignition on that cylinder. The retard is held and decays over several samples, so
   group consecutive negative rows into one **event** (`--events` does this): start–end
   time, rpm range, `Engine Load Ignition` range (the load the ignition maps use; confirm
   the axis with `read_map`), deepest value per cylinder, IAT, throttle. Look for patterns: one cylinder always (sensor/mechanical/
   injector), a band of rpm and load (map too aggressive there), high IAT (heat soak),
   tip-in transients (throttle rising fast).
3. **Ignition actually used.** `Ignition Angle Average` / `Cyl 1…6` against rpm and load,
   and `RON Adaptation Factor` — the ECU's fuel-quality adaptation. Do not guess what its
   numbers mean: ask `search_wiki "RON adaptation"` / `explain_value` first; a change during
   or between logs means the ECU is adapting to fuel or persistent knock.
4. **Fuel.** `Lambda Control 1/2` (closed loop on/off), `Short Term Fuel Trim Bank 1/2`,
   `Long Term Fuel Trim Additive/Multiplicative Bank 1/2`, `Fuel Injector Duty Cycle`
   (above ~85 % the injectors are near their limit). See the `fuel-trims` skill for what can
   and cannot be concluded without a wideband.
5. **Air.** `Intake Air Temperature`, `Mass Air Flow`, `Engine Load MAF`, `Manifold
   Pressure` (X001), `Atmospheric Pressure`.
6. **VANOS.** `VANOS Angle Intake/Exhaust`, `VANOS Ready/Active/Limp Home`.
7. **Flags.** `Engine Misfire`, `VANOS Limp Home`, `Flex Fuel Limp Home`, `Over Boost
   Protection`, `Check Engine Light`, `Torque Intervention *`, `Trailing Throttle Fuel Cut`.
   Any of them set → report it with times.
8. **Coverage.** Which rpm × load cells were actually visited — `log_map_hits` on the map
   in question. A map can only be judged where the log has steady, warm data.

## Charts

Make at least: rpm + throttle + load over time; knock correction per cylinder over time;
a scatter of rpm × `Engine Load Ignition` with knock events marked (`--scatter`); IAT and
coolant over time. Save them to
`analysis/` with the log name in the file name and mention the paths.

## Report

Lead with the problems (with times), then what is fine, then what to log next. Separate
facts from interpretations. If the log cannot answer a question (no wideband, not warm,
too short), say so plainly instead of guessing. Write the report to
`analysis/RUN_review.md` so it shows next to the log in the window, and offer `log_show`
on the most important map. Changes go through `change-request`.
