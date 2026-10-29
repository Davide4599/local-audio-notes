#!/usr/bin/env bash
# Apre la webapp in modalità "app" (senza barra indirizzi/tab), come un programma vero.
# Il server NON gira sempre in background: viene avviato qui al bisogno (systemd --user)
# e si ferma da solo quando premi "Chiudi app" nella pagina.
set -euo pipefail
URL="http://localhost:8765"

systemctl --user start audio-notes.service

# aspetta che il server risponda
for i in $(seq 1 30); do
  curl -s -o /dev/null "$URL/api/status" && break
  sleep 0.3
done

if command -v google-chrome >/dev/null; then
  exec google-chrome --app="$URL" --window-size=1280,900
elif command -v chromium >/dev/null; then
  exec chromium --app="$URL" --window-size=1280,900
else
  exec xdg-open "$URL"
fi
