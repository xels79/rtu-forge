from __future__ import annotations

import configparser
import shlex
import time
from dataclasses import dataclass
from pathlib import Path

from rich.console import Console
from rich.table import Table

from .config import OPTION_SPECS, option_spec, parse_value, save_config
from .formatting import hex_line, parse_hex_bytes, prefix
from .scripts import ScriptStore
from .transport import SerialTransport


INTERACTIVE_HELP = """\
Commands:
  connect                         Connect using current connection options
  disconnect                      Close serial connection
  send <hex...>                   Send one Modbus RTU frame and print response
  add script <name>               Capture commands until 'end script'
  run script <name>               Run a stored script
  scripts | ls | list             List stored scripts
  show script <name>              Show script contents
  delete script <name>            Delete a stored script
  options                         Show all mutable options
  options connection              Show connection options only
  set options <name> <value>      Change and persist an option
  pause <ms>                      Sleep; useful inside scripts
  history                         Show recent interactive commands
  history clear                   Clear persistent history
  help                            Show this help
  exit | quit                     Leave the shell
"""


@dataclass
class CommandContext:
    config_path: Path
    config: configparser.ConfigParser
    scripts: ScriptStore
    transport: SerialTransport
    console: Console


def _print_exchange(ctx: CommandContext, tx: bytes, rx: bytes, elapsed_ms: float) -> None:
    runtime = ctx.config["runtime"]
    uppercase = runtime.getboolean("uppercase_hex")
    stamped = runtime.getboolean("timestamps")
    if runtime.getboolean("show_tx"):
        ctx.console.print(f"{prefix(stamped)}[cyan]TX[/cyan] {hex_line(tx, uppercase)}")
    if runtime.getboolean("show_rx"):
        payload = hex_line(rx, uppercase) if rx else "<timeout / no data>"
        ctx.console.print(f"{prefix(stamped)}[green]RX[/green] {payload} [dim]({elapsed_ms:.1f} ms)[/dim]")


def ensure_connected(ctx: CommandContext) -> None:
    if ctx.transport.connected:
        return
    if not ctx.config["runtime"].getboolean("auto_connect"):
        raise RuntimeError("Not connected. Use connect or enable runtime.auto_connect.")
    ctx.transport.connect()
    ctx.console.print(f"[green]Connected[/green] {ctx.transport.endpoint}")


def send_frame(ctx: CommandContext, payload: str) -> None:
    ensure_connected(ctx)
    raw = parse_hex_bytes(payload)
    exchange = ctx.transport.exchange(raw)
    _print_exchange(ctx, exchange.tx, exchange.rx, exchange.elapsed_ms)


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

    if command == "send":
        if len(parts) < 2:
            raise ValueError("Usage: send <hex bytes...>")
        send_frame(ctx, " ".join(parts[1:]))
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
        ctx.console.print(INTERACTIVE_HELP)
        return None

    if command in {"exit", "quit"}:
        if from_script:
            raise ValueError("exit/quit is not allowed inside scripts")
        return "exit"

    if command == "add" and len(parts) >= 3 and parts[1].lower() == "script":
        if from_script:
            raise ValueError("add script is interactive-only")
        return "add-script:" + " ".join(parts[2:])

    if command == "history":
        return "history-clear" if len(parts) > 1 and parts[1].lower() == "clear" else "history-show"

    raise ValueError(f"Unknown command: {command}. Use 'help'.")
