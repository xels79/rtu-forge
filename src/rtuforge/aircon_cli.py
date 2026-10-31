"""Command layer and startup integration for ``rtuforge aircon``."""

from __future__ import annotations

import argparse
import configparser
import copy
import shlex
import threading
from dataclasses import dataclass, field, replace
from datetime import datetime
from pathlib import Path

import serial.tools.list_ports
from rich.console import Console

from .aircon_config import AirconSettings, changed_setting, load_aircon_settings, save_aircon_settings
from .aircon_modbus import AirconModbusClient, DemoTransport
from .aircon_render import render_status_lines
from .aircon_state import AirconState
from .connection import ConnectionOverrides
from .transport import SerialTransport


MODE_VALUES = {"heat": 1, "cool": 2, "auto": 3, "dry": 4, "fan": 5,
               "нагрев": 1, "охлаждение": 2, "авто": 3, "осушение": 4, "вентиляция": 5}


@dataclass
class AirconContext:
    home: Path
    settings_path: Path
    config: configparser.ConfigParser
    settings: AirconSettings
    persisted_settings: AirconSettings
    overrides: ConnectionOverrides
    transport: object
    client: AirconModbusClient
    state: AirconState
    demo: bool = False
    view: str = "status"
    previous_view: str = "status"
    notice: str = "Готово"
    ports: list[str] | None = None
    _last_log_signature: tuple[bool, bool, str | None] | None = None
    operation_lock: threading.RLock = field(default_factory=threading.RLock, repr=False)

    def refresh(self) -> AirconState:
        with self.operation_lock:
            draft = replace(self.state)
            updated = self.client.refresh(draft)
            self.state = updated
            signature = (updated.gateway_online, updated.aircon_online, updated.last_error)
            if signature != self._last_log_signature:
                self._last_log_signature = signature
                self.log_event(
                    f"связь: шлюз={'да' if updated.gateway_online else 'нет'}, "
                    f"кондиционер={'да' if updated.aircon_online else 'нет'}, "
                    f"ошибка={updated.last_error or 'нет'}"
                )
            return updated

    def show(self, view: str) -> None:
        if self.view != view:
            self.previous_view = self.view
        self.view = view

    def log_event(self, message: str) -> None:
        if self.demo:
            return
        path = Path(self.settings.diagnostic_log).expanduser()
        if not path.is_absolute():
            path = self.home / path
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("a", encoding="utf-8") as stream:
                stream.write(f"{datetime.now():%Y-%m-%d %H:%M:%S} {message}\n")
        except OSError as exc:
            self.notice = f"Ошибка диагностического журнала: {exc}"


def _apply_connection(config: configparser.ConfigParser, settings: AirconSettings) -> None:
    if not config.has_section("connection"):
        config.add_section("connection")
    config["connection"].update({
        "port": settings.port,
        "baudrate": str(settings.baudrate),
        "bytesize": str(settings.bytesize),
        "parity": settings.parity,
        "stopbits": f"{settings.stopbits:g}",
        "timeout_ms": str(settings.timeout_ms),
    })


def _effective_settings(
    settings: AirconSettings, overrides: ConnectionOverrides
) -> AirconSettings:
    values = {
        name: getattr(overrides, name)
        for name in ("port", "baudrate", "bytesize", "parity", "stopbits", "timeout_ms")
        if getattr(overrides, name) is not None
    }
    return replace(settings, **values)


def make_context(
    home: Path,
    base_config: configparser.ConfigParser,
    overrides: ConnectionOverrides,
    *,
    settings_path: Path | None = None,
    demo: bool = False,
) -> AirconContext:
    path = settings_path or home / "aircon.ini"
    fallback_port = base_config.get("connection", "port", fallback="")
    persisted = load_aircon_settings(path, fallback_port=fallback_port)
    settings = _effective_settings(persisted, overrides)
    config = copy.deepcopy(base_config)
    _apply_connection(config, settings)
    transport = DemoTransport(settings.slave_id, settings.humidity_slave_id) if demo else SerialTransport(config, overrides)
    client = AirconModbusClient(transport, settings)
    return AirconContext(
        home=home, settings_path=path, config=config, settings=settings,
        persisted_settings=persisted, overrides=overrides, transport=transport,
        client=client, state=AirconState(), demo=demo,
    )


def _require_connected(ctx: AirconContext) -> None:
    if not ctx.transport.connected:
        raise RuntimeError("нет подключения; выполните connect")


def _safe_console_text(text: str, console: Console) -> str:
    """Make redirected Windows snapshots safe for the active legacy code page."""
    encoding = getattr(console.file, "encoding", None) or "utf-8"
    try:
        return text.encode(encoding, errors="replace").decode(encoding)
    except LookupError:
        return text


def _confirmed(ctx: AirconContext) -> AirconState:
    state = ctx.refresh()
    if not state.gateway_online:
        raise RuntimeError(state.last_error or "шлюз не отвечает")
    if not state.aircon_online:
        raise RuntimeError("шлюз отвечает, но кондиционер не на связи")
    return state


def execute_command(ctx: AirconContext, line: str) -> str | None:
    parts = shlex.split(line)
    if not parts:
        return None
    command = parts[0].casefold()
    args = parts[1:]
    aliases = {"вкл": "on", "выкл": "off", "статус": "status", "помощь": "help", "выход": "exit"}
    command = aliases.get(command, command)

    if command in {"exit", "quit"}:
        return "exit"
    if command == "help":
        ctx.show("help")
        ctx.notice = "Справка открыта; Esc — назад"
        return None
    if command == "settings":
        ctx.show("settings")
        ctx.notice = "Настройки открыты; изменение: set <имя> <значение>"
        return None
    if command == "ports":
        ctx.ports = [f"{port.device} — {port.description}" for port in serial.tools.list_ports.comports()]
        ctx.show("ports")
        ctx.notice = f"Найдено портов: {len(ctx.ports)}"
        return None
    if command == "connect":
        if args:
            raise ValueError("использование: connect")
        with ctx.operation_lock:
            ctx.client.connect()
            state = ctx.refresh()
        ctx.notice = "Подключено, состояние прочитано" if state.gateway_online else f"Подключено, но {state.last_error}"
        ctx.log_event("команда connect")
        return None
    if command == "disconnect":
        if args:
            raise ValueError("использование: disconnect")
        with ctx.operation_lock:
            ctx.client.disconnect()
            ctx.state.gateway_online = False
            ctx.state.aircon_online = False
            ctx.state.fresh = False
            ctx.state.clear_measurements()
        ctx.notice = "Отключено"
        ctx.log_event("команда disconnect")
        return None
    if command == "status":
        if args:
            raise ValueError("использование: status")
        _require_connected(ctx)
        state = ctx.refresh()
        ctx.show("status")
        ctx.notice = "Показания обновлены" if state.gateway_online else f"Ошибка: {state.last_error}"
        return None
    if command == "set":
        if len(args) != 2:
            raise ValueError("использование: set <имя> <значение>")
        with ctx.operation_lock:
            candidate = changed_setting(ctx.persisted_settings, args[0], args[1])
            connection_fields = {"port", "baudrate", "bytesize", "parity", "stopbits", "timeout_ms"}
            if args[0].replace("-", "_").casefold() in connection_fields and ctx.transport.connected:
                ctx.client.disconnect()
            save_aircon_settings(ctx.settings_path, candidate)
            ctx.persisted_settings = candidate
            ctx.settings = _effective_settings(candidate, ctx.overrides)
            ctx.client.settings = ctx.settings
            _apply_connection(ctx.config, ctx.settings)
        ctx.notice = f"Сохранено: {args[0]}={args[1]}"
        ctx.log_event(f"изменена настройка {args[0]}")
        return None

    _require_connected(ctx)
    if command in {"on", "off"}:
        if args:
            raise ValueError(f"использование: {command}")
        expected = command == "on"
        with ctx.operation_lock:
            ctx.client.write_coil(1, expected)
            state = _confirmed(ctx)
        if state.power is not expected:
            raise RuntimeError("шлюз принял команду, но питание не подтверждено чтением")
        ctx.notice = "Питание подтверждено: " + ("ВКЛ" if expected else "ВЫКЛ")
        ctx.log_event(f"{command}: питание подтверждено")
        return None
    if command == "temp":
        if len(args) != 1:
            raise ValueError("использование: temp <16..30>")
        try:
            temperature = float(args[0].replace(",", "."))
        except ValueError:
            raise ValueError("температура должна быть целым числом 16..30") from None
        if not temperature.is_integer() or not 16 <= temperature <= 30:
            raise ValueError("температура должна быть целым числом 16..30")
        with ctx.operation_lock:
            ctx.client.write_register(5, int(temperature * 100))
            state = _confirmed(ctx)
        if state.target_temperature_c != temperature:
            raise RuntimeError("шлюз принял команду, но уставка не подтверждена чтением")
        ctx.notice = f"Уставка подтверждена: {temperature:.0f} °C"
        ctx.log_event(f"temp: подтверждено {temperature:.0f} °C")
        return None
    if command == "mode":
        if len(args) != 1 or args[0].casefold() not in MODE_VALUES:
            raise ValueError("использование: mode heat|cool|auto|dry|fan")
        expected = MODE_VALUES[args[0].casefold()]
        with ctx.operation_lock:
            ctx.client.write_register(1, expected)
            state = _confirmed(ctx)
        if state.mode != expected:
            raise RuntimeError("шлюз принял команду, но режим не подтверждён чтением")
        ctx.notice = "Режим подтверждён"
        ctx.log_event(f"mode: подтверждено значение {expected}")
        return None
    if command == "fan":
        if len(args) != 1 or args[0].casefold() not in {"auto", "1", "2", "3", "авто"}:
            raise ValueError("использование: fan auto|1|2|3")
        expected = 0 if args[0].casefold() in {"auto", "авто"} else int(args[0])
        with ctx.operation_lock:
            ctx.client.write_register(7, expected)
            state = _confirmed(ctx)
        if state.fan != expected:
            raise RuntimeError("шлюз принял команду, но скорость не подтверждена чтением")
        ctx.notice = "Скорость вентилятора подтверждена"
        ctx.log_event(f"fan: подтверждено значение {expected}")
        return None
    raise ValueError(f"неизвестная команда: {parts[0]}; используйте help")


class Poller:
    def __init__(self, ctx: AirconContext, invalidate=lambda: None):
        self.ctx = ctx
        self.invalidate = invalidate
        self.stop_event = threading.Event()
        self.thread = threading.Thread(target=self._run, name="aircon-poller", daemon=True)

    def start(self) -> None:
        self.thread.start()

    def stop(self) -> None:
        self.stop_event.set()
        self.thread.join()

    def _run(self) -> None:
        while not self.stop_event.wait(self.ctx.settings.poll_interval_ms / 1000):
            with self.ctx.operation_lock:
                if self.stop_event.is_set():
                    break
                if not self.ctx.transport.connected:
                    continue
                self.ctx.refresh()
            if not self.stop_event.is_set():
                self.invalidate()


def run_aircon(
    argv: list[str], *, home: Path, base_config: configparser.ConfigParser,
    overrides: ConnectionOverrides, console: Console | None = None,
) -> int:
    parser = argparse.ArgumentParser(prog="rtuforge aircon", description="Управление Hisense через ONOKOM HS-6-MB-B")
    parser.add_argument("--aircon-config", type=Path)
    parser.add_argument("--demo", "--mock", action="store_true", dest="demo")
    parser.add_argument("--snapshot", action="store_true", help="показать один экран и выйти")
    args = parser.parse_args(argv)
    settings_path = args.aircon_config.resolve() if args.aircon_config else None
    output = console or Console(highlight=False)
    ctx = make_context(home, base_config, overrides, settings_path=settings_path, demo=args.demo)
    try:
        if args.demo or ctx.settings.auto_connect:
            ctx.client.connect()
            ctx.refresh()
        if args.snapshot:
            for line in render_status_lines(ctx.state, ctx.settings, width=80, height=22):
                output.print(_safe_console_text(line, output), markup=False)
            return 0
        from .aircon_tui import run_tui
        run_tui(ctx)
        return 0
    except (ValueError, RuntimeError, OSError) as exc:
        Console(stderr=True, highlight=False).print(f"Ошибка aircon: {exc}", markup=False)
        return 1
    finally:
        with ctx.operation_lock:
            ctx.client.disconnect()
