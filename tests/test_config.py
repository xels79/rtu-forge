from pathlib import Path

from rtuforge.config import load_config, option_spec, parse_value


def test_default_config_loads():
    config = load_config(Path("config.ini"))
    assert config["connection"].getint("baudrate") == 9600
    assert config["connection"].get("parity") == "E"
    assert config["runtime"].getint("inter_command_delay_ms") == 100


def test_boolean_option_parser():
    spec = option_spec("auto_connect")
    assert parse_value(spec, "yes") == "true"
    assert parse_value(spec, "off") == "false"
