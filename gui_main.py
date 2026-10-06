#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Точка входа оконной версии (её собирает PyInstaller в ms43diff-gui.exe).

Скрытый режим самодиагностики для проверки собранного .exe:
    ms43diff-gui.exe --selftest -x def.xdf -a A.bin -b B.bin
сохраняет HTML/CSV/PDF во временную папку, пишет результат в журнал и выходит.
Нужен, чтобы поймать ошибки (например PDF), которые в обычном окне не видны.
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
    gui.log_write(f"[самотест] старт, frozen={getattr(sys, 'frozen', False)}")
    if not (xdf and a):
        gui.log_write("[самотест] нужны -x и -a (и по желанию -b)")
        return 2
    try:
        result = compare_bins(XdfFile(xdf), BinFile(a), BinFile(b))
        out = tempfile.gettempdir()
        html = os.path.join(out, "ms43_selftest.html")
        csv_ = os.path.join(out, "ms43_selftest.csv")
        pdf = os.path.join(out, "ms43_selftest.pdf")
        gui.report.write_html(result, html)
        gui.log_write(f"[самотест] HTML ок: {os.path.getsize(html)} байт")
        gui.report.write_csv(result, csv_)
        gui.log_write(f"[самотест] CSV ок: {os.path.getsize(csv_)} байт")
        from ms43diff.pdfreport import HAVE_REPORTLAB, write_compare_pdf
        gui.log_write(f"[самотест] HAVE_REPORTLAB={HAVE_REPORTLAB}")
        write_compare_pdf(result, pdf)
        gui.log_write(f"[самотест] PDF ок: {os.path.getsize(pdf)} байт")
        gui.log_write("[самотест] ВСЁ ОК")
        return 0
    except Exception:
        gui.log_write("[самотест] ОШИБКА:\n" + traceback.format_exc())
        return 3


def main() -> int:
    if "--selftest" in sys.argv:
        return _selftest(sys.argv)
    from ms43diff.gui import run
    return run()


if __name__ == "__main__":
    sys.exit(main())
