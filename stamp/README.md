# Stamp for Bambuddy

`stamp_for_bambuddy.py` prepares Centauri Carbon print files so Bambuddy will print
them through ElegooBridge. **Run it on your own computer**, where you slice. It has
nothing to do with Docker.

It's a single file that needs only Python 3, which macOS and Linux already have.
On Windows, install Python from python.org. You can copy this one file anywhere.

## Easiest on a Mac: the drag-and-drop app

Build it once (it needs only macOS):
```sh
./stamp/build-mac-app.sh
```
This creates **`stamp/dist/Stamp for Bambuddy.app`**. Move it to Applications or
keep it in the Dock. Then:

- **Drop** one or more `.gcode.3mf` files, or a whole folder, on the app. The
  stamped copies are saved **in the same folder as the originals**. For example,
  `~/Downloads/cube.gcode.3mf` gives `~/Downloads/cube.bambuddy.gcode.3mf`. A
  window lists what was stamped or skipped and where it was saved. **Show in
  Finder** selects the stamped files.
- Or **double-click** the app and choose the files.

The app contains the script and runs it with the Mac's own Python. The first time,
macOS may say it can't verify the developer: right-click the app → **Open** →
**Open**.

## Use from the command line

1. In ElegooSlicer, or OrcaSlicer with a Centauri Carbon profile, slice the plate,
   then choose **File → Export → Export plate sliced file**.
2. Stamp the file:
   ```sh
   python3 stamp_for_bambuddy.py ~/Downloads/cube.gcode.3mf
   ```
   ```
   Stamped: cube.gcode.3mf -> cube.bambuddy.gcode.3mf
     saved in /Users/you/Downloads
   ```
   Or a whole folder at once, for example your Downloads:
   ```sh
   python3 stamp_for_bambuddy.py ~/Downloads
   ```
   Tip: type `python3 ` and the script's path, then drag the file from Finder into
   the Terminal window to fill in its path.
3. **Add it to Bambuddy:** open Bambuddy → **File Manager** (left sidebar) →
   **Upload**, and choose the file ending in **`.bambuddy.gcode.3mf`**. You can also
   drag it from Finder onto the File Manager page. Then select it → **Print** →
   choose the **Centauri Carbon**.

Run it again after every new export. It never changes your original file and never
overwrites an earlier stamped copy. Files already stamped are skipped.

## Why it's needed

Bambuddy only prints a file on the printer model it was sliced for. ElegooBridge
shows the Centauri to Bambuddy as a **P1S**, but ElegooSlicer labels the file
**"Elegoo-CC"**. Without the stamp, Bambuddy refuses it: "…was sliced for
Elegoo-CC and cannot be dispatched to P1S printers".

## What it changes

| Part of the file | Change |
| --- | --- |
| `Metadata/slice_info.config`: `printer_model_id` | `Elegoo-CC` → `C12` (P1S) |
| `Metadata/project_settings.config`: `printer_model` | `Elegoo Centauri Carbon` → `Bambu Lab P1S` |
| **The G-code** | **Unchanged, byte for byte**. It still says it's for a Centauri. |
| Everything else | Unchanged |

It refuses files that weren't sliced for a Centauri Carbon, or have no sliced
G-code. ElegooBridge checks the G-code again before printing, so a file for
another printer can never reach the Centauri.
