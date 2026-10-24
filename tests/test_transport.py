from pathlib import Path

from rtuforge.config import load_config
from rtuforge.crc import append_crc, has_valid_crc
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
        return len(data)

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


def test_exchange_append_override_handles_scan_probe_crc_collision():
    config = load_config(Path("config.ini"))
    config["runtime"]["crc_mode"] = "auto"
    config["runtime"]["response_silence_ms"] = "0"
    fake_serial = FakeSerial(b"")
    transport = SerialTransport(config)
    transport.serial = fake_serial
    probe = build_probe(1, 0x03, 0xBF62)
    assert has_valid_crc(probe)

    exchange = transport.exchange(probe, timeout_ms=1, crc_mode_override="append")

    assert exchange.tx == append_crc(probe)
    assert len(exchange.tx) == 8
    assert fake_serial.written == append_crc(probe)


def test_connect_sets_read_and_write_timeouts(monkeypatch):
    config = load_config(Path("config.ini"))
    config["connection"]["timeout_ms"] = "25"
    created = []

    class OpeningSerial:
        def __init__(self, **kwargs):
            created.append((self, kwargs))
            self.is_open = False
            self.port = None

        def open(self):
            self.is_open = True

        def close(self):
            self.is_open = False

    monkeypatch.setattr("rtuforge.transport.serial.Serial", OpeningSerial)
    transport = SerialTransport(config)

    transport.connect()

    assert transport.connected
    _, kwargs = created[0]
    assert kwargs["port"] is None
    assert kwargs["timeout"] == 0.025
    assert kwargs["write_timeout"] == 0.025


def test_exchange_disconnects_after_serial_write_error():
    import serial

    config = load_config(Path("config.ini"))
    fake_serial = FakeSerial(b"")

    def fail_write(data: bytes):
        raise serial.SerialTimeoutException("write timeout")

    fake_serial.write = fail_write
    transport = SerialTransport(config)
    transport.serial = fake_serial

    try:
        transport.exchange(build_probe(1), timeout_ms=1, crc_mode_override="append")
    except serial.SerialTimeoutException:
        pass
    else:
        raise AssertionError("expected SerialTimeoutException")

    assert not transport.connected
    assert transport.serial is None
