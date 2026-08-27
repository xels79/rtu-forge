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
show record
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
show <TAB>                      -> script, record
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

## Clean output

Enable persistently:

```text
set options clean_output true
```

or only for one one-shot invocation:

```bash
uv run rtuforge -c run script idd-status
uv run rtuforge run script idd-status --clean
```

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

In clean mode TX/RX labels, timestamps, elapsed time and automatic decoding are hidden. Explicit `--decode/-d` still has priority.

## Exchange recording

Recording is process-local. `record start all` stores both request and response; `record start rx` stores responses only.

### Normal output mode

```text
record start all
send 01 03 00 65 00 01
```

The buffer contains:

```text
TX 01 03 00 65 00 01 94 15
RX 01 03 02 00 05 78 47
```

### Clean output mode

If `clean_output=true` or one-shot `-c/--clean` is active, `record start all` matches the visible clean format:

```text
01 03 00 65 00 01 94 15
01 03 02 00 05 78 47
```

So copying from the screen and saving the recording no longer produces two subtly different formats, a small victory over unnecessary inconsistency.

### Inspect current recording

Without stopping recording:

```text
show record
```

It prints the current in-memory record buffer exactly as it will be copied or saved. Recording remains active afterwards.

### Save/copy

```text
record stop buffer
record stop clipboard
record stop file captures/idd-status.txt
```

`buffer` and `clipboard` copy to the system clipboard. Relative file paths are resolved relative to `config.ini`. Parent directories are created automatically. Files are UTF-8 text.

Other commands:

```text
record status
record cancel
```

Recording can also be embedded in a stored script:

```text
record start rx
send 01 03 00 65 00 01
send 01 03 00 66 00 01
record stop file capture.txt
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

Useful script commands include `send`, `pause`, `connect`, `disconnect`, `status`, `ports`, nested `run script`, recording commands, `show record`, `options`, `set options`, and `help`.

Not allowed inside scripts: `add script`, `history`, `clear/cls`, `exit/quit`.

## Language

```ini
[ui]
language = en
```

Supported values: `en`, `ru`.

Switch:

```text
set options language ru
```

This localizes help, option table headings/descriptions, status text, shell messages, common errors, recording messages, and Modbus decoding labels/function names. Technical command names stay unchanged.

## One-shot behavior and errors

Examples:

```bash
uv run rtuforge send 01 03 00 65 00 01
uv run rtuforge run script idd-status -r
uv run rtuforge run script idd-status -c -r
```

One-shot mode suppresses automatic `Connected ...`. Expected user/runtime errors are caught and returned as concise messages with exit code `1`, without Python traceback.

## Configuration

### Connection

- `port`
- `baudrate`
- `bytesize`
- `parity`
- `stopbits`
- `timeout_ms`

### Runtime

- `inter_command_delay_ms`
- `post_write_delay_ms`
- `response_silence_ms`
- `max_response_bytes`
- `crc_mode`
- `auto_connect`
- `show_tx`, `show_rx`
- `decode_rx`
- `clean_output`
- `timestamps`
- `uppercase_hex`

### History

- `file`
- `max_entries`

### UI

- `language`: `en` or `ru`.

## Development

Agent rules are in `AGENTS.md`.

Run tests:

```bash
uv run --extra dev pytest -q
```
