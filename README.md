# ms43diff

> **Public edition.** Nothing derived from the MS4X Wiki is bundled here (no copy of the wiki, no glossary, no translations). The reference still works: the **Reference** tab → **Update from site** downloads it straight from ms4x.net. The core tool is unchanged.

**Read, compare and *understand* BMW Siemens MS43 firmware — and let an AI tune alongside you.**

<div align="center">

![Windows](https://img.shields.io/badge/Windows-.exe-0a7f3f)
![Python](https://img.shields.io/badge/Python-3.8%2B-blue)
![Dependencies](https://img.shields.io/badge/core%20deps-stdlib%20only-brightgreen)
![Original](https://img.shields.io/badge/original%20.bin-never%20modified-orange)
![MCP](https://img.shields.io/badge/AI-MCP%20server-8b5cf6)

</div>

Using it with an AI: [HOW_TO_USE_WITH_AI.md](HOW_TO_USE_WITH_AI.md)

---

## What is this

`ms43diff` opens the firmware of a BMW M52TU / M54 engine (Siemens MS43 ECU) through
a TunerPro `.xdf` definition and explains it in plain language: **what each setting is,
what it does, what changed between two files, and how not to blow up the engine.**

It's an analyst, not an editor. You still make your changes in TunerPro.
What it gives you is understanding:

* a cryptic name like `ip_iga_ron_98_pl_ivvt__n__maf` becomes
  *"ignition map, RON98, part load, with VANOS, axes rpm × airflow"*;
* every map is a **colour heat‑map**, so you see the *shape* of a tune, not a wall of numbers;
* a diff tells you *"rev limiter +224 rpm, VANOS opened up top, catalyst monitoring disabled"* —
  in words, with the relevant safety warnings attached.

Core runs on the **Python standard library only**. One double‑click on Windows, no install.

---

## ⭐ The killer feature: ask an AI about *your* firmware (MCP)

This is what makes `ms43diff` different from every other XDF viewer.

It ships an **MCP server** — a small program that hands your firmware data and the
tuning knowledge base to an AI assistant (Claude Desktop / Claude Code). You point it
at your `.xdf` + `.bin` once, and then you just **talk to your tune**:

> *"Show me the ignition map `ip_iga_ron98_pl__n__maf`."*
> *"What does `c_conf_cat = 4` mean, and what breaks if I change it?"*
> *"I'm removing the cats — what do I change and what matters?"*
> *"Compare the rev limit in my file with stock — is it too high?"*

The AI answers from **your actual firmware** and the reference — not from memory.

Why it beats pasting data into a chat: the knowledge lives **outside** the model's
context window. The assistant doesn't hold the whole firmware "in its head" and run
out of room — it *queries the server on demand*, so it never forgets that one parameter
three questions ago, no matter how long the conversation runs.

The server is **read‑only** — the AI can look, never write. Tools it exposes:

| Tool | What the AI gets |
|---|---|
| `firmware_info` | software version, XDF match check, size |
| `list_categories` / `list_params` | what's in the firmware, filtered by category or regex |
| `get_param` | one parameter: value in physical units, decoded name, description |
| `read_map` | a full table with its axes |
| `explain_value` | what a specific value means (e.g. `c_conf_cat = 4`) |
| `search_wiki` / `wiki_page` | the tuning reference, searched or a whole page |
| `cautions` | every safety warning tied to a parameter |

Setup for Claude Desktop & Claude Code: **[HOW_TO_USE_WITH_AI.md](HOW_TO_USE_WITH_AI.md)**.

---

## The window (GUI)

`ms43diff-gui.exe` — one window, seven tabs. Files are picked through normal Open dialogs
and remembered between runs. Long jobs run in the background, so the window never freezes.

### Compare
Two `.bin` files of the same software version against one XDF. You get a table of every
changed parameter: old value → new value in physical units, the delta, and a decoded name.
Filter box on top, toggles for axis tables and checksums.

* **Double‑click a row** → the map opens in its own window as a colour heat‑map, changed
  cells highlighted. From there: view as text or save that single map to PDF.
* The bottom panel explains the selected parameter: what it is, what its values mean,
  and the warnings from the reference.
* Save the whole diff as **HTML, CSV or PDF**.

### Different versions
Same idea, but each firmware has its *own* XDF (say, stock 430069 vs. a custom build).
Parameters are matched by name; you see what exists in both, what's only on one side,
and how the values differ.

### Transfer plan
You tuned version A and want the same edits on version B. Give it A‑stock, your A‑tune,
and the B target — it works out *your* edits (tune minus stock) and tells you, per
parameter, how to carry each one over:

* **safe by bytes** — identical layout, copy 1:1;
* **safe by name** — same parameter, move the value by hand;
* **warning** — something differs (size, scaling, axes), and it says exactly what.

Double‑click any row for the details: what matched, what didn't. Unmatched parameters
can be mapped by hand — a picker suggests look‑alike names and maps of the same size.
**It only produces the plan, never writes.** Export to HTML or CSV.

### Patches
Load the community Patchlist XDF and your firmware — see which patches are applied,
which aren't, and which are only partly there.

### Browse
Search one firmware by name or by meaning ("rev limit", "knock", "lambda") and see the
current value next to the reference text for that parameter.

### VE dial‑in (wideband)
Feed it a CSV log from a wideband O2 sensor. It works out how far the real mixture was
from target in each cell of the VE (volumetric efficiency) map and proposes a correction.
You set the target lambda, minimum samples per cell, max correction %, and sensor lag;
there's a column mapper for logs from different loggers.

It also **reviews the run**: low coverage, too few samples, suspicious data — you get
told when the numbers can't be trusted. Cells with too little data are left alone.
Output: an HTML report and, if you confirm, a **new** `.bin` copy with the corrected map
(your original file is never touched; checksums are not recalculated — do that in TunerPro).

### Reference
The tuning wiki, offline and searchable, plus a **"All warnings"** list — every caution
in one place. Hit **Update from site** to download or refresh it from ms4x.net.

### Small things that matter
* **Ctrl+C** or right‑click copies a parameter name from any table (or the whole row).
* Errors go to a log file; **Show log** in the status bar opens it. Nothing fails silently.

---

## Command line

Everything the window does, the CLI does too:

```bash
python -m ms43diff diff A.bin B.bin -x def.xdf --html out.html --pdf out.pdf
python -m ms43diff show  -x def.xdf -b fw.bin  "^ip_iga_ron_98" -c tune.bin
python -m ms43diff find  -x def.xdf "rev limit" -b fw.bin
python -m ms43diff xdiff A.bin B.bin -A xdfA.xdf -B xdfB.xdf        # different versions
python -m ms43diff port  stock.bin tune.bin target.bin -A a.xdf -B b.xdf   # transfer plan
python -m ms43diff vetune log.csv -x def.xdf -b fw.bin -m ip_map_ve_1__map__n
python -m ms43diff mcp   -x def.xdf -b fw.bin                       # AI server
```

Also: `list`, `dump` (whole firmware → CSV), `multi`, `patches`, `info`, `wiki`.

---

## Install

**Windows, no Python needed** — grab `ms43diff-gui.exe` (and `ms43diff-mcp.exe` for the AI
server) from the [Releases](../../releases) page and double‑click.

**From source:**

```bash
git clone <this repo>
cd ms43diff
python gui_main.py                  # the window
python -m ms43diff --help           # the CLI
```

Only `reportlab` is an optional extra, needed solely for PDF export.

You bring your own `.xdf` and `.bin` — none are included.

---

## How it works (short)

* **Addressing.** The 512K XDF declares `BASEOFFSET 0x70000` — calibration is the last
  64 KB. Offsets resolve automatically. Sanity‑checked on a stock E39 M54B30:
  `c_gr_rax_sp` @ `0x706A2` = `EE 02` → little‑endian `0x02EE` = 750 → ×0.003906 = **2.93**
  (the E39 530i final drive).
* **Data format.** `mmedtypeflags` bit `0x01` = signed, `0x02` = little‑endian; the physical
  value comes from the `<MATH>` formula, parsed by a small *safe* evaluator (no `eval` on
  file data).
* **Software‑version guard.** The `430069.DAT`‑style header string is read; the tool warns
  if the firmware doesn't match the XDF.

---

## Build & CI

```bash
python -m pip install pyinstaller reportlab
python selftest.py             # unit checks, no firmware needed
python build_exe.py            # → dist/ms43diff-gui.exe + dist/ms43diff-mcp.exe
```

GitHub Actions runs the self‑test and builds both Windows executables on every `v*` tag,
then attaches them to the release (`.github/workflows/build.yml`).

---

## Safety

Modifying engine calibrations affects reliability and emissions compliance, and in many
countries is not legal for road use.

* Your original `.bin` is **never modified**. The only thing that writes a firmware file is
  VE dial‑in, and it always writes a *new copy*, after a confirmation.
* Checksums are **never recalculated** — do that in TunerPro before flashing.
* The MCP server is read‑only.

Verify changes with logs, not by ear. **Use at your own risk.**

---

## Credits

The tuning reference comes from the [MS4X Wiki](https://www.ms4x.net) — copyright belongs
to its authors. Huge thanks to the MS4x community. If you rely on the site, the authors ask
for a small donation (see their main page).
