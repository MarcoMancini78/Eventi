"""M8: fingerprinting per famiglia di piattaforma, su HTML campione (15.1 regola 8).

I frammenti usati qui riproducono indizi reali verificati empiricamente
(2026-08-25) su siti comunali del perimetro: comune.cuneo.it (WordPress +
Yoast), comune.asti.it/comune.alessandria.it (Drupal 9), comune.alba.cn.it
(Bootstrap Italia / design system AGID).
"""
import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.fingerprint import (
    classifica_html,
    fingerprint_batch,
    url_prevedibile_comune,
    verifica_jsonld_batch,
    verifica_pa_design_system_batch,
)


def test_classifica_wordpress_da_wp_content():
    html = """
    <html><head>
    <!-- This site is optimized with the Yoast SEO Premium plugin v28.2 -->
    <link rel="stylesheet" href="/wp-content/themes/comune/style.css">
    </head><body>Comune di Prova</body></html>
    """
    fp = classifica_html(html)
    assert fp.piattaforma == "wordpress"
    assert fp.indizi


def test_classifica_drupal_da_meta_generator():
    html = """
    <html><head>
    <meta name="Generator" content="Drupal 9 (https://www.drupal.org)" />
    <meta name="MobileOptimized" content="width" />
    </head><body>Comune di Prova</body></html>
    """
    fp = classifica_html(html)
    assert fp.piattaforma == "drupal"


def test_classifica_pa_design_system_da_bootstrap_italia_e_agid():
    html = """
    <html><head>
    <link rel="stylesheet" href="/bootstrap-italia/dist/css/bootstrap-italia.min.css">
    <link rel="stylesheet" href="/css/agid.css?id=8e7e936f4bacc1509d74">
    </head><body>Comune di Prova</body></html>
    """
    fp = classifica_html(html)
    assert fp.piattaforma == "pa_design_system"


def test_classifica_sconosciuta_senza_indizi():
    html = "<html><head><title>Sito generico</title></head><body>Nessun indizio qui</body></html>"
    fp = classifica_html(html)
    assert fp.piattaforma == "sconosciuta"
    assert fp.indizi == []


def test_ordine_priorita_wordpress_prima_di_altri():
    """Un tema WordPress potrebbe includere per caso Bootstrap: wp-content
    resta il segnale più specifico e va riconosciuto per primo."""
    html = """
    <html><head>
    <link rel="stylesheet" href="/wp-content/themes/comune/bootstrap.min.css">
    </head><body>Comune di Prova</body></html>
    """
    fp = classifica_html(html)
    assert fp.piattaforma == "wordpress"


def test_url_prevedibile_comune_costruisce_pattern_noto():
    url = url_prevedibile_comune("Cuneo", "CN")
    assert url == "https://www.comune.cuneo.cn.it/"


def test_url_prevedibile_comune_normalizza_nome_con_spazi():
    url = url_prevedibile_comune("Isola d'Asti", "AT")
    assert url == "https://www.comune.isoladasti.at.it/"


class _RispostaFinta:
    def __init__(self, status_code, testo):
        self.status_code = status_code
        self.text = testo

    def raise_for_status(self):
        if self.status_code >= 400:
            import httpx
            raise httpx.HTTPStatusError("errore", request=None, response=self)


class _ClientFinto:
    def __init__(self, risposte_per_url):
        self._risposte = risposte_per_url

    def __enter__(self):
        return self

    def __exit__(self, *a):
        pass

    def get(self, url, headers=None):
        if url not in self._risposte:
            raise Exception(f"URL non atteso nel test: {url}")
        risultato = self._risposte[url]
        if isinstance(risultato, Exception):
            raise risultato
        return risultato


def test_fingerprint_batch_isola_i_fallimenti_per_comune():
    """15.1 regola 4: un sito irraggiungibile non deve interrompere il
    censimento degli altri comuni."""
    comuni = [
        {"istat": "1", "comune": "Comune WordPress", "url": "https://wp.example/"},
        {"istat": "2", "comune": "Comune Rotto", "url": "https://rotto.example/"},
        {"istat": "3", "comune": "Comune Drupal", "url": "https://drupal.example/"},
    ]
    risposte = {
        "https://wp.example/": _RispostaFinta(200, "<html><body>wp-content</body></html>"),
        "https://rotto.example/": _RispostaFinta(403, "vietato"),
        "https://drupal.example/": _RispostaFinta(
            200, '<meta name="Generator" content="Drupal 9 (https://www.drupal.org)" />'
        ),
    }

    with patch("httpx.Client", lambda **kw: _ClientFinto(risposte)):
        risultati = fingerprint_batch(comuni)

    assert len(risultati) == 3
    assert risultati[0].piattaforma == "wordpress"
    assert risultati[0].errore is None
    assert risultati[1].piattaforma is None
    assert risultati[1].errore is not None  # isolato, non ha fermato gli altri
    assert risultati[2].piattaforma == "drupal"


def test_verifica_jsonld_batch_rileva_blocco_ld_json():
    """L3 (2026-09-01): promuovere una fonte a T0_jsonld richiede aver
    verificato che la pagina reale contenga davvero un blocco
    <script type="application/ld+json">, non fidarsi del solo pattern URL
    (04.7: mai un valore indovinato)."""
    fonti = [
        {"source_id": "comune-con-jsonld", "endpoint": "https://a.example/eventi"},
        {"source_id": "comune-senza-jsonld", "endpoint": "https://b.example/eventi"},
        {"source_id": "comune-irraggiungibile", "endpoint": "https://c.example/eventi"},
    ]
    risposte = {
        "https://a.example/eventi": _RispostaFinta(
            200, '<script type="application/ld+json">{"@type":"Event"}</script>'
        ),
        "https://b.example/eventi": _RispostaFinta(200, "<html><body>Nessun evento</body></html>"),
        "https://c.example/eventi": _RispostaFinta(500, "errore server"),
    }

    with patch("httpx.Client", lambda **kw: _ClientFinto(risposte)):
        risultati = verifica_jsonld_batch(fonti)

    assert len(risultati) == 3
    assert risultati[0].ha_jsonld is True
    assert risultati[0].errore is None
    assert risultati[1].ha_jsonld is False
    assert risultati[1].errore is None
    assert risultati[2].ha_jsonld is False
    assert risultati[2].errore is not None  # isolato, non ha fermato gli altri


def test_verifica_pa_design_system_batch_rileva_markup_card_wrapper():
    """L3 (2026-09-01): promuovere una fonte a T0_pa_design_system
    richiede il markup .card-wrapper nella pagina reale, non solo il
    pattern URL '.../Eventi' (04.7)."""
    fonti = [
        {"source_id": "comune-con-markup", "endpoint": "https://a.example/Eventi"},
        {"source_id": "comune-senza-markup", "endpoint": "https://b.example/Eventi"},
        {"source_id": "comune-irraggiungibile", "endpoint": "https://c.example/Eventi"},
    ]
    risposte = {
        "https://a.example/Eventi": _RispostaFinta(200, '<div class="card-wrapper"><h3>x</h3></div>'),
        "https://b.example/Eventi": _RispostaFinta(200, "<html><body>Sito diverso</body></html>"),
        "https://c.example/Eventi": _RispostaFinta(500, "errore server"),
    }

    with patch("httpx.Client", lambda **kw: _ClientFinto(risposte)):
        risultati = verifica_pa_design_system_batch(fonti)

    assert len(risultati) == 3
    assert risultati[0].ha_markup is True
    assert risultati[0].errore is None
    assert risultati[1].ha_markup is False
    assert risultati[1].errore is None
    assert risultati[2].ha_markup is False
    assert risultati[2].errore is not None  # isolato, non ha fermato gli altri
