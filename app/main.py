"""Webapp locale in due modalità.

* **Raccolta** — registra un episodio audio (podcast/audiolibro/corso), lo trascrive
  e aggiorna con Claude Code il "libro" di note scelto.
* **Riunione** — registra insieme l'audio della call e il tuo microfono, li fonde in
  una trascrizione con i turni di parola e ne fa un verbale (decisioni, azioni,
  punti aperti).
"""
import os
import re
import signal
import threading
import time
from datetime import datetime
from pathlib import Path

import markdown as md
from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import audio, pipeline

BASE_DIR = Path(__file__).resolve().parent.parent
RECORDINGS_DIR = BASE_DIR / "recordings"
STATIC_DIR = Path(__file__).resolve().parent / "static"
RECORDINGS_DIR.mkdir(exist_ok=True)

app = FastAPI(title="Audio Notes")
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


def _fmt_duration(seconds: float) -> str:
    s = int(seconds)
    h, m = s // 3600, (s % 3600) // 60
    if h:
        return f"{h}h {m:02d}min"
    return f"{m} min" if m else "meno di un minuto"


class _State:
    def __init__(self):
        self.lock = threading.Lock()
        self.phase = "idle"  # idle | recording | processing | error
        self.message = "Pronto per registrare."
        self.mode = "book"   # book | meeting
        self.title = ""
        self.book_slug = ""
        self.book_title = ""
        self.participants = ""
        self.meeting_slug = ""
        self.devices = ""
        self.timestamp = None
        self.rec = None
        self.started_at = None

    def snapshot(self):
        with self.lock:
            elapsed = None
            if self.phase == "recording" and self.started_at:
                elapsed = time.time() - self.started_at
            return {
                "phase": self.phase,
                "message": self.message,
                "mode": self.mode,
                "title": self.title,
                "book_slug": self.book_slug,
                "book_title": self.book_title,
                "meeting_slug": self.meeting_slug,
                "devices": self.devices,
                "elapsed": elapsed,
            }

    def set(self, **kwargs):
        with self.lock:
            for k, v in kwargs.items():
                setattr(self, k, v)


STATE = _State()


class StartBody(BaseModel):
    mode: str = "book"
    book: str = ""
    title: str = ""
    participants: str = ""
    capture_mic: bool = True


@app.get("/", response_class=HTMLResponse)
def index():
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/api/status")
def get_status():
    return STATE.snapshot()


@app.get("/api/books")
def get_books():
    return pipeline.list_books()


@app.get("/api/meetings")
def get_meetings():
    return pipeline.list_meetings()


@app.post("/api/record/start")
def start_recording(body: StartBody):
    mode = body.mode if body.mode in ("book", "meeting") else "book"
    title = body.title.strip()

    book_title = body.book.strip()
    if mode == "book" and not book_title:
        raise HTTPException(400, "Specifica il libro/raccolta a cui aggiungere questo episodio.")

    with STATE.lock:
        if STATE.phase != "idle":
            raise HTTPException(409, "C'è già una registrazione o elaborazione in corso.")

    timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    capture_mic = mode == "meeting" and body.capture_mic

    if mode == "meeting":
        book_slug = ""
        wav_path = RECORDINGS_DIR / f"meeting__in-corso_{timestamp}.wav"
    else:
        book_slug = pipeline._slugify(book_title)
        ep_slug = pipeline._slugify(title) if title else "senza-titolo"
        wav_path = RECORDINGS_DIR / f"{book_slug}__{ep_slug}_{timestamp}.wav"

    try:
        rec = audio.start_recording(wav_path, capture_mic=capture_mic)
    except RuntimeError as e:
        raise HTTPException(500, str(e))

    if mode == "meeting":
        msg = "Riunione in registrazione (audio call + microfono)..." if capture_mic \
            else "Riunione in registrazione (solo audio in arrivo)..."
    else:
        msg = "Registrazione in corso..."

    STATE.set(
        phase="recording",
        message=msg,
        mode=mode,
        title=title,
        book_slug=book_slug,
        book_title=book_title,
        participants=body.participants.strip(),
        meeting_slug="",
        devices=audio.describe_devices(capture_mic),
        timestamp=timestamp,
        rec=rec,
        started_at=time.time(),
    )
    return STATE.snapshot()


@app.post("/api/record/stop")
def stop_recording():
    with STATE.lock:
        if STATE.phase != "recording":
            raise HTTPException(409, "Nessuna registrazione in corso.")
        rec = STATE.rec
        mode = STATE.mode
        title = STATE.title
        book_slug = STATE.book_slug
        book_title = STATE.book_title
        participants = STATE.participants
        timestamp = STATE.timestamp
        duration = _fmt_duration(time.time() - STATE.started_at)

    audio.stop_recording(rec)
    STATE.set(phase="processing", message="Registrazione salvata, avvio elaborazione...")

    def on_progress(msg: str):
        STATE.set(message=msg)

    def run():
        try:
            if mode == "meeting":
                result = pipeline.process_meeting(
                    rec.paths, title, participants, timestamp, duration, on_progress
                )
                STATE.set(
                    phase="idle",
                    meeting_slug=result["meeting_slug"],
                    message="Verbale pronto! Puoi registrare un'altra riunione.",
                )
            else:
                pipeline.process_episode(
                    rec.primary, book_slug, book_title, title, timestamp, on_progress
                )
                STATE.set(phase="idle", message="Libro aggiornato! Pronto per un nuovo episodio.")
        except Exception as e:  # noqa: BLE001 - vogliamo mostrare qualunque errore in UI
            STATE.set(phase="error", message=f"Errore: {e}")

    threading.Thread(target=run, daemon=True).start()
    return STATE.snapshot()


@app.post("/api/reset")
def reset_error():
    with STATE.lock:
        if STATE.phase == "error":
            STATE.phase = "idle"
            STATE.message = "Pronto per registrare."
    return STATE.snapshot()


@app.post("/api/shutdown")
def shutdown():
    with STATE.lock:
        if STATE.phase in ("recording", "processing"):
            raise HTTPException(409, "Non posso chiudere mentre una registrazione o elaborazione è in corso.")

    def _terminate():
        time.sleep(0.4)
        os.kill(os.getpid(), signal.SIGTERM)

    threading.Thread(target=_terminate, daemon=True).start()
    return {"ok": True}


def _render(path: Path, fallback_title: str = "") -> dict:
    raw = path.read_text(encoding="utf-8")
    title = fallback_title
    for line in raw.splitlines():
        if line.startswith("# "):
            title = line[2:].strip()
            break
    body = re.sub(r"^#\s+.*\n+", "", raw, count=1)  # il titolo è già nell'header della pagina
    return {"title": title, "html": md.markdown(body, extensions=["extra", "sane_lists"]), "raw": raw}


@app.get("/api/book")
def get_book(slug: str = ""):
    if not slug:
        return {"title": "", "html": "<p class='empty'>Nessuna raccolta selezionata.</p>", "raw": ""}
    path = pipeline.book_path(slug)
    if not path.exists():
        return {"title": "", "html": "<p class='empty'>Nessun episodio ancora processato.</p>", "raw": ""}
    return _render(path, pipeline.book_title_from_content(slug))


@app.get("/api/meeting")
def get_meeting(slug: str = ""):
    if not slug:
        return {"title": "", "html": "<p class='empty'>Nessuna riunione selezionata.</p>", "raw": ""}
    path = pipeline.meeting_path(slug)
    if not path.exists():
        return {"title": "", "html": "<p class='empty'>Verbale non trovato.</p>", "raw": ""}
    return _render(path, slug)


@app.get("/api/episodes")
def get_episodes(book: str = ""):
    episodes = []
    # i transcript esistono solo a elaborazione completata: un wav ancora in
    # corso di registrazione/trascrizione non deve comparire in lista.
    for txt in sorted(pipeline.TRANSCRIPTS_DIR.glob("*.txt"), reverse=True):
        stem = txt.stem
        if "__" not in stem or stem.startswith("meeting__"):
            continue
        book_slug, rest = stem.split("__", 1)
        if book and book_slug != book:
            continue
        parts = rest.split("_")
        if len(parts) >= 3:
            date_part = parts[-2]
            time_part = parts[-1]
            slug = "_".join(parts[:-2])
        else:
            date_part, time_part, slug = "", "", rest
        episodes.append({
            "title": slug.replace("-", " "),
            "date": date_part,
            "time": time_part.replace("-", ":"),
            "book_slug": book_slug,
        })
    return episodes
