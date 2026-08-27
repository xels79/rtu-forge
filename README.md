# RTU Forge

A compact Python console for raw Modbus RTU work, reusable scripts, response decoding, clean copy-friendly output, and exchange recording.

## Highlights

- Interactive shell with persistent history and Tab completion.
- One-shot mode for quick terminal commands and scripts.
- Raw HEX `send` with automatic Modbus CRC handling.
- Named scripts in `scripts.ini`.
- English and Russian help/UI selected in `config.ini`.
- Optional Modbus RX decoding.
- Per-command and per-script decode overrides.
- Clean output mode with plain HEX only.
- Recording of TX+RX or RX-only data to clipboard or file.
- Windows COM and Linux `/dev/tty*` paths.

## Install / run

```bash
uv sync --extra dev
uv run rtuforge
```

One-shot example:

```bash
uv run rtuforge send 01 03 00 65 00 01
```

One-shot auto-connect is silent: it does not print `Connected COM...` before command output.

## Interactive commands

```text
connect
disconnect
ports
status
send [-d|--decode|-r|--raw] <hex...>
add script <name>
  ...commands...
end script
run script <name> [-d|--decode|-r|--raw]
scripts | ls | list
show script <name>
delete script <name>
record start [all|rx]
record stop buffer
record stop clipboard
record stop file <path>
record status
record cancel
options
options connection
set options <name> <value>
pause <ms>
history
history clear
clear | cls
help [command]
exit | quit
```

## Tab completion

Examples:

```text
co<TAB>                         -> connect
run script <TAB>                -> stored script names
run script idd-status <TAB>     -> --decode, --raw, -d, -r
set options <TAB>               -> mutable option names
set options language <TAB>      -> en, ru
history <TAB>                   -> clear
record <TAB>                    -> start, stop, status, cancel
record start <TAB>              -> all, rx
record stop <TAB>               -> buffer, clipboard, file
send --d<TAB>                   -> --decode
```

## Response decoding

Global default:

```ini
[runtime]
decode_rx = true
```

Force decoding for one frame:

```text
send --decode 01 03 00 65 00 01
send -d 01 03 00 65 00 01
```

Suppress decoding for one frame:

```text
send --raw 01 03 00 65 00 01
send -r 01 03 00 65 00 01
```

The same flags can be applied to a whole script:

```text
run script idd-status -r
run script idd-status --raw
run script idd-status -d
run script idd-status --decode
```

Decode priority is:

```text
flag on individual send > flag on run script > runtime.decode_rx
```

So:

```text
run script idd-status -r
```

suppresses decoding for all ordinary `send` commands inside the script, while a stored line such as:

```text
send --decode 01 03 00 65 00 01
```

still forces decoding for that particular exchange.

## Clean output

Enable:

```text
set options clean_output true
```

or in `config.ini`:

```ini
[runtime]
clean_output = true
```

Normal output:

```text
TX 01 03 00 65 00 01 94 15
RX 01 03 02 00 05 78 47 (12.4 ms)
   Slave: 1
   Function: 03 Read Holding Registers
   ...
```

Clean output contains only HEX frame lines:

```text
01 03 00 65 00 01 94 15
01 03 02 00 05 78 47
```

In clean mode:

- `TX` / `RX` labels are hidden;
- timestamps and elapsed time are hidden;
- automatic response decoding is hidden;
- `show_tx` and `show_rx` still select which frame lines are printed;
- an explicit `send --decode` or `run script ... --decode` has priority and restores decoding.

This makes output convenient for direct copying into other tools without trimming labels manually, because apparently copying eight bytes should not require text surgery.

## Exchange recording

Recording is process-local and independent of screen output settings.

### Record request and response

```text
record start all
send 01 03 00 65 00 01
send 01 03 00 66 00 01
record stop buffer
```

`buffer` and `clipboard` are aliases and copy the recording to the system clipboard.

`all` format:

```text
TX 01 03 00 65 00 01 94 15
RX 01 03 02 00 05 78 47
TX 01 03 00 66 00 01 64 15
RX 01 03 02 00 02 39 85
```

### Record responses only

```text
record start rx
run script idd-status
record stop file captures/idd-status.txt
```

`rx` stores plain response HEX only:

```text
01 03 02 00 05 78 47
01 03 02 00 02 39 85
```

Relative file paths are resolved relative to `config.ini`. Parent directories are created automatically. Files are UTF-8 text.

Other recording commands:

```text
record status
record cancel
```

Recording can also be embedded into a stored script, which allows one-shot capture to a file in a single process:

```text
record start rx
send 01 03 00 65 00 01
send 01 03 00 66 00 01
record stop file capture.txt
```

Then:

```bash
uv run rtuforge run script capture-status
```

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

Useful script commands include:

```text
send ...
send --decode ...
send --raw ...
pause <ms>
connect
disconnect
status
ports
run script <name>
record start ...
record stop ...
record status
record cancel
scripts | ls | list
show script <name>
options [section]
set options <name> <value>
help [command]
```

Not allowed inside scripts:

```text
add script ...
history
history clear
clear | cls
exit | quit
```

Empty lines and lines beginning with `#` are ignored. `runtime.inter_command_delay_ms` is inserted between stored script lines. `pause <ms>` adds an explicit additional delay.

Detailed built-in help:

```text
help scripts
help run
help send
help record
```

## Language

Configuration:

```ini
[ui]
language = en
```

Supported values:

```text
en
ru
```

Switch to Russian:

```text
set options language ru
```

This localizes built-in help, option table headings/descriptions, status text, shell messages, common command errors, recording messages, and Modbus response decoding labels/function names.

Technical command names and option identifiers remain unchanged:

```text
send
run script
set options timeout_ms 1000
```

CLI invocation help also follows the selected language:

```bash
uv run rtuforge --help
```

## One-shot behavior and errors

Examples:

```bash
uv run rtuforge send 01 03 00 65 00 01
uv run rtuforge send --raw 01 03 00 65 00 01
uv run rtuforge run script idd-status -r
uv run rtuforge help record
uv run rtuforge options
```

One-shot mode suppresses the automatic `Connected ...` message.

Expected user/runtime errors are caught and returned as a concise error with exit code `1` instead of a Python traceback. For example, a missing script produces a normal message rather than exposing the internals of `KeyError`, which was never anyone's idea of a user interface.

## Configuration

### Connection

- `port`
- `baudrate`
- `bytesize`
- `parity`
- `stopbits`
- `timeout_ms`

### Runtime

- `inter_command_delay_ms`: delay between script commands.
- `post_write_delay_ms`: delay after a serial write.
- `response_silence_ms`: silence interval used to detect the end of a response.
- `max_response_bytes`: receive size cap.
- `crc_mode`: `auto`, `append`, or `none`.
- `auto_connect`: auto-connect for send/run.
- `show_tx`, `show_rx`: frame output toggles.
- `decode_rx`: default response decoding.
- `clean_output`: print copy-friendly plain HEX and suppress automatic decoding.
- `timestamps`: timestamp normal TX/RX output.
- `uppercase_hex`: HEX letter case.

### History

- `file`
- `max_entries`

### UI

- `language`: `en` or `ru`.

Examples:

```text
set options port COM6
set options timeout_ms 1000
set options crc_mode auto
set options decode_rx false
set options clean_output true
set options language ru
```

Changing a connection option while connected forces a disconnect.

## Development

Agent rules are in `AGENTS.md`.

Run tests:

```bash
uv run --extra dev pytest -q
```
