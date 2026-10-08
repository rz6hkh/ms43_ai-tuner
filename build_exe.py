#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Building the Windows .exe.

    python -m pip install pyinstaller reportlab
    python build_exe.py [--with-python]

Output in the dist folder:
    ms43-ai-tuner.exe          — the program (double-click to start); its
                                 window also runs the MCP server for Claude Code
    python/                    — (--with-python, Windows) an embeddable Python with
                                 pandas, numpy and matplotlib for Claude Code's log analysis
    ms43-ai-tuner-windows.zip  — the .exe, python/ and the README files

The .exe is a single file, no Python needed on the target machine.
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
    "--hidden-import", "ms43diff.vetune",
    "--hidden-import", "ms43diff.wikicache",
    "--hidden-import", "ms43diff.wikitrans",
    "--hidden-import", "ms43diff.keywords",
    "--hidden-import", "ms43diff.heatmap",
    "--hidden-import", "ms43diff.mcpserver",
    "--hidden-import", "ms43diff.mcphttp",
    "--hidden-import", "ms43diff.pdfreport",
    "--hidden-import", "ms43diff.i18n",
    "--hidden-import", "ms43diff.locale_ru",
    "--hidden-import", "ms43diff.names",
    "--hidden-import", "ms43diff.applog",
    "--hidden-import", "ms43diff.webui",
    "--hidden-import", "ms43diff.webui.server",
    "--hidden-import", "ms43diff.webui.dialogs",
    "--hidden-import", "ms43diff.webui.launcher",
    "--hidden-import", "ms43diff.webui.modes",
    "--hidden-import", "ms43diff.webui.ai",
    "--hidden-import", "ms43diff.edits",
    "--hidden-import", "ms43diff.mcpedits",
    "--hidden-import", "ms43diff.mcplogs",
    "--hidden-import", "ms43diff.tplog",
    "--hidden-import", "ms43diff.adx",
    "--hidden-import", "ms43diff.ds2logger",
    "--hidden-import", "ms43diff.car",
    "--hidden-import", "serial",
    "--hidden-import", "serial.tools.list_ports",
    "--hidden-import", "ms43diff.project",
    # the page itself (HTML/CSS/JS) travels inside the .exe
    "--add-data", os.path.join(ROOT, "ms43diff", "webui", "static") + os.pathsep
    + "ms43diff/webui/static",
    # the tuning project templates (CLAUDE.md, skills, the log loader)
    "--add-data", os.path.join(ROOT, "ms43diff", "projectkit") + os.pathsep
    + "ms43diff/projectkit",
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


PY_VERSION = "3.12.10"
PY_PACKAGES = ["pandas", "numpy", "matplotlib"]


def bundle_python() -> str:
    """dist/python: the embeddable CPython for Windows plus the analysis packages."""
    import urllib.request
    import zipfile

    target = os.path.join(ROOT, "dist", "python")
    shutil.rmtree(target, ignore_errors=True)
    os.makedirs(target)
    work = os.path.join(ROOT, "build")
    os.makedirs(work, exist_ok=True)
    url = f"https://www.python.org/ftp/python/{PY_VERSION}/python-{PY_VERSION}-embed-amd64.zip"
    archive = os.path.join(work, "python-embed.zip")
    print(f"Downloading {url}")
    urllib.request.urlretrieve(url, archive)
    with zipfile.ZipFile(archive) as zf:
        zf.extractall(target)
    # the embeddable build ignores site-packages until "import site" is enabled
    for name in os.listdir(target):
        if name.endswith("._pth"):
            path = os.path.join(target, name)
            lines = open(path, encoding="utf-8").read().splitlines()
            lines = [("import site" if line.strip() == "#import site" else line) for line in lines]
            if "Lib\\site-packages" not in lines:
                lines.insert(len(lines) - 1, "Lib\\site-packages")
            open(path, "w", encoding="utf-8").write("\n".join(lines) + "\n")
    exe = os.path.join(target, "python.exe")
    get_pip = os.path.join(work, "get-pip.py")
    urllib.request.urlretrieve("https://bootstrap.pypa.io/get-pip.py", get_pip)
    for cmd in ([exe, get_pip, "--no-warn-script-location"],
                [exe, "-m", "pip", "install", "--no-warn-script-location", "--no-cache-dir",
                 *PY_PACKAGES],
                [exe, "-c", "import pandas, numpy, matplotlib; print('bundled python ok')"]):
        if subprocess.run(cmd, cwd=target).returncode != 0:
            raise SystemExit("Bundling Python failed: " + " ".join(cmd[1:3]))
    return target


def package(exes, python_dir: str = "") -> list:
    """Zip the .exe (and the bundled Python) with the README files."""
    import zipfile

    archive = os.path.join(ROOT, "dist", "ms43-ai-tuner-windows.zip")
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as zf:
        for path in exes:
            zf.write(path, os.path.basename(path))
        if python_dir:
            base = os.path.dirname(python_dir)
            for folder, _dirs, files in os.walk(python_dir):
                for name in files:
                    full = os.path.join(folder, name)
                    zf.write(full, os.path.relpath(full, base))
        for doc in ("README.md", "README.ru.md"):   # the public edition has no README.ru.md
            if os.path.isfile(os.path.join(ROOT, doc)):
                zf.write(os.path.join(ROOT, doc), doc)
    return [archive]


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
    ]

    python_dir = ""
    if "--with-python" in sys.argv:
        if os.name != "nt":
            raise SystemExit("--with-python bundles the Windows embeddable Python: build on Windows.")
        python_dir = bundle_python()

    print("\n" + "=" * 70)
    made += package(made, python_dir)
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
