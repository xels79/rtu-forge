from __future__ import annotations

import configparser
from dataclasses import dataclass, replace
from pathlib import Path

from .stand_protocol import OUTPUT_RANGES, OutputRange


@dataclass(frozen=True)
class StandSettings:
    relay_address: int = 1
    output_address: int = 2
    output_range: str = "0-20ma"

    @property
    def range_spec(self) -> OutputRange:
        return OUTPUT_RANGES[self.output_range]


def _address(value: str | int, name: str) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        raise ValueError(f"{name} must be an integer from 1 to 247") from None
    if not 1 <= parsed <= 247:
        raise ValueError(f"{name} must be in range 1..247")
    return parsed


def _range_name(value: str) -> str:
    normalized = value.strip().lower()
    if normalized not in OUTPUT_RANGES:
        raise ValueError(
            "output_range must be one of: " + ", ".join(OUTPUT_RANGES)
        )
    return normalized


def load_stand_settings(path: Path) -> StandSettings:
    if not path.exists():
        return StandSettings()
    parser = configparser.ConfigParser()
    parser.read(path, encoding="utf-8")
    relay = parser.get("devices", "relay_address", fallback="1")
    output = parser.get("devices", "output_address", fallback="2")
    output_range = parser.get("output", "range", fallback="0-20ma")
    return StandSettings(
        relay_address=_address(relay, "relay_address"),
        output_address=_address(output, "output_address"),
        output_range=_range_name(output_range),
    )


def with_overrides(
    settings: StandSettings,
    *,
    relay_address: int | None = None,
    output_address: int | None = None,
    output_range: str | None = None,
) -> StandSettings:
    return replace(
        settings,
        relay_address=(
            settings.relay_address
            if relay_address is None
            else _address(relay_address, "relay_address")
        ),
        output_address=(
            settings.output_address
            if output_address is None
            else _address(output_address, "output_address")
        ),
        output_range=(
            settings.output_range
            if output_range is None
            else _range_name(output_range)
        ),
    )


def save_stand_settings(path: Path, settings: StandSettings) -> None:
    parser = configparser.ConfigParser()
    if path.exists():
        parser.read(path, encoding="utf-8")
    for section in ("devices", "output"):
        if not parser.has_section(section):
            parser.add_section(section)
    parser["devices"]["relay_address"] = str(settings.relay_address)
    parser["devices"]["output_address"] = str(settings.output_address)
    parser["output"]["range"] = settings.output_range
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as stream:
        parser.write(stream)
