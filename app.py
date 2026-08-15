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

BASE_DIR   = os.path.dirname(os.path.abspath(__file__))
DL_DIR     = os.path.join(BASE_DIR, "downloads");  os.makedirs(DL_DIR, exist_ok=True)
STEMS_DIR  = os.path.join(BASE_DIR, "stems");      os.makedirs(STEMS_DIR, exist_ok=True)
DB_PATH    = os.path.join(BASE_DIR, "samplelab.db")
# Legacy dataset.json kept for compatibility
DATASET_PATH = os.path.join(BASE_DIR, "dataset.json")

jobs = {}
DB_LOCK = threading.Lock()
DATASET_LOCK = threading.Lock()

MIME_MAP = {"mp3":"audio/mpeg","wav":"audio/wav","webm":"audio/webm",
            "m4a":"audio/mp4","mp4":"audio/mp4","ogg":"audio/ogg",
            "opus":"audio/opus","flac":"audio/flac"}

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
    cover_art_path  TEXT,
    local_file      TEXT,
    -- verification flags: 0=unverified(red), 1=verified(green)
    title_verified      INTEGER DEFAULT 0,
    artist_verified     INTEGER DEFAULT 0,
    bpm_verified        INTEGER DEFAULT 0,
    key_verified        INTEGER DEFAULT 0,
    lyrics_verified     INTEGER DEFAULT 0,
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

CREATE INDEX IF NOT EXISTS idx_songs_artist ON songs(artist);
CREATE INDEX IF NOT EXISTS idx_songs_title  ON songs(title);
CREATE INDEX IF NOT EXISTS idx_sr_deriv     ON sample_relations(derivative_song_id);
CREATE INDEX IF NOT EXISTS idx_sr_source    ON sample_relations(source_song_id);
        """)

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
        return {"bpm":round(bpm,1),"key":f"{bk} {bm}","confidence":round(bc,3),"source":"librosa"}
    except Exception as e:
        print(f"[librosa] {e}"); return None

def analyze_audio_ffmpeg(filepath):
    if not FFMPEG: return None
    try:
        cmd=[FFMPEG,"-y","-i",filepath,"-t","90","-ac","1","-ar","22050","-f","f32le","-"]
        res=subprocess.run(cmd,capture_output=True,timeout=60)
        if res.returncode!=0 or len(res.stdout)<1000: return None
        raw=res.stdout; n=len(raw)//4
        samples=struct.unpack(f"{n}f",raw); sr=22050; hop=512; window=2048
        energies=[sum(x*x for x in samples[i:i+window])/window for i in range(0,n-window,hop)]
        onset=[max(0.0,energies[i]-energies[i-1]) for i in range(1,len(energies))]
        min_lag=int(sr*60/(200*hop)); max_lag=min(int(sr*60/(50*hop)),len(onset)//2)
        bl=min_lag; bc=-1.0
        for lag in range(min_lag,max_lag):
            c=sum(onset[i]*onset[i+lag] for i in range(len(onset)-lag))
            if c>bc: bc=c; bl=lag
        bpm=round(sr*60/(bl*hop),1)
        while bpm<60: bpm=round(bpm*2,1)
        while bpm>180: bpm=round(bpm/2,1)
        keys=['C','C#','D','D#','E','F','F#','G','G#','A','A#','B']
        chroma=[0.0]*12
        for i in range(0,min(n,sr*60),4096):
            chunk=samples[i:i+4096]
            if len(chunk)<4096: break
            for k in range(12):
                freq=261.63*(2**(k/12.0)); cs=ss=0.0
                for j,x in enumerate(chunk):
                    a=2*math.pi*freq*j/sr; cs+=x*math.cos(a); ss+=x*math.sin(a)
                chroma[k]+=math.sqrt(cs**2+ss**2)
        tot=sum(chroma) or 1.0; chroma=[c/tot for c in chroma]
        mps=[6.35,2.23,3.48,2.33,4.38,4.09,2.52,5.19,2.39,3.66,2.29,2.88]
        mips=[6.33,2.68,3.52,5.38,2.60,3.53,2.54,4.75,3.98,2.69,3.34,3.17]
        def nv(v): s=math.sqrt(sum(x*x for x in v)) or 1.0; return [x/s for x in v]
        cn,mn,min2=nv(chroma),nv(mps),nv(mips)
        def dr(a,b,r): return sum(a[i]*b[(i-r)%12] for i in range(12))
        bk=0; bmo="Major"; bsc=-1.0
        for r in range(12):
            sm=dr(cn,mn,r); smi=dr(cn,min2,r)
            if sm>bsc: bsc=sm; bk=r; bmo="Major"
            if smi>bsc: bsc=smi; bk=r; bmo="Minor"
        return {"bpm":bpm,"key":f"{keys[bk]} {bmo}","source":"ffmpeg","confidence":round(bsc,3)}
    except Exception as e:
        print(f"[ffmpeg_analysis] {e}"); return None

# ── TUNEBAT SCRAPING ─────────────────────────────────────────────────────────
def scrape_tunebat(artist, title):
    """Scrape BPM+Key from Tunebat using headless Chrome"""
    try:
        driver = make_driver()
        query = urllib.parse.quote(f"{artist} {title}")
        search_url = f"https://tunebat.com/Search?q={query}"
        html = fetch_page(driver, search_url)
        if not html:
            driver.quit(); return None
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(html, "html.parser")
        track_links = soup.find_all("a", href=re.compile(r"^/track/"))
        if not track_links:
            driver.quit(); return None
        detail_url = "https://tunebat.com" + track_links[0]["href"]
        html = fetch_page(driver, detail_url)
        driver.quit()
        if not html: return None
        bpm_m = re.search(r'(\d+(?:\.\d+)?)\s*BPM', html, re.IGNORECASE)
        key_m = re.search(r'([A-G][#b]?)\s*(Major|Minor)', html, re.IGNORECASE)
        bpm = float(bpm_m.group(1)) if bpm_m else None
        key = None
        if key_m:
            key = f"{key_m.group(1).upper()} {key_m.group(2).capitalize()}"
        if bpm or key:
            return {"bpm": bpm, "key": key, "source": "tunebat"}
        return None
    except Exception as e:
        print(f"[tunebat] {e}"); return None

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
            conn.execute("UPDATE songs SET bpm=?,musical_key=?,updated_at=datetime('now') WHERE id=?",
                         (result.get("bpm"),result.get("key"),sid))
    return result

# ── GENIUS ────────────────────────────────────────────────────────────────────
def fetch_genius(artist, title):
    """Fetch lyrics URL, title, artist, date, producers from Genius"""
    try:
        import urllib.request
        import time
        q = urllib.parse.quote(f"{artist} {title}")
        url = f"https://genius.com/api/search/multi?q={q}"
        req = urllib.request.Request(
            url,
            headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                "Accept": "application/json",
                "Accept-Language": "en-US,en;q=0.9",
                "Origin": "https://genius.com",
                "Referer": "https://genius.com/"
            }
        )
        time.sleep(0.5)  # Evita rate limit
        with urllib.request.urlopen(req, timeout=15) as r:
            data = json.loads(r.read())
        hits = data.get("response", {}).get("sections", [])
        for sec in hits:
            if sec.get("type") == "song":
                for h in sec.get("hits", []):
                    res = h.get("result", {})
                    if res:
                        primary = res.get("primary_artist", {})
                        featured = [a.get("name", "") for a in res.get("featured_artists", [])]
                        producers = [p.get("name", "") for p in res.get("producer_artists", [])]
                        release_date = res.get("release_date_for_display", "")
                        return {
                            "genius_url": res.get("url"),
                            "title": res.get("title", ""),
                            "artist": primary.get("name", ""),
                            "featured_artists": featured,
                            "producers": producers,
                            "release_date": release_date,
                            "album": (res.get("album") or {}).get("name", ""),
                            "cover_art": res.get("header_image_thumbnail_url", ""),
                        }
    except Exception as e:
        print(f"[genius] Error: {e}")
    return None
def fetch_genius_lyrics_text(genius_url):
    """Fetch actual lyrics text from a Genius page"""
    try:
        import urllib.request
        req = urllib.request.Request(genius_url, headers={"User-Agent":"Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=15) as r:
            html = r.read().decode("utf-8", errors="ignore")
        # Extract lyrics from data-lyrics-container
        import re
        parts = re.findall(r'data-lyrics-container="true"[^>]*>(.*?)</div>', html, re.DOTALL)
        if not parts:
            # Fallback: look for lyrics in JSON
            m = re.search(r'"lyrics":\{"plain":"(.*?)"', html)
            if m:
                return m.group(1).replace("\\n","\n").replace("\\u0027","'")
        text = "\n".join(re.sub(r'<[^>]+>',' ', p) for p in parts)
        text = re.sub(r' +',' ', text).strip()
        return text if text else None
    except Exception as e:
        print(f"[genius_lyrics] {e}"); return None

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

def yt_search_first(query, expected_title="", expected_artist=""):
    from difflib import SequenceMatcher
    import re

    ydl_opts = {"quiet": True, "extract_flat": True, "noplaylist": True}
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(f"ytsearch20:{query}", download=False)
    entries = info.get("entries", [])
    if not entries:
        return None, None

    if not expected_title:
        e = entries[0]
        return e.get("webpage_url") or e.get("url"), e.get("title", "")

    et = normalize(expected_title)
    ea = normalize(expected_artist) if expected_artist else ""

    # Match esatto
    for e in entries:
        vt = normalize(e.get("title", ""))
        if vt == et:
            print(f"[yt_search]  MATCH ESATTO: {e.get('title')}")
            return e.get("webpage_url") or e.get("url"), e.get("title", "")

    best = None
    best_score = -1.0

    for e in entries:
        raw_title = e.get("title", "")
        vt = normalize(raw_title)
        duration = e.get("duration", 0)

        if duration and (duration < 20 or duration > 1200):
            print(f"[yt_search]  '{raw_title}' -> durata {duration}s, scartato")
            continue

        score = SequenceMatcher(None, et, vt).ratio()

        if ea and ea in vt:
            score += 0.15

        lower = raw_title.lower()
        if "feat" in lower or "featuring" in lower or "with" in lower:
            score += 0.10

        channel = e.get("channel", "").lower()
        if ea and (ea in normalize(channel) or "official" in channel):
            score += 0.20
            print(f"[yt_search]  canale ufficiale: +0.20")

        bad_words = ["cover", "remix", "live", "acoustic", "instrumental", "karaoke",
                     "8-bit", "8bit", "reaction", "review", "slowed", "reverb", "nightcore"]
        for w in bad_words:
            if w in lower:
                score -= 0.25
                break

        if re.search(r'\bpart\s*2\b|\bpt\.?\s*2\b|\bii\b|\b2\.0\b', lower) and not re.search(r'\b2\b', et):
            score -= 0.30

        print(f"[yt_search]  '{raw_title}' -> score={score:.3f}")
        if score > best_score:
            best_score = score
            best = e

    SOGLIA = 0.55
    if best and best_score >= SOGLIA:
        print(f"[yt_search]  => SCELTO: {best.get('title', '')} (score {best_score:.3f})")
        return best.get("webpage_url") or best.get("url"), best.get("title", "")

    print(f"[yt_search]  => NESSUN MATCH sopra soglia {SOGLIA}")
    return None, None

# ── DOWNLOAD ──────────────────────────────────────────────────────────────────
def do_download(job_id, query, fmt, quality="192"):
    jobs[job_id]["status"] = "searching"
    jobs[job_id]["progress"] = {"percent": 0, "speed": "", "eta": ""}
    try:
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
        }

        print(f"[download {job_id}] Avvio download formato nativo...")
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(yt_url, download=True)
            prepared = ydl.prepare_filename(info) if info else None
            filename = os.path.basename(prepared) if prepared else None

        # Fallback: cerca il file più recente nella cartella
        if not filename or not os.path.exists(os.path.join(DL_DIR, filename)):
            files_with_time = []
            valid_exts = (".mp3", ".wav", ".m4a", ".webm", ".mp4", ".ogg", ".opus", ".flac")
            for f in os.listdir(DL_DIR):
                if f.startswith(".") or not f.lower().endswith(valid_exts):
                    continue
                fp = os.path.join(DL_DIR, f)
                files_with_time.append((os.path.getmtime(fp), f))
            if files_with_time:
                files_with_time.sort(reverse=True)
                filename = files_with_time[0][1]
                print(f"[download {job_id}] File trovato via fallback: {filename}")

        if not filename:
            jobs[job_id]["status"] = "error"
            jobs[job_id]["error"] = "Download completato ma nessun file trovato"
            return

        # Conversione esplicita con ffmpeg (se richiesto)
        ext = filename.rsplit(".", 1)[-1].lower()
        target_ext = "mp3" if fmt == "mp3" else "wav"
        if ext != target_ext and fmt in ("mp3", "wav") and FFMPEG:
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
                    filename = out_name
                    print(f"[download {job_id}] Conversione OK: {filename}")
                else:
                    err = result.stderr.decode(errors="ignore")[-200:]
                    print(f"[download {job_id}] Conversione fallita, uso formato nativo: {err}")
            except Exception as conv_err:
                print(f"[download {job_id}] Errore conversione, uso formato nativo: {conv_err}")

        print(f"[download {job_id}] Successo: {filename}")
        jobs[job_id]["status"] = "done"
        jobs[job_id]["filename"] = filename

    except Exception as e:
        print(f"[download {job_id}] Errore: {e}")
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
        res=subprocess.run(cmd,capture_output=True)
        if res.returncode!=0:
            jobs[job_id]["status"]="error"
            jobs[job_id]["error"]="Errore ffmpeg: "+res.stderr.decode(errors="ignore")[-200:]
            return
        jobs[job_id]["status"]="done"; jobs[job_id]["filename"]=out_name
    except Exception as e:
        jobs[job_id]["status"]="error"; jobs[job_id]["error"]=str(e)

# ── WHOSAMPLED SCRAPER ────────────────────────────────────────────────────────
def match_score(sa, st, fa, ft):
    from difflib import SequenceMatcher
    sa, st, fa, ft = normalize(sa), normalize(st), normalize(fa), normalize(ft)
    if sa == fa and st == ft:
        return 1.0
    ts = 0.85 + (min(len(st), len(ft)) / max(len(st), len(ft), 1)) * 0.15 if (st in ft or ft in st) else SequenceMatcher(None, st, ft).ratio()
    ars = 1.0 if (sa == fa or sa in fa or fa in sa) else SequenceMatcher(None, sa, fa).ratio()
    return ts * 0.80 + ars * 0.20

def make_driver():
    import undetected_chromedriver as uc
    opts = uc.ChromeOptions()
    for a in ["--headless=new","--no-sandbox","--disable-dev-shm-usage",
              "--disable-blink-features=AutomationControlled","--disable-gpu",
              "--window-size=1920,1080","--remote-debugging-port=0"]:
        opts.add_argument(a)
    opts.add_argument("--user-agent=Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/131.0.0.0 Safari/537.36")
    return uc.Chrome(options=opts, use_subprocess=True)

def fetch_page(driver, url):
    try:
        driver.get(url)
        for _ in range(20):
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
        time.sleep(2)
        return driver.page_source
    except:
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
    best = max(candidates, key=lambda c: match_score(searched_artist, searched_title, c["artist"], c["title"]), default=None)
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

def clean_yt_title(title):
    title = re.sub(r'\s*\(.*?\)', '', title)
    title = re.sub(r'\s*\[.*?\]', '', title)
    title = re.sub(r'^\s*\d+[\.\s\-:]+', '', title)
    return re.sub(r'\s+', ' ', title).strip()

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
            yt_url, yt_title = yt_search_first(f"{artist} {title}")
            if yt_title:
                yt_title_clean = clean_yt_title(yt_title)
                log(f"[DEBUG] YouTube ha trovato: {yt_title_clean}")

                # Tentativo 1: con artista + titolo pulito
                log(f"Tentativo 1 su WhoSampled: {artist} - {yt_title_clean}")
                if use_scoring:
                    track, candidates = search_whosampled(driver, f"{artist} {yt_title_clean}",
                                                          searched_artist=artist,
                                                          searched_title=yt_title_clean)
                else:
                    track, candidates = search_whosampled(driver, f"{artist} {yt_title_clean}",
                                                          searched_artist="",
                                                          searched_title="")

                # Tentativo 2: solo titolo (senza artista)
                if not track:
                    log(f"Tentativo 2 su WhoSampled (solo titolo): {yt_title_clean}")
                    if use_scoring:
                        track, candidates = search_whosampled(driver, yt_title_clean,
                                                              searched_artist="",
                                                              searched_title=yt_title_clean)
                    else:
                        track, candidates = search_whosampled(driver, yt_title_clean,
                                                              searched_artist="",
                                                              searched_title="")

                if track:
                    track['title'] = yt_title_clean
                    log(f"✅ Trovato su WhoSampled: {track['artist']} - {track['title']}")
                else:
                    # Se anche dopo due tentativi fallisce, usiamo i dati di YouTube (senza sample)
                    log("[DEBUG] WhoSampled non trova la canzone nemmeno con titolo pulito, uso i dati di YouTube")
                    track = {
                        "title": yt_title_clean,
                        "artist": artist,
                        "url": None
                    }
                    jobs[job_id]["status"] = "done"
                    jobs[job_id]["result"] = {
                        "title": yt_title_clean,
                        "artist": artist,
                        "ws_url": None,
                        "main_yt_url": yt_url,
                        "main_yt_title": yt_title_clean,
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
        main_yt_url, main_yt_title = yt_search_first(
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
    return send_file(os.path.join(BASE_DIR, "index.html"))

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
    }
    threading.Thread(target=do_download, args=(jid, query, fmt, quality), daemon=True).start()
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
    with get_db() as conn:
        songs = rows2list(conn.execute("SELECT * FROM songs ORDER BY artist, title").fetchall())
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
        allowed = [
            "album", "album_artist", "composer", "producers", "genre", "year", "release_date",
            "track_number", "disc_number", "compilation", "rating", "bpm", "musical_key",
            "play_count", "comment", "lyrics", "analyzed_status", "genius_url",
            "whosampled_url", "cover_art_path", "title_verified", "artist_verified",
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
        "cover_art_path", "local_file", "title_verified", "artist_verified",
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

# ── DB: VERIFY (auto-fill from Genius + Tunebat) ─────────────────────────────
@app.route("/db/songs/<song_id>/verify", methods=["POST"])
def verify_song(song_id):
    """Look up Genius + Tunebat and fill unverified fields"""
    with get_db() as conn:
        s = row2dict(conn.execute("SELECT * FROM songs WHERE id=?", (song_id,)).fetchone())
    if not s:
        return jsonify({"error": "Non trovata"}), 404

    updates = {}
    messages = []

    # ─── GENIUS ──────────────────────────────────────────────
    try:
        genius = fetch_genius(s.get("artist", ""), s.get("title", ""))
        if genius:
            if not s.get("title_verified") and genius.get("title"):
                updates["title"] = genius["title"]
                updates["title_verified"] = 1
                messages.append("Titolo trovato su Genius")
            if not s.get("artist_verified") and genius.get("artist"):
                updates["artist"] = genius["artist"]
                updates["artist_verified"] = 1
                messages.append("Artista trovato su Genius")
            if not s.get("lyrics_verified") and genius.get("genius_url"):
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
            if genius.get("genius_url") and not s.get("genius_url"):
                updates["genius_url"] = genius["genius_url"]
                messages.append("URL Genius trovato")
        else:
            messages.append("⚠️ Genius: nessun risultato trovato")
    except Exception as e:
        messages.append(f"⚠️ Genius: errore ({str(e)[:50]})")

    # ─── BPM & KEY (Tunebat + audio) ────────────────────────
    if not s.get("bpm_verified") or not s.get("key_verified"):
        try:
            # Prima prova con l'analisi audio (se il file esiste)
            meta = None
            local_file = s.get("local_file")
            if local_file:
                fp = os.path.join(DL_DIR, local_file)
                if os.path.exists(fp):
                    if HAS_LIBROSA:
                        meta = analyze_audio_librosa(fp)
                    if not meta:
                        meta = analyze_audio_ffmpeg(fp)
                    if meta:
                        messages.append(f"BPM/Key dall'analisi audio ({meta.get('source')})")

            # Se l'audio non ha dato risultati, prova Tunebat
            if not meta:
                meta = scrape_tunebat(s.get("artist", ""), s.get("title", ""))
                if meta:
                    messages.append("BPM/Key da Tunebat")

            if meta:
                if meta.get("bpm") and not s.get("bpm_verified"):
                    updates["bpm"] = meta["bpm"]
                    updates["bpm_verified"] = 1
                if meta.get("key") and not s.get("key_verified"):
                    updates["musical_key"] = meta["key"]
                    updates["key_verified"] = 1
            else:
                messages.append("⚠️ BPM/Key: nessuna fonte disponibile")
        except Exception as e:
            messages.append(f"⚠️ BPM/Key: errore ({str(e)[:50]})")

    # ─── SALVA NEL DATABASE ─────────────────────────────────
    if updates:
        with get_db() as conn:
            for f, v in updates.items():
                conn.execute(f"UPDATE songs SET {f}=?, updated_at=datetime('now') WHERE id=?", (v, song_id))
        s.update(updates)
        messages.append("✅ Dati salvati nel database")
    else:
        messages.append("ℹ️ Nessun dato da aggiornare (i campi sono già verificati o non disponibili)")

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

if __name__ == "__main__":
    init_db()
    port = 5000
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        s.bind(("0.0.0.0", port))
        s.close()
    except OSError:
        print("⚠️  Porta 5000 occupata. Uso 5050.")
        port = 5050
    print(f"\n╔════════════════════════════════╗\n║  🎵 SampleLab  —  avviato!    ║\n║  http://localhost:{port}        ║\n╚════════════════════════════════╝\n")
    app.run(debug=True, host="127.0.0.1", port=port, use_reloader=False)