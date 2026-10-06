#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
ms43diff self-test.

    python selftest.py                         # built-in checks only
    python selftest.py def.xdf stock.bin       # plus checks on real files

The built-in checks need no files and no third-party libraries (the PDF part of
the end-to-end test is skipped gracefully without reportlab). Russian strings
below are expected outputs of the Russian layer, i.e. test data.
"""

from __future__ import annotations

import os
import sys

# On a clean Windows (including the CI runner) stdout defaults to cp1252 and
# cannot encode Cyrillic — print fails with UnicodeEncodeError. Force UTF-8.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass

from ms43diff.binfile import BinFile, Reader, format_number
from ms43diff.mathexpr import Equation
from ms43diff.xdf import Embedded, XdfFile

_failed = 0


def check(name: str, got, want) -> None:
    global _failed
    ok = got == want
    if isinstance(want, float) or isinstance(got, float):
        try:
            ok = abs(float(got) - float(want)) < 1e-6
        except (TypeError, ValueError):
            ok = False
    mark = "OK  " if ok else "FAIL"
    if not ok:
        _failed += 1
        print(f"[{mark}] {name}: got {got!r}, expected {want!r}")
    else:
        print(f"[{mark}] {name}")


def test_math() -> None:
    print("\n--- Conversion formulas ---")
    check("0.75*X-48.0 at X=64", Equation("0.75*X-48.0").apply(64), 0.0)
    check("0.375*X-23.625 at X=155", Equation("0.375*X-23.625").apply(155), 34.5)
    check("X*0.003906 at X=750", Equation("X*0.003906").apply(750), 2.9295)
    check("32.0*X at X=202", Equation("32.0*X").apply(202), 6464.0)
    # the variable is not called X — happens in auto-generated XDFs
    check("0.1*X0 at X0=250", Equation("0.1*X0", ["X0"]).apply(250), 25.0)
    check("brackets and power", Equation("(2+3)^2").apply(0), 25.0)
    check("abs function", Equation("abs(0-X)").apply(7), 7.0)
    check("a broken formula does not crash", Equation("0.5*").apply(9), 9.0)
    check("division by zero does not crash", Equation("X/0").apply(9), 9.0)
    eq = Equation("0.75*X-48.0")
    check("linearity detected", eq.is_linear, True)
    check("inverse conversion", eq.invert(0.0), 64.0)
    check("scale description", eq.describe("°C"), "1 bit = 0.75 °C, offset -48 °C")


def test_embedded() -> None:
    print("\n--- Data layout ---")
    e = Embedded(address=0x100, size_bits=16, rowcount=20, colcount=16, type_flags=0x02)
    check("signedness", e.signed, False)
    check("byte order", e.lsb_first, True)
    check("bytes per element", e.elem_bytes, 2)
    check("row stride", e.row_stride, 32)
    check("block length", e.byte_length, 20 * 32)
    s = Embedded(address=0x10, size_bits=8, type_flags=0x03)
    check("signed 8 bit", s.signed, True)
    check("static axis without data",
          Embedded(size_bits=8, major_stride_bits=-32).has_data, False)


def test_format() -> None:
    print("\n--- Formatting ---")
    check("decimals", format_number(2.9295, 2, 1), "2.93")
    check("integer", format_number(6464.0, 0, 3), "6464")
    check("hexadecimal", format_number(255, 0, 2), "0xFF")


def test_ru() -> None:
    print("\n--- Russian layer ---")
    from ms43diff import ru

    check(
        "name decoding",
        ru.name_ru("ip_iga_ron_98_pl_ivvt__n__maf").startswith(
            "[КАРТА] угол опережения зажигания"
        ),
        True,
    )
    check("axes from the name", ru.axis_names_ru("ip_iga_ron_98_pl_ivvt__n__maf"),
          ("обороты двигателя", "расход воздуха (нагрузка)"))
    check("category", ru.category_ru("Vanos"), "VANOS (фазовращатели)")
    check("units", ru.unit_ru("mg/stk"), "мг/такт")
    check(
        "an identifier is not translated word by word",
        "c_vs_fac" in ru.description_ru("Set c_vs_fac to 1096"),
        True,
    )
    check(
        "description translation",
        ru.description_ru("Maximum engine speed for misfire detection"),
        "Максимальный обороты двигателя для обнаружение пропусков воспламенения",
    )


# Modules whose string literals are Russian *data* (dictionaries, the catalog),
# not UI text, so Cyrillic literals are allowed there.
_RU_DATA_MODULES = {"ru.py", "keywords.py", "wikitrans.py", "locale_ru.py", "i18n.py"}


def _i18n_scan():
    """Return (missing keys, bad t() calls, stray Cyrillic literals, Cyrillic comments)."""
    import ast
    import glob
    import io
    import os
    import re
    import tokenize

    from ms43diff.locale_ru import RU

    cyr = re.compile("[\u0400-\u04ff]")
    root = os.path.dirname(os.path.abspath(__file__))
    files = sorted(glob.glob(os.path.join(root, "ms43diff", "**", "*.py"), recursive=True)
                   + glob.glob(os.path.join(root, "*.py")))
    missing, bad_calls, literals, comments = [], [], [], []
    for path in files:
        name = os.path.basename(path)
        rel = os.path.relpath(path, root)
        src = open(path, encoding="utf-8").read()
        tree = ast.parse(src)
        docstrings = set()
        for node in ast.walk(tree):
            if isinstance(node, (ast.Module, ast.FunctionDef, ast.ClassDef,
                                 ast.AsyncFunctionDef)) and node.body:
                first = node.body[0]
                if isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant):
                    docstrings.add(id(first.value))
            if (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                    and node.func.id == "t" and node.args):
                arg = node.args[0]
                if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                    if arg.value not in RU:
                        missing.append(f"{rel}:{node.lineno}: {arg.value!r}")
                else:
                    bad_calls.append(f"{rel}:{node.lineno}")
        if name not in _RU_DATA_MODULES and name != "selftest.py":
            for node in ast.walk(tree):
                if (isinstance(node, ast.Constant) and isinstance(node.value, str)
                        and cyr.search(node.value)):
                    kind = "docstring" if id(node) in docstrings else "literal"
                    literals.append(f"{rel}:{node.lineno}: [{kind}] {node.value[:60]!r}")
        for tok in tokenize.generate_tokens(io.StringIO(src).readline):
            if tok.type == tokenize.COMMENT and cyr.search(tok.string):
                comments.append(f"{rel}:{tok.start[0]}")
    from ms43diff.webui.server import page_keys

    for key in page_keys():
        if key not in RU:
            missing.append(f"ms43diff/webui/static/app.js: {key!r}")
    return missing, bad_calls, literals, comments


def test_i18n() -> None:
    print("\n--- Interface language ---")
    from ms43diff import i18n

    missing, bad_calls, literals, comments = _i18n_scan()
    for line in missing + bad_calls + literals:
        print("   ", line)
    check("every t() key has a Russian translation", len(missing), 0)
    check("t() is called with a plain string literal", len(bad_calls), 0)
    check("no Russian text outside t() and data modules", len(literals), 0)
    check("code comments are in English", len(comments), 0)
    saved = i18n.get_lang()
    try:
        i18n.set_lang("ru")
        check("Russian lookup", i18n.t("yes"), "да")
        check("placeholders", i18n.t("1 bit = {value}", value="0.75"), "1 бит = 0.75")
        i18n.set_lang("en")
        check("English passthrough", i18n.t("1 bit = {value}", value="0.75"), "1 bit = 0.75")
        from ms43diff import names

        check("English name decoding", names.decode("ip_iga_ron_98_pl_ivvt__n__maf"),
              "[MAP] ignition angle, RON, 98, part load, VANOS — rows: engine speed; "
              "columns: air mass flow (load)")
        check("English units pass through", names.unit("mg/stk"), "mg/stk")
        check("junk units dropped", names.unit("8"), "")
    finally:
        i18n.set_lang(saved)


def _run_cli(argv) -> tuple:
    """Run the CLI in-process; return (exit code, captured stdout)."""
    import contextlib
    import io

    from ms43diff import cli

    buf = io.StringIO()
    code = 0
    with contextlib.redirect_stdout(buf):
        try:
            code = cli.main(argv)
        except SystemExit as exc:
            code = exc.code if isinstance(exc.code, int) else 1
            if not isinstance(exc.code, int) and exc.code:
                print(exc.code)
    return code, buf.getvalue()


def _check_mcp(f: dict, lang: str, cyr) -> None:
    """Talk to the MCP server over stdio exactly as Claude Desktop does."""
    import json
    import subprocess

    root = os.path.dirname(os.path.abspath(__file__))
    requests = [
        {"jsonrpc": "2.0", "id": 1, "method": "initialize",
         "params": {"protocolVersion": "2024-11-05"}},
        {"jsonrpc": "2.0", "method": "notifications/initialized"},
        {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
        {"jsonrpc": "2.0", "id": 3, "method": "tools/call",
         "params": {"name": "get_param", "arguments": {"name": "id_n_max_mt__gear"}}},
        {"jsonrpc": "2.0", "id": 4, "method": "tools/call",
         "params": {"name": "read_map", "arguments": {"name": "ip_iga_ron_98_pl_ivvt__n__maf"}}},
        {"jsonrpc": "2.0", "id": 5, "method": "tools/call",
         "params": {"name": "firmware_info", "arguments": {}}},
    ]
    stdin = "\n".join(json.dumps(r) for r in requests) + "\n"
    proc = subprocess.run(
        [sys.executable, os.path.join(root, "mcp_main.py"), "--xdf", f["xdf"],
         "--bin", f["stock"], "--lang", lang],
        input=stdin.encode("utf-8"), capture_output=True, timeout=60,
    )
    answers = [json.loads(line) for line in proc.stdout.decode("utf-8").splitlines() if line]
    check(f"[{lang}] MCP answers every request", [a.get("id") for a in answers], [1, 2, 3, 4, 5])
    tools = answers[1]["result"]["tools"] if len(answers) > 1 else []
    check(f"[{lang}] MCP lists its tools", len(tools) >= 9, True)
    texts = [a["result"]["content"][0]["text"] for a in answers[2:]
             if not a.get("result", {}).get("isError", True)]
    check(f"[{lang}] MCP tools answer", len(texts), 3)
    joined = "\n".join(texts)
    check(f"[{lang}] MCP shows real values", "6464" in joined, True)
    check(f"[{lang}] MCP answers in the chosen language",
          bool(cyr.search(joined)), lang == "ru")


def _check_web(f: dict, lang: str, cyr) -> None:
    """The web interface API, called the way the page calls it."""
    import json
    import urllib.error
    import urllib.request

    from ms43diff import i18n
    from ms43diff.webui import server as web

    i18n.set_lang(lang)
    state = web.State()
    state.paths.update(xdf=f["xdf"], bin_a=f["stock"], bin_b=f["tuned"], xdf2="", bin2="")
    srv = web.start(state)
    base = f"http://127.0.0.1:{srv.server_address[1]}"

    def call(name, body=None, token=srv.token):
        req = urllib.request.Request(base + "/api/" + name, data=json.dumps(body or {}).encode(),
                                     headers={"X-Token": token, "Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=60) as res:
            return json.loads(res.read().decode("utf-8"))

    try:
        page = urllib.request.urlopen(base + "/?t=" + srv.token, timeout=30).read().decode("utf-8")
        check(f"[{lang}] web page carries its token", srv.token in page, True)
        try:
            call("state", token="wrong")
            refused = False
        except urllib.error.HTTPError as exc:
            refused = exc.code == 403
        check(f"[{lang}] web API refuses a wrong token", refused, True)
        st = call("state")
        check(f"[{lang}] web state sees the project", st["files"]["bin_a"].get("ok"), True)
        cmp_ = call("compare")
        titles = [it["title"] for c in cmp_["categories"] for it in c["items"]]
        check(f"[{lang}] web compare finds the changes", sorted(titles),
              ["c_gr_rax_sp", "id_n_max_mt__gear", "ip_iga_ron_98_pl_ivvt__n__maf"])
        param = call("param", {"title": "id_n_max_mt__gear"})
        check(f"[{lang}] web parameter details", (param["a"], param["b"]), ("6464", "6720"))
        m = call("map", {"title": "ip_iga_ron_98_pl_ivvt__n__maf", "mode": "delta"})
        check(f"[{lang}] web map has 4x4 cells", [len(r) for r in m["rows"]], [4, 4, 4, 4])
        st.pop("langs")  # the language menu lists the Russian name in any mode
        import socket

        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            free_port = sock.getsockname()[1]
        call("ai_update", {"name": "ms43", "changes": {"port": free_port, "role": "bin_b"}})
        call("ai_start", {"name": "ms43"})
        live = call("ai_check", {"name": "ms43"})["check"]
        call("ai_stop", {"name": "ms43"})
        check(f"[{lang}] live MCP server for Claude Code answers", (live["ok"], live["tools"] >= 9),
              (True, True))
        check(f"[{lang}] live MCP server shows the chosen firmware", "tuned.bin" in live["info"], True)
        modes = _check_web_modes(f, lang, call, state)
        text = json.dumps([st, cmp_, param, m] + modes, ensure_ascii=False)
        if lang == "en":
            check("[en] web API answers without Russian", bool(cyr.search(text)), False)
        else:
            check("[ru] web API answers in Russian", bool(cyr.search(text)), True)
    finally:
        srv.shutdown()
        srv.server_close()


def _check_web_modes(f: dict, lang: str, call, state) -> list:
    """The other window modes: browse, versions, port plan, patches, VE, reference."""
    import tests_fixtures
    from ms43diff import wikicache
    from ms43diff.webui import dialogs

    out = os.path.join(os.path.dirname(f["xdf"]), lang + "_web")
    os.makedirs(out, exist_ok=True)
    answers = {"path": ""}
    saved_dialog = dialogs.DIALOGS.save_file
    dialogs.DIALOGS.save_file = lambda *args, **kwargs: answers["path"]
    try:
        br = call("browse", {"role": "bin_a"})
        check(f"[{lang}] browse lists every parameter", br["total"], 3)
        found = call("browse", {"role": "bin_a", "query": "ignition"})
        check(f"[{lang}] browse search finds the map", [i["title"] for i in found["items"]],
              ["ip_iga_ron_98_pl_ivvt__n__maf"])
        read = call("param", {"title": "c_gr_rax_sp", "source": "read", "role": "bin_a"})
        check(f"[{lang}] browse shows a single value", read.get("value"), "2.929")

        state.paths.update(xdf2=f["xdf_x"], bin2=f["target"])
        cross = call("cross", {"role": "bin_b"})
        check(f"[{lang}] versions: renamed map matched", cross["stats"]["different"] >= 2, True)
        port = call("port")
        check(f"[{lang}] port plan sorts the changes", port["stats"]["changed"], 3)
        answers["path"] = os.path.join(out, "port.html")
        call("save_report", {"what": "port", "kind": "html"})
        answers["path"] = os.path.join(out, "port.csv")
        call("save_report", {"what": "port", "kind": "csv"})
        answers["path"] = os.path.join(out, "versions.html")
        call("save_report", {"what": "cross", "kind": "html"})
        check(f"[{lang}] mode reports written",
              sorted(n for n in os.listdir(out) if os.path.getsize(os.path.join(out, n))),
              ["port.csv", "port.html", "versions.html"])

        state.paths["patchlist"] = f["xdf"]
        pa = call("patches", {"role": "bin_b"})
        check(f"[{lang}] patch found applied in the tune", pa["stats"], {"total": 1, "applied": 1})

        state.paths["velog"] = f["log"]
        setup = call("ve_setup", {"role": "bin_a"})
        check(f"[{lang}] VE: log columns guessed",
              (setup["rows"], setup["guess"].get("rpm"), setup["guess"].get("lambda")),
              (120, "Engine Speed", "Wideband Lambda"))
        ve = call("ve_run", {"role": "bin_a", "map": "ip_iga_ron_98_pl_ivvt__n__maf",
                             "min_samples": 4})
        check(f"[{lang}] VE: cells corrected", ve["stats"]["changed"] > 0, True)
        answers["path"] = os.path.join(out, "ve.bin")
        saved = call("ve_save", {"kind": "bin"})
        check(f"[{lang}] VE: tuned firmware written",
              (saved["cells"] > 0, os.path.getsize(answers["path"])), (True, os.path.getsize(f["stock"])))

        tests_fixtures.install_wiki(os.environ["APPDATA"])
        wikicache.load(force=True)
        wiki = call("wiki")
        check(f"[{lang}] reference is available", (wiki["available"], wiki["pages"]), (True, 1))
        warn = call("wiki", {"cautions": True})
        check(f"[{lang}] reference finds the warnings", len(warn["sections"]), 1)
        sec = call("wiki_section", {"id": 0})
        check(f"[{lang}] reference section has a warning line",
              any(line["warn"] for line in sec["lines"]), True)
        return [br, found, cross, port, pa, setup, ve, warn, sec]
    finally:
        dialogs.DIALOGS.save_file = saved_dialog
        state.paths.update(xdf2="", bin2="", patchlist="", velog="")


def test_end_to_end() -> None:
    """Every CLI command and report format on synthetic files, in both languages."""
    import re
    import shutil
    import tempfile

    import tests_fixtures
    from ms43diff import i18n

    print("\n--- End-to-end on synthetic files ---")
    cyr = re.compile("[\u0400-\u04ff]")
    tmp = tempfile.mkdtemp(prefix="ms43selftest_")
    saved = i18n.get_lang()
    # keep the user's real settings file out of the test
    saved_env = {k: os.environ.get(k) for k in ("APPDATA", "XDG_CONFIG_HOME")}
    os.environ["APPDATA"] = os.environ["XDG_CONFIG_HOME"] = os.path.join(tmp, "config")
    try:
        f = tests_fixtures.build(tmp)
        for lang in ("en", "ru"):
            out = os.path.join(tmp, lang)
            os.makedirs(out)
            rep = lambda name: os.path.join(out, name)  # noqa: E731
            commands = {
                "diff": ["diff", "-x", f["xdf"], f["stock"], f["tuned"], "-v", "--english",
                         "--html", rep("d.html"), "--csv", rep("d.csv"),
                         "--json", rep("d.json"), "--md", rep("d.md"), "--pdf", rep("d.pdf")],
                "show": ["show", "-x", f["xdf"], "-b", f["stock"], "-c", f["tuned"],
                         "ip_iga", "--pdf", rep("s.pdf")],
                "find": ["find", "-x", f["xdf"], "-b", f["stock"], "ignition"],
                "list": ["list", "-x", f["xdf"], "-b", f["stock"]],
                "categories": ["list", "-x", f["xdf"], "--categories"],
                "dump": ["dump", "-x", f["xdf"], "-b", f["stock"], "-o", rep("dump.csv")],
                "info": ["info", "-x", f["xdf"], "-b", f["target"]],
                "multi": ["multi", "-x", f["xdf"], f["stock"], f["tuned"], f["target"]],
                "patches": ["patches", "-x", f["xdf"], "-b", f["tuned"]],
                "xdiff": ["xdiff", "-A", f["xdf"], "-B", f["xdf_x"], f["tuned"], f["target"],
                          "--html", rep("x.html")],
                "port": ["port", "-A", f["xdf"], "-B", f["xdf_x"], f["stock"], f["tuned"],
                         f["target"], "--html", rep("p.html"), "--csv", rep("p.csv"),
                         "--pdf", rep("p.pdf")],
                "vetune": ["vetune", f["log"], "-x", f["xdf"], "-b", f["stock"],
                           "-m", "ip_iga_ron_98_pl_ivvt__n__maf", "--min-samples", "4",
                           "--html", rep("v.html"), "--write", rep("v.bin")],
                "help": ["diff", "--help"],
            }
            for name, argv in commands.items():
                code, text = _run_cli(["--lang", lang] + argv)
                ok = code == 0 and bool(text.strip())
                if not ok:
                    print(text[-1500:])
                check(f"[{lang}] {name} runs", ok, True)
                if lang == "en":
                    bad = sorted(set(cyr.findall(text)))
                    if bad:
                        print("    stray letters:", "".join(bad),
                              [line for line in text.splitlines() if cyr.search(line)][:3])
                    check(f"[en] {name}: no Russian in the output", bool(bad), False)
            for name in sorted(os.listdir(out)):
                path = os.path.join(out, name)
                check(f"[{lang}] {name} written", os.path.getsize(path) > 0, True)
                if lang == "en" and name.rsplit(".", 1)[-1] in ("html", "csv", "md", "json"):
                    text = open(path, encoding="utf-8-sig").read()
                    lines = [line for line in text.splitlines() if cyr.search(line)]
                    if lines:
                        print("    ", lines[:2])
                    check(f"[en] {name}: no Russian", bool(lines), False)
            if lang == "ru":
                text = open(os.path.join(out, "d.html"), encoding="utf-8").read()
                check("[ru] HTML report is in Russian", "Сравнение прошивок MS43" in text, True)
            _check_mcp(f, lang, cyr)
            _check_web(f, lang, cyr)
    finally:
        i18n.set_lang(saved)
        for key, value in saved_env.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        shutil.rmtree(tmp, ignore_errors=True)


def test_files(xdf_path: str, bin_path: str) -> None:
    print("\n--- Real files ---")
    xdf = XdfFile(xdf_path)
    binf = BinFile(bin_path)
    reader = Reader(xdf, binf)
    print(f"XDF: {xdf.title} v{xdf.file_version}, {len(xdf.items)} objects")
    print(f"BIN: {binf.name}, {binf.size_kb} KB, offset {reader.offset.label}, "
          f"fit {reader.offset.fit * 100:.1f}%")

    check("offset fits completely", reader.offset.fit, 1.0)

    ratio = xdf.by_title("c_gr_rax_sp")
    if ratio is not None:
        values = reader.values(ratio)
        print(f"Final drive ratio (c_gr_rax_sp) = {values[0]:.3f}")
        check("final drive ratio is plausible", 2.0 < values[0] < 5.0, True)

    limiter = xdf.by_title("id_n_max_mt__gear")
    if limiter is not None:
        values = reader.values(limiter)
        print(f"Manual gearbox rev limit per gear: {[int(v) for v in values]}")
        check("rev limit is plausible", all(3000 < v < 9000 for v in values), True)

    iga = xdf.by_title("ip_iga_ron_98_pl_ivvt__n__maf")
    if iga is not None:
        values = reader.values(iga)
        print(f"Ignition map RON98: {min(values):.1f}…{max(values):.1f} deg CRK, "
              f"{len(values)} cells")
        check("ignition angles are plausible", -30 < min(values) and max(values) < 60, True)
        x = reader.axis_values(iga, "x")
        y = reader.axis_values(iga, "y")
        check("X axis read", x is not None and len(x) == iga.cols, True)
        check("Y axis read", y is not None and len(y) == iga.rows, True)


def main() -> int:
    test_math()
    test_embedded()
    test_format()
    test_ru()
    test_i18n()
    test_end_to_end()
    if len(sys.argv) >= 3:
        test_files(sys.argv[1], sys.argv[2])
    else:
        print("\n(Checks on real files skipped — "
              "run: python selftest.py def.xdf firmware.bin)")
    print()
    if _failed:
        print(f"FAILED checks: {_failed}")
        return 1
    print("All checks passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
