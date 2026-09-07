from __future__ import annotations

import configparser
import shlex
import time
from dataclasses import dataclass, field
from pathlib import Path

import serial.tools.list_ports
from rich.console import Console
from rich.live import Live
from rich.table import Table
from rich.text import Text

from .config import OPTION_SPECS, option_spec, parse_value, save_config
from .connection import effective_connection
from .formatting import hex_line, parse_hex_bytes, prefix
from .i18n import command_help, interactive_help, message
from .modbus import decode_response, format_decoded_response
from .runtime_text import tr
from .scanner import ScanArgumentError, ScanResult, parse_scan_arguments, scan_devices
from .script_file import load_script_file, resolve_script_path, save_script_file
from .scripts import ScriptStore
from .script_engine import Instruction, LastResponse, ScriptError, compile_script, run_program
from .transport import Exchange, SerialTransport

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
    "scan_timeout_ms": "Таймаут одного запроса при поиске устройств, мс",
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
    home_path: Path | None = None
    one_shot: bool = False
    recording: RecordingState = field(default_factory=RecordingState)
    last_response: LastResponse | None = None

    @property
    def language(self) -> str:
        return self.config.get("ui", "language", fallback="en")


def _clean_output(ctx: CommandContext) -> bool:
    return ctx.config["runtime"].getboolean("clean_output", fallback=False)


def _record_exchange(
    ctx: CommandContext,
    tx: bytes,
    rx: bytes,
    uppercase: bool,
    *,
    record_empty_rx: bool = True,
) -> None:
    if not ctx.recording.active:
        return
    if ctx.recording.mode == "all":
        if _clean_output(ctx):
            ctx.recording.lines.append(hex_line(tx, uppercase))
            if rx:
                ctx.recording.lines.append(hex_line(rx, uppercase))
        else:
            ctx.recording.lines.append(f"TX {hex_line(tx, uppercase)}")
            if rx or record_empty_rx:
                ctx.recording.lines.append(f"RX {hex_line(rx, uppercase) if rx else ''}".rstrip())
    elif ctx.recording.mode == "rx":
        if rx or record_empty_rx:
            ctx.recording.lines.append(hex_line(rx, uppercase) if rx else "")


def _print_exchange(ctx: CommandContext, tx: bytes, rx: bytes, elapsed_ms: float, *, decode_override: bool | None = None) -> None:
    runtime = ctx.config["runtime"]
    uppercase = runtime.getboolean("uppercase_hex")
    clean = _clean_output(ctx)
    _record_exchange(ctx, tx, rx, uppercase)

    if clean:
        if runtime.getboolean("show_tx"):
            ctx.console.print(hex_line(tx, uppercase), style="cyan", markup=False, highlight=False)
        if runtime.getboolean("show_rx") and rx:
            ctx.console.print(hex_line(rx, uppercase), style="green", markup=False, highlight=False)
    else:
        stamped = runtime.getboolean("timestamps")
        if runtime.getboolean("show_tx"):
            ctx.console.print(
                f"{prefix(stamped)}TX {hex_line(tx, uppercase)}",
                style="cyan",
                markup=False,
                highlight=False,
            )
        if runtime.getboolean("show_rx"):
            payload = hex_line(rx, uppercase) if rx else tr(ctx.language, "no_data")
            ctx.console.print(
                f"{prefix(stamped)}RX {payload} ({elapsed_ms:.1f} ms)",
                style="green",
                markup=False,
                highlight=False,
            )

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
    table.add_column(tr(ctx.language, "port_col")); table.add_column(tr(ctx.language, "description_col")); table.add_column(tr(ctx.language, "hwid_col"))
    for port in ports:
        table.add_row(str(port.device), str(port.description), str(port.hwid))
    ctx.console.print(table)


def show_status(ctx: CommandContext) -> None:
    runtime = ctx.config["runtime"]
    settings = getattr(ctx.transport, "settings", effective_connection(ctx.config))
    is_overridden = getattr(ctx.transport, "is_overridden", lambda name: False)

    def cli_marker(*names: str) -> str:
        return " [CLI]" if any(is_overridden(name) for name in names) else ""

    state = tr(ctx.language, "connected_state" if ctx.transport.connected else "disconnected_state")
    ctx.console.print(f"{tr(ctx.language, 'connection')}: {state}", markup=False)
    if ctx.transport.connected:
        ctx.console.print(f"\n{tr(ctx.language, 'endpoint')}:   {ctx.transport.endpoint}", markup=False)
    ctx.console.print(f"{tr(ctx.language, 'port')}:       {settings.port}{cli_marker('port')}", markup=False)
    ctx.console.print(f"{tr(ctx.language, 'baudrate')}:   {settings.baudrate}{cli_marker('baudrate')}", markup=False)
    ctx.console.print(
        f"{tr(ctx.language, 'format')}:     {settings.bytesize}{settings.parity}{settings.stopbits:g}"
        f"{cli_marker('bytesize', 'parity', 'stopbits')}",
        markup=False,
    )
    ctx.console.print(f"{tr(ctx.language, 'timeout')}:    {settings.timeout_ms} ms{cli_marker('timeout_ms')}", markup=False)
    ctx.console.print(f"{tr(ctx.language, 'crc_mode')}:   {runtime.get('crc_mode')}", markup=False)
    ctx.console.print(f"{tr(ctx.language, 'decode_rx')}:  {runtime.get('decode_rx', 'true')}", markup=False)
    ctx.console.print(f"{tr(ctx.language, 'clean_output')}: {runtime.get('clean_output', 'false')}", markup=False)
    ctx.console.print(f"{tr(ctx.language, 'language')}:   {ctx.language}", markup=False)


def show_paths(ctx: CommandContext) -> None:
    history = Path(ctx.config["history"].get("file", ".rtuforge_history"))
    if not history.is_absolute():
        history = (ctx.config_path.parent / history).resolve()
    home = (ctx.home_path or ctx.config_path.parent).resolve()
    ctx.console.print(f"{tr(ctx.language, 'home')}:    {home}", markup=False)
    ctx.console.print(f"{tr(ctx.language, 'config_path')}:  {ctx.config_path}", markup=False)
    ctx.console.print(f"{tr(ctx.language, 'scripts_path')}: {ctx.scripts.path.resolve()}", markup=False)
    ctx.console.print(f"{tr(ctx.language, 'history_path')}: {history}", markup=False)


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
    exchange = ctx.transport.exchange(parse_hex_bytes(payload))
    ctx.last_response = LastResponse.from_rx(exchange.rx)
    _print_exchange(ctx, exchange.tx, exchange.rx, exchange.elapsed_ms, decode_override=decode_override)


def format_scan_progress(
    language: str, endpoint: str, index: int, total: int, slave: int, found: int
) -> str:
    label = tr(language, "scan_label")
    found_label = tr(language, "scan_found_progress")
    return (
        f"{label} {endpoint} | [{index:03d}/{total:03d}] "
        f"ID {slave:03d} | {found_label} {found:03d}"
    )


def _scan_found_line(ctx: CommandContext, result: ScanResult) -> Text:
    uppercase = ctx.config["runtime"].getboolean("uppercase_hex")
    line = Text()
    line.append(f"ID {result.slave:03d}", style="bold green")
    line.append(f"  {tr(ctx.language, 'scan_found')}  ")
    if result.exception_code is not None:
        line.append(
            f"{tr(ctx.language, 'scan_exception')} {result.exception_code:02X}  ",
            style="yellow",
        )
    line.append(f"RX {hex_line(result.exchange.rx, uppercase)}", style="green")
    line.append(f"  {result.exchange.elapsed_ms:.1f} ms")
    return line


def run_scan(ctx: CommandContext, parts: list[str]) -> bool:
    try:
        options = parse_scan_arguments(
            parts, ctx.config["runtime"].getint("scan_timeout_ms", fallback=100)
        )
    except ScanArgumentError as exc:
        raise ValueError(tr(ctx.language, exc.key, **exc.values)) from None

    ensure_connected(ctx)
    clean = _clean_output(ctx)
    use_live = ctx.console.is_terminal and not clean
    found: list[ScanResult] = []
    uppercase = ctx.config["runtime"].getboolean("uppercase_hex")
    live: Live | None = None

    def on_exchange(exchange: Exchange) -> None:
        _record_exchange(
            ctx, exchange.tx, exchange.rx, uppercase, record_empty_rx=False
        )

    def on_found(result: ScanResult) -> None:
        found.append(result)
        if clean:
            ctx.console.print(str(result.slave), markup=False, highlight=False)
        elif live is not None:
            live.console.print(_scan_found_line(ctx, result), highlight=False)
        else:
            ctx.console.print(_scan_found_line(ctx, result), highlight=False)

    def on_progress(index: int, total: int, slave: int, count: int) -> None:
        if live is not None:
            live.update(
                format_scan_progress(ctx.language, ctx.transport.endpoint, index, total, slave, count),
                refresh=True,
            )

    interrupted = False
    initial = format_scan_progress(
        ctx.language,
        ctx.transport.endpoint,
        0,
        options.end - options.start + 1,
        options.start,
        0,
    )
    try:
        if use_live:
            with Live(initial, console=ctx.console, auto_refresh=False, transient=True) as active_live:
                live = active_live
                scan_devices(
                    ctx.transport,
                    options,
                    on_exchange=on_exchange,
                    on_progress=on_progress,
                    on_found=on_found,
                )
        else:
            scan_devices(ctx.transport, options, on_exchange=on_exchange, on_found=on_found)
    except KeyboardInterrupt:
        interrupted = True
    finally:
        live = None

    if clean:
        return interrupted
    if interrupted:
        ctx.console.print(tr(ctx.language, "scan_stopped"), markup=False)
        ctx.console.print(tr(ctx.language, "scan_found_count", count=len(found)), markup=False)
    elif found:
        ctx.console.print(tr(ctx.language, "scan_found_count", count=len(found)), markup=False)
        ctx.console.print(
            tr(ctx.language, "scan_slave_ids", ids=", ".join(str(item.slave) for item in found)),
            markup=False,
        )
    else:
        ctx.console.print(tr(ctx.language, "scan_none"), markup=False)
    return interrupted


def _parse_decode_flags(parts: list[str], *, command: str) -> tuple[list[str], bool | None]:
    decode_override: bool | None = None; remaining: list[str] = []
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


def _split_command_line(line: str) -> list[str]:
    lexer = shlex.shlex(line, posix=True)
    lexer.whitespace_split = True
    lexer.commenters = ""
    lexer.escape = ""
    return list(lexer)


def _parse_run_arguments(parts: list[str], language: str = "en") -> tuple[str, bool | None]:
    if not parts:
        raise ValueError(tr(language, "run_usage"))
    decode_override: bool | None = None; name_parts: list[str] = []
    for part in parts:
        lowered = part.lower()
        if lowered in {"-d", "--decode"}:
            if decode_override is False: raise ValueError(tr(language, "run_conflict"))
            decode_override = True
        elif lowered in {"-r", "--raw"}:
            if decode_override is True: raise ValueError(tr(language, "run_conflict"))
            decode_override = False
        elif part.startswith("-"):
            raise ValueError(tr(language, "run_unknown_flag", flag=part))
        else:
            name_parts.append(part)
    if not name_parts:
        raise ValueError(tr(language, "run_usage"))
    return " ".join(name_parts), decode_override


def show_options(ctx: CommandContext, section: str | None = None) -> None:
    language = "ru" if ctx.language.lower() == "ru" else "en"; labels = OPTIONS_TABLE_TEXT[language]
    table = Table(title=labels["title"])
    for key in ("section", "name", "value", "description"): table.add_column(labels[key])
    for spec in OPTION_SPECS:
        if section and spec.section.lower() != section.lower(): continue
        description = OPTION_DESCRIPTIONS_RU.get(spec.name, spec.description) if language == "ru" else spec.description
        table.add_row(spec.section, spec.name, ctx.config[spec.section].get(spec.name, ""), description)
    ctx.console.print(table)


def set_option(ctx: CommandContext, name: str, value: str) -> None:
    try: spec = option_spec(name)
    except KeyError: raise ValueError(tr(ctx.language, "unknown_option", name=name)) from None
    try: parsed = parse_value(spec, value)
    except ValueError:
        if spec.kind == "bool": raise ValueError(tr(ctx.language, "expected_boolean")) from None
        if spec.choices: raise ValueError(tr(ctx.language, "allowed_values", values=", ".join(spec.choices))) from None
        if spec.name == "scan_timeout_ms": raise ValueError(tr(ctx.language, "scan_invalid_timeout")) from None
        raise
    if spec.section == "connection" and ctx.transport.connected:
        ctx.transport.disconnect(); ctx.console.print(f"[yellow]{tr(ctx.language, 'connection_option_disconnect')}[/yellow]")
    ctx.config[spec.section][spec.name] = parsed; save_config(ctx.config_path, ctx.config)
    ctx.console.print(f"[green]{tr(ctx.language, 'option_saved', section=spec.section, name=spec.name, value=parsed)}[/green]")


def run_script_lines(
    ctx: CommandContext,
    lines: list[str],
    *,
    source: str,
    decode_override: bool | None = None,
) -> bool:
    if not lines:
        ctx.console.print(f"[yellow]{tr(ctx.language, 'script_empty', name=source)}[/yellow]"); return False
    delay = ctx.config["runtime"].getint("inter_command_delay_ms") / 1000.0
    def execute(item: Instruction) -> bool:
        if not _clean_output(ctx):
            ctx.console.print(f"{item.line:02d}> {item.text}", style="dim", markup=False)
        action = execute_command(ctx, item.text, from_script=True, inherited_decode_override=decode_override)
        return action == "script-interrupted"

    def between_commands() -> None:
        if delay > 0:
            time.sleep(delay)

    try:
        program = compile_script(lines)
        return run_program(program, execute, lambda: ctx.last_response, between_commands)
    except ScriptError as exc:
        raise ValueError(exc.localized(ctx.language, source)) from None
    except KeyboardInterrupt:
        ctx.transport.disconnect()
        raise


def run_script(ctx: CommandContext, name: str, *, decode_override: bool | None = None) -> bool:
    try: lines = ctx.scripts.get(name)
    except KeyError: raise ValueError(tr(ctx.language, "script_not_found", name=name)) from None
    return run_script_lines(ctx, lines, source=name, decode_override=decode_override)


def _file_error(ctx: CommandContext, en: str, ru: str) -> ValueError:
    return ValueError(ru if ctx.language.lower() == "ru" else en)


def _parse_overwrite(parts: list[str], usage: str) -> tuple[list[str], bool]:
    overwrite = False
    plain: list[str] = []
    for part in parts:
        if part.lower() == "--overwrite":
            overwrite = True
        elif part.startswith("-"):
            raise ValueError(f"Unknown flag: {part}")
        else:
            plain.append(part)
    if not plain:
        raise ValueError(usage)
    return plain, overwrite


def _export_command(ctx: CommandContext, parts: list[str]) -> None:
    if not parts or parts[0].lower() not in {"script", "scripts"}:
        raise ValueError("Usage: export script <name> --file <path> [--overwrite] | export scripts --file <path> [--overwrite]")
    kind = parts[0].lower()
    overwrite = False
    args = parts[1:]
    for flag in args:
        if flag.lower() == "--overwrite": overwrite = True
        elif flag.startswith("-") and flag.lower() != "--file": raise ValueError(f"Unknown flag: {flag}")
    try: marker = next(index for index, value in enumerate(args) if value.lower() == "--file")
    except StopIteration: raise ValueError("Missing --file <path>.") from None
    before = [value for value in args[:marker] if value.lower() != "--overwrite"]
    after = [value for value in args[marker + 1:] if value.lower() != "--overwrite"]
    if len(after) != 1: raise ValueError("Missing or invalid --file <path>.")
    if kind == "script":
        name = " ".join(before)
        if not name: raise ValueError("Missing script name.")
        try: scripts = {name: ctx.scripts.get(name)}
        except KeyError: raise ValueError(tr(ctx.language, "script_not_found", name=name)) from None
    else:
        if before: raise ValueError("Usage: export scripts --file <path> [--overwrite]")
        names = ctx.scripts.list()
        if not names:
            ctx.console.print("Скриптов для экспорта нет." if ctx.language.lower() == "ru" else "No scripts to export.", markup=False)
            return
        scripts = {name: ctx.scripts.get(name) for name in names}
    try: path = save_script_file(after[0], scripts, overwrite=overwrite)
    except FileExistsError as exc:
        raise _file_error(ctx, f"File already exists: {exc.args[0]}\nUse --overwrite to replace it.", f"Файл уже существует: {exc.args[0]}\nИспользуйте --overwrite для замены.") from None
    if kind == "script":
        text = f"Скрипт '{name}' экспортирован в {path}." if ctx.language.lower() == "ru" else f"Exported script '{name}' to {path}."
    else:
        text = f"Экспортировано скриптов: {len(scripts)}.\n{path}" if ctx.language.lower() == "ru" else f"Exported {len(scripts)} scripts to {path}."
    ctx.console.print(text, markup=False)


def _import_command(ctx: CommandContext, parts: list[str]) -> None:
    if not parts or parts[0].lower() not in {"script", "scripts"}:
        raise ValueError("Usage: import script|scripts <file> [--overwrite]")
    kind = parts[0].lower()
    plain, overwrite = _parse_overwrite(parts[1:], "Missing script file argument.")
    if len(plain) != 1: raise ValueError("Usage: import script|scripts <file> [--overwrite]")
    scripts = load_script_file(plain[0])
    if not scripts: raise ValueError("Script file contains no scripts.")
    if kind == "script" and len(scripts) != 1:
        raise ValueError("File contains multiple scripts. Use 'import scripts'.")
    try: ctx.scripts.set_many(scripts, overwrite=overwrite)
    except FileExistsError as exc:
        raise _file_error(ctx, f"Scripts already exist: {exc.args[0]}\nUse --overwrite to replace them.", f"Скрипты уже существуют: {exc.args[0]}\nИспользуйте --overwrite для замены.") from None
    if kind == "script":
        name = next(iter(scripts))
        text = f"Скрипт '{name}' импортирован." if ctx.language.lower() == "ru" else f"Imported script '{name}'."
    else:
        text = f"Импортировано скриптов: {len(scripts)}." if ctx.language.lower() == "ru" else f"Imported {len(scripts)} scripts."
    ctx.console.print(text, markup=False)


def _run_file(ctx: CommandContext, parts: list[str], inherited: bool | None) -> bool:
    if not parts: raise ValueError("Usage: run file <file> [--script <name>] [-d|--decode|-r|--raw]")
    path = parts[0]
    decode: bool | None = None
    selector: str | None = None
    index = 1
    while index < len(parts):
        part = parts[index]
        low = part.lower()
        if low in {"-d", "--decode"}:
            if decode is False: raise ValueError("run file: --decode and --raw cannot be used together")
            decode = True; index += 1
        elif low in {"-r", "--raw"}:
            if decode is True: raise ValueError("run file: --decode and --raw cannot be used together")
            decode = False; index += 1
        elif low == "--script":
            index += 1; name_parts: list[str] = []
            while index < len(parts) and not parts[index].startswith("-"):
                name_parts.append(parts[index]); index += 1
            if not name_parts: raise ValueError("Missing value for --script.")
            selector = " ".join(name_parts)
        elif part.startswith("-"): raise ValueError(f"Unknown run file flag: {part}")
        else: raise ValueError("Usage: run file <file> [--script <name>] [-d|--decode|-r|--raw]")
    scripts = load_script_file(path)
    if not scripts: raise ValueError("Script file contains no scripts.")
    if selector is None:
        if len(scripts) > 1:
            raise ValueError("File contains multiple scripts.\nUse --script <name>.\nAvailable scripts: " + ", ".join(scripts))
        selector = next(iter(scripts))
    if selector not in scripts:
        raise ValueError(f"Script '{selector}' not found in file. Available scripts: {', '.join(scripts)}")
    resolved = resolve_script_path(path)
    text = f"Запуск скрипта '{selector}' из {resolved}." if ctx.language.lower() == "ru" else f"Running script '{selector}' from {resolved}."
    if not _clean_output(ctx):
        ctx.console.print(text, markup=False)
    return run_script_lines(ctx, scripts[selector], source=selector, decode_override=decode if decode is not None else inherited)


def _copy_to_clipboard(text: str) -> None:
    import tkinter
    root = tkinter.Tk(); root.withdraw(); root.clipboard_clear(); root.clipboard_append(text); root.update(); root.destroy()


def _finish_recording(ctx: CommandContext, destination_parts: list[str]) -> None:
    if not ctx.recording.active: raise ValueError(tr(ctx.language, "record_not_active"))
    if not destination_parts: raise ValueError(tr(ctx.language, "record_usage"))
    destination = destination_parts[0].lower(); lines = list(ctx.recording.lines); text = "\n".join(lines) + ("\n" if lines else "")
    if destination in {"buffer", "clipboard"} and len(destination_parts) == 1:
        try: _copy_to_clipboard(text)
        except Exception as exc: raise RuntimeError(tr(ctx.language, "clipboard_error", error=exc)) from None
        ctx.recording.clear(); ctx.console.print(tr(ctx.language, "record_copied", count=len(lines)), markup=False); return
    if destination == "file" and len(destination_parts) >= 2:
        path = Path(" ".join(destination_parts[1:])).expanduser()
        if not path.is_absolute(): path = ctx.config_path.parent / path
        path.parent.mkdir(parents=True, exist_ok=True); path.write_text(text, encoding="utf-8")
        ctx.recording.clear(); ctx.console.print(tr(ctx.language, "record_saved", path=path, count=len(lines)), markup=False); return
    raise ValueError(tr(ctx.language, "record_usage"))


def _parse_record_script_arguments(parts: list[str], language: str) -> tuple[str, str, list[str], bool | None, bool]:
    if not parts: raise ValueError(tr(language, "record_script_usage"))
    decode_override: bool | None = None; clean = False; plain: list[str] = []
    for part in parts:
        low = part.lower()
        if low in {"-d", "--decode"}:
            if decode_override is False: raise ValueError(tr(language, "record_script_conflict"))
            decode_override = True
        elif low in {"-r", "--raw"}:
            if decode_override is True: raise ValueError(tr(language, "record_script_conflict"))
            decode_override = False
        elif low in {"-c", "--clean"}: clean = True
        elif part.startswith("-"): raise ValueError(tr(language, "record_script_unknown_flag", flag=part))
        else: plain.append(part)
    marker = next((i for i in range(1, len(plain) - 1) if plain[i].lower() in {"all", "rx"} and plain[i + 1].lower() in {"buffer", "clipboard", "file"}), None)
    if marker is None: raise ValueError(tr(language, "record_script_usage"))
    name = " ".join(plain[:marker]); mode = plain[marker].lower(); destination = plain[marker + 1:]
    if not name or not destination: raise ValueError(tr(language, "record_script_usage"))
    if destination[0].lower() in {"buffer", "clipboard"} and len(destination) != 1: raise ValueError(tr(language, "record_script_usage"))
    if destination[0].lower() == "file" and len(destination) < 2: raise ValueError(tr(language, "record_script_usage"))
    return name, mode, destination, decode_override, clean


def _record_script(ctx: CommandContext, parts: list[str]) -> None:
    if ctx.recording.active: raise ValueError(tr(ctx.language, "record_already_active", mode=ctx.recording.mode))
    name, mode, destination, decode_override, clean = _parse_record_script_arguments(parts, ctx.language)
    previous_clean = ctx.config["runtime"].get("clean_output", "false")
    if clean: ctx.config["runtime"]["clean_output"] = "true"
    ctx.recording.start(mode)
    try:
        run_script(ctx, name, decode_override=decode_override)
        _finish_recording(ctx, destination)
    except (Exception, KeyboardInterrupt):
        ctx.recording.clear()
        raise
    finally:
        ctx.config["runtime"]["clean_output"] = previous_clean


def _record_command(ctx: CommandContext, parts: list[str]) -> None:
    if not parts: raise ValueError(tr(ctx.language, "record_usage"))
    action = parts[0].lower()
    if action == "script": _record_script(ctx, parts[1:]); return
    if action == "start":
        mode = parts[1].lower() if len(parts) > 1 else "all"
        if len(parts) > 2 or mode not in {"all", "rx"}: raise ValueError(tr(ctx.language, "record_usage"))
        if ctx.recording.active: raise ValueError(tr(ctx.language, "record_already_active", mode=ctx.recording.mode))
        ctx.recording.start(mode); ctx.console.print(tr(ctx.language, "record_started", mode=tr(ctx.language, f"record_mode_{mode}")), markup=False); return
    if action == "status":
        key = "record_status_active" if ctx.recording.active else "record_status_inactive"
        values = {"mode": ctx.recording.mode, "count": len(ctx.recording.lines)} if ctx.recording.active else {}
        ctx.console.print(tr(ctx.language, key, **values), markup=False); return
    if action == "cancel":
        if not ctx.recording.active: raise ValueError(tr(ctx.language, "record_not_active"))
        ctx.recording.clear(); ctx.console.print(tr(ctx.language, "record_cancelled"), markup=False); return
    if action == "stop": _finish_recording(ctx, parts[1:]); return
    raise ValueError(tr(ctx.language, "record_usage"))


def execute_command(ctx: CommandContext, line: str, *, from_script: bool = False, inherited_decode_override: bool | None = None) -> str | None:
    stripped = line.strip()
    if not stripped or stripped.startswith("#"): return None
    parts = _split_command_line(stripped); command = parts[0].lower()

    if from_script and command in {"import", "export"}:
        raise ValueError("import/export is not allowed inside scripts")
    if from_script and command == "run" and len(parts) > 1 and parts[1].lower() == "file":
        raise ValueError("run file is not allowed inside scripts")

    if command == "connect":
        ctx.transport.connect()
        if not ctx.one_shot and not _clean_output(ctx): ctx.console.print(f"[green]{tr(ctx.language, 'connected', endpoint=ctx.transport.endpoint)}[/green]")
        return None
    if command == "disconnect":
        ctx.transport.disconnect()
        if not ctx.one_shot and not _clean_output(ctx): ctx.console.print(f"[yellow]{tr(ctx.language, 'disconnected')}[/yellow]")
        return None
    if command == "ports": show_ports(ctx); return None
    if command == "status": show_status(ctx); return None
    if command == "paths": show_paths(ctx); return None
    if command == "scan":
        interrupted = run_scan(ctx, parts[1:])
        return "script-interrupted" if interrupted and from_script else None
    if command == "send":
        payload, explicit = _parse_send_arguments(parts[1:], ctx.language); send_frame(ctx, payload, decode_override=explicit if explicit is not None else inherited_decode_override); return None
    if command == "pause":
        if len(parts) != 2: raise ValueError(tr(ctx.language, "pause_usage"))
        time.sleep(float(parts[1].replace(",", ".")) / 1000.0); return None
    if command in {"scripts", "ls", "list"}:
        names = ctx.scripts.list()
        if names:
            for name in names: ctx.console.print(name, markup=False)
        else: ctx.console.print(tr(ctx.language, "no_scripts"), markup=False)
        return None
    if command == "show" and len(parts) == 2 and parts[1].lower() == "record":
        if not ctx.recording.active: raise ValueError(tr(ctx.language, "record_not_active"))
        for item in ctx.recording.lines: ctx.console.print(item, markup=False)
        return None
    if command == "show" and len(parts) >= 3 and parts[1].lower() == "script":
        name = " ".join(parts[2:])
        try: lines = ctx.scripts.get(name)
        except KeyError: raise ValueError(tr(ctx.language, "script_not_found", name=name)) from None
        for item in lines: ctx.console.print(item, markup=False)
        return None
    if command == "delete" and len(parts) >= 3 and parts[1].lower() == "script":
        name = " ".join(parts[2:])
        try: ctx.scripts.delete(name)
        except KeyError: raise ValueError(tr(ctx.language, "script_not_found", name=name)) from None
        ctx.console.print(f"[green]{tr(ctx.language, 'script_deleted', name=name)}[/green]"); return None
    if command == "export": _export_command(ctx, parts[1:]); return None
    if command == "import": _import_command(ctx, parts[1:]); return None
    if command == "run" and len(parts) >= 2 and parts[1].lower() == "file":
        interrupted = _run_file(ctx, parts[2:], inherited_decode_override)
        return "script-interrupted" if interrupted and from_script else None
    if command == "run" and len(parts) >= 2 and parts[1].lower() == "script":
        name, explicit = _parse_run_arguments(parts[2:], ctx.language)
        interrupted = run_script(
            ctx,
            name,
            decode_override=explicit if explicit is not None else inherited_decode_override,
        )
        return "script-interrupted" if interrupted and from_script else None
    if command == "record": _record_command(ctx, parts[1:]); return None
    if command == "options":
        section = parts[1] if len(parts) > 1 else None
        if section and section not in ctx.config.sections(): raise ValueError(tr(ctx.language, "unknown_section", section=section))
        show_options(ctx, section); return None
    if command == "set" and len(parts) >= 4 and parts[1].lower() in {"option", "options"}: set_option(ctx, parts[2], " ".join(parts[3:])); return None
    if command == "help":
        if len(parts) == 1: ctx.console.print(interactive_help(ctx.language), markup=False); return None
        topic = HELP_ALIASES.get(parts[1].lower(), parts[1].lower())
        if topic in {"record", "run", "export", "import"}:
            from .runtime_text import TEXT
            ctx.console.print(TEXT["ru" if ctx.language.lower() == "ru" else "en"].get(f"help_{topic}", topic), markup=False); return None
        text = command_help(ctx.language, topic)
        if text is None: ctx.console.print(message(ctx.language, "unknown_help_topic", topic=parts[1]), markup=False)
        else: ctx.console.print(text, markup=False)
        return None
    if command in {"clear", "cls"}:
        if from_script: raise ValueError(tr(ctx.language, "clear_script_forbidden"))
        return "clear-screen"
    if command in {"exit", "quit"}:
        if from_script: raise ValueError(tr(ctx.language, "exit_script_forbidden"))
        return "exit"
    if command == "add" and len(parts) >= 3 and parts[1].lower() == "script":
        if from_script: raise ValueError(tr(ctx.language, "add_script_interactive"))
        return "add-script:" + " ".join(parts[2:])
    if command == "history":
        if from_script: raise ValueError(tr(ctx.language, "history_script_forbidden"))
        return "history-clear" if len(parts) > 1 and parts[1].lower() == "clear" else "history-show"
    raise ValueError(tr(ctx.language, "unknown_command", command=command))
