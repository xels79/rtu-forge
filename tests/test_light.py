from pathlib import Path
from types import SimpleNamespace

import pytest
from rich.console import Console

from rtuforge.commands import CommandContext, execute_command
from rtuforge.config import load_config
from rtuforge.crc import append_crc
from rtuforge.light_protocol import (
    build_read, build_write, check_write, display_level, parse_read, percent_to_raw,
)
from rtuforge.scripts import ScriptStore
from rtuforge.transport import Exchange


class FakeAO:
    def __init__(self):
        self.connected = False
        self.settings = SimpleNamespace(port="COM7")
        self.raw = [0, 0, 0, 0]
        self.sent = []
        self.bad_crc = False
        self.bad_echo = False

    def connect(self):
        self.connected = True

    def disconnect(self):
        self.connected = False

    def exchange(self, request, *, crc_mode_override=None):
        self.sent.append((request, crc_mode_override))
        address, function, _, register = request[:4]
        if function == 3:
            raw = self.raw[register]
            response = append_crc(bytes([address, 3, 2, raw >> 8, raw & 255]))
        elif function == 6:
            raw = int.from_bytes(request[4:6], "big")
            self.raw[register] = raw
            response = append_crc(request)
            if self.bad_echo:
                response = append_crc(request[:4] + bytes.fromhex("00 01"))
        else:
            raise AssertionError("unexpected function")
        if self.bad_crc:
            response = response[:-1] + bytes([response[-1] ^ 1])
        return Exchange(request, response, 1.0)


@pytest.fixture
def ctx(tmp_path):
    path = tmp_path / "config.ini"
    path.write_text(Path("config.ini").read_text(encoding="utf-8"), encoding="utf-8")
    config = load_config(path)
    config["runtime"]["auto_connect"] = "true"
    console = Console(record=True, width=120)
    return CommandContext(
        path, config, ScriptStore(tmp_path / "scripts.ini"), FakeAO(),
        console, one_shot=True,
    )


@pytest.mark.parametrize("value,expected", [
    ("0", 0), ("50", 5000), ("100", 10000), ("25.5", 2550), ("0,5", 50),
])
def test_percent(value, expected):
    assert percent_to_raw(value) == expected


@pytest.mark.parametrize("value", ["-1", "100.01", "nan", "inf", "cat", ""])
def test_invalid_percent(value):
    with pytest.raises(ValueError):
        percent_to_raw(value)


def test_frames_and_crc_validation():
    request = build_read(1, 1)
    assert request == bytes.fromhex("01 03 00 00 00 01")
    assert parse_read(request, append_crc(bytes.fromhex("01 03 02 13 88"))) == 5000
    request = build_write(1, 1, 10000)
    assert request == bytes.fromhex("01 06 00 00 27 10")
    check_write(request, append_crc(request))
    with pytest.raises(RuntimeError):
        check_write(request, append_crc(bytes.fromhex("01 06 00 00 00 00")))
    with pytest.raises(RuntimeError):
        parse_read(build_read(1, 1), append_crc(bytes.fromhex("01 03 02 27 11")))


def test_help_and_config_do_not_connect(ctx):
    execute_command(ctx, "help light")
    execute_command(ctx, "light config")
    assert "WAVESHARE AO" in ctx.console.export_text()
    assert ctx.transport.connected is False


def test_single_and_all(ctx):
    execute_command(ctx, "light 1 100")
    assert ctx.transport.raw == [10000, 0, 0, 0]
    assert ctx.transport.sent == [
        (build_write(1, 1, 10000), "append"),
        (build_read(1, 1), "append"),
    ]
    execute_command(ctx, "light all 50")
    assert ctx.transport.raw == [5000] * 4
    execute_command(ctx, "light status")
    assert "50.00% / 5.000 В" in ctx.console.export_text()


def test_save_mapping_and_address(ctx):
    execute_command(ctx, "light set address 7")
    execute_command(ctx, "light set channel 1 3")
    assert ctx.config["light"]["light_address"] == "7"
    assert ctx.config["light"]["light_channel_1"] == "3"
    assert ctx.config["light"]["light_channel_3"] == "1"
    loaded = load_config(ctx.config_path)
    assert loaded["light"]["light_channel_3"] == "1"
    execute_command(ctx, "light 1 50")
    assert ctx.transport.sent[-2][0] == build_write(7, 3, 5000)


def test_reject_bad_reply(ctx):
    ctx.transport.bad_crc = True
    with pytest.raises(RuntimeError, match="CRC"):
        execute_command(ctx, "light status")


def test_reject_bad_echo(ctx):
    ctx.transport.bad_echo = True
    with pytest.raises(RuntimeError, match="эхо"):
        execute_command(ctx, "light 1 100")


def test_prevalidate_all_before_write(ctx):
    with pytest.raises(ValueError):
        execute_command(ctx, "light all 101")
    with pytest.raises(ValueError):
        execute_command(ctx, "light 5 50")
    assert ctx.transport.sent == []


def test_old_config_default_light(tmp_path):
    path = tmp_path / "config.ini"
    original = Path("config.ini").read_text(encoding="utf-8")
    path.write_text(original.split("[light]")[0], encoding="utf-8")
    config = load_config(path)
    assert config["light"]["light_address"] == "1"
    assert [config["light"][f"light_channel_{i}"] for i in range(1,5)] == ["1","2","3","4"]
    assert "[light]" not in path.read_text(encoding="utf-8")
