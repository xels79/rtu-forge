"""Pressure regulation and priority writes tested only against a fake Modbus bus."""
from dataclasses import replace
from threading import RLock

import pytest

from rtuforge.crc import append_crc
from rtuforge.irrigation import IrrigationController, State
from rtuforge.irrigation_config import IrrigationSettings, load_irrigation_settings, set_irrigation_option
from rtuforge.irrigation_preflight import check_start
from rtuforge.irrigation_service import IrrigationService
from rtuforge.stand_cli import execute_command
from test_irrigation_modbus import cli_rig, rig


@pytest.fixture(autouse=True)
def forbid_serial(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("Pressure control tests must never open hardware")
    monkeypatch.setattr("serial.Serial", forbidden)


def controlled_rig(**kwargs):
    settings = dict(pressure_control_enabled=True, high_max_bar=72,
                    drive7_min_hz=5, rise_timeout_ms=60000)
    settings.update(kwargs)
    bus, cfg, hw, time, _ = rig(**settings)
    ctl = IrrigationController(hw, cfg.limits(), clock=lambda: time[0],
                               pressure_control=cfg.pressure_control())
    return bus, cfg, hw, time, ctl


def begin(bus, ctl, hz=21, *, drive=7, selector=19):
    ctl.start(1, 1, "broth", hz, drive=drive, selector=selector)
    for _ in range(6):
        ctl.tick()
    assert ctl.state == State.WAIT_HIGH_PRESSURE
    bus.registers[drive].update({2: round(hz * 10), 0x5000: 1})


def pressure(bus, bar):
    bus.raw[1] = round(4000 + bar * 160)


def frequency_writes(bus):
    return [int.from_bytes(r[4:6], "big") / 10 for r in bus.events
            if r[1] == 6 and int.from_bytes(r[2:4], "big") == 0x2001]


def test_dry_after_idle_increases_slowly_without_catching_up_and_holds_at_target():
    bus, cfg, _, time, ctl = controlled_rig()
    begin(bus, ctl)
    pressure(bus, 40)
    ctl.tick()
    assert frequency_writes(bus) == [21]
    time[0] = 1
    ctl.tick()
    assert frequency_writes(bus) == [21, 21.1]
    # No more raises until the drive has actually reached its new setpoint.
    time[0] = 10
    ctl.tick()
    assert frequency_writes(bus) == [21, 21.1]
    bus.registers[7][2] = 211
    ctl.tick()
    assert frequency_writes(bus) == [21, 21.1, 21.2]
    pressure(bus, 60)
    bus.registers[7][2] = 212
    ctl.tick()
    assert ctl.state == State.RUNNING
    time[0] = 20
    ctl.tick()
    assert ctl.frequency_hz == 21.2


def test_fast_reduction_happens_before_feedback_current_coils_and_telemetry():
    bus, _, _, time, ctl = controlled_rig()
    begin(bus, ctl, 23.7)
    pressure(bus, 60)
    ctl.tick()
    bus.events.clear()
    time[0] = .3
    pressure(bus, 63)
    ctl.tick()
    assert frequency_writes(bus) == [23.2]
    assert bus.events[2][1] == 6  # two AI reads, then the reduction
    assert all(r[0] == 6 for r in bus.events[:2])
    assert bus.events[3][1:4] == bytes.fromhex("03 00 01")  # PA01 readback
    assert ctl.state == State.RUNNING


def test_seventy_bar_reduces_to_verified_minimum_without_waiting_for_interval():
    bus, _, _, time, ctl = controlled_rig()
    begin(bus, ctl, 23.7)
    pressure(bus, 60)
    ctl.tick()
    bus.events.clear()
    pressure(bus, 70)
    ctl.tick()
    assert ctl.state == State.RUNNING and not ctl.fault_reason
    assert frequency_writes(bus) == [20]
    assert bus.coils[31]
    ctl.tick()
    assert frequency_writes(bus) == [20]  # no duplicate minimum writes


@pytest.mark.parametrize("bar", [72, 72.1])
def test_emergency_limit_stops_before_any_auxiliary_reads_or_frequency_writes(bar):
    bus, _, _, _, ctl = controlled_rig()
    begin(bus, ctl)
    bus.events.clear()
    pressure(bus, bar)
    ctl.tick()
    assert ctl.state == State.STOPPING and "Превышено ДВД" in ctl.fault_reason
    assert not frequency_writes(bus)
    assert bus.events[2][1] == 15 and bus.events[2][7] == 0
    assert not bus.coils[31] and not bus.coils[0] and bus.coils[8]


def test_regulation_never_exceeds_cap_and_pressure_rise_still_times_out():
    bus, _, _, time, ctl = controlled_rig(rise_timeout_ms=200000)
    begin(bus, ctl)
    pressure(bus, 40)
    for sec in range(1, 40):
        bus.registers[7][2] = bus.registers[7][1]
        time[0] = sec
        ctl.tick()
    assert ctl.frequency_hz == 23.7 and max(frequency_writes(bus)) == 23.7
    time[0] = 201
    ctl.tick()
    assert ctl.state == State.STOPPING and "ДВД не набирается" in ctl.fault_reason


@pytest.mark.parametrize("cause", ["motor_minimum", "pb05", "initial_cap", "source"])
def test_start_checks_initial_and_whole_regulation_range_before_any_write(cause):
    bus, cfg, hw, time, ctl = controlled_rig(drive7_min_hz=24 if cause == "motor_minimum" else 5)
    if cause == "pb05":
        bus.registers[7][0x69] = 230
    if cause == "source":
        bus.registers[7][0x65] = 0
    if cause == "initial_cap":
        with pytest.raises(ValueError, match="pressure_max_hz"):
            ctl.start(1, 1, "broth", 24, drive=7, selector=19)
        assert not bus.events
    else:
        ctl.start(1, 1, "broth", 21, drive=7, selector=19)
        ctl.tick()
        assert ctl.state == State.STOPPING
        assert not any(r[1] == 6 or (r[1] == 15 and r[7]) for r in bus.events)


@pytest.mark.parametrize("cause", ["low", "run", "sensor", "crc", "fault", "write", "readback", "stop"])
def test_existing_protections_and_stop_prevent_further_increase(cause):
    bus, _, hw, time, ctl = controlled_rig()
    begin(bus, ctl)
    pressure(bus, 60)
    ctl.tick()
    pressure(bus, 40)
    time[0] = 1
    if cause == "low":
        bus.raw[0] = 4000
    elif cause == "run":
        bus.registers[7][0x5000] = 0
    elif cause == "sensor":
        bus.raw[1] = 3000
    elif cause == "crc":
        bus.failure = lambda r: b"bad" if r[0] == 6 else None
    elif cause == "fault":
        bus.registers[7][0x5001] = 1
    elif cause == "write":
        pressure(bus, 65)
        bus.failure = lambda r: b"" if r[1] == 6 else None
    elif cause == "readback":
        pressure(bus, 65)
        bus.failure = lambda r: append_crc(bytes.fromhex("07 03 02 00 00")) if r[1:4] == bytes.fromhex("03 00 01") else None
    else:
        hw.cancelled = lambda: True
    before = len(frequency_writes(bus))
    ctl.tick()
    if cause not in {"write", "readback"}:
        assert len(frequency_writes(bus)) == before
    if cause == "low":
        time[0] += 3
        ctl.tick()
    assert ctl.state == State.STOPPING
    assert not bus.coils[31] and not bus.coils[0]


def test_zero_high_pressure_and_missing_run_do_not_bypass_startup_timeout():
    bus, _, _, time, ctl = controlled_rig(ai2_zero_raw_is_zero=True)
    begin(bus, ctl)
    bus.raw[1] = 0
    bus.registers[7].update({2: 0, 0x5000: 0})
    time[0] = 2
    ctl.tick()
    assert frequency_writes(bus) == [21]
    time[0] = 61
    ctl.tick()
    assert ctl.state == State.STOPPING


def test_regulation_preflight_is_read_only_and_reports_cap_and_soft_limit():
    bus, cfg, hw, _, _ = controlled_rig()
    report = check_start(hw, cfg, 1, 1, "broth", 21)
    assert report.ready and any("23.7" in c.detail for c in report.checks)
    assert all(r[1] in (1, 3, 4) for r in bus.events)
    bus.registers[7][0x69] = 230
    assert not check_start(hw, cfg, 1, 1, "broth", 21).ready
    bus.registers[7][0x69] = 450
    pressure(bus, 70)
    assert not check_start(hw, cfg, 1, 1, "broth", 21).ready
    assert not any(bus.coils)


def test_options_roundtrip_default_disabled_and_validation_preserves_file(tmp_path):
    path = tmp_path / "stand.ini"
    cfg = load_irrigation_settings(path)
    assert not cfg.pressure_control_enabled and cfg.pressure_control() is None
    assert cfg.pressure_poll_ms == 50
    cfg = set_irrigation_option(path, cfg, "high_max_bar", "72")
    cfg = set_irrigation_option(path, cfg, "pressure_control_enabled", "true")
    assert load_irrigation_settings(path) == cfg
    original = path.read_bytes()
    for name, value in [("high_max_bar", "70"), ("pressure_max_hz", "23.75"),
                        ("pressure_up_step_hz", "0.01"), ("pressure_down_step_hz", "0"),
                        ("pressure_up_interval_ms", "0"), ("pressure_poll_ms", "0"),
                        ("pressure_limit_bar", "60"), ("pressure_deadband_bar", "nan")]:
        with pytest.raises(ValueError):
            set_irrigation_option(path, cfg, name, value)
        assert path.read_bytes() == original


def test_service_uses_regulation_and_reports_actual_setpoint(tmp_path):
    ctx, transport, bus = cli_rig(tmp_path)
    ctx.irrigation_settings = replace(ctx.irrigation_settings, pressure_control_enabled=True,
                                      high_max_bar=72, drive7_min_hz=5)
    from rtuforge.stand_cli import _hardware
    output = []
    service = IrrigationService(_hardware(ctx, quiet=True), ctx.irrigation_settings, RLock(), output.append)
    assert service.poll_interval_ms == 50
    service.controller.start(1, 1, "broth", 21, drive=7, selector=19)
    for _ in range(6):
        service.controller.tick()
    bus.registers[7].update({2: 210, 0x5000: 1})
    pressure(bus, 60)
    service.controller.tick()
    service._telemetry()
    assert "уставка=21" in output[-1] and "цель=60" in output[-1]
    assert "70" in output[-1] and "72" in output[-1]
    ctx.irrigation = service
    with pytest.raises(RuntimeError):
        execute_command(ctx, "idd 7 frequency 23.7")


def test_high_pressure_watch_reduces_without_waiting_for_low_drive_or_current_reads():
    bus, _, _, time, ctl = controlled_rig()
    begin(bus, ctl, 23.7)
    pressure(bus, 60)
    ctl.tick()
    bus.events.clear()
    pressure(bus, 70)
    ctl.tick_pressure()
    assert frequency_writes(bus) == [20]
    assert bus.events[0][:6] == bytes.fromhex("06 03 10 01 00 01")
    assert bus.events[1][:6] == bytes.fromhex("06 04 00 01 00 01")
    assert len(bus.events) == 4  # AI2 type/raw, frequency write and PA01 readback
    assert ctl.last.high_bar == 70


def test_pressure_rising_after_reduction_stops_before_emergency_limit():
    bus, _, _, time, ctl = controlled_rig()
    begin(bus, ctl, 23.7)
    pressure(bus, 60)
    ctl.tick()
    time[0] = 1
    pressure(bus, 65)
    ctl.tick_pressure()
    assert ctl.frequency_hz == 23.2
    pressure(bus, 64)
    ctl.tick_pressure()
    assert ctl.state == State.RUNNING  # reduction is working
    pressure(bus, 64.4)
    ctl.tick_pressure()
    assert ctl.state == State.RUNNING  # noise below the rise margin
    pressure(bus, 64.5)
    ctl.tick_pressure()
    assert ctl.state == State.STOPPING and "засор" in ctl.fault_reason
    assert not bus.coils[31]


def test_high_pressure_holding_after_reduction_does_not_imply_a_blockage():
    bus, _, _, time, ctl = controlled_rig()
    begin(bus, ctl, 23.7)
    pressure(bus, 60)
    ctl.tick()
    time[0] = 1
    pressure(bus, 65)
    for _ in range(8):
        ctl.tick_pressure()
        time[0] += .3
    assert ctl.state == State.RUNNING
    pressure(bus, 62)
    ctl.tick_pressure()
    # A new rise needs a new decrease; a recovered episode is no longer latched.
    pressure(bus, 63.4)
    ctl.tick_pressure()
    assert ctl.state == State.RUNNING


@pytest.mark.parametrize("failure", ["raw", "mode", "crc"])
def test_fast_high_watch_keeps_validation_and_never_increases(failure):
    bus, _, _, time, ctl = controlled_rig()
    begin(bus, ctl)
    if failure == "raw":
        bus.raw[1] = 3000
    elif failure == "mode":
        bus.types[1] = 2
    else:
        bus.failure = lambda r: b"bad" if r[0] == 6 else None
    time[0] = 10
    ctl.tick_pressure()
    assert ctl.state == State.STOPPING and frequency_writes(bus) == [21]


def test_pressure_minimum_does_not_follow_a_lower_pb06_or_motor_setting():
    bus, _, _, _, ctl = controlled_rig()
    bus.registers[7][0x6A] = 0
    begin(bus, ctl)
    pressure(bus, 70)
    ctl.tick_pressure()
    assert ctl.frequency_hz == 20


def test_fresh_ai2_check_catches_pressure_jump_during_auxiliary_reads_before_increase():
    bus, _, hw, time, ctl = controlled_rig()
    begin(bus, ctl)
    pressure(bus, 40)
    original = hw.transaction

    def jump(request):
        response = original(request)
        if request[:6] == bytes.fromhex("07 03 00 03 00 01"):
            pressure(bus, 72)
        return response

    hw.transaction = jump
    time[0] = 1
    ctl.tick()
    assert ctl.state == State.STOPPING and frequency_writes(bus) == [21]


def test_worker_interleaves_ai2_watch_and_stops_cleanly_without_serial():
    from threading import Event
    bus, cfg, hw, _, _ = controlled_rig()
    bus.auto_feedback = True
    running, reduced = Event(), Event()
    original = hw.transaction

    def transaction(request):
        response = original(request)
        if request[:6] == bytes.fromhex("07 06 20 01 00 C8"):
            reduced.set()
        return response

    hw.transaction = transaction
    service = IrrigationService(hw, cfg, RLock(), lambda text: running.set() if "Полив: RUNNING" in text else None)
    try:
        service.start(1, 1, "broth", 21)
        assert running.wait(2)
        pressure(bus, 70)
        assert reduced.wait(2)
        assert any(r[:6] == bytes.fromhex("06 04 00 01 00 01") for r in bus.events)
    finally:
        service.close()
    assert service.controller.state == State.IDLE and not any(bus.coils)
    assert not service.thread.is_alive() and bus.maximum_transactions == 1


@pytest.mark.parametrize("drive,minimum_raw,motor_minimum,expected", [
    (7, 221, 5, 22.1), (8, 200, 22.4, 22.4),
])
def test_regulated_reduction_respects_selected_drive_minimum(drive, minimum_raw, motor_minimum, expected):
    bus, _, _, _, ctl = controlled_rig(**{f"drive{drive}_min_hz": motor_minimum})
    bus.registers[drive][0x6A] = minimum_raw
    begin(bus, ctl, 23, drive=drive, selector=19 if drive == 7 else 20)
    pressure(bus, 70)
    ctl.tick_pressure()
    assert ctl.frequency_hz == expected
    assert bus.registers[drive][1] == round(expected * 10)
    assert not any(r[0] == 15 - drive for r in bus.events)


def test_regulated_guided_start_waits_for_fwd_then_regulates_without_more_enter():
    from test_irrigation_steps import approve
    bus, _, _, time, ctl = controlled_rig()
    ctl.start(1, 1, "broth", 21, drive=7, selector=19, guided=True)
    for _ in range(6):
        approve(ctl)
    assert ctl.state == State.WAIT_HIGH_PRESSURE and ctl.pending_step is None
    bus.registers[7].update({2: 210, 0x5000: 1})
    pressure(bus, 40)
    time[0] = 1
    ctl.tick()
    assert ctl.frequency_hz == 21.1 and ctl.pending_step is None


def test_regulated_oneshot_start_uses_same_service_and_shutdown(tmp_path, monkeypatch):
    from threading import Event
    from rtuforge import stand_cli
    ctx, transport, bus = cli_rig(tmp_path)
    ctx.irrigation_settings = replace(ctx.irrigation_settings, pressure_control_enabled=True,
                                      high_max_bar=72, drive7_min_hz=5)
    ctx.config_path.write_text("", encoding="utf-8")
    bus.auto_feedback = True
    monkeypatch.setattr(stand_cli, "load_config", lambda path: ctx.config)
    monkeypatch.setattr(stand_cli, "load_irrigation_settings", lambda path: ctx.irrigation_settings)
    monkeypatch.setattr(stand_cli, "SerialTransport", lambda *args: transport)
    monkeypatch.setattr("sys.argv", ["standforge", "--home", str(tmp_path), "start", "1", "1", "broth", "21"])
    execute = stand_cli.execute_command
    observed = []

    def interrupt_when_running(context, line):
        context.one_shot = False
        started = Event()
        service = IrrigationService(stand_cli._hardware(context, quiet=True), context.irrigation_settings,
                                    context.bus_lock, lambda text: started.set() if "Полив: RUNNING" in text else None)
        context.irrigation = service
        observed.append(service)
        execute(context, line)
        assert started.wait(2)
        assert service.controller.pressure_control is not None
        raise KeyboardInterrupt

    monkeypatch.setattr(stand_cli, "execute_command", interrupt_when_running)
    assert stand_cli.main() == 130
    assert not any(bus.coils) and not transport.connected and not observed[0].thread.is_alive()
