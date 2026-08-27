from pathlib import Path

from rtuforge.config import load_config
from rtuforge.crc import append_crc
from rtuforge.scanner import build_probe
from rtuforge.transport import SerialTransport


class FakeSerial:
    def __init__(self, response: bytes):
        self.is_open = True
        self.response = bytearray(response)
        self.written = b""

    def reset_input_buffer(self):
        pass

    def write(self, data: bytes):
        self.written = data

    def flush(self):
        pass

    @property
    def in_waiting(self):
        return len(self.response)

    def read(self, size: int):
        result = bytes(self.response[:size])
        del self.response[:size]
        return result

    def close(self):
        self.is_open = False


def test_exchange_overrides_crc_and_timeout_without_changing_config():
    config = load_config(Path("config.ini"))
    config["runtime"]["crc_mode"] = "none"
    config["runtime"]["response_silence_ms"] = "0"
    original_timeout = config["connection"]["timeout_ms"]
    response = append_crc(bytes.fromhex("01 03 02 00 05"))
    fake_serial = FakeSerial(response)
    transport = SerialTransport(config)
    transport.serial = fake_serial
    probe = build_probe(1)

    exchange = transport.exchange(probe, timeout_ms=25, crc_mode_override="auto")

    assert exchange.tx == append_crc(probe)
    assert fake_serial.written == append_crc(probe)
    assert exchange.rx == response
    assert config["runtime"]["crc_mode"] == "none"
    assert config["connection"]["timeout_ms"] == original_timeout
