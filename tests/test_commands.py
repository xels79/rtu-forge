from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest
from rich.console import Console

from rtuforge.commands import CommandContext, _parse_send_arguments, _print_exchange, execute_command
from rtuforge.config import load_config
from rtuforge.crc import append_crc
from rtuforge.scripts import ScriptStore


class FakeTransport:
    def __init__(self, config, connected: bool = False):
        self.config = config
        self.connected = connected
        self.connect = Mock(side_effect=self._connect)
        self.disconnect = Mock(side_effect=self._disconnect)

    @property
    def endpoint(self) -> str:
        c = self.config["connection"]
        return f"{c.get('port')} @ {c.get('baudrate')} {c.get('bytesize')}{c.get('parity')}{c.get('stopbits')}"

    def _connect(self) -> None:
        self.connected = True

    def _disconnect(self) -> None:
        self.connected = False


@pytest.fixture
def command_context(tmp_path: Path):
    config = load_config(Path("config.ini"))
    config["ui"]["language"] = "en"
    console = Console(record=True, width=120)
    transport = FakeTransport(config)
    return CommandContext(tmp_path / "config.ini", config, ScriptStore(tmp_path / "scripts.ini"), transport, console)


def output(ctx: CommandContext) -> str:
    return ctx.console.export_text(clear=False)


def test_ports_lists_multiple_ports_without_connect(command_context):
    ports = [
        SimpleNamespace(device="COM4", description="USB-SERIAL CH340", hwid="USB VID:PID=1A86:7523"),
        SimpleNamespace(device="COM7", description="USB Serial Port", hwid="USB VID:PID=0403:6001"),
    ]
    with patch("serial.tools.list_ports.comports", return_value=ports):
        execute_command(command_context, "ports")
    text = output(command_context)
    assert "COM4" in text and "COM7" in text and "HWID" in text
    command_context.transport.connect.assert_not_called()


def test_ports_reports_empty_without_connect(command_context):
    with patch("serial.tools.list_ports.comports", return_value=[]):
        execute_command(command_context, "ports")
    assert "No serial ports found." in output(command_context)
    command_context.transport.connect.assert_not_called()


@pytest.mark.parametrize("connected", [False, True])
def test_status_reports_real_state_and_settings_without_connect(command_context, connected):
    command_context.transport.connected = connected
    execute_command(command_context, "status")
    text = output(command_context)
    connection = command_context.config["connection"]
    assert ("CONNECTED" if connected else "DISCONNECTED") in text
    assert connection.get("port") in text
    assert connection.get("baudrate") in text
    assert f"{connection.get('bytesize')}{connection.get('parity')}{connection.get('stopbits')}" in text
    assert f"{connection.get('timeout_ms')} ms" in text
    assert command_context.config["runtime"].get("crc_mode") in text
    assert "Decode RX:" in text
    assert "Clean output:" in text
    assert "Language:" in text
    command_context.transport.connect.assert_not_called()


@pytest.mark.parametrize(
    ("command", "expected"),
    [
        ("help", "record script <name>"),
        ("help send", "send [-d|--decode|-r|--raw]"),
        ("help run", "run script <name> [-d|--decode|-r|--raw]"),
        ("help scripts", "record start [all|rx]"),
        ("help show", "show record"),
        ("help record", "record script <name> <all|rx>"),
        ("help status", "Show real connection state"),
        ("help scan", "valid IDs are 1..247"),
        ("help nonexistent", "Unknown help topic: nonexistent"),
    ],
)
def test_contextual_help(command_context, command, expected):
    execute_command(command_context, command)
    assert expected in output(command_context)
    command_context.transport.connect.assert_not_called()


def test_help_preserves_literal_placeholders(command_context):
    execute_command(command_context, "help")
    text = output(command_context)
    assert "options [section]" in text
    assert "help [command]" in text


def test_russian_help(command_context):
    command_context.config["ui"]["language"] = "ru"
    execute_command(command_context, "help scripts")
    text = output(command_context)
    assert "Создание:" in text
    assert "Запрещены внутри скриптов" in text
    assert "show record" in text
    assert "record script <name>" in text


def test_russian_scan_help(command_context):
    command_context.config["ui"]["language"] = "ru"
    execute_command(command_context, "help scan")
    text = output(command_context)
    assert "Допустимый диапазон slave ID: 1..247" in text
    assert "exception response" in text
    assert "--timeout" in text


def test_russian_record_help_is_detailed(command_context):
    command_context.config["ui"]["language"] = "ru"
    execute_command(command_context, "help record")
    text = output(command_context)
    assert "Запись скрипта одной командой" in text
    assert "-c, --clean" in text
    assert "-r, --raw" in text
    assert "show record" in text


def test_russian_options_table(command_context):
    command_context.config["ui"]["language"] = "ru"
    execute_command(command_context, "options")
    text = output(command_context)
    assert "Параметры RTU Forge" in text
    assert "Раздел" in text
    assert "Параметр" in text
    assert "Значение" in text
    assert "Описание" in text
    assert "Пауза между командами скрипта" in text
    assert "Язык справки и интерфейса" in text


def test_send_decode_argument_parser():
    payload, override = _parse_send_arguments(["--decode", "01", "03", "00", "65", "00", "01"])
    assert payload == "01 03 00 65 00 01"
    assert override is True

    payload, override = _parse_send_arguments(["01", "03", "00", "65", "00", "01", "--raw"])
    assert payload == "01 03 00 65 00 01"
    assert override is False

    with pytest.raises(ValueError):
        _parse_send_arguments(["--decode", "--raw", "01"])


def test_decode_rx_can_be_enabled_or_disabled(command_context):
    rx = append_crc(bytes.fromhex("01 03 02 00 05"))
    _print_exchange(command_context, b"\x01", rx, 12.4)
    assert "Registers:" in output(command_context)

    command_context.console = Console(record=True, width=120)
    command_context.config["runtime"]["decode_rx"] = "false"
    _print_exchange(command_context, b"\x01", rx, 12.4)
    assert "RX 01 03 02 00 05" in output(command_context)
    assert "Registers:" not in output(command_context)


def test_decode_override_beats_config(command_context):
    rx = append_crc(bytes.fromhex("01 03 02 00 05"))
    command_context.config["runtime"]["decode_rx"] = "false"
    _print_exchange(command_context, b"\x01", rx, 12.4, decode_override=True)
    assert "Registers:" in output(command_context)

    command_context.console = Console(record=True, width=120)
    command_context.config["runtime"]["decode_rx"] = "true"
    _print_exchange(command_context, b"\x01", rx, 12.4, decode_override=False)
    assert "Registers:" not in output(command_context)


def test_history_is_rejected_inside_scripts(command_context):
    with pytest.raises(ValueError, match="history is not allowed"):
        execute_command(command_context, "history clear", from_script=True)
