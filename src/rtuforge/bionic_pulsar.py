"""Passive Pulsar water-meter slave backed by the Bionic water meter."""

from __future__ import annotations

import struct
from dataclasses import dataclass

from .bionic_model import BionicModel
from .pulsar_protocol import build_request, parse_response


PULSAR_MODEL = "N00014163"
PULSAR_VOLUME_CHANNEL = 1
PULSAR_READ_FUNCTION = 0x01
PULSAR_READ_FRAME_LENGTH = 14


def _is_bcd(data: bytes) -> bool:
    return all((byte & 0x0F) <= 9 and (byte >> 4) <= 9 for byte in data)


def is_pulsar_read_header(data: bytes) -> bool:
    """Return whether *data* has the complete shape of a channel-read header."""
    return (
        len(data) >= 6
        and _is_bcd(data[:4])
        and data[4] == PULSAR_READ_FUNCTION
        and data[5] == PULSAR_READ_FRAME_LENGTH
    )


@dataclass(frozen=True)
class PulsarWaterMeterSlave:
    """Expose channel 1 without owning or accumulating any meter state."""

    model: BionicModel
    address: str
    enabled: bool = False

    def handle(self, frame: bytes) -> bytes:
        if not self.enabled:
            return b""
        try:
            request = parse_response(
                frame,
                address=self.address,
                function=PULSAR_READ_FUNCTION,
                payload_length=4,
            )
        except (ValueError, RuntimeError):
            return b""
        channel_mask = int.from_bytes(request.payload, "little")
        if channel_mask != 1 << (PULSAR_VOLUME_CHANNEL - 1):
            return b""
        volume_m3 = self.model.water_meter.total_l / 1000.0
        return build_request(
            self.address,
            PULSAR_READ_FUNCTION,
            struct.pack("<f", volume_m3),
            request_id=request.request_id,
        )
