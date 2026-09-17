"""Test del pannello SQL/script: cosa si può eseguire e cosa no (`sql_consentita`).

Richiesta di Alessandro (18/09/2026): «non capisco perché quella attuale non
funziona su Eminem/Rihanna» — la query naturale per unificare gli artisti,
`UPDATE songs SET artist = replace(artist, ',', ' / ')`, veniva **rifiutata**
dal pannello: fra i comandi vietati c'è `REPLACE` (per bloccare `REPLACE INTO`)
e il controllo colpiva anche la funzione `replace(...)`. La query non arrivava
mai al database, quindi «Rihanna / Eminem» restava com'era.

Ora la parola vietata conta solo se è un COMANDO (non seguita da parentesi):
`replace(...)` passa, `REPLACE INTO …` resta bloccato, e i comandi distruttivi
restano fuori dal pannello perché la query deve cominciare con SELECT o UPDATE.

Questo file prova:
1. `TestGuardiaSql` — la funzione pura `sql_consentita` dell'app vera (caricata
   con importlib: il nome «app (2).py» con lo spazio non è importabile
   normalmente), sui casi scritti a mano.
2. `TestCablaggio` — il sorgente usa ancora il controllo «solo comando»: se
   qualcuno torna al vecchio controllo senza la parentesi, il test cade.
3. `TestEndpointVivo` — se l'app è attiva, gli stessi casi via `/db/execute`.
   Solo query innocue: le SELECT non scrivono e i comandi distruttivi sono
   indirizzati a una **tabella inesistente** (se la guardia non li fermasse non
   cambierebbe comunque niente nella libreria).

Esecuzione (dalla cartella di SampleLab):
    python3 -m unittest -v test_sql_guard
I test HTTP girano solo se l'app è attiva (default http://localhost:5070,
sovrascrivibile con la variabile SAMPLELAB_URL).
"""
import importlib.util
import json
import os
import unittest
import urllib.error
import urllib.request

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
APP_PATH = os.path.join(BASE_DIR, "app (2).py")
SAMPLELAB_URL = os.environ.get("SAMPLELAB_URL", "http://localhost:5070")


def load_app():
    """Carica il modulo dell'app dal file (il nome con spazio non conta)."""
    spec = importlib.util.spec_from_file_location("samplelab_app2", APP_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


APP = load_app()

# (sql, messaggio atteso: "" = consentita)
CASI = [
    # ── consentite ──
    ("SELECT * FROM songs LIMIT 10", ""),
    ("select count(*) from songs", ""),
    ("UPDATE songs SET artist='x' WHERE id='y'", ""),
    # la funzione che serve a correggere gli artisti e i titoli
    ("UPDATE songs SET artist=replace(artist, ' / ', ', ') WHERE artist LIKE '% / %'", ""),
    ("SELECT replace(title, '  ', ' ') FROM songs", ""),
    ("UPDATE songs SET title = REPLACE(title, 'Eminem ', '') WHERE title LIKE '%Eminem%'", ""),
    # ── bloccate: comandi distruttivi ──
    ("DROP TABLE songs", "Sono consentite solo SELECT e UPDATE"),
    ("DELETE FROM songs WHERE id='x'", "Sono consentite solo SELECT e UPDATE"),
    ("INSERT INTO songs (id) VALUES ('x')", "Sono consentite solo SELECT e UPDATE"),
    # REPLACE INTO: dopo la parola non c'è una parentesi → è un comando
    ("REPLACE INTO songs (id) VALUES ('x')", "Sono consentite solo SELECT e UPDATE"),
    # …e anche in mezzo a una UPDATE resta un comando, non una funzione
    ("UPDATE songs SET title='DROP TABLE songs' WHERE id='x'", "Operazione non consentita"),
    ("UPDATE songs SET title='x' WHERE id='y'; DELETE FROM songs", "Operazione non consentita"),
]


class TestGuardiaSql(unittest.TestCase):
    """La funzione vera dell'app, senza avviare il server."""

    def test_sql_consentita(self):
        for sql, atteso in CASI:
            with self.subTest(sql=sql[:60]):
                self.assertEqual(APP.sql_consentita(sql), atteso)

    def test_replace_funzione_ammessa_in_select_e_update(self):
        self.assertEqual(APP.sql_consentita("SELECT replace(artist, 'a', 'b') FROM songs"), "")
        self.assertEqual(APP.sql_consentita("UPDATE songs SET artist=replace(artist,'a','b')"), "")
        self.assertEqual(APP.sql_consentita("REPLACE INTO songs (id) VALUES ('x')"),
                         "Sono consentite solo SELECT e UPDATE")

    def test_falso_positivo_noto_dentro_una_stringa(self):
        # Limite noto e accettato: una parola vietata scritta DENTRO una stringa
        # viene comunque bloccata. Se un giorno si escludono le stringhe dal
        # controllo, aggiornare questo test (e il commento di sql_consentita).
        self.assertEqual(
            APP.sql_consentita("SELECT id FROM songs WHERE comment LIKE '%drop%'"),
            "Operazione non consentita")


class TestCablaggio(unittest.TestCase):
    """Il controllo deve restare «parola come comando, non come funzione»."""

    @classmethod
    def setUpClass(cls):
        with open(APP_PATH, encoding="utf-8") as fh:
            cls.src = fh.read()

    def test_sorgente_della_guardia(self):
        self.assertIn(r're.search(rf"\b{w}\b(?!\s*\()", sql_upper)', self.src,
                      "la guardia deve escludere le funzioni (replace(...))")
        self.assertIn("def sql_consentita(sql):", self.src)
        self.assertIn("problema = sql_consentita(sql)", self.src,
                      "la view /db/execute deve usare la funzione")

    def test_elenchi_consentiti_e_vietati(self):
        self.assertEqual(APP.SQL_ALLOWED, ["SELECT", "UPDATE"])
        self.assertIn("REPLACE", APP.SQL_FORBIDDEN)
        self.assertIn("DROP", APP.SQL_FORBIDDEN)


def app_is_up(url):
    try:
        urllib.request.urlopen(url + "/db/stats", timeout=3)
        return True
    except Exception:
        return False


@unittest.skipUnless(app_is_up(SAMPLELAB_URL), "app non attiva su " + SAMPLELAB_URL)
class TestEndpointVivo(unittest.TestCase):
    """Gli stessi casi attraverso /db/execute (senza mai scrivere nella libreria)."""

    @staticmethod
    def chiedi(sql):
        req = urllib.request.Request(
            SAMPLELAB_URL + "/db/execute",
            data=json.dumps({"sql": sql}).encode(),
            headers={"Content-Type": "application/json"}, method="POST")
        try:
            r = urllib.request.urlopen(req, timeout=15)
            return r.status, json.load(r)
        except urllib.error.HTTPError as e:
            return e.code, json.load(e)

    def test_replace_ammesso(self):
        stato, risposta = self.chiedi(
            "SELECT replace(artist, ' / ', ' / ') AS x FROM songs WHERE artist LIKE '%Rihanna%' LIMIT 1")
        self.assertEqual(stato, 200, risposta)
        self.assertEqual(risposta.get("type"), "select")

    def test_comandi_distruttivi_respinti(self):
        for sql in ("REPLACE INTO tabella_inesistente (x) VALUES (1)",
                    "INSERT INTO tabella_inesistente (x) VALUES (1)",
                    "DELETE FROM tabella_inesistente",
                    "DROP TABLE tabella_inesistente"):
            with self.subTest(sql=sql[:40]):
                stato, risposta = self.chiedi(sql)
                self.assertEqual(stato, 400, risposta)
                self.assertIn(risposta.get("error"), ("Operazione non consentita",
                                                      "Sono consentite solo SELECT e UPDATE"))

    def test_libreria_intatta_dopo_i_test(self):
        stato, risposta = self.chiedi("SELECT count(*) AS n FROM songs")
        self.assertEqual(stato, 200)
        self.assertGreaterEqual(risposta["rows"][0]["n"], 800)


if __name__ == "__main__":
    unittest.main()

