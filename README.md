# RTU Forge: установка, запуск и справка

Единая точка входа для RTU Forge, Stand Forge, Bionic Immitator и Hisense Aircon. **Рабочая ветка: `main`.** Старое полное содержимое README сохранено в [docs/REFERENCE-LEGACY.md](docs/REFERENCE-LEGACY.md), чтобы не потерялись параметры команд и технические детали.

> **Порядок:** установить `uv` → установить Python 3.11 или новее → получить код из `main` → выполнить `setup` → проверить команды → настроить RS-485 и только затем работать с оборудованием. Установщик не требует прав администратора.

## 1. Подготовка среды: uv и Python

`uv` — менеджер Python, окружений и пакетов от Astral. Отдельный системный Python **не обязателен**: `uv python install` устанавливает управляемую версию Python.

### Windows 10/11 (PowerShell)

Откройте PowerShell обычным пользователем:

```powershell
irm https://astral.sh/uv/install.ps1 | iex
```

Закройте и снова откройте PowerShell (для обновления PATH), затем:

```powershell
uv --version
uv python install 3.11
uv python list --only-installed
```

Если команда `uv` не найдена, перезапустите терминал и проверьте PATH. Не отключайте защиту PowerShell ради установки. При ограничениях корпоративной сети см. [официальные варианты установки uv](https://docs.astral.sh/uv/getting-started/installation/).

### Linux (bash)

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

Откройте новый терминал или подключите путь из сообщения установщика, затем:

```bash
uv --version
uv python install 3.11
uv python list --only-installed
```

Для установки потребуется доступ к сети; `curl` должен быть установлен. Не запускайте `setup.sh` с `sudo`.

### Проверка Git

```bash
git --version
```

Если Git не найден, установите [Git](https://git-scm.com/downloads) под свою ОС. `python --version` в системном PATH **может не показывать** Python, установленный через uv; для разработки проверяйте `uv run python --version` из каталога проекта.

## 2. Клонирование актуального проекта

**Windows PowerShell:**

```powershell
git clone https://github.com/xels79/rtu-forge.git
cd rtu-forge
git switch main
git pull --ff-only origin main
```

**Linux:**

```bash
git clone https://github.com/xels79/rtu-forge.git
cd rtu-forge
git switch main
git pull --ff-only origin main
```

Не используйте старые инструкции с `feature/standforge`: функциональность всех рабочих веток объединена в `main`.

## 3. Установка приложения

### Windows

Из корня репозитория:

```powershell
.\setup.ps1
```

Откройте **новый PowerShell** и проверьте:

```powershell
rtuforge paths
rtuforge --help
standforge --help
bionic-immitator --help
```

Установщик делает editable `uv tool` установку, настраивает пользовательские PATH и RTUFORGE_HOME. Данные по умолчанию: `%APPDATA%\RTUForge`. При наличии существующих `config.ini`, `scripts.ini` и истории они не перезаписываются. Варианты: `.\setup.ps1 -NoShortcut` и `.\setup.ps1 -DataDir .\rtu-data -WorkingDir .\rs485`.

### Linux

```bash
chmod +x setup.sh
./setup.sh
```

Затем откройте новый терминал:

```bash
rtuforge paths
rtuforge --help
standforge --help
bionic-immitator --help
```

Установщик размещает виртуальное окружение и исполняемые файлы в каталогах пользователя, не использует `sudo`. Если команда не найдена, проверьте `$HOME/.local/bin` в PATH. Дополнительно: `./setup.sh --desktop`, `./setup.sh --data-dir ~/rtu-data --working-dir ~/rs485`.

### Режим разработчика (без пользовательского установщика)

```bash
uv sync --extra dev
uv run python --version
uv run --extra dev pytest -q
uv run rtuforge --home .
```

На Windows для Bionic: `uv run bionic-immitator --home .\bionic-data --no-controller`. На Linux: `uv run bionic-immitator --home ./bionic-data --no-controller`.

## 4. Что запускать

| Программа | Команда | Что делает | Справка |
|---|---|---|---|
| RTU Forge | `rtuforge` | Modbus RTU, сканирование, HEX, сценарии и запись обмена | [HELP-RTUFORGE.md](docs/HELP-RTUFORGE.md) |
| Stand Forge | `standforge` | Релейная плата, аналоговые каналы, IDD, полив и давление | [HELP-STANDFORGE.md](docs/HELP-STANDFORGE.md) |
| Bionic Immitator | `bionic-immitator --home ./bionic-data --no-controller` | Физический имитатор Bionic Mini, запуск без контроллера | [HELP-BIONIC.md](docs/HELP-BIONIC.md) |
| Hisense Aircon | `rtuforge aircon --demo` | Консоль кондиционера Hisense через ONOKOM, демонстрация | [HELP-AIRCON.md](docs/HELP-AIRCON.md) |

Для запуска с оборудованием сначала настройте COM/`/dev/tty*`, скорость, чётность и адреса устройств. **Не запускайте одновременно два независимых RS-485 master на одной рабочей шине.** Проверка программного ответа реле не гарантирует фактическое положение клапана.

## 5. Практические команды

**RTU Forge:**

```powershell
rtuforge --port COM7 --baudrate 9600
rtuforge --port COM7 --baudrate 9600 send 01 03 00 65 00 01
```

**Stand Forge, сначала диагностика:**

```powershell
standforge --port COM7 --baudrate 9600
```

В интерактивной консоли:

```text
idd 7 status
idd all monitor
ai
pressure
start check 1 1 broth 29
```

`start check` не включает насосы и не переключает реле. После настройки `stand.ini` и проверок оборудования оператор может применять `start step 1 1 broth 29` с отдельным Enter перед каждым шагом; `stop` завершает цикл, `emergency-stop` снимает пуски. **Частота в Гц**, а не в процентах.

**Bionic Immitator:**

```powershell
bionic-immitator --home .\bionic-data --no-controller
bionic-immitator --home .\bionic-data
```

`--no-controller` исключает использование USB №1 для безопасного знакомства. Настройки и состояние имитатора сохраняются отдельно.

**Hisense Aircon:**

```powershell
rtuforge aircon --demo
rtuforge --port COM7 --baudrate 9600 --bytesize 8 --parity N --stopbits 2 aircon diag
rtuforge --port COM7 --baudrate 9600 --bytesize 8 --parity N --stopbits 2 aircon
```

`aircon diag` читает регистры, `--demo` не требует оборудования. Номера COM здесь примеры, а не фиксированные настройки.

## 6. Обновление без потери настроек

```bash
git switch main
git pull --ff-only origin main
```

После обновления повторно выполните `.\setup.ps1` (Windows) или `./setup.sh` (Linux). Для пользовательских параметров используйте собственные `config.ini`, `stand.ini`, `aircon.ini` и `bionic-immitator.ini`. Установщик не заменяет существующие пользовательские файлы; **не копируйте примеры поверх работающих конфигураций без резервной копии**.

## 7. Подробные справочники

- [Подготовка среды и установка](docs/HELP-ENVIRONMENT.md)
- [RTU Forge и скрипты](docs/HELP-RTUFORGE.md)
- [Stand Forge, IDD, полив, аварийная остановка](docs/HELP-STANDFORGE.md)
- [Bionic Immitator и Pulsar](docs/HELP-BIONIC.md)
- [Hisense Aircon](docs/HELP-AIRCON.md)
- [Полное руководство по поливу](IRRIGATION.md)
- [Полное руководство Stand Forge](STANDFORGE.md)
- [Полное руководство Bionic](docs/BIONIC-IMMITATOR-USER-GUIDE.md)
- [Полное руководство Aircon](docs/AIRCON-RU.md)
- [Архив прежнего подробного README](docs/REFERENCE-LEGACY.md)

Официальная документация: [uv](https://docs.astral.sh/uv/), [Python](https://www.python.org/), [Git](https://git-scm.com/). Требуется Python 3.11+; проект использует `pyserial`, `rich` и `prompt-toolkit`.
