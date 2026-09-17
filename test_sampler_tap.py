"""Test della stima TAP del sampler (`bpmDaTap` in `index (2).html`).

Richiesta del 17/09/2026: il pulsante 🎵 TAP deve ricavare il BPM dalla **media
di tutti i colpi** della sessione (prima teneva solo gli ultimi 8) e conservare i
**decimali** (prima arrotondava all'intero). La funzione è pura — prende gli
istanti dei colpi in millisecondi — quindi si testa in esecuzione reale con
JavaScriptCore, senza browser e senza avviare l'app.

Esecuzione (dalla cartella di SampleLab):
    python3 -m unittest -v test_sampler_tap
"""
import json
import os
import re
import shutil
import subprocess
import unittest

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PAGINA = os.path.join(BASE_DIR, "index (2).html")
HA_OSASCRIPT = shutil.which("osascript") is not None

# nome del caso -> istanti dei colpi (ms)
CASI = {
    "tre_a_500": [0, 500, 1000],
    "dodici_a_500": [i * 500 for i in range(12)],
    "quattro_a_320": [i * 320 for i in range(4)],
    "due_a_250": [0, 250],
    "jitter": [0, 500, 990, 1500],
    "trenta_a_600": [i * 600 for i in range(30)],
    "cinque_a_200": [i * 200 for i in range(5)],
    "un_colpo": [0],
    "nessun_colpo": [],
    "troppo_vicino_150": [0, 150],
    "troppo_lontano_2500": [0, 2500],
}


def estrai_funzione(src, nome):
    m = re.search(r"(?:async\s+)?function\s+" + re.escape(nome) + r"\s*\(", src)
    if not m:
        raise AssertionError("funzione %s assente in %s" % (nome, PAGINA))
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


@unittest.skipUnless(HA_OSASCRIPT, "JavaScriptCore (osascript) non disponibile")
class TestBpmDaTap(unittest.TestCase):
    """La funzione della pagina, eseguita davvero, su casi scritti a mano."""

    risultati = {}

    @classmethod
    def setUpClass(cls):
        with open(PAGINA, encoding="utf-8") as fh:
            src = fh.read()
        js = estrai_funzione(src, "bpmDaTap") + """
const casi = %s;
const out = {};
for (const k in casi) { out[k] = bpmDaTap(casi[k]); }
console.log(JSON.stringify(out));
""" % json.dumps(CASI)
        f = "/tmp/test_sampler_tap.js"
        with open(f, "w", encoding="utf-8") as out:
            out.write(js + "\n0;\n")
        r = subprocess.run(["osascript", "-l", "JavaScript", f], capture_output=True, text=True)
        testo = ((r.stdout or "") + (r.stderr or "")).strip().splitlines()
        assert testo, "nessun output da JavaScriptCore: %s" % (r.stderr or "")[:200]
        cls.risultati = json.loads(testo[-1])

    def bpm(self, caso):
        return self.risultati[caso]

    def test_media_di_tutti_i_colpi(self):
        # 12 colpi: la media è su tutti (prima si tenevano solo gli ultimi 8)
        self.assertAlmostEqual(self.bpm("dodici_a_500"), 120.0, places=9)
        self.assertAlmostEqual(self.bpm("trenta_a_600"), 100.0, places=9)

    def test_decimali_conservati(self):
        self.assertAlmostEqual(self.bpm("quattro_a_320"), 187.5, places=9)
        self.assertAlmostEqual(self.bpm("due_a_250"), 240.0, places=9)
        self.assertAlmostEqual(self.bpm("cinque_a_200"), 300.0, places=9)

    def test_jitter_compensato(self):
        # 0 / 500 / 990 / 1500 ms: media 0,5 s -> 120 BPM
        self.assertAlmostEqual(self.bpm("jitter"), 120.0, places=9)

    def test_colpi_insufficienti(self):
        self.assertIsNone(self.bpm("un_colpo"))
        self.assertIsNone(self.bpm("nessun_colpo"))

    def test_tocco_fuori_tempo(self):
        # intervallo < 0,2 s (doppio tocco) o > 2 s: la sessione va riavviata
        self.assertIsNone(self.bpm("troppo_vicino_150"))
        self.assertIsNone(self.bpm("troppo_lontano_2500"))

    def test_limite_alto_incluso(self):
        self.assertAlmostEqual(self.bpm("tre_a_500"), 120.0, places=9)


if __name__ == "__main__":
    unittest.main()
