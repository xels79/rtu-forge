from pathlib import Path
from unittest.mock import Mock

from rich.console import Console

from rtuforge.commands import CommandContext, _parse_run_arguments, _print_exchange, execute_command
from rtuforge.config import load_config
from rtuforge.crc import append_crc
from rtuforge.scripts import ScriptStore


class FakeTransport:
    def __init__(self, config):
        self.config = config
        self.connected = False
        self.connect = Mock(side_effect=self._connect)
        self.disconnect = Mock(side_effect=self._disconnect)

    def _connect(self):
        self.connected = True

    def _disconnect(self):
        self.connected = False

    @property
    def endpoint(self):
        return "COM4 @ 9600 8E1"


def make_context(tmp_path: Path, *, one_shot: bool = False) -> CommandContext:
    config = load_config(Path("config.ini"))
    return CommandContext(
        tmp_path / "config.ini",
        config,
        ScriptStore(tmp_path / "scripts.ini"),
        FakeTransport(config),
        Console(record=True, width=120),
        one_shot=one_shot,
    )


def output(ctx: CommandContext) -> str:
    return ctx.console.export_text(clear=False)


def test_run_script_decode_flags_are_not_part_of_name():
    assert _parse_run_arguments(["idd-status", "-r"]) == ("idd-status", False)
    assert _parse_run_arguments(["idd-status", "--decode"]) == ("idd-status", True)


def test_one_shot_connect_is_silent(tmp_path):
    ctx = make_context(tmp_path, one_shot=True)
    execute_command(ctx, "connect")
    assert output(ctx) == ""


def test_clean_output_is_plain_hex_and_hides_decode(tmp_path):
    ctx = make_context(tmp_path)
    ctx.config["runtime"]["clean_output"] = "true"
    rx = append_crc(bytes.fromhex("01 03 02 00 05"))
    _print_exchange(ctx, bytes.fromhex("01 03 00 65 00 01"), rx, 12.4)
    text = output(ctx)
    assert "TX" not in text
    assert "RX" not in text
    assert "Registers:" not in text
    assert "01 03 00 65 00 01" in text
    assert "01 03 02 00 05" in text


def test_decode_flag_overrides_clean_output(tmp_path):
    ctx = make_context(tmp_path)
    ctx.config["runtime"]["clean_output"] = "true"
    rx = append_crc(bytes.fromhex("01 03 02 00 05"))
    _print_exchange(ctx, b"\x01", rx, 12.4, decode_override=True)
    assert "Registers:" in output(ctx)


def test_record_rx_to_file_is_independent_of_output(tmp_path):
    ctx = make_context(tmp_path)
    ctx.config["runtime"]["show_rx"] = "false"
    execute_command(ctx, "record start rx")
    rx = append_crc(bytes.fromhex("01 03 02 00 05"))
    _print_exchange(ctx, b"\x01", rx, 12.4)
    execute_command(ctx, "record stop file capture.txt")
    text = (tmp_path / "capture.txt").read_text(encoding="utf-8")
    assert text.strip() == " ".join(f"{byte:02X}" for byte in rx)


def test_record_all_matches_clean_screen_format(tmp_path):
    ctx = make_context(tmp_path)
    ctx.config["runtime"]["clean_output"] = "true"
    execute_command(ctx, "record start all")
    tx = bytes.fromhex("01 03 00 65 00 01 94 15")
    rx = bytes.fromhex("01 03 02 00 05 78 47")
    _print_exchange(ctx, tx, rx, 12.4)
    assert ctx.recording.lines == [
        "01 03 00 65 00 01 94 15",
        "01 03 02 00 05 78 47",
    ]


def test_show_record_prints_buffer_without_stopping_recording(tmp_path):
    ctx = make_context(tmp_path)
    ctx.config["runtime"]["clean_output"] = "true"
    execute_command(ctx, "record start all")
    tx = bytes.fromhex("01 03 00 65 00 01 94 15")
    rx = bytes.fromhex("01 03 02 00 05 78 47")
    _print_exchange(ctx, tx, rx, 12.4)
    ctx.console = Console(record=True, width=120)
    execute_command(ctx, "show record")
    text = output(ctx)
    assert "01 03 00 65 00 01 94 15" in text
    assert "01 03 02 00 05 78 47" in text
    assert ctx.recording.active is True
