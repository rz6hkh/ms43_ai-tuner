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
    # logger definitions (.adx) use bit masks and formulas over other channels
    check("bit mask X&8191", Equation("(X&8191)*0.5").apply(9000), 404.0)
    check("shift and or", Equation("(X<<1)|1").apply(3), 7.0)
    check("formula over channels", Equation("(TI*RPM)/1200").evaluate({"TI": 10, "RPM": 6000}), 50.0)
    check("a broken formula is reported", Equation("0.5*").error is not None, True)
    check("a good formula has no error", Equation("0.375*X-23.625").error, None)


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


def test_car() -> None:
    print("\n--- Car profile ---")
    from ms43diff import car as carmod

    c = carmod.normalize({"ratios": "4,21 2.49 1.67 1.24 1.00", "final_drive": "2.93",
                          "tire": "205/55 R16", "speed_sensor": "nonsense"})
    check("car: ratios parsed, unknown sensor refused", (c["ratios"][0], c["speed_sensor"]), (4.21, "unknown"))
    check("car: tyre circumference from the size", 1.9 < (carmod.tire_circumference("205/55 R16") or 0) < 2.0, True)
    c["circumference"] = 1.872
    check("car: the gear from rpm and speed", carmod.gear_for(4000, 61.6, c)[0], 2)
    check("car: no gear without ratios", carmod.gear_for(4000, 61.6, carmod.normalize({})), None)
    try:
        carmod.normalize({"ratios": "1.00 2.49"})
        check("car: ratios in the wrong order refused", False, True)
    except ValueError:
        check("car: ratios in the wrong order refused", True, True)
    check("car: an empty field is not confirmed", "not confirmed" in carmod.rules_text(carmod.normalize({})), True)

    import shutil
    import tempfile

    import tests_fixtures as tf
    tmp = tempfile.mkdtemp(prefix="ms43car_")
    try:
        log = os.path.join(tmp, "gears.csv")
        with open(log, "w", encoding="utf-8") as fh:
            fh.write(tf.gear_log())
        res = carmod.calibrate([log], carmod.normalize({"circumference": 1.872, "final_drive": 2.93}))
        best = res["matches"][0]
        check("car calibration: 4 steady gears found, the gearbox by its steps",
              (len(res["gears"]), best["gearbox"], best["gears"]), (4, "zf_s5d_320z", [2, 3, 4, 5]))
        check("car calibration: the logged speed 2 % high is found, ECU gears agree",
              (round(best["speed_error"] * 100), list(res["ecu"].values())), (2, [2, 3, 4, 5]))
        carmod.save(tmp, {"tire": "", "circumference": "1.872"})
        proposed = carmod.apply_calibration(tmp, res)
        car = carmod.load(tmp)
        check("car calibration: proposed, not confirmed",
              (proposed, carmod.effective(car)["_state"]["gearbox"],
               "proposed, source: logs: gears.csv" in carmod.rules_text(car)),
              (["per_1000", "gearbox", "final_drive"], "proposed", True))
        car = carmod.settle(tmp, "gearbox", True)
        car = carmod.settle(tmp, "final_drive", False)
        check("car: an accepted proposal is confirmed, a rejected one is gone",
              (car["gearbox"], car["ratios"][0], car["final_drive"],
               [p["field"] for p in car["proposals"]]), ("zf_s5d_320z", 4.21, None, ["per_1000"]))
        check("car: the gear from the measured speeds", carmod.gear_for(3000, 47.0, car)[0], 2)
        k = 60 * 1.872 / 3.64
        boxes = [carmod.match([k / r for r in box][1:4])[0]["gearbox"]
                 for box in ([3.72, 2.02, 1.32, 1.00, 0.81], [3.83, 2.20, 1.40, 1.00, 0.81])]
        check("car: Getrag 240 and 260 told apart by their steps", boxes, ["getrag_240", "getrag_260"])
        car = carmod.save(tmp, {"model": "E30"})
        check("car: the owner's form keeps the measured values", (car["model"], car["gearbox"],
              len(car["proposals"])), ("E30", "zf_s5d_320z", 1))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    from ms43diff import tplog
    check("integer formatting keeps the zeros", (tplog.fmt(1240, 0), tplog.fmt(1.50, 2)), ("1240", "1.5"))


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
    """Talk to the MCP server over HTTP exactly as Claude Code does."""
    import socket

    from ms43diff import mcphttp

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
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    server = mcphttp.McpHttpServer("selftest", port, "t0ken", lambda: (f["xdf"], f["stock"]), lang)
    server.start()
    try:
        answers = mcphttp.call(server.url, "t0ken", requests)
    finally:
        server.stop()
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
        edited = _check_edits(f, lang, call, base, srv.token)
        _check_project(f, lang, call)
        logs = _check_logs(f, lang, call, base, srv.token)
        modes = _check_web_modes(f, lang, call, state)
        text = json.dumps([st, cmp_, param, m] + modes + edited + logs, ensure_ascii=False)
        if lang == "en":
            check("[en] web API answers without Russian", bool(cyr.search(text)), False)
        else:
            check("[ru] web API answers in Russian", bool(cyr.search(text)), True)
    finally:
        srv.shutdown()
        srv.server_close()


def _check_web_modes(f: dict, lang: str, call, state) -> list:
    """The other window modes: browse, versions, port plan, patches, reference."""
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

        tests_fixtures.install_wiki(os.environ["APPDATA"])
        wikicache.load(force=True)
        wiki = call("wiki")
        check(f"[{lang}] reference is available", (wiki["available"], wiki["pages"]), (True, 1))
        warn = call("wiki", {"cautions": True})
        check(f"[{lang}] reference finds the warnings", len(warn["sections"]), 1)
        sec = call("wiki_section", {"id": 0})
        check(f"[{lang}] reference section has a warning line",
              any(line["warn"] for line in sec["lines"]), True)
        return [br, found, cross, port, pa, warn, sec]
    finally:
        dialogs.DIALOGS.save_file = saved_dialog
        state.paths.update(xdf2="", bin2="", patchlist="")


def _check_edits(f: dict, lang: str, call, base: str, token: str) -> list:
    """Edits: the AI proposes through MCP, the window checks and writes a new .bin."""
    import json
    import socket
    import urllib.error
    import urllib.request

    from ms43diff import mcphttp
    from ms43diff.binfile import BinFile, Reader
    from ms43diff.xdf import XdfFile

    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    call("ai_update", {"name": "ms43", "changes": {"port": port, "role": "bin_a"}})
    ai = call("ai_start", {"name": "ms43"})
    url, mcp_token = ai["servers"][0]["url"], ai["servers"][0]["command"].split("Bearer ")[1].rstrip('"')

    def tool(name, **arguments):
        answer = mcphttp.call(url, mcp_token, [{"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                                                "params": {"name": name, "arguments": arguments}}])
        return answer[0]["result"]["content"][0]["text"]

    def ping():
        req = urllib.request.Request(base + "/api/ping", data=b"{}",
                                     headers={"X-Token": token, "Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=30) as res:
            return json.loads(res.read().decode("utf-8"))

    try:
        call("edits_remove", {"role": "bin_a", "all": True})
        before = ping()["events"]
        added = tool("edit_propose", kind="value", target="c_gr_rax_sp", value=3.07,
                     reason="shorter final drive")
        check(f"[{lang}] MCP edit: a change is added", "#" in added and "3.070" in added, True)
        refused = tool("edit_propose", kind="value", target="c_gr_rax_sp", value=999, reason="too big")
        check(f"[{lang}] MCP edit: a value that does not fit is refused", "999" in refused
              and "#2" not in refused, True)
        red = tool("edit_propose", kind="region", target="ip_iga_ron_98_pl_ivvt__n__maf", op="add",
                   amount=1.5, y_from=2500, y_to=4000, x_from=200, x_to=300, reason="more advance")
        check(f"[{lang}] MCP edit: more advance is marked as a risk", "⚠" in red or "RISK" in red
              or "РИСК" in red, True)
        check(f"[{lang}] MCP edit: the window is told", ping()["events"] > before, True)
        tool("edit_show")
        check(f"[{lang}] MCP edit: the window opens the Edits screen", ping()["show"], "edits")
        st = call("edits_state", {"role": "bin_a"})
        check(f"[{lang}] edits screen: two changes, risky, writable",
              (len(st["changes"]), st["red"], st["ok"], st["bytes"]), (2, True, True, 6))
        try:
            call("edits_create", {"role": "bin_a"})
            unconfirmed = "written"
        except urllib.error.HTTPError as exc:
            unconfirmed = exc.code
        check(f"[{lang}] edits: a risky draft needs the typed confirmation", unconfirmed, 400)
        made = call("edits_create", {"role": "bin_a", "confirm": st["confirm_word"]})
        check(f"[{lang}] edits: a new .bin and a change log are written",
              (os.path.isfile(made["path"]), os.path.isfile(made["notes"]),
               made["name"].startswith("stock_v")), (True, True, True))
        reader = Reader(XdfFile(f["xdf"]), BinFile(made["path"]))
        check(f"[{lang}] edits: the new file has the new values",
              round(reader.values(reader.xdf.by_title("c_gr_rax_sp"))[0], 3), 3.07)
        check(f"[{lang}] edits: the source file is untouched",
              BinFile(f["stock"]).data == open(f["stock"], "rb").read()
              and round(Reader(XdfFile(f["xdf"]), BinFile(f["stock"])).values(
                  reader.xdf.by_title("c_gr_rax_sp"))[0], 4), 2.9295)
        check(f"[{lang}] edits: the draft is empty after writing",
              len(call("edits_state", {"role": "bin_a"})["changes"]), 0)
        return [added, refused, red, st]
    finally:
        call("ai_stop", {"name": "ms43"})


def _check_logs(f: dict, lang: str, call, base: str, token: str) -> list:
    """Logs bound to a firmware: window screen, MCP tools, evidence in edits."""
    import json
    import socket
    import urllib.request

    from ms43diff import mcphttp, tplog

    folder = os.path.join(call("ai_state")["project"]["folder"], "logs")
    name = os.path.basename(tplog.add_log(f["tplog"], folder, f["stock"], f["xdf"], "test"))
    other = os.path.join(os.path.dirname(f["tplog"]), "other_fw.csv")
    with open(f["tplog"], "rb") as src, open(other, "wb") as dst:
        dst.write(src.read())
    tplog.add_log(other, folder, f["tuned"], f["xdf"])
    st = call("logs_state", {})
    check(f"[{lang}] logs: both logs listed and bound",
          sorted((l["name"], l["firmware"], l["problem"], l["events"]) for l in st["logs"]),
          [(name, "stock.bin", "", 2), ("other_fw.csv", "tuned.bin", "", 2)])
    view = call("logs_view", {"log": name})
    check(f"[{lang}] logs: knock events and the overrun flag",
          ([e["det"] for e in view["events"]], [x["flag"] for x in view["flags"]]),
          ([2, 1], ["Trailing Throttle Fuel Cut"]))
    over = call("logs_map", {"log": name, "map": "ip_iga_ron_98_pl_ivvt__n__maf"})
    cell = over["rows"][1][1]
    check(f"[{lang}] logs: overlay finds the knock cell (2500 rpm, 200 mg/stk)",
          (over["y_channel"], over["x_channel"], cell["k"], cell["cyl"]),
          ("Engine Speed", "Engine Load Ignition", 2, ["4"]))
    check(f"[{lang}] logs: recovery is retard, not knock", (over["rows"][2][2]["k"], over["rows"][2][2]["r"] > 0),
          (0, True))
    raw = call("logs_map", {"log": name, "map": "ip_iga_ron_98_pl_ivvt__n__maf", "filters": []})
    check(f"[{lang}] logs: without filters the cold idle and the stab count too",
          (raw["used"], raw["rows"][2][3]["k"]), (700, 1))
    trims = call("logs_map", {"log": name, "map": "ip_iga_ron_98_pl_ivvt__n__maf",
                              "value_channel": "Short Term Fuel Trim Bank 1",
                              "filters": ["warm", "closed_loop"]})
    check(f"[{lang}] logs: fuel trim mean per cell (closed loop only)",
          (trims["rows"][1][1]["m"], trims["rows"][2][2]["m"], trims["filter_stats"]["closed_loop"] > 0),
          ("4", "-2", True))
    both = call("logs_map", {"log": "other_fw.csv", "map": "ip_iga_ron_98_pl_ivvt__n__maf",
                             "compare": name})
    check(f"[{lang}] logs: before/after shows the changed map and the knock in both logs",
          (both["compare"], both["rows"][2][2].get("was") is not None, both["rows"][1][1]["st"]),
          (name, True, "still"))
    series = call("logs_series", {"log": name, "channels": ["Engine Speed"], "from": 19, "to": 21})
    check(f"[{lang}] logs: chart data with knock marks", series["knock"], [20.0, 20.1])

    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    call("ai_update", {"name": "ms43", "changes": {"port": port, "role": "bin_a"}})
    ai = call("ai_start", {"name": "ms43"})
    url, mcp_token = ai["servers"][0]["url"], ai["servers"][0]["command"].split("Bearer ")[1].rstrip('"')
    proj = call("ai_state")["project"]
    call("ai_project", {"folder": proj["folder"], "name": proj["name"], "server": "ms43"})
    with open(os.path.join(proj["folder"], ".mcp.json"), encoding="utf-8") as fh:
        _check_bridge(lang, json.load(fh)["mcpServers"]["ms43"])
    proj = call("ai_state")["project"]
    call("ai_project", {"folder": proj["folder"], "name": proj["name"], "server": "ms43"})
    with open(os.path.join(proj["folder"], ".mcp.json"), encoding="utf-8") as fh:
        _check_bridge(lang, json.load(fh)["mcpServers"]["ms43"])

    def tool(tool_name, **arguments):
        answer = mcphttp.call(url, mcp_token, [{"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                                                "params": {"name": tool_name, "arguments": arguments}}])
        return answer[0]["result"]["content"][0]["text"]

    def ping():
        req = urllib.request.Request(base + "/api/ping", data=b"{}",
                                     headers={"X-Token": token, "Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=30) as res:
            return json.loads(res.read().decode("utf-8"))

    try:
        listed = tool("log_list")
        info = tool("log_info", log=name)
        hits = tool("log_map_hits", log=name, map="ip_iga_ron_98_pl_ivvt__n__maf")
        rows = tool("log_rows", log=name, **{"from": 20.0, "to": 20.1})
        check(f"[{lang}] MCP logs: log_info reports the fuel trims", info.count("STFT") >= 1, True)
        diff = tool("firmware_diff", a=name, b="other_fw.csv")
        check(f"[{lang}] MCP firmware_diff: the tune's maps and limits, by log firmware",
              ("ip_iga_ron_98_pl_ivvt__n__maf" in diff, "id_n_max_mt__gear" in diff,
               "c_gr_rax_sp" in diff, "4000×300" in diff), (True, True, True, True))
        check(f"[{lang}] MCP logs: list, events, cells, rows",
              (name in listed and "stock.bin" in listed, "#2" in info and "-3" in info,
               "[1,1]" in hits and "-3" in hits, len(rows.splitlines())), (True, True, True, 4))
        cmp_text = tool("log_compare", before=name, after="other_fw.csv", map="ip_iga_ron_98_pl_ivvt__n__maf")
        check(f"[{lang}] MCP logs: before/after comparison", ("[1,1]" in cmp_text, "->" in cmp_text),
              (True, True))
        trim_text = tool("log_map_hits", log=name, map="ip_iga_ron_98_pl_ivvt__n__maf",
                         value_channel="Short Term Fuel Trim Bank 1")
        check(f"[{lang}] MCP logs: a fuel trim per cell, closed loop added by default",
              ("closed_loop" in trim_text, "Short Term Fuel Trim Bank 1" in trim_text), (True, True))
        before_note = tool("log_info", log=name)
        noted = call("logs_note", {"log": name, "conditions": {
            "where": "track", "fuel": "98 RON", "complaint": "rough idle", "changed": "nothing"}})
        after_note = tool("log_info", log=name)
        check(f"[{lang}] logs: conditions note editable after import, shown to Claude",
              (noted["missing"], "98 RON" in after_note, "98 RON" in before_note,
               call("logs_view", {"log": name})["conditions"]["changed"]),
              ([], True, False, "nothing"))
        no_car = tool("log_modes", log=name)
        linfo = tool("logger_info")
        check(f"[{lang}] MCP logger_info: the ADX, the pack and the fallback",
              ("ADX" in linfo, "0B 03" in linfo), (True, True))
        call("ai_car", {"car": {"ratios": "4.21 2.49 1.67 1.24 1.00", "final_drive": "2.93",
                                "circumference": "1.872", "speed_sensor": "differential"}})
        car_text = tool("car_info")
        prop = tool("car_propose", field="mods_other", value="M30 single-mass flywheel",
                    reason="the owner said so in the chat")
        shown = call("ai_state")["car"]["proposals"]
        check(f"[{lang}] car: Claude proposes, the window shows it for the owner",
              ("mods_other" in prop, [p["field"] for p in shown]), (True, ["mods_other"]))
        rules = open(os.path.join(os.path.dirname(folder), ".claude", "ms43-rules.md"),
                     encoding="utf-8").read()
        check(f"[{lang}] car profile: speeds per gear, the rules updated, log_modes runs",
              ("38.3" in car_text, "2.93" in rules and "differential" in rules,
               len(no_car.splitlines()) > 5), (True, True, True))
        tool("log_show", log=name, map="ip_iga_ron_98_pl_ivvt__n__maf", **{"from": 18, "to": 24})
        check(f"[{lang}] MCP logs: the window opens the Logs screen", ping()["show"], "logs")
        check(f"[{lang}] logs: the window gets what to show",
              call("logs_state", {})["view"].get("map"), "ip_iga_ron_98_pl_ivvt__n__maf")
        call("edits_remove", {"role": "bin_a", "all": True})
        tool("edit_propose", kind="region", target="ip_iga_ron_98_pl_ivvt__n__maf", op="add",
             amount=-0.75, y_from=2500, y_to=2500, x_from=200, x_to=200,
             reason="knock at 20 s", evidence_log=name)
        tool("edit_propose", kind="region", target="ip_iga_ron_98_pl_ivvt__n__maf", op="add",
             amount=-0.75, y_from=4000, y_to=4000, x_from=300, x_to=300,
             reason="knock", evidence_log="other_fw.csv")
        ed = call("edits_state", {"role": "bin_a"})
        check(f"[{lang}] edits: evidence from the same firmware is fine, from another one is a risk",
              ([c["evidence"] for c in ed["changes"]], [bool(c["red"]) for c in ed["changes"]]),
              ([name, "other_fw.csv"], [False, True]))
        call("edits_remove", {"role": "bin_a", "all": True})
        return [st, view, over, listed, info, hits]
    finally:
        call("ai_stop", {"name": "ms43"})


def _check_project(f: dict, lang: str, call) -> None:
    """The tuning project folder for Claude Code."""
    import json

    folder = os.path.join(os.path.dirname(f["xdf"]), f"project_{lang}")
    r = call("ai_project", {"folder": folder, "name": "Test car", "server": "ms43"})
    res = r["project_result"]
    skills = sorted(os.listdir(os.path.join(folder, ".claude", "skills")))
    check(f"[{lang}] project: files written",
          (os.path.isfile(os.path.join(folder, "CLAUDE.md")), "log-review" in skills,
           os.path.isfile(os.path.join(folder, "tools", "ms43log.py")),
           os.path.isdir(os.path.join(folder, "logs"))), (True, True, True, True))
    cfg = json.load(open(os.path.join(folder, ".mcp.json"), encoding="utf-8"))["mcpServers"]["ms43"]
    text = open(os.path.join(folder, ".claude", "ms43-rules.md"), encoding="utf-8").read()
    claude_md = open(os.path.join(folder, "CLAUDE.md"), encoding="utf-8").read()
    settings = json.load(open(os.path.join(folder, ".claude", "settings.json"), encoding="utf-8"))
    check(f"[{lang}] project: CLAUDE.md imports the rules, settings deny edits and set UTF-8",
          ("@.claude/ms43-rules.md" in claude_md,
           "Edit(/.claude/skills/log-review/**)" in settings["permissions"]["deny"],
           settings["env"]["PYTHONUTF8"], "SessionStart" in settings.get("hooks", {}),
           os.path.isfile(os.path.join(folder, "analysis", "STATE.md")),
           ".mcp.json" in open(os.path.join(folder, ".gitignore"), encoding="utf-8").read()),
          (True, True, "1", True, True, True))
    with open(os.path.join(folder, "CLAUDE.md"), "w", encoding="utf-8") as fh:
        fh.write("# My car\nE30 with M54B30, ZF gearbox.\n")
    settings["permissions"]["allow"] = ["Bash(git status)"]
    with open(os.path.join(folder, ".claude", "settings.json"), "w", encoding="utf-8") as fh:
        json.dump(settings, fh)
    call("ai_project", {"folder": folder, "name": "Test car", "server": "ms43"})
    call("ai_project", {"folder": folder, "name": "Test car", "server": "ms43"})
    claude_md = open(os.path.join(folder, "CLAUDE.md"), encoding="utf-8").read()
    settings = json.load(open(os.path.join(folder, ".claude", "settings.json"), encoding="utf-8"))
    check(f"[{lang}] project: the owner's CLAUDE.md and settings stay, the import is added once",
          (claude_md.startswith("# My car"), claude_md.count("@.claude/ms43-rules.md"),
           settings["permissions"].get("allow")), (True, 1, ["Bash(git status)"]))
    import subprocess
    hook = subprocess.run([sys.executable, os.path.join(folder, ".claude", "hooks", "session_check.py")],
                          capture_output=True, text=True, timeout=30)
    check(f"[{lang}] project: the session hook runs and reads the state file",
          (hook.returncode, "STATE.md" in hook.stdout), (0, True))
    check(f"[{lang}] project: connected to the live server through the bridge",
          (cfg["type"], cfg["env"]["MS43_URL"] in text, bool(cfg["env"]["MS43_TOKEN"]),
           os.path.isfile(cfg["args"][0])), ("stdio", True, True, True))
    check(f"[{lang}] project: placeholders filled", "{" not in text.replace("{n}", ""), True)
    skill = os.path.join(folder, ".claude", "skills", "ignition", "SKILL.md")
    with open(skill, "a", encoding="utf-8") as fh:
        fh.write("\nMy own note.\n")
    os.remove(os.path.join(folder, "tools", "ms43log.py"))
    again = call("ai_project", {"folder": folder, "name": "Test car", "server": "ms43"})["project_result"]
    check(f"[{lang}] project: an owner-edited file is kept, a missing one restored",
          (again["kept"], "tools/ms43log.py" in again["written"]),
          ([".claude/skills/ignition/SKILL.md"], True))
    check(f"[{lang}] project: remembered", call("ai_state")["project"]["exists"], True)
    check(f"[{lang}] project: first run wrote everything", len(res["written"]) >= 8, True)


def test_history() -> None:
    import shutil
    import tempfile

    from ms43diff import project

    tmp = tempfile.mkdtemp(prefix="ms43hist_")
    saved = os.environ.get("HOME"), os.environ.get("USERPROFILE")
    try:
        os.environ["HOME"] = os.environ["USERPROFILE"] = tmp
        folder = os.path.join(tmp, "tuner")
        os.makedirs(folder)
        before = project.has_history(folder)
        key = "".join(c if c.isalnum() else "-" for c in os.path.abspath(folder))
        os.makedirs(os.path.join(tmp, ".claude", "projects", key))
        open(os.path.join(tmp, ".claude", "projects", key, "s.jsonl"), "w").close()
        check("an earlier Claude Code conversation of the project is found",
              (before, project.has_history(folder)), (False, True))
    finally:
        for k, v in zip(("HOME", "USERPROFILE"), saved):
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        shutil.rmtree(tmp, ignore_errors=True)


def _check_bridge(lang: str, cfg: dict) -> None:
    """The bridge Claude Code starts: passes requests to the window; with the window closed
    it still lists the tools and says that the window is closed."""
    import json
    import socket
    import subprocess

    def run(url: str) -> list:
        msgs = [{"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2025-06-18"}},
                {"jsonrpc": "2.0", "method": "notifications/initialized"},
                {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
                {"jsonrpc": "2.0", "id": 3, "method": "tools/call",
                 "params": {"name": "firmware_info", "arguments": {}}}]
        env = {**os.environ, **cfg["env"], "MS43_URL": url}
        proc = subprocess.run([sys.executable, cfg["args"][0]], env=env, capture_output=True,
                              input="\n".join(json.dumps(m) for m in msgs) + "\n",
                              text=True, encoding="utf-8", timeout=60)
        return [json.loads(line) for line in proc.stdout.splitlines() if line.strip()]

    live = run(cfg["env"]["MS43_URL"])
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        dead_port = sock.getsockname()[1]
    closed = run(f"http://127.0.0.1:{dead_port}/mcp")
    tools = lambda a: len(a[1]["result"]["tools"])  # noqa: E731
    text = lambda a: a[2]["result"]["content"][0]["text"]  # noqa: E731
    check(f"[{lang}] bridge: the open window answers through it",
          (len(live), tools(live) > 20, live[2]["result"]["isError"]), (3, True, False))
    check(f"[{lang}] bridge: window closed - tools still listed, the call says so",
          (len(closed), tools(closed) == tools(live), "window is closed" in text(closed),
           closed[2]["result"]["isError"]), (3, True, True, True))


def test_logger() -> None:
    """The own logger against an emulated ECU: test, record, lose and regain the link."""
    import json
    import shutil
    import tempfile
    import time

    import tests_fixtures
    from ms43diff import ds2logger, tplog
    from ms43diff.adx import Adx

    print("\n--- Logger (emulated ECU) ---")
    tmp = tempfile.mkdtemp(prefix="ms43logger_")
    try:
        adx_path = os.path.join(tmp, "test.adx")
        with open(adx_path, "w", encoding="utf-8") as fh:
            fh.write(tests_fixtures.ADX)
        stock_path = os.path.join(tmp, "stock.adx")
        with open(stock_path, "w", encoding="utf-8") as fh:
            fh.write(tests_fixtures.STOCK_ADX)
        ecu = tests_fixtures.FakeEcu()
        res = ds2logger.test_connection(adx_path, lambda adx: ecu, None, stock_path)
        check("logger: connection test: ident, the request at 9600, then the fast mode",
              (res["ok"], res["mode"], res["ident"]["part"], res["values"]["Engine Speed"]),
              (True, "fast", "7545150", 802.0))
        check("logger: the journal has every step, the ECU is back at 9600",
              ([l["text"] for l in res["journal"] if l["dir"] in ("tx", "rx")], ecu.ecu_baud),
              (["IDENT", "IDENT", "DATAREQUEST", "DATAREPLY", "FASTCMD", "OKREPLY", "DATAREQUEST",
                "DATAREPLY", "SLOWCMD", "OKREPLYFAST"], 9600))
        silent = tests_fixtures.FakeEcu()
        silent.ecu_baud = 1
        res = ds2logger.test_connection(adx_path, lambda adx: silent)
        check("logger: no ECU is reported, not hidden", (res["ok"], bool(res["error"])), (False, True))
        running = tests_fixtures.FakeEcu()
        running.engine_running = True
        res = ds2logger.test_connection(adx_path, lambda adx: running, None, stock_path)
        check("logger: fast rate refused (A2, engine running) -> the same ADX at 9600",
              (res["ok"], res["mode"], any("refused" in st["text"] for st in res["steps"])),
              (True, "slow", True))
        bare = tests_fixtures.FakeEcu()
        bare.patched = False
        res = ds2logger.test_connection(adx_path, lambda adx: bare, None, stock_path)
        check("logger: 0B B0 unknown (B0, no patch) -> the standard ADX",
              (res["ok"], res["mode"], res["adx_used"]), (True, "stock", "stock.adx"))
        bare = tests_fixtures.FakeEcu()
        bare.patched = False
        res = ds2logger.test_connection(adx_path, lambda adx: bare)
        check("logger: no patch and no standard ADX: a clear refusal",
              (res["ok"], "DS2 Logging Feature Enhancement" in res["error"]), (False, True))
        bare = tests_fixtures.FakeEcu()
        bare.patched = False
        rec = ds2logger.Recorder(adx_path, lambda adx: bare, os.path.join(tmp, "logs_bare"))
        rec.start()
        time.sleep(1.5)
        rec.stop()
        check("logger: a refusal stops the recording, no reconnect loop",
              (rec.status["state"], rec.status["reconnects"], len(bare.sent) < 10), ("refused", 0, True))
        bare = tests_fixtures.FakeEcu()
        bare.patched = False
        bare.engine_running = True
        done_stock = []
        rec = ds2logger.Recorder(adx_path, lambda adx: bare, os.path.join(tmp, "logs_stock"),
                                 done_stock.append, stock_path)
        rec.start()
        time.sleep(1.0)
        rec.stop()
        check("logger: records with the standard ADX when the extended request is unknown",
              (rec.status["mode"], rec.status["rows"] > 10, len(done_stock),
               os.path.basename(rec.adx_path)), ("stock", True, 1, "stock.adx"))
        session = ds2logger.Session(Adx(adx_path), tests_fixtures.FakeEcu(), ds2logger.Journal(None))
        try:
            session.send(session.adx.commands["ERASE"])
            sent = "sent"
        except ds2logger.Ds2Error:
            sent = "refused"
        check("logger: a command outside the ADX macros is never sent", sent, "refused")
        ecu = tests_fixtures.FakeEcu()
        done = []
        rec = ds2logger.Recorder(adx_path, lambda adx: ecu, os.path.join(tmp, "logs"), done.append)
        rec.start()
        time.sleep(0.3)
        ecu.drop = 6                                   # the link drops ...
        ecu.ecu_baud = 125000                          # ... and the ECU stays at the fast rate
        time.sleep(3.0)
        rec.stop()
        check("logger: recorded, lost the link and reconnected",
              (rec.status["state"], rec.status["rows"] > 50, rec.status["errors"] >= 5, len(done)),
              ("stopped", True, True, 1))
        log = tplog.load(done[0])
        journal = [json.loads(line) for line in open(rec.raw_path, encoding="utf-8")]
        check("logger: the CSV loads like a TunerPro log and shows the gap",
              (log.col("Engine Speed")[0], len(tplog.quality(log)["gaps"]) >= 1), (802.0, True))
        check("logger: the raw journal notes the loss and the reconnect",
              ["connection lost (no answer), reconnecting" in [j.get("text") for j in journal],
               sum(1 for j in journal if str(j.get("text", "")).startswith("connected"))], [True, 2])
        check("logger: the ECU is left at 9600 after stop", ecu.ecu_baud, 9600)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_adx_pack() -> None:
    """The ADX pack: the list from the wiki pages, the download, the standard ADX, a suggestion."""
    import shutil
    import tempfile

    import tests_fixtures
    from ms43diff import adxpack, logcheck, wikicache

    print("\n--- ADX pack ---")
    tmp = tempfile.mkdtemp(prefix="ms43adx_")
    saved = wikicache.user_dir
    try:
        wikicache.user_dir = lambda: os.path.join(tmp, "wiki")
        pages = {
            "Logger_Definition_Files": '<a href="/index.php?title=File:Siemens_MS42_Extended_Log_v1.7_M52TUB25.adx">x</a>'
                                       '<a href="/index.php?title=File:Siemens_MS43_Extended_Log_v2.9_M54B30.adx">x</a>'
                                       '<a href="/index.php?title=File:Siemens_MS43_Extended_Log_v2.9_M54B25.adx">x</a>',
            "MS43X_Custom_Firmware": '<a href="/index.php?title=File:Siemens_MS43_MS43X001_Logging.adx">x</a>'
                                     '<a href="/index.php?title=File:Siemens_MS43_MS43X001_64K.xdf">x</a>',
            "TunerPro_MS43_Community_Patchlist":
                '<a href="/index.php?title=File:Siemens_MS43_MS430069_Community_Patchlist_v2.9.2.xdf">x</a>'
                '<a href="/index.php?title=File:Siemens_MS43_MS430069_Community_Patchlist_v2.5.xdf">x</a>'}

        def fetch(url, timeout):
            return next(v for k, v in pages.items() if url.endswith(k))

        def fetch_bytes(url, timeout):
            if url.endswith(".xdf"):
                return b"<XDFFORMAT version='1.60'></XDFFORMAT>"
            if "M54B25" in url:
                return b"<html>blocked</html>"
            return tests_fixtures.ADX.encode("utf-8")

        names = adxpack.listing(fetch)
        check("ADX pack: MS43 ADX and the newest patchlist, no MS42, no firmware XDF",
              sorted(names), sorted(["Siemens_MS43_Extended_Log_v2.9_M54B30.adx",
                                     "Siemens_MS43_Extended_Log_v2.9_M54B25.adx",
                                     "Siemens_MS43_MS43X001_Logging.adx",
                                     "Siemens_MS43_MS430069_Community_Patchlist_v2.9.2.xdf"]))
        res = adxpack.download(fetch_bytes=fetch_bytes, fetch=fetch)
        check("ADX pack: downloaded, a non-ADX answer refused", (len(res["files"]), len(res["errors"])), (3, 1))
        check("ADX pack: the program's own standard ADX until the pack has one",
              os.path.basename(adxpack.standard_adx()), adxpack.BUILTIN_STANDARD)
        from ms43diff.adx import Adx
        from ms43diff.ds2logger import adx_kind
        std = Adx(adxpack.standard_adx())
        reply = bytes.fromhex("12 2D A0 02 70 00 00 00 00 38 00 32 72 B3 9A 5F AE 01 DE F8 20 5E EC 8F 77 "
                              "89 7F FB 80 00 FE FE 00 00 14 83 06 20 07 1E 0D 2F 6E 87 EE")
        values = std.decode(std.listen_by_name["DATAREPLY"].idhash, reply[3:44])
        check("standard ADX: 0B 03 at 9600, rpm / coolant / lambda integrator from a real reply",
              (adx_kind(std)["request"], std.baud, values["Engine Speed"], round(values["Coolant Temperature"], 1),
               round(values["Lambda Integrator Bank 1"], 1)), ("0B 03", 9600, 624.0, 86.2, -0.0))
        rec = os.path.join(tmp, "rec.jsonl")
        with open(rec, "w", encoding="utf-8") as fh:
            for i in range(20):
                fh.write('{"t": %.3f, "hex": "%s"}\n' % (i * 0.12, reply.hex(" ").upper()))
        bin_path = os.path.join(tmp, "fw.bin")
        with open(bin_path, "wb") as fh:
            fh.write(b"\0" * 65536)
        from ms43diff import tplog
        dest = tplog.add_log(rec, os.path.join(tmp, "logs"), bin_path, bin_path, "", "")
        check("a raw 0B 03 recording (.jsonl) is added as a log with the standard ADX",
              (tplog.quality(tplog.load(dest))["rows"], os.path.basename(tplog.read_binding(dest)["adx"])),
              (20, adxpack.BUILTIN_STANDARD))
        with open(os.path.join(adxpack.folder(), "my_standard.adx"), "w", encoding="utf-8") as fh:
            fh.write(tests_fixtures.STOCK_ADX)
        check("ADX pack: a 0B 03 ADX in the folder is the standard one",
              os.path.basename(adxpack.standard_adx()), "my_standard.adx")
        check("ADX pack: the suggestion follows X001 and the engine",
              (os.path.basename(adxpack.recommend("43X001", "")),
               os.path.basename(adxpack.recommend("430069", adxpack.engine_of("E30 M54B30 swap")))),
              ("Siemens_MS43_MS43X001_Logging.adx", "Siemens_MS43_Extended_Log_v2.9_M54B30.adx"))
        check("ADX check: the standard request fits every MS43",
              logcheck.check(os.path.join(adxpack.folder(), "my_standard.adx"), "")["state"], "ok")
        check("ADX check: the extended one needs the firmware to tell",
              logcheck.check(os.path.join(adxpack.folder(), "Siemens_MS43_MS43X001_Logging.adx"), "")["state"],
              "unknown")
    finally:
        wikicache.user_dir = saved
        shutil.rmtree(tmp, ignore_errors=True)


def test_xdl() -> None:
    """A TunerPro .xdl decoded with its ADX, then added to a project like a CSV."""
    import json
    import shutil
    import tempfile

    import tests_fixtures
    from ms43diff import adx, tplog

    print("\n--- TunerPro .xdl ---")
    tmp = tempfile.mkdtemp(prefix="ms43xdl_")
    try:
        adx_path = os.path.join(tmp, "test.adx")
        with open(adx_path, "w", encoding="utf-8") as fh:
            fh.write(tests_fixtures.ADX)
        rows = [(i * 50, 800 + 10 * i, 184, 128 - (8 if i == 3 else 0), 4 if i > 6 else 0,
                 1 if i % 2 else 2) for i in range(10)]
        src = os.path.join(tmp, "drive.xdl")
        with open(src, "wb") as fh:
            fh.write(tests_fixtures.xdl(rows))
        out = os.path.join(tmp, "drive.csv")
        info = adx.xdl_to_csv(src, adx_path, out)
        check("xdl: every data packet decoded", (info["rows"], info["channels"], info["bad_packets"]),
              (10, 8, 0))
        log = tplog.load(out)
        check("xdl: 16-bit little-endian value with a mask, units",
              (log.col("Engine Speed")[2], log.units.get("Engine Speed")), (820.0, "rpm"))
        check("xdl: linked channel and lookup table",
              (log.col("Engine Speed Half")[2], log.col("Table Flag")[1], log.col("Table Flag")[2]),
              (410.0, 1.0, 0.0))
        check("xdl: bitmask as ON/OFF, time in seconds",
              (log.col("Trailing Throttle Fuel Cut")[6], log.col("Trailing Throttle Fuel Cut")[7],
               log.time[9]), (0.0, 1.0, 0.45))
        check("xdl: integer output drops the fraction like TunerPro (rpm high bits in the gear byte)",
              (log.col("Current Gear (Calculated)")[2], 0x83 / 32 > 4), (4.0, True))
        check("xdl: a flag without a parent packet is read from the data packet",
              (log.col("Engine Misfire")[0], log.col("Engine Misfire")[7]), (0.0, 0.0))
        check("xdl: knock found in the decoded log", [e["start"] for e in tplog.knock_events(log)],
              [0.15])
        fw = os.path.join(tmp, "fw.bin")
        with open(fw, "wb") as fh:
            fh.write(b"\0" * 64)
        try:
            tplog.add_log(src, os.path.join(tmp, "logs"), fw, adx_path)
            no_adx = "added"
        except tplog.LogError:
            no_adx = "refused"
        check("xdl: refused without its ADX", no_adx, "refused")
        dest = tplog.add_log(src, os.path.join(tmp, "logs"), fw, adx_path, "", adx_path)
        binding = tplog.read_binding(dest)
        check("xdl: added as CSV, the raw file kept, the ADX remembered",
              (os.path.basename(dest), os.path.isfile(os.path.join(tmp, "logs", binding["raw"])),
               binding["adx"] == os.path.abspath(adx_path), len(tplog.list_logs(os.path.join(tmp, "logs")))),
              ("drive.csv", True, True, 1))
        with open(tplog.binding_path(dest), encoding="utf-8") as fh:
            old = json.load(fh)
        old.pop("decoder")                              # as if made by the first decoder
        with open(tplog.binding_path(dest), "w", encoding="utf-8") as fh:
            json.dump(old, fh)
        stale = tplog.redecode_status(dest)
        tplog.redecode(dest)
        check("xdl: a log from an older decoder is offered and decoded again",
              (stale, tplog.redecode_status(dest), tplog.load(dest).n), ("old", "", 10))
        bad = os.path.join(tmp, "other.adx")
        with open(bad, "w", encoding="utf-8") as fh:
            fh.write(tests_fixtures.ADX.replace("0x0000AAAA", "0x0000CCCC"))
        try:
            adx.xdl_to_csv(src, bad, os.path.join(tmp, "x.csv"))
            wrong = "decoded"
        except adx.AdxError:
            wrong = "refused"
        check("xdl: a wrong ADX is refused", wrong, "refused")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_wiki_cache() -> None:
    """A failed download never wipes a working reference; import checks the file."""
    import json
    import shutil
    import tempfile
    import urllib.error

    from ms43diff import wikicache

    print("\n--- Reference cache ---")
    tmp = tempfile.mkdtemp(prefix="ms43wiki_")
    user, bundled = os.path.join(tmp, "user"), os.path.join(tmp, "bundled")
    os.makedirs(bundled)
    page = {"name": "Siemens_MS43", "title": "Siemens MS43", "url": "u", "fetched": "x",
            "sections": [{"heading": "Intro", "text": "c_conf_cat selects the catalyst"}]}
    with open(wikicache.cache_path(bundled), "w", encoding="utf-8") as fh:
        json.dump({"source": "s", "fetched": "2026", "pages": [page]}, fh)
    saved = (wikicache.user_dir, wikicache.bundled_dir, wikicache.urllib.request.urlopen)

    def offline(*_a, **_k):
        raise urllib.error.URLError("no route")

    try:
        wikicache.user_dir = lambda: user
        wikicache.bundled_dir = lambda: bundled
        check("bundled reference is used", len(wikicache.load(force=True)), 1)
        os.makedirs(user)
        with open(wikicache.cache_path(user), "w", encoding="utf-8") as fh:
            json.dump({"pages": []}, fh)
        check("an empty user cache does not hide the bundled one", len(wikicache.load(force=True)), 1)
        wikicache.urllib.request.urlopen = offline
        res = wikicache.download()
        check("offline download writes nothing", res["written"], False)
        check("offline download stops early", len(res["errors"]) <= 3, True)
        check("reference survives a failed update", len(wikicache.load(force=True)), 1)
        bad = os.path.join(tmp, "bad.json")
        with open(bad, "w", encoding="utf-8") as fh:
            fh.write('{"hello": 1}')
        try:
            wikicache.import_file(bad)
            check("a foreign file is refused", "imported", "refused")
        except ValueError:
            check("a foreign file is refused", True, True)
        res = wikicache.import_file(wikicache.cache_path(bundled))
        check("import writes the user cache", (res["pages"], wikicache.meta()["folder"]), (1, user))
        out = os.path.join(tmp, "copy.json")
        check("export saves a copy", wikicache.export_file(out), 1)

        def html(title, text):
            return (f"<html><head><title>{title} - MS4X Wiki</title></head><body>"
                    f'<div class="mw-parser-output"><h2>Intro</h2><p>{text}</p></div></body></html>')

        listing = {"query": {"allpages": [{"title": t_} for t_ in
                   ("Siemens MS43", "MS43 New Feature", "Siemens MS45 Notes", "Main Page")]}}

        def fake(url, timeout):
            if "api.php" in url:
                return json.dumps(listing)
            if "MS43_New_Feature" in url:
                return html("MS43 New Feature", "a new thing")
            if "MS45" in url:
                return html("Siemens MS45 Notes", "unlike the MS43 the MS45 ... MS43 ... MS43")
            return html("Some page", "text of " + url.rsplit("=", 1)[-1])

        saved_fetch = wikicache._fetch
        wikicache._fetch = fake
        try:
            res = wikicache.download()
            check("update finds new MS43 pages and skips the rest",
                  (res["added"], res["skipped"]), (["MS43_New_Feature"], ["Siemens_MS45_Notes"]))
            check("found pages count as expected", "MS43_New_Feature" in wikicache.expected_pages(), True)
            res = wikicache.download()
            check("skipped pages are not fetched again", (res["added"], res["skipped"]), ([], []))
            check("an added page stays", any(p.name == "MS43_New_Feature" for p in wikicache.load()), True)
            res = wikicache.add_pages(["Siemens_MS45_Notes"])
            check("a skipped page can be added by hand",
                  (res["added"], "Siemens_MS45_Notes" in wikicache.meta()["skipped"],
                   "Siemens_MS45_Notes" in wikicache.expected_pages()), (["Siemens_MS45_Notes"], False, True))
            # A redirect (another name of a page we have), a page with no article text
            # (a bot check), progress stages, and the web job reporting it.
            listing["query"]["allpages"].append({"title": "MS43"})
            good = {"Siemens_MS43": html("Siemens MS43", "c_conf_cat selects the catalyst")}

            def fake2(url, timeout):
                if "MS43_Pinout" in url:
                    return "<html><title>Just a moment</title><body>checking your browser</body></html>"
                if url.endswith("title=MS43") or url.endswith("title=Siemens_MS43"):
                    return good["Siemens_MS43"]
                return fake(url, timeout)

            wikicache._fetch = fake2
            before = next(p for p in wikicache.load() if p.name == "Siemens_MS43_Pinout").sections
            stages = []
            res = wikicache.download(progress=lambda i, n, name, stage="pages": stages.append(stage))
            pin = next(p for p in wikicache.load() if p.name == "Siemens_MS43_Pinout")
            check("a page without article text keeps its old copy and is reported",
                  (pin.sections == before, any(n == "Siemens_MS43_Pinout" for n, _ in res["errors"])),
                  (True, True))
            check("a redirect is not a missing page", ("MS43" in res["added"], res["missing"]), (False, []))
            check("progress reports every stage", sorted(set(stages)), ["listing", "new", "pages"])

            import time
            import types
            from ms43diff.webui import modes
            st = types.SimpleNamespace()
            first = modes.wiki_download(st, {})
            for _ in range(200):
                done = modes.wiki_progress(st, {})
                if done["job"] and done["job"]["done"]:
                    break
                time.sleep(0.05)
            check("the window updates the reference in the background with progress",
                  (first["job"]["done"], done["job"]["done"], "message" in done), (False, True, True))
        finally:
            wikicache._fetch = saved_fetch
    finally:
        wikicache.user_dir, wikicache.bundled_dir, wikicache.urllib.request.urlopen = saved
        wikicache.load(force=True)
        shutil.rmtree(tmp, ignore_errors=True)


def test_edits_core() -> None:
    """Edit guards that need no window: version mismatch, patches, naming."""
    import shutil
    import tempfile

    import tests_fixtures
    from ms43diff import edits
    from ms43diff.binfile import BinFile, Reader
    from ms43diff.xdf import XdfFile

    print("\n--- Edits ---")
    tmp = tempfile.mkdtemp(prefix="ms43edits_")
    try:
        f = tests_fixtures.build(tmp)
        xdf = XdfFile(f["xdf"])
        store = os.path.join(tmp, "drafts")
        wrong = edits.Draft(store, f["target"])
        wrong.add("value", "c_gr_rax_sp", {"value": 3.0}, "test")
        plan = edits.plan_draft(Reader(xdf, BinFile(f["target"])), wrong)
        check("edits refused on another software version", bool(plan.blockers), True)
        draft = edits.Draft(store, f["stock"])
        draft.add("patch", "Disable something", {"enable": True}, "test")
        plan = edits.plan_draft(Reader(xdf, BinFile(f["stock"])), draft, xdf)
        check("patch over its original bytes is accepted", (plan.ok, plan.needs_full_image), (True, True))
        tuned = edits.Draft(store, f["tuned"])
        tuned.add("patch", "Disable something", {"enable": True}, "test")
        plan = edits.plan_draft(Reader(xdf, BinFile(f["tuned"])), tuned, xdf)
        check("an applied patch writes nothing", len(plan.writes), 0)
        draft.add("cells", "ip_iga_ron_98_pl_ivvt__n__maf", {"cells": [{"y": 2500, "x": 999, "value": 1}]},
                  "test")
        plan = edits.plan_draft(Reader(xdf, BinFile(f["stock"])), draft, xdf)
        check("a cell off the axis breakpoints is refused", plan.plans[-1].ok, False)
        check("draft survives a restart", len(edits.Draft(store, f["stock"]).changes), 2)
        check("next file name", os.path.basename(edits.next_version_path(
            os.path.join(tmp, "a_v3.bin"))), "a_v4.bin")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


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
    test_car()
    test_history()
    test_edits_core()
    test_wiki_cache()
    test_xdl()
    test_adx_pack()
    test_logger()
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
