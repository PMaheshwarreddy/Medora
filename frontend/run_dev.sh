#!/usr/bin/env bash
# Runs the kiosk in Chrome. Use this instead of `flutter run` when the
# terminal is inside VS Code (see tool/chrome.sh for why).
#
# The app is served on the network (port 8090), so patients' phones can open
# the QR codes (phone intake, report pages): the QR codes use this machine's
# network address, while Chrome here opens it as localhost (the microphone
# and Bluetooth need localhost or https). The backend must listen on the
# network too (backend/run_dev.sh does), and the firewall must allow 8090
# and 8100.
set -euo pipefail
cd "$(dirname "$0")"
export CHROME_EXECUTABLE="$PWD/tool/chrome.sh"
port="${MEDORA_WEB_PORT:-8090}"
# This machine's network address. Without internet there may be no route to
# 1.1.1.1, so fall back to the first address of a network card.
ip="${MEDORA_LAN_IP:-$(ip route get 1.1.1.1 2>/dev/null | awk '{for(i=1;i<=NF;i++) if($i=="src") print $(i+1)}' | head -1)}"
ip="${ip:-$(hostname -I 2>/dev/null | tr ' ' '\n' | grep -E '^[0-9]+\.' | grep -v '^127\.' | head -1)}"
# --no-web-resources-cdn: the engine files come from this machine, not a
# Google CDN, so the kiosk also opens without internet.
args=(--no-web-resources-cdn --web-hostname 0.0.0.0 --web-port "$port" --web-launch-url "http://localhost:$port/")
if [ -n "$ip" ]; then
  args+=(--dart-define=MEDORA_PUBLIC_URL="http://$ip:$port")
  echo "Kiosk: http://localhost:$port/#/kiosk   Phones reach: http://$ip:$port"
fi
exec flutter run -d chrome "${args[@]}" "$@"
