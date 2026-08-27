# AGENTS.md - RTU Forge guardrails

These rules apply to Codex and any automated coding agent working in this repository.

## Product boundaries

- RTU Forge is a generic Modbus RTU serial console and script runner.
- Keep raw frame sending as a first-class feature. Do not force users into register abstractions.
- Do not silently change CRC semantics. `crc_mode=auto` means: preserve an already-valid CRC, otherwise append one.
- Never send serial data in tests. Hardware access must be behind `SerialTransport` and mocked/faked in tests.
- Never auto-connect merely to display help, options, scripts, or history.
- One-shot and interactive modes must use the same command execution layer.
- Persistent files are user-owned. Never overwrite `config.ini`, `scripts.ini`, or history unless the user explicitly invokes a mutating command.

## CLI compatibility

The following commands are public interface and must remain compatible unless the user explicitly requests a breaking change:

- `send <hex...>`
- `add script <name>` ... `end script`
- `run script <name>`
- `scripts`, `ls`, `list`
- `show script <name>`
- `delete script <name>`
- `options`
- `options connection`
- `set options <name> <value>`
- `connect`
- `disconnect`
- `pause <ms>`
- `history`, `history clear`
- `help`
- `exit`, `quit`

## Configuration rules

- New mutable options must be added to `OPTION_SPECS` and documented in README.
- Connection option changes must disconnect an active transport before being persisted.
- Delays must be configuration-driven or explicit `pause` script commands. Do not add unexplained sleeps.
- Keep time settings in milliseconds in config and convert to seconds only at API boundaries.

## Tests required before completion

Run:

```bash
uv run --extra dev pytest -q
```

At minimum maintain tests for:

1. Known Modbus CRC vectors.
2. `crc_mode=auto` with and without an existing CRC.
3. HEX parser validation.
4. Config defaults and option parsing.
5. Script save/load round trip.
6. Any command parser behavior changed by a patch.

If transport behavior changes, add fake-serial tests before touching hardware-facing code.

## Coding style

- Python 3.11+.
- Type hints on public functions and methods.
- Small modules with one responsibility.
- No global mutable serial connection.
- Prefer explicit errors over hidden fallback behavior.
- User-facing errors should explain the failed command and how to correct it.
- Keep Windows COM ports and Linux `/dev/tty*` paths supported.

## Codex workflow

Before editing:

1. Read this file and `README.md`.
2. Inspect relevant tests.
3. Make the smallest coherent change.
4. Run the full test suite.
5. Do not claim hardware validation unless real hardware was actually used.
