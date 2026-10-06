# -*- coding: utf-8 -*-
"""
Synthetic XDF/BIN/log files for selftest.py.

Real MS43 definitions and firmware cannot be shipped, so the end-to-end test
builds tiny stand-ins with the same structure: a calibration header with the
software version, a 16-bit constant, a 2D map with static axes, a 1D table,
a patch, a second "software version" with a renamed parameter and a different
formula, and a wideband log.
"""

from __future__ import annotations

import os
import struct

SIZE = 0x10000

# addresses
A_HEADER = 0x0000
A_RATIO = 0x06A2
A_IGN = 0x1000
A_LIMIT = 0x2000
A_PATCH = 0x3000
A_CODE = 0x5000


def _xdf(title: str, ign_title: str, ratio_eq: str) -> str:
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<XDFFORMAT version="1.70">
  <XDFHEADER>
    <fileversion>1.0</fileversion>
    <deftitle>{title}</deftitle>
    <description>Synthetic test definition</description>
    <author>selftest</author>
    <BASEOFFSET offset="0" subtract="0" />
    <DEFAULTS datasizeinbits="8" sigdigits="2" outputtype="1" signed="0" lsbfirst="1" float="0" />
    <REGION type="0xFFFFFFFF" startaddress="0x0" size="0x{SIZE:X}" regionflags="0x0" name="Binary File" desc="" />
    <CATEGORY index="0x0" name="Ignition" />
    <CATEGORY index="0x1" name="Gear" />
  </XDFHEADER>
  <XDFCONSTANT uniqueid="0x10">
    <title>c_gr_rax_sp</title>
    <description>Final drive ratio</description>
    <CATEGORYMEM index="0" category="2" />
    <EMBEDDEDDATA mmedaddress="0x{A_RATIO:X}" mmedelementsizebits="16" mmedtypeflags="0x02" />
    <units>-</units>
    <decimalpl>3</decimalpl>
    <MATH equation="{ratio_eq}"><VAR id="X" /></MATH>
  </XDFCONSTANT>
  <XDFTABLE uniqueid="0x20">
    <title>{ign_title}</title>
    <description>Ignition angle map for RON 98, part load</description>
    <CATEGORYMEM index="0" category="1" />
    <XDFAXIS id="x" uniqueid="0x0">
      <EMBEDDEDDATA mmedelementsizebits="8" mmedmajorstridebits="-32" />
      <indexcount>4</indexcount>
      <units>mg/stk</units>
      <LABEL index="0" value="100" /><LABEL index="1" value="200" />
      <LABEL index="2" value="300" /><LABEL index="3" value="400" />
      <MATH equation="X"><VAR id="X" /></MATH>
    </XDFAXIS>
    <XDFAXIS id="y" uniqueid="0x0">
      <EMBEDDEDDATA mmedelementsizebits="8" mmedmajorstridebits="-32" />
      <indexcount>4</indexcount>
      <units>rpm</units>
      <LABEL index="0" value="1000" /><LABEL index="1" value="2500" />
      <LABEL index="2" value="4000" /><LABEL index="3" value="6000" />
      <MATH equation="X"><VAR id="X" /></MATH>
    </XDFAXIS>
    <XDFAXIS id="z">
      <EMBEDDEDDATA mmedaddress="0x{A_IGN:X}" mmedelementsizebits="8" mmedrowcount="4" mmedcolcount="4" mmedtypeflags="0x02" />
      <units>deg CRK</units>
      <decimalpl>1</decimalpl>
      <MATH equation="0.375*X-23.625"><VAR id="X" /></MATH>
    </XDFAXIS>
  </XDFTABLE>
  <XDFTABLE uniqueid="0x30">
    <title>id_n_max_mt__gear</title>
    <description>Maximum engine speed per gear, manual gearbox</description>
    <CATEGORYMEM index="0" category="2" />
    <XDFAXIS id="x" uniqueid="0x0">
      <EMBEDDEDDATA mmedelementsizebits="8" mmedmajorstridebits="-32" />
      <indexcount>6</indexcount>
      <LABEL index="0" value="1" /><LABEL index="1" value="2" /><LABEL index="2" value="3" />
      <LABEL index="3" value="4" /><LABEL index="4" value="5" /><LABEL index="5" value="6" />
    </XDFAXIS>
    <XDFAXIS id="z">
      <EMBEDDEDDATA mmedaddress="0x{A_LIMIT:X}" mmedelementsizebits="8" mmedcolcount="6" mmedtypeflags="0x02" />
      <units>rpm</units>
      <decimalpl>0</decimalpl>
      <MATH equation="32.0*X"><VAR id="X" /></MATH>
    </XDFAXIS>
  </XDFTABLE>
  <XDFPATCH uniqueid="0x40">
    <title>Disable something</title>
    <description>Test patch for the selftest</description>
    <CATEGORYMEM index="0" category="1" />
    <XDFPATCHENTRY name="p1" address="0x{A_PATCH:X}" datasize="0x2" patchdata="AA55" basedata="0000" />
  </XDFPATCH>
</XDFFORMAT>
"""


def _bin(fw: str, ratio_raw: int, ign_delta: int = 0, limit_raw: int = 202,
         patched: bool = False, code_edit: bool = False) -> bytes:
    data = bytearray(SIZE)
    header = f"  {fw}.DAT  ".encode("ascii")
    data[A_HEADER:A_HEADER + len(header)] = header
    data[A_RATIO:A_RATIO + 2] = struct.pack("<H", ratio_raw)
    for r in range(4):
        for c in range(4):
            raw = 100 + r * 4 + c
            if r == 2 and c >= 2:
                raw += ign_delta
            data[A_IGN + r * 4 + c] = raw
    for g in range(6):
        data[A_LIMIT + g] = limit_raw
    if patched:
        data[A_PATCH:A_PATCH + 2] = b"\xAA\x55"
    if code_edit:
        data[A_CODE:A_CODE + 4] = b"\x12\x34\x56\x78"
    return bytes(data)


def _log() -> str:
    lines = ["Time;Engine Speed;Mass Air Flow;Wideband Lambda;Target Lambda;Coolant"]
    t = 0.0
    for _ in range(3):
        for rpm, load in ((2500, 200), (4000, 300)):
            for _ in range(20):
                lines.append(f"{t:.1f};{rpm};{load};1.05;1.00;90")
                t += 0.1
    return "\n".join(lines) + "\n"


def _wiki() -> dict:
    url = "https://www.ms4x.net/index.php?title=Siemens_MS43"
    return {
        "source": "https://www.ms4x.net", "note": "synthetic test data", "fetched": "2026-01-01 00:00",
        "pages": [{
            "name": "Siemens_MS43", "title": "Siemens MS43", "url": url, "fetched": "2026-01-01 00:00",
            "sections": [
                {"heading": "Rev limiter",
                 "text": "id_n_max_mt__gear - Maximum engine speed per gear for manual gearboxes.\n"
                         "Warning: Raising the limit above 7000 rpm can damage the valve train."},
                {"heading": "Configuration",
                 "text": "Configuration switch - Lambda sensor configuration (c_conf_cat)\n"
                         "0: Monitoring disabled\n4: Monitoring of both catalysts\n"
                         "After changing it recalculate the checksums."},
            ],
        }],
    }


def install_wiki(appdata: str) -> str:
    """Write the synthetic wiki where wikicache looks for the user cache."""
    import json

    folder = os.path.join(appdata, "ms43diff", "wiki")
    os.makedirs(folder, exist_ok=True)
    path = os.path.join(folder, "ms4x_wiki.json")
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(_wiki(), fh)
    return path


def build(folder: str) -> dict:
    """Write all fixture files into ``folder`` and return their paths."""
    os.makedirs(folder, exist_ok=True)
    files = {
        "xdf": ("test_430069.xdf", _xdf("430069 test", "ip_iga_ron_98_pl_ivvt__n__maf", "X*0.003906")),
        "xdf_x": ("test_43X001.xdf", _xdf("43X001 test", "ip_iga_ron98_pl__n__maf", "X*0.0390625")),
        "log": ("wideband.csv", _log()),
    }
    out = {}
    for key, (name, text) in files.items():
        path = os.path.join(folder, name)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(text)
        out[key] = path
    bins = {
        "stock": _bin("430069", 750),
        "tuned": _bin("430069", 820, ign_delta=6, limit_raw=210, patched=True, code_edit=True),
        "target": _bin("43X001", 75),
    }
    for key, data in bins.items():
        path = os.path.join(folder, f"{key}.bin")
        with open(path, "wb") as fh:
            fh.write(data)
        out[key] = path
    return out
