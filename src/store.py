"""Accesso a SQLite: verità operativa del sistema (03.2). Sheets è solo la vista."""
from __future__ import annotations

import sqlite3
from pathlib import Path

SCHEMA_VERSION = 1

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS schema_version (
    version INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS comuni (
    istat TEXT PRIMARY KEY,
    comune TEXT NOT NULL,
    alias TEXT,
    provincia TEXT,
    lat REAL,
    lon REAL,
    km REAL,
    minuti REAL,
    fascia TEXT,
    attivo TEXT DEFAULT 'si'
);

CREATE TABLE IF NOT EXISTS sources (
    source_id TEXT PRIMARY KEY,
    config_json TEXT,
    tier TEXT,
    endpoint TEXT,
    last_run TEXT,
    last_hash TEXT,
    consecutive_errors INTEGER DEFAULT 0,
    stats_json TEXT,
    piattaforma TEXT  -- famiglia di CMS rilevata dal fingerprinting (M8, 12.5)
);

CREATE TABLE IF NOT EXISTS artifacts (
    artifact_id TEXT PRIMARY KEY,
    source_id TEXT NOT NULL,
    url TEXT,
    fetched_at TEXT,
    kind TEXT,
    text TEXT,
    context_date TEXT,
    raw_hash TEXT,
    image_paths_json TEXT,
    processed_at TEXT,
    FOREIGN KEY (source_id) REFERENCES sources (source_id)
);

CREATE TABLE IF NOT EXISTS image_cache (
    phash TEXT PRIMARY KEY,
    first_seen TEXT,
    extraction_json TEXT,
    model_used TEXT,
    cost_tokens INTEGER
);

CREATE TABLE IF NOT EXISTS extractions (
    extraction_id TEXT PRIMARY KEY,
    artifact_id TEXT NOT NULL,
    model TEXT,
    prompt_version TEXT,
    raw_output TEXT,
    parsed_json TEXT,
    confidence INTEGER,
    created_at TEXT,
    FOREIGN KEY (artifact_id) REFERENCES artifacts (artifact_id)
);

CREATE TABLE IF NOT EXISTS series (
    serie_id TEXT PRIMARY KEY,
    titolo TEXT,
    tipologia TEXT,
    comune TEXT,
    luogo TEXT,
    rrule TEXT,
    regola_leggibile TEXT,
    valida_dal TEXT,
    valida_al TEXT,
    eccezioni TEXT,
    ultima_conferma TEXT,
    stato TEXT DEFAULT 'attiva',
    fonti TEXT,
    bloccata TEXT DEFAULT 'no'
);

CREATE TABLE IF NOT EXISTS events (
    event_id TEXT PRIMARY KEY,
    dedup_key TEXT,
    titolo TEXT,
    descrizione TEXT,
    tipologia TEXT,
    data_inizio TEXT,
    ora_inizio TEXT,
    data_fine TEXT,
    ora_fine TEXT,
    serie_id TEXT,
    occorrenza TEXT,
    comune TEXT,
    luogo TEXT,
    km REAL,
    minuti REAL,
    prezzo TEXT,
    organizzatore TEXT,
    url TEXT,
    url_immagine TEXT,
    confidenza INTEGER,
    stato TEXT DEFAULT 'nuovo',
    note TEXT,
    primo_visto TEXT,
    ultimo_visto TEXT,
    bloccato TEXT DEFAULT 'no',
    soppressa TEXT DEFAULT 'no',
    manual_overrides_json TEXT,
    archiviato TEXT DEFAULT 'no'
);

CREATE TABLE IF NOT EXISTS event_sources (
    event_id TEXT NOT NULL,
    source_id TEXT NOT NULL,
    url TEXT,
    seen_at TEXT,
    PRIMARY KEY (event_id, source_id)
);

CREATE TABLE IF NOT EXISTS runs (
    run_id TEXT PRIMARY KEY,
    tipo TEXT,
    inizio TEXT,
    fine TEXT,
    durata_min REAL,
    fonti_tentate INTEGER,
    fonti_ok INTEGER,
    fonti_errore INTEGER,
    artefatti INTEGER,
    chiamate_llm INTEGER,
    eventi_nuovi INTEGER,
    eventi_aggiornati INTEGER,
    in_quarantena INTEGER,
    archiviati INTEGER,
    note TEXT
);

-- M9 (14.4): coda di follow semiautomatica per i due account social dedicati.
CREATE TABLE IF NOT EXISTS coda_follow (
    source_id TEXT NOT NULL,
    piattaforma TEXT NOT NULL,
    handle TEXT,
    url TEXT,
    soggetto TEXT,
    comune TEXT,
    fascia TEXT,
    categoria TEXT,
    stato TEXT DEFAULT 'da_seguire',
    tentativi INTEGER DEFAULT 0,
    data_follow TEXT,
    note TEXT,
    PRIMARY KEY (source_id, piattaforma)
);

-- Log storico di ogni tentativo di follow, indipendente dallo stato corrente
-- in coda_follow: serve per il conteggio giornaliero (14.4, 14.5).
CREATE TABLE IF NOT EXISTS coda_follow_log (
    log_id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_id TEXT,
    piattaforma TEXT,
    esito TEXT,
    data_follow TEXT
);

-- Stato minimo persistente per il circuito di sicurezza (14.5) e l'orario
-- dell'ultimo lotto (14.4: intervallo minimo tra due lotti).
CREATE TABLE IF NOT EXISTS app_state (
    chiave TEXT PRIMARY KEY,
    valore TEXT
);
"""


def connect(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def migrate(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA_SQL)
    row = conn.execute("SELECT version FROM schema_version").fetchone()
    if row is None:
        conn.execute("INSERT INTO schema_version (version) VALUES (?)", (SCHEMA_VERSION,))
        conn.commit()
