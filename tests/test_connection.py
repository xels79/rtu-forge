from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest
from rich.console import Console

from rtuforge.commands import CommandContext, execute_command, set_option
from rtuforge.config import load_config
from rtuforge.connection import (
    ConnectionOverrides,
    effective_connection,
    parse_connection_overrides,
)
from rtuforge.scripts import ScriptStore
from rtuforge.shell import toolbar_text
from rtuforge.transport import SerialTransport


def config_copy(tmp_path: Path):
    path = tmp_path / "config.ini"
    path.write_text(Path("config.ini").read_text(encoding="utf-8"), encoding="utf-8")
    config = load_config(path)
    config["ui"]["language"] = "en"
    return path, config


def test_effective_connection_without_overrides_matches_config(tmp_path):
    _, config = config_copy(tmp_path)
    settings = effective_connection(config)
    assert settings.port == config["connection"]["port"]
    assert settings.baudrate == config["connection"].getint("baudrate")


def test_one_or_multiple_connection_overrides_do_not_mutate_config(tmp_path):
    _, config = config_copy(tmp_path)
    saved_port = config["connection"]["port"]
    saved_baudrate = config["connection"]["baudrate"]
    overrides = parse_connection_overrides(
        {"port": "COM7", "baudrate": "19200", "parity": "n"}
    )
    settings = effective_connection(config, overrides)
    assert settings.port == "COM7"
    assert settings.baudrate == 19200
    assert settings.parity == "N"
    assert config["connection"]["port"] == saved_port
    assert config["connection"]["baudrate"] == saved_baudrate


@pytest.mark.parametrize(
    ("name", "value"),
    [
        ("port", ""), ("baudrate", "0"), ("bytesize", "9"),
        ("parity", "X"), ("stopbits", "3"), ("timeout_ms", "0"),
    ],
)
def test_invalid_connection_overrides(name, value):
    with pytest.raises(ValueError, match=name):
        parse_connection_overrides({name: value})


def test_transport_connect_and_endpoint_use_effective_settings(tmp_path):
    _, config = config_copy(tmp_path)
    overrides = ConnectionOverrides(port="COM7", baudrate=19200, parity="N")
    transport = SerialTransport(config, overrides)
    with patch("serial.Serial") as serial_class:
        serial_class.return_value.is_open = True
        transport.connect()
    kwargs = serial_class.call_args.kwargs
    assert kwargs["port"] == "COM7"
    assert kwargs["baudrate"] == 19200
    assert kwargs["parity"] == "N"
    assert transport.endpoint == "COM7 @ 19200 8N1"


def test_status_effective_but_options_connection_persistent(tmp_path):
    path, config = config_copy(tmp_path)
    transport = SerialTransport(config, ConnectionOverrides(port="COM7", baudrate=19200))
    console = Console(record=True, width=120)
    ctx = CommandContext(path, config, ScriptStore(tmp_path / "scripts.ini"), transport, console)
    execute_command(ctx, "status")
    status = console.export_text(clear=False)
    assert "COM7 [CLI]" in status
    assert "19200 [CLI]" in status

    ctx.console = Console(record=True, width=160)
    execute_command(ctx, "options connection")
    options = ctx.console.export_text(clear=False)
    assert config["connection"]["port"] in options
    assert "COM7" not in options
    assert "COM7 @ 19200" in toolbar_text(ctx)


def test_persistent_set_does_not_capture_cli_overrides(tmp_path):
    path, config = config_copy(tmp_path)
    saved_port = config["connection"]["port"]
    saved_baudrate = config["connection"]["baudrate"]
    transport = SerialTransport(
        config, ConnectionOverrides(port="COM7", baudrate=19200)
    )
    ctx = CommandContext(
        path, config, ScriptStore(tmp_path / "scripts.ini"), transport, Console(record=True)
    )

    set_option(ctx, "language", "ru")
    reloaded = load_config(path)
    assert reloaded["connection"]["port"] == saved_port
    assert reloaded["connection"]["baudrate"] == saved_baudrate

    set_option(ctx, "port", "COM8")
    assert load_config(path)["connection"]["port"] == "COM8"
    assert transport.settings.port == "COM7"
    assert SerialTransport(load_config(path)).settings.port == "COM8"


class FakeSerial:
    def __init__(self):
        self.is_open = True
        self.in_waiting = 0
        self.writes: list[bytes] = []

    def reset_input_buffer(self):
        return None

    def write(self, payload):
        self.writes.append(payload)

    def flush(self):
        return None

    def close(self):
        self.is_open = False


@pytest.mark.parametrize(
    "command",
    ["connect", "send 01 03 00 00 00 01", "scan 1 --timeout 1"],
)
def test_connect_send_and_scan_open_the_same_effective_cli_port(tmp_path, command):
    path, config = config_copy(tmp_path)
    config["runtime"]["auto_connect"] = "true"
    transport = SerialTransport(
        config,
        ConnectionOverrides(port="COM7", baudrate=19200, timeout_ms=1),
    )
    ctx = CommandContext(
        path,
        config,
        ScriptStore(tmp_path / "scripts.ini"),
        transport,
        Console(record=True),
        one_shot=True,
    )
    fake_serial = FakeSerial()
    with patch("serial.Serial", return_value=fake_serial) as serial_class:
        execute_command(ctx, command)
    assert serial_class.call_args.kwargs["port"] == "COM7"
    assert serial_class.call_args.kwargs["baudrate"] == 19200


def test_connection_timeout_override_does_not_replace_scan_probe_timeout(tmp_path):
    path, config = config_copy(tmp_path)
    config["runtime"]["auto_connect"] = "true"
    transport = SerialTransport(config, ConnectionOverrides(timeout_ms=1000))
    ctx = CommandContext(
        path,
        config,
        ScriptStore(tmp_path / "scripts.ini"),
        transport,
        Console(record=True),
        one_shot=True,
    )
    fake_serial = FakeSerial()
    with patch("serial.Serial", return_value=fake_serial):
        execute_command(ctx, "scan 1 --timeout 1")
    assert transport.settings.timeout_ms == 1000
    assert config["runtime"]["scan_timeout_ms"] == "100"
