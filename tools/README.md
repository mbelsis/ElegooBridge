# Test tools

Small Python scripts used to work out the protocol. They use only the standard
library. Each one sends a fixed, listed set of commands and refuses anything else.
They're test scripts, not the bridge.

`ID` is the printer's MainboardID. Get it from `discover.py` or the
`MainboardID` field in `sdcp_read.py`'s output. Run them with `python3 -I`.

| Script | Sends | Usage |
| --- | --- | --- |
| `discover.py` | UDP `M99999` | `discover.py BROADCAST_OR_IP`. The printer only answers broadcasts, for example `192.168.1.255`. |
| `sdcp_read.py` | Cmd 0, 1 | `sdcp_read.py IP ID SECONDS`: prints status and attributes |
| `sdcp_record.py` | Cmd 0, 1 (keep-alive every 25 s) | `sdcp_record.py IP ID LOG.jsonl MAX_SECONDS`: records every message, reconnects, prints changes |
| `sdcp_history.py` | Cmd 320, 321 | `sdcp_history.py IP ID 0`: last 5 history entries |
| `sdcp_files.py` | Cmd 258 | `sdcp_files.py IP ID 0`: files in `/local` |
| `sdcp_job.py` | Cmd 0, 128, 129, 130, 131 | `sdcp_job.py IP ID 0 ACTION SECONDS [FILE]`: `ACTION` is status, start, pause, resume or stop |
| `sdcp_temp.py` | Cmd 403 temperatures | Hard-coded: nozzle 100 / bed 40 for 45 s, then off, even if it fails partway |
| `sdcp_fan.py` | Cmd 403 fans | Hard-coded: part fan 50 % for 8 s, then off |
| `sdcp_light.py` | Cmd 403 light | Hard-coded: sends 0, then 1 (the light toggles) |

The unused `0` argument is the `SECONDS` slot of the shared connection code; just
pass it.

Upload a file, without starting it, with `curl`:

```sh
f=file.gcode; curl -F Check=1 -F "S-File-MD5=$(md5 -q "$f")" -F Offset=0 \
  -F "Uuid=$(uuidgen | tr -d - | tr A-Z a-z)" -F "TotalSize=$(stat -f %z "$f")" \
  -F "File=@$f;filename=name-on-printer.gcode" http://IP/uploadFile/upload
```

That works for files up to 1 MiB. Bigger files need one request per 1 MiB chunk,
with `Offset` set and the same `Uuid` and MD5.
