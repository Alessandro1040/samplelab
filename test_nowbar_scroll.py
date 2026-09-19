"""Test del clic sulla barra in basso del player (`onyx_whosampled.html`).

Richiesta di Alessandro: «se io clicco su una canzone mentre la sto ascoltando,
in basso a sinistra, dovrebbe rimandarmi proprio all'esatta canzone, non solo
all'album, cioè all'album ma nel punto in cui compare la canzone, non all'inizio
dell'album».

Com'era prima: `nowbarOpenAlbum()` chiamava solo `setAlbumFilter(t.album)` (e
`nowbarOpenArtist()` solo `setArtistFilter(t.artist)`), quindi si apriva la
scheda giusta ma la lista riscritta da `renderTracks()` restava al punto di
scorrimento di prima: la canzone in ascolto poteva essere fuori schermo e la
riga attiva (`.track-row.playing`) è quasi invisibile.

Ora il clic fa due cose: apre la scheda **e** porta la riga della canzone al
centro della parte visibile della lista (`evidenziaBrano`), facendola
lampeggiare per ~1,7 s. La lista che scorre è `.tracks-area` (#tracksArea); la
scheda (cover, titolo, chip) sta fuori da quell'area, quindi resta a vista.

Questo file prova due cose:
1. `TestFunzioniIndiceBrano` — `indiceBrano(lista, id)`, la funzione pura che
   dice se la canzone è fra quelle mostrate (e a che posizione), **eseguita
   davvero** con JavaScriptCore (`osascript -l JavaScript`).
2. `TestCablaggioBarraInBasso` — controlli Python: la riga porta il suo id
   (`data-track-id`), `evidenziaBrano` scorre la lista giusta e lampeggia, lo
   stile `.trovato` esiste (lime nella scheda artista, teal in quella album) e i
   due clic chiamano il filtro **e** l'evidenziazione nell'ordine giusto. Un
   brano senza album non esce più in silenzio: il clic lo dice e non scorre
   niente (`apriAlbumPerNome` → `avvisoOnyx`, vedi `test_album_clic.py`).

Esecuzione (dalla cartella di SampleLab):
    python3 -m unittest -v test_nowbar_scroll
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

# ── dati dei casi: la libreria di prova, cinque brani ────────────────────────
LISTA = [
    {"id": "song_a", "name": "Primo", "album": "Album X"},
    {"id": "song_b", "name": "Secondo", "album": "Album X"},
    {"id": "song_c", "name": "Terzo", "album": "Album X"},
    {"id": "song_d", "name": "Quarto", "album": "Album Y"},
    {"id": "song_e", "name": "Quinto", "album": "Album Y"},
]
DOPPIONI = [{"id": "song_a"}, {"id": "song_a"}, {"id": "song_b"}]
SOLO_NUMERI = [{"id": 7}, {"id": 8}]

# (nome del caso, chiave della lista, id cercato, indice atteso)
CASI = [
    ("primo", "piena", "song_a", 0),
    ("in_mezzo", "piena", "song_c", 2),
    ("ultimo", "piena", "song_e", 4),
    ("assente", "piena", "song_z", -1),
    ("id_vuoto", "piena", "", -1),
    ("id_nullo", "piena", None, -1),
    ("lista_vuota", "vuota", "song_a", -1),
    ("lista_nulla", "nulla", "song_a", -1),
    ("doppioni", "doppioni", "song_a", 0),      # vince la prima riga
    ("id_numerico", "numeri", 7, 0),            # gli id si confrontano come testo
]

INTESTAZIONE_RIGA = 'data-track-id="${t.id}"'


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


@unittest.skipUnless(HA_OSASCRIPT, "JavaScriptCore (osascript) non disponibile")
class TestFunzioniIndiceBrano(unittest.TestCase):
    """`indiceBrano`, eseguita davvero, sui casi scritti a mano."""

    risultati = {}

    @classmethod
    def setUpClass(cls):
        src = leggi_pagina()
        js = estrai_funzione(src, "indiceBrano")
        js += """
const liste = { piena: %s, vuota: [], nulla: null,
                doppioni: %s, numeri: %s };
const casi = %s;
const out = {};
for (const c of casi) { out[c.nome] = indiceBrano(liste[c.lista], c.id); }
out["id_undefined"] = indiceBrano(liste.piena, undefined);
out["brano_nullo"] = indiceBrano([null, {id: "song_a"}], "song_a");
out["senza_id"] = indiceBrano([{name: "senza id"}], "song_a");
console.log(JSON.stringify(out));
""" % (json.dumps(LISTA), json.dumps(DOPPIONI), json.dumps(SOLO_NUMERI),
       json.dumps([{"nome": n, "lista": k, "id": i} for n, k, i, _ in CASI]))
        f = "/tmp/test_nowbar_scroll.js"
        with open(f, "w", encoding="utf-8") as out:
            out.write(js + "\n0;\n")
        r = subprocess.run(["osascript", "-l", "JavaScript", f],
                           capture_output=True, text=True)
        testo = ((r.stdout or "") + (r.stderr or "")).strip().splitlines()
        assert testo, "nessun output da JavaScriptCore: %s" % (r.stderr or "")[:200]
        cls.risultati = json.loads(testo[-1])

    def test_indice_atteso(self):
        for nome, _lista, _id, atteso in CASI:
            with self.subTest(caso=nome):
                self.assertEqual(self.risultati.get(nome), atteso)

    def test_casi_limite(self):
        # gli stessi casi che in pagina non devono far scorrere niente
        self.assertEqual(self.risultati.get("id_undefined"), -1)
        self.assertEqual(self.risultati.get("brano_nullo"), 1,
                         "un elemento nullo nella lista non deve fermare la ricerca")
        self.assertEqual(self.risultati.get("senza_id"), -1)


class TestCablaggioBarraInBasso(unittest.TestCase):
    """Controlli sul sorgente: riga con id, scroll sulla lista giusta, clic."""

    @classmethod
    def setUpClass(cls):
        cls.src = leggi_pagina()

    def test_riga_con_il_suo_id(self):
        self.assertIn(INTESTAZIONE_RIGA, self.src,
                      "senza data-track-id la riga della canzone non si trova")
        self.assertIn('class="track-row ${isActive ? "playing" : ""}" ' + INTESTAZIONE_RIGA,
                      self.src)

    def test_evidenzia_scorre_la_lista_giusta(self):
        corpo = estrai_funzione(self.src, "evidenziaBrano")
        self.assertIn('getElementById("tracksArea")', corpo,
                      "deve scorrere .tracks-area, la sola area che scorre")
        self.assertIn("scrollIntoView", corpo)
        self.assertIn('block: "center"', corpo, "la canzone va portata al centro")
        self.assertIn("indiceBrano(visibleTracks(), brano) < 0", corpo,
                      "se la canzone non è fra quelle mostrate non si scorre")
        self.assertIn(".track-row[data-track-id]", corpo)
        self.assertIn("lampeggiaRiga(riga);", corpo)

    def test_lampeggio_riavviabile_anche_all_arrivo(self):
        # il lampeggio è in una funzione a parte, così può ripartire
        corpo = estrai_funzione(self.src, "lampeggiaRiga")
        self.assertIn('classList.remove("trovato")', corpo)
        self.assertIn('classList.add("trovato")', corpo)
        self.assertIn("void riga.offsetWidth", corpo, "senza reflow l'animazione non riparte")
        self.assertIn("clearTimeout(lampeggiaRiga._timer)", corpo,
                      "lampeggi ripetuti non devono lasciare timer aperti")
        self.assertIn('setTimeout(() => riga.classList.remove("trovato"), 2000)', corpo)
        # con le liste lunghe lo scorrimento dura più del lampeggio: quando la
        # lista si ferma la riga si riaccende
        evidenzia = estrai_funzione(self.src, "evidenziaBrano")
        self.assertIn("clearInterval(evidenziaBrano._poll)", evidenzia)
        self.assertIn("evidenziaBrano._poll = setInterval(", evidenzia)
        self.assertIn("pos === evidenziaBrano._ultimoScroll", evidenzia,
                      "la riaccensione scatta quando lo scroll si ferma")
        self.assertIn("clearInterval(evidenziaBrano._poll);\n      lampeggiaRiga(riga);", evidenzia)

    def test_stile_della_riga_trovata(self):
        self.assertIn(".track-row.trovato{--flash:200,240,0;", self.src)   # lime
        self.assertIn("body.album-view .track-row.trovato{--flash:45,212,191;}", self.src)
        self.assertIn("@keyframes branoTrovato{", self.src)
        self.assertIn("animation:branoTrovato 1.6s ease-out;", self.src)

    def test_i_due_clic_aprono_e_evidenziano(self):
        for funzione, filtro, cosa in (("nowbarOpenAlbum", "apriAlbumPerNome(t.album)", "album"),
                                       ("nowbarOpenArtist", "setArtistFilter(t.artist);", "artista")):
            with self.subTest(click=funzione):
                corpo = estrai_funzione(self.src, funzione)
                self.assertIn(filtro, corpo, "%s deve aprire la scheda %s" % (funzione, cosa))
                self.assertIn("evidenziaBrano(t.id);", corpo,
                              "%s deve portare la canzone in vista" % funzione)
                self.assertLess(corpo.index(filtro), corpo.index("evidenziaBrano(t.id);"),
                                "prima si apre la scheda (che rifà la lista), poi si scorre")
                # l'artista senza nome esce in silenzio; per l'album la guardia è
                # solo sul brano, perché se l'album manca si avvisa (vedi sotto)
                atteso = "if(!t) return;" if cosa == "album" else "if(!t || !t.artist) return;"
                self.assertIn(atteso, corpo)
        # L'artista senza nome esce in silenzio; l'album no: se non c'è un album da
        # aprire lo deve DIRE (`apriAlbumPerNome` avvisa e ritorna false), e in quel
        # caso non si scorre niente.
        self.assertIn("if(apriAlbumPerNome(t.album)) evidenziaBrano(t.id);",
                      estrai_funzione(self.src, "nowbarOpenAlbum"))
        self.assertIn("avvisoOnyx(", estrai_funzione(self.src, "apriAlbumPerNome"))

    def test_barra_in_basso_collegata(self):
        self.assertIn('id="nowTrack" onclick="nowbarOpenAlbum()"', self.src)
        self.assertIn('id="nowArtist" onclick="nowbarOpenArtist()"', self.src)


if __name__ == "__main__":
    unittest.main()

