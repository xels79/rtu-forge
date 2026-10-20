from pathlib import Path

import pytest

from rtuforge.bionic_config import BionicSettings, changed, load_settings, save_settings
from rtuforge.bionic_model import BionicModel
from rtuforge.bionic_modbus import build_default_bus
from rtuforge.bionic_sensor_bridge import SensorRelayBridge
from rtuforge.crc import append_crc, has_valid_crc
from rtuforge.transport import Exchange


def request(bus, payload: str) -> bytes:
    response = bus.handle(append_crc(bytes.fromhex(payload)))
    assert has_valid_crc(response)
    return response[:-2]


def test_relay_fc0f_write_and_fc01_readback():
    model = BionicModel()
    bus = build_default_bus(model, BionicSettings())
    assert request(bus, "01 0F 00 08 00 06 01 25") == bytes.fromhex("01 0F 00 08 00 06")
    assert model.relays[8:14] == [True, False, True, False, False, True]
    assert request(bus, "01 01 00 08 00 06") == bytes.fromhex("01 01 01 25")


def test_ao_fc03_fc06_fc10_and_illegal_address():
    bus = build_default_bus(BionicModel(), BionicSettings())
    assert request(bus, "02 06 00 00 13 88") == bytes.fromhex("02 06 00 00 13 88")
    assert request(bus, "02 10 00 01 00 02 04 03 E8 27 10") == bytes.fromhex("02 10 00 01 00 02")
    assert request(bus, "02 03 00 00 00 03") == bytes.fromhex("02 03 06 13 88 03 E8 27 10")
    assert request(bus, "02 03 00 08 00 01") == bytes.fromhex("02 83 02")


def test_ai_fc04_uses_physical_pressure_and_rejects_fc03():
    model = BionicModel()
    model.low_pressure_bar = 3
    model.high_pressure_bar = 50
    bus = build_default_bus(model, BionicSettings())
    assert request(bus, "06 04 00 00 00 02") == bytes.fromhex("06 04 04 2E E0 2E E0")
    assert request(bus, "06 03 00 00 00 01") == bytes.fromhex("06 83 01")


def test_idd_registers_and_write_does_not_fake_run_feedback():
    model = BionicModel()
    bus = build_default_bus(model, BionicSettings())
    assert request(bus, "07 06 20 01 01 A4") == bytes.fromhex("07 06 20 01 01 A4")
    assert model.drives["hp1"].setpoint_hz == 42
    assert request(bus, "07 03 00 1C 00 01") == bytes.fromhex("07 03 02 00 00")
    request(bus, "07 06 20 00 00 02")
    assert model.drives["hp1"].run_register
    assert request(bus, "07 03 00 1C 00 01") == bytes.fromhex("07 03 02 00 00")


def test_bad_crc_unknown_and_offline_device_time_out():
    bus = build_default_bus(BionicModel(), BionicSettings())
    assert bus.handle(bytes.fromhex("01 01 00 00 00 01 00 00")) == b""
    assert bus.handle(append_crc(bytes.fromhex("09 03 00 00 00 01"))) == b""
    bus.devices[1].online = False
    assert bus.handle(append_crc(bytes.fromhex("01 01 00 00 00 01"))) == b""


def test_settings_roundtrip_validation_and_no_implicit_file(tmp_path: Path):
    path = tmp_path / "bionic-immitator.ini"
    assert load_settings(path) == BionicSettings()
    assert not path.exists()
    settings = changed(BionicSettings(), "hp1_address", "17")
    save_settings(path, settings)
    assert load_settings(path) == settings
    with pytest.raises(ValueError, match="не должны совпадать"):
        changed(settings, "hp2_address", "17")
    with pytest.raises(ValueError, match="один COM"):
        changed(settings, "sensor_relay_port", "com1")


class FakeTransport:
    def __init__(self):
        self.requests = []

    def exchange(self, payload, *, crc_mode_override):
        self.requests.append((payload, crc_mode_override))
        if payload[1] == 15:
            response = append_crc(payload[:6])
        else:
            response = append_crc(bytes((payload[0], 1, 1, 0x03)))
        return Exchange(append_crc(payload), response, 1.0)


def test_second_usb_is_disabled_until_explicitly_enabled_and_uses_readback():
    model = BionicModel()
    model.sensors["bo-min"].automatic = True
    model.sensors["bo-max"].automatic = True
    transport = FakeTransport()
    bridge = SensorRelayBridge(transport)
    state = bridge.sync(model)
    assert state.desired == 3
    assert transport.requests == []
    bridge.enabled = True
    state = bridge.sync(model)
    assert state.confirmed == 3
    assert state.online
    assert [item[0][1] for item in transport.requests] == [15, 1]
    assert all(item[1] == "append" for item in transport.requests)
