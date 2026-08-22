"""M1 — Import del Perimetro, fasce, alias e risoluzione del comune (03.1.4, 07.3, 07.5).

Il file sorgente Perimetro.txt usa già il punto come separatore decimale
(non la virgola tra apici del vecchio workbook, 13.1/15/M1) ma non è ancora
tagliato a 100 km (D15): il taglio e la derivazione della fascia si fanno qui.
"""
from __future__ import annotations

import csv
import sqlite3
import unicodedata
from pathlib import Path

from .config import Config


def _normalizza(testo: str) -> str:
    """minuscolo, senza accenti — per il matching (M1 criterio di accettazione)."""
    if not testo:
        return ""
    testo = testo.strip().lower()
    testo = unicodedata.normalize("NFKD", testo)
    return "".join(c for c in testo if not unicodedata.combining(c))


def _fascia(km: float, config: Config) -> str:
    if km <= config.soglia_fascia_a_km:
        return "A"
    if km <= config.soglia_fascia_b_km:
        return "B"
    return "C"


def importa_perimetro(csv_path: Path, conn: sqlite3.Connection, config: Config) -> dict:
    """Legge Perimetro.txt (';' separato), filtra a raggio_max_km, scrive in SQLite.

    Ritorna un riepilogo {fascia: conteggio} per il criterio di accettazione
    di M1 ("il conteggio per fascia è stampabile e i numeri sono plausibili").
    """
    conteggi = {"A": 0, "B": 0, "C": 0, "esclusi": 0}

    with open(csv_path, encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f, delimiter=";")
        righe = list(reader)

    for riga in righe:
        km = float(riga["DistanzaKm"])
        if riga.get("Incluso", "SI").strip().upper() != "SI" or km > config.raggio_max_km:
            conteggi["esclusi"] += 1
            continue

        fascia = _fascia(km, config)
        conteggi[fascia] += 1

        conn.execute(
            """
            INSERT INTO comuni (istat, comune, alias, provincia, lat, lon, km, minuti, fascia, attivo)
            VALUES (:istat, :comune, :alias, :provincia, :lat, :lon, :km, :minuti, :fascia, 'si')
            ON CONFLICT(istat) DO UPDATE SET
                comune=excluded.comune, provincia=excluded.provincia,
                lat=excluded.lat, lon=excluded.lon, km=excluded.km,
                minuti=excluded.minuti, fascia=excluded.fascia
            """,
            {
                "istat": riga["CodiceISTAT"],
                "comune": riga["Comune"],
                "alias": riga["Comune"],  # popolato solo con il nome ufficiale; le frazioni si aggiungono a mano per fascia A (03.1.4)
                "provincia": riga["Provincia"],
                "lat": float(riga["Latitudine"]),
                "lon": float(riga["Longitudine"]),
                "km": km,
                "minuti": float(riga["DurataStimataMinuti"]),
                "fascia": fascia,
            },
        )

    conn.commit()
    return conteggi


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
