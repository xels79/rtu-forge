"""Read-only readiness checks: no actuator writes and no automatic commissioning."""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from .irrigation import DRIVE_START, VALVES
from .irrigation_config import IrrigationSettings
from .stand_hardware import StandHardware
from .stand_vfd import parse_frequency_hz


@dataclass(frozen=True)
class ReadinessCheck:
    name: str
    passed: bool
    detail: str


@dataclass(frozen=True)
class PreflightReport:
    drive: int
    selector: int
    valve: int
    checks: tuple[ReadinessCheck, ...]

    @property
    def ready(self) -> bool:
        return all(check.passed for check in self.checks)


def parse_start_args(args: list[str]) -> tuple[int, int, str, float]:
    usage = "start [check] <1..2> <1..3> broth <частота в Гц>"
    if len(args) != 4:
        raise ValueError(usage)
    try:
        rack, tier = int(args[0]), int(args[1])
        hz = parse_frequency_hz(args[3])
    except ValueError:
        raise ValueError(usage) from None
    liquid = args[2].lower()
    if rack not in (1, 2) or tier not in (1, 2, 3) or liquid != "broth":
        raise ValueError(usage)
    return rack, tier, liquid, hz


def check_start(hardware: StandHardware, settings: IrrigationSettings,
                rack: int, tier: int, liquid: str, hz: float) -> PreflightReport:
    """Collect every available blocker, even if commissioning is incomplete."""
    parse_start_args([str(rack), str(tier), liquid, str(hz)])
    settings.validate()
    drive, selector = settings.mapping(rack)
    checks: list[ReadinessCheck] = []
    missing = settings.commissioning_blockers()
    checks.append(ReadinessCheck("Подтверждения и разрешение пуска", not missing,
                                 "все заданы" if not missing else "Не заданы в stand.ini: " + ", ".join(missing)))

    def capture(name: str, action: Callable[[], str]) -> None:
        try:
            checks.append(ReadinessCheck(name, True, action()))
        except (ValueError, RuntimeError, OSError) as exc:
            checks.append(ReadinessCheck(name, False, str(exc)))

    try:
        readings = hardware.pressure()
    except (ValueError, RuntimeError, OSError) as exc:
        checks.append(ReadinessCheck("AI1/AI2: связь и сигналы", False, str(exc)))
    else:
        for reading in readings:
            detail = (f"raw={reading.raw}; тип={reading.mode}; "
                      f"ток={reading.current_ma} мА; "
                      + (reading.error or f"расчётное давление={reading.bar:g} бар"))
            checks.append(ReadinessCheck(f"AI{reading.sensor.channel}", not reading.error, detail))
        high = readings[1]
        if high.bar is not None and high.bar >= settings.high_max_bar:
            checks.append(ReadinessCheck("ДВД перед пуском", False,
                                         f"{high.bar:g} бар >= аварийного максимума {settings.high_max_bar:g} бар"))

    def relays() -> str:
        hardware.precheck_relays()
        return f"RTU {hardware.relay_id}: реле гидравлики выключены; FWD выбранного IDD — реле {DRIVE_START[drive]}"

    def frequency() -> str:
        plan = hardware.frequency_plan(drive, hz)
        return (f"Pb01/Pb02/Pd15/Pd16 соответствуют RS485/FWD; "
                f"{plan.limits_description}; "
                f"задание {plan.requested_hz:g} Гц → {plan.setpoint_raw / 10:g} Гц (только расчёт, шаг 0.1 Гц)")

    def feedback() -> str:
        hz, running, fault = hardware.drive_feedback(drive)
        if running or hz > settings.stop_hz or fault:
            raise RuntimeError(f"Пуск запрещён: частота={hz:g} Гц; {'RUN' if running else 'STOP'}; авария={fault}")
        return f"STOP подтверждён; частота={hz:g} Гц; текущей аварии нет"

    capture("Релейная плата", relays)
    capture(f"IDD {drive}: настройки и задание", frequency)
    capture(f"IDD {drive}: обратная связь", feedback)
    return PreflightReport(drive, selector, VALVES[(rack, tier)], tuple(checks))
