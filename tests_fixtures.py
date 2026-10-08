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


def gear_log() -> str:
    """Steady driving 8 s in 2nd..5th gear of a ZF S5D 320Z, final drive 2.93, 1.872 m tyres,
    the speed reading 2 % high, updated once a second as whole km/h; accelerations between."""
    import math as _m

    per_1000 = [60 * 1.872 / (r * 2.93) * 1.02 for r in (4.21, 2.49, 1.66, 1.24, 1.00)]
    lines = ["TunerPro log", "Sample,Time,Engine Speed,Vehicle Speed,Current Gear (Calculated),",
             "Sample #,Seconds,Engine Speed (rpm),Vehicle Speed (km/h),Current Gear (Calculated) (),"]
    plan = [(2, 2200), (3, 2100), (4, 2000), (5, 2300)]
    tm, i, shown = 0.0, 0, 0.0
    for gear, rpm0 in plan:
        for phase in ("steady", "accel"):
            for k in range(160 if phase == "steady" else 60):
                rpm = rpm0 * (1 + 0.004 * _m.sin(k)) if phase == "steady" else rpm0 + 25 * k
                speed = rpm * per_1000[gear - 1] / 1000
                if abs(tm - round(tm)) < 0.026:          # the speed updates once a second
                    shown = float(round(speed))
                lines.append(f"{i},{tm:.2f},{rpm:.0f},{shown:.0f},{gear},")
                tm += 0.05
                i += 1
    return "\n".join(lines) + "\n"


def tunerpro_log() -> str:
    """A TunerPro-style log (title, header, units row, trailing commas, ON/OFF).

    0-10 s cold idle; 10-21 s 2500 rpm / 200 mg/stk, knock on cyl 4 at 20.0 s;
    21-30 s 4000 rpm / 300 mg/stk while that retard recovers (no new knock);
    30-32 s a throttle stab with knock on cyl 2 (a transient); 32-35 s overrun.
    """
    knock = ["Knock Correction Cyl %d" % c for c in range(1, 7)]
    head = ["", "Time", "Engine Speed", "Engine Load Ignition", "Coolant Temperature",
            "Throttle Body Position", "Trailing Throttle Fuel Cut", "Lambda Control 1",
            "Short Term Fuel Trim Bank 1"] + knock
    units = ["Sample #", "Seconds", "Engine Speed (rpm)", "Engine Load Ignition (mg/stk)",
             "Coolant Temperature (°C)", "Throttle Body Position (%)",
             "Trailing Throttle Fuel Cut ()", "Lambda Control 1 ()",
             "Short Term Fuel Trim Bank 1 (%)"] + ["%s (°CRK)" % k for k in knock]
    lines = ["TunerPro Engine data log recorded on 2026-10-07", ",".join(head) + ",",
             ",".join(units) + ","]
    cyl4 = cyl2 = 0.0
    for i in range(700):
        tm = i * 0.05
        coolant = 60 + 2 * tm if tm < 10 else 90
        rpm, load, thr, cut = 1000, 100, 3.0, "OFF"
        if 10 <= tm < 21:
            rpm, load, thr = 2500, 200, 15.0
        elif 21 <= tm < 30:
            rpm, load, thr = 4000, 300, 25.0
        elif 30 <= tm < 32:
            rpm, load = 4000, 400
            thr = min(80.0, 25 + (tm - 30) * 120)
        elif tm >= 32:
            rpm, load, thr, cut = 2500, 100, 0.0, "ON"
        if abs(tm - 20.0) < 1e-6:
            cyl4 = -1.5
        elif abs(tm - 20.1) < 1e-6:
            cyl4 = -3.0
        elif cyl4 < 0 and i % 10 == 0:
            cyl4 = min(0.0, cyl4 + 0.375)
        if abs(tm - 30.2) < 1e-6:
            cyl2 = -0.75
        elif cyl2 < 0 and i % 10 == 0:
            cyl2 = min(0.0, cyl2 + 0.375)
        ks = ["0", str(cyl2), "0", str(cyl4), "0", "0"]
        closed = "ON" if coolant >= 80 and cut == "OFF" and thr < 40 else "OFF"
        trim = ("4.0" if rpm == 2500 else "-2.0") if closed == "ON" else "0.0"
        lines.append(",".join([str(i), "%.2f" % tm, str(rpm), str(load), "%.1f" % coolant,
                               "%.1f" % thr, cut, closed, trim] + ks) + ",")
    return "\n".join(lines) + "\n"


ADX = """<ADXFORMAT version="1.01">
  <ADXHEADER>
    <desc>synthetic logger definition</desc>
    <baud>9600</baud>
    <parity>2</parity>
    <connectcmd>FAST</connectcmd>
    <monitorcmd>MONITOR</monitorcmd>
    <disconnectcmd>SLOW</disconnectcmd>
    <DEFAULTS datasizeinbits="8" sigdigits="2" outputtype="3" baud="0" signed="0" lsbfirst="0" float="0" />
  </ADXHEADER>
  <ADXLOOKUPTABLE id="ONEZERO" idhash="0x00000099" title="one/zero">
    <tableentry input="1.000000" output="1.000000" />
    <tableentry input="2.000000" output="0.000000" />
  </ADXLOOKUPTABLE>
  <ADXVALUE id="N" idhash="0x00000011" title="Engine Speed">
    <flags>0x00000002</flags>
    <parentcmdidhash>0x0000AAAA</parentcmdidhash>
    <units>Engine Speed (rpm)</units>
    <packetoffset>0x00</packetoffset>
    <sizeinbits>16</sizeinbits>
    <MATH equation="X&amp;8191"><VAR varID="X" type="native" /></MATH>
  </ADXVALUE>
  <ADXVALUE id="TCO" idhash="0x00000012" title="Coolant Temperature">
    <parentcmdidhash>0x0000AAAA</parentcmdidhash>
    <units>Coolant Temperature (&#176;C)</units>
    <packetoffset>0x02</packetoffset>
    <MATH equation="0.75*X-48.0"><VAR varID="X" type="native" /></MATH>
  </ADXVALUE>
  <ADXVALUE id="KNK4" idhash="0x00000013" title="Knock Correction Cyl 4">
    <parentcmdidhash>0x0000AAAA</parentcmdidhash>
    <units>Knock Correction Cyl 4 (&#176;CRK)</units>
    <packetoffset>0x03</packetoffset>
    <MATH equation="0.375*X-48.0"><VAR varID="X" type="native" /></MATH>
  </ADXVALUE>
  <ADXVALUE id="HALF" idhash="0x00000014" title="Engine Speed Half">
    <parentcmdidhash>0x0000AAAA</parentcmdidhash>
    <packetoffset>0x00</packetoffset>
    <MATH equation="N/2"><VAR varID="N" type="link" linkIDHash="0x00000011" /></MATH>
  </ADXVALUE>
  <ADXVALUE id="TAB" idhash="0x00000015" title="Table Flag">
    <parentcmdidhash>0x0000AAAA</parentcmdidhash>
    <packetoffset>0x05</packetoffset>
    <MATH equation="X&amp;15" lookupidhash="0x00000099"><VAR varID="X" type="native" /></MATH>
  </ADXVALUE>
  <ADXVALUE id="GEAR" idhash="0x00000017" title="Current Gear (Calculated)">
    <parentcmdidhash>0x0000AAAA</parentcmdidhash>
    <units>Gear</units>
    <packetoffset>0x01</packetoffset>
    <outputtype>1</outputtype>
    <MATH equation="X/32"><VAR varID="X" type="native" /></MATH>
  </ADXVALUE>
  <ADXBITMASK id="NOPARENT" idhash="0x00000018" title="Engine Misfire">
    <truestring>ON</truestring>
    <falsestring>OFF</falsestring>
    <packetoffset>0x04</packetoffset>
    <operand>0x00000010</operand>
    <bitop>AND</bitop>
    <result>0x00000010</result>
  </ADXBITMASK>
  <ADXBITMASK id="CUT" idhash="0x00000016" title="Trailing Throttle Fuel Cut">
    <parentcmdidhash>0x0000AAAA</parentcmdidhash>
    <truestring>ON</truestring>
    <falsestring>OFF</falsestring>
    <packetoffset>0x04</packetoffset>
    <operand>0x00000004</operand>
    <bitop>AND</bitop>
  </ADXBITMASK>
  <ADXCLISTENPACKET id="HELLO" idhash="0x0000BBBB" title="Hello">
    <packetsize>0</packetsize>
  </ADXCLISTENPACKET>
  <ADXCLISTENPACKET id="DATAREPLY" idhash="0x0000AAAA" title="Data Reply">
    <baud>125000</baud>
    <listentimeout>200</listentimeout>
    <packetsize>6</packetsize>
    <headerstring size="3">120AA0</headerstring>
  </ADXCLISTENPACKET>
  <ADXMACRO id="MONITOR" idhash="0x00000101" title="Monitor">
    <NODE commandID="DATAREQUEST" repeatcount="1" />
    <NODE commandID="DATAREPLY" repeatcount="1" />
  </ADXMACRO>
  <ADXMACRO id="FAST" idhash="0x00000102" title="Fast">
    <NODE commandID="FASTCMD" repeatcount="1" />
    <NODE commandID="OKREPLY" repeatcount="1" />
  </ADXMACRO>
  <ADXMACRO id="SLOW" idhash="0x00000103" title="Slow">
    <NODE commandID="SLOWCMD" repeatcount="1" />
    <NODE commandID="OKREPLYFAST" repeatcount="1" />
  </ADXMACRO>
  <ADXCSENDCOMMAND id="FASTCMD" idhash="0x00000104" title="125000 baud">
    <bytestring size="0x8">12089101E848002A</bytestring>
  </ADXCSENDCOMMAND>
  <ADXCSENDCOMMAND id="SLOWCMD" idhash="0x00000105" title="9600 baud">
    <baud>125000</baud>
    <bytestring size="0x8">120891002580002E</bytestring>
  </ADXCSENDCOMMAND>
  <ADXCSENDCOMMAND id="DATAREQUEST" idhash="0x00000106" title="Data request">
    <baud>125000</baud>
    <bytestring size="0x5">12050BB0AC</bytestring>
  </ADXCSENDCOMMAND>
  <ADXCSENDCOMMAND id="ERASE" idhash="0x00000107" title="Not in any macro">
    <bytestring size="0x4">12040000</bytestring>
  </ADXCSENDCOMMAND>
  <ADXCLISTENPACKET id="OKREPLY" idhash="0x00000108" title="OK">
    <listentimeout>200</listentimeout>
    <packetsize>0</packetsize>
    <headerstring size="4">1204A0B6</headerstring>
  </ADXCLISTENPACKET>
  <ADXCLISTENPACKET id="OKREPLYFAST" idhash="0x00000109" title="OK fast">
    <baud>125000</baud>
    <listentimeout>200</listentimeout>
    <packetsize>0</packetsize>
    <headerstring size="4">1204A0B6</headerstring>
  </ADXCLISTENPACKET>
</ADXFORMAT>
"""


# The standard logging definition: 0B 03 at 9600, no baud switch (the same channels here).
STOCK_ADX = (ADX.replace("<connectcmd>FAST</connectcmd>", "<connectcmd></connectcmd>")
             .replace("<disconnectcmd>SLOW</disconnectcmd>", "<disconnectcmd></disconnectcmd>")
             .replace("<desc>synthetic logger definition</desc>", "<desc>synthetic standard logging</desc>")
             .replace("""    <baud>125000</baud>
    <bytestring size="0x5">12050BB0AC</bytestring>""", """    <bytestring size="0x5">12050B031F</bytestring>""")
             .replace("""    <baud>125000</baud>
    <listentimeout>200</listentimeout>
    <packetsize>6</packetsize>""", """    <listentimeout>200</listentimeout>
    <packetsize>6</packetsize>"""))


class FakeEcu:
    """A K+DCAN cable with an MS43 behind it, for the logger tests.

    Echoes what is sent, answers only at the baud rate it is at, switches to
    125000 on the FASTCMD and back on SLOWCMD, sends noise before some replies
    and can go silent for a number of requests (`drop`).
    """

    def __init__(self, echo: bool = True):
        import threading as _th

        self.baud = 9600
        self.ecu_baud = 9600
        self.echo = echo
        self.out = bytearray()
        self.lock = _th.Lock()
        self.requests = 0
        self.drop = 0
        self.engine_running = False
        self.patched = True        # knows the extended request 0B B0
        self.sent: list = []

    def set_baud(self, baud):
        self.baud = baud

    def _reply(self, payload: bytes) -> bytes:
        frame = bytearray([0x12, len(payload) + 3]) + payload
        x = 0
        for b in frame:
            x ^= b
        return bytes(frame) + bytes([x])

    def write(self, data: bytes):
        self.sent.append(bytes(data))
        with self.lock:
            if self.echo:
                self.out += data
            if self.baud != self.ecu_baud:
                return                                    # the ECU hears noise
            if data == bytes.fromhex("12089101E848002A"):
                if self.engine_running:                   # the ECU refuses the fast rate
                    self.out += self._reply(b"\xA2")
                    return
                self.out += self._reply(b"\xA0")
                self.ecu_baud = 125000
            elif data == bytes.fromhex("120891002580002E"):
                self.out += self._reply(b"\xA0")
                self.ecu_baud = 9600
            elif data == bytes.fromhex("12040016"):
                self.out += self._reply(b"\xA0" + b"7545150 19 00156\x00")
            elif data == bytes.fromhex("12050BB0AC") and not self.patched:
                self.out += self._reply(b"\xB0")
            elif data in (bytes.fromhex("12050BB0AC"), bytes.fromhex("12050B031F")):
                self.requests += 1
                if self.drop > 0:
                    self.drop -= 1
                    return
                n = self.requests
                body = (800 + n).to_bytes(2, "little") + bytes([184, 128, 4 if n % 2 else 0, 1])
                if n % 7 == 0:
                    self.out += b"\x00\xff"                 # noise before the reply
                self.out += self._reply(b"\xA0" + body)

    def read(self, timeout):
        import time as _t

        end = _t.monotonic() + timeout
        while True:
            with self.lock:
                if self.out:
                    data, self.out[:] = bytes(self.out), b""
                    return data
            if _t.monotonic() >= end:
                return b""
            _t.sleep(0.001)

    def reset_input(self):
        with self.lock:
            self.out.clear()

    def close(self):
        pass


def xdl(rows) -> bytes:
    """A TunerPro .xdl with the given (ms, rpm, coolant_raw, knock_raw, flags, table) rows.

    The packet index carries garbage in its upper bytes, like real files do.
    """
    import struct as _s

    header = bytearray(_s.pack("<III", 3, 0, 0))
    header += _s.pack("<8H", 2026, 10, 3, 7, 18, 24, 37, 78)
    header += _s.pack("<II", len(rows), 2)
    header += _s.pack("<I", 0x0000BBBB) + b"HELLO\0" + b"\xff" * 10
    header += _s.pack("<I", 0x0000AAAA) + b"DATAREPLY\0" + b"\xff" * 10
    header[4:8] = _s.pack("<I", len(header))
    out = bytearray(header)
    for ms, rpm, tco, knk, flags, tab in rows:
        body = _s.pack("<H", rpm | 0x8000) + bytes([tco, knk, flags, tab])
        start = len(out)
        out += _s.pack("<III", start + 12 + len(body), ms, 0x3B009701) + body
    return bytes(out)


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
        "tplog": ("drive_2026-10-07.csv", tunerpro_log()),
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
