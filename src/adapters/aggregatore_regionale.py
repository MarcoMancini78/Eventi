"""Adattatore per aggregatori regionali con contenuto renderizzato via
JavaScript (M3, 2026-08-28): visitlmr.it e simili.

Scoperta dal collaudo dal vivo (Playwright reale, non solo fetch statico):
- Il fetch statico (httpx) trova 0 eventi — coerente con la verifica di
  agosto già fatta (piemonteitalia.eu/visitlmr.it "T1, non T0").
- Con rendering reale, le pagine di DETTAGLIO evento espongono un blocco
  JSON-LD @type=Event completo (name, startDate, endDate, location,
  description) — un vero T0, semplicemente iniettato via JS invece che
  presente nell'HTML statico. Il fetch remoto di agosto (via markdown, non
  view-source reale) non l'aveva visto perché non eseguiva JavaScript.

piemonteitalia.eu è stato escluso (non solo "T1"): il sito blocca
esplicitamente il traffico Playwright con una pagina "problema di
sicurezza" (probabile fingerprinting anti-bot) — non un semplice caso di
"serve un browser", richiederebbe eludere una protezione attiva, fuori
scope qui.

Ambito: 2 livelli, mai un adattatore stateless puro come gli altri T0/T1
(qui serve un browser reale, quindi il costo per richiesta è alto — va
usato con parsimonia, coerente con 04.3 sul Playwright headless riservato
a polling_diretto).
    1. pagina lista (endpoint della fonte): raccoglie i link /it/eventi/...
    2. per ciascun link, apre il dettaglio e ne estrae il JSON-LD già
       collaudato in adapters/jsonld.py (parse_jsonld, riusata qui senza
       duplicare la logica di parsing).
"""
from __future__ import annotations

import re

from .base import Adapter, Artefatto
from .jsonld import parse_jsonld

_TIMEOUT_NAVIGAZIONE_MS = 20000
_ATTESA_RENDER_MS = 2000
_MAX_EVENTI_PER_GIRO = 20  # tetto per fonte per run, coerente con 04.3
_PATTERN_LINK_EVENTO = re.compile(r"/it/eventi/", re.IGNORECASE)
_SELETTORI_ACCETTA_COOKIE = ["text=Accetta tutti", "text=Accept all"]


def _chiudi_banner_cookie_se_presente(pagina) -> None:
    for selettore in _SELETTORI_ACCETTA_COOKIE:
        try:
            pagina.click(selettore, timeout=3000)
            pagina.wait_for_timeout(800)
            return
        except Exception:
            continue


def _raccogli_link_eventi(pagina, url_base: str) -> list[str]:
    from urllib.parse import urljoin

    href_grezzi = pagina.evaluate(
        """
        () => Array.from(document.querySelectorAll('a[href]'))
            .map(a => a.getAttribute('href'))
        """
    )
    assoluti = {urljoin(url_base, h) for h in href_grezzi if h and _PATTERN_LINK_EVENTO.search(h)}
    return sorted(assoluti)


class AggregatoreRegionalePlaywrightAdapter(Adapter):
    """T0 in due passaggi (lista -> dettagli con JSON-LD), tramite browser
    reale headless. Isolamento totale (15.1 regola 4): un dettaglio che
    fallisce non deve far perdere gli altri già raccolti."""

    def fetch(self, fonte: dict) -> list[Artefatto]:
        from playwright.sync_api import sync_playwright

        endpoint = fonte["endpoint"]
        source_id = fonte["source_id"]
        artefatti: list[Artefatto] = []

        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            try:
                pagina = browser.new_page()
                pagina.goto(endpoint, timeout=_TIMEOUT_NAVIGAZIONE_MS, wait_until="domcontentloaded")
                pagina.wait_for_timeout(_ATTESA_RENDER_MS)
                _chiudi_banner_cookie_se_presente(pagina)

                link_eventi = _raccogli_link_eventi(pagina, endpoint)[:_MAX_EVENTI_PER_GIRO]

                for link in link_eventi:
                    try:
                        pagina.goto(link, timeout=_TIMEOUT_NAVIGAZIONE_MS, wait_until="domcontentloaded")
                        pagina.wait_for_timeout(_ATTESA_RENDER_MS)
                        html = pagina.content()
                        artefatti.extend(parse_jsonld(html, source_id, link))
                    except Exception:
                        # 15.1 regola 4: un dettaglio irraggiungibile non
                        # deve fermare la raccolta degli altri.
                        continue
            finally:
                browser.close()

        return artefatti
