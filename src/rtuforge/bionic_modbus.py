"""Protocol-faithful Modbus RTU slaves used by Bionic Immitator."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

from .bionic_model import BionicModel
from .bionic_ponics import PONICS_DOSING_REGISTERS, PONICS_REGISTER_COUNT, PONICS_WRITABLE_SETTINGS
from .crc import append_crc, has_valid_crc


ILLEGAL_FUNCTION = 1
ILLEGAL_ADDRESS = 2
ILLEGAL_VALUE = 3


def _u16(payload: bytes, offset: int) -> int:
    return int.from_bytes(payload[offset : offset + 2], "big")


def _bits(values: list[bool]) -> bytes:
    packed = bytearray((len(values) + 7) // 8)
    for index, value in enumerate(values):
        if value:
            packed[index // 8] |= 1 << (index % 8)
    return bytes(packed)


def exception(slave: int, function: int, code: int) -> bytes:
    return append_crc(bytes((slave, function | 0x80, code)))


class ModbusDevice:
    def __init__(self, address: int) -> None:
        self.address = address
        self.online = True

    def handle_pdu(self, function: int, data: bytes) -> bytes | int:
        return ILLEGAL_FUNCTION


class RelayDevice(ModbusDevice):
    def __init__(self, address: int, model: BionicModel, channels: int = 32) -> None:
        super().__init__(address)
        self.model = model
        self.channels = channels

    def handle_pdu(self, function: int, data: bytes) -> bytes | int:
        if function in {1, 2}:
            if len(data) != 4:
                return ILLEGAL_VALUE
            start, count = _u16(data, 0), _u16(data, 2)
            if count < 1 or start + count > self.channels:
                return ILLEGAL_ADDRESS
            values = [self.model.relays[index] for index in range(start, start + count)]
            packed = _bits(values)
            return bytes((len(packed),)) + packed
        if function == 5:
            if len(data) != 4:
                return ILLEGAL_VALUE
            address, value = _u16(data, 0), _u16(data, 2)
            if address == 0x00FF and value == 0:
                for channel in range(1, self.channels + 1):
                    self.model.set_relay(channel, False)
                return data
            if address >= self.channels or value not in {0, 0xFF00}:
                return ILLEGAL_ADDRESS if address >= self.channels else ILLEGAL_VALUE
            self.model.set_relay(address + 1, value == 0xFF00)
            return data
        if function == 15:
            if len(data) < 5:
                return ILLEGAL_VALUE
            start, count, byte_count = _u16(data, 0), _u16(data, 2), data[4]
            if count < 1 or start + count > self.channels:
                return ILLEGAL_ADDRESS
            if byte_count != (count + 7) // 8 or len(data) != 5 + byte_count:
                return ILLEGAL_VALUE
            for offset in range(count):
                self.model.set_relay(start + offset + 1, bool(data[5 + offset // 8] & (1 << (offset % 8))))
            return data[:4]
        return ILLEGAL_FUNCTION


class AnalogOutputDevice(ModbusDevice):
    """Waveshare AO 8CH(B): holding registers 0..7 in mV."""

    def __init__(self, address: int, on_change: Callable[[int, int], None] | None = None) -> None:
        super().__init__(address)
        self.registers = [0] * 8
        self.on_change = on_change or (lambda _channel, _value: None)

    def handle_pdu(self, function: int, data: bytes) -> bytes | int:
        if function == 3:
            if len(data) != 4:
                return ILLEGAL_VALUE
            start, count = _u16(data, 0), _u16(data, 2)
            if count < 1 or start + count > 8:
                return ILLEGAL_ADDRESS
            values = b"".join(value.to_bytes(2, "big") for value in self.registers[start : start + count])
            return bytes((len(values),)) + values
        if function == 6:
            if len(data) != 4:
                return ILLEGAL_VALUE
            register, value = _u16(data, 0), _u16(data, 2)
            if register >= 8:
                return ILLEGAL_ADDRESS
            if value > 10000:
                return ILLEGAL_VALUE
            self.registers[register] = value
            self.on_change(register + 1, value)
            return data
        if function == 16:
            if len(data) < 5:
                return ILLEGAL_VALUE
            start, count, byte_count = _u16(data, 0), _u16(data, 2), data[4]
            if count < 1 or start + count > 8:
                return ILLEGAL_ADDRESS
            if byte_count != count * 2 or len(data) != 5 + byte_count:
                return ILLEGAL_VALUE
            values = [_u16(data, 5 + index * 2) for index in range(count)]
            if any(value > 10000 for value in values):
                return ILLEGAL_VALUE
            self.registers[start : start + count] = values
            for index, value in enumerate(values, start + 1):
                self.on_change(index, value)
            return data[:4]
        return ILLEGAL_FUNCTION


class AnalogInputDevice(ModbusDevice):
    """Waveshare AI: FC04 input registers 0..7 in microamps."""

    def __init__(self, address: int, model: BionicModel) -> None:
        super().__init__(address)
        self.model = model

    def handle_pdu(self, function: int, data: bytes) -> bytes | int:
        if function != 4:
            return ILLEGAL_FUNCTION
        if len(data) != 4:
            return ILLEGAL_VALUE
        start, count = _u16(data, 0), _u16(data, 2)
        if count < 1 or start + count > 8:
            return ILLEGAL_ADDRESS
        values = [self.model.analog_raw(index + 1) for index in range(start, start + count)]
        payload = b"".join(value.to_bytes(2, "big") for value in values)
        return bytes((len(payload),)) + payload


class PonicsDevice(ModbusDevice):
    """Ponics Pilot 32 holding registers at PDU addresses 0..41."""

    def __init__(self, address: int, model: BionicModel) -> None:
        super().__init__(address)
        self.model = model

    def handle_pdu(self, function: int, data: bytes) -> bytes | int:
        ponics = self.model.ponics
        if function == 3:
            if len(data) != 4:
                ponics.note_error()
                return ILLEGAL_VALUE
            start, count = _u16(data, 0), _u16(data, 2)
            if count < 1 or start + count > PONICS_REGISTER_COUNT:
                ponics.note_error(address=True)
                return ILLEGAL_ADDRESS
            values = ponics.registers()[start : start + count]
            payload = b"".join(value.to_bytes(2, "big") for value in values)
            ponics.note_read(start, count)
            return bytes((len(payload),)) + payload
        if function == 6:
            if len(data) != 4:
                ponics.note_error()
                return ILLEGAL_VALUE
            register, value = _u16(data, 0), _u16(data, 2)
            if register not in PONICS_WRITABLE_SETTINGS and register not in PONICS_DOSING_REGISTERS:
                ponics.note_error(address=True)
                return ILLEGAL_ADDRESS
            try:
                ponics.write(register, value)
            except (ValueError, RuntimeError):
                ponics.note_error()
                return ILLEGAL_VALUE
            ponics.requests += 1
            ponics.responses += 1
            return data
        if function == 16:
            if len(data) < 5:
                ponics.note_error()
                return ILLEGAL_VALUE
            start, count, byte_count = _u16(data, 0), _u16(data, 2), data[4]
            if count < 1 or byte_count != count * 2 or len(data) != 5 + byte_count:
                ponics.note_error()
                return ILLEGAL_VALUE
            writable = PONICS_WRITABLE_SETTINGS | frozenset(PONICS_DOSING_REGISTERS)
            if start + count > PONICS_REGISTER_COUNT or any(
                address not in writable for address in range(start, start + count)
            ):
                ponics.note_error(address=True)
                return ILLEGAL_ADDRESS
            values = [_u16(data, 5 + index * 2) for index in range(count)]
            try:
                for address, value in zip(range(start, start + count), values):
                    ponics._validate(address, value)
                    if address in PONICS_DOSING_REGISTERS and ponics.doser_faults[PONICS_DOSING_REGISTERS[address]]:
                        raise RuntimeError("doser fault")
                for address, value in zip(range(start, start + count), values):
                    ponics.write(address, value, source="Modbus FC10")
            except (ValueError, RuntimeError):
                ponics.note_error()
                return ILLEGAL_VALUE
            ponics.requests += 1
            ponics.responses += 1
            return data[:4]
        ponics.note_error()
        return ILLEGAL_FUNCTION


class IddDevice(ModbusDevice):
    """Register subset used by the firmware's IDD222M21E driver."""

    def __init__(self, address: int, model: BionicModel, drive_id: str) -> None:
        super().__init__(address)
        self.model = model
        self.drive_id = drive_id
        self.configuration = self.model.drives[drive_id].configuration

    def _register(self, address: int) -> int | None:
        drive = self.model.drives[self.drive_id]
        values = {
            1: round(drive.setpoint_hz * 10),
            2: round(drive.actual_hz * 10),
            3: round(drive.actual_hz * 2),
            4: round(drive.motor_hours * 10),
            27: drive.fault,
            28: 1 if drive.actual_hz > 0.1 else 0,
            **self.configuration,
        }
        return values.get(address)

    def handle_pdu(self, function: int, data: bytes) -> bytes | int:
        drive = self.model.drives[self.drive_id]
        if function == 3:
            if len(data) != 4:
                return ILLEGAL_VALUE
            start, count = _u16(data, 0), _u16(data, 2)
            values = [self._register(start + offset) for offset in range(count)]
            if count < 1 or any(value is None for value in values):
                return ILLEGAL_ADDRESS
            payload = b"".join(int(value).to_bytes(2, "big") for value in values)
            return bytes((len(payload),)) + payload
        if function == 6:
            if len(data) != 4:
                return ILLEGAL_VALUE
            register, value = _u16(data, 0), _u16(data, 2)
            if register == 0x2000:
                if value == 1:
                    drive.run_register = False
                elif value == 2:
                    drive.run_register = True
                elif value == 0x10:
                    drive.fault = 0
                else:
                    return ILLEGAL_VALUE
            elif register == 0x2001:
                if not 200 <= value <= 500:
                    return ILLEGAL_VALUE
                drive.setpoint_hz = value / 10.0
            else:
                return ILLEGAL_ADDRESS
            return data
        return ILLEGAL_FUNCTION


@dataclass
class ModbusBus:
    devices: dict[int, ModbusDevice] = field(default_factory=dict)

    def add(self, device: ModbusDevice) -> None:
        if not 1 <= device.address <= 247:
            raise ValueError("Modbus address must be in range 1..247")
        if device.address in self.devices:
            raise ValueError(f"Duplicate Modbus address: {device.address}")
        self.devices[device.address] = device

    def handle(self, frame: bytes) -> bytes:
        if len(frame) < 4:
            return b""
        if not has_valid_crc(frame):
            device = self.devices.get(frame[0])
            if isinstance(device, PonicsDevice):
                device.model.ponics.requests += 1
                device.model.ponics.crc_errors += 1
            return b""
        slave, function = frame[0], frame[1]
        device = self.devices.get(slave)
        if device is None or not device.online or (
            isinstance(device, PonicsDevice) and not device.model.ponics.respond
        ):
            return b""
        result = device.handle_pdu(function, frame[2:-2])
        if isinstance(result, int):
            return exception(slave, function, result)
        return append_crc(bytes((slave, function)) + result)


def expected_frame_length(buffer: bytes) -> int | None:
    if len(buffer) < 2:
        return None
    function = buffer[1]
    if function in {1, 2, 3, 4, 5, 6}:
        return 8
    if function in {15, 16}:
        return 9 + buffer[6] if len(buffer) >= 7 else None
    return 8


def build_default_bus(model: BionicModel, addresses: object) -> ModbusBus:
    bus = ModbusBus()
    bus.add(RelayDevice(addresses.relay_address, model))
    bus.add(AnalogOutputDevice(addresses.ao1_address, lambda channel, value: model.set_analog_output(addresses.ao1_address, channel, value)))
    bus.add(AnalogOutputDevice(addresses.ao2_address, lambda channel, value: model.set_analog_output(addresses.ao2_address, channel, value)))
    bus.add(AnalogOutputDevice(addresses.ao3_address, lambda channel, value: model.set_analog_output(addresses.ao3_address, channel, value)))
    bus.add(PonicsDevice(addresses.ponics_address, model))
    bus.add(AnalogInputDevice(addresses.ai_address, model))
    bus.add(IddDevice(addresses.hp1_address, model, "hp1"))
    bus.add(IddDevice(addresses.hp2_address, model, "hp2"))
    return bus
