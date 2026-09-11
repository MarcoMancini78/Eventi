"""Collega i teatri/attività in coda_follow al comune del perimetro (16, pagina Perimetro).

`coda_follow` per categoria='teatro' (e simili) ha sempre `comune=NULL`: il
nome del comune è scritto solo dentro `soggetto` come testo libero
("Cambiano - Teatro Comunale"). Per costruire la pagina Perimetro (elenco
comuni con i link collegati, incluso "Altro" per teatri/attività) serve un
collegamento esplicito. Deduzione fatta una volta e persistita in
`coda_follow.comune` — mai ricalcolata ad ogni publish — così resta
correggibile a mano come ogni altro campo del progetto (03.1).
"""
from __future__ import annotations

import sqlite3

from . import perimetro


def deduci_comune_da_soggetto(soggetto: str) -> str | None:
    """"Comune - Nome attività" -> "Comune". None se il formato non combacia."""
    if not soggetto or " - " not in soggetto:
        return None
    return soggetto.split(" - ", 1)[0].strip() or None


def collega_teatri(conn: sqlite3.Connection, categorie: tuple[str, ...] = ("teatro",)) -> list[dict]:
    """Popola `coda_follow.comune` per le righe con comune NULL, deducendolo dal
    soggetto e risolvendolo contro il perimetro. Non sovrascrive mai un comune
    già presente (manuale o già dedotto in un giro precedente).

    Ritorna un riepilogo per riga (source_id, piattaforma, soggetto, comune
    dedotto o None) per poter stampare/verificare cosa è stato fatto.
    """
    placeholders = ",".join("?" * len(categorie))
    righe = conn.execute(
        f"SELECT source_id, piattaforma, soggetto FROM coda_follow "
        f"WHERE categoria IN ({placeholders}) AND (comune IS NULL OR comune = '')",
        categorie,
    ).fetchall()

    esiti = []
    for riga in righe:
        nome_dedotto = deduci_comune_da_soggetto(riga["soggetto"])
        comune_risolto = perimetro.risolvi_comune(nome_dedotto, conn) if nome_dedotto else None
        comune_finale = comune_risolto["comune"] if comune_risolto else None

        if comune_finale:
            conn.execute(
                "UPDATE coda_follow SET comune = ?, note = 'comune dedotto automaticamente dal soggetto' "
                "WHERE source_id = ? AND piattaforma = ?",
                (comune_finale, riga["source_id"], riga["piattaforma"]),
            )

        esiti.append(
            {
                "source_id": riga["source_id"],
                "piattaforma": riga["piattaforma"],
                "soggetto": riga["soggetto"],
                "comune": comune_finale,
            }
        )

    conn.commit()
    return esiti
