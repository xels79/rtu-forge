"""Configurable lighting profile for the Bionic Mini installation."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, replace
from enum import Enum


class LightType(str, Enum):
    NONE = "NONE"
    SINGLE = "SINGLE"
    SPECTRAL_4 = "SPECTRAL_4"


SPECTRAL_ROLES = ("red", "far_red", "blue", "white")
RESERVED_NON_LIGHT_RELAYS = {1, 2, *range(9, 24), 31, 32}
ROLE_LABELS = {
    "brightness": "Яркость",
    "red": "Красный",
    "far_red": "Дальний красный",
    "blue": "Синий",
    "white": "Белый",
}


@dataclass(frozen=True)
class LightChannel:
    role: str
    device_id: int
    channel: int


@dataclass(frozen=True)
class LightConfig:
    id: str
    rack: int
    tier: int
    name: str
    light_type: LightType
    power_relay: int
    channels: tuple[LightChannel, ...]
    min_voltage_v: float = 0.0
    max_voltage_v: float = 10.0
    min_brightness_pct: float = 0.0
    max_brightness_pct: float = 100.0
    enabled: bool = True


FACTORY_LIGHTS: tuple[LightConfig, ...] = (
    LightConfig("zone-1", 1, 1, "Стеллаж 1, ярус 1", LightType.SINGLE, 3, (LightChannel("brightness", 2, 1),)),
    LightConfig("zone-2", 1, 2, "Стеллаж 1, ярус 2", LightType.SPECTRAL_4, 4, (
        LightChannel("red", 2, 2), LightChannel("far_red", 2, 3),
        LightChannel("blue", 2, 4), LightChannel("white", 2, 5),
    )),
    LightConfig("zone-3", 1, 3, "Стеллаж 1, ярус 3", LightType.SINGLE, 5, (LightChannel("brightness", 2, 6),)),
    LightConfig("zone-4", 2, 1, "Стеллаж 2, ярус 1", LightType.SINGLE, 6, (LightChannel("brightness", 2, 7),)),
    LightConfig("zone-5", 2, 2, "Стеллаж 2, ярус 2", LightType.SPECTRAL_4, 7, (
        LightChannel("red", 2, 8), LightChannel("far_red", 3, 1),
        LightChannel("blue", 3, 2), LightChannel("white", 3, 3),
    )),
    LightConfig("zone-6", 2, 3, "Стеллаж 2, ярус 3", LightType.SINGLE, 8, (LightChannel("brightness", 3, 4),)),
)


def serialize_light_profile(profile: tuple[LightConfig, ...]) -> str:
    payload = []
    for light in profile:
        item = asdict(light)
        item["light_type"] = light.light_type.value
        payload.append(item)
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))


FACTORY_LIGHT_PROFILE = serialize_light_profile(FACTORY_LIGHTS)


def parse_light_profile(value: str) -> tuple[LightConfig, ...]:
    try:
        payload = json.loads(value)
        if not isinstance(payload, list):
            raise ValueError
        result = []
        for item in payload:
            enabled = item.get("enabled", True)
            if not isinstance(enabled, bool):
                raise ValueError
            channels = tuple(
                LightChannel(str(channel["role"]), int(channel["device_id"]), int(channel["channel"]))
                for channel in item["channels"]
            )
            result.append(LightConfig(
                id=str(item["id"]), rack=int(item["rack"]), tier=int(item["tier"]),
                name=str(item["name"]), light_type=LightType(item["light_type"]),
                power_relay=int(item["power_relay"]), channels=channels,
                min_voltage_v=float(item.get("min_voltage_v", 0.0)),
                max_voltage_v=float(item.get("max_voltage_v", 10.0)),
                min_brightness_pct=float(item.get("min_brightness_pct", 0.0)),
                max_brightness_pct=float(item.get("max_brightness_pct", 100.0)),
                enabled=enabled,
            ))
        return tuple(result)
    except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise ValueError("Профиль освещения повреждён или имеет неизвестный формат") from exc


def validate_light_profile(profile: tuple[LightConfig, ...], ao_device_ids: set[int]) -> None:
    if len(profile) != 6 or len({light.id for light in profile}) != 6:
        raise ValueError("Профиль освещения должен содержать шесть уникальных ярусов")
    positions = [(light.rack, light.tier) for light in profile]
    if any(rack < 1 or tier < 1 for rack, tier in positions) or len(set(positions)) != len(positions):
        raise ValueError("Стеллаж и ярус должны быть положительными и не повторяться")
    used_relays: dict[int, str] = {}
    used_channels: dict[tuple[int, int], str] = {}
    for light in profile:
        if not 1 <= light.power_relay <= 32:
            raise ValueError(f"{light.id}: реле питания должно быть DO1..DO32")
        if not 0 <= light.min_voltage_v < light.max_voltage_v <= 10:
            raise ValueError(f"{light.id}: диапазон напряжения должен находиться внутри 0..10 В")
        if not 0 <= light.min_brightness_pct < light.max_brightness_pct <= 100:
            raise ValueError(f"{light.id}: диапазон яркости должен находиться внутри 0..100%")
        expected_roles = {
            LightType.NONE: (),
            LightType.SINGLE: ("brightness",),
            LightType.SPECTRAL_4: SPECTRAL_ROLES,
        }[light.light_type]
        roles = tuple(channel.role for channel in light.channels)
        if roles != expected_roles:
            expected = ", ".join(expected_roles) or "без каналов"
            raise ValueError(f"{light.id}: для {light.light_type.value} требуются каналы {expected}")
        for channel in light.channels:
            if channel.device_id not in ao_device_ids:
                raise ValueError(f"{light.id}: Modbus ID {channel.device_id} не является настроенным AO-модулем")
            if not 1 <= channel.channel <= 8:
                raise ValueError(f"{light.id}: номер аналогового канала должен быть AO1..AO8")
        if not light.enabled or light.light_type == LightType.NONE:
            continue
        if light.power_relay in RESERVED_NON_LIGHT_RELAYS:
            raise ValueError(f"{light.id}: DO{light.power_relay} занят другой подсистемой Bionic Mini")
        if light.power_relay in used_relays:
            raise ValueError(f"Конфликт DO{light.power_relay}: {used_relays[light.power_relay]} и {light.id}")
        used_relays[light.power_relay] = light.id
        for channel in light.channels:
            physical = (channel.device_id, channel.channel)
            if physical in used_channels:
                previous = used_channels[physical]
                raise ValueError(f"Конфликт ID{physical[0]}/AO{physical[1]}: {previous} и {light.id}")
            used_channels[physical] = light.id


def replace_light(profile: tuple[LightConfig, ...], zone_id: str, updated: LightConfig) -> tuple[LightConfig, ...]:
    if zone_id not in {light.id for light in profile}:
        raise ValueError(f"Неизвестный ярус освещения: {zone_id}")
    return tuple(updated if light.id == zone_id else light for light in profile)


def change_light_type(light: LightConfig, light_type: LightType) -> LightConfig:
    if light_type == light.light_type:
        return light
    roles = {
        LightType.NONE: (),
        LightType.SINGLE: ("brightness",),
        LightType.SPECTRAL_4: SPECTRAL_ROLES,
    }[light_type]
    # Zero is an explicit "not assigned" placeholder. Validation prevents an
    # incomplete draft from being applied or saved; no free hardware channel
    # is guessed on the operator's behalf.
    channels = tuple(LightChannel(role, 0, 0) for role in roles)
    return replace(light, light_type=light_type, channels=channels)


def brightness_percent(light: LightConfig, voltage_v: float) -> float:
    fraction = (voltage_v - light.min_voltage_v) / (light.max_voltage_v - light.min_voltage_v)
    value = light.min_brightness_pct + fraction * (
        light.max_brightness_pct - light.min_brightness_pct
    )
    return min(light.max_brightness_pct, max(light.min_brightness_pct, value))
