"""Test del clic sull'album nella lista del player (`onyx_whosampled.html`).

Domanda di Alessandro: «ci sono alcuni brani tipo [HARD] Night Lovell x Dope
D.O.D. Type Beat 2022 ＂Extermination” (Prod. Raedius) - Brano locale che se li
clicchi NON aprono l'album… che succede?»

Cosa succedeva: quei brani (importati da file locali e da YouTube) hanno il campo
`album` vuoto — 58 su 945 nel database vero del 19/09/2026, fra cui i type beat
scaricati con yt-dlp. La riga scriveva il nome dell'album in `data-album=""` e
`apriAlbumDa()` faceva `if(nome) setAlbumFilter(nome)`: con l'album vuoto usciva
**in silenzio** — nessun filtro, nessun messaggio, nessun errore in console, e il
titolo (che ha `cursor:pointer` e si sottolinea al passaggio del mouse) sembrava
rotto. Lo stesso nella barra in basso: `nowbarOpenAlbum()` faceva
`if(!t || !t.album) return;`, quindi cliccare il titolo in ascolto non diceva
niente (nella pagina principale, per lo stesso caso, c'era già un avviso:
`toast('Album non disponibile per questo brano','err')`).

Ora il clic passa da `apriAlbumPerNome()`: con l'album apre la scheda come prima
e ritorna true; senza album mostra un avviso in basso (`avvisoOnyx`) che dice
cosa manca e dove si riempie (`✏️ Modifica info avanzata`, tasto destro sul
brano) e ritorna false. Nella lista la cella dell'album dice «nessun album» in
grigio corsivo (niente finta sottolineatura: `cursor:help`) e il tooltip del
titolo diventa «Questo brano non ha un album salvato».

Questo file prova due cose:
1. `TestFunzioniAlbum` — `apriAlbumPerNome` e `nowbarOpenAlbum` eseguite
   **davvero** in JavaScriptCore (`osascript -l JavaScript`), con `setAlbumFilter`,
   `avvisoOnyx`, `evidenziaBrano`, `tracks` e `currentTrackId` finti: album pieno
   → filtro e nessun avviso; album vuoto/nullo/assente → avviso e nessun filtro;
   nowbar senza album → avvisa e non scorre.
2. `TestCablaggioAlbum` — controlli Python sul documento: la riga e la barra in
   basso passano da `apriAlbumPerNome`, l'avviso esiste, la cella vuota è
   marcata e il tooltip è onesto.

Esecuzione (dalla cartella di SampleLab):
    python3 -m unittest -v test_album_clic
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


def leggi_pagina():
    with open(PAGINA, encoding="utf-8") as fh:
        return fh.read()


def _blocco(src, inizio, apre, chiude, nome):
    """Il testo del blocco aperto in `inizio` e l'indice della sua chiusura."""
    livello = 0
    i = inizio
    while i < len(src):
        if src[i] == apre:
            livello += 1
        elif src[i] == chiude:
            livello -= 1
            if livello == 0:
                return src[inizio:i + 1], inizio, i
        i += 1
    raise AssertionError("blocco %s non chiuso in %s" % (nome, PAGINA))


def estrai_funzione(src, nome):
    m = re.search(r"(?:async\s+)?function\s+" + re.escape(nome) + r"\s*\(", src)
    if not m:
        raise AssertionError("funzione %s assente in %s" % (nome, PAGINA))
    _corpo, _i, j = _blocco(src, m.end() - 1, "{", "}", nome)
    return src[m.start():j + 1]


@unittest.skipUnless(HA_OSASCRIPT, "JavaScriptCore (osascript) non disponibile")
class TestFunzioniAlbum(unittest.TestCase):
    """`apriAlbumPerNome` / `nowbarOpenAlbum`, eseguite davvero, con le dipendenze finte."""

    risultati = {}

    @classmethod
    def setUpClass(cls):
        src = leggi_pagina()
        js = estrai_funzione(src, "apriAlbumPerNome") + "\n"
        js += estrai_funzione(src, "nowbarOpenAlbum") + "\n"
        js += """
const chiamate = [];
function setAlbumFilter(a){ chiamate.push(["filtro", a]); }
function avvisoOnyx(t){ chiamate.push(["avviso", t]); }
function evidenziaBrano(id){ chiamate.push(["evidenzia", id]); }
let tracks = [], currentTrackId = null;
const out = {};

// 1) album presente: apre la scheda, nessun avviso
out.con_album_esito = apriAlbumPerNome("The Marshall Mathers LP");
out.con_album_chiamate = chiamate.splice(0);

// 2) album vuoto / nullo / assente: avvisa e ritorna false
out.vuoto_esito = apriAlbumPerNome("");
out.vuoto_chiamate = chiamate.splice(0);
out.nullo_esito = apriAlbumPerNome(null);
out.nullo_chiamate = chiamate.splice(0);
out.assente_esito = apriAlbumPerNome(undefined);
out.assente_chiamate = chiamate.splice(0);

// 3) barra in basso con un brano SENZA album: avvisa e NON scorre
tracks = [{id: "song_a", album: ""}, {id: "song_b", album: "2001"}];
currentTrackId = "song_a";
nowbarOpenAlbum();
out.nowbar_senza_album = chiamate.splice(0);

// 4) barra in basso con un album: filtra e poi porta in vista
currentTrackId = "song_b";
nowbarOpenAlbum();
out.nowbar_con_album = chiamate.splice(0);

// 5) nessun brano corrente: non deve fare nulla (nemmeno avvisi)
currentTrackId = null;
nowbarOpenAlbum();
out.nowbar_senza_brano = chiamate.splice(0);

console.log(JSON.stringify(out));
"""
        f = "/tmp/test_album_clic.js"
        with open(f, "w", encoding="utf-8") as out:
            out.write(js + "\n0;\n")
        r = subprocess.run(["osascript", "-l", "JavaScript", f],
                           capture_output=True, text=True)
        testo = ((r.stdout or "") + (r.stderr or "")).strip().splitlines()
        assert testo, "nessun output da JavaScriptCore: %s" % (r.stderr or "")[:200]
        cls.risultati = json.loads(testo[-1])

    def test_album_presente_apre_la_scheda(self):
        self.assertIs(self.risultati["con_album_esito"], True)
        self.assertEqual(self.risultati["con_album_chiamate"],
                         [["filtro", "The Marshall Mathers LP"]])

    def test_album_assente_avvisa_e_non_filtra(self):
        for nome in ("vuoto", "nullo", "assente"):
            with self.subTest(album=nome):
                self.assertIs(self.risultati[nome + "_esito"], False,
                              "senza album non si apre niente: l'esito è false")
                chiamate = self.risultati[nome + "_chiamate"]
                self.assertEqual(len(chiamate), 1, "solo l'avviso, nessun filtro")
                tipo, testo = chiamate[0]
                self.assertEqual(tipo, "avviso")
                self.assertIn("Modifica info avanzata", testo,
                              "l'avviso deve dire dove si riempie il campo")

    def test_nowbar_senza_album_avvisa_e_non_scorre(self):
        chiamate = self.risultati["nowbar_senza_album"]
        self.assertEqual([c[0] for c in chiamate], ["avviso"],
                         "con un album vuoto la barra in basso avvisa e non scorre")

    def test_nowbar_con_album_filtra_e_poi_scorre(self):
        self.assertEqual(self.risultati["nowbar_con_album"],
                         [["filtro", "2001"], ["evidenzia", "song_b"]],
                         "prima si apre la scheda, poi si porta la canzone in vista")

    def test_nowbar_senza_brano_non_fa_niente(self):
        self.assertEqual(self.risultati["nowbar_senza_brano"], [])


class TestCablaggioAlbum(unittest.TestCase):
    """Controlli sul documento: chi chiama chi, e cosa vede l'utente."""

    @classmethod
    def setUpClass(cls):
        cls.src = leggi_pagina()

    def test_riga_e_barra_passano_da_aprialbumpernome(self):
        self.assertIn("function apriAlbumPerNome(", self.src)
        for funzione in ("apriAlbumDa", "heroApriAlbum"):
            with self.subTest(funzione=funzione):
                corpo = estrai_funzione(self.src, funzione)
                self.assertIn('apriAlbumPerNome(el && el.getAttribute ? '
                              'el.getAttribute("data-album") : "")', corpo)
                self.assertNotIn("if(nome) setAlbumFilter(nome);", corpo,
                                 "il `if(nome)` muto è il bug che è stato tolto")
        self.assertIn("if(apriAlbumPerNome(t.album)) evidenziaBrano(t.id);",
                      estrai_funzione(self.src, "nowbarOpenAlbum"))

    def test_la_riga_resta_collegata_dai_data_attribute(self):
        # il clic passa dagli attributi (l'apostrofo in un onclick inline lo rompeva)
        self.assertIn('data-album="${escHtml(t.album)}"', self.src)
        self.assertIn('onclick="event.stopPropagation(); apriAlbumDa(this)"', self.src)

    def test_cella_vuota_marcata_e_onesta(self):
        self.assertIn('class="track-album${t.album ? "" : " senza-album"}"', self.src)
        self.assertIn('${t.album ? escHtml(t.album) : "nessun album"}', self.src)
        self.assertIn(".track-album.senza-album{cursor:help", self.src)
        self.assertIn(".track-album.senza-album:hover{text-decoration:none", self.src)

    def test_tooltip_onesto_quando_manca_l_album(self):
        self.assertIn('title="${t.album ? "Apri l\'album di questa canzone" : '
                      '"Questo brano non ha un album salvato"}"', self.src)

    def test_avviso_esiste_ed_e_in_basso(self):
        corpo = estrai_funzione(self.src, "avvisoOnyx")
        self.assertIn('el.id = "avvisoOnyx"', corpo)
        self.assertIn("position:fixed", corpo)
        self.assertIn("bottom:", corpo)
        self.assertIn("clearTimeout(avvisoTimer)", corpo,
                      "un avviso nuovo deve sostituire il precedente, non accavallarsi")


if __name__ == "__main__":
    unittest.main()
