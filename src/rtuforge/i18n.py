from __future__ import annotations

SUPPORTED_LANGUAGES: tuple[str, ...] = ("en", "ru")


def normalize_language(language: str | None) -> str:
    value = (language or "en").strip().lower()
    return value if value in SUPPORTED_LANGUAGES else "en"


GENERAL_HELP: dict[str, str] = {
    "en": """Commands:
  connect                         Connect using current connection options
  disconnect                      Close serial connection
  ports                           List available serial ports
  status                          Show connection state and current settings
  paths                           Show active home/config/scripts/history paths
  scan [start [end]] [options]    Find Modbus RTU devices by slave ID
  send [-d|--decode|-r|--raw] <hex...>
                                  Send one Modbus RTU frame
  add script <name>               Capture commands until 'end script'
  run script <name> [-d|-r]       Run a stored script
  scripts | ls | list             List stored scripts
  show script <name>              Show script contents
  show record                     Show current recording buffer
  delete script <name>            Delete a stored script
  record start [all|rx]           Start session recording
  record stop <destination>       Save/copy and stop recording
  record script <name> ...        Run and record a script in one command
  record status | cancel          Inspect/cancel session recording
  options [section]               Show mutable options
  set options <name> <value>      Change and persist an option
  pause <ms>                      Sleep; useful inside scripts
  history                         Show recent interactive commands
  history clear                   Clear persistent history
  clear | cls                     Clear the terminal
  help [command]                  Show general or command-specific help
  exit | quit                     Leave the shell

One-shot global flag:
  -c, --clean                     Plain HEX output for this invocation only

Use 'help scan', 'help scripts', 'help send', 'help run' and 'help record' for details.
""",
    "ru": """Команды:
  connect                         Подключиться с текущими параметрами
  disconnect                      Закрыть последовательное соединение
  ports                           Показать доступные последовательные порты
  status                          Показать состояние и текущие параметры
  paths                           Показать пути home/config/scripts/history
  scan [начало [конец]] [опции]   Найти Modbus RTU устройства по slave ID
  send [-d|--decode|-r|--raw] <hex...>
                                  Отправить один Modbus RTU кадр
  add script <name>               Записать скрипт до команды 'end script'
  run script <name> [-d|-r]       Запустить сохранённый скрипт
  scripts | ls | list             Показать список скриптов
  show script <name>              Показать содержимое скрипта
  show record                     Показать текущий буфер записи
  delete script <name>            Удалить сохранённый скрипт
  record start [all|rx]           Начать сессионную запись
  record stop <назначение>        Сохранить/скопировать и остановить запись
  record script <name> ...        Выполнить и записать скрипт одной командой
  record status | cancel          Состояние/отмена сессионной записи
  options [section]               Показать изменяемые параметры
  set options <name> <value>      Изменить и сохранить параметр
  pause <ms>                      Пауза; удобно внутри скриптов
  history                         Показать историю интерактивных команд
  history clear                   Очистить сохранённую историю
  clear | cls                     Очистить экран
  help [command]                  Общая или подробная справка
  exit | quit                     Выйти из консоли

Глобальный флаг one-shot режима:
  -c, --clean                     Чистый HEX-вывод только для этого запуска

Подробнее: help scan, help scripts, help send, help run, help record.
""",
}


HELP: dict[str, dict[str, str]] = {
    "en": {
        "connect": """connect

Open the serial connection using the current [connection] options. The command does not change config.ini.

Examples:
  connect
  status

Changing a connection option with 'set options ...' disconnects an active connection first.

Temporary startup examples:
  rtuforge --port COM7
  rtuforge --port COM7 --baudrate 19200 --parity N
  rtuforge --port /dev/ttyUSB0 --baudrate 115200 connect

Startup overrides apply only to the current process and never change config.ini. They remain effective even if a persistent connection option is changed with 'set options'; restart without the flag to use the saved value.
""",
        "disconnect": """disconnect

Close the active serial connection. Safe to use when already disconnected.
""",
        "ports": """ports

List serial ports detected by pyserial. No port is opened.

Columns:
  Port         Device name such as COM4 or /dev/ttyUSB0
  Description  Driver/device description
  HWID         Hardware identifier reported by the OS
""",
        "status": """status

Show real connection state and current settings without auto-connecting.

Includes port, baud rate, serial format, timeout, CRC mode, RX decoding, clean output and interface language.

Connection values are effective runtime values. Fields supplied as startup overrides are marked [CLI]. Use 'options connection' to see persistent config.ini values.
""",
        "paths": """paths

Show the active RTU Forge data/home directory and absolute paths to config.ini, scripts.ini and history.

When RTUFORGE_HOME is set by a user launcher, these paths do not depend on the current working directory. The command also works before config.ini exists.
""",
        "scan": """scan [start [end]] [--timeout ms] [--function 01|02|03|04] [--address address]

Search for Modbus RTU devices by slave ID. A slave ID is the device address on the bus; valid IDs are 1..247.

Defaults:
  range       1..247
  function    03 Read Holding Registers
  address     0
  quantity    1
  timeout     runtime.scan_timeout_ms (default 100 ms per device)

Only read-only functions 01, 02, 03 and 04 are allowed. A device is found only when its response has a valid CRC, matching slave ID, and the requested function. A valid Modbus exception response also proves that the device was found.

Options:
  --timeout <ms>       Temporary per-device timeout; does not change config.ini.
  --function <01..04>  Read function used by the probe.
  --address <address>  Decimal or 0x-prefixed hexadecimal address.

Examples:
  scan
  scan 7
  scan 1 32 --timeout 200
  scan 1 32 --function 04
  scan 1 32 --function 03 --address 0x0065
  rtuforge scan -c

Normal TTY output uses one stable progress line. Ctrl+C stops the scan and returns to the shell. Clean mode prints only found slave IDs, one per line. Scan always sends one valid CRC without changing runtime.crc_mode.
""",
        "send": """send [-d|--decode|-r|--raw] <hex bytes...>

Send one raw Modbus RTU frame and wait for a response.

Examples:
  send 01 03 00 65 00 01
  send --decode 01 03 00 65 00 01
  send -r 01 06 20 00 00 02

Decode flags:
  -d, --decode   Force response decoding for this send.
  -r, --raw      Suppress response decoding for this send.

If neither is present, inherited script mode is used; otherwise runtime.decode_rx is used. An explicit send flag has the highest decode priority.

CRC is controlled separately by runtime.crc_mode:
  auto    Keep a valid supplied CRC, otherwise append one.
  append  Always append CRC.
  none    Send bytes exactly as entered.

Clean output is configured by runtime.clean_output. In one-shot mode use global -c/--clean for a temporary override.
""",
        "add": """add script <name>

Interactive-only script capture. Every entered line is stored until 'end script'.

Example:
  add script read-basic
  send 01 03 00 65 00 01
  pause 100
  send --decode 01 03 00 66 00 01
  end script

The result is stored in scripts.ini. See 'help scripts' for commands allowed inside scripts.
""",
        "run": """run script <name> [-d|--decode|-r|--raw]

Run a stored script line by line.

Examples:
  run script idd-status
  run script idd-status -r
  run script idd-status -d

Decode priority:
  flag on individual send > flag on run script > runtime.decode_rx

runtime.inter_command_delay_ms is applied between stored lines; explicit 'pause <ms>' adds another delay.

For one-shot clean output:
  rtuforge -c run script idd-status -r
  rtuforge run script idd-status -c -r

The global -c/--clean flag does not modify config.ini.
""",
        "scripts": """scripts | ls | list

List stored scripts. Scripts are command sequences saved in scripts.ini.

Create:
  add script read-basic
  send 01 03 00 65 00 01
  pause 100
  record start rx
  send 01 03 00 66 00 01
  show record
  record stop file capture.txt
  end script

Run / inspect / delete:
  run script read-basic
  show script read-basic
  delete script read-basic

Useful commands inside scripts:
  send ...
  send --decode ...
  send --raw ...
  pause <ms>
  connect
  disconnect
  status
  ports
  run script <name> [-d|-r]
  scripts | ls | list
  show script <name>
  show record
  record start [all|rx]
  record stop <buffer|clipboard|file PATH>
  record status
  record cancel
  record script <name> ...
  options [section]
  set options <name> <value>
  help [command]

Not allowed inside scripts:
  add script ...
  history / history clear
  clear / cls
  exit / quit

Empty lines and lines beginning with '#' are ignored. Nested scripts are supported; avoid recursive cycles.
""",
        "show": """show script <name>
show record

'show script <name>' prints a saved script without running it.
'show record' prints the current in-memory recording buffer without stopping recording.

Examples:
  show script idd-status
  record start rx
  run script idd-status
  show record
""",
        "delete": """delete script <name>

Delete a stored script from scripts.ini.

Example:
  delete script temporary-test
""",
        "options": """options [section]

Show mutable configuration values, their current values and descriptions.

Examples:
  options
  options connection
  options runtime
  options history
  options ui

Table headings and descriptions follow ui.language. Option identifiers remain unchanged because they are used by config.ini and 'set options'.
""",
        "set": """set options <name> <value>

Change one mutable option and persist it to config.ini.

Examples:
  set options port COM7
  set options timeout_ms 1000
  set options decode_rx false
  set options clean_output true
  set options language ru

Boolean values accept true/false, yes/no, on/off and 1/0. Fixed-choice options support Tab completion.
""",
        "pause": """pause <milliseconds>

Wait for the specified duration. Decimal values accept '.' or ','.

Examples:
  pause 100
  pause 250.5
""",
        "history": """history
history clear

'history' prints recent interactive commands.
'history clear' clears the persistent history file.

Interactive-only. Not allowed inside scripts.
Tab completion: history <TAB> -> clear
""",
        "clear": """clear | cls

Clear the interactive terminal. Does not change connection, config, scripts or history.
Interactive-only and not allowed inside scripts.
""",
        "help": """help [command]

Show general help or detailed help for one command/topic.

Examples:
  help
  help send
  help scripts
  help run
  help record
  help show

The language is selected by ui.language and applies to interactive and one-shot help.
""",
        "exit": """exit | quit

Leave the interactive shell. The serial connection is closed by the shell.
Not allowed inside scripts.
""",
    },
    "ru": {
        "connect": """connect

Открыть последовательное соединение с текущими параметрами раздела [connection]. config.ini не изменяется.

Примеры:
  connect
  status

При изменении параметров соединения через 'set options ...' активное соединение сначала закрывается.

Примеры временных startup-параметров:
  rtuforge --port COM7
  rtuforge --port COM7 --baudrate 19200 --parity N
  rtuforge --port /dev/ttyUSB0 --baudrate 115200 connect

Startup overrides действуют только в текущем процессе и никогда не изменяют config.ini. Они сохраняют приоритет даже после 'set options' для persistent connection option; после перезапуска без флага используется сохранённое значение.
""",
        "disconnect": """disconnect

Закрыть активное последовательное соединение. Безопасно выполнять и при уже закрытом соединении.
""",
        "ports": """ports

Показать порты, найденные pyserial. Команда не открывает порт.

Столбцы:
  Порт         Имя устройства, например COM4 или /dev/ttyUSB0
  Описание     Описание драйвера/устройства
  HWID         Аппаратный идентификатор от ОС
""",
        "status": """status

Показать реальное состояние соединения и текущие параметры без автоматического подключения.

Выводятся порт, скорость, формат, таймаут, режим CRC, расшифровка RX, чистый вывод и язык интерфейса.

Параметры соединения являются effective runtime значениями. Поля из startup overrides отмечаются [CLI]. Persistent значения config.ini показывает 'options connection'.
""",
        "paths": """paths

Показать активный каталог данных/home RTU Forge и абсолютные пути к config.ini, scripts.ini и истории.

Если пользовательский launcher установил RTUFORGE_HOME, пути не зависят от текущего рабочего каталога. Команда работает и до появления config.ini.
""",
        "scan": """scan [начало [конец]] [--timeout мс] [--function 01|02|03|04] [--address адрес]

Найти устройства Modbus RTU по slave ID — адресу устройства на общей шине. Допустимый диапазон slave ID: 1..247.

По умолчанию:
  диапазон     1..247
  функция      03 Read Holding Registers
  адрес        0
  quantity     1
  таймаут      runtime.scan_timeout_ms (по умолчанию 100 мс на устройство)

Используются только безопасные функции чтения 01, 02, 03 и 04. Устройство считается найденным, только если ответ имеет корректный CRC, совпадающий slave ID и ожидаемую функцию. Корректный Modbus exception response также означает, что устройство найдено.

Параметры:
  --timeout <мс>       Временный таймаут одного запроса; config.ini не изменяется.
  --function <01..04>  Функция чтения для probe-запроса.
  --address <адрес>    Десятичный адрес или HEX с префиксом 0x.

Примеры:
  scan
  scan 7
  scan 1 32 --timeout 200
  scan 1 32 --function 04
  scan 1 32 --function 03 --address 0x0065
  rtuforge scan -c

В обычном terminal прогресс занимает одну стабильную строку. Ctrl+C останавливает поиск и возвращает приглашение shell. В clean mode печатаются только найденные slave ID, по одному в строке. Scan всегда отправляет один корректный CRC и не изменяет runtime.crc_mode.
""",
        "send": """send [-d|--decode|-r|--raw] <hex bytes...>

Отправить один сырой Modbus RTU кадр и дождаться ответа.

Примеры:
  send 01 03 00 65 00 01
  send --decode 01 03 00 65 00 01
  send -r 01 06 20 00 00 02

Флаги расшифровки:
  -d, --decode   Принудительно расшифровать ответ этого send.
  -r, --raw      Не расшифровывать ответ этого send.

Если флаг не указан, используется режим, унаследованный от run script; иначе runtime.decode_rx. Явный флаг конкретного send имеет наивысший приоритет.

CRC задаётся отдельно через runtime.crc_mode:
  auto    Сохранить уже корректный CRC, иначе добавить автоматически.
  append  Всегда добавить CRC.
  none    Отправить байты ровно в введённом виде.

Чистый вывод задаётся runtime.clean_output. В one-shot режиме временно включается глобальным -c/--clean.
""",
        "add": """add script <name>

Интерактивная запись скрипта. Все введённые строки сохраняются до 'end script'.

Пример:
  add script read-basic
  send 01 03 00 65 00 01
  pause 100
  send --decode 01 03 00 66 00 01
  end script

Результат сохраняется в scripts.ini. Допустимые команды описаны в 'help scripts'.
""",
        "run": """run script <name> [-d|--decode|-r|--raw]

Выполнить сохранённый скрипт построчно.

Примеры:
  run script idd-status
  run script idd-status -r
  run script idd-status -d

Приоритет расшифровки:
  флаг отдельного send > флаг run script > runtime.decode_rx

Между строками действует runtime.inter_command_delay_ms; команда 'pause <ms>' добавляет собственную паузу.

Чистый one-shot вывод:
  rtuforge -c run script idd-status -r
  rtuforge run script idd-status -c -r

Глобальный -c/--clean не изменяет config.ini.
""",
        "scripts": """scripts | ls | list

Показать сохранённые скрипты. Скрипты являются последовательностями команд RTU Forge в scripts.ini.

Создание:
  add script read-basic
  send 01 03 00 65 00 01
  pause 100
  record start rx
  send 01 03 00 66 00 01
  show record
  record stop file capture.txt
  end script

Запуск / просмотр / удаление:
  run script read-basic
  show script read-basic
  delete script read-basic

Полезные команды внутри скриптов:
  send ...
  send --decode ...
  send --raw ...
  pause <ms>
  connect
  disconnect
  status
  ports
  run script <name> [-d|-r]
  scripts | ls | list
  show script <name>
  show record
  record start [all|rx]
  record stop <buffer|clipboard|file PATH>
  record status
  record cancel
  record script <name> ...
  options [section]
  set options <name> <value>
  help [command]

Запрещены внутри скриптов:
  add script ...
  history / history clear
  clear / cls
  exit / quit

Пустые строки и строки с '#' в начале игнорируются. Вложенные скрипты поддерживаются; циклических вызовов следует избегать.
""",
        "show": """show script <name>
show record

'show script <name>' показывает сохранённый скрипт без выполнения.
'show record' показывает текущий буфер записи и не останавливает запись.

Примеры:
  show script idd-status
  record start rx
  run script idd-status
  show record
""",
        "delete": """delete script <name>

Удалить сохранённый скрипт из scripts.ini.

Пример:
  delete script temporary-test
""",
        "options": """options [section]

Показать изменяемые параметры, текущие значения и описания.

Примеры:
  options
  options connection
  options runtime
  options history
  options ui

Заголовки и описания таблицы следуют ui.language. Имена параметров не переводятся, так как используются в config.ini и 'set options'.
""",
        "set": """set options <name> <value>

Изменить параметр и сохранить его в config.ini.

Примеры:
  set options port COM7
  set options timeout_ms 1000
  set options decode_rx false
  set options clean_output true
  set options language ru

Логические значения: true/false, yes/no, on/off, 1/0. Для параметров с фиксированным набором значений работает Tab.
""",
        "pause": """pause <milliseconds>

Подождать указанное количество миллисекунд. Для дробных значений принимаются '.' и ','.

Примеры:
  pause 100
  pause 250,5
""",
        "history": """history
history clear

'history' показывает последние интерактивные команды.
'history clear' очищает файл постоянной истории.

Работает только интерактивно и запрещён внутри скриптов.
Tab: history <TAB> -> clear
""",
        "clear": """clear | cls

Очистить интерактивный экран. Соединение, настройки, скрипты и история не изменяются.
Команда интерактивная и запрещена внутри скриптов.
""",
        "help": """help [command]

Показать общую или подробную справку.

Примеры:
  help
  help send
  help scripts
  help run
  help record
  help show

Язык задаётся ui.language и применяется к интерактивной и one-shot справке.
""",
        "exit": """exit | quit

Выйти из интерактивной консоли. Соединение закрывается оболочкой.
Команда запрещена внутри скриптов.
""",
    },
}

CLI_TEXT: dict[str, dict[str, str]] = {
    "en": {
        "description": "RTU Forge - Modbus RTU console and script runner",
        "config": "Path to settings INI",
        "scripts": "Path to scripts INI",
        "command": "One-shot command; omit for interactive shell",
        "help": "Show this help message and exit",
        "epilog": """examples:
  rtuforge
  rtuforge -c send 01 03 00 65 00 01
  rtuforge scan 1 32 --timeout 200
  rtuforge scan -c
  rtuforge run script idd-status -r
  rtuforge record script idd-status rx file capture.txt -r
  rtuforge help record
""",
    },
    "ru": {
        "description": "RTU Forge - консоль Modbus RTU и запуск скриптов",
        "config": "Путь к INI-файлу настроек",
        "scripts": "Путь к INI-файлу скриптов",
        "command": "One-shot команда; без команды запускается интерактивный режим",
        "help": "Показать эту справку и выйти",
        "epilog": """примеры:
  rtuforge
  rtuforge -c send 01 03 00 65 00 01
  rtuforge scan 1 32 --timeout 200
  rtuforge scan -c
  rtuforge run script idd-status -r
  rtuforge record script idd-status rx file capture.txt -r
  rtuforge help record
""",
    },
}

MESSAGES: dict[str, dict[str, str]] = {
    "en": {"unknown_help_topic": "Unknown help topic: {topic}"},
    "ru": {"unknown_help_topic": "Неизвестный раздел справки: {topic}"},
}


def help_topics() -> tuple[str, ...]:
    return tuple(HELP["en"].keys())


def interactive_help(language: str | None) -> str:
    return GENERAL_HELP[normalize_language(language)]


def command_help(language: str | None, topic: str) -> str | None:
    return HELP[normalize_language(language)].get(topic)


def cli_text(language: str | None) -> dict[str, str]:
    return CLI_TEXT[normalize_language(language)]


def message(language: str | None, key: str, **values: str) -> str:
    template = MESSAGES[normalize_language(language)].get(key, MESSAGES["en"][key])
    return template.format(**values)
