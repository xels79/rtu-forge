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
  send [-d|--decode|-r|--raw] <hex...>
                                  Send one Modbus RTU frame and print response
  add script <name>               Capture commands until 'end script'
  run script <name>               Run a stored script
  scripts | ls | list             List stored scripts
  show script <name>              Show script contents
  delete script <name>            Delete a stored script
  options [section]               Show mutable options
  set options <name> <value>      Change and persist an option
  pause <ms>                      Sleep; useful inside scripts
  history                         Show recent interactive commands
  history clear                   Clear persistent history
  clear | cls                     Clear the terminal
  help [command]                  Show general or command-specific help
  exit | quit                     Leave the shell

Use 'help scripts' for script syntax and allowed commands.
Use 'help send' for CRC and response decoding options.
""",
    "ru": """Команды:
  connect                         Подключиться с текущими параметрами соединения
  disconnect                      Закрыть последовательное соединение
  ports                           Показать доступные последовательные порты
  status                          Показать состояние и текущие параметры
  send [-d|--decode|-r|--raw] <hex...>
                                  Отправить один Modbus RTU кадр и вывести ответ
  add script <name>               Начать запись скрипта до команды 'end script'
  run script <name>               Запустить сохранённый скрипт
  scripts | ls | list             Показать список скриптов
  show script <name>              Показать содержимое скрипта
  delete script <name>            Удалить скрипт
  options [section]               Показать изменяемые параметры
  set options <name> <value>      Изменить и сохранить параметр
  pause <ms>                      Пауза; удобно внутри скриптов
  history                         Показать историю интерактивных команд
  history clear                   Очистить сохранённую историю
  clear | cls                     Очистить экран
  help [command]                  Общая или подробная справка по команде
  exit | quit                     Выйти из консоли

Для синтаксиса скриптов и допустимых команд: help scripts
Для CRC и расшифровки ответа: help send
""",
}


HELP: dict[str, dict[str, str]] = {
    "en": {
        "connect": """connect

Open the serial connection using the current connection options.

The command does not change config.ini. If already connected, the transport keeps the existing connection.

Example:
  connect

See also:
  status
  disconnect
  options connection
""",
        "disconnect": """disconnect

Close the active serial connection. It is safe to call when already disconnected.

Example:
  disconnect
""",
        "ports": """ports

List serial ports detected by pyserial. The command does not open any port.

Columns:
  Port         Device name such as COM4 or /dev/ttyUSB0
  Description  Driver/device description
  HWID         Hardware identifier reported by the OS

Example:
  ports
""",
        "status": """status

Show the real connection state together with the active configuration.

Displayed values include port, baud rate, serial format, timeout and CRC mode. The command never auto-connects.

Example:
  status
""",
        "send": """send [-d|--decode|-r|--raw] <hex bytes...>

Send one raw Modbus RTU frame and wait for a response.

Examples:
  send 01 03 00 65 00 01
  send --decode 01 03 00 65 00 01
  send -d 01 06 20 00 00 02
  send --raw 01 03 00 65 00 01

Response decoding:
  -d, --decode   Force full Modbus response decoding for this send.
  -r, --raw      Suppress decoding for this send and keep raw RX only.

If neither flag is present, runtime.decode_rx from config.ini is used. These flags belong to RTU Forge and are never transmitted as Modbus bytes.

CRC handling is controlled separately by runtime.crc_mode:
  auto    preserve a valid supplied CRC, otherwise append one
  append  always append CRC
  none    send bytes exactly as entered

The raw TX/RX line remains the primary representation even when decoding is enabled.
""",
        "add": """add script <name>

Start interactive script capture. Every entered line is stored until 'end script'.

Example:
  add script read-basic
  send 01 03 00 65 00 01
  pause 100
  send --decode 01 03 00 66 00 01
  end script

The script is stored in scripts.ini. For supported commands, comments, delays and restrictions use:
  help scripts
""",
        "run": """run script <name>

Run a stored script line by line.

Example:
  run script idd-status

A configured runtime.inter_command_delay_ms delay is inserted between script lines. Explicit 'pause <ms>' commands add additional delays.

A script may call another script with 'run script <name>'. Avoid cyclic script calls.
""",
        "scripts": """scripts | ls | list

List stored scripts. Scripts are kept in scripts.ini and are ordinary RTU Forge command sequences.

Create a script interactively:
  add script read-basic
  send 01 03 00 65 00 01
  pause 100
  send --decode 01 03 00 66 00 01
  # comments and empty lines are allowed
  end script

Run it:
  run script read-basic

Inspect or remove it:
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
  run script <name>
  scripts | ls | list
  show script <name>
  options [section]
  set options <name> <value>
  help [command]

Not allowed inside scripts:
  add script ...
  history / history clear
  clear / cls
  exit / quit

Lines beginning with '#' and empty lines are ignored. The configured runtime.inter_command_delay_ms delay is applied between stored lines; 'pause <ms>' is an explicit additional delay.
""",
        "show": """show script <name>

Print every stored line of a script without running it.

Example:
  show script idd-status
""",
        "delete": """delete script <name>

Delete a stored script from scripts.ini.

Example:
  delete script temporary-test
""",
        "options": """options [section]

Show mutable configuration values and descriptions.

Examples:
  options
  options connection
  options runtime
  options ui

Available sections depend on config.ini. Tab completion shows section names.
""",
        "set": """set options <name> <value>

Change one mutable option and persist it to config.ini.

Examples:
  set options port COM7
  set options timeout_ms 1000
  set options decode_rx false
  set options language ru

Changing a connection option while connected forces a disconnect. Options with fixed choices support Tab completion for values.
""",
        "pause": """pause <milliseconds>

Wait for the specified duration. Decimal values accept either '.' or ','.

Examples:
  pause 100
  pause 250.5

This is most useful inside scripts when a device needs more time than runtime.inter_command_delay_ms.
""",
        "history": """history
history clear

'history' prints recent interactive commands.
'history clear' clears the persistent history file.

Tab completion:
  history <TAB>  -> clear

History commands are interactive-only and are not allowed inside scripts.
""",
        "clear": """clear | cls

Clear the interactive terminal. Connection, config, scripts and command history are not changed.

This command is interactive-only.
""",
        "help": """help [command]

Show general help or detailed help for one command.

Examples:
  help
  help send
  help scripts
  help history

The help language is selected by ui.language in config.ini:
  set options language en
  set options language ru

The same localized command help works in one-shot mode:
  uv run rtuforge help scripts
""",
        "exit": """exit | quit

Leave the interactive shell and close the serial connection.

This command is not allowed inside scripts.
""",
    },
    "ru": {
        "connect": """connect

Открыть последовательное соединение с текущими параметрами из config.ini.

Команда не меняет настройки. Если соединение уже открыто, существующее соединение сохраняется.

Пример:
  connect

См. также:
  status
  disconnect
  options connection
""",
        "disconnect": """disconnect

Закрыть активное последовательное соединение. Команду можно безопасно выполнять и при уже закрытом соединении.

Пример:
  disconnect
""",
        "ports": """ports

Показать последовательные порты, найденные pyserial. Ни один порт при этом не открывается.

Столбцы:
  Port         Имя устройства, например COM4 или /dev/ttyUSB0
  Description  Описание драйвера/устройства
  HWID         Аппаратный идентификатор от ОС

Пример:
  ports
""",
        "status": """status

Показать реальное состояние соединения и текущие параметры конфигурации.

Выводятся порт, скорость, формат последовательного порта, timeout и режим CRC. Команда никогда не выполняет автоматическое подключение.

Пример:
  status
""",
        "send": """send [-d|--decode|-r|--raw] <hex bytes...>

Отправить один сырой Modbus RTU кадр и дождаться ответа.

Примеры:
  send 01 03 00 65 00 01
  send --decode 01 03 00 65 00 01
  send -d 01 06 20 00 00 02
  send --raw 01 03 00 65 00 01

Расшифровка ответа:
  -d, --decode   Принудительно вывести полную доступную расшифровку Modbus ответа для этой команды.
  -r, --raw      Не расшифровывать этот ответ, вывести только сырой RX.

Если флаг не указан, используется runtime.decode_rx из config.ini. Флаги относятся только к RTU Forge и никогда не отправляются в Modbus кадре.

CRC передачи задаётся отдельно параметром runtime.crc_mode:
  auto    сохранить уже корректный CRC, иначе добавить CRC автоматически
  append  всегда добавить CRC
  none    отправить байты ровно в введённом виде

Сырой TX/RX остаётся основным представлением даже при включённой расшифровке.
""",
        "add": """add script <name>

Начать интерактивную запись скрипта. Каждая введённая строка сохраняется до команды 'end script'.

Пример:
  add script read-basic
  send 01 03 00 65 00 01
  pause 100
  send --decode 01 03 00 66 00 01
  end script

Скрипт сохраняется в scripts.ini. Полный список допустимых команд, комментарии и паузы описаны в:
  help scripts
""",
        "run": """run script <name>

Выполнить сохранённый скрипт построчно.

Пример:
  run script idd-status

Между строками автоматически добавляется пауза runtime.inter_command_delay_ms. Команды 'pause <ms>' добавляют собственную дополнительную паузу.

Скрипт может вызвать другой скрипт через 'run script <name>'. Не создавайте циклические вызовы скриптов.
""",
        "scripts": """scripts | ls | list

Показать список сохранённых скриптов. Скрипты находятся в scripts.ini и состоят из обычных команд RTU Forge.

Создание скрипта в интерактивном режиме:
  add script read-basic
  send 01 03 00 65 00 01
  pause 100
  send --decode 01 03 00 66 00 01
  # комментарии и пустые строки разрешены
  end script

Запуск:
  run script read-basic

Просмотр и удаление:
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
  run script <name>
  scripts | ls | list
  show script <name>
  options [section]
  set options <name> <value>
  help [command]

Запрещены внутри скриптов:
  add script ...
  history / history clear
  clear / cls
  exit / quit

Пустые строки и строки, начинающиеся с '#', игнорируются. Между сохранёнными строками действует runtime.inter_command_delay_ms; команда 'pause <ms>' задаёт дополнительную явную паузу.
""",
        "show": """show script <name>

Показать все сохранённые строки скрипта без его выполнения.

Пример:
  show script idd-status
""",
        "delete": """delete script <name>

Удалить сохранённый скрипт из scripts.ini.

Пример:
  delete script temporary-test
""",
        "options": """options [section]

Показать изменяемые параметры конфигурации и их описание.

Примеры:
  options
  options connection
  options runtime
  options ui

Доступные секции берутся из config.ini. Tab показывает имена секций.
""",
        "set": """set options <name> <value>

Изменить один параметр и сохранить его в config.ini.

Примеры:
  set options port COM7
  set options timeout_ms 1000
  set options decode_rx false
  set options language ru

Изменение параметра соединения при активном подключении автоматически разрывает соединение. Для параметров с фиксированным набором значений Tab предлагает варианты.
""",
        "pause": """pause <milliseconds>

Подождать указанное количество миллисекунд. В дробных значениях принимаются '.' и ','.

Примеры:
  pause 100
  pause 250,5

Особенно полезно в скриптах, если устройству нужна пауза больше runtime.inter_command_delay_ms.
""",
        "history": """history
history clear

'history' показывает последние интерактивные команды.
'history clear' очищает файл сохранённой истории.

Автодополнение:
  history <TAB>  -> clear

Команды истории работают только в интерактивном режиме и запрещены внутри скриптов.
""",
        "clear": """clear | cls

Очистить экран интерактивной консоли. Соединение, настройки, скрипты и история команд не изменяются.

Команда доступна только в интерактивном режиме.
""",
        "help": """help [command]

Показать общую справку или подробную справку по одной команде.

Примеры:
  help
  help send
  help scripts
  help history

Язык справки задаётся параметром ui.language в config.ini:
  set options language en
  set options language ru

Та же локализованная справка работает в one-shot режиме:
  uv run rtuforge help scripts
""",
        "exit": """exit | quit

Выйти из интерактивной консоли и закрыть последовательное соединение.

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
  rtuforge shell
  rtuforge send --decode 01 03 00 65 00 01
  rtuforge run script read-basic
  rtuforge help scripts
  rtuforge set options language ru
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
  rtuforge shell
  rtuforge send --decode 01 03 00 65 00 01
  rtuforge run script read-basic
  rtuforge help scripts
  rtuforge set options language en
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
