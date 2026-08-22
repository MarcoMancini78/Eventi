"""Deduplica, livello 1: chiave esatta (07.6). I livelli 2 (pHash) e 3 (fuzzy) arrivano con M5."""
from __future__ import annotations

import sqlite3
from datetime import date, datetime, timedelta, timezone

from .normalizer import dedup_key, event_id


def upsert_evento(conn: sqlite3.Connection, evento: dict, source_id: str) -> str:
    """Inserisce o aggiorna un evento per dedup_key esatta. Ritorna l'event_id.

    Se l'evento esiste già, aggiorna solo i campi calcolati (mai le colonne
    utente: stato/note/bloccato/soppressa restano quelle già in DB — le
    tocca solo publisher.py in fase di scrittura su Sheet, mai qui).
    """
    chiave = dedup_key(evento["titolo_normalizzato"], evento["data_inizio"], evento["comune_normalizzato"])
    eid = event_id(chiave)
    oggi = date.today().isoformat()

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
                ora_fine=:ora_fine, comune=:comune, luogo=:luogo, km=:km, minuti=:minuti,
                prezzo=:prezzo, organizzatore=:organizzatore, url=:url, url_immagine=:url_immagine,
                confidenza=:confidenza, ultimo_visto=:oggi
            WHERE event_id=:event_id
            """,
            {**evento, "event_id": eid, "oggi": oggi},
        )
    else:
        conn.execute(
            """
            INSERT INTO events (
                event_id, dedup_key, titolo, descrizione, tipologia, data_inizio,
                ora_inizio, data_fine, ora_fine, comune, luogo, km, minuti, prezzo,
                organizzatore, url, url_immagine, confidenza, stato, primo_visto,
                ultimo_visto, bloccato, soppressa, archiviato
            ) VALUES (
                :event_id, :dedup_key, :titolo, :descrizione, :tipologia, :data_inizio,
                :ora_inizio, :data_fine, :ora_fine, :comune, :luogo, :km, :minuti, :prezzo,
                :organizzatore, :url, :url_immagine, :confidenza, 'nuovo', :oggi,
                :oggi, 'no', 'no', 'no'
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
        (event_id_, source_id, url, datetime.now(timezone.utc).isoformat()),
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
