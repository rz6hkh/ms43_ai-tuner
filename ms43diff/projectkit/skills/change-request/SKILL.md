---
name: change-request
description: Turn findings into a safe firmware draft through the ms43 MCP edit tools and hand it to the owner in the window. Use whenever a change to the firmware is about to be proposed.
---

# Proposing firmware changes

1. **Read before you write.** `firmware_info` (is this the right file and version?),
   `get_param` / `read_map` for the current values, and the wiki (`search_wiki`,
   `explain_value`, `cautions`) for anything not obvious.
2. **One topic per draft** (e.g. "pull 1° out of the knock band at 2000–2200 rpm"). Check
   `edit_list` first; remove leftovers the owner did not ask for.
3. **Smallest change that answers the evidence.** Prefer `region` with axis values that are
   breakpoints; `op: "add"` for degrees, `op: "mul"` for % fuel changes.
4. **`reason` is mandatory and specific:** the log, times/cells, what was seen, what you
   expect, what to check in the next log. It goes into the change log next to the new
   `.bin`. When the change rests on a log, pass `evidence_log` and cite the cells from
   `log_map_hits`. Propose the change for the firmware the log was recorded on (or its
   direct successor the owner confirms); an edit of another firmware citing the log is
   marked as a risk the owner must confirm.
5. **Read the reply.** It shows what really lands after rounding, field limits, refusals
   and risks. Fix refused changes instead of retrying blindly.
6. **Red changes** (more advance, higher limits, knock control, full-load mixture,
   protections off, shared axes) need the owner's typed confirmation — explain the risk to
   them in plain words before they press anything.
7. **`edit_show`** opens the draft in the window. Tell the owner what to look at; the owner
   creates `name_vN.bin` and flashes it with MS4X Flasher (checksums are fixed there).
   Patches change program code, so the owner must flash the full 512 KB image in MS4X
   Flasher (a calibration-only flash would apply half of the patch); map and constant
   changes need only the calibration. The window and the change log say which.
   Before the very first flash, make sure the owner has a full 512 KB read of the ECU
   (MS4x Flasher → Read, Full) as a backup. Keep a battery charger connected while
   flashing and never switch off the flasher's voltage check.
8. **Keep the previous version** for rollback and ask for a new log after flashing, in the
   same conditions. The ECU keeps its learnt adaptations (long-term fuel trims, knock / RON
   adaptation) across a flash; MS4x Flasher can reset them. Agree with the owner whether to
   reset them before the AFTER log, and note it in the log's note — otherwise the
   comparison mixes the new map with the old learning. Then `log_compare` the old and the new log on the changed map and
   report honestly whether the change did what the `reason` expected.
