"""Test del metronomo del sampler (`index (2).html`).

Richiesta del 17/09/2026: il metronomo deve poter battere **ogni 1/4**, ogni 2/4,
3/4, ogni battuta, ogni 2 o 4 battute — **indipendentemente dalla griglia** (prima
seguiva la suddivisione della griglia, quindi per sentire i quarti si doveva
cambiare la griglia). Le funzioni di calcolo sono pure, quindi si testano in
esecuzione reale con JavaScriptCore, senza browser e senza avviare l'app:

- `stepMetronomo(bpm, unità)`  → secondi fra un colpo e l'altro;
- `accentoBattuta(istante, bpm, unità)` → vero se il colpo è il primo della battuta;
- `etichettaUnita(unità)` → '1/4', '2/4', '3/4', '1 battuta', 'N battute'.

Esecuzione (dalla cartella di SampleLab):
    python3 -m unittest -v test_sampler_metronomo
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

UNITÀ = [0.25, 0.5, 0.75, 1, 2, 4]


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
class TestMetronomo(unittest.TestCase):
    risultati = {}

    @classmethod
    def setUpClass(cls):
        with open(PAGINA, encoding="utf-8") as fh:
            src = fh.read()
        js = "\n".join([
            estrai_funzione(src, "stepMetronomo"),
            estrai_funzione(src, "accentoBattuta"),
            estrai_funzione(src, "etichettaUnita"),
            """
const unita = %s;
const out = {passo: {}, accento: {}, etichetta: {}};
unita.forEach(u => { out.passo[u] = stepMetronomo(120, u); out.etichetta[u] = etichettaUnita(u); });
// accenti a 120 BPM (battuta = 2 s), valutati SOLO sugli istanti in cui il
// metronomo batte davvero: k * passo, per ~due battute
unita.forEach(u => {
  const passo = stepMetronomo(120, u);
  const istanti = [];
  for (let k = 0; k * passo <= 4.0001; k++) istanti.push(+(k * passo).toFixed(6));
  out.accento[u] = istanti.map(t => accentoBattuta(t, 120, u) ? 1 : 0);
  out.istanti = out.istanti || {};
  out.istanti[u] = istanti;
});
out.passo_60 = stepMetronomo(60, 0.25);
out.passo_bpm_zero = stepMetronomo(0, 0.25);
out.passo_unita_assente = stepMetronomo(120, null);
out.passo_114_8 = stepMetronomo(114.8, 0.25);
console.log(JSON.stringify(out));
""" % json.dumps(UNITÀ),
        ])
        f = "/tmp/test_sampler_metronomo.js"
        with open(f, "w", encoding="utf-8") as out:
            out.write(js + "\n0;\n")
        r = subprocess.run(["osascript", "-l", "JavaScript", f], capture_output=True, text=True)
        righe = ((r.stdout or "") + (r.stderr or "")).strip().splitlines()
        assert righe, "nessun output da JavaScriptCore: %s" % (r.stderr or "")[:200]
        cls.risultati = json.loads(righe[-1])

    def test_passo_a_120_bpm(self):
        # 240/120 = 2 s per battuta: 1/4 = 0,5 s · 2/4 = 1 s · 3/4 = 1,5 s · 1 = 2 s
        self.assertAlmostEqual(self.risultati["passo"]["0.25"], 0.5, places=9)
        self.assertAlmostEqual(self.risultati["passo"]["0.5"], 1.0, places=9)
        self.assertAlmostEqual(self.risultati["passo"]["0.75"], 1.5, places=9)
        self.assertAlmostEqual(self.risultati["passo"]["1"], 2.0, places=9)
        self.assertAlmostEqual(self.risultati["passo"]["2"], 4.0, places=9)
        self.assertAlmostEqual(self.risultati["passo"]["4"], 8.0, places=9)

    def test_passo_altri_bpm(self):
        self.assertAlmostEqual(self.risultati["passo_60"], 1.0, places=9)
        self.assertAlmostEqual(self.risultati["passo_114_8"], 240 / 114.8 * 0.25, places=9)

    def test_bpm_non_valido(self):
        self.assertEqual(self.risultati["passo_bpm_zero"], 0)
        # unità assente: si assume "ogni quarto"
        self.assertAlmostEqual(self.risultati["passo_unita_assente"], 0.5, places=9)

    def test_accento_ogni_quarto(self):
        # 1/4 a 120 BPM: batte ogni 0,5 s; l'accento cade ogni 4 colpi (inizio battuta)
        self.assertEqual(self.risultati["istanti"]["0.25"], [0, 0.5, 1, 1.5, 2, 2.5, 3, 3.5, 4])
        self.assertEqual(self.risultati["accento"]["0.25"], [1, 0, 0, 0, 1, 0, 0, 0, 1])

    def test_accento_ogni_due_quarti(self):
        # 2/4: batte ogni 1 s → accento sul 1°, 3° e 5° colpo (t = 0, 2, 4 s)
        self.assertEqual(self.risultati["accento"]["0.5"], [1, 0, 1, 0, 1])

    def test_accento_ogni_tre_quarti(self):
        # 3/4: batte ogni 1,5 s → 0 s accentato, 1,5 s e 3 s no (l'accento
        # tornerebbe a 4,5 s, che è il primo colpo successivo a una battuta)
        self.assertEqual(self.risultati["accento"]["0.75"], [1, 0, 0])

    def test_accento_ogni_battuta(self):
        # 1 battuta: ogni colpo coincide con l'inizio di una battuta → sempre accentato
        self.assertEqual(self.risultati["accento"]["1"], [1, 1, 1])
        # 2 e 4 battute: i colpi cadono sempre su un inizio di battuta
        self.assertEqual(self.risultati["accento"]["2"], [1, 1])
        self.assertEqual(self.risultati["accento"]["4"], [1])

    def test_etichette(self):
        self.assertEqual(self.risultati["etichetta"]["0.25"], "1/4")
        self.assertEqual(self.risultati["etichetta"]["0.5"], "2/4")
        self.assertEqual(self.risultati["etichetta"]["0.75"], "3/4")
        self.assertEqual(self.risultati["etichetta"]["1"], "1 battuta")
        self.assertEqual(self.risultati["etichetta"]["2"], "2 battute")
        self.assertEqual(self.risultati["etichetta"]["4"], "4 battute")


if __name__ == "__main__":
    unittest.main()
