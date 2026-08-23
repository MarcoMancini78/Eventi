"""M9 — Sincronizzazione della lista 'seguiti' reale con coda_follow.

Lettura passiva, non un'azione (14.5b: "la lettura passiva è molto meno
rilevabile dell'azione"). Sostituisce il riportare a mano in chat ogni
follow fatto dall'app: si legge la lista vera direttamente dalla
piattaforma e si allinea coda_follow di conseguenza.

Comportamento sulle voci sconosciute (non in coda_follow): non si scartano
mai (04.7 — principio generale del progetto, mai silenzioso). Diventano
candidati in quarantena con comune da verificare a mano, non seguiti
automaticamente da nessun lotto finché qualcuno non conferma il comune.
"""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from .follow import _apri_sessione_browser, _assicura_identita_pagina, _chiudi_sessione_browser
from .config import Config


@dataclass
class EsitoSync:
    aggiornati: int  # handle già in coda_follow, marcati 'seguito'
    nuovi: int  # handle non censiti, aggiunti in quarantena
    handle_letti: int  # totale handle raccolti dalla piattaforma


def confronta_e_aggiorna(conn: sqlite3.Connection, piattaforma: str, handle_seguiti: list[str]) -> EsitoSync:
    """Funzione pura (testabile senza browser): dato l'elenco reale degli
    handle seguiti, allinea coda_follow.

    - handle già presenti in coda_follow, in qualunque stato diverso da
      'seguito' -> marcati 'seguito' con data_follow di oggi
    - handle non presenti -> nuova riga in quarantena, comune vuoto (da
      verificare a mano prima che diventi una fonte attiva)
    """
    oggi = datetime.now().isoformat()
    handle_normalizzati = {h.strip().lower().lstrip("@") for h in handle_seguiti if h.strip()}

    esistenti = conn.execute(
        "SELECT source_id, handle FROM coda_follow WHERE piattaforma = ?", (piattaforma,)
    ).fetchall()
    handle_a_source_id = {r["handle"].lower(): r["source_id"] for r in esistenti if r["handle"]}

    aggiornati = 0
    nuovi = 0

    for handle in handle_normalizzati:
        if handle in handle_a_source_id:
            cur = conn.execute(
                "UPDATE coda_follow SET stato='seguito', data_follow=? WHERE piattaforma=? AND handle=? AND stato != 'seguito'",
                (oggi, piattaforma, handle),
            )
            if cur.rowcount > 0:
                aggiornati += 1
        else:
            source_id = f"sconosciuto-{piattaforma}-{handle}"
            conn.execute(
                """
                INSERT INTO coda_follow (source_id, piattaforma, handle, url, soggetto, comune, fascia, categoria, stato, data_follow, note)
                VALUES (?, ?, ?, ?, ?, '', '', 'sconosciuto', 'quarantena', ?, 'trovato nella lista seguiti, comune da verificare')
                ON CONFLICT(source_id, piattaforma) DO NOTHING
                """,
                (source_id, piattaforma, handle, _url_da_handle(piattaforma, handle), handle, oggi),
            )
            if conn.execute("SELECT changes()").fetchone()[0] > 0:
                nuovi += 1

    conn.commit()
    return EsitoSync(aggiornati=aggiornati, nuovi=nuovi, handle_letti=len(handle_normalizzati))


def _url_da_handle(piattaforma: str, handle: str) -> str:
    if piattaforma == "instagram":
        return f"https://www.instagram.com/{handle}"
    return f"https://www.facebook.com/{handle}"


# --- Interazione browser reale: isolata qui, mai chiamata dai test automatici ---

def leggi_seguiti_reali(piattaforma: str, config: Config, sessione_dir: Path | None = None) -> list[str]:
    """Apre il browser con la sessione salvata, naviga alla lista 'seguiti'
    e scrolla fino in fondo raccogliendo gli handle. Nessuna azione:
    solo lettura, coerente con 14.5b.
    """
    contesto = _apri_sessione_browser(piattaforma, sessione_dir)
    try:
        if piattaforma == "facebook":
            _assicura_identita_pagina(contesto, config)
            return _leggi_seguiti_facebook(contesto, config)
        return _leggi_seguiti_instagram(contesto)
    finally:
        _chiudi_sessione_browser(contesto)


def _scroll_e_raccogli(pagina, selettore_link: str, max_scroll: int = 40, pausa_ms: int = 800) -> set[str]:
    """Scroll incrementale della pagina raccogliendo href che matchano il
    selettore, fino a quando due scroll consecutivi non aggiungono nulla
    (fine lista) o si raggiunge max_scroll (circuit-breaker anti-loop)."""
    handle_trovati: set[str] = set()
    altezza_precedente = -1

    for _ in range(max_scroll):
        elementi = pagina.query_selector_all(selettore_link)
        for el in elementi:
            href = el.get_attribute("href") or ""
            handle = href.strip("/").split("/")[-1] if href else ""
            if handle:
                handle_trovati.add(handle)

        pagina.mouse.wheel(0, 2000)
        pagina.wait_for_timeout(pausa_ms)

        altezza_corrente = pagina.evaluate("document.body.scrollHeight")
        if altezza_corrente == altezza_precedente:
            break
        altezza_precedente = altezza_corrente

    return handle_trovati


def _leggi_seguiti_instagram(contesto: dict) -> list[str]:
    """URL confermato dall'utente ispezionando l'interfaccia reale:
    instagram.com/?variant=following mostra direttamente la lista dei
    seguiti del profilo attivo, senza bisogno di conoscere lo username
    (i due tentativi precedenti, basati su ipotesi sul testo dei bottoni,
    erano entrambi sbagliati)."""
    pagina = contesto["browser"].new_page()
    try:
        pagina.goto("https://www.instagram.com/?variant=following", timeout=20000)
        pagina.wait_for_timeout(2000)

        return sorted(_scroll_e_raccogli(pagina, "a[href^='/'][role='link']"))
    finally:
        pagina.close()


def _aggiungi_parametro_query(url: str, chiave: str, valore: str) -> str:
    separatore = "&" if "?" in url else "?"
    return f"{url}{separatore}{chiave}={valore}"


def _leggi_seguiti_facebook(contesto: dict, config: Config) -> list[str]:
    """URL confermato dall'utente ispezionando l'interfaccia reale:
    aggiungere &sk=following (o ?sk=following) all'URL della Pagina mostra
    la lista di pagine seguite. Il tentativo precedente (/pages_followed_by)
    era un path inesistente per questa Pagina/versione dell'interfaccia."""
    pagina = contesto["browser"].new_page()
    try:
        url_seguiti = _aggiungi_parametro_query(config.facebook_page_url, "sk", "following")
        pagina.goto(url_seguiti, timeout=20000)
        pagina.wait_for_timeout(1500)

        return sorted(_scroll_e_raccogli(pagina, "a[href*='facebook.com/'][role='link']"))
    finally:
        pagina.close()
