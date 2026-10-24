import os
from dataclasses import replace

import pytest

from rtuforge.bionic_cli import apply_model_settings, execute_command, make_context
from rtuforge.bionic_config import BionicSettings, load_settings, save_settings
from rtuforge.bionic_equipment import (
    EquipmentHealth, lifetime_for_new_equipment, parse_equipment_profile,
    synchronize_wear_rate,
)
from rtuforge.bionic_model import Alarm, AlarmState, BionicModel


def test_synchronized_hp1_failure_time_is_240_seconds_not_old_180():
    profile = parse_equipment_profile(BionicSettings().equipment_profile)["hp1"]
    profile = synchronize_wear_rate(replace(profile, failure_s=240.0))
    assert lifetime_for_new_equipment(profile).effective_s == pytest.approx(240.0)
    health = EquipmentHealth.create(profile)
    for _ in range(2399):
        health.update(True, False, 0.1)
    assert not health.failed
    health.update(True, False, 0.2)
    assert health.failed


def test_existing_wear_can_fail_earlier_after_synchronization():
    profile = parse_equipment_profile(BionicSettings().equipment_profile)["hp1"]
    health = EquipmentHealth.create(synchronize_wear_rate(replace(profile, failure_s=240.0)))
    health.damage = 0.5
    elapsed = 0.0
    while not health.failed:
        health.update(True, False, 0.1)
        elapsed += 0.1
    assert elapsed == pytest.approx(122.5, abs=0.2)


def test_sync_command_survives_restart_without_resetting_live_damage(tmp_path):
    ctx = make_context(tmp_path)
    ctx.model.drives["hp1"].health.damage = 0.37
    execute_command(ctx, "equipment set hp1 failure_s 240 --sync-wear")
    execute_command(ctx, "settings apply")
    assert ctx.model.drives["hp1"].health.damage == 0.37
    execute_command(ctx, "settings save")
    restored = make_context(tmp_path)
    profile = restored.model.drives["hp1"].health.profile
    assert profile.failure_s == 240
    assert lifetime_for_new_equipment(profile).effective_s == pytest.approx(240)
    assert restored.model.drives["hp1"].health.damage == 0  # state is intentionally separate


def test_checkpoint_restores_physics_alarms_and_rupture_but_not_controller_commands(tmp_path):
    ctx = make_context(tmp_path)
    model = ctx.model
    model.tanks["bp"].volume_l = 123.4
    model.tanks["bp"].solute_mass = 456.7
    model.drives["hp1"].health.damage = 0.42
    model.pipe_ruptured = True
    model.total_leak_l = 9.5
    model.current_leak_flow_lpm = 1.5
    model.total_plant_water_uptake_l = 2.5
    model.total_irrigation_evaporation_l = 0.75
    model.alarms[("PIPE_RUPTURE", "pipe")] = Alarm("PIPE_RUPTURE", "pipe", AlarmState.ACTIVE)
    model.set_relay(22, True)
    model.set_analog_output(2, 1, 7000)
    model.drives["hp1"].run_register = True
    execute_command(ctx, "sim state save авария-1")

    model.tanks["bp"].volume_l = 1
    model.tanks["bp"].solute_mass = 2
    model.drives["hp1"].health.damage = 0
    model.pipe_ruptured = False
    model.total_leak_l = 0
    model.current_leak_flow_lpm = 0
    model.total_plant_water_uptake_l = 0
    model.total_irrigation_evaporation_l = 0
    model.alarms.clear()
    model.set_relay(22, False)
    model.set_analog_output(2, 1, 1000)
    model.drives["hp1"].run_register = False
    execute_command(ctx, "sim state load авария-1 --confirm")

    assert model.tanks["bp"].volume_l == 123.4
    assert model.tanks["bp"].solute_mass == 456.7
    assert model.drives["hp1"].health.damage == 0.42
    assert model.pipe_ruptured and model.total_leak_l == 9.5
    assert model.current_leak_flow_lpm == 1.5
    assert model.total_plant_water_uptake_l == 2.5
    assert model.total_irrigation_evaporation_l == 0.75
    assert model.alarms[("PIPE_RUPTURE", "pipe")].state == AlarmState.ACTIVE
    assert not model.relay(22)
    assert model.analog_outputs[(2, 1)] == 1000
    assert not model.drives["hp1"].run_register
    execute_command(ctx, "sim state list")
    assert "авария-1" in ctx.notice


def test_checkpoint_load_requires_confirmation_and_rejects_path(tmp_path):
    ctx = make_context(tmp_path)
    execute_command(ctx, "sim state save safe")
    with pytest.raises(ValueError, match="требует подтверждения"):
        execute_command(ctx, "sim state load safe")
    with pytest.raises(ValueError, match="без пути"):
        execute_command(ctx, "sim state save ../escape")


def test_atomic_config_save_preserves_original_when_replace_fails(tmp_path, monkeypatch):
    path = tmp_path / "bionic-immitator.ini"
    save_settings(path, BionicSettings())
    original = path.read_bytes()
    monkeypatch.setattr(os, "replace", lambda _source, _target: (_ for _ in ()).throw(OSError("boom")))
    with pytest.raises(OSError, match="boom"):
        save_settings(path, replace(BionicSettings(), fill_flow_lpm=9.0))
    assert path.read_bytes() == original
    assert not list(tmp_path.glob("*.tmp"))


def test_legacy_config_gets_defaults_and_backup_on_format_upgrade(tmp_path):
    path = tmp_path / "bionic-immitator.ini"
    path.write_text("[tanks]\nfill_flow_lpm = 7.25\n", encoding="utf-8")
    settings = load_settings(path)
    assert settings.fill_flow_lpm == 7.25
    assert settings.bp_capacity_l == BionicSettings().bp_capacity_l
    save_settings(path, settings)
    assert (tmp_path / "bionic-immitator.ini.v1.bak").read_text(encoding="utf-8") == "[tanks]\nfill_flow_lpm = 7.25\n"
    assert "version = 2" in path.read_text(encoding="utf-8")


def test_invalid_config_identifies_section_and_parameter(tmp_path):
    path = tmp_path / "bionic-immitator.ini"
    path.write_text("[pressure]\nvalve_pressure_response_ms = nope\n", encoding="utf-8")
    with pytest.raises(ValueError, match=r"\[pressure\] valve_pressure_response_ms"):
        load_settings(path)


def test_representative_settings_from_every_subsystem_are_applied_after_restart(tmp_path):
    settings = replace(
        BionicSettings(),
        model_interval_ms=75,
        bo_capacity_l=550,
        bo_min_threshold_l=80,
        bo_max_threshold_l=420,
        fill_flow_lpm=6.5,
        rack1_tier_flow_lpm=3.25,
        plant_water_uptake_fraction=0.007,
        irrigation_evaporation_fraction=0.003,
        pressure_rise_s=8.0,
        blockage_severity=44,
        ponics_ec_target_ms_cm=2.75,
        tap_ph=7.4,
        nutrient_absorption_fraction=0.08,
        hp1_ramp_up_s=7.0,
        hp2_nominal_current_a=15.0,
        simulation_speed=2.0,
    )
    save_settings(tmp_path / "bionic-immitator.ini", settings)
    restored = make_context(tmp_path)
    model = restored.model
    assert restored.settings == settings
    assert model.tanks["bo"].capacity_l == 550
    assert model.sensors["bo-min"].threshold_l == 80
    assert model.fill_flow_lpm == 6.5
    assert model.tiers["tier-1"].flow_lpm == 3.25
    assert model.plant_water_uptake_fraction == 0.007
    assert model.irrigation_evaporation_fraction == 0.003
    assert model.pressure_rise_s == 8.0
    assert model.blockage_severity == 44
    assert model.ponics.settings[33] == 275
    assert model.tap_profile["ph"] == 7.4
    assert model.nutrient_absorption_fraction == 0.08
    assert model.drives["hp1"].ramp_up_s == 7.0
    assert model.drives["hp2"].nominal_current_a == 15.0
    assert model.speed == 2.0


def test_all_declared_settings_round_trip_exactly(tmp_path):
    path = tmp_path / "bionic-immitator.ini"
    settings = BionicSettings()
    save_settings(path, settings)
    assert load_settings(path) == settings
    assert not hasattr(settings, "hp1_mechanical_damage")
    assert not hasattr(settings, "hp2_mechanical_failure")


def test_applying_profile_does_not_repair_existing_damage(tmp_path):
    ctx = make_context(tmp_path)
    ctx.model.pumps["bo-to-bp"].health.damage = 0.61
    ctx.model.drives["hp2"].health.failure = "jammed"
    ctx.model.drives["hp2"].health.state = "FAILED"
    execute_command(ctx, "equipment set bo-to-bp failure_s 150 --sync-wear")
    execute_command(ctx, "equipment set hp2 failure_s 220 --sync-wear")
    execute_command(ctx, "settings apply")
    assert ctx.model.pumps["bo-to-bp"].health.damage == 0.61
    assert ctx.model.drives["hp2"].health.failure == "jammed"


def test_all_five_equipment_profiles_persist_independently(tmp_path):
    ctx = make_context(tmp_path)
    expected = {}
    for index, equipment_id in enumerate(("bo-to-bp", "bso1-to-bp", "bso2-to-bp", "hp1", "hp2")):
        value = 130 + index * 20
        execute_command(ctx, f"equipment set {equipment_id} failure_s {value} --sync-wear")
        expected[equipment_id] = value
    execute_command(ctx, "settings save")
    profiles = parse_equipment_profile(make_context(tmp_path).settings.equipment_profile)
    assert {equipment_id: profiles[equipment_id].failure_s for equipment_id in expected} == expected


def test_immediately_applied_convenience_commands_are_saveable_and_restored(tmp_path):
    ctx = make_context(tmp_path)
    commands = (
        "tank bo capacity 600",
        "tank bo fill-rate 6.25",
        "pump bo-to-bp flow 11.5",
        "irrigation shelf 1 flow-per-tier 3.5",
        "pressure range 0 88",
        "pressure rise-time 7",
        "pressure fall-time 6",
        "pipe rupture-threshold 74",
        "sensor bo-min threshold 80",
        "fault leak rate 9",
        "fault blockage severity 55",
        "sim speed 2.5",
    )
    for command in commands:
        execute_command(ctx, command)
    execute_command(ctx, "settings save")
    restored = make_context(tmp_path)
    assert restored.model.tanks["bo"].capacity_l == 600
    assert restored.model.fill_flow_lpm == 6.25
    assert restored.model.pumps["bo-to-bp"].flow_lpm == 11.5
    assert restored.model.tiers["tier-1"].flow_lpm == 3.5
    assert restored.model.pressure_max_bar == 88
    assert restored.model.pressure_rise_s == 7
    assert restored.model.pressure_fall_s == 6
    assert restored.model.rupture_threshold_bar == 74
    assert restored.model.sensors["bo-min"].threshold_l == 80
    assert restored.model.leak_rate_lpm == 9
    assert restored.model.blockage_severity == 55
    assert restored.model.speed == 2.5
