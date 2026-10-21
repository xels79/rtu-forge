"""Width-aware, non-scrolling pages for the Bionic Immitator TUI."""
from __future__ import annotations

from dataclasses import dataclass
from rich.console import Console
from rich.text import Text
from .bionic_config import BionicSettings, OPTION_SPECS
from .bionic_events import EventJournal
from .bionic_model import AlarmState, BionicModel

VIEW_NAMES = ("status", "devices", "ports", "settings", "help", "log", "rs485", "tanks", "pumps", "pressure", "irrigation", "light", "sensors")
TANK_NAMES = {"bo": "Осмос", "bp": "Бульон", "bso1": "Дренаж 1", "bso2": "Дренаж 2"}
PUMP_NAMES = {"bo-to-bp": "Осмос → Бульон", "bso1-to-bp": "Дренаж 1 → Бульон", "bso2-to-bp": "Дренаж 2 → Бульон"}
OUTPUT_NAMES = {1:"Насос подпора",2:"Перекачка: осмос → бульон",17:"Возврат: дренаж 1 → бульон",18:"Возврат: дренаж 2 → бульон",19:"Выбор HP1",20:"Выбор HP2",21:"Клапан источника: Осмос",22:"Клапан наполнения осмоса",23:"Клапан источника: Бульон",31:"RUN частотника HP2",32:"RUN частотника HP1"}
HELP_GROUPS = (
    ("ОБЩИЕ", "status — состояние; devices — устройства; ports — порты; help — справка; exit/quit — выход"),
    ("НАВИГАЦИЯ", "view status|devices|ports|settings|help|log|rs485|tanks|pumps|pressure|irrigation|light|sensors"),
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
    "sensor_relay_loss_behavior":("Реле: поведение при потере связи",""), "hardware_mode":("Аппаратный режим USB №2",""),
    "relay_address":("Релейный модуль: Modbus ID",""), "ao1_address":("Аналоговый выход №1: Modbus ID",""),
    "ao2_address":("Аналоговый выход №2: Modbus ID",""), "ao3_address":("Аналоговый выход №3: Modbus ID",""),
    "ai_address":("Аналоговый вход давления: Modbus ID",""), "hp1_address":("Частотник HP1: Modbus ID",""), "hp2_address":("Частотник HP2: Modbus ID",""),
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
    "pressure_max_bar":("Максимальное давление модели","бар"),
    "rupture_threshold_bar":("Порог разрыва трассы","бар"), "leak_rate_lpm":("Интенсивность протечки","л/мин"),
    "rupture_residual_bar":("Остаточное давление после разрыва","бар"), "leak_pressure_factor":("Влияние протечки на давление","доля"),
    "blockage_severity":("Степень засора","%"),
    "simulation_speed":("Скорость симуляции","×"),
}

@dataclass(frozen=True)
class ScreenPage:
    title: str
    lines: list[str]
    row_keys: list[str | None]

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
    rows=[("relay-32ch","Релейный модуль Waveshare 32CH",s.relay_address,"виртуальный"),("ao-1","Аналоговый выход №1",s.ao1_address,"виртуальный"),("ao-2","Аналоговый выход №2",s.ao2_address,"виртуальный"),("ao-3","Аналоговый выход №3",s.ao3_address,"виртуальный"),("ai-pressure","Аналоговый вход давления",s.ai_address,"виртуальный"),("hp1","Частотник высокого давления 1",s.hp1_address,"виртуальный"),("hp2","Частотник высокого давления 2",s.hp2_address,"виртуальный"),("sensor-relay","Физическое реле датчиков уровня",s.sensor_relay_id,"физический/USB №2")]
    if width < 60:
        lines=[_row([("ID",12),("Русское название",max(8,width-15))],width)]+[_row([(a,12),(b,max(8,width-15))],width) for a,b,_,_ in rows]+["","ИСПОЛНИТЕЛЬНЫЕ ВЫХОДЫ"]
        return lines+[ellipsize(f"do-{c:<2} | {n}",width) for c,n in OUTPUT_NAMES.items()]
    nw=max(12,min(18,width//5)); aw=8; tw=17; lw=max(12,width-nw-aw-tw-9); lines=[_row([("ID",nw),("Русское название",lw),("Modbus",aw),("Тип",tw)],width)]+[_row([(a,nw),(b,lw),(c,aw),(d,tw)],width) for a,b,c,d in rows]+["","ИСПОЛНИТЕЛЬНЫЕ ВЫХОДЫ"]
    return lines+[ellipsize(f"do-{c:<2} | {n}",width) for c,n in OUTPUT_NAMES.items()]

def _ports(s:BionicSettings,width:int)->list[str]:
    return [ellipsize(x,width) for x in ("USB №1 | Контроллер Bionic Mini | Modbus RTU slave",f"Порт: {s.controller_port} | {s.controller_baudrate} 8{s.controller_parity}{s.controller_stopbits:g}","Устройства: relay-32ch, ao-1..3, ai-pressure, hp1, hp2","","USB №2 | Физическое реле датчиков | Modbus RTU master",f"Порт: {s.sensor_relay_port} | {s.sensor_relay_baudrate} 8{s.sensor_relay_parity}{s.sensor_relay_stopbits:g}",f"Waveshare {s.sensor_relay_channels}CH | ID {s.sensor_relay_id} | аппаратный режим {'ВКЛ' if s.hardware_mode else 'ВЫКЛ'}")]

def _technical(section:str,name:str)->str:
    return {"bo_capacity_l":"tanks.bo.capacity_l","bp_capacity_l":"tanks.bp.capacity_l","bso1_capacity_l":"tanks.bso1.capacity_l","bso2_capacity_l":"tanks.bso2.capacity_l"}.get(name,f"{section}.{name}")

def setting_rows(settings:BionicSettings,draft:BionicSettings,saved:BionicSettings,width:int)->tuple[list[str],list[str|None]]:
    sw=3; tw=max(12,min(34,width*30//100)); vw=max(8,min(20,width*18//100)); lw=max(8,width-tw-sw-vw-9); lines=[ellipsize("A — применено, S — сохранено",width),"",_row([("Техническое имя",tw),("Русское название",lw),("Значение",vw),("A/S",sw)],width)]; keys: list[str | None]=[None,None,None]
    for name,(section,_kind) in OPTION_SPECS.items():
        label,unit=SETTING_LABELS.get(name,(name.replace("_"," "),"")); value=f"{getattr(draft,name)} {unit}".rstrip(); state=("A" if getattr(draft,name)==getattr(settings,name) else "-")+"/"+("S" if getattr(draft,name)==getattr(saved,name) else "-"); lines.append(_row([(_technical(section,name),tw),(label,lw),(value,vw),(state,sw)],width)); keys.append(name)
    return lines,keys

def _help(width:int,query:str)->list[str]:
    q=query.casefold().strip(); lines=["Поиск: "+(q or "нет")+"  (help search <текст>)",""]
    for title,body in HELP_GROUPS:
        if q and q not in title.casefold() and q not in body.casefold(): continue
        lines += [title,ellipsize(body,width),""]
    return lines

def _log(j:EventJournal,category:str,width:int)->list[str]:
    return [f"Фильтр: {category}","Дата/время                | Тип       | Объект       | Событие"]+[ellipsize(f"{e.at[:19]:<24} | {e.kind:<9} | {e.subject:<12} | {e.message}",width) for e in j.filtered(category)]

def render_page(name:str,model:BionicModel,journal:EventJournal,settings:BionicSettings,draft:BionicSettings,saved:BionicSettings,*,width:int,log_filter:str="all",help_query:str="")->ScreenPage:
    name="status" if name=="main" else name; keys:list[str|None]=[]
    if name=="status": lines=_status(model,journal,width)
    elif name=="devices": lines=_devices(settings,width)
    elif name=="ports": lines=_ports(settings,width)
    elif name=="settings": lines,keys=setting_rows(settings,draft,saved,width)
    elif name=="help": lines=_help(width,help_query)
    elif name=="log": lines=_log(journal,log_filter,width)
    elif name=="tanks": lines=[f"{t.id} | {TANK_NAMES[t.id]} | {t.volume_l:.1f}/{t.capacity_l:.1f} л | перелив {t.overflow_l:.1f} л" for t in model.tanks.values()]
    elif name=="pumps": lines=[f"{p.id} | {PUMP_NAMES[p.id]} | {'RUN' if model.relay(p.relay) else 'STOP'} | {p.actual_flow_lpm:.1f} л/мин" for p in model.pumps.values()]
    elif name=="pressure": lines=[f"LOW | Датчик низкого давления | {model.low_pressure_bar:.2f} бар",f"HIGH | Датчик высокого давления | {model.high_pressure_bar:.2f} бар",f"HP1 | Частотник высокого давления 1 | {model.drives['hp1'].actual_hz:.1f} Гц",f"HP2 | Частотник высокого давления 2 | {model.drives['hp2'].actual_hz:.1f} Гц"]
    elif name=="irrigation": lines=[f"{t.id} | Стеллаж {t.rack}, ярус | do-{t.relay} | {t.actual_flow_lpm:.1f} л/мин" for t in model.tiers.values()]
    elif name=="light": lines=[f"{z.id} | Стеллаж {z.rack}, ярус {z.tier} | do-{z.power_relay} | {'ON' if model.light_state(z.id)[0] else 'OFF'}" for z in model.lights.values()]
    elif name=="sensors": lines=[f"{s.id} | {TANK_NAMES[s.tank_id]} {s.kind.upper()} | {'ON' if s.value else 'OFF'} | {'AUTO' if s.forced is None else 'FORCE'}" for s in model.sensors.values()]
    elif name=="rs485": lines=_ports(settings,width)+["","Адреса USB №1: 1 Relay, 2..4 AO, 6 AI, 7 HP1, 8 HP2"]
    else: lines=[f"Неизвестный экран: {name}"]
    return ScreenPage(name.upper(),[ellipsize(x,width) for x in lines],keys or [None]*len(lines))

def visible_lines(page:ScreenPage,*,height:int,scroll:int=0)->list[str]:
    height=max(1,height); start=min(max(scroll,0),max(0,len(page.lines)-height)); lines=page.lines[start:start+height]; return lines+[""]*(height-len(lines))

def print_view(console:Console,name:str,model:BionicModel,journal:EventJournal,settings:BionicSettings,draft:BionicSettings,saved:BionicSettings|None=None)->None:
    page=render_page(name,model,journal,settings,draft,saved or settings,width=console.width); console.print(Text("BIONIC IMMITATOR — "+page.title+"\n"+"\n".join(page.lines)))
