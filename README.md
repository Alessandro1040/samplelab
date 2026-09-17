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
- `fortissimo_compare_v3.py` — modello **Fortissimo Compare v3**: confronto tra
  due output `AudioAnalysis` (MIDI + one-shot), score [0,1]
- `fortissimo.html` — interfaccia di test del modello (pagina `/fortissimo`)
- `test_fortissimo_compare.py` — test del modello
  (`python3 -m unittest -v test_fortissimo_compare`)
- `test_download_fallback.py` — test del recupero dei download (solo file creati
  dal job, mai l'audio di un altro sample): `python3 -m unittest -v test_download_fallback`
- `test_verify_genius.py` — test del recupero crediti da Genius (tutti gli
  artisti, produttori, compositori): `python3 -m unittest -v test_verify_genius`
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

## Note operative e stato corrente (11/09/2026, aggiornate al 17/09/2026)

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

