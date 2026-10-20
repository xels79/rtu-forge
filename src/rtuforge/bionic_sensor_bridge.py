"""Explicitly enabled USB №2 bridge to a physical Waveshare relay."""

from __future__ import annotations

from dataclasses import dataclass

from .bionic_model import BionicModel
from .crc import has_valid_crc


@dataclass
class SensorRelayState:
    desired: int = 0
    confirmed: int | None = None
    online: bool = False
    error: str | None = None


class SensorRelayBridge:
    SENSOR_ORDER = (
        "bo-min", "bo-max", "bp-min", "bp-max",
        "bso1-min", "bso1-max", "bso2-min", "bso2-max",
    )

    def __init__(self, transport: object, slave: int = 1, channels: int = 8, *, active_low: bool = False, mapping: dict[str, int] | None = None, loss_behavior: str = "hold") -> None:
        self.transport = transport
        self.slave = slave
        self.channels = channels
        self.active_low = active_low
        self.mapping = mapping or {sensor: index + 1 for index, sensor in enumerate(self.SENSOR_ORDER)}
        self.loss_behavior = loss_behavior
        self.enabled = False
        self.state = SensorRelayState()

    def desired_from(self, model: BionicModel) -> int:
        image = 0
        for sensor_id, channel in self.mapping.items():
            value = model.sensors[sensor_id].value
            if value ^ self.active_low:
                image |= 1 << (channel - 1)
        return image

    def sync(self, model: BionicModel) -> SensorRelayState:
        self.state.desired = self.desired_from(model)
        if not self.enabled:
            return self.state
        count = min(self.channels, len(self.SENSOR_ORDER))
        data = self.state.desired.to_bytes((count + 7) // 8, "little")
        write = bytes((self.slave, 15, 0, 0, 0, count, len(data))) + data
        read = bytes((self.slave, 1, 0, 0, 0, count))
        try:
            write_exchange = self.transport.exchange(write, crc_mode_override="append")
            if not self._valid_write(write, write_exchange.rx):
                raise RuntimeError("физическое реле не подтвердило FC0F")
            read_exchange = self.transport.exchange(read, crc_mode_override="append")
            self.state.confirmed = self._read_image(read_exchange.rx, count)
            self.state.online = True
            self.state.error = None
        except Exception as exc:
            self.state.online = False
            self.state.error = str(exc)
            if self.loss_behavior == "unknown":
                self.state.confirmed = None
        return self.state

    def _valid_write(self, request: bytes, response: bytes) -> bool:
        return (
            len(response) == 8 and has_valid_crc(response)
            and response[:6] == request[:6]
        )

    def _read_image(self, response: bytes, count: int) -> int:
        size = (count + 7) // 8
        if (
            len(response) != size + 5 or not has_valid_crc(response)
            or response[:3] != bytes((self.slave, 1, size))
        ):
            raise RuntimeError("неверный readback FC01 физического реле")
        return int.from_bytes(response[3 : 3 + size], "little")
