"""Scrittura su Google Sheets: sempre batch, mai cella per cella (15.1 regola 5).

Il punto critico di M0 (criterio di accettazione): prima di sovrascrivere un
foglio, si rileggono le colonne che l'utente modifica a mano (`stato`, `note`,
`bloccato`, `soppressa`) e si riportano nei dati da scrivere. Senza questo
passaggio, ogni run cancella il lavoro manuale della notte precedente
(08.8, 03.1.1).
"""
from __future__ import annotations

import sqlite3

import gspread

COLONNE_EVENTI = [
    "id", "titolo", "descrizione", "tipologia", "data_inizio", "ora_inizio",
    "data_fine", "ora_fine", "serie_id", "occorrenza", "comune", "luogo",
    "km", "minuti", "prezzo", "organizzatore", "url", "url_immagine",
    "fonti", "confidenza", "stato", "note", "primo_visto", "ultimo_visto",
    "bloccato", "soppressa",
]

# Colonne che appartengono all'utente: un run non le sovrascrive mai con un
# valore calcolato, le riporta così come le trova sul foglio (03.1.1).
COLONNE_UTENTE = {"stato", "note", "bloccato", "soppressa"}


def _leggi_overrides_utente(worksheet: gspread.Worksheet) -> dict[str, dict[str, str]]:
    """Rilettura preventiva: id evento -> {colonna_utente: valore}."""
    valori = worksheet.get_all_records()
    overrides: dict[str, dict[str, str]] = {}
    for riga in valori:
        event_id = riga.get("id")
        if not event_id:
            continue
        overrides[event_id] = {col: riga.get(col, "") for col in COLONNE_UTENTE}
    return overrides


def pubblica_eventi(worksheet: gspread.Worksheet, righe: list[dict]) -> None:
    """Scrive l'intero foglio `Eventi` in un colpo solo, preservando le colonne utente.

    `righe` è la lista di eventi calcolati da questo run (dict con le chiavi
    di COLONNE_EVENTI, tranne le colonne utente che vengono qui reintegrate).
    Le righe con `bloccato = si` letto dal foglio non vengono toccate: si
    riscrive comunque l'intera riga, ma con gli stessi valori già presenti
    (08.8: "Le righe con bloccato = sì non vengono mai sovrascritte, solo
    riposizionate").
    """
    overrides = _leggi_overrides_utente(worksheet)

    corpo = []
    for riga in righe:
        event_id = riga["id"]
        utente = overrides.get(event_id, {})
        riga_finale = dict(riga)
        for col in COLONNE_UTENTE:
            if col in utente and utente[col] != "":
                riga_finale[col] = utente[col]
        corpo.append([riga_finale.get(col, "") for col in COLONNE_EVENTI])

    worksheet.clear()
    worksheet.update(
        [COLONNE_EVENTI] + corpo,
        value_input_option="USER_ENTERED",
    )


COLONNE_PERIMETRO = ["comune", "alias", "provincia", "lat", "lon", "istat", "km", "minuti", "fascia", "attivo"]


def pubblica_perimetro(worksheet: gspread.Worksheet, conn: sqlite3.Connection) -> int:
    """Scrive il foglio `Perimetro` da SQLite (03.1.4). Nessuna colonna utente qui:
    `attivo` è l'unica modificabile a mano ma il foglio Perimetro è a bassa
    frequenza di scrittura (si aggiorna solo dopo un nuovo import), quindi
    non serve la rilettura preventiva di pubblica_eventi.
    """
    cur = conn.execute(
        "SELECT comune, alias, provincia, lat, lon, istat, km, minuti, fascia, attivo FROM comuni ORDER BY km ASC"
    )
    righe = [[row[col] for col in COLONNE_PERIMETRO] for row in cur.fetchall()]
    worksheet.clear()
    worksheet.update([COLONNE_PERIMETRO] + righe, value_input_option="USER_ENTERED")
    return len(righe)


def righe_da_sqlite(conn: sqlite3.Connection) -> list[dict]:
    cur = conn.execute(
        """
        SELECT event_id AS id, titolo, descrizione, tipologia, data_inizio,
               ora_inizio, data_fine, ora_fine, serie_id, occorrenza, comune,
               luogo, km, minuti, prezzo, organizzatore, url, url_immagine,
               '' AS fonti, confidenza, stato, note, primo_visto, ultimo_visto,
               bloccato, soppressa
        FROM events
        WHERE archiviato = 'no'
        ORDER BY data_inizio ASC, km ASC
        """
    )
    return [dict(row) for row in cur.fetchall()]
