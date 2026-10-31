"""The FTPS server Bambuddy uploads print files to, as on a Bambu printer.

Implicit TLS on port 990, user bblp with the access code, files kept in a spool
folder. Only print files can be stored: a firmware file or anything else is
refused, so nothing but sliced G-code can ever reach the Centauri.
"""
from __future__ import annotations

import logging
import threading
import time
from pathlib import Path

from OpenSSL import SSL
from pyftpdlib.authorizers import DummyAuthorizer
from pyftpdlib.handlers import FTPHandler, TLS_FTPHandler
from pyftpdlib.servers import FTPServer

from elegoobridge.jobs import is_print_file

log = logging.getLogger("elegoobridge.ftp")

KEEP_DAYS = 30
FOLDERS = ("cache", "model", "timelapse", "data", "data/Metadata")


class PrintFilesOnly(TLS_FTPHandler):
    """Implicit FTPS (TLS from the first byte) that only stores print files."""

    def handle(self) -> None:  # type: ignore[override]
        self.secure_connection(self.ssl_context)
        FTPHandler.handle(self)
        self._current_type = "i"

    def ftp_TYPE(self, line):
        # Always binary, like a Bambu printer (vsftpd). Bambuddy uploads without
        # TYPE I, and ASCII mode rewrites line endings, corrupting 3MF files.
        self._current_type = "i"
        self.respond("200 Type set to: Binary.")

    def _refuse(self, path: str) -> bool:
        if is_print_file(path):
            return False
        log.warning("refused upload of %s: only .gcode.3mf, .3mf and .gcode files are accepted", Path(path).name)
        self.respond("553 Only print files (.gcode.3mf, .3mf, .gcode) are accepted.")
        # Drop the data connection the client opened for this upload, so the
        # next command starts clean.
        self._shutdown_connecting_dtp()
        if self.data_channel is not None:
            self.data_channel.close()
            self.data_channel = None
        return True

    def ftp_STOR(self, file, mode="w"):
        if not self._refuse(file):
            return super().ftp_STOR(file, mode)

    def ftp_APPE(self, file):
        if not self._refuse(file):
            return super().ftp_APPE(file)

    def ftp_STOU(self, line):
        self.respond("553 Uploads need a file name.")

    def ftp_RNTO(self, path):
        if not self._refuse(path):
            return super().ftp_RNTO(path)

    def on_file_received(self, file: str) -> None:
        log.info("received %s (%s bytes)", Path(file).name, Path(file).stat().st_size)


def clean_old_files(root: Path, days: int = KEEP_DAYS) -> None:
    limit = time.time() - days * 86400
    for path in root.rglob("*"):
        if path.is_file() and path.stat().st_mtime < limit:
            path.unlink(missing_ok=True)


def start_ftps(
    *, root: Path, certfile: Path, keyfile: Path, password: str, masquerade: str,
    passive: range, port: int = 990, user: str = "bblp",
) -> FTPServer:
    root.mkdir(parents=True, exist_ok=True)
    for folder in FOLDERS:
        (root / folder).mkdir(parents=True, exist_ok=True)
    clean_old_files(root)

    authorizer = DummyAuthorizer()
    authorizer.add_user(user, password, str(root), perm="elradfmwMT")
    context = SSL.Context(SSL.TLS_SERVER_METHOD)
    context.use_certificate_file(str(certfile))
    context.use_privatekey_file(str(keyfile))
    # Like a Bambu printer: TLS 1.2 with a session cache. Bambuddy's P1S client
    # reuses the control connection's TLS session on every data connection,
    # and with TLS 1.3 or no cache the transfer hangs.
    context.set_min_proto_version(SSL.TLS1_2_VERSION)
    context.set_max_proto_version(SSL.TLS1_2_VERSION)
    context.set_session_cache_mode(SSL.SESS_CACHE_SERVER)
    context.set_session_id(b"elegoobridge")
    # Bambuddy ends an upload by closing the data connection without a TLS
    # close_notify. OpenSSL 3 reports that as an error, so the transfer never
    # completed and Bambuddy waited forever; treat it as a normal close, as
    # Bambu printers do.
    context.set_options(getattr(SSL, "OP_IGNORE_UNEXPECTED_EOF", 1 << 7))

    handler = PrintFilesOnly
    handler.authorizer = authorizer
    handler.certfile, handler.keyfile = str(certfile), str(keyfile)
    handler.ssl_context = context
    handler.tls_control_required = True
    # Bambu clients ask for a protected data channel but some send it in clear.
    handler.tls_data_required = False
    handler.masquerade_address = masquerade or None
    handler.passive_ports = passive
    handler.banner = "ElegooBridge FTPS"

    server = FTPServer(("0.0.0.0", port), handler)
    threading.Thread(target=server.serve_forever, name="ftps", daemon=True).start()
    log.info("FTPS on port %s, files in %s, passive ports %s-%s", port, root, passive.start, passive.stop - 1)
    return server
