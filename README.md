# ElegooBridge

**Lets [Bambuddy](https://github.com/maziggy/bambuddy) manage an Elegoo Centauri
Carbon alongside Bambu Lab printers.**

ElegooBridge runs in Docker next to Bambuddy. It talks to the Centauri in its own
protocol (SDCP over a local WebSocket) and presents it to Bambuddy as a Bambu LAN
printer. Bambuddy itself is not modified.

ElegooBridge follows the same idea as
[klipper-bambuddy](https://github.com/ooniiik/klipper-bambuddy), which does this
for Klipper printers: a small bridge that speaks the printer's own protocol on
one side and imitates a Bambu printer on the other, so
Bambuddy works with it unchanged. ElegooBridge uses the same Bambu report fields
and applies the approach to Elegoo's SDCP protocol.

```
Bambuddy  --MQTT/TLS :8883-->  Mosquitto  <-->  ElegooBridge  --SDCP :3030-->  Centauri Carbon
          --FTPS :990------------------------->  (uploads)    --HTTP :80---->  (G-code)
         (sees a Bambu P1S)
```

Version **0.3.0**. Tested with Bambuddy and a Centauri Carbon (firmware V1.4.49),
including a print sent from Bambuddy's queue.

> ⚠️ **Before printing from Bambuddy:** sliced files must be stamped first, on your
> own computer, with the **Stamp for Bambuddy** Mac app (drag and drop) or a
> Python script. See [Printing from Bambuddy](#printing-from-bambuddy).

## Screenshots

The Centauri Carbon in Bambuddy, through ElegooBridge:

| Printing a file sent from Bambuddy's queue | Fan control during a print |
| --- | --- |
| ![The Centauri Carbon card in Bambuddy, printing at 48 %, layer 71 of 128](Screenshots/SamplePrinting.png) | ![Setting the auxiliary (side) fan speed](Screenshots/FansSpeed.png) |

| Temperature control after a finished print | Live camera |
| --- | --- |
| ![Setting the nozzle temperature](Screenshots/TempConfiguration.png) | ![The Centauri's camera view next to its card](Screenshots/Camera.png) |

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
| **Camera**, built in: live view and snapshots, as a P1S camera on port 6000. Any number of viewers share one connection to the printer, which allows only four. | ✓ |
| Offline when the Centauri is off (after Bambuddy's 60 s timeout) | ✓ |
| **Printing from Bambuddy** (library, queue): files must be stamped, see below | ✓ |
| A refused print shows on the card at once as a failed job with a Bambu error, e.g. `0500_4037` "not compatible with current printer model" | ✓ |
| File manager: the files Bambuddy uploaded | ✓ |

**Not supported yet** (the bridge refuses these and the printer does nothing):

| In Bambuddy | Why |
| --- | --- |
| Extruder jog (extrude / retract buttons) | The Centauri has no documented command for it, and the bridge only sends tested commands |
| AMS filament slots and colours | The Centauri's CANVAS unit isn't mapped to Bambu's AMS yet; prints use the loaded filament |
| Files already stored on the Centauri (e.g. sent from ElegooSlicer) | The file manager shows only the files Bambuddy uploaded; planned, see [Plan](#plan) |
| Any other G-code command | The Centauri doesn't accept raw G-code. The bridge translates temperatures (M104/M109, M140/M190), fans (M106/M107), X/Y/Z moves (G0/G1, G90/G91) and homing (G28) |

## Testing

**On a real printer.** Everything marked ✓ above was tested on a real Centauri
Carbon (firmware V1.4.49) with Bambuddy: every printer command the bridge uses,
a full print sent from Bambuddy's queue, pause, resume and stop, a power cut
during a print and a filament runout. The results are in
[`docs/FINDINGS.md`](docs/FINDINGS.md).

**Automated tests.** The project's tests (see [Development](#development)) check the bridge's
own code against a simulated Centauri that answers like the real one, so they run
in seconds without a printer switched on.

## Set up

### What you need

- **Docker Desktop**, installed and **running**: download it from
  [docker.com/products/docker-desktop](https://www.docker.com/products/docker-desktop/)
  for Mac or Windows. On Linux, Docker Engine with the Compose plugin also works.
  ElegooBridge runs inside Docker, so nothing else needs installing.
- The **Centauri Carbon switched on**, on the same network as this computer.
- **Bambuddy**, running anywhere on your network, to add the printer to.

Then download or clone this repository, and set it up with the quick setup script
or by hand.

### Quick setup (recommended)

The setup script does everything below for you:
- checks Docker Desktop is installed and running;
- finds the Centauri on your network;
- creates the settings with a random access code;
- starts ElegooBridge and waits until it's connected to the printer;
- prints exactly what to enter in Bambuddy.

| | |
| --- | --- |
| **Mac or Linux** | In a terminal, in this folder: `./setup.sh` |
| **Windows** | Double-click **`setup.bat`** (or run it from a command prompt in this folder) |

Press Enter to accept the suggested values. At the end you'll see something like:

```
ElegooBridge is running and connected to the printer.

Now add the printer in Bambuddy (Printers > Add Printer):
  Model:          P1S
  IP address:     192.168.1.20      this computer, not the printer
  Serial number:  0390000ELEGOO01   made up: a Bambu-style name for the bridge
  Access code:    48213907          random: a password for the bridge
```

The Centauri has no serial number or access code that Bambuddy could use, so the
bridge provides both:

- **Serial number:** made up. Bambuddy needs a Bambu-style serial (15 letters
  and digits) to address the printer, so the bridge uses `0390000ELEGOO01`.
  You can choose your own in `.env` (`BAMBU_SERIAL`), for example
  `0390000ELEGOO02` for a second bridge, or `01P00ACENTAUR01`. It isn't the
  Centauri's real ID (that is `PRINTER_MAINBOARD_ID`, which only the bridge uses).
- **Access code:** a random 8-digit code the setup script creates
  (`ACCESS_CODE` in `.env`), or any password you type, up to 20 characters.
  Bambuddy must send it to use the bridge, its file upload and its camera. The
  Centauri itself has no password.

Run the script again at any time. It keeps your settings unless you choose to
change them, and restarts the bridge with any updates.

### Manual setup

1. **Find the printer**, from this folder. This needs Python 3, which Macs and
   Linux already have:
   ```sh
   python3 -m elegoobridge discover
   ```
   It prints the printer's IP and its `PRINTER_MAINBOARD_ID`.
2. **Configure:** copy `.env.example` to `.env` and fill it in.
   - `BRIDGE_HOST_IP` is **this** computer's IP address.
   - `ACCESS_CODE` is a password you choose, up to 20 characters. Bambuddy will
     use it.
3. **Start it:**
   ```sh
   docker compose up -d --build
   docker compose logs -f bridge
   ```
   The TLS certificate Bambuddy connects with is created automatically the first
   time.

### Add the printer in Bambuddy

Bambuddy sees the bridge as a Bambu Lab **P1S**, so you add it like a P1S. The
setup script prints the values to use; they are also in `.env`.

1. Open Bambuddy in your browser and go to **Printers**.
2. Click **Add Printer**. Bambuddy's network scan won't find the bridge, so fill
   in the form by hand:

   | Field | Enter |
   | --- | --- |
   | Name | Anything, e.g. `Centauri Carbon` |
   | IP Address | The computer running ElegooBridge (`BRIDGE_HOST_IP`), **not** the printer's IP |
   | Serial Number | `BAMBU_SERIAL` from `.env` (default `0390000ELEGOO01`) |
   | Access Code | `ACCESS_CODE` from `.env` |
   | Model | **P1S**: enclosed, same 256 mm build volume, and the same three fans |

3. Save. Within a few seconds the card shows the Centauri's state and
   temperatures. If it stays offline, check `docker compose logs -f bridge`.
4. Leave **External camera** off in the printer's settings: the camera works
   through the bridge.

**One bridge per printer.** Bambuddy expects each printer on its own IP address
with port 8883, so a second Centauri needs a second host or IP address.

## Printing from Bambuddy

> **Important: stamp every file before you add it to Bambuddy.**
> Files from ElegooSlicer (or OrcaSlicer with a Centauri profile) can't be printed
> from Bambuddy as they are. Stamp them first, each time you export: drop them on
> the **Stamp for Bambuddy** Mac app, or run the Python script. Both run on your
> own computer, where you slice, not in Docker.

### Why

Bambuddy only sends a file to a printer of the same model it was sliced for. The
bridge shows the Centauri to Bambuddy as a **P1S**, but a file sliced for the
Centauri says **"Elegoo-CC"**. Without the stamp, Bambuddy refuses to print it,
with a message like:

> test.gcode.3mf was sliced for Elegoo-CC and cannot be dispatched to P1S printers

The stamp changes only that label, to P1S, so Bambuddy accepts the file.

### How: the three steps

1. **Slice for the Centauri.** In ElegooSlicer, or OrcaSlicer with a Centauri
   Carbon profile, slice the plate, then choose **File → Export → Export plate
   sliced file**. You get a `.gcode.3mf` file. A project saved with **Save
   project** has no G-code and can't be stamped. The menu item is greyed out
   until the plate is sliced.
2. **Stamp it**, with the Mac app or the Python script (both below). The stamped
   copy is saved **next to the original**, with `.bambuddy.gcode.3mf` at the end:
   `~/Downloads/cube.gcode.3mf` → `~/Downloads/cube.bambuddy.gcode.3mf`.
3. **Add the stamped file to Bambuddy.** Open **File Manager** in the left sidebar
   → **Upload**, or drag the file onto that page. Then select it → **Print** →
   **Centauri Carbon**. If asked about AMS slots, choose the external spool.

### Stamping with the Mac app (easiest)

**Stamp for Bambuddy.app** is a drag-and-drop app. Build it once, in this folder;
it needs only macOS:

```sh
./stamp/build-mac-app.sh
```

It's created in `stamp/dist/Stamp for Bambuddy.app`. Move it to **Applications**,
or drag it into the Dock. Then:

- **Drop** one or more sliced `.gcode.3mf` files, or a whole folder, onto the app.
- Or **double-click** the app and choose the files.

A window shows what was stamped and where it was saved. **Show in Finder** selects
the stamped files, ready to drag into Bambuddy.

![The Stamp for Bambuddy window after stamping a file](Screenshots/FileStamp.png)

If a file can't be stamped, for example a project without sliced G-code or a file
for another printer, the window says why and what to do instead.

The first time you open it, macOS may say it can't verify the developer. Right-click
the app → **Open** → **Open**. It's built and signed on your own Mac, not
notarised by Apple.

### Stamping with Python (Mac, Linux or Windows)

The app is a wrapper around one self-contained script,
[`stamp/stamp_for_bambuddy.py`](stamp/stamp_for_bambuddy.py). It needs only
Python 3: already installed on macOS and Linux; on Windows, install it from
python.org. Run it from any folder, or copy the file anywhere.

```sh
# one file
python3 stamp/stamp_for_bambuddy.py ~/Downloads/cube.gcode.3mf

# several files
python3 stamp/stamp_for_bambuddy.py cube.gcode.3mf vase.gcode.3mf

# every sliced file in a folder
python3 stamp/stamp_for_bambuddy.py ~/Downloads
```

```
Stamped: cube.gcode.3mf -> cube.bambuddy.gcode.3mf
  saved in /Users/you/Downloads
Skipped: project.3mf: no sliced G-code inside: slice the plate, then use "Export plate sliced file"
```

Files that are already stamped, or already have a stamped copy, are skipped, so
running it again over a folder is safe. On Windows, use `py` instead of `python3`.
On a Mac, you can type the command and then drag the file from Finder into the
Terminal window to fill in its path.

**Re-slice, re-stamp.** If you change anything and export again, stamp the new
export too. The stamp never changes your original file and never overwrites an
existing stamped file. Delete the old `.bambuddy.gcode.3mf` first, or keep both.

### What the stamp changes, and what it doesn't

| Part of the file | Stamped |
| --- | --- |
| `Metadata/slice_info.config`: `printer_model_id` | `Elegoo-CC` → `C12` (P1S) |
| `Metadata/project_settings.config`: `printer_model` | `Elegoo Centauri Carbon` → `Bambu Lab P1S` |
| **The G-code** | **Unchanged, byte for byte**. It still says it was sliced for the Centauri. |
| Everything else (thumbnails, settings, model) | Unchanged |

The stamp refuses files that weren't sliced for a Centauri Carbon, and files with
no sliced G-code.

### What happens when Bambuddy prints it

The bridge receives the file and:
- takes the plate's G-code out of it;
- **checks that G-code was sliced for a Centauri Carbon**, and refuses anything
  else, so a real P1S file can never reach the Centauri;
- uploads it to the printer, then starts it.

If the bridge refuses a file, the Centauri card shows a failed job with the
reason, for example `0500_4037` "Your sliced file is not compatible with current
printer model".

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
   - show the Centauri's own stored files;
   - switch the camera on through SDCP (386) after a restart, if it comes back
     without a picture;
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
| `elegoobridge/camera.py` | Camera relay: one MJPEG connection to the printer, served as a P1S camera on port 6000 |
| `stamp/` | **Standalone script** that labels Centauri `.gcode.3mf` files for Bambuddy's P1S card; runs on your own computer |
| `docs/` | Protocol findings and the test log |
| `setup.sh`, `setup.bat`, `scripts/setup.ps1` | Quick setup for Mac/Linux and Windows |
| `elegoobridge/certs.py` | Creates the TLS certificate on first start, inside Docker |
| `tools/` | The scripts used to work out the protocol |
| `local/` | Private: your printer's details and raw recordings. Ignored by git. |

## Credits and licence

- The command formats come from [pycentauri](https://github.com/bjan/pycentauri)
  (Apache-2.0).
- The approach and the Bambu report fields follow
  [klipper-bambuddy](https://github.com/ooniiik/klipper-bambuddy) (MIT).
- Bambuddy is AGPL-3.0. ElegooBridge only talks to it over the network.

**Licence: [MIT](LICENSE).** ElegooBridge is free: use it, copy it, change it
and share it in any way, including in your own projects, as long as the licence
notice stays with it. It comes with no warranty.

ElegooBridge isn't affiliated with Elegoo, Bambu Lab or the Bambuddy project.
