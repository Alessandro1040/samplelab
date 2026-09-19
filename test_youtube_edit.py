"""Test del collegamento a YouTube e della MODIFICA dei video dall'app (19/09/2026).

Richiesta di Alessandro: «aggiungi la possibilità di connettere a youtube e
modificare la descrizione dei video, oppure modificare i tag, o il titolo, ecc…
direttamente dall'applicazione, decidi tu come implementarlo questo, magari l'app
può chiedere email e password del canale youtube all'utente oppure può chiedere
altre cose però se riesci sarebbe veramente tanta roba».

Strada scelta (opzione A, con ripiego sul browser): l'**API ufficiale YouTube Data
v3** con OAuth. La password di Google **non** passa da SampleLab: il consenso si dà
nella pagina di Google, come per qualunque «Accedi con Google». Servono un «client
OAuth» creato una volta in Google Cloud (ID+secret in `youtube_client.json`) e il
token del consenso (`youtube_token.json`): due file NON versionati, permessi 600.

Cosa copre questo file:
1. le funzioni PURE: `tag_da_testo`/`testo_da_tag` (i tag sono una stringa «a, b, c»
   e l'API vuole una lista), `yt_id_video_riga` (id dal campo o dal link),
   `snippet_da_modificare` (i campi che non si toccano restano: categoria e lingue
   si riportano indietro, i campi di sola lettura NON si mandano);
2. la lettura del video e la modifica con un'API FINTA (nessuna rete): solo i campi
   cambiati finiscono nel `body`, «niente da cambiare» non chiama l'API, un titolo
   vuoto viene fermato prima, un rifiuto di YouTube non tocca il database, e dopo un
   salvataggio riuscito la riga si riallinea a quello che c'è DAVVERO sul video;
3. lo STATO del collegamento (`yt_stato`) nei suoi passaggi: manca il client → client
   salvato ma non collegato → collegato (con un client finto);
4. le rotte su un database temporaneo: `/youtube/stato`, `/youtube/client`,
   `/youtube/collega` (senza client dice cosa manca), `/youtube/scollega`,
   `/db/songs/<id>/youtube_video` (GET e POST, coi loro codici);
5. il cablaggio (sorgenti): pannello 🔗 e finestra ✍️ nella pagina, i file privati in
   `.gitignore`, le librerie in `requirements.txt`;
6. l'app VIVA in sola lettura: `/youtube/stato`.

Esecuzione (dalla cartella di SampleLab):
    python3 -m unittest -v test_youtube_edit
I test HTTP dell'app viva girano solo se l'app è attiva (default
http://localhost:5070, sovrascrivibile con la variabile SAMPLELAB_URL).
"""
import importlib.util
import json
import os
import shutil
import tempfile
import unittest
import urllib.request

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
APP_PATH = os.path.join(BASE_DIR, "app (2).py")
PAGINA_PATH = os.path.join(BASE_DIR, "index (2).html")
README_PATH = os.path.join(BASE_DIR, "README.md")
GITIGNORE_PATH = os.path.join(BASE_DIR, ".gitignore")
REQUIREMENTS_PATH = os.path.join(BASE_DIR, "requirements.txt")
SAMPLELAB_URL = os.environ.get("SAMPLELAB_URL", "http://localhost:5070")


def load_app():
    """Carica il modulo dell'app dal file (il nome con spazio non conta)."""
    spec = importlib.util.spec_from_file_location("samplelab_app2_youtube", APP_PATH)
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
    with urllib.request.urlopen(SAMPLELAB_URL + path, timeout=30) as r:
        return json.loads(r.read().decode("utf-8"))


# Lo `snippet` di un video vero, come lo restituisce l'API.
SNIPPET = {
    "title": "[CINEMATIC] NF Type Beat 2024 ＂Clown” (Prod. Raedius)",
    "description": "● Buy: https://www.beatstars.com/beat/nf-type-beat-clown-19982397\n\nBPM: 112",
    "tags": ["nf type beat 2024", "orchestral type beat 2024"],
    "categoryId": "10",
    "channelTitle": "Prod By Raedius",
    "publishedAt": "2024-09-22T10:00:00Z",
}


class _Esegui:
    """Quello che l'API restituisce (`.execute()`), come nella libreria vera."""

    def __init__(self, dati):
        self._dati = dati

    def execute(self):
        return self._dati


class FakeVideos:
    """`videos()` dell'API YouTube, finto: registra le chiamate e risponde.

    `attuale` è lo snippet che `list` restituisce (None = video invisibile al
    canale); `errore_lettura`/`errore_scrittura` fanno fallire le due chiamate come
    farebbe YouTube (quota, permessi).
    """

    letture = []
    scritture = []
    attuale = None
    errore_lettura = ""
    errore_scrittura = ""

    def list(self, part="snippet", id=""):
        type(self).letture.append((part, id))
        if type(self).errore_lettura:
            raise Exception(type(self).errore_lettura)
        if type(self).attuale is None:
            return _Esegui({"items": []})
        return _Esegui({"items": [{"id": id, "snippet": dict(type(self).attuale)}]})

    def update(self, part="snippet", body=None):
        type(self).scritture.append((part, body))
        if type(self).errore_scrittura:
            raise Exception(type(self).errore_scrittura)
        return _Esegui({"id": (body or {}).get("id"), "snippet": dict((body or {}).get("snippet") or {})})


class FakeChannels:
    """`channels()` finto: serve a `yt_stato` per dire a QUALE canale siamo collegati."""

    titolo = "Prod By Raedius"

    def list(self, part="snippet", mine=True):
        return _Esegui({"items": [{"snippet": {"title": type(self).titolo}}]})


class FakeYouTube:
    """Il servizio dell'API, finto (basta `videos()` e `channels()`)."""

    def videos(self):
        return FakeVideos()

    def channels(self):
        return FakeChannels()


class TestFunzioniPure(unittest.TestCase):
    """Le funzioni che si possono provare senza toccare né rete né database."""

    def test_tag_da_testo_e_ritorno(self):
        self.assertEqual(APP.tag_da_testo("a, b, c"), ["a", "b", "c"])
        self.assertEqual(APP.tag_da_testo(" uno , due "), ["uno", "due"])
        self.assertEqual(APP.tag_da_testo(""), [])
        self.assertEqual(APP.tag_da_testo(None), [])
        self.assertEqual(APP.tag_da_testo("solo"), ["solo"])
        self.assertEqual(APP.tag_da_testo("a,,  ,b"), ["a", "b"])
        self.assertEqual(APP.testo_da_tag(["a", "b"]), "a, b")
        self.assertEqual(APP.testo_da_tag([]), "")
        # il giro completo non perde niente
        self.assertEqual(APP.tag_da_testo(APP.testo_da_tag(["x", "y"])), ["x", "y"])

    def test_la_descrizione_non_si_perde_cambiando_solo_i_tag(self):
        # Il bug trovato dai test il 19/09/2026: senza riportare indietro la
        # descrizione, `videos.update` la CANCELLA (lo snippet si sostituisce in
        # blocco). Con un video che ha una descrizione lunga sarebbe un danno serio.
        nuovo = APP.snippet_da_modificare(dict(SNIPPET), tag="solo, tag")
        self.assertEqual(nuovo["description"], SNIPPET["description"])
        self.assertEqual(nuovo["title"], SNIPPET["title"])
        # e vale anche al contrario: cambiando il titolo, i tag restano
        nuovo2 = APP.snippet_da_modificare(dict(SNIPPET), titolo="solo titolo nuovo")
        self.assertEqual(nuovo2["tags"], SNIPPET["tags"])
        self.assertEqual(nuovo2["description"], SNIPPET["description"])

    def test_id_del_video_dalla_riga(self):
        self.assertEqual(APP.yt_id_video_riga({"yt_video_id": "abc123"}), "abc123")
        self.assertEqual(APP.yt_id_video_riga(
            {"youtube_url": "https://www.youtube.com/watch?v=byD8lVZdsyo"}), "byD8lVZdsyo")
        self.assertEqual(APP.yt_id_video_riga(
            {"youtube_url": "https://youtu.be/byD8lVZdsyo?t=1"}), "byD8lVZdsyo")
        # l'id scritto vince sul link
        self.assertEqual(APP.yt_id_video_riga(
            {"yt_video_id": "zzz", "youtube_url": "https://www.youtube.com/watch?v=byD8lVZdsyo"}), "zzz")
        for brutto in ({}, None, {"youtube_url": "https://example.invalid/x"}):
            self.assertEqual(APP.yt_id_video_riga(brutto), "")

    def test_lo_snippet_che_si_manda_indietro_non_calza_niente(self):
        attuale = dict(SNIPPET)
        # si cambia SOLO la descrizione: titolo, tag, categoria e lingua restano
        nuovo = APP.snippet_da_modificare(attuale, descrizione="nuova descrizione")
        self.assertEqual(nuovo["title"], SNIPPET["title"])
        self.assertEqual(nuovo["tags"], SNIPPET["tags"])
        self.assertEqual(nuovo["categoryId"], "10")
        self.assertEqual(nuovo["description"], "nuova descrizione")
        # i campi di sola lettura NON si mandano (l'API li rifiuterebbe)
        for vietato in ("channelTitle", "publishedAt", "id"):
            self.assertNotIn(vietato, nuovo)
        # solo i tag: la descrizione resta quella di prima
        nuovo2 = APP.snippet_da_modificare(attuale, tag="uno, due")
        self.assertEqual(nuovo2["tags"], ["uno", "due"])
        self.assertEqual(nuovo2["description"], SNIPPET["description"])
        # la lingua dichiarata si riporta indietro quando c'è
        nuovo3 = APP.snippet_da_modificare(
            {"title": "x", "defaultLanguage": "it", "defaultAudioLanguage": "it"},
            titolo="y")
        self.assertEqual(nuovo3["defaultLanguage"], "it")
        self.assertEqual(nuovo3["defaultAudioLanguage"], "it")
        self.assertEqual(nuovo3["title"], "y")
        # titolo vuoto: chi chiama lo deve fermare PRIMA (YouTube lo rifiuta)
        self.assertEqual(APP.snippet_da_modificare(attuale, titolo="")["title"], "")


class BaseYouTube(unittest.TestCase):
    """Database temporaneo + API YouTube FINTA: nessuna rete, nessun token vero.

    `yt_servizio` si sostituisce con un servizio finto e i percorsi dei due file
    privati puntano a una cartella usa e getta: i test non toccano né la libreria
    vera né le credenziali di Alessandro.
    """

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="youtube_edit_prova_")
        self.orig = (APP.DB_PATH, APP.YT_CLIENT_PATH, APP.YT_TOKEN_PATH, APP.yt_servizio)
        APP.DB_PATH = os.path.join(self.tmp, "samplelab di prova.db")
        APP.YT_CLIENT_PATH = os.path.join(self.tmp, "youtube_client.json")
        APP.YT_TOKEN_PATH = os.path.join(self.tmp, "youtube_token.json")
        APP.init_db()
        FakeVideos.letture, FakeVideos.scritture = [], []
        FakeVideos.attuale = dict(SNIPPET)
        FakeVideos.errore_lettura = FakeVideos.errore_scrittura = ""
        self.servizio = FakeYouTube()
        APP.yt_servizio = lambda: (self.servizio, "")
        self.client = APP.app.test_client()

    def tearDown(self):
        (APP.DB_PATH, APP.YT_CLIENT_PATH, APP.YT_TOKEN_PATH, APP.yt_servizio) = self.orig
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


class TestLetturaVideo(BaseYouTube):
    """`yt_video_attuale`: cosa c'è ORA sul video, per riempire i campi."""

    def test_legge_il_video_della_riga(self):
        sid = self.crea_riga(yt_video_id="byD8lVZdsyo")
        res = APP.yt_video_attuale(sid)
        self.assertTrue(res["ok"], res)
        self.assertEqual(res["video_id"], "byD8lVZdsyo")
        self.assertEqual(res["snippet"]["title"], SNIPPET["title"])
        self.assertEqual(res["snippet"]["tags"], SNIPPET["tags"])
        self.assertEqual(res["snippet"]["description"], SNIPPET["description"])
        self.assertEqual(res["snippet"]["channelTitle"], "Prod By Raedius")
        self.assertEqual(FakeVideos.letture, [("snippet", "byD8lVZdsyo")])

    def test_l_id_si_ricava_anche_dal_link(self):
        sid = self.crea_riga(youtube_url="https://www.youtube.com/watch?v=byD8lVZdsyo")
        self.assertEqual(APP.yt_video_attuale(sid)["video_id"], "byD8lVZdsyo")

    def test_una_riga_senza_link_ne_id_lo_dice(self):
        sid = self.crea_riga()
        res = APP.yt_video_attuale(sid)
        self.assertFalse(res["ok"])
        self.assertIn("non ha né l'id del video né un link", res["error"])
        self.assertEqual(FakeVideos.letture, [], "senza link non si chiama YouTube")

    def test_un_video_invisibile_al_canale(self):
        FakeVideos.attuale = None      # l'API risponde con `items` vuoto
        sid = self.crea_riga(yt_video_id="byD8lVZdsyo")
        res = APP.yt_video_attuale(sid)
        self.assertFalse(res["ok"])
        self.assertIn("non è visibile col canale collegato", res["error"])

    def test_un_errore_dell_api_diventa_un_motivo(self):
        FakeVideos.errore_lettura = "quotaExceeded"
        sid = self.crea_riga(yt_video_id="byD8lVZdsyo")
        res = APP.yt_video_attuale(sid)
        self.assertFalse(res["ok"])
        self.assertIn("YouTube non ha risposto", res["error"])

    def test_una_riga_che_non_c_e(self):
        res = APP.yt_video_attuale("song_fantasma")
        self.assertFalse(res["ok"])
        self.assertIn("non trovata", res["error"])


class TestModificaVideo(BaseYouTube):
    """`yt_modifica_video`: cosa si manda a YouTube e cosa resta nella riga."""

    def test_cambia_solo_la_descrizione_e_il_resto_resta(self):
        sid = self.crea_riga(yt_video_id="byD8lVZdsyo", yt_title=SNIPPET["title"],
                             yt_tags="nf type beat 2024, orchestral type beat 2024")
        res = APP.yt_modifica_video(sid, descrizione="● Buy: nuovo listino")
        self.assertTrue(res["ok"], res)
        self.assertEqual(res["modifiche"], ["descrizione"])
        self.assertEqual(len(FakeVideos.scritture), 1)
        _, body = FakeVideos.scritture[0]
        self.assertEqual(body["id"], "byD8lVZdsyo")
        self.assertEqual(body["snippet"]["title"], SNIPPET["title"])
        self.assertEqual(body["snippet"]["tags"], SNIPPET["tags"])
        self.assertEqual(body["snippet"]["categoryId"], "10")
        self.assertEqual(body["snippet"]["description"], "● Buy: nuovo listino")
        # la riga si riallinea a quello che c'è DAVVERO sul video
        r = self.riga(sid)
        self.assertEqual(r["yt_description"], "● Buy: nuovo listino")
        self.assertEqual(r["yt_title"], SNIPPET["title"])

    def test_solo_i_tag(self):
        sid = self.crea_riga(yt_video_id="byD8lVZdsyo", yt_description=SNIPPET["description"])
        res = APP.yt_modifica_video(sid, tag="uno, due, tre")
        self.assertTrue(res["ok"], res)
        self.assertEqual(res["modifiche"], ["tag"])
        body = FakeVideos.scritture[0][1]
        self.assertEqual(body["snippet"]["tags"], ["uno", "due", "tre"])
        self.assertEqual(body["snippet"]["description"], SNIPPET["description"])
        self.assertEqual(self.riga(sid)["yt_tags"], "uno, due, tre")

    def test_solo_il_titolo(self):
        sid = self.crea_riga(yt_video_id="byD8lVZdsyo")
        res = APP.yt_modifica_video(sid, titolo='NF Type Beat 2024 "Clown" (Prod. Raedius)')
        self.assertEqual(res["modifiche"], ["titolo"])
        self.assertEqual(self.riga(sid)["yt_title"], 'NF Type Beat 2024 "Clown" (Prod. Raedius)')

    def test_niente_da_cambiare_non_chiama_lapi(self):
        sid = self.crea_riga(yt_video_id="byD8lVZdsyo", yt_title=SNIPPET["title"])
        res = APP.yt_modifica_video(sid, titolo=SNIPPET["title"])
        self.assertTrue(res["ok"], res)
        self.assertEqual(res["modifiche"], [])
        self.assertIn("niente da cambiare", res["messaggio"])
        self.assertEqual(FakeVideos.scritture, [], "senza differenze non si chiama YouTube")

    def test_un_titolo_vuoto_si_ferma_prima(self):
        sid = self.crea_riga(yt_video_id="byD8lVZdsyo")
        res = APP.yt_modifica_video(sid, titolo="   ")
        self.assertFalse(res["ok"])
        self.assertIn("non può restare vuoto", res["error"])
        self.assertEqual(FakeVideos.scritture, [])

    def test_un_rifiuto_di_youtube_non_tocca_il_database(self):
        FakeVideos.errore_scrittura = "forbidden: the request is not authorized"
        sid = self.crea_riga(yt_video_id="byD8lVZdsyo", yt_description="descrizione originale")
        res = APP.yt_modifica_video(sid, descrizione="nuova descrizione")
        self.assertFalse(res["ok"])
        self.assertIn("ha rifiutato la modifica", res["error"])
        self.assertEqual(self.riga(sid)["yt_description"], "descrizione originale",
                         "con un errore la riga NON si tocca")

    def test_senza_collegamento_arriva_il_motivo(self):
        APP.yt_servizio = lambda: (None, "YouTube non è collegato: premi 🔗 Collega adesso nel pannello")
        sid = self.crea_riga(yt_video_id="byD8lVZdsyo")
        res = APP.yt_modifica_video(sid, descrizione="x")
        self.assertFalse(res["ok"])
        self.assertIn("non è collegato", res["error"])
        self.assertEqual(FakeVideos.scritture, [])


class TestStatoCollegamento(BaseYouTube):
    """`yt_stato`: i passaggi del collegamento (librerie → client → token → canale)."""

    def test_senza_client(self):
        stato = APP.yt_stato()
        self.assertTrue(stato["librerie"], "le librerie Google sono installate")
        self.assertFalse(stato["client"])
        self.assertFalse(stato["collegato"])
        self.assertEqual(stato["motivo"], "client OAuth non configurato")
        self.assertIn("console.cloud.google.com", stato["aiuto"], "l'aiuto c'è sempre")

    def test_client_salvato_ma_non_collegato(self):
        errore = APP.yt_salva_client("123-abc.apps.googleusercontent.com", "GOCSPX-segreto")
        self.assertEqual(errore, "")
        self.assertEqual(APP.yt_leggi_client()["client_id"], "123-abc.apps.googleusercontent.com")
        # il file dei segreti non è leggibile da tutti (600, come cookies.txt)
        self.assertEqual(os.stat(APP.YT_CLIENT_PATH).st_mode & 0o777, 0o600)
        stato = APP.yt_stato()
        self.assertTrue(stato["client"])
        self.assertFalse(stato["collegato"])
        self.assertIn("Collega adesso", stato["motivo"])

    def test_un_client_incompleto_non_si_salva(self):
        self.assertIn("ID client", APP.yt_salva_client("", "solo-secret"))
        self.assertIn("ID client", APP.yt_salva_client("solo-id", ""))
        self.assertEqual(APP.yt_leggi_client(), {})
        self.assertFalse(os.path.exists(APP.YT_CLIENT_PATH))

    def test_collegato_al_canale(self):
        APP.yt_salva_client("123-abc.apps.googleusercontent.com", "GOCSPX-segreto")
        with open(APP.YT_TOKEN_PATH, "w", encoding="utf-8") as f:
            f.write('{"token": "finto"}')
        stato = APP.yt_stato()
        self.assertTrue(stato["collegato"])
        self.assertEqual(stato["canale"], "Prod By Raedius")
        self.assertIn("collegato al canale", stato["motivo"])
        # senza leggere il canale non si chiama l'API (serve al pannello, che è veloce)
        FakeVideos.letture = []
        stato2 = APP.yt_stato(leggi_canale=False)
        self.assertTrue(stato2["collegato"])
        self.assertEqual(FakeVideos.letture, [])


class TestRotteYouTube(BaseYouTube):
    """Le rotte vere del pannello 🔗 e della modifica, su database temporaneo."""

    def test_stato(self):
        corpo = self.client.get("/youtube/stato").get_json()
        for chiave in ("librerie", "client", "token", "collegato", "canale", "aiuto", "motivo"):
            self.assertIn(chiave, corpo)

    def test_salva_il_client(self):
        res = self.client.post("/youtube/client",
                               json={"client_id": "abc.apps.googleusercontent.com",
                                     "client_secret": "sec"})
        self.assertEqual(res.status_code, 200)
        self.assertTrue(res.get_json()["stato"]["client"])
        res2 = self.client.post("/youtube/client", json={"client_id": "", "client_secret": ""})
        self.assertEqual(res2.status_code, 400)
        self.assertIn("ID client", res2.get_json()["error"])

    def test_collega_senza_client_lo_dice_e_non_apre_niente(self):
        res = self.client.post("/youtube/collega", json={})
        self.assertEqual(res.status_code, 400)
        self.assertFalse(res.get_json()["avviato"])
        self.assertIn("client OAuth", res.get_json()["motivo"])

    def test_scollega(self):
        res = self.client.post("/youtube/scollega")
        self.assertEqual(res.status_code, 200)
        self.assertTrue(res.get_json()["ok"])

    def test_lettura_del_video(self):
        sid = self.crea_riga(yt_video_id="byD8lVZdsyo")
        res = self.client.get(f"/db/songs/{sid}/youtube_video")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.get_json()["snippet"]["title"], SNIPPET["title"])
        sid2 = self.crea_riga("song_senza_video")
        res2 = self.client.get(f"/db/songs/{sid2}/youtube_video")
        self.assertEqual(res2.status_code, 502)
        self.assertIn("non ha né l'id del video né un link", res2.get_json()["error"])

    def test_modifica_del_video(self):
        sid = self.crea_riga(yt_video_id="byD8lVZdsyo")
        res = self.client.post(f"/db/songs/{sid}/youtube_video", json={"description": "nuova"})
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.get_json()["modifiche"], ["descrizione"])
class TestCablaggio(unittest.TestCase):
    """Il cablaggio (sorgenti): pannello, finestra ✍️, file privati, dipendenze."""

    def test_pannello_e_rotte_nella_pagina(self):
        html = leggi(PAGINA_PATH)
        for pezzo in ('id="youtube-panel"', 'id="yt-stato"', 'id="yt-client-id"',
                      'id="yt-client-secret"', 'id="yt-esito"',
                      "function ytStato(", "function ytCollega(", "function ytSalvaClient(",
                      "function ytScollega(", "/youtube/stato", "/youtube/client",
                      "/youtube/collega", "/youtube/scollega",
                      "console.cloud.google.com/projectcreate"):
            self.assertIn(pezzo, html, "manca nel pannello 🔗: " + pezzo)

    def test_finestra_modifica_nel_riquadro(self):
        html = leggi(PAGINA_PATH)
        for pezzo in ("✍️ Modifica sul video", 'id="yt-edit-titolo"', 'id="yt-edit-tag"',
                      'id="yt-edit-desc"', 'id="yt-edit-esito"',
                      "function ytLeggiVideo(", "function ytSalvaVideo(",
                      "function ytApriPannello(", "/youtube_video"):
            self.assertIn(pezzo, html, "manca nella finestra ✍️: " + pezzo)

    def test_le_rotte_e_il_timeout_nel_backend(self):
        app = leggi(APP_PATH)
        for pezzo in ('@app.route("/youtube/stato"', '@app.route("/youtube/client"',
                      '@app.route("/youtube/collega"', '@app.route("/youtube/scollega"',
                      '/db/songs/<song_id>/youtube_video',
                      "def yt_modifica_video(", "def snippet_da_modificare(",
                      "def yt_video_attuale(", "def yt_stato(",
                      # il consenso non può restare appeso all'infinito
                      "timeout_seconds=300",
                      # i due file privati si scrivono con permessi 600
                      "os.chmod(YT_CLIENT_PATH, 0o600)"):
            self.assertIn(pezzo, app, "manca nel backend: " + pezzo)

    def test_i_file_privati_sono_ignorati_da_git(self):
        gitignore = leggi(GITIGNORE_PATH)
        self.assertIn("youtube_client.json", gitignore)
        self.assertIn("youtube_token.json", gitignore)

    def test_le_librerie_sono_nei_requirements(self):
        req = leggi(REQUIREMENTS_PATH)
        self.assertIn("google-api-python-client", req)
        self.assertIn("google-auth-oauthlib", req)

    def test_il_readme_lo_racconta(self):
        readme = leggi(README_PATH)
        for pezzo in ("/youtube/collega", "youtube_client.json", "YouTube Data v3"):
            self.assertIn(pezzo, readme)


@unittest.skipUnless(app_is_up(SAMPLELAB_URL), f"app non attiva su {SAMPLELAB_URL}")
class TestAppViva(unittest.TestCase):
    """L'app viva, in sola lettura: lo stato del collegamento e il pannello in pagina."""

    def test_stato_del_collegamento(self):
        d = http_json("/youtube/stato")
        self.assertIn("librerie", d)
        self.assertIn("client", d)
        self.assertIn("collegato", d)
        self.assertIn("motivo", d)
        self.assertTrue(d["librerie"], "le librerie Google devono essere installate")

    def test_il_pannello_e_nella_pagina_servita(self):
        with urllib.request.urlopen(SAMPLELAB_URL + "/", timeout=30) as r:
            pagina = r.read().decode("utf-8", "replace")
        self.assertIn('id="youtube-panel"', pagina)
        self.assertIn("function ytCollega(", pagina)


if __name__ == "__main__":
    unittest.main(verbosity=2)





