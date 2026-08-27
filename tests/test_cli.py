from rtuforge.cli import _promote_clean_flag, build_parser


def test_english_cli_help():
    text = build_parser("en").format_help()
    assert "Modbus RTU console and script runner" in text
    assert "examples:" in text
    assert "--clean" in text


def test_russian_cli_help():
    text = build_parser("ru").format_help()
    assert "консоль Modbus RTU" in text
    assert "примеры:" in text
    assert "Путь к INI-файлу настроек" in text
    assert "Чистый HEX-вывод" in text


def test_clean_flag_can_be_written_after_command():
    assert _promote_clean_flag(["run", "script", "idd-status", "-c"]) == [
        "--clean", "run", "script", "idd-status"
    ]
    assert _promote_clean_flag(["send", "01", "03", "--clean"]) == [
        "--clean", "send", "01", "03"
    ]
