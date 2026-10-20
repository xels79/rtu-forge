"""Manual FWD/Pb00 configuration uses a fake bus and never starts a motor."""
from dataclasses import replace
from threading import RLock

import pytest

from rtuforge.crc import append_crc
from rtuforge.irrigation import State, StopRequested
from rtuforge.irrigation_service import IrrigationService
from rtuforge.stand_cli import execute_command
from rtuforge.stand_completion import completion_candidates
from test_irrigation_modbus import cli_rig, rig


@pytest.fixture(autouse=True)
def forbid_real_serial(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("Manual configure tests must never access hardware")
    monkeypatch.setattr("serial.Serial", forbidden)


@pytest.mark.parametrize("drive", [7, 8])
def test_manual_configure_keeps_pb00_and_enables_terminal_start_and_panel_stop(tmp_path, drive):
    ctx, _, bus = cli_rig(tmp_path)
    bus.registers[drive][0x64] = 210
    bus.registers[drive][0x67] = 0
    original = "[private]\nvalue=keep\n"
    ctx.stand_config_path.write_text(original, encoding="utf-8")
    settings = ctx.irrigation_settings
    other_drive = dict(bus.registers[15 - drive])

    execute_command(ctx, f"idd {drive} configure manual --confirm")

    assert bus.registers[drive][0x65] == 0  # frequency from Pb00
    assert bus.registers[drive][0x66] == 1  # terminal start
    assert bus.registers[drive][0x67] == 1  # panel STOP enabled
    assert bus.registers[drive][0x13B] == 6
    assert bus.registers[drive][0x13C] == 7
    assert bus.registers[drive][0x64] == 210
    assert (bus.registers[drive][0x69], bus.registers[drive][0x6A]) == (450, 200)
    assert bus.registers[15 - drive] == other_drive
    assert not any(bus.coils) and ctx.irrigation is None
    assert ctx.irrigation_settings == settings
    assert ctx.stand_config_path.read_text(encoding="utf-8") == original
    assert all(r[1] in (1, 3, 6) for r in bus.events)
    writes = [r for r in bus.events if r[1] == 6]
    assert {int.from_bytes(r[2:4], "big") for r in writes} == {0x65, 0x66, 0x67, 0x13B, 0x13C}
    output = ctx.console.export_text()
    assert "Pb01=0" in output and "Pb03=1" in output and "Pb00" in output


@pytest.mark.parametrize("blocker", ["running", "frequency", "fault", "fwd", "unknown", "communication"])
def test_manual_configure_blocks_unsafe_or_unknown_state_without_writing(blocker):
    bus, _, hw, _, _ = rig()
    if blocker == "running":
        bus.registers[7][0x5000] = 1
    elif blocker == "frequency":
        bus.registers[7][2] = 2
    elif blocker == "fault":
        bus.registers[7][0x5001] = 1
    elif blocker == "fwd":
        bus.coils[31] = True
    elif blocker == "unknown":
        hw.settings = replace(hw.settings, vfd_verified=False)
    else:
        bus.failure = lambda request: b""
    with pytest.raises(RuntimeError):
        hw.configure(7, manual=True)
    assert not any(r[1] in (6, 15) for r in bus.events)


@pytest.mark.parametrize("failure", ["write", "readback"])
def test_manual_configure_stops_after_failed_stop_button_setting(failure):
    bus, _, hw, _, _ = rig()
    bus.registers[7][0x67] = 0

    def fail(request):
        if int.from_bytes(request[2:4], "big") == 0x67:
            if failure == "write" and request[1] == 6:
                return b""
            if failure == "readback" and request[1] == 3:
                return append_crc(bytes.fromhex("07 03 02 00 00"))
        return None

    bus.failure = fail
    with pytest.raises(RuntimeError):
        hw.configure(7, manual=True)
    # STOP availability is established before changing the frequency/start source.
    assert [int.from_bytes(r[2:4], "big") for r in bus.events if r[1] == 6] == [0x67]


@pytest.mark.parametrize("command", [
    "idd 7 configure manual", "idd 7 configure manual --confirm extra",
    "idd 7 configure invalid --confirm", "idd 7 configure --confirm manual",
    "idd all configure manual --confirm",
])
def test_invalid_manual_configure_syntax_never_connects(tmp_path, command):
    ctx, transport, bus = cli_rig(tmp_path)
    with pytest.raises(ValueError):
        execute_command(ctx, command)
    assert not transport.connected and not bus.events


@pytest.mark.parametrize("state", [State.RUNNING, State.STOPPING, State.FAULT])
def test_manual_configure_conflicts_with_irrigation_before_io(tmp_path, state):
    ctx, transport, bus = cli_rig(tmp_path)
    _, cfg, hw, _, _ = rig()
    ctx.irrigation = IrrigationService(hw, cfg, RLock(), lambda text: None)
    ctx.irrigation.controller.state = state
    with pytest.raises(RuntimeError, match="конфликт"):
        execute_command(ctx, "idd 7 configure manual --confirm")
    assert not transport.connected and not bus.events


def test_automatic_configure_still_restores_rs485_fwd_after_manual_mode():
    bus, _, hw, _, _ = rig()
    hw.configure(7, manual=True)
    bus.events.clear()
    hw.configure(7)
    assert bus.registers[7][0x65] == 5 and bus.registers[7][0x66] == 1
    assert [int.from_bytes(r[2:4], "big") for r in bus.events if r[1] == 6] == [0x65, 0x66, 0x13B, 0x13C]
    assert not any(bus.coils)


def test_cancelled_manual_configure_never_writes():
    bus, _, hw, _, _ = rig()
    hw.cancelled = lambda: True
    with pytest.raises(StopRequested):
        hw.configure(7, manual=True)
    assert all(r[1] in (1, 3) for r in bus.events)


@pytest.mark.parametrize("command", ["idd 7 setup", "idd 7 frequency 21", "start check 1 1 broth 21"])
def test_manual_mode_does_not_silently_restore_rs485_for_irrigation(tmp_path, command):
    ctx, _, bus = cli_rig(tmp_path)
    execute_command(ctx, "idd 7 configure manual --confirm")
    bus.events.clear()
    with pytest.raises(RuntimeError):
        execute_command(ctx, command)
    assert bus.registers[7][0x65] == 0
    assert all(r[1] in (1, 3, 4) for r in bus.events)
    assert not any(bus.coils)


def test_manual_configure_oneshot_uses_same_handler(tmp_path, monkeypatch):
    from rtuforge import stand_cli
    ctx, transport, bus = cli_rig(tmp_path)
    ctx.config_path.write_text("", encoding="utf-8")
    monkeypatch.setattr(stand_cli, "load_config", lambda path: ctx.config)
    monkeypatch.setattr(stand_cli, "load_irrigation_settings", lambda path: ctx.irrigation_settings)
    monkeypatch.setattr(stand_cli, "SerialTransport", lambda *args: transport)
    monkeypatch.setattr("sys.argv", ["standforge", "--home", str(tmp_path), "idd", "8", "configure", "manual", "--confirm"])
    assert stand_cli.main() == 0
    assert bus.registers[8][0x65] == 0 and bus.registers[8][0x67] == 1
    assert not any(bus.coils) and not transport.connected


def test_manual_configure_completion_and_help_are_available_without_connection(tmp_path):
    assert completion_candidates("idd 7 configure ") == ["--confirm", "manual"]
    assert completion_candidates("idd 8 configure manual ") == ["--confirm"]
    ctx, transport, bus = cli_rig(tmp_path)
    execute_command(ctx, "help idd")
    assert "configure manual --confirm" in ctx.console.export_text()
    assert not transport.connected and not bus.events
