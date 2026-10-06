# ms43diff

> **Public edition.** The MS4X Wiki glossary and our Russian translations are not bundled here (they are derived from the community wiki). The reference still works: use **Reference → Update from site** in the app to download it from ms4x.net (English). The core tool is unchanged.

**Read, compare and *understand* BMW Siemens MS43 firmware — and let an AI tune alongside you.**

<div align="center">

![Windows](https://img.shields.io/badge/Windows-.exe-0a7f3f)
![Python](https://img.shields.io/badge/Python-3.8%2B-blue)
![Dependencies](https://img.shields.io/badge/core%20deps-stdlib%20only-brightgreen)
![Firmware](https://img.shields.io/badge/firmware-read--only-orange)
![MCP](https://img.shields.io/badge/AI-MCP%20server-8b5cf6)

</div>

Русская версия: [README.ru.md](README.ru.md) · Using with an AI: [HOW_TO_USE_WITH_AI.md](HOW_TO_USE_WITH_AI.md)

---

## What is this

`ms43diff` opens the firmware of a BMW M52TU / M54 engine (Siemens MS43 ECU) through
a TunerPro `.xdf` definition and explains it in plain language: **what each setting is,
what it does, what changed between two files, and how not to blow up the engine.**

It is a **read‑only analyst**, not an editor — you still make changes in TunerPro.
What it gives you is understanding:

* a cryptic name like `ip_iga_ron_98_pl_ivvt__n__maf` becomes
  *"ignition map, RON98, part load, with VANOS, axes rpm × airflow"*;
* every map is a **colour heat‑map**, so you see the *shape* of a tune, not a wall of numbers;
* a diff tells you *"rev limiter +224 rpm, VANOS opened up top, catalyst monitoring disabled"* —
  in words, with the relevant safety warnings attached.

Core runs on the **Python standard library only**. One Windows double‑click, no install.

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

Tools the server exposes: `firmware_info`, `list_categories`, `list_params`,
`get_param`, `read_map`, `explain_value`, `search_wiki`, `wiki_page`, `cautions`.

Full setup (Claude Desktop & Claude Code): **[HOW_TO_USE_WITH_AI.md](HOW_TO_USE_WITH_AI.md)**.

---

## Features

* 🔍 **Compare two firmwares** — by XDF parameters (converted to physical units) *and*
  byte‑by‑byte, so code/patch edits are flagged apart from map changes.
* 🌡️ **Readable maps** — one colour scheme everywhere (window, HTML, PDF): a diverging
  blue→grey→red scale for changes, sequential for values.
* 📚 **Offline tuning reference** — the community wiki is linked to each parameter:
  value meanings, "do this after changing", and safety warnings, right next to the value.
* 🔀 **Cross‑version compare & transfer plan** — between software versions (e.g. 430069 ↔
  a custom build): matches by name, marks what's safe to carry over 1:1 vs. by hand.
  Plan only — it never writes.
* 🎯 **VE‑map dial‑in from a wideband log** — computes a correction *and* reviews the run,
  warning you when the data can't be trusted.
* 🤖 **MCP server** — the AI integration above.
* 📄 **Export** — searchable HTML, CSV, JSON, Markdown, PDF (coloured maps included).
* 🇬🇧🇷🇺 Parameter explanations in English (original) and Russian.

---

## Install

**Windows, no Python needed** — grab `ms43diff-gui.exe` (and `ms43diff-mcp.exe` for the AI
server) from the [Releases](../../releases) page and double‑click.

**From source:**

```bash
git clone <this repo>
cd ms43diff
python -m ms43diff diff stock.bin tune.bin -x def.xdf --html report.html
```

Only `reportlab` is an optional extra, needed solely for PDF export.

---

## The window

`ms43diff-gui.exe` — seven tabs, files chosen through dialogs:

| Tab | What it does |
|---|---|
| **Compare** | two bins of the same version; double‑click a row → full colour map |
| **Different versions** | each bin its own XDF, matched by names |
| **Transfer plan** | plan for porting edits into another version (read‑only) |
| **Patches** | which community patches are applied |
| **Browse** | search a parameter, see its value and the reference beside it |
| **Dial‑in by wideband** | VE‑map correction from a log |
| **Reference** | the offline tuning wiki, searchable, with a warnings list |

Ctrl+C (or right‑click) copies a parameter name from any table. Errors go to a log file
with a **Show log** button, so nothing fails silently.

---

## Command line

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

## How it works (short)

* **Addressing.** The 512K XDF declares `BASEOFFSET 0x70000` — calibration is the last
  64 KB. Offsets resolve automatically. Sanity‑checked on a stock E39 M54B30:
  `c_gr_rax_sp` @ `0x706A2` = `EE 02` → little‑endian `0x02EE` = 750 → ×0.003906 = **2.93**
  (the E39 530i final drive).
* **Data format.** `mmedtypeflags` bit `0x01` = signed, `0x02` = little‑endian; physical
  value from the `<MATH>` formula, parsed by a small *safe* evaluator (no `eval` on file data).
* **Software‑version guard.** The `430069.DAT`‑style header string is read; the tool warns
  if the firmware doesn't match the XDF.

---

## Build & CI

```bash
python -m pip install pyinstaller reportlab
python build_exe.py            # → dist/ms43diff-gui.exe + dist/ms43diff-mcp.exe
```

GitHub Actions builds the Windows executables on every `v*` tag and attaches them to the
release (`.github/workflows/build.yml`).

---

## Safety

Modifying engine calibrations affects reliability and emissions compliance, and in many
countries is not legal for road use. This tool never writes to the firmware and never
recalculates checksums — do that in TunerPro. Verify changes with logs, not by ear.
**Use at your own risk.**

---

## Credits

Tuning guidance and the abbreviation glossary are based on the
[MS4X Wiki](https://www.ms4x.net) — copyright belongs to its authors. Huge thanks to the
MS4x community. If you rely on the site, the authors ask for a small donation (see their
main page).
