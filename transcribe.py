#!/usr/bin/env python3
"""Trascrive un file audio in testo usando faster-whisper (locale, offline)."""
import sys
import os
from pathlib import Path

MODEL_SIZE = os.environ.get("WHISPER_MODEL", "small")  # small = buon compromesso su CPU
LANGUAGE = os.environ.get("WHISPER_LANGUAGE", "it")


def main():
    if len(sys.argv) != 2:
        print("Uso: transcribe.py <file_audio.wav>", file=sys.stderr)
        sys.exit(1)

    audio_path = Path(sys.argv[1])
    if not audio_path.exists():
        print(f"File non trovato: {audio_path}", file=sys.stderr)
        sys.exit(1)

    from faster_whisper import WhisperModel

    print(f"Carico il modello Whisper '{MODEL_SIZE}' (CPU)...", file=sys.stderr)
    model = WhisperModel(MODEL_SIZE, device="cpu", compute_type="int8")

    print(f"Trascrivo {audio_path.name}...", file=sys.stderr)
    segments, info = model.transcribe(str(audio_path), language=LANGUAGE, vad_filter=True)

    print(f"Lingua rilevata: {info.language} (prob. {info.language_probability:.2f})", file=sys.stderr)

    out_dir = audio_path.parent.parent / "transcripts"
    out_dir.mkdir(exist_ok=True)
    out_path = out_dir / (audio_path.stem + ".txt")

    with open(out_path, "w", encoding="utf-8") as f:
        for seg in segments:
            f.write(seg.text.strip() + " ")

    print(str(out_path))


if __name__ == "__main__":
    main()
