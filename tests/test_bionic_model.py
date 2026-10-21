import pytest

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
    assert model.pumps["bso1-to-bp"].actual_flow_lpm == 8
    assert ("WATER_SHORTAGE", "bso1") in model.alarms


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
    assert blocked.tanks["bo"].volume_l < before


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
