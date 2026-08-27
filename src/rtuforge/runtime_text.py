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
        "record_usage": "Usage: record start [all|rx] | record stop <buffer|clipboard|file PATH> | record status | record cancel | record script <name> <all|rx> <buffer|clipboard|file PATH> [-d|--decode|-r|--raw] [-c|--clean]",
        "record_script_usage": "Usage: record script <name> <all|rx> <buffer|clipboard|file PATH> [-d|--decode|-r|--raw] [-c|--clean]",
        "record_script_conflict": "record script: --decode and --raw cannot be used together",
        "record_script_unknown_flag": "Unknown record script flag: {flag}",
        "record_already_active": "Recording is already active ({mode}).", "record_not_active": "Recording is not active.",
        "record_started": "Recording started: {mode}.", "record_status_active": "Recording: active, mode={mode}, lines={count}",
        "record_status_inactive": "Recording: inactive", "record_cancelled": "Recording cancelled.",
        "record_copied": "Recording copied to clipboard ({count} lines).", "record_saved": "Recording saved to {path} ({count} lines).",
        "clipboard_error": "Clipboard error: {error}", "record_mode_all": "TX + RX", "record_mode_rx": "RX only",
        "record_oneshot": "record start/stop alone is meaningful only in interactive mode or inside a running script",
        "help_extra": "Additional commands:\n  show record                       Show current recording buffer\n  record start [all|rx]             Start session recording\n  record stop buffer                Copy recording to clipboard\n  record stop file <path>           Save recording to a UTF-8 file\n  record script <name> ...          Run and capture a script in one command\n  record status                     Show recording state\n  record cancel                     Discard current recording",
        "help_record": """record start [all|rx]\nrecord stop <buffer|clipboard|file PATH>\nrecord status\nrecord cancel\nshow record\nrecord script <name> <all|rx> <buffer|clipboard|file PATH> [-d|--decode|-r|--raw] [-c|--clean]\n\nRecord raw Modbus exchanges in the current process.\n\nModes:\n  all   Record request and response. In normal output the buffer uses TX/RX labels; in clean output it stores plain HEX lines.\n  rx    Record responses only as plain HEX lines.\n\nSession example:\n  record start all\n  send 01 03 00 65 00 01\n  show record\n  record stop buffer\n\nOne-command script capture:\n  record script idd-status rx file captures/idd-status.txt -r\n  record script idd-status all buffer -c -r\n\nFlags for record script:\n  -d, --decode   Force Modbus decoding while the script runs.\n  -r, --raw      Suppress Modbus decoding while the script runs.\n  -c, --clean    Temporarily force clean output and clean 'all' recording format; config.ini is not changed.\n\nRecording itself always stores raw frames, not the decoded text. Relative file paths are resolved from config.ini.\n""",
        "help_run": """run script <name> [-d|--decode|-r|--raw]\n\nRun a stored script line by line.\n\nExamples:\n  run script idd-status\n  run script idd-status -r\n  run script idd-status -d\n\nDecode priority:\n  flag on an individual send > flag on run script > runtime.decode_rx.\n\nFor one-shot mode, -c/--clean is a global CLI flag and may be placed before or after the command:\n  rtuforge -c run script idd-status -r\n  rtuforge run script idd-status -c -r\n""",
        "frame_short": "Frame too short for Modbus decoding", "modbus_exception": "Modbus exception", "slave": "Slave",
        "function": "Function", "exception": "Exception", "byte_count": "Byte count", "data": "Data", "registers": "Registers",
        "address": "Address", "value": "Value", "crc": "CRC",
        "scan_label": "Scan", "scan_found_progress": "found", "scan_found": "found",
        "scan_exception": "exception", "scan_found_count": "Devices found: {count}",
        "scan_slave_ids": "Slave IDs: {ids}", "scan_none": "No devices found.",
        "scan_stopped": "Scan stopped.", "scan_missing_value": "Missing value for {flag}",
        "scan_invalid_value": "Invalid value for {flag}: {value}",
        "scan_unknown_flag": "Unknown scan flag: {flag}",
        "scan_usage": "Usage: scan [start [end]] [--timeout ms] [--function 01|02|03|04] [--address address]",
        "scan_invalid_slave": "Slave IDs must be decimal integers",
        "scan_invalid_range": "Slave ID range must be within 1..247 and start must not exceed end",
        "scan_invalid_timeout": "Scan timeout must be greater than zero",
        "scan_invalid_function": "Scan function must be one of 01, 02, 03, 04",
        "scan_invalid_address": "Scan address must be within 0..65535",
        "invalid_connection_override": "Invalid temporary connection value: {name}",
        "home": "Home", "config_path": "Config", "scripts_path": "Scripts", "history_path": "History",
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
        "record_usage": "Использование: record start [all|rx] | record stop <buffer|clipboard|file PATH> | record status | record cancel | record script <name> <all|rx> <buffer|clipboard|file PATH> [-d|--decode|-r|--raw] [-c|--clean]",
        "record_script_usage": "Использование: record script <name> <all|rx> <buffer|clipboard|file PATH> [-d|--decode|-r|--raw] [-c|--clean]",
        "record_script_conflict": "record script: --decode и --raw нельзя использовать одновременно",
        "record_script_unknown_flag": "Неизвестный флаг record script: {flag}",
        "record_already_active": "Запись уже идёт ({mode}).", "record_not_active": "Запись не активна.",
        "record_started": "Запись начата: {mode}.", "record_status_active": "Запись: активна, режим={mode}, строк={count}",
        "record_status_inactive": "Запись: не активна", "record_cancelled": "Запись отменена.",
        "record_copied": "Запись скопирована в буфер обмена ({count} строк).", "record_saved": "Запись сохранена в {path} ({count} строк).",
        "clipboard_error": "Ошибка буфера обмена: {error}", "record_mode_all": "TX + RX", "record_mode_rx": "только RX",
        "record_oneshot": "record start/stop отдельно имеет смысл только в интерактивном режиме или внутри выполняющегося скрипта",
        "help_extra": "Дополнительные команды:\n  show record                       Показать текущий буфер записи\n  record start [all|rx]             Начать сессионную запись\n  record stop buffer                Скопировать запись в буфер обмена\n  record stop file <path>           Сохранить запись в UTF-8 файл\n  record script <name> ...          Выполнить и записать скрипт одной командой\n  record status                     Показать состояние записи\n  record cancel                     Отменить текущую запись",
        "help_record": """record start [all|rx]\nrecord stop <buffer|clipboard|file PATH>\nrecord status\nrecord cancel\nshow record\nrecord script <name> <all|rx> <buffer|clipboard|file PATH> [-d|--decode|-r|--raw] [-c|--clean]\n\nЗаписывает сырые Modbus-обмены в рамках текущего процесса.\n\nРежимы:\n  all   Запрос и ответ. В обычном выводе буфер содержит метки TX/RX; в чистом режиме сохраняются только HEX-строки.\n  rx    Только ответы, всегда как чистые HEX-строки.\n\nСессионный пример:\n  record start all\n  send 01 03 00 65 00 01\n  show record\n  record stop buffer\n\nЗапись скрипта одной командой:\n  record script idd-status rx file captures/idd-status.txt -r\n  record script idd-status all buffer -c -r\n\nФлаги record script:\n  -d, --decode   Принудительно включить расшифровку Modbus при выполнении скрипта.\n  -r, --raw      Отключить расшифровку Modbus при выполнении скрипта.\n  -c, --clean    Временно включить чистый вывод и чистый формат записи all; config.ini не изменяется.\n\nВ запись всегда попадают сырые кадры, а не текст расшифровки. Относительный путь файла считается от каталога config.ini.\n""",
        "help_run": """run script <name> [-d|--decode|-r|--raw]\n\nВыполнить сохранённый скрипт построчно.\n\nПримеры:\n  run script idd-status\n  run script idd-status -r\n  run script idd-status -d\n\nПриоритет расшифровки:\n  флаг отдельного send > флаг run script > runtime.decode_rx.\n\nВ one-shot режиме -c/--clean является общим CLI-флагом и может стоять до или после команды:\n  rtuforge -c run script idd-status -r\n  rtuforge run script idd-status -c -r\n""",
        "frame_short": "Кадр слишком короткий для расшифровки Modbus", "modbus_exception": "Исключение Modbus", "slave": "Адрес устройства",
        "function": "Функция", "exception": "Исключение", "byte_count": "Количество байт", "data": "Данные", "registers": "Регистры",
        "address": "Адрес", "value": "Значение", "crc": "CRC",
        "scan_label": "Поиск", "scan_found_progress": "найдено", "scan_found": "найден",
        "scan_exception": "исключение", "scan_found_count": "Найдено устройств: {count}",
        "scan_slave_ids": "Slave ID: {ids}", "scan_none": "Устройства не найдены.",
        "scan_stopped": "Поиск остановлен.", "scan_missing_value": "Не указано значение для {flag}",
        "scan_invalid_value": "Некорректное значение {flag}: {value}",
        "scan_unknown_flag": "Неизвестный флаг scan: {flag}",
        "scan_usage": "Использование: scan [начало [конец]] [--timeout мс] [--function 01|02|03|04] [--address адрес]",
        "scan_invalid_slave": "Slave ID должны быть целыми десятичными числами",
        "scan_invalid_range": "Диапазон Slave ID должен быть в пределах 1..247, начало не больше конца",
        "scan_invalid_timeout": "Таймаут поиска должен быть больше нуля",
        "scan_invalid_function": "Функция поиска должна быть одной из: 01, 02, 03, 04",
        "scan_invalid_address": "Адрес поиска должен быть в пределах 0..65535",
        "invalid_connection_override": "Некорректный временный параметр соединения: {name}",
        "home": "Домашний каталог", "config_path": "Конфигурация", "scripts_path": "Скрипты", "history_path": "История",
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
