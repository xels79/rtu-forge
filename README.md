# RTU Forge

RTU Forge is a compact Python console for raw Modbus RTU work, reusable scripts, localized help, response decoding, clean copy-friendly output, and exchange recording.

## Highlights

- Interactive shell with persistent history and Tab completion.
- One-shot mode for terminal commands and stored scripts.
- Raw HEX `send` with configurable Modbus CRC handling.
- Named scripts stored in `scripts.ini`.
- English and Russian help/UI selected by `ui.language`.
- Optional Modbus RX decoding with per-send and per-script overrides.
- Clean output mode with plain HEX only.
- Recording of TX+RX or RX-only data to clipboard or UTF-8 files.
- One-command script recording with decode and clean-output flags.
- Windows COM and Linux `/dev/tty*` serial paths.

## Windows setup

Install for the current Windows user from PowerShell in the Git checkout:

```powershell
.\setup.ps1
```

The installer does not require Administrator rights. It performs an editable `uv tool` installation, asks `uv tool dir --bin` for the actual executable directory, updates the user shell PATH through `uv tool update-shell`, and sets the user-level `RTUFORGE_HOME` to the absolute DataDir. Open a new terminal after installation to use the updated PATH.

Defaults:

- `RepoRoot`: directory containing `setup.ps1`;
- `DataDir`: `%APPDATA%\RTUForge`;
- `WorkingDir`: DataDir;
- executable: the actual `rtuforge.exe` reported by the uv tool bin directory.

Explicit relative `-RepoRoot`, `-DataDir`, and `-WorkingDir` values are resolved against the PowerShell invocation directory, even when the destination does not exist yet:

```powershell
.\setup.ps1 -DataDir .\rtu-data -WorkingDir .\rs485
.\setup.ps1 -NoShortcut
```

Unless `-NoShortcut` is used, the installer creates a per-user `RTU Forge.lnk` whose target is the installed `rtuforge.exe`, whose arguments contain the absolute DataDir as `--home`, and whose working directory is WorkingDir. Unless `-NoMigrate` is used, `config.ini`, `scripts.ini`, and `.rtuforge_history` are copied from RepoRoot only when the source exists and the destination does not. Existing user data is never overwritten, moved, or deleted. Rerun `setup.ps1` to update the editable installation after dependency or packaging changes.

`-NoMigrate` means only that these three files are not copied from RepoRoot. With a pre-existing config in DataDir, the installation is fully operational. With a new empty DataDir, setup and its `--help`/`paths` self-check succeed, but config-dependent commands report a missing config until you provide `config.ini`.

Verify the active locations from any directory:

```powershell
rtuforge paths
```

## Development launch

For development without the user installer:

```powershell
uv sync --extra dev
uv run rtuforge --home .
uv run rtuforge --home . send 01 03 00 65 00 01
```

Linux development launch uses the same explicit checkout-local home:

```bash
uv run rtuforge --home .
```

`--home .` is only for development launches from the checkout. A normally installed program uses installer-provided `RTUFORGE_HOME` or the platform DataDir.

One-shot auto-connect is silent: it does not print `Connected COM...` before command output.

## Linux user installation

Install for the current Linux user from the Git checkout:

```bash
chmod +x setup.sh
./setup.sh
```

Do not use `sudo`. The installer refuses root, never writes to `/usr`, `/opt`, or `/etc`, and never runs `sudo` or `usermod`. It creates a dedicated virtual environment and performs an editable install from RepoRoot.

Examples:

```bash
./setup.sh \
    --data-dir ~/rtu-data \
    --working-dir ~/rs485

./setup.sh --desktop
```

Options:

- `--repo-root PATH`: Git/source directory; defaults to the directory containing `setup.sh`.
- `--data-dir PATH`: persistent RTUFORGE_HOME; defaults to `${XDG_CONFIG_HOME:-$HOME/.config}/rtu-forge`.
- `--working-dir PATH`: desktop launch directory; defaults to DataDir.
- `--install-dir PATH`: venv location; defaults to `${XDG_DATA_HOME:-$HOME/.local/share}/rtu-forge`.
- `--bin-dir PATH`: launcher directory; defaults to `$HOME/.local/bin`.
- `--no-migrate`: do not copy existing `config.ini`, `scripts.ini`, or history from RepoRoot.
- `--desktop`: create `~/.local/share/applications/rtu-forge.desktop` with `Terminal=true`.
- `--no-path-update`: do not add the managed RTU Forge block to `.bashrc` or `.zshrc`.
- `-h`, `--help`: show installer help.

All installer paths are normalized to absolute paths before files are created. Migration is copy-only: a source is copied only when it exists and its destination does not. Existing user data is never overwritten, moved, or deleted.

`--no-migrate` means only that config, scripts, and history are not copied from RepoRoot. It is suitable when DataDir already contains the intended user files. For a new empty DataDir, installer self-checks `--help` and `paths` still succeed, while config-dependent commands report a missing `config.ini` until one is supplied.

The generated `<BinDir>/rtuforge` launcher exports the absolute DataDir as `RTUFORGE_HOME`, uses `exec`, forwards all arguments, and preserves the caller's current directory. `--desktop` is optional and uses WorkingDir only for graphical launch.

## Runtime path and user-data model

| Term | Purpose | Windows default | Linux default |
|---|---|---|---|
| RepoRoot | Git/source directory used by the editable install | directory containing `setup.ps1` | directory containing `setup.sh` |
| DataDir / RTUFORGE_HOME | `config.ini`, `scripts.ini`, history | `%APPDATA%\RTUForge` | `${XDG_CONFIG_HOME:-$HOME/.config}/rtu-forge` |
| WorkingDir | Starting directory for shortcut/desktop launch | DataDir | DataDir |
| InstallDir | Installation environment | managed by `uv tool` | `${XDG_DATA_HOME:-$HOME/.local/share}/rtu-forge` |
| Executable / BinDir | User shell executable/launcher | value from `uv tool dir --bin` | `$HOME/.local/bin/rtuforge` |

These roles are independent: DataDir, WorkingDir, and RepoRoot may coincide, but none is derived from another after setup. Inspect active application paths with:

```bash
rtuforge paths
```

Runtime config/scripts priority is:

```text
explicit --config / --scripts
> --home
> RTUFORGE_HOME
> platform default
```

`--home` changes DataDir only for the current process and does not modify the environment or config. Relative `--home`, `--config`, and `--scripts` values are resolved against the invocation CWD and immediately made absolute. `RTUFORGE_HOME` must already be absolute. Without explicit paths or `RTUFORGE_HOME`, Windows uses `%APPDATA%\RTUForge` and Linux uses `${XDG_CONFIG_HOME:-$HOME/.config}/rtu-forge`.

Under Linux, relative `XDG_CONFIG_HOME` and `XDG_DATA_HOME` values are invalid XDG roots and are ignored. Their fallbacks remain `$HOME/.config` and `$HOME/.local/share`, so implicit DataDir and InstallDir never depend on CWD.

CWD is not an implicit DataDir and never determines default config or scripts locations. It affects only explicitly relative CLI paths. A relative history filename inside `config.ini` is resolved against the directory containing that config file.

Examples:

```powershell
rtuforge --home C:\temp\rtu paths
rtuforge --config C:\profiles\drive-a.ini --scripts C:\profiles\scripts.ini paths
```

```bash
rtuforge --home /tmp/rtu paths
```

## Working directory

A shell launch preserves the caller's CWD:

```bash
cd /tmp
rtuforge
```

The optional desktop entry starts in configured WorkingDir. In both cases, RTUFORGE_HOME continues to point to DataDir.

## Temporary connection overrides

Global startup flags temporarily replace effective serial settings for one process:

```text
--port PORT
--baudrate RATE
--bytesize BITS
--parity N|E|O|M|S
--stopbits 1|1.5|2
--timeout-ms MS
```

Windows examples:

```bash
rtuforge --port COM7 --baudrate 19200
rtuforge --port COM7 --baudrate 19200 --parity N send 01 03 00 65 00 01
```

Linux example:

```bash
rtuforge \
    --port /dev/ttyUSB0 \
    --baudrate 9600 \
    --bytesize 8 \
    --parity E \
    --stopbits 1 \
    scan
```

Overrides never modify `config.ini`. `options connection` shows persistent values; `status` and the interactive toolbar show effective values, with overridden fields marked `[CLI]` in status. CLI values retain priority until exit—even if `set options port ...` changes the saved value. A new launch without overrides uses config.ini again.

`--timeout-ms` is the effective serial connection timeout. It is distinct from `scan --timeout`, which temporarily controls each scan probe:

```bash
rtuforge --timeout-ms 1000 scan 1 32 --timeout 100
```

## Serial permissions on Linux

The installer prints current groups and warns when no common serial group is detected. It does not change permissions automatically. Access to `/dev/ttyUSB*`, `/dev/ttyACM*`, or `/dev/ttyS*` commonly requires membership in `dialout` on Debian/Ubuntu:

```bash
sudo usermod -aG dialout "$USER"
```

Run that command yourself only when appropriate for your distribution, then start a new login session. Other distributions may use `uucp`, `tty`, or another group.

## Updating editable installation

Python source changes from the Git checkout are visible immediately because installation is editable:

```bash
git pull
```

If dependencies or `pyproject.toml` changed, rerun:

```bash
./setup.sh
```

## Command reference

```text
connect
disconnect
ports
status
paths
scan [start [end]] [--timeout ms] [--function 01|02|03|04] [--address address]

send [-d|--decode|-r|--raw] <hex...>

add script <name>
  ...commands...
end script

run script <name> [-d|--decode|-r|--raw]
run file <file> [--script <name>] [-d|--decode|-r|--raw]
scripts | ls | list
show script <name>
delete script <name>
export script <name> --file <path> [--overwrite]
export scripts --file <path> [--overwrite]
import script <file> [--overwrite]
import scripts <file> [--overwrite]

show record
record start [all|rx]
record stop buffer
record stop clipboard
record stop file <path>
record status
record cancel
record script <name> <all|rx> <buffer|clipboard|file PATH> [-d|--decode|-r|--raw] [-c|--clean]

options
options <section>
set options <name> <value>

pause <ms>

history
history clear

clear | cls

help
help <command>

exit | quit
```

Global one-shot flag:

```text
-c, --clean
```

It temporarily enables clean output for the current CLI invocation and does not change `config.ini`.

## Tab completion

Examples:

```text
co<TAB>                                   -> connect
show <TAB>                                -> record, script
run script <TAB>                          -> stored script names
run script idd-status <TAB>               -> --decode, --raw, -d, -r
set options <TAB>                         -> mutable option names
set options language <TAB>                -> en, ru
history <TAB>                             -> clear
record <TAB>                              -> cancel, script, start, status, stop
record start <TAB>                        -> all, rx
record stop <TAB>                         -> buffer, clipboard, file
record script <TAB>                       -> stored script names
record script idd-status <TAB>            -> all, rx
record script idd-status rx <TAB>         -> buffer, clipboard, file
record script idd-status rx file x <TAB>  -> --clean, --decode, --raw, -c, -d, -r
send --d<TAB>                             -> --decode
scan <TAB>                                -> --address, --function, --timeout
scan 1 32 --function <TAB>                -> 01, 02, 03, 04
```

## Device scanning

`scan` searches the Modbus RTU bus for slave IDs using a read-only request. The default probe is function `03` (Read Holding Registers), address `0`, quantity `1`.

```text
scan
scan 1
scan 1 32
scan 1 247 --timeout 200
scan 1 32 --function 04 --address 0
scan 1 32 --function 03 --address 0x0065
rtuforge scan -c
```

The default range is `1..247`. Functions `01`, `02`, `03`, and `04` are supported; write functions are never used. `--address` accepts decimal and `0x`-prefixed hexadecimal values.

A normal response is reported only when its Modbus RTU CRC, slave ID, function, byte count, and exact frame length are all valid. For quantity `1`, FC01/FC02 require one data byte and FC03/FC04 require two data bytes. A standard-length response with the expected exception function and a valid CRC counts as a found device; malformed exceptions, bad CRC, unrelated frames, short data, extra data, and serial noise do not.

The default per-device timeout is `runtime.scan_timeout_ms` (100 ms). `--timeout` overrides it for one scan without changing `connection.timeout_ms`, `runtime.scan_timeout_ms`, or `config.ini`. The scanner builds each six-byte request without a CRC, and the transport always adds one CRC through a temporary `append` override. Scan does not change or depend on `runtime.crc_mode`.

In an interactive terminal, Rich keeps progress on one stable fixed-width line and prints discovered devices above it. Redirected output omits Live progress and ANSI cursor control. One-shot `rtuforge scan -c` prints only found slave IDs, one per line, without progress, summaries, TX/RX lines, or ANSI formatting. Ctrl+C stops a standalone scan cleanly and returns to the shell; inside a stored script it also prevents the remaining commands in that script from running, including through nested scripts.

## Sending frames

Basic raw request:

```text
send 01 03 00 65 00 01
```

CRC handling is controlled by `runtime.crc_mode`:

```text
auto    Preserve a valid supplied CRC, otherwise append one
append  Always append CRC
none    Send exactly the bytes entered
```

### Response decoding

Global default:

```ini
[runtime]
decode_rx = true
```

Force decoding for one request:

```text
send --decode 01 03 00 65 00 01
send -d 01 03 00 65 00 01
```

Suppress decoding for one request:

```text
send --raw 01 03 00 65 00 01
send -r 01 03 00 65 00 01
```

For a script:

```text
run script idd-status -d
run script idd-status --decode
run script idd-status -r
run script idd-status --raw
```

Decode priority is:

```text
flag on individual send > flag on run script > runtime.decode_rx
```

For example, `run script idd-status -r` suppresses decoding for ordinary `send` lines in that script, while a stored `send --decode ...` still enables decoding for that specific exchange.

## Clean output

Persistent setting:

```text
set options clean_output true
```

or:

```ini
[runtime]
clean_output = true
```

Temporary one-shot mode:

```bash
uv run rtuforge -c send 01 03 00 65 00 01
uv run rtuforge run script idd-status -c -r
```

The global `-c/--clean` flag can be placed before or after the one-shot command. RTU Forge promotes it to the CLI level internally.

Normal output:

```text
TX 01 03 00 65 00 01 94 15
RX 01 03 02 00 05 78 47 (12.4 ms)
```

Clean output:

```text
01 03 00 65 00 01 94 15
01 03 02 00 05 78 47
```

In clean mode:

- `TX` / `RX` labels are hidden;
- timestamps are hidden;
- elapsed response time is hidden;
- automatic response decoding is hidden;
- `show_tx` and `show_rx` still determine which raw frame lines are printed;
- explicit `-d/--decode` still has priority and can restore decoding.

## Recording

Recording is process-local. It stores raw Modbus frames, not decoded explanatory text.

### Session recording

Start request + response recording:

```text
record start all
```

Start RX-only recording:

```text
record start rx
```

Inspect the current in-memory buffer without stopping recording:

```text
show record
```

Show recording state:

```text
record status
```

Discard the current buffer:

```text
record cancel
```

### Stop and save/copy

Copy to the system clipboard:

```text
record stop buffer
record stop clipboard
```

`buffer` and `clipboard` are aliases.

Save to a UTF-8 file:

```text
record stop file capture.txt
record stop file captures/idd-status.txt
```

Relative paths are resolved relative to the directory containing `config.ini`. Parent directories are created automatically.

### Recording format

`record start rx` always stores only response HEX lines:

```text
01 03 02 00 05 78 47
01 03 02 00 02 39 85
```

`record start all` follows the active output style.

Normal mode:

```text
TX 01 03 00 65 00 01 94 15
RX 01 03 02 00 05 78 47
```

Clean mode (`runtime.clean_output=true`, one-shot `-c/--clean`, or `record script ... -c`):

```text
01 03 00 65 00 01 94 15
01 03 02 00 05 78 47
```

The recording buffer therefore matches the visible clean format when clean output is active.

## Record a script in one command

Syntax:

```text
record script <name> <all|rx> <buffer|clipboard|file PATH> [-d|--decode|-r|--raw] [-c|--clean]
```

This command performs the complete sequence internally:

1. starts a fresh recording;
2. runs the named script;
3. applies the selected recording mode;
4. applies optional decode/clean overrides;
5. saves or copies the result;
6. restores the previous `clean_output` setting.

Examples:

```text
record script idd-status rx file captures/idd-status.txt -r
record script idd-status all buffer -c -r
record script idd-status all clipboard --decode
```

One-shot examples:

```bash
uv run rtuforge record script idd-status rx file capture.txt -r
uv run rtuforge record script idd-status all file capture.txt -c -r
```

Recording modes:

```text
all   Record both transmitted and received frames
rx    Record received frames only
```

Destinations:

```text
buffer       Copy to system clipboard
clipboard    Same as buffer
file PATH    Save to a UTF-8 text file
```

Flags:

```text
-d, --decode   Force Modbus response decoding while the script runs
-r, --raw      Suppress Modbus response decoding while the script runs
-c, --clean    Temporarily enable clean screen output and clean 'all' recording format
```

`-c/--clean` used by `record script` is temporary and does not persist to `config.ini`.

If the script fails, the temporary recording is discarded and the previous clean-output setting is restored.

## Scripts

Create interactively:

```text
rtu> add script read-basic
... send 01 03 00 65 00 01
... pause 100
... send --decode 01 03 00 66 00 01
... end script
```

Run:

```text
run script read-basic
```

Inspect:

```text
show script read-basic
```

Delete:

```text
delete script read-basic
```

### Commands useful inside scripts

```text
send ...
send --decode ...
send --raw ...
pause <ms>
connect
disconnect
status
ports
scan [start [end]] [--timeout ms] [--function 01|02|03|04] [--address address]
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
```

For example, a script can contain its own RX capture:

```text
record start rx
send 01 03 00 65 00 01
send 01 03 00 66 00 01
show record
record stop file capture.txt
```

Commands not allowed inside scripts:

```text
add script ...
import script ... | import scripts ...
export script ... | export scripts ...
run file ...
history
history clear
clear | cls
exit | quit
```

Empty lines and lines beginning with `#` are ignored.

`runtime.inter_command_delay_ms` is applied between stored script lines. `pause <ms>` adds an explicit additional delay.

Nested `run script` calls are supported. Recursive/cyclic script calls should be avoided.

## Portable script files

RTU Forge can export, import, and directly run human-readable UTF-8 `.rtus` files. The extension is recommended but optional; the `scripts-v1` marker identifies the format.

Single-script example:

```ini
[rtuforge]
format = scripts-v1

[scripts]
status =
    send 01 03 00 65 00 01
```

A bundle uses the same format with more entries:

```ini
[rtuforge]
format = scripts-v1

[scripts]
status =
    send 01 03 00 65 00 01

errors =
    send 01 03 00 1B 00 01
```

```text
export script idd-status --file idd-status.rtus
export scripts --file backup.rtus
import script idd-status.rtus
import scripts backup.rtus
run file idd-status.rtus
run file backup.rtus --script idd-status
```

Import merges scripts into `scripts.ini`; it does not remove unrelated stored scripts. `run file` executes directly and does not import. Relative paths are based on the process CWD, and paths with spaces should be quoted. Existing destination files and stored scripts are not overwritten without `--overwrite`.

Portable-file commands are not allowed inside scripts. In one-shot mode, `-c/--clean` remains a global flag and may be placed before or after the whole command; it is not a `run file` flag in the interactive shell.

## Options

Show all mutable options:

```text
options
```

Show one section:

```text
options connection
options runtime
options history
options ui
```

Change an option:

```text
set options port COM6
set options timeout_ms 1000
set options crc_mode auto
set options decode_rx false
set options clean_output true
set options language ru
```

Changing a connection option while connected forces a disconnect.

Boolean values accept:

```text
true / false
yes / no
on / off
1 / 0
```

### Connection options

- `port`
- `baudrate`
- `bytesize`
- `parity`
- `stopbits`
- `timeout_ms`

### Runtime options

- `inter_command_delay_ms`
- `post_write_delay_ms`
- `response_silence_ms`
- `max_response_bytes`
- `crc_mode`
- `auto_connect`
- `show_tx`
- `show_rx`
- `decode_rx`
- `clean_output`
- `scan_timeout_ms`: per-device scan timeout; must be greater than zero (default `100`).
- `timestamps`
- `uppercase_hex`

### History options

- `file`
- `max_entries`

### UI options

- `language`: `en` or `ru`

## Language

Configuration:

```ini
[ui]
language = en
```

Switch to Russian:

```text
set options language ru
```

Supported values:

```text
en
ru
```

Localization covers:

- general and command-specific help;
- option table headings and descriptions;
- status output;
- common shell messages and errors;
- recording messages;
- Modbus response decoding labels, function names and exception names;
- CLI `--help` descriptions/examples.

Technical command names and option identifiers are intentionally not translated.

## Help

General help:

```text
help
```

Detailed topics:

```text
help connect
help disconnect
help ports
help status
help paths
help scan
help send
help add
help run
help scripts
help export
help import
help show
help delete
help record
help options
help set
help pause
help history
help clear
help help
help exit
```

The detailed help is available in both interactive and one-shot mode:

```bash
uv run rtuforge help record
uv run rtuforge help scripts
```

## One-shot behavior and errors

Examples:

```bash
uv run rtuforge send 01 03 00 65 00 01
uv run rtuforge -c send 01 03 00 65 00 01
uv run rtuforge run script idd-status -r
uv run rtuforge record script idd-status rx file capture.txt -r
```

One-shot mode suppresses the automatic `Connected ...` message.

Expected user/runtime errors are returned as concise messages with exit code `1`, without a Python traceback.

## Development

Agent rules are in `AGENTS.md`.

Run tests:

```bash
uv run --extra dev pytest -q
```
