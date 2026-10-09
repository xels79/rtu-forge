# Optional pressure-monitored irrigation

This is a **work-in-progress, hardware-disabled** state-machine implementation.
The existing `standforge` manual commands remain unchanged. No automatic
start command is registered until the hardware adapter has been commissioned.

## Intended command (not implemented yet)

`standforge start 1 1 broth 35` (rack 1, tier 1, 35% of configured VFD maximum).

## Mapping

- Rack/tier valve: 1/1=9, 1/2=10, 1/3=11, 2/1=12, 2/2=13, 2/3=14.
- Booster: relay 1.
- Broth selector: relay 23.
- Pump selector: relay 19 or 20 (requires an explicit choice).
- VFD RTU 7: terminal-start relay 32. RTU 8: terminal-start relay 31.
- AI module RTU 6: AI1 low pressure (0..6 bar); AI2 high pressure (0..100 bar).
- VFD frequency is to be set over RS485, startup is by FWD terminal.
- No tank level checks.

## States

IDLE -> VALVES -> BOOST -> STARTING -> RUNNING -> STOPPING -> IDLE.
If pressure rises too high, fails to rise, falls too low, or feedback fails:
STOPPING -> FAULT.

Normal STOP opens the drive-start contact and drops the booster/selector
but keeps the rack valve open until BOTH VFD actual output frequency is
near zero AND VFD RUN is false. With no valid feedback, the rack valve stays
open and the controller latches FAULT. Hardware emergency pressure/stop
interlocks are required separately.

## Commissioning blockers

No live control is exposed because the following have not been established:

1. Exact Waveshare 8CH **analog input** model and its Modbus input register
   map; calibration and 4-20mA/voltage scaling of all sensors.
2. Verified VFD runtime output-frequency and RUN/fault registers plus
   frequency scaling and setpoint readback.
3. Relay board Modbus slave ID, physical normally-open contact arrangement,
   selector relay 19 vs 20 for each pump, and independently wired E-stop.
4. Safe pressure thresholds and operating pressure units (the requested
   value '60' has not been independently confirmed as bar).
5. Behavior on controller/PC/serial power loss, valve opening timing,
   pressure relief and pump stop-time validation.

The code should be tested with a fake hardware adapter and then a supervised,
de-energized bench before it is connected to a live water system.

## Реализованные команды консоли (русская справка)

- `help idd` — справка INNOVERT IDD MINI.
- `idd 7 status`, `idd 8 status` — чтение Pb00/Pb01/Pb02/Pb05/Pb06/Pd15/Pd16.
- `idd 7 setup`, `idd 8 setup` — безопасная проверка Pb01=5 и Pb02=1, **без записи**.
- `idd 7 frequency 35`, `idd 8 frequency 35` — вычисление частоты от Pb05, проверка Pb06, запись регистра 0x2001 по RS485.
- `help ai`, `ai`, `ai types` — чтение входов AI1..AI4 на адресе 6.
- `help start` — причина блокировки автоматического пуска до калибровки и проверки обратной связи привода.

Датчики: AI1 ПД100-ДИ0,6-171-0,5 (0..6 бар), AI2 ПД100-ДИ10,0-111-0,5 (0..100 бар), выходы 4..20 мА. Масштабирование тока в бар вынесено в `stand_sensors.py`. Нельзя применять формулу к сырому регистру AI без проверки его единиц. Модуль Stand Forge ранее использовал аналоговые **выходы** для имитации датчиков. Эти выходы остаются тестовыми и не подменяют настоящие входы устройства с адресом 6.

## Ограничения

Контроллер полива пока самостоятельный модуль `IrrigationController`, не связанный с рабочими командами запуска. Команда `start` преднамеренно не запускает оборудование, пока не подтверждены масштабирование AI1/AI2, адреса RUN/output Hz/fault IDD, канал реле и аппаратная аварийная защита. Пользовательские команды проверки параметров и ручное управление доступны отдельно. Тесты написаны, но в подключении GitHub не запускались.

## Подтверждённая карта подключения (со слов владельца оборудования)

Waveshare Relay 32CH, адрес RTU релейной платы пока не сообщён. Номера ниже — **физические номера каналов реле**, не адреса регистров Modbus.

| Канал | Устройство / действие |
|---|---|
| 1 | Подпорный насос НВД |
| 9 | Клапан ВД, стеллаж 1, ярус 1 |
| 10 | Клапан ВД, стеллаж 1, ярус 2 |
| 11 | Клапан ВД, стеллаж 1, ярус 3 |
| 12 | Клапан ВД, стеллаж 2, ярус 1 |
| 13 | Клапан ВД, стеллаж 2, ярус 2 |
| 14 | Клапан ВД, стеллаж 2, ярус 3 |
| 15 | Вентилятор стеллажа 1 (включён в рабочем режиме) |
| 16 | Вентилятор стеллажа 2 (включён в рабочем режиме) |
| 17 | Насос БСО1 → БП (пуск по БСО1 max, останов по min; автоматизация уровней отложена) |
| 18 | Насос БСО2 → БП (пуск по БСО2 max, останов по min; автоматизация уровней отложена) |
| 19 | Клапан выбора НВД 1 |
| 20 | Клапан выбора НВД 2 |
| 21 | Клапан выбора осмотической воды при промывке |
| 22 | Клапан водопровода → БО (управление по уровням БО отложено) |
| 23 | Клапан выбора бульона, включён перед поливом и выключен после |
| 31 | Сухой контакт пуска IDD MINI Modbus RTU 8 |
| 32 | Сухой контакт пуска IDD MINI Modbus RTU 7 |

**Аналоговые входы:** Waveshare Analog Input 8CH, RTU **6**, AI1 — НВД ПД100-ДИ0,6-171-0,5 (0–6 бар), AI2 — ДВД ПД100-ДИ10,0-111-0,5 (0–100 бар). AI3/AI4 — температура/влажность (их чтение не входит в защиту полива).

**Частотники:** INNOVERT IDD MINI адреса **7** и **8**. Ранее проверено на устройстве 7: Pb01=5, Pb02 требовал смены с 2 на 1; после исправления пуск FWD работал. Для устройства 8 требуется собственная проверка параметров и диапазонов.

Для полива не включать реле 17, 18, 21, 22; они относятся к другим процессам. При рабочем режиме стеллажей предусмотреть реле 15/16, но без подтверждения области действия «рабочего режима» не смешивать вентиляторы с аварийным остановом гидравлики. Насосы БСО и поплавковые датчики не проверяются в этом сценарии.
