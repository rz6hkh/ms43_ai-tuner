---
name: wot-pull
description: Plan a full-throttle pull or another test run for logging on a closed road section, a track or a dyno — preconditions, the steps, what to log and when to abort. Use before judging full-load behaviour or when the owner plans such runs; for public-road logging see logging-setup.
---

# Planning a test run

**Only on a closed road section (closed to traffic, with permission), a track or a dyno, with
a passenger operating the laptop.** Ask the owner which of these it is and adapt the plan
(a dyno allows steady cells at any load; a closed section or a track limits the gear and the
length of a pull). On a public road there are no pulls — use `logging-setup`. Do not plan pulls while a recent log shows unexplained knock
(deeper than about −3°, or one cylinder repeatedly). Full-load mixture can only be judged
with a wideband logged in the same run. You plan the run
before it; you do not direct the driver during it. Write the plan into
`analysis/PLAN_<date>.md` so the passenger can follow it.

## Preconditions

- Coolant ≥ 80 °C and oil warm (`Oil Temperature`), the usual fuel, the logger running
  with the project ADX before the run starts.
- Note fuel, outside temperature and anything unusual in the plan file.

## A full-load pull

1. Choose the gear from the car's ratios and the length of the section (`car_info` gives the
   speed per 1000 rpm in each gear): the pull must end below the limiter well before the end
   of a closed section (on a short section often 2nd). If the ratios, final drive or tyres
   are not confirmed, ask — never assume a typical gearbox. Start steady at about 2000 rpm.
2. Throttle fully open in one smooth movement, hold to about 200 rpm below the limiter.
3. Lift, cool down for a minute before the next pull. Two or three pulls make a good log.

## Steady-state cells (for part-load ignition and trims)

Hold a given rpm and throttle for 5–10 s at a time across the range you want to judge —
on a dyno this is easy, on a track take what the corners give and mark it in the notes.

## Abort criteria (the passenger watches, the driver lifts)

- Knock correction on any cylinder deeper than about −3° during a pull.
- Coolant above ~110 °C, check engine light, misfire, VANOS limp home.
- Anything sounding or feeling wrong.

After the run: `log-review`.
