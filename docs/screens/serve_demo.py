# -*- coding: utf-8 -*-
"""
Start the web interface on the demo project (for the screenshots).

    python docs/screens/serve_demo.py WORK_FOLDER en [wiki.json]

Settings go to WORK_FOLDER, so the real ones are not touched. Prints the URL
and keeps serving until killed.
"""

import json
import os
import shutil
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

work, lang = sys.argv[1], sys.argv[2]
wiki = sys.argv[3] if len(sys.argv) > 3 else ""
os.environ["APPDATA"] = os.environ["XDG_CONFIG_HOME"] = os.path.join(work, "config")

import demo_data  # noqa: E402

f = demo_data.build(os.path.join(work, "files"))
if wiki:
    folder = os.path.join(work, "config", "ms43diff", "wiki")
    os.makedirs(folder, exist_ok=True)
    shutil.copy(wiki, os.path.join(folder, "ms4x_wiki.json"))
os.makedirs(os.path.join(work, "config", "ms43diff"), exist_ok=True)
with open(os.path.join(work, "config", "ms43diff", "settings.json"), "w") as fh:
    json.dump({"proj_xdf": f["xdf"], "proj_bin_a": f["stage1"], "proj_bin_b": f["stage2"],
               "proj_xdf2": f["xdf_x"], "proj_bin2": f["target"], "proj_patchlist": f["xdf"],
               "project_dir": os.path.join(work, "project"), "project_name": "Demo E46 330i",
               "lang": lang}, fh)

# a tuning project with two logs (before / after a flash) and an AI draft
import tests_fixtures  # noqa: E402
from ms43diff import tplog  # noqa: E402
from ms43diff.webui.server import State  # noqa: E402

logs = os.path.join(work, "project", "logs")
for name, fw in (("2026-10-01_cruise.csv", f["stage1"]), ("2026-10-07_cruise.csv", f["stage2"])):
    src = os.path.join(work, "files", name)
    with open(src, "w", encoding="utf-8") as fh:
        fh.write(tests_fixtures.tunerpro_log())
    tplog.add_log(src, logs, fw, f["xdf"], "98 RON, +12 °C, cruise 1500-4000 rpm")

# the owner's notes on the conditions of each log
for name, changed in (("2026-10-01_cruise.csv", "nothing"),
                      ("2026-10-07_cruise.csv", "flashed stage 2 (ignition +1.5° at part load)")):
    tplog.set_conditions(os.path.join(logs, name), {
        "where": "public_road", "fuel": "98 RON", "air_temp": "+12 °C",
        "complaint": "light knock at 2500 rpm", "changed": changed,
        "note": "cruise 1500-4000 rpm"})

# the car: what the owner picked, plus values waiting for the owner to accept
from ms43diff import car as carmod, i18n  # noqa: E402
from ms43diff.i18n import t  # noqa: E402

i18n.set_lang(lang)

project_dir = os.path.join(work, "project")
carmod.save(project_dir, {"model": "E46 330i (M54B30)", "gearbox": "zf_s5d_320z", "final_drive": "2.93",
                          "tire": "225/45 R17", "fuel": "98 RON", "modifications": ["cat", "rear_o2"]})
carmod.propose(project_dir, "per_1000", [9.62, 16.26, 24.39, 32.66, 40.5],
               t("logs: {list}", list="2026-10-07_cruise.csv"),
               t("steady driving in gears {gears}; the other gears from the steps of {box}",
                 gears="3, 4, 5", box="ZF S5D 320Z / 310Z"))
carmod.propose(project_dir, "speed_sensor", "abs_front", "Claude",
               t("the owner said: stock E46, the speed comes from the ABS (front wheels)"))

from ms43diff.webui import start  # noqa: E402

state = State()
draft = state.draft(f["stage2"])
draft.clear()
draft.add("region", "ip_iga_ron_98_pl_ivvt__n__maf",
          {"op": "add", "amount": -0.75, "y_from": 2400, "y_to": 2400, "x_from": 200, "x_to": 200},
          "2026-10-07_cruise.csv: knock on cyl 4 at 20.0-20.1 s, 2500 rpm / 200 mg/stk, down to -3°; "
          "take 0.75° out of that cell and log the same drive again",
          evidence={"log": "2026-10-07_cruise.csv", "bin_sha1": tplog.sha1_file(f["stage2"])})
draft.add("region", "id_n_max_mt__gear", {"op": "add", "amount": 128},
          "owner's request for the track: rev limit +128 rpm in every gear")
state.ai.project_create(project_dir, "Demo E46 330i", state.ai.servers[0]["name"])
srv = start(state)
print(srv.url, flush=True)
while True:
    time.sleep(1)
