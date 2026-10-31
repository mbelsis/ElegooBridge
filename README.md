# ElegooBridge

**Goal:** let [Bambuddy](https://github.com/maziggy/bambuddy) manage an Elegoo
Centauri Carbon alongside Bambu Lab printers. It would run as a small Docker
container that talks to the Elegoo printer in its own language (SDCP over a local
WebSocket) and presents it to Bambuddy as a printer.

**Status:** research done; nothing built yet. On 2026-10-31 everything the bridge
needs was tested live on a Centauri Carbon with stock firmware V1.4.49:
- monitoring;
- file upload;
- start, pause, resume and stop;
- temperatures, fans and the light;
- offline handling and power-loss recovery;
- filament-runout detection, with its reason.

## Contents

| Path | What |
| --- | --- |
| [`docs/FINDINGS.md`](docs/FINDINGS.md) | The protocol as observed: commands, status codes, errors, quirks, and what the bridge must do |
| [`docs/TEST-LOG-2026-10-31.md`](docs/TEST-LOG-2026-10-31.md) | Every test, with times, commands sent and results |
| [`tools/`](tools/) | The standard-library Python scripts used for testing |
| `local/` | Private: your printer's address and raw recordings. Ignored by git. |

## Plan

1. **Design** how the bridge appears to Bambuddy. Either:
   - emulate a Bambu LAN printer (MQTT on 8883 and FTPS on 990), as
     [klipper-bambuddy](https://github.com/ooniiik/klipper-bambuddy) does for
     Klipper; or
   - add a "custom printer" type to Bambuddy (open request #2935).
2. **Status-only bridge first:** live state, progress, temperatures and errors
   in Bambuddy.
3. **Then control:** upload the plate G-code from Bambuddy's `.gcode.3mf`, then
   start, pause, resume and stop it; temperatures, fans and light.
4. **Package it** as a Docker image, configured with the printer's IP.

Licences to keep in mind:
- Bambuddy is AGPL-3.0, so the bridge stays a separate program that only talks to
  it over the network.
- pycentauri, the source of the command formats, is Apache-2.0: credit it.
- klipper-bambuddy is MIT.

ElegooBridge isn't affiliated with Elegoo, Bambu Lab or the Bambuddy project.
