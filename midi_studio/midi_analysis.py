"""MIDI → modello Fortissimo: parsing dei file .mid e confronto.

Modulo autonomo (usa `mido` e il modello `fortissimo_compare_v3.py` della repo):

- `parse_midi(path)`   → tracce, note in secondi, tempo
- `describe(path)`     → riepilogo leggibile per l'interfaccia
- `to_analysis(path)`  → `AudioAnalysisOutput` del modello (uno strumento per traccia)
- `compare_midi(a, b)` → risultato del modello (score + dettaglio per strumento)

Il modello v3 confronta due `AudioAnalysisOutput`, cioè MIDI **+** one-shot audio.
I file .mid non contengono audio, quindi il one-shot viene **sintetizzato** dal
MIDI (tono pluck sul pitch dominante della traccia, ampiezza = velocity media)
mentre il blocco MIDI usa le note reali: è la stessa convenzione del demo del
modello e del builder JSON di SampleLab.
"""
import importlib.util
import os
import re
import threading

import mido

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
MODEL_PATH = os.path.join(os.path.dirname(BASE_DIR), "fortissimo_compare_v3.py")

_MODEL = None
_MODEL_LOCK = threading.Lock()


def load_model():
    """Carica (una sola volta) fortissimo_compare_v3.py dal repo."""
    global _MODEL
    with _MODEL_LOCK:
        if _MODEL is None:
            spec = importlib.util.spec_from_file_location("fortissimo_compare_v3", MODEL_PATH)
            if spec is None or spec.loader is None:
                raise RuntimeError(f"Modello non trovato: {MODEL_PATH}")
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            _MODEL = mod
    return _MODEL


# ── nomi strumento per il modello ─────────────────────────────────────────────
# L'estrattore chiama le tracce con nomi come "Kick", "Piano/Guitar": qui vengono
# ricondotti ai nomi usati dal matching del modello (ALIASES di InstrumentMatcher).
TRACK_NAME_MAP = {
    "kick": ("drum", True),
    "snare": ("drum", True),
    "hi-hat": ("drum", True),
    "hihat": ("drum", True),
    "hat": ("drum", True),
    "drums": ("drum", True),
    "perc": ("drum", True),
    "sub bass": ("bass", False),
    "bass": ("bass", False),
    "piano/guitar": ("piano", False),
    "guitar": ("electric guitar", False),
    "piano": ("piano", False),
    "pad/strings": ("piano", False),
    "synth/fx": ("synthesizer", False),
    "brass": ("trumpet", False),
    "tonal": ("piano", False),
    "voice": ("voice", False),
}

# General MIDI program (0-127) → nome modello. Il primo blocco che contiene il
# programma vince; se non c'è corrispondenza si usa "unknown".
GM_FAMILIES = (
    (range(0, 8), "piano"),
    (range(8, 16), "piano"),
    (range(16, 24), "organ"),
    (range(24, 32), "electric guitar"),
    (range(32, 40), "bass"),
    (range(40, 48), "violin"),
    (range(48, 56), "violin"),
    (range(56, 64), "trumpet"),
    (range(64, 72), "saxophone"),
    (range(72, 80), "flute"),
    (range(80, 96), "synthesizer"),
    (range(104, 112), "electric guitar"),
    (range(112, 120), "drum"),
)


# Traccia con nome tecnico ("s0", "s1", "track 3"): il file multi-traccia creato
# dall'estrattore usa gli id delle sorgenti, non i nomi degli strumenti.
GENERIC_TRACK_RE = re.compile(r"^(?:s|t|src|source|track|traccia)[\s_\-]*\d+$", re.IGNORECASE)


def track_label(name, program, channel):
    """(nome per il modello, is_drum) da nome traccia, program GM e canale."""
    raw = (name or "").strip()
    if GENERIC_TRACK_RE.match(raw):
        # "s0", "s1", "track 3": sono id tecnici del file multi-traccia, non
        # dicono nulla sullo strumento → si abbina per timbro/pitch.
        raw = ""
    is_drum = (channel == 9) or (program is not None and 112 <= program <= 119)
    key = raw.lower().replace("_", " ").replace("-", " ")
    for k, (mapped, drum) in TRACK_NAME_MAP.items():
        if k in key:
            return mapped, (drum or is_drum)
    if program is not None:
        for rng, mapped in GM_FAMILIES:
            if program in rng:
                return mapped, is_drum
    if is_drum:
        return "drum", True
    return (raw or "unknown"), is_drum


def note_name(pitch):
    """72 → 'C5' (per l'interfaccia)."""
    names = ("C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B")
    return f"{names[int(pitch) % 12]}{int(pitch) // 12 - 1}"


def _tempo_map(mid):
    """Eventi (tick assoluto, tempo µs/beat) di tutti i canali, in ordine."""
    events = []
    for track in mid.tracks:
        tick = 0
        for msg in track:
            tick += msg.time
            if msg.type == "set_tempo":
                events.append((tick, msg.tempo))
    events.sort(key=lambda x: x[0])
    if not events or events[0][0] > 0:
        events.insert(0, (0, 500000))
    return events


def _tick_converter(mid, events):
    """Restituisce tick→secondi contando i cambi di tempo."""
    tpb = mid.ticks_per_beat or 480
    starts = [0.0]
    for i in range(1, len(events)):
        delta = events[i][0] - events[i - 1][0]
        starts.append(starts[-1] + delta * events[i - 1][1] / 1e6 / tpb)

    def to_seconds(tick):
        idx = 0
        for i, (t, _) in enumerate(events):
            if t <= tick:
                idx = i
            else:
                break
        t0, tempo = events[idx]
        return starts[idx] + (tick - t0) * tempo / 1e6 / tpb

    return to_seconds


def parse_midi(path):
    """Legge un .mid e restituisce tracce con note in secondi, tempo e durata."""
    mid = mido.MidiFile(path)
    events = _tempo_map(mid)
    to_seconds = _tick_converter(mid, events)
    bpm = 60_000_000 / events[0][1] if events else 120.0
    tracks = []
    duration = 0.0

    for index, track in enumerate(mid.tracks):
        name = (track.name or "").strip()
        program = None
        notes = []
        open_notes = {}
        tick = 0
        for msg in track:
            tick += msg.time
            if msg.type == "track_name":
                name = (msg.name or "").strip() or name
            elif msg.type == "program_change" and program is None:
                program = int(msg.program)
            elif msg.type == "note_on" and msg.velocity > 0:
                open_notes.setdefault((msg.channel, msg.note), []).append((tick, int(msg.velocity)))
            elif msg.type == "note_off" or (msg.type == "note_on" and msg.velocity == 0):
                stack = open_notes.get((msg.channel, msg.note))
                if stack:
                    start_tick, vel = stack.pop(0)
                    start, end = to_seconds(start_tick), to_seconds(tick)
                    notes.append({"pitch": int(msg.note), "channel": int(msg.channel),
                                  "start": round(start, 4), "end": round(max(end, start), 4),
                                  "velocity": vel})
        # note rimaste senza note_off: chiuse all'ultimo tick visto
        for (channel, pitch), stack in open_notes.items():
            for start_tick, vel in stack:
                start = to_seconds(start_tick)
                notes.append({"pitch": int(pitch), "channel": int(channel),
                              "start": round(start, 4), "end": round(start, 4), "velocity": vel})
        if not notes:
            continue  # traccia vuota (es. solo tempo): il modello non la usa

        notes.sort(key=lambda n: n["start"])
        channels = sorted({n["channel"] for n in notes})
        pitches = [n["pitch"] for n in notes]
        instrument, is_drum = track_label(name, program, channels[0])
        duration = max(duration, max(n["end"] for n in notes))
        tracks.append({
            "index": index,
            "name": name or f"Traccia {index}",
            "instrument": instrument,
            "is_drum": is_drum,
            "channel": channels[0],
            "program": program,
            "note_count": len(notes),
            "pitch_min": min(pitches), "pitch_max": max(pitches),
            "pitch_min_name": note_name(min(pitches)),
            "pitch_max_name": note_name(max(pitches)),
            "notes": notes,
        })

    return {"file": os.path.basename(path), "ticks_per_beat": mid.ticks_per_beat,
            "tempo_bpm": round(bpm, 2), "duration": round(duration, 3), "tracks": tracks}


def synth_pluck(freq, amp=0.5, duration=0.1, sr=44100, harmonics=(1.0, 0.5)):
    """One-shot sintetico (stessa formula di gen_pluck dell'esempio del modello)."""
    import numpy as np
    n = max(1, int(sr * duration))
    t = np.linspace(0, duration, n, endpoint=False)
    w = np.sin(2 * np.pi * freq * t)
    for i, h in enumerate(harmonics, start=2):
        w = w + float(h) * np.sin(2 * np.pi * freq * i * t)
    return w * np.exp(-t * 4) * amp


def dominant_pitch(notes):
    """Pitch più frequente, usato per il one-shot sintetico della traccia."""
    counts = {}
    for n in notes:
        counts[n["pitch"]] = counts.get(n["pitch"], 0) + 1
    return max(counts.items(), key=lambda kv: (kv[1], kv[0]))[0]


def to_analysis(path, sr=44100):
    """Costruisce l'`AudioAnalysisOutput` del modello a partire da un .mid."""
    mod = load_model()
    info = parse_midi(path)
    instruments = []
    for tr in info["tracks"]:
        notes = [mod.NoteEvent(pitch=n["pitch"], start=n["start"], end=n["end"],
                               velocity=n["velocity"]) for n in tr["notes"]]
        track = mod.InstrumentTrack(name=tr["instrument"], program=tr["program"] or 0,
                                    channel=tr["channel"], notes=notes,
                                    is_drum=tr["is_drum"], confidence=1.0)
        pitch = dominant_pitch(tr["notes"])
        vel = sum(n["velocity"] for n in tr["notes"]) / len(tr["notes"])
        amp = min(0.9, max(0.05, vel / 127.0))
        shot = mod.OneShotSample(instrument_name=tr["instrument"], program=tr["program"] or 0,
                                 pitch=pitch, audio=synth_pluck(440.0 * 2 ** ((pitch - 69) / 12.0),
                                                               amp=amp, sr=sr),
                                 sr=sr, original_loudness=vel / 127.0)
        instruments.append(mod.AnalyzedInstrument(instrument_name=tr["instrument"], track=track,
                                                 one_shot=shot, separation_quality=1.0))
    return mod.AudioAnalysisOutput(instruments=instruments,
                                   source_filename=info["file"],
                                   global_tempo=info["tempo_bpm"],
                                   duration=info["duration"])


def describe(path):
    """Riepilogo di un .mid per l'interfaccia (senza l'elenco note)."""
    info = parse_midi(path)
    return {"file": info["file"], "tempo_bpm": info["tempo_bpm"],
            "duration": info["duration"], "ticks_per_beat": info["ticks_per_beat"],
            "n_tracks": len(info["tracks"]),
            "n_notes": sum(tr["note_count"] for tr in info["tracks"]),
            "tracks": [{k: v for k, v in tr.items() if k != "notes"} for tr in info["tracks"]]}


def _jsonable(obj):
    """Rende serializzabili in JSON i tipi numpy del modello."""
    import numpy as np
    if isinstance(obj, dict):
        return {k: _jsonable(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_jsonable(v) for v in obj]
    if isinstance(obj, np.ndarray):
        return obj.tolist()
    if isinstance(obj, np.bool_):
        return bool(obj)
    if isinstance(obj, np.floating):
        return float(obj)
    if isinstance(obj, np.integer):
        return int(obj)
    return obj


DEFAULT_WEIGHTS = {"midi": 0.4, "oneshot": 0.4, "presence": 0.2, "volume": 0.3}


def compare_midi(path_a, path_b, weights=None):
    """Confronta due .mid con il modello Fortissimo: score + riepiloghi."""
    mod = load_model()
    w = dict(DEFAULT_WEIGHTS)
    for k, v in (weights or {}).items():
        if k in w and v is not None:
            w[k] = float(v)
    model = mod.AudioSimilarityModel(midi_weight=w["midi"], oneshot_weight=w["oneshot"],
                                     presence_weight=w["presence"], volume_weight=w["volume"])
    result = model.compare(to_analysis(path_a), to_analysis(path_b))
    return {"result": _jsonable(result), "weights": w,
            "a": describe(path_a), "b": describe(path_b)}
