# Справка: подготовка среды и обновление

Это руководство рассчитано на Windows PowerShell и Linux bash; все команды выполнять под обычным пользователем.

## Что понадобится
- Git, доступ в интернет при первой установке, свободный последовательный порт для работы с оборудованием
- `uv` для установки Python и зависимостей
- Python **3.11 или новее**, установленный через uv

## Windows
```powershell
irm https://astral.sh/uv/install.ps1 | iex
```
Откройте новый терминал:
```powershell
uv --version
uv python install 3.11
git clone https://github.com/xels79/rtu-forge.git
cd rtu-forge
git switch main
.\setup.ps1
```
Ещё раз откройте PowerShell:
```powershell
rtuforge paths
rtuforge --help
standforge --help
bionic-immitator --help
```
Пользовательская папка по умолчанию: `%APPDATA%\RTUForge`. Для изменения: `.\setup.ps1 -DataDir .\rtu-data -WorkingDir .\rs485`.

## Linux
```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```
Перезапустите терминал:
```bash
uv --version
uv python install 3.11
git clone https://github.com/xels79/rtu-forge.git
cd rtu-forge
git switch main
chmod +x setup.sh
./setup.sh
rtuforge paths
```
Без sudo; при необходимости добавьте `~/.local/bin` в PATH.

## Разработка и тесты
```bash
uv sync --extra dev
uv run python --version
uv run --extra dev pytest -q
```

## Обновление
```bash
git switch main
git pull --ff-only origin main
```
Затем повторите `setup.ps1` / `setup.sh`. Старые инструкции с `feature/standforge` больше не использовать. Не затирайте действующие INI файлами из `examples`.

## Где что лежит
`config.ini` — RTU Forge; `scripts.ini` — сценарии; `stand.ini` — управление стендом; `aircon.ini` — кондиционер; `bionic-immitator.ini` и `bionic-runtime-state.json` — конфигурация и состояние имитатора. Проверяйте фактические каталоги через `rtuforge paths`.

См. [README](../README.md), [официальную установку uv](https://docs.astral.sh/uv/getting-started/installation/) и [документацию по управляемому Python](https://docs.astral.sh/uv/guides/install-python/).
