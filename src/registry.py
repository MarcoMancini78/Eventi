"""Sincronizzazione Sheets -> SQLite per i fogli anagrafici (M0.3): Config, Perimetro, Fonti, Tipologie.

Sheets è l'interfaccia, mai la verità operativa (00-README §6). Ogni run
rilegge questi fogli e li scrive in SQLite; il resto del sistema lavora solo
su SQLite.
"""
from __future__ import annotations

import sqlite3
from dataclasses import fields

import gspread

from .config import Config


def _open_sheet(client: gspread.Client, spreadsheet_id: str, worksheet_name: str):
    sh = client.open_by_key(spreadsheet_id)
    return sh.worksheet(worksheet_name)


def sync_config(client: gspread.Client, config: Config) -> Config:
    """Legge il foglio `Config` (chiave, valore) e aggiorna i default in-place.

    Le chiavi sconosciute vengono ignorate: aggiungere un parametro nuovo
    richiede prima il campo in Config, poi la riga nel foglio (15.1 regola 1).
    """
    ws = _open_sheet(client, config.spreadsheet_id_principale, "Config")
    rows = ws.get_all_records()
    valid_fields = {f.name for f in fields(config)}
    for row in rows:
        chiave = row.get("chiave")
        valore = row.get("valore")
        if chiave not in valid_fields or valore in (None, ""):
            continue
        current = getattr(config, chiave)
        try:
            if isinstance(current, bool):
                setattr(config, chiave, str(valore).strip().lower() in ("si", "true", "1"))
            elif isinstance(current, int):
                setattr(config, chiave, int(valore))
            elif isinstance(current, float):
                setattr(config, chiave, float(str(valore).replace(",", ".")))
            else:
                setattr(config, chiave, valore)
        except (TypeError, ValueError):
            continue
    return config


def _decimal_virgola(valore: str) -> float:
    """Converte i decimali con virgola tra apici del workbook originale ("5,5" -> 5.5).

    Errore documentato in 15/M1: se non convertiti, producono distanze nulle
    in modo silenzioso.
    """
    if valore in (None, ""):
        return 0.0
    return float(str(valore).replace(",", "."))


def sync_perimetro(conn: sqlite3.Connection, client: gspread.Client, config: Config) -> int:
    ws = _open_sheet(client, config.spreadsheet_id_anagrafiche, "Perimetro")
    rows = ws.get_all_records()
    inseriti = 0
    for row in rows:
        km = _decimal_virgola(row.get("km") or row.get("DistanzaKm"))
        if km > config.raggio_max_km:
            continue
        if km <= config.soglia_fascia_a_km:
            fascia = "A"
        elif km <= config.soglia_fascia_b_km:
            fascia = "B"
        else:
            fascia = "C"
        conn.execute(
            """
            INSERT INTO comuni (istat, comune, alias, provincia, lat, lon, km, minuti, fascia, attivo)
            VALUES (:istat, :comune, :alias, :provincia, :lat, :lon, :km, :minuti, :fascia, :attivo)
            ON CONFLICT(istat) DO UPDATE SET
                comune=excluded.comune, alias=excluded.alias, provincia=excluded.provincia,
                lat=excluded.lat, lon=excluded.lon, km=excluded.km, minuti=excluded.minuti,
                fascia=excluded.fascia, attivo=excluded.attivo
            """,
            {
                "istat": row.get("istat") or row.get("CodiceISTAT") or row.get("IdComune"),
                "comune": row.get("comune") or row.get("Comune"),
                "alias": row.get("alias", ""),
                "provincia": row.get("provincia") or row.get("Provincia"),
                "lat": _decimal_virgola(row.get("lat") or row.get("Latitudine")),
                "lon": _decimal_virgola(row.get("lon") or row.get("Longitudine")),
                "km": km,
                "minuti": _decimal_virgola(row.get("minuti") or row.get("DurataStimataMinuti")),
                "fascia": row.get("fascia") or fascia,
                "attivo": row.get("attivo", "si") or "si",
            },
        )
        inseriti += 1
    conn.commit()
    return inseriti


def sync_fonti(conn: sqlite3.Connection, client: gspread.Client, config: Config) -> int:
    ws = _open_sheet(client, config.spreadsheet_id_anagrafiche, "Fonti")
    rows = ws.get_all_records()
    inseriti = 0
    for row in rows:
        source_id = row.get("source_id")
        if not source_id:
            continue
        conn.execute(
            """
            INSERT INTO sources (source_id, config_json, tier, endpoint, last_run, last_hash, consecutive_errors, stats_json)
            VALUES (:source_id, :config_json, :tier, :endpoint, NULL, NULL, 0, NULL)
            ON CONFLICT(source_id) DO UPDATE SET
                config_json=excluded.config_json, tier=excluded.tier, endpoint=excluded.endpoint
            """,
            {
                "source_id": source_id,
                "config_json": None,
                "tier": row.get("tier", "T3"),
                "endpoint": row.get("endpoint", ""),
            },
        )
        inseriti += 1
    conn.commit()
    return inseriti
