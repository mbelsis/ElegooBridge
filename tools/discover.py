"""Send the SDCP discovery probe (as ElegooSlicer does) to one printer and print the reply."""
import json, socket, sys
ip = sys.argv[1]
s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
s.settimeout(3)
s.sendto(b"M99999", (ip, 3000))
try:
    data, addr = s.recvfrom(65535)
    print(addr)
    try:
        print(json.dumps(json.loads(data), indent=2))
    except ValueError:
        print(data[:2000])
except socket.timeout:
    print("no reply")
