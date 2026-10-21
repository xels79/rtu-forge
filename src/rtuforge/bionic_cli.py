"""Russian command interface for the Bionic Mini physical imitator."""

from __future__ import annotations

import argparse
import configparser
import shlex
import sys
import threading
import time
from dataclasses import dataclass
from pathlib import Path

from rich.console import Console
from .bionic_config import BionicSettings, changed, load_settings, save_settings
from .bionic_events import EventJournal
from .bionic_model import BionicModel
from .bionic_modbus import build_default_bus
from .bionic_render import print_view
from .bionic_sensor_bridge import SensorRelayBridge
from .bionic_server import ModbusSlaveServer, SerialSlaveTransport
from .transport import SerialTransport


HELP = """Bionic Immitator — цифровая физическая установка Bionic Mini

status | devices | ports | help
tank list | tank <bo|bp|bso1|bso2> level <л|N%> | capacity <л> | fill-rate <л/мин>
pump list | pump <bo-to-bp|bso1-to-bp|bso2-to-bp> flow <л/мин>
irrigation shelf <1|2> flow-per-tier <л/мин>
pressure target <бар> | range <мин> <макс> | rise-time <с> | fall-time <с>
pipe rupture-threshold <бар> | status | repair
sensor list | sensor <id> threshold <л> | force on|off | auto
fault leak on|off | rate <л/мин>
fault blockage on|off | severity <0..100> | fault list | fault clear all
alarm list | alarm reset all
sim start | pause | resume | speed <1..100> | reset --confirm
view main|settings|log|rs485|tanks|pumps|pressure|irrigation|light|sensors
log last <N> | filter alarms|rs485|tanks|pumps|all | export <файл.csv>
settings list | set <имя> <значение> | apply | save
exit | quit

Имитатор не формирует STOP и не изменяет выходы контроллера при авариях.
Ручные исполнительные выходы запрещены без --test-mode.
"""


@dataclass
class BionicContext:
    home: Path
    config_path: Path
    settings: BionicSettings
    draft: BionicSettings
    model: BionicModel
    journal: EventJournal
    console: Console
    view: str = "status"
    log_filter: str = "all"
    test_mode: bool = False
    screen_mode: bool = False
    help_query: str = ""
    notice: str = ""
    saved: BionicSettings | None = None

    def event(self, kind: str, subject: str, message: str) -> None:
        self.journal.add(kind, subject, message)


def apply_model_settings(settings: BionicSettings, model: BionicModel, *, initial: bool = False) -> None:
    capacities = {
        "bo": settings.bo_capacity_l, "bp": settings.bp_capacity_l,
        "bso1": settings.bso1_capacity_l, "bso2": settings.bso2_capacity_l,
    }
    initials = {
        "bo": settings.bo_initial_l, "bp": settings.bp_initial_l,
        "bso1": settings.bso1_initial_l, "bso2": settings.bso2_initial_l,
    }
    for tank_id, capacity in capacities.items():
        if not initial and model.tanks[tank_id].volume_l > capacity:
            raise ValueError(f"Нельзя применить ёмкость {tank_id}: текущий объём больше нового значения")
        model.tanks[tank_id].capacity_l = capacity
        if initial:
            model.tanks[tank_id].volume_l = initials[tank_id]
    model.fill_flow_lpm = settings.fill_flow_lpm
    model.pumps["bo-to-bp"].flow_lpm = settings.bo_to_bp_flow_lpm
    model.pumps["bso1-to-bp"].flow_lpm = settings.bso1_to_bp_flow_lpm
    model.pumps["bso2-to-bp"].flow_lpm = settings.bso2_to_bp_flow_lpm
    for tier in model.tiers.values():
        tier.flow_lpm = settings.rack1_tier_flow_lpm if tier.rack == 1 else settings.rack2_tier_flow_lpm
        tier.return_fraction = settings.return_fraction
        tier.return_delay_s = settings.return_delay_s
    for sensor in model.sensors.values():
        sensor.hysteresis_l = settings.sensor_hysteresis_l
        sensor.delay_s = settings.sensor_delay_s
        sensor.threshold_l = model.tanks[sensor.tank_id].capacity_l * (0.2 if sensor.kind == "min" else 0.8)
    model.boost_pressure_bar = settings.boost_pressure_bar
    model.boost_rise_s = settings.boost_rise_s
    model.boost_fall_s = settings.boost_fall_s
    model.pressure_rise_s = settings.pressure_rise_s
    model.pressure_fall_s = settings.pressure_fall_s
    model.pressure_max_bar = settings.pressure_max_bar
    model.rupture_threshold_bar = settings.rupture_threshold_bar
    model.rupture_residual_bar = settings.rupture_residual_bar
    model.leak_rate_lpm = settings.leak_rate_lpm
    model.leak_pressure_factor = settings.leak_pressure_factor
    model.blockage_severity = settings.blockage_severity
    model.speed = settings.simulation_speed


def make_context(home: Path, config_path: Path | None = None, *, console: Console | None = None, test_mode: bool = False) -> BionicContext:
    path = config_path or home / "bionic-immitator.ini"
    settings = load_settings(path)
    journal = EventJournal(home / "bionic-events.jsonl", settings.retention_days)
    model = BionicModel()
    apply_model_settings(settings, model, initial=True)
    ctx = BionicContext(home, path, settings, settings, model, journal, console or Console(), test_mode=test_mode)
    ctx.saved = settings
    ctx.model.event = ctx.event
    return ctx


def _number(value: str, label: str, minimum: float = 0.0, maximum: float | None = None) -> float:
    try:
        result = float(value.replace(",", "."))
    except ValueError:
        raise ValueError(f"{label}: ожидалось число") from None
    if result < minimum or maximum is not None and result > maximum:
        suffix = f"..{maximum:g}" if maximum is not None else " или больше"
        raise ValueError(f"{label}: допустимо {minimum:g}{suffix}")
    return result


def _on_off(value: str) -> bool:
    if value.casefold() == "on":
        return True
    if value.casefold() == "off":
        return False
    raise ValueError("Укажите on или off")


def _print_tanks(ctx: BionicContext) -> None:
    for tank in ctx.model.tanks.values():
        ctx.console.print(f"{tank.id}: {tank.volume_l:.2f}/{tank.capacity_l:.2f} л ({tank.percent:.1f}%), перелив {tank.overflow_l:.2f} л")


def _print_alarms(ctx: BionicContext) -> None:
    alarms = [alarm for alarm in ctx.model.alarms.values() if alarm.state.value != "CLEARED"]
    if not alarms:
        ctx.console.print("Зафиксированных аварий нет")
    for alarm in alarms:
        ctx.console.print(f"{alarm.state.value:<7} {alarm.code} {alarm.subject} {alarm.first_at.isoformat()}")


def execute_command(ctx: BionicContext, line: str) -> str | None:
    try:
        parts = shlex.split(line)
    except ValueError as exc:
        raise ValueError(f"Ошибка командной строки: {exc}") from None
    if not parts:
        return None
    command = parts[0].casefold()
    args = parts[1:]
    model = ctx.model
    if command in {"exit", "quit"}:
        return "exit"
    if command == "help":
        if len(args) >= 2 and args[0] == "search":
            ctx.help_query = " ".join(args[1:])
        elif args:
            ctx.help_query = " ".join(args)
        ctx.view = "help"
        if not ctx.screen_mode:
            ctx.console.print(HELP)
        return None
    if command == "status":
        ctx.view = "status"
        if not ctx.screen_mode:
            print_view(ctx.console, "status", model, ctx.journal, ctx.settings, ctx.draft, ctx.saved)
        return None
    if command == "view":
        allowed = {"main", "status", "devices", "ports", "settings", "help", "log", "rs485", "tanks", "pumps", "pressure", "irrigation", "light", "sensors"}
        if len(args) != 1 or args[0] not in allowed:
            raise ValueError("view: укажите status, devices, ports, settings, help, log, rs485, tanks, pumps, pressure, irrigation, light или sensors")
        ctx.view = "status" if args[0] == "main" else args[0]
        if not ctx.screen_mode:
            print_view(ctx.console, ctx.view, model, ctx.journal, ctx.settings, ctx.draft, ctx.saved)
        return None
    if command == "ports":
        ctx.view = "ports"
        if not ctx.screen_mode:
            print_view(ctx.console, "ports", model, ctx.journal, ctx.settings, ctx.draft, ctx.saved)
        return None
    if command == "devices":
        ctx.view = "devices"
        if not ctx.screen_mode:
            print_view(ctx.console, "devices", model, ctx.journal, ctx.settings, ctx.draft, ctx.saved)
        return None
    if command == "tank":
        if args == ["list"]:
            ctx.view = "tanks"
            if not ctx.screen_mode: _print_tanks(ctx)
            return None
        if len(args) != 3 or args[0] not in model.tanks:
            raise ValueError("tank: используйте list или tank <bo|bp|bso1|bso2> <level|capacity|fill-rate> <значение>")
        tank_id, action, raw = args
        if action == "level":
            percent = raw.endswith("%")
            model.set_tank_level(tank_id, _number(raw[:-1] if percent else raw, "Уровень", 0, 100 if percent else model.tanks[tank_id].capacity_l), percent=percent)
        elif action == "capacity":
            capacity = _number(raw, "Ёмкость", 0.001)
            if capacity < model.tanks[tank_id].volume_l:
                raise ValueError("Ёмкость не может быть меньше текущего объёма")
            model.tanks[tank_id].capacity_l = capacity
            ctx.event("ОПЕРАТОР", tank_id, f"ёмкость {capacity:g} л")
        elif action == "fill-rate" and tank_id == "bo":
            model.fill_flow_lpm = _number(raw, "Расход наполнения")
            ctx.event("ОПЕРАТОР", tank_id, f"расход наполнения {model.fill_flow_lpm:g} л/мин")
        else:
            raise ValueError("tank: допустимы level, capacity; fill-rate доступен для bo")
        return None
    if command == "pump":
        if args == ["list"]:
            ctx.view = "pumps"
            if ctx.screen_mode: return None
            for pump in model.pumps.values():
                ctx.console.print(f"{pump.id}: команда {'RUN' if model.relay(pump.relay) else 'STOP'}, {pump.actual_flow_lpm:.2f}/{pump.flow_lpm:.2f} л/мин")
            return None
        if len(args) == 3 and args[0] in model.pumps and args[1] == "flow":
            model.pumps[args[0]].flow_lpm = _number(args[2], "Расход насоса")
            ctx.event("ОПЕРАТОР", args[0], f"расход {model.pumps[args[0]].flow_lpm:g} л/мин")
            return None
        raise ValueError("pump: используйте list или pump <id> flow <л/мин>")
    if command == "irrigation":
        if len(args) == 4 and args[0] == "shelf" and args[2] == "flow-per-tier":
            rack = int(args[1])
            if rack not in {1, 2}:
                raise ValueError("Номер стеллажа должен быть 1 или 2")
            flow = _number(args[3], "Расход яруса")
            for tier in model.tiers.values():
                if tier.rack == rack:
                    tier.flow_lpm = flow
            ctx.event("ОПЕРАТОР", f"rack-{rack}", f"расход яруса {flow:g} л/мин")
            return None
        raise ValueError("irrigation shelf <1|2> flow-per-tier <л/мин>")
    if command == "pressure":
        if len(args) == 2 and args[0] == "target":
            # Target is informational for this passive model; the board still controls frequency.
            ctx.event("ОПЕРАТОР", "pressure", f"рабочая цель {_number(args[1], 'Давление'):g} бар")
        elif len(args) == 3 and args[0] == "range":
            low, high = _number(args[1], "Минимум"), _number(args[2], "Максимум")
            if low >= high:
                raise ValueError("Минимальное давление должно быть меньше максимального")
            model.pressure_max_bar = high
            ctx.event("ОПЕРАТОР", "pressure", f"диапазон {low:g}..{high:g} бар")
        elif len(args) == 2 and args[0] in {"rise-time", "fall-time"}:
            value = _number(args[1], "Время")
            setattr(model, "pressure_rise_s" if args[0] == "rise-time" else "pressure_fall_s", value)
        else:
            raise ValueError("pressure: используйте target, range, rise-time или fall-time")
        return None
    if command == "pipe":
        if args == ["status"]:
            ctx.view = "pressure"
            ctx.notice = f"Трубопровод: {'РАЗРУШЕН' if model.pipe_ruptured else 'исправен'}, порог {model.rupture_threshold_bar:g} бар"
            if not ctx.screen_mode: ctx.console.print(ctx.notice)
        elif args == ["repair"]:
            model.repair_pipe()
        elif len(args) == 2 and args[0] == "rupture-threshold":
            model.rupture_threshold_bar = _number(args[1], "Порог разрушения", 1)
            ctx.event("ОПЕРАТОР", "pipe", f"порог {model.rupture_threshold_bar:g} бар")
        else:
            raise ValueError("pipe: используйте status, repair или rupture-threshold <бар>")
        return None
    if command == "sensor":
        if args == ["list"]:
            ctx.view = "sensors"
            if ctx.screen_mode: return None
            for sensor in model.sensors.values():
                ctx.console.print(f"{sensor.id}: {'ON' if sensor.value else 'OFF'}; {'AUTO' if sensor.forced is None else 'FORCE'}; порог {sensor.threshold_l:g} л")
            return None
        if not args or args[0] not in model.sensors:
            raise ValueError("sensor: неизвестный датчик; используйте sensor list")
        sensor_id = args[0]
        if len(args) == 2 and args[1] == "auto":
            model.force_sensor(sensor_id, None)
        elif len(args) == 3 and args[1] == "force":
            model.force_sensor(sensor_id, _on_off(args[2]))
        elif len(args) == 3 and args[1] == "threshold":
            model.sensors[sensor_id].threshold_l = _number(args[2], "Порог", 0, model.tanks[model.sensors[sensor_id].tank_id].capacity_l)
            ctx.event("ОПЕРАТОР", sensor_id, f"порог {model.sensors[sensor_id].threshold_l:g} л")
        else:
            raise ValueError("sensor <id> threshold <л> | force on|off | auto")
        return None
    if command == "fault":
        if args == ["list"]:
            ctx.view = "pressure"
            ctx.notice = f"leak={'on' if model.leak_enabled else 'off'}; blockage={'on' if model.blockage_enabled else 'off'}; pipe={'ruptured' if model.pipe_ruptured else 'ok'}"
            if not ctx.screen_mode: ctx.console.print(ctx.notice)
        elif args == ["clear", "all"]:
            model.leak_enabled = model.blockage_enabled = False
            ctx.event("ОПЕРАТОР", "faults", "протечка и засор отключены; труба не ремонтировалась")
        elif len(args) == 2 and args[0] == "leak":
            model.leak_enabled = _on_off(args[1])
            ctx.event("ОПЕРАТОР", "leak", args[1])
        elif len(args) == 3 and args[:2] == ["leak", "rate"]:
            model.leak_rate_lpm = _number(args[2], "Интенсивность протечки")
        elif len(args) == 2 and args[0] == "blockage":
            model.blockage_enabled = _on_off(args[1])
            ctx.event("ОПЕРАТОР", "blockage", args[1])
        elif len(args) == 3 and args[:2] == ["blockage", "severity"]:
            model.blockage_severity = _number(args[2], "Степень засора", 0, 100)
        else:
            raise ValueError("fault: используйте list, clear all, leak on|off|rate или blockage on|off|severity")
        return None
    if command == "alarm":
        if args == ["list"]:
            ctx.view = "status"
            if not ctx.screen_mode: _print_alarms(ctx)
        elif args == ["reset", "all"]:
            model.reset_alarms()
        else:
            raise ValueError("alarm list | alarm reset all")
        return None
    if command == "sim":
        if args == ["start"]:
            model.running = True
            model.paused = False
        elif args == ["pause"]:
            model.paused = True
        elif args == ["resume"]:
            model.running = True
            model.paused = False
        elif len(args) == 2 and args[0] == "speed":
            model.speed = _number(args[1], "Скорость", 0.1, 100)
        elif args == ["reset", "--confirm"]:
            ctx.model = BionicModel(ctx.event)
            apply_model_settings(ctx.settings, ctx.model, initial=True)
            ctx.event("ОПЕРАТОР", "simulation", "виртуальное состояние сброшено; физические выходы не изменялись")
            return "reconnect"
        elif args and args[0] == "reset":
            raise ValueError("sim reset требует явного подтверждения: sim reset --confirm")
        else:
            raise ValueError("sim start|pause|resume|speed <1..100>|reset --confirm")
        ctx.event("ОПЕРАТОР", "simulation", " ".join(args))
        return None
    if command == "log":
        if len(args) == 2 and args[0] == "last":
            ctx.view = "log"
            events = ctx.journal.filtered(ctx.log_filter, int(args[1]))
            if not ctx.screen_mode:
                for event in events: ctx.console.print(f"{event.at} {event.kind} {event.subject}: {event.message}")
        elif len(args) == 2 and args[0] == "filter" and args[1] in {"alarms", "rs485", "tanks", "pumps", "all"}:
            ctx.log_filter = args[1]
            ctx.view = "log"
        elif len(args) == 2 and args[0] == "export":
            path = Path(args[1])
            if not path.is_absolute():
                path = ctx.home / path
            ctx.journal.export_csv(path, ctx.journal.filtered(ctx.log_filter))
            ctx.notice = f"Журнал экспортирован: {path}"
            if not ctx.screen_mode: ctx.console.print(ctx.notice)
        else:
            raise ValueError("log last <N> | filter alarms|rs485|tanks|pumps|all | export <файл.csv>")
        return None
    if command == "settings":
        if args == ["list"]:
            ctx.view = "settings"
            if not ctx.screen_mode: print_view(ctx.console, "settings", model, ctx.journal, ctx.settings, ctx.draft, ctx.saved)
        elif len(args) == 3 and args[0] == "set":
            ctx.draft = changed(ctx.draft, args[1], args[2])
            ctx.notice = f"Черновик: {args[1]}={getattr(ctx.draft, args[1])}"
            if not ctx.screen_mode: ctx.console.print(ctx.notice)
        elif args == ["apply"]:
            reconnect = any(getattr(ctx.settings, name) != getattr(ctx.draft, name) for name in (
                "controller_port", "controller_baudrate", "controller_parity", "controller_stopbits",
                "relay_address", "ao1_address", "ao2_address", "ao3_address", "ai_address", "hp1_address", "hp2_address",
                "sensor_relay_port", "sensor_relay_baudrate", "sensor_relay_parity", "sensor_relay_stopbits",
                "sensor_relay_id", "sensor_relay_channels", "sensor_relay_active_low", "sensor_relay_map",
                "sensor_relay_loss_behavior", "hardware_mode",
            ))
            apply_model_settings(ctx.draft, ctx.model)
            ctx.settings = ctx.draft
            ctx.event("ОПЕРАТОР", "settings", "черновик применён к работающей модели")
            return "reconnect" if reconnect else None
        elif args == ["save"]:
            save_settings(ctx.config_path, ctx.draft)
            ctx.saved = ctx.draft
            ctx.event("ОПЕРАТОР", "settings", f"черновик сохранён в {ctx.config_path}; рабочая модель не изменена")
        else:
            raise ValueError("settings list | set <имя> <значение> | apply | save")
        return None
    if command == "relay" and len(args) == 3 and args[0] == "force":
        if not ctx.test_mode:
            raise ValueError("Ручное изменение выходов запрещено; перезапустите с --test-mode")
        channel = int(args[1])
        model.set_relay(channel, _on_off(args[2]))
        ctx.event("ОПЕРАТОР", f"do-{channel}", f"ТЕСТОВОЕ ПРИНУДИТЕЛЬНОЕ {args[2]}")
        return None
    raise ValueError(f"Неизвестная команда: {command}. Используйте help")


class ModelRunner:
    def __init__(self, ctx: BionicContext) -> None:
        self.ctx = ctx
        self.stop_event = threading.Event()
        self.thread = threading.Thread(target=self._run, name="bionic-physics", daemon=True)

    def start(self) -> None:
        self.ctx.model.running = True
        self.thread.start()

    def _run(self) -> None:
        previous = time.monotonic()
        while not self.stop_event.wait(self.ctx.settings.model_interval_ms / 1000.0):
            now = time.monotonic()
            self.ctx.model.tick(now - previous)
            previous = now

    def stop(self) -> None:
        self.stop_event.set()
        self.thread.join(timeout=1)


class BridgeRunner:
    def __init__(self, ctx: BionicContext) -> None:
        self.ctx = ctx
        self.stop_event = threading.Event()
        parser = configparser.ConfigParser()
        parser["connection"] = {
            "port": ctx.settings.sensor_relay_port,
            "baudrate": str(ctx.settings.sensor_relay_baudrate),
            "bytesize": "8",
            "parity": ctx.settings.sensor_relay_parity,
            "stopbits": str(ctx.settings.sensor_relay_stopbits),
            "timeout_ms": "250",
        }
        parser["runtime"] = {
            "crc_mode": "auto", "response_silence_ms": "5",
            "max_response_bytes": "256", "post_write_delay_ms": "0",
        }
        self.transport = SerialTransport(parser)
        mapping = {
            sensor.strip(): int(channel)
            for item in ctx.settings.sensor_relay_map.split(",")
            for sensor, channel in [item.split(":", 1)]
        }
        self.bridge = SensorRelayBridge(
            self.transport, ctx.settings.sensor_relay_id, ctx.settings.sensor_relay_channels,
            active_low=ctx.settings.sensor_relay_active_low, mapping=mapping,
            loss_behavior=ctx.settings.sensor_relay_loss_behavior,
        )
        self.bridge.enabled = True
        self.last_error: str | None = None
        self.thread = threading.Thread(target=self._run, name="bionic-sensor-relay", daemon=True)

    def start(self) -> None:
        self.transport.connect()
        self.thread.start()
        self.ctx.event("АППАРАТУРА", "USB2", "аппаратный режим физического реле включён")

    def _run(self) -> None:
        while not self.stop_event.wait(0.5):
            state = self.bridge.sync(self.ctx.model)
            if not state.online and state.error and state.error != self.last_error:
                self.ctx.event("RS485", "USB2", state.error)
            self.last_error = state.error

    def stop(self) -> None:
        self.stop_event.set()
        if self.thread.is_alive():
            self.thread.join(timeout=1)
        self.transport.disconnect()


def _start_bridge(ctx: BionicContext) -> BridgeRunner | None:
    if not ctx.settings.hardware_mode:
        return None
    runner = BridgeRunner(ctx)
    runner.start()
    return runner


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Цифровой имитатор физической установки Bionic Mini")
    parser.add_argument("--home", type=Path, default=Path.cwd(), help="каталог настроек и журнала")
    parser.add_argument("--config", type=Path, help="файл bionic-immitator.ini")
    parser.add_argument("--test-mode", action="store_true", help="разрешить явно помеченные ручные выходы")
    parser.add_argument("--no-controller", action="store_true", help="не открывать USB №1 в интерактивном режиме")
    parser.add_argument("command", nargs=argparse.REMAINDER)
    return parser


def main() -> int:
    args = _parser().parse_args()
    home = args.home.resolve()
    config = args.config.resolve() if args.config else None
    try:
        ctx = make_context(home, config, test_mode=args.test_mode)
        if args.command:
            result = execute_command(ctx, " ".join(args.command))
            return 0 if result != "exit" else 0
        runner = ModelRunner(ctx)
        server: ModbusSlaveServer | None = None
        bridge_runner: BridgeRunner | None = None
        runner.start()
        def stop_hardware() -> None:
            nonlocal server, bridge_runner
            if server is not None:
                server.stop()
                server = None
            if bridge_runner is not None:
                bridge_runner.stop()
                bridge_runner = None

        def start_hardware() -> None:
            nonlocal server, bridge_runner
            if not args.no_controller:
                bus = build_default_bus(ctx.model, ctx.settings)
                transport = SerialSlaveTransport(
                    ctx.settings.controller_port, ctx.settings.controller_baudrate,
                    ctx.settings.controller_parity, ctx.settings.controller_stopbits,
                )
                server = ModbusSlaveServer(bus, transport, home / f".{ctx.settings.controller_port}.bionic.lock")
                server.start()
            bridge_runner = _start_bridge(ctx)

        def reconnect_hardware() -> None:
            stop_hardware()
            start_hardware()

        start_hardware()
        if sys.stdin.isatty() and sys.stdout.isatty():
            from .bionic_tui import run_tui
            run_tui(ctx, reconnect_hardware)
        else:
            print_view(ctx.console, ctx.view, ctx.model, ctx.journal, ctx.settings, ctx.draft)
            while True:
                try:
                    line = input("bionic-immitator> ")
                    result = execute_command(ctx, line)
                    if result == "exit":
                        break
                    if result == "reconnect":
                        reconnect_hardware()
                except (ValueError, RuntimeError) as exc:
                    ctx.console.print(f"[red]Ошибка:[/red] {exc}")
                except (EOFError, KeyboardInterrupt):
                    break
        stop_hardware()
        runner.stop()
        ctx.journal.compact()
        return 0
    except (ValueError, RuntimeError, OSError) as exc:
        Console(stderr=True).print(f"[red]Ошибка:[/red] {exc}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
