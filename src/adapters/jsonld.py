"""Adattatore JSON-LD schema.org/Event (04.3): T0 puro, nessun LLM.

Estrae direttamente startDate, endDate, location, name, description da
pagine HTML normali. È il tier T0 più prezioso perché arriva da pagine che
non sembrano un feed.
"""
from __future__ import annotations

import hashlib
import json
import re

import httpx

from .base import Adapter, Artefatto

_TIMEOUT_SECONDI = 15
_SCRIPT_LD_JSON = re.compile(
    r'<script[^>]+type=["\']application/ld\+json["\'][^>]*>(.*?)</script>',
    re.DOTALL | re.IGNORECASE,
)


def _estrai_data(valore) -> str | None:
    if not valore:
        return None
    return str(valore)[:10]


def _estrai_luogo(location) -> str | None:
    """Bug reale trovato (2026-09-01, template ePublic/ComWeb — variante di
    pa_design_system usata da diversi comuni, es. comune.parodiligure.al.it):
    'address' è talvolta una LISTA di un solo elemento invece di un dict
    (schema.org lo permette, la maggior parte dei siti non lo fa). Un
    location.get('address', {}) presumeva sempre un dict e sollevava
    AttributeError, facendo fallire l'intera fonte silenziosamente in
    produzione (isolata da esegui_fonte, ma zero eventi estratti)."""
    if isinstance(location, dict):
        nome = location.get("name")
        if nome:
            return nome
        indirizzo = location.get("address")
        if isinstance(indirizzo, list):
            indirizzo = indirizzo[0] if indirizzo else None
        if isinstance(indirizzo, dict):
            return indirizzo.get("addressLocality")
        return None
    if isinstance(location, str):
        return location
    return None


def _eventi_da_nodo(nodo: dict) -> list[dict]:
    tipo = nodo.get("@type")
    tipi = tipo if isinstance(tipo, list) else [tipo]
    if any(t == "Event" for t in tipi if t):
        return [nodo]
    grafo = nodo.get("@graph")
    if isinstance(grafo, list):
        return [n for n in grafo if isinstance(n, dict) and _eventi_da_nodo(n)]
    return []


def parse_jsonld(html: str, source_id: str, fetch_url: str) -> list[Artefatto]:
    artefatti: list[Artefatto] = []
    for blocco in _SCRIPT_LD_JSON.findall(html):
        try:
            dati = json.loads(blocco.strip())
        except json.JSONDecodeError:
            continue

        candidati = dati if isinstance(dati, list) else [dati]
        nodi_evento: list[dict] = []
        for candidato in candidati:
            if not isinstance(candidato, dict):
                continue
            nodi_evento.extend(_eventi_da_nodo(candidato))

        for evento in nodi_evento:
            titolo = evento.get("name")
            data_inizio = _estrai_data(evento.get("startDate"))
            if not titolo or not data_inizio:
                continue
            data_fine = _estrai_data(evento.get("endDate")) or data_inizio
            descrizione = evento.get("description")
            testo = f"{titolo}\n{descrizione or ''}".strip()
            artefatti.append(
                Artefatto(
                    source_id=source_id,
                    url=evento.get("url", fetch_url),
                    kind="jsonld",
                    text=testo,
                    titolo=titolo,
                    data_inizio=data_inizio,
                    data_fine=data_fine,
                    luogo_testuale=_estrai_luogo(evento.get("location")),
                    descrizione=descrizione,
                    raw_hash=hashlib.sha1(testo.encode("utf-8")).hexdigest(),
                )
            )
    return artefatti


class JsonLdAdapter(Adapter):
    def fetch(self, fonte: dict) -> list[Artefatto]:
        endpoint = fonte["endpoint"]
        with httpx.Client(timeout=_TIMEOUT_SECONDI, follow_redirects=True) as client:
            risposta = client.get(endpoint, headers={"User-Agent": fonte.get("user_agent", "EventiLocaliBot/1.0")})
            risposta.raise_for_status()
        return parse_jsonld(risposta.text, fonte["source_id"], endpoint)
