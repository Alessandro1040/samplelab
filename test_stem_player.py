"""Test del PLAYER DI OGNI STEM nella pagina `/scheda` (19/09/2026).

Richiesta di Alessandro: «quando l'utente carica dal computer gli stems di una
canzone oppure gli stems vengono estratti, per ognuno degli stems deve esserci un
player, il player classico stile fl studio che è già implementato in altre parti
dell'app però SENZA il trim giallo ovviamente».

Com'è fatto:
1. il sampler (il player stile FL Studio: onda, griglia del BPM, metronomo, TAP,
   trim…) vive DENTRO `index (2).html`, in una `<textarea id="audio-editor-src">`:
   la pagina principale lo monta in un iframe `blob:`. La rotta nuova
   **`GET /sampler`** serve QUELLA textarea come pagina — un posto solo da
   aggiornare — così anche `/scheda` lo può montare in un iframe;
2. nel protocollo dei messaggi c'è l'opzione nuova **`trim: false`**: il sampler
   si apre col **trim giallo spento** e con la selezione = **tutto il file**
   (senza, il play si fermerebbe dopo i 30 s di default). Uno stem non ha un
   intervallo da ritagliare: si ascolta intero;
3. `/scheda` monta un player per OGNI stem (`<iframe loading="lazy" src="/sampler">`,
   un messaggio `load` per ciascuno con l'URL della traccia e il BPM della
   canzone) e il mixer «▶ Suona tutti insieme» resta sugli `<audio>` nascosti: un
   solo audio per volta, nei due versi (il sampler avvisa quando parte).

Questo file prova:
1. `TestRottaSampler` — il documento di `/sampler` è la textarea di
   `index (2).html` (parità carattere per carattere), la rotta risponde 200, il
   file si legge una volta sola (cache sull'mtime) e se la textarea sparisse la
   rotta non serve una pagina vuota;
2. `TestCablaggioScheda` — la pagina `/scheda`: un iframe per riga, il messaggio
   `load` con `trim:false`, il BPM e l'etichetta, il mixer intatto, l'handler su
   `window` e il «un solo audio per volta» nei due versi;
3. `TestAppViva` — l'app attiva: `/sampler` 200 col sampler dentro, `/scheda` 200
   con l'iframe del player.

Esecuzione (dalla cartella di SampleLab):
    python3 -m unittest -v test_stem_player
"""
import importlib.util
import os
import re
import shutil
import tempfile
import unittest
import urllib.error
import urllib.request

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
APP_PATH = os.path.join(BASE_DIR, "app (2).py")
INDEX_PATH = os.path.join(BASE_DIR, "index (2).html")
SCHEDA_PATH = os.path.join(BASE_DIR, "scheda.html")
SAMPLELAB_URL = os.environ.get("SAMPLELAB_URL", "http://localhost:5070")


def load_app():
    """Carica il modulo dell'app dal file (il nome con spazio non conta)."""
    spec = importlib.util.spec_from_file_location("samplelab_app2_stem_player", APP_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


APP = load_app()


def leggi(percorso):
    with open(percorso, encoding="utf-8") as fh:
        return fh.read()


def estrai_funzione(src, nome):
    """Il testo della funzione `nome` (graffe contate, come in test_sampler_trim)."""
    m = re.search(r"(?:async\s+)?function\s+" + re.escape(nome) + r"\s*\(", src)
    if not m:
        raise AssertionError("funzione %s assente" % nome)
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


def app_is_up(url):
    try:
        urllib.request.urlopen(url + "/db/stats", timeout=3)
        return True
    except Exception:
        return False


def http(path):
    """GET sull'app VIVA: (stato, corpo)."""
    try:
        with urllib.request.urlopen(SAMPLELAB_URL + path, timeout=20) as r:
            return r.status, r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "replace")


class TestRottaSampler(unittest.TestCase):
    """`GET /sampler`: il sampler servito come pagina, dalla textarea di index."""

    def setUp(self):
        self.client = APP.app.test_client()

    def test_il_documento_e_la_textarea_di_index(self):
        # La sorgente è UNA: quello che serve la rotta è esattamente il testo della
        # textarea (nessuna copia da tenere allineata a mano).
        index = leggi(INDEX_PATH)
        m = re.search(r'<textarea[^>]*id="audio-editor-src"[^>]*>(.*?)</textarea>',
                      index, re.S)
        self.assertIsNotNone(m, "la textarea del sampler non è più in index (2).html")
        atteso = m.group(1).strip()
        self.assertTrue(atteso.startswith("<!DOCTYPE html>"))
        self.assertEqual(APP.sampler_html(), atteso)

    def test_la_rotta_serve_il_sampler(self):
        res = self.client.get("/sampler")
        self.assertEqual(res.status_code, 200)
        corpo = res.get_data(as_text=True)
        self.assertIn("<title>SampleLab (2) – Player standalone</title>", corpo)
        self.assertIn('id="trim-btn-main"', corpo)      # è il sampler, non una pagina qualsiasi
        self.assertIn("function initPlayer(", corpo)
        self.assertIn("function intervalloTrimIniziale(", corpo)
        self.assertTrue(corpo.lstrip().startswith("<!DOCTYPE html>"),
                        "il documento del sampler, non l'involucro di index (2).html")

    def test_il_file_si_legge_una_volta_sola(self):
        # Un iframe per stem: rileggere ogni volta `index (2).html` (388 KB) sarebbe
        # lavoro sprecato, quindi la cache tiene il testo finché l'mtime non cambia.
        APP._SAMPLER_CACHE.clear()
        primo = APP.sampler_html()
        chiave = os.path.join(BASE_DIR, "index (2).html")
        self.assertIn(chiave, APP._SAMPLER_CACHE)
        self.assertEqual(APP._SAMPLER_CACHE[chiave][1], primo)
        self.assertIs(APP.sampler_html(), primo)

    def test_senza_la_textarea_non_si_serve_una_pagina_vuota(self):
        # Se un giorno il sampler sparisse da `index (2).html`, meglio un errore
        # chiaro (500 col motivo) che un iframe bianco senza spiegazione.
        tmp = tempfile.mkdtemp(prefix="sampler_mancante_")
        base_originale = APP.BASE_DIR
        try:
            with open(os.path.join(tmp, "index (2).html"), "w", encoding="utf-8") as fh:
                fh.write("<html><body>niente sampler qui</body></html>")
            APP.BASE_DIR = tmp
            APP._SAMPLER_CACHE.clear()
            with self.assertRaises(RuntimeError):
                APP.sampler_html()
            res = self.client.get("/sampler")
            self.assertEqual(res.status_code, 500)
            self.assertIn("sampler non disponibile", res.get_data(as_text=True))
        finally:
            APP.BASE_DIR = base_originale
            APP._SAMPLER_CACHE.clear()
            shutil.rmtree(tmp, ignore_errors=True)


class TestCablaggioScheda(unittest.TestCase):
    """`/scheda`: un player per ogni stem, senza il trim giallo."""

    @classmethod
    def setUpClass(cls):
        cls.pagina = leggi(SCHEDA_PATH)

    def test_un_player_per_ogni_riga(self):
        # L'iframe sta DENTRO il `map` delle righe: una riga = un player.
        corpo = self.pagina.split("body.innerHTML=stemRows.map", 1)[1].split(".join('')", 1)[0]
        self.assertIn('<div class="stem-player">', corpo)
        self.assertIn('src="/sampler"', corpo)
        self.assertIn('loading="lazy"', corpo,
                      "i player si aprono scorrendo, non tutti insieme")
        self.assertIn('onload="stemPlayerMonto(this)"', corpo)
        self.assertIn('data-url="${esc(r.url)}"', corpo)
        self.assertIn('data-bpm="${Number(s.bpm)||0}"', corpo)
        self.assertIn('data-etichetta="${esc(r.etichetta)}${s.title?', corpo)
        # Il player si monta solo per le tracce che ci sono davvero.
        self.assertIn("${r.esiste?`<audio", corpo)

    def test_il_carico_spegne_il_trim(self):
        fn = estrai_funzione(self.pagina, "stemPlayerMonto")
        self.assertIn("action:'load'", fn)
        self.assertIn("trim:false", fn, "senza il trim giallo: uno stem si ascolta intero")
        self.assertIn("bpm:Number(fr.dataset.bpm)||0", fn)
        self.assertIn("origin:window.location.origin", fn)
        self.assertIn("if(!fr || fr.dataset.montato) return;", fn,
                      "ogni iframe si monta una volta sola")

    def test_solo_un_audio_per_volta(self):
        # Il sampler avvisa da sé quando comincia a suonare: da lì si ferma il mixer.
        self.assertIn("function pausaSamplerStem(){", self.pagina)
        self.assertIn("function pausaMixer(){", self.pagina)
        self.assertIn("if(e.data && e.data.action==='audioplaying') pausaMixer();", self.pagina)
        self.assertIn("postMessage({action:'pauseall'}", self.pagina)
        # ...e viceversa: far partire il mixer (o una sola traccia) ferma i player
        self.assertIn("pausaSamplerStem();      // e i player degli stem si fermano", self.pagina)
        self.assertIn("pausaSamplerStem();      // il mixer parte", self.pagina)

    def test_il_ridisegno_automatico_non_taglia_la_musica(self):
        # La scheda si ridisegna quando il database cambia: se lo facesse mentre un
        # player suona, l'iframe verrebbe buttato giù e la traccia si
        # interromperebbe a metà. Vale anche per i player del sampler, non solo
        # per gli <audio> del mixer.
        self.assertIn("function stemSamplerInRiproduzione(){", self.pagina)
        self.assertIn("fr.contentWindow&&fr.contentWindow.players&&fr.contentWindow.players.main",
                      self.pagina)
        self.assertIn("if(stemInRiproduzione().length||stemSamplerInRiproduzione()){ attesaRicaricamento=true; return; }",
                      self.pagina)

    def test_il_mixer_resta_sugli_audio_nascosti(self):
        # «▶ Suona tutti insieme» lavora sugli `<audio>` sincronizzati: il player
        # del sampler è IN PIÙ (per guardare e ascoltare una traccia sola), non al
        # posto loro.
        self.assertIn('id="stem-audio-${i}"', self.pagina)
        self.assertIn("function mixerToggle(){", self.pagina)
        self.assertIn("function stemPlay(i){", self.pagina)
        self.assertIn("function audioDi(i){", self.pagina)

    def test_l_handler_e_su_window(self):
        # `onload="stemPlayerMonto(this)"` è nell'HTML: dentro la funzione anonima
        # non sarebbe raggiungibile (stesso motivo degli altri handler).
        self.assertIn("Object.assign(window,{", self.pagina)
        self.assertIn("stemPlayerMonto,", self.pagina)

    def test_il_player_e_raccontato_nella_card(self):
        self.assertIn("Ogni traccia ha il suo player", self.pagina)
        self.assertIn("senza il trim giallo", self.pagina)
        self.assertIn(".stem-player iframe{", self.pagina)


@unittest.skipUnless(app_is_up(SAMPLELAB_URL), "app non attiva su " + SAMPLELAB_URL)
class TestAppViva(unittest.TestCase):
    """Sola lettura sull'app attiva."""

    def test_la_pagina_del_sampler(self):
        stato, corpo = http("/sampler")
        self.assertEqual(stato, 200)
        self.assertIn('id="trim-btn-main"', corpo)
        self.assertIn("Player standalone", corpo)

    def test_la_scheda_monta_i_player(self):
        stato, corpo = http("/scheda")
        self.assertEqual(stato, 200)
        self.assertIn('src="/sampler"', corpo)
        self.assertIn("stemPlayerMonto", corpo)
