"""M8/12.8 — Discovery: il prober (04.2).

Trova, per una fonte, la vera pagina eventi/calendario invece di fermarsi
alla sola homepage, e cerca endpoint strutturati (iCal/RSS/JSON-LD) su
quella pagina. Eseguito una volta per fonte (e su richiesta, es.
mensilmente), non ad ogni run — il risultato va scritto in sources.endpoint.

Scoperta empirica (2026-08-26, campione di comuni reali con famiglie CMS
diverse — WordPress, Drupal, PA design system): tutti espongono un link
testuale "Eventi" in homepage, ma con path completamente diverso ogni
volta (/vivere/eventi/, /vivere-comune/eventi, ecc.) — troppo vario per
indovinare pattern URL fissi (i path comuni citati in 04.2, come /eventi,
hanno prodotto 404 o timeout su Asti). Strategia più economica: cercare
quel link nella homepage già scaricata (zero richieste HTTP aggiuntive
per il rilevamento in sé), seguirlo, e solo lì cercare feed strutturati.
La sitemap resta un fallback più costoso se nessun link testuale è trovato.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from urllib.parse import urljoin

import httpx

_TIMEOUT_SECONDI = 15
_USER_AGENT_BROWSER = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)

_TESTI_LINK_EVENTI = re.compile(
    r"^(eventi|manifestazioni|agenda|calendario|cartellone|spettacoli|"
    r"events|what'?s on)$",
    re.IGNORECASE,
)
_PATTERN_LINK_HREF_TESTO = re.compile(r'<a[^>]+href=["\']([^"\']+)["\'][^>]*>([^<]*)</a>', re.IGNORECASE)
_PATTERN_LINK_CALENDAR = re.compile(
    r'<link[^>]+type=["\']text/calendar["\'][^>]+href=["\']([^"\']+)["\']', re.IGNORECASE
)
_PATTERN_LINK_RSS = re.compile(
    r'<link[^>]+rel=["\']alternate["\'][^>]+type=["\']application/(?:rss|atom)\+xml["\'][^>]+href=["\']([^"\']+)["\']',
    re.IGNORECASE,
)
_PATTERN_JSONLD_EVENT = re.compile(
    r'<script[^>]+type=["\']application/ld\+json["\'][^>]*>(.*?)</script>', re.IGNORECASE | re.DOTALL
)
_PATTERN_SITEMAP_URL_EVENTI = re.compile(
    r"<loc>([^<]*(?:/eventi/|/manifestazion|/spettacol|/cartellone|/agenda)[^<]*)</loc>", re.IGNORECASE
)


@dataclass
class RisultatoProbing:
    pagina_eventi: str | None = None  # URL della pagina eventi trovata (o homepage se nessuna trovata)
    endpoint_strutturato: str | None = None  # URL di un feed iCal/RSS trovato sulla pagina eventi
    tipo_endpoint: str | None = None  # 'ical' | 'rss' | 'jsonld' | None
    fonte_scoperta: str = "homepage"  # 'homepage' | 'sitemap' | 'nessuna'
    note: list[str] = field(default_factory=list)


def _trova_link_pagina_eventi(html: str, url_base: str) -> str | None:
    """Cerca un <a> il cui testo visibile corrisponde a 'Eventi'/'Agenda'/ecc.
    (case-insensitive, match esatto sul testo ripulito, non una sottostringa
    — evita falsi positivi su frasi come 'Tutti gli eventi del 2025')."""
    for href, testo in _PATTERN_LINK_HREF_TESTO.findall(html):
        if _TESTI_LINK_EVENTI.match(testo.strip()):
            return _url_assoluto(href, url_base)
    return None


def _url_assoluto(href: str, url_base: str) -> str:
    """Bug reale osservato (2026-08-26, comune.calosso.at.it): un vecchio
    sito ASP.NET WebForms usa href="Eventi" (path relativo senza slash
    iniziale, risolto dal browser rispetto alla cartella corrente, non
    alla radice del dominio) — la risoluzione manuale precedente gestiva
    solo http(s):// e '/'-iniziale, producendo un URL malformato
    ('/Eventi' invece di 'https://dominio/Eventi'). urljoin gestisce
    correttamente tutte le varianti di URL relativo secondo lo standard."""
    return urljoin(url_base, href)


def _cerca_endpoint_strutturato(html: str, url_base: str) -> tuple[str | None, str | None]:
    """Cerca, in ordine di affidabilità (04.2): calendar link, RSS/Atom,
    JSON-LD con @type Event. Ritorna (url_endpoint, tipo) o (None, None)."""
    m = _PATTERN_LINK_CALENDAR.search(html)
    if m:
        return _url_assoluto(m.group(1), url_base), "ical"

    m = _PATTERN_LINK_RSS.search(html)
    if m:
        return _url_assoluto(m.group(1), url_base), "rss"

    for blocco in _PATTERN_JSONLD_EVENT.findall(html):
        if '"@type"' in blocco and re.search(r'"@type"\s*:\s*"Event"', blocco, re.IGNORECASE):
            return url_base, "jsonld"  # il JSON-LD è incorporato nella pagina stessa, non un endpoint separato

    return None, None


def _cerca_pagina_eventi_da_sitemap(client: httpx.Client, url_base: str) -> str | None:
    """Fallback più costoso (04.2 punto 4): scarica solo la prima pagina
    della sitemap (o l'indice, se paginata) e cerca un URL con pattern
    eventi. Non segue tutte le pagine di un sitemap index — costo
    accettabile per un singolo tentativo, non per centinaia."""
    radice = re.match(r"(https?://[^/]+)", url_base)
    if not radice:
        return None
    try:
        risposta = client.get(f"{radice.group(1)}/sitemap.xml", headers={"User-Agent": _USER_AGENT_BROWSER})
        risposta.raise_for_status()
    except Exception:
        return None

    m = _PATTERN_SITEMAP_URL_EVENTI.search(risposta.text)
    if m:
        return m.group(1)
    return None


def prova_fonte(url_base: str) -> RisultatoProbing:
    """Discovery per una singola fonte. Nessun try/except interno oltre a
    quelli già previsti sui singoli tentativi opzionali (sitemap): un
    fallimento sulla richiesta principale deve propagarsi, l'isolamento
    per-fonte è responsabilità del chiamante (15.1 regola 4), come negli
    adapter e in fingerprint_batch."""
    risultato = RisultatoProbing()

    with httpx.Client(timeout=_TIMEOUT_SECONDI, follow_redirects=True) as client:
        risposta = client.get(url_base, headers={"User-Agent": _USER_AGENT_BROWSER})
        risposta.raise_for_status()
        html_home = risposta.text

        pagina_eventi = _trova_link_pagina_eventi(html_home, url_base)
        html_da_analizzare = html_home
        url_da_analizzare = url_base

        if pagina_eventi:
            risultato.pagina_eventi = pagina_eventi
            risultato.fonte_scoperta = "homepage"
            try:
                risposta_eventi = client.get(pagina_eventi, headers={"User-Agent": _USER_AGENT_BROWSER})
                risposta_eventi.raise_for_status()
                html_da_analizzare = risposta_eventi.text
                url_da_analizzare = pagina_eventi
            except Exception as exc:
                risultato.note.append(f"link 'Eventi' trovato ma non raggiungibile: {exc}")
        else:
            pagina_sitemap = _cerca_pagina_eventi_da_sitemap(client, url_base)
            if pagina_sitemap:
                risultato.pagina_eventi = pagina_sitemap
                risultato.fonte_scoperta = "sitemap"
                try:
                    risposta_eventi = client.get(pagina_sitemap, headers={"User-Agent": _USER_AGENT_BROWSER})
                    risposta_eventi.raise_for_status()
                    html_da_analizzare = risposta_eventi.text
                    url_da_analizzare = pagina_sitemap
                except Exception as exc:
                    risultato.note.append(f"URL da sitemap trovato ma non raggiungibile: {exc}")
            else:
                risultato.fonte_scoperta = "nessuna"
                risultato.pagina_eventi = url_base  # nessun miglioramento: resta la homepage

        endpoint, tipo = _cerca_endpoint_strutturato(html_da_analizzare, url_da_analizzare)
        risultato.endpoint_strutturato = endpoint
        risultato.tipo_endpoint = tipo

    return risultato
