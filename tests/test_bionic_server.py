from collections import deque
from pathlib import Path

import pytest

from rtuforge.bionic_config import BionicSettings
from rtuforge.bionic_model import BionicModel
from rtuforge.bionic_modbus import build_default_bus
from rtuforge.bionic_pulsar import PulsarWaterMeterSlave
from rtuforge.bionic_server import (
    ModbusSlaveServer, PortInUseError, SerialSlaveTransport,
    Usb1RequestDispatcher,
)
from rtuforge.crc import append_crc
from rtuforge.pulsar_protocol import parse_response, read_channel_request


class FakeSerial:
    def __init__(self, incoming: bytes, **kwargs):
        self.incoming = deque(incoming)
        self.written = bytearray()
        self.closed = False

    def read(self, size):
        return bytes([self.incoming.popleft()]) if self.incoming else b""

    def write(self, payload):
        self.written.extend(payload)
        return len(payload)

    def flush(self):
        pass

    def close(self):
        self.closed = True


def test_serial_slave_transport_is_injected_and_processes_a_frame(tmp_path: Path):
    frame = append_crc(bytes.fromhex("01 0F 00 15 00 01 01 01"))
    fake = FakeSerial(frame)
    transport = SerialSlaveTransport("COM7", 9600, "N", 1, serial_factory=lambda **kwargs: fake)
    server = ModbusSlaveServer(build_default_bus(BionicModel(), BionicSettings()), transport, tmp_path / "port.lock")
    server.start()
    for _ in range(100):
        if fake.written:
            break
        import time
        time.sleep(0.001)
    server.stop()
    assert bytes(fake.written) == append_crc(bytes.fromhex("01 0F 00 15 00 01"))
    assert not (tmp_path / "port.lock").exists()
    assert fake.closed


def test_lock_prevents_two_server_owners(tmp_path: Path):
    lock = tmp_path / "port.lock"
    lock.write_text("123")
    transport = SerialSlaveTransport("COM7", 9600, "N", 1, serial_factory=lambda **kwargs: FakeSerial(b""))
    server = ModbusSlaveServer(build_default_bus(BionicModel(), BionicSettings()), transport, lock)
    with pytest.raises(PortInUseError, match="уже занят"):
        server.start()


def _feed(dispatcher: Usb1RequestDispatcher, payload: bytes) -> list[bytes]:
    return [response for byte in payload for response in dispatcher.feed(bytes((byte,)))]


def test_one_dispatcher_processes_modbus_pulsar_modbus_in_order():
    model = BionicModel()
    model.water_meter.total_l = 1250.0
    settings = BionicSettings()
    bus = build_default_bus(model, settings)
    dispatcher = Usb1RequestDispatcher(
        bus, PulsarWaterMeterSlave(model, "17440707", enabled=True),
    )
    modbus_on = append_crc(bytes.fromhex("01 0F 00 15 00 01 01 01"))
    pulsar = read_channel_request("17440707", request_id=0x1234)
    modbus_off = append_crc(bytes.fromhex("01 0F 00 15 00 01 01 00"))

    responses = _feed(dispatcher, modbus_on + pulsar + modbus_off)

    assert responses[0] == append_crc(bytes.fromhex("01 0F 00 15 00 01"))
    parsed = parse_response(
        responses[1], address="17440707", function=1,
        request_id=0x1234, payload_length=4,
    )
    assert parsed.payload == bytes.fromhex("00 00 A0 3F")
    assert responses[2] == append_crc(bytes.fromhex("01 0F 00 15 00 01"))


def test_single_serial_owner_processes_modbus_pulsar_modbus(tmp_path: Path):
    model = BionicModel()
    model.water_meter.total_l = 1250.0
    modbus_on = append_crc(bytes.fromhex("01 0F 00 15 00 01 01 01"))
    pulsar_request = read_channel_request("17440707")
    modbus_off = append_crc(bytes.fromhex("01 0F 00 15 00 01 01 00"))
    fake = FakeSerial(modbus_on + pulsar_request + modbus_off)
    opens = 0

    def serial_factory(**kwargs):
        nonlocal opens
        opens += 1
        return fake

    transport = SerialSlaveTransport(
        "COM7", 9600, "N", 1, serial_factory=serial_factory,
    )
    server = ModbusSlaveServer(
        build_default_bus(model, BionicSettings()), transport,
        tmp_path / "port.lock",
        PulsarWaterMeterSlave(model, "17440707", enabled=True),
    )
    server.start()
    for _ in range(100):
        if len(fake.written) == 30:
            break
        import time
        time.sleep(0.001)
    server.stop()

    modbus_response = append_crc(bytes.fromhex("01 0F 00 15 00 01"))
    assert bytes(fake.written[:8]) == modbus_response
    assert parse_response(
        bytes(fake.written[8:22]), address="17440707",
        function=1, request_id=0, payload_length=4,
    ).payload == bytes.fromhex("00 00 A0 3F")
    assert bytes(fake.written[22:]) == modbus_response
    assert opens == 1


def test_enabled_pulsar_does_not_change_unrelated_modbus_response():
    request = append_crc(bytes.fromhex("01 01 00 00 00 01"))
    baseline = build_default_bus(BionicModel(), BionicSettings()).handle(request)
    model = BionicModel()
    dispatcher = Usb1RequestDispatcher(
        build_default_bus(model, BionicSettings()),
        PulsarWaterMeterSlave(model, "17440707", enabled=True),
    )
    assert _feed(dispatcher, request) == [baseline]


def test_disabled_pulsar_consumes_request_without_responding():
    model = BionicModel()
    dispatcher = Usb1RequestDispatcher(
        build_default_bus(model, BionicSettings()),
        PulsarWaterMeterSlave(model, "17440707", enabled=False),
    )
    assert _feed(dispatcher, read_channel_request("17440707")) == []


@pytest.mark.parametrize("damage", ("crc", "address", "length"))
def test_bad_pulsar_frame_does_not_respond_or_break_next_modbus_exchange(damage):
    model = BionicModel()
    dispatcher = Usb1RequestDispatcher(
        build_default_bus(model, BionicSettings()),
        PulsarWaterMeterSlave(model, "17440707", enabled=True),
    )
    request = bytearray(read_channel_request("17440707"))
    if damage == "crc":
        request[-1] ^= 1
    elif damage == "address":
        request = bytearray(read_channel_request("17440708"))
    else:
        request[5] = 13

    assert _feed(dispatcher, bytes(request)) == []
    assert dispatcher.finish_frame() == []

    modbus = append_crc(bytes.fromhex("01 01 00 00 00 01"))
    expected = build_default_bus(BionicModel(), BionicSettings()).handle(modbus)
    assert _feed(dispatcher, modbus) == [expected]


def test_ambiguous_prefix_waits_for_crc_or_serial_frame_boundary():
    model = BionicModel()
    bus = build_default_bus(model, BionicSettings())
    dispatcher = Usb1RequestDispatcher(
        bus, PulsarWaterMeterSlave(model, "01060001", enabled=True),
    )
    # As Pulsar: BCD address 01060001, function 01, length 0E.
    # As Modbus: slave 1, FC06, register 1, value 0x010E, plus CRC.
    modbus = append_crc(bytes.fromhex("01 06 00 01 01 0E"))
    expected = build_default_bus(BionicModel(), BionicSettings()).handle(modbus)

    assert _feed(dispatcher, modbus) == []
    assert dispatcher.finish_frame() == [expected]
