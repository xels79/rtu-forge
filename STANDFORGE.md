# Stand Forge

Stand Forge is a small test-bench console built on RTU Forge's existing serial transport and configuration.

It controls two Waveshare Modbus RTU devices:

- 8-channel relay board: four tanks, two relays per tank.
- 8-channel analog output board: first four channels mapped to temperature, humidity, low pressure and high pressure.

## Tank commands

Relay mapping:

- Tank 1 -> relay 1 (lower float), relay 2 (upper float)
- Tank 2 -> relay 3, relay 4
- Tank 3 -> relay 5, relay 6
- Tank 4 -> relay 7, relay 8

States:

- `empty` -> both relays off
- `middle` -> lower relay on, upper relay off
- `full` -> both relays on

Examples:

```text
standforge tank 1 empty
standforge tank 1 middle
standforge tank 1 full
standforge tank 4 full
```

The two relays are written in one Modbus FC0F request.

## Analog output commands

Channel mapping:

1. temperature
2. humidity
3. pressure-low
4. pressure-high

Examples:

```text
standforge output temperature 50
standforge output humidity 75
standforge output pressure-low 25
standforge output pressure high 80
```

Percent is scaled into the configured physical output range.

Supported ranges:

- `0-20ma` -> 0..20000 uA
- `4-20ma` -> 4000..20000 uA
- `0-10v` -> 0..10000 mV

## Configuration

Stand Forge reuses RTU Forge's `config.ini` and `RTUFORGE_HOME` for serial settings.

Stand-specific settings are stored in `stand.ini` in the same home directory:

```ini
[devices]
relay_address = 1
output_address = 2

[output]
range = 0-20ma
```

Change them interactively:

```text
set relay-id 1
set output-id 2
set output-range 4-20ma
```

Or temporarily for one launch:

```bash
standforge --relay-id 5 --output-id 6 --output-range 0-10v status
```

Serial overrides are the same as RTU Forge:

```bash
standforge --port COM7 --baudrate 9600 tank 1 full
```

## Interactive shell

Run:

```bash
standforge
```

Prompt:

```text
stand>
```

The shell has persistent history and Tab completion.

Useful commands:

```text
tank <1..4> <empty|middle|full>
output <temperature|humidity|pressure-low|pressure-high> <0..100>
set <relay-id|output-id|output-range> <value>
connect
disconnect
ports
status
paths
help
exit
```

Hardware access is not exercised by unit tests. Tests use a fake transport and validate the generated Modbus frames and responses.
