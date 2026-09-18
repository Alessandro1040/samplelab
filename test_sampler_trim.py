"""Test del sampler: il trim GIALLO (mostra/nascondi) e il loop.

Richieste di Alessandro (18/09/2026):
- «metti un pulsante per togliere il trim giallo (nel senso che quando lo clicchi
  l'utente non lo vede proprio più, scompare)»;
- «quando c'è trim giallo off dovrebbe smettere anche di far comparire una parte di
  audio completamente gialla, dovrebbe tornare tutto grigio»;
- e, nella stessa sessione, la funzione «🎯 Trova la battuta» è stata **tolta**
  (pulsanti, trim celeste, loop 🔁, rotta `/beat/bar`): il file lo verifica, così
  non rientra da una porta di servizio.

Com'è fatto adesso:
- **✂ Trim giallo on/off** (nella riga di *Battute Sel.*) nasconde del tutto il trim
  del sample: `display:none` su riquadro, ombreggiature, maniglie IN/OUT e area di
  trascinamento (quindi non si trascina più) e `fullRedraw` per ridisegnare l'onda;
- la **forma d'onda** dentro la selezione torna **grigia** quando il trim è spento
  (`drawWaveform` guarda `p.trimVisibile`): non resta niente di giallo;
- il **loop ✂ Sel** torna indietro un pelo *prima* della fine: l'audio già consegnato
  alle casse si sente comunque (misurato: 24 ms di `AudioContext.outputLatency` su
  questo Mac), e senza l'anticipo si sentiva un pezzetto oltre il punto di OUT;
- i percorsi del backend si rendono assoluti con `urlBackend()` (il sampler vive in
  un iframe `blob:`, dove una fetch relativa non parte nemmeno).

Questo file prova:
1. `TestFunzioniPagina` — le funzioni pure del sampler in JavaScriptCore:
   `etichettaTrimGiallo`, `origineHttp`, `urlBackend` (9 casi), `anticipoRitorno`
   (6 casi), `anticipoLoop` (5 casi).
2. `TestCablaggio` — il pulsante, gli elementi che spariscono, l'onda grigia,
   l'anticipo nel loop, l'URL assoluta; e che «Trova la battuta» non resti da
   nessuna parte (né nella pagina né nel backend).
3. `TestEndpointVivo` — l'app attiva: `POST /beat/bar` non esiste più (404), il
   sampler si serve, `/db/stats` risponde.

Esecuzione (dalla cartella di SampleLab):
    python3 -m unittest -v test_sampler_trim
"""
import json
import os
import re
import shutil
import subprocess
import unittest

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
APP_PATH = os.path.join(BASE_DIR, "app (2).py")
PAGINA = os.path.join(BASE_DIR, "index (2).html")
SAMPLELAB_URL = os.environ.get("SAMPLELAB_URL", "http://localhost:5070")
HA_OSASCRIPT = shutil.which("osascript") is not None


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


def esegui_js(codice, nome_file="/tmp/test_sampler_trim.js"):
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
    """Le funzioni pure del sampler, eseguite davvero sui casi scritti a mano."""

    risultati = {}

    @classmethod
    def setUpClass(cls):
        src = leggi(PAGINA)
        js = "\n".join([
            estrai_funzione(src, "etichettaTrimGiallo"),
            estrai_funzione(src, "origineHttp"),
            estrai_funzione(src, "urlBackend"),
            estrai_funzione(src, "anticipoRitorno"),
            estrai_funzione(src, "anticipoLoop"),
            estrai_funzione(src, "intervalloTrimIniziale"),
        ])
        js += """
// Il documento del sampler vive in un iframe blob:: qui `document` e `window` non
// esistono (JavaScriptCore non ha le API del browser), quindi si mettono due
// oggetti finti con quello che urlBackend() legge davvero — i testi — e le
// costanti dell'anticipo, che nel documento sono dichiarate con `const`.
var document = {referrer: ''};
var window = {location: {href: ''}};
var baseBackend = '';
var LATENZA_USCITA_TIPICA = 0.02, MARGINE_DISEGNO = 0.008, ANTICIPO_MAX = 0.06;
function urlDa(base, referrer, href, percorso) {
  baseBackend = base; document.referrer = referrer; window.location.href = href;
  return urlBackend(percorso);
}
// (nome, base del messaggio, referrer, nostra posizione, percorso)
const urlCasi = [
  ['origine',          'http://localhost:5070',      '',                        'blob:http://localhost:5070/x', '/stream/canzone.mp3'],
  ['origine_con_path', 'http://localhost:5070/onyx', '',                        'blob:http://localhost:5070/x', '/stream/canzone.mp3'],
  ['referrer',         '',                           'http://localhost:5070/',  'blob:http://localhost:5070/x', '/stream/canzone.mp3'],
  ['nessuna_base',     '',                           '',                        'blob:http://localhost:5070/x', '/stream/canzone.mp3'],
  ['assoluto',         '',                           '',                        '',                             'http://127.0.0.1:5075/stream/canzone.mp3'],
  ['senza_slash',      'http://localhost:5070',      '',                        '',                             'stream/canzone.mp3'],
  ['porta',            'http://127.0.0.1:5070',      '',                        '',                             '/stream/canzone.mp3'],
  ['mittente_nullo',   'null',                       '',                        'blob:http://localhost:5070/x', '/stream/canzone.mp3'],
  ['nostra_posizione', '',                           '',                        'http://localhost:5075/',       '/stream/canzone.mp3']
];
console.log(JSON.stringify({
  trim: [etichettaTrimGiallo(true), etichettaTrimGiallo(false)],
  url: urlCasi.map(c => urlDa(c[1], c[2], c[3], c[4])),
  url_nomi: urlCasi.map(c => c[0]),
  origini: ['http://localhost:5070', 'http://localhost:5070/onyx?x=1',
            'blob:http://localhost:5070/abc', 'null', '',
            'https://esempio.test:8443/x', undefined].map(origineHttp),
  anticipo: [anticipoRitorno(0.024), anticipoRitorno(0), anticipoRitorno(undefined),
             anticipoRitorno(-1), anticipoRitorno('0.024'), anticipoRitorno(0.2)],
  anticipo_loop: [anticipoLoop(0.024, 2), anticipoLoop(0.024, 0.06), anticipoLoop(0.024, 0),
                  anticipoLoop(0.024, undefined), anticipoLoop(0.024, 10)],
  // (nome, intervallo) — la selezione iniziale del trim
  intervallo: [
    ['default',                 intervalloTrimIniziale(0, 0, 200, false)],
    ['dal_secondo_100',         intervalloTrimIniziale(100, 0, 200, false)],
    ['salvato',                 intervalloTrimIniziale(56, 86, 200, false)],
    ['salvato_oltre_la_fine',   intervalloTrimIniziale(190, 300, 200, false)],
    ['fine_prima_del_start',    intervalloTrimIniziale(50, 10, 200, false)],
    ['start_oltre_la_fine',     intervalloTrimIniziale(300, 0, 200, false)],
    ['senza_durata',            intervalloTrimIniziale(0, 0, 0, false)],
    ['finestra_5_secondi',      intervalloTrimIniziale(0, 0, 200, false, 5)],
    ['stem',                    intervalloTrimIniziale(0, 0, 200, true)],
    ['stem_senza_durata',       intervalloTrimIniziale(0, 0, 0, true)],
    ['stem_ignora_intervallo',  intervalloTrimIniziale(56, 86, 200, true)]
  ]
}));
"""
        cls.risultati = esegui_js(js)


    def test_etichetta_del_trim(self):
        # Il pulsante dice lo STATO (come quello della griglia), non l'azione.
        et = self.risultati["trim"]
        self.assertEqual(et[0], "✂ Trim giallo on")
        self.assertEqual(et[1], "✂ Trim giallo off")

    def test_percorso_del_backend_diventa_assoluto(self):
        # Dentro l'iframe blob: del sampler una fetch relativa non parte nemmeno:
        # il percorso va reso assoluto con l'origine della pagina.
        nomi, url = self.risultati["url_nomi"], self.risultati["url"]
        self.assertEqual(nomi, ['origine', 'origine_con_path', 'referrer', 'nessuna_base',
                                'assoluto', 'senza_slash', 'porta', 'mittente_nullo',
                                'nostra_posizione'])
        self.assertEqual(url[0], "http://localhost:5070/stream/canzone.mp3",
                         "l'origine che la pagina manda nel messaggio 'load'")
        self.assertEqual(url[1], "http://localhost:5070/stream/canzone.mp3",
                         "l'origine può avere un percorso dietro: non conta")
        self.assertEqual(url[2], "http://localhost:5070/stream/canzone.mp3",
                         "senza origine nel messaggio si ripiega sul referrer")
        self.assertEqual(url[3], "/stream/canzone.mp3",
                         "base blob: e niente referrer: resta relativa (non c'è di meglio)")
        self.assertEqual(url[4], "http://127.0.0.1:5075/stream/canzone.mp3",
                         "un percorso già assoluto non si tocca")
        self.assertEqual(url[5], "http://localhost:5070/stream/canzone.mp3",
                         "percorso senza slash iniziale")
        self.assertEqual(url[6], "http://127.0.0.1:5070/stream/canzone.mp3",
                         "la porta fa parte dell'origine")
        self.assertEqual(url[7], "/stream/canzone.mp3", "origine 'null': non è una base http")
        self.assertEqual(url[8], "http://localhost:5075/stream/canzone.mp3",
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

    def test_anticipo_del_ritorno(self):
        # Di quanto si anticipa il ritorno all'inizio: la latenza dichiarata dal
        # browser (24 ms su questo Mac) più il margine misurato del disegno (8 ms).
        a = self.risultati["anticipo"]
        self.assertAlmostEqual(a[0], 0.032, places=6)
        self.assertAlmostEqual(a[1], 0.028, places=6, msg="senza latenza: valore tipico 20 ms")
        self.assertAlmostEqual(a[2], 0.028, places=6, msg="undefined: valore tipico")
        self.assertAlmostEqual(a[3], 0.028, places=6, msg="negativa: valore tipico")
        self.assertAlmostEqual(a[4], 0.032, places=6, msg="le caselle danno stringhe")
        self.assertAlmostEqual(a[5], 0.06, places=6, msg="tetto: oltre 60 ms si taglierebbe troppo")

    def test_anticipo_non_mangia_la_selezione(self):
        # Con una selezione più corta dell'anticipo si tornerebbe indietro subito
        # (loop vuoto): al massimo si anticipa un terzo della selezione.
        al = self.risultati["anticipo_loop"]
        self.assertAlmostEqual(al[0], 0.032, places=6, msg="selezione di 2 s: anticipo pieno")
        self.assertAlmostEqual(al[1], 0.02, places=6, msg="selezione di 60 ms: un terzo")
        self.assertEqual(al[2], 0, msg="selezione vuota: nessun anticipo")
        self.assertEqual(al[3], 0, msg="senza lunghezza: nessun anticipo")
        self.assertAlmostEqual(al[4], 0.032, places=6)

    def test_intervallo_iniziale_del_trim(self):
        # La selezione con cui il file si apre: la finestra di 30 s, oppure
        # l'intervallo SALVATO nel database (confronto campioni), coi limiti del
        # file rispettati (mai oltre la durata, mai a rovescio).
        casi = {nome: iv for nome, iv in self.risultati["intervallo"]}
        self.assertEqual(casi["default"], {"start": 0, "end": 30, "voluto": False})
        self.assertEqual(casi["dal_secondo_100"], {"start": 100, "end": 130, "voluto": False})
        self.assertEqual(casi["salvato"], {"start": 56, "end": 86, "voluto": True})
        self.assertEqual(casi["salvato_oltre_la_fine"],
                         {"start": 190, "end": 200, "voluto": True})
        self.assertEqual(casi["fine_prima_del_start"],
                         {"start": 50, "end": 80, "voluto": False})
        self.assertEqual(casi["start_oltre_la_fine"],
                         {"start": 199.9, "end": 200, "voluto": False})
        self.assertEqual(casi["senza_durata"], {"start": 0, "end": 0, "voluto": False})
        self.assertEqual(casi["finestra_5_secondi"], {"start": 0, "end": 5, "voluto": False})

    def test_lo_stem_si_ascolta_tutto_e_senza_trim(self):
        # `senzaTrim` (19/09/2026): la selezione è TUTTO il file — senza, il play si
        # fermerebbe dopo i 30 secondi di default. È il caso degli stem di /scheda.
        casi = {nome: iv for nome, iv in self.risultati["intervallo"]}
        self.assertEqual(casi["stem"]["start"], 0)
        self.assertEqual(casi["stem"]["end"], 200)
        self.assertTrue(casi["stem"]["senzaTrim"])
        self.assertEqual(casi["stem_senza_durata"]["end"], 0)
        self.assertEqual(casi["stem_ignora_intervallo"]["end"], 200,
                         "con senzaTrim l'intervallo salvato nel database non conta")
        self.assertEqual(casi["stem_ignora_intervallo"]["start"], 0)


class TestCablaggio(unittest.TestCase):
    """Pulsante, elementi che spariscono, onda grigia, anticipo e URL assoluta."""

    @classmethod
    def setUpClass(cls):
        cls.pagina = leggi(PAGINA)
        cls.app = leggi(APP_PATH)

    def test_pulsante_del_trim_giallo(self):
        self.assertIn('id="trim-btn-main" onclick="toggleTrimGiallo(\'main\')"', self.pagina)
        self.assertIn(">✂ Trim giallo on</button>", self.pagina)
        for funzione in ("etichettaTrimGiallo", "aggiornaPulsantiTrim", "toggleTrimGiallo"):
            self.assertRegex(self.pagina, r"function\s+%s\s*\(" % funzione)
        self.assertIn("trimVisibile: opts.senzaTrim ? false : true,", self.pagina,
                      "il trim nasce visibile; l'unica eccezione è lo stem (senzaTrim)")
        self.assertIn("senzaTrim: !!opts.senzaTrim,", self.pagina)
        self.assertIn("aggiornaPulsantiTrim(key); // etichetta del pulsante del trim giallo",
                      self.pagina)
        # sparisce DAVVERO: riquadro, ombreggiature, maniglie e area di trascinamento
        self.assertIn("const mostra = (el) => { if (el) el.style.display = visibile ? 'block' : 'none'; };",
                      self.pagina)
        for pezzo in ("mostra(sl);", "mostra(ss);", "mostra(sr);",
                      "mostra(ths);", "mostra(the_);", "mostra(tda);"):
            self.assertIn(pezzo, self.pagina)

    def test_lo_stem_carica_senza_trim(self):
        # 19/09/2026 — `/scheda` monta un player su OGNI stem: è lo stesso sampler,
        # ma col trim SPENTO e la griglia sul BPM della canzone. La selezione è
        # tutto il file, altrimenti il play si fermerebbe dopo i 30 s di default.
        self.assertIn("{senzaTrim: e.data.trim === false}", self.pagina)
        self.assertIn("const iv = intervalloTrimIniziale(p.startSec, p.wantEnd, dur, p.senzaTrim);",
                      self.pagina)
        self.assertIn("setLoopMode(key, 'all');", self.pagina)
        self.assertIn("senzaTrim: !!opts.senzaTrim,", self.pagina)

    def test_onda_grigia_col_trim_spento(self):
        # «quando c'è trim giallo off … dovrebbe tornare tutto grigio»: l'onda dentro
        # la selezione non resta gialla, e il clic la ridisegna (fullRedraw).
        self.assertIn("const inSel = p.trimVisibile !== false && timelineT >= p.trimStart"
                      " && timelineT <= p.trimEnd;", self.pagina)
        self.assertIn("ctx.fillStyle = inSel ? 'rgba(200,240,0,0.6)' : 'rgba(100,100,100,0.4)';",
                      self.pagina)
        self.assertIn("fullRedraw(key);   // ridisegna anche la forma d'onda: col trim spento",
                      self.pagina)

    def test_loop_con_anticipo(self):
        # Il ritorno non aspetta la fine esatta: l'audio già consegnato alle casse si
        # sente comunque (18/09/2026: «viene suonata anche una piccola parte che va
        # oltre»), quindi si anticipa di quel tanto.
        self.assertIn("const anticipo = anticipoLoop(latenzaUscita, p.trimEnd - p.trimStart);",
                      self.pagina)
        self.assertIn("p.timelineTime >= p.trimEnd - anticipo", self.pagina)
        self.assertIn("function anticipoRitorno(latenza)", self.pagina)
        self.assertIn("function anticipoLoop(latenza, lunghezzaSelezione)", self.pagina)
        self.assertIn("LATENZA_USCITA_TIPICA = 0.02", self.pagina)
        self.assertIn("MARGINE_DISEGNO = 0.008", self.pagina)
        self.assertIn("ANTICIPO_MAX = 0.06", self.pagina)
        # la latenza la dichiara il browser: si chiede quando parte la riproduzione e
        # si rilegge a ogni fotogramma, perché `outputLatency` compare solo a
        # contesto avviato (da fermo vale 0 e resterebbe `baseLatency`, più corta)
        self.assertIn("aggiornaLatenzaUscita();   // quanto ritarda l'uscita", self.pagina)
        self.assertIn("leggiLatenzaUscita();   // appena il browser dichiara il ritardo vero",
                      self.pagina)
        self.assertIn("ctxLatenza.resume().catch(() => {});", self.pagina)

    def test_url_assoluta_per_l_audio(self):
        # Il sampler è un iframe blob:: l'URL dell'audio va reso assoluto.
        self.assertIn("currentAudioUrl = urlBackend(e.data.url);", self.pagina)
        self.assertIn("function urlBackend(percorso)", self.pagina)
        self.assertIn("function origineHttp(valore)", self.pagina)

    def test_legenda_dei_controlli_della_griglia(self):
        # Richiesta di Alessandro (18/09/2026): «puoi aggiungere una legenda nel
        # sampler? qualcosa che spieghi quello che hai appena detto, magari con un
        # esempio di utilizzo» — cioè Offset, Battute Sel., Diventa Bar N° e
        # Allinea griglia, con i numeri di un caso vero.
        self.assertIn('<details class="grid-legend" id="legenda-griglia-main">', self.pagina)
        self.assertIn("📖 Come funzionano Offset, Battute Sel., Diventa Bar N° e Allinea griglia",
                      self.pagina)
        # sta DOPO il pulsante del trim e FUORI dalla riga dei pulsanti (che è un
        # flex: dentro sarebbe una colonnina stretta invece di un riquadro largo)
        prima = self.pagina.index('id="trim-btn-main"')
        dentro = self.pagina.index('id="legenda-griglia-main"')
        self.assertGreater(dentro, prima, "la legenda viene dopo i controlli che spiega")
        self.assertIn("</div>\n\n      <!-- 📖 Legenda", self.pagina,
                      "la legenda sta dopo la </div> della riga, non dentro il flex")
        corpo = self.pagina.split('id="legenda-griglia-main"')[1].split("</details>")[0]
        for pezzo in ("<b>Offset</b>", "<b>Battute Sel.</b>", "<b>Diventa Bar N°</b>",
                      "Adatta alla griglia ≠ Allinea griglia", "<b>Esempio</b>",
                      "BPM = 60 × 4 ÷ 2 = 120", "offset = 10 − 2 × 1 = 8,0000 s"):
            self.assertIn(pezzo, corpo, "manca %r nella legenda" % pezzo)
        # è solo testo: si apre e si chiude da sé, senza JavaScript...
        self.assertNotIn("toggleLegenda", self.pagina)
        # ...e il suo CSS c'è (riquadro, corpo a scorrimento, esempi con la barretta)
        self.assertIn(".grid-legend {", self.pagina)
        self.assertIn(".grid-legend-body code { color:var(--accent); }", self.pagina)
        self.assertIn(".grid-legend-body .lg-esempio {", self.pagina)

    def test_trova_battuta_e_stata_tolta(self):
        # Tolta il 18/09/2026 su richiesta di Alessandro: non deve restare niente,
        # né nella pagina né nel backend (rotta e funzioni).
        for pezzo in ("Trova la battuta", "barStart", "bar-trim", "barVisibile", "barTrimClamp",
                      "bpmDaBattuta", "quartiBattuta", "aggiornaBattuta", "salvaBpmDaSampler",
                      "loop-bar", "bt-info", "battuta-btn"):
            self.assertNotIn(pezzo, self.pagina, "resta %r nella pagina" % pezzo)
        for pezzo in ("/beat/bar", "analizza_battuta", "def trova_battuta", "periodi_candidati",
                      "inviluppo_onset", "_campioni_del_file", "periodo_e_fase"):
            self.assertNotIn(pezzo, self.app, "resta %r nel backend" % pezzo)
        # il loop ha ancora le sue due modalità, senza la terza
        self.assertIn("p.loopMode = (mode === 'all') ? mode : 'sel';", self.pagina)
        self.assertIn('id="loop-sel-main"', self.pagina)
        self.assertIn('id="loop-all-main"', self.pagina)


def app_is_up(url):
    try:
        import urllib.request
        urllib.request.urlopen(url + "/db/stats", timeout=3)
        return True
    except Exception:
        return False


@unittest.skipUnless(app_is_up(SAMPLELAB_URL), "app non attiva su " + SAMPLELAB_URL)
class TestEndpointVivo(unittest.TestCase):
    """L'app attiva: la rotta della battuta non c'è più, il resto risponde."""

    @staticmethod
    def risposta(path, metodo="GET"):
        import urllib.error
        import urllib.request
        req = urllib.request.Request(SAMPLELAB_URL + path, method=metodo)
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                return r.status, r.read().decode("utf-8", "replace")
        except urllib.error.HTTPError as e:
            return e.code, e.read().decode("utf-8", "replace")

    def test_la_rotta_della_battuta_non_esiste_piu(self):
        stato, _ = self.risposta("/beat/bar", "POST")
        self.assertEqual(stato, 404)

    def test_il_sampler_si_serve(self):
        stato, corpo = self.risposta("/")
        self.assertEqual(stato, 200)
        self.assertIn("✂ Trim giallo on", corpo)
        self.assertNotIn("bar-trim", corpo)

    def test_db_stats(self):
        stato, corpo = self.risposta("/db/stats")
        self.assertEqual(stato, 200)
        self.assertGreater(json.loads(corpo)["songs"], 0)

