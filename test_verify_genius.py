"""Test del recupero crediti da Genius (app (2).py).

Richiesta del 16/09/2026: premendo "Verifica" su un brano (es. *Apex* di Chris
Webby) il database registrava solo l'artista principale di Genius, senza i
featuring, e spesso senza produttori/compositori — per due motivi:
1. il campo `artist` veniva riempito con `genius["artist"]` (solo il primary) e
   solo se `artist_verified` era 0, quindi le righe già verificate non si
   completavano mai;
2. i produttori arrivano solo dall'API della singola canzone (`/api/songs/<id>`),
   che a volte risponde vuoto/429 e non veniva ritentata (7 brani verificati su
   54 senza produttori, 5 senza compositori).

Questi test coprono gli helper puri e verificano sull'API viva (`/genius`) che
Genius restituisca davvero tutti gli artisti, i produttori e i compositori.

Esecuzione (dalla cartella di SampleLab):
    python3 -m unittest -v test_verify_genius
I test HTTP girano solo se l'app è attiva (default http://localhost:5070,
sovrascrivibile con la variabile SAMPLELAB_URL).
"""
import importlib.util
import json
import os
import unittest
import urllib.request

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
APP_PATH = os.path.join(BASE_DIR, "app (2).py")
SAMPLELAB_URL = os.environ.get("SAMPLELAB_URL", "http://localhost:5070")


def load_app():
    """Carica il modulo dell'app dal file (il nome con spazio non conta).
    L'import NON avvia il server e non tocca il database."""
    spec = importlib.util.spec_from_file_location("samplelab_app2", APP_PATH)
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


class TestAnnoEAlbumPuri(unittest.TestCase):
    """Verifiche del 17/09/2026: dopo la Verifica la riga aveva la data di Genius
    ("September 2, 2025") ma la casella **anno** vuota, e l'album restava il
    segnaposto "Mus" (il nome della cartella di caricamento)."""

    def test_anno_da_data_inglese(self):
        self.assertEqual(APP._year_from_date("September 2, 2025"), 2025)

    def test_anno_da_data_iso(self):
        self.assertEqual(APP._year_from_date("2002-10-28"), 2002)

    def test_anno_da_data_con_anno_a_inizio(self):
        self.assertEqual(APP._year_from_date("1998, April 1"), 1998)

    def test_anno_assente(self):
        self.assertIsNone(APP._year_from_date(""))
        self.assertIsNone(APP._year_from_date(None))
        self.assertIsNone(APP._year_from_date("senza data"))
        self.assertIsNone(APP._year_from_date("12/34"))

    def test_album_segnaposto_riconosce_i_falsi(self):
        for v in ("Mus", "  mus ", "Music", "Album sconosciuto", "", None, "N/A"):
            self.assertTrue(APP._album_segnaposto(v), f"{v!r} doveva essere un segnaposto")

    def test_album_segnaposto_non_tocca_gli_album_veri(self):
        # anche corti, ma reali: non devono essere sovrascritti
        for v in ("2001", "BV3", "King Mathers", "17", "SOS"):
            self.assertFalse(APP._album_segnaposto(v), f"{v!r} è un album vero")


class TestCreditiPuri(unittest.TestCase):
    def test_credits_missing_vero_se_manca_un_nome(self):
        self.assertTrue(APP._credits_missing("Chris Webby", ["Chris Webby", "ANoyd"]))

    def test_credits_missing_falso_se_ci_sono_tutti(self):
        self.assertFalse(APP._credits_missing(
            "Chris Webby / Ren Thomas / Mickey Factz / ANoyd / Apathy / NEMS",
            ["Chris Webby", "Ren Thomas", "Mickey Factz", "ANoyd", "Apathy", "NEMS"]))

    def test_credits_missing_ignora_maiuscole_e_formato(self):
        # Genius scrive "NEMS"/"ANoyd", il DB può avere "Nems": non è un mancante.
        self.assertFalse(APP._credits_missing("Chris Webby / Nems", ["Chris Webby", "NEMS"]))

    def test_credits_missing_funziona_col_json_dei_produttori(self):
        # Nel DB i produttori sono salvati come JSON: '["Nox Beatz", "C-Lance"]'.
        self.assertFalse(APP._credits_missing('["Nox Beatz", "C-Lance"]',
                                             ["Nox Beatz", "C-Lance"]))
        self.assertTrue(APP._credits_missing('["C-Lance"]', ["Nox Beatz", "C-Lance"]))

    def test_credits_missing_su_campo_vuoto(self):
        self.assertTrue(APP._credits_missing("", ["Scott Storch"]))
        self.assertFalse(APP._credits_missing("", []))

    def test_unique_names_toglie_duplicati_e_vuoti(self):
        self.assertEqual(APP._unique_names(["Chris Webby", "chris webby", "", "  ", "Nems"]),
                         ["Chris Webby", "Nems"])


@unittest.skipUnless(app_is_up(SAMPLELAB_URL), "app SampleLab non attiva")
class TestGeniusApi(unittest.TestCase):
    """/genius deve restituire TUTTI gli artisti, i produttori e i compositori.

    Test di rete contro Genius (nessuna scrittura sul database)."""

    def _genius(self, artist, title):
        req = urllib.request.Request(
            SAMPLELAB_URL + "/genius",
            data=json.dumps({"artist": artist, "title": title}).encode(),
            headers={"Content-Type": "application/json"})
        return json.load(urllib.request.urlopen(req, timeout=60))

    def test_apex_chris_webby_tutti_i_crediti(self):
        g = self._genius("Chris Webby", "Apex")
        self.assertIsNotNone(g, "Genius non ha trovato 'Apex'")
        artists = g.get("artists") or []
        # primary + 5 featuring, come la pagina Genius
        for atteso in ["Chris Webby", "Ren Thomas", "Mickey Factz", "ANoyd", "Apathy", "NEMS"]:
            self.assertIn(atteso, artists, "manca %s in artists: %r" % (atteso, artists))
        self.assertEqual(artists[0], "Chris Webby", "il primary artist deve restare primo")
        self.assertIn("Nox Beatz", g.get("producers") or [], "produttori mancanti")
        self.assertIn("C-Lance", g.get("producers") or [], "produttori mancanti")
        self.assertIn("Chris Webby", g.get("composers") or [], "compositori mancanti")

    def test_artista_singolo_resta_tale(self):
        # Nessun featuring: l'elenco non deve inventarsi nomi in più.
        g = self._genius("Eminem", "Lose Yourself")
        if not g:
            self.skipTest("Genius non ha risposto")
        self.assertEqual(g.get("artists"), ["Eminem"])


if __name__ == "__main__":
    unittest.main()
