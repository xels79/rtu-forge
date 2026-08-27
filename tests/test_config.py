from pathlib import Path

import pytest

from rtuforge.config import load_config, option_spec, parse_value


def test_default_config_loads():
    config = load_config(Path("config.ini"))
    assert config["connection"].getint("baudrate") == 9600
    assert config["connection"].get("parity") == "E"
    assert config["runtime"].getint("inter_command_delay_ms") == 100
    assert config["runtime"].getboolean("decode_rx") is True
    assert config["ui"].get("language") in {"en", "ru"}
    assert config["runtime"].getint("scan_timeout_ms") == 100


def test_boolean_option_parser():
    spec = option_spec("auto_connect")
    assert parse_value(spec, "yes") == "true"
    assert parse_value(spec, "off") == "false"


def test_language_option_parser():
    spec = option_spec("language")
    assert parse_value(spec, "ru") == "ru"
    assert parse_value(spec, "EN") == "EN"


def test_scan_timeout_option_must_be_positive():
    spec = option_spec("scan_timeout_ms")
    assert parse_value(spec, "1") == "1"
    with pytest.raises(ValueError):
        parse_value(spec, "0")


def test_old_config_gets_scan_timeout_default(tmp_path):
    path = tmp_path / "config.ini"
    path.write_text("[runtime]\ncrc_mode = auto\n", encoding="utf-8")
    config = load_config(path)
    assert config["runtime"].getint("scan_timeout_ms") == 100
