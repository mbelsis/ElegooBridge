"""Create the self-signed TLS certificate the bridge presents, if it doesn't exist.

Bambu printers use self-signed certificates and Bambuddy doesn't verify them, so
any certificate works. Run by Docker Compose before the other services start
(`python -m elegoobridge certs`), so nobody needs OpenSSL on their computer.
"""
from __future__ import annotations

import datetime
import sys
from pathlib import Path

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID


def create(folder: Path, days: int = 3650) -> bool:
    """Write server.crt and server.key into folder; False if they already exist."""
    cert, key_file = folder / "server.crt", folder / "server.key"
    if cert.exists() and key_file.exists():
        return False
    folder.mkdir(parents=True, exist_ok=True)
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "elegoobridge")])
    now = datetime.datetime.now(datetime.timezone.utc)
    certificate = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - datetime.timedelta(days=1))
        .not_valid_after(now + datetime.timedelta(days=days))
        .sign(key, hashes.SHA256())
    )
    key_file.write_bytes(key.private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.TraditionalOpenSSL, serialization.NoEncryption()))
    cert.write_bytes(certificate.public_bytes(serialization.Encoding.PEM))
    # Mosquitto and the bridge run as different users and both need to read them.
    key_file.chmod(0o644)
    cert.chmod(0o644)
    return True


def main(folder: str = "/certs") -> int:
    made = create(Path(folder))
    print(f"Created a TLS certificate in {folder}" if made else f"TLS certificate already present in {folder}")
    return 0


if __name__ == "__main__":
    sys.exit(main(*sys.argv[1:]))
