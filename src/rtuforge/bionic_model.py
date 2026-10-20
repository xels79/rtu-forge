"""Deterministic physical model for the Bionic Mini installation.

The model consumes controller outputs and calculates their physical effects.  It
never changes an output on behalf of the controller, including on an alarm.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from math import sqrt
from typing import Callable


class AlarmState(str, Enum):
    ACTIVE = "ACTIVE"
    LATCHED = "LATCHED"
    CLEARED = "CLEARED"


@dataclass
class Alarm:
    code: str
    subject: str
    state: AlarmState = AlarmState.ACTIVE
    first_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    acknowledged: bool = False


@dataclass
class Tank:
    id: str
    name: str
    capacity_l: float
    volume_l: float
    height_mm: float = 1000.0
    inflow_lpm: float = 0.0
    outflow_lpm: float = 0.0
    total_loss_l: float = 0.0
    overflow_l: float = 0.0

    @property
    def percent(self) -> float:
        return 100.0 * self.volume_l / self.capacity_l if self.capacity_l else 0.0

    def add(self, litres: float) -> float:
        """Add water and return the overflow volume."""
        accepted = min(max(litres, 0.0), self.capacity_l - self.volume_l)
        self.volume_l += accepted
        overflow = max(0.0, litres - accepted)
        self.overflow_l += overflow
        self.total_loss_l += overflow
        return overflow

    def take(self, litres: float) -> float:
        actual = min(max(litres, 0.0), self.volume_l)
        self.volume_l -= actual
        return actual


@dataclass
class LevelSensor:
    id: str
    tank_id: str
    kind: str
    threshold_l: float
    hysteresis_l: float = 5.0
    delay_s: float = 0.5
    polarity: bool = True
    forced: bool | None = None
    automatic: bool = False
    _candidate: bool | None = None
    _candidate_s: float = 0.0

    @property
    def value(self) -> bool:
        value = self.automatic if self.forced is None else self.forced
        return value if self.polarity else not value

    def update(self, volume_l: float, dt_s: float) -> None:
        if self.kind == "min":
            wanted = volume_l >= (
                self.threshold_l - self.hysteresis_l
                if self.automatic
                else self.threshold_l + self.hysteresis_l
            )
        else:
            wanted = volume_l >= (
                self.threshold_l - self.hysteresis_l
                if self.automatic
                else self.threshold_l + self.hysteresis_l
            )
        if wanted == self.automatic:
            self._candidate = None
            self._candidate_s = 0.0
            return
        if self._candidate != wanted:
            self._candidate = wanted
            self._candidate_s = 0.0
        self._candidate_s += dt_s
        if self._candidate_s >= self.delay_s:
            self.automatic = wanted
            self._candidate = None
            self._candidate_s = 0.0


@dataclass
class TransferPump:
    id: str
    source: str
    destination: str
    relay: int
    flow_lpm: float
    start_s: float = 1.0
    stop_s: float = 1.0
    coefficient: float = 1.0
    failed: bool = False
    actual_flow_lpm: float = 0.0
    total_l: float = 0.0

    def update(self, commanded: bool, dt_s: float) -> float:
        target = self.flow_lpm * self.coefficient if commanded and not self.failed else 0.0
        duration = self.start_s if target > self.actual_flow_lpm else self.stop_s
        step = self.flow_lpm * dt_s / max(duration, 1e-9)
        if self.actual_flow_lpm < target:
            self.actual_flow_lpm = min(target, self.actual_flow_lpm + step)
        else:
            self.actual_flow_lpm = max(target, self.actual_flow_lpm - step)
        return self.actual_flow_lpm


@dataclass
class Tier:
    id: str
    rack: int
    relay: int
    drain_tank: str
    flow_lpm: float = 2.0
    return_fraction: float = 0.8
    return_delay_s: float = 5.0
    actual_flow_lpm: float = 0.0
    total_l: float = 0.0
    loss_l: float = 0.0
    _returns: deque[tuple[float, float]] = field(default_factory=deque)


@dataclass
class Drive:
    id: str
    address: int
    run_relay: int
    selector_relay: int
    setpoint_hz: float = 29.0
    actual_hz: float = 0.0
    run_register: bool = False
    ramp_up_s: float = 5.0
    ramp_down_s: float = 5.0
    motor_hours: float = 0.0
    fault: int = 0
    online: bool = True

    def update(self, external_run: bool, selected: bool, dt_s: float) -> None:
        running = self.online and not self.fault and selected and (external_run or self.run_register)
        target = self.setpoint_hz if running else 0.0
        duration = self.ramp_up_s if target > self.actual_hz else self.ramp_down_s
        step = max(self.setpoint_hz, 1.0) * dt_s / max(duration, 1e-9)
        if self.actual_hz < target:
            self.actual_hz = min(target, self.actual_hz + step)
        else:
            self.actual_hz = max(target, self.actual_hz - step)
        if self.actual_hz > 0.1:
            self.motor_hours += dt_s / 3600.0


@dataclass
class WaterMeter:
    flow_lpm: float = 0.0
    total_l: float = 0.0
    status: str = "OK"
    source: str = "виртуальный"


@dataclass(frozen=True)
class LightZone:
    id: str
    rack: int
    tier: int
    power_relay: int
    channels: dict[str, tuple[int, int]]


DEFAULT_OUTPUTS: dict[str, int] = {
    "boost": 1,
    "bo_to_bp": 2,
    "bso1_to_bp": 17,
    "bso2_to_bp": 18,
    "hp1_select": 19,
    "hp2_select": 20,
    "source_osmosis": 21,
    "bo_fill": 22,
    "source_broth": 23,
    "hp2_run": 31,
    "hp1_run": 32,
}


class BionicModel:
    """Four-tank plant driven exclusively by externally supplied commands."""

    def __init__(self, event: Callable[[str, str, str], None] | None = None) -> None:
        self.event = event or (lambda _kind, _subject, _message: None)
        self.outputs = dict(DEFAULT_OUTPUTS)
        self.relays = [False] * 32
        self.tanks = {
            "bo": Tank("bo", "Осмос", 500.0, 250.0),
            "bp": Tank("bp", "Бульон", 500.0, 250.0),
            "bso1": Tank("bso1", "Дренаж 1", 200.0, 20.0),
            "bso2": Tank("bso2", "Дренаж 2", 200.0, 20.0),
        }
        self.sensors: dict[str, LevelSensor] = {}
        for tank_id, tank in self.tanks.items():
            self.sensors[f"{tank_id}-min"] = LevelSensor(
                f"{tank_id}-min", tank_id, "min", tank.capacity_l * 0.2
            )
            self.sensors[f"{tank_id}-max"] = LevelSensor(
                f"{tank_id}-max", tank_id, "max", tank.capacity_l * 0.8
            )
        self.pumps = {
            "bo-to-bp": TransferPump("bo-to-bp", "bo", "bp", 2, 10.0),
            "bso1-to-bp": TransferPump("bso1-to-bp", "bso1", "bp", 17, 8.0),
            "bso2-to-bp": TransferPump("bso2-to-bp", "bso2", "bp", 18, 8.0),
        }
        self.tiers = {
            f"tier-{index}": Tier(
                f"tier-{index}", 1 if index <= 3 else 2, 8 + index,
                "bso1" if index <= 3 else "bso2",
            )
            for index in range(1, 7)
        }
        self.drives = {
            "hp1": Drive("hp1", 7, 32, 19),
            "hp2": Drive("hp2", 8, 31, 20),
        }
        self.water_meter = WaterMeter()
        self.analog_outputs: dict[tuple[int, int], int] = {}
        # Device indexes follow the verified Stage 7 bindings (AO slaves 2..4).
        self.lights = {
            "zone-1": LightZone("zone-1", 1, 1, 3, {"brightness": (2, 1)}),
            "zone-2": LightZone("zone-2", 1, 2, 4, {"red": (2, 2), "far_red": (2, 3), "blue": (2, 4), "white": (2, 5)}),
            "zone-3": LightZone("zone-3", 1, 3, 5, {"brightness": (2, 6)}),
            "zone-4": LightZone("zone-4", 2, 1, 6, {"brightness": (2, 7)}),
            "zone-5": LightZone("zone-5", 2, 2, 7, {"red": (2, 8), "far_red": (3, 1), "blue": (3, 2), "white": (3, 3)}),
            "zone-6": LightZone("zone-6", 2, 3, 8, {"brightness": (3, 4)}),
        }
        self.water_supply_available = True
        self.fill_flow_lpm = 3.0
        self.fill_valve_stuck_open = False
        self.low_pressure_bar = 0.0
        self.boost_pressure_bar = 2.0
        self.boost_rise_s = 2.0
        self.boost_fall_s = 2.0
        self.high_pressure_bar = 0.0
        self.pressure_rise_s = 5.0
        self.pressure_fall_s = 4.0
        self.pressure_max_bar = 90.0
        self.rupture_threshold_bar = 75.0
        self.rupture_residual_bar = 2.0
        self.pipe_ruptured = False
        self.leak_enabled = False
        self.leak_rate_lpm = 12.0
        self.leak_pressure_factor = 0.25
        self.blockage_enabled = False
        self.blockage_severity = 70.0
        self.total_leak_l = 0.0
        self.total_irrigation_loss_l = 0.0
        self.alarms: dict[tuple[str, str], Alarm] = {}
        self.paused = False
        self.speed = 1.0
        self.running = False
        self.operation_hint: str | None = None
        self.hydraulic_uncertainty = False
        self._overflowing: set[str] = set()

    def relay(self, channel: int) -> bool:
        return self.relays[channel - 1]

    def set_relay(self, channel: int, enabled: bool) -> None:
        if not 1 <= channel <= len(self.relays):
            raise ValueError("Канал реле должен быть в диапазоне 1..32")
        old = self.relays[channel - 1]
        self.relays[channel - 1] = bool(enabled)
        if old != enabled:
            self.event("RS485", f"do-{channel}", f"{int(old)} -> {int(enabled)}")

    def set_analog_output(self, device_address: int, channel: int, value: int) -> None:
        self.analog_outputs[(device_address, channel)] = value
        self.event("RS485", f"ao-{device_address}/{channel}", str(value))

    def light_state(self, zone_id: str) -> tuple[bool, dict[str, float]]:
        zone = self.lights[zone_id]
        values = {
            name: self.analog_outputs.get((device, channel), 0) / 100.0
            for name, (device, channel) in zone.channels.items()
        }
        return self.relay(zone.power_relay), values

    def force_sensor(self, sensor_id: str, value: bool | None) -> None:
        sensor = self.sensors[sensor_id]
        sensor.forced = value
        mode = "AUTO" if value is None else f"FORCE {'ON' if value else 'OFF'}"
        self.event("ОПЕРАТОР", sensor_id, mode)

    def set_tank_level(self, tank_id: str, value: float, *, percent: bool = False) -> None:
        tank = self.tanks[tank_id]
        litres = tank.capacity_l * value / 100.0 if percent else value
        if not 0 <= litres <= tank.capacity_l:
            raise ValueError(f"Уровень должен быть в диапазоне 0..{tank.capacity_l:g} л")
        old = tank.volume_l
        tank.volume_l = litres
        self.event("ОПЕРАТОР", tank_id, f"уровень {old:.2f} -> {litres:.2f} л")
        for sensor in self.sensors.values():
            if sensor.tank_id == tank_id:
                sensor.update(litres, max(sensor.delay_s, 0.0))

    def _alarm(self, code: str, subject: str, active: bool) -> None:
        key = (code, subject)
        alarm = self.alarms.get(key)
        if active and (alarm is None or alarm.state == AlarmState.CLEARED):
            self.alarms[key] = Alarm(code, subject)
            self.event("АВАРИЯ", subject, code)
        elif not active and alarm is not None and alarm.state == AlarmState.ACTIVE:
            alarm.state = AlarmState.LATCHED
            self.event("АВАРИЯ", subject, f"{code}: физическое событие завершено")

    def reset_alarms(self) -> None:
        for alarm in self.alarms.values():
            if alarm.state != AlarmState.ACTIVE:
                alarm.state = AlarmState.CLEARED
                alarm.acknowledged = True
        self.event("ОПЕРАТОР", "alarms", "сброс фиксации")

    def repair_pipe(self) -> None:
        self.pipe_ruptured = False
        self._alarm("PIPE_RUPTURE", "pipe", False)
        self.event("ОПЕРАТОР", "pipe", "виртуальный трубопровод отремонтирован")

    def _add(self, tank_id: str, litres: float) -> None:
        overflow = self.tanks[tank_id].add(litres)
        if overflow > 1e-12:
            self._overflowing.add(tank_id)
        self._alarm("TANK_OVERFLOW", tank_id, overflow > 1e-12)

    def _transfer(self, pump: TransferPump, dt_s: float) -> None:
        flow = pump.update(self.relay(pump.relay), dt_s)
        requested = flow * dt_s / 60.0
        actual = self.tanks[pump.source].take(requested)
        self.tanks[pump.source].outflow_lpm += actual * 60.0 / max(dt_s, 1e-9)
        self.tanks[pump.destination].inflow_lpm += actual * 60.0 / max(dt_s, 1e-9)
        pump.total_l += actual
        self._add(pump.destination, actual)
        if requested > 0 and actual <= 1e-12:
            self._alarm("WATER_SHORTAGE", pump.source, True)
        elif self.tanks[pump.source].volume_l > 0:
            self._alarm("WATER_SHORTAGE", pump.source, False)

    def _pressure_target(self, open_tiers: int) -> float:
        drive = max(self.drives.values(), key=lambda item: item.actual_hz)
        if drive.actual_hz <= 0.1 or self.low_pressure_bar <= 0.1:
            return 0.0
        calibrated = max(0.0, 30.0 + (drive.actual_hz - 29.0) * (27.0 / 13.0))
        paths = max(open_tiers, 0.35)
        pressure = calibrated * sqrt(3.0 / paths)
        if self.leak_enabled:
            pressure *= max(0.05, 1.0 - self.leak_pressure_factor)
        if self.blockage_enabled:
            pressure *= 1.0 + 0.5 * self.blockage_severity / 100.0
        if self.pipe_ruptured:
            return self.rupture_residual_bar
        return min(self.pressure_max_bar, pressure)

    def _smooth(self, current: float, target: float, rise_s: float, fall_s: float, dt_s: float) -> float:
        duration = rise_s if target > current else fall_s
        fraction = min(1.0, dt_s / max(duration, 1e-9))
        return current + (target - current) * fraction

    def tick(self, elapsed_s: float) -> None:
        if elapsed_s < 0:
            raise ValueError("Время шага не может быть отрицательным")
        if self.paused or not self.running or elapsed_s == 0:
            return
        dt_s = elapsed_s * self.speed
        self._overflowing.clear()
        for tank in self.tanks.values():
            tank.inflow_lpm = tank.outflow_lpm = 0.0

        fill_on = self.relay(self.outputs["bo_fill"]) or self.fill_valve_stuck_open
        fill_flow = self.fill_flow_lpm if fill_on and self.water_supply_available else 0.0
        self.water_meter.flow_lpm = fill_flow
        filled = fill_flow * dt_s / 60.0
        self.water_meter.total_l += filled
        self.tanks["bo"].inflow_lpm += fill_flow
        self._add("bo", filled)

        for pump in self.pumps.values():
            self._transfer(pump, dt_s)

        for drive in self.drives.values():
            drive.update(self.relay(drive.run_relay), self.relay(drive.selector_relay), dt_s)

        boost_has_water = self.tanks["bo"].volume_l > 0 or self.tanks["bp"].volume_l > 0
        boost_target = (
            self.boost_pressure_bar
            if self.relay(self.outputs["boost"]) and boost_has_water
            else 0.0
        )
        self.low_pressure_bar = self._smooth(
            self.low_pressure_bar, boost_target, self.boost_rise_s, self.boost_fall_s, dt_s
        )

        active_tiers = [tier for tier in self.tiers.values() if self.relay(tier.relay)]
        pressure_target = self._pressure_target(len(active_tiers))
        if not self.pipe_ruptured and pressure_target >= self.rupture_threshold_bar:
            self.pipe_ruptured = True
            self._alarm("PIPE_RUPTURE", "pipe", True)
            pressure_target = self.rupture_residual_bar
        self.high_pressure_bar = self._smooth(
            self.high_pressure_bar, pressure_target, self.pressure_rise_s,
            0.5 if self.pipe_ruptured else self.pressure_fall_s, dt_s,
        )

        source_bo = self.relay(self.outputs["source_osmosis"])
        source_bp = self.relay(self.outputs["source_broth"])
        self.hydraulic_uncertainty = source_bo and source_bp
        scale = max((drive.actual_hz for drive in self.drives.values()), default=0.0) / 29.0
        if self.pipe_ruptured:
            scale *= 0.1
        if self.blockage_enabled:
            scale *= max(0.0, 1.0 - self.blockage_severity / 100.0)
        requested_l = sum(tier.flow_lpm for tier in active_tiers) * scale * dt_s / 60.0
        shares: list[str] = []
        if source_bo:
            shares.append("bo")
        if source_bp:
            shares.append("bp")
        delivered = 0.0
        if shares and max((d.actual_hz for d in self.drives.values()), default=0.0) > 0.1:
            for tank_id in shares:
                taken = self.tanks[tank_id].take(requested_l / len(shares))
                delivered += taken
                self.tanks[tank_id].outflow_lpm += taken * 60.0 / max(dt_s, 1e-9)
        ratio = delivered / requested_l if requested_l else 0.0
        for tier in self.tiers.values():
            tier.actual_flow_lpm = tier.flow_lpm * scale * ratio if tier in active_tiers else 0.0
            amount = tier.actual_flow_lpm * dt_s / 60.0
            tier.total_l += amount
            returned = amount * tier.return_fraction
            loss = amount - returned
            tier.loss_l += loss
            self.total_irrigation_loss_l += loss
            if returned:
                tier._returns.append((tier.return_delay_s, returned))
            pending: deque[tuple[float, float]] = deque()
            while tier._returns:
                delay, volume = tier._returns.popleft()
                if delay <= dt_s:
                    self._add(tier.drain_tank, volume)
                    self.tanks[tier.drain_tank].inflow_lpm += volume * 60.0 / max(dt_s, 1e-9)
                else:
                    pending.append((delay - dt_s, volume))
            tier._returns = pending

        leak_flow = self.leak_rate_lpm if self.leak_enabled and self.high_pressure_bar > 0.1 else 0.0
        if self.pipe_ruptured and self.high_pressure_bar > 0.1:
            leak_flow += max(20.0, requested_l * 60.0 / max(dt_s, 1e-9))
        leak_l = leak_flow * dt_s / 60.0
        if shares and leak_l:
            actual_leak = 0.0
            for tank_id in shares:
                taken = self.tanks[tank_id].take(leak_l / len(shares))
                actual_leak += taken
                self.tanks[tank_id].outflow_lpm += taken * 60.0 / max(dt_s, 1e-9)
            self.total_leak_l += actual_leak

        for sensor in self.sensors.values():
            sensor.update(self.tanks[sensor.tank_id].volume_l, dt_s)
        for tank_id, tank in self.tanks.items():
            self._alarm("TANK_OVERFLOW", tank_id, tank_id in self._overflowing)
        self._alarm("LEAK", "pipe", self.leak_enabled)
        self._alarm("BLOCKAGE", "pipe", self.blockage_enabled)
        for drive in self.drives.values():
            self._alarm("DRIVE_FAULT", drive.id, bool(drive.fault))

    @property
    def operation(self) -> str:
        if not any(t.actual_flow_lpm > 0 for t in self.tiers.values()):
            return "Ожидание"
        return self.operation_hint or "Операция не определена"

    def analog_raw(self, channel: int) -> int:
        if channel == 1:
            bar, maximum = self.low_pressure_bar, 6.0
        elif channel == 2:
            bar, maximum = self.high_pressure_bar, 100.0
        else:
            return 0
        return round(4000 + min(max(bar / maximum, 0.0), 1.0) * 16000)
