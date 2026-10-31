"""python -m elegoobridge            run the bridge (settings from the environment)
python -m elegoobridge discover   find Centauri printers on the local network
python -m elegoobridge certs      create the TLS certificate if missing (run by Docker Compose)

Stamping print files for Bambuddy is a separate script: stamp/stamp_for_bambuddy.py"""
from __future__ import annotations

import json
import logging
import socket
import sys


def discover(timeout: float = 3.0, tries: int = 3) -> int:
    # The Centauri only answers discovery sent as a broadcast. Wi-Fi can drop a
    # single UDP packet, so the probe is sent several times.
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
    sock.settimeout(timeout / tries)
    found: dict[str, dict] = {}
    for _ in range(tries):
        sock.sendto(b"M99999", ("255.255.255.255", 3000))
        try:
            while True:
                data, (address, _) = sock.recvfrom(65535)
                try:
                    found.setdefault(address, json.loads(data).get("Data") or {})
                except ValueError:
                    continue
        except socket.timeout:
            pass
    for address, info in found.items():
        print(f"{info.get('Name', '?')} at {address}: PRINTER_MAINBOARD_ID={info.get('MainboardID', '?')} "
              f"(firmware {info.get('FirmwareVersion', '?')})")
    if not found:
        print("No printers answered.")
    return 0 if found else 1


def main() -> int:
    if sys.argv[1:] == ["discover"]:
        return discover()
    if sys.argv[1:2] == ["certs"]:
        from elegoobridge.certs import main as certs

        return certs(*sys.argv[2:])
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
