"""Test del 📂 caricamento a mano di una cartella di stem (app (2).py + scheda.html).

Richiesta del 18/09/2026 (Alessandro): «se clicchi su una canzone nel database
puoi separare gli stem e salvarli automaticamente, però vorrei aggiungere la
possibilità di caricarli manualmente: caricare una cartella di stem e fare in
modo che vengano salvati nel database direttamente lì — e se gli stem si
chiamano "canzone - Violino", "canzone - Pianoforte" …, nell'app dovranno
comparire solo come Pianoforte ecc. E ci dovrà essere il mass renamer che c'è
già da un'altra parte: deve essere lo stesso identico renamer» → il pannello
«✏️ Rinomina in massa» del tab Database, con le stesse regole e lo stesso ↩️
Undo, applicato alle ETICHETTE delle tracce (`stem_tracks.stem_type`).

Cosa copre questo file:
1. `strumento_da_nomefile` (funzione pura in `app (2).py`): dal nome del file
   all'etichetta della traccia;
2. la STESSA regola in JavaScript (`etichettaStemDaNome` in scheda.html),
   confrontata caso per caso con quella Python dentro JavaScriptCore;
3. il cablaggio: rotte dell'app, selettore di cartella nella pagina, opzione
   «🏷 Etichetta stem» nel pannello Rinomina in massa, pulsante 📂 nella tabella;
4. il giro COMPLETO sull'app viva, su una canzone di prova usa-e-getta: import
   della cartella → righe in `stem_tracks`, ricarica senza doppioni, rinomina in
   massa delle etichette (+ ↩️ Undo) e cancellazione della sessione. Alla fine
   database e cartelle tornano come prima (il test lo verifica).

Esecuzione (dalla cartella di SampleLab):
    python3 -m unittest -v test_stem_upload
I test HTTP girano solo se l'app è attiva (default http://localhost:5070,
sovrascrivibile con la variabile SAMPLELAB_URL).
"""
import importlib.util
import json
import os
import re
import shutil
import sqlite3
import subprocess
import unittest
import urllib.error
import urllib.parse
import urllib.request
import uuid

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
APP_PATH = os.path.join(BASE_DIR, "app (2).py")
PAGINA_PATH = os.path.join(BASE_DIR, "scheda.html")
INDEX_PATH = os.path.join(BASE_DIR, "index (2).html")
DB_PATH = os.path.join(BASE_DIR, "samplelab (2).db")
STEMS_DIR = os.path.join(BASE_DIR, "stems", "htdemucs")
TRASH_DIR = os.path.join(BASE_DIR, ".trash")
SAMPLELAB_URL = os.environ.get("SAMPLELAB_URL", "http://localhost:5070")
HA_OSASCRIPT = shutil.which("osascript") is not None


def load_app():
    """Carica il modulo dell'app dal file (il nome con spazio non conta).

    Non avvia il server: `init_db()` e `serve()` stanno sotto `if __name__ ==
    "__main__"`.
    """
    spec = importlib.util.spec_from_file_location("samplelab_app2_stem", APP_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


APP = load_app()


def leggi(percorso):
    with open(percorso, encoding="utf-8") as fh:
        return fh.read()


# ── il runner JavaScript (stesso schema di test_scheda_canzone.py) ───────────
def _blocco(src, inizio, apri, chiudi, cosa):
    i = src.index(apri, inizio)
    liv, j = 0, i
    while j < len(src):
        if src[j] == apri:
            liv += 1
        elif src[j] == chiudi:
            liv -= 1
            if liv == 0:
                return src[i:j + 1]
        j += 1
    raise AssertionError("parentesi non bilanciate in %s" % cosa)


def estrai_funzione(src, nome):
    m = re.search(r"(?:async\s+)?function\s+" + re.escape(nome) + r"\s*\(", src)
    if not m:
        raise AssertionError("funzione %s assente in %s" % (nome, PAGINA_PATH))
    inizio_corpo = src.index("{", m.end() - 1)
    corpo = _blocco(src, m.end() - 1, "{", "}", nome)
    return src[m.start(): inizio_corpo + len(corpo)]


def estrai_costante(src, nome):
    """La riga `const NOME=…;` (per le costanti che non sono oggetti letterali)."""
    m = re.search(r"const\s+" + re.escape(nome) + r"\s*=\s*[^;]+;", src)
    if not m:
        raise AssertionError("costante %s assente in %s" % (nome, PAGINA_PATH))
    return m.group(0)


def esegui_js(codice, nome_file="/tmp/test_stem_upload.js"):
    """Esegue un frammento di JavaScript con JavaScriptCore e torna il JSON finale."""
    with open(nome_file, "w", encoding="utf-8") as out:
        out.write(codice + "\n0;\n")
    r = subprocess.run(["osascript", "-l", "JavaScript", nome_file],
                       capture_output=True, text=True)
    righe = ((r.stdout or "") + (r.stderr or "")).strip().splitlines()
    if not righe:
        raise AssertionError("nessun output da JavaScriptCore: %s" % (r.stderr or "")[:200])
    return json.loads(righe[-1])


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
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.status, json.loads(r.read().decode("utf-8") or "{}")
    except urllib.error.HTTPError as e:
        corpo = e.read().decode("utf-8") or "{}"
        try:
            return e.code, json.loads(corpo)
        except json.JSONDecodeError:
            return e.code, {"raw": corpo}


def http_carica_stem(song_id, files, etichette=None):
    """POST multipart su /db/songs/<id>/stems/import (come fa la pagina /scheda).

    `files` è una lista di (nome, contenuto): è il selettore di CARTELLA del
    browser, che manda tutti i file scelti col nome di campo `files`.
    """
    boundary = "----SampleLabTest%s" % uuid.uuid4().hex
    parti = []
    if etichette is not None:
        campo = ("--%s\r\nContent-Disposition: form-data; name=\"etichette\"\r\n\r\n%s\r\n"
                 % (boundary, json.dumps(etichette)))
        parti.append(campo.encode("utf-8"))
    for nome, contenuto in files:
        testa = ("--%s\r\nContent-Disposition: form-data; name=\"files\"; filename=\"%s\"\r\n"
                 "Content-Type: audio/mpeg\r\n\r\n" % (boundary, nome))
        parti.append(testa.encode("utf-8") + contenuto + b"\r\n")
    parti.append(("--%s--\r\n" % boundary).encode("utf-8"))
    req = urllib.request.Request(
        SAMPLELAB_URL + "/db/songs/%s/stems/import" % urllib.parse.quote(song_id),
        data=b"".join(parti), method="POST",
        headers={"Content-Type": "multipart/form-data; boundary=%s" % boundary})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return r.status, json.loads(r.read().decode("utf-8") or "{}")
    except urllib.error.HTTPError as e:
        corpo = e.read().decode("utf-8") or "{}"
        try:
            return e.code, json.loads(corpo)
        except json.JSONDecodeError:
            return e.code, {"raw": corpo}


# ── i casi scritti a mano: (nome del file, etichetta attesa) ─────────────────
CASI_NOME = [
    # il caso della richiesta: la canzone davanti, lo strumento dopo
    ("canzone - Violino.mp3", "violino"),
    ("canzone - Pianoforte.mp3", "pianoforte"),
    # il titolo può contenere altri « - »: conta l'ULTIMO pezzo
    ("50 Cent - In da Club - Pianoforte.wav", "pianoforte"),
    ("Tyler, The Creator And Domo Genesis - Sam Is Dead - Batteria.flac", "batteria"),
    # separatori scritti in modi diversi (underscore, trattini tipografici)
    ("canzone_-_Batteria.flac", "batteria"),
    ("canzone \u2013 Violino.mp3", "violino"),
    ("canzone \u2014 Archi.ogg", "archi"),
    # marcatore di duplicato lasciato dal file system
    ("canzone - Violino (2).mp3", "violino"),
    ("canzone - Archi [3].wav", "archi"),
    # le tracce di Demucs NON hanno separatore: resta tutto il nome
    ("vocals.mp3", "vocals"),
    ("drums.mp3", "drums"),
    # separatore senza niente dopo: non si butta via il nome
    ("canzone - .mp3", "canzone"),
    # un nome e basta, con gli spazi dell'export alla rinfusa
    ("Violino.wav", "violino"),
    ("  canzone  -   Pianoforte  .mp3", "pianoforte"),
    # niente da ricavare
    ("", ""),
    ("   ", ""),
]


class TestStrumentoDaNomefile(unittest.TestCase):
    """`strumento_da_nomefile`: la regola dell'app (funzione pura)."""

    def test_casi_scritti_a_mano(self):
        for nome, atteso in CASI_NOME:
            with self.subTest(nome=nome):
                self.assertEqual(APP.strumento_da_nomefile(nome), atteso)

    def test_etichette_in_ordine(self):
        nomi = ["canzone - Violino.mp3", "canzone - Pianoforte.mp3", "vocals.mp3"]
        self.assertEqual(APP.etichette_stem_da_nomi(nomi), ["violino", "pianoforte", "vocals"])
        self.assertEqual(APP.etichette_stem_da_nomi(None), [])

    def test_estensioni_audio_riconosciute(self):
        # l'estensione si toglie solo se è un'estensione audio vera: un pezzo di
        # titolo con un punto dentro non deve sparire
        self.assertEqual(APP.strumento_da_nomefile("canzone - Sig. Rossi.mp3"), "sig. rossi")
        self.assertEqual(APP.strumento_da_nomefile("canzone - Archi.aiff"), "archi")
        self.assertEqual(APP.strumento_da_nomefile("canzone - Archi.aiff.txt"), "archi.aiff.txt")

    def test_nome_file_sicuro(self):
        # il nome arriva dal browser: niente percorsi, niente file nascosti
        self.assertEqual(APP._nome_file_sicuro("../../etc/passwd"), "passwd")
        self.assertEqual(APP._nome_file_sicuro("cartella\\sub\\Violino.mp3"), "Violino.mp3")
        self.assertEqual(APP._nome_file_sicuro(".nascosto.mp3"), "nascosto.mp3")
        self.assertEqual(APP._nome_file_sicuro(""), "")

    def test_cartella_della_canzone(self):
        # con il file locale: la stessa cartella che usa Demucs
        self.assertEqual(APP._cartella_stem({"id": "song_a", "local_file": "X - Y.mp3"}), "X - Y")
        # senza file locale: una cartella sua, così le tracce restano ordinabili
        self.assertEqual(APP._cartella_stem({"id": "song_abc", "local_file": ""}), "caricati_abc")
        self.assertEqual(APP._cartella_stem({"id": "song_abc", "local_file": None}), "caricati_abc")

    def test_le_etichette_escono_minuscole(self):
        # come le tracce di Demucs (vocals/drums): la maiuscola la mette la pagina
        for nome in ("canzone - VIOLINO.mp3", "Canzone - pianoforte.mp3"):
            with self.subTest(nome=nome):
                self.assertEqual(APP.strumento_da_nomefile(nome), APP.strumento_da_nomefile(nome).lower())


@unittest.skipUnless(HA_OSASCRIPT, "JavaScriptCore (osascript) non disponibile")
class TestEtichettaPaginaUgualeAllaPython(unittest.TestCase):
    """La regola scritta in scheda.html, eseguita davvero in JavaScriptCore."""

    risultati = {}

    @classmethod
    def setUpClass(cls):
        src = leggi(PAGINA_PATH)
        js = "\n".join([
            estrai_costante(src, "STEM_EXT"),
            estrai_funzione(src, "etichettaStemDaNome"),
            estrai_funzione(src, "eFileAudioStem"),
            estrai_funzione(src, "origineStem"),
        ])
        js += """
const out = {etichette:{}, audio:{}, origine:{}};
for (const nome of %s) { out.etichette[nome] = etichettaStemDaNome(nome); }
for (const nome of %s) { out.audio[nome] = eFileAudioStem(nome); }
const righe = [{origine:'database',modello:'manuale'},{origine:'database',modello:'htdemucs'},
               {origine:'disco',modello:'htdemucs'},{origine:'database',modello:''}];
out.origine = righe.map(origineStem);
console.log(JSON.stringify(out));
""" % (json.dumps([n for n, _ in CASI_NOME]),
       json.dumps(["canzone - Violino.mp3", "vocals.wav", "note.txt", "senza_estensione"]))
        cls.risultati = esegui_js(js)

    def test_stessa_regola_della_python(self):
        # è il punto della richiesta: la regola della pagina e quella dell'app
        # devono dare la STESSA etichetta, caso per caso
        for nome, atteso in CASI_NOME:
            with self.subTest(nome=nome):
                self.assertEqual(self.risultati["etichette"][nome], atteso)
                self.assertEqual(self.risultati["etichette"][nome],
                                 APP.strumento_da_nomefile(nome))

    def test_quali_file_sono_audio(self):
        self.assertEqual(self.risultati["audio"],
                         {"canzone - Violino.mp3": True, "vocals.wav": True,
                          "note.txt": False, "senza_estensione": False})

    def test_da_dove_arriva_la_traccia(self):
        self.assertEqual(self.risultati["origine"],
                         ["caricata a mano", "separata con Demucs",
                          "cartella di Demucs", "dal database"])


class TestCablaggio(unittest.TestCase):
    """Rotte, pagina /scheda e pannello ✏️ Rinomina in massa."""

    @classmethod
    def setUpClass(cls):
        cls.pagina = leggi(PAGINA_PATH)
        cls.index = leggi(INDEX_PATH)
        with open(APP_PATH, encoding="utf-8") as fh:
            cls.app = fh.read()

    def test_rotte_dellapp(self):
        self.assertIn('@app.route("/db/songs/<song_id>/stems/import", methods=["POST"])', self.app)
        self.assertIn("def import_stems(song_id):", self.app)
        self.assertIn('@app.route("/db/stems/<session_id>", methods=["DELETE"])', self.app)
        self.assertIn("def delete_stem_session(session_id):", self.app)

    def test_il_mass_renamer_e_lo_stesso_pannello(self):
        # campo consentito in piu' accanto ai BULK_FIELDS, stessa strada di Undo
        self.assertIn('STEM_LABEL_FIELD = "stem_type"', self.app)
        self.assertIn("if field == STEM_LABEL_FIELD:", self.app)
        self.assertIn("def _mass_rename_etichette_stem(find, replace):", self.app)
        self.assertIn("UPDATE stem_tracks SET stem_type=? WHERE id=?", self.app)
        m = re.search(r"def _mass_rename_etichette_stem.*?\n\n\n", self.app, re.S)
        self.assertIsNotNone(m)
        self.assertIn("push_undo(", m.group(0), "la rinomina delle etichette deve essere annullabile")

    def test_opzione_nel_pannello_della_pagina(self):
        self.assertIn('<option value="stem_type"', self.index)
        self.assertIn("Etichetta stem", self.index)

    def test_selettore_di_cartella_in_scheda(self):
        for pezzo in ('id="stem-input"', "webkitdirectory", 'id="stem-drop"',
                      'id="stem-anteprima"', "+'/stems/import'", "salvaStemManuali"):
            with self.subTest(pezzo=pezzo):
                self.assertIn(pezzo, self.pagina)

    def test_pulsante_nella_tabella_del_database(self):
        self.assertIn('href="/scheda?song=${encodeURIComponent(s.id)}#card-stem"', self.index)
        self.assertIn("📂 Stem", self.index)

    def test_handler_esposti_su_window(self):
        # dentro la funzione anonima di scheda.html gli handler scritti nell'HTML
        # non si vedono: devono stare tutti in Object.assign(window,{…})
        m = re.search(r"Object\.assign\(window,\{([^}]*)\}", self.pagina)
        self.assertIsNotNone(m)
        for nome in ("apriSceltaStem", "stemScelti", "svuotaAnteprimaStem", "salvaStemManuali",
                     "stemDragOver", "stemDragLeave", "stemDrop"):
            with self.subTest(handler=nome):
                self.assertIn(nome, m.group(1), "manca window.%s" % nome)
                self.assertRegex(self.pagina, r"(?:async\s+)?function\s+%s\s*\(" % re.escape(nome))



def _conteggi_db():
    """(canzoni, sessioni, tracce): per controllare che il test non lasci residui."""
    conn = sqlite3.connect(DB_PATH, timeout=10)
    try:
        return tuple(conn.execute("SELECT (SELECT COUNT(*) FROM songs), "
                                  "(SELECT COUNT(*) FROM stem_sessions), "
                                  "(SELECT COUNT(*) FROM stem_tracks)").fetchone())
    finally:
        conn.close()


def _tracce_di(session_id):
    conn = sqlite3.connect(DB_PATH, timeout=10)
    conn.row_factory = sqlite3.Row
    try:
        return [dict(r) for r in conn.execute(
            "SELECT * FROM stem_tracks WHERE session_id=? ORDER BY file_path", (session_id,))]
    finally:
        conn.close()


def _esegui_sql(sql, parametri=()):
    conn = sqlite3.connect(DB_PATH, timeout=10)
    conn.row_factory = sqlite3.Row
    try:
        righe = [dict(r) for r in conn.execute(sql, parametri)]
        conn.commit()
        return righe
    finally:
        conn.close()


@unittest.skipUnless(app_is_up(SAMPLELAB_URL), "app non attiva su %s" % SAMPLELAB_URL)
class TestImportVivo(unittest.TestCase):
    """Il giro completo sull'app viva, su una canzone di prova usa-e-getta."""

    @classmethod
    def setUpClass(cls):
        cls.prima = _conteggi_db()
        cls.song_id = "song_teststem%s" % uuid.uuid4().hex[:8]
        cls.cartella = os.path.join(STEMS_DIR, "caricati_%s" % cls.song_id.replace("song_", ""))
        _esegui_sql("INSERT INTO songs(id,title,artist,local_file,created_at) "
                    "VALUES(?,?,?,'',datetime('now'))",
                    (cls.song_id, "Test stem import", "SampleLab test"))
        # i numeri ATTESI durante la prova: una canzone in più (quella di prova),
        # le sessioni e le tracce di stem della libreria invariate
        cls.atteso_durante_la_prova = (cls.prima[0] + 1, cls.prima[1], cls.prima[2])

    @classmethod
    def tearDownClass(cls):
        # qualunque cosa sia successo, la canzone di prova e i suoi file spariscono
        _esegui_sql("DELETE FROM stem_tracks WHERE session_id IN "
                    "(SELECT id FROM stem_sessions WHERE song_id=?)", (cls.song_id,))
        _esegui_sql("DELETE FROM stem_sessions WHERE song_id=?", (cls.song_id,))
        _esegui_sql("DELETE FROM songs WHERE id=?", (cls.song_id,))
        shutil.rmtree(cls.cartella, ignore_errors=True)

    def test_validazioni(self):
        stato, r = http_carica_stem(self.song_id, [])
        self.assertEqual(stato, 400)
        self.assertIn("Nessun file", r.get("error", ""))

        stato, r = http_carica_stem("song_inesistente", [("Canzone - Violino.mp3", b"x")])
        self.assertEqual(stato, 404)

        stato, r = http_json("/db/mass_rename", {"field": "stem_type", "find": ""})
        self.assertEqual(stato, 400)
        self.assertIn("find richiesto", r.get("error", ""))

        stato, r = http_json("/db/mass_rename", {"field": "stem", "find": "x"})
        self.assertEqual(stato, 400)
        self.assertIn("stem_type", r.get("error", ""),
                      "il campo consentito va detto nel messaggio")

    def test_sessioni_e_tracce_della_canzone(self):
        # la canzone di prova non ha nessuno stem: la scheda lo dice
        stato, scheda = http_json("/db/songs/%s/scheda" % self.song_id)
        self.assertEqual(stato, 200)
        self.assertEqual(scheda["counts"]["stem_tracks"], 0)
        self.assertEqual(scheda["stems"]["sessions"], [])

    def test_giro_completo(self):
        files = [("canzone - Violino.mp3", b"violino-finto"),
                 ("canzone - Pianoforte.wav", b"pianoforte-finto"),
                 ("note.txt", b"questo non e' audio")]
        stato, res = http_carica_stem(self.song_id, files, etichette=["", "grancassa", ""])
        self.assertEqual(stato, 200, res)
        self.assertTrue(res.get("ok"), res)
        self.assertEqual(res["count"], 2, res)
        self.assertEqual(res["count_skipped"], 1, res)
        self.assertEqual(os.path.basename(self.cartella), res["folder"])
        session_id = res["session_id"]
        try:
            # 1) le etichette: riconosciuta dal nome, oppure corretta a mano
            self.assertEqual({i["stem_type"] for i in res["importati"]}, {"violino", "grancassa"})
            self.assertEqual(res["skipped"][0]["file"], "note.txt")
            # 2) il database: UNA sessione «manuale», una riga per traccia
            sess = _esegui_sql("SELECT * FROM stem_sessions WHERE id=?", (session_id,))[0]
            self.assertEqual(sess["song_id"], self.song_id)
            self.assertEqual(sess["model_name"], "manuale")
            self.assertEqual(sess["status"], "done")
            tracce = _tracce_di(session_id)
            self.assertEqual(len(tracce), 2)
            self.assertEqual({t["stem_type"] for t in tracce}, {"violino", "grancassa"})
            self.assertTrue(all(t["file_size_bytes"] > 0 for t in tracce))
            # 3) i file sono nella cartella della canzone (quella che legge la scheda)
            self.assertTrue(os.path.isdir(self.cartella), self.cartella)
            self.assertEqual(sorted(os.listdir(self.cartella)),
                             ["canzone - Pianoforte.wav", "canzone - Violino.mp3"])
            # 4) la scheda della canzone li mostra, col modello «manuale»
            stato, scheda = http_json("/db/songs/%s/scheda" % self.song_id)
            self.assertEqual(stato, 200)
            self.assertEqual(scheda["counts"]["stem_tracks"], 2)
            self.assertEqual(scheda["counts"]["stem_sessions"], 1)
            sessione = scheda["stems"]["sessions"][0]
            self.assertEqual(sessione["model_name"], "manuale")
            self.assertEqual({t["stem_type"] for t in sessione["tracks"]}, {"violino", "grancassa"})
            self.assertTrue(all(t["exists"] for t in sessione["tracks"]))
            # 5) ricaricare la stessa cartella NON crea doppioni: aggiorna le tracce
            stato, res2 = http_carica_stem(self.song_id, files, etichette=["", "grancassa", ""])
            self.assertEqual(stato, 200)
            self.assertEqual(res2["session_id"], session_id)
            self.assertEqual({i["azione"] for i in res2["importati"]}, {"aggiornata"})
            self.assertEqual({i["track_id"] for i in res2["importati"]},
                             {i["track_id"] for i in res["importati"]})
            self.assertEqual(len(_tracce_di(session_id)), 2)
            # 6) ✏️ Rinomina in massa sulle ETICHETTE (stesso pannello, stesse regole)
            stato, rinomina = http_json("/db/mass_rename", {"field": "stem_type",
                                                            "find": "grancassa",
                                                            "replace": "pianoforte"})
            self.assertEqual(stato, 200, rinomina)
            self.assertEqual(rinomina["count"], 1)
            self.assertEqual(rinomina["updated"][0]["old"], "grancassa")
            self.assertEqual(rinomina["updated"][0]["new"], "pianoforte")
            self.assertEqual(rinomina["updated"][0]["file"], "canzone - Pianoforte.wav")
            self.assertEqual({t["stem_type"] for t in _tracce_di(session_id)},
                             {"violino", "pianoforte"})
            # 7) …e ↩️ Undo la rimette com'era (lo stesso ciclo di Undo degli altri strumenti)
            stato, undo = http_json("/db/undo", {})
            self.assertEqual(stato, 200, undo)
            self.assertIn("grancassa", undo.get("label", ""))
            self.assertEqual({t["stem_type"] for t in _tracce_di(session_id)},
                             {"violino", "grancassa"})
        finally:
            # 8) 🗑 la sessione si cancella: righe via dal database, file in .trash
            stato, cancella = http_json("/db/stems/%s" % session_id, None, method="DELETE")
            self.assertEqual(stato, 200, cancella)
            self.assertEqual(cancella["tracks"], 2)
            self.assertEqual(len(cancella["trash"]), 2)
            self.assertEqual(_tracce_di(session_id), [])
            self.assertEqual(sorted(os.listdir(self.cartella)), [])
            for nome in cancella["trash"]:
                try:
                    os.remove(os.path.join(TRASH_DIR, nome))
                except OSError:
                    pass
            shutil.rmtree(self.cartella, ignore_errors=True)

    def test_nessun_residuo(self):
        # dopo il giro completo il database ha esattamente i numeri di partenza
        # (più la sola canzone di prova): nessuna sessione e nessuna traccia
        # rimasta appesa dopo import, rinominata e cancellazione
        self.assertEqual(_conteggi_db(), self.atteso_durante_la_prova)

