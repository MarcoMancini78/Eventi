"""Autenticazione e creazione della struttura dei fogli Google (M0.5, 08.8).

Autenticazione: OAuth utente installato, non service account (il progetto
riusa il client OAuth ereditato dal tentativo precedente). Al primo utilizzo
si apre il browser per il consenso una tantum; il token ottenuto si salva in
`config/token.json` e viene riusato/rinnovato in automatico alle esecuzioni
successive, senza richiedere un nuovo login.

2026-09-07, richiesto dall'utente: un token scaduto/revocato lato Google
(RefreshError: 'invalid_grant') mandava in crash l'intero comando (es.
'run.py publish'), lasciando in `config/token.json` un token ormai inutile
che avrebbe fatto fallire allo stesso modo ogni tentativo successivo, non
solo quello in corso. Non è possibile automatizzare il consenso OAuth in
sé (richiede l'interazione umana nel browser, non aggirabile) — ma quando
il refresh fallisce, il token rotto viene ora archiviato (mai cancellato
in silenzio, 04.7: 'mai un dato perso senza traccia') e si ricade
automaticamente sul flusso di login pulito già previsto sotto, che riapre
il browser una volta sola invece di richiedere all'operatore un intervento
manuale separato (cancellare il file) prima di poter ritentare."""
from __future__ import annotations

import json
import logging
from datetime import datetime
from pathlib import Path

import gspread
from google.auth.exceptions import RefreshError
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow

from .config import Config

logger = logging.getLogger(__name__)

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive.file",
]


def _archivia_token_rotto(token_path: Path) -> None:
    """Rinomina il token scaduto/revocato invece di cancellarlo (04.7):
    resta ispezionabile per capire quando/perché è stato invalidato, ma
    non interferisce più con il prossimo tentativo di caricamento."""
    if not token_path.exists():
        return
    timestamp = datetime.now().strftime("%Y%m%dT%H%M%S")
    destinazione = token_path.with_name(f"{token_path.stem}.rotto-{timestamp}{token_path.suffix}")
    token_path.rename(destinazione)
    logger.warning("Token OAuth scaduto/revocato, archiviato in %s", destinazione)


def _load_user_credentials(config: Config) -> Credentials:
    token_path = Path(config.google_oauth_token_json)
    creds: Credentials | None = None

    if token_path.exists():
        creds = Credentials.from_authorized_user_file(str(token_path), SCOPES)

    if creds and creds.expired and creds.refresh_token:
        try:
            creds.refresh(Request())
        except RefreshError:
            _archivia_token_rotto(token_path)
            creds = None

    if not creds or not creds.valid:
        flow = InstalledAppFlow.from_client_secrets_file(config.google_oauth_client_json, SCOPES)
        creds = flow.run_local_server(port=0)

    token_path.parent.mkdir(parents=True, exist_ok=True)
    token_path.write_text(creds.to_json())
    return creds

# Spreadsheet -> fogli che contiene. Un solo file (2026-08-28, richiesta
# dell'utente): ai volumi attuali (683 comuni, poche migliaia di righe Fonti)
# la ripartizione su piu' spreadsheet prevista da 08.8 per scala 1000+ comuni
# non era ancora necessaria, e un file unico e' piu' semplice da navigare.
# I tre nomi logici (principale/anagrafiche/esteso) restano nel codice per
# compatibilita' con run.py/config.py, ma puntano tutti allo stesso file.
STRUTTURA = {
    "principale": [
        "Eventi", "Quarantena", "Log", "Serie", "Stato",
        "Newsletter", "CodaFollow", "Perimetro", "Fonti",
        "Archivio", "DaVerificare", "CoperturaComuni", "CoperturaAltreEntita",
    ],
    "anagrafiche": [],
    "esteso": [],
}

INTESTAZIONI = {
    "Eventi": [
        "id", "titolo", "descrizione", "tipologia", "data_inizio", "ora_inizio",
        "data_fine", "ora_fine", "serie_id", "occorrenza", "comune", "luogo",
        "km", "minuti", "prezzo", "organizzatore", "url", "url_immagine",
        "url_approfondimento", "fonti", "confidenza", "stato", "note",
        "primo_visto", "ultimo_visto", "bloccato", "soppressa",
        "data_post", "ora_post",
    ],
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
    "DaVerificare": [
        "source_id", "piattaforma", "handle", "url", "comune", "note",
    ],
    "CoperturaComuni": [
        "fascia", "comune", "sito_istituzionale", "fb_comune", "fb_proloco", "ig_proloco",
    ],
    "CoperturaAltreEntita": ["tipologia", "nome", "sito", "facebook", "instagram"],
    "Archivio": [
        "id", "titolo", "descrizione", "tipologia", "data_inizio", "data_fine",
        "comune", "luogo", "organizzatore", "url", "url_approfondimento",
        "fonti", "serie_id", "stato", "note", "data_post", "ora_post",
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
