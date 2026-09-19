"""Test dei messaggi d'errore di rete, detti in modo comprensibile (19/09/2026).

Il caso vero: Alessandro vede «❌ Failed to fetch onyx_t_1786610656293_ads8r.COM]
3ree6ix5ive» mentre l'app veniva riavviata. Il file era a posto (il server lo serve:
HTTP 200, 6,8 MB, `audio/mpeg`) e quel messaggio viene dal BROWSER quando la richiesta
non arriva proprio al server. Il problema non era il dato, era il MESSAGGIO: «Failed to
fetch» non dice a chi legge cosa è successo né cosa fare.

Cosa copre questo file:
1. `messaggioReteOnyx` (player) e `messaggioRete` (pagina principale) — funzioni PURE,
   eseguite DAVVERO in JavaScriptCore: i testi del browser per l'errore di rete
   diventano «il server non risponde… ricarica la pagina (⌘R)», e gli altri errori
   passano com'è;
2. il cablaggio nei sorgenti: il player non ha più una `fetch(track.url)` nuda, avvisa
   la pagina principale (`playerError`), l'errore dell'`<audio>` non resta più solo
   nella console, e la pagina principale mostra quell'avviso e usa `messaggioRete`
   quando l'onda non si carica.

Esecuzione (dalla cartella di SampleLab):
    python3 -m unittest -v test_errori_rete
"""
import json
import os
import re
import shutil
import subprocess
import unittest

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PAGINA_PATH = os.path.join(BASE_DIR, "index (2).html")
ONYX_PATH = os.path.join(BASE_DIR, "onyx_whosampled.html")
HA_OSASCRIPT = shutil.which("osascript") is not None


def leggi(percorso):
    with open(percorso, encoding="utf-8") as f:
        return f.read()


def estrai_funzione(src, nome):
    """Il sorgente di una funzione dichiarata con `function nome(…)` (graffe contate)."""
    m = re.search(r"function\s+" + re.escape(nome) + r"\s*\(", src)
    if not m:
        raise AssertionError("funzione %s assente" % nome)
    i = src.index("{", m.end() - 1)
    liv, j = 0, i
    while j < len(src):
        if src[j] == "{":
            liv += 1
        elif src[j] == "}":
            liv -= 1
            if liv == 0:
                return src[m.start():j + 1]
        j += 1
    raise AssertionError("graffe non bilanciate in %s" % nome)


def esegui_js(codice, nome_file="/tmp/test_errori_rete.js"):
    with open(nome_file, "w", encoding="utf-8") as out:
        out.write(codice + "\n0;\n")
    r = subprocess.run(["osascript", "-l", "JavaScript", nome_file],
                       capture_output=True, text=True)
    righe = ((r.stdout or "") + (r.stderr or "")).strip().splitlines()
    if not righe:
        raise AssertionError("nessun output da JavaScriptCore: %s" % (r.stderr or "")[:200])
    return json.loads(righe[-1])


# I testi che il browser usa davvero quando la richiesta non arriva al server
MESSAGGI_BROWSER = ["Failed to fetch", "NetworkError when attempting to fetch resource.",
                    "Load failed", "Network request failed", "fetch failed",
                    "TypeError: Failed to fetch", "failed to fetch"]


@unittest.skipUnless(HA_OSASCRIPT, "JavaScriptCore (osascript) non disponibile")
class TestMessaggiRete(unittest.TestCase):
    """Le due funzioni pure, eseguite davvero: cosa diventa un errore di rete."""

    risultati = {}

    @classmethod
    def setUpClass(cls):
        js = "\n".join([
            estrai_funzione(leggi(ONYX_PATH), "messaggioReteOnyx"),
            estrai_funzione(leggi(PAGINA_PATH), "messaggioRete"),
        ])
        js += """
const casi = %s;
console.log(JSON.stringify({
  onyx: casi.map(m => messaggioReteOnyx(new TypeError(m))),
  pagina: casi.map(m => messaggioRete(new TypeError(m), 'canzone.mp3')),
  altri: [messaggioReteOnyx(new Error('quota esaurita')),
          messaggioRete(new Error('HTTP 500'), 'x.mp3'),
          messaggioReteOnyx(undefined),
          messaggioRete(undefined)],
  senza_nome: messaggioRete(new TypeError('Failed to fetch'))
}));
""" % json.dumps(MESSAGGI_BROWSER)
        cls.risultati = esegui_js(js)

    def test_il_player_traduce_lerrore_di_rete(self):
        for testo in self.risultati["onyx"]:
            self.assertIn("il server non risponde", testo)
            self.assertIn("ricarica la pagina", testo)
            self.assertNotIn("Failed to fetch", testo)

    def test_la_pagina_lo_traduce_e_ci_mette_il_nome(self):
        for testo in self.risultati["pagina"]:
            self.assertIn("il server non risponde", testo)
            self.assertIn("«canzone.mp3»", testo)
            self.assertIn("ricarica la pagina", testo)

    def test_gli_altri_errori_passano_cosi_comi_sono(self):
        altri = self.risultati["altri"]
        self.assertEqual(altri[0], "quota esaurita")
        self.assertEqual(altri[1], "HTTP 500")
        self.assertEqual(altri[2], "errore di rete")
        self.assertEqual(altri[3], "errore di rete")

    def test_senza_nome_il_messaggio_resta_chiaro(self):
        testo = self.risultati["senza_nome"]
        self.assertIn("il server non risponde", testo)
        self.assertNotIn("«", testo)


class TestCablaggio(unittest.TestCase):
    """Il cablaggio nei sorgenti: chi avvisa e chi mostra il messaggio."""

    def test_il_player_non_ha_piu_la_fetch_nuda(self):
        onyx = leggi(ONYX_PATH)
        self.assertNotIn("const res = await fetch(track.url);", onyx)
        self.assertIn("function messaggioReteOnyx(", onyx)
        self.assertIn("function avvisaOnyx(", onyx)
        # l'import di un brano del database: URL controllata, fetch protetta, avviso
        self.assertIn("if(!track.url){", onyx)
        self.assertIn("avvisaOnyx(nomeCanzone + ': ' + messaggioReteOnyx(err));", onyx)
        self.assertIn("il file non è raggiungibile dal server (HTTP ", onyx)
        # l'errore dell'elemento audio non resta solo nella console
        self.assertIn('audio.addEventListener("error"', onyx)
        # nel sorgente l'apostrofo è scritto «l\'audio» (stringa JS)
        self.assertIn("non riesco a leggere l\\'audio dal server", onyx)
        # e non si riempie lo schermo di messaggi uguali
        self.assertIn("_ultimoAvvisoOnyx", onyx)

    def test_la_pagina_mostra_lavviso_del_player(self):
        pagina = leggi(PAGINA_PATH)
        self.assertIn("else if(d.action === 'playerError' && d.text){", pagina)
        self.assertIn("toast('🎧 ' + d.text, 'err');", pagina)
        self.assertIn("function messaggioRete(", pagina)
        # l'onda che non si carica lo dice, invece di sparire in silenzio
        self.assertIn("toast('✕ ' + messaggioRete(e, filename), 'err');", pagina)
        self.assertIn("p.reteAvvisata", pagina)

    def test_il_player_dice_perche_non_suona(self):
        onyx = leggi(ONYX_PATH)
        # il catch della riproduzione non è più un semplice console.error
        self.assertNotIn("}).catch(err => { console.error(err); pushPlaybackState(true); });", onyx)
        self.assertIn("isPlaying = false; updatePlayUI(); renderTracks(); pushPlaybackState(true);",
                      onyx)


if __name__ == "__main__":
    unittest.main(verbosity=2)

