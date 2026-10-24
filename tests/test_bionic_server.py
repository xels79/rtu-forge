from collections import deque
from pathlib import Path

import pytest

from rtuforge.bionic_config import BionicSettings
from rtuforge.bionic_model import BionicModel
from rtuforge.bionic_modbus import build_default_bus
from rtuforge.bionic_server import ModbusSlaveServer, PortInUseError, SerialSlaveTransport
from rtuforge.crc import append_crc


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
