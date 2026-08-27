from rtuforge.cli import build_parser


def test_english_cli_help():
    text = build_parser("en").format_help()
    assert "Modbus RTU console and script runner" in text
    assert "examples:" in text


def test_russian_cli_help():
    text = build_parser("ru").format_help()
    assert "консоль Modbus RTU" in text
    assert "примеры:" in text
    assert "Путь к INI-файлу настроек" in text
