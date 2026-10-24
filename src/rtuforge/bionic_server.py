"""Serial slave loop for USB №1.

The transport is injectable; tests never open a real serial port.
"""

from __future__ import annotations

import os
import threading
from pathlib import Path
from typing import Callable

import serial

from .bionic_modbus import ModbusBus, expected_frame_length


class PortInUseError(RuntimeError):
    pass


class SerialSlaveTransport:
    def __init__(
        self, port: str, baudrate: int, parity: str, stopbits: float, timeout_ms: int = 50,
        *, serial_factory: Callable[..., object] = serial.Serial,
    ) -> None:
        self.port = port
        self.baudrate = baudrate
        self.parity = parity
        self.stopbits = stopbits
        self.timeout_ms = timeout_ms
        self.serial_factory = serial_factory
        self.serial: object | None = None

    def open(self) -> None:
        if self.serial is not None:
            return
        self.serial = self.serial_factory(
            port=self.port, baudrate=self.baudrate, bytesize=8,
            parity=self.parity, stopbits=self.stopbits, timeout=self.timeout_ms / 1000.0,
            write_timeout=self.timeout_ms / 1000.0,
        )

    def read(self, size: int) -> bytes:
        if self.serial is None:
            raise RuntimeError("USB №1 не открыт")
        return self.serial.read(size)

    def write(self, payload: bytes) -> None:
        if self.serial is None:
            raise RuntimeError("USB №1 не открыт")
        written = self.serial.write(payload)
        if written != len(payload):
            raise RuntimeError("USB №1: неполная запись ответа")
        self.serial.flush()

    def close(self) -> None:
        if self.serial is not None:
            self.serial.close()
            self.serial = None


class ModbusSlaveServer:
    def __init__(self, bus: ModbusBus, transport: SerialSlaveTransport, lock_path: Path) -> None:
        self.bus = bus
        self.transport = transport
        self.lock_path = lock_path
        self._lock_fd: int | None = None
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self.error: str | None = None

    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def _acquire(self) -> None:
        self.lock_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            self._lock_fd = os.open(self.lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            raise PortInUseError(
                f"USB №1 уже занят другим Bionic Immitator ({self.lock_path})"
            ) from None
        os.write(self._lock_fd, str(os.getpid()).encode("ascii"))

    def start(self) -> None:
        if self.running:
            return
        self._acquire()
        try:
            self.transport.open()
        except Exception:
            self._release()
            raise
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="bionic-modbus-slave", daemon=True)
        self._thread.start()

    def _run(self) -> None:
        buffer = bytearray()
        try:
            while not self._stop.is_set():
                chunk = self.transport.read(1)
                if not chunk:
                    buffer.clear()
                    continue
                buffer.extend(chunk)
                length = expected_frame_length(buffer)
                if length is not None and len(buffer) >= length:
                    frame = bytes(buffer[:length])
                    del buffer[:length]
                    response = self.bus.handle(frame)
                    if response:
                        self.transport.write(response)
        except Exception as exc:
            self.error = str(exc)
        finally:
            self.transport.close()
            self._release()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=max(1.0, self.transport.timeout_ms / 1000.0 * 3))
        self.transport.close()
        self._release()

    def _release(self) -> None:
        if self._lock_fd is not None:
            os.close(self._lock_fd)
            self._lock_fd = None
            try:
                self.lock_path.unlink()
            except FileNotFoundError:
                pass
