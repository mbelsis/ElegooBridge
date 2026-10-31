#!/usr/bin/env python3
"""Stamp Centauri Carbon print files so Bambuddy will print them through ElegooBridge.

Usage (from any folder, on the computer where you slice):

    python3 stamp_for_bambuddy.py cube.gcode.3mf          one file
    python3 stamp_for_bambuddy.py a.gcode.3mf b.gcode.3mf  several files
    python3 stamp_for_bambuddy.py ~/Downloads              every sliced file in a folder

Each file gets a stamped copy next to it, ending in .bambuddy.gcode.3mf. Add that
copy to Bambuddy. Your original file is never changed.

Why: Bambuddy only prints a file on the printer model it was sliced for.
ElegooBridge shows the Centauri to Bambuddy as a P1S, but ElegooSlicer labels
the file "Elegoo-CC". The stamp changes only that label:
- Metadata/slice_info.config: printer_model_id -> C12 (P1S)
- Metadata/project_settings.config: printer_model -> Bambu Lab P1S
The G-code is copied unchanged and still says it is for a Centauri Carbon, which
ElegooBridge checks before printing.

This file is self-contained: it needs only Python 3, nothing else from
ElegooBridge, so it can be copied anywhere.
"""
from __future__ import annotations

import json
import re
import sys
import zipfile
from pathlib import Path

MODEL_ID = "C12"
MODEL_NAME = "Bambu Lab P1S"
SUFFIX = ".bambuddy.gcode.3mf"
MARKER = "Metadata/elegoobridge.json"

SLICE_INFO = "Metadata/slice_info.config"
PROJECT_SETTINGS = "Metadata/project_settings.config"
PLATE = re.compile(r"Metadata/plate_\d+\.gcode")
MODEL_ID_PATTERN = re.compile(r'(<metadata key="printer_model_id" value=")[^"]*(")')
MODEL_NAME_PATTERN = re.compile(r'("printer_model"\s*:\s*")[^"]*(")')
PRINTER_LINE = re.compile(rb"^;\s*(printer_model|printer_settings_id)\s*=\s*(.*)$", re.M)


class StampError(Exception):
    pass


def sliced_for(gcode: bytes) -> str:
    """The printer named in the G-code's settings block."""
    found = {key.decode(): value.decode(errors="replace").strip() for key, value in PRINTER_LINE.findall(gcode)}
    return found.get("printer_model") or found.get("printer_settings_id") or ""


def output_path(source: Path) -> Path:
    name = source.name
    for suffix in (".gcode.3mf", ".3mf"):
        if name.lower().endswith(suffix):
            name = name[: -len(suffix)]
            break
    return source.with_name(name + SUFFIX)


def stamp(source: Path, target: Path | None = None) -> Path:
    if source.name.lower().endswith(SUFFIX):
        raise StampError("already stamped")
    target = target or output_path(source)
    if target.exists():
        raise StampError(f"{target.name} already exists")
    try:
        archive = zipfile.ZipFile(source)
    except (zipfile.BadZipFile, OSError) as error:
        raise StampError(f"not a 3MF file ({error})") from None
    with archive:
        names = archive.namelist()
        if MARKER in names:
            raise StampError("already stamped")
        plates = [n for n in names if PLATE.fullmatch(n)]
        if not plates:
            raise StampError('no sliced G-code inside: slice the plate, then use "Export plate sliced file"')
        for plate in plates:
            printer = sliced_for(archive.read(plate))
            if "centauri" not in printer.lower():
                raise StampError(f"{plate} was sliced for {printer or 'an unknown printer'}, not a Centauri Carbon")
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
                out.writestr(MARKER, json.dumps(
                    {"stamped_for": "Bambuddy P1S card (ElegooBridge)", "sliced_for": printer}, indent=2))
            partial.replace(target)
        finally:
            partial.unlink(missing_ok=True)
    return target


def files_to_stamp(arguments: list[str]) -> list[Path]:
    paths = []
    for argument in arguments:
        path = Path(argument).expanduser()
        if path.is_dir():
            paths += sorted(p for p in path.iterdir()
                            if p.name.lower().endswith(".3mf") and not p.name.lower().endswith(SUFFIX))
        else:
            paths.append(path)
    return paths


def main(arguments: list[str]) -> int:
    # --paths-file FILE: also write the stamped files' full paths there, one per
    # line (used by the Mac app to select them in Finder).
    paths_file = None
    if arguments[:1] == ["--paths-file"] and len(arguments) > 1:
        paths_file, arguments = Path(arguments[1]), arguments[2:]
    if not arguments or arguments[0] in ("-h", "--help"):
        print(__doc__.split("\n\nWhy:")[0])
        return 0 if arguments else 2
    paths = files_to_stamp(arguments)
    if not paths:
        print("No .3mf files found.")
        return 1
    failed = 0
    stamped = []
    for path in paths:
        try:
            target = stamp(path)
            stamped.append(target)
            print(f"Stamped: {path.name} -> {target.name}")
            print(f"  saved in {target.parent}")
        except StampError as error:
            print(f"Skipped: {path.name}: {error}")
            failed += 1
    if paths_file:
        paths_file.write_text("".join(f"{p.resolve()}\n" for p in stamped))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
