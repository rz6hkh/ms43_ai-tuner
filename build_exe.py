#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Building the Windows .exe files.

    python -m pip install pyinstaller reportlab
    python build_exe.py

Output in the dist folder:
    ms43-ai-tuner.exe     — the window version (double-click to start)
    ms43-ai-tuner-mcp.exe     — the MCP server for an AI assistant (started by the client)
    mcp-add.bat          — connect the MCP server to Claude Desktop
    mcp-remove.bat       — disconnect it
    ms43-ai-tuner-windows.zip — all of the above plus the README files

Each .exe is a single file, no Python needed on the target machine.
reportlab is bundled whole with --collect-all, otherwise its data/fonts are
missing from the .exe and PDF export fails.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys

# On a clean Windows / CI the default stdout encoding is cp1252; force UTF-8.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass

ROOT = os.path.dirname(os.path.abspath(__file__))

COMMON = [
    "--onefile",
    "--clean",
    "--noconfirm",
    "--distpath", os.path.join(ROOT, "dist"),
    "--workpath", os.path.join(ROOT, "build"),
    "--specpath", os.path.join(ROOT, "build"),
    # dictionaries and parsers are ordinary package modules, but list them
    # explicitly so PyInstaller does not lose them while analysing imports
    "--hidden-import", "ms43diff.ru",
    "--hidden-import", "ms43diff.report",
    "--hidden-import", "ms43diff.crossdiff",
    "--hidden-import", "ms43diff.gui",
    "--hidden-import", "ms43diff.vetune",
    "--hidden-import", "ms43diff.wikicache",
    "--hidden-import", "ms43diff.wikitrans",
    "--hidden-import", "ms43diff.keywords",
    "--hidden-import", "ms43diff.heatmap",
    "--hidden-import", "ms43diff.mcpserver",
    "--hidden-import", "ms43diff.pdfreport",
    "--hidden-import", "ms43diff.i18n",
    "--hidden-import", "ms43diff.locale_ru",
    "--hidden-import", "ms43diff.names",
    "--hidden-import", "ms43diff.mcpinstall",
    "--hidden-import", "ms43diff.applog",
    "--hidden-import", "ms43diff.webui",
    "--hidden-import", "ms43diff.webui.server",
    "--hidden-import", "ms43diff.webui.dialogs",
    "--hidden-import", "ms43diff.webui.launcher",
    # the page itself (HTML/CSS/JS) travels inside the .exe
    "--add-data", os.path.join(ROOT, "ms43diff", "webui", "static") + os.pathsep
    + "ms43diff/webui/static",
    "--paths", ROOT,
    # keep the build lean.
    # PIL is NOT excluded: excluding it conflicts with --collect-all reportlab
    # and the reportlab fonts go missing — PDF export then fails silently.
    "--exclude-module", "numpy",
    "--exclude-module", "pytest",
    "--exclude-module", "matplotlib",
]

# The offline MS4X Wiki copy is bundled ONLY if it exists locally. It is not in
# the repository (third-party content), so the GitHub Actions release is built
# without it — the public .exe does not redistribute someone else's content.
# Users download the reference with the "Update from site" button.
_WIKIDATA = os.path.join(ROOT, "ms43diff", "wikidata")
if os.path.isdir(_WIKIDATA) and os.listdir(_WIKIDATA):
    COMMON += ["--add-data", _WIKIDATA + os.pathsep + "ms43diff/wikidata"]
    print("MS4X Wiki reference found locally — bundling it into the .exe.")
else:
    print("No wikidata reference — building without it (downloaded in the app).")

# the window needs reportlab for PDF; bundle it whole so the fonts come along
GUI_EXTRA = ["--collect-all", "reportlab"]


def build(entry: str, name: str, windowed: bool, extra=None) -> str:
    args = [sys.executable, "-m", "PyInstaller", *COMMON, *(extra or []),
            "--name", name]
    args.append("--windowed" if windowed else "--console")
    args.append(os.path.join(ROOT, entry))
    print("\n" + "=" * 70)
    print(f"Building {name}.exe from {entry}")
    print("=" * 70)
    result = subprocess.run(args, cwd=ROOT)
    if result.returncode != 0:
        raise SystemExit(f"PyInstaller failed while building {name}")
    return os.path.join(ROOT, "dist", name + ".exe")


def package(exes) -> list:
    """Copy the .bat helpers next to the .exe files and zip everything."""
    import zipfile

    dist = os.path.join(ROOT, "dist")
    extras = []
    for name in ("mcp-add.bat", "mcp-remove.bat"):
        target = os.path.join(dist, name)
        shutil.copy2(os.path.join(ROOT, name), target)
        extras.append(target)
    archive = os.path.join(dist, "ms43-ai-tuner-windows.zip")
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as zf:
        for path in list(exes) + extras:
            zf.write(path, os.path.basename(path))
        for doc in ("README.md", "README.ru.md"):   # the public edition has no README.ru.md
            if os.path.isfile(os.path.join(ROOT, doc)):
                zf.write(os.path.join(ROOT, doc), doc)
    return extras + [archive]


def main() -> int:
    try:
        import PyInstaller  # noqa: F401
    except ImportError:
        raise SystemExit(
            "PyInstaller is not installed. Run:\n"
            "    python -m pip install pyinstaller reportlab"
        )

    made = [
        # the window: with PDF (reportlab), no console
        build("gui_main.py", "ms43-ai-tuner", windowed=True, extra=GUI_EXTRA),
        # the MCP server talks over stdin/stdout, so --console only
        # (the client starts it hidden, no black window flashes)
        build("mcp_main.py", "ms43-ai-tuner-mcp", windowed=False),
    ]

    print("\n" + "=" * 70)
    made += package(made)
    print("Done. Files:")
    for path in made:
        size = os.path.getsize(path) / 1024 / 1024
        print(f"  {path}   ({size:.1f} MB)")
    print("=" * 70)
    print("Copy them anywhere — no Python is needed on the target machine.")

    # temporary build folders are not needed
    for folder in ("build",):
        shutil.rmtree(os.path.join(ROOT, folder), ignore_errors=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
