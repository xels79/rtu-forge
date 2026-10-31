"""Separate persistent configuration for the air-conditioner application."""

from __future__ import annotations

import configparser
import math
from dataclasses import dataclass, fields, replace
from pathlib import Path


@dataclass(frozen=True)
class AirconSettings:
    port: str = ""
    baudrate: int = 9600
    bytesize: int = 8
    parity: str = "N"
    stopbits: float = 2.0
    timeout_ms: int = 1000
    slave_id: int = 1
    poll_interval_ms: int = 2000
    auto_connect: bool = False
    humidity_enabled: bool = False
    humidity_slave_id: int = 2
    humidity_register_type: str = "holding"
    humidity_address: int = 0
    humidity_scale: float = 0.1
    humidity_stale_ms: int = 10_000
    diagnostic_log: str = "aircon.log"


SECTIONS = {
    "port": "connection", "baudrate": "connection", "bytesize": "connection",
    "parity": "connection", "stopbits": "connection", "timeout_ms": "connection",
    "slave_id": "modbus", "poll_interval_ms": "runtime", "auto_connect": "runtime",
    "humidity_enabled": "humidity", "humidity_slave_id": "humidity",
    "humidity_register_type": "humidity", "humidity_address": "humidity",
    "humidity_scale": "humidity", "humidity_stale_ms": "humidity",
    "diagnostic_log": "diagnostics",
}


def _bool(value: str) -> bool:
    normalized = value.strip().casefold()
    if normalized in {"1", "true", "yes", "on", "да", "вкл"}:
        return True
    if normalized in {"0", "false", "no", "off", "нет", "выкл"}:
        return False
    raise ValueError("ожидалось логическое значение: true/false")


def _convert(current: object, value: str) -> object:
    if isinstance(current, bool):
        return _bool(value)
    if isinstance(current, int):
        return int(value, 10)
    if isinstance(current, float):
        return float(value.replace(",", "."))
    return value.strip()


def validate_aircon_settings(settings: AirconSettings) -> None:
    if settings.baudrate <= 0 or settings.bytesize not in {5, 6, 7, 8}:
        raise ValueError("скорость должна быть положительной, биты данных — 5..8")
    if settings.parity.upper() not in {"N", "E", "O", "M", "S"}:
        raise ValueError("чётность должна быть N, E, O, M или S")
    if settings.stopbits not in {1.0, 1.5, 2.0}:
        raise ValueError("стоповые биты: 1, 1.5 или 2")
    if settings.timeout_ms <= 0 or settings.poll_interval_ms <= 0:
        raise ValueError("тайм-аут и интервал опроса должны быть больше нуля")
    if not 1 <= settings.slave_id <= 247 or not 1 <= settings.humidity_slave_id <= 247:
        raise ValueError("Modbus ID должен быть в диапазоне 1..247")
    if settings.humidity_enabled and settings.humidity_slave_id == settings.slave_id:
        raise ValueError("внешний датчик влажности должен иметь отдельный Modbus ID")
    if settings.humidity_register_type not in {"holding", "input"}:
        raise ValueError("тип регистра влажности: holding или input")
    if not 0 <= settings.humidity_address <= 65535:
        raise ValueError("адрес регистра влажности должен быть в диапазоне 0..65535")
    if (
        not math.isfinite(settings.humidity_scale)
        or settings.humidity_scale <= 0
        or settings.humidity_stale_ms <= 0
    ):
        raise ValueError("коэффициент и срок свежести влажности должны быть больше нуля")
    if not settings.diagnostic_log.strip():
        raise ValueError("путь диагностического журнала не может быть пустым")


def load_aircon_settings(path: Path, *, fallback_port: str = "") -> AirconSettings:
    defaults = AirconSettings(port=fallback_port)
    if not path.exists():
        return defaults
    parser = configparser.ConfigParser()
    parser.read(path, encoding="utf-8")
    values: dict[str, object] = {}
    for field in fields(defaults):
        section = SECTIONS[field.name]
        current = getattr(defaults, field.name)
        raw = parser.get(section, field.name, fallback=str(current))
        values[field.name] = _convert(current, raw)
    settings = AirconSettings(**values)
    validate_aircon_settings(settings)
    return settings


def changed_setting(settings: AirconSettings, name: str, value: str) -> AirconSettings:
    normalized = name.strip().casefold().replace("-", "_")
    known = {field.name for field in fields(settings)}
    if normalized not in known:
        raise ValueError("неизвестная настройка; откройте F4 для списка")
    candidate = replace(settings, **{normalized: _convert(getattr(settings, normalized), value)})
    if normalized == "parity":
        candidate = replace(candidate, parity=candidate.parity.upper())
    if normalized == "humidity_register_type":
        candidate = replace(candidate, humidity_register_type=candidate.humidity_register_type.lower())
    validate_aircon_settings(candidate)
    return candidate


def save_aircon_settings(path: Path, settings: AirconSettings) -> None:
    validate_aircon_settings(settings)
    parser = configparser.ConfigParser()
    for field in fields(settings):
        parser.setdefault(SECTIONS[field.name], {})
        parser[SECTIONS[field.name]][field.name] = str(getattr(settings, field.name))
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as stream:
        parser.write(stream)
