"""Test del confronto fra canzoni (niente doppioni) e del download automatico.

Segnalazione di Alessandro (18/09/2026): «in database c'è un problema con i
campionamenti … quando l'utente clicca su "scheda" dovrebbe comparire proprio una
canzone da una parte e l'altra dall'altra … inoltre dovresti fare in modo che
venga scaricata nei download una canzone una volta che compare nel database, cioè
attualmente c'è un errore e l'app non nota che till i collapse è gia presente nel
database e quindi mi ha segnato sia … quella normale che c'è già e sia quella
appena aggiunta però compare solo ✓ testo ✂️ Stem ✏️ Edit 📄 Scheda 🔗 1 perché
non è "scaricata", e non me la fa nemmeno mettere in play».

Il difetto vero: `get_or_create_song_db()` confrontava `normalize_key(title)` e
`normalize_key(artist)` **identici**. La riga vecchia di «Till I Collapse»
(13/08/2026) aveva l'artista «Eminem / Nate Dogg»; il salvataggio del campione ha
passato «Eminem» → nessun match → **riga nuova**, senza file locale (per questo
niente ▶, niente 🎛 Sampler e «manca il file locale in downloads/» nella Verifica).
La Verifica poi ha completato i crediti della riga nuova, che quindi ora sembra
identica a quella vecchia: un doppione vero.

Questo file prova:
1. `TestConfrontoTitoli` — le funzioni PURE del confronto: stessa canzone con
   artista scritto in modo diverso (o con «(Official Video)», «[Explicit]»,
   «feat. X») si riconosce, mentre **strumentale, remix, live e cover restano
   brani diversi**; `normalize_key` regge i NULL.
2. `TestRigheDelDatabase` — `/db/songs`, `/save_pair`, `/db/songs/merge` ed
   `/db/songs/<id>/ensure_file` col test client di Flask su database TEMPORANEO:
   la riga esistente si riusa (nessun doppione), l'unione conserva file, liriche e
   campionamenti, e il download automatico aggancia il file alla riga giusta.
3. `TestTrimGiallo` — `trimRangeFor` di `index (2).html` in JavaScriptCore: con
   un intervallo salvato (`endSec`) il trim giallo copre quello esatto.
4. `TestEndpointVivo` — in sola lettura sull'app attiva (`SAMPLELAB_URL`, default
   http://localhost:5070): la libreria vera non ha doppioni del tipo «stessa
   canzone scritta in due modi».

Esecuzione (dalla cartella di SampleLab):
    python3 -m unittest -v test_song_dedup
"""
import importlib.util
import json
import os
import shutil
import sqlite3
import subprocess
import tempfile
import time
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
    spec = importlib.util.spec_from_file_location("samplelab_app2_song_dedup", APP_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


APP = load_app()


def leggi(percorso):
    with open(percorso, encoding="utf-8") as f:
        return f.read()


def funzione_js(src, nome):
    """Estrae `function <nome>(…) { … }` contando le graffe."""
    inizio = src.index("function " + nome + "(")
    j, liv = src.index("{", inizio), 0
    while j < len(src):
        if src[j] == "{":
            liv += 1
        elif src[j] == "}":
            liv -= 1
            if liv == 0:
                return src[inizio:j + 1]
        j += 1
    raise AssertionError("funzione non chiusa: " + nome)


def esegui_js(codice, nome_file="/tmp/test_song_dedup.js"):
    """Esegue JavaScript con JavaScriptCore e torna il JSON dell'ultima espressione."""
    with open(nome_file, "w", encoding="utf-8") as out:
        out.write(codice + "\n")
    r = subprocess.run(["osascript", "-l", "JavaScript", nome_file],
                       capture_output=True, text=True)
    righe = ((r.stdout or "") + (r.stderr or "")).strip().splitlines()
    if not righe:
        raise AssertionError("nessun output da JavaScriptCore: %s" % (r.stderr or "")[:200])
    return json.loads(righe[-1])


def app_is_up(url):
    try:
        urllib.request.urlopen(url + "/db/stats", timeout=3)
        return True
    except Exception:
        return False


def http_json(path):
    """Chiama l'app VIVA (sola lettura) e torna (stato, json)."""
    try:
        with urllib.request.urlopen(SAMPLELAB_URL + path, timeout=20) as r:
            return r.status, json.loads(r.read().decode("utf-8") or "{}")
    except urllib.error.HTTPError as e:
        return e.code, {}


class TestConfrontoTitoli(unittest.TestCase):
    """Le funzioni pure che decidono se due righe sono la STESSA canzone."""

    def test_stessa_canzone_artista_scritto_diverso(self):
        # È il caso «Till I Collapse»: la riga vecchia aveva anche Nate Dogg.
        self.assertTrue(APP.canzoni_equivalenti("Till I Collapse", "Eminem",
                                                "Till I Collapse", "Eminem / Nate Dogg"))
        self.assertTrue(APP.canzoni_equivalenti("'Till I Collapse", "Eminem",
                                                "Till I Collapse", "Eminem"))
        self.assertTrue(APP.canzoni_equivalenti("Lights Out (feat. Justina Valentine)",
                                                "Chris Webby / Justina Valentine",
                                                "Lights Out (feat. Justina Valentine)",
                                                "Chris Webby"))

    def test_marcatori_di_servizio_non_cambiano_la_canzone(self):
        for titolo in ("Till I Collapse (Official Video)", "Till I Collapse [Explicit]",
                       "Till I Collapse (Official Music Video)", "Till I Collapse (Audio)",
                       "Till I Collapse (feat. Nate Dogg)"):
            with self.subTest(titolo=titolo):
                self.assertTrue(APP.canzoni_equivalenti(titolo, "Eminem",
                                                        "Till I Collapse", "Eminem"))

    def test_crediti_senza_parentesi_nel_titolo_non_si_tagliano(self):
        # Scelta voluta: «… feat. X» SCIOLTO (senza parentesi) nel titolo non si
        # toglie, perché la libreria vera ha titoli come «Kim ft. 2Pac, Miley
        # Cyrus - 2021 - Mashup…», che diventerebbe «Kim» (un altro brano).
        # Il caso normale delle collaborazioni lo copre il campo ARTISTA
        # (`artisti_compatibili` divide su feat./ft./with/&...).
        self.assertFalse(APP.canzoni_equivalenti("Brano feat. Tizio", "Artista",
                                                 "Brano", "Artista"))
        self.assertTrue(APP.artisti_compatibili("Artista feat. Tizio", "Artista"))
        self.assertTrue(APP.canzoni_equivalenti("GHIGLIOTTINA - feat. Noyz Narcos",
                                                "Salmo / Noyz Narcos",
                                                "GHIGLIOTTINA - feat. Noyz Narcos",
                                                "Salmo"))


    def test_remix_strumentale_live_e_cover_restano_altri_brani(self):
        # Regressione trovata il 19/09/2026: la `titolo_base()` che serve a CERCARE
        # le varianti (scheda canzone) toglie «Remix/Instrumental/Live», e usata
        # qui univa brani diversi. Il confronto per il dedup NON li tocca.
        for altro in ("Till I Collapse - Instrumental", "Till I Collapse (Remix)",
                      "Till I Collapse (Live)", "Till I Collapse Cover",
                      "Just Don't Give a Fuck - Instrumental"):
            with self.subTest(titolo=altro):
                self.assertFalse(APP.canzoni_equivalenti("Till I Collapse", "Eminem",
                                                        altro, "Eminem"),
                                 "«%s» NON è la stessa canzone" % altro)

    def test_artisti_diversi_non_si_unisono(self):
        self.assertFalse(APP.canzoni_equivalenti("Till I Collapse", "Eminem",
                                                 "Till I Collapse", "D12"))
        self.assertFalse(APP.canzoni_equivalenti("Bounce", "Chris Webby",
                                                 "Bounce", "Eminem"))

    def test_artista_mancante_solo_se_il_titolo_e_unico(self):
        # I file di yt-dlp non sempre hanno l'artista nel nome.
        con = sqlite3.connect(":memory:")
        con.row_factory = sqlite3.Row
        con.executescript(
            "CREATE TABLE songs(id TEXT PRIMARY KEY, title TEXT, artist TEXT);"
            "INSERT INTO songs VALUES('a','Titolo Unico','Artista Uno');"
            "INSERT INTO songs VALUES('b','Titolo Doppio','Artista Uno');"
            "INSERT INTO songs VALUES('c','Titolo Doppio','Artista Due');")
        sid, come = APP.find_existing_song(con, "Titolo Unico", "")
        self.assertEqual(sid, "a")
        self.assertIn("unico", come)
        sid2, _ = APP.find_existing_song(con, "Titolo Doppio", "")
        self.assertIsNone(sid2, "con due brani omonimi non si tira a indovinare")

    def test_titolo_vuoto_non_un_isce_niente(self):
        self.assertFalse(APP.canzoni_equivalenti("", "Eminem", "Till I Collapse", "Eminem"))
        self.assertFalse(APP.canzoni_equivalenti(None, None, None, None))

    def test_normalize_key_regge_i_null(self):
        # In libreria ci sono righe con `title` a NULL (import dal player Onyx):
        # prima facevano fallire /db/songs con 500.
        self.assertEqual(APP.normalize_key(None), "")
        self.assertEqual(APP.normalize_key("Samuel's Song"), "samuelssong")
        self.assertEqual(APP.titolo_confronto(None), "")

class TestRigheDelDatabase(unittest.TestCase):
    """Gli endpoint veri su un database TEMPORANEO (la libreria non si tocca)."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="song_dedup_prova_")
        self.db_originale = APP.DB_PATH
        self.dataset_originale = APP.DATASET_PATH
        self.dl_originale = APP.DL_DIR
        APP.DB_PATH = os.path.join(self.tmp, "samplelab di prova.db")
        APP.DATASET_PATH = os.path.join(self.tmp, "dataset di prova.json")
        APP.DL_DIR = os.path.join(self.tmp, "downloads")
        os.makedirs(APP.DL_DIR, exist_ok=True)
        APP.init_db()
        self.client = APP.app.test_client()
        # Nessun test deve scaricare davvero: il download automatico si registra,
        # ma imita la funzione vera (non parte se il file locale c'è già).
        self.download = []
        self._vero_avvia = APP.avvia_download_canzone

        def finto(song_id, forzato=False):
            with APP.get_db() as conn:
                riga = conn.execute("SELECT local_file FROM songs WHERE id=?",
                                    (song_id,)).fetchone()
            if not forzato and riga and APP.file_locale_valido(riga["local_file"]):
                return "", "il file locale c'è già"
            self.download.append((song_id, forzato))
            return "job_di_prova", "download avviato (prova)"

        APP.avvia_download_canzone = finto

    def tearDown(self):
        APP.avvia_download_canzone = self._vero_avvia
        APP.DB_PATH = self.db_originale
        APP.DATASET_PATH = self.dataset_originale
        APP.DL_DIR = self.dl_originale
        shutil.rmtree(self.tmp, ignore_errors=True)

    def canzoni(self):
        return self.client.get("/db/songs").get_json()

    def crea_riga(self, sid, titolo, artista, **campi):
        with APP.get_db() as conn:
            colonne = ["id", "title", "artist"] + list(campi)
            valori = [sid, titolo, artista] + list(campi.values())
            conn.execute("INSERT INTO songs(%s) VALUES(%s)" % (
                ",".join(colonne), ",".join("?" * len(colonne))), valori)
        return sid

    def test_la_canzone_esistente_non_si_duplica_con_artista_scritto_diverso(self):
        # È il caso vero: riga del 13/08 con «Eminem / Nate Dogg», poi il
        # salvataggio del campione arriva con «Eminem».
        self.crea_riga("song_vecchia", "Till I Collapse", "Eminem / Nate Dogg",
                       local_file="vecchio.mp3")
        r = self.client.post("/db/songs", json={"title": "Till I Collapse",
                                                "artist": "Eminem"})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.get_json()["id"], "song_vecchia")
        titoli = [b for b in self.canzoni() if b["title"] == "Till I Collapse"]
        self.assertEqual(len(titoli), 1, "nessuna riga nuova")
        self.assertEqual(titoli[0]["local_file"], "vecchio.mp3")

    def test_una_variante_nuova_si_crea_davvero(self):
        # Il contrario del test sopra: uno strumentale NON è la stessa canzone.
        self.crea_riga("song_base", "Till I Collapse", "Eminem", local_file="base.mp3")
        r = self.client.post("/db/songs", json={"title": "Till I Collapse - Instrumental",
                                                "artist": "Eminem"})
        self.assertNotEqual(r.get_json()["id"], "song_base")

    def test_save_pair_riusa_la_riga_esistente_e_dice_come(self):
        # Il file della riga vecchia esiste davvero in downloads/: è il caso in cui
        # NON si deve scaricare niente per quella canzone.
        with open(os.path.join(APP.DL_DIR, "vecchio.mp3"), "wb") as f:
            f.write(b"audio")
        self.crea_riga("song_vecchia", "Till I Collapse", "Eminem / Nate Dogg",
                       local_file="vecchio.mp3")
        r = self.client.post("/save_pair", json={
            "song_x": {"title": "Till I Collapse", "artist": "Eminem",
                       "youtube_url": "https://youtu.be/zzz"},
            "song_yi": {"title": "We Will Rock You", "artist": "Queen"},
            "trim_x": {"start": 56, "end": 86}, "trim_yi": {"start": 1, "end": 31},
            "category": "STEM_REUSE", "transformation": "PROCESSED",
            "notes": "Ritmo Batteria"})
        self.assertEqual(r.status_code, 200)
        dati = r.get_json()
        self.assertTrue(dati["relation_created"])
        self.assertEqual(dati["derivative"]["id"], "song_vecchia")
        self.assertFalse(dati["derivative"]["created"], "riga esistente riusata")
        self.assertIn("compatibile", dati["derivative"]["matched_by"])
        self.assertTrue(dati["source"]["created"], "il campionato è nuovo")
        riga = [b for b in self.canzoni() if b["id"] == "song_vecchia"][0]
        self.assertEqual(riga["local_file"], "vecchio.mp3", "il file non si sovrascrive")
        self.assertEqual(riga["youtube_url"], "https://youtu.be/zzz")
        self.assertEqual(riga["relation_count"], 1)
        # il download automatico parte SOLO per la riga senza file
        self.assertEqual([d[0] for d in self.download], [dati["source"]["id"]])
        self.assertIn("source", dati["downloads"])


    # ── L'UNIONE DI DUE RIGHE CHE SONO LA STESSA CANZONE ──────────────────
    def test_unione_conserva_file_liriche_e_campioni(self):
        self.crea_riga("song_vecchia", "Till I Collapse", "Eminem / Nate Dogg",
                       local_file="vecchio.mp3")
        self.crea_riga("song_nuova", "Till I Collapse", "Eminem",
                       lyrics="[Intro] yo left", genius_url="https://genius.com/x",
                       album="The Eminem Show")
        self.crea_riga("song_fonte", "We Will Rock You", "Queen", local_file="queen.mp3")
        with APP.get_db() as conn:
            conn.execute("INSERT INTO sample_relations(id, derivative_song_id, "
                         "source_song_id, category, timestamp_derivative_start, "
                         "timestamp_source_start) VALUES('rel_x','song_nuova',"
                         "'song_fonte','STEM_REUSE',56,1)")
        r = self.client.post("/db/songs/merge", json={"keep": "song_vecchia",
                                                      "drop": "song_nuova"})
        self.assertEqual(r.status_code, 200)
        dati = r.get_json()
        self.assertTrue(dati["ok"])
        self.assertIn("lyrics", dati["campi_completati"])
        self.assertIn("genius_url", dati["campi_completati"])
        self.assertIn("album", dati["campi_completati"])
        self.assertEqual(dati["agganci_spostati"]["sample_relations.derivative_song_id"], 1)
        keep = [b for b in self.canzoni() if b["id"] == "song_vecchia"][0]
        self.assertEqual(keep["lyrics"], "[Intro] yo left")
        self.assertEqual(keep["genius_url"], "https://genius.com/x")
        self.assertEqual(keep["local_file"], "vecchio.mp3", "il file buono resta")
        self.assertEqual(keep["relation_count"], 1, "il campionamento è passato qui")
        tutti = self.canzoni()
        self.assertFalse([b for b in tutti if b["id"] == "song_nuova"], "doppione cancellato")
        self.assertEqual(len([b for b in tutti if b["title"] == "Till I Collapse"]), 1)

    def test_unione_non_sovrascrive_quello_che_c_e(self):
        self.crea_riga("song_a", "Brano", "Artista", album="Album Buono",
                       bpm=90, local_file="mio.mp3")
        self.crea_riga("song_b", "Brano", "Artista", album="Album Vecchio", bpm=140)
        r = self.client.post("/db/songs/merge", json={"keep": "song_a", "drop": "song_b"})
        self.assertEqual(r.status_code, 200)
        keep = [b for b in self.canzoni() if b["id"] == "song_a"][0]
        self.assertEqual(keep["album"], "Album Buono")
        self.assertEqual(keep["bpm"], 90)

    def test_unione_azzera_i_verdetti_presi_quando_il_file_mancava(self):
        # La riga che resta ha il file: dire ancora «manca il file locale» è falso.
        with open(os.path.join(APP.DL_DIR, "mio.mp3"), "wb") as f:
            f.write(b"audio")
        self.crea_riga("song_a", "Brano", "Artista", local_file="mio.mp3")
        self.crea_riga("song_b", "Brano", "Artista",
                       audio_match_esito="non verificabile",
                       audio_match_motivo="audio non verificabile: manca il file locale in downloads/",
                       audio_match_at="2026-09-18 17:08:41",
                       testo_esito="non verificabile",
                       testo_motivo="conferma dal parlato non possibile: manca il file locale")
        r = self.client.post("/db/songs/merge", json={"keep": "song_a", "drop": "song_b"})
        dati = r.get_json()
        self.assertEqual(sorted(dati["verdetti_azzerati"]), ["audio_match", "testo"])
        keep = [b for b in self.canzoni() if b["id"] == "song_a"][0]
        self.assertIsNone(keep["audio_match_esito"])
        self.assertIsNone(keep["audio_match_at"])
        self.assertIn("la Verifica lo rifarà", keep["audio_match_motivo"])
        self.assertIsNone(keep["testo_esito"])

    def test_unione_rifiuta_righe_mancanti_o_uguali(self):
        self.crea_riga("song_a", "Brano", "Artista")
        self.assertEqual(self.client.post(
            "/db/songs/merge", json={"keep": "song_a", "drop": "song_a"}).status_code, 400)
        self.assertEqual(self.client.post(
            "/db/songs/merge", json={"keep": "song_a", "drop": "song_inesistente"}).status_code, 404)
        self.assertEqual(self.client.post(
            "/db/songs/merge", json={"keep": "song_a"}).status_code, 400)


    # ── IL DOWNLOAD AUTOMATICO ────────────────────────────────────────────
    def test_il_file_scaricato_si_aggancia_alla_stessa_riga(self):
        """Una riga nel database senza file locale: il file arriva e resta LEI."""
        APP.avvia_download_canzone = self._vero_avvia       # serve la funzione vera
        with APP.get_db() as conn:
            sid = APP.resolve_or_create_song(conn, "Brano Nuovo", "Artista Prova",
                                             "https://youtu.be/zzz")[0]
        nome = "Brano Nuovo [zzz].mp3"
        self.query_vista = None

        def scarica_finto(job_id, query, fmt, quality="192", expected_title="",
                          expected_artist="", min_duration=0):
            self.query_vista = query
            with open(os.path.join(APP.DL_DIR, nome), "wb") as f:
                f.write(b"audio finto")
            APP.jobs[job_id]["status"] = "done"
            APP.jobs[job_id]["filename"] = nome

        vero = APP.do_download
        APP.do_download = scarica_finto
        try:
            job, motivo = APP.avvia_download_canzone(sid)
            self.assertTrue(job, motivo)
            for _ in range(60):
                with APP.get_db() as conn:
                    riga = conn.execute("SELECT local_file FROM songs WHERE id=?",
                                        (sid,)).fetchone()
                if riga["local_file"]:
                    break
                time.sleep(0.1)
        finally:
            APP.do_download = vero
        with APP.get_db() as conn:
            riga = conn.execute("SELECT local_file FROM songs WHERE id=?",
                                (sid,)).fetchone()
            quante = conn.execute("SELECT COUNT(*) c FROM songs").fetchone()["c"]
        self.assertEqual(riga["local_file"], nome, "il file va su QUELLA riga")
        self.assertEqual(quante, 1, "nessuna riga nuova creata dal download")
        self.assertEqual(self.query_vista, "https://youtu.be/zzz")

    def test_ensure_file_non_riscarica_quando_il_file_c_e(self):
        nome = "gia-presente.mp3"
        with open(os.path.join(APP.DL_DIR, nome), "wb") as f:
            f.write(b"audio")
        self.crea_riga("song_con_file", "Brano", "Artista", local_file=nome)
        APP.avvia_download_canzone = self._vero_avvia
        r = self.client.post("/db/songs/song_con_file/ensure_file", json={})
        self.assertEqual(r.status_code, 200)
        dati = r.get_json()
        self.assertFalse(dati["avviato"])
        self.assertIn("c'è già", dati["motivo"])

    def test_ensure_file_avvia_il_download_della_riga(self):
        self.crea_riga("song_senza_file", "Brano", "Artista",
                       youtube_url="https://youtu.be/qqq")
        r = self.client.post("/db/songs/song_senza_file/ensure_file", json={})
        self.assertEqual(r.status_code, 200)
        dati = r.get_json()
        self.assertTrue(dati["avviato"])
        self.assertEqual(dati["song_id"], "song_senza_file")
        self.assertEqual(self.download, [("song_senza_file", False)])

    def test_un_titolo_null_non_rompe_la_tabella(self):
        # Regressione del 19/09/2026: `normalize_key(None)` mandava in 500
        # /db/songs per le due righe importate dal player Onyx senza titolo.
        self.crea_riga("song_senza_titolo", None, "Raedius, Hopsin",
                       local_file="onyx.mp3")
        r = self.client.get("/db/songs")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(len(r.get_json()), 1)



class TestCablaggioDellaPagina(unittest.TestCase):
    """I pezzi di `index (2).html` e `app (2).py` che reggono le due richieste."""

    @classmethod
    def setUpClass(cls):
        cls.pagina = leggi(PAGINA_PATH)
        cls.app = leggi(APP_PATH)

    def test_esiste_il_confronto_a_due_canzoni(self):
        self.assertIn('id="rel-compare-modal"', self.pagina)
        for fn in ("apriConfrontoCampione", "apriConfrontoRelazione", "rcmScarica",
                   "scaricaInDownload", "renderConfrontoCampione", "closeConfrontoCampione"):
            self.assertIn("function " + fn, self.pagina, "manca " + fn)
        # la stessa vista a due colonne delle card di Trova Campioni
        self.assertIn('<div class="pair-players">', self.pagina)
        self.assertIn("rcmMontaEditor", self.pagina)

    def test_il_pulsante_scheda_della_tabella_apre_il_confronto(self):
        inizio = self.pagina.index("function renderDbTable")
        corpo = self.pagina[inizio:inizio + 8000]
        self.assertIn("apriConfrontoCampione('${s.id}')", corpo)
        self.assertNotIn('<a class="db-stem-btn" href="/scheda?song=', corpo,
                         "il pulsante 📄 Scheda non deve più essere un link diretto")
        # e c'è il pulsante per la riga senza file
        self.assertIn("scaricaInDownload('${s.id}',this)", corpo)

    def test_il_trim_giallo_riceve_la_fine_dell_intervallo(self):
        self.assertIn("function trimRangeFor(startSec, duration, defaultDur, endSec)", self.pagina)
        self.assertIn("endSec: endSec || 0", self.pagina)
        self.assertIn("initPlayer('main', currentAudioUrl, e.data.startSec || 0, e.data.endSec || 0)",
                      self.pagina)
        self.assertIn("carico.grid=false", self.pagina)

    def test_il_backend_ha_dedup_merge_e_download_automatico(self):
        for pezzo in ("def find_existing_song", "def resolve_or_create_song",
                      "def avvia_download_canzone", "def file_locale_valido",
                      "/db/songs/<song_id>/ensure_file", "/db/songs/merge"):
            self.assertIn(pezzo, self.app, "manca " + pezzo)
        # il download automatico è agganciato ai tre ingressi nel database:
        # /save_pair (entrambe le canzoni), /db/songs (POST) e /db/from_onyx.
        self.assertEqual(self.app.count("avvia_download_canzone(sid"), 3)
        self.assertIn("avvia_download_canzone(sid_)", self.app)

    def test_il_doppione_non_nasce_dal_download(self):
        # `avvia_download_canzone` deve scrivere il file sulla riga, mai crearne una
        inizio = self.app.index("def avvia_download_canzone")
        corpo = self.app[inizio:inizio + 3200]
        self.assertNotIn("register_local_file", corpo)
        self.assertIn("UPDATE songs SET local_file=?", corpo)


@unittest.skipUnless(HA_OSASCRIPT, "serve osascript (JavaScriptCore)")
class TestTrimGiallo(unittest.TestCase):
    """`trimRangeFor` con l'intervallo salvato nel database (trim giallo esatto)."""

    @classmethod
    def setUpClass(cls):
        src = leggi(PAGINA_PATH)
        cls.esito = esegui_js(funzione_js(src, "trimRangeFor") + """
JSON.stringify({
  salvato:   trimRangeFor(56, 300, 30, 86),
  senzaFine: trimRangeFor(56, 300, 30, 0),
  oltre:     trimRangeFor(4000, 300, 30, 4030),
  corto:     trimRangeFor(10, 12, 30, 40)
});""")

    def test_intervallo_salvato_copia_quello_esatto(self):
        caso = self.esito["salvato"]
        self.assertEqual(caso["start"], 56)
        self.assertEqual(caso["end"], 86)
        self.assertTrue(caso["voluto"])
        self.assertFalse(caso["beyond"])

    def test_senza_fine_resta_la_finestra_di_30_secondi(self):
        caso = self.esito["senzaFine"]
        self.assertEqual(caso["start"], 56)
        self.assertEqual(caso["end"], 86)

    def test_timestamp_oltre_la_durata_non_da_durate_negative(self):
        caso = self.esito["oltre"]
        self.assertTrue(caso["beyond"])
        self.assertLess(caso["end"], 300.1)
        self.assertGreater(caso["end"], caso["start"])

    def test_audio_piu_corto_dell_intervallo_salvato(self):
        caso = self.esito["corto"]
        self.assertLessEqual(caso["end"], 12.0)
        self.assertGreater(caso["end"], caso["start"])


@unittest.skipUnless(app_is_up(SAMPLELAB_URL), "app non attiva su " + SAMPLELAB_URL)
class TestEndpointVivo(unittest.TestCase):
    """Sola lettura sull'app viva: la libreria vera non viene toccata."""

    def brani(self):
        stato, dati = http_json("/db/songs")
        self.assertEqual(stato, 200)
        return dati

    def test_till_i_collapse_e_una_sola_riga_con_file_e_campione(self):
        # Il doppione della segnalazione: due righe di «Till I Collapse», una con
        # il file e l'altra con liriche e link. Il 19/09/2026 sono state UNITE.
        righe = [b for b in self.brani()
                 if APP.titolo_confronto(b["title"]) == APP.titolo_confronto("Till I Collapse")
                 and APP.artisti_compatibili(b["artist"], "Eminem")]
        self.assertEqual(len(righe), 1, "una riga sola per «Till I Collapse»")
        riga = righe[0]
        self.assertTrue(riga["local_file"], "la riga unita ha il file locale")
        self.assertTrue(riga["relation_count"] >= 1, "e conserva il campionamento")

    def test_ogni_campionamento_punta_a_righe_esistenti(self):
        stato, rels = http_json("/db/relations")
        self.assertEqual(stato, 200)
        id_esistenti = {b["id"] for b in self.brani()}
        for r in rels:
            with self.subTest(rel=r["id"]):
                self.assertIn(r["derivative_song_id"], id_esistenti)
                self.assertIn(r["source_song_id"], id_esistenti)

    def test_la_pagina_servita_ha_il_confronto_nuovo(self):
        with urllib.request.urlopen(SAMPLELAB_URL + "/", timeout=10) as r:
            html = r.read().decode("utf-8")
        self.assertIn('id="rel-compare-modal"', html)
        self.assertIn("function apriConfrontoCampione", html)


if __name__ == "__main__":
    unittest.main(verbosity=2)

