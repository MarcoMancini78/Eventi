"""Deduplica, livello 1: chiave esatta (07.6). Livello 3 (fuzzy) trova un
evento simile nello stesso comune+data quando la chiave esatta non
matcha (dedup_key tronca lo slug a 20 caratteri: una singola parola
diversa può bastare a mancare un duplicato reale) — confronta titolo,
descrizione e fonte insieme (`normalizer.eventi_duplicati`, 2026-08-30:
il solo titolo mancava casi reali dove il titolo aggiunge solo un
dettaglio organizzativo breve, es. "Gruppi di Cammino" vs "Gruppi di
Cammino promossi dall'A.S.L. CN1"). Livello 2 (pHash) arriva con M5."""
from __future__ import annotations

import sqlite3
from datetime import date, datetime, timedelta

from .normalizer import dedup_key, event_id, eventi_duplicati, titolo_normalizzato

_CAMPI_OPZIONALI_DEFAULT = {
    "serie_id": None, "occorrenza": None, "url_approfondimento": None,
    "dettaglio_confidenza": None, "campi_incerti": None, "note_estrazione": None,
}


def _trova_duplicato_fuzzy(
    conn: sqlite3.Connection,
    titolo_norm: str,
    descrizione: str | None,
    source_id: str,
    data_inizio: str,
    comune: str,
) -> str | None:
    """Cerca un evento esistente nello stesso comune+data simile per
    titolo+descrizione+fonte (07.6 livello 3, trovato con casi reali
    2026-08-28/30). Limita la ricerca a comune+data invece di scorrere
    tutti gli eventi: due eventi diversi con titolo simile ma
    date/comuni diversi non sono un duplicato, e la finestra ristretta
    tiene il costo trascurabile anche a migliaia di righe."""
    candidati = conn.execute(
        "SELECT event_id, titolo, descrizione FROM events WHERE data_inizio = ? AND comune = ? AND archiviato = 'no'",
        (data_inizio, comune),
    ).fetchall()

    for candidato in candidati:
        fonti_candidato = {
            r["source_id"]
            for r in conn.execute(
                "SELECT source_id FROM event_sources WHERE event_id = ?", (candidato["event_id"],)
            ).fetchall()
        }
        if eventi_duplicati(
            titolo_norm,
            titolo_normalizzato(candidato["titolo"]),
            descrizione,
            candidato["descrizione"],
            {source_id},
            fonti_candidato,
        ):
            return candidato["event_id"]
    return None


def upsert_evento(conn: sqlite3.Connection, evento: dict, source_id: str) -> str:
    """Inserisce o aggiorna un evento per dedup_key esatta, con un
    controllo fuzzy di riserva (livello 3) quando la chiave esatta non
    trova nulla. Ritorna l'event_id.

    Se l'evento esiste già, aggiorna solo i campi calcolati (mai le colonne
    utente: stato/note/bloccato/soppressa restano quelle già in DB — le
    tocca solo publisher.py in fase di scrittura su Sheet, mai qui).
    `serie_id`/`occorrenza` sono opzionali: presenti solo per le occorrenze
    generate da una Serie (07.9), assenti per gli eventi singoli.
    """
    evento = {**_CAMPI_OPZIONALI_DEFAULT, **evento}
    chiave = dedup_key(evento["titolo_normalizzato"], evento["data_inizio"], evento["comune_normalizzato"])
    eid = event_id(chiave)
    oggi = date.today().isoformat()

    esistente = conn.execute("SELECT bloccato FROM events WHERE event_id = ?", (eid,)).fetchone()

    if not esistente:
        eid_fuzzy = _trova_duplicato_fuzzy(
            conn,
            evento["titolo_normalizzato"],
            evento.get("descrizione"),
            source_id,
            evento["data_inizio"],
            evento["comune"],
        )
        if eid_fuzzy:
            eid = eid_fuzzy
            esistente = conn.execute("SELECT bloccato FROM events WHERE event_id = ?", (eid,)).fetchone()

    if esistente and esistente["bloccato"] == "si":
        conn.execute("UPDATE events SET ultimo_visto = ? WHERE event_id = ?", (oggi, eid))
        _registra_fonte(conn, eid, source_id, evento.get("url", ""))
        conn.commit()
        return eid

    if esistente:
        conn.execute(
            """
            UPDATE events SET
                titolo=:titolo, descrizione=:descrizione, tipologia=:tipologia,
                data_inizio=:data_inizio, ora_inizio=:ora_inizio, data_fine=:data_fine,
                ora_fine=:ora_fine, serie_id=:serie_id, occorrenza=:occorrenza,
                comune=:comune, luogo=:luogo, km=:km, minuti=:minuti,
                prezzo=:prezzo, organizzatore=:organizzatore, url=:url, url_immagine=:url_immagine,
                url_approfondimento=:url_approfondimento,
                confidenza=:confidenza, dettaglio_confidenza=:dettaglio_confidenza,
                campi_incerti=:campi_incerti, note_estrazione=:note_estrazione, ultimo_visto=:oggi
            WHERE event_id=:event_id
            """,
            {**evento, "event_id": eid, "oggi": oggi},
        )
    else:
        conn.execute(
            """
            INSERT INTO events (
                event_id, dedup_key, titolo, descrizione, tipologia, data_inizio,
                ora_inizio, data_fine, ora_fine, serie_id, occorrenza, comune, luogo,
                km, minuti, prezzo, organizzatore, url, url_immagine, url_approfondimento,
                confidenza, dettaglio_confidenza, campi_incerti, note_estrazione,
                stato, primo_visto, ultimo_visto, bloccato, soppressa, archiviato
            ) VALUES (
                :event_id, :dedup_key, :titolo, :descrizione, :tipologia, :data_inizio,
                :ora_inizio, :data_fine, :ora_fine, :serie_id, :occorrenza, :comune, :luogo,
                :km, :minuti, :prezzo, :organizzatore, :url, :url_immagine, :url_approfondimento,
                :confidenza, :dettaglio_confidenza, :campi_incerti, :note_estrazione,
                'nuovo', :oggi, :oggi, 'no', 'no', 'no'
            )
            """,
            {**evento, "event_id": eid, "dedup_key": chiave, "oggi": oggi},
        )

    _registra_fonte(conn, eid, source_id, evento.get("url", ""))
    conn.commit()
    return eid


def _registra_fonte(conn: sqlite3.Connection, event_id_: str, source_id: str, url: str) -> None:
    conn.execute(
        """
        INSERT INTO event_sources (event_id, source_id, url, seen_at)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(event_id, source_id) DO UPDATE SET url=excluded.url, seen_at=excluded.seen_at
        """,
        (event_id_, source_id, url, datetime.now().isoformat()),
    )


def archivia_eventi_conclusi(conn: sqlite3.Connection, giorni_archiviazione: int) -> int:
    """Sposta in Archivio (flag `archiviato`) gli eventi con data_fine < oggi - giorni_archiviazione (03.1.2).

    In SQLite non serve una tabella separata: `archiviato='si'` esclude la
    riga dalla vista principale (publisher.righe_da_sqlite già filtra su
    questo campo). Il publisher scriverà la riga nel foglio Archivio in una
    fase successiva (M2 completo prevede questa parte quando Sheets è collegato).
    """
    soglia = (date.today() - timedelta(days=giorni_archiviazione)).isoformat()
    cur = conn.execute(
        "UPDATE events SET archiviato = 'si' WHERE data_fine < ? AND archiviato = 'no'",
        (soglia,),
    )
    conn.commit()
    return cur.rowcount
