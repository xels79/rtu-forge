import pytest

from rtuforge.bionic_equipment import EquipmentProfile
from rtuforge.bionic_model import AlarmState, BionicModel


def running_model() -> BionicModel:
    model = BionicModel()
    model.running = True
    return model


def enable_pressure(model: BionicModel, *, hz: float = 29.0, tiers=(9, 10, 11)) -> None:
    for relay in (1, 19, 21, 32, *tiers):
        model.set_relay(relay, True)
    model.drives["hp1"].setpoint_hz = hz
    model.tick(10)


def test_osmosis_fill_obeys_do22_and_never_closes_it_on_overflow():
    model = running_model()
    initial = model.tanks["bo"].volume_l
    model.tick(60)
    assert model.tanks["bo"].volume_l == initial
    model.set_relay(22, True)
    model.tick(60)
    assert model.tanks["bo"].volume_l == pytest.approx(initial + 3)
    model.tanks["bo"].volume_l = model.tanks["bo"].capacity_l
    model.tick(60)
    assert model.relay(22)
    assert model.tanks["bo"].volume_l == model.tanks["bo"].capacity_l
    assert model.tanks["bo"].overflow_l == pytest.approx(3)
    assert model.alarms[("TANK_OVERFLOW", "bo")].state == AlarmState.ACTIVE


def test_incoming_water_meter_logs_total_when_fill_output_closes():
    events = []
    model = BionicModel(lambda kind, subject, message: events.append((kind, subject, message)))
    model.running = True
    model.water_meter.total_l = 120.0
    model.set_relay(22, True)
    model.tick(60)
    model.set_relay(22, False)

    assert model.water_meter.total_l == pytest.approx(123.0)
    assert events[-1] == (
        "RS485", "do-22",
        "Клапан наполнения осмоса: ВКЛ → ВЫКЛ; подача закрыта; "
        "счётчик входящей воды 123.000 л",
    )


@pytest.mark.parametrize(
    ("channel", "description"),
    (
        (1, "Насос подпора"),
        (3, "Питание света: Стеллаж 1, ярус 1"),
        (10, "Полив: стеллаж 1, ярус 2"),
        (15, "Резервный выход"),
        (32, "RUN частотника HP1"),
    ),
)
def test_every_do_log_has_a_human_readable_description(channel, description):
    events = []
    model = BionicModel(lambda kind, subject, message: events.append((kind, subject, message)))
    model.set_relay(channel, True)
    assert events[-1] == ("RS485", f"do-{channel}", f"{description}: ВЫКЛ → ВКЛ")


def test_max_sensor_below_capacity_does_not_stop_fill_or_mean_overflow():
    model = running_model()
    model.sensors["bo-max"].threshold_l = 400
    model.set_tank_level("bo", 399)
    model.set_relay(22, True)
    model.tick(60)
    assert model.sensors["bo-max"].value
    assert model.tanks["bo"].volume_l == pytest.approx(402)
    assert model.tanks["bo"].overflow_l == 0
    assert model.relay(22)
    model.tick(2000)
    assert model.tanks["bo"].volume_l == 500
    assert model.tanks["bo"].overflow_l > 0


def test_stuck_fill_valve_is_explicit_fault_effect():
    model = running_model()
    model.fill_valve_stuck_open = True
    model.tick(60)
    assert model.tanks["bo"].volume_l == pytest.approx(253)
    assert not model.relay(22)


@pytest.mark.parametrize(
    "pump_id,relay,source",
    [("bo-to-bp", 2, "bo"), ("bso1-to-bp", 17, "bso1"), ("bso2-to-bp", 18, "bso2")],
)
def test_transfer_routes_end_in_broth(pump_id, relay, source):
    model = running_model()
    model.pumps[pump_id].start_s = 0
    before_source = model.tanks[source].volume_l
    before_broth = model.tanks["bp"].volume_l
    model.set_relay(relay, True)
    model.tick(60)
    moved = model.pumps[pump_id].flow_lpm
    assert model.tanks[source].volume_l == pytest.approx(before_source - moved)
    assert model.tanks["bp"].volume_l == pytest.approx(before_broth + moved)


def test_both_drain_returns_can_run_together():
    model = running_model()
    for pump in model.pumps.values():
        pump.start_s = 0
    before = model.tanks["bp"].volume_l
    model.set_relay(17, True)
    model.set_relay(18, True)
    model.tick(60)
    assert model.tanks["bp"].volume_l == pytest.approx(before + 16)


def test_empty_source_does_not_rewrite_controller_run_command():
    model = running_model()
    model.tanks["bso1"].volume_l = 0
    model.pumps["bso1-to-bp"].start_s = 0
    model.set_relay(17, True)
    model.tick(60)
    assert model.relay(17)
    assert model.pumps["bso1-to-bp"].actual_flow_lpm == 0
    assert model.pumps["bso1-to-bp"].health.dry_running
    assert ("WATER_SHORTAGE", "bso1") in model.alarms


def fast_failure_profile(failure_type: str = "motor_failure") -> EquipmentProfile:
    return EquipmentProfile(
        dry_run_warning_s=0.1,
        overheat_s=0.2,
        degrade_s=0.3,
        failure_s=0.4,
        heating_rate_per_s=1.0,
        cooling_rate_per_s=1.0,
        wear_rate_per_s=1.0,
        wear_flow_reduction=0.8,
        initial_state="HEALTHY",
        failure_type=failure_type,
    )


def test_transfer_dry_run_progresses_to_failure_without_changing_board_output():
    events = []
    model = BionicModel(lambda kind, subject, message: events.append((kind, subject, message)))
    model.running = True
    pump = model.pumps["bo-to-bp"]
    pump.start_s = 0
    pump.health.configure(fast_failure_profile())
    model.tanks["bo"].take_solution(model.tanks["bo"].volume_l)
    model.set_relay(pump.relay, True)
    states = []
    for _ in range(4):
        model.tick(0.1)
        states.append(pump.health.state)
    assert states == ["DRY_RUNNING", "OVERHEATED", "DEGRADED", "FAILED"]
    assert pump.actual_flow_lpm == 0
    assert model.relay(pump.relay)
    assert pump.repair_required
    assert any("команда платы остаётся" in message for _, _, message in events)


def test_water_return_and_stop_end_dry_run_but_preserve_accumulated_wear():
    model = running_model()
    pump = model.pumps["bo-to-bp"]
    pump.start_s = 0
    pump.health.configure(fast_failure_profile())
    model.tanks["bo"].take_solution(model.tanks["bo"].volume_l)
    model.set_relay(pump.relay, True)
    model.tick(0.2)
    damage = pump.health.damage
    model.set_tank_level("bo", 10)
    model.tick(0.1)
    assert not pump.health.dry_running
    assert pump.health.damage == pytest.approx(damage)
    model.set_relay(pump.relay, False)
    model.tick(1)
    assert pump.health.damage == pytest.approx(damage)


def test_failure_type_controls_remaining_transfer_performance_without_self_repair():
    model = running_model()
    pump = model.pumps["bso2-to-bp"]
    pump.start_s = 0
    pump.health.failure = "impeller_damage"
    pump.health.state = "FAILED"
    model.set_relay(pump.relay, True)
    model.tick(60)
    assert pump.actual_flow_lpm == pytest.approx(pump.flow_lpm * 0.2)
    assert pump.health.state == "FAILED"
    assert pump.repair_required


def test_hp_dry_run_uses_real_path_and_fails_without_clearing_run_command():
    model = running_model()
    drive = model.drives["hp1"]
    drive.ramp_up_s = 0
    drive.health.configure(fast_failure_profile("impeller_damage"))
    model.set_relay(drive.selector_relay, True)
    model.set_relay(drive.run_relay, True)
    for _ in range(4):
        model.tick(0.1)
    assert drive.health.state == "FAILED"
    assert drive.health.failure == "impeller_damage"
    assert model.drive_input_command(drive)
    assert model.relay(drive.run_relay)
    assert model.high_pressure_bar == 0


@pytest.mark.parametrize("tank_relay,tank_id", [(21, "bo"), (23, "bp")])
def test_irrigation_takes_selected_source_and_returns_to_each_rack_drain(tank_relay, tank_id):
    model = running_model()
    model.tiers["tier-1"].return_delay_s = 0
    before_source = model.tanks[tank_id].volume_l
    before_drain = model.tanks["bso1"].volume_l
    for relay in (1, 19, 32, 9, tank_relay):
        model.set_relay(relay, True)
    model.tick(10)
    assert model.tanks[tank_id].volume_l < before_source
    assert model.tanks["bso1"].volume_l > before_drain
    assert model.operation == "Операция не определена"


def test_pressure_calibration_points_after_settling():
    model = running_model()
    model.pressure_rise_s = 0
    model.boost_rise_s = 0
    enable_pressure(model, hz=29)
    assert model.high_pressure_bar == pytest.approx(30, abs=0.2)
    model.drives["hp1"].setpoint_hz = 42
    model.tick(10)
    assert model.high_pressure_bar == pytest.approx(57, abs=0.2)


def test_fewer_open_tiers_increases_pressure():
    model = running_model()
    model.pressure_rise_s = 0
    model.pressure_fall_s = 0
    model.boost_rise_s = 0
    enable_pressure(model)
    three = model.high_pressure_bar
    model.set_relay(10, False)
    model.set_relay(11, False)
    model.tick(1)
    assert model.high_pressure_bar > three


def test_rupture_latches_without_stopping_controller_and_requires_repair():
    model = running_model()
    model.pressure_rise_s = 0
    model.boost_rise_s = 0
    model.rupture_threshold_bar = 40
    enable_pressure(model, hz=42, tiers=(9,))
    assert model.pipe_ruptured
    assert model.relay(32)
    assert model.high_pressure_bar <= 3
    assert 4000 <= model.analog_raw(2) <= 4480
    model.tick(10)
    assert model.high_pressure_bar <= 3
    model.reset_alarms()
    assert model.pipe_ruptured
    model.repair_pipe()
    model.set_relay(10, True)
    model.set_relay(11, True)
    model.rupture_threshold_bar = 75
    model.tick(1)
    assert model.high_pressure_bar > 3


def test_leak_loses_water_and_blockage_reduces_flow():
    clean = running_model()
    clean.pressure_rise_s = clean.boost_rise_s = 0
    enable_pressure(clean)
    clean_flow = clean.tiers["tier-1"].actual_flow_lpm
    blocked = running_model()
    blocked.pressure_rise_s = blocked.boost_rise_s = 0
    blocked.blockage_enabled = True
    enable_pressure(blocked)
    assert blocked.tiers["tier-1"].actual_flow_lpm < clean_flow
    blocked.leak_enabled = True
    before = blocked.tanks["bo"].volume_l
    blocked.tick(60)
    assert blocked.total_leak_l > 0
    assert blocked.current_leak_flow_lpm > 0
    assert blocked.tanks["bo"].volume_l < before


def test_irrigation_tracks_small_plant_uptake_evaporation_and_solution_degradation():
    model = running_model()
    model.pressure_rise_s = model.boost_rise_s = 0
    model.rupture_threshold_bar = 100
    model.drives["hp1"].ramp_up_s = 0
    model.plant_water_uptake_fraction = 0.005
    model.irrigation_evaporation_fraction = 0.002
    model.nutrient_absorption_fraction = 0.9
    model.deposition_fraction = 0.0
    model.tanks["bso1"].initialize_solution(
        ec_ms_cm=2.0, ph=6.0, temperature_c=20.0, buffer_per_l=1.0,
    )
    ponics_ec_before = model.ponics.registers()[5]
    before_loop = model.irrigation_loop_volume_l
    before_solute = sum(
        model.tanks[tank_id].solute_mass for tank_id in ("bp", "bso1", "bso2")
    )
    for relay in (1, 9, 19, 23, 32):
        model.set_relay(relay, True)

    model.tick(60)

    irrigated = model.tiers["tier-1"].total_l
    assert irrigated == pytest.approx(2.0)
    assert model.total_plant_water_uptake_l == pytest.approx(irrigated * 0.005)
    assert model.total_irrigation_evaporation_l == pytest.approx(irrigated * 0.002)
    assert model.irrigation_loop_volume_l < before_loop
    assert sum(
        model.tanks[tank_id].solute_mass for tank_id in ("bp", "bso1", "bso2")
    ) < before_solute
    assert model.tanks["bso1"].nutrients_consumed > 0

    for relay in (1, 9, 19, 23, 32):
        model.set_relay(relay, False)
    model.pumps["bso1-to-bp"].start_s = 0
    model.set_relay(17, True)
    model.tick(180)
    assert model.ponics.registers()[5] < ponics_ec_before


def test_blockage_is_downstream_resistance_raising_high_and_reducing_flow():
    pressures = []
    flows = []
    resistances = []
    for severity in (0, 40, 70, 90):
        model = running_model()
        model.pressure_rise_s = model.boost_rise_s = 0
        model.rupture_threshold_bar = 100
        model.blockage_enabled = severity > 0
        model.blockage_severity = severity
        enable_pressure(model, hz=42)
        pressures.append(model.high_pressure_bar)
        flows.append(model.calculated_flow_lpm)
        resistances.append(model.hydraulic_resistance)
    assert pressures[0] == pytest.approx(57, abs=0.2)
    assert pressures == sorted(pressures)
    assert flows == sorted(flows, reverse=True)
    assert resistances == sorted(resistances)
    assert model.blockage_position == "после датчика HIGH"


def test_strong_blockage_ruptures_pipe_and_off_does_not_repair_it():
    model = running_model()
    model.pressure_rise_s = model.boost_rise_s = 0
    model.blockage_enabled = True
    model.blockage_severity = 100
    enable_pressure(model, hz=42)
    assert model.pipe_ruptured
    assert model.high_pressure_bar <= 3
    assert model.max_pressure_bar >= 75
    assert model.alarms[("PIPE_RUPTURE", "pipe")].state == AlarmState.ACTIVE
    assert model.relay(32)
    model.blockage_enabled = False
    model.tick(1)
    assert model.pipe_ruptured
    model.repair_pipe()
    model.tick(1)
    assert not model.pipe_ruptured
    assert model.high_pressure_bar == pytest.approx(57, abs=0.2)


def test_blockage_cannot_create_pressure_with_stopped_hp_or_closed_source():
    model = running_model()
    model.pressure_rise_s = model.pressure_fall_s = model.boost_rise_s = 0
    model.blockage_enabled = True
    model.blockage_severity = 100
    model.rupture_threshold_bar = 100
    enable_pressure(model, hz=42)
    model.set_relay(32, False)
    model.tick(0.1)
    assert model.drives["hp1"].actual_hz > 0
    assert model.pressure_target_bar == 0
    assert model.high_pressure_bar == 0
    model.set_relay(32, True)
    model.drives["hp1"].ramp_up_s = 0
    model.set_relay(21, False)
    model.tick(0.2)
    assert model.pressure_target_bar == 0
    assert model.calculated_flow_lpm == 0


def test_running_hp_reacts_quickly_to_tier_valves_and_closed_head():
    model = running_model()
    model.pressure_rise_s = model.boost_rise_s = 0
    model.valve_pressure_response_ms = 200
    model.valve_pressure_close_response_ms = 200
    model.rupture_threshold_bar = 100
    enable_pressure(model, hz=42)
    three = model.high_pressure_bar
    model.set_relay(11, False)
    model.tick(0.05)
    assert three < model.high_pressure_bar < model.pressure_target_bar
    model.tick(0.2)
    two = model.high_pressure_bar
    model.set_relay(10, False)
    model.tick(0.2)
    one = model.high_pressure_bar
    model.set_relay(9, False)
    model.tick(0.2)
    closed = model.high_pressure_bar
    assert three < two < one < closed
    assert closed == pytest.approx(84, abs=0.2)
    model.set_relay(9, True)
    model.set_relay(10, True)
    model.set_relay(11, True)
    model.set_relay(12, True)
    model.set_relay(13, True)
    model.set_relay(14, True)
    model.tick(0.2)
    assert model.high_pressure_bar < three


def test_new_pressure_rise_interrupts_fall_and_starts_from_current_value():
    model = running_model()
    model.boost_rise_s = 0
    model.pressure_rise_s = 0
    model.pressure_fall_s = 4
    model.valve_pressure_response_ms = 2000
    model.rupture_threshold_bar = 100
    model.drives["hp1"].ramp_up_s = 0
    enable_pressure(model, hz=29)
    assert model.high_pressure_bar == pytest.approx(30)

    for relay in (12, 13, 14):
        model.set_relay(relay, True)
    model.tick(0.2)
    falling_value = model.high_pressure_bar
    falling_target = model.pressure_target_bar
    assert falling_target < falling_value < 30
    assert model._valve_response_remaining_s == pytest.approx(1.8)

    model.pressure_rise_s = 4
    model.drives["hp1"].setpoint_hz = 45
    model.tick(0.2)

    rising_target = model.pressure_target_bar
    expected = falling_value + (rising_target - falling_value) * (0.2 / 4)
    assert rising_target > falling_value
    assert model.high_pressure_bar == pytest.approx(expected)
    assert model.high_pressure_bar > falling_value
    assert model._valve_response_remaining_s == 0


def test_boost_restart_immediately_reverses_low_pressure_fall():
    model = running_model()
    model.boost_rise_s = 2
    model.boost_fall_s = 2
    model.set_relay(model.outputs["source_osmosis"], True)
    model.set_relay(model.outputs["boost"], True)
    model.low_pressure_bar = model.boost_pressure_bar

    model.set_relay(model.outputs["boost"], False)
    model.tick(0.5)
    falling_value = model.low_pressure_bar
    assert 0 < falling_value < model.boost_pressure_bar

    model.set_relay(model.outputs["boost"], True)
    model.tick(0.05)

    assert model.low_pressure_bar > falling_value


def test_starting_hp_with_all_tiers_closed_reaches_shutoff_head_and_ruptures():
    model = running_model()
    model.pressure_rise_s = model.boost_rise_s = 0
    enable_pressure(model, hz=42, tiers=())
    assert model.max_pressure_bar == pytest.approx(84, abs=0.2)
    assert model.pipe_ruptured
    assert model.high_pressure_bar <= 3
    assert model.relay(32)


def test_configured_closing_spike_participates_in_rupture_threshold():
    model = running_model()
    model.pressure_rise_s = model.boost_rise_s = 0
    model.valve_pressure_close_response_ms = 200
    model.transient_pressure_spike_coefficient = 3.0
    model.transient_pressure_spike_duration_ms = 100
    enable_pressure(model, hz=42)
    assert not model.pipe_ruptured
    model.set_relay(11, False)
    model.tick(0.05)
    assert model.last_pressure_spike_bar > 0
    assert model.max_pressure_bar >= 75
    assert model.pipe_ruptured
    model.tick(0.2)
    assert model.high_pressure_bar <= 3


@pytest.mark.parametrize(
    "source,terminal,modbus,selected,expected",
    [
        (1, True, False, True, True),
        (1, False, True, True, False),
        (2, True, False, True, False),
        (2, False, True, True, True),
        (1, True, False, False, False),
        (2, False, True, False, False),
        (0, True, True, True, False),
    ],
)
def test_drive_run_source_and_selector_are_not_ored(source, terminal, modbus, selected, expected):
    model = running_model()
    drive = model.drives["hp1"]
    drive.configuration[102] = source
    drive.run_register = modbus
    drive.ramp_up_s = 0.1
    model.set_relay(drive.run_relay, terminal)
    model.set_relay(drive.selector_relay, selected)
    model.tick(0.2)
    assert (drive.actual_hz > 0.1) is expected


def test_pressure_matrix_zero_to_six_tiers_is_monotonic_at_42_hz():
    pressures = []
    for count in range(7):
        model = running_model()
        model.pressure_rise_s = model.boost_rise_s = 0
        model.rupture_threshold_bar = 100
        tiers = tuple(range(9, 9 + count))
        enable_pressure(model, hz=42, tiers=tiers)
        pressures.append(model.high_pressure_bar)
    assert pressures == sorted(pressures, reverse=True)
    assert pressures[0] == pytest.approx(84, abs=0.2)
    assert pressures[3] == pytest.approx(57, abs=0.2)
    assert pressures[6] < pressures[3]


def test_jammed_pump_has_no_pressure_trips_protection_and_keeps_run_command():
    model = running_model()
    model.pressure_rise_s = model.boost_rise_s = 0
    model.rupture_threshold_bar = 100
    drive = model.drives["hp1"]
    drive.mechanical_failure = "jammed"
    drive.overload_trip_s = 0.2
    enable_pressure(model, hz=42)
    assert drive.calculated_current_a > drive.nominal_current_a
    assert drive.fault == 10
    assert drive.run_register is False
    assert model.relay(drive.run_relay)
    assert model.drive_input_command(drive)
    assert not model.drive_commanded(drive)
    assert model.high_pressure_bar == 0
    assert model.calculated_flow_lpm == 0


def test_disabled_protection_and_loss_of_prime_do_not_fake_safe_stop():
    model = running_model()
    drive = model.drives["hp1"]
    drive.mechanical_failure = "jammed"
    drive.overload_protection_enabled = False
    enable_pressure(model, hz=42)
    assert drive.fault == 0
    assert drive.actual_hz > 0
    assert drive.calculated_current_a > drive.nominal_current_a
    drive.mechanical_failure = "loss_of_prime"
    model.tick(1)
    assert drive.fault == 0
    assert drive.actual_hz > 0
    assert drive.calculated_current_a <= drive.no_load_current_a
    assert model.high_pressure_bar < 5


def test_reset_does_not_repair_mechanics_and_jam_retrips():
    model = running_model()
    drive = model.drives["hp1"]
    drive.mechanical_failure = "jammed"
    drive.overload_trip_s = 0.1
    drive.configuration[102] = 2
    drive.run_register = True
    model.set_relay(drive.selector_relay, True)
    model.tick(0.2)
    assert drive.fault == 10
    drive.reset_fault()
    assert drive.mechanical_failure == "jammed"
    model.tick(0.2)
    assert drive.fault == 10
    drive.repair()
    assert drive.mechanical_failure == "none"


def test_level_sensor_delay_hysteresis_and_force_do_not_change_volume():
    model = running_model()
    sensor = model.sensors["bo-min"]
    model.set_tank_level("bo", sensor.threshold_l + sensor.hysteresis_l + 1)
    model.tick(sensor.delay_s)
    assert sensor.automatic
    model.set_tank_level("bo", sensor.threshold_l)
    model.tick(sensor.delay_s)
    assert sensor.automatic
    model.set_tank_level("bo", sensor.threshold_l - sensor.hysteresis_l - 1)
    model.tick(sensor.delay_s)
    assert not sensor.automatic
    volume = model.tanks["bo"].volume_l
    model.force_sensor("bo-min", True)
    assert sensor.value
    assert model.tanks["bo"].volume_l == volume
    model.force_sensor("bo-min", None)
    assert not sensor.value


def test_pause_and_speed_only_affect_physics():
    model = running_model()
    model.set_relay(22, True)
    model.paused = True
    model.tick(60)
    assert model.tanks["bo"].volume_l == 250
    assert model.relay(22)
    model.paused = False
    model.speed = 5
    model.tick(60)
    assert model.tanks["bo"].volume_l == pytest.approx(265)


def test_transfer_carries_solution_and_dilutes_bp():
    model = running_model()
    model.pumps["bo-to-bp"].start_s = 0
    before = model.tanks["bp"].ec_ms_cm
    model.set_relay(2, True)
    model.tick(60)
    assert model.tanks["bp"].ec_ms_cm < before
    assert model.tanks["bo"].ec_ms_cm == pytest.approx(0.1)


def test_every_ponics_reagent_changes_only_bp():
    for reagent in ("a", "b", "c", "ph_plus", "ph_minus"):
        model = BionicModel()
        untouched = {
            tank_id: (tank.volume_l, tank.solute_mass, tank.acidity_units, tank.buffer_units, tank.heat_c_l)
            for tank_id, tank in model.tanks.items() if tank_id != "bp"
        }
        before_ec = model.tanks["bp"].ec_ms_cm
        before_ph = model.tanks["bp"].ph
        model.ponics.dose(reagent, 10)
        if reagent in {"a", "b", "c"}:
            assert model.tanks["bp"].ec_ms_cm > before_ec
        elif reagent == "ph_plus":
            assert model.tanks["bp"].ph > before_ph
        else:
            assert model.tanks["bp"].ph < before_ph
        assert {
            tank_id: (tank.volume_l, tank.solute_mass, tank.acidity_units, tank.buffer_units, tank.heat_c_l)
            for tank_id, tank in model.tanks.items() if tank_id != "bp"
        } == untouched


def test_ponics_measurements_are_always_bp_even_when_other_tanks_change():
    model = BionicModel()
    initial = model.ponics.registers()[4:7]
    model.tanks["bo"].initialize_solution(ec_ms_cm=8, ph=10, temperature_c=50, buffer_per_l=1)
    assert model.ponics.registers()[4:7] == initial
    model.tanks["bp"].initialize_solution(ec_ms_cm=3.21, ph=5.7, temperature_c=22.4, buffer_per_l=1)
    assert model.ponics.registers()[4:7] == [570, 321, 224]


def test_solution_is_stable_without_flows_or_dosing():
    model = running_model()
    before = {
        tank_id: (tank.ec_ms_cm, tank.ph, tank.temperature_c)
        for tank_id, tank in model.tanks.items()
    }
    model.tick(3600)
    after = {
        tank_id: (tank.ec_ms_cm, tank.ph, tank.temperature_c)
        for tank_id, tank in model.tanks.items()
    }
    assert after == before
