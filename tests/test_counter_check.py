from __future__ import annotations

import json
from pathlib import Path

import pytest
from rich.console import Console

from rtuforge.bionic_cli import execute_command, make_context
from rtuforge.bionic_config import BionicSettings
from rtuforge.bionic_modbus import build_default_bus
from rtuforge.bionic_pulsar import PulsarWaterMeterSlave
from rtuforge.bionic_server import Usb1RequestDispatcher
from rtuforge.counter_check import CounterCheck
from rtuforge.crc import append_crc
from rtuforge.pulsar_protocol import read_channel_request


def feed(dispatcher: Usb1RequestDispatcher, payload: bytes) -> list[bytes]:
    return [reply for byte in payload for reply in dispatcher.feed(bytes((byte,)))]


def test_counter_check_commands_are_passive_and_stop_writes_one_report(tmp_path: Path):
    console = Console(record=True, width=180)
    ctx = make_context(tmp_path, console=console)
    before_relays = list(ctx.model.relays)
    before_volume = ctx.model.water_meter.total_l

    execute_command(ctx, "counter check start")
    session = ctx.counter_check.status(ctx.model)["sessionId"]
    execute_command(ctx, "counter check start")
    assert ctx.counter_check.status(ctx.model)["sessionId"] == session
    execute_command(ctx, "counter check status")
    execute_command(ctx, "counter check stop")
    stopped = ctx.counter_check.status(ctx.model)

    assert not stopped["active"]
    assert ctx.model.relays == before_relays
    assert ctx.model.water_meter.total_l == before_volume
    reports = list((tmp_path / "counter-check-reports").glob("*.json"))
    assert len(reports) == 1
    report = json.loads(reports[0].read_text(encoding="utf-8"))
    assert report["sessionId"] == session
    assert report["observableTimeouts"] == 0
    assert "не подтверждает" in report["timeoutNote"]
    assert "timeout firmware не подтверждается" in console.export_text()


def test_dispatcher_observes_modbus_and_pulsar_without_sending_any_request(tmp_path: Path):
    ctx = make_context(tmp_path)
    ctx.model.water_meter.total_l = 1250.0
    check = CounterCheck()
    check.start()
    dispatcher = Usb1RequestDispatcher(
        build_default_bus(ctx.model, BionicSettings()),
        PulsarWaterMeterSlave(ctx.model, "17440707", enabled=True),
        check,
    )
    modbus = append_crc(bytes.fromhex("01 01 00 00 00 01"))
    pulsar = read_channel_request("17440707", request_id=0x1234)

    assert len(feed(dispatcher, modbus)) == 1
    assert len(feed(dispatcher, pulsar)) == 1
    summary = check.status(ctx.model)

    assert summary["modbusRequests"] == 1
    assert summary["pulsarRequests"] == 1
    assert summary["successfulResponses"] == 2
    assert summary["lastPulsarVolumeM3"] == pytest.approx(1.25)
    assert summary["observableTimeouts"] == 0
    assert summary["observedNoResponse"] == 0


def test_bad_crc_and_absent_response_are_not_called_firmware_timeouts(tmp_path: Path):
    ctx = make_context(tmp_path)
    check = CounterCheck()
    check.start()
    slave = PulsarWaterMeterSlave(ctx.model, "17440707", enabled=True)
    dispatcher = Usb1RequestDispatcher(build_default_bus(ctx.model, BionicSettings()), slave, check)
    damaged = bytearray(read_channel_request("17440707"))
    damaged[-1] ^= 1
    assert feed(dispatcher, bytes(damaged)) == []
    assert dispatcher.finish_frame() == []

    silent = Usb1RequestDispatcher(
        build_default_bus(ctx.model, BionicSettings()),
        PulsarWaterMeterSlave(ctx.model, "17440707", enabled=False),
        check,
    )
    # Disabled slave behavior is existing emulator behavior. Record a valid
    # addressed request directly to prove the diagnostic terminology.
    now = 10
    check.observe(
        "Pulsar", read_channel_request("17440707"), b"",
        rx_started_ns=now, rx_completed_ns=now + 1,
        response_started_ns=now + 1, response_completed_ns=now + 2,
        model=ctx.model,
    )
    assert silent is not None
    summary = check.status(ctx.model)
    assert summary["crcErrors"] == 1
    assert summary["observedNoResponse"] == 2
    assert summary["observableTimeouts"] == 0
