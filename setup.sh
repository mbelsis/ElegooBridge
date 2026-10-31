#!/bin/sh
# ElegooBridge setup for macOS and Linux: checks Docker, finds the Centauri,
# writes .env, starts the bridge and prints what to enter in Bambuddy.
# Run it again at any time; it keeps your existing settings unless you choose
# otherwise.
set -e
cd "$(dirname "$0")"

say() { printf '%s\n' "$*"; }
ask() { # ask "Question" default -> answer in $REPLY
    printf '%s [%s]: ' "$1" "$2"
    read -r REPLY </dev/tty || REPLY=""
    [ -n "$REPLY" ] || REPLY="$2"
}

say "== ElegooBridge setup =="
say ""

# 1. Docker
if ! command -v docker >/dev/null 2>&1; then
    say "Docker is not installed."
    say "Install Docker Desktop: https://www.docker.com/products/docker-desktop/"
    say "(On Linux you can use Docker Engine with the Compose plugin instead.)"
    say "Then start Docker and run ./setup.sh again."
    exit 1
fi
if ! docker info >/dev/null 2>&1; then
    say "Docker is installed but not running."
    say "Start Docker Desktop, wait until it says it is running, then run ./setup.sh again."
    exit 1
fi
if ! docker compose version >/dev/null 2>&1; then
    say "Docker Compose is missing. Update Docker Desktop, or install the Compose plugin."
    exit 1
fi
say "Docker: OK"

# 2. Settings
write_env=yes
if [ -f .env ]; then
    ask "Settings (.env) already exist. Keep them?" "Y"
    case "$REPLY" in [Nn]*) write_env=yes ;; *) write_env=no ;; esac
fi

if [ "$write_env" = yes ]; then
    printer_ip="" board=""
    if command -v python3 >/dev/null 2>&1; then
        say "Looking for Centauri printers on your network..."
        found=$(python3 -m elegoobridge discover 2>/dev/null | grep "PRINTER_MAINBOARD_ID=" || true)
    else
        found=""
    fi
    count=$(printf '%s' "$found" | grep -c . || true)
    if [ "$count" -ge 1 ]; then
        printf '%s\n' "$found" | nl -w2 -s') '
        choice=1
        [ "$count" -eq 1 ] || { ask "Which printer?" "1"; choice=$REPLY; }
        line=$(printf '%s\n' "$found" | sed -n "${choice}p")
        printer_ip=$(printf '%s' "$line" | sed -E 's/.* at ([0-9.]+):.*/\1/')
        board=$(printf '%s' "$line" | sed -E 's/.*PRINTER_MAINBOARD_ID=([^ ]+).*/\1/')
        say "Using the printer at $printer_ip"
    else
        say "No printer found automatically. Check it is on and on the same network,"
        say "or enter its details (IP: printer screen > Settings > Network)."
        ask "Printer IP address" ""
        printer_ip=$REPLY
        ask "Printer mainboard ID" ""
        board=$REPLY
    fi
    [ -n "$printer_ip" ] && [ -n "$board" ] || { say "The printer IP and mainboard ID are needed."; exit 1; }

    # This computer's address on the printer's network: Bambuddy connects here.
    host_ip=""
    if command -v route >/dev/null 2>&1 && [ "$(uname)" = Darwin ]; then
        iface=$(route -n get "$printer_ip" 2>/dev/null | awk '/interface:/{print $2}')
        [ -n "$iface" ] && host_ip=$(ipconfig getifaddr "$iface" 2>/dev/null || true)
    elif command -v ip >/dev/null 2>&1; then
        host_ip=$(ip route get "$printer_ip" 2>/dev/null | sed -nE 's/.* src ([0-9.]+).*/\1/p' | head -1)
    fi
    ask "This computer's IP address (Bambuddy connects to it)" "$host_ip"
    host_ip=$REPLY
    [ -n "$host_ip" ] || { say "This computer's IP address is needed."; exit 1; }

    code=$(od -An -N4 -tu4 /dev/urandom | tr -d ' ' | cut -c1-8)
    ask "Access code for Bambuddy (any password, up to 20 characters)" "$code"
    code=$REPLY

    umask 077
    cat > .env <<EOF
# Written by setup.sh. Edit it, or run ./setup.sh again.
BRIDGE_HOST_IP=$host_ip
PRINTER_HOST=$printer_ip
PRINTER_MAINBOARD_ID=$board
BAMBU_SERIAL=0390000ELEGOO01
ACCESS_CODE=$code
EOF
    say "Saved the settings in .env"
fi

# 3. Start
say ""
say "Starting ElegooBridge (the first time takes a few minutes)..."
docker compose up -d --build

say "Waiting for the bridge to reach the printer..."
connected=no
for _ in $(seq 1 30); do
    if docker compose logs bridge 2>/dev/null | grep -q "printer .* connected"; then
        connected=yes
        break
    fi
    sleep 2
done

# 4. What to enter in Bambuddy
get() { sed -n "s/^$1=//p" .env | tail -1; }
say ""
if [ "$connected" = yes ]; then
    say "ElegooBridge is running and connected to the printer."
else
    say "ElegooBridge is running, but hasn't reached the printer yet."
    say "Check the printer is on, then look at: docker compose logs -f bridge"
fi
say ""
say "Now add the printer in Bambuddy (Printers > Add Printer):"
say "  Model:          P1S"
say "  IP address:     $(get BRIDGE_HOST_IP)      this computer, not the printer"
say "  Serial number:  $(get BAMBU_SERIAL)   made up: a Bambu-style name for the bridge"
say "  Access code:    $(get ACCESS_CODE)          random: a password for the bridge"
say ""
say "Before printing from Bambuddy, stamp your sliced files: see stamp/README.md"
