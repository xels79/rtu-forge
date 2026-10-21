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

from .bionic_equipment import (
    FACTORY_EQUIPMENT_PROFILES, EquipmentHealth, EquipmentProfile,
)
from .bionic_idd import IDD_FAULT_OVERLOAD_RUNNING, validate_idd_parameter
from .bionic_lights import FACTORY_LIGHTS, LightConfig, LightType, brightness_percent
from .bionic_ponics import PonicsPilot


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
class SolutionParcel:
    volume_l: float
    solute_mass: float
    acidity_units: float
    buffer_units: float
    heat_c_l: float

    def scaled(self, fraction: float) -> SolutionParcel:
        fraction = min(max(fraction, 0.0), 1.0)
        return SolutionParcel(
            self.volume_l * fraction,
            self.solute_mass * fraction,
            self.acidity_units * fraction,
            self.buffer_units * fraction,
            self.heat_c_l * fraction,
        )


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
    solute_mass: float = 0.0
    acidity_units: float = 0.0
    buffer_units: float = 0.0
    heat_c_l: float = 0.0
    nutrients_consumed: float = 0.0

    @property
    def percent(self) -> float:
        return 100.0 * self.volume_l / self.capacity_l if self.capacity_l else 0.0

    def add(self, litres: float) -> float:
        """Add liquid with the tank's current composition."""
        parcel = self.sample(max(litres, 0.0))
        return self.add_solution(parcel)

    def initialize_solution(
        self, *, ec_ms_cm: float, ph: float, temperature_c: float,
        buffer_per_l: float,
    ) -> None:
        self.solute_mass = max(0.0, ec_ms_cm) * self.volume_l
        self.buffer_units = max(1e-9, buffer_per_l * self.volume_l)
        self.acidity_units = (7.0 - ph) * self.buffer_units
        self.heat_c_l = temperature_c * self.volume_l

    @property
    def ec_ms_cm(self) -> float:
        return self.solute_mass / self.volume_l if self.volume_l > 1e-12 else 0.0

    @property
    def ph(self) -> float:
        if self.buffer_units <= 1e-12:
            return 7.0
        return min(14.0, max(0.0, 7.0 - self.acidity_units / self.buffer_units))

    @property
    def temperature_c(self) -> float:
        return self.heat_c_l / self.volume_l if self.volume_l > 1e-12 else 0.0

    def sample(self, litres: float) -> SolutionParcel:
        """Return a parcel with this concentration without changing the tank."""
        if self.volume_l <= 1e-12 or litres <= 0:
            return SolutionParcel(max(0.0, litres), 0.0, 0.0, 0.0, 0.0)
        fraction = litres / self.volume_l
        return SolutionParcel(
            litres,
            self.solute_mass * fraction,
            self.acidity_units * fraction,
            self.buffer_units * fraction,
            self.heat_c_l * fraction,
        )

    def add_solution(self, parcel: SolutionParcel) -> float:
        accepted = min(max(parcel.volume_l, 0.0), self.capacity_l - self.volume_l)
        fraction = accepted / parcel.volume_l if parcel.volume_l > 1e-12 else 0.0
        self.volume_l += accepted
        self.solute_mass += parcel.solute_mass * fraction
        self.acidity_units += parcel.acidity_units * fraction
        self.buffer_units += parcel.buffer_units * fraction
        self.heat_c_l += parcel.heat_c_l * fraction
        overflow = max(0.0, parcel.volume_l - accepted)
        self.overflow_l += overflow
        self.total_loss_l += overflow
        return overflow

    def take(self, litres: float) -> float:
        return self.take_solution(litres).volume_l

    def take_solution(self, litres: float) -> SolutionParcel:
        actual = min(max(litres, 0.0), self.volume_l)
        parcel = self.sample(actual)
        self.volume_l -= actual
        self.solute_mass -= parcel.solute_mass
        self.acidity_units -= parcel.acidity_units
        self.buffer_units -= parcel.buffer_units
        self.heat_c_l -= parcel.heat_c_l
        if self.volume_l <= 1e-12:
            self.solute_mass = self.acidity_units = self.buffer_units = self.heat_c_l = 0.0
        return parcel


@dataclass
class LevelSensor:
    id: str
    tank_id: str
    kind: str
    threshold_l: float
    hysteresis_l: float = 0.0
    delay_s: float = 0.0
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
    actual_flow_lpm: float = 0.0
    total_l: float = 0.0
    health: EquipmentHealth = field(init=False)

    def __post_init__(self) -> None:
        self.health = EquipmentHealth.create(FACTORY_EQUIPMENT_PROFILES[self.id])

    @property
    def failed(self) -> bool:
        return self.health.failed

    @property
    def repair_required(self) -> bool:
        return self.health.repair_required

    def update(self, commanded: bool, dt_s: float) -> float:
        target = (
            self.flow_lpm * self.coefficient * self.health.performance_factor
            if commanded else 0.0
        )
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
    _returns: deque[tuple[float, SolutionParcel]] = field(default_factory=deque)


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
    nominal_current_a: float = 16.0
    no_load_current_a: float = 4.0
    pump_load_coefficient: float = 1.0
    jam_current_multiplier: float = 2.0
    overload_trip_s: float = 60.0
    overload_protection_enabled: bool = True
    overload_threshold_multiplier: float = 1.5
    protection_behavior: str = "latched_reset"
    calculated_current_a: float = 0.0
    calculated_load: float = 0.0
    overload_elapsed_s: float = 0.0
    protection_state: str = "READY"
    configuration: dict[int, int] = field(default_factory=dict)
    health: EquipmentHealth = field(init=False)
    configuration_changed: Callable[[int, int], None] = field(
        default=lambda _address, _value: None, repr=False, compare=False,
    )

    def __post_init__(self) -> None:
        self.health = EquipmentHealth.create(FACTORY_EQUIPMENT_PROFILES[self.id])
        if not self.configuration:
            self.configuration = {
                # Standalone model tests use the physical RUN terminals.  The
                # application applies its persisted PB.02 (normally RS-485).
                100: 290, 101: 5, 102: 1, 105: 500, 106: 200,
                107: 50, 108: 50, 210: round(self.nominal_current_a * 10),
                212: 1460, 215: 500,
                700: 1, 701: 3, 702: self.address,
                816: int(self.overload_protection_enabled),
            }

    @property
    def control_source(self) -> str:
        return {0: "panel", 1: "terminals", 2: "modbus"}.get(
            self.configuration.get(102, 0), "unsupported",
        )

    @property
    def frequency_source(self) -> str:
        return "modbus" if self.configuration.get(101) == 5 else (
            "local" if self.configuration.get(101) == 0 else "unsupported"
        )

    def write_parameter(self, address: int, value: int) -> None:
        validate_idd_parameter(address, value, self.configuration)
        self.configuration[address] = value
        if address == 107:
            self.ramp_up_s = value / 10.0
        elif address == 108:
            self.ramp_down_s = value / 10.0
        elif address == 702:
            self.address = value
        elif address == 210:
            self.nominal_current_a = value / 10.0
        elif address == 816:
            self.overload_protection_enabled = bool(value)
        self.configuration_changed(address, value)

    def commanded(self, terminal_run: bool, selected: bool) -> bool:
        return self.input_command(terminal_run, selected) and self.online and not self.fault

    def input_command(self, terminal_run: bool, selected: bool) -> bool:
        """Return the physical controller command before internal VFD protection."""
        if not selected:
            return False
        if self.control_source == "terminals":
            return terminal_run
        if self.control_source == "modbus":
            return self.run_register
        return False

    @property
    def repair_required(self) -> bool:
        return self.health.repair_required

    @property
    def mechanical_failure(self) -> str:
        return self.health.failure

    @mechanical_failure.setter
    def mechanical_failure(self, value: str) -> None:
        self.health.failure = value
        if value != "none":
            self.health.state = "FAILED"
        elif self.health.damage > 0:
            self.health.state = "DEGRADED"
        else:
            self.health.state = "HEALTHY"

    @property
    def mechanical_damage(self) -> float:
        return self.health.damage

    @mechanical_damage.setter
    def mechanical_damage(self, value: float) -> None:
        self.health.damage = min(1.0, max(0.0, value))
        if self.health.failure == "none":
            self.health.state = "DEGRADED" if self.health.damage > 0 else "HEALTHY"

    @property
    def hydraulic_factor(self) -> float:
        return self.health.performance_factor

    def repair(self) -> None:
        self.health.repair()
        self.overload_elapsed_s = 0.0

    def reset_fault(self) -> None:
        self.fault = 0
        self.overload_elapsed_s = 0.0
        self.protection_state = "READY"

    def target_hz(self) -> float:
        if self.frequency_source == "modbus":
            requested = self.setpoint_hz
        elif self.frequency_source == "local":
            requested = self.configuration[100] / 10.0
        else:
            requested = 0.0
        minimum = self.configuration[106] / 10.0
        maximum = self.configuration[105] / 10.0
        return min(maximum, max(minimum, requested))

    @property
    def speed_rpm(self) -> int:
        nominal_hz = self.configuration[215] / 10.0
        if nominal_hz <= 0:
            return 0
        return round(self.configuration[212] * self.actual_hz / nominal_hz)

    def update(self, external_run: bool, selected: bool, dt_s: float) -> None:
        running = self.commanded(external_run, selected)
        target = self.target_hz() if running else 0.0
        duration = self.ramp_up_s if target > self.actual_hz else self.ramp_down_s
        step = max(self.setpoint_hz, 1.0) * dt_s / max(duration, 1e-9)
        if self.actual_hz < target:
            self.actual_hz = min(target, self.actual_hz + step)
        else:
            self.actual_hz = max(target, self.actual_hz - step)
        if self.actual_hz > 0.1:
            self.motor_hours += dt_s / 3600.0
        ratio = min(1.0, self.actual_hz / max(self.configuration[105] / 10.0, 0.1))
        if self.actual_hz <= 0.1:
            self.calculated_load = 0.0
            self.calculated_current_a = 0.0
        elif self.mechanical_failure == "jammed":
            self.calculated_load = self.jam_current_multiplier
            self.calculated_current_a = self.nominal_current_a * self.jam_current_multiplier
        elif self.mechanical_failure == "motor_failure":
            self.calculated_load = 0.0
            self.calculated_current_a = 0.0
        elif self.health.dry_running or self.mechanical_failure in {"loss_of_prime", "dry_run_wear"}:
            self.calculated_load = 0.1
            self.calculated_current_a = self.no_load_current_a * max(ratio, 0.2)
        else:
            self.calculated_load = self.pump_load_coefficient * self.hydraulic_factor
            span = max(0.0, self.nominal_current_a - self.no_load_current_a)
            self.calculated_current_a = self.no_load_current_a + span * self.calculated_load * ratio
        threshold = self.nominal_current_a * self.overload_threshold_multiplier
        overloaded = self.calculated_current_a > threshold
        if running and overloaded and self.overload_protection_enabled:
            self.protection_state = "TIMING"
            self.overload_elapsed_s += dt_s
            if self.overload_elapsed_s >= self.overload_trip_s:
                self.fault = IDD_FAULT_OVERLOAD_RUNNING
                self.protection_state = "TRIPPED"
        elif not self.fault:
            self.overload_elapsed_s = 0.0
            self.protection_state = "READY" if self.overload_protection_enabled else "DISABLED"


@dataclass
class WaterMeter:
    flow_lpm: float = 0.0
    total_l: float = 0.0
    status: str = "OK"
    source: str = "виртуальный"


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
        self.sensor_change: Callable[[], None] = lambda: None
        self.outputs = dict(DEFAULT_OUTPUTS)
        self.relays = [False] * 32
        self.tanks = {
            "bo": Tank("bo", "Осмос", 500.0, 250.0),
            "bp": Tank("bp", "Бульон", 500.0, 250.0),
            "bso1": Tank("bso1", "Дренаж 1", 200.0, 20.0),
            "bso2": Tank("bso2", "Дренаж 2", 200.0, 20.0),
        }
        self.tanks["bo"].initialize_solution(ec_ms_cm=0.1, ph=6.8, temperature_c=20.0, buffer_per_l=0.3)
        self.tanks["bp"].initialize_solution(ec_ms_cm=2.0, ph=6.0, temperature_c=20.0, buffer_per_l=1.0)
        self.tanks["bso1"].initialize_solution(ec_ms_cm=1.8, ph=6.1, temperature_c=20.0, buffer_per_l=0.8)
        self.tanks["bso2"].initialize_solution(ec_ms_cm=1.8, ph=6.1, temperature_c=20.0, buffer_per_l=0.8)
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
        self.lights = {light.id: light for light in FACTORY_LIGHTS}
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
        self.valve_pressure_response_ms = 200
        self.valve_pressure_close_response_ms = 200
        self.transient_pressure_spike_coefficient = 0.0
        self.transient_pressure_spike_duration_ms = 100
        self.closed_head_pressure_bar = 90.0
        self.pressure_max_bar = 90.0
        self.rupture_threshold_bar = 75.0
        self.rupture_residual_bar = 2.0
        self.pressure_target_bar = 0.0
        self.last_pressure_spike_bar = 0.0
        self.max_pressure_bar = 0.0
        self.calculated_flow_lpm = 0.0
        self.hydraulic_resistance = 1.0
        self.blockage_position = "после датчика HIGH"
        self.pipe_ruptured = False
        self.leak_enabled = False
        self.leak_rate_lpm = 12.0
        self.leak_pressure_factor = 0.25
        self.blockage_enabled = False
        self.blockage_severity = 70.0
        self.total_leak_l = 0.0
        self.total_irrigation_loss_l = 0.0
        self.osmosis_profile = {"ec": 0.1, "ph": 6.8, "temperature": 20.0, "buffer": 0.3}
        self.nutrient_absorption_fraction = 0.05
        self.deposition_fraction = 0.01
        self.ph_drift_per_pass = 0.02
        self.fertilizer_ec_per_ml_at_100l = 0.01
        self.ph_reagent_delta_per_ml_at_100l = 0.02
        self.alarms: dict[tuple[str, str], Alarm] = {}
        self.paused = False
        self.speed = 1.0
        self.running = False
        self.operation_hint: str | None = None
        self.hydraulic_uncertainty = False
        self._overflowing: set[str] = set()
        self._hydraulic_signature: tuple[object, ...] | None = None
        self._pressure_pump_running = False
        self._valve_response_remaining_s = 0.0
        self._spike_remaining_s = 0.0
        self.ponics = PonicsPilot(self, lambda kind, subject, message: self.event(kind, subject, message))

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

    def configure_lights(self, profile: tuple[LightConfig, ...]) -> None:
        """Apply a mapping without changing any controller-owned output."""
        self.lights = {light.id: light for light in profile}

    def configure_equipment(
        self, profiles: dict[str, EquipmentProfile], *, initial: bool = False,
    ) -> None:
        """Apply damage parameters without changing controller commands."""
        for equipment_id, pump in self.pumps.items():
            pump.health.configure(profiles[equipment_id], initial=initial)
        for drive_id, drive in self.drives.items():
            drive.health.configure(profiles[drive_id], initial=initial)

    def light_channel_state(self, zone_id: str) -> dict[str, tuple[int, int, float, float]]:
        """Return role -> (Modbus ID, AO, volts, requested brightness percent)."""
        light = self.lights[zone_id]
        return {
            binding.role: (
                binding.device_id,
                binding.channel,
                self.analog_outputs.get((binding.device_id, binding.channel), 0) / 1000.0,
                brightness_percent(
                    light,
                    self.analog_outputs.get((binding.device_id, binding.channel), 0) / 1000.0,
                ),
            )
            for binding in light.channels
        }

    def light_state(self, zone_id: str) -> tuple[bool, dict[str, float]]:
        light = self.lights[zone_id]
        powered = light.enabled and light.light_type != LightType.NONE and self.relay(light.power_relay)
        values = {role: state[3] for role, state in self.light_channel_state(zone_id).items()}
        return powered, values

    def light_effective(self, zone_id: str) -> bool:
        powered, values = self.light_state(zone_id)
        return powered and any(value > 0 for value in values.values())

    def force_sensor(self, sensor_id: str, value: bool | None) -> None:
        sensor = self.sensors[sensor_id]
        previous = sensor.value
        sensor.forced = value
        mode = "AUTO" if value is None else f"FORCE {'ON' if value else 'OFF'}"
        self.event("ОПЕРАТОР", sensor_id, mode)
        self._sensor_changed(sensor, previous)

    def _sensor_changed(self, sensor: LevelSensor, previous: bool, *, notify: bool = True) -> bool:
        if sensor.value == previous:
            return False
        self.event(
            "ДАТЧИК", sensor.id,
            f"{'ВКЛ' if previous else 'ВЫКЛ'} -> {'ВКЛ' if sensor.value else 'ВЫКЛ'}",
        )
        if notify:
            self.sensor_change()
        return True

    def refresh_sensor(self, sensor_id: str, elapsed_s: float = 0.0) -> None:
        """Recalculate one level sensor and notify the physical bridge on an edge."""
        self.refresh_sensors(elapsed_s, (sensor_id,))

    def refresh_sensors(
        self, elapsed_s: float = 0.0,
        sensor_ids: tuple[str, ...] | None = None,
    ) -> None:
        """Recalculate sensors as one image and emit one bridge notification."""
        changed = False
        for sensor_id in sensor_ids or tuple(self.sensors):
            sensor = self.sensors[sensor_id]
            previous = sensor.value
            sensor.update(self.tanks[sensor.tank_id].volume_l, elapsed_s)
            changed |= self._sensor_changed(sensor, previous, notify=False)
        if changed:
            self.sensor_change()

    def set_tank_level(self, tank_id: str, value: float, *, percent: bool = False) -> None:
        tank = self.tanks[tank_id]
        litres = tank.capacity_l * value / 100.0 if percent else value
        if not 0 <= litres <= tank.capacity_l:
            raise ValueError(f"Уровень должен быть в диапазоне 0..{tank.capacity_l:g} л")
        old = tank.volume_l
        if litres < old:
            tank.take_solution(old - litres)
        elif litres > old:
            tank.add_solution(tank.sample(litres - old))
        self.event("ОПЕРАТОР", tank_id, f"уровень {old:.2f} -> {litres:.2f} л")
        sensor_ids = tuple(sensor_id for sensor_id, sensor in self.sensors.items() if sensor.tank_id == tank_id)
        self.refresh_sensors(sensor_ids=sensor_ids)

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
        self._hydraulic_signature = None
        self._valve_response_remaining_s = 0.0
        self._spike_remaining_s = 0.0
        self._alarm("PIPE_RUPTURE", "pipe", False)
        self.event("ОПЕРАТОР", "pipe", "виртуальный трубопровод отремонтирован")

    def _add_solution(self, tank_id: str, parcel: SolutionParcel) -> None:
        overflow = self.tanks[tank_id].add_solution(parcel)
        if overflow > 1e-12:
            self._overflowing.add(tank_id)
        self._alarm("TANK_OVERFLOW", tank_id, overflow > 1e-12)

    def _add(self, tank_id: str, litres: float) -> None:
        self._add_solution(tank_id, self.tanks[tank_id].sample(litres))

    def _transfer(self, pump: TransferPump, dt_s: float) -> None:
        commanded = self.relay(pump.relay)
        flow = pump.update(commanded, dt_s)
        requested = flow * dt_s / 60.0
        parcel = self.tanks[pump.source].take_solution(requested)
        actual = parcel.volume_l
        water_available = not commanded or requested <= 1e-12 or actual + 1e-12 >= requested
        self._update_equipment_health(pump.id, pump.health, commanded, water_available, dt_s)
        pump.actual_flow_lpm = actual * 60.0 / max(dt_s, 1e-9)
        self.tanks[pump.source].outflow_lpm += actual * 60.0 / max(dt_s, 1e-9)
        self.tanks[pump.destination].inflow_lpm += actual * 60.0 / max(dt_s, 1e-9)
        pump.total_l += actual
        self._add_solution(pump.destination, parcel)
        if requested > 0 and actual <= 1e-12:
            self._alarm("WATER_SHORTAGE", pump.source, True)
        elif self.tanks[pump.source].volume_l > 0:
            self._alarm("WATER_SHORTAGE", pump.source, False)

    def _update_equipment_health(
        self, equipment_id: str, health: EquipmentHealth, commanded: bool,
        water_available: bool, dt_s: float,
    ) -> None:
        previous_state, previous_warning = health.update(commanded, water_available, dt_s)
        if health.state != previous_state:
            self.event(
                "ОБОРУДОВАНИЕ", equipment_id,
                f"{previous_state} -> {health.state}; износ {health.damage * 100:.1f}%",
            )
        if health.warning_active and not previous_warning:
            self.event("АВАРИЯ", equipment_id, "достигнут порог сухого хода")
        if health.state == "FAILED" and previous_state != "FAILED" and commanded:
            self.event("ОБОРУДОВАНИЕ", equipment_id, "физический отказ; команда платы остаётся ВКЛ/RUN")
        self._alarm("DRY_RUN", equipment_id, health.dry_running)
        self._alarm("EQUIPMENT_FAILURE", equipment_id, health.failed)

    def apply_ponics_dose(self, reagent: str, millilitres: float) -> None:
        """Apply a PonicPilot dose exclusively to the shared BP solution."""
        tank = self.tanks["bp"]
        if millilitres <= 0:
            return
        effective_volume = max(tank.volume_l, 1e-9)
        if reagent in {"a", "b", "c"}:
            ec_delta = self.fertilizer_ec_per_ml_at_100l * millilitres * 100.0 / effective_volume
            tank.solute_mass += ec_delta * effective_volume
        elif reagent in {"ph_plus", "ph_minus"}:
            direction = 1.0 if reagent == "ph_plus" else -1.0
            ph_delta = direction * self.ph_reagent_delta_per_ml_at_100l * millilitres * 100.0 / effective_volume
            tank.acidity_units -= ph_delta * max(tank.buffer_units, 1e-9)
        else:
            raise ValueError("Неизвестный реагент PonicPilot")

    def selected_sources(self) -> list[str]:
        """Return source tanks whose feed valves are physically open."""
        sources: list[str] = []
        if self.relay(self.outputs["source_osmosis"]):
            sources.append("bo")
        if self.relay(self.outputs["source_broth"]):
            sources.append("bp")
        return sources

    def available_sources(self) -> list[str]:
        """Return selected source tanks which can currently supply water."""
        return [tank_id for tank_id in self.selected_sources() if self.tanks[tank_id].volume_l > 1e-9]

    def drive_commanded(self, drive: Drive) -> bool:
        """Report whether the controller is currently commanding this HP."""
        return drive.commanded(
            self.relay(drive.run_relay), self.relay(drive.selector_relay),
        )

    def drive_input_command(self, drive: Drive) -> bool:
        """Return the selected controller command even when the VFD has tripped."""
        return drive.input_command(
            self.relay(drive.run_relay), self.relay(drive.selector_relay),
        )

    def equipment_health(self, equipment_id: str) -> EquipmentHealth:
        if equipment_id in self.pumps:
            return self.pumps[equipment_id].health
        if equipment_id in self.drives:
            return self.drives[equipment_id].health
        raise ValueError(f"Неизвестное оборудование: {equipment_id}")

    def equipment_commanded(self, equipment_id: str) -> bool:
        if equipment_id in self.pumps:
            return self.relay(self.pumps[equipment_id].relay)
        if equipment_id in self.drives:
            return self.drive_input_command(self.drives[equipment_id])
        raise ValueError(f"Неизвестное оборудование: {equipment_id}")

    def repair_equipment(self, equipment_id: str, *, replace: bool = False) -> bool:
        commanded = self.equipment_commanded(equipment_id)
        health = self.equipment_health(equipment_id)
        if replace:
            health.replace()
            action = "заменено"
        else:
            health.repair()
            action = "отремонтировано"
        self._alarm("EQUIPMENT_FAILURE", equipment_id, False)
        self._alarm("DRY_RUN", equipment_id, False)
        self.event("ОПЕРАТОР", equipment_id, f"оборудование {action}; команда платы не изменена")
        return commanded

    def _blockage_aperture(self) -> float:
        if not self.blockage_enabled:
            return 1.0
        # A narrowing increases resistance approximately with the inverse
        # square of its effective opening. HIGH is fixed upstream of it.
        return max(0.1, 1.0 - 0.55 * self.blockage_severity / 100.0)

    def _pressure_target(self, open_tiers: int) -> float:
        aperture = self._blockage_aperture()
        self.hydraulic_resistance = 1.0 / (aperture * aperture)
        drive = max(self.drives.values(), key=lambda item: item.actual_hz * item.hydraulic_factor)
        if (
            drive.actual_hz <= 0.1
            or not self.drive_commanded(drive)
            or self.low_pressure_bar <= 0.1
            or not self.available_sources()
        ):
            return 0.0
        if self.pipe_ruptured:
            return min(3.0, max(0.0, self.rupture_residual_bar))
        calibrated = max(0.0, 30.0 + (drive.actual_hz - 29.0) * (27.0 / 13.0))
        effective_paths = open_tiers / self.hydraulic_resistance
        shutoff = min(
            self.pressure_max_bar,
            max(0.0, self.closed_head_pressure_bar * drive.actual_hz / 45.0),
        )
        if effective_paths <= 3.0:
            load = (1.0 - max(0.0, effective_paths) / 3.0) ** 1.5
            pressure = calibrated + (shutoff - calibrated) * load
        else:
            pressure = calibrated * sqrt(3.0 / effective_paths)
        supply_factor = min(
            1.0,
            self.low_pressure_bar / max(self.boost_pressure_bar, 1e-9),
        )
        pressure *= supply_factor * drive.hydraulic_factor
        if self.leak_enabled:
            pressure *= max(0.05, 1.0 - self.leak_pressure_factor)
        return min(self.pressure_max_bar, pressure)

    def _hydraulic_state(self, active_tiers: list[Tier]) -> tuple[object, ...]:
        return (
            tuple(tier.id for tier in active_tiers),
            self.relay(self.outputs["boost"]),
            tuple(self.selected_sources()),
            self.blockage_enabled,
            round(self.blockage_severity, 6),
        )

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
        buffer_units = self.osmosis_profile["buffer"] * filled
        self._add_solution("bo", SolutionParcel(
            filled,
            self.osmosis_profile["ec"] * filled,
            (7.0 - self.osmosis_profile["ph"]) * buffer_units,
            buffer_units,
            self.osmosis_profile["temperature"] * filled,
        ))

        for pump in self.pumps.values():
            self._transfer(pump, dt_s)

        for drive in self.drives.values():
            drive.update(self.relay(drive.run_relay), self.relay(drive.selector_relay), dt_s)

        boost_has_water = bool(self.available_sources())
        boost_target = (
            self.boost_pressure_bar
            if self.relay(self.outputs["boost"]) and boost_has_water
            else 0.0
        )
        self.low_pressure_bar = self._smooth(
            self.low_pressure_bar, boost_target, self.boost_rise_s, self.boost_fall_s, dt_s
        )

        hp_water_available = self.relay(self.outputs["boost"]) and boost_has_water
        for drive in self.drives.values():
            self._update_equipment_health(
                drive.id, drive.health, drive.actual_hz > 0.1,
                hp_water_available, dt_s,
            )

        active_tiers = [tier for tier in self.tiers.values() if self.relay(tier.relay)]
        pressure_target = self._pressure_target(len(active_tiers))
        self.pressure_target_bar = pressure_target
        pump_running = max((drive.actual_hz for drive in self.drives.values()), default=0.0) > 0.1
        pump_pressurizing = any(
            drive.actual_hz > 0.1 and drive.hydraulic_factor > 0 and self.drive_commanded(drive)
            for drive in self.drives.values()
        )
        hydraulic_signature = self._hydraulic_state(active_tiers)
        hydraulic_changed = (
            self._hydraulic_signature is not None
            and hydraulic_signature != self._hydraulic_signature
            and self._pressure_pump_running
            and pump_running
        )
        if hydraulic_changed:
            closing = pressure_target > self.high_pressure_bar
            response_ms = (
                self.valve_pressure_close_response_ms
                if closing else self.valve_pressure_response_ms
            )
            self._valve_response_remaining_s = response_ms / 1000.0
            self.last_pressure_spike_bar = 0.0
            if closing and self.transient_pressure_spike_coefficient > 0:
                self.last_pressure_spike_bar = max(
                    0.0,
                    pressure_target - self.high_pressure_bar,
                ) * self.transient_pressure_spike_coefficient
                self._spike_remaining_s = self.transient_pressure_spike_duration_ms / 1000.0
        self._hydraulic_signature = hydraulic_signature
        self._pressure_pump_running = pump_running

        spike = self.last_pressure_spike_bar if self._spike_remaining_s > 0 else 0.0
        rupture_pressure = pressure_target + spike
        self.max_pressure_bar = max(self.max_pressure_bar, self.high_pressure_bar, rupture_pressure)
        if not self.pipe_ruptured and rupture_pressure >= self.rupture_threshold_bar:
            self.pipe_ruptured = True
            self._alarm("PIPE_RUPTURE", "pipe", True)
            pressure_target = min(3.0, max(0.0, self.rupture_residual_bar))
            self.pressure_target_bar = pressure_target
            self._spike_remaining_s = 0.0
            spike = 0.0
        displayed_target = pressure_target + spike
        if self.pipe_ruptured:
            displayed_target = min(3.0, max(0.0, self.rupture_residual_bar)) if pump_pressurizing else 0.0
        if self._valve_response_remaining_s > 0 or self.pipe_ruptured:
            response_s = min(
                self._valve_response_remaining_s or 0.2,
                0.2 if self.pipe_ruptured else float("inf"),
            )
            rise_s = fall_s = response_s
        else:
            rise_s, fall_s = self.pressure_rise_s, self.pressure_fall_s
        self.high_pressure_bar = self._smooth(
            self.high_pressure_bar, displayed_target, rise_s, fall_s, dt_s,
        )
        self.max_pressure_bar = max(self.max_pressure_bar, self.high_pressure_bar)
        self._valve_response_remaining_s = max(0.0, self._valve_response_remaining_s - dt_s)
        self._spike_remaining_s = max(0.0, self._spike_remaining_s - dt_s)

        source_bo = self.relay(self.outputs["source_osmosis"])
        source_bp = self.relay(self.outputs["source_broth"])
        self.hydraulic_uncertainty = source_bo and source_bp
        scale = max(
            (drive.actual_hz * drive.hydraulic_factor for drive in self.drives.values()),
            default=0.0,
        ) / 29.0
        if self.pipe_ruptured:
            scale *= 0.1
        scale *= self._blockage_aperture()
        requested_l = sum(tier.flow_lpm for tier in active_tiers) * scale * dt_s / 60.0
        shares = self.available_sources() if self.relay(self.outputs["boost"]) else []
        delivered = 0.0
        delivered_solution = SolutionParcel(0.0, 0.0, 0.0, 0.0, 0.0)
        if shares and max((d.actual_hz for d in self.drives.values()), default=0.0) > 0.1:
            for tank_id in shares:
                parcel = self.tanks[tank_id].take_solution(requested_l / len(shares))
                delivered += parcel.volume_l
                delivered_solution.volume_l += parcel.volume_l
                delivered_solution.solute_mass += parcel.solute_mass
                delivered_solution.acidity_units += parcel.acidity_units
                delivered_solution.buffer_units += parcel.buffer_units
                delivered_solution.heat_c_l += parcel.heat_c_l
                self.tanks[tank_id].outflow_lpm += parcel.volume_l * 60.0 / max(dt_s, 1e-9)
        ratio = delivered / requested_l if requested_l else 0.0
        for tier in self.tiers.values():
            tier.actual_flow_lpm = tier.flow_lpm * scale * ratio if tier in active_tiers else 0.0
            amount = tier.actual_flow_lpm * dt_s / 60.0
            tier.total_l += amount
            returned = amount * tier.return_fraction
            loss = amount - returned
            tier.loss_l += loss
            self.total_irrigation_loss_l += loss
            if returned and delivered > 1e-12:
                incoming = delivered_solution.scaled(amount / delivered)
                return_fraction = returned / max(amount, 1e-12)
                nutrient_loss_fraction = min(
                    1.0, self.nutrient_absorption_fraction + self.deposition_fraction
                )
                returned_solution = incoming.scaled(return_fraction)
                # Evaporated water concentrates the non-consumed nutrients in
                # the returning fraction; uptake and deposition are separate.
                returned_solution.solute_mass = incoming.solute_mass * (1.0 - nutrient_loss_fraction)
                consumed = incoming.solute_mass * self.nutrient_absorption_fraction
                self.tanks[tier.drain_tank].nutrients_consumed += consumed
                returned_solution.acidity_units -= (
                    self.ph_drift_per_pass * returned_solution.buffer_units
                )
                tier._returns.append((tier.return_delay_s, returned_solution))
            pending: deque[tuple[float, SolutionParcel]] = deque()
            while tier._returns:
                delay, parcel = tier._returns.popleft()
                if delay <= dt_s:
                    self._add_solution(tier.drain_tank, parcel)
                    self.tanks[tier.drain_tank].inflow_lpm += parcel.volume_l * 60.0 / max(dt_s, 1e-9)
                else:
                    pending.append((delay - dt_s, parcel))
            tier._returns = pending

        self.calculated_flow_lpm = sum(tier.actual_flow_lpm for tier in self.tiers.values())

        leak_flow = self.leak_rate_lpm if self.leak_enabled and self.high_pressure_bar > 0.1 else 0.0
        if self.pipe_ruptured and self.high_pressure_bar > 0.1:
            leak_flow += max(20.0, requested_l * 60.0 / max(dt_s, 1e-9))
        leak_l = leak_flow * dt_s / 60.0
        if shares and leak_l:
            actual_leak = 0.0
            for tank_id in shares:
                parcel = self.tanks[tank_id].take_solution(leak_l / len(shares))
                actual_leak += parcel.volume_l
                self.tanks[tank_id].outflow_lpm += parcel.volume_l * 60.0 / max(dt_s, 1e-9)
            self.total_leak_l += actual_leak

        self.refresh_sensors(dt_s)
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
