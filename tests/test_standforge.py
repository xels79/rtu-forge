from pathlib import Path

import configparser
import sys
import pytest
from rich.console import Console

from rtuforge.connection import ConnectionSettings
from rtuforge import stand_cli
from rtuforge.crc import append_crc
from rtuforge.stand_cli import StandContext, execute_command
from rtuforge.stand_completion import completion_candidates
from rtuforge.stand_config import StandSettings, load_stand_settings, save_stand_settings, with_overrides
from rtuforge.stand_protocol import OUTPUT_RANGES, build_all_relays_off_request, build_output_request, build_tank_request, raw_for_percent, resolve_output_channel, validate_write_response
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
    fc05 = bytes.fromhex("01 05 00 FF 00 00")
    validate_write_response(fc05, bytes.fromhex("01 05 00 FF 00 00 FD FA"))
    fc06 = bytes.fromhex("02 06 00 01 27 10")
    validate_write_response(fc06, append_crc(fc06))
    fc0f = bytes.fromhex("01 0F 00 02 00 02 01 01")
    validate_write_response(fc0f, append_crc(bytes.fromhex("01 0F 00 02 00 02")))
    with pytest.raises(RuntimeError, match="No Modbus response"):
        validate_write_response(fc06, b"")


def test_all_relays_off_request_matches_waveshare_vector():
    request = build_all_relays_off_request(1)
    assert request == bytes.fromhex("01 05 00 FF 00 00")
    assert append_crc(request) == bytes.fromhex("01 05 00 FF 00 00 FD FA")


@pytest.mark.parametrize("slave", [0, 248])
def test_all_relays_off_request_rejects_invalid_device_id(slave):
    with pytest.raises(ValueError, match="1\\.\\.247"):
        build_all_relays_off_request(slave)


@pytest.mark.parametrize("payload,message", [
    ("01 05 00 00 00 00", "Unexpected FC05 write response"),
    ("01 05 00 FF FF 00", "Unexpected FC05 write response"),
    ("01 05 00 FF 00", "Unexpected FC05 write response"),
    ("01 05 00 FF 00 00 00", "Unexpected FC05 write response"),
    ("07 05 00 FF 00 00", "Unexpected Modbus address"),
    ("01 06 00 FF 00 00", "Unexpected Modbus function"),
    ("01 85 02", "Modbus exception 02"),
])
def test_all_relays_off_rejects_unexpected_response(payload, message):
    with pytest.raises(RuntimeError, match=message):
        validate_write_response(build_all_relays_off_request(1), append_crc(bytes.fromhex(payload)))


def test_all_relays_off_rejects_bad_crc():
    with pytest.raises(RuntimeError, match="Invalid Modbus CRC"):
        validate_write_response(build_all_relays_off_request(1), bytes.fromhex("01 05 00 FF 00 00 00 00"))


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
    assert "reset" in completion_candidates("res")
    assert completion_candidates("reset ") == ["all"]


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
        response = append_crc(request if request[1] in {0x05, 0x06} else request[:6])
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


@pytest.mark.parametrize("command,enabled", [("on", True), ("off", False), ("of", False), ("ON", True)])
@pytest.mark.parametrize("channel", range(1, 33))
def test_manual_relay_command(tmp_path, command, enabled, channel):
    ctx, transport = make_ctx(tmp_path)
    ctx.settings = StandSettings(relay_address=7)
    execute_command(ctx, f"{command} {channel}")
    assert transport.requests == [
        (bytes([7, 0x0F, 0, channel - 1, 0, 1, 1, int(enabled)]), "append")
    ]
    assert transport.connected


def test_manual_relay_multiple_channels(tmp_path):
    ctx, transport = make_ctx(tmp_path)
    execute_command(ctx, "on 32 1 9 1")
    assert transport.requests == [
        (bytes.fromhex("01 0F 00 1F 00 01 01 01"), "append"),
        (bytes.fromhex("01 0F 00 00 00 01 01 01"), "append"),
        (bytes.fromhex("01 0F 00 08 00 01 01 01"), "append"),
    ]
    execute_command(ctx, "of 9 32")
    assert transport.requests[-2:] == [
        (bytes.fromhex("01 0F 00 08 00 01 01 00"), "append"),
        (bytes.fromhex("01 0F 00 1F 00 01 01 00"), "append"),
    ]


@pytest.mark.parametrize("command", ["on", "off", "of"])
@pytest.mark.parametrize("args", ["", "0", "33", "-1", "one", "1.5", "1 33", "1 bad"])
def test_manual_relay_rejects_invalid_channels_before_connecting(tmp_path, command, args):
    ctx, transport = make_ctx(tmp_path)
    with pytest.raises(ValueError, match="1\\.\\.32"):
        execute_command(ctx, f"{command} {args}")
    assert transport.requests == []
    assert not transport.connected


def test_manual_relay_respects_disabled_auto_connect(tmp_path):
    ctx, transport = make_ctx(tmp_path)
    ctx.config["runtime"]["auto_connect"] = "false"
    with pytest.raises(RuntimeError, match="Use 'connect'"):
        execute_command(ctx, "on 1")
    assert transport.requests == []
    assert not transport.connected


def test_manual_relay_stops_on_invalid_response(tmp_path, monkeypatch):
    ctx, transport = make_ctx(tmp_path)

    def wrong_channel_response(request, **kwargs):
        transport.requests.append((request, kwargs["crc_mode_override"]))
        return Exchange(append_crc(request), append_crc(bytes.fromhex("01 0F 00 07 00 01")), 1.0)

    monkeypatch.setattr(transport, "exchange", wrong_channel_response)
    with pytest.raises(RuntimeError, match="Unexpected FC0F write response"):
        execute_command(ctx, "on 1 3")
    assert len(transport.requests) == 1
    assert "Реле" not in ctx.console.export_text()


@pytest.mark.parametrize("language,expected", [("en", "Relay 1: on"), ("ru", "Реле 1: включено")])
def test_manual_relay_reports_success(tmp_path, language, expected):
    ctx, _ = make_ctx(tmp_path)
    ctx.config["ui"]["language"] = language
    execute_command(ctx, "on 1")
    assert expected in ctx.console.export_text()


def test_manual_relay_clean_output(tmp_path):
    ctx, _ = make_ctx(tmp_path)
    ctx.config["runtime"].update({"clean_output": "true", "show_tx": "true", "show_rx": "true"})
    execute_command(ctx, "of 8")
    assert ctx.console.export_text().splitlines() == [
        append_crc(bytes.fromhex("01 0F 00 07 00 01 01 00")).hex(" ").upper(),
        append_crc(bytes.fromhex("01 0F 00 07 00 01")).hex(" ").upper(),
    ]


@pytest.mark.parametrize("topic", ["", "on", "off", "of"])
def test_manual_relay_help_does_not_connect(tmp_path, topic):
    ctx, transport = make_ctx(tmp_path)
    execute_command(ctx, f"help {topic}")
    text = ctx.console.export_text()
    assert "on <1..32>" in text
    assert "off <1..32>" in text
    assert "of" in text
    assert not transport.connected


def test_manual_relay_completion():
    assert completion_candidates("o") == ["of", "off", "on", "output"]
    for command in ("on", "off", "of"):
        assert completion_candidates(f"{command} ") == sorted(str(channel) for channel in range(1, 33))
        assert "1" not in completion_candidates(f"{command} 1 ")
        assert completion_candidates(f"{command} 3") == ["3", "30", "31", "32"]
        assert "32" not in completion_candidates(f"{command} 32 ")
        assert command in completion_candidates("help ")


@pytest.mark.parametrize("command,enabled", [("on", True), ("off", False), ("of", False)])
@pytest.mark.parametrize("channel", [8, 32])
def test_manual_relay_one_shot(tmp_path, monkeypatch, command, enabled, channel):
    config_path = tmp_path / "config.ini"
    config_path.write_bytes(Path("config.ini").read_bytes())
    before = config_path.read_bytes()
    transport = FakeTransport()
    monkeypatch.setattr(stand_cli, "SerialTransport", lambda *args: transport)
    monkeypatch.setattr(sys, "argv", ["standforge", "--home", str(tmp_path), "--relay-id", "7", command, str(channel)])
    assert stand_cli.main() == 0
    assert transport.requests == [(bytes([7, 0x0F, 0, channel - 1, 0, 1, 1, int(enabled)]), "append")]
    assert not transport.connected
    assert config_path.read_bytes() == before
    assert not (tmp_path / "stand.ini").exists()
    assert not (tmp_path / ".standforge_history").exists()


def test_output_commands(tmp_path):
    ctx, transport = make_ctx(tmp_path)
    execute_command(ctx, "output pressure-high 75")
    assert transport.requests[-1] == (bytes.fromhex("02 06 00 03 3A 98"), "append")
    execute_command(ctx, "output pressure low 25")
    assert transport.requests[-1] == (bytes.fromhex("02 06 00 02 13 88"), "append")


def test_reset_command_resets_all_relays_and_outputs(tmp_path):
    ctx, transport = make_ctx(tmp_path)
    execute_command(ctx, "reset")
    assert transport.requests == [
        (bytes.fromhex("01 05 00 FF 00 00"), "append"),
        (bytes.fromhex("02 06 00 00 00 00"), "append"),
        (bytes.fromhex("02 06 00 01 00 00"), "append"),
        (bytes.fromhex("02 06 00 02 00 00"), "append"),
        (bytes.fromhex("02 06 00 03 00 00"), "append"),
    ]


def test_reset_all_alias(tmp_path):
    ctx, transport = make_ctx(tmp_path)
    execute_command(ctx, "reset all")
    assert len(transport.requests) == 5
    assert transport.requests[0] == (bytes.fromhex("01 05 00 FF 00 00"), "append")


def test_reset_uses_configured_relay_id(tmp_path):
    ctx, transport = make_ctx(tmp_path)
    ctx.settings = StandSettings(relay_address=7)
    execute_command(ctx, "reset")
    assert transport.requests[0] == (bytes.fromhex("07 05 00 FF 00 00"), "append")
    assert len(transport.requests) == 5


def test_reset_continues_analog_reset_after_relay_failure(tmp_path, monkeypatch):
    ctx, transport = make_ctx(tmp_path)
    original_exchange = transport.exchange

    def failed_relay_exchange(request, **kwargs):
        if request[1] == 0x05:
            transport.requests.append((request, kwargs["crc_mode_override"]))
            return Exchange(append_crc(request), b"", 1.0)
        return original_exchange(request, **kwargs)

    monkeypatch.setattr(transport, "exchange", failed_relay_exchange)
    with pytest.raises(RuntimeError, match="Reset incomplete: relays: No Modbus response"):
        execute_command(ctx, "reset")
    assert transport.requests == [
        (bytes.fromhex("01 05 00 FF 00 00"), "append"),
        (bytes.fromhex("02 06 00 00 00 00"), "append"),
        (bytes.fromhex("02 06 00 01 00 00"), "append"),
        (bytes.fromhex("02 06 00 02 00 00"), "append"),
        (bytes.fromhex("02 06 00 03 00 00"), "append"),
    ]
    assert "Стенд сброшен" not in ctx.console.export_text()


def test_set_output_range_persists(tmp_path):
    ctx, _ = make_ctx(tmp_path)
    execute_command(ctx, "set output-range 4-20ma")
    assert ctx.settings.output_range == "4-20ma"
    assert "4-20ma" in (tmp_path/"stand.ini").read_text(encoding="utf-8")
