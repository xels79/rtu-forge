"""Named simulation checkpoints, deliberately separate from configuration."""

from __future__ import annotations

import json
import os
import re
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .bionic_model import Alarm, AlarmState, BionicModel, SolutionParcel


STATE_VERSION = 1
RUNTIME_STATE_FILENAME = "bionic-runtime-state.json"
STATE_NAME = re.compile(r"^[\w.-]{1,64}$", re.UNICODE)
TANK_FIELDS = (
    "volume_l", "inflow_lpm", "outflow_lpm", "total_loss_l", "overflow_l",
    "solute_mass", "acidity_units", "buffer_units", "heat_c_l", "nutrients_consumed",
)
HEALTH_FIELDS = (
    "state", "dry_running", "dry_run_s", "total_dry_run_s", "heat", "damage",
    "failure", "warning_active", "replacements",
)


def validate_state_name(name: str) -> str:
    if not STATE_NAME.fullmatch(name) or name in {".", ".."}:
        raise ValueError("Имя состояния: 1..64 буквы, цифры, '_', '-' или '.', без пути")
    return name


def state_path(directory: Path, name: str) -> Path:
    return directory / f"{validate_state_name(name)}.json"


def runtime_state_path(home: Path) -> Path:
    """Return the automatic physical-state file outside named checkpoints."""
    return home / RUNTIME_STATE_FILENAME


def _health(model: BionicModel, equipment_id: str) -> dict[str, Any]:
    health = model.equipment_health(equipment_id)
    return {field: getattr(health, field) for field in HEALTH_FIELDS}


def capture_state(model: BionicModel) -> dict[str, Any]:
    """Capture physical state without controller-owned DO/AO/Modbus commands."""
    return {
        "format_version": STATE_VERSION,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "simulation": {
            "running": model.running, "paused": model.paused, "speed": model.speed,
        },
        "tanks": {
            tank_id: {field: getattr(tank, field) for field in TANK_FIELDS}
            for tank_id, tank in model.tanks.items()
        },
        "sensors": {
            sensor_id: {
                "forced": sensor.forced, "automatic": sensor.automatic,
                "candidate": sensor._candidate, "candidate_s": sensor._candidate_s,
            }
            for sensor_id, sensor in model.sensors.items()
        },
        "equipment": {
            equipment_id: _health(model, equipment_id)
            for equipment_id in (*model.pumps, *model.drives)
        },
        "pumps": {
            pump_id: {
                "actual_flow_lpm": pump.actual_flow_lpm, "total_l": pump.total_l,
                "coefficient": pump.coefficient,
            }
            for pump_id, pump in model.pumps.items()
        },
        "tiers": {
            tier_id: {
                "actual_flow_lpm": tier.actual_flow_lpm, "total_l": tier.total_l,
                "loss_l": tier.loss_l,
                "returns": [
                    [delay, {
                        "volume_l": parcel.volume_l, "solute_mass": parcel.solute_mass,
                        "acidity_units": parcel.acidity_units,
                        "buffer_units": parcel.buffer_units, "heat_c_l": parcel.heat_c_l,
                    }]
                    for delay, parcel in tier._returns
                ],
            }
            for tier_id, tier in model.tiers.items()
        },
        "drives": {
            drive_id: {
                "actual_hz": drive.actual_hz, "motor_hours": drive.motor_hours,
                "fault": drive.fault, "online": drive.online,
                "calculated_current_a": drive.calculated_current_a,
                "calculated_load": drive.calculated_load,
                "overload_elapsed_s": drive.overload_elapsed_s,
                "protection_state": drive.protection_state,
            }
            for drive_id, drive in model.drives.items()
        },
        "hydraulics": {
            "water_supply_available": model.water_supply_available,
            "fill_valve_stuck_open": model.fill_valve_stuck_open,
            "low_pressure_bar": model.low_pressure_bar,
            "high_pressure_bar": model.high_pressure_bar,
            "pressure_target_bar": model.pressure_target_bar,
            "last_pressure_spike_bar": model.last_pressure_spike_bar,
            "max_pressure_bar": model.max_pressure_bar,
            "calculated_flow_lpm": model.calculated_flow_lpm,
            "current_leak_flow_lpm": model.current_leak_flow_lpm,
            "hydraulic_resistance": model.hydraulic_resistance,
            "pipe_ruptured": model.pipe_ruptured,
            "leak_enabled": model.leak_enabled,
            "blockage_enabled": model.blockage_enabled,
            "blockage_severity": model.blockage_severity,
            "leak_rate_lpm": model.leak_rate_lpm,
            "rupture_threshold_bar": model.rupture_threshold_bar,
            "total_leak_l": model.total_leak_l,
            "total_irrigation_loss_l": model.total_irrigation_loss_l,
            "total_plant_water_uptake_l": model.total_plant_water_uptake_l,
            "total_irrigation_evaporation_l": model.total_irrigation_evaporation_l,
            "water_meter_flow_lpm": model.water_meter.flow_lpm,
            "water_meter_total_l": model.water_meter.total_l,
            "water_meter_status": model.water_meter.status,
            "valve_response_remaining_s": model._valve_response_remaining_s,
            "spike_remaining_s": model._spike_remaining_s,
            "pressure_pump_running": model._pressure_pump_running,
            "overflowing": sorted(model._overflowing),
        },
        "alarms": [
            {
                "code": alarm.code, "subject": alarm.subject, "state": alarm.state.value,
                "first_at": alarm.first_at.isoformat(), "acknowledged": alarm.acknowledged,
            }
            for alarm in model.alarms.values()
        ],
        "ponics": {
            "dosing_totals": dict(model.ponics.dosing_totals),
            "discrete_inputs": model.ponics.discrete_inputs,
            "discrete_outputs": model.ponics.discrete_outputs,
            "sensor_faults": dict(model.ponics.sensor_faults),
            "doser_faults": dict(model.ponics.doser_faults),
            "respond": model.ponics.respond,
            "requests": model.ponics.requests, "responses": model.ponics.responses,
            "crc_errors": model.ponics.crc_errors,
            "function_errors": model.ponics.function_errors,
            "address_errors": model.ponics.address_errors,
            "last_success_at": model.ponics.last_success_at,
            "last_read_range": model.ponics.last_read_range,
            "last_written_register": model.ponics.last_written_register,
            "register_sources": list(model.ponics.register_sources),
            "register_changed_at": list(model.ponics.register_changed_at),
        },
    }


def _require_mapping(data: Any, key: str) -> dict[str, Any]:
    value = data.get(key) if isinstance(data, dict) else None
    if not isinstance(value, dict):
        raise ValueError(f"Состояние повреждено: отсутствует объект {key}")
    return value


def restore_state(model: BionicModel, data: dict[str, Any]) -> None:
    """Restore physical state while preserving current controller output commands."""
    if data.get("format_version") != STATE_VERSION:
        raise ValueError(f"Неподдерживаемая версия состояния: {data.get('format_version')}")
    tanks = _require_mapping(data, "tanks")
    equipment = _require_mapping(data, "equipment")
    if set(tanks) != set(model.tanks) or set(equipment) != {*model.pumps, *model.drives}:
        raise ValueError("Состояние не соответствует составу модели")
    # Validate all mandatory sections before changing the live model.
    for key in ("sensors", "pumps", "tiers", "drives", "hydraulics", "ponics", "simulation"):
        _require_mapping(data, key)
    if not isinstance(data.get("alarms"), list):
        raise ValueError("Состояние повреждено: отсутствует список alarms")

    for tank_id, values in tanks.items():
        tank = model.tanks[tank_id]
        for field in TANK_FIELDS:
            setattr(tank, field, values[field])
    for sensor_id, values in data["sensors"].items():
        sensor = model.sensors[sensor_id]
        sensor.forced = values["forced"]
        sensor.automatic = values["automatic"]
        sensor._candidate = values["candidate"]
        sensor._candidate_s = values["candidate_s"]
    for equipment_id, values in equipment.items():
        health = model.equipment_health(equipment_id)
        for field in HEALTH_FIELDS:
            setattr(health, field, values[field])
    for pump_id, values in data["pumps"].items():
        pump = model.pumps[pump_id]
        for field in ("actual_flow_lpm", "total_l", "coefficient"):
            setattr(pump, field, values[field])
    for tier_id, values in data["tiers"].items():
        tier = model.tiers[tier_id]
        tier.actual_flow_lpm, tier.total_l, tier.loss_l = (
            values["actual_flow_lpm"], values["total_l"], values["loss_l"],
        )
        tier._returns.clear()
        for delay, parcel in values["returns"]:
            tier._returns.append((delay, SolutionParcel(**parcel)))
    for drive_id, values in data["drives"].items():
        drive = model.drives[drive_id]
        for field in (
            "actual_hz", "motor_hours", "fault", "online", "calculated_current_a",
            "calculated_load", "overload_elapsed_s", "protection_state",
        ):
            setattr(drive, field, values[field])
    hydraulics = data["hydraulics"]
    for field in (
        "water_supply_available", "fill_valve_stuck_open", "low_pressure_bar",
        "high_pressure_bar", "pressure_target_bar", "last_pressure_spike_bar",
        "max_pressure_bar", "calculated_flow_lpm", "hydraulic_resistance",
        "pipe_ruptured", "leak_enabled", "blockage_enabled", "total_leak_l",
        "total_irrigation_loss_l", "blockage_severity", "leak_rate_lpm",
        "rupture_threshold_bar",
    ):
        setattr(model, field, hydraulics[field])
    model.water_meter.flow_lpm = hydraulics["water_meter_flow_lpm"]
    model.water_meter.total_l = hydraulics["water_meter_total_l"]
    model.water_meter.status = hydraulics["water_meter_status"]
    model.current_leak_flow_lpm = hydraulics.get("current_leak_flow_lpm", 0.0)
    model.total_plant_water_uptake_l = hydraulics.get("total_plant_water_uptake_l", 0.0)
    model.total_irrigation_evaporation_l = hydraulics.get(
        "total_irrigation_evaporation_l", 0.0,
    )
    model._valve_response_remaining_s = hydraulics["valve_response_remaining_s"]
    model._spike_remaining_s = hydraulics["spike_remaining_s"]
    model._pressure_pump_running = hydraulics["pressure_pump_running"]
    model._overflowing = set(hydraulics["overflowing"])
    model.alarms.clear()
    for values in data["alarms"]:
        alarm = Alarm(
            values["code"], values["subject"], AlarmState(values["state"]),
            datetime.fromisoformat(values["first_at"]), values["acknowledged"],
        )
        model.alarms[(alarm.code, alarm.subject)] = alarm
    ponics = data["ponics"]
    model.ponics.dosing_totals.update(ponics["dosing_totals"])
    model.ponics.sensor_faults.update(ponics["sensor_faults"])
    model.ponics.doser_faults.update(ponics["doser_faults"])
    for field in (
        "discrete_inputs", "discrete_outputs", "respond", "requests", "responses",
        "crc_errors", "function_errors", "address_errors",
        "last_success_at", "last_written_register",
    ):
        setattr(model.ponics, field, ponics[field])
    model.ponics.last_read_range = (
        tuple(ponics["last_read_range"]) if ponics["last_read_range"] is not None else None
    )
    model.ponics.register_sources = list(ponics["register_sources"])
    model.ponics.register_changed_at = list(ponics["register_changed_at"])
    simulation = data["simulation"]
    model.running = bool(simulation["running"])
    model.paused = bool(simulation["paused"])
    model.speed = float(simulation.get("speed", model.speed))
    model._hydraulic_signature = None
    model.sensor_change()


def save_state(path: Path, model: BionicModel) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(capture_state(model), ensure_ascii=False, indent=2)
    temp_name: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
            "w", encoding="utf-8", newline="", delete=False,
            dir=path.parent, prefix=f".{path.name}.", suffix=".tmp",
        ) as stream:
            temp_name = stream.name
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp_name, path)
    except Exception:
        if temp_name:
            Path(temp_name).unlink(missing_ok=True)
        raise


def load_state(path: Path, model: BionicModel) -> None:
    if not path.exists():
        raise ValueError(f"Состояние не найдено: {path.stem}")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"Не удалось прочитать состояние {path.stem}: {exc}") from None
    try:
        restore_state(model, data)
    except ValueError:
        raise
    except (KeyError, TypeError, AttributeError) as exc:
        raise ValueError(f"Состояние повреждено: {exc}") from None


def list_states(directory: Path) -> list[str]:
    if not directory.exists():
        return []
    return sorted(path.stem for path in directory.glob("*.json") if STATE_NAME.fullmatch(path.stem))
