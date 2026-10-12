"""Operator-calibrated zero markers never establish loop current or health."""
from dataclasses import replace
from threading import RLock

import pytest

from rtuforge.irrigation import State
from rtuforge.irrigation_config import load_irrigation_settings, set_irrigation_option
from rtuforge.irrigation_preflight import check_start
from rtuforge.irrigation_service import IrrigationService
from rtuforge.stand_cli import execute_command
from rtuforge.stand_sensors import HIGH, LOW, decode_pressure
from test_irrigation_modbus import cli_rig, rig, to_running


@pytest.fixture(autouse=True)
def forbid_real_serial(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("Zero-marker tests must never access hardware")
    monkeypatch.setattr("serial.Serial", forbidden)


@pytest.mark.parametrize("sensor", [LOW, HIGH])
def test_zero_marker_has_no_inferred_current_and_requires_explicit_permission(sensor):
    with pytest.raises(ValueError, match="raw=0"):
        decode_pressure(0, 3, sensor)
    assert decode_pressure(0, 3, sensor, zero_raw_is_zero=True) == (None, 0)
    assert decode_pressure(4000, 3, sensor, zero_raw_is_zero=True) == (4, 0)
    for raw, mode in [(0, 2), (1, 3), (3000, 3), (21000, 3), (-1, 3), (65536, 3)]:
        with pytest.raises(ValueError):
            decode_pressure(raw, mode, sensor, zero_raw_is_zero=True)


@pytest.mark.parametrize("channel", [1, 2])
def test_zero_permission_is_per_channel_and_persists_without_enabling_start(tmp_path, channel):
    path = tmp_path / "stand.ini"
    cfg = load_irrigation_settings(path)
    name = f"ai{channel}_zero_raw_is_zero"
    assert not getattr(cfg, name)
    cfg = set_irrigation_option(path, cfg, name, "true")
    assert load_irrigation_settings(path) == cfg
    assert not cfg.enabled and not cfg.ai_verified
    bus, _, hw, _, _ = rig(**{name: True})
    bus.raw[:2] = [0, 0]
    readings = hw.pressure()
    accepted, rejected = readings[channel - 1], readings[2 - channel]
    assert accepted.bar == 0 and accepted.current_ma is None and not accepted.error
    assert "исправность петли не определена" in accepted.warning
    assert rejected.bar is None and rejected.error


def test_preflight_reports_conditional_zero_without_writes_or_false_health_claim():
    bus, cfg, hw, _, _ = rig(ai1_zero_raw_is_zero=True, ai2_zero_raw_is_zero=True)
    bus.raw[:2] = [0, 0]
    report = check_start(hw, cfg, 1, 1, "broth", 29)
    assert report.ready
    for check in report.checks[1:3]:
        assert "ток=не определён" in check.detail
        assert "исправность петли не определена" in check.detail
    assert all(request[1] in (1, 3, 4) for request in bus.events)
    assert not any(bus.coils)


@pytest.mark.parametrize("command", ["pressure", "ai", "test-pressure low", "test-pressure high"])
def test_readonly_cli_warns_about_ambiguous_zero(tmp_path, command):
    ctx, _, bus = cli_rig(tmp_path)
    ctx.irrigation_settings = replace(ctx.irrigation_settings,
                                     ai1_zero_raw_is_zero=True, ai2_zero_raw_is_zero=True)
    bus.raw[:2] = [0, 0]
    execute_command(ctx, command)
    output = " ".join(ctx.console.export_text().split())
    assert "ток=не определён" in output and "0 бар" in output
    assert "исправность петли не определена" in output
    assert all(request[1] in (3, 4) for request in bus.events)


def test_zero_low_never_permits_fwd_and_still_times_out():
    bus, _, _, time, ctl = rig(ai1_zero_raw_is_zero=True, ai2_zero_raw_is_zero=True)
    bus.raw[:2] = [0, 0]
    ctl.start(1, 1, "broth", 29, drive=7, selector=19)
    for _ in range(4):
        ctl.tick()
    assert ctl.state == State.WAIT_LOW_PRESSURE and bus.coils[0]
    time[0] += 11
    ctl.tick()
    assert ctl.state == State.STOPPING and "Нет подпора" in ctl.fault_reason
    assert not bus.coils[0] and not bus.coils[31]


def test_zero_high_still_requires_pressure_rise_and_times_out():
    bus, _, _, time, ctl = rig(ai2_zero_raw_is_zero=True)
    bus.raw[1] = 0
    ctl.start(1, 1, "broth", 29, drive=7, selector=19)
    for _ in range(6):
        ctl.tick()
    assert ctl.state == State.WAIT_HIGH_PRESSURE
    bus.registers[7].update({2: 290, 0x5000: 1})
    time[0] += 21
    ctl.tick()
    assert ctl.state == State.STOPPING and "ДВД не набирается" in ctl.fault_reason
    assert not bus.coils[31] and not bus.coils[0]


@pytest.mark.parametrize("channel", [0, 1])
def test_zero_during_running_still_triggers_pressure_loss_stop(channel):
    bus, _, _, time, ctl = rig(ai1_zero_raw_is_zero=True, ai2_zero_raw_is_zero=True)
    to_running(bus, time, ctl)
    bus.raw[channel] = 0
    ctl.tick()
    assert ctl.state == State.RUNNING and ctl.last.pressure_warning
    time[0] += 2.1
    ctl.tick()
    assert ctl.state == State.STOPPING and "Падение давления" in ctl.fault_reason
    assert not bus.coils[31] and not bus.coils[0]


def test_telemetry_preserves_zero_warning_and_overpressure_limit():
    bus, cfg, hw, _, ctl = rig(ai1_zero_raw_is_zero=True, ai2_zero_raw_is_zero=True,
                              high_max_bar=80)
    bus.raw[:2] = [0, 0]
    output = []
    service = IrrigationService(hw, cfg, RLock(), output.append)
    service.controller = ctl
    ctl.start(1, 1, "broth", 29, drive=7, selector=19)
    ctl.tick()
    service._telemetry()
    assert "исправность петли не определена" in output[-1]
    bus.raw[1] = 16800  # 80 bar: the zero setting does not change normal scaling.
    ctl.tick()
    assert ctl.state == State.STOPPING and "Превышено ДВД" in ctl.fault_reason


def test_zero_permissions_do_not_hide_modbus_loss_or_bad_crc():
    bus, _, hw, _, _ = rig(ai1_zero_raw_is_zero=True, ai2_zero_raw_is_zero=True)
    for reply in (b"", bytes.fromhex("06 04 08 00 00 00 00 00 00 00 00 00 00")):
        bus.failure = lambda request: reply if request[:2] == b"\x06\x04" else None
        with pytest.raises(RuntimeError):
            hw.sample(7)
