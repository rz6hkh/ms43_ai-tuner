#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""MCP server entry point (PyInstaller builds it into ms43-ai-tuner-mcp.exe).

The AI client passes the firmware and the XDF as arguments in its config:
    ms43-ai-tuner-mcp.exe --xdf path\\to\\def.xdf --bin path\\to\\firmware.bin

Connecting to Claude Desktop (used by mcp-add.bat / mcp-remove.bat):
    ms43-ai-tuner-mcp.exe --install [file.xdf file.bin]   # no files: pick them in a dialog
    ms43-ai-tuner-mcp.exe --uninstall
"""

import argparse
import os
import sys


def _preselect_lang(argv) -> None:
    from ms43diff.i18n import LANGS, set_lang

    pre = argparse.ArgumentParser(add_help=False)
    pre.add_argument("--lang", choices=LANGS)
    known, _ = pre.parse_known_args(argv)
    if known.lang:
        set_lang(known.lang)


def _ask_files(xdf, bin_path):
    """Ask for missing files with dialogs; fall back to the console."""
    from ms43diff.i18n import t

    try:
        import tkinter as tk
        from tkinter import filedialog

        root = tk.Tk()
        root.withdraw()
        if not xdf:
            xdf = filedialog.askopenfilename(
                title=t("Choose the XDF definition"),
                filetypes=[(t("TunerPro definitions"), "*.xdf"), (t("All files"), "*.*")])
        if xdf and not bin_path:
            bin_path = filedialog.askopenfilename(
                title=t("Choose the firmware file"), initialdir=os.path.dirname(xdf),
                filetypes=[(t("Firmware files"), "*.bin"), (t("All files"), "*.*")])
        root.destroy()
    except Exception:  # noqa: BLE001 - no GUI available: ask in the console
        if not xdf:
            xdf = input(t("Path to the .xdf file: ")).strip().strip('"')
        if not bin_path:
            bin_path = input(t("Path to the .bin file: ")).strip().strip('"')
    return xdf, bin_path


def _install(files) -> int:
    from ms43diff import mcpinstall
    from ms43diff.i18n import t

    xdf, bin_path = mcpinstall.split_paths(files)
    if not (xdf and bin_path):
        xdf, bin_path = _ask_files(xdf, bin_path)
    if not (xdf and bin_path):
        print(t("Cancelled: both an .xdf and a .bin file are needed."))
        return 1
    try:
        info = mcpinstall.install(xdf, bin_path)
    except mcpinstall.InstallError as exc:
        print(t("Error: {error}", error=exc))
        return 1
    print(mcpinstall.install_message(info))
    return 0


def _uninstall() -> int:
    from ms43diff import mcpinstall
    from ms43diff.i18n import t

    try:
        info = mcpinstall.uninstall()
    except mcpinstall.InstallError as exc:
        print(t("Error: {error}", error=exc))
        return 1
    print(mcpinstall.uninstall_message(info))
    return 0


def main() -> int:
    from ms43diff.i18n import LANGS, t

    argv = sys.argv[1:]
    _preselect_lang(argv)
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass

    parser = argparse.ArgumentParser(
        prog="ms43-ai-tuner-mcp",
        description=t("ms43diff MCP server: MS43 firmware data and the MS4X Wiki "
                      "knowledge base for an AI assistant (read-only)."),
    )
    parser.add_argument("-x", "--xdf", help=t(".xdf definition file"))
    parser.add_argument("-b", "--bin", help=t(".bin firmware file"))
    parser.add_argument("--lang", choices=LANGS,
                        help=t("interface language (default: saved setting or system language)"))
    parser.add_argument("--install", action="store_true",
                        help=t("connect the server to Claude Desktop"))
    parser.add_argument("--uninstall", action="store_true",
                        help=t("disconnect the server from Claude Desktop"))
    parser.add_argument("files", nargs="*", help=t(".xdf and .bin for --install"))
    args = parser.parse_args(argv)

    if args.install:
        return _install([p for p in (args.xdf, args.bin) if p] + args.files)
    if args.uninstall:
        return _uninstall()

    from ms43diff.mcpserver import serve

    return serve(args.xdf, args.bin)


if __name__ == "__main__":
    sys.exit(main())
