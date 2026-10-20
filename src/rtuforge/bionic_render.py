"""Stable-width Russian console views."""

from __future__ import annotations

from rich.console import Console, Group
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from .bionic_config import BionicSettings, OPTION_SPECS
from .bionic_events import EventJournal
from .bionic_model import BionicModel


def _tank_lines(model: BionicModel) -> list[str]:
    result = ["БАКИ"]
    for tank in model.tanks.values():
        result.append(
            f"{tank.id:<5} {tank.volume_l:7.1f}/{tank.capacity_l:<7.1f} л {tank.percent:5.1f}% "
            f"перелив {tank.overflow_l:6.1f} л"
        )
    result.extend(("", "ВОДОПРОВОД", f"Расход {model.water_meter.flow_lpm:6.2f} л/мин", f"Всего  {model.water_meter.total_l:7.1f} л"))
    result.extend(("", "ПЕРЕКАЧКА"))
    for pump in model.pumps.values():
        result.append(f"{pump.id:<12} {'RUN' if model.relay(pump.relay) else 'STOP':<4} {pump.actual_flow_lpm:5.1f} л/мин")
    result.extend(("", "ДАТЧИКИ"))
    for sensor in model.sensors.values():
        mode = "AUTO" if sensor.forced is None else "FORCE"
        result.append(f"{sensor.id:<9} {'ON' if sensor.value else 'OFF':<3} {mode}")
    return result


def _process_lines(model: BionicModel) -> list[str]:
    result = ["ВЫСОКОЕ ДАВЛЕНИЕ"]
    for drive in model.drives.values():
        result.append(
            f"{drive.id.upper():<3} {'RUN' if drive.actual_hz > .1 else 'STOP':<4} "
            f"{drive.actual_hz:5.1f}/{drive.setpoint_hz:5.1f} Гц  {drive.motor_hours:6.2f} ч"
        )
    result.extend((
        "", "ДАВЛЕНИЕ",
        f"LOW  {model.low_pressure_bar:6.2f} бар",
        f"HIGH {model.high_pressure_bar:6.2f} бар",
        f"Труба {'РАЗРУШЕНА' if model.pipe_ruptured else 'исправна'}",
        "", "ПОЛИВ / ПРОМЫВКА", model.operation,
    ))
    open_tiers = [tier.id for tier in model.tiers.values() if model.relay(tier.relay)]
    result.append("Ярусы: " + (", ".join(open_tiers) if open_tiers else "нет"))
    bo = model.relay(model.outputs["source_osmosis"])
    bp = model.relay(model.outputs["source_broth"])
    source = "Осмос+Бульон (неопределённо)" if bo and bp else "Осмос" if bo else "Бульон" if bp else "закрыт"
    result.extend((f"Источник: {source}", "", "НЕИСПРАВНОСТИ", f"Протечка {'ON' if model.leak_enabled else 'OFF'}", f"Засор {'ON' if model.blockage_enabled else 'OFF'} {model.blockage_severity:.0f}%"))
    active_lights = []
    for zone_id in model.lights:
        enabled, values = model.light_state(zone_id)
        if enabled:
            active_lights.append(f"{zone_id} " + "/".join(f"{value:.0f}%" for value in values.values()))
    result.extend(("", "АКТИВНОЕ ОСВЕЩЕНИЕ", *(active_lights or ["нет"])))
    return result


def render_main(model: BionicModel, journal: EventJournal, width: int = 120, *, prompt: bool = True) -> Group:
    table = Table.grid(expand=True)
    table.add_column(width=(width - 5) // 2)
    table.add_column(width=(width - 5) // 2)
    left, right = _tank_lines(model), _process_lines(model)
    rows = max(len(left), len(right))
    left += [""] * (rows - len(left))
    right += [""] * (rows - len(right))
    for first, second in zip(left, right):
        table.add_row(first, second)
    recent = journal.events[-3:]
    event_lines = [f"{event.at[11:19]} {event.kind:<9} {event.subject}: {event.message}" for event in recent]
    event_lines = [""] * (3 - len(event_lines)) + event_lines
    parts: list[object] = [Panel(table, title="BIONIC IMMITATOR — виртуальная установка"), Panel("\n".join(event_lines), title="Последние события (3)")]
    if prompt:
        parts.append(Text("bionic-immitator> "))
    return Group(*parts)


def render_settings(settings: BionicSettings, draft: BionicSettings) -> Table:
    table = Table(title="Настройки — F5 применить, Ctrl+S сохранить")
    table.add_column("Категория")
    table.add_column("Параметр")
    table.add_column("Рабочее")
    table.add_column("Черновик")
    for name, (section, _kind) in OPTION_SPECS.items():
        live, pending = getattr(settings, name), getattr(draft, name)
        table.add_row(section, name, str(live), ("* " if live != pending else "") + str(pending))
    return table


def render_view(name: str, model: BionicModel, journal: EventJournal, settings: BionicSettings, draft: BionicSettings, *, prompt: bool = True) -> object:
    if name == "main":
        return render_main(model, journal, prompt=prompt)
    if name == "settings":
        return render_settings(settings, draft)
    if name == "log":
        table = Table(title="Журнал за последние 7 суток")
        for title in ("Дата/время", "Тип", "Объект", "Событие"):
            table.add_column(title)
        for event in journal.events[-100:]:
            table.add_row(event.at, event.kind, event.subject, event.message)
        return table
    title = {
        "rs485": "RS485", "tanks": "Баки", "pumps": "Насосы",
        "pressure": "Давление", "irrigation": "Полив",
        "light": "Освещение", "sensors": "Датчики",
    }.get(name, name)
    return Panel(render_main(model, journal, prompt=False), title=title)


def print_view(console: Console, name: str, model: BionicModel, journal: EventJournal, settings: BionicSettings, draft: BionicSettings) -> None:
    console.print(render_view(name, model, journal, settings, draft))
