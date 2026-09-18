"""Test del salvataggio di un campione da Trova Campioni («Salva nel dataset»).

Segnalazione di Alessandro (18/09/2026): «quando cerco una canzone in trovacampioni
e clicco aggiungi al database non dà nessuna conferma che la canzone è stata
aggiunta e poi, quando vado su database a vedere i sample di tale canzone, non
compare quell'aggiunta». Il pulsante di partenza era **«Salva nel dataset»**.

Il difetto vero era nel GESTORE del pulsante: `renderPairCard` scriveva i titoli
nell'`onclick` con `esc()`, che protegge `& < > "` ma NON l'apostrofo. Con un
titolo come *Samuel's Song* l'attributo diventava

    onclick="savePair(this,'Samuel's Song','Tyler, The Creator',…)"

cioè JavaScript NON compilabile: il click non faceva nulla (nessun messaggio,
nessuna chiamata al backend, niente nel database). Provato con JavaScriptCore:
`SyntaxError: Unexpected identifier 's'. Expected ')' to end an argument list.`
Con la funzione `perHandler()` (escape HTML + escape del letterale JS) il gestore
compila e gli argomenti arrivano col testo esatto.

In più, perché il «non compare nel database» non potesse ripetersi:
`/save_pair` non ha più il `try/except: pass` attorno all'INSERT, non esce prima
dell'INSERT quando la coppia è già nel dataset, e non duplica la riga se la stessa
coppia+categoria viene salvata due volte (upsert).

Questo file prova:
1. `TestGestoreDelPulsante` — le funzioni VERE di `index (2).html` (`esc`, `escA`,
   `perHandler`, `fmtTime`, `renderPairCard`) eseguite con JavaScriptCore: il
   gestore prodotto si COMPILA e gli argomenti portano il testo esatto anche con
   apostrofi, virgolette, `&`, barre e ritorni a capo.
2. `TestCablaggio` — i pezzi della pagina che tolgono il vecchio silenzio: avviso
   visibile se manca la categoria, conferma con «🔗 Vedi nel database», scrittura
   immediata dell'aggiunta manuale, filtro del tab Database azzerato e riga
   evidenziata.
3. `TestSalvataggioNelDatabase` — l'endpoint vero `/save_pair` col test client di
   Flask su database e dataset TEMPORANEI (la libreria vera non si tocca).
4. `TestEndpointVivo` — in sola lettura sull'app attiva (`SAMPLELAB_URL`, default
   http://localhost:5070).

Esecuzione (dalla cartella di SampleLab):
    python3 -m unittest -v test_save_pair
"""
import importlib.util
import json
import os
import shutil
import sqlite3
import subprocess
import tempfile
import unittest
import urllib.error
import urllib.request

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
APP_PATH = os.path.join(BASE_DIR, "app (2).py")
PAGINA_PATH = os.path.join(BASE_DIR, "index (2).html")
SAMPLELAB_URL = os.environ.get("SAMPLELAB_URL", "http://localhost:5070")
HA_OSASCRIPT = shutil.which("osascript") is not None


def load_app():
    """Carica il modulo dell'app dal file (il nome con spazio non conta)."""
    spec = importlib.util.spec_from_file_location("samplelab_app2_save_pair", APP_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


APP = load_app()


def leggi(percorso):
    with open(percorso, encoding="utf-8") as fh:
        return fh.read()


# ── estrazione delle funzioni VERE dalla pagina (schema di test_scheda_canzone.py) ──
def funzione_js(src, nome):
    inizio = src.index("function " + nome + "(")
    i = src.index("{", inizio)
    liv, j = 0, i
    while j < len(src):
        if src[j] == "{":
            liv += 1
        elif src[j] == "}":
            liv -= 1
            if liv == 0:
                return src[inizio:j + 1]
        j += 1
    raise AssertionError("funzione non chiusa: " + nome)


def esegui_js(codice, nome_file="/tmp/test_save_pair.js"):
    """Esegue JavaScript con JavaScriptCore e torna il JSON dell'ultima espressione."""
    with open(nome_file, "w", encoding="utf-8") as out:
        out.write(codice + "\n")
    r = subprocess.run(["osascript", "-l", "JavaScript", nome_file],
                       capture_output=True, text=True)
    righe = ((r.stdout or "") + (r.stderr or "")).strip().splitlines()
    if not righe:
        raise AssertionError("nessun output da JavaScriptCore: %s" % (r.stderr or "")[:200])
    return json.loads(righe[-1])


def http_json(path, method="GET"):
    """Chiama l'app VIVA (sola lettura) e torna (stato, json)."""
    req = urllib.request.Request(SAMPLELAB_URL + path, method=method)
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            return r.status, json.loads(r.read().decode("utf-8") or "{}")
    except urllib.error.HTTPError as e:
        return e.code, {}


def app_is_up(url):
    try:
        urllib.request.urlopen(url + "/db/stats", timeout=3)
        return True
    except Exception:
        return False


# Titoli "difficili": quelli che rompevano il gestore del pulsante (vedi sopra).
TITOLI_DIFFICILI = [
    "Samuel's Song",
    'Titolo "con" virgolette',
    "Back\\slash",
    "A & B <c>",
    "Apice' e ritorno a capo\nseconda riga",
    'Doppio apice " finale',
    "Normale",
]


@unittest.skipUnless(HA_OSASCRIPT, "serve osascript (JavaScriptCore)")
class TestGestoreDelPulsante(unittest.TestCase):
    """Il gestore prodotto da renderPairCard deve COMPILARE e portare il testo vero."""

    @classmethod
    def setUpClass(cls):
        src = leggi(PAGINA_PATH)
        parti = [funzione_js(src, n) for n in ("esc", "escA", "perHandler", "fmtTime",
                                              "playerLoadingHTML", "playerUnavailableHTML",
                                              "renderPairCard")]
        cls.esito = esegui_js("\n".join(parti) + """
function decodifica(s){
  return s.replace(/&quot;/g,'"').replace(/&lt;/g,'<').replace(/&gt;/g,'>').replace(/&amp;/g,'&');
}
// Come il browser: prende il primo onclick della card e lo compila come gestore.
function gestore(titolo, sezione, extra){
  var item={title:titolo,artist:"Tyler, The Creator",year:2013,
            yt_url:"https://youtu.be/x?a=1&b=2",timestamp_yi:12,timestamp_x:5,already_saved:false};
  if(extra) Object.keys(extra).forEach(function(k){item[k]=extra[k]});
  var html=renderPairCard(item,0,sezione,"Sam Is Dead","Tyler, The Creator",
                          "https://www.youtube.com/watch?v=abc");
  var m=html.match(/onclick="([^"]*)"/);
  return decodifica(m[1]);
}
function prova(titolo, sezione, extra){
  var attr=gestore(titolo,sezione,extra);
  var f;
  try{ f=new Function('savePair', attr); }catch(e){ return {titolo:titolo, errore:e.message}; }
  var presi=null;
  try{ f(function(){ presi=Array.prototype.slice.call(arguments); }); }
  catch(e){ return {titolo:titolo, errore:'esecuzione: '+e.message}; }
  return {titolo:titolo, args:(presi||[]).slice(1)};
}
var TITOLI=""" + json.dumps(TITOLI_DIFFICILI, ensure_ascii=False) + """;
JSON.stringify({
  titoli:TITOLI.map(function(t){ return prova(t,"sampled_in"); }),
  nel_titolo_principale:prova("Sam Is Dead","contains",{title:"Samuel's Song"})
});
""")

    def test_ogni_gestore_si_compila_e_porta_il_testo_esatto(self):
        for caso in self.esito["titoli"]:
            with self.subTest(titolo=caso["titolo"]):
                self.assertNotIn("errore", caso,
                                 "gestore non compilabile: %s" % caso.get("errore"))
                self.assertEqual(caso["args"][0], caso["titolo"])
                self.assertEqual(caso["args"][2], "https://youtu.be/x?a=1&b=2")
                self.assertEqual(caso["args"][3], "Sam Is Dead")

    def test_gli_altri_argomenti_restano_al_loro_posto(self):
        caso = self.esito["titoli"][-1]        # «Normale»
        self.assertNotIn("errore", caso)
        self.assertEqual(caso["args"][1], "Tyler, The Creator")
        self.assertEqual(caso["args"][4], "Tyler, The Creator")
        self.assertEqual(caso["args"][5], "https://www.youtube.com/watch?v=abc")
        self.assertEqual(caso["args"][6], 5)       # timestamp_x
        self.assertEqual(caso["args"][7], 12)      # timestamp_yi
        self.assertEqual(caso["args"][8], "s-x-0")   # chiave del player X
        self.assertEqual(caso["args"][9], "s-yi-0")  # chiave del player Yi
        self.assertEqual(caso["args"][10], "sampled_in")

    def test_anche_quando_l_apostrofo_e_nel_titolo_principale(self):
        caso = self.esito["nel_titolo_principale"]
        self.assertNotIn("errore", caso)
        self.assertEqual(caso["args"][0], "Sam Is Dead")
        self.assertEqual(caso["args"][3], "Samuel's Song")

    def test_la_funzione_vecchia_sarebbe_rotta(self):
        """Prova che il difetto era reale: `esc()` da solo non basta per l'onclick."""
        src = leggi(PAGINA_PATH)
        vecchio = """%s
var attr = "savePair(this,'" + esc("Samuel's Song") + "')";
var esito;
try { new Function(attr); esito = JSON.stringify("OK"); }
catch(e) { esito = JSON.stringify(String(e.message)); }
esito
""" % funzione_js(src, "esc")
        esito = esegui_js(vecchio)
        self.assertIn("Unexpected identifier", esito)


class TestCablaggio(unittest.TestCase):
    """I pezzi di pagina che tolgono il vecchio «nessun messaggio, niente nel database»."""

    @classmethod
    def setUpClass(cls):
        cls.pagina = leggi(PAGINA_PATH)

    def test_esiste_l_escape_per_gli_handler(self):
        self.assertIn("function perHandler", self.pagina)
        for pezzo in ("'${perHandler(sxTitle)}'", "'${perHandler(syTitle)}'",
                      "'${perHandler(mainTitleX)}'", "'${perHandler(yiTitle)}'"):
            self.assertIn(pezzo, self.pagina)

    def test_il_messaggio_dell_aggiunta_manuale_non_si_cancella_piu(self):
        self.assertNotIn('if(statusEl)statusEl.textContent="";', self.pagina)
        self.assertIn("salvaCampioneManuale(card,section,songX,songYi);", self.pagina)
        self.assertIn("async function salvaCampioneManuale", self.pagina)

    def test_l_aggiunta_manuale_scrive_subito_col_categoria_del_gruppo(self):
        inizio = self.pagina.index("async function salvaCampioneManuale")
        corpo = self.pagina[inizio:inizio + 2200]
        self.assertIn("section==='covered'?'VOCAL_COVER':'SAMPLE'", corpo)
        self.assertIn("fetch('/save_pair'", corpo)
        self.assertIn("res.relation_updated?", corpo)

    def test_avviso_visibile_se_manca_la_categoria(self):
        self.assertIn("Scegli la categoria: senza categoria il campione NON viene salvato",
                      self.pagina)
        self.assertIn('toast("⚠ "+messaggio,"err")', self.pagina)

    def test_conferma_col_pulsante_per_andare_a_vederlo(self):
        self.assertIn("async function mostraCampionamenti", self.pagina)
        self.assertIn("🔗 Vedi nel database", self.pagina)
        self.assertIn("p.style.display='block'", self.pagina)

    def test_tab_database_filtro_azzerato_e_riga_evidenziata(self):
        self.assertIn("function evidenziaRigaDb", self.pagina)
        self.assertIn("evidenziaRigaDb(res.id);", self.pagina)
        self.assertIn("if(filtrato) filtro.value='';", self.pagina)


PAYLOAD = {
    "song_x": {"title": "Samuel's Song", "artist": "Tyler, The Creator",
               "youtube_url": "https://youtu.be/x?a=1&b=2"},
    "song_yi": {"title": "Sam Is Dead", "artist": "Tyler, The Creator",
                "youtube_url": "https://youtu.be/y"},
    "trim_x": {"start": 5.0, "end": 35.0},
    "trim_yi": {"start": 12.0, "end": 40.0},
    "category": "SAMPLE",
    "transformation": "DIRECT",
    "notes": "prova",
}


class TestSalvataggioNelDatabase(unittest.TestCase):
    """`/save_pair` col test client di Flask, su database e dataset TEMPORANEI."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="save_pair_prova_")
        self.db_originale = APP.DB_PATH
        self.dataset_originale = APP.DATASET_PATH
        APP.DB_PATH = os.path.join(self.tmp, "samplelab di prova.db")
        APP.DATASET_PATH = os.path.join(self.tmp, "dataset di prova.json")
        APP.init_db()
        self.client = APP.app.test_client()
        # Dal 19/09/2026 `/save_pair` avvia il download del file locale per le
        # canzoni che non ce l'hanno. Nei test NON deve uscire in rete (le coppie
        # di prova usano URL finti): si sostituisce la funzione e si registra.
        self._vero_avvia = APP.avvia_download_canzone
        self.download = []

        def finto(song_id, forzato=False):
            self.download.append(song_id)
            return "", "prova: nessun download"

        APP.avvia_download_canzone = finto

    def tearDown(self):
        APP.avvia_download_canzone = self._vero_avvia
        APP.DB_PATH = self.db_originale
        APP.DATASET_PATH = self.dataset_originale
        shutil.rmtree(self.tmp, ignore_errors=True)

    def salva(self, **modifiche):
        payload = json.loads(json.dumps(PAYLOAD))
        for chiave, valore in modifiche.items():
            payload[chiave] = valore
        return self.client.post("/save_pair", json=payload)

    def righe_relazioni(self):
        with sqlite3.connect(APP.DB_PATH) as c:
            return c.execute(
                "SELECT id, category, transformation, notes, "
                "timestamp_derivative_start, timestamp_source_end "
                "FROM sample_relations").fetchall()

    def test_salva_e_compare_nei_campionamenti(self):
        r = self.salva()
        self.assertEqual(r.status_code, 200)
        dati = r.get_json()
        self.assertTrue(dati["saved"])
        self.assertTrue(dati["relation_created"])
        self.assertTrue(dati["relation_id"].startswith("rel_"))
        rels = self.client.get("/db/relations").get_json()
        self.assertEqual(len(rels), 1)
        self.assertEqual(rels[0]["derivative_title"], "Samuel's Song")
        self.assertEqual(rels[0]["source_title"], "Sam Is Dead")
        self.assertEqual(rels[0]["category"], "SAMPLE")
        self.assertEqual(rels[0]["transformation"], "DIRECT")
        self.assertEqual(rels[0]["timestamp_derivative_start"], 5.0)
        self.assertEqual(rels[0]["timestamp_source_end"], 40.0)

    def test_il_salvataggio_chiede_di_scaricare_chi_non_ha_il_file(self):
        # 19/09/2026: «una canzone che compare nel database deve poter essere
        # ascoltata». Delle due canzoni della coppia, quelle SENZA file locale
        # finiscono in `avvia_download_canzone` (qui sostituita, niente rete).
        self.salva()
        self.assertEqual(len(self.download), 2)

    def test_colonna_sample_del_tab_database_e_i_conteggi(self):
        self.salva()
        brani = self.client.get("/db/songs").get_json()
        campione = [b for b in brani if b["title"] == "Samuel's Song"]
        self.assertEqual(len(campione), 1)
        self.assertEqual(campione[0]["relation_count"], 1)
        self.assertEqual(self.client.get("/db/stats").get_json()["relations"], 1)

    def test_la_stessa_coppia_aggiorna_e_non_duplica(self):
        primo = self.salva().get_json()
        secondo = self.salva(notes="rifinito", trim_x={"start": 1.0, "end": 9.0}).get_json()
        self.assertEqual(secondo["relation_id"], primo["relation_id"])
        self.assertTrue(secondo["relation_updated"])
        self.assertFalse(secondo["relation_created"])
        righe = self.righe_relazioni()
        self.assertEqual(len(righe), 1)
        self.assertEqual(righe[0][3], "rifinito")
        self.assertEqual(righe[0][4], 1.0)

    def test_categoria_diversa_e_un_altro_campione(self):
        self.salva()
        self.salva(category="VOCAL_COVER", transformation=None)
        self.assertEqual(len(self.righe_relazioni()), 2)

    def test_la_relazione_torna_anche_se_la_coppia_e_gia_nel_dataset(self):
        # era il difetto: con la coppia già nel dataset la funzione usciva PRIMA
        # dell'INSERT e nel tab Database non compariva niente
        self.salva()
        with sqlite3.connect(APP.DB_PATH) as c:
            c.execute("DELETE FROM sample_relations")
        dati = self.salva().get_json()
        self.assertTrue(dati["duplicate"])
        self.assertFalse(dati["saved"])
        self.assertTrue(dati["relation_created"])
        self.assertEqual(len(self.righe_relazioni()), 1)

    def test_dataset_json_scritto_dove_dice_l_app(self):
        self.salva()
        self.assertTrue(os.path.exists(APP.DATASET_PATH))
        with open(APP.DATASET_PATH, encoding="utf-8") as fh:
            self.assertEqual(json.load(fh)["meta"]["count"], 1)

    def test_campi_obbligatori(self):
        r = self.client.post("/save_pair", json={"song_x": {"title": "Solo titolo"},
                                                 "song_yi": {"title": "Altra", "artist": "X"}})
        self.assertEqual(r.status_code, 400)
        self.assertIn("Campi obbligatori", r.get_json()["error"])

    def test_un_errore_del_database_non_resta_nascosto(self):
        # prima l'INSERT era dentro `try/except: pass`: sembrava salvato e non c'era
        APP.DB_PATH = os.path.join(self.tmp, "cartella-che-non-esiste", "x.db")
        r = self.salva()
        self.assertEqual(r.status_code, 500)
        dati = r.get_json()
        self.assertFalse(dati["saved"])
        self.assertIn("Database:", dati["error"])


@unittest.skipUnless(app_is_up(SAMPLELAB_URL), "app non attiva su " + SAMPLELAB_URL)
class TestEndpointVivo(unittest.TestCase):
    """Sola lettura sull'app viva: la libreria vera non viene toccata."""

    def test_relations_risponde(self):
        stato, dati = http_json("/db/relations")
        self.assertEqual(stato, 200)
        self.assertIsInstance(dati, list)

    def test_stats_risponde(self):
        stato, dati = http_json("/db/stats")
        self.assertEqual(stato, 200)
        self.assertIn("songs", dati)

    def test_la_pagina_servita_ha_il_gestore_nuovo(self):
        with urllib.request.urlopen(SAMPLELAB_URL + "/", timeout=10) as r:
            html = r.read().decode("utf-8")
        self.assertIn("function perHandler", html)
        self.assertIn("function mostraCampionamenti", html)
        self.assertIn("function evidenziaRigaDb", html)


if __name__ == "__main__":
    unittest.main(verbosity=2)
