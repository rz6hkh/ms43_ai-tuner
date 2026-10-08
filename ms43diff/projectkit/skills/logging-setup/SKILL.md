---
name: logging-setup
description: How to record a useful MS43 log — first ask where (public road, closed road section, track, dyno); channels, sample rate, warm-up, duration, notes and naming; when a full-load or wideband log is needed instead. Use when the owner asks how to log, or when a log could not answer the question.
---

# Recording a useful log

**First ask where the session will be:** public road, closed road section, track or dyno.
On a public road plan part-load driving within the traffic rules only; full-load pulls
belong to a closed road section, a track or a dyno (`wot-pull`).

## The connection (from the MS4X Wiki: How to connect, TunerPro Data Logging)

- Check `car_info` first: the car, swaps and removed parts decide the connector and what
  the log can show.
- K+DCAN cable: on an OBD-II car before the E90 (E46, E39 from 2000, E53…) the OBD pins 7
  and 8 must be bridged — on a cable with a switch that is the position for the older cars.
  Swapped cars (an M54 in an E30, a round 20-pin connector) differ: ask how the cable is
  connected to the ECU's K-line. Wrong position = no connection.
- **Connect the logger before starting the engine** when the ADX is a high-speed one: the
  ECU refuses the baud-rate switch while the engine runs.
- An "Extended Log" ADX needs the MS4x extended logging feature in the firmware, and the ADX
  version must match the patchlist version the firmware was built with (e.g. v2.9).
  `search_wiki "Logger Definition"` lists them; ask the owner which ADX they use.
- Cheap cables may not reach the usual ~20–25 Hz; check the rate in `log_info` afterwards.
- Two ways to record: the program's own logger (Logs screen → Record with the cable: COM
  port, the ADX, Check the connection with the ignition on, then Start recording) or
  TunerPro. The own logger writes the CSV straight into `logs/` plus a raw exchange
  journal in `logs/raw/` — ask the owner for it when a connection fails. Only the owner
  starts and stops it; you never control the car or the logger.
- In TunerPro nothing is saved without pressing Record. TunerPro saves its own `.xdl`
  (raw packets): the owner adds it on the Logs screen as it is — the program decodes it
  with the ADX into a CSV in `logs/` and keeps the `.xdl` in `logs/raw/`. A CSV export
  works too.

## Before the drive

- The engine fully warm (coolant ≥ 80 °C, oil warm) before the part you want to judge.
- Logger started with the project ADX that matches the firmware in the car (a wrong ADX
  reads garbage at the right offsets).
- Fewer channels → more samples per second. Keep at least: Engine Speed, Vehicle Speed,
  gear, pedal, throttle, `Engine Load Ignition`, `Engine Load MAF`, Mass Air Flow, ignition
  angle per cylinder, knock correction per cylinder, IAT, coolant, oil temperature,
  lambda control, short- and long-term trims per bank, injector duty cycle, VANOS angles,
  the protection/limp flags, and a wideband channel once one is fitted.

## On the road — part load only, within the law

- 10–20 minutes. Steady cruise at different speeds and gears; hold a given rpm and throttle
  for 5–10 s at a time across 1500–4000 rpm. Avoid stop-and-go and standstill revving.
- No full-throttle pulls on a public road. Those belong to `wot-pull` (closed road section,
  track or dyno, a passenger at the laptop).

## Calibration drive (once per car, and after changing the gearbox, final drive or tyres)

If `car_info` has no measured speed per 1000 rpm: 5–10 s at a steady speed in each gear,
e.g. 2nd at 30, 3rd at 50, 4th at 70, 5th at 90 km/h — on a public road too, within the
rules. Then `car_calibrate`: it finds the gearbox by the steps between gears, checks the
final drive, the tyres and the logged speed (c_vs_fac), and proposes the values to the owner.

## Notes the owner should keep

After adding the log, the owner fills in **Conditions** on the Logs screen: where, fuel
(brand, RON, E-content), outside temperature, what bothers them, **what changed since the
previous log** ("nothing" is an answer too), a free note. It is shown by `log_list` and
`log_info`. Longer notes (anything that felt or sounded wrong and roughly when) go to
`analysis/NOTES_<log name>.md`.

## File names

`logs/YYYY-MM-DD_<what>.csv`, e.g. `2026-08-02_cruise.csv`, `2026-08-03_dyno_pulls.csv`.

## When this is not enough

- Full-load ignition or mixture → `wot-pull` (closed road section, track or dyno) with a
  wideband in the same run.
- A single cylinder knocking everywhere → check sensor, wiring, plugs, injector first.
