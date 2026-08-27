from __future__ import annotations

import configparser
from dataclasses import dataclass, fields

from .config import option_spec, parse_value


@dataclass(frozen=True)
class ConnectionOverrides:
    port: str | None = None
    baudrate: int | None = None
    bytesize: int | None = None
    parity: str | None = None
    stopbits: float | None = None
    timeout_ms: int | None = None

    def contains(self, name: str) -> bool:
        return getattr(self, name, None) is not None


@dataclass(frozen=True)
class ConnectionSettings:
    port: str
    baudrate: int
    bytesize: int
    parity: str
    stopbits: float
    timeout_ms: int

    @property
    def endpoint(self) -> str:
        return (
            f"{self.port} @ {self.baudrate} "
            f"{self.bytesize}{self.parity}{self.stopbits:g}"
        )


def effective_connection(
    config: configparser.ConfigParser,
    overrides: ConnectionOverrides | None = None,
) -> ConnectionSettings:
    section = config["connection"]
    override = overrides or ConnectionOverrides()
    return ConnectionSettings(
        port=override.port if override.port is not None else section.get("port", ""),
        baudrate=override.baudrate if override.baudrate is not None else section.getint("baudrate"),
        bytesize=override.bytesize if override.bytesize is not None else section.getint("bytesize"),
        parity=override.parity if override.parity is not None else section.get("parity", "N").upper(),
        stopbits=override.stopbits if override.stopbits is not None else section.getfloat("stopbits"),
        timeout_ms=override.timeout_ms if override.timeout_ms is not None else section.getint("timeout_ms"),
    )


def parse_connection_overrides(values: dict[str, str | None]) -> ConnectionOverrides:
    parsed: dict[str, object] = {}
    for field in fields(ConnectionOverrides):
        raw = values.get(field.name)
        if raw is None:
            parsed[field.name] = None
            continue
        if field.name == "port" and not raw.strip():
            raise ValueError("port")
        try:
            value = parse_value(option_spec(field.name), raw)
        except (KeyError, ValueError):
            raise ValueError(field.name) from None
        if field.name == "parity":
            parsed[field.name] = value.upper()
        elif field.name in {"baudrate", "bytesize", "timeout_ms"}:
            parsed[field.name] = int(value)
        elif field.name == "stopbits":
            parsed[field.name] = float(value)
        else:
            parsed[field.name] = value
    return ConnectionOverrides(**parsed)
