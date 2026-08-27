from __future__ import annotations

import configparser
import time
from dataclasses import dataclass

import serial

from .crc import apply_crc_mode


@dataclass
class Exchange:
    tx: bytes
    rx: bytes
    elapsed_ms: float


class SerialTransport:
    def __init__(self, config: configparser.ConfigParser):
        self.config = config
        self.serial: serial.Serial | None = None

    @property
    def connected(self) -> bool:
        return self.serial is not None and self.serial.is_open

    @property
    def endpoint(self) -> str:
        c = self.config["connection"]
        return f"{c.get('port')} @ {c.get('baudrate')} {c.get('bytesize')}{c.get('parity')}{c.get('stopbits')}"

    def connect(self) -> None:
        if self.connected:
            return
        c = self.config["connection"]
        self.serial = serial.Serial(
            port=c.get("port"),
            baudrate=c.getint("baudrate"),
            bytesize=c.getint("bytesize"),
            parity=c.get("parity").upper(),
            stopbits=c.getfloat("stopbits"),
            timeout=c.getint("timeout_ms") / 1000.0,
        )

    def disconnect(self) -> None:
        if self.serial is not None:
            self.serial.close()
        self.serial = None

    def exchange(self, raw_frame: bytes) -> Exchange:
        if not self.connected or self.serial is None:
            raise RuntimeError("Not connected")

        runtime = self.config["runtime"]
        tx = apply_crc_mode(raw_frame, runtime.get("crc_mode", "auto"))
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
        timeout_s = self.config["connection"].getint("timeout_ms") / 1000.0
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
