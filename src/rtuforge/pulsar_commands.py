"""Isolated Pulsar CLI commands; never change Modbus CRC/configuration defaults."""
from __future__ import annotations

from typing import TYPE_CHECKING

from .connection import effective_connection
from .pulsar_protocol import (
    decode_clock,
    decode_value,
    parse_number,
    parse_response,
    parse_value_bytes,
    read_channel_request,
    read_clock_request,
    read_parameter_request,
    validate_clock_write_response,
    validate_parameter_write_response,
    write_clock_request,
    write_parameter_request,
)

if TYPE_CHECKING:
    from .commands import CommandContext


HELP_EN = """pulsar: proprietary Pulsar RS-485 protocol (NOT Modbus RTU)
  pulsar discover --single
      Find one Pulsar on an isolated bus (broadcast; multiple replies collide).
  pulsar read <8-digit-address> [--channel 1..32] [--format float|s32|u32|f64|raw]
      Read channel; default channel 1, float32 (Pulsar Water model 1).
  pulsar param get <address> <index> [--format raw|u8|u16|u32|s32|float|f64]
      Read parameter 0x0A; raw 8 bytes by default, indices are model-specific.
  pulsar param set <address> <index> <16-hex-digits> [--execute]
      Preview by default; --execute writes parameter with function 0x0B.
  pulsar time get <address>
  pulsar time set <address> YYYY-MM-DDTHH:MM:SS [--execute]
      Preview by default. Changing clock can affect metering archives.
  pulsar decode <hex-frame...>
      Decode a captured frame offline without opening the serial port.

Examples:
  rtuforge --port COM4 --baudrate 9600 --parity N pulsar read 17440707
  rtuforge --port COM4 --parity N pulsar param get 17440707 0x000A
  rtuforge pulsar param set 17440707 0x0010 0000000000000000

Frames use their own CRC16, irrespective of runtime.crc_mode.
Use only one RS-485 master. Before any write, verify the exact model-specific
parameter index, data format and permissions.
"""

HELP_RU = """pulsar: собственный протокол RS-485 «Пульсар» (НЕ Modbus RTU)
  pulsar discover --single
      Поиск одного счётчика на отдельной шине (broadcast, ответы конфликтуют).
  pulsar read <адрес-8-цифр> [--channel 1..32] [--format float|s32|u32|f64|raw]
      Чтение канала; по умолчанию канал 1, float32 (модель воды 1).
  pulsar param get <адрес> <индекс> [--format raw|u8|u16|u32|s32|float|f64]
      Чтение параметра 0x0A; по умолчанию сырые 8 байт, индексы зависят от модели.
  pulsar param set <адрес> <индекс> <16-hex-цифр> [--execute]
      По умолчанию только просмотр пакета; --execute выполняет запись 0x0B.
  pulsar time get <адрес>
  pulsar time set <адрес> YYYY-MM-DDTHH:MM:SS [--execute]
      По умолчанию только просмотр; смена часов влияет на архивы учёта.
  pulsar decode <hex-кадр...>
      Проверка пакета без подключения к COM-порту.

Примеры:
  rtuforge --port COM4 --baudrate 9600 --parity N pulsar read 17440707
  rtuforge --port COM4 --parity N pulsar param get 17440707 0x000A
  rtuforge pulsar param set 17440707 0x0010 0000000000000000

CRC рассчитывается отдельно, настройка runtime.crc_mode не меняется.
На шине RS-485 должен быть один мастер. Перед записью проверяйте
назначение индекса и формат по паспорту конкретной модели.
"""


def _option(tokens: list[str], name: str, default: str) -> str:
    if tokens.count(name) > 1:
        raise ValueError(f"Duplicate {name} option")
    if name not in tokens:
        return default
    position = tokens.index(name)
    if position + 1 >= len(tokens) or tokens[position + 1].startswith("--"):
        raise ValueError(f"{name} requires a value")
    value = tokens.pop(position + 1)
    tokens.pop(position)
    return value


def _switch(tokens: list[str], name: str) -> bool:
    if tokens.count(name) > 1:
        raise ValueError(f"Duplicate {name} flag")
    if name not in tokens:
        return False
    tokens.remove(name)
    return True


def _expect(tokens: list[str], count: int, usage: str) -> None:
    if len(tokens) != count or any(token.startswith("--") for token in tokens):
        raise ValueError(f"Usage: {usage}; see 'help pulsar'")


def _serial_exchange(ctx: CommandContext, request: bytes, *, function: int,
                     address: str | None, request_id: int = 0,
                     payload_length: int | None = None):
    from .commands import _print_exchange, ensure_connected

    settings = getattr(ctx.transport, "settings", None)
    if settings is None:
        settings = effective_connection(ctx.config)
    if settings.bytesize != 8 or settings.parity.upper() != "N" or settings.stopbits != 1:
        raise ValueError(
            f"Pulsar requires 8N1 (configured {settings.bytesize}{settings.parity}{settings.stopbits:g}); "
            "use --parity N --bytesize 8 --stopbits 1 before 'pulsar'"
        )
    ensure_connected(ctx)
    # CRC already calculated; do not let the Modbus send setting change the frame.
    exchange = ctx.transport.exchange(request, crc_mode_override="none")
    # Never leave stale Modbus registers in the script 'last' result.
    ctx.last_response = None
    _print_exchange(ctx, exchange.tx, exchange.rx, exchange.elapsed_ms, decode_override=False)
    if not exchange.rx:
        raise RuntimeError("No Pulsar response; check address, wiring, 9600 8N1 and RS-485 bus ownership")
    return parse_response(exchange.rx, address=address, function=function,
                          request_id=request_id, payload_length=payload_length)


def _preview(ctx: CommandContext, request: bytes) -> None:
    ctx.console.print("DRY RUN: no bytes sent to RS-485", markup=False)
    ctx.console.print("TX " + request.hex(" ").upper(), markup=False)
    ctx.console.print("Add --execute only after verifying model-specific parameter permissions.", markup=False)


def execute_pulsar(ctx: CommandContext, args: list[str]) -> None:
    ru = ctx.language.lower() == "ru"
    if not args or args[0].lower() in {"help", "-h", "--help"}:
        ctx.console.print(HELP_RU if ru else HELP_EN, markup=False)
        return

    cmd = args[0].lower()
    if cmd == "decode":
        if len(args) < 2:
            raise ValueError("Usage: pulsar decode <hex-frame...>")
        try:
            raw = bytes.fromhex(" ".join(args[1:]))
        except ValueError:
            raise ValueError("Invalid HEX frame") from None
        response = parse_response(raw)
        ctx.console.print(f"Pulsar address: {response.address}", markup=False)
        ctx.console.print(f"Function: 0x{response.function:02X}; request ID: 0x{response.request_id:04X}; CRC: OK", markup=False)
        ctx.console.print("Data: " + response.payload.hex(" ").upper(), markup=False)
        return

    if cmd == "discover":
        tokens = args[1:].copy()
        allow = _switch(tokens, "--single")
        _expect(tokens, 0, "pulsar discover --single")
        if not allow:
            raise ValueError("Broadcast can collide on multi-device RS-485; add --single only on an isolated one-meter bus")
        request = read_parameter_request("00000000", 1, request_id=0xE679)
        reply = _serial_exchange(ctx, request, function=0x0A, address=None,
                                 request_id=0xE679, payload_length=8)
        ctx.console.print(f"Pulsar address: {reply.address}", markup=False)
        return

    if cmd == "read":
        tokens = args[1:].copy()
        channel = parse_number(_option(tokens, "--channel", "1"), maximum=32, name="channel")
        if not 1 <= channel <= 32:
            raise ValueError("Channel must be 1..32")
        fmt = _option(tokens, "--format", "float").lower()
        if fmt not in {"float", "s32", "u32", "f64", "raw"}:
            raise ValueError("Channel format must be float, s32, u32, f64 or raw")
        _expect(tokens, 1, "pulsar read <address> [--channel N] [--format float|s32|u32|f64|raw]")
        request = read_channel_request(tokens[0], channel)
        reply = _serial_exchange(ctx, request, function=0x01, address=tokens[0],
                                 payload_length=None if fmt == "raw" else 8 if fmt == "f64" else 4)
        value = decode_value(reply.payload, fmt)
        ctx.console.print(f"Pulsar {reply.address} channel {channel}: {value}" +
                          (" m3" if fmt == "float" and channel == 1 else ""), markup=False)
        return

    if cmd in {"param", "parameter", "params"}:
        if len(args) < 2:
            raise ValueError("Usage: pulsar param get|set <address> <index> ...")
        operation = args[1].lower()
        tokens = args[2:].copy()
        if operation in {"get", "read"}:
            fmt = _option(tokens, "--format", "raw").lower()
            widths = {"raw": 8, "u8": 1, "u16": 2, "u32": 4, "s32": 4, "float": 4, "f64": 8}
            if fmt not in widths:
                raise ValueError("Invalid parameter format; use raw|u8|u16|u32|s32|float|f64")
            _expect(tokens, 2, "pulsar param get <address> <index> [--format raw|u8|u16|u32|s32|float|f64]")
            index = parse_number(tokens[1], name="parameter index")
            request = read_parameter_request(tokens[0], index)
            reply = _serial_exchange(ctx, request, function=0x0A,
                                     address=tokens[0], payload_length=8)
            ctx.console.print(f"Parameter 0x{index:04X} raw: " + reply.payload.hex(" ").upper(), markup=False)
            if fmt != "raw":
                ctx.console.print(f"{fmt} (first {widths[fmt]} bytes LE): "
                                  f"{decode_value(reply.payload[:widths[fmt]], fmt)}", markup=False)
            return
        if operation in {"set", "write"}:
            execute = _switch(tokens, "--execute")
            _expect(tokens, 3, "pulsar param set <address> <index> <16-hex-digits> [--execute]")
            index = parse_number(tokens[1], name="parameter index")
            request = write_parameter_request(tokens[0], index, parse_value_bytes(tokens[2]))
            if not execute:
                _preview(ctx, request)
                return
            reply = _serial_exchange(ctx, request, function=0x0B, address=tokens[0], payload_length=2)
            validate_parameter_write_response(reply)
            ctx.console.print(f"Pulsar {reply.address}: parameter 0x{index:04X} write acknowledged", markup=False)
            return
        raise ValueError("Usage: pulsar param get|set <address> <index> ...")

    if cmd in {"time", "clock"}:
        if len(args) < 2:
            raise ValueError("Usage: pulsar time get|set <address> ...")
        operation = args[1].lower()
        tokens = args[2:].copy()
        if operation in {"get", "read"}:
            _expect(tokens, 1, "pulsar time get <address>")
            request = read_clock_request(tokens[0])
            reply = _serial_exchange(ctx, request, function=0x04, address=tokens[0], payload_length=6)
            ctx.console.print(f"Pulsar {reply.address} time: {decode_clock(reply.payload) or 'not set'}", markup=False)
            return
        if operation in {"set", "write"}:
            execute = _switch(tokens, "--execute")
            _expect(tokens, 2, "pulsar time set <address> YYYY-MM-DDTHH:MM:SS [--execute]")
            request = write_clock_request(tokens[0], tokens[1])
            if not execute:
                _preview(ctx, request)
                return
            reply = _serial_exchange(ctx, request, function=0x05, address=tokens[0], payload_length=4)
            validate_clock_write_response(reply)
            ctx.console.print(f"Pulsar {reply.address}: time write acknowledged; verify with 'pulsar time get'", markup=False)
            return
        raise ValueError("Usage: pulsar time get|set <address> ...")

    raise ValueError("Unknown Pulsar command; see 'help pulsar'")
