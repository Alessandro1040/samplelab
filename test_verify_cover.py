"""Test delle copertine (cover art) della Verifica — 18/09/2026.

Richiesta di Alessandro: «quando clicchi su verifica dovrebbe trovare anche
l'immagine (cover) di ogni canzone». La colonna `songs.cover_art_path` era
**vuota su tutte le 890 canzoni**: la Verifica trovava titolo, album, BPM,
tonalità e testo, ma nessuna immagine.

Ora la Verifica:
1. prende la copertina da Genius (la search API dà la miniatura, l'API della
   singola canzone `song_art_image_url`, quadrata ~1000 px);
2. se Genius non ha l'immagine, la prende dal file audio (APIC/covr/pictures);
3. salva il file in `covers/` e scrive nel database il NOME del file
   (`<id>.<ext>`, es. 'song_7553a924d202.jpg') — non l'URL, che scade;
4. la pagina la serve da `/cover/<file>`: miniatura nella tabella del database,
   anteprima nell'editor e immagine dell'hero nella scheda.

Esecuzione (dalla cartella di SampleLab):
    python3 -m unittest -v test_verify_cover

I test di rete (Genius) e quelli HTTP (rotta `/cover` sull'app viva) si saltano
da soli se Genius/l'app non ci sono; `SAMPLELAB_URL` sovrascrive l'indirizzo.
"""
import importlib.util
import json
import os
import shutil
import struct
import tempfile
import unittest
import urllib.error
import urllib.parse
import urllib.request
import zlib
from unittest import mock

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
APP_PATH = os.path.join(BASE_DIR, "app (2).py")
INDEX_PATH = os.path.join(BASE_DIR, "index (2).html")
SCHEDA_PATH = os.path.join(BASE_DIR, "scheda.html")
DL_DIR = os.path.join(BASE_DIR, "downloads")
SAMPLELAB_URL = os.environ.get("SAMPLELAB_URL", "http://localhost:5070")


def load_app():
    """Carica il modulo dell'app dal file (il nome con spazio non conta).
    L'import NON avvia il server e non tocca il database."""
    spec = importlib.util.spec_from_file_location("samplelab_app2_cover", APP_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


APP = load_app()


def leggi(path):
    with open(path, encoding="utf-8") as fh:
        return fh.read()


def app_is_up(url):
    try:
        urllib.request.urlopen(url + "/db/stats", timeout=3)
        return True
    except Exception:
        return False


def png_finto():
    """PNG 1x1 valido (firma + chunk veri): prova i controlli di formato e
    fabbrica una copertina per i test senza scaricare niente."""
    def chunk(tipo, dati):
        corpo = tipo + dati
        return (struct.pack(">I", len(dati)) + corpo
                + struct.pack(">I", zlib.crc32(corpo) & 0xffffffff))
    ihdr = struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0)
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr)
            + chunk(b"IDAT", zlib.compress(b"\x00\xff\x00\x00")) + chunk(b"IEND", b""))


class TestNomeFile(unittest.TestCase):
    """Il file di copertina si chiama come l'id della canzone: si trova subito
    in `covers/` e non si confonde con le altre."""

    def test_estensione_dallurl(self):
        self.assertEqual(APP._cover_ext_from_url("https://images.genius.com/a.jpg"), "jpg")
        self.assertEqual(APP._cover_ext_from_url("https://images.genius.com/a.1000x1000x1.png"), "png")
        self.assertEqual(APP._cover_ext_from_url("https://images.genius.com/a.webp?v=2"), "webp")

    def test_estensione_ripiego(self):
        # URL senza formato dichiarato (o con parametri strani) → jpg
        for url in ("https://images.genius.com/senza-estensione", "", None,
                    "https://images.genius.com/a.xyz", "https://images.genius.com/x.jpeg"):
            with self.subTest(url=url):
                self.assertEqual(APP._cover_ext_from_url(url), "jpg")

    def test_nome_dallid_del_database(self):
        self.assertEqual(APP._cover_filename("song_7553a924d202", "https://i.genius.com/x.jpg"),
                         "song_7553a924d202.jpg")
        self.assertEqual(APP._cover_filename("song_7553a924d202", "https://i.genius.com/x.png?v=1"),
                         "song_7553a924d202.png")

    def test_nome_con_id_sporco(self):
        # l'id finisce in un percorso: via separatori e punti
        self.assertEqual(APP._cover_filename("song/3../x", "https://i.genius.com/y.webp"),
                         "song3x.webp")
        self.assertEqual(APP._cover_filename("", "https://i.genius.com/y.jpg"), "cover.jpg")

    def test_percorso_solo_dentro_covers(self):
        self.assertEqual(os.path.dirname(APP._cover_local_path("song_1.jpg")), APP.COVERS_DIR)
        # un nome con percorso non esce dalla cartella
        self.assertEqual(os.path.dirname(APP._cover_local_path("../../etc/passwd")), APP.COVERS_DIR)
        self.assertEqual(APP._cover_local_path(""), "")

    def test_content_type(self):
        self.assertEqual(APP._cover_mime("song_1.jpg"), "image/jpeg")
        self.assertEqual(APP._cover_mime("song_1.png"), "image/png")
        self.assertEqual(APP._cover_mime("song_1.webp"), "image/webp")
        self.assertEqual(APP._cover_mime("song_1.gif"), "image/gif")
        self.assertEqual(APP._cover_mime("song_1.strano"), "image/jpeg")


class TestFirmaImmagine(unittest.TestCase):
    """Prima di salvare si controlla la FIRMA del file: Genius a volte risponde
    con una pagina HTML (blocco/errore) e senza questo controllo salveremmo un
    '.jpg' che immagine non è."""

    def test_formati_veri(self):
        self.assertTrue(APP._looks_like_image(b"\xff\xd8\xff\xe0" + b"0" * 20))
        self.assertTrue(APP._looks_like_image(png_finto()))
        self.assertTrue(APP._looks_like_image(b"GIF89a" + b"0" * 20))
        self.assertTrue(APP._looks_like_image(b"RIFF\x00\x00\x00\x00WEBP" + b"0" * 10))
        self.assertTrue(APP._looks_like_image(b"BM" + b"0" * 20))

    def test_non_immagini(self):
        for data in (b"", None, b"<!DOCTYPE html><html><body>errore</body></html>",
                     b"<html><head><title>Genius</title>", b"0" * 40, b"\x00" * 40):
            with self.subTest(data=(data or b"")[:20]):
                self.assertFalse(APP._looks_like_image(data))

    def test_png_finto_e_valido(self):
        # il PNG dei test deve avere la firma giusta, altrimenti i test mentono
        self.assertTrue(png_finto().startswith(b"\x89PNG\r\n\x1a\n"))
        self.assertGreater(len(png_finto()), 50)


class TestUrlGenius(unittest.TestCase):
    """Quale immagine si sceglie: prima quella quadrata grande della canzone,
    poi la miniatura della ricerca. Misurato il 18/09/2026: la search API dà
    immagini da ~200 px che nella scheda sgranano."""

    def test_preferisce_limmagine_grande_della_canzone(self):
        url = APP._genius_cover_url(
            {"header_image_thumbnail_url": "https://images.genius.com/piccola.200x200x1.jpg"},
            {"song_art_image_url": "https://images.genius.com/grande.1000x1000x1.jpg"})
        self.assertEqual(url, "https://images.genius.com/grande.1000x1000x1.jpg")

    def test_ripiego_sulla_miniatura_della_ricerca(self):
        self.assertEqual(
            APP._genius_cover_url({"header_image_thumbnail_url": "https://images.genius.com/p.200x200x1.jpg"}),
            "https://images.genius.com/p.200x200x1.jpg")

    def test_ripiego_su_header_image_url(self):
        self.assertEqual(
            APP._genius_cover_url({}, {"header_image_url": "https://images.genius.com/h.jpg"}),
            "https://images.genius.com/h.jpg")

    def test_nessun_url(self):
        for res, sdata in ((None, None), ({}, {}), ({}, {"song_art_image_url": ""}),
                           ({"header_image_thumbnail_url": "non-un-url"}, {})):
            with self.subTest(res=res, sdata=sdata):
                self.assertEqual(APP._genius_cover_url(res, sdata), "")


class TestCoverMancante(unittest.TestCase):
    """`covers/` non è versionata (le immagini pesano): su un altro Mac il nome
    nel database c'è ma il file no, e in quel caso la Verifica la riscarica."""

    def test_campo_vuoto_o_file_assente(self):
        self.assertTrue(APP._cover_mancante(""))
        self.assertTrue(APP._cover_mancante(None))
        self.assertTrue(APP._cover_mancante("non-esiste-davvero.jpg"))

    def test_file_presente(self):
        tmp = tempfile.mkdtemp()
        try:
            with open(os.path.join(tmp, "song_1.png"), "wb") as fh:
                fh.write(png_finto())
            with mock.patch.object(APP, "COVERS_DIR", tmp):
                self.assertFalse(APP._cover_mancante("song_1.png"))
                self.assertTrue(APP._cover_mancante("song_2.png"))
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


@unittest.skipUnless(APP.HAS_MUTAGEN, "mutagen non installato")
class TestTagAudio(unittest.TestCase):
    """Ripiego: la copertina incorporata nel file audio. Si lavora su una COPIA
    di un mp3 vero in una cartella temporanea (i downloads non si toccano)."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.mp3 = None
        try:
            for nome in sorted(os.listdir(DL_DIR)):
                sorgente = os.path.join(DL_DIR, nome)
                if nome.lower().endswith(".mp3") and os.path.getsize(sorgente) > 20000:
                    self.mp3 = os.path.join(self.tmp, "brano.mp3")
                    shutil.copyfile(sorgente, self.mp3)
                    break
        except OSError:
            pass

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_copertina_incorporata(self):
        if not self.mp3:
            self.skipTest("nessun mp3 in downloads/ con cui fabbricare la copertina")
        from mutagen.id3 import ID3, APIC, ID3NoHeaderError
        try:
            tag = ID3(self.mp3)
        except ID3NoHeaderError:
            tag = ID3()
        tag.add(APIC(encoding=3, mime="image/png", type=3, desc="cover", data=png_finto()))
        tag.save(self.mp3)
        dati, ext = APP._cover_da_tag_audio(self.mp3)
        self.assertEqual(ext, "png")
        self.assertEqual(dati, png_finto())

    def test_senza_copertina_ritorna_vuoto(self):
        if not self.mp3:
            self.skipTest("nessun mp3 in downloads/")
        from mutagen.id3 import ID3
        try:
            ID3.delete(self.mp3)
        except Exception:
            pass
        self.assertEqual(APP._cover_da_tag_audio(self.mp3), (b"", ""))

    def test_file_inesistente(self):
        self.assertEqual(APP._cover_da_tag_audio(os.path.join(self.tmp, "niente.mp3")), (b"", ""))
        self.assertEqual(APP._cover_da_tag_audio(""), (b"", ""))

    def test_salva_copertina_dal_tag_del_file(self):
        """Genius senza immagine (o brano che Genius non conosce): la copertina
        arriva dal tag del file audio, e il nome è quello dell'id."""
        if not self.mp3:
            self.skipTest("nessun mp3 in downloads/")
        from mutagen.id3 import ID3, APIC, ID3NoHeaderError
        try:
            tag = ID3(self.mp3)
        except ID3NoHeaderError:
            tag = ID3()
        tag.add(APIC(encoding=3, mime="image/png", type=3, desc="cover", data=png_finto()))
        tag.save(self.mp3)
        with mock.patch.object(APP, "COVERS_DIR", self.tmp):
            nome, msg = APP._salva_copertina("song_da_tag", "", self.mp3)
            self.assertEqual(nome, "song_da_tag.png")
            self.assertFalse(APP._cover_mancante(nome))
        self.assertIn("tag del file audio", msg)
        with open(os.path.join(self.tmp, "song_da_tag.png"), "rb") as fh:
            self.assertEqual(fh.read(), png_finto())


class TestSalvaCopertina(unittest.TestCase):
    """Il salvataggio: un solo file per canzone e nessun file fantasma."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_una_sola_immagine_per_canzone(self):
        # il formato può cambiare da una verifica all'altra (jpg → png): il file
        # vecchio viene rimosso, non resta orfano in covers/
        with open(os.path.join(self.tmp, "song_9.jpg"), "wb") as fh:
            fh.write(b"vecchia-copertina")
        with mock.patch.object(APP, "COVERS_DIR", self.tmp), \
             mock.patch.object(APP, "_scarica_immagine", lambda *a, **k: png_finto()):
            nome, msg = APP._salva_copertina("song_9", "https://images.genius.com/n.png", "")
        self.assertEqual(nome, "song_9.png")
        self.assertIn("Genius", msg)
        self.assertIn("song_9.png", os.listdir(self.tmp))
        self.assertNotIn("song_9.jpg", os.listdir(self.tmp))
        # ...e non tocca le copertine delle altre canzoni
        self.assertTrue(all(f != "song_9.jpg" for f in os.listdir(self.tmp)))

    def test_copertina_non_trovata(self):
        with mock.patch.object(APP, "COVERS_DIR", self.tmp), \
             mock.patch.object(APP, "_scarica_immagine", lambda *a, **k: b""):
            nome, msg = APP._salva_copertina("song_x", "https://images.genius.com/a.jpg", "")
        self.assertIsNone(nome)
        self.assertIn("Copertina non trovata", msg)
        self.assertEqual(os.listdir(self.tmp), [])

    def test_url_vuoto_e_senza_file_audio(self):
        with mock.patch.object(APP, "COVERS_DIR", self.tmp):
            nome, msg = APP._salva_copertina("song_x", "", "")
        self.assertIsNone(nome)
        self.assertIn("⚠️", msg)


class TestRottaCopertina(unittest.TestCase):
    """`/cover/<file>`: è la rotta con cui la pagina mostra la copertina."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.patch = mock.patch.object(APP, "COVERS_DIR", self.tmp)
        self.patch.start()
        self.client = APP.app.test_client()

    def tearDown(self):
        self.patch.stop()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_serve_limmagine(self):
        with open(os.path.join(self.tmp, "song_42.png"), "wb") as fh:
            fh.write(png_finto())
        r = self.client.get("/cover/song_42.png")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.headers.get("Content-Type"), "image/png")
        self.assertEqual(r.data, png_finto())

    def test_404_se_il_file_non_ce(self):
        r = self.client.get("/cover/non-esiste.jpg")
        self.assertEqual(r.status_code, 404)
        self.assertIn("Copertina non trovata", r.get_data(as_text=True))

    def test_il_percorso_non_esce_dalla_cartella(self):
        # un nome con '..' viene ridotto al nome del file: si cerca comunque
        # dentro covers/, non nel resto del disco
        r = self.client.get("/cover/..%2F..%2Fapp%20(2).py")
        self.assertEqual(r.status_code, 404)


class TestDownloadReale(unittest.TestCase):
    """Prova vera di rete: la copertina di *TILL I COLLAPSE* (Eminem) da Genius,
    salvata in una cartella temporanea (le covers/ del progetto non si toccano).
    Si salta da solo se Genius non risponde."""

    def test_copertina_da_genius(self):
        try:
            g = APP.fetch_genius("Eminem", "Till I Collapse")
        except Exception as e:
            self.skipTest("Genius non raggiungibile: %s" % e)
        if not g or not g.get("cover_art"):
            self.skipTest("Genius non ha dato la copertina (risposta vuota/429)")
        url = g["cover_art"]
        self.assertIn("genius", url.lower())
        tmp = tempfile.mkdtemp()
        try:
            with mock.patch.object(APP, "COVERS_DIR", tmp):
                nome, msg = APP._salva_copertina("song_reale", url, "")
                self.assertIsNotNone(nome, msg)
                self.assertTrue(nome.startswith("song_reale."))
                percorso = os.path.join(tmp, nome)
                self.assertTrue(os.path.exists(percorso), msg)
                with open(percorso, "rb") as fh:
                    dati = fh.read()
                self.assertTrue(APP._looks_like_image(dati))
                self.assertGreater(len(dati), 3000)
                self.assertFalse(APP._cover_mancante(nome))
                self.assertIn("Genius", msg)
                print("[cover] %s · %d byte · %s" % (nome, len(dati), url))
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


class TestCablaggio(unittest.TestCase):
    """Pagina e backend devono restare d'accordo: se cambia un nome di funzione
    o un pezzo di markup, qui se ne accorge subito."""

    @classmethod
    def setUpClass(cls):
        cls.index = leggi(INDEX_PATH)
        cls.scheda = leggi(SCHEDA_PATH)
        cls.app = leggi(APP_PATH)

    def test_helper_della_pagina(self):
        self.assertIn("function coverUrl(f){ return f ? '/cover/' + encodeURIComponent(f) : ''; }", self.index)
        self.assertIn("function coverThumb(f, size){", self.index)
        self.assertIn(".db-cover{width:26px;height:26px", self.index)

    def test_miniatura_nella_tabella_e_nelleditor(self):
        # riga della tabella: miniatura accanto al titolo
        self.assertIn("${coverThumb(s.cover_art_path, 26)}", self.index)
        # feedback della Verifica: la cover appena trovata si vede subito
        self.assertIn("${coverThumb(song.cover_art_path, 54)}", self.index)
        # editor ✏️: anteprima accanto al campo «Cover path»
        self.assertIn("${coverThumb(v('cover_art_path'),72)}", self.index)

    def test_scheda_usa_la_copertina_nellhero(self):
        self.assertIn("const arte = s.cover_art_path ? '/cover/' + encodeURIComponent(s.cover_art_path) : '';", self.scheda)
        self.assertIn("${artoHTML}", self.scheda)

    def test_backend(self):
        self.assertIn('@app.route("/cover/<path:filename>")', self.app)
        self.assertIn("def cover_file(filename):", self.app)
        self.assertIn('COVERS_DIR = os.path.join(BASE_DIR, "covers")', self.app)
        # la Verifica riempie la colonna solo se il file non c'è già
        self.assertIn('if _cover_mancante(s.get("cover_art_path")):', self.app)
        self.assertIn('updates["cover_art_path"] = nome_cover', self.app)
        self.assertIn('_set_verify_status(song_id, 2, 6, "Recupero copertina da Genius…")', self.app)

    def test_cover_escluse_dal_versionamento(self):
        # le immagini non vanno in repo (una per canzone): covers/ in .gitignore
        self.assertIn("covers/", leggi(os.path.join(BASE_DIR, ".gitignore")))


@unittest.skipUnless(app_is_up(SAMPLELAB_URL), "app non attiva su " + SAMPLELAB_URL)
class TestEndpointVivo(unittest.TestCase):
    """Sull'app VERA, in sola lettura: la rotta risponde, la tabella ha il campo
    e la pagina servita contiene gli agganci delle miniature."""

    def test_rotta_404_su_file_inesistente(self):
        try:
            urllib.request.urlopen(SAMPLELAB_URL + "/cover/questa-non-esiste-mai.jpg", timeout=20)
            self.fail("la rotta /cover doveva rispondere 404")
        except urllib.error.HTTPError as e:
            self.assertEqual(e.code, 404)

    def test_elenco_canzoni_ha_il_campo_cover(self):
        with urllib.request.urlopen(SAMPLELAB_URL + "/db/songs", timeout=60) as r:
            brani = json.load(r)
        self.assertTrue(brani, "database vuoto")
        self.assertIn("cover_art_path", brani[0])

    def test_copertina_di_una_canzone_che_ce_lha(self):
        with urllib.request.urlopen(SAMPLELAB_URL + "/db/songs", timeout=60) as r:
            brani = json.load(r)
        for s in brani:
            nome = s.get("cover_art_path")
            if nome and os.path.exists(os.path.join(APP.COVERS_DIR, nome)):
                with urllib.request.urlopen(
                        SAMPLELAB_URL + "/cover/" + urllib.parse.quote(nome), timeout=20) as r:
                    self.assertEqual(r.status, 200)
                    self.assertTrue(str(r.headers.get("Content-Type", "")).startswith("image/"))
                    self.assertGreater(len(r.read()), 1000)
                return
        self.skipTest("nessuna canzone ha ancora la copertina su disco")

    def test_pagina_con_gli_agganci_delle_copertine(self):
        with urllib.request.urlopen(SAMPLELAB_URL + "/", timeout=30) as r:
            pagina = r.read().decode("utf-8", "replace")
        self.assertIn("function coverThumb(f, size){", pagina)
        self.assertIn("/cover/' + encodeURIComponent(f)", pagina)


if __name__ == "__main__":
    unittest.main(verbosity=2)
