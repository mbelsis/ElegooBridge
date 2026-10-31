"""python -m elegoobridge            run the bridge (settings from the environment)
python -m elegoobridge discover   find Centauri printers on the local network"""
from __future__ import annotations

import json
import logging
import socket
import sys


def discover(timeout: float = 3.0) -> int:
    # The Centauri only answers discovery sent as a broadcast.
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
    sock.settimeout(timeout)
    sock.sendto(b"M99999", ("255.255.255.255", 3000))
    found = 0
    try:
        while True:
            data, (address, _) = sock.recvfrom(65535)
            try:
                info = json.loads(data).get("Data") or {}
            except ValueError:
                continue
            found += 1
            print(f"{info.get('Name', '?')} at {address}: PRINTER_MAINBOARD_ID={info.get('MainboardID', '?')} "
                  f"(firmware {info.get('FirmwareVersion', '?')})")
    except socket.timeout:
        pass
    if not found:
        print("No printers answered.")
    return 0 if found else 1


def main() -> int:
    if sys.argv[1:] == ["discover"]:
        return discover()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    from elegoobridge.config import Config, ConfigError

    try:
        cfg = Config.from_env()
    except ConfigError as error:
        print(f"Configuration error: {error}", file=sys.stderr)
        return 2
    from elegoobridge.bridge import Bridge

    Bridge(cfg).run_forever()
    return 0


if __name__ == "__main__":
    sys.exit(main())
