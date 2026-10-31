"""The Centauri's camera as a Bambu P1S camera, shared by any number of viewers.

The Centauri streams MJPEG at http://HOST:3031/video but allows only four
viewers, and Bambuddy opens one per view and snapshot. The relay keeps a single
connection to the printer while anyone is watching, and serves every viewer
with the P1-series "chamber image" protocol Bambuddy uses for a P1S:
TLS on port 6000, an 80-byte login (bblp + access code), then frames of a
16-byte header (little-endian JPEG size first) followed by the JPEG.
"""
from __future__ import annotations

import hmac
import http.client
import logging
import socket
import ssl
import struct
import threading
import time
from pathlib import Path

log = logging.getLogger("elegoobridge.camera")

SOI, EOI = b"\xff\xd8", b"\xff\xd9"
MAX_FRAME = 5 * 1024 * 1024
IDLE_CLOSE = 10.0       # seconds without viewers before the printer connection is closed
RETRY = 5.0             # seconds between attempts while the camera is unavailable
LOGIN_SIZE = 80
NO_FRAME_LIMIT = 20.0   # seconds a viewer waits for a frame before being disconnected


def split_frames(buffer: bytes) -> tuple[list[bytes], bytes]:
    """JPEG frames found in an MJPEG byte stream, and the unfinished rest."""
    frames = []
    while True:
        start = buffer.find(SOI)
        if start < 0:
            return frames, b""
        end = buffer.find(EOI, start + 2)
        if end < 0:
            buffer = buffer[start:]
            if len(buffer) > MAX_FRAME:
                buffer = b""
            return frames, buffer
        frames.append(buffer[start:end + 2])
        buffer = buffer[end + 2:]


def frame_header(size: int) -> bytes:
    return struct.pack("<IIII", size, 0, 1, 0)


def parse_login(packet: bytes) -> tuple[str, str]:
    if len(packet) != LOGIN_SIZE:
        raise ValueError("short login packet")
    _magic, _command, _pad, user, code = struct.unpack("<II8s32s32s", packet)
    return user.rstrip(b"\x00").decode(errors="replace"), code.rstrip(b"\x00").decode(errors="replace")


class CameraRelay:
    """One MJPEG connection to the printer, opened only while someone watches."""

    def __init__(self, host: str, port: int = 3031, path: str = "/video") -> None:
        self.host, self.port, self.path = host, port, path
        self.frame: bytes | None = None
        self.frame_number = 0
        self.viewers = 0
        self._changed = threading.Condition()
        self._thread: threading.Thread | None = None
        self._last_viewer = time.time()

    def subscribe(self) -> None:
        with self._changed:
            self.viewers += 1
            if self._thread is None or not self._thread.is_alive():
                self._thread = threading.Thread(target=self._run, name="camera", daemon=True)
                self._thread.start()

    def unsubscribe(self) -> None:
        with self._changed:
            self.viewers = max(0, self.viewers - 1)
            self._last_viewer = time.time()

    def next_frame(self, after: int, timeout: float = 10.0) -> tuple[int, bytes] | None:
        """The first frame newer than `after`, or None if none arrives in time."""
        with self._changed:
            if not self._changed.wait_for(lambda: self.frame_number > after, timeout):
                return None
            return self.frame_number, self.frame

    def _wanted(self) -> bool:
        with self._changed:
            return self.viewers > 0 or time.time() - self._last_viewer < IDLE_CLOSE

    def _run(self) -> None:
        while self._wanted():
            try:
                self._stream()
            except (OSError, http.client.HTTPException) as error:
                log.info("camera unavailable: %s", error)
            if self._wanted():
                time.sleep(RETRY)
        log.info("camera connection closed (no viewers)")

    def _stream(self) -> None:
        connection = http.client.HTTPConnection(self.host, self.port, timeout=10)
        try:
            connection.request("GET", self.path)
            response = connection.getresponse()
            if response.status != 200:
                # The Centauri answers 500 when all four of its viewer slots are taken.
                raise OSError(f"HTTP {response.status} (the printer allows four camera viewers)")
            log.info("camera connected")
            buffer = b""
            while self._wanted():
                chunk = response.read1(65536)
                if not chunk:
                    raise OSError("camera stream ended")
                frames, buffer = split_frames(buffer + chunk)
                if frames:
                    with self._changed:
                        self.frame = frames[-1]
                        self.frame_number += 1
                        self._changed.notify_all()
        finally:
            connection.close()


class ChamberImageServer:
    """Bambu P1-series camera protocol on port 6000, fed by the relay."""

    def __init__(self, relay: CameraRelay, certfile: Path, keyfile: Path, access_code: str, port: int = 6000):
        self.relay, self.access_code, self.port = relay, access_code, port
        self.context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        self.context.load_cert_chain(str(certfile), str(keyfile))
        self.sock = socket.create_server(("0.0.0.0", port), reuse_port=False)

    def start(self) -> None:
        threading.Thread(target=self._accept, name="camera-server", daemon=True).start()
        log.info("camera on port %s (P1S chamber image protocol)", self.port)

    def close(self) -> None:
        self.sock.close()

    def _accept(self) -> None:
        while True:
            try:
                client, _ = self.sock.accept()
            except OSError:
                return
            threading.Thread(target=self._serve, args=(client,), name="camera-viewer", daemon=True).start()

    def _serve(self, raw: socket.socket) -> None:
        raw.settimeout(15)
        try:
            with self.context.wrap_socket(raw, server_side=True) as conn:
                packet = b""
                while len(packet) < LOGIN_SIZE:
                    chunk = conn.recv(LOGIN_SIZE - len(packet))
                    if not chunk:
                        return
                    packet += chunk
                user, code = parse_login(packet)
                if user != "bblp" or not hmac.compare_digest(code, self.access_code):
                    log.warning("camera login refused")
                    return
                self.relay.subscribe()
                try:
                    number = self.relay.frame_number - 1 if self.relay.frame else 0
                    while True:
                        got = self.relay.next_frame(number, timeout=NO_FRAME_LIMIT)
                        if got is None:
                            return  # the printer's camera is unavailable
                        number, frame = got
                        conn.sendall(frame_header(len(frame)) + frame)
                finally:
                    self.relay.unsubscribe()
        except (OSError, ValueError, ssl.SSLError):
            return
