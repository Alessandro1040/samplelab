"""Test del modale «✏️ Modifica info avanzata» del player (/onyx) coi campi del DB.

Richiesta del 18/09/2026 (Alessandro): «in modifica info avanzate dovrebbero
comparire tutte le opzioni del database, lo stesso che compare su "edit" in
database». Il modale del player (menu contestuale di un brano → ✏️ Modifica info
avanzata, funzione `openEditTrackModal`) ha ora lo stesso elenco di campi
dell'editor ✏️ Edit del tab Database (`dbEditFormHTML`), con id `editdb-<campo>`,
e li salva nel database passando dal bridge del player
(`notifyDbTrackUpdated` → postMessage → `applyPlayerTrackToDb` → PUT
/db/songs/<id>).

Cosa copre questo file:
1. il CONFRONTO FRA LE TRE LISTE: i campi del modale (`CAMPI_DB_INFO` in
   onyx_whosampled.html), quelli dell'editor del database (`dbEditFormHTML` e
   `CAMPI_DB_MODALE` in index (2).html) e quelli accettati dal PUT (`allowed` in
   app (2).py) — se una lista cambia, il test dice quale resta indietro;
2. le funzioni pure in JavaScriptCore: `campiDbHTML` (l'HTML dei campi, riempito
   con la riga del DB), `leggiCampiDbDalModale` (i valori scritti nel modale) e
   `payloadDaBranoPlayer` (il corpo del PUT);
3. il messaggio del player al parent (`notifyDbTrackUpdated` con un `window.parent`
   finto): i campi del database devono esserci;
4. il PUT vero su una canzone di prova usa-e-getta (il test non lascia residui:
   la riga viene cancellata).

Esecuzione (dalla cartella di SampleLab):
    python3 -m unittest -v test_onyx_modifica_db
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
import urllib.request
import uuid

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
APP_PATH = os.path.join(BASE_DIR, "app (2).py")
PAGINA_PATH = os.path.join(BASE_DIR, "index (2).html")
ONYX_PATH = os.path.join(BASE_DIR, "onyx_whosampled.html")
DB_PATH = os.path.join(BASE_DIR, "samplelab (2).db")
SAMPLELAB_URL = os.environ.get("SAMPLELAB_URL", "http://localhost:5070")
HA_OSASCRIPT = shutil.which("osascript") is not None

# I campi principali del modale del player (id editTrack*): NON sono in
# CAMPI_DB_INFO perché hanno già la loro casella in cima al modale.
CAMPI_PRINCIPALI = {"title": "editTrackName", "artist": "editTrackArtist",
                    "album": "editTrackAlbum", "year": "editTrackYear",
                    "lyrics": "editTrackLyrics"}


def load_app():
    spec = importlib.util.spec_from_file_location("samplelab_app2_onyxedit", APP_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


APP = load_app()


def leggi(percorso):
    with open(percorso, encoding="utf-8") as fh:
        return fh.read()


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
        raise AssertionError("funzione %s assente" % nome)
    inizio_corpo = src.index("{", m.end() - 1)
    corpo = _blocco(src, m.end() - 1, "{", "}", nome)
    return src[m.start(): inizio_corpo + len(corpo)]


def estrai_lista(src, nome):
    """I nomi di campo da una lista JS `const NOME = ['a','b',…];`."""
    m = re.search(r"const\s+" + re.escape(nome) + r"\s*=\s*\[(.*?)\];", src, re.S)
    if not m:
        raise AssertionError("lista %s assente" % nome)
    return re.findall(r"['\"]([A-Za-z_]\w*)['\"]", m.group(1))


def campi_del_modale_onyx(src=None):
    """I nomi dei campi di CAMPI_DB_INFO (un campo per riga: `['campo', 'Etichetta', …]`)."""
    src = src if src is not None else leggi(ONYX_PATH)
    m = re.search(r"const\s+CAMPI_DB_INFO\s*=\s*\[(.*?)\n\];", src, re.S)
    if not m:
        raise AssertionError("CAMPI_DB_INFO assente in onyx_whosampled.html")
    # solo il PRIMO elemento di ogni riga: dentro le righe ci sono anche i valori
    # dei menu (['analyzed_status', 'Stato analisi', ['none', 'analyzing', …]])
    return re.findall(r"\n\s*\[\s*'([A-Za-z_]\w*)'\s*,", m.group(1))


def campi_dell_editor_db(src=None):
    src = src if src is not None else leggi(PAGINA_PATH)
    return re.findall(r"(?:inp|ta|sel|chk)\(\s*'([A-Za-z_]\w*)'", estrai_funzione(src, "dbEditFormHTML"))


def campi_ammessi_dal_put(src=None):
    if src is None:
        with open(APP_PATH, encoding="utf-8") as fh:
            src = fh.read()
    m = re.search(r"def db_update_song\(song_id\):.*?allowed\s*=\s*\[(.*?)\]", src, re.S)
    if not m:
        raise AssertionError("la lista `allowed` del PUT non si trova in app (2).py")
    return re.findall(r"\"([A-Za-z_]\w*)\"", m.group(1))


def esegui_js(codice, nome_file="/tmp/test_onyx_modifica_db.js"):
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


# ── la riga di prova per i test in JavaScriptCore ───────────────────────────
RIGA_DB = {
    "id": "song_prova", "title": "Titolo", "artist": "Artista", "album": "Album",
    "album_artist": "Artista Album", "composer": "Compositore", "producers": '["A", "B"]',
    "genre": "Hip Hop", "year": 2009, "release_date": "2009-11-03", "track_number": 4,
    "disc_number": 1, "compilation": 1, "rating": 5, "bpm": 92.5, "musical_key": "C min",
    "play_count": 12, "duration": 235.24, "analyzed_status": "done",
    "youtube_url": "https://youtu.be/x", "genius_url": "https://genius.com/x",
    "whosampled_url": "https://whosampled.com/x/", "tunebat_url": "https://tunebat.com/x",
    "cover_art_path": "song_prova.jpg", "local_file": "File - Prova.mp3",
    "comment": "nota con \"virgolette\"", "title_verified": 1, "artist_verified": 0,
    "bpm_verified": 1, "key_verified": 0, "lyrics_verified": 1,
}


class TestListeDeiCampi(unittest.TestCase):
    """Le liste dei campi devono restare allineate: modale /onyx ↔ editor DB ↔ PUT."""

    @classmethod
    def setUpClass(cls):
        cls.pagina = leggi(PAGINA_PATH)
        cls.onyx = leggi(ONYX_PATH)
        cls.modale = campi_del_modale_onyx(cls.onyx)
        cls.editor = campi_dell_editor_db(cls.pagina)
        cls.percorso = estrai_lista(cls.pagina, "CAMPI_DB_MODALE")
        cls.put = campi_ammessi_dal_put()

    def test_il_modale_ha_tutti_i_campi_dell_editor(self):
        # gli stessi campi dell'editor ✏️ Edit, meno quelli che il modale ha già
        # in cima con un'altra casella (titolo, artista, album, anno, testo)
        attesi = [c for c in self.editor if c not in CAMPI_PRINCIPALI]
        self.assertEqual(self.modale, attesi,
                         "i campi del modale (/onyx) e dell'editor del Database non coincidono")

    def test_il_percorso_nella_pagina_li_conosce_tutti(self):
        self.assertEqual(sorted(self.percorso), sorted(self.modale),
                         "CAMPI_DB_MODALE (index) e CAMPI_DB_INFO (/onyx) devono avere gli stessi campi")

    def test_il_put_accetta_tutti_i_campi_dell_editor(self):
        for campo in self.editor:
            with self.subTest(campo=campo):
                self.assertIn(campo, self.put,
                              "il PUT /db/songs/<id> non accetta «%s»: il modale lo manderebbe a vuoto" % campo)

    def test_i_campi_principali_restano_nel_modale(self):
        for campo, id_atteso in CAMPI_PRINCIPALI.items():
            with self.subTest(campo=campo):
                self.assertIn('id="%s"' % id_atteso, self.onyx)
                self.assertNotIn(campo, self.modale, "«%s» ha già la sua casella principale" % campo)

    def test_il_modale_ha_il_contenitore_e_la_nota(self):
        self.assertIn('id="editTrackDbFields"', self.onyx)
        self.assertIn("CAMPI DEL DATABASE", self.onyx)
        self.assertIn("gli stessi di ✏️ Edit nel tab Database", self.onyx)


@unittest.skipUnless(HA_OSASCRIPT, "serve osascript (JavaScriptCore)")
class TestFunzioniDelModale(unittest.TestCase):
    """Le funzioni pure del modale e del ponte col database, eseguite davvero."""

    risultati = {}

    @classmethod
    def setUpClass(cls):
        pagina = leggi(PAGINA_PATH)
        onyx = leggi(ONYX_PATH)
        lista_onyx = re.search(r"const\s+CAMPI_DB_INFO\s*=\s*\[.*?\n\];", onyx, re.S).group(0)
        js = "\n".join([
            estrai_funzione(onyx, "escHtml"),
            lista_onyx,
            # `campiDbHTML` chiama questo per i comandi della copertina (📂 🎬 📁 🗑)
            estrai_funzione(onyx, "coverControlsHTML"),
            estrai_funzione(onyx, "campiDbHTML"),
            estrai_funzione(onyx, "leggiCampiDbDalModale"),
            estrai_funzione(onyx, "notifyDbTrackUpdated"),
            "const CAMPI_DB_MODALE = %s;" % json.dumps(estrai_lista(pagina, "CAMPI_DB_MODALE")),
            estrai_funzione(pagina, "payloadDaBranoPlayer"),
        ])
        js += """
globalThis.window = { self: {}, top: {}, parent: { postMessage: (m) => { globalThis.__msg = m; } } };
const RIGA = %s;
const out = {};
const html = campiDbHTML(RIGA);
out.quanti = (html.match(/id="editdb-/g) || []).length;
out.campi = CAMPI_DB_INFO.map(c => c[0]);
out.valoreInput = (/id="editdb-genre"[^>]*value="([^"]*)"/.exec(html) || [])[1];
out.valoreArea = (/id="editdb-comment"[^>]*>([^<]*)</.exec(html) || [])[1];
out.escapeArea = html.indexOf('&quot;virgolette&quot;') >= 0;
out.compilationSi = /value="1" selected>Compilation: Sì/.test(html);
out.statoDone = /id="editdb-analyzed_status"[\\s\\S]*?<option value="done" selected>/.test(html);
out.veriZero = (html.match(/value="0" selected/g) || []).length;
const finto = {};
CAMPI_DB_INFO.forEach(c => { finto['editdb-' + c[0]] = { value: 'v-' + c[0] }; });
out.letti = leggiCampiDbDalModale({ getElementById: (id) => finto[id] || null });
out.lettiParziale = leggiCampiDbDalModale({ getElementById: (id) => (id === 'editdb-bpm' ? { value: '99' } : null) });
notifyDbTrackUpdated({ dbSongId: 'song_x', name: 'Nuovo', artist: 'Art', localFile: 'f.mp3',
                       db_fields: out.letti }, 'vecchio', 'art');
out.messaggio = (globalThis.__msg || {}).action;
out.messaggioTitolo = ((globalThis.__msg || {}).track || {}).title;
out.messaggioCampi = ((globalThis.__msg || {}).track || {}).db_fields || {};
out.payload = payloadDaBranoPlayer({ dbSongId: 'song_x', title: 'T', artist: 'A',
  db_fields: { bpm: '92', musical_key: 'C min', title_verified: '1', sconosciuto: 'x' } });
out.payloadVuoto = payloadDaBranoPlayer({ db_fields: { comment: '' } });
out.payloadNullo = payloadDaBranoPlayer({ db_fields: { comment: null, genre: 'Rap' } });
console.log(JSON.stringify(out));
""" % json.dumps(RIGA_DB)
        cls.risultati = esegui_js(js)

    def test_un_campo_per_ogni_voce_della_lista(self):
        self.assertEqual(self.risultati["quanti"], len(self.risultati["campi"]))
        self.assertEqual(len(self.risultati["campi"]), 27)

    def test_i_valori_del_database_finiscono_nel_modale(self):
        self.assertEqual(self.risultati["valoreInput"], "Hip Hop")
        # nell'HTML i valori sono scappati (il browser li mostra normali: è quello
        # che fa la prova «escapeArea»)
        self.assertEqual(self.risultati["valoreArea"], 'nota con &quot;virgolette&quot;')
        self.assertTrue(self.risultati["escapeArea"], "le virgolette vanno scappate")
        self.assertTrue(self.risultati["compilationSi"])
        self.assertTrue(self.risultati["statoDone"])
        self.assertEqual(self.risultati["veriZero"], 2,
                         "artist_verified e key_verified sono a 0: il select deve dirlo")

    def test_lettura_dal_modale(self):
        letti = self.risultati["letti"]
        self.assertEqual(sorted(letti), sorted(self.risultati["campi"]))
        self.assertEqual(letti["bpm"], "v-bpm")
        self.assertEqual(self.risultati["lettiParziale"], {"bpm": "99"})

    def test_il_messaggio_porta_i_campi_del_database(self):
        self.assertEqual(self.risultati["messaggio"], "dbTrackUpdated")
        self.assertEqual(self.risultati["messaggioTitolo"], "Nuovo")
        self.assertEqual(self.risultati["messaggioCampi"]["bpm"], "v-bpm",
                         "i campi del modale devono arrivare al parent")

    def test_il_corpo_del_put(self):
        payload = self.risultati["payload"]
        self.assertEqual(payload["title"], "T")
        self.assertEqual(payload["bpm"], "92")
        self.assertEqual(payload["musical_key"], "C min")
        self.assertEqual(payload["title_verified"], "1")
        self.assertNotIn("sconosciuto", payload, "i campi fuori lista non si mandano")
        # un campo svuotato a mano si può svuotare; uno mai letto (null) no
        self.assertEqual(self.risultati["payloadVuoto"], {"comment": ""})
        self.assertEqual(self.risultati["payloadNullo"], {"genre": "Rap"})


def _quante_canzoni():
    conn = sqlite3.connect(DB_PATH, timeout=10)
    try:
        return conn.execute("SELECT COUNT(*) FROM songs").fetchone()[0]
    finally:
        conn.close()


def _uguali(a, b):
    """Confronto tollerante: 4 e 4.0 sono lo stesso valore (le colonne sono REAL)."""
    try:
        return abs(float(a) - float(b)) < 1e-9
    except (TypeError, ValueError):
        return str(a) == str(b)


@unittest.skipUnless(app_is_up(SAMPLELAB_URL), "app non attiva su " + SAMPLELAB_URL)
class TestPutDeiCampiDelModale(unittest.TestCase):
    """Il PUT vero coi campi del modale, su una canzone di prova usa-e-getta."""

    @classmethod
    def setUpClass(cls):
        cls.prima = _quante_canzoni()
        cls.song_id = "song_testonyx" + uuid.uuid4().hex[:8]
        conn = sqlite3.connect(DB_PATH, timeout=10)
        try:
            conn.execute("INSERT INTO songs(id,title,artist,created_at) "
                         "VALUES(?,?,?,datetime('now'))",
                         (cls.song_id, "Test modale onyx", "SampleLab test"))
            conn.commit()
        finally:
            conn.close()

    @classmethod
    def tearDownClass(cls):
        conn = sqlite3.connect(DB_PATH, timeout=10)
        try:
            conn.execute("DELETE FROM songs WHERE id=?", (cls.song_id,))
            conn.commit()
        finally:
            conn.close()

    def test_campi_fuori_lista_ignorati(self):
        stato, res = http_json("/db/songs/%s" % self.song_id,
                               {"pincopallo": "x", "genre": "Rap"}, method="PUT")
        self.assertEqual(stato, 200, res)
        self.assertEqual(res.get("genre"), "Rap")
        self.assertNotIn("pincopallo", res)

    def test_tutti_i_campi_del_modale_arrivano_nel_database(self):
        payload = {c: ("valore " + c) for c in campi_del_modale_onyx()}
        payload.update({"compilation": 1, "rating": 4, "bpm": 92.5, "play_count": 7,
                        "duration": 200.5, "track_number": 3, "disc_number": 1,
                        "analyzed_status": "done", "title_verified": 1, "artist_verified": 1,
                        "bpm_verified": 1, "key_verified": 1, "lyrics_verified": 1})
        stato, res = http_json("/db/songs/%s" % self.song_id, payload, method="PUT")
        self.assertEqual(stato, 200, res)
        self.assertEqual(res.get("id"), self.song_id)
        for campo, valore in payload.items():
            with self.subTest(campo=campo):
                self.assertTrue(_uguali(res.get(campo), valore),
                                "%s: nel DB c'è %r invece di %r" % (campo, res.get(campo), valore))
        # rileggendo la riga i valori ci sono ancora (sono nel database, non solo nella risposta)
        stato, riga = http_json("/db/songs/%s" % self.song_id)
        self.assertEqual(stato, 200)
        for campo, valore in payload.items():
            with self.subTest(campo=campo, dove="rilettura"):
                self.assertTrue(_uguali(riga.get(campo), valore),
                                "%s: nel DB c'è %r invece di %r" % (campo, riga.get(campo), valore))

    def test_nessun_residuo(self):
        # solo la canzone di prova: nessun'altra riga creata o cancellata
        self.assertEqual(_quante_canzoni(), self.prima + 1)




