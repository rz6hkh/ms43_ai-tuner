#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Window version entry point (PyInstaller builds it into ms43-ai-tuner.exe).

    ms43-ai-tuner.exe [--lang en|ru] [--classic]

The interface is an HTML page in an Edge app window (ms43diff.webui);
--classic starts the older tkinter window.

Hidden self-test mode for checking a built .exe:
    ms43-ai-tuner.exe --selftest -x def.xdf -a A.bin -b B.bin
saves HTML/CSV/PDF into the temp folder, writes the result to the log and
exits. It catches errors (e.g. in PDF export) that a normal window hides.
"""

import sys


def _selftest(argv) -> int:
    import os
    import tempfile
    import traceback

    from ms43diff import gui
    from ms43diff.binfile import BinFile
    from ms43diff.compare import compare_bins
    from ms43diff.xdf import XdfFile

    def opt(flag, default=None):
        return argv[argv.index(flag) + 1] if flag in argv and argv.index(flag) + 1 < len(argv) else default

    xdf = opt("-x")
    a = opt("-a")
    b = opt("-b", a)
    gui.log_write(f"[selftest] start, frozen={getattr(sys, 'frozen', False)}")
    if not (xdf and a):
        gui.log_write("[selftest] -x and -a are required (-b is optional)")
        return 2
    try:
        result = compare_bins(XdfFile(xdf), BinFile(a), BinFile(b))
        out = tempfile.gettempdir()
        html = os.path.join(out, "ms43_selftest.html")
        csv_ = os.path.join(out, "ms43_selftest.csv")
        pdf = os.path.join(out, "ms43_selftest.pdf")
        gui.report.write_html(result, html)
        gui.log_write(f"[selftest] HTML ok: {os.path.getsize(html)} bytes")
        gui.report.write_csv(result, csv_)
        gui.log_write(f"[selftest] CSV ok: {os.path.getsize(csv_)} bytes")
        from ms43diff.pdfreport import HAVE_REPORTLAB, write_compare_pdf
        gui.log_write(f"[selftest] HAVE_REPORTLAB={HAVE_REPORTLAB}")
        write_compare_pdf(result, pdf)
        gui.log_write(f"[selftest] PDF ok: {os.path.getsize(pdf)} bytes")
        gui.log_write("[selftest] ALL OK")
        return 0
    except Exception:
        gui.log_write("[selftest] ERROR:\n" + traceback.format_exc())
        return 3


def main() -> int:
    argv = sys.argv
    if "--lang" in argv and argv.index("--lang") + 1 < len(argv):
        from ms43diff.i18n import set_lang

        set_lang(argv[argv.index("--lang") + 1])
    if "--selftest" in argv:
        return _selftest(argv)
    if "--classic" in argv:
        from ms43diff.gui import run
        return run()
    from ms43diff.webui import run
    return run()


if __name__ == "__main__":
    sys.exit(main())
