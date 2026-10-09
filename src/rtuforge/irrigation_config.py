"""Explicit commissioning and pressure options, stored in stand.ini only."""
from __future__ import annotations

import configparser
from dataclasses import dataclass, fields, replace
from math import isfinite
from pathlib import Path

from .config import OptionSpec, parse_value
from .irrigation import Limits


@dataclass(frozen=True)
class IrrigationSettings:
    enabled: bool = False
    ai_verified: bool = False
    vfd_verified: bool = False
    hydraulics_verified: bool = False
    protections_verified: bool = False
    pressure_unit_verified: bool = False
    relay_id_verified: bool = False
    pump1_drive: int = 7
    pump2_drive: int = 8
    rack1_pump: int = 1
    rack2_pump: int = 2
    drive7_min_hz: float = 24.0
    drive8_min_hz: float = 0.0
    low_ready_bar: float = 1.0
    low_min_bar: float = 0.5
    high_target_bar: float = 60.0
    high_min_bar: float = 50.0
    high_max_bar: float = 70.0
    hysteresis_bar: float = 0.2
    valve_delay_ms: int = 2000
    prime_timeout_ms: int = 10000
    rise_timeout_ms: int = 20000
    stop_timeout_ms: int = 15000
    leak_delay_ms: int = 2000
    poll_ms: int = 250
    stop_hz: float = 0.1
    run_register: int = -1
    run_mask: int = 1
    fault_register: int = -1
    fault_mask: int = 65535
    setpoint_readback: bool = False

    def validate(self) -> None:
        self.limits()
        if {self.pump1_drive, self.pump2_drive} != {7, 8}:
            raise ValueError("pump1_drive/pump2_drive должны однозначно задавать адреса 7 и 8")
        if self.rack1_pump not in (1, 2) or self.rack2_pump not in (1, 2):
            raise ValueError("rack1_pump/rack2_pump: допустимы 1 и 2")
        if any(not isfinite(v) or not 0 <= v <= 400
               for v in (self.drive7_min_hz, self.drive8_min_hz)):
            raise ValueError("drive7_min_hz/drive8_min_hz: допустимо 0..400 Гц")
        if any(v <= 0 for v in (self.poll_ms, self.prime_timeout_ms, self.rise_timeout_ms,
                                self.stop_timeout_ms, self.leak_delay_ms)) or self.valve_delay_ms < 0:
            raise ValueError("Задержки/периоды должны быть положительными (valve_delay_ms допускает 0)")
        if not isfinite(self.stop_hz) or not 0 <= self.stop_hz <= 0.1:
            raise ValueError("stop_hz: допустимо 0..0.1 Гц")
        if any(not -1 <= v <= 65535 for v in (self.run_register, self.fault_register)):
            raise ValueError("Регистры обратной связи: -1 (не подтверждён) или 0..65535")
        incompatible = {1, 2, *range(10, 19), 0x2000, 0x2001}
        if self.run_register in incompatible or self.fault_register in incompatible:
            raise ValueError("RUN/текущую аварию нельзя подменять заданием, частотой, командами или историей PA10..PA18")
        if any(not 1 <= v <= 65535 for v in (self.run_mask, self.fault_mask)):
            raise ValueError("Маски RUN/ошибки: допустимо 1..65535")

    def limits(self) -> Limits:
        return Limits(self.low_ready_bar, self.low_min_bar, self.high_target_bar,
                      self.high_min_bar, self.high_max_bar,
                      self.valve_delay_ms / 1000, self.prime_timeout_ms / 1000,
                      self.rise_timeout_ms / 1000, self.stop_timeout_ms / 1000,
                      self.leak_delay_ms / 1000, self.hysteresis_bar, self.stop_hz)

    def require_commissioned(self) -> None:
        self.validate()
        missing = self.commissioning_blockers()
        if missing:
            raise RuntimeError("Автопуск заблокирован: подтвердите на оборудовании и задайте в stand.ini: "
                               + ", ".join(missing) + ". См. start check, help start и IRRIGATION.md")

    def commissioning_blockers(self) -> list[str]:
        """List missing confirmations without changing settings or connecting hardware."""
        missing = [f.name for f in fields(self) if (f.name == "enabled" or f.name.endswith("_verified"))
                   and not getattr(self, f.name)]
        missing.extend(name for name in ("run_register", "fault_register") if getattr(self, name) < 0)
        return missing

    def mapping(self, rack: int) -> tuple[int, int]:
        pump = self.rack1_pump if rack == 1 else self.rack2_pump
        return (self.pump1_drive if pump == 1 else self.pump2_drive, 18 + pump)


# Like RTU options, every mutable stand irrigation setting has an OptionSpec.
OPTION_SPECS: tuple[OptionSpec, ...] = tuple(
    OptionSpec("irrigation", f.name, f.name,
               "bool" if isinstance(value := getattr(IrrigationSettings(), f.name), bool)
               else "int" if isinstance(value, int) else "float", default=str(value).lower())
    for f in fields(IrrigationSettings)
)


def _parse_option(spec: OptionSpec, value: str) -> str:
    if spec.name in {"run_register", "fault_register", "run_mask", "fault_mask"} and value.strip().lower().startswith("0x"):
        value = str(int(value, 16))
    return parse_value(spec, value)


def load_irrigation_settings(path: Path) -> IrrigationSettings:
    parser = configparser.ConfigParser()
    if path.exists():
        parser.read(path, encoding="utf-8")
    values = {}
    for spec in OPTION_SPECS:
        value = _parse_option(spec, parser.get(spec.section, spec.name, fallback=spec.default))
        values[spec.name] = value == "true" if spec.kind == "bool" else int(value) if spec.kind == "int" else float(value)
    settings = IrrigationSettings(**values)
    settings.validate()
    return settings


def set_irrigation_option(path: Path, settings: IrrigationSettings, name: str, value: str) -> IrrigationSettings:
    spec = next((s for s in OPTION_SPECS if s.name == name), None)
    if spec is None:
        raise ValueError("Неизвестная настройка полива. См. help pressure")
    parsed = _parse_option(spec, value)
    typed = parsed == "true" if spec.kind == "bool" else int(parsed) if spec.kind == "int" else float(parsed)
    updated = replace(settings, **{name: typed})
    updated.validate()
    parser = configparser.ConfigParser()
    if path.exists():
        parser.read(path, encoding="utf-8")
    if not parser.has_section("irrigation"):
        parser.add_section("irrigation")
    parser["irrigation"][name] = parsed
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as stream:
        parser.write(stream)
    return updated
