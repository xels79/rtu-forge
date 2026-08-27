import sys

from rtuforge.cli import build_parser, main


def test_english_cli_help():
    text = build_parser("en").format_help()
    assert "Modbus RTU console and script runner" in text
    assert "examples:" in text


def test_russian_cli_help():
    text = build_parser("ru").format_help()
    assert "консоль Modbus RTU" in text
    assert "примеры:" in text
    assert "Путь к INI-файлу настроек" in text


def test_one_shot_missing_script_has_no_traceback(monkeypatch, capsys):
    monkeypatch.setattr(sys, "argv", ["rtuforge", "run", "script", "definitely-missing-script", "-r"])
    assert main() == 1
    captured = capsys.readouterr()
    combined = captured.out + captured.err
    assert "Traceback" not in combined
    assert "definitely-missing-script" in combined
    assert "not found" in combined
