"""OWEN PD100 pressure sensors on Waveshare 8CH analog input RTU slave 6.

AI1: PD100-DI0.6-171-0.5, 0..6 bar, 4..20mA.
AI2: PD100-DI10.0-111-0.5, 0..100 bar, 4..20mA.

The conversion expects validated microamp readings. Do not assume that
Waveshare Modbus raw registers have this unit; the hardware adapter MUST
decode its documented per-channel input mode and register scaling first.
"""
from __future__ import annotations

from dataclasses import dataclass
from math import isfinite

AI_RTU_ID = 6


@dataclass(frozen=True)
class Sensor:
    model: str
    channel: int
    maximum_bar: float


LOW = Sensor("ПД100-ДИ0,6-171-0,5", 1, 6.0)
HIGH = Sensor("ПД100-ДИ10,0-111-0,5", 2, 100.0)


def ma_to_bar(current_ma: float, maximum_bar: float, *, tolerance_ma: float = 0.1) -> float:
    """Scale calibrated 4..20mA to bar; fault on broken/out-of-range loop."""
    if (not isfinite(current_ma) or not isfinite(maximum_bar) or maximum_bar <= 0
        or not isfinite(tolerance_ma) or not 0 <= tolerance_ma < 4):
        raise ValueError("Некорректное значение датчика")
    if current_ma < 4 - tolerance_ma or current_ma > 20 + tolerance_ma:
        raise ValueError("Обрыв петли или ток датчика вне диапазона 4..20 мА")
    return max(0.0, min(maximum_bar, (current_ma - 4) * maximum_bar / 16.0))


def low_pressure(current_ma: float) -> float:
    return ma_to_bar(current_ma, LOW.maximum_bar)


def high_pressure(current_ma: float) -> float:
    return ma_to_bar(current_ma, HIGH.maximum_bar)


def decode_pressure(raw: int, mode: int, sensor: Sensor) -> tuple[float, float]:
    """Waveshare Input 8CH protocol V2: mode 3 registers contain microamps."""
    if mode != 3:
        raise ValueError(f"AI{sensor.channel}: требуется тип 3 (4–20 мА), получен {mode}; проверьте ai types")
    if not 0 <= raw <= 65535:
        raise ValueError(f"AI{sensor.channel}: неверный сырой регистр")
    current = raw / 1000.0
    try:
        pressure = ma_to_bar(current, sensor.maximum_bar)
    except ValueError as exc:
        raise ValueError(f"AI{sensor.channel}: raw={raw}, ток={current:g} мА: {exc}") from exc
    return current, pressure
