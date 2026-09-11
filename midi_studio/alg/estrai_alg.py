#!/usr/bin/env python3
"""Rigenera alg/fortissimo_alg.js estraendo le funzioni da extractor.html.

Le funzioni di calcolo vengono copiate **verbatim** (graffe bilanciate, quindi
include anche le funzioni annidate come p32at dentro writeMidi); la testa del
file (header + stato + callback opzionali) resta quella già presente.

Uso:  python3 midi_studio/alg/estrai_alg.py
"""
import os
import re

ALG_DIR = os.path.dirname(os.path.abspath(__file__))
BASE = os.path.dirname(ALG_DIR)
SRC = os.path.join(BASE, "extractor.html")
OUT = os.path.join(ALG_DIR, "fortissimo_alg.js")
MARK = "function sl(ms) { return new Promise(r => setTimeout(r, ms)); }"

DA_ESTRARRE = ["specgram", "fftMag", "autoK", "kmeans", "silhouette", "wiener",
               "classify", "features", "transcribe", "yin", "extract", "proc",
               "recon", "siSdr", "mse", "corr", "writeMidi", "writeMultiMidi", "writeWav"]

html = open(SRC, encoding="utf-8").read()
linee = re.search(r"<script>(.*?)</script>", html, re.S).group(1).split("\n")


def blocco(nome):
    start = next(i for i, l in enumerate(linee) if l.startswith("function " + nome + "("))
    depth, iniziato, out = 0, False, []
    for i in range(start, len(linee)):
        out.append(linee[i])
        for ch in linee[i]:
            if ch == "{":
                depth += 1
                iniziato = True
            elif ch == "}":
                depth -= 1
        if iniziato and depth <= 0:
            return "\n".join(out)
    raise SystemExit("graffe non bilanciate in " + nome)


corpi = []
for nome in DA_ESTRARRE:
    corpo = blocco(nome)
    corpi.append(corpo)
    print(f"  {nome:<16} {len(corpo):>5} caratteri")

# ── tesi (header+stato), coda (analizza+export) e funzioni estratte ──────────
testo_vecchio = open(OUT, encoding="utf-8").read()
assert MARK in testo_vecchio, "testa non riconosciuta (function sl): il file è stato modificato?"
testa = testo_vecchio.split(MARK)[0] + MARK + "\n"

ancora = "// INGRESSO UNICO: analizza()"
assert ancora in testo_vecchio, "coda (analizza) non trovata: il file è stato modificato?"
fine_riga = testo_vecchio.rindex("\n", 0, testo_vecchio.index(ancora))   # riga prima dell'ancora
inizio_coda = testo_vecchio.rindex("\n", 0, fine_riga) + 1               # la riga con "// ═══"
coda = testo_vecchio[inizio_coda:]

open(OUT, "w", encoding="utf-8").write(testa + "\n".join(corpi) + "\n\n" + coda)
print(f"\nscritto {OUT}: {len(open(OUT, encoding='utf-8').read().splitlines())} righe")
