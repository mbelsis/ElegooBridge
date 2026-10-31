"""Translate Bambuddy's MQTT commands into SDCP commands.

`translate` is pure: it returns what to do, and the bridge does it. Commands the
Centauri can't do are reported as unsupported instead of being guessed at.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from elegoobridge import sdcp

MAX_NOZZLE = 300
MAX_BED = 110

# Bambu speed levels -> Centauri PrintSpeedPct
SPEED_LEVELS = {1: 50, 2: 100, 3: 125, 4: 166}

# M106 P<n> fan index -> Centauri fan name
FANS = {1: "ModelFan", 2: "AuxiliaryFan", 3: "BoxFan"}


@dataclass
class Action:
    sdcp: list[tuple[int, dict[str, Any]]] = field(default_factory=list)
    light: bool | None = None          # wanted chamber light state
    clear_error: bool = False
    push_status: bool = False
    version: bool = False
    reply: dict[str, Any] | None = None
    unsupported: list[str] = field(default_factory=list)


def parse_command(payload: dict[str, Any]) -> tuple[str, str, dict[str, Any]]:
    for family in ("print", "pushing", "info", "system", "camera"):
        block = payload.get(family)
        if isinstance(block, dict) and block.get("command"):
            return family, str(block["command"]), block
    return "", "", {}


def _param(line: str, letter: str) -> float | None:
    match = re.search(rf"(?:^|\s){letter}(-?\d+(?:\.\d+)?)", line, re.I)
    return float(match.group(1)) if match else None


def translate_gcode(text: str) -> tuple[list[tuple[int, dict[str, Any]]], list[str]]:
    """Bambuddy sends temperatures, fans and jogs as G-code lines: M104, M140,
    M106, and `G91 / G1 X10 / G90` or `G28`. Only relative moves are passed on,
    because the Centauri moves by steps, not to positions."""
    commands: list[tuple[int, dict[str, Any]]] = []
    unsupported: list[str] = []
    fans: dict[str, int] = {}
    relative = False
    for raw in text.replace("\\n", "\n").splitlines():
        line = raw.split(";", 1)[0].strip()
        if not line:
            continue
        word = line.split()[0].upper()
        value = _param(line, "S")
        if word in ("M104", "M109") and value is not None and 0 <= value <= MAX_NOZZLE:
            commands.append((sdcp.SET_PARAMS, {"TempTargetNozzle": int(value)}))
        elif word in ("M140", "M190") and value is not None and 0 <= value <= MAX_BED:
            commands.append((sdcp.SET_PARAMS, {"TempTargetHotbed": int(value)}))
        elif word == "M106" and value is not None:
            index = int(_param(line, "P") or 1)
            if index in FANS:
                fans[FANS[index]] = round(max(0.0, min(255.0, value)) * 100 / 255)
            else:
                unsupported.append(line)
        elif word == "M107" and int(_param(line, "P") or 1) in FANS:
            fans[FANS[int(_param(line, "P") or 1)]] = 0
        elif word in ("G90", "G91"):
            relative = word == "G91"
        elif word == "G28":
            commands.append((sdcp.HOME_AXES, {"Axis": "XYZ"}))
        elif word in ("G0", "G1") and relative and _param(line, "E") is None:
            moves = [(axis, _param(line, axis)) for axis in ("X", "Y", "Z")]
            moves = [(axis, step) for axis, step in moves if step]
            if moves and all(abs(step) <= sdcp.MAX_STEP for _, step in moves):
                commands += [(sdcp.MOVE_AXIS, {"Axis": axis, "Step": step}) for axis, step in moves]
            else:
                unsupported.append(line)
        else:
            unsupported.append(line)
    if fans:
        commands.append((sdcp.SET_PARAMS, {"TargetFanSpeed": fans}))
    return commands, unsupported


def translate(payload: dict[str, Any]) -> Action:
    family, command, block = parse_command(payload)
    sequence = str(block.get("sequence_id") or "0")
    action = Action()
    if family == "pushing" and command == "pushall":
        action.push_status = True
    elif family == "info" and command == "get_version":
        action.version = True
    elif family == "print" and command in ("pause", "resume", "stop"):
        action.sdcp.append(({"pause": sdcp.PAUSE, "resume": sdcp.RESUME, "stop": sdcp.STOP}[command], {}))
        action.push_status = True
    elif family == "print" and command == "gcode_line":
        action.sdcp, action.unsupported = translate_gcode(str(block.get("param") or ""))
    elif family == "print" and command == "print_speed":
        level = int(str(block.get("param") or "2").strip() or 2)
        if level in SPEED_LEVELS:
            action.sdcp.append((sdcp.SET_PARAMS, {"PrintSpeedPct": SPEED_LEVELS[level]}))
        else:
            action.unsupported.append(f"print_speed {level}")
    elif family == "print" and command == "clean_print_error":
        action.clear_error = True
        action.push_status = True
    elif family == "system" and command == "ledctrl":
        if block.get("led_node") == "chamber_light":
            action.light = block.get("led_mode") == "on"
    else:
        action.unsupported.append(f"{family}.{command}")
    if family == "print" and command not in ("pause", "resume", "stop"):
        result = "failed" if action.unsupported and not action.sdcp else "success"
        action.reply = {"print": {"command": command, "sequence_id": sequence, "result": result}}
    return action
