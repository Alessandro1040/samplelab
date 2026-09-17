"""Test dello strumento ➡️ Sposta (app (2).py: `move_field_value`, /db/move_field).

Richiesta del 17/09/2026: nel pannello "⚙️ Esegui query / script personalizzati"
c'era un pulsante «📋 Script Eminem» — uno script pronto che spostava Eminem dal
titolo agli artisti. Il pulsante non c'è più: al suo posto c'è uno strumento
generico che sposta QUALSIASI testo da un campo all'altro (es. un artista dal
titolo agli artisti, l'anno dal titolo al campo anno), con anteprima prima di
scrivere e annullabile con ↩️ Undo.

Perché conta: in libreria 124 titoli hanno "(feat. …)" con l'artista da spostare
nel campo `artist`, e il 17/09 una sostituzione di massa fatta a mano
("50 Cent" → "51 Cent" su 35 righe) ha mostrato che gli strumenti in blocco
devono essere annullabili — ora lo sono sia ➡️ Sposta sia ✏️ Rinomina in massa.

Test puri sulla funzione `move_field_value` (+ `_pulisci_dopo_rimozione`) e test
HTTP sull'app viva: anteprima SENZA scrittura, validazioni e legenda
(/db/schema). Il ciclo completo scrittura + ↩️ Undo è verificato a parte su una
copia isolata del database (per non toccare la libreria vera).

Esecuzione (dalla cartella di SampleLab):
    python3 -m unittest -v test_move_field
I test HTTP girano solo se l'app è attiva (default http://localhost:5070,
sovrascrivibile con la variabile SAMPLELAB_URL).
"""
import importlib.util
import json
import os
import re
import unittest
import urllib.error
import urllib.request

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
APP_PATH = os.path.join(BASE_DIR, "app (2).py")
SAMPLELAB_URL = os.environ.get("SAMPLELAB_URL", "http://localhost:5070")


def load_app():
    """Carica il modulo dell'app dal file (il nome con spazio non conta).

    Non avvia il server: `init_db()` e `serve()` stanno sotto `if __name__ ==
    "__main__"`.
    """
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


def http_json(path, payload=None, method=None):
    """Chiama l'app viva e restituisce (stato, json). Non solleva sui 4xx/5xx."""
    data = None
    headers = {}
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(SAMPLELAB_URL + path, data=data, headers=headers,
                                 method=method or ("POST" if data else "GET"))
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            return r.status, json.loads(r.read().decode("utf-8") or "{}")
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8") or "{}"
        try:
            return e.code, json.loads(body)
        except json.JSONDecodeError:
            return e.code, {"raw": body}


class TestPuliziaDopoRimozione(unittest.TestCase):
    """`_pulisci_dopo_rimozione`: quel che resta quando si porta via un testo."""

    def test_parentesi_con_feat_rimasta_vuota(self):
        casi = {
            "Remember The Name (feat. )": "Remember The Name",
            "Bad Meets Evil (ft. )": "Bad Meets Evil",
            "Titolo [with ]": "Titolo",
            "Titolo ()": "Titolo",
        }
        for testo, atteso in casi.items():
            self.assertEqual(APP._pulisci_dopo_rimozione(testo), atteso, testo)

    def test_separatori_orfani(self):
        self.assertEqual(APP._pulisci_dopo_rimozione("Titolo -  "), "Titolo")
        self.assertEqual(APP._pulisci_dopo_rimozione(" - Titolo"), "Titolo")
        self.assertEqual(APP._pulisci_dopo_rimozione("Titolo / "), "Titolo")
        self.assertEqual(APP._pulisci_dopo_rimozione(" , Titolo"), "Titolo")

    def test_separatore_appeso_prima_di_una_parentesi(self):
        # caso reale: "The Anthem (feat. RZA, … , Chino XL & KRS-One)"
        self.assertEqual(APP._pulisci_dopo_rimozione("The Anthem (feat. RZA & )"),
                         "The Anthem (feat. RZA)")
        self.assertEqual(APP._pulisci_dopo_rimozione("Titolo (feat. A, B,)"),
                         "Titolo (feat. A, B)")

    def test_non_tocca_i_titoli_sani(self):
        for testo in ("Nuttin’ To Do", "As the World Turns", "50 Cent - In da Club"):
            self.assertEqual(APP._pulisci_dopo_rimozione(testo), testo)


class TestMoveFieldValue(unittest.TestCase):
    """`move_field_value`: sposta un testo dal campo sorgente alla destinazione."""

    def test_artista_dal_titolo_all_artista(self):
        nuovo_titolo, nuovo_artista = APP.move_field_value(
            "Because I Can (feat. Eminem)", "The Jokerr", "Eminem")
        self.assertEqual(nuovo_titolo, "Because I Can")
        self.assertEqual(nuovo_artista, "The Jokerr / Eminem")

    def test_anno_dal_titolo_al_campo_anno(self):
        titolo, anno = APP.move_field_value("Kenny Parker Show 2001 (feat. KRS-One)",
                                            None, "2001", numerico=True)
        self.assertEqual(titolo, "Kenny Parker Show (feat. KRS-One)")
        self.assertEqual(anno, "2001")

    def test_destinazione_numerica_occupata_viene_saltata(self):
        # l'anno c'è già: non lo sovrascrivo (meglio saltare la riga che perdere un dato)
        self.assertEqual(APP.move_field_value("Titolo 2001", 1999, "2001", numerico=True),
                         (None, None))

    def test_campo_sorgente_con_solo_quel_testo_non_viene_svuotato(self):
        self.assertEqual(APP.move_field_value("Eminem", "Dr. Dre", "Eminem"), (None, None))

    def test_testo_assente_dal_campo_sorgente(self):
        self.assertEqual(APP.move_field_value("Titolo", "Artista", "Eminem"), (None, None))

    def test_parola_intera_non_tocca_le_parole_che_la_contengono(self):
        # "Ever" dentro "Forever": né tolto dal titolo né aggiunto agli artisti
        # (bug trovato da questo test il 17/09: prima il nome finiva negli
        # artisti senza essere tolto dal titolo)
        self.assertEqual(APP.move_field_value("Forever Young", "Dr. Dre", "Ever"), (None, None))
        # senza "parola intera" invece tocca anche dentro la parola
        titolo, artista = APP.move_field_value("Forever Young", "Dr. Dre", "Ever", whole_word=False)
        self.assertEqual(titolo, "For Young")   # "For|ever Young" → tolto "ever"
        self.assertEqual(artista, "Dr. Dre / Ever")  # nel campo va la forma scritta a mano

    def test_destinazione_che_ha_gia_il_testo_non_lo_duplica(self):
        titolo, artista = APP.move_field_value("Titolo (feat. Eminem)", "Eminem", "Eminem")
        self.assertEqual(titolo, "Titolo")
        self.assertEqual(artista, "Eminem")

    def test_modo_replace_sostituisce_la_destinazione(self):
        titolo, artista = APP.move_field_value("Titolo (feat. Eminem)", "Dr. Dre",
                                               "Eminem", mode="replace")
        self.assertEqual(titolo, "Titolo")
        self.assertEqual(artista, "Eminem")

    def test_senza_pulizia_restano_le_parentesi_vuote(self):
        titolo, _ = APP.move_field_value("Titolo (feat. Eminem)", None, "Eminem",
                                         pulisci=False)
        self.assertEqual(titolo, "Titolo (feat. )")

    def test_multipli_occorrenze_dello_stesso_testo(self):
        titolo, artista = APP.move_field_value("Eminem & Eminem", "Dr. Dre", "Eminem")
        self.assertEqual(titolo, "&")           # entrambe tolte dal titolo
        self.assertEqual(artista, "Dr. Dre / Eminem")  # nel campo artista una sola volta

    def test_titolo_con_solo_separatori_dopo_la_rimozione(self):
        # "Titolo - Eminem" → resta "Titolo", non "-"
        self.assertEqual(APP.move_field_value("Titolo - Eminem", None, "Eminem"),
                         ("Titolo", "Eminem"))


@unittest.skipUnless(app_is_up(SAMPLELAB_URL), f"app non attiva su {SAMPLELAB_URL}")
class TestSpostaHttp(unittest.TestCase):
    """➡️ /db/move_field sull'app viva: anteprima e validazioni.

    Nessuno di questi test scrive nel database: l'anteprima (dry_run) non salva
    niente e le validazioni rispondono 400 prima di toccare le righe. Il ciclo
    completo scrittura + ↩️ Undo è verificato a parte su una copia isolata del DB.
    """

    @classmethod
    def setUpClass(cls):
        stato, songs = http_json("/db/songs")
        cls.songs = songs if isinstance(songs, list) else []

    def caso_feat(self):
        """Prima canzone con "(feat. …)" nel titolo → (riga, nome da spostare).

        Il confine di parola dopo "feat"/"ft"/"with" serve a non prendere
        "Featuring" (che diventerebbe "uring Ne-Yo").
        """
        for s in self.songs:
            m = re.search(r"\(\s*(?:feat|ft|with)\.?\s+([^)]+)\)",
                          s.get("title") or "", re.IGNORECASE)
            if m and m.group(1).strip():
                return s, m.group(1).strip()
        self.skipTest("nessun titolo con (feat. …) nella libreria")

    def test_anteprima_non_scrive_niente(self):
        riga, nome = self.caso_feat()
        stato, r = http_json("/db/move_field", {
            "from_field": "title", "to_field": "artist", "text": nome,
            "whole_word": True, "clean": True, "dry_run": True})
        self.assertEqual(stato, 200, r)
        self.assertTrue(r["dry_run"])
        self.assertGreaterEqual(r["count"], 1, r)
        self.assertIn(riga["id"], [u["id"] for u in r["updated"]])
        for u in r["updated"]:
            self.assertNotIn("(feat. )", (u["new_from"] or "").lower(), u)
            self.assertNotIn("()", u["new_from"] or "", u)
            self.assertIn(nome.split()[0].lower(), (u["new_to"] or "").lower(), u)
        # la riga vera è rimasta identica
        stato, dopo = http_json("/db/songs/" + riga["id"])
        self.assertEqual(stato, 200)
        self.assertEqual(dopo["title"], riga["title"])
        self.assertEqual(dopo["artist"], riga["artist"])

    def test_stessi_campi_da_e_a(self):
        stato, r = http_json("/db/move_field", {"from_field": "title",
                                                "to_field": "title", "text": "x"})
        self.assertEqual(stato, 400)
        self.assertIn("due campi diversi", r["error"])

    def test_testo_vuoto(self):
        stato, _ = http_json("/db/move_field", {"from_field": "title",
                                                "to_field": "artist", "text": "  "})
        self.assertEqual(stato, 400)

    def test_campo_non_consentito(self):
        stato, r = http_json("/db/move_field", {"from_field": "id",
                                                "to_field": "artist", "text": "x"})
        self.assertEqual(stato, 400)
        self.assertIn("Campi consentiti", r["error"])

    def test_destinazione_anno_vuole_una_cifra(self):
        stato, r = http_json("/db/move_field", {"from_field": "title",
                                                "to_field": "year", "text": "Eminem"})
        self.assertEqual(stato, 400)
        self.assertIn("numerico", r["error"])

    def test_rinomina_in_massa_senza_match_non_lascia_snapshot(self):
        """La ✏️ Rinomina in massa senza corrispondenze non crea voci di Undo."""
        _, prima = http_json("/db/history")
        stato, r = http_json("/db/mass_rename", {"field": "title",
                                                 "find": "ZZZ_NON_ESISTE_ZZZ",
                                                 "replace": "x"})
        self.assertEqual(stato, 200, r)
        self.assertEqual(r["count"], 0)
        _, dopo = http_json("/db/history")
        self.assertEqual(dopo["undo"], prima["undo"])


@unittest.skipUnless(app_is_up(SAMPLELAB_URL), f"app non attiva su {SAMPLELAB_URL}")
class TestLegendaSchema(unittest.TestCase):
    """📖 /db/schema: legenda del pannello (tabelle, campi, comandi consentiti)."""

    @classmethod
    def setUpClass(cls):
        cls.stato, cls.s = http_json("/db/schema")

    def test_tabelle_della_libreria(self):
        self.assertEqual(self.stato, 200)
        nomi = [t["name"] for t in self.s["tables"]]
        for atteso in ("songs", "sample_relations", "stem_sessions", "stem_tracks",
                       "audio_analyses", "playback_state"):
            self.assertIn(atteso, nomi)
        for t in self.s["tables"]:
            self.assertTrue(t["doc"], f"la tabella {t['name']} ha una descrizione in italiano")

    def test_campi_della_tabella_songs(self):
        songs = next(t for t in self.s["tables"] if t["name"] == "songs")
        campi = {c["name"]: c for c in songs["columns"]}
        for atteso in ("id", "title", "artist", "album", "bpm", "musical_key", "lyrics",
                       "local_file", "updated_at"):
            self.assertIn(atteso, campi)
        self.assertGreater(songs["count"], 0)
        self.assertTrue(campi["artist"]["doc"], "il campo artist ha una descrizione")
        self.assertTrue(campi["id"]["pk"], "id è la chiave primaria")

    def test_comandi_consentiti(self):
        self.assertEqual(self.s["sql"]["allowed"], ["SELECT", "UPDATE"])
        self.assertIn("DROP", self.s["sql"]["forbidden"])
        self.assertIn("conn", self.s["script"]["globals"])
        self.assertEqual(self.s["script"]["timeout"], 30)

    def test_campi_dello_strumento_sposta(self):
        for campo in ("title", "artist", "album", "year"):
            self.assertIn(campo, self.s["bulk_fields"])
        self.assertEqual(self.s["numeric_fields"], ["year"])


if __name__ == "__main__":
    unittest.main()
