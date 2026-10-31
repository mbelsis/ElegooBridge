"""The camera relay: a fake Centauri MJPEG camera, the bridge's port-6000 server,
and a client doing what Bambuddy's P1S camera code does."""
import http.server
import socket
import socketserver
import ssl
import struct
import subprocess
import tempfile
import threading
import time
import unittest
from pathlib import Path

from elegoobridge import camera

FRAME = b"\xff\xd8" + b"jpeg-body" * 50 + b"\xff\xd9"


class FakeCamera(http.server.BaseHTTPRequestHandler):
    connections = 0
    full = False

    def do_GET(self):
        if FakeCamera.full:
            self.send_response(500)
            self.end_headers()
            return
        FakeCamera.connections += 1
        self.send_response(200)
        self.send_header("Content-Type", "multipart/x-mixed-replace; boundary=--foo")
        self.end_headers()
        try:
            for _ in range(200):
                self.wfile.write(b"--foo\r\nContent-Type: image/jpeg\r\n\r\n" + FRAME + b"\r\n")
                self.wfile.flush()
                time.sleep(0.05)
        except OSError:
            pass
        finally:
            FakeCamera.connections -= 1

    def log_message(self, *args):
        pass


def login(code, user=b"bblp"):
    return struct.pack("<II8s32s32s", 0x40, 0x3000, b"\x00" * 8, user.ljust(32, b"\x00"), code.ljust(32, b"\x00"))


def read_frame(port, code=b"secret"):
    """What Bambuddy's read_chamber_image_frame does."""
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    context.check_hostname = False
    context.verify_mode = ssl.CERT_NONE
    with context.wrap_socket(socket.create_connection(("127.0.0.1", port), timeout=5)) as s:
        s.sendall(login(code))
        header = b""
        while len(header) < 16:
            chunk = s.recv(16 - len(header))
            if not chunk:
                return None
            header += chunk
        size = struct.unpack("<I", header[:4])[0]
        data = b""
        while len(data) < size:
            data += s.recv(size - len(data))
        return data


class UnitTests(unittest.TestCase):
    def test_split_frames(self):
        frames, rest = camera.split_frames(b"junk" + FRAME + b"--foo\r\n" + FRAME + b"\r\n" + FRAME[:10])
        self.assertEqual(frames, [FRAME, FRAME])
        self.assertEqual(rest, FRAME[:10])
        self.assertEqual(camera.split_frames(b"no jpeg here"), ([], b""))

    def test_header_and_login(self):
        self.assertEqual(struct.unpack("<IIII", camera.frame_header(1234)), (1234, 0, 1, 0))
        self.assertEqual(camera.parse_login(login(b"abc123")), ("bblp", "abc123"))
        with self.assertRaises(ValueError):
            camera.parse_login(b"short")


class RelayTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        base = Path(cls.tmp.name)
        cls.cert, cls.key = base / "c", base / "k"
        subprocess.run(["openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-days", "1", "-subj", "/CN=t",
                        "-keyout", str(cls.key), "-out", str(cls.cert)], check=True, capture_output=True)
        cls.http = socketserver.ThreadingTCPServer(("127.0.0.1", 0), FakeCamera)
        cls.http.daemon_threads = True
        threading.Thread(target=cls.http.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.http.shutdown()
        cls.http.server_close()
        cls.tmp.cleanup()

    def setUp(self):
        FakeCamera.full = False
        self.old_idle, self.old_retry = camera.IDLE_CLOSE, camera.RETRY
        camera.IDLE_CLOSE, camera.RETRY = 0.5, 0.2
        self.relay = camera.CameraRelay("127.0.0.1", port=self.http.server_address[1])
        self.server = camera.ChamberImageServer(self.relay, self.cert, self.key, "secret", port=0)
        self.port = self.server.sock.getsockname()[1]
        self.server.start()

    def tearDown(self):
        self.server.close()
        camera.IDLE_CLOSE, camera.RETRY = self.old_idle, self.old_retry
        deadline = time.time() + 5
        while FakeCamera.connections and time.time() < deadline:
            time.sleep(0.05)

    def test_bambuddy_gets_a_jpeg(self):
        self.assertEqual(read_frame(self.port), FRAME)

    def test_many_viewers_share_one_printer_connection(self):
        results = []
        threads = [threading.Thread(target=lambda: results.append(read_frame(self.port))) for _ in range(8)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(10)
        self.assertEqual(results, [FRAME] * 8)
        self.assertLessEqual(FakeCamera.connections, 1)

    def test_printer_connection_closes_when_nobody_watches(self):
        read_frame(self.port)
        deadline = time.time() + 5
        while FakeCamera.connections and time.time() < deadline:
            time.sleep(0.05)
        self.assertEqual(FakeCamera.connections, 0)

    def test_wrong_access_code_gets_nothing(self):
        self.assertIsNone(read_frame(self.port, code=b"wrong"))
        self.assertEqual(self.relay.viewers, 0)

    def test_full_printer_camera_disconnects_the_viewer(self):
        FakeCamera.full = True
        old = camera.NO_FRAME_LIMIT
        camera.NO_FRAME_LIMIT = 1.0
        try:
            self.assertIsNone(read_frame(self.port))
        finally:
            camera.NO_FRAME_LIMIT = old


if __name__ == "__main__":
    unittest.main()
