# RTU Forge — TODO проверки setup на 28.08.2026

Ветка: `feature/make-setup-scripts`

Статус: Codex уже выполнил ТЗ.  
Цель: **только проверка и исправление найденных дефектов**. Новую функциональность без необходимости не добавлять.

## 1. Code review ветки

- [x] Сравнить `feature/make-setup-scripts` с базовой веткой.
- [x] Проверить полный список изменённых файлов.
- [x] Проверить, что installer-ветка не содержит случайных изменений Modbus/`scan` logic.
- [x] Проверить:
  - `setup.ps1`;
  - `setup.sh`;
  - path-resolution code;
  - connection override code;
  - tests;
  - `README.md`.
- [x] Проверить, что user-owned файлы нигде не overwrite автоматически.
- [x] Проверить, что пути нормализуются в absolute до файловых операций.

## 2. Общая модель путей

Проверить разделение:

- `RepoRoot` — Git/source directory;
- `DataDir` / `RTUFORGE_HOME` — `config.ini`, `scripts.ini`, history;
- `WorkingDir` — рабочая директория запуска;
- `InstallDir` — место user installation/venv;
- `BinDir` — launcher/executable directory.

- [x] `DataDir`, `WorkingDir`, `RepoRoot` могут быть разными.
- [x] Implicit config/scripts/history не зависят от CWD.
- [x] Все resolved paths абсолютные.
- [x] Явные относительные setup/CLI paths считаются относительно документированной base directory.
- [x] Команда `paths` показывает фактические absolute paths.
- [x] `paths` не открывает serial.
- [x] `paths` ничего не создаёт и не сохраняет.

## 3. Windows `setup.ps1`

Проверять обычным пользователем, без Administrator.

### Базовый запуск

- [x] Запустить:
  ```powershell
  .\setup.ps1
  ```
- [x] Проверить:
  - `RTUFORGE_HOME`;
  - executable;
  - PATH;
  - shortcut;
  - DataDir;
  - WorkingDir;
  - self-check.

### Относительные пути

- [x] Запустить из отдельной test directory:
  ```powershell
  .\setup.ps1 `
      -DataDir .\test-data `
      -WorkingDir .\test-work
  ```
- [x] В выводе должны быть только absolute paths.
- [x] `test-data` и `test-work` должны разрешаться относительно PowerShell CWD.
- [x] `Resolve-Path` не должен ломать создание ещё не существующих каталогов.

### Повторный запуск

- [x] Повторно выполнить `setup.ps1`.
- [x] Существующие:
  - `config.ini`;
  - `scripts.ini`;
  - history
  не должны быть overwritten.
- [x] Source files не должны удаляться или перемещаться.

### Флаги

- [x] Проверить `-NoMigrate`.
- [x] Проверить `-NoShortcut`.
- [x] Проверить явный `-RepoRoot`.
- [x] Проверить явный `-DataDir`.
- [x] Проверить явный `-WorkingDir`.

### Shortcut

- [x] `TargetPath` абсолютный.
- [x] `WorkingDirectory` = absolute `WorkingDir`.
- [x] Shortcut не зависит от RepoRoot как working directory.
- [x] Запустить shortcut и выполнить:
  ```text
  paths
  ```
- [x] Проверить:
  - `CWD == WorkingDir`;
  - `Home == DataDir`.

## 4. Windows запуск через PATH

- [x] Открыть новый terminal после setup.
- [x] Из `C:\`:
  ```powershell
  rtuforge paths
  ```
- [x] Из другой директории:
  ```powershell
  cd $env:TEMP
  rtuforge paths
  ```
- [x] Home/config/scripts/history должны совпадать.
- [x] CWD может отличаться.
- [x] `config.ini` и `scripts.ini` не должны появляться в `$env:TEMP`.

## 5. Linux `setup.sh`

Проверять от обычного пользователя.

### Базовый запуск

- [x] Сделать executable:
  ```bash
  chmod +x setup.sh
  ```
- [x] Запустить:
  ```bash
  ./setup.sh
  ```
- [x] Не должен использоваться `sudo`.
- [x] Не должно быть записи в:
  - `/usr`;
  - `/usr/local`;
  - `/etc`.

### Root guard

- [x] Проверить, что запуск от root завершается с понятной ошибкой.
- [x] Скрипт сам не вызывает `sudo`.

### Test paths

- [x] Запустить:
  ```bash
  ./setup.sh \
      --data-dir ./test-data \
      --working-dir ./test-work \
      --install-dir ./test-install \
      --bin-dir ./test-bin \
      --no-path-update
  ```
- [x] Все итоговые пути absolute.
- [x] Относительные пути считаются относительно текущего shell CWD.
- [x] Каталоги создаются корректно.

### Повторный запуск

- [x] Повторный запуск не overwrite:
  - config;
  - scripts;
  - history.
- [x] Проверить `--no-migrate`.
- [x] Проверить `--desktop`.
- [x] Проверить `--no-path-update`.

## 6. Linux launcher

- [x] Launcher создан в `BinDir`.
- [x] В launcher используются absolute paths.
- [x] Launcher экспортирует правильный `RTUFORGE_HOME`.
- [x] Launcher использует `exec`.
- [x] PATH launch сохраняет caller CWD:
  ```bash
  cd /tmp
  rtuforge paths
  ```
- [x] Проверить:
  - `CWD == /tmp`;
  - `Home == DataDir`.

## 7. Linux desktop entry

Только если setup запущен с `--desktop`.

- [x] `.desktop` создан в user applications directory.
- [x] `Exec` абсолютный.
- [x] `Path` = absolute WorkingDir.
- [x] `Terminal=true`.
- [x] Без `--desktop` desktop entry не создаётся.

## 8. Linux serial permissions

- [x] setup не выполняет `usermod`.
- [x] setup не требует sudo.
- [x] README объясняет права на:
  - `/dev/ttyUSB*`;
  - `/dev/ttyACM*`;
  - `/dev/ttyS*`.
- [x] Для Debian/Ubuntu приведён пример `dialout`.
- [x] Ясно указано, что после изменения групп нужен новый login session.

## 9. Temporary connection overrides

Проверить global startup options:

- `--port`
- `--baudrate`
- `--bytesize`
- `--parity`
- `--stopbits`
- `--timeout-ms`

### Базовая проверка

- [x] Windows:
  ```powershell
  rtuforge --port COM7 --baudrate 19200 status
  ```
- [x] Linux:
  ```bash
  rtuforge --port /dev/ttyUSB0 --baudrate 9600 --parity E status
  ```
- [x] `status` показывает effective settings.
- [x] `options connection` показывает persistent config values.
- [x] Toolbar показывает effective settings.
- [x] После restart без flags снова используются значения config.ini.

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

- [x] После выхода `config.ini` всё ещё содержит:
  - `port = COM4`;
  - `baudrate = 9600`.
- [x] Temporary overrides не попадают в ConfigParser/persistent config.
- [x] `set options port COM8` при активном `--port COM7`:
  - сохраняет COM8;
  - текущий effective port остаётся COM7 до exit;
  - после нового запуска без override используется COM8.

## 10. Connection override integration

- [x] `connect` использует effective settings.
- [x] `send` использует effective settings.
- [x] `run script` использует effective settings.
- [x] `record script` использует effective settings.
- [x] `scan` использует effective settings.
- [x] Endpoint показывает effective settings.
- [x] Не должно быть ситуации, где status показывает один port, а pyserial открывает другой.

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

- [x] Connection timeout = 1000 ms.
- [x] Scan probe timeout = 100 ms.
- [x] Ни один параметр не сохраняется в config.ini.

## 12. README review

- [x] Windows setup полностью документирован.
- [x] Linux user setup полностью документирован.
- [x] Описаны:
  - RepoRoot;
  - DataDir / RTUFORGE_HOME;
  - WorkingDir;
  - InstallDir;
  - BinDir.
- [x] Явно сказано, что это разные понятия.
- [x] Документированы absolute path rules.
- [x] Документирован порядок:
  - `--home`;
  - `RTUFORGE_HOME`;
  - platform default.
- [x] Документированы `--config` и `--scripts`.
- [x] Документирована команда `paths`.
- [x] Документированы temporary connection overrides.
- [x] Документирована разница `status` vs `options connection`.
- [x] Документирована разница `--timeout-ms` vs `scan --timeout`.
- [x] Документирована editable installation/update procedure.
- [x] Документирована migration safety.
- [x] Документированы Linux serial permissions.

## 13. Automated tests / CI

- [x] Запустить:
  ```bash
  uv run --extra dev pytest -q
  ```
- [x] Проверить tests path resolution.
- [x] Проверить tests connection overrides.
- [x] Проверить tests persistence regression.
- [x] Проверить Linux path tests через monkeypatch.
- [ ] Проверить GitHub Actions именно на голове `feature/make-setup-scripts` после push нового commit.
- [ ] Зафиксировать результат нового CI; предыдущий run #61 не используется как подтверждение.

## 14. Итог ручной проверки

Записать фактические значения:

```text
OS: Windows + Ubuntu WSL (user schuk, UID 1000)
Branch: feature/make-setup-scripts
HEAD before: cb690d5109dd7d4d4090c49bc0fbff7e165fcd32
RepoRoot: C:\dev\rtu-forge / /mnt/c/dev/rtu-forge
Windows DataDir: C:\Users\schuk\AppData\Roaming\RTUForge
Windows WorkingDir: C:\Users\schuk\AppData\Roaming\RTUForge
Windows BinDir: C:\Users\schuk\.local\bin
Windows Executable: C:\Users\schuk\.local\bin\rtuforge.exe
Windows RTUFORGE_HOME: C:\Users\schuk\AppData\Roaming\RTUForge
Windows shortcut: C:\Users\schuk\Desktop\RTU Forge.lnk; TargetPath and WorkingDirectory verified; launch exit 0
Windows PATH: uv tool bin present
Linux manual root: /tmp/rtuforge-manual-acceptance-20260828
Linux default DataDir: /tmp/rtuforge-manual-acceptance-20260828/xdg-config/rtu-forge
Linux default InstallDir: /tmp/rtuforge-manual-acceptance-20260828/xdg-data/rtu-forge
Linux default BinDir: /tmp/rtuforge-manual-acceptance-20260828/home/.local/bin
Linux desktop entry: generated and validated by integration test; graphical GUI launch not performed
pytest Windows: 160 passed, 4 skipped
pytest WSL: 163 passed, 1 skipped
CI: pending new HEAD after push
```

## Definition of Done

Ветка `feature/make-setup-scripts` готова к merge только когда:

- [x] Windows setup проверен вручную.
- [x] Linux setup проверен вручную.
- [x] Повторная установка не портит user data.
- [x] Relative paths корректно resolve в absolute.
- [x] PATH launch работает из произвольной директории.
- [x] Shortcut/desktop launcher использует правильный WorkingDir.
- [x] Temporary connection overrides не сохраняются.
- [x] `status`/toolbar/transport используют effective settings.
- [x] README соответствует реализации.
- [x] Полный pytest зелёный.
- [ ] CI зелёный на новом HEAD.
