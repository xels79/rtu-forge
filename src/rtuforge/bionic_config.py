"""Configuration loading and validation for Bionic Immitator."""

from __future__ import annotations

import configparser
import io
import os
import re
import shutil
import tempfile
from dataclasses import dataclass, fields, replace
from pathlib import Path

from .bionic_equipment import FACTORY_EQUIPMENT_PROFILE, parse_equipment_profile
from .bionic_idd import validate_idd_parameter
from .bionic_lights import FACTORY_LIGHT_PROFILE, parse_light_profile, validate_light_profile


@dataclass(frozen=True)
class BionicSettings:
    controller_port: str = "COM1"
    controller_baudrate: int = 9600
    controller_parity: str = "N"
    controller_stopbits: float = 1.0
    sensor_relay_port: str = "COM2"
    sensor_relay_baudrate: int = 9600
    sensor_relay_parity: str = "N"
    sensor_relay_stopbits: float = 1.0
    sensor_relay_id: int = 1
    sensor_relay_channels: int = 8
    sensor_relay_active_low: bool = False
    sensor_relay_contact: str = "NO"
    sensor_relay_map: str = "bo-min:1,bo-max:2,bp-min:3,bp-max:4,bso1-min:5,bso1-max:6,bso2-min:7,bso2-max:8"
    sensor_relay_loss_behavior: str = "unknown"
    hardware_mode: bool = False
    relay_address: int = 1
    ao1_address: int = 2
    ao2_address: int = 3
    ao3_address: int = 4
    ai_address: int = 6
    ponics_address: int = 5
    hp1_address: int = 7
    hp2_address: int = 8
    pulsar_enabled: bool = False
    pulsar_address: str = "00000001"
    model_interval_ms: int = 50
    ui_interval_ms: int = 500
    retention_days: int = 7
    bo_capacity_l: float = 500.0
    bp_capacity_l: float = 500.0
    bso1_capacity_l: float = 200.0
    bso2_capacity_l: float = 200.0
    bo_initial_l: float = 250.0
    bp_initial_l: float = 250.0
    bso1_initial_l: float = 20.0
    bso2_initial_l: float = 20.0
    bo_min_threshold_l: float = 100.0
    bo_max_threshold_l: float = 400.0
    bp_min_threshold_l: float = 100.0
    bp_max_threshold_l: float = 400.0
    bso1_min_threshold_l: float = 40.0
    bso1_max_threshold_l: float = 160.0
    bso2_min_threshold_l: float = 40.0
    bso2_max_threshold_l: float = 160.0
    fill_flow_lpm: float = 3.0
    water_meter_initial_l: float = 0.0
    bo_to_bp_flow_lpm: float = 10.0
    bso1_to_bp_flow_lpm: float = 8.0
    bso2_to_bp_flow_lpm: float = 8.0
    rack1_tier_flow_lpm: float = 2.0
    rack2_tier_flow_lpm: float = 2.0
    return_fraction: float = 0.8
    return_delay_s: float = 5.0
    plant_water_uptake_fraction: float = 0.005
    irrigation_evaporation_fraction: float = 0.002
    sensor_hysteresis_l: float = 0.0
    sensor_delay_s: float = 0.0
    boost_pressure_bar: float = 2.0
    boost_rise_s: float = 2.0
    boost_fall_s: float = 2.0
    pressure_rise_s: float = 5.0
    pressure_fall_s: float = 4.0
    valve_pressure_response_ms: int = 200
    valve_pressure_close_response_ms: int = 200
    transient_pressure_spike_coefficient: float = 0.0
    transient_pressure_spike_duration_ms: int = 100
    closed_head_pressure_bar: float = 90.0
    pressure_max_bar: float = 90.0
    rupture_threshold_bar: float = 75.0
    rupture_residual_bar: float = 2.0
    leak_rate_lpm: float = 12.0
    leak_pressure_factor: float = 0.25
    blockage_severity: float = 70.0
    light_profile: str = FACTORY_LIGHT_PROFILE
    equipment_profile: str = FACTORY_EQUIPMENT_PROFILE
    ponics_irrigation_on_s: int = 60
    ponics_irrigation_pause_s: int = 300
    ponics_mode: int = 0
    ponics_ph_enabled: bool = False
    ponics_ph_dosing_pause_s: int = 60
    ponics_ph_low: float = 5.5
    ponics_ph_high: float = 6.5
    ponics_ec_enabled: bool = False
    ponics_ec_protection_enabled: bool = False
    ponics_ec_dosing_pause_s: int = 60
    ponics_ec_program: int = 0
    ponics_ec_target_ms_cm: float = 2.0
    ponics_fertilizer_a_share: int = 33
    ponics_fertilizer_b_share: int = 33
    ponics_fertilizer_c_share: int = 34
    ponics_thermostat_enabled: bool = False
    ponics_temperature_low_c: int = 18
    ponics_temperature_high_c: int = 24
    tap_ec_ms_cm: float = 0.5
    tap_ph: float = 7.2
    tap_temperature_c: float = 18.0
    tap_buffer_per_l: float = 0.8
    osmosis_ec_ms_cm: float = 0.1
    osmosis_ph: float = 6.8
    osmosis_temperature_c: float = 20.0
    osmosis_buffer_per_l: float = 0.3
    broth_initial_ec_ms_cm: float = 2.0
    broth_initial_ph: float = 6.0
    broth_initial_temperature_c: float = 20.0
    broth_buffer_per_l: float = 1.0
    drain_initial_ec_ms_cm: float = 1.8
    drain_initial_ph: float = 6.1
    drain_initial_temperature_c: float = 20.0
    drain_buffer_per_l: float = 0.8
    nutrient_absorption_fraction: float = 0.05
    deposition_fraction: float = 0.01
    ph_drift_per_pass: float = 0.02
    fertilizer_ec_per_ml_at_100l: float = 0.01
    ph_reagent_delta_per_ml_at_100l: float = 0.02
    hp1_ramp_up_s: float = 5.0
    hp1_ramp_down_s: float = 5.0
    hp1_pb00: int = 290
    hp1_pb01: int = 5
    hp1_pb02: int = 2
    hp1_pb05: int = 500
    hp1_pb06: int = 200
    hp1_pc12: int = 1460
    hp1_pc15: int = 500
    hp1_ph00: int = 1
    hp1_ph01: int = 3
    hp1_nominal_current_a: float = 16.0
    hp1_no_load_current_a: float = 4.0
    hp1_pump_load_coefficient: float = 1.0
    hp1_jam_current_multiplier: float = 2.0
    hp1_overload_trip_s: float = 60.0
    hp1_overload_protection_enabled: bool = True
    hp1_overload_threshold_multiplier: float = 1.5
    hp1_protection_behavior: str = "latched_reset"
    hp2_ramp_up_s: float = 5.0
    hp2_ramp_down_s: float = 5.0
    hp2_pb00: int = 290
    hp2_pb01: int = 5
    hp2_pb02: int = 2
    hp2_pb05: int = 500
    hp2_pb06: int = 200
    hp2_pc12: int = 1460
    hp2_pc15: int = 500
    hp2_ph00: int = 1
    hp2_ph01: int = 3
    hp2_nominal_current_a: float = 16.0
    hp2_no_load_current_a: float = 4.0
    hp2_pump_load_coefficient: float = 1.0
    hp2_jam_current_multiplier: float = 2.0
    hp2_overload_trip_s: float = 60.0
    hp2_overload_protection_enabled: bool = True
    hp2_overload_threshold_multiplier: float = 1.5
    hp2_protection_behavior: str = "latched_reset"
    simulation_speed: float = 1.0


def _section(name: str) -> str:
    if name.startswith("pulsar_"):
        return "pulsar"
    if name in {"hp1_address", "hp2_address"}:
        return "devices"
    if name.startswith("hp1_"):
        return "drive_hp1"
    if name.startswith("hp2_"):
        return "drive_hp2"
    if any(token in name for token in ("port", "baudrate", "parity", "stopbits")):
        return "serial"
    if name == "ponics_address":
        return "ponics"
    if name.startswith("ponics_"):
        return "ponics"
    if name.startswith(("tap_", "osmosis_", "broth_", "drain_", "nutrient_", "deposition_", "ph_drift_", "fertilizer_", "ph_reagent_")):
        return "ponics_chemistry"
    if name.endswith("_address") or name.startswith("sensor_relay"):
        return "devices"
    if name.endswith("_threshold_l") or name.startswith("sensor_"):
        return "sensors"
    if name == "equipment_profile":
        return "equipment"
    if name.startswith(("bo_", "bp_", "bso1_", "bso2_", "fill_", "water_meter_")):
        return "tanks"
    if name.startswith(("rack", "return_", "plant_water_", "irrigation_evaporation_")):
        return "irrigation"
    if name.startswith(("boost_", "pressure_", "valve_pressure_", "transient_pressure_", "closed_head_", "rupture_")):
        return "pressure"
    if name.startswith(("leak_", "blockage_")):
        return "faults"
    if name == "light_profile":
        return "lighting"
    return "simulation"


OPTION_SPECS: dict[str, tuple[str, str]] = {
    field.name: (_section(field.name), field.type if isinstance(field.type, str) else field.type.__name__)
    for field in fields(BionicSettings)
}


def parse_sensor_relay_map(value: str) -> dict[str, int]:
    """Parse the configured sensor-to-physical-channel mapping."""
    try:
        return {
            sensor.strip(): int(channel)
            for item in value.split(",")
            for sensor, channel in [item.split(":", 1)]
        }
    except (ValueError, TypeError):
        raise ValueError("Карта реле должна иметь вид sensor:channel,sensor:channel") from None


def validate_settings(settings: BionicSettings, *, validate_lights: bool = True) -> None:
    if not re.fullmatch(r"[0-9]{8}", settings.pulsar_address):
        raise ValueError("Адрес «Пульсар» должен состоять ровно из 8 десятичных цифр BCD")
    addresses = {
        name: getattr(settings, name)
        for name in ("relay_address", "ao1_address", "ao2_address", "ao3_address", "ponics_address", "ai_address", "hp1_address", "hp2_address")
    }
    if any(not 1 <= value <= 247 for value in addresses.values()):
        raise ValueError("Адреса виртуальных Modbus-устройств должны быть в диапазоне 1..247")
    if settings.ponics_address != 5:
        raise ValueError("PonicPilot Bionic Mini жёстко использует Modbus ID 5")
    if len(set(addresses.values())) != len(addresses):
        raise ValueError("Адреса виртуальных Modbus-устройств на USB №1 не должны совпадать")
    if settings.sensor_relay_id not in range(1, 248):
        raise ValueError("Modbus ID физического реле должен быть в диапазоне 1..247")
    if settings.sensor_relay_channels not in {8, 16}:
        raise ValueError("Физическое реле должно иметь 8 или 16 каналов")
    if settings.sensor_relay_loss_behavior not in {"hold", "unknown"}:
        raise ValueError("Поведение при потере связи должно быть hold или unknown")
    if settings.sensor_relay_contact not in {"NO", "NC"}:
        raise ValueError("Контакт физического реле должен быть NO или NC")
    mapping = parse_sensor_relay_map(settings.sensor_relay_map)
    expected = {"bo-min", "bo-max", "bp-min", "bp-max", "bso1-min", "bso1-max", "bso2-min", "bso2-max"}
    if set(mapping) != expected or len(set(mapping.values())) != len(mapping) or any(not 1 <= value <= settings.sensor_relay_channels for value in mapping.values()):
        raise ValueError("Карта реле должна назначать все 8 датчиков уникальным допустимым каналам")
    if settings.controller_port.casefold() == settings.sensor_relay_port.casefold():
        raise ValueError("USB №1 и USB №2 не могут использовать один COM-порт")
    if settings.model_interval_ms <= 0 or settings.ui_interval_ms <= 0:
        raise ValueError("Интервалы модели и интерфейса должны быть больше нуля")
    capacities = {
        "bo": settings.bo_capacity_l, "bp": settings.bp_capacity_l,
        "bso1": settings.bso1_capacity_l, "bso2": settings.bso2_capacity_l,
    }
    initials = {
        "bo": settings.bo_initial_l, "bp": settings.bp_initial_l,
        "bso1": settings.bso1_initial_l, "bso2": settings.bso2_initial_l,
    }
    if any(value <= 0 for value in capacities.values()):
        raise ValueError("Ёмкости баков должны быть больше нуля")
    if any(initials[name] < 0 or initials[name] > capacity for name, capacity in capacities.items()):
        raise ValueError("Начальный объём каждого бака должен находиться между нулём и его ёмкостью")
    for tank_id, capacity in capacities.items():
        minimum = getattr(settings, f"{tank_id}_min_threshold_l")
        maximum = getattr(settings, f"{tank_id}_max_threshold_l")
        if not 0 <= minimum < maximum <= capacity:
            raise ValueError(f"{tank_id}: требуется 0 ≤ MIN < MAX ≤ {capacity:g} л")
    parse_equipment_profile(settings.equipment_profile)
    nonnegative = (
        settings.fill_flow_lpm, settings.water_meter_initial_l,
        settings.bo_to_bp_flow_lpm, settings.bso1_to_bp_flow_lpm,
        settings.bso2_to_bp_flow_lpm, settings.rack1_tier_flow_lpm, settings.rack2_tier_flow_lpm,
        settings.return_delay_s, settings.sensor_hysteresis_l, settings.sensor_delay_s,
        settings.boost_pressure_bar, settings.boost_rise_s, settings.boost_fall_s,
        settings.pressure_rise_s, settings.pressure_fall_s, settings.pressure_max_bar,
        settings.valve_pressure_response_ms, settings.valve_pressure_close_response_ms,
        settings.transient_pressure_spike_coefficient, settings.transient_pressure_spike_duration_ms,
        settings.closed_head_pressure_bar,
        settings.rupture_threshold_bar, settings.rupture_residual_bar, settings.leak_rate_lpm,
    )
    if any(value < 0 for value in nonnegative):
        raise ValueError("Физические расходы, времена и пороги не могут быть отрицательными")
    if not 0 <= settings.return_fraction <= 1 or not 0 <= settings.leak_pressure_factor <= 1:
        raise ValueError("Доли возврата и влияния протечки должны быть в диапазоне 0..1")
    if any(not 0 <= value <= 1 for value in (
        settings.plant_water_uptake_fraction,
        settings.irrigation_evaporation_fraction,
    )):
        raise ValueError("Доли поглощения воды и испарения должны быть в диапазоне 0..1")
    if settings.plant_water_uptake_fraction + settings.irrigation_evaporation_fraction > 1:
        raise ValueError("Сумма долей поглощения воды и испарения не должна превышать 1")
    if not 0 <= settings.blockage_severity <= 100:
        raise ValueError("Степень засора должна быть в диапазоне 0..100")
    if not 0 <= settings.rupture_residual_bar <= 3:
        raise ValueError("Остаточное давление после разрыва должно быть в диапазоне 0..3 бар")
    if validate_lights:
        validate_light_profile(
            parse_light_profile(settings.light_profile),
            {settings.ao1_address, settings.ao2_address, settings.ao3_address},
        )
    if not 0.1 <= settings.simulation_speed <= 100:
        raise ValueError("Скорость симуляции должна быть в диапазоне 0.1..100")
    if settings.ponics_mode not in {0, 2, 3, 4, 5}:
        raise ValueError("Режим PonicPilot должен быть 0, 2, 3, 4 или 5")
    if not 0 <= settings.ponics_ph_low <= settings.ponics_ph_high <= 14:
        raise ValueError("Диапазон pH PonicPilot должен быть упорядочен внутри 0..14")
    if not 0 <= settings.ponics_ec_target_ms_cm <= 20:
        raise ValueError("Целевая EC PonicPilot должна быть в диапазоне 0..20 мСм/см")
    if settings.ponics_ec_program not in range(5):
        raise ValueError("Программа EC PonicPilot должна быть в диапазоне 0..4")
    shares = (
        settings.ponics_fertilizer_a_share,
        settings.ponics_fertilizer_b_share,
        settings.ponics_fertilizer_c_share,
    )
    if any(not 0 <= value <= 99 for value in shares) or sum(shares) <= 0:
        raise ValueError("Доли удобрений PonicPilot должны быть 0..99 и иметь ненулевую сумму")
    if not 0 <= settings.ponics_temperature_low_c <= settings.ponics_temperature_high_c <= 100:
        raise ValueError("Температурный диапазон PonicPilot должен быть упорядочен внутри 0..100 °C")
    chemistry_nonnegative = (
        settings.tap_ec_ms_cm, settings.tap_buffer_per_l, settings.osmosis_ec_ms_cm,
        settings.osmosis_buffer_per_l, settings.broth_initial_ec_ms_cm,
        settings.broth_buffer_per_l, settings.drain_initial_ec_ms_cm,
        settings.drain_buffer_per_l, settings.ph_drift_per_pass,
        settings.fertilizer_ec_per_ml_at_100l, settings.ph_reagent_delta_per_ml_at_100l,
    )
    if any(value < 0 for value in chemistry_nonnegative):
        raise ValueError("Параметры демонстрационной химии не могут быть отрицательными")
    if any(not 0 <= value <= 14 for value in (settings.tap_ph, settings.osmosis_ph, settings.broth_initial_ph, settings.drain_initial_ph)):
        raise ValueError("Начальные значения pH должны быть в диапазоне 0..14")
    if any(not 0 <= value <= 1 for value in (settings.nutrient_absorption_fraction, settings.deposition_fraction)):
        raise ValueError("Доли поглощения и осаждения должны быть в диапазоне 0..1")
    if settings.nutrient_absorption_fraction + settings.deposition_fraction > 1:
        raise ValueError("Сумма поглощения и осаждения не должна превышать 1")
    if min(settings.hp1_ramp_up_s, settings.hp1_ramp_down_s, settings.hp2_ramp_up_s, settings.hp2_ramp_down_s) < 0:
        raise ValueError("Времена разгона и торможения частотников не могут быть отрицательными")
    for prefix in ("hp1", "hp2"):
        drive_config = {
            100: getattr(settings, f"{prefix}_pb00"),
            101: getattr(settings, f"{prefix}_pb01"),
            102: getattr(settings, f"{prefix}_pb02"),
            105: getattr(settings, f"{prefix}_pb05"),
            106: getattr(settings, f"{prefix}_pb06"),
            107: round(getattr(settings, f"{prefix}_ramp_up_s") * 10),
            108: round(getattr(settings, f"{prefix}_ramp_down_s") * 10),
            210: round(getattr(settings, f"{prefix}_nominal_current_a") * 10),
            212: getattr(settings, f"{prefix}_pc12"),
            215: getattr(settings, f"{prefix}_pc15"),
            700: getattr(settings, f"{prefix}_ph00"),
            701: getattr(settings, f"{prefix}_ph01"),
            702: getattr(settings, f"{prefix}_address"),
            816: int(getattr(settings, f"{prefix}_overload_protection_enabled")),
        }
        for address, raw in drive_config.items():
            validate_idd_parameter(address, raw, drive_config)
        if getattr(settings, f"{prefix}_protection_behavior") != "latched_reset":
            raise ValueError("Для IDD подтверждено только поведение защиты latched_reset")
        positive = (
            getattr(settings, f"{prefix}_nominal_current_a"),
            getattr(settings, f"{prefix}_jam_current_multiplier"),
            getattr(settings, f"{prefix}_overload_threshold_multiplier"),
        )
        nonnegative_drive = (
            getattr(settings, f"{prefix}_no_load_current_a"),
            getattr(settings, f"{prefix}_pump_load_coefficient"),
            getattr(settings, f"{prefix}_overload_trip_s"),
        )
        if any(value <= 0 for value in positive) or any(value < 0 for value in nonnegative_drive):
            raise ValueError("Параметры тока и защиты частотников вне допустимого диапазона")
        if getattr(settings, f"{prefix}_no_load_current_a") > getattr(settings, f"{prefix}_nominal_current_a"):
            raise ValueError("Ток холостого хода не может превышать номинальный ток")


def _parse_value(current: object, value: str) -> object:
    if isinstance(current, bool):
        normalized = value.strip().casefold()
        if normalized in {"1", "true", "yes", "on"}:
            return True
        if normalized in {"0", "false", "no", "off"}:
            return False
        raise ValueError("Ожидалось логическое значение true/false")
    if isinstance(current, int):
        return int(value, 0)
    if isinstance(current, float):
        return float(value.replace(",", "."))
    return value.strip()


def changed(settings: BionicSettings, name: str, raw_value: str) -> BionicSettings:
    if name not in OPTION_SPECS:
        raise ValueError(f"Неизвестный параметр: {name}")
    result = replace(settings, **{name: _parse_value(getattr(settings, name), raw_value)})
    validate_settings(result, validate_lights=False)
    return result


def load_settings(path: Path) -> BionicSettings:
    if not path.exists():
        result = BionicSettings()
        validate_settings(result)
        return result
    parser = configparser.ConfigParser()
    try:
        parser.read(path, encoding="utf-8")
    except (configparser.Error, OSError) as exc:
        raise ValueError(f"Не удалось прочитать конфигурацию {path}: {exc}") from None
    result = BionicSettings()
    updates: dict[str, object] = {}
    for name in OPTION_SPECS:
        for section in parser.sections():
            if parser.has_option(section, name):
                try:
                    updates[name] = _parse_value(getattr(result, name), parser.get(section, name))
                except ValueError as exc:
                    raise ValueError(f"Некорректный параметр [{section}] {name}: {exc}") from None
                break
    result = replace(result, **updates)
    try:
        validate_settings(result)
    except ValueError as exc:
        raise ValueError(f"Некорректная конфигурация {path}: {exc}") from None
    return result


CONFIG_VERSION = 2


def save_settings(path: Path, settings: BionicSettings) -> None:
    validate_settings(settings)
    parser = configparser.ConfigParser()
    parser["meta"] = {"version": str(CONFIG_VERSION)}
    for name, (section, _kind) in OPTION_SPECS.items():
        if section not in parser:
            parser[section] = {}
        parser[section][name] = str(getattr(settings, name)).lower() if isinstance(getattr(settings, name), bool) else str(getattr(settings, name))
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        previous = configparser.ConfigParser()
        try:
            previous.read(path, encoding="utf-8")
            old_version = previous.getint("meta", "version", fallback=1)
        except (configparser.Error, OSError, ValueError):
            old_version = 1
        if old_version != CONFIG_VERSION:
            backup = path.with_name(f"{path.name}.v{old_version}.bak")
            if not backup.exists():
                shutil.copy2(path, backup)
    buffer = io.StringIO()
    parser.write(buffer)
    temp_name: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
            "w", encoding="utf-8", newline="", delete=False,
            dir=path.parent, prefix=f".{path.name}.", suffix=".tmp",
        ) as stream:
            temp_name = stream.name
            stream.write(buffer.getvalue())
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp_name, path)
    except Exception:
        if temp_name:
            Path(temp_name).unlink(missing_ok=True)
        raise
