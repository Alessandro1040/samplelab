"""Test del recupero di MINIATURA e DATI YouTube sulle righe già in libreria.

Richiesta di Alessandro del 19/09/2026: «le canzoni che scarichi da youtube, tipo
[CINEMATIC] NF Type Beat 2024 ＂Clown” (Prod. Raedius) non contengono miniatura
video e informazioni che stanno su youtube come tag, descrizione, ecc… puoi
sistemare?»

Perché mancavano: `arricchisci_riga_dal_video` completa la riga APPENA nata da un
download, mentre le righe già in libreria sono rimaste spoglie (921 su 945 senza
miniatura in `covers/`, 897 senza nemmeno un campo `yt_*`), e le pagine leggono
SOLO `cover_art_path`: l'URL della miniatura in `yt_thumbnail` non si usava da
nessuna parte. Da oggi (a) la riga si può completare a richiesta — pulsante 🖼 YT —
o in blocco per le righe che hanno già un link/id, e (b) la miniatura si vede
anche quando il file in `covers/` non c'è ancora.

Cosa copre questo file:
1. `fonte_video_riga` (PURA): prima il link della riga, poi l'id del video, e solo
   se non c'è né l'uno né l'altro «artista - titolo» (`da_link=False`, ricerca);
2. `info_video_riga` con un yt-dlp FINTO: con un link non si cerca niente, senza
   link si passa dalla ricerca, un video illeggibile diventa un motivo (non
   un'eccezione) e una riga senza titolo lo dice;
3. `recupera_dati_video` su un database TEMPORANEO: i campi `yt_*` scritti, la
   miniatura salvata in `covers/` col nome in `cover_art_path`, una copertina che
   c'è già non si tocca (`forzato=True` la rifà), il link trovato dalla ricerca
   resta scritto nella riga, e con `video=True` parte anche l'MP4;
4. `righe_da_recuperare` e `avvia_recupero_youtube`: chi è candidato e cosa gli
   manca, chi resta fuori (le righe senza link), il lavoro in blocco col progresso;
5. le ROTTE vere su un database temporaneo: `POST /db/songs/<id>/recupera_youtube`,
   `GET /db/recupera_youtube` (elenco, nessuna chiamata a YouTube) e
   `POST /db/recupera_youtube` (blocco);
6. il cablaggio (sorgenti): pulsante 🖼 YT su ogni riga, pannello nel tab
   Database, miniatura di riserva in `index (2).html`/`browse.html`/`scheda.html`
   e riquadro 📺 nel modale ✏️ Edit;
7. l'app VIVA in sola lettura: `/db/recupera_youtube`.

Esecuzione (dalla cartella di SampleLab):
    python3 -m unittest -v test_recupera_youtube
I test HTTP girano solo se l'app è attiva (default http://localhost:5070,
sovrascrivibile con la variabile SAMPLELAB_URL).
"""
import importlib.util
import json
import os
import shutil
import tempfile
import time
import types
import unittest
import urllib.request

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
APP_PATH = os.path.join(BASE_DIR, "app (2).py")
PAGINA_PATH = os.path.join(BASE_DIR, "index (2).html")
BROWSE_PATH = os.path.join(BASE_DIR, "browse.html")
SCHEDA_PATH = os.path.join(BASE_DIR, "scheda.html")
README_PATH = os.path.join(BASE_DIR, "README.md")
SAMPLELAB_URL = os.environ.get("SAMPLELAB_URL", "http://localhost:5070")


def load_app():
    """Carica il modulo dell'app dal file (il nome con spazio non conta)."""
    spec = importlib.util.spec_from_file_location("samplelab_app2_recupero", APP_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


APP = load_app()


def leggi(percorso):
    with open(percorso, encoding="utf-8") as f:
        return f.read()


def app_is_up(url):
    try:
        urllib.request.urlopen(url + "/db/stats", timeout=3)
        return True
    except Exception:
        return False


def http_json(path):
    """Chiama l'app VIVA (sola lettura) e torna il JSON."""
    with urllib.request.urlopen(SAMPLELAB_URL + path, timeout=30) as r:
        return json.loads(r.read().decode("utf-8"))


# L'info_dict di un video vero, ridotto ai campi che si salvano.
INFO = {
    "id": "IX7UWaSoVv0",
    "title": "50 Cent - Window Shopper",
    "upload_date": "20250915",
    "release_date": "20051115",
    "channel": "50 Cent",
    "channel_url": "https://www.youtube.com/channel/UCxxx",
    "description": "Official video\n\nAscolta: https://example.invalid/album",
    "view_count": 12345678,
    "like_count": 98765,
    "comment_count": 4321,
    "tags": ["50 cent", "hip hop", "window shopper"],
    "categories": ["Music"],
    "thumbnail": "https://i.ytimg.com/vi/IX7UWaSoVv0/maxresdefault.jpg",
    "duration": 236.4,
}

# PNG 1×1 valido (firma + IHDR + IDAT + IEND): è l'"immagine" che i test danno al
# posto della miniatura, così la copertina si prova senza andare in rete.
PNG_DI_PROVA = bytes.fromhex(
    "89504e470d0a1a0a0000000d494844520000000100000001080600000"
    "01f15c4890000000a49444154789c63000100000500010d0a2db40000"
    "000049454e44ae426082")


class FakeYDL:
    """yt-dlp finto: non tocca la rete e registra gli URL chiesti.

    - `extract_info(url, download=False)` è la LETTURA dei metadati (quella che fa
      `info_video_riga`): risponde con `INFO`;
    - `ytsearch20:…` risponde con una voce dal titolo «Brano Di Prova», così
      `yt_search_first` la sceglie per una riga con quel titolo;
    - con `download=True` scrive il file nell'`outtmpl` (è il job dell'MP4).
    """

    chiamate = []
    fallisci = ()
    risultati_vuoti = False

    def __init__(self, opts):
        self.opts = opts

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def prepare_filename(self, info):
        richieste = (info or {}).get("requested_downloads") or []
        if richieste and isinstance(richieste[0], dict):
            return richieste[0].get("filepath") or ""
        return ""

    def extract_info(self, url, download=True):
        url = str(url)
        type(self).chiamate.append(url)
        if "ytsearch" in url:
            if type(self).risultati_vuoti:
                return {"entries": []}
            return {"entries": [{"title": "Brano Di Prova",
                                 "webpage_url": "https://www.youtube.com/watch?v=idtst123456",
                                 "id": "idtst123456", "duration": 200,
                                 "channel": "Canale Di Prova"}]}
        if url in tuple(type(self).fallisci):
            raise Exception("This video is unavailable (prova)")
        if not download:
            return dict(INFO)
        nome = "Brano Di Prova [idtst123456].mp4"
        percorso = os.path.join(os.path.dirname(self.opts["outtmpl"]), nome)
        with open(percorso, "wb") as f:
            f.write(b"video" * 8)
        return {**INFO, "requested_downloads": [{"filepath": percorso}]}


class TestFonteVideoRiga(unittest.TestCase):
    """Da dove si prende il video: il link, l'id, o una ricerca (funzione PURA)."""

    def test_il_link_della_riga_vince_su_tutto(self):
        query, da_link = APP.fonte_video_riga({
            "youtube_url": "https://www.youtube.com/watch?v=abc123",
            "yt_video_id": "zzz", "artist": "Eminem", "title": "Who Knew"})
        self.assertEqual(query, "https://www.youtube.com/watch?v=abc123")
        self.assertTrue(da_link)

    def test_l_id_salvato_col_download(self):
        query, da_link = APP.fonte_video_riga({"yt_video_id": "IX7UWaSoVv0"})
        self.assertEqual(query, "https://www.youtube.com/watch?v=IX7UWaSoVv0")
        self.assertTrue(da_link)

    def test_senza_link_ne_id_si_cerca(self):
        query, da_link = APP.fonte_video_riga({"artist": "Eminem", "title": "Who Knew"})
        self.assertEqual(query, "Eminem Who Knew")
        self.assertFalse(da_link, "senza link/id il video va CERCATO: la pagina deve saperlo")

    def test_un_link_che_non_e_youtube_non_conta(self):
        query, da_link = APP.fonte_video_riga({
            "youtube_url": "https://example.invalid/x", "yt_video_id": "abc"})
        self.assertEqual(query, "https://www.youtube.com/watch?v=abc")
        self.assertTrue(da_link)

    def test_riga_vuota_o_inesistente(self):
        self.assertEqual(APP.fonte_video_riga({}), ("", False))
        self.assertEqual(APP.fonte_video_riga(None), ("", False))


class TestInfoVideoRiga(unittest.TestCase):
    """La lettura dei dati del video: con un link non si cerca, senza link sì."""

    def setUp(self):
        self.orig = APP.yt_dlp
        FakeYDL.chiamate = []
        FakeYDL.fallisci = ()
        FakeYDL.risultati_vuoti = False
        APP.yt_dlp = types.SimpleNamespace(YoutubeDL=FakeYDL)

    def tearDown(self):
        APP.yt_dlp = self.orig

    def test_con_il_link_non_si_cerca_niente(self):
        link = "https://www.youtube.com/watch?v=byD8lVZdsyo"
        info, url, cercato, motivo = APP.info_video_riga(
            {"youtube_url": link, "title": "Brano"})
        self.assertEqual(motivo, "")
        self.assertFalse(cercato)
        self.assertEqual(url, link)
        self.assertEqual(info["channel"], "50 Cent")
        self.assertTrue(info.get("thumbnail"))
        self.assertEqual(FakeYDL.chiamate, [link],
                         "con un link non si deve cercare niente")

    def test_senza_link_il_video_e_quello_trovato_dalla_ricerca(self):
        info, url, cercato, motivo = APP.info_video_riga(
            {"artist": "Artista Di Prova", "title": "Brano Di Prova"})
        self.assertTrue(cercato)
        self.assertEqual(motivo, "")
        self.assertEqual(url, "https://www.youtube.com/watch?v=idtst123456")
        self.assertTrue(FakeYDL.chiamate and FakeYDL.chiamate[0].startswith("ytsearch20:"))

    def test_un_video_illeggibile_diventa_un_motivo(self):
        rotto = "https://www.youtube.com/watch?v=rotto"
        FakeYDL.fallisci = (rotto,)
        info, url, cercato, motivo = APP.info_video_riga({"youtube_url": rotto, "title": "X"})
        self.assertIsNone(info)
        self.assertFalse(cercato)
        self.assertIn("non leggibile", motivo)

    def test_ricerca_senza_risultati(self):
        FakeYDL.risultati_vuoti = True
        info, url, cercato, motivo = APP.info_video_riga(
            {"artist": "Nessuno", "title": "Brano Introvabile"})
        self.assertIsNone(info)
        self.assertTrue(cercato)
        self.assertIn("nessun video trovato", motivo)

    def test_una_riga_senza_titolo_ne_link_lo_dice(self):
        info, url, cercato, motivo = APP.info_video_riga({})
        self.assertIsNone(info)
        self.assertIn("né link YouTube né titolo", motivo)


class BaseRecupero(unittest.TestCase):
    """Database temporaneo + yt-dlp finto + miniatura finta: nessuna rete.

    `covers/`, `downloads/`, `videos/` e `.trash/` sono cartelle usa e getta: i
    test non toccano né la libreria vera né le sue immagini.
    """

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="recupero_youtube_prova_")
        self.orig = (APP.DB_PATH, APP.COVERS_DIR, APP.DL_DIR, APP.VID_DIR,
                     APP.TRASH_DIR, APP.yt_dlp, APP._scarica_immagine)
        APP.DB_PATH = os.path.join(self.tmp, "samplelab di prova.db")
        APP.COVERS_DIR = os.path.join(self.tmp, "covers")
        APP.DL_DIR = os.path.join(self.tmp, "downloads")
        APP.VID_DIR = os.path.join(self.tmp, "videos")
        APP.TRASH_DIR = os.path.join(self.tmp, ".trash")
        for cartella in (APP.COVERS_DIR, APP.DL_DIR, APP.VID_DIR, APP.TRASH_DIR):
            os.makedirs(cartella, exist_ok=True)
        APP.init_db()
        FakeYDL.chiamate = []
        FakeYDL.fallisci = ()
        FakeYDL.risultati_vuoti = False
        APP.yt_dlp = types.SimpleNamespace(YoutubeDL=FakeYDL)
        # La miniatura non si scarica da i.ytimg.com: i byte li dà questa funzione.
        APP._scarica_immagine = lambda url: PNG_DI_PROVA
        self.client = APP.app.test_client()

    def tearDown(self):
        (APP.DB_PATH, APP.COVERS_DIR, APP.DL_DIR, APP.VID_DIR, APP.TRASH_DIR,
         APP.yt_dlp, APP._scarica_immagine) = self.orig
        shutil.rmtree(self.tmp, ignore_errors=True)

    def crea_riga(self, sid="song_prova", titolo="Brano Di Prova",
                  artista="Artista Di Prova", **campi):
        with APP.get_db() as conn:
            colonne = ["id", "title", "artist"] + list(campi)
            conn.execute("INSERT INTO songs(" + ", ".join(colonne) + ") VALUES(" +
                         ", ".join(["?"] * len(colonne)) + ")",
                         [sid, titolo, artista] + list(campi.values()))
        return sid

    def riga(self, sid):
        with APP.get_db() as conn:
            return conn.execute("SELECT * FROM songs WHERE id=?", (sid,)).fetchone()

    def file_copertina(self, sid):
        """I file di copertina di QUELLA riga che stanno in covers/."""
        return sorted(f for f in os.listdir(APP.COVERS_DIR) if f.startswith(sid + "."))

    def aspetta(self, condizione, secondi=20):
        fine = time.time() + secondi
        while time.time() < fine:
            if condizione():
                return True
            time.sleep(0.1)
        return condizione()


class TestRecuperoRiga(BaseRecupero):
    """`recupera_dati_video`: la miniatura e i dati del video su UNA riga."""

    LINK = "https://www.youtube.com/watch?v=IX7UWaSoVv0"

    def test_scrive_i_dati_e_salva_la_miniatura(self):
        sid = self.crea_riga(youtube_url=self.LINK)
        esito = APP.recupera_dati_video(sid)
        self.assertTrue(esito["ok"], esito)
        self.assertFalse(esito["cercato"])
        self.assertEqual(esito["cover"], f"{sid}.jpg")
        r = self.riga(sid)
        self.assertEqual(r["yt_channel"], "50 Cent")
        self.assertEqual(r["yt_views"], 12345678)
        self.assertEqual(r["yt_upload_date"], "2025-09-15")
        self.assertEqual(r["yt_tags"], "50 cent, hip hop, window shopper")
        self.assertEqual(r["yt_category"], "Music")
        self.assertEqual(r["cover_art_path"], f"{sid}.jpg")
        self.assertTrue(r["yt_meta_at"], "manca la data di lettura dei metadati")
        self.assertEqual(self.file_copertina(sid), [f"{sid}.jpg"])
        self.assertEqual(r["youtube_url"], self.LINK, "il link della riga non si tocca")
        self.assertEqual(FakeYDL.chiamate, [self.LINK])

    def test_una_copertina_che_c_e_non_si_tocca(self):
        percorso = os.path.join(APP.COVERS_DIR, "mio.jpg")
        with open(percorso, "wb") as f:
            f.write(b"immagine scelta a mano")
        sid = self.crea_riga(youtube_url=self.LINK, cover_art_path="mio.jpg")
        esito = APP.recupera_dati_video(sid)
        self.assertEqual(esito["cover"], "")
        self.assertIn("la copertina c'era già", esito["cover_motivo"])
        self.assertEqual(self.riga(sid)["cover_art_path"], "mio.jpg")
        with open(percorso, "rb") as f:
            self.assertEqual(f.read(), b"immagine scelta a mano")
        # I DATI del video invece si scrivono: quelli mancavano.
        self.assertEqual(self.riga(sid)["yt_channel"], "50 Cent")

    def test_forzato_rifa_la_copertina(self):
        with open(os.path.join(APP.COVERS_DIR, "vecchia.png"), "wb") as f:
            f.write(b"vecchia")
        sid = self.crea_riga(youtube_url=self.LINK, cover_art_path="vecchia.png")
        esito = APP.recupera_dati_video(sid, forzato=True)
        self.assertEqual(esito["cover"], f"{sid}.jpg")
        self.assertEqual(self.riga(sid)["cover_art_path"], f"{sid}.jpg")
        self.assertEqual(self.file_copertina(sid), [f"{sid}.jpg"])
        with open(os.path.join(APP.COVERS_DIR, "vecchia.png"), "rb") as f:
            self.assertEqual(f.read(), b"vecchia",
                             "la copertina di un'altra riga non si tocca")

    def test_senza_link_si_cerca_e_il_link_resta_scritto(self):
        sid = self.crea_riga()          # né youtube_url né yt_video_id
        esito = APP.recupera_dati_video(sid)
        self.assertTrue(esito["ok"], esito)
        self.assertTrue(esito["cercato"])
        r = self.riga(sid)
        self.assertEqual(r["youtube_url"], "https://www.youtube.com/watch?v=idtst123456")
        self.assertEqual(r["cover_art_path"], f"{sid}.jpg")
        self.assertTrue(any("CERCANDO" in m for m in esito["messaggi"]), esito["messaggi"])

    def test_un_video_illeggibile_non_scrive_niente(self):
        rotto = "https://www.youtube.com/watch?v=rotto"
        sid = self.crea_riga(youtube_url=rotto)
        FakeYDL.fallisci = (rotto,)
        esito = APP.recupera_dati_video(sid)
        self.assertFalse(esito["ok"])
        self.assertIn("non leggibile", esito["error"])
        r = self.riga(sid)
        self.assertIsNone(r["cover_art_path"])
        self.assertIsNone(r["yt_channel"])

    def test_una_riga_che_non_c_e(self):
        esito = APP.recupera_dati_video("song_fantasma")
        self.assertFalse(esito["ok"])
        self.assertIn("non trovata", esito["error"])

    def test_con_video_si_avvia_anche_l_mp4(self):
        sid = self.crea_riga(youtube_url=self.LINK)
        esito = APP.recupera_dati_video(sid, video=True)
        self.assertTrue(esito["video_job"], esito.get("video_motivo"))
        self.assertTrue(self.aspetta(lambda: (self.riga(sid)["video_file"] or "") != ""),
                        "il video non è stato agganciato alla riga")
        self.assertTrue(APP.file_video_valido(self.riga(sid)["video_file"]))


class TestRigheDaRecuperare(BaseRecupero):
    """Chi è candidato al recupero e cosa gli manca (`righe_da_recuperare`)."""

    LINK = "https://www.youtube.com/watch?v=IX7UWaSoVv0"

    def test_candidati_e_chi_resta_fuori(self):
        self.crea_riga("song_con_link", youtube_url=self.LINK)
        self.crea_riga("song_completo", youtube_url=self.LINK,
                       cover_art_path="song_completo.jpg",
                       yt_meta_at="2026-09-19 10:00:00")
        with open(os.path.join(APP.COVERS_DIR, "song_completo.jpg"), "wb") as f:
            f.write(b"copertina sua")
        self.crea_riga("song_senza_link")      # artista e titolo, niente link
        righe, senza_link = APP.righe_da_recuperare()
        per_id = {r["id"]: r["manca"] for r in righe}
        self.assertIn("song_con_link", per_id)
        self.assertNotIn("song_completo", per_id, "non gli manca niente")
        self.assertNotIn("song_senza_link", per_id, "senza link sta fuori dal blocco")
        self.assertEqual(senza_link, 1)
        self.assertIn("copertina", per_id["song_con_link"])
        # ... ma col pulsante (solo_con_link=False) entra anche quella
        righe2, _ = APP.righe_da_recuperare(solo_con_link=False)
        self.assertIn("song_senza_link", [r["id"] for r in righe2])

    def test_una_copertina_col_file_sparito_e_da_rifare(self):
        self.crea_riga("song_file_sparito", youtube_url=self.LINK,
                       cover_art_path="nome-senza-file.jpg",
                       yt_meta_at="2026-09-19 10:00:00")
        righe, _ = APP.righe_da_recuperare()
        per_id = {r["id"]: r["manca"] for r in righe}
        self.assertIn("song_file_sparito", per_id,
                      "se il file non c'è più, la copertina va rifatta")
        self.assertIn("copertina", per_id["song_file_sparito"])
        self.assertNotIn("dati del video", per_id["song_file_sparito"])


class TestAvvioBlocco(BaseRecupero):
    """`avvia_recupero_youtube`: il lavoro in blocco, col progresso nel job."""

    LINK = "https://www.youtube.com/watch?v=IX7UWaSoVv0"

    def test_il_blocco_lavora_e_racconta_cosa_ha_fatto(self):
        for n in (1, 2):
            self.crea_riga(f"song_blocco{n}", youtube_url=self.LINK)
        job, motivo = APP.avvia_recupero_youtube(pausa=0)
        self.assertTrue(job, motivo)
        self.assertIn("2 righe", motivo)
        self.assertTrue(self.aspetta(lambda: APP.jobs[job]["status"] == "done"),
                        "il job non è finito")
        j = APP.jobs[job]
        self.assertEqual(len(j["risultati"]), 2)
        self.assertEqual(j["progress"]["fatti"], 2)
        self.assertEqual(j["progress"]["totale"], 2)
        self.assertIn("2 miniature salvate", j["riepilogo"])
        for n in (1, 2):
            self.assertEqual(self.riga(f"song_blocco{n}")["cover_art_path"],
                             f"song_blocco{n}.jpg")

    def test_un_secondo_avvio_non_parte(self):
        self.crea_riga("song_blocco_uno", youtube_url=self.LINK)
        job, _ = APP.avvia_recupero_youtube(pausa=1)
        job2, motivo = APP.avvia_recupero_youtube()
        self.assertEqual(job2, job)
        self.assertIn("già in corso", motivo)
        # Si aspetta che il lavoro finisca: nessun thread appeso fra un test e l'altro.
        self.assertTrue(self.aspetta(lambda: APP.jobs[job]["status"] == "done", 20))

    def test_niente_da_recuperare(self):
        self.aspetta(lambda: not APP._ry_bulk.get("job"), 10)   # nessun recupero in corso
        job, motivo = APP.avvia_recupero_youtube()
        self.assertEqual(job, "")
        self.assertIn("niente da recuperare", motivo)


class TestRotteRecupero(BaseRecupero):
    """Le rotte vere (`POST /db/songs/<id>/recupera_youtube`, elenco, blocco)."""

    LINK = "https://www.youtube.com/watch?v=IX7UWaSoVv0"

    def test_post_su_una_riga(self):
        sid = self.crea_riga(youtube_url=self.LINK)
        res = self.client.post(f"/db/songs/{sid}/recupera_youtube", json={})
        self.assertEqual(res.status_code, 200)
        corpo = res.get_json()
        self.assertTrue(corpo["ok"], corpo)
        self.assertEqual(corpo["cover"], f"{sid}.jpg")
        self.assertEqual(corpo["song"]["yt_channel"], "50 Cent")
        self.assertEqual(corpo["song"]["cover_art_path"], f"{sid}.jpg")

    def test_post_su_una_riga_che_non_c_e(self):
        res = self.client.post("/db/songs/song_fantasma/recupera_youtube", json={})
        self.assertEqual(res.status_code, 404)
        self.assertIn("non trovata", res.get_json()["error"])

    def test_post_con_un_video_illeggibile_risponde_502(self):
        rotto = "https://www.youtube.com/watch?v=rotto"
        sid = self.crea_riga(youtube_url=rotto)
        FakeYDL.fallisci = (rotto,)
        res = self.client.post(f"/db/songs/{sid}/recupera_youtube", json={})
        self.assertEqual(res.status_code, 502)
        self.assertFalse(res.get_json()["ok"])
        self.assertIn("non leggibile", res.get_json()["error"])

    def test_l_elenco_dei_candidati_non_tocca_la_rete(self):
        self.crea_riga("song_con_link", youtube_url=self.LINK)
        self.crea_riga("song_senza_link")
        res = self.client.get("/db/recupera_youtube")
        self.assertEqual(res.status_code, 200)
        corpo = res.get_json()
        self.assertEqual(corpo["totale"], 1)
        self.assertEqual(corpo["righe"][0]["id"], "song_con_link")
        self.assertEqual(corpo["senza_link"], 1)
        self.assertEqual(FakeYDL.chiamate, [], "l'elenco non deve toccare YouTube")

    def test_avvio_del_blocco_dalla_rotta(self):
        for n in (1, 2):
            self.crea_riga(f"song_rotta{n}", youtube_url=self.LINK)
        res = self.client.post("/db/recupera_youtube", json={})
        corpo = res.get_json()
        self.assertTrue(corpo["avviato"], corpo)
        job = corpo["job_id"]
        self.assertTrue(self.aspetta(
            lambda: self.client.get(f"/status/{job}").get_json()["status"] == "done", 25),
            "il job del blocco non è finito")
        j = self.client.get(f"/status/{job}").get_json()
        self.assertEqual(j["progress"]["totale"], 2)
        self.assertEqual(len(j["risultati"]), 2)
        self.assertIn("miniature salvate", j["riepilogo"])

    def test_blocco_senza_candidati(self):
        res = self.client.post("/db/recupera_youtube", json={})
        corpo = res.get_json()
        self.assertFalse(corpo["avviato"])
        self.assertIn("niente da recuperare", corpo["motivo"])


class TestCablaggio(unittest.TestCase):
    """Il cablaggio nelle pagine e nel backend (ricerca nei sorgenti)."""

    def test_pulsante_pannello_e_rotte_nella_pagina(self):
        html = leggi(PAGINA_PATH)
        self.assertIn("function recuperaYoutube(", html)
        self.assertIn("onclick=\"recuperaYoutube('${s.id}',this)\"", html)
        self.assertIn("/db/songs/${id}/recupera_youtube", html)
        self.assertIn('id="ry-stato"', html)
        self.assertIn('id="ry-esito"', html)
        self.assertIn("function aggiornaRecuperoYoutube(", html)
        self.assertIn("function avviaRecuperoYoutube(", html)
        self.assertIn("aggiornaRecuperoYoutube(); }", html)   # al cambio tab 🗄️ Database
        self.assertIn("/db/recupera_youtube", html)

    def test_miniatura_di_riserva_dove_serve(self):
        html = leggi(PAGINA_PATH)
        self.assertIn("function coverUrlRiga(", html)
        self.assertIn("coverThumb(s.cover_art_path, 26, s.yt_thumbnail)", html)
        self.assertIn("coverThumb(song.cover_art_path, 54, song.yt_thumbnail)", html)
        browse = leggi(BROWSE_PATH)
        self.assertIn("function miniaturaYT(s)", browse)
        self.assertIn("miniaturaYT(s); }", browse)
        self.assertIn("miniaturaYT", leggi(SCHEDA_PATH))

    def test_riquadro_youtube_nel_modale_edit(self):
        html = leggi(PAGINA_PATH)
        self.assertIn("function rigaYoutubeHTML(", html)
        self.assertIn("${rigaYoutubeHTML(s)}", html)

    def test_le_funzioni_e_le_rotte_nel_backend(self):
        app = leggi(APP_PATH)
        for pezzo in ("def fonte_video_riga", "def info_video_riga",
                      "def recupera_dati_video", "def righe_da_recuperare",
                      "def avvia_recupero_youtube",
                      '@app.route("/db/songs/<song_id>/recupera_youtube"',
                      '@app.route("/db/recupera_youtube"'):
            self.assertIn(pezzo, app)

    def test_il_readme_lo_racconta(self):
        self.assertIn("recupera_youtube", leggi(README_PATH))


@unittest.skipUnless(app_is_up(SAMPLELAB_URL), f"app non attiva su {SAMPLELAB_URL}")
class TestAppViva(unittest.TestCase):
    """L'app viva, in sola lettura: l'elenco dei candidati e le pagine."""

    def test_elenco_candidati(self):
        d = http_json("/db/recupera_youtube")
        self.assertIn("totale", d)
        self.assertIn("senza_link", d)
        for r in d["righe"]:
            self.assertIn("manca", r)
            self.assertTrue(r["manca"], "una riga candidata deve dire COSA le manca")

    def test_le_pagine_rispondono(self):
        for percorso in ("/", "/browse", "/scheda", "/onyx", "/verifica"):
            with urllib.request.urlopen(SAMPLELAB_URL + percorso, timeout=15) as r:
                self.assertEqual(r.status, 200)


if __name__ == "__main__":
    unittest.main(verbosity=2)






