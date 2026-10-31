# Elegoo Centauri Carbon: protocol findings

What the Centauri Carbon (CC1) does on the local network, tested live on one printer
on 2026-10-31. Firmware **V1.4.49** (stock), protocol **SDCP V3.0.0**. Every item
below was seen on the wire unless it is marked *unconfirmed*.

The command formats come from [pycentauri](https://github.com/bjan/pycentauri)
(Apache-2.0), `docs/PROTOCOL.md`. That project tested older firmware (V1.1.46 and
OpenCentauri V0.3.0-o). The results here confirm them on V1.4.49.

> **Safety:** pycentauri reports that *unrecognised* `Cmd` numbers can crash the
> printer's main program (`app`). Send only the commands listed here.

## Network

| Port | Use |
| --- | --- |
| UDP 3000 | Discovery: send `M99999`, get a JSON description back |
| TCP 3030 | WebSocket `ws://IP:3030/websocket`, the control and status channel |
| TCP 3031 | Camera stream (not tested) |
| TCP 80 | Printer web page and file upload |
| 7125, 8080 | Closed (no Moonraker) |

- **No authentication** on any of them. Anyone on the LAN can control the printer.
- **Discovery only answers broadcasts** (for example to `192.168.1.255`), not a
  probe sent straight to the printer's address. Configure the IP instead.

## Messages

A request:

```json
{"Id": "", "Topic": "sdcp/request/<MainboardID>",
 "Data": {"Cmd": 0, "Data": {}, "RequestID": "<hex uuid>",
          "MainboardID": "<MainboardID>", "TimeStamp": 1793427840, "From": 1}}
```

Replies arrive on `sdcp/response/<id>` (an `Ack`, 0 = accepted),
`sdcp/status/<id>` and `sdcp/attributes/<id>`.

**The printer never sent anything on `sdcp/notice` or `sdcp/error`.** That held
through two runouts, a power cut, a power loss mid-print, and pause/resume/stop.
Errors have to be worked out from status plus print history (see *Errors*).

### Connection behaviour

- Status is **pushed automatically**: every 1–3 s while busy, and on change.
- The printer **closes the socket after about 60 s** if the client sends nothing.
  Sending `Cmd 0` every 25 s kept one connection open for over 10 minutes.
- Answer WebSocket pings with pongs.
- Power off closes the socket cleanly (EOF), with no message first.
- After a restart it took 4–5 minutes, power-off time included, before the
  printer accepted connections again. It sends no "I restarted" message.
  Recognise a restart by the reconnect plus the reset fields.
- Several clients can be connected at once, for example the bridge, ElegooSlicer
  and a second test script.

## Commands verified on V1.4.49

| Cmd | Purpose | Data | Result |
| --- | --- | --- | --- |
| 0 | Status | `{}` | Status push |
| 1 | Attributes | `{}` | Attributes push |
| 258 | List files | `{"Url": "/local"}` | `FileList[]`: `name` (`/local/...`), `FileSize`, `TotalLayers`, `type` |
| 320 | Print history IDs | `{}` | `HistoryData[]` of task IDs, newest first |
| 321 | History detail | `{"Id": ["<TaskId>", ...]}` | `HistoryDetailList[]` (see *Errors*) |
| 128 | Start print | see below | Starts; preheat and levelling as from the screen |
| 129 | Pause | `{}` | 13 → 5 pausing → 6 paused within 8–13 s |
| 131 | Resume | `{}` | 6 → 20 → 13 printing |
| 130 | Stop | `{}` | → 7 stopping (heaters off at once) → 8 stopped, idle within about 9 s |
| 401 | Move an axis | `{"Axis": "X\|Y\|Z", "Step": ±mm}` | Relative. The printer's panel offers 0.1, 1, 10 and 100. Refused until homed (`Ack 3`). |
| 402 | Home | `{"Axis": "X\|Y\|Z\|XYZ"}` | `CurrentStatus` 9 while homing; XYZ took 67 s |
| 403 | Fans | `{"TargetFanSpeed": {"ModelFan": 0-100}}` | Any subset of `ModelFan`, `AuxiliaryFan`, `BoxFan` |
| 403 | Temperatures | `{"TempTargetNozzle": °C, "TempTargetHotbed": °C}` | Works while idle |
| 403 | Light | `{"LightStatus": {"SecondLight": 0 or 1}}` | **Toggles** whatever value is sent (see quirks) |

Errors for 401 and 402, in the reply's `Ack`, as the printer's web page words them:
- 1: the machine is busy
- 2: parameter error
- 3: "Please zero the moving axis before moving"
- 4, 5: zeroing failed

### The printer's own command list

The printer's built-in web page (`http://IP/`, also shown in ElegooSlicer's
Device tab) names every SDCP command it uses, in its script `main.*.js`:

| Cmd | Name | Notes |
| --- | --- | --- |
| 0, 1 | Status, attributes | |
| 64 | Disconnect | |
| 128–131 | Start, pause, stop, resume | |
| 134 | Power-loss status | Sent on every connect. `Ack 1` = an unfinished job is waiting: the page asks "Resume printing?". |
| 135 | Power-loss action | `{"action": 1}` resumes, `0` cancels |
| 192 | Rename printer | |
| 255 | File transfer end | |
| 257–260 | Rename, list, delete, detail of files | |
| 320–324 | History IDs, detail, delete, time-lapse video, material data | |
| 386 | Video stream | `{"Enable": 1}` or `0`; the reply carries `VideoUrl` |
| 387 | Time-lapse on/off | |
| 401, 402, 403 | Move, home, set parameters | As above |
| 503 | File colour data | |

The control panel's own scripts (`25.*.js`) show how it uses them:
- Moves and homing are only sent when `CurrentStatus` doesn't contain 1.
- The light is sent as the whole `LightStatus` object.
- The side fan's on/off switch sets 70 %.

Start print:

```json
{"Filename": "name.gcode", "StartLayer": 0, "Calibration_switch": 1,
 "PrintPlatformType": 0, "Tlp_Switch": 0, "slot_map": [], "path_prefix": "/local"}
```

`Filename` is the bare name; `path_prefix` gives the storage. `Calibration_switch`
1 = auto-levelling, `Tlp_Switch` = time-lapse.

### File upload (HTTP, not WebSocket)

`POST http://IP/uploadFile/upload`, multipart form data, one request per chunk of up
to 1 MiB, with these fields:
- `Check=1`
- `S-File-MD5` (MD5 of the whole file)
- `Offset`
- `Uuid` (one per upload)
- `TotalSize`
- `File` (the chunk, sent with the name it should have on the printer)

Success is `{"code": "000000", "success": true}`. A 275 KB file took 0.2 s. It shows
up in `Cmd 258` a moment later, not instantly. Only `.gcode` files are accepted
(`SupportFileType: ["gcode"]`). `GET /downloadFile/local/<name>` returned 404.

## Status fields

From `sdcp/status`, under `Status`:

| Field | Meaning |
| --- | --- |
| `CurrentStatus` | List; 0 idle, 1 busy with a job, **9 homing**, 10 filament load/unload from the screen, 2/8 brief at job start |
| `PrintInfo.Status` | Job state (table below) |
| `PrintInfo.CurrentLayer`, `TotalLayer` | Layers. `TotalLayer` appears once the file is loaded (state 18). |
| `PrintInfo.CurrentTicks`, `TotalTicks` | Elapsed and estimated seconds. Remaining = total − current. |
| `PrintInfo.Progress` | **Time-based**: Current ÷ Total ticks, not layers |
| `PrintInfo.Filename`, `TaskId` | Empty until state 18; cleared on stop and completion |
| `PrintInfo.PrintSpeedPct` | 100 normally; 50 for a few layers after power-loss recovery |
| `TempOfNozzle`, `TempOfHotbed`, `TempOfBox` and `TempTarget…` | °C. Updated every 1–3 s, sooner than the printer's screen. |
| `CurrentFanSpeed.ModelFan`, `AuxiliaryFan`, `BoxFan` | **The set value, not a measured speed** |
| `LightStatus.SecondLight` | Chamber light 0/1 |
| `CurrenCoord` | `"x,y,z"` (sic) |
| `PlatFormType` | Flicked 0 → 1 → 0 when a print was started from the screen |

### `PrintInfo.Status`

| Code | Meaning on this printer | pycentauri's name |
| --- | --- | --- |
| 0 | Idle | IDLE |
| 1 | Homing (alternates with 21 during preparation) | HOMING |
| 5 | Pausing | PAUSING |
| 6 | Paused | PAUSED |
| 7 | Stopping | STOPPING |
| 8 | Stopped | STOPPED |
| 9 | **Completed** | COMPLETED |
| 13 | **Printing** | PRINTING |
| 14 | *Error (not seen)* | ERROR |
| 15 | Levelling (seen when started from the screen) | LEVELING |
| 16 | Heating | PREHEATING |
| 18 | File loaded: file name, layers and total time appear | PRINT START |
| 20 | "Preparing": the screen showed both "preheating" and "auto-levelling" during it | PREHEAT DONE |
| 21 | Alternates with 1 during preparation | HOMING DONE |

pycentauri lists more (2–4, 10–12, 17, 19, 22–26) that weren't seen here.

Typical sequences:
- **Start:** 0 → 16 → 20 (≈3 min of levelling) → 18 → 1/21 alternating → 16 → 20 → 13.
- **Normal end:** 13 → **9** → 0 about 1.5 min later. Progress jumps from about 88 %
  to 0 and never reports 100.
- **Stop:** 13 or 6 → 7 → 8 → 0.

## Errors

The printer never says *why* something happened in the live status. The reason is
in the print history, but **only while the job is paused**.

**Filament runout**, tested twice. The sensor sits at the rear filament inlet.
1. Its LED goes off as soon as the filament end passes it.
2. The printer keeps printing for about **4 minutes**, using the filament still in
   the tube.
3. Then `PrintInfo.Status` goes 13 → 5 → 6. No error or notice message is sent.
4. **At that moment** the history (`Cmd 320` → `Cmd 321` with the current `TaskId`)
   has an entry for the running job with `TaskStatus: 5` and
   **`ErrorStatusReason: 45`**: "Consumables are about to run out, please replace
   consumables". The bridge had it about **1 minute before ElegooSlicer** showed the
   message. ElegooSlicer shows it once the state reaches 6.
5. After resume, the entry **disappears**. If the job is stopped while paused, the
   entry turns into `TaskStatus: 3` with reason 0. **So read the reason as soon as
   the state turns to 5 or 6.**
6. Loading filament during the pause produced no separate state. Resuming from the
   screen gave 6 → 20 → 13.

**Manual pause** (`Cmd 129`) produced *no* history entry for the running job. So:
paused **and** a history entry with a reason = an error pause; paused with no entry
= a user pause. That's based on one example of each.

**Power loss mid-print:**
- After the restart, the screen shows "Uncompleted job detected – Cancel / Resume".
- Meanwhile the network status says **idle (0)**, and nothing is in the history.
  The bridge can't see the prompt.
- Resume continues at the same layer with a **new `TaskId`**: status 16 → 20 → 1/21
  → 13, `PrintSpeedPct` 50 for about 10 layers, then 100. The job then completed
  normally (state 9).

History detail fields:
- `TaskName`, `TaskId`, `BeginTime`, `EndTime` (Unix time)
- `TaskStatus`: 1 completed, 3 stopped, 5 paused
- `AlreadyPrintLayer` (unreliable: once 17062), `SliceInformation.total_layer_numbers`
- `ErrorStatusReason`, `MD5`

**Error reason texts:** Elegoo publishes the CC firmware in
[elegooofficial/CentauriCarbon](https://github.com/elegooofficial/CentauriCarbon).
The web UI's `firmware/resources/e100/www/assets/i18n/network-en.json` maps
`networkDeviceManager.control.errorStatusReason`, but only contains **45**. The
full list still has to be found in the firmware source.

The history keeps only a few entries: 3–6 seen.

## Quirks

- **After a power cut the printer can come back in a bad state.** On 2026-10-31,
  the camera stream sent no frames (HTTP 200, 0 bytes), even in ElegooSlicer. A
  home command (402) was accepted, but homing never ran and `CurrentStatus` stayed
  9. Meanwhile the printer ignored fan commands, even from its own touchscreen.
  Switching it off and on fixed everything, and the same home then worked.

- **Light:** `SecondLight: 0` turned the light on and `1` turned it off, starting
  from off. Treat it as a toggle: read the state, then send only if a change is
  needed, and check the result.
- **Fan status lags:** the new value appears on the next push, about 3 s later. A
  `BoxFan` change sent while idle never showed in the status, although the fan ran;
  during prints `BoxFan` is reported (68/78/100).
- **`XYZsize`** in attributes says `218.88x128.88x220`, but the CC build volume is
  256 × 256 × 256 mm. Don't use it.
- **History `AlreadyPrintLayer`** was once 17062 for a 128-layer job.

## What a Bambuddy bridge must do

1. Keep one WebSocket open; send `Cmd 0` every 25 s; reconnect every few seconds
   when it drops. Show the printer offline while it's away.
2. Translate `PrintInfo.Status` into Bambu states (`gcode_state`: IDLE, PREPARE,
   RUNNING, PAUSE, FINISH, FAILED). Report **100 % / FINISH on state 9**.
3. On state 5 or 6, read the history for the current `TaskId` at once. Reason ≠ 0
   → an error with a human-readable message (45 = filament runout).
4. Bambuddy sends a `.gcode.3mf`. Extract the plate's `.gcode`, upload it over
   HTTP, then send `Cmd 128` with the bare name.
5. Map Bambuddy's controls (pause, resume, stop, temperatures, fans, light) onto
   the commands above. Send no other `Cmd` numbers.
6. The power-loss prompt can't be seen or answered over the network: tell the user
   to check the printer's screen when a printer reconnects after a drop mid-print.
