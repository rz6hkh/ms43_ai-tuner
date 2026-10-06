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
               "proj_velog": f["log"], "lang": lang}, fh)

from ms43diff.webui import start  # noqa: E402

srv = start()
print(srv.url, flush=True)
while True:
    time.sleep(1)
