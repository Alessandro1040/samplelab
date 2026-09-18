"""Test del sampler: lo scorrimento ORIZZONTALE (touchpad) e la barra di scorrimento.

Richiesta di Alessandro (18/09/2026), guardando *Hustler's Ambition* nel player:
«puoi fare in modo che se scorro col touchpad a destra o sinistra sopra le barre
nel player … va a destra oppure a sinistra? cioè che si sposta scorrendo? oltre a
questo magari aggiungi un indicatore di posizione sotto, una sorta di barra di
scorrimento».

Com'è adesso il sampler:
- **touchpad (due dita) a destra/sinistra sopra l'onda, sopra il righello o sulla
  barra**: la vista scorre e il contenuto **segue le dita** (1:1 con i pixel mossi,
  quindi a zoom 2 sono metà dei secondi rispetto a zoom 1);
- la **rotella del mouse** manda delta "a scatto" (≥ 40 px) e resta a **3 s per
  tacca** come prima; un delta piccolo (touchpad) è invece proporzionale, così non
  «salta» di 3 s a ogni evento;
- scorrere a mano spegne **⟳ Segui** (come già faceva la rotella);
- sotto la forma d'onda c'è la **barra di scorrimento**: fascia gialla = selezione
  IN/OUT, **riquadro turchese** = finestra visibile (si trascina per scorrere),
  **lineetta bianca** = playhead (l'indicatore di posizione). Il clic sulla barra
  **centra** la vista lì. A zoom 1 il riquadro riempie tutto (non c'è niente da
  scorrere) e resta la lineetta.

Questo file prova:
1. `TestFunzioniPagina` — le funzioni **pure** che stanno dietro la barra, eseguite
   davvero in JavaScriptCore: `secondiDaScorrimento` (1:1 col dito, W nullo,
   stringhe), `clampScrollOffset` (i due estremi, zoom 1, zoom 4),
   `timbroScorrimento` (larghezza e posizione del riquadro, anche oltre il fondo),
   `offsetPerCentratura` (al centro, agli estremi), `secondiDaCorsa` (il
   trascinamento del riquadro) e `frazionePosizione` (la lineetta).
2. `TestCablaggio` — i sorgenti: markup e CSS della barra, i tre agganci
   (`applyScroll`, `updatePlayhead`, `updateTrimUI`), il wheel che legge `deltaX`,
   e la stessa gestione del touchpad nel player inline delle card.
3. `TestPaginaServita` — l'app viva: `/` serve il documento con la barra.

Esecuzione (dalla cartella di SampleLab):
    python3 -m unittest -v test_sampler_scroll
"""
import json
import os
import re
import shutil
import subprocess
import unittest

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PAGINA = os.path.join(BASE_DIR, "index (2).html")
SAMPLELAB_URL = os.environ.get("SAMPLELAB_URL", "http://localhost:5070")
HA_OSASCRIPT = shutil.which("osascript") is not None

# Valori dipendenti dalla finestra: (nome, durata, W, vw)
# vw = finestra visibile (px), W = LARGHEZZA TOTALE dell'onda = vw × zoom.
FINESTRE = [
    ("zoom1", 200, 800, 800),      # tutto il brano visibile: niente da scorrere
    ("zoom2", 200, 1600, 800),
    ("zoom4", 120, 3200, 800),
]

FUNZIONI = ["secondiDaScorrimento", "clampScrollOffset", "timbroScorrimento",
            "offsetPerCentratura", "secondiDaCorsa", "frazionePosizione"]


def leggi(percorso):
    with open(percorso, encoding="utf-8") as fh:
        return fh.read()


def estrai_funzione(src, nome):
    m = re.search(r"(?:async\s+)?function\s+" + re.escape(nome) + r"\s*\(", src)
    if not m:
        raise AssertionError("funzione %s assente in %s" % (nome, PAGINA))
    i = src.index("{", m.end() - 1)
    liv, j = 0, i
    while j < len(src):
        if src[j] == "{":
            liv += 1
        elif src[j] == "}":
            liv -= 1
            if liv == 0:
                return src[m.start():j + 1]
        j += 1
    raise AssertionError("graffe non bilanciate in %s" % nome)


def esegui_js(codice, nome_file="/tmp/test_sampler_scroll.js"):
    with open(nome_file, "w", encoding="utf-8") as out:
        out.write(codice + "\n0;\n")
    r = subprocess.run(["osascript", "-l", "JavaScript", nome_file],
                       capture_output=True, text=True)
    righe = ((r.stdout or "") + (r.stderr or "")).strip().splitlines()
    if not righe:
        raise AssertionError("nessun output da JavaScriptCore: %s" % (r.stderr or "")[:200])
    return json.loads(righe[-1])


@unittest.skipUnless(HA_OSASCRIPT, "JavaScriptCore (osascript) non disponibile")
class TestFunzioniPagina(unittest.TestCase):
    """Le funzioni pure della barra di scorrimento, eseguite davvero."""

    risultati = {}

    @classmethod
    def setUpClass(cls):
        src = leggi(PAGINA)
        js = [estrai_funzione(src, n) for n in FUNZIONI]
        js.append("""
function clamp(v, min, max) { return Math.max(min, Math.min(max, v)); }
// La corsa massima (in secondi) è ciò che clampScrollOffset restituisce al limite.
function massimoScorrimento(durata, W, vw) { return clampScrollOffset(1e9, durata, W, vw); }
const finestre = %s;
console.log(JSON.stringify({
  scorrimento: [
    ['destra',    secondiDaScorrimento(100, 200, 800)],
    ['sinistra',  secondiDaScorrimento(-100, 200, 800)],
    ['fermo',     secondiDaScorrimento(0, 200, 800)],
    ['senza_W',   secondiDaScorrimento(50, 200, 0)],
    ['senza_dur', secondiDaScorrimento(50, 0, 800)],
    ['stringa',   secondiDaScorrimento('100', 200, 800)],
    ['niente',    secondiDaScorrimento(undefined, 200, 800)],
    ['zoom2',     secondiDaScorrimento(37, 146.448254, 1600)],
    ['fine',      secondiDaScorrimento(3, 200, 1600)]
  ],
  clamp: [
    ['sotto',   clampScrollOffset(-5, 200, 1600, 800)],
    ['dentro',  clampScrollOffset(40, 200, 1600, 800)],
    ['oltre',   clampScrollOffset(150, 200, 1600, 800)],
    ['zoom1',   clampScrollOffset(40, 200, 800, 800)],
    ['zoom4',   clampScrollOffset(200, 120, 3200, 800)],
    ['stringa', clampScrollOffset('40', 200, 1600, 800)],
    ['niente',  clampScrollOffset(undefined, 200, 1600, 800)]
  ],
  timbro: finestre.map(f => {
    const W = f[2], vw = f[3];
    const max = massimoScorrimento(f[1], W, vw);
    const t0 = timbroScorrimento(0, f[1], W, vw);
    const tMax = timbroScorrimento(max, f[1], W, vw);
    const tMeta = timbroScorrimento(max / 2, f[1], W, vw);
    return [f[0], t0.larghezza, t0.sinistra, tMax.sinistra, tMeta.sinistra];
  }),
  timbro_fuori: [
    ['oltre_il_fondo', timbroScorrimento(999, 200, 1600, 800).sinistra],
    ['negativo',       timbroScorrimento(-10, 200, 1600, 800).sinistra],
    ['senza_W',        timbroScorrimento(10, 200, 0, 800).larghezza],
    ['zoom4_meta',     timbroScorrimento(45, 120, 3200, 800).sinistra]
  ],
  centratura: [
    ['centro',  offsetPerCentratura(100, 200, 1600, 800)],
    ['inizio',  offsetPerCentratura(10, 200, 1600, 800)],
    ['fine',    offsetPerCentratura(195, 200, 1600, 800)],
    ['zoom1',   offsetPerCentratura(100, 200, 800, 800)],
    ['zoom4',   offsetPerCentratura(60, 120, 3200, 800)]
  ],
  corsa: [
    ['meta',       secondiDaCorsa(0.5, 200, 1600, 800)],
    ['inizio',     secondiDaCorsa(0, 200, 1600, 800)],
    ['fondo',      secondiDaCorsa(1, 200, 1600, 800)],
    ['oltre',      secondiDaCorsa(2, 200, 1600, 800)],
    ['sotto',      secondiDaCorsa(-1, 200, 1600, 800)],
    ['zoom1',      secondiDaCorsa(0.5, 200, 800, 800)],
    ['zoom4_meta', secondiDaCorsa(0.5, 120, 3200, 800)]
  ],
  frazione: [
    ['inizio',    frazionePosizione(0, 200)],
    ['quarto',    frazionePosizione(50, 200)],
    ['fondo',     frazionePosizione(200, 200)],
    ['oltre',     frazionePosizione(250, 200)],
    ['negativo',  frazionePosizione(-5, 200)],
    ['senza_dur', frazionePosizione(50, 0)],
    ['niente',    frazionePosizione(undefined, 200)]
  ]
}));
""" % json.dumps([list(f) for f in FINESTRE]))
        cls.risultati = esegui_js("\n".join(js))

    def test_scorrimento_proporzionale(self):
        # 100 px su un'onda di 800 px per 200 s: un ottavo del brano, 25 s.
        s = dict(self.risultati["scorrimento"])
        self.assertAlmostEqual(s["destra"], 25, places=9)
        self.assertAlmostEqual(s["sinistra"], -25, places=9,
                               msg="verso sinistra si torna indietro")
        self.assertAlmostEqual(s["fermo"], 0, places=9)
        self.assertAlmostEqual(s["senza_W"], 0, places=9, msg="senza larghezza non si scorre")
        self.assertAlmostEqual(s["senza_dur"], 0, places=9)
        self.assertAlmostEqual(s["stringa"], 25, places=9,
                               msg="il delta può arrivare come stringa")
        self.assertAlmostEqual(s["niente"], 0, places=9)
        # A zoom 2 (1600 px per 146,448254 s) 37 px sono 3,386616 s: metà dei
        # secondi che sarebbero a zoom 1 — il contenuto segue le dita.
        self.assertAlmostEqual(s["zoom2"], 3.386616, places=6)
        self.assertAlmostEqual(s["fine"], 0.375, places=9, msg="3 px su 1600 per 200 s")

    def test_fin_dove_si_puo_scorrere(self):
        c = dict(self.risultati["clamp"])
        self.assertAlmostEqual(c["sotto"], 0, places=9, msg="non si va prima dell'inizio")
        self.assertAlmostEqual(c["dentro"], 40, places=9)
        self.assertAlmostEqual(c["oltre"], 100, places=9,
                               msg="l'ultima schermata: (1600-800)/1600 × 200 = 100 s")
        self.assertAlmostEqual(c["zoom1"], 0, places=9,
                               msg="a zoom 1 si vede tutto: nulla da scorrere")
        self.assertAlmostEqual(c["zoom4"], 90, places=9,
                               msg="a zoom 4: (3200-800)/3200 × 120 = 90 s")
        self.assertAlmostEqual(c["stringa"], 40, places=9)
        self.assertAlmostEqual(c["niente"], 0, places=9)

    def test_il_riquadro_della_finestra(self):
        # (nome, larghezza, sinistra a inizio, sinistra a fondo corsa, sinistra a metà)
        t = {riga[0]: riga[1:] for riga in self.risultati["timbro"]}
        self.assertEqual(t["zoom1"], [1, 0, 0, 0],
                         "a zoom 1 il riquadro riempie la barra: nulla da scorrere")
        self.assertEqual(t["zoom2"], [0.5, 0, 0.5, 0.25],
                         "a zoom 2 il riquadro è metà barra e corre per l'altra metà")
        self.assertEqual(t["zoom4"], [0.25, 0, 0.75, 0.375],
                         "a zoom 4 il riquadro è un quarto della barra")

    def test_il_riquadro_non_esce_dalla_barra(self):
        f = dict(self.risultati["timbro_fuori"])
        self.assertAlmostEqual(f["oltre_il_fondo"], 0.5, places=9,
                               msg="oltre la fine si ferma contro il bordo destro")
        self.assertAlmostEqual(f["negativo"], 0, places=9,
                               msg="prima dell'inizio si ferma contro il bordo sinistro")
        self.assertAlmostEqual(f["senza_W"], 1, places=9)
        self.assertAlmostEqual(f["zoom4_meta"], 0.375, places=9)

    def test_clic_che_centra_la_vista(self):
        c = dict(self.risultati["centratura"])
        self.assertAlmostEqual(c["centro"], 50, places=9,
                               msg="100 s al centro di una schermata da 50 s: offset 50")
        self.assertAlmostEqual(c["inizio"], 0, places=9, msg="prima dell'inizio non si va")
        self.assertAlmostEqual(c["fine"], 100, places=9, msg="l'ultima schermata")
        self.assertAlmostEqual(c["zoom1"], 0, places=9, msg="a zoom 1 non c'è niente da centrare")
        self.assertAlmostEqual(c["zoom4"], 45, places=9, msg="a zoom 4 la schermata è 15 s")

    def test_trascinamento_del_riquadro(self):
        c = dict(self.risultati["corsa"])
        self.assertAlmostEqual(c["meta"], 50, places=9, msg="metà corsa = 50 s su 100")
        self.assertAlmostEqual(c["inizio"], 0, places=9)
        self.assertAlmostEqual(c["fondo"], 100, places=9)
        self.assertAlmostEqual(c["oltre"], 100, places=9, msg="la corsa si ferma a 1")
        self.assertAlmostEqual(c["sotto"], 0, places=9, msg="e non va sotto 0")
        self.assertAlmostEqual(c["zoom1"], 0, places=9)
        self.assertAlmostEqual(c["zoom4_meta"], 45, places=9)

    def test_la_lineetta_del_playhead(self):
        f = dict(self.risultati["frazione"])
        self.assertAlmostEqual(f["inizio"], 0, places=9)
        self.assertAlmostEqual(f["quarto"], 0.25, places=9)
        self.assertAlmostEqual(f["fondo"], 1, places=9)
        self.assertAlmostEqual(f["oltre"], 1, places=9, msg="oltre la fine resta al fondo")
        self.assertAlmostEqual(f["negativo"], 0, places=9)
        self.assertAlmostEqual(f["senza_dur"], 0, places=9)
        self.assertAlmostEqual(f["niente"], 0, places=9)


class TestCablaggio(unittest.TestCase):
    """I sorgenti: la barra c'è, è agganciata, e il wheel legge il touchpad."""

    @classmethod
    def setUpClass(cls):
        cls.pagina = leggi(PAGINA)

    def test_la_barra_e_nel_markup(self):
        for pezzo in ('class="scroll-bar" id="sb-main"',
                      'class="scroll-track" id="sbt-main"',
                      'class="scroll-sel" id="sbs-main"',
                      'class="scroll-window" id="sbw-main"',
                      'class="scroll-playhead" id="sbp-main"'):
            self.assertIn(pezzo, self.pagina, "manca %r" % pezzo)
        # sta SOTTO la forma d'onda (dopo il trim-viewport, prima della riga IN→OUT)
        onda = self.pagina.index('class="trim-viewport" id="tv-main"')
        barra = self.pagina.index('class="scroll-bar" id="sb-main"')
        riga = self.pagina.index('class="trim-time-row"')
        self.assertLess(onda, barra)
        self.assertLess(barra, riga)
        # e si trascina (mouse e dito): il clic sulla barra centra
        self.assertIn("onmousedown=\"startScrollDrag(event,'main')\"", self.pagina)
        self.assertIn("ontouchstart=\"startScrollDragTouch(event,'main')\"", self.pagina)

    def test_il_css_della_barra(self):
        for pezzo in (".scroll-bar {", ".scroll-track {", ".scroll-sel {",
                      ".scroll-window {", ".scroll-window.dragging {",
                      ".scroll-playhead {"):
            self.assertIn(pezzo, self.pagina, "manca %r nel CSS" % pezzo)

    def test_i_tre_agganci(self):
        # La barra si aggiorna quando ci si sposta, quando si muove il playhead
        # (60 fps) e quando cambia la selezione (la fascia gialla).
        self.assertIn("updateScrollBar(key);   // la barra dice dove ci si è spostati", self.pagina)
        self.assertIn("aggiornaIndicatorePosizione(key);   // la lineetta sulla barra di scorrimento",
                      self.pagina)
        self.assertIn("updateScrollBar(key);   // la fascia gialla della barra segue la selezione",
                      self.pagina)
        self.assertEqual(self.pagina.count("function updateScrollBar("), 1)
        self.assertEqual(self.pagina.count("function aggiornaIndicatorePosizione("), 1)

    def test_il_wheel_legge_il_touchpad(self):
        # Lo scorrimento orizzontale (deltaX) e i delta piccoli sono proporzionali;
        # la rotella a scatti resta a 3 s per tacca.
        self.assertIn("const dx = e.deltaX || 0;", self.pagina)
        self.assertIn("if (Math.abs(dx) > Math.abs(dy)) dSec = secondiDaScorrimento(dx, dur, W);",
                      self.pagina)
        self.assertIn("const TACCA_PX = 40;", self.pagina)
        self.assertIn("p.scrollOffset = clampScrollOffset(p.scrollOffset + dSec, dur, W, vw);",
                      self.pagina)
        self.assertNotIn("p.scrollOffset = clamp(p.scrollOffset + (e.deltaY > 0 ? 3 : -3), 0, p.audio.duration || 0);",
                         self.pagina, "la vecchia rotella (3 s sempre) non deve restare")
        # il wheel è agganciato a onda, righello e barra
        self.assertIn('<div class="ruler-scroll-container" id="ruler-scroll-main" onwheel="onTrimWheel(event,\'main\')">',
                      self.pagina)
        self.assertIn('onwheel="onTrimWheel(event,\'main\')">\n          <div class="scroll-sel"',
                      self.pagina)

    def test_le_funzioni_pure_sono_una_sola_volta(self):
        for nome in FUNZIONI:
            self.assertEqual(self.pagina.count("function %s(" % nome), 1,
                             "%s definita più di una volta" % nome)

    def test_anche_il_player_delle_card_legge_il_touchpad(self):
        # La copia minificata nella pagina (player inline delle card): stesso
        # comportamento per lo scorrimento, con il suo aiuto sui limiti.
        self.assertIn("function maxScrollSec(key){", self.pagina)
        self.assertIn("dx=e.deltaX||0,dy=e.deltaY||0", self.pagina)
        self.assertIn("Math.abs(dx)>Math.abs(dy)", self.pagina)
        self.assertIn("onwheel=\"onTrimWheel(event,'${key}')\"", self.pagina)


def app_is_up(url):
    try:
        import urllib.request
        urllib.request.urlopen(url + "/db/stats", timeout=3)
        return True
    except Exception:
        return False


@unittest.skipUnless(app_is_up(SAMPLELAB_URL), "app non attiva su " + SAMPLELAB_URL)
class TestPaginaServita(unittest.TestCase):
    """L'app viva: il documento servito ha la barra di scorrimento."""

    @staticmethod
    def risposta(path):
        import urllib.error
        import urllib.request
        req = urllib.request.Request(SAMPLELAB_URL + path, method="GET")
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                return r.status, r.read().decode("utf-8", "replace")
        except urllib.error.HTTPError as e:
            return e.code, e.read().decode("utf-8", "replace")

    def test_la_pagina_serve_la_barra(self):
        stato, corpo = self.risposta("/")
        self.assertEqual(stato, 200)
        for pezzo in ('id="sb-main"', 'id="sbw-main"', 'id="sbp-main"',
                      "function updateScrollBar(key)", "function secondiDaScorrimento("):
            self.assertIn(pezzo, corpo, "manca %r nella pagina servita" % pezzo)

    def test_db_stats(self):
        stato, corpo = self.risposta("/db/stats")
        self.assertEqual(stato, 200)
        self.assertGreater(json.loads(corpo)["songs"], 0)
