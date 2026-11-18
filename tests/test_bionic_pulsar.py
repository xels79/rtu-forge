"""Pulsar slave tests use only the in-memory Bionic model."""

from __future__ import annotations

import struct

import pytest

from rtuforge.bionic_cli import execute_command, make_context, save_runtime_state
from rtuforge.bionic_config import BionicSettings, changed
from rtuforge.bionic_model import BionicModel
from rtuforge.bionic_pulsar import PulsarWaterMeterSlave
from rtuforge.pulsar_protocol import parse_response, read_channel_request


ADDRESS = "17440707"


def read_volume(slave: PulsarWaterMeterSlave, *, request_id: int = 0) -> float:
    response = slave.handle(read_channel_request(ADDRESS, request_id=request_id))
    parsed = parse_response(
        response,
        address=ADDRESS,
        function=1,
        request_id=request_id,
        payload_length=4,
    )
    return struct.unpack("<f", parsed.payload)[0]


@pytest.mark.parametrize(("litres", "cubic_metres"), ((0.0, 0.0), (1250.0, 1.25)))
def test_channel_one_reads_existing_water_meter_in_cubic_metres(litres, cubic_metres):
    model = BionicModel()
    model.water_meter.total_l = litres
    slave = PulsarWaterMeterSlave(model, ADDRESS, enabled=True)
    assert read_volume(slave) == pytest.approx(cubic_metres)


def test_pulsar_read_tracks_changes_and_never_changes_the_total_itself():
    model = BionicModel()
    model.water_meter.total_l = 1250.0
    slave = PulsarWaterMeterSlave(model, ADDRESS, enabled=True)

    before = model.water_meter.total_l
    assert read_volume(slave) == pytest.approx(1.25)
    assert model.water_meter.total_l == before

    model.water_meter.total_l += 50.0
    assert read_volume(slave) == pytest.approx(1.30)
    assert model.water_meter.total_l == 1300.0


def test_closed_do22_keeps_both_views_constant_without_physical_inflow():
    model = BionicModel()
    model.running = True
    model.water_meter.total_l = 1250.0
    slave = PulsarWaterMeterSlave(model, ADDRESS, enabled=True)

    model.set_relay(22, False)
    model.tick(60)

    assert model.water_meter.total_l == 1250.0
    assert read_volume(slave) == pytest.approx(1.25)


def test_stuck_open_valve_uses_the_existing_physical_inflow_calculation():
    model = BionicModel()
    model.running = True
    model.water_meter.total_l = 1250.0
    model.fill_valve_stuck_open = True
    slave = PulsarWaterMeterSlave(model, ADDRESS, enabled=True)

    model.tick(60)

    assert not model.relay(22)
    assert model.water_meter.total_l == pytest.approx(1253.0)
    assert read_volume(slave) == pytest.approx(1.253)


def test_runtime_restart_preserves_the_same_source_value(tmp_path):
    ctx = make_context(tmp_path)
    ctx.model.water_meter.total_l = 1250.5
    save_runtime_state(ctx)

    restored = make_context(tmp_path)
    slave = PulsarWaterMeterSlave(restored.model, ADDRESS, enabled=True)
    assert restored.model.water_meter.total_l == 1250.5
    assert read_volume(slave) == pytest.approx(1.2505)


def test_pulsar_settings_are_disabled_by_default_and_validate_bcd_address():
    settings = BionicSettings()
    assert not settings.pulsar_enabled
    assert changed(settings, "pulsar_enabled", "true").pulsar_enabled
    assert changed(settings, "pulsar_address", ADDRESS).pulsar_address == ADDRESS
    with pytest.raises(ValueError, match="8 десятичных цифр"):
        changed(settings, "pulsar_address", "17A40707")


def test_applying_pulsar_connection_settings_requests_usb1_reconnect(tmp_path):
    ctx = make_context(tmp_path)
    execute_command(ctx, f"settings set pulsar_address {ADDRESS}")
    execute_command(ctx, "settings set pulsar_enabled true")
    assert execute_command(ctx, "settings apply") == "reconnect"
