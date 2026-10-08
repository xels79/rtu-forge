from __future__ import annotations

from dataclasses import dataclass

from .crc import has_valid_crc


RELAY_CHANNEL_COUNT = 32


TANK_LEVEL_BITS: dict[str, tuple[bool, bool]] = {
    "empty": (False, False),
    "middle": (True, False),
    "full": (True, True),
}

OUTPUT_CHANNEL_ALIASES: dict[str, int] = {
    "temperature": 0,
    "temp": 0,
    "humidity": 1,
    "hum": 1,
    "pressure-low": 2,
    "low-pressure": 2,
    "plow": 2,
    "pressure-high": 3,
    "high-pressure": 3,
    "phigh": 3,
}

OUTPUT_CHANNEL_NAMES: tuple[str, ...] = (
    "temperature",
    "humidity",
    "pressure-low",
    "pressure-high",
)


@dataclass(frozen=True)
class OutputRange:
    name: str
    minimum: int
    maximum: int
    unit: str


OUTPUT_RANGES: dict[str, OutputRange] = {
    "0-20ma": OutputRange("0-20ma", 0, 20_000, "uA"),
    "4-20ma": OutputRange("4-20ma", 4_000, 20_000, "uA"),
    "0-10v": OutputRange("0-10v", 0, 10_000, "mV"),
}


def _slave(value: int) -> int:
    if not 1 <= value <= 247:
        raise ValueError("Modbus address must be in range 1..247")
    return value


def _u16(value: int, *, name: str) -> int:
    if not 0 <= value <= 0xFFFF:
        raise ValueError(f"{name} must be in range 0..65535")
    return value


def _pack_coils(values: tuple[bool, ...] | list[bool]) -> bytes:
    result = bytearray((len(values) + 7) // 8)
    for index, enabled in enumerate(values):
        if enabled:
            result[index // 8] |= 1 << (index % 8)
    return bytes(result)


def build_write_multiple_coils(
    slave: int, start_address: int, values: tuple[bool, ...] | list[bool]
) -> bytes:
    _slave(slave)
    _u16(start_address, name="start_address")
    if not values:
        raise ValueError("At least one coil is required")
    if len(values) > 0x07B0:
        raise ValueError("Too many coils")
    packed = _pack_coils(values)
    quantity = len(values)
    return bytes(
        (
            slave,
            0x0F,
            (start_address >> 8) & 0xFF,
            start_address & 0xFF,
            (quantity >> 8) & 0xFF,
            quantity & 0xFF,
            len(packed),
        )
    ) + packed


def build_all_relays_off_request(slave: int) -> bytes:
    """Build Waveshare's FC05 command to switch every relay off (without CRC)."""
    return bytes((_slave(slave), 0x05, 0x00, 0xFF, 0x00, 0x00))


def build_tank_request(slave: int, tank: int, level: str) -> bytes:
    if not 1 <= tank <= 4:
        raise ValueError("Tank number must be in range 1..4")
    normalized = level.strip().lower()
    try:
        lower, upper = TANK_LEVEL_BITS[normalized]
    except KeyError:
        raise ValueError("Tank level must be empty, middle or full") from None
    start = (tank - 1) * 2
    return build_write_multiple_coils(slave, start, [lower, upper])


def resolve_output_channel(name: str) -> tuple[int, str]:
    normalized = name.strip().lower().replace("_", "-")
    if normalized.isdigit():
        channel = int(normalized)
        if 1 <= channel <= 4:
            return channel - 1, OUTPUT_CHANNEL_NAMES[channel - 1]
    try:
        channel = OUTPUT_CHANNEL_ALIASES[normalized]
    except KeyError:
        raise ValueError(
            "Output must be temperature, humidity, pressure-low or pressure-high"
        ) from None
    return channel, OUTPUT_CHANNEL_NAMES[channel]


def parse_percent(value: str | float | int) -> float:
    if isinstance(value, str):
        value = value.strip().replace(",", ".")
    try:
        percent = float(value)
    except (TypeError, ValueError):
        raise ValueError("Percent must be a number from 0 to 100") from None
    if not 0.0 <= percent <= 100.0:
        raise ValueError("Percent must be in range 0..100")
    return percent


def raw_for_percent(percent: float, output_range: OutputRange) -> int:
    percent = parse_percent(percent)
    span = output_range.maximum - output_range.minimum
    return output_range.minimum + int(span * percent / 100.0 + 0.5)


def build_write_single_register(slave: int, register: int, value: int) -> bytes:
    _slave(slave)
    _u16(register, name="register")
    _u16(value, name="value")
    return bytes(
        (
            slave,
            0x06,
            (register >> 8) & 0xFF,
            register & 0xFF,
            (value >> 8) & 0xFF,
            value & 0xFF,
        )
    )


def build_output_request(
    slave: int,
    output: str,
    percent: str | float | int,
    output_range: OutputRange,
) -> tuple[bytes, int, str, float]:
    channel, canonical = resolve_output_channel(output)
    parsed = parse_percent(percent)
    raw = raw_for_percent(parsed, output_range)
    return build_write_single_register(slave, channel, raw), raw, canonical, parsed


def validate_write_response(request: bytes, response: bytes) -> None:
    if not response:
        raise RuntimeError("No Modbus response")
    if len(response) < 5:
        raise RuntimeError("Short Modbus response")
    if not has_valid_crc(response):
        raise RuntimeError("Invalid Modbus CRC in response")
    if response[0] != request[0]:
        raise RuntimeError(
            f"Unexpected Modbus address in response: {response[0]} (expected {request[0]})"
        )
    function = request[1]
    if response[1] == (function | 0x80):
        raise RuntimeError(f"Modbus exception {response[2]:02X}")
    if response[1] != function:
        raise RuntimeError(
            f"Unexpected Modbus function in response: {response[1]:02X}"
        )
    if function in {0x05, 0x06}:
        if len(response) != 8 or response[:6] != request[:6]:
            raise RuntimeError(f"Unexpected FC{function:02X} write response")
        return
    if function == 0x0F:
        if len(response) != 8 or response[:6] != request[:6]:
            raise RuntimeError("Unexpected FC0F write response")
        return
    raise ValueError(f"Unsupported write function: {function:02X}")
