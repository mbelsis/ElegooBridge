#!/bin/sh
# Creates the self-signed TLS certificate Mosquitto presents to Bambuddy.
# Bambuddy doesn't verify it, as with real Bambu printers. Run once.
set -e
cd "$(dirname "$0")/../mosquitto"
mkdir -p certs
if [ -f certs/server.crt ]; then
  echo "mosquitto/certs/server.crt already exists; delete it to make a new one."
  exit 0
fi
openssl req -x509 -newkey rsa:2048 -nodes -days 3650 -subj "/CN=elegoobridge" \
  -keyout certs/server.key -out certs/server.crt 2>/dev/null
chmod 644 certs/server.key certs/server.crt
echo "Created mosquitto/certs/server.crt and server.key"
