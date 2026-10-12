"""Live valve commands use a fake bus and never close the last flow path."""
from threading import Event

import pytest

from rtuforge.irrigation import State, TIER_VALVES
from rtuforge.irrigation_service import IrrigationService
from rtuforge.stand_cli import _hardware, _shutdown, execute_command
from test_irrigation_modbus import cli_rig, stop_feedback, to_running


@pytest.fixture(autouse=True)
def forbid_real_serial(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("Live valve tests must never access a real serial port")
    monkeypatch.setattr("serial.Serial", forbidden)


def running_ctx(tmp_path):
    ctx, _, bus = cli_rig(tmp_path)
    ctx.one_shot = False
    service = IrrigationService(_hardware(ctx, quiet=True), ctx.irrigation_settings,
                                ctx.bus_lock, lambda text: ctx.console.print(text, markup=False))
    ctx.irrigation = service
    time = [0.0]
    ctl = service.controller
    ctl.clock = lambda: time[0]
    to_running(bus, time, ctl)
    return ctx, bus, service, time


def relay_writes(bus):
    return [(int.from_bytes(r[2:4], "big") + 1, bool(r[7]))
            for r in bus.events if r[1] == 15]


@pytest.mark.parametrize("new_valve", [10, 11, 12, 13, 14])
@pytest.mark.parametrize("off", ["off", "of"])
def test_open_new_path_before_closing_original_and_stop_closes_all(tmp_path, new_valve, off):
    ctx, bus, service, _ = running_ctx(tmp_path)
    execute_command(ctx, f"on {new_valve}")
    execute_command(ctx, f"{off} 9")
    ctl = service.controller
    assert ctl.state == State.RUNNING
    assert [ch for ch in TIER_VALVES if bus.coils[ch - 1]] == [new_valve]
    assert new_valve in service.hardware.expected_hydraulics
    assert 9 not in service.hardware.expected_hydraulics
    ctl.stop()
    ctl.tick()
    assert ctl.state == State.STOPPING and bus.coils[new_valve - 1]
    stop_feedback(bus)
    bus.events.clear()
    ctl.tick()
    assert ctl.state == State.IDLE and not any(bus.coils)
    assert relay_writes(bus) == [(ch, False) for ch in TIER_VALVES]


def test_batch_closing_all_paths_is_rejected_before_any_write(tmp_path):
    ctx, bus, service, _ = running_ctx(tmp_path)
    execute_command(ctx, "on 10 12 14")
    bus.events.clear()
    with pytest.raises(RuntimeError, match="последний клапан"):
        execute_command(ctx, "off 9 10 12 14")
    assert not relay_writes(bus) and service.controller.state == State.RUNNING
    execute_command(ctx, "off 9 10 14")
    assert bus.coils[11] and not any(bus.coils[i] for i in (8, 9, 13))


@pytest.mark.parametrize("command", ["on 12 32", "off 9 1", "on 19", "off 23", "on 8", "off 15"])
def test_mixed_and_non_valve_commands_remain_blocked_as_a_whole(tmp_path, command):
    ctx, bus, service, _ = running_ctx(tmp_path)
    bus.events.clear()
    with pytest.raises(RuntimeError, match="только для клапанов 9..14"):
        execute_command(ctx, command)
    assert not relay_writes(bus) and service.controller.state == State.RUNNING
    assert bus.coils[8] and bus.coils[0] and bus.coils[31]


def test_repeated_channels_are_idempotent(tmp_path):
    ctx, bus, service, _ = running_ctx(tmp_path)
    bus.events.clear()
    execute_command(ctx, "on 12 12")
    execute_command(ctx, "off 9 9")
    assert relay_writes(bus) == [(12, True), (9, False)]
    assert service.controller.state == State.RUNNING


@pytest.mark.parametrize("state", [State.PRECHECK, State.CONFIGURE_VFD, State.OPEN_VALVES,
                                  State.START_BOOSTER, State.WAIT_LOW_PRESSURE, State.START_VFD,
                                  State.STOPPING, State.FAULT])
def test_startup_stopping_and_fault_reject_live_commands(tmp_path, state):
    ctx, bus, service, _ = running_ctx(tmp_path)
    service.controller.state = state
    bus.events.clear()
    with pytest.raises(RuntimeError, match="WAIT_HIGH_PRESSURE/RUNNING"):
        execute_command(ctx, "on 12")
    assert not bus.events


def test_valves_can_be_changed_while_high_pressure_is_building(tmp_path):
    ctx, bus, service, _ = running_ctx(tmp_path)
    service.controller.state = State.WAIT_HIGH_PRESSURE
    bus.raw[1] = 8000
    execute_command(ctx, "on 12")
    execute_command(ctx, "off 9")
    assert service.controller.state == State.WAIT_HIGH_PRESSURE and bus.coils[11]


def test_hardware_rechecks_last_path_after_display_before_write(tmp_path):
    ctx, bus, service, _ = running_ctx(tmp_path)
    execute_command(ctx, "on 12")
    def close_other_path(text):
        if text.startswith("Реле 9: ВЫКЛ"):
            bus.coils[11] = False
    service.hardware.report = close_other_path
    bus.events.clear()
    with pytest.raises(RuntimeError):
        execute_command(ctx, "off 9")
    assert (9, False) not in relay_writes(bus)
    assert bus.coils[8] and service.controller.state == State.STOPPING
    assert not bus.coils[0] and not bus.coils[31]


def test_no_open_valves_in_feedback_immediately_drops_pumps(tmp_path):
    ctx, bus, service, _ = running_ctx(tmp_path)
    bus.coils[8] = False
    service.controller.tick()
    assert service.controller.state == State.STOPPING
    assert "Ни один клапан" in service.controller.fault_reason
    assert not bus.coils[0] and not bus.coils[31]


@pytest.mark.parametrize("fault", ["pressure", "sensor", "communication", "coil", "ack"])
def test_live_commands_keep_all_protection_checks_and_stop_on_write_failure(tmp_path, fault):
    ctx, bus, service, _ = running_ctx(tmp_path)
    if fault == "pressure":
        bus.raw[1] = 17000
    elif fault == "sensor":
        bus.raw[0] = 3000
    elif fault == "communication":
        bus.failure = lambda r: b"" if r[0] == 6 else None
    elif fault == "coil":
        bus.coils[9] = True  # Not requested by the operator.
    else:
        bus.failure = lambda r: b"" if r[1] == 15 and r[7] else None
    with pytest.raises(RuntimeError):
        execute_command(ctx, "on 12")
    assert service.controller.state == State.STOPPING
    assert not bus.coils[0] and not bus.coils[31]
    assert bus.coils[8]  # No closing before actual drive STOP.


def test_stop_requested_during_relay_display_cancels_enable(tmp_path):
    ctx, bus, service, _ = running_ctx(tmp_path)
    service.hardware.report = lambda text: service.stop() if text.startswith("Реле 12: ВКЛ") else None
    bus.events.clear()
    with pytest.raises(RuntimeError, match="STOP принят"):
        execute_command(ctx, "on 12")
    assert (12, True) not in relay_writes(bus)
    assert service.controller.state == State.STOPPING
    assert bus.coils[8] and not bus.coils[31]


def test_stop_timeout_retains_all_open_paths_then_reset_closes_every_valve(tmp_path):
    ctx, bus, service, time = running_ctx(tmp_path)
    execute_command(ctx, "on 10 12 14")
    ctl = service.controller
    ctl.stop()
    time[0] += 16
    ctl.tick()
    assert ctl.state == State.FAULT
    assert all(bus.coils[ch - 1] for ch in (9, 10, 12, 14))
    stop_feedback(bus)
    execute_command(ctx, "reset fault")
    assert ctl.state == State.IDLE and not any(bus.coils)


def test_close_failure_attempts_other_valves_and_cannot_report_idle(tmp_path):
    ctx, bus, service, time = running_ctx(tmp_path)
    execute_command(ctx, "on 12 14")
    ctl = service.controller
    ctl.stop()
    stop_feedback(bus)
    bus.failure = lambda r: b"" if r[1] == 15 and r[2:4] == b"\x00\x0b" and not r[7] else None
    bus.events.clear()
    time[0] += 16
    ctl.tick()
    assert ctl.state == State.FAULT and bus.coils[11]
    assert relay_writes(bus) == [(ch, False) for ch in TIER_VALVES]
    assert not bus.coils[13] and not bus.coils[8]
    bus.failure = None
    execute_command(ctx, "reset fault")
    assert ctl.state == State.IDLE and not any(bus.coils)


def test_idle_stop_closes_all_tier_valves_after_both_drives_confirm_stop(tmp_path):
    ctx, _, bus = cli_rig(tmp_path)
    bus.coils[8:14] = [True] * 6
    execute_command(ctx, "stop")
    assert not any(bus.coils)
    assert [ch for ch, active in relay_writes(bus) if ch in TIER_VALVES] == list(TIER_VALVES)


def test_worker_commands_and_shutdown_share_bus_and_close_every_path(tmp_path):
    ctx, _, bus = cli_rig(tmp_path)
    ctx.one_shot = False
    bus.auto_feedback = True
    running = Event()
    ctx.irrigation = IrrigationService(_hardware(ctx, quiet=True), ctx.irrigation_settings,
                                      ctx.bus_lock, lambda text: running.set() if text == "Полив: RUNNING" else None)
    execute_command(ctx, "start 1 1 broth 29 --pump 1")
    try:
        assert running.wait(2)
        execute_command(ctx, "on 10 12 14")
        execute_command(ctx, "off 9 10")
        assert ctx.irrigation.controller.state == State.RUNNING
    finally:
        _shutdown(ctx)
    assert not any(bus.coils) and bus.maximum_transactions == 1
