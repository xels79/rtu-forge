from pathlib import Path

import configparser
import pytest
from rich.console import Console

from rtuforge import bionic_cli
from rtuforge.bionic_cli import execute_command, make_context
from rtuforge.bionic_completion import completion_candidates
from rtuforge.bionic_lights import FACTORY_LIGHT_PROFILE, LightType, parse_light_profile
from rtuforge.crc import append_crc


def context(tmp_path: Path):
    console = Console(record=True, width=120)
    return make_context(tmp_path, console=console), console


def test_help_and_status_do_not_create_configuration_or_connect(tmp_path):
    ctx, console = context(tmp_path)
    execute_command(ctx, "help")
    execute_command(ctx, "status")
    text = console.export_text()
    assert "цифровая физическая установка" in text
    assert "BIONIC IMMITATOR" in text
    assert not (tmp_path / "bionic-immitator.ini").exists()


def test_tank_sensor_fault_pipe_and_alarm_commands(tmp_path):
    ctx, _ = context(tmp_path)
    execute_command(ctx, "tank bo level 60%")
    assert ctx.model.tanks["bo"].volume_l == 300
    execute_command(ctx, "sensor bo-min force on")
    assert ctx.model.sensors["bo-min"].forced is True
    execute_command(ctx, "fault leak on")
    execute_command(ctx, "fault leak rate 9.5")
    execute_command(ctx, "fault blockage on")
    execute_command(ctx, "fault blockage severity 40")
    assert ctx.model.leak_enabled and ctx.model.leak_rate_lpm == 9.5
    assert ctx.model.blockage_enabled and ctx.model.blockage_severity == 40
    ctx.model.pipe_ruptured = True
    execute_command(ctx, "fault blockage off")
    assert not ctx.model.blockage_enabled
    assert ctx.model.pipe_ruptured
    execute_command(ctx, "alarm reset all")
    assert ctx.model.pipe_ruptured
    execute_command(ctx, "pipe repair")
    assert not ctx.model.pipe_ruptured


def test_pump_failure_and_repair_are_physical_only(tmp_path):
    ctx, _ = context(tmp_path)
    execute_command(ctx, "fault pump hp1 jammed")
    assert ctx.model.drives["hp1"].mechanical_failure == "jammed"
    assert not any(sensor.forced is not None for sensor in ctx.model.sensors.values())
    execute_command(ctx, "pump hp1 repair")
    assert ctx.model.drives["hp1"].mechanical_failure == "none"


def test_settings_save_and_apply_are_independent(tmp_path):
    ctx, _ = context(tmp_path)
    execute_command(ctx, "settings set hp1_address 17")
    assert ctx.settings.hp1_address == 7
    assert ctx.draft.hp1_address == 17
    execute_command(ctx, "settings save")
    assert ctx.settings.hp1_address == 7
    parser = configparser.ConfigParser()
    parser.read(ctx.config_path, encoding="utf-8")
    assert parser.getint("devices", "hp1_address") == 17
    assert execute_command(ctx, "settings apply") == "reconnect"
    assert ctx.settings.hp1_address == 17


def test_physics_settings_are_restored_and_apply_without_resetting_level(tmp_path):
    ctx, _ = context(tmp_path)
    execute_command(ctx, "tank bo level 300")
    execute_command(ctx, "settings set fill_flow_lpm 7.5")
    execute_command(ctx, "settings set bo_capacity_l 600")
    assert execute_command(ctx, "settings apply") is None
    assert ctx.model.fill_flow_lpm == 7.5
    assert ctx.model.tanks["bo"].capacity_l == 600
    assert ctx.model.tanks["bo"].volume_l == 300
    execute_command(ctx, "settings save")
    restored = make_context(tmp_path)
    assert restored.model.fill_flow_lpm == 7.5
    assert restored.model.tanks["bo"].capacity_l == 600


def test_sim_reset_requires_confirmation_and_does_not_mutate_old_outputs(tmp_path):
    ctx, _ = context(tmp_path)
    ctx.model.set_relay(22, True)
    old = ctx.model
    with pytest.raises(ValueError, match="явного подтверждения"):
        execute_command(ctx, "sim reset")
    assert old.relay(22)
    assert execute_command(ctx, "sim reset --confirm") == "reconnect"
    assert old.relay(22)  # reset never sends an OFF to real/controller-owned outputs
    assert not ctx.model.relay(22)


def test_light_profile_can_apply_save_reload_and_restore_independently(tmp_path):
    ctx, _ = context(tmp_path)
    ctx.model.tanks["bo"].volume_l = 321
    ctx.model.set_relay(3, True)
    ctx.model.set_analog_output(2, 1, 7000)
    outputs_before = (tuple(ctx.model.relays), dict(ctx.model.analog_outputs))
    execute_command(ctx, "light set zone-1 type NONE")
    assert ctx.settings.light_profile == FACTORY_LIGHT_PROFILE
    execute_command(ctx, "light apply")
    assert ctx.model.lights["zone-1"].light_type == LightType.NONE
    assert ctx.model.tanks["bo"].volume_l == 321
    assert (tuple(ctx.model.relays), ctx.model.analog_outputs) == outputs_before
    execute_command(ctx, "light save")
    restored = make_context(tmp_path)
    assert restored.model.lights["zone-1"].light_type == LightType.NONE
    execute_command(ctx, "light restore-defaults")
    assert ctx.draft.light_profile == FACTORY_LIGHT_PROFILE
    assert ctx.model.lights["zone-1"].light_type == LightType.NONE
    assert ctx.model.tanks["bo"].volume_l == 321
    assert (tuple(ctx.model.relays), ctx.model.analog_outputs) == outputs_before


def test_light_types_channel_assignment_and_conflicts_are_validated(tmp_path):
    ctx, _ = context(tmp_path)
    execute_command(ctx, "light set zone-1 type SPECTRAL_4")
    with pytest.raises(ValueError, match="Modbus ID 0"):
        execute_command(ctx, "light apply")
    for role, channel in zip(("red", "far_red", "blue", "white"), range(1, 5)):
        execute_command(ctx, f"light set zone-1 channel {role} 4 {channel}")
    execute_command(ctx, "light apply")
    assert ctx.model.lights["zone-1"].light_type == LightType.SPECTRAL_4
    assert [(item.device_id, item.channel) for item in ctx.model.lights["zone-1"].channels] == [
        (4, 1), (4, 2), (4, 3), (4, 4),
    ]
    execute_command(ctx, "light set zone-3 channel brightness 4 1")
    with pytest.raises(ValueError, match="Конфликт ID4/AO1"):
        execute_command(ctx, "light apply")
    assert ctx.model.lights["zone-3"].channels[0].device_id == 2


def test_light_profile_default_matches_bionic_mini_map(tmp_path):
    ctx, _ = context(tmp_path)
    profile = parse_light_profile(ctx.settings.light_profile)
    assert [light.light_type for light in profile] == [
        LightType.SINGLE, LightType.SPECTRAL_4, LightType.SINGLE,
        LightType.SINGLE, LightType.SPECTRAL_4, LightType.SINGLE,
    ]
    assert [light.power_relay for light in profile] == [3, 4, 5, 6, 7, 8]
    assert [(channel.device_id, channel.channel) for channel in profile[4].channels] == [
        (2, 8), (3, 1), (3, 2), (3, 3),
    ]


def test_light_rejects_reserved_do_and_invalid_voltage_range(tmp_path):
    ctx, _ = context(tmp_path)
    execute_command(ctx, "light set zone-1 relay 9")
    with pytest.raises(ValueError, match="занят другой подсистемой"):
        execute_command(ctx, "light apply")
    execute_command(ctx, "light set zone-1 relay 3")
    execute_command(ctx, "light set zone-1 voltage 8 2")
    with pytest.raises(ValueError, match="диапазон напряжения"):
        execute_command(ctx, "light save")


def test_manual_output_requires_explicit_test_mode(tmp_path):
    ctx, _ = context(tmp_path)
    with pytest.raises(ValueError, match="--test-mode"):
        execute_command(ctx, "relay force 22 on")
    ctx.test_mode = True
    execute_command(ctx, "relay force 22 on")
    assert ctx.model.relay(22)
    assert "ТЕСТОВОЕ" in ctx.journal.events[-1].message


def test_log_keeps_three_rows_on_main_and_exports_csv(tmp_path):
    ctx, console = context(tmp_path)
    for index in range(5):
        ctx.event("БАК", "bo", f"event-{index}")
    execute_command(ctx, "status")
    text = console.export_text()
    assert "event-2" in text and "event-4" in text
    assert "event-1" not in text
    execute_command(ctx, "log filter tanks")
    execute_command(ctx, "log export events.csv")
    exported = (tmp_path / "events.csv").read_text(encoding="utf-8-sig")
    assert "event-4" in exported


def test_one_shot_help_uses_entry_without_serial(monkeypatch, tmp_path):
    monkeypatch.setattr(bionic_cli.sys, "argv", ["bionic-immitator", "--home", str(tmp_path), "help"])
    assert bionic_cli.main() == 0
    assert not (tmp_path / "bionic-immitator.ini").exists()


def test_completion_covers_pages_settings_and_protects_manual_outputs():
    assert completion_candidates("vi") == ["view"]
    assert "pressure" in completion_candidates("view ")
    assert "hp1_address" in completion_candidates("settings set hp")
    assert "relay" not in completion_candidates("")
    assert "relay" in completion_candidates("", test_mode=True)
    assert "jammed" in completion_candidates("fault pump hp1 ")
    assert completion_candidates("pump hp2 ") == ["repair"]


@pytest.mark.parametrize("command", ["tank unknown level 1", "fault leak maybe", "view nowhere", "sim speed 0"])
def test_command_validation_is_explicit(tmp_path, command):
    ctx, _ = context(tmp_path)
    with pytest.raises(ValueError):
        execute_command(ctx, command)


def test_nested_ponics_and_drive_views_and_bp_only_dosing(tmp_path):
    ctx, _ = context(tmp_path)
    ctx.screen_mode = True
    execute_command(ctx, "view ponics settings")
    assert ctx.view == "ponics-settings"
    execute_command(ctx, "view ponics registers")
    assert ctx.view == "ponics-registers"
    execute_command(ctx, "view drive hp2")
    assert ctx.view == "drive-hp2"
    other = {key: tank.solute_mass for key, tank in ctx.model.tanks.items() if key != "bp"}
    execute_command(ctx, "ponics dose a 12.5")
    assert ctx.model.ponics.dosing_totals["a"] == 12.5
    assert {key: tank.solute_mass for key, tank in ctx.model.tanks.items() if key != "bp"} == other
    assert not any(name in {"ponics_tank", "ponics_tank_id", "ponics_served_tank"} for name in ctx.settings.__dataclass_fields__)


def test_ponics_register_write_can_be_explicitly_saved_as_start_profile(tmp_path):
    ctx, _ = context(tmp_path)
    execute_command(ctx, "ponics set 33 275")
    assert ctx.model.ponics.settings[33] == 275
    assert ctx.draft.ponics_ec_target_ms_cm == 2.75
    execute_command(ctx, "settings save")
    restored = make_context(tmp_path)
    assert restored.model.ponics.settings[33] == 275


def test_idd_parameter_write_is_staged_and_saved_explicitly(tmp_path):
    ctx, _ = context(tmp_path)
    bus = bionic_cli.build_default_bus(ctx.model, ctx.settings)
    request_frame = append_crc(bytes.fromhex("07 06 00 6B 00 19"))
    assert bus.handle(request_frame)
    assert bus.handle(append_crc(bytes.fromhex("07 06 00 D2 00 96")))
    assert bus.handle(append_crc(bytes.fromhex("07 06 03 30 00 00")))
    assert ctx.model.drives["hp1"].ramp_up_s == 2.5
    assert ctx.draft.hp1_ramp_up_s == 2.5
    assert ctx.draft.hp1_nominal_current_a == 15.0
    assert not ctx.draft.hp1_overload_protection_enabled
    execute_command(ctx, "settings save")
    restored = make_context(tmp_path).settings
    assert restored.hp1_ramp_up_s == 2.5
    assert restored.hp1_nominal_current_a == 15.0
    assert not restored.hp1_overload_protection_enabled
