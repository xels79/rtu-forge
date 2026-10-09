# Stand Forge

## Автоматический полив и русская диагностика

Добавлены `idd <7|8> status|setup|frequency <Гц>|monitor`, явная настройка
`idd <7|8> configure --confirm`, `ai [types]`, `pressure`, `test-pressure low/high`,
`start <стеллаж> <ярус> broth <Гц>`, `stop`, `emergency-stop`,
`test-pressure stop` и `reset fault`. Подробная русская справка: `help idd`,
`help ai`, `help start`, `help stop`, `help pressure`, `help test-pressure`.
Tab дополняет команды и настройки.

Для IDD222M21E используется документированная обратная связь mini PLUS:
`idd 7 feedback` / `idd 8 feedback` только читает PA02, PA27 (текущая ошибка)
и PA28 (STOP/RUN). Пуск/останов остаётся через реле 32/31; частота — RS485.
Выбор этой карты для контроллера и ограничения старых прошивок описаны в IRRIGATION.md.

`idd all setup` и `idd all monitor` последовательно проверяют связь и доступные
данные обоих приводов. Чтение monitor не требует флагов подтверждения; неизвестные
RUN/STOP и текущая авария явно показываются как «неизвестно». Ошибка одного IDD
не пропускает проверку другого. Запись настроек и пуск этими командами не выполняются.

Для проверки перед пуском выполните `start check 1 1 broth 29`: команда читает
сигналы AI, реле и выбранный IDD, показывает расчёт частоты и все причины
блокировки, не включает насосы и не записывает настройки. Исправные датчики
сами по себе не подтверждают STOP/текущую аварию частотника.

Задания IDD и полива вводятся в Гц. Максимум Pb05 выводится при проверке и
задании частоты; для IDD 7 минимум мотора `drive7_min_hz=24`.
При Pb05=45 Гц/Pb06=20 Гц допустимо 24..45 Гц. Старые сценарии с процентами
нужно обновить вручную; команды аналоговых выходов `output` сохраняют проценты.

Пуск работает в отдельном цикле, STOP остаётся доступен во время запуска.
Ручные изменения при активном поливе/FAULT запрещены. Автопуск отключён до
проверки входов, обратной связи IDD, единиц давления, адреса реле, гидравлики
и аппаратных защит. Все новые параметры `[irrigation]` и пример конфигурации
описаны в [IRRIGATION.md](IRRIGATION.md). Состояния и снятие пуска не заменяют
аппаратный аварийный останов.

Следующие прежние команды относятся к **имитационному тестовому стенду**.
На поливной установке реле 1..8 имеют другое назначение. `reset all` выключает
все реле сразу; для полива используется `stop`, который оставляет клапан яруса
открытым до подтверждённого останова привода. AI устройства 6 — настоящие входы;
аналоговые выходы ниже используются только для имитации и сохранены без изменения.

Stand Forge is a small test-bench console built on RTU Forge's existing serial transport and configuration.

It controls two Waveshare Modbus RTU devices:

- Relay board: manual control of channels 1..32; four tanks mapped to the first eight channels, two relays per tank.
- 8-channel analog output board: first four channels mapped to temperature, humidity, low pressure and high pressure.

## Tank commands

Relay mapping:

- Tank 1 -> relay 1 (lower float), relay 2 (upper float)
- Tank 2 -> relay 3, relay 4
- Tank 3 -> relay 5, relay 6
- Tank 4 -> relay 7, relay 8

States:

- `empty` -> both relays off
- `middle` -> lower relay on, upper relay off
- `full` -> both relays on

Examples:

```text
standforge tank 1 empty
standforge tank 1 middle
standforge tank 1 full
standforge tank 4 full
```

The two relays are written in one Modbus FC0F request.

## Manual relay commands

Switch selected relay channels (1..32) on or off:

```text
standforge on 1
standforge off 1
standforge of 1
standforge on 1 3 8
standforge off 2 4
standforge on 1 16 32
standforge off 32
```

`of` is an alias for `off`. The same commands work at the `stand>` prompt.
Channels 1..32 map to coil addresses 0..31 at the configured relay device ID.
Each selected channel is written separately using Modbus FC0F with quantity 1;
other channels are left unchanged. All channel numbers are validated before
connecting or sending, and repeated channels are written only once. If a write
fails, the command stops and reports the error; earlier successful writes remain applied.

## Analog output commands

Channel mapping:

1. temperature
2. humidity
3. pressure-low
4. pressure-high

Examples:

```text
standforge output temperature 50
standforge output humidity 75
standforge output pressure-low 25
standforge output pressure high 80
```

Percent is scaled into the configured physical output range.

Supported ranges:

- `0-20ma` -> 0..20000 uA
- `4-20ma` -> 4000..20000 uA
- `0-10v` -> 0..10000 mV


## Reset

Reset the complete bench to its initial state:

```text
standforge reset
standforge reset all
```

This switches all relays on the configured relay device off in one command,
including channels 9..32, and sets all four tanks to `empty`. It then sets the
first four analog outputs to `0%`. For a `4-20ma` range, `0%` means 4000 uA rather than 0 uA.

The relay reset uses Waveshare's FC05 command at coil address `0x00FF` with
value `0x0000`, as documented in the
[Waveshare relay protocol](https://www.waveshare.com/wiki/Modbus_RTU_Relay_16CH).
For relay ID 1, the complete request is `01 05 00 FF 00 00 FD FA`; other IDs use
their own calculated CRC. The response must echo the request with a valid CRC.

The command attempts every reset operation even if one device fails, then reports any incomplete items.

## Configuration

Stand Forge reuses RTU Forge's `config.ini` and `RTUFORGE_HOME` for serial settings.

Stand-specific settings are stored in `stand.ini` in the same home directory:

```ini
[devices]
relay_address = 1
output_address = 2

[output]
range = 0-20ma
```

Change them interactively:

```text
set relay-id 1
set output-id 2
set output-range 4-20ma
```

Or temporarily for one launch:

```bash
standforge --relay-id 5 --output-id 6 --output-range 0-10v status
```

Serial overrides are the same as RTU Forge:

```bash
standforge --port COM7 --baudrate 9600 tank 1 full
```

## Interactive shell

Run:

```bash
standforge
```

Prompt:

```text
stand>
```

The shell has persistent history and Tab completion.

Useful commands:

```text
tank <1..4> <empty|middle|full>
on <1..32> [<1..32> ...]
off <1..32> [<1..32> ...]  (alias: of)
output <temperature|humidity|pressure-low|pressure-high> <0..100>
reset [all]
set <relay-id|output-id|output-range> <value>
connect
disconnect
ports
status
paths
help
exit
```

Hardware access is not exercised by unit tests. Tests use a fake transport and validate the generated Modbus frames and responses.
