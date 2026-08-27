from __future__ import annotations

from dataclasses import replace

import pytest

from rtuforge.crc import append_crc, has_valid_crc
from rtuforge.scanner import (
    ScanArgumentError,
    ScanOptions,
    build_probe,
    parse_scan_arguments,
    scan_devices,
    validate_probe_response,
)
from rtuforge.transport import Exchange


class FakeTransport:
    def __init__(self, responses: dict[int, bytes] | None = None):
        self.responses = responses or {}
        self.calls: list[tuple[bytes, int | None, str | None]] = []

    def exchange(self, raw_frame, *, timeout_ms=None, crc_mode_override=None):
        self.calls.append((raw_frame, timeout_ms, crc_mode_override))
        slave = raw_frame[0]
        return Exchange(append_crc(raw_frame), self.responses.get(slave, b""), 8.5)


def test_default_and_explicit_scan_ranges():
    assert parse_scan_arguments([], 100) == ScanOptions(1, 247, 100, 3, 0)
    assert parse_scan_arguments(["7"], 100) == ScanOptions(7, 7, 100, 3, 0)
    assert parse_scan_arguments(["10", "30"], 100) == ScanOptions(10, 30, 100, 3, 0)


def test_scan_options_parse_timeout_function_and_addresses():
    assert parse_scan_arguments(["1", "32", "--timeout", "200"], 100).timeout_ms == 200
    assert parse_scan_arguments(["--function", "04"], 100).function == 4
    assert parse_scan_arguments(["--address", "101"], 100).address == 101
    assert parse_scan_arguments(["--address", "0065"], 100).address == 65
    assert parse_scan_arguments(["--address", "0x0065"], 100).address == 0x0065


@pytest.mark.parametrize(
    "parts",
    [
        ["0"], ["248"], ["20", "10"], ["1", "2", "3"],
        ["--timeout", "0"], ["--function", "05"], ["--address", "65536"],
        ["--unknown", "1"], ["--timeout"],
    ],
)
def test_invalid_scan_arguments(parts):
    with pytest.raises(ScanArgumentError):
        parse_scan_arguments(parts, 100)


def test_probe_is_read_only_and_quantity_one():
    assert build_probe(1) == bytes.fromhex("01 03 00 00 00 01")
    assert build_probe(7, 4, 0x0065) == bytes.fromhex("07 04 00 65 00 01")


def test_valid_normal_and_exception_responses_are_found():
    responses = {
        1: append_crc(bytes.fromhex("01 03 02 00 05")),
        7: append_crc(bytes.fromhex("07 83 02")),
    }
    results = scan_devices(FakeTransport(responses), ScanOptions(1, 7, 100, 3, 0))
    assert [result.slave for result in results] == [1, 7]
    assert results[0].exception_code is None
    assert results[1].exception_code == 2


@pytest.mark.parametrize(
    ("byte_count", "data", "found"),
    [
        (0, "", False),
        (1, "05", False),
        (2, "00 05", True),
    ],
)
def test_fc03_requires_exact_quantity_one_response(byte_count, data, found):
    payload = f"01 03 {byte_count:02X}" + (f" {data}" if data else "")
    frame = append_crc(bytes.fromhex(payload))
    assert (validate_probe_response(frame, 1, 3) is not False) is found


@pytest.mark.parametrize("function", [1, 2])
def test_fc01_fc02_require_one_data_byte(function):
    correct = append_crc(bytes((1, function, 1, 1)))
    wrong_count = append_crc(bytes((1, function, 2, 1, 0)))
    assert validate_probe_response(correct, 1, function) is None
    assert validate_probe_response(wrong_count, 1, function) is False


def test_exception_response_requires_exact_structure():
    valid = append_crc(bytes.fromhex("01 83 02"))
    malformed = append_crc(bytes.fromhex("01 83 02 00"))
    assert validate_probe_response(valid, 1, 3) == 2
    assert validate_probe_response(malformed, 1, 3) is False


@pytest.mark.parametrize(
    "frame",
    [
        b"",
        b"\x01\x03",
        bytes.fromhex("01 03 02 00 05 00 00"),
        append_crc(bytes.fromhex("02 03 02 00 05")),
        append_crc(bytes.fromhex("01 04 02 00 05")),
    ],
)
def test_invalid_or_unrelated_response_is_not_found(frame):
    assert validate_probe_response(frame, 1, 3) is False


def test_scan_uses_temporary_timeout_and_crc_override_for_every_probe():
    transport = FakeTransport()
    scan_devices(transport, ScanOptions(3, 5, 175, 4, 101))
    assert len(transport.calls) == 3
    assert all(timeout == 175 for _, timeout, _ in transport.calls)
    assert all(mode == "auto" for _, _, mode in transport.calls)
    assert all(frame[1:] == bytes.fromhex("04 00 65 00 01") for frame, _, _ in transport.calls)
    assert all(has_valid_crc(append_crc(frame)) for frame, _, _ in transport.calls)


def test_default_scan_probes_all_247_ids():
    transport = FakeTransport()
    scan_devices(transport, ScanOptions())
    assert len(transport.calls) == 247
    assert transport.calls[0][0][0] == 1
    assert transport.calls[-1][0][0] == 247
