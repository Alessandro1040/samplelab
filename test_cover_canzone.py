"""Test della COPERTINA di una canzone (app (2).py + le due pagine) — 18/09/2026.

Richiesta di Alessandro: «in Modifica Info Brano e anche in database dovrebbe
comparire la possibilità di aggiungere (o modificare) la cover».

Il campo `cover_art_path` c'era da sempre (lo scrive la Verifica col nome del file
salvato in `covers/`), ma dalla pagina non si poteva mettere un'immagine: si poteva
solo scrivere a mano un nome di file. Ora, sia nel modale ✏️ Edit del Database sia
nel «Modifica Info Brano» del player, ci sono quattro strade:

- 📂 **Carica dal computer** (`POST /db/songs/<id>/cover`, multipart) → si salva
  `covers/<id>.<ext>`, una sola immagine per canzone (la vecchia di un altro
  formato va in `.trash/`);
- 🎬 **Dal video** (JSON `{"da": "youtube"}`) → la miniatura salvata col download
  della playlist (`yt_thumbnail`);
- 📁 **Copertine in `covers/`** (JSON `{"filename": …}`, elenco da `GET /covers`)
  → si usa una copertina che c'è già, senza ricopiarla;
- 🗑 **Togli** (`DELETE`) → il file va in `.trash/`, la colonna si svuota.

Cosa copre questo file:
1. le funzioni pure (`_estensione_da_nome_o_mime`, `nome_cover_archivio`) e la
   validazione VERA dei byte (`salva_copertina_bytes`: si guarda la firma del
   file, non l'estensione — un .jpg che è una pagina HTML si rifiuta);
2. la regola «una sola copertina per canzone»: cambiando formato l'immagine
   vecchia finisce nel cesto;
3. le rotte vere su database, `covers/` e `.trash/` TEMPORANEI (upload di un PNG
   fatto con ffmpeg, file che non è un'immagine, scelta di una copertina già
   presente, nome con percorso rifiutato, miniatura del video, 🗑 togli);
4. il cablaggio (sorgenti): i comandi ci sono in entrambi i modali;
5. l'app viva in sola lettura (`/covers`, `/cover/<file>` 404).

Esecuzione (dalla cartella di SampleLab):
    python3 -m unittest -v test_cover_canzone
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
import unittest
import urllib.error
import urllib.request

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
APP_PATH = os.path.join(BASE_DIR, "app (2).py")
PAGINA_PATH = os.path.join(BASE_DIR, "index (2).html")
ONYX_PATH = os.path.join(BASE_DIR, "onyx_whosampled.html")
SAMPLELAB_URL = os.environ.get("SAMPLELAB_URL", "http://localhost:5070")


def load_app():
    """Carica il modulo dell'app dal file (il nome con spazio non conta)."""
    spec = importlib.util.spec_from_file_location("samplelab_app2_cover", APP_PATH)
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
    try:
        with urllib.request.urlopen(SAMPLELAB_URL + path, timeout=20) as r:
            return r.status
    except urllib.error.HTTPError as e:
        return e.code


def png_vero(lato=2):
    """Un PNG VERO di `lato`×`lato` pixel (fatto con ffmpeg, se c'è)."""
    tmp = tempfile.mkdtemp(prefix="png_prova_")
    percorso = os.path.join(tmp, "prova.png")
    fatto = False
    if APP.FFMPEG:
        r = subprocess.run([APP.FFMPEG, "-y", "-f", "lavfi",
                            "-i", f"color=c=red:s={lato}x{lato}", "-frames:v", "1",
                            percorso], capture_output=True, timeout=60)
        fatto = r.returncode == 0 and os.path.exists(percorso)
    if not fatto:
        # PNG 1×1 trasparente valido (firma + IHDR + IDAT + IEND)
        dati = bytes.fromhex(
            "89504e470d0a1a0a0000000d494844520000000100000001080600000"
            "01f15c4890000000a49444154789c63000100000500010d0a2db40000"
            "000049454e44ae426082")
        with open(percorso, "wb") as f:
            f.write(dati)
    with open(percorso, "rb") as f:
        dati = f.read()
    shutil.rmtree(tmp, ignore_errors=True)
    return dati


class TestFunzioniDellaCopertina(unittest.TestCase):
    """Le funzioni pure e la validazione dei byte."""

    def test_estensione_da_nome_o_mime(self):
        self.assertEqual(APP._estensione_da_nome_o_mime("cover.PNG"), "png")
        self.assertEqual(APP._estensione_da_nome_o_mime("foto.jpeg"), "jpg")
        self.assertEqual(APP._estensione_da_nome_o_mime("x.webp"), "webp")
        self.assertEqual(APP._estensione_da_nome_o_mime("strano.txt"), "jpg")
        self.assertEqual(APP._estensione_da_nome_o_mime("", "image/gif"), "gif")
        self.assertEqual(APP._estensione_da_nome_o_mime("", "image/webp"), "webp")
        self.assertEqual(APP._estensione_da_nome_o_mime("", "text/plain"), "jpg")

    def test_nome_cover_archivio(self):
        self.assertTrue(APP.nome_cover_archivio("song_abc123.jpg"))
        self.assertTrue(APP.nome_cover_archivio("cover.PNG"))
        self.assertFalse(APP.nome_cover_archivio(""))
        self.assertFalse(APP.nome_cover_archivio("brano.mp3"))
        # Un percorso non è un nome di copertina (niente uscite da covers/).
        self.assertFalse(APP.nome_cover_archivio("../song_abc.jpg"))
        self.assertFalse(APP.nome_cover_archivio("/tmp/song_abc.jpg"))

    def test_i_byte_devono_essere_un_immagine(self):
        # Un .jpg che in realtà è una pagina HTML (capita scaricando dal web) si
        # rifiuta: si guarda la FIRMA del file, non il nome.
        nome, errore = APP.salva_copertina_bytes("song_prova", b"<html>niente</html>", "jpg")
        self.assertEqual(nome, "")
        self.assertIn("non è un'immagine", errore)
        self.assertEqual(APP.salva_copertina_bytes("song_prova", b"", "jpg")[0], "")


class BaseCover(unittest.TestCase):
    """Database, `covers/` e `.trash/` TEMPORANEI (la libreria non si tocca)."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="cover_canzone_prova_")
        self.orig = (APP.DB_PATH, APP.COVERS_DIR, APP.TRASH_DIR, APP._scarica_immagine)
        APP.DB_PATH = os.path.join(self.tmp, "samplelab di prova.db")
        APP.COVERS_DIR = os.path.join(self.tmp, "covers")
        APP.TRASH_DIR = os.path.join(self.tmp, ".trash")
        for cartella in (APP.COVERS_DIR, APP.TRASH_DIR):
            os.makedirs(cartella, exist_ok=True)
        APP.init_db()
        self.client = APP.app.test_client()

    def tearDown(self):
        (APP.DB_PATH, APP.COVERS_DIR, APP.TRASH_DIR, APP._scarica_immagine) = self.orig
        shutil.rmtree(self.tmp, ignore_errors=True)

    def crea_riga(self, sid="song_prova", titolo="Brano Di Prova", artista="Artista Di Prova",
                  **campi):
        with APP.get_db() as conn:
            colonne = ["id", "title", "artist"] + list(campi)
            conn.execute("INSERT INTO songs(" + ", ".join(colonne) + ") VALUES(" +
                         ", ".join(["?"] * len(colonne)) + ")",
                         [sid, titolo, artista] + list(campi.values()))
        return sid

    def riga(self, sid):
        with APP.get_db() as conn:
            return conn.execute("SELECT * FROM songs WHERE id=?", (sid,)).fetchone()

    def copertine(self):
        return sorted(os.listdir(APP.COVERS_DIR))


class TestCopertinaCaricata(BaseCover):
    """📂 Carica dal computer e 🗑 Togli."""

    def test_una_copertina_nuova(self):
        sid = self.crea_riga()
        res = self.client.post(f"/db/songs/{sid}/cover",
                               data={"file": (io.BytesIO(png_vero()), "La Mia Cover.PNG")},
                               content_type="multipart/form-data")
        self.assertEqual(res.status_code, 200)
        corpo = res.get_json()
        self.assertEqual(corpo["origine"], "caricata dal computer")
        self.assertEqual(corpo["cover_art_path"], f"{sid}.png")
        self.assertEqual(self.riga(sid)["cover_art_path"], f"{sid}.png")
        self.assertEqual(self.copertine(), [f"{sid}.png"])
        self.assertTrue(os.path.getsize(os.path.join(APP.COVERS_DIR, f"{sid}.png")) > 20)

    def test_un_file_che_non_e_un_immagine_si_rifiuta(self):
        sid = self.crea_riga()
        res = self.client.post(f"/db/songs/{sid}/cover",
                               data={"file": (io.BytesIO(b"<html>no</html>"), "finta.jpg")},
                               content_type="multipart/form-data")
        self.assertEqual(res.status_code, 400)
        self.assertIn("non è un'immagine", res.get_json()["error"])
        self.assertIsNone(self.riga(sid)["cover_art_path"])
        self.assertEqual(self.copertine(), [])

    def test_un_secondo_upload_non_lascia_file_orfani(self):
        # Una sola immagine per canzone (lo stesso nome si sovrascrive).
        sid = self.crea_riga()
        for _ in range(2):
            self.client.post(f"/db/songs/{sid}/cover",
                             data={"file": (io.BytesIO(png_vero()), "cover.png")},
                             content_type="multipart/form-data")
        self.assertEqual(self.copertine(), [f"{sid}.png"])
        self.assertEqual(self.riga(sid)["cover_art_path"], f"{sid}.png")

    def test_canzone_inesistente(self):
        res = self.client.post("/db/songs/song_fantasma/cover",
                               data={"file": (io.BytesIO(png_vero()), "x.png")},
                               content_type="multipart/form-data")
        self.assertEqual(res.status_code, 404)

    def test_togliere_la_copertina_la_manda_nel_cesto(self):
        sid = self.crea_riga(cover_art_path="song_prova.png")
        with open(os.path.join(APP.COVERS_DIR, "song_prova.png"), "wb") as f:
            f.write(png_vero())
        res = self.client.delete(f"/db/songs/{sid}/cover")
        self.assertEqual(res.status_code, 200)
        self.assertIsNone(self.riga(sid)["cover_art_path"])
        self.assertEqual(self.copertine(), [])
        self.assertTrue(os.path.exists(os.path.join(APP.TRASH_DIR, "song_prova.png")))

    def test_togliere_una_copertina_che_non_c_e(self):
        sid = self.crea_riga()
        self.assertEqual(self.client.delete(f"/db/songs/{sid}/cover").status_code, 200)
        self.assertEqual(self.client.delete("/db/songs/song_fantasma/cover").status_code, 404)

    def test_togliere_la_copertina_di_un_altra_canzone_non_tocca_il_file(self):
        # Una riga può usare una copertina che c'è già (magari di un'altra canzone):
        # togliendola si svuota solo il campo, il file NON va nel cesto (18/09/2026:
        # la prova dal vivo aveva mandato nel cesto la copertina di un'altra canzone).
        sid = self.crea_riga(cover_art_path="song_altra.jpg")
        with open(os.path.join(APP.COVERS_DIR, "song_altra.jpg"), "wb") as f:
            f.write(png_vero())
        res = self.client.delete(f"/db/songs/{sid}/cover")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.get_json()["file_lasciato"], "song_altra.jpg")
        self.assertEqual(res.get_json()["spostato_in"], "")
        self.assertIsNone(self.riga(sid)["cover_art_path"])
        self.assertEqual(self.copertine(), ["song_altra.jpg"])       # il file resta
        self.assertEqual(os.listdir(APP.TRASH_DIR), [])              # niente nel cesto


class TestCopertinaScegliEVideo(BaseCover):
    """📁 Una copertina già in `covers/` · 🎬 la miniatura del video."""

    def test_scegliere_una_copertina_gia_presente(self):
        sid = self.crea_riga()
        with open(os.path.join(APP.COVERS_DIR, "song_altra.jpg"), "wb") as f:
            f.write(png_vero())
        res = self.client.post(f"/db/songs/{sid}/cover", json={"filename": "song_altra.jpg"})
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.get_json()["origine"], "scelta fra le copertine dell'app")
        self.assertEqual(self.riga(sid)["cover_art_path"], "song_altra.jpg")
        # non si copia niente: si usa il file che c'è già
        self.assertEqual(self.copertine(), ["song_altra.jpg"])

    def test_nome_non_valido_o_file_inesistente(self):
        sid = self.crea_riga()
        with open(os.path.join(self.tmp, "fuori.png"), "wb") as f:
            f.write(png_vero())
        self.assertEqual(
            self.client.post(f"/db/songs/{sid}/cover",
                             json={"filename": "../fuori.png"}).status_code, 400)
        self.assertEqual(
            self.client.post(f"/db/songs/{sid}/cover",
                             json={"filename": "non-c-e.png"}).status_code, 404)
        self.assertEqual(self.client.post(f"/db/songs/{sid}/cover", json={}).status_code, 400)

    def test_dalla_miniatura_del_video(self):
        sid = self.crea_riga(yt_thumbnail="https://i.ytimg.com/vi/abc/maxresdefault.jpg")
        APP._scarica_immagine = lambda url, timeout=20: png_vero()   # niente rete
        res = self.client.post(f"/db/songs/{sid}/cover", json={"da": "youtube"})
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.get_json()["origine"], "miniatura del video YouTube")
        self.assertEqual(res.get_json()["cover_art_path"], f"{sid}.jpg")   # ext dall'URL
        self.assertEqual(self.riga(sid)["cover_art_path"], f"{sid}.jpg")

    def test_senza_miniatura_lo_dice(self):
        sid = self.crea_riga()
        res = self.client.post(f"/db/songs/{sid}/cover", json={"da": "youtube"})
        self.assertEqual(res.status_code, 400)
        self.assertIn("miniatura del video", res.get_json()["error"])

    def test_se_la_miniatura_non_si_scarica(self):
        sid = self.crea_riga(yt_thumbnail="https://i.ytimg.com/vi/abc/x.jpg")
        APP._scarica_immagine = lambda url, timeout=20: b""
        res = self.client.post(f"/db/songs/{sid}/cover", json={"da": "youtube"})
        self.assertEqual(res.status_code, 502)

    def test_elenco_delle_copertine(self):
        for nome in ("song_a.jpg", "song_b.png", "non-immagine.txt"):
            with open(os.path.join(APP.COVERS_DIR, nome), "wb") as f:
                f.write(png_vero() if nome != "non-immagine.txt" else b"x")
        elenco = self.client.get("/covers").get_json()
        self.assertEqual([v["name"] for v in elenco], ["song_a.jpg", "song_b.png"])


class TestCablaggio(unittest.TestCase):
    """I comandi devono stare in ENTRAMBI i modali (letti dai sorgenti)."""

    def test_le_rotte_ci_sono(self):
        src = leggi(APP_PATH)
        for pezzo in ('@app.route("/covers")',
                      '@app.route("/db/songs/<song_id>/cover", methods=["POST"])',
                      '@app.route("/db/songs/<song_id>/cover", methods=["DELETE"])'):
            self.assertIn(pezzo, src, "manca la rotta: " + pezzo)

    def test_la_pagina_principale_ha_i_comandi(self):
        html = leggi(PAGINA_PATH)
        self.assertIn("function coverControlsHTML(song)", html)
        self.assertIn("${coverControlsHTML(s)}", html)          # nel modale ✏️ Edit
        self.assertIn("caricaCoverArchivio()", html)
        self.assertIn("coverDalComputer(this.files)", html)     # 📂
        self.assertIn("coverDaYoutube()", html)                 # 🎬
        self.assertIn("coverDaArchivio(this.value)", html)      # 📁
        self.assertIn("togliCover()", html)                     # 🗑
        self.assertIn("coverSongId=id;", html)                  # il modale sa la canzone
        # il campo resta dichiarato come prima (le tre liste dei modali non cambiano)
        self.assertIn("inp('cover_art_path'", html)

    def test_il_modale_del_player_ha_i_comandi(self):
        onyx = leggi(ONYX_PATH)
        self.assertIn("f === 'cover_art_path'", onyx)
        self.assertIn("coverControlsHTML(song)", onyx)
        self.assertIn("coverDalComputer(this.files)", onyx)
        self.assertIn("coverDaYoutube()", onyx)
        self.assertIn("coverDaArchivio(this.value)", onyx)
        self.assertIn("togliCover()", onyx)
        # gli id dei comandi NON iniziano con `editdb-`: quelli sono i campi del
        # PUT, e il test dei modali li conta (devono restare 27)
        self.assertIn('id="coverfile-upload"', onyx)
        self.assertNotIn('id="editdb-cover-', onyx)


class TestAppViva(unittest.TestCase):
    """Sola lettura sull'app attiva: l'elenco delle copertine risponde."""

    def setUp(self):
        if not app_is_up(SAMPLELAB_URL):
            self.skipTest("app non attiva su " + SAMPLELAB_URL)

    def test_elenco_copertine(self):
        elenco = http_json("/covers")
        self.assertIsInstance(elenco, list)
        for voce in elenco:
            self.assertTrue(APP.nome_cover_archivio(voce["name"]), voce["name"])

    def test_copertina_che_non_c_e_da_404(self):
        self.assertEqual(http_stato("/cover/non-esiste-questa.jpg"), 404)

