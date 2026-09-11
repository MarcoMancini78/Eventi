"""Risoluzione del comune dal Perimetro già importato in SQLite (07.3, 07.5).

L'import iniziale del perimetro (M1, da Perimetro.txt) è stato eseguito una
tantum in fase di bootstrap ed è stato rimosso da qui: la tabella `comuni` è
la fonte di verità, popolata e mantenuta direttamente in SQLite/Sheets.
"""
from __future__ import annotations

import sqlite3
import unicodedata


def _normalizza(testo: str) -> str:
    """minuscolo, senza accenti — per il matching (M1 criterio di accettazione)."""
    if not testo:
        return ""
    testo = testo.strip().lower()
    testo = unicodedata.normalize("NFKD", testo)
    return "".join(c for c in testo if not unicodedata.combining(c))


def risolvi_comune(nome: str, conn: sqlite3.Connection) -> sqlite3.Row | None:
    """Cascata di risoluzione, livelli 1-2 di 07.3 (match esatto comune, poi alias).

    I livelli successivi (testo del luogo, dizionario dei luoghi, comune_riferimento
    della fonte, geocoding) si aggiungono nei moduli che li usano (normalizer, M5+).
    """
    chiave = _normalizza(nome)
    if not chiave:
        return None

    riga = conn.execute(
        "SELECT * FROM comuni WHERE attivo = 'si'"
    ).fetchall()
    for r in riga:
        if _normalizza(r["comune"]) == chiave:
            return r
    for r in riga:
        alias_list = [a.strip() for a in (r["alias"] or "").split(";")]
        if any(_normalizza(a) == chiave for a in alias_list):
            return r
    return None
