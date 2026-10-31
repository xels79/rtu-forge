from __future__ import annotations

import configparser
import io
import sys
import threading
from datetime import datetime, timedelta
from pathlib import Path

import pytest
from prompt_toolkit.input import DummyInput
from prompt_toolkit.buffer import Buffer
from prompt_toolkit.history import FileHistory
from prompt_toolkit.output import DummyOutput
from rich.console import Console

from rtuforge import aircon_cli, cli
from rtuforge.aircon_cli import Poller, execute_command, make_context, run_aircon
from rtuforge.aircon_config import AirconSettings, changed_setting, load_aircon_settings, save_aircon_settings
from rtuforge.aircon_diag import collect_diagnostics, run_diagnostics
from rtuforge.aircon_modbus import (
    AirconModbusClient,
    DemoTransport,
    ModbusCrcError,
    ModbusError,
    ModbusTimeout,
    parse_bits,
    parse_registers,
    read_request,
    validate_write_response,
    write_coil_request,
    write_register_request,
)
from rtuforge.aircon_render import HELP_LINES, humidity_text, render_status_lines
from rtuforge.aircon_state import AirconState
from rtuforge.aircon_tui import CommandQueue, build_tui, remember_command
from rtuforge.connection import ConnectionOverrides
from rtuforge.crc import append_crc


def base_config() -> configparser.ConfigParser:
    config = configparser.ConfigParser()
    config["connection"] = {
        "port": "COM7", "baudrate": "19200", "bytesize": "8", "parity": "E",
        "stopbits": "1", "timeout_ms": "500",
    }
    config["runtime"] = {
        "crc_mode": "auto", "response_silence_ms": "5", "max_response_bytes": "256",
        "post_write_delay_ms": "0",
    }
    config["ui"] = {"language": "ru"}
    return config


def demo_context(tmp_path: Path, settings: AirconSettings | None = None):
    path = tmp_path / "aircon.ini"
    if settings is not None:
        save_aircon_settings(path, settings)
    ctx = make_context(tmp_path, base_config(), ConnectionOverrides(), settings_path=path, demo=True)
    ctx.client.connect()
    return ctx


def test_official_pdu_addresses_are_used_directly():
    assert read_request(1, 1, 20) == bytes.fromhex("01 01 00 14 00 01")
    assert read_request(1, 3, 5) == bytes.fromhex("01 03 00 05 00 01")
    assert write_coil_request(1, 1, True) == bytes.fromhex("01 05 00 01 FF 00")
    assert write_register_request(1, 7, 3) == bytes.fromhex("01 06 00 07 00 03")


def test_strict_response_parsing_and_crc_errors():
    assert parse_bits(append_crc(bytes.fromhex("01 01 01 01")), 1, 1) == [True]
    response = append_crc(bytes.fromhex("01 03 04 0A 00 FF FF"))
    assert parse_registers(response, 1, 3, 2) == [2560, 65535]
    with pytest.raises(ModbusCrcError):
        parse_registers(response[:-1] + b"\x00", 1, 3, 2)
    with pytest.raises(ModbusTimeout):
        parse_bits(b"", 1, 1)
    with pytest.raises(ModbusError, match="исключение Modbus 02"):
        parse_registers(append_crc(bytes.fromhex("01 83 02")), 1, 3, 1)


def test_write_response_must_echo_exact_request():
    request = write_register_request(1, 5, 2300)
    validate_write_response(request, append_crc(request))
    with pytest.raises(ModbusError, match="не подтверждает"):
        validate_write_response(request, append_crc(write_register_request(1, 5, 2400)))


def test_demo_refresh_reads_power_temperature_mode_and_no_writes(tmp_path: Path):
    ctx = demo_context(tmp_path)
    ctx.refresh()
    assert ctx.state.gateway_online and ctx.state.aircon_online and ctx.state.fresh
    assert ctx.state.power is True
    assert ctx.state.mode == 2
    assert ctx.state.active_mode == 2
    assert ctx.state.room_temperature_c == 25.60
    assert ctx.state.target_temperature_c == 23.0
    assert ctx.state.thermostat == 2
    assert ctx.state.fan == 0
    assert all(request[1] in {1, 3, 4} for request in ctx.transport.requests)


@pytest.mark.parametrize("value", ["15", "16.5", "31", "bad"])
def test_temperature_command_rejects_invalid_value_before_write(tmp_path: Path, value: str):
    ctx = demo_context(tmp_path)
    with pytest.raises(ValueError, match=r"16\.\.30"):
        execute_command(ctx, f"temp {value}")
    assert ctx.transport.requests == []


def test_control_commands_write_once_then_confirm_by_readback(tmp_path: Path):
    ctx = demo_context(tmp_path)
    execute_command(ctx, "temp 24")
    writes = [request for request in ctx.transport.requests if request[1] in {5, 6}]
    assert writes == [bytes.fromhex("01 06 00 05 09 60")]
    assert ctx.state.target_temperature_c == 24.0
    ctx.transport.requests.clear()
    execute_command(ctx, "mode dry")
    assert [request for request in ctx.transport.requests if request[1] in {5, 6}] == [
        bytes.fromhex("01 06 00 01 00 04")
    ]
    assert ctx.state.mode == 4
    assert ctx.state.active_mode == 4
    ctx.transport.requests.clear()
    execute_command(ctx, "fan 3")
    assert [request for request in ctx.transport.requests if request[1] in {5, 6}] == [
        bytes.fromhex("01 06 00 07 00 03")
    ]


def test_fifo_queue_preserves_control_command_order(tmp_path: Path):
    ctx = demo_context(tmp_path)
    errors: list[Exception] = []
    commands = CommandQueue(lambda line: execute_command(ctx, line), errors.append)
    commands.start()
    for line in ("off", "on", "temp 24", "mode dry", "fan 3"):
        commands.submit(line)
    commands.wait_idle()
    commands.stop()

    assert errors == []
    assert [request for request in ctx.transport.requests if request[1] in {5, 6}] == [
        bytes.fromhex("01 05 00 01 00 00"),
        bytes.fromhex("01 05 00 01 FF 00"),
        bytes.fromhex("01 06 00 05 09 60"),
        bytes.fromhex("01 06 00 01 00 04"),
        bytes.fromhex("01 06 00 07 00 03"),
    ]


def test_on_off_use_only_documented_coil_one(tmp_path: Path):
    ctx = demo_context(tmp_path)
    execute_command(ctx, "off")
    assert ctx.transport.requests[0] == bytes.fromhex("01 05 00 01 00 00")
    assert ctx.state.power is False
    assert ctx.state.active_mode == 0
    ctx.transport.requests.clear()
    execute_command(ctx, "on")
    assert ctx.transport.requests[0] == bytes.fromhex("01 05 00 01 FF 00")
    assert ctx.state.power is True


def test_gateway_and_aircon_link_are_distinct(tmp_path: Path):
    ctx = demo_context(tmp_path)
    ctx.transport.coils[20] = False
    ctx.refresh()
    assert ctx.state.gateway_online is True
    assert ctx.state.aircon_online is False
    assert ctx.state.fresh is False
    assert ctx.state.room_temperature_c is None


def test_read_only_diagnostics_continue_after_coil_twenty_is_zero(tmp_path: Path):
    ctx = demo_context(tmp_path)
    ctx.transport.coils[20] = False
    results = collect_diagnostics(ctx.client)

    assert [request.hex(" ").upper() for request in ctx.transport.requests] == [
        "01 01 00 14 00 01",
        "01 01 00 01 00 01",
        "01 03 00 01 00 03",
        "01 03 00 05 00 03",
    ]
    assert all(request[1] in {1, 3} for request in ctx.transport.requests)
    assert all(result.error is None for result in results)
    assert results[0].decoded == "Coil 20 = 0 — кондиционер НЕТ СВЯЗИ"
    assert "Holding 1=2" in (results[2].decoded or "")
    assert "23.00 °C" in (results[3].decoded or "")


def test_diagnostics_show_modbus_exception_and_write_log(tmp_path: Path):
    ctx = demo_context(tmp_path)
    ctx.demo = False
    original_exchange = ctx.transport.exchange

    def exception_on_operation(request, **kwargs):
        if request[1] == 3 and request[2:4] == bytes.fromhex("00 01"):
            from rtuforge.transport import Exchange
            response = append_crc(bytes.fromhex("01 83 02"))
            return Exchange(append_crc(request), response, 2.5)
        return original_exchange(request, **kwargs)

    ctx.transport.exchange = exception_on_operation
    stream = io.StringIO()
    console = Console(file=stream, force_terminal=False, highlight=False)
    assert not run_diagnostics(ctx.client, console, log_event=ctx.log_event)
    output = stream.getvalue()
    assert "RX: 01 83 02 C0 F1" in output
    assert "исключение Modbus 02" in output
    log = (tmp_path / "aircon.log").read_text(encoding="utf-8")
    assert "TX=01 03 00 01 00 03 54 0B" in log
    assert "RX=01 83 02 C0 F1" in log


def test_gateway_stays_online_when_a_later_state_read_times_out(tmp_path: Path):
    ctx = demo_context(tmp_path)
    original = ctx.transport.exchange
    calls = [0]

    def timeout_after_link(request, **kwargs):
        calls[0] += 1
        if calls[0] == 2:
            from rtuforge.transport import Exchange
            return Exchange(append_crc(request), b"", 1.0)
        return original(request, **kwargs)

    ctx.transport.exchange = timeout_after_link
    ctx.refresh()
    assert ctx.state.gateway_online is True
    assert ctx.state.aircon_online is True
    assert ctx.state.fresh is False
    assert ctx.state.timeout_count == 1


def test_poll_recovers_after_timeout_without_replaying_writes(tmp_path: Path):
    ctx = demo_context(tmp_path)
    original = ctx.transport.exchange
    failures = [True]

    def flaky(request, **kwargs):
        if failures:
            failures.pop()
            from rtuforge.transport import Exchange
            return Exchange(append_crc(request), b"", 1.0)
        return original(request, **kwargs)

    ctx.transport.exchange = flaky
    ctx.refresh()
    assert not ctx.state.gateway_online
    assert ctx.state.timeout_count == 1
    ctx.refresh()
    assert ctx.state.gateway_online and ctx.state.fresh
    assert all(request[1] in {1, 3, 4} for request in ctx.transport.requests)


def test_bad_crc_counter_and_stale_values_are_cleared(tmp_path: Path):
    ctx = demo_context(tmp_path)
    ctx.refresh()
    original = ctx.transport.exchange

    def bad_crc(request, **kwargs):
        exchange = original(request, **kwargs)
        exchange.rx = exchange.rx[:-2] + b"\x00\x00"
        return exchange

    ctx.transport.exchange = bad_crc
    ctx.refresh()
    assert ctx.state.crc_error_count == 1
    assert ctx.state.room_temperature_c is None
    assert not ctx.state.fresh


def test_humidity_disabled_enabled_and_stale(tmp_path: Path):
    state = AirconState()
    settings = AirconSettings()
    assert humidity_text(state, settings) == "НЕТ ДАТЧИКА"
    settings = AirconSettings(humidity_enabled=True, humidity_scale=0.1)
    ctx = demo_context(tmp_path, settings)
    ctx.refresh()
    assert ctx.state.humidity_percent == 48.5
    assert humidity_text(ctx.state, settings).startswith("48.5 %")
    now = ctx.state.humidity_updated_at + timedelta(milliseconds=settings.humidity_stale_ms + 1)
    assert humidity_text(ctx.state, settings, now=now) == "НЕТ СВЕЖИХ ДАННЫХ"


@pytest.mark.parametrize("raw,expected", [(0, 0.0), (1000, 100.0)])
def test_humidity_accepts_inclusive_zero_to_one_hundred(
    tmp_path: Path, raw: int, expected: float
):
    settings = AirconSettings(humidity_enabled=True, humidity_scale=0.1)
    ctx = demo_context(tmp_path, settings)
    ctx.transport.humidity_raw = raw
    ctx.refresh()
    assert ctx.state.humidity_percent == expected
    assert ctx.state.humidity_error is None


@pytest.mark.parametrize("raw", [0xFFFF, 1001])
def test_humidity_rejects_values_outside_zero_to_one_hundred(
    tmp_path: Path, raw: int
):
    settings = AirconSettings(humidity_enabled=True, humidity_scale=0.1)
    ctx = demo_context(tmp_path, settings)
    ctx.transport.humidity_raw = raw
    ctx.refresh()
    assert ctx.state.gateway_online and ctx.state.fresh
    assert ctx.state.humidity_percent is None
    assert "0..100" in (ctx.state.humidity_error or "")
    assert humidity_text(ctx.state, settings) == "НЕТ СВЕЖИХ ДАННЫХ"


def test_humidity_read_error_hides_previous_value_but_keeps_last_success_time(
    tmp_path: Path
):
    settings = AirconSettings(humidity_enabled=True, humidity_scale=0.1)
    ctx = demo_context(tmp_path, settings)
    ctx.refresh()
    last_value = ctx.state.humidity_percent
    last_update = ctx.state.humidity_updated_at
    original_exchange = ctx.transport.exchange

    def humidity_timeout(request, **kwargs):
        if request[0] == settings.humidity_slave_id:
            from rtuforge.transport import Exchange
            return Exchange(append_crc(request), b"", 1.0)
        return original_exchange(request, **kwargs)

    ctx.transport.exchange = humidity_timeout
    ctx.refresh()
    assert ctx.state.gateway_online and ctx.state.fresh
    assert ctx.state.humidity_percent == last_value
    assert ctx.state.humidity_updated_at == last_update
    assert ctx.state.humidity_error == "нет ответа Modbus"
    assert ctx.state.timeout_count == 1
    assert humidity_text(ctx.state, settings) == "НЕТ СВЕЖИХ ДАННЫХ"


def test_aircon_config_roundtrip_defaults_and_validation(tmp_path: Path):
    path = tmp_path / "aircon.ini"
    defaults = load_aircon_settings(path, fallback_port="COM9")
    assert defaults.port == "COM9"
    assert (defaults.baudrate, defaults.bytesize, defaults.parity, defaults.stopbits) == (9600, 8, "N", 2.0)
    assert not path.exists()
    changed = changed_setting(defaults, "humidity-enabled", "true")
    changed = changed_setting(changed, "humidity_scale", "0,01")
    save_aircon_settings(path, changed)
    assert load_aircon_settings(path) == changed
    with pytest.raises(ValueError, match=r"1\.\.247"):
        changed_setting(changed, "slave_id", "0")
    with pytest.raises(ValueError, match="отдельный Modbus ID"):
        changed_setting(changed, "humidity_slave_id", "1")
    with pytest.raises(ValueError, match="коэффициент"):
        changed_setting(changed, "humidity_scale", "nan")


def test_diagnostic_log_is_appended_outside_demo_mode(tmp_path: Path):
    ctx = demo_context(tmp_path)
    ctx.demo = False
    execute_command(ctx, "status")
    text = (tmp_path / "aircon.log").read_text(encoding="utf-8")
    assert "связь: шлюз=да" in text


def test_set_connection_setting_disconnects_and_does_not_touch_main_config(tmp_path: Path):
    ctx = demo_context(tmp_path)
    original_main = base_config()
    execute_command(ctx, "set port COM8")
    assert not ctx.transport.connected
    assert load_aircon_settings(tmp_path / "aircon.ini").port == "COM8"
    assert original_main["connection"]["port"] == "COM7"


@pytest.mark.parametrize("command", ["disconnect", "set port COM8"])
def test_poll_cycle_does_not_overlap_connection_or_setting_changes(
    tmp_path: Path, command: str
):
    ctx = demo_context(tmp_path)
    entered = threading.Event()
    release = threading.Event()
    action_done = threading.Event()
    original_exchange = ctx.transport.exchange

    def blocked_exchange(request, **kwargs):
        if not entered.is_set():
            entered.set()
            assert release.wait(2)
        return original_exchange(request, **kwargs)

    ctx.transport.exchange = blocked_exchange
    poll = threading.Thread(target=ctx.refresh)
    poll.start()
    assert entered.wait(1)

    def run_action() -> None:
        execute_command(ctx, command)
        action_done.set()

    action = threading.Thread(target=run_action)
    action.start()
    assert not action_done.wait(0.05)
    release.set()
    poll.join(2)
    action.join(2)
    assert not poll.is_alive() and not action.is_alive()
    assert action_done.is_set()
    assert not ctx.transport.connected
    if command.startswith("set"):
        assert load_aircon_settings(tmp_path / "aircon.ini").port == "COM8"


def test_poller_stop_waits_for_inflight_exchange(tmp_path: Path):
    settings = AirconSettings(poll_interval_ms=1)
    ctx = demo_context(tmp_path, settings)
    entered = threading.Event()
    release = threading.Event()
    stopped = threading.Event()
    original_exchange = ctx.transport.exchange

    def blocked_exchange(request, **kwargs):
        if not entered.is_set():
            entered.set()
            assert release.wait(2)
        return original_exchange(request, **kwargs)

    ctx.transport.exchange = blocked_exchange
    poller = Poller(ctx)
    poller.start()
    assert entered.wait(1)

    def stop_poller() -> None:
        poller.stop()
        stopped.set()

    stopper = threading.Thread(target=stop_poller)
    stopper.start()
    assert not stopped.wait(0.05)
    release.set()
    stopper.join(2)
    assert stopped.is_set()
    assert not poller.thread.is_alive()


def test_help_is_russian_and_offline():
    text = "\n".join(HELP_LINES)
    assert "Подключение" in text
    assert "ВЛАЖНОСТЬ" in text
    assert "temp 23" in text


def test_status_renderer_fits_80_by_24_and_has_two_console_rows(tmp_path: Path):
    ctx = demo_context(tmp_path)
    lines = render_status_lines(ctx.state, ctx.settings, width=80, height=22)
    assert len(lines) == 22
    assert all(len(line) == 80 for line in lines)
    app, _, commands = build_tui(ctx, input=DummyInput(), output=DummyOutput())
    root = app.layout.container
    assert len(root.children) == 3
    heights = [child.height if isinstance(child.height, int) else child.height.preferred for child in root.children[-2:]]
    assert heights == [1, 1]
    assert not commands.started


def test_command_history_is_loaded_by_a_new_session(tmp_path: Path):
    path = tmp_path / ".aircon_history"
    first_buffer = Buffer(history=FileHistory(str(path)))
    remember_command(first_buffer, "mode cool")
    assert first_buffer.text == ""

    second_history = FileHistory(str(path))
    assert list(second_history.load_history_strings()) == ["mode cool"]


def test_rtuforge_aircon_demo_snapshot_launches_without_hardware(tmp_path: Path, monkeypatch, capsys):
    (tmp_path / "config.ini").write_bytes(Path("config.ini").read_bytes())
    monkeypatch.setattr(sys, "argv", ["rtuforge", "--home", str(tmp_path), "aircon", "--demo", "--snapshot"])
    assert cli.main() == 0
    output = capsys.readouterr().out
    assert "HISENSE AUC-18HR4SAA1" in output
    assert "НА СВЯЗИ" in output
    assert not (tmp_path / "aircon.ini").exists()


def test_rtuforge_aircon_diag_is_available_as_read_only_command(
    tmp_path: Path, monkeypatch, capsys
):
    (tmp_path / "config.ini").write_bytes(Path("config.ini").read_bytes())
    monkeypatch.setattr(
        sys, "argv", ["rtuforge", "--home", str(tmp_path), "aircon", "--demo", "diag"]
    )
    assert cli.main() == 0
    output = capsys.readouterr().out
    assert "AIRCON DIAG" in output
    assert "TX: 01 01 00 14 00 01 BD CE" in output
    assert "CRC: OK" in output


def test_demo_snapshot_is_safe_when_windows_code_page_lacks_box_drawing(tmp_path: Path):
    raw = io.BytesIO()
    stream = io.TextIOWrapper(raw, encoding="cp1251")
    console = Console(file=stream, force_terminal=False, highlight=False)
    assert run_aircon(
        ["--demo", "--snapshot"], home=tmp_path, base_config=base_config(),
        overrides=ConnectionOverrides(), console=console,
    ) == 0
    stream.flush()
    text = raw.getvalue().decode("cp1251")
    assert "HISENSE AUC-18HR4SAA1" in text
    assert "ПОДКЛЮЧЕНИЕ" in text


def test_run_aircon_closes_transport_when_tui_fails(tmp_path: Path, monkeypatch):
    captured = {}
    original_make_context = aircon_cli.make_context

    def capture_context(*args, **kwargs):
        ctx = original_make_context(*args, **kwargs)
        captured["ctx"] = ctx
        return ctx

    def failed_tui(ctx):
        raise RuntimeError("остановка тестового TUI")

    monkeypatch.setattr(aircon_cli, "make_context", capture_context)
    monkeypatch.setattr("rtuforge.aircon_tui.run_tui", failed_tui)
    assert run_aircon(
        ["--demo"], home=tmp_path, base_config=base_config(),
        overrides=ConnectionOverrides(),
    ) == 1
    assert not captured["ctx"].transport.connected


def test_cli_connection_overrides_win_over_saved_aircon_settings(tmp_path: Path):
    save_aircon_settings(tmp_path / "aircon.ini", AirconSettings(port="COM5", baudrate=9600))
    overrides = ConnectionOverrides(port="COM7", baudrate=19200)
    ctx = make_context(tmp_path, base_config(), overrides, demo=False)
    assert ctx.transport.settings.port == "COM7"
    assert ctx.transport.settings.baudrate == 19200
    assert ctx.settings.port == "COM7"
    assert ctx.persisted_settings.port == "COM5"
