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

START = {"Filename": sys.argv[6] if len(sys.argv) > 6 else "PlateBridge-test-cube.gcode", "StartLayer": 0, "Calibration_switch": 1, "PrintPlatformType": 0,
         "Tlp_Switch": 0, "slot_map": [], "path_prefix": "/local"}
ALLOWED = {"status": (0, {}), "start": (128, START), "pause": (129, {}), "resume": (131, {}), "stop": (130, {})}

def send(s, cmd, data):
    assert (cmd, data) in ALLOWED.values()
    msg = {"Id": "", "Data": {"Cmd": cmd, "Data": data, "RequestID": uuid.uuid4().hex, "MainboardID": mainboard,
                              "TimeStamp": int(time.time()), "From": 1}, "Topic": "sdcp/request/" + mainboard}
    send_text(s, json.dumps(msg))

def listen(s, secs, label):
    end = time.time() + secs; last = None
    while time.time() < end:
        try: op, payload = recv_frame(s)
        except socket.timeout: continue
        if op == 0x9:
            s.sendall(bytes([0x8A, 0x80 | len(payload)]) + b"\0\0\0\0" + payload); continue
        if op != 0x1: continue
        d = json.loads(payload.decode(errors="replace"))
        if "response" in d.get("Topic", ""):
            print(time.strftime("%H:%M:%S"), label, "ack Cmd", d["Data"]["Cmd"], d["Data"]["Data"], flush=True)
        st = d.get("Status")
        if st:
            pi = st["PrintInfo"]
            line = "state %s print %s file=%r layer %s/%s prog %s%% | nozzle %.0f->%s bed %.0f->%s" % (st["CurrentStatus"], pi["Status"], pi["Filename"], pi["CurrentLayer"], pi["TotalLayer"], pi["Progress"], st["TempOfNozzle"], st["TempTargetNozzle"], st["TempOfHotbed"], st["TempTargetHotbed"])
            if line != last: print(time.strftime("%H:%M:%S"), label, line, flush=True); last = line

action, secs = sys.argv[4], float(sys.argv[5])
s = connect(); s.settimeout(1)
send(s, *ALLOWED["status"]); listen(s, 2, "before")
if action != "status":
    send(s, *ALLOWED[action])
listen(s, secs, action)
s.close()
