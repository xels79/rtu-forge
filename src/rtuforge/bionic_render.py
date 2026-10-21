"""Width-aware, non-scrolling pages for the Bionic Immitator TUI."""
from __future__ import annotations

from dataclasses import dataclass
from rich.console import Console
from rich.text import Text
from .bionic_config import BionicSettings, OPTION_SPECS, parse_sensor_relay_map
from .bionic_events import EventJournal
from .bionic_model import AlarmState, BionicModel
from .bionic_ponics import (
    PONICS_DEMO_LABEL, PONICS_OPTION_NAMES, PONICS_REGISTER_COUNT, PONICS_REGISTERS,
    PONICS_STATE_LABELS, PONICS_TANK_LABEL,
)
from .bionic_sensor_bridge import SensorRelayState

VIEW_NAMES = ("status", "devices", "ports", "settings", "help", "log", "rs485", "tanks", "pumps", "pressure", "irrigation", "light", "sensors", "ponics", "ponics-settings", "ponics-registers", "water", "drives", "drive-hp1", "drive-hp2")
VIEW_TITLES = {"status":"СТАТУС","devices":"УСТРОЙСТВА","ports":"ПОРТЫ","settings":"НАСТРОЙКИ","help":"СПРАВКА","log":"ЖУРНАЛ","rs485":"RS485","tanks":"БАКИ","pumps":"НАСОСЫ","pressure":"ДАВЛЕНИЕ","irrigation":"ПОЛИВ","light":"ОСВЕЩЕНИЕ","sensors":"ДАТЧИКИ УРОВНЯ","water":"СОСТАВ ВОДЫ","drives":"ЧАСТОТНИКИ","drive-hp1":"ЧАСТОТНИК HP1","drive-hp2":"ЧАСТОТНИК HP2"}
TANK_NAMES = {"bo": "Осмос", "bp": "Бульон", "bso1": "Дренаж 1", "bso2": "Дренаж 2"}
PUMP_NAMES = {"bo-to-bp": "Осмос → Бульон", "bso1-to-bp": "Дренаж 1 → Бульон", "bso2-to-bp": "Дренаж 2 → Бульон"}
OUTPUT_NAMES = {1:"Насос подпора",2:"Перекачка: осмос → бульон",17:"Возврат: дренаж 1 → бульон",18:"Возврат: дренаж 2 → бульон",19:"Выбор HP1",20:"Выбор HP2",21:"Клапан источника: Осмос",22:"Клапан наполнения осмоса",23:"Клапан источника: Бульон",31:"RUN частотника HP2",32:"RUN частотника HP1"}
HELP_GROUPS = (
    ("УПРАВЛЕНИЕ СИМУЛЯЦИЕЙ", "\n".join((
        "sim start            Запустить расчёт физики",
        "sim pause            Приостановить расчёт физики",
        "sim resume           Продолжить расчёт",
        "sim speed 1          Нормальная скорость",
        "sim speed 5          Пятикратная скорость",
        "sim reset --confirm  Сбросить виртуальное состояние",
        "sim pause не закрывает RS485 и не отправляет плате команду остановки.",
    ))),
    ("ОБЩИЕ", "status — состояние; devices — устройства; ports — порты; help — справка; exit/quit — выход"),
    ("НАВИГАЦИЯ", "view status|devices|ports|settings|help|log|rs485|tanks|pumps|pressure|irrigation|light|sensors|water|ponics|drives"),
    ("PONICPILOT", "view ponics; view ponics settings; view ponics registers; ponics dose <a|b|c|ph_plus|ph_minus> <мл>"),
    ("ЧАСТОТНИКИ", "view drives; view drive hp1; view drive hp2"),
    ("БАКИ", "tank list; tank <bo|bp|bso1|bso2> level <л|N%>; capacity <л>; tank bo fill-rate <л/мин>"),
    ("НАСОСЫ", "pump list; pump <bo-to-bp|bso1-to-bp|bso2-to-bp> flow <л/мин>; irrigation shelf <1|2> flow-per-tier <л/мин>"),
    ("ДАТЧИКИ", "sensor list; sensor <id> threshold <л>; force on|off; auto"),
    ("ДАВЛЕНИЕ", "pressure target <бар>; range <мин> <макс>; rise-time <с>; fall-time <с>; pipe status|repair"),
    ("АВАРИИ", "fault list; fault leak on|off|rate; fault blockage on|off|severity; alarm list; alarm reset all"),
    ("ЖУРНАЛ", "log last <N>; log filter alarms|rs485|tanks|pumps|all; log export <файл.csv>"),
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
    "fill_flow_lpm":("Осмос: расход наполнения","л/мин"), "bo_to_bp_flow_lpm":("Насос Осмос → Бульон: расход","л/мин"),
    "bso1_to_bp_flow_lpm":("Насос Дренаж 1 → Бульон: расход","л/мин"), "bso2_to_bp_flow_lpm":("Насос Дренаж 2 → Бульон: расход","л/мин"),
    "rack1_tier_flow_lpm":("Стеллаж 1: расход яруса","л/мин"), "rack2_tier_flow_lpm":("Стеллаж 2: расход яруса","л/мин"),
    "return_fraction":("Доля возврата в дренаж","доля"), "return_delay_s":("Задержка возврата в дренаж","с"),
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
    "hp1_ramp_up_s":("HP1: время разгона","с"), "hp1_ramp_down_s":("HP1: время торможения","с"),
    "hp1_pb01":("HP1 Pb01: источник частоты","RAW"), "hp1_pb02":("HP1 Pb02: источник RUN","RAW"),
    "hp1_ph00":("HP1 PH00: связь","RAW"), "hp1_ph01":("HP1 PH01: связь","RAW"),
    "hp2_ramp_up_s":("HP2: время разгона","с"), "hp2_ramp_down_s":("HP2: время торможения","с"),
    "hp2_pb01":("HP2 Pb01: источник частоты","RAW"), "hp2_pb02":("HP2 Pb02: источник RUN","RAW"),
    "hp2_ph00":("HP2 PH00: связь","RAW"), "hp2_ph01":("HP2 PH01: связь","RAW"),
    "simulation_speed":("Скорость симуляции","×"),
}

@dataclass(frozen=True)
class ScreenPage:
    title: str
    lines: list[str]
    row_keys: list[str | None]
    simulation_status: str = ""

def ellipsize(value: object, width: int) -> str:
    text = str(value).replace("\n", " ")
    if width <= 0: return ""
    if len(text) <= width: return text
    return "." * width if width <= 3 else text[:width-3] + "..."

def _row(columns: list[tuple[object,int]], width: int) -> str:
    return ellipsize(" | ".join(ellipsize(v,w).ljust(w) for v,w in columns).rstrip(), width)

def _status(model: BionicModel, journal: EventJournal, width: int) -> list[str]:
    tanks=["БАКИ"]+[f"{t.id:<4} | {TANK_NAMES[t.id]:<9} | {t.volume_l:7.1f}/{t.capacity_l:7.1f} л | {t.percent:5.1f}%" for t in model.tanks.values()]
    pumps=["НАСОСЫ"]+[f"{p.id} | {PUMP_NAMES[p.id]} | {'RUN' if model.relay(p.relay) else 'STOP'} | {p.actual_flow_lpm:5.1f} л/мин" for p in model.pumps.values()]
    process=["ДАВЛЕНИЕ / ПОЛИВ",f"LOW Датчик низкого: {model.low_pressure_bar:.2f} бар | HIGH Датчик высокого: {model.high_pressure_bar:.2f} бар",f"Труба: {'РАЗРУШЕНА' if model.pipe_ruptured else 'исправна'} | Операция: {model.operation}","Ярусы: "+(", ".join(t.id for t in model.tiers.values() if model.relay(t.relay)) or "нет"),"ДАТЧИКИ: "+" ".join(f"{s.id}({TANK_NAMES[s.tank_id]})={'ON' if s.value else 'OFF'}" for s in model.sensors.values())]
    alarms=[a for a in model.alarms.values() if a.state != AlarmState.CLEARED]
    process.append("АВАРИИ: "+(", ".join(f"{a.code}/{a.subject}" for a in alarms) or "нет"))
    if width>=90:
        split=(width-3)//2; left=tanks+[""]+pumps; right=process; count=max(len(left),len(right)); left += [""]*(count-len(left)); right += [""]*(count-len(right)); lines=[ellipsize(a,split).ljust(split)+" │ "+ellipsize(b,split) for a,b in zip(left,right)]
    else: lines=tanks+[""]+pumps+[""]+process
    recent=journal.events[-3:]; lines += ["","ПОСЛЕДНИЕ СОБЫТИЯ (3)"]+[f"{e.at[11:19]} {e.kind} {e.subject}: {e.message}" for e in recent]+[""]*(3-len(recent))
    return [ellipsize(x,width) for x in lines]

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

def setting_rows(settings:BionicSettings,draft:BionicSettings,saved:BionicSettings,width:int)->tuple[list[str],list[str|None]]:
    sw=3; tw=max(12,min(34,width*30//100)); vw=max(8,min(20,width*18//100)); lw=max(8,width-tw-sw-vw-9); lines=[ellipsize("A — применено, S — сохранено",width),"",_row([("Техническое имя",tw),("Русское название",lw),("Значение",vw),("A/S",sw)],width)]; keys: list[str | None]=[None,None,None]
    for name,(section,_kind) in OPTION_SPECS.items():
        label,unit=SETTING_LABELS.get(name,(name.replace("_"," "),"")); value=f"{getattr(draft,name)} {unit}".rstrip(); state=("A" if getattr(draft,name)==getattr(settings,name) else "-")+"/"+("S" if getattr(draft,name)==getattr(saved,name) else "-"); lines.append(_row([(_technical(section,name),tw),(label,lw),(value,vw),(state,sw)],width)); keys.append(name)
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
        lines.append(_row([("CH",4),("Датчик",9),("Название",max(10,width-50)),("Р/С/Т/П",15),("Режим",8)],width))
    else:
        lines.append(_row([("Канал",6),("Датчик",10),("Русское название",20),("Расчёт",7),("Сигнал",7),("Треб.",7),("Подтв.",10),("Режим",14)],width))
    keys:list[str|None]=[None]*len(lines)
    for sensor_id,channel in sorted(mapping.items(),key=lambda item:item[1]):
        sensor=model.sensors[sensor_id]
        mode="AUTO" if sensor.forced is None else ("FORCE ON" if sensor.forced else "FORCE OFF")
        required=_relay_bit(desired,channel); acknowledged=_relay_bit(confirmed,channel)
        if compact:
            unknown="-" if not settings.hardware_mode else "?"
            states=f"{int(sensor.automatic)}/{int(sensor.value)}/{int(bool(required))}/{(unknown if acknowledged is None else int(acknowledged))}"
            lines.append(_row([(f"CH{channel}",4),(sensor_id,9),(_sensor_name(sensor_id),max(10,width-50)),(states,15),(mode.replace('FORCE ','F-'),8)],width))
        else:
            offline="ОТКЛ" if not settings.hardware_mode else "НЕТ СВЯЗИ"
            lines.append(_row([(f"CH{channel}",6),(sensor_id,10),(_sensor_name(sensor_id),20),(_on_off(sensor.automatic),7),(_on_off(sensor.value),7),(_on_off(required),7),(_on_off(acknowledged,offline=offline),10),(mode,14)],width))
        keys.append(f"sensor:{sensor_id}")
    lines += ["",ellipsize("Расчёт/Р — автоматика; Сигнал/С — с FORCE; Треб./Т — команда; Подтв./П — FC01.",width)]
    keys += [None,None]
    return lines,keys

def _sensor_setting_rows(model:BionicModel,settings:BionicSettings,width:int)->tuple[list[str],list[str|None]]:
    mapping=parse_sensor_relay_map(settings.sensor_relay_map)
    lines=[_row([("Датчик",10),("Бак / тип",22),("Порог",10),("Расчёт",8),("Канал",7),("Полярн.",11),("Контакт",8),("Режим",14)],width)]
    keys:list[str|None]=[None]
    for sensor_id,channel in sorted(mapping.items(),key=lambda item:item[1]):
        sensor=model.sensors[sensor_id]
        mode="AUTO" if sensor.forced is None else ("FORCE ON" if sensor.forced else "FORCE OFF")
        lines.append(_row([(sensor_id,10),(_sensor_name(sensor_id),22),(f"{sensor.threshold_l:g} л",10),(_on_off(sensor.automatic),8),(f"CH{channel}",7),("LOW" if settings.sensor_relay_active_low else "HIGH",11),(settings.sensor_relay_contact,8),(mode,14)],width))
        keys.append(f"sensor:{sensor_id}")
    return lines,keys

def _settings(model:BionicModel,settings:BionicSettings,draft:BionicSettings,saved:BionicSettings,state:SensorRelayState|None,width:int)->tuple[list[str],list[str|None]]:
    sensor_lines,sensor_keys=_sensor_setting_rows(model,draft,width)
    generic_lines,generic_keys=setting_rows(settings,draft,saved,width)
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
    lines += [f"Входящая вода осмоса: EC {model.osmosis_profile['ec']:.2f}, pH {model.osmosis_profile['ph']:.2f}, {model.osmosis_profile['temperature']:.1f} °C",f"Потери полива: {model.total_irrigation_loss_l:.2f} л | протечки: {model.total_leak_l:.2f} л",f"PonicPilot дозировал в БП: {sum(model.ponics.dosing_totals.values()):.1f} мл"]
    return [ellipsize(line,width) for line in lines]

def _drives(model:BionicModel,settings:BionicSettings,width:int)->list[str]:
    lines=["Привод | ID | Команда Modbus | RUN-клемма | Выбор | Факт | Задание | Частота | Моточасы | Ошибка"]
    for drive_id,drive in model.drives.items():
        lines.append(_row([(drive_id.upper(),6),(drive.address,3),("RUN" if drive.run_register else "STOP",14),("ON" if model.relay(drive.run_relay) else "OFF",10),("ON" if model.relay(drive.selector_relay) else "OFF",6),("RUN" if drive.actual_hz>0.1 else "STOP",5),(f"{drive.setpoint_hz:.1f} Гц",9),(f"{drive.actual_hz:.1f} Гц",9),(f"{drive.motor_hours:.2f} ч",10),(drive.fault,6)],width))
    lines += ["",f"do-19 выбор HP1: {_on_off(model.relay(19))} | do-20 выбор HP2: {_on_off(model.relay(20))}",f"do-32 RUN HP1: {_on_off(model.relay(32))} | do-31 RUN HP2: {_on_off(model.relay(31))}"]
    return [ellipsize(line,width) for line in lines]

def _drive(model:BionicModel,drive_id:str,width:int)->list[str]:
    drive=model.drives[drive_id]
    telemetry={1:round(drive.setpoint_hz*10),2:round(drive.actual_hz*10),3:round(drive.actual_hz*2),4:round(drive.motor_hours*10),27:drive.fault,28:int(drive.actual_hz>0.1)}
    configuration=getattr(drive,"configuration",{101:5,102:2,700:1,701:3,702:drive.address})
    names={1:("PA01","Заданная частота","0.1 Гц"),2:("PA02","Фактическая частота","0.1 Гц"),3:("PA03","Телеметрия, связанная с частотой","RAW"),4:("PA04","Моточасы","0.1 ч"),27:("PA27","Код ошибки","RAW"),28:("PA28","Состояние работы","0/1"),101:("Pb01","Источник задания частоты","R"),102:("Pb02","Источник RUN/STOP","R"),700:("PH00","Параметр связи 0","R"),701:("PH01","Параметр связи 1","R"),702:("PH02","Modbus ID","R")}
    lines=["ТЕКУЩАЯ РАБОТА",f"Команда Modbus: {'RUN' if drive.run_register else 'STOP'} | RUN-клемма do-{drive.run_relay}: {_on_off(model.relay(drive.run_relay))} | выбор do-{drive.selector_relay}: {_on_off(model.relay(drive.selector_relay))}",f"Задание {drive.setpoint_hz:.1f} Гц | факт {drive.actual_hz:.1f} Гц | разгон/торможение {drive.ramp_up_s:g}/{drive.ramp_down_s:g} с",f"Моточасы {drive.motor_hours:.2f} ч | ошибка {drive.fault} | связь {'есть' if drive.online else 'нет'}","","РЕГИСТРЫ","Имя | Адрес | Название                          | RAW   | Масштаб / доступ"]
    for address,value in {**telemetry,**configuration}.items():
        code,label,detail=names[address]
        lines.append(_row([(code,6),(address,6),(label,33),(value,6),(detail,18)],width))
    lines += ["","Конфигурационные регистры читаются. Запись не реализована: firmware использует их только для проверки конфигурации."]
    return [ellipsize(line,width) for line in lines]

def render_page(name:str,model:BionicModel,journal:EventJournal,settings:BionicSettings,draft:BionicSettings,saved:BionicSettings,*,width:int,log_filter:str="all",help_query:str="",relay_state:SensorRelayState|None=None)->ScreenPage:
    name="status" if name=="main" else name; keys:list[str|None]=[]
    if name=="status": lines=_status(model,journal,width)
    elif name=="devices": lines=_devices(settings,width)
    elif name=="ports": lines=_ports(settings,width)
    elif name=="settings": lines,keys=_settings(model,settings,draft,saved,relay_state,width)
    elif name=="help": lines=_help(width,help_query)
    elif name=="log": lines=_log(journal,log_filter,width)
    elif name=="tanks": lines=[f"{t.id} | {TANK_NAMES[t.id]} | {t.volume_l:.1f}/{t.capacity_l:.1f} л | перелив {t.overflow_l:.1f} л" for t in model.tanks.values()]
    elif name=="pumps": lines=[f"{p.id} | {PUMP_NAMES[p.id]} | {'RUN' if model.relay(p.relay) else 'STOP'} | {p.actual_flow_lpm:.1f} л/мин" for p in model.pumps.values()]
    elif name=="pressure": lines=_pressure(model,width)
    elif name=="irrigation": lines=[f"{t.id} | Стеллаж {t.rack}, ярус | do-{t.relay} | {t.actual_flow_lpm:.1f} л/мин" for t in model.tiers.values()]
    elif name=="light": lines=[f"{z.id} | Стеллаж {z.rack}, ярус {z.tier} | do-{z.power_relay} | {'ON' if model.light_state(z.id)[0] else 'OFF'}" for z in model.lights.values()]
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
        simulation_status(model),
    )

def visible_lines(page:ScreenPage,*,height:int,scroll:int=0)->list[str]:
    height=max(1,height); start=min(max(scroll,0),max(0,len(page.lines)-height)); lines=page.lines[start:start+height]; return lines+[""]*(height-len(lines))

def print_view(console:Console,name:str,model:BionicModel,journal:EventJournal,settings:BionicSettings,draft:BionicSettings,saved:BionicSettings|None=None,relay_state:SensorRelayState|None=None)->None:
    page=render_page(name,model,journal,settings,draft,saved or settings,width=console.width,relay_state=relay_state); console.print(Text("BIONIC IMMITATOR — "+page.simulation_status+" | "+page.title+"\n"+"\n".join(page.lines)))
