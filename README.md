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
- `README_sampler.md` — **guida utente del sampler** (il trimmer FL-Studio della
  pagina `/`: griglia, BPM, offset, Battute Sel., Diventa Bar N°, Allinea griglia,
  TAP, metronomo, undo/redo, taglio): come aprirlo, ogni controllo spiegato e la
  matematica della griglia coi numeri misurati
- `test_sampler_tap.py` — test della stima **TAP** del sampler (funzione pura
  `bpmDaTap`: media di tutti i colpi, decimali, tocchi fuori tempo):
  `python3 -m unittest -v test_sampler_tap`
- `test_sampler_metronomo.py` — test del **metronomo** del sampler (passo fra i
  colpi, accenti, unità: 1/4 · 2/4 · 3/4 · battuta · 2 · 4 battute):
  `python3 -m unittest -v test_sampler_metronomo`
- `test_sampler_trim.py` — test del **trim giallo** del sampler (pulsante
  **✂ Trim giallo on/off**, gli elementi che spariscono, l'**onda grigia** col
  trim spento) e del **loop** (anticipo del ritorno per non sfondare il punto di
  OUT, URL assoluta per l'audio nel documento `blob:`): funzioni pure in
  JavaScriptCore, cablaggio e app viva:
  `python3 -m unittest -v test_sampler_trim`
- `fortissimo_compare_v3.py` — modello **Fortissimo Compare v3**: confronto tra
  due output `AudioAnalysis` (MIDI + one-shot), score [0,1]
- `fortissimo.html` — interfaccia di test del modello (pagina `/fortissimo`)
- `test_fortissimo_compare.py` — test del modello
  (`python3 -m unittest -v test_fortissimo_compare`)
- `test_download_fallback.py` — test del recupero dei download (solo file creati
  dal job, mai l'audio di un altro sample): `python3 -m unittest -v test_download_fallback`
- `test_verify_genius.py` — test del recupero crediti da Genius (tutti gli
  artisti, produttori, compositori): `python3 -m unittest -v test_verify_genius`
- `test_move_field.py` — test della **legenda 📖** e dello strumento **➡️ Sposta**
  del pannello SQL/script (funzione pura `move_field_value`: artista dal titolo
  agli artisti, anno dal titolo al campo anno, parola intera, parentesi rimaste
  vuote): `python3 -m unittest -v test_move_field`
- `test_search_field.py` — test della **ricerca del player** (pagina `/onyx`): su
  quale informazione cerca la barra «Cerca» (titolo, artista, album, artista
  dell'album, anno, genere, compositore, BPM, tonalità, commento, testo, nome file
  oppure *Tutto*), funzione pura `branoCorrisponde`:
  `python3 -m unittest -v test_search_field`
- `test_player_hero.py` — test delle **schede di artista e di album** (pagina
  `/onyx`, due GUI diverse: avatar tondo + chip degli album per l'artista, cover
  quadrata in stile vinile + numeri di traccia per l'album), funzioni pure
  `monogramma`, `tintaDa`, `durataEstesa`, `riassuntoArtista`, `riassuntoAlbum`:
  `python3 -m unittest -v test_player_hero`
- `test_nowbar_scroll.py` — test del clic sulla **barra in basso del player**
  (pagina `/onyx`): si apre la scheda dell'album o dell'artista E la lista
  scorre fino alla canzone in ascolto, che lampeggia; funzione pura
  `indiceBrano`: `python3 -m unittest -v test_nowbar_scroll`
- `test_sql_guard.py` — test del **pannello SQL/script** (cosa si può eseguire:
  solo SELECT/UPDATE; `replace(...)` ammesso come funzione, `REPLACE INTO`
  bloccato): `python3 -m unittest -v test_sql_guard`
- `scheda.html` — **scheda di una canzone** (pagina `/scheda`, pulsante **📄 Scheda**
  nella tabella del database): stem, remix e cover, campionamenti WhoSampled e
  analisi audio di quel brano (vedi la sezione *Scheda canzone* qui sotto)
- `test_scheda_canzone.py` — test della **scheda canzone**: classificazione di
  sample/remix/cover, funzioni pure della pagina in JavaScriptCore, mixer degli
  stem con un DOM finto, endpoint vero su un database di prova:
  `python3 -m unittest -v test_scheda_canzone`
- `midi_studio/` — **app separata (porta 5080)**: estrae MIDI da un audio e
  confronta due MIDI (vedi la sezione *MIDI Studio* qui sotto)
- `cookies.txt` — 🔒 versione **snellita**: solo i cookie anti-403 di YouTube
  (consenso + anti-bot), nessun dato di account Google, PayPal o altri siti.
  Sul Mac il file **completo** resta intatto (escluso dalla repo con
  `.gitignore` + `skip-worktree`) perché è quello che l'app usa davvero per
  i download senza errori 403. **Regola d'oro**: non caricare mai il file
  completo su GitHub — tanto meno ora che **la repo è pubblica** (dall'11/09/2026):
  quello che è in repo è visibile a chiunque, e la storia di git non si "pulisce"
  con un semplice commit.

## Cartelle escluse dal versionamento

- `downloads/` — audio scaricati (centinaia di GB)
- `stems/` — tracce separate generate
- `.trash/`, `.snapshots/`, `__pycache__/` — file temporanei

## Requisiti di sistema

- **ffmpeg** (`brew install ffmpeg`) per la conversione dei formati
- **Google Chrome** per lo scraping con `undetected_chromedriver`
- **librosa + numpy** opzionali ma consigliati per l'analisi audio

## Sampler (griglia FL-Studio) — pagina `/`

Il **sampler** è il trimmer in stile FL-Studio della pagina principale: forma
d'onda con la griglia sovrapposta, righello numerato per battute, metronomo, TAP,
offset, *Battute Sel.* / *Diventa Bar N°*, **Allinea griglia** e Undo/Redo. Si
apre su una canzone dal pulsante **🎛 Sampler** (tab 🗄️ Database), dalla voce
**🎛 Apri nel sampler** del menu del player, oppure dal link `/?sampler=<id>`
(anche `/?sampler_file=<nome file>`) — e arriva con il **BPM del database già
impostato**, così si vede e si sente subito se quel valore è quello vero.

Guida completa, controllo per controllo (con la matematica della griglia e i
numeri misurati): **[`README_sampler.md`](README_sampler.md)**.

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


## Scheda canzone (pagina `/scheda`) — tutto quello che il database sa di un brano

Nella tabella del **Database** (pagina `/`) ogni riga ha il pulsante **📄 Scheda**:
apre `/scheda?song=<id>`, una schermata dedicata a quella canzone con quattro
riquadri, riempiti **solo** con i dati del database.

| Riquadro | Cosa mostra | Da dove viene |
|---|---|---|
| ✂️ **Tracce di cui è composta** | gli stem (voce, batteria, basso, altro) con player, mute, volume e download; **▶ Suona tutti insieme** li fa partire sincronizzati, per sentire il brano ricomposto | `stem_sessions` + `stem_tracks`, più la cartella `stems/htdemucs/<nome>` se il job era partito senza `song_id` |
| ♻️ **Remix e cover** | i remix e le cover registrati, con il verso della relazione, più un blocco separato di **candidati** riconosciuti dal titolo | `sample_relations` (`category` VOCAL_COVER / FULL_REMAKE / INSTRUMENT_REMAKE, oppure «remix» in categoria/trasformazione/note) |
| 🎚 **Campionamenti (WhoSampled)** | cosa campiona questa canzone e chi campiona questa canzone, con gli intervalli e i link WhoSampled/YouTube | `sample_relations` (`derivative_song_id` = chi usa il sample, `source_song_id` = la fonte campionata) |
| 🧠 **Analisi audio** | BPM, tonalità e confidenza salvati per il brano | `audio_analyses` |

Dettagli che servono a fidarsi di quello che si vede:

- i file degli stem sono **controllati su disco**: se qualcuno li ha cancellati
  la riga dice «file mancante» invece di far cliccare su un player vuoto;
- la cartella degli stem cerca lo **stesso nome che usa l'app** per Demucs
  (`os.path.splitext(filename)[0]`, dentro `do_stems`): le tracce che non hanno
  una riga in `stem_tracks` compaiono lo stesso, marcate «solo su disco»;
- i **candidati** di remix/cover sono indizi (stesso titolo base + un marcatore
  «remix/cover/live…», oppure artista diverso): la pagina lo scrive a chiare
  lettere, non sono relazioni registrate;
- gli intervalli dei campionamenti sono mostrati **dal punto di vista di questa
  canzone** («questa canzone: 0:12 → 0:34 · l'altra: 0:02 → 0:25»);
- la pagina si aggiorna da sola quando cambia la firma di `/db/changed`, **ma non
  mentre gli stem suonano** (ricostruirebbe gli `<audio>` e la riproduzione si
  interromperebbe);
- dal riquadro degli stem, se è vuoto, si può lanciare la separazione
  (**✂️ Separa gli stem ora**): riusa `/separate` e segue il job con `/status/<id>`.

Endpoint usati dalla pagina:

| Endpoint | Metodo | Cosa fa |
|---|---|---|
| `/scheda` | GET | la pagina (si apre con `?song=<id>`) |
| `/db/songs/<song_id>/scheda` | GET | i dati della scheda (404 se la canzone non esiste) |

Test: `test_scheda_canzone.py` (38 test) — funzioni pure Python
(`classifica_relazione`, `titolo_base`, `possibili_varianti`…), funzioni pure
della pagina **eseguite davvero** in JavaScriptCore, il **mixer con un DOM
finto** (sync, mute, volume, stop), il cablaggio (pulsante in tabella, sezioni,
handler esposti su `window`) e l'endpoint vero su un **database di prova** (stem
con file mancanti, una relazione per gruppo, analisi, candidati) senza toccare la
libreria: `python3 -m unittest -v test_scheda_canzone`.

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

## Note operative e stato corrente (11/09/2026, aggiornate al 18/09/2026)

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
- **REPO PUBBLICA (11/09/2026).** `https://github.com/Alessandro1040/samplelab`
  è stata resa **pubblica** (`gh repo edit --visibility public`), branch `main`
  allineato. Sono quindi visibili a chiunque: tutto il codice, la pagina
  `midi_studio/alg/` (algoritmo puro + prompt), i file legacy, `cookies.txt`
  **snellito** (9 cookie anonimi di YouTube: `YSC`, `VISITOR_INFO1_LIVE`,
  `SOCS`, `PREF`, `GPS`, `__Secure-ROLLOUT_TOKEN` — **nessun** cookie di account)
  e `samplelab (2).db` con la libreria (titoli/artisti/nomi file, ~890 brani).
  Verificato: il file **completo** dei cookie non è mai stato committato (nella
  storia c'è un solo blob da 566 byte) e nel codice non ci sono segreti.
  Per tornare privati: `gh repo edit Alessandro1040/samplelab --visibility private`
  (ma chi ha già clonato/forkato conserva la copia).
- **ALGORITMO IN FILE PURO (11/09/2026).** `midi_studio/alg/fortissimo_alg.js` è
  l'algoritmo dell'estrattore estratto verbatim (19 funzioni identiche, nessun
  DOM) con ingresso unico `analizza(audio, opts)`; si rigenera da
  `extractor.html` con `midi_studio/alg/estrai_alg.py` (idempotente). Banco di
  prova su **http://localhost:5080/alg**. Attenzione: la pagina
  `extractor.html` ha ancora una **copia propria** delle stesse funzioni, quindi
  una modifica al file puro non cambia la pagina finché non si allinea.
- **AUDIO SBAGLIATO NEI SAMPLE — CORRETTO (16/09/2026).** Cercando *Till I
  Collapse* di Eminem il sample **"Sam Is Dead"** compariva correttamente in
  elenco, ma il player riproduceva l'audio di **"Mosh"** (un altro sample dello
  stesso gruppo), e lo stesso file sbagliato si ripeteva su più card. Causa: in
  `_do_download` il fallback, quando un download non produceva file, restituiva
  *l'ultimo file di `downloads/` modificato negli ultimi 60 secondi*; con i
  sample scaricati in parallelo (2 alla volta, `DL_SEM`) era il file di un ALTRO
  job. (Il video di "Sam Is Dead" è davvero non scaricabile: yt-dlp risponde
  `Please sign in`, è un brano con restrizioni.) Fix in `app (2).py`:
  1. `_downloads_snapshot()` + `_pick_job_file()`: si consegnano solo file
     creati **da quel job** e, se la pagina manda `expected_title`, il nome deve
     contenerlo; se non c'è nulla il job va in **errore** — mai l'audio altrui
     (il messaggio in pagina è "Download non riuscito: nessun file audio per
     '…' (audio NON sostituito)");
  2. recupero mirato: se il video di partenza non è scaricabile e si conoscono
     titolo/artista, si cerca un **altro video dello stesso brano** (ranking
     titolo/artista, soglia 0.55) e si scarica quello;
  3. le query `/stream/<file>` (es. conversione m4a→mp3 dall'editor) non passano
     più dalla ricerca YouTube: sono file locali, convertiti con ffmpeg;
  4. `_rank_yt_entries`: penalità per i video < 60 s e, a parità di titolo/score,
     vince la versione **più lunga** — senza questo, fra i due "match esatti" di
     *Sam Is Dead* poteva uscire una clip di 30 s invece del brano da 170 s.
  La pagina (`index (2).html`) manda ora `expected_title` a `/download` dai 4
  punti che lo chiamano (player principale, editor sample, download completo,
  tab database). Verifiche del 16/09/2026: `python3 -m unittest -v
  test_download_fallback` (22 test, aggiornati in serata) e prova end-to-end — URL inesistente → job
  **in errore senza file** (prima restituiva `Mosh.mp3`), "Sam Is Dead" →
  `Sam (Is Dead).mp3` (170 s, recupero del brano completo; con il vecchio
  ranking usciva `sam is dead.mp3`, una clip di 30 s), `/stream/Mosh.mp3` +
  formato wav → `Mosh.wav`.
- **TIMESTAMP DEL SAMPLE FUORI DALL'AUDIO — CORRETTO (16/09/2026, sera).** Con
  l'audio giusto ma più corto del previsto la card mostrava
  `IN 3:36 → OUT 2:50 | durata: -1:-46 | sample: +0.00s`: il timestamp del sample
  (216 s = 3:36) cade **oltre la fine** dell'audio scaricato (170 s = 2:50), e
  `fmtTime` su una differenza negativa stampa `-1:-46` (in JavaScript `%`
  conserva il segno). Causa: `wirePlayerEvents` faceva
  `trimStart=startSec` e `trimEnd=min(startSec+30, durata)` senza controllare che
  il timestamp esistesse nel file. Fix:
  1. `index (2).html`: nuova funzione pura **`trimRangeFor(startSec, durata,
     finestra)`**, usata da `wirePlayerEvents` (loadedmetadata) e da
     `resetTrimStart`: IN/OUT restano sempre dentro `[0, durata]` con finestra
     > 0 (caso 216 s su file di 170 s → **IN 2:20, OUT 2:50, durata 30 s**) e
     quando il timestamp non esiste nel file compare in rosso
     *"⚠ il sample a 3:36 non c'è in questo audio (durata 2:50): file più corto
     del previsto — serve una versione completa"* (span `tt-warn-*`, sia nel
     player principale sia in `buildPlayerHTML`). Verificata **in esecuzione
     reale** con JavaScriptCore (`osascript -l JavaScript`) su 7 casi limite
     (216/170, 600/170, 170/170, 216/216, 10/5, 0/300, 30/300): tutti con
     `start < end` dentro la durata.
  2. `app (2).py`: la pagina manda ora anche **`min_duration`** (il secondo in
     cui serve il sample) e **`expected_artist`** (prima mandava solo il titolo);
     se il video indicato non è scaricabile il recupero preferisce un video che
     CONTENGA quel secondo, ma **solo con l'artista noto e solo se l'artista
     compare nel titolo/canale** — senza questo ancoraggio usciva un omonimo
     sbagliato (*"Sam Is Dead | Ghost (1990)"*, un video sul film).
  Verifiche: job reale su `nojZbdeHPCk` (video con "Please sign in") con
  `expected_title` + `expected_artist` + `min_duration=216` → scelto
  `Tyler The Creator And Domo Genesis - Sam Is Dead` (**400 s**, contiene 3:36);
  senza artista → resta la versione corta `Sam (Is Dead)` (170 s) con l'avviso
  in pagina e **nessun errore**; `python3 -m unittest -v test_download_fallback
  test_fortissimo_compare` → **44 test OK**. Nota: durante la verifica è emerso
  anche un `NameError` (`ea` non definito in `yt_search_first`, introdotto in
  questo stesso fix) → corretto subito e ricontrollato con il job reale.
- **DUE COVER CON LO STESSO TITOLO DAVANO LO STESSO AUDIO — CORRETTO
  (16/09/2026, sera).** Nella sezione *cover* di *'Till I Collapse* le card
  **"8-Bit Misfits"** e **"Twinkle Twinkle Little Rock Star"** riproducevano lo
  stesso file. Causa: i due video YouTube si chiamano **entrambi**
  `'Till I Collapse` (303 s e 334 s) e il download singolo scriveva su
  `%(title)s.%(ext)s`: un solo file per due video, e il secondo job lo riusava
  (yt-dlp non riscarica un file già presente) → la seconda card suonava l'audio
  della prima. Fix: il nome del download singolo usa ora **`DL_OUTTMPL =
  "%(title)s [%(id)s].%(ext)s"`** (l'`[id]` del video rende il nome unico; è lo
  stesso schema che il download playlist usava già) e `clean_filename()` toglie
  un `[ID YouTube]` di 11 caratteri in coda, così `/db/add_local` continua a
  ricavare artista/titolo puliti (es. `Eminem - Song [Pi3_Zs-oRUo].mp3` →
  *Eminem - Song*) senza toccare titoli tipo `[Remix Version]`.
  Verifiche del 16/09/2026: riproduzione del bug (prima entrambe le cover
  restituivano `'Till I Collapse.mp3`, 303 s) e fix verificato con lo stesso job
  reale → `'Till I Collapse [1l_SO4Ndd6o].mp3` (303,0 s) e
  `'Till I Collapse [ZczdMEIW2rM].mp3` (333,7 s), **2 file distinti su 2**.
  ⚠️ Nota: i file scaricati **prima** di questo fix restano con il vecchio nome
  (senza `[id]`) e vanno considerati "di una cover sola": i nuovi download
  creano file nuovi col nome completo, quindi in `downloads/` possono convivere
  il vecchio e il nuovo nome dello stesso brano.
- **ARTISTI E PRODUTTORI DA GENIUS — COMPLETATI (16/09/2026).** Premendo
  *Verifica* su un brano (es. *Apex* di Chris Webby) il database registrava solo
  l'**artista principale** e spesso **nessun produttore**. Due cause:
  1. il campo `artist` veniva riempito con `genius["artist"]` (solo il primary) e
     **solo se `artist_verified` era 0**, quindi una riga già verificata non si
     completava mai più;
  2. i produttori arrivano solo dall'API della singola canzone
     (`/api/songs/<id>`), che a volte risponde vuoto o 429 e **non veniva
     ritentata** (misurato: 7 brani verificati su 54 senza produttori e 5 senza
     compositori).
  Fix in `app (2).py`:
  1. `fetch_genius` restituisce anche **`artists`** (primary + feat., senza
     duplicati e nell'ordine di Genius), ritenta una volta l'API della canzone e
     pulisce i nomi con `_unique_names`;
  2. la verifica scrive in `artist` **tutti** i crediti separati da `" / "` (il
     formato del resto della libreria) e **completa** `producers` e `composer`
     quando manca qualche nome, senza duplicare né cancellare ciò che c'è
     (`_credits_missing`): rifare la verifica su una riga vecchia la completa;
  3. le ricerche successive (YouTube/WhoSampled/Tunebat) usano il **solo artista
     principale**, non l'elenco completo dei crediti.
  Verifiche del 16/09/2026: `/genius` su *Apex* → 6 artisti (Chris Webby / Ren
  Thomas / Mickey Factz / ANoyd / Apathy / NEMS), produttori `["Nox Beatz",
  "C-Lance"]`, 6 compositori; *Verifica* reale su quella riga → messaggio
  `🎤 Artisti completati da Genius: Chris Webby / Ren Thomas / Mickey Factz /
  ANoyd / Apathy / NEMS` (mancava ANoyd) e riga aggiornata in DB; backfill sulle
  righe già verificate → **7→5 senza produttori e 5→3 senza compositori** (le
  altre non hanno crediti su Genius, e una è stata saltata perché il suo URL
  Genius punta a una pagina di traduzione). Test nuovo
  `test_verify_genius.py` (6 puri + 2 di rete):
  `python3 -m unittest -v test_verify_genius`.
  ⚠️ Da sapere: la verifica ora **riscrive** `artist`/`producers`/`composer` con
  i dati di Genius quando trova nomi mancanti — le modifiche manuali a questi
  tre campi possono quindi essere sovrascritte rifacendo la verifica.
- **GLI ARTISTI COMPLETI NON COMPARIVANO NEL PLAYER — CORRETTO (16/09/2026,
  sera).** Dopo la verifica il *database* aveva tutti i crediti, ma aprendo il
  modale info del player (quello con i `🔗 Genius` / `🔗 WhoSampled`) si vedeva
  ancora **solo "Chris Webby"**. Due cause:
  1. il player tiene una **copia propria** dei brani (IndexedDB) e il modale
     leggeva da lì, non dal database; salvando il form, il valore vecchio veniva
     anche riscritto nel DB;
  2. il "smart parsing" del player (`fetchGeniusMetadata`) interrogava Genius con
     **il solo titolo** e salvava **solo `primary_artist`**, cancellando i
     featuring dall'artista.
  Fix:
  1. `onyx_whosampled.html` — `openEditTrackModal` scarica la riga aggiornata da
     `/db/songs/<id>` e mostra anche **🎛 Produttori** e **✍️ Compositore**
     (prima solo i due link), allineando la copia locale **senza** riscrivere il
     database (niente più salvataggi di valori vecchi);
  2. `fetchGeniusMetadata` usa l'endpoint **locale `/genius`** (stessa origine)
     e scrive **tutti** gli artisti + compositore; l'artista passato è quello
     del brano, svuotato se è un segnaposto (`artistForGenius`);
  3. `fetch_genius` (backend): quando si cerca **col solo titolo** (artista
     vuoto o segnaposto) si accetta solo un **titolo (quasi) identico** —
     `match_score` dà 1.0 all'artista vuoto (`""` è contenuto in qualsiasi
     nome), quindi la soglia da sola non bastava: *Apex* senza artista matchava
     **"Apex Predator"** del musical *Mean Girls* (credits di un'altra canzone
     nel database).
  Verifiche del 16/09/2026: `/genius` senza artista + "Apex" → **nessun match**;
  con "Chris Webby" → 6 artisti + produttori `["Nox Beatz","C-Lance"]`; con il
  solo titolo *"Apex Predator"* → la canzone giusta; le due funzioni JS
  (`artistForGenius`, `producersText`) testate **in esecuzione reale** con
  JavaScriptCore (8/8) e **tutti i blocchi `<script>`** delle due pagine
  compilati senza errori (6/6, `new Function`); verifica reale su *Apex* →
  artista completo in DB e nel player dopo il refresh; 56 test OK.
  ⚠️ Ricaricare la pagina (Cmd+Shift+R) per prendere il JS nuovo.

- **APRI NEL SAMPLER — CONTROLLO DEL BPM VERO (17/09/2026).** In ogni canzone,
  nel tab 🗄️ Database e nel player, c'è ora **🎛 Sampler / "🎛 Apri nel sampler"**:
  apre il brano nel **sampler FL-Studio** (quello che era "Player standalone":
  griglia, metronomo, TAP, Moltiplica, Segui) con il **BPM del database già
  dentro la casella**, così si vede e si sente subito se il brano ci sta sopra o
  se il BPM salvato è sbagliato e va corretto.
  - `index (2).html`: nuova `openInSampler(songIdOFile)` — risolve la riga per id
    (`song_…`) o per nome del file locale, apre il modale `#audio-editor-modal`
    con `openAudioEditor(url, label, startSec, bpm)` (che ora accetta `startSec` e
    `bpm` e li passa all'editor nel messaggio `load`) e mostra un toast col BPM
    salvato (`BPM nel database: … (controlla con griglia/TAP)`, oppure "nessun BPM
    nel database: misuralo con TAP"); il template dell'editor applica il BPM
    ricevuto (`setBpm('main', …)`). Il pulsante 🎛 Sampler è nella cella azioni di
    ogni riga **con file locale** (per i brani senza file resta il link YouTube);
    le novità `startSec`/`bpm` non rompono i chiamanti esistenti.
  - `onyx_whosampled.html`: voce **"🎛 Apri nel sampler"** nel menu della canzone
    (⋮ o tasto destro). Dentro SampleLab (iframe) chiede alla pagina padre di
    aprire il sampler nella stessa finestra (messaggio `openSampler`); con `/onyx`
    aperto da solo apre una nuova scheda su `/?sampler=<id>` e, se il brano non è
    nel database, su `/?sampler_file=<nome file>` (`samplerUrlFor`).
  - Deep link: la pagina principale accetta ora **`?sampler=<id>`** e
    **`?sampler_file=<file>`** (oltre a `?tab=…`), per aprire il sampler da un
    bookmark o dal player standalone.
  - Verifiche del 17/09/2026: prova **reale in Chrome pilotato da Selenium** (8/8) —
    la riga del DB ha il pulsante (`▶ ⏹ 🎧 ✂️ Stem ✏️ Edit 🎛 Sampler 🔎 Verifica ✕`),
    il click apre il modale col titolo giusto e, entrando nell'iframe, l'editor ha
    **`players.main.bpm = 60.1` e la casella 60.1** (*60 Hz II* di DJ Shocca, BPM
    nel DB 60.1), come col link diretto; nel player la voce è presente nel menu.
    Percorso `?sampler_file=…` provato a parte (modale + BPM 60.1): OK. Dump DOM
    reale di `/?tab=database`: **890 righe e 890 pulsanti 🎛 Sampler**. Test in
    esecuzione reale con JavaScriptCore: 23/23 su `openInSampler`/`openAudioEditor`/
    `samplerUrlFor`/`dbSongIdFor` (BPM passato all'editor, messaggio al parent,
    nuova scheda, casi d'errore) e 5/5 sul template della riga del DB (pulsante
    presente solo con file locale); **8/8 blocchi `<script>`** delle due pagine
    (template dell'editor incluso) compilati senza errori.
  - Nota: il BPM serve solo da punto di partenza — il sampler **non** lo riscrive
    nel database: per salvarlo si usa *✏️ Edit* (o *Verifica*) sulla riga.

- **`/metadata` (BPM/Tonalità) ANDAVA IN 500 — CORRETTO (17/09/2026).** Il log
  dell'app mostrava `AttributeError: 'NoneType' object has no attribute 'lower'`
  su `/metadata`: `get_or_create_song_db` confronta i titoli/artisti con
  `n(s) = re.sub(...).lower()` e in libreria ci sono **3 righe con `title` NULL**
  (due storiche + una creata oggi rinominando male un brano) → `None.lower()`.
  Non era un caso limite: la funzione viene chiamata **solo quando BPM/tonalità
  vengono trovati**, quindi il 500 arrivava proprio quando c'era qualcosa da
  salvare — e la stessa `get_or_create_song_db` è usata da `/db/from_onyx` e
  `/db/add_local`. Fix in `app (2).py`: `n()` regge i NULL
  (`str(s or "").lower()`), con commento sul perché.
  Verifiche del 17/09/2026: riproduzione **prima del fix** su una **copia** del DB
  reale → 3 casi su 3 in `AttributeError` (inserimento nuovo brano, match su riga
  esistente, brano senza artista); dopo il fix → 3/3 OK. Endpoint: `POST /metadata`
  su *Uncommon Valor: A Vietnam Story* (riga con bpm NULL, quindi niente cache) →
  **HTTP 200** con `{"bpm": 61.5, "key": "G Minor", "source": "ffmpeg"}` e valori
  scritti in DB; `bpm`/`musical_key`/`updated_at` rimessi com'erano dopo la prova;
  log dell'app senza traceback; **22 + 26 + 8 test** delle suite esistenti OK.
  ⚠️ Le righe con `title` NULL restano (dati da decidere): il codice ora non ci
  sbatte più, ma la riga di *Apex* va rinominata (vedi **🎛 Sampler** o *✏️ Edit*).

- **PULSANTE DELLA GRIGLIA: ETICHETTA DI STATO (17/09/2026).** Il pulsante diceva
  **"Visualizza griglia"** quando la griglia era *già accesa* e **"Nascondi
  griglia"** quando era *spenta*: due nomi invertiti rispetto a quello che fa il
  clic (segnalato da Alessandro). Ora dice lo **stato** — **`Griglia on`** /
  **`Griglia off`** — è evidenziato quando è accesa e il tooltip dice cosa farà il
  clic («Griglia accesa — clic per spegnerla» / «Griglia spenta — clic per
  accenderla»). Stessa etichetta anche nel player delle card dei sample.
  Verificato in Chrome (14/14): stato iniziale `Griglia on` con la griglia
  disegnata (**85 linee**), un clic → `Griglia off` e **0 linee** sull'onda
  (griglia davvero nascosta), secondo clic → di nuovo `Griglia on` con 85 linee,
  tooltip e classe `active` coerenti in tutti i casi.
- **METRONOMO CON UNITÀ SUA (17/09/2026).** Il metronomo del sampler non segue più
  la griglia: ha una **tendina dedicata** con **ogni 1/4** (predefinito), `ogni 2/4`,
  `ogni 3/4`, `ogni battuta`, `ogni 2 battute`, `ogni 4 battute`. Prima seguiva la
  suddivisione della griglia, quindi per sentire i quarti si doveva mettere la
  griglia a `1/4 bar` — cambiando anche linee e snap. Lo stato in basso dice cosa
  stai sentendo (`🔊 1/4`), il primo colpo di ogni battuta resta più acuto
  (1000 Hz) e i colpi sono **contati davvero** nelle prove: a 120 BPM in due
  battute escono **8 colpi** con `ogni 1/4`, 4 con `2/4`, 2 con `ogni battuta`,
  1 con `ogni 2 battute`, con la griglia **ferma a 1 battuta**. La matematica è in
  funzioni pure (`stepMetronomo`, `accentoBattuta`, `etichettaUnita`) con test
  committato `test_sampler_metronomo.py`: **8/8** in JavaScriptCore e **15/15** in
  Chrome (colpi reali intercettando `playMetronomeClick`, stato `🔊 1/4`).
- **TAP PIÙ PRECISO (17/09/2026).** Nel sampler il pulsante **🎵 TAP** ora ricava
  il BPM dalla **media di tutti i colpi della sessione** (prima teneva solo gli
  ultimi 8) e lo salva con **un decimale** invece di arrotondarlo all'intero: più
  colpi batti, più la stima converge (12 colpi a 0,5 s → **120,00**; 5 colpi a
  320 ms → **187,6**). Il pulsante mostra su quanti colpi sta mediando
  (`🎵 TAP ×12`); un tocco fuori tempo (< 0,2 s o > 2 s, cioè fuori dai 30–300
  BPM), un **Undo/Redo** o un BPM scritto a mano **fanno ripartire la sessione**.
  La matematica è in una funzione pura (`bpmDaTap`), quindi testabile — test
  committato `test_sampler_tap.py` (`python3 -m unittest -v test_sampler_tap`,
  6 test) — e verificata il 17/09/2026: **11/11** controlli in JavaScriptCore e
  **9/9** in Chrome con **clic reali** sul pulsante (contatore `🎵 TAP ×12`, BPM
  120,00 con 12 colpi, 187,60 con 5 colpi, riavvio dopo un tocco fuori tempo,
  sessione azzerata scrivendo 114,8 a mano); **6/6 blocchi `<script>`** compilati.
  Dettagli e tutti i numeri misurati in [`README_sampler.md`](README_sampler.md)
  (§5.5).

- **TITOLI ROVINATI DALLA SOSTITUZIONE "TOGLI EMINEM" — RIPARATI (17/09/2026).**
  Una sostituzione fatta sulla colonna `title` (intento: "Eminem sta nell'artista,
  non nel titolo") aveva lasciato **26 titoli mutilati + la riga di *Apex* col
  titolo vuoto**:
  - **12 con la parentesi aperta** — `Rock City (feat.`, `We Shine (Feat.`,
    `Rush Ya Clique (feat.`, `Here Comes the Weekend (feat.`, `Watch Deez (feat.`,
    `Symphony In H (feat.`, `Homicide (feat.`, `Macosa (feat.`, `Fuck Off (feat.`,
    `Turn Me Loose (feat.`, `Flawless Victory (feat.`, `Don't Aproach Me (feat.`;
  - **5 con il separatore orfano** — `My Name (feat.& Nate Dogg)`,
    `You Hear Me (feat.& Pauly Yams)`, `Remember The Name (feat.& 50 Cent)`,
    `You Must Be Crazy (feat., Hot Karl & Dree)`,
    `… (Funkmaster Flex & Big Kap Feat.and Dr. Dre)`;
  - **9 con parole spezzate o frammenti appesi** — `Eminems Freestyle…` →
    `s Freestyle That Got Him…`, `Airplanes part II (Eminem Solo)` →
    `Airplanes part IISolo)`, `The Warning -(Music & Lyrics)`,
    `“Toy Soldier Remix”(1)`, `50 Cent - Patiently Waiting ft.(Tradução…)`,
    `Busta Rhymes Feat- I'll Hurt You`, `ft. Nate Dogg Til I Collapse…`,
    `- Lose Yourself`, `- I Do Pop Pills [Freestyle Friday]`.
  Riparazione con una **mappa esplicita id → titolo** (nessuna sostituzione
  automatica), applicata via `PUT /db/songs/<id>` — cioè come si farebbe a mano
  dalla pagina: i 12 titoli con il solo Eminem diventano il nome del brano, i 5
  con altri featuring li mantengono (`My Name (feat. Nate Dogg)`), i frammenti
  ricomposti (`Lose Yourself`, `Airplanes, Part II`, `Busta Rhymes - I'll Hurt
  You`…). Su *Apex* (`song_7310cfc5145c`) sono stati rimessi titolo, artista,
  produttori e compositore verificati il 16/09 (`Chris Webby / Ren Thomas /
  Mickey Factz / ANoyd / Apathy / NEMS`, `["Nox Beatz", "C-Lance"]`). Su
  *Lose Yourself* è stato azzerato `title_verified`: la verifica precedente era
  stata fatta su un altro testo. Backup prima dell'intervento:
  `/tmp/samplelab_pre_riparazione_2023.db`.
  Verifiche del 17/09/2026: 27 righe aggiornate, **tutte HTTP 200** e
  **0 artefatti rimasti** (ricontrollo automatico sui pattern dei difetti); in
  Chrome (Selenium) la ricerca `apex` ritrova **1 riga** con titolo `Apex`,
  crediti completi e il 🎛 Sampler che si apre su di essa, e la riga riparata
  mostra `Rush Ya Clique`; log dell'app senza errori.
  ⚠️ I brani **senza** Eminem e con altri featuring sono rimasti come erano
  (es. `Murder, Murder Lyrics (HD)`): la riparazione ha toccato solo i danni.
  🛡️ **Prevenzione:** lo script di esempio nel pannello «Script personalizzato»
  era proprio quello che aveva fatto il danno (`re.sub(r'\s*Eminem\s*', '', …)`,
  senza confine di parola: `Eminems` → `s`, `(feat. Eminem)` → `(feat.`). Ora
  l'esempio è **di sola lettura** (mostra le righe col nome nel titolo e non
  modifica niente) e ricordava le due regole per una `UPDATE` sicura: usare
  `r'\bEminem\b'` e ripulire le parentesi rimaste vuote. (Più tardi lo stesso
  giorno quel pulsante «📋 Script Eminem» **non c'è più**: al suo posto lo
  strumento generico **➡️ Sposta**, annullabile — vedi l'ultima nota.)
  Verificato provando le
  regex dell'esempio sui titoli che erano stati rovinati: la versione vecchia li
  rompe (`Eminems…` → `s Freestyle…`, `Rock City (feat. Eminem)` → `Rock City
  (feat.)`), mentre un esempio "sicuro" che togliesse comunque Eminem ne
  creerebbe di nuovi (`You Hear Me (feat. Eminem & Pauly Yams)` → `You Hear Me &
  Pauly Yams)`) — ed è il motivo per cui l'esempio non modifica più nulla.

- **ANNO VUOTO E ALBUM «Mus» — CORRETTI (17/09/2026).** Premendo *Verifica* su un
  brano compariva la data di Genius ("September 2, 2025") ma **non l'anno**, e
  l'album restava **"Mus"**. Erano tre difetti distinti:
  1. **L'anno non veniva ricavato dalla data.** Genius dà solo `release_date`
     come testo: la Verifica salvava la data e lasciava `year` vuoto (13 righe in
     libreria). Ora `_year_from_date()` in `app (2).py` ricava l'anno da qualunque
     formato ("September 2, 2025" → 2025, "2002-10-28" → 2002) e la Verifica lo
     scrive, dicendolo in interfaccia.
  2. **Un album falso bloccava quello vero.** La Verifica completava l'album
     *solo se vuoto*: con "Mus" dentro, il nome di Genius non entrava mai. Ora
     `_album_segnaposto()` riconosce i valori che non sono album (Mus/Music/
     Album sconosciuto/Unknown…) e in quel caso la Verifica scrive quello di
     Genius — senza toccare gli album veri, anche se corti ("2001", "BV3").
  3. **Da dove venivano "Mus" e il «Genius non ha trovato».** Nel player il
     caricamento per **cartella** usava il nome della cartella come album
     (`album = parts[parts.length - 2]`) → **168 righe con album "Mus"**; e la
     ricerca Genius includeva l'artista **anche quando è il segnaposto "Brano
     locale"** (query «Brano locale The Sauce…» → **zero risultati**), che è il
     motivo per cui sui brani locali la Verifica non trovava né album né data.
     Fix: `albumDaCartella()` / `albumPerDb()` in `onyx_whosampled.html` (i nomi
     generici di cartella e l'etichetta "Album sconosciuto" non entrano più nel
     database) e in `fetch_genius()` l'artista segnaposto non entra più nella
     query.
  4. **Col solo titolo si rischiava l'omonimo.** Togliendo l'artista dalla query
     tornavano risultati… anche sbagliati: 'Cha-Ching' della libreria prendeva
     l'album di *Unique Salonga* ("Cha-Ching!", score 0.87). Misurato con la
     search API: quel titolo è condiviso da **2 artisti** ('Apex Predator' da
     **3**). Ora, quando l'artista manca, si accetta il risultato solo se il
     titolo è **univoco** oppure se l'artista di Genius è **riconoscibile nel
     titolo** (direttamente o come artista noto della libreria,
     `known_artist_in_title`): meglio nessun dato che i credits di un omonimo.
  Verifiche del 17/09/2026: *Verifica* reale su **The Apple** (Eminem) → `year`
  da `None` a **2011** e album da `Mus` a **King Mathers**, con i messaggi
  «Anno ricavato dalla data (December 18, 2011): 2011» e «Album da Genius: King
  Mathers»; in Chrome la riga del database e il modale ✏️ Edit mostrano anno
  `2011` + album `King Mathers` (7/7 controlli Selenium); 12/12 controlli in
  JavaScriptCore sulle funzioni dell'album; **6/6 blocchi `<script>`** delle due
  pagine compilati; **17 + 26 + 22 test** OK (i test nuovi su anno/album/omonimo
  sono in `test_verify_genius.py`) e 7/7 casi reali su `/genius` (Cha-Ching e
  Apex Predator scartati, *The Sauce* → Eminem perché titolo univoco, artisti
  veri invariati). Backfill delle righe già in libreria: **25 anni**
  sistemati (13 ricavati dalle date già presenti, gli altri 12 arrivati con le
  date nuove) e **18 album** completati con **guardie strette** (artista
  compatibile, oppure stesso URL Genius già salvato: es. *Bounce* → *There Goes
  the Neighborhood*, *Pyro* e *In My Baggie* → *88 Milligrams*, *5 AM* → *MM,
  Vol. 1*); le altre **151** righe (149 con `Mus` + 2 vuote) restano col
  segnaposto perché su Genius non hanno una pagina — 46 di queste hanno anche un
  artista segnaposto, quindi non c'è nemmeno un nome su cui cercare.
  ⚠️ Lezione: una prima passata più permissiva (col solo titolo) aveva preso
  l'album di un **omonimo** ("Cha-Ching" → album di *Unique Salonga*): è stata
  **annullata** dal backup (`/tmp/samplelab_pre_backfill_2114.db`) prima di
  rifarla con le guardie. Meglio un segnaposto che l'album di un'altra canzone.

- **PANNELLO SQL/SCRIPT: LEGENDA 📖 E STRUMENTO ➡️ SPOSTA (17/09/2026, sera).**
  Richiesta di Alessandro: «all'inizio della sezione dai una legenda con tutte le
  tabelle e i nomi delle cose che possiamo usare; togli anche il pulsante *Script
  Eminem* e piuttosto rendilo generico — l'utente scrive da dove spostare cosa,
  dove spostarla e cosa spostare (es. prendere una parola dal titolo, tipo
  l'anno, e spostarla in anno)». Fatto:
  1. **📖 Legenda** in cima al pannello (a comparsa): `GET /db/schema` legge il
     database **vero** (`sqlite_master` + `PRAGMA table_info`) e la pagina mostra
     le **6 tabelle** con il numero di righe e **tutte le colonne** — per `songs`
     (35 campi) ognuna con la sua descrizione in italiano («artist: artisti
     separati da ' / '», «producers: produttori in JSON», «title_verified: 1 =
     titolo confermato»). La legenda dice anche cosa si può usare nel pannello:
     in SQL solo `SELECT`/`UPDATE` (vietate DROP/ALTER/CREATE/DELETE/INSERT/
     TRUNCATE/REPLACE) e nello script Python `conn`, `db_path`, `re`, `time`,
     `json`, `sqlite3`, `os`, `math`, `hashlib` più le funzioni di base, con
     timeout 30 s. Le due liste sono **costanti del backend** (`SQL_ALLOWED`,
     `SQL_FORBIDDEN`, `SCRIPT_GLOBALS`, `SCRIPT_TIMEOUT`), usate anche da
     `/db/execute`: legenda e controlli non possono divergere.
  2. **➡️ Sposta** sostituisce il pulsante «📋 Script Eminem» (rimosso): si sceglie
     **da** quale campo, **a** quale campo, **cosa** spostare (es. `Eminem`,
     oppure `1999`), se **aggiungere** con ` / ` o **sostituire**, con due
     opzioni («solo parola intera», «pulisci parentesi vuote»). Endpoint nuovo
     `POST /db/move_field` con **anteprima** (`dry_run: true` → non scrive
     nulla), conferma in pagina con l'elenco delle righe e **↩️ Undo** (snapshot
     prima/dopo). I menu «Da»/«a» si riempiono da `/db/schema`, quindi i campi
     disponibili sono sempre quelli che il backend accetta.
  3. **✏️ Rinomina in massa ora è annullabile**: era l'unico strumento in blocco
     senza snapshot. Non è teoria: il 17/09 alle 20:23 una sostituzione
     `50 Cent` → `51 Cent` aveva toccato **35 righe** e l'unico modo per tornare
     indietro era scrivere l'`UPDATE` inverso a mano (i valori sono stati
     ripristinati alle 20:23:43; nel database di lavoro resta solo l'`updated_at`
     nuovo su quelle righe). Ora salva lo snapshot prima/dopo come `/db/execute`.
  4. La **matematica del testo** è in funzioni pure (`move_field_value`,
     `_pulisci_dopo_rimozione`): sposta senza duplicare (se il nome è già nel
     campo destinazione non lo aggiunge due volte), **non svuota** un titolo che
     era solo quel nome, su campi numerici accetta **solo cifre** e non
     sovrascrive un anno già presente (riga **saltata**, non rovinata), e
     ripulisce i resti (`(feat. )` → via, `… Chino XL & )` → `… Chino XL)`).
  Verifiche del 17/09/2026: **25 test** in `test_move_field.py`
  (`python3 -m unittest -v test_move_field`) e nessuna regressione nelle altre
  suite (**6 + 8 + 17 + 26 + 22** test OK); il ciclo completo scrittura + ↩️ Undo
  è stato provato su una **copia isolata** di app+DB (porta 5075: il database
  vero non è stato toccato) → **10/10**, compresa la riproduzione dell'incidente
  (`50 Cent` → `51 Cent`, 35 righe) e l'Undo che riporta la libreria **identica**
  (md5 della lista `id|artist` uguale a prima); in **Chrome** (Selenium) **22/22**:
  legenda popolata (3.545 caratteri con `890 righe`, `artist`, `SELECT`, `conn`,
  `PK`), menu «Da»/«a» con 11 campi e destinazione predefinita *Artista*,
  anteprima in pagina (`👁 Anteprima — 2 righe cambierebbero (niente è stato
  scritto)`) col titolo nel database **intatto**, pulsante Eminem **rimosso**,
  **0 errori JavaScript** in console.
  Due bug trovati proprio dalle verifiche e corretti: (a) con «solo parola
  intera» attivo, un testo che compare solo *dentro* un'altra parola (`Ever` in
  `Forever`) veniva **aggiunto** alla destinazione senza essere tolto dal titolo
  (ora la riga si salta — l'ha scoperto il test); (b) col deep link
  `/?tab=database` la console dava `Cannot access 'dbSchemaCache' before
  initialization` (le dichiarazioni `let`/`const` sono state spostate in cima
  allo `<script>`).
  Nota: i titoli con «(feat. …)» in libreria sono **124**: buona parte si sistema
  da qui in 3 clic (da *Titolo* a *Artista*, testo = il nome, «solo parola
  intera» attivo).
- **RICERCA DEL PLAYER: SI SCEGLIE SU COSA CERCARE (17/09/2026, notte).**
  Richiesta di Alessandro: «nella barra cerca nel player, l'utente dovrebbe poter
  scegliere tra cercare un titolo, un artista, un album o un anno o altre
  informazioni». Prima la barra «Cerca» (pagina `/onyx`, tab 🎧 Player) filtrava
  soltanto `name`+`artist`. Ora accanto alla barra c'è la tendina **cerco in…**
  (`#searchField`) con 13 voci: *Tutto* (predefinita), Titolo, Artista, Album,
  Artista album, Anno, Genere, Compositore, BPM, Tonalità, Commento, Testo, Nome
  file. Le opzioni **non** sono scritte nell'HTML: le costruisce
  `initSearchFieldUI()` dalla costante `SEARCH_FIELDS`, quindi elenco, etichette,
  segnaposto e filtro non possono divergere; il segnaposto della barra dice su cosa
  si sta cercando. La logica è in funzioni pure — `normalizzaRicerca(val)`
  (minuscole, accenti tolti, **apostrofi tolti senza spazio**, il resto della
  punteggiatura in spazi), `valoreCampoRicerca(track, field)` (`all` =
  `SEARCH_FIELDS_ALL`, `file` = `localFile`+`_origName`) e
  `branoCorrisponde(track, field, query)` (TUTTE le parole scritte devono
  comparire, in qualsiasi ordine) — usate da `visibleTracks()`. Effetti pratici
  misurati: «cant» trova *If I Can’t* (apostrofo tipografico: prima era
  introvabile), «61,5» trova i BPM 61.5 (virgola italiana) e «50 cent 2003» trova
  i brani di 50 Cent del 2003 anche con le parole su campi diversi. Il messaggio di
  ricerca senza risultati ora dice cosa si cercava e in quale campo («Nessun brano
  trovato per «…» in 🎵 Titolo») invece di parlare di playlist. Il filtro del tab
  🗄️ Database (`db-search`) resta **invariato** (cerca in titolo+artista+album+nome
  file): lì la tendina non c'è.
  Verifiche del 17/09/2026: **`test_search_field.py`** → 8 test con **45 casi**
  eseguiti davvero in JavaScriptCore (apostrofi dritto/tipografico, accenti,
  virgola dei BPM, anno parziale, campo sconosciuto, brano `null`) più i controlli
  di cablaggio (ogni campo della tendina esiste nel modello del brano — un refuso
  tipo `key` invece di `musical_key` non passerebbe —, tendina vuota nell'HTML e
  costruita da `SEARCH_FIELDS`, `SEARCH_FIELDS_ALL` allineato, filtro che passa da
  `branoCorrisponde`); in **Chrome reale** (Selenium, app viva su
  <http://localhost:5070/?tab=player>) **19/19**: 890 brani caricati dal database,
  13 opzioni nella tendina, barra mostrata dalla voce *Cerca*, segnaposto «Cerca per
  anno (es. 1999)…», 12 filtri confrontati riga per riga col conteggio indipendente
  ricavato da `/db/songs` (apex 1, anno 1999 **78** contro titolo 1999 **2**,
  gunmen 1, «61,5» 4, «dr dre» 6, eminem 228, «.mp3» 3, album *Marshall Mathers*
  25, «cant» 3 righe: *i can't get high*, *If I Can’t*, *Just Cant Kill The
  Beast*) e messaggio di ricerca senza risultati; **3/3** blocchi `<script>` della
  pagina compilati (JavaScriptCore) e `curl /onyx` → **200** con la nuova tendina.
  La correzione dell'apostrofo è arrivata **dal test**: la prima versione
  normalizzava `’` in uno spazio («if i can t») e «cant» non trovava *If I Can’t*.
  Solo la pagina del player è cambiata (`onyx_whosampled.html`, servita da
  `send_file` a ogni richiesta): nessuna modifica al backend, nessun riavvio
  necessario.
- **SCHEDE DI ARTISTA E DI ALBUM: DUE GUI DIVERSE (17/09/2026, notte).** Richiesta
  di Alessandro: «quando clicchi compare *Album: Everyday Is Christmas (Deluxe
  Edition)*, oppure *Album: Mus*, oppure *Artista: Eminem* … non ho idea di come
  sistemare ma è semplicemente brutto: potresti fare due cose diverse per quando
  uno clicca su un artista e quando uno clicca su un album?». Prima il nome era una
  riga di **testo piatto** nella barra in alto (`Artista: …` / `Album: …`) e
  l'album segnaposto «Mus» (147 righe in libreria: è il nome della cartella di
  caricamento) sembrava un disco vero. Ora un clic apre una **scheda** costruita da
  `renderHero()` (pagina `/onyx`), **diversa nei due casi**:
  1. **Artista** — avatar **tondo** col monogramma su gradiente generato, nome
     grande (32 px, peso 700), riga «N brani · M album · anni · durata», pulsanti
     ▶ *Riproduci* / 🔀 *Casuale* e sotto una **chip per album** (col pallino del
     colore della sua cover e il numero di brani) che porta alla scheda dell'album;
     oltre 12 album: «+N altri album».
  2. **Album** — **cover quadrata** in stile vinile (monogramma + gradiente + solco
     del disco disegnato in CSS), artista dell'album (o artisti), brani, anno,
     durata totale, e nella lista i **numeri di traccia** del disco al posto della
     posizione, senza ripetere l'album su ogni riga (`body.album-view`). Se il nome
     è un segnaposto compare il badge **⚠ album segnaposto**.
  Colori e copertine sono **generati dal nome** (`tintaDa`/`gradienteDa`,
  hash stabile: lo stesso artista ha sempre lo stesso colore) perché nel database
  `cover_art_path` è **vuota su tutte le 890 righe**: niente artwork da mostrare.
  Funzioni pure: `monogramma` (iniziali delle prime due parole che contano:
  «The Slim Shady LP» → `SS`, «Stan's Tape» → `ST`), `durataEstesa` («1 h 12 min»),
  `intervalloAnni` («1999–2018»), `riassuntoArtista`, `riassuntoAlbum`.
  Sistemato anche un **bug latente dei clic**: l'apostrofo dentro l'`onclick`
  inline (`setArtistFilter('Knoc-Turn'al')`) generava JavaScript non valido e il
  clic **non apriva niente** — in libreria sono **43 brani** con l'apostrofo in
  artista o album (10 artisti e 14 album diversi, es. «Stan's Tape»,
  «Royce Da 5'9"»): ora nome e album viaggiano in attributi
  `data-artist`/`data-album` letti da `apriArtistaDa`/`apriAlbumDa`/`heroApriAlbum`.
  Verifiche del 17/09/2026: **`test_player_hero.py`** → 17 test (8 di funzioni pure
  eseguite in JavaScriptCore — monogrammi, tinte stabili, gradienti, segnaposto,
  durate, anni, riassunti — e 9 di cablaggio: due GUI diverse, testo piatto
  sparito, numeri di traccia, clic via `data-`); in **Chrome reale** (Selenium,
  app viva) **29/29** — clic sulla chip *Eminem* → scheda artista (227 brani, 49
  album, 1996–2026, 15 h 41 min), clic su *The Marshall Mathers LP* → scheda album
  (14 brani · 2000 · 1 h 11 min · 10 artisti), «Mus» col badge ⚠, chiusura che
  ripristina la barra, clic su *Knoc-Turn'al* che ora funziona, ▶ *Riproduci* che
  parte dal primo brano della lista; **16/16 misure** della grafica (scheda dentro
  il contenuto e che non copre la lista, titolo 32 px peso 700, etichetta Space Mono
  spaziata, cover 104×104 tonda/quadrata, chip che non sbordano e si distinguono
  dallo sfondo, titolo lungo su 2 righe, finestra a 880 px che manda i pulsanti a
  capo); **8/8 sui pixel** degli screenshot (cover = gradiente reale con ~1000-1700
  colori distinti, monogramma stampato, titolo testo chiaro, accento lime
  nell'artista e teal nell'album). Tre difetti trovati **dai test** e corretti:
  l'apostrofo spezzava il monogramma («Stan's Tape» dava `SS` invece di `ST`),
  l'album **vuoto** non era marcato come segnaposto, e le chip degli album erano
  invisibili (`#1a1a1a` su `#111` → ora `#222` con bordo più chiaro e pallino
  colorato). README aggiornato (elenco file + questa nota). Screenshot delle due
  schede in `~/Desktop/SampleLab_schede_player/`.
- **IL CLIC SULLA BARRA IN BASSO PORTA PROPRIO SULLA CANZONE (18/09/2026,
  notte).** Richiesta di Alessandro: «se io clicco su una canzone mentre la sto
  ascoltando, in basso a sinistra, dovrebbe rimandarmi proprio all'esatta
  canzone, non solo all'album, cioè all'album ma nel punto in cui compare la
  canzone, non all'inizio dell'album». Prima `nowbarOpenAlbum()` chiamava solo
  `setAlbumFilter(t.album)` (e `nowbarOpenArtist()` solo `setArtistFilter`): la
  scheda si apriva, ma `renderTracks()` riscrive **la lista da capo** e
  `.tracks-area` resta al punto di scorrimento di prima → la canzone in ascolto
  poteva restare **fuori schermo** (misurato: album «Mus», 146 brani, riga
  all'indice 135 con `scrollTop` 0). Ora **entrambi** i clic, dopo il filtro,
  chiamano `evidenziaBrano(t.id)`, che:
  1. controlla con la funzione pura **`indiceBrano(lista, id)`** che la canzone
     sia davvero fra quelle mostrate (id inesistente → nessuno scorrimento);
  2. trova la riga (`.track-row[data-track-id]`, attributo nuovo sulla riga) e
     la porta **al centro** della parte visibile della lista
     (`scrollIntoView({block:"center", behavior:"smooth"})` — la sola area che
     scorre è `.tracks-area`, la scheda sta fuori e **resta a vista**);
  3. la fa **lampeggiare** (`.trovato` + `@keyframes branoTrovato`, 1,6 s:
     lime nella scheda artista, teal in quella album) con `lampeggiaRiga()`,
     riavviabile — e riaccesa **quando la lista si ferma** (poll su `scrollTop`),
     perché con le liste lunghe lo scorrimento fluido dura più del lampeggio.
     Questo difetto l'ha trovato il test, non l'occhio: la pulsazione finiva
     prima che la riga arrivasse.
  Verifiche del 18/09/2026: **`test_nowbar_scroll.py`** (nuovo) → 8 test: 10 casi
  sulla funzione pura eseguiti davvero in JavaScriptCore (primo/in mezzo/ultimo,
  assente, id vuoto/nullo/undefined, lista vuota o nulla, doppioni, id numerico)
  più i controlli di cablaggio (riga con `data-track-id`, scroll sull'area
  giusta, stile `.trovato`, i due clic che filtrano **e** evidenziano
  nell'ordine giusto); **94 test** della suite (tutti OK); in **Chrome reale**
  (Selenium, app viva, dentro l'iframe `#onyx-frame` di `/?tab=player`) **26/26**:
  A/B col vecchio comportamento (riga fuori vista), clic sul titolo → scheda
  album «Mus» con 146 brani, riga all'indice 135 **dentro** l'area,
  scostamento dal centro **0 px**, `scrollTop` da 0 a 7414, lampeggio in corso
  alla partenza **e** all'arrivo, cover ancora visibile; clic sull'artista →
  scheda di Eminem con 227 righe, riga all'indice 225, **48 px** dal centro,
  `scrollTop` 16267; fine del lampeggio dopo 2 s; id inesistente → `false` e
  lista ferma; brano senza album → non apre niente e non solleva errori. 3/3
  blocchi `<script>` compilati in JavaScriptCore. Solo la pagina del player è
  cambiata (`onyx_whosampled.html`, servita da `send_file`): **nessuna modifica
  al backend, nessun riavvio**.
- **PANNELLO SQL: `replace()` ERA BLOCCATO — E IL RECUPERO DEGLI ARTISTI
  «MULTIPLI» (18/09/2026).** Alessandro: «perché l'artista Rihanna / Eminem
  continua a comparire dopo aver runnato la query per dividere gli artisti con
  /?» e «mandami una query python da mettere nel posto adeguato nel file html ed
  eseguire». Due cose distinte, risolte entrambe:
  1. **Perché non cambiava niente.** Il pannello vieta le parole di
     `SQL_FORBIDDEN`, fra cui `REPLACE` (serve a bloccare `REPLACE INTO`), e il
     controllo colpiva anche la **funzione** `replace(...)`: la query naturale
     (`UPDATE songs SET artist = replace(artist, ',', ' / ')`) veniva rifiutata
     con «Operazione non consentita» e **non arrivava mai al database**. Ora
     `sql_consentita()` (funzione pura nuova) considera vietata una parola solo
     se è un **comando**, cioè non seguita da parentesi: `replace(...)` passa,
     `REPLACE INTO …` resta bloccato. Per la riga specifica c'era anche un
     secondo motivo: il vecchio script del pannello («📋 Script "/" artisti»)
     normalizzava **solo la spaziatura** degli slash (`50 Cent/Eminem` →
     `50 Cent / Eminem`), quindi su `Rihanna / Eminem` — già nel formato giusto
     — non aveva nulla da fare.
  2. **Il pulsante ora carica uno script completo** («📋 Script artisti
     multipli» → `loadArtistiMultipliScript()`, nel pannello *Esegui query /
     script personalizzati*): porta a `A / B / C` tutte le varianti — `&`,
     virgola, `;`, `|`, `+`, `feat.`/`ft.`/`with` e gli slash con spazi — con
     `APPLICA = True/False` in cima per l'anteprima, `conn.commit()` e
     annullabile con ↩️ Undo. **Non tocca i nomi veri** (`Tyler, The Creator`,
     `AC/DC`, `The High & Mighty`, `The Mamas & The Papas`, `Sway & King Tech`,
     `Royal & the Serpent`) e toglie il segnaposto `Brano locale` quando è
     insieme a un artista vero. Aggiorna `updated_at`, così le pagine
     ricaricano da sole (cambia la firma di `/db/changed`).
  Verifiche del 18/09/2026: lo script eseguito **su una copia** del database con
  l'**ambiente vero del pannello** (`exec` con `conn` e i builtins ridotti — il
  primo tentativo è caduto su `any()`, che lì non esiste: trovato dal test, non
  dall'occhio): **38 righe** da correggere su 890 (`Brano locale, Eminem` →
  `Eminem` per 11 righe, `Mark Moore, Eminem` → `Mark Moore / Eminem`, `Onyx
  Feat. 50 Cent, X-1` → `Onyx / 50 Cent / X-1`, `Macklemore & Ryan Lewis /
  Macklemore / Ryan Lewis` → `Macklemore / Ryan Lewis`, `Eminem ft Royce Da 59 &
  Mr Porter freestyle` → `Eminem / Royce Da 59 / Mr Porter freestyle`…), con
  `Rihanna / Eminem`, `AC/DC` e `Tyler, The Creator` **intatti**; la prima
  versione sbagliava tre nomi veri (`The High & Mighty`, `The Mamas & The
  Papas`, `Sway & King Tech`) e li ha corretti l'anteprima, non la libreria.
  Nuovo test `test_sql_guard.py` (8 test: funzione pura + cablaggio + endpoint
  vivo, con i comandi distruttivi indirizzati a una tabella inesistente) e
  **102 test** di suite. Il testo dello script dentro l'HTML è verificato con un
  giro di andata/ritorno (`String.raw`: dal template si rilegge lo script
  **byte per byte**) e i 3 blocchi `<script>` di `index (2).html` compilano.
  L'app è stata riavviata (backend toccato) e la guardia provata sull'endpoint
  vivo: `SELECT replace(...)` → 200, `REPLACE INTO`/`INSERT`/`DELETE`/`DROP` →
  400. **Lo script non è ancora stato eseguito sulla libreria vera**: si lancia
  dal pannello (carica, Esegui Python) quando si vuole.




- **SCHEDA CANZONE (18/09/2026).** Nella tabella del database ogni riga ha il
  pulsante **📄 Scheda**: è un link a `/scheda?song=<id>` (non un `onclick`, così si
  può aprire anche in una scheda nuova del browser — e si apre **davvero** in una
  scheda nuova: nell'head di `index (2).html` c'è `<base target="_blank">`). La schermata
  `/scheda` mette insieme gli **stem** (`stem_sessions` + `stem_tracks` + la
  cartella di Demucs), i **remix/cover** e i **campionamenti WhoSampled**
  (`sample_relations`) e le **analisi audio** (`audio_analyses`), con un mixer
  per far suonare gli stem insieme. Due decisioni da ricordare:
  1. `classifica_relazione` decide sample / remix / cover guardando `category`,
     `relation_type`, `transformation` e `notes`; il **titolo dell'altra canzone
     conta solo quando è l'altra a derivare** (un «(Remix)» nel brano *campionato*
     non dice niente sul nostro brano).
  2. `titolo_base` / `possibili_varianti` (i candidati per titolo) tolgono **solo
     le annotazioni** fra parentesi («(Remix)», «[HQ Lyrics]», «(Official
     Video)»…), così «Sam (Is Dead)» resta «sam is dead» (le parole contano): la
     prima versione buttava via tutta la parentesi e produceva candidati falsi.
  Le funzioni richiamate dagli `onclick` scritti nell'HTML sono esposte su
  `window`, perché dentro la funzione anonima della pagina non sarebbero
  raggiungibili (è lo stesso motivo per cui in `browse.html` il pulsante
  «↑/↓ Crescente» non risponde: **bug noto, non corretto qui**).
  Verifiche del 18/09/2026: **38 test nuovi** (`test_scheda_canzone.py`) e **183
  test** di suite; app riavviata (backend toccato: rotta `/scheda` ed endpoint
  `/db/songs/<id>/scheda`), pagine `/` `/browse` `/onyx` `/scheda` → 200; la
  scheda caricata in **Chrome reale** (headless, `--dump-dom`) su una canzone
  vera: hero, riquadri, messaggi dei gruppi vuoti e candidato *off the wall remix*
  (trovato davvero dal titolo) resi correttamente; con una cartella Demucs di
  prova (`stems/htdemucs/<nome>`, poi rimossa) la pagina ha mostrato le 4 tracce
  «solo su disco» con player, mute, volume e download, e
  `/stream-stem/<cartella>/vocals.mp3` + `/download-stem/...` → 200. La
  separazione degli stem veri **non è stata eseguita** (richiede minuti): in
  libreria `stem_*` è ancora a 0, quindi la scheda mostra «✂️ Separa gli stem ora»
  al posto delle tracce.
  Nota: `/tmp/samplelab.log` resta **vuoto** all'avvio perché l'output di Python è
  bufferizzato quando è rediretto su file (comportamento preesistente).


- **BPM DALLA BATTUTA — «🎯 Trova la battuta» e trim celeste (18/09/2026).** ⚠️
  **TOLTA LO STESSO GIORNO** su richiesta di Alessandro (vedi l'ultima nota qui
  sotto): pulsanti, trim celeste, loop `🔁 Battuta` e rotta `/beat/bar` non esistono
  più. Questa nota resta come storia di quello che si era provato e misurato. La
  stima automatica «🔎 BPM & Key» è stata **tolta da `index (2).html`** (pulsanti e
  funzione `fetchMetadata`): sbagliava troppo spesso. Al suo posto, nel sampler:
  **🎯 Trova la battuta** chiama il nuovo `POST /beat/bar` (app (2).py) e mette il
  risultato nel **trim celeste** — due maniglie libere `BATTUTA` / `FINE BATTUTA`,
  indipendenti dal trim giallo del sample — da cui nasce il BPM
  (`60 × quarti ÷ durata`, aggiornato mentre trascini); **🔁 Battuta** fa girare
  solo quel tratto e **💾 Salva BPM** lo scrive nel database della canzone aperta
  (e segna `bpm_verified`). Nel flusso «➕ Aggiungi canzone» BPM e tonalità ora
  arrivano **solo dai tag del file** (`TBPM`/`TKEY`), non più da una stima.
  Cose imparate misurando (tutte documentate nel codice e in `README_sampler.md`):
  1. in 4/4 il picco dell'autocorrelazione è del **disegno cassa-rullante** (due
     quarti): il BPM veniva la metà (un 120 diventava 60,1). Ora il tempo parte dai
     candidati dell'autocorrelazione **più** il tempo di librosa, e a parità di
     punteggio vince il periodo **più lungo**, ma solo se è un multiplo intero del
     migliore;
  2. i lag a passi di `hop` valgono 23 ms: a 120 BPM un lag di differenza è 5 BPM
     (*In Da Club*: 123,0 invece di 117,5). Il periodo viene rifinito al
     millisecondo in una finestra **stretta** (±3%: con ±8% scappava a 133,8);
  3. l'inviluppo di onset era **un frame avanti** (un colpo a 20,00 s finiva a
     19,93): ora lo zero in testa lo allinea;
  4. la soglia dei «quarti a fuoco» era troppo severa (25% del massimo): i quarti
     deboli della musica vera (*Get Up*: 0,21 contro 0,88) risultavano fuori. Ora è
     al 12% e misura «la griglia cade su un transiente», non «il colpo è forte».
  Verifiche del 18/09/2026: **21 test nuovi** (`test_sampler_battuta.py`) e **204
  test** di suite; app riavviata (backend toccato) e pagine `/` `/browse` `/onyx`
  `/scheda` → 200; `POST /beat/bar` sull'app viva → 200 con battuta sensata, 404 su
  file inesistente, 400 senza nome. Sui **segnali sintetici con tempo noto** (4/4 a
  75/90/120/140 BPM con 20 s di intro senza batteria) il BPM esce entro **0,7** e la
  battuta comincia dove entrano i tamburi (20,0-22,4 s). Sui **file veri** la
  proposta è onesta ma non sempre esatta e lo dice: *Get Up* 123,2 BPM con 3/4
  quarti a fuoco (affidabile), *In Da Club* 120,5 e *21 Questions* 93,0 con
  l'avviso «controlla a orecchio» (i valori del database per questi due sono
  117,5 e 86,1, e per *Get Up* 92,3 — un rapporto 3:4: il livello metrico dei pezzi
  shuffle non è affidabile, ed è per questo che il trim si trascina). Il trim
  celeste è stato provato **nel DOM vero** (Chrome headless sul documento del
  sampler con un audio finto: trim disegnato a 47,9 px/7,2 px, BPM 160 ricavato dal
  trim, casella BPM aggiornata, loop `🔁` attivo). Sistemato anche un difetto che
  c'era prima: nel sampler aperto da una canzone `p.filename` restava `'audio'`, e
  «Scarica selezione» non sapeva quale file tagliare.

- **«🎯 TROVA LA BATTUTA» NON PARTIVA — CORRETTI DUE DIFETTI (18/09/2026).**
  Segnalazione di Alessandro: «non funziona *trova la battuta*, compare questo:
  `Failed to execute 'fetch' on 'Window': Failed to parse URL from /beat/bar`».
  Il backend era sano (`POST /beat/bar` rispondeva 200/404/400 come previsto): i
  difetti erano due, entrambi **davanti**, e il secondo si è visto solo dopo aver
  corretto il primo.
  1. **L'URL era relativa e il sampler vive in un iframe `blob:`.** Il documento
     del sampler è un `<textarea>` (`index (2).html` righe 830–3273) che la pagina
     monta con `src = blob:…` (`openAudioEditor`, `embedAudioEditorX`). In un
     documento `blob:` la base **non è http**: `fetch('/beat/bar')` non parte
     nemmeno — Chrome si ferma al parse dell'URL. L'audio invece caricava già,
     perché il suo URL arrivava risolto dal parent (`new URL(e.data.url,
     e.origin)`). Ora in coda al documento del sampler ci sono due funzioni pure,
     `origineHttp()` e `urlBackend()`, e `trovaBattuta` fa
     `fetch(urlBackend('/beat/bar'))`: la pagina dichiara la **sua** origine
     (`window.location.origin`) nel messaggio `'load'`, con ripiego su `e.origin`,
     `document.referrer` e sulla posizione del documento. Se non c'è nessuna base
     http l'interfaccia lo dice («il sampler è aperto fuori dalla pagina di
     SampleLab: riaprilo dal database») invece di mostrare il `TypeError` nudo.
  2. **Al sampler arrivava il TITOLO della canzone al posto del nome del FILE.**
     Trovato provando il pulsante **dal vivo**: dopo il fix dell'URL la risposta
     era «File non trovato». `openInSampler` passava `label` dove ci vuole
     `local_file`, e `loadSampleXEditor` faceva lo stesso con
     `embedAudioEditorX`; il backend cerca in `downloads/`, quindi col titolo non
     trovava niente (e nemmeno «Scarica selezione» sapeva quale file tagliare).
     Ora il messaggio `'load'` porta `filename` (il file vero) **e** `etichetta`
     (il nome mostrato in testa al sampler, che resta il titolo della canzone).
  Perché i test non li avevano visti: la `load` la mandavano i test stessi (col
  nome giusto) e l'endpoint veniva chiamato con un `local_file` preso dal
  database — il guasto stava **nel cablaggio fra pagina e sampler**, che solo un
  clic vero esercita.
  Verifiche del 18/09/2026: **4 test nuovi** in `test_sampler_battuta.py` (25 in
  tutto: `origineHttp`, i 9 casi di `urlBackend`, il nome file contro etichetta) e
  **208 test di suite** (erano 204); **Chrome vero** (Selenium) su
  `http://localhost:5070/?sampler=song_799822c51db6` → l'iframe è `blob:…`,
  `baseBackend` = `http://localhost:5070`, `urlBackend('/beat/bar')` =
  `http://localhost:5070/beat/bar`, la vecchia `fetch` relativa dà **ancora**
  l'errore segnalato (prova che la diagnosi è giusta) e 🎯 **Trova la battuta**
  risponde «battuta a 0:00,9 → 0:03,0 · 116,4 BPM · 3/4 quarti a fuoco · batteria
  da 0:00,0» col trim celeste nel player (0,902–2,965 s, BPM 116,3);
  `/` servita con il fix (200, 320.564 byte) e nessun clic su 💾 Salva BPM
  (il database non è stato toccato dalla verifica). Verificato anche l'**altro
  punto che monta il sampler** (`embedAudioEditorX`, l'editor embedded dello
  scraper) intercettando il messaggio `'load'`: `origin` =
  `http://localhost:5070`, `filename` = `onyx_t_…Cha-Ching` (il file vero),
  `etichetta` = 'Etichetta di prova'. Il backend **non** è stato
  modificato, quindi l'app non è stata riavviata: la pagina la legge dal disco a
  ogni richiesta (`send_file`). Mappa del codice in `README_sampler.md` §12
  aggiornata: il documento finisce a riga **3273** e i **34 numeri interni** dopo
  `trovaBattuta` sono stati ricalcolati dal file vero (non a mano).


- **DUE INTERRUTTORI PER I TRIM E RIQUADRO CELESTE PIENO (18/09/2026).** Richiesta di
  Alessandro: «metti un pulsante per togliere il trim giallo (nel senso che quando lo
  clicchi l'utente non lo vede proprio più, scompare) e uno per il riquadro blu, on ed
  off, però il riquadro blu deve essere costruito esattamente come il riquadro giallo a
  livello di grafica: adesso ha solamente i bordi celesti ma in realtà … tutta la parte
  selezionata dall'inizio alla fine dovrebbe cambiare colore».
  1. **Il riquadro celeste è pieno come il giallo.** Il trim della battuta aveva
     `background:rgba(45,212,191,.06)` (praticamente invisibile) e ombreggiature fuori
     **celesti** (`.10`): la fascia selezionata risultava più *chiara* di quella fuori,
     quindi si vedevano solo i due bordi (esattamente il difetto segnalato). Ora è
     costruito come il trim giallo: riempimento deciso `rgba(45,212,191,.22)`, bordi
     sopra e sotto, e ombreggiature **scure** fuori dalla battuta (`rgba(0,0,0,.45)`).
     Resta **sopra** la selezione gialla (`z-index:5` contro `2`), quindi si vede anche
     quando la battuta è dentro al sample — ed è quello il caso normale, visto che il
     trim giallo parte con 30 s di finestra e la battuta ne dura 2.
  2. **Due pulsanti nuovi** nella riga di *Battute Sel.*, con l'etichetta che dice lo
     STATO e non l'azione (la lezione del pulsante della griglia, 17/09): **✂ Trim giallo
     on/off** toglie di mezzo riquadro, ombreggiature, maniglie **IN/OUT** *e l'area di
     trascinamento* — quindi con `display:none` su tutti e sei gli elementi il trim
     giallo non si vede e non si trascina più; **🎯 Battuta on/off** spegne solo il
     disegno del celeste, mentre misura, loop `🔁 Battuta` e `💾 Salva BPM` continuano a
     funzionare. **🎯 Trova la battuta riaccende il celeste da sé**: un risultato che non
     si vede non serve a niente. Stato per player (`trimVisibile`/`barVisibile`), due
     funzioni pure per le etichette (`etichettaTrimGiallo`, `etichettaBattutaVisibile`),
     `aggiornaPulsantiTrim`, `toggleTrimGiallo`, `toggleBattutaVisibile`; le funzioni
     stanno con la famiglia della visibilità della griglia, i pulsanti accanto a 🎯 e 💾.
  Verifiche del 18/09/2026: **3 test nuovi** in `test_sampler_battuta.py` (28 in tutto) e
  **211 test di suite** (erano 208); **Chrome vero** (Selenium) sul sampler con giallo
  0→20 s e celeste 4→12 s, misurando i **pixel** di `#tv-main` (a una quota senza barre
  d'onda): con entrambi accesi la fascia della battuta è `(28,67,48)` — **turchese** —
  contro `(12,14,4)` della fascia gialla e `(2,2,2)` fuori; con **✂ off** tutti e sei gli
  elementi gialli risultano `display:none` e il punto dov'era il giallo torna a `(4,4,4)`
  di sfondo mentre la battuta resta turchese `(16,53,48)`; con **🎯 off** il centro torna
  `(23,26,7)` (nessun turchese) e il pulsante dice `🎯 Battuta off` senza `active`; la
  riga dei pulsanti resta su **una linea** (5 pulsanti, `scrollWidth` 958 = larghezza
  958: nessun trabocco) e i due nuovi dicono `on`↔`off` con la classe `active` a ogni
  clic; dopo **🎯 Trova la battuta** sulla canzone vera («battuta a 0:00,9 → 0:03,0 ·
  116,4 BPM · 3/4 quarti a fuoco · batteria da 0:00,0») il pulsante torna
  `🎯 Battuta on` e il riquadro riappare. Mappa del codice in `README_sampler.md` §12
  ricalcolata dal file vero: il documento del sampler ora finisce a riga **3345** e i
  numeri interni (67 fra funzioni e ancore) sono stati riallineati.


- **LOOP DELLA BATTUTA — NON SI SENTE PIÙ MUSICA OLTRE LA BARRA (18/09/2026).**
  Segnalazione di Alessandro: «l'endpoint e punto di inizio del trim blu non
  coincidono con l'inizio e la fine effettiva, cioè viene suonata anche una piccola
  parte che va oltre la barra blu». Prima di toccare il codice l'ho **misurato**
  (campioni di `audio.currentTime` ogni 4 ms mentre il loop 🔁 gira, battuta
  4,000→6,000 s): il controllo del loop sfora di **4-8 ms** e la ripresa è **sempre
  esatta** (4,000 s in tutti e sei i giri) — quindi non era il controllo: era
  **l'audio già consegnato al dispositivo**, che si sente comunque anche dopo aver
  riportato indietro la testina. Il ritardo lo dichiara il browser:
  `AudioContext.outputLatency` = **24 ms** su questo Mac (5,8 ms `baseLatency`;
  identico headless e in una finestra vera). Fix: il ritorno si **anticipa** di
  quella latenza più il margine del disegno (8 ms), con due funzioni pure —
  `anticipoRitorno(latenza)` (tetto **60 ms**, valore tipico 20 ms se il browser non
  lo dichiara) e `anticipoLoop(latenza, lunghezza)` (mai più di **un terzo** della
  selezione, altrimenti con una selezione corta si tornerebbe indietro subito, in un
  loop vuoto). La latenza si legge davvero: `aggiornaLatenzaUscita()` alla prima
  riproduzione (il clic su ▶ è il gesto dell'utente che rende lecito il contesto
  audio) più `leggiLatenzaUscita()` a ogni fotogramma del loop, perché
  `outputLatency` compare **solo a contesto avviato** (misurato: 0 da fermo, 24 ms
  poco dopo — la prima versione leggeva 6 ms, cioè solo `baseLatency`). Vale per
  **tutti e due** i loop: 🔁 Battuta e ✂ Sel.
  Verifiche del 18/09/2026: **3 test nuovi** (`test_sampler_battuta.py`, 31 in
  tutto: `anticipoRitorno` su 6 casi, `anticipoLoop` su 5, più il cablaggio) e
  **214 test di suite** (erano 211); misurato in Chrome dopo il fix: **sforamento 0 ms**, ritorno
  ~26 ms prima della fine, ripresa esatta a 4,000 s in tutti e 6 i giri, latenza
  letta 24 ms → anticipo 32 ms, e **identico col loop ✂ Sel** (sempre 0 ms di
  sforamento). Cosa **non** cambia: barra disegnata, `barStart`/`barEnd`, BPM
  salvato e taglio scaricato restano esatti — cambia solo dove torna indietro la
  testina, quindi la battuta **suonata** è ~30 ms più corta di quella disegnata
  (1,5% su una battuta di 2 s) e in cambio non si sente più musica dopo la barra.

- **«TRIM GIALLO OFF» = TUTTO GRIGIO, E VIA «TROVA LA BATTUTA» (18/09/2026).** Due
  richieste di Alessandro nella stessa sessione: «quando c'è trim giallo off dovrebbe
  smettere anche di far comparire una parte di audio completamente gialla, dovrebbe
  tornare tutto grigio» e «non mi piace per niente tutta sta roba di trova battuta,
  fa un po schifo… toglila».
  1. **L'onda torna grigia.** Col trim spento restava gialla la forma d'onda *dentro*
     la selezione: `drawWaveform` colora le barre con `rgba(200,240,0,0.6)` quando il
     tempo è fra IN e OUT, e non guardava lo stato del trim. Ora la condizione è
     `p.trimVisibile !== false && …` e `toggleTrimGiallo` fa `fullRedraw` (prima
     `updateTrimUI`, che l'onda non la ridisegna): col trim spento non resta
     **niente** di giallo, in nessun punto della forma d'onda.
  2. **«Trova la battuta» tolta del tutto.** Via i pulsanti **🎯 Trova la battuta**,
     **💾 Salva BPM** e **🎯 Battuta on/off**, il **trim celeste** con le maniglie
     BATTUTA/FINE BATTUTA e la sua riga di informazioni, la terza modalità di loop
     **🔁 Battuta**, tutto il JS che li reggeva (`trovaBattuta`, `salvaBpm`,
     `aggiornaBattuta`, `impostaBattuta`, `bpmDaBattuta`, `barTrimClamp`,
     `etichettaBattuta`, `quartiBattuta`, i trascinamenti `startBarTrimDrag`…), il
     ponte nella pagina (`salvaBpmDaSampler` e il messaggio `saveBpm`), il cablaggio
     `songId` che serviva solo a quello, e **la rotta `/beat/bar`** in `app (2).py`
     con le sue 14 funzioni (428 righe: autocorrelazione, periodi candidati,
     punteggio della griglia, colpi a fuoco, inviluppo di onset, lettura del file).
     Restano il trim giallo, la griglia, il metronomo, il TAP, **Allinea griglia** e
     il player: il BPM si misura a orecchio come prima, e i suggerimenti in pagina ora
     dicono «🎵 TAP o Allinea griglia» invece di mandare a 🎯. L'anteprima dell'audio
     nel sampler usa ancora `urlBackend()` — gli ho dato quell'uso, prima lo usava solo
     la battuta — e `origineHttp`/`urlBackend` restano con i loro test.
  Verifiche del 18/09/2026: **`test_sampler_battuta.py` → `test_sampler_trim.py`**
  (13 test: il pulsante, gli elementi che spariscono, l'onda grigia, l'anticipo del
  loop, l'URL assoluta e il controllo che «Trova la battuta» non resti né nella pagina
  né nel backend) e **196 test di suite**; in **Chrome vero** il DOM del sampler non
  contiene più nessuno dei 13 id della battuta (`bts-main`, `bt-info-main`,
  `bar-btn-main`, `loop-bar-main`…) e i superstiti ci sono tutti (`trim-btn-main`,
  `loop-sel-main`, `loop-all-main`); misurati i **pixel** della forma d'onda: col trim
  acceso la barra dentro la selezione è `(193,231,0)` (giallo) e fuori `(38,38,38)`,
  col trim spento diventa `(86,86,86)` con **differenza fra i canali 0** (grigio puro),
  uguale al resto dell'onda; app riavviata (backend toccato) con `/beat/bar` → **404**,
  `/db/stats` e tutte le pagine → 200, `/metadata/estimate` ancora vivo; guida del
  sampler aggiornata (la §5.7 è diventata «✂ Trim giallo on/off», §11 e §13 riscritte,
  mappa §12 ricalcolata dal file vero: il documento del sampler ora finisce a riga
  **3074**).

  Guida del sampler aggiornata (riga 🔁 Battuta in §5.7 e il «perché» in §13) e
  mappa del codice §12 ricalcolata dal file vero.


- **LEGENDA DEI CONTROLLI DELLA GRIGLIA NEL SAMPLER (18/09/2026).** Alessandro:
  «puoi aggiungere una legenda nel sampler? qualcosa che spieghi quello che hai
  appena detto [come funzionano **Offset**, **Battute Sel.**, **Diventa Bar N°** e
  **Allinea griglia**], magari con un esempio di utilizzo». Fatto: sotto la riga di
  quei controlli c'è un riquadro che si apre con un clic —
  **📖 Come funzionano Offset, Battute Sel., Diventa Bar N° e Allinea griglia (con un
  esempio)** — e spiega: il significato di ognuno con la formula vera
  (`offset + k × passo`, `BPM = 60 × Battute Sel. ÷ (OUT − IN)`,
  `offset = IN − (N − 1) × (240 ÷ BPM)`), la differenza fra **Adatta** e **Allinea**,
  l'**esempio** numerico (selezione `10,0 → 12,0 s`: con `4` → 120 BPM e offset = IN;
  con `8` e Bar N° `3` → 240 BPM e offset = 8 s) e cosa fare «se qualcosa non torna»
  (metronomo che cade con la cassa, scivolamento = BPM sbagliato di poco, «gira» =
  multiplo da correggere con **Moltiplica**). È un `<details>` come la 📖 Legenda del
  pannello SQL: si apre e si chiude da sé, **senza JavaScript**, e non tocca niente
  nel brano. Corretta anche una frase stantia della guida (§8, punto 2): diceva che
  la selezione riempie «sempre `Battute Sel./4` celle, che siano quarti o battute»,
  mentre il `/4` vale solo con l'unità a `1 bar` (le celle hanno la larghezza
  dell'unità: `celle = Battute Sel. ÷ (4 × unità)`).
  Verifiche del 18/09/2026: **1 test nuovo** (`test_sampler_trim.py`, 14 in tutto:
  presenza della legenda, contenuto con l'esempio, e il controllo che sia **fuori**
  dalla riga dei pulsanti — dentro al flex sarebbe una colonnina stretta) e **197
  test di suite**; in **Chrome vero** la legenda è chiusa all'apertura, si apre al
  clic (contenuto visibile, `offsetHeight` > 0), si richiude al secondo clic e il
  riquadro resta largo quanto la riga dei controlli; mappa del codice §12 ricalcolata
  dal file vero (il documento del sampler ora finisce a riga **3143**).


- **PULSANTE «📄 SCHEDA»: APERTURA CORRETTA (18/09/2026).** Segnalazione di Alessandro:
  «il pulsante scheda su ogni canzone non funziona, viene aperta una pagina
  inesistente». Il pulsante c'era dal 17/09 ma linkava il **nome del FILE**
  (`scheda.html?song=<id>`, href relativo): l'app quella pagina la serve sulla rotta
  **`/scheda`**, quindi il browser chiedeva `/scheda.html` e riceveva un **404** — in
  una scheda nuova, perché nell'head di `index (2).html` c'è `<base target="_blank">`
  (ed è per questo che la pagina inesistente «compariva altrove» mentre la tabella del
  database restava al suo posto). Corretti **tutti** i link interni che usavano i nomi
  dei file invece delle rotte — **11 sostituzioni in 3 pagine**: `/scheda?song=…` (il
  pulsante), `/browse?artist=…` e `/browse?album=…` (i chip artista, le 💿 nel database
  e i link interni di `browse.html` e `scheda.html`). Ripulito anche il
  `<base target="_blank">` **duplicato cinque volte** (conta solo il primo): ora ce n'è
  uno, con il commento che spiega cosa fa.
  **Perché non se n'era accorto nessuno:** il test controllava la *stringa* dell'href
  (giusta per sbaglio) e la pagina veniva aperta per la sua rotta vera `/scheda`: la
  domanda che mancava — «il link che vedo porta a una pagina che l'app serve?» — non
  era coperta da nessun test. Ora sì (**4 test nuovi** in `test_scheda_canzone.py`,
  42 in tutto): nessun link a file `.html`, l'href del pulsante è `/scheda?song=…`, il
  `<base>` è uno solo, e due prove sull'**app viva** chiedono `/scheda?song=<id vero>`
  (200, con le sezioni della scheda) e `/browse?artist=…` (200) — più il fatto che
  `/scheda.html` risponde 404.
  Verifiche del 18/09/2026: in **Chrome vero**, cliccando 📄 Scheda nella tabella si
  apre una **seconda scheda** su `/scheda?song=song_f5dfab2c474a` con titolo
  «SampleLab (2) — off the wall remix» e le sezioni `hero`, `stem-body`,
  `varianti-body`, `sample-body` — **nessun 404** — e il link 💿 porta a
  `/browse?album=Mus` («Esplora»); **201 test di suite** (erano 197); pagine
  `/` `/browse` `/onyx` `/scheda` → 200.

