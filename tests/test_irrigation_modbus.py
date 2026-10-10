"""No hardware access: exercise the real adapter against a Modbus bus simulator."""
from dataclasses import replace
from threading import Event, RLock

import pytest

from rtuforge.crc import append_crc
from rtuforge.irrigation import IrrigationController, Limits, State
from rtuforge.irrigation_config import (IrrigationSettings, OPTION_SPECS,
                                        load_irrigation_settings, set_irrigation_option)
from rtuforge.irrigation_service import IrrigationService
from rtuforge.stand_config import load_stand_settings, save_stand_settings, StandSettings
from rtuforge.stand_hardware import StandHardware
from rtuforge.stand_protocol import build_read_request, validate_read_response
from rtuforge.stand_sensors import HIGH, LOW, decode_pressure, ma_to_bar


@pytest.fixture(autouse=True)
def forbid_real_serial(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("A test attempted to access a real serial port")
    monkeypatch.setattr("serial.Serial", forbidden)


def commissioned(**kwargs):
    # Synthetic RUN/fault registers belong only to this simulator, not a real IDD map.
    cfg = IrrigationSettings(enabled=True, ai_verified=True, vfd_verified=True,
                             hydraulics_verified=True, protections_verified=True,
                             pressure_unit_verified=True, relay_id_verified=True,
                             run_register=0x5000, fault_register=0x5001,
                             valve_delay_ms=0, poll_ms=1)
    return replace(cfg, **kwargs)


class ModbusBus:
    def __init__(self):
        self.events = []
        self.coils = [False] * 32
        self.raw = [8000, 4000, 0, 0]
        self.types = [3, 3, 2, 2]
        self.registers = {drive: {0x64: 500, 0x65: 5, 0x66: 1, 0x69: 450,
                                  0x6A: 200, 0x13B: 6, 0x13C: 7,
                                  1: 0, 2: 0, 3: 0, 10: 0, 0x5000: 0, 0x5001: 0}
                          for drive in (7, 8)}
        self.failure = None
        self.auto_feedback = False
        self.active_transactions = 0
        self.maximum_transactions = 0

    def transaction(self, request):
        self.active_transactions += 1
        self.maximum_transactions = max(self.maximum_transactions, self.active_transactions)
        try:
            return self._reply(request)
        finally:
            self.active_transactions -= 1

    def _reply(self, request):
        self.events.append(request)
        if self.failure is not None:
            failed = self.failure(request)
            if failed is not None:
                return failed
        slave, fn = request[:2]
        address, count = int.from_bytes(request[2:4], "big"), int.from_bytes(request[4:6], "big")
        if fn == 15:
            self.coils[address] = bool(request[7] & 1)
            if self.auto_feedback and address in (30, 31):
                drive = 7 if address == 31 else 8
                self.registers[drive][2] = self.registers[drive][1] if self.coils[address] else 0
                self.registers[drive][0x5000] = int(self.coils[address])
                self.raw[1] = 13600 if any(self.coils[30:32]) else 4000
            return append_crc(request[:6])
        if fn == 6:
            self.registers[slave][address] = count
            if address == 0x2001:
                self.registers[slave][1] = count
            return append_crc(request)
        if fn == 1:
            data = bytes(sum(int(self.coils[i+j]) << j for j in range(8)) for i in range(0, 32, 8))
        else:
            if slave == 6:
                values = self.types[address-0x1000:address-0x1000+count] if fn == 3 else self.raw[address:address+count]
            else:
                values = [self.registers[slave][address+i] for i in range(count)]
            data = b"".join(v.to_bytes(2, "big") for v in values)
        return append_crc(bytes((slave, fn, len(data))) + data)


def rig(**kwargs):
    bus = ModbusBus()
    cfg = commissioned(**kwargs)
    hw = StandHardware(bus.transaction, 1, cfg)
    time = [0.0]
    ctl = IrrigationController(hw, cfg.limits(), clock=lambda: time[0])
    return bus, cfg, hw, time, ctl


def to_running(bus, time, ctl):
    ctl.start(1, 1, "broth", 27, drive=7, selector=19)
    for _ in range(6):
        ctl.tick()
    assert ctl.state == State.WAIT_HIGH_PRESSURE
    assert bus.coils[31]
    bus.registers[7][0x5000] = 1
    bus.registers[7][2] = 270
    bus.raw[1] = 13600
    ctl.tick()
    assert ctl.state == State.RUNNING


def stop_feedback(bus):
    bus.registers[7][0x5000] = 0
    bus.registers[7][2] = 0


def test_successful_sequence_and_valve_closes_only_after_confirmed_stop():
    bus, cfg, hw, time, ctl = rig()
    to_running(bus, time, ctl)
    writes = [(int.from_bytes(r[2:4], "big") + 1, bool(r[7])) for r in bus.events if r[1] == 15]
    assert writes == [(9, True), (19, True), (23, True), (1, True), (32, True)]
    assert bus.registers[7][1] == 270  # 27 Hz, written with the documented 0.1 Hz scale
    ctl.stop()
    ctl.tick()
    assert bus.coils[8] and ctl.state == State.STOPPING
    stop_feedback(bus)
    ctl.tick()
    assert ctl.state == State.IDLE
    assert not any(bus.coils)


def test_low_pressure_does_not_rise():
    bus, cfg, hw, time, ctl = rig()
    bus.raw[0] = 4000
    ctl.start(1, 1, "broth", 27, drive=7, selector=19)
    for _ in range(4):
        ctl.tick()
    assert ctl.state == State.WAIT_LOW_PRESSURE
    time[0] += 11
    ctl.tick()
    assert ctl.state == State.STOPPING and "НВД" in ctl.fault_reason
    assert not bus.coils[31]


@pytest.mark.parametrize("running", [0, 1])
def test_high_pressure_or_run_does_not_rise(running):
    bus, cfg, hw, time, ctl = rig()
    ctl.start(1, 1, "broth", 27, drive=7, selector=19)
    for _ in range(6):
        ctl.tick()
    bus.registers[7][0x5000] = running
    bus.registers[7][2] = 270 if running else 0
    time[0] += 21
    ctl.tick()
    assert ctl.state == State.STOPPING and "ДВД" in ctl.fault_reason
    assert not bus.coils[31] and bus.coils[8]


def test_overpressure_stops_immediately():
    bus, cfg, hw, time, ctl = rig()
    to_running(bus, time, ctl)
    bus.raw[1] = 16000  # 75 bar
    ctl.tick()
    assert ctl.state == State.STOPPING and "Превышено" in ctl.fault_reason
    assert not bus.coils[31]


def test_pressure_loss_delay_and_hysteresis():
    bus, cfg, hw, time, ctl = rig()
    to_running(bus, time, ctl)
    bus.raw[1] = 11840  # 49 bar
    ctl.tick()
    assert ctl.state == State.RUNNING
    time[0] += 1
    bus.raw[1] = 12016  # 50.1 bar, below recovery hysteresis
    ctl.tick()
    assert ctl.low_since == 0
    time[0] += 1.1
    ctl.tick()
    assert ctl.state == State.STOPPING and "протечка" in ctl.fault_reason


@pytest.mark.parametrize("failure", ["broken", "timeout", "fault", "run_lost", "crc"])
def test_feedback_failures_stop_and_fault(failure):
    bus, cfg, hw, time, ctl = rig()
    to_running(bus, time, ctl)
    if failure == "broken":
        bus.raw[0] = 0
    elif failure == "timeout":
        bus.failure = lambda request: b"" if request[0] == 6 else None
    elif failure == "crc":
        bus.failure = lambda request: bytes.fromhex("06 04 02 00 00 00 00") if request[0] == 6 else None
    elif failure == "fault":
        bus.registers[7][0x5001] = 3
    else:
        bus.registers[7][0x5000] = 0
    ctl.tick()
    assert ctl.state == State.STOPPING and not bus.coils[31]
    stop_feedback(bus)
    ctl.tick()
    assert ctl.state == State.FAULT
    assert not bus.coils[8]  # AI failure does not prevent independent valid STOP feedback


@pytest.mark.parametrize("lost", [True, False])
def test_missing_stop_confirmation_keeps_valve_open(lost):
    bus, cfg, hw, time, ctl = rig()
    to_running(bus, time, ctl)
    ctl.stop()
    if lost:
        bus.failure = lambda request: b"" if request[0] == 7 else None
    time[0] += 16
    ctl.tick()
    assert ctl.state == State.FAULT and bus.coils[8]
    with pytest.raises(RuntimeError):
        ctl.reset_fault()
    bus.failure = None
    stop_feedback(bus)
    ctl.reset_fault()
    assert ctl.state == State.IDLE and not bus.coils[8]


def test_failed_stop_relay_does_not_prevent_remaining_off_attempts():
    bus, cfg, hw, time, ctl = rig()
    to_running(bus, time, ctl)
    bus.failure = lambda request: b"" if request[1] == 15 and request[3] == 31 else None
    ctl.stop()
    assert not bus.coils[0] and not bus.coils[18] and not bus.coils[22]
    stop_feedback(bus)
    time[0] += 16
    ctl.tick()
    assert ctl.state == State.FAULT and bus.coils[8]


def test_frequency_below_minimum_does_not_write_or_change_limits():
    bus, cfg, hw, time, ctl = rig()
    with pytest.raises(RuntimeError, match="Pb06"):
        hw.set_frequency(7, 19)
    assert not any(r[1] == 6 for r in bus.events)
    assert bus.registers[7][0x69] == 450 and bus.registers[7][0x6A] == 200
    bus.registers[8][0x69] = 600
    hw.set_frequency(8, 30)
    assert bus.registers[8][1] == 300


def test_setpoint_readback_must_match():
    bus, cfg, hw, time, ctl = rig()
    def mismatch(request):
        if request[0] == 7 and request[1:6] == bytes.fromhex("03 00 01 00 01"):
            return append_crc(bytes.fromhex("07 03 02 00 00"))
    bus.failure = mismatch
    with pytest.raises(RuntimeError, match="Уставка"):
        hw.set_frequency(7, 27)


@pytest.mark.parametrize("stage", range(7))
def test_stop_during_every_start_stage(stage):
    bus, cfg, hw, time, ctl = rig()
    ctl.start(1, 1, "broth", 27, drive=7, selector=19)
    for _ in range(stage):
        ctl.tick()
    with pytest.raises(RuntimeError, match="START"):
        ctl.start(1, 1, "broth", 27, drive=7, selector=19)
    ctl.stop()
    stop_feedback(bus)
    ctl.tick()
    assert ctl.state == State.IDLE and not any(bus.coils)


@pytest.mark.parametrize("raw,mode", [(0, 3), (3000, 3), (21000, 3), (8000, 2), (8000, 4)])
def test_bad_ai_cannot_start_actuators(raw, mode):
    bus, cfg, hw, time, ctl = rig()
    bus.raw[0], bus.types[0] = raw, mode
    ctl.start(1, 1, "broth", 27, drive=7, selector=19)
    ctl.tick()
    assert ctl.state == State.STOPPING
    assert not any(r[1] == 15 and r[7] == 1 for r in bus.events)


@pytest.mark.parametrize("payload", ["07 03 02 00 01", "06 04 02 00 01", "06 03 04 00 01 00 02", "06 83 02 00", "06 03 02 00"])
def test_invalid_modbus_response(payload):
    request = build_read_request(6, 3, 0x1000, 1)
    with pytest.raises(RuntimeError):
        validate_read_response(request, append_crc(bytes.fromhex(payload)))


def test_emergency_off_attempts_both_drives_and_booster_even_on_failure():
    bus, cfg, hw, time, ctl = rig()
    bus.coils[0] = bus.coils[30] = bus.coils[31] = True
    bus.failure = lambda request: b"" if request[1] == 15 and request[3] == 31 else None
    with pytest.raises(RuntimeError, match="не подтверждено"):
        hw.emergency_off()
    assert not bus.coils[0] and not bus.coils[30] and bus.coils[31]
    assert bus.events[-1][1] == 1


def test_setup_is_readonly_and_configuration_requires_open_fwd():
    bus, cfg, hw, time, ctl = rig()
    hw.check_setup(7)
    assert all(r[1] == 3 for r in bus.events)
    bus.coils[31] = True
    with pytest.raises(RuntimeError, match="FWD"):
        hw.configure(7)
    assert not any(r[1] == 6 for r in bus.events)
    bus.coils[31] = False
    hw.configure(7)
    assert [int.from_bytes(r[2:4], "big") for r in bus.events if r[1] == 6] == [0x65, 0x66, 0x13B, 0x13C]


def test_worker_nonblocking_stop_and_shutdown():
    bus, cfg, hw, time, ctl = rig()
    bus.auto_feedback = True
    running = Event()
    service = IrrigationService(hw, cfg, RLock(), lambda text: running.set() if "RUNNING" in text else None)
    service.start(1, 1, "broth", 27)
    try:
        assert running.wait(2), service.controller.fault_reason
        with pytest.raises(RuntimeError, match="START"):
            service.start(1, 1, "broth", 27)
        service.close()
        assert service.finished.is_set() and service.controller.state == State.IDLE
        assert not any(bus.coils)
        assert not service.thread.is_alive()
        assert bus.maximum_transactions == 1
    finally:
        service.close()


def test_stop_between_valve_writes_prevents_any_later_enable():
    bus, cfg, hw, time, ctl = rig()
    stop = Event()
    hw.cancelled = stop.is_set
    original = hw.transaction
    def transaction(request):
        result = original(request)
        if request[1] == 15 and request[3] == 8 and request[7] == 1:
            stop.set()
        return result
    hw.transaction = transaction
    ctl.start(1, 1, "broth", 27, drive=7, selector=19)
    for _ in range(3):
        ctl.tick()
    assert ctl.state == State.STOPPING and not ctl.fault_reason
    assert not bus.coils[18] and not bus.coils[0] and not bus.coils[31]


def test_config_load_and_mutation_preserve_other_user_sections(tmp_path):
    path = tmp_path / "stand.ini"
    assert load_irrigation_settings(path) == IrrigationSettings()
    assert not path.exists()
    path.write_text("[devices]\nrelay_address=5\ncustom=keep\n[output]\nrange=4-20ma\n[private]\nx=keep\n", encoding="utf-8")
    cfg = IrrigationSettings()
    cfg = set_irrigation_option(path, cfg, "poll_ms", "100")
    assert load_irrigation_settings(path).poll_ms == 100
    save_stand_settings(path, replace(load_stand_settings(path), relay_address=3))
    text = path.read_text(encoding="utf-8")
    assert "private" in text and "custom = keep" in text and "poll_ms = 100" in text
    assert len(OPTION_SPECS) == len(cfg.__dict__)
    before = path.read_bytes()
    with pytest.raises(ValueError):
        set_irrigation_option(path, cfg, "poll_ms", "0")
    assert path.read_bytes() == before


@pytest.mark.parametrize("kwargs", [{"poll_ms": 0}, {"high_target_bar": float("nan")},
                                   {"low_min_bar": -1}, {"run_mask": 0}, {"pump1_drive": 8},
                                   {"run_register": 2}, {"fault_register": 10}])
def test_config_rejects_invalid_values(kwargs):
    with pytest.raises(ValueError):
        replace(IrrigationSettings(), **kwargs).validate()


def test_all_commissioning_confirmations_required():
    cfg = commissioned()
    cfg.require_commissioned()
    for name in ("enabled", "ai_verified", "vfd_verified", "hydraulics_verified",
                 "protections_verified", "pressure_unit_verified", "relay_id_verified"):
        with pytest.raises(RuntimeError, match="заблокирован"):
            replace(cfg, **{name: False}).require_commissioned()
    assert replace(cfg, pump1_drive=8, pump2_drive=7).mapping(1) == (8, 19)


@pytest.mark.parametrize("tolerance", [float("nan"), float("inf"), -1, 4])
def test_invalid_sensor_tolerance(tolerance):
    with pytest.raises(ValueError):
        ma_to_bar(0, 6, tolerance_ma=tolerance)


def test_microamps_scaling():
    assert decode_pressure(12000, 3, LOW) == (12, 3)


@pytest.mark.parametrize("state,running", [(0, False), (1, True), (2, True)])
def test_plus_feedback_uses_documented_enum_and_full_error_code(state, running):
    bus, cfg, hw, _, _ = rig(run_register=28, fault_register=27,
                            run_mask=1, fault_mask=1)
    bus.registers[7].update({27: 2, 28: state, 2: 0})
    assert hw.drive_feedback(7) == (0, running, True)
    assert all(request[1] == 3 for request in bus.events)
    assert [int.from_bytes(request[2:4], "big") for request in bus.events] == [2, 27]


@pytest.mark.parametrize("state", [3, 4, 65535])
def test_plus_feedback_rejects_undocumented_state_even_with_zero_frequency(state):
    bus, cfg, hw, _, _ = rig(run_register=28, fault_register=27)
    bus.registers[7].update({27: 0, 28: state, 2: 0})
    with pytest.raises(RuntimeError, match="недопустимое PA28"):
        hw.drive_feedback(7)


def test_plus_controller_uses_fwd_relay_and_waits_for_actual_state_before_closing():
    bus, cfg, hw, time, ctl = rig(run_register=28, fault_register=27)
    bus.registers[7].update({27: 0, 28: 0})
    ctl.start(1, 1, "broth", 27, drive=7, selector=19)
    for _ in range(6):
        ctl.tick()
    assert bus.coils[31] and ctl.state == State.WAIT_HIGH_PRESSURE
    bus.registers[7].update({2: 270, 28: 1})
    bus.raw[1] = 13600
    ctl.tick()
    assert ctl.state == State.RUNNING
    ctl.stop()
    ctl.tick()
    assert not bus.coils[31] and bus.coils[8]
    bus.registers[7][2] = 0
    ctl.tick()
    assert ctl.state == State.STOPPING and bus.coils[8]
    bus.registers[7][28] = 0
    ctl.tick()
    assert ctl.state == State.IDLE and not bus.coils[8]
    assert not any(request[1] == 6 and int.from_bytes(request[2:4], "big") == 0x2000 for request in bus.events)


def test_plus_current_fault_blocks_start_even_when_history_is_zero():
    bus, cfg, hw, time, ctl = rig(run_register=28, fault_register=27)
    bus.registers[7].update({27: 9, 28: 0, 10: 0})
    ctl.start(1, 1, "broth", 27, drive=7, selector=19)
    ctl.tick()
    assert ctl.state == State.STOPPING
    ctl.tick()
    assert ctl.state == State.FAULT
    assert not any(bus.coils)


def test_plus_undocumented_state_keeps_tier_open_after_stop_timeout():
    bus, cfg, hw, time, ctl = rig(run_register=28, fault_register=27)
    bus.registers[7].update({27: 0, 28: 0})
    ctl.start(1, 1, "broth", 27, drive=7, selector=19)
    for _ in range(6):
        ctl.tick()
    bus.registers[7].update({2: 270, 28: 1})
    ctl.stop()
    ctl.tick()
    bus.registers[7].update({2: 0, 28: 4})
    time[0] += 16
    ctl.tick()
    assert ctl.state == State.FAULT and bus.coils[8]


@pytest.mark.parametrize("drive", [7, 8])
def test_plus_feedback_command_is_readonly_and_does_not_require_commissioning(tmp_path, drive):
    from rtuforge.stand_cli import execute_command
    ctx, transport, bus = cli_rig(tmp_path)
    cfg = IrrigationSettings()
    ctx.irrigation_settings = cfg
    bus.registers[drive].update({27: 0, 28: 0, 10: 9})
    execute_command(ctx, f"idd {drive} feedback")
    output = ctx.console.export_text()
    assert "PA28 (0x001C)=0 — STOP" in output
    assert "текущая ошибка=0" in output
    assert all(request[0] == drive and request[1] == 3 for request in bus.events)
    assert ctx.irrigation_settings == cfg and not ctx.stand_config_path.exists()
    assert ctx.irrigation is None and not any(bus.coils)


@pytest.mark.parametrize("failure", ["timeout", "exception", "crc"])
def test_plus_feedback_does_not_fallback_to_frequency_or_history_on_error(failure):
    bus, cfg, hw, _, _ = rig(run_register=28, fault_register=27)
    bus.registers[7].update({27: 0, 28: 0})
    def fail(request):
        if int.from_bytes(request[2:4], "big") != 27:
            return None
        if failure == "exception":
            return append_crc(bytes((7, 0x83, 2)))
        return b"" if failure == "timeout" else bytes.fromhex("07 03 04 00 00 00 00 00 00")
    bus.failure = fail
    with pytest.raises(RuntimeError):
        hw.drive_feedback(7)
    assert all(request[1] == 3 for request in bus.events)


def test_plus_configure_rejects_run_with_zero_frequency_and_open_fwd():
    bus, cfg, hw, _, _ = rig(run_register=28, fault_register=27)
    bus.registers[7].update({27: 0, 28: 1, 2: 0})
    with pytest.raises(RuntimeError, match="STOP"):
        hw.configure(7)
    assert all(request[1] == 3 for request in bus.events)


def test_plus_feedback_tab_completion():
    from rtuforge.stand_completion import completion_candidates
    assert completion_candidates("idd 7 f") == ["feedback", "frequency"]


def test_high_pressure_zero_requires_live_zero_current_not_zero_register():
    assert decode_pressure(4000, 3, HIGH) == (4, 0)
    assert decode_pressure(13600, 3, HIGH) == pytest.approx((13.6, 60))
    with pytest.raises(ValueError, match="не подтверждает обрыв или нулевое давление") as error:
        decode_pressure(0, 3, HIGH)
    assert "4000 (4 мА)" in str(error.value)


def test_captured_ai_frame_preserves_zero_and_blocks_sample():
    bus, cfg, hw, _, _ = rig()
    captured = bytes.fromhex("06 04 08 10 4B 00 00 00 00 00 00 C4 71")
    bus.failure = lambda request: captured if request[:2] == b"\x06\x04" else None
    low, high = hw.pressure()
    assert low.raw == 4171 and low.bar == pytest.approx(0.064125)
    assert high.raw == 0 and high.bar is None
    assert "недостоверное измерение" in high.error
    with pytest.raises(RuntimeError, match="AI2: raw=0"):
        hw.sample(7)
    assert all(request[1] in (3, 4) for request in bus.events)


@pytest.mark.parametrize("topic", ["", "idd", "ai", "start", "stop", "pressure", "test-pressure", "reset", "set", "exit"])
def test_cli_russian_help_never_connects_or_writes(tmp_path, topic):
    from io import StringIO
    from rich.console import Console
    from test_standforge import make_ctx
    from rtuforge.stand_cli import execute_command
    ctx, transport = make_ctx(tmp_path)
    output = StringIO()
    ctx.console = Console(file=output, record=True, force_terminal=True, color_system="standard")
    execute_command(ctx, f"help {topic}")
    assert not transport.connected and not transport.requests
    assert ctx.console.export_text()
    assert "\x1b" not in output.getvalue()  # Inspect actual output, not ANSI-stripped export.
    assert not (tmp_path / "stand.ini").exists()


def cli_rig(tmp_path):
    from test_standforge import make_ctx
    from rtuforge.transport import Exchange
    ctx, transport = make_ctx(tmp_path)
    bus = ModbusBus()
    def exchange(request, **kwargs):
        assert kwargs["crc_mode_override"] == "append"
        transport.requests.append(request)
        return Exchange(append_crc(request), bus.transaction(request), 1.0)
    transport.exchange = exchange
    ctx.irrigation_settings = commissioned()
    return ctx, transport, bus


@pytest.mark.parametrize("command", ["start 1 1 broth 27", "start 9 1 broth 27", "start 1 1 broth nan", "idd 7 configure", "idd 7 frequency nan"])
def test_cli_invalid_or_uncommissioned_commands_do_not_connect(tmp_path, command):
    from test_standforge import make_ctx
    from rtuforge.stand_cli import execute_command
    ctx, transport = make_ctx(tmp_path)
    with pytest.raises((ValueError, RuntimeError)):
        execute_command(ctx, command)
    assert not transport.connected and not transport.requests


def test_cli_pressure_diagnostics_and_log_never_enable_pumps(tmp_path):
    from rtuforge.stand_cli import execute_command
    ctx, transport, bus = cli_rig(tmp_path)
    bus.raw[0] = 0
    execute_command(ctx, "test-pressure low")
    assert "недостоверно" in ctx.pressure_log[-1]
    execute_command(ctx, "test-pressure log")
    execute_command(ctx, "pressure")
    assert len(ctx.pressure_log) == 3
    assert all(r[1] in (3, 4) for r in bus.events)


def test_cli_emergency_stop_works_without_controller_or_commissioning(tmp_path):
    from rtuforge.stand_cli import execute_command
    ctx, transport, bus = cli_rig(tmp_path)
    ctx.irrigation_settings = IrrigationSettings()
    bus.coils[0] = bus.coils[30] = bus.coils[31] = True
    bus.coils[8] = True
    execute_command(ctx, "test-pressure stop")
    assert not bus.coils[0] and not bus.coils[30] and not bus.coils[31]
    assert bus.coils[8]


@pytest.mark.parametrize("drive", [7, 8])
def test_cli_monitor_reads_uncommissioned_drive_without_claiming_stop(tmp_path, drive):
    from rtuforge.stand_cli import execute_command
    ctx, transport, bus = cli_rig(tmp_path)
    cfg = IrrigationSettings()
    ctx.irrigation_settings = cfg
    bus.registers[drive][1] = 270
    bus.registers[drive][10] = 69  # history need not be a currently active fault
    execute_command(ctx, f"idd {drive} monitor")
    output = ctx.console.export_text()
    assert "связь Modbus подтверждена" in output
    assert "PA01=27 Гц; PA02=0 Гц" in output
    assert "RUN/STOP=неизвестно; текущая авария=неизвестно" in output
    assert all(request[0] == drive and request[1] == 3 for request in bus.events)
    assert ctx.irrigation_settings == cfg and ctx.irrigation is None
    assert not ctx.stand_config_path.exists()


@pytest.mark.parametrize("drive", [7, 8])
def test_cli_monitor_verified_profile_reports_actual_fault(tmp_path, drive):
    from rtuforge.stand_cli import execute_command
    ctx, transport, bus = cli_rig(tmp_path)
    bus.registers[drive][0x5001] = 1
    execute_command(ctx, f"idd {drive} monitor")
    assert "текущая авария=True" in ctx.console.export_text()
    assert all(request[1] == 3 for request in bus.events)


@pytest.mark.parametrize("drive", [7, 8])
@pytest.mark.parametrize("failure", ["timeout", "crc", "frequency"])
def test_cli_monitor_still_rejects_invalid_responses(tmp_path, drive, failure):
    from rtuforge.stand_cli import execute_command
    ctx, transport, bus = cli_rig(tmp_path)
    ctx.irrigation_settings = IrrigationSettings()
    if failure == "frequency":
        bus.registers[drive][2] = 4001
    else:
        bus.failure = lambda request: b"" if failure == "timeout" else bytes.fromhex("07 03 04 00 00 00 00 00 00")
    with pytest.raises(RuntimeError):
        execute_command(ctx, f"idd {drive} monitor")
    assert all(request[1] == 3 for request in bus.events)


@pytest.mark.parametrize("action", ["setup", "status", "monitor"])
def test_cli_all_drives_are_read_sequentially_without_commissioning(tmp_path, action):
    from rtuforge.stand_cli import execute_command
    ctx, transport, bus = cli_rig(tmp_path)
    ctx.irrigation_settings = IrrigationSettings()
    execute_command(ctx, f"idd all {action}")
    ids = [request[0] for request in bus.events]
    assert set(ids) == {7, 8} and ids == sorted(ids)
    assert all(request[1] == 3 for request in bus.events)
    assert not any(bus.coils) and not ctx.stand_config_path.exists()


@pytest.mark.parametrize("action", ["setup", "status", "monitor"])
def test_cli_all_drives_checks_drive_eight_when_seven_fails(tmp_path, action):
    from rtuforge.stand_cli import execute_command
    ctx, transport, bus = cli_rig(tmp_path)
    ctx.irrigation_settings = IrrigationSettings()
    bus.failure = lambda request: b"" if request[0] == 7 else None
    with pytest.raises(RuntimeError, match="IDD 7"):
        execute_command(ctx, f"idd all {action}")
    assert any(request[0] == 8 for request in bus.events)
    assert "IDD 8:" in ctx.console.export_text()
    assert all(request[1] == 3 for request in bus.events)


@pytest.mark.parametrize("command", ["idd all frequency 27", "idd all configure --confirm", "idd all monitor extra"])
def test_cli_grouped_drive_writes_rejected_before_connect(tmp_path, command):
    from rtuforge.stand_cli import execute_command
    ctx, transport, bus = cli_rig(tmp_path)
    with pytest.raises(ValueError):
        execute_command(ctx, command)
    assert not transport.connected and not bus.events


def test_cli_unblocked_monitor_does_not_unlock_configuration_or_start(tmp_path):
    from rtuforge.stand_cli import execute_command
    ctx, transport, bus = cli_rig(tmp_path)
    ctx.irrigation_settings = IrrigationSettings()
    execute_command(ctx, "idd all monitor")
    for command in ("idd 7 configure --confirm", "idd 8 configure --confirm", "start 1 1 broth 27"):
        with pytest.raises(RuntimeError):
            execute_command(ctx, command)
    assert all(request[1] == 3 for request in bus.events)
    assert not any(bus.coils)


def test_completion_for_both_drives_offers_only_read_commands():
    from rtuforge.stand_completion import completion_candidates
    assert completion_candidates("idd a") == ["all"]
    assert completion_candidates("idd all ") == ["monitor", "setup", "status"]


def test_cli_stop_distinguishes_relay_off_from_unknown_drive_stop(tmp_path):
    from rtuforge.stand_cli import execute_command
    ctx, transport, bus = cli_rig(tmp_path)
    ctx.irrigation_settings = IrrigationSettings()
    bus.coils[0] = bus.coils[30] = bus.coils[31] = True
    bus.coils[8] = True
    with pytest.raises(RuntimeError, match="Команды пуска сняты.*останов IDD не подтверждён") as error:
        execute_command(ctx, "stop")
    assert "IDD 7" in str(error.value) and "IDD 8" in str(error.value)
    assert not any(bus.coils[ch - 1] for ch in (1, 31, 32))
    assert bus.coils[8]


def test_cli_stop_checks_second_drive_when_first_does_not_respond(tmp_path):
    from rtuforge.stand_cli import execute_command
    ctx, transport, bus = cli_rig(tmp_path)
    bus.failure = lambda request: b"" if request[0] == 7 else None
    bus.registers[8][2] = 270
    bus.registers[8][0x5000] = 1
    with pytest.raises(RuntimeError, match="останов IDD не подтверждён") as error:
        execute_command(ctx, "stop")
    assert "IDD 7" in str(error.value) and "IDD 8: частота=27 Гц, RUN" in str(error.value)
    assert any(request[0] == 8 for request in bus.events)
    assert not any(bus.coils)


def test_cli_stop_reports_confirmed_drive_stop(tmp_path):
    from rtuforge.stand_cli import execute_command
    ctx, transport, bus = cli_rig(tmp_path)
    execute_command(ctx, "stop")
    assert "IDD 7 и 8: STOP и частота около нуля подтверждены" in ctx.console.export_text()
    assert not any(bus.coils)


def test_cli_start_allows_stop_and_blocks_conflicting_commands(tmp_path):
    from rtuforge.stand_cli import execute_command, _shutdown
    ctx, transport, bus = cli_rig(tmp_path)
    bus.auto_feedback = True
    ctx.one_shot = False
    running = Event()
    service = IrrigationService(StandHardware(lambda request: ctx.transport.exchange(request, crc_mode_override="append").rx,
                                              1, ctx.irrigation_settings),
                                ctx.irrigation_settings, ctx.bus_lock,
                                lambda text: running.set() if "RUNNING" in text else None)
    transport.connect()
    ctx.irrigation = service
    execute_command(ctx, "start 1 1 broth 27")
    try:
        assert running.wait(2)
        for command in ("on 32", "off 9", "reset", "disconnect", "set relay-id 5", "idd 7 frequency 27", "start 1 1 broth 27"):
            with pytest.raises(RuntimeError):
                execute_command(ctx, command)
        execute_command(ctx, "stop")
        assert service.finished.wait(2)
        assert service.controller.state == State.IDLE
        assert not any(bus.coils)
    finally:
        _shutdown(ctx)
    assert not transport.connected


def test_worker_shutdown_during_precheck_never_starts_actuators():
    bus, cfg, hw, time, ctl = rig()
    entered, release = Event(), Event()
    original = hw.transaction
    def delayed(request):
        if request[0] == 6 and not entered.is_set():
            entered.set()
            assert release.wait(2)
        return original(request)
    hw.transaction = delayed
    service = IrrigationService(hw, cfg, RLock(), lambda text: None)
    service.start(1, 1, "broth", 27)
    try:
        assert entered.wait(2)
        service.stop()  # does not wait for the in-flight bus operation
        release.set()
        service.close()
        assert service.controller.state == State.IDLE
        assert not any(r[1] == 15 and r[7] == 1 for r in bus.events)
    finally:
        release.set()
        service.close()


def test_completion_for_irrigation_commands():
    from rtuforge.stand_completion import completion_candidates
    assert "stop" in completion_candidates("st")
    assert "monitor" in completion_candidates("idd 7 ")
    assert completion_candidates("idd 8 configure ") == ["--confirm"]
    assert completion_candidates("start 1 1 ") == ["broth"]
    assert completion_candidates("test-pressure ") == ["high", "log", "low", "stop"]
    assert "poll_ms" in completion_candidates("set irrigation ")


def test_cli_oneshot_fault_returns_error_and_closes_transport(tmp_path, monkeypatch):
    from rtuforge import stand_cli
    ctx, transport, bus = cli_rig(tmp_path)
    bus.raw[0] = 0
    ctx.config_path.write_text("", encoding="utf-8")
    monkeypatch.setattr(stand_cli, "load_config", lambda path: ctx.config)
    monkeypatch.setattr(stand_cli, "load_irrigation_settings", lambda path: ctx.irrigation_settings)
    monkeypatch.setattr(stand_cli, "SerialTransport", lambda *args: transport)
    monkeypatch.setattr("sys.argv", ["standforge", "--home", str(tmp_path), "start", "1", "1", "broth", "27"])
    assert stand_cli.main() == 1
    assert not transport.connected
    assert not any(bus.coils)


@pytest.mark.parametrize("command", [["emergency-stop"], ["test-pressure", "stop"]])
def test_cli_emergency_ignores_invalid_pressure_config(tmp_path, monkeypatch, command):
    from rtuforge import stand_cli
    ctx, transport, bus = cli_rig(tmp_path)
    ctx.config_path.write_text("", encoding="utf-8")
    ctx.stand_config_path.write_text("[irrigation]\npoll_ms=0\n", encoding="utf-8")
    bus.coils[0] = bus.coils[30] = bus.coils[31] = True
    monkeypatch.setattr(stand_cli, "load_config", lambda path: ctx.config)
    monkeypatch.setattr(stand_cli, "SerialTransport", lambda *args: transport)
    monkeypatch.setattr("sys.argv", ["standforge", "--home", str(tmp_path), *command])
    assert stand_cli.main() == 0
    assert not any(bus.coils) and not transport.connected


def test_reset_fault_rejects_live_inverter_fault():
    bus, cfg, hw, time, ctl = rig()
    to_running(bus, time, ctl)
    bus.registers[7][0x5001] = 1
    ctl.tick()
    stop_feedback(bus)
    ctl.tick()
    with pytest.raises(RuntimeError):
        ctl.reset_fault()
    bus.registers[7][0x5001] = 0
    ctl.reset_fault()
    assert ctl.state == State.IDLE


def test_invalid_actual_frequency_stops_control():
    bus, cfg, hw, time, ctl = rig()
    to_running(bus, time, ctl)
    bus.registers[7][2] = 5000
    ctl.tick()
    assert ctl.state == State.STOPPING and "масштабирование" in ctl.fault_reason


def test_cli_ctrl_c_stops_worker_before_disconnect(tmp_path, monkeypatch):
    from rtuforge import stand_cli
    ctx, transport, bus = cli_rig(tmp_path)
    bus.auto_feedback = True
    ctx.config_path.write_text("", encoding="utf-8")
    monkeypatch.setattr(stand_cli, "load_config", lambda path: ctx.config)
    monkeypatch.setattr(stand_cli, "load_irrigation_settings", lambda path: ctx.irrigation_settings)
    monkeypatch.setattr(stand_cli, "SerialTransport", lambda *args: transport)
    monkeypatch.setattr("sys.argv", ["standforge", "--home", str(tmp_path), "start", "1", "1", "broth", "27"])
    real_execute = stand_cli.execute_command
    running = Event()
    observed = []
    def interrupt_after_running(context, line):
        context.one_shot = False
        service = IrrigationService(stand_cli._hardware(context, quiet=True), context.irrigation_settings,
                                    context.bus_lock, lambda text: running.set() if "RUNNING" in text else None)
        context.irrigation = service
        observed.append(service)
        real_execute(context, line)
        assert running.wait(2)
        raise KeyboardInterrupt
    monkeypatch.setattr(stand_cli, "execute_command", interrupt_after_running)
    assert stand_cli.main() == 130
    assert not transport.connected and not any(bus.coils)
    assert not observed[0].thread.is_alive()


def test_preflight_is_readonly_and_shares_frequency_calculation():
    from rtuforge.irrigation_preflight import check_start
    bus, cfg, hw, _, _ = rig()
    report = check_start(hw, cfg, 1, 1, "broth", 27)
    assert report.ready
    assert (report.drive, report.selector, report.valve) == (7, 19, 9)
    assert all(request[1] in (1, 3, 4) for request in bus.events)
    assert not any(bus.coils) and bus.registers[7][1] == 0
    plan = hw.frequency_plan(7, 27)
    hw.set_frequency(7, 27)
    assert bus.registers[7][1] == plan.setpoint_raw == 270


def test_preflight_collects_sensor_drive_relay_and_commissioning_failures():
    from rtuforge.irrigation_preflight import check_start
    bus, cfg, hw, _, _ = rig(enabled=False)
    bus.raw[0] = 0
    bus.coils[31] = True
    bus.registers[7][0x65] = 2
    bus.registers[7][0x5001] = 1
    report = check_start(hw, cfg, 1, 1, "broth", 27)
    assert not report.ready
    failures = [check for check in report.checks if not check.passed]
    assert len(failures) == 5
    assert any("AI1" == check.name for check in failures)
    assert any("Pb01" in check.detail for check in failures)
    assert any("enabled" in check.detail for check in failures)
    assert all(request[1] in (1, 3, 4) for request in bus.events)
    assert bus.coils[31]  # even an unsafe initial state is never silently changed


def test_preflight_calibrated_sensors_do_not_bypass_unknown_drive_feedback():
    from rtuforge.irrigation_preflight import check_start
    bus, cfg, hw, _, _ = rig(ai_verified=True, run_register=-1, fault_register=-1)
    report = check_start(hw, cfg, 1, 1, "broth", 27)
    assert not report.ready
    assert all(check.passed for check in report.checks if check.name in ("AI1", "AI2"))
    assert any("run_register" in check.detail for check in report.checks if not check.passed)
    assert all(request[1] in (1, 3, 4) for request in bus.events)


@pytest.mark.parametrize("failure", ["pressure", "frequency", "running", "timeout"])
def test_preflight_detects_operating_limits_and_communication_failure(failure):
    from rtuforge.irrigation_preflight import check_start
    bus, cfg, hw, _, _ = rig()
    hz = 27
    if failure == "pressure":
        bus.raw[1] = 16000
    elif failure == "frequency":
        hz = 19
    elif failure == "running":
        bus.registers[7][0x5000] = 1
    else:
        bus.failure = lambda request: b"" if request[0] == 6 else None
    report = check_start(hw, cfg, 1, 1, "broth", hz)
    assert not report.ready
    assert all(request[1] in (1, 3, 4) for request in bus.events)
    assert any(check.passed and check.name == "Релейная плата" for check in report.checks)


@pytest.mark.parametrize("args", [[], ["3", "1", "broth", "27"], ["1", "1", "water", "60"],
                                  ["1", "1", "broth", "nan"], ["1", "1", "broth", "0"]])
def test_preflight_cli_rejects_invalid_args_before_connecting(tmp_path, args):
    from rtuforge.stand_cli import execute_command
    ctx, transport, bus = cli_rig(tmp_path)
    with pytest.raises(ValueError):
        execute_command(ctx, "start check " + " ".join(args))
    assert not transport.connected and not bus.events


@pytest.mark.parametrize("enabled", [True, False])
def test_preflight_cli_does_not_create_controller_or_change_user_files(tmp_path, enabled):
    from rtuforge.stand_cli import execute_command
    ctx, transport, bus = cli_rig(tmp_path)
    ctx.irrigation_settings = replace(ctx.irrigation_settings, enabled=enabled)
    original = "[irrigation]\nenabled=false\n[private]\nx=keep\n"
    ctx.stand_config_path.write_text(original, encoding="utf-8")
    if enabled:
        execute_command(ctx, "start check 1 1 broth 27")
    else:
        with pytest.raises(RuntimeError, match="БЛОК"):
            execute_command(ctx, "start check 1 1 broth 27")
    assert ctx.irrigation is None
    assert not any(bus.coils) and bus.registers[7][1] == 0
    assert ctx.stand_config_path.read_text(encoding="utf-8") == original
    assert ctx.irrigation_settings.enabled == enabled


def test_successful_preflight_does_not_cache_permission_to_start(tmp_path):
    from rtuforge.stand_cli import execute_command, _shutdown
    ctx, transport, bus = cli_rig(tmp_path)
    execute_command(ctx, "start check 1 1 broth 27")
    bus.raw[0] = 0
    ctx.one_shot = False
    execute_command(ctx, "start 1 1 broth 27")
    try:
        assert ctx.irrigation.finished.wait(2)
        assert ctx.irrigation.controller.state == State.FAULT
        assert not any(request[1] == 15 and request[7] == 1 for request in bus.events)
    finally:
        _shutdown(ctx)


def test_preflight_respects_explicit_pump_mapping():
    from rtuforge.irrigation_preflight import check_start
    bus, cfg, hw, _, _ = rig(pump1_drive=8, pump2_drive=7)
    bus.registers[8][0x69] = 600
    report = check_start(hw, cfg, 1, 3, "broth", 30)
    assert report.ready
    assert (report.drive, report.selector, report.valve) == (8, 19, 11)
    assert any("30 Гц" in check.detail for check in report.checks)
    assert not any(request[0] == 7 for request in bus.events)


def test_hex_feedback_configuration_roundtrip(tmp_path):
    path = tmp_path / "stand.ini"
    cfg = IrrigationSettings()
    for name, value in (("run_register", "0x5000"), ("fault_register", "0x5001"),
                        ("run_mask", "0x02"), ("fault_mask", "0xFF00")):
        cfg = set_irrigation_option(path, cfg, name, value)
    assert load_irrigation_settings(path) == cfg
    assert (cfg.run_register, cfg.fault_register, cfg.run_mask, cfg.fault_mask) == (0x5000, 0x5001, 2, 0xFF00)
    path.write_text("[irrigation]\nrun_register=0x5000\nfault_register=0x5001\n", encoding="utf-8")
    assert load_irrigation_settings(path).run_register == 0x5000
    before = path.read_bytes()
    with pytest.raises(ValueError):
        set_irrigation_option(path, cfg, "run_register", "0x0002")
    assert path.read_bytes() == before


def test_preflight_tab_completion():
    from rtuforge.stand_completion import completion_candidates
    assert completion_candidates("start c") == ["check"]
    assert completion_candidates("start check ") == ["1", "2"]
    assert completion_candidates("start check 1 ") == ["1", "2", "3"]
    assert completion_candidates("start check 1 1 ") == ["broth"]


def test_motor_minimum_and_hz_setpoint():
    bus, cfg, hw, _, _ = rig()
    with pytest.raises(RuntimeError, match="минимум мотора=24 Гц"):
        hw.frequency_plan(7, 22.5)
    assert hw.frequency_plan(7, 24).setpoint_raw == 240


@pytest.mark.parametrize("hz, raw", [(24, 240), (29, 290), (29.04, 290), (45, 450)])
def test_frequency_in_hz_writes_exact_scaled_setpoint_without_starting(hz, raw):
    bus, _, hw, _, _ = rig()
    plan = hw.set_frequency(7, hz)
    assert plan.requested_hz == hz and plan.maximum_raw == 450
    assert bus.registers[7][1] == plan.setpoint_raw == raw
    assert not any(bus.coils)
    writes = [r for r in bus.events if r[1] in (6, 15)]
    assert len(writes) == 1 and writes[0][1:4] == bytes.fromhex("06 20 01")


@pytest.mark.parametrize("hz", [20, 22.5, 23.99, 45.01, 50])
def test_frequency_outside_motor_and_vfd_limits_never_writes(hz):
    bus, _, hw, _, _ = rig()
    with pytest.raises(RuntimeError) as error:
        hw.set_frequency(7, hz)
    assert "максимум Pb05=45 Гц" in str(error.value)
    assert "допустимо 24..45 Гц" in str(error.value)
    assert all(r[1] == 3 for r in bus.events)
    assert bus.registers[7][1] == 0 and not any(bus.coils)


def test_frequency_is_hz_even_when_maximum_changes_and_pb06_can_be_stricter():
    bus, _, hw, _, _ = rig()
    bus.registers[7][0x69] = 600
    hw.set_frequency(7, 29)
    assert bus.registers[7][1] == 290
    bus.registers[7][0x6A] = 300
    bus.events.clear()
    with pytest.raises(RuntimeError, match="допустимо 30..60 Гц"):
        hw.set_frequency(7, 29)
    assert all(r[1] == 3 for r in bus.events)


def test_motor_limits_belong_to_drive_address_and_are_independently_configurable():
    bus, cfg, hw, _, _ = rig(pump1_drive=8, pump2_drive=7)
    assert hw.frequency_plan(8, 22.5).setpoint_raw == 225
    with pytest.raises(RuntimeError, match="минимум мотора=24 Гц"):
        hw.frequency_plan(7, 22.5)
    hw.settings = replace(cfg, drive8_min_hz=30)
    with pytest.raises(RuntimeError, match="допустимо 30..45 Гц"):
        hw.frequency_plan(8, 29)


@pytest.mark.parametrize("value", ["0", "-1", "nan", "inf", "401", "50%"])
@pytest.mark.parametrize("prefix", ["start check 1 1 broth", "start 1 1 broth", "idd 7 frequency"])
def test_invalid_hz_commands_do_not_connect(tmp_path, value, prefix):
    from rtuforge.stand_cli import execute_command
    ctx, transport, bus = cli_rig(tmp_path)
    with pytest.raises(ValueError):
        execute_command(ctx, f"{prefix} {value}")
    assert not transport.connected and not bus.events and ctx.irrigation is None


@pytest.mark.parametrize("command", ["start check 1 1 broth 29", "idd 7 frequency 29", "idd 7 setup"])
def test_hz_commands_show_maximum_and_motor_minimum(tmp_path, command):
    from rtuforge.stand_cli import execute_command
    ctx, _, bus = cli_rig(tmp_path)
    execute_command(ctx, command)
    output = " ".join(ctx.console.export_text().split())
    assert "максимум Pb05=45 Гц" in output and "минимум мотора=24 Гц" in output
    if "29" in command:
        assert "задание 29 Гц" in output
    if command != "idd 7 frequency 29":
        assert all(r[1] in (1, 3, 4) for r in bus.events)
    assert not any(bus.coils) and ctx.irrigation is None


def test_motor_frequency_settings_roundtrip_and_reject_invalid_values(tmp_path):
    path = tmp_path / "stand.ini"
    cfg = load_irrigation_settings(path)
    assert cfg.drive7_min_hz == 24 and cfg.drive8_min_hz == 0
    cfg = set_irrigation_option(path, cfg, "drive8_min_hz", "30")
    assert load_irrigation_settings(path).drive8_min_hz == 30
    before = path.read_bytes()
    for value in ("-1", "401", "nan", "inf"):
        with pytest.raises(ValueError):
            set_irrigation_option(path, cfg, "drive7_min_hz", value)
        assert path.read_bytes() == before


def test_motor_minimum_above_pb05_blocks_preflight_and_setpoint():
    from rtuforge.irrigation_preflight import check_start
    bus, cfg, hw, _, _ = rig()
    bus.registers[7][0x69] = 230
    report = check_start(hw, cfg, 1, 1, "broth", 23)
    assert not report.ready
    with pytest.raises(RuntimeError, match="минимум мотора=24 Гц"):
        hw.set_frequency(7, 23)
    assert all(r[1] in (1, 3, 4) for r in bus.events) and not any(bus.coils)


def test_setup_rejects_motor_minimum_above_maximum_without_writes(tmp_path):
    from rtuforge.stand_cli import execute_command
    ctx, _, bus = cli_rig(tmp_path)
    bus.registers[7][0x69] = 230
    with pytest.raises(RuntimeError, match="выше максимума Pb05=23 Гц"):
        execute_command(ctx, "idd 7 setup")
    assert all(r[1] == 3 for r in bus.events)
