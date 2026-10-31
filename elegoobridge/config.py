from __future__ import annotations

import os
from dataclasses import dataclass


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
        )
