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
from rtuforge.stand_sensors import LOW, decode_pressure, ma_to_bar


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
                                  1: 0, 2: 0, 10: 0, 0x5000: 0, 0x5001: 0}
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
    ctl.start(1, 1, "broth", 60, drive=7, selector=19)
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
    assert bus.registers[7][1] == 270  # 60% of this drive's Pb05=450
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
    ctl.start(1, 1, "broth", 60, drive=7, selector=19)
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
    ctl.start(1, 1, "broth", 60, drive=7, selector=19)
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
        hw.set_frequency(7, 35)
    assert not any(r[1] == 6 for r in bus.events)
    assert bus.registers[7][0x69] == 450 and bus.registers[7][0x6A] == 200
    bus.registers[8][0x69] = 600
    hw.set_frequency(8, 50)
    assert bus.registers[8][1] == 300


def test_setpoint_readback_must_match():
    bus, cfg, hw, time, ctl = rig()
    def mismatch(request):
        if request[0] == 7 and request[1:6] == bytes.fromhex("03 00 01 00 01"):
            return append_crc(bytes.fromhex("07 03 02 00 00"))
    bus.failure = mismatch
    with pytest.raises(RuntimeError, match="Уставка"):
        hw.set_frequency(7, 60)


@pytest.mark.parametrize("stage", range(7))
def test_stop_during_every_start_stage(stage):
    bus, cfg, hw, time, ctl = rig()
    ctl.start(1, 1, "broth", 60, drive=7, selector=19)
    for _ in range(stage):
        ctl.tick()
    with pytest.raises(RuntimeError, match="START"):
        ctl.start(1, 1, "broth", 60, drive=7, selector=19)
    ctl.stop()
    stop_feedback(bus)
    ctl.tick()
    assert ctl.state == State.IDLE and not any(bus.coils)


@pytest.mark.parametrize("raw,mode", [(0, 3), (3000, 3), (21000, 3), (8000, 2), (8000, 4)])
def test_bad_ai_cannot_start_actuators(raw, mode):
    bus, cfg, hw, time, ctl = rig()
    bus.raw[0], bus.types[0] = raw, mode
    ctl.start(1, 1, "broth", 60, drive=7, selector=19)
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
    service.start(1, 1, "broth", 60)
    try:
        assert running.wait(2), service.controller.fault_reason
        with pytest.raises(RuntimeError, match="START"):
            service.start(1, 1, "broth", 60)
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
    ctl.start(1, 1, "broth", 60, drive=7, selector=19)
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


@pytest.mark.parametrize("topic", ["", "idd", "ai", "start", "stop", "pressure", "test-pressure", "reset", "set", "exit"])
def test_cli_russian_help_never_connects_or_writes(tmp_path, topic):
    from test_standforge import make_ctx
    from rtuforge.stand_cli import execute_command
    ctx, transport = make_ctx(tmp_path)
    execute_command(ctx, f"help {topic}")
    assert not transport.connected and not transport.requests
    assert ctx.console.export_text()
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


@pytest.mark.parametrize("command", ["start 1 1 broth 60", "start 9 1 broth 60", "start 1 1 broth nan", "idd 7 configure", "idd 7 frequency nan"])
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
    execute_command(ctx, "start 1 1 broth 60")
    try:
        assert running.wait(2)
        for command in ("on 32", "off 9", "reset", "disconnect", "set relay-id 5", "idd 7 frequency 60", "start 1 1 broth 60"):
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
    service.start(1, 1, "broth", 60)
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
    monkeypatch.setattr("sys.argv", ["standforge", "--home", str(tmp_path), "start", "1", "1", "broth", "60"])
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
    monkeypatch.setattr("sys.argv", ["standforge", "--home", str(tmp_path), "start", "1", "1", "broth", "60"])
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
