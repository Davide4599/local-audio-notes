"""Cattura audio da PipeWire.

Due sorgenti possibili, registrate su file separati:

* ``remote`` — il monitor del sink di default: tutto ciò che esce dal PC
  (podcast, audiolibro, oppure le voci degli altri partecipanti alla riunione).
* ``mic`` — il microfono di default: la tua voce.

In modalità "raccolta" (podcast/audiolibro) serve solo ``remote``. In modalità
"riunione", se ascolti in cuffia, la tua voce NON passa dal sink: senza la
traccia ``mic`` il verbale risulterebbe monco. Tenerle su due file separati
permette poi di sapere chi ha detto cosa senza diarizzazione.
"""
import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

REMOTE = "remote"
MIC = "mic"


def _default_node_id(target: str) -> int | None:
    """Id PipeWire del nodo di default (``@DEFAULT_AUDIO_SINK@`` o ``@DEFAULT_AUDIO_SOURCE@``).

    Va risolto a ogni registrazione: collegare cuffie USB/Bluetooth cambia il
    device di default e quindi l'id.
    """
    try:
        out = subprocess.run(
            ["wpctl", "inspect", target], capture_output=True, text=True, check=True
        ).stdout
    except (subprocess.CalledProcessError, FileNotFoundError):
        return None
    m = re.match(r"\s*id (\d+)", out)
    return int(m.group(1)) if m else None


def _first_sink_name() -> str | None:
    """Fallback se wpctl non è disponibile: primo Audio/Sink visto da pw-cli."""
    try:
        out = subprocess.run(
            ["pw-cli", "ls", "Node"], capture_output=True, text=True, check=True
        ).stdout
    except (subprocess.CalledProcessError, FileNotFoundError):
        return None
    for block in out.split("id "):
        if 'media.class = "Audio/Sink"' in block:
            m = re.search(r'node\.name = "([^"]+)"', block)
            if m:
                return m.group(1)
    return None


def _node_description(node_id: int) -> str:
    try:
        out = subprocess.run(
            ["wpctl", "inspect", str(node_id)], capture_output=True, text=True, check=True
        ).stdout
    except (subprocess.CalledProcessError, FileNotFoundError):
        return str(node_id)
    m = re.search(r'node\.description = "([^"]+)"', out)
    return m.group(1) if m else str(node_id)


def _node_props(node_id: int) -> dict[str, str]:
    """Tutte le proprietà PipeWire di un nodo (node.name, device.api, profilo bluez...)."""
    try:
        out = subprocess.run(
            ["wpctl", "inspect", str(node_id)], capture_output=True, text=True, check=True
        ).stdout
    except (subprocess.CalledProcessError, FileNotFoundError):
        return {}
    props = {}
    for line in out.splitlines():
        m = re.match(r'\s*\*?\s*([\w.]+)\s*=\s*"?([^"]*)"?\s*$', line)
        if m:
            props[m.group(1)] = m.group(2)
    return props


# Profili Bluetooth che aprono il canale voce: il collegamento diventa
# bidirezionale ma scende a 8/16 kHz mono (CVSD/mSBC), qualità telefonica.
# Su un audio così Whisper non trascrive male: inventa.
_HFP_PROFILES = ("headset-head-unit", "headset-audio-gateway", "hfp", "hsp")


def preflight(capture_mic: bool) -> list[str]:
    """Problemi di configurazione audio che renderebbero inutile la registrazione.

    Restituisce una lista di messaggi: vuota se tutto a posto.
    """
    problems: list[str] = []

    sink_id = _default_node_id("@DEFAULT_AUDIO_SINK@")
    sink = _node_props(sink_id) if sink_id else {}
    sink_name = sink.get("node.description", "uscita sconosciuta")

    profile = sink.get("api.bluez5.profile", "").lower()
    if sink.get("device.api") == "bluez5" and any(p in profile for p in _HFP_PROFILES):
        problems.append(
            f"\"{sink_name}\" e' un dispositivo Bluetooth in modalita' vivavoce "
            f"(profilo {profile}): l'audio scende a qualita' telefonica e la "
            "trascrizione risultera' inventata. Imposta il microfono del PC come "
            "ingresso nella app della call: le cuffie torneranno in alta qualita'."
        )

    if capture_mic:
        src_id = _default_node_id("@DEFAULT_AUDIO_SOURCE@")
        src = _node_props(src_id) if src_id else {}
        src_name = src.get("node.name", "")
        if src_name.endswith(".monitor") or src.get("media.class") == "Audio/Source/Virtual":
            problems.append(
                f"Il microfono di default e' in realta' un monitor dell'uscita "
                f"(\"{src.get('node.description', src_name)}\"): le due tracce "
                "conterrebbero lo stesso audio. Scegli un microfono vero nelle "
                "impostazioni audio di sistema."
            )
        elif src_id and sink_id and src.get("device.id") == sink.get("device.id") \
                and sink.get("device.api") == "bluez5":
            problems.append(
                f"Microfono e cuffie sono lo stesso dispositivo Bluetooth "
                f"(\"{src_name}\"): usare il microfono forza il profilo vivavoce "
                "e degrada anche l'ascolto. Usa il microfono del PC."
            )

    return problems


def describe_devices(capture_mic: bool) -> str:
    """Descrizione leggibile dei device che verranno registrati (per la UI)."""
    sink = _default_node_id("@DEFAULT_AUDIO_SINK@")
    parts = [f"uscita: {_node_description(sink)}" if sink else "uscita: sink di default"]
    if capture_mic:
        src = _default_node_id("@DEFAULT_AUDIO_SOURCE@")
        parts.append(f"microfono: {_node_description(src)}" if src else "microfono: source di default")
    return " · ".join(parts)


@dataclass
class Recording:
    """Una registrazione in corso: uno o due processi pw-record e i relativi wav."""
    procs: dict[str, subprocess.Popen] = field(default_factory=dict)
    paths: dict[str, Path] = field(default_factory=dict)

    @property
    def primary(self) -> Path:
        return self.paths[REMOTE]


def _spawn(target: str | int, out_file: Path, log_file: Path) -> subprocess.Popen:
    with open(log_file, "ab") as log:
        return subprocess.Popen(
            ["pw-record", f"--target={target}", str(out_file)], stdout=log, stderr=log
        )


def start_recording(out_file: Path, capture_mic: bool = False) -> Recording:
    """Avvia la cattura. Con ``capture_mic`` i file diventano due: ``*.remote.wav``
    e ``*.mic.wav``; senza, resta il singolo file passato in ``out_file``."""
    log_file = out_file.parent.parent / ".record.log"

    problems = preflight(capture_mic)
    if problems:
        raise RuntimeError(" ".join(problems))

    sink_target: str | int | None = _default_node_id("@DEFAULT_AUDIO_SINK@")
    if sink_target is None:
        sink_target = _first_sink_name()
    if sink_target is None:
        raise RuntimeError("Nessun Audio/Sink trovato su questo PC (controlla PipeWire).")

    rec = Recording()

    if capture_mic:
        remote_path = out_file.with_suffix(".remote.wav")
        mic_path = out_file.with_suffix(".mic.wav")
    else:
        remote_path = out_file
        mic_path = None

    rec.paths[REMOTE] = remote_path
    rec.procs[REMOTE] = _spawn(sink_target, remote_path, log_file)

    if capture_mic:
        source_target = _default_node_id("@DEFAULT_AUDIO_SOURCE@")
        if source_target is None:
            stop_recording(rec)
            raise RuntimeError(
                "Nessun microfono di default trovato: la riunione registrerebbe solo gli altri."
            )
        rec.paths[MIC] = mic_path
        rec.procs[MIC] = _spawn(source_target, mic_path, log_file)

    return rec


def stop_recording(rec: Recording, timeout: float = 5.0) -> None:
    """SIGINT a tutti i pw-record: è il segnale con cui chiudono correttamente il WAV."""
    for proc in rec.procs.values():
        if proc.poll() is None:
            proc.send_signal(2)
    for proc in rec.procs.values():
        try:
            proc.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            proc.kill()
