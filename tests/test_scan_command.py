from __future__ import annotations

from pathlib import Path

from rich.console import Console

from rtuforge.commands import CommandContext, RecordingState, execute_command, format_scan_progress
from rtuforge.config import load_config
from rtuforge.crc import append_crc
from rtuforge.scripts import ScriptStore
from rtuforge.transport import Exchange


class ScanTransport:
    def __init__(self, config, responses=None, interrupt_at=None):
        self.config = config
        self.responses = responses or {}
        self.interrupt_at = interrupt_at
        self.calls = []
        self.connected = False
        self.endpoint = "COM4 @ 9600 8E1"

    def connect(self):
        self.connected = True

    def disconnect(self):
        self.connected = False

    def exchange(self, raw_frame, *, timeout_ms=None, crc_mode_override=None):
        slave = raw_frame[0]
        if slave == self.interrupt_at:
            raise KeyboardInterrupt
        self.calls.append((raw_frame, timeout_ms, crc_mode_override))
        return Exchange(append_crc(raw_frame), self.responses.get(slave, b""), 12.4)


def make_context(tmp_path: Path, *, force_terminal=False, responses=None, interrupt_at=None):
    config = load_config(Path("config.ini"))
    config["ui"]["language"] = "en"
    transport = ScanTransport(config, responses, interrupt_at)
    return CommandContext(
        tmp_path / "config.ini",
        config,
        ScriptStore(tmp_path / "scripts.ini"),
        transport,
        Console(record=True, width=120, force_terminal=force_terminal),
    )


def output(ctx):
    return ctx.console.export_text(clear=False)


def test_clean_scan_prints_only_found_ids(tmp_path):
    responses = {
        1: append_crc(bytes.fromhex("01 03 02 00 05")),
        3: append_crc(bytes.fromhex("03 83 02")),
    }
    ctx = make_context(tmp_path, responses=responses)
    ctx.config["runtime"]["clean_output"] = "true"
    execute_command(ctx, "scan 1 3")
    assert output(ctx) == "1\n3\n"


def test_scan_records_probes_without_printing_regular_tx_rx(tmp_path):
    responses = {1: append_crc(bytes.fromhex("01 03 02 00 05"))}
    ctx = make_context(tmp_path, responses=responses)
    ctx.recording = RecordingState(mode="all")
    execute_command(ctx, "scan 1 2")
    text = output(ctx)
    assert "TX " not in text
    assert "<timeout" not in text
    assert ctx.recording.lines[0].startswith("TX 01 03 00 00 00 01")
    assert any(line.startswith("RX 01 03 02 00 05") for line in ctx.recording.lines)
    assert ctx.recording.lines.count("RX") == 0


def test_scan_rx_recording_keeps_responses_but_not_timeouts(tmp_path):
    response = append_crc(bytes.fromhex("01 03 02 00 05"))
    ctx = make_context(tmp_path, responses={1: response})
    ctx.recording = RecordingState(mode="rx")
    execute_command(ctx, "scan 1 2")
    assert ctx.recording.lines == [" ".join(f"{byte:02X}" for byte in response)]


def test_scan_overrides_do_not_modify_config(tmp_path):
    ctx = make_context(tmp_path)
    ctx.config["runtime"]["crc_mode"] = "none"
    original_connection_timeout = ctx.config["connection"]["timeout_ms"]
    execute_command(ctx, "scan 2 --timeout 25")
    assert ctx.transport.calls[0][1:] == (25, "auto")
    assert ctx.config["connection"]["timeout_ms"] == original_connection_timeout
    assert ctx.config["runtime"]["crc_mode"] == "none"


def test_ctrl_c_stops_scan_and_reports_partial_result(tmp_path):
    responses = {1: append_crc(bytes.fromhex("01 03 02 00 05"))}
    ctx = make_context(tmp_path, force_terminal=True, responses=responses, interrupt_at=2)
    execute_command(ctx, "scan 1 3")
    text = output(ctx)
    assert "Scan stopped." in text
    assert "Devices found: 1" in text
    assert "Traceback" not in text


def test_russian_scan_error_is_localized(tmp_path):
    ctx = make_context(tmp_path)
    ctx.config["ui"]["language"] = "ru"
    try:
        execute_command(ctx, "scan 0")
    except ValueError as exc:
        assert "Диапазон Slave ID" in str(exc)
    else:
        raise AssertionError("scan 0 must fail")


def test_scan_timeout_option_must_be_positive(tmp_path):
    ctx = make_context(tmp_path)
    try:
        execute_command(ctx, "set options scan_timeout_ms 0")
    except ValueError as exc:
        assert "greater than zero" in str(exc)
    else:
        raise AssertionError("zero scan timeout must fail")


def test_scan_progress_has_fixed_width_fields():
    lines = [format_scan_progress("en", "COM4 @ 9600 8E1", value, 247, value, value) for value in (1, 9, 10, 99, 100, 247)]
    assert all(f"ID {value:03d}" in line for line, value in zip(lines, (1, 9, 10, 99, 100, 247)))
    assert len({len(line) for line in lines}) == 1
