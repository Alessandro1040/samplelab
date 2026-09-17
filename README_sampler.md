# 🎛️ Sampler — Player standalone con griglia FL-Studio

**Guida utente del sampler di SampleLab (`index (2).html`, pagina `/`)**

> **In una frase.** È il banco di ascolto e di misura del tempo della libreria:
> apri una canzone (dal tab 🗄️ Database, dal player 🎧 Onyx o da un link) e il
> sampler ti mostra la **griglia sovrapposta alla forma d'onda** con il **BPM che
> hai in database già impostato** — così vedi e senti *subito* se quel BPM è
> quello vero, e se non lo è lo **ricavi dalla musica**: selezioni una battuta,
> dici quante battute è e premi **Allinea griglia**.

SampleLab · Alessandro Lo Curcio · aggiornato al **17/09/2026**

---

## Sommario

1. [Che cos'è e a cosa serve](#1-che-cosè-e-a-cosa-serve)
2. [Come aprirlo](#2-come-aprirlo)
3. [La mappa dell'interfaccia](#3-la-mappa-dellinterfaccia)
4. [Percorso guidato: il BPM vero in 60 secondi](#4-percorso-guidato-il-bpm-vero-in-60-secondi)
5. [I controlli, uno per uno](#5-i-controlli-uno-per-uno)
6. [Il righello e le battute: selezionare, spostare, allungare](#6-il-righello-e-le-battute-selezionare-spostare-allungare)
7. [La forma d'onda: IN, OUT, playhead e offset del campione](#7-la-forma-donda-in-out-playhead-e-offset-del-campione)
8. [La matematica della griglia (con i numeri misurati)](#8-la-matematica-della-griglia-con-i-numeri-misurati)
9. [Ritagliare e scaricare](#9-ritagliare-e-scaricare)
10. [I due sampler e le loro differenze](#10-i-due-sampler-e-le-loro-differenze)
11. [Perché il BPM del database può non tornare](#11-perché-il-bpm-del-database-può-non-tornare)
12. [Dove sta cosa nel codice](#12-dove-sta-cosa-nel-codice)
13. [Note, limiti e piccoli trucchi](#13-note-limiti-e-piccoli-trucchi)

---

## 1. Che cos'è e a cosa serve

Il sampler è il **trimmer in stile FL-Studio** che vive dentro la pagina
principale di SampleLab: una forma d'onda a tutto schermo, un righello numerato
per battute, una griglia che si disegna sopra l'audio, un metronomo e un
trasporto di riproduzione. Non è un giocattolo: serve a **chiudere il cerchio tra
i dati e la musica**.

I BPM che vedi nella colonna `bpm` del database arrivano da Tunebat o da
un'analisi del file (`ffmpeg`/`librosa`): sono stime, e come tutte le stime
sbagliano — prendono il doppio o la metà del tempo, il tempo di un'altra sezione,
o semplicemente nessun tempo. Il sampler è il posto dove quel valore si
**verifica a orecchio e a occhio**:

- **a orecchio**: accendi il **metronomo** e senti se i colpi cadono insieme alla
  cassa o "scivolano" — se scivolano, il BPM salvato è sbagliato;
- **a occhio**: guardi se le **linee della griglia** passano sopra i colpi di
  batteria o finiscono tra due colpi;
- **se non tornano**, invece di andare a tentoni premi **🎵 TAP** a tempo di
  musica oppure selezioni una battuta e lasci che il BPM te lo **calcoli il
  sampler** (*Battute Sel.* + **Allinea griglia**);
- **per sistemare i mezzi tempi** (il caso più frequente: un pezzo che "sembra"
  150 ma è 75) c'è **Moltiplica**;
- quando hai capito qual è il numero giusto, lo salvi sulla riga della libreria
  (*✏️ Edit* nella tab Database) e da lì in poi è quello il valore di riferimento.

In più il sampler serve a **ritagliare**: definisci un intervallo IN/OUT (a mano
o agganciandolo alla griglia), e nel player dei sample il taglio viene eseguito
davvero dal backend e scaricato in MP3 o WAV.

Tutto gira **in locale** sulla tua macchina: l'audio arriva dal disco
(`/stream/<file>`), il BPM dalla riga del database, e niente lascia il computer.

## 2. Come aprirlo

Ci sono **quattro strade**, tutte sulla stessa macchina (l'app deve essere attiva:
`python3 "app (2).py"`, porta **5070**).

| Da dove | Come | A cosa serve |
|---|---|---|
| 🗄️ **Database** (pagina `/`) | pulsante **🎛 Sampler** nella cella azioni di ogni riga **con file locale** (accanto a ✂️ Stem e ✏️ Edit) | controllare il BPM di una canzone della libreria, partendo dal valore salvato |
| 🎧 **Player** (tab Player, oppure `/onyx` aperto da solo) | menu **⋮** della canzone (o tasto destro) → **🎛 Apri nel sampler** | idem, senza passare dalla tabella: il player trova da sé l'id del brano nel database |
| 🔗 **Link diretto** | `/?sampler=<id>` (es. `/?sampler=song_204a06d6ac12`) oppure `/?sampler_file=<nome file>` | aprirlo da un segnalibro, o per un brano che nel database non c'è ancora |
| 🔍 **Trova Campioni** | le card dei sample/originali **incorporano** il sampler (player "di pagina") | confrontare originale e sample e **ritagliare davvero** (vedi §9) |

Cosa succede quando lo apri:

1. si apre il modale **🎛️ ‹titolo del brano›** con dentro il sampler;
2. il file viene letto dal disco e trasmesso da `/stream/<nome file>` (l'audio
   **non** viene riscaricato da YouTube);
3. la casella **BPM** è già compilata con il valore del database: se è `60.1`,
   nel campo leggerai `60.10`;
4. compare un avviso in basso a destra che riassume cosa stai guardando:
   *«🎛️ "60 Hz II" aperto nel sampler — BPM nel database: 60.1 (controlla con
   griglia/TAP)»*; se il BPM non c'è: *«nessun BPM nel database: misuralo con
   TAP»*;
5. la selezione parte dall'inizio con una finestra di **30 secondi**
   (IN `0:00`, OUT `0:30`) — è solo un punto di partenza, si trascina dove vuoi.

> 💡 **Se non vedi il pulsante o la voce di menu**: ricarica la pagina con
> **Cmd+Shift+R**. Le pagine servono il JavaScript così com'è su disco, ma il
> browser tiene in cache la versione vecchia.
>
> 💡 **Se il brano non ha file locale** (solo il link YouTube) il pulsante non
> c'è: prima scarica l'audio, poi il sampler lo trova.
>
> 🔒 Il sampler è un **iframe** creato al volo dal template che sta dentro la
> pagina: non è una pagina separata da aprire a mano, e per questo funziona
> sempre allineato con la versione dell'app che stai usando.

## 3. La mappa dell'interfaccia

Dall'alto verso il basso il modale è organizzato in **nove fasce**:

```
┌─────────────────────────────────────────────────────────────────────┐
│ 🎛️ ‹titolo del brano›                                        ✕ Chiudi│  1
├─────────────────────────────────────────────────────────────────────┤
│ ▶  ‹titolo›                        ✂ Sel  ⟳ Tutto   🔊 ─────────●  │  2
│    1:23 / 4:38                                                      │
├─────────────────────────────────────────────────────────────────────┤
│ Zoom  − ────────●────────────  +   1×              ⟳ Segui         │  3
├─────────────────────────────────────────────────────────────────────┤
│ Visualizza griglia │ Adatta alla griglia │ 1 bar ▾ │ 120.00 BPM │   │  4
│ x (es. 2,3) │ Moltiplica                                            │
├─────────────────────────────────────────────────────────────────────┤
│ 0 Offset │ Battute Sel. 4 │ Diventa Bar N° 1 │ Allinea griglia      │  5
├─────────────────────────────────────────────────────────────────────┤
│ 🎵 TAP │ ● Metronomo │ ogni 1/4 ▾ │ ↔ Sposta │ ↩ Undo │ ↪ Redo        │  6
├─────────────────────────────────────────────────────────────────────┤
│ │1    │2    │3    │4    │5    │6    │7    │   ← righello numerato   │  7
├─────────────────────────────────────────────────────────────────────┤
│ ░░░░▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓░░░░  forma d'onda + griglia + IN/OUT + playhead │  8
├─────────────────────────────────────────────────────────────────────┤
│ IN 0:10 → OUT 0:14 │ durata: 0:04 │ sample: +0.00s │ 🔇  ⟳ Reset…  │  9
├─────────────────────────────────────────────────────────────────────┤
│ MP3 ▾ │ Scarica selezione │ Scarica intero │ stato                  │ 10
└─────────────────────────────────────────────────────────────────────┘
```

1. **Barra del titolo** — il nome del brano e la ✕ che chiude il modale (la
   riproduzione si ferma da sola).
2. **Trasporto** — play/pausa, titolo, **timecode** `tempo corrente / durata
   totale`, il modo di ripetizione **✂ Sel** / **⟳ Tutto** e il volume.
3. **Zoom e inseguimento** — ingrandimento della forma d'onda (1× → 16×) e il
   pulsante **⟳ Segui** che tiene il playhead al centro.
4. **Griglia (riga 1)** — mostra/nascondi la griglia, **Adatta alla griglia**,
   l'unità della griglia (1/4, 1/2, 1, 2, 4 battute), il **BPM** e il
   moltiplicatore con **Moltiplica**.
5. **Griglia (riga 2)** — **Offset** (di quanto la griglia è spostata rispetto
   allo zero), **Battute Sel.**, **Diventa Bar N°** e **Allinea griglia**.
6. **Griglia (riga 3)** — **🎵 TAP**, **Metronomo** con la sua **tendina
   dell'unità** (`ogni 1/4`, `2/4`, `3/4`, `battuta`, `2`, `4 battute`),
   **↔ Sposta**, **↩ Undo**, **↪ Redo** e **✕ Deseleziona** (quest'ultimo compare
   solo quando hai una battuta selezionata).
7. **Righello** — i numeri delle battute calcolati *con la griglia corrente*
   (il `1` è in giallo), con le maniglie ai bordi della battuta selezionata.
8. **Forma d'onda** — l'audio (con la griglia disegnata sopra), le ombreggiature
   scure fuori dalla selezione, la selezione con le maniglie **IN** e **OUT**, il
   **playhead** bianco, e i due bordi turchesi quando è selezionata una battuta.
9. **Informazioni** — `IN ‹tempo› → OUT ‹tempo› | durata: ‹…› | sample: ±‹…›s |
   🔇/🔊` e il pulsante **⟳ Reset al sample**.
10. **Download** — formato (MP3/WAV), **Scarica selezione**, **Scarica intero** e
    lo stato dell'operazione.

## 4. Percorso guidato: il BPM vero in 60 secondi

Esempio reale (è il brano usato per le verifiche di questa guida: *60 Hz II* di
DJ Shocca, BPM **60.1** nel database).

1. **Apri il sampler** — tab 🗄️ Database, riga del brano, pulsante **🎛 Sampler**
   (oppure ⋮ → 🎛 Apri nel sampler dal player). Nel campo BPM leggi `60.10`.
2. **Metti il metronomo a misura di quarti** — nella tendina accanto a
   **● Metronomo** scegli **`ogni 1/4`** (è già il valore predefinito: un colpo per
   quarto) e premi **● Metronomo** (lo stato in basso passa a `🔊 1/4`). La griglia
   può restare a `1 bar`: sono due cose indipendenti.
3. **Premi ▶** e ascolta: se i colpi del metronomo **cadono insieme** alla cassa
   (o al charleston) il BPM salvato è quello giusto. Ogni volta che un colpo
   arriva "fuori fase" il numero è sbagliato.
4. **Sospetto di mezzo tempo?** Moltiplica per **2** (o per **0,5**) e riascolta:
   il caso più comune è un pezzo che "sembra" 150 ed è 75, o viceversa.
5. **Misuralo tu, se il metronomo ti confonde** — premi **🎵 TAP** una volta per
   battito seguendo la cassa, per 4–8 battiti: il BPM si aggiorna da solo
   (arrotondato all'intero).
6. **Oppure fai fare i conti al sampler**: trascina sulla forma d'onda per
   selezionare **una battuta** della musica (IN sull'attacco, OUT sulla battuta
   dopo), scrivi **Battute Sel. = 4** (una battuta 4/4 = quattro quarti) e premi
   **Allinea griglia**: il sampler calcola il BPM dal contenuto della selezione
   (nella prova: 2,000 s con 4 → **120 BPM**) e posiziona la griglia lì.
7. **Verifica** — torna a **1 bar** nell'unità della griglia: le linee marcate
   devono cadere ogni battuta (i numeri del righello tornano a ogni giro) e il
   metronomo su `ogni 1/4` deve battere a tempo anche dopo 30 secondi.
8. **Salva** — ✕ Chiudi, poi **✏️ Edit** sulla riga della tabella e scrivi il BPM
   giusto nel campo `bpm`: da quel momento la colonna dice la verità.

> 💡 **Regola pratica.** Se il metronomo "scivola" sempre nella stessa direzione
> (prima o dopo il colpo) il BPM è sbagliato di poco (1–2). Se scivola di tanto o
> "gira", è un multiplo (×2, ×0,5) o è un altro tempo del brano (un cambio di
> sezione). Se la griglia tiene su un passaggio ma non su un altro, stai
> misurando un **cambio di tempo**: il valore da salvare dipende da cosa ti serve
> campionare.

## 5. I controlli, uno per uno

### 5.1 Riproduzione, loop, volume

| Controllo | Cosa fa |
|---|---|
| **▶ / ⏸** | avvia e mette in pausa. Con **✂ Sel** attivo la riproduzione resta dentro la selezione: se sei fuori, al play riparte da **IN**; con **⟳ Tutto** scorre l'intero file e alla fine si ferma. Mentre suona, il playhead si muove e il timecode si aggiorna. |
| **✂ Sel** | ripetizione della selezione: arrivato a **OUT** torna a **IN**. È il modo giusto per giudicare il tempo su un passaggio (4 o 8 battute) senza rincorrerlo. |
| **⟳ Tutto** | nessun limite: il brano scorre dall'inizio alla fine e poi si ferma. |
| **volume** | cursore da 0 a 1 (si applica subito; non viene salvato). |
| **timecode** | `tempo corrente / durata totale`, misurato sul **righello** (quindi comprensivo dello spostamento dato a **↔ Sposta**). |

### 5.2 Zoom, scorrimento e inseguimento

| Controllo | Cosa fa |
|---|---|
| **Zoom − / +** | saltano fra i livelli **1, 1,5, 2, 3, 4, 6, 8, 12, 16×**. Più zoom = più secondi per schermo, quindi battute larghe e clic precisi. |
| **cursore dello zoom** | continuo, da 1× a 16× a passi di 0,5. In entrambi i casi la vista si **ricentra sul playhead**, così non perdi il punto. |
| **rotella del mouse** | **scorre** la forma d'onda di 3 s per tacca (non è uno zoom). Funziona anche da trackpad; si ferma ai bordi del file. |
| **⟳ Segui** | tiene il playhead **al centro** mentre l'audio suona (comodo per ascoltare un punto lontano senza perdere la vista). Si spegne da sé appena clicchi sulla forma d'onda, trascini il playhead o usi la rotella. |

### 5.3 La griglia: mostrarla, adattarla, sceglierne l'unità

| Controllo | Cosa fa |
|---|---|
| **Visualizza / Nascondi griglia** | disegna (o toglie) le linee verticali sul righello e sulla forma d'onda; quelle più marcate sono le **battute**. L'etichetta dice sempre lo stato in cui passi. |
| **Adatta alla griglia** | prende **IN** e **OUT** e li porta sul punto più vicino della griglia (snap). È il "raddrizza la selezione" dopo averla trascinata a orecchio. *Se la griglia è spenta o il BPM è 0 non fa niente*: non c'è niente su cui agganciare. Nella prova a 120 BPM: IN 10,3 → **10** e OUT 13,9 → **14**; con offset 0,7 gli agganci stanno a 0,7 + multipli del passo (10,3 → **10,7**). |
| **unità della griglia** | `1/4 bar` = un quarto, `1/2 bar` = due quarti, `1 bar` = una battuta 4/4 (**predefinito**), `2 bar` = due battute, `4 bar` = quattro battute. Cambia **linee, righello e snap**: il **metronomo no**, che ha un'unità sua (§5.5). |
| **BPM** | il tempo in battiti al minuto, con passi di 0,1. Quando confermi il valore (Invio o uscendo dal campo): la selezione si riaggancia alla nuova griglia, il metronomo si risincronizza e l'azione finisce nello storico (**Undo**). All'apertura arriva dal database. |
| **x (es. 2,3)** + **Moltiplica** | moltiplica il BPM per il fattore scritto. Accetta **virgola o punto** (`2,3` = `2.3`). Nella prova: 120 × 2,3 = **276**. Dopo il calcolo la casella si svuota. Usalo per i mezzi tempi (×2 se il BPM vero è il doppio, ×0,5 se è la metà). |

### 5.4 Offset, Battute Sel., Diventa Bar N° e Allinea griglia

Qui c'è il cuore del «fammi il BPM tu»: quattro controlli che descrivono **dove
cade la musica rispetto alla griglia**.

| Controllo | Cosa fa |
|---|---|
| **Offset** (secondi) | di quanto la griglia è spostata rispetto allo zero del file: con offset `0` la prima linea cade a 0,000 s, con `0,5` cade a mezzo secondo (e così tutte le altre). Serve quando la musica non parte esattamente sullo zero (quasi sempre). I decimali sono normali (anche negativi: `-0,13`). |
| **Battute Sel.** | **quanti quarti dura la selezione**: con `4` stai dicendo «la mia selezione è **una battuta** 4/4», con `8` «sono due battute», con `6` «una battuta e mezza». (Il nome dice *battute*, ma il conto è in **quarti**: è il numero che serve alla formula di §8.) Predefinito `4`. |
| **Diventa Bar N°** | **quale numero deve avere la prima battuta della selezione** (predefinito `1`): con `3` la selezione diventa la terza battuta del brano. È il modo per allineare i numeri del righello a quelli che leggi sul DAW o sullo spartito. |
| **Allinea griglia** | fa i conti **da zero**: dal contenuto della selezione ricava il **BPM** e l'**offset** che fanno entrare esattamente quella selezione in *Battute Sel.* quarti a partire dalla battuta *Diventa Bar N°*, e riscrive entrambi i campi. Se il BPM che ne esce è fuori dall'intervallo **1–1000** avvisa e non cambia nulla. Nella prova: selezione di 2,000 s con Battute Sel. = 4 → **120 BPM** e offset 10 (cioè IN); con Battute Sel. = 8 e Diventa Bar N° = 3 → **240 BPM** e offset 8 = IN − 2 passi. |

> ⚠️ **Da non confondere**: **Adatta alla griglia** *sposta la selezione* sulla
> griglia che hai già (non tocca il BPM); **Allinea griglia** *rifà la griglia*
> dai conti sulla selezione (ti riscrive BPM e offset).

### 5.5 🎵 TAP e Metronomo

| Controllo | Cosa fa |
|---|---|
| **🎵 TAP** | premuto a tempo di musica ricava il BPM dalla **media di tutti i colpi della sessione** (dal secondo in poi): più colpi batti, più la stima è precisa — e il pulsante lo dice, mostrando il contatore (`🎵 TAP ×12`). Accetta intervalli fra **0,2 e 2 s** (cioè 30–300 BPM): un tocco fuori tempo (o un doppio tocco) **fa ripartire la sessione** da quel colpo, e lo stesso succede se cambi il BPM a mano. Il risultato è tenuto con **un decimale** (es. `187.6`), come i BPM del database: nessun arrotondamento all'intero. |
| **● Metronomo** | clic generati via Web Audio (nessun file da caricare), con lo stato che passa da `🔇` a `🔊` (e dice l'unità: `🔊 1/4`) e un pallino che pulsa. **Ha una sua unità, indipendente dalla griglia**: nella tendina accanto scegli `ogni 1/4` (predefinito: un colpo per quarto), `ogni 2/4`, `ogni 3/4`, `ogni battuta`, `ogni 2 battute`, `ogni 4 battute` — così puoi tenere la griglia a `1 bar` per vedere le battute e sentire comunque i quarti. Il **primo** colpo di ogni battuta è più acuto (1000 Hz) e più forte, gli altri più cupi (720 Hz): senti dove ricomincia il giro. Ogni colpo fa lampeggiare una lineetta sulla forma d'onda: è il «click» che vedi. |

> 💡 **Per misurare il tempo il metronomo vuole «1/4 bar»**: con l'unità a `1 bar`
> senti un colpo per battuta e non capisci se il tempo è giusto; con `1/4 bar`
> senti ogni quarto e l'errore si sente subito.

### 5.6 ↔ Sposta, ↩ Undo, ↪ Redo, ✕ Deseleziona

| Controllo | Cosa fa |
|---|---|
| **↔ Sposta** | attiva la modalità *sposta l'audio*: il trascinamento sulla forma d'onda non muove più il playhead ma **l'intera onda sotto la griglia**. Serve per allineare a mano la musica alle linee (ascoltando il metronomo) quando l'offset a occhio non basta. Alla fine del trascinamento, se la griglia è attiva, l'onda si **aggancia** al multiplo più vicino, e la riga in basso mostra lo spostamento: `sample: ±0,00s`. |
| **↩ Undo** | torna indietro di un'azione. |
| **↪ Redo** | riapplica l'azione annullata (si perde se nel frattempo ne fai una nuova). |
| **✕ Deseleziona** | compare **solo** quando hai selezionato una battuta sul righello: fa tornare la selezione normale (IN/OUT). |

Lo storico tiene **30 stati** e ogni stato è la fotografia di cinque valori:
**BPM, IN, OUT, offset del campione, offset della griglia**. Undo/Redo non sono
persistenti (ricaricando il brano lo storico riparte).

## 6. Il righello e le battute: selezionare, spostare, allungare

Il righello in alto non è decorativo: è **la griglia stessa, numerata**.

- **Cosa contano i numeri**: una cella del righello = **una unità della griglia**.
  Con l'unità a `1 bar` i numeri sono le **battute**; con `1/4 bar` sono i
  **quarti**; con `2 bar` ogni numero vale due battute. Il numero `1` è in giallo
  per riconoscerlo subito.
- **Selezionare una cella**: un clic su una cella la evidenzia (in turchese, sul
  righello e sulla forma d'onda) e fa comparire sul waveform i due **bordi
  turchesi**; le maniglie **IN/OUT** si nascondono. Un secondo clic sulla stessa
  cella la deseleziona, come il pulsante **✕ Deseleziona**.
- **Trascinare il bordo di sinistra** sposta **la griglia**: cambiano l'**Offset**
  e, con esso, tutte le linee (utile per far combaciare la griglia con la prima
  cassa del brano).
- **Trascinare il bordo di destra** allunga o accorcia la cella selezionata e
  quindi **riscrive il BPM**: il sampler prende la nuova lunghezza e ne fa
  `BPM = 240 × unità / lunghezza`. Se tieni premuto **Shift** il BPM viene
  arrotondato all'unità; altrimenti resta con i decimali. È il modo più diretto
  per "aggiustare" il tempo a occhio: fai combaciare la cella con la musica e il
  numero si aggiorna da solo.
- **Lo scorrimento** del righello è lo stesso della forma d'onda: la rotella del
  mouse (3 s per tacca) e la vista si ricentrano quando cambi zoom.

## 7. La forma d'onda: IN, OUT, playhead e offset del campione

La zona grande è la forma d'onda del file, con dentro tutto quello che serve per
ritagliare e per misurare:

- **Fuori dalla selezione** l'onda è coperta da un'ombra scura: quello che *non*
  verrà ritagliato (e che con **✂ Sel** non viene riprodotto).
- **La selezione** è la fascia chiara delimitata da due barre color accento con
  le maniglie **IN** e **OUT**: trascinale per spostare i due estremi (con la
  griglia attiva si agganciano al passo). La **lunghezza minima** è un decimo di
  secondo.
- **Trascinare dentro la selezione** la sposta tutta intera mantenendo la
  lunghezza (e con la griglia attiva si aggancia). Un **clic secco** (senza
  trascinare) sulla selezione o fuori sposta invece il **playhead** in quel punto.
- **Il playhead** è la barretta bianca con la punta in alto: si trascina con il
  mouse (o col dito) e durante la riproduzione si muove da solo a 60 fps. Con
  **✂ Sel** attivo non esce dalla selezione.
- **Bordi turchesi**: compaiono solo con una cella selezionata sul righello e
  fanno quello che fa il righello (sinistra = offset della griglia, destra = BPM).
- **La riga in basso** riassume lo stato: `IN ‹tempo› → OUT ‹tempo›`, `durata:
  ‹…›`, `sample: ±‹…›s` (lo spostamento dato da **↔ Sposta**) e l'icona
  **🔇/🔊** del metronomo. Se compare un avviso rosso significa che il punto da
  cui è stato aperto il sampler **non esiste in questo file** (capita quando
  l'audio scaricato è più corto del previsto: serve una versione completa).
- **⟳ Reset al sample** rimette **IN** all'inizio del brano (il secondo da cui è
  stato aperto il sampler) e, se la selezione non è più valida, le ridà i 30
  secondi di partenza.
- **Il disegno dell'onda** è il valore massimo dell'audio per colonna di pixel,
  calcolato una volta sola: su file lunghi il disegno può comparire un istante
  dopo l'apertura (sotto, di solito, la forma d'onda è già pronta nel giro di
  mezzo secondo).

## 8. La matematica della griglia (con i numeri misurati)

Tutto quello che fa la griglia nasce da **una sola formula**: una **battuta 4/4
vale `240 / BPM` secondi** (4 quarti × 60/BPM). Da lì:

| Grandezza | Formula | Esempio misurato |
|---|---|---|
| lunghezza di una cella (il **passo**) | `passo = (240 / BPM) × unità` dove `unità` è 0,25 / 0,5 / 1 / 2 / 4 | a **120 BPM**: 1/4 = **0,5 s** · 1/2 = **1 s** · 1 = **2 s** · 2 = **4 s** · 4 = **8 s** |
| posizione delle linee | `t = offset + k × passo` (k intero, anche negativo) | con offset 0,7 e passo 2: 0,7 · 2,7 · 4,7… |
| **Adatta alla griglia** (snap) | `t' = offset + round((t − offset) / passo) × passo` | a 120 BPM con offset 0: 10,3 → **10** e 13,9 → **14**; con offset 0,7: 10,3 → **10,7** |
| **Allinea griglia**: BPM | `BPM = 60 × Battute Sel. / durata della selezione` | 2,000 s con `4` → **120 BPM**; 2,000 s con `8` → **240 BPM** |
| **Allinea griglia**: offset | `offset = IN − (Diventa Bar N° − 1) × passo` | IN 10 s con `1` → **10**; con `3` (passo 1 s) → **8** |
| BPM dal **bordo destro** della cella (Shift = intero) | `BPM = 240 × unità / nuova lunghezza` | cella da 2 s con unità 1 bar → **120 BPM** |
| **Moltiplica** | `BPM × fattore` (virgola o punto) | 120 × `2,3` → **276** |
| **Segui** e playhead | il playhead è a `timeline = audio.currentTime + sample`; il metronomo suona sui `t = offset + k × passo` | a 1/4 bar e 120 BPM: un colpo ogni 0,5 s |
| **metronomo**: passo fra due colpi | `passo = (240 / BPM) × unità_metronomo` (unità: 0,25 = ogni 1/4, 0,5 = 2/4, 1 = battuta, 2 = 2 battute…) | a 120 BPM: 1/4 → **0,5 s** · 2/4 → 1 s · 3/4 → 1,5 s · battuta → 2 s |
| selezione coperta da **Battute Sel.** | `celle coperte = Battute Sel. / 4` | con unità `1 bar`: `4` → una cella/una battuta |

Tre cose da tenere a mente:

1. **`Battute Sel.` conta i quarti**, non le battute: `4` significa «una battuta
   4/4». Per una selezione di due battute scrivi `8`, per una e mezza `6`.
2. **L'unità della griglia non entra nella formula del BPM** (che dipende solo da
   selezione e durata), ma cambia da quanto *sono* le celle: la stessa selezione
   riempie sempre `Battute Sel. / 4` celle, che siano quarti (`1/4 bar`) o
   battute (`1 bar`).
3. **I numeri sono coerenti in ogni direzione**: qualunque cosa tocchi (BPM,
   offset, unità, bordi della cella), il sampler ridisegna griglia, righello,
   metronomo e forma d'onda con la stessa formula — non ci sono "due verità".

> 📐 **Esempio completo** (*60 Hz II*, 60,1 BPM nel database). All'apertura il
> passo a `1 bar` è `240 / 60,1 = ` **3,993 s** e la selezione è `0:00 → 0:30`.
> Se il metronomo a `1/4 bar` non batte a tempo, seleziono una battuta della
> musica, scrivo `4` in *Battute Sel.* e premo *Allinea griglia*: il sampler
> riscrive BPM e offset — da quel momento la griglia disegna esattamente la
> musica che sento, e il BPM che leggo è quello vero da salvare nel database.

## 9. Ritagliare e scaricare

In fondo al sampler ci sono il **formato** (MP3 o WAV) e due pulsanti:

| Pulsante | Nel **sampler del modale** | Nel **player delle card** (Trova Campioni) |
|---|---|---|
| **Scarica selezione** | il taglio non viene eseguito: compare l'avviso *«In modalità standalone, il taglio viene simulato»* e viene scaricato il **file intero** | il taglio viene eseguito **davvero dal backend** (ffmpeg): parte la richiesta, la pagina attende il lavoro e alla fine scarica il file tagliato; lo stato in linea dice `Taglio in corso…` → `✓ Pronto` (oppure l'errore) |
| **Scarica intero** | scarica il file del brano così com'è | idem (eventualmente convertito nel formato scelto) |

Per il taglio vero, quindi, si usa il **tab 🔍 Trova Campioni**: le card dei
sample hanno lo stesso sampler (stesse funzioni, stessa griglia) ma collegate al
backend. Il file ritagliato arriva nella cartella `downloads/` e da lì si scarica
sul Mac. Il taglio tiene conto anche dello spostamento `sample`: quello che
ritagli è **ciò che vedi selezionato sull'onda**, non l'istante grezzo del file.

## 10. I due sampler e le loro differenze

La logica è **la stessa** (grattano lo stesso codice: griglia, snap, TAP,
metronomo, undo), ma ci sono due "posti" in cui il sampler appare e non fanno
esattamente le stesse cose:

| | **Sampler del modale** (🎛 Sampler / 🎛 Apri nel sampler) | **Player delle card** (tab 🔍 Trova Campioni) |
|---|---|---|
| Dove vive | modale `#audio-editor-modal` della pagina `/` | dentro le card dei sample, sempre nella pagina `/` |
| Da dove arriva l'audio | `/stream/<file>`: un file della tua libreria | il file scaricato per quel sample (o un file locale) |
| BPM iniziale | **quello del database** (novità 17/09/2026) | 120: lì il tempo si misura, non si eredita |
| Clic sulla selezione | sposta solo il playhead | sposta il playhead **e avvia la riproduzione** |
| **Scarica selezione** | simulato (scarica il file intero) | **taglio reale** col backend (ffmpeg) |
| Etichetta del pulsante griglia | `Visualizza griglia` / `Nascondi griglia` | `Griglia` |
| Avviso "il sample non è in questo file" | compare se il punto d'apertura non esiste | idem, con il messaggio esteso |

In pratica: **col modale si misura il tempo della libreria** (è ciò per cui è
nato questo lavoro), **con le card si confronta e si ritaglia**.

## 11. Perché il BPM del database può non tornare

Il BPM salvato arriva da un'analisi automatica (Tunebat, oppure ffmpeg/librosa
sul file): è un'**ipotesi**. Ecco le cause in ordine di frequenza, con la
contromisura.

| Sintomo nel sampler | Causa tipica | Cosa fare |
|---|---|---|
| Il metronomo va **al doppio** o **alla metà** dei tuoi colpi | il brano è in *half-time*: l'analisi ha contato i mezzi o i doppi | **Moltiplica** per `2` o per `0,5` e riascolta |
| Il metronomo "gira" su un pezzo shuffle / 6/8 | tempo ternario | prova `1,5` o `0,667` |
| La griglia **tiene** ma è tutta **spostata** | non è il BPM: è l'offset | non toccare il BPM: **Diventa Bar N°**, oppure trascina il **bordo sinistro** della cella, o **Adatta alla griglia** |
| Tiene all'inizio e **perde** dopo 20–30 s | BPM sbagliato di poco (1–2) o drift del master | **Allinea griglia** su una parte centrale (4 o 8 battute) |
| Tiene solo in una sezione | il brano **cambia tempo** (intro rubato, breakdown) | misura la sezione che ti interessa e annotalo nel campo `comment` |
| Il numero misura una **cover** o un'altra versione | il file in libreria è la versione YouTube/cover, non l'originale | il BPM giusto è quello del **file che hai**: misura e salva quello |
| L'analisi ha misurato l'**intro** (parlato, senza batteria) | la parte iniziale non ha un tempo | seleziona una parte con la batteria e usa **Allinea griglia** |

Due dettagli sul database, per non rovinare il lavoro fatto a orecchio:

- **La Verifica non ti cancella il BPM.** Il BPM viene scritto dalla Verifica
  **solo se il campo è vuoto**; se c'è già, il valore viene *confrontato* con
  Tunebat: se la differenza è **più di 2** la riga viene segnata con
  *«⚠️ CONFLITTO BPM: … vs Tunebat … → rosso»* e `bpm_verified` torna a 0, senza
  sovrascrivere il numero.
- **Dichiaralo verificato tu.** Nel modale **✏️ Edit** c'è la casella **BPM
  verificato**: mettila quando il numero l'hai controllato col metronomo o col
  TAP. È il modo per dire «questo l'ho sentito io», ed è coerente con la colonna
  verde/gialla della tabella.

## 12. Dove sta cosa nel codice

Il sampler è **un documento intero dentro una textarea**: la pagina lo crea al
volo e lo monta in un iframe quando apri il modale. I numeri di riga qui sotto
sono quelli di `index (2).html` (il contenuto della textarea inizia alla riga
791, quindi una funzione del documento alla riga *N* sta nel file alla riga
*N + 789*).

| Cosa | Dove |
|---|---|
| Modale del sampler | `index (2).html` riga **780** (`#audio-editor-modal` + `iframe#audio-editor-iframe`) |
| Documento del sampler (markup + tutto il JS) | `index (2).html` righe **790–2889** (`<textarea id="audio-editor-src">`) |
| Apertura del modale | `index (2).html` riga **5201**: `openAudioEditor(url, filename, startSec, bpm)` |
| "Apri nel sampler" (risolve id o file, toast col BPM) | `index (2).html` riga **5224**: `openInSampler(songIdOFile, opts)` |
| Pulsante nella riga del database | dentro `renderDbTable` (riga **4281**), cella azioni (🎛 Sampler accanto a ✂️ Stem / ✏️ Edit) |
| Ricezione dal player (`openSampler`) | `index (2).html` riga **2981** |
| Link diretti `?tab=` / `?sampler=` / `?sampler_file=` | `index (2).html` riga **3017** |
| Voce di menu nel player | `onyx_whosampled.html` riga **2478**, con `samplerUrlFor` (**2489**), `dbSongIdFor` (**2497**), `openInSampler` (**2516**) |
| Handshake col documento (`{action:'load', url, filename, startSec, bpm}`) | documento del sampler, ricezione del messaggio (in coda allo script) |
| Griglia: passo, snap, unità | `getGridStep` **2169** · `snapToGrid` **2174** · `snapTrimToGrid` **2211** · `setBpm` **2181** · `setGridOffset` **2193** · `setGridSubdivision` **2203** |
| **Adatta** e **Allinea griglia** | `snapSelectionToGrid` **1719** · `alignGridToSelection` **1727** |
| BPM dai battiti e dal fattore | `bpmDaTap` **2229** (media pura) · `tapTempo` **2250** · `updateTapLabel` **2243** · `multiplyBpm` **2272** |
| Metronomo e sua unità (menu `#metro-sel-main`) | `stepMetronomo` **2301** (pura) · `accentoBattuta` **2311** (pura) · `etichettaUnita` **2320** (pura) · `getMetroStep` **2330** · `updateMetroStatus` **2336** · `setMetroSubdivision` **2343** · `toggleMetronome` **2351** · `checkMetronome` **2368** · `flashMetronome` **2396** |
| Disegno della griglia e del righello | `updateGridUI` **2409** · `updateRuler` **2435** |
| Selezione di una cella e bordi trascinabili | `selectBarByNumber` **2504** · `deselectBar` **2522** · `updateBarSelectionUI` **2537** · `_startCellBorderDrag` **2577** · `_moveCellBorderDrag` **2605** |
| Modalità sposta, playhead, IN/OUT | `toggleMoveMode` **2680** · `onAudioLayerMouseDown` **2689** · `startPlayheadDrag` **2780** · `applyHandleDrag` **2080** · `startSelDrag` **2093** · `resetTrimStart` **2814** |
| Zoom, scorrimento, trasporto | `setZoom` **1890** · `adjustZoom` **1908** · `onTrimWheel` **1932** · `togglePlay` **1945** · `toggleFollow` **1763** |
| Storico (Undo/Redo) | `pushHistory` **1465** · `applyHistoryState` **1498** · `undoAction` **1521** · `redoAction` **1528** |
| Caricamento del brano | `initPlayer` **1620** (+ `loadedmetadata`: finestra di 30 s, storico, disegno) |
| Taglio reale (player delle card) | `index (2).html` `downloadTrim` → `POST /trim` → `GET /status/<job_id>` → `GET /download-file/<nome>` (in `app (2).py`: righe **2528**, **2395**, **2308**) |
| Test della stima TAP | `test_sampler_tap.py` (`python3 -m unittest -v test_sampler_tap`): esegue `bpmDaTap` con JavaScriptCore su 11 casi |
| Test del metronomo | `test_sampler_metronomo.py` (`python3 -m unittest -v test_sampler_metronomo`): 8 test su `stepMetronomo`, `accentoBattuta` ed `etichettaUnita` (JavaScriptCore) |
| Streaming del file | `app (2).py` riga **2265**: `/stream/<path:filename>` (regge anche le richieste Range) |

## 13. Note, limiti e piccoli trucchi

**Cosa il sampler *non* fa** (per scelta, così non ti sorprende):

- **Non scrive nel database.** Il BPM che misuri vive nel sampler: per salvarlo
  si usa **✏️ Edit** (o la casella *BPM verificato*). Nessuna scrittura
  automatica sulle righe della libreria.
- **Nel modale "Scarica selezione" è simulato** (scarica il file intero): il
  taglio vero sta nelle card del tab 🔍 Trova Campioni.
- **Le impostazioni non si ricordano**: ogni apertura riparte con il BPM del
  database, unità `1 bar`, griglia accesa, zoom 1×, metronomo spento, selezione
  di 30 s dall'inizio.
- **Lo storico non è persistente**: 30 passi in memoria, azzerati cambiando
  brano.
- **Nessuna scorciatoia da tastiera**: tutto a pulsanti e trascinamenti (che
  funzionano anche col dito, su touchscreen).

**Piccoli trucchi che fanno risparmiare tempo**

| Trucco | Perché |
|---|---|
| Lascia la griglia a **1 bar** e metti il metronomo su **`ogni 1/4`** | vedi le battute sulla griglia e senti i quarti: le due unità sono **indipendenti** (prima andavano cambiate insieme) |
| **✂ Sel** su 4 o 8 battute invece di tutto il brano | il tempo si giudica sul giro, non sull'intro |
| **Allinea griglia** su 4 o 8 battute (non su una) | più battute nella selezione = stima del BPM più precisa |
| **Diventa Bar N°** invece di ritoccare l'offset a mano | sposta i numeri del righello dove ti servono, in un colpo |
| Trascina il **bordo destro** della cella finché combacia con la musica | il BPM lo calcola lui (Shift per farlo intero) |
| **Adatta alla griglia** prima di ritagliare | IN/OUT finiscono su tempi "tondi" e il taglio esce pulito |
| Guarda `sample: ±…s` in basso | ti dice se hai spostato l'audio (nella tabella non c'è: è solo nel sampler) |
| Se il pulsante non c'è → **Cmd+Shift+R** | il browser tiene in cache il JavaScript vecchio |
| Batti **8–12 colpi** invece di due o tre | la stima è la media di **tutti** i colpi della sessione: il jitter della mano si annulla e il BPM converge (es. 12 colpi a 0,5 s → 120,00) |
| Guarda il contatore sul pulsante (`🎵 TAP ×N`) | dice su quanti colpi sta mediando: se riparte da ×1 hai battuto fuori tempo |
| I **decimali** del TAP sono reali (es. 187,6) | puoi copiarli nel campo `bpm` con ✏️ Edit senza arrotondarli a mano |

**Verifiche di questa guida (17/09/2026).** I numeri qui sopra non sono
"secondo la documentazione": sono **misurati** in Chrome pilotato da Selenium
dentro l'iframe del sampler, con *60 Hz II* di DJ Shocca (BPM nel database
60,1) — 15 controlli su passo della griglia (3,993 s a 60,1 BPM), snap
(10,3 → 10 e 13,9 → 14 a 120 BPM; 10,3 → 10,7 con offset 0,7), *Allinea griglia*
(2 s con `4` → 120 BPM e offset 10; con `8` e Bar N° 3 → 240 BPM e offset 8),
*Moltiplica* (120 × 2,3 = 276), metronomo, Undo/Redo (90 → 100 → 90, storico di
12 stati) e le cinque suddivisioni a 120 BPM (0,5 · 1 · 2 · 4 · 8 s) — più 8
controlli sull'apertura dal tab Database, dal menu del player, dal link diretto
e su `?sampler_file=`. Il **TAP** ha verifiche sue: 11/11 sulla funzione pura
`bpmDaTap` (JavaScriptCore: 12 colpi a 500 ms → 120; 4 colpi a 320 ms → 187,5;
tocco a 150 ms e a 2,5 s → sessione da riavviare) e 9/9 in Chrome con **clic
reali** sul pulsante (contatore `🎵 TAP ×12`, BPM 120,00 con 12 colpi, 187,6 con
5 colpi a 320 ms, sessione che riparte dopo un tocco fuori tempo e azzerata
quando si scrive il BPM a mano). Anche il **metronomo** ha le sue: 8/8 test sulla
parte pura (`stepMetronomo`, `accentoBattuta`, `etichettaUnita`) e 15/15 in
Chrome, dove i colpi vengono **contati davvero** intercettando
`playMetronomeClick`: a 120 BPM in due battute escono **8 colpi** con `ogni 1/4`,
4 con `ogni 2/4`, 2 con `ogni battuta`, 1 con `ogni 2 battute` — e la **griglia
resta a 1 battuta** (2 s) mentre il metronomo batte i quarti.







