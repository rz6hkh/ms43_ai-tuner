# -*- coding: utf-8 -*-
"""
Demo project for the README screenshots.

Real MS43 definitions and firmware cannot be published, so this builds a
believable stand-in: a 430069-style XDF with real parameter names, two tunes
(stage 1 and stage 2), a custom software version with a renamed map and a
different scale, a few patches and a wideband log with a lean area.

    python docs/screens/demo_data.py OUT_FOLDER
"""

from __future__ import annotations

import math
import os
import struct
import sys

SIZE = 0x10000
RPM16 = [600, 800, 1000, 1300, 1600, 2000, 2400, 2800, 3200, 3600, 4000, 4500, 5000, 5500, 6000, 6500]
MAF12 = [80, 120, 160, 200, 260, 320, 380, 440, 500, 580, 660, 740]
MAP12 = [200, 300, 400, 500, 600, 650, 700, 750, 800, 850, 900, 950]

CATS = ["Ignition", "Vanos", "Engine Speed", "Config Switches", "Injection", "DISA",
        "Airflow Meter", "Checksums", "Catalyst", "Secondary Air"]


class Xdf:
    """Collects XDF items and the raw bytes they describe."""

    def __init__(self, title: str):
        self.title = title
        self.items: list = []
        self.patches: list = []
        self.uid = 0x100

    def _cat(self, name: str) -> int:
        return CATS.index(name) + 1

    def const(self, title, desc, cat, addr, units, eq, bits=8, dec=0):
        self.uid += 1
        self.items.append(f"""  <XDFCONSTANT uniqueid="0x{self.uid:X}">
    <title>{title}</title>
    <description>{desc}</description>
    <CATEGORYMEM index="0" category="{self._cat(cat)}" />
    <EMBEDDEDDATA mmedaddress="0x{addr:X}" mmedelementsizebits="{bits}" mmedtypeflags="0x02" />
    <units>{units}</units>
    <decimalpl>{dec}</decimalpl>
    <MATH equation="{eq}"><VAR id="X" /></MATH>
  </XDFCONSTANT>""")

    @staticmethod
    def _axis(aid, labels, units):
        lab = "".join(f'<LABEL index="{i}" value="{v}" />' for i, v in enumerate(labels))
        return f"""    <XDFAXIS id="{aid}" uniqueid="0x0">
      <EMBEDDEDDATA mmedelementsizebits="8" mmedmajorstridebits="-32" />
      <indexcount>{len(labels)}</indexcount>
      <units>{units}</units>
      {lab}
      <MATH equation="X"><VAR id="X" /></MATH>
    </XDFAXIS>"""

    def table(self, title, desc, cat, addr, units, eq, cols, cols_units, rows=None,
              rows_units="", bits=8, dec=1):
        self.uid += 1
        nrows = len(rows) if rows else 1
        y = self._axis("y", rows, rows_units) if rows else ""
        self.items.append(f"""  <XDFTABLE uniqueid="0x{self.uid:X}">
    <title>{title}</title>
    <description>{desc}</description>
    <CATEGORYMEM index="0" category="{self._cat(cat)}" />
{self._axis("x", cols, cols_units)}
{y}
    <XDFAXIS id="z">
      <EMBEDDEDDATA mmedaddress="0x{addr:X}" mmedelementsizebits="{bits}" mmedrowcount="{nrows}" mmedcolcount="{len(cols)}" mmedtypeflags="0x02" />
      <units>{units}</units>
      <decimalpl>{dec}</decimalpl>
      <MATH equation="{eq}"><VAR id="X" /></MATH>
    </XDFAXIS>
  </XDFTABLE>""")

    def patch(self, title, desc, cat, addr, data, base):
        self.uid += 1
        self.patches.append(f"""  <XDFPATCH uniqueid="0x{self.uid:X}">
    <title>{title}</title>
    <description>{desc}</description>
    <CATEGORYMEM index="0" category="{self._cat(cat)}" />
    <XDFPATCHENTRY name="p1" address="0x{addr:X}" datasize="0x{len(data) // 2:X}" patchdata="{data}" basedata="{base}" />
  </XDFPATCH>""")

    def text(self) -> str:
        cats = "\n".join(f'    <CATEGORY index="0x{i:X}" name="{c}" />' for i, c in enumerate(CATS))
        body = "\n".join(self.items + self.patches)
        return f"""<?xml version="1.0" encoding="UTF-8"?>
<XDFFORMAT version="1.70">
  <XDFHEADER>
    <fileversion>1.3</fileversion>
    <deftitle>{self.title}</deftitle>
    <description>Demo definition for screenshots</description>
    <author>demo</author>
    <BASEOFFSET offset="0" subtract="0" />
    <DEFAULTS datasizeinbits="8" sigdigits="2" outputtype="1" signed="0" lsbfirst="1" float="0" />
    <REGION type="0xFFFFFFFF" startaddress="0x0" size="0x{SIZE:X}" regionflags="0x0" name="Binary File" desc="" />
{cats}
  </XDFHEADER>
{body}
</XDFFORMAT>
"""


# ---------------------------------------------------------------------------
# values (physical) for the stock file and the tunes
# ---------------------------------------------------------------------------

def ignition(stage: int):
    out = []
    for r, rpm in enumerate(RPM16):
        row = []
        for c, maf in enumerate(MAF12):
            load = c / (len(MAF12) - 1)
            base = 12 + 30 * (1 - load) ** 1.3 + 8 * min(rpm, 4500) / 4500 * (1 - 0.5 * load)
            if stage and rpm >= 2800 and load > 0.45:
                base += (1.5 if stage == 1 else 3.0) * min(1, (load - 0.45) / 0.3)
            row.append(base)
        out.append(row)
    return out


def vanos(stage: int):
    out = []
    for r, rpm in enumerate(RPM16):
        row = []
        for c, _ in enumerate(MAF12):
            load = c / (len(MAF12) - 1)
            v = 120 - 25 * load * math.sin(min(rpm, 5000) / 5000 * math.pi)
            if stage == 2 and rpm >= 4500:
                v -= 6 * load
            row.append(v)
        out.append(row)
    return out


def ve(scale_lean: bool):
    out = []
    for r, p in enumerate(MAP12):
        row = []
        for c, rpm in enumerate(RPM16):
            v = 0.62 + 0.3 * (p / 950) + 0.08 * math.sin(rpm / 6500 * math.pi)
            row.append(v)
        out.append(row)
    return out


def build(folder: str) -> dict:
    os.makedirs(folder, exist_ok=True)

    def define(title, ign_name, ratio_eq, ign_eq):
        x = Xdf(title)
        x.const("c_gr_rax_sp", "Final drive ratio", "Engine Speed", 0x06A2, "-", ratio_eq, 16, 3)
        x.table(ign_name, "Ignition angle map for RON 98, part load, with VANOS",
                "Ignition", 0x1000, "°CRK", ign_eq, MAF12, "mg/stk", RPM16, "rpm")
        x.table("ip_iga_ron_91_pl_ivvt__n__maf", "Ignition angle map for RON 91, part load, with VANOS",
                "Ignition", 0x1100, "°CRK", "0.375*X-23.625", MAF12, "mg/stk", RPM16, "rpm")
        x.table("ip_cam_sp_tco_1_in_pl__n__maf_iv", "Intake camshaft setpoint, part load, warm engine",
                "Vanos", 0x1200, "°CRK", "0.375*X+60", MAF12, "mg/stk", RPM16, "rpm")
        x.table("id_n_max_mt__gear", "Maximum engine speed per gear, manual gearbox", "Engine Speed",
                0x2000, "rpm", "32.0*X", [1, 2, 3, 4, 5, 6], "", dec=0)
        x.table("id_n_max_max_mt__gear", "Hard engine speed limit per gear, manual gearbox",
                "Engine Speed", 0x2010, "rpm", "32.0*X", [1, 2, 3, 4, 5, 6], "", dec=0)
        x.const("c_vs_max_mt_1", "Maximum vehicle speed, manual gearbox", "Engine Speed", 0x2020,
                "km/h", "X", 8, 0)
        x.const("c_conf_cat", "Configuration of catalyst diagnosis", "Config Switches", 0x2100, "-", "X")
        x.const("c_conf_sap", "Configuration of secondary air system", "Config Switches", 0x2101, "-", "X")
        x.const("c_conf_mil", "Configuration of malfunction indicator lamp", "Config Switches", 0x2102, "-", "X")
        x.table("ip_map_ve_1__map__n", "Volumetric efficiency, intake manifold pressure and engine speed",
                "Injection", 0x3000, "-", "X*0.0000305", RPM16, "rpm", MAP12, "hPa", bits=16, dec=3)
        x.table("id_vim_pl__n_vim__maf", "DISA switching threshold, part load", "DISA", 0x3200, "rpm",
                "32.0*X", [100, 200, 300, 400, 500, 600], "mg/stk", dec=0)
        x.table("id_maf_tab__v_maf_1__v_maf_2", "Airflow meter characteristic", "Airflow Meter", 0x3300,
                "kg/h", "X*2", [1.0, 1.5, 2.0, 2.5, 3.0, 3.5, 4.0, 4.5], "V", dec=0)
        x.const("cal_cks", "Calibration checksum", "Checksums", 0x7FF0, "-", "X", 16)
        x.patch("Disable secondary air pump", "Secondary air system off, no fault codes",
                "Secondary Air", 0x5000, "0000", "01A0")
        x.patch("Disable post-cat O2 sensor diagnosis", "For removed catalysts",
                "Catalyst", 0x5010, "00000000", "8F12A000")
        x.patch("Ignition cut limiter", "Rev limiter by ignition cut instead of fuel cut",
                "Ignition", 0x5020, "E6F40100", "E6F40000")
        return x

    xdf = define("430069 demo", "ip_iga_ron_98_pl_ivvt__n__maf", "X*0.003906", "0.375*X-23.625")
    xdf_x = define("43X001 demo", "ip_iga_ron98_pl__n__maf", "X*0.0390625", "0.375*X-23.625")

    def raw8(value, k, b):
        return max(0, min(255, round((value - b) / k)))

    def firmware(fw: str, stage: int, ratio_raw: int):
        data = bytearray(SIZE)
        header = f"  {fw}.DAT  ".encode("ascii")
        data[0:len(header)] = header
        data[0x06A2:0x06A4] = struct.pack("<H", ratio_raw)
        for base, values in ((0x1000, ignition(stage)), (0x1100, ignition(0)), (0x1200, vanos(stage))):
            flat = [v for row in values for v in row]
            k, b = (0.375, -23.625) if base != 0x1200 else (0.375, 60)
            data[base:base + len(flat)] = bytes(raw8(v, k, b) for v in flat)
        limit = {0: 6500, 1: 6750, 2: 7000}[stage]
        data[0x2000:0x2006] = bytes([round(limit / 32)] * 6)
        data[0x2010:0x2016] = bytes([round((limit + 150) / 32)] * 6)
        data[0x2020] = 250 if stage < 2 else 255
        data[0x2100] = 4 if stage < 2 else 0
        data[0x2101] = 1 if stage < 2 else 0
        data[0x2102] = 1
        flat = [v for row in ve(False) for v in row]
        for i, v in enumerate(flat):
            data[0x3000 + 2 * i:0x3002 + 2 * i] = struct.pack("<H", round(v / 0.0000305))
        data[0x3200:0x3206] = bytes(round(v / 32) for v in (3600, 3700, 3800, 4000, 4200, 4400))
        data[0x3300:0x3308] = bytes(round(v / 2) for v in (10, 40, 90, 160, 250, 350, 440, 500))
        data[0x5000:0x5002] = b"\x01\xA0" if stage < 2 else b"\x00\x00"
        data[0x5010:0x5014] = b"\x8F\x12\xA0\x00" if stage < 2 else b"\x00\x00\x00\x00"
        data[0x5020:0x5024] = b"\xE6\xF4\x00\x00" if stage == 0 else b"\xE6\xF4\x01\x00"
        if stage:
            data[0x6000:0x6010] = bytes(range(16 * stage, 16 * stage + 16))  # code edit
        data[0x7FF0:0x7FF2] = struct.pack("<H", 0x1234 + stage)
        return bytes(data)

    out = {}
    for key, name, text in (("xdf", "Siemens_MS43_430069_demo.xdf", xdf.text()),
                            ("xdf_x", "Siemens_MS43X001_demo.xdf", xdf_x.text())):
        path = os.path.join(folder, name)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(text)
        out[key] = path
    for key, name, data in (("stock", "430069_stock.bin", firmware("430069", 0, 750)),
                            ("stage1", "430069_stage1.bin", firmware("430069", 1, 750)),
                            ("stage2", "430069_stage2.bin", firmware("430069", 2, 820)),
                            ("target", "43X001_stock.bin", firmware("43X001", 0, 75))):
        path = os.path.join(folder, name)
        with open(path, "wb") as fh:
            fh.write(data)
        out[key] = path

    # wideband log: steady points, lean (about +7 %) around 3000-4500 rpm and 650-850 hPa
    lines = ["Time;Engine Speed;Manifold Pressure;Wideband Lambda;Target Lambda;Coolant"]
    t = 0.0
    for p in MAP12:
        for rpm in RPM16:
            if (p >= 900 and rpm < 1300) or (p <= 300 and rpm > 5000):
                continue  # never reached on the road
            lean = 1.07 if 2800 <= rpm <= 4500 and 650 <= p <= 850 else 1.0
            target = 0.88 if p >= 900 else 1.0
            for i in range(12):
                wobble = 0.006 * math.sin(i * 1.7 + rpm / 500)
                lines.append(f"{t:.1f};{rpm + 10 * math.sin(i)};{p};{target * lean + wobble:.3f};{target};90")
                t += 0.1
    log = os.path.join(folder, "wideband_log.csv")
    with open(log, "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines) + "\n")
    out["log"] = log
    return out


if __name__ == "__main__":
    print(build(sys.argv[1] if len(sys.argv) > 1 else "demo"))
