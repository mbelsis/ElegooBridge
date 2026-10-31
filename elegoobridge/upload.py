"""Upload G-code to the Centauri over HTTP, as the printer's web page does.

POST http://HOST/uploadFile/upload, multipart form data, one request per 1 MiB
chunk, each carrying the whole file's MD5. Tested on firmware V1.4.49.
"""
from __future__ import annotations

import hashlib
import json
import uuid
import urllib.request

CHUNK = 1024 * 1024


class UploadError(Exception):
    pass


def _multipart(fields: dict[str, str], name: str, chunk: bytes) -> tuple[bytes, str]:
    boundary = uuid.uuid4().hex
    parts = []
    for key, value in fields.items():
        parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="{key}"\r\n\r\n{value}\r\n'.encode())
    parts.append(
        f'--{boundary}\r\nContent-Disposition: form-data; name="File"; filename="{name}"\r\n'
        f"Content-Type: application/octet-stream\r\n\r\n".encode()
    )
    parts.append(chunk)
    parts.append(f"\r\n--{boundary}--\r\n".encode())
    return b"".join(parts), f"multipart/form-data; boundary={boundary}"


def upload(host: str, name: str, data: bytes, port: int = 80, timeout: float = 60.0) -> None:
    md5 = hashlib.md5(data).hexdigest()  # the printer's protocol requires MD5
    upload_id = uuid.uuid4().hex
    url = f"http://{host}:{port}/uploadFile/upload"
    for offset in range(0, max(len(data), 1), CHUNK):
        body, content_type = _multipart(
            {"Check": "1", "S-File-MD5": md5, "Offset": str(offset), "Uuid": upload_id, "TotalSize": str(len(data))},
            name,
            data[offset:offset + CHUNK],
        )
        request = urllib.request.Request(url, data=body, method="POST", headers={"Content-Type": content_type})
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                reply = json.loads(response.read() or b"{}")
        except (OSError, ValueError) as error:
            raise UploadError(f"upload to the printer failed at byte {offset}: {error}") from None
        if reply.get("code") != "000000":
            raise UploadError(f"the printer refused the upload at byte {offset}: {reply}")
