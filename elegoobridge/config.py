from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


class ConfigError(Exception):
    pass


def _env(name: str, default: str | None = None) -> str:
    value = (os.environ.get(name) or "").strip()
    if value:
        return value
    if default is None:
        raise ConfigError(f"{name} must be set")
    return default


@dataclass(frozen=True)
class Config:
    printer_host: str
    mainboard_id: str
    serial: str
    mqtt_host: str
    mqtt_port: int
    mqtt_user: str
    mqtt_password: str
    mqtt_tls: bool
    ftp_enable: bool = False
    ftp_root: Path = Path("/data/ftp")
    ftp_port: int = 990
    ftp_passive_ip: str = ""
    ftp_passive_start: int = 50000
    ftp_passive_end: int = 50009
    ftp_cert: Path = Path("/certs/server.crt")
    ftp_key: Path = Path("/certs/server.key")
    camera_enable: bool = False
    camera_port: int = 6000

    @classmethod
    def from_env(cls) -> Config:
        return cls(
            printer_host=_env("PRINTER_HOST"),
            mainboard_id=_env("PRINTER_MAINBOARD_ID"),
            serial=_env("BAMBU_SERIAL", "0390000ELEGOO01"),
            mqtt_host=_env("MQTT_HOST", "mosquitto"),
            mqtt_port=int(_env("MQTT_PORT", "1883")),
            mqtt_user=_env("MQTT_USER", "bblp"),
            mqtt_password=_env("MQTT_PASSWORD"),
            mqtt_tls=_env("MQTT_TLS", "0").lower() in ("1", "true", "yes"),
            ftp_enable=_env("FTP_ENABLE", "1").lower() in ("1", "true", "yes"),
            ftp_root=Path(_env("FTP_ROOT", "/data/ftp")),
            ftp_port=int(_env("FTP_PORT", "990")),
            ftp_passive_ip=_env("FTP_PASSIVE_IP", ""),
            ftp_passive_start=int(_env("FTP_PASSIVE_START", "50000")),
            ftp_passive_end=int(_env("FTP_PASSIVE_END", "50009")),
            ftp_cert=Path(_env("FTP_CERT", "/certs/server.crt")),
            ftp_key=Path(_env("FTP_KEY", "/certs/server.key")),
            camera_enable=_env("CAMERA_ENABLE", "1").lower() in ("1", "true", "yes"),
            camera_port=int(_env("CAMERA_PORT", "6000")),
        )
