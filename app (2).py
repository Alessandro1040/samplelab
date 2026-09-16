#!/usr/bin/env python3
"""
SampleLab — Backend unificato
Fonde: YT Downloader (index-5), WhoSampled Scraper (scraper_app), Mass Renamer, Database
"""

from flask import Flask, request, jsonify, send_file, Response
from flask_cors import CORS
import yt_dlp, os, threading, uuid, ssl, socket, json, time, re
import urllib.parse, subprocess, hashlib, sqlite3, struct, math
from datetime import datetime
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
DB_PATH    = os.path.join(BASE_DIR, "samplelab (2).db")
# Legacy dataset.json kept for compatibility
DATASET_PATH = os.path.join(BASE_DIR, "dataset.json")

jobs = {}
DB_LOCK = threading.Lock()
DATASET_LOCK = threading.Lock()

MIME_MAP = {"mp3":"audio/mpeg","wav":"audio/wav","webm":"audio/webm",
            "m4a":"audio/mp4","mp4":"audio/mp4","ogg":"audio/ogg",
            "opus":"audio/opus","flac":"audio/flac"}

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

def normalize_key(s): return re.sub(r"[^a-z0-9]","",s.lower())

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
def get_or_create_song_db(conn, title, artist, youtube_url="", local_file="", duration=None):
    def n(s): return re.sub(r"[^a-z0-9]","",s.lower())
    if youtube_url:
        r = conn.execute("SELECT id FROM songs WHERE youtube_url=?",(youtube_url,)).fetchone()
        if r: return r["id"]
    rows = conn.execute("SELECT id,title,artist FROM songs").fetchall()
    for row in rows:
        if n(row["title"])==n(title) and n(row["artist"])==n(artist):
            if youtube_url:
                conn.execute("UPDATE songs SET youtube_url=?,updated_at=datetime('now') WHERE id=? AND (youtube_url IS NULL OR youtube_url='')",(youtube_url,row["id"]))
            return row["id"]
    sid="song_"+hashlib.sha256(f"{title}|{artist}|{time.time()}".encode()).hexdigest()[:12]
    conn.execute("INSERT INTO songs(id,title,artist,youtube_url,local_file,duration) VALUES(?,?,?,?,?,?)",
                 (sid,title,artist,youtube_url,local_file,duration))
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
        q = urllib.parse.quote(f"{artist} {title}")
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
        for sec in hits:
            if sec.get("type") != "song":
                continue
            for h in sec.get("hits", []):
                res = h.get("result", {})
                if not res:
                    continue
                hit_artist = re.sub(r'[\u200e\u200f\u202a-\u202e\u2066-\u2069]', '', (res.get("primary_artist") or {}).get("name", "")).strip()
                hit_title = re.sub(r'[\u200e\u200f\u202a-\u202e\u2066-\u2069]', '', res.get("title", "")).strip()
                sc = match_score(artist or "", title or "", hit_artist, hit_title)
                if sc > best_score:
                    best_score = sc
                    best = (res, hit_artist, hit_title)
        if not best or best_score < 0.55:
            print(f"[genius] nessuna hit sopra soglia (best={best_score:.2f})")
            return None
        res, hit_artist, hit_title = best
        song = {
            "genius_url": res.get("url"),
            "title": hit_title,
            "artist": hit_artist,
            "score": round(best_score, 3),
            "featured_artists": [a.get("name", "") for a in res.get("featured_artists", [])],
            "producers": [p.get("name", "") for p in res.get("producer_artists", [])],
            "composers": [],
            "album_artist": "",
            "release_date": res.get("release_date_for_display", ""),
            "album": (res.get("album") or {}).get("name", ""),
            "cover_art": res.get("header_image_thumbnail_url", ""),
        }
        # API della singola canzone: compositori, produttori, album artist
        sid = res.get("id")
        if sid:
            try:
                time.sleep(0.3)
                req2 = urllib.request.Request(f"https://genius.com/api/songs/{sid}", headers=headers)
                with urllib.request.urlopen(req2, timeout=15) as r2:
                    sdata = json.loads(r2.read()).get("response", {}).get("song", {})
                if sdata:
                    song["composers"] = [a.get("name", "") for a in sdata.get("writer_artists", [])]
                    prods2 = [a.get("name", "") for a in sdata.get("producer_artists", [])]
                    if prods2:
                        song["producers"] = prods2
                    alb = sdata.get("album") or {}
                    if alb.get("name"):
                        song["album"] = alb["name"]
                    if (alb.get("artist") or {}).get("name"):
                        song["album_artist"] = alb["artist"]["name"]
                    if sdata.get("release_date_for_display"):
                        song["release_date"] = sdata["release_date_for_display"]
            except Exception as e:
                print(f"[genius song api] {e}")
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
            "score": round(score, 3),
            "explicit": explicit,
            "clean": clean,
            "duration": duration or 0,
        })
    # A parità di score si preferisce la versione più lunga (brano completo
    # invece di una clip di pochi secondi).
    ranked.sort(key=lambda r: (r["score"], r["duration"]), reverse=True)
    return ranked

def yt_search_first(query, expected_title="", expected_artist=""):
    entries = _yt_fetch_entries(query)
    if not entries:
        return None, None

    if not expected_title:
        e = entries[0]
        return e.get("webpage_url") or e.get("url"), e.get("title", "")

    et = normalize(expected_title)
    ranked = _rank_yt_entries(entries, expected_title, expected_artist)
    for r in ranked:
        tag = (" [ESPLICITA]" if r["explicit"] else "") + (" [CENSURATA]" if r["clean"] else "")
        print(f"[yt_search]  '{r['title']}' -> score={r['score']:.3f} ({r.get('duration')}s){tag}")

    # Un titolo identico vince sempre; fra più titoli identici si sceglie però il
    # migliore (score + durata), così una clip di 30 s non batte la versione
    # completa del brano (caso "Sam Is Dead", 16/09/2026).
    exact = [r for r in ranked if r["url"] and normalize(r["title"]) == et]
    if exact:
        best = max(exact, key=lambda r: (r["score"], r.get("duration") or 0))
        print(f"[yt_search]  MATCH ESATTO: {best['title']} "
              f"({best.get('duration')}s, score {best['score']:.3f})")
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

def _downloads_snapshot():
    """Nome file -> (mtime, size) della cartella download.

    Serve a capire quali file ha creato UN determinato job: senza questo
    confronto un download fallito poteva "adottare" il file scritto da un altro
    download in corso (bug del 16/09/2026: il sample "Sam Is Dead" riproduceva
    l'audio di "Mosh")."""
    snap = {}
    try:
        names = os.listdir(DL_DIR)
    except OSError:
        return snap
    for f in names:
        if f.startswith("."):
            continue
        try:
            st = os.stat(os.path.join(DL_DIR, f))
        except OSError:
            continue
        snap[f] = (st.st_mtime, st.st_size)
    return snap

def _pick_job_file(before, after, expected_title=""):
    """Sceglie il file audio creato DA QUESTO job: presente in `after` ma non in
    `before` (o modificato nel frattempo).

    Se `expected_title` è noto il file deve anche contenerlo (testo normalizzato):
    meglio nessun file — e quindi un errore visibile in pagina — che un audio
    appartenente a un altro brano. Ritorna il nome file oppure None."""
    candidates = []
    for name, state in after.items():
        if not name.lower().endswith(AUDIO_EXTS):
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

def do_download(job_id, query, fmt, quality="192", expected_title="", expected_artist=""):
    with DL_SEM:
        _do_download(job_id, query, fmt, quality, expected_title, expected_artist)

def _do_download(job_id, query, fmt, quality="192", expected_title="", expected_artist=""):
    # Foto della cartella download PRIMA di iniziare: alla fine si accettano solo
    # i file creati da questo job (vedi _pick_job_file), mai file di altri download.
    before = _downloads_snapshot()
    expected_title = (expected_title or "").strip()
    expected_artist = (expected_artist or "").strip()
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
            "format": "bestaudio[ext=m4a]/bestaudio[ext=webm]/bestaudio",
            "outtmpl": os.path.join(DL_DIR, "%(title)s.%(ext)s"),
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

        print(f"[download {job_id}] Avvio download formato nativo...")

        def _attempt_download(url):
            """Un giro di download (3 tentativi). Ritorna il nome del file creato
            da yt-dlp (percorso reale, non un file qualsiasi della cartella), o None."""
            for attempt in range(1, 4):
                try:
                    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                        info = ydl.extract_info(url, download=True)
                        prepared = ydl.prepare_filename(info) if info else None
                        requested = (info or {}).get("requested_downloads") or []
                        if requested and requested[0].get("filepath"):
                            prepared = requested[0]["filepath"]
                        name = os.path.basename(prepared) if prepared else None
                    if name and os.path.exists(os.path.join(DL_DIR, name)):
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
        # primo file trovato in cartella.
        if not filename and expected_title:
            alt_url, alt_title = yt_search_first(
                f"{expected_artist} {expected_title}".strip(),
                expected_title=expected_title, expected_artist=expected_artist)
            if alt_url and alt_url != yt_url:
                print(f"[download {job_id}] Video di partenza non scaricabile: provo {alt_url}")
                jobs[job_id]["status"] = "downloading"
                filename = _attempt_download(alt_url)
                if filename:
                    yt_title = alt_title or ""

        # RECUPERO 2: si accettano SOLO file creati da questo job (confronto con
        # la foto iniziale della cartella) e, quando il titolo è noto, che lo
        # contengono. Il vecchio fallback prendeva "l'ultimo file degli ultimi 60
        # secondi": nei download in parallelo dei sample succedeva che il sample
        # "Sam Is Dead" riproducesse l'audio di "Mosh" (file di un altro job).
        if not filename:
            filename = _pick_job_file(before, _downloads_snapshot(), expected_title or yt_title)

        if not filename:
            jobs[job_id]["status"] = "error"
            jobs[job_id]["error"] = (f"Download non riuscito: nessun file audio per "
                                     f"'{expected_title or query}' (audio NON sostituito)")
            print(f"[download {job_id}] ERRORE: questo job non ha prodotto file "
                  f"(nessun file di altri download riutilizzato)")
            return

        # Conversione esplicita con ffmpeg (se richiesto)
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
def register_local_file(filename):
    """Registra un file scaricato nella tabella songs (parsing artista - titolo)."""
    raw = clean_filename(filename)
    # Rimuove il suffisso ' [idYouTube]' aggiunto da yt-dlp nel template
    base = re.sub(r"\s*\[[^\]]{5,}\]\s*$", "", raw)
    parts = base.split(" - ", 1)
    artist = parts[0].strip() if len(parts) == 2 else ""
    title = parts[1].strip() if len(parts) == 2 else base.strip()
    with get_db() as conn:
        sid = get_or_create_song_db(conn, title, artist, local_file=filename)
    return sid

def do_download_playlist(job_id, url, fmt="mp3"):
    jobs[job_id]["status"] = "fetching"
    jobs[job_id]["progress"] = {"percent": 0, "speed": "", "eta": ""}
    valid_exts = (".mp3", ".wav", ".m4a", ".webm", ".mp4", ".ogg", ".opus", ".flac")

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
            "format": "bestaudio[ext=m4a]/bestaudio[ext=webm]/bestaudio",
            "outtmpl": os.path.join(DL_DIR, "%(title)s [%(id)s].%(ext)s"),
            "progress_hooks": [progress_hook],
            "ignoreerrors": True,
            "cookiefile": os.path.join(BASE_DIR, "cookies.txt"),
        }
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)

        after = snapshot()
        new_files = sorted(
            f for f, v in after.items()
            if f not in before or (before[f][0], before[f][1]) != v
        )
        new_files = [f for f in new_files if f.lower().endswith(valid_exts)]

        if not new_files:
            jobs[job_id]["status"] = "error"
            jobs[job_id]["error"] = "Nessun file scaricato dalla playlist (controlla l'URL)"
            return

        # Conversione esplicita in MP3 se richiesto
        if fmt == "mp3" and FFMPEG:
            converted = []
            for f in new_files:
                ext = f.rsplit(".", 1)[-1].lower()
                if ext == "mp3":
                    converted.append(f)
                    continue
                base = os.path.splitext(f)[0]
                out_name = f"{base}.mp3"
                out_path = os.path.join(DL_DIR, out_name)
                src_path = os.path.join(DL_DIR, f)
                try:
                    cmd = [FFMPEG, "-y", "-i", src_path, "-acodec", "libmp3lame", "-q:a", "2", out_path]
                    r = subprocess.run(cmd, capture_output=True, timeout=300)
                    if r.returncode == 0 and os.path.exists(out_path):
                        converted.append(out_name)
                    else:
                        converted.append(f)
                except Exception:
                    converted.append(f)
            new_files = converted

        # Registra ogni brano nel database
        registered = 0
        for f in new_files:
            if register_local_file(f):
                registered += 1

        jobs[job_id]["status"] = "done"
        jobs[job_id]["files"] = new_files
        jobs[job_id]["count"] = len(new_files)
        jobs[job_id]["registered"] = registered
        jobs[job_id]["playlist_title"] = info.get("title", "") if info else ""

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
    if not searched_artist:
        return candidates[0], candidates
    # Preferisce i candidati che NON sono varianti (remix/cover/live…) quando la
    # ricerca non chiede esplicitamente una variante. Es.: cercando "Hell on Earth"
    # deve vincere "Hell on Earth (Front Lines)" e non "Hell on Earth (Remix)".
    pool = candidates
    if not _has_variant_marker(searched_title):
        originals = [c for c in candidates if not _has_variant_marker(c["title"])]
        if originals:
            pool = originals
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

# ── STREAMING ────────────────────────────────────────────────────────────────
@app.route("/stream/<path:filename>")
def stream_file(filename):
    path = os.path.join(DL_DIR, filename)
    if not os.path.exists(path):
        return jsonify({"error": "File non trovato"}), 404
    ext = filename.rsplit(".", 1)[-1].lower()
    mime = MIME_MAP.get(ext, "audio/mpeg")
    rh = request.headers.get("Range")
    fs = os.path.getsize(path)
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

@app.route("/stream-stem/<folder>/<filename>")
def stream_stem(folder, filename):
    path = os.path.join(STEMS_DIR, "htdemucs", folder, filename)
    if not os.path.exists(path):
        return jsonify({"error": "File non trovato"}), 404
    ext = filename.rsplit(".", 1)[-1].lower()
    mime = MIME_MAP.get(ext, "audio/mpeg")
    return send_file(path, mimetype=mime)

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
    expected_title = (data.get("expected_title") or "").strip()
    expected_artist = (data.get("expected_artist") or "").strip()
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
                     args=(jid, query, fmt, quality, expected_title, expected_artist),
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
    threading.Thread(target=do_download_playlist, args=(jid, url, fmt), daemon=True).start()
    return jsonify({"job_id": jid})

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
@app.route("/save_pair", methods=["POST"])
def save_pair():
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
    if is_duplicate(dataset, new_pair):
        return jsonify({"duplicate": True, "total": dataset["meta"]["count"]})
    dataset["pairs"].append(new_pair)
    save_dataset(dataset)
    # Also save in SQLite
    try:
        with get_db() as conn:
            did = get_or_create_song_db(conn, song_x["title"], song_x["artist"], song_x.get("youtube_url", ""))
            sid2 = get_or_create_song_db(conn, song_yi["title"], song_yi["artist"], song_yi.get("youtube_url", ""))
            rid = "rel_" + uuid.uuid4().hex[:12]
            conn.execute(
                """INSERT OR IGNORE INTO sample_relations(
                    id, derivative_song_id, source_song_id,
                    category, transformation, yt_url_derivative, yt_url_source,
                    timestamp_derivative_start, timestamp_derivative_end,
                    timestamp_source_start, timestamp_source_end, notes, verified_by_user
                ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,1)""",
                (
                    rid, did, sid2,
                    category, transformation,
                    song_x.get("youtube_url"), song_yi.get("youtube_url"),
                    trim_x.get("start"), trim_x.get("end"),
                    trim_yi.get("start"), trim_yi.get("end"),
                    notes,
                )
            )
    except:
        pass
    return jsonify({"saved": True, "total": dataset["meta"]["count"]})

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
    allowed = [
        "title", "artist", "album", "album_artist", "composer", "producers", "genre", "year", "release_date",
        "track_number", "disc_number", "compilation", "rating", "bpm", "musical_key", "play_count",
        "comment", "lyrics", "analyzed_status", "genius_url", "whosampled_url", "youtube_url",
        "tunebat_url", "cover_art_path", "local_file", "title_verified", "artist_verified",
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

def _set_verify_status(song_id, step, total, status):
    verify_progress[song_id] = {"step": step, "total": total, "status": status, "ts": time.time()}

@app.route("/db/songs/<song_id>/verify_status", methods=["GET"])
def verify_status_endpoint(song_id):
    st = verify_progress.get(song_id)
    if not st:
        return jsonify({"active": False, "song_id": song_id})
    return jsonify({"active": True, "song_id": song_id, "step": st["step"],
                    "total": st["total"], "status": st["status"]})

@app.route("/db/songs/<song_id>/verify", methods=["POST"])
def verify_song(song_id):
    """Look up Genius + Tunebat and fill unverified fields"""
    with get_db() as conn:
        s = row2dict(conn.execute("SELECT * FROM songs WHERE id=?", (song_id,)).fetchone())
    if not s:
        return jsonify({"error": "Non trovata"}), 404

    _set_verify_status(song_id, 1, 6, "Ricerca canzone su Genius…")
    updates = {}
    messages = []

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
        for ca, ct in uniq:
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
        if not genius:
            _set_verify_status(song_id, 1, 6, "Genius non ha trovato: cerco titolo corretto su YouTube…")
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
            if not s.get("artist_verified") and genius.get("artist"):
                updates["artist"] = genius["artist"]
                updates["artist_verified"] = 1
                messages.append("Artista trovato su Genius")
            # Il testo viene cercato se manca o se è "sporco" (es. vecchi fetch del
            # player con '8 Contributors', 'Read More', descrizioni di Genius...).
            existing_lyrics = (s.get("lyrics") or "")
            lyrics_dirty = (not existing_lyrics.strip()) or bool(re.search(
                r'\d+\s*[Cc]ontributors?|Read\s+More\.?$|You\s+might\s+also\s+like|^\s*.{1,80}\s+Lyrics\s*$|'
                r'^\s*\[(?:' + _TRANS_KEYS + r')[^\]\n]{0,90}\]',
                existing_lyrics, re.IGNORECASE | re.MULTILINE))
            if lyrics_dirty and genius.get("genius_url"):
                _set_verify_status(song_id, 2, 6, "Recupero testo da Genius…")
                lyrics = fetch_genius_lyrics_text(genius["genius_url"])
                if lyrics:
                    updates["lyrics"] = lyrics
                    updates["lyrics_verified"] = 1
                    messages.append("Testo trovato su Genius")
            if genius.get("producers"):
                updates["producers"] = json.dumps(genius["producers"])
                messages.append(f"Produttori trovati: {len(genius['producers'])}")
            if genius.get("release_date") and not s.get("release_date"):
                updates["release_date"] = genius["release_date"]
                messages.append("Data rilascio trovata su Genius")
            if genius.get("album") and not s.get("album"):
                updates["album"] = genius["album"]
                messages.append("Album trovato su Genius")
            if genius.get("composers") and not s.get("composer"):
                updates["composer"] = ", ".join(genius["composers"])
                messages.append(f"Compositore trovato su Genius: {updates['composer']}")
            if genius.get("album_artist") and not s.get("album_artist"):
                updates["album_artist"] = genius["album_artist"]
                messages.append(f"Artista album trovato su Genius: {genius['album_artist']}")
            if genius.get("genius_url") and not s.get("genius_url"):
                updates["genius_url"] = genius["genius_url"]
                messages.append("URL Genius trovato")
        else:
            messages.append("⚠️ Genius: nessun risultato trovato")
    except Exception as e:
        messages.append(f"⚠️ Genius: errore ({str(e)[:50]})")

    # Titolo/artista "effettivi" da usare nelle ricerche successive (YouTube,
    # WhoSampled, Tunebat): se titolo/artista sono stati corretti (da Genius o
    # da YouTube) si usano i nuovi; altrimenti la versione "pulita" (senza
    # numeretto iniziale di traccia/trattini) che ha più probabilità di match.
    search_artist = updates.get("artist") or base_artist
    search_title = updates.get("title") or base_title

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
        _set_verify_status(song_id, 3, 6, "Ricerca URL YouTube…")
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

        # 2) Browser SOLO se serve davvero (WhoSampled senza URL, o BPM/Key non già verificati)
        need_browser = (not s.get("whosampled_url")) or (not bpmkey_done)
        if need_browser:
            try:
                ws_driver = _make_driver_safe(60)
            except Exception as e:
                messages.append(f"⚠️ Browser non avviato: {str(e)[:60]}")
        else:
            messages.append("ℹ️ URL WhoSampled e BPM/Key già presenti: browser non avviato")

        # 3) URL WhoSampled → stessa ricerca dello scraper (artista + titolo)
        if ws_driver and not s.get("whosampled_url"):
            _set_verify_status(song_id, 4, 6, "Ricerca WhoSampled…")
            try:
                track, _ = search_whosampled(
                    ws_driver,
                    f"{search_artist} {search_title}",
                    searched_artist=search_artist,
                    searched_title=search_title)
                if track and track.get("url"):
                    ws_score = match_score(search_artist, search_title,
                                           track.get("artist", ""), track.get("title", ""))
                    if ws_score >= 0.55:
                        updates["whosampled_url"] = track["url"]
                        messages.append(f"🔗 URL WhoSampled: {track['artist']} — {track['title']}")
                    else:
                        messages.append(f"⚠️ WhoSampled: punteggio basso ({ws_score:.2f}), URL non salvato")
                else:
                    messages.append("⚠️ WhoSampled: nessun risultato trovato")
            except Exception as e:
                messages.append(f"⚠️ WhoSampled: errore ({str(e)[:50]})")

        # 4) TUNEBAT PRIMA → BPM/Key (fonte principale) e link — solo se non già verificati
        if not bpmkey_done and ws_driver:
            _set_verify_status(song_id, 5, 6, "Verifica BPM/Key su Tunebat…")
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
            _set_verify_status(song_id, 6, 6, "Analisi audio (BPM/Key)…")
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

# ── DB: MASS RENAME ───────────────────────────────────────────────────────────
@app.route("/db/mass_rename", methods=["POST"])
def mass_rename():
    """Apply find/replace on a specific field across all songs"""
    data = request.json or {}
    field = data.get("field", "title")
    find = data.get("find", "")
    replace = data.get("replace", "")
    if field not in ["title", "artist", "album", "genre", "comment", "producers"]:
        return jsonify({"error": "Campo non consentito"}), 400
    if not find:
        return jsonify({"error": "find richiesto"}), 400
    with get_db() as conn:
        rows = conn.execute(f"SELECT id, {field} FROM songs WHERE {field} LIKE ?", (f"%{find}%",)).fetchall()
        updated = []
        for r in rows:
            old = r[field] or ""
            new = old.replace(find, replace)
            if new != old:
                conn.execute(f"UPDATE songs SET {field}=?, updated_at=datetime('now') WHERE id=?", (new, r["id"]))
                updated.append({"id": r["id"], "old": old, "new": new})
    return jsonify({"updated": updated, "count": len(updated)})

# ── DB: ADD FROM FILE (upload) ────────────────────────────────────────────────
@app.route("/db/add_local", methods=["POST"])
def add_local_file():
    """Register a local file in the DB (after user uploads/selects it)"""
    data = request.json or {}
    filename = data.get("filename", "").strip()
    if not filename:
        return jsonify({"error": "filename richiesto"}), 400
    raw = clean_filename(filename)
    parts = raw.split(" - ", 1)
    artist = parts[0].strip() if len(parts) == 2 else ""
    title = parts[1].strip() if len(parts) == 2 else raw
    with get_db() as conn:
        sid = get_or_create_song_db(conn, title, artist, local_file=filename)
        s = row2dict(conn.execute("SELECT * FROM songs WHERE id=?", (sid,)).fetchone())
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
    return jsonify(s)

# ── DB: QUERY / SCRIPT PERSONALIZZATI (con UNDO/REDO) ────────────────────────
# ATTENZIONE: funzionalità per uso locale/sviluppo. L'esecuzione di script
# Python arbitrari è potenzialmente pericolosa: NON esporre queste rotte
# pubblicamente senza autenticazione e limitazioni severe.
# Prima di ogni operazione che modifica il database (UPDATE o script) viene
# salvato uno snapshot completo del DB: con /db/undo e /db/redo puoi
# annullare/ripetere le ultime operazioni.
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
        sql_upper = sql.upper().strip()
        if not (sql_upper.startswith("SELECT") or sql_upper.startswith("UPDATE")):
            return jsonify({"error": "Sono consentite solo SELECT e UPDATE"}), 400
        forbidden = ["DROP", "ALTER", "CREATE", "DELETE", "INSERT", "TRUNCATE", "REPLACE"]
        if any(re.search(rf"\b{w}\b", sql_upper) for w in forbidden):
            return jsonify({"error": "Operazione non consentita"}), 400
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
    t.join(timeout=30)
    _sys.stdout = old_stdout

    if t.is_alive():
        _drop_snapshot(before)
        return jsonify({"error": "Script timeout (30s)"}), 500

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