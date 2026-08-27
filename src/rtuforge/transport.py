from __future__ import annotations

import configparser
import time
from dataclasses import dataclass

import serial

from .connection import ConnectionOverrides, ConnectionSettings, effective_connection
from .crc import apply_crc_mode


@dataclass
class Exchange:
    tx: bytes
    rx: bytes
    elapsed_ms: float


class SerialTransport:
    def __init__(
        self,
        config: configparser.ConfigParser,
        overrides: ConnectionOverrides | None = None,
    ):
        self.config = config
        self.overrides = overrides or ConnectionOverrides()
        self.serial: serial.Serial | None = None

    @property
    def settings(self) -> ConnectionSettings:
        return effective_connection(self.config, self.overrides)

    @property
    def connected(self) -> bool:
        return self.serial is not None and self.serial.is_open

    @property
    def endpoint(self) -> str:
        return self.settings.endpoint

    def is_overridden(self, name: str) -> bool:
        return self.overrides.contains(name)

    def connect(self) -> None:
        if self.connected:
            return
        settings = self.settings
        self.serial = serial.Serial(
            port=settings.port,
            baudrate=settings.baudrate,
            bytesize=settings.bytesize,
            parity=settings.parity,
            stopbits=settings.stopbits,
            timeout=settings.timeout_ms / 1000.0,
        )

    def disconnect(self) -> None:
        if self.serial is not None:
            self.serial.close()
        self.serial = None

    def exchange(
        self,
        raw_frame: bytes,
        *,
        timeout_ms: int | None = None,
        crc_mode_override: str | None = None,
    ) -> Exchange:
        if not self.connected or self.serial is None:
            raise RuntimeError("Not connected")

        runtime = self.config["runtime"]
        crc_mode = runtime.get("crc_mode", "auto") if crc_mode_override is None else crc_mode_override
        tx = apply_crc_mode(raw_frame, crc_mode)
        silence = runtime.getint("response_silence_ms") / 1000.0
        max_bytes = runtime.getint("max_response_bytes")
        post_write = runtime.getint("post_write_delay_ms") / 1000.0

        self.serial.reset_input_buffer()
        started = time.perf_counter()
        self.serial.write(tx)
        self.serial.flush()
        if post_write > 0:
            time.sleep(post_write)

        rx = bytearray()
        last_data = time.perf_counter()
        saw_data = False
        effective_timeout_ms = (
            self.settings.timeout_ms
            if timeout_ms is None
            else timeout_ms
        )
        timeout_s = effective_timeout_ms / 1000.0
        deadline = time.perf_counter() + timeout_s

        while len(rx) < max_bytes and time.perf_counter() < deadline:
            waiting = self.serial.in_waiting
            if waiting:
                chunk = self.serial.read(min(waiting, max_bytes - len(rx)))
                if chunk:
                    rx.extend(chunk)
                    last_data = time.perf_counter()
                    saw_data = True
                    continue
            if saw_data and time.perf_counter() - last_data >= silence:
                break
            time.sleep(0.001)

        elapsed_ms = (time.perf_counter() - started) * 1000.0
        return Exchange(tx=tx, rx=bytes(rx), elapsed_ms=elapsed_ms)
