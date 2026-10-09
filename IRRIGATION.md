# Optional pressure-monitored irrigation

This is a **work-in-progress, hardware-disabled** state-machine implementation.
The existing `standforge` manual commands remain unchanged. No automatic
start command is registered until the hardware adapter has been commissioned.

## Intended command (not implemented yet)

`standforge start 1 1 broth 35` (rack 1, tier 1, 35% of configured VFD maximum).

## Mapping

- Rack/tier valve: 1/1=9, 1/2=10, 1/3=11, 2/1=12, 2/2=13, 2/3=14.
- Booster: relay 1.
- Broth selector: relay 23.
- Pump selector: relay 19 or 20 (requires an explicit choice).
- VFD RTU 7: terminal-start relay 32. RTU 8: terminal-start relay 31.
- AI module RTU 6: AI1 low pressure (0..6 bar); AI2 high pressure (0..100 bar).
- VFD frequency is to be set over RS485, startup is by FWD terminal.
- No tank level checks.

## States

IDLE -> VALVES -> BOOST -> STARTING -> RUNNING -> STOPPING -> IDLE.
If pressure rises too high, fails to rise, falls too low, or feedback fails:
STOPPING -> FAULT.

Normal STOP opens the drive-start contact and drops the booster/selector
but keeps the rack valve open until BOTH VFD actual output frequency is
near zero AND VFD RUN is false. With no valid feedback, the rack valve stays
open and the controller latches FAULT. Hardware emergency pressure/stop
interlocks are required separately.

## Commissioning blockers

No live control is exposed because the following have not been established:

1. Exact Waveshare 8CH **analog input** model and its Modbus input register
   map; calibration and 4-20mA/voltage scaling of all sensors.
2. Verified VFD runtime output-frequency and RUN/fault registers plus
   frequency scaling and setpoint readback.
3. Relay board Modbus slave ID, physical normally-open contact arrangement,
   selector relay 19 vs 20 for each pump, and independently wired E-stop.
4. Safe pressure thresholds and operating pressure units (the requested
   value '60' has not been independently confirmed as bar).
5. Behavior on controller/PC/serial power loss, valve opening timing,
   pressure relief and pump stop-time validation.

The code should be tested with a fake hardware adapter and then a supervised,
de-energized bench before it is connected to a live water system.
