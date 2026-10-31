"""Turn Centauri Carbon status pushes into Bambu LAN `push_status` reports.

The state codes and their behaviour are documented in docs/FINDINGS.md. Bambuddy
reads the report fields listed in its backend/app/services/bambu_mqtt.py.
"""
from __future__ import annotations

import hashlib
import math
from typing import Any

# PrintInfo.Status
IDLE, HOMING, PAUSING, PAUSED, STOPPING, STOPPED, COMPLETED = 0, 1, 5, 6, 7, 8, 9
PRINTING, ERROR, LEVELLING, HEATING, FILE_LOADED, PREPARING, HOMING_DONE = 13, 14, 15, 16, 18, 20, 21

PAUSE_STATES = {PAUSING, PAUSED}

# CurrentStatus: 0 idle, 1 busy with a job, 9 homing (seen 2026-10-31, about 67 s)
HOMING_DEVICE = 9

# Bambu stg_cur stages (Bambuddy's STAGE_NAMES)
STAGE_NONE = 255
STAGE_PRINTING = 0
STAGE_LEVELLING = 1
STAGE_HEATBED = 2
STAGE_RUNOUT = 6
STAGE_HOMING = 13
STAGE_USER_PAUSE = 16

PREPARE_STAGES = {
    HOMING: STAGE_HOMING,
    HOMING_DONE: STAGE_HOMING,
    LEVELLING: STAGE_LEVELLING,
    PREPARING: STAGE_LEVELLING,
    HEATING: STAGE_HEATBED,
    FILE_LOADED: STAGE_HEATBED,
}

# ErrorStatusReason (Centauri) -> print_error (Bambu, 32-bit) and stage
RUNOUT_REASON = 45
REASONS = {
    RUNOUT_REASON: (0x03008004, STAGE_RUNOUT, "Filament ran out. Please load new filament."),
}


def _num(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def fan_level(percent: Any) -> str:
    """Bambu reports fans as 0-15."""
    return str(round(max(0.0, min(100.0, _num(percent))) * 15 / 100))


def speed_level(percent: Any) -> int:
    """Bambu speed level: 1 silent, 2 standard, 3 sport, 4 ludicrous."""
    pct = _num(percent, 100)
    if pct <= 75:
        return 1
    if pct <= 112:
        return 2
    if pct <= 145:
        return 3
    return 4


def job_number(task_id: str) -> str:
    """A stable numeric job id; Bambuddy treats job ids as numbers."""
    if not task_id:
        return "0"
    return str(int(hashlib.md5(task_id.encode()).hexdigest()[:7], 16))


class Mapper:
    """Holds what a Bambu printer keeps between reports: the finished or failed
    state after a job, the last file name, and the reason for a pause."""

    def __init__(self) -> None:
        self.gcode_state = "IDLE"
        self.last_file = ""
        self.last_task = ""
        self.pause_reason = 0
        self.job_active = False

    def state_for(self, code: int) -> str:
        if code == PRINTING:
            return "RUNNING"
        if code in PAUSE_STATES:
            return "PAUSE"
        if code == COMPLETED:
            return "FINISH"
        if code in (STOPPING, STOPPED, ERROR):
            return "FAILED"
        if code == IDLE:
            # A job that vanished without stopping or finishing lost power.
            if self.job_active:
                return "FAILED"
            return self.gcode_state if self.gcode_state in ("FINISH", "FAILED") else "IDLE"
        return "PREPARE"

    def update(self, status: dict[str, Any]) -> dict[str, Any]:
        info = status.get("PrintInfo") or {}
        code = int(_num(info.get("Status")))
        state = self.state_for(code)
        if code not in PAUSE_STATES:
            self.pause_reason = 0
        self.job_active = state in ("RUNNING", "PAUSE", "PREPARE")
        self.gcode_state = state

        filename = str(info.get("Filename") or "")
        task_id = str(info.get("TaskId") or "")
        if filename:
            self.last_file = filename
        if task_id:
            self.last_task = task_id
        if state == "IDLE":
            self.last_file = self.last_task = ""

        current, total = _num(info.get("CurrentTicks")), _num(info.get("TotalTicks"))
        percent = int(_num(info.get("Progress")))
        remaining = math.ceil(max(0.0, total - current) / 60) if total else 0
        if state == "FINISH":
            percent, remaining = 100, 0

        error, stage = 0, STAGE_NONE
        if state == "PAUSE":
            error, stage = REASONS.get(self.pause_reason, (0, STAGE_USER_PAUSE, ""))[:2]
        elif state == "RUNNING":
            stage = STAGE_PRINTING
        elif state == "PREPARE":
            stage = PREPARE_STAGES.get(code, STAGE_NONE)
        elif HOMING_DEVICE in (status.get("CurrentStatus") or []):
            # Homing from a control panel, outside any job.
            stage = STAGE_HOMING

        fans = status.get("CurrentFanSpeed") or {}
        light = (status.get("LightStatus") or {}).get("SecondLight")
        return {
            # Bit 0x20000000 clear = LAN developer mode, which Bambuddy needs for control.
            "fun": "0",
            "print": {
                "command": "push_status",
                "msg": 0,
                "gcode_state": state,
                "stg_cur": stage,
                "mc_percent": percent,
                "mc_remaining_time": remaining,
                "layer_num": int(_num(info.get("CurrentLayer"))),
                "total_layer_num": int(_num(info.get("TotalLayer"))),
                "gcode_file": self.last_file,
                "subtask_name": self.last_file.rsplit(".gcode", 1)[0],
                "subtask_id": job_number(self.last_task),
                "task_id": job_number(self.last_task),
                "job_id": job_number(self.last_task),
                "print_type": "local" if self.last_file else "",
                "print_error": error,
                "hms": [],
                "nozzle_temper": round(_num(status.get("TempOfNozzle")), 1),
                "nozzle_target_temper": round(_num(status.get("TempTargetNozzle")), 1),
                "bed_temper": round(_num(status.get("TempOfHotbed")), 1),
                "bed_target_temper": round(_num(status.get("TempTargetHotbed")), 1),
                "chamber_temper": round(_num(status.get("TempOfBox")), 1),
                "cooling_fan_speed": fan_level(fans.get("ModelFan")),
                "big_fan1_speed": fan_level(fans.get("AuxiliaryFan")),
                "big_fan2_speed": fan_level(fans.get("BoxFan")),
                "heatbreak_fan_speed": "0",
                "spd_mag": int(_num(info.get("PrintSpeedPct"), 100)),
                "spd_lvl": speed_level(info.get("PrintSpeedPct")),
                "lights_report": [{"node": "chamber_light", "mode": "on" if light == 1 else "off"}],
                "wifi_signal": "-50dBm",
                "nozzle_diameter": "0.4",
            }
        }


def version_report(serial: str, sequence_id: str) -> dict[str, Any]:
    return {
        "info": {
            "command": "get_version",
            "sequence_id": sequence_id,
            "module": [
                {"name": "ota", "sw_ver": "01.04.49.00", "hw_ver": "AP05", "sn": serial, "flag": 0},
                {"name": "mc", "sw_ver": "00.00.00.00", "hw_ver": "MC07", "sn": serial, "flag": 0},
            ],
        }
    }
