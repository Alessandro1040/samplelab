#!/usr/bin/env python3
"""
SampleLab — Backend unificato
Fonde: YT Downloader (index-5), WhoSampled Scraper (scraper_app), Mass Renamer, Database
"""

from flask import Flask, request, jsonify, send_file, Response
from flask_cors import CORS
import yt_dlp, os, sys, threading, uuid, ssl, socket, json, time, re
import urllib.parse, subprocess, hashlib, sqlite3, struct, math, select
from datetime import datetime, timezone
from contextlib import contextmanager

ssl._create_default_https_context = ssl._create_unverified_context
app = Flask(__name__)
CORS(app)

@app.after_request
def _no_cache_html(resp):
    # Sviluppo locale: le pagine HTML non devono restare in cache, altrimenti
    # il browser continua a usare le versioni vecchie (es. player senza i fix).
    if resp.mimetype == "text/html":
        resp.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
        resp.headers["Pragma"] = "no-cache"
        resp.headers["Expires"] = "0"
    return resp

BASE_DIR   = os.path.dirname(os.path.abspath(__file__))
DL_DIR     = os.path.join(BASE_DIR, "downloads");  os.makedirs(DL_DIR, exist_ok=True)
STEMS_DIR  = os.path.join(BASE_DIR, "stems");      os.makedirs(STEMS_DIR, exist_ok=True)
# Copertine delle canzoni (una per brano, servita da /cover/<file>): le immagini
# non vanno in repo, come downloads/ e stems/ (vedi .gitignore).
COVERS_DIR = os.path.join(BASE_DIR, "covers");     os.makedirs(COVERS_DIR, exist_ok=True)
# Video delle canzoni (MP4 da YouTube o caricati dal computer): serviti da
# /video/<file>, cartella non versionata come downloads/ (vedi .gitignore).
VID_DIR    = os.path.join(BASE_DIR, "videos");     os.makedirs(VID_DIR, exist_ok=True)
DB_PATH    = os.path.join(BASE_DIR, "samplelab (2).db")
# Legacy dataset.json kept for compatibility
DATASET_PATH = os.path.join(BASE_DIR, "dataset.json")

jobs = {}
DB_LOCK = threading.Lock()
DATASET_LOCK = threading.Lock()

MIME_MAP = {"mp3":"audio/mpeg","wav":"audio/wav","webm":"audio/webm",
            "m4a":"audio/mp4","mp4":"audio/mp4","ogg":"audio/ogg",
            "opus":"audio/opus","flac":"audio/flac"}

# ── VIDEO DELLE CANZONI (18/09/2026) ─────────────────────────────────────────
# I video (il file MP4 scaricato da YouTube o quello caricato dal computer) NON
# stanno in `downloads/` con gli audio: hanno la loro cartella `videos/` (non
# versionata, come `covers/`), il loro streaming `/video/<file>` e il nome del
# file nella colonna `songs.video_file`. Così la cartella degli audio resta
# leggibile (il selettore «📁 File locale» non si riempie di video) e si vede
# subito quali canzoni hanno un video.
VIDEO_EXTS = (".mp4", ".mkv", ".webm", ".mov", ".m4v", ".avi")
MIME_VIDEO = {"mp4":"video/mp4","webm":"video/webm","mkv":"video/x-matroska",
              "mov":"video/quicktime","m4v":"video/x-m4v","avi":"video/x-msvideo"}

def mime_video(nome):
    """Il MIME del file video dal nome (funzione PURA). Default: video/mp4."""
    ext = str(nome or "").rsplit(".", 1)[-1].lower()
    return MIME_VIDEO.get(ext, "video/mp4")

def _clean_tag(v):
    if v is None:
        return ""
    if isinstance(v, bool):
        return ""
    if isinstance(v, (int, float)):
        try:
            return "" if not v else (str(int(v)) if float(v).is_integer() else str(v))
        except Exception:
            return str(v)
    return str(v).strip()

def apply_audio_tags(src_path, out_path, song):
    """Copia src_path in out_path e scrive nei tag del file i metadati del DB.

    Supporta MP3 (ID3), M4A/MP4 (tag MP4) e FLAC/OGG/OPUS (Vorbis).
    Ritorna True se i tag sono stati scritti, False altrimenti.
    """
    if not HAS_MUTAGEN:
        return False
    import shutil
    shutil.copyfile(src_path, out_path)
    ext = src_path.rsplit(".", 1)[-1].lower() if "." in src_path else ""
    title       = _clean_tag(song.get("title"))
    artist      = _clean_tag(song.get("artist"))
    album       = _clean_tag(song.get("album"))
    albumartist = _clean_tag(song.get("album_artist"))
    composer    = _clean_tag(song.get("composer"))
    genre       = _clean_tag(song.get("genre"))
    year        = _clean_tag(song.get("year"))
    track       = _clean_tag(song.get("track_number"))
    comment     = _clean_tag(song.get("comment"))
    lyrics      = _clean_tag(song.get("lyrics"))
    bpm         = _clean_tag(song.get("bpm"))
    key         = _clean_tag(song.get("musical_key"))
    try:
        if ext == "mp3":
            try:
                audio = ID3(out_path)
            except Exception:
                audio = ID3()
            frames = {
                "TIT2": (TIT2, title), "TPE1": (TPE1, artist), "TALB": (TALB, album),
                "TPE2": (TPE2, albumartist), "TCOM": (TCOM, composer),
                "TCON": (TCON, genre), "TDRC": (TDRC, year), "TRCK": (TRCK, track),
                "TBPM": (TBPM, bpm), "TKEY": (TKEY, key),
            }
            for fid, (cls, val) in frames.items():
                audio.delall(fid)
                if val:
                    try: audio.add(cls(encoding=3, text=val))
                    except Exception: pass
            audio.delall("COMM")
            if comment:
                try: audio.add(COMM(encoding=3, lang="eng", desc="", text=comment))
                except Exception: pass
            audio.delall("USLT")
            if lyrics:
                try: audio.add(USLT(encoding=3, lang="eng", desc="", text=lyrics))
                except Exception: pass
            audio.save(out_path)
            return True
        if ext in ("m4a", "mp4"):
            from mutagen.mp4 import MP4
            audio = MP4(out_path)
            if title: audio["\xa9nam"] = [title]
            if artist: audio["\xa9ART"] = [artist]
            if album: audio["\xa9alb"] = [album]
            if albumartist: audio["aART"] = [albumartist]
            if composer: audio["\xa9wrt"] = [composer]
            if genre: audio["\xa9gen"] = [genre]
            if year: audio["\xa9day"] = [year]
            if track:
                try: audio["trkn"] = [(int(float(track)), 0)]
                except Exception: pass
            if comment: audio["\xa9cmt"] = [comment]
            if bpm:
                try: audio["tmpo"] = [int(float(bpm))]
                except Exception: pass
            if key:
                try: audio["----:com.apple.iTunes:initialkey"] = [key]
                except Exception: pass
            audio.save()
            return True
        if ext in ("flac", "ogg", "opus"):
            audio = mutagen.File(out_path, easy=True)
            if audio is None:
                return False
            keys = {}
            if title: keys["title"] = title
            if artist: keys["artist"] = artist
            if album: keys["album"] = album
            if albumartist: keys["albumartist"] = albumartist
            if composer: keys["composer"] = composer
            if genre: keys["genre"] = genre
            if year: keys["date"] = year
            if track: keys["tracknumber"] = track
            if comment: keys["comment"] = comment
            if bpm: keys["bpm"] = bpm
            if key: keys["key"] = key
            if lyrics: keys["lyrics"] = lyrics
            for k, v in keys.items():
                try: audio[k] = [v]
                except Exception: pass
            audio.save()
            return True
    except Exception as e:
        print(f"[tags] errore scrittura tag: {e}")
    return False

# ── FFMPEG ────────────────────────────────────────────────────────────────────
def find_ffmpeg():
    for cmd in ["ffmpeg","/opt/homebrew/bin/ffmpeg","/usr/local/bin/ffmpeg","/usr/bin/ffmpeg"]:
        try:
            if subprocess.run([cmd,"-version"],capture_output=True,timeout=5).returncode==0:
                return cmd
        except: pass
    return None
FFMPEG = find_ffmpeg()
print(f"[init] ffmpeg: {FFMPEG or 'NON TROVATO'}")

try:
    import librosa, numpy as np
    HAS_LIBROSA = True
except ImportError:
    HAS_LIBROSA = False; np = None

# ── TRASCRIZIONE (Whisper) per la conferma dal PARLATO ───────────────────────
# Opzionale e pesante (~1,5 GB fra dipendenze e modello): l'app funziona lo stesso
# senza. Misure del 18/09/2026 (modello `small`, CPU): 20-70 s per brano e, sul
# brano giusto, il 68-78% delle parole ascoltate si ritrova nel testo (contro ≤16%
# di un brano sbagliato) — numeri completi nel README.
try:
    from faster_whisper import WhisperModel as _WhisperModel
    HAS_WHISPER = True
except Exception:
    _WhisperModel = None
    HAS_WHISPER = False

# ── MUTAGEN (scrittura tag audio nei file scaricati) ─────────────────────────
try:
    import mutagen
    from mutagen.id3 import ID3, TIT2, TPE1, TALB, TCOM, TCON, TRCK, TDRC, TPE2, COMM, TBPM, TKEY, USLT
    HAS_MUTAGEN = True
except Exception:
    HAS_MUTAGEN = False

# ── NORMALIZE (definita subito per essere disponibile ovunque) ─────────────
def normalize(s):
    return re.sub(r"[^a-z0-9]", "", s.lower())

# ── TIMEOUT EXCEPTION ──────────────────────────────────────────────────────
class TimeoutException(Exception):
    pass

# ── SQLITE ────────────────────────────────────────────────────────────────────
def init_db():
    with sqlite3.connect(DB_PATH) as c:
        c.executescript("""
PRAGMA journal_mode=WAL;
PRAGMA foreign_keys=ON;

CREATE TABLE IF NOT EXISTS songs (
    id              TEXT PRIMARY KEY,
    title           TEXT,
    artist          TEXT,
    album           TEXT,
    album_artist    TEXT,
    composer        TEXT,
    producers       TEXT,
    genre           TEXT,
    year            INTEGER,
    release_date    TEXT,
    track_number    TEXT,
    disc_number     TEXT,
    compilation     INTEGER DEFAULT 0,
    rating          REAL,
    bpm             REAL,
    musical_key     TEXT,
    play_count      INTEGER,
    comment         TEXT,
    lyrics          TEXT,
    duration        REAL,
    analyzed_status TEXT DEFAULT 'none',
    genius_url      TEXT,
    whosampled_url  TEXT,
    youtube_url     TEXT,
    tunebat_url     TEXT,
    cover_art_path  TEXT,
    local_file      TEXT,
    -- verification flags: 0=unverified(red), 1=verified(green)
    title_verified      INTEGER DEFAULT 0,
    artist_verified     INTEGER DEFAULT 0,
    bpm_verified        INTEGER DEFAULT 0,
    key_verified        INTEGER DEFAULT 0,
    lyrics_verified     INTEGER DEFAULT 0,
    genius_match_score  REAL,
    created_at      TEXT DEFAULT (datetime('now')),
    updated_at      TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS sample_relations (
    id                          TEXT PRIMARY KEY,
    derivative_song_id          TEXT REFERENCES songs(id) ON DELETE CASCADE,
    source_song_id              TEXT REFERENCES songs(id) ON DELETE CASCADE,
    relation_source             TEXT DEFAULT 'whosampled',
    relation_type               TEXT DEFAULT 'samples',
    category                    TEXT DEFAULT 'SAMPLE',
    transformation              TEXT,
    ws_url                      TEXT,
    yt_url_derivative           TEXT,
    yt_url_source               TEXT,
    timestamp_derivative_start  REAL,
    timestamp_derivative_end    REAL,
    timestamp_source_start      REAL,
    timestamp_source_end        REAL,
    notes                       TEXT,
    verified_by_user            INTEGER DEFAULT 0,
    created_at                  TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS stem_sessions (
    id                   TEXT PRIMARY KEY,
    song_id              TEXT REFERENCES songs(id) ON DELETE CASCADE,
    job_id               TEXT,
    model_name           TEXT DEFAULT 'htdemucs',
    output_folder        TEXT,
    status               TEXT DEFAULT 'pending',
    progress_percent     INTEGER DEFAULT 0,
    error_message        TEXT,
    created_at           TEXT DEFAULT (datetime('now')),
    completed_at         TEXT
);

CREATE TABLE IF NOT EXISTS stem_tracks (
    id              TEXT PRIMARY KEY,
    session_id      TEXT REFERENCES stem_sessions(id) ON DELETE CASCADE,
    stem_type       TEXT,
    file_path       TEXT NOT NULL,
    file_size_bytes INTEGER,
    created_at      TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS audio_analyses (
    id           TEXT PRIMARY KEY,
    song_id      TEXT REFERENCES songs(id) ON DELETE CASCADE,
    source       TEXT,
    bpm          REAL,
    musical_key  TEXT,
    confidence   REAL,
    analyzed_at  TEXT DEFAULT (datetime('now'))
);

-- Stato di riproduzione globale (unica riga, id=1): persiste play/pausa,
-- posizione e brano corrente così il player resta sincronizzato tra le pagine.
CREATE TABLE IF NOT EXISTS playback_state (
    id          INTEGER PRIMARY KEY CHECK (id = 1),
    title       TEXT,
    artist      TEXT,
    local_file  TEXT,
    song_id     TEXT,
    is_playing  INTEGER DEFAULT 0,
    position    REAL DEFAULT 0,
    duration    REAL DEFAULT 0,
    volume      REAL DEFAULT 0.7,
    updated_at  TEXT DEFAULT (datetime('now'))
);
INSERT OR IGNORE INTO playback_state (id) VALUES (1);

CREATE INDEX IF NOT EXISTS idx_songs_artist ON songs(artist);
CREATE INDEX IF NOT EXISTS idx_songs_title  ON songs(title);
CREATE INDEX IF NOT EXISTS idx_sr_deriv     ON sample_relations(derivative_song_id);
CREATE INDEX IF NOT EXISTS idx_sr_source    ON sample_relations(source_song_id);
        """)
        # Migrazione: aggiunge tunebat_url / genius_match_score ai database creati
        # prima di queste versioni
        cols = [r[1] for r in c.execute("PRAGMA table_info(songs)").fetchall()]
        if "tunebat_url" not in cols:
            c.execute("ALTER TABLE songs ADD COLUMN tunebat_url TEXT")
        if "genius_match_score" not in cols:
            c.execute("ALTER TABLE songs ADD COLUMN genius_match_score REAL")
        # Conferma AUDIO della Verifica (18/09/2026). Il match di Genius è solo
        # TESTUALE, quindi può essere un falso positivo (misurato sui dati veri:
        # `song_b6e7cc46b04c` "Fast Lane(Eminem & Royce Da 5'9 Remix)" è finita
        # abbinata a due artisti sconosciuti con score 0,589). Qui si registra
        # l'esito del confronto fra il file locale e l'ANTEPRIMA UFFICIALE di
        # iTunes: `audio_match_esito` è 'confermato' | 'non confermato' |
        # 'ambiguo' | 'non verificabile', `audio_match_voti` sono gli hash
        # acustici allineati allo stesso offset (più alto = più sicuro).
        for colonna, tipo in (("audio_match_esito", "TEXT"),
                              ("audio_match_voti", "INTEGER"),
                              ("audio_match_offset", "REAL"),
                              ("audio_match_comuni", "INTEGER"),
                              ("audio_match_fonte", "TEXT"),
                              ("audio_match_motivo", "TEXT"),
                              ("audio_match_at", "TEXT"),
                              # stesso controllo, ma sul candidato WhoSampled (18/09/2026):
                              # il link si salvava col solo confronto testuale e con
                              # l'artista vuoto finiva su un altro brano (caso vero:
                              # *End of the World* → pagina di Skeeter Davis)
                              ("ws_match_score", "REAL"),
                              ("ws_audio_esito", "TEXT"),
                              ("ws_audio_voti", "INTEGER"),
                              ("ws_audio_offset", "REAL"),
                              ("ws_audio_comuni", "INTEGER"),
                              ("ws_audio_fonte", "TEXT"),
                              ("ws_audio_motivo", "TEXT"),
                              ("ws_query", "TEXT"),
                              ("ws_audio_at", "TEXT"),
                              # ── Verifica guidata dalla pagina /verifica (18/09/2026) ──
                              # `genius_escluso`: l'utente dichiara che la canzone NON è su
                              # Genius (freestyle, mixtape): la ricerca si salta e la riga
                              # resta etichettata come tale.
                              ("genius_escluso", "INTEGER DEFAULT 0"),
                              # conferma dal PARLATO (Whisper): percentuale di parole
                              # ascoltate che compaiono nel testo, e verdetto
                              ("testo_esito", "TEXT"),
                              ("testo_voti", "REAL"),
                              ("testo_parole", "INTEGER"),
                              ("testo_fonte", "TEXT"),
                              ("testo_motivo", "TEXT"),
                              ("testo_at", "TEXT"),
                              # ── Confronto voce: i TESTI e i DUE AUDIO (18/09/2026) ──
                              # La pagina /verifica fa VEDERE il confronto (due colonne:
                              # «quello che si sente» / «il testo vero») e SENTIRE i due
                              # audio. Prima si salvavano solo i numeri: il testo
                              # trascritto andava perso e non c'era niente da mostrare.
                              # `testo_parole_uniche` è il denominatore VERO della
                              # percentuale (`testo_parole` conta la lista, che con i
                              # ritornelli ripetuti è più lunga): senza, il 77,2% non si
                              # ricontava a mano.
                              ("testo_trascrizione", "TEXT"),
                              ("testo_riferimento", "TEXT"),
                              ("testo_parole_uniche", "INTEGER"),
                              # i DUE file confrontati, relativi alla cartella dell'app
                              # ('downloads/…' oppure 'anteprime/acapella_…/vocals.mp3')
                              ("testo_audio_nostro", "TEXT"),
                              ("testo_audio_riferimento", "TEXT"),
                              # l'anteprima ufficiale usata dal controllo audio: senza
                              # questa non si sa QUALE file è stato confrontato (la
                              # cartella `anteprime/` non è versionata e il nome del file
                              # cambia con l'id iTunes)
                              ("anteprima_file", "TEXT")
                              # ── Metadati del video YouTube (18/09/2026) ──
                              # La lista sta in `CAMPI_YOUTUBE` per non averla in due
                              # posti: le stesse colonne le usa `resolve_or_create_song`
                              # per filtrare quello che arriva da yt-dlp.
                              ) + CAMPI_YOUTUBE + (
                              # ── VIDEO della canzone (18/09/2026) ──
                              # Il nome del file in `videos/` (MP4 scaricato da YouTube
                              # o caricato dal computer): non è un metadata del video,
                              # è il file che la riga ha, come `local_file` per l'audio.
                              ("video_file", "TEXT"),
                              # ── PLAYLIST DI PROVENIENZA (18/09/2026) ──
                              # Il titolo della playlist da cui è arrivata la riga
                              # («Remixes Collection Vol. 2»): serve a RITROVARLE
                              # (la ricerca del tab Database cerca anche questo).
                              ("yt_playlist", "TEXT"),
                              ):
            if colonna not in cols:
                c.execute(f"ALTER TABLE songs ADD COLUMN {colonna} {tipo}")

@contextmanager
def get_db():
    with DB_LOCK:
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys=ON")
        try:
            yield conn; conn.commit()
        except:
            conn.rollback(); raise
        finally:
            conn.close()

def row2dict(r): return dict(r) if r else None
def rows2list(rs): return [dict(r) for r in rs]

# ── DATASET JSON (compatibilità scraper_app) ──────────────────────────────────
def load_dataset():
    if not os.path.exists(DATASET_PATH):
        return {"songs":{},"pairs":[],"meta":{"version":"1.0","count":0,"last_updated":None}}
    with open(DATASET_PATH,"r",encoding="utf-8") as f:
        return json.load(f)

def save_dataset(data):
    data["meta"]["last_updated"] = datetime.utcnow().isoformat()+"Z"
    data["meta"]["count"] = len(data["pairs"])
    tmp = DATASET_PATH+".tmp"
    with DATASET_LOCK:
        with open(tmp,"w",encoding="utf-8") as f:
            json.dump(data,f,indent=2,ensure_ascii=False)
        os.replace(tmp,DATASET_PATH)

def normalize_key(s):
    # 19/09/2026: NULL-safe (`str(s or "")`). In libreria ci sono righe con
    # `title` a NULL (brani importati dal player Onyx, rinominati male) e
    # `None.lower()` faceva fallire con 500 tutto ciò che confronta le canzoni:
    # /db/songs, /db/from_onyx, /metadata, register_local_file e il dataset JSON.
    # La guardia locale che c'era dentro get_or_create_song_db ora vale per tutti.
    return re.sub(r"[^a-z0-9]", "", str(s or "").lower())

# ── MUSICAL KEY UTILITIES ─────────────────────────────────────────────────────
_NOTE_SEMIS = {
    "C":0, "B#":0,
    "C#":1, "DB":1,
    "D":2,
    "D#":3, "EB":3,
    "E":4, "FB":4,
    "F":5, "E#":5,
    "F#":6, "GB":6,
    "G":7,
    "G#":8, "AB":8,
    "A":9,
    "A#":10, "BB":10,
    "B":11, "CB":11,
}

def parse_key_str(key):
    """Ritorna (semitone_root, mode) o None. Gestisce diesis/bemolle e maj/min."""
    if not key:
        return None
    m = re.match(r"^\s*([A-Ga-g])([#b]?)\s*(major|minor|maj|min|m)?", key.strip(), re.IGNORECASE)
    if not m:
        return None
    root = m.group(1).upper() + (m.group(2) or "").replace("b", "B")
    # normalizza b → B (es. 'Db' → 'DB')
    if len(root) == 2 and root[1] == "b":
        root = root[0] + "B"
    mode = (m.group(3) or "major").lower()
    if mode in ("m", "min", "minor", "minore"):
        mode = "minor"
    else:
        mode = "major"
    semis = _NOTE_SEMIS.get(root)
    if semis is None:
        return None
    return semis, mode

def keys_equivalent(k1, k2):
    """Due chiavi sono equivalenti se hanno la stessa nota fondamentale con lo stesso
    modo, oppure sono relative (es. C Major ≡ A Minor)."""
    p1, p2 = parse_key_str(k1), parse_key_str(k2)
    if not p1 or not p2:
        return False
    s1, m1 = p1
    s2, m2 = p2
    if m1 == m2:
        return s1 == s2
    # relativa: fondamentale maggiore = fondamentale minore + 3 semitoni
    if m1 == "major" and m2 == "minor":
        return (s1 - s2) % 12 == 3
    return (s2 - s1) % 12 == 3

# ── IDENTITÀ DI UNA CANZONE (serve a NON creare doppioni) ────────────────────
# Caso vero (18/09/2026): «Till I Collapse» di Eminem è finita in libreria DUE
# volte — la riga del 13/08 (con il file locale e l'artista «Eminem / Nate Dogg»)
# e quella del 18/09, creata salvando un campione con l'artista «Eminem» e poi
# COMPLETATA dalla Verifica (che riscrive i crediti nel formato «A / B»).
# Il confronto di prima (`normalize_key(title)` e `normalize_key(artist)`
# identici) non poteva riconoscerle, perché l'artista era scritto in due modi.
# Qui il confronto si allarga a quello che NON cambia la canzone: apostrofi,
# punteggiatura, crediti feat./ft./with e i marcatori di servizio
# ([Explicit], (Official Video)…). NON si toccano invece «Remix», «Live»,
# «Cover», «Instrumental»: quelli sono brani diversi, e in `sample_relations`
# hanno una categoria propria.
_MARCA_SERVIZIO = re.compile(
    r"\s*[\(\[]\s*(?:feat(?:uring)?\.?|ft\.?|with|con|official|explicit|video|audio|lyric"
    r"|hd|hq|prod\.?(?:\s+by)?|visualizer|clip)\b[^\)\]]*[\)\]]", re.I)
# Crediti scritti SENZA parentesi («Baby by Me feat. Ne-Yo», «… ft Ne-Yo», «…
# featuring Ne-Yo»): è la stessa canzone, quindi nel confronto si tolgono. La riga
# del 13/08 di «Baby By Me (Featuring Ne-Yo)» è il caso vero (18/09/2026): con
# solo `feat\.?` il confronto non riconosceva «Featuring» e salvando il campione
# di «Baby by Me» nasceva un doppione.
# NON si tolgono «with»/«con» FUORI parentesi: farebbero sparire mezzo titolo
# («Dance with the Devil» → «dance»). E si taglia SOLO la frase del credito,
# fermandosi a un « - » o a una parentesi: in
# «Kim ft. 2Pac, Miley Cyrus - 2021 - Mashup» il marcatore «Mashup» (cioè che il
# brano è un altro lavoro) deve restare.
_MARCA_CREDITI_LIBERA = re.compile(
    r"\s+(?:feat(?:uring)?|ft)\b\.?\s+[^\n]*?(?=\s[-–—]\s|[\(\[]|$)", re.I)
_SEPARA_ARTISTI = re.compile(
    r"\s*(?:/|,|;|\||\+|&|\bfeat\.?\b|\bft\.?\b|\bwith\b|\bcon\b|\bx\b)\s*", re.I)


def titolo_confronto(s):
    """Titolo per il CONFRONTO fra canzoni (dedup): toglie punteggiatura e i
    marcatori di servizio («Samuel's Song [Official Video] (feat. X)» →
    «samuelssong»), ma **NON** tocca «Remix», «Live», «Cover», «Instrumental»:
    quelli sono brani diversi. (La `titolo_base()` più sotto, riga ~3657, fa il
    contrario di proposito: serve a TROVARE le varianti nella scheda, non a
    decidere se due righe sono la stessa canzone.)

    I crediti si tolgono in tutte le forme scritte in libreria: fra parentesi
    («(feat. X)», «(Featuring X)», «[ft. X]») e **senza** parentesi
    («Baby by Me feat. Ne-Yo»), perché la canzone è la stessa. È il caso vero
    del 18/09/2026: «Baby by Me» (salvato da Trova Campioni) e
    «Baby By Me (Featuring Ne-Yo)» (riga del 13/08) erano la stessa canzone.
    """
    testo = _MARCA_SERVIZIO.sub(" ", str(s or ""))
    testo = _MARCA_CREDITI_LIBERA.sub("", testo)
    return normalize_key(testo)


def artista_principale(s):
    """Il PRIMO artista di un elenco («A / B feat. C» → «a»), normalizzato."""
    parti = [p for p in _SEPARA_ARTISTI.split(str(s or "").lower()) if p.strip()]
    return normalize_key(parti[0]) if parti else ""


def artisti_compatibili(a, b):
    """Vero se i due campi artista indicano lo stesso artista: testo identico,
    uno contenuto nell'altro, o stesso artista PRINCIPALE
    («Eminem» vs «Eminem / Nate Dogg», «Eminem feat. Nate Dogg» vs «Eminem»)."""
    na, nb = normalize_key(a), normalize_key(b)
    if not na or not nb:
        return False
    if na == nb or na in nb or nb in na:
        return True
    pa, pb = artista_principale(a), artista_principale(b)
    return bool(pa) and pa == pb and len(pa) >= 3


def canzoni_equivalenti(t1, a1, t2, a2):
    """Stessa canzone? Stesso titolo (anche scritto in modo diverso) e artista
    compatibile: è il confronto che riconosce un doppione."""
    if not normalize_key(t1) or not normalize_key(t2):
        return False
    if normalize_key(t1) != normalize_key(t2) and titolo_confronto(t1) != titolo_confronto(t2):
        return False
    return artisti_compatibili(a1, a2)


def find_existing_song(conn, title, artist, youtube_url="", exclude_id=""):
    """La riga di QUESTA canzone già in libreria, o `(None, "")`.

    Prove, dalla più forte alla più debole:
    1. stesso link YouTube;
    2. titolo e artista identici (il confronto di sempre);
    3. stesso titolo + artista compatibile (il caso «Till I Collapse»);
    4. stesso titolo, artista mancante da una parte, e quel titolo è **unico** in
       libreria (i file di yt-dlp non sempre hanno l'artista nel nome).
    `come` dice quale prova ha riconosciuto la riga: finisce nella risposta di
    /save_pair, così si vede che NON è stato creato un doppione.
    """
    yt = (youtube_url or "").strip()
    if yt:
        r = conn.execute("SELECT id FROM songs WHERE youtube_url=?", (yt,)).fetchone()
        if r and r["id"] != exclude_id:
            return r["id"], "stesso link YouTube"
    nt, na = normalize_key(title), normalize_key(artist)
    rows = conn.execute("SELECT id,title,artist FROM songs").fetchall()
    # 2) titolo e artista identici (il confronto di sempre). Con `nt` vuoto non si
    #    confronta niente: senza titolo non si può dire che sia la stessa canzone.
    if nt:
        for row in rows:
            if row["id"] == exclude_id:
                continue
            if normalize_key(row["title"]) == nt and normalize_key(row["artist"]) == na:
                return row["id"], "titolo e artista identici"
    tb = titolo_confronto(title)
    if not tb:
        return None, ""
    candidate = [row for row in rows
                 if row["id"] != exclude_id and titolo_confronto(row["title"]) == tb]
    for row in candidate:
        if artisti_compatibili(artist, row["artist"]):
            return row["id"], "stesso titolo, artista compatibile"
    if len(candidate) == 1 and (not na or not normalize_key(candidate[0]["artist"])):
        return candidate[0]["id"], "stesso titolo (unico in libreria), artista mancante"
    return None, ""


def resolve_or_create_song(conn, title, artist, youtube_url="", local_file="", duration=None,
                           extra=None, video_file=None, playlist=None):
    """La riga di questa canzone, creandola solo se non c'è davvero. Ritorna
    `(song_id, creata, come)`: `come` è la prova del riconoscimento.

    `extra` sono i campi `yt_*` del video YouTube (vedi `campi_youtube`) e, se
    c'è, l'anno che ne deriva: si scrivono SOLO le colonne di `CAMPI_YOUTUBE`
    (un nome fuori lista si ignora, così dall'esterno non si può scegliere una
    colonna qualsiasi) e `year` si riempie **solo se è vuoto**, perché l'anno è
    un campo curato (Genius, o corretto a mano).

    `video_file` è il nome del file video in `videos/` (18/09/2026): come
    `local_file` si aggancia a QUESTA riga e **solo se è vuoto** — un video
    scelto a mano non viene sostituito da un download della playlist.

    `playlist` è il titolo della playlist da cui è arrivato il file: si scrive in
    `yt_playlist` **solo se è vuoto** (la prima playlist da cui viene la canzone),
    così le righe di una playlist si ritrovano cercandone il nome.
    """
    extra = dict(extra or {})
    anno_yt = extra.pop("year", None) or None
    extra = {k: v for k, v in extra.items()
             if k in CAMPI_YOUTUBE_NOMI and v is not None and str(v).strip() != ""}
    sid, come = find_existing_song(conn, title, artist, youtube_url)
    if sid:
        # Nella riga che c'è già si COMPLETANO solo i campi vuoti: quello che è
        # stato curato a mano (artista, titolo, BPM…) non viene mai sovrascritto.
        if youtube_url:
            conn.execute("UPDATE songs SET youtube_url=?, updated_at=datetime('now') "
                         "WHERE id=? AND (youtube_url IS NULL OR youtube_url='')",
                         (youtube_url, sid))
        if local_file:
            conn.execute("UPDATE songs SET local_file=?, updated_at=datetime('now') "
                         "WHERE id=? AND (local_file IS NULL OR local_file='')",
                         (local_file, sid))
        if duration is not None:
            conn.execute("UPDATE songs SET duration=COALESCE(duration,?), "
                         "updated_at=datetime('now') WHERE id=?", (duration, sid))
        if video_file:
            conn.execute("UPDATE songs SET video_file=?, updated_at=datetime('now') "
                         "WHERE id=? AND (video_file IS NULL OR video_file='')",
                         (video_file, sid))
        if playlist:
            conn.execute("UPDATE songs SET yt_playlist=?, updated_at=datetime('now') "
                         "WHERE id=? AND (yt_playlist IS NULL OR yt_playlist='')",
                         (playlist, sid))
        if extra:
            # I dati del video si riscrivono a ogni download riuscito: sono fatti
            # letti da YouTube, non scelte fatte a mano.
            conn.execute("UPDATE songs SET " + ", ".join(f"{k}=?" for k in extra) +
                         ", updated_at=datetime('now') WHERE id=?",
                         (*extra.values(), sid))
        if anno_yt:
            conn.execute("UPDATE songs SET year=?, updated_at=datetime('now') "
                         "WHERE id=? AND (year IS NULL OR year='')", (anno_yt, sid))
        return sid, False, come
    sid = "song_" + hashlib.sha256(f"{title}|{artist}|{time.time()}".encode()).hexdigest()[:12]
    colonne = ["id", "title", "artist", "youtube_url", "local_file", "duration"]
    valori = [sid, title, artist, youtube_url, local_file, duration]
    if extra:
        colonne += list(extra)
        valori += list(extra.values())
    if anno_yt:
        colonne.append("year")
        valori.append(anno_yt)
    if video_file:
        colonne.append("video_file")
        valori.append(video_file)
    if playlist:
        colonne.append("yt_playlist")
        valori.append(playlist)
    conn.execute("INSERT INTO songs(" + ", ".join(colonne) + ") VALUES(" +
                 ", ".join(["?"] * len(colonne)) + ")", valori)
    return sid, True, "nuova riga"


def song_match(s1,s2):
    return (normalize_key(s1.get("title",""))==normalize_key(s2.get("title","")) and
            normalize_key(s1.get("artist",""))==normalize_key(s2.get("artist","")))

def get_or_create_song_dataset(data,title,artist,youtube_url="",local_file="",duration=None):
    if youtube_url:
        for sid,s in data["songs"].items():
            if s.get("youtube_url")==youtube_url: return sid
    for sid,s in data["songs"].items():
        if song_match(s,{"title":title,"artist":artist}):
            if youtube_url and not s.get("youtube_url"): s["youtube_url"]=youtube_url
            return sid
    sid="song_"+hashlib.sha256(f"{title}|{artist}|{time.time()}".encode()).hexdigest()[:12]
    data["songs"][sid]={"title":title,"artist":artist,"youtube_url":youtube_url,
                        "local_file":local_file,"duration":duration}
    return sid

def is_duplicate(data,new_pair,tol=2.0):
    for p in data["pairs"]:
        if p["song_x"]!=new_pair["song_x"] or p["song_yi"]!=new_pair["song_yi"]: continue
        if p["category"]!=new_pair["category"]: continue
        if abs(p["trim_x"]["start"]-new_pair["trim_x"]["start"])<=tol and \
           abs(p["trim_x"]["end"]-new_pair["trim_x"]["end"])<=tol and \
           abs(p["trim_yi"]["start"]-new_pair["trim_yi"]["start"])<=tol and \
           abs(p["trim_yi"]["end"]-new_pair["trim_yi"]["end"])<=tol:
            return True
    return False

def check_pair_exists_loose(data,song_x_meta,song_yi_meta,category):
    sid_x=sid_y=None
    for sid,s in data["songs"].items():
        if song_match(s,song_x_meta): sid_x=sid
        if song_match(s,song_yi_meta): sid_y=sid
    if not sid_x or not sid_y: return False
    for p in data["pairs"]:
        if p["song_x"]==sid_x and p["song_yi"]==sid_y and p["category"]==category: return True
    return False

# ── SONG HELPERS (SQLite) ────────────────────────────────────────────────────
def get_or_create_song_db(conn, title, artist, youtube_url="", local_file="", duration=None,
                          extra=None, video_file=None, playlist=None):
    """La riga di questa canzone (id), creandola **solo se manca davvero**.

    Dal 19/09/2026 passa da `resolve_or_create_song`, cioè dal confronto
    tollerante di `find_existing_song`: prima bastava un artista scritto in modo
    diverso («Eminem» vs «Eminem / Nate Dogg») per creare una riga in più, ed è
    così che «Till I Collapse» è finita due volte in libreria.
    Il nome della funzione resta perché la usano /metadata, /db/from_onyx,
    /db/add_local, /save_pair e register_local_file.
    Nota storica: deve reggere anche i NULL — in libreria ci sono righe con
    `title` a NULL e `None.lower()` faceva fallire ogni chiamata con 500.
    """
    sid, _, _ = resolve_or_create_song(conn, title, artist, youtube_url, local_file, duration,
                                       extra, video_file, playlist)
    return sid

# ── AUDIO ANALYSIS ────────────────────────────────────────────────────────────
def analyze_audio_librosa(filepath):
    if not HAS_LIBROSA: return None
    # librosa può essere lentissimo su alcuni file: la eseguiamo in un thread
    # con timeout (40s) così la verifica non resta mai bloccata su questo passo.
    result = [None]
    def _run():
        try:
            y,sr=librosa.load(filepath,sr=None,duration=90)
            tempo,_=librosa.beat.beat_track(y=y,sr=sr)
            bpm=float(tempo)
            chroma=librosa.feature.chroma_cqt(y=y,sr=sr)
            ca=chroma.mean(axis=1)
            mp=np.array([6.35,2.23,3.48,2.33,4.38,4.09,2.52,5.19,2.39,3.66,2.29,2.88])
            mip=np.array([6.33,2.68,3.52,5.38,2.60,3.53,2.54,4.75,3.98,2.69,3.34,3.17])
            mp/=np.linalg.norm(mp); mip/=np.linalg.norm(mip)
            n=np.linalg.norm(ca)
            if n>0: ca/=n
            keys=['C','C#','D','D#','E','F','F#','G','G#','A','A#','B']
            bc=-1; bk=None; bm=None
            for i in range(12):
                cm=float(np.corrcoef(ca,np.roll(mp,i))[0,1])
                cmi=float(np.corrcoef(ca,np.roll(mip,i))[0,1])
                if cm>bc: bc=cm; bk=keys[i]; bm='Major'
                if cmi>bc: bc=cmi; bk=keys[i]; bm='Minor'
            result[0] = {"bpm":round(bpm,1),"key":f"{bk} {bm}","confidence":round(bc,3),"source":"librosa"}
        except Exception as e:
            print(f"[librosa] {e}")
    t = threading.Thread(target=_run, daemon=True)
    t.start()
    t.join(40)
    if t.is_alive():
        print("[librosa] TIMEOUT dopo 40s")
        return None
    return result[0]

def analyze_audio_ffmpeg(filepath):
    if not FFMPEG: return None
    import tempfile
    import signal
    tmp_path = None
    try:
        # ffmpeg scrive su FILE temporaneo. Per lanciarlo si usa os.posix_spawnp
        # e NON subprocess/multiprocessing: in un server multithread, fork+exec
        # può bloccarsi (il figlio eredita lock di altri thread e il genitore
        # resta appeso tenendo il GIL, congelando TUTTO il server). posix_spawn
        # NON fa fork → nessun deadlock possibile.
        tmp_fd, tmp_path = tempfile.mkstemp(suffix=".f32le")
        os.close(tmp_fd)
        cmd=[FFMPEG,"-y","-i",filepath,"-t","90","-ac","1","-ar","22050","-f","f32le",tmp_path]
        # CRITICO: stdin/stdout/stderr NON devono essere TTY. Se ffmpeg eredita
        # il terminale (server avviato da terminale) resta bloccato in
        # tcsetattr() all'avvio per sempre (e appende la verifica). Con
        # DEVNULL è sicuro e veloce.
        try:
            res=subprocess.run(cmd, stdin=subprocess.DEVNULL,
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                               timeout=60)
        except subprocess.TimeoutExpired:
            print("[ffmpeg_analysis] TIMEOUT dopo 60s → ffmpeg terminato")
            return None
        if res.returncode!=0 or not os.path.exists(tmp_path):
            return None
        with open(tmp_path,"rb") as f:
            raw=f.read()
        if len(raw)<1000: return None
        if np is None: return None  # serve numpy per l'analisi vettorizzata
        raw_a=np.frombuffer(raw,dtype=np.float32); sr=22050; hop=512; window=2048
        # ANALISI VETTORIALIZZATA (numpy): i loop in puro Python della versione
        # precedente tenevano il GIL per minuti (decine di milioni di cos/sin),
        # congelando TUTTO il server (gli altri thread restavano in attesa del
        # GIL). Con numpy il lavoro pesante rilascia il GIL → server reattivo.
        if len(raw_a) < window+hop: return None
        nf=(len(raw_a)-window)//hop
        frames=np.lib.stride_tricks.sliding_window_view(raw_a,window)[::hop][:nf]
        energies=np.sum(frames*frames,axis=1)/window
        onset=np.maximum(0.0,energies[1:]-energies[:-1])
        min_lag=int(sr*60/(200*hop)); max_lag=min(int(sr*60/(50*hop)),len(onset)//2)
        bl=min_lag; bc=-1.0
        for lag in range(min_lag,max_lag):
            c=float(np.dot(onset[:len(onset)-lag],onset[lag:]))
            if c>bc: bc=c; bl=lag
        bpm=round(sr*60/(bl*hop),1)
        while bpm<60: bpm=round(bpm*2,1)
        while bpm>180: bpm=round(bpm/2,1)
        keys=['C','C#','D','D#','E','F','F#','G','G#','A','A#','B']
        # chroma vettorializzato (matrice di fasi precalcolata)
        limit=int(min(len(raw_a), sr*60))
        n_chunk=4096
        jj=np.arange(n_chunk)
        freqs=261.63*(2**(np.arange(12)/12.0))
        phase=2*math.pi*(np.outer(jj,freqs))/sr
        cosm=np.cos(phase); sinm=np.sin(phase)
        chroma=np.zeros(12)
        for i in range(0, limit-n_chunk+1, n_chunk):
            chunk=raw_a[i:i+n_chunk]
            cs=chunk@cosm; ss=chunk@sinm
            chroma+=np.sqrt(cs*cs+ss*ss)
        tot=float(np.linalg.norm(chroma)) or 1.0; chroma=chroma/tot
        mps=np.array([6.35,2.23,3.48,2.33,4.38,4.09,2.52,5.19,2.39,3.66,2.29,2.88])
        mips=np.array([6.33,2.68,3.52,5.38,2.60,3.53,2.54,4.75,3.98,2.69,3.34,3.17])
        mps=mps/np.linalg.norm(mps); mips=mips/np.linalg.norm(mips)
        bk=0; bmo="Major"; bsc=-1.0
        for r in range(12):
            sm=float(np.dot(chroma,np.roll(mps,r)))
            smi=float(np.dot(chroma,np.roll(mips,r)))
            if sm>bsc: bsc=sm; bk=r; bmo="Major"
            if smi>bsc: bsc=smi; bk=r; bmo="Minor"
        return {"bpm":bpm,"key":f"{keys[bk]} {bmo}","source":"ffmpeg","confidence":round(bsc,3)}
    except Exception as e:
        print(f"[ffmpeg_analysis] {e}"); return None
    finally:
        if tmp_path:
            try:
                if os.path.exists(tmp_path): os.remove(tmp_path)
            except Exception: pass

def run_with_timeout(fn, timeout_sec):
    """Esegue fn() in un thread daemon con timeout rigido.
    Ritorna il risultato di fn() oppure None se scade il timeout
    (il thread daemon viene abbandonato, la richiesta HTTP prosegue)."""
    result = [None]
    done = [False]
    def _t():
        try:
            result[0] = fn()
        except Exception:
            result[0] = None
        finally:
            done[0] = True
    th = threading.Thread(target=_t, daemon=True)
    th.start()
    th.join(timeout_sec)
    if not done[0]:
        print(f"[run_with_timeout] TIMEOUT dopo {timeout_sec}s")
        return None
    return result[0]

# ── TUNEBAT SCRAPING ─────────────────────────────────────────────────────────
def scrape_tunebat(artist, title, driver=None):
    """Scrape BPM+Key from Tunebat using headless Chrome.

    Se viene passato un driver già aperto lo riusa (e NON lo chiude);
    altrimenti ne apre uno proprio e lo chiude a fine scraping."""
    own = driver is None
    try:
        if own:
            driver = make_driver()
        query = urllib.parse.quote(f"{artist} {title}")
        search_url = f"https://tunebat.com/Search?q={query}"
        html = fetch_page(driver, search_url)
        if not html:
            return None
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(html, "html.parser")
        track_links = soup.find_all("a", href=re.compile(r"^/track/"))
        if not track_links:
            return None
        detail_url = "https://tunebat.com" + track_links[0]["href"]
        html = fetch_page(driver, detail_url)
        if not html: return None
        bpm_m = re.search(r'(\d+(?:\.\d+)?)\s*BPM', html, re.IGNORECASE)
        key_m = re.search(r'([A-G][#b]?)\s*(Major|Minor)', html, re.IGNORECASE)
        bpm = float(bpm_m.group(1)) if bpm_m else None
        key = None
        if key_m:
            key = f"{key_m.group(1).upper()} {key_m.group(2).capitalize()}"
        if detail_url or bpm or key:
            return {"bpm": bpm, "key": key, "source": "tunebat", "tunebat_url": detail_url}
        return None
    except Exception as e:
        print(f"[tunebat] {e}"); return None
    finally:
        if own and driver is not None:
            try: driver.quit()
            except Exception: pass

def get_metadata_hybrid(artist, title, filename=None):
    """Try librosa → ffmpeg → tunebat, cache in DB"""
    with get_db() as conn:
        r = conn.execute("SELECT bpm,musical_key FROM songs WHERE title=? AND artist=? AND bpm IS NOT NULL",
                         (title,artist)).fetchone()
        if r: return {"bpm":r["bpm"],"key":r["musical_key"],"source":"cache","cached":True}

    result = None
    if filename:
        fp = os.path.join(DL_DIR, filename)
        if os.path.exists(fp):
            if HAS_LIBROSA: result = analyze_audio_librosa(fp)
            if not result: result = analyze_audio_ffmpeg(fp)
    if not result:
        result = scrape_tunebat(artist, title)
    if not result and filename:
        fp = os.path.join(DL_DIR, filename)
        if os.path.exists(fp):
            result = analyze_audio_ffmpeg(fp)

    if result:
        with get_db() as conn:
            sid = get_or_create_song_db(conn, title, artist)
            upd = "bpm=?,musical_key=?,updated_at=datetime('now')"
            vals = [result.get("bpm"), result.get("key")]
            if result.get("tunebat_url"):
                upd += ",tunebat_url=?"
                vals.append(result["tunebat_url"])
            vals.append(sid)
            conn.execute(f"UPDATE songs SET {upd} WHERE id=?", vals)
    return result

def estimate_metadata_local(filename):
    """Stima BPM+Key SOLO dal file audio (librosa → ffmpeg), senza scraping web.
    Usato quando l'utente aggiunge una canzone senza cliccare 'verifica'."""
    if not filename:
        return None
    fp = os.path.join(DL_DIR, filename)
    if not os.path.exists(fp):
        return None
    if HAS_LIBROSA:
        r = analyze_audio_librosa(fp)
        if r:
            return r
    return analyze_audio_ffmpeg(fp)

# ── GENIUS ────────────────────────────────────────────────────────────────────
def _unique_names(names):
    """Elenco di nomi pulito: via i caratteri invisibili di Genius, senza vuoti
    e senza duplicati (case-insensitive), mantenendo l'ordine di arrivo."""
    out, seen = [], set()
    for n in names or []:
        n = re.sub(r'[\u200e\u200f\u202a-\u202e\u2066-\u2069]', '', (n or "")).strip()
        k = normalize(n)
        if n and k and k not in seen:
            seen.add(k)
            out.append(n)
    return out

def _credits_missing(current, names):
    """True se tra i crediti di Genius (`names`) ce n'è almeno uno che NON
    compare in `current` (il valore già salvato, anche come JSON tipo
    '["Nox Beatz", "C-Lance"]'). Serve a riempire i crediti mancanti senza
    riscrivere/cancellare ciò che c'è già (aggiornamento idempotente)."""
    have = normalize(current or "")
    for n in names or []:
        nn = normalize(n)
        if nn and nn not in have:
            return True
    return False

# ── ANNO E ALBUM (dai dati di Genius) ────────────────────────────────────────
# Genius dà la data come testo ("September 2, 2025") e NON l'anno: se non lo si
# ricava, la colonna `year` resta vuota anche quando la data c'è (segnalato il
# 17/09/2026: 13 righe con data e anno vuoto).
_ANNO_RE = re.compile(r'\b(1[89]\d{2}|2[01]\d{2})\b')
def _year_from_date(value):
    """'September 2, 2025' → 2025 · '2002-10-28' → 2002 · None se non c'è."""
    m = _ANNO_RE.search(str(value or ""))
    return int(m.group(1)) if m else None

# ── METADATI DEL VIDEO YOUTUBE (18/09/2026) ──────────────────────────────────
# Richiesta di Alessandro: «se carico una playlist da YouTube … puoi fare in modo
# che prenda automaticamente l'anno dalla data di caricamento del video? e che
# prenda in input anche la descrizione e tutte le altre informazioni disponibili
# da YouTube?» → ogni riga che nasce da una playlist scaricata porta con sé
# quello che il video dice di sé: data di CARICAMENTO (e da lì l'anno), canale,
# descrizione, viste/like/commenti, tag, categoria, miniatura e durata.
#
# Due regole, perché sono due tipi di dato diversi:
# 1) il file scaricato si riconosce dall'`[id]` nel NOME — `DL_OUTTMPL` lo scrive
#    sempre («Titolo [IX7UWaSoVv0].mp3») e ci si arriva anche dopo la conversione
#    in mp3 o una rinomina; col titolo no: YouTube e il disco lo scrivono diverso.
# 2) `year` è un campo CURATO (la Verifica lo scrive da Genius, si corregge a
#    mano): si riempie **solo se è vuoto**. I campi `yt_*` sono fatti letti da
#    YouTube: si riscrivono a ogni download riuscito, e un campo che YouTube non
#    dà non spegne quello che c'era già.
#
# La stessa tupla serve alla migrazione di `init_db` (le colonne si aggiungono da
# sole a un database che esiste già) e al filtro di `resolve_or_create_song`.
CAMPI_YOUTUBE = (
    ("yt_video_id", "TEXT"),        # l'id del video (l'`[id]` nel nome del file)
    ("yt_title", "TEXT"),           # il titolo del video COSÌ COM'È SU YOUTUBE (19/09/2026)
    ("yt_upload_date", "TEXT"),     # data di CARICAMENTO su YouTube, 'YYYY-MM-DD'
    ("yt_release_date", "TEXT"),    # data di uscita dichiarata dal video (se c'è)
    ("yt_channel", "TEXT"),         # canale (o uploader) che l'ha pubblicato
    ("yt_channel_url", "TEXT"),
    ("yt_description", "TEXT"),     # la descrizione del video, intera
    ("yt_views", "INTEGER"),        # view_count
    ("yt_likes", "INTEGER"),        # like_count
    ("yt_comments", "INTEGER"),     # comment_count
    ("yt_tags", "TEXT"),            # tag del video, separati da ', '
    ("yt_category", "TEXT"),        # categorie YouTube (es. 'Music')
    ("yt_thumbnail", "TEXT"),       # URL della miniatura (è un URL, non un file)
    ("yt_duration", "REAL"),        # durata dichiarata dal video, in secondi
    ("yt_meta_at", "TEXT"),         # quando questi dati sono stati letti
)
CAMPI_YOUTUBE_NOMI = tuple(nome for nome, _ in CAMPI_YOUTUBE)

_DATA_RE = re.compile(r"^\s*(\d{4})-?(\d{2})-?(\d{2})\s*$")

def data_da_yt(value):
    """'20250915' (formato di yt-dlp) → '2025-09-15'; '' se non è una data.

    yt-dlp dà `upload_date` (e `release_date`) come otto cifre attaccate; nella
    riga si salva la data leggibile, così si confronta con `release_date`.
    """
    m = _DATA_RE.match(str(value or ""))
    if not m:
        return ""
    anno, mese, giorno = (int(x) for x in m.groups())
    if not (1900 <= anno <= 2999 and 1 <= mese <= 12 and 1 <= giorno <= 31):
        return ""
    return f"{anno:04d}-{mese:02d}-{giorno:02d}"

def id_video_dal_nome_file(nome):
    """'Artista - Titolo [IX7UWaSoVv0].mp3' → 'IX7UWaSoVv0' (o '').

    È la stessa coda che `register_local_file` toglie dal titolo: da lì si sa a
    QUALE voce della playlist appartiene il file scaricato.
    """
    base = os.path.splitext(os.path.basename(str(nome or "")))[0]
    m = re.search(r"\[([A-Za-z0-9_-]{5,})\]\s*$", base)
    return m.group(1) if m else ""

def campi_youtube(info):
    """I campi `yt_*` (e l'anno che ne deriva) che il video racconta di sé, o `{}`.

    `info` è l'info_dict di yt-dlp. Si mettono solo i valori che ci sono davvero:
    un campo assente non spegne quello che era già nella riga.
    """
    if not isinstance(info, dict):
        return {}

    def primo(*chiavi):
        """Il primo valore non vuoto (le liste — tag, categorie — unite da ', ')."""
        for k in chiavi:
            v = info.get(k)
            if isinstance(v, (list, tuple)):
                v = ", ".join(str(x).strip() for x in v if str(x).strip())
            v = str(v or "").strip()
            if v:
                return v
        return ""

    def numero(chiave):
        try:
            return float(info.get(chiave))
        except (TypeError, ValueError):
            return None

    campi = {}
    vid = primo("id")
    if vid:
        campi["yt_video_id"] = vid
    # Data di CARICAMENTO (è quella che diventa l'anno della riga, come chiesto) e,
    # quando il video la dichiara, anche la data di uscita: NON sono la stessa cosa
    # (caso vero misurato il 18/09/2026: «Who Knew» di Eminem è caricato il
    # 31/07/2018 ma il disco è del 2000), quindi si salvano entrambe invece di
    # scegliere per l'utente. L'anno si ricava dalla data di caricamento e, solo se
    # quella manca, da quella di uscita.
    caricamento = data_da_yt(info.get("upload_date"))
    uscita = data_da_yt(info.get("release_date"))
    if caricamento:
        campi["yt_upload_date"] = caricamento
    if uscita:
        campi["yt_release_date"] = uscita
    data_anno = caricamento or uscita
    for colonna, chiavi in (("yt_title", ("title",)),
                            ("yt_channel", ("channel", "uploader")),
                            ("yt_channel_url", ("channel_url", "uploader_url")),
                            ("yt_description", ("description",)),
                            ("yt_tags", ("tags",)),
                            ("yt_category", ("categories", "category")),
                            ("yt_thumbnail", ("thumbnail",))):
        valore = primo(*chiavi)
        if valore:
            campi[colonna] = valore
    for colonna, chiave in (("yt_views", "view_count"), ("yt_likes", "like_count"),
                            ("yt_comments", "comment_count")):
        n = numero(chiave)
        if n is not None:
            campi[colonna] = int(n)
    durata = numero("duration")
    if durata is not None:
        campi["yt_duration"] = durata
    campi["yt_meta_at"] = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    anno = _year_from_date(data_anno) if data_anno else None
    if anno:
        campi["year"] = anno
    return campi

def mappa_metadati_playlist(entries):
    """{id del video: campi `yt_*`} per le voci scaricate di una playlist.

    `entries` è `info["entries"]` di yt-dlp: una voce per video, `None` per i
    video che non si sono potuti scaricare (si saltano). L'id si prende dalla
    voce e, se la voce non lo dice, dall'`[id]` del file che ne è uscito.
    """
    mappa = {}
    for voce in entries or []:
        if not isinstance(voce, dict):
            continue
        campi = campi_youtube(voce)
        file = ""
        richieste = voce.get("requested_downloads") or []
        if richieste and isinstance(richieste[0], dict):
            file = richieste[0].get("filepath") or ""
        vid = campi.get("yt_video_id") or id_video_dal_nome_file(
            file or voce.get("_filename") or "")
        if vid:
            mappa[vid] = campi
    return mappa

# Valori che NON sono il nome di un album: segnaposto delle etichette/degli
# store o del caricamento per cartella (il player usava il nome della cartella:
# 168 brani si erano ritrovati l'album "Mus"). Con uno di questi Genius può
# scrivere sopra; un album "vero", anche corto (es. "2001"), non si tocca.
_ALBUM_SEGNAPOSTO = {"", "mus", "music", "musica", "album", "album sconosciuto",
                     "sconosciuto", "unknown", "unknown album", "various",
                     "various artists", "-", "--", "n/a", "na", "single",
                     "singolo", "download", "downloads", "desktop", "audio",
                     "brani", "mp3", "samplelab"}
def _album_segnaposto(v):
    """True se il campo album è vuoto o è un segnaposto (non un album vero)."""
    return str(v or "").strip().lower() in _ALBUM_SEGNAPOSTO

# ── COPERTINE (cover art) ────────────────────────────────────────────────────
# La colonna `cover_art_path` restava VUOTA per tutte le canzoni: la Verifica
# riempiva titolo, album, BPM, tonalità e testo ma nessuna immagine. La cover si
# prende da Genius — la search API dà `header_image_thumbnail_url` (piccola),
# l'API della singola canzone `song_art_image_url` (quadrata, ~1000 px) — e viene
# salvata come FILE in `covers/`: nel database resta il NOME del file
# (`<id>.<ext>`, es. 'song_7553a924d202.jpg'), non l'URL, che sulle CDN di Genius
# cambia e scade. Le immagini non sono versionate (`covers/` è in .gitignore).
_MIME_ESTENSIONI = {
    "image/jpeg": "jpg", "image/jpg": "jpg", "image/pjpeg": "jpg",
    "image/png": "png", "image/webp": "webp", "image/gif": "gif",
}
_ESTENSIONI_IMMAGINE = {"jpg", "jpeg", "png", "webp", "gif"}

def _cover_ext_from_url(url):
    """Estensione del file di copertina dall'URL ('…/x.jpg?v=1' → 'jpg').
    Se l'URL non dichiara un formato d'immagine si ripiega su 'jpg' (è il
    formato con cui Genius serve quasi tutte le cover)."""
    percorso = urllib.parse.urlparse(str(url or "")).path
    ext = percorso.rsplit(".", 1)[-1].lower() if "." in percorso else ""
    if ext == "jpeg":
        return "jpg"
    return ext if ext in _ESTENSIONI_IMMAGINE else "jpg"

def _cover_filename(song_id, url):
    """Nome del file di copertina di una canzone: `<id>.<ext>`.
    L'id viene ripulito (lettere, numeri, underscore) perché finisce in un
    percorso. Gli id del database sono già del tipo 'song_7553a924d202', quindi
    il file è 'song_7553a924d202.jpg' — stesso nome dell'id, si trova subito."""
    sid = re.sub(r'[^A-Za-z0-9_]', '', str(song_id or "")) or "cover"
    return f"{sid}.{_cover_ext_from_url(url)}"

def _cover_local_path(filename):
    """Percorso su disco di una copertina ('' se il nome è vuoto o non è un
    semplice nome di file: si serve solo dentro covers/, niente percorsi)."""
    nome = os.path.basename(str(filename or ""))
    return os.path.join(COVERS_DIR, nome) if nome else ""

def _cover_mime(filename):
    """Content-type da mandare al browser per una copertina salvata."""
    ext = str(filename or "").rsplit(".", 1)[-1].lower()
    return {"jpg": "image/jpeg", "jpeg": "image/jpeg", "png": "image/png",
            "webp": "image/webp", "gif": "image/gif"}.get(ext, "image/jpeg")

def _cover_mancante(cover_art_path):
    """True se la copertina va (ri)trovata: campo vuoto o file non più su disco.
    Serve perché `covers/` non è versionata: su un altro Mac (o dopo una pulizia)
    il nome nel database c'è ma l'immagine no."""
    percorso = _cover_local_path(cover_art_path)
    return (not percorso) or (not os.path.exists(percorso))

def _looks_like_image(data):
    """True se i primi byte sono la firma di un'immagine vera. Genius a volte
    risponde con una pagina HTML (blocco/errore): senza questo controllo
    salveremmo un '.jpg' che immagine non è."""
    if not data or len(data) < 12:
        return False
    if data[:3] == b"\xff\xd8\xff":                        # JPEG
        return True
    if data[:8] == b"\x89PNG\r\n\x1a\n":                   # PNG
        return True
    if data[:6] in (b"GIF87a", b"GIF89a"):                 # GIF
        return True
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":      # WEBP
        return True
    return data[:2] == b"BM"                               # BMP

def _genius_cover_url(search_res, song_data=None):
    """URL della copertina da Genius, dalla migliore alla peggiore: l'immagine
    quadrata della singola canzone (~1000 px), la sua versione grande, poi la
    miniatura della ricerca."""
    for valore in (
        (song_data or {}).get("song_art_image_url"),
        (song_data or {}).get("header_image_url"),
        (song_data or {}).get("song_art_image_thumbnail_url"),
        (search_res or {}).get("song_art_image_url"),
        (search_res or {}).get("header_image_thumbnail_url"),
        (search_res or {}).get("header_image_url"),
    ):
        if valore and str(valore).startswith("http"):
            return str(valore)
    return ""

_COVER_MAX_BYTES = 8 * 1024 * 1024

def _scarica_immagine(url, timeout=20):
    """Scarica i byte di un'immagine (b'' se la risposta non è un'immagine o se è
    troppo grande: le cover più pesanti di Genius stanno sotto 1 MB)."""
    import urllib.request
    req = urllib.request.Request(url, headers={
        "User-Agent": ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                       "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"),
        "Accept": "image/avif,image/webp,image/*,*/*;q=0.8",
        "Referer": "https://genius.com/",
    })
    with urllib.request.urlopen(req, timeout=timeout) as r:
        data = r.read(_COVER_MAX_BYTES + 1)
    if len(data) > _COVER_MAX_BYTES:
        print(f"[cover] immagine troppo grande ({len(data)} byte), scartata")
        return b""
    if not _looks_like_image(data):
        print("[cover] la risposta non è un'immagine (probabile pagina di errore)")
        return b""
    return data

def _cover_da_tag_audio(path):
    """Copertina incorporata nel file audio: MP3 (APIC), M4A/MP4 (covr), FLAC
    (pictures). Ritorna (byte, estensione) oppure (b'', ''): è il ripiego per i
    brani che Genius non conosce (file locali)."""
    if not path or not os.path.exists(path) or not HAS_MUTAGEN:
        return b"", ""
    try:
        from mutagen import File as MutagenFile
        f = MutagenFile(path)
        if not f:
            return b"", ""
        candidati = []
        tag = f.tags
        if isinstance(tag, dict):
            for voce in (tag.get("covr") or []):                 # MP4 / M4A
                candidati.append((getattr(voce, "data", None) or bytes(voce),
                                  getattr(voce, "mime", "") or ""))
        try:                                                     # MP3 (ID3)
            for apic in (tag.getall("APIC") if hasattr(tag, "getall") else []):
                candidati.append((getattr(apic, "data", b""), getattr(apic, "mime", "") or ""))
        except Exception:
            pass
        for pic in (getattr(f, "pictures", []) or []):           # FLAC
            candidati.append((getattr(pic, "data", b""), getattr(pic, "mime", "") or ""))
        for data, mime in candidati:
            data = bytes(data or b"")
            if _looks_like_image(data):
                ext = _MIME_ESTENSIONI.get(str(mime).lower().split(";")[0].strip())
                if not ext:
                    ext = "png" if data[:8] == b"\x89PNG\r\n\x1a\n" else "jpg"
                return data, ext
    except Exception as e:
        print(f"[cover] tag audio: {e}")
    return b"", ""

def _estensione_da_nome_o_mime(nome="", mime=""):
    """L'estensione dell'immagine ('cover.PNG' → 'png', 'image/webp' → 'webp').

    Funzione PURA. Default 'jpg': è il formato con cui arrivano quasi tutte le
    copertine. Un'estensione che non è un'immagine si ignora.
    """
    ext = str(nome or "").rsplit(".", 1)[-1].lower()
    if ext == "jpeg":
        ext = "jpg"
    if ext in _ESTENSIONI_IMMAGINE:
        return ext
    m = str(mime or "").lower().split(";")[0].strip()
    return _MIME_ESTENSIONI.get(m, "jpg")

def salva_copertina_bytes(song_id, dati, ext="jpg"):
    """Scrive la copertina di una canzone in `covers/<id>.<ext>`.

    Ritorna `(nome_file, errore)`: `("", motivo)` se i byte non sono un'immagine
    vera (si guarda la FIRMA del file, non l'estensione: dal web può arrivare una
    pagina HTML travestita da .jpg). Una sola immagine per canzone: la vecchia di
    un ALTRO formato va in `.trash/` (recuperabile), come fa la Verifica quando il
    formato cambia. È la strada delle copertine caricate/scelte a mano (18/09/2026).
    """
    if not _looks_like_image(dati):
        return "", "il file non è un'immagine (jpg, png, webp o gif)"
    ext = str(ext or "jpg").lower()
    if ext not in _ESTENSIONI_IMMAGINE:
        ext = "jpg"
    sid = re.sub(r'[^A-Za-z0-9_]', '', str(song_id or "")) or "cover"
    nome = f"{sid}.{ext}"
    try:
        with open(_cover_local_path(nome), "wb") as fh:
            fh.write(dati)
    except OSError as e:
        return "", f"non riesco a salvare la copertina ({str(e)[:60]})"
    for altro in os.listdir(COVERS_DIR):
        if altro != nome and altro.startswith(f"{sid}."):
            try:
                move_to_trash(os.path.join(COVERS_DIR, altro))
            except Exception:
                pass
    return nome, ""

def nome_cover_archivio(nome):
    """Un nome di copertina è utilizzabile? (semplice nome di file, immagine).

    Funzione PURA: niente percorsi (`../`), niente nomi vuoti, estensione di
    immagine. Serve a `POST /db/songs/<id>/cover` quando si SCEGLIE una copertina
    già presente in `covers/` invece di caricarla.
    """
    base = os.path.basename(str(nome or "").strip())
    if not base or base != str(nome or "").strip():
        return False
    return os.path.splitext(base)[1].lower().lstrip(".") in _ESTENSIONI_IMMAGINE

def _salva_copertina(song_id, cover_url="", local_file=""):
    """Salva la copertina della canzone in `covers/`. Ritorna (nome_file|None, msg).

    Fonte 1: l'immagine di Genius (`cover_url`, già grande e quadrata).
    Fonte 2 (ripiego): la copertina incorporata nel file audio locale, così
    anche i brani che Genius non conosce possono avere la loro immagine.
    """
    dati, nome, origine = b"", "", ""
    if cover_url:
        try:
            dati = _scarica_immagine(cover_url)
            if dati:
                nome, origine = _cover_filename(song_id, cover_url), "Genius"
        except Exception as e:
            print(f"[cover] download da Genius fallito: {e}")
    if not dati and local_file:
        dati, ext = _cover_da_tag_audio(os.path.join(DL_DIR, local_file))
        if dati:
            nome, origine = _cover_filename(song_id, "." + ext), "tag del file audio"
    if not dati or not nome:
        return None, "⚠️ Copertina non trovata (né su Genius né nel file audio)"
    try:
        with open(_cover_local_path(nome), "wb") as fh:
            fh.write(dati)
    except OSError as e:
        return None, f"⚠️ Copertina non salvata ({str(e)[:60]})"
    # Una sola immagine per canzone: se il formato è cambiato (jpg → png) il file
    # vecchio va rimosso, altrimenti resterebbe orfano nella cartella.
    prefisso = f"{re.sub(r'[^A-Za-z0-9_]', '', str(song_id or ''))}."
    for altro in os.listdir(COVERS_DIR):
        if altro != nome and altro.startswith(prefisso):
            try: os.remove(os.path.join(COVERS_DIR, altro))
            except OSError: pass
    return nome, f"🖼 Copertina salvata ({origine}): {nome} · {max(1, len(dati) // 1024)} KB"

def fetch_genius(artist, title):
    """Fetch da Genius: URL, titolo, artista, produttori, compositori (writers),
    album, artista album, data e cover.

    Usa la search API per trovare la canzone e poi l'API della singola canzone
    (writer_artists → compositori, producer_artists → produttori, album.artist
    → artista album) per i campi extra."""
    try:
        import urllib.request
        import time
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept": "application/json",
            "Accept-Language": "en-US,en;q=0.9",
            "Origin": "https://genius.com",
            "Referer": "https://genius.com/"
        }
        # L'artista segnaposto ("Brano locale", "Artista sconosciuto"…) NON va
        # messo nella query: la search API rispondeva **zero** risultati
        # ("Brano locale The Sauce…"), ed è il motivo per cui sui brani locali la
        # Verifica non trovava né album né data (segnalato il 17/09/2026). Col
        # solo titolo la soglia è più alta e il titolo deve combaciare (sotto).
        artista_query = "" if is_placeholder_artist(artist) else (artist or "")
        q = urllib.parse.quote(f"{artista_query} {title}".strip())
        url = f"https://genius.com/api/search/multi?q={q}"
        req = urllib.request.Request(url, headers=headers)
        time.sleep(0.5)  # Evita rate limit
        with urllib.request.urlopen(req, timeout=15) as r:
            data = json.loads(r.read())
        hits = data.get("response", {}).get("sections", [])

        # Raccolta di tutte le hit "song" con punteggio fuzzy (match_score):
        # si prende la MIGLIORE e solo se supera la soglia (0.55, come nel resto
        # dell'app). Così un titolo "sporco" (es. "1 - TRE STRONZI" invece di
        # "TRE STRONZI") non porta a salvare la canzone sbagliata e il chiamante
        # può attivare il fallback YouTube per correggere il titolo.
        best = None
        best_score = 0.0
        # Per la ricerca col solo titolo serve sapere se quel titolo è UNIVOCO:
        # se lo stesso titolo appartiene a più artisti non identifica la canzone
        # (misurato il 17/09/2026: 'Cha-Ching' → 2 artisti, 'Apex Predator' → 3).
        artisti_con_stesso_titolo = set()
        for sec in hits:
            if sec.get("type") != "song":
                continue
            for h in sec.get("hits", []):
                res = h.get("result", {})
                if not res:
                    continue
                hit_artist = re.sub(r'[\u200e\u200f\u202a-\u202e\u2066-\u2069]', '', (res.get("primary_artist") or {}).get("name", "")).strip()
                hit_title = re.sub(r'[\u200e\u200f\u202a-\u202e\u2066-\u2069]', '', res.get("title", "")).strip()
                if title and normalize(hit_title) == normalize(title):
                    artisti_con_stesso_titolo.add(normalize(hit_artist))
                sc = match_score(artist or "", title or "", hit_artist, hit_title)
                if sc > best_score:
                    best_score = sc
                    best = (res, hit_artist, hit_title)
        # Soglia 0.55 come nel resto dell'app; più alta (0.75) quando si cerca col
        # SOLO titolo (artista vuoto o segnaposto), perché lì l'artista non aiuta
        # il confronto e la search API può proporre un omonimo: caso reale
        # 16/09/2026, titolo "Apex" senza artista → "Apex Predator" del musical
        # Mean Girls (i credits di un'altra canzone finivano nel database).
        artist_missing = (not (artist or "").strip()) or is_placeholder_artist(artist)
        min_score = 0.75 if artist_missing else 0.55
        if not best or best_score < min_score:
            print(f"[genius] nessuna hit sopra soglia (best={best_score:.2f}, soglia {min_score})")
            return None
        # Senza artista il match va giudicato sul TITOLO: `match_score` dà 1.0
        # all'artista vuoto ("" è "contenuto" in qualsiasi nome) e un titolo
        # contenuto nell'altro prende 0.85+, quindi la soglia da sola non basta.
        # Qui si accetta solo un titolo (quasi) identico: meglio nessun dato che
        # i credits di un'altra canzone.
        if artist_missing and normalize(best[2]) != normalize(title or ""):
            print(f"[genius] ricerca col solo titolo: scartato '{best[2]}' (richiesto '{title}')")
            return None
        res, hit_artist, hit_title = best
        feat = [a.get("name", "") for a in res.get("featured_artists", [])]
        # SENZA ARTISTA non basta il titolo identico: un titolo uguale può essere
        # di un ALTRO artista (caso reale 17/09/2026: 'Cha-Ching' in libreria →
        # "Cha-Ching!" di Unique Salonga, score 0.87). Si accetta solo se l'artista
        # di Genius è riconoscibile nel titolo — direttamente o perché è un artista
        # noto della libreria citato lì. Meglio nessun dato che un omonimo.
        if artist_missing:
            norm_titolo = normalize(title or "")
            noto = known_artist_in_title(title or "", get_db_artist_list())
            norm_noto = normalize(noto or "")

            def _artista_identificabile(a):
                na = normalize(a or "")
                if not na:
                    return False
                if na in norm_titolo:
                    return True
                return bool(norm_noto) and (norm_noto in na or na in norm_noto)

            titolo_univoco = len(artisti_con_stesso_titolo) == 1
            identificabile = any(_artista_identificabile(a) for a in [hit_artist] + feat)
            if not (titolo_univoco or identificabile):
                print(f"[genius] ricerca col solo titolo: '{hit_title}' di {hit_artist} "
                      f"non identificabile (titolo condiviso da "
                      f"{len(artisti_con_stesso_titolo)} artisti, artista non citato) → scartato")
                return None

        song = {
            "genius_url": res.get("url"),
            "title": hit_title,
            "artist": hit_artist,
            # TUTTI gli artisti (primary + feat.) nell'ordine di Genius: è questo
            # elenco che finisce nel campo `artist` del database.
            "artists": _unique_names([hit_artist] + feat),
            "score": round(best_score, 3),
            "featured_artists": feat,
            "producers": [p.get("name", "") for p in res.get("producer_artists", [])],
            "composers": [],
            "album_artist": "",
            "release_date": res.get("release_date_for_display", ""),
            "album": (res.get("album") or {}).get("name", ""),
            # Copertina: miniatura della ricerca come base, poi l'API della
            # singola canzone la sostituisce con l'immagine quadrata grande.
            "cover_art": _genius_cover_url(res),
        }
        # API della singola canzone: compositori (writer), produttori, album
        # artist, feat. ufficiali. Questa chiamata è l'unica fonte dei produttori:
        # quando Genius risponde vuoto o 429 i crediti restavano vuoti, quindi si
        # ritenta una volta (caso reale 16/09/2026: 7 brani verificati su 54
        # senza produttori e 5 senza compositori).
        sid = res.get("id")
        for attempt in (1, 2):
            if not sid:
                break
            try:
                time.sleep(0.3 if attempt == 1 else 1.5)
                req2 = urllib.request.Request(f"https://genius.com/api/songs/{sid}", headers=headers)
                with urllib.request.urlopen(req2, timeout=15) as r2:
                    sdata = json.loads(r2.read()).get("response", {}).get("song", {})
                if not sdata:
                    continue
                writers = _unique_names([a.get("name", "") for a in sdata.get("writer_artists", [])])
                prods = _unique_names([a.get("name", "") for a in sdata.get("producer_artists", [])])
                feat2 = _unique_names([a.get("name", "") for a in sdata.get("featured_artists", [])])
                if writers:
                    song["composers"] = writers
                if prods:
                    song["producers"] = prods
                if feat2:
                    song["featured_artists"] = feat2
                    song["artists"] = _unique_names([hit_artist] + feat2)
                alb = sdata.get("album") or {}
                if alb.get("name"):
                    song["album"] = alb["name"]
                if (alb.get("artist") or {}).get("name"):
                    song["album_artist"] = alb["artist"]["name"]
                if sdata.get("release_date_for_display"):
                    song["release_date"] = sdata["release_date_for_display"]
                # Copertina grande (~1000 px) dalla singola canzone: la miniatura
                # che arriva dalla ricerca è 200 px e sgrana nella scheda.
                cover_big = _genius_cover_url(res, sdata)
                if cover_big:
                    song["cover_art"] = cover_big
                if writers or prods:
                    break
                print(f"[genius song api] risposta senza crediti (tentativo {attempt}/2)")
            except Exception as e:
                print(f"[genius song api] tentativo {attempt}/2: {e}")
        return song
    except Exception as e:
        print(f"[genius] Error: {e}")
    return None
# Header di traduzione che Genius mette in cima ai testi non inglesi o tradotti
# (es. [Testo di "90MIN"], [English translation of "..."], [Letra de "..."]).
# Non è testo reale: va saltato così il testo parte subito dal primo marker vero
# (es. [Strofa 1], [Intro]) o dalla prima riga cantata.
_TRANS_KEYS = (r'Testo\s+di|Traduç[ãa]o\s+d[ei]|Traduzione|Traducci[óo]n\s+de|'
               r'Translat\w*\s+of|Letra\s+de|Paroles?\s+de|Songtekst\s+van|'
               r'Liedtext\s+von|Текст\w*|Песни\w*|Çeviri|الترجمة')
TRANS_HEADER_RE = re.compile(
    r'^\s*\[[^\]\n]{0,90}(?:' + _TRANS_KEYS + r')[^\]\n]{0,90}\]\s*$',
    re.IGNORECASE)


def _clean_lyrics(text):
    """Pulisce il testo Genius: toglie la spazzatura della pagina (es. '8 Contributors',
    '10 Laws Lyrics', descrizioni tipo 'Read More', 'You might also like', 'Embed', 'About',
    header di traduzione tipo '[Testo di "90MIN"]')
    e fa iniziare il testo dal primo marker di sezione (es. [Intro])."""
    import html as _html
    if not text:
        return text
    text = _html.unescape(text)                            # &#x27; → '  &amp; → &  ...
    text = text.replace('\r\n', '\n').replace('\r', '\n').replace('\u00a0', ' ')

    # 1) Inizia dal primo marker di sezione [...]: prima cerca marker a inizio riga
    #    (più affidabile), poi qualunque [...] nel testo (gestisce anche testo attaccato
    #    tipo '8 Contributors10 Laws Lyrics[Intro]'). Gli header di traduzione Genius
    #    ([Testo di "..."], [English translation of "..."], ...) vengono saltati.
    raw_lines = text.split('\n')
    idx = None
    for i, ln in enumerate(raw_lines):
        if re.match(r'^\s*\[[^\]\n]{1,60}\]\s*$', ln) and not TRANS_HEADER_RE.match(ln):
            idx = i
            break
    if idx is not None:
        text = '\n'.join(raw_lines[idx:])
    else:
        m = None
        for mm in re.finditer(r'\[[^\]\n]{1,60}\]', text):
            if not TRANS_HEADER_RE.match(mm.group(0)):
                m = mm
                break
        if m:
            text = text[m.start():]

    lines = [ln.strip() for ln in text.split('\n')]

    JUNK_ANYWHERE = re.compile(
        r'^Read\s+More\.?$'
        r'|^Embed\s*$'
        r'|^Translations?\s*$'
        r'|^You\s+might\s+also\s+like\.?\s*$'
        r'|^How\s+to\s+Format\s+Lyrics:.*$'
        r'|^\[' + '(?:' + _TRANS_KEYS + ')' + r'[^\]\n]{0,90}\]$',
        re.IGNORECASE)
    JUNK_LEAD = re.compile(
        r'^\d+\s*[Cc]ontributors?$'
        r'|^.{1,80}\s+Lyrics\s*$',
        re.IGNORECASE)
    JUNK_TAIL = re.compile(
        r'^(About|Verified\s+Bio|Live\s+Performances?|Q\s*&\s*A|Expand|Lyrics|Embed|Cancel)\s*$'
        r'|^\d+\s*[Cc]ontributors?$',
        re.IGNORECASE)

    # 2) Righe spazzatura anche in mezzo al testo (You might also like, Read More...)
    lines = [ln for ln in lines if not JUNK_ANYWHERE.match(ln)]

    # 3) Righe spazzatura all'inizio (N Contributors, 'Title Lyrics', header di traduzione)
    while lines and (not lines[0] or JUNK_LEAD.match(lines[0]) or TRANS_HEADER_RE.match(lines[0])):
        lines.pop(0)

    # 4) Righe spazzatura in coda (About, Verified Bio, Contributors...)
    while lines and (not lines[-1] or JUNK_TAIL.match(lines[-1])):
        lines.pop()

    text = "\n".join(lines).strip()
    # 5) Normalizza spazi e righe vuote
    text = re.sub(r'[ \t]+', ' ', text)
    text = re.sub(r'\n{3,}', '\n\n', text)
    return text

def fetch_genius_lyrics_text(genius_url):
    """Fetch actual lyrics text from a Genius page (pulito). Strategie in ordine:
    1) richiesta diretta; 2) pool di proxy con RETRY (allorigins è instabile);
    3) browser Chrome (undetected_chromedriver) per bypassare il blocco 403."""
    import urllib.request
    import urllib.parse

    def _parse(html):
        import re
        # 1) Estrazione robusta dei container lyrics con un vero parser HTML
        try:
            from bs4 import BeautifulSoup
            soup = BeautifulSoup(html, "html.parser")
            parts = [c.get_text("\n") for c in soup.select('[data-lyrics-container="true"]')]
            if parts:
                return "\n".join(parts)
        except Exception:
            pass
        # 2) Fallback regex sui container + JSON 'lyrics.plain' della pagina
        parts = re.findall(r'data-lyrics-container="true"[^>]*>(.*?)</div>', html, re.DOTALL)
        if not parts:
            m = re.search(r'"lyrics":\{"plain":"(.*?)"', html)
            if m:
                s = m.group(1)
                for a, b in [("\\n", "\n"), ("\\u0027", "'"), ("\\u0026", "&"),
                             ("\\u0022", '"'), ("\\u002F", "/"), ("\\u003C", "<"),
                             ("\\u003E", ">")]:
                    s = s.replace(a, b)
                return s
        text = "\n".join(re.sub(r'<[^>]+>', ' ', p) for p in parts)
        text = re.sub(r' +', ' ', text).strip()
        return text if text else None

    def _fetch(url, timeout=25):
        req = urllib.request.Request(url, headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9"})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.read().decode("utf-8", errors="ignore")

    # 1) Tentativo diretto
    try:
        html = _fetch(genius_url, 15)
        text = _parse(html)
        if text and len(text.strip()) > 20:
            return _clean_lyrics(text)
    except Exception as e:
        print(f"[genius_lyrics direct] {e}")

    # 2) Pool di proxy (come fa il player per aggirare il blocco di Genius)
    #    con 2 passate e timeout brevi: così il peggiore dei casi resta sotto
    #    ~1,5 min invece di bloccare la verifica per 5+ minuti.
    proxies = [
        "https://api.allorigins.win/raw?url=",
        "https://api.allorigins.win/get?url=",
        "https://corsproxy.io/?url=",
        "https://api.codetabs.com/v1/proxy?quest=",
    ]
    for pass_ in range(2):
        for p in proxies:
            try:
                url = p + urllib.parse.quote(genius_url, safe="")
                html = _fetch(url, 12)
                # allorigins /get restituisce un JSON con {contents: html}
                if "get?url=" in p:
                    try:
                        html = json.loads(html).get("contents", html)
                    except Exception:
                        pass
                text = _parse(html)
                if text and len(text.strip()) > 20:
                    return _clean_lyrics(text)
            except Exception as e:
                print(f"[genius_lyrics proxy {pass_}] {e}")
            time.sleep(0.8)
        time.sleep(1.5)

    # 3) Ultima spiaggia: browser Chrome (bypassa il blocco 403 di Genius)
    #    — solo se i proxy hanno fallito, con timeout breve.
    try:
        from bs4 import BeautifulSoup
        driver = _make_driver_safe(30)
        try:
            driver.get(genius_url)
            time.sleep(1.5)
            soup = BeautifulSoup(driver.page_source, "html.parser")
            parts = [c.get_text("\n") for c in soup.select('[data-lyrics-container="true"]')]
            if parts:
                text = "\n".join(parts)
                if len(text.strip()) > 20:
                    return _clean_lyrics(text)
        finally:
            try: driver.quit()
            except Exception: pass
    except Exception as e:
        print(f"[genius_lyrics browser] {e}")

    return None

# ── FILENAME CLEANER ──────────────────────────────────────────────────────────
def clean_filename(name):
    """Remove common suffixes: '- Copia', '(1)', '[Official Video]', etc."""
    # Remove extension
    base = re.sub(r'\.[^.]+$', '', name)
    # Remove ' - Copia', ' - Copy'
    base = re.sub(r'\s*[-–]\s*cop[yi]a?\s*$', '', base, flags=re.IGNORECASE)
    # Remove trailing (1), (2), ...
    base = re.sub(r'\s*\(\d+\)\s*$', '', base)
    # Remove l'[ID YouTube] (11 caratteri) del template di download:
    # "Eminem - 'Till I Collapse [Explicit] [Pi3_Zs-oRUo]" → titolo pulito.
    # Solo 11 caratteri alfanumerici, così "[Remix Version]" resta intatto.
    base = re.sub(r'\s*\[[A-Za-z0-9_-]{11}\]\s*$', '', base)
    # Remove [Official Video], (Audio), etc.
    base = re.sub(r'\s*[\[\(][^\]\)]*(?:official|audio|video|lyric|hd|4k|mv|clip)[^\]\)]*[\]\)]\s*', '', base, flags=re.IGNORECASE)
    # Remove ★, •, and similar
    base = re.sub(r'[★•·|–—]', '-', base)
    # Collapse multiple spaces/dashes
    base = re.sub(r'\s{2,}', ' ', base).strip()
    base = re.sub(r'-{2,}', '-', base).strip(' -')
    return base

# ── YOUTUBE UTILITIES ────────────────────────────────────────────────────────
def is_youtube_url(s):
    return "youtube.com/watch" in s or "youtu.be/" in s

# ── VERSIONI ESPLICITE vs CENSURATE ─────────────────────────────────────────
_EXPLICIT_RE = re.compile(
    r'[\(\[]\s*(?:explicit|uncensored|unedited|uncut)\s*[\)\]]'
    r'|\b(?:explicit|uncensored|unedited|uncut|nsfw)\b'
    r'|\bdirty\s+version\b|\bdirty\s+edit\b',
    re.IGNORECASE)

_CLEAN_RE = re.compile(
    r'[\(\[]\s*(?:clean|censored)\s*[\)\]]'
    r'|\b(?:censored|clean\s+version|clean\s+edit|radio\s+edit|edited\s+version)\b'
    r'|\bno\s+swears?\b|\bwithout\s+cursing\b|\bsfw\b',
    re.IGNORECASE)

def _yt_fetch_entries(query):
    """Esegue ytsearch20 e restituisce le entry (con timeout ~25s)."""
    ydl_opts = {"quiet": True, "extract_flat": True, "noplaylist": True}
    info_box = [None]; exc_box = [None]
    def _do_yt_search():
        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info_box[0] = ydl.extract_info(f"ytsearch20:{query}", download=False)
        except Exception as e:
            exc_box[0] = e
    t = threading.Thread(target=_do_yt_search, daemon=True)
    t.start()
    t.join(25)
    if t.is_alive():
        print("[yt_search] TIMEOUT dopo 25s")
        return []
    if exc_box[0]:
        print(f"[yt_search] errore: {exc_box[0]}")
        return []
    info = info_box[0]
    return info.get("entries", []) if info else []

def _rank_yt_entries(entries, expected_title="", expected_artist=""):
    """Classifica le entry YouTube per pertinenza, preferendo le versioni
    esplicite/uncensored e penalizzando quelle censurate. Restituisce una lista
    di dict ordinata per score decrescente."""
    from difflib import SequenceMatcher
    et = normalize(expected_title) if expected_title else ""
    ea = normalize(expected_artist) if expected_artist else ""
    ranked = []
    for e in entries:
        raw_title = e.get("title", "")
        vt = normalize(raw_title)
        duration = e.get("duration", 0)
        if duration and (duration < 20 or duration > 1200):
            print(f"[yt_search]  '{raw_title}' -> durata {duration}s, scartato")
            continue
        score = SequenceMatcher(None, et, vt).ratio()
        if duration and duration < 60:
            # clip/anteprima di pochi secondi: quasi mai il brano che serve
            # (penalità, non esclusione: se è l'unica versione resta selezionabile)
            score -= 0.25
        if ea and ea in vt:
            score += 0.15
        lower = raw_title.lower()
        if "feat" in lower or "featuring" in lower or "with" in lower:
            score += 0.10
        channel = e.get("channel", "").lower()
        if ea and (ea in normalize(channel) or "official" in channel):
            score += 0.20
        for w in ["cover", "remix", "live", "acoustic", "instrumental", "karaoke",
                  "8-bit", "8bit", "reaction", "review", "slowed", "reverb", "nightcore"]:
            if w in lower:
                score -= 0.25
                break
        if re.search(r'\bpart\s*2\b|\bpt\.?\s*2\b|\bii\b|\b2\.0\b', lower) and not re.search(r'\b2\b', et):
            score -= 0.30
        # versione esplicita/uncensored: bonus · versione censurata: penalità
        explicit = bool(_EXPLICIT_RE.search(raw_title))
        clean = bool(_CLEAN_RE.search(raw_title))
        if explicit:
            score += 0.20
        if clean:
            score -= 0.25
        ranked.append({
            "url": e.get("webpage_url") or e.get("url"),
            "title": raw_title,
            "channel": e.get("channel", "") or "",
            "score": round(score, 3),
            "explicit": explicit,
            "clean": clean,
            "duration": duration or 0,
        })
    # A parità di score si preferisce la versione più lunga (brano completo
    # invece di una clip di pochi secondi).
    ranked.sort(key=lambda r: (r["score"], r["duration"]), reverse=True)
    return ranked

def yt_search_first(query, expected_title="", expected_artist="", min_duration=0):
    entries = _yt_fetch_entries(query)
    if not entries:
        return None, None

    if not expected_title:
        e = entries[0]
        return e.get("webpage_url") or e.get("url"), e.get("title", "")

    et = normalize(expected_title)
    ea = normalize(expected_artist) if expected_artist else ""
    ranked = _rank_yt_entries(entries, expected_title, expected_artist)
    for r in ranked:
        tag = (" [ESPLICITA]" if r["explicit"] else "") + (" [CENSURATA]" if r["clean"] else "")
        print(f"[yt_search]  '{r['title']}' -> score={r['score']:.3f} ({r.get('duration')}s){tag}")

    # Un titolo identico vince sempre; fra più titoli identici si sceglie però il
    # migliore (score + durata), così una clip di 30 s non batte la versione
    # completa del brano (caso "Sam Is Dead", 16/09/2026).
    exact = [r for r in ranked if r["url"] and normalize(r["title"]) == et]
    if exact:
        if min_duration:
            # Serve un audio che CONTENGA il timestamp del sample (min_duration):
            # se nessun titolo identico è abbastanza lungo si accetta un titolo
            # simile abbastanza lungo (es. la versione da 401 s invece di quella
            # tagliata da 170 s, che non arriva a 3:36). L'allargamento si fa
            # SOLO con un artista noto e solo se l'artista compare nel titolo o
            # nel canale: senza questo ancoraggio si pescava un omonimo sbagliato
            # (caso osservato: "Sam Is Dead | Ghost (1990)", un video sul film).
            long_exact = [r for r in exact if (r.get("duration") or 0) >= min_duration]
            if not long_exact and ea:
                long_exact = [r for r in ranked if r["url"]
                              and (r.get("duration") or 0) >= min_duration
                              and r["score"] >= 0.55
                              and ea in normalize(r["title"] + " " + (r.get("channel") or ""))]
            if long_exact:
                exact = long_exact
        best = max(exact, key=lambda r: (r["score"], r.get("duration") or 0))
        if normalize(best["title"]) == et:
            print(f"[yt_search]  MATCH ESATTO: {best['title']} "
                  f"({best.get('duration')}s, score {best['score']:.3f})")
        else:
            print(f"[yt_search]  SCELTO (titolo simile, serviva >= {min_duration:g}s): "
                  f"{best['title']} ({best.get('duration')}s, score {best['score']:.3f})")
        return best["url"], best["title"]

    if ranked and ranked[0]["score"] >= 0.55 and ranked[0]["url"]:
        print(f"[yt_search]  => SCELTO: {ranked[0]['title']} (score {ranked[0]['score']:.3f})")
        return ranked[0]["url"], ranked[0]["title"]

    print("[yt_search]  => NESSUN MATCH sopra soglia 0.55")
    return None, None

def yt_search_choices_prefer_explicit(query, expected_title="", expected_artist="", limit=6):
    """Come yt_search_choices, ma esegue anche una seconda ricerca mirata alle
    versioni 'explicit/uncensored' e la fonde nelle scelte. Se esiste una versione
    esplicita con punteggio decente, la restituisce come predefinita (il primo
    chip nel selettore) così l'utente sente l'uncensored senza doverla cercare."""
    url, title, choices = yt_search_choices(query, expected_title=expected_title,
                                            expected_artist=expected_artist, limit=limit)
    # Seconda ricerca mirata alle versioni esplicite/uncensored
    _, _, extra = yt_search_choices(f"{query} explicit uncensored",
                                    expected_title=expected_title,
                                    expected_artist=expected_artist, limit=limit)
    merged = list(choices)
    seen = {c["url"] for c in merged if c["url"]}
    for c in extra:
        if c["url"] and c["url"] not in seen:
            merged.append(c)
            seen.add(c["url"])

    best_explicit = None
    for c in merged:
        if c.get("explicit") and c.get("score", 0) >= 0.5:
            if best_explicit is None or c["score"] > best_explicit["score"]:
                best_explicit = c

    # La versione esplicita va in cima (e non deve essere tagliata dal limite)
    if best_explicit:
        merged = [best_explicit] + [c for c in merged if c["url"] != best_explicit["url"]]

    merged = merged[:limit]

    if best_explicit:
        return best_explicit["url"], best_explicit["title"], merged
    return url, title, merged

def yt_search_choices(query, expected_title="", expected_artist="", limit=6):
    """Come yt_search_first ma restituisce anche la lista dei candidati migliori
    (con flag explicit/clean) così l'utente può scegliere la versione preferita
    (es. uncensored vs censurata)."""
    entries = _yt_fetch_entries(query)
    if not entries:
        return None, None, []

    if not expected_title:
        e = entries[0]
        return e.get("webpage_url") or e.get("url"), e.get("title", ""), []

    ranked = _rank_yt_entries(entries, expected_title, expected_artist)
    ranked = [r for r in ranked if r["url"] and r["score"] >= 0.45][:limit]
    # Il match esatto (se esiste) deve vincere comunque, ma torniamo le scelte
    et = normalize(expected_title)
    for i, r in enumerate(ranked):
        if normalize(r["title"]) == et:
            ranked.insert(0, ranked.pop(i))
            break
    for r in ranked:
        tag = (" [ESPLICITA]" if r["explicit"] else "") + (" [CENSURATA]" if r["clean"] else "")
        print(f"[yt_search]  (scelta) '{r['title']}' -> score={r['score']:.3f}{tag}")

    if ranked:
        return ranked[0]["url"], ranked[0]["title"], ranked
    return None, None, []

# ── DOWNLOAD ──────────────────────────────────────────────────────────────────
# Limita i download YouTube simultanei (troppi in parallelo → rate-limit/403)
DL_SEM = threading.Semaphore(2)

# Estensioni considerate "file audio" della cartella download.
AUDIO_EXTS = (".mp3", ".wav", ".m4a", ".webm", ".mp4", ".ogg", ".opus", ".flac")

# Nome dei file scaricati da YouTube: l'[id] del video è indispensabile perché
# due video diversi possono avere lo STESSO titolo (bug del 16/09/2026: le cover
# "8-Bit Misfits" e "Twinkle Twinkle Little Rock Star" di 'Till I Collapse
# finivano nello stesso file e la seconda riproduceva l'audio della prima).
DL_OUTTMPL = "%(title)s [%(id)s].%(ext)s"

def _downloads_snapshot(folder=None):
    """Nome file -> (mtime, size) della cartella indicata (default: `downloads/`).

    Serve a capire quali file ha creato UN determinato job: senza questo
    confronto un download fallito poteva "adottare" il file scritto da un altro
    download in corso (bug del 16/09/2026: il sample "Sam Is Dead" riproduceva
    l'audio di "Mosh"). Dal 18/09/2026 la stessa foto si fa anche su `videos/`,
    per il download video (MP4) di una canzone."""
    folder = folder or DL_DIR
    snap = {}
    try:
        names = os.listdir(folder)
    except OSError:
        return snap
    for f in names:
        if f.startswith("."):
            continue
        try:
            st = os.stat(os.path.join(folder, f))
        except OSError:
            continue
        snap[f] = (st.st_mtime, st.st_size)
    return snap

def _pick_job_file(before, after, expected_title="", exts=AUDIO_EXTS, folder=None):
    """Sceglie il file creato DA QUESTO job: presente in `after` ma non in
    `before` (o modificato nel frattempo), con una delle estensioni `exts` e
    dentro `folder` (default `downloads/`; per il video: `VIDEO_EXTS`, `videos/`).

    Se `expected_title` è noto il file deve anche contenerlo (testo normalizzato):
    meglio nessun file — e quindi un errore visibile in pagina — che un audio
    appartenente a un altro brano. Ritorna il nome file oppure None."""
    folder = folder or DL_DIR
    candidates = []
    for name, state in after.items():
        if not name.lower().endswith(tuple(exts)):
            continue
        if before.get(name) == state:
            continue                      # già presente e invariato: non è di questo job
        candidates.append((state[0], name))
    candidates.sort(reverse=True)         # il più recente per primo
    if expected_title:
        needle = normalize(expected_title)
        if needle:
            matching = [n for _, n in candidates if needle in normalize(n)]
            if not matching:
                return None               # il job NON ha prodotto il brano richiesto
            return matching[0]
    return candidates[0][1] if candidates else None

def _convert_download_format(job_id, filename, fmt):
    """Converte con ffmpeg il file scaricato nel formato richiesto (mp3/wav).

    Ritorna il nome file da consegnare al job: quello convertito quando la
    conversione riesce, altrimenti l'originale (comportamento invariato)."""
    if not filename:
        return filename
    ext = filename.rsplit(".", 1)[-1].lower()
    target_ext = "mp3" if fmt == "mp3" else "wav"
    if ext == target_ext or fmt not in ("mp3", "wav") or not FFMPEG:
        return filename
    base = os.path.splitext(filename)[0]
    out_name = f"{base}.{target_ext}"
    out_path = os.path.join(DL_DIR, out_name)
    src_path = os.path.join(DL_DIR, filename)
    codec_args = ["-acodec", "libmp3lame", "-q:a", "2"] if target_ext == "mp3" else ["-acodec", "pcm_s16le"]
    cmd = [FFMPEG, "-y", "-i", src_path, *codec_args, out_path]
    try:
        print(f"[download {job_id}] Conversione in {target_ext}...")
        result = subprocess.run(cmd, capture_output=True, timeout=120)
        if result.returncode == 0 and os.path.exists(out_path):
            print(f"[download {job_id}] Conversione OK: {out_name}")
            return out_name
        err = result.stderr.decode(errors="ignore")[-200:]
        print(f"[download {job_id}] Conversione fallita, uso formato nativo: {err}")
    except Exception as conv_err:
        print(f"[download {job_id}] Errore conversione, uso formato nativo: {conv_err}")
    return filename

def _converti_in_mp3(src_path, out_path, timeout=300):
    """ffmpeg: un file audio (o un VIDEO) → MP3. True se il file è stato creato.

    Serve alla conversione della playlist: dal 18/09/2026 la playlist può
    scaricare il video MP4 e da lì si ricava l'mp3 da ascoltare in libreria,
    senza riscaricare niente.
    """
    if not FFMPEG or not os.path.exists(src_path):
        return False
    try:
        cmd = [FFMPEG, "-y", "-i", src_path, "-vn", "-acodec", "libmp3lame",
               "-q:a", "2", out_path]
        r = subprocess.run(cmd, capture_output=True, timeout=timeout)
        return r.returncode == 0 and os.path.exists(out_path)
    except Exception as e:
        print(f"[mp3] conversione non riuscita ({os.path.basename(src_path)}): {e}")
        return False

def do_download(job_id, query, fmt, quality="192", expected_title="", expected_artist="",
                min_duration=0, solo_url=False):
    with DL_SEM:
        _do_download(job_id, query, fmt, quality, expected_title, expected_artist, min_duration,
                     solo_url)

def _do_download(job_id, query, fmt, quality="192", expected_title="", expected_artist="",
                 min_duration=0, solo_url=False):
    # `fmt == "mp4"` (o "video"): si scarica il VIDEO del brano — che va in
    # `videos/` e non in `downloads/` — invece dell'audio (18/09/2026).
    # `solo_url=True`: la query È il video preciso che serve (il link della riga o
    # il suo id YouTube) e **non si cerca niente**: se quel video non è scaricabile
    # il job lo dice, invece di prendere un ALTRO video (18/09/2026: il video di
    # «Public Enemy» è finito con «Public Enemy #1», trovato per artista+titolo).
    video = str(fmt or "").lower() in ("mp4", "video")
    cartella = VID_DIR if video else DL_DIR
    estensioni = VIDEO_EXTS if video else AUDIO_EXTS
    # Foto della cartella PRIMA di iniziare: alla fine si accettano solo i file
    # creati da questo job (vedi _pick_job_file), mai file di altri download.
    before = _downloads_snapshot(cartella)
    expected_title = (expected_title or "").strip()
    expected_artist = (expected_artist or "").strip()
    try:
        min_duration = float(min_duration or 0)
    except (TypeError, ValueError):
        min_duration = 0.0
    jobs[job_id]["status"] = "searching"
    jobs[job_id]["progress"] = {"percent": 0, "speed": "", "eta": ""}
    try:
        # Query "/stream/<file>": la pagina chiede un file che sta già in downloads/
        # (es. conversione m4a→mp3 dall'editor audio). Qui non c'è niente da
        # cercare su YouTube: prima questa query finiva in una ricerca senza senso
        # e poi nel fallback dei file recenti, restituendo un audio a caso.
        if query.startswith("/stream/"):
            local_name = os.path.basename(urllib.parse.unquote(query[len("/stream/"):]))
            if not local_name or not os.path.exists(os.path.join(DL_DIR, local_name)):
                jobs[job_id]["status"] = "error"
                jobs[job_id]["error"] = f"File locale non trovato: {local_name or query}"
                return
            print(f"[download {job_id}] File locale, nessuna ricerca YouTube: {local_name}")
            jobs[job_id]["yt_title"] = local_name
            filename = _convert_download_format(job_id, local_name, fmt)
            jobs[job_id]["status"] = "done"
            jobs[job_id]["filename"] = filename
            return

        if is_youtube_url(query):
            yt_url = query
            yt_title = ""
            print(f"[download {job_id}] URL YouTube diretto: {yt_url}")
        else:
            print(f"[download {job_id}] Ricerca YouTube per: {query}")
            yt_url, yt_title = yt_search_first(query)
            if not yt_url:
                jobs[job_id]["status"] = "error"
                jobs[job_id]["error"] = "Nessun risultato YouTube trovato"
                return

        jobs[job_id]["status"] = "downloading"
        jobs[job_id]["yt_title"] = yt_title

        def progress_hook(d):
            if d["status"] == "downloading":
                total = d.get("total_bytes") or d.get("total_bytes_estimate", 0)
                downloaded = d.get("downloaded_bytes", 0)
                pct = int(downloaded / total * 100) if total else 0
                jobs[job_id]["progress"] = {
                    "percent": pct,
                    "speed": d.get("_speed_str", ""),
                    "eta": d.get("_eta_str", ""),
                }

        ydl_opts = {
            # Audio (default) oppure VIDEO: per il video si chiede il meglio
            # disponibile e si fa unire audio+video in un MP4 (`merge_output_format`).
            "format": ("bestvideo[ext=mp4]+bestaudio[ext=m4a]/bestvideo+bestaudio/best"
                       if video else
                       "bestaudio[ext=m4a]/bestaudio[ext=webm]/bestaudio"),
            # Il solo titolo YouTube NON distingue i file: due video diversi (es.
            # le cover "8-Bit Misfits" e "Twinkle Twinkle Little Rock Star" di
            # 'Till I Collapse) possono chiamarsi uguale e finire nello STESSO
            # file, così la seconda card riproduceva l'audio della prima.
            # L'[id] del video rende il nome unico (vedi DL_OUTTMPL).
            "outtmpl": os.path.join(cartella, DL_OUTTMPL),
            "progress_hooks": [progress_hook],
            "socket_timeout": 20,
            "retries": 3,
            "fragment_retries": 3,
            "noplaylist": True,
            "quiet": True,
            # cookie esportati da Chrome una tantum in cookies.txt: evita il blocco 403 di YouTube senza prompt del portachiavi
            "cookiefile": os.path.join(BASE_DIR, "cookies.txt"),
            # NOTA (ago 2026): remote_components=["ejs:github"] RIMOSSA perché con yt-dlp
            # recenti provoca "Video unavailable"/403 su YouTube. Il solver JS integrato
            # (con deno) gestisce da solo le firme.
        }
        if video:
            # audio e video in UN SOLO file MP4 (senza questo yt-dlp lascerebbe
            # i due pezzi separati, es. '... [id].f137.mp4' + '... .f140.m4a').
            ydl_opts["merge_output_format"] = "mp4"

        print(f"[download {job_id}] Avvio download "
              f"{'video (MP4)' if video else 'formato nativo'}...")

        def _attempt_download(url):
            """Un giro di download (3 tentativi). Ritorna il nome del file creato
            da yt-dlp (percorso reale, non un file qualsiasi della cartella), o None.

            19/09/2026 — l'`info_dict` NON si butta più via. Il video racconta
            canale, tag, descrizione, viste e miniatura (`campi_youtube`) e quei
            dati restano scritti NEL JOB: `/status` li serve alla pagina, che li
            passa a `/db/add_local`, e da lì la riga nasce completa (vedi
            `arricchisci_riga_dal_video`). Prima si salvava solo `prepare_filename`
            e i metadati finivano nel cestino: 890 righe su 945 senza niente.
            """
            for attempt in range(1, 4):
                try:
                    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                        info = ydl.extract_info(url, download=True)
                        prepared = ydl.prepare_filename(info) if info else None
                        requested = (info or {}).get("requested_downloads") or []
                        if requested and requested[0].get("filepath"):
                            prepared = requested[0]["filepath"]
                        name = os.path.basename(prepared) if prepared else None
                        campi = campi_youtube(info)
                        if campi:
                            jobs[job_id]["yt_meta"] = campi
                            jobs[job_id]["yt_url"] = (info or {}).get("webpage_url") or url
                    if name and os.path.exists(os.path.join(cartella, name)):
                        return name
                except Exception as e:
                    print(f"[download {job_id}] Tentativo {attempt}/3 fallito: {e}")
                if attempt < 3:
                    jobs[job_id]["status"] = "retry"
                    time.sleep(3)
            return None

        filename = _attempt_download(yt_url)

        # RECUPERO 1 (16/09/2026): se il video indicato non è scaricabile (capita
        # spesso con "Please sign in" di YouTube sui brani con restrizioni) e la
        # pagina ci ha detto QUALE brano serve, si cerca un ALTRO video dello
        # stesso brano con il ranking titolo/artista, invece di restituire il
        # primo file trovato in cartella. Se la pagina sa anche a che SECONDO
        # serve il sample (min_duration) si preferisce un video abbastanza lungo
        # da contenerlo (altrimenti il timestamp cadrebbe oltre la fine
        # dell'audio: IN > OUT, durata negativa in pagina).
        if not filename and expected_title and not solo_url:
            alt_url, alt_title = yt_search_first(
                f"{expected_artist} {expected_title}".strip(),
                expected_title=expected_title, expected_artist=expected_artist,
                min_duration=min_duration)
            if alt_url and alt_url != yt_url:
                print(f"[download {job_id}] Video di partenza non scaricabile: provo {alt_url}")
                jobs[job_id]["status"] = "downloading"
                filename = _attempt_download(alt_url)
                if filename:
                    yt_title = alt_title or ""
                    # visibile in /status: si sa QUALE video alternativo è stato usato
                    jobs[job_id]["yt_title"] = alt_title or alt_url
                    jobs[job_id]["yt_url"] = alt_url

        # RECUPERO 2: si accettano SOLO file creati da questo job (confronto con
        # la foto iniziale della cartella) e, quando il titolo è noto, che lo
        # contengono. Il vecchio fallback prendeva "l'ultimo file degli ultimi 60
        # secondi": nei download in parallelo dei sample succedeva che il sample
        # "Sam Is Dead" riproducesse l'audio di "Mosh" (file di un altro job).
        if not filename:
            filename = _pick_job_file(before, _downloads_snapshot(cartella),
                                      expected_title or yt_title,
                                      exts=estensioni, folder=cartella)

        if not filename:
            jobs[job_id]["status"] = "error"
            jobs[job_id]["error"] = (
                (f"Il video del link non è scaricabile ({query}): nessun altro video è "
                 f"stato preso al posto suo")
                if solo_url else
                f"Download non riuscito: nessun file {'video' if video else 'audio'} per "
                f"'{expected_title or query}' ({'video' if video else 'audio'} NON sostituito)")
            print(f"[download {job_id}] ERRORE: questo job non ha prodotto file "
                  f"(nessun file di altri download riutilizzato)")
            return

        # Conversione esplicita con ffmpeg (se richiesto). Il video non si converte:
        # è già quello che serve (MP4).
        if not video:
            filename = _convert_download_format(job_id, filename, fmt)

        print(f"[download {job_id}] Successo: {filename}")
        jobs[job_id]["status"] = "done"
        jobs[job_id]["filename"] = filename

    except Exception as e:
        print(f"[download {job_id}] Errore: {e}")
        import traceback
        traceback.print_exc()
        jobs[job_id]["status"] = "error"
        jobs[job_id]["error"] = str(e)

# ── PLAYLIST DOWNLOAD ─────────────────────────────────────────────────────────
def register_local_file(filename, campi=None, video=None, local_file=None, playlist=None,
                        youtube_url=None):
    """Registra un file scaricato nella tabella songs (parsing artista - titolo).

    `campi` sono i metadati del video YouTube (vedi `campi_youtube`): la riga
    nasce già con la data di caricamento, l'anno, il canale, la descrizione…
    Senza (`None`) il comportamento è quello di sempre.

    `video` è il nome del file video in `videos/` da agganciare alla stessa riga
    (18/09/2026), e `local_file` è il file audio da scrivere in tabella: si passa
    `""` quando il file registrato è SOLO un video (l'audio non c'è — la riga
    esiste lo stesso, con la sua scheda e il suo video).

    `playlist` è il titolo della playlist di provenienza (colonna `yt_playlist`,
    scritta solo se la riga non ne ha già una).

    `youtube_url` è il LINK del video da cui è arrivato il file: si scrive in
    `youtube_url` solo se la riga non ce l'ha già, ed è da lì che il pulsante 🎬
    Video riprende il video (18/09/2026: prima la playlist non lo salvava e il
    video veniva cercato per artista+titolo, scaricando un video sbagliato).
    """
    raw = clean_filename(filename)
    # Rimuove il suffisso ' [idYouTube]' aggiunto da yt-dlp nel template
    base = re.sub(r"\s*\[[^\]]{5,}\]\s*$", "", raw)
    parts = base.split(" - ", 1)
    artist = parts[0].strip() if len(parts) == 2 else ""
    title = parts[1].strip() if len(parts) == 2 else base.strip()
    audio = filename if local_file is None else local_file
    with get_db() as conn:
        sid = get_or_create_song_db(conn, title, artist, youtube_url or "", local_file=audio,
                                    extra=campi, video_file=video, playlist=playlist)
    return sid

# ── DOWNLOAD AUTOMATICO DI UNA RIGA DEL DATABASE ─────────────────────────────
# Regola del 19/09/2026 (segnalazione: «Till I Collapse non è scaricata, non si
# sente e compare due volte»): **una canzone che entra nel database deve poter
# essere ascoltata**. Il download riusa il percorso di /download (yt-dlp, cookie,
# fallback) ma il file che ne esce si aggancia a QUESTA riga (`local_file`), non
# a una riga nuova: è esattamente da lì che nascevano i doppioni, perché
# `register_local_file` ricava artista e titolo dal NOME del file (che spesso non
# li contiene) e creava una riga in più.
_dl_canzone_lock = threading.Lock()
_dl_canzone = {}          # song_id -> job_id del download in corso per quella riga

_STATI_DOWNLOAD_ATTIVI = ("pending", "searching", "downloading", "retry", "converting")


def file_locale_valido(nome):
    """Il file locale esiste DAVVERO in downloads/ (non solo il nome in tabella)."""
    nome = os.path.basename(str(nome or "").strip())
    return bool(nome) and os.path.exists(os.path.join(DL_DIR, nome))


def avvia_download_canzone(song_id, forzato=False):
    """Scarica in `downloads/` il brano di una riga che non ha (più) un file.

    Ritorna `(job_id, motivo)`: `job_id` vuoto quando non c'era niente da fare
    (file già presente, riga inesistente, nessuna query possibile). Il job si
    segue con `/status/<job_id>` come tutti gli altri download.
    """
    with get_db() as conn:
        s = row2dict(conn.execute("SELECT * FROM songs WHERE id=?", (song_id,)).fetchone())
    if not s:
        return "", "canzone non trovata"
    if not forzato and file_locale_valido(s.get("local_file")):
        return "", "il file locale c'è già"
    query = (s.get("youtube_url") or "").strip()
    if not query:
        query = " ".join(x for x in [(s.get("artist") or "").strip(),
                                     (s.get("title") or "").strip()] if x)
    if not query:
        return "", "niente da cercare: la riga non ha né link YouTube né titolo"
    with _dl_canzone_lock:
        attivo = _dl_canzone.get(song_id)
        if attivo and jobs.get(attivo, {}).get("status") in _STATI_DOWNLOAD_ATTIVI:
            return attivo, "download già in corso"
        jid = str(uuid.uuid4())[:8]
        jobs[jid] = {"status": "pending", "progress": {}, "files": [], "filename": None,
                     "yt_title": "", "error": "", "song_id": song_id,
                     "expected_title": s.get("title") or ""}
        _dl_canzone[song_id] = jid

    def run():
        try:
            do_download(jid, query, "mp3", "192", s.get("title") or "",
                        s.get("artist") or "", 0)
            job = jobs.get(jid) or {}
            nome = job.get("filename")
            if nome:
                # Il file va su QUESTA riga: nessuna riga nuova, nessun doppione.
                with get_db() as conn:
                    conn.execute(
                        "UPDATE songs SET local_file=?, "
                        "youtube_url=CASE WHEN youtube_url IS NULL OR youtube_url='' THEN ? "
                        "                 ELSE youtube_url END, updated_at=datetime('now') "
                        "WHERE id=?",
                        (nome, query if is_youtube_url(query) else "", song_id))
                print(f"[db {song_id}] file locale agganciato alla riga: {nome}")
                # Il download porta anche il RESTO (19/09/2026): i dati del video
                # YouTube, la copertina dalla miniatura e il VIDEO MP4. Il link
                # vero del video scaricato si scrive sulla riga se non c'è: è da
                # lì (o dall'id) che il video si riprende, mai per ricerca.
                url_video = (job.get("yt_url") or "").strip()
                if url_video and is_youtube_url(url_video):
                    with get_db() as conn:
                        conn.execute("UPDATE songs SET youtube_url=?, "
                                     "updated_at=datetime('now') WHERE id=? "
                                     "AND (youtube_url IS NULL OR youtube_url='')",
                                     (url_video, song_id))
                esito = arricchisci_riga_dal_video(song_id, job.get("yt_meta"))
                print(f"[db {song_id}] arricchita dal video: {esito}")
            else:
                print(f"[db {song_id}] download non riuscito: "
                      f"{(jobs.get(jid) or {}).get('error', '')}")
        except Exception as e:
            print(f"[db {song_id}] download automatico: errore {e}")
        finally:
            with _dl_canzone_lock:
                _dl_canzone.pop(song_id, None)

    threading.Thread(target=run, daemon=True).start()
    return jid, ("download avviato (forzato)" if forzato else "download avviato")


# ── VIDEO DI UNA RIGA DEL DATABASE (18/09/2026) ──────────────────────────────
# Come `avvia_download_canzone`, ma per il VIDEO (MP4): il file va in `videos/`
# e si aggancia a QUESTA riga (`video_file`), mai a una riga nuova. Il video si
# può anche caricare dal computer o scegliere fra quelli già in `videos/`
# (POST /db/songs/<id>/video) e togliere (DELETE, il file va in `.trash/`).
_dl_video_lock = threading.Lock()
_dl_video = {}            # song_id -> job_id del download video in corso

def file_video_valido(nome):
    """Il file video esiste DAVVERO in `videos/` (non solo il nome in tabella)."""
    nome = os.path.basename(str(nome or "").strip())
    return bool(nome) and os.path.exists(os.path.join(VID_DIR, nome))

def nome_video_unico(nome):
    """Un nome file VIDEO libero dentro `videos/` (non sovrascrive mai niente).

    Funzione pura rispetto al database: guarda solo la cartella. Se il nome è
    già usato si aggiunge un numero («Brano [id] (1).mp4»).
    """
    base = os.path.basename(str(nome or "").strip()) or "video.mp4"
    nome_base, ext = os.path.splitext(base)
    ext = ext.lower() if ext.lower() in VIDEO_EXTS else ".mp4"
    candidato = f"{nome_base}{ext}"
    i = 1
    while os.path.exists(os.path.join(VID_DIR, candidato)):
        candidato = f"{nome_base} ({i}){ext}"
        i += 1
    return candidato

def nome_video_sicuro(nome):
    """Il nome con cui salvare un video caricato dal computer (funzione PURA).

    Niente percorsi (`../` fuori da `videos/`), niente caratteri che Windows o
    macOS leggono male, e l'estensione deve essere una di quelle video: se manca
    (o è un'altra) si salva come `.mp4`. Spazi, punti, trattini, parentesi e
    quadre si tengono: sono normali nei nomi che si vedono in libreria
    («Artista - Titolo (Live) [id].mp4»).
    """
    base = os.path.basename(str(nome or "")).strip()
    base = re.sub(r"[^\w\-. \[\]()',&]+", "_", base, flags=re.UNICODE).strip(" .")
    if not base:
        base = "video.mp4"
    if os.path.splitext(base)[1].lower() not in VIDEO_EXTS:
        base += ".mp4"
    return base

def avvia_download_video_canzone(song_id, forzato=False):
    """Scarica in `videos/` il VIDEO (MP4) **del video che è stato scaricato**: quello
    del LINK YouTube della riga (o, se il link non c'è, dell'id del video salvato coi
    metadati della playlist); solo se non c'è né link né id si cerca per artista +
    titolo. Il file va in `videos/` e si scrive in `video_file`.

    ⚠️ Con un link/ID **non si cerca niente**: se quel video non è scaricabile il job
    lo dice, invece di prendere un altro video (18/09/2026: il video di «Public
    Enemy» è finito con «Public Enemy #1», trovato per artista+titolo).

    Ritorna `(job_id, motivo)`; `("", motivo)` quando non parte.
    """
    with get_db() as conn:
        s = row2dict(conn.execute("SELECT * FROM songs WHERE id=?", (song_id,)).fetchone())
    if not s:
        return "", "riga non trovata"
    if not forzato and file_video_valido(s.get("video_file")):
        return "", "il video c'è già"
    # 1) il link della riga (il video da cui è arrivato l'audio)
    query = (s.get("youtube_url") or "").strip()
    da_link = bool(query) and is_youtube_url(query)
    # 2) l'id del video, se la riga è arrivata da una playlist
    if not da_link:
        vid = (s.get("yt_video_id") or "").strip()
        if vid:
            query = f"https://www.youtube.com/watch?v={vid}"
            da_link = True
    # 3) solo se non c'è né link né id: ricerca per artista + titolo
    if not da_link:
        query = " ".join(x for x in [(s.get("artist") or "").strip(),
                                     (s.get("title") or "").strip()] if x)
    if not query:
        return "", "niente da cercare: la riga non ha né link YouTube né titolo"
    with _dl_video_lock:
        attivo = _dl_video.get(song_id)
        if attivo and jobs.get(attivo, {}).get("status") in _STATI_DOWNLOAD_ATTIVI:
            return attivo, "download video già in corso"
        jid = str(uuid.uuid4())[:8]
        jobs[jid] = {"status": "pending", "progress": {}, "files": [], "filename": None,
                     "yt_title": "", "error": "", "song_id": song_id, "video": True,
                     "expected_title": s.get("title") or "",
                     # si vede in /status da DOVE si sta prendendo il video
                     "da_link": da_link, "fonte": query}
        _dl_video[song_id] = jid

    def run():
        try:
            do_download(jid, query, "mp4", "192", s.get("title") or "",
                        s.get("artist") or "", 0, solo_url=da_link)
            nome = (jobs.get(jid) or {}).get("filename")
            if nome:
                # Il video va su QUESTA riga: nessuna riga nuova, nessun doppione.
                with get_db() as conn:
                    conn.execute(
                        "UPDATE songs SET video_file=?, "
                        "youtube_url=CASE WHEN youtube_url IS NULL OR youtube_url='' THEN ? "
                        "                 ELSE youtube_url END, updated_at=datetime('now') "
                        "WHERE id=?",
                        (nome, query if da_link else "", song_id))
                print(f"[db {song_id}] video agganciato alla riga: {nome}")
            else:
                print(f"[db {song_id}] download video non riuscito: "
                      f"{(jobs.get(jid) or {}).get('error', '')}")
        except Exception as e:
            print(f"[db {song_id}] download video: errore {e}")
        finally:
            with _dl_video_lock:
                _dl_video.pop(song_id, None)

    threading.Thread(target=run, daemon=True).start()
    return jid, ("download video avviato (forzato)" if forzato
                 else "download video avviato")


def _sposta_video_in_archivio(nome, origine=None):
    """Sposta un file video in `videos/` (da `downloads/`) e torna il nome finale.

    Serve alla playlist che scarica anche il video: yt-dlp scrive tutto in
    `downloads/`, ma il video ha la sua cartella. Il nome non si sovrascrive mai
    (se c'è già, si aggiunge un numero) — mentre un file **identico** già
    archiviato (stessa dimensione) non viene duplicato: la copia appena scaricata
    si butta. Ritorna '' se lo spostamento non riesce.
    """
    origine = origine or DL_DIR
    src = os.path.join(origine, nome)
    if not os.path.isfile(src):
        return ""
    base, ext = os.path.splitext(os.path.basename(nome))
    dest_name = base + ext
    dest = os.path.join(VID_DIR, dest_name)
    i = 1
    while os.path.exists(dest):
        if os.path.getsize(dest) == os.path.getsize(src):
            try:
                os.remove(src)
            except OSError:
                pass
            return dest_name
        dest_name = f"{base} ({i}){ext}"
        dest = os.path.join(VID_DIR, dest_name)
        i += 1
    try:
        os.rename(src, dest)
    except OSError as e:
        print(f"[video] spostamento non riuscito ({nome}): {e}")
        return ""
    return dest_name


# ── DAL VIDEO AL RESTO DELLA RIGA (19/09/2026) ────────────────────────────────
# Un download porta con sé MOLTO più del file audio: il video racconta il canale,
# i tag, la descrizione, le viste, la data di caricamento e ha la sua miniatura
# (`campi_youtube`). Fino a ieri quei dati arrivavano alla riga **solo** passando
# da una playlist, e la miniatura restava un URL: su 945 canzoni, 890 non avevano
# nemmeno un campo `yt_*`, la copertina c'era su 17 e il VIDEO su 57.
# Da oggi la riga appena nata da un download si completa DA SOLA, e il lavoro sta
# in UN posto solo: lo usano il download di una riga (`avvia_download_canzone`),
# il download dal modale «➕ Aggiungi» (`/db/add_local`) e la playlist.
def aggancia_metadati_youtube(song_id, campi):
    """Scrive sulla riga i campi `yt_*` del video (solo quelli con un valore).

    Stessa regola di `resolve_or_create_song`: si accettano SOLO le colonne di
    `CAMPI_YOUTUBE` (un nome fuori lista si ignora) e un campo vuoto non spegne
    quello che c'era. Ritorna True se c'era qualcosa da scrivere.
    """
    campi = {k: v for k, v in (campi or {}).items()
             if k in CAMPI_YOUTUBE_NOMI and v is not None and str(v).strip() != ""}
    if not campi:
        return False
    with get_db() as conn:
        conn.execute("UPDATE songs SET " + ", ".join(f"{k}=?" for k in campi) +
                     ", updated_at=datetime('now') WHERE id=?",
                     (*campi.values(), song_id))
    return True


def copertina_da_miniatura(song_id, url=None, forzato=False):
    """Mette in `covers/<id>.<ext>` la MINIATURA del video YouTube. Ritorna
    `(nome_file|"", motivo)`.

    La miniatura è l'unica immagine che abbiamo di certo per un brano appena
    scaricato (`yt_thumbnail`, da `campi_youtube`). Se la riga ha già una
    copertina **non si tocca** (a meno di `forzato=True`): una copertina scelta a
    mano vale più di una miniatura. L'URL si prende da `url` o, se non c'è, dalla
    colonna `yt_thumbnail` della riga.

    Il file va in `covers/<id>.<ext>` E il nome si scrive nella riga
    (`cover_art_path`): `salva_copertina_bytes` da sola scrive solo il file, e
    senza la colonna la copertina non si vedrebbe in pagina.
    """
    with get_db() as conn:
        riga = row2dict(conn.execute(
            "SELECT cover_art_path, yt_thumbnail FROM songs WHERE id=?",
            (song_id,)).fetchone())
    if not riga:
        return "", "riga non trovata"
    if not forzato and not _cover_mancante(riga.get("cover_art_path")):
        return "", "la copertina c'era già"
    url = url or (riga.get("yt_thumbnail") or "").strip()
    if not url:
        return "", "nessuna miniatura da usare"
    try:
        dati = _scarica_immagine(url)
    except Exception as e:
        return "", f"miniatura non scaricabile ({str(e)[:60]})"
    if not dati:
        return "", "miniatura non scaricabile"
    nome, errore = salva_copertina_bytes(song_id, dati, _cover_ext_from_url(url))
    if errore:
        return "", errore
    with get_db() as conn:
        conn.execute("UPDATE songs SET cover_art_path=?, updated_at=datetime('now') "
                     "WHERE id=?", (nome, song_id))
    return nome, f"🖼 Copertina dalla miniatura del video: {nome}"


def arricchisci_riga_dal_video(song_id, campi=None, video=True):
    """La riga nata da un download si completa DA SOLA dal video.

    Tre passi, tutti già pronti altrove: i campi `yt_*`
    (`aggancia_metadati_youtube`), la copertina dalla miniatura
    (`copertina_da_miniatura`) e il VIDEO MP4 (`avvia_download_video_canzone`,
    che parte dal link o dall'id della riga appena scritto — mai una ricerca a
    caso). Niente viene calpestato: i campi vuoti non spengono quelli che c'erano,
    la copertina esistente resta, un video già agganciato non si riscarica.

    Ritorna il resoconto di cosa è stato fatto (la pagina lo mostra):
    `{"metadati":…, "cover":…, "video_job":…, "video_motivo":…}`.
    """
    res = {"metadati": "", "cover": "", "video_job": "", "video_motivo": ""}
    if aggancia_metadati_youtube(song_id, campi):
        res["metadati"] = "dati del video YouTube scritti nella riga"
    nome, motivo = copertina_da_miniatura(song_id, (campi or {}).get("yt_thumbnail"))
    res["cover"] = nome or motivo
    if video:
        res["video_job"], res["video_motivo"] = avvia_download_video_canzone(song_id)
    return res


# ── MINIATURA E DATI DEL VIDEO PER LE RIGHE GIÀ IN LIBRERIA (19/09/2026) ──────
# `arricchisci_riga_dal_video` completa la riga APPENA nata da un download. Le
# righe che erano già in libreria sono rimaste spoglie: su 945 canzoni 921 non
# hanno la miniatura in `covers/` e 897 non hanno nemmeno un campo `yt_*`. Alcune
# (per esempio le playlist del 18/09) hanno invece l'URL della miniatura e i dati,
# ma il FILE non è mai stato scaricato — e in pagina non si vedeva niente, perché
# tutte le pagine (index, browse, scheda) leggono solo `cover_art_path`.
# Qui si recupera SU RICHIESTA: una riga per volta (pulsante 🖼 YT della riga) o
# in blocco **solo** per le righe che hanno già un link/id YouTube — niente
# ricerca a caso sui 788 brani senza link, che riporterebbe il caso «Public
# Enemy #1» (un video trovato per artista+titolo al posto di quello vero).
def fonte_video_riga(riga):
    """Da dove si prende il video di una riga: `(query, da_link)` (funzione PURA).

    Stessa regola di `avvia_download_video_canzone`, in quest'ordine:
    1) il LINK YouTube della riga (`youtube_url`); 2) l'id salvato col download
    (`yt_video_id`); 3) solo se non c'è né l'uno né l'altro, «artista - titolo»
    con `da_link=False` — cioè una RICERCA, che può pescare un altro video.
    """
    riga = riga or {}
    link = str(riga.get("youtube_url") or "").strip()
    if link and is_youtube_url(link):
        return link, True
    vid = str(riga.get("yt_video_id") or "").strip()
    if vid:
        return f"https://www.youtube.com/watch?v={vid}", True
    query = " ".join(x for x in [str(riga.get("artist") or "").strip(),
                                 str(riga.get("title") or "").strip()] if x)
    return query, False


def info_video_riga(riga, timeout=60):
    """I dati che il video della riga racconta di sé, SENZA scaricare niente.

    yt-dlp con `skip_download` legge solo l'`info_dict` (canale, tag, descrizione,
    viste, data, miniatura) e non crea nessun file in `downloads/`. Con un
    link/ID **non si cerca niente**: se quel video non è leggibile lo si dice,
    invece di prendere un altro video. Senza link né ID si passa da
    `yt_search_first` (quello col punteggio su titolo e artista).

    Ritorna `(info|None, url_usata, cercato, motivo)`: `cercato=True` quando il
    video è stato TROVATO con una ricerca, e la pagina lo deve dire.
    """
    riga = riga or {}
    query, da_link = fonte_video_riga(riga)
    if not query:
        return None, "", False, "la riga non ha né link YouTube né titolo"
    url = query
    if not da_link:
        trovato, _titolo = yt_search_first(query, riga.get("title") or "",
                                           riga.get("artist") or "")
        if not trovato:
            return None, "", True, f"nessun video trovato cercando «{query}»"
        url = trovato
    ydl_opts = {
        "quiet": True, "no_warnings": True, "skip_download": True,
        "noplaylist": True, "socket_timeout": 20,
        # cookie esportati da Chrome: senza, YouTube risponde 403 (come nel download)
        "cookiefile": os.path.join(BASE_DIR, "cookies.txt"),
    }
    info_box, exc_box = [None], [None]

    def _leggi():
        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info_box[0] = ydl.extract_info(url, download=False)
        except Exception as e:
            exc_box[0] = e

    t = threading.Thread(target=_leggi, daemon=True)
    t.start()
    t.join(max(5, int(timeout or 60)))
    if t.is_alive():
        return None, url, not da_link, f"YouTube non ha risposto in {timeout}s"
    if exc_box[0]:
        return None, url, not da_link, f"video non leggibile ({str(exc_box[0])[:80]})"
    info = info_box[0] or {}
    if isinstance(info.get("entries"), list) and info["entries"]:
        info = info["entries"][0] or {}
    if not isinstance(info, dict) or not info:
        return None, url, not da_link, "il video non racconta niente"
    return info, url, not da_link, ""


def recupera_dati_video(song_id, forzato=False, video=False, timeout=60):
    """Riempie una riga già in libreria coi dati del video e la MINIATURA.

    Tre passi, gli stessi di `arricchisci_riga_dal_video` (che li fa per la riga
    appena scaricata): i campi `yt_*` (`aggancia_metadati_youtube`), la miniatura
    in `covers/` col suo nome in `cover_art_path` (`copertina_da_miniatura`) e —
    solo con `video=True` — l'MP4 (`avvia_download_video_canzone`). Niente si
    calpesta: un campo vuoto non spegne quello che c'era, una copertina già
    presente resta (a meno di `forzato=True`), un video agganciato non si riscarica.

    Quando il video è stato TROVATO con una ricerca, il link resta scritto nella
    riga (solo se `youtube_url` era vuoto): senza, il 🎬 Video lo cercherebbe una
    seconda volta, magari su un video diverso.

    Ritorna `{"ok":…, "fonte":…, "cercato":…, "cover":…, "messaggi":[…], …}`.
    """
    with get_db() as conn:
        s = row2dict(conn.execute("SELECT * FROM songs WHERE id=?", (song_id,)).fetchone())
    if not s:
        return {"ok": False, "error": "riga non trovata"}
    info, url, cercato, motivo = info_video_riga(s, timeout=timeout)
    if info is None:
        return {"ok": False, "error": motivo, "fonte": url, "cercato": cercato}
    campi = campi_youtube(info)
    messaggi = []
    if aggancia_metadati_youtube(song_id, campi):
        messaggi.append("📺 dati del video YouTube scritti nella riga")
    if cercato and url:
        with get_db() as conn:
            conn.execute(
                "UPDATE songs SET youtube_url=CASE WHEN youtube_url IS NULL OR youtube_url='' "
                "THEN ? ELSE youtube_url END, updated_at=datetime('now') WHERE id=?",
                (url, song_id))
        messaggi.append(f"⚠️ video trovato CERCANDO «{s.get('artist') or ''} - "
                        f"{s.get('title') or ''}»: {url} — se non è quello giusto, "
                        "correggi il link con ✏️ Edit → URL YouTube")
    nome, motivo_cover = copertina_da_miniatura(song_id, campi.get("yt_thumbnail"),
                                                forzato=forzato)
    if nome:
        messaggi.append(f"🖼 miniatura salvata in covers/: {nome}")
    elif motivo_cover:
        messaggi.append(f"🖼 copertina: {motivo_cover}")
    res = {"ok": True, "fonte": url, "cercato": cercato, "metadati": bool(campi),
           "cover": nome or "", "cover_motivo": motivo_cover,
           "messaggi": messaggi, "video_job": "", "video_motivo": ""}
    if video:
        res["video_job"], res["video_motivo"] = avvia_download_video_canzone(
            song_id, forzato=forzato)
    with get_db() as conn:
        res["song"] = row2dict(conn.execute("SELECT * FROM songs WHERE id=?",
                                            (song_id,)).fetchone())
    print(f"[db {song_id}] recupero dal video: " +
          ("; ".join(messaggi) if messaggi else "niente da aggiungere"))
    return res


def righe_da_recuperare(solo_con_link=True):
    """I candidati al recupero: `(righe, senza_link)`.

    Una riga è candidata se ha una FONTE per il video (link o id) e le manca
    qualcosa: la miniatura (`cover_art_path` vuoto o file non più in `covers/`,
    vedi `_cover_mancante`) o i dati del video (`yt_meta_at` vuoto). Ogni riga
    porta `manca` con l'elenco (serve al pannello della pagina per dirlo).

    Con `solo_con_link=True` (il blocco) restano fuori le righe senza link/id:
    per quelle servirebbe una ricerca YouTube per «artista - titolo», che può
    pescare un video sbagliato — si fanno una per volta, col pulsante 🖼 YT.
    Il secondo valore conta proprio quelle righe lì (la pagina le mostra).
    """
    with get_db() as conn:
        righe = rows2list(conn.execute(
            "SELECT id, artist, title, youtube_url, yt_video_id, cover_art_path, "
            "yt_meta_at, yt_title FROM songs ORDER BY created_at").fetchall())
    fuori, senza_link = [], 0
    for r in righe:
        query, da_link = fonte_video_riga(r)
        if not query:
            continue
        if not da_link:
            senza_link += 1
            if solo_con_link:
                continue
        manca = []
        if _cover_mancante(r.get("cover_art_path")):
            manca.append("copertina")
        # La lettura è completa solo se c'è `yt_meta_at` E il titolo del video
        # (`yt_title`, aggiunto il 19/09/2026): le righe recuperate prima non ce
        # l'hanno, e rifacendo il giro il blocco lo riempie (niente si calpesta).
        if not str(r.get("yt_meta_at") or "").strip() or not str(r.get("yt_title") or "").strip():
            manca.append("dati del video")
        if manca:
            r["manca"] = manca
            fuori.append(r)
    return fuori, senza_link


_ry_lock = threading.Lock()
_ry_bulk = {"job": ""}

def avvia_recupero_youtube(limite=0, forzato=False, pausa=1.5):
    """Avvia il recupero in blocco (solo righe con link/id). Ritorna `(job_id, motivo)`.

    Un job come gli altri (`/status/<job_id>` lo racconta passo passo): `progress`
    ha `fatti`/`totale`/`brano`, `risultati` l'esito riga per riga e `riepilogo`
    il conto finale. Fra una riga e l'altra si aspetta un momento (`pausa`): sono
    chiamate a YouTube, e cento di fila senza respiro si fanno bloccare (403).
    """
    with _ry_lock:
        attivo = _ry_bulk.get("job") or ""
        if attivo and jobs.get(attivo, {}).get("status") in _STATI_DOWNLOAD_ATTIVI + ("working",):
            return attivo, "recupero già in corso"
        righe, senza_link = righe_da_recuperare(solo_con_link=True)
        if limite:
            righe = righe[:int(limite)]
        if not righe:
            return "", ("niente da recuperare: le righe con un link YouTube hanno già "
                        "miniatura e dati del video")
        jid = str(uuid.uuid4())[:8]
        jobs[jid] = {"status": "pending",
                     "progress": {"percent": 0, "fatti": 0, "totale": len(righe), "brano": ""},
                     "files": [], "filename": "", "yt_title": "", "error": "",
                     "bulk": True, "senza_link": senza_link, "risultati": []}
        _ry_bulk["job"] = jid

    def run():
        risultati = jobs[jid]["risultati"]
        totale = len(righe)
        for n, r in enumerate(righe, start=1):
            brano = " - ".join(x for x in [str(r.get("artist") or "").strip(),
                                           str(r.get("title") or "").strip()] if x) or str(r.get("id"))
            jobs[jid]["status"] = "working"
            jobs[jid]["progress"] = {"percent": int((n - 1) / totale * 100), "fatti": n - 1,
                                     "totale": totale, "brano": brano}
            try:
                esito = recupera_dati_video(r["id"], forzato=forzato)
            except Exception as e:
                esito = {"ok": False, "error": str(e)[:120]}
            risultati.append({"id": r["id"], "brano": brano, "ok": bool(esito.get("ok")),
                              "cover": esito.get("cover") or "",
                              "motivo": esito.get("error") or (esito.get("cover_motivo") or "")})
            jobs[jid]["progress"] = {"percent": int(n / totale * 100), "fatti": n,
                                     "totale": totale, "brano": brano}
            if pausa and n < totale:
                time.sleep(float(pausa))
        con_cover = sum(1 for x in risultati if x.get("cover"))
        riuscite = sum(1 for x in risultati if x.get("ok"))
        jobs[jid]["status"] = "done"
        jobs[jid]["filename"] = ""
        jobs[jid]["riepilogo"] = (f"{con_cover} miniature salvate su {totale} righe "
                                  f"({riuscite} recuperi riusciti)")
        print(f"[recupero youtube {jid}] {jobs[jid]['riepilogo']}")
        with _ry_lock:
            _ry_bulk["job"] = ""

    threading.Thread(target=run, daemon=True).start()
    return jid, f"recupero avviato su {len(righe)} righe con link/ID"


def do_download_playlist(job_id, url, fmt="mp3", video=False):
    """Scarica TUTTA la playlist. Con `video=True` (18/09/2026) scarica l'MP4 del
    video, lo archivia in `videos/` e ne ricava l'mp3 da ascoltare in libreria:
    la riga porta sia `local_file` (l'audio) sia `video_file` (il video)."""
    jobs[job_id]["status"] = "fetching"
    jobs[job_id]["progress"] = {"percent": 0, "speed": "", "eta": ""}
    valid_exts = (".mp3", ".wav", ".m4a", ".webm", ".mp4", ".mkv", ".ogg",
                  ".opus", ".flac")

    def snapshot():
        snap = {}
        for f in os.listdir(DL_DIR):
            if f.startswith("."):
                continue
            fp = os.path.join(DL_DIR, f)
            try:
                snap[f] = (os.path.getmtime(fp), os.path.getsize(fp))
            except OSError:
                pass
        return snap

    try:
        before = snapshot()

        def progress_hook(d):
            if d["status"] == "downloading":
                total = d.get("total_bytes") or d.get("total_bytes_estimate", 0)
                downloaded = d.get("downloaded_bytes", 0)
                pct = int(downloaded / total * 100) if total else 0
                jobs[job_id]["progress"] = {
                    "percent": pct,
                    "filename": os.path.basename(d.get("filename", "")),
                    "speed": d.get("_speed_str", ""),
                    "eta": d.get("_eta_str", ""),
                }

        ydl_opts = {
            # Con `video=True` si scarica il VIDEO (audio+video uniti in un MP4):
            # da lì si ricava l'mp3, così la playlist porta «oltre all'mp3 anche
            # l'mp4» con UN solo download per brano.
            "format": ("bestvideo[ext=mp4]+bestaudio[ext=m4a]/bestvideo+bestaudio/best"
                       if video else
                       "bestaudio[ext=m4a]/bestaudio[ext=webm]/bestaudio"),
            "outtmpl": os.path.join(DL_DIR, DL_OUTTMPL),
            "progress_hooks": [progress_hook],
            "ignoreerrors": True,
            "cookiefile": os.path.join(BASE_DIR, "cookies.txt"),
        }
        if video:
            ydl_opts["merge_output_format"] = "mp4"
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)

        after = snapshot()
        # Metadati del video per OGNI voce scaricata (18/09/2026): l'`[id]` nel
        # nome del file dice quale voce è quale (vedi `id_video_dal_nome_file`).
        # Le voci che YouTube non ha lasciato scaricare sono `None`: si saltano.
        per_id = mappa_metadati_playlist((info or {}).get("entries") or [])
        new_files = sorted(
            f for f, v in after.items()
            if f not in before or (before[f][0], before[f][1]) != v
        )
        new_files = [f for f in new_files if f.lower().endswith(valid_exts)]

        if not new_files:
            jobs[job_id]["status"] = "error"
            jobs[job_id]["error"] = "Nessun file scaricato dalla playlist (controlla l'URL)"
            return

        # I VIDEO della playlist si tengono da parte: si archiviano in `videos/`
        # (non sono file audio) e da lì si ricava l'mp3. Solo con l'opzione 🎬:
        # senza, un `.mp4` scaricato è un file audio come gli altri e si converte.
        video_files = ([f for f in new_files if f.lower().endswith(tuple(VIDEO_EXTS))]
                       if video else [])

        # Conversione esplicita in MP3 se richiesto
        if fmt == "mp3" and FFMPEG:
            converted = []
            for f in new_files:
                if f in video_files:
                    continue
                ext = f.rsplit(".", 1)[-1].lower()
                if ext == "mp3":
                    converted.append(f)
                    continue
                out_name = f"{os.path.splitext(f)[0]}.mp3"
                if _converti_in_mp3(os.path.join(DL_DIR, f), os.path.join(DL_DIR, out_name)):
                    converted.append(out_name)
                else:
                    converted.append(f)
            new_files = converted
        # Un video scaricato non è un file audio: fuori dalla lista delle righe.
        new_files = [f for f in new_files if f not in video_files]

        # Il video va in `videos/` e si aggancia alla riga della sua canzone
        # (stesso `[id]` nel nome). L'mp3 da ascoltare si ricava dal video, se per
        # quel brano non c'è già un file audio.
        video_per_id = {}
        for f in video_files:
            src = os.path.join(DL_DIR, f)
            vid = id_video_dal_nome_file(f)
            if vid and not any(id_video_dal_nome_file(x) == vid for x in new_files):
                out_name = f"{os.path.splitext(f)[0]}.mp3"
                if _converti_in_mp3(src, os.path.join(DL_DIR, out_name)):
                    new_files.append(out_name)
                    print(f"[playlist {job_id}] mp3 ricavato dal video: {out_name}")
            nome_video = _sposta_video_in_archivio(f)
            if nome_video:
                video_per_id[id_video_dal_nome_file(nome_video)] = nome_video
                print(f"[playlist {job_id}] video archiviato: {nome_video}")

        # Registra ogni brano nel database. Con i metadati del video, quando ci
        # sono: la riga nasce già con data di caricamento, anno, canale,
        # descrizione, viste, tag, categoria, miniatura e durata (campi `yt_*`).
        #
        # Prima si guarda com'era la libreria (id → file locale): serve a dire la
        # VERITÀ nel messaggio finale. Il 18/09/2026 Alessandro ha visto «7 brani
        # scaricati, 7 registrati nel database» e non li trovava: due di quelle
        # canzoni erano già in libreria CON un loro file, quindi il file appena
        # scaricato non è stato agganciato a niente (resta in `downloads/`) e la
        # riga non diceva da quale playlist veniva.
        nome_playlist = (info or {}).get("title", "") if info else ""

        def url_video(vid):
            """Il LINK YouTube del video (per la colonna `youtube_url` della riga)."""
            return f"https://www.youtube.com/watch?v={vid}" if vid else ""

        with get_db() as conn:
            prima = {r["id"]: (r["local_file"] or "")
                     for r in conn.execute("SELECT id, local_file FROM songs")}
        registered = 0
        con_metadati = 0
        con_anno = 0
        nuovi = 0
        gia_in_libreria = 0
        file_non_agganciati = []
        id_con_audio = set()
        for f in new_files:
            vid = id_video_dal_nome_file(f)
            campi = per_id.get(vid) or {}
            if campi:
                con_metadati += 1
            sid = register_local_file(f, campi, video=video_per_id.get(vid),
                                      playlist=nome_playlist, youtube_url=url_video(vid))
            if sid:
                registered += 1
                id_con_audio.add(vid)
                # La copertina si prende dalla MINIATURA del video (19/09/2026): la
                # riga aveva l'URL (`yt_thumbnail`) ma in `covers/` non c'era
                # niente, così in pagina la canzone restava senza immagine. Una
                # copertina già scelta a mano non si tocca.
                copertina_da_miniatura(sid, campi.get("yt_thumbnail"))
                if campi.get("year"):
                    con_anno += 1
                if sid in prima:
                    gia_in_libreria += 1
                    if prima[sid] and prima[sid] != f:
                        # La riga ha GIÀ un file DIVERSO: il nuovo non si aggancia (un
                        # file scelto a mano non si sovrascrive) — ma va detto, col
                        # nome del file, altrimenti sembra che sia andato perso. Se il
                        # nome è lo STESSO (playlist riscaricata, stesso video) il file
                        # è già quello della riga: non c'è niente da segnalare.
                        file_non_agganciati.append({"song_id": sid, "titolo": "",
                                                    "file": f, "file_in_tabella": prima[sid]})
                else:
                    nuovi += 1
        for voce in file_non_agganciati:
            with get_db() as conn:
                r = conn.execute("SELECT title, artist FROM songs WHERE id=?",
                                 (voce["song_id"],)).fetchone()
            if r:
                voce["titolo"] = " - ".join(x for x in [r["artist"] or "", r["title"] or ""] if x)
        # I video che sono rimasti senza file audio (la conversione in mp3 non è
        # riuscita): la riga nasce lo stesso, col video e la sua scheda — senza
        # `local_file`, perché l'audio non c'è.
        for vid, nome_video in video_per_id.items():
            if vid in id_con_audio:
                continue
            register_local_file(nome_video, per_id.get(vid) or {}, video=nome_video,
                                local_file="", playlist=nome_playlist, youtube_url=url_video(vid))
            print(f"[playlist {job_id}] riga registrata col solo video: {nome_video}")

        jobs[job_id]["status"] = "done"
        jobs[job_id]["files"] = new_files
        jobs[job_id]["count"] = len(new_files)
        jobs[job_id]["registered"] = registered
        jobs[job_id]["nuovi"] = nuovi
        jobs[job_id]["gia_in_libreria"] = gia_in_libreria
        jobs[job_id]["file_non_agganciati"] = file_non_agganciati
        jobs[job_id]["con_metadati"] = con_metadati
        jobs[job_id]["con_anno"] = con_anno
        jobs[job_id]["con_video"] = len(video_per_id)
        jobs[job_id]["playlist_title"] = nome_playlist

    except Exception as e:
        print(f"[playlist {job_id}] Errore: {e}")
        import traceback
        traceback.print_exc()
        jobs[job_id]["status"] = "error"
        jobs[job_id]["error"] = str(e)

# ── STEMS ─────────────────────────────────────────────────────────────────────
def do_stems(job_id, filename, song_id=None):
    jobs[job_id]["status"]="separating"
    jobs[job_id]["progress"]={"percent":0}
    filepath=os.path.join(DL_DIR,filename)
    session_id="sess_"+uuid.uuid4().hex[:10]
    try:
        with get_db() as conn:
            conn.execute("INSERT INTO stem_sessions(id,song_id,job_id,model_name,output_folder,status) VALUES(?,?,?,'htdemucs',?,'running')",
                         (session_id,song_id,job_id,os.path.join(STEMS_DIR,"htdemucs")))

        cmd=["python3","-m","demucs","--mp3","--mp3-bitrate","320","-n","htdemucs","-o",STEMS_DIR,filepath]
        proc=subprocess.Popen(cmd,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True)
        for line in proc.stdout:
            if "%" in line:
                try:
                    pct=int(line.split("%")[0].split()[-1])
                    jobs[job_id]["progress"]["percent"]=pct
                    with get_db() as conn:
                        conn.execute("UPDATE stem_sessions SET progress_percent=? WHERE id=?",(pct,session_id))
                except: pass
        proc.wait()
        if proc.returncode==0:
            name=os.path.splitext(filename)[0]
            stem_folder=os.path.join(STEMS_DIR,"htdemucs",name)
            stems=os.listdir(stem_folder) if os.path.exists(stem_folder) else []
            stem_map={"vocals":"vocals","drums":"drums","bass":"bass","other":"other"}
            with get_db() as conn:
                conn.execute("UPDATE stem_sessions SET status='done',completed_at=datetime('now') WHERE id=?",(session_id,))
                for sf in stems:
                    stype=stem_map.get(os.path.splitext(sf)[0].lower(),"other")
                    fp=os.path.join(stem_folder,sf)
                    tid="stm_"+uuid.uuid4().hex[:10]
                    conn.execute("INSERT INTO stem_tracks(id,session_id,stem_type,file_path,file_size_bytes) VALUES(?,?,?,?,?)",
                                 (tid,session_id,stype,fp,os.path.getsize(fp) if os.path.exists(fp) else None))
            jobs[job_id]["status"]="done"; jobs[job_id]["stems"]=stems; jobs[job_id]["stem_folder"]=name
        else:
            with get_db() as conn:
                conn.execute("UPDATE stem_sessions SET status='error' WHERE id=?",(session_id,))
            jobs[job_id]["status"]="error"; jobs[job_id]["error"]="Errore Demucs"
    except Exception as e:
        jobs[job_id]["status"]="error"; jobs[job_id]["error"]=str(e)

# ── STEM CARICATI A MANO (una cartella di tracce già separate) ────────────────
# Demucs produce sempre le stesse quattro tracce (vocals/drums/bass/other).
# Quando invece le tracce arrivano da fuori — una cartella con dentro
# "canzone - Violino.mp3", "canzone - Pianoforte.mp3", … — i nomi sono liberi,
# quindi l'ETICHETTA della traccia (`stem_tracks.stem_type`, quella che si legge
# in /scheda) si ricava dal NOME DEL FILE. È la stessa etichetta che ✏️ Rinomina
# in massa può correggere in blocco dopo l'import (stesso pannello del tab
# Database, stesse regole, annullabile con ↩️ Undo).
STEM_EXT = {"mp3", "wav", "flac", "m4a", "aac", "ogg", "opus", "aif", "aiff"}
# Prefisso del modello salvato in `stem_sessions.model_name` per gli import a mano
# (Demucs scrive 'htdemucs'): serve a riusare UNA sola sessione per canzone.
STEM_MODELLO_MANUALE = "manuale"


def strumento_da_nomefile(nome):
    """Funzione PURA: dal nome di un file di stem all'etichetta della traccia.

    "canzone - Violino.mp3"                  → "violino"
    "50 Cent - In da Club - Pianoforte.wav"  → "pianoforte"
    "canzone_-_Batteria.flac"                → "batteria"
    "canzone – Violino (2).mp3"              → "violino"
    "vocals.mp3"  (Demucs, senza " - ")      → "vocals"

    Si prende il pezzo DOPO l'ULTIMO separatore « - » (tutto quel che sta prima è
    il nome della canzone) e si tolgono estensione audio, trattini tipografici,
    doppi spazi e il marcatore di duplicato finale («(2)», «[2]»). Senza
    separatore si usa il nome intero, così le tracce di Demucs restano
    vocals/drums/bass/other. L'etichetta esce in minuscolo (come 'vocals'): a
    scriverla con la maiuscola è la pagina /scheda.
    """
    base = os.path.basename(str(nome or "").strip())
    if not base:
        return ""
    radice, ext = os.path.splitext(base)
    if ext.lower().lstrip(".") in STEM_EXT:
        base = radice
    base = re.sub(r"[\u2010-\u2015]", "-", base)      # trattini tipografici → "-"
    base = re.sub(r"_\s*-\s*_", " - ", base)          # "canzone_-_Violino"
    base = re.sub(r"[\s_]+", " ", base).strip()
    if " - " in base:                                  # il pezzo dopo l'ULTIMO " - "
        pezzo = base.rsplit(" - ", 1)[1].strip()
        if pezzo:
            base = pezzo
    base = re.sub(r"\s*[\(\[]\s*\d+\s*[\)\]]\s*$", "", base)   # "(2)" di duplicato
    base = re.sub(r"\s{2,}", " ", base).strip(" -_.")
    return base.lower()


def etichette_stem_da_nomi(nomi):
    """Funzione PURA: le etichette di una lista di nomi, nello stesso ordine."""
    return [strumento_da_nomefile(n) for n in (nomi or [])]


def _nome_file_sicuro(nome):
    """Il nome di un file caricato, ripulito: niente percorsi né caratteri strani.

    Il selettore di cartella manda solo il nome del file, ma il nome arriva dal
    browser: si toglie ogni pezzo di percorso (`../`, `C:\\…`), i caratteri di
    controllo e i punti iniziali (niente file nascosti). Funzione PURA.
    """
    base = os.path.basename(str(nome or "").replace("\\", "/")).strip()
    base = re.sub(r"[\x00-\x1f\x7f]", "", base)
    return base.lstrip(".").strip()


def _cartella_stem(song):
    """La cartella (dentro `stems/htdemucs`) dei file di UNA canzone.

    È la stessa che sceglie Demucs — il nome del file locale senza estensione —
    così `_scheda_stem()` ritrova su disco anche le tracce caricate a mano. Se la
    canzone non ha file locale si usa un nome suo (`caricati_<id>`), così le
    tracce restano comunque ordinabili.
    """
    base = os.path.splitext(os.path.basename(str(song.get("local_file") or "")))[0].strip()
    if not base:
        base = "caricati_%s" % (str(song.get("id") or "").replace("song_", "") or "senza_id")
    return re.sub(r"[\\/]+", "_", base).strip() or "stems"


# ── TRIM ─────────────────────────────────────────────────────────────────────
def do_trim(job_id, filename, start, end, fmt):
    jobs[job_id]["status"]="trimming"
    try:
        src=os.path.join(DL_DIR,filename)
        if not os.path.exists(src):
            jobs[job_id]["status"]="error"; jobs[job_id]["error"]="File non trovato"; return
        base=os.path.splitext(filename)[0]
        out_name=f"{base}_trim_{int(start)}-{int(end)}.{fmt}"
        out_path=os.path.join(DL_DIR,out_name)
        dur=end-start
        codec=["-acodec","libmp3lame","-q:a","2"] if fmt=="mp3" else ["-acodec","pcm_s16le"]
        cmd=[FFMPEG,"-y","-ss",str(start),"-t",str(dur),"-i",src,*codec,out_path]
        res=subprocess.run(cmd,capture_output=True,stdin=subprocess.DEVNULL)
        if res.returncode!=0:
            jobs[job_id]["status"]="error"
            jobs[job_id]["error"]="Errore ffmpeg: "+res.stderr.decode(errors="ignore")[-200:]
            return
        jobs[job_id]["status"]="done"; jobs[job_id]["filename"]=out_name
    except Exception as e:
        jobs[job_id]["status"]="error"; jobs[job_id]["error"]=str(e)

# ── WHOSAMPLED SCRAPER ────────────────────────────────────────────────────────
# Parole-variante dentro le parentesi: possono comparire subito dopo "("
# ("(Remix)", "(Clean)", "(Live)") oppure come alternative a più parole
# ("(Radio Edit)", "(Album Version)").
_VARIANT_WORDS_IN_PARENS = (r'remix|cover|live|radio edit|edit|version|instrumental|remaster'
                            r'|acoustic|demo|reprise|album version|single version|explicit'
                            r'|clean|intro|outro|karaoke|a cappella')
# Parole-variante come SUFFISSO finale del titolo (senza parentesi o dopo un
# numero dentro parentesi: "Title Remix", "Title (2024 Remix)"). Escludiamo
# parole ambigue come version/live/edit perché possono essere parte del nome
# reale (es. "...(Griffith Park Collection Live Version)").
_VARIANT_WORDS_TRAILING = (r'remix|cover|instrumental|remaster|acoustic|demo|reprise|karaoke|a cappella')
# Rileva marcatori di variante: dentro parentesi oppure come parola finale.
# NON tocca parole a metà titolo ("Live and Let Die" non è una variante).
_VARIANT_RE = re.compile(
    r'\((?:%s)\b|\b(?:%s)\s*\)?\s*$' % (_VARIANT_WORDS_IN_PARENS, _VARIANT_WORDS_TRAILING),
    re.IGNORECASE)

def _has_variant_marker(s):
    """True se la stringa contiene un marcatore di variante (remix/cover/live/...),
    che indica una versione NON originale del brano."""
    return bool(_VARIANT_RE.search(s or ""))

def match_score(sa, st, fa, ft):
    from difflib import SequenceMatcher
    raw_st, raw_ft = st, ft
    sa, st, fa, ft = normalize(sa), normalize(st), normalize(fa), normalize(ft)
    if sa == fa and st == ft:
        return 1.0
    ts = 0.85 + (min(len(st), len(ft)) / max(len(st), len(ft), 1)) * 0.15 if (st in ft or ft in st) else SequenceMatcher(None, st, ft).ratio()
    ars = 1.0 if (sa == fa or sa in fa or fa in sa) else SequenceMatcher(None, sa, fa).ratio()
    score = ts * 0.80 + ars * 0.20
    # Le varianti (remix, cover, live…) NON sono il brano originale: se il brano
    # cercato non è una variante, i candidati variante vengono penalizzati
    # (es. cercando "Hell on Earth" non deve vincere "Hell on Earth (Remix)").
    if _has_variant_marker(raw_ft) and not _has_variant_marker(raw_st):
        score *= 0.75
    return score

def _detect_chrome_version():
    """Rileva la versione maggiore di Chrome/Chromium installato, per allineare
    il ChromeDriver alla versione reale del browser (evita l'errore
    'ChromeDriver only supports Chrome version X. Current browser version is Y')."""
    candidates = [
        "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
        "/Applications/Chromium.app/Contents/MacOS/Chromium",
        "/Applications/Google Chrome Canary.app/Contents/MacOS/Google Chrome Canary",
    ]
    for path in candidates:
        if os.path.exists(path):
            try:
                out = subprocess.run([path, "--version"], capture_output=True,
                                     text=True, timeout=10).stdout or ""
                m = re.search(r"(\d+)\.", out)
                if m:
                    print(f"[chrome] browser rilevato: {out.strip()} (major {m.group(1)})")
                    return int(m.group(1))
            except Exception:
                pass
    return None

def make_driver():
    import undetected_chromedriver as uc
    opts = uc.ChromeOptions()
    for a in ["--headless=new","--no-sandbox","--disable-dev-shm-usage",
              "--disable-blink-features=AutomationControlled","--disable-gpu",
              "--window-size=1920,1080","--remote-debugging-port=0"]:
        opts.add_argument(a)
    opts.add_argument("--user-agent=Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/131.0.0.0 Safari/537.36")
    version_main = _detect_chrome_version()
    driver = uc.Chrome(options=opts, use_subprocess=True, version_main=version_main)
    # Timeout di caricamento pagina: il default di Chrome è 300s, troppo lungo
    # (es. Tunebat/WhoSampled lenti o bloccati da Cloudflare → la verifica
    # restava appesa per minuti sul passo "Verifica BPM/Key su Tunebat").
    try:
        driver.set_page_load_timeout(25)
    except Exception:
        pass
    return driver

def fetch_page(driver, url):
    try:
        driver.set_page_load_timeout(25)
        driver.get(url)
        for _ in range(12):
            time.sleep(1)
            title = driver.title or ""
            html = driver.page_source
            if "Just a moment" in title or "Attention Required" in title:
                continue
            if "Sorry, you have been blocked" in html:
                return None
            break
        else:
            return None
        time.sleep(1)
        return driver.page_source
    except Exception:
        return None

def search_whosampled(driver, query, searched_artist="", searched_title=""):
    from bs4 import BeautifulSoup
    html = fetch_page(driver, "https://www.whosampled.com/search/?q=" + urllib.parse.quote(query))
    if not html:
        return None, []
    soup = BeautifulSoup(html, "html.parser")
    candidates = []
    top = soup.select_one("div.topHit")
    if top:
        tl = top.select_one("a.trackTitle")
        al = top.select_one(".trackArtist a")
        if tl and al:
            href = tl.get("href", "")
            candidates.append({
                "title": tl.get_text(strip=True),
                "artist": al.get_text(strip=True),
                "url": "https://www.whosampled.com" + href if href.startswith("/") else href,
            })
    for entry in soup.select("li.trackEntry"):
        tl = entry.select_one("a.trackName")
        al = entry.select_one(".trackArtist a")
        if tl and al:
            href = tl.get("href", "")
            candidates.append({
                "title": tl.get_text(strip=True),
                "artist": al.get_text(strip=True),
                "url": "https://www.whosampled.com" + href if href.startswith("/") else href,
            })
    if not candidates:
        return None, []
    # Preferisce i candidati che NON sono varianti (remix/cover/live…) quando la
    # ricerca non chiede esplicitamente una variante. Es.: cercando "Hell on Earth"
    # deve vincere "Hell on Earth (Front Lines)" e non "Hell on Earth (Remix)".
    pool = candidates
    if not _has_variant_marker(searched_title):
        originals = [c for c in candidates if not _has_variant_marker(c["title"])]
        if originals:
            pool = originals
    if not searched_artist:
        # SENZA artista non si può confrontare l'artista: `match_score` dà 1.0 a un
        # nome vuoto ("".lower() è contenuto in qualsiasi nome), quindi il punteggio
        # non prova nulla. Fino al 18/09/2026 qui si restituiva `candidates[0]` a
        # occhio: la Verifica di *End of the World* (artista "Brano locale") salvava
        # così la pagina di **Skeeter Davis** — un altro brano. Ora si sceglie per
        # TITOLO e si restituiscono TUTTI i candidati, perché il chiamante deve poter
        # vedere se quel titolo è condiviso da più artisti e far decidere la conferma
        # audio (`esito_whosampled`).
        best = max(pool, key=lambda c: match_score("", searched_title, "", c["title"]),
                   default=None)
        return best, candidates
    best = max(pool, key=lambda c: match_score(searched_artist, searched_title, c["artist"], c["title"]), default=None)
    return best, candidates

def extract_timestamps(driver, conn_url):
    html = fetch_page(driver, conn_url)
    if not html:
        return None, None
    from bs4 import BeautifulSoup
    text = BeautifulSoup(html, "html.parser").get_text()
    matches = re.findall(r"Sample appears at\s+(?:\*\*)?(\d+):(\d+)(?:\*\*)?", text)
    ts = [int(m[0]) * 60 + int(m[1]) for m in matches]
    if not ts:
        ts = [int(s) for s in re.findall(r"Sample appears at\s+(\d+)\s+second", text)]
    return (ts[0] if ts else None), (ts[1] if len(ts) > 1 else None)

def get_track_detail(driver, track_url):
    from bs4 import BeautifulSoup
    html = fetch_page(driver, track_url)
    if not html:
        return {"contains": [], "sampled_in": [], "covered_by": []}
    soup = BeautifulSoup(html, "html.parser")
    result = {"contains": [], "sampled_in": [], "covered_by": []}
    for section in soup.find_all("section", class_="subsection"):
        h = section.find(["h2", "h3"])
        if not h:
            continue
        ht = h.get_text().lower()
        is_c = "contains" in ht or "sampled by" in ht
        is_s = "was sampled in" in ht or "sampled in" in ht
        is_cv = "covered by" in ht or "cover" in ht
        if not is_c and not is_s and not is_cv:
            continue
        for row in section.select("table.tdata tbody tr"):
            tn = row.select_one("td.tdata__td2 a.trackName")
            if not tn:
                continue
            title = tn.get_text(strip=True)
            ac = row.find_all("td", class_="tdata__td3")
            artist = " ".join(ac[0].get_text(" ", strip=True).split()) if ac else ""
            year = ac[1].get_text(strip=True) if len(ac) > 1 else ""
            cu = tn.get("href", "")
            if cu.startswith("/"):
                cu = "https://www.whosampled.com" + cu
            td, ts = None, None
            if cu:
                td, ts = extract_timestamps(driver, cu)
                time.sleep(1.5)
            item = {
                "title": title,
                "artist": artist,
                "year": year,
                "ws_url": cu,
                "timestamp_yi": ts if is_c else td,
                "timestamp_x": td if is_c else ts,
            }
            if is_c:
                result["contains"].append(item)
            elif is_s:
                result["sampled_in"].append(item)
            elif is_cv:
                result["covered_by"].append(item)
    return result

def clean_yt_title(title, artist=""):
    title = re.sub(r'\s*\(.*?\)', '', title)
    title = re.sub(r'\s*\[.*?\]', '', title)
    title = re.sub(r'^\s*\d+[\.\s\-:]+', '', title)
    if artist and artist.strip():
        a = artist.strip()
        # "Artista - Titolo" / "Artista: Titolo" (prefisso) o "Titolo - Artista" (suffisso)
        title = re.sub(r'^\s*' + re.escape(a) + r'\s*[-–:·|]\s*', '', title, flags=re.IGNORECASE)
        title = re.sub(r'\s*[-–:·|]\s*' + re.escape(a) + r'\s*$', '', title, flags=re.IGNORECASE)
        # il numero di traccia può venire dopo l'artista (es. "ILL MOVEMENT - 1 - TRE STRONZI")
        title = re.sub(r'^\s*\d+[\.\s\-:]+', '', title)
    return re.sub(r'\s+', ' ', title).strip()

def split_yt_title(yt_title, default_artist=""):
    """Da un titolo YouTube tipo 'Eminem - Guilty Conscience ft. Dr. Dre'
    estrae (artista, titolo_pulito) -> ('Eminem', 'Guilty Conscience').
    Se non c'è il prefisso 'Artista - ', usa default_artist.
    Rimuove parentesi, feat./ft./featuring e numeri di traccia iniziali."""
    t = (yt_title or "").strip()
    artist = (default_artist or "").strip()
    m = re.match(r'^\s*([^\-–—:·|]{1,50}?)\s*[-–—:·|]\s+(.+)$', t)
    if m:
        artist = m.group(1).strip() or artist
        t = m.group(2).strip()
    # contenuto tra parentesi tonde o quadre
    t = re.sub(r'\s*[\(\[][^\)\]]*[\)\]]', '', t)
    # feat. / ft. / featuring (e varianti senza punto)
    t = re.sub(r'\s+(?:feat\.?|ft\.?|featuring|feat)\b.*$', '', t, flags=re.IGNORECASE)
    # numero di traccia iniziale (es. "03 Titolo")
    t = re.sub(r'^\s*\d+\s*[\.\-\s:]+', '', t)
    t = re.sub(r'\s+', ' ', t).strip(' -–—|')
    return artist, t

def _strip_part_suffix(title):
    """Da 'Shook Ones Pt. II' → 'Shook Ones'. Rimuove i suffissi di parte
    ('Pt. X'/'Part X', arabici o romani) per cercare meglio su WhoSampled."""
    t = (title or "").strip()
    t = re.sub(r'\s*(?:pt\.?|part)\s*(?:[ivxIVX]+|\d+)\s*\)?\s*$', '', t, flags=re.IGNORECASE)
    return t.strip(' ,.–-')

def yt_match_score(expected_artist, expected_title, found_title):
    """Match score tra la canzone cercata e il titolo restituito da YouTube.

    yt_search_first restituisce solo il titolo (di solito 'Artista - Titolo'),
    senza l'artista separato: se dal titolo si riesce a estrarre l'artista si usa
    match_score completo (artista+titolo); altrimenti si confronta solo il
    titolo, con un bonus se l'artista cercato compare nel titolo trovato.

    Serve a NON accettare il primo risultato YouTube quando è una canzone
    diversa ma popolare (es. 'Eminem 3hree6ix5ive' → 'Lose Yourself')."""
    from difflib import SequenceMatcher
    found = (found_title or "").strip()
    m = re.match(r'^(.+?)\s+[-–—]\s+(.+)$', found)
    if m:
        fa = m.group(1).strip()
        ft = clean_yt_title(m.group(2), artist=fa)
        return match_score(expected_artist, expected_title, fa, ft)
    ft = clean_yt_title(found)
    score = SequenceMatcher(None, normalize(expected_title), normalize(ft)).ratio()
    if expected_artist and normalize(expected_artist) and normalize(expected_artist) in normalize(found):
        score = max(score, 0.60)
    return score

def clean_search_text(text, artist=""):
    """Pulisce titolo/artista per la ricerca web (Genius, YouTube, WhoSampled…).

    - toglie il numeretto iniziale di traccia: '1 - TRE STRONZI' → 'TRE STRONZI'
      (serve un separatore dopo il numero, così '10 Laws'/'90MIN' non vengono toccati)
    - toglie trattini/separatori iniziali e finali
    - se viene passato l'artista, toglie il prefisso 'Artista - ' e il suffisso ' - Artista'
    - toglie annotazioni comuni '(Lyrics)', '[Official Video]', ecc. ma NON '(feat ...)'
    - compatta gli spazi
    """
    t = (text or "").strip()
    if not t:
        return t
    if artist:
        a = artist.strip()
        if a:
            t = re.sub(r'^\s*' + re.escape(a) + r'\s*[-–—:·|]\s*', '', t, flags=re.IGNORECASE)
            t = re.sub(r'\s*[-–—:·|]\s*' + re.escape(a) + r'\s*$', '', t, flags=re.IGNORECASE)
    # numeretto di traccia iniziale ('1 - TRE STRONZI' → 'TRE STRONZI', '3) GIRLS' → 'GIRLS')
    t = re.sub(r'^\s*\d+\s*[-–—:.,)\]\[/]+\s*', '', t)
    # separatori iniziali residui
    t = re.sub(r'^\s*[-–—:·|,.;]+\s*', '', t)
    # annotazioni comuni in coda (non feat, che serve al match)
    t = re.sub(r'\s*\((?:official\s+)?(?:lyrics|video|audio|music\s*video)\)\s*$', '', t, flags=re.IGNORECASE)
    t = re.sub(r'\s*\[(?:official\s+)?(?:lyrics|video|audio|music\s*video)\]', '', t, flags=re.IGNORECASE)
    return re.sub(r'\s+', ' ', t).strip()

def artist_title_from_filename(filename, db_artist=""):
    """Prova a estrarre (artista, titolo) dal nome del file locale.

    I file arrivano dal player come 'onyx_t_<timestamp>.<TESTO>' dove TESTO è
    tipicamente '<ARTISTA> - <TITOLO>' (es. 'ILL MOVEMENT - 1 - TRE STRONZI')
    oppure solo '<TITOLO>' ('Cha-Ching', 'COM] Who Knew').

    Per evitare falsi positivi (es. 'Save Me - with Lainey Wilson') il pattern
    'ARTISTA - TITOLO' viene accettato solo se l'artista estratto combacia con
    quello salvato nel DB (o se nel DB non c'è un artista reale)."""
    f = (filename or "").strip()
    if not f:
        return None, None
    base = f.rsplit(".", 1)[-1] if "." in f else f
    base = base.strip()
    # rimuovi prefissi artefatto tipo 'COM] ' che appaiono su alcuni file
    base = re.sub(r'^[A-Za-z]{2,4}\]\s*', '', base)
    m = re.match(r'^(.+?)\s+[-–—]\s+(.+)$', base)
    if not m:
        return None, None
    artist = m.group(1).strip()
    title = m.group(2).strip()
    if not artist or not title or len(artist) > 80:
        return None, None
    if re.search(r'\bfeat\.?\b', artist, re.I):
        return None, None
    if db_artist:
        da = db_artist.strip()
        if da and normalize(da) != normalize("Brano locale") and normalize(artist) != normalize(da):
            return None, None
    return artist, title

    return artist, title

# ── ARTISTA SEGNAPOSTO / ESTRAZIONE ARTISTA DAL TITOLO ───────────────────────
# Molte canzoni importate dal player hanno artist="Brano locale" (o simili):
# non è un artista vero e, messo nella query di ricerca, confonde Genius/YouTube
# ("Brano locale Simon says hopsin freestyle" → 0 risultati). Per quelle canzoni
# si cerca col solo titolo e, se il titolo contiene un artista conosciuto dal DB
# (es. "Simon says hopsin freestyle" → Hopsin), lo si estrae come artista.
_PLACEHOLDER_ARTISTS = {
    "", "brano", "brano locale", "local", "local track", "local artist",
    "unknown", "unknown artist", "unknown artists", "various artists",
    "varie artisti", "varie", "sconosciuto", "no artist", "n/a",
}

def is_placeholder_artist(artist):
    return (artist or "").strip().lower() in _PLACEHOLDER_ARTISTS

_db_artists_cache = None

def get_db_artist_list():
    """Lista (cache) degli artisti distinti nel DB: serve a riconoscere dentro
    un titolo il nome dell'artista quando il campo artist è un segnaposto."""
    global _db_artists_cache
    if _db_artists_cache is None:
        try:
            with get_db() as conn:
                _db_artists_cache = [
                    r[0] for r in conn.execute(
                        "SELECT DISTINCT artist FROM songs "
                        "WHERE artist IS NOT NULL AND TRIM(artist) != ''").fetchall()
                ]
        except Exception:
            _db_artists_cache = []
    return _db_artists_cache

def known_artist_in_title(title, artist_list):
    """Cerca nel titolo un artista conosciuto (dalla lista del DB), con confine
    di parola. Ritorna il match più a sinistra (a parità di posizione, il nome
    più lungo). Es. 'Simon says hopsin freestyle' + artisti del DB → 'Hopsin'."""
    t = title or ""
    best = None
    best_pos = len(t) + 1
    best_len = 0
    for a in artist_list:
        a = (a or "").strip()
        if len(a) < 2 or is_placeholder_artist(a):
            continue
        m = re.search(r'(?<![A-Za-z0-9])' + re.escape(a) + r'(?![A-Za-z0-9])', t, re.IGNORECASE)
        if m and (m.start() < best_pos or (m.start() == best_pos and len(a) > best_len)):
            best = a
            best_pos = m.start()
            best_len = len(a)
    return best

def _make_driver_safe(timeout=60):
    result = [None]
    exc = [None]
    def _t():
        try:
            result[0] = make_driver()
        except Exception as e:
            exc[0] = e
    t = threading.Thread(target=_t, daemon=True)
    t.start()
    t.join(timeout)
    if t.is_alive():
        raise TimeoutException("Timeout avvio browser")
    if exc[0]:
        raise exc[0]
    return result[0]

def do_scrape(job_id, artist, title):
    use_yt_fallback = jobs[job_id].get("use_yt_fallback", True)
    use_scoring = jobs[job_id].get("use_scoring", True)

    jobs[job_id]["status"] = "starting"
    jobs[job_id]["log"] = []
    def log(msg):
        jobs[job_id]["log"].append(msg)
        print(msg)

    driver = None
    try:
        log("Avvio browser...")
        jobs[job_id]["status"] = "browser_startup"

        driver = None
        try:
            driver = _make_driver_safe(60)
        except TimeoutException:
            jobs[job_id]["status"] = "error"
            jobs[job_id]["error"] = "Timeout: il browser non si è avviato entro 60 secondi. Verifica che Google Chrome sia installato e aggiornato."
            log("TIMEOUT durante l'avvio del browser")
            return
        except Exception as e:
            jobs[job_id]["status"] = "error"
            jobs[job_id]["error"] = f"Errore avvio browser: {str(e)}"
            log(f"ERRORE avvio browser: {e}")
            return

        log(f"Browser avviato. Ricerca su WhoSampled: {artist} - {title}")
        jobs[job_id]["status"] = "whosampled_search"

        # Prima ricerca su WhoSampled
        if use_scoring:
            track, candidates = search_whosampled(driver, f"{artist} {title}", searched_artist=artist, searched_title=title)
        else:
            track, candidates = search_whosampled(driver, f"{artist} {title}", searched_artist="", searched_title="")

        # Se il track ha punteggio basso, forziamo il fallback YouTube
        if track and use_yt_fallback and use_scoring:
            track_score = match_score(artist, title, track.get("artist", ""), track.get("title", ""))
            if track_score < 0.55:
                log(f"[DEBUG] Punteggio del track trovato ({track_score:.3f}) troppo basso, attivo fallback YouTube")
                track = None

        # Fallback YouTube se track non trovato o forzato
        if not track and use_yt_fallback:
            log("[DEBUG] WhoSampled non ha trovato la canzone (o punteggio basso), provo su YouTube...")
            yt_url, yt_title, yt_choices = yt_search_choices_prefer_explicit(
                f"{artist} {title}", expected_title=title, expected_artist=artist)
            if yt_title:
                # Estrae artista e titolo dal titolo YouTube (es. "Eminem - Guilty Conscience ft. Dr. Dre"
                # -> artista "Eminem", titolo "Guilty Conscience"). Usa la grafia ufficiale di YouTube,
                # quindi corregge anche eventuali refusi dell'utente (es. "coscience" -> "Conscience").
                yt_artist_clean, yt_title_clean = split_yt_title(yt_title, artist)
                log(f"[DEBUG] YouTube ha trovato: artista='{yt_artist_clean}' titolo='{yt_title_clean}'")

                # Prova più combinazioni su WhoSampled finché una non dà un match valido.
                # Oltre al titolo pulito prova anche il titolo SENZA 'Pt. X'/'Part X'
                # (es. "Shook Ones Pt. 1" → "Shook Ones") perché su WhoSampled le parti
                # sono scritte in romano ("Shook Ones, Pt. II") e i numeri arabici non
                # vengono trovati.
                yt_bare_title = _strip_part_suffix(yt_title_clean)
                attempts = [
                    (f"{yt_artist_clean} {yt_title_clean}", yt_artist_clean, yt_title_clean, "artista YouTube"),
                    (f"{artist} {yt_title_clean}", artist, yt_title_clean, "artista cercato"),
                ]
                if yt_bare_title and yt_bare_title.lower() != yt_title_clean.lower():
                    attempts.append((f"{yt_artist_clean} {yt_bare_title}", yt_artist_clean, yt_bare_title, "artista YouTube + titolo senza pt."))
                attempts.append((yt_title_clean, "", yt_title_clean, "solo titolo"))
                if yt_bare_title and yt_bare_title.lower() != yt_title_clean.lower():
                    attempts.append((yt_bare_title, "", yt_bare_title, "solo titolo senza pt."))
                for query, sa, st, desc in attempts:
                    if track:
                        break
                    if use_scoring:
                        cand, cands = search_whosampled(driver, query, searched_artist=sa, searched_title=st)
                        if cand:
                            sc = match_score(sa or artist, st, cand.get("artist", ""), cand.get("title", ""))
                            log(f"Tentativo ({desc}): '{query}' -> {cand['artist']} - {cand['title']} (score {sc:.3f})")
                            if sc >= 0.45:
                                track = cand
                        else:
                            log(f"Tentativo ({desc}): '{query}' -> nessun risultato")
                    else:
                        cand, cands = search_whosampled(driver, query, searched_artist="", searched_title="")
                        if cand:
                            log(f"Tentativo ({desc}): '{query}' -> {cand['artist']} - {cand['title']}")
                            track = cand
                        else:
                            log(f"Tentativo ({desc}): '{query}' -> nessun risultato")

                if track:
                    if not track.get("title"):
                        track['title'] = yt_title_clean
                    log(f"✅ Trovato su WhoSampled: {track['artist']} - {track['title']}")
                else:
                    # Se anche dopo i tentativi fallisce, usiamo i dati di YouTube (senza sample)
                    log("[DEBUG] WhoSampled non trova la canzone, uso i dati di YouTube")
                    track = {
                        "title": yt_title_clean,
                        "artist": yt_artist_clean or artist,
                        "url": None
                    }
                    jobs[job_id]["status"] = "done"
                    jobs[job_id]["result"] = {
                        "title": yt_title_clean,
                        "artist": yt_artist_clean or artist,
                        "ws_url": None,
                        "main_yt_url": yt_url,
                        "main_yt_title": yt_title_clean,
                        "main_yt_choices": yt_choices or [],
                        "contains": [],
                        "sampled_in": [],
                    }
                    log(f"⚠️ Usato YouTube come fonte primaria per '{yt_title_clean}'")
                    return

        if not track:
            jobs[job_id]["status"] = "error"
            jobs[job_id]["error"] = "Canzone non trovata su WhoSampled"
            return

        log(f"Trovata: {track['title']} by {track['artist']}")
        jobs[job_id]["status"] = "whosampled_detail"
        log("Estrazione sample e timestamp...")
        detail = get_track_detail(driver, track["url"])
        log(f"Trovati: {len(detail['contains'])} sample usati, {len(detail['sampled_in'])} canzoni che campionano, {len(detail.get('covered_by', []))} cover")
        driver.quit()
        driver = None
        log(f"Ricerca YouTube: {track['artist']} - {track['title']}")
        jobs[job_id]["status"] = "youtube_search"
        main_yt_url, main_yt_title, main_yt_choices = yt_search_choices_prefer_explicit(
            f"{track['artist']} {track['title']}",
            expected_title=track['title'],
            expected_artist=track['artist']
        )
        log(f"YouTube principale: {main_yt_title or 'non trovato'}")

        for section_key in ("contains", "sampled_in", "covered_by"):
            for item in detail[section_key]:
                query_parts = [item['artist'], item['title']]
                if item['artist'].lower() != track['artist'].lower():
                    query_parts.append(track['artist'])
                q = " ".join(query_parts)
                log(f"Ricerca YouTube: {q}")
                yt_url, yt_title = yt_search_first(q, expected_title=item['title'], expected_artist=item['artist'])
                item["yt_url"] = yt_url
                item["yt_title"] = yt_title or item["title"]
                time.sleep(0.3)

        dataset = load_dataset()
        for section_key in ("contains", "sampled_in", "covered_by"):
            for item in detail[section_key]:
                item["already_saved"] = check_pair_exists_loose(
                    dataset,
                    {"title": track["title"], "artist": track["artist"]},
                    {"title": item["title"], "artist": item["artist"]},
                    category="SAMPLE"
                )

        jobs[job_id]["status"] = "done"
        jobs[job_id]["result"] = {
            "title": track["title"],
            "artist": track["artist"],
            "ws_url": track["url"],
            "main_yt_url": main_yt_url,
            "main_yt_title": main_yt_title or track["title"],
            "main_yt_choices": main_yt_choices or [],
            "contains": detail["contains"],
            "sampled_in": detail["sampled_in"],
            "covered_by": detail.get("covered_by", []),
        }
        log("Completato!")

    except Exception as e:
        jobs[job_id]["status"] = "error"
        jobs[job_id]["error"] = str(e)
        log(f"ERRORE: {e}")
    finally:
        if driver:
            try: driver.quit()
            except: pass
# ═══════════════════════════════════════════════════════════
# ROUTES
# ═══════════════════════════════════════════════════════════

@app.route("/")
def index():
    return send_file(os.path.join(BASE_DIR, "index (2).html"))

# ── ONYX PLAYER (interfaccia completa di ascolto) ─────────────────────────────
@app.route("/onyx")
def onyx():
    return send_file(os.path.join(BASE_DIR, "onyx_whosampled.html"))

# ── BROWSE (pagina esplora: canzoni di un artista o di un album) ─────────────
@app.route("/browse")
def browse():
    return send_file(os.path.join(BASE_DIR, "browse.html"))

# ── FORTISSIMO COMPARE (pagina di test del modello di confronto strumenti) ────
@app.route("/fortissimo")
def fortissimo():
    return send_file(os.path.join(BASE_DIR, "fortissimo.html"))

# ── SCHEDA CANZONE (stem + remix/cover + campionamenti WhoSampled) ───────────
# Una schermata per canzone: /scheda?song=<id> (i dati li dà
# /db/songs/<id>/scheda). Si apre dal pulsante «📄 Scheda» della tabella del
# database, su ogni riga.
@app.route("/scheda")
def scheda():
    return send_file(os.path.join(BASE_DIR, "scheda.html"))

@app.route("/verifica")
def verifica_pagina():
    """La schermata di verifica guidata (18/09/2026): una pagina per UNA canzone,
    con i dati da correggere, le opzioni (audio / voce / a cappella / non-su-Genius),
    le tolleranze e il progresso passo-per-passo. Si apre da 🔎 Verifica nel
    database o dal player con `?song=<id>`."""
    return send_file(os.path.join(BASE_DIR, "verifica.html"))

# ── IL SAMPLER COME PAGINA A SÉ STANTE (19/09/2026) ──────────────────────────
# Il player stile FL Studio (onda, griglia BPM, metronomo, TAP, trim…) è definito
# DENTRO `index (2).html`, in una <textarea id="audio-editor-src">: la pagina lo
# monta in un iframe `blob:` (embedAudioEditorX) e lo apre nella finestra modale.
# Per montarlo anche da un'ALTRA pagina — `/scheda`, dove serve un player per OGNI
# stem — senza copiare quel documento (sarebbe una copia da tenere allineata a
# mano, e alla prima modifica del sampler andrebbero fuori sincrono), qui il testo
# della textarea si serve su `GET /sampler`: la sorgente resta una sola.
_SAMPLER_CACHE = {}      # percorso del file -> (mtime, testo del sampler)

def sampler_html():
    """Il documento del sampler, letto dalla textarea di `index (2).html`.

    Il file si rilegge solo quando cambia (mtime): la pagina principale è grande
    e un iframe per stem farebbe tre o quattro letture per niente.
    """
    percorso = os.path.join(BASE_DIR, "index (2).html")
    mtime = os.path.getmtime(percorso)
    cache = _SAMPLER_CACHE.get(percorso)
    if cache and cache[0] == mtime:
        return cache[1]
    with open(percorso, encoding="utf-8") as fh:
        pagina = fh.read()
    m = re.search(r'<textarea[^>]*id="audio-editor-src"[^>]*>(.*?)</textarea>',
                  pagina, re.S)
    testo = (m.group(1).strip() if m else "")
    if not testo:
        raise RuntimeError("il documento del sampler non è in index (2).html")
    _SAMPLER_CACHE[percorso] = (mtime, testo)
    return testo

@app.route("/sampler")
def sampler_pagina():
    """Il sampler come pagina indipendente (per gli iframe: `/scheda` lo monta su
    ogni stem). Il protocollo dei messaggi è lo stesso della pagina principale:
    `{action:'load', url, filename, etichetta, startSec, endSec, bpm, grid, trim}`."""
    try:
        return Response(sampler_html(), mimetype="text/html")
    except Exception as e:
        return Response(f"<p>sampler non disponibile: {e}</p>", status=500,
                        mimetype="text/html")

# ── STREAMING ────────────────────────────────────────────────────────────────
def _risposta_audio(path, mime):
    """Risponde con un file audio rispettando l'header `Range`.

    Serve ai player (`/stream`, `/anteprima`): senza la risposta 206 il browser
    scarica tutto il file prima di poter scorrere avanti/indietro con la barra.
    """
    fs = os.path.getsize(path)
    rh = request.headers.get("Range")
    if rh:
        m = re.match(r"bytes=(\d+)-(\d*)", rh)
        if m:
            s = int(m.group(1))
            e = int(m.group(2)) if m.group(2) else fs - 1
            ln = e - s + 1
            def gen():
                with open(path, "rb") as f:
                    f.seek(s)
                    rem = ln
                    while rem > 0:
                        c = f.read(min(8192, rem))
                        if not c:
                            break
                        rem -= len(c)
                        yield c
            resp = Response(gen(), 206, mimetype=mime)
            resp.headers.update({
                "Content-Range": f"bytes {s}-{e}/{fs}",
                "Accept-Ranges": "bytes",
                "Content-Length": str(ln),
            })
            return resp
    return send_file(path, mimetype=mime)


def _dentro_la_cartella(cartella, percorso):
    """Funzione PURA. Il file sta (davvero) dentro la cartella indicata?

    I nomi dei file della libreria sono liberi (parentesi, virgole, `]`) e arrivano
    dall'URL: senza questo controllo un `../` nella richiesta uscirebbe dalla
    cartella. Si confrontano i percorsi RISOLTI.
    """
    try:
        base = os.path.realpath(cartella) + os.sep
        return os.path.realpath(percorso).startswith(base)
    except Exception:
        return False


@app.route("/stream/<path:filename>")
def stream_file(filename):
    path = os.path.join(DL_DIR, filename)
    if not os.path.exists(path) or not _dentro_la_cartella(DL_DIR, path):
        return jsonify({"error": "File non trovato"}), 404
    ext = filename.rsplit(".", 1)[-1].lower()
    return _risposta_audio(path, MIME_MAP.get(ext, "audio/mpeg"))


# ── ANTEPRIME UFFICIALI (e a cappella) ───────────────────────────────────────
# `anteprime/` (non versionata) non era servita da nessuna rotta: la pagina
# /verifica ora fa ASCOLTARE i due audio del confronto — l'anteprima ufficiale di
# iTunes che è stata confrontata col file locale e la voce estratta da demucs
# (`anteprime/acapella_…/htdemucs/<file>/vocals.mp3`, cioè quello che Whisper ha
# davvero trascritto).
@app.route("/anteprima/<path:filename>")
def anteprima_file(filename):
    path = os.path.join(ANTEPRIME_DIR, filename)
    if not os.path.isfile(path) or not _dentro_la_cartella(ANTEPRIME_DIR, path):
        return jsonify({"error": "Anteprima non trovata"}), 404
    ext = filename.rsplit(".", 1)[-1].lower()
    return _risposta_audio(path, MIME_MAP.get(ext, "audio/mpeg"))

@app.route("/stream-stem/<folder>/<filename>")
def stream_stem(folder, filename):
    path = os.path.join(STEMS_DIR, "htdemucs", folder, filename)
    if not os.path.exists(path):
        return jsonify({"error": "File non trovato"}), 404
    ext = filename.rsplit(".", 1)[-1].lower()
    mime = MIME_MAP.get(ext, "audio/mpeg")
    return send_file(path, mimetype=mime)

# ── VIDEO DELLE CANZONI (18/09/2026) ─────────────────────────────────────────
# `songs.video_file` contiene il NOME del file in `videos/` (il MP4 scaricato da
# YouTube o il video caricato dal computer). Lo stream rispetta l'header `Range`
# come `/stream`: senza, il lettore video del browser non può avanzare.
@app.route("/video/<path:filename>")
def stream_video_file(filename):
    path = os.path.join(VID_DIR, filename)
    if not os.path.isfile(path) or not _dentro_la_cartella(VID_DIR, path):
        return jsonify({"error": "Video non trovato"}), 404
    return _risposta_audio(path, mime_video(filename))

@app.route("/video-file/<path:filename>")
def download_video_file(filename):
    """Scarica il file video (attachment), senza riscrivere i tag (è un video)."""
    path = os.path.join(VID_DIR, filename)
    if not os.path.isfile(path) or not _dentro_la_cartella(VID_DIR, path):
        return jsonify({"error": "Video non trovato"}), 404
    resp = send_file(path, mimetype=mime_video(filename), as_attachment=True,
                     download_name=os.path.basename(filename))
    return resp

@app.route("/videos")
def list_video_files():
    """I video già in `videos/` (per il selettore «scegli un video» della riga)."""
    files = []
    for f in sorted(os.listdir(VID_DIR)):
        if f.startswith("."):
            continue
        fp = os.path.join(VID_DIR, f)
        if not os.path.isfile(fp) or not f.lower().endswith(VIDEO_EXTS):
            continue
        files.append({"name": f, "size": os.path.getsize(fp),
                      "ext": f.rsplit(".", 1)[-1].lower()})
    return jsonify(files)

# ── COPERTINE ────────────────────────────────────────────────────────────────
# `songs.cover_art_path` contiene il NOME del file (es. 'song_7553a924d202.jpg'),
# salvato in `covers/` dalla Verifica: qui lo si serve alla pagina, che lo usa
# come miniatura nella tabella del database e come immagine della scheda.
@app.route("/cover/<path:filename>")
def cover_file(filename):
    path = _cover_local_path(filename)
    if not path or not os.path.exists(path):
        return jsonify({"error": "Copertina non trovata"}), 404
    return send_file(path, mimetype=_cover_mime(filename))

@app.route("/download-file/<path:filename>")
def download_file(filename):
    """Scarica un file locale con i metadati del database scritti nei tag.

    Se il file è registrato nel DB (local_file) viene prima copiato e sui tag
    della copia vengono scritti i metadati (anche quelli modificati dall'utente
    nell'app), poi la copia viene inviata e infine eliminata.
    """
    path = os.path.join(DL_DIR, filename)
    if not os.path.exists(path):
        return jsonify({"error": "File non trovato"}), 404
    base, ext = os.path.splitext(filename)
    download_name = os.path.basename(filename)
    mime = MIME_MAP.get(ext.lower().lstrip("."), "audio/mpeg")
    song = None
    with get_db() as conn:
        song = row2dict(conn.execute("SELECT * FROM songs WHERE local_file=?", (filename,)).fetchone())
    temp_path = None
    if song and HAS_MUTAGEN:
        temp_path = os.path.join(DL_DIR, "." + base + ".tagged" + ext)
        if apply_audio_tags(path, temp_path, song):
            path = temp_path
            nice = f"{song.get('artist') or ''} - {song.get('title') or base}".strip(" -")
            nice = re.sub(r'[^\w\-\. ]+', '', nice).strip()
            download_name = (nice or os.path.basename(base)) + ext
    fs = os.path.getsize(path)

    def generate():
        try:
            with open(path, "rb") as f:
                while True:
                    chunk = f.read(65536)
                    if not chunk:
                        break
                    yield chunk
        finally:
            # Rimuove sempre la copia temporanea, dopo che è stata inviata.
            if temp_path and os.path.exists(temp_path):
                try: os.remove(temp_path)
                except OSError: pass

    resp = Response(generate())
    resp.headers["Content-Disposition"] = f'attachment; filename="{download_name}"'
    resp.headers["Content-Length"] = str(fs)
    resp.headers["Content-Type"] = mime
    return resp

@app.route("/upload_file", methods=["POST"])
def upload_file():
    file = request.files.get("file")
    if not file:
        return jsonify({"error": "No file"}), 400
    path = os.path.join(DL_DIR, file.filename)
    file.save(path)
    return jsonify({"ok": True, "filename": file.filename})

@app.route("/delete-file/<path:filename>", methods=["DELETE"])
def delete_file(filename):
    path = os.path.join(DL_DIR, filename)
    deleted = False
    if os.path.exists(path):
        os.remove(path)
        deleted = True
    with get_db() as conn:
        conn.execute("DELETE FROM songs WHERE local_file = ?", (filename,))
    return jsonify({"ok": True, "deleted": deleted})

@app.route("/download-stem/<folder>/<filename>")
def download_stem(folder, filename):
    path = os.path.join(STEMS_DIR, "htdemucs", folder, filename)
    if not os.path.exists(path):
        return jsonify({"error": "File non trovato"}), 404
    return send_file(path, as_attachment=True)

@app.route("/files")
def list_files():
    files = []
    for f in os.listdir(DL_DIR):
        if f.startswith("."):
            continue
        fp = os.path.join(DL_DIR, f)
        ext = f.rsplit(".", 1)[-1].lower()
        if ext in ("mp3", "wav", "m4a", "webm", "mp4", "flac", "ogg", "opus"):
            files.append({"name": f, "size": os.path.getsize(fp), "ext": ext})
    return jsonify(sorted(files, key=lambda x: x["name"]))

# ── JOBS ─────────────────────────────────────────────────────────────────────
@app.route("/status/<job_id>")
def get_status(job_id):
    j = jobs.get(job_id)
    if not j:
        return jsonify({"error": "Job non trovato"}), 404
    return jsonify(j)

# ── YOUTUBE SEARCH ────────────────────────────────────────────────────────────
@app.route("/search", methods=["POST"])
def search_youtube():
    data = request.json or {}
    query = data.get("query", "").strip()
    if not query:
        return jsonify({"error": "Query mancante"}), 400
    try:
        ydl_opts = {"quiet": True, "extract_flat": False, "noplaylist": True}
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(f"ytsearch5:{query}", download=False)
        entries = info.get("entries", [])
        return jsonify({
            "results": [
                {
                    "title": e.get("title", ""),
                    "url": e.get("webpage_url") or e.get("url"),
                    "duration": e.get("duration"),
                    "uploader": e.get("uploader", ""),
                    "thumbnail": e.get("thumbnail", ""),
                }
                for e in entries if e
            ]
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/info", methods=["POST"])
def get_info():
    data = request.json or {}
    url = data.get("url", "").strip()
    if not url:
        return jsonify({"error": "URL mancante"}), 400
    try:
        ydl_opts = {"quiet": True, "extract_flat": True, "noplaylist": False}
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
        entries = info.get("entries", [info])
        return jsonify({
            "title": info.get("title", ""),
            "count": len(entries),
            "uploader": info.get("uploader", ""),
            "thumbnail": info.get("thumbnail", ""),
            "videos": [
                {"title": e.get("title", ""), "duration": e.get("duration")}
                for e in entries[:10]
            ],
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# ── DOWNLOAD ─────────────────────────────────────────────────────────────────
@app.route("/download", methods=["POST"])
def start_download():
    data = request.json or {}
    query = (data.get("query", "") or data.get("url", "")).strip()
    fmt = data.get("format", "mp3")
    quality = data.get("quality", "192")
    # Titolo/artista attesi: li manda la pagina (es. il titolo del sample). Servono
    # a NON consegnare un audio di un altro brano quando il download fallisce.
    # min_duration = secondo del sample nell'audio: serve a preferire una versione
    # abbastanza lunga da contenerlo.
    expected_title = (data.get("expected_title") or "").strip()
    expected_artist = (data.get("expected_artist") or "").strip()
    try:
        min_duration = float(data.get("min_duration") or 0)
    except (TypeError, ValueError):
        min_duration = 0.0
    if not query:
        return jsonify({"error": "URL/query mancante"}), 400
    jid = str(uuid.uuid4())[:8]
    jobs[jid] = {
        "status": "pending",
        "progress": {},
        "files": [],
        "filename": None,
        "yt_title": "",
        "error": "",
        "expected_title": expected_title,
    }
    threading.Thread(target=do_download,
                     args=(jid, query, fmt, quality, expected_title, expected_artist,
                           min_duration),
                     daemon=True).start()
    return jsonify({"job_id": jid})

# ── DOWNLOAD PLAYLIST ─────────────────────────────────────────────────────────
@app.route("/download/playlist", methods=["POST"])
def start_download_playlist():
    data = request.json or {}
    url = (data.get("url") or "").strip()
    fmt = data.get("format", "mp3")
    if not url:
        return jsonify({"error": "URL playlist mancante"}), 400
    jid = str(uuid.uuid4())[:8]
    jobs[jid] = {
        "status": "pending",
        "progress": {},
        "files": [],
        "filename": None,
        "yt_title": "",
        "error": "",
    }
    video = bool(data.get("video"))
    threading.Thread(target=do_download_playlist, args=(jid, url, fmt, video), daemon=True).start()
    return jsonify({"job_id": jid, "video": video})

# ── SEPARATE ─────────────────────────────────────────────────────────────────
@app.route("/separate", methods=["POST"])
def start_separate():
    data = request.json or {}
    filename = data.get("filename", "").strip()
    song_id = data.get("song_id")
    if not filename:
        return jsonify({"error": "Nome file mancante"}), 400
    jid = str(uuid.uuid4())[:8]
    jobs[jid] = {
        "status": "pending",
        "progress": {},
        "stems": [],
        "stem_folder": "",
        "error": "",
    }
    threading.Thread(target=do_stems, args=(jid, filename, song_id), daemon=True).start()
    return jsonify({"job_id": jid})

# ── TRIM ─────────────────────────────────────────────────────────────────────
@app.route("/trim", methods=["POST"])
def start_trim():
    data = request.json or {}
    filename = data.get("filename", "").strip()
    start = float(data.get("start", 0))
    end = float(data.get("end", 30))
    fmt = data.get("format", "mp3")
    if not filename:
        return jsonify({"error": "Filename mancante"}), 400
    if not FFMPEG:
        return jsonify({"error": "ffmpeg non trovato"}), 400
    if end <= start:
        return jsonify({"error": "Fine deve essere dopo l'inizio"}), 400
    jid = str(uuid.uuid4())[:8]
    jobs[jid] = {"status": "pending", "filename": None, "error": ""}
    threading.Thread(target=do_trim, args=(jid, filename, start, end, fmt), daemon=True).start()
    return jsonify({"job_id": jid})

# ── SCRAPE ────────────────────────────────────────────────────────────────────
@app.route("/scrape", methods=["POST"])
def start_scrape():
    data = request.json or {}
    artist = data.get("artist", "").strip()
    title = data.get("title", "").strip()
    if not artist or not title:
        return jsonify({"error": "Artista e titolo richiesti"}), 400
    jid = str(uuid.uuid4())[:8]
    jobs[jid] = {
        "status": "pending",
        "log": [],
        "progress": {},
        "result": None,
        "error": "",
        "use_yt_fallback": data.get("use_yt_fallback", True),
        "use_scoring": data.get("use_scoring", True),
    }
    threading.Thread(target=do_scrape, args=(jid, artist, title), daemon=True).start()
    return jsonify({"job_id": jid})

# ── SAVE PAIR (compatibile con scraper_index.html) ────────────────────────────
def upsert_sample_relation(conn, derivative_id, source_id, category, transformation,
                           trim_deriv, trim_source, notes, yt_deriv, yt_source):
    """Scrive il campionamento in `sample_relations` senza mai duplicarlo.

    Regola del 18/09/2026: per la stessa coppia (chi campiona, cosa è campionato)
    e la stessa categoria esiste UNA sola riga. Se la riga c'è già si AGGIORNA
    (così salvare due volte la stessa card, o rifinire categoria e timestamp, non
    crea doppioni), se non c'è si CREA. Ritorna `(id, creata)`.
    """
    riga = conn.execute(
        "SELECT id FROM sample_relations "
        "WHERE derivative_song_id=? AND source_song_id=? AND category=?",
        (derivative_id, source_id, category)).fetchone()
    if riga:
        conn.execute(
            """UPDATE sample_relations SET
                   transformation=?, yt_url_derivative=?, yt_url_source=?,
                   timestamp_derivative_start=?, timestamp_derivative_end=?,
                   timestamp_source_start=?, timestamp_source_end=?,
                   notes=?, verified_by_user=1
               WHERE id=?""",
            (transformation, yt_deriv, yt_source,
             trim_deriv.get("start"), trim_deriv.get("end"),
             trim_source.get("start"), trim_source.get("end"),
             notes, riga["id"]))
        return riga["id"], False
    rid = "rel_" + uuid.uuid4().hex[:12]
    conn.execute(
        """INSERT INTO sample_relations(
               id, derivative_song_id, source_song_id,
               category, transformation, yt_url_derivative, yt_url_source,
               timestamp_derivative_start, timestamp_derivative_end,
               timestamp_source_start, timestamp_source_end, notes, verified_by_user
           ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,1)""",
        (rid, derivative_id, source_id, category, transformation,
         yt_deriv, yt_source,
         trim_deriv.get("start"), trim_deriv.get("end"),
         trim_source.get("start"), trim_source.get("end"), notes))
    return rid, True


@app.route("/save_pair", methods=["POST"])
def save_pair():
    """Salva una coppia: dataset JSON legacy + tabella `sample_relations`.

    Fino al 18/09/2026 questo salvataggio poteva non lasciare traccia di sé: se la
    coppia era già nel dataset la funzione usciva PRIMA dell'INSERT (quindi nel
    tab Database il campione non compariva) e qualunque errore di SQLite finiva in
    un `except: pass` muto. La risposta ora dice esattamente cosa è stato scritto
    (`relation_id`, creata/aggiornata) e riporta l'errore vero.
    """
    data = request.json or {}
    song_x = data.get("song_x") or {}
    song_yi = data.get("song_yi") or {}
    trim_x = data.get("trim_x") or {"start": 0, "end": 30}
    trim_yi = data.get("trim_yi") or {"start": 0, "end": 30}
    category = data.get("category", "SAMPLE")
    transformation = data.get("transformation")
    notes = data.get("notes", "")
    if not song_x.get("title") or not song_yi.get("title") or not song_x.get("artist") or not song_yi.get("artist"):
        return jsonify({"error": "Campi obbligatori mancanti"}), 400
    # 1) dataset JSON legacy (compatibilità con scraper_index.html). Un errore
    #    qui NON deve più impedire la scrittura nel database.
    dataset, duplicato, dataset_error = None, False, None
    try:
        dataset = load_dataset()
        sid_x = get_or_create_song_dataset(dataset, song_x["title"], song_x["artist"], song_x.get("youtube_url", ""))
        sid_y = get_or_create_song_dataset(dataset, song_yi["title"], song_yi["artist"], song_yi.get("youtube_url", ""))
        new_pair = {
            "song_x": sid_x,
            "song_yi": sid_y,
            "trim_x": trim_x,
            "trim_yi": trim_yi,
            "category": category,
            "transformation": transformation,
            "notes": notes,
            "created_at": datetime.utcnow().isoformat() + "Z",
        }
        duplicato = is_duplicate(dataset, new_pair)
        if not duplicato:
            dataset["pairs"].append(new_pair)
            save_dataset(dataset)
    except Exception as e:
        dataset_error = str(e)
    # 2) il database: è la scrittura che conta. La coppia già presente nel dataset
    #    NON impedisce più di registrare il campionamento.
    did = sid2 = None
    nuova_x = nuova_y = True
    come_x = come_y = ""
    try:
        with get_db() as conn:
            # `resolve_or_create_song` riconosce una canzone GIÀ in libreria anche
            # quando l'artista è scritto in modo diverso (il caso «Eminem» vs
            # «Eminem / Nate Dogg» che ha creato il doppione di Till I Collapse):
            # in quel caso si usa la riga che c'è, e la risposta lo dice.
            did, nuova_x, come_x = resolve_or_create_song(
                conn, song_x["title"], song_x["artist"], song_x.get("youtube_url", ""))
            sid2, nuova_y, come_y = resolve_or_create_song(
                conn, song_yi["title"], song_yi["artist"], song_yi.get("youtube_url", ""))
            rel_id, creata = upsert_sample_relation(
                conn, did, sid2, category, transformation,
                trim_x, trim_yi, notes,
                song_x.get("youtube_url"), song_yi.get("youtube_url"))
    except Exception as e:
        # prima l'errore finiva in un `except: pass`: il salvataggio sembrava
        # riuscito e la riga non c'era. Ora si dice cosa non ha funzionato.
        return jsonify({"error": "Database: " + str(e), "saved": False,
                        "duplicate": duplicato}), 500

    # 3) «Una canzone che compare nel database deve poter essere ascoltata»
    #    (19/09/2026): se una delle due righe non ha il file locale, il download
    #    parte da sé e il file si aggancia a QUELLA riga (nessun doppione).
    downloads = {}
    for ruolo, sid_ in (("derivative", did), ("source", sid2)):
        if not sid_:
            continue
        job, motivo = avvia_download_canzone(sid_)
        if job:
            downloads[ruolo] = {"job_id": job, "song_id": sid_, "motivo": motivo}

    risposta = {
        "saved": not duplicato,
        "duplicate": duplicato,
        "total": (dataset or {}).get("meta", {}).get("count", 0),
        "relation_id": rel_id,
        "relation_created": creata,
        "relation_updated": not creata,
        "derivative": {"id": did, "title": song_x["title"], "artist": song_x["artist"],
                       "created": nuova_x, "matched_by": come_x},
        "source": {"id": sid2, "title": song_yi["title"], "artist": song_yi["artist"],
                   "created": nuova_y, "matched_by": come_y},
        "downloads": downloads,
    }
    if dataset_error:
        risposta["dataset_error"] = dataset_error
    return jsonify(risposta)

# ── DATASET STATS (compatibile con scraper_index.html) ───────────────────────
@app.route("/dataset/stats", methods=["GET"])
def dataset_stats():
    data = load_dataset()
    cats = {}
    for p in data["pairs"]:
        cats[p["category"]] = cats.get(p["category"], 0) + 1
    return jsonify({
        "total_pairs": data["meta"]["count"],
        "total_songs": len(data["songs"]),
        "by_category": cats,
    })

@app.route("/dataset", methods=["GET"])
def get_dataset():
    return jsonify(load_dataset())


# ── METADATA (BPM + Key) ──────────────────────────────────────────────────────
@app.route("/metadata", methods=["POST"])
def metadata_endpoint():
    data = request.json or {}
    artist = data.get("artist", "")
    title = data.get("title", "")
    filename = data.get("filename", "")
    yt_url = data.get("yt_url", "")
    if not artist or not title:
        return jsonify({"error": "Artist e title richiesti"}), 400
    result = get_metadata_hybrid(artist, title, filename or None)
    return jsonify({"metadata": result})

@app.route("/metadata/estimate", methods=["POST"])
def metadata_estimate_endpoint():
    """Stima BPM/Key solo dal file locale (niente scraping web)."""
    data = request.json or {}
    filename = data.get("filename", "")
    if not filename:
        return jsonify({"error": "filename richiesto"}), 400
    result = estimate_metadata_local(filename)
    return jsonify({"metadata": result})

# ── GENIUS ────────────────────────────────────────────────────────────────────
@app.route("/genius", methods=["POST"])
def genius_endpoint():
    data = request.json or {}
    artist = data.get("artist", "")
    title = data.get("title", "")
    result = fetch_genius(artist, title)
    if result and result.get("genius_url") and data.get("fetch_lyrics"):
        lyrics = fetch_genius_lyrics_text(result["genius_url"])
        if lyrics:
            result["lyrics"] = lyrics
    return jsonify(result or {})

# ── DB: SONGS ─────────────────────────────────────────────────────────────────
@app.route("/db/songs", methods=["GET"])
def db_list_songs():
    """Lista canzoni. Filtri opzionali:
       ?artist=<nome>  — tutte le canzoni dell'artista (gestisce anche multi-artista
                         tipo "Limp Bizkit feat. Eminem": cerca ogni parte).
       ?album=<nome>   — tutte le canzoni dell'album.
       ?title=<nome>   — filtro sul titolo.
    """
    artist_q = (request.args.get("artist") or "").strip()
    album_q  = (request.args.get("album")  or "").strip()
    title_q  = (request.args.get("title")  or "").strip()
    with get_db() as conn:
        sql  = "SELECT * FROM songs"
        where, params = [], []
        if artist_q:
            parts = [p.strip() for p in re.split(r"\s*(?:/|,|;|\||\+|&|feat\.?|ft\.?|with|x)\s*", artist_q.lower()) if p.strip()]
            if parts:
                where.append("(" + " OR ".join(["LOWER(artist) LIKE ?"] * len(parts)) + ")")
                params += ["%" + p + "%" for p in parts]
        if album_q:
            where.append("LOWER(album) LIKE ?")
            params.append("%" + album_q.lower() + "%")
        if title_q:
            where.append("LOWER(title) LIKE ?")
            params.append("%" + title_q.lower() + "%")
        if where:
            sql += " WHERE " + " AND ".join(where)
        sql += " ORDER BY artist, title"
        songs = rows2list(conn.execute(sql, params).fetchall())
        for s in songs:
            rels = conn.execute(
                "SELECT COUNT(*) as c FROM sample_relations WHERE derivative_song_id=? OR source_song_id=?",
                (s["id"], s["id"])
            ).fetchone()
            stems = conn.execute(
                "SELECT COUNT(*) as c FROM stem_tracks st JOIN stem_sessions ss ON st.session_id=ss.id WHERE ss.song_id=?",
                (s["id"],)
            ).fetchone()
            s["relation_count"] = rels["c"] if rels else 0
            s["stem_count"] = stems["c"] if stems else 0
    return jsonify(songs)

@app.route("/db/songs", methods=["POST"])
def db_add_song():
    data = request.json or {}
    if not data.get("title") or not data.get("artist"):
        return jsonify({"error": "title e artist richiesti"}), 400
    with get_db() as conn:
        sid = get_or_create_song_db(
            conn,
            data["title"],
            data["artist"],
            data.get("youtube_url", ""),
            data.get("local_file", ""),
            data.get("duration"),
        )
        if data.get("local_file"):
            conn.execute("UPDATE songs SET local_file=?, updated_at=datetime('now') WHERE id=?",
                         (data["local_file"], sid))
        if data.get("duration") is not None:
            conn.execute("UPDATE songs SET duration=?, updated_at=datetime('now') WHERE id=?",
                         (data["duration"], sid))
        allowed = [
            "album", "album_artist", "composer", "producers", "genre", "year", "release_date",
            "track_number", "disc_number", "compilation", "rating", "bpm", "musical_key",
            "play_count", "comment", "lyrics", "analyzed_status", "genius_url",
            "whosampled_url", "tunebat_url", "cover_art_path", "title_verified", "artist_verified",
            "bpm_verified", "key_verified", "lyrics_verified",
        ]
        for f in allowed:
            if f in data and data[f] is not None:
                conn.execute(f"UPDATE songs SET {f}=?, updated_at=datetime('now') WHERE id=?", (data[f], sid))
        s = row2dict(conn.execute("SELECT * FROM songs WHERE id=?", (sid,)).fetchone())
    # Una riga con solo i dati (senza file locale) non si può ascoltare: il
    # download parte da sé e il file si aggancia a QUESTA riga (19/09/2026).
    if not (data.get("local_file") or ""):
        job, motivo = avvia_download_canzone(sid)
        if job:
            s["download_job"], s["download_motivo"] = job, motivo
    return jsonify(s)

@app.route("/db/songs/<song_id>", methods=["GET"])
def db_get_song(song_id):
    with get_db() as conn:
        s = row2dict(conn.execute("SELECT * FROM songs WHERE id=?", (song_id,)).fetchone())
        if not s:
            return jsonify({"error": "Non trovata"}), 404
        s["relations_as_derivative"] = rows2list(conn.execute(
            "SELECT sr.*, ss.title as source_title, ss.artist as source_artist "
            "FROM sample_relations sr JOIN songs ss ON ss.id=sr.source_song_id "
            "WHERE sr.derivative_song_id=?", (song_id,)
        ).fetchall())
        s["relations_as_source"] = rows2list(conn.execute(
            "SELECT sr.*, sd.title as derivative_title, sd.artist as derivative_artist "
            "FROM sample_relations sr JOIN songs sd ON sd.id=sr.derivative_song_id "
            "WHERE sr.source_song_id=?", (song_id,)
        ).fetchall())
        s["stem_sessions"] = rows2list(conn.execute(
            "SELECT * FROM stem_sessions WHERE song_id=?", (song_id,)
        ).fetchall())
        for sess in s["stem_sessions"]:
            sess["tracks"] = rows2list(conn.execute(
                "SELECT * FROM stem_tracks WHERE session_id=?", (sess["id"],)
            ).fetchall())
    return jsonify(s)

@app.route("/db/songs/<song_id>", methods=["PUT"])
def db_update_song(song_id):
    data = request.json or {}
    # ⚠️ 18/09/2026: mancava «duration». Sia l'editor ✏️ Edit del Database
    # (`saveDbEditor`, che nello `fields` la durata ce l'ha) sia il modale
    # «Modifica info avanzata» del player la mandavano, e il PUT la buttava via
    # senza dire niente: il campo «Durata (s)» non si salvava.
    allowed = [
        "title", "artist", "album", "album_artist", "composer", "producers", "genre", "year", "release_date",
        "track_number", "disc_number", "compilation", "rating", "bpm", "musical_key", "play_count",
        "duration", "comment", "lyrics", "analyzed_status", "genius_url", "whosampled_url", "youtube_url",
        "tunebat_url", "cover_art_path", "local_file", "video_file", "title_verified", "artist_verified",
        "bpm_verified", "key_verified", "lyrics_verified",
    ]
    with get_db() as conn:
        for f in allowed:
            if f in data:
                conn.execute(f"UPDATE songs SET {f}=?, updated_at=datetime('now') WHERE id=?", (data[f], song_id))
        s = row2dict(conn.execute("SELECT * FROM songs WHERE id=?", (song_id,)).fetchone())
    return jsonify(s or {"error": "Non trovata"})

@app.route("/db/songs/<song_id>", methods=["DELETE"])
def db_delete_song(song_id):
    with get_db() as conn:
        conn.execute("DELETE FROM songs WHERE id=?", (song_id,))
    return jsonify({"ok": True})

@app.route("/db/songs/<song_id>/ensure_file", methods=["POST"])
def db_song_ensure_file(song_id):
    """Scarica in `downloads/` il file locale della riga che non ce l'ha.

    È quello che fa da sé anche `/save_pair`: la riga resta la stessa e il file
    le viene agganciato (`local_file`), senza creare doppioni. Il pulsante ⬇
    della tabella del database chiama qui; si segue con `/status/<job_id>`.
    """
    forzato = bool((request.json or {}).get("forzato"))
    job, motivo = avvia_download_canzone(song_id, forzato=forzato)
    return jsonify({"avviato": bool(job), "job_id": job, "motivo": motivo, "song_id": song_id})


@app.route("/db/songs/<song_id>/ensure_video", methods=["POST"])
def db_song_ensure_video(song_id):
    """Scarica in `videos/` il VIDEO (MP4) del brano (pulsante 🎬 Video → «Da YouTube»).

    Come `/db/songs/<id>/ensure_file` ma per il video: la riga resta la stessa e
    il file le viene agganciato (`video_file`). Si segue con `/status/<job_id>`.
    """
    forzato = bool((request.json or {}).get("forzato"))
    job, motivo = avvia_download_video_canzone(song_id, forzato=forzato)
    return jsonify({"avviato": bool(job), "job_id": job, "motivo": motivo, "song_id": song_id})

@app.route("/db/songs/<song_id>/video", methods=["POST"])
def db_song_set_video(song_id):
    """Aggancia un video alla riga: caricato dal COMPUTER o già in `videos/`.

    Due modi, stessa rotta:
    - multipart con `file` (il pulsante «📂 Dal computer») → il file si salva in
      `videos/` con un nome sicuro e unico;
    - JSON `{"filename": "…"}` → si aggancia un video che è già in `videos/`.
    """
    with get_db() as conn:
        s = row2dict(conn.execute("SELECT id FROM songs WHERE id=?", (song_id,)).fetchone())
    if not s:
        return jsonify({"error": "Canzone non trovata"}), 404

    upload = request.files.get("file")
    if upload:
        nome = nome_video_unico(nome_video_sicuro(upload.filename))
        upload.save(os.path.join(VID_DIR, nome))
        origine = "caricato dal computer"
    else:
        richiesto = os.path.basename(str((request.json or {}).get("filename") or "").strip())
        if not richiesto:
            return jsonify({"error": "Serve un file (o il nome di un video già in videos/)"}), 400
        if not file_video_valido(richiesto):
            return jsonify({"error": f"Video non trovato in videos/: {richiesto}"}), 404
        nome = richiesto
        origine = "scelto fra i video dell'app"

    with get_db() as conn:
        conn.execute("UPDATE songs SET video_file=?, updated_at=datetime('now') WHERE id=?",
                     (nome, song_id))
        riga = row2dict(conn.execute("SELECT * FROM songs WHERE id=?", (song_id,)).fetchone())
    print(f"[db {song_id}] video agganciato ({origine}): {nome}")
    return jsonify({"ok": True, "video_file": nome, "origine": origine, "song": riga})

@app.route("/db/songs/<song_id>/video", methods=["DELETE"])
def db_song_delete_video(song_id):
    """Toglie il video dalla riga: il FILE va in `.trash/` (recuperabile), la
    colonna `video_file` si svuota. La riga e l'audio non si toccano."""
    with get_db() as conn:
        s = row2dict(conn.execute("SELECT video_file FROM songs WHERE id=?",
                                  (song_id,)).fetchone())
        if not s:
            return jsonify({"error": "Canzone non trovata"}), 404
        nome = s.get("video_file") or ""
        spostato = ""
        percorso = os.path.join(VID_DIR, os.path.basename(nome)) if nome else ""
        if percorso and os.path.isfile(percorso) and _dentro_la_cartella(VID_DIR, percorso):
            try:
                spostato = move_to_trash(percorso)
            except OSError as e:
                return jsonify({"error": f"Non riesco a spostare il file: {e}"}), 500
        conn.execute("UPDATE songs SET video_file=NULL, updated_at=datetime('now') "
                     "WHERE id=?", (song_id,))
    print(f"[db {song_id}] video tolto dalla riga ({nome}) → {spostato or 'file già assente'}")
    return jsonify({"ok": True, "video_file": None, "spostato_in": spostato})


# ── MINIATURA E DATI DEL VIDEO PER LE RIGHE GIÀ IN LIBRERIA (19/09/2026) ──────
# Il pulsante 🖼 YT di ogni riga usa `POST /db/songs/<id>/recupera_youtube`; il
# pannello del tab 🗄️ Database usa `GET /db/recupera_youtube` (l'elenco dei
# candidati, che NON tocca la rete) e `POST /db/recupera_youtube` (il blocco).
@app.route("/db/songs/<song_id>/recupera_youtube", methods=["POST"])
def db_song_recupera_youtube(song_id):
    """Dati del video + miniatura su UNA riga già in libreria (pulsante 🖼 YT).

    JSON opzionale: `{"forzato": true}` rifà anche la copertina se c'è già,
    `{"video": true}` scarica ANCHE l'MP4. Il video si prende dal link della riga
    o dal suo id; solo se non c'è né l'uno né l'altro si cerca per «artista -
    titolo», e la risposta lo dice (`cercato: true`).
    """
    dati = request.json or {}
    with get_db() as conn:
        esiste = conn.execute("SELECT 1 FROM songs WHERE id=?", (song_id,)).fetchone()
    if not esiste:
        return jsonify({"ok": False, "error": "Canzone non trovata"}), 404
    res = recupera_dati_video(song_id, forzato=bool(dati.get("forzato")),
                              video=bool(dati.get("video")))
    return jsonify(res), (200 if res.get("ok") else 502)


@app.route("/db/recupera_youtube", methods=["GET"])
def db_recupera_youtube_elenco():
    """I candidati al recupero (sola lettura: NESSUNA chiamata a YouTube).

    `{"totale": N, "righe": […], "senza_link": M}`: le righe con un link/id a cui
    manca la miniatura o i dati del video (ogni riga porta `manca`), e quante
    righe in più si potrebbero fare SOLO col pulsante — quelle senza link, dove
    il video andrebbe CERCATO per «artista - titolo» (e può uscire quello
    sbagliato: il caso «Public Enemy #1» del 18/09/2026).
    """
    righe, senza_link = righe_da_recuperare(solo_con_link=True)
    return jsonify({"totale": len(righe), "righe": righe[:200], "senza_link": senza_link})


@app.route("/db/recupera_youtube", methods=["POST"])
def db_recupera_youtube_avvia():
    """Recupero in blocco. JSON: `{"limite": N}` (0 = tutte), `{"forzato": true}`.

    Risponde subito col job da seguire (`/status/<job_id>`): il lavoro è in
    un thread, e fra una riga e l'altra c'è una pausa per non farsi bloccare.
    """
    dati = request.json or {}
    job, motivo = avvia_recupero_youtube(limite=dati.get("limite") or 0,
                                         forzato=bool(dati.get("forzato")))
    return jsonify({"avviato": bool(job), "job_id": job, "motivo": motivo})


@app.route("/covers")
def list_cover_files():
    """Le copertine che ci sono in `covers/` (per il selettore «📁 copertine»)."""
    files = []
    for f in sorted(os.listdir(COVERS_DIR)):
        if f.startswith(".") or not nome_cover_archivio(f):
            continue
        fp = os.path.join(COVERS_DIR, f)
        if not os.path.isfile(fp):
            continue
        files.append({"name": f, "size": os.path.getsize(fp),
                      "ext": os.path.splitext(f)[1].lower().lstrip(".")})
    return jsonify(files)

@app.route("/db/songs/<song_id>/cover", methods=["POST"])
def db_song_set_cover(song_id):
    """La COPERTINA di una canzone: caricata dal computer, scelta fra quelle già in
    `covers/` o presa dalla MINIATURA del video YouTube (18/09/2026).

    Tre modi, stessa rotta:
    - multipart con `file` (pulsante «📂 Carica dal computer») → si salva in
      `covers/<id>.<ext>` (una sola immagine per canzone: la vecchia di un altro
      formato va in `.trash/`);
    - JSON `{"filename": "song_…jpg"}` → si usa una copertina che c'è già;
    - JSON `{"da": "youtube"}` → la miniatura del video salvata col download
      della playlist (`yt_thumbnail`).
    """
    with get_db() as conn:
        s = row2dict(conn.execute("SELECT * FROM songs WHERE id=?", (song_id,)).fetchone())
    if not s:
        return jsonify({"error": "Canzone non trovata"}), 404

    upload = request.files.get("file")
    origine = ""
    if upload:
        dati = upload.read()
        ext = _estensione_da_nome_o_mime(upload.filename, upload.mimetype)
        origine = "caricata dal computer"
    else:
        data = request.json or {}
        if data.get("da") == "youtube":
            # Gemella automatica di questa strada: `copertina_da_miniatura()`
            # (19/09/2026), usata dal download per completare la riga da sé. Qui
            # però si è a mano, quindi si può anche RIFARE la copertina (`forzato`).
            url = (s.get("yt_thumbnail") or "").strip()
            if not url:
                return jsonify({"error": "Questa canzone non ha la miniatura del video "
                                         "(arriva col download della playlist)"}), 400
            dati, ext = _scarica_immagine(url), _cover_ext_from_url(url)
            origine = "miniatura del video YouTube"
            if not dati:
                return jsonify({"error": "Non sono riuscito a scaricare la miniatura"}), 502
        elif data.get("filename"):
            richiesto = str(data["filename"]).strip()
            if not nome_cover_archivio(richiesto):
                return jsonify({"error": "Nome di copertina non valido"}), 400
            percorso = _cover_local_path(richiesto)
            if not os.path.isfile(percorso) or not _dentro_la_cartella(COVERS_DIR, percorso):
                return jsonify({"error": f"Copertina non trovata in covers/: {richiesto}"}), 404
            with get_db() as conn:
                conn.execute("UPDATE songs SET cover_art_path=?, updated_at=datetime('now') "
                             "WHERE id=?", (richiesto, song_id))
                riga = row2dict(conn.execute("SELECT * FROM songs WHERE id=?", (song_id,)).fetchone())
            print(f"[db {song_id}] copertina scelta fra quelle in covers/: {richiesto}")
            return jsonify({"ok": True, "cover_art_path": richiesto,
                            "origine": "scelta fra le copertine dell'app", "song": riga})
        else:
            return jsonify({"error": "Serve un file, un «filename» o «da: youtube»"}), 400

    nome, errore = salva_copertina_bytes(song_id, dati, ext)
    if errore:
        return jsonify({"error": errore}), 400
    with get_db() as conn:
        conn.execute("UPDATE songs SET cover_art_path=?, updated_at=datetime('now') WHERE id=?",
                     (nome, song_id))
        riga = row2dict(conn.execute("SELECT * FROM songs WHERE id=?", (song_id,)).fetchone())
    print(f"[db {song_id}] copertina agganciata ({origine}): {nome}")
    return jsonify({"ok": True, "cover_art_path": nome, "origine": origine, "song": riga})

@app.route("/db/songs/<song_id>/cover", methods=["DELETE"])
def db_song_delete_cover(song_id):
    """Toglie la copertina dalla riga: il FILE va in `.trash/`, la colonna si svuota.

    ⚠️ Nel cesto va solo la copertina **sua** (`<id>.<ext>`): una riga può puntare a
    una copertina che c'è già in `covers/` (magari di un'altra canzone), e quella non
    si tocca — si svuota solo il campo (18/09/2026: la prova dal vivo ha mandato nel
    cesto la copertina di un'altra canzone, poi rimessa a posto a mano).
    """
    with get_db() as conn:
        s = row2dict(conn.execute("SELECT cover_art_path FROM songs WHERE id=?",
                                  (song_id,)).fetchone())
        if not s:
            return jsonify({"error": "Canzone non trovata"}), 404
        nome = s.get("cover_art_path") or ""
        sid_pulito = re.sub(r'[^A-Za-z0-9_]', '', str(song_id or "")) or "cover"
        sua = bool(nome) and nome.startswith(f"{sid_pulito}.")
        percorso = _cover_local_path(nome)
        spostato, lasciato = "", ""
        if nome and os.path.isfile(percorso) and _dentro_la_cartella(COVERS_DIR, percorso):
            if sua:
                try:
                    spostato = move_to_trash(percorso)
                except OSError as e:
                    return jsonify({"error": f"Non riesco a spostare il file: {e}"}), 500
            else:
                lasciato = nome     # è la copertina di un'altra canzone: resta dov'è
        conn.execute("UPDATE songs SET cover_art_path=NULL, updated_at=datetime('now') "
                     "WHERE id=?", (song_id,))
    print(f"[db {song_id}] copertina tolta ({nome or 'nessuna'}) → "
          f"{spostato or ('lasciato ' + lasciato if lasciato else 'file già assente')}")
    return jsonify({"ok": True, "cover_art_path": None, "spostato_in": spostato,
                    "file_lasciato": lasciato})


# ── DB: UNISCI DUE RIGHE CHE SONO LA STESSA CANZONE ──────────────────────────
@app.route("/db/songs/merge", methods=["POST"])
def db_merge_songs():
    """Unisce due righe che sono LA STESSA canzone (doppione) in una sola.

    Body: `{"keep": "song_…", "drop": "song_…"}`.
      * i campionamenti (e gli stem) della riga da cancellare passano a quella
        che resta;
      * i campi VUOTI della riga che resta si completano con quelli dell'altra
        (liriche, link Genius/WhoSampled, copertina, verdetti, crediti…): quello
        che c'è già non viene toccato;
      * il `local_file` si prende solo se la riga che resta è senza file — o se
        il suo file non esiste più in `downloads/` e quello dell'altra sì;
      * infine la riga doppia si cancella.
    Serve per i doppioni nati PRIMA del confronto tollerante: caso vero
    «Till I Collapse» di Eminem (riga vecchia col file + riga nuova con le
    liriche e i link).
    """
    data = request.json or {}
    keep = (data.get("keep") or "").strip()
    drop = (data.get("drop") or "").strip()
    if not keep or not drop:
        return jsonify({"error": "keep e drop richiesti"}), 400
    if keep == drop:
        return jsonify({"error": "keep e drop sono la stessa riga"}), 400
    with get_db() as conn:
        righe = {r["id"]: row2dict(r) for r in conn.execute(
            "SELECT * FROM songs WHERE id IN (?,?)", (keep, drop)).fetchall()}
        if keep not in righe or drop not in righe:
            return jsonify({"error": "una delle due righe non esiste"}), 404
        colonne = [c[1] for c in conn.execute("PRAGMA table_info(songs)").fetchall()]
        # 1) quello che era agganciato alla riga doppia passa a quella che resta
        spostati = {}
        for tabella, campo in (("sample_relations", "derivative_song_id"),
                               ("sample_relations", "source_song_id"),
                               ("stem_sessions", "song_id"),
                               ("audio_analyses", "song_id")):
            cur = conn.execute(f"UPDATE {tabella} SET {campo}=? WHERE {campo}=?",
                               (keep, drop))
            if cur.rowcount:
                spostati[f"{tabella}.{campo}"] = cur.rowcount
        # 2) se dopo lo spostamento la stessa coppia+categoria compare due volte,
        #    resta una sola riga di campionamento (la più recente)
        rel_doppie = 0
        for d in conn.execute(
                "SELECT GROUP_CONCAT(id) ids FROM sample_relations "
                "GROUP BY derivative_song_id, source_song_id, category "
                "HAVING COUNT(*)>1").fetchall():
            for vecchia in (d["ids"] or "").split(",")[:-1]:
                conn.execute("DELETE FROM sample_relations WHERE id=?", (vecchia,))
                rel_doppie += 1
        # 3) i campi vuoti della riga che resta si completano con l'altra
        keepv, dropv = righe[keep], righe[drop]
        file_keep_ok = file_locale_valido(keepv.get("local_file"))
        completati = []
        for c in colonne:
            if c in ("id", "created_at", "updated_at"):
                continue
            nuovo = dropv.get(c)
            if nuovo in (None, ""):
                continue
            if c == "local_file":
                if file_keep_ok:
                    continue        # il file che c'è funziona: non si sostituisce
            elif keepv.get(c) not in (None, ""):
                continue            # non si sovrascrive quello che c'è
            conn.execute(f"UPDATE songs SET {c}=?, updated_at=datetime('now') WHERE id=?",
                         (nuovo, keep))
            completati.append(c)
        conn.execute("DELETE FROM songs WHERE id=?", (drop,))
        # 4) se la riga che resta ora HA un file locale, i verdetti presi quando il
        #    file mancava non valgono più: dicono «manca il file locale in
        #    downloads/», cioè una cosa falsa. Si azzerano (col motivo del perché),
        #    così la prossima Verifica li rifà invece di mostrare una bugia.
        azzerati = []
        riga_finale = conn.execute("SELECT local_file FROM songs WHERE id=?",
                                   (keep,)).fetchone()
        if riga_finale and file_locale_valido(riga_finale["local_file"]):
            for prefisso in ("audio_match", "ws_audio", "testo"):
                v = conn.execute(
                    f"SELECT {prefisso}_esito AS esito, {prefisso}_motivo AS motivo "
                    "FROM songs WHERE id=?", (keep,)).fetchone()
                if v and "manca il file locale" in (v["motivo"] or ""):
                    conn.execute(
                        f"UPDATE songs SET {prefisso}_esito=NULL, {prefisso}_at=NULL, "
                        f"{prefisso}_motivo=?, updated_at=datetime('now') WHERE id=?",
                        ("verdetto azzerato: il file locale ora c'è, la Verifica lo rifarà",
                         keep))
                    azzerati.append(prefisso)
        campione = row2dict(conn.execute("SELECT * FROM songs WHERE id=?", (keep,)).fetchone())
    return jsonify({"ok": True, "keep": keep, "drop": drop, "campione": campione,
                    "campi_completati": completati, "agganci_spostati": spostati,
                    "campioni_doppi_rimossi": rel_doppie, "verdetti_azzerati": azzerati})


# ── DB: RELATIONS ─────────────────────────────────────────────────────────────
@app.route("/db/relations", methods=["GET"])
def db_list_relations():
    with get_db() as conn:
        rels = rows2list(conn.execute("""
            SELECT sr.*,
                   sd.title as derivative_title, sd.artist as derivative_artist,
                   ss.title as source_title, ss.artist as source_artist
            FROM sample_relations sr
            JOIN songs sd ON sd.id = sr.derivative_song_id
            JOIN songs ss ON ss.id = sr.source_song_id
            ORDER BY sr.created_at DESC
        """).fetchall())
    return jsonify(rels)

@app.route("/db/relations/<rel_id>", methods=["DELETE"])
def db_delete_relation(rel_id):
    with get_db() as conn:
        conn.execute("DELETE FROM sample_relations WHERE id=?", (rel_id,))
    return jsonify({"ok": True})

# ── DB: SCHEDA CANZONE (stem · remix e cover · campionamenti) ────────────────
# La pagina /scheda (scheda.html) mette insieme TUTTO quello che il database sa
# di una canzone: le tracce separate (stem_sessions + stem_tracks), i remix e le
# cover e i campionamenti (sample_relations) e le analisi audio (audio_analyses).
# Le regole con cui una relazione finisce in un gruppo stanno qui in funzioni
# PURE, provate da test_scheda_canzone.py: così la pagina e il backend restano
# d'accordo su cosa è un sample, un remix e una cover.

# Categorie con cui il database descrive una relazione. Quelle "cover" sono
# quelle del pannello Salva coppia di index (2).html (VOCAL_COVER, FULL_REMAKE,
# INSTRUMENT_REMAKE); SAMPLE, STEM_REUSE e BEAT_CHANGE sono campionamenti.
REL_CATEGORIE_COVER = {"COVER", "COVERS", "VOCAL_COVER", "FULL_REMAKE",
                       "INSTRUMENT_REMAKE", "REINTERPRETATION", "RIFACIMENTO"}

_RE_MARCATORE_REMIX = re.compile(r"\b(remix|rmx|remixed|rework|bootleg)\b")
_RE_MARCATORE_COVER = re.compile(r"\b(cover|covered|covers|karaoke|reinterpretation|reinterpretazione|rifacimento)\b")
# Marcatori di variante nel titolo ("X (Remix)", "X [Cover]", "X Live"): servono
# a riconoscere le altre versioni dello stesso brano già in libreria.
_RE_VARIANTE_TITOLO = re.compile(r"\b(remix|rmx|cover|covered|karaoke|instrumental|strumentale|reinterpretation|rework|live|acoustic|demo)\b")
# Annotazioni fra parentesi da BUTTARE via nel titolo base: se dentro le
# parentesi c'è una di queste parole la parentesi è un'annotazione («(Remix)»,
# «[HQ Lyrics]», «(Official Video)», «(feat. Tizio)»); altrimenti le parole
# contano e restano («Sam (Is Dead)» → «sam is dead»).
_RE_PARENTESI_ANNOTAZIONE = re.compile(
    r"(remix|rmx|cover|live|acoustic|instrumental|strumentale|karaoke|demo|remaster|"
    r"version|edit|lyrics|testo|official|video|audio|visualizer|feat\.?|ft\.?|with|"
    r"prod\.?|explicit|clean|hq|hd|4k)", re.I)


def classifica_relazione(rel, direzione="derivative"):
    """In quale gruppo della scheda va questa relazione: "remix", "cover" o "sample".

    Guarda i campi con cui il database descrive la relazione (`category`,
    `relation_type`, `transformation`, `notes`) e — solo quando il brano che
    deriva è l'ALTRO (`direzione="source"`) — anche i marcatori nel titolo
    dell'altro brano: un "(Remix)" nella canzone che campiona la nostra È un
    remix di questa, mentre un "(Remix)" nel brano CAMPIONATO non dice niente
    sul nostro brano (è solo il titolo della fonte).
    """
    testo = " ".join(str(rel.get(k) or "") for k in
                     ("category", "relation_type", "transformation", "notes")).lower()
    categoria = str(rel.get("category") or "").strip().upper()
    if _RE_MARCATORE_REMIX.search(testo):
        return "remix"
    if categoria in REL_CATEGORIE_COVER or _RE_MARCATORE_COVER.search(testo):
        return "cover"
    titolo = str(rel.get("other_title") or "").lower()
    if direzione == "source":
        if _RE_MARCATORE_REMIX.search(titolo):
            return "remix"
        if _RE_MARCATORE_COVER.search(titolo):
            return "cover"
    return "sample"


def ruolo_relazione(gruppo, direzione):
    """La frase da mostrare sulla riga: chi fa cosa, vista da questa canzone."""
    derivato = direzione == "derivative"
    if gruppo == "remix":
        return "questa canzone è un remix dell'altra" if derivato else "l'altra è un remix di questa"
    if gruppo == "cover":
        return "questa canzone è una cover dell'altra" if derivato else "l'altra è una cover di questa"
    return "questa canzone campiona l'altra" if derivato else "l'altra campiona questa"


def titolo_base(titolo):
    """Titolo ridotto all'osso per confrontare le versioni dello stesso brano.

    Vengono tolte SOLO le annotazioni fra parentesi («(Remix)», «(feat. Tizio)»,
    «[HQ Lyrics]», «(Official Video)»…), non tutto quello che sta fra parentesi:
    «Sam (Is Dead)» resta «sam is dead» (le parole contano), mentre «Mosh
    (Remix)», «MOSH [Live]» e «Eminem - Without Me (Official Video)» diventano
    «mosh» e «eminem without me». Poi via la punteggiatura e i marcatori sciolti.
    """
    t = str(titolo or "").lower()

    def _dentro(m):
        contenuto = m.group(1)
        return " " if _RE_PARENTESI_ANNOTAZIONE.search(contenuto) else " " + contenuto + " "

    t = re.sub(r"[\(\[\{]([^\)\]\}]*)[\)\]\}]", _dentro, t)
    t = _RE_VARIANTE_TITOLO.sub(" ", t)
    t = re.sub(r"[^a-z0-9]+", " ", t)
    return " ".join(t.split())


def artisti_diversi(a, b):
    """True se i due crediti indicano artisti diversi (confronto per parti:
    «Eminem / D12» e «D12» condividono D12, quindi non sono diversi)."""
    def parti(x):
        return {p.strip().lower() for p in
                re.split(r"\s*(?:/|,|;|\||\+|&)\s*", str(x or "")) if p.strip()}
    pa, pb = parti(a), parti(b)
    return bool(pa and pb and not (pa & pb))


def possibili_varianti(song, brani, limite=25):
    """Le altre versioni dello stesso brano già in libreria, riconosciute dal titolo.

    Il database non tiene le cover e i remix in una tabella propria: o li racconta
    una relazione (sample_relations), oppure si riconoscono dal titolo. Qui si
    cercano i brani con lo stesso titolo base che hanno un marcatore di variante
    («(Remix)», «[Cover]», «Live»…) o un artista diverso: sono CANDIDATI da
    guardare a occhio, non una verità del database (per questo la pagina li tiene
    in un blocco separato e dice sempre il perché).
    """
    base = titolo_base(song.get("title"))
    if len(base) < 3:
        return []
    nostro_artista = song.get("artist") or ""
    segnaposto = is_placeholder_artist(nostro_artista)
    fuori = []
    for b in brani:
        if str(b.get("id")) == str(song.get("id")):
            continue
        if titolo_base(b.get("title")) != base:
            continue
        marcatori = sorted({m for m in _RE_VARIANTE_TITOLO.findall(str(b.get("title") or "").lower())})
        motivo = ""
        if marcatori:
            motivo = "nel titolo: " + " / ".join(marcatori)
        elif not segnaposto and artisti_diversi(nostro_artista, b.get("artist")):
            motivo = "artista diverso: " + str(b.get("artist") or "")
        if not motivo:
            continue
        fuori.append({
            "id": b.get("id"), "title": b.get("title"), "artist": b.get("artist"),
            "album": b.get("album"), "year": b.get("year"),
            "local_file": b.get("local_file"), "motivo": motivo,
        })
    fuori.sort(key=lambda x: (str(x.get("artist") or "").lower(), str(x.get("title") or "").lower()))
    return fuori[:limite]


def _url_stem(folder, filename):
    """URL di uno stem (cartella e nome possono avere spazi e punti: vanno quotati)."""
    return ("/stream-stem/%s/%s" % (urllib.parse.quote(str(folder or "")),
                                    urllib.parse.quote(str(filename or ""))),
            "/download-stem/%s/%s" % (urllib.parse.quote(str(folder or "")),
                                      urllib.parse.quote(str(filename or ""))))


def _scheda_stem(conn, song):
    """Gli stem del brano: sessioni e tracce dal database + quello che c'è su disco.

    `stem_sessions` dice come è stata fatta la separazione (Demucs) e
    `stem_tracks` elenca i file (voce, batteria, basso, altro). I file vengono
    anche controllati su disco (`exists`): se qualcuno li ha cancellati la
    pagina lo dice invece di far cliccare su un player vuoto.
    """
    sessions = rows2list(conn.execute(
        "SELECT * FROM stem_sessions WHERE song_id=? ORDER BY created_at DESC", (song["id"],)))
    totale = mancanti = 0
    registrati = set()
    for sess in sessions:
        tracce = rows2list(conn.execute(
            "SELECT * FROM stem_tracks WHERE session_id=? ORDER BY stem_type", (sess["id"],)))
        for t in tracce:
            percorso = str(t.get("file_path") or "")
            t["filename"] = os.path.basename(percorso)
            t["folder"] = os.path.basename(os.path.dirname(percorso))
            t["exists"] = bool(percorso) and os.path.exists(percorso)
            t["size_on_disk"] = os.path.getsize(percorso) if t["exists"] else None
            if t["exists"]:
                t["url"], t["download_url"] = _url_stem(t["folder"], t["filename"])
                registrati.add(t["filename"])
            totale += 1
            if not t["exists"]:
                mancanti += 1
        sess["tracks"] = tracce
    # Cartella su disco: Demucs la nomina come il file di partenza senza
    # estensione. Serve a mostrare gli stem separati anche quando il job è
    # partito senza `song_id` (quindi senza riga in stem_sessions).
    disco = None
    base_file = os.path.splitext(os.path.basename(str(song.get("local_file") or "")))[0]
    if base_file:
        cartella = os.path.join(STEMS_DIR, "htdemucs", base_file)
        if os.path.isdir(cartella):
            files = []
            for nome in sorted(os.listdir(cartella)):
                percorso = os.path.join(cartella, nome)
                if not os.path.isfile(percorso):
                    continue
                url, dl = _url_stem(base_file, nome)
                files.append({
                    "filename": nome,
                    "stem_type": os.path.splitext(nome)[0].lower(),
                    "size_on_disk": os.path.getsize(percorso),
                    "registrato": nome in registrati,
                    "url": url, "download_url": dl,
                })
            if files:
                disco = {"folder": base_file, "files": files,
                         "non_registrati": [f["filename"] for f in files if not f["registrato"]]}
    return {
        "sessions": sessions,
        "count_tracks": totale,
        "count_missing": mancanti,
        "on_disk": disco,
        "has_stems": bool(totale or (disco and disco["files"])),
    }


@app.route("/db/songs/<song_id>/scheda", methods=["GET"])
def db_song_scheda(song_id):
    """Tutto quello che il database sa di una canzone: stem, remix e cover,
    campionamenti WhoSampled e analisi audio. Usato dalla pagina /scheda."""
    with get_db() as conn:
        song = row2dict(conn.execute("SELECT * FROM songs WHERE id=?", (song_id,)).fetchone())
        if not song:
            return jsonify({"error": "Non trovata"}), 404
        stems = _scheda_stem(conn, song)
        altrove = ("sr.*, alt.title AS other_title, alt.artist AS other_artist, "
                   "alt.year AS other_year, alt.id AS other_id, "
                   "alt.local_file AS other_local_file, alt.whosampled_url AS other_whosampled_url")
        derivate = rows2list(conn.execute(
            "SELECT " + altrove + " FROM sample_relations sr JOIN songs alt ON alt.id=sr.source_song_id "
            "WHERE sr.derivative_song_id=? ORDER BY alt.artist, alt.title", (song_id,)))
        fonti = rows2list(conn.execute(
            "SELECT " + altrove + " FROM sample_relations sr JOIN songs alt ON alt.id=sr.derivative_song_id "
            "WHERE sr.source_song_id=? ORDER BY alt.artist, alt.title", (song_id,)))
        gruppi = {"samples_used": [], "sampled_by": [], "remixes": [], "covers": []}
        for riga, direzione in ([(r, "derivative") for r in derivate] +
                                [(r, "source") for r in fonti]):
            riga["direzione"] = direzione
            riga["gruppo"] = classifica_relazione(riga, direzione)
            riga["ruolo"] = ruolo_relazione(riga["gruppo"], direzione)
            if riga["gruppo"] == "remix":
                gruppi["remixes"].append(riga)
            elif riga["gruppo"] == "cover":
                gruppi["covers"].append(riga)
            elif direzione == "derivative":
                gruppi["samples_used"].append(riga)
            else:
                gruppi["sampled_by"].append(riga)
        brani = rows2list(conn.execute(
            "SELECT id, title, artist, album, year, local_file FROM songs"))
        varianti = possibili_varianti(song, brani)
        analisi = rows2list(conn.execute(
            "SELECT * FROM audio_analyses WHERE song_id=? ORDER BY analyzed_at DESC", (song_id,)))
    return jsonify({
        "song": song,
        "stems": stems,
        "samples_used": gruppi["samples_used"],
        "sampled_by": gruppi["sampled_by"],
        "remixes": gruppi["remixes"],
        "covers": gruppi["covers"],
        "varianti": varianti,
        "analyses": analisi,
        "whosampled_url": song.get("whosampled_url") or "",
        "counts": {
            "stem_sessions": len(stems["sessions"]),
            "stem_tracks": stems["count_tracks"],
            "stem_missing": stems["count_missing"],
            "samples_used": len(gruppi["samples_used"]),
            "sampled_by": len(gruppi["sampled_by"]),
            "remixes": len(gruppi["remixes"]),
            "covers": len(gruppi["covers"]),
            "varianti": len(varianti),
            "analyses": len(analisi),
        },
    })

# ── DB: STEM CARICATI A MANO (📂 una cartella di tracce già separate) ─────────
# Il pulsante ✂️ Stem fa separare le tracce a Demucs; qui invece le tracce
# arrivano già separate da fuori (violino, pianoforte, archi…): la pagina /scheda
# manda la cartella scelta dall'utente, il backend copia i file nella cartella di
# quella canzone e scrive una riga per traccia in `stem_tracks`.
@app.route("/db/songs/<song_id>/stems/import", methods=["POST"])
def import_stems(song_id):
    """📂 Salva nel database una cartella di stem caricata a mano.

    I file arrivano in multipart (`files`, uno per traccia) come li manda il
    selettore di cartella di /scheda. L'etichetta di ogni traccia
    (`stem_tracks.stem_type`) è quella riconosciuta nel nome del file
    (`strumento_da_nomefile`: «canzone - Violino.mp3» → «violino») oppure quella
    corretta a mano nella pagina, che manda `etichette` (JSON, nello stesso
    ordine dei file).

    I file si copiano in `stems/htdemucs/<base del file locale>/` — la stessa
    cartella di Demucs — e le tracce di UNA canzone stanno in UNA sola sessione
    (`model_name='manuale'`): ricaricare la stessa cartella non crea doppioni,
    aggiorna le tracce già presenti (stesso nome file). I file non audio si
    saltano e vengono elencati in `skipped`.
    """
    files = request.files.getlist("files")
    if not files:
        return jsonify({"error": "Nessun file: scegli la cartella delle tracce"}), 400
    try:
        etichette = json.loads(request.form.get("etichette") or "[]")
    except (TypeError, ValueError):
        etichette = []
    if not isinstance(etichette, list):
        etichette = []

    with get_db() as conn:
        song = row2dict(conn.execute("SELECT * FROM songs WHERE id=?", (song_id,)).fetchone())
    if not song:
        return jsonify({"error": "Canzone non trovata"}), 404

    cartella = _cartella_stem(song)
    destinazione = os.path.join(STEMS_DIR, "htdemucs", cartella)
    os.makedirs(destinazione, exist_ok=True)

    with get_db() as conn:
        sess = row2dict(conn.execute(
            "SELECT * FROM stem_sessions WHERE song_id=? AND model_name=? "
            "ORDER BY created_at DESC LIMIT 1", (song_id, STEM_MODELLO_MANUALE)).fetchone())
        if sess:
            session_id = sess["id"]
            conn.execute("UPDATE stem_sessions SET status='done', progress_percent=100, "
                         "output_folder=?, completed_at=datetime('now') WHERE id=?",
                         (destinazione, session_id))
        else:
            session_id = "sess_" + uuid.uuid4().hex[:10]
            conn.execute("INSERT INTO stem_sessions(id,song_id,job_id,model_name,output_folder,status,"
                         "progress_percent,completed_at) VALUES(?,?,NULL,?,?, 'done',100,datetime('now'))",
                         (session_id, song_id, STEM_MODELLO_MANUALE, destinazione))

    importati, saltati = [], []
    for i, f in enumerate(files):
        nome = _nome_file_sicuro(f.filename)
        ext = nome.rsplit(".", 1)[-1].lower() if "." in nome else ""
        if not nome:
            saltati.append({"file": str(f.filename or ""), "motivo": "nome non valido"})
            continue
        if ext not in STEM_EXT:
            saltati.append({"file": nome, "motivo": "non è un file audio"})
            continue
        percorso = os.path.join(destinazione, nome)
        f.save(percorso)
        etichetta = str(etichette[i]).strip().lower() if i < len(etichette) and etichette[i] else ""
        if not etichetta:
            etichetta = strumento_da_nomefile(nome)
        etichetta = re.sub(r"\s{2,}", " ", etichetta)[:120] or os.path.splitext(nome)[0].lower()
        try:
            peso = os.path.getsize(percorso)
        except OSError:
            peso = None
        with get_db() as conn:
            esistente = conn.execute("SELECT id FROM stem_tracks WHERE session_id=? AND file_path=?",
                                     (session_id, percorso)).fetchone()
            if esistente:
                track_id, azione = esistente["id"], "aggiornata"
                conn.execute("UPDATE stem_tracks SET stem_type=?, file_size_bytes=? WHERE id=?",
                             (etichetta, peso, track_id))
            else:
                track_id, azione = "stm_" + uuid.uuid4().hex[:10], "aggiunta"
                conn.execute("INSERT INTO stem_tracks(id,session_id,stem_type,file_path,file_size_bytes) "
                             "VALUES(?,?,?,?,?)", (track_id, session_id, etichetta, percorso, peso))
        importati.append({"file": nome, "stem_type": etichetta, "track_id": track_id,
                          "azione": azione, "byte": peso})

    with get_db() as conn:
        song = row2dict(conn.execute("SELECT * FROM songs WHERE id=?", (song_id,)).fetchone())
        stems = _scheda_stem(conn, song)
    return jsonify({"ok": True, "song_id": song_id, "session_id": session_id,
                    "folder": cartella, "importati": importati, "skipped": saltati,
                    "count": len(importati), "count_skipped": len(saltati),
                    "stems": stems})


@app.route("/db/stems/<session_id>", methods=["DELETE"])
def delete_stem_session(session_id):
    """🗑 Toglie dal database una sessione di stem con le sue tracce.

    I file non si cancellano: finiscono in `.trash/` (recuperabili), come fa la
    pulizia del database. Serve a tornare indietro quando una cartella è stata
    caricata per sbaglio, o a rifare l'import pulito.
    """
    with get_db() as conn:
        sess = row2dict(conn.execute("SELECT * FROM stem_sessions WHERE id=?", (session_id,)).fetchone())
        if not sess:
            return jsonify({"error": "Sessione non trovata"}), 404
        tracce = rows2list(conn.execute("SELECT * FROM stem_tracks WHERE session_id=?", (session_id,)))
        conn.execute("DELETE FROM stem_tracks WHERE session_id=?", (session_id,))
        conn.execute("DELETE FROM stem_sessions WHERE id=?", (session_id,))
    spostati = []
    for t in tracce:
        percorso = str(t.get("file_path") or "")
        if percorso and os.path.exists(percorso):
            try:
                spostati.append(os.path.basename(move_to_trash(percorso)))
            except OSError:
                pass
    return jsonify({"ok": True, "session_id": session_id, "song_id": sess.get("song_id"),
                    "model_name": sess.get("model_name"), "tracks": len(tracce),
                    "trash": spostati})


# ── DB: STATS ─────────────────────────────────────────────────────────────────
@app.route("/db/stats", methods=["GET"])
def db_stats():
    with get_db() as conn:
        songs = conn.execute("SELECT COUNT(*) as c FROM songs").fetchone()["c"]
        rels = conn.execute("SELECT COUNT(*) as c FROM sample_relations").fetchone()["c"]
        stems = conn.execute("SELECT COUNT(*) as c FROM stem_sessions WHERE status='done'").fetchone()["c"]
    dl_count = len([f for f in os.listdir(DL_DIR) if not f.startswith(".")])
    data = load_dataset()
    return jsonify({
        "songs": songs,
        "relations": rels,
        "stem_sessions": stems,
        "downloads": dl_count,
        "dataset_pairs": data["meta"]["count"],
    })

# ── DB: CHANGED (segnatura leggera per il polling automatico) ─────────────────
@app.route("/db/changed", methods=["GET"])
def db_changed():
    """Firma ultraleggera dello stato del database: il frontend la interroga
    ogni 2s e ricarica i dati completi SOLO se questa firma cambia."""
    with get_db() as conn:
        s = conn.execute("SELECT COUNT(*) as c, COALESCE(MAX(updated_at),'') as u FROM songs").fetchone()
        r = conn.execute("SELECT COUNT(*) as c, COALESCE(MAX(created_at),'') as u FROM sample_relations").fetchone()
    return jsonify({
        "songs_count": s["c"], "songs_max_updated": s["u"],
        "rels_count": r["c"], "rels_max_updated": r["u"],
    })

# ── DB: VERIFY (auto-fill from Genius + Tunebat) ─────────────────────────────
# Stato di avanzamento della verifica: il frontend (pulsante "Verifica" nel DB
# e "Analizza" nel player) lo interroga per mostrare una riga di stato live.
verify_progress = {}
# Passi della Verifica: 1 Genius, 2 testo/copertina, 3 YouTube, 4 WhoSampled,
# 5 Tunebat, 6 conferma audio (🔊), 7 analisi audio per BPM/Key (+ conferma dal parlato).
VERIFY_TOTALE = 7
# Campi che la pagina /verifica può correggere PRIMA di lanciare la ricerca: sono
# quelli che finiscono nelle query (titolo, artista, anno…) — gli stessi di ✏️ Edit.
METADATI_MODIFICABILI = ("title", "artist", "album", "album_artist", "composer",
                         "producers", "genre", "year", "release_date", "bpm",
                         "musical_key", "comment", "lyrics", "youtube_url",
                         "genius_url", "whosampled_url", "cover_art_path")

# ── PROGRESSO TOTALE DELLA VERIFICA (0-100%) ────────────────────────────────
# La pagina mostrava «Passo 4/7» e una barra che saltava di 1/7 in 1/7: dentro il
# passo più lungo (la trascrizione, 60-85 s) sembrava ferma. Qui si tiene il conto
# del lavoro TOTALE: `VERIFY_PESI` è quanto pesa ogni passo in secondi (misurati sul
# Mac di origine il 18/09/2026 — il 7, la trascrizione Whisper, è di gran lunga il
# più lungo) e il passo corrente ci mette dentro la sua frazione: quella VERA quando
# il pezzo la sa dire (Whisper dai segmenti già trascritti, demucs dal suo
# avanzamento), altrimenti una stima dal tempo trascorso.
VERIFY_PESI = {1: 3.0,     # ricerca su Genius
               2: 6.0,     # testo e copertina da Genius
               3: 8.0,     # ricerca URL YouTube
               4: 20.0,    # WhoSampled (col browser pilotato)
               5: 4.0,     # BPM/Key su Tunebat
               6: 12.0,    # impronta acustica sull'anteprima iTunes
               7: 90.0}    # trascrizione Whisper (e demucs, se a cappella)
VERIFY_PESO_TOTALE = sum(VERIFY_PESI.values())
# ⚠️ I passi NON girano in ordine numerico: `verify_song` fa 1 → 2 → **6** (l'audio)
# → 3 → 4 → 5 → 7. Questo è l'ordine vero, e il conto del lavoro deve usarlo: con la
# «somma dei passi con numero minore» la percentuale SCENDEVA passando dal 6 al 3
# (segnalato da Alessandro il 18/09/2026: «ci sono momenti in cui è alta e poi torna
# più bassa»: dal 30% al 6%). Entrando in un passo si considerano finiti tutti quelli
# che lo precedono NELL'ORDINE, anche se saltati.
VERIFY_ORDINE = (1, 2, 6, 3, 4, 5, 7)


def _set_verify_status(song_id, step, total, status, frazione=None, misurabile=False):
    """Segna il passo corrente e il testo da mostrare. `frazione` (0-1) è quanto è
    già stato fatto DENTRO il passo (None = non si sa ancora); `misurabile=True`
    quando questo passo la frazione la sa dire da sé (Whisper, demucs): lì non si
    inventa una stima dal tempo.

    Se il passo è lo STESSO si aggiorna solo il testo: la frazione già misurata e il
    cronometro restano (dentro il 7 ci sono più annunci — «Analisi audio (BPM/Key)…»,
    «Trascrivo il file locale…»: azzerarli faceva tornare indietro la percentuale).
    """
    vecchio = verify_progress.get(song_id) or {}
    if vecchio.get("step") == step:
        vecchio["status"] = status
        vecchio["ts"] = time.time()
        if misurabile:
            vecchio["misurabile"] = True
        return
    verify_progress[song_id] = {"step": step, "total": total, "status": status,
                                "ts": time.time(), "iniziato": time.time(),
                                "frazione": frazione, "misurabile": misurabile,
                                # il progresso mostrato non torna mai indietro: si
                                # porta avanti il massimo raggiunto (vedi l'endpoint)
                                "percento_max": vecchio.get("percento_max") or 0}


def _avanza_verify(song_id, frazione):
    """Il passo corrente dice a che punto è (0-1). Si tiene il MASSIMO: se una misura
    arriva dopo un'altra la barra non torna indietro."""
    st = verify_progress.get(song_id)
    if not st:
        return
    try:
        f = max(0.0, min(1.0, float(frazione)))
    except (TypeError, ValueError):
        return
    st["frazione"] = max(st.get("frazione") or 0.0, f)


def _con_il_massimo(vecchio, nuovo):
    """Funzione PURA. Il progresso mostrato **non torna mai indietro**: fra quello
    calcolato adesso e il massimo già visto vince il più alto."""
    try:
        return max(int(vecchio or 0), int(nuovo))
    except (TypeError, ValueError):
        return int(nuovo or 0)


def _verify_percento(passo, frazione=None, secondi=0.0, misurabile=False):
    """Funzione PURA. Quanto lavoro è stato fatto, da 0 a 100, sul TOTALE dei passi.

    Contano per intero i passi che vengono PRIMA di questo nell'ordine di esecuzione
    (`VERIFY_ORDINE`, che non è 1-2-3…: l'audio, il 6, gira subito dopo il 2); il passo
    corrente conta per la sua `frazione` — quella VERA se il pezzo la sa dire
    (`misurabile=True`: lì non si stima niente, meglio un numero fermo che uno
    inventato), altrimenti stimata dal tempo trascorso sul peso del passo e **mai oltre
    il 90%**: la barra non deve arrivare a 100 prima della fine.
    """
    peso = VERIFY_PESI.get(passo, 5.0)
    ordine = VERIFY_ORDINE if passo in VERIFY_ORDINE else tuple(sorted(VERIFY_PESI))
    prima = (ordine[:ordine.index(passo)] if passo in ordine
             else tuple(k for k in ordine if k < passo))
    fatto_prima = sum(VERIFY_PESI.get(k, 5.0) for k in prima)
    if frazione is None:
        if misurabile:
            frazione = 0.0
        else:
            frazione = 0.9 * min(1.0, max(0.0, (secondi or 0.0) / peso)) if peso else 0.0
    fattezza = peso * max(0.0, min(1.0, frazione))
    return int(round(100.0 * (fatto_prima + fattezza) / VERIFY_PESO_TOTALE))


@app.route("/db/songs/<song_id>/verify_status", methods=["GET"])
def verify_status_endpoint(song_id):
    """A che punto è la verifica: passo, testo, e il **progresso totale 0-100%**.

    Il valore restituito è il MASSIMO fra il calcolo di adesso e quello già mostrato:
    la percentuale **non può scendere** (segnalato il 18/09/2026, quando calava dal 30%
    al 6% cambiando passo e dal 56% al 38% quando arrivava la frazione vera di demucs).
    """
    st = verify_progress.get(song_id)
    if not st:
        return jsonify({"active": False, "song_id": song_id})
    secondi = max(0.0, time.time() - st.get("iniziato", st["ts"]))
    percento = _verify_percento(st["step"], st.get("frazione"), secondi,
                                bool(st.get("misurabile")))
    percento = _con_il_massimo(st.get("percento_max"), percento)
    st["percento_max"] = percento
    return jsonify({"active": True, "song_id": song_id, "step": st["step"],
                    "total": st["total"], "status": st["status"],
                    "secondi": round(secondi, 1),
                    "frazione": st.get("frazione"), "percento": percento})

def opzioni_verifica(corpo):
    """Le opzioni di `/db/songs/<id>/verify` lette dal corpo della POST.

    `tutto: true` = il lavoro COMPLETO che si può spuntare nella pagina /verifica:
    audio (anteprima ufficiale iTunes) + voce (trascrizione Whisper) + prima la
    separazione della voce (a cappella, demucs). Lo mandano i pulsanti
    «🔍 Verifica tutto» (tab Database) e «🔍 Analizza tutto» (player), che devono
    fare **su ogni canzone** tutto quello che si può fare a mano — richiesta di
    Alessandro del 18/09/2026: «fai in modo che "analizza tutto" vada a fare in
    automatico tutte queste cose per ogni canzone». Le chiavi esplicite restano
    quelle del corpo (la pagina /verifica manda le sue caselle): `tutto` riempie
    solo quello che non c'è, quindi non sovrascrive mai una scelta precisa.

    ⚠️ `tutto` accende anche demucs e Whisper: 1-3 min + 20-70 s PER BRANO.
    """
    opzioni = dict(corpo) if isinstance(corpo, dict) else {}
    if opzioni.get("tutto"):
        opzioni.setdefault("audio", True)
        opzioni.setdefault("testo", True)
        opzioni.setdefault("testo_acapella", True)
    return opzioni


@app.route("/db/songs/<song_id>/verify", methods=["POST"])
def verify_song(song_id):
    """Look up Genius + Tunebat and fill unverified fields"""
    with get_db() as conn:
        s = row2dict(conn.execute("SELECT * FROM songs WHERE id=?", (song_id,)).fetchone())
    if not s:
        return jsonify({"error": "Non trovata"}), 404

    _set_verify_status(song_id, 1, VERIFY_TOTALE, "Ricerca canzone su Genius…")
    updates = {}
    messages = []
    primary_for_search = ""      # solo artista principale, per le ricerche successive

    # ─── METADATI scritti nella pagina /verifica (prima della ricerca) ──────────
    # La pagina fa correggere titolo/artista/anno e il resto PRIMA di lanciare la
    # verifica: sono esattamente i valori che finiscono nelle ricerche. È ciò che
    # aveva risolto il caso *End of the World* (titolo corretto a mano → pagina
    # giusta trovata). Si scrivono subito nel database, come fa ✏️ Edit.
    metadati = (request.json or {}).get("metadata") or {}
    if isinstance(metadati, dict) and metadati:
        modifiche = {campo: metadati[campo] for campo in METADATI_MODIFICABILI if campo in metadati}
        if modifiche:
            with get_db() as conn:
                for campo, valore in modifiche.items():
                    conn.execute(f"UPDATE songs SET {campo}=?, updated_at=datetime('now') WHERE id=?",
                                 (valore, song_id))
            s.update(modifiche)
            messages.append("✏️ Metadati aggiornati prima della verifica: "
                            + ", ".join(sorted(modifiche)))

    # ─── OPZIONI SCELTE NELLA PAGINA /verifica ──────────────────────────────────
    # La pagina fa decidere PRIMA cosa controllare e con quali TOLLERANZE (e vale
    # anche per i pulsanti in blocco «Verifica tutto» / «Analizza tutto», che
    # mandano `{"tutto": true}`, cioè audio + voce + a cappella):
    #   tutto          → TUTTO quello che si può spuntare (vedi `opzioni_verifica`)
    #   audio          → confronto con l'anteprima ufficiale (5-10 s)
    #   testo          → confronto dal parlato, Whisper (20-70 s)
    #   testo_acapella → trascrive solo la voce, demucs (1-3 min in più)
    #   non_su_genius  → la canzone non è su Genius (freestyle/mixtape): si salta
    #   voti_conferma/voti_rifiuto e testo_conferma/testo_rifiuto → le tolleranze
    opzioni = opzioni_verifica(request.json or {})

    def _tolleranza(chiave, default, minimo, massimo):
        try:
            return max(minimo, min(massimo, float(opzioni.get(chiave, default))))
        except Exception:
            return float(default)

    audio_richiesto = bool(opzioni.get("audio"))
    testo_richiesto = bool(opzioni.get("testo"))
    sorgente_testo = "a cappella" if opzioni.get("testo_acapella") else "mix"
    non_su_genius = bool(opzioni.get("non_su_genius"))
    soglie_audio = (_tolleranza("voti_conferma", AUDIO_VOTI_CONFERMA, 1, 100000),
                    _tolleranza("voti_rifiuto", AUDIO_VOTI_RIFIUTO, 0, 100000))
    soglie_testo = (_tolleranza("testo_conferma", TESTI_SOGLIA_CONFERMA, 1, 100),
                    _tolleranza("testo_rifiuto", TESTI_SOGLIA_RIFIUTO, 0, 100))
    if soglie_audio[1] >= soglie_audio[0]:      # il rifiuto sta sempre sotto la conferma
        soglie_audio = (soglie_audio[0], max(0.0, soglie_audio[0] - 1))
    if soglie_testo[1] >= soglie_testo[0]:
        soglie_testo = (soglie_testo[0], max(0.0, soglie_testo[0] - 1))

    # Versione "pulita" di titolo/artista per la ricerca web: via il numeretto
    # iniziale di traccia ('1 - TRE STRONZI' → 'TRE STRONZI'), i trattini inutili
    # e le annotazioni tipo '(Lyrics)'/'[Official Video]'. Usata come candidato
    # aggiuntivo per Genius e come fallback per le ricerche successive.
    raw_artist = s.get("artist", "") or ""
    raw_title = s.get("title", "") or ""
    cl_artist = clean_search_text(raw_artist)
    cl_title = clean_search_text(raw_title, artist=raw_artist)

    # Valori "di base" per le ricerche successive (YouTube/WhoSampled/Tunebat)
    # quando Genius non corregge nulla. Se l'artista è segnaposto ("Brano locale")
    # si usa vuoto + titolo; se nel titolo c'è un artista conosciuto dal DB
    # (es. 'Hopsin' in 'Simon says hopsin freestyle') lo si estrae e lo si toglie
    # dal titolo, così la query è "Hopsin Simon Says Freestyle" e non
    # "Brano locale Simon says hopsin freestyle" (che Genius non trova).
    base_artist = "" if is_placeholder_artist(raw_artist) else (cl_artist or raw_artist)
    base_title = cl_title or raw_title
    if is_placeholder_artist(raw_artist):
        known_artist = known_artist_in_title(raw_title, get_db_artist_list())
        if known_artist:
            base_artist = known_artist
            t_noartist = re.sub(
                r'(?<![A-Za-z0-9])' + re.escape(known_artist) + r'(?![A-Za-z0-9])',
                ' ', raw_title, flags=re.IGNORECASE)
            base_title = re.sub(r'\s+', ' ', t_noartist).strip(' -–—:·|') or raw_title.strip()

    # ─── GENIUS ──────────────────────────────────────────────
    # `genius` è inizializzato QUI (non solo dentro il try): il passo della
    # copertina lo legge anche se la ricerca Genius esplode a metà.
    genius = None
    if non_su_genius:
        # Dichiara l'UTENTE nella pagina /verifica: la canzone non è su Genius
        # (freestyle, mixtape) → la ricerca si salta e la riga resta etichettata.
        updates["genius_escluso"] = 1
        messages.append("🚫 Segnata come NON su Genius (freestyle/mixtape): ricerca Genius saltata")
    elif s.get("genius_escluso"):
        updates["genius_escluso"] = 0
    try:
        # Candidati (artista, titolo) da provare per Genius, in ordine:
        #  1) artista/titolo estratti dal nome del file locale (se coerente col DB)
        #  2) se l'artista è segnaposto ("Brano locale"): artista estratto dal titolo
        #     (es. 'Hopsin' da 'Simon says hopsin freestyle') e solo-titolo
        #  3) dati originali del DB
        #  4) dati originali PULITI (numeretto iniziale di traccia/trattini rimossi)
        #  5) file pulito
        candidates = []
        f_artist, f_title = artist_title_from_filename(s.get("local_file", ""), db_artist=raw_artist)
        if f_artist or f_title:
            candidates.append(((f_artist or raw_artist).strip(), (f_title or raw_title).strip()))
        if is_placeholder_artist(raw_artist):
            # "Brano locale" non è un artista: se nel titolo c'è un artista vero
            # conosciuto dal DB, usalo (rimuovendolo dal titolo per la query).
            known_artist = known_artist_in_title(raw_title, get_db_artist_list())
            if known_artist:
                t_noartist = re.sub(
                    r'(?<![A-Za-z0-9])' + re.escape(known_artist) + r'(?![A-Za-z0-9])',
                    ' ', raw_title, flags=re.IGNORECASE)
                t_noartist = re.sub(r'\s+', ' ', t_noartist).strip(' -–—:·|')
                candidates.append((known_artist, t_noartist or raw_title.strip()))
            candidates.append(("", raw_title.strip()))
        candidates.append((raw_artist.strip(), raw_title.strip()))
        if cl_artist != raw_artist.strip() or cl_title != raw_title.strip():
            candidates.append(((cl_artist or raw_artist).strip(), (cl_title or raw_title).strip()))
        if (f_artist or f_title) and normalize(f_title or "") != normalize(raw_title):
            cf_artist = (clean_search_text(f_artist) or cl_artist).strip()
            cf_title = (clean_search_text(f_title, artist=f_artist) or cl_title).strip()
            candidates.append((cf_artist, cf_title))
        # deduplica mantenendo l'ordine
        seen = set()
        uniq = []
        for ca, ct in candidates:
            k = (normalize(ca), normalize(ct))
            if k not in seen and (ca or ct):
                seen.add(k)
                uniq.append((ca, ct))

        genius = None
        genius_score = 0.0
        for ca, ct in ([] if non_su_genius else uniq):
            g = fetch_genius(ca, ct)
            if g:
                # Controllo di similarità tra la query originale e il risultato di
                # Genius: la search API restituisce il primo hit (spesso il più
                # famoso dell'artista, es. "Lose Yourself" per "Eminem 3hree6ix5ive")
                # e senza questo filtro verrebbe accettato ciecamente, sovrascrivendo
                # titolo e artista con quelli di una canzone sbagliata. Il risultato
                # è accettato SOLO se il match supera la soglia (0.55, come nel resto
                # dell'app); altrimenti si prova il candidato successivo.
                score = match_score(ca or raw_artist, ct or raw_title,
                                    g.get("artist", ""), g.get("title", ""))
                if score >= 0.55:
                    if normalize(ca) != normalize(raw_artist) or normalize(ct) != normalize(raw_title):
                        messages.append(f"🔍 Genius trovato con ricerca pulita: \"{ct}\" — {ca or 'artista sconosciuto'}")
                    messages.append(f"✅ Genius match score: {score:.2f}")
                    genius = g
                    genius_score = score
                    break
                else:
                    messages.append(f"⚠️ Genius match score troppo basso ({score:.2f}), risultato scartato: \"{g.get('title', '')}\"")
        # Genius non trova nulla col titolo attuale (spesso perché è "sporco",
        # es. "1 - TRE STRONZI" invece di "TRE STRONZI"): cerchiamo il titolo
        # corretto su YouTube (con la versione pulita della query) e riproviamo
        # Genius con quello. Se YouTube conferma il titolo, viene salvato.
        if not genius and not non_su_genius:
            _set_verify_status(song_id, 1, VERIFY_TOTALE, "Genius non ha trovato: cerco titolo corretto su YouTube…")
            try:
                yt_artist = base_artist
                yt_title = base_title
                yt_url_c, yt_title_c = yt_search_first(
                    f"{yt_artist} {yt_title}",
                    expected_title=yt_title,
                    expected_artist=yt_artist)
                if yt_url_c and yt_title_c:
                    # Anche il risultato YouTube va verificato: senza filtro di
                    # similarità, la query "Eminem 3hree6ix5ive" darebbe il primo
                    # video più popolare ("Lose Yourself") e il titolo verrebbe
                    # "corretto" in modo sbagliato. Si accetta solo se il match
                    # con la canzone cercata supera la soglia (0.55).
                    yt_clean = clean_yt_title(yt_title_c, artist=yt_artist)
                    yt_score = yt_match_score(yt_artist, yt_title, yt_title_c)
                    if yt_score >= 0.55:
                        if yt_clean and normalize(yt_clean) != normalize(raw_title):
                            messages.append(f"🔄 Titolo corretto via YouTube: \"{raw_title}\" → \"{yt_clean}\" (score {yt_score:.2f})")
                            updates["title"] = yt_clean
                            updates["title_verified"] = 1
                            if not s.get("youtube_url"):
                                updates["youtube_url"] = yt_url_c
                                messages.append(f"▶ URL YouTube trovato: {yt_title_c}")
                            # Riprova Genius col titolo corretto (troverà anche il testo)
                            genius = fetch_genius(yt_artist, yt_clean)
                            if genius:
                                genius_score = match_score(yt_artist, yt_clean,
                                                           genius.get("artist", ""), genius.get("title", ""))
                                if genius_score < 0.55:
                                    messages.append(f"⚠️ Genius match score troppo basso dopo correzione YouTube ({genius_score:.2f}), scartato")
                                    genius = None
                        elif not s.get("youtube_url"):
                            updates["youtube_url"] = yt_url_c
                            messages.append(f"▶ URL YouTube trovato: {yt_title_c}")
                    else:
                        messages.append(f"⚠️ YouTube match score basso ({yt_score:.2f}), titolo non accettato: \"{yt_title_c}\"")
            except Exception as e2:
                messages.append(f"⚠️ Correzione titolo via YouTube: errore ({str(e2)[:50]})")
        if genius:
            if genius_score:
                # Salva la qualità del match Genius per tracciamento futuro
                updates["genius_match_score"] = round(genius_score, 3)
            if not s.get("title_verified") and genius.get("title"):
                updates["title"] = genius["title"]
                updates["title_verified"] = 1
                messages.append("Titolo trovato su Genius")
            # ARTISTI: Genius elenca il primary + i feat. (chiave "artists"); nel
            # campo `artist` del DB devono comparire TUTTI, separati da " / "
            # (formato del resto della libreria), non solo il primo. Se il brano
            # era già verificato ma l'elenco è incompleto (vecchie verifiche che
            # salvavano il solo primary, o un feat. mancante) si completa adesso:
            # l'aggiornamento è idempotente e non concatena doppioni.
            genius_artists = genius.get("artists") or ([genius["artist"]] if genius.get("artist") else [])
            if genius_artists:
                prev_artist = (s.get("artist") or "").strip()
                missing_artists = _credits_missing(prev_artist, genius_artists)
                if missing_artists:
                    updates["artist"] = " / ".join(genius_artists)
                    if prev_artist:
                        messages.append(f"🎤 Artisti completati da Genius: {updates['artist']}")
                    else:
                        messages.append(f"🎤 Artisti da Genius: {updates['artist']}")
                if missing_artists or not s.get("artist_verified"):
                    updates["artist_verified"] = 1
            if genius.get("artist"):
                # Le ricerche successive (YouTube/WhoSampled/Tunebat) vanno fatte
                # col solo artista principale, non con l'elenco completo.
                primary_for_search = genius["artist"]
            # Il testo viene cercato se manca o se è "sporco" (es. vecchi fetch del
            # player con '8 Contributors', 'Read More', descrizioni di Genius...).
            existing_lyrics = (s.get("lyrics") or "")
            lyrics_dirty = (not existing_lyrics.strip()) or bool(re.search(
                r'\d+\s*[Cc]ontributors?|Read\s+More\.?$|You\s+might\s+also\s+like|^\s*.{1,80}\s+Lyrics\s*$|'
                r'^\s*\[(?:' + _TRANS_KEYS + r')[^\]\n]{0,90}\]',
                existing_lyrics, re.IGNORECASE | re.MULTILINE))
            if lyrics_dirty and genius.get("genius_url"):
                _set_verify_status(song_id, 2, VERIFY_TOTALE, "Recupero testo da Genius…")
                lyrics = fetch_genius_lyrics_text(genius["genius_url"])
                if lyrics:
                    updates["lyrics"] = lyrics
                    updates["lyrics_verified"] = 1
                    messages.append("Testo trovato su Genius")
            # PRODUTTORI: li fornisce l'API della singola canzone; si salvano come
            # JSON (formato già in uso) e si completano se ne manca qualcuno.
            if genius.get("producers") and _credits_missing(s.get("producers"), genius["producers"]):
                updates["producers"] = json.dumps(genius["producers"], ensure_ascii=False)
                messages.append("🎛 Produttori da Genius: " + ", ".join(genius["producers"]))
            # DATA: Genius la dà come testo ("September 2, 2025").
            data_eff = s.get("release_date") or ""
            if genius.get("release_date") and not data_eff:
                updates["release_date"] = genius["release_date"]
                data_eff = genius["release_date"]
                messages.append("Data rilascio trovata su Genius")
            # ANNO: va ricavato dalla data, altrimenti la casella "anno" resta
            # vuota mentre la data c'è (segnalato il 17/09/2026).
            if data_eff and not str(s.get("year") or "").strip():
                anno = _year_from_date(data_eff)
                if anno:
                    updates["year"] = anno
                    messages.append(f"Anno ricavato dalla data ({data_eff}): {anno}")
            # ALBUM: si completa se manca o se è un segnaposto ("Mus", che era il
            # nome della cartella di caricamento): un falso album corto non deve
            # bloccare quello vero di Genius.
            album_attuale = str(s.get("album") or "").strip()
            if genius.get("album") and (not album_attuale or _album_segnaposto(album_attuale)):
                if normalize(genius["album"]) != normalize(album_attuale):
                    updates["album"] = genius["album"]
                    messages.append(f"Album da Genius: {genius['album']}")
            # COMPOSITORI (i "writer" di Genius): si completano se manca qualcuno.
            if genius.get("composers") and _credits_missing(s.get("composer"), genius["composers"]):
                updates["composer"] = ", ".join(genius["composers"])
                messages.append("✍️ Compositore da Genius: " + ", ".join(genius["composers"]))
            if genius.get("album_artist") and not s.get("album_artist"):
                updates["album_artist"] = genius["album_artist"]
                messages.append(f"Artista album trovato su Genius: {genius['album_artist']}")
            if genius.get("genius_url") and not s.get("genius_url"):
                updates["genius_url"] = genius["genius_url"]
                messages.append("URL Genius trovato")
        elif not non_su_genius:
            messages.append("⚠️ Genius: nessun risultato trovato")
    except Exception as e:
        messages.append(f"⚠️ Genius: errore ({str(e)[:50]})")

    # ─── COPERTINA ───────────────────────────────────────────
    # Fino al 18/09/2026 `cover_art_path` restava vuoto per TUTTE le 890 canzoni:
    # la Verifica trovava titolo, album, BPM, tonalità e testo, ma nessuna
    # immagine. Qui si scarica la cover di Genius e la si salva in `covers/`; se
    # Genius non ha l'immagine si prova con quella incorporata nel file audio
    # (MP3/M4A/FLAC). Nel database va il NOME del file, non l'URL: gli URL delle
    # CDN di Genius cambiano, il nome no. Se il file esiste già non si rifà nulla.
    if _cover_mancante(s.get("cover_art_path")):
        _set_verify_status(song_id, 2, VERIFY_TOTALE, "Recupero copertina da Genius…")
        nome_cover, msg_cover = _salva_copertina(
            song_id, (genius or {}).get("cover_art", ""), s.get("local_file", "") or "")
        if nome_cover:
            updates["cover_art_path"] = nome_cover
        messages.append(msg_cover)

    # Titolo/artista "effettivi" da usare nelle ricerche successive (YouTube,
    # WhoSampled, Tunebat): il campo `artist` può elencare TUTTI i crediti
    # ("A / B / C") e come query farebbe fallire i match, quindi per le ricerche
    # si usa il solo artista principale (quello di Genius, o il primo del DB).
    if not primary_for_search:
        primary_for_search = (base_artist or "").split(" / ")[0].strip() or base_artist
    search_artist = primary_for_search
    search_title = updates.get("title") or base_title

    # ─── CONFERMA AUDIO (🔊) ─────────────────────────────────
    # Genius NON ha audio: il match è solo TESTUALE (match_score = 0,80·titolo +
    # 0,20·artista) e quindi può essere un falso positivo. Qui si controlla
    # l'AUDIO: si cerca l'ANTEPRIMA UFFICIALE della canzone su iTunes (API
    # pubblica, 30 s) e la si cerca DENTRO il file locale con un'impronta
    # acustica (vedi `conferma_audio`). Il passo costa 5-10 s (ricerca + 1 MB di
    # anteprima + impronta), quindi si fa quando serve davvero: se il chiamante
    # lo chiede (`{"audio": true}` nel corpo) o se il match testuale è DEBOLE
    # (score < 0,95) — cioè proprio le righe a rischio falso positivo. Su
    # "Verifica tutto" delle righe mai abbinate (score assente) non si attiva,
    # altrimenti sarebbero 890 × 8 s di attesa.
    # (Le opzioni della pagina /verifica — audio, testo, tolleranze, non-su-Genius —
    #  sono lette all'inizio della funzione, subito dopo i metadati.)
    score_eff = updates.get("genius_match_score", s.get("genius_match_score"))
    # Anche il match Genius va confermato con l'audio quando l'artista della riga è
    # un segnaposto ("Brano locale"): lì il confronto testuale è strutturalmente
    # debole, ed è il caso in cui un link sbagliato passa più facilmente.
    artista_mancante_riga = (not (raw_artist or "").strip()) or is_placeholder_artist(raw_artist)
    if (audio_richiesto
            or (score_eff is not None and score_eff < AUDIO_SCORE_SOSPETTO)
            or (genius and artista_mancante_riga)):
        _set_verify_status(song_id, 6, VERIFY_TOTALE, "🔊 Confronto con l'anteprima ufficiale…")
        try:
            audio_s = dict(s); audio_s.update(updates)   # titolo/artista/score appena trovati
            upd_audio, msg_audio = conferma_audio(
                audio_s,
                status=lambda testo: _set_verify_status(song_id, 6, VERIFY_TOTALE, testo),
                soglie=soglie_audio)
            updates.update(upd_audio)
            messages.append(msg_audio)
        except Exception as e:
            messages.append(f"⚠️ Conferma audio: errore ({str(e)[:60]})")

    # ─── BPM & KEY + URL (YouTube / WhoSampled / Tunebat) ──────────
    # Logica BPM/Key:
    #  - Se BPM e Key sono GIÀ VERIFICATI nel DB → si salta tutto (né Tunebat né audio).
    #  - Altrimenti Tunebat è la fonte principale; l'analisi audio (librosa) viene
    #    fatta SOLO se e solo se Tunebat non fornisce BPM o Key.
    #  - Il browser (Chrome) parte SOLO se serve: WhoSampled senza URL, o BPM/Key
    #    non già verificati (per Tunebat). Se c'è già tutto → niente browser.
    ws_driver = None
    cur_bpm = s.get("bpm")
    cur_key = s.get("musical_key")
    eff_bpm = cur_bpm            # valore effettivo che rimarrà nel DB
    eff_key = cur_key
    bpm_ok = (s.get("bpm_verified") == 1) and (cur_bpm not in (None, ""))
    key_ok = (s.get("key_verified") == 1) and (cur_key not in (None, ""))
    bpmkey_done = bpm_ok and key_ok
    tb = None
    try:

        # 1) URL YouTube → stessa ricerca dello scraper di WhoSampled
        _set_verify_status(song_id, 3, VERIFY_TOTALE, "Ricerca URL YouTube…")
        try:
            if not s.get("youtube_url") and not updates.get("youtube_url"):
                yt_url, yt_title = yt_search_first(
                    f"{search_artist} {search_title}",
                    expected_title=search_title,
                    expected_artist=search_artist)
                if yt_url:
                    updates["youtube_url"] = yt_url
                    messages.append(f"▶ URL YouTube trovato" + (f": {yt_title}" if yt_title else ""))
                else:
                    messages.append("⚠️ YouTube: nessun risultato trovato")
        except Exception as e:
            messages.append(f"⚠️ YouTube: errore ({str(e)[:50]})")

        # 2) Browser SOLO se serve davvero (WhoSampled da cercare o da ricontrollare,
        #    o BPM/Key non già verificati). Dal 18/09/2026 si ricontrolla anche un URL
        #    già salvato che non ha ancora un verdetto audio — è così che si scopre un
        #    link sbagliato (l'audio è l'unica prova non testuale) — mentre un candidato
        #    già scartato NON si ricontrolla con la STESSA ricerca: `ws_query` ricorda
        #    cosa è stato cercato, quindi se il titolo cambia la Verifica riprova.
        query_ws = f"{search_artist} {search_title}".strip()
        ws_da_controllare = ws_da_cercare(s.get("whosampled_url"), s.get("ws_audio_esito"),
                                          s.get("ws_query"), query_ws)
        need_browser = ws_da_controllare or (not bpmkey_done)
        if need_browser:
            try:
                ws_driver = _make_driver_safe(60)
            except Exception as e:
                messages.append(f"⚠️ Browser non avviato: {str(e)[:60]}")
        else:
            messages.append("ℹ️ URL WhoSampled e BPM/Key già presenti: browser non avviato")

        # 3) URL WhoSampled → stessa ricerca dello scraper (artista + titolo)
        if ws_driver and ws_da_controllare:
            _set_verify_status(song_id, 4, VERIFY_TOTALE, "Ricerca WhoSampled…")
            try:
                track, candidati = search_whosampled(
                    ws_driver,
                    query_ws,
                    searched_artist=search_artist,
                    searched_title=search_title)
                if track and track.get("url"):
                    ws_score = match_score(search_artist, search_title,
                                           track.get("artist", ""), track.get("title", ""))
                    riga_candidato = f"{track.get('artist', '')} — {track.get('title', '')}"
                    # Senza artista il punteggio NON prova nulla (`match_score` dà 1.0
                    # all'artista vuoto): servono il titolo univoco/riconoscibile e,
                    # soprattutto, la CONFERMA AUDIO del candidato.
                    artisti_stesso_titolo = {normalize(c.get("artist", ""))
                                             for c in (candidati or [])
                                             if normalize(c.get("title", "")) == normalize(track.get("title", ""))}
                    verdetto = verifica_audio_riferimento(
                        os.path.join(DL_DIR, s.get("local_file") or "") if s.get("local_file") else "",
                        track.get("artist", ""), track.get("title", ""),
                        status=lambda testo: _set_verify_status(song_id, 4, VERIFY_TOTALE, testo),
                        soglie=soglie_audio)
                    decisione = esito_whosampled(
                        ws_score, verdetto["esito"],
                        artista_mancante=not (search_artist or "").strip(),
                        titolo_univoco=len(artisti_stesso_titolo) == 1,
                        artista_identificabile=artista_identificabile_nel_titolo(
                            track.get("artist", ""), search_title, get_db_artist_list()))
                    if verdetto["confronto"]:
                        messages.append(verdetto["messaggio"])
                    if decisione["azione"] == "salva":
                        updates["whosampled_url"] = track["url"]
                        updates["ws_match_score"] = round(ws_score, 3)
                        updates["ws_query"] = query_ws        # cosa è stato cercato
                        updates.update(campi_dal_risultato_audio(verdetto, "ws_audio_"))
                        messages.append(f"🔗 URL WhoSampled: {riga_candidato} "
                                        f"(score {ws_score:.2f} · {decisione['motivo']})")
                    else:
                        # Il candidato scartato si SCRIVE COMUNQUE nel database: prima
                        # si scriveva solo quando c'era un link da rimuovere, quindi la
                        # riga non ricordava di aver controllato e sembrava che la
                        # Verifica non avesse fatto niente (segnalato il 18/09/2026).
                        rimosso = bool(decisione.get("rimuovi_url")
                                       and s.get("whosampled_url") == track["url"])
                        updates["whosampled_url"] = None
                        updates["ws_match_score"] = round(ws_score, 3)
                        updates["ws_query"] = query_ws        # cosa è stato cercato
                        updates.update(campi_dal_risultato_audio(verdetto, "ws_audio_"))
                        updates["ws_audio_esito"] = "scartato"    # verdetto sul CANDIDATO
                        dettagli = decisione["motivo"]
                        if verdetto["confronto"]:
                            dettagli += f" ({verdetto['voti']} hash allineati)"
                        if rimosso:
                            dettagli += " · link salvato rimosso"
                        updates["ws_audio_motivo"] = dettagli[:200]
                        messages.append(f"❌ WhoSampled scartato ({decisione['motivo']}): "
                                        f"{riga_candidato}")
                        if rimosso:
                            messages.append("🧹 Il link WhoSampled salvato era proprio questo: rimosso")
                else:
                    messages.append("⚠️ WhoSampled: nessun risultato trovato")
            except Exception as e:
                messages.append(f"⚠️ WhoSampled: errore ({str(e)[:50]})")

        # 4) TUNEBAT PRIMA → BPM/Key (fonte principale) e link — solo se non già verificati
        if not bpmkey_done and ws_driver:
            _set_verify_status(song_id, 5, VERIFY_TOTALE, "Verifica BPM/Key su Tunebat…")
            tb = scrape_tunebat(search_artist, search_title, driver=ws_driver)
            if tb:
                if tb.get("bpm") is not None:
                    tb_bpm = float(tb["bpm"])
                    if eff_bpm not in (None, ""):
                        if abs(float(eff_bpm) - tb_bpm) > 2.0:
                            updates["bpm_verified"] = 0
                            messages.append(f"⚠️ CONFLITTO BPM: {float(eff_bpm)} vs Tunebat {tb_bpm} (differenza >2) → rosso")
                        else:
                            updates["bpm_verified"] = 1
                            messages.append(f"BPM confermato da Tunebat ({tb_bpm}) → verde")
                    else:
                        updates["bpm"] = tb_bpm
                        updates["bpm_verified"] = 1
                        eff_bpm = tb_bpm
                        messages.append(f"BPM da Tunebat: {tb_bpm}")
                if tb.get("key"):
                    tb_key = tb["key"]
                    if eff_key not in (None, ""):
                        if keys_equivalent(str(eff_key), tb_key):
                            updates["key_verified"] = 1
                            messages.append(f"Chiave confermata da Tunebat ({tb_key}) → verde")
                        else:
                            updates["key_verified"] = 0
                            messages.append(f"⚠️ CONFLITTO chiave: '{eff_key}' vs Tunebat '{tb_key}' (fondamentale diversa) → rosso")
                    else:
                        updates["musical_key"] = tb_key
                        updates["key_verified"] = 1
                        eff_key = tb_key
                        messages.append(f"Chiave da Tunebat: {tb_key}")
            else:
                messages.append("⚠️ Tunebat: nessun risultato (BPM/Key non confrontati)")
            # Salva il link Tunebat della canzone (se la pagina è stata trovata)
            if tb and tb.get("tunebat_url") and not s.get("tunebat_url"):
                updates["tunebat_url"] = tb["tunebat_url"]
                messages.append(f"🔗 Link Tunebat salvato")
        elif not bpmkey_done:
            messages.append("⚠️ Browser non disponibile: BPM/Key via Tunebat saltati")
    except Exception as e:
        messages.append(f"⚠️ BPM/Key: errore ({str(e)[:50]})")
    finally:
        if ws_driver:
            try: ws_driver.quit()
            except Exception: pass

    # 5) ANALISI AUDIO → SOLO se BPM/Key non già verificati e Tunebat NON li ha forniti
    if not bpmkey_done and (eff_bpm in (None, "") or eff_key in (None, "")) and s.get("local_file"):
        fp = os.path.join(DL_DIR, s["local_file"])
        if os.path.exists(fp):
            _set_verify_status(song_id, 7, VERIFY_TOTALE, "Analisi audio (BPM/Key)…",
                               misurabile=True)
            try:
                # Analisi audio VELOCE e SICURA: prima ffmpeg via os.posix_spawn
                # (niente fork) + numpy vettorizzato (rilascia il GIL → il server
                # resta reattivo). librosa (che tramite audioread può spawnare
                # subprocess) viene usato SOLO come fallback se ffmpeg fallisce.
                meta_audio = analyze_audio_ffmpeg(fp)
                if not meta_audio and HAS_LIBROSA:
                    meta_audio = analyze_audio_librosa(fp)
                if meta_audio:
                    if (meta_audio.get("bpm") is not None) and (eff_bpm in (None, "")):
                        updates["bpm"] = float(meta_audio["bpm"])
                        updates["bpm_verified"] = 1
                        eff_bpm = float(meta_audio["bpm"])
                        messages.append(f"BPM stimato dal file audio ({meta_audio.get('source')}): {updates['bpm']}")
                    if meta_audio.get("key") and (eff_key in (None, "")):
                        updates["musical_key"] = meta_audio["key"]
                        updates["key_verified"] = 1
                        eff_key = meta_audio["key"]
                        messages.append(f"Chiave stimata dal file audio ({meta_audio.get('source')}): {meta_audio['key']}")
            except Exception as e:
                messages.append(f"⚠️ Analisi audio: errore ({str(e)[:50]})")

    # ─── CONFERMA DAL PARLATO (Whisper) ────────────────────────────────────────
    # Quello che si SENTE è il testo che ci si aspetta? Il riferimento sono le
    # liriche della canzone trovata su Genius (o già in database); se non ci sono,
    # si trascrive l'ANTEPRIMA ufficiale e si controlla che le sue parole si
    # sentano nel file locale. `sorgente_testo` = 'a cappella' se l'utente ha
    # chiesto di separare prima la voce (demucs, 1-3 min in più).
    if testo_richiesto:
        percorso_locale = (os.path.join(DL_DIR, s.get("local_file") or "")
                           if s.get("local_file") else "")
        try:
            liriche_rif = (updates.get("lyrics") or s.get("lyrics") or "").strip()
            if liriche_rif:
                risultato_testo = verifica_testo_riferimento(
                    percorso_locale, liriche_rif, tipo="liriche", sorgente=sorgente_testo,
                    status=lambda testo: _set_verify_status(song_id, 7, VERIFY_TOTALE, testo,
                                                            misurabile=True),
                    soglie=soglie_testo, avanza=lambda f: _avanza_verify(song_id, f))
            else:
                _set_verify_status(song_id, 7, VERIFY_TOTALE,
                                   "🗣 Cerco un audio di riferimento…", misurabile=True)
                info_rif = cerca_anteprima_itunes(search_artist, search_title)
                audio_rif = scarica_anteprima(info_rif) if info_rif else None
                risultato_testo = verifica_testo_riferimento(
                    percorso_locale, audio_rif or "", tipo="audio", sorgente=sorgente_testo,
                    status=lambda testo: _set_verify_status(song_id, 7, VERIFY_TOTALE, testo,
                                                            misurabile=True),
                    soglie=soglie_testo, avanza=lambda f: _avanza_verify(song_id, f))
            updates.update(campi_dal_risultato_testo(risultato_testo))
            messages.append(risultato_testo["messaggio"])
        except Exception as e:
            messages.append(f"⚠️ Confronto dal parlato: errore ({str(e)[:60]})")

    # ─── SALVA NEL DATABASE ─────────────────────────────────
    if updates:
        with get_db() as conn:
            for f, v in updates.items():
                conn.execute(f"UPDATE songs SET {f}=?, updated_at=datetime('now') WHERE id=?", (v, song_id))
        s.update(updates)
        messages.append("✅ Dati salvati nel database")
    else:
        messages.append("ℹ️ Nessun dato da aggiornare (i campi sono già verificati o non disponibili)")

    verify_progress.pop(song_id, None)

    return jsonify({
        "updated": updates,
        "song": s,
        "messages": messages,
        "success": len(updates) > 0
    })

@app.route("/db/songs/<song_id>/audio_check", methods=["POST"])
def audio_check_song(song_id):
    """🔊 Il controllo audio di una canzone (senza rifare tutta la Verifica).

    Confronta il file locale con l'anteprima UFFICIALE su iTunes di OGNI
    riferimento salvato nella riga:
    1. il match **Genius** (artista principale + titolo della riga) → `audio_match_*`;
    2. il link **WhoSampled** già salvato, di cui artista e titolo si leggono
       dall'URL (`/Artista/Titolo/`: niente browser) → `ws_audio_*`. Se l'audio
       dimostra che quella pagina è di un ALTRO brano il link viene **rimosso**:
       è il caso di *End of the World* → pagina di *Skeeter Davis* (18/09/2026,
       8 hash allineati contro 2.525 del caso giusto).
    Dura 5-15 s (ricerca + ~1 MB di anteprima + impronta per ogni riferimento).
    """
    with get_db() as conn:
        s = row2dict(conn.execute("SELECT * FROM songs WHERE id=?", (song_id,)).fetchone())
    if not s:
        return jsonify({"error": "Non trovata"}), 404

    aggiornamenti, messaggi = {}, []
    try:
        upd, msg = conferma_audio(
            s, status=lambda testo: _set_verify_status(song_id, 6, VERIFY_TOTALE, testo))
        aggiornamenti.update(upd)
        messaggi.append(msg)

        riferimenti = artista_titolo_da_whosampled_url(s.get("whosampled_url") or "")
        if riferimenti and s.get("local_file"):
            _set_verify_status(song_id, 6, VERIFY_TOTALE, "🔊 Confronto il link WhoSampled…")
            verdetto = verifica_audio_riferimento(
                os.path.join(DL_DIR, s["local_file"]), riferimenti[0], riferimenti[1])
            aggiornamenti.update(campi_dal_risultato_audio(verdetto, "ws_audio_"))
            messaggi.append(f"🔗 WhoSampled ({riferimenti[0]} — {riferimenti[1]}): "
                            f"{verdetto['messaggio']}")
            decisione = esito_whosampled(
                s.get("ws_match_score") if s.get("ws_match_score") is not None else 1.0,
                verdetto["esito"], artista_mancante=is_placeholder_artist(s.get("artist")))
            if decisione.get("rimuovi_url") and verdetto["confronto"]:
                aggiornamenti["whosampled_url"] = None
                aggiornamenti["ws_match_score"] = None
                aggiornamenti["ws_audio_esito"] = "scartato"      # verdetto sul CANDIDATO
                aggiornamenti["ws_audio_motivo"] = (
                    f"{decisione['motivo']} ({verdetto['voti']} hash allineati) · "
                    f"link salvato rimosso")[:200]
                messaggi.append("🧹 Il link WhoSampled salvato è di un altro brano: rimosso")
    finally:
        verify_progress.pop(song_id, None)

    if aggiornamenti:
        with get_db() as conn:
            for campo, valore in aggiornamenti.items():
                conn.execute(f"UPDATE songs SET {campo}=?, updated_at=datetime('now') WHERE id=?",
                             (valore, song_id))
    with get_db() as conn:
        s = row2dict(conn.execute("SELECT * FROM songs WHERE id=?", (song_id,)).fetchone())
    return jsonify({"song": s, "updated": aggiornamenti, "messages": messaggi,
                    "esito": aggiornamenti.get("audio_match_esito"),
                    "esito_whosampled": aggiornamenti.get("ws_audio_esito"),
                    "success": bool(aggiornamenti)})


# ── CONFRONTO VOCE: I TESTI E I DUE AUDIO ─────────────────────────────────────
# La pagina /verifica mostra il confronto a due colonne: a sinistra quello che si
# SENTE (la trascrizione di Whisper del file locale o dell'a-cappella), a destra il
# testo VERO usato come riferimento (le liriche di Genius; la trascrizione
# dell'anteprima ufficiale quando le liriche non c'erano), e sotto i due file da
# ascoltare — il nostro e l'anteprima ufficiale. Le parole in comune si calcolano
# con le STESSE funzioni del verdetto (`parole_contenuto`), così l'evidenziazione
# in pagina è esattamente quello che ha prodotto la percentuale.
def _audio_del_confronto(rel, etichetta, default_rel=""):
    """Funzione PURA. Dal percorso salvato nel database all'URL del player:
    `/stream/<file>` per la libreria (`downloads/…`) e `/anteprima/<file>` per le
    anteprime e per la voce estratta da demucs (`anteprime/…`). None se non c'è."""
    rel = (rel or default_rel or "").strip().replace(os.sep, "/")
    if not rel:
        return None
    if rel.startswith("downloads/"):
        url = "/stream/" + urllib.parse.quote(rel[len("downloads/"):])
    elif rel.startswith("anteprime/"):
        url = "/anteprima/" + urllib.parse.quote(rel[len("anteprime/"):])
    else:
        return None
    return {"percorso": rel, "url": url, "etichetta": etichetta,
            "esiste": os.path.exists(os.path.join(BASE_DIR, rel))}


@app.route("/db/songs/<song_id>/confronto", methods=["GET"])
def db_song_confronto(song_id):
    """📄 I testi e gli audio del confronto, per la pagina /verifica.

    Restituisce DUE cose che non vanno confuse (lezione del 18/09/2026, quando
    l'anteprima del passo 🔊 era finita accanto all'a-cappella del passo 🗣 e
    sembrava che il confronto voce confrontasse quei due file — non è così):

    1. il confronto **voce**: `trascrizione` (quello che si sente) contro
       `riferimento` (il TESTO delle liriche, o l'audio ufficiale quando le liriche
       mancavano). `audio_nostro` è il file che Whisper ha trascritto (a cappella o
       mix), `audio_mix` lo stesso brano con la musica, `audio_riferimento` c'è SOLO
       se il riferimento era davvero un audio;
    2. il confronto **audio** (impronta acustica, passo 🔊) in `impronta`: l'anteprima
       ufficiale cercata DENTRO il file locale, con `offset` = dove comincia. Lì i due
       file non devono corrispondere: per ascoltarli a confronto il nostro si fa
       partire da `offset` e l'anteprima da zero.
    """
    with get_db() as conn:
        s = row2dict(conn.execute("SELECT * FROM songs WHERE id=?", (song_id,)).fetchone())
    if not s:
        return jsonify({"error": "Non trovata"}), 404

    trascrizione = (s.get("testo_trascrizione") or "").strip()
    rif = (s.get("testo_riferimento") or "").strip() or (s.get("lyrics") or "").strip()
    tipo = "audio" if (s.get("testo_audio_riferimento") or "").strip() else "liriche"

    attese = parole_contenuto(rif)
    sentite = parole_contenuto(trascrizione)
    comuni = sorted(set(attese) & set(sentite))

    # L'audio che Whisper ha DAVVERO trascritto e, quando è diverso, il mix: la pagina
    # fa sentire l'uno o l'altro con un interruttore (stessa canzone con e senza
    # musica: questo sì è un confronto che ha senso sentire).
    nostro_rel = s.get("testo_audio_nostro") or ""
    mix_rel = ("downloads/" + s["local_file"]) if s.get("local_file") else ""
    nostro = _audio_del_confronto(
        nostro_rel,
        "a cappella (demucs)" if "acapella_" in nostro_rel else "il file locale",
        default_rel=mix_rel)
    mix = _audio_del_confronto(mix_rel, "file locale (con la musica)") if mix_rel else None
    # Solo se il riferimento del passo voce ERA un audio (liriche mancanti): quando il
    # riferimento è il TESTO a destra non si ascolta niente.
    riferimento_audio = _audio_del_confronto(
        s.get("testo_audio_riferimento") or "", "audio di riferimento (anteprima ufficiale)")

    # ── Il confronto audio (impronta acustica, passo 🔊) ───────────────────────
    impronta = None
    if s.get("audio_match_esito") or s.get("audio_match_offset") is not None:
        impronta = {
            "esito": s.get("audio_match_esito"), "voti": s.get("audio_match_voti"),
            "comuni": s.get("audio_match_comuni"), "offset": s.get("audio_match_offset"),
            "fonte": s.get("audio_match_fonte"), "motivo": s.get("audio_match_motivo"),
            "at": s.get("audio_match_at"),
            "audio_nostro": _audio_del_confronto(mix_rel or nostro_rel, "il file locale"),
            "audio_anteprima": _audio_del_confronto(s.get("anteprima_file") or "",
                                                    "anteprima ufficiale (iTunes)"),
        }

    return jsonify({
        "song_id": s["id"], "titolo": s.get("title") or s.get("local_file") or "",
        "artista": s.get("artist") or "",
        # `pronto` = c'è un testo trascritto da mostrare; se è falso la pagina
        # spiega che va lanciato 🗣 Controlla voce (il testo si salva da adesso).
        "pronto": bool(trascrizione),
        "tipo": tipo, "esito": s.get("testo_esito"), "copertura": s.get("testo_voti"),
        "fonte": s.get("testo_fonte"), "motivo": s.get("testo_motivo"),
        "trascrizione": trascrizione, "riferimento": rif,
        "parole_attese": len(set(attese)), "parole_attese_totali": len(attese),
        "parole_sentite": len(sentite),
        "parole_sentite_uniche": (s.get("testo_parole_uniche")
                                  if s.get("testo_parole_uniche") is not None
                                  else len(set(sentite))),
        "comuni": comuni, "comuni_quanti": len(comuni),
        "audio_nostro": nostro, "audio_mix": mix, "audio_riferimento": riferimento_audio,
        "impronta": impronta,
    })


# ── DB: MASS RENAME ───────────────────────────────────────────────────────────
# ── DB: MODIFICHE IN BLOCCO (✏️ Rinomina in massa / ➡️ Sposta) ────────────────
# Campi su cui possono lavorare gli strumenti "in blocco" della tab Database:
# sono i campi testuali semplici di `songs`. Restano fuori (apposta) `id`, i
# timestamp e le colonne di stato (verified, analyzed_status, URL…): quelle si
# toccano da ✏️ Edit, dalle funzioni dell'app o dallo script Python del pannello.
BULK_FIELDS = [
    "title", "artist", "album", "album_artist", "composer", "producers",
    "genre", "year", "release_date", "comment", "musical_key",
]
# Campi numerici: da un titolo si sposta solo una cifra (es. l'anno 1999)
NUMERIC_FIELDS = {"year"}
# Etichetta delle tracce separate (`stem_tracks.stem_type`): non è un campo di
# `songs`, ma il pannello «✏️ Rinomina in massa» sa lavorare anche su questa, con
# le STESSE regole (sostituzione letterale, solo le righe che contengono il testo,
# annullabile con ↩️ Undo). Serve dopo un import a mano, quando le tracce arrivano
# con l'etichetta sbagliata (es. «canzone - Violino» → «Violino»).
STEM_LABEL_FIELD = "stem_type"
# Separatore con cui la libreria tiene più valori nello stesso campo
# (es. artist = "Bad Meets Evil / Eminem").
VALUE_SEPARATOR = " / "


def _pulisci_dopo_rimozione(testo):
    """Ripulisce quel che resta quando si porta via un pezzo di testo.

    Esempio: "Remember The Name (feat. 50 Cent)" → tolto "50 Cent" resta
    "(feat. )" → qui diventa "" e resta solo "Remember The Name"; vengono tolti
    anche i separatori rimasti orfani (" - ", " / ", ",") in testa o in coda.
    Funzione PURA (la usa `move_field_value`, testata da test_move_field).
    """
    s = re.sub(r"\s{2,}", " ", testo)
    # parentesi/quadre rimaste vuote, anche col solo "feat."/"ft."/"with" dentro
    s = re.sub(r"\s*[(\[]\s*(?:feat\.?|ft\.?|with)?\s*[)\]]", " ", s, flags=re.IGNORECASE)
    # separatore rimasto appeso prima di una parentesi chiusa:
    # "The Anthem (feat. RZA & )" → "The Anthem (feat. RZA)"
    s = re.sub(r"\s*[&,;/\-–—]\s*([)\]])", r"\1", s)
    # "feat." rimasto appeso senza parentesi (es. "Titolo - feat.")
    s = re.sub(r"\s*[-–—,]\s*(?:feat\.?|ft\.?)\s*$", "", s, flags=re.IGNORECASE)
    # separatori doppi rimasti in mezzo: "A - / B" → "A / B"
    s = re.sub(r"([-–—/,;])\s*[-–—/,;]", r"\1", s)
    # separatori orfani in testa e in coda
    s = re.sub(r"^\s*[-–—/,;]\s*", "", s)
    s = re.sub(r"\s*[-–—/,;]\s*$", "", s)
    return s.strip()


def move_field_value(old_from, old_to, text, mode="append", whole_word=True,
                     pulisci=True, numerico=False):
    """Sposta `text` dal campo `old_from` al campo `old_to` (funzione PURA).

    Restituisce (nuovo_valore_sorgente, nuovo_valore_destinazione) oppure
    (None, None) quando la riga va **saltata**: testo non presente, campo
    sorgente che resterebbe vuoto, o destinazione numerica già occupata.
    - mode="append"  → il testo si AGGIUNGE alla destinazione (con " / "),
      senza duplicarlo se c'è già;
    - mode="replace" → il testo SOSTITUISCE il valore della destinazione;
    - whole_word     → sposta solo la parola intera ("Ever" non tocca "Forever");
    - pulisci        → ripulisce parentesi/separatori rimasti vuoti;
    - numerico       → in "append" scrive solo se la destinazione è vuota.
    """
    src, dst = (old_from or ""), (old_to or "")
    testo = (text or "").strip()
    if not testo:
        return None, None
    if not re.search(re.escape(testo), src, flags=re.IGNORECASE):
        return None, None
    pattern = rf"(?<!\w){re.escape(testo)}(?!\w)" if whole_word else re.escape(testo)
    nuovo_src = re.sub(pattern, " ", src, flags=re.IGNORECASE)
    if pulisci:
        nuovo_src = _pulisci_dopo_rimozione(nuovo_src)
    else:
        nuovo_src = re.sub(r"\s{2,}", " ", nuovo_src).strip()
    if not nuovo_src:
        return None, None  # il campo conteneva SOLO quel testo: non lo svuoto
    if nuovo_src == src:
        # Nessuna occorrenza valida (es. "Ever" dentro "Forever" con "solo parola
        # intera"): NON si tocca la destinazione, altrimenti il nome finirebbe
        # aggiunto agli artisti senza essere tolto dal titolo.
        return None, None
    if mode == "replace":
        nuovo_dst = testo
    elif not dst:
        nuovo_dst = testo
    elif numerico:
        return None, None  # destinazione numerica già piena: non la sovrascrivo
    elif testo.lower() in [p.strip().lower() for p in re.split(r"[,/]", dst)]:
        nuovo_dst = dst  # già presente (a meno di maiuscole): non lo duplico
    else:
        nuovo_dst = dst + VALUE_SEPARATOR + testo
    if nuovo_src == src and nuovo_dst == dst:
        return None, None
    return nuovo_src, nuovo_dst


def _mass_rename_etichette_stem(find, replace):
    """✏️ Rinomina in massa le ETICHETTE delle tracce (`stem_tracks.stem_type`).

    Stesso pannello e stesse regole di `mass_rename` sui campi di `songs`
    (sostituzione letterale, solo le righe che contengono il testo) e stesso ↩️
    Undo, perché lo snapshot è quello dell'intero database. Esempio: dopo un
    import a mano le tracce si chiamano «canzone - violino» e si riportano a
    «violino» con find «canzone - » e replace vuoto.
    """
    before = db_snapshot()
    updated = []
    try:
        with get_db() as conn:
            rows = conn.execute(
                "SELECT id, session_id, stem_type, file_path FROM stem_tracks WHERE stem_type LIKE ?",
                (f"%{find}%",)).fetchall()
            for r in rows:
                old = r["stem_type"] or ""
                new = old.replace(find, replace)
                if new != old:
                    conn.execute("UPDATE stem_tracks SET stem_type=? WHERE id=?", (new, r["id"]))
                    updated.append({"id": r["id"], "old": old, "new": new,
                                    "file": os.path.basename(str(r["file_path"] or "")),
                                    "session_id": r["session_id"]})
    except Exception as e:
        _drop_snapshot(before)
        return jsonify({"error": str(e)}), 500
    if updated:
        push_undo(before, db_snapshot(),
                  f"Rinomina in massa «{find}» → «{replace}» ({len(updated)} tracce, {STEM_LABEL_FIELD})")
    else:
        _drop_snapshot(before)
    return jsonify({"updated": updated, "count": len(updated), "field": STEM_LABEL_FIELD,
                    **_history()})


@app.route("/db/mass_rename", methods=["POST"])
def mass_rename():
    """Apply find/replace on a specific field across all songs

    Salva uno snapshot prima/dopo: l'operazione è annullabile con ↩️ Undo
    (prima non lo era: una sostituzione sbagliata — es. "50 Cent" → "51 Cent"
    su 35 righe, 17/09/2026 — restava scritta nel database).

    Con `field: "stem_type"` lavora sulle ETICHETTE delle tracce separate
    (`stem_tracks`, vedi `_mass_rename_etichette_stem`): è il modo per correggere
    in blocco i nomi arrivati da una cartella di stem caricata a mano.
    """
    data = request.json or {}
    field = data.get("field", "title")
    find = data.get("find", "")
    replace = data.get("replace", "")
    if field != STEM_LABEL_FIELD and field not in BULK_FIELDS:
        return jsonify({"error": "Campi consentiti: " + ", ".join(BULK_FIELDS + [STEM_LABEL_FIELD])}), 400
    if not find:
        return jsonify({"error": "find richiesto"}), 400
    if field == STEM_LABEL_FIELD:
        return _mass_rename_etichette_stem(find, replace)
    before = db_snapshot()
    updated = []
    try:
        with get_db() as conn:
            rows = conn.execute(f"SELECT id, {field} FROM songs WHERE {field} LIKE ?", (f"%{find}%",)).fetchall()
            for r in rows:
                old = r[field] or ""
                new = old.replace(find, replace)
                if new != old:
                    conn.execute(f"UPDATE songs SET {field}=?, updated_at=datetime('now') WHERE id=?", (new, r["id"]))
                    updated.append({"id": r["id"], "old": old, "new": new})
    except Exception as e:
        _drop_snapshot(before)
        return jsonify({"error": str(e)}), 500
    if updated:
        after = db_snapshot()
        push_undo(before, after, f"Rinomina in massa «{find}» → «{replace}» ({len(updated)} righe, {field})")
    else:
        _drop_snapshot(before)
    return jsonify({"updated": updated, "count": len(updated), **_history()})

@app.route("/db/move_field", methods=["POST"])
def move_field():
    """➡️ Sposta un testo da un campo a un altro, su tutte le righe che lo contengono.

    Esempi: «Eminem» dal titolo agli artisti; «1999» dal titolo al campo anno.
    Con `dry_run: true` fa SOLO l'anteprima (nessuna scrittura: la usa la pagina
    per mostrare cosa cambierebbe prima di applicare). L'operazione vera salva
    uno snapshot prima/dopo, quindi è annullabile con ↩️ Undo (come /db/execute).
    """
    data = request.json or {}
    from_field = (data.get("from_field") or "").strip()
    to_field = (data.get("to_field") or "").strip()
    text = (data.get("text") or "").strip()
    mode = data.get("mode") or "append"
    whole_word = bool(data.get("whole_word", True))
    pulisci = bool(data.get("clean", True))
    dry_run = bool(data.get("dry_run", False))

    if from_field not in BULK_FIELDS or to_field not in BULK_FIELDS:
        return jsonify({"error": "Campi consentiti: " + ", ".join(BULK_FIELDS)}), 400
    if from_field == to_field:
        return jsonify({"error": "«Da» e «a» devono essere due campi diversi"}), 400
    if not text:
        return jsonify({"error": "Scrivi cosa spostare (es. Eminem, oppure 1999)"}), 400
    if mode not in ("append", "replace"):
        return jsonify({"error": "Modalità non valida"}), 400
    numerico = to_field in NUMERIC_FIELDS
    if numerico and not re.fullmatch(r"\d{1,4}", text):
        return jsonify({"error": f"«{to_field}» è un campo numerico: si sposta solo una cifra (es. 1999)"}), 400

    before = None if dry_run else db_snapshot()
    updated, skipped = [], 0
    try:
        with get_db() as conn:
            rows = conn.execute(
                f"SELECT id, {from_field} AS f, {to_field} AS t FROM songs WHERE {from_field} LIKE ?",
                (f"%{text}%",),
            ).fetchall()
            for r in rows:
                new_from, new_to = move_field_value(r["f"], r["t"], text, mode=mode,
                                                    whole_word=whole_word,
                                                    pulisci=pulisci, numerico=numerico)
                if new_from is None:
                    skipped += 1
                    continue
                updated.append({"id": r["id"], "old_from": r["f"], "new_from": new_from,
                                "old_to": r["t"], "new_to": new_to})
                if dry_run:
                    continue
                if (new_to or "") != (r["t"] or ""):
                    conn.execute(
                        f"UPDATE songs SET {from_field}=?, {to_field}=?, updated_at=datetime('now') WHERE id=?",
                        (new_from, new_to, r["id"]),
                    )
                else:
                    conn.execute(
                        f"UPDATE songs SET {from_field}=?, updated_at=datetime('now') WHERE id=?",
                        (new_from, r["id"]),
                    )
    except Exception as e:
        _drop_snapshot(before)
        return jsonify({"error": str(e)}), 500

    if not dry_run:
        if updated:
            after = db_snapshot()
            push_undo(before, after, f"Sposta «{text}»: {from_field} → {to_field} ({len(updated)} righe)")
        else:
            _drop_snapshot(before)

    return jsonify({
        "dry_run": dry_run,
        "count": len(updated),
        "skipped": skipped,
        "updated": updated[:50],
        "message": ("Anteprima: nessuna riga scritta" if dry_run else
                    f"{len(updated)} righe aggiornate" + (f", {skipped} saltate" if skipped else "")),
        **_history(),
    })

# ── DB: ADD FROM FILE (upload) ────────────────────────────────────────────────
@app.route("/db/add_local", methods=["POST"])
def add_local_file():
    """Register a local file in the DB (after user uploads/selects it).

    `yt_meta` (19/09/2026): i dati del video YouTube che ha prodotto questo file.
    La pagina li prende da `/status/<job>` — l'`info_dict` di yt-dlp resta scritto
    nel job (vedi `_do_download`) — e con quelli la riga nasce già con data di
    caricamento, canale, tag, descrizione, viste e miniatura; poi si completa DA
    SOLA dal video: copertina dalla miniatura e VIDEO MP4
    (`arricchisci_riga_dal_video`). `youtube_url` è il LINK del video scaricato.

    Senza `yt_meta` (un file caricato dal computer, o le pagine vecchie) il
    comportamento è quello di sempre: si registra e basta, nessun download.
    """
    data = request.json or {}
    filename = data.get("filename", "").strip()
    if not filename:
        return jsonify({"error": "filename richiesto"}), 400
    campi = data.get("yt_meta") if isinstance(data.get("yt_meta"), dict) else None
    url = (data.get("youtube_url") or "").strip()
    if not is_youtube_url(url):
        url = ""
    raw = clean_filename(filename)
    parts = raw.split(" - ", 1)
    artist = parts[0].strip() if len(parts) == 2 else ""
    title = parts[1].strip() if len(parts) == 2 else raw
    with get_db() as conn:
        sid = get_or_create_song_db(conn, title, artist, url, local_file=filename,
                                    extra=campi)
    arricchimento = arricchisci_riga_dal_video(sid, campi) if campi else None
    # La riga si rilegge DOPO l'arricchimento: così nella risposta si vedono i
    # campi e la copertina appena scritti (la pagina li mostra).
    with get_db() as conn:
        s = row2dict(conn.execute("SELECT * FROM songs WHERE id=?", (sid,)).fetchone())
    if arricchimento:
        s["arricchimento"] = arricchimento
    return jsonify(s)

# ── DB: ADD FROM ONYX PLAYER ──────────────────────────────────────────────────
@app.route("/db/from_onyx", methods=["POST"])
def db_from_onyx():
    """Registra un brano caricato nel player Onyx nel database principale."""
    data = request.json or {}
    title = (data.get("title") or data.get("name") or "").strip()
    artist = (data.get("artist") or "").strip()
    if not title or not artist:
        return jsonify({"error": "title e artist richiesti"}), 400
    local_file = (data.get("local_file") or "").strip()
    with get_db() as conn:
        sid = get_or_create_song_db(conn, title, artist, local_file=local_file, duration=data.get("duration"))
        allowed = [
            "album", "album_artist", "composer", "producers", "genre", "year",
            "release_date", "track_number", "disc_number", "bpm", "musical_key",
            "comment", "lyrics", "duration",
        ]
        for f in allowed:
            if f in data and data[f] is not None and data[f] != "":
                conn.execute(f"UPDATE songs SET {f}=?, updated_at=datetime('now') WHERE id=?", (data[f], sid))
        if local_file:
            conn.execute("UPDATE songs SET local_file=?, updated_at=datetime('now') WHERE id=?", (local_file, sid))
        s = row2dict(conn.execute("SELECT * FROM songs WHERE id=?", (sid,)).fetchone())
    # Anche qui: riga nel database senza file locale → il download parte da sé e
    # il file si aggancia a QUESTA riga (19/09/2026).
    if not local_file:
        job, motivo = avvia_download_canzone(sid)
        if job:
            s["download_job"], s["download_motivo"] = job, motivo
    return jsonify(s)

# ── DB: QUERY / SCRIPT PERSONALIZZATI (con UNDO/REDO) ────────────────────────
# ATTENZIONE: funzionalità per uso locale/sviluppo. L'esecuzione di script
# Python arbitrari è potenzialmente pericolosa: NON esporre queste rotte
# pubblicamente senza autenticazione e limitazioni severe.
# Prima di ogni operazione che modifica il database (UPDATE o script) viene
# salvato uno snapshot completo del DB: con /db/undo e /db/redo puoi
# annullare/ripetere le ultime operazioni.
# Regole del pannello SQL/script: usate da /db/execute e mostrate dalla legenda
# (/db/schema), così pagina e backend restano d'accordo su cosa è permesso.
SQL_ALLOWED = ["SELECT", "UPDATE"]
SQL_FORBIDDEN = ["DROP", "ALTER", "CREATE", "DELETE", "INSERT", "TRUNCATE", "REPLACE"]


def sql_consentita(sql):
    """Il pannello SQL può eseguire questa query? Ritorna "" se va bene,
    altrimenti il messaggio d'errore da mostrare.

    Consentite solo SELECT e UPDATE. Una parola vietata conta se è un COMANDO,
    non se è una funzione: così `replace(testo, ' / ', ' , ')` — che serve a
    correggere gli artisti e i titoli — passa, mentre `REPLACE INTO …` resta
    bloccato (dopo la parola non c'è una parentesi).
    """
    sql_upper = sql.upper().strip()
    if not any(sql_upper.startswith(w) for w in SQL_ALLOWED):
        return "Sono consentite solo " + " e ".join(SQL_ALLOWED)
    for w in SQL_FORBIDDEN:
        if re.search(rf"\b{w}\b(?!\s*\()", sql_upper):
            return "Operazione non consentita"
    return ""
# Variabili disponibili dentro lo script Python (stesse di `safe_globals`) e
# funzioni di base; SCRIPT_TIMEOUT è il tempo massimo di esecuzione.
SCRIPT_GLOBALS = ["conn", "db_path", "re", "time", "json", "sqlite3", "os", "math", "hashlib"]
SCRIPT_BUILTINS = ["print", "len", "str", "int", "float", "bool", "dict", "list", "tuple",
                   "set", "range", "enumerate", "zip", "sorted", "min", "max", "sum",
                   "abs", "round", "repr", "isinstance"]
SCRIPT_TIMEOUT = 30

SNAP_DIR = os.path.join(BASE_DIR, ".snapshots")
os.makedirs(SNAP_DIR, exist_ok=True)
MAX_UNDO = 30
undo_stack = []
redo_stack = []
SNAP_COUNTER = 0
# Pulizia di eventuali snapshot orfani di esecuzioni precedenti
for _f in os.listdir(SNAP_DIR):
    if _f.startswith("snap_") and _f.endswith(".db"):
        try: os.remove(os.path.join(SNAP_DIR, _f))
        except OSError: pass

def _snap_path():
    global SNAP_COUNTER
    SNAP_COUNTER += 1
    return os.path.join(SNAP_DIR, f"snap_{int(time.time())}_{SNAP_COUNTER}.db")

def db_snapshot():
    """Copia lo stato corrente del DB in un file temporaneo."""
    path = _snap_path()
    with DB_LOCK:
        src = sqlite3.connect(DB_PATH)
        dst = sqlite3.connect(path)
        try:
            src.backup(dst)
        finally:
            dst.close(); src.close()
    return path

def db_restore(path, attempts=4):
    """Ripristina il DB dallo snapshot (con retry in caso di lock)."""
    last = None
    for _ in range(attempts):
        try:
            with DB_LOCK:
                src = sqlite3.connect(path)
                dst = sqlite3.connect(DB_PATH)
                try:
                    src.backup(dst)
                finally:
                    dst.close(); src.close()
            return True
        except Exception as e:
            last = e
            time.sleep(0.3)
    raise last

def _drop_snapshot(path):
    if path:
        try: os.remove(path)
        except OSError: pass

def push_undo(before, after, label):
    undo_stack.append({"before": before, "after": after, "label": label})
    if len(undo_stack) > MAX_UNDO:
        old = undo_stack.pop(0)
        _drop_snapshot(old["before"]); _drop_snapshot(old["after"])
    while redo_stack:
        e = redo_stack.pop()
        _drop_snapshot(e["before"]); _drop_snapshot(e["after"])

def _history():
    return {"undo_remaining": len(undo_stack), "redo_available": len(redo_stack)}

@app.route("/db/execute", methods=["POST"])
def execute_custom():
    """Esegue una query SQL personalizzata (SELECT/UPDATE) oppure uno script
    Python con accesso al database. Nello script sono già disponibili:
    `conn` (connessione SQLite, con row_factory sqlite3.Row), `db_path`,
    `re`, `time`, `json`, `sqlite3`, `os`, `math`, `hashlib`."""
    data = request.json or {}
    sql = data.get("sql", "").strip()
    script = data.get("script", "").strip()

    if not sql and not script:
        return jsonify({"error": "Inserisci una query SQL o uno script Python"}), 400

    # ── Query SQL ──
    if sql:
        problema = sql_consentita(sql)
        if problema:
            return jsonify({"error": problema}), 400
        sql_upper = sql.upper().strip()
        try:
            if sql_upper.startswith("SELECT"):
                with get_db() as conn:
                    rows = conn.execute(sql).fetchall()
                return jsonify({
                    "type": "select",
                    "rows": [dict(r) for r in rows],
                    "count": len(rows),
                    **_history(),
                })
            # UPDATE → snapshot prima/dopo per consentire l'undo
            before = db_snapshot()
            with get_db() as conn:
                cur = conn.execute(sql)
            after = db_snapshot()
            push_undo(before, after, "UPDATE: " + sql[:90])
            return jsonify({
                "type": "update",
                "message": "Aggiornamento eseguito",
                "rowcount": cur.rowcount if cur.rowcount and cur.rowcount >= 0 else 0,
                **_history(),
            })
        except Exception as e:
            for p in (locals().get("before"), locals().get("after")):
                _drop_snapshot(p)
            return jsonify({"error": str(e)}), 500

    # ── Script Python ──
    import io, sys as _sys, threading as _threading
    buf = io.StringIO()
    holder = {"error": None}
    old_stdout = _sys.stdout
    _sys.stdout = buf

    before = db_snapshot()

    def run_script():
        try:
            with DB_LOCK:
                conn = sqlite3.connect(DB_PATH)
                conn.row_factory = sqlite3.Row
                try:
                    safe_globals = {
                        "__builtins__": {
                            "print": print, "len": len, "str": str, "int": int,
                            "float": float, "bool": bool, "dict": dict, "list": list,
                            "tuple": tuple, "set": set, "range": range,
                            "enumerate": enumerate, "zip": zip, "sorted": sorted,
                            "min": min, "max": max, "sum": sum, "abs": abs,
                            "round": round, "repr": repr, "isinstance": isinstance,
                            "__import__": __import__,
                            "re": re, "time": time, "json": json, "sqlite3": sqlite3,
                            "os": os, "math": math, "hashlib": hashlib,
                        },
                        "conn": conn,
                        "db_path": DB_PATH,
                    }
                    exec(script, safe_globals)
                    conn.commit()
                finally:
                    conn.close()
        except Exception as e:
            holder["error"] = str(e)

    t = _threading.Thread(target=run_script)
    t.start()
    t.join(timeout=SCRIPT_TIMEOUT)
    _sys.stdout = old_stdout

    if t.is_alive():
        _drop_snapshot(before)
        return jsonify({"error": f"Script timeout ({SCRIPT_TIMEOUT}s)"}), 500

    after = db_snapshot()
    first_line = script.strip().splitlines()[0][:60] if script.strip() else "Script"
    label = "Script: " + first_line
    if holder["error"]:
        label += " (errore)"
    push_undo(before, after, label)

    if holder["error"]:
        return jsonify({"error": holder["error"]}), 500
    return jsonify({"type": "script", "output": buf.getvalue(), **_history()})

@app.route("/db/undo", methods=["POST"])
def db_undo():
    """Annulla l'ultima operazione (ripristina lo snapshot 'before')."""
    if not undo_stack:
        return jsonify({"error": "Niente da annullare"}), 400
    entry = undo_stack.pop()
    try:
        db_restore(entry["before"])
    except Exception as e:
        undo_stack.append(entry)
        return jsonify({"error": f"Undo fallito: {e}"}), 500
    redo_stack.append(entry)
    return jsonify({"ok": True, "label": entry["label"], **_history()})

@app.route("/db/redo", methods=["POST"])
def db_redo():
    """Ripete l'ultima operazione annullata (ripristina lo snapshot 'after')."""
    if not redo_stack:
        return jsonify({"error": "Niente da rifare"}), 400
    entry = redo_stack.pop()
    try:
        db_restore(entry["after"])
    except Exception as e:
        redo_stack.append(entry)
        return jsonify({"error": f"Redo fallito: {e}"}), 500
    undo_stack.append(entry)
    return jsonify({"ok": True, "label": entry["label"], **_history()})

@app.route("/db/history", methods=["GET"])
def db_history():
    return jsonify({"undo": len(undo_stack), "redo": len(redo_stack)})


# ── DB: LEGENDA DEL PANNELLO SQL/SCRIPT (tabelle, campi, cose disponibili) ────
# Le descrizioni stanno qui, accanto agli endpoint, così restano allineate ai
# campi veri della tabella: la legenda in pagina le mostra in italiano.
TABLE_DOCS = {
    "songs": "La libreria: una riga per canzone (titolo, artisti, album, BPM, tonalità, crediti, testo, file locale…).",
    "sample_relations": "Campionamenti (WhoSampled): chi campiona chi — `derivative_song_id` = chi usa il sample, `source_song_id` = il brano campionato.",
    "stem_sessions": "Una sessione di separazione degli stem (Demucs) di un brano.",
    "stem_tracks": "Le singole tracce separate di una sessione: `stem_type` è l'etichetta (voce, batteria, basso, altro con Demucs; violino, pianoforte… per le cartelle di stem caricate a mano).",
    "audio_analyses": "Analisi audio salvate (MIDI + one-shot) usate dal confronto FORTISSIMO.",
    "playback_state": "Stato del player: UNA sola riga (id = 1) con brano, posizione, volume.",
}
COLUMN_DOCS = {"songs": {
    "id": "identificativo interno (song_…)",
    "title": "titolo del brano",
    "artist": "artisti separati da ' / ' (dopo la Verifica: crediti completi)",
    "album": "album",
    "album_artist": "artista dell'album",
    "composer": "compositori (da Genius)",
    "producers": "produttori in JSON: [\"Nome\", …]",
    "genre": "genere",
    "year": "anno (numero)",
    "release_date": "data di uscita (testo, es. 'October 1, 1999')",
    "track_number": "numero di traccia",
    "disc_number": "numero di disco",
    "compilation": "1 se è una compilation",
    "rating": "voto",
    "bpm": "BPM (numero; da Verifica o ffmpeg)",
    "musical_key": "tonalità (es. 'A# Minor')",
    "play_count": "quante volte è stato riprodotto",
    "comment": "commento libero",
    "lyrics": "testo del brano (da Genius)",
    "duration": "durata in secondi",
    "analyzed_status": "stato dell'analisi audio ('none' = mai analizzato)",
    "genius_url": "link Genius",
    "whosampled_url": "link WhoSampled",
    "youtube_url": "link YouTube",
    "tunebat_url": "link Tunebat",
    "cover_art_path": "file della copertina",
    "local_file": "nome del file audio in downloads/",
    "title_verified": "1 = titolo confermato (verde in pagina)",
    "artist_verified": "1 = artisti confermati",
    "bpm_verified": "1 = BPM confermato",
    "key_verified": "1 = tonalità confermata",
    "lyrics_verified": "1 = testo confermato",
    "genius_match_score": "somiglianza del match Genius (0-1)",
    "audio_match_esito": "conferma AUDIO: 'confermato'/'non confermato'/'ambiguo'/'non verificabile'",
    "audio_match_voti": "hash acustici allineati con l'anteprima ufficiale (più alto = più sicuro)",
    "audio_match_comuni": "hash in comune con l'anteprima (anche non allineati)",
    "audio_match_offset": "dove sta l'anteprima ufficiale dentro il file locale (secondi)",
    "audio_match_fonte": "anteprima usata: 'iTunes <id> · artista — titolo (durata)'",
    "audio_match_motivo": "PERCHÉ non si è potuto confrontare (es. 'nessuna anteprima ufficiale: iTunes 0 risultati per …'); vuoto quando il confronto è stato fatto",
    "audio_match_at": "quando è stato fatto il confronto audio",
    "ws_match_score": "somiglianza del match WhoSampled (0-1)",
    "ws_audio_esito": "conferma AUDIO del link WhoSampled ('confermato'/'non confermato'/'ambiguo'/'non verificabile')",
    "ws_audio_voti": "hash acustici allineati con l'anteprima ufficiale del candidato WhoSampled",
    "ws_audio_comuni": "hash in comune col candidato WhoSampled (anche non allineati)",
    "ws_audio_offset": "dove sta l'anteprima del candidato dentro il file locale (secondi)",
    "ws_audio_fonte": "anteprima usata per il link WhoSampled: 'iTunes <id> · artista — titolo'",
    "ws_audio_motivo": "PERCHÉ il confronto del link WhoSampled non si è potuto fare (vuoto se è stato fatto)",
    "ws_query": "cosa è stato cercato su WhoSampled per quest'ultimo verdetto (se il titolo cambia, la Verifica riprova)",
    "ws_audio_at": "quando è stato fatto il confronto audio del link WhoSampled",
    "genius_escluso": "1 = la canzone NON è su Genius (freestyle/mixtape): la Verifica salta la ricerca",
    "testo_esito": "conferma dal PARLATO (Whisper): 'confermato'/'non confermato'/'ambiguo'/'non verificabile'",
    "testo_voti": "percentuale di parole ascoltate che compaiono nel testo (0-100)",
    "testo_parole": "quante parole sono state riconosciute nella trascrizione",
    "testo_fonte": "testo usato per il confronto (pagina Genius) e come è stato trascritto (mix o a cappella)",
    "testo_motivo": "PERCHÉ il confronto dal parlato non si è potuto fare (vuoto se è stato fatto)",
    "testo_at": "quando è stato fatto il confronto dal parlato",
    "testo_trascrizione": "QUEL CHE SI SENTE: il testo trascritto da Whisper (è la colonna sinistra del confronto in /verifica)",
    "testo_riferimento": "il testo VERO usato come riferimento: le liriche di Genius, o la trascrizione dell'anteprima ufficiale quando le liriche non c'erano",
    "testo_parole_uniche": "parole UNICHE riconosciute: è il denominatore della percentuale (testo_parole conta anche i ritornelli ripetuti)",
    "testo_audio_nostro": "il file che è stato trascritto, relativo ('downloads/…' o 'anteprime/acapella_…/vocals.mp3'): si ascolta nel confronto in /verifica",
    "testo_audio_riferimento": "l'audio di riferimento confrontato (anteprima ufficiale), relativo a 'anteprime/'",
    "anteprima_file": "l'anteprima ufficiale di iTunes usata dal controllo audio (in 'anteprime/', cartella non versionata)",
    "video_file": "il VIDEO della canzone: nome del file in 'videos/' (MP4 scaricato da YouTube o caricato dal computer); vuoto = la canzone non ha un video",
    "yt_playlist": "la PLAYLIST YouTube da cui è arrivata la canzone (es. 'Remixes Collection Vol. 2'): la ricerca del tab Database cerca anche qui, così le righe di una playlist si ritrovano",
    "yt_video_id": "l'id del video YouTube (è l'`[id]` nel nome del file in downloads/)",
    "yt_title": "il titolo del video COSÌ COM'È su YouTube (può essere diverso dal titolo della riga: «[CINEMATIC] NF Type Beat…») — è quello che si vedrebbe aprendo il video",
    "yt_upload_date": "data di CARICAMENTO del video su YouTube ('YYYY-MM-DD'; è quella che dà l'anno della riga)",
    "yt_release_date": "data di uscita dichiarata dal video, quando c'è ('YYYY-MM-DD'; non è l'anno del brano: «Who Knew» è caricato nel 2018 ma è del 2000)",
    "yt_channel": "canale che ha pubblicato il video (o l'uploader)",
    "yt_channel_url": "link del canale",
    "yt_description": "la descrizione del video, intera, come l'ha scritta chi l'ha pubblicato",
    "yt_views": "visualizzazioni dichiarate al momento della lettura",
    "yt_likes": "like dichiarati al momento della lettura",
    "yt_comments": "commenti dichiarati al momento della lettura",
    "yt_tags": "tag del video, separati da ', '",
    "yt_category": "categoria YouTube (es. 'Music')",
    "yt_thumbnail": "URL della miniatura del video (un link, non un file in covers/)",
    "yt_duration": "durata dichiarata dal video (secondi)",
    "yt_meta_at": "quando questi dati del video sono stati letti (gli `yt_*` si riscrivono a ogni download, `year` no: si riempie solo se è vuoto)",
    "created_at": "quando è stata aggiunta",
    "updated_at": "ultima modifica",
}}


@app.route("/db/schema", methods=["GET"])
def db_schema():
    """📖 Legenda del pannello: tabelle e campi (con descrizione), numero di righe
    e comandi consentiti (SQL e script Python)."""
    tables = []
    with get_db() as conn:
        names = [r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name")]
        for name in names:
            columns = [{
                "name": c["name"],
                "type": c["type"] or "",
                "pk": bool(c["pk"]),
                "notnull": bool(c["notnull"]),
                "doc": COLUMN_DOCS.get(name, {}).get(c["name"], ""),
            } for c in conn.execute(f"PRAGMA table_info({name})")]
            tables.append({
                "name": name,
                "doc": TABLE_DOCS.get(name, ""),
                "count": conn.execute(f"SELECT COUNT(*) FROM {name}").fetchone()[0],
                "columns": columns,
            })
    return jsonify({
        "tables": tables,
        "bulk_fields": BULK_FIELDS,
        # Campo fuori da `songs` su cui sa lavorare lo stesso pannello ✏️ Rinomina
        # in massa: l'etichetta delle tracce separate (vedi mass_rename).
        "stem_label_field": STEM_LABEL_FIELD,
        "numeric_fields": sorted(NUMERIC_FIELDS),
        "sql": {"allowed": SQL_ALLOWED, "forbidden": SQL_FORBIDDEN},
        "script": {"globals": SCRIPT_GLOBALS, "builtins": SCRIPT_BUILTINS,
                   "timeout": SCRIPT_TIMEOUT},
    })

# ── DB: PULIZIA (file durata zero + duplicati per contenuto audio) ───────────
TRASH_DIR = os.path.join(BASE_DIR, ".trash")
os.makedirs(TRASH_DIR, exist_ok=True)

def move_to_trash(path):
    """Sposta un file nella cartella .trash (recuperabile) senza sovrascrivere."""
    base = os.path.basename(path)
    dest = os.path.join(TRASH_DIR, base)
    i = 1
    while os.path.exists(dest):
        dest = os.path.join(TRASH_DIR, f"{i}_{base}")
        i += 1
    os.rename(path, dest)
    return dest

def audio_fingerprint(filepath, n_points=512):
    """Analizza il contenuto audio REALE di un file (non il nome).

    Restituisce (fingerprint_normalizzato, durata_secondi) oppure None se il
    file è vuoto/corrotto (durata ≈ 0). Il fingerprint è il waveform mono a
    4 kHz (intero file) ridotto a n_points campioni e normalizzato in ampiezza:
    due brani identici hanno fingerprint quasi uguali.
    """
    if not FFMPEG or np is None:
        return None
    try:
        cmd = [FFMPEG, "-v", "error", "-i", filepath,
               "-ac", "1", "-ar", "4000", "-f", "f32le", "pipe:1"]
        p = subprocess.run(cmd, capture_output=True, timeout=180)
        if p.returncode != 0 or not p.stdout:
            return None
        arr = np.frombuffer(p.stdout, dtype=np.float32)
        if arr.size == 0:
            return None
        dur = arr.size / 4000.0
        if dur < 0.05:  # praticamente vuoto → durata zero
            return None
        if arr.size <= n_points:
            pts = arr
        else:
            idx = np.linspace(0, arr.size - 1, n_points).astype(int)
            pts = arr[idx]
        peak = float(np.max(np.abs(pts))) or 1.0
        return pts / peak, dur
    except Exception:
        return None

def find_duplicate_groups(fps, tolerance):
    """fps: lista di (song_id, fingerprint). Raggruppa in modo greedy i brani
    il cui contenuto audio differisce mediamente di meno di `tolerance`
    (0.05 = 5%). Restituisce i gruppi con più di un membro."""
    groups = []  # {"rep": fingerprint, "members": [song_id, ...]}
    for sid, pts in fps:
        placed = False
        for g in groups:
            diff = float(np.mean(np.abs(g["rep"] - pts)))
            if diff <= tolerance:
                g["members"].append(sid)
                placed = True
                break
        if not placed:
            groups.append({"rep": pts, "members": [sid]})
    return [g for g in groups if len(g["members"]) > 1]

# ── CONFERMA AUDIO DELLA VERIFICA (18/09/2026) ────────────────────────────────
# La Verifica abbina la canzone su Genius con un confronto TESTUALE e Genius NON
# ha audio: il match può quindi essere un falso positivo (misurato sui dati veri
# del 18/09/2026: `song_b6e7cc46b04c` "Fast Lane(Eminem & Royce Da 5'9 Remix)" è
# finita abbinata a due artisti sconosciuti con score 0,589, e la riga
# `song_7553a924d202` "1998 Freestyle" ha 0,754 — le due più basse in libreria).
# Per avere una prova che NON sia testuale si usa l'ANTEPRIMA UFFICIALE di 30 s
# di iTunes (API pubblica `itunes.apple.com/search`, nessuna chiave) e la si
# cerca DENTRO il file locale con un'impronta acustica stile Shazam:
#   1. spettrogramma (STFT) → picchi spettrali (i più forti per gruppo di
#      frequenze, così sono unici nella loro cella);
#   2. hash di coppie di picchi: (gruppo_f1, gruppo_f2, Δt fra i due);
#   3. istogramma degli scarti temporali fra gli hash delle due impronte: se è
#      lo stesso brano centinaia di hash si allineano allo STESSO offset, fra
#      brani diversi l'istogramma è piatto.
# Numeri misurati il 18/09/2026 con queste funzioni su *21 Questions* (50 Cent /
# Nate Dogg, file locale da 258,6 s contro anteprima ufficiale di 30,0 s):
# **2.525 hash allineati a 76,0 s** contro **5-9 hash** di 8 brani presi a caso
# dalla libreria (e 806 contro 16 sul caso sintetico del test). La funzione è
# indipendente da durata, tagli e master (nel file locale l'anteprima sta a 76 s
# perché il file è più lungo del disco ufficiale: 258,6 s contro 224,4 s).
# ⚠️ Le soglie qui sotto sono tarate su quelle misure: il primo tentativo usava i
# picchi "più forti del frame" (la banda dei bassi è la più forte in ogni istante)
# e un brano SBAGLIATO arrivava a 1.415 voti, cioè un falso positivo: da lì il
# massimo LOCALE in frequenza × tempo dentro `picchi_spettrali`.
# NIENTE nuove dipendenze: ffmpeg (già usato per le analisi) per la decodifica,
# numpy + librosa (già in requirements.txt) per spettrogramma e picchi.
ANTEPRIME_DIR = os.path.join(BASE_DIR, "anteprime"); os.makedirs(ANTEPRIME_DIR, exist_ok=True)
AUDIO_SR, AUDIO_HOP, AUDIO_FFT = 11025, 512, 2048
AUDIO_BIN_HASH = 8            # frequenze raggruppate a 8 a 8 (≈43 Hz per gruppo)
AUDIO_RAGGIO_FREQ = 3         # picco = massimo locale su ±3 gruppi (≈±130 Hz)
AUDIO_RAGGIO_TEMPO = 7        # picco = massimo locale su ±7 frame (≈±0,32 s)
AUDIO_DT_MAX = 64             # "target zone": 3 s (un frame = 46,4 ms)
AUDIO_COPPIE = 4              # accoppiamenti massimi per picco
AUDIO_SOGLIA_DB = -55.0       # picchi più deboli di così sono rumore
AUDIO_VOTI_CONFERMA = 50      # hash allineati per dire "audio confermato"
AUDIO_VOTI_RIFIUTO = 20       # ≤ questo: l'anteprima NON è nel file (il massimo
                              # misurato su un brano sbagliato è 16; sul brano
                              # giusto il minimo è 806 — vedi il commento sopra)
AUDIO_SCORE_SOSPETTO = 0.95   # match Genius sotto questa soglia → si controlla l'audio


def _massimo_del_vicinato(matrice, raggio, asse):
    """Massimo dei VICINI (esclusa la cella stessa) entro `raggio` lungo un asse.

    Serve a dire "questa cella spicca": il massimo mobile normale comprende la
    cella, quindi un confronto stretto non troverebbe mai nessun picco (misurato:
    zero picchi su tutta la libreria). Padding a -inf per non leggere fuori bordo.
    """
    if raggio <= 0:
        return np.full_like(matrice, -np.inf)
    imbottitura = [(0, 0)] * matrice.ndim
    imbottitura[asse] = (raggio, raggio)
    P = np.pad(matrice, imbottitura, mode="constant", constant_values=-np.inf)
    lunghezza = matrice.shape[asse]
    out = np.full_like(matrice, -np.inf)
    for d in range(-raggio, raggio + 1):
        if d == 0:
            continue                      # la cella non è un vicino di se stessa
        out = np.maximum(out, P.take(range(raggio + d, raggio + d + lunghezza), axis=asse))
    return out


def picchi_spettrali(spettro_db, n_picchi=5, soglia_db=AUDIO_SOGLIA_DB,
                     raggio_freq=AUDIO_RAGGIO_FREQ, raggio_tempo=AUDIO_RAGGIO_TEMPO):
    """Funzione PURA. Picchi dello spettrogramma in dB: un picco è il massimo
    LOCALE della sua cella (frequenza × tempo, dopo aver raggruppato le frequenze
    a blocchi di AUDIO_BIN_HASH), non semplicemente la banda più forte del frame.

    Perché il massimo locale e non "i più forti del frame": in un brano la banda
    dei bassi è la più forte in OGNI istante, quindi sceglierla sempre produce
    hash che si ripetono identici e falsi positivi (misurato: un brano sbagliato
    arrivava a 1.415 voti). Un picco vero è un evento che spicca anche nel suo
    intorno: così gli hash seguono gli attacchi del brano.

    Restituisce (frame, gruppo_frequenza, ampiezza) per ogni picco, al massimo
    `n_picchi` per istante, dal più forte al più debole.
    """
    if spettro_db is None or getattr(spettro_db, "size", 0) == 0:
        return []
    n_freq, n_frame = spettro_db.shape
    gruppi = n_freq // AUDIO_BIN_HASH
    if gruppi == 0:
        return []
    # massimo per (gruppo di frequenze, istante): vettoriale, niente cicli sulle frequenze
    M = spettro_db[:gruppi * AUDIO_BIN_HASH].reshape(gruppi, AUDIO_BIN_HASH, n_frame).max(axis=1)
    # un picco deve essere il massimo nel suo intorno in frequenza E in tempo
    # (confronto STRETTO coi vicini: una banda costante non "spicca" e non è un picco)
    e_massimo_freq = M > _massimo_del_vicinato(M, raggio_freq, 0)
    e_massimo_tempo = M > _massimo_del_vicinato(M, raggio_tempo, 1)
    picchi = []
    for t in range(n_frame):
        colonna = M[:, t]
        forti = np.flatnonzero((colonna > soglia_db) & e_massimo_freq[:, t] & e_massimo_tempo[:, t])
        if forti.size == 0:
            continue
        for g in forti[np.argsort(colonna[forti])[::-1][:n_picchi]]:
            picchi.append((t, int(g), float(colonna[g])))
    return picchi


def hash_da_picchi(picchi, dt_max=AUDIO_DT_MAX, coppie=AUDIO_COPPIE):
    """Funzione PURA. Da (frame, gruppo, ampiezza) agli hash stile Shazam: ogni
    picco fa da àncora e si accoppia con i `coppie` picchi che lo seguono entro
    `dt_max` frame. Restituisce [((g1, g2, dt), frame_àncora), …]."""
    ordinati = sorted(picchi, key=lambda p: p[0])
    hashes = []
    for i, (t1, g1, _) in enumerate(ordinati):
        presi = 0
        for t2, g2, _ in ordinati[i + 1:]:
            dt = t2 - t1
            if dt > dt_max:
                break                     # ordinati per tempo: oltre non serve guardare
            if dt <= 0:
                continue                  # picchi dello stesso istante: nessun Δt da confrontare
            hashes.append(((g1, g2, dt), t1))
            presi += 1
            if presi >= coppie:
                break
    return hashes


def istogramma_offset(hash_locali, hash_anteprima, hop=AUDIO_HOP, sr=AUDIO_SR):
    """Funzione PURA. Confronta due impronte e restituisce (voti, offset, comuni).

    `voti` = il massimo numero di hash che cadono sullo STESSO scarto temporale
    (locali − anteprima); `offset` = quello scarto in secondi, cioè dove sta
    l'anteprima dentro il file locale; `comuni` = quanti hash hanno combaciato in
    totale (comprese le coincidenze sparse, che non contano nulla).
    """
    indici = {}
    for h, t in hash_anteprima:
        indici.setdefault(h, []).append(t)
    voti = {}
    comuni = 0
    for h, t in hash_locali:
        for tp in indici.get(h, ()):
            comuni += 1
            delta = t - tp
            voti[delta] = voti.get(delta, 0) + 1
    if not voti:
        return 0, None, 0
    migliore = max(voti, key=voti.get)
    return voti[migliore], migliore * hop / float(sr), comuni


def esito_confronto_audio(voti, soglia_conferma=None, soglia_rifiuto=None):
    """Funzione PURA. Verdetto in parole dal confronto audio:
    - 'confermato' se gli hash allineati allo STESSO offset sono ≥ soglia_conferma;
    - 'ambiguo' se stanno fra soglia_rifiuto e soglia_conferma;
    - 'non confermato' se sono pochissimi (≤ soglia_rifiuto): l'anteprima ufficiale
      NON è dentro il file locale, quindi il match testuale di Genius è da rivedere
      (falso positivo, oppure remix/live/versione diversa).
    Le soglie sono quelle dell'app (AUDIO_VOTI_CONFERMA / AUDIO_VOTI_RIFIUTO) ma la
    pagina /verifica può passarne di proprie: sono le "tolleranze" che Alessandro
    vuole poter scegliere prima di lanciare la verifica.
    Il caso "non si è potuto provare" — nessuna anteprima ufficiale, file locale
    assente o non decodificabile — NON passa da qui: lo decide `conferma_audio` e
    vale 'non verificabile', così un dato mancante non diventa mai un verdetto.
    """
    conferma = AUDIO_VOTI_CONFERMA if soglia_conferma is None else float(soglia_conferma)
    rifiuto = AUDIO_VOTI_RIFIUTO if soglia_rifiuto is None else float(soglia_rifiuto)
    if voti >= conferma:
        return "confermato"
    if voti <= rifiuto:
        return "non confermato"
    return "ambiguo"

def _audio_mono(filepath, sr=AUDIO_SR):
    """Decodifica ffmpeg → float32 mono (numpy). None se ffmpeg/numpy mancano o il
    file è rotto: la conferma audio non deve mai far fallire la Verifica."""
    if not FFMPEG or np is None:
        return None
    try:
        p = subprocess.run([FFMPEG, "-v", "error", "-i", filepath, "-ac", "1",
                            "-ar", str(sr), "-f", "f32le", "pipe:1"],
                           capture_output=True, timeout=180)
    except Exception as e:
        print(f"[audio] decodifica fallita: {e}")
        return None
    if p.returncode != 0 or not p.stdout:
        return None
    arr = np.frombuffer(p.stdout, dtype=np.float32)
    return arr if arr.size else None


def spettrogramma_db(campioni, n_fft=AUDIO_FFT, hop=AUDIO_HOP):
    """Spettrogramma in dB (la base dei picchi). None se librosa non c'è."""
    if campioni is None or not HAS_LIBROSA or np is None:
        return None
    try:
        S = np.abs(librosa.stft(campioni, n_fft=n_fft, hop_length=hop))
        return librosa.amplitude_to_db(S, ref=np.max)
    except Exception as e:
        print(f"[audio] spettrogramma fallito: {e}")
        return None


def impronta_audio(campioni):
    """Impronta acustica (lista di hash) dei campioni decodificati: dipende solo
    dall'audio, mai dal nome del file. Lista vuota se non si può calcolare."""
    spettro = spettrogramma_db(campioni)
    if spettro is None:
        return []
    return hash_da_picchi(picchi_spettrali(spettro))


def _parole_artista(nome):
    """Minuscole, solo lettere/numeri con spazi singoli: serve a confrontare
    l'artista per PAROLE INTERE (`normalize` toglie anche gli spazi, e così
    "Ren" combaciava con "Rennes Choir")."""
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9]+", " ", (nome or "").lower())).strip()


def artista_compatibile(artisti, candidato, soglia=0.7):
    """Funzione PURA. Il candidato trovato è dello STESSO artista?

    In `match_score` l'artista pesa solo 0,20, quindi da solo non protegge:
    cercando "Control" di Big Sean, iTunes proponeva "Control (Kendrick Lamar
    Diss)" di *The Rap Mafia* — titolo quasi identico, artista diverso, e il
    confronto audio partiva contro il brano sbagliato (misurato il 18/09/2026).
    Si accetta se una parte dell'artista atteso (la libreria usa "A / B" per i
    feat.) compare come parola intera nel nome del candidato o viceversa, oppure
    se i due nomi sono simili (soglia 0,7 di `SequenceMatcher`).
    """
    from difflib import SequenceMatcher
    nome = _parole_artista(candidato)
    if not nome:
        return False
    for parte in re.split(r"\s*/\s*", artisti or ""):
        a = _parole_artista(parte)
        if not a:
            continue
        if a == nome:
            return True
        if re.search(r"(?<![a-z0-9])" + re.escape(a) + r"(?![a-z0-9])", nome):
            return True                     # "50 cent" dentro "50 cent feat nate dogg"
        if re.search(r"(?<![a-z0-9])" + re.escape(nome) + r"(?![a-z0-9])", a):
            return True                     # "50 cent" (candidato) dentro l'atteso
        if SequenceMatcher(None, a, nome).ratio() >= soglia:
            return True
    return False


def cerca_anteprima_itunes(artist, title, min_score=0.55, diagnostica=None):
    """Anteprima UFFICIALE della canzone da iTunes (API pubblica, senza chiave).

    Genius non ha audio: l'unico modo per sentire "ciò che Genius ha trovato" è
    l'anteprima del negozio. Restituisce il candidato col `match_score` migliore
    (stessa funzione e stessa soglia 0,55 usate dalle altre ricerche) **e con
    l'artista compatibile** (`artista_compatibile`), come dict {"preview_url",
    "track", "artist", "album", "durata", "id", "score"}: None se non c'è nessun
    candidato decente — meglio nessun verdetto che un verdetto sul brano sbagliato.

    Se si passa un dict in `diagnostica`, ci si scrive DENTRO perché la ricerca è
    fallita (quanti risultati, quanti scartati per artista, il migliore scartato,
    l'errore di rete): è quello che permette di scrivere il motivo nel database
    («nessuna anteprima ufficiale: iTunes 0 risultati per …») invece di un
    "non verificabile" che non spiega niente.
    """
    termine = " ".join(p for p in [(artist or "").strip(), (title or "").strip()] if p)
    if diagnostica is not None:
        diagnostica.update({"termine": termine, "risultati": 0, "con_anteprima": 0,
                            "artisti_scartati": 0, "migliore": None, "punteggio": None,
                            "errore": None})
    if not termine:
        if diagnostica is not None:
            diagnostica["errore"] = "nessun termine di ricerca (artista e titolo vuoti)"
        return None
    import urllib.request
    url = "https://itunes.apple.com/search?" + urllib.parse.urlencode(
        {"term": termine, "entity": "song", "limit": 5})
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "SampleLab/1.0 (+locale)"})
        with urllib.request.urlopen(req, timeout=15) as r:
            data = json.loads(r.read())
    except Exception as e:
        print(f"[anteprima] iTunes: {e}")
        if diagnostica is not None:
            diagnostica["errore"] = f"{type(e).__name__}: {e}"[:120]
        return None
    risultati = data.get("results", []) or []
    con_anteprima = [res for res in risultati if res.get("previewUrl")]
    migliore, punteggio, scartati = None, 0.0, 0
    for res in con_anteprima:
        if not artista_compatibile(artist, res.get("artistName", "")):
            scartati += 1
            continue
        sc = match_score(artist or "", title or "",
                         res.get("artistName", ""), res.get("trackName", ""))
        if sc > punteggio:
            migliore, punteggio = res, sc
    if diagnostica is not None:
        diagnostica.update({
            "risultati": len(risultati), "con_anteprima": len(con_anteprima),
            "artisti_scartati": scartati,
            "migliore": ("%s — %s" % (migliore.get("artistName", ""),
                                      migliore.get("trackName", ""))) if migliore else None,
            "punteggio": round(punteggio, 3) if migliore else None,
        })
    if not migliore:
        print(f"[anteprima] nessun candidato con l'artista compatibile per '{termine}'")
        return None
    if punteggio < min_score:
        print(f"[anteprima] candidato '{migliore.get('trackName', '')}' sotto la soglia "
              f"{min_score} per '{termine}'")
        return None
    return {
        "preview_url": migliore["previewUrl"],
        "track": migliore.get("trackName", ""),
        "artist": migliore.get("artistName", ""),
        "album": migliore.get("collectionName", ""),
        "durata": round((migliore.get("trackTimeMillis") or 0) / 1000.0, 1),
        "id": str(migliore.get("trackId") or ""),
        "score": round(punteggio, 3),
    }


def motivo_senza_anteprima(diagnostica, artista="", titolo="", min_score=0.55):
    """Funzione PURA. PERCHÉ non si è potuto confrontare, in una frase: è il testo
    che finisce in `songs.audio_match_motivo` / `ws_audio_motivo` e che la pastiglia
    mostra nel tooltip, così una riga spiegata da sé non chiede di fidarsi.

    Esempi: «nessuna anteprima ufficiale: iTunes 0 risultati per «50 Cent 1998
    Freestyle»», «…i 3 risultati con anteprima sono di altri artisti», «…«Shadi —
    1998 Freestyle» è troppo diverso (0.42 < 0.55)», «ricerca iTunes non riuscita: …».
    """
    d = diagnostica or {}
    termine = (d.get("termine") or "").strip() or " ".join(
        p for p in [(artista or "").strip(), (titolo or "").strip()] if p)
    if d.get("errore"):
        return f"ricerca iTunes non riuscita: {d['errore']}"
    risultati = d.get("risultati") or 0
    if not risultati:
        return f"nessuna anteprima ufficiale: iTunes 0 risultati per «{termine}»"
    con_anteprima = d.get("con_anteprima") or 0
    if not con_anteprima:
        return (f"nessuna anteprima ufficiale: {risultati} risultati su iTunes per "
                f"«{termine}» ma nessuno ha l'anteprima")
    if d.get("migliore"):
        return (f"nessuna anteprima ufficiale: «{d['migliore']}» è troppo diverso "
                f"({d.get('punteggio')} < {min_score}) per «{termine}»")
    return (f"nessuna anteprima ufficiale: i {con_anteprima} risultati con anteprima per "
            f"«{termine}» sono di altri artisti")


def scarica_anteprima(info):
    """Scarica l'm4a dell'anteprima in `anteprime/` (cartella NON versionata) e
    restituisce il percorso; None se il download fallisce. Se il file c'è già
    (stesso id iTunes) non lo riscarica: l'anteprima di una canzone non cambia."""
    if not info or not info.get("preview_url"):
        return None
    nome = re.sub(r"[^A-Za-z0-9_-]", "_",
                  "%s_%s" % (info.get("id") or "anteprima", info.get("track") or ""))[:80]
    dst = os.path.join(ANTEPRIME_DIR, nome + ".m4a")
    if os.path.exists(dst) and os.path.getsize(dst) > 2048:
        return dst
    import urllib.request
    try:
        req = urllib.request.Request(info["preview_url"],
                                     headers={"User-Agent": "SampleLab/1.0 (+locale)"})
        with urllib.request.urlopen(req, timeout=30) as r:
            dati = r.read()
    except Exception as e:
        print(f"[anteprima] download: {e}")
        return None
    if len(dati) < 2048:
        return None
    try:
        with open(dst, "wb") as f:
            f.write(dati)
    except Exception as e:
        print(f"[anteprima] scrittura: {e}")
        return None
    return dst


def confronto_audio_file(percorso_locale, percorso_anteprima):
    """Confronta DUE file audio e restituisce {"voti", "offset", "comuni", "hash"}
    (offset = dove sta l'anteprima dentro il file locale, in secondi).
    None se non si può fare (ffmpeg/librosa assenti o file illeggibili)."""
    yl = _audio_mono(percorso_locale)
    ya = _audio_mono(percorso_anteprima)
    if yl is None or ya is None:
        return None
    hl, ha = impronta_audio(yl), impronta_audio(ya)
    if not hl or not ha:
        return None
    voti, offset, comuni = istogramma_offset(hl, ha)
    return {"voti": int(voti), "offset": offset, "comuni": int(comuni), "hash": len(hl)}


def artista_identificabile_nel_titolo(artista, titolo, artisti_noti=None):
    """Funzione PURA. L'artista del candidato è riconoscibile nel titolo della riga
    (direttamente, o perché è un artista della libreria citato lì)?

    È la stessa regola che `fetch_genius` applica quando l'artista della riga è un
    segnaposto: serve a non prendere un omonimo ("Cha-Ching!" di Unique Salonga per
    il titolo *Cha-Ching*)."""
    norm_titolo = normalize(titolo or "")
    na = normalize(artista or "")
    if not na or not norm_titolo:
        return False
    if na in norm_titolo:
        return True
    noto = normalize(known_artist_in_title(titolo or "", artisti_noti or []) or "")
    return bool(noto) and (noto in na or na in noto)


def esito_whosampled(score, audio_esito, artista_mancante=False, titolo_univoco=False,
                     artista_identificabile=False, soglia=0.55):
    """Funzione PURA. Il link WhoSampled trovato si salva? → dict
    {"azione": 'salva'|'scarta', "rimuovi_url": bool, "motivo": testo}.

    Il punteggio testuale da solo NON basta: con l'artista vuoto o segnaposto
    `match_score` dà **1.0 all'artista** (`""` è contenuto in qualsiasi nome), e
    *End of the World* di "Brano locale" accettava così *The End of the World* di
    **Skeeter Davis** (un altro brano — l'audio lo dice: 8 hash contro 2.525 del
    caso giusto). Qui decide l'**AUDIO** quando esiste un'anteprima ufficiale;
    quando non esiste si salva solo se il match testuale è comunque informativo
    (artista confrontato davvero, oppure titolo univoco, oppure artista
    riconoscibile nel titolo). `rimuovi_url` dice se il link eventualmente già
    salvato va tolto: si toglie solo quando c'è una PROVA contraria (audio non
    confermato o ambiguo), mai per semplice mancanza di dati.
    """
    if score < soglia:
        return {"azione": "scarta", "rimuovi_url": False,
                "motivo": f"punteggio testuale basso ({score:.2f})"}
    if audio_esito == "confermato":
        return {"azione": "salva", "rimuovi_url": False, "motivo": "audio confermato"}
    if audio_esito == "non confermato":
        return {"azione": "scarta", "rimuovi_url": True,
                "motivo": "l'audio del candidato NON è dentro il file locale: probabile falso positivo"}
    if audio_esito == "ambiguo":
        return {"azione": "scarta", "rimuovi_url": True,
                "motivo": "audio ambiguo: da controllare a orecchio"}
    if artista_mancante and not (titolo_univoco or artista_identificabile):
        return {"azione": "scarta", "rimuovi_url": False,
                "motivo": "artista non confrontabile (segnaposto) e titolo non identificabile"}
    return {"azione": "salva", "rimuovi_url": False,
            "motivo": "nessuna anteprima ufficiale: match solo testuale"}


_SEGMENTI_NON_ARTISTA = {"search", "sample", "artist", "album", "track", "lists", "browse",
                         "submit", "news", "forum", "blog", "charts", "genres", "label",
                         "producer", "song", "video"}


def ws_da_cercare(url_salvato, verdetto_audio, query_memorizzata, query_corrente):
    """Funzione PURA. La Verifica deve (ri)cercare il link WhoSampled?

    - **nessun link salvato**: sì, a meno che l'ultima ricerca — con la STESSA query —
      abbia già scartato il candidato: rifare sarebbe un browser e un confronto audio
      per niente. Se però il titolo (o l'artista) è cambiato, la query è diversa e si
      **riprova** (è il caso di Alessandro: titolo corretto a mano → nuovo tentativo).
    - **link salvato ma senza verdetto audio**: sì, va messo alla prova (è così che si
      scopre una pagina sbagliata).
    - **link salvato con verdetto**: no, è già stato giudicato.
    """
    salvato = (url_salvato or "").strip()
    if not salvato:
        if (verdetto_audio or "") == "scartato" and (query_memorizzata or "") == (query_corrente or ""):
            return False
        return True
    return not (verdetto_audio or "")


def artista_titolo_da_whosampled_url(url):
    """Funzione PURA. Da 'https://www.whosampled.com/Skeeter-Davis/The-End-of-the-World/'
    → ('Skeeter Davis', 'The End of the World'). None se l'URL non ha la forma
    /Artista/Titolo/ (es. /search/, /sample/…). Serve a ricontrollare con l'audio
    un link già salvato, senza riaprire il browser."""
    m = re.match(r"^https?://(?:www\.)?whosampled\.com/([^/?#]+)/([^/?#]+)/?", url or "")
    if not m:
        return None
    if m.group(1).lower() in _SEGMENTI_NON_ARTISTA:
        return None

    def umano(slug):
        testo = urllib.parse.unquote(slug).replace("-", " ").replace("_", " ").strip()
        return re.sub(r"\s+", " ", testo)

    artista, titolo = umano(m.group(1)), umano(m.group(2))
    if not artista or not titolo:
        return None
    return artista, titolo


def verifica_audio_riferimento(percorso, artista, titolo, status=None, soglie=None):
    """Conferma AUDIO di un riferimento QUALSIASI (il match Genius, il candidato
    WhoSampled, un link già salvato…): cerca l'anteprima ufficiale di (artista,
    titolo) su iTunes e la cerca dentro il file locale.

    `soglie` = (voti_conferma, voti_rifiuto) per le "tolleranze" scelte nella pagina
    /verifica; None = quelle dell'app.

    Restituisce {"esito", "voti", "offset", "comuni", "fonte", "messaggio",
    "confronto", "motivo", "file_riferimento"}: `confronto` dice se il confronto è
    stato eseguito davvero (False = nessuna anteprima ufficiale, file illeggibile…),
    perché un dato mancante NON è un no; `file_riferimento` è il file dell'anteprima
    (None se non si è potuto scaricare) e serve a farlo ASCOLTARE nella pagina.
    `motivo` ∈ {'ok','file','anteprima','download','calcolo'}.
    """
    def segnala(testo):
        if status:
            try:
                status(testo)
            except Exception:
                pass

    def senza_confronto(codice, motivo_testo, emoji="⚪"):
        """Niente confronto → si registra PERCHÉ (il testo va nel campo `*_motivo`
        e nel messaggio: la riga si spiega da sé)."""
        return {"esito": "non verificabile", "voti": None, "offset": None, "comuni": None,
                "fonte": None, "messaggio": f"{emoji} {motivo_testo}", "confronto": False,
                "motivo": codice, "motivo_testo": motivo_testo, "file_riferimento": None}

    if not percorso or not os.path.exists(percorso):
        return senza_confronto("file", "audio non verificabile: manca il file locale in downloads/")

    segnala("🔊 Cerco l'anteprima ufficiale…")
    diagnostica = {}
    info = cerca_anteprima_itunes(artista, titolo, diagnostica=diagnostica)
    if not info:
        return senza_confronto("anteprima", motivo_senza_anteprima(diagnostica, artista, titolo))

    segnala("🔊 Scarico l'anteprima ufficiale…")
    anteprima_path = scarica_anteprima(info)
    if not anteprima_path:
        return senza_confronto("download", "anteprima ufficiale non scaricabile", "⚠️")

    segnala("🔊 Confronto l'audio del file locale con l'anteprima…")
    calcolo = confronto_audio_file(percorso, anteprima_path)
    if not calcolo:
        return senza_confronto("calcolo", "confronto audio non riuscito (decodifica o spettrogramma)", "⚠️")

    voti, comuni, offset = calcolo["voti"], calcolo["comuni"], calcolo["offset"]
    esito = esito_confronto_audio(voti, *(soglie or (None, None)))
    etichetta = f"{info['artist']} — {info['track']}"
    fonte = "iTunes %s · %s (%.1f s)" % (info["id"], etichetta, info["durata"] or 0)
    if esito == "confermato":
        messaggio = (f"✅ Audio confermato: {voti} hash allineati a {offset:.1f} s "
                     f"(anteprima ufficiale: {etichetta})")
    elif esito == "non confermato":
        messaggio = (f"❌ Audio NON confermato: solo {voti} hash allineati — l'anteprima "
                     f"ufficiale \"{etichetta}\" NON è dentro il file locale: possibile "
                     f"falso positivo (o versione diversa/remix)")
    else:
        messaggio = (f"🟡 Audio ambiguo: {voti} hash allineati ({comuni} in comune, soglia di "
                     f"conferma {AUDIO_VOTI_CONFERMA}) — da controllare a orecchio")
    return {"esito": esito, "voti": voti, "comuni": comuni,
            "offset": round(offset, 3) if offset is not None else None,
            "fonte": fonte[:200], "messaggio": messaggio, "confronto": True,
            "motivo": "ok", "motivo_testo": None,
            # il file dell'anteprima che è stata confrontata: si salva nel dato
            # (`anteprima_file`) così la pagina può farla SENTIRE
            "file_riferimento": anteprima_path}


def campi_dal_risultato_audio(risultato, prefisso="audio_match_"):
    """Funzione PURA. Dai campi di `verifica_audio_riferimento` alle colonne del
    database: con `prefisso="ws_"` si scrivono i campi del candidato WhoSampled."""
    return {
        prefisso + "esito": risultato["esito"],
        prefisso + "voti": risultato["voti"],
        prefisso + "comuni": risultato["comuni"],
        prefisso + "offset": risultato["offset"],
        prefisso + "fonte": risultato["fonte"],
        # PERCHÉ non si è potuto confrontare (NULL quando il confronto è stato fatto:
        # lì i numeri parlano da soli). È il testo che la pastiglia mostra nel tooltip.
        prefisso + "motivo": risultato.get("motivo_testo"),
        # come il resto del database: UTC (prima erano ora locale e la riga sembrava
        # modificata "prima" del verdetto quando si confrontavano i due timestamp)
        prefisso + "at": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S"),
    }


def conferma_audio(song, status=None, soglie=None):
    """Il passo 🔊 della Verifica sul match GENIUS: il file locale contiene
    l'anteprima ufficiale della canzone trovata su Genius?

    Restituisce (aggiornamenti, messaggio): i campi `audio_match_*` da scrivere nel
    database e la riga da mostrare in interfaccia. `soglie` = (conferma, rifiuto)
    sulle tolleranze scelte nella pagina /verifica. Non solleva MAI eccezioni: ogni
    intoppo diventa un messaggio ⚪/⚠️, perché la Verifica deve poter continuare.
    """
    locale = song.get("local_file") or ""
    percorso = os.path.join(DL_DIR, locale) if locale else ""
    artista = (song.get("artist") or "").split(" / ")[0].strip()
    # L'artista segnaposto ("Brano locale", "Artista sconosciuto") NON va nella
    # ricerca: "Brano locale End of the World" non trova nulla di utile (era uno
    # dei motivi per cui su queste righe la Verifica non trovava né album né data).
    if is_placeholder_artist(artista):
        artista = ""
    risultato = verifica_audio_riferimento(percorso, artista, song.get("title") or "",
                                           status, soglie)
    aggiornamenti = campi_dal_risultato_audio(risultato)
    # QUALE anteprima è stata confrontata si scrive nel dato: la pagina la fa
    # risentire accanto al nostro file (e nessuno deve indovinare il nome del file,
    # che contiene l'id iTunes).
    anteprima = percorso_relativo(risultato.get("file_riferimento"))
    if anteprima:
        aggiornamenti["anteprima_file"] = anteprima
    return aggiornamenti, risultato["messaggio"]



# ── CONFERMA DAL PARLATO (Whisper) — 18/09/2026 ───────────────────────────────
# Idea di Alessandro: «sentire effettivamente il testo che viene detto a parole e
# confrontarlo con quelli presunti di genius». Serve dove l'impronta audio non può
# arrivare (nessuna anteprima ufficiale: freestyle, mixtape). Misure del 18/09/2026
# su righe vere della libreria (modello `small`, CPU int8, VAD spento): *Get Up*
# 77,9% delle parole ascoltate dentro le sue liriche, *Simon Says* 76,6%,
# *ANTIPATICO* (italiano) 68,8%, mentre il brano di confronto sta sotto il 16,3% —
# e *Havana* (liriche di una pagina di traduzioni su audio inglese) sta al 10,9%,
# cioè il metodo scopre anche le liriche sbagliate. ⚠️ Le impostazioni contano più
# del metodo: col default (`base` + VAD attivo) due brani rendevano 18 e 3 parole
# utili, quindi qui si usa `vad_filter=False`, `no_speech_threshold=None`,
# `log_prob_threshold=None`, `condition_on_previous_text=False` e una GUARDIA sul
# numero di parole (sotto le 100 parole si resta a "non verificabile").
TESTI_MODELLO = os.environ.get("SAMPLELAB_WHISPER", "small")
TESTI_SOGLIA_CONFERMA = 40.0      # % di parole ascoltate presenti nel testo
TESTI_SOGLIA_RIFIUTO = 15.0       # sotto questa: si sta cantando un'altra cosa
TESTI_MIN_PAROLE = 100            # meno parole di così = trascrizione troppo povera
MODELLI_DIR = os.path.join(BASE_DIR, "modelli"); os.makedirs(MODELLI_DIR, exist_ok=True)
_whisper_cache = {}

# Parole che non distinguono un testo dall'altro (articoli, pronomi, "yeah"…):
# italiano e inglese, le due lingue della libreria.
STOPWORD = set("""a an the and or but if of to in on at for with from by is are was were be been being
it its this that these those you your i me my we our he she they them his her her as so not no
do does did done have has had will would can could should may might must just like all any there
here what when who whom which how why then than too very s t re ve ll d m o yeah uh ah oh
il lo la i gli le un uno una di da in con su per tra fra non che chi cui come dove quando e o ma
se anche solo piu meno molto poco io tu lui lei noi voi loro mi ti si ci vi ne""".split())


_SEZIONI_LIRICHE = {"intro", "chorus", "verse", "bridge", "outro", "hook", "refrain",
                    "pre-chorus", "prechorus", "post-chorus", "strofa", "ritornello",
                    "skit", "interlude", "part", "pre", "post", "repeat", "x2"}


def pulisci_annotazioni(testo):
    """Funzione PURA. Toglie le indicazioni di sezione delle liriche di Genius
    («[Chorus: Akon]», «[Verse 1: 50 Cent]», «[Ritornello]»): sono parole che
    nessuno canta e abbasserebbero la copertura (misurato: valgono ~10% delle
    parole del testo). Le parentesi quadre che NON sono sezioni restano."""
    def sostituisci(m):
        interno = m.group(1).strip().lower()
        primo = re.split(r"[:\-–]", interno)[0].strip()
        if primo in _SEZIONI_LIRICHE or (primo and primo.split()[0] in _SEZIONI_LIRICHE):
            return " "
        return m.group(0)
    return re.sub(r"\[([^\]]{0,80})\]", sostituisci, testo or "")


def parole_contenuto(testo):
    """Funzione PURA. Le parole che contano di un testo: minuscole, solo lettere e
    numeri, senza le indicazioni di sezione, senza le parole funzionali (STOPWORD) e
    senza i monosillabi."""
    testo = pulisci_annotazioni(testo).lower()
    for brutto, buono in (("’", "'"), ("`", "'"), ("–", " "), ("—", " ")):
        testo = testo.replace(brutto, buono)
    pulito = "".join(c if (c.isalnum() or c == "'") else " " for c in testo)
    return [p for p in pulito.split() if p not in STOPWORD and len(p) > 1]


def copertura_testo(parole_riferimento, parole_ascoltate):
    """Funzione PURA. Quanta parte del RIFERIMENTO si sente davvero (0-100).

    È unidirezionale di proposito: le liriche di Genius contengono anche le
    indicazioni delle sezioni («[Chorus: Akon]») e gli ad-lib che nessuno canta,
    quindi si misura se *ciò che si sente* copre il riferimento, non il contrario.
    """
    rif = set(p for p in (parole_riferimento or []) if p)
    ascoltate = set(p for p in (parole_ascoltate or []) if p)
    if not rif:
        return 0.0
    return round(100.0 * len(rif & ascoltate) / len(rif), 1)


def esito_testo(copertura, n_parole, soglia_conferma=TESTI_SOGLIA_CONFERMA,
                soglia_rifiuto=TESTI_SOGLIA_RIFIUTO, min_parole=TESTI_MIN_PAROLE):
    """Funzione PURA. Verdetto dal confronto del parlato:
    - 'non verificabile' se la trascrizione è troppo povera (meno di `min_parole`):
      lì non si può dire né sì né no (misurato: con le impostazioni sbagliate si
      scendeva a 3-18 parole e il verdetto sarebbe stato casuale);
    - 'confermato' se la copertura è ≥ `soglia_conferma`;
    - 'non confermato' se è ≤ `soglia_rifiuto`;
    - 'ambiguo' in mezzo.
    """
    if (n_parole or 0) < min_parole:
        return "non verificabile"
    if copertura >= soglia_conferma:
        return "confermato"
    if copertura <= soglia_rifiuto:
        return "non confermato"
    return "ambiguo"


def modello_whisper(nome=None):
    """Il modello Whisper, caricato una volta sola (il caricamento dura ~30 s).
    Restituisce None se la trascrizione non è disponibile (pacchetto non installato
    o modello non scaricabile): la Verifica deve poter continuare lo stesso."""
    if not HAS_WHISPER or _WhisperModel is None:
        return None
    nome = (nome or TESTI_MODELLO).strip() or "small"
    if nome not in _whisper_cache:
        try:
            _whisper_cache[nome] = _WhisperModel(nome, device="cpu", compute_type="int8",
                                                 download_root=(os.environ.get("SAMPLELAB_MODELLI") or None))
        except Exception as e:
            print(f"[whisper] modello non caricabile: {e}")
            return None
    return _whisper_cache[nome]


def a_cappella(percorso, timeout=900, avanza=None):
    """Estrae la VOCE con demucs (`--two-stems=vocals`: 1-3 minuti per brano) e
    restituisce il percorso dell'a cappella, oppure None. Si usa quando si vuole
    trascrivere SOLO la voce: sul mix la trascrizione funziona già (68-78% nel
    brano giusto) ma con la musica sotto sbaglia più parole.

    `avanza` riceve la frazione di lavoro fatta (0-1) leggendo l'avanzamento che
    demucs stampa da sé (le percentuali del suo tqdm su stderr): è una misura vera,
    non una stima — demucs sa quanti pezzi ha finito. Se supera `timeout` il
    processo viene ucciso e si restituisce None (come prima).
    """
    if not percorso or not os.path.exists(percorso):
        return None
    import tempfile
    cartella = tempfile.mkdtemp(prefix="acapella_", dir=ANTEPRIME_DIR)
    p = None
    try:
        p = subprocess.Popen(["python3", "-m", "demucs", "--two-stems=vocals", "--mp3",
                              "--mp3-bitrate", "320", "-o", cartella, percorso],
                             stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    except Exception as e:
        print(f"[demucs] {e}")
        return None
    # Si legge stderr pezzo per pezzo (demucs scrive il progresso con `\r`, quindi
    # niente `readline`): `select` con un secondo di pazienza serve a rispettare il
    # timeout anche se il processo resta muto.
    scadenza = time.time() + timeout
    coda = ""
    try:
        fd = p.stderr.fileno()
        while True:
            pronto, _, _ = select.select([fd], [], [], 1.0)
            if not pronto:
                if time.time() > scadenza:
                    p.kill()
                    print("[demucs] timeout")
                    return None
                continue
            blocco = os.read(fd, 512)
            if not blocco:
                break
            coda = (coda + blocco.decode("utf-8", "replace"))[-400:]
            if avanza:
                percentuali = re.findall(r"(\d{1,3})%", coda)
                if percentuali:
                    avanza(min(0.98, int(percentuali[-1]) / 100.0))
            if time.time() > scadenza:
                p.kill()
                print("[demucs] timeout")
                return None
        p.wait(timeout=30)
    except Exception as e:
        print(f"[demucs] {e}")
        try:
            p.kill()
        except Exception:
            pass
        return None
    if p.returncode != 0:
        print(f"[demucs] errore: uscita {p.returncode}")
        return None
    for radice, _, files in os.walk(cartella):
        for f in sorted(files):
            if f.startswith("vocals"):
                return os.path.join(radice, f)
    return None


def trascrivi(percorso, sorgente="mix", modello=None, avanza=None):
    """Trascrive un file e restituisce {"testo", "parole", "durata", "lingua",
    "fonte"} oppure None. `sorgente` = 'mix' (veloce) | 'a cappella' (demucs).

    `avanza` è una callback opzionale che riceve la frazione di lavoro fatta (0-1),
    per la barra di avanzamento della pagina: con l'a cappella la prima metà è demucs
    (col suo avanzamento vero) e la seconda è Whisper.
    """
    m = modello_whisper(modello)
    if m is None or not percorso or not os.path.exists(percorso):
        return None
    da_trascrivere, nota = percorso, "mix"
    avanza_whisper = avanza
    if sorgente == "a cappella":
        voce = a_cappella(percorso, avanza=(lambda f: avanza(0.5 * f)) if avanza else None)
        if voce:
            da_trascrivere, nota = voce, "a cappella"
            avanza_whisper = (lambda f: avanza(0.5 + 0.5 * f)) if avanza else None
    try:
        segmenti, info = m.transcribe(da_trascrivere, vad_filter=False,
                                      no_speech_threshold=None, log_prob_threshold=None,
                                      condition_on_previous_text=False)
        durata = getattr(info, "duration", None) or 0
        pezzi = []
        for seg in segmenti:
            pezzi.append(getattr(seg, "text", "").strip())
            # Il progresso VERO del passo più lungo: Whisper restituisce i segmenti in
            # ordine e ognuno sa dove finisce dentro l'audio, quindi la frazione già
            # trascritta è una misura e non una stima (brano di 4:18 → ~60-85 s).
            if avanza_whisper and durata:
                avanza_whisper(min(0.98, (getattr(seg, "end", 0) or 0) / durata))
        testo = " ".join(p for p in pezzi if p)
    except Exception as e:
        print(f"[whisper] trascrizione fallita: {e}")
        return None
    return {"testo": testo, "parole": parole_contenuto(testo),
            "durata": getattr(info, "duration", None),
            "lingua": getattr(info, "language", ""), "fonte": nota,
            # QUALE file è stato trascritto: se la sorgente è 'a cappella' è la voce
            # estratta da demucs (dentro `anteprime/`), non il file locale. Serve al
            # confronto in pagina: si ascolta esattamente quello che Whisper ha sentito.
            "file": da_trascrivere}


def verifica_testo_riferimento(percorso, riferimento, tipo="liriche", sorgente="mix",
                               status=None, soglie=None, min_parole=TESTI_MIN_PAROLE,
                               avanza=None):
    """Conferma dal PARLATO: quello che si sente è il testo che ci si aspetta?

    `riferimento` è il TESTO delle liriche (`tipo='liriche'`) oppure il percorso di
    un AUDIO ufficiale (`tipo='audio'`, es. l'anteprima iTunes). Restituisce
    {"esito", "copertura", "parole", "fonte", "motivo", "confronto", "messaggio"} più
    quello che serve a MOSTRARE il confronto nella pagina (`/db/songs/<id>/confronto`):
    `trascrizione` (quello che si sente), `riferimento_testo` (il testo vero usato),
    `file_nostro` (il file trascritto: mix o a cappella) e `file_riferimento` (l'audio
    ufficiale, quando il riferimento è un audio).

    La direzione della misura è scelta perché sia informativa in entrambi i casi:
    - con le LIRICHE (più lunghe di ciò che si sente) si misura quanta parte delle
      parole ASCOLTATE sta nel testo (misurato: 68-78% sul brano giusto, ≤16% su
      quello sbagliato);
    - con un AUDIO di riferimento (30 s di anteprima, più corto) si misura quanta
      parte delle parole del riferimento si sente nel nostro file.
    Non solleva mai: ogni intoppo diventa un verdetto "non verificabile" col motivo.
    """
    def segnala(testo):
        if status:
            try:
                status(testo)
            except Exception:
                pass

    def senza_confronto(codice, testo):
        # Anche quando il confronto non si fa, i campi del confronto esistono: la
        # pagina mostra il MOTIVO, non un pannello mezzo vuoto.
        return {"esito": "non verificabile", "copertura": None, "parole": None,
                "fonte": None, "motivo": testo, "confronto": False,
                "messaggio": f"⚪ {testo}", "codice": codice,
                "trascrizione": None, "riferimento_testo": None, "parole_uniche": None,
                "file_nostro": None, "file_riferimento": None}

    if not HAS_WHISPER:
        return senza_confronto("whisper", "conferma dal parlato non disponibile "
                                "(faster-whisper non è installato)")
    if not percorso or not os.path.exists(percorso):
        return senza_confronto("file", "conferma dal parlato non possibile: manca il file locale")

    segnala("🗣 Trascrivo il file locale" + (" (a cappella)" if sorgente == "a cappella" else "") + "…")
    # La barra: il nostro file occupa i primi 70% del passo (demucs incluso se serve),
    # l'eventuale audio di riferimento il resto.
    nostro = trascrivi(percorso, sorgente=sorgente,
                       avanza=(lambda f: avanza(0.7 * f)) if avanza else None)
    if not nostro:
        return senza_confronto("trascrizione", "trascrizione del file locale non riuscita")
    nota_sorgente = f"trascrizione {nostro['fonte']}"

    testo_rif, file_riferimento = "", None
    if tipo == "audio":
        if not riferimento or not os.path.exists(riferimento):
            return senza_confronto("riferimento", "nessun audio di riferimento da trascrivere")
        segnala("🗣 Trascrivo l'audio di riferimento…")
        altro = trascrivi(riferimento, sorgente=sorgente,
                          avanza=(lambda f: avanza(0.7 + 0.3 * f)) if avanza else None)
        if not altro:
            return senza_confronto("trascrizione", "trascrizione dell'audio di riferimento non riuscita")
        parole_rif = set(altro["parole"])
        copertura = copertura_testo(altro["parole"], nostro["parole"])
        # La guardia guarda il più corto dei due: se il riferimento ha poche parole,
        # il confronto non è affidabile nemmeno se il nostro file ne ha tante.
        n_guardia = min(len(parole_rif), len(nostro["parole"]))
        fonte = f"audio di riferimento ({altro['fonte']}, {len(parole_rif)} parole) · {nota_sorgente}"
        # il "testo vero" è la trascrizione dell'anteprima ufficiale: si salva anche
        # quella, altrimenti la colonna di destra del confronto resterebbe vuota
        testo_rif, file_riferimento = altro["testo"], riferimento
    else:
        parole_rif = set(parole_contenuto(riferimento or ""))
        if not parole_rif:
            return senza_confronto("liriche", "nessun testo di riferimento (liriche non disponibili)")
        copertura = copertura_testo(nostro["parole"], parole_rif)
        n_guardia = len(nostro["parole"])
        fonte = f"liriche ({len(parole_rif)} parole) · {nota_sorgente}"
        testo_rif = riferimento or ""

    conferma, rifiuto = soglie or (TESTI_SOGLIA_CONFERMA, TESTI_SOGLIA_RIFIUTO)
    esito = esito_testo(copertura, n_guardia, conferma, rifiuto, min_parole)
    base = {"esito": esito, "copertura": copertura, "parole": n_guardia, "fonte": fonte[:200],
            "confronto": True, "codice": "ok", "motivo": None,
            # Per la schermata «📄 Confronta»: i due testi e i DUE file da ascoltare.
            # `parole_uniche` è il denominatore vero della percentuale (i ritornelli
            # ripetuti gonfiano la lista delle parole riconosciute).
            "trascrizione": nostro.get("testo") or "",
            "riferimento_testo": testo_rif or "",
            "parole_uniche": len(set(nostro.get("parole") or [])),
            "file_nostro": nostro.get("file"),
            "file_riferimento": file_riferimento}
    if esito == "confermato":
        base["messaggio"] = (f"✅ Testo confermato: {copertura}% delle parole è nel testo atteso "
                             f"({n_guardia} parole riconosciute · {fonte})")
    elif esito == "non confermato":
        base["messaggio"] = (f"❌ Testo NON confermato: solo {copertura}% — quello che si sente "
                             f"non è questo testo ({n_guardia} parole · {fonte})")
    elif esito == "ambiguo":
        base["messaggio"] = (f"🟡 Testo ambiguo: {copertura}% ({n_guardia} parole · {fonte}) — "
                             f"da controllare a orecchio")
    else:
        base["messaggio"] = (f"⚪ Trascrizione troppo povera: {n_guardia} parole riconosciute "
                            f"(servono almeno {min_parole}) — {fonte}")
    return base


def percorso_relativo(percorso):
    """Funzione PURA. Il percorso da salvare nel database, relativo alla cartella
    dell'app: 'downloads/<file>' oppure 'anteprime/acapella_…/vocals.mp3'. Serve a
    ritrovare il file per farlo ASCOLTARE (rotta /stream o /anteprima) e a restare
    valido anche se la cartella dell'app viene spostata. None se è fuori o assente."""
    if not percorso:
        return None
    try:
        rel = os.path.relpath(percorso, BASE_DIR)
    except Exception:
        return None
    if rel.startswith(".."):
        return None
    return rel.replace(os.sep, "/")


def campi_dal_risultato_testo(risultato):
    """Funzione PURA. Dai campi di `verifica_testo_riferimento` alle colonne del
    database (`testo_*`), testi compresi: senza il testo trascritto e il riferimento
    la pagina non può mostrare il confronto (e i due file non si possono ascoltare)."""
    return {
        "testo_esito": risultato["esito"],
        "testo_voti": risultato["copertura"],
        "testo_parole": risultato["parole"],
        "testo_fonte": risultato["fonte"],
        "testo_motivo": risultato["motivo"],
        "testo_at": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S"),
        "testo_trascrizione": risultato.get("trascrizione"),
        "testo_riferimento": risultato.get("riferimento_testo"),
        "testo_parole_uniche": risultato.get("parole_uniche"),
        "testo_audio_nostro": percorso_relativo(risultato.get("file_nostro")),
        "testo_audio_riferimento": percorso_relativo(risultato.get("file_riferimento")),
    }


def run_cleanup(tolerance, progress=None):
    """Esegue la pulizia (durata zero + duplicati per contenuto audio).
    `progress` è una callback opzionale che riceve {"percent": int, "phase": str}.
    Restituisce un dict con i risultati. La cancellazione del DB è annullabile
    (push_undo) e i file vengono spostati in .trash."""
    def report(percent, phase):
        if progress:
            try: progress({"percent": percent, "phase": phase})
            except Exception: pass

    with get_db() as conn:
        songs = rows2list(conn.execute(
            "SELECT id, title, artist, local_file, duration FROM songs "
            "WHERE local_file IS NOT NULL AND local_file != ''").fetchall())

    total = len(songs)
    valid = []      # (song_id, fingerprint, durata, local_file)
    zero_dur = []   # (song_id, local_file)
    for i, s in enumerate(songs):
        report(int(i / total * 50) if total else 50, f"analisi audio {i+1}/{total}")
        fp = os.path.join(DL_DIR, s["local_file"])
        if not os.path.exists(fp):
            # File mancante sul disco → riga orfana: va eliminata dalla pulizia
            zero_dur.append((s["id"], s["local_file"]))
            continue
        res = audio_fingerprint(fp)
        if res is None:
            zero_dur.append((s["id"], s["local_file"]))
        else:
            valid.append((s["id"], res[0], res[1], s["local_file"]))

    report(55, "rilevamento duplicati")
    groups = find_duplicate_groups([(sid, pts) for sid, pts, dur, lf in valid], tolerance)

    to_delete_ids = set(sid for sid, _ in zero_dur)
    to_delete_files = set(lf for _, lf in zero_dur)
    for g in groups:
        members = [m for m in valid if m[0] in g["members"]]
        members.sort(key=lambda m: (-m[2], m[0]))  # mantieni durata più lunga
        keep = members[0]
        for m in members[1:]:
            to_delete_ids.add(m[0])
            to_delete_files.add(m[3])

    report(70, "snapshot ante (per undo)")
    before = db_snapshot()

    deleted_songs = []
    moved_files = []
    with get_db() as conn:
        for lf in sorted(to_delete_files):
            fp = os.path.join(DL_DIR, lf)
            if os.path.exists(fp):
                try:
                    move_to_trash(fp)
                    moved_files.append(lf)
                except Exception:
                    pass
        for sid in sorted(to_delete_ids):
            r = conn.execute("SELECT title, artist FROM songs WHERE id=?", (sid,)).fetchone()
            if r:
                deleted_songs.append(f"{r['artist']} - {r['title']}")
            conn.execute("DELETE FROM songs WHERE id=?", (sid,))

    report(90, "snapshot post")
    after = db_snapshot()
    n_dups = sum(len(g["members"]) - 1 for g in groups)
    push_undo(before, after, f"Cleanup: {len(zero_dur)} durata zero, {n_dups} duplicati")

    return {
        "zero_duration": len(zero_dur),
        "duplicate_groups": len(groups),
        "duplicates_removed": n_dups,
        "deleted_songs": len(deleted_songs),
        "moved_files": len(moved_files),
        "deleted_list": deleted_songs[:60],
        "trash_dir": TRASH_DIR,
        "undo_remaining": len(undo_stack),
    }

@app.route("/db/cleanup", methods=["POST"])
def db_cleanup():
    """Avvia un job di pulizia in background:
    1) elimina i file con durata zero (contenuto audio vuoto/corrotto);
    2) elimina i duplicati (stesso contenuto audio entro la tolleranza %).
    Le righe vengono rimosse dal database (annullabile con Undo) e i file
    spostati in .trash (recuperabili). Tolleranza: body {"tolerance": 5} (%).
    """
    data = request.json or {}
    try:
        tol = max(0.0, min(50.0, float(data.get("tolerance", 5))))
    except Exception:
        tol = 5.0
    tolerance = tol / 100.0
    job_id = "clean_" + uuid.uuid4().hex[:8]
    jobs[job_id] = {"status": "running", "log": [], "progress": {"percent": 0, "phase": "avvio"}}

    def run():
        try:
            result = run_cleanup(tolerance, progress=lambda p: jobs[job_id].__setitem__("progress", p))
            jobs[job_id].update(status="done", result=result)
        except Exception as e:
            import traceback; traceback.print_exc()
            jobs[job_id].update(status="error", error=str(e))

    threading.Thread(target=run, daemon=True).start()
    return jsonify({"job_id": job_id})

# ── PLAYBACK STATE (play/pausa persistito nel database) ─────────────────────
@app.route("/playback/state", methods=["GET"])
def playback_state_get():
    with get_db() as conn:
        row = row2dict(conn.execute("SELECT * FROM playback_state WHERE id=1").fetchone())
    return jsonify({"state": row})

@app.route("/playback/state", methods=["POST"])
def playback_state_set():
    """Salva lo stato di riproduzione corrente (brano, play/pausa, posizione).
    Usato dal player Onyx per far sopravvivere play/pausa tra le pagine."""
    data = request.json or {}
    with get_db() as conn:
        conn.execute(
            """UPDATE playback_state SET
                 title=?, artist=?, local_file=?, song_id=?,
                 is_playing=?, position=?, duration=?, volume=?,
                 updated_at=datetime('now')
               WHERE id=1""",
            (
                (data.get("title") or "").strip(),
                (data.get("artist") or "").strip(),
                (data.get("local_file") or "").strip(),
                data.get("song_id") or None,
                1 if data.get("is_playing") else 0,
                float(data.get("position") or 0),
                float(data.get("duration") or 0),
                float(data.get("volume") if data.get("volume") is not None else 0.7),
            ),
        )
        row = row2dict(conn.execute("SELECT * FROM playback_state WHERE id=1").fetchone())
    return jsonify({"state": row})

# ═══════════════════════════════════════════════════════════
# FORTISSIMO COMPARE — ponte JSON ⇄ modello (fortissimo_compare_v3.py)
# Il modello confronta due output AudioAnalysis (YAMNet + Demucs → MIDI +
# one-shot) e restituisce uno score [0,1]. Qui lo si rende pilotabile dal
# browser: le due analisi arrivano come JSON e i one-shot si generano da una
# piccola "spec" (non serve caricare waveform).
# ═══════════════════════════════════════════════════════════
FC_PATH = os.path.join(BASE_DIR, "fortissimo_compare_v3.py")
FC_LOCK = threading.Lock()
FC_MOD = None

def fc_module():
    """Importa una sola volta il modulo del modello Fortissimo."""
    global FC_MOD
    with FC_LOCK:
        if FC_MOD is None:
            import importlib.util
            spec = importlib.util.spec_from_file_location("fortissimo_compare_v3", FC_PATH)
            if spec is None or spec.loader is None:
                raise RuntimeError(f"Impossibile caricare {FC_PATH}")
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            FC_MOD = mod
    return FC_MOD

def fc_jsonable(obj):
    """Rende serializzabili in JSON i tipi numpy restituiti dal modello."""
    import numpy as np
    if isinstance(obj, dict):
        return {k: fc_jsonable(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [fc_jsonable(v) for v in obj]
    if isinstance(obj, np.ndarray):
        return obj.tolist()
    if isinstance(obj, np.bool_):
        return bool(obj)
    if isinstance(obj, np.floating):
        return float(obj)
    if isinstance(obj, np.integer):
        return int(obj)
    return obj

def fc_synth_audio(spec, sr=44100):
    """Genera la waveform di un one-shot dalla spec JSON.

    spec = {"type":"pluck"|"sine"|"noise"|"silence", "freq":440.0,
            "duration":0.1, "amp":0.6, "harmonics":[1.0,0.5], "seed":0}
    "pluck" riproduce esattamente il gen_pluck() dell'esempio del modello.
    """
    import numpy as np
    spec = spec or {}
    kind = str(spec.get("type") or "pluck").lower()
    sr = int(spec.get("sr", sr) or sr)
    dur = float(spec.get("duration", 0.1) or 0.1)
    amp = float(spec.get("amp", 0.5) if spec.get("amp") is not None else 0.5)
    n = max(0, int(sr * dur))
    if kind == "silence" or n == 0:
        return np.zeros(n, dtype=float)
    t = np.linspace(0, dur, n, endpoint=False)
    if kind == "noise":
        rng = np.random.default_rng(int(spec.get("seed", 0) or 0))
        w = rng.uniform(-1.0, 1.0, n)
    elif kind == "sine":
        w = np.sin(2 * np.pi * float(spec.get("freq", 440.0)) * t)
    else:
        f = float(spec.get("freq", 440.0))
        w = np.sin(2 * np.pi * f * t)
        for i, h in enumerate(spec.get("harmonics", [1.0, 0.5]) or [], start=2):
            w = w + float(h) * np.sin(2 * np.pi * f * i * t)
        w = w * np.exp(-t * 4)
    return w * amp

def fc_build_notes(track):
    """Costruisce le NoteEvent di una traccia dal JSON.

    Due formati, combinabili:
      "notes":   [{"pitch":64,"start":0.0,"end":0.4,"velocity":100,"channel":0}, ...]
      "pattern": {"base_pitch":64,"pattern":[0,2,4],"tempo":120,"velocity":100,
                  "length":0.8}   (come make_notes() nell'esempio del modello)
    """
    mod = fc_module()
    ch = int(track.get("channel", 0) or 0)
    notes = []
    for n in track.get("notes") or []:
        notes.append(mod.NoteEvent(
            pitch=int(n.get("pitch", 60)),
            start=float(n.get("start", 0.0) or 0.0),
            end=float(n.get("end", 0.0) or 0.0),
            velocity=int(n.get("velocity", 100)),
            channel=int(n.get("channel", ch)),
        ))
    pat = track.get("pattern")
    if isinstance(pat, dict):
        base = int(pat.get("base_pitch", 60))
        tempo = float(pat.get("tempo", 120.0) or 120.0)
        vel = int(pat.get("velocity", 100))
        ln = float(pat.get("length", 0.8))
        bd = (60.0 / tempo) if tempo > 0 else 0.5
        for k, step in enumerate(pat.get("pattern") or []):
            notes.append(mod.NoteEvent(base + int(step), k * bd,
                                       k * bd + bd * ln, vel, ch))
    return notes

def fc_build_output(payload):
    """Costruisce un AudioAnalysisOutput del modello da un payload JSON."""
    import numpy as np
    mod = fc_module()
    payload = payload or {}
    sr_default = int(payload.get("sr", 44100) or 44100)
    instruments = []
    for inst in payload.get("instruments") or []:
        tr = inst.get("track") or {}
        sk = inst.get("one_shot") or {}
        name = inst.get("instrument_name") or tr.get("name") or "unknown"
        track = mod.InstrumentTrack(
            name=tr.get("name") or name,
            program=int(tr.get("program", 0) or 0),
            channel=int(tr.get("channel", 0) or 0),
            notes=fc_build_notes(tr),
            is_drum=bool(tr.get("is_drum", False)),
            confidence=float(tr.get("confidence", 1.0) or 1.0),
        )
        sr = int(sk.get("sr", sr_default) or sr_default)
        spec = sk.get("audio")
        if isinstance(spec, dict):
            audio = fc_synth_audio(spec, sr=sr)
        elif isinstance(spec, list):
            audio = np.asarray(spec, dtype=float)
        else:
            audio = fc_synth_audio({"type": "silence"}, sr=sr)
        shot = mod.OneShotSample(
            instrument_name=sk.get("instrument_name") or track.name,
            program=int(sk.get("program", track.program) or 0),
            pitch=int(sk.get("pitch", 60) or 0),
            audio=audio,
            sr=sr,
            original_loudness=float(sk.get("original_loudness", 0.0) or 0.0),
            features=sk.get("features") or {},
        )
        instruments.append(mod.AnalyzedInstrument(
            instrument_name=name, track=track, one_shot=shot,
            separation_quality=float(inst.get("separation_quality", 1.0) or 0.0),
        ))
    return mod.AudioAnalysisOutput(
        instruments=instruments,
        source_filename=str(payload.get("source_filename") or ""),
        global_tempo=float(payload.get("global_tempo", 120.0) or 0.0),
        duration=float(payload.get("duration", 0.0) or 0.0),
    )

def fc_example_payload():
    """Riproduce l'esempio di test di fortissimo_compare_v3.py (canzoni A e B).

    B è identica ad A tranne il piano suonato più forte: serve a vedere sia il
    MIDI sia il one-shot lavorare (il volume pesa solo sul one-shot).
    """
    def song(fname, piano_amp):
        return {"source_filename": fname, "global_tempo": 120, "duration": 4.0,
                "instruments": [
                    {"instrument_name": "electric guitar", "separation_quality": 1.0,
                     "track": {"name": "electric guitar", "program": 27, "channel": 0,
                               "pattern": {"base_pitch": 64,
                                           "pattern": [0, 2, 4, 2, 0, -1, 0, 2],
                                           "tempo": 120, "velocity": 100}},
                     "one_shot": {"program": 27, "pitch": 72, "sr": 44100,
                                  "original_loudness": 0.6,
                                  "audio": {"type": "pluck", "freq": 440, "duration": 0.1,
                                            "amp": 0.6, "harmonics": [1.0, 0.5]}}},
                    {"instrument_name": "bass", "separation_quality": 1.0,
                     "track": {"name": "bass", "program": 32, "channel": 1,
                               "pattern": {"base_pitch": 36,
                                           "pattern": [0, 0, 7, 0, 5, 0, 7, 0],
                                           "tempo": 120, "velocity": 100}},
                     "one_shot": {"program": 32, "pitch": 36, "sr": 44100,
                                  "original_loudness": 0.7,
                                  "audio": {"type": "pluck", "freq": 110, "duration": 0.1,
                                            "amp": 0.7, "harmonics": [1.0, 0.5]}}},
                    {"instrument_name": "piano", "separation_quality": 1.0,
                     "track": {"name": "piano", "program": 0, "channel": 2,
                               "pattern": {"base_pitch": 60,
                                           "pattern": [0, 4, 7, 4, 0, -3, 0, 4],
                                           "tempo": 120, "velocity": 100}},
                     "one_shot": {"program": 0, "pitch": 72, "sr": 44100,
                                  "original_loudness": piano_amp,
                                  "audio": {"type": "pluck", "freq": 440, "duration": 0.1,
                                            "amp": piano_amp, "harmonics": [1.0, 0.5]}}},
                ]}
    return {"a": song("song_a.wav", 0.5), "b": song("song_b.wav", 0.9)}

# ── FORTISSIMO COMPARE: API (esempio, self-test, confronto) ───────────────────
@app.route("/fortissimo/example", methods=["GET"])
def fortissimo_example():
    """Le due analisi di esempio (canzoni A e B dell'esempio del modello)."""
    return jsonify(fc_example_payload())

@app.route("/fortissimo/selftest", methods=["GET"])
def fortissimo_selftest():
    """Verifica rapida del modello sui casi noti (senza input dell'utente)."""
    try:
        mod = fc_module()
        ex = fc_example_payload()
        a, b = fc_build_output(ex["a"]), fc_build_output(ex["b"])
        model = mod.AudioSimilarityModel()
        demo = model.compare(a, b)
        same = model.compare(a, a)
        quick = model.quick_score(a, b)
        checks = [
            {"name": "A vs A non peggiore di A vs B",
             "ok": same["overall_score"] >= demo["overall_score"],
             "detail": f"{same['overall_score']} >= {demo['overall_score']}"},
            {"name": "score di due brani identici = 0.925 (tetto MIDI 0.85)",
             "ok": abs(same["overall_score"] - 0.925) < 1e-6,
             "detail": f"{same['overall_score']}"},
            {"name": "A vs B → 0 < overall < 1",
             "ok": 0.0 < demo["overall_score"] < 1.0,
             "detail": f"{demo['overall_score']}"},
            {"name": "3/3 strumenti matchati",
             "ok": demo["n_match"] == demo["n_a"] == 3,
             "detail": f"{demo['n_match']}/{demo['n_a']}"},
            {"name": "quick_score == overall_score",
             "ok": abs(quick - demo["overall_score"]) < 1e-9,
             "detail": f"{quick} vs {demo['overall_score']}"},
            {"name": "tutti gli score in [0,1]",
             "ok": all(0.0 <= demo[k] <= 1.0 for k in
                       ("overall_score", "midi_score", "oneshot_score", "presence_score")),
             "detail": "ok"},
        ]
        return jsonify({"ok": bool(all(c["ok"] for c in checks)),
                        "checks": fc_jsonable(checks),
                        "quick_score": float(quick), "result": fc_jsonable(demo)})
    except Exception as e:
        import traceback; traceback.print_exc()
        return jsonify({"ok": False, "error": f"{type(e).__name__}: {e}"}), 500

@app.route("/fortissimo/compare", methods=["POST"])
def fortissimo_compare():
    """Confronta due analisi JSON. Body: {a:{...}, b:{...}, weights:{...}}."""
    data = request.json or {}
    a, b = data.get("a"), data.get("b")
    if not isinstance(a, dict) or not isinstance(b, dict):
        return jsonify({"error": "Servono due analisi JSON: i campi 'a' e 'b'"}), 400
    w = data.get("weights") or {}
    weights = {
        "midi": float(w.get("midi", 0.4)),
        "oneshot": float(w.get("oneshot", 0.4)),
        "presence": float(w.get("presence", 0.2)),
        "volume": float(w.get("volume", 0.3)),
    }
    try:
        mod = fc_module()
        model = mod.AudioSimilarityModel(
            midi_weight=weights["midi"], oneshot_weight=weights["oneshot"],
            presence_weight=weights["presence"], volume_weight=weights["volume"],
        )
        result = model.compare(fc_build_output(a), fc_build_output(b))
        return jsonify({"ok": True, "weights": weights, "result": fc_jsonable(result)})
    except AssertionError:
        return jsonify({"error": "I pesi midi + oneshot + presence devono sommare 1.0"}), 400
    except (ValueError, TypeError) as e:
        return jsonify({"error": f"Payload non valido: {e}"}), 400
    except Exception as e:
        import traceback; traceback.print_exc()
        return jsonify({"error": f"{type(e).__name__}: {e}"}), 500

if __name__ == "__main__":
    # Il log di avvio serve davvero: l'app può passare alla 5075 se la 5070 è
    # occupata, e con l'output rediretto su file (`nohup ... > /tmp/samplelab.log`)
    # Python tiene stdout in BUFFER: il banner e la porta scelta non si vedevano
    # fino al riempimento del buffer (18/09/2026). Così ogni riga è scritta subito.
    try:
        sys.stdout.reconfigure(line_buffering=True)
        sys.stderr.reconfigure(line_buffering=True)
    except Exception:
        pass
    init_db()
    port = 5070
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        s.bind(("0.0.0.0", port))
        s.close()
    except OSError:
        print("⚠️  Porta 5070 occupata. Uso 5075.")
        port = 5075
    print(f"\n╔════════════════════════════════╗\n║  🎵 SampleLab (2) — avviato!  ║\n║  http://localhost:{port}      ║\n╚════════════════════════════════╝\n")
    # Server WSGI di PRODUZIONE (waitress): il server di sviluppo di Flask
    # (werkzeug) con richieste lunghe (Verifica con Chrome/Tunebat/ffmpeg) può
    # congelare TUTTE le richieste dell'app; waitress gestisce la concorrenza
    # in modo robusto (thread pool). Se non è installato, ripiega su werkzeug.
    try:
        from waitress import serve
        print(f"* Server WSGI (waitress) su 0.0.0.0:{port} — thread pool 32")
        serve(app, host="0.0.0.0", port=port, threads=32, channel_timeout=600,
              max_request_body_size=2147483647)
    except ImportError:
        print("* waitress non installato: uso werkzeug (threaded=True)")
        app.run(debug=True, host="0.0.0.0", port=port, use_reloader=False, threaded=True)