# ElegooBridge

**Lets [Bambuddy](https://github.com/maziggy/bambuddy) manage an Elegoo Centauri
Carbon alongside Bambu Lab printers.**

ElegooBridge runs in Docker next to Bambuddy. It talks to the Centauri in its own
protocol (SDCP over a local WebSocket) and presents it to Bambuddy as a Bambu LAN
printer. Bambuddy itself is not modified.

```
Bambuddy  --MQTT/TLS :8883-->  Mosquitto  <-->  ElegooBridge  --SDCP :3030-->  Centauri Carbon
          --FTPS :990------------------------->  (uploads)    --HTTP :80---->  (G-code)
         (sees a Bambu P1S)
```

Version **0.2.0**. Tested with Bambuddy and a Centauri Carbon (firmware V1.4.49),
including a print sent from Bambuddy's queue.

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
| **Printing from Bambuddy** (library, queue): files must be stamped, see below | ✓ |
| File manager: the files Bambuddy uploaded | ✓ |
| Extruder jog, AMS / CANVAS, the Centauri's own stored files, other G-code | No |

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

## Printing from Bambuddy

Bambuddy only sends a file to a printer of the model it was sliced for, and the
card is a P1S. So Centauri files need a label change first:

1. In ElegooSlicer, or OrcaSlicer with a Centauri Carbon profile, slice the plate
   and use **File → Export → Export plate sliced file** (`.gcode.3mf`).
2. Stamp it, from this folder:
   ```sh
   python3 -m elegoobridge stamp ~/Downloads/cube.gcode.3mf
   ```
   This writes `cube.bambuddy.gcode.3mf` next to it. Only two labels change: the
   printer model in `slice_info.config` and in `project_settings.config`. The
   G-code is copied unchanged. Files not sliced for a Centauri are refused.
3. Add the stamped file to Bambuddy's **File Manager**, then print it on the
   Centauri card. Choose the external spool if asked about AMS slots.

When Bambuddy starts the print, the bridge:
- takes the plate's G-code out of the file;
- **checks it was sliced for a Centauri Carbon**, and refuses anything else;
- uploads it to the printer, then starts it.

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
- **Only print files can be uploaded** (`.gcode.3mf`, `.3mf`, `.gcode`). A Bambu
  firmware file, which Bambuddy's "update firmware" would upload, is refused, so
  nothing can try to update the Centauri. The bridge also reports version
  `99.01.04.49`, so Bambuddy never offers a Bambu update for it.
- Only G-code sliced for a Centauri Carbon is ever sent to the printer.
- Moves and homing are refused while the printer is busy or homing.
- The Centauri's own network port has no password. Anything on your LAN can
  control it, with or without this bridge.

## Plan

1. ~~Research the protocol~~: done, see [`docs/FINDINGS.md`](docs/FINDINGS.md).
2. ~~Phase 1, status and control~~: done.
3. ~~Phase 2, printing from Bambuddy~~: done.
4. Next:
   - report a refused print to Bambuddy at once, with the reason (today its
     90-second watchdog notices);
   - show the Centauri's own stored files;
   - switch the camera on through SDCP (386) after a restart;
   - answer the power-loss prompt from Bambuddy (134 / 135);
   - publish a Docker image.

## Development

```sh
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/python -m unittest discover -s tests -t .
```

The tests use a fake Centauri, a stand-in MQTT client and a real local FTPS
server, so no printer or broker is needed. Without the requirements installed,
the bridge and FTPS tests are skipped.

| Path | What |
| --- | --- |
| `elegoobridge/sdcp.py` | Centauri client: connection, keep-alive, reconnect, allow-listed commands, history |
| `elegoobridge/mapper.py` | Centauri status → Bambu `push_status` report |
| `elegoobridge/commands.py` | Bambuddy commands → Centauri commands |
| `elegoobridge/bridge.py` | Connects the two; reads pause reasons; starts prints |
| `elegoobridge/ftp_server.py` | FTPS server for Bambuddy's uploads (print files only, binary, Bambu-style TLS) |
| `elegoobridge/jobs.py` | Finds the upload, extracts the plate, checks it was sliced for a Centauri |
| `elegoobridge/upload.py` | Uploads G-code to the Centauri over HTTP |
| `elegoobridge/stamp.py` | Labels Centauri `.gcode.3mf` files for Bambuddy's P1S card |
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
