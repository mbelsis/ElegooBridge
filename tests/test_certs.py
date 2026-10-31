import ssl
import tempfile
import unittest
from pathlib import Path

try:
    from elegoobridge.certs import create
except ImportError:  # cryptography not installed
    create = None


@unittest.skipIf(create is None, "cryptography is not installed")
class CertTests(unittest.TestCase):
    def test_creates_a_usable_certificate_once(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp) / "certs"
            self.assertTrue(create(folder))
            context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
            context.load_cert_chain(folder / "server.crt", folder / "server.key")
            before = (folder / "server.key").read_bytes()
            self.assertFalse(create(folder))
            self.assertEqual((folder / "server.key").read_bytes(), before)


if __name__ == "__main__":
    unittest.main()
