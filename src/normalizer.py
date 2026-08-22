"""Normalizzazione deterministica: titolo, date, comune (07.1-07.3). Nessun LLM, nessun costo."""
from __future__ import annotations

import hashlib
import re
import sqlite3
import unicodedata

from .perimetro import risolvi_comune

_STOPWORD = {
    "la", "il", "lo", "di", "a", "da", "in", "con", "su", "per", "tra", "fra",
    "e", "ed", "festa", "sagra", "edizione", "annuale",
}
_ORDINALE_EDIZIONE = re.compile(r"\b\d+[ªº°]|\bX{0,3}(IX|IV|V?I{0,3})\b", re.IGNORECASE)
_PUNTEGGIATURA_RIPETUTA = re.compile(r"([!?.]){2,}")
_SPAZI_MULTIPLI = re.compile(r"\s+")

_MINUSCOLE_INTERNE = {"di", "della", "dello", "delle", "dei", "degli", "e", "a", "in", "per", "del"}


def titolo_visualizzato(titolo_grezzo: str) -> str:
    """Rimuove emoji/decorazioni, applica Title Case italiano, taglia a 120 caratteri (07.1)."""
    if not titolo_grezzo:
        return ""

    senza_emoji = "".join(
        c for c in titolo_grezzo if unicodedata.category(c)[0] != "So"
    )
    compresso = _SPAZI_MULTIPLI.sub(" ", senza_emoji).strip()
    ripulito = _PUNTEGGIATURA_RIPETUTA.sub(r"\1", compresso)

    if ripulito.isupper():
        parole = ripulito.lower().split(" ")
        parole = [
            p if p in _MINUSCOLE_INTERNE and i > 0 else p.capitalize()
            for i, p in enumerate(parole)
        ]
        ripulito = " ".join(parole)

    if len(ripulito) > 120:
        troncato = ripulito[:120]
        ultimo_spazio = troncato.rfind(" ")
        ripulito = troncato[:ultimo_spazio] if ultimo_spazio > 0 else troncato

    return ripulito


def titolo_normalizzato(titolo_grezzo: str, comune: str | None = None) -> str:
    """Solo per il matching interno: minuscolo, senza accenti, stopword rimosse, token ordinati (07.1)."""
    if not titolo_grezzo:
        return ""

    testo = unicodedata.normalize("NFKD", titolo_grezzo.lower())
    testo = "".join(c for c in testo if not unicodedata.combining(c))
    testo = _ORDINALE_EDIZIONE.sub("", testo)

    if comune:
        comune_norm = unicodedata.normalize("NFKD", comune.lower())
        comune_norm = "".join(c for c in comune_norm if not unicodedata.combining(c))
        testo = testo.replace(comune_norm, "")

    testo = re.sub(r"[^\w\s]", " ", testo)
    token = [t for t in testo.split() if t and t not in _STOPWORD]
    return " ".join(sorted(token))


def normalizza_orario(valore: str | None) -> str | None:
    """'21' -> '21:00'; '21.30' -> '21:30' (07.2)."""
    if not valore:
        return None
    valore = valore.strip().replace(".", ":")
    if ":" not in valore:
        valore = f"{valore}:00"
    ore, _, minuti = valore.partition(":")
    ore = ore.zfill(2)
    minuti = (minuti or "00").zfill(2)
    return f"{ore}:{minuti}"


def risolvi_comune_evento(comune_testuale: str | None, comune_fonte: str | None, conn: sqlite3.Connection):
    """Cascata 07.3, livelli 1-2-5: match esatto/alias, poi comune_riferimento della fonte.

    Ritorna (riga_comune | None, confidenza_penalita). I livelli 3/4/6/7
    (testo del luogo, dizionario dei luoghi, geocoding, quarantena) si
    aggiungono quando i moduli relativi esistono (M5+).
    """
    if comune_testuale:
        riga = risolvi_comune(comune_testuale, conn)
        if riga:
            return riga, 0

    if comune_fonte:
        riga = risolvi_comune(comune_fonte, conn)
        if riga:
            return riga, -10  # inferenza dal comune di riferimento della fonte (07.3.5)

    return None, 0


def dedup_key(titolo_norm: str, data_inizio: str, comune_norm: str) -> str:
    """sha1(slug(titolo)[:20] | data_inizio | comune) — identità dell'evento (03.3)."""
    slug = titolo_norm.replace(" ", "-")[:20]
    base = f"{slug}|{data_inizio}|{comune_norm}"
    return hashlib.sha1(base.encode("utf-8")).hexdigest()


def event_id(chiave: str) -> str:
    return chiave[:12]
