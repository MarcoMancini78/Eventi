"""M6 collegato alla pipeline: dal campo `ricorrenza` dell'estrattore (06.2)
a una riga in `Serie` e alle occorrenze espanse in `events` (07.9, 03.1.3b).

Una serie è identificata da (titolo_normalizzato, comune, luogo): stessa
regola di deduplica del titolo usata per gli eventi singoli, applicata qui
per non creare una serie nuova a ogni citazione della stessa ricorrenza.
"""
from __future__ import annotations

import hashlib
import sqlite3
from datetime import date

from .extractor.schema import Ricorrenza
from .normalizer import dedup_key, titoli_simili, titolo_normalizzato, titolo_visualizzato
from .recurrence import (
    RegolaRicorrenza,
    costruisci_rrule,
    espandi_occorrenze,
    normalizza_giorno_settimana,
    regola_leggibile,
    stato_decadimento,
)


def _serie_id(titolo_normalizzato_: str, comune: str, luogo: str | None) -> str:
    base = f"{titolo_normalizzato_}|{comune}|{luogo or ''}"
    return hashlib.sha1(base.encode("utf-8")).hexdigest()[:12]


def _titolo_serie_simile(titolo_norm_a: str, titolo_norm_b: str) -> bool:
    """`titoli_simili` da sola manca lo stesso caso limite già trovato per
    gli eventi singoli ('Gruppi di Cammino' vs 'Gruppi di Cammino
    promossi dall'A.S.L. CN1': overlap titolo 1.0 ma solo 2 token nel
    titolo corto, sotto la soglia di 3 pensata per titoli brevi
    genuinamente diversi). Per gli eventi il segnale aggiuntivo era
    descrizione/fonte (`eventi_duplicati`); le Serie non hanno una
    descrizione, ma qui il confronto è già ristretto allo stesso comune
    (meno margine per falsi positivi di quanto ne avrebbe un confronto
    globale) — overlap perfetto senza il vincolo dei 3 token basta."""
    if titoli_simili(titolo_norm_a, titolo_norm_b):
        return True
    token_a = set(titolo_norm_a.split())
    token_b = set(titolo_norm_b.split())
    if not token_a or not token_b:
        return False
    overlap = len(token_a & token_b) / min(len(token_a), len(token_b))
    return overlap >= 1.0


def _trova_serie_fuzzy(conn: sqlite3.Connection, titolo_norm: str, comune: str) -> str | None:
    """Dedup livello 3 per le Serie (2026-08-30, richiesto dall'utente
    dopo aver notato 3 righe 'Gruppi di Cammino' a Envie): `_serie_id` fa
    match esatto sul titolo normalizzato, lo stesso limite già risolto
    per gli eventi singoli in dedup.py, ma mai esteso qui. Cerca tra le
    serie attive dello stesso comune un titolo simile, prima di crearne
    una nuova."""
    candidate = conn.execute(
        "SELECT serie_id, titolo FROM series WHERE comune = ? AND stato != 'sospesa'", (comune,)
    ).fetchall()
    for candidata in candidate:
        if _titolo_serie_simile(titolo_norm, titolo_normalizzato(candidata["titolo"], comune)):
            return candidata["serie_id"]
    return None


def upsert_serie(
    conn: sqlite3.Connection,
    ricorrenza: Ricorrenza,
    titolo: str,
    tipologia: str,
    comune: str,
    luogo: str | None,
    fonte: str,
    oggi: date | None = None,
) -> str | None:
    """Crea o aggiorna la riga Serie. Ritorna serie_id, o None se la ricorrenza
    non è convertibile in RRULE (frequenza annuale o campi insufficienti:
    07.9 prevede solo settimanale/mensile per ora)."""
    if ricorrenza.frequenza not in ("settimanale", "mensile") or not ricorrenza.giorni_settimana:
        return None

    # Bug reale osservato (2026-08-26): l'LLM può restituire il nome del
    # giorno per esteso ("mercoledì") invece del codice RFC5545 atteso,
    # nonostante il prompt lo richieda esplicitamente — normalizzato qui,
    # una sola volta, prima che il valore raggiunga costruisci_rrule/
    # regola_leggibile (che altrimenti sollevano KeyError e fermano
    # l'intero run, violando 15.1 regola 4). Giorni non riconosciuti
    # vengono scartati silenziosamente, non l'intera serie.
    giorni_normalizzati = [
        g for g in (normalizza_giorno_settimana(g) for g in ricorrenza.giorni_settimana) if g
    ]
    if not giorni_normalizzati:
        return None

    oggi = oggi or date.today()
    titolo_norm = titolo_normalizzato(titolo, comune)
    sid = _serie_id(titolo_norm, comune, luogo)

    if not conn.execute("SELECT 1 FROM series WHERE serie_id = ?", (sid,)).fetchone():
        sid_fuzzy = _trova_serie_fuzzy(conn, titolo_norm, comune)
        if sid_fuzzy:
            sid = sid_fuzzy

    regola = RegolaRicorrenza(
        frequenza=ricorrenza.frequenza,
        giorni_settimana=giorni_normalizzati,
        ordinale=ricorrenza.ordinale,
        mesi_inclusi=ricorrenza.mesi_inclusi or list(range(1, 13)),
        valida_dal=oggi.isoformat(),
        valida_al=ricorrenza.fine_dichiarata,
    )
    rrule_str = costruisci_rrule(regola)
    leggibile = regola_leggibile(regola)

    esistente = conn.execute("SELECT serie_id, bloccata FROM series WHERE serie_id = ?", (sid,)).fetchone()
    if esistente and esistente["bloccata"] == "si":
        # 07.9: una serie bloccata dall'utente non viene più toccata dal sistema.
        conn.execute("UPDATE series SET ultima_conferma = ? WHERE serie_id = ?", (oggi.isoformat(), sid))
        conn.commit()
        return sid

    if esistente:
        conn.execute(
            """
            UPDATE series SET titolo=?, tipologia=?, comune=?, luogo=?, rrule=?, regola_leggibile=?,
                   valida_al=?, ultima_conferma=?, stato='attiva', fonti=?
            WHERE serie_id=?
            """,
            (titolo_visualizzato(titolo), tipologia, comune, luogo, rrule_str, leggibile,
             ricorrenza.fine_dichiarata, oggi.isoformat(), fonte, sid),
        )
    else:
        conn.execute(
            """
            INSERT INTO series (serie_id, titolo, tipologia, comune, luogo, rrule, regola_leggibile,
                                 valida_dal, valida_al, eccezioni, ultima_conferma, stato, fonti, bloccata)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, '', ?, 'attiva', ?, 'no')
            """,
            (sid, titolo_visualizzato(titolo), tipologia, comune, luogo, rrule_str, leggibile,
             oggi.isoformat(), ricorrenza.fine_dichiarata, oggi.isoformat(), fonte),
        )
    conn.commit()
    return sid


def espandi_serie_in_eventi(conn: sqlite3.Connection, serie_id: str, config, oggi: date | None = None) -> list[dict]:
    """Genera le occorrenze non ancora presenti/soppresse per una serie (07.9).

    Ritorna la lista di dict pronti per dedup.upsert_evento, con serie_id e
    occorrenza valorizzati. Le occorrenze soppresse (soppressa='si' su un
    evento già generato con lo stesso serie_id+data) non vengono ricreate.
    """
    riga = conn.execute("SELECT * FROM series WHERE serie_id = ?", (serie_id,)).fetchone()
    if riga is None:
        return []

    oggi = oggi or date.today()
    stato = stato_decadimento(riga["ultima_conferma"], oggi)
    if stato != riga["stato"]:
        conn.execute("UPDATE series SET stato = ? WHERE serie_id = ?", (stato, serie_id))
        conn.commit()
    if stato == "sospesa":
        return []  # 07.9: oltre 400 giorni senza conferma, smette di espandere

    eccezioni = [d for d in (riga["eccezioni"] or "").split(";") if d]
    date_generate = espandi_occorrenze(
        riga["rrule"], riga["valida_dal"], eccezioni, config.orizzonte_espansione_giorni, oggi
    )

    comune_riga = conn.execute("SELECT * FROM comuni WHERE comune = ?", (riga["comune"],)).fetchone()
    if comune_riga is None:
        return []  # comune della serie non nel perimetro: non generare occorrenze fantasma

    soppresse = {
        r["data_inizio"]
        for r in conn.execute(
            "SELECT data_inizio FROM events WHERE serie_id = ? AND soppressa = 'si'", (serie_id,)
        ).fetchall()
    }

    confidenza_penalita = -25 if stato == "da_verificare" else 0
    eventi = []
    totale = len(date_generate)
    for indice, data_iso in enumerate(sorted(date_generate), start=1):
        if data_iso in soppresse:
            continue
        titolo_norm = titolo_normalizzato(riga["titolo"], riga["comune"])
        eventi.append(
            {
                "titolo": riga["titolo"],
                "titolo_normalizzato": titolo_norm,
                "descrizione": None,
                "tipologia": riga["tipologia"],
                "data_inizio": data_iso,
                "ora_inizio": None,
                "data_fine": data_iso,
                "ora_fine": None,
                "serie_id": serie_id,
                "occorrenza": f"{indice} di {totale}",
                "comune": riga["comune"],
                "comune_normalizzato": titolo_normalizzato(riga["comune"]),
                "luogo": riga["luogo"],
                "km": comune_riga["km"],
                "minuti": comune_riga["minuti"],
                "prezzo": None,
                "organizzatore": None,
                "url": None,
                "url_immagine": None,
                "confidenza": max(0, 90 + confidenza_penalita),
            }
        )
    return eventi
