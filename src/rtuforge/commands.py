from __future__ import annotations

import configparser
import shlex
import time
from dataclasses import dataclass
from pathlib import Path

import serial.tools.list_ports
from rich.console import Console
from rich.table import Table

from .config import OPTION_SPECS, option_spec, parse_value, save_config
from .formatting import hex_line, parse_hex_bytes, prefix
from .i18n import command_help, interactive_help, message
from .modbus import decode_response, format_decoded_response
from .scripts import ScriptStore
from .transport import SerialTransport

HELP_ALIASES = {"ls": "scripts", "list": "scripts", "cls": "clear", "quit": "exit"}


@dataclass
class CommandContext:
    config_path: Path
    config: configparser.ConfigParser
    scripts: ScriptStore
    transport: SerialTransport
    console: Console

    @property
    def language(self) -> str:
        return self.config.get("ui", "language", fallback="en")


def _print_exchange(
    ctx: CommandContext,
    tx: bytes,
    rx: bytes,
    elapsed_ms: float,
    *,
    decode_override: bool | None = None,
) -> None:
    runtime = ctx.config["runtime"]
    uppercase = runtime.getboolean("uppercase_hex")
    stamped = runtime.getboolean("timestamps")
    if runtime.getboolean("show_tx"):
        ctx.console.print(f"{prefix(stamped)}[cyan]TX[/cyan] {hex_line(tx, uppercase)}")
    if runtime.getboolean("show_rx"):
        payload = hex_line(rx, uppercase) if rx else "<timeout / no data>"
        ctx.console.print(f"{prefix(stamped)}[green]RX[/green] {payload} [dim]({elapsed_ms:.1f} ms)[/dim]")
        decode_enabled = runtime.getboolean("decode_rx", fallback=True) if decode_override is None else decode_override
        if rx and decode_enabled:
            for line in format_decoded_response(decode_response(rx), uppercase):
                ctx.console.print(f"   {line}")


def show_ports(ctx: CommandContext) -> None:
    ports = list(serial.tools.list_ports.comports())
    if not ports:
        ctx.console.print("No serial ports found.")
        return
    table = Table(show_header=True, header_style="bold")
    table.add_column("Port")
    table.add_column("Description")
    table.add_column("HWID")
    for port in ports:
        table.add_row(str(port.device), str(port.description), str(port.hwid))
    ctx.console.print(table)


def show_status(ctx: CommandContext) -> None:
    connection = ctx.config["connection"]
    runtime = ctx.config["runtime"]
    state = "CONNECTED" if ctx.transport.connected else "DISCONNECTED"
    ctx.console.print(f"Connection: {state}")
    if ctx.transport.connected:
        ctx.console.print(f"\nEndpoint:   {ctx.transport.endpoint}")
    ctx.console.print(f"Port:       {connection.get('port')}")
    ctx.console.print(f"Baudrate:   {connection.get('baudrate')}")
    ctx.console.print(
        f"Format:     {connection.get('bytesize')}{connection.get('parity')}{connection.get('stopbits')}"
    )
    ctx.console.print(f"Timeout:    {connection.get('timeout_ms')} ms")
    ctx.console.print(f"CRC mode:   {runtime.get('crc_mode')}")
    ctx.console.print(f"Decode RX:  {runtime.get('decode_rx', 'true')}")
    ctx.console.print(f"Language:   {ctx.language}")


def ensure_connected(ctx: CommandContext) -> None:
    if ctx.transport.connected:
        return
    if not ctx.config["runtime"].getboolean("auto_connect"):
        raise RuntimeError("Not connected. Use connect or enable runtime.auto_connect.")
    ctx.transport.connect()
    ctx.console.print(f"[green]Connected[/green] {ctx.transport.endpoint}")


def send_frame(ctx: CommandContext, payload: str, *, decode_override: bool | None = None) -> None:
    ensure_connected(ctx)
    raw = parse_hex_bytes(payload)
    exchange = ctx.transport.exchange(raw)
    _print_exchange(
        ctx,
        exchange.tx,
        exchange.rx,
        exchange.elapsed_ms,
        decode_override=decode_override,
    )


def _parse_send_arguments(parts: list[str]) -> tuple[str, bool | None]:
    decode_override: bool | None = None
    payload_parts: list[str] = []
    for part in parts:
        lowered = part.lower()
        if lowered in {"-d", "--decode"}:
            if decode_override is False:
                raise ValueError("send: --decode and --raw cannot be used together")
            decode_override = True
        elif lowered in {"-r", "--raw"}:
            if decode_override is True:
                raise ValueError("send: --decode and --raw cannot be used together")
            decode_override = False
        else:
            payload_parts.append(part)
    if not payload_parts:
        raise ValueError("Usage: send [-d|--decode|-r|--raw] <hex bytes...>")
    return " ".join(payload_parts), decode_override


def show_options(ctx: CommandContext, section: str | None = None) -> None:
    table = Table(title="RTU Forge options")
    table.add_column("Section")
    table.add_column("Name")
    table.add_column("Value")
    table.add_column("Description")
    for spec in OPTION_SPECS:
        if section and spec.section.lower() != section.lower():
            continue
        table.add_row(spec.section, spec.name, ctx.config[spec.section].get(spec.name, ""), spec.description)
    ctx.console.print(table)


def set_option(ctx: CommandContext, name: str, value: str) -> None:
    spec = option_spec(name)
    parsed = parse_value(spec, value)
    was_connection = spec.section == "connection"
    if was_connection and ctx.transport.connected:
        ctx.transport.disconnect()
        ctx.console.print("[yellow]Disconnected because a connection option changed.[/yellow]")
    ctx.config[spec.section][spec.name] = parsed
    save_config(ctx.config_path, ctx.config)
    ctx.console.print(f"[green]Saved[/green] {spec.section}.{spec.name} = {parsed}")


def run_script(ctx: CommandContext, name: str) -> None:
    lines = ctx.scripts.get(name)
    if not lines:
        ctx.console.print(f"[yellow]Script '{name}' is empty.[/yellow]")
        return
    delay = ctx.config["runtime"].getint("inter_command_delay_ms") / 1000.0
    for index, line in enumerate(lines, start=1):
        ctx.console.print(f"[dim]{index:02d}> {line}[/dim]")
        execute_command(ctx, line, from_script=True)
        if index < len(lines) and delay > 0:
            time.sleep(delay)


def execute_command(ctx: CommandContext, line: str, *, from_script: bool = False) -> str | None:
    stripped = line.strip()
    if not stripped or stripped.startswith("#"):
        return None

    parts = shlex.split(stripped)
    command = parts[0].lower()

    if command == "connect":
        ctx.transport.connect()
        ctx.console.print(f"[green]Connected[/green] {ctx.transport.endpoint}")
        return None

    if command == "disconnect":
        ctx.transport.disconnect()
        ctx.console.print("[yellow]Disconnected[/yellow]")
        return None

    if command == "ports":
        show_ports(ctx)
        return None

    if command == "status":
        show_status(ctx)
        return None

    if command == "send":
        payload, decode_override = _parse_send_arguments(parts[1:])
        send_frame(ctx, payload, decode_override=decode_override)
        return None

    if command == "pause":
        if len(parts) != 2:
            raise ValueError("Usage: pause <milliseconds>")
        time.sleep(float(parts[1].replace(",", ".")) / 1000.0)
        return None

    if command in {"scripts", "ls", "list"}:
        names = ctx.scripts.list()
        if names:
            for name in names:
                ctx.console.print(name)
        else:
            ctx.console.print("[dim]No scripts.[/dim]")
        return None

    if command == "show" and len(parts) >= 3 and parts[1].lower() == "script":
        name = " ".join(parts[2:])
        lines = ctx.scripts.get(name)
        for item in lines:
            ctx.console.print(item)
        return None

    if command == "delete" and len(parts) >= 3 and parts[1].lower() == "script":
        name = " ".join(parts[2:])
        ctx.scripts.delete(name)
        ctx.console.print(f"[green]Deleted[/green] {name}")
        return None

    if command == "run" and len(parts) >= 3 and parts[1].lower() == "script":
        run_script(ctx, " ".join(parts[2:]))
        return None

    if command == "options":
        section = parts[1] if len(parts) > 1 else None
        if section and section not in ctx.config.sections():
            raise ValueError(f"Unknown option section: {section}")
        show_options(ctx, section)
        return None

    if command == "set" and len(parts) >= 4 and parts[1].lower() in {"option", "options"}:
        set_option(ctx, parts[2], " ".join(parts[3:]))
        return None

    if command == "help":
        if len(parts) == 1:
            ctx.console.print(interactive_help(ctx.language))
            return None
        topic = HELP_ALIASES.get(parts[1].lower(), parts[1].lower())
        help_text = command_help(ctx.language, topic)
        if help_text is None:
            ctx.console.print(message(ctx.language, "unknown_help_topic", topic=parts[1]))
        else:
            ctx.console.print(help_text)
        return None

    if command in {"clear", "cls"}:
        if from_script:
            raise ValueError("clear/cls is not allowed inside scripts")
        return "clear-screen"

    if command in {"exit", "quit"}:
        if from_script:
            raise ValueError("exit/quit is not allowed inside scripts")
        return "exit"

    if command == "add" and len(parts) >= 3 and parts[1].lower() == "script":
        if from_script:
            raise ValueError("add script is interactive-only")
        return "add-script:" + " ".join(parts[2:])

    if command == "history":
        if from_script:
            raise ValueError("history is not allowed inside scripts")
        return "history-clear" if len(parts) > 1 and parts[1].lower() == "clear" else "history-show"

    raise ValueError(f"Unknown command: {command}. Use 'help'.")
