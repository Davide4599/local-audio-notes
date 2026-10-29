#!/usr/bin/env bash
# Ferma la registrazione in corso, trascrive l'audio e aggiorna il libro personale
# di consigli finanziari usando Claude Code.
set -euo pipefail

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PID_FILE="$DIR/.recording.pid"
CUR_FILE="$DIR/.current_recording"
TS_FILE="$DIR/.current_timestamp"
TITLE_FILE="$DIR/.current_title"
BOOK="$DIR/book/personal_finance_book.md"

if [ ! -f "$PID_FILE" ]; then
  echo "Nessuna registrazione risulta in corso."
  exit 1
fi

PID="$(cat "$PID_FILE")"
if kill -0 "$PID" 2>/dev/null; then
  kill -INT "$PID"
  sleep 1
fi
rm -f "$PID_FILE"

if [ ! -f "$CUR_FILE" ]; then
  echo "Non trovo il file della registrazione appena fatta."
  exit 1
fi
WAV_FILE="$(cat "$CUR_FILE")"
TIMESTAMP="$(cat "$TS_FILE" 2>/dev/null || basename "$WAV_FILE" .wav)"
TITLE="$(cat "$TITLE_FILE" 2>/dev/null || true)"
rm -f "$CUR_FILE" "$TS_FILE" "$TITLE_FILE"

echo "Registrazione salvata: $WAV_FILE"
echo "Avvio trascrizione (può richiedere qualche minuto)..."

TXT_FILE="$("$DIR/venv/bin/python" "$DIR/transcribe.py" "$WAV_FILE" | tail -1)"

if [ ! -s "$TXT_FILE" ]; then
  echo "Trascrizione vuota o fallita: $TXT_FILE"
  exit 1
fi

echo "Trascrizione completata: $TXT_FILE"

if [ -z "$TITLE" ]; then
  echo "Nessun titolo fornito, lo deduco dal contenuto..."
  TITLE="$(claude -p "Leggi questa trascrizione di un podcast e restituisci SOLO un titolo breve (max 6 parole, il nome del podcast se viene menzionato, altrimenti l'argomento principale). Nessuna virgoletta, nessun testo aggiuntivo, una riga sola.

$(head -c 4000 "$TXT_FILE")" --allowedTools "" | tr -d '\n"' | sed -E 's/^[[:space:]]+|[[:space:]]+$//g')"
  [ -z "$TITLE" ] && TITLE="episodio"
  echo "Titolo dedotto: $TITLE"
fi

SLUG="$(echo "$TITLE" | tr '[:upper:]' '[:lower:]' | sed -E 's/[^a-z0-9]+/-/g; s/^-+|-+$//g')"
[ -z "$SLUG" ] && SLUG="episodio"
NEW_BASE="${SLUG}_${TIMESTAMP}"

mv "$WAV_FILE" "$DIR/recordings/${NEW_BASE}.wav"
mv "$TXT_FILE" "$DIR/transcripts/${NEW_BASE}.txt"
TXT_FILE="$DIR/transcripts/${NEW_BASE}.txt"

echo "Elaborazione con Claude Code..."

[ -f "$BOOK" ] || printf '# Il mio libro di finanza personale\n\nNote estratte automaticamente dai podcast ascoltati.\n' > "$BOOK"

EPISODE_DATE="$TITLE ($TIMESTAMP)"

PROMPT="Sei il mio assistente personale di finanza. Ti passo la trascrizione grezza (con probabili errori di trascrizione) di un episodio di podcast finanziario che ho appena ascoltato durante l'allenamento, e il contenuto attuale del mio 'libro personale di finanza'.

Compito:
1. Leggi la trascrizione ed estrai SOLO i consigli pratici, i concetti, i dati/numeri rilevanti e le cose davvero importanti in tema di finanza personale (investimenti, risparmio, fiscalità, strumenti finanziari, errori da evitare, ecc). Ignora chiacchiere, sponsor, saluti, ripetizioni.
2. Organizza quanto estratto per argomento (usa o riusa le sezioni già presenti nel libro, es. '## Investimenti', '## Risparmio', '## Fisco', '## Pensione', creane di nuove se serve).
3. Integra i nuovi contenuti nel libro esistente: se un concetto è già presente non duplicarlo, ma arricchiscilo o segnala eventuali contraddizioni tra fonti diverse.
4. Aggiungi in fondo a ogni voce nuova un riferimento breve tra parentesi alla data dell'episodio: (fonte: $EPISODE_DATE).
5. Alla fine mantieni una sezione '## Indice episodi ascoltati' con la lista delle date processate.

Riscrivi l'intero file aggiornato di book/personal_finance_book.md e SALVALO usando i tuoi strumenti di editing (Edit/Write), non limitarti a stamparlo.

--- LIBRO ATTUALE ---
$(cat "$BOOK")

--- TRASCRIZIONE EPISODIO ($EPISODE_DATE) ---
$(cat "$TXT_FILE")
"

cd "$DIR"
claude -p "$PROMPT" --allowedTools "Edit,Write,Read"

echo "Fatto. Libro aggiornato in: $BOOK"
