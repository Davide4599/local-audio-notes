"""Trascrizione locale (faster-whisper) + elaborazione con Claude Code.

Due modalità:

* **raccolta** (``book``) — podcast/audiolibri/corsi: le note si accumulano
  episodio dopo episodio in ``book/<slug>.md``.
* **riunione** (``meeting``) — un verbale autonomo per ogni incontro in
  ``meetings/<timestamp>__<slug>.md``, costruito da due tracce audio separate
  (il tuo microfono e l'audio in arrivo dagli altri) fuse cronologicamente.
"""
import os
import re
import shutil
import subprocess
from pathlib import Path
from typing import Callable

from . import audio

# In riunione le voci sono più difficili (più parlanti, microfoni scadenti,
# sovrapposizioni): conviene un modello più grande di quello dei podcast.
WHISPER_MODEL = os.environ.get("WHISPER_MODEL", "small")
MEETING_WHISPER_MODEL = os.environ.get("MEETING_WHISPER_MODEL", "medium")
WHISPER_LANGUAGE = os.environ.get("WHISPER_LANGUAGE", "it")

BASE_DIR = Path(__file__).resolve().parent.parent
RECORDINGS_DIR = BASE_DIR / "recordings"
TRANSCRIPTS_DIR = BASE_DIR / "transcripts"
BOOKS_DIR = BASE_DIR / "book"
MEETINGS_DIR = BASE_DIR / "meetings"

ProgressFn = Callable[[str], None]

_models: dict[str, object] = {}


def _get_model(name: str):
    if name not in _models:
        from faster_whisper import WhisperModel
        _models[name] = WhisperModel(name, device="cpu", compute_type="int8")
    return _models[name]


def _claude_bin() -> str:
    """Percorso completo dell'eseguibile ``claude``.

    L'app gira come servizio ``systemd --user``, che non legge il profilo della
    shell: il suo PATH non contiene la bin di nvm dove npm installa la CLI, e
    ``subprocess`` fallirebbe con "No such file or directory: 'claude'". Cerchiamo
    quindi anche nelle posizioni note, con override esplicito via ``CLAUDE_BIN``.
    """
    override = os.environ.get("CLAUDE_BIN", "").strip()
    if override:
        return override

    found = shutil.which("claude")
    if found:
        return found

    home = Path.home()
    candidates = sorted(home.glob(".nvm/versions/node/*/bin/claude"), reverse=True)
    candidates += [home / ".local/bin/claude", Path("/usr/local/bin/claude")]
    for c in candidates:
        if c.exists() and os.access(c, os.X_OK):
            return str(c)

    raise RuntimeError(
        "Non trovo l'eseguibile 'claude': installa Claude Code oppure imposta la "
        "variabile d'ambiente CLAUDE_BIN con il percorso completo."
    )


def _slugify(text: str) -> str:
    slug = text.lower()
    slug = re.sub(r"[^a-z0-9]+", "-", slug).strip("-")
    return slug or "episodio"


def _fmt_ts(seconds: float) -> str:
    s = int(seconds)
    return f"{s // 3600:02d}:{(s % 3600) // 60:02d}:{s % 60:02d}"


# --- Libri (raccolte di note) -------------------------------------------------

def _safe_slug(slug: str) -> str:
    # lo slug arriva dalla query string: niente separatori, così non si esce dalla cartella
    if not re.fullmatch(r"[A-Za-z0-9_-]+", slug):
        raise ValueError(f"slug non valido: {slug!r}")
    return slug


def book_path(slug: str) -> Path:
    return BOOKS_DIR / f"{_safe_slug(slug)}.md"


def book_title_from_content(slug: str) -> str:
    path = book_path(slug)
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.startswith("# "):
                return line[2:].strip()
    return slug.replace("-", " ").replace("_", " ").title()


def list_books() -> list[dict]:
    BOOKS_DIR.mkdir(exist_ok=True)
    books = []
    for f in sorted(BOOKS_DIR.glob("*.md")):
        books.append({"slug": f.stem, "title": book_title_from_content(f.stem)})
    return books


def ensure_book(slug: str, title: str) -> None:
    BOOKS_DIR.mkdir(exist_ok=True)
    path = book_path(slug)
    if not path.exists():
        path.write_text(
            f"# {title}\n\nNote estratte automaticamente dagli episodi ascoltati.\n",
            encoding="utf-8",
        )


# --- Riunioni ------------------------------------------------------------------

def meeting_path(slug: str) -> Path:
    return MEETINGS_DIR / f"{_safe_slug(slug)}.md"


def list_meetings() -> list[dict]:
    MEETINGS_DIR.mkdir(exist_ok=True)
    meetings = []
    for f in sorted(MEETINGS_DIR.glob("*.md"), reverse=True):
        stem = f.stem
        title = stem
        for line in f.read_text(encoding="utf-8").splitlines():
            if line.startswith("# "):
                title = line[2:].strip()
                break
        date = stem.split("_")[0] if "_" in stem else ""
        meetings.append({"slug": stem, "title": title, "date": date})
    return meetings


# --- Trascrizione --------------------------------------------------------------

def _segments(wav_path: Path, model_name: str) -> list[dict]:
    """Segmenti con timestamp. Il VAD scarta i silenzi: sulla traccia del
    microfono, muta mentre parlano gli altri, taglia gran parte dell'audio."""
    model = _get_model(model_name)
    segments, _info = model.transcribe(
        str(wav_path), language=WHISPER_LANGUAGE, vad_filter=True
    )
    return [
        {"start": s.start, "end": s.end, "text": s.text.strip()}
        for s in segments
        if s.text.strip()
    ]


def transcribe(wav_path: Path, on_progress: ProgressFn) -> Path:
    """Modalità raccolta: traccia singola, testo continuo senza timestamp."""
    on_progress("Carico il modello di trascrizione...")
    _get_model(WHISPER_MODEL)
    on_progress("Trascrivo l'audio...")
    segs = _segments(wav_path, WHISPER_MODEL)

    TRANSCRIPTS_DIR.mkdir(exist_ok=True)
    txt_path = TRANSCRIPTS_DIR / (wav_path.stem + ".txt")
    txt_path.write_text(" ".join(s["text"] for s in segs), encoding="utf-8")
    return txt_path


def transcribe_meeting(paths: dict[str, Path], out_stem: str, on_progress: ProgressFn) -> Path:
    """Modalità riunione: trascrive le tracce separatamente e le fonde in ordine
    cronologico, etichettando chi parla. Le due registrazioni partono insieme,
    quindi i timestamp sono confrontabili direttamente."""
    on_progress(f"Carico il modello di trascrizione ({MEETING_WHISPER_MODEL})...")
    _get_model(MEETING_WHISPER_MODEL)

    labelled: list[dict] = []
    labels = {audio.REMOTE: "Interlocutori", audio.MIC: "Io"}
    for key in (audio.REMOTE, audio.MIC):
        wav = paths.get(key)
        if not wav or not wav.exists():
            continue
        on_progress(f"Trascrivo la traccia \"{labels[key]}\"...")
        for seg in _segments(wav, MEETING_WHISPER_MODEL):
            seg["speaker"] = labels[key]
            labelled.append(seg)

    labelled.sort(key=lambda s: s["start"])

    # accorpa battute consecutive dello stesso parlante: più leggibile per Claude
    lines: list[str] = []
    current_speaker = None
    buffer: list[str] = []
    buffer_start = 0.0
    for seg in labelled:
        if seg["speaker"] != current_speaker:
            if buffer:
                lines.append(f"[{_fmt_ts(buffer_start)}] {current_speaker}: {' '.join(buffer)}")
            current_speaker = seg["speaker"]
            buffer = []
            buffer_start = seg["start"]
        buffer.append(seg["text"])
    if buffer:
        lines.append(f"[{_fmt_ts(buffer_start)}] {current_speaker}: {' '.join(buffer)}")

    TRANSCRIPTS_DIR.mkdir(exist_ok=True)
    txt_path = TRANSCRIPTS_DIR / f"{out_stem}.txt"
    txt_path.write_text("\n".join(lines), encoding="utf-8")
    return txt_path


TITLE_PROMPTS = {
    "book": (
        "Leggi questa trascrizione audio e restituisci SOLO un titolo breve "
        "(max 6 parole: il nome del podcast/audiolibro/corso se viene menzionato, "
        "altrimenti l'argomento principale)."
    ),
    "meeting": (
        "Leggi questa trascrizione di una riunione e restituisci SOLO un titolo breve "
        "(max 6 parole) che ne descriva l'oggetto principale, come lo scriveresti "
        "nell'oggetto di una mail di riepilogo."
    ),
}


def infer_title(txt_path: Path, kind: str = "book") -> str:
    excerpt = txt_path.read_text(encoding="utf-8")[:4000]
    prompt = (
        f"{TITLE_PROMPTS[kind]} Nessuna virgoletta, nessun testo aggiuntivo, "
        f"una riga sola.\n\n{excerpt}"
    )
    result = subprocess.run(
        [_claude_bin(), "-p", prompt, "--allowedTools", ""],
        cwd=BASE_DIR,
        capture_output=True,
        text=True,
    )
    title = result.stdout.strip().strip('"').splitlines()[0].strip() if result.stdout.strip() else ""
    return title or ("riunione" if kind == "meeting" else "episodio")


def rename_files(wav_path: Path, txt_path: Path, book_slug: str, title: str, timestamp: str) -> tuple[Path, Path]:
    base = f"{book_slug}__{_slugify(title)}_{timestamp}"
    new_wav = RECORDINGS_DIR / f"{base}.wav"
    new_txt = TRANSCRIPTS_DIR / f"{base}.txt"
    wav_path.rename(new_wav)
    txt_path.rename(new_txt)
    return new_wav, new_txt


BOOK_PROMPT_TEMPLATE = """Sei il mio assistente personale per la raccolta di appunti. Sto costruendo \
una raccolta di note intitolata "{book_title}", a cui aggiungo contenuti man mano che ascolto episodi \
(podcast, audiolibri, corsi audio...) legati a questo argomento, di solito mentre mi alleno. Ti passo \
la trascrizione grezza (con probabili errori di trascrizione) dell'episodio appena ascoltato, e il \
contenuto attuale della raccolta.

Compito:
1. Leggi la trascrizione ed estrai SOLO le informazioni realmente utili e pertinenti al tema di questa \
raccolta ("{book_title}"): consigli pratici, concetti chiave, dati/numeri rilevanti, insegnamenti, \
esempi significativi. Ignora chiacchiere, sponsor, saluti, ripetizioni e tutto ciò che non è pertinente.
2. Organizza quanto estratto per argomento/sotto-tema (usa o riusa le sezioni già presenti nella \
raccolta, creane di nuove se serve).
3. Integra i nuovi contenuti in quelli esistenti: se un concetto è già presente non duplicarlo, ma \
arricchiscilo o segnala eventuali contraddizioni tra fonti diverse.
4. Aggiungi in fondo a ogni voce nuova un riferimento breve tra parentesi alla fonte: (fonte: {episode_label}).
5. Alla fine mantieni una sezione '## Indice episodi ascoltati' con la lista degli episodi processati.

Riscrivi l'intero file aggiornato di {book_rel_path} e SALVALO usando i tuoi strumenti di editing \
(Edit/Write), non limitarti a stamparlo. Non toccare altri file.

--- CONTENUTO ATTUALE DELLA RACCOLTA ---
{book_content}

--- TRASCRIZIONE EPISODIO ({episode_label}) ---
{transcript}
"""


MEETING_PROMPT_TEMPLATE = """Sei il mio assistente per i verbali di riunione. Ti passo la trascrizione \
automatica di una riunione a cui ho appena partecipato. La trascrizione è grezza e contiene errori di \
riconoscimento (nomi propri, sigle e termini tecnici sono spesso sbagliati): interpretala con buon senso \
e correggi ciò che è chiaramente un errore di trascrizione, senza però inventare contenuti.

Ogni battuta è marcata con il timestamp e con chi parla:
- "Io" sono io, l'utente (traccia del microfono di questo PC).
- "Interlocutori" sono tutti gli altri partecipanti insieme (audio in arrivo dalla call): non è possibile \
distinguerli automaticamente, ma spesso si capisce dal contesto o dal fatto che si chiamino per nome. \
Quando l'attribuzione è ragionevolmente certa usa il nome, altrimenti resta generico. Non attribuire mai \
un impegno a una persona di cui non sei sicuro.

{participants_block}
Scrivi un verbale in italiano, in questo formato:

# {title}
*{date_human} · durata ~{duration}*

## In sintesi
Tre-cinque bullet con l'essenziale, leggibili da chi non era presente.

## Decisioni prese
Ogni decisione su una riga, con il contesto minimo per capirla. Se non ce ne sono, scrivilo.

## Azioni da fare
Tabella markdown con colonne: Azione | Responsabile | Scadenza. Usa "da definire" dove il dato manca. \
Includi le azioni in capo a me distinguendole chiaramente.

## Punti aperti e questioni irrisolte
Domande rimaste senza risposta, disaccordi, cose rimandate.

## Discussione in dettaglio
I temi affrontati, uno per sotto-sezione, con i passaggi rilevanti e i numeri/date citati. Riporta tra \
virgolette solo le frasi davvero significative, con il timestamp.

## Note di attendibilità
Elenca i punti in cui la trascrizione era ambigua o incomprensibile e la tua ricostruzione è incerta, \
con il timestamp, così posso verificarli riascoltando. Se non ce ne sono, scrivi "nessuna".

Scrivi il file {meeting_rel_path} usando i tuoi strumenti di editing (Write), non limitarti a stampare \
il testo. Non toccare altri file.

--- TRASCRIZIONE RIUNIONE ---
{transcript}
"""


def update_book(txt_path: Path, book_slug: str, book_title: str, episode_title: str, timestamp: str,
                 on_progress: ProgressFn) -> None:
    on_progress(f"Claude sta aggiornando \"{book_title}\"...")
    ensure_book(book_slug, book_title)
    path = book_path(book_slug)

    episode_label = f"{episode_title} ({timestamp})"
    prompt = BOOK_PROMPT_TEMPLATE.format(
        book_title=book_title,
        book_rel_path=f"book/{book_slug}.md",
        episode_label=episode_label,
        book_content=path.read_text(encoding="utf-8"),
        transcript=txt_path.read_text(encoding="utf-8"),
    )
    subprocess.run(
        [_claude_bin(), "-p", prompt, "--allowedTools", "Edit,Write,Read"],
        cwd=BASE_DIR,
        check=True,
    )


def write_minutes(txt_path: Path, meeting_slug: str, title: str, participants: str,
                  timestamp: str, duration: str, on_progress: ProgressFn) -> None:
    on_progress("Claude sta scrivendo il verbale...")
    MEETINGS_DIR.mkdir(exist_ok=True)

    participants_block = ""
    if participants.strip():
        participants_block = (
            f"Partecipanti dichiarati da me: {participants.strip()}. Usa questi nomi "
            "quando attribuisci interventi e azioni.\n\n"
        )

    date_part, _, time_part = timestamp.partition("_")
    date_human = f"{date_part} {time_part.replace('-', ':')}"

    prompt = MEETING_PROMPT_TEMPLATE.format(
        title=title,
        date_human=date_human,
        duration=duration,
        participants_block=participants_block,
        meeting_rel_path=f"meetings/{meeting_slug}.md",
        transcript=txt_path.read_text(encoding="utf-8"),
    )
    subprocess.run(
        [_claude_bin(), "-p", prompt, "--allowedTools", "Edit,Write,Read"],
        cwd=BASE_DIR,
        check=True,
    )


def process_episode(wav_path: Path, book_slug: str, book_title: str, title: str, timestamp: str,
                     on_progress: ProgressFn) -> dict:
    txt_path = transcribe(wav_path, on_progress)

    if not txt_path.read_text(encoding="utf-8").strip():
        on_progress("Trascrizione vuota: audio silenzioso o non registrato correttamente.")
        txt_path.unlink(missing_ok=True)
        wav_path.unlink(missing_ok=True)
        raise RuntimeError("Trascrizione vuota")

    if not title:
        on_progress("Deduco il titolo dal contenuto...")
        title = infer_title(txt_path)

    wav_path, txt_path = rename_files(wav_path, txt_path, book_slug, title, timestamp)
    on_progress(f"Titolo: {title}")

    update_book(txt_path, book_slug, book_title, title, timestamp, on_progress)
    on_progress("Fatto!")
    return {
        "title": title, "timestamp": timestamp,
        "book_slug": book_slug, "book_title": book_title,
        "wav": str(wav_path), "txt": str(txt_path),
    }


def process_meeting(paths: dict[str, Path], title: str, participants: str, timestamp: str,
                    duration: str, on_progress: ProgressFn) -> dict:
    txt_path = transcribe_meeting(paths, f"meeting__{timestamp}", on_progress)

    if not txt_path.read_text(encoding="utf-8").strip():
        on_progress("Trascrizione vuota: audio silenzioso o non registrato correttamente.")
        txt_path.unlink(missing_ok=True)
        for p in paths.values():
            p.unlink(missing_ok=True)
        raise RuntimeError("Trascrizione vuota")

    if not title:
        on_progress("Deduco il titolo dal contenuto...")
        title = infer_title(txt_path, kind="meeting")
    on_progress(f"Titolo: {title}")

    meeting_slug = f"{timestamp}__{_slugify(title)}"
    new_txt = TRANSCRIPTS_DIR / f"meeting__{meeting_slug}.txt"
    txt_path.rename(new_txt)
    for key, p in list(paths.items()):
        if p.exists():
            p.rename(RECORDINGS_DIR / f"meeting__{meeting_slug}.{key}.wav")

    write_minutes(new_txt, meeting_slug, title, participants, timestamp, duration, on_progress)
    on_progress("Verbale pronto!")
    return {
        "title": title, "timestamp": timestamp,
        "meeting_slug": meeting_slug, "txt": str(new_txt),
    }
