# Prompt da dare all'AI (copia-incolla)

> Allego un file JavaScript **autonomo, senza dipendenze e senza DOM**:
> `fortissimo_alg.js`. Contiene un algoritmo completo che, dato un brano audio
> mono (`Float32Array` + sample rate), **stima in quante sorgenti/strumenti è
> composto**, le **separa**, **trascrive le note** di ogni sorgente (YIN +
> spectral flux) come MIDI, **estrae un campione one-shot** per sorgente,
> **ricostruisce il mix** da note + campioni e ne **misura la qualità**
> (SI-SDR / MSE / correlazione). Ingresso unico:
> `await analizza(audio, { sr, maxK, onsetSigma, minNoteMs, onLog, onProgress })`.
>
> **Cosa voglio**: migliorare (1) la stima del numero di sorgenti, (2) la qualità
> della separazione, (3) la trascrizione MIDI, **senza cambiare** la firma di
> `analizza()` né le chiavi dell'oggetto restituito.
>
> **Vincoli**
> - JS puro, nessuna dipendenza esterna, niente DOM: deve girare in browser e in Node.
> - Mantieni le funzioni esportate: `analizza`, `writeMidi`, `writeMultiMidi`, `writeWav`.
> - Performance: gira in un thread solo; evita algoritmi O(N²) per frame (YIN attuale).
> - Determinismo: stesso input → stesso output (oggi `kmeans()` usa `Math.random()`).
>
> **Come verificare**: le misure attuali sono note. Audio di prova sintetico:
> 2,5 s → 4 sorgenti, 31 note, SI-SDR ≈ −45 dB, 1,15 s di calcolo; 6 s → 4
> sorgenti, 70 note, SI-SDR ≈ −39,6 dB, 2,78 s. Brano vero di 150 s → 2 sorgenti,
> 60 note, SI-SDR −56 dB, 50 s. C'è anche un banco di prova web (`alg_test.html`)
> che esegue l'algoritmo e stampa il riepilogo, con download di MIDI/WAV.
>
> **Difetti misurati da correggere** (dettagli nel README allegato):
> 1. non deterministico (`kmeans` con random init);
> 2. `classify()` etichetta tutto `Synth/FX` sul materiale di prova;
> 3. `autoK()` sceglie K=2 sui mix densi (servono feature più informative);
> 4. maschera solo sul modulo dello spettro, senza fase → SI-SDR basso;
> 5. YIN O(N²) per frame e pochissime note sui mix densi;
> 6. one-shot tagliato a 1,2 s senza allineamento al pitch;
> 7. solo input mono, nessun ricampionamento;
> 8. nessun test automatico.
>
> **Consegna**: il file modificato + una nota con, per ogni modifica, il risultato
> misurato sul materiale di prova (così vediamo subito se migliora davvero).

## File da allegare

1. `fortissimo_alg.js` (l'algoritmo)
2. questo `README.md` (descrizione, pipeline, API, difetti misurati)
3. `PROMPT.md` (il testo qui sopra)
