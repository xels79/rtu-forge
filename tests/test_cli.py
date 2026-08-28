import sys
from pathlib import Path
from unittest.mock import patch

from rtuforge.cli import _language_for_argv, _promote_clean_flag, build_parser, main
from rtuforge.connection import parse_connection_overrides


def test_english_cli_help():
    text = build_parser("en").format_help()
    assert "Modbus RTU console and script runner" in text
    assert "examples:" in text
    assert "--clean" in text
    assert "Detailed command help:" in text
    assert "rtuforge help <command>" in text
    assert "rtuforge help scan" in text
    assert "rtuforge scan" in text
    assert "Temporary connection overrides" in text
    assert "--timeout-ms" in text
    assert "--parity {N,E,O,M,S}" in text


def test_russian_cli_help():
    text = build_parser("ru").format_help()
    assert "консоль Modbus RTU" in text
    assert "примеры:" in text
    assert "Путь к INI-файлу настроек" in text
    assert "Чистый HEX-вывод" in text
    assert "Подробная справка по командам:" in text
    assert "rtuforge help <command>" in text
    assert "rtuforge help scan" in text
    assert "rtuforge scan" in text
    assert "Временные параметры соединения" in text


def test_connection_flags_are_global_startup_options():
    args = build_parser("en").parse_args(
        ["--port", "COM7", "--baudrate", "19200", "--parity", "n", "status"]
    )
    overrides = parse_connection_overrides(
        {
            "port": args.port,
            "baudrate": args.baudrate,
            "bytesize": args.bytesize,
            "parity": args.parity,
            "stopbits": args.stopbits,
            "timeout_ms": args.timeout_ms,
        }
    )
    assert overrides.port == "COM7"
    assert overrides.baudrate == 19200
    assert overrides.parity == "N"
    assert args.command == ["status"]


def test_connection_timeout_and_scan_timeout_remain_separate():
    args = build_parser("en").parse_args(
        ["--timeout-ms", "1000", "scan", "1", "32", "--timeout", "100"]
    )
    assert args.timeout_ms == "1000"
    assert args.command == ["scan", "1", "32", "--timeout", "100"]


def test_clean_flag_can_be_written_after_command():
    assert _promote_clean_flag(["run", "script", "idd-status", "-c"]) == [
        "--clean", "run", "script", "idd-status"
    ]
    assert _promote_clean_flag(["send", "01", "03", "--clean"]) == [
        "--clean", "send", "01", "03"
    ]


def test_startup_override_status_does_not_modify_config(tmp_path, monkeypatch):
    config_path = tmp_path / "config.ini"
    config_path.write_bytes(Path("config.ini").read_bytes())
    scripts_path = tmp_path / "scripts.ini"
    scripts_path.write_bytes(Path("scripts.ini").read_bytes())
    before = config_path.read_bytes()
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "rtuforge", "--config", str(config_path), "--scripts", str(scripts_path),
            "--port", "COM7", "--baudrate", "19200", "status",
        ],
    )
    assert main() == 0
    assert config_path.read_bytes() == before


def test_paths_works_before_config_exists(tmp_path, monkeypatch, capsys):
    home = tmp_path / "new-home"
    monkeypatch.setenv("RTUFORGE_HOME", str(home))
    monkeypatch.setattr(sys, "argv", ["rtuforge", "paths"])
    assert main() == 0
    output = capsys.readouterr().out.replace("\n", "")
    assert str(home.resolve()) in output
    assert str((home / "config.ini").resolve()) in output
    assert not home.exists()


def test_paths_with_config_uses_custom_relative_history_without_connect(
    tmp_path, monkeypatch, capsys
):
    home = tmp_path / "data"
    home.mkdir()
    config_path = home / "config.ini"
    config_path.write_bytes(Path("config.ini").read_bytes())
    scripts_path = home / "scripts.ini"
    scripts_path.write_bytes(Path("scripts.ini").read_bytes())
    text = config_path.read_text(encoding="utf-8")
    config_path.write_text(
        text.replace("file = .rtuforge_history", "file = history/custom.log"),
        encoding="utf-8",
    )
    before = {path.name: path.read_bytes() for path in (config_path, scripts_path)}
    monkeypatch.setattr(sys, "argv", ["rtuforge", "--home", str(home), "paths"])
    with patch("rtuforge.transport.SerialTransport.connect") as connect:
        assert main() == 0
    connect.assert_not_called()
    output = capsys.readouterr().out.replace("\n", "")
    assert str((home / "history" / "custom.log").resolve()) in output
    assert {path.name: path.read_bytes() for path in (config_path, scripts_path)} == before


def test_paths_with_connection_override_does_not_connect(tmp_path, monkeypatch):
    home = tmp_path / "missing"
    monkeypatch.setattr(
        sys, "argv", ["rtuforge", "--home", str(home), "--port", "COM99", "paths"]
    )
    with patch("rtuforge.transport.SerialTransport.connect") as connect:
        assert main() == 0
    connect.assert_not_called()
    assert not home.exists()


def test_home_controls_help_language_and_explicit_config_wins(tmp_path):
    russian_home = tmp_path / "ru"
    english_home = tmp_path / "en"
    russian_home.mkdir()
    english_home.mkdir()
    ru_text = Path("config.ini").read_text(encoding="utf-8").replace(
        "language = en", "language = ru"
    )
    en_text = Path("config.ini").read_text(encoding="utf-8").replace(
        "language = ru", "language = en"
    )
    (russian_home / "config.ini").write_text(ru_text, encoding="utf-8")
    (english_home / "config.ini").write_text(en_text, encoding="utf-8")
    assert _language_for_argv(["--home", str(russian_home), "--help"]) == "ru"
    assert _language_for_argv(
        [
            "--home", str(russian_home),
            "--config", str(english_home / "config.ini"),
            "--help",
        ]
    ) == "en"
