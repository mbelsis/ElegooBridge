# Future work: CANVAS and the Centauri Carbon 2

This is the plan for two extensions that need hardware the project doesn't have
yet:

1. **CANVAS**, Elegoo's 4-colour filament unit, on the original Centauri Carbon
   (CC1), shown in Bambuddy as an AMS.
2. **Centauri Carbon 2** (CC2), a newer printer with a different protocol.

Nothing here is implemented or tested. Everything ElegooBridge does today was
tested on a real CC1 first (see [`FINDINGS.md`](FINDINGS.md)), and both
extensions must follow the same rule: **no command reaches a printer until it
has been tried by hand on a real one, with someone standing next to it.**

Written 2026-10-31 from: the CC1's own web page (copy in
`local/refs/printer-web`), [pycentauri](https://github.com/bjan/pycentauri)
0.9.0 (`docs/PROTOCOL.md`, July 2026), Bambuddy's source, and Elegoo's product
pages. Recheck these before starting; firmware changes.

---

## Part 1: CANVAS on the Centauri Carbon (CC1)

### 1.1 What is known

**Hardware.** Elegoo sells a CANVAS made for the original Centauri Carbon
(released April 2026, about US$55). It's a different unit from the CC2's CANVAS;
the two aren't interchangeable. It has 4 slots, reads RFID filament tags and can
refill automatically.

**The printer side**, from the CC1's own web page (`25.*.js` in
`local/refs/printer-web`), which already supports CANVAS:

| Step | How the web page does it |
| --- | --- |
| Is a CANVAS connected? | `Status.AmsConnectStatus` in the status push (`1` = connected). Our printer, without a CANVAS, doesn't send this field at all. |
| Read the slots | **Cmd 324** `GET_MATERIAL_DATA`, data `{}`. Reply: `Data.canvas_list[0].tray_list[]`, each slot with `tray_id` (0–3), `filament_color` (`#RRGGBB`), `filament_name`, `status` (truthy = loaded). The web page sends it with an empty `Id` and `MainboardID`. |
| A file's colours | **Cmd 260** `GET_PRINTER_FILE_DETAIL`, data `{"Url": "<file name>"}`. Reply: `Data.FileInfo.ColorMapping[]` (one entry per filament used in the file, each with `tray_id` and `color`), plus `ColorNum`, `Thumbnail`, `EstTime`, `EstWeight`, `TotalLayers`. The page refuses files with more than 32 colours ("Color count exceeds the maximum allowed by the machine"). |
| Print with CANVAS | **Cmd 128** as today, but `slot_map` filled: `[{"t": <index in ColorMapping>, "canvas_id": 0, "tray_id": <slot 0–3>}, ...]`, one entry per colour. The page requires every colour to have a loaded slot ("Please select a print channel"). Without a CANVAS it sends `slot_map: []`, which is what the bridge sends today. |
| Colour data | **Cmd 503** `GET_FILE_COLOR_DATA` exists in the command table; its use is unknown. |

**Open questions** (answer these first, on the real printer):
- pycentauri lists Cmd 324 on CC1 as **unprobed**, and one source claims the
  CC1's CANVAS slots aren't readable over SDCP. The web page clearly uses 324,
  but on which firmware? Check the firmware version the CANVAS needs.
- Is `t` in `slot_map` the position in `ColorMapping` (the page uses the array
  index) or the file's filament number? Are they always the same?
- How do runout, auto-refill and filament changes show in the status push?
  (A new `CurrentStatus`, `PrintInfo.Status` or error code?)
- Does `AmsConnectStatus` appear only with a CANVAS, or after a firmware update?
- Elegoo's own SDK, [elegoo-link](https://github.com/ELEGOO-3D/elegoo-link)
  (Apache-2.0), has an `elegoo_fdm_cc` adapter. Read its CANVAS message formats
  before testing: they're the authoritative schema.

**The Bambuddy side.** Bambuddy shows an AMS from the `ams` block of a Bambu
status report, and sends the user's slot choice when printing:

- Status: `print.ams.ams[]` units with `id` and `tray[]`; each tray has `id`,
  `tray_type` (e.g. `PLA`), `tray_color` (`RRGGBBAA`), `tray_sub_brands`,
  `nozzle_temp_min/max`, `remain`. Plus `ams_exist_bits`, `tray_exist_bits` and
  `tray_now` (the active slot, `255` = none). Read
  `backend/app/services/bambu_mqtt.py` in Bambuddy for the exact fields it uses
  (`tray.get(...)` calls).
- Print: the `project_file` command gets `use_ams` and `ams_mapping`: a list with
  one entry per filament in the 3MF, each the **global tray id**
  (`ams_id * 4 + slot`, `254` = external spool, `-1` = unused). Also
  `ams_mapping2`.

### 1.2 Design

| Piece | Change |
| --- | --- |
| `sdcp.py` | Allow Cmd 324 (and 260, if used). Nothing else new. |
| `bridge.py` | When `AmsConnectStatus` is 1, ask for 324 at start, after every print and every few minutes while idle (not every status push). |
| `mapper.py` | New: CANVAS slots → `ams` block. One unit, `id "0"`, trays 0–3. `#RRGGBB` → `RRGGBBFF`. `filament_name` → `tray_type` and `tray_sub_brands`. Unloaded slot → empty tray. No CANVAS → no `ams` block (as today). |
| `commands.py` / `_start_job` | Read `ams_mapping` from `project_file`. Turn it into `slot_map`: for each filament `i` with tray `g` (0–3), add `{"t": i, "canvas_id": 0, "tray_id": g}`. **Refuse** the print (with a Bambu error, as for other refusals) if any tray is outside 0–3, a used filament has no slot, or a slot isn't loaded. |
| Stamp tool | Make sure the stamp keeps the file's filament list unchanged (it only changes the printer label today, so it should). Check Bambuddy shows each filament's colour for the mapping. |
| Tests | A fake CANVAS in the fake printer (`tests/test_sdcp.py`): replies to 324, `AmsConnectStatus` in status. Tests for the mapping, refusals and the `ams` block. |

Keep single-colour printing exactly as it is when no CANVAS is connected.

### 1.3 Steps

**Step 1: get the facts, read only.**
1. Note the printer's firmware version and the CANVAS's. Update both only if
   Elegoo says CANVAS needs it.
2. Record status pushes for 10 minutes with the CANVAS connected and idle
   (`tools/sdcp_record.py`). Look for `AmsConnectStatus` and any new fields.
3. Load filament into some slots, change one, remove one. Record again. Note
   which fields change.
4. Read elegoo-link's CC adapter for 324, 260 and `slot_map`.
5. Write everything into `FINDINGS.md`.

**Step 2: try each command by hand, with someone at the printer.**

| # | Test | Expect | Record |
| --- | --- | --- | --- |
| 2.1 | Cmd 324 once, idle | `canvas_list` with 4 slots matching what's loaded | The full reply |
| 2.2 | Cmd 324 during a print | Same, or a busy error | Whether it's safe mid-print |
| 2.3 | Cmd 260 on a multi-colour file sent from ElegooSlicer | `ColorMapping` with one entry per colour | Its fields; the meaning of `tray_id` there |
| 2.4 | Start a 2-colour test print from ElegooSlicer and capture the Cmd 128 it sends (check first whether the printer echoes other clients' commands to the recorder; if not, capture the slicer's traffic, e.g. with Wireshark) | `slot_map` filled | The exact `slot_map` |
| 2.5 | The same 2-colour file with Cmd 128 by hand, using the recorded `slot_map` | Prints with the right colours | Status during filament changes |
| 2.6 | Swap the slots in `slot_map` | Colours swap | Confirms the meaning of `t` and `tray_id` |
| 2.7 | Runout of one slot during a print (cut the filament, as in the CC1 runout test) | Pause or auto-refill | Status fields and error codes |
| 2.8 | Power cut during a multi-colour print | As on CC1? | Resume behaviour |

Use small test files (two-colour 20 mm cubes). Check the plate is clear before
every print.

**Step 3: build** (section 1.2), with tests against the fake CANVAS. All tests
must pass.

**Step 4: test through Bambuddy**, in order:
1. The AMS panel shows 4 slots with the right colours and types; it updates when
   a spool is changed.
2. Single-colour print with no AMS mapping: unchanged from today.
3. Single-colour print using a chosen slot.
4. Two-colour print with Bambuddy's mapping; check the colours on the part.
5. Refusals: a mapping to an empty slot, to the external spool (254) and with a
   missing slot. Each must show a failed job with an error, and the printer must
   do nothing.
6. Runout of a slot mid-print: shown in Bambuddy as a runout.
7. Pause, resume and stop during a multi-colour print.

**Step 5: document.** README "What works" table, `FINDINGS.md`, version bump.

---

## Part 2: Centauri Carbon 2 (CC2)

### 2.1 What is known

The CC2 is a different printer to the bridge: almost nothing of the CC1 protocol
carries over. From pycentauri's `docs/PROTOCOL.md` (CC2 firmware 01.03.02.51,
02.00.02.00 and 02.01.00.00, July 2026):

| | CC1 (today) | CC2 |
| --- | --- | --- |
| Control | SDCP over WebSocket, port 3030 | **MQTT 3.1.1, port 1883**, JSON-RPC style `{"id", "method", "params"}` |
| Password | None | MQTT user `elegoo`, password = the **access code** shown on the printer's screen |
| Setting needed | None | **"LAN Only" mode** on the printer, or the local API is closed |
| Discovery | UDP `M99999` broadcast | HTTP `GET /system/info?X-Token=<code>` gives the serial number |
| Topics | `sdcp/request/<MainboardID>` | `elegoo/<sn>/<client_id>/api_request`, `.../api_response`, `elegoo/<sn>/api_status` |
| Session | Keep-alive Cmd 0 | Register on `elegoo/<sn>/api_register`, then `{"type": "PING"}` every 30 s (**mandatory**: without it the printer silently stops answering after a few minutes) |
| Rate limit | None seen | 3 quick requests trigger a ~5 s silence: space requests at least 2 s apart |
| Status | Cmd 0 / push | Method 1002 / pushes 6000 and 6008 |
| Commands | 128–131 print, 401/402 move/home, 403 temps, fans, light, speed | 1020 start, 1021 pause, 1022 stop, 1023 resume, 1026 home, 1027 move, 1028 temperatures, 1029 light (`{"power": 0/1}`, not a toggle), 1030 fans (0–255, 3 settable), 1031 speed (`{"mode": 0-3}`) |
| Files | 258 list, HTTP `POST /uploadFile/upload` | 1044 list, 1047 delete, HTTP `PUT /upload` with `Content-Range` |
| Camera | MJPEG `:3031/video`, max 4 viewers | MJPEG `:8080`, any path, no password |
| CANVAS | Cmd 324 (unprobed) | **2005** status (`canvas_info.canvas_list[].tray_list[]`: `tray_id`, `filament_name/type/color/code`, `brand`, `min/max_nozzle_temp`, `status`; `active_tray_id`; `auto_refill`), **2004** auto-refill on/off |
| Bad commands | Unknown Cmd numbers can **crash** the printer's app | Answered with an error code (`1003`, `1010`) |

Not yet confirmed on a CC2 by anyone: 1020 start, 1021 pause, 1022 stop. Some
methods only work on newer firmware (1042, 1044, 1047 need 02.01.00.00).
Firmware 02.00.02.00 removed SSH and blocks downgrades.

### 2.2 Design

Split the printer side from the Bambu side, so the bridge talks to either model:

```
Bambuddy <-> Mosquitto <-> bridge.py <-> PrinterBackend
                                           ├── CC1Backend: sdcp.py (today's code)
                                           └── CC2Backend: cc2.py (new, MQTT)
```

1. **A backend interface** (`elegoobridge/printers/base.py`): connect, status
   callback, `pause/resume/stop`, `set_temperatures`, `set_fans`, `set_light(on)`,
   `set_speed(level)`, `home`, `move(axis, mm)`, `list_files`, `upload`, `start`,
   `canvas_status`, `camera_url`. Each backend has its **own allowlist** of
   tested commands, like `sdcp.ALLOWED` today.
2. **One common status format.** Today `mapper.py` reads SDCP fields directly.
   Each backend turns its printer's status into a common form (state, stage,
   progress, layers, times, temperatures, fans, light, speed, error, CANVAS
   slots); the mapper turns that into the Bambu report. The CC1 code moves
   behind the interface unchanged, and all current tests must still pass.
3. **`cc2.py`**: paho-mqtt client (already a dependency) to the printer's broker;
   registration, PING every 30 s, request/response matching by `id` on our own
   `api_response` topic, at least 2 s between requests, reconnect and
   re-register.
4. **Upload**: `PUT /upload` with `Content-Range` (see pycentauri's
   `upload.py`).
5. **Camera**: the existing relay, pointed at `:8080`.
6. **Config**: `PRINTER_MODEL=cc1|cc2` (or detect it: port 1883 answers on a
   CC2), `PRINTER_ACCESS_CODE` for the CC2. `setup.sh` and `setup.ps1` ask for
   the access code and remind the user to turn on LAN Only.
7. **Model check**: today `jobs.py` and the stamp accept any G-code whose
   `printer_model` contains "centauri". That would let a **CC2 file reach a CC1**
   or the other way round. Both must check the exact model and refuse the wrong
   one, with the same Bambu error as today.
8. **Bambuddy card**: keep P1S if the CC2 has the same build volume, enclosure
   and 3 controllable fans; check its specs.
9. **Firmware protection**: as for CC1, never forward an update.

### 2.3 Steps

**Step 1: read only.** Connect with pycentauri (`centauri status`,
`centauri watch`, `centauri canvas`), then with a small recorder script. Note the
firmware version, the status fields while idle, printing, paused, finished and
after a stop, and the CANVAS fields. Write it all into a new section in
`FINDINGS.md`.

**Step 2: each command by hand, with someone at the printer**, in this order,
recording the reply and the printer's behaviour:

| # | Command | Note |
| --- | --- | --- |
| 2.1 | 1029 light on, off | Check it's not a toggle |
| 2.2 | 1030 fans, one at a time | Which value moves which fan |
| 2.3 | 1028 nozzle 100 °C, bed 40 °C, then 0 | As on CC1 |
| 2.4 | 1026 home, then 1027 small moves on X, Y, Z | 1003 before homing |
| 2.5 | Upload a small file (`PUT /upload`), list it (1044) | Byte-exact |
| 2.6 | 1020 start a test cube | **Never confirmed by anyone**: find the exact params in elegoo-link first, or record what ElegooSlicer / Orca sends |
| 2.7 | 1021 pause, 1023 resume, 1022 stop, during the print | Status codes in each state |
| 2.8 | 1031 speed modes 0–3 during a print | Match to Bambu's 4 speed levels |
| 2.9 | Filament runout; power cut | As in the CC1 tests |
| 2.10 | 2005 CANVAS status; 1020 with a slot mapping | With a CC2 CANVAS |

**Step 3: build** (section 2.2). First move the CC1 code behind the interface
with no change in behaviour; test on the CC1 again (status, light, one print).
Then add the CC2 backend with a fake CC2 in the tests.

**Step 4: test through Bambuddy**: the same checklist as the CC1 (README "What
works"), plus the wrong-model refusals in both directions, plus Part 1 step 4 for
CANVAS.

**Step 5: document**: README (supported printers, CC2 setup with access code and
LAN Only), `FINDINGS.md`, setup scripts, version bump.

---

## How to help

If you have a CANVAS or a Centauri Carbon 2 and want this supported: open an
issue with your printer's firmware version, and run the read-only steps (Part 1
step 1, or Part 2 step 1). Recordings from a real printer are the most useful
thing to share. Remove your serial number, mainboard ID, IP and access code
first.
