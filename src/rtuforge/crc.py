from __future__ import annotations


def crc16_modbus(data: bytes) -> int:
    crc = 0xFFFF
    for byte in data:
        crc ^= byte
        for _ in range(8):
            if crc & 1:
                crc = (crc >> 1) ^ 0xA001
            else:
                crc >>= 1
    return crc


def append_crc(data: bytes) -> bytes:
    crc = crc16_modbus(data)
    return data + bytes((crc & 0xFF, (crc >> 8) & 0xFF))


def has_valid_crc(frame: bytes) -> bool:
    if len(frame) < 4:
        return False
    expected = crc16_modbus(frame[:-2])
    received = frame[-2] | (frame[-1] << 8)
    return expected == received


def apply_crc_mode(frame: bytes, mode: str) -> bytes:
    mode = mode.lower()
    if mode == "none":
        return frame
    if mode == "append":
        return append_crc(frame)
    if mode == "auto":
        return frame if has_valid_crc(frame) else append_crc(frame)
    raise ValueError(f"Unknown crc_mode: {mode}")
