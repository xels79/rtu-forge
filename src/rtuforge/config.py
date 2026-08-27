from __future__ import annotations

import configparser
from dataclasses import dataclass
from pathlib import Path


DEFAULT_CONFIG = Path("config.ini")


@dataclass(frozen=True)
class OptionSpec:
    section: str
    name: str
    description: str
    kind: str
    choices: tuple[str, ...] = ()
    default: str | None = None
    minimum: float | None = None


OPTION_SPECS: tuple[OptionSpec, ...] = (
    OptionSpec("connection", "port", "Serial port, e.g. COM5 or /dev/ttyUSB0", "str"),
    OptionSpec("connection", "baudrate", "Baud rate", "int", minimum=1),
    OptionSpec("connection", "bytesize", "Data bits", "int", ("5", "6", "7", "8")),
    OptionSpec("connection", "parity", "Parity: N/E/O/M/S", "str", ("N", "E", "O", "M", "S")),
    OptionSpec("connection", "stopbits", "Stop bits", "float", ("1", "1.5", "2")),
    OptionSpec("connection", "timeout_ms", "Serial read timeout", "int", minimum=1),
    OptionSpec("runtime", "inter_command_delay_ms", "Delay between script commands", "int"),
    OptionSpec("runtime", "post_write_delay_ms", "Delay after each serial write", "int"),
    OptionSpec("runtime", "response_silence_ms", "Silence used to detect end of response", "int"),
    OptionSpec("runtime", "max_response_bytes", "Maximum bytes collected for one response", "int"),
    OptionSpec("runtime", "crc_mode", "CRC handling: auto/append/none", "str", ("auto", "append", "none")),
    OptionSpec("runtime", "auto_connect", "Auto-connect for send/run in one-shot mode", "bool"),
    OptionSpec("runtime", "show_tx", "Print transmitted frames", "bool"),
    OptionSpec("runtime", "show_rx", "Print received frames", "bool"),
    OptionSpec("runtime", "decode_rx", "Decode received Modbus RTU frames after raw RX output", "bool", default="true"),
    OptionSpec("runtime", "clean_output", "Print plain HEX frames without TX/RX labels or timing", "bool", default="false"),
    OptionSpec(
        "runtime",
        "scan_timeout_ms",
        "Per-device Modbus scan timeout in milliseconds",
        "int",
        default="100",
        minimum=1,
    ),
    OptionSpec("runtime", "timestamps", "Show timestamps in TX/RX output", "bool"),
    OptionSpec("runtime", "uppercase_hex", "Use uppercase HEX output", "bool"),
    OptionSpec("history", "file", "Persistent interactive history file", "str"),
    OptionSpec("history", "max_entries", "History trimming limit", "int"),
    OptionSpec("ui", "language", "Help and CLI language: en/ru", "str", ("en", "ru"), default="en"),
)


def load_config(path: Path) -> configparser.ConfigParser:
    parser = configparser.ConfigParser()
    if not path.exists():
        raise FileNotFoundError(f"Config file not found: {path}")
    parser.read(path, encoding="utf-8")
    for spec in OPTION_SPECS:
        if spec.default is not None and not parser.has_option(spec.section, spec.name):
            if not parser.has_section(spec.section):
                parser.add_section(spec.section)
            parser[spec.section][spec.name] = spec.default
    return parser


def save_config(path: Path, config: configparser.ConfigParser) -> None:
    with path.open("w", encoding="utf-8") as stream:
        config.write(stream)


def option_spec(name: str) -> OptionSpec:
    needle = name.lower()
    matches = [spec for spec in OPTION_SPECS if spec.name.lower() == needle]
    if not matches:
        raise KeyError(name)
    if len(matches) > 1:
        raise KeyError(f"Ambiguous option: {name}")
    return matches[0]


def parse_value(spec: OptionSpec, value: str) -> str:
    if spec.kind == "int":
        parsed = str(int(value, 10))
    elif spec.kind == "float":
        parsed = f"{float(value.replace(',', '.')):g}"
    elif spec.kind == "bool":
        lowered = value.lower()
        if lowered in {"1", "true", "yes", "on"}:
            parsed = "true"
        elif lowered in {"0", "false", "no", "off"}:
            parsed = "false"
        else:
            raise ValueError("Expected boolean: true/false, yes/no, on/off, 1/0")
    else:
        parsed = value

    if spec.choices and parsed.upper() not in {choice.upper() for choice in spec.choices}:
        raise ValueError(f"Allowed values: {', '.join(spec.choices)}")
    if spec.minimum is not None and float(parsed) < spec.minimum:
        raise ValueError(f"Value must be at least {spec.minimum:g}")
    return parsed
