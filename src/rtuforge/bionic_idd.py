"""Verified INNOVERT IDD mini PLUS parameter map used by the simulator.

RAW addresses and scales follow the manufacturer's IDD mini PLUS manual and
its Modbus RTU application note.  Only parameters whose ranges are documented
and which affect the simulated installation are writable here.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class IddParameter:
    address: int
    code: str
    label: str
    minimum: int
    maximum: int
    scale: float = 1.0


IDD_PARAMETERS: dict[int, IddParameter] = {
    100: IddParameter(100, "PB.00", "Локальное задание частоты", 0, 9999, 0.1),
    101: IddParameter(101, "PB.01", "Источник задания частоты", 0, 8),
    102: IddParameter(102, "PB.02", "Источник RUN/STOP", 0, 2),
    105: IddParameter(105, "PB.05", "Максимальная частота", 1, 9999, 0.1),
    106: IddParameter(106, "PB.06", "Минимальная частота", 0, 9999, 0.1),
    107: IddParameter(107, "PB.07", "Время разгона", 1, 9999, 0.1),
    108: IddParameter(108, "PB.08", "Время торможения", 1, 9999, 0.1),
    210: IddParameter(210, "PC.10", "Номинальный ток двигателя", 0, 9999, 0.1),
    212: IddParameter(212, "PC.12", "Номинальная скорость двигателя", 0, 6000),
    215: IddParameter(215, "PC.15", "Номинальная частота двигателя", 0, 4000, 0.1),
    700: IddParameter(700, "PH.00", "Скорость последовательного порта", 0, 1),
    701: IddParameter(701, "PH.01", "Формат последовательного порта", 0, 5),
    # The virtual RTU bus intentionally exposes standard unicast IDs only.
    702: IddParameter(702, "PH.02", "Modbus ID", 1, 247),
    816: IddParameter(816, "Pi.16", "Защита двигателя от перегрузки", 0, 1),
}


IDD_TELEMETRY: dict[int, tuple[str, str, str]] = {
    1: ("PA.01", "Заданная частота", "0.1 Гц, R"),
    2: ("PA.02", "Фактическая частота", "0.1 Гц, R"),
    3: ("PA.03", "Выходной ток (демо)", "0.1 А, R"),
    4: ("PA.04", "Скорость вращения", "об/мин, R"),
    27: ("PA.27", "Код ошибки", "RAW, R"),
    28: ("PA.28", "Подтверждённое состояние", "0/1, R"),
}


IDD_BAUDRATES = {0: 4800, 1: 9600}
IDD_FORMATS = {
    0: ("ASCII", "N", 1.0),
    1: ("ASCII", "E", 1.0),
    2: ("ASCII", "O", 1.0),
    3: ("RTU", "N", 1.0),
    4: ("RTU", "E", 1.0),
    5: ("RTU", "O", 1.0),
}

IDD_FREQUENCY_SOURCES = {
    0: "цифровое задание PB.00",
    1: "аналоговый вход AVI",
    2: "потенциометр внешней клавиатуры",
    3: "потенциометр панели",
    4: "контакты UP/DOWN",
    5: "RS485",
    6: "предустановленные скорости",
    7: "простой ПЛК",
    8: "ПИД",
}

IDD_RUN_SOURCES = {
    0: "панель управления",
    1: "управляющие клеммы",
    2: "RS485",
}

IDD_OVERLOAD_PROTECTION = {
    0: "отключена",
    1: "включена",
}

IDD_FAULTS = {
    0: "нет ошибки",
    10: "oL2 — перегрузка при работе",
}

# IDD mini PLUS manual, chapter 8-5: oL2 (decimal code 10) is an overload
# while the converter is running.  PA.27 exposes the current error code.
IDD_FAULT_OVERLOAD_RUNNING = 10


def decode_idd_value(address: int, value: int) -> str:
    """Return the documented engineering or enumerated meaning of a RAW value."""
    if address in {1, 2, 100, 105, 106, 215}:
        return f"{value / 10:.1f} Гц"
    if address == 3 or address == 210:
        return f"{value / 10:.1f} А"
    if address in {107, 108}:
        return f"{value / 10:.1f} с"
    if address in {4, 212}:
        return f"{value} об/мин"
    if address == 27:
        return IDD_FAULTS.get(value, f"код ошибки {value}")
    if address == 28:
        return {0: "STOP", 1: "RUN"}.get(value, f"состояние {value}")
    if address == 101:
        return IDD_FREQUENCY_SOURCES.get(value, f"неизвестный источник {value}")
    if address == 102:
        return IDD_RUN_SOURCES.get(value, f"неизвестный источник {value}")
    if address == 700:
        baudrate = IDD_BAUDRATES.get(value)
        return f"{baudrate} бит/с" if baudrate is not None else f"неизвестная скорость {value}"
    if address == 701:
        serial_format = IDD_FORMATS.get(value)
        if serial_format is None:
            return f"неизвестный формат {value}"
        protocol, parity, stopbits = serial_format
        return f"{protocol} 8{parity}{stopbits:g}"
    if address == 702:
        return f"Modbus ID {value}"
    if address == 816:
        return IDD_OVERLOAD_PROTECTION.get(value, f"неизвестное состояние {value}")
    return str(value)


def validate_idd_parameter(address: int, value: int, configuration: dict[int, int]) -> None:
    """Validate one documented parameter including cross-register limits."""
    spec = IDD_PARAMETERS[address]
    if not spec.minimum <= value <= spec.maximum:
        raise ValueError(f"{spec.code}: допустимо {spec.minimum}..{spec.maximum}")
    if address == 100 and value > configuration.get(105, 9999):
        raise ValueError("PB.00 не может превышать PB.05")
    if address == 105 and value < configuration.get(106, 0):
        raise ValueError("PB.05 не может быть меньше PB.06")
    if address == 106 and value > configuration.get(105, 9999):
        raise ValueError("PB.06 не может превышать PB.05")
