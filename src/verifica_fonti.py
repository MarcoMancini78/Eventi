"""16.10 — Verifica di disponibilità delle fonti social (caso Canelli, 2026-09-17).

Segnalato dall'utente: la pagina Facebook del Teatro Balbi di Canelli
(teatrobalbocanelli) non è visibile/disponibile, ma la fonte resta seguita
in `coda_follow` — inutile, va rimossa. Da qui due esigenze distinte:

1. **Audit una tantum**: tra le fonti social con 0 eventi mai prodotti,
   quali altre mostrano lo stesso segnale di "contenuto non disponibile"
   (non solo "silenziosa", che è normale — vedi 04.7)?
2. **Controllo all'ingresso**: quando una fonte social nuova viene importata
   (follow, sync_seguiti), verificare se il contenuto è già bloccato e, in
   quel caso, rifiutarla subito invece di seguirla a vuoto.

Verifica fatta con la sessione browser già autenticata (stessa identità di
`follow.py`/`sync_seguiti.py`), mai con un fetch anonimo: una pagina privata
o soggetta a restrizioni regionali risulterebbe indistinguibile da una
davvero rimossa se aperta senza login, producendo falsi positivi di massa
(15.1 — mai un giudizio che non regge a un secondo sguardo).
"""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path

from .config import Config

# Testi mostrati da Facebook/Instagram quando il contenuto non esiste più o
# non è raggiungibile per l'account che lo guarda (pagina rimossa, violazione
# standard della community, non disponibile nella tua zona, ecc.) — verificato
# dal vivo sul caso Canelli. Cercati nel testo VISIBILE (inner_text), stesso
# principio anti-falso-positivo di follow._SEGNALI_BLOCCO (14.5): l'HTML
# grezzo contiene spesso questi stessi testi in blocchi nascosti/template.
SEGNALI_CONTENUTO_INDISPONIBILE = (
    "questo contenuto non è al momento disponibile",
    "questo contenuto non è disponibile",
    "this content isn't available",
    "content isn't available right now",
    "la pagina che hai richiesto non è disponibile",
    "sorry, this page isn't available",
    "the link you followed may be broken",
    "sorry, this content isn't available right now",
)


@dataclass
class EsitoVerifica:
    source_id: str
    url: str
    disponibile: bool
    dettaglio: str = ""


def classifica_testo_pagina(testo_visibile: str) -> tuple[bool, str]:
    """Funzione pura (testabile senza browser): dato il testo visibile di una
    pagina già caricata, dice se il contenuto risulta disponibile.

    Ritorna (disponibile, dettaglio) — dettaglio vuoto se disponibile,
    altrimenti il segnale che ha fatto scattare il giudizio.
    """
    testo_normalizzato = (testo_visibile or "").lower()
    for segnale in SEGNALI_CONTENUTO_INDISPONIBILE:
        if segnale in testo_normalizzato:
            return False, f"contenuto non disponibile: '{segnale}'"
    return True, ""


def fonti_social_da_verificare(conn: sqlite3.Connection, solo_senza_eventi: bool = True) -> list[sqlite3.Row]:
    """Candidate all'audit: fonti social seguite con URL valorizzato.

    `solo_senza_eventi` (default) restringe a quelle che non hanno mai
    prodotto un evento (0 nel totale storico) — sono le uniche su cui il
    sospetto "forse è bloccata" ha senso: una fonte che produce eventi è
    per definizione raggiungibile. Verificare anche quelle produttive
    sarebbe lavoro sprecato e rischio inutile sulla sessione autenticata.
    """
    righe = conn.execute(
        "SELECT rowid, * FROM coda_follow "
        "WHERE stato = 'seguito' AND url IS NOT NULL AND url != '' AND piattaforma = 'facebook'"
    ).fetchall()

    if not solo_senza_eventi:
        return righe

    conteggi_totale: dict[str, int] = {}
    for r in conn.execute(
        "SELECT source_id, COUNT(*) AS totale FROM event_sources GROUP BY source_id"
    ).fetchall():
        conteggi_totale[r["source_id"]] = r["totale"]

    def senza_eventi(riga: sqlite3.Row) -> bool:
        source_id_conteggio = f"feed-{riga['piattaforma']}-{riga['handle']}" if riga["handle"] else ""
        return conteggi_totale.get(source_id_conteggio, 0) == 0

    return [r for r in righe if senza_eventi(r)]


def registra_esito_verifica(conn: sqlite3.Connection, candidato: sqlite3.Row, esito: EsitoVerifica) -> None:
    """Se il contenuto risulta indisponibile, marca la fonte 'non_valido'
    (stesso stato già usato da follow.py per un handle scartato, 04.8-simile)
    così esce dalla coda seguita senza essere mai più riproposta a un lotto
    di follow — mai una cancellazione fisica della riga (03.1: tutto resta
    ispezionabile e correggibile a mano)."""
    if esito.disponibile:
        return
    conn.execute(
        "UPDATE coda_follow SET stato = 'non_valido', note = ? WHERE rowid = ?",
        (esito.dettaglio, candidato["rowid"]),
    )
    conn.commit()


# --- Interazione browser reale: isolata qui, mai chiamata dai test automatici ---

def verifica_disponibilita_url(pagina, url: str) -> tuple[bool, str]:
    """Apre `url` con una pagina Playwright già autenticata e classifica il
    contenuto. Nessuna azione (sola lettura, 14.5b)."""
    try:
        pagina.goto(url, timeout=20000)
        pagina.wait_for_timeout(1500)
        testo_visibile = pagina.inner_text("body")
    except Exception as exc:
        # Un errore di navigazione (timeout, DNS) non è un segnale di
        # "contenuto rimosso": è un problema transitorio o di rete, va
        # lasciato al retry normale delle fonti, non marcato non_valido.
        return True, f"verifica non conclusiva: {exc}"
    disponibile, dettaglio = classifica_testo_pagina(testo_visibile)
    return disponibile, dettaglio


def verifica_lotto_facebook(
    conn: sqlite3.Connection,
    config: Config,
    candidati: list[sqlite3.Row],
    sessione_dir: Path | None = None,
) -> list[EsitoVerifica]:
    """Verifica un lotto di fonti Facebook con la sessione autenticata già
    usata per il follow (stesso profilo Chromium salvato, nessun nuovo
    login). Sola lettura: mai un click, mai un'azione sull'account."""
    from .follow import _apri_sessione_browser, _assicura_identita_pagina, _chiudi_sessione_browser

    if not candidati:
        return []

    esiti: list[EsitoVerifica] = []
    contesto = _apri_sessione_browser("facebook", sessione_dir, config.browser_visibile)
    try:
        _assicura_identita_pagina(contesto, config)
        for candidato in candidati:
            pagina = contesto["browser"].new_page()
            try:
                disponibile, dettaglio = verifica_disponibilita_url(pagina, candidato["url"])
            finally:
                pagina.close()
            esito = EsitoVerifica(candidato["source_id"], candidato["url"], disponibile, dettaglio)
            registra_esito_verifica(conn, candidato, esito)
            esiti.append(esito)
    finally:
        _chiudi_sessione_browser(contesto)

    return esiti
