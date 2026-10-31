"""Connect a Centauri Carbon (SDCP) to an MQTT broker as an emulated Bambu printer.

Bambuddy connects to the broker as if it were the printer's. The bridge publishes
status on device/<serial>/report and takes commands from device/<serial>/request.
While the Centauri is unreachable nothing is published, so Bambuddy shows the
printer offline after its usual 60 s.
"""
from __future__ import annotations

import json
import logging
import queue
import ssl
import threading
import time
from typing import Any

import paho.mqtt.client as mqtt

from elegoobridge import jobs, sdcp, upload
from elegoobridge.commands import Action, translate
from elegoobridge.config import Config
from elegoobridge.mapper import PAUSE_STATES, REASONS, Mapper, version_report

log = logging.getLogger("elegoobridge")

HEARTBEAT = 5.0


def _sequence() -> str:
    return str(int(time.time() * 1000) % 1_000_000_000)


class Bridge:
    def __init__(self, cfg: Config) -> None:
        self.cfg = cfg
        self.mapper = Mapper()
        self.report: dict[str, Any] | None = None
        self._last_code: int | None = None
        self._lock = threading.Lock()
        self._jobs: queue.Queue = queue.Queue()
        self.printer = sdcp.SdcpClient(
            cfg.printer_host, cfg.mainboard_id, on_status=self._on_status, on_connection=self._on_connection
        )
        self.mqtt = mqtt.Client(
            mqtt.CallbackAPIVersion.VERSION2, client_id=f"elegoobridge-{cfg.serial}", protocol=mqtt.MQTTv311
        )
        self.mqtt.username_pw_set(cfg.mqtt_user, cfg.mqtt_password)
        if cfg.mqtt_tls:
            context = ssl.create_default_context()
            context.check_hostname = False
            context.verify_mode = ssl.CERT_NONE
            self.mqtt.tls_set_context(context)
        self.mqtt.on_connect = self._on_mqtt_connect
        self.mqtt.on_message = self._on_mqtt_message
        self.report_topic = f"device/{cfg.serial}/report"
        self.request_topic = f"device/{cfg.serial}/request"

    # Printer side (called on the SDCP thread: never block here)

    def _on_connection(self, connected: bool) -> None:
        if connected:
            self._last_code = None

    def _on_status(self, status: dict[str, Any]) -> None:
        code = int((status.get("PrintInfo") or {}).get("Status") or 0)
        entered_pause = code in PAUSE_STATES and self._last_code not in PAUSE_STATES
        self._last_code = code
        self._publish_status(status)
        if entered_pause:
            task_id = str((status.get("PrintInfo") or {}).get("TaskId") or "")
            self._jobs.put(lambda: self._read_pause_reason(task_id))

    def _read_pause_reason(self, task_id: str) -> None:
        # The reason only exists in the history while the job is paused, and
        # may be written a moment after the pause starts.
        entry = None
        for attempt in range(3):
            if attempt:
                time.sleep(4)
            if self._last_code not in PAUSE_STATES:
                return
            try:
                entry = self.printer.history_entry(task_id) if task_id else None
            except sdcp.SdcpError as error:
                log.warning("could not read the pause reason: %s", error)
            if entry:
                break
        reason = int((entry or {}).get("ErrorStatusReason") or 0)
        if reason:
            text = REASONS.get(reason, (0, 0, "unknown reason"))[2]
            log.warning("print paused by the printer: reason %s (%s)", reason, text)
        else:
            log.info("print paused (no error reason)")
        with self._lock:
            self.mapper.pause_reason = reason
        self._publish_status(self.printer.status)

    def _publish_status(self, status: dict[str, Any]) -> None:
        with self._lock:
            self.report = self.mapper.update(status)
            self.report["print"]["sequence_id"] = _sequence()
            body = json.dumps(self.report, separators=(",", ":"))
        self.mqtt.publish(self.report_topic, body, qos=0)

    # Bambuddy side

    def _on_mqtt_connect(self, client, userdata, flags, reason_code, properties=None) -> None:
        log.info("MQTT connected (%s), serial %s", reason_code, self.cfg.serial)
        client.subscribe(self.request_topic, qos=1)

    def _on_mqtt_message(self, client, userdata, message) -> None:
        try:
            payload = json.loads(message.payload.decode("utf-8") or "{}")
        except (UnicodeDecodeError, json.JSONDecodeError):
            log.warning("ignored a malformed command")
            return
        self._jobs.put(lambda: self._execute(translate(payload)))

    def _execute(self, action: Action) -> None:
        for item in action.unsupported:
            log.info("not supported on the Centauri, ignored: %s", item)
        if not self.printer.connected:
            if action.sdcp or action.light is not None:
                log.warning("printer offline: command not sent")
            return
        busy = any(code != 0 for code in self.printer.status.get("CurrentStatus") or [])
        for cmd, data in action.sdcp:
            if cmd in (sdcp.MOVE_AXIS, sdcp.HOME_AXES) and busy:
                # The printer's own control panel never moves a busy printer either.
                log.warning("printer busy: move or home not sent")
                continue
            try:
                self.printer.request(cmd, data)
                log.info("sent command %s %s", cmd, json.dumps(data))
            except sdcp.SdcpError as error:
                log.warning("command %s failed: %s", cmd, error)
        if action.start is not None:
            self._start_job(action.start)
        if action.light is not None:
            self._set_light(action.light)
        if action.clear_error:
            with self._lock:
                self.mapper.pause_reason = 0
                self.mapper.job_error = 0
        if action.reply:
            self.mqtt.publish(self.report_topic, json.dumps(action.reply), qos=0)
        if action.version:
            self.mqtt.publish(self.report_topic, json.dumps(version_report(self.cfg.serial, _sequence())), qos=0)
        if action.push_status and self.printer.status:
            self._publish_status(self.printer.status)

    def _start_job(self, block: dict[str, Any]) -> None:
        """Print a file Bambuddy uploaded: extract the plate, upload it, start it."""
        command = str(block.get("command") or "project_file")
        result, reason = "failed", ""
        try:
            if any(code != 0 for code in self.printer.status.get("CurrentStatus") or []):
                raise jobs.JobError("the printer is busy")
            url = str(block.get("url") or block.get("param") or "")
            plate = str(block.get("param") or "") if command == "project_file" else ""
            source = jobs.find_upload(self.cfg.ftp_root, url)
            gcode = jobs.extract_gcode(source, plate)
            name = jobs.printer_file_name(url, str(block.get("subtask_name") or ""))
            log.info("uploading %s (%s bytes) from %s to the printer", name, len(gcode), source.name)
            upload.upload(self.cfg.printer_host, name, gcode)
            self._wait_for_file(name)
            self.printer.request(sdcp.START, {
                "Filename": name, "StartLayer": 0, "Calibration_switch": 1, "PrintPlatformType": 0,
                "Tlp_Switch": 0, "slot_map": [], "path_prefix": "/local",
            })
            log.info("print started: %s", name)
            result = "success"
        except (jobs.JobError, upload.UploadError, sdcp.SdcpError, OSError) as error:
            reason = str(error)
            log.warning("print not started: %s", reason)
            if reason != "the printer is busy":
                # Show it on Bambuddy's card at once, with a Bambu error code.
                with self._lock:
                    self.mapper.refuse_job(getattr(error, "code", jobs.FILE_PROBLEM))
                if self.printer.status:
                    self._publish_status(self.printer.status)
        reply = {"print": {"command": command, "sequence_id": str(block.get("sequence_id") or "0"), "result": result}}
        if reason:
            reply["print"]["reason"] = reason
        self.mqtt.publish(self.report_topic, json.dumps(reply), qos=0)

    def _wait_for_file(self, name: str, timeout: float = 15.0) -> None:
        # A new upload appears in the printer's file list a moment later.
        end = time.time() + timeout
        while time.time() < end:
            files = self.printer.request(sdcp.FILE_LIST, {"Url": "/local"}).get("FileList") or []
            if any(str(f.get("name", "")).endswith("/" + name) for f in files):
                return
            time.sleep(1)
        raise jobs.JobError(f"{name} did not appear on the printer after uploading")

    def _set_light(self, on: bool) -> None:
        # On V1.4.49 the light toggles on every command. 0 turns it on from off,
        # 1 turns it off from on, so send only when a change is needed.
        current = (self.printer.status.get("LightStatus") or {}).get("SecondLight")
        if current == (1 if on else 0):
            return
        try:
            self.printer.request(sdcp.SET_PARAMS, {"LightStatus": {"SecondLight": 0 if on else 1}})
            log.info("light %s", "on" if on else "off")
        except sdcp.SdcpError as error:
            log.warning("light command failed: %s", error)

    # Running

    def _worker(self) -> None:
        while True:
            job = self._jobs.get()
            try:
                job()
            except Exception:
                log.exception("command failed")

    def run_forever(self) -> None:
        log.info(
            "bridging Centauri %s to MQTT %s:%s as %s",
            self.cfg.printer_host, self.cfg.mqtt_host, self.cfg.mqtt_port, self.cfg.serial,
        )
        threading.Thread(target=self._worker, name="commands", daemon=True).start()
        if self.cfg.camera_enable:
            from elegoobridge.camera import CameraRelay, ChamberImageServer

            ChamberImageServer(
                CameraRelay(self.cfg.printer_host), self.cfg.ftp_cert, self.cfg.ftp_key,
                self.cfg.mqtt_password, port=self.cfg.camera_port,
            ).start()
        if self.cfg.ftp_enable:
            from elegoobridge.ftp_server import start_ftps

            start_ftps(
                root=self.cfg.ftp_root, certfile=self.cfg.ftp_cert, keyfile=self.cfg.ftp_key,
                password=self.cfg.mqtt_password, masquerade=self.cfg.ftp_passive_ip,
                passive=range(self.cfg.ftp_passive_start, self.cfg.ftp_passive_end + 1), port=self.cfg.ftp_port,
            )
        self.mqtt.connect_async(self.cfg.mqtt_host, self.cfg.mqtt_port, keepalive=30)
        self.mqtt.loop_start()
        self.printer.start()
        try:
            while True:
                time.sleep(HEARTBEAT)
                # Idle printers push rarely; keep Bambuddy from marking it stale.
                if self.printer.connected and self.printer.status:
                    self._publish_status(self.printer.status)
        finally:
            self.printer.close()
            self.mqtt.loop_stop()
