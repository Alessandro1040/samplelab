"""Test della CONFERMA AUDIO della Verifica (il passo 🔊) — 18/09/2026.

Domanda di Alessandro: «c'è un modo per avere la certezza che la canzone x è stata
veramente trovata su Genius e non è un falso positivo? ad esempio scaricando la
canzone trovata su genius e confrontando l'audio con quello del computer presunto».

Genius **non ospita audio** (è un database di testi/metadati): l'unico audio
"ufficiale" raggiungibile è l'**anteprima di 30 s di iTunes** (API pubblica
`itunes.apple.com/search`, nessuna chiave). Il passo 🔊 (qui `conferma_audio`):
1. cerca l'anteprima del brano (titolo + artista principale, soglia 0,55 di
   `match_score` come tutte le altre ricerche dell'app);
2. la scarica in `anteprime/` (cartella NON versionata, come `covers/`);
3. calcola l'**impronta acustica** di entrambi gli audio (spettrogramma → picchi
   → hash di coppie di picchi) e ne confronta gli **scarti temporali**: se è lo
   stesso brano, centinaia di hash cadono sullo STESSO offset;
4. scrive l'esito in `songs.audio_match_*`
   ('confermato' / 'non confermato' / 'ambiguo' / 'non verificabile').

Misurato il 18/09/2026 con le funzioni dell'app su *21 Questions* (50 Cent / Nate
Dogg, file locale da 258,6 s, anteprima ufficiale 30,0 s): **2.525 hash allineati
a 76,0 s** contro **5-9 hash** di 8 brani presi a caso dalla libreria (806 contro
16 sul caso sintetico qui sotto). La durata da sola non basta: il file locale è
34 s più lungo del disco ufficiale e l'anteprima sta *dentro* il file, quindi la
durata direbbe "diverso" mentre l'audio dice "uguale".
⚠️ Questi test hanno trovato un difetto vero: con i picchi "più forti del frame"
(la banda dei bassi è la più forte in ogni istante) gli hash si ripetevano e un
brano SBAGLIATO arrivava a **1.415 voti**; ora i picchi sono massimi LOCALI in
frequenza × tempo (test di regressione in TestPicchiSpettrali). Il passo è nella
Verifica (`/db/songs/<id>/verify`: si attiva da sé quando il match testuale è
debole, score < 0,95, o quando si chiede `{"audio": true}`) e ha un endpoint
dedicato `/db/songs/<id>/audio_check`, usato dal pulsante "🔊 Audio" della
tabella del database.

Esecuzione (dalla cartella di SampleLab):
    python3 -m unittest -v test_audio_match

I test di rete (iTunes), quelli HTTP (app viva) e quelli in JavaScriptCore si
saltano da soli se manca il pezzo; `SAMPLELAB_URL` sovrascrive l'indirizzo.
"""
import importlib.util
import json
import os
import re
import shutil
import subprocess
import tempfile
import time
import unittest
import urllib.error
import urllib.request
import wave

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
APP_PATH = os.path.join(BASE_DIR, "app (2).py")
INDEX_PATH = os.path.join(BASE_DIR, "index (2).html")
ONYX_PATH = os.path.join(BASE_DIR, "onyx_whosampled.html")
VERIFICA_PATH = os.path.join(BASE_DIR, "verifica.html")
GITIGNORE_PATH = os.path.join(BASE_DIR, ".gitignore")
FFMPEG = shutil.which("ffmpeg")
HA_OSASCRIPT = shutil.which("osascript") is not None
SAMPLELAB_URL = os.environ.get("SAMPLELAB_URL", "http://localhost:5070")
# La canzone usata come caso vero (ha l'anteprima ufficiale su iTunes): è la
# stessa delle misurazioni del 18/09/2026.
ID_21_QUESTIONS = "song_abf47df2aae9"


def load_app():
    """Carica il modulo dell'app dal file (il nome con spazio non conta).
    L'import NON avvia il server e non tocca il database."""
    spec = importlib.util.spec_from_file_location("samplelab_app2_audio", APP_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


APP = load_app()
HA_NUMPY = APP.np is not None
HA_AUDIO = bool(HA_NUMPY and APP.HAS_LIBROSA)


def leggi(path):
    with open(path, encoding="utf-8") as fh:
        return fh.read()


def app_is_up(url):
    try:
        urllib.request.urlopen(url + "/db/stats", timeout=3)
        return True
    except Exception:
        return False


def _blocco(src, inizio, apri, chiudi, cosa):
    i = src.index(apri, inizio)
    liv, j = 0, i
    while j < len(src):
        if src[j] == apri:
            liv += 1
        elif src[j] == chiudi:
            liv -= 1
            if liv == 0:
                return src[i:j + 1]
        j += 1
    raise AssertionError("parentesi non bilanciate in %s" % cosa)


def estrai_funzione(src, nome):
    """Il testo della funzione `nome` preso dal file vero (pagina o app)."""
    m = re.search(r"(?:async\s+)?function\s+" + re.escape(nome) + r"\s*\(", src)
    if not m:
        raise AssertionError("funzione %s assente" % nome)
    inizio_corpo = src.index("{", m.end() - 1)
    corpo = _blocco(src, m.end() - 1, "{", "}", nome)
    return src[m.start(): inizio_corpo + len(corpo)]


def esegui_js(codice, nome_file="/tmp/test_audio_match.js"):
    """Esegue un frammento di JavaScript con JavaScriptCore e torna il JSON
    dell'ULTIMA espressione (che deve essere una JSON.stringify(...))."""
    with open(nome_file, "w", encoding="utf-8") as out:
        out.write(codice + "\n")
    r = subprocess.run(["osascript", "-l", "JavaScript", nome_file],
                       capture_output=True, text=True)
    righe = ((r.stdout or "") + (r.stderr or "")).strip().splitlines()
    if not righe:
        raise AssertionError("nessun output da JavaScriptCore: %s" % (r.stderr or "")[:200])
    return json.loads(righe[-1])


def spettro_finto(valori, gruppi=None):
    """Spettrogramma finto: `valori` è {frame: {gruppo: dB}} e ogni gruppo occupa
    AUDIO_BIN_HASH frequenze (le altre restano a -100 dB, sotto soglia)."""
    np = APP.np
    larghezza = APP.AUDIO_BIN_HASH
    n_gruppi = gruppi or (max(max(v) for v in valori.values()) + 2 if valori else 4)
    frames = (max(valori) + 1) if valori else 0
    S = np.full((n_gruppi * larghezza, frames), -100.0)
    for t, colonna in valori.items():
        for g, db in colonna.items():
            S[g * larghezza:(g + 1) * larghezza, t] = db
    return S


def scrivi_wav(percorso, campioni_int16, sr):
    """WAV mono 16 bit (stdlib): serve per fabbricare audio vero senza scaricare."""
    with wave.open(percorso, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes(campioni_int16.tobytes())


@unittest.skipUnless(HA_NUMPY, "numpy non installato")
class TestPicchiSpettrali(unittest.TestCase):
    """I picchi sono UNO per gruppo di frequenze (stessa risoluzione degli hash):
    così due massimi vicini non diventano due eventi diversi."""

    def test_un_picco_per_gruppo(self):
        S = spettro_finto({0: {3: -10.0}})          # 8 frequenze dello stesso gruppo
        picchi = APP.picchi_spettrali(S)
        self.assertEqual(len(picchi), 1)
        self.assertEqual(picchi[0][0], 0)           # frame
        self.assertEqual(picchi[0][1], 3)           # gruppo
        self.assertAlmostEqual(picchi[0][2], -10.0)

    def test_vince_il_piu_forte_e_rispetta_il_limite(self):
        # due eventi lontani in frequenza (oltre il raggio) e un limite di picchi:
        # il gruppo 7 è dentro la finestra del 6, quindi non è un picco
        S = spettro_finto({0: {1: -20.0, 6: -5.0, 7: -30.0}}, gruppi=10)
        self.assertEqual([p[1] for p in APP.picchi_spettrali(S, n_picchi=1)], [6])
        picchi = APP.picchi_spettrali(S, n_picchi=2)
        self.assertEqual([p[1] for p in picchi], [6, 1])       # i due più forti, in ordine
        self.assertEqual([p[2] for p in picchi], [-5.0, -20.0])

    def test_sotto_soglia_non_ce_ne_sono(self):
        self.assertEqual(APP.picchi_spettrali(spettro_finto({0: {1: -70.0}})), [])

    def test_eventi_lontani_nel_tempo_sono_due_picchi(self):
        # a 20 frame di distanza (≈0,93 s) i due eventi non si danno fastidio
        S = spettro_finto({0: {1: -10.0}, 20: {1: -8.0}})
        self.assertEqual(sorted(p[0] for p in APP.picchi_spettrali(S)), [0, 20])

    def test_eventi_vicini_nel_tempo_vince_il_piu_forte(self):
        # a 2 frame (≈0,09 s) il più debole è dentro la finestra del più forte
        S = spettro_finto({0: {1: -10.0}, 2: {1: -8.0}})
        self.assertEqual([(p[0], p[1]) for p in APP.picchi_spettrali(S)], [(2, 1)])

    def test_input_vuoto(self):
        self.assertEqual(APP.picchi_spettrali(None), [])
        self.assertEqual(APP.picchi_spettrali(APP.np.zeros((0, 0))), [])

    def test_regressione_la_banda_sempre_forte_non_e_un_picco(self):
        """Regressione del difetto trovato da questi test: la banda dei bassi è la
        più forte in OGNI istante, quindi "i più forti del frame" la sceglieva
        sempre e gli hash si ripetevano (un brano sbagliato arrivava a 1.415 voti).
        Col massimo locale quella banda è un picco solo dove spicca davvero."""
        rng = APP.np.random.RandomState(3)
        valori = {t: {0: -5.0 - 4.0 * float(rng.rand())} for t in range(40)}
        valori[20][6] = -3.0                     # evento vero: spicca in frequenza e nel tempo
        picchi = APP.picchi_spettrali(spettro_finto(valori, gruppi=8))
        forti_del_frame = [p for p in picchi if p[1] == 0]
        self.assertLess(len(forti_del_frame), 8)          # prima erano 40, uno per ogni frame
        self.assertIn((20, 6), [(p[0], p[1]) for p in picchi])

    def test_il_picco_deve_spiccare_nel_tempo(self):
        # un evento isolato è un picco, uno continuo (che copre tutta la finestra)
        valori = {t: {4: -10.0} for t in range(40)}
        valori[20][4] = -2.0
        picchi = APP.picchi_spettrali(spettro_finto(valori, gruppi=6))
        self.assertEqual([(p[0], p[1]) for p in picchi], [(20, 4)])


@unittest.skipUnless(HA_NUMPY, "numpy non installato")
class TestHashDaPicchi(unittest.TestCase):
    """Gli hash sono coppie (gruppo_f1, gruppo_f2, Δt) con àncora sul primo picco:
    è il Δt che rende l'impronta indipendente dal taglio e dal master."""

    def test_coppie_entro_il_delta(self):
        picchi = [(0, 5, -1.0), (10, 7, -2.0), (100, 9, -3.0)]
        hashes = APP.hash_da_picchi(picchi, dt_max=64, coppie=4)
        self.assertEqual(hashes, [((5, 7, 10), 0)])            # il picco a 100 è troppo lontano

    def test_limite_di_coppie_per_picco(self):
        picchi = [(0, 1, -1.0), (2, 2, -1.0), (4, 3, -1.0), (6, 4, -1.0), (8, 5, -1.0)]
        hashes = APP.hash_da_picchi(picchi, dt_max=64, coppie=2)
        self.assertEqual(len([h for h in hashes if h[1] == 0]), 2)
        self.assertEqual(len(hashes), 2 + 2 + 2 + 1)           # l'ultimo picco non ha nessuno dopo

    def test_ordine_sparso_e_stesso_istante(self):
        # picchi in ordine sparso e due sullo stesso frame: il Δt non è mai 0
        picchi = [(5, 9, -1.0), (0, 3, -1.0), (0, 4, -1.0)]
        hashes = APP.hash_da_picchi(picchi, dt_max=64, coppie=4)
        self.assertEqual(len(hashes), 2)                        # solo le coppie col frame 5
        self.assertTrue(all(h[0][2] == 5 and h[1] == 0 for h in hashes))

    def test_vuoto(self):
        self.assertEqual(APP.hash_da_picchi([]), [])


class TestIstogrammaOffset(unittest.TestCase):
    """Il cuore del confronto: gli hash in comune CONTANO solo se cadono tutti
    sullo stesso scarto temporale (altrimenti sono coincidenze)."""

    def test_impronte_identiche_offset_zero(self):
        h = [((1, 2, 3), 10), ((4, 5, 6), 40), ((7, 8, 9), 90)]
        voti, offset, comuni = APP.istogramma_offset(h, h)
        self.assertEqual(voti, 3)
        self.assertEqual(offset, 0.0)
        self.assertEqual(comuni, 3)

    def test_anteprima_dentro_il_brano(self):
        # stessa impronta spostata di 50 frame (≈2,32 s a 11025 Hz / hop 512)
        locale = [((1, 2, 3), 60), ((4, 5, 6), 90), ((7, 8, 9), 140)]
        anteprima = [((1, 2, 3), 10), ((4, 5, 6), 40), ((7, 8, 9), 90)]
        voti, offset, comuni = APP.istogramma_offset(locale, anteprima)
        self.assertEqual(voti, 3)
        self.assertAlmostEqual(offset, 50 * APP.AUDIO_HOP / APP.AUDIO_SR, places=3)
        self.assertEqual(comuni, 3)

    def test_coincidenze_sparse_non_fanno_un_picco(self):
        # lo stesso hash in punti diversi: comuni alti, voti minuscoli
        locale = [((1, 1, 1), t) for t in (5, 20, 35, 50, 65, 80)]
        anteprima = [((1, 1, 1), t) for t in (0, 17, 31, 44, 59, 77)]
        voti, offset, comuni = APP.istogramma_offset(locale, anteprima)
        self.assertEqual(comuni, 36)
        self.assertLessEqual(voti, 2)
        self.assertLess(voti, APP.AUDIO_VOTI_CONFERMA)

    def test_brani_diversi(self):
        locale = [((1, 2, 3), 10), ((9, 9, 9), 40)]
        anteprima = [((5, 6, 7), 10), ((8, 8, 8), 40)]
        self.assertEqual(APP.istogramma_offset(locale, anteprima), (0, None, 0))

    def test_elenchi_vuoti(self):
        self.assertEqual(APP.istogramma_offset([], []), (0, None, 0))
        self.assertEqual(APP.istogramma_offset([((1, 2, 3), 5)], []), (0, None, 0))


class TestEsito(unittest.TestCase):
    """Il verdetto in parole: soglie esplicite, così un "non lo so" non viene mai
    spacciato per un sì."""

    def test_soglie(self):
        self.assertEqual(APP.esito_confronto_audio(2525), "confermato")
        self.assertEqual(APP.esito_confronto_audio(806), "confermato")
        self.assertEqual(APP.esito_confronto_audio(APP.AUDIO_VOTI_CONFERMA), "confermato")
        self.assertEqual(APP.esito_confronto_audio(APP.AUDIO_VOTI_CONFERMA - 1), "ambiguo")
        self.assertEqual(APP.esito_confronto_audio(APP.AUDIO_VOTI_RIFIUTO + 1), "ambiguo")
        self.assertEqual(APP.esito_confronto_audio(APP.AUDIO_VOTI_RIFIUTO), "non confermato")
        self.assertEqual(APP.esito_confronto_audio(16), "non confermato")   # massimo su un brano sbagliato
        self.assertEqual(APP.esito_confronto_audio(9), "non confermato")    # massimo sui brani reali
        self.assertEqual(APP.esito_confronto_audio(0), "non confermato")

    def test_valori_del_contratto(self):
        # sono i numeri scritti nel README: se cambiano, va aggiornato anche quello
        self.assertEqual(APP.AUDIO_VOTI_CONFERMA, 50)
        self.assertEqual(APP.AUDIO_VOTI_RIFIUTO, 20)
        self.assertAlmostEqual(APP.AUDIO_SCORE_SOSPETTO, 0.95)
        self.assertEqual(APP.AUDIO_BIN_HASH, 8)
        self.assertEqual(APP.AUDIO_RAGGIO_FREQ, 3)
        self.assertEqual(APP.AUDIO_RAGGIO_TEMPO, 7)
        self.assertEqual(APP.AUDIO_DT_MAX, 64)
        self.assertEqual(APP.AUDIO_COPPIE, 4)
        self.assertEqual(APP.AUDIO_SR, 11025)

    def test_bande_di_verdetto(self):
        soglie = {"confermato": 50, "ambiguo": 21, "non confermato": 20}
        for atteso, voti in soglie.items():
            self.assertEqual(APP.esito_confronto_audio(voti), atteso)

    def test_non_verificabile_non_esce_dai_numeri(self):
        # "non verificabile" lo decide conferma_audio (dato mancante), non questa funzione
        verdi = [APP.esito_confronto_audio(v) for v in (0, 20, 21, 50, 2525)]
        self.assertNotIn("non verificabile", verdi)
        self.assertEqual(set(verdi), {"confermato", "ambiguo", "non confermato"})


@unittest.skipUnless(HA_AUDIO and FFMPEG, "ffmpeg/librosa/numpy non disponibili")
class TestConfrontoAudioFileEndToEnd(unittest.TestCase):
    """L'algoritmo su audio VERO fabbricato in casa (nessuna rete): il file locale
    contiene l'anteprima a 20 s dall'inizio, ricodificata in MP3 per simulare un
    master/encoding diverso. Il caso negativo è un altro brano."""

    @classmethod
    def setUpClass(cls):
        np = APP.np
        sr = APP.AUDIO_SR
        cls.dir = tempfile.mkdtemp(prefix="samplelab_audio_")
        cls.locale = os.path.join(cls.dir, "locale.wav")
        cls.corretta_mp3 = os.path.join(cls.dir, "corretta.mp3")
        cls.sbagliata_mp3 = os.path.join(cls.dir, "sbagliata.mp3")

        def brano(seme, secondi=60):
            """Rumore con inviluppo e due componenti forti: picchi spettrali che
            cambiano nel tempo (come una canzone) e riproducibili identici."""
            rng = np.random.RandomState(seme)
            n = sr * secondi
            t = np.arange(n) / float(sr)
            inviluppo = 0.35 + 0.65 * np.abs(np.sin(2 * np.pi * 0.7 * t + seme))
            return np.clip(inviluppo * (0.25 * np.sin(2 * np.pi * 110 * t)
                                        + 0.2 * np.sin(2 * np.pi * 660 * t)
                                        + 0.15 * rng.randn(n)), -1, 1)

        def int16(x):
            return (x * 30000).astype(np.int16)

        # 1) il "disco ufficiale" (60 s) e la sua anteprima (15 s a partire da 20 s)
        cls.brano = brano(7)
        scrivi_wav(cls.locale, int16(cls.brano), sr)
        cls.anteprima_wav = os.path.join(cls.dir, "anteprima.wav")
        scrivi_wav(cls.anteprima_wav, int16(cls.brano[20 * sr:35 * sr]), sr)
        # 2) l'anteprima di un ALTRO brano (controllo negativo)
        cls.altro = brano(99)
        altro_wav = os.path.join(cls.dir, "altro.wav")
        scrivi_wav(altro_wav, int16(cls.altro[20 * sr:35 * sr]), sr)

        # ricodifica in MP3: l'impronta deve reggere il cambio di encoding
        for src, dst in ((cls.anteprima_wav, cls.corretta_mp3), (altro_wav, cls.sbagliata_mp3)):
            r = subprocess.run([FFMPEG, "-y", "-v", "error", "-i", src,
                                "-codec:a", "libmp3lame", "-b:a", "192k", dst],
                               capture_output=True, text=True)
            if r.returncode != 0 or not os.path.exists(dst):
                raise unittest.SkipTest("ffmpeg non ha ricodificato in MP3: %s" % r.stderr[:120])

    def test_il_file_locale_contiene_lanteprima(self):
        esito = APP.confronto_audio_file(self.locale, self.corretta_mp3)
        self.assertIsNotNone(esito)
        self.assertGreater(esito["hash"], 0)
        # l'anteprima sta a 20 s: l'offset trovato deve essere quello
        self.assertLess(abs(esito["offset"] - 20.0), 0.5, "offset trovato: %s" % esito["offset"])
        self.assertEqual(APP.esito_confronto_audio(esito["voti"]), "confermato")
        self.assertGreaterEqual(esito["voti"], APP.AUDIO_VOTI_CONFERMA)

    def test_un_altro_brano_non_conferma(self):
        esito = APP.confronto_audio_file(self.locale, self.sbagliata_mp3)
        self.assertIsNotNone(esito)
        self.assertEqual(APP.esito_confronto_audio(esito["voti"]), "non confermato")

    def test_il_brano_giusto_vince_di_molto(self):
        giusto = APP.confronto_audio_file(self.locale, self.corretta_mp3)
        sbagliato = APP.confronto_audio_file(self.locale, self.sbagliata_mp3)
        self.assertGreater(giusto["voti"], 10 * max(sbagliato["voti"], 1),
                           "giusto %s vs sbagliato %s" % (giusto["voti"], sbagliato["voti"]))

    def test_file_illeggibili(self):
        self.assertIsNone(APP.confronto_audio_file(os.path.join(self.dir, "non-esiste.wav"),
                                                   self.corretta_mp3))
        rotto = os.path.join(self.dir, "rotto.wav")
        with open(rotto, "wb") as fh:
            fh.write(b"non e' un wav")
        self.assertIsNone(APP.confronto_audio_file(rotto, self.corretta_mp3))

    def test_impronta_dipende_solo_dall_audio(self):
        # stesso audio in due formati diversi → impronte quasi identiche a offset 0
        wav = APP.impronta_audio(APP._audio_mono(self.anteprima_wav))
        mp3 = APP.impronta_audio(APP._audio_mono(self.corretta_mp3))
        self.assertTrue(wav and mp3)
        voti, offset, comuni = APP.istogramma_offset(wav, mp3)
        self.assertAlmostEqual(offset, 0.0, places=3)
        self.assertGreater(voti, 100)
        self.assertGreaterEqual(voti, comuni * 0.5)   # la maggior parte degli hash si allinea


@unittest.skipUnless(HA_OSASCRIPT, "JavaScriptCore (osascript) non disponibile")
class TestChipNellaPagina(unittest.TestCase):
    """La pastiglia 🔊 della riga: la funzione della pagina eseguita davvero in
    JavaScriptCore (non una copia nel test)."""

    def _chip(self, casi):
        src = leggi(INDEX_PATH)
        m = re.search(r"const AUDIO_CHIP = \{.*?\n\};", src, re.S)
        if not m:
            raise AssertionError("AUDIO_CHIP assente in index (2).html")
        codice = ("function esc(s){return String(s==null?'':s)"
                  ".replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;')}\n"
                  + m.group(0) + "\n" + estrai_funzione(src, "motivoBreve") + "\n"
                  + estrai_funzione(src, "chipAudio") + "\n"
                  + "const out = %s;\nJSON.stringify(out);\n" % casi)
        return esegui_js(codice)

    def test_confermato(self):
        html = self._chip("[chipAudio({audio_match_esito:'confermato',audio_match_voti:2583,"
                          "audio_match_offset:76.0,audio_match_fonte:'iTunes 1 · 50 Cent — 21 Questions',"
                          "audio_match_at:'2026-09-18 13:20:00'})]")[0]
        self.assertIn("🔊 ✓ confermato", html)
        self.assertIn("#4ade80", html)
        self.assertIn("2583 hash", html)
        self.assertIn("offset 76.0 s", html)
        self.assertIn("iTunes 1 · 50 Cent — 21 Questions", html)
        self.assertIn("2026-09-18 13:20:00", html)

    def test_non_confermato_e_ambiguo(self):
        html = self._chip("[chipAudio({audio_match_esito:'non confermato',audio_match_voti:8}),"
                          "chipAudio({audio_match_esito:'ambiguo',audio_match_voti:20})]")
        self.assertIn("🔊 ✗ non confermato", html[0])
        self.assertIn("#ff4545", html[0])
        self.assertEqual(html[0].count("offset"), 0)      # niente offset quando è null
        self.assertIn("🔊 ? ambiguo", html[1])
        self.assertIn("#fbbf24", html[1])

    def test_non_verificabile_e_esito_ignoto(self):
        html = self._chip("[chipAudio({audio_match_esito:'non verificabile'}),"
                          "chipAudio({audio_match_esito:'strano'})]")
        self.assertIn("🔊 – non verificabile", html[0])
        self.assertIn("var(--muted)", html[0])
        self.assertIn("strano", html[1])                  # esito sconosciuto: si mostra com'è

    def test_senza_esito_nessuna_pastiglia(self):
        html = self._chip("[chipAudio({title:'x'}),chipAudio(null),chipAudio(undefined)]")
        self.assertEqual(html, ["", "", ""])

    def test_la_scansione_html_e_innocua(self):
        # il titolo/fonte finiscono nell'HTML: le parentesi angolari si neutralizzano
        html = self._chip("[chipAudio({audio_match_esito:'confermato',"
                          "audio_match_fonte:'<b>x</b>'})]")[0]
        self.assertNotIn("<b>", html)
        self.assertIn("&lt;b&gt;", html)

    def test_pastiglia_del_link_whosampled(self):
        html = self._chip("[chipAudio({ws_audio_esito:'non confermato',ws_audio_voti:8,"
                          "ws_audio_offset:40.8,"
                          "ws_audio_fonte:'iTunes 2 · Skeeter Davis — The End of the World'},"
                          "'whosampled')]")[0]
        self.assertIn("🔊 ✗ non confermato", html)
        self.assertIn("#ff4545", html)
        self.assertIn("8 hash", html)
        self.assertIn("offset 40.8 s", html)
        self.assertIn("il link WhoSampled", html)          # l'anteprima dice di cosa parla
        self.assertIn("Skeeter Davis", html)
        self.assertNotIn("audio_match_", html)             # niente campi dell'altro verdetto

    def test_le_due_pastiglie_non_si_confondono(self):
        riga = ("{audio_match_esito:'confermato',audio_match_voti:1230,audio_match_offset:76.0,"
                "ws_audio_esito:'non confermato',ws_audio_voti:8,ws_audio_offset:40.8}")
        html = self._chip("[chipAudio(%s),chipAudio(%s,'whosampled')]" % (riga, riga))
        self.assertIn("✓ confermato", html[0])
        self.assertIn("1230 hash", html[0])
        self.assertIn("76.0 s", html[0])
        self.assertNotIn("non confermato", html[0])
        self.assertIn("✗ non confermato", html[1])
        self.assertIn("8 hash", html[1])
        self.assertIn("40.8 s", html[1])
        self.assertIn("il link WhoSampled", html[1])
        self.assertIn("la canzone trovata su Genius", html[0])

    def test_motivo_breve(self):
        html = self._chip(
            "[motivoBreve('nessuna anteprima ufficiale: iTunes 0 risultati per «50 Cent 1998 Freestyle»'),"
            "motivoBreve(''),motivoBreve(null),"
            "motivoBreve('audio non verificabile: manca il file locale in downloads/'),"
            "motivoBreve('una frase senza separatori che e davvero molto molto lunga')]")
        self.assertEqual(html[0], "nessuna anteprima ufficiale")     # si taglia ai due punti
        self.assertEqual(html[1], "")
        self.assertEqual(html[2], "")
        self.assertEqual(html[3], "audio non verificabile")
        self.assertTrue(html[4].endswith("…"))
        self.assertLessEqual(len(html[4]), 34)

    def test_pastiglia_con_il_motivo(self):
        html = self._chip("[chipAudio({audio_match_esito:'non verificabile',"
                          "audio_match_motivo:'nessuna anteprima ufficiale: iTunes 0 risultati "
                          "per «50 Cent 1998 Freestyle»',audio_match_at:'2026-09-18 16:10:00'})]")[0]
        self.assertIn("🔊 – non verificabile", html)
        self.assertIn("nessuna anteprima ufficiale", html)                  # si vede in riga
        self.assertIn("iTunes 0 risultati per «50 Cent 1998 Freestyle»", html)  # frase intera nel title
        self.assertNotIn("nessuna anteprima ufficiale · nessuna", html)

    def test_pastiglia_del_candidato_scartato(self):
        html = self._chip(
            "[chipAudio({ws_audio_esito:'scartato',"
            "ws_audio_fonte:'iTunes 258619200 · Skeeter Davis — The End of the World (157.6 s)',"
            "ws_audio_motivo:\"l'audio del candidato NON è dentro il file locale: probabile "
            "falso positivo (9 hash allineati)\"},'whosampled')]")[0]
        self.assertIn("🔊 ✗ candidato scartato", html)
        self.assertIn("#ff4545", html)
        self.assertIn("il link WhoSampled", html)
        self.assertIn("Skeeter Davis", html)                # la fonte nel title
        self.assertIn("falso positivo", html)               # il motivo, intero, nel title

    def test_pastiglia_del_link_anche_col_motivo(self):
        html = self._chip("[chipAudio({ws_audio_esito:'non verificabile',"
                          "ws_audio_motivo:'nessuna anteprima ufficiale: i 3 risultati con anteprima "
                          "per «End of the World» sono di altri artisti'},'whosampled')]")[0]
        self.assertIn("🔊 – non verificabile", html)
        self.assertIn("il link WhoSampled", html)
        self.assertIn("i 3 risultati con anteprima", html)                  # frase intera nel title


class TestEsitoWhosampled(unittest.TestCase):
    """La decisione sul link WhoSampled: il punteggio testuale da solo NON basta
    (con l'artista vuoto `match_score` dà 1.0 all'artista) — decide l'audio."""

    def test_punteggio_basso(self):
        d = APP.esito_whosampled(0.40, "confermato")
        self.assertEqual((d["azione"], d["rimuovi_url"]), ("scarta", False))
        self.assertIn("0.40", d["motivo"])

    def test_audio_confermato_salva(self):
        d = APP.esito_whosampled(0.976, "confermato")
        self.assertEqual((d["azione"], d["rimuovi_url"]), ("salva", False))

    def test_audio_non_confermato_scarta_e_rimuove_il_link(self):
        # il caso vero: *End of the World* → pagina di Skeeter Davis
        # (8 hash allineati contro 2.525 del brano giusto)
        d = APP.esito_whosampled(0.976, "non confermato")
        self.assertEqual((d["azione"], d["rimuovi_url"]), ("scarta", True))
        self.assertIn("falso positivo", d["motivo"])

    def test_audio_ambiguo_scarta_e_rimuove(self):
        self.assertEqual(APP.esito_whosampled(0.976, "ambiguo")["rimuovi_url"], True)

    def test_senza_anteprima_e_artista_mancante_scarta_senza_rimuovere(self):
        d = APP.esito_whosampled(0.976, "non verificabile", artista_mancante=True)
        self.assertEqual((d["azione"], d["rimuovi_url"]), ("scarta", False))
        # manca la prova, quindi non si rimuove nulla: si rimuove solo con una prova contraria

    def test_senza_anteprima_ma_candidato_identificabile(self):
        for extra in ({"titolo_univoco": True}, {"artista_identificabile": True}):
            d = APP.esito_whosampled(0.976, "non verificabile", artista_mancante=True, **extra)
            self.assertEqual(d["azione"], "salva")

    def test_senza_anteprima_con_artista_confrontabile(self):
        self.assertEqual(APP.esito_whosampled(0.976, "non verificabile",
                                              artista_mancante=False)["azione"], "salva")

    def test_soglia_personalizzabile(self):
        self.assertEqual(APP.esito_whosampled(0.70, "non verificabile")["azione"], "salva")
        self.assertEqual(APP.esito_whosampled(0.70, "non verificabile",
                                              soglia=0.80)["azione"], "scarta")


class TestUrlWhoSampled(unittest.TestCase):
    """Dall'URL salvato si rileggono artista e titolo: così si ricontrolla con
    l'audio un link già in libreria, senza riaprire il browser."""

    def test_url_vera(self):
        self.assertEqual(APP.artista_titolo_da_whosampled_url(
            "https://www.whosampled.com/Skeeter-Davis/The-End-of-the-World/"),
            ("Skeeter Davis", "The End of the World"))

    def test_senza_www_e_senza_slash_finale(self):
        self.assertEqual(APP.artista_titolo_da_whosampled_url(
            "https://whosampled.com/50-Cent/21-Questions/"), ("50 Cent", "21 Questions"))

    def test_percorsi_che_non_sono_una_canzone(self):
        for url in ("https://www.whosampled.com/search/?q=test",
                    "https://www.whosampled.com/sample/123456/Skeeter-Davis-The-End/",
                    "https://www.whosampled.com/artist/Skeeter-Davis/",
                    "https://esempio.com/Skeeter-Davis/The-End-of-the-World/",
                    "", None):
            self.assertIsNone(APP.artista_titolo_da_whosampled_url(url), url)

    def test_slug_con_caratteri_speciali(self):
        self.assertEqual(APP.artista_titolo_da_whosampled_url(
            "https://www.whosampled.com/Bad-Meets-Evil/Fast-Lane-(Remix)/"),
            ("Bad Meets Evil", "Fast Lane (Remix)"))


class TestArtistaIdentificabile(unittest.TestCase):
    """Quando l'anteprima ufficiale non esiste si accetta solo un candidato
    riconoscibile (o un titolo univoco): la stessa regola dei segnaposto di Genius."""

    def test_artista_gia_nel_titolo(self):
        self.assertTrue(APP.artista_identificabile_nel_titolo("Eminem", "Eminem Freestyle"))
        self.assertTrue(APP.artista_identificabile_nel_titolo("Eminem", "Freestyle di Eminem"))

    def test_artista_della_libreria_citato_nel_titolo(self):
        self.assertTrue(APP.artista_identificabile_nel_titolo(
            "Hopsin", "Simon says hopsin freestyle", ["Hopsin", "Eminem"]))
        self.assertFalse(APP.artista_identificabile_nel_titolo(
            "Skeeter Davis", "End of the World", ["Hopsin", "Eminem"]))

    def test_casi_vuoti(self):
        self.assertFalse(APP.artista_identificabile_nel_titolo("", "Titolo"))
        self.assertFalse(APP.artista_identificabile_nel_titolo("Artista", ""))
        self.assertFalse(APP.artista_identificabile_nel_titolo(None, None))


class TestCampiDalRisultatoAudio(unittest.TestCase):
    """Dai campi del verdetto alle colonne del database (due prefissi diversi)."""

    def test_prefisso_genius(self):
        campi = APP.campi_dal_risultato_audio(
            {"esito": "confermato", "voti": 12, "comuni": 30, "offset": 1.5,
             "fonte": "iTunes 1 · X — Y", "motivo_testo": None}, "audio_match_")
        self.assertEqual(set(campi), {"audio_match_esito", "audio_match_voti",
                                      "audio_match_comuni", "audio_match_offset",
                                      "audio_match_fonte", "audio_match_motivo",
                                      "audio_match_at"})
        self.assertEqual(campi["audio_match_esito"], "confermato")
        self.assertEqual(campi["audio_match_voti"], 12)
        self.assertIsNone(campi["audio_match_motivo"])      # il confronto è stato fatto
        self.assertTrue(campi["audio_match_at"])

    def test_prefisso_whosampled(self):
        campi = APP.campi_dal_risultato_audio(
            {"esito": "non confermato", "voti": 8, "comuni": 2517, "offset": 40.8,
             "fonte": "iTunes 2 · Skeeter Davis — The End of the World"}, "ws_audio_")
        self.assertIn("ws_audio_esito", campi)
        self.assertEqual(campi["ws_audio_voti"], 8)
        self.assertEqual(campi["ws_audio_offset"], 40.8)
        self.assertNotIn("audio_match_esito", campi)

    def test_il_motivo_finisce_nel_campo(self):
        campi = APP.campi_dal_risultato_audio(
            {"esito": "non verificabile", "voti": None, "comuni": None, "offset": None,
             "fonte": None, "motivo_testo": "nessuna anteprima ufficiale: iTunes 0 risultati per «X»"},
            "audio_match_")
        self.assertEqual(campi["audio_match_motivo"],
                         "nessuna anteprima ufficiale: iTunes 0 risultati per «X»")


class TestMotivoSenzaAnteprima(unittest.TestCase):
    """PERCHÉ non si è potuto confrontare: la frase che finisce in `*_motivo` e nel
    tooltip, così «non verificabile» non resta un mistero (richiesta di Alessandro)."""

    def test_zero_risultati(self):
        testo = APP.motivo_senza_anteprima(
            {"termine": "50 Cent 1998 Freestyle", "risultati": 0, "con_anteprima": 0},
            "50 Cent", "1998 Freestyle")
        self.assertEqual(testo,
                         "nessuna anteprima ufficiale: iTunes 0 risultati per «50 Cent 1998 Freestyle»")

    def test_risultati_senza_anteprima(self):
        testo = APP.motivo_senza_anteprima({"termine": "X Y", "risultati": 3, "con_anteprima": 0})
        self.assertIn("3 risultati su iTunes", testo)
        self.assertIn("nessuno ha l'anteprima", testo)

    def test_risultati_di_altri_artisti(self):
        testo = APP.motivo_senza_anteprima({"termine": "End of the World", "risultati": 5,
                                            "con_anteprima": 3, "artisti_scartati": 3})
        self.assertIn("sono di altri artisti", testo)
        self.assertIn("«End of the World»", testo)

    def test_candidato_sotto_soglia(self):
        testo = APP.motivo_senza_anteprima({"termine": "X", "risultati": 2, "con_anteprima": 1,
                                            "migliore": "Shadi — 1998 Freestyle",
                                            "punteggio": 0.42})
        self.assertIn("è troppo diverso", testo)
        self.assertIn("0.42 < 0.55", testo)

    def test_errore_di_rete(self):
        self.assertIn("ricerca iTunes non riuscita",
                      APP.motivo_senza_anteprima({"termine": "X", "errore": "URLError: timeout"}))

    def test_termine_ricostruito_se_manca(self):
        self.assertIn("«50 Cent 1998 Freestyle»",
                      APP.motivo_senza_anteprima({}, "50 Cent", "1998 Freestyle"))

    def test_diagnostica_della_ricerca_vera(self):
        # la ricerca VERA compila la diagnostica: il caso misurato il 18/09/2026
        diag = {}
        try:
            APP.cerca_anteprima_itunes("50 Cent", "1998 Freestyle", diagnostica=diag)
        except Exception as e:
            self.skipTest("iTunes non raggiungibile: %s" % e)
        self.assertEqual(diag.get("termine"), "50 Cent 1998 Freestyle")
        self.assertEqual(diag.get("risultati"), 0)
        self.assertEqual(APP.motivo_senza_anteprima(diag, "50 Cent", "1998 Freestyle"),
                         "nessuna anteprima ufficiale: iTunes 0 risultati per «50 Cent 1998 Freestyle»")
        self.assertEqual(APP.motivo_senza_anteprima({}, "50 Cent", "1998 Freestyle"),
                         "nessuna anteprima ufficiale: iTunes 0 risultati per «50 Cent 1998 Freestyle»")

    def test_diagnostica_con_artista_scartato(self):
        diag = {}
        try:
            APP.cerca_anteprima_itunes("Big Sean", "Control", diagnostica=diag)
        except Exception as e:
            self.skipTest("iTunes non raggiungibile: %s" % e)
        self.assertGreaterEqual(diag.get("risultati") or 0, 1)
        # il candidato "Control (Kendrick Lamar Diss)" di The Rap Mafia viene scartato
        self.assertGreaterEqual(diag.get("artisti_scartati") or 0, 1)
        self.assertIn("altri artisti", APP.motivo_senza_anteprima(diag, "Big Sean", "Control"))


class TestWsDaCercare(unittest.TestCase):
    """Quando la Verifica deve (ri)cercare il link WhoSampled? Una ricerca costa un
    browser e un confronto audio: non va ripetuta a vuoto, ma non va nemmeno saltata
    quando il titolo è stato corretto (caso di Alessandro del 18/09/2026)."""

    def test_senza_link_si_cerca(self):
        self.assertTrue(APP.ws_da_cercare(None, None, None, "End of the World"))

    def test_link_senza_verdetto_si_ricontrolla(self):
        self.assertTrue(APP.ws_da_cercare("https://www.whosampled.com/A/B/", None, None, "q"))

    def test_link_con_verdetto_non_si_ricontrolla(self):
        for esito in ("confermato", "non confermato", "scartato", "non verificabile"):
            self.assertFalse(APP.ws_da_cercare("https://www.whosampled.com/A/B/", esito, "q", "q"), esito)

    def test_candidato_scartato_stessa_query_non_si_ripete(self):
        self.assertFalse(APP.ws_da_cercare(None, "scartato", "End of the World", "End of the World"))

    def test_candidato_scartato_con_titolo_corretto_si_riprova(self):
        # il caso vero: la riga è stata corretta in "FORGOTTENAGE - End of the World"
        self.assertTrue(APP.ws_da_cercare(None, "scartato", "End of the World",
                                          "FORGOTTENAGE - End of the World"))

    def test_query_vuote(self):
        self.assertFalse(APP.ws_da_cercare(None, "scartato", "", ""))
        self.assertTrue(APP.ws_da_cercare("   ", None, None, ""))     # link vuoto = nessun link


@unittest.skipUnless(HA_OSASCRIPT, "JavaScriptCore (osascript) non disponibile")
class TestPaginaVerifica(unittest.TestCase):
    """La schermata di verifica guidata (`/verifica`): le funzioni pure della pagina
    (corpo della verifica, etichette dei verdetti) e la sintassi dello script —
    senza questo un errore di battitura romperebbe la pagina senza che nessun test
    se ne accorga (è già successo due volte, vedi il README)."""

    def _script(self):
        src = leggi(VERIFICA_PATH)
        m = re.search(r"<script>(.*?)</script>", src, re.S)
        if not m:
            raise AssertionError("nessun <script> in verifica.html")
        return src, m.group(1)

    def test_lo_script_compila(self):
        _, script = self._script()
        esito = esegui_js("try { new Function(%s); JSON.stringify('ok'); }"
                          " catch (e) { JSON.stringify('ERRORE: ' + e.message); }"
                          % json.dumps(script), "/tmp/test_verifica_sintassi.js")
        self.assertEqual(esito, "ok")

    def test_payload_della_verifica(self):
        src, _ = self._script()
        codice = (estrai_funzione(src, "payloadVerifica") + "\n"
                  "JSON.stringify(payloadVerifica({title:'Nuovo', artist:'Tizio'},"
                  " {audio:true, testo:true, acapella:true, non_su_genius:true,"
                  "  voti_conferma:'60', voti_rifiuto:'25', testo_conferma:'45', testo_rifiuto:'10'}));")
        d = esegui_js(codice, "/tmp/test_verifica_payload.js")
        self.assertEqual(d["metadata"], {"title": "Nuovo", "artist": "Tizio"})
        self.assertTrue(d["audio"] and d["testo"] and d["testo_acapella"] and d["non_su_genius"])
        self.assertEqual([d["voti_conferma"], d["voti_rifiuto"]], [60, 25])
        self.assertEqual([d["testo_conferma"], d["testo_rifiuto"]], [45, 10])

    def test_l_acapella_non_ha_senso_senza_il_controllo_voce(self):
        src, _ = self._script()
        codice = (estrai_funzione(src, "payloadVerifica") + "\n"
                  "JSON.stringify(payloadVerifica({}, {testo:false, acapella:true}));")
        d = esegui_js(codice, "/tmp/test_verifica_acapella.js")
        self.assertFalse(d["testo"])
        self.assertFalse(d["testo_acapella"])

    def test_etichette_dei_verdetti(self):
        src, _ = self._script()
        codice = (estrai_funzione(src, "etichettaVerdetto") + "\n"
                  "JSON.stringify(['confermato','non confermato','ambiguo','scartato',"
                  "'non verificabile','strano',''].map(etichettaVerdetto));")
        d = esegui_js(codice, "/tmp/test_verifica_etichette.js")
        self.assertEqual(d[0], ["ok", "✓ confermato"])
        self.assertEqual(d[1], ["no", "✗ non confermato"])
        self.assertEqual(d[2], ["amb", "? ambiguo"])
        self.assertEqual(d[3], ["no", "✗ candidato scartato"])
        self.assertEqual(d[4], ["mut", "– non verificabile"])
        self.assertEqual(d[5][0], "mut")          # esito sconosciuto: si mostra com'è
        self.assertEqual(d[6], ["mut", "—"])

    def test_la_pagina_ha_tutto_quello_che_serve(self):
        src, _ = leggi(VERIFICA_PATH), None
        for pezzo in ('id="metadati"', 'id="optAudio"', 'id="optTesto"', 'id="optAcapella"',
                      'id="optNoGenius"', 'id="tolVotiConf"', 'id="tolTestoConf"',
                      'id="progress"', 'id="passo"', 'id="msgs"', 'id="verdicts"',
                      'id="scheda"', "avviaVerifica()", "verify_status"):
            self.assertIn(pezzo, src, pezzo)

    def test_la_pagina_e_collegata_ai_pulsanti(self):
        self.assertIn("function apriVerifica(id)", leggi(INDEX_PATH))
        self.assertIn("onclick=\"apriVerifica('${s.id}')\"", leggi(INDEX_PATH))
        self.assertIn("function apriVerifica(trackId)", leggi(ONYX_PATH))
        self.assertIn("apriVerifica('${t.id}')", leggi(ONYX_PATH))
        # la rotta esiste nel backend e serve il file
        self.assertIn('@app.route("/verifica")', leggi(APP_PATH))
        self.assertIn('send_file(os.path.join(BASE_DIR, "verifica.html"))', leggi(APP_PATH))


def estrai_funzione_py(src, nome):
    """Il testo della funzione `nome` del backend (def a indentazione 0)."""
    m = re.search(r"^def %s\(" % re.escape(nome), src, re.M)
    if not m:
        raise AssertionError("funzione %s assente nel backend" % nome)
    righe = src[m.start():].splitlines(True)
    corpo = [righe[0]]
    for riga in righe[1:]:
        if riga.strip() and not riga[0].isspace():
            break
        corpo.append(riga)
    return "".join(corpo)


class TestConfrontoVoce(unittest.TestCase):
    """Il confronto voce: i due testi affiancati e i due audio da sentire (18/09/2026).

    Richiesta di Alessandro: «un pulsante sotto 🗣 voce … che permetta di vedere i
    testi a confronto, a sinistra il testo estratto e a destra quello vero, e anche
    i due audio che confronta, magari usando lo stesso player stile FL Studio del
    campionatore (senza trim giallo)». Per MOSTRARE i testi bisogna salvarli: prima
    la Verifica scriveva solo i numeri. Colonne nuove `testo_trascrizione`,
    `testo_riferimento`, `testo_parole_uniche`, i due file (`testo_audio_nostro`,
    `testo_audio_riferimento`) e `anteprima_file`, più la rotta `/anteprima/…`.

    Qui si prova anche il fix che ha reso possibile tutto questo: `esc()` non metteva
    al sicuro il doppio apice, quindi un valore come `["Dirty Swift"]` (Produttori)
    troncava l'attributo `value` e la Verifica riscriveva nel database il troncato
    ('[') — dato corrotto vero, trovato il 18/09/2026 sulla riga *21 Questions*.
    """

    def setUp(self):
        self.verifica = leggi(VERIFICA_PATH)
        self.app_src = leggi(APP_PATH)

    # ── la pagina: il pulsante e il pannello ─────────────────────────────────
    def test_il_pulsante_sta_sotto_il_verdetto_voce(self):
        verdetti = estrai_funzione(self.verifica, "mostraVerdetti")
        self.assertIn("if (s.testo_esito)", verdetti)
        self.assertIn("apriConfronto(true)", verdetti)
        self.assertIn("📄 Confronta testi e audio", verdetti)

    def test_la_pagina_ha_il_pannello(self):
        for pezzo in ('id="confrontoBox"', 'id="confrontoNumeri"', 'id="playerNostro"',
                      'id="playerRiferimento"', 'id="testoTrascrizione"', 'id="testoRiferimento"',
                      'id="btnConfronto"', 'id="confrontoNota"', 'id="switchVoce"',
                      'id="improntaBox"', 'id="improntaNumeri"', 'id="improntaNota"',
                      'id="playerImprontaNostro"', 'id="playerImprontaAnteprima"',
                      'id="btnImpronta"', "avviaImpronta()", "fermaImpronta()",
                      "apriConfronto(", "apriImpronta(", "avviaEntrambi()", "fermaEntrambi()",
                      "/confronto"):
            self.assertIn(pezzo, self.verifica, pezzo)
        # dopo una verifica i pannelli aperti si aggiornano da soli (dati appena salvi)
        corpo = estrai_funzione(self.verifica, "avviaVerifica")
        self.assertIn("apriConfronto(true)", corpo)
        self.assertIn("apriImpronta(true)", corpo)

    def test_il_pannello_voce_non_presta_l_audio_di_un_altro_controllo(self):
        """Lezione del 18/09/2026: la preview del passo 🔊 (30 s di iTunes) era finita
        accanto all'a-cappella del passo 🗣 (tutto il brano), come se il confronto voce
        confrontasse quei due file. Non è così: il passo voce confronta TRASCRIZIONE e
        TESTO. A destra c'è un player solo quando il riferimento È un audio; il
        confronto fra due audio ha il suo pannello (4 · impronta), con l'offset."""
        corpo = estrai_funzione(self.verifica, "mostraConfronto")
        self.assertIn("if (d.audio_riferimento)", corpo)
        self.assertNotIn("anteprima_file", corpo)
        self.assertIn("mostraInterruttoreVoce(d)", corpo)
        interruttore = estrai_funzione(self.verifica, "mostraInterruttoreVoce")
        self.assertIn("d.audio_mix", interruttore)
        impronta = estrai_funzione(self.verifica, "mostraImpronta")
        self.assertIn("imp.offset", impronta)
        self.assertIn("inizio: imp.offset", impronta)

    def test_il_pulsante_e_raggiungibile_anche_a_pagina_ricaricata(self):
        """Il pulsante dentro il blocco del progresso resta invisibile finché non si
        lancia una verifica (`.progress{display:none}`): su una canzone già verificata
        serviva un pulsante FUORI da quel blocco (lo ha trovato la prova in Chrome
        vero del 18/09/2026, che non riusciva a cliccarlo)."""
        fuori = self.verifica.index('id="btnConfronto"')
        fra = self.verifica[self.verifica.index('id="verdicts"'):fuori]
        self.assertGreaterEqual(fra.count("</div>"), 2,
                                "fra i verdetti e il pulsante devono chiudersi "
                                ".verdicts e .progress: il pulsante è fuori dal blocco")
        # e la sezione dice DA DOVE viene il verdetto (o perché non c'è ancora)
        corpo = estrai_funzione(self.verifica, "carica")
        self.assertIn('document.getElementById("confrontoNota").textContent', corpo)
        self.assertIn("etichettaVerdetto(s.testo_esito)", corpo)

    def test_i_due_player_non_hanno_il_trim_giallo(self):
        corpo = estrai_funzione(self.verifica, "creaPlayer")
        for vietato in ("trimStart", "trimEnd", "Trim giallo", "toggleTrimGiallo", "Battute"):
            self.assertNotIn(vietato, corpo)
        self.assertIn("frazioneDaClick(", corpo)     # click sull'onda = vai a quel punto
        self.assertIn("picchiDaBuffer(", corpo)      # forma d'onda vera, come il sampler

    def test_lo_script_compila(self):
        script = re.search(r"<script>(.*?)</script>", self.verifica, re.S).group(1)
        esito = esegui_js("try { new Function(%s); JSON.stringify('ok'); }"
                          " catch (e) { JSON.stringify('ERRORE: ' + e.message); }"
                          % json.dumps(script), "/tmp/test_confronto_sintassi.js")
        self.assertEqual(esito, "ok")

    # ── le funzioni pure, eseguite davvero in JavaScriptCore ─────────────────
    def test_escape_delle_virgolette(self):
        codice = (estrai_funzione(self.verifica, "esc") + "\n"
                  "JSON.stringify([esc('[\\\"Dirty Swift\\\"]'),"
                  " esc(\"Royce Da 5'9\\\"\"), esc('a & b <c>')]);")
        d = esegui_js(codice, "/tmp/test_confronto_esc.js")
        self.assertEqual(d[0], "[&quot;Dirty Swift&quot;]")
        self.assertEqual(d[1], "Royce Da 5&#39;9&quot;")
        self.assertEqual(d[2], "a &amp; b &lt;c&gt;")
        # le caselle dei dati si riempiono con l'escape (era la riga del bug)
        self.assertIn('value="${esc(valoreMostrato(campo, s))}"', self.verifica)

    def test_i_produttori_si_leggono_e_si_riscrivono(self):
        codice = (estrai_funzione(self.verifica, "producersTesto") + "\n"
                  + estrai_funzione(self.verifica, "producersJson") + "\n"
                  "JSON.stringify([producersTesto('[\\\"Dr. Dre\\\", \\\"Mel-Man\\\"]'),"
                  " producersTesto('Raedius'), producersTesto(null),"
                  " producersJson('Dirty Swift'), producersJson('Dr. Dre, Mel-Man'),"
                  " producersJson('[\\\"Dirty Swift\\\"]'),"
                  " producersJson(producersTesto('[\\\"Dr. Dre\\\", \\\"Mel-Man\\\"]'))]);")
        d = esegui_js(codice, "/tmp/test_confronto_producers.js")
        self.assertEqual(d[0], "Dr. Dre, Mel-Man")
        self.assertEqual(d[1], "Raedius")
        self.assertEqual(d[2], "")
        self.assertEqual(d[3], '["Dirty Swift"]')
        self.assertEqual(d[4], '["Dr. Dre","Mel-Man"]')
        self.assertEqual(d[5], '["Dirty Swift"]')          # già JSON: resta com'è
        self.assertEqual(d[6], '["Dr. Dre","Mel-Man"]')     # andata e ritorno


    def test_le_parole_in_comune_sono_evidenziate(self):
        codice = ("function esc(s){return String(s==null?'':s).replace(/&/g,'&amp;')"
                  ".replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/\"/g,'&quot;')"
                  ".replace(/'/g,'&#39;')}\n"
                  + estrai_funzione(self.verifica, "normalizzaParola") + "\n"
                  + estrai_funzione(self.verifica, "evidenzia") + "\n"
                  "JSON.stringify([evidenzia('Girl, it\\'s easy to love me \\n[Chorus: Nate Dogg]',"
                  " ['easy','love']), evidenzia('niente', []), normalizzaParola('Love,'),"
                  " normalizzaParola('LOVE\\u2019s')]);")
        d = esegui_js(codice, "/tmp/test_confronto_evidenzia.js")
        self.assertIn("<mark>easy</mark>", d[0])
        self.assertIn("<mark>love</mark>", d[0])
        self.assertNotIn("<mark>Girl</mark>", d[0])         # non è in comune
        self.assertIn("\n", d[0])                           # gli a capo restano
        self.assertEqual(d[1], "niente")                    # senza comuni: nessun mark
        self.assertEqual(d[2], "love")
        self.assertEqual(d[3], "love's")

    def test_i_numeri_del_confronto(self):
        codice = (estrai_funzione(self.verifica, "formattaTempo") + "\n"
                  + estrai_funzione(self.verifica, "frazioneDaClick") + "\n"
                  "JSON.stringify([formattaTempo(0), formattaTempo(67), formattaTempo(258.6),"
                  " frazioneDaClick(150, 100, 100), frazioneDaClick(50, 100, 100),"
                  " frazioneDaClick(999, 100, 100), frazioneDaClick(100, 100, 0)]);")
        d = esegui_js(codice, "/tmp/test_confronto_numeri.js")
        self.assertEqual(d[0], "0:00")
        self.assertEqual(d[1], "1:07")
        self.assertEqual(d[2], "4:18")          # 258,6 s = la durata di *21 Questions*
        self.assertEqual(d[3], 0.5)
        self.assertEqual(d[4], 0)               # prima dell'onda: si ferma a 0
        self.assertEqual(d[5], 1)               # oltre la fine: si ferma a 1
        self.assertEqual(d[6], 0)               # larghezza zero: niente divisione per zero

    def test_il_punto_allineato_del_confronto_audio(self):
        """Il nostro file parte da dove l'impronta ha trovato l'anteprima (misurato:
        76,022 s su *21 Questions*); se l'offset non ha senso si parte dall'inizio."""
        codice = (estrai_funzione(self.verifica, "puntoAllineato") + "\n"
                  "JSON.stringify([puntoAllineato(76.022, 258.6), puntoAllineato(0, 258.6),"
                  " puntoAllineato(-5, 258.6), puntoAllineato(300, 258.6),"
                  " puntoAllineato('', 258.6), puntoAllineato(76, NaN),"
                  " puntoAllineato(null, null)]);")
        d = esegui_js(codice, "/tmp/test_confronto_punto.js")
        self.assertAlmostEqual(d[0], 76.022, places=3)
        self.assertEqual(d[1], 0)       # senza offset: dall'inizio
        self.assertEqual(d[2], 0)       # negativo: dall'inizio
        self.assertEqual(d[3], 0)       # oltre la durata del file: dall'inizio
        self.assertEqual(d[4], 0)
        self.assertEqual(d[5], 76)      # durata sconosciuta: ci si fida dell'offset
        self.assertEqual(d[6], 0)

    # ── il backend ────────────────────────────────────────────────────────────
    def test_i_testi_e_i_file_finiscono_nel_database(self):
        campi = APP.campi_dal_risultato_testo({
            "esito": "confermato", "copertura": 77.2, "parole": 268,
            "fonte": "liriche (152 parole) · trascrizione a cappella", "motivo": None,
            "trascrizione": "New York City", "riferimento_testo": "[Intro] New York City",
            "parole_uniche": 207,
            "file_nostro": os.path.join(APP.DL_DIR, "brano.mp3"),
            "file_riferimento": os.path.join(APP.ANTEPRIME_DIR, "6811474800_21_Questions.m4a")})
        self.assertEqual(campi["testo_trascrizione"], "New York City")
        self.assertEqual(campi["testo_riferimento"], "[Intro] New York City")
        self.assertEqual(campi["testo_parole_uniche"], 207)
        self.assertEqual(campi["testo_audio_nostro"], "downloads/brano.mp3")
        self.assertEqual(campi["testo_audio_riferimento"],
                         "anteprime/6811474800_21_Questions.m4a")
        self.assertEqual(campi["testo_esito"], "confermato")
        # un confronto che non si è potuto fare: campi vuoti, non chiavi mancanti
        vuoto = APP.campi_dal_risultato_testo({
            "esito": "non verificabile", "copertura": None, "parole": None, "fonte": None,
            "motivo": "faster-whisper non è installato", "trascrizione": None,
            "riferimento_testo": None, "parole_uniche": None,
            "file_nostro": None, "file_riferimento": None})
        self.assertIsNone(vuoto["testo_trascrizione"])
        self.assertIsNone(vuoto["testo_audio_nostro"])

    def test_percorso_relativo_solo_dentro_la_cartella(self):
        self.assertIsNone(APP.percorso_relativo(""))
        self.assertIsNone(APP.percorso_relativo("/etc/passwd"))
        self.assertEqual(APP.percorso_relativo(os.path.join(APP.DL_DIR, "x.mp3")),
                         "downloads/x.mp3")

    def test_url_dei_due_audio(self):
        self.assertEqual(APP._audio_del_confronto("downloads/a b.mp3", "x")["url"],
                         "/stream/a%20b.mp3")
        self.assertEqual(
            APP._audio_del_confronto("anteprime/acapella_1/htdemucs/f/vocals.mp3", "x")["url"],
            "/anteprima/acapella_1/htdemucs/f/vocals.mp3")
        self.assertIsNone(APP._audio_del_confronto("", "x"))
        self.assertIsNone(APP._audio_del_confronto("stems/f.mp3", "x"))
        # righe verificate prima del 18/09/2026: senza il campo si ripiega sul file locale
        d = APP._audio_del_confronto("", "x", default_rel="downloads/brano.mp3")
        self.assertEqual(d["url"], "/stream/brano.mp3")

    def test_dalla_cartella_non_si_esce(self):
        self.assertTrue(APP._dentro_la_cartella(APP.DL_DIR, os.path.join(APP.DL_DIR, "x.mp3")))
        self.assertFalse(APP._dentro_la_cartella(
            APP.DL_DIR, os.path.join(APP.DL_DIR, "..", "app (2).py")))

    def test_rotta_colonne_e_legenda(self):
        self.assertIn('@app.route("/anteprima/<path:filename>")', self.app_src)
        self.assertIn('@app.route("/db/songs/<song_id>/confronto", methods=["GET"])', self.app_src)
        for colonna in ("testo_trascrizione", "testo_riferimento", "testo_parole_uniche",
                        "testo_audio_nostro", "testo_audio_riferimento", "anteprima_file"):
            self.assertIn('"%s"' % colonna, self.app_src)
            self.assertIn('"%s":' % colonna, self.app_src)      # anche nella legenda
        # i testi e i file del confronto sono salvati dal passo 🗣 e dai due 🔇/🔊
        self.assertIn("percorso_relativo(risultato.get(\"file_riferimento\"))",
                      estrai_funzione_py(self.app_src, "conferma_audio"))


class TestProgressoVerifica(unittest.TestCase):
    """Il progresso TOTALE della verifica (0-100%) — 18/09/2026.

    Richiesta di Alessandro: «anziché Passo 7/7 · 🗣 Trascrivo il file locale (a
    cappella)… o quantomeno oltre a questo… potrei vedere una barra di avanzamento
    totale che va da 0 a 100? tipo una rotella o qualcosa del genere che indica
    progresso». Prima la barra faceva 7 salti e dentro la trascrizione (60-85 s)
    sembrava ferma: ora i passi hanno un PESO in secondi, il passo corrente porta la
    sua frazione — quella VERA quando il pezzo la sa dire (Whisper dai segmenti già
    trascritti, demucs dal suo avanzamento) — e il resto è stima dal tempo trascorso,
    mai oltre il 90% del passo (la barra non deve arrivare a 100 prima della fine).
    """

    def setUp(self):
        self.app_src = leggi(APP_PATH)
        self.verifica = leggi(VERIFICA_PATH)

    def test_percento_del_lavoro_totale(self):
        self.assertEqual(APP._verify_percento(1, None, 0), 0)          # non è iniziato
        # la frazione VERA conta subito: metà trascrizione = ~2/3 del lavoro
        meta_trascrizione = APP._verify_percento(7, 0.5, 0)
        self.assertGreater(meta_trascrizione, 60)
        self.assertLess(meta_trascrizione, 75)
        self.assertEqual(APP._verify_percento(7, 1.0, 0), 100)         # solo alla fine
        self.assertLess(APP._verify_percento(7, None, 100000), 100)    # la stima no
        self.assertEqual(APP._verify_percento(2, None, 0), 2)          # dopo il passo 1

    def test_cresce_sempre_e_non_esce_dai_limiti(self):
        # ⚠️ la monotonia si controlla NELL'ORDINE DI ESECUZIONE, non 1-2-3…: il 6
        # (audio) viene prima di 3-4-5, e il conto tiene conto di questo.
        valori = [APP._verify_percento(k, None, 0) for k in APP.VERIFY_ORDINE]
        self.assertEqual(valori, sorted(valori), "il progresso non torna indietro")
        for passo in sorted(APP.VERIFY_PESI):
            for frazione in (None, 0, 0.5, 1):
                for secondi in (0, 10, 10000):
                    p = APP._verify_percento(passo, frazione, secondi)
                    self.assertGreaterEqual(p, 0)
                    self.assertLessEqual(p, 100)

    def test_la_frazione_vera_non_torna_indietro(self):
        chiave = "song_test_progresso"
        APP.verify_progress[chiave] = {"step": 7, "total": 7, "status": "x", "ts": 0,
                                       "iniziato": 0, "frazione": None}
        try:
            APP._avanza_verify(chiave, 0.4)
            self.assertAlmostEqual(APP.verify_progress[chiave]["frazione"], 0.4)
            APP._avanza_verify(chiave, 0.2)         # misura più arretrata: si ignora
            self.assertAlmostEqual(APP.verify_progress[chiave]["frazione"], 0.4)
            APP._avanza_verify(chiave, 5)           # fuori scala: si taglia a 1
            self.assertEqual(APP.verify_progress[chiave]["frazione"], 1.0)
            APP._avanza_verify(chiave, "boh")       # non solleva
            APP._avanza_verify("song_inesistente", 0.5)
        finally:
            APP.verify_progress.pop(chiave, None)

    def test_il_progresso_non_scende_cambiando_passo(self):
        """Il 18/09/2026 la percentuale SCENDEVA («ci sono momenti in cui è alta e poi
        torna più bassa»): i passi non girano in ordine numerico (l'audio, il 6, viene
        subito dopo il 2) e il conto era «somma dei passi con numero minore», così dal
        6 (≈30%) si passava al 3 (≈6%). Ora si usa l'ORDINE vero."""
        self.assertEqual(tuple(APP.VERIFY_ORDINE), (1, 2, 6, 3, 4, 5, 7))
        # entrando in un passo, quelli che lo precedono NELL'ORDINE sono finiti
        self.assertEqual(APP._verify_percento(1, None, 0), 0)
        self.assertEqual(APP._verify_percento(2, None, 0), 2)          # dopo 1 (3)
        self.assertEqual(APP._verify_percento(6, None, 0), 6)          # dopo 1, 2 (9)
        self.assertEqual(APP._verify_percento(3, None, 0), 15)         # dopo 1, 2, 6 (21)
        self.assertEqual(APP._verify_percento(4, None, 0), 20)         # + 3 (29)
        self.assertEqual(APP._verify_percento(5, None, 0), 34)         # + 4 (49)
        self.assertEqual(APP._verify_percento(7, None, 0), 37)         # + 5 (53)
        # e in nessun passaggio intermedio la percentuale può calare
        valori = []
        for passo in APP.VERIFY_ORDINE:
            valori.append(APP._verify_percento(passo, None, 10 ** 6))  # passo "finito"
        self.assertEqual(valori, sorted(valori), valori)
        self.assertGreaterEqual(APP._verify_percento(3, None, 0),
                                APP._verify_percento(6, None, 10 ** 6))

    def test_un_passo_che_sa_la_sua_frazione_non_se_la_inventa(self):
        """Nei passi «misurabili» (trascrizione) la stima dal tempo non si usa: meglio
        un numero fermo che uno inventato che poi scende quando arriva la misura vera."""
        self.assertEqual(APP._verify_percento(7, None, 100000, True), 37)
        self.assertEqual(APP._verify_percento(7, None, 100000, False), 94)
        # e la misura vera (metà trascrizione) vale più della stima
        self.assertGreater(APP._verify_percento(7, 0.5, 0, True),
                           APP._verify_percento(7, None, 100000, True))

    def test_lo_stesso_passo_non_azzera_quello_che_ha_fatto(self):
        """Dentro il passo 7 ci sono più annunci («Analisi audio (BPM/Key)…», «Trascrivo
        il file locale…»): un nuovo annuncio non deve azzerare la frazione già misurata
        né il cronometro (era un'altra causa del tornare indietro)."""
        chiave = "song_test_stesso_passo"
        try:
            APP._set_verify_status(chiave, 7, 7, "Analisi audio (BPM/Key)…", misurabile=True)
            APP._avanza_verify(chiave, 0.5)
            inizio = APP.verify_progress[chiave]["iniziato"]
            time.sleep(0.05)
            APP._set_verify_status(chiave, 7, 7, "🗣 Trascrivo il file locale…",
                                   misurabile=True)
            stato = APP.verify_progress[chiave]
            self.assertAlmostEqual(stato["frazione"], 0.5)
            self.assertEqual(stato["iniziato"], inizio)          # cronometro non azzerato
            self.assertIn("Trascrivo", stato["status"])          # ma il testo sì
            # cambiando passo la frazione riparte (è un altro lavoro)
            APP._set_verify_status(chiave, 6, 7, "🔊 Confronto…")
            self.assertIsNone(APP.verify_progress[chiave]["frazione"])
            self.assertEqual(APP.verify_progress[chiave]["step"], 6)
        finally:
            APP.verify_progress.pop(chiave, None)

    def test_il_massimo_non_torna_indietro(self):
        self.assertEqual(APP._con_il_massimo(30, 6), 30)
        self.assertEqual(APP._con_il_massimo(None, 6), 6)
        self.assertEqual(APP._con_il_massimo("boh", 6), 6)
        self.assertEqual(APP._con_il_massimo(0, 0), 0)
        self.assertIn("percento = _con_il_massimo(st.get(\"percento_max\"), percento)",
                      leggi(APP_PATH))

    def test_il_progresso_vero_dei_due_pezzi_lunghi(self):
        trascrivi = estrai_funzione_py(self.app_src, "trascrivi")
        self.assertIn("avanza=None", trascrivi)
        self.assertIn('getattr(seg, "end", 0)', trascrivi)      # Whisper: i segmenti
        self.assertIn("avanza_whisper", trascrivi)
        cappella = estrai_funzione_py(self.app_src, "a_cappella")
        self.assertIn("avanza=None", cappella)
        self.assertIn(r"(\d{1,3})%", cappella)                  # demucs: le sue %
        self.assertIn("select.select", cappella)                # timeout rispettato
        # il passo 7 della Verifica passa la sua frazione al contatore
        corpo = estrai_funzione_py(self.app_src, "verify_song")
        self.assertEqual(corpo.count("avanza=lambda f: _avanza_verify(song_id, f)"), 2)

    def test_l_endpoint_lo_dice_alla_pagina(self):
        self.assertIn("percento = _verify_percento(st[\"step\"], st.get(\"frazione\"), secondi,",
                      self.app_src)
        self.assertIn('"percento": percento', self.app_src)
        self.assertIn('"secondi": round(secondi, 1)', self.app_src)
        for pezzo in ('id="percento"', 'id="rotella"', 'id="secondi"',
                      'st.percento', 'classList.add("ferma")', "1200"):
            self.assertIn(pezzo, self.verifica, pezzo)


class TestCablaggio(unittest.TestCase):
    """Il passo 🔊 è agganciato al posto giusto: dentro la Verifica (prima di
    BPM/Key), con endpoint dedicato, migrazione, legenda e interfaccia."""

    def setUp(self):
        self.app_src = leggi(APP_PATH)
        self.index_src = leggi(INDEX_PATH)
        self.onyx_src = leggi(ONYX_PATH)

    def test_rotta_dedicata(self):
        self.assertIn('@app.route("/db/songs/<song_id>/audio_check", methods=["POST"])', self.app_src)
        self.assertIn("def audio_check_song(song_id):", self.app_src)

    def test_passo_dentro_la_verifica(self):
        corpo = estrai_funzione_py(self.app_src, "verify_song")
        self.assertIn("conferma_audio(", corpo)
        self.assertIn("AUDIO_SCORE_SOSPETTO", corpo)
        self.assertIn('get("audio")', corpo)
        # il controllo audio sta PRIMA di BPM/Key, che resta l'ultimo passo (7/7)
        self.assertLess(corpo.index("conferma_audio("), corpo.index("─── BPM & KEY"))
        self.assertIn("VERIFY_TOTALE = 7", self.app_src)
        self.assertIn("_set_verify_status(song_id, 6, VERIFY_TOTALE", corpo)
        self.assertIn("_set_verify_status(song_id, 7, VERIFY_TOTALE", corpo)

    def test_migrazione_delle_colonne(self):
        for colonna, tipo in (("audio_match_esito", "TEXT"), ("audio_match_voti", "INTEGER"),
                              ("audio_match_offset", "REAL"), ("audio_match_comuni", "INTEGER"),
                              ("audio_match_fonte", "TEXT"), ("audio_match_at", "TEXT")):
            self.assertIn('("%s", "%s")' % (colonna, tipo), self.app_src)

    def test_legenda_delle_colonne(self):
        for colonna in ("audio_match_esito", "audio_match_voti", "audio_match_offset",
                        "audio_match_comuni", "audio_match_fonte", "audio_match_at"):
            self.assertIn('"%s":' % colonna, self.app_src)

    def test_nessuna_dipendenza_nuova(self):
        # si usa solo ffmpeg + numpy + librosa: già in requirements.txt
        for modulo in ("acoustid", "chromaprint", "scipy", "essentia"):
            self.assertNotIn("import %s" % modulo, self.app_src)
        req = leggi(os.path.join(BASE_DIR, "requirements.txt"))
        self.assertIn("numpy", req)
        self.assertIn("librosa", req)

    def test_interfaccia(self):
        self.assertIn("db-audio-btn", self.index_src)
        self.assertEqual(self.index_src.count("audioCheckSong("), 2)   # onclick + definizione
        for pezzo in ("✓ confermato", "✗ non confermato", "? ambiguo", "– non verificabile"):
            self.assertIn(pezzo, self.index_src)
        self.assertIn("✗ candidato scartato", self.index_src)
        # la pastiglia sta nella riga della tabella, accanto al pulsante Verifica
        riga = estrai_funzione(self.index_src, "renderDbTable")
        self.assertIn("chipAudio(s)", riga)
        self.assertIn("db-audio-btn", riga)

    def test_whosampled_confermato_dall_audio(self):
        corpo = estrai_funzione_py(self.app_src, "verify_song")
        self.assertIn("esito_whosampled(", corpo)
        self.assertIn("verifica_audio_riferimento(", corpo)
        self.assertIn("ws_da_controllare", corpo)
        self.assertIn("ws_da_cercare(", corpo)
        self.assertIn("query_ws", corpo)
        self.assertIn('updates["ws_query"] = query_ws', corpo)
        self.assertIn('updates["ws_match_score"] = round(ws_score, 3)', corpo)
        self.assertIn('campi_dal_risultato_audio(verdetto, "ws_audio_")', corpo)
        # il link sbagliato si RIMUOVE e il CANDIDATO scartato si SCRIVE comunque
        self.assertIn('decisione.get("rimuovi_url")', corpo)
        self.assertIn('updates["whosampled_url"] = None', corpo)
        self.assertIn('updates["ws_audio_esito"] = "scartato"', corpo)

    def test_il_player_non_mostra_piu_un_link_rimosso(self):
        """Il difetto segnalato il 18/09/2026: il player tiene una copia propria
        (IndexedDB) e, quando il database toglieva un link, la copia restava — così
        sembrava che la Verifica non avesse controllato."""
        self.assertIn("track.whosampledUrl = s.whosampled_url || '';", self.onyx_src)
        self.assertIn("track.geniusUrl = s.genius_url || '';", self.onyx_src)
        self.assertIn("whosampledUrl: row.whosampled_url || '',", self.onyx_src)
        # e il pannello del player mostra il verdetto audio (link e canzone)
        self.assertIn("wsAudioMotivo", self.onyx_src)
        self.assertIn('🔊 ${escHtml(dove)}: ${escHtml(esito)}', self.onyx_src)

    def test_ricerca_whosampled_non_piu_a_occhio(self):
        # senza artista si sceglie per TITOLO, non `candidates[0]` (era il motivo per
        # cui *End of the World* finiva sulla pagina di Skeeter Davis)
        corpo = estrai_funzione_py(self.app_src, "search_whosampled")
        self.assertNotIn("return candidates[0], candidates", corpo)
        self.assertIn('match_score("", searched_title, "", c["title"])', corpo)

    def test_endpoint_controlla_anche_il_link_salvato(self):
        corpo = estrai_funzione_py(self.app_src, "audio_check_song")
        self.assertIn("artista_titolo_da_whosampled_url(", corpo)
        self.assertIn("esito_whosampled(", corpo)
        self.assertIn('"esito_whosampled"', corpo)

    def test_colonne_whosampled(self):
        for colonna, tipo in (("ws_match_score", "REAL"), ("ws_audio_esito", "TEXT"),
                              ("ws_audio_voti", "INTEGER"), ("ws_audio_offset", "REAL"),
                              ("ws_audio_comuni", "INTEGER"), ("ws_audio_fonte", "TEXT"),
                              ("ws_audio_at", "TEXT")):
            self.assertIn('("%s", "%s")' % (colonna, tipo), self.app_src)
            self.assertIn('"%s":' % colonna, self.app_src)

    def test_pastiglia_del_link_in_pagina(self):
        riga = estrai_funzione(self.index_src, "renderDbTable")
        self.assertIn("chipAudio(s,'whosampled')", riga)
        self.assertIn("function chipAudio(s, quale)", self.index_src)

    def test_il_motivo_e_collegato(self):
        # le due colonne del motivo, la legenda, la frase nel backend e la pastiglia
        for colonna in ("audio_match_motivo", "ws_audio_motivo"):
            self.assertIn('("%s", "TEXT")' % colonna, self.app_src)
            self.assertIn('"%s":' % colonna, self.app_src)
        corpo = estrai_funzione_py(self.app_src, "verifica_audio_riferimento")
        self.assertIn("motivo_senza_anteprima(", corpo)
        self.assertIn('"motivo_testo"', corpo)
        diagnostica = estrai_funzione_py(self.app_src, "cerca_anteprima_itunes")
        self.assertIn("diagnostica", diagnostica)
        self.assertIn("artisti_scartati", diagnostica)
        self.assertIn("function motivoBreve(motivo, max)", self.index_src)
        self.assertIn("motivoBreve(", estrai_funzione(self.index_src, "chipAudio"))


@unittest.skipUnless(app_is_up(SAMPLELAB_URL), "app non attiva su " + SAMPLELAB_URL)
class TestAppViva(unittest.TestCase):
    """Le colonne nuove escono da /db/songs (SELECT *) e l'endpoint risponde."""

    def test_colonne_nel_payload(self):
        with urllib.request.urlopen(SAMPLELAB_URL + "/db/songs", timeout=60) as r:
            songs = json.load(r)
        if not songs:
            self.skipTest("database vuoto")
        for campo in ("audio_match_esito", "audio_match_voti", "audio_match_offset",
                      "audio_match_comuni", "audio_match_fonte", "audio_match_at"):
            self.assertIn(campo, songs[0])

    def test_canzone_inesistente(self):
        req = urllib.request.Request(
            SAMPLELAB_URL + "/db/songs/song_questa_non_esiste/audio_check", method="POST")
        try:
            urllib.request.urlopen(req, timeout=20)
            self.fail("atteso HTTP 404")
        except urllib.error.HTTPError as e:
            self.assertEqual(e.code, 404)

    def test_pagina_servita(self):
        with urllib.request.urlopen(SAMPLELAB_URL + "/", timeout=30) as r:
            html = r.read().decode("utf-8", "replace")
        self.assertIn("function chipAudio(s, quale)", html)
        self.assertIn("db-audio-btn", html)
        self.assertIn("/audio_check", html)

    def test_controllo_audio_vero(self):
        """Il caso vero (quello del pulsante 🔊): *21 Questions* → anteprima
        ufficiale → esito scritto in `songs.audio_match_*`. Senza rete diventa
        'non verificabile' e il test resta valido (un dato mancante non è un sì)."""
        with urllib.request.urlopen(SAMPLELAB_URL + "/db/songs", timeout=60) as r:
            songs = json.load(r)
        canzone = [s for s in songs if s["id"] == ID_21_QUESTIONS]
        if not canzone:
            self.skipTest("la canzone %s non è più in libreria" % ID_21_QUESTIONS)
        if not canzone[0].get("local_file"):
            self.skipTest("la canzone non ha il file locale")
        req = urllib.request.Request(
            SAMPLELAB_URL + "/db/songs/%s/audio_check" % ID_21_QUESTIONS, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=180) as r:
                res = json.load(r)
        except Exception as e:
            self.skipTest("controllo audio non eseguibile: %s" % e)
        self.assertIn(res.get("esito"),
                      ("confermato", "non confermato", "ambiguo", "non verificabile"))
        self.assertTrue(res.get("messages"))
        # il controllo copre anche il link WhoSampled salvato (None se la riga non ne ha)
        self.assertIn("esito_whosampled", res)
        song = res.get("song") or {}
        self.assertEqual(song.get("audio_match_esito"), res.get("esito"))
        self.assertTrue(song.get("audio_match_at"))
        if res.get("esito") == "confermato":
            self.assertGreaterEqual(song.get("audio_match_voti") or 0, APP.AUDIO_VOTI_CONFERMA)
            self.assertIsNotNone(song.get("audio_match_offset"))





    def test_confronto_della_canzone_vera(self):
        """Il pannello «📄 Confronta» ha quello che gli serve per *21 Questions*:
        i due testi, i numeri (attese/sentite/uniche/in comune) e i due audio."""
        with urllib.request.urlopen(
                SAMPLELAB_URL + "/db/songs/%s/confronto" % ID_21_QUESTIONS, timeout=60) as r:
            d = json.load(r)
        for campo in ("pronto", "tipo", "trascrizione", "riferimento", "parole_attese",
                      "parole_sentite", "parole_sentite_uniche", "comuni", "comuni_quanti",
                      "audio_nostro", "audio_riferimento"):
            self.assertIn(campo, d)
        self.assertTrue(d["riferimento"], "le liriche ci sono")
        self.assertEqual(d["tipo"], "liriche")
        self.assertEqual(d["parole_attese"], 152)        # il numero che cita la fonte
        # il nostro audio: il file locale (`/stream/…`) o l'a-cappella (`/anteprima/…`,
        # quando la verifica è stata fatta con 🎤: è la voce che Whisper ha trascritto)
        self.assertTrue(d["audio_nostro"]["url"].startswith(("/stream/", "/anteprima/")),
                        d["audio_nostro"]["url"])
        self.assertTrue(d["audio_nostro"]["percorso"].startswith(("downloads/", "anteprime/")),
                        d["audio_nostro"]["percorso"])
        # il testo trascritto c'è solo dalle verifiche fatte col salvataggio nuovo
        if d["pronto"]:
            self.assertTrue(d["trascrizione"])
            self.assertTrue(d["comuni"])
            self.assertLessEqual(d["comuni_quanti"], d["parole_attese"])
            self.assertLessEqual(d["comuni_quanti"], d["parole_sentite_uniche"])
        # il pannello voce NON deve ricevere l'anteprima del passo 🔊 (incoerenza del
        # 18/09/2026: il riferimento qui è il TESTO, non un audio)
        self.assertIsNone(d["audio_riferimento"])
        # ...e il confronto audio ha i suoi dati, con l'offset: il nostro file parte da lì
        self.assertIsNotNone(d["impronta"])
        self.assertEqual(d["impronta"]["esito"], "confermato")
        self.assertGreaterEqual(d["impronta"]["voti"], 50)
        self.assertAlmostEqual(d["impronta"]["offset"], 76.0, delta=1.0)
        self.assertTrue(d["impronta"]["audio_anteprima"]["url"].startswith("/anteprima/"))
        self.assertTrue(d["impronta"]["audio_nostro"]["url"].startswith("/stream/"))
        if d["audio_mix"]:      # l'interruttore mix/a-cappella del pannello voce
            self.assertTrue(d["audio_mix"]["url"].startswith("/stream/"))

    def test_confronto_canzone_inesistente(self):
        try:
            urllib.request.urlopen(SAMPLELAB_URL + "/db/songs/song_non_esiste/confronto",
                                   timeout=20)
            self.fail("atteso HTTP 404")
        except urllib.error.HTTPError as e:
            self.assertEqual(e.code, 404)

    def test_anteprima_servita_col_range(self):
        """La rotta nuova `/anteprima/…`: serve i file di `anteprime/` (cartella NON
        versionata, quindi il test si salta se il file non c'è) e risponde 206 al
        Range, che è quello che fa scorrere la barra dei due player."""
        nome = "6811474800_21_Questions__feat__Nate_Dogg_.m4a"
        percorso = os.path.join(APP.ANTEPRIME_DIR, nome)
        if not os.path.exists(percorso):
            self.skipTest("anteprima non presente (cartella non versionata)")
        req = urllib.request.Request(SAMPLELAB_URL + "/anteprima/" + nome,
                                     headers={"Range": "bytes=0-1023"})
        with urllib.request.urlopen(req, timeout=30) as r:
            self.assertEqual(r.status, 206)
            self.assertEqual(r.headers.get("Content-Range", "").split("/")[-1],
                             str(os.path.getsize(percorso)))
            self.assertEqual(len(r.read()), 1024)

    def test_anteprima_inesistente_e_fuori_cartella(self):
        for brutto in ("/anteprima/non_esiste.m4a", "/anteprima/..%2F..%2Fetc%2Fpasswd"):
            try:
                urllib.request.urlopen(SAMPLELAB_URL + brutto, timeout=20)
                self.fail("atteso HTTP 404 per %s" % brutto)
            except urllib.error.HTTPError as e:
                self.assertEqual(e.code, 404, brutto)

    def test_pagina_verifica_col_confronto(self):
        with urllib.request.urlopen(
                SAMPLELAB_URL + "/verifica?song=" + ID_21_QUESTIONS, timeout=30) as r:
            html = r.read().decode("utf-8", "replace")
        for pezzo in ('id="confrontoBox"', "apriConfronto(", "avviaEntrambi()",
                      "/db/songs/", "playerRiferimento"):
            self.assertIn(pezzo, html)


class TestAnteprimaItunes(unittest.TestCase):
    """L'anteprima ufficiale: è l'unico modo di sentire "ciò che Genius ha
    trovato", perché Genius non serve file audio."""

    def test_termini_vuoti_non_chiamano_la_rete(self):
        self.assertIsNone(APP.cerca_anteprima_itunes("", ""))
        self.assertIsNone(APP.cerca_anteprima_itunes(None, None))
        self.assertIsNone(APP.cerca_anteprima_itunes("   ", "  "))

    def test_scaricamento_senza_info(self):
        self.assertIsNone(APP.scarica_anteprima(None))
        self.assertIsNone(APP.scarica_anteprima({}))
        self.assertIsNone(APP.scarica_anteprima({"track": "senza URL"}))

    def test_anteprima_vera(self):
        try:
            info = APP.cerca_anteprima_itunes("50 Cent", "21 Questions")
        except Exception as e:                     # rete assente: il test si salta
            self.skipTest("iTunes non raggiungibile: %s" % e)
        if not info:
            self.skipTest("iTunes non ha dato l'anteprima (rete/rate limit)")
        self.assertTrue(info["preview_url"].startswith("http"))
        self.assertIn("21 Questions", info["track"])
        self.assertGreater(info["durata"], 10)     # è un'anteprima da ~30 s
        self.assertTrue(info["id"].isdigit())      # id iTunes, per rifare il check
        self.assertGreaterEqual(info["score"], 0.55)

    def test_brano_inesistente(self):
        try:
            info = APP.cerca_anteprima_itunes("50 Cent", "zzzqq brano che non esiste 98765")
        except Exception as e:
            self.skipTest("iTunes non raggiungibile: %s" % e)
        self.assertIsNone(info)

    def test_la_cartella_delle_anteprime_non_e_versionata(self):
        self.assertEqual(APP.ANTEPRIME_DIR, os.path.join(BASE_DIR, "anteprime"))
        self.assertIn("anteprime/", leggi(GITIGNORE_PATH))

    def test_artista_sbagliato_non_da_un_verdetto_sbagliato(self):
        # caso vero: cercando "Control" di Big Sean, iTunes propone "Control
        # (Kendrick Lamar Diss)" di The Rap Mafia. L'invariante è che QUALSIASI
        # candidato accettato abbia l'artista compatibile (o niente candidato).
        try:
            info = APP.cerca_anteprima_itunes("Big Sean", "Control")
        except Exception as e:
            self.skipTest("iTunes non raggiungibile: %s" % e)
        if info:
            self.assertTrue(APP.artista_compatibile("Big Sean", info["artist"]),
                            "candidato con artista incompatibile: %s" % info["artist"])


class TestArtistaCompatibile(unittest.TestCase):
    """La guardia sull'artista: senza, "Control" di Big Sean veniva confrontato
    con "Control (Kendrick Lamar Diss)" di The Rap Mafia (titolo quasi identico)."""

    def test_stesso_artista(self):
        self.assertTrue(APP.artista_compatibile("50 Cent", "50 Cent"))
        self.assertTrue(APP.artista_compatibile("50 Cent", "50 Cent feat. Nate Dogg"))
        self.assertTrue(APP.artista_compatibile("Eminem", "Eminem & Royce da 5'9\""))

    def test_crediti_multipli_della_libreria(self):
        self.assertTrue(APP.artista_compatibile("50 Cent / Nate Dogg", "50 Cent"))
        self.assertTrue(APP.artista_compatibile("Chris Webby / Jaye Michelle", "Chris Webby"))
        self.assertTrue(APP.artista_compatibile("Chris Webby / Jaye Michelle", "Jaye Michelle"))

    def test_artista_diverso(self):
        self.assertFalse(APP.artista_compatibile("Big Sean", "The Rap Mafia"))
        self.assertFalse(APP.artista_compatibile("50 Cent", "Chris Webby"))
        self.assertFalse(APP.artista_compatibile("Salmo", "Crystal Waters"))
        self.assertFalse(APP.artista_compatibile("", "50 Cent"))
        self.assertFalse(APP.artista_compatibile("50 Cent", ""))
        self.assertFalse(APP.artista_compatibile(None, None))

    def test_parole_intere_non_pezzi_di_parola(self):
        # `normalize` toglie anche gli spazi: senza il confronto per parole intere
        # "Ren" combaciava con "Rennes Choir"
        self.assertFalse(APP.artista_compatibile("Ren", "Rennes Choir"))
        self.assertFalse(APP.artista_compatibile("Nas", "Nashville Choir"))

    def test_nomi_molto_simili(self):
        self.assertTrue(APP.artista_compatibile("Merkules", "Merkules Music"))




