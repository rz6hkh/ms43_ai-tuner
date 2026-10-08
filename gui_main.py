#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Window version entry point (PyInstaller builds it into ms43-ai-tuner.exe).

    ms43-ai-tuner.exe [--lang en|ru]

The interface is an HTML page in an Edge app window (ms43diff.webui).

Hidden check modes for a built .exe:
    ms43-ai-tuner.exe --check out.json   (what is bundled: wiki pages, project kit, Python)
    ms43-ai-tuner.exe --selftest -x def.xdf -a A.bin -b B.bin
saves HTML/CSV/PDF into the temp folder, writes the result to the log and
exits. It catches errors (e.g. in PDF export) that a normal window hides.
"""

import sys


def _selftest(argv) -> int:
    import os
    import tempfile
    import traceback

    from ms43diff import report
    from ms43diff.applog import log_write
    from ms43diff.binfile import BinFile
    from ms43diff.compare import compare_bins
    from ms43diff.xdf import XdfFile

    def opt(flag, default=None):
        return argv[argv.index(flag) + 1] if flag in argv and argv.index(flag) + 1 < len(argv) else default

    xdf = opt("-x")
    a = opt("-a")
    b = opt("-b", a)
    log_write(f"[selftest] start, frozen={getattr(sys, 'frozen', False)}")
    if not (xdf and a):
        log_write("[selftest] -x and -a are required (-b is optional)")
        return 2
    try:
        result = compare_bins(XdfFile(xdf), BinFile(a), BinFile(b))
        out = tempfile.gettempdir()
        html = os.path.join(out, "ms43_selftest.html")
        csv_ = os.path.join(out, "ms43_selftest.csv")
        pdf = os.path.join(out, "ms43_selftest.pdf")
        report.write_html(result, html)
        log_write(f"[selftest] HTML ok: {os.path.getsize(html)} bytes")
        report.write_csv(result, csv_)
        log_write(f"[selftest] CSV ok: {os.path.getsize(csv_)} bytes")
        from ms43diff.pdfreport import HAVE_REPORTLAB, write_compare_pdf
        log_write(f"[selftest] HAVE_REPORTLAB={HAVE_REPORTLAB}")
        write_compare_pdf(result, pdf)
        log_write(f"[selftest] PDF ok: {os.path.getsize(pdf)} bytes")
        log_write("[selftest] ALL OK")
        return 0
    except Exception:
        log_write("[selftest] ERROR:\n" + traceback.format_exc())
        return 3


def _importable(name: str) -> bool:
    import importlib

    try:
        importlib.import_module(name)
        return True
    except ImportError:
        return False


def _check(path: str) -> int:
    """--check FILE: write what the built .exe really contains (used by CI)."""
    import json
    import os

    from ms43diff import project, wikicache

    pages = wikicache.load()
    kit = project.kit_dir()
    info = {
        "wiki_pages": len(pages),
        "wiki_params": len(wikicache.index_parameters()) if pages else 0,
        "wiki_missing": wikicache.missing_pages(),
        "wiki_folder": wikicache.meta().get("folder", ""),
        "projectkit": sorted(os.listdir(os.path.join(kit, "skills"))) if os.path.isdir(kit) else [],
        "python": project.bundled_python(),
        "python_exists": os.path.isfile(project.bundled_python()),
        "serial": _importable("serial.tools.list_ports"),
    }
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(info, fh, indent=1)
    return 0


def main() -> int:
    argv = sys.argv
    if "--lang" in argv and argv.index("--lang") + 1 < len(argv):
        from ms43diff.i18n import set_lang

        set_lang(argv[argv.index("--lang") + 1])
    if "--selftest" in argv:
        return _selftest(argv)
    if "--check" in argv and argv.index("--check") + 1 < len(argv):
        return _check(argv[argv.index("--check") + 1])
    from ms43diff.webui import run
    return run()


if __name__ == "__main__":
    sys.exit(main())
