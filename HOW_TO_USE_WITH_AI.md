# ms43diff — how to use it, and how to connect an AI

Plain steps.

This program reads your MS43 firmware and shows, in plain language, what each
setting is and does. It can also hand all of that to an AI so you can *ask*
questions and get answers grounded in your real firmware and in the MS4X Wiki
reference.

The program **never writes to the firmware**. It only shows and explains. You
make edits yourself in TunerPro.

---

## Part 1. Just look at the firmware (no AI)

1. Run `ms43diff-gui.exe` (double‑click).
2. **Browse** tab: pick your XDF file and BIN file, click **Find**.
   * Search in plain language.
   * Click a row → the bottom panel shows what the parameter is, its value from
     your firmware, and the MS4X Wiki article about it.
   * Double‑click a map → a colour table (red = raised, blue = lowered).
3. **Compare** tab: two BINs of the same version → see what was changed.
4. **Reference** tab: the whole MS4X Wiki offline, with search and a list of
   safety warnings.

No internet needed — the reference is inside the program. (First time, if the
reference is empty, use **Reference → Update from site**; that needs access to
ms4x.net, possibly via VPN.)

---

## Part 2. Connect an AI

Idea: the AI does not hold your whole firmware "in its head" — it asks the
program for a value or a wiki article whenever it needs one. So it never forgets
and never runs out of context.

### If you use Claude Desktop

The MCP config file is `%APPDATA%\Claude\claude_desktop_config.json`.
Add an `ms43` server under `mcpServers` (keep everything else in the file):

```json
{
  "mcpServers": {
    "ms43": {
      "command": "D:\\ms43diff\\dist\\ms43diff-mcp.exe",
      "args": [
        "-x", "C:\\path\\to\\Siemens_MS43_430069_512K.xdf",
        "-b", "C:\\path\\to\\your_firmware.bin"
      ]
    }
  }
}
```

Then: fully quit Claude Desktop, start it again, and when it asks whether to
trust the `ms43` server — approve it. Check with `/mcp` in a chat: `ms43` should
be **connected**.

### If you use Claude Code (CLI)

One command in its terminal:

```
claude mcp add ms43 -- "D:\ms43diff\dist\ms43diff-mcp.exe" -x "C:\path\to\def.xdf" -b "C:\path\to\firmware.bin"
```

Restart the session; check with `/mcp`.

### Point it at a different firmware

Change the `-x` / `-b` paths (in the JSON or the command) and restart the client.

---

## Part 3. How to ask

Write normally — the AI pulls the data it needs:

* "Show the ignition map ip_iga_ron98_pl__n__maf."
* "What is c_conf_cat and what does value 4 mean?"
* "I want to remove the catalytic converters — what to change and what matters?"
* "Search the reference for boost and lean‑wall."
* "Any warnings about the cooling fan?"
* "Compare the rev limit in my firmware with stock — is it too high?"

The AI answers from **your** firmware and the reference, not from memory. If it
doesn't know something, it asks the program again.

---

## Important (so you don't kill the engine)

* The program and the AI **never write** to the firmware — read and advise only.
  You edit in TunerPro.
* After editing in TunerPro, recompute the checksums (`cal_cks`,
  `cal_mon_cks`), or the ECU goes into limp mode.
* An AI is an assistant, not a guarantee. On important changes (ignition,
  fuelling, boost) cross‑check with the reference and with logs.
* Make sure the firmware software version matches the XDF — the program warns
  if it doesn't (wrong addresses otherwise).
