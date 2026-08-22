"""Adattatore RSS/Atom (04.3).

La data del feed è la data di *pubblicazione*, non dell'evento: serve
comunque l'estrattore sul testo, ma con `context_date` valorizzato, che
rende affidabile l'interpretazione di date relative ("sabato prossimo").
Nessun campo evento strutturato qui: solo titolo, testo e data di
pubblicazione grezzi.
"""
from __future__ import annotations

import hashlib
import xml.etree.ElementTree as ET
from email.utils import parsedate_to_datetime

import httpx

from .base import Adapter, Artefatto

_TIMEOUT_SECONDI = 15

_NS_ATOM = "{http://www.w3.org/2005/Atom}"


def _testo(elemento: ET.Element | None) -> str:
    return (elemento.text or "").strip() if elemento is not None else ""


def _data_pubblicazione_iso(valore: str) -> str | None:
    if not valore:
        return None
    try:
        return parsedate_to_datetime(valore).date().isoformat()
    except (TypeError, ValueError):
        return None


def parse_rss(testo_xml: str, source_id: str, fetch_url: str) -> list[Artefatto]:
    root = ET.fromstring(testo_xml)
    artefatti: list[Artefatto] = []

    items = root.findall(".//item")
    if items:  # RSS 2.0
        for item in items:
            titolo = _testo(item.find("title"))
            link = _testo(item.find("link")) or fetch_url
            descrizione = _testo(item.find("description"))
            pub_date = _data_pubblicazione_iso(_testo(item.find("pubDate")))
            testo = f"{titolo}\n{descrizione}".strip()
            artefatti.append(
                Artefatto(
                    source_id=source_id,
                    url=link,
                    kind="rss",
                    text=testo,
                    context_date=pub_date,
                    raw_hash=hashlib.sha1(testo.encode("utf-8")).hexdigest(),
                )
            )
        return artefatti

    entries = root.findall(f".//{_NS_ATOM}entry")  # Atom
    for entry in entries:
        titolo = _testo(entry.find(f"{_NS_ATOM}title"))
        link_el = entry.find(f"{_NS_ATOM}link")
        link = link_el.get("href") if link_el is not None else fetch_url
        contenuto = _testo(entry.find(f"{_NS_ATOM}summary")) or _testo(entry.find(f"{_NS_ATOM}content"))
        pubblicato = _testo(entry.find(f"{_NS_ATOM}published")) or _testo(entry.find(f"{_NS_ATOM}updated"))
        pub_date = pubblicato[:10] if pubblicato else None
        testo = f"{titolo}\n{contenuto}".strip()
        artefatti.append(
            Artefatto(
                source_id=source_id,
                url=link or fetch_url,
                kind="rss",
                text=testo,
                context_date=pub_date,
                raw_hash=hashlib.sha1(testo.encode("utf-8")).hexdigest(),
            )
        )
    return artefatti


class RssAdapter(Adapter):
    def fetch(self, fonte: dict) -> list[Artefatto]:
        endpoint = fonte["endpoint"]
        with httpx.Client(timeout=_TIMEOUT_SECONDI, follow_redirects=True) as client:
            risposta = client.get(endpoint, headers={"User-Agent": fonte.get("user_agent", "EventiLocaliBot/1.0")})
            risposta.raise_for_status()
        return parse_rss(risposta.text, fonte["source_id"], endpoint)
