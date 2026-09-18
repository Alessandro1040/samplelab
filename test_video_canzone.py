"""Test dei VIDEO delle canzoni (app (2).py + index (2).html) — 18/09/2026.

Richiesta di Alessandro: «riusciresti a fare in modo di lasciare un opzione per
scaricare oltre al mp3 (oppure wav) anche l'mp4 da youtube? e in generale di ogni
canzone di avere la possibilità di aggiungere un video dal computer o di
reperirlo da youtube».

I video hanno la loro cartella `videos/` (non versionata, come `covers/`) e il
nome del file sta in `songs.video_file`:
- dalla PLAYLIST: la casella «🎬 Anche il video (MP4)» fa scaricare l'MP4 di ogni
  brano, lo archivia in `videos/` e ne ricava l'mp3 da ascoltare (`local_file`);
- da OGNI RIGA: il pulsante «🎬 Video» apre il modale dove si prende il video da
  YouTube (`/db/songs/<id>/ensure_video`) o si sceglie un file dal computer o già
  in `videos/` (`POST /db/songs/<id>/video`), e lo si toglie (`DELETE`, il file
  va in `.trash/`).

Cosa copre questo file:
1. le funzioni pure: `mime_video`, `nome_video_sicuro` (niente percorsi, niente
   estensioni strane), `nome_video_unico`, `file_video_valido`;
2. `_downloads_snapshot(folder)` e `_pick_job_file(..., exts, folder)` — la
   ricerca del file di UN job ora sa guardare anche `videos/` (estensioni video);
3. il download del video con un yt-dlp finto: il file finisce in `videos/` e NON
   in `downloads/`, e il job dice il nome del file;
4. `avvia_download_video_canzone`: il video si aggancia a QUELLA riga
   (`video_file`), e se il video c'è già non riscarica niente;
5. le rotte vere su un database TEMPORANEO: upload dal computer, aggancio di un
   file già in `videos/`, file inesistente (404), 🗑 togli (il file va in
   `.trash/` e la colonna si svuota);
6. la PLAYLIST con l'opzione video (yt-dlp finto + ffmpeg vero su un mp4
   piccolissimo fabbricato al momento): la riga porta sia l'mp3 sia il video;
7. il cablaggio (sorgenti): casella in pagina, pulsante 🎬 su ogni riga, modale,
   rotte, `video_file` nelle tre liste dei modali e nella 📖 Legenda, `videos/`
   in .gitignore;
8. l'app VIVA in sola lettura: `/videos`, `/video/<file>` (404 se non c'è),
   `/db/schema` con la colonna documentata.

Esecuzione (dalla cartella di SampleLab):
    python3 -m unittest -v test_video_canzone
I test HTTP girano solo se l'app è attiva (default http://localhost:5070,
sovrascrivibile con la variabile SAMPLELAB_URL).
"""
import importlib.util
import io
import json
import os
import shutil
import subprocess
import tempfile
import time
import types
import unittest
import urllib.error
import urllib.request

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
APP_PATH = os.path.join(BASE_DIR, "app (2).py")
PAGINA_PATH = os.path.join(BASE_DIR, "index (2).html")
ONYX_PATH = os.path.join(BASE_DIR, "onyx_whosampled.html")
GITIGNORE_PATH = os.path.join(BASE_DIR, ".gitignore")
SAMPLELAB_URL = os.environ.get("SAMPLELAB_URL", "http://localhost:5070")


def load_app():
    """Carica il modulo dell'app dal file (il nome con spazio non conta)."""
    spec = importlib.util.spec_from_file_location("samplelab_app2_video", APP_PATH)
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
    with urllib.request.urlopen(SAMPLELAB_URL + path, timeout=20) as r:
        return json.loads(r.read().decode("utf-8"))


def http_stato(path):
    """Solo il codice HTTP della risposta (per i 404)."""
    try:
        with urllib.request.urlopen(SAMPLELAB_URL + path, timeout=20) as r:
            return r.status
    except urllib.error.HTTPError as e:
        return e.code


class TestNomiVideo(unittest.TestCase):
    """I nomi dei file video: sicuri, unici, con l'estensione giusta."""

    def test_mime_dal_nome(self):
        self.assertEqual(APP.mime_video("brano.mp4"), "video/mp4")
        self.assertEqual(APP.mime_video("brano.MKV"), "video/x-matroska")
        self.assertEqual(APP.mime_video("brano.webm"), "video/webm")
        self.assertEqual(APP.mime_video("senza-estensione"), "video/mp4")

    def test_nome_sicuro_toglie_i_percorsi(self):
        self.assertEqual(APP.nome_video_sicuro("/tmp/Mio Video.mp4"), "Mio Video.mp4")
        # Parentesi e quadre si tengono: sono normali nei nomi della libreria.
        self.assertEqual(APP.nome_video_sicuro("Brano (Live) [id].mp4"),
                         "Brano (Live) [id].mp4")

    def test_nome_sicuro_non_esce_dalla_cartella(self):
        # Un nome con `../` (o con una barra) non deve poter uscire da `videos/`:
        # le barre e i due punti diventano `_`.
        for brutto in ("../../etc/passwd", "..\\..\\windows\\system32", "a/b/c.mp4"):
            self.assertNotIn("/", APP.nome_video_sicuro(brutto))
            self.assertNotIn("\\", APP.nome_video_sicuro(brutto))
        self.assertTrue(APP.nome_video_sicuro("../../etc/passwd").endswith(".mp4"))

    def test_nome_sicuro_estensione(self):
        self.assertEqual(APP.nome_video_sicuro("brano.mkv"), "brano.mkv")
        self.assertEqual(APP.nome_video_sicuro("brano.txt"), "brano.txt.mp4")
        self.assertEqual(APP.nome_video_sicuro(""), "video.mp4")
        self.assertEqual(APP.nome_video_sicuro(None), "video.mp4")

    def test_nome_unico_e_file_valido(self):
        tmp = tempfile.mkdtemp(prefix="video_nomi_prova_")
        vid_originale = APP.VID_DIR
        APP.VID_DIR = tmp
        try:
            self.assertEqual(APP.nome_video_unico("Brano [id].mp4"), "Brano [id].mp4")
            open(os.path.join(tmp, "Brano [id].mp4"), "wb").write(b"x")
            self.assertEqual(APP.nome_video_unico("Brano [id].mp4"), "Brano [id] (1).mp4")
            self.assertEqual(APP.nome_video_unico("strano.xyz"), "strano.mp4")
            self.assertTrue(APP.file_video_valido("Brano [id].mp4"))
            self.assertFalse(APP.file_video_valido("altro.mp4"))
            self.assertFalse(APP.file_video_valido(""))
            # Un nome con percorso si guarda per NOME (mai fuori da videos/): qui
            # il file non c'è dentro `videos/`, quindi non è valido.
            fuori = os.path.join(os.path.dirname(tmp), "fuori.mp4")
            open(fuori, "wb").write(b"x")
            self.assertFalse(APP.file_video_valido("../fuori.mp4"))
        finally:
            APP.VID_DIR = vid_originale
            shutil.rmtree(tmp, ignore_errors=True)


class BaseVideo(unittest.TestCase):
    """Database, `downloads/`, `videos/` e `.trash/` TEMPORANEI (la libreria non si tocca)."""

    class FakeYDL:
        """yt-dlp finto: scrive lui il file (nella cartella dell'outtmpl) e torna l'info.

        Il formato chiesto dice se è un video o un audio, così si prova la strada
        vera di `_do_download` senza toccare la rete. `chiamate` registra gli URL
        chiesti (per verificare DA DOVE arriva il video) e `fallisci_url` gli URL
        diretti che devono fallire (per provare che NON si prende un altro video).
        """

        chiamate = []
        fallisci_url = ()

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
            type(self).chiamate.append(str(url))
            # La RICERCA YouTube (ytsearch) non ha `outtmpl`: si risponde con una
            # voce sola, come fa yt-dlp, così si prova anche la strada vera
            # «artista + titolo → video → file».
            if "ytsearch" in str(url):
                return {"entries": [{"title": "Artista Di Prova - Brano Di Prova",
                                     "webpage_url": "https://www.youtube.com/watch?v=idtst123456",
                                     "id": "idtst123456", "duration": 200}]}
            if str(url) in tuple(type(self).fallisci_url):
                raise Exception("This video is unavailable (prova)")
            video = "bestvideo" in str(self.opts.get("format") or "")
            nome = ("Brano Di Prova [idtst123456].mp4" if video
                    else "Brano Di Prova [idtst123456].mp3")
            cartella = os.path.dirname(self.opts["outtmpl"])
            percorso = os.path.join(cartella, nome)
            with open(percorso, "wb") as f:
                f.write(b"video" * 8 if video else b"audio" * 8)
            return {"id": "idtst123456", "title": "Brano Di Prova",
                    "upload_date": "20250915", "description": "descrizione di prova",
                    "requested_downloads": [{"filepath": percorso}]}

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="video_canzone_prova_")
        self.orig = (APP.DB_PATH, APP.DL_DIR, APP.VID_DIR, APP.TRASH_DIR, APP.yt_dlp)
        APP.DB_PATH = os.path.join(self.tmp, "samplelab di prova.db")
        APP.DL_DIR = os.path.join(self.tmp, "downloads")
        APP.VID_DIR = os.path.join(self.tmp, "videos")
        APP.TRASH_DIR = os.path.join(self.tmp, ".trash")
        for cartella in (APP.DL_DIR, APP.VID_DIR, APP.TRASH_DIR):
            os.makedirs(cartella, exist_ok=True)
        APP.init_db()
        self.FakeYDL.chiamate = []
        self.FakeYDL.fallisci_url = ()
        APP.yt_dlp = types.SimpleNamespace(YoutubeDL=self.FakeYDL)
        self.client = APP.app.test_client()

    def tearDown(self):
        (APP.DB_PATH, APP.DL_DIR, APP.VID_DIR, APP.TRASH_DIR, APP.yt_dlp) = self.orig
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

    def aspetta(self, condizione, secondi=15):
        fine = time.time() + secondi
        while time.time() < fine:
            if condizione():
                return True
            time.sleep(0.1)
        return condizione()


class TestDownloadVideoDellaRiga(BaseVideo):
    """Il video scaricato da YouTube per una riga (`avvia_download_video_canzone`).

    Regola del 18/09/2026: il video è QUELLO della canzone — si prende dal link
    YouTube della riga, o dall'id del video salvato col download; solo se non c'è
    né l'uno né l'altro si cerca per artista + titolo (e se il link c'è ma quel
    video non è scaricabile, il job lo dice: non prende un video diverso).
    """

    def test_il_video_finisce_in_videos_e_si_aggancia_alla_riga(self):
        sid = self.crea_riga()
        job, motivo = APP.avvia_download_video_canzone(sid)
        self.assertTrue(job, motivo)
        self.assertTrue(self.aspetta(lambda: (self.riga(sid)["video_file"] or "") != ""),
                        "il video non è stato agganciato alla riga")
        r = self.riga(sid)
        self.assertEqual(r["video_file"], "Brano Di Prova [idtst123456].mp4")
        self.assertTrue(APP.file_video_valido(r["video_file"]))
        self.assertEqual(os.listdir(APP.DL_DIR), [], "il video non deve stare in downloads/")
        self.assertIsNone(r["local_file"], "il video NON è il file audio della canzone")

    def test_se_il_video_ce_gia_non_si_riscarica(self):
        sid = self.crea_riga(video_file="Brano Di Prova [idtst123456].mp4")
        open(os.path.join(APP.VID_DIR, "Brano Di Prova [idtst123456].mp4"), "wb").write(b"x")
        job, motivo = APP.avvia_download_video_canzone(sid)
        self.assertEqual(job, "")
        self.assertEqual(motivo, "il video c'è già")
        # ...e col forzato riparte lo stesso (poi si aspetta che finisca, così il
        # job non resta in corso per i test successivi)
        job2, motivo2 = APP.avvia_download_video_canzone(sid, forzato=True)
        self.assertTrue(job2, motivo2)
        self.assertTrue(self.aspetta(
            lambda: (APP.jobs.get(job2) or {}).get("status") in ("done", "error")))

    def test_riga_inesistente(self):
        self.assertEqual(APP.avvia_download_video_canzone("song_fantasma"),
                         ("", "riga non trovata"))

    def test_senza_audio_il_video_si_scarica_lo_stesso(self):
        # Una riga senza titolo né artista né link YouTube non ha niente da cercare.
        sid = self.crea_riga(titolo="", artista="")
        job, motivo = APP.avvia_download_video_canzone(sid)
        self.assertEqual(job, "")
        self.assertIn("niente da cercare", motivo)

    def test_il_video_viene_dal_LINK_della_riga(self):
        # Il caso vero del 18/09/2026: la riga aveva il link YouTube, ma il video
        # veniva CERCATO per artista+titolo e scaricava un altro video («Public
        # Enemy» è finita con «Public Enemy #1»). Ora si usa il link e non si cerca.
        sid = self.crea_riga(youtube_url="https://www.youtube.com/watch?v=GmCU1u-g7LI")
        job, motivo = APP.avvia_download_video_canzone(sid)
        self.assertTrue(job, motivo)
        self.assertTrue(self.aspetta(lambda: APP.jobs.get(job, {}).get("status") == "done"))
        self.assertEqual(APP.jobs[job]["da_link"], True)
        self.assertEqual(self.FakeYDL.chiamate,
                         ["https://www.youtube.com/watch?v=GmCU1u-g7LI"])
        self.assertFalse([u for u in self.FakeYDL.chiamate if "ytsearch" in u],
                         "con un link non si deve cercare")

    def test_il_video_viene_dall_id_salvato_col_download(self):
        # Le righe arrivate da una playlist hanno l'id del video (`yt_video_id`):
        # il link si ricostruisce da lì e RESTA scritto nella riga (per le volte
        # dopo, e per il pulsante 🎬 dei giorni successivi).
        sid = self.crea_riga(yt_video_id="GmCU1u-g7LI")
        job, motivo = APP.avvia_download_video_canzone(sid)
        self.assertTrue(job, motivo)
        self.assertTrue(self.aspetta(lambda: APP.jobs.get(job, {}).get("status") == "done"))
        self.assertEqual(APP.jobs[job]["da_link"], True)
        self.assertEqual(self.FakeYDL.chiamate,
                         ["https://www.youtube.com/watch?v=GmCU1u-g7LI"])
        self.assertEqual(self.riga(sid)["youtube_url"],
                         "https://www.youtube.com/watch?v=GmCU1u-g7LI")

    def test_senza_link_ne_id_si_cerca_per_artista_e_titolo(self):
        sid = self.crea_riga()
        job, motivo = APP.avvia_download_video_canzone(sid)
        self.assertTrue(job, motivo)
        self.assertTrue(self.aspetta(lambda: APP.jobs.get(job, {}).get("status") == "done"))
        self.assertEqual(APP.jobs[job]["da_link"], False)
        self.assertTrue(any("ytsearch" in u for u in self.FakeYDL.chiamate))

    def test_se_il_link_non_e_scaricabile_non_si_prende_un_altro_video(self):
        # Il video del link non è disponibile: il job lo DICE e non scarica quello
        # che troverebbe cercando (sarebbe un altro brano).
        sid = self.crea_riga(youtube_url="https://www.youtube.com/watch?v=GmCU1u-g7LI")
        self.FakeYDL.fallisci_url = ("https://www.youtube.com/watch?v=GmCU1u-g7LI",)
        vero_sleep = APP.time.sleep
        APP.time.sleep = lambda *a, **k: None      # niente 3+3 s fra i tentativi
        try:
            job, motivo = APP.avvia_download_video_canzone(sid)
            self.assertTrue(job, motivo)
            self.assertTrue(self.aspetta(lambda: APP.jobs.get(job, {}).get("status") == "error"))
        finally:
            APP.time.sleep = vero_sleep
        self.assertIn("non è scaricabile", APP.jobs[job]["error"])
        self.assertFalse([u for u in self.FakeYDL.chiamate if "ytsearch" in u],
                         "non si deve cercare un altro video")
        self.assertIsNone(self.riga(sid)["video_file"])
        self.assertEqual(self.riga(sid)["youtube_url"],
                         "https://www.youtube.com/watch?v=GmCU1u-g7LI")


class TestFotoDelleCartelle(unittest.TestCase):
    """`_downloads_snapshot` / `_pick_job_file` sanno guardare anche `videos/`."""

    def test_la_foto_si_puo_fare_su_un_altra_cartella(self):
        tmp = tempfile.mkdtemp(prefix="video_snapshot_prova_")
        try:
            open(os.path.join(tmp, "brano.mp4"), "wb").write(b"x" * 10)
            snap = APP._downloads_snapshot(tmp)
            self.assertIn("brano.mp4", snap)
            self.assertNotIn("brano.mp4", APP._downloads_snapshot())   # non è in downloads/
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_si_sceglie_il_file_colle_estensioni_giuste(self):
        tmp = tempfile.mkdtemp(prefix="video_pick_prova_")
        try:
            prima, dopo = {}, {}
            for nome in ("Brano [id].mp4", "Brano [id].mp3"):
                percorso = os.path.join(tmp, nome)
                open(percorso, "wb").write(b"x" * 10)
                dopo[nome] = (os.path.getmtime(percorso), os.path.getsize(percorso))
            self.assertEqual(APP._pick_job_file(prima, dopo, "", APP.VIDEO_EXTS, tmp),
                             "Brano [id].mp4")
            self.assertEqual(APP._pick_job_file(prima, dopo, "", APP.AUDIO_EXTS, tmp),
                             "Brano [id].mp3")
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


class TestRotteVideo(BaseVideo):
    """Le rotte vere del modale 🎬: dal computer, da `videos/`, togli."""

    def test_upload_dal_computer(self):
        sid = self.crea_riga()
        res = self.client.post(f"/db/songs/{sid}/video",
                               data={"file": (io.BytesIO(b"finto video"), "Mio Video!.mp4")},
                               content_type="multipart/form-data")
        self.assertEqual(res.status_code, 200)
        corpo = res.get_json()
        self.assertEqual(corpo["origine"], "caricato dal computer")
        self.assertEqual(corpo["video_file"], "Mio Video_.mp4")
        self.assertTrue(APP.file_video_valido("Mio Video_.mp4"))
        self.assertEqual(self.riga(sid)["video_file"], "Mio Video_.mp4")

    def test_upload_senza_estensione_diventa_mp4(self):
        sid = self.crea_riga()
        res = self.client.post(f"/db/songs/{sid}/video",
                               data={"file": (io.BytesIO(b"x"), "video senza nome")},
                               content_type="multipart/form-data")
        self.assertEqual(res.get_json()["video_file"], "video senza nome.mp4")

    def test_un_secondo_upload_non_sovrascrive(self):
        sid = self.crea_riga()
        for atteso in ("Brano.mp4", "Brano (1).mp4"):
            res = self.client.post(f"/db/songs/{sid}/video",
                                   data={"file": (io.BytesIO(b"x"), "Brano.mp4")},
                                   content_type="multipart/form-data")
            self.assertEqual(res.get_json()["video_file"], atteso)
        self.assertEqual(sorted(os.listdir(APP.VID_DIR)), ["Brano (1).mp4", "Brano.mp4"])

    def test_scegliere_un_video_gia_in_videos(self):
        sid = self.crea_riga()
        open(os.path.join(APP.VID_DIR, "Archivio [abc].mp4"), "wb").write(b"x")
        res = self.client.post(f"/db/songs/{sid}/video", json={"filename": "Archivio [abc].mp4"})
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.get_json()["origine"], "scelto fra i video dell'app")
        self.assertEqual(self.riga(sid)["video_file"], "Archivio [abc].mp4")

    def test_video_inesistente_o_richiesta_vuota(self):
        sid = self.crea_riga()
        res = self.client.post(f"/db/songs/{sid}/video", json={"filename": "non-c-e.mp4"})
        self.assertEqual(res.status_code, 404)
        self.assertIn("non-c-e.mp4", res.get_json()["error"])
        self.assertEqual(self.client.post(f"/db/songs/{sid}/video", json={}).status_code, 400)
        # Un nome con percorso non pesca fuori da `videos/`.
        fuori = os.path.join(self.tmp, "fuori.mp4")
        open(fuori, "wb").write(b"x")
        res2 = self.client.post(f"/db/songs/{sid}/video", json={"filename": "../fuori.mp4"})
        self.assertEqual(res2.status_code, 404)

    def test_canzone_inesistente(self):
        res = self.client.post("/db/songs/song_fantasma/video", json={"filename": "x.mp4"})
        self.assertEqual(res.status_code, 404)
        self.assertEqual(self.client.delete("/db/songs/song_fantasma/video").status_code, 404)

    def test_togliere_il_video_lo_manda_nel_cesto(self):
        sid = self.crea_riga(video_file="Da Togliere [abc].mp4", comment="nota mia")
        percorso = os.path.join(APP.VID_DIR, "Da Togliere [abc].mp4")
        open(percorso, "wb").write(b"x" * 20)
        res = self.client.delete(f"/db/songs/{sid}/video")
        self.assertEqual(res.status_code, 200)
        self.assertIsNone(self.riga(sid)["video_file"])
        self.assertFalse(os.path.exists(percorso))
        self.assertTrue(os.path.exists(os.path.join(APP.TRASH_DIR, "Da Togliere [abc].mp4")))
        self.assertEqual(self.riga(sid)["comment"], "nota mia")   # il resto non si tocca

    def test_togliere_un_video_che_non_c_e(self):
        sid = self.crea_riga()
        self.assertEqual(self.client.delete(f"/db/songs/{sid}/video").status_code, 200)
        sid2 = self.crea_riga("song_prova2", video_file="file-sparito.mp4")
        res = self.client.delete(f"/db/songs/{sid2}/video")
        self.assertEqual(res.status_code, 200)
        self.assertIsNone(self.riga("song_prova2")["video_file"])

    def test_la_rotta_ensure_video_avvia_il_job_e_aggancia(self):
        # Una riga sua (non «song_prova»): la rotta non parte se per QUELLA riga
        # c'è già un download in corso, e altri test usano lo stesso id.
        sid = self.crea_riga("song_rotta_video")
        res = self.client.post(f"/db/songs/{sid}/ensure_video", json={})
        self.assertEqual(res.status_code, 200)
        corpo = res.get_json()
        self.assertTrue(corpo["avviato"], corpo.get("motivo"))
        self.assertTrue(self.aspetta(lambda: (self.riga(sid)["video_file"] or "") != ""))
        self.assertEqual(self.riga(sid)["video_file"], "Brano Di Prova [idtst123456].mp4")


class TestPlaylistConVideo(BaseVideo):
    """La playlist con «🎬 Anche il video (MP4)»: un download, mp3 + mp4.

    Il downloader è finto ma il file che scrive è un MP4 VERO (0,4 s, fatto con
    ffmpeg): così si prova anche la conversione dal video all'mp3 da ascoltare,
    senza usare la rete.
    """

    class FakeYDLPlaylist:
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
            cartella = os.path.dirname(self.opts["outtmpl"])
            nome = "Artista Uno - Brano Uno [aaaaaaaaaaa].mp4"
            percorso = os.path.join(cartella, nome)
            subprocess.run([APP.FFMPEG, "-y", "-f", "lavfi",
                            "-i", "color=c=black:s=32x32:d=0.4",
                            "-f", "lavfi", "-i", "anullsrc=r=44100:cl=mono",
                            "-shortest", "-pix_fmt", "yuv420p",
                            percorso], capture_output=True, timeout=90)
            return {"title": "Playlist di prova", "entries": [
                {"id": "aaaaaaaaaaa", "title": "Brano Uno", "upload_date": "20250915",
                 "channel": "Canale Uno", "description": "descrizione uno",
                 "requested_downloads": [{"filepath": percorso}]}]}

    def setUp(self):
        super().setUp()
        if not APP.FFMPEG:
            self.skipTest("ffmpeg non c'è: la conversione dal video non si può provare")
        APP.yt_dlp = types.SimpleNamespace(YoutubeDL=self.FakeYDLPlaylist)

    def lancia(self, video, jid="job_video_prova"):
        APP.jobs[jid] = {"status": "pending", "progress": {}, "files": [],
                         "filename": None, "yt_title": "", "error": ""}
        APP.do_download_playlist(jid, "https://www.youtube.com/playlist?list=PLprova",
                                 "mp3", video)
        return APP.jobs.pop(jid)

    def test_la_riga_porta_sia_l_mp3_sia_il_video(self):
        job = self.lancia(video=True)
        self.assertEqual(job["status"], "done", job.get("error"))
        self.assertEqual(job["con_video"], 1)
        self.assertEqual(job["registered"], 1)
        self.assertEqual(job["con_metadati"], 1)
        self.assertEqual(job["con_anno"], 1)
        with APP.get_db() as conn:
            r = conn.execute("SELECT * FROM songs").fetchone()
        self.assertEqual(r["title"], "Brano Uno")
        self.assertEqual(r["artist"], "Artista Uno")
        self.assertEqual(r["video_file"], "Artista Uno - Brano Uno [aaaaaaaaaaa].mp4")
        self.assertTrue(APP.file_video_valido(r["video_file"]))
        self.assertEqual(r["year"], 2025)
        # l'audio c'è, è l'mp3 ricavato dal video, ed è in downloads/
        self.assertTrue((r["local_file"] or "").endswith(".mp3"), r["local_file"])
        self.assertTrue(os.path.exists(os.path.join(APP.DL_DIR, r["local_file"])))
        # il video è stato SPOSTATO: in downloads/ non è rimasto
        self.assertFalse(os.path.exists(os.path.join(APP.DL_DIR, r["video_file"])))

    def test_senza_l_opzione_niente_video(self):
        # Stesso download, ma senza la casella: il file resta dov'era prima e la
        # riga non ha nessun video (comportamento di sempre).
        job = self.lancia(video=False)
        self.assertEqual(job["status"], "done", job.get("error"))
        self.assertEqual(job["con_video"], 0)
        with APP.get_db() as conn:
            r = conn.execute("SELECT * FROM songs").fetchone()
        self.assertIsNone(r["video_file"])
        self.assertEqual(os.listdir(APP.VID_DIR), [])
        self.assertTrue((r["local_file"] or "").endswith(".mp3"), r["local_file"])


class TestCablaggio(unittest.TestCase):
    """I pezzi devono restare attaccati (letti dai sorgenti, senza app attiva)."""

    def test_le_rotte_ci_sono(self):
        src = leggi(APP_PATH)
        for pezzo in ('@app.route("/video/<path:filename>")',
                      '@app.route("/video-file/<path:filename>")',
                      '@app.route("/videos")',
                      '@app.route("/db/songs/<song_id>/video", methods=["POST"])',
                      '@app.route("/db/songs/<song_id>/video", methods=["DELETE"])',
                      '@app.route("/db/songs/<song_id>/ensure_video", methods=["POST"])'):
            self.assertIn(pezzo, src, "manca la rotta: " + pezzo)

    def test_il_video_e_una_colonna_documentata_del_database(self):
        src = leggi(APP_PATH)
        self.assertIn('("video_file", "TEXT"),', src)
        self.assertTrue(APP.COLUMN_DOCS["songs"].get("video_file", "").strip())
        # il PUT /db/songs/<id> deve accettare il campo (altrimenti l'editor ✏️
        # lo manderebbe a vuoto): si guarda la sua lista `allowed`.
        allowed = src.split("def db_update_song(song_id):")[1].split("]")[0]
        self.assertIn('"video_file"', allowed)

    def test_la_playlist_passa_l_opzione_video(self):
        src = leggi(APP_PATH)
        self.assertIn('def do_download_playlist(job_id, url, fmt="mp3", video=False):', src)
        self.assertIn('jobs[job_id]["con_video"] = len(video_per_id)', src)
        self.assertIn("args=(jid, url, fmt, video)", src)

    def test_la_pagina_ha_casella_pulsante_e_modale(self):
        html = leggi(PAGINA_PATH)
        self.assertIn('id="db-playlist-video"', html)      # 🎬 anche il video
        self.assertIn("j.con_video", html)                 # l'esito lo dice
        self.assertIn('id="video-modal"', html)            # il modale 🎬
        self.assertIn("apriVideoModal('${s.id}')", html)   # il pulsante su OGNI riga
        self.assertIn("videoDalComputer", html)
        self.assertIn("videoDaYoutube", html)
        self.assertIn("videoDaArchivio", html)
        self.assertIn("togliVideo", html)
        self.assertIn("/ensure_video", html)
        self.assertIn("/video-file/", html)

    def test_le_tre_liste_dei_modali_conoscono_il_video(self):
        pagina = leggi(PAGINA_PATH)
        onyx = leggi(ONYX_PATH)
        self.assertIn("'video_file'", pagina)      # CAMPI_DB_MODALE
        self.assertIn('"video_file"', pagina)      # editor ✏️ (saveDbEditor)
        self.assertIn("inp('video_file'", pagina)  # il campo nel form dell'editor
        self.assertIn("['video_file'", onyx)       # CAMPI_DB_INFO del player

    def test_videos_non_si_versiona(self):
        self.assertIn("videos/", leggi(GITIGNORE_PATH))


class TestAppViva(unittest.TestCase):
    """Sola lettura sull'app attiva: le rotte dei video rispondono."""

    def setUp(self):
        if not app_is_up(SAMPLELAB_URL):
            self.skipTest("app non attiva su " + SAMPLELAB_URL)

    def test_elenco_video(self):
        elenco = http_json("/videos")
        self.assertIsInstance(elenco, list)
        for voce in elenco:
            self.assertIn("name", voce)
            self.assertTrue(voce["name"].lower().endswith(APP.VIDEO_EXTS), voce["name"])

    def test_video_che_non_c_e_da_404(self):
        self.assertEqual(http_stato("/video/non-esiste-questo-file.mp4"), 404)
        self.assertEqual(http_stato("/video-file/non-esiste-questo-file.mp4"), 404)

    def test_schema_con_la_colonna_documentata(self):
        schema = http_json("/db/schema")
        songs = next(t for t in schema["tables"] if t["name"] == "songs")
        per_nome = {c["name"]: c for c in songs["columns"]}
        self.assertIn("video_file", per_nome)
        self.assertEqual(per_nome["video_file"]["type"], "TEXT")
        self.assertTrue(per_nome["video_file"]["doc"].strip())
