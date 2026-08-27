# RTU Forge — TODO проверки setup на 28.08.2026

Ветка: `feature/make-setup-scripts`

Статус: Codex уже выполнил ТЗ.  
Цель: **только проверка и исправление найденных дефектов**. Новую функциональность без необходимости не добавлять.

## 1. Code review ветки

- [ ] Сравнить `feature/make-setup-scripts` с базовой веткой.
- [ ] Проверить полный список изменённых файлов.
- [ ] Проверить, что installer-ветка не содержит случайных изменений Modbus/`scan` logic.
- [ ] Проверить:
  - `setup.ps1`;
  - `setup.sh`;
  - path-resolution code;
  - connection override code;
  - tests;
  - `README.md`.
- [ ] Проверить, что user-owned файлы нигде не overwrite автоматически.
- [ ] Проверить, что пути нормализуются в absolute до файловых операций.

## 2. Общая модель путей

Проверить разделение:

- `RepoRoot` — Git/source directory;
- `DataDir` / `RTUFORGE_HOME` — `config.ini`, `scripts.ini`, history;
- `WorkingDir` — рабочая директория запуска;
- `InstallDir` — место user installation/venv;
- `BinDir` — launcher/executable directory.

- [ ] `DataDir`, `WorkingDir`, `RepoRoot` могут быть разными.
- [ ] Implicit config/scripts/history не зависят от CWD.
- [ ] Все resolved paths абсолютные.
- [ ] Явные относительные setup/CLI paths считаются относительно документированной base directory.
- [ ] Команда `paths` показывает фактические absolute paths.
- [ ] `paths` не открывает serial.
- [ ] `paths` ничего не создаёт и не сохраняет.

## 3. Windows `setup.ps1`

Проверять обычным пользователем, без Administrator.

### Базовый запуск

- [ ] Запустить:
  ```powershell
  .\setup.ps1
  ```
- [ ] Проверить:
  - `RTUFORGE_HOME`;
  - executable;
  - PATH;
  - shortcut;
  - DataDir;
  - WorkingDir;
  - self-check.

### Относительные пути

- [ ] Запустить из отдельной test directory:
  ```powershell
  .\setup.ps1 `
      -DataDir .\test-data `
      -WorkingDir .\test-work
  ```
- [ ] В выводе должны быть только absolute paths.
- [ ] `test-data` и `test-work` должны разрешаться относительно PowerShell CWD.
- [ ] `Resolve-Path` не должен ломать создание ещё не существующих каталогов.

### Повторный запуск

- [ ] Повторно выполнить `setup.ps1`.
- [ ] Существующие:
  - `config.ini`;
  - `scripts.ini`;
  - history
  не должны быть overwritten.
- [ ] Source files не должны удаляться или перемещаться.

### Флаги

- [ ] Проверить `-NoMigrate`.
- [ ] Проверить `-NoShortcut`.
- [ ] Проверить явный `-RepoRoot`.
- [ ] Проверить явный `-DataDir`.
- [ ] Проверить явный `-WorkingDir`.

### Shortcut

- [ ] `TargetPath` абсолютный.
- [ ] `WorkingDirectory` = absolute `WorkingDir`.
- [ ] Shortcut не зависит от RepoRoot как working directory.
- [ ] Запустить shortcut и выполнить:
  ```text
  paths
  ```
- [ ] Проверить:
  - `CWD == WorkingDir`;
  - `Home == DataDir`.

## 4. Windows запуск через PATH

- [ ] Открыть новый terminal после setup.
- [ ] Из `C:\`:
  ```powershell
  rtuforge paths
  ```
- [ ] Из другой директории:
  ```powershell
  cd $env:TEMP
  rtuforge paths
  ```
- [ ] Home/config/scripts/history должны совпадать.
- [ ] CWD может отличаться.
- [ ] `config.ini` и `scripts.ini` не должны появляться в `$env:TEMP`.

## 5. Linux `setup.sh`

Проверять от обычного пользователя.

### Базовый запуск

- [ ] Сделать executable:
  ```bash
  chmod +x setup.sh
  ```
- [ ] Запустить:
  ```bash
  ./setup.sh
  ```
- [ ] Не должен использоваться `sudo`.
- [ ] Не должно быть записи в:
  - `/usr`;
  - `/usr/local`;
  - `/etc`.

### Root guard

- [ ] Проверить, что запуск от root завершается с понятной ошибкой.
- [ ] Скрипт сам не вызывает `sudo`.

### Test paths

- [ ] Запустить:
  ```bash
  ./setup.sh \
      --data-dir ./test-data \
      --working-dir ./test-work \
      --install-dir ./test-install \
      --bin-dir ./test-bin \
      --no-path-update
  ```
- [ ] Все итоговые пути absolute.
- [ ] Относительные пути считаются относительно текущего shell CWD.
- [ ] Каталоги создаются корректно.

### Повторный запуск

- [ ] Повторный запуск не overwrite:
  - config;
  - scripts;
  - history.
- [ ] Проверить `--no-migrate`.
- [ ] Проверить `--desktop`.
- [ ] Проверить `--no-path-update`.

## 6. Linux launcher

- [ ] Launcher создан в `BinDir`.
- [ ] В launcher используются absolute paths.
- [ ] Launcher экспортирует правильный `RTUFORGE_HOME`.
- [ ] Launcher использует `exec`.
- [ ] PATH launch сохраняет caller CWD:
  ```bash
  cd /tmp
  rtuforge paths
  ```
- [ ] Проверить:
  - `CWD == /tmp`;
  - `Home == DataDir`.

## 7. Linux desktop entry

Только если setup запущен с `--desktop`.

- [ ] `.desktop` создан в user applications directory.
- [ ] `Exec` абсолютный.
- [ ] `Path` = absolute WorkingDir.
- [ ] `Terminal=true`.
- [ ] Без `--desktop` desktop entry не создаётся.

## 8. Linux serial permissions

- [ ] setup не выполняет `usermod`.
- [ ] setup не требует sudo.
- [ ] README объясняет права на:
  - `/dev/ttyUSB*`;
  - `/dev/ttyACM*`;
  - `/dev/ttyS*`.
- [ ] Для Debian/Ubuntu приведён пример `dialout`.
- [ ] Ясно указано, что после изменения групп нужен новый login session.

## 9. Temporary connection overrides

Проверить global startup options:

- `--port`
- `--baudrate`
- `--bytesize`
- `--parity`
- `--stopbits`
- `--timeout-ms`

### Базовая проверка

- [ ] Windows:
  ```powershell
  rtuforge --port COM7 --baudrate 19200 status
  ```
- [ ] Linux:
  ```bash
  rtuforge --port /dev/ttyUSB0 --baudrate 9600 --parity E status
  ```
- [ ] `status` показывает effective settings.
- [ ] `options connection` показывает persistent config values.
- [ ] Toolbar показывает effective settings.
- [ ] После restart без flags снова используются значения config.ini.

### Persistence regression

Исходный config:

```ini
[connection]
port = COM4
baudrate = 9600
```

Запуск:

```powershell
rtuforge --port COM7 --baudrate 19200
```

В shell:

```text
set options language ru
```

- [ ] После выхода `config.ini` всё ещё содержит:
  - `port = COM4`;
  - `baudrate = 9600`.
- [ ] Temporary overrides не попадают в ConfigParser/persistent config.
- [ ] `set options port COM8` при активном `--port COM7`:
  - сохраняет COM8;
  - текущий effective port остаётся COM7 до exit;
  - после нового запуска без override используется COM8.

## 10. Connection override integration

- [ ] `connect` использует effective settings.
- [ ] `send` использует effective settings.
- [ ] `run script` использует effective settings.
- [ ] `record script` использует effective settings.
- [ ] `scan` использует effective settings.
- [ ] Endpoint показывает effective settings.
- [ ] Не должно быть ситуации, где status показывает один port, а pyserial открывает другой.

## 11. Timeout separation

Проверить различие:

```text
--timeout-ms
```

и:

```text
scan --timeout
```

Пример:

```powershell
rtuforge --port COM7 --timeout-ms 1000 scan 1 32 --timeout 100
```

- [ ] Connection timeout = 1000 ms.
- [ ] Scan probe timeout = 100 ms.
- [ ] Ни один параметр не сохраняется в config.ini.

## 12. README review

- [ ] Windows setup полностью документирован.
- [ ] Linux user setup полностью документирован.
- [ ] Описаны:
  - RepoRoot;
  - DataDir / RTUFORGE_HOME;
  - WorkingDir;
  - InstallDir;
  - BinDir.
- [ ] Явно сказано, что это разные понятия.
- [ ] Документированы absolute path rules.
- [ ] Документирован порядок:
  - `--home`;
  - `RTUFORGE_HOME`;
  - platform default.
- [ ] Документированы `--config` и `--scripts`.
- [ ] Документирована команда `paths`.
- [ ] Документированы temporary connection overrides.
- [ ] Документирована разница `status` vs `options connection`.
- [ ] Документирована разница `--timeout-ms` vs `scan --timeout`.
- [ ] Документирована editable installation/update procedure.
- [ ] Документирована migration safety.
- [ ] Документированы Linux serial permissions.

## 13. Automated tests / CI

- [ ] Запустить:
  ```bash
  uv run --extra dev pytest -q
  ```
- [ ] Проверить tests path resolution.
- [ ] Проверить tests connection overrides.
- [ ] Проверить tests persistence regression.
- [ ] Проверить Linux path tests через monkeypatch.
- [ ] Проверить GitHub Actions именно на голове `feature/make-setup-scripts`.
- [ ] Если CI зелёный, отдельно отметить, что Windows shortcut и реальный shell setup всё равно требуют ручной проверки.

## 14. Итог ручной проверки

Записать фактические значения:

```text
OS:
Branch:
Commit:
RepoRoot:
DataDir:
WorkingDir:
InstallDir:
BinDir:
Executable:
RTUFORGE_HOME:
Shortcut/Desktop entry:
PATH:
pytest:
CI:
```

## Definition of Done

Ветка `feature/make-setup-scripts` готова к merge только когда:

- [ ] Windows setup проверен вручную.
- [ ] Linux setup проверен вручную.
- [ ] Повторная установка не портит user data.
- [ ] Relative paths корректно resolve в absolute.
- [ ] PATH launch работает из произвольной директории.
- [ ] Shortcut/desktop launcher использует правильный WorkingDir.
- [ ] Temporary connection overrides не сохраняются.
- [ ] `status`/toolbar/transport используют effective settings.
- [ ] README соответствует реализации.
- [ ] Полный pytest зелёный.
- [ ] CI зелёный.
