# Audio Notes

Registra l'audio che passa da questo PC, lo trascrive in locale e usa Claude Code per
trasformarlo in testo utile. Due modalità, scelte dalle linguette in alto nella webapp:

- **Raccolta note** — podcast, audiolibri, corsi: i contenuti si accumulano in una o più
  "raccolte" (libri) che crescono episodio dopo episodio.
- **Riunione** — registra insieme l'audio della call e il tuo microfono, e produce un
  **verbale** autonomo per ogni incontro: sintesi, decisioni, azioni con responsabile e
  scadenza, punti aperti.

Tutto in locale: l'audio non esce mai da questo computer, solo la trascrizione testuale
viene passata a Claude Code.

## Installazione

Serve Linux con PipeWire (`pw-record`, `wpctl`), Python 3.11+ e la CLI di
[Claude Code](https://docs.anthropic.com/en/docs/claude-code) con accesso già fatto.

```bash
python3 -m venv venv
venv/bin/pip install -r requirements.txt

# servizio utente e icona nel menu: sostituisci /percorso/audio-notes nei due file
cp deploy/audio-notes.service ~/.config/systemd/user/
cp deploy/audio-notes.desktop ~/.local/share/applications/
systemctl --user daemon-reload
```

Audio, trascrizioni, verbali e raccolte (`recordings/`, `transcripts/`, `meetings/`,
`book/`) sono esclusi dal repository e restano solo sul tuo computer.

## Come funziona

1. **Registrazione (loopback)**: cattura l'audio in uscita da questo PC (quello che
   senti dagli speaker/cuffie), tramite PipeWire — nessun rumore ambientale, qualità
   pulita.
2. **Trascrizione locale**: [faster-whisper](https://github.com/SYSTRAN/faster-whisper)
   (modello `small`, CPU, offline) converte l'audio in testo.
3. **Estrazione con Claude Code**: la trascrizione grezza + il contenuto attuale della
   raccolta scelta vengono passati a `claude -p`, che estrae solo le informazioni
   pertinenti al tema di quella raccolta, le organizza per argomento e aggiorna il file
   `book/<raccolta>.md` evitando duplicati.
4. Se non specifichi un titolo per l'episodio, viene dedotto automaticamente dal
   contenuto.

## Modalità riunione

Seleziona la linguetta **Riunione**, eventualmente scrivi i nomi dei partecipanti (aiuta
molto Claude ad attribuire correttamente interventi e azioni) e registra.

### Perché servono due tracce

Il loopback cattura solo ciò che **esce** dal PC: se ascolti in cuffia, la tua voce non
passa di lì e il verbale risulterebbe monco. Per questo in modalità riunione vengono
registrate due tracce separate:

- `*.remote.wav` — il monitor del sink di default: le voci degli altri partecipanti
- `*.mic.wav` — il microfono di default: la tua voce

Le due tracce partono insieme, vengono trascritte separatamente e poi fuse in ordine
cronologico con l'etichetta di chi parla:

```
[00:03:12] Interlocutori: ...
[00:03:20] Io: ...
```

È una diarizzazione "gratuita" (io / gli altri) senza bisogno di pyannote o WhisperX.
I singoli interlocutori non sono distinguibili tra loro: Claude prova ad attribuirli per
contesto quando ne ha indizi ragionevoli, e segnala nel verbale i punti in cui non è certo.

### Le cuffie sono un vantaggio

Con le cuffie le due tracce restano pulite e separate. **Senza** cuffie il microfono
riprende anche l'audio degli altri dagli speaker, e ti ritrovi le stesse frasi due volte,
sfasate. Se non usi le cuffie, conviene togliere la spunta "Registra anche il mio
microfono" e accettare di perdere i propri interventi.

Attenzione alle **cuffie Bluetooth**: se il sistema ne usa anche il microfono, il profilo
scende da A2DP a HFP/HSP e la qualità audio crolla a banda telefonica, in ingresso e in
uscita. Meglio cuffie BT con il microfono del PC, oppure cuffie cablate.

### Dove finiscono i verbali

In `meetings/<data>__<titolo>.md`, uno per riunione, visibili nella webapp e apribili con
qualunque editor markdown. La trascrizione integrale con i turni di parola resta in
`transcripts/meeting__*.txt`, e l'audio in `recordings/` — utile per riascoltare i punti
che il verbale segnala come incerti nella sezione "Note di attendibilità".

### Una nota non tecnica

Registrare una riunione richiede di avvisare i partecipanti: in molti contesti, anche per
legge.

## Più libri/raccolte

Ogni registrazione va a finire in una **raccolta** a tua scelta: puoi averne una per
la finanza personale, una per gli appunti di un audiolibro, una per un corso, ecc.
Nella webapp basta scrivere il nome della raccolta nel campo "Libro / raccolta" — se
esiste già viene continuata, altrimenti viene creata al volo. Le raccolte esistenti
compaiono anche come pillole cliccabili per rivedere il contenuto di ciascuna.

Il prompt inviato a Claude è generico e usa il nome della raccolta per capire cosa
estrarre: funziona sia per "Finanza personale" sia per "Atomic Habits" sia per
qualunque altro argomento, senza bisogno di modificare il codice.

## Uso — un click, niente terminale

Il server **non gira sempre**: parte solo quando apri l'app e si ferma quando hai
finito, così non consuma risorse in background inutilmente.

- apri **"Audio Notes"** dall'icona sul Desktop, oppure cercalo nelle
  Attività/menu applicazioni di GNOME → il server parte da solo in quel momento
- si apre una finestra dedicata (senza barra indirizzi/tab, come un programma vero)
  già puntata sull'app

Da lì:

- scrivi (o scegli da quelle esistenti) il nome della raccolta a cui vuoi aggiungere
  l'episodio, ed eventualmente il titolo dell'episodio (opzionale, altrimenti dedotto)
- premi il pulsante rotondo per avviare la registrazione
- fai l'allenamento con l'audio riprodotto su questo PC
- premi di nuovo il pulsante per fermare: parte in automatico trascrizione +
  aggiornamento della raccolta, con lo stato mostrato live nella pagina
- il contenuto aggiornato appare subito sotto, con la lista degli episodi già
  processati per quella raccolta
- quando hai finito, premi **"Chiudi app"** in alto a destra: ferma il server e chiude
  la finestra (disabilitato mentre c'è una registrazione/elaborazione in corso, per
  sicurezza)

## Uso — CLI (alternativa, solo finanza personale)

Gli script da terminale restano disponibili come fallback rapido, ma lavorano solo
sulla raccolta originale di finanza personale (`book/personal_finance_book.md`), non
supportano ancora la scelta della raccolta:

```bash
./record.sh                              # titolo dedotto automaticamente
./record.sh "The Bull - Il Sole 24 Ore"  # oppure specifica subito il titolo
# ... allenamento + ascolto podcast ...
./stop_and_process.sh                    # ferma, trascrive e aggiorna il libro
```

Ogni raccolta è comunque un normale file markdown in `book/` — apribile con qualunque
editor di testo/markdown, anche dal telefono se sincronizzato (es. Syncthing, Obsidian
vault, ecc).

## Gestione del servizio in background

Il server è un servizio utente di systemd, avviato da `open_app.sh` quando apri l'app.
Comandi utili se mai servisse intervenire (da terminale, solo per manutenzione):

```bash
systemctl --user status audio-notes   # è attivo?
systemctl --user restart audio-notes  # riavvialo (es. dopo un aggiornamento)
journalctl --user -u audio-notes -f   # log in tempo reale
```

`run.sh` resta come modalità manuale alternativa (utile solo per debug): se lo usi,
ferma prima il servizio con `systemctl --user stop audio-notes` per evitare
conflitti sulla porta 8765.

## Configurazione

- Modelli Whisper, configurabili da variabili d'ambiente (nel file di servizio
  systemd, con `Environment=`):
  - `WHISPER_MODEL` — modalità raccolta, default `small`: una voce sola, registrata in
    studio, non chiede di più.
  - `MEETING_WHISPER_MODEL` — modalità riunione, default `medium`: più parlanti, microfoni
    scadenti e sovrapposizioni rendono `small` poco affidabile.
  - `WHISPER_LANGUAGE` — default `it`.

  Il primo uso della modalità riunione scarica `medium` (~1,5 GB) da Hugging Face: la
  prima elaborazione è quindi più lenta, le successive no. Ordine di grandezza su CPU:
  un'ora di audio richiede ~15 minuti con `small` e ~40 con `medium`. In modalità riunione
  le tracce sono due, ma il VAD scarta i silenzi — e la traccia del microfono è muta per
  gran parte del tempo, quindi costa poco.
- Porta della webapp: `8765`, modificabile nel file di servizio
  `~/.config/systemd/user/audio-notes.service` (poi `daemon-reload` +
  `restart`).

## Note

- La registrazione cattura l'audio di **uscita** del PC (loopback), quindi l'audio
  deve essere riprodotto sugli speaker/cuffie collegati a questo computer, non su un
  altro dispositivo. Vale anche per le riunioni: la call deve essere sul PC, non sul
  telefono.
- Sink e microfono vengono risolti come device **di default** al momento di ogni
  registrazione, quindi puoi collegare le cuffie anche a server già avviato: basta che
  siano attive prima di premere REC.
- Se in futuro vuoi processare anche file già scaricati (mp3/file esistenti), basta
  lanciare direttamente:
  `venv/bin/python transcribe.py percorso/file.mp3`
  e poi passare a mano il transcript risultante a Claude Code con lo stesso prompt
  usato in `app/pipeline.py`.
