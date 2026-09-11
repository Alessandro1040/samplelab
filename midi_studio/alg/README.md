# fortissimo_alg.js — algoritmo di analisi (versione pura)

Questo file contiene **solo l'algoritmo** che, dato un brano audio:

1. stima in quante sorgenti/strumenti è composto,
2. le separa,
3. trascrive le note di ciascuna sorgente (MIDI),
4. estrae un campione one-shot per sorgente,
5. ricostruisce il mix da MIDI+campioni e ne misura la bontà (SI-SDR/MSE/correlazione).

È estratto **verbatim** dall'estrattore dell'interfaccia (`../extractor.html`, a sua
volta copia corretta di `fortissimo_pro.html`): le 19 funzioni di calcolo sono
state verificate identiche carattere per carattere, l'unica differenza è che i
richiami all'interfaccia (`log`, `sp`, `sl`) ora passano da callback opzionali e
non c'è alcun accesso al DOM. Si può quindi eseguire in browser, worker o Node.

## API

```js
const esito = await analizza(audioFloat32, {
  sr: 44100,        // sample rate dell'array
  maxK: 6,          // n. massimo di sorgenti da provare (default 6)
  onsetSigma: 1.5,  // soglia onset per le percussioni (× deviazione standard)
  minNoteMs: 50,    // durata minima di una nota (ms)
  onLog: m => {},   // callback di log (facoltativa)
  onProgress: (fase, pct) => {},   // avanzamento (facoltativa)
});
```

`esito` contiene: `sources` (`{id,name,type,energyPct,features}`), `nSources`,
`notes` (`{s0:[{pitch,start,end,velocity}], …}`), `samples` (one-shot),
`reconstructed` (mix ricostruito), `siSdr`, `mse`, `corr`, `ms`, `durationSec`.

Sono esportate anche `writeMidi(nome, note)`, `writeMultiMidi(sorgenti, note)` e
`writeWav(campioni, sr)` (restituiscono `Uint8Array`). In Node:
`const { analizza } = require("./alg/fortissimo_alg.js")`.

Per **far suonare il MIDI con lo strumento giusto** (il one-shot della traccia):

```js
rendiTraccia(id, esito, [durata])   // → Float32Array: MIDI di una sorgente reso
                                    //   applicandolo al SUO one-shot (pitch+ADSR)
rendiMix([ids], esito, [durata])    // → mix di più tracce rese così
```

`rendiTraccia` è la stessa logica di `recon()` ristretta a una traccia: le note
MIDI vengono trasposte sul pitch del campione one-shot di quella sorgente, quindi
il timbro resta quello dello strumento rilevato.

## Pipeline (ordine dei passi nel codice)

| Fase | Funzione | Cosa fa |
|---|---|---|
| 1 | `specgram()` + `fftMag()` | spettrogramma FFT: N=2048, hop=512, finestra di Hann, 1024 bin |
| 2 | `autoK()` + `kmeans()` + `silhouette()` | K-means su **16 bande spettrali** medie; sceglie K massimizzando la silhouette (K da 2 a `maxK`) |
| 3 | `wiener()` | maschera **soft di Wiener** sulla coerenza tra spettro del frame e centroide di ogni cluster; ricostruisce i K segnali con overlap-add (Hann²) |
| 4 | `features()` + `classify()` | centroid/rolloff/ZCR/contrasto di banda per sorgente → nome (`Kick`, `Snare`, `Bass`, `Piano/Guitar`, `Synth/FX`, …) e tipo (`drums`/`perc`/`tonal`) |
| 5 | `transcribe()` + `yin()` | percussioni: spectral flux + soglia; tonali: YIN frame-per-frame (hop 1024) con merging delle note |
| 6 | `extract()` + `proc()` | per sorgente tonale: cerca il segmento più stabile (YIN) e taglia 1,2 s; altrimenti il punto di massima energia; fade in/out |
| 7 | `recon()` + `siSdr()`/`mse()`/`corr()` | ricostruisce il mix trasponendo i campioni sulle note (ADSR) e misura la qualità |

## Stato verificato (11/09/2026)

- 19/19 funzioni **identiche** a `extractor.html` (controllo automatico), zero
  riferimenti al DOM, sintassi valida (JavaScriptCore).
- Banco di prova: **http://localhost:5080/alg** (esegue `analizza()` su un audio di
  prova o su un file caricato, stampa il riepilogo e offre i download di MIDI/WAV).
- **Ascolto per traccia** (nel banco `/alg`): per ogni sorgente una scheda con
  piano roll e i pulsanti *🎹 MIDI con lo strumento* (`rendiTraccia` → MIDI reso
  con il one-shot di quella sorgente), *🔊 Traccia separata* (`SS[id]`),
  *🎯 Campione* (`samples[id]`), più i download `.mid` e del rendering `.wav`;
  in cima i comandi globali (originale, mix MIDI+one-shot, mix ricostruito,
  ferma). Nell'estrattore (`/extract`, tab **Strumenti**) c'è lo stesso pulsante
  *🎹 MIDI con lo strumento* accanto a *Campione* e *Separato*.
- Verifiche del rendering per traccia (Chrome headless, audio di prova 6 s):
  4 sorgenti, per ognuna la resa ha 264.600 campioni con ~193.000 campioni non
  nulli e ampiezza massima 0,909; playback avviato davvero (`suonaTraccia`,
  `suonaMixTracce`, `suonaRicostruzione`, `suonaOriginale` → `true`, stato
  AudioContext `running`), nessun errore in console.
- Misure su audio di prova sintetico (3 sorgenti + melodia + kick):
  - 2,5 s → **4 sorgenti**, 31 note, SI-SDR ≈ −45 dB, **1,15 s** di calcolo;
  - 6 s → **4 sorgenti**, 70 note, SI-SDR ≈ −39,6 dB, **2,78 s** di calcolo.
- Su un brano vero di 150 s ("Average Joe"): 2 sorgenti, 60 note, SI-SDR −56 dB,
  **50 s** di calcolo (≈ 0,33× la durata).

## Difetti noti (misurati) — punti da migliorare

1. **Risultati non deterministici.** `kmeans()` inizializza i centroidi con
   `Math.random()`: lo stesso audio dà risultati diversi a ogni esecuzione
   (es. SI-SDR da −44,9 a −46,1 dB in tre run consecutivi; il numero di sorgenti
   può cambiare). → PRNG seminato e/o più restart scegliendo il clustering migliore.
2. **Classificazione che collassa.** Sul materiale di prova **tutte** le sorgenti
   vengono etichettate `Synth/FX`: le soglie di `classify()` sono tarate su
   batteria/basso e non usano feature armoniche. → rapporti armonico/percussivo
   (HPSS), spectral flatness, chroma, o un classificatore addestrato.
3. **Stima di K fragile.** 16 bande medie + silhouette danno K=2 su mix densi
   ("Average Joe", "10 Laws") e K=4-6 sul sintetico. → feature più informative
   (MFCC/chroma/HPSS) e criterio più robusto (stabilità, BIC, elbow).
4. **Separazione grossolana.** Maschera solo sul **modulo** dello spettro, senza
   fase né contesto temporale: SI-SDR intorno a −40/−56 dB. → maschere complesse,
   più iterazioni, vincoli di sparsità (o modelli appresi, es. Demucs in Python).
5. **YIN lento e povero sui mix densi.** O(N²) per frame (il costo cresce con la
   durata) e su un mix denso estrae pochissime note (1 nota per sorgente su
   "Average Joe"). → autocorrelazione via FFT, tracking multi-pitch, controllo di
   durata/velocity.
6. **One-shot naïf**: taglio fisso di 1,2 s al punto di massima energia (o al
   segmento più stabile), senza allineamento al pitch reale né loop.
7. **Input mono obbligatorio, nessun ricampionamento**: chi chiama deve passare un
   `Float32Array` mono a un `sr` ragionevole.
8. **Nessuna verifica automatica**: il banco `/alg` stampa solo un riepilogo.
   → aggiungere asserzioni di riferimento (sorgenti/note/metriche) per non
   rompere nulla modificando l'algoritmo.

## Nota importante per chi modifica questo file

`../extractor.html` contiene **ancora una copia** di queste funzioni (versione
legata all'interfaccia). Se modifichi `fortissimo_alg.js`, la pagina
dell'estrattore **non** cambia finché non si portano le modifiche anche lì — o,
meglio, finché non si fa caricare `fortissimo_alg.js` all'estrattore eliminando la
copia duplicata (a quel punto questo file diventa l'unica fonte).

## Banco di prova

```bash
open http://localhost:5080/alg      # esegue l'algoritmo puro su un audio
```
Oppure da Node: `const { analizza } = require("./fortissimo_alg.js")`.
