"""Pressure controller, independent of serial I/O and the polling worker."""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum
from math import isfinite
from time import monotonic
from typing import Protocol

from .stand_vfd import parse_frequency_hz


class State(str, Enum):
    IDLE = "IDLE"
    PRECHECK = "PRECHECK"
    CONFIGURE_VFD = "CONFIGURE_VFD"
    OPEN_VALVES = "OPEN_VALVES"
    START_BOOSTER = "START_BOOSTER"
    WAIT_LOW_PRESSURE = "WAIT_LOW_PRESSURE"
    START_VFD = "START_VFD"
    WAIT_HIGH_PRESSURE = "WAIT_HIGH_PRESSURE"
    RUNNING = "RUNNING"
    STOPPING = "STOPPING"
    FAULT = "FAULT"
    VALVES = "START_BOOSTER"
    BOOST = "WAIT_LOW_PRESSURE"
    STARTING = "WAIT_HIGH_PRESSURE"


VALVES = {(1, 1): 9, (1, 2): 10, (1, 3): 11,
          (2, 1): 12, (2, 2): 13, (2, 3): 14}
DRIVE_START = {7: 32, 8: 31}


def relay_purpose(channel: int) -> str:
    for (rack, tier), valve in VALVES.items():
        if channel == valve:
            return f"клапан ВД: стеллаж {rack}, ярус {tier}"
    return {1: "подпорный насос НВД", 19: "выбор НВД 1", 20: "выбор НВД 2",
            23: "клапан бульона", 31: "FWD IDD 8", 32: "FWD IDD 7"}.get(channel, "реле")


@dataclass(frozen=True)
class PendingStep:
    number: int
    description: str
    deadline: float


@dataclass(frozen=True)
class Limits:
    low_ready: float
    low_min: float
    high_ready: float
    high_min: float
    high_max: float
    valve_delay: float = 2.0
    prime_timeout: float = 10.0
    rise_timeout: float = 20.0
    stop_timeout: float = 15.0
    leak_delay: float = 2.0
    hysteresis: float = 0.2
    stop_hz: float = 0.1

    def __post_init__(self) -> None:
        if not all(isfinite(v) for v in self.__dict__.values()):
            raise ValueError("Пороги и задержки должны быть конечными числами")
        if not 0 < self.low_min < self.low_ready <= 6:
            raise ValueError("Пороги НВД: 0 < минимум < готовность <= 6 бар")
        if not 0 < self.high_min <= self.high_ready < self.high_max <= 100:
            raise ValueError("Пороги ДВД: 0 < минимум <= цель < максимум <= 100 бар")
        if self.valve_delay < 0 or any(x <= 0 for x in (self.prime_timeout, self.rise_timeout,
                                                       self.stop_timeout, self.leak_delay)):
            raise ValueError("Тайм-ауты должны быть положительными")
        if not 0 <= self.hysteresis < min(6 - self.low_min, self.high_max - self.high_min):
            raise ValueError("Недопустимый гистерезис давления")
        if not 0 <= self.stop_hz <= 0.1:
            raise ValueError("Порог останова должен быть 0..0.1 Гц")


@dataclass(frozen=True)
class Sample:
    low_bar: float
    high_bar: float
    hz: float
    running: bool
    fault: bool = False
    drive_current_a: float | None = None
    pressure_warning: str = ""


class Hardware(Protocol):
    def relay(self, channel: int, active: bool) -> None: ...
    def precheck(self, drive: int) -> None: ...
    def set_frequency(self, drive: int, hz: float) -> object: ...
    def sample(self, drive: int) -> Sample: ...
    def drive_feedback(self, drive: int) -> tuple[float, bool, bool]: ...
    def confirm_off(self, channels: tuple[int, ...]) -> None: ...


class StopRequested(Exception):
    """The operator requested stop before the next actuator write."""


class IrrigationController:
    def __init__(self, hw: Hardware, limits: Limits, *, clock: Callable[[], float] = monotonic,
                 confirm_timeout: float = 30.0):
        if not isfinite(confirm_timeout) or confirm_timeout <= 0:
            raise ValueError("Тайм-аут подтверждения должен быть положительным")
        self.hw, self.limits, self.clock = hw, limits, clock
        self.confirm_timeout = confirm_timeout
        self.guided = False
        self.pending_step: PendingStep | None = None
        self.step_number = 0
        self.step_approved = False
        self.valve_index = 0
        self.last_stop_hz: float | None = None
        self.state = State.IDLE
        self.changed = clock()
        self.fault_reason = ""
        self.valve: int | None = None
        self.select: int | None = None
        self.drive: int | None = None
        self.last: Sample | None = None
        self.low_since: float | None = None
        self.frequency_hz = 0.0
        self.stop_outputs_confirmed = False
        self.valve_opened = False

    def _state(self, value: State) -> None:
        self.state, self.changed = value, self.clock()

    def _read(self) -> Sample:
        self.last = None
        sample = self.hw.sample(self.drive)
        if (not all(isfinite(v) for v in (sample.low_bar, sample.high_bar, sample.hz))
            or not 0 <= sample.low_bar <= 6 or not 0 <= sample.high_bar <= 100
            or sample.hz < 0 or sample.fault):
            raise RuntimeError("Некорректная обратная связь датчика/частотника или авария IDD")
        if sample.drive_current_a is not None and (not isfinite(sample.drive_current_a) or sample.drive_current_a < 0):
            raise RuntimeError("Некорректный выходной ток IDD")
        self.last = sample
        return sample

    def start(self, rack: int, tier: int, liquid: str, hz: float,
              *, drive: int, selector: int, guided: bool = False) -> None:
        if self.state != State.IDLE:
            raise RuntimeError("Повторный START запрещён: требуется IDLE; выполните stop / reset fault")
        if (rack, tier) not in VALVES or liquid != "broth":
            raise ValueError("start <1..2> <1..3> broth <частота в Гц>")
        if drive not in DRIVE_START or selector not in (19, 20):
            raise ValueError("Неизвестный частотник или выбор НВД")
        hz = parse_frequency_hz(hz)
        self.drive, self.valve, self.select = drive, VALVES[(rack, tier)], selector
        self.frequency_hz, self.low_since, self.last = hz, None, None
        self.guided = guided
        self.pending_step = None
        self.step_number = self.valve_index = 0
        self.step_approved = False
        self.last_stop_hz = None
        self.fault_reason = ""
        self.stop_outputs_confirmed = False
        self.valve_opened = False
        self._state(State.PRECHECK)

    def confirm_step(self, number: int) -> None:
        if (not self.guided or self.pending_step is None or self.pending_step.number != number
            or self.step_approved or self.state in (State.IDLE, State.STOPPING, State.FAULT)):
            raise RuntimeError("Нет ожидающего подтверждения шага; Enter заранее не сохраняется")
        if self.clock() >= self.pending_step.deadline:
            raise RuntimeError("Время подтверждения шага истекло; дождитесь останова")
        self.step_approved = True

    def _approve(self, description: str) -> bool:
        if not self.guided:
            return True
        if self.pending_step is None:
            self.step_number += 1
            self.pending_step = PendingStep(self.step_number, description, self.clock() + self.confirm_timeout)
            return False
        if self.clock() >= self.pending_step.deadline:
            raise RuntimeError("Тайм-аут подтверждения шага оператором")
        if not self.step_approved:
            return False
        self.pending_step = None
        self.step_approved = False
        return True

    def _drop_outputs(self) -> None:
        errors = []
        channels = (DRIVE_START[self.drive], 1, self.select, 23)
        for channel in channels:
            try:
                self.hw.relay(channel, False)
            except Exception as exc:
                errors.append(f"реле {channel}: {exc}")
        try:
            self.hw.confirm_off(channels)
        except Exception as exc:
            errors.append(f"подтверждение реле: {exc}")
        self.stop_outputs_confirmed = not errors
        if errors:
            self.fault_reason = self.fault_reason or "; ".join(errors)

    def stop(self) -> None:
        if self.drive is None or self.state == State.IDLE:
            return
        if self.state != State.STOPPING:
            self._state(State.STOPPING)
        self.pending_step = None
        self.step_approved = False
        self._drop_outputs()

    def emergency(self, reason: str) -> None:
        self.fault_reason = self.fault_reason or reason
        if self.drive is None:
            self._state(State.FAULT)
        else:
            self.stop()

    def tick(self) -> State:
        if self.state in (State.IDLE, State.FAULT):
            return self.state
        now = self.clock()
        if self.state == State.STOPPING:
            try:
                self.last_stop_hz = None
                if not self.stop_outputs_confirmed:
                    self._drop_outputs()
                hz, running, _ = self.hw.drive_feedback(self.drive)
                if not isfinite(hz) or hz < 0:
                    raise RuntimeError("Некорректная выходная частота при останове")
                self.last_stop_hz = hz
                if hz <= self.limits.stop_hz and not running and self.stop_outputs_confirmed:
                    if self.valve is not None and self.valve_opened:
                        self.hw.relay(self.valve, False)
                    self.valve = None
                    self.valve_opened = False
                    self._state(State.FAULT if self.fault_reason else State.IDLE)
                elif now - self.changed >= self.limits.stop_timeout:
                    self.fault_reason = self.fault_reason or "Останов частотника/реле не подтверждён; клапан яруса оставлен открытым"
                    self._state(State.FAULT)
            except Exception as exc:
                if now - self.changed >= self.limits.stop_timeout:
                    self.fault_reason = self.fault_reason or f"Нет обратной связи останова: {exc}; клапан оставлен открытым"
                    self._state(State.FAULT)
            return self.state
        try:
            r = self._read()
            age = now - self.changed
            if r.high_bar >= self.limits.high_max:
                raise RuntimeError("Превышено ДВД: возможна закупорка линии")
            if self.guided and self.state in (State.CONFIGURE_VFD, State.OPEN_VALVES,
                                              State.START_BOOSTER, State.WAIT_LOW_PRESSURE, State.START_VFD):
                if r.running or r.hz > self.limits.stop_hz:
                    raise RuntimeError("IDD запущен до подтверждённого шага FWD")
            if self.state == State.PRECHECK:
                if r.running or r.hz > self.limits.stop_hz:
                    raise RuntimeError("Частотник уже работает; пуск запрещён")
                self.hw.precheck(self.drive)
                self._state(State.CONFIGURE_VFD)
            elif self.state == State.CONFIGURE_VFD:
                if self._approve(f"IDD {self.drive}: записать задание {self.frequency_hz:g} Гц, пуск FWD выключен"):
                    self.hw.set_frequency(self.drive, self.frequency_hz)
                    self._state(State.OPEN_VALVES)
            elif self.state == State.OPEN_VALVES:
                channels = (self.valve, self.select, 23)
                if self.guided:
                    channel = channels[self.valve_index]
                    if self._approve(f"ВКЛ реле {channel}: {relay_purpose(channel)}"):
                        if channel == self.valve:
                            self.valve_opened = True  # lost acknowledgement may still mean open
                        self.hw.relay(channel, True)
                        self.valve_index += 1
                        if self.valve_index == len(channels):
                            self._state(State.START_BOOSTER)
                else:
                    self.valve_opened = True
                    for channel in channels:
                        self.hw.relay(channel, True)
                    self._state(State.START_BOOSTER)
            elif self.state == State.START_BOOSTER:
                if age >= self.limits.valve_delay and self._approve("ВКЛ реле 1: подпорный насос НВД"):
                    self.hw.relay(1, True)
                    self._state(State.WAIT_LOW_PRESSURE)
            elif self.state == State.WAIT_LOW_PRESSURE:
                if r.low_bar >= self.limits.low_ready:
                    self._state(State.START_VFD)
                elif age >= self.limits.prime_timeout:
                    raise RuntimeError("Нет подпора: НВД не поднялось за тайм-аут")
            elif self.state == State.START_VFD:
                if r.low_bar < self.limits.low_ready:
                    raise RuntimeError("Подпор пропал до пуска частотника")
                channel = DRIVE_START[self.drive]
                if self._approve(f"ВКЛ реле {channel}: FWD IDD {self.drive}, после подтверждения НВД"):
                    self.hw.relay(channel, True)
                    self._state(State.WAIT_HIGH_PRESSURE)
            elif self.state == State.WAIT_HIGH_PRESSURE:
                if r.low_bar < self.limits.low_min:
                    raise RuntimeError("Нет подпора во время набора ДВД")
                if r.running and r.hz > self.limits.stop_hz and r.high_bar >= self.limits.high_ready:
                    self._state(State.RUNNING)
                elif age >= self.limits.rise_timeout:
                    raise RuntimeError("ДВД не набирается / пуск RUN не подтверждён")
            elif self.state == State.RUNNING:
                if not r.running or r.hz <= self.limits.stop_hz:
                    raise RuntimeError("Потеря подтверждения RUN/выходной частоты")
                if r.low_bar < self.limits.low_min or r.high_bar < self.limits.high_min:
                    if self.low_since is None:
                        self.low_since = now
                elif (r.low_bar >= self.limits.low_min + self.limits.hysteresis
                      and r.high_bar >= self.limits.high_min + self.limits.hysteresis):
                    self.low_since = None
                if self.low_since is not None and now - self.low_since >= self.limits.leak_delay:
                    raise RuntimeError("Падение давления: возможна протечка или потеря подпора")
        except StopRequested:
            self.stop()
        except Exception as exc:
            self.emergency(str(exc))
        return self.state

    def reset_fault(self) -> None:
        if self.state != State.FAULT:
            raise RuntimeError("reset fault: контроллер должен быть в FAULT")
        self._drop_outputs()
        hz, running, fault = self.hw.drive_feedback(self.drive)
        if not self.stop_outputs_confirmed or not isfinite(hz) or hz < 0 or running or fault or hz > self.limits.stop_hz:
            raise RuntimeError("reset fault: останов частотника и реле не подтверждён")
        if self.valve is not None and self.valve_opened:
            self.hw.relay(self.valve, False)
        self.valve_opened = False
        self.valve = self.drive = self.select = self.last = None
        self.fault_reason = ""
        self.low_since = None
        self._state(State.IDLE)
