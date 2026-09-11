# SampleLab 🎵

Applicazione Flask per scaricare musica da YouTube, identificare campioni
(sample digging), gestire una libreria di brani e molto altro.

Sviluppata in locale su macOS e servita con il server WSGI **waitress**
sulla porta **5070**.

## Avvio

```bash
# 1) Installa le dipendenze (Python 3.14 consigliato)
pip install -r requirements.txt

# 2) Avvia l'app
python3 "app (2).py"
```

Poi apri il browser su: **http://localhost:5070**

Sull'account GitHub la versione "di produzione" corrisponde ai file
con `(2)` nella cartella locale:

| File locale            | File nel repo (se rinominato) |
|------------------------|-------------------------------|
| `app (2).py`           | (mantiene lo stesso nome)     |
| `index (2).html`       | (mantiene lo stesso nome)     |
| `samplelab (2).db`     | (mantiene lo stesso nome)     |

## File principali

- `app (2).py` — backend Flask unificato (download, scraping WhoSampled,
  mass renamer, database, verifica BPM/tonalità)
- `index (2).html` — interfaccia principale
- `browse.html` — interfaccia di navigazione libreria
- `onyx_whosampled.html` — scraping WhoSampled
- `samplelab (2).db` — database SQLite della libreria
- `fortissimo_compare_v3.py` — modello **Fortissimo Compare v3**: confronto tra
  due output `AudioAnalysis` (MIDI + one-shot), score [0,1]
- `fortissimo.html` — interfaccia di test del modello (pagina `/fortissimo`)
- `test_fortissimo_compare.py` — test del modello
  (`python3 -m unittest -v test_fortissimo_compare`)
- `midi_studio/` — **app separata (porta 5080)**: estrae MIDI da un audio e
  confronta due MIDI (vedi la sezione *MIDI Studio* qui sotto)
- `cookies.txt` — 🔒 versione **snellita**: solo i cookie anti-403 di YouTube
  (consenso + anti-bot), nessun dato di account Google, PayPal o altri siti.
  Sul Mac il file **completo** resta intatto (escluso dalla repo con
  `.gitignore` + `skip-worktree`) perché è quello che l'app usa davvero per
  i download senza errori 403. **Regola d'oro**: non caricare mai il file
  completo su GitHub — nemmeno in una repo privata.

## Cartelle escluse dal versionamento

- `downloads/` — audio scaricati (centinaia di GB)
- `stems/` — tracce separate generate
- `.trash/`, `.snapshots/`, `__pycache__/` — file temporanei

## Requisiti di sistema

- **ffmpeg** (`brew install ffmpeg`) per la conversione dei formati
- **Google Chrome** per lo scraping con `undetected_chromedriver`
- **librosa + numpy** opzionali ma consigliati per l'analisi audio

## Fortissimo Compare (pagina `/fortissimo`)

`fortissimo_compare_v3.py` è il modello di confronto tra due output
`AudioAnalysis` (YAMNet + Demucs → traccia MIDI + one-shot): matcha gli
strumenti per nome/timbro e aggrega uno **score [0,1]** con quattro valori
(overall, MIDI, one-shot, presence). La pagina
**http://localhost:5070/fortissimo** permette di provarlo senza scrivere codice:

- due editor JSON (analisi A e B) con tasto "Carica esempio" (le canzoni A/B di
  `fortissimo_compare_v3.py`: identiche tranne il piano suonato più forte);
- pesi regolabili: MIDI / one-shot / presence (devono sommare 1.0) e volume
  dentro il blocco one-shot;
- **Self-test del modello**: esegue l'esempio e mostra i controlli con esito;
- risultato: schede score con barre, tabella per strumento (match, MIDI, f1,
  one-shot, volume, peso, esito) e JSON completo.

Endpoint usati dalla pagina (implementati in `app (2).py`):

| Endpoint | Metodo | Cosa fa |
|---|---|---|
| `/fortissimo` | GET | la pagina |
| `/fortissimo/example` | GET | le due analisi di esempio (JSON) |
| `/fortissimo/selftest` | GET | esegue l'esempio e torna i controlli con esito |
| `/fortissimo/compare` | POST | confronta `{a, b, weights}` |

Formato del JSON di un'analisi (il one-shot non richiede file audio: la waveform
si genera da una spec):

```json
{"source_filename":"song_a.wav","global_tempo":120,"duration":4.0,
 "instruments":[{"instrument_name":"piano","separation_quality":1.0,
   "track":{"program":0,"channel":2,
            "pattern":{"base_pitch":60,"pattern":[0,4,7],"tempo":120,"velocity":100}},
   "one_shot":{"program":0,"pitch":72,"original_loudness":0.5,
               "audio":{"type":"pluck","freq":440,"duration":0.1,"amp":0.5}}}]}
```

In `track` le note si danno con `"notes"` esplicite o con `"pattern"` compatto;
`"audio"` accetta `{"type":"pluck"|"sine"|"noise"|"silence", ...}` oppure un
array di campioni.

Test: `python3 -m unittest -v test_fortissimo_compare` (22 test; quelli HTTP
girano solo se l'app è attiva, altrimenti vengono saltati).

**Due limiti noti del modello, documentati e NON corretti** (servono i test per
evidenziarli, non è codice nostro):

1. **Tetto dello score = 0.925.** `TrackComparator` somma i pesi a 0.85
   (0.25+0.20+0.15+0.10+0.15), quindi il blocco MIDI vale al massimo 0.85 e due
   brani **identici** danno 0.925 invece di 1.0.
2. **Il timbro non entra mai nel matching.** In `InstrumentMatcher._timbre_features`
   le bande `[0, 100, 500, 2000, 8000, len(spec)]` sono usate come *indici di bin*
   su uno spettro che con `n_fft=2048` ha 1025 bin: la banda 2000→8000 è vuota,
   `np.mean([])` → **NaN** e `np.linalg.norm(features)` → NaN. Misurato:
   `_timbre_similarity` restituisce **0.1 per qualsiasi coppia** (piano identico,
   piano a volume diverso, piano vs rumore) e `_instrument_similarity` tra nomi
   diversi si ferma a 0.08 (sotto la soglia 0.7): in pratica matcha solo il
   **nome** YAMNet, non il timbro. (I valori sono pensati in Hz ma usati come
   indici: la correzione è convertire Hz→bin con `freqs` e limitare l'indice.)


## MIDI Studio (porta 5080) — estrai MIDI da un audio e confronta due MIDI

`midi_studio/` è un'**app locale separata** da questa (così non tocca SampleLab):
un'unica interfaccia web con tre tab.

- **🎵 Estrai MIDI** — l'estrattore *FORTISSIMO PRO — Auto-Analyzer* (`extractor.html`,
  JS puro: rileva K strumenti, separazione Wiener, trascrizione YIN, piano roll)
  gira **nel browser**: carichi un audio e ottieni i `.mid` (uno per strumento +
  `final_multi_track.mid`) e i `.wav` dei campioni. I MIDI vengono salvati
  automaticamente in `midi_studio/files/`.
- **🔀 Confronta MIDI** — carichi due `.mid` (o scegli tra quelli generati) e il
  backend, con `mido` + `fortissimo_compare_v3.py`, dà lo score complessivo e il
  dettaglio per strumento.
- **📁 File generati** — elenco dei file salvati, con download e cancellazione.

**Avvio automatico (una volta sola):**

```bash
cd "/Users/alessandrolocurcio/Documents/musica/sample lab/midi_studio"
./install_autostart.sh          # servizio macOS: parte a ogni accesso
# poi apri http://localhost:5080
./gestisci.sh status|restart|stop|log
./uninstall_autostart.sh        # per togliere l'avvio automatico
```

Avvio manuale: `python3 midi_studio/midi_studio.py` (se la 5080 è occupata passa
da sola alla successiva; se è già attiva non fa nulla).

Dettagli, endpoint e note sul confronto MIDI: **`midi_studio/README.md`**.
Test: `cd midi_studio && python3 -m unittest -v test_midi_studio` (23 test).

**Nota**: l'estrattore scaricato (`fortissimo_pro.html`) non funzionava (errore di
sintassi JS, handler inline verso funzioni inesistenti, un `const` che si
auto-inizializzava, delta-time negativi che corrompevano i `.mid`): la copia
servita dall'app è corretta e l'elenco dei fix è in `midi_studio/README.md`.

## Note operative e stato corrente (11/09/2026)

Da tenere presente nelle sessioni di lavoro successive:

- **Cartella di lavoro = clone git.** Qui **non** esiste una copia di lavoro
  separata dal repository: si lavora direttamente in
  `/Users/alessandrolocurcio/Documents/musica/sample lab/` (il nome contiene
  spazi: **quota sempre i path**) e si committa da lì. `origin` =
  `https://github.com/Alessandro1040/samplelab.git`, branch `main`.
- **File "di produzione" vs legacy.** La versione su GitHub è quella con `(2)`
  nel nome: `app (2).py`, `index (2).html`, `samplelab (2).db`. I file `app.py`,
  `index.html`, `samplelab.db` sono **legacy**: non vanno allineati a mano né
  usati come base per le modifiche.
- **Avvio.** `python3 "app (2).py"` (waitress, thread pool 32). Se la porta 5070
  è occupata l'app passa da sola alla **5075**: va controllato nell'output di
  avvio. Sul Mac di origine gira su <http://localhost:5070>.
- **Cookie.** `cookies.txt` è tracciato con `skip-worktree`: sul Mac resta il
  file **completo** (è quello che serve a scaricare senza errori 403), in repo
  deve restare solo la versione **snellita** senza dati di account. Non
  committare mai il file completo.
- **`samplelab (2).db` è binario** e cambia a ogni uso: committarlo solo quando
  la modifica dei dati è voluta.
- **`remote_components=["ejs:github"]` rimosso** dai download (`_do_download`,
  `do_download_playlist`): con yt-dlp recenti provocava "Video unavailable"/403.
- **FORTISSIMO COMPARE (11/09/2026).** Aggiunti `fortissimo_compare_v3.py`, la
  pagina `/fortissimo` (`fortissimo.html`) e `test_fortissimo_compare.py`.
  Fix applicato al modello scaricato: in `AudioSimilarityModel.__init__` c'era
  `OneShotComparator(vol_weight=...)`, parametro inesistente → `TypeError` a
  ogni istanza (il file non partiva nemmeno da solo); ora è `volume_weight`.
  **Limite noto, non corretto:** i pesi di `TrackComparator` sommano a 0.85
  (0.25+0.20+0.15+0.10+0.15), quindi il blocco MIDI vale al massimo 0.85 e due
  brani **identici** arrivano a **0.925**, non a 1.0 (valore documentato nei
  test). Se i pesi vengono normalizzati a 1.0 vanno aggiornati
  `test_identico_score_tetto`, `test_tetto_dello_score_midi`, il test HTTP
  `test_compare_stesso_brano` e il check "score di due brani identici" dello
  `/fortissimo/selftest`.
- **MIDI STUDIO (11/09/2026).** Nuova app **separata** in `midi_studio/` (porta
  5080, l'app di questa repo resta la principale): serve l'estrattore MIDI e il
  confronto dei `.mid` in un'unica interfaccia. Resta sempre attiva: LaunchAgent
  `com.alessandrolocurcio.midistudio` (`RunAtLoad` + `KeepAlive`, log in
  `midi_studio/logs/`), installato da `midi_studio/install_autostart.sh`; si
  gestisce con `midi_studio/gestisci.sh` (status/start/stop/restart/log). I file
  generati stanno in `midi_studio/files/` (**non** versionati, come i log).
  L'estrattore scaricato non funzionava affatto: corretti 5 bug (sintassi JS,
  due handler inline verso funzioni inesistenti, `const` auto-inizializzato,
  delta-time negativi nei `.mid`) — elenco in `midi_studio/README.md`. Test: 23
  (`cd midi_studio && python3 -m unittest -v test_midi_studio`).

