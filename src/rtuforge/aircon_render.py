"""Width-aware Russian text rendering for the air-conditioner TUI."""

from __future__ import annotations

from datetime import datetime

from .aircon_config import AirconSettings
from .aircon_state import AirconState, FAN_NAMES, MODE_NAMES, THERMOSTAT_NAMES


def _fit(value: object, width: int) -> str:
    text = str(value)
    if width <= 0:
        return ""
    if len(text) > width:
        return text[: max(0, width - 1)] + ("…" if width else "")
    return text.ljust(width)


def _value(value: object | None, fallback: str = "НЕТ СВЕЖИХ ДАННЫХ") -> str:
    return fallback if value is None else str(value)


def humidity_text(state: AirconState, settings: AirconSettings, *, now: datetime | None = None) -> str:
    if not settings.humidity_enabled:
        return "НЕТ ДАТЧИКА"
    if state.humidity_error is not None:
        return "НЕТ СВЕЖИХ ДАННЫХ"
    if state.humidity_percent is None or state.humidity_updated_at is None:
        return "НЕТ СВЕЖИХ ДАННЫХ"
    current = datetime.now() if now is None else now
    age_ms = (current - state.humidity_updated_at).total_seconds() * 1000
    if age_ms > settings.humidity_stale_ms:
        return "НЕТ СВЕЖИХ ДАННЫХ"
    return f"{state.humidity_percent:.1f} % ({state.humidity_updated_at:%H:%M:%S})"


def _section(title: str, width: int) -> str:
    prefix = f"── {title} "
    return (prefix + "─" * max(0, width - len(prefix)))[:width]


def render_status_lines(
    state: AirconState, settings: AirconSettings, *, width: int, height: int
) -> list[str]:
    width = max(20, width)
    port = settings.port or "НЕ ЗАДАН"
    gateway = "НА СВЯЗИ" if state.gateway_online else "НЕТ СВЯЗИ"
    ac_link = "НА СВЯЗИ" if state.aircon_online else "НЕТ СВЯЗИ"
    fresh = state.fresh
    power = None if not fresh else ("ВКЛ" if state.power else "ВЫКЛ")
    room = None if not fresh or state.room_temperature_c is None else f"{state.room_temperature_c:+.2f} °C"
    target = None if not fresh or state.target_temperature_c is None else f"{state.target_temperature_c:+.1f} °C"
    exchanger = None if not fresh or state.exchanger_temperature_c is None else f"{state.exchanger_temperature_c:+.2f} °C"
    temperature_fallback = "НЕТ ДАННЫХ" if fresh else "НЕТ СВЕЖИХ ДАННЫХ"
    displayed_mode = state.active_mode if fresh else None
    lines = [
        _fit("HISENSE AUC-18HR4SAA1 | ONOKOM HS-6-MB-B", width),
        _section("ПОДКЛЮЧЕНИЕ", width),
        _fit(f"{port}  {settings.baudrate} {settings.bytesize}{settings.parity}{settings.stopbits:g}  Modbus ID: {settings.slave_id}", width),
        _fit(f"Шлюз: {gateway:<12} Кондиционер: {ac_link}", width),
        _section("СОСТОЯНИЕ", width),
        _fit(f"Питание:       {_value(power)}", width),
        _fit(f"Режим:         {_value(MODE_NAMES.get(displayed_mode))}", width),
        _fit(f"Термостат:     {_value(THERMOSTAT_NAMES.get(state.thermostat) if fresh else None)}", width),
        _fit(f"Вентилятор:    {_value(FAN_NAMES.get(state.fan) if fresh else None)}", width),
        _section("КЛИМАТ", width),
        _fit(f"Температура сейчас: {_value(room, temperature_fallback)}", width),
        _fit(f"Температура задана: {_value(target)}", width),
        _fit(f"Теплообменник:       {_value(exchanger, temperature_fallback)}", width),
        _fit(f"Влажность, %:        {humidity_text(state, settings)}", width),
        _section("ДИАГНОСТИКА", width),
        _fit(f"Последний ответ: {_value(state.last_response_at.strftime('%d.%m.%Y %H:%M:%S') if state.last_response_at else None, '—')}", width),
        _fit(f"Тайм-ауты: {state.timeout_count}  CRC: {state.crc_error_count}  Ошибки: {state.exchange_error_count}", width),
        _fit("F1 Справка  F2 Статус  F3 Порты  F4 Настройки  Esc Назад", width),
    ]
    return (lines + [" " * width] * height)[:height]


HELP_LINES = [
    "СПРАВКА — управление Hisense через ONOKOM HS-6-MB-B",
    "Назначение: безопасное чтение состояния и ручное управление кондиционером.",
    "Подключение: HS-A6 подключается к CN18 WIRED CON, шлюз — к RS485.",
    "Параметры ONOKOM по умолчанию: 9600 бод, 8N2, Modbus ID 1.",
    "COM-порт задаётся в F4 или глобальным параметром --port COM7.",
    "",
    "КОМАНДЫ",
    "on / off                 включить / выключить",
    "temp 23                 задать 16..30 °C, шаг 1 °C",
    "mode heat|cool|auto|dry|fan",
    "fan auto|1|2|3          скорость вентилятора",
    "status, ports, connect, disconnect, settings, help, exit",
    "set <имя> <значение>    сохранить параметр только в aircon.ini",
    "",
    "ВЛАЖНОСТЬ",
    "В HS-6-MB-B нет регистра RH. Значение доступно только от отдельно настроенного",
    "Modbus-датчика. Режим dry не является автоматическим поддержанием уставки RH.",
    "",
    "ДИАГНОСТИКА",
    "«Нет ответа Modbus» означает потерю шлюза; «кондиционер не на связи» означает,",
    "что шлюз отвечает, но HS-A6/кондиционер не подтверждает связь. Esc — назад.",
]


def render_help_lines(*, width: int, height: int) -> list[str]:
    lines = [_fit(line, width) for line in HELP_LINES]
    return (lines + [" " * width] * height)[:height]


def render_settings_lines(settings: AirconSettings, *, width: int, height: int) -> list[str]:
    rows = [
        "НАСТРОЙКИ AIRCON (set <имя> <значение>; сохраняются в aircon.ini)",
        f"port={settings.port or 'НЕ ЗАДАН'}  baudrate={settings.baudrate}  bytesize={settings.bytesize}",
        f"parity={settings.parity}  stopbits={settings.stopbits:g}  timeout_ms={settings.timeout_ms}",
        f"slave_id={settings.slave_id}  poll_interval_ms={settings.poll_interval_ms}",
        f"auto_connect={str(settings.auto_connect).lower()}",
        "",
        "ВНЕШНИЙ ДАТЧИК ВЛАЖНОСТИ",
        f"humidity_enabled={str(settings.humidity_enabled).lower()}",
        f"humidity_slave_id={settings.humidity_slave_id}",
        f"humidity_register_type={settings.humidity_register_type}",
        f"humidity_address={settings.humidity_address}",
        f"humidity_scale={settings.humidity_scale:g}",
        f"humidity_stale_ms={settings.humidity_stale_ms}",
        f"diagnostic_log={settings.diagnostic_log}",
        "",
        "Изменение параметров соединения отключает активный порт до команды connect.",
        "Параметры командной строки имеют приоритет и в aircon.ini не записываются.",
        "Esc — вернуться на предыдущий экран.",
    ]
    lines = [_fit(line, width) for line in rows]
    return (lines + [" " * width] * height)[:height]


def render_ports_lines(ports: list[str], *, width: int, height: int) -> list[str]:
    rows = ["ДОСТУПНЫЕ COM-ПОРТЫ", *(ports or ["Последовательные порты не найдены."]), "", "Esc — назад"]
    lines = [_fit(line, width) for line in rows]
    return (lines + [" " * width] * height)[:height]
