"""Foglio Stato (M11, 08-orchestrazione-operativita.md): cruscotto di salute
del sistema con 4 indicatori e semaforo verde/giallo/rosso, scelti
dall'utente (2026-08-27): fonti in errore/rotte, quota LLM residua, ultimo
run completato, eventi in quarantena da rivedere.

'Ultimo run' usa MAX(sources.last_run) come proxy: la tabella `runs` esiste
nello schema ma non è mai scritta da nessun comando (nessuna infrastruttura
di log strutturato per-run ancora costruita) — il proxy riflette comunque
fedelmente quando l'ultimo giro ha toccato l'ultima fonte, senza dover
costruire quell'infrastruttura solo per questo indicatore.
"""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import date, datetime, timedelta

SEMAFORO_VERDE = "verde"
SEMAFORO_GIALLO = "giallo"
SEMAFORO_ROSSO = "rosso"


@dataclass
class Indicatore:
    nome: str
    valore: str
    semaforo: str


def _indicatore_fonti_in_errore(conn: sqlite3.Connection) -> Indicatore:
    totale = conn.execute("SELECT COUNT(*) FROM sources WHERE tier IS NOT NULL").fetchone()[0]
    in_errore = conn.execute(
        "SELECT COUNT(*) FROM sources WHERE tier IS NOT NULL AND consecutive_errors > 0"
    ).fetchone()[0]
    rotte = conn.execute("SELECT COUNT(*) FROM sources WHERE stato = 'rotta'").fetchone()[0]

    quota = (in_errore / totale) if totale > 0 else 0.0
    if rotte > 0 or quota > 0.20:
        semaforo = SEMAFORO_ROSSO
    elif in_errore > 0:
        semaforo = SEMAFORO_GIALLO
    else:
        semaforo = SEMAFORO_VERDE

    return Indicatore(
        nome="Fonti in errore/rotte",
        valore=f"{in_errore} in errore, {rotte} rotte (su {totale})",
        semaforo=semaforo,
    )


def _indicatore_quota_llm(conn: sqlite3.Connection, budget_giornaliero: int, oggi: date | None = None) -> Indicatore:
    oggi = oggi or date.today()
    usate = conn.execute(
        "SELECT COUNT(*) FROM extractions WHERE date(created_at) = ?", (oggi.isoformat(),)
    ).fetchone()[0]

    percentuale = (usate / budget_giornaliero) if budget_giornaliero > 0 else 0.0
    # Soglie di 08.5: 70% e 85% degradano le estrazioni, 100% le ferma del tutto.
    if percentuale >= 0.85:
        semaforo = SEMAFORO_ROSSO
    elif percentuale >= 0.70:
        semaforo = SEMAFORO_GIALLO
    else:
        semaforo = SEMAFORO_VERDE

    return Indicatore(
        nome="Quota LLM residua",
        valore=f"{usate}/{budget_giornaliero} ({percentuale:.0%})",
        semaforo=semaforo,
    )


def _indicatore_ultimo_run(conn: sqlite3.Connection, adesso: datetime | None = None) -> Indicatore:
    adesso = adesso or datetime.now()
    riga = conn.execute("SELECT MAX(last_run) AS ultimo FROM sources WHERE tier IS NOT NULL").fetchone()
    ultimo = riga["ultimo"] if riga else None

    if not ultimo:
        return Indicatore(nome="Ultimo run completato", valore="mai eseguito", semaforo=SEMAFORO_ROSSO)

    eta = adesso - datetime.fromisoformat(ultimo)
    if eta > timedelta(days=2):
        semaforo = SEMAFORO_ROSSO
    elif eta > timedelta(hours=36):
        semaforo = SEMAFORO_GIALLO
    else:
        semaforo = SEMAFORO_VERDE

    return Indicatore(nome="Ultimo run completato", valore=ultimo, semaforo=semaforo)


def _indicatore_quarantena(conn: sqlite3.Connection) -> Indicatore:
    n = conn.execute(
        "SELECT COUNT(*) FROM events WHERE stato = 'quarantena' AND archiviato = 'no'"
    ).fetchone()[0]

    if n >= 30:
        semaforo = SEMAFORO_ROSSO
    elif n >= 10:
        semaforo = SEMAFORO_GIALLO
    else:
        semaforo = SEMAFORO_VERDE

    return Indicatore(nome="Eventi in quarantena da rivedere", valore=str(n), semaforo=semaforo)


def _indicatore_coda_follow(conn: sqlite3.Connection) -> Indicatore:
    """Richiesto dall'utente (2026-08-28): la coda non è ferma, il feed
    social e sync-seguiti continuano ad aggiungere candidati. 'da lavorare'
    conta solo gli stati che richiedono ancora un'azione (follow o verifica
    manuale) — non 'seguito'/'fallito'/'non_valido', già chiusi."""
    righe = conn.execute(
        "SELECT stato, COUNT(*) AS n FROM coda_follow "
        "WHERE stato IN ('da_seguire', 'candidato_da_feed', 'quarantena') GROUP BY stato"
    ).fetchall()
    conteggi = {r["stato"]: r["n"] for r in righe}
    totale = sum(conteggi.values())

    if totale >= 200:
        semaforo = SEMAFORO_ROSSO
    elif totale >= 50:
        semaforo = SEMAFORO_GIALLO
    else:
        semaforo = SEMAFORO_VERDE

    valore = (
        f"{totale} da lavorare "
        f"({conteggi.get('da_seguire', 0)} da seguire, "
        f"{conteggi.get('candidato_da_feed', 0)} candidati da feed, "
        f"{conteggi.get('quarantena', 0)} da verificare)"
    )
    return Indicatore(nome="Coda follow in attesa", valore=valore, semaforo=semaforo)


def calcola_indicatori(
    conn: sqlite3.Connection,
    budget_llm_giornaliero: int,
    oggi: date | None = None,
    adesso: datetime | None = None,
) -> list[Indicatore]:
    return [
        _indicatore_fonti_in_errore(conn),
        _indicatore_quota_llm(conn, budget_llm_giornaliero, oggi),
        _indicatore_ultimo_run(conn, adesso),
        _indicatore_quarantena(conn),
        _indicatore_coda_follow(conn),
    ]
