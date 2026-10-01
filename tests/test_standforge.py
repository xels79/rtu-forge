from pathlib import Path

import configparser
import pytest
from rich.console import Console

from rtuforge.connection import ConnectionSettings
from rtuforge.crc import append_crc
from rtuforge.stand_cli import StandContext, execute_command
from rtuforge.stand_completion import completion_candidates
from rtuforge.stand_config import StandSettings, load_stand_settings, save_stand_settings, with_overrides
from rtuforge.stand_protocol import OUTPUT_RANGES, build_output_request, build_tank_request, raw_for_percent, resolve_output_channel, validate_write_response
from rtuforge.transport import Exchange


def test_tank_requests_use_two_adjacent_relays():
    assert build_tank_request(1, 1, "empty") == bytes.fromhex("01 0F 00 00 00 02 01 00")
    assert build_tank_request(1, 1, "middle") == bytes.fromhex("01 0F 00 00 00 02 01 01")
    assert build_tank_request(1, 1, "full") == bytes.fromhex("01 0F 00 00 00 02 01 03")
    assert build_tank_request(1, 4, "full") == bytes.fromhex("01 0F 00 06 00 02 01 03")


def test_output_channels_and_ranges():
    assert resolve_output_channel("temperature") == (0, "temperature")
    assert resolve_output_channel("pressure_high") == (3, "pressure-high")
    request, raw, name, percent = build_output_request(2, "humidity", "50", OUTPUT_RANGES["0-20ma"])
    assert request == bytes.fromhex("02 06 00 01 27 10")
    assert (raw, name, percent) == (10_000, "humidity", 50.0)
    assert raw_for_percent(0, OUTPUT_RANGES["4-20ma"]) == 4_000
    assert raw_for_percent(100, OUTPUT_RANGES["4-20ma"]) == 20_000
    assert raw_for_percent(50, OUTPUT_RANGES["0-10v"]) == 5_000


def test_percent_validation():
    with pytest.raises(ValueError):
        build_output_request(2, "temperature", -1, OUTPUT_RANGES["0-20ma"])
    with pytest.raises(ValueError):
        build_output_request(2, "temperature", 101, OUTPUT_RANGES["0-20ma"])


def test_write_response_validation():
    fc06 = bytes.fromhex("02 06 00 01 27 10")
    validate_write_response(fc06, append_crc(fc06))
    fc0f = bytes.fromhex("01 0F 00 02 00 02 01 01")
    validate_write_response(fc0f, append_crc(bytes.fromhex("01 0F 00 02 00 02")))
    with pytest.raises(RuntimeError, match="No Modbus response"):
        validate_write_response(fc06, b"")


def test_stand_config_roundtrip_and_overrides(tmp_path: Path):
    path = tmp_path / "stand.ini"
    assert load_stand_settings(path) == StandSettings()
    expected = StandSettings(relay_address=7, output_address=8, output_range="4-20ma")
    save_stand_settings(path, expected)
    assert load_stand_settings(path) == expected
    changed = with_overrides(expected, relay_address=5, output_range="0-10v")
    assert changed.relay_address == 5
    assert changed.output_range == "0-10v"


def test_completion():
    assert "tank" in completion_candidates("t")
    assert completion_candidates("tank 1 ") == ["empty", "full", "middle"]
    assert "pressure-high" in completion_candidates("output pressure-")
    assert completion_candidates("set output-range 4") == ["4-20ma"]


class FakeTransport:
    def __init__(self):
        self.connected = False
        self.requests = []
        self.settings = ConnectionSettings("COM7", 9600, 8, "N", 1.0, 100)

    @property
    def endpoint(self):
        return self.settings.endpoint

    def connect(self):
        self.connected = True

    def disconnect(self):
        self.connected = False

    def exchange(self, request, *, crc_mode_override=None, timeout_ms=None):
        self.requests.append((request, crc_mode_override))
        response = append_crc(request if request[1] == 0x06 else request[:6])
        return Exchange(append_crc(request), response, 1.0)


def make_ctx(tmp_path: Path):
    config = configparser.ConfigParser()
    config["connection"] = {"port":"COM7","baudrate":"9600","bytesize":"8","parity":"N","stopbits":"1","timeout_ms":"100"}
    config["runtime"] = {"auto_connect":"true","show_tx":"false","show_rx":"false","timestamps":"false","uppercase_hex":"true","clean_output":"false"}
    config["ui"] = {"language":"ru"}
    transport = FakeTransport()
    ctx = StandContext(tmp_path/"config.ini", tmp_path/"stand.ini", tmp_path, config, StandSettings(), transport, Console(record=True), True)
    return ctx, transport


def test_tank_command(tmp_path):
    ctx, transport = make_ctx(tmp_path)
    execute_command(ctx, "tank 2 middle")
    assert transport.requests == [(bytes.fromhex("01 0F 00 02 00 02 01 01"), "append")]


def test_output_commands(tmp_path):
    ctx, transport = make_ctx(tmp_path)
    execute_command(ctx, "output pressure-high 75")
    assert transport.requests[-1] == (bytes.fromhex("02 06 00 03 3A 98"), "append")
    execute_command(ctx, "output pressure low 25")
    assert transport.requests[-1] == (bytes.fromhex("02 06 00 02 13 88"), "append")


def test_set_output_range_persists(tmp_path):
    ctx, _ = make_ctx(tmp_path)
    execute_command(ctx, "set output-range 4-20ma")
    assert ctx.settings.output_range == "4-20ma"
    assert "4-20ma" in (tmp_path/"stand.ini").read_text(encoding="utf-8")
