# ElegooBridge

**Lets [Bambuddy](https://github.com/maziggy/bambuddy) manage an Elegoo Centauri
Carbon alongside Bambu Lab printers.**

ElegooBridge runs in Docker next to Bambuddy. It talks to the Centauri in its own
protocol (SDCP over a local WebSocket) and presents it to Bambuddy as a Bambu LAN
printer. Bambuddy itself is not modified.

```
Bambuddy  --MQTT/TLS :8883-->  Mosquitto  <-->  ElegooBridge  --SDCP :3030-->  Centauri Carbon
         (sees a Bambu P1S)
```

Version **0.1.0**, phase 1 of the plan below. **Not yet tested with a real
Bambuddy.**

## What works

| In Bambuddy | Status |
| --- | --- |
| Live card: state, progress, layers, remaining time, file name | ✓ |
| Nozzle, bed and chamber temperatures | ✓ |
| Preparation stages (heating, homing, levelling) | ✓, as close as the Centauri reports them |
| Finished and failed jobs, including power loss mid-print | ✓ |
| **Filament runout:** reported as Bambu error `0300_8004`, "Filament ran out" | ✓ |
| Pause, resume, stop | ✓ |
| Nozzle and bed temperature, part / auxiliary / chamber fans, chamber light, speed level | ✓ |
| Home and X/Y/Z jog (the printer must be homed before jogging) | ✓ |
| Camera, through Bambuddy's external camera: MJPEG, `http://PRINTER_IP:3031/video` | ✓ |
| Offline when the Centauri is off (after Bambuddy's 60 s timeout) | ✓ |
| **Starting prints from Bambuddy** | Not yet (phase 2) |
| Extruder jog, AMS / CANVAS, file manager, other G-code | No |

The bridge is tested against a fake Centauri. The Centauri commands it uses were
each tested on a real Centauri Carbon, firmware V1.4.49: see
[`docs/FINDINGS.md`](docs/FINDINGS.md).

## Set up

You need Docker, and the Centauri on the same network.

1. **Find the printer**, from this folder:
   ```sh
   python3 -m elegoobridge discover
   ```
   It prints the IP and `PRINTER_MAINBOARD_ID`.
2. **Configure:** copy `.env.example` to `.env` and fill it in. `ACCESS_CODE` is a
   password you choose; Bambuddy will use it.
3. **Create the TLS certificate**, once:
   ```sh
   ./scripts/make-certs.sh
   ```
4. **Start it:**
   ```sh
   docker compose up -d --build
   docker compose logs -f bridge
   ```
5. **Add the printer in Bambuddy:**

   | Field | Value |
   | --- | --- |
   | Model | **P1S**: enclosed, same 256 mm build volume, and the same three fans |
   | IP address | The computer running ElegooBridge, **not** the printer |
   | Serial number | `BAMBU_SERIAL` from `.env` |
   | Access code | `ACCESS_CODE` from `.env` |

**One bridge per printer.** Bambuddy expects each printer on its own IP address
with port 8883, so a second Centauri needs a second host or IP address.

## How states are shown

| Centauri | Bambuddy |
| --- | --- |
| Idle | IDLE, or FINISH / FAILED after a job, as on a Bambu printer |
| Heating, homing, levelling, file loaded | PREPARE, with a matching stage |
| Printing | RUNNING |
| Pausing / paused | PAUSE: "Paused by the user", or "Filament ran out" with error `0300_8004` |
| Completed | FINISH at 100 %: the Centauri itself stops at about 88 % |
| Stopping / stopped, or idle after losing power mid-job | FAILED |

The runout reason exists only while the printer is paused, in its print history.
The bridge reads it as the pause starts, about a minute before ElegooSlicer shows
it.

## Safety

- Only the commands tested in `docs/FINDINGS.md` are ever sent. Unknown SDCP
  commands can crash the printer's software.
- Other G-code from Bambuddy, such as moves or homing, is logged and ignored.
- Temperatures above 300 °C (nozzle) or 110 °C (bed) are refused.
- The Centauri's own network port has no password. Anything on your LAN can
  control it, with or without this bridge.

## Plan

1. ~~Research the protocol~~: done, see [`docs/FINDINGS.md`](docs/FINDINGS.md).
2. **Phase 1, status and control:** this version.
3. **Phase 2, starting prints:**
   - an FTPS server on port 990 for Bambuddy's uploads;
   - extract the plate G-code from the `.gcode.3mf`;
   - upload it to the Centauri and start it;
   - mark Centauri-sliced files so Bambuddy accepts them for a P1S card, as
     [klipper-bambuddy](https://github.com/ooniiik/klipper-bambuddy) does.
4. Test with a real Bambuddy; publish a Docker image.

## Development

```sh
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/python -m unittest discover -s tests -t .
```

The tests use a fake Centauri and a stand-in MQTT client, so no printer or broker
is needed. Without `paho-mqtt`, the bridge tests are skipped.

| Path | What |
| --- | --- |
| `elegoobridge/sdcp.py` | Centauri client: connection, keep-alive, reconnect, allow-listed commands, history |
| `elegoobridge/mapper.py` | Centauri status → Bambu `push_status` report |
| `elegoobridge/commands.py` | Bambuddy commands → Centauri commands |
| `elegoobridge/bridge.py` | Connects the two; reads pause reasons |
| `docs/` | Protocol findings and the test log |
| `tools/` | The scripts used to work out the protocol |
| `local/` | Private: your printer's details and raw recordings. Ignored by git. |

## Credits and licence

- The command formats come from [pycentauri](https://github.com/bjan/pycentauri)
  (Apache-2.0).
- The approach and the Bambu report fields follow
  [klipper-bambuddy](https://github.com/ooniiik/klipper-bambuddy) (MIT).
- Bambuddy is AGPL-3.0. ElegooBridge only talks to it over the network.

Licence: not chosen yet.

ElegooBridge isn't affiliated with Elegoo, Bambu Lab or the Bambuddy project.
