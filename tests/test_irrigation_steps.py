"""Guided commissioning uses only a synthetic Modbus bus, never hardware."""
from threading import Event, RLock
from contextlib import nullcontext

import pytest

from rtuforge.irrigation import State, VALVES
from rtuforge.irrigation_service import IrrigationService
from rtuforge.stand_cli import _hardware, execute_command
from test_irrigation_modbus import cli_rig, rig


@pytest.fixture(autouse=True)
def forbid_real_serial(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("Guided tests must never open serial ports")
    monkeypatch.setattr("serial.Serial", forbidden)


def pending(ctl):
    for _ in range(4):
        if ctl.pending_step is not None:
            return ctl.pending_step
        ctl.tick()
    raise AssertionError(f"No pending step in {ctl.state}: {ctl.fault_reason}")


def approve(ctl):
    step = pending(ctl)
    ctl.confirm_step(step.number)
    ctl.tick()
    return step


def writes(bus):
    return [r for r in bus.events if r[1] in (6, 15)]


@pytest.mark.parametrize("rack,tier", VALVES)
def test_each_route_requires_six_enters_and_opens_only_its_tier(rack, tier):
    bus, cfg, hw, time, ctl = rig()
    drive, selector = cfg.mapping(rack)
    valve = VALVES[rack, tier]
    fwd = 32 if drive == 7 else 31
    ctl.start(rack, tier, "broth", 29, drive=drive, selector=selector, guided=True)
    first = pending(ctl)
    assert first.number == 1 and "29 Гц" in first.description
    assert not writes(bus)
    ctl.tick()
    assert not writes(bus)
    approve(ctl)
    assert bus.registers[drive][1] == 290 and not any(bus.coils)
    for number, channel in enumerate((valve, selector, 23, 1, fwd), 2):
        step = pending(ctl)
        assert step.number == number and f"реле {channel}" in step.description
        before = writes(bus).copy()
        ctl.tick()
        ctl.tick()
        assert writes(bus) == before
        assert not bus.coils[channel - 1]
        approve(ctl)
        assert bus.coils[channel - 1]
        assert [ch for ch in range(9, 15) if bus.coils[ch - 1]] == [valve]
    assert ctl.state == State.WAIT_HIGH_PRESSURE
    bus.registers[drive].update({2: 290, 0x5000: 1})
    bus.raw[1] = 13600
    ctl.tick()
    assert ctl.state == State.RUNNING and ctl.pending_step is None
    enables = [int.from_bytes(r[2:4], "big") + 1 for r in writes(bus) if r[1] == 15 and r[7]]
    assert enables == [valve, selector, 23, 1, fwd]


def test_enter_is_not_queued_and_stale_or_duplicate_confirmation_is_rejected():
    bus, _, _, _, ctl = rig()
    ctl.start(1, 1, "broth", 29, drive=7, selector=19, guided=True)
    with pytest.raises(RuntimeError, match="Нет ожидающего"):
        ctl.confirm_step(1)
    first = pending(ctl)
    ctl.confirm_step(first.number)
    with pytest.raises(RuntimeError, match="Нет ожидающего"):
        ctl.confirm_step(first.number)
    ctl.tick()
    second = pending(ctl)
    assert second.number == 2
    with pytest.raises(RuntimeError, match="Нет ожидающего"):
        ctl.confirm_step(first.number)
    assert not any(bus.coils)


@pytest.mark.parametrize("step_number", range(1, 7))
def test_stop_cancels_every_pending_step_without_enter(step_number):
    bus, _, _, _, ctl = rig()
    ctl.start(1, 1, "broth", 29, drive=7, selector=19, guided=True)
    for _ in range(step_number - 1):
        approve(ctl)
    assert pending(ctl).number == step_number
    before = len(bus.events)
    ctl.stop()
    ctl.tick()
    assert ctl.state == State.IDLE and ctl.pending_step is None
    assert not any(bus.coils)
    assert all(r[1] != 6 and not (r[1] == 15 and r[7]) for r in bus.events[before:])
    with pytest.raises(RuntimeError):
        ctl.confirm_step(step_number)


def test_confirmation_timeout_stops_booster_without_starting_vfd():
    bus, _, _, time, ctl = rig()
    ctl.start(1, 1, "broth", 29, drive=7, selector=19, guided=True)
    for _ in range(5):
        approve(ctl)
    assert pending(ctl).number == 6
    assert bus.coils[0] and not bus.coils[31]
    time[0] = 31
    ctl.tick()
    assert ctl.state == State.STOPPING and "подтверждения" in ctl.fault_reason
    assert not bus.coils[0] and not bus.coils[31]
    ctl.tick()
    assert ctl.state == State.FAULT and not any(bus.coils)


@pytest.mark.parametrize("failure", ["pressure", "signal", "communication", "drive", "unexpected_relay"])
def test_pressure_and_feedback_are_monitored_while_waiting_for_enter(failure):
    bus, _, _, _, ctl = rig(high_max_bar=80)
    ctl.start(1, 1, "broth", 29, drive=7, selector=19, guided=True)
    approve(ctl)
    assert pending(ctl).number == 2
    if failure == "pressure":
        bus.raw[1] = 16800  # exactly 80 bar
    elif failure == "signal":
        bus.raw[1] = 0
    elif failure == "communication":
        bus.failure = lambda r: b"" if r[0] == 6 else None
    elif failure == "drive":
        bus.registers[7][0x5001] = 1
    else:
        bus.coils[11] = True  # wrong rack, relay 12
    ctl.tick()
    assert ctl.state == State.STOPPING and ctl.pending_step is None
    assert not bus.coils[31] and not bus.coils[0]
    assert ctl.fault_reason


def test_relay_ack_with_wrong_coil_does_not_advance_to_next_valve_or_pump():
    bus, _, hw, _, ctl = rig()
    ctl.start(1, 1, "broth", 29, drive=7, selector=19, guided=True)
    approve(ctl)
    original = hw.transaction
    def swap(request):
        response = original(request)
        if request[1] == 15 and request[3] == 8 and request[7]:
            bus.coils[8], bus.coils[11] = False, True
        return response
    hw.transaction = swap
    approve(ctl)
    assert ctl.state == State.STOPPING
    assert "Реле 9" in ctl.fault_reason
    assert not bus.coils[0] and not bus.coils[18] and not bus.coils[22] and not bus.coils[31]


def test_stop_event_after_enter_prevents_the_approved_actuator_write():
    bus, _, hw, _, ctl = rig()
    cancelled = Event()
    hw.cancelled = cancelled.is_set
    ctl.start(1, 1, "broth", 29, drive=7, selector=19, guided=True)
    step = pending(ctl)
    ctl.confirm_step(step.number)
    cancelled.set()
    ctl.tick()
    assert ctl.state == State.STOPPING and not any(r[1] == 6 for r in bus.events)


def test_stop_while_printing_relay_command_prevents_serial_enable():
    bus, _, hw, _, ctl = rig()
    cancelled = Event()
    hw.cancelled = cancelled.is_set
    def report(text):
        if text.startswith("Реле 9: ВКЛ"):
            cancelled.set()
    hw.report = report
    ctl.start(1, 1, "broth", 29, drive=7, selector=19, guided=True)
    approve(ctl)
    approve(ctl)
    assert ctl.state == State.STOPPING
    assert not any(r[1] == 15 and r[7] for r in bus.events)


def test_low_pressure_loss_while_waiting_for_fwd_enter_stops_booster():
    bus, _, _, _, ctl = rig()
    ctl.start(1, 1, "broth", 29, drive=7, selector=19, guided=True)
    for _ in range(5):
        approve(ctl)
    assert pending(ctl).number == 6 and bus.coils[0]
    bus.raw[0] = 4000
    ctl.tick()
    assert ctl.state == State.STOPPING and "Подпор пропал" in ctl.fault_reason
    assert not bus.coils[0] and not bus.coils[31]


def test_current_read_failure_during_enter_wait_is_not_displayed_as_zero():
    bus, _, _, _, ctl = rig()
    ctl.start(1, 1, "broth", 29, drive=7, selector=19, guided=True)
    approve(ctl)
    assert pending(ctl).number == 2
    bus.failure = lambda r: b"" if r[0] == 7 and r[1:6] == bytes.fromhex("03 00 03 00 01") else None
    ctl.tick()
    assert ctl.state == State.STOPPING and ctl.last is None and not bus.coils[31]


def test_measurements_refresh_repeatedly_without_confirming_a_step():
    bus, cfg, hw, _, _ = rig(telemetry_ms=1)
    ready, refreshed = Event(), Event()
    def report(text):
        if "Enter — подтвердить" in text:
            ready.set()
        if "ДВД=1.25 бар" in text and "ток=7.3 А" in text:
            refreshed.set()
    service = IrrigationService(hw, cfg, RLock(), report)
    service.start(1, 1, "broth", 29, guided=True)
    try:
        assert ready.wait(2)
        with service.bus_lock:
            bus.raw[1] = 4200
            bus.registers[7][3] = 73
        assert refreshed.wait(2)
        assert service.controller.pending_step.number == 1 and not writes(bus)
    finally:
        service.close()


@pytest.mark.parametrize("option", ["telemetry_ms", "step_timeout_ms"])
def test_step_and_telemetry_intervals_validate_and_persist(tmp_path, option):
    from rtuforge.irrigation_config import load_irrigation_settings, set_irrigation_option
    path = tmp_path / "stand.ini"
    cfg = load_irrigation_settings(path)
    cfg = set_irrigation_option(path, cfg, option, "1500")
    assert getattr(load_irrigation_settings(path), option) == 1500
    before = path.read_bytes()
    with pytest.raises(ValueError):
        set_irrigation_option(path, cfg, option, "0")
    assert path.read_bytes() == before


def test_worker_cli_enter_telemetry_and_eof_cleanup(tmp_path):
    ctx, _, bus = cli_rig(tmp_path)
    ctx.one_shot = False
    bus.auto_feedback = True
    bus.registers[7][3] = 73
    ready, running = Event(), Event()
    def report(text):
        if "Enter — подтвердить" in text:
            ready.set()
        if text == "Полив: RUNNING":
            running.set()
        ctx.console.print(text, markup=False)
    service = IrrigationService(_hardware(ctx, quiet=True), ctx.irrigation_settings, ctx.bus_lock, report)
    ctx.irrigation = service
    execute_command(ctx, "start step 1 1 broth 29")
    try:
        for number in range(1, 7):
            assert ready.wait(2), service.controller.fault_reason
            ready.clear()
            assert service.controller.pending_step.number == number
            execute_command(ctx, "")
        assert running.wait(2), service.controller.fault_reason
        output = " ".join(ctx.console.export_text().split())
        assert "НВД=" in output and "ДВД=" in output and "ток=7.3 А" in output
        assert "Реле 9: ВКЛ — клапан ВД: стеллаж 1, ярус 1" in output
        assert "Реле 9: ВКЛ подтверждено платой" in output
        assert bus.maximum_transactions == 1
    finally:
        from rtuforge.stand_cli import _shutdown
        _shutdown(ctx)
    assert service.finished.is_set() and not service.thread.is_alive() and not any(bus.coils)


@pytest.mark.parametrize("end", ["stop", "eof"])
def test_one_shot_guided_prompt_uses_the_same_enter_and_stop_executor(tmp_path, monkeypatch, end):
    ctx, _, bus = cli_rig(tmp_path)
    ctx.one_shot = True
    bus.auto_feedback = True
    ready, running = Event(), Event()
    def report(text):
        if "Enter — подтвердить" in text:
            ready.set()
        if text == "Полив: RUNNING":
            running.set()
    service = IrrigationService(_hardware(ctx, quiet=True), ctx.irrigation_settings, ctx.bus_lock, report)
    ctx.irrigation = service
    class StepPrompt:
        count = 0
        def prompt(self, message):
            self.count += 1
            if end == "eof" and self.count == 2:
                raise EOFError
            if self.count <= 6:
                assert ready.wait(2), service.controller.fault_reason
                ready.clear()
                assert service.controller.pending_step.number == self.count
                return ""
            assert running.wait(2), service.controller.fault_reason
            return "stop"
    monkeypatch.setattr("rtuforge.stand_cli.PromptSession", StepPrompt)
    monkeypatch.setattr("rtuforge.stand_cli.patch_stdout", nullcontext)
    try:
        execute_command(ctx, "start step 1 1 broth 29")
        assert service.finished.is_set() and service.controller.state == State.IDLE
        assert not any(bus.coils)
    finally:
        service.close()


@pytest.mark.parametrize("command", ["start step", "start step 1 1 broth nan", "start step 1 1 broth 0"])
def test_invalid_step_command_does_not_connect(tmp_path, command):
    ctx, transport, bus = cli_rig(tmp_path)
    with pytest.raises(ValueError):
        execute_command(ctx, command)
    assert not transport.connected and not bus.events and ctx.irrigation is None


def test_monitor_reports_documented_motor_current_without_writes(tmp_path):
    ctx, _, bus = cli_rig(tmp_path)
    bus.registers[7][3] = 73
    execute_command(ctx, "idd 7 monitor")
    assert "ток двигателя=7.3 А" in " ".join(ctx.console.export_text().split())
    assert all(r[1] == 3 for r in bus.events)


def test_step_tab_completion():
    from rtuforge.stand_completion import completion_candidates
    assert completion_candidates("start s") == ["step"]
    assert completion_candidates("start step ") == ["1", "2"]
    assert completion_candidates("start step 1 ") == ["1", "2", "3"]
    assert completion_candidates("start step 1 1 ") == ["broth"]
