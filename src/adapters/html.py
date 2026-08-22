"""Adattatore HTML generico (04.3): T1, nessun selettore CSS per sito.

Scarica la pagina indice, ripulisce il testo con trafilatura, e produce un
artefatto grezzo se contiene abbastanza segnali di data da giustificare la
chiamata all'estrattore. Se una fonte richiede selettori custom per essere
utile, è il segnale che non conviene scriverne uno (04.3).
"""
from __future__ import annotations

import hashlib
import re

import httpx
import trafilatura

from .base import Adapter, Artefatto

_TIMEOUT_SECONDI = 15
_MAX_LINK_DETTAGLIO = 10  # limite rigido per fonte per run (04.3)

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


class HtmlAdapter(Adapter):
    """Adattatore generico: 1 pagina indice, nessun link di dettaglio per default.

    Il rendering JavaScript (Playwright) va aggiunto come flag per-fonte solo
    se il testo pulito risulta vuoto e la fonte è in polling_diretto (04.3):
    non è compito di questo adattatore di base.
    """

    def fetch(self, fonte: dict) -> list[Artefatto]:
        endpoint = fonte["endpoint"]
        with httpx.Client(timeout=_TIMEOUT_SECONDI, follow_redirects=True) as client:
            risposta = client.get(endpoint, headers={"User-Agent": fonte.get("user_agent", "EventiLocaliBot/1.0")})
            risposta.raise_for_status()
        return parse_html(risposta.text, fonte["source_id"], endpoint)
