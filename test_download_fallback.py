"""Test del recupero dei download di SampleLab (app (2).py).

Bug del 16/09/2026 (osservato in pagina): cercando "Till I Collapse" di Eminem,
il sample **"Sam Is Dead"** veniva elencato correttamente ma riproduceva l'audio
del sample **"Mosh"**. Causa: in `_do_download` il fallback, quando un download
non produceva file, restituiva *l'ultimo file della cartella download modificato
negli ultimi 60 secondi* — con i sample scaricati in parallelo era il file di un
ALTRO job. (Il video di "Sam Is Dead" è davvero non scaricabile: yt-dlp risponde
"Please sign in".) Fix: si accettano solo file creati DA QUESTO job, il titolo
atteso deve comparire nel nome, e se non c'è nulla il job va in **errore**
invece di consegnare un audio sbagliato. In più il ranking YouTube ora preferisce
la versione completa (niente clip di 30 s quando esiste il brano intero).

Test "puri" (nessuna rete, nessun database) più un test HTTP che riproduce il
caso quando l'app è attiva.

Esecuzione (dalla cartella di SampleLab):
    python3 -m unittest -v test_download_fallback
Il test HTTP gira solo se l'app è attiva (default http://localhost:5070,
sovrascrivibile con la variabile SAMPLELAB_URL).
"""
import importlib.util
import json
import os
import tempfile
import time
import unittest
import urllib.request

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
APP_PATH = os.path.join(BASE_DIR, "app (2).py")
SAMPLELAB_URL = os.environ.get("SAMPLELAB_URL", "http://localhost:5070")


def load_app():
    """Carica il modulo dell'app dal file (il nome con spazio non conta).

    Non avvia il server e non tocca il database: `init_db()` e `serve()` stanno
    sotto `if __name__ == "__main__"`."""
    spec = importlib.util.spec_from_file_location("samplelab_app", APP_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


APP = load_app()


def app_is_up(url):
    try:
        urllib.request.urlopen(url + "/db/stats", timeout=3)
        return True
    except Exception:
        return False


class TestPickJobFile(unittest.TestCase):
    """`_pick_job_file`: si consegnano solo i file creati da questo job."""

    def test_file_di_un_altro_job_non_viene_usato(self):
        # "Mosh.mp3" esisteva già prima del job: il job non ha prodotto nulla,
        # quindi nessun file (in pagina compare l'errore) e non l'audio di Mosh.
        before = {"Mosh.mp3": (100.0, 1000)}
        after = {"Mosh.mp3": (100.0, 1000)}
        self.assertIsNone(APP._pick_job_file(before, after))

    def test_file_creato_dal_job_viene_usato(self):
        before = {"Mosh.mp3": (100.0, 1000)}
        after = {"Mosh.mp3": (100.0, 1000), "Sam Is Dead.mp3": (200.0, 2000)}
        self.assertEqual(APP._pick_job_file(before, after), "Sam Is Dead.mp3")

    def test_file_modificato_dal_job_viene_usato(self):
        # Stesso nome di prima ma contenuto nuovo (riscaricato da questo job).
        before = {"Eminem - Mosh.m4a": (100.0, 1000)}
        after = {"Eminem - Mosh.m4a": (200.0, 2222)}
        self.assertEqual(APP._pick_job_file(before, after), "Eminem - Mosh.m4a")

    def test_titolo_atteso_scarta_il_file_altrui(self):
        # Un altro job ha scritto "Mosh.mp3" mentre questo scaricava "Sam Is Dead":
        # meglio nessun file che l'audio del brano sbagliato.
        before = {}
        after = {"Mosh.mp3": (200.0, 2000)}
        self.assertIsNone(APP._pick_job_file(before, after, expected_title="Sam Is Dead"))

    def test_titolo_atteso_trova_il_file_giusto(self):
        before = {}
        after = {"Mosh.mp3": (200.0, 2000),
                 "Tyler, The Creator - Sam Is Dead.mp3": (190.0, 1900)}
        self.assertEqual(APP._pick_job_file(before, after, expected_title="Sam Is Dead"),
                         "Tyler, The Creator - Sam Is Dead.mp3")

    def test_titolo_atteso_molto_diverso_dal_nome_file(self):
        # Limite noto e voluto: il nome del file deve contenere il titolo atteso.
        # Se non lo contiene (qui il sample "'Til I Collapse Freestyle" è stato
        # pubblicato come "50 Cent - Collapse (Freestyle)") NON si consegna nulla:
        # l'utente vede l'errore e può aggiungere il sample a mano con un altro URL.
        before = {}
        after = {"50 Cent - Collapse (Freestyle).mp3": (200.0, 2000)}
        self.assertIsNone(APP._pick_job_file(before, after,
                                            expected_title="'Til I Collapse Freestyle"))

    def test_ignora_i_file_non_audio(self):
        before = {}
        after = {"cover.jpg": (300.0, 10), "note.txt": (300.0, 10)}
        self.assertIsNone(APP._pick_job_file(before, after))


def yt_entry(title, duration, url, channel="Canale"):
    return {"title": title, "duration": duration, "webpage_url": url, "channel": channel}


class TestYtSearchSelection(unittest.TestCase):
    """`yt_search_first`: fra più titoli identici vince la versione più lunga.

    Senza questo, per "Sam Is Dead" (due video con lo stesso titolo, 31 s e
    170 s) la scelta dipendeva dall'ordine dei risultati di YouTube e poteva
    uscire la clip di 31 s. Le ricerche sono simulate: nessuna rete."""

    def setUp(self):
        self._orig = APP._yt_fetch_entries
        self.addCleanup(self._restore)

    def _restore(self):
        APP._yt_fetch_entries = self._orig

    def use_entries(self, entries):
        APP._yt_fetch_entries = lambda query: entries

    def test_tra_titoli_identici_vince_il_piu_lungo(self):
        self.use_entries([
            yt_entry("sam is dead", 31, "url-clip"),
            yt_entry("Sam (Is Dead)", 170, "url-completa"),
        ])
        url, title = APP.yt_search_first("Tyler Sam Is Dead", "Sam Is Dead", "Tyler")
        self.assertEqual(url, "url-completa")

    def test_le_clip_sotto_il_minuto_sono_penalizzate(self):
        self.use_entries([
            yt_entry("Sam Is Dead", 31, "url-clip"),      # titolo identico ma clip
            yt_entry("Sam (Is Dead)", 170, "url-completa"),
        ])
        # Titolo identico = precedenza, ma fra i due identici vince il completo;
        # le clip restano selezionabili solo se non c'è di meglio.
        url, _ = APP.yt_search_first("Tyler Sam Is Dead", "Sam Is Dead", "Tyler")
        self.assertEqual(url, "url-completa")

    def test_titolo_identico_batte_la_versione_estesa(self):
        # Comportamento voluto: un titolo identico vince anche se un altro video
        # ha un titolo simile con score alto (prevedibilità della scelta).
        self.use_entries([
            yt_entry("Sam Is Dead", 31, "url-clip"),
            yt_entry("Tyler, The Creator - Sam Is Dead (Showmix)", 401, "url-estesa"),
        ])
        url, _ = APP.yt_search_first("Tyler Sam Is Dead", "Sam Is Dead", "Tyler")
        self.assertEqual(url, "url-clip")

    def test_senza_titolo_esatto_si_usa_il_ranking(self):
        self.use_entries([
            yt_entry("Cosa Completamente Diversa", 200, "url-altra"),
            yt_entry("Sam Is Dead Freestyle", 200, "url-simile"),
        ])
        url, _ = APP.yt_search_first("Tyler Sam Is Dead", "Sam Is Dead", "Tyler")
        self.assertEqual(url, "url-simile")

    def test_sotto_soglia_non_si_scarica_nulla(self):
        self.use_entries([yt_entry("Cosa Completamente Diversa", 200, "url-altra")])
        self.assertEqual(APP.yt_search_first("x", "Sam Is Dead", "Tyler"), (None, None))

    def test_video_scartati_per_durata(self):
        self.use_entries([
            yt_entry("Sam Is Dead", 7, "url-troppo-corta"),
            yt_entry("Sam Is Dead", 3644, "url-loop"),
        ])
        self.assertEqual(APP.yt_search_first("Tyler Sam Is Dead", "Sam Is Dead", "Tyler"),
                         (None, None))

    # ── min_duration: l'audio deve contenere il secondo del sample ────────────
    def test_min_duration_preferisce_la_versione_che_contiene_il_timestamp(self):
        # Caso reale "Sam Is Dead" (16/09/2026): il titolo identico dura 170 s ma
        # il sample è a 216 s (3:36) → si sceglie la versione lunga da 401 s.
        self.use_entries([
            yt_entry("Sam Is Dead", 170, "url-tagliata"),
            yt_entry("Tyler, The Creator And Domo Genesis - Sam Is Dead", 401,
                     "url-lunga", channel="Tyler, The Creator"),
        ])
        url, _ = APP.yt_search_first("Tyler Sam Is Dead", "Sam Is Dead", "Tyler",
                                     min_duration=216)
        self.assertEqual(url, "url-lunga")

    def test_min_duration_con_titolo_identico_abbastanza_lungo(self):
        self.use_entries([
            yt_entry("Sam Is Dead", 260, "url-identica-lunga"),
            yt_entry("Sam Is Dead", 170, "url-identica-corta"),
        ])
        url, _ = APP.yt_search_first("Sam Is Dead", "Sam Is Dead", "",
                                     min_duration=216)
        self.assertEqual(url, "url-identica-lunga")

    def test_min_duration_senza_versioni_lunghe_non_blocca_il_download(self):
        # Nessun video arriva al timestamp: si consegna la versione corta (in
        # pagina compare l'avviso "il sample a 3:36 non c'è in questo audio"),
        # NON un errore: l'utente può comunque ascoltare e ritagliare a mano.
        self.use_entries([yt_entry("Sam Is Dead", 170, "url-corta")])
        url, _ = APP.yt_search_first("Sam Is Dead", "Sam Is Dead", "",
                                     min_duration=216)
        self.assertEqual(url, "url-corta")


    def test_min_duration_senza_artista_non_allarga_la_ricerca(self):
        # Senza artista l'allargamento a titoli simili è pericoloso (in prova
        # pescava "Sam Is Dead | Ghost (1990)", un video sul film): si resta sul
        # titolo identico anche se corto — la pagina avviserà che il sample non
        # è in quell'audio.
        self.use_entries([
            yt_entry("Sam Is Dead", 170, "url-tagliata"),
            yt_entry("Sam Is Dead | Ghost (1990)", 559, "url-film", channel="Cinema"),
        ])
        url, _ = APP.yt_search_first("Sam Is Dead", "Sam Is Dead", "",
                                     min_duration=216)
        self.assertEqual(url, "url-tagliata")

    def test_min_duration_allarga_solo_verso_l_artista_giusto(self):
        self.use_entries([
            yt_entry("Sam Is Dead", 170, "url-tagliata"),
            yt_entry("Sam Is Dead | Ghost (1990)", 559, "url-film", channel="Cinema"),
            yt_entry("Tyler, The Creator - Sam Is Dead", 401, "url-giusta",
                     channel="OfficialHipHopWire"),
        ])
        url, _ = APP.yt_search_first("Tyler Sam Is Dead", "Sam Is Dead", "Tyler",
                                     min_duration=216)
        self.assertEqual(url, "url-giusta")


class TestNomiFileDownload(unittest.TestCase):
    """Il nome del file scaricato deve distinguere video diversi con lo STESSO titolo.

    Bug del 16/09/2026: le cover "8-Bit Misfits" (303 s) e "Twinkle Twinkle Little
    Rock Star" (334 s) di *'Till I Collapse* hanno lo stesso titolo YouTube e
    finivano nello stesso file: la seconda card riproduceva l'audio della prima."""

    def test_template_include_l_id_del_video(self):
        self.assertIn("%(id)s", APP.DL_OUTTMPL,
                      "senza [%(id)s] due video con lo stesso titolo condividono il file")

    def test_clean_filename_toglie_l_id_youtube(self):
        self.assertEqual(APP.clean_filename("Eminem - Song [Pi3_Zs-oRUo].mp3"),
                         "Eminem - Song")

    def test_clean_filename_lascia_i_titoli_con_parentesi(self):
        # Solo un [id] di 11 caratteri viene tolto: un titolo con parentesi no.
        self.assertEqual(APP.clean_filename("Artist - Song [Remix Version].mp3"),
                         "Artist - Song [Remix Version]")


class TestDownloadsSnapshot(unittest.TestCase):
    def test_snapshot_ignora_i_file_nascosti(self):
        with tempfile.TemporaryDirectory() as d:
            orig = APP.DL_DIR
            APP.DL_DIR = d
            try:
                open(os.path.join(d, "brano.mp3"), "w").close()
                open(os.path.join(d, ".brano.mp3.part"), "w").close()
                snap = APP._downloads_snapshot()
                self.assertIn("brano.mp3", snap)
                self.assertNotIn(".brano.mp3.part", snap)
                self.assertEqual(snap["brano.mp3"][1], 0)   # size
            finally:
                APP.DL_DIR = orig


class TestConvertDownloadFormat(unittest.TestCase):
    """`_convert_download_format`: nessuna conversione inutile."""

    def test_formato_gia_richiesto(self):
        self.assertEqual(APP._convert_download_format("job", "brano.mp3", "mp3"), "brano.mp3")
        self.assertEqual(APP._convert_download_format("job", "brano.wav", "wav"), "brano.wav")

    def test_none_resta_none(self):
        self.assertIsNone(APP._convert_download_format("job", None, "mp3"))


@unittest.skipUnless(app_is_up(SAMPLELAB_URL), "app SampleLab non attiva")
class TestApiDownload(unittest.TestCase):
    """Contratto HTTP: un download fallito NON deve restituire un file altrui."""

    def _download(self, query, expected_title="", expected_artist="", min_duration=0,
                  timeout=240):
        body = {"query": query, "format": "mp3"}
        if expected_title:
            body["expected_title"] = expected_title
        if expected_artist:
            body["expected_artist"] = expected_artist
        if min_duration:
            body["min_duration"] = min_duration
        req = urllib.request.Request(
            SAMPLELAB_URL + "/download",
            data=json.dumps(body).encode(),
            headers={"Content-Type": "application/json"})
        jid = json.load(urllib.request.urlopen(req, timeout=30))["job_id"]
        t0 = time.time()
        while time.time() - t0 < timeout:
            job = json.load(urllib.request.urlopen(
                SAMPLELAB_URL + "/status/" + jid, timeout=30))
            if job.get("status") in ("done", "error"):
                return job
            time.sleep(2)
        self.fail("job di download non terminato entro %ss" % timeout)

    def test_video_inesistente_non_restituisce_un_audio_altrui(self):
        # Riproduce il caso reale: il download fallisce (video inesistente), ma
        # in cartella ci sono file appena scritti da altri job (es. Mosh.mp3). Il
        # job deve dare errore oppure — se il recupero trova un video giusto — un
        # file che contiene il titolo atteso: MAI l'audio di un altro brano.
        job = self._download("https://www.youtube.com/watch?v=zzzzzzzzzzz",
                             expected_title="Titolo Di Prova Inesistente Zzz")
        filename = job.get("filename") or ""
        if job.get("status") == "done":
            self.assertIn("titolidiprovainesistentezzz", APP.normalize(filename),
                          "consegnato un file che non è il brano richiesto: %r" % filename)
        else:
            self.assertEqual(job.get("status"), "error")
            self.assertFalse(filename, "job in errore ma con un filename: %r" % filename)

    def test_due_cover_con_lo_stesso_titolo_hanno_file_diversi(self):
        # Caso reale del 16/09/2026: *'Till I Collapse* ha due cover con lo stesso
        # titolo YouTube (8-Bit Misfits 303 s, Twinkle Twinkle Little Rock Star
        # 334 s) che finivano nello stesso file: la seconda riproduceva l'audio
        # della prima. Test di rete: alla prima esecuzione i due file vengono
        # scaricati, poi yt-dlp li riusa (l'[id] nel nome li rende distinti).
        cover1 = self._download("https://www.youtube.com/watch?v=1l_SO4Ndd6o",
                                expected_title="'Till I Collapse",
                                expected_artist="8-Bit Misfits")
        cover2 = self._download("https://www.youtube.com/watch?v=ZczdMEIW2rM",
                                expected_title="'Till I Collapse",
                                expected_artist="Twinkle Twinkle Little Rock Star")
        self.assertEqual(cover1.get("status"), "done", cover1.get("error"))
        self.assertEqual(cover2.get("status"), "done", cover2.get("error"))
        nomi = {cover1.get("filename"), cover2.get("filename")}
        self.assertNotIn(None, nomi)
        self.assertEqual(len(nomi), 2,
                         "le due cover condividono lo stesso file: %r" % nomi)


if __name__ == "__main__":
    unittest.main()
