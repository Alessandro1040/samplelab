"""
═══════════════════════════════════════════════════════════════════════════════
  FORTISSIMO COMPARE v3.0
  Modello di confronto tra output AudioAnalysis (MIDI + One-Shot)

  Confronta strumento-per-strumento con:
  - Matching per nome YAMNet + timbro audio
  - Analisi MIDI: note, timing, velocity, ritmo
  - Analisi One-Shot: timbro + VOLUME/LOUDNESS
  - NON penalizza a priori per numero diverso di strumenti

  Output: score globale [0,1] + dettaglio per strumento
═══════════════════════════════════════════════════════════════════════════════
"""

import numpy as np
import warnings
from dataclasses import dataclass, field
from typing import List, Dict, Tuple, Optional, Any
import json

warnings.filterwarnings('ignore')


# ═══════════════════════════════════════════════════════════════════════════════
# 1. STRUTTURE DATI (formato output del modello precedente YAMNet + Demucs)
# ═══════════════════════════════════════════════════════════════════════════════

@dataclass
class NoteEvent:
    """Singola nota MIDI"""
    pitch: int           # 0-127
    start: float         # tempo in secondi
    end: float
    velocity: int        # 0-127
    channel: int = 0


@dataclass
class InstrumentTrack:
    """Traccia MIDI di uno strumento"""
    name: str            # Nome rilevato da YAMNet
    program: int         # General MIDI program number
    channel: int
    notes: List[NoteEvent] = field(default_factory=list)
    is_drum: bool = False
    confidence: float = 1.0


@dataclass
class OneShotSample:
    """Campionamento one-shot di uno strumento"""
    instrument_name: str
    program: int
    pitch: int              # Pitch del campione (C5=72, C1=36, ecc.)
    audio: np.ndarray       # Waveform
    sr: int = 44100
    original_loudness: float = 0.0   # LUFS/RMS dello strumento nel mix originale
    features: Dict[str, Any] = field(default_factory=dict)


@dataclass
class AnalyzedInstrument:
    """
    Output del modello precedente per UN singolo strumento rilevato.
    Contiene sia il MIDI che il one-shot dello strumento.
    """
    instrument_name: str
    track: InstrumentTrack
    one_shot: OneShotSample
    separation_quality: float = 1.0   # Qualità separazione Demucs (0-1)


@dataclass
class AudioAnalysisOutput:
    """
    Output completo del modello precedente per un file audio.
    Contiene N strumenti rilevati.
    """
    instruments: List[AnalyzedInstrument]
    source_filename: str = ""
    global_tempo: float = 120.0
    duration: float = 0.0


# ═══════════════════════════════════════════════════════════════════════════════
# 2. MATCHING STRUMENTI (nome YAMNet + timbro audio)
# ═══════════════════════════════════════════════════════════════════════════════

class InstrumentMatcher:
    """
    Matcha strumenti tra due file audio analizzati.
    Usa nome YAMNet come primary key, con fallback su similarità timbrica.
    Supporta alias (es. "distorted guitar" = "electric guitar").
    """

    ALIASES = {
        "electric guitar": ["guitar", "distorted guitar", "clean guitar", "lead guitar"],
        "acoustic guitar": ["guitar", "steel guitar", "nylon guitar"],
        "piano": ["keyboard", "electric piano", "grand piano", "upright piano"],
        "synthesizer": ["synth", "synth lead", "synth pad", "synth bass", "electronic"],
        "drum": ["drums", "percussion", "drum kit", "trap"],
        "bass": ["bass guitar", "electric bass", "double bass", "sub bass"],
        "violin": ["strings", "viola", "cello", "string section"],
        "trumpet": ["brass", "horn", "trombone", "french horn"],
        "flute": ["woodwind", "clarinet", "oboe", "recorder"],
        "saxophone": ["sax", "alto sax", "tenor sax"],
        "voice": ["vocal", "singing", "choir", "speech", "rap"],
        "organ": ["hammond", "church organ", "electric organ"],
    }

    def __init__(self, threshold: float = 0.7):
        self.threshold = threshold

    def _normalize(self, name: str) -> str:
        return name.lower().strip().replace("_", " ").replace("-", " ")

    def _name_similarity(self, a: str, b: str) -> float:
        """Similarità tra nomi strumento (0-1)"""
        na, nb = self._normalize(a), self._normalize(b)
        if na == nb:
            return 1.0
        # Controlla alias
        for canonical, aliases in self.ALIASES.items():
            all_names = [canonical] + aliases
            if na in all_names and nb in all_names:
                return 1.0
        # Similarità parziale
        if na in nb or nb in na:
            return 0.85
        # Word overlap
        wa, wb = set(na.split()), set(nb.split())
        if wa & wb:
            return 0.5 + 0.3 * len(wa & wb) / max(len(wa), len(wb))
        # Jaccard caratteri
        ca, cb = set(na), set(nb)
        if ca & cb:
            return len(ca & cb) / len(ca | cb) * 0.3
        return 0.0

    def _timbre_features(self, shot: OneShotSample) -> np.ndarray:
        """Estrae feature timbriche compatte per matching"""
        audio = shot.audio
        if len(audio) == 0:
            return np.zeros(10)
        audio = audio / (np.max(np.abs(audio)) + 1e-10)
        feats = []
        # RMS
        feats.append(np.sqrt(np.mean(audio**2)))
        # ZCR
        feats.append(np.mean(np.abs(np.diff(np.sign(audio)))) / 2)
        # Bande spettrali
        n_fft = min(2048, len(audio))
        if len(audio) >= n_fft:
            spec = np.abs(np.fft.rfft(audio[:n_fft]))**2
            freqs = np.fft.rfftfreq(n_fft, 1/shot.sr)
            bands = [0, 100, 500, 2000, 8000, len(spec)]
            be = []
            for i in range(len(bands)-1):
                lo, hi = bands[i], bands[i+1]
                be.append(np.mean(spec[lo:hi]) if hi > lo else 0)
            be = np.array(be)
            if be.sum() > 0:
                be /= be.sum()
            feats.extend(be.tolist())
            feats.append(np.sum(freqs * spec) / (np.sum(spec) + 1e-10) / (shot.sr/2))
        else:
            feats.extend([0]*6)
            feats.append(0)
        return np.array(feats[:10])

    def _timbre_similarity(self, sa: OneShotSample, sb: OneShotSample) -> float:
        """Similarità timbrica tra due one-shot"""
        fa = self._timbre_features(sa)
        fb = self._timbre_features(sb)
        fa = fa / (np.linalg.norm(fa) + 1e-10)
        fb = fb / (np.linalg.norm(fb) + 1e-10)
        dist = np.linalg.norm(fa - fb)
        sim = max(0, 1.0 - dist / np.sqrt(2))
        pitch_bonus = max(0, 1.0 - abs(sa.pitch - sb.pitch) / 12.0) * 0.1
        return min(1.0, sim + pitch_bonus)

    def _instrument_similarity(self, ia: AnalyzedInstrument, 
                                ib: AnalyzedInstrument) -> float:
        """Similarità complessiva tra due strumenti"""
        ns = self._name_similarity(ia.instrument_name, ib.instrument_name)
        ts = self._timbre_similarity(ia.one_shot, ib.one_shot)
        # Se entrambi drum, match per pitch del campione
        if ia.track.is_drum and ib.track.is_drum:
            return 1.0 if ia.one_shot.pitch == ib.one_shot.pitch else 0.1
        if ns >= 0.9:
            return 0.8 * ns + 0.2 * ts
        elif ns >= 0.5:
            return 0.6 * ns + 0.4 * ts
        else:
            return 0.3 * ns + 0.7 * ts

    def match(self, list_a: List[AnalyzedInstrument],
              list_b: List[AnalyzedInstrument]) -> List[Tuple[Optional[AnalyzedInstrument], 
                                                              Optional[AnalyzedInstrument], 
                                                              float]]:
        """
        Matcha strumenti tra due liste.
        Restituisce coppie (inst_a, inst_b, similarity).
        """
        if not list_a and not list_b:
            return []
        if not list_a or not list_b:
            r = []
            for x in list_a:
                r.append((x, None, 0.0))
            for x in list_b:
                r.append((None, x, 0.0))
            return r

        n, m = len(list_a), len(list_b)
        sim = np.zeros((n, m))
        for i, ia in enumerate(list_a):
            for j, ib in enumerate(list_b):
                sim[i,j] = self._instrument_similarity(ia, ib)

        matched = []
        used_b = set()
        pairs = [(sim[i,j], i, j) for i in range(n) for j in range(m)]
        pairs.sort(reverse=True)
        used_a = set()
        for s, i, j in pairs:
            if i not in used_a and j not in used_b and s >= self.threshold:
                matched.append((list_a[i], list_b[j], s))
                used_a.add(i)
                used_b.add(j)

        for i, ia in enumerate(list_a):
            if i not in used_a:
                matched.append((ia, None, 0.0))
        for j, ib in enumerate(list_b):
            if j not in used_b:
                matched.append((None, ib, 0.0))

        return matched


# ═══════════════════════════════════════════════════════════════════════════════
# 3. CONFRONTO MIDI A LIVELLO DI TRACCIA
# ═══════════════════════════════════════════════════════════════════════════════

class TrackComparator:
    """Confronta due tracce MIDI dello stesso strumento"""

    def __init__(self, tempo_tolerance: float = 0.05, pitch_tolerance: int = 0):
        self.tempo_tol = tempo_tolerance
        self.pitch_tol = pitch_tolerance

    def compare(self, ta: InstrumentTrack, tb: InstrumentTrack) -> Dict[str, float]:
        """Confronto completo di due tracce MIDI"""
        na, nb = ta.notes, tb.notes
        if not na and not nb:
            return {"score": 1.0, "f1": 1.0, "timing": 1.0, "pitch": 1.0, 
                    "velocity": 1.0, "rhythm": 1.0}
        if not na or not nb:
            return {"score": 0.0, "f1": 0.0, "timing": 0.0, "pitch": 0.0,
                    "velocity": 0.0, "rhythm": 0.0}

        # Allineamento note greedy
        matched = []
        used_b = set()
        for a in sorted(na, key=lambda x: x.start):
            best_j, best_s, best_m = -1, -1, {}
            for j, b in enumerate(nb):
                if j in used_b:
                    continue
                td = abs(a.start - b.start)
                if td > self.tempo_tol * 3:
                    continue
                pd = abs(a.pitch - b.pitch)
                if pd > self.pitch_tol + 3:
                    continue
                tsc = max(0, 1.0 - td / max(self.tempo_tol, 0.01))
                psc = max(0, 1.0 - pd / 12.0)
                vsc = max(0, 1.0 - abs(a.velocity - b.velocity) / 127.0)
                dsc = max(0, 1.0 - abs((a.end-a.start)-(b.end-b.start)) / 2.0)
                ps = 0.35*tsc + 0.30*psc + 0.15*vsc + 0.20*dsc
                if ps > best_s:
                    best_s = ps
                    best_j = j
                    best_m = {"timing_sim": tsc, "pitch_sim": psc, "velocity_sim": vsc}
            if best_j >= 0 and best_s > 0.3:
                matched.append(best_m)
                used_b.add(best_j)

        prec = len(matched) / len(na) if na else 0
        rec = len(matched) / len(nb) if nb else 0
        f1 = 2*prec*rec/(prec+rec) if (prec+rec) > 0 else 0
        ts = np.mean([m["timing_sim"] for m in matched]) if matched else 0
        ps = np.mean([m["pitch_sim"] for m in matched]) if matched else 0
        vs = np.mean([m["velocity_sim"] for m in matched]) if matched else 0

        # Ritmo (istogrammi onset)
        dur = max(max(n.end for n in na), max(n.end for n in nb))
        dur = max(dur, 0.1)
        bins = 32
        ha, hb = np.zeros(bins), np.zeros(bins)
        for n in na:
            idx = min(int((n.start/dur)*bins), bins-1)
            ha[idx] += n.velocity/127.0
        for n in nb:
            idx = min(int((n.start/dur)*bins), bins-1)
            hb[idx] += n.velocity/127.0
        if ha.sum() > 0:
            ha /= ha.sum()
        if hb.sum() > 0:
            hb /= hb.sum()
        dot = np.dot(ha, hb)
        rhy = dot / (np.linalg.norm(ha)*np.linalg.norm(hb)+1e-10) if np.linalg.norm(ha)*np.linalg.norm(hb) > 0 else 0
        rhy = max(0, rhy)

        score = 0.25*f1 + 0.20*ts + 0.15*ps + 0.10*vs + 0.15*rhy
        return {"score": min(1.0, max(0.0, score)), "f1": f1, "timing": ts, 
                "pitch": ps, "velocity": vs, "rhythm": rhy}


# ═══════════════════════════════════════════════════════════════════════════════
# 4. CONFRONTO ONE-SHOT (con VOLUME / LOUDNESS)
# ═══════════════════════════════════════════════════════════════════════════════

class OneShotComparator:
    """
    Confronta one-shot samples con enfasi su volume/loudness.
    Il volume è una feature chiave per determinare "cosa succede" nel mix.
    """

    def __init__(self, sr: int = 44100, volume_weight: float = 0.3):
        self.sr = sr
        self.volume_weight = volume_weight

    def _extract_features(self, sample: OneShotSample) -> Dict[str, Any]:
        """Estrae feature audio con volume/loudness"""
        audio = sample.audio
        if len(audio) == 0:
            return {}
        peak = np.max(np.abs(audio))
        audio_n = audio / (peak + 1e-10) if peak > 0 else audio
        f = {}
        # VOLUME / LOUDNESS
        f["rms"] = np.sqrt(np.mean(audio**2))
        f["peak"] = peak
        f["crest"] = peak / (f["rms"] + 1e-10)
        f["orig_loud"] = sample.original_loudness
        f["loud_db"] = 20 * np.log10(f["rms"] + 1e-10)
        # TIMBRO
        n_fft = min(2048, len(audio_n))
        if len(audio_n) >= n_fft:
            spec = np.abs(np.fft.rfft(audio_n[:n_fft]))**2
            freqs = np.fft.rfftfreq(n_fft, 1/self.sr)
            f["mean_spec"] = spec / (np.sum(spec) + 1e-10)
            geo = np.exp(np.mean(np.log(spec + 1e-10)))
            f["flatness"] = geo / (np.mean(spec) + 1e-10)
            f["centroid"] = np.sum(freqs * spec) / (np.sum(spec) + 1e-10)
        return f

    def compare(self, sa: OneShotSample, sb: OneShotSample) -> Dict[str, float]:
        """Confronto completo di due one-shot"""
        fa = self._extract_features(sa)
        fb = self._extract_features(sb)
        if not fa or not fb:
            return {"score": 0.0, "volume_sim": 0.0, "timbre_sim": 0.0}

        # VOLUME
        vol_scores = []
        if "rms" in fa and "rms" in fb:
            ra, rb = fa["rms"], fb["rms"]
            if max(ra, rb) > 0:
                vol_scores.append(max(0, 1.0 - abs(ra-rb)/max(ra, rb)))
        if "orig_loud" in fa and "orig_loud" in fb:
            la, lb = fa["orig_loud"], fb["orig_loud"]
            if max(la, lb) > 0:
                vol_scores.append(max(0, 1.0 - abs(la-lb)/max(la, lb)))
        elif "loud_db" in fa and "loud_db" in fb:
            dbd = abs(fa["loud_db"] - fb["loud_db"])
            vol_scores.append(max(0, 1.0 - dbd / 60.0))
        if "crest" in fa and "crest" in fb:
            ca, cb = fa["crest"], fb["crest"]
            if max(ca, cb) > 0:
                vol_scores.append(max(0, 1.0 - abs(ca-cb)/max(ca, cb)))
        vsim = np.mean(vol_scores) if vol_scores else 0.0

        # TIMBRO
        tim_scores = []
        if "mean_spec" in fa and "mean_spec" in fb:
            sa_, sb_ = fa["mean_spec"], fb["mean_spec"]
            ml = min(len(sa_), len(sb_))
            sa_, sb_ = sa_[:ml], sb_[:ml]
            dot = np.dot(sa_, sb_)
            na, nb = np.linalg.norm(sa_), np.linalg.norm(sb_)
            if na > 0 and nb > 0:
                tim_scores.append(dot/(na*nb))
        if "flatness" in fa and "flatness" in fb:
            fa_, fb_ = fa["flatness"], fb["flatness"]
            if max(fa_, fb_) > 0:
                tim_scores.append(max(0, 1.0 - abs(fa_-fb_)/max(fa_, fb_, 0.001)))
        if "centroid" in fa and "centroid" in fb:
            ca, cb = fa["centroid"], fb["centroid"]
            if max(ca, cb) > 0:
                tim_scores.append(max(0, 1.0 - abs(ca-cb)/max(ca, cb)))
        tsim = np.mean(tim_scores) if tim_scores else 0.0

        vw, tw = self.volume_weight, 1.0 - self.volume_weight
        return {"score": vw*vsim + tw*tsim, "volume_sim": vsim, "timbre_sim": tsim,
                "rms_a": fa.get("rms",0), "rms_b": fb.get("rms",0),
                "loud_a": fa.get("orig_loud", fa.get("loud_db",0)),
                "loud_b": fb.get("orig_loud", fb.get("loud_db",0))}


# ═══════════════════════════════════════════════════════════════════════════════
# 5. MODELLO AGGREGATORE FINALE
# ═══════════════════════════════════════════════════════════════════════════════

class AudioSimilarityModel:
    """
    Modello completo che confronta due output AudioAnalysisOutput.

    Logica:
    1. Matcha strumenti per nome YAMNet + timbro
    2. Per ogni strumento matchato: confronta MIDI + One-Shot
    3. Per strumenti non matchati: score parziale basato su "mancanza"
    4. Aggrega ponderando per confidence/separation quality
    5. NON penalizza a priori per numero diverso di strumenti

    Pesi default:
    - midi: 40% (struttura, note, ritmo)
    - oneshot: 40% (timbro 70% + volume 30%)
    - presence: 20% (quanti strumenti sono in comune)
    """

    def __init__(self,
                 midi_weight: float = 0.4,
                 oneshot_weight: float = 0.4,
                 presence_weight: float = 0.2,
                 volume_weight: float = 0.3):
        assert abs(midi_weight + oneshot_weight + presence_weight - 1.0) < 1e-6
        self.midi_w = midi_weight
        self.oneshot_w = oneshot_weight
        self.presence_w = presence_weight
        self.matcher = InstrumentMatcher()
        self.track_comp = TrackComparator()
        # FIX SampleLab (11/09/2026): qui c'era "vol_weight=volume_weight",
        # ma OneShotComparator accetta "volume_weight" → TypeError a ogni
        # istanziazione di AudioSimilarityModel (il file non partiva nemmeno
        # con "python3 fortissimo_compare_v3.py"). Nome del parametro corretto.
        self.shot_comp = OneShotComparator(volume_weight=volume_weight)

    def compare(self, a: AudioAnalysisOutput, 
                b: AudioAnalysisOutput) -> Dict[str, Any]:
        """
        Confronto completo.
        Restituisce dict con:
        - overall_score: float [0,1]
        - midi_score: float [0,1]
        - oneshot_score: float [0,1]
        - presence_score: float [0,1]
        - details: list con dettaglio per strumento
        - unmatched_a: list strumenti solo in A
        - unmatched_b: list strumenti solo in B
        - n_a, n_b, n_match: contatori
        """
        matches = self.matcher.match(a.instruments, b.instruments)
        scores = []

        for ia, ib, ms in matches:
            if ia and ib:
                midi_r = self.track_comp.compare(ia.track, ib.track)
                shot_r = self.shot_comp.compare(ia.one_shot, ib.one_shot)
                inst_score = 0.5 * midi_r["score"] + 0.5 * shot_r["score"]
                w = (ia.separation_quality + ib.separation_quality) / 2
                scores.append({"score": inst_score, "weight": max(0.1, w), 
                               "name_a": ia.instrument_name, "name_b": ib.instrument_name,
                               "match_conf": ms, "midi": midi_r, "shot": shot_r})
            elif ia:
                scores.append({"score": 0.0, "weight": ia.separation_quality*0.5,
                               "name_a": ia.instrument_name, "name_b": None,
                               "match_conf": 0, "midi": None, "shot": None, "reason": "only_a"})
            elif ib:
                scores.append({"score": 0.0, "weight": ib.separation_quality*0.5,
                               "name_a": None, "name_b": ib.instrument_name,
                               "match_conf": 0, "midi": None, "shot": None, "reason": "only_b"})

        if not scores:
            return {"overall_score": 1.0, "midi_score": 1.0, "oneshot_score": 1.0,
                    "presence_score": 1.0, "details": [], "unmatched_a": [],
                    "unmatched_b": [], "n_a": 0, "n_b": 0, "n_match": 0}

        tw = sum(s["weight"] for s in scores)
        midi_scores = [s["midi"]["score"] for s in scores if s["midi"]]
        shot_scores = [s["shot"]["score"] for s in scores if s["shot"]]

        midi_s = np.average([s["midi"]["score"] for s in scores if s["midi"]],
                            weights=[s["weight"] for s in scores if s["midi"]]) if midi_scores else 0.0
        shot_s = np.average([s["shot"]["score"] for s in scores if s["shot"]],
                            weights=[s["weight"] for s in scores if s["shot"]]) if shot_scores else 0.0
        n_match = sum(1 for s in scores if s["match_conf"] > 0)
        n_total = len(scores)
        pres_s = n_match / n_total if n_total > 0 else 0.0
        overall_inst = sum(s["score"]*s["weight"] for s in scores) / tw if tw > 0 else 0
        overall = self.midi_w * midi_s + self.oneshot_w * shot_s + self.presence_w * pres_s * overall_inst

        return {"overall_score": round(min(1.0, max(0.0, overall)), 6),
                "midi_score": round(midi_s, 6),
                "oneshot_score": round(shot_s, 6),
                "presence_score": round(pres_s, 6),
                "details": scores,
                "unmatched_a": [s["name_a"] for s in scores if s.get("reason") == "only_a"],
                "unmatched_b": [s["name_b"] for s in scores if s.get("reason") == "only_b"],
                "n_a": len(a.instruments), "n_b": len(b.instruments), "n_match": n_match}

    def quick_score(self, a: AudioAnalysisOutput, b: AudioAnalysisOutput) -> float:
        """Versione rapida che restituisce solo lo score [0,1]"""
        return self.compare(a, b)["overall_score"]


# ═══════════════════════════════════════════════════════════════════════════════
# ESEMPIO D'USO
# ═══════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    # Esempio: crea due canzoni di test e confrontale

    def make_notes(p, pat, tempo=120, vel=100):
        bd = 60.0/tempo
        return [NoteEvent(p+pi, i*bd, i*bd+bd*0.8, vel) for i, pi in enumerate(pat)]

    def gen_pluck(f, d=0.1, sr=44100, amp=0.5):
        t = np.linspace(0, d, int(sr*d), endpoint=False)
        w = np.sin(2*np.pi*f*t) + 0.5*np.sin(2*np.pi*f*2*t)
        env = np.exp(-t*4)
        return w * env * amp

    # Canzone A: 3 strumenti
    insts_a = [
        AnalyzedInstrument("electric guitar",
            InstrumentTrack("electric guitar", 27, 0, make_notes(64, [0,2,4,2,0,-1,0,2])),
            OneShotSample("electric guitar", 27, 72, gen_pluck(440, amp=0.6), original_loudness=0.6)),
        AnalyzedInstrument("bass",
            InstrumentTrack("bass", 32, 1, make_notes(36, [0,0,7,0,5,0,7,0])),
            OneShotSample("bass", 32, 36, gen_pluck(110, amp=0.7), original_loudness=0.7)),
        AnalyzedInstrument("piano",
            InstrumentTrack("piano", 0, 2, make_notes(60, [0,4,7,4,0,-3,0,4])),
            OneShotSample("piano", 0, 72, gen_pluck(440, amp=0.5), original_loudness=0.5)),
    ]
    song_a = AudioAnalysisOutput(insts_a, "song_a.wav", 120, 4.0)

    # Canzone B: stessi strumenti ma piano più forte
    insts_b = [
        AnalyzedInstrument("electric guitar",
            InstrumentTrack("electric guitar", 27, 0, make_notes(64, [0,2,4,2,0,-1,0,2])),
            OneShotSample("electric guitar", 27, 72, gen_pluck(440, amp=0.6), original_loudness=0.6)),
        AnalyzedInstrument("bass",
            InstrumentTrack("bass", 32, 1, make_notes(36, [0,0,7,0,5,0,7,0])),
            OneShotSample("bass", 32, 36, gen_pluck(110, amp=0.7), original_loudness=0.7)),
        AnalyzedInstrument("piano",
            InstrumentTrack("piano", 0, 2, make_notes(60, [0,4,7,4,0,-3,0,4])),
            OneShotSample("piano", 0, 72, gen_pluck(440, amp=0.9), original_loudness=0.9)),
    ]
    song_b = AudioAnalysisOutput(insts_b, "song_b.wav", 120, 4.0)

    # Confronta
    model = AudioSimilarityModel()
    result = model.compare(song_a, song_b)

    print("═" * 60)
    print("  FORTISSIMO COMPARE v3.0 - RISULTATO")
    print("═" * 60)
    print(f"  Overall Score:  {result['overall_score']}")
    print(f"  MIDI Score:     {result['midi_score']}")
    print(f"  OneShot Score:  {result['oneshot_score']}")
    print(f"  Presence Score: {result['presence_score']}")
    print(f"  Matchati:       {result['n_match']}/{result['n_a']} strumenti")
    print("═" * 60)
    print("\nDettaglio per strumento:")
    for d in result['details']:
        print(f"  {d['name_a']} vs {d['name_b']}: score={d['score']:.3f}")
