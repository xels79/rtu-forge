from pathlib import Path
from unittest.mock import Mock, patch

import pytest
from rich.console import Console

from rtuforge.commands import CommandContext, execute_command
from rtuforge.config import load_config
from rtuforge.script_file import load_script_file, save_script_file
from rtuforge.scripts import ScriptStore


class FakeTransport:
    def __init__(self, config):
        self.config = config
        self.connected = False
        self.connect = Mock()
        self.disconnect = Mock()


@pytest.fixture
def ctx(tmp_path: Path) -> CommandContext:
    config = load_config(Path("config.ini"))
    config["ui"]["language"] = "en"
    config["runtime"]["inter_command_delay_ms"] = "0"
    return CommandContext(
        tmp_path / "config.ini",
        config,
        ScriptStore(tmp_path / "scripts.ini"),
        FakeTransport(config),
        Console(record=True, width=160),
    )


def output(ctx: CommandContext) -> str:
    return ctx.console.export_text(clear=False)


def test_export_one_all_relative_space_and_overwrite(ctx: CommandContext, tmp_path: Path, monkeypatch):
    ctx.scripts.set("Motor status", ["pause 1"])
    ctx.scripts.set("other", ["pause 2"])
    monkeypatch.chdir(tmp_path)
    execute_command(ctx, 'export script Motor status --file "sub dir/motor.rtus"')
    path = tmp_path / "sub dir" / "motor.rtus"
    assert load_script_file(path) == {"Motor status": ["pause 1"]}
    assert str(path.resolve()) in output(ctx)
    with pytest.raises(ValueError, match="already exists"):
        execute_command(ctx, 'export script Motor status --file "sub dir/motor.rtus"')
    execute_command(ctx, 'export script Motor status --file "sub dir/motor.rtus" --overwrite')
    execute_command(ctx, "export scripts --file bundle.rtus")
    assert set(load_script_file(tmp_path / "bundle.rtus")) == {"Motor status", "other"}
    ctx.transport.connect.assert_not_called()


def test_unquoted_windows_absolute_path_keeps_backslashes(ctx: CommandContext):
    with patch("rtuforge.commands.load_script_file", return_value={"demo": ["pause 0"]}) as load:
        execute_command(ctx, r"run file C:\temp\demo.rtus")
    load.assert_called_once_with(r"C:\temp\demo.rtus")


def test_export_missing_and_empty_do_not_create_files(ctx: CommandContext, tmp_path: Path):
    with pytest.raises(ValueError, match="not found"):
        execute_command(ctx, f'export script missing --file "{tmp_path / "x.rtus"}"')
    execute_command(ctx, f'export scripts --file "{tmp_path / "empty.rtus"}"')
    assert not (tmp_path / "empty.rtus").exists()


def test_import_single_bundle_merge_overwrite_and_atomic_conflict(ctx: CommandContext, tmp_path: Path):
    single = tmp_path / "single.rtus"
    save_script_file(single, {"demo": ["pause 1"]})
    execute_command(ctx, f'import script "{single}"')
    assert ctx.scripts.get("demo") == ["pause 1"]

    bundle = tmp_path / "bundle.rtus"
    save_script_file(bundle, {"new": ["pause 2"], "demo": ["pause 3"]})
    before = ctx.scripts.path.read_bytes()
    with pytest.raises(ValueError, match="Scripts already exist"):
        execute_command(ctx, f'import scripts "{bundle}"')
    assert ctx.scripts.path.read_bytes() == before
    assert "new" not in ctx.scripts.list()

    execute_command(ctx, f'import scripts "{bundle}" --overwrite')
    assert ctx.scripts.get("demo") == ["pause 3"]
    assert ctx.scripts.get("new") == ["pause 2"]
    ctx.transport.connect.assert_not_called()


def test_import_script_rejects_bundle_and_malformed_is_byte_identical(ctx: CommandContext, tmp_path: Path):
    ctx.scripts.set("kept", ["pause 1"])
    bundle = tmp_path / "bundle.rtus"
    save_script_file(bundle, {"a": [], "b": []})
    with pytest.raises(ValueError, match="multiple scripts"):
        execute_command(ctx, f'import script "{bundle}"')
    before = ctx.scripts.path.read_bytes()
    bad = tmp_path / "bad.rtus"
    bad.write_text("not ini", encoding="utf-8")
    with pytest.raises(ValueError):
        execute_command(ctx, f'import scripts "{bad}"')
    assert ctx.scripts.path.read_bytes() == before


def test_run_file_single_and_selected_bundle_do_not_import(ctx: CommandContext, tmp_path: Path):
    ctx.scripts.set("stored", ["pause 0"])
    before = ctx.scripts.path.read_bytes()
    single = tmp_path / "single.rtus"
    save_script_file(single, {"direct": ["pause 0"]})
    execute_command(ctx, f'run file "{single}"')
    assert "Running script 'direct'" in output(ctx)
    assert ctx.scripts.path.read_bytes() == before

    bundle = tmp_path / "bundle.rtus"
    save_script_file(bundle, {"one": ["pause 0"], "Motor status": ["pause 0"]})
    with pytest.raises(ValueError, match="multiple scripts"):
        execute_command(ctx, f'run file "{bundle}"')
    execute_command(ctx, f'run file "{bundle}" --script "Motor status"')
    assert ctx.scripts.path.read_bytes() == before


def test_run_file_decode_inheritance_and_send_override(ctx: CommandContext, tmp_path: Path):
    path = tmp_path / "decode.rtus"
    save_script_file(path, {"demo": ["send 01", "send --decode 02"]})
    with patch("rtuforge.commands.send_frame") as send:
        execute_command(ctx, f'run file "{path}" --raw')
    assert send.call_args_list[0].kwargs["decode_override"] is False
    assert send.call_args_list[1].kwargs["decode_override"] is True
    with pytest.raises(ValueError, match="cannot be used together"):
        execute_command(ctx, f'run file "{path}" --raw --decode')


def test_run_file_interrupt_stops_remaining_lines(ctx: CommandContext, tmp_path: Path):
    path = tmp_path / "interrupt.rtus"
    save_script_file(path, {"demo": ["scan 1 247", "connect"]})
    with patch("rtuforge.commands.run_scan", return_value=True):
        execute_command(ctx, f'run file "{path}"')
    ctx.transport.connect.assert_not_called()


@pytest.mark.parametrize("line", ["run file nested.rtus", "import scripts nested.rtus", "export scripts --file nested.rtus"])
def test_file_management_is_forbidden_inside_scripts(ctx: CommandContext, line: str):
    with pytest.raises(ValueError, match="not allowed inside scripts"):
        execute_command(ctx, line, from_script=True)


def test_run_file_can_run_stored_script(ctx: CommandContext, tmp_path: Path):
    ctx.scripts.set("stored", ["pause 0"])
    path = tmp_path / "nested.rtus"
    save_script_file(path, {"direct": ["run script stored"]})
    execute_command(ctx, f'run file "{path}"')
    assert "01> run script stored" in output(ctx)
