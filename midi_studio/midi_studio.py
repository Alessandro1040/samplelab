#!/usr/bin/env python3
"""MIDI Studio — app locale per estrarre MIDI da un audio e confrontare due MIDI.

- **Estrazione MIDI**: pagina `extractor.html` (JS puro, gira nel browser: l'audio
  non lascia il computer) servita su `/extract`; i `.mid` generati vengono
  salvati automaticamente in `files/`.
- **Confronto MIDI**: `POST /api/compare` legge i `.mid` con `mido` e usa il
  modello `fortissimo_compare_v3.py` della repo (vedi `midi_analysis.py`).
- **Porta 5080** (SampleLab usa 5070), server waitress, avviabile all'accensione
  con il LaunchAgent `install_autostart.sh`.

Uso manuale:  python3 midi_studio.py     →  http://localhost:5080
"""
import os
import socket
import time
from flask import Flask, jsonify, request, send_file, send_from_directory

import midi_analysis as ma

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
FILES_DIR = os.path.join(BASE_DIR, "files")
os.makedirs(FILES_DIR, exist_ok=True)
DEFAULT_PORT = int(os.environ.get("MIDI_STUDIO_PORT") or 5080)
MIDI_EXT = (".mid", ".midi", ".kar")
AUDIO_EXT = (".wav", ".mp3", ".m4a", ".flac", ".ogg", ".aiff", ".aif")

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 512 * 1024 * 1024


@app.after_request
def _no_cache_html(resp):
    """Le pagine HTML non devono restare in cache: dopo una modifica al codice
    il browser deve servire subito la versione nuova."""
    if resp.mimetype == "text/html":
        resp.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
        resp.headers["Pragma"] = "no-cache"
        resp.headers["Expires"] = "0"
    return resp


# ── helper ────────────────────────────────────────────────────────────────────
def safe_name(name, fallback="caricato.mid"):
    """Nome file senza percorsi (non si esce mai da files/)."""
    base = os.path.basename(str(name or "").replace("\\", "/")).strip()
    base = "".join(c for c in base if c.isalnum() or c in " ._-()[]#")
    return (base or fallback)[:120]


def unique_name(name):
    """Nome libero dentro files/ (aggiunge ' (2)' se esiste già)."""
    base, ext = os.path.splitext(name)
    candidate, i = name, 2
    while os.path.exists(os.path.join(FILES_DIR, candidate)):
        candidate = f"{base} ({i}){ext}"
        i += 1
    return candidate


def save_upload(storage):
    """Salva un file caricato in files/ e restituisce il nome finale."""
    fallback = "caricato.mid" if (storage.filename or "").lower().endswith(MIDI_EXT) else "caricato.wav"
    name = unique_name(safe_name(storage.filename, fallback))
    storage.save(os.path.join(FILES_DIR, name))
    return name


def file_entry(name):
    """Metadati di un file salvato (per l'elenco dell'interfaccia)."""
    path = os.path.join(FILES_DIR, name)
    st = os.stat(path)
    kind = "midi" if name.lower().endswith(MIDI_EXT) else "audio"
    entry = {"name": name, "size": st.st_size, "kind": kind,
             "modified": time.strftime("%d/%m/%Y %H:%M", time.localtime(st.st_mtime))}
    if kind == "midi":
        try:
            d = ma.describe(path)
            entry.update(n_tracks=d["n_tracks"], n_notes=d["n_notes"],
                         duration=d["duration"], tempo_bpm=d["tempo_bpm"])
        except Exception as e:  # file rotto: lo elenco comunque
            entry["error"] = f"{type(e).__name__}: {e}"
    return entry


def resolve_input(field):
    """Percorso del file per il confronto: upload diretto o nome di un file salvato."""
    uploaded = request.files.get(field)
    if uploaded and uploaded.filename:
        name = save_upload(uploaded)
        return os.path.join(FILES_DIR, name), name
    body = request.get_json(silent=True) or {}
    name = request.form.get(f"{field}_name") or body.get(field)
    if not name:
        raise ValueError(f"manca il file '{field}' (upload oppure nome di un file salvato)")
    name = safe_name(name)
    path = os.path.join(FILES_DIR, name)
    if not os.path.exists(path):
        raise FileNotFoundError(f"File non trovato: {name}")
    return path, name


# ── pagine ────────────────────────────────────────────────────────────────────
@app.route("/")
def home():
    return send_file(os.path.join(BASE_DIR, "studio.html"))


@app.route("/extract")
def extract_page():
    """L'estrattore MIDI (FORTISSIMO PRO — Auto-Analyzer), identico all'originale."""
    return send_file(os.path.join(BASE_DIR, "extractor.html"))


@app.route("/alg")
def alg_page():
    """Banco di prova dell'algoritmo puro (alg/fortissimo_alg.js), senza interfaccia."""
    return send_file(os.path.join(BASE_DIR, "alg_test.html"))


@app.route("/alg/<path:filename>")
def alg_files(filename):
    """Serve i file dell'algoritmo (fortissimo_alg.js) usati dal banco di prova."""
    return send_from_directory(os.path.join(BASE_DIR, "alg"), filename)


@app.route("/favicon.ico")
def favicon():
    return ("", 204)


@app.route("/api/health")
def health():
    model_ok = os.path.exists(ma.MODEL_PATH)
    return jsonify({"ok": True, "app": "MIDI Studio", "port": os.environ.get("MIDI_STUDIO_PORT_BOUND", ""),
                    "model": os.path.basename(ma.MODEL_PATH), "model_found": model_ok,
                    "files_dir": FILES_DIR, "pid": os.getpid()})


# ── API file ──────────────────────────────────────────────────────────────────
@app.route("/api/files")
def api_files():
    names = [n for n in os.listdir(FILES_DIR)
             if os.path.isfile(os.path.join(FILES_DIR, n)) and not n.startswith(".")]
    names.sort(key=lambda n: os.path.getmtime(os.path.join(FILES_DIR, n)), reverse=True)
    return jsonify({"files": [file_entry(n) for n in names], "dir": FILES_DIR})


@app.route("/api/save-midi", methods=["POST"])
def api_save_midi():
    """Usato dall'estrattore: salva nel server i .mid generati nel browser."""
    up = request.files.get("file")
    if not up or not up.filename:
        return jsonify({"error": "nessun file ricevuto"}), 400
    wanted = safe_name(request.form.get("name") or up.filename, "estratto.mid")
    if not wanted.lower().endswith(MIDI_EXT):
        wanted = os.path.splitext(wanted)[0] + ".mid"
    name = unique_name(wanted)
    up.save(os.path.join(FILES_DIR, name))
    return jsonify({"ok": True, "file": file_entry(name)})


@app.route("/download/<path:name>")
def download(name):
    return send_from_directory(FILES_DIR, safe_name(name), as_attachment=True)


@app.route("/api/delete/<path:name>", methods=["DELETE", "POST"])
def api_delete(name):
    clean = safe_name(name)
    path = os.path.join(FILES_DIR, clean)
    if not os.path.exists(path):
        return jsonify({"error": "File non trovato"}), 404
    os.remove(path)
    return jsonify({"ok": True, "deleted": clean})


# ── API confronto ─────────────────────────────────────────────────────────────
@app.route("/api/compare", methods=["POST"])
def api_compare():
    """Confronta due .mid: upload diretto (a/b) oppure nomi di file salvati."""
    try:
        body = request.get_json(silent=True) or {}
        raw = body.get("weights") or {k: request.form.get(f"w_{k}")
                                      for k in ("midi", "oneshot", "presence", "volume")}
        w = dict(ma.DEFAULT_WEIGHTS)
        for k in w:
            v = raw.get(k) if isinstance(raw, dict) else None
            if v not in (None, ""):
                w[k] = float(v)
        # I pesi si controllano prima di toccare i file: errore più chiaro
        if abs(w["midi"] + w["oneshot"] + w["presence"] - 1.0) > 1e-6:
            return jsonify({"error": "I pesi MIDI + one-shot + presence devono sommare 1.0"}), 400
        path_a, name_a = resolve_input("a")
        path_b, name_b = resolve_input("b")
        out = ma.compare_midi(path_a, path_b, w)
        out.update({"ok": True, "a_file": name_a, "b_file": name_b})
        return jsonify(out)
    except FileNotFoundError as e:
        return jsonify({"error": str(e)}), 404
    except (ValueError, OSError, EOFError, TypeError) as e:
        # payload incompleto oppure file .mid non valido (mido: "MThd not found")
        return jsonify({"error": f"Input non valido: {e}"}), 400
    except AssertionError:
        return jsonify({"error": "I pesi MIDI + one-shot + presence devono sommare 1.0"}), 400
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({"error": f"{type(e).__name__}: {e}"}), 500


@app.route("/api/test-audio")
def api_test_audio():
    """WAV di prova generato al volo (serve per collaudare l'estrattore).

    Parametro opzionale `seconds` (default 6): comodo per prove rapide.
    """
    import io
    import wave

    import numpy as np
    sr = 22050
    dur = max(1.0, min(30.0, float(request.args.get("seconds", 6.0))))
    n = int(sr * dur)
    t = np.arange(n) / sr
    sig = 0.30 * np.sin(2 * np.pi * 220.0 * t) * (np.sin(2 * np.pi * 0.5 * t) > 0)
    for i, freq in enumerate((440.0, 554.37, 659.25, 880.0)):          # melodia
        start, length = int(i * 0.9 * sr), int(0.7 * sr)
        if start >= n:
            break
        length = min(length, n - start)
        seg = np.arange(length) / sr
        sig[start:start + length] += 0.40 * np.sin(2 * np.pi * freq * seg) * np.exp(-seg * 3)
    for k in range(int(dur) + 1):                                       # kick
        start, length = int(k * 1.0 * sr), int(0.12 * sr)
        if start >= n:
            break
        length = min(length, n - start)
        seg = np.arange(length) / sr
        sig[start:start + length] += 0.45 * np.sin(2 * np.pi * 60 * seg) * np.exp(-seg * 25)
    sig = np.clip(sig / max(1e-9, float(np.max(np.abs(sig)))) * 0.9, -1.0, 1.0)
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes((sig * 32767).astype("<i2").tobytes())
    buf.seek(0)
    return send_file(buf, mimetype="audio/wav", as_attachment=True,
                     download_name="test_audio.wav")


# ── avvio ─────────────────────────────────────────────────────────────────────
def port_in_use(port):
    with socket.socket() as s:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            s.bind(("127.0.0.1", port))
            return False
        except OSError:
            return True


def is_our_instance(port):
    """True se su quella porta risponde già MIDI Studio (evita doppioni)."""
    import json as _json
    import urllib.request
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/health", timeout=2) as r:
            return _json.loads(r.read().decode()).get("app") == "MIDI Studio"
    except Exception:
        return False


def pick_port():
    """Prima porta libera da DEFAULT_PORT in poi; esce se siamo già attivi."""
    for port in range(DEFAULT_PORT, DEFAULT_PORT + 6):
        if not port_in_use(port):
            return port
        if is_our_instance(port):
            print(f"* MIDI Studio è già in esecuzione su http://localhost:{port} — niente da fare.")
            raise SystemExit(0)
    raise SystemExit(f"* Nessuna porta libera tra {DEFAULT_PORT} e {DEFAULT_PORT + 5}")


if __name__ == "__main__":
    bound = pick_port()
    os.environ["MIDI_STUDIO_PORT_BOUND"] = str(bound)
    print("\n╔════════════════════════════════════════════╗")
    print(f"║  🎹 MIDI Studio → http://localhost:{bound}")
    print("╚════════════════════════════════════════════╝")
    print(f"* File generati: {FILES_DIR}")
    print(f"* Modello:       {ma.MODEL_PATH} ({'trovato' if os.path.exists(ma.MODEL_PATH) else 'NON TROVATO'})")
    try:
        from waitress import serve
        print(f"* Server WSGI (waitress) su 127.0.0.1:{bound}")
        serve(app, host="127.0.0.1", port=bound, threads=8)
    except ImportError:
        print("* waitress non installato: uso werkzeug (threaded)")
        app.run(host="127.0.0.1", port=bound, threaded=True, use_reloader=False)

