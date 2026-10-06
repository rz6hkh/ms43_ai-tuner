#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Точка входа MCP-сервера (её собирает PyInstaller в ms43diff-mcp.exe).

Прошивку и XDF задаёт нейросеть-клиент через аргументы в своём конфиге:
    ms43diff-mcp.exe --xdf путь\\к\\def.xdf --bin путь\\к\\прошивке.bin
"""

import argparse
import sys

from ms43diff.mcpserver import serve


def main() -> int:
    parser = argparse.ArgumentParser(
        prog="ms43diff-mcp",
        description="MCP-сервер ms43diff: данные прошивки MS43 и база знаний MS4X Wiki "
                    "для нейросети (только чтение).",
    )
    parser.add_argument("-x", "--xdf", help="файл описания .xdf")
    parser.add_argument("-b", "--bin", help="файл прошивки .bin")
    args = parser.parse_args()
    return serve(args.xdf, args.bin)


if __name__ == "__main__":
    sys.exit(main())
