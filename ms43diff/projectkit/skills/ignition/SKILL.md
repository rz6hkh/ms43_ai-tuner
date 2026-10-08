---
name: ignition
description: Decide on MS43 ignition-map changes from knock evidence in logs — where advance can be added, where it must be removed, and how to propose it safely. Use for any "more timing / less knock / which ignition map" question.
---

# Ignition on MS43

Find the maps with `list_params` (category Ignition) and read them with `read_map` — names
differ between software versions (430069 vs MS43X001), so always take them from the XDF.
They follow the Siemens scheme, e.g. `ip_iga_ron_98_pl_ivvt__n__maf` = ignition angle,
RON 98, part load, VANOS active, rows engine speed, columns load. There are separate maps
for RON 98 and RON 91, part and full load, VANOS on and off; the ECU blends between the
RON maps by the `RON Adaptation Factor`. Ask the wiki (`search_wiki "ignition"`,
`cautions`) before touching a family of maps you have not read about.

## Removing advance — knock seen

- Knock correction (negative) **repeatedly** — at least 3 separate passes — in the same
  rpm × load cells, warm engine, normal IAT → take 0.75–1.5° out of exactly those cells (and
  their immediate neighbours) in the map that was active at that moment. Say why that map
  was active (`Part Load` / `Full Load` flags, pedal, VANOS state).
- A single pass, a transient, or a heat-soaked engine (IAT above ~55 °C) is reported and
  re-logged, not mapped.
- Knock on one cylinder only, everywhere → suspect a sensor, wiring, injector or mechanical
  issue first; do not "fix" it with the map.
- Knock only with high IAT or on tip-in → report it; a map change may be the wrong cure.

## Adding advance — only with evidence

All of these must hold for each cell you change:

1. Warm engine (coolant ≥ 80 °C), IAT up to about 45 °C (rule of thumb), the owner's
   usual fuel.
2. At least 3 separate passes and about 10 steady samples in that cell with **zero** knock
   correction on all cylinders.
3. Step of **+0.375° or +0.75°** (the MS43 ignition step is 0.375°), never more than +0.75°
   per draft. Next step only after a new log.
4. Not in cells where the neighbours already show knock.

More advance is a **red** change: the window asks the owner to type a confirmation. State
the gain you expect and the risk in the `reason`.
If a cylinder already shows unexplained knock, do not add advance anywhere until it is
understood.

## Proposing

Use `edit_propose` with `kind: "region"` and axis values (`y_from/y_to` = rpm,
`x_from/x_to` = load) that are breakpoints of the map; check the reply for rounding — the
ignition step on MS43 is 0.375°. Then `edit_list` and `edit_show`. One topic per draft.
