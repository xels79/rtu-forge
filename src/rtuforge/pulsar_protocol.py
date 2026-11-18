"""Pulsar proprietary RS-485 frames, not Modbus RTU register requests.

Frame layout: BCD address (4), function (1), total length (1), payload,
request ID (uint16 LE), CRC16 (uint16 LE).
"""
from __future__ import annotations

import math
import re
import struct
from dataclasses import dataclass
from datetime import datetime

from .crc import append_crc, has_valid_crc

ERROR_CODES = {
    1: "unsupported function",
    2: "invalid channel mask",
    3: "invalid frame length",
    4: "invalid parameter index",
    5: "access denied (authorization required)",
    6: "parameter value out of range",
    7: "unsupported archive type",
    8: "archive request too large",
}


@dataclass(frozen=True)
class PulsarFrame:
    address: str
    function: int
    payload: bytes
    request_id: int
    raw: bytes


def _address_bytes(address: str) -> bytes:
    if not re.fullmatch(r"[0-9]{8}", address):
        raise ValueError("Pulsar address must be exactly 8 decimal BCD digits, e.g. 17440707")
    return bytes.fromhex(address)


def _address_text(value: bytes) -> str:
    if len(value) != 4 or any((byte & 0xF) > 9 or (byte >> 4) > 9 for byte in value):
        raise ValueError("Pulsar frame contains invalid BCD address")
    return value.hex().upper()


def parse_number(value: str, *, maximum: int = 65535, name: str = "number") -> int:
    try:
        number = int(value, 16) if value.lower().startswith("0x") else int(value, 10)
    except ValueError:
        raise ValueError(f"Invalid {name}: {value}; use decimal or 0x-prefixed HEX") from None
    if not 0 <= number <= maximum:
        raise ValueError(f"{name} must be between 0 and {maximum}")
    return number


def build_request(address: str, function: int, payload: bytes = b"", *, request_id: int = 0) -> bytes:
    if not 0 <= function <= 255:
        raise ValueError("Pulsar function must fit into one byte")
    if not 0 <= request_id <= 65535:
        raise ValueError("Pulsar request ID must fit into uint16")
    length = len(payload) + 10
    if length > 255:
        raise ValueError("Pulsar request is too long")
    return append_crc(_address_bytes(address) + bytes((function, length)) + payload + request_id.to_bytes(2, "little"))


def parse_response(
    frame: bytes, *, address: str | None = None,
    function: int | None = None, request_id: int | None = None,
    payload_length: int | None = None,
) -> PulsarFrame:
    if len(frame) < 10:
        raise ValueError("Pulsar response is shorter than 10 bytes")
    if len(frame) != frame[5]:
        raise ValueError(f"Pulsar length mismatch: received {len(frame)}, header {frame[5]}")
    if not has_valid_crc(frame):
        raise ValueError("Pulsar CRC16 mismatch")
    decoded_addr = _address_text(frame[:4])
    if address is not None and decoded_addr != _address_text(_address_bytes(address)):
        raise ValueError(f"Pulsar address mismatch: expected {address}, got {decoded_addr}")
    actual_id = int.from_bytes(frame[-4:-2], "little")
    if request_id is not None and actual_id != request_id:
        raise ValueError(f"Pulsar request ID mismatch: expected {request_id}, got {actual_id}")
    actual_function = frame[4]
    payload = frame[6:-4]
    if actual_function == 0:
        code = payload[0] if payload else None
        description = ERROR_CODES.get(code, "unknown device error")
        raise RuntimeError(f"Pulsar device error 0x{code:02X}: {description}" if code is not None else "Empty Pulsar error response")
    if function is not None and actual_function != function:
        raise ValueError(f"Pulsar function mismatch: expected 0x{function:02X}, got 0x{actual_function:02X}")
    if payload_length is not None and len(payload) != payload_length:
        raise ValueError(f"Pulsar payload length mismatch: expected {payload_length}, got {len(payload)}")
    return PulsarFrame(decoded_addr, actual_function, payload, actual_id, frame)


def read_channel_request(address: str, channel: int = 1, *, request_id: int = 0) -> bytes:
    if not 1 <= channel <= 32:
        raise ValueError("Pulsar channel must be in range 1..32")
    return build_request(address, 0x01, (1 << (channel - 1)).to_bytes(4, "little"), request_id=request_id)


def read_parameter_request(address: str, index: int, *, request_id: int = 0) -> bytes:
    if not 0 <= index <= 65535:
        raise ValueError("Pulsar parameter index must be in range 0..65535")
    return build_request(address, 0x0A, index.to_bytes(2, "little"), request_id=request_id)


def write_parameter_request(address: str, index: int, data: bytes, *, request_id: int = 0) -> bytes:
    if not 0 <= index <= 65535:
        raise ValueError("Pulsar parameter index must be in range 0..65535")
    if len(data) != 8:
        raise ValueError("Pulsar parameter value must be exactly 8 bytes (pad unused bytes with zero)")
    return build_request(address, 0x0B, index.to_bytes(2, "little") + data, request_id=request_id)


def read_clock_request(address: str, *, request_id: int = 0) -> bytes:
    return build_request(address, 0x04, request_id=request_id)


def _clock_bytes(text: str) -> bytes:
    if not re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}", text):
        raise ValueError("Clock must be YYYY-MM-DDTHH:MM:SS")
    try:
        value = datetime.strptime(text, "%Y-%m-%dT%H:%M:%S")
    except ValueError:
        raise ValueError("Clock must be YYYY-MM-DDTHH:MM:SS") from None
    if not 2000 <= value.year <= 2099:
        raise ValueError("Pulsar clock supports years 2000..2099")
    return bytes((value.year - 2000, value.month, value.day, value.hour, value.minute, value.second))


def write_clock_request(address: str, timestamp: str, *, request_id: int = 0) -> bytes:
    return build_request(address, 0x05, _clock_bytes(timestamp), request_id=request_id)


def decode_clock(data: bytes) -> str | None:
    if len(data) != 6:
        raise ValueError("Pulsar clock response must contain exactly 6 bytes")
    if data == b"\xFF" * 6:
        return None
    try:
        timestamp = datetime(2000 + data[0], *data[1:])
    except ValueError:
        raise ValueError("Invalid date/time in Pulsar response") from None
    return timestamp.isoformat(timespec="seconds")


def decode_value(data: bytes, fmt: str) -> int | float | str:
    formats = {
        "float": ("<f", 4), "s32": ("<i", 4), "u32": ("<I", 4),
        "f64": ("<d", 8), "u8": ("<B", 1), "u16": ("<H", 2),
    }
    if fmt == "raw":
        return data.hex(" ").upper()
    if fmt not in formats:
        raise ValueError(f"Unknown Pulsar value format: {fmt}")
    pack, size = formats[fmt]
    if len(data) != size:
        raise ValueError(f"Pulsar {fmt} value needs {size} bytes, received {len(data)}")
    value = struct.unpack(pack, data)[0]
    if isinstance(value, float) and not math.isfinite(value):
        raise ValueError("Pulsar value is NaN or infinite; check device format")
    return value


def parse_value_bytes(text: str) -> bytes:
    compact = text.replace(" ", "").replace(":", "")
    if not re.fullmatch(r"[0-9A-Fa-f]{16}", compact):
        raise ValueError("Pulsar parameter value must be 16 HEX digits / exactly 8 bytes")
    return bytes.fromhex(compact)


def validate_parameter_write_response(response: PulsarFrame) -> None:
    if response.function != 0x0B or response.payload != b"\x00\x00":
        raise ValueError("Unexpected Pulsar parameter write response")


def validate_clock_write_response(response: PulsarFrame) -> None:
    if response.function != 0x05 or response.payload != b"\x01\x00\x00\x00":
        raise ValueError("Pulsar clock write was not confirmed by device")
