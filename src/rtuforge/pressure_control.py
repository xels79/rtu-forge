"""Asymmetric pressure regulation, independent of serial I/O."""
from __future__ import annotations

from dataclasses import dataclass
from math import isfinite


@dataclass(frozen=True)
class PressureControl:
    limit_bar: float = 70.0
    max_hz: float = 23.7
    deadband_bar: float = 1.0
    up_step_hz: float = 0.1
    down_step_hz: float = 0.5
    up_interval: float = 1.0
    down_interval: float = 0.25
    rise_stop_bar: float = 63.0
    rise_margin_bar: float = 0.5
    min_hz: float = 20.0

    def __post_init__(self) -> None:
        if not all(isfinite(v) and v > 0 for v in self.__dict__.values()):
            raise ValueError("Настройки регулирования давления должны быть конечными и положительными")
        if self.limit_bar > 100 or not self.min_hz <= self.max_hz <= 400:
            raise ValueError("pressure_limit_bar <= 100 бар; 0 < pressure_min_hz <= pressure_max_hz <= 400 Гц")
        for value in (self.min_hz, self.max_hz, self.up_step_hz, self.down_step_hz):
            if abs(value * 10 - round(value * 10)) > 1e-7:
                raise ValueError("pressure_min_hz/pressure_max_hz/pressure_up_step_hz/pressure_down_step_hz задаются с шагом 0.1 Гц")
        if self.down_step_hz / self.down_interval < self.up_step_hz / self.up_interval:
            raise ValueError("Снижение частоты должно быть не медленнее повышения")

    def validate_limits(self, target_bar: float, cutoff_bar: float) -> None:
        if (not self.deadband_bar < target_bar
            or not target_bar + self.deadband_bar < self.rise_stop_bar < self.limit_bar < cutoff_bar):
            raise ValueError("Регулирование требует: 0 < зона цели < high_target_bar; "
                             "high_target_bar + pressure_deadband_bar < pressure_rise_stop_bar "
                             "< pressure_limit_bar < high_max_bar")

    def validate_start(self, hz: float) -> None:
        if not self.min_hz <= hz <= self.max_hz:
            raise ValueError(f"Начальная частота {hz:g} Гц вне pressure_min_hz={self.min_hz:g} "
                             f"..pressure_max_hz={self.max_hz:g}; задайте частоту в допустимом диапазоне")


class PressureRegulator:
    def __init__(self, settings: PressureControl, target_bar: float, minimum_hz: float,
                 initial_hz: float) -> None:
        self.settings, self.target_bar = settings, target_bar
        self.minimum_raw = max(1, round(minimum_hz * 10))
        self.maximum_raw = round(settings.max_hz * 10)
        self.current_raw = round(initial_hz * 10)
        if not self.minimum_raw <= self.current_raw <= self.maximum_raw:
            raise ValueError("Начальная частота вне проверенного диапазона регулирования")
        self.last_change: float | None = None

    def arm(self, now: float) -> None:
        """Start the increase delay at FWD, rather than at configuration time."""
        self.last_change = now

    def propose(self, pressure_bar: float, now: float, *, allow_increase: bool = False) -> float | None:
        cfg = self.settings
        age = 0 if self.last_change is None else now - self.last_change
        if pressure_bar >= cfg.limit_bar:
            value = self.minimum_raw  # urgent reduction bypasses the normal interval
        elif pressure_bar > self.target_bar + cfg.deadband_bar and age >= cfg.down_interval:
            value = max(self.minimum_raw, self.current_raw - round(cfg.down_step_hz * 10))
        elif (allow_increase and pressure_bar < self.target_bar - cfg.deadband_bar
              and age >= cfg.up_interval):
            # Exactly one step, even after a delayed poll; never catch up with a jump.
            value = min(self.maximum_raw, self.current_raw + round(cfg.up_step_hz * 10))
        else:
            return None
        return value / 10 if value != self.current_raw else None

    def commit(self, hz: float, now: float) -> None:
        """Only remember a setpoint after the adapter has verified its readback."""
        self.current_raw = round(hz * 10)
        self.last_change = now
