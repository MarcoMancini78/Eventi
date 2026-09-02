"""Backup dello spreadsheet principale (17.2.2, richiesto dall'utente
2026-09-01): mitiga il rischio "foglio corrotto da un bug di publish"
([11.1](../../Documentazione/11-rischi-decisioni.md)), esplicitamente
accettato in documentazione ma mai mitigato in codice fino ad ora.

Nessuna nuova dipendenza: la ricerca/creazione della cartella Drive usa
l'API REST direttamente con httpx (stesso token OAuth già caricato da
sheets_client), la copia dello spreadsheet usa gspread.Client.copy (già
disponibile, nessuna chiamata REST manuale necessaria per quella parte).
"""
from __future__ import annotations

from datetime import date

import httpx

_TIMEOUT_SECONDI = 15
_NOME_CARTELLA = "Eventi Locali — Backup"
_DRIVE_FILES_URL = "https://www.googleapis.com/drive/v3/files"


def _trova_o_crea_cartella(token: str, nome: str) -> str:
    """Cerca una cartella con questo nome (tra quelle create/accessibili
    dall'app, coerente con lo scope drive.file già in uso); la crea se non
    esiste. Ritorna l'id della cartella."""
    headers = {"Authorization": f"Bearer {token}"}
    query = f"name = '{nome}' and mimeType = 'application/vnd.google-apps.folder' and trashed = false"
    with httpx.Client(timeout=_TIMEOUT_SECONDI) as client:
        risposta = client.get(_DRIVE_FILES_URL, headers=headers, params={"q": query, "fields": "files(id,name)"})
        risposta.raise_for_status()
        trovate = risposta.json().get("files", [])
        if trovate:
            return trovate[0]["id"]

        risposta = client.post(
            _DRIVE_FILES_URL,
            headers=headers,
            json={"name": nome, "mimeType": "application/vnd.google-apps.folder"},
        )
        risposta.raise_for_status()
        return risposta.json()["id"]


def backup_spreadsheet(client, spreadsheet_id: str, oggi: date | None = None) -> str:
    """Copia lo spreadsheet nella cartella dedicata di backup, con il nome
    che porta la data (17.2.2). Nessuna cancellazione automatica delle
    copie vecchie (deciso con l'utente): l'operatore ripulisce a mano
    quando vuole. Ritorna l'id del nuovo file copiato.

    `client` è un gspread.Client già autenticato (sheets_client.get_client).
    """
    oggi = oggi or date.today()
    # gspread.Client non espone le credenziali direttamente (verificato:
    # nessun attributo 'auth' su Client, solo su Client.http_client — non
    # documentato pubblicamente, trovato ispezionando l'oggetto dal vivo).
    token = client.http_client.auth.token
    cartella_id = _trova_o_crea_cartella(token, _NOME_CARTELLA)

    titolo_backup = f"Backup {oggi.isoformat()}"
    copia = client.copy(spreadsheet_id, title=titolo_backup, folder_id=cartella_id, copy_permissions=False)
    return copia.id
