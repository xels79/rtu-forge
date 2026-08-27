# RTU Forge

A compact Python console for sending raw Modbus RTU frames, reading replies, and keeping reusable command scripts.

## Highlights

- Interactive shell with persistent history.
- Connection status in the prompt bottom toolbar.
- One-shot mode for scripts, batch files, CI, or quick terminal commands.
- Raw HEX `send` command.
- Automatic Modbus CRC handling.
- Named scripts stored separately in `scripts.ini`.
- Serial-port discovery, connection status, and contextual command help.
- Interactive command, script, option, help, and option-value autocomplete.
- Optional Modbus RX decoding after the unchanged raw response.
- Per-command `send --decode` / `send --raw` override.
- English and Russian help selected from `config.ini`.
- Settings stored separately in `config.ini`.
- Runtime option editing with persistence.
- Script delay and explicit `pause <ms>`.
- Windows COM and Linux serial paths.

## Install / run with uv

```bash
uv sync --extra dev
uv run rtuforge
```

Or one-shot:

```bash
uv run rtuforge send 01 03 00 65 00 01
```

With default `crc_mode=auto`, RTU Forge appends CRC when missing and preserves it when the frame already has a valid CRC.

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
run script <name>
scripts | ls | list
show script <name>
delete script <name>
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

Use Tab in interactive mode. Examples:

```text
co<TAB>                    -> connect
run script <TAB>           -> stored script names
set options <TAB>          -> mutable option names
set options language <TAB> -> en, ru
history <TAB>              -> clear
help <TAB>                 -> help topics
send --d<TAB>              -> --decode
```

## Response decoding

Raw TX/RX is always preserved when `show_tx` / `show_rx` are enabled.

Global default:

```ini
[runtime]
decode_rx = true
```

Change it interactively:

```text
set options decode_rx false
```

Force full decoding for one send even when the global option is disabled:

```text
send --decode 01 03 00 65 00 01
send -d 01 03 00 65 00 01
```

Suppress decoding for one send even when the global option is enabled:

```text
send --raw 01 03 00 65 00 01
send -r 01 03 00 65 00 01
```

The same syntax works in one-shot command-line mode:

```bash
uv run rtuforge send --decode 01 03 00 65 00 01
uv run rtuforge send --raw 01 03 00 65 00 01
```

`--decode` and `--raw` are RTU Forge options. They are removed before HEX parsing and are never transmitted to the Modbus device.

## Scripts

Scripts live in `scripts.ini`, separate from connection/runtime settings.

Create a script interactively:

```text
rtu> add script read-basic
... send 01 03 00 65 00 01
... pause 100
... send --decode 01 03 00 66 00 01
... # comments are allowed
... end script
```

Run it:

```text
run script read-basic
```

Inspect or delete it:

```text
show script read-basic
delete script read-basic
```

Useful commands that can be stored in scripts include:

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
scripts | ls | list
show script <name>
options [section]
set options <name> <value>
help [command]
```

Commands that are intentionally not allowed in scripts:

```text
add script ...
history
history clear
clear | cls
exit | quit
```

Empty lines and lines beginning with `#` are ignored. `runtime.inter_command_delay_ms` is inserted between stored script lines. `pause <ms>` adds an explicit additional delay.

For the full built-in explanation:

```text
help scripts
```

## Contextual help

General interactive help:

```text
help
```

Detailed help:

```text
help send
help scripts
help history
help set
```

The same command help works outside the interactive shell:

```bash
uv run rtuforge help scripts
uv run rtuforge help send
```

CLI invocation help remains separate:

```bash
uv run rtuforge --help
```

## Language

The UI help language is selected in `config.ini`:

```ini
[ui]
language = en
```

Supported values currently:

```text
en
ru
```

Change it from RTU Forge:

```text
set options language ru
```

After that:

```text
help
help scripts
help send
```

use Russian text. `uv run rtuforge --help` and one-shot `uv run rtuforge help ...` also use the configured language.

Switch back:

```text
set options language en
```

## One-shot commands

```bash
uv run rtuforge options
uv run rtuforge options connection
uv run rtuforge ports
uv run rtuforge status
uv run rtuforge help send
uv run rtuforge help scripts
uv run rtuforge set options port COM7
uv run rtuforge set options language ru
uv run rtuforge send 01 03 00 65 00 01
uv run rtuforge send --decode 01 03 00 65 00 01
uv run rtuforge run script read-basic
```

Mutating script creation is intentionally interactive because `add script ... end script` is a capture mode.

## Configuration

`config.ini` contains defaults and mutable settings.

### Connection

- `port`
- `baudrate`
- `bytesize`
- `parity`
- `stopbits`
- `timeout_ms`

### Runtime

- `inter_command_delay_ms`: delay between script commands.
- `post_write_delay_ms`: optional delay immediately after a serial write.
- `response_silence_ms`: silence interval used to decide that a reply frame is complete.
- `max_response_bytes`: hard cap for one received response.
- `crc_mode`: `auto`, `append`, or `none`.
- `auto_connect`: default auto-connect behavior for send/run.
- `show_tx`, `show_rx`: output toggles.
- `decode_rx`: default Modbus response decoding behavior.
- `timestamps`: prefix TX/RX with local timestamps.
- `uppercase_hex`: output formatting.

### History

- `file`: persistent history file.
- `max_entries`: history display/retention limit.

### UI

- `language`: help/CLI language, currently `en` or `ru`.

Change a value:

```text
set options inter_command_delay_ms 250
set options port COM6
set options crc_mode auto
set options decode_rx false
set options language ru
```

Changing a connection option while connected forces a disconnect so stale serial settings cannot linger.

## History

Interactive history is persistent. Use:

```text
history
history clear
```

Autocomplete is available:

```text
history <TAB>
```

and proposes `clear`.

## Development

Agent rules are in `AGENTS.md`.

Run tests:

```bash
uv run --extra dev pytest -q
```
