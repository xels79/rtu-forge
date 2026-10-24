"""Width-aware, non-scrolling pages for the Bionic Immitator TUI."""
from __future__ import annotations

from dataclasses import dataclass
from math import floor
from rich.cells import cell_len, set_cell_size
from rich.console import Console
from rich.text import Text
from .bionic_config import BionicSettings, OPTION_SPECS, parse_sensor_relay_map
from .bionic_equipment import (
    EQUIPMENT_IDS, lifetime_for_new_equipment, parse_equipment_profile,
    remaining_dry_run_s,
)
from .bionic_events import EventJournal
from .bionic_idd import IDD_PARAMETERS, IDD_TELEMETRY, decode_idd_value
from .bionic_lights import (
    FACTORY_LIGHTS, LightType, ROLE_LABELS, parse_light_profile,
    validate_light_profile,
)
from .bionic_model import AlarmState, BionicModel, LevelSensor, OUTPUT_NAMES
from .bionic_ponics import (
    PONICS_DEMO_LABEL, PONICS_OPTION_NAMES, PONICS_REGISTER_COUNT, PONICS_REGISTERS,
    PONICS_STATE_LABELS, PONICS_TANK_LABEL,
)
from .bionic_sensor_bridge import SensorRelayState

VIEW_NAMES = ("status", "devices", "ports", "settings", "help", "log", "rs485", "tanks", "pumps", "equipment", "pressure", "irrigation", "light", "light-settings", "sensors", "ponics", "ponics-settings", "ponics-registers", "water", "drives", "drive-hp1", "drive-hp2")
VIEW_TITLES = {"status":"СТАТУС","devices":"УСТРОЙСТВА","ports":"ПОРТЫ","settings":"НАСТРОЙКИ","help":"СПРАВКА","log":"ЖУРНАЛ","rs485":"RS485","tanks":"БАКИ","pumps":"НАСОСЫ","equipment":"СОСТОЯНИЕ ОБОРУДОВАНИЯ","pressure":"ДАВЛЕНИЕ","irrigation":"ПОЛИВ","light":"ОСВЕЩЕНИЕ","light-settings":"НАСТРОЙКИ ОСВЕЩЕНИЯ","sensors":"ДАТЧИКИ УРОВНЯ","water":"СОСТАВ ВОДЫ","drives":"ЧАСТОТНИКИ","drive-hp1":"ЧАСТОТНИК HP1","drive-hp2":"ЧАСТОТНИК HP2"}
TANK_NAMES = {"bo": "Осмос", "bp": "Бульон", "bso1": "Дренаж 1", "bso2": "Дренаж 2"}
PUMP_NAMES = {"bo-to-bp": "Осмос → Бульон", "bso1-to-bp": "Дренаж 1 → Бульон", "bso2-to-bp": "Дренаж 2 → Бульон"}
DRIVE_SOURCE_NAMES = {"panel":"панель", "terminals":"клеммы", "modbus":"Modbus", "unsupported":"не поддерживается"}
PUMP_FAILURE_NAMES = {"none":"исправен", "jammed":"заклинивание", "impeller_damage":"повреждение рабочего колеса", "motor_failure":"отказ двигателя", "dry_run_wear":"износ после сухого хода", "loss_of_prime":"потеря заливки"}
PROTECTION_NAMES = {"READY":"готова", "TIMING":"выдержка", "TRIPPED":"авария", "DISABLED":"отключена"}
EQUIPMENT_STATE_NAMES = {"HEALTHY":"ИСПРАВНО", "DRY_RUNNING":"СУХОЙ ХОД", "OVERHEATED":"ПЕРЕГРЕВ", "DEGRADED":"ДЕГРАДАЦИЯ", "FAILED":"ОТКАЗ"}
HELP_GROUPS = (
    ("УПРАВЛЕНИЕ СИМУЛЯЦИЕЙ", "\n".join((
        "sim start            Запустить расчёт физики",
        "sim pause            Приостановить расчёт физики",
        "sim resume           Продолжить расчёт",
        "sim speed 1          Нормальная скорость",
        "sim speed 5          Пятикратная скорость",
        "sim reset --confirm  Сбросить виртуальное состояние",
        "sim state save <имя> Сохранить физическое состояние отдельно от настроек",
        "sim state load <имя> --confirm  Загрузить состояние, не меняя команды платы",
        "sim state list        Показать контрольные точки",
        "sim pause не закрывает RS485 и не отправляет плате команду остановки.",
    ))),
    ("ОБЩИЕ", "status — состояние; devices — устройства; ports — порты; help — справка; exit/quit — выход"),
    ("НАВИГАЦИЯ", "view status|devices|ports|settings|help|log|rs485|tanks|pumps|equipment|pressure|irrigation|light|sensors|water|ponics|drives"),
    ("СВЕТ", "view light — все сигналы и фактическое свечение; view light settings — отдельная карта каждого яруса; light set <zone> type NONE|SINGLE|SPECTRAL_4; light set <zone> channel <role> <ID> <AO>; light apply; light save; light restore-defaults"),
    ("PONICPILOT", "view ponics; view ponics settings; view ponics registers; ponics dose <a|b|c|ph_plus|ph_minus> <мл>"),
    ("ЧАСТОТНИКИ", "view drives; view drive hp1; view drive hp2; fault pump hp1|hp2 <тип>. RUN учитывает PB.02; RESET частотника не ремонтирует насос; ремонт требует equipment repair <id> --confirm."),
    ("БАКИ", "tank list; tank <bo|bp|bso1|bso2> level <л|N%>; capacity <л>; tank bo fill-rate <л/мин>"),
    ("НАСОСЫ И ПОВРЕЖДЕНИЯ", "view equipment; equipment list; equipment status <id>; equipment repair|replace <id> --confirm; equipment set <id> <параметр> <значение> [--sync-wear]; equipment sync-wear <id>. failure_s — непрерывный сухой ход, wear_rate_per_s — необратимый накопительный износ. Команда платы не изменяется."),
    ("ДАТЧИКИ", "sensor list; sensor <id> threshold <л>; force on|off; auto. Порог MAX — положение датчика, а не физическая ёмкость бака."),
    ("ДАВЛЕНИЕ", "pressure target <бар>; range <мин> <макс>; rise-time <с>; fall-time <с>; pipe status|repair"),
    ("ЗАСОР И ПРОТЕЧКИ", "fault list — внутренние отказы модели; fault leak on|off|rate — протечка; fault blockage on|off|severity — засор после HIGH; fault pump hp1|hp2 <тип> — механический отказ без дополнительного сигнала плате; alarm list; alarm reset all"),
    ("ЖУРНАЛ", "log last <N>; log filter alarms|rs485|tanks|pumps|poinics|all; log export <файл.csv>"),
    ("НАСТРОЙКИ", "settings list; settings set <имя> <значение>; settings apply; settings save"),
    ("КЛАВИШИ", "F1 help · F2 settings · F3 status · F4 devices · F5 ports · F6 log · PgUp/PgDn прокрутка"),
)
SETTING_LABELS = {
    "controller_port":("USB №1: COM-порт контроллера",""), "sensor_relay_port":("USB №2: COM-порт реле датчиков",""),
    "controller_baudrate":("USB №1: скорость линии","бод"), "controller_parity":("USB №1: чётность",""), "controller_stopbits":("USB №1: стоп-биты","бит"),
    "sensor_relay_baudrate":("USB №2: скорость линии","бод"), "sensor_relay_parity":("USB №2: чётность",""), "sensor_relay_stopbits":("USB №2: стоп-биты","бит"),
    "sensor_relay_id":("Физическое реле: Modbus ID",""), "sensor_relay_channels":("Физическое реле: число каналов","кан."),
    "sensor_relay_active_low":("Физическое реле: активный низкий уровень",""), "sensor_relay_map":("Карта датчиков на каналы реле",""),
    "sensor_relay_contact":("Монтажный контакт физического реле","NO/NC"),
    "sensor_relay_loss_behavior":("Реле: поведение при потере связи",""), "hardware_mode":("Аппаратный режим USB №2",""),
    "relay_address":("Релейный модуль: Modbus ID",""), "ao1_address":("Аналоговый выход №1: Modbus ID",""),
    "ao2_address":("Аналоговый выход №2: Modbus ID",""), "ao3_address":("Аналоговый выход №3: Modbus ID",""),
    "ai_address":("Аналоговый вход давления: Modbus ID",""), "hp1_address":("Частотник HP1: Modbus ID",""), "hp2_address":("Частотник HP2: Modbus ID",""),
    "ponics_address":("PonicPilot 32: Modbus ID",""),
    "model_interval_ms":("Период расчёта модели","мс"), "ui_interval_ms":("Период обновления экрана","мс"), "retention_days":("Хранение журнала","дн."),
    "bo_capacity_l":("Осмос: ёмкость бака","л"), "bp_capacity_l":("Бульон: ёмкость бака","л"),
    "bso1_capacity_l":("Дренаж 1: ёмкость бака","л"), "bso2_capacity_l":("Дренаж 2: ёмкость бака","л"),
    "bo_initial_l":("Осмос: начальный объём","л"), "bp_initial_l":("Бульон: начальный объём","л"),
    "bso1_initial_l":("Дренаж 1: начальный объём","л"), "bso2_initial_l":("Дренаж 2: начальный объём","л"),
    "bo_min_threshold_l":("Осмос: порог MIN","л"), "bo_max_threshold_l":("Осмос: порог MAX","л"),
    "bp_min_threshold_l":("Бульон: порог MIN","л"), "bp_max_threshold_l":("Бульон: порог MAX","л"),
    "bso1_min_threshold_l":("Дренаж 1: порог MIN","л"), "bso1_max_threshold_l":("Дренаж 1: порог MAX","л"),
    "bso2_min_threshold_l":("Дренаж 2: порог MIN","л"), "bso2_max_threshold_l":("Дренаж 2: порог MAX","л"),
    "fill_flow_lpm":("Осмос: расход наполнения","л/мин"),
    "water_meter_initial_l":("Счётчик входящей воды: начальное показание после сброса","л"),
    "bo_to_bp_flow_lpm":("Насос Осмос → Бульон: расход","л/мин"),
    "bso1_to_bp_flow_lpm":("Насос Дренаж 1 → Бульон: расход","л/мин"), "bso2_to_bp_flow_lpm":("Насос Дренаж 2 → Бульон: расход","л/мин"),
    "rack1_tier_flow_lpm":("Стеллаж 1: расход яруса","л/мин"), "rack2_tier_flow_lpm":("Стеллаж 2: расход яруса","л/мин"),
    "return_fraction":("Доля возврата в дренаж","доля"), "return_delay_s":("Задержка возврата в дренаж","с"),
    "plant_water_uptake_fraction":("Растения: поглощение воды за проход","доля"),
    "irrigation_evaporation_fraction":("Полив: испарение воды за проход","доля"),
    "sensor_hysteresis_l":("Гистерезис датчиков уровня","л"), "sensor_delay_s":("Задержка датчиков уровня","с"),
    "boost_pressure_bar":("Давление подпора","бар"), "boost_rise_s":("Время набора подпора","с"), "boost_fall_s":("Время падения подпора","с"),
    "pressure_rise_s":("Время набора давления","с"), "pressure_fall_s":("Время падения давления","с"),
    "valve_pressure_response_ms":("Реакция давления на открытие клапана","мс"),
    "valve_pressure_close_response_ms":("Реакция давления на закрытие клапана","мс"),
    "transient_pressure_spike_coefficient":("Коэффициент переходного скачка","×"),
    "transient_pressure_spike_duration_ms":("Длительность переходного скачка","мс"),
    "closed_head_pressure_bar":("Давление HP при закрытых ярусах (45 Гц)","бар"),
    "pressure_max_bar":("Максимальное давление модели","бар"),
    "rupture_threshold_bar":("Порог разрыва трассы","бар"), "leak_rate_lpm":("Интенсивность протечки","л/мин"),
    "rupture_residual_bar":("Остаточное давление после разрыва","бар"), "leak_pressure_factor":("Влияние протечки на давление","доля"),
    "blockage_severity":("Степень засора","%"),
    "light_profile":("Профиль освещения (редактируется в view light settings)",""),
    "equipment_profile":("Профиль повреждений (редактируется в view equipment)",""),
    "ponics_irrigation_on_s":("PonicPilot: время полива","с"), "ponics_irrigation_pause_s":("PonicPilot: пауза полива","с"),
    "ponics_mode":("PonicPilot: режим",""), "ponics_ph_enabled":("PonicPilot: регулятор pH",""),
    "ponics_ph_dosing_pause_s":("PonicPilot: пауза дозирования pH","с"), "ponics_ph_low":("PonicPilot: нижняя точка pH","pH"),
    "ponics_ph_high":("PonicPilot: верхняя точка pH","pH"), "ponics_ec_enabled":("PonicPilot: регулятор EC",""),
    "ponics_ec_protection_enabled":("PonicPilot: защита EC",""), "ponics_ec_dosing_pause_s":("PonicPilot: пауза дозирования EC","с"),
    "ponics_ec_program":("PonicPilot: программа EC",""), "ponics_ec_target_ms_cm":("PonicPilot: целевая EC","мСм/см"),
    "ponics_fertilizer_a_share":("PonicPilot: доля удобрения A",""), "ponics_fertilizer_b_share":("PonicPilot: доля удобрения B",""),
    "ponics_fertilizer_c_share":("PonicPilot: доля удобрения C",""), "ponics_thermostat_enabled":("PonicPilot: термостат",""),
    "ponics_temperature_low_c":("PonicPilot: нижняя температура","°C"), "ponics_temperature_high_c":("PonicPilot: верхняя температура","°C"),
    "tap_ec_ms_cm":("Водопровод: EC","мСм/см"), "tap_ph":("Водопровод: pH","pH"), "tap_temperature_c":("Водопровод: температура","°C"), "tap_buffer_per_l":("Водопровод: буферная ёмкость","усл./л"),
    "osmosis_ec_ms_cm":("Осмос: EC","мСм/см"), "osmosis_ph":("Осмос: pH","pH"), "osmosis_temperature_c":("Осмос: температура","°C"), "osmosis_buffer_per_l":("Осмос: буферная ёмкость","усл./л"),
    "broth_initial_ec_ms_cm":("БП: начальная EC","мСм/см"), "broth_initial_ph":("БП: начальный pH","pH"), "broth_initial_temperature_c":("БП: начальная температура","°C"), "broth_buffer_per_l":("БП: буферная ёмкость","усл./л"),
    "drain_initial_ec_ms_cm":("Дренажи: начальная EC","мСм/см"), "drain_initial_ph":("Дренажи: начальный pH","pH"), "drain_initial_temperature_c":("Дренажи: начальная температура","°C"), "drain_buffer_per_l":("Дренажи: буферная ёмкость","усл./л"),
    "nutrient_absorption_fraction":("Поглощение питательных веществ","доля"), "deposition_fraction":("Осаждение компонентов","доля"),
    "ph_drift_per_pass":("Дрейф pH за проход","pH"), "fertilizer_ec_per_ml_at_100l":("Влияние 1 мл удобрения на EC при 100 л","мСм/см"),
    "ph_reagent_delta_per_ml_at_100l":("Влияние 1 мл корректора pH при 100 л","pH"),
    "hp1_ramp_up_s":("HP1 PB.07: время разгона","с"), "hp1_ramp_down_s":("HP1 PB.08: время торможения","с"),
    "hp1_pb00":("HP1 PB.00: локальная частота","0.1 Гц"),
    "hp1_pb01":("HP1 PB.01: источник частоты",""), "hp1_pb02":("HP1 PB.02: источник RUN",""),
    "hp1_pb05":("HP1 PB.05: максимум частоты","0.1 Гц"), "hp1_pb06":("HP1 PB.06: минимум частоты","0.1 Гц"),
    "hp1_pc12":("HP1 PC.12: номинальная скорость","об/мин"), "hp1_pc15":("HP1 PC.15: номинальная частота","0.1 Гц"),
    "hp1_ph00":("HP1 PH.00: скорость связи",""), "hp1_ph01":("HP1 PH.01: формат связи",""),
    "hp1_nominal_current_a":("HP1 PC.10: номинальный ток двигателя","А"), "hp1_no_load_current_a":("HP1: ток холостого хода","А"),
    "hp1_pump_load_coefficient":("HP1: коэффициент нагрузки насоса","×"), "hp1_jam_current_multiplier":("HP1: ток при заклинивании","×"),
    "hp1_overload_trip_s":("HP1: выдержка перегрузки (модель)","с"), "hp1_overload_protection_enabled":("HP1 Pi.16: защита перегрузки",""),
    "hp1_overload_threshold_multiplier":("HP1: порог перегрузки","×Iном"), "hp1_protection_behavior":("HP1: поведение защиты",""),
    "hp2_ramp_up_s":("HP2 PB.07: время разгона","с"), "hp2_ramp_down_s":("HP2 PB.08: время торможения","с"),
    "hp2_pb00":("HP2 PB.00: локальная частота","0.1 Гц"),
    "hp2_pb01":("HP2 PB.01: источник частоты",""), "hp2_pb02":("HP2 PB.02: источник RUN",""),
    "hp2_pb05":("HP2 PB.05: максимум частоты","0.1 Гц"), "hp2_pb06":("HP2 PB.06: минимум частоты","0.1 Гц"),
    "hp2_pc12":("HP2 PC.12: номинальная скорость","об/мин"), "hp2_pc15":("HP2 PC.15: номинальная частота","0.1 Гц"),
    "hp2_ph00":("HP2 PH.00: скорость связи",""), "hp2_ph01":("HP2 PH.01: формат связи",""),
    "hp2_nominal_current_a":("HP2 PC.10: номинальный ток двигателя","А"), "hp2_no_load_current_a":("HP2: ток холостого хода","А"),
    "hp2_pump_load_coefficient":("HP2: коэффициент нагрузки насоса","×"), "hp2_jam_current_multiplier":("HP2: ток при заклинивании","×"),
    "hp2_overload_trip_s":("HP2: выдержка перегрузки (модель)","с"), "hp2_overload_protection_enabled":("HP2 Pi.16: защита перегрузки",""),
    "hp2_overload_threshold_multiplier":("HP2: порог перегрузки","×Iном"), "hp2_protection_behavior":("HP2: поведение защиты",""),
    "simulation_speed":("Скорость симуляции","×"),
}

SETTINGS_GROUP_TITLES = {
    "serial": "ПОСЛЕДОВАТЕЛЬНЫЕ ПОРТЫ",
    "devices": "MODBUS-УСТРОЙСТВА И ФИЗИЧЕСКОЕ РЕЛЕ",
    "simulation": "СИМУЛЯЦИЯ",
    "tanks": "БАКИ И ПЕРЕКАЧКА",
    "irrigation": "ПОЛИВ И ВОЗВРАТ",
    "sensors": "ДАТЧИКИ УРОВНЯ",
    "pressure": "ДАВЛЕНИЕ И ГИДРАВЛИКА",
    "faults": "НЕИСПРАВНОСТИ ТРУБОПРОВОДА",
    "equipment": "НАСОСЫ — ДЕМОНСТРАЦИОННАЯ ФИЗИЧЕСКАЯ МОДЕЛЬ",
    "ponics": "PONICPILOT",
    "ponics_chemistry": "PONICPILOT — ДЕМОНСТРАЦИОННАЯ ХИМИЯ",
    "drive_hp1": "ЧАСТОТНИК HP1",
    "drive_hp2": "ЧАСТОТНИК HP2",
}

DRIVE_SETTING_REGISTERS = {
    "pb00": 100,
    "pb01": 101,
    "pb02": 102,
    "pb05": 105,
    "pb06": 106,
    "pc12": 212,
    "pc15": 215,
    "ph00": 700,
    "ph01": 701,
}
SETTINGS_GROUP_ORDER = tuple(SETTINGS_GROUP_TITLES)
EQUIPMENT_SETTING_NAMES = {
    "bo-to-bp": "Насос БО → БП: время до физического отказа",
    "bso1-to-bp": "Насос БСО1 → БП: время до физического отказа",
    "bso2-to-bp": "Насос БСО2 → БП: время до физического отказа",
    "hp1": "Насос высокого давления HP1: время до физического отказа",
    "hp2": "Насос высокого давления HP2: время до физического отказа",
}
EQUIPMENT_FIELD_LABELS = {
    "dry_run_warning_s": ("порог предупреждения сухого хода", "с"),
    "overheat_s": ("порог перегрева", "с"),
    "degrade_s": ("порог деградации", "с"),
    "failure_s": ("время до физического отказа", "с"),
    "heating_rate_per_s": ("скорость нагрева", "1/с"),
    "cooling_rate_per_s": ("скорость охлаждения", "1/с"),
    "wear_rate_per_s": ("скорость необратимого износа", "1/с"),
    "wear_flow_reduction": ("снижение расхода от износа", "доля"),
    "initial_state": ("начальное состояние", ""),
    "failure_type": ("тип физического отказа", ""),
}

@dataclass(frozen=True)
class ScreenPage:
    title: str
    lines: list[str]
    row_keys: list[str | None]
    simulation_status: str = ""
    styled_lines: list[tuple[tuple[str, str], ...]] | None = None
    layout_mode: str = "single"
    column_widths: tuple[int, ...] | None = None


StyledLine = tuple[tuple[str, str], ...]
RICH_STYLES = {
    "heading": "bold",
    "sensor_on": "bold red",
    "output_on": "bold red",
    "running": "bold green",
    "ok": "green",
    "inactive": "grey62",
    "warning": "bold yellow",
    "fault": "bold red",
    "demo": "dim",
}


def _plain(line: StyledLine) -> str:
    return "".join(text for _style, text in line)


def _styled(*parts: tuple[str, object] | object) -> StyledLine:
    return tuple(
        (part[0], str(part[1])) if isinstance(part, tuple) else ("", str(part))
        for part in parts
    )


def _fit_fragments(line: StyledLine, width: int, *, pad: bool = False) -> StyledLine:
    """Crop/pad styled text by terminal cells without counting style metadata."""
    width = max(0, width)
    if cell_len(_plain(line)) <= width:
        if pad:
            return (*line, ("", " " * (width - cell_len(_plain(line)))))
        return line
    if width <= 3:
        return (("", "." * width),)
    remaining = width - 3
    result: list[tuple[str, str]] = []
    for style, text in line:
        if remaining <= 0:
            break
        fragment_width = cell_len(text)
        if fragment_width <= remaining:
            result.append((style, text))
            remaining -= fragment_width
        else:
            result.append((style, set_cell_size(text, remaining).rstrip()))
            remaining = 0
    result.append(("", "..."))
    return tuple(result)

def ellipsize(value: object, width: int) -> str:
    text = str(value).replace("\n", " ")
    if width <= 0: return ""
    if cell_len(text) <= width: return text
    return "." * width if width <= 3 else set_cell_size(text, width-3).rstrip() + "..."

def _row(columns: list[tuple[object,int]], width: int) -> str:
    return ellipsize(" | ".join(ellipsize(v,w).ljust(w) for v,w in columns).rstrip(), width)

def _heading(value: str) -> StyledLine:
    return _styled(("heading", value))


def _state(value: bool, *, on_style: str = "output_on") -> tuple[str, str]:
    """Return every binary indication as the same four-cell text field."""
    text = "ВКЛ" if value else "ВЫКЛ"
    return (on_style if value else "inactive", text.ljust(4))


def _status_tanks(model: BionicModel) -> list[StyledLine]:
    names = {"bo": "БО", "bp": "БП", "bso1": "БСО1", "bso2": "БСО2"}
    lines = [_heading("БАКИ")]
    for tank_id in ("bo", "bp", "bso1", "bso2"):
        tank = model.tanks[tank_id]
        lines.append(_styled(f"{names[tank_id]:<4} {tank.volume_l:7.1f} / {tank.capacity_l:7.1f} л  {tank.percent:5.1f}%"))
    return lines


def _status_tank_gauges(model: BionicModel) -> list[StyledLine]:
    """One-line horizontal gauges with MIN/MAX marks at their real positions."""
    names = {"bo": "БО", "bp": "БП", "bso1": "БСО1", "bso2": "БСО2"}
    bar_width = 8
    lines = [_heading("НАПОЛНЕНИЕ · m=МИН M=МАКС")]
    for tank_id in ("bo", "bp", "bso1", "bso2"):
        tank = model.tanks[tank_id]
        sensors = {
            "m": model.sensors[f"{tank_id}-min"],
            "M": model.sensors[f"{tank_id}-max"],
        }
        positions: dict[int, tuple[str, object]] = {}
        for mark, sensor in sensors.items():
            ratio = sensor.threshold_l / tank.capacity_l if tank.capacity_l else 0.0
            position = min(bar_width - 1, max(0, round(ratio * (bar_width - 1))))
            if position in positions:
                position = min(bar_width - 1, position + (1 if mark == "M" else -1))
            positions[position] = (mark, sensor)
        filled = round(max(0.0, min(100.0, tank.percent)) / 100.0 * bar_width)
        parts: list[tuple[str, object] | object] = [f"{names[tank_id]:<4} ["]
        for position in range(bar_width):
            if position in positions:
                mark, sensor = positions[position]
                parts.append(("sensor_on" if sensor.value else "inactive", mark))
            else:
                parts.append("█" if position < filled else "░")
        parts += [f"] {tank.percent:>5.1f}% "]
        for index, mark in enumerate(("m", "M")):
            if index:
                parts.append(" ")
            sensor = sensors[mark]
            parts += [
                f"{mark}:",
                _state(sensor.value, on_style="sensor_on"),
            ]
        lines.append(_styled(*parts))
    lines += [
        tuple(),
        _heading("ИТОГО ВОДЫ"),
        _styled("СЧЁТЧИК ВХОДА ", ("ok", f"{model.water_meter.total_l:.3f} л")),
        _styled(f"БО {model.tanks['bo'].volume_l:.3f} л"),
        _styled(f"ТРАКТ БП+БСО1+БСО2 {model.irrigation_loop_volume_l:.3f} л"),
        _styled(f"ВСЕГО В СИСТЕМЕ {model.total_system_water_l:.3f} л"),
        _styled(f"РАСХОД РАСЧЁТНЫЙ {model.calculated_flow_lpm:.2f} л/мин"),
        _styled(
            f"ПРОТЕЧКИ {model.current_leak_flow_lpm:.2f} л/мин · ",
            ("fault" if model.current_leak_flow_lpm > 0 else "inactive",
             f"Σ {model.total_leak_l:.3f} л"),
        ),
        _styled(f"РАСТЕНИЯ ПОГЛОТИЛИ {model.total_plant_water_uptake_l:.3f} л"),
        _styled(f"ИСПАРИЛОСЬ {model.total_irrigation_evaporation_l:.3f} л"),
    ]
    return lines


def _status_pair(
    prefix: str, left: StyledLine, right: StyledLine, width: int,
) -> StyledLine:
    """Place two status cells at stable column positions after a fixed prefix."""
    available = max(2, width - cell_len(prefix) - 3)
    left_width = available // 2
    right_width = available - left_width
    return _styled(
        prefix,
        *_fit_fragments(left, left_width, pad=True),
        " | ",
        *_fit_fragments(right, right_width),
    )


def _sensor_status_cell(
    label: str, sensor: LevelSensor, channel: int, *, marker_width: int,
    threshold_width: int,
) -> StyledLine:
    state = _state(sensor.value, on_style="sensor_on")
    marker = f"(CH{channel})"
    threshold = f"{sensor.threshold_l:g} л"
    return _styled(
        f"{label} ", state, " ", marker.ljust(marker_width),
        threshold.rjust(threshold_width),
    )


def _status_sensors(
    model: BionicModel, settings: BionicSettings,
    relay_state: SensorRelayState | None, width: int,
) -> tuple[list[StyledLine], list[str]]:
    names = {"bo": "БО", "bp": "БП", "bso1": "БСО1", "bso2": "БСО2"}
    mapping = parse_sensor_relay_map(settings.sensor_relay_map)
    # Reserve the widest physical marker used here.  This keeps thresholds at
    # one position for CH1, CH10 and the longer NO/NC notation.
    marker_width = max(
        cell_len("(NO/NC)"),
        *(cell_len(f"(CH{channel})") for channel in mapping.values()),
    )
    threshold_width = max(
        cell_len(f"{sensor.threshold_l:g} л") for sensor in model.sensors.values()
    )
    desired = sum(
        int(model.sensors[sensor_id].value ^ settings.sensor_relay_active_low) << (channel - 1)
        for sensor_id, channel in mapping.items()
    )
    lines = [_heading("ДАТЧИКИ УРОВНЯ")]
    if settings.hardware_mode:
        lines.append(_styled(("demo", "MIN/MAX — расчёт; CH — выход реле, не контакт NO/NC")))
    warnings: list[str] = []
    if settings.hardware_mode and (relay_state is None or not relay_state.online or relay_state.confirmed is None):
        warnings.append("USB №2: НЕТ СВЯЗИ, состояние выходов не подтверждено")
    for tank_id in ("bo", "bp", "bso1", "bso2"):
        lines.append(_status_pair(
            f"{names[tank_id]:<4} ",
            _sensor_status_cell(
                "MIN", model.sensors[f"{tank_id}-min"], mapping[f"{tank_id}-min"],
                marker_width=marker_width, threshold_width=threshold_width,
            ),
            _sensor_status_cell(
                "MAX", model.sensors[f"{tank_id}-max"], mapping[f"{tank_id}-max"],
                marker_width=marker_width, threshold_width=threshold_width,
            ),
            width,
        ))
        if settings.hardware_mode:
            relay_values: list[StyledLine] = []
            relay_problem = False
            for kind, label in (("min", "MIN"), ("max", "MAX")):
                sensor_id = f"{tank_id}-{kind}"
                channel = mapping[sensor_id]
                expected = bool(desired & (1 << (channel - 1)))
                relay_parts: list[tuple[str, object] | object] = [f"{label} CH{channel} "]
                if relay_state is None or not relay_state.online or relay_state.confirmed is None:
                    relay_parts.append(("warning", "НЕТ СВЯЗИ"))
                    relay_problem = True
                else:
                    confirmed = bool(relay_state.confirmed & (1 << (channel - 1)))
                    relay_parts.append(_state(confirmed))
                    if confirmed != expected:
                        relay_problem = True
                        relay_parts += [("warning", " ≠ ТРЕБ.")]
                        warnings.append(f"{sensor_id}/CH{channel}: треб. {'ВКЛ' if expected else 'ВЫКЛ'}, подтв. {'ВКЛ' if confirmed else 'ВЫКЛ'}")
                relay_value = _styled(*relay_parts)
                relay_values.append(relay_value)
            if relay_problem:
                lines.append(_status_pair(
                    "     ", relay_values[0], relay_values[1], width,
                ))
    if not settings.hardware_mode:
        lines.append(_styled(("inactive", "Физическое подтверждение USB №2 отключено")))
    return lines, warnings


def _pump_status_lines(
    name: str, width: int, *, commanded: bool,
    motor_style: str, motor_text: str, motor_is_modelled: bool,
    flow_style: str, flow_text: str, dry_running: bool,
    failures: tuple[str, ...],
) -> list[StyledLine]:
    """Render one pump without allowing its safety-critical states to clip."""
    name_width = 7
    indent = " " * (name_width + 1)
    command = _state(commanded)
    motor = (motor_style, motor_text)
    model_note = ("demo", " (МОДЕЛЬ)") if motor_is_modelled else ("", "")
    flow = (flow_style, flow_text)
    dry = ("fault", "ДА") if dry_running else ("inactive", "НЕТ")
    failure_parts = tuple(("fault", failure) for failure in failures) or (("inactive", "ОТКАЗ НЕТ"),)

    first = _styled(
        f"{name:<{name_width}} CMD ", command,
        " | МОТОР ", motor, model_note,
    )
    failure_cells: list[StyledLine] = []
    for style, failure in failure_parts:
        if failure.startswith("ОТКАЗ "):
            label, value = "ОТКАЗ", failure.removeprefix("ОТКАЗ ")
        elif failure.startswith("АВАРИЯ "):
            label, value = "АВАРИЯ", failure.removeprefix("АВАРИЯ ")
        else:
            label, value = "ОТКАЗ", failure
        failure_cells.append(_styled(f"{label} ", (style, value)))

    available = max(1, width - cell_len(indent) - 6)
    if available >= 50:
        column_widths = (24, 16, available - 40)
    elif available >= 43:
        column_widths = (21, 15, available - 36)
    else:
        column_widths = (14, 13, max(1, available - 27))
    cells = [
        _styled("ПОДАЧА ", flow),
        _styled("СУХОЙ ХОД ", dry),
        failure_cells[0],
    ]
    row_parts: list[tuple[str, object] | object] = [indent]
    overflow: list[StyledLine] = []
    for index, (cell, column_width) in enumerate(zip(cells, column_widths)):
        if index:
            row_parts.append(" | ")
        if cell_len(_plain(cell)) <= column_width:
            row_parts.extend(_fit_fragments(cell, column_width, pad=True))
        else:
            label = (
                ("ПОДАЧА", "СУХОЙ ХОД")[index]
                if index < 2 else cell[0][1].strip()
            )
            marker = _styled(label + " ", (cell[-1][0], "↴"))
            row_parts.extend(_fit_fragments(marker, column_width, pad=True))
            overflow.append(_styled(indent, *cell))
    lines = [first, _styled(*row_parts), *overflow]
    lines.extend(_styled(indent, *cell) for cell in failure_cells[1:])
    return lines


def _status_pumps(model: BionicModel, width: int) -> list[StyledLine]:
    lines = [_heading("НАСОСЫ")]
    short_names = {"bo-to-bp": "БО→БП", "bso1-to-bp": "БСО1→БП", "bso2-to-bp": "БСО2→БП"}
    blocking_failures = {"jammed", "motor_failure"}
    failure_names = {
        "jammed": "ОТКАЗ ЗАКЛИНИВАНИЕ",
        "impeller_damage": "ОТКАЗ ПОВРЕЖДЕНО КОЛЕСО",
        "motor_failure": "ОТКАЗ ДВИГАТЕЛЯ",
        "loss_of_prime": "ОТКАЗ ПОТЕРЯ ЗАЛИВКИ",
        "dry_run_wear": "ОТКАЗ ИЗНОС ПОСЛЕ СУХОГО ХОДА",
    }
    for pump_id in ("bo-to-bp", "bso1-to-bp", "bso2-to-bp"):
        pump = model.pumps[pump_id]
        commanded = model.equipment_commanded(pump_id)
        motor_running = commanded and pump.health.failure not in blocking_failures
        has_flow = pump.actual_flow_lpm > 1e-6
        flow_style = "ok" if has_flow else ("warning" if motor_running else "inactive")
        failures = (
            (failure_names.get(pump.health.failure, f"ОТКАЗ {pump.health.failure.upper()}"),)
            if pump.health.failed else tuple()
        )
        lines.extend(_pump_status_lines(
            short_names[pump_id], width, commanded=commanded,
            motor_style="running" if motor_running else "inactive",
            motor_text="РАБОТАЕТ" if motor_running else "СТОП",
            motor_is_modelled=True,
            flow_style=flow_style,
            flow_text=(f"ЕСТЬ {pump.actual_flow_lpm:.2f} л/мин" if has_flow else "НЕТ"),
            dry_running=pump.health.dry_running,
            failures=failures,
        ))
    for drive_id in ("hp1", "hp2"):
        drive = model.drives[drive_id]
        commanded = model.equipment_commanded(drive_id)
        motor_running = (
            drive.actual_hz > 0.1
            and drive.health.failure not in blocking_failures
        )
        flow_known_absent = (
            not motor_running
            or drive.health.dry_running
            or drive.health.failure in blocking_failures
        )
        flow_text = "НЕТ" if flow_known_absent else "НЕ ОПРЕДЕЛЕНА"
        flow_style = "inactive" if not motor_running else "warning"
        failures_list: list[str] = []
        if drive.health.failed:
            failures_list.append(failure_names.get(
                drive.health.failure, f"ОТКАЗ {drive.health.failure.upper()}",
            ))
        if drive.fault:
            failures_list.append(f"АВАРИЯ IDD {drive.fault}")
        lines.extend(_pump_status_lines(
            drive_id.upper(), width, commanded=commanded,
            motor_style="running" if motor_running else "inactive",
            motor_text=(f"РАБОТАЕТ {drive.actual_hz:.1f} Гц" if motor_running else "СТОП"),
            motor_is_modelled=False,
            flow_style=flow_style, flow_text=flow_text,
            dry_running=drive.health.dry_running,
            failures=tuple(failures_list),
        ))
    return lines


def _output_parts(
    model: BionicModel, items: tuple[tuple[str, int], ...], width: int,
    *, label_width: int,
) -> StyledLine:
    cell_width = max(1, (width - 3 * (len(items) - 1)) // len(items))
    cells: list[StyledLine] = []
    for index, (label, channel) in enumerate(items):
        state_style, state_text = _state(model.relay(channel))
        cell = _styled(f"{label:<{label_width}} DO{channel:>2} ", (state_style, state_text))
        cells.append(_fit_fragments(cell, cell_width, pad=index < len(items) - 1))
    parts: list[tuple[str, object] | object] = []
    for index, cell in enumerate(cells):
        if index:
            parts.append(" | ")
        parts.extend(cell)
    return _styled(*parts)


def _status_outputs(model: BionicModel, width: int) -> list[StyledLine]:
    return [
        _heading("КЛАПАНЫ И ВЫХОДЫ"),
        _output_parts(model, (("Наполнение", 22), ("Осмос", 21)), width, label_width=10),
        _output_parts(model, (("Бульон", 23), ("Подпор", 1)), width, label_width=10),
        _output_parts(model, (("БО→БП", 2), ("БСО1", 17)), width, label_width=10),
        _output_parts(model, (("БСО2", 18),), width, label_width=10),
        _output_parts(model, tuple((f"Я{index}", 8 + index) for index in range(1, 4)), width, label_width=2),
        _output_parts(model, tuple((f"Я{index}", 8 + index) for index in range(4, 7)), width, label_width=2),
        _output_parts(model, (("Выбор HP1", 19), ("Выбор HP2", 20)), width, label_width=10),
        _output_parts(model, (("RUN HP1", 32), ("RUN HP2", 31)), width, label_width=10),
    ]


def _status_hydraulics(model: BionicModel) -> list[StyledLine]:
    return [
        _heading("ГИДРАВЛИКА"),
        _styled(f"LOW {model.low_pressure_bar:.2f} бар | HIGH {model.high_pressure_bar:.2f} бар"),
        _styled(f"Расход {model.calculated_flow_lpm:.2f} л/мин | цель {model.pressure_target_bar:.2f} бар"),
        _styled("Трубопровод: ", ("fault" if model.pipe_ruptured else "ok", "РАЗРУШЕН" if model.pipe_ruptured else "ИСПРАВЕН")),
    ]


def _status_ponics(model: BionicModel) -> list[StyledLine]:
    p = model.ponics
    dose_total = sum(p.dosing_totals.values())
    return [
        _heading("PONICPILOT · БП"),
        _styled(f"pH {p.tank.ph:.2f} | EC {p.tank.ec_ms_cm:.2f} мСм/см"),
        _styled(f"Температура {p.tank.temperature_c:.1f} °C"),
        _styled(f"Дозирование: {PONICS_STATE_LABELS.get(p.state, p.state)} | всего {dose_total:.1f} мл"),
        _styled("Устройство ID5: ", ("ok" if p.respond else "fault", "ГОТОВО" if p.respond else "НЕТ ОТВЕТА")),
        _styled(("demo", PONICS_DEMO_LABEL)),
    ]


def _status_drives(model: BionicModel) -> list[StyledLine]:
    lines = [_heading("ЧАСТОТНИКИ")]
    for drive_id in ("hp1", "hp2"):
        drive = model.drives[drive_id]
        command = model.drive_input_command(drive)
        faulted = bool(drive.fault)
        lines.append(_styled(
            f"{drive_id.upper()} CMD ", _state(command), " | ",
            ("fault" if faulted else "inactive", f"АВАРИЯ {drive.fault}" if faulted else "ошибок нет"),
        ))
        lines.append(_styled(
            f"    задано {drive.target_hz():.1f} Гц | факт {drive.actual_hz:.1f} Гц | ток {drive.calculated_current_a:.1f} А",
        ))
    return lines


def _status_lights(model: BionicModel) -> list[StyledLine]:
    lines = [_heading("ОСВЕЩЕНИЕ")]
    role_short = {"red": "R", "far_red": "FR", "blue": "B", "white": "W", "brightness": "BR"}
    for rack in (1, 2):
        parts: list[tuple[str, object] | object] = [f"Стеллаж {rack}: "]
        rack_lights = sorted((light for light in model.lights.values() if light.rack == rack), key=lambda item: item.tier)
        for index, light in enumerate(rack_lights):
            if index:
                parts.append(" | ")
            powered = model.relay(light.power_relay)
            active = [role_short.get(role, role) for role, state in model.light_channel_state(light.id).items() if state[3] > 0]
            channels = f"[{','.join(active) or '—'}]" if light.light_type == LightType.SPECTRAL_4 else ""
            parts += [f"Я{light.tier} ", _state(powered), channels]
        lines.append(_styled(*parts))
    return lines


def _status_alarms(model: BionicModel, journal: EventJournal, relay_warnings: list[str]) -> list[StyledLine]:
    alarms = [alarm for alarm in model.alarms.values() if alarm.state != AlarmState.CLEARED]
    equipment_failures = [equipment_id for equipment_id in EQUIPMENT_IDS if model.equipment_health(equipment_id).failed]
    count = len(alarms) + len(relay_warnings)
    lines = [_heading("АВАРИИ"), _styled("Активных: ", ("fault" if count else "ok", str(count)))]
    for alarm in alarms[-2:]:
        lines.append(_styled(("fault", f"{alarm.code}/{alarm.subject}: {alarm.state.value}")))
    if equipment_failures:
        lines.append(_styled(("fault", "Отказы: " + ", ".join(equipment_failures))))
    if model.pipe_ruptured and not any(alarm.code == "PIPE_RUPTURE" for alarm in alarms):
        lines.append(_styled(("fault", "PIPE_RUPTURE/pipe")))
    for warning in relay_warnings[:2]:
        lines.append(_styled(("warning", "РЕЛЕ: " + warning)))
    recent = journal.events[-3:]
    lines += [_styled("События: нет")] if not recent else [
        _styled(f"{event.at[11:19]} {event.kind} {event.subject}: {event.message}") for event in recent
    ]
    return lines


def _status_link(settings: BionicSettings, relay_state: SensorRelayState | None) -> list[StyledLine]:
    lines = [_heading("СВЯЗЬ")]
    lines.append(_styled(f"USB №1 {settings.controller_port}: ", ("inactive", "НАСТРОЕНО (без readback порта)")))
    if not settings.hardware_mode:
        lines.append(_styled(f"USB №2 {settings.sensor_relay_port}: ", ("inactive", "ОТКЛЮЧЕНО")))
    elif relay_state is not None and relay_state.online:
        mismatch = relay_state.confirmed != relay_state.desired
        lines.append(_styled(
            f"USB №2 {settings.sensor_relay_port}: ",
            ("warning" if mismatch else "ok", "РАСХОЖДЕНИЕ" if mismatch else "ПОДТВЕРЖДЕНО FC01"),
        ))
    else:
        lines.append(_styled(f"USB №2 {settings.sensor_relay_port}: ", ("warning", "НЕТ СВЯЗИ")))
    if relay_state is not None and relay_state.error:
        lines.append(_styled(("fault" if not relay_state.online else "warning", "Ошибка: " + relay_state.error)))
    return lines


def _join_status_columns(
    left: list[StyledLine], right: list[StyledLine], width: int,
) -> tuple[list[StyledLine], tuple[int, int]]:
    content_width = width - 5
    left_width = floor(content_width * 0.56)
    right_width = content_width - left_width
    count = max(len(left), len(right))
    left = [*left, *([tuple()] * (count - len(left)))]
    right = [*right, *([tuple()] * (count - len(right)))]
    return [
        (("", " "), *_fit_fragments(left[index], left_width, pad=True), ("", " │ "),
         *_fit_fragments(right[index], right_width, pad=True), ("", " "))
        for index in range(count)
    ], (left_width, right_width)


def _join_status_three_columns(
    left: list[StyledLine], middle: list[StyledLine], right: list[StyledLine], width: int,
) -> tuple[list[StyledLine], tuple[int, int, int]]:
    content_width = width - 8
    left_width = floor(content_width * 0.42)
    middle_width = floor(content_width * 0.31)
    right_width = content_width - left_width - middle_width
    count = max(len(left), len(middle), len(right))
    left = [*left, *([tuple()] * (count - len(left)))]
    middle = [*middle, *([tuple()] * (count - len(middle)))]
    right = [*right, *([tuple()] * (count - len(right)))]
    return [
        (
            ("", " "), *_fit_fragments(left[index], left_width, pad=True),
            ("", " │ "), *_fit_fragments(middle[index], middle_width, pad=True),
            ("", " │ "), *_fit_fragments(right[index], right_width, pad=True),
            ("", " "),
        )
        for index in range(count)
    ], (left_width, middle_width, right_width)


def _status(
    model: BionicModel, journal: EventJournal, settings: BionicSettings,
    relay_state: SensorRelayState | None, width: int,
) -> tuple[list[str], list[StyledLine], str, tuple[int, ...] | None]:
    if width >= 150:
        left_content_width = floor((width - 8) * 0.42)
    elif width >= 110:
        left_content_width = floor((width - 5) * 0.56)
    else:
        left_content_width = width
    sensors, relay_warnings = _status_sensors(
        model, settings, relay_state, left_content_width,
    )
    tanks = _status_tanks(model)
    pumps = _status_pumps(model, left_content_width)
    outputs = _status_outputs(model, left_content_width)
    hydraulics = _status_hydraulics(model)
    ponics = _status_ponics(model)
    drives = _status_drives(model)
    lights = _status_lights(model)
    alarms = _status_alarms(model, journal, relay_warnings)
    link = _status_link(settings, relay_state)
    if width >= 150:
        left = tanks + [tuple()] + sensors + [tuple()] + pumps + [tuple()] + outputs + [tuple()] + hydraulics
        middle = ponics + [tuple()] + drives + [tuple()] + lights + [tuple()] + alarms + [tuple()] + link
        gauges = _status_tank_gauges(model)
        styled_lines, column_widths = _join_status_three_columns(
            left, middle, gauges, width,
        )
        mode = "triple"
    elif width >= 110:
        left = tanks + [tuple()] + sensors + [tuple()] + pumps + [tuple()] + outputs + [tuple()] + hydraulics
        right = ponics + [tuple()] + drives + [tuple()] + lights + [tuple()] + alarms + [tuple()] + link
        styled_lines, column_widths = _join_status_columns(left, right, width)
        mode = "double"
    else:
        styled_lines = []
        for block in (tanks, sensors, pumps, ponics, drives, hydraulics, outputs, lights, alarms, link):
            if styled_lines:
                styled_lines.append(tuple())
            styled_lines.extend(_fit_fragments(line, width) for line in block)
        column_widths = None
        mode = "single"
    lines = [_plain(line) for line in styled_lines]
    return lines, styled_lines, mode, column_widths

def _devices(s:BionicSettings,width:int)->list[str]:
    rows=[("relay-32ch","Релейный модуль Waveshare 32CH",s.relay_address,"виртуальный"),("ao-1","Аналоговый выход №1",s.ao1_address,"виртуальный"),("ao-2","Аналоговый выход №2",s.ao2_address,"виртуальный"),("ao-3","Аналоговый выход №3",s.ao3_address,"виртуальный"),("ponics","PonicPilot 32 — бак БП",s.ponics_address,"виртуальный"),("ai-pressure","Аналоговый вход давления",s.ai_address,"виртуальный"),("hp1","Частотник высокого давления 1",s.hp1_address,"виртуальный"),("hp2","Частотник высокого давления 2",s.hp2_address,"виртуальный"),("sensor-relay","Физическое реле датчиков уровня",s.sensor_relay_id,"физический/USB №2")]
    if width < 60:
        lines=[_row([("ID",12),("Русское название",max(8,width-15))],width)]+[_row([(a,12),(b,max(8,width-15))],width) for a,b,_,_ in rows]+["","ИСПОЛНИТЕЛЬНЫЕ ВЫХОДЫ"]
        return lines+[ellipsize(f"do-{c:<2} | {n}",width) for c,n in OUTPUT_NAMES.items()]
    nw=max(12,min(18,width//5)); aw=8; tw=17; lw=max(12,width-nw-aw-tw-9); lines=[_row([("ID",nw),("Русское название",lw),("Modbus",aw),("Тип",tw)],width)]+[_row([(a,nw),(b,lw),(c,aw),(d,tw)],width) for a,b,c,d in rows]+["","ИСПОЛНИТЕЛЬНЫЕ ВЫХОДЫ"]
    return lines+[ellipsize(f"do-{c:<2} | {n}",width) for c,n in OUTPUT_NAMES.items()]

def _ports(s:BionicSettings,width:int)->list[str]:
    return [ellipsize(x,width) for x in ("USB №1 | Контроллер Bionic Mini | Modbus RTU slave",f"Порт: {s.controller_port} | {s.controller_baudrate} 8{s.controller_parity}{s.controller_stopbits:g}","Устройства: relay-32ch, ao-1..3, PonicPilot ID 5, ai-pressure, hp1, hp2","","USB №2 | Физическое реле датчиков | Modbus RTU master",f"Порт: {s.sensor_relay_port} | {s.sensor_relay_baudrate} 8{s.sensor_relay_parity}{s.sensor_relay_stopbits:g}",f"Waveshare {s.sensor_relay_channels}CH | ID {s.sensor_relay_id} | аппаратный режим {'ВКЛ' if s.hardware_mode else 'ВЫКЛ'}")]

def _technical(section:str,name:str)->str:
    return {"bo_capacity_l":"tanks.bo.capacity_l","bp_capacity_l":"tanks.bp.capacity_l","bso1_capacity_l":"tanks.bso1.capacity_l","bso2_capacity_l":"tanks.bso2.capacity_l"}.get(name,f"{section}.{name}")

def setting_rows(model:BionicModel,settings:BionicSettings,draft:BionicSettings,saved:BionicSettings,width:int)->tuple[list[str],list[str|None]]:
    sw=3; tw=max(12,min(34,width*30//100)); vw=max(8,min(20,width*18//100)); lw=max(8,width-tw-sw-vw-9)
    grouped:dict[str,list[tuple[str,str,str,str,str|None]]]={}
    for name,(section,_kind) in OPTION_SPECS.items():
        if name in {"light_profile", "equipment_profile"}:
            continue
        label,unit=SETTING_LABELS.get(name,(name.replace("_"," "),""))
        raw_value=getattr(draft,name)
        register_name=name[4:] if name.startswith(("hp1_", "hp2_")) else ""
        if register_name in DRIVE_SETTING_REGISTERS:
            decoded=decode_idd_value(DRIVE_SETTING_REGISTERS[register_name],int(raw_value))
            value=f"{raw_value} — {decoded}"
        elif name.endswith("_overload_protection_enabled"):
            value=f"{int(raw_value)} — {decode_idd_value(816,int(raw_value))}"
        else:
            value=f"{raw_value} {unit}".rstrip()
        state=("A" if getattr(draft,name)==getattr(settings,name) else "-")+"/"+("S" if getattr(draft,name)==getattr(saved,name) else "-")
        grouped.setdefault(section,[]).append((_technical(section,name),label,value,state,name))
    applied_equipment=parse_equipment_profile(settings.equipment_profile)
    draft_equipment=parse_equipment_profile(draft.equipment_profile)
    saved_equipment=parse_equipment_profile(saved.equipment_profile)
    for equipment_id in EQUIPMENT_IDS:
        draft_profile=draft_equipment[equipment_id]
        applied_profile=applied_equipment[equipment_id]
        saved_profile=saved_equipment[equipment_id]
        rows=grouped.setdefault("equipment",[])
        equipment_name=EQUIPMENT_SETTING_NAMES[equipment_id].split(": время",1)[0]
        for field_name,(field_label,unit) in EQUIPMENT_FIELD_LABELS.items():
            draft_value=getattr(draft_profile,field_name)
            state=("A" if draft_value==getattr(applied_profile,field_name) else "-")+"/"+("S" if draft_value==getattr(saved_profile,field_name) else "-")
            rendered=(f"{draft_value:.9g}" if isinstance(draft_value,float) else str(draft_value))
            value_text=(
                f"{rendered} с (расчётное) (ДЕМО)"
                if field_name=="failure_s" else
                f"{rendered} {unit} (ДЕМО)".replace("  "," ").strip()
            )
            rows.append((
                f"equipment.{equipment_id}.{field_name}",
                f"{equipment_name}: {field_label}",
                value_text, state,
                f"equipment:{equipment_id}:{field_name}",
            ))
        lifetime=lifetime_for_new_equipment(draft_profile)
        wear_time="∞" if lifetime.wear_s == float("inf") else f"{lifetime.wear_s:g} с"
        rows += [
            (f"equipment.{equipment_id}.effective_lifetime",f"{EQUIPMENT_SETTING_NAMES[equipment_id]}: эффективный ресурс нового насоса",f"{lifetime.effective_s:g} с; {lifetime.limiting_mechanism} (ДЕМО)","-",None),
            (f"equipment.{equipment_id}.wear_lifetime",f"{EQUIPMENT_SETTING_NAMES[equipment_id]}: отказ нового насоса по износу",f"{wear_time} (ДЕМО)","-",None),
            (f"state.{equipment_id}.damage",f"{EQUIPMENT_SETTING_NAMES[equipment_id]}: текущий необратимый износ",f"{model.equipment_health(equipment_id).damage*100:.1f}% (состояние)","-",None),
            (f"state.{equipment_id}.remaining",f"{EQUIPMENT_SETTING_NAMES[equipment_id]}: осталось при непрерывном сухом ходе",f"{remaining_dry_run_s(model.equipment_health(equipment_id)):g} с (ДЕМО)","-",None),
        ]
    lines=[ellipsize("A — применено, S — сохранено. Параметры демонстрационной модели не являются измеренными характеристиками.",width)]
    keys: list[str | None]=[None]
    ordered_sections=[*SETTINGS_GROUP_ORDER,*sorted(set(grouped)-set(SETTINGS_GROUP_ORDER))]
    for section in ordered_sections:
        rows=grouped.get(section,[])
        if not rows:
            continue
        lines += ["",SETTINGS_GROUP_TITLES.get(section,section.upper()),_row([("Техническое имя",tw),("Русское название",lw),("Значение",vw),("A/S",sw)],width)]
        keys += [None,None,None]
        for technical,label,value,state,key in sorted(rows,key=lambda item:item[1].casefold()):
            lines.append(_row([(technical,tw),(label,lw),(value,vw),(state,sw)],width))
            keys.append(key)
    return lines,keys

def _relay_link(settings:BionicSettings,state:SensorRelayState|None)->str:
    if not settings.hardware_mode: return "ОТКЛЮЧЕНО"
    return "ПОДКЛЮЧЕНО" if state is not None and state.online else "НЕТ СВЯЗИ"

def _sensor_name(sensor_id:str)->str:
    tank_id,kind=sensor_id.rsplit("-",1)
    return f"{TANK_NAMES[tank_id]}: {'минимум' if kind=='min' else 'максимум'}"

def _relay_bit(image:int|None,channel:int)->bool|None:
    return None if image is None else bool(image & (1 << (channel-1)))

def _on_off(value:bool|None,*,offline:str="НЕТ СВЯЗИ")->str:
    if value is None: return offline
    return "ВКЛ" if value else "ВЫКЛ"

def _sensor_rows(model:BionicModel,settings:BionicSettings,state:SensorRelayState|None,width:int)->tuple[list[str],list[str|None]]:
    mapping=parse_sensor_relay_map(settings.sensor_relay_map)
    desired=sum((int(model.sensors[sensor_id].value ^ settings.sensor_relay_active_low) << (channel-1)) for sensor_id,channel in mapping.items())
    confirmed=state.confirmed if state is not None and state.online else None
    lines=[
        ellipsize(f"RS485 №2: {settings.sensor_relay_port} | Waveshare {settings.sensor_relay_channels}CH | ID {settings.sensor_relay_id}",width),
        f"Связь: {_relay_link(settings,state)}",
        ellipsize("Последний успешный обмен: "+((state.last_success_at[:19].replace("T"," ")) if state and state.last_success_at else "нет"),width),
        ellipsize(f"Монтаж: контакт {settings.sensor_relay_contact} | полярность {'ACTIVE LOW' if settings.sensor_relay_active_low else 'ACTIVE HIGH'}",width),
        "",
    ]
    compact=width<105
    if compact:
        lines.append(_row([("CH",4),("Датчик",9),("Порог",15),("Р/С/Т/П",15),("Режим",8)],width))
    else:
        lines.append(_row([("Канал",6),("Датчик",10),("Русское название",18),("Порог",15),("Расчёт",7),("Сигнал",7),("Треб.",7),("Подтв.",10),("Режим",14)],width))
    keys:list[str|None]=[None]*len(lines)
    for sensor_id,channel in sorted(mapping.items(),key=lambda item:item[1]):
        sensor=model.sensors[sensor_id]
        mode="AUTO" if sensor.forced is None else ("FORCE ON" if sensor.forced else "FORCE OFF")
        required=_relay_bit(desired,channel); acknowledged=_relay_bit(confirmed,channel)
        capacity=model.tanks[sensor.tank_id].capacity_l
        threshold=f"{sensor.threshold_l:g} л/{sensor.threshold_l/capacity*100:.1f}%"
        if compact:
            unknown="-" if not settings.hardware_mode else "?"
            states=f"{int(sensor.automatic)}/{int(sensor.value)}/{int(bool(required))}/{(unknown if acknowledged is None else int(acknowledged))}"
            lines.append(_row([(f"CH{channel}",4),(sensor_id,9),(threshold,15),(states,15),(mode.replace('FORCE ','F-'),8)],width))
        else:
            offline="ОТКЛ" if not settings.hardware_mode else "НЕТ СВЯЗИ"
            lines.append(_row([(f"CH{channel}",6),(sensor_id,10),(_sensor_name(sensor_id),18),(threshold,15),(_on_off(sensor.automatic),7),(_on_off(sensor.value),7),(_on_off(required),7),(_on_off(acknowledged,offline=offline),10),(mode,14)],width))
        keys.append(f"sensor:{sensor_id}")
    lines += ["",ellipsize("Расчёт/Р — автоматика; Сигнал/С — с FORCE; Треб./Т — команда; Подтв./П — FC01.",width)]
    keys += [None,None]
    return lines,keys

def _sensor_setting_rows(model:BionicModel,settings:BionicSettings,width:int)->tuple[list[str],list[str|None]]:
    mapping=parse_sensor_relay_map(settings.sensor_relay_map)
    lines=[_row([("Датчик",10),("Бак / тип",22),("Порог",16),("Расчёт",8),("Канал",7),("Полярн.",11),("Контакт",8),("Режим",14)],width)]
    keys:list[str|None]=[None]
    for sensor_id,channel in sorted(mapping.items(),key=lambda item:item[1]):
        sensor=model.sensors[sensor_id]
        mode="AUTO" if sensor.forced is None else ("FORCE ON" if sensor.forced else "FORCE OFF")
        capacity=getattr(settings,f"{sensor.tank_id}_capacity_l")
        threshold_l=getattr(settings,f"{sensor_id.replace('-', '_')}_threshold_l")
        threshold=f"{threshold_l:g} л / {threshold_l/capacity*100:.1f}%"
        lines.append(_row([(sensor_id,10),(_sensor_name(sensor_id),22),(threshold,16),(_on_off(sensor.automatic),8),(f"CH{channel}",7),("LOW" if settings.sensor_relay_active_low else "HIGH",11),(settings.sensor_relay_contact,8),(mode,14)],width))
        keys.append(f"sensor:{sensor_id}")
    return lines,keys

def _settings(model:BionicModel,settings:BionicSettings,draft:BionicSettings,saved:BionicSettings,state:SensorRelayState|None,width:int)->tuple[list[str],list[str|None]]:
    sensor_lines,sensor_keys=_sensor_setting_rows(model,draft,width)
    generic_lines,generic_keys=setting_rows(model,settings,draft,saved,width)
    mapping=parse_sensor_relay_map(draft.sensor_relay_map)
    last=(state.last_success_at[:19].replace("T"," ")) if state and state.last_success_at else "нет"
    module=[
        "", "МОДУЛЬ РЕЛЕ ДАТЧИКОВ",
        ellipsize(f"USB/COM: {draft.sensor_relay_port} | Modbus ID {draft.sensor_relay_id} | Waveshare {draft.sensor_relay_channels}CH",width),
        ellipsize(f"Линия: {draft.sensor_relay_baudrate} бод | {draft.sensor_relay_parity} | {draft.sensor_relay_stopbits:g} стоп-бит",width),
        ellipsize(f"Полярность: {'ACTIVE LOW' if draft.sensor_relay_active_low else 'ACTIVE HIGH'} | монтажный контакт: {draft.sensor_relay_contact}",width),
        ellipsize(f"Связь: {_relay_link(draft,state)} | последний успешный обмен: {last}",width),
        ellipsize(f"Карта: {draft.sensor_relay_map}",width),
        "", "ПОДСКАЗКА МОНТАЖНИКУ",
        *[ellipsize(f"CH{channel} — {_sensor_name(sensor_id)}, датчик {'минимального' if sensor_id.endswith('-min') else 'максимального'} уровня",width) for sensor_id,channel in sorted(mapping.items(),key=lambda item:item[1])],
        "", "ВСЕ НАСТРОЙКИ",
    ]
    lines=["ДАТЧИКИ УРОВНЯ"]+sensor_lines+module+generic_lines
    keys=[None]+sensor_keys+[None]*len(module)+generic_keys
    return lines,keys

def _help(width:int,query:str)->list[str]:
    q=query.casefold().strip(); lines=["Поиск: "+(q or "нет")+"  (help search <текст>)",""]
    for title,body in HELP_GROUPS:
        if q and q not in title.casefold() and q not in body.casefold(): continue
        lines += [title,*[ellipsize(line,width) for line in body.splitlines()],""]
    return lines

def simulation_status(model:BionicModel)->str:
    if model.paused:
        state="ПАУЗА"
    elif model.running:
        state="РАБОТАЕТ"
    else:
        state="ОСТАНОВЛЕНА"
    return f"СИМУЛЯЦИЯ: {state} | СКОРОСТЬ: ×{model.speed:.1f}"

def _pressure(model:BionicModel,width:int)->list[str]:
    drive=max(model.drives.values(),key=lambda item:item.actual_hz)
    active=[tier for tier in model.tiers.values() if model.relay(tier.relay)]
    source_ids=model.selected_sources()
    source_names={"bo":"БО (Осмос)","bp":"БП (Бульон)"}
    selected=", ".join(source_names[item] for item in source_ids) or "нет — путь закрыт"
    available=", ".join(source_names[item] for item in model.available_sources()) or "нет"
    lines=[
        "ГИДРАВЛИКА ВЫСОКОГО ДАВЛЕНИЯ",
        f"HP: {drive.id.upper()} | команда {'RUN' if model.drive_commanded(drive) else 'STOP'} | факт {'RUN' if drive.actual_hz>0.1 else 'STOP'} | частота {drive.actual_hz:.1f} Гц",
        f"Ярусы открыты: {len(active)} из {len(model.tiers)} | "+(", ".join(tier.id for tier in active) or "нет"),
        "Клапаны ярусов: "+" | ".join(f"do-{tier.relay} {'ОТКР' if model.relay(tier.relay) else 'ЗАКР'}" for tier in model.tiers.values()),
        f"Насос подпора do-{model.outputs['boost']}: {'RUN' if model.relay(model.outputs['boost']) else 'STOP'} | LOW {model.low_pressure_bar:.2f} бар",
        f"Источник: {selected} | доступна вода: {available}",
        f"Клапаны источника: do-{model.outputs['source_osmosis']} {'ОТКР' if model.relay(model.outputs['source_osmosis']) else 'ЗАКР'} | do-{model.outputs['source_broth']} {'ОТКР' if model.relay(model.outputs['source_broth']) else 'ЗАКР'}",
        "",
        f"Расчётный расход: {model.calculated_flow_lpm:.2f} л/мин",
        f"HIGH, текущее давление: {model.high_pressure_bar:.2f} бар",
        f"Целевое давление модели: {model.pressure_target_bar:.2f} бар",
        f"Последний переходный скачок: +{model.last_pressure_spike_bar:.2f} бар",
        f"Максимальное зафиксированное давление: {model.max_pressure_bar:.2f} бар",
        f"Трубопровод: {'РАЗРУШЕН — требуется pipe repair' if model.pipe_ruptured else 'ИСПРАВЕН'}",
        "",
        f"Засор: {'ВКЛ' if model.blockage_enabled else 'ВЫКЛ'} | степень {model.blockage_severity:.0f}% | положение: {model.blockage_position}",
        f"Расчётное относительное сопротивление: ×{model.hydraulic_resistance:.2f}",
    ]
    return [ellipsize(line,width) for line in lines]

def _log(j:EventJournal,category:str,width:int)->list[str]:
    return [f"Фильтр: {category}","Дата/время                | Тип       | Объект       | Событие"]+[ellipsize(f"{e.at[:19]:<24} | {e.kind:<9} | {e.subject:<12} | {e.message}",width) for e in j.filtered(category)]

def _ponics_banner(width:int)->list[str]:
    return [ellipsize(PONICS_TANK_LABEL,width),ellipsize(PONICS_DEMO_LABEL,width),""]

def _ponics(model:BionicModel,settings:BionicSettings,width:int)->list[str]:
    p=model.ponics; tank=p.tank; registers=p.registers(); last=p.last_success_at[:19].replace("T"," ") if p.last_success_at else "нет"
    lines=_ponics_banner(width)+[
        f"PonicPilot 32 | Modbus ID {settings.ponics_address} | связь: {'НЕТ ОТВЕТА' if not p.respond else 'ГОТОВ'} | последний обмен: {last}",
        "ИЗМЕРЕНИЯ ИЗ ОБЩЕЙ МОДЕЛИ БП",
        f"pH {tank.ph:.2f} | EC {tank.ec_ms_cm:.2f} мСм/см | температура {tank.temperature_c:.1f} °C | объём {tank.volume_l:.1f} л",
        "",
        "РАБОТА",
        f"Режим: {p.settings[23]} | состояние: {p.state} — {PONICS_STATE_LABELS.get(p.state,'неизвестно')}",
        f"Полив / пауза: {registers[8]} / {registers[9]} с | DI 0x{registers[10]:04X} | DO 0x{registers[12]:04X}",
        f"Аварии: 0x{registers[19]:04X}{registers[20]:04X}",
        "",
        "ДОЗИРОВАНИЕ — ТОЛЬКО В БП",
        f"A / B / C: {p.dosing_totals['a']:.1f} / {p.dosing_totals['b']:.1f} / {p.dosing_totals['c']:.1f} мл",
        f"pH+ / pH−: {p.dosing_totals['ph_plus']:.1f} / {p.dosing_totals['ph_minus']:.1f} мл",
        "",
        "ДИАГНОСТИКА",
        f"Запросы / ответы: {p.requests} / {p.responses} | CRC: {p.crc_errors} | функции: {p.function_errors} | адреса: {p.address_errors}",
        f"Последнее чтение: {p.last_read_range or 'нет'} | последняя запись PDU: {p.last_written_register if p.last_written_register is not None else 'нет'}",
    ]
    return [ellipsize(line,width) for line in lines]

def _ponics_settings(model:BionicModel,width:int)->tuple[list[str],list[str|None]]:
    p=model.ponics; values=p.registers()
    lines=_ponics_banner(width)+[
        "WEB | PDU | Параметр                         | RAW   | Значение             | Доступ",
    ]
    keys:list[str|None]=[None]*len(lines)
    for index in sorted(p.settings):
        register=PONICS_REGISTERS[index]
        lines.append(_row([(index,4),(index,4),(register.name,32),(values[index],6),(p.engineering_value(index,values[index]),20),(register.access,7)],width))
        keys.append(PONICS_OPTION_NAMES[index])
    lines += ["","ДЕМОНСТРАЦИОННАЯ МОДЕЛЬ РАСТВОРА",f"Источник измерений и единственная точка дозирования: {PONICS_TANK_LABEL}","Выбор обслуживаемого бака отсутствует намеренно."]
    keys += [None]*4
    return [ellipsize(line,width) for line in lines],keys

def _ponics_registers(model:BionicModel,width:int)->list[str]:
    p=model.ponics; values=p.registers()
    lines=_ponics_banner(width)+[
        "IDX | PDU | Ручн. | Название                     | RAW DEC | RAW HEX | Инженерное        | Доступ | Источник / время"
    ]
    for register,value in zip(PONICS_REGISTERS,values):
        source=p.register_sources[register.index]
        changed=p.register_changed_at[register.index]
        lines.append(_row([(register.index,3),(register.pdu_address,3),(register.manual_address,5),(register.name,28),(value,7),(f"0x{value:04X}",8),(p.engineering_value(register.index,value),18),(register.access,7),(f"{source} {changed}",24)],width))
    return [ellipsize(line,width) for line in lines]

def _water(model:BionicModel,width:int)->list[str]:
    lines=["Бак  | Название   | Объём, л        | EC, мСм/см | pH   | Темп., °C | Поглощено"]
    for tank in model.tanks.values():
        lines.append(_row([(tank.id,4),(TANK_NAMES[tank.id],10),(f"{tank.volume_l:.1f}/{tank.capacity_l:.1f}",15),(f"{tank.ec_ms_cm:.3f}",10),(f"{tank.ph:.2f}",5),(f"{tank.temperature_c:.1f}",9),(f"{tank.nutrients_consumed:.3f}",10)],width))
    lines += ["","ТЕКУЩИЕ ПОТОКИ"]
    lines += [ellipsize(f"{PUMP_NAMES[p.id]}: {p.actual_flow_lpm:.2f} л/мин",width) for p in model.pumps.values()]
    lines += [
        f"Входящая вода осмоса: EC {model.osmosis_profile['ec']:.2f}, pH {model.osmosis_profile['ph']:.2f}, {model.osmosis_profile['temperature']:.1f} °C",
        f"Водопровод (справочно, подтверждённого пути нет): EC {model.tap_profile['ec']:.2f}, pH {model.tap_profile['ph']:.2f}, {model.tap_profile['temperature']:.1f} °C",
        f"Потери полива: {model.total_irrigation_loss_l:.2f} л | растения: {model.total_plant_water_uptake_l:.2f} л | испарение: {model.total_irrigation_evaporation_l:.2f} л",
        f"Протечки: {model.current_leak_flow_lpm:.2f} л/мин | накоплено: {model.total_leak_l:.2f} л",
        f"PonicPilot дозировал в БП: {sum(model.ponics.dosing_totals.values()):.1f} мл",
    ]
    return [ellipsize(line,width) for line in lines]

def _light(model:BionicModel,width:int)->list[str]:
    lines=[
        "ТЕКУЩИЕ СИГНАЛЫ ОСВЕЩЕНИЯ",
        "Напряжение и яркость — заданные управляющие сигналы виртуальных AO, не измеренная световая мощность.",
        "Для профиля 0–10 В: яркость, % = напряжение / 10 × 100.",
    ]
    for light in sorted(model.lights.values(),key=lambda item:(item.rack,item.tier)):
        lines += ["",f"{light.id} | {light.name} | Стеллаж {light.rack}, ярус {light.tier} | тип {light.light_type.value} | {'ВКЛЮЧЁН В КОНФИГУРАЦИЮ' if light.enabled else 'ИСКЛЮЧЁН ИЗ КОНФИГУРАЦИИ'}"]
        if light.light_type == LightType.NONE:
            lines.append("Светильник не установлен")
            continue
        powered=model.relay(light.power_relay)
        effective=model.light_effective(light.id)
        lines.append(f"Питание DO{light.power_relay}: {'ВКЛ' if powered else 'ВЫКЛ'} | фактический свет: {'ВКЛ' if effective else 'ВЫКЛ'}")
        for role,(device,channel,voltage,brightness) in model.light_channel_state(light.id).items():
            lines.append(f"  {ROLE_LABELS[role]} | Modbus ID {device} / AO{channel} | задание {voltage:.3f} В | яркость {brightness:.1f}%")
    return [ellipsize(line,width) for line in lines]

def _light_settings(settings:BionicSettings,draft:BionicSettings,saved:BionicSettings,width:int)->tuple[list[str],list[str|None]]:
    applied={light.id:light for light in parse_light_profile(settings.light_profile)}
    pending=parse_light_profile(draft.light_profile)
    stored={light.id:light for light in parse_light_profile(saved.light_profile)}
    factory={light.id:light for light in FACTORY_LIGHTS}
    lines=[
        "ПРОФИЛЬ ОСВЕЩЕНИЯ: F — заводской, A — применён, S — сохранён",
        "F5: применить только свет | Ctrl+S: сохранить только свет | Esc: выйти без применения",
        "Команды: light set <zone> type|rack|tier|relay|enabled|name|channel|voltage|brightness ...",
        "Восстановление: light restore-defaults (меняет только черновик освещения)",
        "",
    ]
    keys:list[str|None]=[None]*len(lines)
    try:
        validate_light_profile(pending,{settings.ao1_address,settings.ao2_address,settings.ao3_address})
        lines += ["Проверка черновика: КОРРЕКТЕН",""]
    except ValueError as exc:
        lines += [ellipsize(f"Проверка черновика: ОШИБКА — {exc}",width),""]
    keys += [None,None]
    for light in sorted(pending,key=lambda item:(item.rack,item.tier)):
        state=("F" if light==factory.get(light.id) else "-")+"/"+("A" if light==applied.get(light.id) else "-")+"/"+("S" if light==stored.get(light.id) else "-")
        lines.append(f"{light.id} | Стеллаж {light.rack}, ярус {light.tier} | {light.name} | {light.light_type.value} | DO{light.power_relay} | {'ВКЛЮЧЁН' if light.enabled else 'ИСКЛЮЧЁН'} | F/A/S {state}")
        keys.append(f"light:{light.id}")
        lines.append(f"  Диапазон: {light.min_voltage_v:g}–{light.max_voltage_v:g} В | {light.min_brightness_pct:g}–{light.max_brightness_pct:g}%")
        keys.append(None)
        if light.light_type == LightType.NONE:
            lines.append("  Аналоговые каналы: не требуются")
            keys.append(None)
        else:
            for binding in light.channels:
                assigned=(f"Modbus ID {binding.device_id} / AO{binding.channel}" if binding.device_id and binding.channel else "НЕ НАЗНАЧЕН")
                lines.append(f"  {ROLE_LABELS[binding.role]}: {assigned}")
                keys.append(None)
    return [ellipsize(line,width) for line in lines],keys

def _equipment(model:BionicModel,settings:BionicSettings,draft:BionicSettings,saved:BionicSettings,width:int)->list[str]:
    profiles=parse_equipment_profile(settings.equipment_profile)
    draft_profiles=parse_equipment_profile(draft.equipment_profile)
    saved_profiles=parse_equipment_profile(saved.equipment_profile)
    lines=[
        "АВТОМАТИЧЕСКОЕ РАЗВИТИЕ ПОВРЕЖДЕНИЙ",
        "Внутренняя диагностика имитатора: отдельные аварийные сигналы контроллеру не передаются.",
        "Команда платы сохраняется при отказе. Ремонт: equipment repair <id> --confirm.",
        "",
        _row([("Оборудование",12),("Команда",8),("Факт",8),("Состояние",13),("Расход",11),("Сух. ход",10),("Нагрев",8),("Износ",8),("Ремонт",8),("Отказ",17)],width),
    ]
    for equipment_id in EQUIPMENT_IDS:
        health=model.equipment_health(equipment_id)
        commanded=model.equipment_commanded(equipment_id)
        if equipment_id in model.pumps:
            actual=model.pumps[equipment_id].actual_flow_lpm > 1e-6
            flow=model.pumps[equipment_id].actual_flow_lpm
            water_available=model.tanks[model.pumps[equipment_id].source].volume_l > 1e-9
            pressure="—"
        else:
            drive=model.drives[equipment_id]
            actual=drive.actual_hz > 0.1 and drive.hydraulic_factor > 0
            flow=model.calculated_flow_lpm if actual else 0.0
            water_available=model.relay(model.outputs["boost"]) and bool(model.available_sources())
            pressure=f"{model.high_pressure_bar:.2f} бар"
        lines.append(_row([
            (equipment_id,12),("RUN" if commanded else "STOP",8),("RUN" if actual else "STOP",8),
            (EQUIPMENT_STATE_NAMES[health.state],13),(f"{flow:.2f} л/мин",11),(f"{health.dry_run_s:.1f} с",10),
            (f"{health.heat*100:.1f}%",8),(f"{health.damage*100:.1f}%",8),("ДА" if health.repair_required else "нет",8),(PUMP_FAILURE_NAMES.get(health.failure,health.failure),17),
        ],width))
        profile=profiles[equipment_id]
        lines.append(ellipsize(
            f"  вода: {'доступна' if water_available else 'НЕТ'}; создаваемое давление: {pressure}; "
            f"суммарный сухой ход {health.total_dry_run_s:.1f} с; замен {health.replacements}",
            width,
        ))
        lines.append(ellipsize(
            f"  пороги, с: предупреждение {profile.dry_run_warning_s:g}; перегрев {profile.overheat_s:g}; "
            f"деградация {profile.degrade_s:g}; отказ {profile.failure_s:g}; тип отказа {profile.failure_type}",
            width,
        ))
        lifetime=lifetime_for_new_equipment(profile)
        wear_time="∞" if lifetime.wear_s == float("inf") else f"{lifetime.wear_s:g} с"
        failure_state=("A" if draft_profiles[equipment_id].failure_s==profile.failure_s else "-")+"/"+("S" if draft_profiles[equipment_id].failure_s==saved_profiles[equipment_id].failure_s else "-")
        wear_state=("A" if draft_profiles[equipment_id].wear_rate_per_s==profile.wear_rate_per_s else "-")+"/"+("S" if draft_profiles[equipment_id].wear_rate_per_s==saved_profiles[equipment_id].wear_rate_per_s else "-")
        lines.append(ellipsize(
            f"  failure_s {profile.failure_s:g} с [{failure_state}] — непрерывный сухой ход; "
            f"wear_rate_per_s {profile.wear_rate_per_s:.9g} 1/с [{wear_state}] — необратимый износ",
            width,
        ))
        lines.append(ellipsize(
            f"  ДЕМО: новый насос — по износу {wear_time}, эффективно {lifetime.effective_s:g} с "
            f"({lifetime.limiting_mechanism}); текущий износ {health.damage*100:.1f}%; "
            f"осталось при непрерывном сухом ходе {remaining_dry_run_s(health):g} с",
            width,
        ))
    lines += [
        "",
        "Настройка: equipment set <id> failure_s <с> [--sync-wear]; equipment sync-wear <id>.",
        "Дополнительно: heating_rate_per_s, cooling_rate_per_s, wear_rate_per_s, wear_flow_reduction, initial_state, failure_type.",
        "failure_s не является STOP платы: имитатор меняет физику насоса, но сохраняет команду контроллера.",
        "Применение/сохранение: settings apply / settings save. initial_state применяется при следующем сбросе модели.",
    ]
    return [ellipsize(line,width) for line in lines]

def _drives(model:BionicModel,settings:BionicSettings,width:int)->list[str]:
    lines=["Привод | ID | Источник | Modbus | Клемма | Выбор | Факт | Частота | Ток | Ошибка"]
    for drive_id,drive in model.drives.items():
        lines.append(_row([(drive_id.upper(),6),(drive.address,3),(DRIVE_SOURCE_NAMES[drive.control_source],9),("RUN" if drive.run_register else "STOP",7),("ON" if model.relay(drive.run_relay) else "OFF",7),("ON" if model.relay(drive.selector_relay) else "OFF",6),("RUN" if drive.actual_hz>0.1 else "STOP",5),(f"{drive.actual_hz:.1f} Гц",9),(f"{drive.calculated_current_a:.1f} А",8),(drive.fault,6)],width))
    lines += ["",f"do-19 выбор HP1: {_on_off(model.relay(19))} | do-20 выбор HP2: {_on_off(model.relay(20))}",f"do-32 RUN HP1: {_on_off(model.relay(32))} | do-31 RUN HP2: {_on_off(model.relay(31))}"]
    return [ellipsize(line,width) for line in lines]

def _drive(model:BionicModel,drive_id:str,width:int)->list[str]:
    drive=model.drives[drive_id]
    telemetry={1:round(drive.target_hz()*10),2:round(drive.actual_hz*10),3:round(drive.calculated_current_a*10),4:drive.speed_rpm,27:drive.fault,28:int(drive.actual_hz>0.1)}
    configuration=drive.configuration
    lines=["ТЕКУЩАЯ РАБОТА",f"Источник RUN: PB.02={configuration[102]} ({DRIVE_SOURCE_NAMES[drive.control_source]}) | команда платы: {'RUN' if model.drive_input_command(drive) else 'STOP'} | разрешение ПЧ: {'RUN' if model.drive_commanded(drive) else 'STOP'}",f"Команда Modbus: {'RUN' if drive.run_register else 'STOP'} | RUN-клемма do-{drive.run_relay}: {_on_off(model.relay(drive.run_relay))} | выбор do-{drive.selector_relay}: {_on_off(model.relay(drive.selector_relay))}",f"Задание {drive.target_hz():.1f} Гц | выход ПЧ {drive.actual_hz:.1f} Гц | разгон/торможение {drive.ramp_up_s:g}/{drive.ramp_down_s:g} с",f"РАСЧЁТ ИМИТАТОРА: ток {drive.calculated_current_a:.1f}/{drive.nominal_current_a:.1f} А | нагрузка ×{drive.calculated_load:.2f} | защита {PROTECTION_NAMES[drive.protection_state]}",f"Насос: {PUMP_FAILURE_NAMES[drive.mechanical_failure]} | повреждение {drive.mechanical_damage*100:.0f}% | ремонт {'ТРЕБУЕТСЯ' if drive.repair_required else 'не требуется'}",f"Штатный PA.27: {drive.fault} | RESET {'возможен, механику не ремонтирует' if drive.fault else 'не требуется'} | связь {'есть' if drive.online else 'нет'}","","РЕГИСТРЫ",_row([("Имя",6),("Адрес",6),("Название",33),("RAW",6),("Значение",36),("Доступ",6)],width)]
    for address,value in {**telemetry,**configuration}.items():
        if address in IDD_TELEMETRY:
            code,label,_detail=IDD_TELEMETRY[address]
            access="R"
        else:
            spec=IDD_PARAMETERS[address]
            code,label=spec.code,spec.label
            access="RW"
        lines.append(_row([(code,6),(address,6),(label,33),(value,6),(decode_idd_value(address,value),36),(access,6)],width))
    lines += ["","RW-параметры проверяются по документированным диапазонам; PA.* доступны только для чтения.","Внутренний тип поломки показывается только здесь и не передаётся плате отдельным сигналом."]
    return [ellipsize(line,width) for line in lines]

def render_page(name:str,model:BionicModel,journal:EventJournal,settings:BionicSettings,draft:BionicSettings,saved:BionicSettings,*,width:int,log_filter:str="all",help_query:str="",relay_state:SensorRelayState|None=None)->ScreenPage:
    name="status" if name=="main" else name; keys:list[str|None]=[]
    styled_lines: list[StyledLine] | None = None
    layout_mode = "single"
    column_widths: tuple[int, int] | None = None
    if name=="status":
        lines,styled_lines,layout_mode,column_widths=_status(model,journal,settings,relay_state,width)
    elif name=="devices": lines=_devices(settings,width)
    elif name=="ports": lines=_ports(settings,width)
    elif name=="settings": lines,keys=_settings(model,settings,draft,saved,relay_state,width)
    elif name=="help": lines=_help(width,help_query)
    elif name=="log": lines=_log(journal,log_filter,width)
    elif name=="tanks": lines=[f"{t.id} | {TANK_NAMES[t.id]} | {t.volume_l:.1f}/{t.capacity_l:.1f} л | MIN {model.sensors[f'{t.id}-min'].threshold_l:g} л | MAX {model.sensors[f'{t.id}-max'].threshold_l:g} л | перелив {t.overflow_l:.1f} л" for t in model.tanks.values()]
    elif name=="pumps": lines=[f"{p.id} | {PUMP_NAMES[p.id]} | {'RUN' if model.relay(p.relay) else 'STOP'} | {p.actual_flow_lpm:.1f} л/мин" for p in model.pumps.values()]
    elif name=="equipment": lines=_equipment(model,settings,draft,saved,width)
    elif name=="pressure": lines=_pressure(model,width)
    elif name=="irrigation": lines=[f"{t.id} | Стеллаж {t.rack}, ярус | do-{t.relay} | {t.actual_flow_lpm:.1f} л/мин" for t in model.tiers.values()]
    elif name=="light": lines=_light(model,width)
    elif name=="light-settings": lines,keys=_light_settings(settings,draft,saved,width)
    elif name=="sensors": lines,keys=_sensor_rows(model,settings,relay_state,width)
    elif name=="ponics": lines=_ponics(model,settings,width)
    elif name=="ponics-settings": lines,keys=_ponics_settings(model,width)
    elif name=="ponics-registers": lines=_ponics_registers(model,width)
    elif name=="water": lines=_water(model,width)
    elif name=="drives": lines=_drives(model,settings,width)
    elif name=="drive-hp1": lines=_drive(model,"hp1",width)
    elif name=="drive-hp2": lines=_drive(model,"hp2",width)
    elif name=="rs485": lines=_ports(settings,width)+["",f"Адреса USB №1: {settings.relay_address} Relay, {settings.ao1_address}..{settings.ao3_address} AO, {settings.ponics_address} PonicPilot, {settings.ai_address} AI, {settings.hp1_address} HP1, {settings.hp2_address} HP2"]
    else: lines=[f"Неизвестный экран: {name}"]
    if name.startswith("ponics"):
        title=f"PONICPILOT • {PONICS_TANK_LABEL} • {PONICS_DEMO_LABEL}"
    else:
        title=VIEW_TITLES.get(name,name.upper())
    return ScreenPage(
        title,[ellipsize(x,width) for x in lines],keys or [None]*len(lines),
        simulation_status(model),styled_lines,layout_mode,column_widths,
    )

def visible_lines(page:ScreenPage,*,height:int,scroll:int=0)->list[str]:
    height=max(1,height); start=min(max(scroll,0),max(0,len(page.lines)-height)); lines=page.lines[start:start+height]; return lines+[""]*(height-len(lines))

def print_view(console:Console,name:str,model:BionicModel,journal:EventJournal,settings:BionicSettings,draft:BionicSettings,saved:BionicSettings|None=None,relay_state:SensorRelayState|None=None)->None:
    page=render_page(name,model,journal,settings,draft,saved or settings,width=console.width,relay_state=relay_state)
    output=Text("BIONIC IMMITATOR — "+page.simulation_status+" | "+page.title+"\n")
    for index,line in enumerate(page.lines):
        fragments=(page.styled_lines[index] if page.styled_lines is not None else (("",line),))
        for style,text in fragments:
            output.append(text,style=RICH_STYLES.get(style,""))
        if index < len(page.lines)-1:
            output.append("\n")
    console.print(output)
