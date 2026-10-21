from pathlib import Path

import pytest

from rtuforge.bionic_config import BionicSettings, changed, load_settings, parse_sensor_relay_map, save_settings
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


def test_ponics_reads_full_map_scales_bp_measurements_and_writes_only_confirmed_registers():
    model = BionicModel()
    bus = build_default_bus(model, BionicSettings())
    full = request(bus, "05 03 00 00 00 2A")
    assert full[:3] == bytes((5, 3, 84))
    assert len(full) == 87
    assert request(bus, "05 03 00 04 00 03") == bytes.fromhex("05 03 06 02 58 00 C8 00 C8")
    assert request(bus, "05 06 00 1B 00 3D") == bytes.fromhex("05 06 00 1B 00 3D")
    assert request(bus, "05 03 00 1B 00 01") == bytes.fromhex("05 03 02 00 3D")
    assert request(bus, "05 06 00 04 02 BC") == bytes.fromhex("05 86 02")


def test_ponics_fc10_and_manual_dose_affect_only_bp():
    model = BionicModel()
    bus = build_default_bus(model, BionicSettings())
    others = {
        tank_id: (tank.volume_l, tank.solute_mass, tank.acidity_units, tank.heat_c_l)
        for tank_id, tank in model.tanks.items() if tank_id != "bp"
    }
    assert request(bus, "05 10 00 1B 00 02 04 00 37 00 41") == bytes.fromhex("05 10 00 1B 00 02")
    before_ec = model.tanks["bp"].ec_ms_cm
    assert request(bus, "05 06 00 0E 00 64") == bytes.fromhex("05 06 00 0E 00 64")
    assert model.tanks["bp"].ec_ms_cm > before_ec
    assert {
        tank_id: (tank.volume_l, tank.solute_mass, tank.acidity_units, tank.heat_c_l)
        for tank_id, tank in model.tanks.items() if tank_id != "bp"
    } == others
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
    assert changed(settings, "sensor_relay_contact", "NC").sensor_relay_contact == "NC"
    with pytest.raises(ValueError, match="NO или NC"):
        changed(settings, "sensor_relay_contact", "closed")
    assert changed(settings, "valve_pressure_response_ms", "200").valve_pressure_response_ms == 200
    with pytest.raises(ValueError, match="0..3 бар"):
        changed(settings, "rupture_residual_bar", "3.1")


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


class RelayTransport:
    def __init__(self):
        self.requests = []
        self.image = 0
        self.fail = False

    def exchange(self, payload, *, crc_mode_override):
        self.requests.append((payload, crc_mode_override))
        if self.fail:
            raise RuntimeError("нет ответа")
        if payload[1] == 15:
            size = payload[6]
            self.image = int.from_bytes(payload[7 : 7 + size], "little")
            response = append_crc(payload[:6])
        else:
            count = int.from_bytes(payload[4:6], "big")
            size = (count + 7) // 8
            response = append_crc(bytes((payload[0], 1, size)) + self.image.to_bytes(size, "little"))
        return Exchange(append_crc(payload), response, 1.0)


def enabled_bridge(model, transport=None):
    transport = transport or RelayTransport()
    bridge = SensorRelayBridge(transport)
    bridge.enabled = True
    return bridge, transport


def test_default_sensor_map_assigns_all_eight_channels_once():
    mapping = parse_sensor_relay_map(BionicSettings().sensor_relay_map)
    assert mapping == {
        "bo-min": 1, "bo-max": 2, "bp-min": 3, "bp-max": 4,
        "bso1-min": 5, "bso1-max": 6, "bso2-min": 7, "bso2-max": 8,
    }
    assert len(set(mapping.values())) == 8


def test_16_channel_relay_supports_a_sensor_remapped_above_channel_eight():
    model = BionicModel()
    model.force_sensor("bso2-max", True)
    mapping = parse_sensor_relay_map(BionicSettings().sensor_relay_map)
    mapping["bso2-max"] = 16
    transport = RelayTransport()
    bridge = SensorRelayBridge(transport, channels=16, mapping=mapping)
    bridge.enabled = True
    state = bridge.sync(model, now=0)
    assert state.confirmed == 1 << 15
    assert transport.requests[0][0][4:6] == bytes((0, 16))


def test_threshold_edges_switch_only_the_assigned_relay_and_switch_back():
    model = BionicModel()
    bridge, transport = enabled_bridge(model)
    threshold = model.sensors["bo-min"].threshold_l

    model.set_tank_level("bo", threshold)
    state = bridge.sync(model, now=0)
    assert state.desired == 0b00000001
    assert state.confirmed == 0b00000001
    assert transport.image == 0b00000001

    model.set_tank_level("bo", threshold - 0.1)
    state = bridge.sync(model, now=1)
    assert state.desired == 0
    assert state.confirmed == 0
    assert transport.image == 0


def test_zero_delay_is_immediate_and_optional_delay_hysteresis_still_work():
    defaults = BionicSettings()
    assert defaults.sensor_hysteresis_l == 0
    assert defaults.sensor_delay_s == 0

    model = BionicModel()
    model.running = True
    sensor = model.sensors["bo-min"]
    sensor.hysteresis_l = 5
    sensor.delay_s = 0.5
    model.set_tank_level("bo", sensor.threshold_l + 6)
    assert not sensor.automatic
    model.tick(0.25)
    assert not sensor.automatic
    model.tick(0.25)
    assert sensor.automatic
    model.set_tank_level("bo", sensor.threshold_l - 6)
    model.tick(0.5)
    assert not sensor.automatic


def test_force_on_off_and_auto_drive_the_mapped_relay():
    model = BionicModel()
    bridge, transport = enabled_bridge(model)
    model.set_tank_level("bo", 0)

    model.force_sensor("bo-min", True)
    assert bridge.sync(model, now=0).confirmed == 1
    model.force_sensor("bo-min", False)
    assert bridge.sync(model, now=1).confirmed == 0

    model.set_tank_level("bo", model.sensors["bo-min"].threshold_l + 1)
    assert model.sensors["bo-min"].automatic
    assert not model.sensors["bo-min"].value
    model.force_sensor("bo-min", None)
    assert bridge.sync(model, now=2).confirmed == 1
    assert transport.image == 1


def test_bridge_does_not_repeat_writes_and_uses_separate_fc01_readback():
    model = BionicModel()
    model.force_sensor("bo-min", True)
    bridge, transport = enabled_bridge(model)
    bridge.sync(model, now=0)
    assert [request[0][1] for request in transport.requests] == [15, 1]
    transport.requests.clear()
    bridge.sync(model, now=1)
    assert transport.requests == []
    bridge.sync(model, force_read=True, now=2)
    assert [request[0][1] for request in transport.requests] == [1]


def test_lost_link_never_exposes_stale_confirmation():
    model = BionicModel()
    bridge, transport = enabled_bridge(model)
    model.force_sensor("bo-min", True)
    assert bridge.sync(model, now=0).confirmed == 1
    transport.fail = True
    model.force_sensor("bo-min", False)
    state = bridge.sync(model, now=1)
    assert not state.online
    assert state.confirmed is None
    assert state.error == "нет ответа"


def test_failed_write_uses_bounded_retry_policy():
    model = BionicModel()
    model.force_sensor("bo-min", True)
    transport = RelayTransport()
    transport.fail = True
    bridge, _ = enabled_bridge(model, transport)
    for now in (0.0, 0.1, 0.2, 0.4, 0.8):
        bridge.sync(model, now=now)
    assert len(transport.requests) == 3
    assert bridge.state.confirmed is None


def test_duplicate_sensor_channel_is_rejected():
    duplicate = BionicSettings().sensor_relay_map.replace("bo-max:2", "bo-max:1")
    with pytest.raises(ValueError, match="уникальным"):
        changed(BionicSettings(), "sensor_relay_map", duplicate)


def test_sensor_edge_notifies_bridge_without_any_tui_refresh():
    model = BionicModel()
    bridge, transport = enabled_bridge(model)
    bridge.sync(model, now=0)
    transport.requests.clear()
    model.sensor_change = lambda: bridge.sync(model, now=1)
    model.set_tank_level("bo", model.tanks["bo"].capacity_l)
    assert transport.image == 0b11
    assert bridge.state.confirmed == 0b11
    assert [request[0][1] for request in transport.requests] == [15, 1]
