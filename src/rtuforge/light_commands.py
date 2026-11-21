"""Four-channel light control in the existing RTU Forge shell."""
from __future__ import annotations

import configparser

from .config import save_config
from .light_protocol import (
    build_read, build_write, check_address, check_channel,
    check_write, display_level, parse_read, percent_to_raw,
)

HELP = """СВЕТ: WAVESHARE AO, 0..10 В, четыре канала
  light help                   Справка, без соединения
  light config                 Адрес и соответствие выходов, без соединения
  light status                 Прочитать все 4 AO: яркость % и напряжение В
  light 1 100                  AO канала 1: 100% = 10 В
  light channel 2 50           Канал 2: 50% = 5 В
  light all 0                  Все каналы: 0% (четыре отдельных записи)
  light set address 1          Сохранить Modbus ID в config.ini
  light set channel 1 1        Назначить логическому каналу 1 физический AO1
  set options port COM7        Сохранить COM-порт RTU Forge
  set options baudrate 9600    Сохранить скорость
  help light                   Справка

По умолчанию ID=1, логические каналы 1..4 соответствуют AO1..AO4.
При статусе напряжение рассчитывается по прочитанным мВ, не измеряется вольтметром.
Записи меняют реальные выходы. При запуске никакие значения не восстанавливаются.
"""


def mapping(config: configparser.ConfigParser) -> tuple[int, tuple[int, ...]]:
    section = config["light"]
    try:
        address = check_address(section.getint("light_address"))
        channels = tuple(check_channel(section.getint(f"light_channel_{n}")) for n in range(1, 5))
    except (ValueError, configparser.Error) as exc:
        raise ValueError(f"Ошибка настроек света в config.ini: {exc}") from None
    if len(set(channels)) != 4:
        raise ValueError("Физический AO нельзя назначить нескольким каналам")
    return address, channels


def _read(ctx, address: int, channel: int) -> int:
    from .commands import ensure_connected
    ensure_connected(ctx)
    req = build_read(address, channel)
    response = ctx.transport.exchange(req, crc_mode_override="append").rx
    return parse_read(req, response)


def _write(ctx, address: int, channel: int, raw: int) -> None:
    from .commands import ensure_connected
    ensure_connected(ctx)
    req = build_write(address, channel, raw)
    response = ctx.transport.exchange(req, crc_mode_override="append").rx
    check_write(req, response)


def _save(ctx, option: str, value: str) -> None:
    ctx.config["light"][option] = value
    save_config(ctx.config_path, ctx.config)


def execute_light(ctx, parts: list[str]) -> None:
    if not parts or parts[0].lower() == "help":
        if len(parts) > 1:
            raise ValueError("Использование: light help")
        ctx.console.print(HELP, markup=False)
        return

    command = parts[0].lower()
    address, channels = mapping(ctx.config)
    if command == "config":
        if len(parts) != 1:
            raise ValueError("Использование: light config")
        settings = getattr(ctx.transport, "settings", None)
        port = getattr(settings, "port", ctx.config.get("connection", "port", fallback="?"))
        ctx.console.print(f"Свет: Modbus ID={address}, порт={port}", markup=False)
        for index, physical in enumerate(channels, 1):
            ctx.console.print(f"Канал {index} -> AO{physical}", markup=False)
        return

    if command == "set":
        if len(parts) == 3 and parts[1].lower() == "address":
            try:
                target = check_address(int(parts[2]))
            except (ValueError, TypeError):
                raise ValueError("Адрес Modbus должен быть 1..247") from None
            _save(ctx, "light_address", str(target))
            ctx.console.print(f"Сохранён адрес света: {target}", markup=False)
            return
        if len(parts) == 4 and parts[1].lower() == "channel":
            try:
                index = check_channel(int(parts[2]))
                physical = check_channel(int(parts[3]))
            except (ValueError, TypeError):
                raise ValueError("Номера каналов должны быть 1..4") from None
            swap = next((i for i, value in enumerate(channels, 1) if value == physical), index)
            previous = channels[index - 1]
            if swap != index:
                ctx.config["light"][f"light_channel_{swap}"] = str(previous)
            _save(ctx, f"light_channel_{index}", str(physical))
            ctx.console.print(f"Сохранён канал {index} -> AO{physical}" + (f"; канал {swap} -> AO{previous}" if swap != index else ""), markup=False)
            return
        raise ValueError("Использование: light set address <1..247> | light set channel <1..4> <1..4>")

    if command == "status":
        if len(parts) != 1:
            raise ValueError("Использование: light status")
        for index, physical in enumerate(channels, 1):
            raw = _read(ctx, address, physical)
            ctx.console.print(f"Канал {index} (AO{physical}): {display_level(raw)}", markup=False)
        return

    if command == "all":
        if len(parts) != 2:
            raise ValueError("Использование: light all <0..100>")
        raw = percent_to_raw(parts[1])
        for index, physical in enumerate(channels, 1):
            _write(ctx, address, physical, raw)
            confirmed = _read(ctx, address, physical)
            if confirmed != raw:
                raise RuntimeError(f"Канал {index} AO{physical}: запись не совпала с чтением")
            ctx.console.print(f"Канал {index} (AO{physical}): {display_level(confirmed)}", markup=False)
        return

    values = parts[1:]
    if command == "channel":
        if len(parts) != 3:
            raise ValueError("Использование: light channel <1..4> <0..100>")
        values = parts[1:]
    else:
        values = parts
    if len(values) != 2:
        raise ValueError("Использование: light <1..4> <0..100>")
    try:
        index = check_channel(int(values[0]))
    except (ValueError, TypeError):
        raise ValueError("Номер канала должен быть 1..4") from None
    raw = percent_to_raw(values[1])
    physical = channels[index - 1]
    _write(ctx, address, physical, raw)
    confirmed = _read(ctx, address, physical)
    if confirmed != raw:
        raise RuntimeError(f"Канал {index} AO{physical}: запись не совпала с чтением")
    ctx.console.print(f"Канал {index} (AO{physical}): {display_level(confirmed)}", markup=False)
