from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol

from .crc import has_valid_crc
from .transport import Exchange


READ_FUNCTIONS = frozenset({0x01, 0x02, 0x03, 0x04})


class ScanArgumentError(ValueError):
    def __init__(self, key: str, **values: object):
        super().__init__(key)
        self.key = key
        self.values = values


class ScanTransport(Protocol):
    def exchange(
        self,
        raw_frame: bytes,
        *,
        timeout_ms: int | None = None,
        crc_mode_override: str | None = None,
    ) -> Exchange: ...


@dataclass(frozen=True)
class ScanOptions:
    start: int = 1
    end: int = 247
    timeout_ms: int = 100
    function: int = 0x03
    address: int = 0


@dataclass(frozen=True)
class ScanResult:
    slave: int
    exchange: Exchange
    exception_code: int | None = None


def parse_scan_arguments(parts: list[str], default_timeout_ms: int) -> ScanOptions:
    positional: list[str] = []
    timeout_ms = default_timeout_ms
    function = 0x03
    address = 0
    index = 0
    while index < len(parts):
        part = parts[index]
        if part in {"--timeout", "--function", "--address"}:
            if index + 1 >= len(parts):
                raise ScanArgumentError("scan_missing_value", flag=part)
            value = parts[index + 1]
            try:
                if part == "--timeout":
                    timeout_ms = int(value, 10)
                elif part == "--function":
                    function = int(value, 10)
                else:
                    address = (
                        int(value[2:], 16)
                        if value.lower().startswith("0x")
                        else int(value, 10)
                    )
            except ValueError:
                raise ScanArgumentError("scan_invalid_value", flag=part, value=value) from None
            index += 2
            continue
        if part.startswith("-"):
            raise ScanArgumentError("scan_unknown_flag", flag=part)
        positional.append(part)
        index += 1

    if len(positional) > 2:
        raise ScanArgumentError("scan_usage")
    try:
        start = int(positional[0], 10) if positional else 1
        end = int(positional[1], 10) if len(positional) == 2 else start if positional else 247
    except ValueError:
        raise ScanArgumentError("scan_invalid_slave") from None

    if start < 1 or end > 247 or start > end:
        raise ScanArgumentError("scan_invalid_range")
    if timeout_ms <= 0:
        raise ScanArgumentError("scan_invalid_timeout")
    if function not in READ_FUNCTIONS:
        raise ScanArgumentError("scan_invalid_function")
    if not 0 <= address <= 0xFFFF:
        raise ScanArgumentError("scan_invalid_address")
    return ScanOptions(start, end, timeout_ms, function, address)


def build_probe(slave: int, function: int = 0x03, address: int = 0) -> bytes:
    """Build a quantity-one Modbus read request without a CRC."""
    return bytes((slave, function, address >> 8, address & 0xFF, 0x00, 0x01))


def validate_probe_response(
    frame: bytes, expected_slave: int, expected_function: int
) -> int | None | bool:
    """Return False for no device, None for normal response, or exception code."""
    if not has_valid_crc(frame) or frame[0] != expected_slave:
        return False
    if frame[1] == (expected_function | 0x80):
        return frame[2] if len(frame) == 5 else False
    if frame[1] != expected_function or len(frame) < 5:
        return False

    expected_byte_count = 1 if expected_function in {0x01, 0x02} else 2
    byte_count = frame[2]
    if byte_count != expected_byte_count:
        return False
    if len(frame) != 3 + byte_count + 2:
        return False
    return None


def scan_devices(
    transport: ScanTransport,
    options: ScanOptions,
    *,
    on_exchange: Callable[[Exchange], None] | None = None,
    on_progress: Callable[[int, int, int, int], None] | None = None,
    on_found: Callable[[ScanResult], None] | None = None,
) -> list[ScanResult]:
    results: list[ScanResult] = []
    total = options.end - options.start + 1
    for index, slave in enumerate(range(options.start, options.end + 1), start=1):
        exchange = transport.exchange(
            build_probe(slave, options.function, options.address),
            timeout_ms=options.timeout_ms,
            crc_mode_override="append",
        )
        if on_exchange is not None:
            on_exchange(exchange)
        validation = validate_probe_response(exchange.rx, slave, options.function)
        if validation is not False:
            result = ScanResult(slave, exchange, validation)
            results.append(result)
            if on_found is not None:
                on_found(result)
        if on_progress is not None:
            on_progress(index, total, slave, len(results))
    return results
