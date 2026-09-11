# 🎹 MIDI Studio

App locale (separata da SampleLab, **porta 5080**) che fa due cose in un'unica
interfaccia web:

1. **Estrai MIDI da un audio** — l'estrattore *FORTISSIMO PRO — Auto-Analyzer*
   (JS puro: rileva K strumenti, separazione Wiener, trascrizione YIN, piano
   roll) gira **nel browser**; i `.mid` generati vengono salvati automaticamente
   in `files/`.
2. **Confronta due MIDI** — il backend legge i `.mid` con `mido` e usa il modello
   **Fortissimo Compare v3** (`../fortissimo_compare_v3.py`) per confrontare
   strumento per strumento.

## Avvio automatico (consigliato)

Una volta sola:

```bash
cd "/Users/alessandrolocurcio/Documents/musica/sample lab/midi_studio"
./install_autostart.sh
```

Da quel momento **parte da solo a ogni accesso** al Mac (e viene riavviato se
cade): ti basta aprire **http://localhost:5080**.

Gestione:

```bash
./gestisci.sh status    # stato del servizio
./gestisci.sh restart   # riavvia dopo una modifica al codice
./gestisci.sh stop      # ferma ora (riparte al prossimo accesso)
./gestisci.sh log       # ultime righe di log
./uninstall_autostart.sh   # rimuove l'avvio automatico
```

## Avvio manuale (senza autostart)

```bash
cd "/Users/alessandrolocurcio/Documents/musica/sample lab/midi_studio"
python3 midi_studio.py     # → http://localhost:5080
```

Se la 5080 è occupata l'app passa da sola alla porta libera successiva
(5081, 5082…) e lo dice in avvio; se siamo già in esecuzione non fa nulla.

## Come si usa

- **Tab “Estrai MIDI”**: trascina/ carica un audio (WAV, MP3, FLAC, OGG) → premi
  *Analizza* → al termine trovi i `.mid` scaricabili e **già salvati** in
  `files/`. Per una prova veloce c'è *Scarica test_audio.wav* in cima alla tab.
- **Tab “Confronta MIDI”**: scegli due `.mid` (dall'elenco dei file generati
  oppure caricandoli) e premi *CONFRONTA*. Vedi il punteggio complessivo, il
  dettaglio per strumento (match, MIDI, one-shot, peso) e le tracce lette.
- **Tab “File generati”**: elenco dei file salvati con download e cancellazione.

C'è anche un **banco di prova dell'algoritmo puro** su
**http://localhost:5080/alg**: esegue solo le funzioni di calcolo
(`midi_studio/alg/fortissimo_alg.js`, estratte identiche dall'estrattore) su un
audio di prova o su un file caricato, e per **ogni traccia** mostra una scheda con
piano roll e i pulsanti di ascolto — *🎹 MIDI con lo strumento* (il MIDI reso con
il one-shot di quella sorgente), *🔊 Traccia separata*, *🎯 Campione* — più i
download del `.mid` e del rendering `.wav`; in cima i comandi globali (originale,
mix MIDI+one-shot, mix ricostruito). Serve per sviluppare l'algoritmo senza
l'interfaccia: descrizione, limiti misurati e prompt pronto per un'AI in
`midi_studio/alg/`.

## Endpoint (per script/automazioni)

| Endpoint | Metodo | Cosa fa |
|---|---|---|
| `/` | GET | interfaccia |
| `/extract` | GET | l'estrattore MIDI |
| `/api/health` | GET | stato app, modello, porta |
| `/api/files` | GET | elenco file salvati (con tracce/note/durata/bpm per i MIDI) |
| `/api/save-midi` | POST | salva un `.mid` (usato dall'estrattore) |
| `/api/compare` | POST | confronta due MIDI: upload `a`/`b` oppure `a_name`/`b_name` (+ pesi `w_*`) |
| `/api/test-audio` | GET | WAV di prova generato al volo (`?seconds=2.5`) |
| `/api/delete/<nome>` | DELETE | cancella un file |
| `/download/<nome>` | GET | scarica un file |

Esempio:

```bash
curl -s -F a=@primo.mid -F b=@secondo.mid localhost:5080/api/compare | python3 -m json.tool
```

## Come funziona il confronto MIDI

Il modello v3 confronta due `AudioAnalysisOutput`, cioè note MIDI **+** one-shot
audio. I `.mid` non contengono audio, quindi (`midi_analysis.py`):

- ogni **traccia** con note diventa uno strumento: le note reali vanno nel blocco
  MIDI, l'estensione/velocity restano quelle del file;
- il **one-shot viene sintetizzato** (tono pluck sul pitch dominante della traccia,
  ampiezza dalla velocity media) — stessa convenzione dell'esempio del modello;
- il **nome traccia** viene ricondotto ai nomi usati dal matching
  (`Kick/Snare/Hi-Hat` → `drum`, `Piano/Guitar` → `piano`, `Sub Bass` → `bass`,
  `Synth/FX` → `synthesizer`, `Brass` → `trumpet`, …), con fallback sul program
  General MIDI e sul canale 10 (percussioni);
- la **tempo map** è rispettata: i tick diventano secondi contando i cambi di tempo.

Limiti noti del modello (ereditati, non introdotti qui): lo score di due MIDI
identici è **0.925** e non 1.0 (`TrackComparator` somma i pesi a 0.85), e il
matching timbrico vale sempre 0.1 per un bug delle bande in
`InstrumentMatcher._timbre_features` → in pratica matcha il **nome**. Dettagli in
`../README.md`.

## Bug corretti nell'estrattore (11/09/2026)

Il file scaricato (`fortissimo_pro.html`) **non funzionava affatto**: la copia in
questo progetto (`extractor.html`) è la stessa pagina con **5 correzioni minime**
più l'aggiunta che salva i MIDI sul server.

1. **Errore di sintassi che uccideva tutto lo script.** In `show()` i pulsanti dei
   campioni erano costruiti con `onclick="ps(''+s.id+'')"` dentro una stringa JS
   delimitata da apici singoli → `SyntaxError: Unexpected string literal '+s.id+'`:
   **nessuna** funzione della pagina veniva definita (`run`, `hf`, `writeMidi`…
   tutte `undefined`). → `onclick="ps(\''+s.id+'\')"`.
2. **`onchange="handleFile(event)"`** ma la funzione si chiama `hf` → scegliere un
   file non faceva nulla. → `onchange="hf(event.target.files[0])"`.
3. **`ondrop="handleDrop(event)"`** ma la funzione si chiama `hd` → il drag&drop
   non faceva nulla. → `ondrop="hd(event)"`.
4. **`const sdr=siSdr(O,R),mse=mse(O,R),cor=corr(O,R)`**: la costante locale `mse`
   ombreggia la funzione omonima e viene usata nel proprio inizializzatore →
   `ReferenceError` (TDZ) a fine analisi: la pagina restava su "FASE 7 — 90%" senza
   mai mostrare i risultati. → variabile rinominata `mseV` (aggiornata la chiamata
   a `show`).
5. **File MIDI non validi.** `vl()` non scriveva nulla per i delta-time negativi
   (note che si sovrappongono) → l'MTrk si "sfasava" e i file contenevano byte
   fuori range (`data byte must be in range 0..127`): illeggibili da mido e da
   qualsiasi DAW. → i delta sono ora limitati a ≥ 0 in entrambi i writer
   (`writeMidi`, `writeMultiMidi`).
6. **Analisi che moriva al 90% su audio più lungo di ~2,7 s.** `recon()` faceva
   `Math.max(...recon.map(Math.abs))` su un array lungo quanto tutto l'audio:
   in Chrome lo spread di argomenti esplode già a ~125.000 elementi
   (`RangeError: Maximum call stack size exceeded`), quindi qualsiasi brano vero
   si fermava su "FASE 7 — 90%" senza risultati. → massimo calcolato con un
   ciclo (corretta anche `proc()` e il piano roll, che usavano lo stesso schema).
   Trovato durante un test su un estratto reale di 12 s.

In coda alla pagina c'è l'aggiunta di MIDI Studio: al termine dell'analisi i `.mid`
generati vengono inviati a `POST /api/save-midi`, così compaiono subito in
"File generati" e nel selettore di "Confronta MIDI".

## Tempi e qualità (misurati)

- **Tempo**: l'analisi gira in JavaScript, in un solo thread, e il costo cresce
  con durata e numero di sorgenti rilevate. Misure reali: **6,6 s** per un
  estratto di 12 s di un brano vero (2 sorgenti), ~10 s per 2,5 s di audio
  sintetico (5 sorgenti). In pratica: da ~0,5× a ~4× la durata del brano, quindi
  per una canzone intera aspettati **da 1-2 a ~10 minuti**.
- **Tieni la tab in primo piano**: Chrome rallenta le tab in background e
  chiudendo la pagina l'analisi si interrompe (non c'è nulla lato server).
- **Qualità**: la trascrizione è pensata per materiale **melodico/sparso**
  (sul test sintetico: 5 strumenti e 38 note, coerenti). Su un mix denso e
  moderno estrae molto meno (sull'estratto di "Average Joe": 2 sorgenti, 1 nota
  ciascuna, SI-SDR -40 dB): il valore è indicativo, non è una trascrizione
  professionale.

## Consigli sul confronto

- Per confrontare **due brani diversi**: estrai entrambi e usa i rispettivi
  `final_multi_track.mid`. Le loro tracce si chiamano `s0…sN` (id tecnici): il
  bridge le tratta come **generiche** e le abbina per timbro/pitch, quindi il
  punteggio è significativo.
- Confrontando file **per singolo strumento** (`Synth/FX.mid`, `Kick.mid`, …)
  l'abbinamento avviene per nome (`synthesizer`, `drum`, …).
- Un singolo file strumento contro un multi-traccia dà 0 perché i nomi non
  corrispondono: è il comportamento previsto dal modello (match per nome +
  timbro), non un errore.


## Test

```bash
cd "/Users/alessandrolocurcio/Documents/musica/sample lab/midi_studio"
python3 -m unittest -v test_midi_studio     # 23 test (parsing, confronto, HTTP)
```

I test HTTP girano solo se l'app è attiva (altrimenti vengono saltati);
l'URL si può cambiare con `MIDI_STUDIO_URL`.

## File

| File | Ruolo |
|---|---|
| `midi_studio.py` | server Flask (porta 5080) + API |
| `midi_analysis.py` | parsing `.mid` (mido) → modello Fortissimo + confronto |
| `studio.html` | interfaccia unificata (3 tab) |
| `extractor.html` | estrattore MIDI originale + salvataggio automatico nel server |
| `test_midi_studio.py` | test automatici |
| `install_autostart.sh`, `uninstall_autostart.sh`, `gestisci.sh` | avvio automatico e gestione |
| `files/`, `logs/` | dati generati e log (**non** versionati) |

Dipendenze: `flask`, `waitress`, `mido`, `numpy` (già installate).
