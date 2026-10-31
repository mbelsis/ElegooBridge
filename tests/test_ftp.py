"""The bridge's FTPS server with a real implicit-TLS FTP client, as Bambuddy uses."""
import ftplib
import io
import socket
import ssl
import subprocess
import tempfile
import unittest
from pathlib import Path

try:
    from elegoobridge.ftp_server import start_ftps
except ImportError:  # pyftpdlib / pyOpenSSL not installed
    start_ftps = None


class ImplicitFTPS(ftplib.FTP_TLS):
    """Bambu printers speak TLS from the first byte on port 990."""

    def connect(self, host="", port=0, timeout=10):
        self.host, self.port = host, port
        self.sock = socket.create_connection((host, port), timeout)
        self.af = self.sock.family
        self.sock = self.context.wrap_socket(self.sock, server_hostname=host)
        self.file = self.sock.makefile("r", encoding=self.encoding)
        self.welcome = self.getresp()
        return self.welcome


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@unittest.skipIf(start_ftps is None, "pyftpdlib or pyOpenSSL is not installed")
class FtpsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        base = Path(cls.tmp.name)
        cls.root = base / "spool"
        cert, key = base / "server.crt", base / "server.key"
        subprocess.run(["openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-days", "1",
                        "-subj", "/CN=test", "-keyout", str(key), "-out", str(cert)],
                       check=True, capture_output=True)
        cls.port = free_port()
        passive = free_port()
        cls.server = start_ftps(root=cls.root, certfile=cert, keyfile=key, password="code",
                                masquerade="127.0.0.1", passive=range(passive, passive + 1), port=cls.port)

    @classmethod
    def tearDownClass(cls):
        cls.server.close_all()
        cls.tmp.cleanup()

    def client(self):
        context = ssl.create_default_context()
        context.check_hostname = False
        context.verify_mode = ssl.CERT_NONE
        ftp = ImplicitFTPS(context=context)
        ftp.connect("127.0.0.1", self.port)
        ftp.login("bblp", "code")
        ftp.prot_p()
        return ftp

    def test_print_file_upload_lands_in_the_spool(self):
        ftp = self.client()
        ftp.storbinary("STOR /cube.gcode.3mf", io.BytesIO(b"PK zip data"))
        self.assertEqual((self.root / "cube.gcode.3mf").read_bytes(), b"PK zip data")
        self.assertIn("cube.gcode.3mf", ftp.nlst("/"))
        self.assertIn("cache", ftp.nlst("/"))
        ftp.quit()

    def test_uploads_are_byte_exact_without_type_i(self):
        # Bambuddy never sends TYPE I; a zip full of CR LF bytes must survive.
        data = bytes(range(256)) * 50 + b"\r\n" * 500
        ftp = self.client()
        conn = ftp.transfercmd("STOR /bytes.3mf")
        conn.sendall(data)
        conn.close()  # no TLS close_notify, as Bambuddy does
        self.assertTrue(ftp.voidresp().startswith("226"))
        self.assertEqual((self.root / "bytes.3mf").read_bytes(), data)
        ftp.sendcmd("TYPE A")
        ftp.storbinary("STOR /ascii.3mf", __import__("io").BytesIO(data))
        self.assertEqual((self.root / "ascii.3mf").read_bytes(), data)
        ftp.quit()

    def test_firmware_upload_is_refused(self):
        ftp = self.client()
        for name in ("/P1S_01.08.02.00.bin", "/cache/firmware.zip"):
            with self.subTest(name=name):
                with self.assertRaisesRegex(ftplib.error_perm, "553"):
                    ftp.storbinary(f"STOR {name}", io.BytesIO(b"firmware"))
                self.assertFalse((self.root / name.lstrip("/")).exists())
        ftp.quit()

    def test_cannot_rename_a_print_file_into_firmware(self):
        ftp = self.client()
        ftp.storbinary("STOR /a.3mf", io.BytesIO(b"x"))
        with self.assertRaisesRegex(ftplib.error_perm, "553"):
            ftp.rename("/a.3mf", "/a.bin")
        ftp.quit()

    def test_wrong_access_code_is_refused(self):
        context = ssl.create_default_context()
        context.check_hostname = False
        context.verify_mode = ssl.CERT_NONE
        ftp = ImplicitFTPS(context=context)
        ftp.connect("127.0.0.1", self.port)
        with self.assertRaises(ftplib.error_perm):
            ftp.login("bblp", "wrong")
        ftp.close()


if __name__ == "__main__":
    unittest.main()
