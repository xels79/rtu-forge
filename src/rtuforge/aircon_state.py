"""Runtime state displayed by the Hisense air-conditioner console."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


MODE_NAMES = {
    0: "ВЫКЛЮЧЕН",
    1: "НАГРЕВ",
    2: "ОХЛАЖДЕНИЕ",
    3: "АВТО",
    4: "ОСУШЕНИЕ",
    5: "ВЕНТИЛЯЦИЯ",
}
THERMOSTAT_NAMES = {0: "ПРОСТАИВАЕТ", 1: "НАГРЕВАЕТ", 2: "ОХЛАЖДАЕТ"}
FAN_NAMES = {0: "АВТО", 1: "СКОРОСТЬ 1", 2: "СКОРОСТЬ 2", 3: "СКОРОСТЬ 3"}


@dataclass
class AirconState:
    """Latest confirmed values. ``fresh`` is false after every failed poll."""

    gateway_online: bool = False
    aircon_online: bool = False
    fresh: bool = False
    power: bool | None = None
    mode: int | None = None
    active_mode: int | None = None
    room_temperature_c: float | None = None
    target_temperature_c: float | None = None
    thermostat: int | None = None
    fan: int | None = None
    exchanger_temperature_c: float | None = None
    temperature_placeholder_count: int = 0
    temperature_telemetry_note: str | None = None
    humidity_percent: float | None = None
    humidity_updated_at: datetime | None = None
    humidity_error: str | None = None
    last_response_at: datetime | None = None
    timeout_count: int = 0
    crc_error_count: int = 0
    exchange_error_count: int = 0
    last_error: str | None = None

    def mark_offline(self, message: str, *, timeout: bool = False, crc: bool = False) -> None:
        self.gateway_online = False
        self.aircon_online = False
        self.fresh = False
        self.last_error = message
        self.exchange_error_count += 1
        if timeout:
            self.timeout_count += 1
        if crc:
            self.crc_error_count += 1

    def clear_measurements(self) -> None:
        """Prevent old values from being presented as current after link loss."""
        self.power = None
        self.mode = None
        self.active_mode = None
        self.room_temperature_c = None
        self.target_temperature_c = None
        self.thermostat = None
        self.fan = None
        self.exchanger_temperature_c = None
        self.temperature_placeholder_count = 0
        self.temperature_telemetry_note = None
