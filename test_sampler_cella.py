"""Test del sampler: il bordo DESTRO della cella selezionata (la barra turchese).

Richiesta di Alessandro (18/09/2026): «è corretto che spostando l'inizio di tale
barra automaticamente trasli tutti, ma potresti fare in modo che se l'utente
cambia solo la fine allora l'inizio rimane lo stesso per tale barra? e si adegui
solo la fine e anche i bpm e la lunghezza degli altri?»

Com'è adesso (e com'era prima, che è il punto):

- **bordo SINISTRO** — al trascinamento si somma l'offset: si sposta la griglia e
  con lei la battuta selezionata e tutte le altre. Era così e **resta così**
  (Alessandro: «è corretto»).
- **bordo DESTRO** — la battuta si allunga o si accorcia, il BPM si rifà
  (`BPM = 240 × unità / lunghezza`) e **l'inizio non si muove**: si sposta
  l'**offset** di quanto serve perché quella battuta cominci ancora nello stesso
  istante, cioè `offset = inizio − (N − 1) × passo`
  (`offsetPerBattutaAncorata`, funzione pura). Le altre celle cambiano lunghezza
  con il nuovo passo.
  **Prima** invece l'offset restava fermo e l'inizio "scappava" di
  `(N − 1) × (passo nuovo − passo vecchio)`: tanto più quanto più avanti era la
  battuta nel brano — e **invisibile con la prima battuta** (N = 1), che è il
  motivo per cui il difetto non si era notato.
- la stessa regola vale nel **player inline delle card** di 🔍 Trova Campioni
  (`applyBarTimeChange`, la copia minificata dentro la pagina): anche lì il bordo
  destro ora àncora l'inizio, così i due player non si comportano diversamente.

Questo file prova:
1. `TestFunzioniPagina` — `offsetPerBattutaAncorata` **eseguita davvero** in
   JavaScriptCore: la battuta 1 (l'offset È l'inizio), le battute in mezzo, il
   passo nullo, i numeri scritti come stringhe, e che l'ancoraggio **torni**
   (`offset + (N − 1) × passo == inizio`) in tutti i casi. Più il caso vero del
   trascinamento (battuta 2 da 10 s: bordo destro a 13 s → 80 BPM, passo 3,
   offset 7) con il confronto con la formula vecchia (che avrebbe dato 11 s).
2. `TestCablaggio` — i sorgenti: il bordo destro non ricalcola più l'inizio dal
   passo (riga che lo faceva scappare), usa la funzione pura, riscrive il campo
   *Offset*, il bordo sinistro continua a traslare tutto, e la stessa formula c'è
   anche nella copia inline delle card.
3. `TestPaginaServita` — l'app viva: `/` serve il documento col codice nuovo (il
   sampler si legge dal disco a ogni richiesta: nessun riavvio) e `/db/stats`
   risponde.

Esecuzione (dalla cartella di SampleLab):
    python3 -m unittest -v test_sampler_cella
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

# (nome, battuta, inizio della battuta, passo nuovo) -> offset atteso
# L'offset è quello che fa COMINCIARE la battuta N in `inizio`:
# offset = inizio − (N − 1) × passo.
CASI = [
    ("prima",           1,    10,   2),      # N = 1: l'offset È l'inizio
    ("terza",           3,    10,   2),
    ("quarta_mezzo",    4,    10,   1.5),
    ("quarantesima",    40,   120,  3),
    ("offset_negativo", 5,    2,    1),
    ("passo_nullo",     3,    10,   0),      # senza griglia non c'è da ancorare
    ("passo_stringa",   3,    10,   "2"),    # arriva dal campo, quindi testo
    ("numeri_stringa",  "3",  "10", 2),
    ("battuta_zero",    0,    10,   2),      # 0 -> si conta come prima battuta
    ("senza_battuta",   None, 10,   2),
    ("inizio_zero",     2,    0,    2.5),
    ("passo_decimali",  3,    7.5,  0.5),
]
ATTESI = [10, 6, 5.5, 3, -2, 10, 6, 6, 10, 10, -2.5, 6.5]


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


def esegui_js(codice, nome_file="/tmp/test_sampler_cella.js"):
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
    """`offsetPerBattutaAncorata` sui casi veri, eseguita in JavaScriptCore."""

    risultati = {}

    @classmethod
    def setUpClass(cls):
        src = leggi(PAGINA)
        js = [estrai_funzione(src, "offsetPerBattutaAncorata")]
        js.append("""
// (nome, battuta, inizio, passo): gli stessi casi scritti in Python.
const casi = %s;
function ancorata(c) {
  const off = offsetPerBattutaAncorata(c[1], c[2], c[3]);
  const n = Math.max(1, Math.round(Number(c[1]) || 1));
  return off + (n - 1) * Number(c[3]) === Number(c[2]);
}
// Il caso vero del trascinamento: battuta 2 selezionata a 10,0000 s con passo
// 2 s (offset 8, 120 BPM). Il bordo destro va a 13 s: la battuta è lunga 3 s,
// quindi 240 / 3 = 80 BPM e passo 3. Formula nuova: offset 10 − 1 × 3 = 7, la
// battuta 2 ricomincia a 10 (l'inizio non si muove). Formula vecchia (offset
// fermo a 8): la battuta 2 partirebbe da 8 + 3 = 11, cioè 1 s più avanti.
const vecchio = 8;
const passoTre = 3;
console.log(JSON.stringify({
  nomi: casi.map(c => c[0]),
  valori: casi.map(c => offsetPerBattutaAncorata(c[1], c[2], c[3])),
  ancorate: casi.map(ancorata),
  scenario: {
    passo: passoTre,
    bpm: 240 / passoTre,
    offset: offsetPerBattutaAncorata(2, 10, passoTre),
    inizio_nuovo: offsetPerBattutaAncorata(2, 10, passoTre) + 1 * passoTre,
    inizio_vecchio: vecchio + 1 * passoTre,
    scappato: (vecchio + 1 * passoTre) - 10
  }
}));
""" % json.dumps([[c[0], c[1], c[2], c[3]] for c in CASI]))
        cls.risultati = esegui_js("\n".join(js))

    def test_la_battuta_1_non_ha_offset_da_correggere(self):
        # Con N = 1 l'offset è l'inizio stesso: è il caso in cui il vecchio
        # comportamento sembrava giusto.
        self.assertEqual(self.risultati["valori"][0], 10)

    def test_offset_delle_altre_battute(self):
        # Tante indietro quante la battuta è avanti: (N − 1) × passo.
        self.assertEqual(self.risultati["nomi"], [c[0] for c in CASI])
        self.assertEqual(self.risultati["valori"], ATTESI)

    def test_l_ancoraggio_torna_sempre(self):
        # La prova che conta: offset + (N − 1) × passo == inizio della battuta.
        # Vale anche col passo nullo, con 0 e coi numeri arrivati come stringhe.
        self.assertEqual(self.risultati["ancorate"], [True] * len(CASI))

    def test_il_caso_del_trascinamento(self):
        # Battuta 2 a 10 s, bordo destro a 13 s: 80 BPM (passo 3) e offset 7.
        s = self.risultati["scenario"]
        self.assertAlmostEqual(s["bpm"], 80, places=9)
        self.assertAlmostEqual(s["offset"], 7, places=9)
        self.assertAlmostEqual(s["inizio_nuovo"], 10, places=9,
                               msg="con la formula nuova l'inizio resta a 10 s")
        self.assertAlmostEqual(s["inizio_vecchio"], 11, places=9,
                               msg="con l'offset fermo sarebbe scappato a 11 s")
        self.assertAlmostEqual(s["scappato"], 1, places=9)


class TestCablaggio(unittest.TestCase):
    """I sorgenti: dove sta la formula e dove NON deve stare."""

    @classmethod
    def setUpClass(cls):
        cls.pagina = leggi(PAGINA)

    def test_la_funzione_pura_c_e_ed_e_una_sola(self):
        self.assertEqual(self.pagina.count("function offsetPerBattutaAncorata("), 1)
        self.assertIn("function offsetPerBattutaAncorata(barNum, startTime, passo) {",
                      self.pagina)

    def test_il_bordo_destro_ancora_l_inizio(self):
        # Il bordo destro del DOCUMENTO del sampler: l'inizio non si ricalcola
        # più dal passo (era la riga che lo faceva scappare) ma resta quello
        # della battuta selezionata; a muoversi è l'offset.
        self.assertEqual(self.pagina.count("_moveCellBorderDrag"), 3,
                         "una definizione + le due chiamate (mouse e touch)")
        self.assertIn("const newOffset = offsetPerBattutaAncorata(state.barNum, state.startTime, updatedStep);",
                      self.pagina)
        self.assertIn("p.gridOffset = newOffset;", self.pagina)
        self.assertIn("document.getElementById(`offset-${key}`).value = newOffset.toFixed(4);",
                      self.pagina)
        self.assertIn("p.selectedBarStartTime = state.startTime;", self.pagina)
        self.assertNotIn("p.selectedBarStartTime = offset + (state.barNum - 1) * updatedStep;",
                         self.pagina,
                         "la formula vecchia (offset fermo) non deve restare")

    def test_il_bordo_sinistro_trasla_tutto(self):
        # «è corretto che spostando l'inizio di tale barra automaticamente
        # trasli tutti»: il bordo sinistro somma il trascinamento all'offset.
        self.assertIn("let newOffset = state.origOffset + dSec;", self.pagina)
        self.assertIn("p.selectedBarStartTime = newOffset + (state.barNum - 1) * step;",
                      self.pagina)
        # la funzione pura si chiama UNA volta sola: il ramo sinistro non la usa
        self.assertEqual(self.pagina.count("offsetPerBattutaAncorata("), 2,
                         "una definizione + la chiamata del bordo destro")

    def test_la_maniglia_lo_dice(self):
        # Il suggerimento (tooltip) delle due maniglie: quello del righello...
        self.assertIn("rightH.title = 'Trascina: allunga o accorcia la battuta (BPM)",
                      self.pagina)
        self.assertIn("leftH.title = 'Trascina: sposta offset';", self.pagina)
        # ...e quello dei bordi turchesi sulla forma d'onda (stesso testo)
        self.assertIn('id="cell-border-right-main" style="display:none" '
                      'title="Trascina: allunga o accorcia la battuta (BPM) — il suo inizio resta fermo"',
                      self.pagina)
        self.assertIn('id="cell-border-left-main" style="display:none" '
                      'title="Trascina: sposta offset"',
                      self.pagina)

    def test_anche_il_player_delle_card_ancora_l_inizio(self):
        # `applyBarTimeChange` è la copia minificata nella pagina (player inline
        # delle card di 🔍 Trova Campioni): lì il bordo destro parte da
        # `startTime` (l'inizio della battuta) e riscrive l'offset.
        self.assertIn("function applyBarTimeChange(", self.pagina)
        self.assertIn("p.gridOffset=startTime-(barIndex-1)*getGridStep(key);", self.pagina)
        self.assertIn("if(offInput)offInput.value=p.gridOffset.toFixed(4);", self.pagina)
        # e il bordo sinistro, lì, continua a spostare la griglia
        self.assertIn("const newOffset=newTime-(barIndex-1)*step;", self.pagina)


def app_is_up(url):
    try:
        import urllib.request
        urllib.request.urlopen(url + "/db/stats", timeout=3)
        return True
    except Exception:
        return False


@unittest.skipUnless(app_is_up(SAMPLELAB_URL), "app non attiva su " + SAMPLELAB_URL)
class TestPaginaServita(unittest.TestCase):
    """L'app viva: la pagina servita contiene il codice nuovo."""

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

    def test_la_pagina_serve_il_sampler_con_la_formula_nuova(self):
        stato, corpo = self.risposta("/")
        self.assertEqual(stato, 200)
        self.assertIn("function offsetPerBattutaAncorata(barNum, startTime, passo)",
                      corpo)
        self.assertIn("const newOffset = offsetPerBattutaAncorata(state.barNum, state.startTime, updatedStep);",
                      corpo)
        self.assertNotIn("p.selectedBarStartTime = offset + (state.barNum - 1) * updatedStep;",
                         corpo)

    def test_il_sampler_si_apre_sulla_canzone(self):
        stato, corpo = self.risposta("/?sampler=song_7553a924d202")
        self.assertEqual(stato, 200)
        self.assertIn("audio-editor-src", corpo)

    def test_db_stats(self):
        stato, corpo = self.risposta("/db/stats")
        self.assertEqual(stato, 200)
        self.assertGreater(json.loads(corpo)["songs"], 0)
