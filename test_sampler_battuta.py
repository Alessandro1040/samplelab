"""Test della ricerca della battuta: 🎯 Trova la battuta + trim CELESTE + 💾 Salva BPM.

Richiesta di Alessandro (18/09/2026): «il rilevatore automatico di BPM fa davvero
cagare … trova nel brano dove sta l'inizio della battuta … il pulsante find bpm
non deve più esistere … il trim di cui ho parlato deve essere celeste … i bpm
verranno salvati in base a quel trim, quell'inizio e quella fine».

Com'è fatto ora:
- il pulsante **🎯 Trova la battuta** chiama `POST /beat/bar` (app (2).py), che
  trova DOVE comincia la battuta — il primo colpo forte dove il tempo tiene:
  l'entrata della batteria, il drop — e la sua fine;
- il risultato finisce nel **trim celeste** (indipendente dal trim giallo del
  sample), i cui estremi si trascinano liberamente: **il BPM è 60 × quarti /
  durata della battuta**, quindi si aggiorna mentre trascini;
- **🔁 Battuta** fa girare solo quel trim (per sentire se va fluido a tempo) e
  **💾 Salva BPM** scrive il BPM nel database della canzone aperta;
- la vecchia stima automatica «🔎 BPM & Key» (Tunebat/librosa) **non c'è più**.

Questo file prova:
1. `TestBattutaSuonoSintetico` — l'algoritmo sulle funzioni pure dell'app vera
   (importlib: il nome «app (2).py» con lo spazio non si importa) con un pattern
   4/4 generato in numpy e 20 s di intro SENZA batteria: è il caso che il vecchio
   rilevatore sbagliava (misurava l'intro, dimezzava o raddoppiava).
2. `TestFunzioniPagina` — `bpmDaBattuta`, `barTrimClamp`, `etichettaBattuta`
   estratte dal documento del sampler ed eseguite in JavaScriptCore.
3. `TestCablaggio` — markup, stili e handler: trim celeste, tre pulsanti, loop a
   tre modalità, messaggio `saveBpm` verso la pagina, sparizione della stima,
   URL ASSOLUTA del backend (vedi la nota qui sotto).
4. `TestEndpointVivo` — `POST /beat/bar` sull'app attiva con un file vero della
   libreria (se c'è): 200 con battuta sensata, 404 per un file inesistente.

Nota del 18/09/2026 — «non funziona *Trova la battuta*, compare `Failed to
execute 'fetch' on 'Window': Failed to parse URL from /beat/bar`»: il documento
del sampler viene montato in un iframe con `src` = **blob:** (la pagina lo prende
da una `<textarea>`), e in un documento `blob:` la base NON è http: una `fetch`
con URL **relativa** non parte nemmeno, anche col backend attivo. Il backend era
sano (`POST /beat/bar` rispondeva 400/404 correttamente) e l'audio già caricava
perché l'URL arrivava risolto dal parent (`new URL(e.data.url, e.origin)`).
Ora `trovaBattuta` usa `urlBackend('/beat/bar')` — assoluto, costruito con
l'origine che la pagina manda nel messaggio `'load'` (`window.location.origin`,
dai due punti che montano il sampler: `openAudioEditor` e `embedAudioEditorX`) —
e in coda al documento del sampler ci sono le due funzioni pure `origineHttp` e
`urlBackend`.

Secondo difetto, scoperto provando il pulsante DAL VIVO dopo il primo fix (i test
non lo vedevano perché la `load` la mandavano loro e l'endpoint lo chiamavano con
un nome file preso dal database): al sampler arrivava il **titolo** della canzone
al posto del **nome del file** (`openInSampler` passava `label` dove ci vuole
`local_file`, e `loadSampleXEditor` faceva lo stesso con `embedAudioEditorX`), così
la risposta era «File non trovato». Ora il messaggio `'load'` porta `filename`
(il file in `downloads/`, per 🎯 e per «Scarica selezione») **e** `etichetta` (il
nome da mostrare in testa al sampler, che resta il titolo della canzone).

Esecuzione (dalla cartella di SampleLab):
    python3 -m unittest -v test_sampler_battuta
"""
import importlib.util
import json
import os
import re
import shutil
import subprocess
import unittest

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
APP_PATH = os.path.join(BASE_DIR, "app (2).py")
PAGINA = os.path.join(BASE_DIR, "index (2).html")
DOWNLOAD = os.path.join(BASE_DIR, "downloads")
SAMPLELAB_URL = os.environ.get("SAMPLELAB_URL", "http://localhost:5070")
HA_OSASCRIPT = shutil.which("osascript") is not None


def load_app():
    spec = importlib.util.spec_from_file_location("samplelab_app2_battuta", APP_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


APP = load_app()


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


def esegui_js(codice, nome_file="/tmp/test_sampler_battuta.js"):
    with open(nome_file, "w", encoding="utf-8") as out:
        out.write(codice + "\n0;\n")
    r = subprocess.run(["osascript", "-l", "JavaScript", nome_file],
                       capture_output=True, text=True)
    righe = ((r.stdout or "") + (r.stderr or "")).strip().splitlines()
    if not righe:
        raise AssertionError("nessun output da JavaScriptCore: %s" % (r.stderr or "")[:200])
    return json.loads(righe[-1])


def batteria_sintetica(bpm=120.0, intro=20.0, totale=40.0, sr=22050):
    """Pattern 4/4 generato: cassa su 1 e 3, rullante su 2 e 4, hi-hat sui quarti.

    L'intro (20 s) è silenzio: serve a provare che la battuta non comincia là.
    """
    import numpy as np
    n = int(sr * totale)
    x = np.zeros(n, dtype=np.float32)
    beat = 60.0 / bpm
    t, k = intro, 0
    while t < totale - beat:
        pos, quarto = int(t * sr), k % 4
        if quarto in (0, 2):        # cassa
            lung = int(0.10 * sr)
            if pos + lung < n:
                tt = np.arange(lung) / sr
                x[pos:pos + lung] += (np.sin(2 * np.pi * 55 * tt) * np.exp(-25 * tt) * 0.9).astype(np.float32)
        if quarto in (1, 3):        # rullante
            lung = int(0.08 * sr)
            if pos + lung < n:
                rng = np.random.default_rng(1000 + k)
                x[pos:pos + lung] += (rng.standard_normal(lung) * np.exp(-30 * np.arange(lung) / sr) * 0.5).astype(np.float32)
        lung = int(0.02 * sr)       # hi-hat
        if pos + lung < n:
            rng = np.random.default_rng(2000 + k)
            x[pos:pos + lung] += (rng.standard_normal(lung) * np.exp(-80 * np.arange(lung) / sr) * 0.2).astype(np.float32)
        t += beat
        k += 1
    return x

class TestBattutaSuonoSintetico(unittest.TestCase):
    """L'algoritmo su un tempo NOTO: è l'unica verità che si può avere."""

    @classmethod
    def setUpClass(cls):
        cls.campioni = batteria_sintetica(120.0)
        cls.onset, cls.bassi = APP.inviluppo_onset(cls.campioni, 22050)

    def test_inviluppo_onset(self):
        self.assertIsNotNone(self.onset)
        self.assertEqual(len(self.onset), len(self.bassi))
        self.assertAlmostEqual(max(self.onset), 1.0, places=6, msg="l'inviluppo è normalizzato")
        self.assertEqual(self.onset[0], 0.0, msg="prima dei colpi l'inviluppo è piatto")

    def test_battuta_di_un_pattern_conosciuto(self):
        esito = APP.trova_battuta(self.onset, self.bassi, 512, 22050, quarti=4)
        self.assertTrue(esito["ok"], esito)
        # il BPM vero è 120: la prima versione del 18/09/2026 dava 60,1 (dimezzato)
        self.assertAlmostEqual(esito["bpm"], 120.0, delta=1.0, msg=esito["message"])
        self.assertAlmostEqual(esito["bar_end"] - esito["bar_start"], 2.0, delta=0.06)
        self.assertEqual(esito["quarters"], 4)
        self.assertEqual(len(esito["beats"]), 4)
        self.assertTrue(esito["reliable"], esito["message"])
        self.assertIn("BPM", esito["message"])
        self.assertEqual(esito["confidence"], 1.0)

    def test_battuta_comincia_dove_entra_la_batteria(self):
        # 20 s di intro senza batteria: la battuta NON deve cominciare a 0
        esito = APP.trova_battuta(self.onset, self.bassi, 512, 22050, quarti=4)
        self.assertGreaterEqual(esito["bar_start"], 19.9, "non si prende l'intro")
        self.assertLess(esito["bar_start"], 22.7, "non si salta oltre la prima battuta")
        self.assertAlmostEqual(esito["first_hit"], 20.0, delta=0.12)

    def test_bpm_di_altri_tempi(self):
        for bpm in (90.0, 140.0, 75.0):
            with self.subTest(bpm=bpm):
                onset, bassi = APP.inviluppo_onset(batteria_sintetica(bpm), 22050)
                esito = APP.trova_battuta(onset, bassi, 512, 22050, quarti=4)
                self.assertTrue(esito["ok"])
                self.assertAlmostEqual(esito["bpm"], bpm, delta=1.0, msg=esito["message"])
                self.assertAlmostEqual(esito["bar_end"] - esito["bar_start"], 240.0 / bpm, delta=0.08)

    def test_due_battute_non_cambiano_il_bpm(self):
        # con «Battute Sel.» = 8 la selezione vale due battute: il BPM non cambia
        esito = APP.trova_battuta(self.onset, self.bassi, 512, 22050, quarti=8)
        self.assertAlmostEqual(esito["bpm"], 120.0, delta=1.0)
        self.assertAlmostEqual(esito["bar_end"] - esito["bar_start"], 4.0, delta=0.1)

    def test_silenzio_non_da_battuta(self):
        silenzio = [0.0] * 500
        esito = APP.trova_battuta(silenzio, silenzio, 512, 22050)
        self.assertFalse(esito["ok"])
        self.assertIn("colpo", esito["message"])

    def test_traccia_troppo_corta(self):
        self.assertEqual(APP.inviluppo_onset([0.0] * 10, 22050), (None, None))

    def test_colpi_a_fuoco_conta_i_quarti(self):
        self.assertEqual(APP.colpi_a_fuoco(self.onset, 20.0, 0.5, 512, 22050, 4), 4)
        self.assertEqual(APP.colpi_a_fuoco(self.onset, 20.02, 0.5, 512, 22050, 4), 4,
                         "un paio di centesimi di scarto rientrano nella tolleranza")
        self.assertEqual(APP.colpi_a_fuoco(self.onset, 20.25, 0.5, 512, 22050, 4), 0,
                         "mezzo quarto fuori tempo non è un colpo a fuoco")

    def test_candidati_e_rifinitura(self):
        # i candidati vengono dall'autocorrelazione (a passi di `hop`, quindi il
        # più vicino a 120 BPM sta entro un passo di griglia) e `periodo_fine` lo
        # riporta al tempo vero: è la rifinitura che rende il BPM utilizzabile
        candidati = APP.periodi_candidati(self.onset, 512, 22050)
        self.assertTrue(candidati)
        vicini = [c for c in candidati if abs(60.0 / c - 120.0) < 3.0]
        self.assertTrue(vicini, "nessun candidato vicino a 120 BPM: %s" % [round(60.0 / c, 1) for c in candidati])
        self.assertAlmostEqual(60.0 / APP.periodo_fine(self.onset, vicini[0], 512, 22050, 0.03),
                               120.0, delta=0.5)



@unittest.skipUnless(HA_OSASCRIPT, "JavaScriptCore (osascript) non disponibile")
class TestFunzioniPagina(unittest.TestCase):
    """Le funzioni del sampler, eseguite davvero sui casi scritti a mano."""

    risultati = {}

    @classmethod
    def setUpClass(cls):
        src = leggi(PAGINA)
        js = "\n".join([
            estrai_funzione(src, "bpmDaBattuta"),
            estrai_funzione(src, "barTrimClamp"),
            estrai_funzione(src, "etichettaBattuta"),
            estrai_funzione(src, "origineHttp"),
            estrai_funzione(src, "urlBackend"),
            estrai_funzione(src, "etichettaTrimGiallo"),
            estrai_funzione(src, "etichettaBattutaVisibile"),
        ])
        js += """
// Il documento del sampler vive in un iframe blob:: qui `document` e `window` non
// esistono (JavaScriptCore non ha le API del browser), quindi si mettono due
// oggetti finti con quello che urlBackend() legge davvero — i testi.
var document = {referrer: ''};
var window = {location: {href: ''}};
var baseBackend = '';
function urlDa(base, referrer, href, percorso) {
  baseBackend = base; document.referrer = referrer; window.location.href = href;
  return urlBackend(percorso);
}
const clamp = [[-5, 300, 200, 0.05], [10, 10, 200, 0.05], [30, 20, 200, 0.05],
               [10, 11.5, 200, 0.05], [1, 2, 0, 0.05]];
// (nome, base del messaggio, referrer, nostra posizione, percorso)
const urlCasi = [
  ['origine',          'http://localhost:5070',      '',                        'blob:http://localhost:5070/x', '/beat/bar'],
  ['origine_con_path', 'http://localhost:5070/onyx', '',                        'blob:http://localhost:5070/x', '/beat/bar'],
  ['referrer',         '',                           'http://localhost:5070/',  'blob:http://localhost:5070/x', '/beat/bar'],
  ['nessuna_base',     '',                           '',                        'blob:http://localhost:5070/x', '/beat/bar'],
  ['assoluto',         '',                           '',                        '',                             'http://127.0.0.1:5075/beat/bar'],
  ['senza_slash',      'http://localhost:5070',      '',                        '',                             'beat/bar'],
  ['porta',            'http://127.0.0.1:5070',      '',                        '',                             '/beat/bar'],
  ['mittente_nullo',   'null',                       '',                        'blob:http://localhost:5070/x', '/beat/bar'],
  ['nostra_posizione', '',                           '',                        'http://localhost:5075/',       '/beat/bar']
];
console.log(JSON.stringify({
  bpm: [bpmDaBattuta(4, 2), bpmDaBattuta(4, 1.5), bpmDaBattuta(8, 4), bpmDaBattuta(4, 0),
        bpmDaBattuta(4, 0.1), bpmDaBattuta(0, 2), bpmDaBattuta('4', '2'), bpmDaBattuta(4, null)],
  clamp: clamp.map(c => barTrimClamp(c[0], c[1], c[2], c[3])),
  etichette: [etichettaBattuta(160, 4, 1.5), etichettaBattuta(null, 4, 2),
              etichettaBattuta(null, 4, 0), etichettaBattuta(120, 8, 4)],
  url: urlCasi.map(c => urlDa(c[1], c[2], c[3], c[4])),
  url_nomi: urlCasi.map(c => c[0]),
  trim: [etichettaTrimGiallo(true), etichettaTrimGiallo(false),
         etichettaBattutaVisibile(true), etichettaBattutaVisibile(false)],
  origini: ['http://localhost:5070', 'http://localhost:5070/onyx?x=1',
            'blob:http://localhost:5070/abc', 'null', '',
            'https://esempio.test:8443/x', undefined].map(origineHttp)
}));
"""
        cls.risultati = esegui_js(js)

    def test_bpm_dalla_battuta(self):
        bpm = self.risultati["bpm"]
        self.assertEqual(bpm[0], 120)      # 4 quarti in 2 s
        self.assertEqual(bpm[1], 160)      # 4 quarti in 1,5 s
        self.assertEqual(bpm[2], 120)      # 8 quarti in 4 s: due battute 4/4
        self.assertIsNone(bpm[3], "durata 0 → niente BPM")
        self.assertIsNone(bpm[4], "4 quarti in 0,1 s = 2400 BPM: fuori misura")
        self.assertIsNone(bpm[5], "quarti 0 → niente BPM")
        self.assertEqual(bpm[6], 120, "i valori dei campi arrivano come stringhe")
        self.assertIsNone(bpm[7])

    def test_estremi_della_battuta(self):
        clamp = self.risultati["clamp"]
        self.assertEqual(clamp[0], {"start": 0, "end": 200}, "fuori dal brano: si taglia")
        self.assertAlmostEqual(clamp[1]["end"] - clamp[1]["start"], 0.05, places=6)
        self.assertEqual(clamp[2], {"start": 20, "end": 30}, "estremi invertiti: si scambiano")
        self.assertEqual(clamp[3], {"start": 10, "end": 11.5})
        self.assertEqual(clamp[4], {"start": 1, "end": 2}, "senza durata non si taglia")

    def test_etichetta_della_battuta(self):
        et = self.risultati["etichette"]
        self.assertEqual(et[0], "battuta di 1.50 s · 4 quarti · 160 BPM")
        self.assertEqual(et[1], "battuta di 2.00 s · 4 quarti · 120 BPM")
        self.assertIn("nessuna battuta", et[2])
        self.assertEqual(et[3], "battuta di 4.00 s · 8 quarti · 120 BPM")

    def test_percorso_del_backend_diventa_assoluto(self):
        # Dentro l'iframe blob: del sampler una fetch con '/beat/bar' non parte
        # nemmeno: il percorso va reso assoluto con l'origine della pagina.
        nomi, url = self.risultati["url_nomi"], self.risultati["url"]
        self.assertEqual(nomi, ['origine', 'origine_con_path', 'referrer', 'nessuna_base',
                                'assoluto', 'senza_slash', 'porta', 'mittente_nullo',
                                'nostra_posizione'])
        self.assertEqual(url[0], "http://localhost:5070/beat/bar",
                         "l'origine che la pagina manda nel messaggio 'load'")
        self.assertEqual(url[1], "http://localhost:5070/beat/bar",
                         "l'origine può avere un percorso dietro: non conta")
        self.assertEqual(url[2], "http://localhost:5070/beat/bar",
                         "senza origine nel messaggio si ripiega sul referrer")
        self.assertEqual(url[3], "/beat/bar",
                         "base blob: e niente referrer: resta relativa (non c'è di meglio)")
        self.assertEqual(url[4], "http://127.0.0.1:5075/beat/bar",
                         "un percorso già assoluto non si tocca")
        self.assertEqual(url[5], "http://localhost:5070/beat/bar",
                         "percorso senza slash iniziale")
        self.assertEqual(url[6], "http://127.0.0.1:5070/beat/bar",
                         "la porta fa parte dell'origine")
        self.assertEqual(url[7], "/beat/bar", "origine 'null': non è una base http")
        self.assertEqual(url[8], "http://localhost:5075/beat/bar",
                         "sampler servito da http (non da blob): vale la sua posizione")

    def test_origine_http(self):
        o = self.risultati["origini"]
        self.assertEqual(o[0], "http://localhost:5070")
        self.assertEqual(o[1], "http://localhost:5070",
                         "percorso e query restano fuori dall'origine")
        self.assertEqual(o[2], "", "blob: non è un'origine http")
        self.assertEqual(o[3], "", "'null' non è un'origine http")
        self.assertEqual(o[4], "", "stringa vuota: nessuna origine")
        self.assertEqual(o[5], "https://esempio.test:8443", "https e porta valgono")
        self.assertEqual(o[6], "", "undefined: nessuna origine")

    def test_etichette_dei_due_trim(self):
        # I due pulsanti dicono lo STATO (come quello della griglia), non l'azione:
        # "Trim giallo on/off" e "Battuta on/off".
        et = self.risultati["trim"]
        self.assertEqual(et[0], "✂ Trim giallo on")
        self.assertEqual(et[1], "✂ Trim giallo off")
        self.assertEqual(et[2], "🎯 Battuta on")
        self.assertEqual(et[3], "🎯 Battuta off")


class TestCablaggio(unittest.TestCase):
    """Markup, stili, handler e la sparizione della stima automatica."""

    @classmethod
    def setUpClass(cls):
        cls.pagina = leggi(PAGINA)
        with open(APP_PATH, encoding="utf-8") as fh:
            cls.app = fh.read()

    def test_trim_celeste_in_pagina(self):
        for pezzo in ('id="bts-main"', 'id="btsl-main"', 'id="btsr-main"',
                      'id="bth-start-main"', 'id="bth-end-main"'):
            self.assertIn(pezzo, self.pagina)
        self.assertIn(".bar-trim-selection {", self.pagina)
        self.assertIn("2dd4bf", self.pagina.split(".bar-trim-selection")[1][:200],
                      "il trim della battuta è celeste (#2dd4bf)")
        self.assertIn("BATTUTA", self.pagina)

    def test_tre_pulsanti_nuovi(self):
        self.assertIn('id="bar-btn-main" onclick="trovaBattuta(\'main\')"', self.pagina)
        self.assertIn('id="save-bpm-main" onclick="salvaBpm(\'main\')"', self.pagina)
        self.assertIn("setLoopMode('main','bar')", self.pagina)
        for funzione in ("trovaBattuta", "salvaBpm", "impostaBattuta", "aggiornaBattuta",
                         "startBarTrimDrag", "startBarTrimDragTouch", "applyBarTrimDrag"):
            self.assertRegex(self.pagina, r"(?:async\s+)?function\s+%s\s*\(" % funzione)

    def test_loop_a_tre_modalita(self):
        self.assertIn("p.loopMode = (mode === 'all' || mode === 'bar') ? mode : 'sel';", self.pagina)
        self.assertIn("p.loopMode === 'bar' && p.barStart !== null", self.pagina)
        self.assertIn("if (p.loopMode === 'bar'", self.pagina)

    def test_il_sampler_manda_il_bpm_alla_pagina(self):
        self.assertIn("action: 'saveBpm'", self.pagina)
        self.assertIn("else if(d.action === 'saveBpm'){ salvaBpmDaSampler(d); }", self.pagina)
        self.assertIn("async function salvaBpmDaSampler(d){", self.pagina)
        self.assertIn("await updateSongField(song.id, 'bpm', valore);", self.pagina,
                      "il BPM va nel campo bpm della canzone")
        # il nome del file e l'id della canzone devono arrivare al sampler
        self.assertIn("songId: songId || ''}, '*');", self.pagina)
        self.assertIn("pl.filename = e.data.filename || pl.filename;", self.pagina)
        self.assertIn("(song && song.id) || ''", self.pagina)

    def test_stima_automatica_tolta(self):
        self.assertNotIn("fetchMetadata", self.pagina)
        self.assertNotIn("renderMetadata", self.pagina)
        self.assertNotIn("BPM &amp; Key", self.pagina)
        self.assertNotIn("/metadata/estimate", self.pagina)
        self.assertIn("misuralo nel sampler", self.pagina)

    def test_la_battuta_si_chiede_con_url_assoluta(self):
        # Difetto del 18/09/2026: il sampler gira in un iframe blob: e la fetch
        # con '/beat/bar' falliva con «Failed to parse URL from /beat/bar».
        self.assertIn("const url = urlBackend('/beat/bar');", self.pagina)
        self.assertIn("esito = await fetch(url, {", self.pagina)
        self.assertNotIn("fetch('/beat/bar'", self.pagina,
                         "niente più URL relativa: dal documento blob: non partirebbe")
        self.assertRegex(self.pagina, r"function\s+origineHttp\s*\(")
        self.assertRegex(self.pagina, r"function\s+urlBackend\s*\(")
        self.assertIn("let baseBackend = '';", self.pagina)
        self.assertIn("const originePagina = origineHttp(e.data.origin);", self.pagina)
        self.assertIn("if (originePagina) baseBackend = originePagina;", self.pagina)
        # la pagina dichiara la SUA origine in tutti e due i punti che montano il
        # sampler: il modale e l'editor embedded dello scraper
        self.assertIn("origin: window.location.origin,", self.pagina)
        self.assertIn("action:'load',origin:window.location.origin,", self.pagina)
        # l'errore in interfaccia non è più il TypeError nudo di Chrome
        self.assertIn("non riesco a chiedere la battuta: ", self.pagina)
        self.assertIn("riaprilo dal database", self.pagina)

    def test_al_sampler_arriva_il_nome_del_file_e_non_il_titolo(self):
        # Secondo difetto trovato il 18/09/2026 provando il pulsante dal vivo (dopo
        # il fix dell'URL): al sampler arrivava il TITOLO della canzone come
        # `filename`, quindi il backend rispondeva «File non trovato» (i file
        # stanno in downloads/) e nemmeno «Scarica selezione» sapeva cosa tagliare.
        self.assertIn("function openAudioEditor(url, filename, startSec, bpm, songId, etichetta) {",
                      self.pagina)
        self.assertIn("etichetta: nome || 'audio',", self.pagina)
        self.assertIn("(song && song.id) || '', label);", self.pagina,
                      "`openInSampler` passa il FILE locale e in più l'etichetta da mostrare")
        self.assertIn("function embedAudioEditorX(containerId, url, filename, startSec, etichetta){",
                      self.pagina)
        self.assertIn("embedAudioEditorX(containerId,'/stream/'+encodeURIComponent(filename), filename, startSec||0, label||filename);",
                      self.pagina, "anche l'editor embedded riceve il file, non l'etichetta")
        # l'interfaccia del sampler continua a mostrare il nome della canzone
        self.assertIn("e.data.etichetta || e.data.filename || 'audio'", self.pagina)
        self.assertIn("pl.filename = e.data.filename || pl.filename;", self.pagina)

    def test_due_interruttori_per_i_trim(self):
        # Richiesta di Alessandro (18/09/2026): «metti un pulsante per togliere il
        # trim giallo … e uno per il riquadro blu, on ed off».
        self.assertIn('id="trim-btn-main" onclick="toggleTrimGiallo(\'main\')"', self.pagina)
        self.assertIn('id="battuta-btn-main" onclick="toggleBattutaVisibile(\'main\')"', self.pagina)
        self.assertIn(">✂ Trim giallo on</button>", self.pagina)
        self.assertIn(">🎯 Battuta on</button>", self.pagina)
        for funzione in ("etichettaTrimGiallo", "etichettaBattutaVisibile",
                         "aggiornaPulsantiTrim", "toggleTrimGiallo", "toggleBattutaVisibile"):
            self.assertRegex(self.pagina, r"function\s+%s\s*\(" % funzione)
        self.assertIn("trimVisibile: true,", self.pagina)
        self.assertIn("barVisibile: true,", self.pagina)
        self.assertIn("aggiornaPulsantiTrim(key); // etichette dei due interruttori", self.pagina)
        # il trim GIALLO sparisce davvero: riquadro, ombreggiature, maniglie e area
        # di trascinamento (senza drag area non si trascina più)
        self.assertIn("const mostra = (el) => { if (el) el.style.display = visibile ? 'block' : 'none'; };",
                      self.pagina)
        for pezzo in ("mostra(sl);", "mostra(ss);", "mostra(sr);",
                      "mostra(ths);", "mostra(the_);", "mostra(tda);"):
            self.assertIn(pezzo, self.pagina)
        # il CELESTE si spegne senza perdere la battuta: barStart/barEnd restano
        self.assertIn("&& p.barVisibile !== false;   // 🎯 Battuta on/off spegne solo il disegno",
                      self.pagina)
        self.assertIn("\n  p.barVisibile = true;\n", self.pagina,
                      "🎯 Trova la battuta riaccende il riquadro: il risultato va visto")

    def test_il_celeste_e_pieno_come_il_giallo(self):
        # «adesso ha solamente i bordi celesti ma … tutta la parte selezionata
        # dall'inizio alla fine dovrebbe cambiare colore»: riempimento pieno, come
        # il trim giallo, e ombreggiature scure fuori dalla battuta.
        celeste = self.pagina.split(".bar-trim-selection {")[1].split("}")[0]
        self.assertIn("background:rgba(45,212,191,.22);", celeste)
        self.assertIn("border-top:2px solid #2dd4bf;", celeste)
        self.assertIn("z-index:5;", celeste, "sta sopra la selezione gialla (z-index 2)")
        giallo = self.pagina.split(".trim-selection {")[1].split("}")[0]
        self.assertIn("background:rgba(200,240,0,.08);", giallo)
        ombre = self.pagina.split(".bar-trim-shade-left, .bar-trim-shade-right {")[1].split("}")[0]
        self.assertIn("background:rgba(0,0,0,.45);", ombre,
                      "fuori dalla battuta si scurisce, come nel trim giallo")

    def test_endpoint_nellapp(self):
        self.assertIn('@app.route("/beat/bar", methods=["POST"])', self.app)
        self.assertIn("def beat_bar():", self.app)
        self.assertIn("def analizza_battuta(filepath", self.app)
        for funzione in ("periodi_candidati", "scegli_tra_candidati", "punteggio_griglia",
                         "periodo_fine", "scegli_quarto", "colpi_a_fuoco", "primo_colpo_forte",
                         "inviluppo_onset", "periodo_e_fase"):
            self.assertIn("def %s(" % funzione, self.app)



def app_is_up(url):
    try:
        import urllib.request
        urllib.request.urlopen(url + "/db/stats", timeout=3)
        return True
    except Exception:
        return False


def file_di_prova():
    """(nome file, bpm nel database) di un brano che esiste davvero in downloads/."""
    import urllib.request
    try:
        with urllib.request.urlopen(SAMPLELAB_URL + "/db/songs", timeout=60) as r:
            brani = json.load(r)
    except Exception:
        return None, None
    for b in brani:
        nome = b.get("local_file") or ""
        if nome and os.path.exists(os.path.join(DOWNLOAD, nome)):
            return nome, b.get("bpm")
    return None, None


@unittest.skipUnless(app_is_up(SAMPLELAB_URL), "app non attiva su " + SAMPLELAB_URL)
class TestEndpointVivo(unittest.TestCase):
    """POST /beat/bar sull'app attiva, su un file vero (sola lettura)."""

    @staticmethod
    def chiedi(payload):
        import urllib.error
        import urllib.request
        req = urllib.request.Request(
            SAMPLELAB_URL + "/beat/bar", data=json.dumps(payload).encode(),
            headers={"Content-Type": "application/json"}, method="POST")
        try:
            r = urllib.request.urlopen(req, timeout=180)
            return r.status, json.load(r)
        except urllib.error.HTTPError as e:
            return e.code, json.load(e)

    @classmethod
    def setUpClass(cls):
        cls.filename, cls.bpm_database = file_di_prova()
        if not cls.filename:
            raise unittest.SkipTest("nessun file della libreria presente in downloads/")
        cls.stato, cls.esito = cls.chiedi({"filename": cls.filename, "quarters": 4})

    def test_battuta_di_un_file_vero(self):
        self.assertEqual(self.stato, 200, self.esito)
        self.assertTrue(self.esito.get("ok"), self.esito)
        self.assertGreater(self.esito["bar_end"], self.esito["bar_start"])
        self.assertGreater(self.esito["beat"], 0.2)
        self.assertTrue(40 <= self.esito["bpm"] <= 220, self.esito["bpm"])
        self.assertEqual(self.esito["quarters"], 4)
        self.assertEqual(len(self.esito["beats"]), 4)
        self.assertIn("BPM", self.esito["message"])
        self.assertIn(self.esito["source"], ("librosa", "ffmpeg"))
        # la battuta sta dentro il tratto analizzato
        self.assertGreater(self.esito["bar_start"], 0)
        self.assertLess(self.esito["bar_start"], self.esito["seconds_analysed"])

    def test_file_inesistente(self):
        stato, risposta = self.chiedi({"filename": "questo-non-esiste.mp3"})
        self.assertEqual(stato, 404)
        self.assertFalse(risposta["ok"])

    def test_senza_nome_file(self):
        stato, risposta = self.chiedi({})
        self.assertEqual(stato, 400)
        self.assertFalse(risposta["ok"])

