#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Сборка .exe для Windows.

    python -m pip install pyinstaller reportlab
    python build_exe.py

На выходе в папке dist:
    ms43diff-gui.exe   — оконная версия (запускается двойным кликом)
    ms43diff-mcp.exe   — MCP-сервер для нейросети (запускает клиент, не человек)

Оба — один файл, без установки Python на целевой машине.
reportlab кладём целиком через --collect-all, иначе в .exe не попадают его
данные/шрифты и экспорт в PDF падает.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys

# На чистой Windows / CI stdout по умолчанию cp1252 — русские print падают.
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
    # словари и парсеры — обычные модули пакета, но перечислим явно,
    # чтобы PyInstaller не потерял их при анализе импортов
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
    "--paths", ROOT,
    # ничего лишнего в сборку не тащим.
    # PIL НЕ исключаем: с ним конфликтует --collect-all reportlab и в .exe
    # не попадают шрифты reportlab — PDF молча падает.
    "--exclude-module", "numpy",
    "--exclude-module", "pytest",
    "--exclude-module", "matplotlib",
]

# Офлайн-копию MS4X Wiki встраиваем в .exe ТОЛЬКО если она есть локально.
# В репозитории её нет (контент чужого сайта), поэтому релиз с GitHub Actions
# собирается без неё — публичный .exe не распространяет чужой контент.
# Пользователь качает справочник кнопкой «Обновить с сайта» в окне.
_WIKIDATA = os.path.join(ROOT, "ms43diff", "wikidata")
if os.path.isdir(_WIKIDATA) and os.listdir(_WIKIDATA):
    COMMON += ["--add-data", _WIKIDATA + os.pathsep + "ms43diff/wikidata"]
    print("Справочник MS4X Wiki найден локально — встраиваю в .exe.")
else:
    print("Справочника wikidata нет — .exe без него (качается в программе).")

# reportlab нужен окну для PDF; тянем целиком, чтобы попали шрифты
GUI_EXTRA = ["--collect-all", "reportlab"]


def build(entry: str, name: str, windowed: bool, extra=None) -> str:
    args = [sys.executable, "-m", "PyInstaller", *COMMON, *(extra or []),
            "--name", name]
    args.append("--windowed" if windowed else "--console")
    args.append(os.path.join(ROOT, entry))
    print("\n" + "=" * 70)
    print(f"Собираю {name}.exe из {entry}")
    print("=" * 70)
    result = subprocess.run(args, cwd=ROOT)
    if result.returncode != 0:
        raise SystemExit(f"PyInstaller завершился с ошибкой при сборке {name}")
    return os.path.join(ROOT, "dist", name + ".exe")


def main() -> int:
    try:
        import PyInstaller  # noqa: F401
    except ImportError:
        raise SystemExit(
            "Не установлен PyInstaller. Выполните:\n"
            "    python -m pip install pyinstaller reportlab"
        )

    made = [
        # окно: с PDF (reportlab), без консоли
        build("gui_main.py", "ms43diff-gui", windowed=True, extra=GUI_EXTRA),
        # MCP-сервер: общается по stdin/stdout, поэтому только --console
        # (клиент запускает его скрыто, чёрное окно не мелькает)
        build("mcp_main.py", "ms43diff-mcp", windowed=False),
    ]

    print("\n" + "=" * 70)
    print("Готово. Файлы:")
    for path in made:
        size = os.path.getsize(path) / 1024 / 1024
        print(f"  {path}   ({size:.1f} МБ)")
    print("=" * 70)
    print("Их можно копировать куда угодно — Python на целевой машине не нужен.")

    # временные папки сборки не нужны
    for folder in ("build",):
        shutil.rmtree(os.path.join(ROOT, folder), ignore_errors=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
