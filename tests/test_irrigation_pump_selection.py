"""A rack valve and an explicitly selected pump are independent routes."""
from threading import Event

import pytest

from rtuforge.irrigation import State
from rtuforge.irrigation_preflight import check_start, parse_start_args
from rtuforge.irrigation_service import IrrigationService
from rtuforge.stand_cli import _hardware, _shutdown, execute_command
from rtuforge.stand_completion import completion_candidates
from test_irrigation_modbus import cli_rig, rig


@pytest.fixture(autouse=True)
def forbid_real_serial(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("Pump selection tests must never open a COM port")
    monkeypatch.setattr("serial.Serial", forbidden)


@pytest.mark.parametrize("rack", [1, 2])
@pytest.mark.parametrize("pump", [1, 2])
@pytest.mark.parametrize("swapped", [False, True])
def test_preflight_routes_pump_independently_of_rack_without_writes(rack, pump, swapped):
    bus, cfg, hw, _, _ = rig(pump1_drive=8 if swapped else 7,
                             pump2_drive=7 if swapped else 8)
    drive, selector = cfg.mapping(rack, pump=pump)
    bus.failure = lambda request: b"" if request[0] in (7, 8) and request[0] != drive else None
    report = check_start(hw, cfg, rack, 2, "broth", 29, pump=pump)
    assert report.ready
    assert (report.drive, report.selector, report.valve) == (drive, 18 + pump, 10 if rack == 1 else 13)
    assert all(r[0] not in (7, 8) or r[0] == drive for r in bus.events)
    assert all(r[1] in (1, 3, 4) for r in bus.events)
    assert cfg.mapping(2) == (cfg.pump2_drive, 20)  # No persistent mapping change.


@pytest.mark.parametrize("prefix", ["start", "start check", "start step"])
@pytest.mark.parametrize("suffix", ["--pump", "--pump 0", "--pump 3", "--pump seven",
                                    "--idd 7", "--pump 1 --pump 2", "--pump 1 extra"])
def test_invalid_pump_args_fail_before_connect(tmp_path, prefix, suffix):
    ctx, transport, bus = cli_rig(tmp_path)
    with pytest.raises(ValueError):
        execute_command(ctx, f"{prefix} 2 1 broth 29 {suffix}")
    assert not transport.connected and not bus.events and ctx.irrigation is None


@pytest.mark.parametrize("guided", [False, True])
@pytest.mark.parametrize("pump", [1, 2])
def test_cli_starts_rack_two_with_chosen_pump_and_stops_same_drive(tmp_path, guided, pump):
    ctx, _, bus = cli_rig(tmp_path)
    ctx.one_shot = False
    bus.auto_feedback = True
    drive, selector = ctx.irrigation_settings.mapping(2, pump=pump)
    fwd = 32 if drive == 7 else 31
    bus.failure = lambda request: b"" if request[0] in (7, 8) and request[0] != drive else None
    running, pending = Event(), Event()
    def report(text):
        ctx.console.print(text, markup=False)
        if text == "Полив: RUNNING":
            running.set()
        if "Enter — подтвердить" in text:
            pending.set()
    ctx.irrigation = IrrigationService(_hardware(ctx, quiet=True), ctx.irrigation_settings,
                                      ctx.bus_lock, report)
    service = ctx.irrigation
    execute_command(ctx, f"start {'step ' if guided else ''}2 2 broth 29 --pump {pump}")
    try:
        if guided:
            for number in range(1, 7):
                assert pending.wait(2), service.controller.fault_reason
                pending.clear()
                assert service.controller.pending_step.number == number
                execute_command(ctx, "")
        assert running.wait(2), service.controller.fault_reason
        ctl = service.controller
        assert (ctl.drive, ctl.select, ctl.valve) == (drive, selector, 13)
        assert bus.coils[12] and not any(bus.coils[8:12]) and not bus.coils[13]
        enables = [int.from_bytes(r[2:4], "big") + 1 for r in bus.events if r[1] == 15 and r[7]]
        assert enables == [13, selector, 23, 1, fwd]
        with pytest.raises(RuntimeError):
            execute_command(ctx, f"start 1 1 broth 29 --pump {3 - pump}")
        assert ctl.drive == drive  # Rejected START cannot redirect STOP.
        execute_command(ctx, "stop")
        assert service.finished.wait(2)
        assert ctl.state == State.IDLE and not any(bus.coils)
        assert all(r[0] not in (7, 8) or r[0] == drive for r in bus.events)
        assert "ручной выбор" in ctx.console.export_text()
    finally:
        _shutdown(ctx)


def test_selected_drive_keeps_its_frequency_limits():
    bus, cfg, hw, _, _ = rig(drive7_min_hz=35)
    report = check_start(hw, cfg, 2, 1, "broth", 29, pump=1)
    assert not report.ready and report.drive == 7
    assert any(not c.passed and "минимум мотора=35" in c.detail for c in report.checks)


def test_optional_selection_preserves_defaults_and_help_has_no_side_effects(tmp_path):
    assert parse_start_args(["2", "1", "broth", "29"])[-1] is None
    assert parse_start_args(["2", "1", "broth", "29", "--pump", "1"])[-1] == 1
    ctx, transport, bus = cli_rig(tmp_path)
    execute_command(ctx, "help start")
    assert "--pump" in ctx.console.export_text()
    assert not transport.connected and not bus.events


@pytest.mark.parametrize("prefix", ["start", "start check", "start step"])
def test_pump_completion(prefix):
    assert completion_candidates(f"{prefix} 2 1 broth 29 ") == ["--pump"]
    assert completion_candidates(f"{prefix} 2 1 broth 29 --pump ") == ["1", "2"]
