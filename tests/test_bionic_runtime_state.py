import sys

from rtuforge.bionic_cli import (
    BridgeRunner, execute_command, main, make_context, save_runtime_state,
)
from rtuforge.bionic_model import BionicModel
from rtuforge.bionic_sensor_bridge import SensorRelayBridge
from rtuforge.bionic_state import runtime_state_path
from rtuforge.crc import append_crc
from rtuforge.transport import Exchange


class RelayTransport:
    def __init__(self) -> None:
        self.requests: list[bytes] = []
        self.image = 0
        self.fail = False

    def exchange(self, payload: bytes, *, crc_mode_override: str) -> Exchange:
        assert crc_mode_override == "append"
        self.requests.append(payload)
        if self.fail:
            raise RuntimeError("нет ответа")
        if payload[1] == 15:
            size = payload[6]
            self.image = int.from_bytes(payload[7 : 7 + size], "little")
            response = append_crc(payload[:6])
        else:
            count = int.from_bytes(payload[4:6], "big")
            size = (count + 7) // 8
            response = append_crc(
                bytes((payload[0], 1, size)) + self.image.to_bytes(size, "little")
            )
        return Exchange(append_crc(payload), response, 1.0)


def test_main_saves_physical_state_on_one_shot_exit_and_next_start_restores_it(
    tmp_path, monkeypatch,
):
    monkeypatch.setattr(
        sys, "argv",
        ["bionic-immitator", "--home", str(tmp_path), "tank", "bp", "level", "321"],
    )
    assert main() == 0
    assert runtime_state_path(tmp_path).exists()
    assert make_context(tmp_path).model.tanks["bp"].volume_l == 321


def test_automatic_state_keeps_physics_but_not_controller_owned_commands(tmp_path):
    ctx = make_context(tmp_path)
    ctx.model.tanks["bp"].volume_l = 234.5
    ctx.model.pipe_ruptured = True
    ctx.model.drives["hp1"].health.damage = 0.42
    ctx.model.paused = True
    ctx.model.speed = 5.0
    ctx.model.set_relay(22, True)
    ctx.model.set_analog_output(2, 1, 7000)
    ctx.model.drives["hp1"].run_register = True
    save_runtime_state(ctx)

    restored = make_context(tmp_path)
    assert restored.model.tanks["bp"].volume_l == 234.5
    assert restored.model.pipe_ruptured
    assert restored.model.drives["hp1"].health.damage == 0.42
    assert restored.model.paused and restored.model.speed == 5.0
    assert not restored.model.relay(22)
    assert restored.model.analog_outputs.get((2, 1), 0) == 0
    assert not restored.model.drives["hp1"].run_register


def test_manual_reset_immediately_replaces_automatic_state(tmp_path):
    ctx = make_context(tmp_path)
    ctx.model.tanks["bp"].volume_l = 1
    ctx.model.pipe_ruptured = True
    save_runtime_state(ctx)

    assert execute_command(ctx, "sim reset --confirm") == "reconnect"
    restored = make_context(tmp_path)
    assert restored.model.tanks["bp"].volume_l == restored.settings.bp_initial_l
    assert not restored.model.pipe_ruptured


def test_corrupt_automatic_state_is_logged_and_initial_state_is_used(tmp_path):
    runtime_state_path(tmp_path).write_text("not json", encoding="utf-8")
    ctx = make_context(tmp_path)
    assert ctx.model.tanks["bp"].volume_l == ctx.settings.bp_initial_l
    assert "Автосостояние не восстановлено" in ctx.notice
    assert any(
        event.subject == "simulation-state" and "начальное состояние" in event.message
        for event in ctx.journal.events
    )


def test_relay_rewrites_complete_image_after_link_recovers():
    model = BionicModel()
    model.force_sensor("bo-min", True)
    transport = RelayTransport()
    bridge = SensorRelayBridge(transport)
    bridge.enabled = True
    assert bridge.sync(model, now=0).confirmed == 1

    transport.fail = True
    bridge.sync(model, force_read=True, now=1)
    assert not bridge.state.online
    transport.fail = False
    transport.image = 0
    transport.requests.clear()

    state = bridge.sync(model, now=2)
    assert [request[1] for request in transport.requests] == [15, 1]
    assert state.online and state.confirmed == state.desired == 1


def test_periodic_health_check_restarts_writes_after_retry_burst():
    model = BionicModel()
    model.force_sensor("bo-min", True)
    transport = RelayTransport()
    transport.fail = True
    bridge = SensorRelayBridge(transport, retry_interval_s=0.2)
    bridge.enabled = True
    for now in (0.0, 0.2, 0.4):
        bridge.sync(model, now=now)
    assert len(transport.requests) == 3

    transport.fail = False
    transport.requests.clear()
    state = bridge.sync(model, force_read=True, now=0.61)
    assert [request[1] for request in transport.requests] == [15, 1]
    assert state.online and state.confirmed == 1


def test_relay_recovery_is_logged_after_correct_image_is_confirmed(tmp_path):
    ctx = make_context(tmp_path)
    ctx.model.force_sensor("bo-min", True)
    transport = RelayTransport()
    bridge = SensorRelayBridge(transport)
    bridge.enabled = True
    runner = object.__new__(BridgeRunner)
    runner.ctx = ctx
    runner.bridge = bridge
    runner.last_error = None
    runner.link_was_lost = False

    runner._sync(now=0)
    transport.fail = True
    runner._sync(force_read=True, now=1)
    transport.fail = False
    transport.image = 0
    runner._sync(now=2)

    hardware_messages = [
        event.message for event in ctx.journal.events
        if event.kind == "АППАРАТУРА" and event.subject == "USB2"
    ]
    assert any("потеря связи" in message for message in hardware_messages)
    assert any(
        "правильное состояние реле установлено и подтверждено" in message
        for message in hardware_messages
    )
