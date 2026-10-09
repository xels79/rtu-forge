from __future__ import annotations

import argparse
import configparser
import shlex
import sys
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from threading import RLock
from time import sleep

import serial.tools.list_ports
from prompt_toolkit import PromptSession
from prompt_toolkit.history import FileHistory
from prompt_toolkit.patch_stdout import patch_stdout
from rich.console import Console
from rich.table import Table

from .config import load_config
from .connection import parse_connection_overrides
from .formatting import hex_line, prefix
from .paths import resolve_runtime_paths
from .stand_completion import StandForgeCompleter
from .stand_config import StandSettings, load_stand_settings, save_stand_settings, with_overrides
from .stand_protocol import OUTPUT_CHANNEL_NAMES, OUTPUT_RANGES, RELAY_CHANNEL_COUNT, build_all_relays_off_request, build_output_request, build_tank_request, build_write_multiple_coils, validate_write_response
from .transport import SerialTransport
from .stand_protocol import parse_percent
from .irrigation import State
from .irrigation_config import IrrigationSettings, load_irrigation_settings, set_irrigation_option
from .irrigation_service import IrrigationService
from .stand_hardware import StandHardware
from .stand_help import GENERAL_RU, HELP_RU
from .irrigation_preflight import check_start, parse_start_args


@dataclass
class StandContext:
    config_path: Path
    stand_config_path: Path
    home_path: Path
    config: configparser.ConfigParser
    settings: StandSettings
    transport: SerialTransport
    console: Console
    one_shot: bool = False
    irrigation_settings: IrrigationSettings = field(default_factory=IrrigationSettings)
    bus_lock: RLock = field(default_factory=RLock)
    irrigation: IrrigationService | None = None
    pressure_log: deque[str] = field(default_factory=lambda: deque(maxlen=4096))

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
        "relay_ok": "Relay {channel}: {state}",
        "output_ok": "{name}: {percent:g}% -> {raw} {unit} (channel {channel})",
        "reset_ok": "Stand reset: all relays off, all tanks empty, all analog outputs 0%",
        "saved": "Stand settings saved: {path}",
        "error": "Error: {error}",
    },
    "ru": {
        "banner": "Stand Forge - консоль тестового стенда. Справка: help",
        "connected": "Подключено: {endpoint}",
        "disconnected": "Отключено",
        "no_ports": "Последовательные порты не найдены.",
        "tank_ok": "Бак {tank}: {level} (реле {first}/{second})",
        "relay_ok": "Реле {channel}: {state}",
        "output_ok": "{name}: {percent:g}% -> {raw} {unit} (канал {channel})",
        "reset_ok": "Стенд сброшен: все реле выключены, все баки empty, все аналоговые выходы 0%",
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



def _transaction(ctx: StandContext, request: bytes, *, quiet: bool = False) -> bytes:
    with ctx.bus_lock:
        _ensure_connected(ctx)
        exchange = ctx.transport.exchange(request, crc_mode_override="append")
        if not quiet:
            _print_exchange(ctx, exchange.tx, exchange.rx, exchange.elapsed_ms)
        return exchange.rx


def _hardware(ctx: StandContext, *, quiet: bool = False) -> StandHardware:
    return StandHardware(lambda request: _transaction(ctx, request, quiet=quiet),
                         ctx.settings.relay_address, ctx.irrigation_settings)


def _registers(ctx: StandContext, slave: int, fn: int, addr: int, count: int) -> list[int]:
    return _hardware(ctx).registers(slave, fn, addr, count)


def _idd(ctx: StandContext, args: list[str]) -> None:
    usage = "idd <7|8> <status|setup|frequency ПРОЦЕНТ|monitor|feedback|configure --confirm>"
    if args and args[0].lower() == "all":
        if len(args) != 2 or args[1].lower() not in {"status", "setup", "monitor"}:
            raise ValueError("idd all <status|setup|monitor> — только чтение; запись выполняется для одного IDD")
        errors: list[str] = []
        for drive in (7, 8):
            ctx.console.print(f"IDD {drive}:", markup=False)
            try:
                _idd(ctx, [str(drive), args[1]])
            except (RuntimeError, OSError) as exc:
                errors.append(f"IDD {drive}: {exc}")
        if errors:
            raise RuntimeError("Проверка IDD завершена с ошибками: " + "; ".join(errors))
        return
    if len(args) < 2 or args[0] not in ("7", "8"):
        raise ValueError(usage)
    slave, action = int(args[0]), args[1].lower()
    hw = _hardware(ctx)
    if action == "status" and len(args) == 2:
        for label, addr in (("Pb00", 0x64), ("Pb01", 0x65), ("Pb02", 0x66),
                            ("Pb05", 0x69), ("Pb06", 0x6a),
                            ("Pd15", 0x13b), ("Pd16", 0x13c)):
            val = hw.registers(slave, 3, addr, 1)[0]
            unit = f" ({val / 10:g} Гц)" if label in ("Pb00", "Pb05", "Pb06") else ""
            ctx.console.print(f"{label} = {val}{unit}", markup=False)
    elif action == "setup" and len(args) == 2:
        hw.check_setup(slave)
        maximum, minimum = hw.registers(slave, 3, 0x69, 2)
        if not 0 <= minimum <= maximum <= 4000 or maximum == 0:
            raise RuntimeError("Недопустимые Pb05/Pb06: проверьте настройки IDD")
        ctx.console.print(f"Проверено: частота RS485, пуск FWD; диапазон {minimum/10:g}..{maximum/10:g} Гц. Параметры не менялись.", markup=False)
    elif action == "frequency" and len(args) == 3:
        percent = parse_percent(args[2])
        hw.set_frequency(slave, percent)
        ctx.console.print(f"IDD {slave}: {percent:g}% от Pb05; уставка подтверждена", markup=False)
    elif action == "monitor" and len(args) == 2:
        setpoint, frequency = hw.registers(slave, 3, 1, 2)
        if frequency > 4000:
            raise RuntimeError(f"IDD {slave}: PA02 вне диапазона 0..400 Гц; проверьте карту и масштабирование")
        history = hw.registers(slave, 3, 10, 1)[0]
        ctx.console.print(f"IDD {slave}: связь Modbus подтверждена; PA01={setpoint/10:g} Гц; PA02={frequency/10:g} Гц; PA10 (история ошибок)={history}", markup=False)
        cfg = ctx.irrigation_settings
        if not cfg.vfd_verified or cfg.run_register < 0 or cfg.fault_register < 0:
            ctx.console.print("RUN/STOP=неизвестно; текущая авария=неизвестно. Для управления нужны подтверждённые run_register/fault_register и vfd_verified. PA10 — история; нулевая PA02 сама по себе не подтверждает STOP.", markup=False)
            return
        hz, running, fault = hw.drive_feedback(slave)
        ctx.console.print(f"Выход={hz:g} Гц; {'RUN' if running else 'STOP'}; текущая авария={fault}", markup=False)
    elif action == "feedback" and len(args) == 2:
        feedback = hw.plus_feedback(slave)
        state = {0: "STOP", 1: "RUN вперёд", 2: "RUN назад"}[feedback.state]
        ctx.console.print(f"IDD {slave}, карта mini PLUS: PA02={feedback.output_hz:g} Гц; PA28 (0x001C)={feedback.state} — {state}; PA27 (0x001B), текущая ошибка={feedback.error_code}.", markup=False)
        ctx.console.print("Только чтение обратной связи. Пуск/останов остаётся через реле FWD; параметры и флаги stand.ini не менялись.", markup=False)
    elif action == "configure" and args[2:] == ["--confirm"]:
        hw.configure(slave)
        ctx.console.print("Записаны и проверены Pb01=5, Pb02=1, Pd15=6, Pd16=7; Pb05/Pb06 не менялись.", markup=False)
    else:
        raise ValueError(usage + "; configure требует явного --confirm после проверки оператором")


def _ai(ctx: StandContext, args: list[str]) -> None:
    if args not in ([], ["types"]):
        raise ValueError("ai [types]")
    fn, address = (3, 0x1000) if args else (4, 0)
    values = _registers(ctx, 6, fn, address, 4)
    for i, value in enumerate(values, 1):
        ctx.console.print(f"AI{i}: {'тип' if args else 'сырое значение'} = {value}", markup=False)
    if not args:
        _pressure(ctx, [])


def _pressure(ctx: StandContext, args: list[str]) -> None:
    if args:
        raise ValueError("pressure")
    for reading in _hardware(ctx).pressure():
        value = f"{reading.bar:g} бар" if reading.bar is not None else reading.error
        current = f"{reading.current_ma:g} мА" if reading.current_ma is not None else "единицы не подтверждены"
        text = f"AI{reading.sensor.channel}: raw={reading.raw}, тип={reading.mode}, {current}, {value}"
        ctx.console.print(text, markup=False)
        ctx.pressure_log.append(datetime.now(timezone.utc).isoformat() + " " + text)


def _test_pressure(ctx: StandContext, args: list[str]) -> None:
    if not args or args[0] not in ("low", "high", "stop", "log"):
        raise ValueError("test-pressure <low|high> [число измерений] | test-pressure stop | test-pressure log")
    if args == ["log"]:
        for line in ctx.pressure_log:
            ctx.console.print(line, markup=False)
        return
    if args[0] not in ("low", "high") or len(args) > 2:
        raise ValueError("test-pressure <low|high> [число измерений]")
    count = int(args[1]) if len(args) == 2 else 1
    if not 1 <= count <= 10000:
        raise ValueError("Число измерений: 1..10000")
    channel = 0 if args[0] == "low" else 1
    for i in range(count):
        try:
            reading = _hardware(ctx, quiet=True).pressure()[channel]
            pressure = f"{reading.bar:g} бар" if reading.bar is not None else "давление недостоверно"
            text = (f"AI{channel+1}: модуль отвечает; raw={reading.raw}; тип={reading.mode}; "
                    f"ток={reading.current_ma} мА; {pressure}; ошибка={reading.error or 'нет'}")
        except (RuntimeError, OSError) as exc:
            text = f"AI{channel+1}: потеря связи/неверный ответ: {exc}"
        entry = datetime.now(timezone.utc).isoformat() + " " + text
        ctx.pressure_log.append(entry)
        ctx.console.print(entry, markup=False)
        if i + 1 < count:
            sleep(ctx.irrigation_settings.poll_ms / 1000)


def _start(ctx: StandContext, args: list[str]) -> None:
    rack, tier, liquid, percent = parse_start_args(args)
    ctx.irrigation_settings.require_commissioned()
    if ctx.irrigation is None:
        ctx.irrigation = IrrigationService(_hardware(ctx, quiet=True), ctx.irrigation_settings,
                                          ctx.bus_lock, lambda text: ctx.console.print(text, markup=False))
    ctx.irrigation.start(rack, tier, liquid, percent)
    if ctx.one_shot:
        ctx.console.print("Полив под наблюдением этого процесса; Ctrl+C — безопасный останов.", markup=False)
        while not ctx.irrigation.finished.wait(ctx.irrigation_settings.poll_ms / 1000):
            pass
        if ctx.irrigation.controller.state == State.FAULT:
            raise RuntimeError(ctx.irrigation.controller.fault_reason)


def _check_start(ctx: StandContext, args: list[str]) -> None:
    rack, tier, liquid, percent = parse_start_args(args)
    report = check_start(_hardware(ctx, quiet=True), ctx.irrigation_settings,
                         rack, tier, liquid, percent)
    ctx.console.print(f"Проверка без пуска: IDD {report.drive}; выбор НВД — реле {report.selector}; ярус — реле {report.valve}.", markup=False)
    for check in report.checks:
        ctx.console.print(f"{'OK' if check.passed else 'БЛОК'} — {check.name}: {check.detail}", markup=False)
    ctx.console.print("Реле, частота и stand.ini не изменялись. Проверки повторятся при настоящем start.", markup=False)
    if not report.ready:
        raise RuntimeError("Автопуск не готов: устраните причины БЛОК выше; исправность AI не подтверждает обратную связь IDD и аппаратные защиты")
    ctx.console.print("Проверка пуска пройдена. Для запуска выполните start с теми же аргументами.", markup=False)


def _stop(ctx: StandContext, *, emergency: bool = False) -> None:
    if ctx.irrigation is not None and ctx.irrigation.busy:
        ctx.irrigation.stop()
        if not emergency:
            ctx.console.print("STOP принят; клапан яруса закроется после подтверждения STOP и нулевой частоты.", markup=False)
            return
    with ctx.bus_lock:
        hw = _hardware(ctx)
        hw.emergency_off()
        ctx.console.print("Сняты команды пуска: реле 32, 31, 1; релейная плата подтвердила отключение. Клапаны ярусов не закрывались.", markup=False)
        if not emergency:
            errors = []
            for drive in (7, 8):
                try:
                    hz, running, _ = hw.drive_feedback(drive)
                    if running or hz > ctx.irrigation_settings.stop_hz:
                        errors.append(f"IDD {drive}: частота={hz:g} Гц, {'RUN' if running else 'STOP'}")
                except (RuntimeError, OSError) as exc:
                    errors.append(f"IDD {drive}: {exc}")
            if errors:
                raise RuntimeError("Команды пуска сняты и подтверждены релейной платой, но останов IDD не подтверждён: "
                                   + "; ".join(errors))
            ctx.console.print("IDD 7 и 8: STOP и частота около нуля подтверждены.", markup=False)


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


def _relay(ctx: StandContext, parts: list[str], *, enabled: bool) -> None:
    command = "on" if enabled else "off"
    usage = f"Usage: {command} <1..{RELAY_CHANNEL_COUNT}> [<1..{RELAY_CHANNEL_COUNT}> ...]"
    if not parts:
        raise ValueError(usage)
    try:
        channels = [int(part) for part in parts]
    except ValueError:
        raise ValueError(f"Relay channels must be integers in range 1..{RELAY_CHANNEL_COUNT}. {usage}") from None
    if any(not 1 <= channel <= RELAY_CHANNEL_COUNT for channel in channels):
        raise ValueError(f"Relay channels must be in range 1..{RELAY_CHANNEL_COUNT}. {usage}")
    for channel in dict.fromkeys(channels):
        request = build_write_multiple_coils(ctx.settings.relay_address, channel - 1, [enabled])
        _exchange(ctx, request)
        if not _clean(ctx):
            state = ("включено" if enabled else "выключено") if _lang(ctx) == "ru" else command
            ctx.console.print(_t(ctx, "relay_ok", channel=channel, state=state), markup=False)


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
        ("relays", build_all_relays_off_request(ctx.settings.relay_address))
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
    is_ru = _lang(ctx) == "ru"
    state = ("подключено" if ctx.transport.connected else "отключено") if is_ru else ("connected" if ctx.transport.connected else "disconnected")
    spec = ctx.settings.range_spec
    labels = ("Соединение", "Порт", "Адрес реле", "Адрес выходов", "Выходы", "Баки (имитация)", "Аналоговые выходы") if is_ru else ("Connection", "Endpoint", "Relay ID", "Output ID", "Output", "Tanks", "Analog")
    values = (state, settings.endpoint, ctx.settings.relay_address, ctx.settings.output_address,
              f"{ctx.settings.output_range} ({spec.minimum}..{spec.maximum} {spec.unit})",
              "1=CH1/2, 2=CH3/4, 3=CH5/6, 4=CH7/8",
              "CH1=temperature, CH2=humidity, CH3=pressure-low, CH4=pressure-high")
    for label, value in zip(labels, values):
        ctx.console.print(f"{label}: {value}", markup=False)
    ctl = ctx.irrigation.controller if ctx.irrigation else None
    ctx.console.print(f"Полив: {ctl.state.value if ctl else 'IDLE'}; enabled={ctx.irrigation_settings.enabled}", markup=False)
    if ctl and ctl.fault_reason:
        ctx.console.print(f"Авария: {ctl.fault_reason}", markup=False)


def _show_paths(ctx: StandContext) -> None:
    labels = ("Данные", "Конфигурация RTU", "Конфигурация стенда", "История") if _lang(ctx) == "ru" else ("Home", "RTU config", "Stand config", "History")
    for label, value in zip(labels, (ctx.home_path, ctx.config_path, ctx.stand_config_path, ctx.home_path / '.standforge_history')):
        ctx.console.print(f"{label}: {value}", markup=False)


def _set(ctx: StandContext, parts: list[str]) -> None:
    if len(parts) == 3 and parts[0] == "irrigation":
        # Validation and saving are explicit; load never creates user files.
        ctx.irrigation_settings = set_irrigation_option(ctx.stand_config_path, ctx.irrigation_settings, parts[1], parts[2])
        ctx.irrigation = None
        ctx.console.print(_t(ctx, "saved", path=ctx.stand_config_path), markup=False)
        return
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
    if ctx.transport.connected and updated != ctx.settings:
        ctx.transport.disconnect()
    save_stand_settings(ctx.stand_config_path, updated)
    ctx.settings = updated
    ctx.irrigation = None
    ctx.console.print(_t(ctx, "saved", path=ctx.stand_config_path), markup=False)


def _help(ctx: StandContext, topic: str | None = None) -> None:
    if _lang(ctx) == "ru" or topic in {"stop", "pressure", "test-pressure", "emergency-stop"}:
        if topic and topic not in HELP_RU:
            raise ValueError("Неизвестная тема справки; используйте help")
        ctx.console.print(HELP_RU[topic] if topic else GENERAL_RU, markup=False)
        return
    if topic == "idd":
        text = HELP_RU["idd"]
    elif topic == "ai":
        text = "ai — сырые значения AI1..AI4 модуля RTU 6; ai types — типы входов. Давление требует проверки масштабирования."
    elif topic == "start":
        text = HELP_RU["start"]
    elif topic == "tank":
        text = "tank <1..4> <empty|middle|full>\n  empty=both off, middle=lower on, full=both on"
    elif topic in {"on", "off", "of"}:
        description = (
            f"  Ручное включение/выключение указанных каналов реле 1..{RELAY_CHANNEL_COUNT}; of = off"
            if _lang(ctx) == "ru"
            else f"  Switch the selected relay channels 1..{RELAY_CHANNEL_COUNT} on/off; of = off"
        )
        text = (
            f"on <1..{RELAY_CHANNEL_COUNT}> [<1..{RELAY_CHANNEL_COUNT}> ...]\n"
            f"off <1..{RELAY_CHANNEL_COUNT}> [<1..{RELAY_CHANNEL_COUNT}> ...]\n"
            f"of <1..{RELAY_CHANNEL_COUNT}> [<1..{RELAY_CHANNEL_COUNT}> ...]\n"
        ) + description
    elif topic == "output":
        text = (
            "output <name> <0..100>\n"
            "  names: temperature, humidity, pressure-low, pressure-high\n"
            "  aliases: output pressure low 25 / output pressure high 75"
        )
    elif topic == "set":
        text = "set relay-id <1..247>\nset output-id <1..247>\nset output-range <0-20ma|4-20ma|0-10v>"
    elif topic == "reset":
        text = "reset [all]\n  all relays -> off (Waveshare FC05, 0x00FF); all tanks -> empty; all four analog outputs -> 0%"
    else:
        text = (
            "Stand Forge commands:\n"
            "  idd <7|8> status|setup|frequency <процент>|monitor|feedback|configure --confirm\n"
            "  ai [types] — датчики RTU 6\n"
            "  start <rack> <tier> broth <percent> | stop | emergency-stop\n"
            "  pressure | test-pressure low|high [count] | test-pressure stop\n"
            "  help idd | help ai | help start\n"
            "  tank <1..4> <empty|middle|full>\n"
            f"  on <1..{RELAY_CHANNEL_COUNT}> [<1..{RELAY_CHANNEL_COUNT}> ...]\n"
            f"  off <1..{RELAY_CHANNEL_COUNT}> [<1..{RELAY_CHANNEL_COUNT}> ...] (alias: of)\n"
            "  output <temperature|humidity|pressure-low|pressure-high> <0..100>\n"
            "  set <relay-id|output-id|output-range> <value>\n"
            "  reset [all]\n"
            "  connect | disconnect | ports | status | paths\n"
            "  clear | help [topic] | exit\n\n"
            "Examples:\n"
            "  tank 1 middle\n"
            "  tank 4 full\n"
            "  on 1 16 32\n"
            "  off 32\n"
            "  output temperature 50\n"
            "  output pressure high 75\n"
            "  reset\n"
            "  set output-range 4-20ma"
        )
    ctx.console.print(text, markup=False)


def _execute_command(ctx: StandContext, line: str) -> str | None:
    stripped = line.strip()
    if not stripped or stripped.startswith("#"):
        return None
    parts = shlex.split(stripped, posix=True)
    command, args = parts[0].lower(), parts[1:]
    if command == "idd":
        _idd(ctx, args)
    elif command == "ai":
        _ai(ctx, args)
    elif command == "start":
        _start(ctx, args)
    elif command == "pressure":
        _pressure(ctx, args)
    elif command == "test-pressure":
        _test_pressure(ctx, args)
    elif command == "tank":
        _tank(ctx, args)
    elif command in {"on", "off", "of"}:
        _relay(ctx, args, enabled=command == "on")
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


def execute_command(ctx: StandContext, line: str) -> str | None:
    parts = shlex.split(line.strip(), posix=True)
    if not parts or line.lstrip().startswith("#"):
        return None
    command, args = parts[0].lower(), parts[1:]
    if command in {"stop", "emergency-stop"} or (command == "test-pressure" and args == ["stop"]):
        if command in {"stop", "emergency-stop"} and args:
            raise ValueError(f"{command}: аргументы не требуются")
        _stop(ctx, emergency=command != "stop")
        return None
    if command == "reset" and args == ["fault"]:
        if ctx.irrigation is None:
            raise RuntimeError("Нет аварии контроллера в этом процессе")
        ctx.irrigation.reset_fault()
        return None
    busy = ctx.irrigation is not None and ctx.irrigation.busy
    mutating = command in {"tank", "on", "off", "of", "output", "reset", "set", "connect", "disconnect"}
    mutating |= command == "idd" and len(args) > 1 and args[1].lower() in {"frequency", "configure"}
    if busy and (mutating or command == "test-pressure" and args != ["log"]):
        raise RuntimeError(f"{command}: конфликт с циклом полива/FAULT; выполните stop и дождитесь IDLE или reset fault")
    if command == "start":
        if args and args[0].lower() == "check":
            if busy:
                raise RuntimeError("start check: сначала остановите текущий цикл и дождитесь IDLE / reset fault")
            with ctx.bus_lock:
                _check_start(ctx, args[1:])
            return None
        _start(ctx, args)
        return None
    # This same lock protects worker samples, manual operations and port lifecycle.
    with ctx.bus_lock:
        return _execute_command(ctx, line)


def _shutdown(ctx: StandContext) -> None:
    if ctx.irrigation is not None:
        ctx.irrigation.close()
    with ctx.bus_lock:
        ctx.transport.disconnect()


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
    try:
        with patch_stdout():
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
                    if ctx.irrigation is not None and ctx.irrigation.busy:
                        ctx.irrigation.stop()
                    else:
                        ctx.transport.disconnect()
                    ctx.console.print()
                except Exception as exc:
                    ctx.console.print(_t(ctx, "error", error=exc), markup=False)
    finally:
        _shutdown(ctx)



def build_parser(language: str = "en") -> argparse.ArgumentParser:
    is_ru = language.lower() == "ru"
    parser = argparse.ArgumentParser(
        prog="standforge",
        description=("Консоль управления тестовым стендом на Waveshare Modbus RTU" if is_ru else "Waveshare Modbus RTU test-bench console"),
    )
    descriptions = {
        "clean": ("Вывод кадров без TX/RX и времени", "Plain frame output"),
        "home": ("Каталог пользовательских данных", "User data directory"),
        "config": ("Путь к config.ini RTU Forge", "RTU Forge config.ini path"),
        "stand-config": ("Путь к stand.ini стенда и полива", "Stand and irrigation settings path"),
        "port": ("COM-порт или /dev/tty*, только для этого запуска", "Serial port for this invocation"),
        "baudrate": ("Скорость последовательного порта", "Serial baud rate"),
        "bytesize": ("Число бит данных: 5..8", "Data bits: 5..8"),
        "parity": ("Чётность: N/E/O/M/S", "Parity: N/E/O/M/S"),
        "stopbits": ("Стоповые биты: 1/1.5/2", "Stop bits: 1/1.5/2"),
        "timeout-ms": ("Тайм-аут обмена в миллисекундах", "Exchange timeout in milliseconds"),
        "relay-id": ("Адрес релейной платы: 1..247", "Relay slave ID: 1..247"),
        "output-id": ("Адрес тестовых аналоговых выходов: 1..247", "Analog output slave ID: 1..247"),
        "output-range": ("Диапазон тестовых аналоговых выходов", "Analog output range"),
        "command": ("Команда; help показывает справку без подключения", "Command; use help for command reference"),
    }
    def description(name: str) -> str:
        return descriptions[name][0 if is_ru else 1]
    parser.add_argument("-c", "--clean", action="store_true", help=description("clean"))
    for name in ("home", "config", "stand-config", "port", "baudrate", "bytesize", "parity", "stopbits", "timeout-ms"):
        parser.add_argument("--" + name, help=description(name))
    parser.add_argument("--relay-id", type=int, help=description("relay-id"))
    parser.add_argument("--output-id", type=int, help=description("output-id"))
    parser.add_argument("--output-range", choices=tuple(OUTPUT_RANGES), help=description("output-range"))
    parser.add_argument("command", nargs=argparse.REMAINDER, help=description("command"))
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
        # Independent emergency removal must also work with invalid pressure settings.
        emergency_only = args.command in (["emergency-stop"], ["test-pressure", "stop"])
        irrigation_settings = IrrigationSettings() if emergency_only else load_irrigation_settings(stand_path)
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
        irrigation_settings=irrigation_settings,
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
        _shutdown(ctx)


if __name__ == "__main__":
    raise SystemExit(main())
