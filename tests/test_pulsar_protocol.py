"""Pulsar protocol golden vectors, no hardware access."""
from __future__ import annotations
import struct
import pytest
from rtuforge.crc import append_crc
from rtuforge.pulsar_protocol import (
    build_request, decode_clock, decode_value, parse_number, parse_response,
    parse_value_bytes, read_channel_request, read_clock_request,
    read_parameter_request, write_clock_request, write_parameter_request,
    validate_clock_write_response, validate_parameter_write_response,
)

def test_real_discovery_tx_and_rx():
    tx = read_parameter_request("00000000", 1, request_id=0xE679)
    assert tx.hex(" ").upper() == "00 00 00 00 0A 0C 01 00 79 E6 C3 4A"
    rx = bytes.fromhex("17 44 07 07 0A 12 C3 1F 0A 01 00 00 00 00 79 E6 B4 7B")
    parsed = parse_response(rx, function=0x0A, request_id=0xE679, payload_length=8)
    assert parsed.address == "17440707"
    assert parsed.payload == bytes.fromhex("C3 1F 0A 01 00 00 00 00")

def test_wirenboard_float_vector():
    assert read_channel_request("00107080", 3).hex(" ").upper() == "00 10 70 80 01 0E 04 00 00 00 00 00 7C A7"
    rx = bytes.fromhex("00 10 70 80 01 0E 5A B3 C5 41 00 00 18 DB")
    frame = parse_response(rx, address="00107080", function=0x01, request_id=0, payload_length=4)
    assert decode_value(frame.payload, "float") == pytest.approx(24.71257, abs=0.0001)

def test_meter_request_frame_and_param_frames():
    assert read_channel_request("17440707").hex(" ").upper() == "17 44 07 07 01 0E 01 00 00 00 00 00 A8 F0"
    assert read_parameter_request("17440707", 0x1234)[4:8] == bytes.fromhex("0A 0C 34 12")
    tx = write_parameter_request("17440707", 0x1234, bytes.fromhex("0102030405060708"))
    assert tx[4:16] == bytes.fromhex("0B 14 34 12 01 02 03 04 05 06 07 08")
    assert len(tx) == 20
    with pytest.raises(ValueError, match="exactly 8"):
        write_parameter_request("17440707", 1, b"\x00")

def test_clock_frames_and_decoding():
    assert read_clock_request("17440707")[4:6] == bytes.fromhex("04 0A")
    assert write_clock_request("17440707", "2026-10-12T15:34:56")[4:12] == bytes((5, 16, 26, 10, 12, 15, 34, 56))
    assert decode_clock(bytes((26, 10, 12, 15, 34, 56))) == "2026-10-12T15:34:56"
    assert decode_clock(b"\xFF" * 6) is None
    with pytest.raises(ValueError):
        write_clock_request("17440707", "2100-01-01T00:00:00")

def test_response_validation():
    valid = build_request("17440707", 0x0A, b"abcdefgh", request_id=5)
    assert parse_response(valid, address="17440707", function=0x0A, request_id=5, payload_length=8)
    with pytest.raises(ValueError, match="CRC"):
        parse_response(valid[:-1] + bytes((valid[-1] ^ 1,)))
    with pytest.raises(ValueError, match="address mismatch"):
        parse_response(valid, address="17440708")
    with pytest.raises(ValueError, match="request ID"):
        parse_response(valid, request_id=6)
    with pytest.raises(ValueError, match="function mismatch"):
        parse_response(valid, function=0x01)
    with pytest.raises(ValueError, match="payload length mismatch"):
        parse_response(valid, payload_length=4)
    with pytest.raises(ValueError, match="length mismatch"):
        parse_response(valid[:5] + b"\x11" + valid[6:])
    with pytest.raises(ValueError, match="BCD"):
        parse_response(append_crc(bytes.fromhex("1A 44 07 07 01 0A 00 00")))

def test_errors_and_write_acknowledgements():
    with pytest.raises(RuntimeError, match="authorization required"):
        parse_response(build_request("17440707", 0x00, b"\x05"))
    validate_parameter_write_response(parse_response(build_request("17440707", 0x0B, b"\x00\x00")))
    validate_clock_write_response(parse_response(build_request("17440707", 0x05, b"\x01\x00\x00\x00")))
    with pytest.raises(ValueError, match="not confirmed"):
        validate_clock_write_response(parse_response(build_request("17440707", 0x05, b"\x00\x00\x00\x00")))

def test_validation_helpers():
    assert parse_number("0x10") == 16
    assert parse_number("10") == 10
    assert parse_value_bytes("01:02:03:04:05:06:07:08") == bytes(range(1, 9))
    with pytest.raises(ValueError, match="8 decimal"):
        read_channel_request("17G40707")
    with pytest.raises(ValueError, match="1..32"):
        read_channel_request("17440707", 33)
    with pytest.raises(ValueError, match="16 HEX"):
        parse_value_bytes("AB CD")
    with pytest.raises(ValueError, match="NaN"):
        decode_value(struct.pack("<f", float("nan")), "float")
