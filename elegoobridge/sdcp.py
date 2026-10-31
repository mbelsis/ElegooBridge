"""Client for Elegoo's SDCP v3 protocol (Centauri Carbon), standard library only.

One background thread keeps a WebSocket open to ws://HOST:3030/websocket, sends a
status request every 25 s so the printer doesn't drop the connection, reconnects
whenever it does, and hands every status push to a callback.

Only the commands in docs/FINDINGS.md are allowed: the printer's main program can
crash on command numbers it doesn't know.
"""
from __future__ import annotations

import base64
import json
import logging
import os
import socket
import struct
import threading
import time
import uuid
from typing import Any, Callable

log = logging.getLogger("elegoobridge.sdcp")

STATUS, ATTRIBUTES = 0, 1
START, PAUSE, STOP, RESUME = 128, 129, 130, 131
FILE_LIST, HISTORY, HISTORY_DETAIL = 258, 320, 321
MOVE_AXIS, HOME_AXES, SET_PARAMS = 401, 402, 403

ALLOWED = {STATUS, ATTRIBUTES, START, PAUSE, STOP, RESUME, FILE_LIST, HISTORY, HISTORY_DETAIL,
           MOVE_AXIS, HOME_AXES, SET_PARAMS}
SET_PARAMS_KEYS = {"TargetFanSpeed", "TempTargetNozzle", "TempTargetHotbed", "LightStatus", "PrintSpeedPct"}
MAX_STEP = 100.0  # mm, the printer's own control panel's largest step

# Ack codes for moves and homing, from the printer's web page (axisError)
AXIS_ERRORS = {1: "the printer is busy", 2: "parameter error", 3: "home the axis before moving it",
               4: "homing failed", 5: "homing failed"}

KEEPALIVE = 25.0
RECONNECT_DELAY = 3.0


class SdcpError(Exception):
    pass


def check_command(cmd: int, data: dict[str, Any]) -> None:
    """Refuse anything outside the tested command set."""
    if cmd not in ALLOWED:
        raise SdcpError(f"command {cmd} is not allowed")
    if cmd == SET_PARAMS and (not data or not set(data) <= SET_PARAMS_KEYS):
        raise SdcpError(f"command 403 with fields {sorted(data)} is not allowed")
    if cmd == MOVE_AXIS:
        step = data.get("Step")
        if (set(data) != {"Axis", "Step"} or data["Axis"] not in ("X", "Y", "Z")
                or not isinstance(step, (int, float)) or not 0 < abs(step) <= MAX_STEP):
            raise SdcpError(f"move {data} is not allowed")
    if cmd == HOME_AXES and (set(data) != {"Axis"} or data["Axis"] not in ("X", "Y", "Z", "XYZ")):
        raise SdcpError(f"home {data} is not allowed")


class _Frames:
    def __init__(self, sock: socket.socket) -> None:
        self.sock, self.buf = sock, b""
        self._op: int | None = None   # the message being reassembled from fragments
        self._fragments: list[bytes] = []

    def _need(self, size: int) -> None:
        while len(self.buf) < size:
            chunk = self.sock.recv(65536)
            if not chunk:
                raise EOFError("closed by printer")
            self.buf += chunk

    def next(self) -> tuple[int, bytes]:
        """The next whole message: fragments are joined, control frames
        (which may arrive between fragments) are returned as they come. A
        partly received message survives a read timeout."""
        while True:
            fin, op, payload = self._frame()
            if op >= 0x8:
                return op, payload
            if op != 0x0:
                self._op, self._fragments = op, []
            elif self._op is None:
                continue  # a continuation without its start
            self._fragments.append(payload)
            if fin:
                message = (self._op, b"".join(self._fragments))
                self._op, self._fragments = None, []
                return message

    def _frame(self) -> tuple[bool, int, bytes]:
        self._need(2)
        fin, op, size, pos = bool(self.buf[0] & 0x80), self.buf[0] & 0x0F, self.buf[1] & 0x7F, 2
        if size == 126:
            self._need(4)
            size, pos = struct.unpack(">H", self.buf[2:4])[0], 4
        elif size == 127:
            self._need(10)
            size, pos = struct.unpack(">Q", self.buf[2:10])[0], 10
        self._need(pos + size)
        payload, self.buf = self.buf[pos:pos + size], self.buf[pos + size:]
        return fin, op, payload


def _frame(op: int, data: bytes) -> bytes:
    """A masked client frame, as the WebSocket protocol requires."""
    mask = os.urandom(4)
    size = len(data)
    if size < 126:
        head = bytes([0x80 | op, 0x80 | size])
    elif size < 65536:
        head = bytes([0x80 | op, 0x80 | 126]) + struct.pack(">H", size)
    else:
        head = bytes([0x80 | op, 0x80 | 127]) + struct.pack(">Q", size)
    return head + mask + bytes(b ^ mask[i % 4] for i, b in enumerate(data))


class SdcpClient:
    def __init__(
        self,
        host: str,
        mainboard_id: str,
        on_status: Callable[[dict[str, Any]], None] | None = None,
        on_connection: Callable[[bool], None] | None = None,
        port: int = 3030,
    ) -> None:
        self.host, self.port, self.mainboard_id = host, port, mainboard_id
        self.on_status = on_status
        self.on_connection = on_connection
        self.status: dict[str, Any] = {}
        self.attributes: dict[str, Any] = {}
        self.connected = False
        self._sock: socket.socket | None = None
        self._send_lock = threading.Lock()
        self._pending: dict[str, tuple[threading.Event, dict[str, Any]]] = {}
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, name="sdcp", daemon=True)

    def start(self) -> None:
        self._thread.start()

    def close(self) -> None:
        self._stop.set()
        if self._sock:
            self._sock.close()

    # Requests

    def request(self, cmd: int, data: dict[str, Any] | None = None, timeout: float = 5.0) -> dict[str, Any]:
        """Send a command and return the reply's Data (with "Ack"). Raises SdcpError."""
        data = data or {}
        check_command(cmd, data)
        request_id = uuid.uuid4().hex
        waiter = (threading.Event(), {})
        self._pending[request_id] = waiter
        try:
            self._send(cmd, data, request_id)
            if not waiter[0].wait(timeout):
                raise SdcpError(f"no reply to command {cmd}")
            reply = waiter[1]
        finally:
            self._pending.pop(request_id, None)
        ack = reply.get("Ack")
        if ack not in (0, None):
            if cmd in (MOVE_AXIS, HOME_AXES) and ack in AXIS_ERRORS:
                raise SdcpError(f"printer refused: {AXIS_ERRORS[ack]}")
            raise SdcpError(f"command {cmd} refused: {reply}")
        return reply

    def history_entry(self, task_id: str) -> dict[str, Any] | None:
        """The print-history entry for a task, if the printer lists it."""
        ids = self.request(HISTORY).get("HistoryData") or []
        if task_id not in ids:
            return None
        details = self.request(HISTORY_DETAIL, {"Id": [task_id]}).get("HistoryDetailList") or []
        return next((d for d in details if d.get("TaskId") == task_id), None)

    def _send(self, cmd: int, data: dict[str, Any], request_id: str | None = None) -> None:
        message = {
            "Id": "",
            "Data": {
                "Cmd": cmd,
                "Data": data,
                "RequestID": request_id or uuid.uuid4().hex,
                "MainboardID": self.mainboard_id,
                "TimeStamp": int(time.time()),
                "From": 1,
            },
            "Topic": f"sdcp/request/{self.mainboard_id}",
        }
        with self._send_lock:
            if not self._sock or not self.connected:
                raise SdcpError("printer not connected")
            self._sock.sendall(_frame(0x1, json.dumps(message).encode()))

    # Connection

    def _connect(self) -> socket.socket:
        sock = socket.create_connection((self.host, self.port), timeout=5)
        key = base64.b64encode(os.urandom(16)).decode()
        sock.sendall(
            (
                f"GET /websocket HTTP/1.1\r\nHost: {self.host}:{self.port}\r\nUpgrade: websocket\r\n"
                f"Connection: Upgrade\r\nSec-WebSocket-Key: {key}\r\nSec-WebSocket-Version: 13\r\n\r\n"
            ).encode()
        )
        head = b""
        while b"\r\n\r\n" not in head:
            chunk = sock.recv(1)
            if not chunk:
                raise ConnectionError("closed during handshake")
            head += chunk
        if b" 101 " not in head.split(b"\r\n")[0]:
            raise ConnectionError(f"handshake refused: {head[:120]!r}")
        return sock

    def _set_connected(self, value: bool) -> None:
        if value != self.connected:
            self.connected = value
            log.info("printer %s %s", self.host, "connected" if value else "disconnected")
            if self.on_connection:
                self.on_connection(value)

    def _run(self) -> None:
        failures = 0
        while not self._stop.is_set():
            try:
                sock = self._connect()
            except OSError as error:
                failures += 1
                if failures == 1 or failures % 20 == 0:
                    log.warning("cannot reach printer %s: %s", self.host, error)
                self._stop.wait(RECONNECT_DELAY)
                continue
            failures = 0
            self._sock = sock
            sock.settimeout(1)
            self._set_connected(True)
            try:
                self._send(ATTRIBUTES, {})
                self._send(STATUS, {})
                self._read(sock)
            except (OSError, EOFError, SdcpError) as error:
                log.info("printer connection lost: %s", error)
            finally:
                with self._send_lock:
                    sock.close()
                    self._sock = None
                self._set_connected(False)
                for event, reply in list(self._pending.values()):
                    reply.setdefault("Ack", "disconnected")
                    event.set()
            self._stop.wait(RECONNECT_DELAY)

    def _read(self, sock: socket.socket) -> None:
        frames = _Frames(sock)
        last_keepalive = time.time()
        while not self._stop.is_set():
            if time.time() - last_keepalive > KEEPALIVE:
                self._send(STATUS, {})
                last_keepalive = time.time()
            try:
                op, payload = frames.next()
            except socket.timeout:
                continue
            if op == 0x9:
                with self._send_lock:
                    sock.sendall(_frame(0xA, payload))
            elif op == 0x8:
                raise EOFError("printer closed the connection")
            elif op == 0x1:
                self._handle(payload)

    def _handle(self, payload: bytes) -> None:
        try:
            message = json.loads(payload)
        except ValueError:
            log.debug("ignored non-JSON message: %r", payload[:120])
            return
        topic = (message.get("Topic") or "").split("/")
        kind = topic[1] if len(topic) > 1 else ""
        if kind == "status" and isinstance(message.get("Status"), dict):
            self.status = message["Status"]
            if self.on_status:
                self.on_status(self.status)
        elif kind == "attributes" and isinstance(message.get("Attributes"), dict):
            self.attributes = message["Attributes"]
        elif kind == "response":
            data = message.get("Data") or {}
            waiter = self._pending.get(data.get("RequestID", ""))
            if waiter:
                waiter[1].update(data.get("Data") or {})
                waiter[0].set()
        else:
            log.info("printer message on %s: %s", kind or "?", json.dumps(message)[:500])
