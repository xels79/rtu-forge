from __future__ import annotations

from dataclasses import dataclass

from .crc import has_valid_crc
from .formatting import hex_line


FUNCTION_NAMES: dict[int, str] = {
    0x01: "Read Coils",
    0x02: "Read Discrete Inputs",
    0x03: "Read Holding Registers",
    0x04: "Read Input Registers",
    0x05: "Write Single Coil",
    0x06: "Write Single Register",
    0x0F: "Write Multiple Coils",
    0x10: "Write Multiple Registers",
}

EXCEPTION_NAMES: dict[int, str] = {
    0x01: "Illegal Function",
    0x02: "Illegal Data Address",
    0x03: "Illegal Data Value",
    0x04: "Slave Device Failure",
    0x05: "Acknowledge",
    0x06: "Slave Device Busy",
    0x08: "Memory Parity Error",
    0x0A: "Gateway Path Unavailable",
    0x0B: "Gateway Target Device Failed to Respond",
}


@dataclass(frozen=True)
class DecodedFrame:
    slave: int | None = None
    function: int | None = None
    function_name: str | None = None
    crc_valid: bool | None = None
    exception_code: int | None = None
    exception_name: str | None = None
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
    function_name = FUNCTION_NAMES.get(function)
    exception_code = frame[2] if is_exception and len(frame) > 2 else None
    exception_name = EXCEPTION_NAMES.get(exception_code) if exception_code is not None else None

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
        function_name=function_name,
        crc_valid=crc_valid,
        exception_code=exception_code,
        exception_name=exception_name,
        byte_count=byte_count,
        data=data,
        registers=registers,
        address=address,
        value=value,
        too_short=too_short,
    )


def format_decoded_response(decoded: DecodedFrame, uppercase: bool = True) -> list[str]:
    if decoded.too_short:
        return ["Frame too short for Modbus decoding", "CRC: N/A"]

    lines: list[str] = []
    if decoded.exception_code is not None:
        lines.append("Modbus exception")
    if decoded.slave is not None:
        lines.append(f"Slave: {decoded.slave}")
    if decoded.function is not None:
        suffix = f" {decoded.function_name}" if decoded.function_name and decoded.exception_code is None else ""
        lines.append(f"Function: {decoded.function:02X}{suffix}")
    if decoded.exception_code is not None:
        suffix = f" {decoded.exception_name}" if decoded.exception_name else ""
        lines.append(f"Exception: {decoded.exception_code:02X}{suffix}")
    else:
        if decoded.byte_count is not None:
            lines.append(f"Byte count: {decoded.byte_count}")
        if decoded.data:
            lines.append(f"Data: {hex_line(decoded.data, uppercase)}")
        if decoded.registers:
            lines.append("Registers:")
            lines.extend(f"  [{index}] 0x{value:04X} = {value}" for index, value in enumerate(decoded.registers))
        if decoded.address is not None:
            lines.append(f"Address: 0x{decoded.address:04X} ({decoded.address})")
        if decoded.value is not None:
            lines.append(f"Value:   0x{decoded.value:04X} ({decoded.value})")
    crc_text = "N/A" if decoded.crc_valid is None else "OK" if decoded.crc_valid else "BAD"
    lines.append(f"CRC: {crc_text}")
    return lines
