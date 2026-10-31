"""Turn a print file Bambuddy uploaded into G-code the Centauri can print.

Bambuddy uploads a .gcode.3mf over FTPS, then sends `project_file` with
`url: "ftp://<name>"` and `param: "Metadata/plate_<n>.gcode"`. The Centauri only
prints plain .gcode, so the plate's G-code is taken out of the archive. Only
G-code sliced for a Centauri Carbon is accepted.
"""
from __future__ import annotations

import re
import zipfile
from pathlib import Path, PurePosixPath

# What Bambuddy may store on the printer. Anything else, such as a Bambu
# firmware file, is refused at upload and never reaches the Centauri.
PRINT_SUFFIXES = (".gcode.3mf", ".3mf", ".gcode")
MAX_GCODE = 512 * 1024 * 1024

CENTAURI = re.compile(r"centauri", re.I)
PRINTER_LINE = re.compile(rb"^;\s*(printer_model|printer_settings_id)\s*=\s*(.*)$", re.M)


# Bambu print_error codes Bambuddy shows when the bridge refuses a print
WRONG_PRINTER = 0x05004037   # "Your sliced file is not compatible with current printer model"
INVALID_FILE = 0x05004046    # "The print has stopped because the 3MF file is invalid"
FILE_PROBLEM = 0x0500400B    # "There was a problem downloading a file"


class JobError(Exception):
    def __init__(self, message: str, code: int = FILE_PROBLEM) -> None:
        super().__init__(message)
        self.code = code


def is_print_file(name: str) -> bool:
    return name.lower().endswith(PRINT_SUFFIXES)


def file_name(url: str) -> str:
    """The bare file name in a project_file url: ftp://x, file:///sdcard/x, /cache/x."""
    raw = (url or "").replace("\\", "/")
    raw = re.sub(r"^[a-z]+://", "", raw, flags=re.I)
    name = PurePosixPath(raw).name
    if not name or name in (".", ".."):
        raise JobError(f"no file name in {url!r}")
    return name


def find_upload(root: Path, url: str) -> Path:
    name = file_name(url)
    for candidate in (root / name, root / "cache" / name):
        if candidate.is_file():
            return candidate
    raise JobError(f"{name} was not uploaded to the bridge")


def _plate_member(names: list[str], wanted: str) -> str:
    wanted = (wanted or "").replace("\\", "/").lstrip("/")
    if wanted in names:
        return wanted
    plates = sorted(n for n in names if re.fullmatch(r"Metadata/plate_\d+\.gcode", n))
    if wanted and not plates:
        raise JobError(f"{wanted} is not in the file", INVALID_FILE)
    if not plates:
        raise JobError("the file contains no sliced G-code; slice it before printing", INVALID_FILE)
    if wanted:
        raise JobError(f"{wanted} is not in the file (it has {', '.join(plates)})", INVALID_FILE)
    return plates[0]


def sliced_for(gcode: bytes) -> str:
    """The printer named in the slicer's settings block, if any."""
    found = {key.decode(): value.decode(errors="replace").strip() for key, value in PRINTER_LINE.findall(gcode)}
    return found.get("printer_model") or found.get("printer_settings_id") or ""


def extract_gcode(path: Path, plate: str = "") -> bytes:
    """The G-code to print, refusing anything not sliced for a Centauri Carbon."""
    if path.name.lower().endswith(".gcode") and not path.name.lower().endswith(".gcode.3mf"):
        if path.stat().st_size > MAX_GCODE:
            raise JobError("the G-code file is too large", INVALID_FILE)
        data = path.read_bytes()
    else:
        try:
            with zipfile.ZipFile(path) as archive:
                member = _plate_member(archive.namelist(), plate)
                if archive.getinfo(member).file_size > MAX_GCODE:
                    raise JobError("the plate's G-code is too large", INVALID_FILE)
                data = archive.read(member)
        except zipfile.BadZipFile:
            raise JobError(f"{path.name} is not a valid 3MF file", INVALID_FILE) from None
    printer = sliced_for(data)
    if not CENTAURI.search(printer):
        raise JobError(
            f"this G-code was sliced for {printer or 'an unknown printer'}, not a Centauri Carbon; "
            "slice it with a Centauri Carbon profile",
            WRONG_PRINTER,
        )
    return data


def printer_file_name(url: str, subtask: str = "") -> str:
    """The name the G-code gets on the Centauri."""
    base = subtask or file_name(url)
    for suffix in (".gcode.3mf", ".3mf", ".gcode"):
        if base.lower().endswith(suffix):
            base = base[: -len(suffix)]
    base = re.sub(r"[^\w\-. ()]+", "_", base).strip(" .") or "bambuddy"
    return f"{base[:100]}.gcode"
