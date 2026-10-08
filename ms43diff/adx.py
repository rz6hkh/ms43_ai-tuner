# -*- coding: utf-8 -*-
"""
TunerPro logger definitions (.adx) and TunerPro's own log files (.xdl).

An .xdl file keeps the raw reply packets of the ECU with a time stamp; the ADX
says where each channel sits in a packet and how to turn the raw number into
a physical value. Decoding an .xdl therefore needs the ADX it was recorded
with. The result is written as a CSV in TunerPro's own export layout (title
line, header, units row, ON/OFF flags), so the rest of the program and
Claude's pandas tools read it like any exported log.

.xdl layout (TunerPro RT, version 3, read from real files):
    u32 version, u32 header size, u32 ?, SYSTEMTIME start (8 x u16),
    u32 record count, u32 packet count, then the packet definitions (their
    ADX id hashes appear in order); after the header, records of
    u32 offset of the next record, u32 milliseconds since start,
    u32 packet index (low byte; the rest is uncleared memory), then the
    packet body.

The ADX is data from someone else's file: formulas go through the safe
mathexpr parser, never eval.
"""

from __future__ import annotations

import datetime as _dt
import math
import os
import re
import struct
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from .i18n import t
from .mathexpr import Equation, MathError


# Raised when decoding changes in a way that alters values: logs decoded by an older
# version are offered for decoding again from their raw file.
#   2: outputtype 1 drops the fraction; a channel without a parent reads the data packet
DECODER_VERSION = 2


class AdxError(ValueError):
    """An ADX or an .xdl that cannot be used; the text is shown as is."""


def _int(text: Optional[str], default: int = 0) -> int:
    if text is None or not str(text).strip():
        return default
    text = str(text).strip()
    try:
        return int(text, 16) if text.lower().startswith("0x") else int(float(text))
    except ValueError:
        return default


def _units(title: str, text: str) -> str:
    """"Engine Speed (rpm)" -> "rpm"; TunerPro writes the units this way."""
    text = (text or "").strip()
    if text.endswith(")") and "(" in text:
        return text[text.rfind("(") + 1:-1]
    return text if text and text != title else ""


@dataclass
class Channel:
    title: str
    idhash: int
    kind: str                         # "value" | "bitmask"
    packet: int                       # parent packet id hash
    offset: int
    bits: int = 8
    lsb_first: bool = False
    signed: bool = False
    units: str = ""
    equation: Optional[Equation] = None
    native: List[str] = field(default_factory=list)          # variables fed with the raw value
    links: Dict[str, int] = field(default_factory=dict)      # variable -> id hash of a channel
    lookup: Optional[int] = None
    operand: int = 0
    result: Optional[int] = None
    output_type: int = 3              # 1 = integer: TunerPro drops the fraction
    bitop: str = "AND"
    true_text: str = "ON"
    false_text: str = "OFF"


@dataclass
class Packet:
    """A reply the ECU sends (ADXCLISTENPACKET)."""
    name: str
    idhash: int
    size: int                          # body bytes kept after the header
    header: bytes = b""                # expected first bytes of the reply
    timeout_ms: int = 500
    baud: int = 0                      # 0 = the ADX's default baud rate


@dataclass
class Command:
    """Bytes the logger sends (ADXCSENDCOMMAND)."""
    name: str
    data: bytes
    baud: int = 0


def _hex_bytes(text: Optional[str]) -> bytes:
    text = re.sub(r"[^0-9A-Fa-f]", "", text or "")
    return bytes.fromhex(text[: len(text) // 2 * 2])


class Adx:
    """The channels of an ADX and how to decode a reply packet."""

    def __init__(self, path: str):
        self.path = path
        try:
            root = ET.parse(path).getroot()
        except (ET.ParseError, OSError) as exc:
            raise AdxError(t("Not a TunerPro logger definition (.adx): {error}", error=exc)) from exc
        if root.tag != "ADXFORMAT":
            raise AdxError(t("Not a TunerPro logger definition (.adx): {error}", error=root.tag))
        head = root.find("ADXHEADER")
        defaults = head.find("DEFAULTS") if head is not None else None
        d = defaults.attrib if defaults is not None else {}
        self.title = (head.findtext("desc") if head is not None else "") or os.path.basename(path)
        def_bits = _int(d.get("datasizeinbits"), 8)
        def_lsb = d.get("lsbfirst", "0") == "1"
        def_signed = d.get("signed", "0") == "1"
        self.baud = _int(head.findtext("baud") if head is not None else None, 9600) or 9600
        # 0 none, 1 odd, 2 even (DS2 uses 8 data bits, even parity)
        self.parity = _int(head.findtext("parity") if head is not None else None, 0)
        self.connect_macro = (head.findtext("connectcmd") if head is not None else "") or ""
        self.monitor_macro = (head.findtext("monitorcmd") if head is not None else "") or ""
        self.disconnect_macro = (head.findtext("disconnectcmd") if head is not None else "") or ""
        self.packets: Dict[int, Packet] = {}
        self.listen_by_name: Dict[str, Packet] = {}
        for el in root.findall("ADXCLISTENPACKET"):
            h = _int(el.get("idhash"))
            pk = Packet(el.get("id", ""), h, _int(el.findtext("packetsize")),
                        _hex_bytes(el.findtext("headerstring")),
                        _int(el.findtext("listentimeout"), 500) or 500, _int(el.findtext("baud")))
            self.packets[h] = pk
            self.listen_by_name[pk.name] = pk
        self.commands: Dict[str, Command] = {}
        for el in root.findall("ADXCSENDCOMMAND"):
            self.commands[el.get("id", "")] = Command(el.get("id", ""), _hex_bytes(el.findtext("bytestring")),
                                                      _int(el.findtext("baud")))
        # macro id -> [(command or packet id, repeat count)]
        self.macros: Dict[str, List[Tuple[str, int]]] = {}
        for el in root.findall("ADXMACRO"):
            self.macros[el.get("id", "")] = [(n.get("commandID", ""), max(1, _int(n.get("repeatcount"), 1)))
                                             for n in el.findall("NODE")]
        self.lookups: Dict[int, List[Tuple[float, float]]] = {}
        for el in root.findall("ADXLOOKUPTABLE"):
            rows = [(float(e.get("input", 0)), float(e.get("output", 0)))
                    for e in el.findall("tableentry")]
            self.lookups[_int(el.get("idhash"))] = rows
        self.channels: List[Channel] = []
        for el in root.findall("ADXVALUE"):
            flags = _int(el.findtext("flags"))
            title = el.get("title") or el.get("id") or "?"
            math = el.find("MATH")
            ch = Channel(title=title, idhash=_int(el.get("idhash")), kind="value",
                         packet=_int(el.findtext("parentcmdidhash")),
                         offset=_int(el.findtext("packetoffset")),
                         bits=_int(el.findtext("sizeinbits"), def_bits),
                         lsb_first=bool(flags & 0x2) or def_lsb,
                         signed=bool(flags & 0x1) or def_signed,
                         units=_units(title, el.findtext("units") or ""),
                         output_type=_int(el.findtext("outputtype"), _int(d.get("outputtype"), 3)))
            if math is not None:
                names = []
                for var in math.findall("VAR"):
                    name = var.get("varID") or "X"
                    names.append(name)
                    if var.get("type") == "link":
                        ch.links[name] = _int(var.get("linkIDHash"))
                    else:
                        ch.native.append(name)
                ch.equation = Equation(math.get("equation") or "X", names)
                if math.get("lookupidhash"):
                    ch.lookup = _int(math.get("lookupidhash"))
            if not ch.native and not ch.links:
                ch.native = ["X"]
            self.channels.append(ch)
        for el in root.findall("ADXBITMASK"):
            title = el.get("title") or el.get("id") or "?"
            operand = _int(el.findtext("operand"))
            res = el.findtext("result")
            self.channels.append(Channel(
                title=title, idhash=_int(el.get("idhash")), kind="bitmask",
                packet=_int(el.findtext("parentcmdidhash")),
                offset=_int(el.findtext("packetoffset")),
                bits=_int(el.findtext("sizeinbits"), def_bits),
                operand=operand, result=_int(res) if res is not None else None,
                bitop=(el.findtext("bitop") or "AND").strip().upper(),
                true_text=el.findtext("truestring") or "ON",
                false_text=el.findtext("falsestring") or "OFF"))
        if not self.channels:
            raise AdxError(t("The ADX defines no channels."))
        # A channel without a parent packet belongs to the main data packet (TunerPro reads it
        # from there): the reply in the monitor macro with the largest body.
        listens = [self.listen_by_name[n] for n, _r in self.macros.get(self.monitor_macro, [])
                   if n in self.listen_by_name]
        main = max(listens or list(self.packets.values()) or [None],
                   key=lambda p: p.size if p else 0)
        for ch in self.channels:
            if not ch.packet and main is not None:
                ch.packet = main.idhash
        self.by_hash = {c.idhash: c for c in self.channels}
        self._cache: Dict[int, Dict[tuple, float]] = {}

    # ---- decoding --------------------------------------------------------
    def _raw(self, ch: Channel, body: bytes) -> Optional[int]:
        size = max(1, ch.bits // 8)
        if ch.offset + size > len(body):
            return None
        chunk = body[ch.offset:ch.offset + size]
        value = int.from_bytes(chunk, "little" if ch.lsb_first else "big", signed=ch.signed)
        return value

    def _lookup(self, table: int, value: float) -> float:
        rows = self.lookups.get(table)
        if not rows:
            return value
        for inp, out in rows:
            if abs(inp - value) < 1e-9:
                return out
        return min(rows, key=lambda r: abs(r[0] - value))[1]

    def _value(self, ch: Channel, body: bytes, memo: Dict[int, Optional[float]],
               depth: int = 0) -> Optional[float]:
        if ch.idhash in memo:
            return memo[ch.idhash]
        memo[ch.idhash] = None                      # breaks a link cycle
        raw = self._raw(ch, body)
        if raw is None or depth > 8:
            return None
        if ch.kind == "bitmask":
            masked = raw & ch.operand if ch.bitop == "AND" else raw | ch.operand
            want = ch.result if ch.result is not None else ch.operand
            out: Optional[float] = 1.0 if masked == want else 0.0
        else:
            inputs = {name: float(raw) for name in ch.native}
            for name, h in ch.links.items():
                other = self.by_hash.get(h)
                v = self._value(other, body, memo, depth + 1) if other else None
                inputs[name] = 0.0 if v is None else v
            key = tuple(sorted(inputs.items()))
            cache = self._cache.setdefault(ch.idhash, {})
            out = cache.get(key)
            if out is None:
                try:
                    out = ch.equation.evaluate(inputs) if ch.equation else float(raw)
                except MathError:
                    out = float(raw)
                if ch.lookup is not None:
                    out = self._lookup(ch.lookup, out)
                if ch.output_type == 1:
                    out = float(math.trunc(out))
                if len(cache) < 200_000:
                    cache[key] = out
        memo[ch.idhash] = out
        return out

    def decode(self, packet: int, body: bytes) -> Dict[str, Optional[float]]:
        memo: Dict[int, Optional[float]] = {}
        return {ch.title: self._value(ch, body, memo)
                for ch in self.channels if ch.packet == packet}


# ---------------------------------------------------------------------------
# .xdl
# ---------------------------------------------------------------------------

def read_xdl(path: str, adx: Adx) -> Tuple[_dt.datetime, List[Tuple[float, int, bytes]]]:
    """(start time, [(seconds, packet id hash, body)]) of a TunerPro .xdl log."""
    with open(path, "rb") as fh:
        data = fh.read()
    if len(data) < 48:
        raise AdxError(t("Not a TunerPro log (.xdl): the file is too short."))
    version, header = struct.unpack_from("<II", data, 0)
    if header < 40 or header > len(data) or header > 1 << 20:
        raise AdxError(t("Not a TunerPro log (.xdl): unknown header (version {v}).", v=version))
    y, mo, _dow, day, hh, mi, ss, ms = struct.unpack_from("<8H", data, 12)
    try:
        start = _dt.datetime(y, mo, day, hh, mi, ss, ms * 1000)
    except ValueError:
        start = _dt.datetime(2000, 1, 1)
    # the packet definitions list the listen packets in index order: find them by hash
    found = []
    for h in adx.packets:
        pos = data.find(struct.pack("<I", h), 0, header)
        if pos >= 0:
            found.append((pos, h))
    order = [h for _pos, h in sorted(found)]
    if not order:
        raise AdxError(t("This .xdl was not recorded with this ADX (no matching packets)."))
    out: List[Tuple[float, int, bytes]] = []
    off = header
    while off + 12 <= len(data):
        nxt, ms_, idx = struct.unpack_from("<III", data, off)
        if nxt <= off + 12 or nxt > len(data):
            break                                       # end of the records or a cut file
        idx &= 0xFF                                     # the upper bytes are not cleared by TunerPro
        if idx < len(order):
            out.append((ms_ / 1000.0, order[idx], data[off + 12:nxt]))
        off = nxt
    return start, out


class CsvLog:
    """A log in TunerPro's CSV export layout, written row by row (used by the
    .xdl import and by the live logger)."""

    def __init__(self, adx: Adx, path: str, title: str):
        self.adx = adx
        self.path = path
        packets = {c.packet for c in adx.channels}
        self.packets = packets
        self.titles = sorted({c.title for c in adx.channels if c.packet in packets}, key=str.lower)
        self.chans = {c.title: c for c in adx.channels}
        self.rows = 0
        self._fh = open(path, "w", encoding="utf-8", newline="\r\n")
        units = [self._esc(f"{x} ({self.chans[x].units})") if self.chans[x].units else self._esc(x)
                 for x in self.titles]
        self._fh.write(title + "\n")
        self._fh.write(",".join(["", "Time"] + [self._esc(x) for x in self.titles]) + ",\n")
        self._fh.write(",".join(["Sample #", "Seconds"] + units) + ",\n")

    @staticmethod
    def _esc(text: str) -> str:
        return f'"{text}"' if "," in text else text

    def _cell(self, v: Optional[float], ch: Channel) -> str:
        if v is None:
            return ""
        if ch.kind == "bitmask":
            return ch.true_text if v else ch.false_text
        text = f"{v:.6f}".rstrip("0").rstrip(".")
        return "0" if text in ("-0", "") else text

    def add(self, seconds: float, packet: int, body: bytes) -> Dict[str, Optional[float]]:
        values = self.adx.decode(packet, body)
        self._fh.write(",".join([str(self.rows), f"{seconds:.3f}"] +
                                [self._cell(values.get(x), self.chans[x]) for x in self.titles]) + ",\n")
        self.rows += 1
        return values

    def flush(self) -> None:
        self._fh.flush()

    def close(self) -> None:
        if not self._fh.closed:
            self._fh.close()


def xdl_to_csv(xdl_path: str, adx_path: str, csv_path: str) -> Dict[str, object]:
    """Decode an .xdl with its ADX into a CSV in TunerPro's export layout."""
    adx = Adx(adx_path)
    start, records = read_xdl(xdl_path, adx)
    data_packets = {c.packet for c in adx.channels}
    rows = [(tm, p, body) for tm, p, body in records if p in data_packets]
    if not rows:
        raise AdxError(t("This .xdl was not recorded with this ADX (no matching packets)."))
    sizes = {p: adx.packets[p].size for p in data_packets if p in adx.packets}
    bad = sum(1 for _tm, p, body in rows if sizes.get(p) and len(body) != sizes[p])
    if bad > len(rows) // 2:
        raise AdxError(t("This .xdl was not recorded with this ADX: packet sizes differ."))
    tmp = csv_path + ".tmp"
    log = CsvLog(adx, tmp, f"TunerPro Engine data log recorded on {start:%m/%d/%Y %H:%M:%S} "
                           f"(decoded from {os.path.basename(xdl_path)} with "
                           f"{os.path.basename(adx_path)})")
    try:
        t0 = rows[0][0]
        for tm, p, body in rows:
            log.add(tm - t0, p, body)
    finally:
        log.close()
    os.replace(tmp, csv_path)
    return {"rows": len(rows), "channels": len(log.titles), "start": start,
            "duration": rows[-1][0] - t0, "bad_packets": bad}


def jsonl_to_csv(jsonl_path: str, adx_path: str, csv_path: str, title: str = "") -> Dict[str, object]:
    """Decode the raw journal of the program's own logger again (e.g. with a corrected ADX)."""
    import json

    adx = Adx(adx_path)
    by_name = adx.listen_by_name
    data_packets = {c.packet for c in adx.channels}
    rows = []
    with open(jsonl_path, encoding="utf-8") as fh:
        for line in fh:
            try:
                rec = json.loads(line)
            except ValueError:
                continue
            raw = bytes.fromhex(rec.get("hex", "").replace(" ", ""))
            if "dir" in rec:                      # the program's own journal
                pk = by_name.get(rec.get("text", ""))
                if rec.get("dir") != "rx" or pk is None or pk.idhash not in data_packets:
                    continue
            else:                                 # a plain {"t", "hex"} recording: match the header
                pk = next((p for p in by_name.values() if p.idhash in data_packets and p.header
                           and raw.startswith(p.header) and len(raw) >= len(p.header) + p.size), None)
                if pk is None:
                    continue
            start = len(pk.header)
            rows.append((float(rec.get("t", 0)), pk.idhash, raw[start:start + pk.size]))
    if not rows:
        raise AdxError(t("This .xdl was not recorded with this ADX (no matching packets)."))
    tmp = csv_path + ".tmp"
    log = CsvLog(adx, tmp, title or f"MS43 AI-Tuner log decoded from {os.path.basename(jsonl_path)}")
    try:
        t0 = rows[0][0]
        for tm, p, body in rows:
            log.add(tm - t0, p, body)
    finally:
        log.close()
    os.replace(tmp, csv_path)
    return {"rows": len(rows), "channels": len(log.titles), "duration": rows[-1][0] - t0}
