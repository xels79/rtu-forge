"""Documented IDD mini PLUS feedback; commands still use external FWD relays."""
from __future__ import annotations

from dataclasses import dataclass
from math import isfinite

PLUS_FAULT_REGISTER = 0x001B  # PA27: current error code
PLUS_STATE_REGISTER = 0x001C  # PA28: 0=STOP, 1=forward, 2=reverse


def parse_frequency_hz(value: str | float | int) -> float:
    """Frequency commands accept Hz only; never infer percentages."""
    try:
        hz = float(value)
    except (TypeError, ValueError):
        raise ValueError("Частота задаётся числом в Гц, больше 0 и до 400") from None
    if not isfinite(hz) or not 0 < hz <= 400:
        raise ValueError("Частота задаётся в Гц, больше 0 и до 400; проверьте минимум мотора и максимум Pb05")
    return hz


@dataclass(frozen=True)
class DriveFeedback:
    output_hz: float
    state: int
    error_code: int

    @property
    def running(self) -> bool:
        return self.state != 0

    @property
    def fault(self) -> bool:
        return self.error_code != 0


def decode_plus_feedback(frequency_raw: int, state: int, error_code: int) -> DriveFeedback:
    """PA28 is an enumeration, not a bit mask; reject undocumented states."""
    if not 0 <= frequency_raw <= 4000:
        raise RuntimeError("IDD mini PLUS: PA02 вне документированного диапазона 0..400 Гц")
    if state not in (0, 1, 2):
        raise RuntimeError(f"IDD mini PLUS: недопустимое PA28={state}; допустимы 0 (STOP), 1 и 2 (RUN)")
    if not 0 <= error_code <= 65535:
        raise RuntimeError("IDD mini PLUS: недопустимый код текущей ошибки PA27")
    return DriveFeedback(frequency_raw / 10, state, error_code)
