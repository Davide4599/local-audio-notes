#!/usr/bin/env bash
# Avvia la webapp locale su http://localhost:8765
set -euo pipefail
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$DIR"

echo "Avvio la webapp su http://localhost:8765 ..."
( sleep 1 && command -v xdg-open >/dev/null && xdg-open "http://localhost:8765" >/dev/null 2>&1 || true ) &

exec ./venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8765
