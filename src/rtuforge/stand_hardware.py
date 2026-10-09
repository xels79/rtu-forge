"""Validated sequential Modbus operations for the irrigation controller."""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from math import ceil

from .irrigation import DRIVE_START, Sample, StopRequested
from .irrigation_config import IrrigationSettings
from .stand_protocol import (build_read_request, build_write_multiple_coils,
                             build_write_single_register, parse_percent,
                             validate_read_response, validate_write_response)
from .stand_sensors import HIGH, LOW, Sensor, decode_pressure


@dataclass(frozen=True)
class PressureReading:
    sensor: Sensor
    raw: int
    mode: int
    current_ma: float | None
    bar: float | None
    error: str = ""


@dataclass(frozen=True)
class FrequencyPlan:
    percent: float
    minimum_raw: int
    maximum_raw: int
    setpoint_raw: int


class StandHardware:
    def __init__(self, transaction: Callable[[bytes], bytes], relay_id: int,
                 settings: IrrigationSettings, *, cancelled: Callable[[], bool] = lambda: False):
        self.transaction = transaction
        self.relay_id = relay_id
        self.settings = settings
        self.cancelled = cancelled

    def registers(self, slave: int, function: int, address: int, count: int) -> list[int]:
        request = build_read_request(slave, function, address, count)
        data = validate_read_response(request, self.transaction(request))
        return [int.from_bytes(data[i:i + 2], "big") for i in range(0, len(data), 2)]

    def coils(self) -> list[bool]:
        request = build_read_request(self.relay_id, 1, 0, 32)
        data = validate_read_response(request, self.transaction(request))
        return [bool(data[i // 8] & (1 << (i % 8))) for i in range(32)]

    def _allow_write(self) -> None:
        if self.cancelled():
            raise StopRequested()

    def relay(self, channel: int, active: bool) -> None:
        if not 1 <= channel <= 32:
            raise ValueError("Реле: допустимы каналы 1..32")
        if active:
            self._allow_write()
        request = build_write_multiple_coils(self.relay_id, channel - 1, [active])
        validate_write_response(request, self.transaction(request))

    def write_register(self, slave: int, register: int, value: int) -> None:
        self._allow_write()
        request = build_write_single_register(slave, register, value)
        validate_write_response(request, self.transaction(request))

    def pressure(self) -> list[PressureReading]:
        modes = self.registers(6, 3, 0x1000, 4)
        raw = self.registers(6, 4, 0, 4)
        readings = []
        for i, sensor in enumerate((LOW, HIGH)):
            try:
                ma, bar = decode_pressure(raw[i], modes[i], sensor)
                readings.append(PressureReading(sensor, raw[i], modes[i], ma, bar))
            except ValueError as exc:
                readings.append(PressureReading(sensor, raw[i], modes[i],
                                                raw[i] / 1000 if modes[i] == 3 else None,
                                                None, str(exc)))
        return readings

    def drive_feedback(self, drive: int) -> tuple[float, bool, bool]:
        cfg = self.settings
        if not cfg.vfd_verified or cfg.run_register < 0 or cfg.fault_register < 0:
            raise RuntimeError("RUN/STOP и текущая авария IDD не подтверждены: настройте run_register/fault_register и vfd_verified; PA10 — история ошибок")
        hz = self.registers(drive, 3, 2, 1)[0] / 10
        if hz > 400:
            raise RuntimeError(f"IDD {drive}: выходная частота вне документированного диапазона 0..400 Гц; проверьте масштабирование")
        run = self.registers(drive, 3, cfg.run_register, 1)[0]
        fault = self.registers(drive, 3, cfg.fault_register, 1)[0]
        return hz, bool(run & cfg.run_mask), bool(fault & cfg.fault_mask)

    def precheck(self, drive: int) -> None:
        self.precheck_relays()
        self.check_setup(drive)

    def precheck_relays(self) -> None:
        """Verify inactive hydraulic relays without changing any coils."""
        coils = self.coils()
        # Do not start onto an already active hydraulic circuit or another rack.
        owned = [1, *range(9, 15), 19, 20, 23, 31, 32]
        active = [ch for ch in owned if coils[ch - 1]]
        if active:
            raise RuntimeError(f"Пуск запрещён: уже включены реле {active}; проверьте гидравлику и выполните stop")

    def confirm_off(self, channels: tuple[int, ...]) -> None:
        coils = self.coils()
        active = [ch for ch in channels if coils[ch - 1]]
        if active:
            raise RuntimeError(f"Снятие команд реле не подтверждено: {active}")

    def check_setup(self, drive: int) -> None:
        sources = self.registers(drive, 3, 0x65, 2)
        fwd = self.registers(drive, 3, 0x13B, 2)
        if sources != [5, 1] or fwd != [6, 7]:
            raise RuntimeError(f"IDD {drive}: требуются Pb01=5, Pb02=1, Pd15=6, Pd16=7; получены {sources}, {fwd}. См. idd {drive} configure --confirm")

    def frequency_plan(self, drive: int, percent: float) -> FrequencyPlan:
        """Read configuration and validate a setpoint without writing or starting."""
        percent = parse_percent(percent)
        if percent <= 0:
            raise ValueError("Задание frequency должно быть больше 0%")
        self.check_setup(drive)
        maximum, minimum = self.registers(drive, 3, 0x69, 2)
        if not 0 <= minimum <= maximum <= 4000 or maximum == 0:
            raise RuntimeError("Недопустимые Pb05/Pb06; проверьте диапазон частоты на частотнике")
        requested = maximum * percent / 100
        value = int(requested + .5)
        if requested < minimum or value == 0:
            # Round advice upward so copying it cannot produce another below-minimum request.
            minimum_percent = ceil(minimum * 100_000_000 / maximum) / 1_000_000
            raise RuntimeError(f"Задание {requested / 10:g} Гц ниже минимума Pb06={minimum / 10:g} Гц. Минимальный процент от Pb05: {minimum_percent:.6f}%. Проверьте процент и настройки IDD; Pb05/Pb06 автоматически не меняются")
        return FrequencyPlan(percent, minimum, maximum, value)

    def set_frequency(self, drive: int, percent: float) -> None:
        value = self.frequency_plan(drive, percent).setpoint_raw
        self.write_register(drive, 0x2001, value)
        if self.settings.setpoint_readback:
            # 0x2001 is write-only in the published manual; only enable for verified firmware.
            actual = self.registers(drive, 3, 0x2001, 1)[0]
        else:
            actual = self.registers(drive, 3, 1, 1)[0]  # PA01: effective setpoint
        if actual != value:
            raise RuntimeError(f"Уставка IDD не подтверждена: записано {value}, прочитано {actual}")

    def sample(self, drive: int) -> Sample:
        readings = self.pressure()
        for reading in readings:
            if reading.error:
                raise RuntimeError(reading.error)
        hz, running, fault = self.drive_feedback(drive)
        return Sample(readings[0].bar, readings[1].bar, hz, running, fault)

    def configure(self, drive: int) -> None:
        hz, running, fault = self.drive_feedback(drive)
        if hz > self.settings.stop_hz or running or fault or self.coils()[DRIVE_START[drive] - 1]:
            raise RuntimeError("Изменение настроек запрещено: требуются STOP, нулевая частота, отсутствие аварии и разомкнутый FWD")
        for register, value in ((0x65, 5), (0x66, 1), (0x13B, 6), (0x13C, 7)):
            self.write_register(drive, register, value)
            if self.registers(drive, 3, register, 1)[0] != value:
                raise RuntimeError(f"IDD {drive}: настройка 0x{register:04X} не подтверждена")

    def emergency_off(self) -> None:
        errors = []
        for channel in (32, 31, 1):
            try:
                self.relay(channel, False)
            except Exception as exc:
                errors.append(f"реле {channel}: {exc}")
        try:
            coils = self.coils()
            if any(coils[ch - 1] for ch in (32, 31, 1)):
                errors.append("релейная плата не подтвердила снятие пуска")
        except Exception as exc:
            errors.append(f"чтение реле: {exc}")
        if errors:
            raise RuntimeError("Снятие пуска не подтверждено: " + "; ".join(errors))
