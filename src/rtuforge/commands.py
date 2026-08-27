from __future__ import annotations

import configparser
import shlex
import time
from dataclasses import dataclass, field
from pathlib import Path

import serial.tools.list_ports
from rich.console import Console
from rich.table import Table

from .config import OPTION_SPECS, option_spec, parse_value, save_config
from .formatting import hex_line, parse_hex_bytes, prefix
from .i18n import command_help, interactive_help, message
from .modbus import decode_response, format_decoded_response
from .runtime_text import tr
from .scripts import ScriptStore
from .transport import SerialTransport

HELP_ALIASES = {"ls": "scripts", "list": "scripts", "cls": "clear", "quit": "exit"}

OPTIONS_TABLE_TEXT = {
    "en": {"title": "RTU Forge options", "section": "Section", "name": "Name", "value": "Value", "description": "Description"},
    "ru": {"title": "Параметры RTU Forge", "section": "Раздел", "name": "Параметр", "value": "Значение", "description": "Описание"},
}

OPTION_DESCRIPTIONS_RU = {
    "port": "Последовательный порт, например COM5 или /dev/ttyUSB0",
    "baudrate": "Скорость обмена", "bytesize": "Биты данных", "parity": "Чётность: N/E/O/M/S", "stopbits": "Стоп-биты",
    "timeout_ms": "Таймаут чтения последовательного порта, мс", "inter_command_delay_ms": "Пауза между командами скрипта, мс",
    "post_write_delay_ms": "Пауза после записи в последовательный порт, мс", "response_silence_ms": "Интервал тишины для определения конца ответа, мс",
    "max_response_bytes": "Максимальное количество байт одного ответа", "crc_mode": "Обработка CRC при отправке: auto/append/none",
    "auto_connect": "Автоподключение для send/run в one-shot режиме", "show_tx": "Показывать отправленные кадры",
    "show_rx": "Показывать принятые кадры", "decode_rx": "Расшифровывать Modbus RTU ответ после сырого RX",
    "clean_output": "Чистый вывод HEX без меток TX/RX, времени и длительности ответа",
    "timestamps": "Показывать время в строках TX/RX", "uppercase_hex": "Показывать HEX в верхнем регистре",
    "file": "Файл постоянной истории интерактивных команд", "max_entries": "Максимальное число записей истории",
    "language": "Язык справки и интерфейса: en/ru",
}


@dataclass
class RecordingState:
    mode: str | None = None
    lines: list[str] = field(default_factory=list)

    @property
    def active(self) -> bool:
        return self.mode in {"all", "rx"}

    def start(self, mode: str) -> None:
        self.mode = mode
        self.lines.clear()

    def clear(self) -> None:
        self.mode = None
        self.lines.clear()


@dataclass
class CommandContext:
    config_path: Path
    config: configparser.ConfigParser
    scripts: ScriptStore
    transport: SerialTransport
    console: Console
    one_shot: bool = False
    recording: RecordingState = field(default_factory=RecordingState)

    @property
    def language(self) -> str:
        return self.config.get("ui", "language", fallback="en")


def _clean_output(ctx: CommandContext) -> bool:
    return ctx.config["runtime"].getboolean("clean_output", fallback=False)


def _record_exchange(ctx: CommandContext, tx: bytes, rx: bytes, uppercase: bool) -> None:
    if not ctx.recording.active:
        return

    if ctx.recording.mode == "all":
        if _clean_output(ctx):
            ctx.recording.lines.append(hex_line(tx, uppercase))
            if rx:
                ctx.recording.lines.append(hex_line(rx, uppercase))
        else:
            ctx.recording.lines.append(f"TX {hex_line(tx, uppercase)}")
            ctx.recording.lines.append(f"RX {hex_line(rx, uppercase) if rx else ''}".rstrip())
    elif ctx.recording.mode == "rx":
        ctx.recording.lines.append(hex_line(rx, uppercase) if rx else "")


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
    clean = _clean_output(ctx)
    _record_exchange(ctx, tx, rx, uppercase)

    if clean:
        if runtime.getboolean("show_tx"):
            ctx.console.print(hex_line(tx, uppercase), markup=False)
        if runtime.getboolean("show_rx") and rx:
            ctx.console.print(hex_line(rx, uppercase), markup=False)
    else:
        stamped = runtime.getboolean("timestamps")
        if runtime.getboolean("show_tx"):
            ctx.console.print(f"{prefix(stamped)}[cyan]TX[/cyan] {hex_line(tx, uppercase)}")
        if runtime.getboolean("show_rx"):
            payload = hex_line(rx, uppercase) if rx else tr(ctx.language, "no_data")
            ctx.console.print(f"{prefix(stamped)}[green]RX[/green] {payload} [dim]({elapsed_ms:.1f} ms)[/dim]")

    if decode_override is not None:
        decode_enabled = decode_override
    elif clean:
        decode_enabled = False
    else:
        decode_enabled = runtime.getboolean("decode_rx", fallback=True)

    if rx and decode_enabled:
        for line in format_decoded_response(decode_response(rx), uppercase, ctx.language):
            ctx.console.print(f"   {line}", markup=False)


def show_ports(ctx: CommandContext) -> None:
    ports = list(serial.tools.list_ports.comports())
    if not ports:
        ctx.console.print(tr(ctx.language, "no_ports"), markup=False)
        return
    table = Table(show_header=True, header_style="bold")
    table.add_column(tr(ctx.language, "port_col"))
    table.add_column(tr(ctx.language, "description_col"))
    table.add_column(tr(ctx.language, "hwid_col"))
    for port in ports:
        table.add_row(str(port.device), str(port.description), str(port.hwid))
    ctx.console.print(table)


def show_status(ctx: CommandContext) -> None:
    connection = ctx.config["connection"]
    runtime = ctx.config["runtime"]
    state = tr(ctx.language, "connected_state" if ctx.transport.connected else "disconnected_state")
    ctx.console.print(f"{tr(ctx.language, 'connection')}: {state}", markup=False)
    if ctx.transport.connected:
        ctx.console.print(f"\n{tr(ctx.language, 'endpoint')}:   {ctx.transport.endpoint}", markup=False)
    ctx.console.print(f"{tr(ctx.language, 'port')}:       {connection.get('port')}", markup=False)
    ctx.console.print(f"{tr(ctx.language, 'baudrate')}:   {connection.get('baudrate')}", markup=False)
    ctx.console.print(f"{tr(ctx.language, 'format')}:     {connection.get('bytesize')}{connection.get('parity')}{connection.get('stopbits')}", markup=False)
    ctx.console.print(f"{tr(ctx.language, 'timeout')}:    {connection.get('timeout_ms')} ms", markup=False)
    ctx.console.print(f"{tr(ctx.language, 'crc_mode')}:   {runtime.get('crc_mode')}", markup=False)
    ctx.console.print(f"{tr(ctx.language, 'decode_rx')}:  {runtime.get('decode_rx', 'true')}", markup=False)
    ctx.console.print(f"{tr(ctx.language, 'clean_output')}: {runtime.get('clean_output', 'false')}", markup=False)
    ctx.console.print(f"{tr(ctx.language, 'language')}:   {ctx.language}", markup=False)


def ensure_connected(ctx: CommandContext) -> None:
    if ctx.transport.connected:
        return
    if not ctx.config["runtime"].getboolean("auto_connect"):
        raise RuntimeError(tr(ctx.language, "not_connected"))
    ctx.transport.connect()
    if not ctx.one_shot and not _clean_output(ctx):
        ctx.console.print(f"[green]{tr(ctx.language, 'connected', endpoint=ctx.transport.endpoint)}[/green]")


def send_frame(ctx: CommandContext, payload: str, *, decode_override: bool | None = None) -> None:
    ensure_connected(ctx)
    raw = parse_hex_bytes(payload)
    exchange = ctx.transport.exchange(raw)
    _print_exchange(ctx, exchange.tx, exchange.rx, exchange.elapsed_ms, decode_override=decode_override)


def _parse_decode_flags(parts: list[str], *, command: str) -> tuple[list[str], bool | None]:
    decode_override: bool | None = None
    remaining: list[str] = []
    for part in parts:
        lowered = part.lower()
        if lowered in {"-d", "--decode"}:
            if decode_override is False:
                raise ValueError(tr("en", f"{command}_conflict"))
            decode_override = True
        elif lowered in {"-r", "--raw"}:
            if decode_override is True:
                raise ValueError(tr("en", f"{command}_conflict"))
            decode_override = False
        else:
            remaining.append(part)
    return remaining, decode_override


def _parse_send_arguments(parts: list[str], language: str = "en") -> tuple[str, bool | None]:
    try:
        payload_parts, decode_override = _parse_decode_flags(parts, command="send")
    except ValueError:
        raise ValueError(tr(language, "send_conflict")) from None
    if not payload_parts:
        raise ValueError(tr(language, "send_usage"))
    return " ".join(payload_parts), decode_override


def _parse_run_arguments(parts: list[str], language: str = "en") -> tuple[str, bool | None]:
    if not parts:
        raise ValueError(tr(language, "run_usage"))
    decode_override: bool | None = None
    name_parts: list[str] = []
    for part in parts:
        lowered = part.lower()
        if lowered in {"-d", "--decode"}:
            if decode_override is False:
                raise ValueError(tr(language, "run_conflict"))
            decode_override = True
        elif lowered in {"-r", "--raw"}:
            if decode_override is True:
                raise ValueError(tr(language, "run_conflict"))
            decode_override = False
        elif part.startswith("-"):
            raise ValueError(tr(language, "run_unknown_flag", flag=part))
        else:
            name_parts.append(part)
    if not name_parts:
        raise ValueError(tr(language, "run_usage"))
    return " ".join(name_parts), decode_override


def show_options(ctx: CommandContext, section: str | None = None) -> None:
    language = "ru" if ctx.language.lower() == "ru" else "en"
    labels = OPTIONS_TABLE_TEXT[language]
    table = Table(title=labels["title"])
    table.add_column(labels["section"])
    table.add_column(labels["name"])
    table.add_column(labels["value"])
    table.add_column(labels["description"])
    for spec in OPTION_SPECS:
        if section and spec.section.lower() != section.lower():
            continue
        description = OPTION_DESCRIPTIONS_RU.get(spec.name, spec.description) if language == "ru" else spec.description
        table.add_row(spec.section, spec.name, ctx.config[spec.section].get(spec.name, ""), description)
    ctx.console.print(table)


def set_option(ctx: CommandContext, name: str, value: str) -> None:
    try:
        spec = option_spec(name)
    except KeyError:
        raise ValueError(tr(ctx.language, "unknown_option", name=name)) from None
    try:
        parsed = parse_value(spec, value)
    except ValueError:
        if spec.kind == "bool":
            raise ValueError(tr(ctx.language, "expected_boolean")) from None
        if spec.choices:
            raise ValueError(tr(ctx.language, "allowed_values", values=", ".join(spec.choices))) from None
        raise
    was_connection = spec.section == "connection"
    if was_connection and ctx.transport.connected:
        ctx.transport.disconnect()
        ctx.console.print(f"[yellow]{tr(ctx.language, 'connection_option_disconnect')}[/yellow]")
    ctx.config[spec.section][spec.name] = parsed
    save_config(ctx.config_path, ctx.config)
    ctx.console.print(f"[green]{tr(ctx.language, 'option_saved', section=spec.section, name=spec.name, value=parsed)}[/green]")


def run_script(ctx: CommandContext, name: str, *, decode_override: bool | None = None) -> None:
    try:
        lines = ctx.scripts.get(name)
    except KeyError:
        raise ValueError(tr(ctx.language, "script_not_found", name=name)) from None
    if not lines:
        ctx.console.print(f"[yellow]{tr(ctx.language, 'script_empty', name=name)}[/yellow]")
        return
    delay = ctx.config["runtime"].getint("inter_command_delay_ms") / 1000.0
    for index, line in enumerate(lines, start=1):
        if not _clean_output(ctx):
            ctx.console.print(f"[dim]{index:02d}> {line}[/dim]")
        execute_command(ctx, line, from_script=True, inherited_decode_override=decode_override)
        if index < len(lines) and delay > 0:
            time.sleep(delay)


def _copy_to_clipboard(text: str) -> None:
    import tkinter

    root = tkinter.Tk()
    root.withdraw()
    root.clipboard_clear()
    root.clipboard_append(text)
    root.update()
    root.destroy()


def _record_command(ctx: CommandContext, parts: list[str]) -> None:
    if not parts:
        raise ValueError(tr(ctx.language, "record_usage"))
    action = parts[0].lower()
    if action == "start":
        mode = parts[1].lower() if len(parts) > 1 else "all"
        if len(parts) > 2 or mode not in {"all", "rx"}:
            raise ValueError(tr(ctx.language, "record_usage"))
        if ctx.recording.active:
            raise ValueError(tr(ctx.language, "record_already_active", mode=ctx.recording.mode))
        ctx.recording.start(mode)
        ctx.console.print(tr(ctx.language, "record_started", mode=tr(ctx.language, f"record_mode_{mode}")), markup=False)
        return
    if action == "status":
        if ctx.recording.active:
            ctx.console.print(tr(ctx.language, "record_status_active", mode=ctx.recording.mode, count=len(ctx.recording.lines)), markup=False)
        else:
            ctx.console.print(tr(ctx.language, "record_status_inactive"), markup=False)
        return
    if action == "cancel":
        if not ctx.recording.active:
            raise ValueError(tr(ctx.language, "record_not_active"))
        ctx.recording.clear()
        ctx.console.print(tr(ctx.language, "record_cancelled"), markup=False)
        return
    if action != "stop" or len(parts) < 2:
        raise ValueError(tr(ctx.language, "record_usage"))
    if not ctx.recording.active:
        raise ValueError(tr(ctx.language, "record_not_active"))

    destination = parts[1].lower()
    lines = list(ctx.recording.lines)
    text = "\n".join(lines) + ("\n" if lines else "")
    if destination in {"buffer", "clipboard"} and len(parts) == 2:
        try:
            _copy_to_clipboard(text)
        except Exception as exc:
            raise RuntimeError(tr(ctx.language, "clipboard_error", error=exc)) from None
        ctx.recording.clear()
        ctx.console.print(tr(ctx.language, "record_copied", count=len(lines)), markup=False)
        return
    if destination == "file" and len(parts) >= 3:
        path = Path(" ".join(parts[2:])).expanduser()
        if not path.is_absolute():
            path = ctx.config_path.parent / path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        ctx.recording.clear()
        ctx.console.print(tr(ctx.language, "record_saved", path=path, count=len(lines)), markup=False)
        return
    raise ValueError(tr(ctx.language, "record_usage"))


def execute_command(
    ctx: CommandContext,
    line: str,
    *,
    from_script: bool = False,
    inherited_decode_override: bool | None = None,
) -> str | None:
    stripped = line.strip()
    if not stripped or stripped.startswith("#"):
        return None

    parts = shlex.split(stripped)
    command = parts[0].lower()

    if command == "connect":
        ctx.transport.connect()
        if not ctx.one_shot and not _clean_output(ctx):
            ctx.console.print(f"[green]{tr(ctx.language, 'connected', endpoint=ctx.transport.endpoint)}[/green]")
        return None
    if command == "disconnect":
        ctx.transport.disconnect()
        if not ctx.one_shot and not _clean_output(ctx):
            ctx.console.print(f"[yellow]{tr(ctx.language, 'disconnected')}[/yellow]")
        return None
    if command == "ports":
        show_ports(ctx); return None
    if command == "status":
        show_status(ctx); return None
    if command == "send":
        payload, explicit_override = _parse_send_arguments(parts[1:], ctx.language)
        effective_override = explicit_override if explicit_override is not None else inherited_decode_override
        send_frame(ctx, payload, decode_override=effective_override)
        return None
    if command == "pause":
        if len(parts) != 2:
            raise ValueError(tr(ctx.language, "pause_usage"))
        time.sleep(float(parts[1].replace(",", ".")) / 1000.0)
        return None
    if command in {"scripts", "ls", "list"}:
        names = ctx.scripts.list()
        if names:
            for name in names:
                ctx.console.print(name, markup=False)
        else:
            ctx.console.print(tr(ctx.language, "no_scripts"), markup=False)
        return None
    if command == "show" and len(parts) == 2 and parts[1].lower() == "record":
        if not ctx.recording.active:
            raise ValueError(tr(ctx.language, "record_not_active"))
        for item in ctx.recording.lines:
            ctx.console.print(item, markup=False)
        return None
    if command == "show" and len(parts) >= 3 and parts[1].lower() == "script":
        name = " ".join(parts[2:])
        try:
            lines = ctx.scripts.get(name)
        except KeyError:
            raise ValueError(tr(ctx.language, "script_not_found", name=name)) from None
        for item in lines:
            ctx.console.print(item, markup=False)
        return None
    if command == "delete" and len(parts) >= 3 and parts[1].lower() == "script":
        name = " ".join(parts[2:])
        try:
            ctx.scripts.delete(name)
        except KeyError:
            raise ValueError(tr(ctx.language, "script_not_found", name=name)) from None
        ctx.console.print(f"[green]{tr(ctx.language, 'script_deleted', name=name)}[/green]")
        return None
    if command == "run" and len(parts) >= 2 and parts[1].lower() == "script":
        name, explicit_override = _parse_run_arguments(parts[2:], ctx.language)
        effective_override = explicit_override if explicit_override is not None else inherited_decode_override
        run_script(ctx, name, decode_override=effective_override)
        return None
    if command == "record":
        _record_command(ctx, parts[1:]); return None
    if command == "options":
        section = parts[1] if len(parts) > 1 else None
        if section and section not in ctx.config.sections():
            raise ValueError(tr(ctx.language, "unknown_section", section=section))
        show_options(ctx, section); return None
    if command == "set" and len(parts) >= 4 and parts[1].lower() in {"option", "options"}:
        set_option(ctx, parts[2], " ".join(parts[3:])); return None
    if command == "help":
        if len(parts) == 1:
            ctx.console.print(interactive_help(ctx.language), markup=False)
            return None
        topic = HELP_ALIASES.get(parts[1].lower(), parts[1].lower())
        if topic == "record":
            from .runtime_text import TEXT
            ctx.console.print(TEXT["ru" if ctx.language.lower() == "ru" else "en"].get("help_record", "record"), markup=False)
            return None
        if topic == "run":
            from .runtime_text import TEXT
            ctx.console.print(TEXT["ru" if ctx.language.lower() == "ru" else "en"].get("help_run", "run"), markup=False)
            return None
        help_text = command_help(ctx.language, topic)
        if help_text is None:
            ctx.console.print(message(ctx.language, "unknown_help_topic", topic=parts[1]), markup=False)
        else:
            ctx.console.print(help_text, markup=False)
        return None
    if command in {"clear", "cls"}:
        if from_script:
            raise ValueError(tr(ctx.language, "clear_script_forbidden"))
        return "clear-screen"
    if command in {"exit", "quit"}:
        if from_script:
            raise ValueError(tr(ctx.language, "exit_script_forbidden"))
        return "exit"
    if command == "add" and len(parts) >= 3 and parts[1].lower() == "script":
        if from_script:
            raise ValueError(tr(ctx.language, "add_script_interactive"))
        return "add-script:" + " ".join(parts[2:])
    if command == "history":
        if from_script:
            raise ValueError(tr(ctx.language, "history_script_forbidden"))
        return "history-clear" if len(parts) > 1 and parts[1].lower() == "clear" else "history-show"
    raise ValueError(tr(ctx.language, "unknown_command", command=command))
