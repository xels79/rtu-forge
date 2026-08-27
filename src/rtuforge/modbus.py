from __future__ import annotations

from dataclasses import dataclass

from .crc import has_valid_crc
from .formatting import hex_line
from .runtime_text import exception_name, function_name, tr


@dataclass(frozen=True)
class DecodedFrame:
    slave: int | None = None
    function: int | None = None
    crc_valid: bool | None = None
    exception_code: int | None = None
    byte_count: int | None = None
    data: bytes = b""
    registers: tuple[int, ...] = ()
    address: int | None = None
    value: int | None = None
    too_short: bool = False


def decode_response(frame: bytes) -> DecodedFrame:
    """Decode useful Modbus RTU response fields without ever rejecting raw RX."""
    slave = frame[0] if frame else None
    raw_function = frame[1] if len(frame) > 1 else None
    crc_valid = has_valid_crc(frame) if len(frame) >= 5 else None
    too_short = len(frame) < 5
    if raw_function is None:
        return DecodedFrame(slave=slave, crc_valid=crc_valid, too_short=too_short)

    is_exception = bool(raw_function & 0x80)
    function = raw_function & 0x7F if is_exception else raw_function
    exception_code = frame[2] if is_exception and len(frame) > 2 else None

    byte_count: int | None = None
    data = b""
    registers: tuple[int, ...] = ()
    address: int | None = None
    value: int | None = None
    payload_end = max(2, len(frame) - 2) if len(frame) >= 4 else len(frame)

    if not is_exception and function in {0x03, 0x04} and len(frame) > 2:
        byte_count = frame[2]
        data = frame[3:min(3 + byte_count, payload_end)]
        registers = tuple(
            int.from_bytes(data[index:index + 2], "big")
            for index in range(0, len(data) - 1, 2)
        )
    elif not is_exception and function == 0x06 and payload_end >= 6:
        address = int.from_bytes(frame[2:4], "big")
        value = int.from_bytes(frame[4:6], "big")
        data = frame[2:6]
    elif not is_exception and len(frame) > 2:
        data = frame[2:payload_end]

    return DecodedFrame(
        slave=slave,
        function=function,
        crc_valid=crc_valid,
        exception_code=exception_code,
        byte_count=byte_count,
        data=data,
        registers=registers,
        address=address,
        value=value,
        too_short=too_short,
    )


def format_decoded_response(
    decoded: DecodedFrame,
    uppercase: bool = True,
    language: str = "en",
) -> list[str]:
    if decoded.too_short:
        return [tr(language, "frame_short"), f"{tr(language, 'crc')}: N/A"]

    lines: list[str] = []
    if decoded.exception_code is not None:
        lines.append(tr(language, "modbus_exception"))
    if decoded.slave is not None:
        lines.append(f"{tr(language, 'slave')}: {decoded.slave}")
    if decoded.function is not None:
        name = function_name(language, decoded.function)
        suffix = f" {name}" if name and decoded.exception_code is None else ""
        lines.append(f"{tr(language, 'function')}: {decoded.function:02X}{suffix}")
    if decoded.exception_code is not None:
        name = exception_name(language, decoded.exception_code)
        suffix = f" {name}" if name else ""
        lines.append(f"{tr(language, 'exception')}: {decoded.exception_code:02X}{suffix}")
    else:
        if decoded.byte_count is not None:
            lines.append(f"{tr(language, 'byte_count')}: {decoded.byte_count}")
        if decoded.data:
            lines.append(f"{tr(language, 'data')}: {hex_line(decoded.data, uppercase)}")
        if decoded.registers:
            lines.append(f"{tr(language, 'registers')}:")
            lines.extend(f"  [{index}] 0x{value:04X} = {value}" for index, value in enumerate(decoded.registers))
        if decoded.address is not None:
            lines.append(f"{tr(language, 'address')}: 0x{decoded.address:04X} ({decoded.address})")
        if decoded.value is not None:
            lines.append(f"{tr(language, 'value')}:   0x{decoded.value:04X} ({decoded.value})")
    crc_text = "N/A" if decoded.crc_valid is None else "OK" if decoded.crc_valid else "BAD"
    lines.append(f"{tr(language, 'crc')}: {crc_text}")
    return lines
