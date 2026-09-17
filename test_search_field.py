"""Test della ricerca del player (`branoCorrisponde` in `onyx_whosampled.html`).

Richiesta del 17/09/2026: nella barra «Cerca» del player l'utente deve poter
scegliere **su cosa** cercare — un titolo, un artista, un album, un anno o
un'altra informazione (genere, compositore, BPM, tonalità, commento, testo,
nome file) — invece di cercare sempre e solo in titolo+artista. La scelta è la
tendina accanto alla barra, costruita dalla costante `SEARCH_FIELDS` della
pagina (unica fonte: tendina e filtro non possono divergere).

Perché conta: in libreria i titoli hanno l'apostrofo **tipografico**
(«If I Can’t», «Nuttin’ To Do») e i BPM la **virgola** italiana; la ricerca
normalizza accenti e punteggiatura, quindi trova il brano anche scrivendo
"if i cant" o "61,5". Su «Tutto» più parole scritte (es. "50 cent 2003")
devono comparire tutte, anche su campi diversi e in qualsiasi ordine.

Due gruppi di test:
1. `TestCampiRicerca` — controlli Python sul cablaggio: i campi della tendina
   esistono davvero nel modello del brano della pagina (un refuso tipo "key"
   invece di "musical_key" non passerebbe), la tendina è vuota nell'HTML e
   viene costruita da `SEARCH_FIELDS`, il filtro usa la funzione pura.
2. `TestBranoCorrisponde` — la funzione **estratta dalla pagina ed eseguita
   davvero** con JavaScriptCore (`osascript -l JavaScript`), senza browser.

Esecuzione (dalla cartella di SampleLab):
    python3 -m unittest -v test_search_field
"""
import json
import os
import re
import shutil
import subprocess
import unittest

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PAGINA = os.path.join(BASE_DIR, "onyx_whosampled.html")
HA_OSASCRIPT = shutil.which("osascript") is not None

# ── brani di prova (campi come nel modello `const track = {…}` della pagina) ──
TRACK_50 = {
    "id": "song_if", "name": "If I Can’t", "artist": "50 Cent",
    "album": "Get Rich or Die Tryin’", "album_artist": "50 Cent", "year": 2003,
    "genre": "Hip-Hop", "composer": "50 Cent, Dr. Dre, Mike Elizondo",
    "bpm": 103.4, "musical_key": "A Minor", "comment": "",
    "lyrics": "[Verse 1: 50 Cent]\nIf I can't do it, then I'ma boom",
    "localFile": "50 Cent - If I Cant [z5zz7GHU4ec].mp3",
    "_origName": "50 Cent - If I Cant.mp3",
}
TRACK_LOCALE = {
    "id": "song_locale", "name": "Beat", "artist": "Raedius", "album": "",
    "album_artist": "", "year": "", "genre": "", "composer": "", "bpm": "",
    "musical_key": "", "comment": "da sistemare a mano", "lyrics": "",
    "localFile": "onyx_t_1786610656293_oo1tb.monkey see monkey do.mp3",
    "_origName": "monkey see monkey do mashup.mp3",
}
TRACK_ACCENTI = {
    "id": "song_acc", "name": "Café Chantant", "artist": "Édith Piaf",
    "album": "Álbum", "album_artist": "Édith Piaf", "year": 1954,
    "genre": "Chanson", "composer": "Norbert Glanzberg", "bpm": 88,
    "musical_key": "C Major", "comment": "",
    "lyrics": "Quand il me prend dans ses bras",
    "localFile": "Édith Piaf - Café Chantant.mp3", "_origName": "",
}
TRACK_ALBUM_ARTIST = {
    "id": "song_aa", "name": "Stan", "artist": "Dido",
    "album": "The Marshall Mathers LP", "album_artist": "Eminem", "year": 2000,
    "genre": "", "composer": "", "bpm": "", "musical_key": "", "comment": "",
    "lyrics": "", "localFile": "", "_origName": "",
}
TRACKS = {
    "cinquanta": TRACK_50, "locale": TRACK_LOCALE,
    "accenti": TRACK_ACCENTI, "album_artist": TRACK_ALBUM_ARTIST,
}

# nome del caso, brano, campo scelto nella tendina, testo scritto, atteso
CASI = [
    # titolo: apostrofo tipografico / dritto / assente, maiuscole
    ("titolo_apostrofo_tipografico", "cinquanta", "name", "cant", True),
    ("titolo_apostrofo_dritto", "cinquanta", "name", "can't", True),
    ("titolo_apostrofo_tipografico_nella_query", "cinquanta", "name", "can’t", True),
    ("titolo_maiuscole", "cinquanta", "name", "IF I CANT", True),
    ("titolo_parola_assente", "cinquanta", "name", "pilot", False),
    ("titolo_non_guarda_l_anno", "cinquanta", "name", "2003", False),
    # artista
    ("artista", "cinquanta", "artist", "50 cent", True),
    ("artista_non_cerca_nel_titolo", "cinquanta", "artist", "cant", False),
    # album (apostrofo tipografico)
    ("album_senza_apostrofo", "cinquanta", "album", "get rich or die tryin", True),
    ("album_con_apostrofo_tipografico", "cinquanta", "album", "Die Tryin’", True),
    # artista dell'album, che può essere diverso dall'artista del brano
    ("artista_album", "album_artist", "album_artist", "eminem", True),
    ("artista_album_non_e_l_artista", "album_artist", "artist", "eminem", False),
    # anno (campo numerico: si cerca per cifre)
    ("anno_esatto", "cinquanta", "year", "2003", True),
    ("anno_parziale", "cinquanta", "year", "20", True),
    ("anno_sbagliato", "cinquanta", "year", "1999", False),
    # BPM: virgola italiana, punto e intero
    ("bpm_virgola_italiana", "cinquanta", "bpm", "103,4", True),
    ("bpm_punto", "cinquanta", "bpm", "103.4", True),
    ("bpm_intero", "cinquanta", "bpm", "103", True),
    ("bpm_sbagliato", "cinquanta", "bpm", "61", False),
    # tonalità, genere, compositore, commento
    ("tonalita", "cinquanta", "musical_key", "a minor", True),
    ("genere_con_trattino", "cinquanta", "genre", "hip hop", True),
    ("genere_sbagliato", "cinquanta", "genre", "rock", False),
    ("compositore", "cinquanta", "composer", "dr dre", True),
    ("commento", "locale", "comment", "sistemare", True),
    ("commento_non_cerca_nei_dati_altrui", "cinquanta", "comment", "50 cent", False),
    # testo del brano
    ("testo_due_parole", "cinquanta", "lyrics", "do it", True),
    ("testo_parola_assente", "cinquanta", "lyrics", "lose yourself", False),
    # nome file: id del video YouTube e nome originale del file
    ("nome_file_id_youtube", "cinquanta", "file", "z5zz7ghu4ec", True),
    ("nome_file_originale", "locale", "file", "monkey see monkey do mashup", True),
    # accenti
    ("accenti_query_senza_accenti", "accenti", "artist", "edith piaf", True),
    ("accenti_query_con_accenti", "accenti", "name", "café", True),
    ("accenti_titolo_senza_accenti", "accenti", "name", "cafe chantant", True),
    # «Tutto»: più parole anche su campi diversi, in qualsiasi ordine
    ("tutto_parole_su_campi_diversi", "cinquanta", "all", "50 cent 2003", True),
    ("tutto_ordine_libero", "cinquanta", "all", "2003 cant", True),
    ("tutto_titolo_e_album", "cinquanta", "all", "cant die tryin", True),
    ("tutto_guarda_il_testo", "cinquanta", "all", "do it", True),
    ("tutto_guarda_il_nome_file", "cinquanta", "all", "z5zz7ghu4ec", True),
    ("tutto_manca_una_parola", "cinquanta", "all", "50 cent eminem", False),
    ("tutto_artista_album_e_titolo", "album_artist", "all", "eminem stan", True),
    # casi limite: query vuota, campo inesistente, brano mancante
    ("query_vuota_mostra_tutto", "cinquanta", "all", "", True),
    ("query_solo_spazi", "cinquanta", "name", "   ", True),
    ("campo_sconosciuto", "cinquanta", "pippo", "cant", False),
    ("brano_mancante", None, "all", "cant", False),
    ("brano_mancante_query_vuota", None, "all", "", True),
]

# Campi del modello del brano che la tendina deve poter cercare: serve per
# accorgersi se un campo sparisce o cambia nome (`musical_key`, non `key`).
CAMPI_TRACCIA_RICHIESTI = ["name", "artist", "album", "album_artist", "year",
                           "genre", "composer", "bpm", "musical_key",
                           "comment", "lyrics"]

def leggi_pagina():
    with open(PAGINA, encoding="utf-8") as fh:
        return fh.read()


def _estrai_blocco(src, inizio, apri, chiudi, cosa):
    """Dal primo `apri` dopo `inizio` al `chiudi` che lo bilancia."""
    i = src.index(apri, inizio)
    liv, j = 0, i
    while j < len(src):
        if src[j] == apri:
            liv += 1
        elif src[j] == chiudi:
            liv -= 1
            if liv == 0:
                return src[i:j + 1], i, j
        j += 1
    raise AssertionError("parentesi non bilanciate in %s" % cosa)


def estrai_funzione(src, nome):
    """Il testo della funzione `nome`, graffe bilanciate (come in test_sampler_tap)."""
    m = re.search(r"(?:async\s+)?function\s+" + re.escape(nome) + r"\s*\(", src)
    if not m:
        raise AssertionError("funzione %s assente in %s" % (nome, PAGINA))
    _corpo, _i, j = _estrai_blocco(src, m.end() - 1, "{", "}", nome)
    return src[m.start():j + 1]


def estrai_array(src, nome):
    """Il testo dell'array `const nome = [ … ];` (quadre bilanciate)."""
    m = re.search(r"const\s+" + re.escape(nome) + r"\s*=\s*\[", src)
    if not m:
        raise AssertionError("costante %s assente in %s" % (nome, PAGINA))
    return _estrai_blocco(src, m.end() - 1, "[", "]", nome)[0]


def estrai_blocco_traccia(src):
    """L'oggetto `const track = { … }` della pagina (il modello del brano)."""
    m = re.search(r"const\s+track\s*=\s*\{", src)
    if not m:
        raise AssertionError("costante track assente in %s" % PAGINA)
    return _estrai_blocco(src, m.end() - 1, "{", "}", "track")[0]


class TestCampiRicerca(unittest.TestCase):
    """Cablaggio fra tendina, costanti e filtro (senza eseguire JavaScript)."""

    @classmethod
    def setUpClass(cls):
        cls.src = leggi_pagina()
        cls.array = estrai_array(cls.src, "SEARCH_FIELDS")
        cls.campi = re.findall(r'value:\s*"([^"]+)"', cls.array)
        cls.tutti = re.findall(r'"([^"]+)"', estrai_array(cls.src, "SEARCH_FIELDS_ALL"))

    def test_tendina_costruita_da_search_fields(self):
        # nell'HTML la <select> è vuota: le opzioni arrivano dalla costante
        m = re.search(r"<select[^>]*id=\"searchField\"[^>]*>(.*?)</select>", self.src, re.S)
        self.assertIsNotNone(m, 'manca la <select id="searchField"> nella barra Cerca')
        self.assertEqual(m.group(1).strip(), "", "le opzioni non vanno scritte a mano nell'HTML")
        self.assertIn("sel.innerHTML = SEARCH_FIELDS.map", self.src,
                      "la tendina deve essere costruita da SEARCH_FIELDS")

    def test_tendina_inizializzata_all_avvio(self):
        self.assertRegex(self.src, r"(?m)^initSearchFieldUI\(\);",
                         "initSearchFieldUI() deve girare all'avvio della pagina")
        self.assertIn('onchange="onSearchFieldChange()"', self.src,
                      "il cambio di campo deve rileggere i risultati")

    def test_campi_della_tendina_esistono_nel_modello_del_brano(self):
        modello = set(re.findall(r"^\s*([A-Za-z_][A-Za-z0-9_]*)\s*:",
                                 estrai_blocco_traccia(self.src), re.M))
        for campo in self.campi:
            if campo in ("all", "file"):   # «all» = tutti i campi, «file» = localFile + _origName
                continue
            self.assertIn(campo, modello,
                          "il campo «%s» della tendina non esiste nel brano costruito dalla pagina" % campo)
        for campo in CAMPI_TRACCIA_RICHIESTI:
            self.assertIn(campo, self.campi, "«%s» non è più cercabile dalla tendina" % campo)

    def test_ogni_voce_ha_etichetta_e_segnaposto(self):
        self.assertEqual(len(self.campi), len(set(self.campi)), "campi duplicati nella tendina")
        for chiave in ("label", "placeholder"):
            self.assertEqual(len(re.findall(r"%s:\s*\"[^\"]+\"" % chiave, self.array)), len(self.campi),
                             "ogni voce della tendina deve avere %s" % chiave)
        self.assertEqual(self.campi[0], "all", "la voce predefinita deve essere «Tutto»")

    def test_tutto_copre_tutti_i_campi(self):
        attesi = [c for c in self.campi if c not in ("all", "file")] + ["file"]
        self.assertEqual(sorted(self.tutti), sorted(attesi),
                         "SEARCH_FIELDS_ALL deve contenere gli stessi campi della tendina (tranne «all»)")
        self.assertEqual(len(self.tutti), len(set(self.tutti)), "campi duplicati in SEARCH_FIELDS_ALL")

    def test_il_filtro_usa_la_funzione_pura(self):
        corpo = estrai_funzione(self.src, "visibleTracks")
        self.assertIn("branoCorrisponde(t, field, q)", corpo,
                      "la ricerca del player deve passare da branoCorrisponde")
        self.assertNotIn("t.name.toLowerCase().includes(q) || t.artist.toLowerCase().includes(q)", corpo,
                         "la vecchia ricerca limitata a titolo+artista deve essere sparita")


@unittest.skipUnless(HA_OSASCRIPT, "JavaScriptCore (osascript) non disponibile")
class TestBranoCorrisponde(unittest.TestCase):
    """La funzione della pagina, eseguita davvero, sui casi scritti a mano."""

    risultati = {}

    @classmethod
    def setUpClass(cls):
        src = leggi_pagina()
        js = "\n".join([
            "const SEARCH_FIELDS = %s;" % estrai_array(src, "SEARCH_FIELDS"),
            "const SEARCH_FIELDS_ALL = %s;" % estrai_array(src, "SEARCH_FIELDS_ALL"),
            estrai_funzione(src, "normalizzaRicerca"),
            estrai_funzione(src, "valoreCampoRicerca"),
            estrai_funzione(src, "branoCorrisponde"),
        ])
        casi = [{"nome": n, "track": TRACKS.get(t) if t else None, "field": f, "query": q}
                for (n, t, f, q, _atteso) in CASI]
        js += """
const casi = %s;
const out = {};
for (const c of casi) { out[c.nome] = branoCorrisponde(c.track, c.field, c.query); }
console.log(JSON.stringify(out));
""" % json.dumps(casi)
        f = "/tmp/test_search_field.js"
        with open(f, "w", encoding="utf-8") as out:
            out.write(js + "\n0;\n")
        r = subprocess.run(["osascript", "-l", "JavaScript", f], capture_output=True, text=True)
        testo = ((r.stdout or "") + (r.stderr or "")).strip().splitlines()
        assert testo, "nessun output da JavaScriptCore: %s" % (r.stderr or "")[:200]
        cls.risultati = json.loads(testo[-1])

    def test_esiti_di_tutti_i_casi(self):
        for nome, _track, campo, query, atteso in CASI:
            with self.subTest(caso=nome):
                self.assertIn(nome, self.risultati, "caso non eseguito: %s" % nome)
                self.assertIs(self.risultati[nome], atteso,
                              "«%s» (campo %s, testo «%s») atteso %s" % (nome, campo, query, atteso))

    def test_tutti_i_casi_eseguiti(self):
        self.assertEqual(len(self.risultati), len(CASI))
        self.assertGreaterEqual(len(CASI), 40)


if __name__ == "__main__":
    unittest.main()

