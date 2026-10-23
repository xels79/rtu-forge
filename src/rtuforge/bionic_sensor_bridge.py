"""Explicitly enabled USB №2 bridge to a physical Waveshare relay."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import time

from .bionic_model import BionicModel
from .crc import has_valid_crc


@dataclass
class SensorRelayState:
    desired: int = 0
    confirmed: int | None = None
    online: bool = False
    error: str | None = None
    last_success_at: str | None = None


class SensorRelayBridge:
    SENSOR_ORDER = (
        "bo-min", "bo-max", "bp-min", "bp-max",
        "bso1-min", "bso1-max", "bso2-min", "bso2-max",
    )

    def __init__(
        self, transport: object, slave: int = 1, channels: int = 8, *,
        active_low: bool = False, mapping: dict[str, int] | None = None,
        loss_behavior: str = "hold", max_retries: int = 3,
        retry_interval_s: float = 0.2,
    ) -> None:
        self.transport = transport
        self.slave = slave
        self.channels = channels
        self.active_low = active_low
        self.mapping = mapping or {sensor: index + 1 for index, sensor in enumerate(self.SENSOR_ORDER)}
        self.loss_behavior = loss_behavior
        self.max_retries = max_retries
        self.retry_interval_s = retry_interval_s
        self.enabled = False
        self.state = SensorRelayState()
        self._last_written: int | None = None
        self._write_attempts = 0
        self._next_retry_at = 0.0

    def desired_from(self, model: BionicModel) -> int:
        image = 0
        for sensor_id, channel in self.mapping.items():
            value = model.sensors[sensor_id].value
            if value ^ self.active_low:
                image |= 1 << (channel - 1)
        return image

    def sync(
        self, model: BionicModel, *, force_read: bool = False,
        now: float | None = None,
    ) -> SensorRelayState:
        current_time = time.monotonic() if now is None else now
        desired = self.desired_from(model)
        if desired != self.state.desired:
            self._write_attempts = 0
            self._next_retry_at = 0.0
        self.state.desired = desired
        if not self.enabled:
            return self.state

        needs_write = self._last_written != desired
        # After a bounded retry burst, a periodic health check starts a new
        # burst with FC0F.  This guarantees that recovery re-applies the
        # complete desired image instead of trusting outputs left during the
        # outage.
        if (
            needs_write and force_read and self._write_attempts >= self.max_retries
            and current_time >= self._next_retry_at
        ):
            self._write_attempts = 0
        if (
            needs_write and self._write_attempts < self.max_retries
            and current_time >= self._next_retry_at
        ):
            self._write_attempts += 1
            self._next_retry_at = current_time + self.retry_interval_s
            return self._write_and_read(desired)
        if force_read:
            return self._read_only(desired)
        return self.state

    def _write_and_read(self, desired: int) -> SensorRelayState:
        count = self.channels
        data = self.state.desired.to_bytes((count + 7) // 8, "little")
        write = bytes((self.slave, 15, 0, 0, 0, count, len(data))) + data
        try:
            write_exchange = self.transport.exchange(write, crc_mode_override="append")
            if not self._valid_write(write, write_exchange.rx):
                raise RuntimeError("физическое реле не подтвердило FC0F")
            self._read_confirmed(desired)
        except Exception as exc:
            self._offline(exc)
        return self.state

    def _read_only(self, desired: int) -> SensorRelayState:
        try:
            self._read_confirmed(desired)
        except Exception as exc:
            self._offline(exc)
        return self.state

    def _read_confirmed(self, desired: int) -> None:
        read = bytes((self.slave, 1, 0, 0, 0, self.channels))
        read_exchange = self.transport.exchange(read, crc_mode_override="append")
        self.state.confirmed = self._read_image(read_exchange.rx, self.channels)
        self.state.online = True
        self.state.last_success_at = datetime.now(timezone.utc).isoformat()
        self._write_attempts = 0
        self._next_retry_at = 0.0
        if self.state.confirmed == desired:
            self._last_written = desired
            self.state.error = None
        else:
            self._last_written = None
            self.state.error = "подтверждённое состояние реле не совпадает с требуемым"

    def _offline(self, exc: Exception) -> None:
        self.state.online = False
        self.state.confirmed = None
        self.state.error = str(exc)
        self._last_written = None

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
