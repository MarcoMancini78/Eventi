"""Autenticazione e creazione della struttura dei fogli Google (M0.5, 08.8).

Autenticazione: OAuth utente installato, non service account (il progetto
riusa il client OAuth ereditato dal tentativo precedente). Al primo utilizzo
si apre il browser per il consenso una tantum; il token ottenuto si salva in
`config/token.json` e viene riusato/rinnovato in automatico alle esecuzioni
successive, senza richiedere un nuovo login.
"""
from __future__ import annotations

import json
from pathlib import Path

import gspread
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow

from .config import Config

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive.file",
]


def _load_user_credentials(config: Config) -> Credentials:
    token_path = Path(config.google_oauth_token_json)
    creds: Credentials | None = None

    if token_path.exists():
        creds = Credentials.from_authorized_user_file(str(token_path), SCOPES)

    if creds and creds.expired and creds.refresh_token:
        creds.refresh(Request())

    if not creds or not creds.valid:
        flow = InstalledAppFlow.from_client_secrets_file(config.google_oauth_client_json, SCOPES)
        creds = flow.run_local_server(port=0)

    token_path.parent.mkdir(parents=True, exist_ok=True)
    token_path.write_text(creds.to_json())
    return creds

# Spreadsheet -> fogli che contiene (08.8: ripartizione obbligatoria a questa scala)
STRUTTURA = {
    "principale": ["Eventi", "Quarantena", "Config", "Tipologie", "Log", "Serie", "Stato", "Newsletter", "CodaFollow"],
    "anagrafiche": ["Perimetro", "Fonti"],
    "esteso": ["Eventi_estesi", "Archivio"],
}

INTESTAZIONI = {
    "Eventi": [
        "id", "titolo", "descrizione", "tipologia", "data_inizio", "ora_inizio",
        "data_fine", "ora_fine", "serie_id", "occorrenza", "comune", "luogo",
        "km", "minuti", "prezzo", "organizzatore", "url", "url_immagine",
        "fonti", "confidenza", "stato", "note", "primo_visto", "ultimo_visto",
        "bloccato", "soppressa",
    ],
    "Config": ["chiave", "valore", "descrizione"],
    "Tipologie": ["tipologia", "sinonimi", "attiva"],
    "Perimetro": ["comune", "alias", "provincia", "lat", "lon", "istat", "km", "minuti", "fascia", "attivo"],
    "Fonti": [
        "source_id", "soggetto", "categoria", "comune_riferimento", "fascia",
        "polling_diretto", "canale", "url", "handle", "seguito", "piattaforma",
        "metodo", "tier", "endpoint", "frequenza", "attivo", "stato", "priorita",
        "finestra_attenzione", "ultimo_run", "ultimo_esito", "primo_errore",
        "giorni_in_errore", "eventi_totali", "eventi_utili", "resa_annuale",
        "regime",
    ],
    "Log": [
        "run_id", "inizio", "fine", "durata_min", "fonti_tentate", "fonti_ok",
        "fonti_errore", "artefatti", "chiamate_llm", "eventi_nuovi",
        "eventi_aggiornati", "in_quarantena", "archiviati", "note",
    ],
    "Serie": [
        "serie_id", "titolo", "tipologia", "comune", "luogo", "rrule",
        "regola_leggibile", "valida_dal", "valida_al", "eccezioni",
        "ultima_conferma", "stato", "fonti", "bloccata",
    ],
    "Stato": ["indicatore", "valore", "semaforo"],
    "Newsletter": ["soggetto", "url_iscrizione", "stato"],
    "CodaFollow": [
        "source_id", "piattaforma", "handle", "url", "soggetto", "comune",
        "fascia", "priorita", "stato", "tentativi", "data_follow", "note",
    ],
    "Eventi_estesi": [
        "id", "titolo", "descrizione", "tipologia", "data_inizio", "ora_inizio",
        "data_fine", "ora_fine", "serie_id", "occorrenza", "comune", "luogo",
        "km", "minuti", "prezzo", "organizzatore", "url", "url_immagine",
        "fonti", "confidenza", "stato", "note", "primo_visto", "ultimo_visto",
        "bloccato", "soppressa",
    ],
    "Archivio": [
        "id", "titolo", "descrizione", "tipologia", "data_inizio", "data_fine",
        "comune", "luogo", "organizzatore", "url", "fonti", "serie_id",
        "stato", "note",
    ],
}


def get_client(config: Config) -> gspread.Client:
    creds = _load_user_credentials(config)
    return gspread.authorize(creds)


def crea_workbook(client: gspread.Client, titolo: str, fogli: list[str]) -> gspread.Spreadsheet:
    sh = client.create(titolo)
    # Il foglio di default va rinominato/rimosso solo dopo aver creato gli altri.
    primo = True
    for nome in fogli:
        intestazione = INTESTAZIONI.get(nome, [])
        if primo:
            ws = sh.sheet1
            ws.update_title(nome)
            primo = False
        else:
            ws = sh.add_worksheet(title=nome, rows=100, cols=max(len(intestazione), 10))
        if intestazione:
            ws.update([intestazione], value_input_option="USER_ENTERED")
    return sh


def init_workbooks(config: Config) -> dict[str, str]:
    """run.py init: crea i tre spreadsheet e restituisce i loro ID da salvare in .env."""
    client = get_client(config)
    ids = {}
    for nome_logico, fogli in STRUTTURA.items():
        sh = crea_workbook(client, f"Eventi Locali — {nome_logico}", fogli)
        ids[nome_logico] = sh.id
    return ids
