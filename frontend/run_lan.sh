#!/usr/bin/env bash
# Serves the app on this machine's network address, so patients' phones can
# open the QR codes the kiosk shows (phone intake, report pages).
#   ./run_lan.sh            build, then serve on port 8080
#   ./run_lan.sh --no-build serve the last build
# Kiosk on this machine:  http://localhost:8080/#/kiosk   (microphone needs localhost or https)
# Phones:                 http://<this machine's IP>:8080 (from the QR code)
# The backend must listen on the network too (backend/run_dev.sh does by default).
set -euo pipefail
cd "$(dirname "$0")"
# This machine's network address. Without internet there may be no route to
# 1.1.1.1, so fall back to the first address of a network card.
ip="${MEDORA_LAN_IP:-$(ip route get 1.1.1.1 2>/dev/null | awk '{for(i=1;i<=NF;i++) if($i=="src") print $(i+1)}' | head -1)}"
ip="${ip:-$(hostname -I 2>/dev/null | tr ' ' '\n' | grep -E '^[0-9]+\.' | grep -v '^127\.' | head -1)}"
if [ -z "$ip" ]; then echo "No network address found; set MEDORA_LAN_IP." >&2; exit 1; fi
port="${MEDORA_WEB_PORT:-8080}"
if [ "${1:-}" != "--no-build" ]; then
  # --no-web-resources-cdn: everything is served from here, so the kiosk
  # also opens without internet.
  flutter build web --release --no-web-resources-cdn --dart-define=MEDORA_PUBLIC_URL="http://$ip:$port"
fi
echo "Kiosk:  http://localhost:$port/#/kiosk"
echo "Phones: http://$ip:$port   (API: http://$ip:8100)"
exec python3 -m http.server "$port" --bind 0.0.0.0 --directory build/web
