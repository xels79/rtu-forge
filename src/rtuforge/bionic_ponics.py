"""Ponics Pilot 32 register map and demo solution chemistry.

The Modbus layout follows the manufacturer's 42-register holding-register
table (manual addresses 1..42, PDU addresses 0..41).  Chemistry is deliberately
demonstrational and is always attached to the shared ``bp`` tank.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from time import time
from typing import TYPE_CHECKING, Callable

if TYPE_CHECKING:
    from .bionic_model import BionicModel, SolutionParcel, Tank


PONICS_TANK_ID = "bp"
PONICS_TANK_LABEL = "Бак: БП (Бульон)"
PONICS_DEMO_LABEL = "ДЕМО: показания рассчитаны имитатором"
PONICS_REGISTER_COUNT = 42
PONICS_WRITABLE_SETTINGS = frozenset(
    {8, 9, 23, 24, 26, 27, 28, 29, 30, 31, 32, 33, 34, 35, 36, 37, 38, 39}
)
PONICS_DOSING_REGISTERS = {14: "a", 15: "b", 16: "c", 17: "ph_plus", 18: "ph_minus"}
PONICS_OPTION_NAMES = {
    8: "ponics_irrigation_on_s", 9: "ponics_irrigation_pause_s", 23: "ponics_mode",
    24: "ponics_ph_enabled", 26: "ponics_ph_dosing_pause_s", 27: "ponics_ph_low",
    28: "ponics_ph_high", 29: "ponics_ec_enabled", 30: "ponics_ec_protection_enabled",
    31: "ponics_ec_dosing_pause_s", 32: "ponics_ec_program",
    33: "ponics_ec_target_ms_cm", 34: "ponics_fertilizer_a_share",
    35: "ponics_fertilizer_b_share", 36: "ponics_fertilizer_c_share",
    37: "ponics_thermostat_enabled", 38: "ponics_temperature_low_c",
    39: "ponics_temperature_high_c",
}


@dataclass(frozen=True)
class PonicsRegister:
    index: int
    name: str
    access: str
    scale: float = 1.0
    unit: str = ""

    @property
    def pdu_address(self) -> int:
        return self.index

    @property
    def manual_address(self) -> int:
        return self.index + 1


_REGISTER_ROWS = (
    ("UNIX-время, слово 1 (старшее)", "R", 1, ""),
    ("UNIX-время, слово 2", "R", 1, ""),
    ("UNIX-время, слово 3", "R", 1, ""),
    ("UNIX-время, слово 4", "R", 1, ""),
    ("pH раствора", "R", 0.01, "pH"),
    ("EC раствора", "R", 0.01, "мСм/см"),
    ("Температура раствора", "R", 0.1, "°C"),
    ("Состояние прибора", "R", 1, ""),
    ("Время полива", "RW", 1, "с"),
    ("Пауза между поливами", "RW", 1, "с"),
    ("Состояние дискретных входов", "R", 1, "битовая маска"),
    ("Зарезервировано", "R", 1, ""),
    ("Состояние дискретных выходов", "R", 1, "битовая маска"),
    ("Зарезервировано", "R", 1, ""),
    ("Счётчик удобрения A", "RW-доза", 0.1, "мл"),
    ("Счётчик удобрения B", "RW-доза", 0.1, "мл"),
    ("Счётчик удобрения C", "RW-доза", 0.1, "мл"),
    ("Счётчик компонента pH+", "RW-доза", 0.1, "мл"),
    ("Счётчик компонента pH−", "RW-доза", 0.1, "мл"),
    ("Флаги аварий, слово 1", "R", 1, "битовая маска"),
    ("Флаги аварий, слово 2", "R", 1, "битовая маска"),
    ("Зарезервировано", "R", 1, ""),
    ("Зарезервировано", "R", 1, ""),
    ("Текущий режим / сценарий", "RW", 1, ""),
    ("Состояние регулятора pH", "RW", 1, ""),
    ("Зарезервировано", "R", 1, ""),
    ("Пауза дозирования pH", "RW", 1, "с"),
    ("Нижняя точка pH", "RW", 0.1, "pH"),
    ("Верхняя точка pH", "RW", 0.1, "pH"),
    ("Состояние регулятора EC", "RW", 1, ""),
    ("Защита регулятора EC", "RW", 1, ""),
    ("Пауза дозирования EC", "RW", 1, "с"),
    ("Программа EC", "RW", 1, ""),
    ("Целевая EC", "RW", 0.01, "мСм/см"),
    ("Доля удобрения A", "RW", 1, ""),
    ("Доля удобрения B", "RW", 1, ""),
    ("Доля удобрения C", "RW", 1, ""),
    ("Состояние термостата", "RW", 1, ""),
    ("Нижняя температура", "RW", 1, "°C"),
    ("Верхняя температура", "RW", 1, "°C"),
    ("Серийный номер, слово 1", "R", 1, ""),
    ("Серийный номер, слово 2", "R", 1, ""),
)
PONICS_REGISTERS = tuple(
    PonicsRegister(index, name, access, scale, unit)
    for index, (name, access, scale, unit) in enumerate(_REGISTER_ROWS)
)

PONICS_STATE_LABELS = {
    0: "выключен", 10: "авария", 20: "наполнение бака",
    21: "естественное регулирование EC", 22: "первичное регулирование pH",
    23: "наполнение каналов", 24: "пауза полива", 25: "полив",
    26: "регулирование EC/pH без полива", 27: "слив излишка",
    28: "разбавление", 29: "полив отключён", 30: "слив бака",
    31: "бак слит", 32: "авария слива бака", 40: "начало слива каналов",
    41: "слив излишка при сливе каналов", 42: "слив канала при пустом баке",
    43: "слив канала в бак", 44: "слив излишка в бак",
    45: "слив канала", 46: "слив каналов завершён", 47: "авария слива каналов",
    50: "начало системного слива", 51: "системный слив излишка",
    52: "системный слив канала при пустом баке", 53: "системный слив канала",
    54: "системный слив излишка в бак", 55: "системный слив канала в пустой бак",
    56: "системный слив завершён", 57: "авария системного слива",
}
PONICS_MODE_LABELS = {0: "выключен", 2: "работает", 3: "слив бака", 4: "слив каналов", 5: "системный слив"}


def default_ponics_settings() -> dict[int, int]:
    return {
        8: 60, 9: 300, 23: 0, 24: 0, 26: 60, 27: 55, 28: 65,
        29: 0, 30: 0, 31: 60, 32: 0, 33: 200, 34: 33, 35: 33,
        36: 34, 37: 0, 38: 18, 39: 24,
    }


class PonicsPilot:
    """Virtual register image whose measurements and dosing are hard-bound to BP."""

    def __init__(self, model: BionicModel, event: Callable[[str, str, str], None]) -> None:
        self.model = model
        self.event = event
        self.settings = default_ponics_settings()
        self.dosing_totals = {name: 0.0 for name in PONICS_DOSING_REGISTERS.values()}
        self.serial_number = 500_001
        self.discrete_inputs = 0
        self.discrete_outputs = 0
        self.sensor_faults = {"ph": False, "ec": False, "temperature": False}
        self.doser_faults = {name: False for name in self.dosing_totals}
        self.respond = True
        self.requests = 0
        self.responses = 0
        self.crc_errors = 0
        self.function_errors = 0
        self.address_errors = 0
        self.last_success_at: str | None = None
        self.last_read_range: tuple[int, int] | None = None
        self.last_written_register: int | None = None
        self.register_sources = ["модель" for _ in range(PONICS_REGISTER_COUNT)]
        self.register_changed_at = ["при запуске" for _ in range(PONICS_REGISTER_COUNT)]
        self.setting_changed: Callable[[int, int], None] = lambda _index, _value: None

    @property
    def tank(self) -> Tank:
        return self.model.tanks[PONICS_TANK_ID]

    @property
    def state(self) -> int:
        if any(self.sensor_faults.values()):
            return 10
        mode = self.settings[23]
        if mode == 0:
            return 0
        if mode == 3:
            return 30
        if mode == 4:
            return 40
        if mode == 5:
            return 50
        if any(tier.actual_flow_lpm > 0 for tier in self.model.tiers.values()):
            return 25
        return 29

    def configure(self, values: dict[int, int]) -> None:
        for index, value in values.items():
            self._validate(index, value)
        self.settings.update(values)

    def _unix_words(self) -> list[int]:
        value = int(time() * 1000)
        return [(value >> shift) & 0xFFFF for shift in (48, 32, 16, 0)]

    def registers(self) -> list[int]:
        result = [0] * PONICS_REGISTER_COUNT
        result[:4] = self._unix_words()
        result[4] = 0 if self.sensor_faults["ph"] else round(self.tank.ph * 100)
        result[5] = 0 if self.sensor_faults["ec"] else round(self.tank.ec_ms_cm * 100)
        result[6] = 0 if self.sensor_faults["temperature"] else round(self.tank.temperature_c * 10)
        result[7] = self.state
        result[8] = self.settings[8]
        result[9] = self.settings[9]
        result[10] = self.discrete_inputs & 0xFFFF
        result[12] = self.discrete_outputs & 0xFFFF
        for index, name in PONICS_DOSING_REGISTERS.items():
            result[index] = min(0xFFFF, round(self.dosing_totals[name] * 10))
        for index, value in self.settings.items():
            result[index] = value
        result[40] = (self.serial_number >> 16) & 0xFFFF
        result[41] = self.serial_number & 0xFFFF
        return result

    def engineering_value(self, index: int, raw: int | None = None) -> str:
        value = self.registers()[index] if raw is None else raw
        register = PONICS_REGISTERS[index]
        if index == 7:
            return PONICS_STATE_LABELS.get(value, f"неизвестно ({value})")
        if index == 23:
            return PONICS_MODE_LABELS.get(value, f"неизвестно ({value})")
        if index in {10, 12, 19, 20}:
            return f"0x{value:04X}"
        if 0 <= index <= 3:
            return "часть UNIX-времени"
        scaled = value * register.scale
        rendered = f"{scaled:.2f}" if register.scale == 0.01 else f"{scaled:.1f}" if register.scale == 0.1 else str(value)
        return f"{rendered} {register.unit}".rstrip()

    def note_read(self, start: int, count: int) -> None:
        self.requests += 1
        self.responses += 1
        self.last_read_range = (start, start + count - 1)
        self.last_success_at = datetime.now(timezone.utc).isoformat()

    def note_error(self, *, address: bool = False) -> None:
        self.requests += 1
        if address:
            self.address_errors += 1
        else:
            self.function_errors += 1

    def _validate(self, index: int, value: int) -> None:
        if not 0 <= value <= 0xFFFF:
            raise ValueError("RAW должен быть в диапазоне 0..65535")
        ranges = {
            8: (0, 0xFFFF), 9: (0, 0xFFFF), 23: (0, 5), 24: (0, 1),
            26: (0, 0xFFFF), 27: (0, 140), 28: (0, 140), 29: (0, 1),
            30: (0, 1), 31: (0, 0xFFFF), 32: (0, 4), 33: (0, 2000),
            34: (0, 99), 35: (0, 99), 36: (0, 99), 37: (0, 1),
            38: (0, 100), 39: (0, 100),
        }
        if index in ranges and not ranges[index][0] <= value <= ranges[index][1]:
            raise ValueError(f"Недопустимое значение регистра PDU {index}")
        if index == 23 and value not in {0, 2, 3, 4, 5}:
            raise ValueError("Допустимые режимы PonicPilot: 0, 2, 3, 4, 5")
        if index in {34, 35, 36}:
            shares = {key: self.settings.get(key, 0) for key in (34, 35, 36)}
            shares[index] = value
            if sum(shares.values()) <= 0:
                raise ValueError("Сумма долей удобрений A/B/C должна быть больше нуля")

    def write(self, index: int, value: int, *, source: str = "Modbus FC06") -> None:
        if index in PONICS_DOSING_REGISTERS:
            self._validate(index, value)
            reagent = PONICS_DOSING_REGISTERS[index]
            self.dosing_totals[reagent] = 0.0
            self.dose(reagent, value / 10.0, source=source)
        elif index in PONICS_WRITABLE_SETTINGS:
            self._validate(index, value)
            self.settings[index] = value
            self.setting_changed(index, value)
        else:
            raise PermissionError(f"Регистр PDU {index} доступен только для чтения")
        self.last_success_at = datetime.now(timezone.utc).isoformat()
        self.last_written_register = index
        self.register_sources[index] = source
        self.register_changed_at[index] = self.last_success_at
        self.event("PONICS", f"PDU-{index}", f"записано RAW {value}; {PONICS_TANK_LABEL}")

    def dose(self, reagent: str, millilitres: float, *, source: str = "оператор") -> None:
        if reagent not in self.dosing_totals:
            raise ValueError("Реагент: a, b, c, ph_plus или ph_minus")
        if millilitres < 0:
            raise ValueError("Доза не может быть отрицательной")
        if self.doser_faults[reagent]:
            raise RuntimeError(f"Дозатор {reagent} неисправен")
        self.model.apply_ponics_dose(reagent, millilitres)
        self.dosing_totals[reagent] += millilitres
        self.event("PONICS", reagent, f"доза {millilitres:g} мл только в БП; источник: {source}")

