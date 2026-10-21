from pathlib import Path

import configparser
import pytest
from rich.console import Console

from rtuforge import bionic_cli
from rtuforge.bionic_cli import execute_command, make_context
from rtuforge.bionic_completion import completion_candidates


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
    execute_command(ctx, "alarm reset all")
    assert ctx.model.pipe_ruptured
    execute_command(ctx, "pipe repair")
    assert not ctx.model.pipe_ruptured


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
