"""Test delle schede di artista e di album del player (`onyx_whosampled.html`).

Richiesta di Alessandro: «quando clicchi compare _Album: Everyday Is Christmas
(Deluxe Edition)_, oppure _Album: Mus_, oppure _Artista: Eminem_ … è
semplicemente brutto: potresti fare due cose diverse per quando uno clicca su un
artista e quando clicca su un album?».

Prima il nome era una riga di testo piatta in alto (`Artista: …` / `Album: …`),
in più l'album segnaposto «Mus» (147 righe in libreria, il nome della cartella di
caricamento) compariva come se fosse un disco vero. Ora `renderHero()` costruisce
due schede **diverse**:
- **artista**: avatar tondo col monogramma + nome grande + «N brani · M album ·
  anni · durata» + una chip per album che porta alla scheda dell'album;
- **album**: cover quadrata in stile vinile (monogramma + gradiente) + artista,
  brani, anno, durata totale, badge «⚠ album segnaposto» quando serve, e nella
  lista i **numeri di traccia** del disco invece della posizione.

Le copertine sono **generate** dal nome (nessun artwork nel database:
`cover_art_path` è vuota su tutte le 890 righe): monogramma + gradiente stabile,
quindi lo stesso artista ha sempre lo stesso colore.

Questo file prova due cose:
1. `TestFunzioniScheda` — le funzioni pure **estratte dalla pagina ed eseguite
   davvero** con JavaScriptCore (`osascript -l JavaScript`): monogramma, tinta e
   gradiente, album segnaposto, durate, intervallo di anni e i due riassunti.
2. `TestCablaggioScheda` — controlli Python: la scheda esiste nell'HTML, le due
   GUI sono diverse (avatar tondo vs cover quadrata), il testo piatto
   «Artista: …»/«Album: …» è sparito, i numeri di traccia si usano nella vista
   album e i clic passano da attributi `data-` (con l'apostrofo — «Stan's
   Tape», «Knoc-Turn'al» — lo schema inline generava JavaScript non valido).

Esecuzione (dalla cartella di SampleLab):
    python3 -m unittest -v test_player_hero
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

# ── valori attesi: monogrammi e tinte (la tinta è un hash stabile) ────────────
MONOGRAMMI = {
    "Eminem": "E",
    "Salmo": "S",
    "The Slim Shady LP": "SS",                       # «The» non conta
    "Stan's Tape": "ST",                             # apostrofo: due parole
    "Everyday Is Christmas (Deluxe Edition)": "EC",
    "Music To Be Murdered By - Side B (Deluxe Edition)": "MB",
    "Marshall Mathers LP": "MM",
    "Knoc-Turn'al": "KT",
    "2001": "2",
    "Adam Ant": "AA",
    "The": "T",                                      # solo parole vuote
    "   ": "♪",
    "": "♪",
}
TINTE = {
    "Eminem": 93, "Salmo": 328, "The Slim Shady LP": 71,
    "Everyday Is Christmas (Deluxe Edition)": 121,
    "Knoc-Turn'al": 119, "Marshall Mathers LP": 264,
    "Music To Be Murdered By - Side B (Deluxe Edition)": 246,
    "Stan's Tape": 296, "": 0,
}

# album segnaposto: il nome della cartella di caricamento o etichette vuote
SEGNAPOSTO = {
    "Mus": True, "mus": True, "  Mus  ": True, "Album sconosciuto": True,
    "Unknown Album": True, "-": True, "": True,
    "Museum": False, "Musica": False, "The Marshall Mathers LP": False,
    "Music To Be Murdered By - Side B (Deluxe Edition)": False,
}

DURATE_ATTESE = {
    "zero": "—", "nullo": "—", "quarantacinque": "1 min", "cinquantanove": "1 min",
    "un_minuto": "1 min", "quarantacinque_min": "45 min", "sotto_ora": "60 min",
    "esatta_ora": "1 h", "ora_e_dodici": "1 h 12 min", "due_ore": "2 h",
    "testo": "3 min", "vuoto": "—",
}

# durate di prova: secondi (o testo) -> etichetta attesa
DURATE = {
    "zero": 0, "nullo": None, "quarantacinque": 45, "cinquantanove": 59,
    "un_minuto": 60, "quarantacinque_min": 2700, "sotto_ora": 3599,
    "esatta_ora": 3600, "ora_e_dodici": 4320, "due_ore": 7200,
    "testo": "180", "vuoto": "",
}

ANNI = {
    "nessuno": [],
    "uno": ["1999"],
    "due": ["1999", "2018"],
    "disordinati": ["2018", "1999"],
    "numeri": [1999, "2000"],
    "ripetuti": ["1999", "1999"],
    "sporchi": ["", "   "],
    "non_numeri": ["abc", "1999"],
}
ANNI_ATTESI = {
    "nessuno": "", "uno": "1999", "due": "1999–2018", "disordinati": "1999–2018",
    "numeri": "1999–2000", "ripetuti": "1999", "sporchi": "", "non_numeri": "1999",
}

BRANI_ARTISTA = [
    {"name": "Stan", "album": "The Marshall Mathers LP", "year": "2000", "dur": 400},
    {"name": "The Real Slim Shady", "album": "The Marshall Mathers LP", "year": "2000", "dur": 260},
    {"name": "Lose Yourself", "album": "8 Mile", "year": "2002", "dur": 326},
    {"name": "Senza album", "album": "", "year": "", "dur": 100},
]
ARTISTA_ATTESO = {
    "n": 4,
    "album": [{"nome": "The Marshall Mathers LP", "n": 2}, {"nome": "8 Mile", "n": 1}],
    "anni": "2000–2002",
    "durata": 1086,
}

BRANI_ALBUM = [
    {"album_artist": "", "artist": "Eminem / D12", "year": "2001", "dur": 300},
    {"album_artist": "Eminem", "artist": "D12", "year": "2001", "dur": 180},
    {"album_artist": "", "artist": "Eminem / D12", "year": "", "dur": "200"},
]
ALBUM_ATTESO = {
    "n": 3, "durata": 680, "anno": "2001", "albumArtista": "Eminem",
    "artisti": ["Eminem", "D12"],
}
BRANI_ALBUM_SENZA_AA = [
    {"artist": "Salmo", "year": "2018", "dur": 200},
    {"artist": "Salmo", "year": "2018", "dur": 100},
]
ALBUM_SENZA_AA_ATTESO = {
    "n": 2, "durata": 300, "anno": "2018", "albumArtista": "", "artisti": ["Salmo"],
}


def leggi_pagina():
    with open(PAGINA, encoding="utf-8") as fh:
        return fh.read()


def _blocco(src, inizio, apri, chiudi, cosa):
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
    m = re.search(r"(?:async\s+)?function\s+" + re.escape(nome) + r"\s*\(", src)
    if not m:
        raise AssertionError("funzione %s assente in %s" % (nome, PAGINA))
    _corpo, _i, j = _blocco(src, m.end() - 1, "{", "}", nome)
    return src[m.start():j + 1]


def estrai_array(src, nome):
    m = re.search(r"const\s+" + re.escape(nome) + r"\s*=\s*\[", src)
    if not m:
        raise AssertionError("costante %s assente in %s" % (nome, PAGINA))
    return _blocco(src, m.end() - 1, "[", "]", nome)[0]


@unittest.skipUnless(HA_OSASCRIPT, "JavaScriptCore (osascript) non disponibile")
class TestFunzioniScheda(unittest.TestCase):
    """Le funzioni della pagina, eseguite davvero, sui casi scritti a mano."""

    risultati = {}

    @classmethod
    def setUpClass(cls):
        src = leggi_pagina()
        js = "\n".join([
            "const HERO_PAROLE_VUOTE = %s;" % estrai_array(src, "HERO_PAROLE_VUOTE"),
            "const ALBUM_SEGNAPOSTO = %s;" % estrai_array(src, "ALBUM_SEGNAPOSTO"),
            estrai_funzione(src, "monogramma"),
            estrai_funzione(src, "tintaDa"),
            estrai_funzione(src, "gradienteDa"),
            estrai_funzione(src, "albumSegnaposto"),
            estrai_funzione(src, "durataEstesa"),
            estrai_funzione(src, "intervalloAnni"),
            estrai_funzione(src, "riassuntoArtista"),
            estrai_funzione(src, "riassuntoAlbum"),
        ])
        js += """
const out = { monogrammi: {}, tinte: {}, gradiente: gradienteDa("Eminem"),
              segnaposto: {}, durate: {}, anni: {},
              artista: riassuntoArtista(%s),
              album: riassuntoAlbum(%s),
              albumSenzaAA: riassuntoAlbum(%s) };
for (const n of %s) { out.monogrammi[n] = monogramma(n); out.tinte[n] = tintaDa(n); }
for (const n of %s) { out.segnaposto[n] = albumSegnaposto(n); }
const durate = %s; for (const k in durate) { out.durate[k] = durataEstesa(durate[k]); }
const anni = %s; for (const k in anni) { out.anni[k] = intervalloAnni(anni[k]); }
console.log(JSON.stringify(out));
""" % (json.dumps(BRANI_ARTISTA), json.dumps(BRANI_ALBUM), json.dumps(BRANI_ALBUM_SENZA_AA),
       json.dumps(list(MONOGRAMMI)), json.dumps(list(SEGNAPOSTO)),
       json.dumps(DURATE), json.dumps(ANNI))
        f = "/tmp/test_player_hero.js"
        with open(f, "w", encoding="utf-8") as out:
            out.write(js + "\n0;\n")
        r = subprocess.run(["osascript", "-l", "JavaScript", f], capture_output=True, text=True)
        testo = ((r.stdout or "") + (r.stderr or "")).strip().splitlines()
        assert testo, "nessun output da JavaScriptCore: %s" % (r.stderr or "")[:200]
        cls.risultati = json.loads(testo[-1])

    def test_monogrammi(self):
        for nome, atteso in MONOGRAMMI.items():
            with self.subTest(nome=nome):
                self.assertEqual(self.risultati["monogrammi"][nome], atteso)

    def test_tinte_stabili_e_nel_range(self):
        for nome, atteso in TINTE.items():
            with self.subTest(nome=nome):
                self.assertEqual(self.risultati["tinte"][nome], atteso)
        for nome, valore in self.risultati["tinte"].items():
            self.assertTrue(0 <= valore < 360, "tinta fuori range per %r: %s" % (nome, valore))

    def test_gradiente_della_cover(self):
        self.assertEqual(self.risultati["gradiente"],
                         "linear-gradient(142deg, hsl(93 58% 44%), hsl(135 62% 16%))")

    def test_album_segnaposto(self):
        for nome, atteso in SEGNAPOSTO.items():
            with self.subTest(nome=nome):
                self.assertIs(self.risultati["segnaposto"][nome], atteso)

    def test_durate_estese(self):
        for chiave, atteso in DURATE_ATTESE.items():
            with self.subTest(caso=chiave):
                self.assertEqual(self.risultati["durate"][chiave], atteso)

    def test_intervallo_anni(self):
        for chiave, atteso in ANNI_ATTESI.items():
            with self.subTest(caso=chiave):
                self.assertEqual(self.risultati["anni"][chiave], atteso)

    def test_riassunto_artista(self):
        self.assertEqual(self.risultati["artista"], ARTISTA_ATTESO)

    def test_riassunto_album(self):
        self.assertEqual(self.risultati["album"], ALBUM_ATTESO)

    def test_riassunto_album_senza_artista_album(self):
        self.assertEqual(self.risultati["albumSenzaAA"], ALBUM_SENZA_AA_ATTESO)


class TestCablaggioScheda(unittest.TestCase):
    """La scheda è davvero in pagina e le due GUI sono davvero diverse."""

    @classmethod
    def setUpClass(cls):
        cls.src = leggi_pagina()

    def test_slot_della_scheda_in_pagina(self):
        self.assertIn('class="hero-slot" id="heroSlot"', self.src)
        self.assertIn("renderHero();", self.src, "updateHeaderUI deve costruire la scheda")
        self.assertIn("hero-slot:empty{display:none;}", self.src)

    def test_niente_piu_testo_piatto(self):
        self.assertNotIn("`Artista: ${currentArtistFilter}`", self.src)
        self.assertNotIn("`Album: ${currentAlbumFilter}`", self.src)
        self.assertIn('titleEl.style.display = "none";', self.src,
                      "con la scheda aperta la barra non deve ripetere il nome")

    def test_due_gui_diverse(self):
        # artista = avatar tondo, album = cover quadrata in stile vinile
        self.assertIn(".hero-artist .hero-art{border-radius:50%", self.src)
        self.assertIn(".hero-album .hero-art{border-radius:10px", self.src)
        self.assertIn(".hero-album .hero-art::before", self.src)
        self.assertIn('class="hero hero-artist"', self.src)
        self.assertIn('class="hero hero-album"', self.src)
        self.assertIn('<div class="hero-eyebrow">Album</div>', self.src)
        self.assertIn('<div class="hero-eyebrow">Artista</div>', self.src)

    def test_scheda_artista_con_le_chip_degli_album(self):
        self.assertIn('class="hero-chip" data-album=', self.src)
        self.assertIn("function heroApriAlbum(", self.src)
        self.assertRegex(self.src, r"slice\(0, HERO_MAX_CHIP\)")
        self.assertIn("altri album", self.src)
        # ogni chip porta il pallino dell'album: dal 18/09/2026 è la COPERTINA
        # dell'album (mini 18×18) e il gradiente resta come secondo strato, così
        # se il file manca non si vede un buco; senza cover è il pallino 9px.
        self.assertIn('class="hero-chip-dot${cov ? " con-cover" : ""}"', self.src)
        self.assertIn("background-image:url('${cov}'),${gradienteDa(a.nome)}", self.src)
        self.assertIn(".hero-chip-dot{width:9px", self.src)
        self.assertIn(".hero-chip-dot.con-cover{width:18px", self.src)

    def test_scheda_album_con_badge_segnaposto(self):
        self.assertIn("⚠ album segnaposto", self.src)
        self.assertIn("albumSegnaposto(nome)", self.src)

    def test_vista_album_con_numeri_di_traccia(self):
        self.assertIn("const numero = currentAlbumFilter ? (t.track_number || (i + 1)) : (i + 1);", self.src)
        self.assertIn(": numero}</div>", self.src)
        self.assertIn('document.body.classList.toggle("album-view"', self.src)
        self.assertIn("body.album-view .track-album{display:none;}", self.src)

    def test_clic_senza_javascript_inline(self):
        # l'apostrofo dentro un onclick inline ("Stan's Tape") rompeva il clic
        for schema in ("setAlbumFilter('${escHtml(", "setArtistFilter('${escHtml("):
            self.assertNotIn(schema, self.src)
        for attributo in ('data-album="${escHtml(', 'data-artist="${escHtml('):
            self.assertIn(attributo, self.src)
        for funzione, atteso in (("apriAlbumDa", 'onclick="event.stopPropagation(); apriAlbumDa(this)"'),
                                 ("apriArtistaDa", 'onclick="event.stopPropagation(); apriArtistaDa(this)"'),
                                 ("heroApriAlbum", 'onclick="heroApriAlbum(this)"')):
            self.assertIn("function %s(" % funzione, self.src)
            self.assertIn(atteso, self.src, "il clic di %s deve passare dall'attributo data-" % funzione)

    def test_azioni_della_scheda_sulla_lista_filtrata(self):
        for funzione in ("heroPlayAll", "heroShuffle"):
            self.assertIn("function %s(" % funzione, self.src)
            self.assertIn('onclick="%s()"' % funzione, self.src)
            self.assertIn("visibleTracks()", estrai_funzione(self.src, funzione),
                          "%s deve agire sui brani della scheda, non su tutta la libreria" % funzione)


if __name__ == "__main__":
    unittest.main()
