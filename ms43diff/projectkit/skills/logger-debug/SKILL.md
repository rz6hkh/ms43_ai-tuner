---
name: logger-debug
description: Help the owner get the window's own logger (K+DCAN cable, DS2) talking to the ECU, live, next to the car. Use when "Check the connection" or a recording fails, the connection keeps dropping, or the owner asks which ADX to use.
---

# Getting the logger to talk to the ECU

The owner is at the car; go one step at a time ("do X, tell me what you see"). You only read:
the owner presses "Check the connection" / "Start recording" on the Logs screen.

## First, the facts — never assume the car

1. `car_info` — which car this project is (the owner may have several cars, one project each).
2. `logger_info` — the chosen ADX (0B 03 standard or 0B B0 extended, fast rate or not), whether
   the firmware in the window supports it, the ADX pack and the suggested ADX, and the last
   "Check the connection": ident, every step, the mode, the journal file.
3. If the firmware in the window may not be what is in the car, ask. The ident the ECU sends is
   shown by `logger_info`; compare it with the owner's notes.

## Reading the result

"Check the connection" runs read-only steps: ident at 9600, the ADX's data request at 9600, then
the fast rate. A DS2 reply is `12, length, status, data, XOR`; the status byte:

| Status | Meaning | What to do |
|---|---|---|
| A0 | OK | — |
| A1 | busy | the program asks again |
| A2 on the baud switch `12 08 91 …` | the ECU refuses the fast rate: the **engine runs** | ignition on, engine off, connect, then start; or record at 9600 (the program does it by itself), or the *Baudrate Switch Engine Stopped Bypass* patch |
| B0 / FF on the data request | the firmware does not know the request: an **extended ADX (0B B0) without the DS2 Logging Feature Enhancement patch** (or MS43X) | use the standard ADX (0B 03); the patch is a code change: full 512 KB image, backup first |
| no reply at all, no echo | physics: cable power (12 V), K-line pin, cable mode switch, port busy (TunerPro, INPA) | check one by one |
| echo but no reply | the K-line does not reach the ECU (swaps: own diagnostic connector, check the wiring) | ask how the cable is wired; never guess a pin |

The modes a recording uses, chosen automatically: **fast** (the ADX as it is), **slow** (the
same request at 9600, when the fast rate is refused), **standard** (the 0B 03 ADX of the pack,
when the extended request is unknown). A refusal stops the recording with the reason; only
silence reconnects.

## The ADX

- Extended ADX files (0B B0) and the MS43X one come from the MS4X Wiki: the owner downloads the
  pack on the Logs screen ("Download the ADX pack"). The MS4X Wiki has **no standard 0B 03 ADX**;
  the program has its own (`MS43_Standard_0B03_AI-Tuner.adx`): engine speed, vehicle speed,
  coolant, lambda integrators per bank are certain; channels marked "(?)" are hypotheses from
  one drive — say so when you use them. A 0B 03 ADX put into the pack folder takes precedence.
- A raw recording `{"t", "hex"}` per line (`.jsonl`) can be added on the Logs screen like a log;
  it is decoded with the chosen ADX or the standard one.
- The ADX must match the firmware: X001 → the MS43X001 logging ADX; a stock 0069/0066/0056 with
  the logging patch → "Extended Log v2.9" for the engine; without the patch → a 0B 03 ADX.

## Journals

`logs/raw/test_<time>.jsonl` (connection checks) and `logs/raw/<time>.jsonl` (recordings): one
JSON per line — `t`, `dir` (tx/rx/info/error), `baud`, `hex`, `text`. Read them with the bundled
Python if the owner asks for details; quote the bytes when you explain.

## Never

- Never tell the owner to send anything to the ECU by hand; the logger sends only the ADX's
  connect / monitor / disconnect commands and the read-only ident.
- Never coach driving while logging; plan before, analyse after (`logging-setup`).
