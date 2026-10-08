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


class Session:
    def __init__(self, adx: Adx, transport, journal: Journal):
        self.adx = adx
        self.port = transport
        self.journal = journal
        self._last_tx = b""
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
        baud = baud or self.adx.baud
        self.port.set_baud(baud)
        return baud

    def send(self, cmd: Command) -> None:
        if cmd.name not in self.allowed:
            raise Ds2Error(t("The ADX command {name} is not part of connect/monitor/disconnect; "
                             "not sent.", name=cmd.name))
        baud = self._baud(cmd.baud)
        self.port.reset_input()
        self.port.write(cmd.data)
        self._last_tx = cmd.data
        self.journal.add("tx", cmd.data, baud, cmd.name)

    def receive(self, pk: Packet) -> bytes:
        baud = self._baud(pk.baud)
        deadline = time.monotonic() + pk.timeout_ms / 1000.0
        buf = b""
        echo = self._last_tx
        while True:
            left = deadline - time.monotonic()
            if left <= 0:
                if buf:
                    self.journal.add("rx", buf, baud, "incomplete")
                raise Ds2Error(t("No reply {name} within {ms} ms.", name=pk.name, ms=pk.timeout_ms))
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
                if pk.header and buf[0] != pk.header[0]:
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
                self.journal.add("rx", packet, baud, pk.name)
                if _xor(packet) != 0:
                    raise Ds2Error(t("Bad checksum in {name}.", name=pk.name))
                if pk.header and not packet.startswith(pk.header):
                    raise Ds2Error(t("Unexpected reply to {name}: {hex}", name=pk.name,
                                     hex=packet[:4].hex(" ").upper()))
                start = len(pk.header)
                return packet[start:start + pk.size] if pk.size else b""

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
                    out.append((pk.idhash, self.receive(pk)))
                elif node in self.adx.macros and depth < 4:
                    out += self.run(node, depth + 1)
                else:
                    raise Ds2Error(t("The ADX macro {macro} names an unknown step {name}.",
                                     macro=macro, name=node))
        return out

    def connect(self) -> None:
        """Connect; if the ECU still runs at the fast rate from an earlier session, reset first."""
        if not self.adx.connect_macro:
            return
        try:
            self.run(self.adx.connect_macro)
        except Ds2Error as first:
            self.journal.add("info", text=f"connect failed: {first}; resetting and trying again")
            if self.adx.disconnect_macro:
                try:
                    self.run(self.adx.disconnect_macro)
                except Ds2Error:
                    pass
            self.run(self.adx.connect_macro)

    def disconnect(self) -> None:
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

def test_connection(adx_path: str, transport_factory: Callable[[Adx], Any],
                    journal_path: Optional[str] = None) -> Dict[str, Any]:
    """Connect, read one data packet, disconnect. Returns the journal and the values."""
    adx = Adx(adx_path)
    journal = Journal(journal_path)
    result: Dict[str, Any] = {"ok": False, "values": {}, "error": ""}
    port = None
    try:
        port = transport_factory(adx)
        session = Session(adx, port, journal)
        session.connect()
        replies = session.run(adx.monitor_macro)
        data = [(p, b) for p, b in replies if any(c.packet == p for c in adx.channels)]
        if not data:
            raise Ds2Error(t("The ECU answered, but no data packet came."))
        result["values"] = _live(adx.decode(*data[-1]))
        session.disconnect()
        result["ok"] = True
    except (Ds2Error, AdxError, OSError, ValueError) as exc:
        result["error"] = str(exc)
        journal.add("error", text=str(exc))
    finally:
        if port is not None:
            port.close()
        journal.close()
    result["journal"] = journal.lines
    return result


class Recorder:
    """A recording in a background thread; `status` is read by the window."""

    def __init__(self, adx_path: str, transport_factory: Callable[[Adx], Any], logs_dir: str,
                 on_done: Optional[Callable[[str], None]] = None):
        self.adx = Adx(adx_path)
        self.adx_path = adx_path
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
        self.status: Dict[str, Any] = {"state": "starting", "rows": 0, "rate": 0.0, "live": {},
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
        log = CsvLog(self.adx, self.csv_path,
                     f"MS43 AI-Tuner log recorded on {self.started:%m/%d/%Y %H:%M:%S} "
                     f"with {os.path.basename(self.adx_path)}")
        data_packets = {c.packet for c in self.adx.channels}
        st = self.status
        port = None
        session = None
        connected = False
        fails = 0
        t0 = time.monotonic()
        stamps: List[float] = []
        last_flush = t0
        try:
            while not self._stop.is_set():
                if port is None:
                    try:
                        port = self.factory(self.adx)
                        session = Session(self.adx, port, journal)
                    except (OSError, ValueError) as exc:
                        st.update(state="no_port", message=str(exc))
                        journal.add("error", text=str(exc))
                        self._stop.wait(1.0)
                        port = None
                        continue
                if not connected:
                    st["state"] = "connecting"
                    try:
                        session.connect()
                        connected, fails = True, 0
                        st.update(state="recording", message="")
                        journal.add("info", text="connected")
                    except Ds2Error as exc:
                        st.update(state="reconnecting", message=str(exc))
                        st["reconnects"] += 1
                        self._stop.wait(1.0)
                        continue
                try:
                    replies = session.run(self.adx.monitor_macro)
                    fails = 0
                except Ds2Error as exc:
                    fails += 1
                    st["errors"] += 1
                    st["message"] = str(exc)
                    if fails >= FAILS_BEFORE_RECONNECT:
                        connected = False
                        journal.add("info", text="connection lost, reconnecting")
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
            log.close()
            journal.close()
            st["state"] = "stopped"
            if log.rows == 0:
                try:
                    os.remove(self.csv_path)          # the journal stays: it shows what went wrong
                except OSError:
                    pass
            elif self.on_done:
                self.on_done(self.csv_path)
