# -*- coding: utf-8 -*-
"""
The program's own logger: reads the ECU over the K+DCAN cable (DS2 protocol)
exactly as the chosen ADX describes, and writes two files per recording:

    logs/<date_time>.csv          the log in TunerPro's CSV export layout
    logs/raw/<date_time>.jsonl    every byte sent and received, with times

The raw journal is the debugging record of the exchange and lets a log be
decoded again with a corrected ADX.

Nothing is hard-coded: the connect / monitor / disconnect macros, the bytes of
each command, the baud rates and the expected reply headers all come from the
ADX. The logger sends only the commands those three macros name. A DS2 reply
is address, total length, status, data, XOR checksum; the cable echoes what
was sent on the K-line, and the echo is skipped.

The AI has no control over the logger: only the owner starts and stops it.
"""

from __future__ import annotations

import datetime as _dt
import json
import os
import threading
import time
from typing import Any, Callable, Dict, List, Optional, Tuple

from .adx import Adx, AdxError, Command, CsvLog, Packet
from .i18n import t

LIVE = ("Engine Speed", "Coolant Temperature", "Oil Temperature")
FAILS_BEFORE_RECONNECT = 5


class Ds2Error(Exception):
    """A reply that did not come or did not check out."""


# ---------------------------------------------------------------------------
# The serial port
# ---------------------------------------------------------------------------

class SerialTransport:
    """The cable's COM port (pyserial). DS2: 8 data bits, parity from the ADX, 1 stop bit."""

    def __init__(self, port: str, parity: int = 2):
        import serial

        par = {0: serial.PARITY_NONE, 1: serial.PARITY_ODD, 2: serial.PARITY_EVEN}.get(parity,
                                                                                      serial.PARITY_EVEN)
        self.ser = serial.Serial(port, baudrate=9600, bytesize=8, parity=par, stopbits=1, timeout=0)
        self.baud = 9600

    def set_baud(self, baud: int) -> None:
        if baud != self.baud:
            self.ser.baudrate = baud
            self.baud = baud

    def write(self, data: bytes) -> None:
        self.ser.write(data)
        self.ser.flush()

    def read(self, timeout: float) -> bytes:
        """Whatever arrives within `timeout` seconds (at least one byte, or b"")."""
        end = time.monotonic() + timeout
        while True:
            waiting = self.ser.in_waiting
            if waiting:
                return self.ser.read(waiting)
            if time.monotonic() >= end:
                return b""
            time.sleep(0.001)

    def reset_input(self) -> None:
        self.ser.reset_input_buffer()

    def close(self) -> None:
        try:
            self.ser.close()
        except Exception:  # noqa: BLE001 - closing a port that is already gone
            pass


def list_ports() -> List[Dict[str, Any]]:
    """COM ports with a description; FTDI cables are marked."""
    try:
        from serial.tools import list_ports as lp
    except ImportError:
        return []
    out = []
    for p in sorted(lp.comports(), key=lambda p: p.device):
        text = " ".join(str(x) for x in (p.description, p.manufacturer, p.hwid) if x)
        out.append({"device": p.device, "description": p.description or p.device,
                    "ftdi": "FTDI" in text.upper() or "VID:PID=0403" in text.upper()})
    return out


# ---------------------------------------------------------------------------
# The journal
# ---------------------------------------------------------------------------

class Journal:
    """Every byte both ways, one JSON object per line."""

    def __init__(self, path: Optional[str]):
        self.path = path
        self.t0 = time.monotonic()
        self.lines: List[Dict[str, Any]] = []        # kept in memory for a connection test
        self._fh = open(path, "w", encoding="utf-8") if path else None

    def add(self, kind: str, data: bytes = b"", baud: int = 0, text: str = "") -> None:
        rec: Dict[str, Any] = {"t": round(time.monotonic() - self.t0, 4), "dir": kind}
        if baud:
            rec["baud"] = baud
        if data:
            rec["hex"] = data.hex(" ").upper()
        if text:
            rec["text"] = text
        if len(self.lines) < 2000:
            self.lines.append(rec)
        if self._fh:
            self._fh.write(json.dumps(rec, ensure_ascii=False) + "\n")

    def flush(self) -> None:
        if self._fh:
            self._fh.flush()

    def close(self) -> None:
        if self._fh and not self._fh.closed:
            self._fh.close()


# ---------------------------------------------------------------------------
# The DS2 session: runs ADX macros
# ---------------------------------------------------------------------------

def _xor(data: bytes) -> int:
    out = 0
    for b in data:
        out ^= b
    return out


# DS2 status bytes of a reply
STATUS = {0xA0: "OK", 0xA1: "busy", 0xA2: "rejected", 0xB0: "parameter error / not supported",
          0xFF: "unknown command"}
IDENT = bytes.fromhex("12 04 00 16")   # DS2 ident of the DME: read-only, safe at any time


class Ds2Refused(Ds2Error):
    """The ECU answered, the link is fine, but it refused the request. Reconnecting does not
    help: the logger stops and says why."""

    def __init__(self, message: str, status: int, request: bytes = b""):
        super().__init__(message)
        self.status = status
        self.request = request

    @property
    def baud_switch(self) -> bool:
        return self.request[2:3] == b"\x91"            # DS2 0x91: set the baud rate


class Ds2Busy(Ds2Error):
    """Status A1: the ECU is busy, ask again in a moment."""


def _refusal(name: str, packet: bytes, request: bytes = b"") -> Ds2Error:
    """The exception for a reply with a status other than the expected one."""
    hexed = packet[:4].hex(" ").upper()
    status = packet[2]
    if status == 0xA1:
        return Ds2Busy(t("The ECU is busy ({hex}).", hex=hexed))
    if status == 0xA2 and request[2:3] == b"\x91":
        msg = t("The ECU refused the switch to the fast baud rate ({hex}, status A2). The link "
                "itself works. The ECU accepts the switch only while the engine is not running: "
                "ignition on, engine off, connect, then start the engine.", hex=hexed)
    elif status in (0xB0, 0xFF):
        msg = t("The firmware does not support the ADX's request {req} ({hex}, status {status:02X}). "
                "The link works. An extended-logging ADX (0B B0) needs the DS2 Logging Feature "
                "Enhancement patch or the MS43X custom firmware; without it use the standard "
                "logging ADX (0B 03).", req=request[2:4].hex(" ").upper() or "?", hex=hexed,
                status=status)
    else:
        msg = t("The ECU refused {name} ({hex}, status {status:02X}).", name=name, hex=hexed,
                status=status)
    return Ds2Refused(msg, status, request)


def adx_kind(adx: Adx) -> Dict[str, Any]:
    """What an ADX asks of the ECU: the data request (0B 03 standard, 0B B0 extended) and
    whether it switches to a fast baud rate."""
    req = ""
    for node, _rep in adx.macros.get(adx.monitor_macro, []):
        cmd = adx.commands.get(node)
        if cmd is not None and len(cmd.data) >= 4:
            req = cmd.data[2:4].hex(" ").upper()
            break
    fast = any(c.data[2:3] == b"\x91" for c in adx.commands.values() if len(c.data) > 3)
    return {"request": req, "extended": req == "0B B0", "fast": fast}


class Session:
    """Runs ADX macros. slow=True: no baud switch, everything at the ADX's base rate (the
    extended request on a running engine, when the ECU refuses the fast rate)."""

    def __init__(self, adx: Adx, transport, journal: Journal, slow: bool = False):
        self.adx = adx
        self.port = transport
        self.journal = journal
        self.slow = slow
        self._last_tx = b""
        self._last_cmd: Optional[Command] = None
        allowed = set()
        for macro in (adx.connect_macro, adx.monitor_macro, adx.disconnect_macro):
            allowed |= self._commands_in(macro, 0)
        self.allowed = allowed

    def _commands_in(self, macro: str, depth: int) -> set:
        out = set()
        for node, _rep in self.adx.macros.get(macro, []):
            if node in self.adx.commands:
                out.add(node)
            elif node in self.adx.macros and depth < 4:
                out |= self._commands_in(node, depth + 1)
        return out

    def _baud(self, baud: int) -> int:
        baud = self.adx.baud if self.slow else (baud or self.adx.baud)
        self.port.set_baud(baud)
        return baud

    def send(self, cmd: Command) -> None:
        if cmd.name not in self.allowed:
            raise Ds2Error(t("The ADX command {name} is not part of connect/monitor/disconnect; "
                             "not sent.", name=cmd.name))
        self._write(cmd.data, self._baud(cmd.baud), cmd.name)
        self._last_cmd = cmd

    def _write(self, data: bytes, baud: int, name: str) -> None:
        self.port.reset_input()
        self.port.write(data)
        self._last_tx = data
        self.journal.add("tx", data, baud, name)

    def receive(self, pk: Packet) -> bytes:
        packet = self._frame(pk.name, self._baud(pk.baud), pk.timeout_ms, pk.header[:1])
        if pk.header and not packet.startswith(pk.header):
            if len(packet) > 2 and packet[2] != 0xA0:
                raise _refusal(pk.name, packet, self._last_tx)
            raise Ds2Error(t("Unexpected reply to {name}: {hex}", name=pk.name,
                             hex=packet[:4].hex(" ").upper()))
        start = len(pk.header)
        return packet[start:start + pk.size] if pk.size else b""

    def _frame(self, name: str, baud: int, timeout_ms: int, address: bytes) -> bytes:
        """One DS2 frame from the ECU (the echo and noise before it skipped, checksum checked)."""
        deadline = time.monotonic() + timeout_ms / 1000.0
        buf = b""
        echo = self._last_tx
        while True:
            left = deadline - time.monotonic()
            if left <= 0:
                if buf:
                    self.journal.add("rx", buf, baud, "incomplete")
                raise Ds2Error(t("No reply {name} within {ms} ms.", name=name, ms=timeout_ms))
            chunk = self.port.read(min(left, 0.05))
            if not chunk:
                continue
            buf += chunk
            # the cable echoes the request on the K-line
            if echo:
                if len(buf) < len(echo) and echo.startswith(buf):
                    continue
                if buf.startswith(echo):
                    buf = buf[len(echo):]
                echo = b""
            while buf:
                if address and buf[0] != address[0]:
                    buf = buf[1:]                         # noise before the address byte
                    continue
                if len(buf) < 2:
                    break
                total = buf[1]
                if total < 3:
                    buf = buf[1:]
                    continue
                if len(buf) < total:
                    break
                packet, buf = buf[:total], buf[total:]
                self.journal.add("rx", packet, baud, name)
                if _xor(packet) != 0:
                    raise Ds2Error(t("Bad checksum in {name}.", name=name))
                return packet

    def ident(self) -> Dict[str, Any]:
        """DS2 ident at the base rate: the ECU's part number and the rest of its answer."""
        self._write(IDENT, self._baud(self.adx.baud), "IDENT")
        packet = self._frame("IDENT", self.adx.baud, 1000, b"\x12")
        body = packet[3:-1]
        text = "".join(chr(b) if 32 <= b < 127 else " " for b in body)
        text = " ".join(text.split())
        return {"status": packet[2], "text": text, "part": text.split(" ")[0] if text else "",
                "hex": packet.hex(" ").upper()}

    def run(self, macro: str, depth: int = 0) -> List[Tuple[int, bytes]]:
        """Run a macro; returns the bodies of the replies: [(packet id hash, body)]."""
        out: List[Tuple[int, bytes]] = []
        nodes = self.adx.macros.get(macro)
        if nodes is None:
            raise Ds2Error(t("The ADX has no macro {name}.", name=macro))
        for node, rep in nodes:
            for _ in range(rep):
                if node in self.adx.commands:
                    self.send(self.adx.commands[node])
                elif node in self.adx.listen_by_name:
                    pk = self.adx.listen_by_name[node]
                    out.append((pk.idhash, self._receive_retry(pk)))
                elif node in self.adx.macros and depth < 4:
                    out += self.run(node, depth + 1)
                else:
                    raise Ds2Error(t("The ADX macro {macro} names an unknown step {name}.",
                                     macro=macro, name=node))
        return out

    def _receive_retry(self, pk: Packet) -> bytes:
        for attempt in range(3):
            try:
                return self.receive(pk)
            except Ds2Busy:
                if attempt == 2 or self._last_cmd is None:
                    raise
                time.sleep(0.15)
                self.send(self._last_cmd)
        raise Ds2Error("unreachable")

    def connect(self) -> None:
        """Connect; if the ECU still runs at the fast rate from an earlier session, reset first.
        A refusal (the engine runs, the request is unknown) is not retried."""
        if self.slow or not self.adx.connect_macro:
            return
        try:
            self.run(self.adx.connect_macro)
        except Ds2Refused:
            raise
        except Ds2Error as first:
            self.journal.add("info", text=f"connect failed: {first}; resetting and trying again")
            if self.adx.disconnect_macro:
                try:
                    self.run(self.adx.disconnect_macro)
                except Ds2Error:
                    pass
            self.run(self.adx.connect_macro)

    def disconnect(self) -> None:
        if self.slow:
            return
        if self.adx.disconnect_macro:
            try:
                self.run(self.adx.disconnect_macro)
            except Ds2Error as exc:
                self.journal.add("error", text=str(exc))


def _live(values: Dict[str, Optional[float]]) -> Dict[str, Optional[float]]:
    return {k: (round(values[k], 1) if values.get(k) is not None else None) for k in LIVE}


# ---------------------------------------------------------------------------
# Connection test and recording
# ---------------------------------------------------------------------------

MODE_TEXT = {
    "fast": "fast: the ADX's baud rate",
    "slow": "slow: the same request at the base rate (the ECU refused the fast rate)",
    "stock": "standard logging ADX (the extended request is not supported)",
    "normal": "the ADX as it is",
}


def choose_mode(adx: Adx, port, journal: Journal, fallback: Optional[Adx] = None
                ) -> Tuple[str, Adx, "Session", List[Tuple[int, bytes]]]:
    """Find a way to log: the ADX at its fast rate; if the ECU refuses the fast rate (engine
    running), the same request at the base rate; if the request itself is not supported, the
    standard logging ADX (fallback). Returns (mode, adx, connected session, first replies).
    Raises Ds2Refused when nothing works, Ds2Error when the ECU is silent."""
    kind = adx_kind(adx)
    refused: Optional[Ds2Refused] = None
    session = Session(adx, port, journal)
    try:
        session.connect()
        replies = session.run(adx.monitor_macro)
        return ("fast" if kind["fast"] else "normal"), adx, session, replies
    except Ds2Refused as exc:
        refused = exc
        if not exc.baud_switch:
            session.disconnect()                     # the switch was accepted: back to the base rate
    if refused.baud_switch:
        journal.add("info", text="fast rate refused, trying the same request at the base rate")
        session = Session(adx, port, journal, slow=True)
        try:
            return "slow", adx, session, session.run(adx.monitor_macro)
        except Ds2Refused as exc:
            refused = exc
    if refused.status in (0xB0, 0xFF) and fallback is not None:
        journal.add("info", text="request not supported, trying the standard logging ADX")
        session = Session(fallback, port, journal)
        session.connect()
        return "stock", fallback, session, session.run(fallback.monitor_macro)
    raise refused


def diagnose(adx_path: str, transport_factory: Callable[[Adx], Any],
             journal_path: Optional[str] = None, fallback_path: str = "") -> Dict[str, Any]:
    """"Check the connection": ident, the request at the base rate, the fast rate; the mode
    a recording will use. Every step is read-only."""
    adx = Adx(adx_path)
    fallback = Adx(fallback_path) if fallback_path and os.path.isfile(fallback_path) else None
    journal = Journal(journal_path)
    kind = adx_kind(adx)
    result: Dict[str, Any] = {"ok": False, "values": {}, "error": "", "mode": "", "ident": None,
                              "steps": [], "kind": kind}
    steps = result["steps"]
    port = None
    try:
        port = transport_factory(adx)
        probe = Session(adx, port, journal, slow=True)
        try:
            result["ident"] = probe.ident()
        except Ds2Error:
            # maybe still at the fast rate from an earlier session: reset and ask again
            Session(adx, port, journal).disconnect()
            result["ident"] = probe.ident()
        steps.append({"ok": True, "text": t("The ECU answers (ident): {text}",
                                            text=result["ident"]["text"] or result["ident"]["hex"])})
        try:
            probe.run(adx.monitor_macro)
            steps.append({"ok": True, "text": t("The data request {req} works at {baud} baud.",
                                                req=kind["request"], baud=adx.baud)})
        except Ds2Refused as exc:
            steps.append({"ok": False, "text": str(exc)})
        except Ds2Error as exc:
            steps.append({"ok": None, "text": t("At {baud} baud: {error}", baud=adx.baud, error=exc)})
        mode, used, session, replies = choose_mode(adx, port, journal, fallback)
        data = [(p, b) for p, b in replies if any(c.packet == p for c in used.channels)]
        if not data:
            raise Ds2Error(t("The ECU answered, but no data packet came."))
        result["values"] = _live(used.decode(*data[-1]))
        result["mode"] = mode
        result["adx_used"] = os.path.basename(fallback_path) if mode == "stock" else os.path.basename(adx_path)
        if mode == "slow":
            steps.append({"ok": None, "text": t("The fast rate was refused (engine running?): a recording "
                                                "will use {baud} baud, slower. For the fast rate: ignition "
                                                "on, engine off, connect, then start the engine.",
                                                baud=adx.baud)})
        elif mode == "stock":
            steps.append({"ok": None, "text": t("A recording will use the standard logging ADX {name}: "
                                                "fewer channels, works on any MS43.",
                                                name=result["adx_used"])})
        else:
            steps.append({"ok": True, "text": t("A recording will use {name} as it is.",
                                                name=result["adx_used"])})
        session.disconnect()
        result["ok"] = True
    except Ds2Refused as exc:
        result["error"] = str(exc)
        journal.add("error", text=str(exc))
    except (Ds2Error, AdxError, OSError, ValueError) as exc:
        result["error"] = str(exc)
        if result["ident"] is None:
            result["error"] += " " + t("No answer at all: check the cable power (12 V), the K-line "
                                       "pins, the port and the ignition.")
        journal.add("error", text=str(exc))
    finally:
        if port is not None:
            port.close()
        journal.close()
    result["journal"] = journal.lines
    return result


def test_connection(adx_path: str, transport_factory: Callable[[Adx], Any],
                    journal_path: Optional[str] = None, fallback_path: str = "") -> Dict[str, Any]:
    return diagnose(adx_path, transport_factory, journal_path, fallback_path)


class Recorder:
    """A recording in a background thread; `status` is read by the window."""

    def __init__(self, adx_path: str, transport_factory: Callable[[Adx], Any], logs_dir: str,
                 on_done: Optional[Callable[[str], None]] = None, fallback_path: str = ""):
        self.adx = Adx(adx_path)
        self.adx_path = adx_path
        self.fallback_path = fallback_path if fallback_path and os.path.isfile(fallback_path) else ""
        self.mode = ""
        self.factory = transport_factory
        self.logs_dir = logs_dir
        self.on_done = on_done
        stamp = _dt.datetime.now()
        self.name = stamp.strftime("%Y-%m-%d_%H-%M-%S")
        os.makedirs(os.path.join(logs_dir, "raw"), exist_ok=True)
        self.csv_path = os.path.join(logs_dir, self.name + ".csv")
        self.raw_path = os.path.join(logs_dir, "raw", self.name + ".jsonl")
        self.started = stamp
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self.status: Dict[str, Any] = {"state": "starting", "rows": 0, "rate": 0.0, "live": {}, "mode": "",
                                       "errors": 0, "reconnects": 0, "message": "",
                                       "name": self.name + ".csv", "seconds": 0.0}

    def start(self) -> None:
        self._thread = threading.Thread(target=self._run, name="ds2logger", daemon=True)
        self._thread.start()

    def stop(self, wait: float = 5.0) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(wait)

    @property
    def running(self) -> bool:
        return bool(self._thread and self._thread.is_alive())

    def _run(self) -> None:
        journal = Journal(self.raw_path)
        st = self.status
        port = None
        session = None
        log = None
        connected = False
        fails = 0
        t0 = time.monotonic()
        stamps: List[float] = []
        last_flush = t0
        fallback = Adx(self.fallback_path) if self.fallback_path else None
        try:
            while not self._stop.is_set():
                if port is None:
                    try:
                        port = self.factory(self.adx)
                    except (OSError, ValueError) as exc:
                        st.update(state="no_port", message=str(exc))
                        journal.add("error", text=str(exc))
                        self._stop.wait(1.0)
                        continue
                if not connected:
                    st["state"] = "connecting"
                    try:
                        if not self.mode:
                            self.mode, adx, session, _ = choose_mode(self.adx, port, journal, fallback)
                            if adx is not self.adx:
                                self.adx, self.adx_path = adx, self.fallback_path
                            st["mode"] = self.mode
                        else:
                            session = Session(self.adx, port, journal, slow=self.mode == "slow")
                            session.connect()
                        connected, fails = True, 0
                        st.update(state="recording", message=_mode_note(self.mode))
                        journal.add("info", text=f"connected, mode {self.mode}")
                    except Ds2Refused as exc:
                        # the link works, the ECU refuses: reconnecting does not help
                        st.update(state="refused", message=str(exc))
                        journal.add("error", text=str(exc))
                        break
                    except Ds2Error as exc:
                        st.update(state="reconnecting", message=str(exc))
                        st["reconnects"] += 1
                        self._stop.wait(1.0)
                        continue
                if log is None:
                    log = CsvLog(self.adx, self.csv_path,
                                 f"MS43 AI-Tuner log recorded on {self.started:%m/%d/%Y %H:%M:%S} "
                                 f"with {os.path.basename(self.adx_path)}")
                    data_packets = {c.packet for c in self.adx.channels}
                try:
                    replies = session.run(self.adx.monitor_macro)
                    fails = 0
                except Ds2Refused as exc:
                    st.update(state="refused", message=str(exc))
                    journal.add("error", text=str(exc))
                    break
                except Ds2Error as exc:
                    fails += 1
                    st["errors"] += 1
                    st["message"] = str(exc)
                    if fails >= FAILS_BEFORE_RECONNECT:
                        connected = False
                        journal.add("info", text="connection lost (no answer), reconnecting")
                    continue
                now = time.monotonic()
                for packet, body in replies:
                    if packet in data_packets:
                        values = log.add(now - t0, packet, body)
                        st["live"] = _live(values)
                        stamps.append(now)
                stamps = [s for s in stamps if now - s <= 2.0]
                st.update(rows=log.rows, rate=round(len(stamps) / 2.0, 1), seconds=round(now - t0, 1))
                if now - last_flush > 1.0:
                    log.flush()
                    journal.flush()
                    last_flush = now
        finally:
            if session is not None and connected:
                session.disconnect()
            if port is not None:
                port.close()
            if log is not None:
                log.close()
            journal.close()
            if st["state"] != "refused":
                st["state"] = "stopped"
            if log is None or log.rows == 0:
                try:
                    os.remove(self.csv_path)          # the journal stays: it shows what went wrong
                except OSError:
                    pass
            elif self.on_done:
                self.on_done(self.csv_path)


def _mode_note(mode: str) -> str:
    if mode == "slow":
        return t("Recording at the base rate: the ECU refused the fast rate (engine running). "
                 "For the full rate connect with the engine off next time.")
    if mode == "stock":
        return t("Recording with the standard logging ADX: the firmware does not support the "
                 "extended request.")
    return ""
