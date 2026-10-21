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
- executables: `rtuforge.exe`, `standforge.exe`, and `bionic-immitator.exe` in
  the actual uv tool bin directory.

Explicit relative `-RepoRoot`, `-DataDir`, and `-WorkingDir` values are resolved against the PowerShell invocation directory, even when the destination does not exist yet:

```powershell
.\setup.ps1 -DataDir .\rtu-data -WorkingDir .\rs485
.\setup.ps1 -NoShortcut
```

Unless `-NoShortcut` is used, the installer creates per-user `RTU Forge.lnk`
and `Bionic Immitator.lnk` shortcuts. The Bionic shortcut uses
`<DataDir>\bionic-data`; it does not share or overwrite RTU Forge files. Unless
`-NoMigrate` is used, `config.ini`, `scripts.ini`, and `.rtuforge_history` are
copied from RepoRoot only when the source exists and the destination does not.
Existing user data is never overwritten, moved, or deleted. Rerun `setup.ps1`
to update the editable installation after dependency or packaging changes.

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

The separate Russian-language Bionic Mini physical imitator is launched with:

```powershell
uv run bionic-immitator --home .\bionic-data
uv run bionic-immitator --home .\bionic-data --no-controller
```

Its full-screen interface uses separate status, device, port, settings, help,
log, RS-485, tank, water-composition, pump, equipment-health, pressure, irrigation, light,
sensor, PonicPilot, and drive pages. PonicPilot ID 5 is permanently bound to
the shared BP (broth) tank; all of its calculated measurements and doses use
that tank only. Use
`view <page>` or `F1`–`F6` to navigate, the mouse wheel or `PgUp`/`PgDn` to
scroll, `Tab` for contextual completion, and `Up`/`Down` for persistent command
history. See [BIONIC-IMMITATOR.md](BIONIC-IMMITATOR.md) for the complete key map.

Lighting is configured independently per tier through `view light settings`.
The mutable `light_profile` option stores the six `NONE`, `SINGLE`, or
`SPECTRAL_4` assignments, their power DOs, physical Modbus AO IDs/channels,
voltage ranges, brightness ranges, names, and enabled flags. `light apply`
changes only the active interpretation, `light save` changes only the saved
lighting profile, and `light restore-defaults` restores the Bionic Mini factory
map in the draft. These operations never write controller-owned DO or AO
outputs.

The pressure model exposes mutable `pressure_rise_s`,
`valve_pressure_response_ms`, `valve_pressure_close_response_ms`,
`transient_pressure_spike_coefficient`,
`transient_pressure_spike_duration_ms`, `closed_head_pressure_bar`,
`rupture_threshold_bar`, and `rupture_residual_bar` options. Valve response
times are model parameters in milliseconds; the default transient spike
coefficient is zero because no measured water-hammer characteristic is being
claimed.

The Bionic level sensors drive a separately connected physical Waveshare Relay
8/16CH on USB/RS-485 №2; they are not exposed as extra virtual devices on USB
№1. The default CH1..CH8 map, configurable NO/NC installation contact, relay
polarity, edge-triggered FC0F writes, and separate FC01 confirmation are
documented in the Bionic guide. Every MIN/MAX sensor has its own persisted
absolute threshold; MAX is independent of physical tank capacity and never
stops filling by itself.

Transfer pumps and HP1/HP2 accumulate heat and wear automatically when their
real fluid path is unavailable. `view equipment` separates controller command,
actual operation, flow/pressure, damage, VFD fault, and repair requirement.
These internal diagnostics add no controller inputs or private Modbus alarm
registers; repair and replacement require an explicit `--confirm` command.
The settings page groups parameters by subsystem and sorts each group by its
Russian display name. It also exposes one estimated physical-failure time per
pump (120 seconds for transfer pumps and 180 seconds for HP by default); these
are explicitly labelled demonstration-model values rather than measurements.

It has its own configuration and event journal and does not modify
`config.ini`, `scripts.ini`, or RTU Forge history. Architecture, commands,
verified Stage 7 Modbus maps, USB safety rules, and hardware assumptions are in
[BIONIC-IMMITATOR.md](BIONIC-IMMITATOR.md).

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

The generated `<BinDir>/rtuforge`, `<BinDir>/standforge`, and
`<BinDir>/bionic-immitator` launchers use `exec`, forward all arguments, and
preserve the caller's current directory. The RTU Forge launcher additionally
exports the absolute DataDir as `RTUFORGE_HOME`. `--desktop` is optional and
uses WorkingDir only for graphical RTU Forge launch.

## Runtime path and user-data model

| Term | Purpose | Windows default | Linux default |
|---|---|---|---|
| RepoRoot | Git/source directory used by the editable install | directory containing `setup.ps1` | directory containing `setup.sh` |
| DataDir / RTUFORGE_HOME | `config.ini`, `scripts.ini`, history | `%APPDATA%\RTUForge` | `${XDG_CONFIG_HOME:-$HOME/.config}/rtu-forge` |
| WorkingDir | Starting directory for shortcut/desktop launch | DataDir | DataDir |
| InstallDir | Installation environment | managed by `uv tool` | `${XDG_DATA_HOME:-$HOME/.local/share}/rtu-forge` |
| Executable / BinDir | User shell executables/launchers | value from `uv tool dir --bin` | `$HOME/.local/bin/{rtuforge,standforge,bionic-immitator}` |

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

`runtime.inter_command_delay_ms` is applied between executed ordinary commands. `pause <ms>` adds an explicit additional delay. Labels, jumps, conditions, comments and empty lines add no automatic delays.

Nested `run script` calls are supported. Recursive/cyclic script calls should be avoided.

### Script control flow

```text
label <name>
goto <name>
if <expression>
else
end if
```

Labels match `[A-Za-z_][A-Za-z0-9_.-]*`, are case-sensitive and local to each script invocation. `goto` jumps forward or backward to the command after a label. Nested `if` blocks and optional `else` branches are supported. The entire script's labels, block structure and expressions are checked before its commands execute. Errors identify the script and its script-body line (not the physical INI file line). Existing INI loaders omit empty lines and INI comments.

Simple if/else:

```text
send 05 03 00 0C 00 01
if last.timeout
    pause 250
else
    send 05 03 00 0F 00 01
end if
```

Expressions support decimal and `0x` hexadecimal integers, `true`/`false`, comparisons `== != < <= > >=`, `and or not`, bitwise `& | ^ << >>`, and parentheses. Boolean operators short-circuit; use parentheses around bit masks. Shift counts are restricted to 0..4096. Expressions use a whitelisted AST evaluator without Python `eval`; function calls, strings and arbitrary Python attributes are rejected.

| Value | Meaning |
|---|---|
| `last.timeout` | True when the last `send` received no bytes |
| `last.rx_len` | Complete RX length in bytes |
| `last.address` | Response slave address |
| `last.function` | Raw response function byte, including the exception bit |
| `last.exception` | Modbus exception code, or 0 for a normal response |
| `last.reg[N]` | Zero-based register from the existing FC03/FC04 decoder |
| `last.byte[N]` | Zero-based byte of the complete raw RX frame, including CRC |

`last` is shared by nested scripts and updated by every completed `send`, even with `-r` or hidden RX output. Access before the first `send`, an absent address/function or an unavailable register/byte index raises a localized runtime error; missing registers never become zero. Register decoding follows the existing parser, including its best-effort handling of malformed frames; it does not imply CRC validation.

Poll until bit 1 clears before continuing to the next command:

```text
send 05 06 00 0F 00 1E
label wait_b
pause 100
send 05 03 00 0C 00 01
if last.timeout
    pause 250
    goto wait_b
end if
if (last.reg[0] & 0x0002) != 0
    goto wait_b
end if
send 05 03 00 0F 00 01
```

`last.reg[0]` is the first register of the most recent response. Loops have no iteration limit and do not grow the Python call stack. Ctrl+C stops execution and closes the transport; one-shot execution returns 130.

The acceptance example is in `examples/ponic-test.ini`:

```bash
uv run rtuforge --scripts examples/ponic-test.ini run script ponic-test -r -c
```

Control flow works in the main `scripts.ini`, external `--scripts` files and portable `run file` scripts. Control instructions print no extra output. Explicit `help` still prints in clean mode. Use `help script`, `help if`, `help label` or `help goto` for EN/RU help; `help scripts` includes the same language reference. UI language changes help and diagnostics, never script keywords.

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

## Pulsar water meters (proprietary RS-485 protocol)

The `pulsar` subcommand is deliberately separate from Modbus RTU `send` / `scan` and Stand Forge. It uses its own fully formed CRC16 frames, validating BCD address, function, frame length, request ID, and CRC of responses. No `config.ini` change is needed. Tested using a real discovery frame from the electronic water meter Pulsar model 1, N00014163, address `17440707`, and the Wiren Board protocol vectors.

Use a separate RS-485 test adapter or ensure the existing Bionic controller is not operating on this bus. Do **not** run two masters on the same physical RS-485 line. Use 9600 8N1; override your usual even-parity Modbus settings with `--parity N`. The software does not change serial/parity configuration automatically.

```powershell
rtuforge.exe --port COM4 --baudrate 9600 --parity N pulsar read 17440707
rtuforge.exe --port COM4 --baudrate 9600 --parity N pulsar read 17440707 --format raw
rtuforge.exe --port COM4 --parity N pulsar param get 17440707 0x000A
rtuforge.exe --port COM4 --parity N pulsar time get 17440707
rtuforge.exe pulsar decode 17 44 07 07 0A 12 C3 1F 0A 01 00 00 00 00 79 E6 B4 7B
rtuforge.exe --port COM4 --parity N pulsar discover --single
```

Channel 1 defaults to little-endian float32 (Pulsar Water model 1). For other Pulsar models use `--format s32`, `--format u32`, `--format f64`, or `--format raw` as appropriate. Parameter indices and value encodings are model-dependent; `param get` prints all 8 raw value bytes by default, with optional `--format u8|u16|u32|s32|float|f64`. Do **not** infer parameter names, permissions or scalings without the manufacturer's model-specific table.

Parameter and clock writes default to dry-run, showing the complete frame **without opening the port**. Writing requires `--execute`:

```powershell
rtuforge.exe pulsar param set 17440707 0x0010 0102030405060708
rtuforge.exe --port COM4 --parity N pulsar param set 17440707 0x0010 0102030405060708 --execute
rtuforge.exe pulsar time set 17440707 2026-10-12T15:34:56
rtuforge.exe --port COM4 --parity N pulsar time set 17440707 2026-10-12T15:34:56 --execute
```

**WARNING:** The example parameter index and bytes are synthetic placeholders, **not** validated settings for N00014163. Parameter writes can alter calibration, configuration, accounting, or communications, and may be refused pending authorization. Changing clock impacts archives. Do not use `--execute` without confirming parameter mapping and implications on a test device. `discover --single` is a broadcast-style probe and is unsafe on a bus with several Pulsar devices.

The existing Modbus transport remains single-owner. `pulsar` always uses `crc_mode_override="none"` on frames that already contain CRC16; it does not mutate `runtime.crc_mode`, `decode_rx`, or other runtime options. Ordinary `send`, `scan`, and `standforge` work as before.

References: [Pulsar application-layer functions](https://docs.pulsarm.ru/spaces/PULSARPROTOCOLS/pages/75759667/), [Wiren Board Pulsar driver](https://github.com/wirenboard/wb-mqtt-serial/blob/master/src/devices/pulsar_device.cpp), [Pulsar Water model 1 template](https://github.com/wirenboard/wb-mqtt-serial/blob/master/templates/config-pulsar-water.json).
