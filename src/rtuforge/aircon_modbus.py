"""Strict Modbus RTU transactions for ONOKOM HS-6-MB-B.

The official ONOKOM/WB templates use the documented addresses directly as
PDU addresses (for example Holding 5 is requested as address 0x0005).
"""

from __future__ import annotations

import threading
from datetime import datetime
from typing import Protocol

from .aircon_config import AirconSettings
from .aircon_state import AirconState
from .crc import append_crc, has_valid_crc


class Transport(Protocol):
    connected: bool

    def connect(self) -> None: ...
    def disconnect(self) -> None: ...
    def exchange(self, raw_frame: bytes, *, timeout_ms: int | None = None, crc_mode_override: str | None = None): ...


class ModbusError(RuntimeError):
    pass


class ModbusTimeout(ModbusError):
    pass


class ModbusCrcError(ModbusError):
    pass


def _request(slave: int, function: int, address: int, value: int) -> bytes:
    return bytes((slave, function)) + address.to_bytes(2, "big") + value.to_bytes(2, "big")


def read_request(slave: int, function: int, address: int, quantity: int = 1) -> bytes:
    if function not in {1, 3, 4}:
        raise ValueError("чтение поддерживает только FC01, FC03 и FC04")
    return _request(slave, function, address, quantity)


def write_coil_request(slave: int, address: int, enabled: bool) -> bytes:
    return _request(slave, 5, address, 0xFF00 if enabled else 0x0000)


def write_register_request(slave: int, address: int, value: int) -> bytes:
    if not 0 <= value <= 0xFFFF:
        raise ValueError("значение регистра вне диапазона UInt16")
    return _request(slave, 6, address, value)


def _validated_payload(response: bytes, slave: int, function: int) -> bytes:
    if not response:
        raise ModbusTimeout("нет ответа Modbus")
    if len(response) < 5 or not has_valid_crc(response):
        raise ModbusCrcError("ошибка CRC ответа")
    if response[0] != slave:
        raise ModbusError(f"неожиданный Modbus ID {response[0]}")
    if response[1] == function | 0x80:
        raise ModbusError(f"исключение Modbus {response[2]:02X} для FC{function:02X}")
    if response[1] != function:
        raise ModbusError(f"неожиданная функция FC{response[1]:02X}")
    return response[:-2]


def parse_bits(response: bytes, slave: int, quantity: int) -> list[bool]:
    payload = _validated_payload(response, slave, 1)
    expected_bytes = (quantity + 7) // 8
    if len(payload) != 3 + expected_bytes or payload[2] != expected_bytes:
        raise ModbusError("неверная длина ответа FC01")
    return [bool(payload[3 + index // 8] & (1 << (index % 8))) for index in range(quantity)]


def parse_registers(response: bytes, slave: int, function: int, quantity: int) -> list[int]:
    payload = _validated_payload(response, slave, function)
    byte_count = quantity * 2
    if len(payload) != 3 + byte_count or payload[2] != byte_count:
        raise ModbusError(f"неверная длина ответа FC{function:02X}")
    return [int.from_bytes(payload[3 + index * 2:5 + index * 2], "big") for index in range(quantity)]


def validate_write_response(request: bytes, response: bytes) -> None:
    payload = _validated_payload(response, request[0], request[1])
    if payload != request:
        raise ModbusError(f"ответ FC{request[1]:02X} не подтверждает записанное значение")


def signed(raw: int) -> int:
    return raw - 0x10000 if raw & 0x8000 else raw


class AirconModbusClient:
    """Single-owner transaction layer shared by polling and UI commands."""

    def __init__(self, transport: Transport, settings: AirconSettings):
        self.transport = transport
        self.settings = settings
        self.lock = threading.RLock()

    def connect(self) -> None:
        with self.lock:
            self.transport.connect()

    def disconnect(self) -> None:
        with self.lock:
            self.transport.disconnect()

    def _exchange(self, request: bytes) -> bytes:
        exchange = self.transport.exchange(
            request, timeout_ms=self.settings.timeout_ms, crc_mode_override="append"
        )
        return exchange.rx

    def read_bits(self, slave: int, address: int, quantity: int = 1) -> list[bool]:
        with self.lock:
            return parse_bits(self._exchange(read_request(slave, 1, address, quantity)), slave, quantity)

    def read_registers(self, slave: int, function: int, address: int, quantity: int = 1) -> list[int]:
        with self.lock:
            return parse_registers(
                self._exchange(read_request(slave, function, address, quantity)), slave, function, quantity
            )

    def write_coil(self, address: int, enabled: bool) -> None:
        request = write_coil_request(self.settings.slave_id, address, enabled)
        with self.lock:
            validate_write_response(request, self._exchange(request))

    def write_register(self, address: int, value: int) -> None:
        request = write_register_request(self.settings.slave_id, address, value)
        with self.lock:
            validate_write_response(request, self._exchange(request))

    def refresh(self, state: AirconState) -> AirconState:
        """Read gateway/AC link first, then all displayed values."""
        slave = self.settings.slave_id
        try:
            ac_online = self.read_bits(slave, 20)[0]
        except ModbusTimeout as exc:
            state.mark_offline(str(exc), timeout=True)
            state.clear_measurements()
            return state
        except ModbusCrcError as exc:
            state.mark_offline(str(exc), crc=True)
            state.clear_measurements()
            return state
        except (ModbusError, OSError, RuntimeError) as exc:
            state.mark_offline(str(exc))
            state.clear_measurements()
            return state

        state.gateway_online = True
        state.aircon_online = ac_online
        state.last_response_at = datetime.now()
        state.last_error = None
        if not ac_online:
            state.fresh = False
            state.clear_measurements()
            self._read_humidity(state)
            return state

        try:
            state.power = self.read_bits(slave, 1)[0]
            operation = self.read_registers(slave, 3, 1, 3)
            climate = self.read_registers(slave, 3, 5, 3)
            state.mode = operation[0]
            state.active_mode = operation[1]
            state.room_temperature_c = signed(operation[2]) * 0.01
            state.target_temperature_c = signed(climate[0]) * 0.01
            state.thermostat = climate[1]
            state.fan = climate[2]
            state.exchanger_temperature_c = signed(self.read_registers(slave, 3, 23)[0]) * 0.01
            state.fresh = True
            self._read_humidity(state)
        except ModbusTimeout as exc:
            state.fresh = False
            state.last_error = str(exc)
            state.exchange_error_count += 1
            state.timeout_count += 1
            state.clear_measurements()
        except ModbusCrcError as exc:
            state.fresh = False
            state.last_error = str(exc)
            state.exchange_error_count += 1
            state.crc_error_count += 1
            state.clear_measurements()
        except (ModbusError, OSError, RuntimeError) as exc:
            state.fresh = False
            state.last_error = str(exc)
            state.exchange_error_count += 1
            state.clear_measurements()
        return state

    def _read_humidity(self, state: AirconState) -> None:
        if not self.settings.humidity_enabled:
            state.humidity_percent = None
            state.humidity_updated_at = None
            return
        function = 3 if self.settings.humidity_register_type == "holding" else 4
        try:
            raw = self.read_registers(
                self.settings.humidity_slave_id, function, self.settings.humidity_address
            )[0]
            state.humidity_percent = signed(raw) * self.settings.humidity_scale
            state.humidity_updated_at = datetime.now()
        except ModbusTimeout:
            state.exchange_error_count += 1
            state.timeout_count += 1
        except ModbusCrcError:
            state.exchange_error_count += 1
            state.crc_error_count += 1
        except (ModbusError, OSError, RuntimeError):
            # A humidity sensor failure must not turn a healthy AC gateway offline.
            state.exchange_error_count += 1


class DemoTransport:
    """Deterministic in-process Modbus gateway; never touches serial hardware."""

    def __init__(self, slave_id: int = 1, humidity_slave_id: int = 2):
        self.connected = False
        self.slave_id = slave_id
        self.humidity_slave_id = humidity_slave_id
        self.coils = {1: True, 20: True}
        self.registers = {1: 2, 2: 2, 3: 2560, 5: 2300, 6: 2, 7: 0, 23: 1240}
        self.humidity_raw = 485
        self.requests: list[bytes] = []

    def connect(self) -> None:
        self.connected = True

    def disconnect(self) -> None:
        self.connected = False

    def exchange(self, raw_frame: bytes, **_: object):
        from .transport import Exchange

        if not self.connected:
            raise RuntimeError("нет подключения")
        self.requests.append(raw_frame)
        slave, function = raw_frame[:2]
        address = int.from_bytes(raw_frame[2:4], "big")
        value = int.from_bytes(raw_frame[4:6], "big")
        if function == 1:
            bits = [self.coils.get(address + offset, False) for offset in range(value)]
            packed = sum(int(bit) << index for index, bit in enumerate(bits))
            payload = bytes((slave, 1, 1, packed))
        elif function in {3, 4}:
            if slave == self.humidity_slave_id:
                values = [self.humidity_raw]
            else:
                values = [self.registers.get(address + offset, 0) for offset in range(value)]
            data = b"".join(item.to_bytes(2, "big") for item in values)
            payload = bytes((slave, function, len(data))) + data
        elif function == 5:
            self.coils[address] = value == 0xFF00
            if address == 1:
                self.registers[2] = self.registers[1] if self.coils[address] else 0
            payload = raw_frame
        elif function == 6:
            self.registers[address] = value
            if address == 1:
                self.registers[2] = value if self.coils.get(1) else 0
            payload = raw_frame
        else:
            payload = bytes((slave, function | 0x80, 1))
        return Exchange(append_crc(raw_frame), append_crc(payload), 0.1)
