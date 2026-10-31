# ElegooBridge setup for Windows: checks Docker Desktop, finds the Centauri,
# writes .env, starts the bridge and prints what to enter in Bambuddy.
# Started by setup.bat. Run it again at any time; it keeps your existing
# settings unless you choose otherwise.
$ErrorActionPreference = "Stop"
Set-Location (Split-Path -Parent $PSScriptRoot)

function Ask($question, $default) {
    $answer = Read-Host "$question [$default]"
    if ([string]::IsNullOrWhiteSpace($answer)) { return $default }
    return $answer.Trim()
}

function Stop-Setup($message) {
    Write-Host $message
    Read-Host "Press Enter to close"
    exit 1
}

Write-Host "== ElegooBridge setup =="
Write-Host ""

# 1. Docker
if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
    Stop-Setup ("Docker Desktop is not installed.`n" +
        "Install it from https://www.docker.com/products/docker-desktop/ , start it, then run setup.bat again.")
}
docker info *> $null
if ($LASTEXITCODE -ne 0) {
    Stop-Setup "Docker Desktop is installed but not running. Start it, wait until it says it is running, then run setup.bat again."
}
docker compose version *> $null
if ($LASTEXITCODE -ne 0) { Stop-Setup "Docker Compose is missing. Update Docker Desktop." }
Write-Host "Docker: OK"

# 2. Settings
$writeEnv = $true
if (Test-Path ".env") {
    $keep = Ask "Settings (.env) already exist. Keep them?" "Y"
    $writeEnv = $keep -match "^[Nn]"
}

if ($writeEnv) {
    # Discovery: the Centauri answers "M99999" sent as a UDP broadcast to port 3000.
    Write-Host "Looking for Centauri printers on your network..."
    $printers = @{}
    $udp = New-Object System.Net.Sockets.UdpClient
    $udp.EnableBroadcast = $true
    $udp.Client.ReceiveTimeout = 1000
    $probe = [Text.Encoding]::ASCII.GetBytes("M99999")
    $broadcast = New-Object System.Net.IPEndPoint ([System.Net.IPAddress]::Broadcast), 3000
    for ($try = 0; $try -lt 3; $try++) {
        [void]$udp.Send($probe, $probe.Length, $broadcast)
        while ($true) {
            try {
                $from = New-Object System.Net.IPEndPoint ([System.Net.IPAddress]::Any), 0
                $bytes = $udp.Receive([ref]$from)
                $info = ([Text.Encoding]::UTF8.GetString($bytes) | ConvertFrom-Json).Data
                if ($info.MainboardID) { $printers[$from.Address.ToString()] = $info }
            } catch { break }
        }
    }
    $udp.Close()

    $printerIp = ""; $board = ""
    $list = @($printers.GetEnumerator())
    if ($list.Count -ge 1) {
        for ($i = 0; $i -lt $list.Count; $i++) {
            Write-Host (" {0}) {1} at {2} (firmware {3})" -f ($i + 1), $list[$i].Value.Name, $list[$i].Key, $list[$i].Value.FirmwareVersion)
        }
        $choice = 1
        if ($list.Count -gt 1) { $choice = [int](Ask "Which printer?" "1") }
        $printerIp = $list[$choice - 1].Key
        $board = $list[$choice - 1].Value.MainboardID
        Write-Host "Using the printer at $printerIp"
    } else {
        Write-Host "No printer found automatically. Check it is on and on the same network,"
        Write-Host "or enter its details (IP: printer screen > Settings > Network)."
        $printerIp = Ask "Printer IP address" ""
        $board = Ask "Printer mainboard ID" ""
    }
    if (-not $printerIp -or -not $board) { Stop-Setup "The printer IP and mainboard ID are needed." }

    # This computer's address on the printer's network: Bambuddy connects here.
    $hostIp = ""
    try { $hostIp = (Find-NetRoute -RemoteIPAddress $printerIp -ErrorAction Stop | Where-Object IPAddress | Select-Object -First 1).IPAddress } catch {}
    $hostIp = Ask "This computer's IP address (Bambuddy connects to it)" $hostIp
    if (-not $hostIp) { Stop-Setup "This computer's IP address is needed." }

    $code = Ask "Access code for Bambuddy (any password, up to 20 characters)" ([string](Get-Random -Minimum 10000000 -Maximum 99999999))

    # LF line endings and no byte-order mark, so Docker Compose reads it cleanly.
    $lines = @(
        "# Written by setup.bat. Edit it, or run setup.bat again.",
        "BRIDGE_HOST_IP=$hostIp",
        "PRINTER_HOST=$printerIp",
        "PRINTER_MAINBOARD_ID=$board",
        "BAMBU_SERIAL=0390000ELEGOO01",
        "ACCESS_CODE=$code"
    )
    [IO.File]::WriteAllText((Join-Path (Get-Location) ".env"), ($lines -join "`n") + "`n", (New-Object Text.UTF8Encoding $false))
    Write-Host "Saved the settings in .env"
}

# 3. Start
Write-Host ""
Write-Host "Starting ElegooBridge (the first time takes a few minutes)..."
docker compose up -d --build
if ($LASTEXITCODE -ne 0) { Stop-Setup "Starting ElegooBridge failed; see the messages above." }

Write-Host "Waiting for the bridge to reach the printer..."
$connected = $false
for ($i = 0; $i -lt 30; $i++) {
    if ((docker compose logs bridge 2>$null) -match "printer .* connected") { $connected = $true; break }
    Start-Sleep -Seconds 2
}

# 4. What to enter in Bambuddy
$settings = @{}
foreach ($line in Get-Content ".env") {
    if ($line -match "^([A-Z_]+)=(.*)$") { $settings[$Matches[1]] = $Matches[2] }
}
Write-Host ""
if ($connected) {
    Write-Host "ElegooBridge is running and connected to the printer."
} else {
    Write-Host "ElegooBridge is running, but hasn't reached the printer yet."
    Write-Host "Check the printer is on, then look at: docker compose logs -f bridge"
}
Write-Host ""
Write-Host "Now add the printer in Bambuddy (Printers > Add Printer):"
Write-Host "  Model:          P1S"
Write-Host ("  IP address:     " + $settings["BRIDGE_HOST_IP"] + "      this computer, not the printer")
Write-Host ("  Serial number:  " + $settings["BAMBU_SERIAL"] + "   made up: a Bambu-style name for the bridge")
Write-Host ("  Access code:    " + $settings["ACCESS_CODE"] + "          random: a password for the bridge")
Write-Host ""
Write-Host "Before printing from Bambuddy, stamp your sliced files: see stamp\README.md"
Read-Host "Press Enter to close"
