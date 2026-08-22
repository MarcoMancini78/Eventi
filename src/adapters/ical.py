"""Adattatore iCal: T0 puro, nessun LLM (04.3).

Parsing standard VEVENT -> SUMMARY, DTSTART, DTEND, LOCATION, DESCRIPTION.
Solo normalizzazione, nessuna chiamata al modello: i campi sono già
strutturati alla fonte.
"""
from __future__ import annotations

import hashlib
import re
from datetime import datetime

import httpx

from .base import Adapter, Artefatto

_TIMEOUT_SECONDI = 15  # ogni chiamata di rete ha un timeout esplicito (15.1 regola 3)


def _decodifica_data_ical(valore: str) -> tuple[str, str | None]:
    """'20260912T210000' o '20260912' -> ('2026-09-12', '21:00' | None)."""
    valore = valore.strip()
    solo_data = valore.split("T")[0]
    data_iso = f"{solo_data[0:4]}-{solo_data[4:6]}-{solo_data[6:8]}"
    ora = None
    if "T" in valore:
        parte_ora = valore.split("T")[1].rstrip("Z")
        if len(parte_ora) >= 4:
            ora = f"{parte_ora[0:2]}:{parte_ora[2:4]}"
    return data_iso, ora


def _unfold_righe(testo_ics: str) -> list[str]:
    """RFC 5545: una riga che continua inizia con uno spazio/tab sulla riga dopo."""
    righe_grezze = testo_ics.replace("\r\n", "\n").split("\n")
    righe: list[str] = []
    for riga in righe_grezze:
        if riga.startswith((" ", "\t")) and righe:
            righe[-1] += riga[1:]
        else:
            righe.append(riga)
    return righe


def parse_ical(testo_ics: str, source_id: str, fetch_url: str) -> list[Artefatto]:
    artefatti: list[Artefatto] = []
    evento_corrente: dict[str, str] = {}
    dentro_evento = False

    for riga in _unfold_righe(testo_ics):
        if riga.strip() == "BEGIN:VEVENT":
            dentro_evento = True
            evento_corrente = {}
            continue
        if riga.strip() == "END:VEVENT":
            dentro_evento = False
            if evento_corrente.get("DTSTART") and evento_corrente.get("SUMMARY"):
                data_inizio, ora_inizio = _decodifica_data_ical(evento_corrente["DTSTART"])
                data_fine = data_inizio
                if evento_corrente.get("DTEND"):
                    data_fine, _ = _decodifica_data_ical(evento_corrente["DTEND"])

                testo_grezzo = evento_corrente.get("DESCRIPTION", "")
                raw_hash = hashlib.sha1(
                    f"{evento_corrente.get('SUMMARY')}|{data_inizio}".encode("utf-8")
                ).hexdigest()

                artefatti.append(
                    Artefatto(
                        source_id=source_id,
                        url=evento_corrente.get("URL", fetch_url),
                        kind="ical",
                        text=testo_grezzo,
                        titolo=evento_corrente.get("SUMMARY"),
                        data_inizio=data_inizio,
                        data_fine=data_fine,
                        ora_inizio=ora_inizio,
                        luogo_testuale=evento_corrente.get("LOCATION"),
                        descrizione=testo_grezzo or None,
                        raw_hash=raw_hash,
                    )
                )
            continue

        if dentro_evento and ":" in riga:
            chiave, _, valore = riga.partition(":")
            chiave = chiave.split(";")[0]  # ignora i parametri (es. DTSTART;TZID=...)
            valore = re.sub(r"\\([,;nN])", lambda m: "\n" if m.group(1).lower() == "n" else m.group(1), valore)
            evento_corrente[chiave] = valore.strip()

    return artefatti


class ICalAdapter(Adapter):
    def fetch(self, fonte: dict) -> list[Artefatto]:
        endpoint = fonte["endpoint"]
        with httpx.Client(timeout=_TIMEOUT_SECONDI, follow_redirects=True) as client:
            risposta = client.get(endpoint, headers={"User-Agent": fonte.get("user_agent", "EventiLocaliBot/1.0")})
            risposta.raise_for_status()
        return parse_ical(risposta.text, fonte["source_id"], endpoint)
