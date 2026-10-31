"""Read-only ONOKOM diagnostics used by ``rtuforge aircon diag``."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from rich.console import Console

from .aircon_modbus import (
    AirconModbusClient,
    parse_bits,
    parse_registers,
    read_request,
    signed,
)
from .crc import append_crc, has_valid_crc


@dataclass(frozen=True)
class DiagnosticProbe:
    name: str
    request: bytes
    decode: Callable[[bytes, int], str]


@dataclass(frozen=True)
class DiagnosticResult:
    name: str
    tx: bytes
    rx: bytes
    elapsed_ms: float | None
    decoded: str | None
    error: str | None

    @property
    def crc_status(self) -> str:
        if not self.rx:
            return "НЕТ ДАННЫХ"
        return "OK" if has_valid_crc(self.rx) else "ОШИБКА"


def _decode_link(response: bytes, slave: int) -> str:
    value = parse_bits(response, slave, 1)[0]
    return f"Coil 20 = {int(value)} — кондиционер {'НА СВЯЗИ' if value else 'НЕТ СВЯЗИ'}"


def _decode_power(response: bytes, slave: int) -> str:
    value = parse_bits(response, slave, 1)[0]
    return f"Coil 1 = {int(value)} — питание {'ВКЛ' if value else 'ВЫКЛ'}"


def _decode_operation(response: bytes, slave: int) -> str:
    mode, active_mode, room_raw = parse_registers(response, slave, 3, 3)
    return (
        f"Holding 1={mode}, Holding 2={active_mode}, "
        f"Holding 3={signed(room_raw)} ({signed(room_raw) * 0.01:.2f} °C)"
    )


def _decode_climate(response: bytes, slave: int) -> str:
    target_raw, thermostat, fan = parse_registers(response, slave, 3, 3)
    return (
        f"Holding 5={signed(target_raw)} ({signed(target_raw) * 0.01:.2f} °C), "
        f"Holding 6={thermostat}, Holding 7={fan}"
    )


def diagnostic_probes(slave: int) -> tuple[DiagnosticProbe, ...]:
    return (
        DiagnosticProbe(
            "FC01 Coil 20 — связь с кондиционером",
            read_request(slave, 1, 0x0014, 1),
            _decode_link,
        ),
        DiagnosticProbe(
            "FC01 Coil 1 — питание кондиционера",
            read_request(slave, 1, 0x0001, 1),
            _decode_power,
        ),
        DiagnosticProbe(
            "FC03 Holding 1..3 — режим и температура",
            read_request(slave, 3, 0x0001, 3),
            _decode_operation,
        ),
        DiagnosticProbe(
            "FC03 Holding 5..7 — уставка, термостат, вентилятор",
            read_request(slave, 3, 0x0005, 3),
            _decode_climate,
        ),
    )


def collect_diagnostics(client: AirconModbusClient) -> list[DiagnosticResult]:
    """Execute the fixed read-only probe set without stopping after Coil 20."""
    results: list[DiagnosticResult] = []
    slave = client.settings.slave_id
    for probe in diagnostic_probes(slave):
        expected_tx = append_crc(probe.request)
        try:
            with client.lock:
                exchange = client.transport.exchange(
                    probe.request,
                    timeout_ms=client.settings.timeout_ms,
                    crc_mode_override="append",
                )
            try:
                decoded = probe.decode(exchange.rx, slave)
                error = None
            except (ValueError, RuntimeError) as exc:
                decoded = None
                error = str(exc)
            results.append(
                DiagnosticResult(
                    name=probe.name,
                    tx=exchange.tx,
                    rx=exchange.rx,
                    elapsed_ms=exchange.elapsed_ms,
                    decoded=decoded,
                    error=error,
                )
            )
        except (OSError, RuntimeError) as exc:
            results.append(
                DiagnosticResult(
                    name=probe.name,
                    tx=expected_tx,
                    rx=b"",
                    elapsed_ms=None,
                    decoded=None,
                    error=str(exc),
                )
            )
    return results


def print_diagnostics(
    results: list[DiagnosticResult],
    console: Console,
    *,
    log_event: Callable[[str], None] | None = None,
) -> None:
    console.print("AIRCON DIAG — только чтение FC01/FC03", markup=False)
    for result in results:
        tx = result.tx.hex(" ").upper()
        rx = result.rx.hex(" ").upper() if result.rx else "<нет данных>"
        elapsed = f"{result.elapsed_ms:.1f} мс" if result.elapsed_ms is not None else "—"
        console.print(result.name, markup=False)
        console.print(f"  TX: {tx}", markup=False)
        console.print(f"  RX: {rx}", markup=False)
        console.print(f"  CRC: {result.crc_status}", markup=False)
        console.print(f"  Время: {elapsed}", markup=False)
        if result.error is not None:
            console.print(f"  Ошибка: {result.error}", markup=False)
        else:
            console.print(f"  Результат: {result.decoded}", markup=False)
        if log_event is not None:
            outcome = f"ошибка={result.error}" if result.error else f"результат={result.decoded}"
            log_event(
                f"aircon diag: {result.name}; TX={tx}; RX={rx}; "
                f"CRC={result.crc_status}; время={elapsed}; {outcome}"
            )


def run_diagnostics(
    client: AirconModbusClient,
    console: Console,
    *,
    log_event: Callable[[str], None] | None = None,
) -> bool:
    results = collect_diagnostics(client)
    print_diagnostics(results, console, log_event=log_event)
    return all(result.error is None for result in results)
