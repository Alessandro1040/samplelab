"""Test della scheda canzone: la schermata che apre «tutto quello che il database
sa» di un brano (pagina `/scheda`, pulsante «📄 Scheda» nella tabella Database).

Richiesta di Alessandro (18/09/2026): «fai in modo che su ogni canzone, nel
database, compaia la possibilità di cliccare su un altro pulsante che ti apre un
ulteriore schermata che contiene tutte le tracce stems di cui è composto,
eventuali remix e cover di tale canzone e cose salvate nel database da whosampled
(campionamenti)».

La schermata è `scheda.html` (rotta `/scheda?song=<id>`) e i dati li dà il nuovo
endpoint `/db/songs/<id>/scheda`, che mette insieme:
`stem_sessions` + `stem_tracks` (e la cartella di Demucs su disco),
`sample_relations` per campionamenti, remix e cover, `audio_analyses`.

Questo file prova:
1. `TestClassificazione` — le funzioni pure dell'app vera (caricata con
   importlib: il nome «app (2).py» con lo spazio non è importabile normalmente):
   cosa è un sample, un remix e una cover, i ruoli, il titolo base e i candidati.
2. `TestFunzioniPagina` — le funzioni pure di `scheda.html`, estratte dalla
   pagina ed eseguite DAVVERO con JavaScriptCore (`osascript -l JavaScript`).
3. `TestCablaggio` — il pulsante nella tabella del database, le sezioni della
   pagina e gli handler esposti su `window` (dentro la funzione anonima gli
   `onclick` non li vedrebbero).
4. `TestSchedaConDati` — l'endpoint vero, con un database di prova COMPLETO
   (stem con file veri e file mancanti, una relazione per gruppo, analisi,
   candidati): si chiama con il test client di Flask su DB e cartella stem
   temporanei, senza toccare la libreria.
5. `TestEndpointVivo` — se l'app è attiva: la pagina e l'endpoint su una canzone
   vera (default http://localhost:5070, variabile SAMPLELAB_URL).

Esecuzione (dalla cartella di SampleLab):
    python3 -m unittest -v test_scheda_canzone
"""
import importlib.util
import json
import os
import re
import shutil
import sqlite3
import subprocess
import unittest
import urllib.error
import urllib.parse
import urllib.request

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
APP_PATH = os.path.join(BASE_DIR, "app (2).py")
PAGINA_PATH = os.path.join(BASE_DIR, "scheda.html")
INDEX_PATH = os.path.join(BASE_DIR, "index (2).html")
SAMPLELAB_URL = os.environ.get("SAMPLELAB_URL", "http://localhost:5070")
HA_OSASCRIPT = shutil.which("osascript") is not None


def load_app():
    """Carica il modulo dell'app dal file (il nome con spazio non conta)."""
    spec = importlib.util.spec_from_file_location("samplelab_app2_scheda", APP_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


APP = load_app()

def leggi(percorso):
    with open(percorso, encoding="utf-8") as fh:
        return fh.read()


# ── il runner JavaScript (stesso schema di test_player_hero.py) ──────────────
def _blocco(src, inizio, apri, chiudi, cosa):
    i = src.index(apri, inizio)
    liv, j = 0, i
    while j < len(src):
        if src[j] == apri:
            liv += 1
        elif src[j] == chiudi:
            liv -= 1
            if liv == 0:
                return src[i:j + 1]
        j += 1
    raise AssertionError("parentesi non bilanciate in %s" % cosa)


def estrai_funzione(src, nome):
    m = re.search(r"(?:async\s+)?function\s+" + re.escape(nome) + r"\s*\(", src)
    if not m:
        raise AssertionError("funzione %s assente in %s" % (nome, PAGINA_PATH))
    inizio_corpo = src.index("{", m.end() - 1)
    corpo = _blocco(src, m.end() - 1, "{", "}", nome)
    return src[m.start(): inizio_corpo + len(corpo)]


def estrai_oggetto(src, nome):
    m = re.search(r"const\s+" + re.escape(nome) + r"\s*=\s*\{", src)
    if not m:
        raise AssertionError("costante %s assente in %s" % (nome, PAGINA_PATH))
    return _blocco(src, m.end() - 1, "{", "}", nome)


def esegui_js(codice, nome_file="/tmp/test_scheda_canzone.js"):
    """Esegue un frammento di JavaScript con JavaScriptCore e torna il JSON finale."""
    with open(nome_file, "w", encoding="utf-8") as out:
        out.write(codice + "\n0;\n")
    r = subprocess.run(["osascript", "-l", "JavaScript", nome_file],
                       capture_output=True, text=True)
    righe = ((r.stdout or "") + (r.stderr or "")).strip().splitlines()
    if not righe:
        raise AssertionError("nessun output da JavaScriptCore: %s" % (r.stderr or "")[:200])
    return json.loads(righe[-1])


# ── casi scritti a mano per la classificazione (Python, funzioni dell'app) ───
CASI_CLASSIFICAZIONE = [
    # (relazione, direzione, gruppo atteso)
    ({"category": "SAMPLE"}, "derivative", "sample"),
    ({"category": "STEM_REUSE"}, "derivative", "sample"),
    ({"category": "BEAT_CHANGE"}, "source", "sample"),
    ({"category": ""}, "derivative", "sample"),
    ({"category": "VOCAL_COVER"}, "source", "cover"),
    ({"category": "FULL_REMAKE"}, "derivative", "cover"),
    ({"category": "INSTRUMENT_REMAKE"}, "source", "cover"),
    ({"category": "SAMPLE", "transformation": "remixed"}, "derivative", "remix"),
    ({"category": "SAMPLE", "notes": "Remix ufficiale del 2005"}, "source", "remix"),
    ({"category": "SAMPLE", "relation_type": "remix"}, "derivative", "remix"),
    ({"category": "", "relation_type": "cover"}, "source", "cover"),
    # il titolo dell'ALTRA canzone conta solo se l'altra è quella che deriva
    ({"category": "SAMPLE", "other_title": "Famoso (Remix)"}, "source", "remix"),
    ({"category": "SAMPLE", "other_title": "Famoso (Remix)"}, "derivative", "sample"),
    ({"category": "SAMPLE", "other_title": "Famoso [Cover]"}, "source", "cover"),
    # «Undercover» non è una cover: parola intera, non pezzo di parola
    ({"category": "SAMPLE", "other_title": "Undercover"}, "source", "sample"),
    ({}, "derivative", "sample"),
]
CASI_ARTISTI_DIVERSI = [
    ("Eminem", "Eminem", False),
    ("Eminem / D12", "D12", False),
    ("Eminem", "Salmo", True),
    ("", "Salmo", False),
    ("Salmo", "", False),
    ("Brano locale", "Eminem", True),
]
BRANI_VARIANTI = [
    {"id": "s1", "title": "Mosh", "artist": "Eminem", "album": "Encore", "year": 2004, "local_file": "mosh.mp3"},
    {"id": "s2", "title": "Mosh (Remix)", "artist": "Eminem", "album": "", "year": 2005, "local_file": "mosh remix.mp3"},
    {"id": "s3", "title": "Mosh", "artist": "Salmo", "album": "", "year": 2018, "local_file": "mosh salmo.mp3"},
    {"id": "s4", "title": "MOSH [Live]", "artist": "Eminem", "album": "", "year": "", "local_file": ""},
    {"id": "s5", "title": "Mosh", "artist": "Eminem", "album": "Encore", "year": 2004, "local_file": "mosh2.mp3"},
    {"id": "s6", "title": "Tutt'altro brano", "artist": "Tizio", "album": "", "year": "", "local_file": "x.mp3"},
]
CANZONE_VARIANTI = {"id": "s1", "title": "Mosh", "artist": "Eminem"}


# ── il database di prova: stem (con file veri e mancanti), una relazione per
#    gruppo, analisi, candidati. Tutto in una cartella temporanea: la libreria
#    vera non viene mai toccata.
CANZONE_ID = "song_prova"
CANZONE_FILE = "canzone di prova.mp3"
CARTELLA_STEM = "canzone di prova"          # Demucs usa il nome del file senza estensione

BRANI_DB = [
    (CANZONE_ID, "Canzone di prova", "Artista Prova", "Album Prova", 2020, CANZONE_FILE,
     "https://www.whosampled.com/artista-prova/canzone-di-prova/"),
    ("song_fonte", "Brano Fonte", "Fonte Artist", "Album Fonte", 1995, "", ""),
    ("song_remixato", "Brano Remixato", "Fonte Artist", "", 2011, "", ""),
    ("song_cover", "Canzone di prova Acustica", "Altra Band", "", 2019, "", ""),
    ("song_remix2", "Canzone di prova (Remix)", "Quarto Artista", "", 2021, "", ""),
    ("song_uso", "Brano che la usa", "Terzo Artista", "", 2022, "", ""),
    ("song_dup", "Canzone di prova", "Artista Prova", "Album Prova", 2020, "", ""),
    ("song_seg", "Canzone di prova", "Tizio", "", 2018, "", ""),
]
SESSIONE_ID = "sess_prova"
# (id, song_id, stato, modello, percentuale)
SESSIONI_DB = [(SESSIONE_ID, CANZONE_ID, "done", "htdemucs", 100)]
# (id, stem_type, filename, il file esiste su disco?)
TRACCE_DB = [
    ("st_vocals", "vocals", "vocals.mp3", True),
    ("st_drums", "drums", "drums.mp3", True),
    ("st_bass", "bass", "bass.mp3", False),
    ("st_other", "other", "other.mp3", False),
]
FILE_STEM_EXTRA = "piano.mp3"               # su disco ma NON registrato nel database
# (id, derivato, fonte, categoria, trasformazione, note, verificata a mano)
RELAZIONI_DB = [
    ("rel_uso", CANZONE_ID, "song_fonte", "SAMPLE", "", "", 1),
    ("rel_remix_mio", CANZONE_ID, "song_remixato", "SAMPLE", "remixed", "", 0),
    ("rel_cover_altrui", "song_cover", CANZONE_ID, "VOCAL_COVER", "", "", 0),
    ("rel_remix_altrui", "song_remix2", CANZONE_ID, "SAMPLE", "", "", 0),
    ("rel_uso_altrui", "song_uso", CANZONE_ID, "SAMPLE", "", "", 0),
]
ANALISI_DB = [("an_1", CANZONE_ID, "librosa", 92.5, "A Minor", 0.83)]


def crea_db_di_prova(base):
    """Crea database + cartella degli stem di prova in `base`. Ritorna (db, stems)."""
    db_path = os.path.join(base, "samplelab di prova.db")
    stems_dir = os.path.join(base, "stems")
    cartella = os.path.join(stems_dir, "htdemucs", CARTELLA_STEM)
    os.makedirs(cartella, exist_ok=True)
    for _id, _tipo, nome, esiste in TRACCE_DB:
        if esiste:
            with open(os.path.join(cartella, nome), "wb") as fh:
                fh.write(b"prova" * 10)
    with open(os.path.join(cartella, FILE_STEM_EXTRA), "wb") as fh:
        fh.write(b"prova" * 5)

    APP.DB_PATH = db_path
    APP.init_db()
    with sqlite3.connect(db_path) as c:
        for sid, titolo, artista, album, anno, locale, ws in BRANI_DB:
            c.execute("INSERT INTO songs(id,title,artist,album,year,local_file,whosampled_url) "
                      "VALUES(?,?,?,?,?,?,?)", (sid, titolo, artista, album, anno, locale, ws))
        for sess, sid, stato, modello, pct in SESSIONI_DB:
            c.execute("INSERT INTO stem_sessions(id,song_id,model_name,status,progress_percent,"
                      "output_folder,created_at) VALUES(?,?,?,?,?,?,datetime('now'))",
                      (sess, sid, modello, stato, pct, os.path.join(stems_dir, "htdemucs")))
        for tid, tipo, nome, _esiste in TRACCE_DB:
            c.execute("INSERT INTO stem_tracks(id,session_id,stem_type,file_path,file_size_bytes) "
                      "VALUES(?,?,?,?,?)", (tid, SESSIONE_ID, tipo, os.path.join(cartella, nome), 50))
        for rid, deriv, fonte, categoria, trasf, note, verif in RELAZIONI_DB:
            c.execute("INSERT INTO sample_relations(id,derivative_song_id,source_song_id,relation_source,"
                      "relation_type,category,transformation,notes,verified_by_user,ws_url,"
                      "timestamp_derivative_start,timestamp_derivative_end,"
                      "timestamp_source_start,timestamp_source_end) "
                      "VALUES(?,?,?,'whosampled','samples',?,?,?,?,"
                      "'https://www.whosampled.com/x/',12.0,34.5,2.0,25.0)",
                      (rid, deriv, fonte, categoria, trasf, note, verif))
        for aid, sid, fonte, bpm, chiave, conf in ANALISI_DB:
            c.execute("INSERT INTO audio_analyses(id,song_id,source,bpm,musical_key,confidence) "
                      "VALUES(?,?,?,?,?,?)", (aid, sid, fonte, bpm, chiave, conf))
    return db_path, stems_dir


class TestSchedaConDati(unittest.TestCase):
    """L'endpoint vero, col test client di Flask su un database di prova."""

    @classmethod
    def setUpClass(cls):
        import tempfile
        cls.tmp = tempfile.mkdtemp(prefix="scheda_prova_")
        cls.db_originale = APP.DB_PATH
        cls.stems_originale = APP.STEMS_DIR
        _db, stems_dir = crea_db_di_prova(cls.tmp)
        APP.STEMS_DIR = stems_dir
        cls.client = APP.app.test_client()
        cls.risposta = cls.client.get("/db/songs/%s/scheda" % CANZONE_ID)
        cls.stato = cls.risposta.status_code
        cls.dati = cls.risposta.get_json()

    @classmethod
    def tearDownClass(cls):
        APP.DB_PATH = cls.db_originale
        APP.STEMS_DIR = cls.stems_originale
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def test_canzone_inesistente(self):
        r = self.client.get("/db/songs/non-esiste/scheda")
        self.assertEqual(r.status_code, 404)
        self.assertEqual(r.get_json()["error"], "Non trovata")

    def test_canzone_giusta(self):
        self.assertEqual(self.stato, 200, self.dati)
        self.assertEqual(self.dati["song"]["id"], CANZONE_ID)
        self.assertEqual(self.dati["song"]["title"], "Canzone di prova")
        self.assertEqual(self.dati["whosampled_url"],
                         "https://www.whosampled.com/artista-prova/canzone-di-prova/")

    def test_stem_dal_database_con_file_mancanti(self):
        stem = self.dati["stems"]
        self.assertEqual(len(stem["sessions"]), 1)
        self.assertEqual(stem["count_tracks"], 4)
        self.assertEqual(stem["count_missing"], 2)      # bass e other non sono su disco
        tracce = {t["stem_type"]: t for t in stem["sessions"][0]["tracks"]}
        self.assertTrue(tracce["vocals"]["exists"])
        self.assertFalse(tracce["bass"]["exists"])
        self.assertTrue(tracce["vocals"]["url"].startswith("/stream-stem/"))
        self.assertTrue(tracce["vocals"]["download_url"].startswith("/download-stem/"))
        # cartella e nome del file hanno gli spazi: devono arrivare quotati
        self.assertIn("canzone%20di%20prova", tracce["vocals"]["url"])

    def test_stem_trovati_solo_su_disco(self):
        disco = self.dati["stems"]["on_disk"]
        self.assertIsNotNone(disco)
        self.assertEqual([f["filename"] for f in disco["files"]],
                         ["drums.mp3", "piano.mp3", "vocals.mp3"])
        self.assertEqual(disco["non_registrati"], ["piano.mp3"])

    def test_campionamenti_usati_e_subiti(self):
        usati, subiti = self.dati["samples_used"], self.dati["sampled_by"]
        self.assertEqual([r["other_title"] for r in usati], ["Brano Fonte"])
        self.assertEqual(usati[0]["direzione"], "derivative")
        self.assertEqual(usati[0]["ruolo"], "questa canzone campiona l'altra")
        self.assertEqual(usati[0]["verified_by_user"], 1)
        self.assertTrue(usati[0]["ws_url"])
        self.assertEqual(usati[0]["timestamp_derivative_start"], 12.0)
        self.assertEqual([r["other_title"] for r in subiti], ["Brano che la usa"])
        self.assertEqual(subiti[0]["ruolo"], "l'altra campiona questa")

    def test_remix_e_cover(self):
        remix, cover = self.dati["remixes"], self.dati["covers"]
        self.assertEqual(sorted(r["other_title"] for r in remix),
                         ["Brano Remixato", "Canzone di prova (Remix)"])
        direzioni = {r["other_title"]: r["direzione"] for r in remix}
        self.assertEqual(direzioni["Brano Remixato"], "derivative")     # dal testo
        self.assertEqual(direzioni["Canzone di prova (Remix)"], "source")  # dal titolo
        self.assertEqual([r["other_title"] for r in cover], ["Canzone di prova Acustica"])
        self.assertEqual(cover[0]["ruolo"], "l'altra è una cover di questa")

    def test_varianti_e_duplicati(self):
        varianti = self.dati["varianti"]
        self.assertEqual([v["title"] for v in varianti],
                         ["Canzone di prova (Remix)", "Canzone di prova"])
        motivi = {v["id"]: v["motivo"] for v in varianti}
        self.assertEqual(motivi["song_remix2"], "nel titolo: remix")
        self.assertEqual(motivi["song_seg"], "artista diverso: Tizio")
        # song_dup ha titolo E artista uguali: è lo stesso brano, non una versione
        self.assertNotIn("song_dup", motivi)

    def test_analisi_conteggi_e_libreria_vera_intatta(self):
        self.assertEqual(len(self.dati["analyses"]), 1)
        self.assertEqual(self.dati["analyses"][0]["bpm"], 92.5)
        self.assertEqual(self.dati["analyses"][0]["source"], "librosa")
        self.assertEqual(self.dati["counts"],
                         {"stem_sessions": 1, "stem_tracks": 4, "stem_missing": 2,
                          "samples_used": 1, "sampled_by": 1, "remixes": 2, "covers": 1,
                          "varianti": 2, "analyses": 1})
        with sqlite3.connect("file:%s?mode=ro" % self.db_originale, uri=True) as c:
            n = c.execute("SELECT COUNT(*) FROM songs").fetchone()[0]
        self.assertGreaterEqual(n, 800, "il database vero deve essere ancora al suo posto")


# ── il carico di prova per le funzioni della pagina (stessa forma dell'endpoint)
PAYLOAD_PAGINA = {
    "song": {"id": "song_1", "title": "Canzone di prova", "artist": "Artista Prova / Altro",
             "album": "Album Prova", "year": 2020, "bpm": 92.5, "bpm_verified": 1,
             "musical_key": "A Minor", "duration": 215, "local_file": "prova.mp3"},
    "stems": {
        "sessions": [{
            "id": "sess_1", "model_name": "htdemucs", "status": "done",
            "created_at": "2026-09-18 00:00:00",
            "tracks": [
                {"id": "t1", "stem_type": "vocals", "filename": "vocals.mp3", "exists": True,
                 "size_on_disk": 1048576, "url": "/stream-stem/c/vocals.mp3",
                 "download_url": "/download-stem/c/vocals.mp3"},
                {"id": "t2", "stem_type": "other", "filename": "other.mp3", "exists": False,
                 "size_on_disk": None, "file_size_bytes": 0, "url": "", "download_url": ""},
                {"id": "t3", "stem_type": "bass", "filename": "bass.mp3", "exists": True,
                 "size_on_disk": 524288, "url": "/stream-stem/c/bass.mp3",
                 "download_url": "/download-stem/c/bass.mp3"},
            ]}],
        "on_disk": {"folder": "c", "non_registrati": ["piano.mp3"], "files": [
            {"filename": "vocals.mp3", "stem_type": "vocals", "size_on_disk": 1048576,
             "registrato": True, "url": "/stream-stem/c/vocals.mp3",
             "download_url": "/download-stem/c/vocals.mp3"},
            {"filename": "piano.mp3", "stem_type": "piano", "size_on_disk": 2048,
             "registrato": False, "url": "/stream-stem/c/piano.mp3",
             "download_url": "/download-stem/c/piano.mp3"}]},
        "count_tracks": 3, "count_missing": 1, "has_stems": True},
    "samples_used": [{
        "id": "rel_1", "other_id": "song_2", "other_title": "Brano Fonte", "other_artist": "Fonte Artist",
        "other_year": 1995, "direzione": "derivative", "gruppo": "sample",
        "ruolo": "questa canzone campiona l'altra", "category": "SAMPLE", "verified_by_user": 1,
        "ws_url": "https://www.whosampled.com/x/", "yt_url_source": "https://youtu.be/fonte",
        "timestamp_derivative_start": 12.0, "timestamp_derivative_end": 34.5,
        "timestamp_source_start": 2.0, "timestamp_source_end": 25.0, "notes": ""}],
    "sampled_by": [{
        "id": "rel_2", "other_id": "song_3", "other_title": "Brano che la usa", "other_artist": "Terzo",
        "direzione": "source", "gruppo": "sample", "ruolo": "l'altra campiona questa",
        "category": "SAMPLE", "verified_by_user": 0, "ws_url": "",
        "yt_url_derivative": "https://youtu.be/uso",
        "timestamp_derivative_start": None, "timestamp_derivative_end": None,
        "timestamp_source_start": None, "timestamp_source_end": None}],
    "remixes": [{
        "id": "rel_3", "other_id": "song_4", "other_title": "Canzone di prova (Remix)",
        "other_artist": "Quarto", "direzione": "source", "gruppo": "remix",
        "ruolo": "l'altra è un remix di questa", "category": "SAMPLE", "verified_by_user": 0}],
    "covers": [],
    "varianti": [{"id": "song_5", "title": "Canzone di prova (Cover)", "artist": "Quinto",
                  "album": "", "year": 2019, "local_file": "cover.mp3", "motivo": "nel titolo: cover"}],
    "analyses": [{"id": "an_1", "bpm": 92.5, "musical_key": "A Minor", "source": "librosa",
                  "confidence": 0.83, "analyzed_at": "2026-09-18 00:00:00"}],
    "whosampled_url": "https://www.whosampled.com/x/",
    "counts": {"stem_sessions": 1, "stem_tracks": 3, "stem_missing": 1, "samples_used": 1,
               "sampled_by": 1, "remixes": 1, "covers": 0, "varianti": 1, "analyses": 1},
}

TIPI_STEM = ["vocals", "DRUMS", "other", "piano", "", "  BASSO "]
ETICHETTE_STEM_ATTESE = {
    "vocals": "🎤 Voce", "DRUMS": "🥁 Batteria", "other": "🎹 Altro",
    "piano": "🎵 Piano", "": "🎵 Traccia", "  BASSO ": "🎵 Basso",
}
BYTE_ATTESI = {"zero": 0, "nullo": None, "negativo": -5, "piccolo": 512, "kilo": 1024,
               "unoemezzo": 1536, "mega": 1048576, "giga": 1073741824}
BYTE_LABEL = {"zero": "—", "nullo": "—", "negativo": "—", "piccolo": "512 B",
              "kilo": "1,0 KB", "unoemezzo": "1,5 KB", "mega": "1,0 MB", "giga": "1,0 GB"}
INTERVALLI = {
    "tutti": [12, 34.5], "solo_inizio": [12, None], "solo_fine": [None, 34.5],
    "niente": [None, None], "vuoti": ["", ""], "zeri": [0, 0],
}
INTERVALLI_LABEL = {
    "tutti": "0:12 → 0:34", "solo_inizio": "da 0:12", "solo_fine": "fino a 0:34",
    "niente": "", "vuoti": "", "zeri": "0:00 → 0:00",
}
CATEGORIE_ATTESE = {
    "SAMPLE": "Sample", "sample": "Sample", "vocal_cover": "Cover", "": "Sample",
    "FULL_REMAKE": "Reinterpretazione", "BEAT_CHANGE": "Beat change", "strana": "Strana",
}
FONTI_ATTESE = {"librosa": "🎛️ librosa", "tunebat": "🌐 Tunebat", "demucs": "✂️ Demucs",
                "": "—", "altro": "altro"}


class TestClassificazione(unittest.TestCase):
    """Le funzioni pure dell'app vera (senza avviare il server)."""

    def test_classifica_relazione(self):
        for rel, direzione, atteso in CASI_CLASSIFICAZIONE:
            with self.subTest(rel=rel, direzione=direzione):
                self.assertEqual(APP.classifica_relazione(rel, direzione), atteso)

    def test_ruolo_relazione(self):
        attesi = {
            ("sample", "derivative"): "questa canzone campiona l'altra",
            ("sample", "source"): "l'altra campiona questa",
            ("remix", "derivative"): "questa canzone è un remix dell'altra",
            ("remix", "source"): "l'altra è un remix di questa",
            ("cover", "derivative"): "questa canzone è una cover dell'altra",
            ("cover", "source"): "l'altra è una cover di questa",
        }
        for (gruppo, direzione), atteso in attesi.items():
            with self.subTest(gruppo=gruppo, direzione=direzione):
                self.assertEqual(APP.ruolo_relazione(gruppo, direzione), atteso)

    def test_titolo_base(self):
        attesi = {
            "Mosh": "mosh",
            "Mosh (Remix)": "mosh",
            "MOSH  [Live]": "mosh",
            "Mosh (feat. Tizio)": "mosh",
            "Sam (Is Dead)": "sam is dead",
            "Eminem - Without Me (Official Video)": "eminem without me",
            "": "",
        }
        for titolo, atteso in attesi.items():
            with self.subTest(titolo=titolo):
                self.assertEqual(APP.titolo_base(titolo), atteso)

    def test_artisti_diversi(self):
        for a, b, atteso in CASI_ARTISTI_DIVERSI:
            with self.subTest(a=a, b=b):
                self.assertIs(APP.artisti_diversi(a, b), atteso)

    def test_varianti_trovate_dal_titolo(self):
        fuori = APP.possibili_varianti(CANZONE_VARIANTI, BRANI_VARIANTI)
        self.assertEqual([v["id"] for v in fuori], ["s2", "s4", "s3"])
        per_id = {v["id"]: v for v in fuori}
        self.assertEqual(per_id["s2"]["motivo"], "nel titolo: remix")
        self.assertEqual(per_id["s4"]["motivo"], "nel titolo: live")
        self.assertEqual(per_id["s3"]["motivo"], "artista diverso: Salmo")
        # s5: stesso titolo e stesso artista, senza marcatore → non è una variante
        self.assertNotIn("s5", per_id)
        self.assertNotIn("s6", per_id)

    def test_varianti_con_artista_segnaposto(self):
        # con «Brano locale» il confronto fra artisti non dice niente: si tengono
        # solo i candidati che hanno un marcatore nel titolo
        canzone = {"id": "s1", "title": "Mosh", "artist": "Brano locale"}
        fuori = APP.possibili_varianti(canzone, BRANI_VARIANTI)
        self.assertEqual([v["id"] for v in fuori], ["s2", "s4"])

    def test_varianti_titolo_troppo_corto(self):
        self.assertEqual(APP.possibili_varianti({"id": "x", "title": "ab", "artist": "Tizio"}, BRANI_VARIANTI), [])
@unittest.skipUnless(HA_OSASCRIPT, "JavaScriptCore (osascript) non disponibile")
class TestFunzioniPagina(unittest.TestCase):
    """Le funzioni di scheda.html, eseguite davvero, sui casi scritti a mano."""

    risultati = {}

    @classmethod
    def setUpClass(cls):
        src = leggi(PAGINA_PATH)
        js = "\n".join([
            "const ETICHETTE_STEM = %s;" % estrai_oggetto(src, "ETICHETTE_STEM"),
            "const ORDINE_STEM = %s;" % estrai_oggetto(src, "ORDINE_STEM"),
            estrai_funzione(src, "fmtTime"),
            estrai_funzione(src, "etichettaStem"),
            estrai_funzione(src, "ordineStem"),
            estrai_funzione(src, "formattaByte"),
            estrai_funzione(src, "formattaIntervallo"),
            estrai_funzione(src, "etichettaCategoria"),
            estrai_funzione(src, "etichettaFonte"),
            estrai_funzione(src, "righeStem"),
            estrai_funzione(src, "intervalliRelazione"),
            estrai_funzione(src, "rigaRelazione"),
            estrai_funzione(src, "blocchiRelazioni"),
            estrai_funzione(src, "righeVarianti"),
        ])
        js += """
const p = %s;
const out = {etichette:{}, ordini:{}, byte:{}, intervalli:{}, categorie:{}, fonti:{},
             stem: righeStem(p), blocchi: blocchiRelazioni(p), varianti: righeVarianti(p),
             ivDeriv: intervalliRelazione(p.samples_used[0]),
             ivSource: intervalliRelazione(p.sampled_by[0])};
for (const t of %s) { out.etichette[t] = etichettaStem(t); out.ordini[t] = ordineStem(t); }
const byte = %s; for (const k in byte) { out.byte[k] = formattaByte(byte[k]); }
const iv = %s; for (const k in iv) { out.intervalli[k] = formattaIntervallo(iv[k][0], iv[k][1]); }
const cat = %s; for (const k in cat) { out.categorie[k] = etichettaCategoria(k); }
const fonti = %s; for (const k in fonti) { out.fonti[k] = etichettaFonte(k); }
console.log(JSON.stringify(out));
""" % (json.dumps(PAYLOAD_PAGINA), json.dumps(TIPI_STEM), json.dumps(BYTE_ATTESI),
       json.dumps(INTERVALLI), json.dumps(CATEGORIE_ATTESE), json.dumps(FONTI_ATTESE))
        cls.risultati = esegui_js(js)

    def test_etichette_e_ordine_degli_stem(self):
        for tipo, atteso in ETICHETTE_STEM_ATTESE.items():
            with self.subTest(tipo=tipo):
                self.assertEqual(self.risultati["etichette"][tipo], atteso)
        self.assertEqual([self.risultati["ordini"][t] for t in
                          ("vocals", "DRUMS", "other", "piano", "")], [0, 1, 3, 9, 9])

    def test_dimensioni_leggibili(self):
        for chiave, atteso in BYTE_LABEL.items():
            with self.subTest(caso=chiave):
                self.assertEqual(self.risultati["byte"][chiave], atteso)

    def test_intervalli_dei_timestamp(self):
        for chiave, atteso in INTERVALLI_LABEL.items():
            with self.subTest(caso=chiave):
                self.assertEqual(self.risultati["intervalli"][chiave], atteso)

    def test_categorie_e_fonti(self):
        for chiave, atteso in CATEGORIE_ATTESE.items():
            with self.subTest(categoria=chiave):
                self.assertEqual(self.risultati["categorie"][chiave], atteso)
        for chiave, atteso in FONTI_ATTESE.items():
            with self.subTest(fonte=chiave):
                self.assertEqual(self.risultati["fonti"][chiave], atteso)

    def test_righe_degli_stem(self):
        righe = self.risultati["stem"]
        # voce, basso, altro (dal database), poi il piano trovato solo su disco
        self.assertEqual([r["etichetta"] for r in righe],
                         ["🎤 Voce", "🎸 Basso", "🎹 Altro", "🎵 Piano"])
        self.assertEqual([r["origine"] for r in righe],
                         ["database", "database", "database", "disco"])
        self.assertEqual([r["esiste"] for r in righe], [True, True, False, True])
        self.assertEqual(righe[2]["url"], "", "un file mancante non deve avere un player")
        self.assertFalse(righe[3]["registrato"], "piano.mp3 non è in stem_tracks")
        self.assertEqual(len({r["chiave"] for r in righe}), len(righe),
                         "le chiavi delle righe devono essere uniche")

    def test_intervalli_visti_dalla_canzone(self):
        self.assertEqual(self.risultati["ivDeriv"], {"mio": "0:12 → 0:34", "altro": "0:02 → 0:25"})
        # l'altra relazione non ha timestamp: nessun intervallo da mostrare
        self.assertEqual(self.risultati["ivSource"], {"mio": "", "altro": ""})

    def test_blocchi_delle_relazioni(self):
        blocchi = self.risultati["blocchi"]
        self.assertEqual([b["chiave"] for b in blocchi],
                         ["remixes", "covers", "samples_used", "sampled_by"])
        self.assertTrue(all(b["vuoto"] for b in blocchi), "ogni gruppo deve spiegare il vuoto")
        self.assertEqual([len(b["righe"]) for b in blocchi], [1, 0, 1, 1])
        usato = blocchi[2]["righe"][0]
        self.assertEqual(usato["titolo"], "Brano Fonte")
        self.assertEqual(usato["ruolo"], "questa canzone campiona l'altra")
        self.assertEqual(usato["categoria"], "Sample")
        self.assertTrue(usato["verificato"])
        self.assertEqual(usato["intervallo"],
                         "questa canzone: 0:12 → 0:34 · l'altra: 0:02 → 0:25")
        self.assertEqual(usato["yt_url"], "https://youtu.be/fonte")
        # il remix visto dall'altra parte prende il video del brano derivato
        self.assertEqual(blocchi[0]["righe"][0]["yt_url"], "")
        self.assertIn("cover", blocchi[1]["vuoto"])

    def test_righe_delle_varianti(self):
        varianti = self.risultati["varianti"]
        self.assertEqual(len(varianti), 1)
        self.assertEqual(varianti[0]["motivo"], "nel titolo: cover")
        self.assertTrue(varianti[0]["in_libreria"])



class TestCablaggio(unittest.TestCase):
    """Il pulsante in tabella, le sezioni della pagina e gli handler esposti."""

    @classmethod
    def setUpClass(cls):
        cls.pagina = leggi(PAGINA_PATH)
        cls.index = leggi(INDEX_PATH)
        with open(APP_PATH, encoding="utf-8") as fh:
            cls.app = fh.read()

    def test_pulsante_su_ogni_riga_del_database(self):
        # il link sta nella cella delle azioni, fuori da ogni condizione: c'è su
        # ogni canzone, anche su quelle senza file locale
        self.assertIn('href="scheda.html?song=${encodeURIComponent(s.id)}"', self.index)
        self.assertIn(">📄 Scheda</a>", self.index)
        self.assertIn("a.db-stem-btn{display:inline-block;text-decoration:none}", self.index)

    def test_sezioni_della_pagina(self):
        for pezzo in ('id="hero"', 'id="stem-body"', 'id="varianti-body"', 'id="sample-body"',
                      'id="analisi-body"', 'id="mixer"', 'id="mixer-play"'):
            self.assertIn(pezzo, self.pagina)
        for titolo in ("Tracce di cui è composta", "Remix e cover",
                       "Campionamenti (WhoSampled)", "Analisi audio"):
            self.assertIn(titolo, self.pagina)

    def test_rotta_dellapp_e_endpoint(self):
        self.assertIn('@app.route("/scheda")', self.app)
        self.assertIn('os.path.join(BASE_DIR, "scheda.html")', self.app)
        self.assertIn('@app.route("/db/songs/<song_id>/scheda", methods=["GET"])', self.app)
        self.assertIn("def db_song_scheda(song_id):", self.app)

    def test_ogni_onclick_e_esposto_su_window(self):
        # dentro la funzione anonima della pagina gli handler scritti nell'HTML
        # non si vedono (è il motivo per cui in browse.html il pulsante
        # «↑/↓ Crescente» non risponde): qui si controlla che siano esposti tutti
        nomi = set(re.findall(r'on(?:click|input|change)="\s*([A-Za-z_$][\w$]*)\s*\(', self.pagina))
        self.assertTrue(nomi, "la pagina usa handler scritti nell'HTML")
        m = re.search(r"Object\.assign\(window,\{([^}]*)\}", self.pagina)
        self.assertIsNotNone(m, "gli handler inline devono essere esposti su window")
        for nome in sorted(nomi):
            with self.subTest(handler=nome):
                self.assertIn(nome, m.group(1), "manca window.%s" % nome)
                self.assertRegex(self.pagina, r"(?:async\s+)?function\s+%s\s*\(" % re.escape(nome))

    def test_la_pagina_non_si_ricarica_mentre_gli_stem_suonano(self):
        self.assertIn("if(stemInRiproduzione().length){ attesaRicaricamento=true; return; }",
                      self.pagina)
        self.assertIn("setInterval(autoAggiorna,4000)", self.pagina)
        self.assertIn("/db/changed", self.pagina)

    def test_la_pagina_apre_dal_pulsante_e_dal_link_diretto(self):
        self.assertIn("const songId=(params.get('song')||'').trim();", self.pagina)
        self.assertIn("'scheda.html?song='+encodeURIComponent(id||'')", self.pagina)


def app_is_up(url):
    try:
        urllib.request.urlopen(url + "/db/stats", timeout=3)
        return True
    except Exception:
        return False


@unittest.skipUnless(app_is_up(SAMPLELAB_URL), "app non attiva su " + SAMPLELAB_URL)
class TestEndpointVivo(unittest.TestCase):
    """La pagina e l'endpoint sull'app vera (sola lettura: non scrive niente)."""

    @classmethod
    def setUpClass(cls):
        with urllib.request.urlopen(SAMPLELAB_URL + "/db/songs", timeout=60) as r:
            cls.brani = json.load(r)
        cls.brano = cls.brani[0]
        url = "%s/db/songs/%s/scheda" % (SAMPLELAB_URL, urllib.parse.quote(cls.brano["id"]))
        with urllib.request.urlopen(url, timeout=60) as r:
            cls.stato = r.status
            cls.dati = json.load(r)

    def test_pagina_servita(self):
        with urllib.request.urlopen(SAMPLELAB_URL + "/scheda", timeout=30) as r:
            self.assertEqual(r.status, 200)
            corpo = r.read().decode("utf-8", "replace")
        self.assertIn("Tracce di cui è composta", corpo)
        self.assertIn("Campionamenti (WhoSampled)", corpo)

    def test_scheda_di_una_canzone_vera(self):
        self.assertEqual(self.stato, 200)
        self.assertEqual(self.dati["song"]["id"], self.brano["id"])
        for chiave in ("stems", "samples_used", "sampled_by", "remixes", "covers",
                       "varianti", "analyses", "counts"):
            self.assertIn(chiave, self.dati)
        c = self.dati["counts"]
        self.assertEqual(c["samples_used"], len(self.dati["samples_used"]))
        self.assertEqual(c["sampled_by"], len(self.dati["sampled_by"]))
        self.assertEqual(c["remixes"], len(self.dati["remixes"]))
        self.assertEqual(c["covers"], len(self.dati["covers"]))
        self.assertEqual(c["varianti"], len(self.dati["varianti"]))
        self.assertEqual(c["stem_tracks"], self.dati["stems"]["count_tracks"])
        # ogni relazione è classificata e ha un ruolo da mostrare
        for gruppo in ("samples_used", "sampled_by", "remixes", "covers"):
            for riga in self.dati[gruppo]:
                self.assertIn(riga["gruppo"], ("sample", "remix", "cover"))
                self.assertTrue(riga["ruolo"])
                self.assertTrue(riga["other_title"])

    def test_canzone_inesistente(self):
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            urllib.request.urlopen(SAMPLELAB_URL + "/db/songs/non-esiste/scheda", timeout=30)
        self.assertEqual(ctx.exception.code, 404)

    def test_libreria_intatta(self):
        with urllib.request.urlopen(SAMPLELAB_URL + "/db/stats", timeout=30) as r:
            self.assertGreaterEqual(json.load(r)["songs"], 800)



@unittest.skipUnless(HA_OSASCRIPT, "JavaScriptCore (osascript) non disponibile")
class TestMixerStem(unittest.TestCase):
    """Il mixer degli stem, eseguito con un DOM finto: sync, mute, volume, stop.

    Le righe qui sotto sostituiscono document/window/audio con finzioni minime
    (stessa idea dei test di funzione pura, un gradino più in là): quello che si
    controlla è il comportamento — «Suona tutti insieme» fa partire le tracce
    nello stesso istante, mutare una traccia non ferma le altre, Stop riporta
    tutto a zero e nasconde la barra.
    """

    risultati = {}

    @classmethod
    def setUpClass(cls):
        src = leggi(PAGINA_PATH)
        js = "\n".join([
            estrai_funzione(src, "fmtTime"),
            estrai_funzione(src, "audioDi"),
            estrai_funzione(src, "stemInRiproduzione"),
            estrai_funzione(src, "aggiornaBottoniStem"),
            estrai_funzione(src, "mostraMixer"),
            estrai_funzione(src, "stemPlay"),
            estrai_funzione(src, "stemMuto"),
            estrai_funzione(src, "stemVolume"),
            estrai_funzione(src, "mostraTempo"),
            estrai_funzione(src, "mixerToggle"),
            estrai_funzione(src, "mixerStop"),
        ])
        js += """
// ── DOM finto ──
function fakeEl(id){
  return {id:id, textContent:'', title:'', volume:1, muted:false, paused:true, ended:false,
          currentTime:0, duration:120,
          classList:{c:{}, add(x){this.c[x]=true}, remove(x){delete this.c[x]},
                     toggle(x,on){if(on)this.c[x]=true; else delete this.c[x]},
                     contains(x){return !!this.c[x]}},
          play(){this.paused=false; return {catch(){}}},
          pause(){this.paused=true}};
}
const elementi={};
const document={getElementById:id=>{ if(!elementi[id]) elementi[id]=fakeEl(id); return elementi[id]; }};
const window={};
let intervalli=0;
const setInterval=()=>{intervalli++; return 1;};
const clearInterval=()=>{};
const stemAudio={};
let stemRows=[{etichetta:'🎤 Voce',filename:'vocals.mp3'},{etichetta:'🥁 Batteria',filename:'drums.mp3'}];
let mixerTimer=null;      // dichiarata nella pagina, qui serve al mixer
for(let i=0;i<stemRows.length;i++) stemAudio[i]=fakeEl('stem-audio-'+i);

const out={};
// 1) «Suona tutti insieme»: tutte le tracce partono, stesso istante
mixerToggle();
out.dopoPlay=stemRows.map((_,i)=>[stemAudio[i].paused, stemAudio[i].currentTime]);
out.mixerVisibile=document.getElementById('mixer').classList.contains('visible');
out.intervalli=intervalli;
// 2) mute e volume non fermano le altre tracce
stemAudio[0].currentTime=30; stemAudio[1].currentTime=10;
stemMuto(1);
out.muto=stemRows.map((_,i)=>stemAudio[i].muted);
out.mutoBottone=document.getElementById('stem-mute-1').textContent;
stemVolume(0,40);
out.volume=stemAudio[0].volume;
stemMuto(1);
out.smuto=stemAudio[1].muted;
// 3) pausa e ripresa: si riallineano sullo stesso punto
mixerToggle();
out.dopoPausa=stemRows.map((_,i)=>stemAudio[i].paused);
mixerToggle();
out.ripresi=stemRows.map((_,i)=>[stemAudio[i].paused, stemAudio[i].currentTime]);
// 4) una traccia da sola
mixerStop();
stemPlay(0);
out.solo=[stemAudio[0].paused, stemAudio[1].paused];
out.pausaEtichetta=document.getElementById('stem-play-0').textContent;
stemPlay(0);
out.soloRipausa=stemAudio[0].paused;
// 5) stop: tutto a zero e barra nascosta
stemPlay(1);
stemAudio[1].currentTime=42;
mixerStop();
out.dopoStop=stemRows.map((_,i)=>[stemAudio[i].paused, stemAudio[i].currentTime]);
out.mixerNascosto=!document.getElementById('mixer').classList.contains('visible');
console.log(JSON.stringify(out));
"""
        cls.risultati = esegui_js(js)

    def test_suona_tutti_insieme(self):
        self.assertEqual(self.risultati["dopoPlay"], [[False, 0], [False, 0]])
        self.assertTrue(self.risultati["mixerVisibile"], "la barra del mixer deve comparire")
        self.assertEqual(self.risultati["intervalli"], 1, "il cronometro si crea una volta sola")

    def test_mute_e_volume_non_fermano_le_altre(self):
        self.assertEqual(self.risultati["muto"], [False, True])
        self.assertEqual(self.risultati["mutoBottone"], "🔇")
        self.assertAlmostEqual(self.risultati["volume"], 0.4, places=5)
        self.assertFalse(self.risultati["smuto"])

    def test_pausa_e_ripresa_si_riallineano(self):
        self.assertEqual(self.risultati["dopoPausa"], [True, True])
        self.assertEqual(self.risultati["ripresi"], [[False, 30], [False, 30]])

    def test_una_traccia_da_sola(self):
        self.assertEqual(self.risultati["solo"], [False, True], "le altre tracce restano ferme")
        self.assertEqual(self.risultati["pausaEtichetta"], "⏸")
        self.assertTrue(self.risultati["soloRipausa"], "il secondo clic mette in pausa")

    def test_stop(self):
        self.assertEqual(self.risultati["dopoStop"], [[True, 0], [True, 0]])
        self.assertTrue(self.risultati["mixerNascosto"])

