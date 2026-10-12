"""CLI integration against a fake transport. No real RS-485 writes."""
from __future__ import annotations
import struct
from pathlib import Path
from types import SimpleNamespace
import pytest
from rich.console import Console
from rtuforge.commands import CommandContext, execute_command
from rtuforge.config import load_config
from rtuforge.pulsar_protocol import build_request
from rtuforge.scripts import ScriptStore
from rtuforge.transport import Exchange

class FakePulsarTransport:
    def __init__(self, config):
        self.config = config
        self.connected = False
        self.settings = SimpleNamespace(bytesize=8, parity="N", stopbits=1)
        self.response = b""
        self.sent = []
        self.connects = 0
    def connect(self):
        self.connected = True
        self.connects += 1
    def disconnect(self):
        self.connected = False
    def exchange(self, payload, *, crc_mode_override=None):
        self.sent.append((payload, crc_mode_override))
        return Exchange(payload, self.response, 1.0)

@pytest.fixture
def ctx(tmp_path):
    cfg = load_config(Path("config.ini"))
    cfg["ui"]["language"] = "en"
    cfg["runtime"]["crc_mode"] = "append"
    return CommandContext(
        tmp_path / "config.ini", cfg, ScriptStore(tmp_path / "scripts.ini"),
        FakePulsarTransport(cfg), Console(record=True, width=160), one_shot=True,
    )

def text(ctx):
    return ctx.console.export_text(clear=False)

def test_help_and_offline_decode_do_not_connect(ctx):
    execute_command(ctx, "help pulsar")
    execute_command(ctx, "pulsar decode 17 44 07 07 0A 12 C3 1F 0A 01 00 00 00 00 79 E6 B4 7B")
    assert "Pulsar address: 17440707" in text(ctx)
    assert "0xE679" in text(ctx)
    assert ctx.transport.connects == 0

def test_read_ignores_modbus_crc_setting(ctx):
    ctx.transport.response = build_request("17440707", 0x01, struct.pack("<f", 1.25))
    execute_command(ctx, "pulsar read 17440707")
    assert "1.25 m3" in text(ctx)
    payload, crc_mode = ctx.transport.sent[0]
    assert payload[:10].hex(" ").upper() == "17 44 07 07 01 0E 01 00 00 00"
    assert len(payload) == 14
    assert crc_mode == "none"
    assert ctx.config["runtime"]["crc_mode"] == "append"
    assert "Registers:" not in text(ctx)

def test_param_read_raw_and_conversion(ctx):
    ctx.transport.response = build_request("17440707", 0x0A, bytes.fromhex("01 00 00 00 00 00 00 00"))
    execute_command(ctx, "pulsar param get 17440707 0x000A --format u32")
    assert "Parameter 0x000A raw: 01 00 00 00 00 00 00 00" in text(ctx)
    assert "u32 (first 4 bytes LE): 1" in text(ctx)
    assert ctx.transport.sent[0][0][6:8] == bytes.fromhex("0A 00")

def test_param_write_requires_explicit_execute(ctx):
    execute_command(ctx, "pulsar param set 17440707 0x0010 0102030405060708")
    assert "DRY RUN" in text(ctx)
    assert ctx.transport.connects == 0 and ctx.transport.sent == []
    ctx.transport.response = build_request("17440707", 0x0B, b"\x00\x00")
    execute_command(ctx, "pulsar param set 17440707 0x0010 0102030405060708 --execute")
    assert "write acknowledged" in text(ctx)
    assert ctx.transport.sent[0][0][4:16] == bytes.fromhex("0B 14 10 00 01 02 03 04 05 06 07 08")
    assert ctx.transport.sent[0][1] == "none"

def test_clock_read_and_write_confirmation(ctx):
    ctx.transport.response = build_request("17440707", 0x04, bytes((26, 10, 12, 15, 34, 56)))
    execute_command(ctx, "pulsar time get 17440707")
    assert "2026-10-12T15:34:56" in text(ctx)
    count = len(ctx.transport.sent)
    execute_command(ctx, "pulsar time set 17440707 2026-10-12T15:34:56")
    assert len(ctx.transport.sent) == count
    ctx.transport.response = build_request("17440707", 0x05, b"\x01\x00\x00\x00")
    execute_command(ctx, "pulsar time set 17440707 2026-10-12T15:34:56 --execute")
    assert "time write acknowledged" in text(ctx)

def test_discover_requires_single_device(ctx):
    with pytest.raises(ValueError, match="Broadcast"):
        execute_command(ctx, "pulsar discover")
    assert ctx.transport.connects == 0
    ctx.transport.response = bytes.fromhex("17 44 07 07 0A 12 C3 1F 0A 01 00 00 00 00 79 E6 B4 7B")
    execute_command(ctx, "pulsar discover --single")
    assert "Pulsar address: 17440707" in text(ctx)
    assert ctx.transport.sent[0][0].hex(" ").upper() == "00 00 00 00 0A 0C 01 00 79 E6 C3 4A"

def test_invalid_settings_and_commands_do_not_connect(ctx):
    ctx.transport.settings.parity = "E"
    with pytest.raises(ValueError, match="8N1"):
        execute_command(ctx, "pulsar read 17440707")
    ctx.transport.settings.parity = "N"
    for command in (
        "pulsar read 17440707 --channel 33",
        "pulsar param get 17440707 invalid",
        "pulsar param set 17440707 1 0000 --execute",
        "pulsar time set 17440707 invalid --execute",
    ):
        with pytest.raises(ValueError):
            execute_command(ctx, command)
    assert ctx.transport.connects == 0

def test_device_error_is_not_success(ctx):
    ctx.transport.response = build_request("17440707", 0x00, b"\x05")
    with pytest.raises(RuntimeError, match="authorization required"):
        execute_command(ctx, "pulsar param get 17440707 1")
