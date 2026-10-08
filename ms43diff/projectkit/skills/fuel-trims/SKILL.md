---
name: fuel-trims
description: Read MS43 fuel trims and lambda control correctly and know what cannot be concluded without a wideband sensor. Use for "is it lean/rich", "trims", "MAF scaling" or injector questions.
---

# Fuel trims and lambda control

The stock narrowband sensors only tell rich/lean around lambda 1. So:

- **Closed loop** (`Lambda Control 1/2` = 1, part load, warm engine): the ECU holds lambda 1
  and the trims show how far the base fuelling is off.
  - `Short Term Fuel Trim Bank 1/2` — the fast correction right now.
  - `Long Term Fuel Trim Multiplicative Bank 1/2` — learnt % error over load (e.g. MAF
    scaling, injector size, fuel pressure).
  - `Long Term Fuel Trim Additive Bank 1/2` — learnt error at small injection times
    (idle: vacuum leaks, injector dead time).
  - Both banks moving the same way → a common cause (MAF, fuel pressure, injectors in
    general). One bank only → something on that bank (leak, injector, sensor).
- **Open loop** (`Lambda Control` = 0, full load, cold start): trims do not apply and the
  narrowband tells you nothing about the real mixture. **Without a wideband, never claim a
  full-load AFR.** Say it cannot be known and plan a wideband log.

## Sign and limits

`Short Term Fuel Trim` > 0 means the ECU **adds** fuel (the base mixture was lean), < 0 it
takes fuel away (rich). The limits are the firmware's `c_lam_max` / `c_lam_min` — read them
with `get_param` in the firmware the log was recorded on; a trim that sits at a limit (in
the log a little inside it, e.g. +27.73 / −28.12 for ±28 %, because of the 0.39 % step) is
pinned: report the times, it means the ECU cannot correct further.

## Trims per map cell

`log_map_hits` with `value_channel` (e.g. `Short Term Fuel Trim Bank 1`) averages the trim
per cell of a fuelling map; the `closed_loop` filter is added by default, so open-loop rows
do not dilute it. Check both banks and the long-term trims the same way, and look at the
row count per cell before trusting a mean. `log_compare` with the same `value_channel`
shows whether a change moved the trims.

Long-term trims are learnt and survive a flash; after a fuelling change they need driving
time to settle (or a reset of the adaptations with MS4x Flasher, which the owner decides).
Judge long-term trims only from a log where they had time to settle, and say so.

## Faults before maps

- A short-term trim pinned at one value or beyond about ±25 %, or banks differing by more
  than ~10 % at idle → report it as a fault to check (sensor, leak, injector, logging) and
  change no map.
- `Air Fuel Ratio Target` is the ECU's target, not a measurement.

## Rules of thumb (state them as such)

- Trims within about ±5 % are normal; ±10 % and more points to a real fuelling error.
- Additive trims large at idle with normal multiplicative ones → suspect a vacuum leak.
- `Fuel Injector Duty Cycle` above ~85 % at full load → the injectors are at their limit.

## Changing fuelling

Fuel maps, MAF calibration (`id_maf_tab…`) and injector constants affect everything else.
Propose them only after trims are understood across the whole load range, as small %
changes (`op: "mul"`), and say what the next log must show. Leaner full-load mixture is a
**red** change and needs wideband evidence.
