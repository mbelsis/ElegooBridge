"""Read-only recorder for the Centauri Carbon (SDCP v3).

Saves every WebSocket message on every topic to a JSONL file, prints non-status
messages in full, prints status fields that appear or change (temperatures,
ticks and coordinates are left out of the screen output but kept in the file),
and logs every connect, drop and reconnect. Sends only Cmd 0 (status) and
Cmd 1 (attributes): on connect, and Cmd 0 every 25 s as a keep-alive.

usage: python3 -I sdcp_record.py IP MAINBOARDID LOGFILE [MAX_SECONDS]
"""
import base64, json, os, socket, struct, sys, time, uuid

ip, mainboard, logfile = sys.argv[1], sys.argv[2], sys.argv[3]
max_seconds = float(sys.argv[4]) if len(sys.argv) > 4 else 7200
READ_ONLY = {0, 1}
NOISY = ("TempOf", "CurrenCoord", "CurrentTicks", "TimeStamp")
KEEPALIVE = 25

log = open(logfile, "a", buffering=1)

def now():
    return time.strftime("%H:%M:%S")

def event(kind, **info):
    log.write(json.dumps({"t": time.time(), "event": kind, **info}) + "\n")
    print(now(), "**", kind, json.dumps(info) if info else "", flush=True)

def connect():
    s = socket.create_connection((ip, 3030), timeout=5)
    key = base64.b64encode(os.urandom(16)).decode()
    s.sendall(("GET /websocket HTTP/1.1\r\nHost: %s:3030\r\nUpgrade: websocket\r\nConnection: Upgrade\r\n"
               "Sec-WebSocket-Key: %s\r\nSec-WebSocket-Version: 13\r\n\r\n" % (ip, key)).encode())
    head = b""
    while b"\r\n\r\n" not in head:
        chunk = s.recv(1)
        if not chunk:
            raise ConnectionError("closed during handshake")
        head += chunk
    if b" 101 " not in head.split(b"\r\n")[0]:
        raise ConnectionError("handshake failed: %r" % head[:200])
    return s

def send_text(s, text):
    data = text.encode()
    mask = os.urandom(4)
    n = len(data)
    header = bytes([0x81]) + (bytes([0x80 | n]) if n < 126 else bytes([0x80 | 126]) + struct.pack(">H", n))
    s.sendall(header + mask + bytes(b ^ mask[i % 4] for i, b in enumerate(data)))

def request(s, cmd):
    assert cmd in READ_ONLY
    send_text(s, json.dumps({"Id": "", "Data": {"Cmd": cmd, "Data": {}, "RequestID": uuid.uuid4().hex,
              "MainboardID": mainboard, "TimeStamp": int(time.time()), "From": 1},
              "Topic": "sdcp/request/" + mainboard}))

class Frames:
    def __init__(self, s):
        self.s, self.buf = s, b""

    def need(self, k):
        while len(self.buf) < k:
            chunk = self.s.recv(65536)
            if not chunk:
                raise EOFError
            self.buf += chunk

    def next(self):
        self.need(2)
        op, ln, pos = self.buf[0] & 0x0F, self.buf[1] & 0x7F, 2
        if ln == 126:
            self.need(4); ln = struct.unpack(">H", self.buf[2:4])[0]; pos = 4
        elif ln == 127:
            self.need(10); ln = struct.unpack(">Q", self.buf[2:10])[0]; pos = 10
        self.need(pos + ln)
        payload, self.buf = self.buf[pos:pos + ln], self.buf[pos + ln:]
        return op, payload

def flatten(d, prefix=""):
    out = {}
    for k, v in d.items():
        key = prefix + k
        if isinstance(v, dict):
            out.update(flatten(v, key + "."))
        else:
            out[key] = v
    return out

seen = {}
def show_changes(kind, flat):
    changes = []
    for k, v in flat.items():
        old = seen.get((kind, k), "<new>")
        if v != old:
            seen[(kind, k)] = v
            if not any(n in k for n in NOISY):
                changes.append("%s=%s" % (k, json.dumps(v)) if old == "<new>" else "%s: %s -> %s" % (k, json.dumps(old), json.dumps(v)))
    if changes:
        print(now(), kind, "|", "; ".join(changes), flush=True)

start = time.time()
attempt = 0
while time.time() - start < max_seconds:
    try:
        s = connect()
    except OSError as e:
        attempt += 1
        if attempt == 1 or attempt % 10 == 0:
            event("connect_failed", error=type(e).__name__ + ": " + str(e), attempt=attempt)
        time.sleep(3)
        continue
    event("connected", after_attempts=attempt)
    attempt = 0
    s.settimeout(1)
    frames = Frames(s)
    connected_at = last_ping = time.time()
    try:
        request(s, 1)
        request(s, 0)
        while time.time() - start < max_seconds:
            if time.time() - last_ping > KEEPALIVE:
                request(s, 0); last_ping = time.time()
            try:
                op, payload = frames.next()
            except socket.timeout:
                continue
            if op == 0x9:
                s.sendall(bytes([0x8A, 0x80 | len(payload)]) + b"\0\0\0\0" + payload); continue
            if op == 0x8:
                event("close_frame", payload=payload.hex(), connected_for=round(time.time() - connected_at)); break
            if op != 0x1:
                event("frame", op=op, payload=payload[:200].hex()); continue
            text = payload.decode(errors="replace")
            log.write(json.dumps({"t": time.time(), "msg": text}) + "\n")
            try:
                d = json.loads(text)
            except ValueError:
                print(now(), "TEXT", text[:500], flush=True); continue
            topic = (d.get("Topic") or "?").split("/")[1] if "/" in (d.get("Topic") or "") else d.get("Topic", "?")
            if topic == "status":
                show_changes("status", flatten(d.get("Status", {})))
            elif topic == "attributes":
                show_changes("attributes", flatten(d.get("Attributes", {})))
            elif topic == "response" and d.get("Data", {}).get("Cmd") in READ_ONLY and d["Data"].get("Data") == {"Ack": 0}:
                pass
            else:
                print(now(), "!!", topic.upper(), json.dumps(d)[:1500], flush=True)
    except (EOFError, OSError) as e:
        event("dropped", error=type(e).__name__ + ": " + str(e), connected_for=round(time.time() - connected_at))
    finally:
        s.close()
event("recorder_stopped")
