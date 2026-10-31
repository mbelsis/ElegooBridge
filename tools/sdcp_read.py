"""Read-only SDCP v3 probe: connect, request status (Cmd 0) and attributes (Cmd 1), print replies.
Sends no print, motion, file, camera or settings commands."""
import base64, json, os, socket, struct, sys, time, uuid

READ_ONLY = {0, 1}
ip, mainboard = sys.argv[1], sys.argv[2]
seconds = float(sys.argv[3]) if len(sys.argv) > 3 else 8

def connect():
    s = socket.create_connection((ip, 3030), timeout=5)
    key = base64.b64encode(os.urandom(16)).decode()
    s.sendall(("GET /websocket HTTP/1.1\r\nHost: %s:3030\r\nUpgrade: websocket\r\nConnection: Upgrade\r\n"
               "Sec-WebSocket-Key: %s\r\nSec-WebSocket-Version: 13\r\n\r\n" % (ip, key)).encode())
    head = b""
    while b"\r\n\r\n" not in head:
        chunk = s.recv(1)
        if not chunk:
            raise SystemExit("connection closed during handshake")
        head += chunk
    status = head.split(b"\r\n")[0]
    if b" 101 " not in status:
        raise SystemExit("handshake failed: %r" % head[:300])
    return s

def send_text(s, text):
    data = text.encode()
    mask = os.urandom(4)
    n = len(data)
    header = bytes([0x81]) + (bytes([0x80 | n]) if n < 126 else bytes([0x80 | 126]) + struct.pack(">H", n))
    s.sendall(header + mask + bytes(b ^ mask[i % 4] for i, b in enumerate(data)))

buf = b""
def recv_frame(s):
    global buf
    def need(k):
        global buf
        while len(buf) < k:
            chunk = s.recv(65536)
            if not chunk:
                raise EOFError
            buf += chunk
    need(2)
    op, ln = buf[0] & 0x0F, buf[1] & 0x7F
    pos = 2
    if ln == 126:
        need(4); ln = struct.unpack(">H", buf[2:4])[0]; pos = 4
    elif ln == 127:
        need(10); ln = struct.unpack(">Q", buf[2:10])[0]; pos = 10
    need(pos + ln)
    payload, buf = buf[pos:pos + ln], buf[pos + ln:]
    return op, payload

def request(s, cmd):
    assert cmd in READ_ONLY
    msg = {"Id": "", "Data": {"Cmd": cmd, "Data": {}, "RequestID": uuid.uuid4().hex, "MainboardID": mainboard,
                              "TimeStamp": int(time.time()), "From": 1},
           "Topic": "sdcp/request/" + mainboard}
    send_text(s, json.dumps(msg))

s = connect()
print("connected")
request(s, 1)
request(s, 0)
end = time.time() + seconds
s.settimeout(1)
while time.time() < end:
    try:
        op, payload = recv_frame(s)
    except socket.timeout:
        continue
    except EOFError:
        print("closed by printer"); break
    if op == 0x9:          # ping -> pong
        s.sendall(bytes([0x8A, 0x80 | len(payload)]) + b"\0\0\0\0" + payload); continue
    if op != 0x1:
        print("frame op", op, payload[:100]); continue
    text = payload.decode(errors="replace")
    try:
        d = json.loads(text)
        print("\n### topic:", d.get("Topic"))
        print(json.dumps(d, indent=1)[:4000])
    except ValueError:
        print("text:", text[:300])
s.close()
