"""Label a Centauri-sliced .gcode.3mf so Bambuddy accepts it for the bridge's card.

Bambuddy only sends a file to a printer of the model the file says it was
sliced for. ElegooSlicer writes "Elegoo-CC" / "Elegoo Centauri Carbon"; the
bridge's card is a P1S. This writes a copy with only those two labels changed:
- Metadata/slice_info.config: printer_model_id -> C12
- Metadata/project_settings.config: printer_model -> Bambu Lab P1S

The G-code is copied unchanged and still names the Centauri, which the bridge
checks before printing. Standard library only, so it runs on any computer.
"""
from __future__ import annotations

import json
import re
import zipfile
from pathlib import Path

from elegoobridge.jobs import CENTAURI, sliced_for

MODEL_ID = "C12"
MODEL_NAME = "Bambu Lab P1S"
SUFFIX = ".bambuddy.gcode.3mf"

SLICE_INFO = "Metadata/slice_info.config"
PROJECT_SETTINGS = "Metadata/project_settings.config"
MODEL_ID_PATTERN = re.compile(r'(<metadata key="printer_model_id" value=")[^"]*(")')
MODEL_NAME_PATTERN = re.compile(r'("printer_model"\s*:\s*")[^"]*(")')


class StampError(Exception):
    pass


def output_path(source: Path) -> Path:
    name = source.name
    for suffix in (".gcode.3mf", ".3mf"):
        if name.lower().endswith(suffix):
            name = name[: -len(suffix)]
            break
    return source.with_name(name + SUFFIX)


def stamp(source: Path, target: Path | None = None) -> Path:
    target = target or output_path(source)
    if target.exists():
        raise StampError(f"{target.name} already exists")
    try:
        archive = zipfile.ZipFile(source)
    except (zipfile.BadZipFile, OSError) as error:
        raise StampError(f"{source.name} is not a 3MF file: {error}") from None
    with archive:
        names = archive.namelist()
        plates = [n for n in names if re.fullmatch(r"Metadata/plate_\d+\.gcode", n)]
        if not plates:
            raise StampError("the file contains no sliced G-code: slice the plate and use "
                             "\"Export plate sliced file\"")
        for plate in plates:
            printer = sliced_for(archive.read(plate))
            if not CENTAURI.search(printer):
                raise StampError(f"{plate} was sliced for {printer or 'an unknown printer'}, not a Centauri Carbon")
        printer = sliced_for(archive.read(plates[0]))
        partial = target.with_name(target.name + ".part")
        try:
            with zipfile.ZipFile(partial, "w") as out:
                for info in archive.infolist():
                    data = archive.read(info)
                    if info.filename == SLICE_INFO:
                        text = MODEL_ID_PATTERN.sub(rf"\g<1>{MODEL_ID}\g<2>", data.decode("utf-8"))
                        data = text.encode("utf-8")
                    elif info.filename == PROJECT_SETTINGS:
                        text = MODEL_NAME_PATTERN.sub(rf"\g<1>{MODEL_NAME}\g<2>", data.decode("utf-8"), count=1)
                        data = text.encode("utf-8")
                    # A fresh ZipInfo: writing one updates its offsets, which would
                    # break later reads from the source archive.
                    copy = zipfile.ZipInfo(info.filename, info.date_time)
                    copy.compress_type, copy.external_attr = info.compress_type, info.external_attr
                    out.writestr(copy, data)
                out.writestr("Metadata/elegoobridge.json", json.dumps(
                    {"stamped_for": "Bambuddy P1S card (ElegooBridge)", "sliced_for": printer}, indent=2))
            partial.replace(target)
        finally:
            partial.unlink(missing_ok=True)
    return target
