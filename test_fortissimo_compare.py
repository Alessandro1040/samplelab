"""Test del modello FORTISSIMO COMPARE v3 (fortissimo_compare_v3.py).

Test "veri" sul file di produzione: costruiscono le analisi esattamente come
fa il blocco __main__ del modello e controllano i casi noti e i limiti.

Esecuzione (dalla cartella di SampleLab):
    python3 -m unittest -v test_fortissimo_compare
Gli ultimi test (TestApiHttp) girano solo se l'app è attiva (default
http://localhost:5070, sovrascrivibile con la variabile SAMPLELAB_URL).
"""
import importlib.util
import json
import os
import subprocess
import sys
import unittest
import urllib.error
import urllib.request

import numpy as np

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
MODEL_PATH = os.path.join(BASE_DIR, "fortissimo_compare_v3.py")


def load_model():
    """Carica il modulo dal file (il nome con spazio della cartella non conta)."""
    spec = importlib.util.spec_from_file_location("fortissimo_compare_v3", MODEL_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


FC = load_model()


# ── helper identici all'esempio del modello ───────────────────────────────────
def make_notes(p, pat, tempo=120, vel=100):
    bd = 60.0 / tempo
    return [FC.NoteEvent(p + pi, i * bd, i * bd + bd * 0.8, vel) for i, pi in enumerate(pat)]


def gen_pluck(f, d=0.1, sr=44100, amp=0.5):
    t = np.linspace(0, d, int(sr * d), endpoint=False)
    w = np.sin(2 * np.pi * f * t) + 0.5 * np.sin(2 * np.pi * f * 2 * t)
    return w * np.exp(-t * 4) * amp


def instrument(name, program, base_pitch, pattern, freq, amp, loud, is_drum=False):
    return FC.AnalyzedInstrument(
        name,
        FC.InstrumentTrack(name, program, 0, make_notes(base_pitch, pattern), is_drum=is_drum),
        FC.OneShotSample(name, program, base_pitch, gen_pluck(freq, amp=amp),
                         original_loudness=loud),
    )


def song(piano_amp=0.5, extra=None):
    """Canzone di test: guitar + bass + piano (come l'esempio del modello)."""
    insts = [
        instrument("electric guitar", 27, 64, [0, 2, 4, 2, 0, -1, 0, 2], 440, 0.6, 0.6),
        instrument("bass", 32, 36, [0, 0, 7, 0, 5, 0, 7, 0], 110, 0.7, 0.7),
        instrument("piano", 0, 60, [0, 4, 7, 4, 0, -3, 0, 4], 440, piano_amp, piano_amp),
    ]
    if extra:
        insts.extend(extra)
    return FC.AudioAnalysisOutput(insts, "song.wav", 120, 4.0)


class TestModello(unittest.TestCase):
    """Test sul modello in sé."""

    def setUp(self):
        self.model = FC.AudioSimilarityModel()

    # ── struttura e regressioni ───────────────────────────────────────────────
    def test_modulo_esporta_api_attesa(self):
        for name in ("NoteEvent", "InstrumentTrack", "OneShotSample", "AnalyzedInstrument",
                     "AudioAnalysisOutput", "InstrumentMatcher", "TrackComparator",
                     "OneShotComparator", "AudioSimilarityModel"):
            self.assertTrue(hasattr(FC, name), f"manca {name}")

    def test_costruzione_modello(self):
        """Regressione: 'vol_weight=' in __init__ faceva fallire ogni istanza."""
        m = FC.AudioSimilarityModel()
        self.assertIsInstance(m.shot_comp, FC.OneShotComparator)
        self.assertAlmostEqual(m.midi_w, 0.4)
        self.assertAlmostEqual(m.oneshot_w, 0.4)
        self.assertAlmostEqual(m.presence_w, 0.2)

    def test_pesi_devono_sommare_uno(self):
        with self.assertRaises(AssertionError):
            FC.AudioSimilarityModel(midi_weight=0.5, oneshot_weight=0.4, presence_weight=0.4)

    def test_main_del_modulo_gira(self):
        """End-to-end: 'python3 fortissimo_compare_v3.py' deve completare."""
        r = subprocess.run([sys.executable, MODEL_PATH], capture_output=True, text=True, timeout=180)
        self.assertEqual(r.returncode, 0, r.stderr[-500:])
        self.assertIn("Overall Score", r.stdout)
        self.assertIn("Matchati:       3/3", r.stdout)

    # ── casi noti dell'esempio ───────────────────────────────────────────────
    def test_identico_score_tetto(self):
        """A vs A NON dà 1.0 ma 0.925.

        Motivo (documentato, non corretto qui): TrackComparator somma i pesi a
        0.85, quindi il blocco MIDI vale al massimo 0.85 e il massimo
        raggiungibile è 0.4*0.85 + 0.4*1.0 + 0.2*1.0*0.925 = 0.925.
        Se i pesi del confronto MIDI vengono normalizzati a 1.0, il valore
        atteso diventa 1.0 e questo test va aggiornato.
        """
        a = song()
        r = self.model.compare(a, a)
        self.assertAlmostEqual(r["overall_score"], 0.925, places=6)
        self.assertEqual((r["n_a"], r["n_b"], r["n_match"]), (3, 3, 3))
        self.assertEqual(r["unmatched_a"], [])
        self.assertEqual(r["unmatched_b"], [])

    def test_esempio_piano_piu_forte(self):
        """A vs B: identiche note (MIDI ~tetto), one-shot diverso (piano più forte)."""
        a, b = song(0.5), song(0.9)
        r = self.model.compare(a, b)
        self.assertGreater(r["overall_score"], 0.0)
        self.assertLess(r["overall_score"], 1.0)
        self.assertAlmostEqual(r["midi_score"], 0.85, places=6)   # stessa partitura
        self.assertLess(r["oneshot_score"], 1.0)                  # volume diverso
        self.assertEqual(r["presence_score"], 1.0)
        for k in ("overall_score", "midi_score", "oneshot_score", "presence_score"):
            self.assertGreaterEqual(r[k], 0.0)
            self.assertLessEqual(r[k], 1.0)

    def test_tetto_dello_score_midi(self):
        """Documenta il limite attuale: TrackComparator somma i pesi a 0.85
        (0.25+0.20+0.15+0.10+0.15), quindi con note identiche lo score MIDI è
        0.85 e non 1.0. Se i pesi vengono corretti, questo test va aggiornato."""
        tc = FC.TrackComparator()
        t = FC.InstrumentTrack("piano", 0, 0, make_notes(60, [0, 4, 7]))
        r = tc.compare(t, t)
        self.assertAlmostEqual(r["score"], 0.85, places=6)
        self.assertAlmostEqual(r["f1"], 1.0, places=6)
        self.assertAlmostEqual(r["timing"], 1.0, places=6)
        self.assertAlmostEqual(r["pitch"], 1.0, places=6)
        self.assertAlmostEqual(r["velocity"], 1.0, places=6)
        self.assertAlmostEqual(r["rhythm"], 1.0, places=6)

class TestCasiLimite(unittest.TestCase):
    """Casi limite e proprietà del modello."""

    def setUp(self):
        self.model = FC.AudioSimilarityModel()

    def test_strumento_in_piu_solo_in_a(self):
        flute = instrument("flute", 73, 72, [0, 2], 880, 0.5, 0.5)
        r = self.model.compare(song(extra=[flute]), song())
        self.assertEqual(r["unmatched_a"], ["flute"])
        self.assertEqual(r["unmatched_b"], [])
        self.assertAlmostEqual(r["presence_score"], 0.75)     # 3 matchati su 4
        self.assertLess(r["overall_score"], 1.0)
        self.assertLess(r["overall_score"], self.model.compare(song(), song())["overall_score"])

    def test_strumento_in_piu_solo_in_b(self):
        flute = instrument("flute", 73, 72, [0, 2], 880, 0.5, 0.5)
        r = self.model.compare(song(), song(extra=[flute]))
        self.assertEqual(r["unmatched_b"], ["flute"])
        self.assertEqual(r["unmatched_a"], [])
        self.assertEqual((r["n_a"], r["n_b"], r["n_match"]), (3, 4, 3))

    def test_quick_score_coerente(self):
        a, b = song(0.5), song(0.9)
        self.assertAlmostEqual(self.model.quick_score(a, b),
                               self.model.compare(a, b)["overall_score"], places=9)

    def test_determinismo(self):
        a, b = song(0.5), song(0.9)
        r1, r2 = self.model.compare(a, b), self.model.compare(a, b)
        self.assertEqual(r1["overall_score"], r2["overall_score"])
        self.assertEqual([d["score"] for d in r1["details"]],
                         [d["score"] for d in r2["details"]])

    def test_volume_non_tocca_il_midi(self):
        """Il peso del volume agisce solo sul blocco one-shot."""
        a, b = song(0.5), song(0.9)
        m0 = FC.AudioSimilarityModel(volume_weight=0.0).compare(a, b)
        m1 = FC.AudioSimilarityModel(volume_weight=1.0).compare(a, b)
        self.assertAlmostEqual(m0["midi_score"], m1["midi_score"], places=9)
        self.assertNotAlmostEqual(m0["oneshot_score"], m1["oneshot_score"], places=6)
        self.assertLess(m1["oneshot_score"], m0["oneshot_score"])

    def test_one_shot_senza_campioni(self):
        """Audio vuoto: il confronto one-shot vale 0, senza eccezioni."""
        vuoto = FC.OneShotSample("piano", 0, 72, np.zeros(0), original_loudness=0.5)
        ia = FC.AnalyzedInstrument("piano", FC.InstrumentTrack("piano", 0, 0, make_notes(60, [0, 4])), vuoto)
        r = self.model.compare(FC.AudioAnalysisOutput([ia], "a.wav"),
                               FC.AudioAnalysisOutput([ia], "b.wav"))
        self.assertEqual(r["n_match"], 1)
        self.assertAlmostEqual(r["oneshot_score"], 0.0)
        self.assertGreater(r["midi_score"], 0.0)

    def test_analisi_vuote(self):
        vuoto = FC.AudioAnalysisOutput([], "vuoto.wav")
        r = self.model.compare(vuoto, vuoto)
        self.assertEqual(r["overall_score"], 1.0)
        self.assertEqual((r["n_a"], r["n_b"], r["n_match"], r["details"]), (0, 0, 0, []))
        self.assertEqual((r["unmatched_a"], r["unmatched_b"]), ([], []))

    def test_drum_confrontati_per_pitch(self):
        d36 = instrument("drums", 0, 36, [0], 80, 0.8, 0.8, is_drum=True)
        d36b = instrument("drums", 0, 36, [0], 80, 0.8, 0.8, is_drum=True)
        d51 = instrument("drums", 0, 51, [0], 200, 0.8, 0.8, is_drum=True)
        m = FC.InstrumentMatcher()
        self.assertAlmostEqual(m._instrument_similarity(d36, d36b), 1.0)
        self.assertAlmostEqual(m._instrument_similarity(d36, d51), 0.1)


class TestApiHttp(unittest.TestCase):
    """Verifica gli endpoint reali dell'app (skip se non è in esecuzione)."""

    BASE = os.environ.get("SAMPLELAB_URL", "http://localhost:5070")

    @classmethod
    def setUpClass(cls):
        try:
            urllib.request.urlopen(cls.BASE + "/fortissimo/example", timeout=4).read()
        except Exception as e:
            raise unittest.SkipTest(f"app non attiva su {cls.BASE} ({e})")

    def _get(self, path):
        with urllib.request.urlopen(self.BASE + path, timeout=120) as r:
            return json.loads(r.read().decode())

    def _post(self, path, payload):
        req = urllib.request.Request(self.BASE + path, data=json.dumps(payload).encode(),
                                     headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=120) as r:
            return json.loads(r.read().decode())

    def test_pagina_fortissimo(self):
        with urllib.request.urlopen(self.BASE + "/fortissimo", timeout=10) as r:
            self.assertEqual(r.status, 200)
            self.assertIn(b"Fortissimo Compare", r.read())

    def test_selftest_endpoint(self):
        d = self._get("/fortissimo/selftest")
        self.assertTrue(d["ok"], [c for c in d["checks"] if not c["ok"]])

    def test_compare_endpoint_con_esempio(self):
        ex = self._get("/fortissimo/example")
        d = self._post("/fortissimo/compare", {"a": ex["a"], "b": ex["b"]})
        self.assertTrue(d["ok"], d.get("error"))
        self.assertAlmostEqual(d["result"]["overall_score"], 0.910185, delta=1e-3)
        self.assertEqual(d["result"]["n_match"], 3)
        self.assertEqual(d["weights"]["midi"], 0.4)

    def test_compare_stesso_brano(self):
        """Stesso brano: 0.925 (tetto attuale, non 1.0 — vedi i test unitari)."""
        ex = self._get("/fortissimo/example")
        d = self._post("/fortissimo/compare", {"a": ex["a"], "b": ex["a"]})
        self.assertAlmostEqual(d["result"]["overall_score"], 0.925, places=6)

    def test_compare_pesi_non_validi(self):
        ex = self._get("/fortissimo/example")
        req = urllib.request.Request(
            self.BASE + "/fortissimo/compare",
            data=json.dumps({"a": ex["a"], "b": ex["b"],
                             "weights": {"midi": 0.5, "oneshot": 0.5, "presence": 0.5}}).encode(),
            headers={"Content-Type": "application/json"})
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            urllib.request.urlopen(req, timeout=30)
        self.assertEqual(ctx.exception.code, 400)

    def test_compare_payload_mancante(self):
        req = urllib.request.Request(self.BASE + "/fortissimo/compare", data=b"{}",
                                     headers={"Content-Type": "application/json"})
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            urllib.request.urlopen(req, timeout=30)
        self.assertEqual(ctx.exception.code, 400)

    def test_compare_payload_non_valido(self):
        """Note con pitch non numerico: l'API risponde 400, non 500."""
        req = urllib.request.Request(
            self.BASE + "/fortissimo/compare",
            data=json.dumps({"a": {"instruments": [{"instrument_name": "x",
                                                    "track": {"notes": [{"pitch": "abc"}]}}]},
                             "b": {"instruments": []}}).encode(),
            headers={"Content-Type": "application/json"})
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            urllib.request.urlopen(req, timeout=30)
        self.assertEqual(ctx.exception.code, 400)


if __name__ == "__main__":
    unittest.main(verbosity=2)

