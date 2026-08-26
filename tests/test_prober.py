"""M8/12.8: discovery (prober, 04.2) su HTML campione, nessuna rete reale.

I frammenti riproducono casi reali verificati empiricamente (2026-08-26)
su comuni del perimetro con famiglie CMS diverse: comune.castiglionetinella.cn.it
(WordPress, link "Eventi" con href assoluto relativo-radice), comune.asti.it
(Drupal, path diverso), comune.calosso.at.it (ASP.NET WebForms, href
relativo SENZA slash iniziale — il bug reale che ha portato a sostituire
la risoluzione URL manuale con urllib.parse.urljoin).
"""
import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.prober import (
    _cerca_endpoint_strutturato,
    _trova_link_pagina_eventi,
    _url_assoluto,
    prova_fonte,
)


def test_trova_link_eventi_con_href_radice_relativo():
    html = '<a href="/vivere/eventi/">Eventi</a>'
    assert _trova_link_pagina_eventi(html, "https://comune-prova.it/") == "https://comune-prova.it/vivere/eventi/"


def test_trova_link_eventi_ignora_falsi_positivi_con_testo_diverso():
    html = '<a href="/2025/eventi-passati">Tutti gli eventi del 2025</a>'
    assert _trova_link_pagina_eventi(html, "https://comune-prova.it/") is None


def test_trova_link_eventi_case_insensitive_e_sinonimi():
    for testo in ["Eventi", "EVENTI", "Manifestazioni", "Agenda", "Calendario"]:
        html = f'<a href="/pagina">{testo}</a>'
        assert _trova_link_pagina_eventi(html, "https://comune-prova.it/") == "https://comune-prova.it/pagina"


def test_url_assoluto_gestisce_href_relativo_senza_slash():
    """Bug reale (comune.calosso.at.it): href="Eventi" senza slash iniziale
    va risolto rispetto alla cartella corrente, non concatenato alla radice
    del dominio (produrrebbe '/Eventi' invece di 'https://dominio/Eventi')."""
    assert _url_assoluto("Eventi", "https://comune-prova.it/") == "https://comune-prova.it/Eventi"


def test_url_assoluto_gestisce_href_assoluto():
    url = "https://altrosito.it/eventi"
    assert _url_assoluto(url, "https://comune-prova.it/") == url


def test_cerca_endpoint_trova_calendar_link():
    html = '<link type="text/calendar" href="/eventi.ics">'
    endpoint, tipo = _cerca_endpoint_strutturato(html, "https://comune-prova.it/eventi")
    assert endpoint == "https://comune-prova.it/eventi.ics"
    assert tipo == "ical"


def test_cerca_endpoint_trova_rss_alternate():
    html = '<link rel="alternate" type="application/rss+xml" href="/eventi/feed">'
    endpoint, tipo = _cerca_endpoint_strutturato(html, "https://comune-prova.it/eventi")
    assert endpoint == "https://comune-prova.it/eventi/feed"
    assert tipo == "rss"


def test_cerca_endpoint_trova_jsonld_event():
    html = '<script type="application/ld+json">{"@type": "Event", "name": "Sagra"}</script>'
    endpoint, tipo = _cerca_endpoint_strutturato(html, "https://comune-prova.it/eventi")
    assert tipo == "jsonld"
    assert endpoint == "https://comune-prova.it/eventi"


def test_cerca_endpoint_nessuno_trovato():
    html = "<p>Nessun feed qui</p>"
    endpoint, tipo = _cerca_endpoint_strutturato(html, "https://comune-prova.it/eventi")
    assert endpoint is None
    assert tipo is None


class _RispostaFinta:
    def __init__(self, status_code, testo, url=None):
        self.status_code = status_code
        self.text = testo
        self.url = url

    def raise_for_status(self):
        if self.status_code >= 400:
            raise Exception(f"status {self.status_code}")


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


def test_prova_fonte_segue_il_link_eventi_e_trova_endpoint():
    home = '<html><body><a href="/vivere/eventi/">Eventi</a></body></html>'
    pagina_eventi = '<link rel="alternate" type="application/rss+xml" href="/vivere/eventi/feed">'
    risposte = {
        "https://comune-prova.it/": _RispostaFinta(200, home),
        "https://comune-prova.it/vivere/eventi/": _RispostaFinta(200, pagina_eventi),
    }
    with patch("httpx.Client", lambda **kw: _ClientFinto(risposte)):
        r = prova_fonte("https://comune-prova.it/")

    assert r.pagina_eventi == "https://comune-prova.it/vivere/eventi/"
    assert r.fonte_scoperta == "homepage"
    assert r.tipo_endpoint == "rss"
    assert r.endpoint_strutturato == "https://comune-prova.it/vivere/eventi/feed"


def test_prova_fonte_usa_sitemap_se_nessun_link_in_homepage():
    home = "<html><body><p>Nessun link eventi qui</p></body></html>"
    sitemap = "<urlset><url><loc>https://comune-prova.it/manifestazioni/sagra</loc></url></urlset>"
    pagina_eventi = "<p>Sagra del paese</p>"
    risposte = {
        "https://comune-prova.it/": _RispostaFinta(200, home),
        "https://comune-prova.it/sitemap.xml": _RispostaFinta(200, sitemap),
        "https://comune-prova.it/manifestazioni/sagra": _RispostaFinta(200, pagina_eventi),
    }
    with patch("httpx.Client", lambda **kw: _ClientFinto(risposte)):
        r = prova_fonte("https://comune-prova.it/")

    assert r.pagina_eventi == "https://comune-prova.it/manifestazioni/sagra"
    assert r.fonte_scoperta == "sitemap"


def test_prova_fonte_nessun_miglioramento_resta_su_homepage():
    home = "<html><body><p>Nessun link, nessuna sitemap</p></body></html>"
    risposte = {
        "https://comune-prova.it/": _RispostaFinta(200, home),
        "https://comune-prova.it/sitemap.xml": Exception("404"),
    }
    with patch("httpx.Client", lambda **kw: _ClientFinto(risposte)):
        r = prova_fonte("https://comune-prova.it/")

    assert r.fonte_scoperta == "nessuna"
    assert r.pagina_eventi == "https://comune-prova.it/"
