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
    key: str
    name: str
    request: bytes
    decode: Callable[[bytes, int], str]


@dataclass(frozen=True)
class DiagnosticResult:
    key: str
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


def _decode_external_sensor(response: bytes, slave: int) -> str:
    value = parse_bits(response, slave, 1)[0]
    return f"Coil 100 = {int(value)} — внешний датчик {'РАЗРЕШЁН' if value else 'ОТКЛЮЧЁН'}"


def _decode_operation(response: bytes, slave: int) -> str:
    mode, active_mode, room_raw = parse_registers(response, slave, 3, 3)
    room_signed = signed(room_raw)
    return (
        f"Holding 1={mode}, Holding 2={active_mode}, "
        f"Holding 3=0x{room_raw:04X} ({room_signed}; {room_signed * 0.01:.2f} °C)"
    )


def _decode_climate(response: bytes, slave: int) -> str:
    target_raw, thermostat, fan = parse_registers(response, slave, 3, 3)
    thermostat_name = {0: "ПРОСТАИВАЕТ", 1: "НАГРЕВАЕТ", 2: "ОХЛАЖДАЕТ"}.get(
        thermostat, "ВНЕ ДИАПАЗОНА"
    )
    fan_name = {0: "AUTO", 1: "СКОРОСТЬ 1", 2: "СКОРОСТЬ 2", 3: "СКОРОСТЬ 3"}.get(
        fan, "ВНЕ ДИАПАЗОНА"
    )
    return (
        f"Holding 5={signed(target_raw)} ({signed(target_raw) * 0.01:.2f} °C), "
        f"Holding 6={thermostat} ({thermostat_name}), "
        f"Holding 7={fan} ({fan_name})"
    )


def _decode_compressor(response: bytes, slave: int) -> str:
    raw = parse_registers(response, slave, 3, 1)[0]
    return f"Holding 21=0x{raw:04X} ({signed(raw)} %)"


def _decode_exchanger(response: bytes, slave: int) -> str:
    raw = parse_registers(response, slave, 3, 1)[0]
    value = signed(raw)
    return f"Holding 23=0x{raw:04X} ({value}; {value * 0.01:.2f} °C)"


def _decode_actual_fan(response: bytes, slave: int) -> str:
    raw = parse_registers(response, slave, 3, 1)[0]
    return f"Holding 32=0x{raw:04X} ({signed(raw)}; фактическая скорость 1..3)"


def _text_decoder(quantity: int) -> Callable[[bytes, int], str]:
    def decode(response: bytes, slave: int) -> str:
        values = parse_registers(response, slave, 3, quantity)
        raw = " ".join(f"{value:04X}" for value in values)
        text = "".join(chr(value) for value in values if value).strip()
        return f"{text or 'НЕТ ДАННЫХ'}; raw={raw}"

    return decode


def diagnostic_probes(slave: int) -> tuple[DiagnosticProbe, ...]:
    return (
        DiagnosticProbe(
            "link",
            "FC01 Coil 20 — связь с кондиционером",
            read_request(slave, 1, 0x0014, 1),
            _decode_link,
        ),
        DiagnosticProbe(
            "external_sensor",
            "FC01 Coil 100 — внешний датчик температуры",
            read_request(slave, 1, 0x0064, 1),
            _decode_external_sensor,
        ),
        DiagnosticProbe(
            "power",
            "FC01 Coil 1 — питание кондиционера",
            read_request(slave, 1, 0x0001, 1),
            _decode_power,
        ),
        DiagnosticProbe(
            "operation",
            "FC03 Holding 1..3 — режим и температура",
            read_request(slave, 3, 0x0001, 3),
            _decode_operation,
        ),
        DiagnosticProbe(
            "climate",
            "FC03 Holding 5..7 — уставка, термостат, вентилятор",
            read_request(slave, 3, 0x0005, 3),
            _decode_climate,
        ),
        DiagnosticProbe(
            "compressor",
            "FC03 Holding 21 — текущая мощность компрессора",
            read_request(slave, 3, 0x0015, 1),
            _decode_compressor,
        ),
        DiagnosticProbe(
            "exchanger",
            "FC03 Holding 23 — температура внутреннего теплообменника",
            read_request(slave, 3, 0x0017, 1),
            _decode_exchanger,
        ),
        DiagnosticProbe(
            "actual_fan",
            "FC03 Holding 32 — фактическая скорость вентилятора",
            read_request(slave, 3, 0x0020, 1),
            _decode_actual_fan,
        ),
        DiagnosticProbe(
            "hardware",
            "FC03 Holding 200..219 — аппаратная версия",
            read_request(slave, 3, 0x00C8, 20),
            _text_decoder(20),
        ),
        DiagnosticProbe(
            "firmware",
            "FC03 Holding 250..265 — версия прошивки",
            read_request(slave, 3, 0x00FA, 16),
            _text_decoder(16),
        ),
        DiagnosticProbe(
            "signature",
            "FC03 Holding 290..301 — сигнатура шлюза",
            read_request(slave, 3, 0x0122, 12),
            _text_decoder(12),
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
                    key=probe.key,
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
                    key=probe.key,
                    name=probe.name,
                    tx=expected_tx,
                    rx=b"",
                    elapsed_ms=None,
                    decoded=None,
                    error=str(exc),
                )
            )
    return results


def _temperature_assessment(results: list[DiagnosticResult]) -> str:
    operation = next((result for result in results if result.key == "operation"), None)
    exchanger = next((result for result in results if result.key == "exchanger"), None)
    if operation is None or exchanger is None or operation.error or exchanger.error:
        return "Доступность температур: НЕ ОПРЕДЕЛЕНА — одно из чтений завершилось ошибкой"
    slave = operation.tx[0]
    room_raw = parse_registers(operation.rx, slave, 3, 3)[2]
    exchanger_raw = parse_registers(exchanger.rx, slave, 3, 1)[0]
    if (signed(room_raw), signed(exchanger_raw)) == (0, -2000):
        return (
            "Доступность температур: НЕ ПОДТВЕРЖДЕНА — получена устойчивая "
            "диагностическая пара H3=0x0000 / H23=0xF830; оба отдельных значения "
            "допустимы по диапазонам, validity-флага в протоколе нет"
        )
    return (
        "Доступность температур: значения не совпадают с подтверждённой парой-"
        "заглушкой; отдельного validity-флага в протоколе нет"
    )


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
    assessment = _temperature_assessment(results)
    console.print(assessment, markup=False)
    if log_event is not None:
        log_event(f"aircon diag: {assessment}")


def run_diagnostics(
    client: AirconModbusClient,
    console: Console,
    *,
    log_event: Callable[[str], None] | None = None,
) -> bool:
    results = collect_diagnostics(client)
    print_diagnostics(results, console, log_event=log_event)
    return all(result.error is None for result in results)
