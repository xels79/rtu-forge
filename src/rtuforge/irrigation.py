"""Optional irrigation sequence. No tank levels; hardware adapter supplied by caller.

Safety: pressure instrumentation and VFD register mapping must be commissioned
before running. Hardware overpressure and emergency stop remain mandatory.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from math import isfinite
from time import monotonic
from typing import Protocol


class State(str, Enum):
    IDLE = "idle"
    VALVES = "valves"
    BOOST = "boost"
    STARTING = "starting"
    RUNNING = "running"
    STOPPING = "stopping"
    FAULT = "fault"


VALVES = {(1, 1): 9, (1, 2): 10, (1, 3): 11,
          (2, 1): 12, (2, 2): 13, (2, 3): 14}
DRIVE_START = {7: 32, 8: 31}


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

    def __post_init__(self):
        if not (0 < self.low_min < self.low_ready <= 6):
            raise ValueError("Low-side limits must be within 0..6 bar")
        if not (0 < self.high_min <= self.high_ready < self.high_max <= 100):
            raise ValueError("High-side limits must be within 0..100 bar")
        if any(x <= 0 for x in (self.valve_delay, self.prime_timeout,
                                self.rise_timeout, self.stop_timeout,
                                self.leak_delay)):
            raise ValueError("Timeouts must be positive")


@dataclass(frozen=True)
class Sample:
    low_bar: float
    high_bar: float
    hz: float
    running: bool
    fault: bool = False


class Hardware(Protocol):
    def relay(self, channel: int, active: bool) -> None: ...
    def set_frequency(self, drive: int, percent: float) -> None:
        """Verify terminal start and RS485 frequency source; read back setpoint."""
    def sample(self, drive: int) -> Sample:
        """Read calibrated AI1/AI2 and verified inverter actual frequency/status."""


class IrrigationController:
    def __init__(self, hw: Hardware, limits: Limits, *, clock=monotonic):
        self.hw, self.limits, self.clock = hw, limits, clock
        self.state = State.IDLE
        self.changed = clock()
        self.fault_reason = ""
        self.valve = None
        self.select = None
        self.drive = None
        self.last = None
        self.low_since = None

    def _state(self, value: State):
        self.state, self.changed = value, self.clock()

    def _read(self):
        sample = self.hw.sample(self.drive)
        if (not all(isfinite(v) for v in (sample.low_bar, sample.high_bar, sample.hz))
            or not 0 <= sample.low_bar <= 6
            or not 0 <= sample.high_bar <= 100
            or sample.hz < 0 or sample.fault):
            raise RuntimeError("Invalid sensor/drive feedback or inverter fault")
        self.last = sample
        return sample

    def start(self, rack: int, tier: int, liquid: str, power: float,
              *, drive: int, selector: int):
        if self.state != State.IDLE:
            raise RuntimeError("Controller must be idle")
        if (rack, tier) not in VALVES or liquid != "broth":
            raise ValueError("Supported: rack 1..2, tier 1..3, broth")
        if drive not in DRIVE_START or selector not in (19, 20):
            raise ValueError("Unknown drive or pump selector")
        if not isfinite(power) or not 0 < power <= 100:
            raise ValueError("Power must be between 0 and 100 percent")
        self.drive, self.valve, self.select = drive, VALVES[(rack, tier)], selector
        try:
            self._read()  # communication and scaling check
            self.hw.set_frequency(drive, power)
            self.hw.relay(self.valve, True)
            self.hw.relay(selector, True)
            self.hw.relay(23, True)  # broth
            self._state(State.VALVES)
        except Exception as exc:
            self.emergency(str(exc))
            raise

    def stop(self):
        if self.state in (State.IDLE, State.FAULT):
            return
        errors = []
        # Keep stand valve OPEN until output frequency is zero and RUN is off.
        for channel in (DRIVE_START[self.drive], 1, 23, self.select):
            try:
                self.hw.relay(channel, False)
            except Exception as exc:
                errors.append(f"relay {channel}: {exc}")
        self._state(State.STOPPING)
        if errors:
            self.fault_reason = self.fault_reason or "; ".join(errors)

    def emergency(self, reason: str):
        self.fault_reason = reason
        if self.drive is None:
            self._state(State.FAULT)
        elif self.state not in (State.STOPPING, State.FAULT):
            self.stop()

    def tick(self):
        if self.state in (State.IDLE, State.FAULT):
            return self.state
        now = self.clock()
        if self.state == State.STOPPING:
            try:
                current = self._read()
                if current.hz <= 0.1 and not current.running:
                    if self.valve is not None:
                        self.hw.relay(self.valve, False)
                    self.valve = None
                    self._state(State.FAULT if self.fault_reason else State.IDLE)
                elif now - self.changed >= self.limits.stop_timeout:
                    self.fault_reason = self.fault_reason or "Drive stop not confirmed"
                    self._state(State.FAULT)  # leave stand valve open
            except Exception as exc:
                if now - self.changed >= self.limits.stop_timeout:
                    self.fault_reason = self.fault_reason or f"No stop feedback: {exc}"
                    self._state(State.FAULT)
            return self.state

        try:
            r = self._read()
            age = now - self.changed
            if r.high_bar >= self.limits.high_max:
                raise RuntimeError("Overpressure / blocked irrigation line")
            if self.state == State.VALVES:
                if age >= self.limits.valve_delay:
                    self.hw.relay(1, True)
                    self._state(State.BOOST)
            elif self.state == State.BOOST:
                if r.low_bar >= self.limits.low_ready:
                    self.hw.relay(DRIVE_START[self.drive], True)
                    self._state(State.STARTING)
                elif age >= self.limits.prime_timeout:
                    raise RuntimeError("Low pressure did not rise")
            elif self.state == State.STARTING:
                if r.running and r.high_bar >= self.limits.high_ready:
                    self._state(State.RUNNING)
                elif age >= self.limits.rise_timeout:
                    raise RuntimeError("High pressure / VFD start timeout")
            elif self.state == State.RUNNING:
                if r.low_bar < self.limits.low_min or r.high_bar < self.limits.high_min:
                    if self.low_since is None:
                        self.low_since = now
                    elif now - self.low_since >= self.limits.leak_delay:
                        raise RuntimeError("Pressure loss / leak suspected")
                else:
                    self.low_since = None
        except Exception as exc:
            self.emergency(str(exc))
        return self.state

    def reset_fault(self):
        if self.state != State.FAULT:
            raise RuntimeError("Not in FAULT state")
        if self.drive is not None:
            r = self._read()
            if r.running or r.hz > 0.1:
                raise RuntimeError("Inverter has not stopped")
        # Hardware commissioning must confirm valve and pipe safety.
        if self.valve is not None:
            self.hw.relay(self.valve, False)
        self.valve = self.drive = self.select = self.last = None
        self.fault_reason = ""
        self.low_since = None
        self._state(State.IDLE)
