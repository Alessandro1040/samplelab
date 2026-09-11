"""Test di MIDI Studio: parsing/confronto MIDI (mido) e API HTTP reali.

Esecuzione (dalla cartella midi_studio):
    python3 -m unittest -v test_midi_studio
I test HTTP girano solo se l'app è attiva (default http://localhost:5080,
sovrascrivibile con MIDI_STUDIO_URL).
"""
import json
import os
import sys
import tempfile
import unittest
import urllib.error
import urllib.parse
import urllib.request

import mido

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE_DIR)
import midi_analysis as ma  # noqa: E402

TMP = tempfile.mkdtemp(prefix="midistudio_test_")


def make_midi(path, notes, name="Piano/Guitar", channel=0, tempo=500000, ticks=480, program=0):
    """Scrive un .mid di test: notes = [(pitch, start_beat, length_beat, velocity)].

    Attenzione: in un file MIDI i tempi dei messaggi sono **delta**, non assoluti.
    """
    mid = mido.MidiFile(ticks_per_beat=ticks)
    meta = mido.MidiTrack()
    mid.tracks.append(meta)
    meta.append(mido.MetaMessage("set_tempo", tempo=tempo))
    track = mido.MidiTrack()
    mid.tracks.append(track)
    if name:
        track.append(mido.MetaMessage("track_name", name=name))
    if program is not None:
        track.append(mido.Message("program_change", program=program, channel=channel))
    eventi = []
    for pitch, start, length, vel in notes:
        on, off = int(start * ticks), int((start + length) * ticks)
        eventi.append((on, mido.Message("note_on", note=pitch, velocity=vel, channel=channel)))
        eventi.append((off, mido.Message("note_off", note=pitch, velocity=0, channel=channel,
                                         time=off - on)))
    eventi.sort(key=lambda e: e[0])
    ultimo = 0
    for assoluto, msg in eventi:
        msg.time = assoluto - ultimo
        track.append(msg)
        ultimo = assoluto
    mid.save(path)
    return path


A_MID = make_midi(os.path.join(TMP, "a.mid"),
                  [(60, 0, 1, 100), (64, 1, 1, 100), (67, 2, 1, 100), (72, 3, 1, 100)])
B_MID = make_midi(os.path.join(TMP, "b.mid"),
                  [(60, 0, 1, 100), (64, 1, 1, 100), (67, 2, 1, 100), (71, 3, 1, 100)])
KICK_MID = make_midi(os.path.join(TMP, "kick.mid"), [(36, i, 0.1, 110) for i in range(4)],
                     name="Kick", channel=9)
SLOW_MID = make_midi(os.path.join(TMP, "slow.mid"), [(60, 0, 1, 100), (62, 1, 1, 100)],
                     tempo=1000000)  # 60 bpm


class TestParsing(unittest.TestCase):
    def test_tempi_a_120bpm(self):
        info = ma.parse_midi(A_MID)
        self.assertEqual(info["tempo_bpm"], 120.0)
        self.assertEqual(info["duration"], 2.0)  # 4 note da un beat a 120 bpm
        self.assertEqual(len(info["tracks"]), 1)
        tr = info["tracks"][0]
        self.assertEqual(tr["note_count"], 4)
        self.assertEqual([n["start"] for n in tr["notes"]], [0.0, 0.5, 1.0, 1.5])
        self.assertEqual([n["end"] for n in tr["notes"]], [0.5, 1.0, 1.5, 2.0])
        self.assertEqual((tr["pitch_min_name"], tr["pitch_max_name"]), ("C4", "C5"))

    def test_tempo_lento(self):
        """60 bpm: un beat = 1 secondo (verifica la tempo map, non il default)."""
        info = ma.parse_midi(SLOW_MID)
        self.assertEqual(info["tempo_bpm"], 60.0)
        self.assertEqual([n["start"] for n in info["tracks"][0]["notes"]], [0.0, 1.0])

    def test_canale_10_diventa_drum(self):
        info = ma.parse_midi(KICK_MID)
        tr = info["tracks"][0]
        self.assertTrue(tr["is_drum"])
        self.assertEqual(tr["instrument"], "drum")

    def test_mapping_nomi_traccia(self):
        casi = {"Kick": ("drum", True), "Snare": ("drum", True), "Hi-Hat": ("drum", True),
                "Piano/Guitar": ("piano", False), "Sub Bass": ("bass", False),
                "Synth/FX": ("synthesizer", False), "Brass": ("trumpet", False),
                "Pad/Strings": ("piano", False), "Tonal": ("piano", False)}
        for nome, atteso in casi.items():
            with self.subTest(nome=nome):
                self.assertEqual(ma.track_label(nome, None, 0), atteso)

    def test_nomi_tecnici_generici(self):
        """Gli id del multi-traccia (s0, s1, track 3) non sono nomi di strumento:
        vengono trattati come generici → l'abbinamento usa timbro/pitch."""
        for nome in ("s0", "s1", "track 3", "Source_2", ""):
            with self.subTest(nome=nome):
                self.assertEqual(ma.track_label(nome, None, 0), ("unknown", False))

    def test_confronto_multitraccia_con_se_stesso(self):
        """File multi-traccia con tracce s0..sN: si abbinano tutte (nome generico)."""
        mid = mido.MidiFile(ticks_per_beat=480)
        meta = mido.MidiTrack()
        mid.tracks.append(meta)
        meta.append(mido.MetaMessage("set_tempo", tempo=500000))
        for idx, pitch in enumerate((60, 64)):
            tr = mido.MidiTrack()
            mid.tracks.append(tr)
            tr.append(mido.MetaMessage("track_name", name=f"s{idx}"))
            for beat in range(3):
                tr.append(mido.Message("note_on", note=pitch, velocity=90, time=0))
                tr.append(mido.Message("note_off", note=pitch, velocity=0, time=480))
        path = os.path.join(TMP, "multi.mid")
        mid.save(path)
        out = ma.compare_midi(path, path)
        self.assertEqual(out["a"]["tracks"][0]["instrument"], "unknown")
        self.assertEqual(out["result"]["n_match"], 2)

    def test_fallback_program_gm(self):
        """Senza nome utile decide il program General MIDI."""
        self.assertEqual(ma.track_label("", 32, 0)[0], "bass")
        self.assertEqual(ma.track_label("", 0, 0)[0], "piano")
        self.assertEqual(ma.track_label("", 89, 0)[0], "synthesizer")

    def test_traccia_vuota_ignorata(self):
        """La traccia dei soli metadati (tempo) non diventa uno strumento."""
        mid = mido.MidiFile(ticks_per_beat=480)
        meta = mido.MidiTrack()
        mid.tracks.append(meta)
        meta.append(mido.MetaMessage("set_tempo", tempo=500000))
        solo_note = mido.MidiTrack()
        mid.tracks.append(solo_note)
        solo_note.append(mido.Message("note_on", note=60, velocity=100, time=0))
        solo_note.append(mido.Message("note_off", note=60, velocity=0, time=480))
        path = os.path.join(TMP, "solo_meta.mid")
        mid.save(path)
        self.assertEqual(len(ma.parse_midi(path)["tracks"]), 1)

    def test_nota_senza_note_off(self):
        mid = mido.MidiFile(ticks_per_beat=480)
        tr = mido.MidiTrack()
        mid.tracks.append(tr)
        tr.append(mido.Message("note_on", note=64, velocity=90, time=0))
        path = os.path.join(TMP, "aperta.mid")
        mid.save(path)
        n = ma.parse_midi(path)["tracks"][0]["notes"][0]
        self.assertEqual((n["pitch"], n["start"], n["end"]), (64, 0.0, 0.0))

    def test_note_on_velocity_zero_e_note_off(self):
        mid = mido.MidiFile(ticks_per_beat=480)
        tr = mido.MidiTrack()
        mid.tracks.append(tr)
        tr.append(mido.Message("note_on", note=60, velocity=100, time=0))
        tr.append(mido.Message("note_on", note=60, velocity=0, time=480))  # = note off
        path = os.path.join(TMP, "velzero.mid")
        mid.save(path)
        notes = ma.parse_midi(path)["tracks"][0]["notes"]
        self.assertEqual(len(notes), 1)
        self.assertEqual(notes[0]["end"], 0.5)


class TestConfronto(unittest.TestCase):
    """Il confronto usa il modello Fortissimo Compare v3 in repo."""

    def test_stesso_file_tetto_0925(self):
        """Nota: il modello non arriva a 1.0 (il blocco MIDI si ferma a 0.85)."""
        r = ma.compare_midi(A_MID, A_MID)["result"]
        self.assertAlmostEqual(r["overall_score"], 0.925, places=6)
        self.assertEqual((r["n_a"], r["n_b"], r["n_match"]), (1, 1, 1))
        self.assertEqual((r["unmatched_a"], r["unmatched_b"]), ([], []))

    def test_una_nota_diversa_abbassa_lo_score(self):
        uguale = ma.compare_midi(A_MID, A_MID)["result"]["overall_score"]
        diverso = ma.compare_midi(A_MID, B_MID)
        self.assertLess(diverso["result"]["overall_score"], uguale)
        self.assertAlmostEqual(diverso["result"]["overall_score"], 0.714633, delta=1e-4)
        self.assertEqual(diverso["result"]["n_match"], 1)
        self.assertEqual(diverso["a"]["n_notes"], 4)
        self.assertEqual(diverso["b"]["tracks"][0]["pitch_max_name"], "B4")

    def test_strumenti_diversi_non_si_matcheano(self):
        out = ma.compare_midi(A_MID, KICK_MID)
        self.assertEqual(out["result"]["n_match"], 0)
        self.assertEqual(out["result"]["unmatched_b"], ["drum"])
        self.assertEqual(out["result"]["overall_score"], 0.0)
        self.assertTrue(out["b"]["tracks"][0]["is_drum"])

    def test_pesi_devono_sommare_uno(self):
        with self.assertRaises(AssertionError):
            ma.compare_midi(A_MID, B_MID, {"midi": 0.6, "oneshot": 0.6, "presence": 0.3})

    def test_pesi_cambiano_il_risultato(self):
        base = ma.compare_midi(A_MID, B_MID)["result"]["overall_score"]
        solo_midi = ma.compare_midi(A_MID, B_MID,
                                    {"midi": 1.0, "oneshot": 0.0, "presence": 0.0})["result"]
        self.assertAlmostEqual(solo_midi["overall_score"], solo_midi["midi_score"], places=6)
        self.assertNotAlmostEqual(solo_midi["overall_score"], base, places=4)

    def test_describe_completo(self):
        d = ma.describe(A_MID)
        self.assertEqual((d["n_tracks"], d["n_notes"]), (1, 4))
        tr = d["tracks"][0]
        for chiave in ("name", "instrument", "is_drum", "channel", "note_count",
                       "pitch_min_name", "pitch_max_name", "program"):
            self.assertIn(chiave, tr)
        self.assertNotIn("notes", tr)  # describe non porta l'elenco note


BASE_URL = os.environ.get("MIDI_STUDIO_URL", "http://localhost:5080")


def multipart(path, fields, files):
    """POST multipart/form-data senza dipendenze esterne."""
    boundary = "----midistudio-test-boundary"
    body = b""
    for k, v in fields.items():
        body += (f'--{boundary}\r\nContent-Disposition: form-data; name="{k}"\r\n\r\n{v}\r\n').encode()
    for k, (fname, data) in files.items():
        body += (f'--{boundary}\r\nContent-Disposition: form-data; name="{k}"; '
                 f'filename="{fname}"\r\nContent-Type: audio/midi\r\n\r\n').encode() + data + b"\r\n"
    body += f"--{boundary}--\r\n".encode()
    req = urllib.request.Request(BASE_URL + path, data=body,
                                 headers={"Content-Type": f"multipart/form-data; boundary={boundary}"})
    try:
        with urllib.request.urlopen(req, timeout=180) as r:
            return r.status, json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read().decode())


class TestApi(unittest.TestCase):
    """Endpoint reali dell'app in esecuzione (skip se non è attiva)."""

    @classmethod
    def setUpClass(cls):
        try:
            urllib.request.urlopen(BASE_URL + "/api/health", timeout=4).read()
        except Exception as e:
            raise unittest.SkipTest(f"MIDI Studio non attivo su {BASE_URL} ({e})")

    def _get(self, path, raw=False):
        with urllib.request.urlopen(BASE_URL + path, timeout=180) as r:
            data = r.read()
            return data if raw else json.loads(data.decode())

    def _delete(self, name):
        urllib.request.urlopen(urllib.request.Request(
            BASE_URL + "/api/delete/" + urllib.parse.quote(name), method="DELETE"), timeout=30)

    def test_health(self):
        d = self._get("/api/health")
        self.assertEqual(d["app"], "MIDI Studio")
        self.assertTrue(d["model_found"])
        self.assertEqual(d["model"], "fortissimo_compare_v3.py")

    def test_pagina_e_estrattore(self):
        for path, atteso in (("/", b"MIDI Studio"), ("/extract", b"FORTISSIMO PRO")):
            with self.subTest(path=path):
                with urllib.request.urlopen(BASE_URL + path, timeout=30) as r:
                    self.assertEqual(r.status, 200)
                    self.assertIn(atteso, r.read())

    def test_test_audio_e_un_wav(self):
        data = self._get("/api/test-audio", raw=True)
        self.assertEqual(data[:4], b"RIFF")
        self.assertEqual(data[8:12], b"WAVE")
        self.assertGreater(len(data), 100000)

    def test_ciclo_completo_salva_confronta_cancella(self):
        st, saved_a = multipart("/api/save-midi", {"name": "test_api_a.mid"},
                                {"file": ("test_api_a.mid", open(A_MID, "rb").read())})
        self.assertEqual(st, 200, saved_a)
        st, saved_b = multipart("/api/save-midi", {"name": "test_api_b.mid"},
                                {"file": ("test_api_b.mid", open(B_MID, "rb").read())})
        self.assertEqual(st, 200, saved_b)
        nome_a, nome_b = saved_a["file"]["name"], saved_b["file"]["name"]
        self.addCleanup(self._delete, nome_a)
        self.addCleanup(self._delete, nome_b)

        nomi = [f["name"] for f in self._get("/api/files")["files"]]
        self.assertIn(nome_a, nomi)
        self.assertIn(nome_b, nomi)

        st, d = multipart("/api/compare", {"a_name": nome_a, "b_name": nome_b}, {})
        self.assertEqual(st, 200, d)
        self.assertAlmostEqual(d["result"]["overall_score"], 0.714633, delta=1e-4)
        self.assertEqual((d["a_file"], d["b_file"]), (nome_a, nome_b))

    def test_compare_upload_diretto(self):
        st, d = multipart("/api/compare",
                          {"w_midi": "0.4", "w_oneshot": "0.4", "w_presence": "0.2", "w_volume": "0.3"},
                          {"a": ("test_upload_a.mid", open(A_MID, "rb").read()),
                           "b": ("test_upload_b.mid", open(B_MID, "rb").read())})
        self.assertEqual(st, 200, d)
        self.assertAlmostEqual(d["result"]["overall_score"], 0.714633, delta=1e-4)
        self.addCleanup(self._delete, d["a_file"])
        self.addCleanup(self._delete, d["b_file"])

    def test_compare_stesso_file(self):
        st, d = multipart("/api/compare", {}, {"a": ("test_same.mid", open(A_MID, "rb").read()),
                                               "b": ("test_same.mid", open(A_MID, "rb").read())})
        self.assertEqual(st, 200, d)
        self.assertAlmostEqual(d["result"]["overall_score"], 0.925, places=6)
        self.addCleanup(self._delete, d["a_file"])
        self.addCleanup(self._delete, d["b_file"])

    def test_errori_400_e_404(self):
        st, d = multipart("/api/compare", {}, {})
        self.assertEqual(st, 400)
        self.assertIn("manca il file", d["error"])

        st, d = multipart("/api/compare", {"a_name": "x.mid", "b_name": "y.mid",
                                           "w_midi": "0.6", "w_oneshot": "0.6",
                                           "w_presence": "0.3"}, {})
        self.assertEqual(st, 400)
        self.assertIn("sommare 1.0", d["error"])

        st, d = multipart("/api/compare", {"a_name": "non_esiste.mid",
                                           "b_name": "non_esiste.mid"}, {})
        self.assertEqual(st, 404)

        st, d = multipart("/api/compare", {}, {"a": ("rotto.mid", b"non e un midi"),
                                               "b": ("ok.mid", open(A_MID, "rb").read())})
        self.assertEqual(st, 400)
        self.assertIn("non valido", d["error"])
        self.addCleanup(self._delete, "rotto.mid")


if __name__ == "__main__":
    unittest.main(verbosity=2)
