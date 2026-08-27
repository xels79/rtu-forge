from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest
from rich.console import Console

from rtuforge.commands import CommandContext, _print_exchange, execute_command
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
    assert ("CONNECTED" if connected else "DISCONNECTED") in text
    assert "com4" in text
    assert "9600" in text
    assert "8E1" in text
    assert "500 ms" in text
    assert "auto" in text
    command_context.transport.connect.assert_not_called()


@pytest.mark.parametrize(
    ("command", "expected"),
    [
        ("help", "Commands:"),
        ("help send", "send <hex bytes...>"),
        ("help run", "run script <name>"),
        ("help status", "Show the real connection state"),
        ("help nonexistent", "Unknown help topic: nonexistent"),
    ],
)
def test_contextual_help(command_context, command, expected):
    execute_command(command_context, command)
    assert expected in output(command_context)
    command_context.transport.connect.assert_not_called()


def test_decode_rx_can_be_enabled_or_disabled(command_context):
    rx = append_crc(bytes.fromhex("01 03 02 00 05"))
    _print_exchange(command_context, b"\x01", rx, 12.4)
    assert "Registers:" in output(command_context)

    command_context.console = Console(record=True, width=120)
    command_context.config["runtime"]["decode_rx"] = "false"
    _print_exchange(command_context, b"\x01", rx, 12.4)
    assert "RX 01 03 02 00 05" in output(command_context)
    assert "Registers:" not in output(command_context)
