from __future__ import annotations

import argparse
import shlex
import sys
from dataclasses import dataclass
from pathlib import Path

import serial.tools.list_ports
from prompt_toolkit import PromptSession
from prompt_toolkit.history import FileHistory
from rich.console import Console
from rich.table import Table

from .config import load_config
from .connection import parse_connection_overrides
from .formatting import hex_line, prefix
from .paths import resolve_runtime_paths
from .stand_completion import StandForgeCompleter
from .stand_config import StandSettings, load_stand_settings, save_stand_settings, with_overrides
from .stand_protocol import OUTPUT_CHANNEL_NAMES, OUTPUT_RANGES, build_output_request, build_tank_request, build_write_multiple_coils, validate_write_response
from .transport import SerialTransport


@dataclass
class StandContext:
    config_path: Path
    stand_config_path: Path
    home_path: Path
    config: object
    settings: StandSettings
    transport: SerialTransport
    console: Console
    one_shot: bool = False

    @property
    def language(self) -> str:
        return self.config.get("ui", "language", fallback="en")


TEXT = {
    "en": {
        "banner": "Stand Forge - test bench console. Type 'help'.",
        "connected": "Connected {endpoint}",
        "disconnected": "Disconnected",
        "no_ports": "No serial ports found.",
        "tank_ok": "Tank {tank}: {level} (relays {first}/{second})",
        "output_ok": "{name}: {percent:g}% -> {raw} {unit} (channel {channel})",
        "reset_ok": "Stand reset: all tanks empty, all analog outputs 0%",
        "saved": "Stand settings saved: {path}",
        "error": "Error: {error}",
    },
    "ru": {
        "banner": "Stand Forge - консоль тестового стенда. Справка: help",
        "connected": "Подключено: {endpoint}",
        "disconnected": "Отключено",
        "no_ports": "Последовательные порты не найдены.",
        "tank_ok": "Бак {tank}: {level} (реле {first}/{second})",
        "output_ok": "{name}: {percent:g}% -> {raw} {unit} (канал {channel})",
        "reset_ok": "Стенд сброшен: все баки empty, все аналоговые выходы 0%",
        "saved": "Настройки стенда сохранены: {path}",
        "error": "Ошибка: {error}",
    },
}


def _lang(ctx: StandContext) -> str:
    return "ru" if ctx.language.lower() == "ru" else "en"


def _t(ctx: StandContext, key: str, **values: object) -> str:
    return TEXT[_lang(ctx)][key].format(**values)


def _promote_clean_flag(argv: list[str]) -> list[str]:
    if not any(item in {"-c", "--clean"} for item in argv):
        return argv
    return ["--clean", *(item for item in argv if item not in {"-c", "--clean"})]


def _language_for_argv(argv: list[str]) -> str:
    probe = argparse.ArgumentParser(add_help=False)
    probe.add_argument("--home")
    probe.add_argument("--config")
    probe_args, _ = probe.parse_known_args(argv)
    try:
        path = resolve_runtime_paths(home=probe_args.home, config=probe_args.config).config
    except ValueError:
        return "en"
    if not path.exists():
        return "en"
    try:
        config = load_config(path)
    except Exception:
        return "en"
    return config.get("ui", "language", fallback="en")


def _console(*, stderr: bool = False) -> Console:
    return Console(stderr=stderr, highlight=False)


def _clean(ctx: StandContext) -> bool:
    return ctx.config["runtime"].getboolean("clean_output", fallback=False)


def _ensure_connected(ctx: StandContext) -> None:
    if ctx.transport.connected:
        return
    if not ctx.config["runtime"].getboolean("auto_connect", fallback=True):
        raise RuntimeError("Not connected. Use 'connect'.")
    ctx.transport.connect()
    if not ctx.one_shot and not _clean(ctx):
        ctx.console.print(f"[green]{_t(ctx, 'connected', endpoint=ctx.transport.endpoint)}[/green]")


def _print_exchange(ctx: StandContext, tx: bytes, rx: bytes, elapsed_ms: float) -> None:
    runtime = ctx.config["runtime"]
    uppercase = runtime.getboolean("uppercase_hex", fallback=True)
    if _clean(ctx):
        if runtime.getboolean("show_tx", fallback=True):
            ctx.console.print(hex_line(tx, uppercase), style="cyan", markup=False)
        if runtime.getboolean("show_rx", fallback=True) and rx:
            ctx.console.print(hex_line(rx, uppercase), style="green", markup=False)
        return
    stamped = runtime.getboolean("timestamps", fallback=False)
    if runtime.getboolean("show_tx", fallback=True):
        ctx.console.print(f"{prefix(stamped)}TX {hex_line(tx, uppercase)}", style="cyan", markup=False)
    if runtime.getboolean("show_rx", fallback=True):
        payload = hex_line(rx, uppercase) if rx else "<no data>"
        ctx.console.print(f"{prefix(stamped)}RX {payload} ({elapsed_ms:.1f} ms)", style="green", markup=False)


def _exchange(ctx: StandContext, request: bytes) -> None:
    _ensure_connected(ctx)
    exchange = ctx.transport.exchange(request, crc_mode_override="append")
    _print_exchange(ctx, exchange.tx, exchange.rx, exchange.elapsed_ms)
    validate_write_response(request, exchange.rx)


def _tank(ctx: StandContext, parts: list[str]) -> None:
    if len(parts) != 2:
        raise ValueError("Usage: tank <1..4> <empty|middle|full>")
    try:
        tank = int(parts[0])
    except ValueError:
        raise ValueError("Tank number must be in range 1..4") from None
    level = parts[1].lower()
    _exchange(ctx, build_tank_request(ctx.settings.relay_address, tank, level))
    if not _clean(ctx):
        first = (tank - 1) * 2 + 1
        ctx.console.print(_t(ctx, "tank_ok", tank=tank, level=level, first=first, second=first + 1), markup=False)


def _output(ctx: StandContext, parts: list[str]) -> None:
    if len(parts) == 3 and parts[0].lower() == "pressure" and parts[1].lower() in {"low", "high"}:
        parts = [f"pressure-{parts[1].lower()}", parts[2]]
    if len(parts) != 2:
        raise ValueError("Usage: output <temperature|humidity|pressure-low|pressure-high> <0..100>")
    request, raw, name, percent = build_output_request(
        ctx.settings.output_address, parts[0], parts[1], ctx.settings.range_spec
    )
    _exchange(ctx, request)
    if not _clean(ctx):
        channel = OUTPUT_CHANNEL_NAMES.index(name) + 1
        ctx.console.print(
            _t(ctx, "output_ok", name=name, percent=percent, raw=raw, unit=ctx.settings.range_spec.unit, channel=channel),
            markup=False,
        )


def _reset(ctx: StandContext, parts: list[str]) -> None:
    if parts and [item.lower() for item in parts] != ["all"]:
        raise ValueError("Usage: reset [all]")

    requests: list[tuple[str, bytes]] = [
        (
            "relays",
            build_write_multiple_coils(
                ctx.settings.relay_address, 0, [False] * 8
            ),
        )
    ]
    for name in OUTPUT_CHANNEL_NAMES:
        request, _, _, _ = build_output_request(
            ctx.settings.output_address, name, 0, ctx.settings.range_spec
        )
        requests.append((name, request))

    errors: list[str] = []
    for name, request in requests:
        try:
            _exchange(ctx, request)
        except (RuntimeError, OSError) as exc:
            errors.append(f"{name}: {exc}")

    if errors:
        raise RuntimeError("Reset incomplete: " + "; ".join(errors))
    if not _clean(ctx):
        ctx.console.print(_t(ctx, "reset_ok"), markup=False)


def _show_ports(ctx: StandContext) -> None:
    ports = list(serial.tools.list_ports.comports())
    if not ports:
        ctx.console.print(_t(ctx, "no_ports"), markup=False)
        return
    table = Table(show_header=True, header_style="bold")
    for name in ("Port", "Description", "HWID"):
        table.add_column(name)
    for port in ports:
        table.add_row(str(port.device), str(port.description), str(port.hwid))
    ctx.console.print(table)


def _show_status(ctx: StandContext) -> None:
    settings = ctx.transport.settings
    state = "connected" if ctx.transport.connected else "disconnected"
    spec = ctx.settings.range_spec
    ctx.console.print(f"Connection: {state}", markup=False)
    ctx.console.print(f"Endpoint:   {settings.endpoint}", markup=False)
    ctx.console.print(f"Relay ID:   {ctx.settings.relay_address}", markup=False)
    ctx.console.print(f"Output ID:  {ctx.settings.output_address}", markup=False)
    ctx.console.print(f"Output:     {ctx.settings.output_range} ({spec.minimum}..{spec.maximum} {spec.unit})", markup=False)
    ctx.console.print("Tanks:      1=CH1/2, 2=CH3/4, 3=CH5/6, 4=CH7/8", markup=False)
    ctx.console.print("Analog:     CH1=temperature, CH2=humidity, CH3=pressure-low, CH4=pressure-high", markup=False)


def _show_paths(ctx: StandContext) -> None:
    ctx.console.print(f"Home:         {ctx.home_path}", markup=False)
    ctx.console.print(f"RTU config:   {ctx.config_path}", markup=False)
    ctx.console.print(f"Stand config: {ctx.stand_config_path}", markup=False)
    ctx.console.print(f"History:      {ctx.home_path / '.standforge_history'}", markup=False)


def _set(ctx: StandContext, parts: list[str]) -> None:
    if len(parts) != 2:
        raise ValueError("Usage: set <relay-id|output-id|output-range> <value>")
    name, value = parts[0].lower(), parts[1]
    if name == "relay-id":
        updated = with_overrides(ctx.settings, relay_address=int(value))
    elif name == "output-id":
        updated = with_overrides(ctx.settings, output_address=int(value))
    elif name == "output-range":
        updated = with_overrides(ctx.settings, output_range=value)
    else:
        raise ValueError("Unknown setting. Use relay-id, output-id or output-range.")
    save_stand_settings(ctx.stand_config_path, updated)
    ctx.settings = updated
    ctx.console.print(_t(ctx, "saved", path=ctx.stand_config_path), markup=False)


def _help(ctx: StandContext, topic: str | None = None) -> None:
    if topic == "tank":
        text = "tank <1..4> <empty|middle|full>\n  empty=both off, middle=lower on, full=both on"
    elif topic == "output":
        text = (
            "output <name> <0..100>\n"
            "  names: temperature, humidity, pressure-low, pressure-high\n"
            "  aliases: output pressure low 25 / output pressure high 75"
        )
    elif topic == "set":
        text = "set relay-id <1..247>\nset output-id <1..247>\nset output-range <0-20ma|4-20ma|0-10v>"
    elif topic == "reset":
        text = "reset [all]\n  all tanks -> empty; all four analog outputs -> 0%"
    else:
        text = (
            "Stand Forge commands:\n"
            "  tank <1..4> <empty|middle|full>\n"
            "  output <temperature|humidity|pressure-low|pressure-high> <0..100>\n"
            "  set <relay-id|output-id|output-range> <value>\n"
            "  reset [all]\n"
            "  connect | disconnect | ports | status | paths\n"
            "  clear | help [topic] | exit\n\n"
            "Examples:\n"
            "  tank 1 middle\n"
            "  tank 4 full\n"
            "  output temperature 50\n"
            "  output pressure high 75\n"
            "  reset\n"
            "  set output-range 4-20ma"
        )
    ctx.console.print(text, markup=False)


def execute_command(ctx: StandContext, line: str) -> str | None:
    stripped = line.strip()
    if not stripped or stripped.startswith("#"):
        return None
    parts = shlex.split(stripped, posix=True)
    command, args = parts[0].lower(), parts[1:]
    if command == "tank":
        _tank(ctx, args)
    elif command == "output":
        _output(ctx, args)
    elif command == "reset":
        _reset(ctx, args)
    elif command == "connect":
        if args:
            raise ValueError("Usage: connect")
        ctx.transport.connect()
        if not ctx.one_shot and not _clean(ctx):
            ctx.console.print(f"[green]{_t(ctx, 'connected', endpoint=ctx.transport.endpoint)}[/green]")
    elif command == "disconnect":
        if args:
            raise ValueError("Usage: disconnect")
        ctx.transport.disconnect()
        if not ctx.one_shot and not _clean(ctx):
            ctx.console.print(f"[yellow]{_t(ctx, 'disconnected')}[/yellow]")
    elif command == "ports":
        _show_ports(ctx)
    elif command == "status":
        _show_status(ctx)
    elif command == "paths":
        _show_paths(ctx)
    elif command == "set":
        _set(ctx, args)
    elif command == "help":
        _help(ctx, args[0].lower() if args else None)
    elif command in {"clear", "cls"}:
        return "clear"
    elif command in {"exit", "quit"}:
        return "exit"
    else:
        raise ValueError(f"Unknown command: {command}")
    return None


def _toolbar(ctx: StandContext) -> str:
    state = "connected" if ctx.transport.connected else "disconnected"
    return f" {state} | {ctx.transport.endpoint} | relay={ctx.settings.relay_address} output={ctx.settings.output_address} "


def run_shell(ctx: StandContext) -> None:
    history_path = ctx.home_path / ".standforge_history"
    history_path.parent.mkdir(parents=True, exist_ok=True)
    session = PromptSession(
        history=FileHistory(str(history_path)),
        completer=StandForgeCompleter(),
        complete_while_typing=False,
    )
    ctx.console.print(_t(ctx, "banner"), markup=False)
    while True:
        try:
            line = session.prompt("stand> ", bottom_toolbar=lambda: _toolbar(ctx))
        except (EOFError, KeyboardInterrupt):
            ctx.console.print()
            break
        try:
            action = execute_command(ctx, line)
            if action == "exit":
                break
            if action == "clear":
                ctx.console.clear()
        except KeyboardInterrupt:
            ctx.transport.disconnect()
            ctx.console.print()
        except Exception as exc:
            ctx.console.print(_t(ctx, "error", error=exc), markup=False)
    ctx.transport.disconnect()


def build_parser(language: str = "en") -> argparse.ArgumentParser:
    is_ru = language.lower() == "ru"
    parser = argparse.ArgumentParser(
        prog="standforge",
        description=("Консоль управления тестовым стендом на Waveshare Modbus RTU" if is_ru else "Waveshare Modbus RTU test-bench console"),
    )
    parser.add_argument("-c", "--clean", action="store_true")
    parser.add_argument("--home")
    parser.add_argument("--config")
    parser.add_argument("--stand-config")
    parser.add_argument("--port")
    parser.add_argument("--baudrate")
    parser.add_argument("--bytesize")
    parser.add_argument("--parity")
    parser.add_argument("--stopbits")
    parser.add_argument("--timeout-ms")
    parser.add_argument("--relay-id", type=int)
    parser.add_argument("--output-id", type=int)
    parser.add_argument("--output-range", choices=tuple(OUTPUT_RANGES))
    parser.add_argument("command", nargs=argparse.REMAINDER)
    return parser


def main() -> int:
    argv = _promote_clean_flag(sys.argv[1:])
    language = _language_for_argv(argv)
    args = build_parser(language).parse_args(argv)
    try:
        paths = resolve_runtime_paths(home=args.home, config=args.config)
        stand_path = Path(args.stand_config).expanduser().resolve() if args.stand_config else paths.home / "stand.ini"
        if args.command == ["paths"] and not paths.config.exists():
            console = _console()
            console.print(f"Home:         {paths.home}", markup=False)
            console.print(f"RTU config:   {paths.config}", markup=False)
            console.print(f"Stand config: {stand_path}", markup=False)
            return 0
        config = load_config(paths.config)
        if args.clean:
            config["runtime"]["clean_output"] = "true"
        overrides = parse_connection_overrides(
            {"port": args.port, "baudrate": args.baudrate, "bytesize": args.bytesize, "parity": args.parity, "stopbits": args.stopbits, "timeout_ms": args.timeout_ms}
        )
        settings = with_overrides(
            load_stand_settings(stand_path),
            relay_address=args.relay_id,
            output_address=args.output_id,
            output_range=args.output_range,
        )
    except Exception as exc:
        _console(stderr=True).print(f"Error: {exc}", markup=False)
        return 1

    ctx = StandContext(
        config_path=paths.config,
        stand_config_path=stand_path,
        home_path=paths.home,
        config=config,
        settings=settings,
        transport=SerialTransport(config, overrides),
        console=_console(),
        one_shot=True,
    )
    if not args.command or args.command == ["shell"]:
        ctx.one_shot = False
        run_shell(ctx)
        return 0
    try:
        execute_command(ctx, shlex.join(args.command))
        return 0
    except KeyboardInterrupt:
        return 130
    except (ValueError, RuntimeError, OSError) as exc:
        _console(stderr=True).print(_t(ctx, "error", error=exc), markup=False)
        return 1
    finally:
        ctx.transport.disconnect()


if __name__ == "__main__":
    raise SystemExit(main())
