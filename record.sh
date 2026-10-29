#!/usr/bin/env bash
# Registra l'audio in uscita di questo PC (loopback) mentre ascolti il podcast.
# Uso: ./record.sh ["Nome Podcast"]   (il titolo è opzionale: se lo ometti, verrà dedotto
#                                       automaticamente dal contenuto durante l'elaborazione)
set -euo pipefail

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REC_DIR="$DIR/recordings"
PID_FILE="$DIR/.recording.pid"
mkdir -p "$REC_DIR"

if [ -f "$PID_FILE" ] && kill -0 "$(cat "$PID_FILE")" 2>/dev/null; then
  echo "Una registrazione è già in corso (PID $(cat "$PID_FILE"))."
  exit 1
fi

TITLE="${1:-}"
TIMESTAMP="$(date +%Y-%m-%d_%H-%M-%S)"

SLUG="senza-titolo"
if [ -n "$TITLE" ]; then
  SLUG="$(echo "$TITLE" | tr '[:upper:]' '[:lower:]' | sed -E 's/[^a-z0-9]+/-/g; s/^-+|-+$//g')"
fi

echo "$TIMESTAMP" > "$DIR/.current_timestamp"
echo "$TITLE" > "$DIR/.current_title"

OUT_FILE="$REC_DIR/${SLUG}_${TIMESTAMP}.wav"

# Registra il monitor del sink DI DEFAULT (l'uscita audio realmente in uso): collegare
# cuffie USB/Bluetooth aggiunge un sink, quindi "il primo sink elencato" non basta.
TARGET="$(wpctl inspect @DEFAULT_AUDIO_SINK@ 2>/dev/null | head -1 | grep -oP '(?<=id )[0-9]+' || true)"
if [ -z "$TARGET" ]; then
  TARGET="$(pw-cli ls Node 2>/dev/null | grep -B12 'media.class = "Audio/Sink"' | grep 'node.name' | head -1 | sed -E 's/.*node.name = "(.*)"/\1/')"
fi

if [ -z "$TARGET" ]; then
  echo "Non trovo un Audio/Sink su questo PC. Controlla 'wpctl status' manualmente."
  exit 1
fi

echo "Registro il loopback dal sink di default: $TARGET"
echo "File di output: $OUT_FILE"

nohup pw-record --target="$TARGET" "$OUT_FILE" > "$DIR/.record.log" 2>&1 &
echo $! > "$PID_FILE"
echo "$OUT_FILE" > "$DIR/.current_recording"

echo "Registrazione avviata (PID $!). Buon allenamento!"
echo "Quando hai finito lancia: ./stop_and_process.sh"
