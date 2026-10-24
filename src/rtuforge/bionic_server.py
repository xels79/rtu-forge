"""Serial slave loop for USB №1.

The transport is injectable; tests never open a real serial port.
"""

from __future__ import annotations

import os
import threading
import time
from pathlib import Path
from typing import Callable

import serial

from .bionic_modbus import ModbusBus, expected_frame_length
from .bionic_pulsar import (
    PULSAR_READ_FRAME_LENGTH, PulsarWaterMeterSlave, is_pulsar_read_header,
)
from .crc import has_valid_crc
from .counter_check import CounterCheck


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


class Usb1RequestDispatcher:
    """Frame and route Modbus and Pulsar requests read by one UART owner."""

    def __init__(
        self, bus: ModbusBus, pulsar: PulsarWaterMeterSlave | None = None,
        counter_check: CounterCheck | None = None,
    ) -> None:
        self.bus = bus
        self.pulsar = pulsar
        self.counter_check = counter_check
        self.buffer = bytearray()
        self.frame_started_ns: int | None = None

    def feed(self, chunk: bytes) -> list[bytes]:
        if not self.buffer and chunk:
            self.frame_started_ns = time.perf_counter_ns()
        self.buffer.extend(chunk)
        return self._drain(end_of_frame=False)

    def finish_frame(self) -> list[bytes]:
        """Finish a request at the serial inter-frame timeout."""
        responses = self._drain(end_of_frame=True)
        self.buffer.clear()
        self.frame_started_ns = None
        return responses

    def _observe(self, protocol: str, frame: bytes, response: bytes,
                 response_started_ns: int, response_completed_ns: int) -> None:
        if self.counter_check is not None:
            completed = response_started_ns
            self.counter_check.observe(
                protocol, frame, response,
                rx_started_ns=self.frame_started_ns or completed,
                rx_completed_ns=completed,
                response_started_ns=response_started_ns,
                response_completed_ns=response_completed_ns,
                model=self.pulsar.model if self.pulsar is not None else None,
            )
        self.frame_started_ns = time.perf_counter_ns() if self.buffer else None

    def _modbus(self, frame: bytes) -> bytes:
        started = time.perf_counter_ns()
        response = self.bus.handle(frame)
        completed = time.perf_counter_ns()
        self._observe("Modbus", frame, response, started, completed)
        return response

    def _pulsar(self, frame: bytes) -> bytes:
        started = time.perf_counter_ns()
        response = self.pulsar.handle(frame) if self.pulsar is not None else b""
        completed = time.perf_counter_ns()
        self._observe("Pulsar", frame, response, started, completed)
        return response

    def _drain(self, *, end_of_frame: bool) -> list[bytes]:
        responses: list[bytes] = []
        while self.buffer:
            modbus_length = expected_frame_length(self.buffer)
            pulsar_candidate = (
                self.pulsar is not None
                and self.pulsar.enabled
                and is_pulsar_read_header(self.buffer)
            )

            if pulsar_candidate:
                if len(self.buffer) < PULSAR_READ_FRAME_LENGTH:
                    if (
                        end_of_frame
                        and modbus_length is not None
                        and len(self.buffer) >= modbus_length
                        and has_valid_crc(bytes(self.buffer[:modbus_length]))
                    ):
                        frame = bytes(self.buffer[:modbus_length])
                        del self.buffer[:modbus_length]
                        response = self._modbus(frame)
                        if response:
                            responses.append(response)
                        continue
                    break

                frame = bytes(self.buffer[:PULSAR_READ_FRAME_LENGTH])
                if has_valid_crc(frame):
                    del self.buffer[:PULSAR_READ_FRAME_LENGTH]
                    response = self._pulsar(frame)
                    if response:
                        responses.append(response)
                    continue

                # A rare valid Modbus frame can share the six-byte Pulsar header.
                # Prefer it only after the complete Pulsar candidate fails CRC.
                if (
                    modbus_length is not None
                    and len(self.buffer) >= modbus_length
                    and has_valid_crc(bytes(self.buffer[:modbus_length]))
                ):
                    frame = bytes(self.buffer[:modbus_length])
                    self.buffer.clear()
                    response = self._modbus(frame)
                    if response:
                        responses.append(response)
                    continue

                del self.buffer[:PULSAR_READ_FRAME_LENGTH]
                now = time.perf_counter_ns()
                self._observe("Pulsar", frame, b"", now, now)
                continue

            if modbus_length is None or len(self.buffer) < modbus_length:
                break
            frame = bytes(self.buffer[:modbus_length])
            del self.buffer[:modbus_length]
            response = self._modbus(frame)
            if response:
                responses.append(response)
        return responses


class ModbusSlaveServer:
    def __init__(
        self, bus: ModbusBus, transport: SerialSlaveTransport, lock_path: Path,
        pulsar: PulsarWaterMeterSlave | None = None,
        counter_check: CounterCheck | None = None,
    ) -> None:
        self.bus = bus
        self.transport = transport
        self.lock_path = lock_path
        self.pulsar = pulsar
        self.counter_check = counter_check
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
        dispatcher = Usb1RequestDispatcher(self.bus, self.pulsar, self.counter_check)
        try:
            while not self._stop.is_set():
                chunk = self.transport.read(1)
                if not chunk:
                    for response in dispatcher.finish_frame():
                        self.transport.write(response)
                    continue
                for response in dispatcher.feed(chunk):
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
