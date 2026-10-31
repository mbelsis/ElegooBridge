"""The SDCP client against a small fake Centauri WebSocket server."""
import json
import socket
import socketserver
import struct
import threading
import time
import unittest

from elegoobridge import sdcp

BOARD = "board1"


def server_frame(text):
    data = text.encode()
    head = bytes([0x81, len(data)]) if len(data) < 126 else bytes([0x81, 126]) + struct.pack(">H", len(data))
    return head + data


def read_client_frame(sock):
    head = sock.recv(2)
    if len(head) < 2:
        raise EOFError
    size = head[1] & 0x7F
    if size == 126:
        size = struct.unpack(">H", sock.recv(2))[0]
    mask = sock.recv(4)
    data = b""
    while len(data) < size:
        data += sock.recv(size - len(data))
    return head[0] & 0x0F, bytes(b ^ mask[i % 4] for i, b in enumerate(data))


class FakePrinter(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True

    def __init__(self):
        super().__init__(("127.0.0.1", 0), Handler)
        self.received = []
        self.connections = 0
        self.history = {"HistoryData": ["t1"], "detail": [{"TaskId": "t1", "TaskStatus": 5, "ErrorStatusReason": 45}]}
        self.drop_next = False
        self.status = {"CurrentStatus": [0], "PrintInfo": {"Status": 0}}
        self.files = []
        self.sock = None

    def push(self, status):
        """Send a status push, as the printer does on every change."""
        self.status = status
        self.sock.sendall(server_frame(json.dumps({"Topic": f"sdcp/status/{BOARD}", "Status": status})))


class Handler(socketserver.BaseRequestHandler):
    def handle(self):
        server, sock = self.server, self.request
        head = b""
        while b"\r\n\r\n" not in head:
            head += sock.recv(1)
        sock.sendall(b"HTTP/1.1 101 Switching Protocols\r\nUpgrade: websocket\r\nConnection: Upgrade\r\n\r\n")
        server.connections += 1
        server.sock = sock
        while True:
            try:
                op, payload = read_client_frame(sock)
            except (EOFError, OSError):
                return
            if op != 1:
                continue
            message = json.loads(payload)
            data = message["Data"]
            server.received.append((data["Cmd"], data["Data"]))
            reply = {"Ack": 0}
            if data["Cmd"] == 320:
                reply["HistoryData"] = server.history["HistoryData"]
            elif data["Cmd"] == 321:
                reply["HistoryDetailList"] = server.history["detail"]
            elif data["Cmd"] == 258:
                reply["FileList"] = [{"name": f"/local/{n}", "type": 1} for n in server.files]
            sock.sendall(server_frame(json.dumps({
                "Topic": f"sdcp/response/{BOARD}",
                "Data": {"Cmd": data["Cmd"], "RequestID": data["RequestID"], "Data": reply}})))
            if data["Cmd"] == 0:
                sock.sendall(server_frame(json.dumps({"Topic": f"sdcp/status/{BOARD}", "Status": server.status})))
            if server.drop_next:
                server.drop_next = False
                sock.close()
                return


class ClientTests(unittest.TestCase):
    def setUp(self):
        self.server = FakePrinter()
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.statuses, self.connections = [], []
        self.old_delay = sdcp.RECONNECT_DELAY
        sdcp.RECONNECT_DELAY = 0.1
        self.client = sdcp.SdcpClient(
            "127.0.0.1", BOARD, on_status=self.statuses.append, on_connection=self.connections.append,
            port=self.server.server_address[1])
        self.client.start()
        self.wait(lambda: self.statuses)

    def tearDown(self):
        self.client.close()
        self.server.shutdown()
        self.server.server_close()
        sdcp.RECONNECT_DELAY = self.old_delay

    def wait(self, condition, timeout=3.0):
        end = time.time() + timeout
        while time.time() < end:
            if condition():
                return
            time.sleep(0.02)
        self.fail("timed out")

    def test_connects_and_asks_for_attributes_and_status(self):
        self.assertTrue(self.client.connected)
        self.assertEqual([cmd for cmd, _ in self.server.received[:2]], [1, 0])
        self.assertEqual(self.statuses[0]["PrintInfo"]["Status"], 0)

    def test_request_waits_for_the_ack(self):
        self.assertEqual(self.client.request(sdcp.PAUSE), {"Ack": 0})
        self.assertIn((sdcp.PAUSE, {}), self.server.received)

    def test_history_entry(self):
        self.assertEqual(self.client.history_entry("t1")["ErrorStatusReason"], 45)
        self.assertIsNone(self.client.history_entry("other"))

    def test_disallowed_command_is_never_sent(self):
        with self.assertRaises(sdcp.SdcpError):
            self.client.request(259, {})
        self.assertNotIn(259, [cmd for cmd, _ in self.server.received])

    def test_fragmented_messages_are_joined(self):
        text = json.dumps({"Topic": f"sdcp/status/{BOARD}", "Status": {"PrintInfo": {"Status": 13}}}).encode()
        first, second = text[:20], text[20:]
        # Text frame without FIN, a ping in between, then the final continuation.
        self.server.sock.sendall(bytes([0x01, len(first)]) + first + bytes([0x89, 0])
                                 + bytes([0x80, len(second)]) + second)
        self.wait(lambda: self.client.status.get("PrintInfo", {}).get("Status") == 13)

    def test_reconnects_after_the_printer_drops(self):
        self.server.drop_next = True
        self.client.request(sdcp.STATUS)
        self.wait(lambda: self.server.connections >= 2)
        self.wait(lambda: self.client.connected)
        self.assertIn(False, self.connections)


class OfflineTests(unittest.TestCase):
    def test_request_without_a_printer_fails(self):
        client = sdcp.SdcpClient("127.0.0.1", BOARD, port=1)
        with self.assertRaises(sdcp.SdcpError):
            client.request(sdcp.STATUS)


if __name__ == "__main__":
    unittest.main()
