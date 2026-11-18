"""Russian command interface for the Bionic Mini physical imitator."""

from __future__ import annotations

import argparse
import configparser
import shlex
import sys
import threading
import time
from dataclasses import dataclass, replace
from pathlib import Path

from rich.console import Console
from .bionic_config import (
    BionicSettings, changed, load_settings, parse_sensor_relay_map, save_settings,
    validate_settings,
)
from .bionic_equipment import (
    EQUIPMENT_IDS, EquipmentProfile, lifetime_for_new_equipment,
    parse_equipment_profile, serialize_equipment_profiles, synchronize_wear_rate,
)
from .bionic_events import EventJournal
from .bionic_lights import (
    FACTORY_LIGHT_PROFILE, LightChannel, LightType, change_light_type,
    parse_light_profile, replace_light, serialize_light_profile,
)
from .bionic_model import BionicModel
from .bionic_modbus import build_default_bus
from .bionic_ponics import PONICS_OPTION_NAMES, PONICS_REGISTERS
from .bionic_render import print_view
from .bionic_sensor_bridge import SensorRelayBridge, SensorRelayState
from .bionic_server import ModbusSlaveServer, SerialSlaveTransport
from .bionic_state import (
    list_states, load_state, runtime_state_path, save_state, state_path,
)
from .transport import SerialTransport


HELP = """Bionic Immitator — цифровая физическая установка Bionic Mini

status | devices | ports | help
tank list | tank <bo|bp|bso1|bso2> level <л|N%> | capacity <л> | fill-rate <л/мин>
pump list | pump <bo-to-bp|bso1-to-bp|bso2-to-bp> flow <л/мин>
equipment list | status <id> | repair|replace <id> --confirm | set <id> <параметр> <значение> [--sync-wear]
equipment sync-wear <id>
irrigation shelf <1|2> flow-per-tier <л/мин>
pressure target <бар> | range <мин> <макс> | rise-time <с> | fall-time <с>
pipe rupture-threshold <бар> | status | repair
sensor list | sensor <id> threshold <л> | force on|off | auto
fault leak on|off | rate <л/мин> | fault pump hp1|hp2 <тип>
fault blockage on|off | severity <0..100> | fault list | fault clear all
alarm list | alarm reset all
sim start | pause | resume | speed <0.1..100> | reset --confirm
sim state save <имя> | load <имя> --confirm | list
view main|settings|log|rs485|tanks|pumps|equipment|pressure|irrigation|light|sensors|water
view light settings | light set <zone> <поле> ... | light apply|save|restore-defaults
view ponics | view ponics settings | view ponics registers
view drives | view drive hp1 | view drive hp2
ponics dose <a|b|c|ph_plus|ph_minus> <мл> | set <PDU> <RAW>
log last <N> | filter alarms|rs485|tanks|pumps|ponics|all | export <файл.csv>
settings list | set <имя> <значение> | apply | save
exit | quit

Имитатор не формирует STOP и не изменяет выходы контроллера при авариях.
Ручные исполнительные выходы запрещены без --test-mode.
"""


@dataclass
class BionicContext:
    home: Path
    config_path: Path
    settings: BionicSettings
    draft: BionicSettings
    model: BionicModel
    journal: EventJournal
    console: Console
    view: str = "status"
    log_filter: str = "all"
    test_mode: bool = False
    screen_mode: bool = False
    help_query: str = ""
    notice: str = ""
    saved: BionicSettings | None = None
    sensor_relay_state: SensorRelayState | None = None

    def event(self, kind: str, subject: str, message: str) -> None:
        self.journal.add(kind, subject, message)


def apply_model_settings(settings: BionicSettings, model: BionicModel, *, initial: bool = False) -> None:
    capacities = {
        "bo": settings.bo_capacity_l, "bp": settings.bp_capacity_l,
        "bso1": settings.bso1_capacity_l, "bso2": settings.bso2_capacity_l,
    }
    initials = {
        "bo": settings.bo_initial_l, "bp": settings.bp_initial_l,
        "bso1": settings.bso1_initial_l, "bso2": settings.bso2_initial_l,
    }
    for tank_id, capacity in capacities.items():
        if not initial and model.tanks[tank_id].volume_l > capacity:
            raise ValueError(f"Нельзя применить ёмкость {tank_id}: текущий объём больше нового значения")
        model.tanks[tank_id].capacity_l = capacity
        if initial:
            model.tanks[tank_id].volume_l = initials[tank_id]
    model.fill_flow_lpm = settings.fill_flow_lpm
    if initial:
        model.water_meter.total_l = settings.water_meter_initial_l
    model.pumps["bo-to-bp"].flow_lpm = settings.bo_to_bp_flow_lpm
    model.pumps["bso1-to-bp"].flow_lpm = settings.bso1_to_bp_flow_lpm
    model.pumps["bso2-to-bp"].flow_lpm = settings.bso2_to_bp_flow_lpm
    for tier in model.tiers.values():
        tier.flow_lpm = settings.rack1_tier_flow_lpm if tier.rack == 1 else settings.rack2_tier_flow_lpm
        tier.return_fraction = settings.return_fraction
        tier.return_delay_s = settings.return_delay_s
    model.plant_water_uptake_fraction = settings.plant_water_uptake_fraction
    model.irrigation_evaporation_fraction = settings.irrigation_evaporation_fraction
    for sensor in model.sensors.values():
        sensor.hysteresis_l = settings.sensor_hysteresis_l
        sensor.delay_s = settings.sensor_delay_s
        sensor.threshold_l = getattr(settings, f"{sensor.id.replace('-', '_')}_threshold_l")
    model.refresh_sensors()
    model.configure_equipment(parse_equipment_profile(settings.equipment_profile), initial=initial)
    model.boost_pressure_bar = settings.boost_pressure_bar
    model.boost_rise_s = settings.boost_rise_s
    model.boost_fall_s = settings.boost_fall_s
    model.pressure_rise_s = settings.pressure_rise_s
    model.pressure_fall_s = settings.pressure_fall_s
    model.valve_pressure_response_ms = settings.valve_pressure_response_ms
    model.valve_pressure_close_response_ms = settings.valve_pressure_close_response_ms
    model.transient_pressure_spike_coefficient = settings.transient_pressure_spike_coefficient
    model.transient_pressure_spike_duration_ms = settings.transient_pressure_spike_duration_ms
    model.closed_head_pressure_bar = settings.closed_head_pressure_bar
    model.pressure_max_bar = settings.pressure_max_bar
    model.rupture_threshold_bar = settings.rupture_threshold_bar
    model.rupture_residual_bar = settings.rupture_residual_bar
    model.leak_rate_lpm = settings.leak_rate_lpm
    model.leak_pressure_factor = settings.leak_pressure_factor
    model.blockage_severity = settings.blockage_severity
    model.osmosis_profile = {
        "ec": settings.osmosis_ec_ms_cm,
        "ph": settings.osmosis_ph,
        "temperature": settings.osmosis_temperature_c,
        "buffer": settings.osmosis_buffer_per_l,
    }
    model.tap_profile = {
        "ec": settings.tap_ec_ms_cm,
        "ph": settings.tap_ph,
        "temperature": settings.tap_temperature_c,
        "buffer": settings.tap_buffer_per_l,
    }
    model.nutrient_absorption_fraction = settings.nutrient_absorption_fraction
    model.deposition_fraction = settings.deposition_fraction
    model.ph_drift_per_pass = settings.ph_drift_per_pass
    model.fertilizer_ec_per_ml_at_100l = settings.fertilizer_ec_per_ml_at_100l
    model.ph_reagent_delta_per_ml_at_100l = settings.ph_reagent_delta_per_ml_at_100l
    if initial:
        model.tanks["bo"].initialize_solution(
            ec_ms_cm=settings.osmosis_ec_ms_cm, ph=settings.osmosis_ph,
            temperature_c=settings.osmosis_temperature_c,
            buffer_per_l=settings.osmosis_buffer_per_l,
        )
        model.tanks["bp"].initialize_solution(
            ec_ms_cm=settings.broth_initial_ec_ms_cm, ph=settings.broth_initial_ph,
            temperature_c=settings.broth_initial_temperature_c,
            buffer_per_l=settings.broth_buffer_per_l,
        )
        for tank_id in ("bso1", "bso2"):
            model.tanks[tank_id].initialize_solution(
                ec_ms_cm=settings.drain_initial_ec_ms_cm, ph=settings.drain_initial_ph,
                temperature_c=settings.drain_initial_temperature_c,
                buffer_per_l=settings.drain_buffer_per_l,
            )
    model.ponics.configure({
        8: settings.ponics_irrigation_on_s,
        9: settings.ponics_irrigation_pause_s,
        23: settings.ponics_mode,
        24: int(settings.ponics_ph_enabled),
        26: settings.ponics_ph_dosing_pause_s,
        27: round(settings.ponics_ph_low * 10),
        28: round(settings.ponics_ph_high * 10),
        29: int(settings.ponics_ec_enabled),
        30: int(settings.ponics_ec_protection_enabled),
        31: settings.ponics_ec_dosing_pause_s,
        32: settings.ponics_ec_program,
        33: round(settings.ponics_ec_target_ms_cm * 100),
        34: settings.ponics_fertilizer_a_share,
        35: settings.ponics_fertilizer_b_share,
        36: settings.ponics_fertilizer_c_share,
        37: int(settings.ponics_thermostat_enabled),
        38: settings.ponics_temperature_low_c,
        39: settings.ponics_temperature_high_c,
    })
    for drive_id in ("hp1", "hp2"):
        prefix = drive_id
        address = getattr(settings, f"{prefix}_address")
        drive = model.drives[drive_id]
        drive.address = address
        drive.ramp_up_s = getattr(settings, f"{prefix}_ramp_up_s")
        drive.ramp_down_s = getattr(settings, f"{prefix}_ramp_down_s")
        drive.configuration.update({
            100: getattr(settings, f"{prefix}_pb00"),
            101: getattr(settings, f"{prefix}_pb01"),
            102: getattr(settings, f"{prefix}_pb02"),
            105: getattr(settings, f"{prefix}_pb05"),
            106: getattr(settings, f"{prefix}_pb06"),
            107: round(drive.ramp_up_s * 10),
            108: round(drive.ramp_down_s * 10),
            210: round(getattr(settings, f"{prefix}_nominal_current_a") * 10),
            212: getattr(settings, f"{prefix}_pc12"),
            215: getattr(settings, f"{prefix}_pc15"),
            700: getattr(settings, f"{prefix}_ph00"),
            701: getattr(settings, f"{prefix}_ph01"),
            702: address,
            816: int(getattr(settings, f"{prefix}_overload_protection_enabled")),
        })
        drive.nominal_current_a = getattr(settings, f"{prefix}_nominal_current_a")
        drive.no_load_current_a = getattr(settings, f"{prefix}_no_load_current_a")
        drive.pump_load_coefficient = getattr(settings, f"{prefix}_pump_load_coefficient")
        drive.jam_current_multiplier = getattr(settings, f"{prefix}_jam_current_multiplier")
        drive.overload_trip_s = getattr(settings, f"{prefix}_overload_trip_s")
        drive.overload_protection_enabled = getattr(settings, f"{prefix}_overload_protection_enabled")
        drive.overload_threshold_multiplier = getattr(settings, f"{prefix}_overload_threshold_multiplier")
        drive.protection_behavior = getattr(settings, f"{prefix}_protection_behavior")
    model.speed = settings.simulation_speed
    model.configure_lights(parse_light_profile(settings.light_profile))


def make_context(home: Path, config_path: Path | None = None, *, console: Console | None = None, test_mode: bool = False) -> BionicContext:
    path = config_path or home / "bionic-immitator.ini"
    settings = load_settings(path)
    journal = EventJournal(home / "bionic-events.jsonl", settings.retention_days)
    model = BionicModel()
    apply_model_settings(settings, model, initial=True)
    restored_notice = ""
    automatic_path = runtime_state_path(home)
    if automatic_path.exists():
        try:
            load_state(automatic_path, model)
            restored_notice = "Физическое состояние восстановлено после прошлого выхода"
            journal.add("СИСТЕМА", "simulation-state", restored_notice)
        except ValueError as exc:
            model = BionicModel()
            apply_model_settings(settings, model, initial=True)
            restored_notice = f"Автосостояние не восстановлено: {exc}; загружено начальное состояние"
            journal.add("ОШИБКА", "simulation-state", restored_notice)
    ctx = BionicContext(home, path, settings, settings, model, journal, console or Console(), test_mode=test_mode)
    ctx.saved = settings
    ctx.notice = restored_notice
    ctx.sensor_relay_state = SensorRelayState()
    ctx.model.event = ctx.event
    _bind_ponics_draft(ctx)
    _bind_drive_draft(ctx)
    return ctx


def save_runtime_state(ctx: BionicContext) -> None:
    """Atomically persist physical state without controller-owned commands."""
    save_state(runtime_state_path(ctx.home), ctx.model)


def _bind_ponics_draft(ctx: BionicContext) -> None:
    """Keep externally written nonvolatile registers available to Save."""
    def update(index: int, raw: int) -> None:
        name = PONICS_OPTION_NAMES[index]
        current = getattr(ctx.draft, name)
        if isinstance(current, bool):
            value: object = bool(raw)
        elif isinstance(current, float):
            value = raw * PONICS_REGISTERS[index].scale
        else:
            value = raw
        ctx.draft = replace(ctx.draft, **{name: value})
        ctx.settings = replace(ctx.settings, **{name: value})

    ctx.model.ponics.setting_changed = update


def _bind_drive_draft(ctx: BionicContext) -> None:
    """Stage externally written nonvolatile IDD parameters for explicit Save."""
    names = {
        100: "pb00", 101: "pb01", 102: "pb02", 105: "pb05", 106: "pb06",
        212: "pc12", 215: "pc15",
        700: "ph00", 701: "ph01",
    }

    for drive_id, drive in ctx.model.drives.items():
        def update(address: int, raw: int, prefix: str = drive_id) -> None:
            if address == 107:
                name, value = f"{prefix}_ramp_up_s", raw / 10.0
            elif address == 108:
                name, value = f"{prefix}_ramp_down_s", raw / 10.0
            elif address == 702:
                name, value = f"{prefix}_address", raw
            elif address == 210:
                name, value = f"{prefix}_nominal_current_a", raw / 10.0
            elif address == 816:
                name, value = f"{prefix}_overload_protection_enabled", bool(raw)
            else:
                name, value = f"{prefix}_{names[address]}", raw
            ctx.draft = replace(ctx.draft, **{name: value})
            ctx.settings = replace(ctx.settings, **{name: value})

        drive.configuration_changed = update


def _number(value: str, label: str, minimum: float = 0.0, maximum: float | None = None) -> float:
    try:
        result = float(value.replace(",", "."))
    except ValueError:
        raise ValueError(f"{label}: ожидалось число") from None
    if result < minimum or maximum is not None and result > maximum:
        suffix = f"..{maximum:g}" if maximum is not None else " или больше"
        raise ValueError(f"{label}: допустимо {minimum:g}{suffix}")
    return result


def _record_applied_option(ctx: BionicContext, name: str, raw_value: str) -> None:
    """Keep an immediately applied convenience command visible and saveable."""
    ctx.draft = changed(ctx.draft, name, raw_value)
    ctx.settings = changed(ctx.settings, name, raw_value)


def _integer(value: str, label: str, minimum: int, maximum: int) -> int:
    try:
        result = int(value, 0)
    except ValueError:
        raise ValueError(f"{label}: ожидалось целое число") from None
    if not minimum <= result <= maximum:
        raise ValueError(f"{label}: допустимо {minimum}..{maximum}")
    return result


def _on_off(value: str) -> bool:
    if value.casefold() == "on":
        return True
    if value.casefold() == "off":
        return False
    raise ValueError("Укажите on или off")


def _light_draft(ctx: BionicContext, zone_id: str):
    profile = parse_light_profile(ctx.draft.light_profile)
    try:
        light = next(item for item in profile if item.id == zone_id)
    except StopIteration:
        raise ValueError(f"Неизвестный ярус освещения: {zone_id}") from None
    return profile, light


def _store_light_draft(ctx: BionicContext, profile, message: str) -> None:
    ctx.draft = replace(ctx.draft, light_profile=serialize_light_profile(profile))
    ctx.notice = f"Черновик света: {message}"
    ctx.event("ОПЕРАТОР", "lighting-draft", message)


def _print_tanks(ctx: BionicContext) -> None:
    for tank in ctx.model.tanks.values():
        ctx.console.print(f"{tank.id}: {tank.volume_l:.2f}/{tank.capacity_l:.2f} л ({tank.percent:.1f}%), перелив {tank.overflow_l:.2f} л")


def _print_alarms(ctx: BionicContext) -> None:
    alarms = [alarm for alarm in ctx.model.alarms.values() if alarm.state.value != "CLEARED"]
    if not alarms:
        ctx.console.print("Зафиксированных аварий нет")
    for alarm in alarms:
        ctx.console.print(f"{alarm.state.value:<7} {alarm.code} {alarm.subject} {alarm.first_at.isoformat()}")


def _equipment_description(model: BionicModel, equipment_id: str) -> str:
    health = model.equipment_health(equipment_id)
    command = "RUN" if model.equipment_commanded(equipment_id) else "STOP"
    flow = (
        model.pumps[equipment_id].actual_flow_lpm
        if equipment_id in model.pumps else model.calculated_flow_lpm
    )
    return (
        f"{equipment_id}: команда {command}; состояние {health.state}; "
        f"расход {flow:.2f} л/мин; сухой ход {health.dry_run_s:.1f} с; "
        f"нагрев {health.heat * 100:.1f}%; износ {health.damage * 100:.1f}%; "
        f"отказ {health.failure}; ремонт {'нужен' if health.repair_required else 'не нужен'}"
    )


def execute_command(ctx: BionicContext, line: str) -> str | None:
    try:
        parts = shlex.split(line)
    except ValueError as exc:
        raise ValueError(f"Ошибка командной строки: {exc}") from None
    if not parts:
        return None
    command = parts[0].casefold()
    args = parts[1:]
    model = ctx.model
    if command in {"exit", "quit"}:
        return "exit"
    if command == "help":
        if len(args) >= 2 and args[0] == "search":
            ctx.help_query = " ".join(args[1:])
        elif args:
            ctx.help_query = " ".join(args)
        ctx.view = "help"
        if not ctx.screen_mode:
            ctx.console.print(HELP)
        return None
    if command == "status":
        ctx.view = "status"
        if not ctx.screen_mode:
            print_view(ctx.console, "status", model, ctx.journal, ctx.settings, ctx.draft, ctx.saved, ctx.sensor_relay_state)
        return None
    if command == "view":
        nested = {
            ("ponics",): "ponics", ("ponics", "settings"): "ponics-settings",
            ("ponics", "registers"): "ponics-registers", ("drives",): "drives",
            ("drive", "hp1"): "drive-hp1", ("drive", "hp2"): "drive-hp2",
            ("light", "settings"): "light-settings",
        }
        allowed = {"main", "status", "devices", "ports", "settings", "help", "log", "rs485", "tanks", "pumps", "equipment", "pressure", "irrigation", "light", "light-settings", "sensors", "water"}
        target = nested.get(tuple(args))
        if target is None and len(args) == 1 and args[0] in allowed:
            target = "status" if args[0] == "main" else args[0]
        if target is None:
            raise ValueError("view: укажите страницу, включая light settings, ponics [settings|registers], drives или drive hp1|hp2")
        ctx.view = target
        if not ctx.screen_mode:
            print_view(ctx.console, ctx.view, model, ctx.journal, ctx.settings, ctx.draft, ctx.saved, ctx.sensor_relay_state)
        return None
    if command == "ponics":
        if len(args) == 3 and args[0] == "dose":
            amount = _number(args[2], "Доза", 0, 6553.5)
            model.ponics.dose(args[1].casefold(), amount)
        elif len(args) == 3 and args[0] == "set":
            register = int(args[1], 0)
            value = int(args[2], 0)
            model.ponics.write(register, value, source="оператор TUI")
        elif len(args) == 3 and args[0] == "fault":
            subject = args[1].casefold()
            enabled = _on_off(args[2])
            if subject == "offline":
                model.ponics.respond = not enabled
            elif subject in model.ponics.sensor_faults:
                model.ponics.sensor_faults[subject] = enabled
            elif subject in model.ponics.doser_faults:
                model.ponics.doser_faults[subject] = enabled
            else:
                raise ValueError("Неисправность: offline, ph, ec, temperature, a, b, c, ph_plus или ph_minus")
            ctx.event("ОПЕРАТОР", f"ponics-{subject}", f"неисправность {'включена' if enabled else 'выключена'}")
        else:
            raise ValueError("ponics dose <a|b|c|ph_plus|ph_minus> <мл> | set <PDU> <RAW> | fault <имя> on|off")
        return None
    if command == "ports":
        ctx.view = "ports"
        if not ctx.screen_mode:
            print_view(ctx.console, "ports", model, ctx.journal, ctx.settings, ctx.draft, ctx.saved, ctx.sensor_relay_state)
        return None
    if command == "devices":
        ctx.view = "devices"
        if not ctx.screen_mode:
            print_view(ctx.console, "devices", model, ctx.journal, ctx.settings, ctx.draft, ctx.saved, ctx.sensor_relay_state)
        return None
    if command == "light":
        if args == ["settings"]:
            ctx.view = "light-settings"
            if not ctx.screen_mode:
                print_view(ctx.console, ctx.view, model, ctx.journal, ctx.settings, ctx.draft, ctx.saved, ctx.sensor_relay_state)
            return None
        if args == ["restore-defaults"]:
            ctx.draft = replace(ctx.draft, light_profile=FACTORY_LIGHT_PROFILE)
            ctx.notice = "Черновик света восстановлен из профиля Bionic Mini"
            ctx.event("ОПЕРАТОР", "lighting-draft", "восстановлен заводской профиль Bionic Mini")
            return None
        if args == ["apply"]:
            applied = replace(ctx.settings, light_profile=ctx.draft.light_profile)
            validate_settings(applied)
            model.configure_lights(parse_light_profile(applied.light_profile))
            ctx.settings = applied
            ctx.event("ОПЕРАТОР", "lighting", "черновик света применён; физические выходы не изменялись")
            return None
        if args == ["save"]:
            saved = replace(ctx.saved or ctx.settings, light_profile=ctx.draft.light_profile)
            validate_settings(saved)
            save_settings(ctx.config_path, saved)
            ctx.saved = saved
            ctx.event("ОПЕРАТОР", "lighting", f"профиль света сохранён в {ctx.config_path}; рабочая модель не изменена")
            return None
        if len(args) >= 4 and args[0] == "set":
            zone_id, field = args[1], args[2]
            profile, light = _light_draft(ctx, zone_id)
            if field == "type" and len(args) == 4:
                try:
                    updated = change_light_type(light, LightType(args[3].upper()))
                except ValueError:
                    raise ValueError("Тип света: NONE, SINGLE или SPECTRAL_4") from None
            elif field in {"rack", "tier", "relay"} and len(args) == 4:
                value = _integer(args[3], field, 1, 32)
                attribute = {"rack": "rack", "tier": "tier", "relay": "power_relay"}[field]
                updated = replace(light, **{attribute: value})
            elif field == "enabled" and len(args) == 4:
                updated = replace(light, enabled=_on_off(args[3]))
            elif field == "name" and len(args) >= 4:
                updated = replace(light, name=" ".join(args[3:]))
            elif field == "channel" and len(args) == 6:
                role = args[3].casefold()
                if role not in {channel.role for channel in light.channels}:
                    raise ValueError("Канал не предусмотрен выбранным типом светильника")
                binding = LightChannel(
                    role,
                    _integer(args[4], "Modbus ID", 1, 247),
                    _integer(args[5], "Канал AO", 1, 8),
                )
                updated = replace(light, channels=tuple(
                    binding if channel.role == role else channel for channel in light.channels
                ))
            elif field == "voltage" and len(args) == 5:
                updated = replace(
                    light,
                    min_voltage_v=_number(args[3], "Минимальное напряжение", 0, 10),
                    max_voltage_v=_number(args[4], "Максимальное напряжение", 0, 10),
                )
            elif field == "brightness" and len(args) == 5:
                updated = replace(
                    light,
                    min_brightness_pct=_number(args[3], "Минимальная яркость", 0, 100),
                    max_brightness_pct=_number(args[4], "Максимальная яркость", 0, 100),
                )
            else:
                raise ValueError("light set <zone> type|rack|tier|relay|enabled|name|channel|voltage|brightness ...")
            _store_light_draft(ctx, replace_light(profile, zone_id, updated), f"{zone_id}: {field}")
            return None
        raise ValueError("light settings|apply|save|restore-defaults|set <zone> <поле> ...")
    if command == "tank":
        if args == ["list"]:
            ctx.view = "tanks"
            if not ctx.screen_mode: _print_tanks(ctx)
            return None
        if len(args) != 3 or args[0] not in model.tanks:
            raise ValueError("tank: используйте list или tank <bo|bp|bso1|bso2> <level|capacity|fill-rate> <значение>")
        tank_id, action, raw = args
        if action == "level":
            percent = raw.endswith("%")
            model.set_tank_level(tank_id, _number(raw[:-1] if percent else raw, "Уровень", 0, 100 if percent else model.tanks[tank_id].capacity_l), percent=percent)
        elif action == "capacity":
            capacity = _number(raw, "Ёмкость", 0.001)
            if capacity < model.tanks[tank_id].volume_l:
                raise ValueError("Ёмкость не может быть меньше текущего объёма")
            maximum = model.sensors[f"{tank_id}-max"].threshold_l
            if capacity < maximum:
                raise ValueError(f"Ёмкость не может быть меньше порога MAX {maximum:g} л")
            option = f"{tank_id}_capacity_l"
            _record_applied_option(ctx, option, raw)
            model.tanks[tank_id].capacity_l = capacity
            ctx.event("ОПЕРАТОР", tank_id, f"ёмкость {capacity:g} л; абсолютные пороги датчиков не изменены")
        elif action == "fill-rate" and tank_id == "bo":
            model.fill_flow_lpm = _number(raw, "Расход наполнения")
            _record_applied_option(ctx, "fill_flow_lpm", raw)
            ctx.event("ОПЕРАТОР", tank_id, f"расход наполнения {model.fill_flow_lpm:g} л/мин")
        else:
            raise ValueError("tank: допустимы level, capacity; fill-rate доступен для bo")
        return None
    if command == "pump":
        if args == ["list"]:
            ctx.view = "pumps"
            if ctx.screen_mode: return None
            for pump in model.pumps.values():
                ctx.console.print(f"{pump.id}: команда {'RUN' if model.relay(pump.relay) else 'STOP'}, {pump.actual_flow_lpm:.2f}/{pump.flow_lpm:.2f} л/мин")
            return None
        if len(args) == 3 and args[0] in model.pumps and args[1] == "flow":
            model.pumps[args[0]].flow_lpm = _number(args[2], "Расход насоса")
            option = {
                "bo-to-bp": "bo_to_bp_flow_lpm",
                "bso1-to-bp": "bso1_to_bp_flow_lpm",
                "bso2-to-bp": "bso2_to_bp_flow_lpm",
            }[args[0]]
            _record_applied_option(ctx, option, args[2])
            ctx.event("ОПЕРАТОР", args[0], f"расход {model.pumps[args[0]].flow_lpm:g} л/мин")
            return None
        if len(args) >= 2 and args[0] in model.drives and args[1] == "repair":
            raise ValueError(f"Используйте подтверждённый ремонт: equipment repair {args[0]} --confirm")
        raise ValueError("pump: используйте list или pump <id> flow <л/мин>")
    if command == "equipment":
        if args == ["list"]:
            ctx.view = "equipment"
            if not ctx.screen_mode:
                print_view(ctx.console, "equipment", model, ctx.journal, ctx.settings, ctx.draft, ctx.saved, ctx.sensor_relay_state)
            return None
        if len(args) == 2 and args[0] == "status" and args[1] in EQUIPMENT_IDS:
            ctx.notice = _equipment_description(model, args[1])
            if not ctx.screen_mode:
                ctx.console.print(ctx.notice)
            return None
        if len(args) == 3 and args[0] in {"repair", "replace"} and args[1] in EQUIPMENT_IDS:
            if args[2] != "--confirm":
                raise ValueError("Ремонт или замена требуют --confirm")
            was_commanded = model.repair_equipment(args[1], replace=args[0] == "replace")
            ctx.notice = (
                f"{args[1]}: {'заменено' if args[0] == 'replace' else 'отремонтировано'}; "
                "ВНИМАНИЕ: команда платы активна, оборудование может немедленно запуститься"
                if was_commanded else
                f"{args[1]}: {'заменено' if args[0] == 'replace' else 'отремонтировано'}; команда платы не изменена"
            )
            return None
        if len(args) == 2 and args[0] == "sync-wear" and args[1] in EQUIPMENT_IDS:
            profiles = parse_equipment_profile(ctx.draft.equipment_profile)
            profiles[args[1]] = synchronize_wear_rate(profiles[args[1]])
            ctx.draft = replace(
                ctx.draft, equipment_profile=serialize_equipment_profiles(profiles),
            )
            lifetime = lifetime_for_new_equipment(profiles[args[1]])
            ctx.notice = (
                f"Черновик {args[1]}: wear_rate_per_s={profiles[args[1]].wear_rate_per_s:.9g}; "
                f"новый насос откажет через {lifetime.effective_s:g} с; текущий износ не сброшен"
            )
            ctx.event("ОПЕРАТОР", "equipment-draft", ctx.notice)
            return None
        if len(args) in {4, 5} and args[0] == "set" and args[1] in EQUIPMENT_IDS:
            sync_wear = len(args) == 5
            if sync_wear and (args[4] != "--sync-wear" or args[2] != "failure_s"):
                raise ValueError("--sync-wear допустим только при изменении failure_s")
            profiles = parse_equipment_profile(ctx.draft.equipment_profile)
            profile = profiles[args[1]]
            field_name = args[2]
            if field_name not in EquipmentProfile.__dataclass_fields__:
                raise ValueError("Неизвестный параметр профиля оборудования")
            if field_name == "initial_state":
                value: object = args[3].upper()
            elif field_name == "failure_type":
                value = args[3].casefold()
            else:
                value = _number(args[3], field_name)
            updated_profile = replace(profile, **{field_name: value})
            if sync_wear:
                updated_profile = synchronize_wear_rate(updated_profile)
            profiles[args[1]] = updated_profile
            ctx.draft = replace(
                ctx.draft,
                equipment_profile=serialize_equipment_profiles(profiles),
            )
            lifetime = lifetime_for_new_equipment(updated_profile)
            wear_text = "∞" if lifetime.wear_s == float("inf") else f"{lifetime.wear_s:g} с"
            ctx.notice = (
                f"Черновик {args[1]}: {field_name}={value}; прямой порог "
                f"{lifetime.threshold_s:g} с, накопительный износ {wear_text}, "
                f"эффективно {lifetime.effective_s:g} с ({lifetime.limiting_mechanism})"
                + ("; wear_rate синхронизирован, текущий износ не сброшен" if sync_wear else "")
            )
            ctx.event("ОПЕРАТОР", "equipment-draft", ctx.notice)
            return None
        raise ValueError("equipment list | status <id> | repair|replace <id> --confirm | set <id> <параметр> <значение> [--sync-wear] | sync-wear <id>")
    if command == "irrigation":
        if len(args) == 4 and args[0] == "shelf" and args[2] == "flow-per-tier":
            rack = int(args[1])
            if rack not in {1, 2}:
                raise ValueError("Номер стеллажа должен быть 1 или 2")
            flow = _number(args[3], "Расход яруса")
            for tier in model.tiers.values():
                if tier.rack == rack:
                    tier.flow_lpm = flow
            _record_applied_option(ctx, f"rack{rack}_tier_flow_lpm", args[3])
            ctx.event("ОПЕРАТОР", f"rack-{rack}", f"расход яруса {flow:g} л/мин")
            return None
        raise ValueError("irrigation shelf <1|2> flow-per-tier <л/мин>")
    if command == "pressure":
        if len(args) == 2 and args[0] == "target":
            # Target is informational for this passive model; the board still controls frequency.
            ctx.event("ОПЕРАТОР", "pressure", f"рабочая цель {_number(args[1], 'Давление'):g} бар")
        elif len(args) == 3 and args[0] == "range":
            low, high = _number(args[1], "Минимум"), _number(args[2], "Максимум")
            if low >= high:
                raise ValueError("Минимальное давление должно быть меньше максимального")
            model.pressure_max_bar = high
            _record_applied_option(ctx, "pressure_max_bar", args[2])
            ctx.event("ОПЕРАТОР", "pressure", f"диапазон {low:g}..{high:g} бар")
        elif len(args) == 2 and args[0] in {"rise-time", "fall-time"}:
            value = _number(args[1], "Время")
            option = "pressure_rise_s" if args[0] == "rise-time" else "pressure_fall_s"
            setattr(model, option, value)
            _record_applied_option(ctx, option, args[1])
        else:
            raise ValueError("pressure: используйте target, range, rise-time или fall-time")
        return None
    if command == "pipe":
        if args == ["status"]:
            ctx.view = "pressure"
            ctx.notice = f"Трубопровод: {'РАЗРУШЕН' if model.pipe_ruptured else 'исправен'}, порог {model.rupture_threshold_bar:g} бар"
            if not ctx.screen_mode: ctx.console.print(ctx.notice)
        elif args == ["repair"]:
            model.repair_pipe()
        elif len(args) == 2 and args[0] == "rupture-threshold":
            model.rupture_threshold_bar = _number(args[1], "Порог разрушения", 1)
            _record_applied_option(ctx, "rupture_threshold_bar", args[1])
            ctx.event("ОПЕРАТОР", "pipe", f"порог {model.rupture_threshold_bar:g} бар")
        else:
            raise ValueError("pipe: используйте status, repair или rupture-threshold <бар>")
        return None
    if command == "sensor":
        if args == ["list"]:
            ctx.view = "sensors"
            if not ctx.screen_mode:
                print_view(ctx.console, "sensors", model, ctx.journal, ctx.settings, ctx.draft, ctx.saved, ctx.sensor_relay_state)
            return None
        if not args or args[0] not in model.sensors:
            raise ValueError("sensor: неизвестный датчик; используйте sensor list")
        sensor_id = args[0]
        if len(args) == 2 and args[1] == "auto":
            model.force_sensor(sensor_id, None)
        elif len(args) == 3 and args[1] == "force":
            model.force_sensor(sensor_id, _on_off(args[2]))
        elif len(args) == 3 and args[1] == "threshold":
            sensor = model.sensors[sensor_id]
            threshold = _number(args[2], "Порог", 0, model.tanks[sensor.tank_id].capacity_l)
            option = f"{sensor_id.replace('-', '_')}_threshold_l"
            updated = replace(ctx.draft, **{option: threshold})
            validate_settings(updated, validate_lights=False)
            ctx.draft = updated
            ctx.settings = replace(ctx.settings, **{option: threshold})
            sensor.threshold_l = threshold
            model.refresh_sensor(sensor_id)
            ctx.event("ОПЕРАТОР", sensor_id, f"порог {threshold:g} л; добавлен в черновик настроек")
        else:
            raise ValueError("sensor <id> threshold <л> | force on|off | auto")
        return None
    if command == "fault":
        if args == ["list"]:
            ctx.view = "pressure"
            ctx.notice = (
                f"leak={'on' if model.leak_enabled else 'off'}; "
                f"blockage={'on' if model.blockage_enabled else 'off'} "
                f"({model.blockage_severity:g}%, {model.blockage_position}); "
                f"pipe={'ruptured' if model.pipe_ruptured else 'ok'}; "
                + "; ".join(
                    f"{drive.id}={drive.mechanical_failure}, IDD fault={drive.fault}"
                    for drive in model.drives.values()
                )
            )
            if not ctx.screen_mode: ctx.console.print(ctx.notice)
        elif args == ["clear", "all"]:
            model.leak_enabled = model.blockage_enabled = False
            ctx.event("ОПЕРАТОР", "faults", "протечка и засор отключены; труба не ремонтировалась")
        elif len(args) == 2 and args[0] == "leak":
            model.leak_enabled = _on_off(args[1])
            ctx.event("ОПЕРАТОР", "leak", args[1])
        elif len(args) == 3 and args[:2] == ["leak", "rate"]:
            model.leak_rate_lpm = _number(args[2], "Интенсивность протечки")
            _record_applied_option(ctx, "leak_rate_lpm", args[2])
        elif len(args) == 2 and args[0] == "blockage":
            model.blockage_enabled = _on_off(args[1])
            ctx.event("ОПЕРАТОР", "blockage", args[1])
        elif len(args) == 3 and args[:2] == ["blockage", "severity"]:
            model.blockage_severity = _number(args[2], "Степень засора", 0, 100)
            _record_applied_option(ctx, "blockage_severity", args[2])
        elif len(args) == 3 and args[0] == "pump" and args[1] in model.drives:
            failures = {"none", "jammed", "impeller_damage", "motor_failure", "dry_run_wear", "loss_of_prime"}
            if args[2] not in failures:
                raise ValueError("Тип отказа: none, jammed, impeller_damage, motor_failure, dry_run_wear или loss_of_prime")
            model.drives[args[1]].mechanical_failure = args[2]
            ctx.event("ОПЕРАТОР", args[1], f"механический отказ: {args[2]}; отдельный сигнал контроллеру не формируется")
        else:
            raise ValueError("fault: используйте list, clear all, leak, blockage или fault pump hp1|hp2 <тип>")
        return None
    if command == "alarm":
        if args == ["list"]:
            ctx.view = "status"
            if not ctx.screen_mode: _print_alarms(ctx)
        elif args == ["reset", "all"]:
            model.reset_alarms()
        else:
            raise ValueError("alarm list | alarm reset all")
        return None
    if command == "sim":
        if args == ["start"]:
            model.running = True
            model.paused = False
        elif args == ["pause"]:
            model.paused = True
        elif args == ["resume"]:
            model.running = True
            model.paused = False
        elif len(args) == 2 and args[0] == "speed":
            model.speed = _number(args[1], "Скорость", 0.1, 100)
            _record_applied_option(ctx, "simulation_speed", args[1])
        elif args == ["reset", "--confirm"]:
            ctx.model = BionicModel(ctx.event)
            apply_model_settings(ctx.settings, ctx.model, initial=True)
            _bind_ponics_draft(ctx)
            _bind_drive_draft(ctx)
            save_runtime_state(ctx)
            ctx.event("ОПЕРАТОР", "simulation", "виртуальное состояние сброшено; физические выходы не изменялись")
            return "reconnect"
        elif len(args) == 3 and args[:2] == ["state", "save"]:
            path = state_path(ctx.home / "simulation-states", args[2])
            save_state(path, model)
            ctx.notice = f"Состояние сохранено: {args[2]}"
            ctx.event("ОПЕРАТОР", "simulation-state", ctx.notice)
            if not ctx.screen_mode:
                ctx.console.print(ctx.notice)
            return None
        elif args == ["state", "list"]:
            names = list_states(ctx.home / "simulation-states")
            ctx.notice = "Состояния: " + (", ".join(names) if names else "нет")
            if not ctx.screen_mode:
                ctx.console.print(ctx.notice)
            return None
        elif len(args) == 4 and args[:2] == ["state", "load"] and args[3] == "--confirm":
            controller_active = any(model.relays) or any(
                drive.run_register for drive in model.drives.values()
            )
            load_state(state_path(ctx.home / "simulation-states", args[2]), model)
            suffix = (
                "; ВНИМАНИЕ: активные команды платы сохранены и могут сразу воздействовать на восстановленную модель"
                if controller_active else "; команды платы не восстанавливались и не изменялись"
            )
            ctx.notice = f"Состояние загружено: {args[2]}{suffix}"
            ctx.event("ОПЕРАТОР", "simulation-state", ctx.notice)
            if not ctx.screen_mode:
                ctx.console.print(ctx.notice)
            return None
        elif len(args) >= 3 and args[:2] == ["state", "load"]:
            raise ValueError("sim state load требует подтверждения: sim state load <имя> --confirm")
        elif args and args[0] == "reset":
            raise ValueError("sim reset требует явного подтверждения: sim reset --confirm")
        else:
            raise ValueError("sim start|pause|resume|speed <0.1..100>|reset --confirm|state save|load|list")
        ctx.event("ОПЕРАТОР", "simulation", " ".join(args))
        return None
    if command == "log":
        if len(args) == 2 and args[0] == "last":
            ctx.view = "log"
            events = ctx.journal.filtered(ctx.log_filter, int(args[1]))
            if not ctx.screen_mode:
                for event in events: ctx.console.print(f"{event.at} {event.kind} {event.subject}: {event.message}")
        elif len(args) == 2 and args[0] == "filter" and args[1] in {
            "alarms", "rs485", "tanks", "pumps", "ponics", "all",
        }:
            ctx.log_filter = args[1]
            ctx.view = "log"
        elif len(args) == 2 and args[0] == "export":
            path = Path(args[1])
            if not path.is_absolute():
                path = ctx.home / path
            ctx.journal.export_csv(path, ctx.journal.filtered(ctx.log_filter))
            ctx.notice = f"Журнал экспортирован: {path}"
            if not ctx.screen_mode: ctx.console.print(ctx.notice)
        else:
            raise ValueError("log last <N> | filter alarms|rs485|tanks|pumps|ponics|all | export <файл.csv>")
        return None
    if command == "settings":
        if args == ["list"]:
            ctx.view = "settings"
            if not ctx.screen_mode: print_view(ctx.console, "settings", model, ctx.journal, ctx.settings, ctx.draft, ctx.saved, ctx.sensor_relay_state)
        elif len(args) == 3 and args[0] == "set":
            ctx.draft = changed(ctx.draft, args[1], args[2])
            ctx.notice = f"Черновик: {args[1]}={getattr(ctx.draft, args[1])}"
            if not ctx.screen_mode: ctx.console.print(ctx.notice)
        elif args == ["apply"]:
            reconnect = any(getattr(ctx.settings, name) != getattr(ctx.draft, name) for name in (
                "controller_port", "controller_baudrate", "controller_parity", "controller_stopbits",
                "relay_address", "ao1_address", "ao2_address", "ao3_address", "ponics_address", "ai_address", "hp1_address", "hp2_address",
                "sensor_relay_port", "sensor_relay_baudrate", "sensor_relay_parity", "sensor_relay_stopbits",
                "sensor_relay_id", "sensor_relay_channels", "sensor_relay_active_low", "sensor_relay_map",
                "sensor_relay_loss_behavior", "hardware_mode",
            ))
            validate_settings(ctx.draft)
            apply_model_settings(ctx.draft, ctx.model)
            ctx.settings = ctx.draft
            ctx.event("ОПЕРАТОР", "settings", "черновик применён к работающей модели")
            return "reconnect" if reconnect else None
        elif args == ["save"]:
            save_settings(ctx.config_path, ctx.draft)
            ctx.saved = ctx.draft
            ctx.event("ОПЕРАТОР", "settings", f"черновик сохранён в {ctx.config_path}; рабочая модель не изменена")
        else:
            raise ValueError("settings list | set <имя> <значение> | apply | save")
        return None
    if command == "relay" and len(args) == 3 and args[0] == "force":
        if not ctx.test_mode:
            raise ValueError("Ручное изменение выходов запрещено; перезапустите с --test-mode")
        channel = int(args[1])
        model.set_relay(channel, _on_off(args[2]))
        ctx.event(
            "ОПЕРАТОР", f"do-{channel}",
            f"{model.output_name(channel)}: ТЕСТОВОЕ ПРИНУДИТЕЛЬНОЕ {args[2]}",
        )
        return None
    raise ValueError(f"Неизвестная команда: {command}. Используйте help")


class ModelRunner:
    def __init__(self, ctx: BionicContext) -> None:
        self.ctx = ctx
        self.stop_event = threading.Event()
        self.thread = threading.Thread(target=self._run, name="bionic-physics", daemon=True)

    def start(self) -> None:
        self.ctx.model.running = True
        self.thread.start()

    def _run(self) -> None:
        previous = time.monotonic()
        while not self.stop_event.wait(self.ctx.settings.model_interval_ms / 1000.0):
            now = time.monotonic()
            self.ctx.model.tick(now - previous)
            previous = now

    def stop(self) -> None:
        self.stop_event.set()
        self.thread.join(timeout=1)


class BridgeRunner:
    def __init__(self, ctx: BionicContext) -> None:
        self.ctx = ctx
        self.stop_event = threading.Event()
        self.wake_event = threading.Event()
        parser = configparser.ConfigParser()
        parser["connection"] = {
            "port": ctx.settings.sensor_relay_port,
            "baudrate": str(ctx.settings.sensor_relay_baudrate),
            "bytesize": "8",
            "parity": ctx.settings.sensor_relay_parity,
            "stopbits": str(ctx.settings.sensor_relay_stopbits),
            "timeout_ms": "250",
        }
        parser["runtime"] = {
            "crc_mode": "auto", "response_silence_ms": "5",
            "max_response_bytes": "256", "post_write_delay_ms": "0",
        }
        self.transport = SerialTransport(parser)
        mapping = parse_sensor_relay_map(ctx.settings.sensor_relay_map)
        self.bridge = SensorRelayBridge(
            self.transport, ctx.settings.sensor_relay_id, ctx.settings.sensor_relay_channels,
            active_low=ctx.settings.sensor_relay_active_low, mapping=mapping,
            loss_behavior=ctx.settings.sensor_relay_loss_behavior,
        )
        self.bridge.enabled = True
        self.ctx.sensor_relay_state = self.bridge.state
        self.ctx.model.sensor_change = self.wake_event.set
        self.last_error: str | None = None
        self.link_was_lost = False
        self.thread = threading.Thread(target=self._run, name="bionic-sensor-relay", daemon=True)

    def start(self) -> None:
        self.transport.connect()
        self._sync(force_read=True)
        self.thread.start()
        self.ctx.event("АППАРАТУРА", "USB2", "аппаратный режим физического реле включён")

    def _run(self) -> None:
        next_health = time.monotonic() + 0.5
        while not self.stop_event.is_set():
            self.wake_event.wait(0.2)
            self.wake_event.clear()
            if self.stop_event.is_set():
                break
            now = time.monotonic()
            force_read = now >= next_health
            self._sync(force_read=force_read, now=now)
            if force_read:
                next_health = now + 0.5

    def _sync(self, *, force_read: bool = False, now: float | None = None) -> None:
        previous_desired = self.bridge.state.desired
        previous_confirmed = self.bridge.state.confirmed
        previous_online = self.bridge.state.online
        state = self.bridge.sync(self.ctx.model, force_read=force_read, now=now)
        if state.desired != previous_desired:
            self.ctx.event("RS485", "USB2", f"требуемое состояние 0x{state.desired:04X}")
        if state.online and (
            state.confirmed != previous_confirmed or not previous_online
        ):
            self.ctx.event("RS485", "USB2", f"FC01 подтверждено 0x{state.confirmed or 0:04X}")
        if (
            state.online and self.link_was_lost
            and state.confirmed == state.desired
        ):
            self.ctx.event(
                "АППАРАТУРА", "USB2",
                f"связь восстановлена; правильное состояние реле установлено и подтверждено 0x{state.desired:04X}",
            )
            self.link_was_lost = False
        elif not state.online and previous_online:
            self.ctx.event(
                "АППАРАТУРА", "USB2",
                f"потеря связи с физическим реле: {state.error or 'нет подтверждения'}",
            )
            self.link_was_lost = True
        elif not state.online and state.error:
            self.link_was_lost = True
        if state.error and state.error != self.last_error:
            self.ctx.event("RS485", "USB2", state.error)
        self.last_error = state.error

    def stop(self) -> None:
        self.stop_event.set()
        self.wake_event.set()
        if self.thread.is_alive():
            self.thread.join(timeout=1)
        self.transport.disconnect()
        self.bridge.state.online = False
        self.bridge.state.confirmed = None
        self.ctx.model.sensor_change = lambda: None


def _start_bridge(ctx: BionicContext) -> BridgeRunner | None:
    if not ctx.settings.hardware_mode:
        return None
    runner = BridgeRunner(ctx)
    runner.start()
    return runner


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Цифровой имитатор физической установки Bionic Mini")
    parser.add_argument("--home", type=Path, default=Path.cwd(), help="каталог настроек и журнала")
    parser.add_argument("--config", type=Path, help="файл bionic-immitator.ini")
    parser.add_argument("--test-mode", action="store_true", help="разрешить явно помеченные ручные выходы")
    parser.add_argument("--no-controller", action="store_true", help="не открывать USB №1 в интерактивном режиме")
    parser.add_argument("command", nargs=argparse.REMAINDER)
    return parser


def main() -> int:
    args = _parser().parse_args()
    home = args.home.resolve()
    config = args.config.resolve() if args.config else None
    ctx: BionicContext | None = None
    runner: ModelRunner | None = None
    server: ModbusSlaveServer | None = None
    bridge_runner: BridgeRunner | None = None
    exit_code = 0

    def stop_hardware() -> None:
        nonlocal server, bridge_runner
        errors: list[str] = []
        if server is not None:
            try:
                server.stop()
            except (RuntimeError, OSError) as exc:
                errors.append(f"USB №1: {exc}")
            finally:
                server = None
        if bridge_runner is not None:
            try:
                bridge_runner.stop()
            except (RuntimeError, OSError) as exc:
                errors.append(f"USB №2: {exc}")
            finally:
                bridge_runner = None
        if errors:
            raise RuntimeError("; ".join(errors))

    def start_hardware() -> None:
        nonlocal server, bridge_runner
        if ctx is None:
            return
        if not args.no_controller:
            bus = build_default_bus(ctx.model, ctx.settings)
            transport = SerialSlaveTransport(
                ctx.settings.controller_port, ctx.settings.controller_baudrate,
                ctx.settings.controller_parity, ctx.settings.controller_stopbits,
            )
            server = ModbusSlaveServer(bus, transport, home / f".{ctx.settings.controller_port}.bionic.lock")
            server.start()
        bridge_runner = _start_bridge(ctx)

    def reconnect_hardware() -> None:
        stop_hardware()
        start_hardware()

    try:
        ctx = make_context(home, config, test_mode=args.test_mode)
        if args.command:
            execute_command(ctx, " ".join(args.command))
        else:
            runner = ModelRunner(ctx)
            runner.start()
            start_hardware()
            if sys.stdin.isatty() and sys.stdout.isatty():
                from .bionic_tui import run_tui
                run_tui(ctx, reconnect_hardware)
            else:
                print_view(ctx.console, ctx.view, ctx.model, ctx.journal, ctx.settings, ctx.draft, ctx.saved, ctx.sensor_relay_state)
                while True:
                    try:
                        line = input("bionic-immitator> ")
                        result = execute_command(ctx, line)
                        if result == "exit":
                            break
                        if result == "reconnect":
                            reconnect_hardware()
                    except (ValueError, RuntimeError) as exc:
                        ctx.console.print(f"[red]Ошибка:[/red] {exc}")
                    except (EOFError, KeyboardInterrupt):
                        break
    except (ValueError, RuntimeError, OSError) as exc:
        Console(stderr=True).print(f"[red]Ошибка:[/red] {exc}")
        exit_code = 1
    finally:
        cleanup_errors: list[str] = []
        try:
            stop_hardware()
        except (ValueError, RuntimeError, OSError) as exc:
            cleanup_errors.append(f"остановка оборудования: {exc}")
        try:
            if runner is not None and runner.thread.is_alive():
                runner.stop()
        except (ValueError, RuntimeError, OSError) as exc:
            cleanup_errors.append(f"остановка физической модели: {exc}")
        if ctx is not None:
            try:
                save_runtime_state(ctx)
                ctx.event("СИСТЕМА", "simulation-state", "физическое состояние автоматически сохранено при выходе")
            except (ValueError, RuntimeError, OSError) as exc:
                cleanup_errors.append(f"сохранение состояния: {exc}")
            try:
                ctx.journal.compact()
            except (ValueError, RuntimeError, OSError) as exc:
                cleanup_errors.append(f"сохранение журнала: {exc}")
        if cleanup_errors:
            Console(stderr=True).print(
                "[red]Ошибка завершения:[/red] " + "; ".join(cleanup_errors)
            )
            exit_code = 1
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
