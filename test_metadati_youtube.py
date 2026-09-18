"""Test dei metadati del video YouTube nelle righe della libreria (app (2).py).

Richiesta del 18/09/2026 (Alessandro): «se carico una playlist da YouTube viene
scaricata tutta automaticamente giusto? puoi fare in modo che prenda
automaticamente l'anno da YouTube? dalla data di caricamento del video? e che
prenda in input anche la descrizione del video e tutte le altre informazioni
disponibili da YouTube?»

Prima `do_download_playlist` buttava via tutto l'info_dict di yt-dlp (lo usava
solo per il titolo della playlist) e ogni file diventava una riga ricavata dal
NOME del file: l'anno, la descrizione e il resto andavano persi per sempre.

Cosa copre questo file:
1. `data_da_yt` — `'20250915'` → `'2025-09-15'` (e le date che non sono date);
2. `id_video_dal_nome_file` — l'`[id]` che `DL_OUTTMPL` scrive nel nome del file,
   cioè come si sa a QUALE voce della playlist appartiene ogni file scaricato;
3. `campi_youtube` — i campi `yt_*` presi dall'info_dict (descrizione intera,
   canale, viste, tag, categoria, miniatura…), la data di CARICAMENTO (che dà
   l'anno della riga, come chiesto) e la data di uscita salvata a parte: non sono
   la stessa cosa («Who Knew» di Eminem è caricato nel 2018 ma è del 2000);
4. `mappa_metadati_playlist` — la mappa voce→campi, coi buchi di yt-dlp
   (`None`) e le voci senza id;
5. la migrazione: le colonne `yt_*` si aggiungono da sole a un database che
   esiste già (provato su un database temporaneo creato con lo schema vecchio);
6. le regole di scrittura su un database TEMPORANEO: la riga nuova nasce coi
   metadati, un campo fuori lista non arriva nell'SQL, i valori vuoti non
   spengono i dati, e `year` (campo curato) si riempie SOLO se è vuoto;
7. il cablaggio (sorgenti): la migrazione, `do_download_playlist` che passa i
   campi a `register_local_file`, i conteggi in `/status` e la riga in pagina,
   più la 📖 Legenda: ogni colonna `yt_*` ha la sua descrizione in COLUMN_DOCS;
8. l'app viva (sola lettura): `/db/schema` ha le colonne coi documenti.

Esecuzione (dalla cartella di SampleLab):
    python3 -m unittest -v test_metadati_youtube
I test HTTP girano solo se l'app è attiva (default http://localhost:5070,
sovrascrivibile con la variabile SAMPLELAB_URL).
"""
import importlib.util
import json
import os
import shutil
import sqlite3
import tempfile
import types
import unittest
import urllib.request

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
APP_PATH = os.path.join(BASE_DIR, "app (2).py")
PAGINA_PATH = os.path.join(BASE_DIR, "index (2).html")
DB_PATH = os.path.join(BASE_DIR, "samplelab (2).db")
SAMPLELAB_URL = os.environ.get("SAMPLELAB_URL", "http://localhost:5070")


def load_app():
    """Carica il modulo dell'app dal file (il nome con spazio non conta)."""
    spec = importlib.util.spec_from_file_location("samplelab_app2_metadati_yt", APP_PATH)
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
    with urllib.request.urlopen(SAMPLELAB_URL + path, timeout=20) as r:
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


class TestDataDaYt(unittest.TestCase):
    """`data_da_yt`: le otto cifre di yt-dlp diventano una data leggibile."""

    def test_otto_cifre(self):
        self.assertEqual(APP.data_da_yt("20250915"), "2025-09-15")
        self.assertEqual(APP.data_da_yt("19991231"), "1999-12-31")

    def test_data_gia_leggibile_e_spazi(self):
        self.assertEqual(APP.data_da_yt("2025-09-15"), "2025-09-15")
        self.assertEqual(APP.data_da_yt(" 20250915 "), "2025-09-15")

    def test_cosa_non_e_una_data(self):
        for brutto in ("", None, "abc", "2025091", "20250915T10:00", "20251301", 0):
            self.assertEqual(APP.data_da_yt(brutto), "", brutto)

    def test_fuori_dagli_anni_plausibili(self):
        self.assertEqual(APP.data_da_yt("12050915"), "")
        self.assertEqual(APP.data_da_yt("30050915"), "")


class TestIdVideoDalNomeFile(unittest.TestCase):
    """L'`[id]` nel nome del file: come si riconosce la voce della playlist."""

    def test_id_in_coda(self):
        self.assertEqual(APP.id_video_dal_nome_file(
            "ILL MOVEMENT - 5 - HOLLYWOOD (feat SMACCO) [dQw4w9WgXcQ].mp3"),
            "dQw4w9WgXcQ")
        self.assertEqual(APP.id_video_dal_nome_file("Titolo [IX7UWaSoVv0].webm"),
                         "IX7UWaSoVv0")

    def test_senza_id_o_id_troppo_corto(self):
        self.assertEqual(APP.id_video_dal_nome_file("Titolo senza id.mp3"), "")
        self.assertEqual(APP.id_video_dal_nome_file("Titolo [abc].mp3"), "")
        self.assertEqual(APP.id_video_dal_nome_file(""), "")
        self.assertEqual(APP.id_video_dal_nome_file(None), "")

    def test_vince_l_ultimo(self):
        # Il template mette l'id in coda: un `[qualcosa]` nel titolo non confonde.
        self.assertEqual(APP.id_video_dal_nome_file("Titolo [Live] [dQw4w9WgXcQ].mp3"),
                         "dQw4w9WgXcQ")


class TestCampiYoutube(unittest.TestCase):
    """`campi_youtube`: dall'info_dict ai campi `yt_*` (+ l'anno)."""

    def test_video_completo(self):
        campi = APP.campi_youtube(INFO)
        self.assertEqual(campi["yt_video_id"], "IX7UWaSoVv0")
        self.assertEqual(campi["yt_channel"], "50 Cent")
        self.assertEqual(campi["yt_channel_url"], "https://www.youtube.com/channel/UCxxx")
        self.assertEqual(campi["yt_tags"], "50 cent, hip hop, window shopper")
        self.assertEqual(campi["yt_category"], "Music")
        self.assertEqual(campi["yt_views"], 12345678)
        self.assertEqual(campi["yt_likes"], 98765)
        self.assertEqual(campi["yt_comments"], 4321)
        self.assertEqual(campi["yt_duration"], 236.4)
        self.assertTrue(campi["yt_thumbnail"].startswith("https://i.ytimg.com/"))
        self.assertIn("Official video", campi["yt_description"])

    def test_la_data_di_caricamento_vince_sulla_data_di_uscita(self):
        campi = APP.campi_youtube(INFO)
        self.assertEqual(campi["yt_upload_date"], "2025-09-15")
        self.assertEqual(campi["year"], 2025)
        # La data di uscita si salva comunque a parte: sono due cose diverse.
        self.assertEqual(campi["yt_release_date"], "2005-11-15")

    def test_senza_data_di_caricamento_l_anno_viene_dalla_data_di_uscita(self):
        info = dict(INFO)
        del info["upload_date"]
        campi = APP.campi_youtube(info)
        self.assertNotIn("yt_upload_date", campi)
        self.assertEqual(campi["yt_release_date"], "2005-11-15")
        self.assertEqual(campi["year"], 2005)

    def test_senza_nessuna_data_niente_anno(self):
        info = {k: v for k, v in INFO.items() if k not in ("upload_date", "release_date")}
        campi = APP.campi_youtube(info)
        self.assertNotIn("yt_upload_date", campi)
        self.assertNotIn("yt_release_date", campi)
        self.assertNotIn("year", campi)

    def test_canale_con_ripiego_sull_uploader(self):
        info = {k: v for k, v in INFO.items() if k not in ("channel", "channel_url")}
        info["uploader"] = "OldChannel"
        info["uploader_url"] = "https://www.youtube.com/@OldChannel"
        campi = APP.campi_youtube(info)
        self.assertEqual(campi["yt_channel"], "OldChannel")
        self.assertEqual(campi["yt_channel_url"], "https://www.youtube.com/@OldChannel")

    def test_i_campi_vuoti_non_ci_sono(self):
        campi = APP.campi_youtube({"id": "abc", "description": "   ", "tags": [],
                                   "view_count": None, "like_count": "molte"})
        self.assertEqual(set(campi) - {"yt_meta_at"}, {"yt_video_id"})

    def test_numeri_arrivano_anche_come_testo(self):
        campi = APP.campi_youtube({"id": "abc", "view_count": "1000", "duration": "12.5"})
        self.assertEqual(campi["yt_views"], 1000)
        self.assertEqual(campi["yt_duration"], 12.5)

    def test_quando_i_metadati_non_ci_sono(self):
        self.assertEqual(APP.campi_youtube(None), {})
        self.assertEqual(APP.campi_youtube("testo"), {})
        # Un info_dict vuoto non ha comunque niente da dire sul video.
        self.assertEqual(set(APP.campi_youtube({})), {"yt_meta_at"})

    def test_quando_sono_stati_letti(self):
        campi = APP.campi_youtube(INFO)
        self.assertRegex(campi["yt_meta_at"], r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}$")


class TestMappaMetadatiPlaylist(unittest.TestCase):
    """Le voci della playlist → mappa id→campi (coi buchi di yt-dlp)."""

    def test_una_voce_per_id_e_i_buchi_si_saltano(self):
        mappa = APP.mappa_metadati_playlist([INFO, None, {"id": "abc"}, 42])
        self.assertEqual(set(mappa), {"IX7UWaSoVv0", "abc"})
        self.assertEqual(mappa["IX7UWaSoVv0"]["yt_channel"], "50 Cent")

    def test_id_ricavato_dal_file_scaricato(self):
        voce = {"title": "Senza id", "description": "d",
                "requested_downloads": [{"filepath": "/tmp/downloads/Titolo [zzz99].mp3"}]}
        mappa = APP.mappa_metadati_playlist([voce])
        self.assertEqual(set(mappa), {"zzz99"})

    def test_nome_file_di_ripiego(self):
        mappa = APP.mappa_metadati_playlist([{"_filename": "Titolo [aaa111bbb].webm"}])
        self.assertEqual(set(mappa), {"aaa111bbb"})

    def test_voce_senza_id_non_entra(self):
        self.assertEqual(APP.mappa_metadati_playlist([{"title": "x"}]), {})

    def test_lista_vuota(self):
        self.assertEqual(APP.mappa_metadati_playlist(None), {})
        self.assertEqual(APP.mappa_metadati_playlist([]), {})


class TestRigheDelDatabase(unittest.TestCase):
    """Le regole di scrittura su un database TEMPORANEO (la libreria non si tocca)."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="metadati_youtube_prova_")
        self.db_originale = APP.DB_PATH
        APP.DB_PATH = os.path.join(self.tmp, "samplelab di prova.db")
        APP.init_db()

    def tearDown(self):
        APP.DB_PATH = self.db_originale
        shutil.rmtree(self.tmp, ignore_errors=True)

    def riga(self, sid):
        with APP.get_db() as conn:
            return conn.execute("SELECT * FROM songs WHERE id=?", (sid,)).fetchone()

    def scrivi(self, sid, titolo, artista, **campi):
        with APP.get_db() as conn:
            colonne = ["id", "title", "artist"] + list(campi)
            conn.execute("INSERT INTO songs(" + ", ".join(colonne) + ") VALUES(" +
                         ", ".join(["?"] * len(colonne)) + ")",
                         [sid, titolo, artista] + list(campi.values()))

    def test_le_colonne_yt_ci_sono_dopo_la_migrazione(self):
        with APP.get_db() as conn:
            cols = [r["name"] for r in conn.execute("PRAGMA table_info(songs)")]
        for nome, _ in APP.CAMPI_YOUTUBE:
            self.assertIn(nome, cols)

    def test_la_riga_nuova_nasce_coi_metadati_del_video(self):
        nome = "50 Cent - Window Shopper [IX7UWaSoVv0].mp3"
        sid = APP.register_local_file(nome, APP.campi_youtube(INFO))
        r = self.riga(sid)
        self.assertEqual(r["title"], "Window Shopper")
        self.assertEqual(r["artist"], "50 Cent")
        self.assertEqual(r["local_file"], nome)
        self.assertEqual(r["yt_video_id"], "IX7UWaSoVv0")
        self.assertEqual(r["yt_upload_date"], "2025-09-15")
        self.assertEqual(r["year"], 2025)
        self.assertEqual(r["yt_channel"], "50 Cent")
        self.assertIn("Official video", r["yt_description"])
        self.assertEqual(r["yt_views"], 12345678)
        self.assertEqual(r["yt_tags"], "50 cent, hip hop, window shopper")
        self.assertEqual(r["yt_category"], "Music")
        self.assertIsNotNone(r["yt_meta_at"])

    def test_senza_metadati_e_come_prima(self):
        sid = APP.register_local_file("Artista - Titolo [dQw4w9WgXcQ].mp3")
        r = self.riga(sid)
        self.assertEqual(r["title"], "Titolo")
        self.assertIsNone(r["year"])
        self.assertIsNone(r["yt_video_id"])

    def test_l_anno_scritto_a_mano_non_si_tocca(self):
        # La riga c'è già con un anno suo (curato): l'anno di YouTube non lo
        # sovrascrive, mentre i campi `yt_*` sì (sono fatti, non scelte).
        self.scrivi("song_prova", "Window Shopper", "50 Cent", year=1999)
        sid = APP.register_local_file("50 Cent - Window Shopper [IX7UWaSoVv0].mp3",
                                      APP.campi_youtube(INFO))
        self.assertEqual(sid, "song_prova")
        r = self.riga(sid)
        self.assertEqual(r["year"], 1999)
        self.assertEqual(r["yt_upload_date"], "2025-09-15")
        self.assertEqual(r["yt_video_id"], "IX7UWaSoVv0")

    def test_la_riga_che_c_e_gia_ma_senza_anno_lo_prende(self):
        self.scrivi("song_prova", "Window Shopper", "50 Cent")
        sid = APP.register_local_file("50 Cent - Window Shopper [IX7UWaSoVv0].mp3",
                                      APP.campi_youtube(INFO))
        self.assertEqual(self.riga(sid)["year"], 2025)

    def test_un_campo_fuori_lista_non_arriva_nell_sql(self):
        # `extra` non è una scorciatoia per scrivere su una colonna qualsiasi:
        # passano solo le colonne di CAMPI_YOUTUBE e `year`.
        with APP.get_db() as conn:
            sid, _, _ = APP.resolve_or_create_song(
                conn, "Brano", "Artista",
                extra={"title": "HACK", "id": "HACK", "local_file": "HACK.mp3",
                       "yt_description": "vera", "nsomma": "x", "year": 2001})
        r = self.riga(sid)
        self.assertEqual(r["title"], "Brano")
        self.assertTrue(r["id"].startswith("song_"))
        # `local_file` resta quello che decide la funzione (vuoto): la chiave
        # "local_file" dentro `extra` non è arrivata nell'SQL.
        self.assertEqual(r["local_file"], "")
        self.assertEqual(r["yt_description"], "vera")
        self.assertEqual(r["year"], 2001)

    def test_i_valori_vuoti_non_spengono_i_dati(self):
        self.scrivi("song_prova", "Brano", "Artista", yt_description="la vecchia",
                    yt_views=10, year=2000)
        with APP.get_db() as conn:
            APP.resolve_or_create_song(conn, "Brano", "Artista",
                                       extra={"yt_description": "", "yt_channel": "",
                                              "yt_video_id": "abc"})
        r = self.riga("song_prova")
        self.assertEqual(r["yt_description"], "la vecchia")
        self.assertEqual(r["yt_views"], 10)
        self.assertEqual(r["yt_video_id"], "abc")

    def test_la_migrazione_su_un_database_vecchio(self):
        # Un database creato con lo schema di prima (senza le colonne `yt_*`):
        # `init_db` deve aggiungerle senza perdere la riga che c'è dentro.
        vecchio = os.path.join(self.tmp, "vecchio.db")
        conn = sqlite3.connect(vecchio)
        conn.execute("CREATE TABLE songs (id TEXT PRIMARY KEY, title TEXT, artist TEXT)")
        conn.execute("INSERT INTO songs(id,title,artist) VALUES('song_1','Titolo','Artista')")
        conn.commit()
        conn.close()
        APP.DB_PATH = vecchio
        APP.init_db()
        with APP.get_db() as conn:
            cols = [r["name"] for r in conn.execute("PRAGMA table_info(songs)")]
            riga = conn.execute("SELECT title FROM songs WHERE id='song_1'").fetchone()
        for nome, _ in APP.CAMPI_YOUTUBE:
            self.assertIn(nome, cols)
        self.assertEqual(riga["title"], "Titolo")


class TestGiroDellaPlaylist(unittest.TestCase):
    """`do_download_playlist` per intero, con un yt-dlp finto (nessuna rete).

    È la strada vera: la funzione legge l'info_dict della playlist, riconosce i
    file dall'`[id]` nel nome e scrive le righe. Il downloader è finto perché il
    test non deve usare la rete né toccare la libreria.
    """

    class FakeYDL:
        """Un yt-dlp che scrive due file e torna l'info_dict della playlist."""

        def __init__(self, opts):
            self.opts = opts

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def extract_info(self, url, download=True):
            voci = []
            for nome, voce in (
                ("Artista Uno - Brano Uno [aaaaaaaaaaa].mp3",
                 {"id": "aaaaaaaaaaa", "upload_date": "20250915", "channel": "Canale Uno",
                  "description": "descrizione uno", "view_count": 10}),
                ("Artista Due - Brano Due [bbbbbbbbbbb].mp3",
                 {"id": "bbbbbbbbbbb", "upload_date": "20011103", "uploader": "Canale Due",
                  "description": "descrizione due", "view_count": 20}),
            ):
                with open(os.path.join(APP.DL_DIR, nome), "wb") as f:
                    f.write(b"audio" * 4)
                voci.append(dict(voce))
            return {"title": "Playlist di prova", "entries": voci + [None]}

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="giro_playlist_prova_")
        self.db_originale, self.dl_originale, self.yt_originale = (
            APP.DB_PATH, APP.DL_DIR, APP.yt_dlp)
        APP.DB_PATH = os.path.join(self.tmp, "samplelab di prova.db")
        APP.DL_DIR = os.path.join(self.tmp, "downloads")
        os.makedirs(APP.DL_DIR, exist_ok=True)
        APP.init_db()
        APP.yt_dlp = types.SimpleNamespace(YoutubeDL=self.FakeYDL)
        self.job = {}

    def tearDown(self):
        APP.DB_PATH, APP.DL_DIR, APP.yt_dlp = (self.db_originale, self.dl_originale,
                                               self.yt_originale)
        shutil.rmtree(self.tmp, ignore_errors=True)

    def lancia(self, jid="job_di_prova"):
        APP.jobs[jid] = {"status": "pending", "progress": {}, "files": [],
                         "filename": None, "yt_title": "", "error": ""}
        APP.do_download_playlist(jid, "https://www.youtube.com/playlist?list=PLprova")
        return APP.jobs.pop(jid)

    def test_due_brani_con_i_metadati_del_video(self):
        job = self.lancia()
        self.assertEqual(job["status"], "done")
        self.assertEqual(job["playlist_title"], "Playlist di prova")
        self.assertEqual(job["count"], 2)          # la voce `None` si salta
        self.assertEqual(job["registered"], 2)
        self.assertEqual(job["con_metadati"], 2)
        self.assertEqual(job["con_anno"], 2)
        with APP.get_db() as conn:
            righe = {r["title"]: r for r in conn.execute("SELECT * FROM songs")}
        uno, due = righe["Brano Uno"], righe["Brano Due"]
        self.assertEqual(uno["artist"], "Artista Uno")
        self.assertEqual(uno["local_file"], "Artista Uno - Brano Uno [aaaaaaaaaaa].mp3")
        self.assertEqual(uno["yt_video_id"], "aaaaaaaaaaa")
        self.assertEqual(uno["yt_upload_date"], "2025-09-15")
        self.assertEqual(uno["year"], 2025)
        self.assertEqual(uno["yt_channel"], "Canale Uno")
        self.assertEqual(uno["yt_description"], "descrizione uno")
        self.assertEqual(uno["yt_views"], 10)
        self.assertEqual(due["year"], 2001)
        self.assertEqual(due["yt_channel"], "Canale Due")   # ripiego sull'uploader
        self.assertEqual(due["yt_description"], "descrizione due")

    def test_playlist_senza_data_niente_anno_ma_la_riga_si_crea(self):
        # yt-dlp può restituire voci senza `upload_date`/descrizione: le righe si
        # creano lo stesso, senza anno inventato.
        class YDLPovero(self.FakeYDL):
            def extract_info(self, url, download=True):
                nome = "Artista - Brano [ccccccccccc].mp3"
                with open(os.path.join(APP.DL_DIR, nome), "wb") as f:
                    f.write(b"audio" * 4)
                return {"title": "Senza date", "entries": [{"id": "ccccccccccc"}]}

        APP.yt_dlp = types.SimpleNamespace(YoutubeDL=YDLPovero)
        job = self.lancia("job_povero")
        self.assertEqual(job["status"], "done")
        self.assertEqual(job["registered"], 1)
        self.assertEqual(job["con_metadati"], 1)   # l'id del video c'è comunque
        self.assertEqual(job["con_anno"], 0)
        with APP.get_db() as conn:
            r = conn.execute("SELECT * FROM songs").fetchone()
        self.assertEqual(r["title"], "Brano")
        self.assertIsNone(r["year"])
        self.assertEqual(r["yt_video_id"], "ccccccccccc")


class TestCablaggio(unittest.TestCase):
    """I pezzi devono restare attaccati (letti dai sorgenti, senza app attiva)."""

    def test_la_migrazione_aggiunge_la_lista_dei_campi(self):
        src = leggi(APP_PATH)
        self.assertIn('("anteprima_file", "TEXT")', src)
        self.assertIn(") + CAMPI_YOUTUBE:", src)

    def test_ogni_colonna_e_documentata_nella_legenda(self):
        for nome, _ in APP.CAMPI_YOUTUBE:
            self.assertTrue(APP.COLUMN_DOCS["songs"].get(nome, "").strip(),
                            "colonna senza descrizione in COLUMN_DOCS: " + nome)

    def test_la_playlist_passa_i_metadati_alla_riga(self):
        src = leggi(APP_PATH)
        self.assertIn("per_id = mappa_metadati_playlist(", src)
        self.assertIn("campi = per_id.get(id_video_dal_nome_file(f)) or {}", src)
        self.assertIn("register_local_file(f, campi)", src)
        self.assertIn('jobs[job_id]["con_metadati"] = con_metadati', src)
        self.assertIn('jobs[job_id]["con_anno"] = con_anno', src)

    def test_la_pagina_lo_dice(self):
        html = leggi(PAGINA_PATH)
        self.assertIn("j.con_anno", html)
        self.assertIn("j.con_metadati", html)


class TestAppViva(unittest.TestCase):
    """Sola lettura sull'app attiva: le colonne ci sono e sono documentate."""

    def setUp(self):
        if not app_is_up(SAMPLELAB_URL):
            self.skipTest("app non attiva su " + SAMPLELAB_URL)

    def test_schema_con_le_colonne_e_i_documenti(self):
        schema = http_json("/db/schema")
        songs = next(t for t in schema["tables"] if t["name"] == "songs")
        per_nome = {c["name"]: c for c in songs["columns"]}
        for nome, tipo in APP.CAMPI_YOUTUBE:
            self.assertIn(nome, per_nome)
            self.assertEqual(per_nome[nome]["type"], tipo)
            self.assertTrue(per_nome[nome]["doc"].strip(),
                            "colonna senza descrizione nello schema: " + nome)

    def test_una_canzone_qualunque_porta_i_campi(self):
        righe = http_json("/db/songs")
        self.assertTrue(righe)
        for nome, _ in APP.CAMPI_YOUTUBE:
            self.assertIn(nome, righe[0])
