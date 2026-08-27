# RTU Forge

A compact Python console for sending raw Modbus RTU frames, reading replies, and keeping reusable command scripts.

## Highlights

- Interactive shell with persistent history.
- Connection status in the prompt bottom toolbar.
- One-shot mode for scripts, batch files, CI, or quick terminal commands.
- Raw HEX `send` command.
- Automatic Modbus CRC handling.
- Named scripts stored separately in `scripts.ini`.
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
send <hex...>
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
help
exit | quit
```

Example:

```text
rtu> add script read-basic
... send 01 03 00 65 00 01
... pause 100
... send 01 03 00 66 00 01
... end script
rtu> run script read-basic
```

## One-shot commands

```bash
uv run rtuforge options
uv run rtuforge options connection
uv run rtuforge set options port COM7
uv run rtuforge send 01 03 00 65 00 01
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
- `auto_connect`: reserved default for one-shot send/run behavior.
- `show_tx`, `show_rx`: output toggles.
- `timestamps`: prefix TX/RX with local timestamps.
- `uppercase_hex`: output formatting.

Change a value:

```text
set options inter_command_delay_ms 250
set options port COM6
set options crc_mode auto
```

Changing a connection option while connected forces a disconnect so stale serial settings cannot linger.

## Scripts

Scripts live in `scripts.ini`, separate from connection/runtime settings. Supported script lines are ordinary RTU Forge commands. `pause <ms>` is useful when a device needs breathing room between operations.

## History

Interactive history is persistent. Its file and size limit are configured in `[history]`.

## Development

Agent rules are in `AGENTS.md`.

Run tests:

```bash
uv run --extra dev pytest -q
```
