"""Adattatore HTML generico (04.3): T1, nessun selettore CSS per sito.

Scarica la pagina indice, ripulisce il testo con trafilatura, e produce un
artefatto grezzo se contiene abbastanza segnali di data da giustificare la
chiamata all'estrattore. Se una fonte richiede selettori custom per essere
utile, è il segnale che non conviene scriverne uno (04.3).

Link di dettaglio (2026-09-01, trovato con un caso reale — Attraverso
Festival: la pagina "programma" è solo un indice con titolo+prezzo per
evento, le date vivono unicamente nelle 47 pagine di dettaglio linkate.
`_MAX_LINK_DETTAGLIO` era già previsto nel codice ma mai implementato).
Quando l'indice stesso non supera `contiene_pattern_di_data`, si cerca un
prefisso di path dominante tra i link interni (es. tutti `/eventi/...`):
se un solo prefisso ricorre molto più degli altri (`_SOGLIA_LINK_DOMINANTE`
occorrenze, almeno il doppio del secondo più frequente — su un sito reale
i link di navigazione ricorrono 2 volte, una nell'header e una nel footer,
mentre un vero elenco di elementi ne produce decine), è il segnale di un
elenco di dettagli, non di menu/categoria/pagine correlate. Si seguono al
più `_MAX_LINK_DETTAGLIO` di quei link e si applica lo stesso controllo a
ciascuna pagina raggiunta."""
from __future__ import annotations

import hashlib
import re
from collections import Counter
from urllib.parse import urlparse

import httpx
import lxml.html
import trafilatura

from .base import Adapter, Artefatto

_TIMEOUT_SECONDI = 15
_MAX_LINK_DETTAGLIO = 10  # limite rigido per fonte per run (04.3)
_SOGLIA_LINK_DOMINANTE = 5

_PATTERN_DATA = [
    re.compile(r"\b\d{1,2}[/\-.]\d{1,2}(?:[/\-.]\d{2,4})?\b"),  # 12/09, 12-09-2026
    re.compile(
        r"\b\d{1,2}\s+(gennaio|febbraio|marzo|aprile|maggio|giugno|luglio|agosto|"
        r"settembre|ottobre|novembre|dicembre)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(luned[iì]|marted[iì]|mercoled[iì]|gioved[iì]|venerd[iì]|sabato|domenica)\b",
        re.IGNORECASE,
    ),
]


def contiene_pattern_di_data(testo: str, minimo: int = 2) -> bool:
    """04.3: 'se il testo ripulito contiene >= 2 pattern di data -> passa all'estrattore'."""
    trovati = sum(1 for pattern in _PATTERN_DATA if pattern.search(testo))
    return trovati >= minimo


def estrai_testo_pulito(html: str) -> str | None:
    """trafilatura rimuove menu, footer, cookie banner (04.3)."""
    return trafilatura.extract(html, favor_recall=True)


def parse_html(html: str, source_id: str, fetch_url: str) -> list[Artefatto]:
    testo = estrai_testo_pulito(html)
    if not testo or not contiene_pattern_di_data(testo):
        return []

    return [
        Artefatto(
            source_id=source_id,
            url=fetch_url,
            kind="html",
            text=testo,
            raw_hash=hashlib.sha1(testo.encode("utf-8")).hexdigest(),
        )
    ]


def trova_link_dettaglio_dominanti(html: str, pagina_url: str) -> list[str]:
    """Cerca link interni con un prefisso di path dominante (vedi docstring
    del modulo): candidato a essere l'indice di un elenco di dettagli.
    Esclude link alla pagina stessa, ancore (#...), query string, e feed
    tecnici (/comments/feed/, /wp-json/...) — mai considerati un 'elenco'."""
    try:
        albero = lxml.html.fromstring(html)
        albero.make_links_absolute(pagina_url)
    except Exception:
        return []

    base = urlparse(pagina_url)
    path_pagina = base.path

    link_per_prefisso: dict[str, list[str]] = {}
    for _el, attr, link, _pos in albero.iterlinks():
        if attr != "href":
            continue
        p = urlparse(link)
        if p.netloc != base.netloc or p.fragment or p.query:
            continue
        if p.path in ("/", path_pagina) or "/feed" in p.path or p.path.startswith("/wp-json"):
            continue
        segmenti = p.path.strip("/").split("/")
        if not segmenti or not segmenti[0]:
            continue
        prefisso = segmenti[0]
        link_per_prefisso.setdefault(prefisso, []).append(link)

    if not link_per_prefisso:
        return []

    conteggi = Counter({k: len(set(v)) for k, v in link_per_prefisso.items()})
    (prefisso_top, n_top), *resto = conteggi.most_common()
    n_secondo = resto[0][1] if resto else 0
    if n_top < _SOGLIA_LINK_DOMINANTE or n_top < 2 * max(n_secondo, 1):
        return []

    return sorted(set(link_per_prefisso[prefisso_top]))[:_MAX_LINK_DETTAGLIO]


class HtmlAdapter(Adapter):
    """Adattatore generico: pagina indice, con fallback sui link di
    dettaglio se l'indice stesso non ha abbastanza segnali di data (vedi
    docstring del modulo — 2026-09-01).

    Il rendering JavaScript (Playwright) va aggiunto come flag per-fonte solo
    se il testo pulito risulta vuoto e la fonte è in polling_diretto (04.3):
    non è compito di questo adattatore di base.
    """

    def fetch(self, fonte: dict) -> list[Artefatto]:
        endpoint = fonte["endpoint"]
        user_agent = fonte.get("user_agent", "EventiLocaliBot/1.0")
        with httpx.Client(timeout=_TIMEOUT_SECONDI, follow_redirects=True) as client:
            risposta = client.get(endpoint, headers={"User-Agent": user_agent})
            risposta.raise_for_status()
            artefatti = parse_html(risposta.text, fonte["source_id"], endpoint)
            if artefatti:
                return artefatti

            link_dettaglio = trova_link_dettaglio_dominanti(risposta.text, endpoint)
            trovati: list[Artefatto] = []
            for link in link_dettaglio:
                try:
                    r_dettaglio = client.get(link, headers={"User-Agent": user_agent})
                    r_dettaglio.raise_for_status()
                except httpx.HTTPError:
                    continue  # isolamento totale: un link rotto non blocca gli altri (15.1 regola 4)
                trovati.extend(parse_html(r_dettaglio.text, fonte["source_id"], link))
            return trovati
