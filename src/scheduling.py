"""Coda a priorità dinamica per il giro multi-fonte (M11, 08.3).

Formula da 08-orchestrazione-operativita.md §8.3 (non indovinata):

    punteggio = (5 - fascia) * 25       # A=100, B=75, C=50, D=25 - dominante
              + resa_storica * 20       # eventi_utili / minuti_spesi
              + giorni_da_ultimo_run * 3
              + bonus_stagionale
              - penalita_errori         # 5 * errori_consecutivi
              - costo_stimato_minuti

bonus_stagionale e costo_stimato_minuti non hanno ancora una fonte di dati
reale nel sistema (nessuna stagionalità storica accumulata, nessuna stima
di durata per fonte) — restano a 0 finché non c'è un dato concreto da cui
calcolarli, coerente con "vuoto non è un errore" (04.7): un valore
indovinato sarebbe peggio di ometterlo.

Soglia minima proposta per attivare bonus_stagionale/finestra_attenzione
(decisione dell'utente 2026-08-27: "proponi tu una soglia"), non ancora
implementata perché nessuna fonte ha oggi eventi storici abbastanza vecchi
da confrontare: attivare il termine solo quando esiste, per la stessa
fonte/comune, almeno un evento con `data_inizio` di ≥300 giorni fa (un
ciclo stagionale quasi completo, tollerante a piccoli slittamenti di data
da un anno all'altro). Sotto quella soglia il confronto anno-su-anno
sarebbe rumore statistico su 0-1 osservazioni, peggio di ometterlo.
"""
from __future__ import annotations

import sqlite3
from datetime import date, datetime

_PUNTI_FASCIA = {"A": 100, "B": 75, "C": 50, "D": 25}


def calcola_priorita(
    fascia: str | None,
    eventi_totali: int,
    eventi_utili: int,
    minuti_spesi: float,
    last_run: str | None,
    consecutive_errors: int,
    oggi: date | None = None,
) -> float:
    """Punteggio di priorità dinamica per una fonte (08.3). Più alto = prima."""
    oggi = oggi or date.today()

    punteggio_fascia = _PUNTI_FASCIA.get(fascia, 0)

    # resa_storica = eventi_utili / minuti_spesi: senza tempo speso misurato
    # (fonte mai processata, o costo non tracciato) non si divide per zero
    # né si inventa una resa — resta 0, la fonte parte dalla sola fascia.
    resa_storica = (eventi_utili / minuti_spesi) if minuti_spesi > 0 else 0.0

    if last_run:
        giorni_da_ultimo_run = (oggi - datetime.fromisoformat(last_run).date()).days
    else:
        # Mai processata: bonus_novità implicito, va in cima come una fonte
        # ferma da molto tempo (08.3: "il termine non ha tetto").
        giorni_da_ultimo_run = 365

    penalita_errori = 5 * max(consecutive_errors, 0)

    return (
        punteggio_fascia
        + resa_storica * 20
        + giorni_da_ultimo_run * 3
        - penalita_errori
    )


def fascia_da_source_id(conn: sqlite3.Connection, source_id: str) -> str | None:
    """Risolve la fascia dal nome del comune incorporato nel source_id
    (pattern 'comune-{nome-con-trattini}', coerente con run.py import-fonti)
    — le fonti che non seguono questo pattern (Pro Loco, aggregatori, feed
    social) restano senza fascia, trattate come non dominanti ma non
    escluse. Usata sia per la coda a priorità (sotto) sia per la
    degradazione della quota LLM (08.5, extractor/client.py)."""
    if not source_id.startswith("comune-"):
        return None
    riga = conn.execute(
        "SELECT fascia FROM comuni WHERE attivo='si' AND LOWER(REPLACE(comune, ' ', '-')) = ?",
        (source_id[len("comune-"):],),
    ).fetchone()
    return riga["fascia"] if riga else None


def ordina_fonti_per_priorita(
    conn: sqlite3.Connection, righe: list[sqlite3.Row], oggi: date | None = None
) -> list[sqlite3.Row]:
    """Ordina le righe di `sources` (già filtrate su tier IS NOT NULL) per
    priorità dinamica decrescente."""
    fasce_per_comune = {
        r["comune"].strip().lower().replace(" ", "-"): r["fascia"]
        for r in conn.execute("SELECT comune, fascia FROM comuni WHERE attivo='si'").fetchall()
    }

    def fascia_di(source_id: str) -> str | None:
        if not source_id.startswith("comune-"):
            return None
        return fasce_per_comune.get(source_id[len("comune-"):])

    def punteggio(riga: sqlite3.Row) -> float:
        return calcola_priorita(
            fascia=fascia_di(riga["source_id"]),
            eventi_totali=riga["eventi_totali"] or 0,
            eventi_utili=riga["eventi_utili"] or 0,
            minuti_spesi=0.0,  # nessun costo per-fonte ancora misurato, vedi docstring del modulo
            last_run=riga["last_run"],
            consecutive_errors=riga["consecutive_errors"] or 0,
            oggi=oggi,
        )

    return sorted(righe, key=punteggio, reverse=True)
