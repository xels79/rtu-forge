# Справка: RTU Forge

**Назначение:** консоль для ручных Modbus RTU команд, исследования RS-485, чтения и записи фреймов, сканирования адресов и запуска именованных сценариев. Не путать с `standforge` (аппаратные команды стенда).

## Старт
```powershell
rtuforge paths
rtuforge --help
rtuforge
rtuforge --port COM7 --baudrate 9600
```
На Linux вместо COM-порта укажите нужный `/dev/ttyUSB0` или `/dev/ttyACM0`. Параметры порта должны соответствовать устройству.

## Примеры
```powershell
rtuforge --port COM7 --baudrate 9600 send 01 03 00 65 00 01
rtuforge --port COM7 --baudrate 9600 scan 1 32 --timeout 100
rtuforge help scripts
rtuforge help record
```

## Скрипты и запись
Именованные сценарии находятся в `scripts.ini`. Поддерживается `rtuforge run script <имя>`, а также запись обмена. Для справки в консоли используйте `help scripts`, `help record`, `help send`. Режим `-c` упрощает вывод, `-r` включает декодирование там, где это предусмотрено.

## Типичные ошибки
Отсутствует порт: проверьте `rtuforge paths`, COM/tty и права Linux на последовательный порт. Ошибка CRC или тайм-аут: проверьте скорость, чётность, slave ID, проводку, преобразователь и единственного master на шине. Для проверки без оборудования пользуйтесь `--help` и тестами.

Полное описание флагов и сценариев: [архивный подробный README](REFERENCE-LEGACY.md). Начало работы: [главный README](../README.md).

## Свет Waveshare AO

Встроенная команда `light`, отдельная программа не нужна. Используйте `help light`, `light status`, `light 1 100`, `light all 0`. Настройки адреса и каналов в `config.ini`; подробности в [HELP-LIGHT.md](HELP-LIGHT.md).
