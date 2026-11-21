"""Waveshare 0-10 V Modbus AO: holding registers 0..3 in millivolts."""
from __future__ import annotations

from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from .crc import has_valid_crc


def check_address(value: int) -> int:
    if not 1 <= value <= 247:
        raise ValueError("Modbus ID должен быть 1..247")
    return value


def check_channel(value: int) -> int:
    if not 1 <= value <= 4:
        raise ValueError("Канал AO должен быть 1..4")
    return value


def percent_to_raw(value: str) -> int:
    try:
        percent = Decimal(value.replace(",", "."))
    except (InvalidOperation, AttributeError):
        raise ValueError("Яркость должна быть числом 0..100%") from None
    if not percent.is_finite() or not Decimal("0") <= percent <= Decimal("100"):
        raise ValueError("Яркость должна быть числом 0..100%")
    return int((percent * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def display_level(raw: int) -> str:
    if not 0 <= raw <= 10000:
        raise RuntimeError(f"Некорректное значение AO: {raw} мВ")
    return f"{raw / 100:.2f}% / {raw / 1000:.3f} В"


def build_read(address: int, channel: int) -> bytes:
    return bytes((check_address(address), 3, 0, check_channel(channel) - 1, 0, 1))


def build_write(address: int, channel: int, raw: int) -> bytes:
    check_address(address)
    check_channel(channel)
    if not 0 <= raw <= 10000:
        raise ValueError("AO 0..10 В: нужно 0..10000 мВ")
    return bytes((address, 6, 0, channel - 1, raw >> 8, raw & 255))


def _checked(request: bytes, response: bytes, function: int) -> bytes:
    if not response:
        raise RuntimeError("Нет ответа от модуля света")
    if len(response) < 5 or not has_valid_crc(response):
        raise RuntimeError("Ошибка CRC или длины Modbus-ответа AO")
    if response[0] != request[0]:
        raise RuntimeError("Ответ другого Modbus-адреса")
    if response[1] == (function | 128):
        if len(response) != 5:
            raise RuntimeError("Неверный Modbus exception")
        raise RuntimeError(f"Modbus exception 0x{response[2]:02X}")
    if response[1] != function:
        raise RuntimeError("Неожиданная функция ответа AO")
    return response


def parse_read(request: bytes, response: bytes) -> int:
    _checked(request, response, 3)
    if len(response) != 7 or response[2] != 2:
        raise RuntimeError("AO FC03: некорректная длина/byte count")
    raw = int.from_bytes(response[3:5], "big")
    display_level(raw)
    return raw


def check_write(request: bytes, response: bytes) -> None:
    _checked(request, response, 6)
    if len(response) != 8 or response[:6] != request:
        raise RuntimeError("AO FC06: неверное эхо записи")
