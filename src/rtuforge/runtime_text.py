from __future__ import annotations


def _lang(language: str | None) -> str:
    return "ru" if (language or "en").strip().lower() == "ru" else "en"


TEXT: dict[str, dict[str, str]] = {
    "en": {
        "connected": "Connected {endpoint}", "disconnected": "Disconnected",
        "no_ports": "No serial ports found.", "port_col": "Port", "description_col": "Description", "hwid_col": "HWID",
        "connection": "Connection", "connected_state": "CONNECTED", "disconnected_state": "DISCONNECTED",
        "endpoint": "Endpoint", "port": "Port", "baudrate": "Baudrate", "format": "Format", "timeout": "Timeout",
        "crc_mode": "CRC mode", "decode_rx": "Decode RX", "clean_output": "Clean output", "language": "Language",
        "no_data": "<timeout / no data>", "not_connected": "Not connected. Use connect or enable runtime.auto_connect.",
        "send_conflict": "send: --decode and --raw cannot be used together",
        "send_usage": "Usage: send [-d|--decode|-r|--raw] <hex bytes...>",
        "run_conflict": "run script: --decode and --raw cannot be used together",
        "run_usage": "Usage: run script <name> [-d|--decode|-r|--raw]",
        "run_unknown_flag": "Unknown run script flag: {flag}", "pause_usage": "Usage: pause <milliseconds>",
        "no_scripts": "No scripts.", "script_empty": "Script '{name}' is empty.", "script_not_found": "Script '{name}' not found.",
        "script_deleted": "Deleted script '{name}'.", "unknown_section": "Unknown option section: {section}",
        "unknown_option": "Unknown option: {name}", "allowed_values": "Allowed values: {values}",
        "expected_boolean": "Expected boolean: true/false, yes/no, on/off, 1/0",
        "connection_option_disconnect": "Disconnected because a connection option changed.",
        "option_saved": "Saved {section}.{name} = {value}", "clear_script_forbidden": "clear/cls is not allowed inside scripts",
        "exit_script_forbidden": "exit/quit is not allowed inside scripts", "add_script_interactive": "add script is interactive-only",
        "history_script_forbidden": "history is not allowed inside scripts", "unknown_command": "Unknown command: {command}. Use 'help'.",
        "shell_banner": "RTU Forge interactive shell. Type help.",
        "capture_script": "Capturing script {name}. Finish with 'end script'.", "script_saved": "Saved script '{name}' ({count} commands).",
        "history_error": "History error: {error}", "history_cleared": "History file cleared. Restart shell to clear in-memory history.",
        "error": "Error: {error}", "oneshot_add_script": "'add script' is available only in interactive mode",
        "oneshot_history": "history commands are available only in interactive mode", "oneshot_clear": "clear/cls is available only in interactive mode",
        "record_usage": "Usage: record start [all|rx] | record stop <buffer|clipboard|file PATH> | record status | record cancel",
        "record_already_active": "Recording is already active ({mode}).", "record_not_active": "Recording is not active.",
        "record_started": "Recording started: {mode}.", "record_status_active": "Recording: active, mode={mode}, lines={count}",
        "record_status_inactive": "Recording: inactive", "record_cancelled": "Recording cancelled.",
        "record_copied": "Recording copied to clipboard ({count} lines).", "record_saved": "Recording saved to {path} ({count} lines).",
        "clipboard_error": "Clipboard error: {error}", "record_mode_all": "TX + RX", "record_mode_rx": "RX only",
        "record_oneshot": "record start/stop alone is meaningful only in interactive mode or inside a running script",
        "frame_short": "Frame too short for Modbus decoding", "modbus_exception": "Modbus exception", "slave": "Slave",
        "function": "Function", "exception": "Exception", "byte_count": "Byte count", "data": "Data", "registers": "Registers",
        "address": "Address", "value": "Value", "crc": "CRC",
    },
    "ru": {
        "connected": "Подключено {endpoint}", "disconnected": "Отключено",
        "no_ports": "Последовательные порты не найдены.", "port_col": "Порт", "description_col": "Описание", "hwid_col": "HWID",
        "connection": "Соединение", "connected_state": "ПОДКЛЮЧЕНО", "disconnected_state": "ОТКЛЮЧЕНО",
        "endpoint": "Endpoint", "port": "Порт", "baudrate": "Скорость", "format": "Формат", "timeout": "Таймаут",
        "crc_mode": "Режим CRC", "decode_rx": "Расшифровка RX", "clean_output": "Чистый вывод", "language": "Язык",
        "no_data": "<таймаут / нет данных>", "not_connected": "Нет соединения. Выполните connect или включите runtime.auto_connect.",
        "send_conflict": "send: --decode и --raw нельзя использовать одновременно",
        "send_usage": "Использование: send [-d|--decode|-r|--raw] <hex bytes...>",
        "run_conflict": "run script: --decode и --raw нельзя использовать одновременно",
        "run_usage": "Использование: run script <name> [-d|--decode|-r|--raw]",
        "run_unknown_flag": "Неизвестный флаг run script: {flag}", "pause_usage": "Использование: pause <миллисекунды>",
        "no_scripts": "Скриптов нет.", "script_empty": "Скрипт '{name}' пуст.", "script_not_found": "Скрипт '{name}' не найден.",
        "script_deleted": "Скрипт '{name}' удалён.", "unknown_section": "Неизвестный раздел параметров: {section}",
        "unknown_option": "Неизвестный параметр: {name}", "allowed_values": "Допустимые значения: {values}",
        "expected_boolean": "Ожидается логическое значение: true/false, yes/no, on/off, 1/0",
        "connection_option_disconnect": "Соединение закрыто из-за изменения параметра подключения.",
        "option_saved": "Сохранено {section}.{name} = {value}", "clear_script_forbidden": "clear/cls нельзя использовать внутри скрипта",
        "exit_script_forbidden": "exit/quit нельзя использовать внутри скрипта", "add_script_interactive": "add script доступен только в интерактивном режиме",
        "history_script_forbidden": "history нельзя использовать внутри скрипта", "unknown_command": "Неизвестная команда: {command}. Используйте 'help'.",
        "shell_banner": "Интерактивная консоль RTU Forge. Для справки: help.",
        "capture_script": "Запись скрипта {name}. Для завершения: 'end script'.", "script_saved": "Скрипт '{name}' сохранён ({count} команд).",
        "history_error": "Ошибка истории: {error}", "history_cleared": "Файл истории очищен. Перезапустите консоль для очистки истории в памяти.",
        "error": "Ошибка: {error}", "oneshot_add_script": "'add script' доступен только в интерактивном режиме",
        "oneshot_history": "Команды history доступны только в интерактивном режиме", "oneshot_clear": "clear/cls доступен только в интерактивном режиме",
        "record_usage": "Использование: record start [all|rx] | record stop <buffer|clipboard|file PATH> | record status | record cancel",
        "record_already_active": "Запись уже идёт ({mode}).", "record_not_active": "Запись не активна.",
        "record_started": "Запись начата: {mode}.", "record_status_active": "Запись: активна, режим={mode}, строк={count}",
        "record_status_inactive": "Запись: не активна", "record_cancelled": "Запись отменена.",
        "record_copied": "Запись скопирована в буфер обмена ({count} строк).", "record_saved": "Запись сохранена в {path} ({count} строк).",
        "clipboard_error": "Ошибка буфера обмена: {error}", "record_mode_all": "TX + RX", "record_mode_rx": "только RX",
        "record_oneshot": "record start/stop отдельно имеет смысл только в интерактивном режиме или внутри выполняющегося скрипта",
        "frame_short": "Кадр слишком короткий для расшифровки Modbus", "modbus_exception": "Исключение Modbus", "slave": "Адрес устройства",
        "function": "Функция", "exception": "Исключение", "byte_count": "Количество байт", "data": "Данные", "registers": "Регистры",
        "address": "Адрес", "value": "Значение", "crc": "CRC",
    },
}

FUNCTION_NAMES: dict[str, dict[int, str]] = {
    "en": {1: "Read Coils", 2: "Read Discrete Inputs", 3: "Read Holding Registers", 4: "Read Input Registers", 5: "Write Single Coil", 6: "Write Single Register", 15: "Write Multiple Coils", 16: "Write Multiple Registers"},
    "ru": {1: "Чтение катушек", 2: "Чтение дискретных входов", 3: "Чтение регистров хранения", 4: "Чтение входных регистров", 5: "Запись одной катушки", 6: "Запись одного регистра", 15: "Запись нескольких катушек", 16: "Запись нескольких регистров"},
}

EXCEPTION_NAMES: dict[str, dict[int, str]] = {
    "en": {1: "Illegal Function", 2: "Illegal Data Address", 3: "Illegal Data Value", 4: "Slave Device Failure", 5: "Acknowledge", 6: "Slave Device Busy", 8: "Memory Parity Error", 10: "Gateway Path Unavailable", 11: "Gateway Target Device Failed to Respond"},
    "ru": {1: "Недопустимая функция", 2: "Недопустимый адрес данных", 3: "Недопустимое значение данных", 4: "Ошибка ведомого устройства", 5: "Подтверждение", 6: "Устройство занято", 8: "Ошибка чётности памяти", 10: "Путь шлюза недоступен", 11: "Целевое устройство шлюза не ответило"},
}


def tr(language: str | None, key: str, **values: object) -> str:
    lang = _lang(language)
    template = TEXT[lang].get(key, TEXT["en"].get(key, key))
    return template.format(**values)


def function_name(language: str | None, code: int) -> str | None:
    return FUNCTION_NAMES[_lang(language)].get(code)


def exception_name(language: str | None, code: int) -> str | None:
    return EXCEPTION_NAMES[_lang(language)].get(code)
