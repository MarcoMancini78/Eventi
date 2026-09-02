"""17.2.2: backup dello spreadsheet, con mock httpx (nessuna rete reale,
15.1 regola 8)."""
import sys
from datetime import date
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.drive_backup import _trova_o_crea_cartella, backup_spreadsheet


class _RispostaFinta:
    def __init__(self, status_code, dati):
        self.status_code = status_code
        self._dati = dati

    def json(self):
        return self._dati

    def raise_for_status(self):
        if self.status_code >= 400:
            raise Exception(f"HTTP {self.status_code}")


class _ClientFinto:
    def __init__(self, get_risposta, post_risposta=None):
        self._get_risposta = get_risposta
        self._post_risposta = post_risposta
        self.chiamate_get = []
        self.chiamate_post = []

    def __enter__(self):
        return self

    def __exit__(self, *a):
        pass

    def get(self, url, headers=None, params=None):
        self.chiamate_get.append((url, params))
        return self._get_risposta

    def post(self, url, headers=None, json=None):
        self.chiamate_post.append((url, json))
        return self._post_risposta


def test_trova_o_crea_cartella_riusa_esistente():
    risposta_get = _RispostaFinta(200, {"files": [{"id": "cartella-123", "name": "Eventi Locali — Backup"}]})
    client_finto = _ClientFinto(risposta_get)

    with patch("src.drive_backup.httpx.Client", return_value=client_finto):
        cartella_id = _trova_o_crea_cartella("token-finto", "Eventi Locali — Backup")

    assert cartella_id == "cartella-123"
    assert len(client_finto.chiamate_post) == 0  # non ricreata se esiste già


def test_trova_o_crea_cartella_la_crea_se_assente():
    risposta_get = _RispostaFinta(200, {"files": []})
    risposta_post = _RispostaFinta(200, {"id": "cartella-nuova-456"})
    client_finto = _ClientFinto(risposta_get, risposta_post)

    with patch("src.drive_backup.httpx.Client", return_value=client_finto):
        cartella_id = _trova_o_crea_cartella("token-finto", "Eventi Locali — Backup")

    assert cartella_id == "cartella-nuova-456"
    assert len(client_finto.chiamate_post) == 1


class _HttpClientFinto:
    def __init__(self, token):
        self.auth = type("Auth", (), {"token": token})()


class _GspreadClientFinto:
    def __init__(self, token):
        self.http_client = _HttpClientFinto(token)
        self.chiamate_copy = []

    def copy(self, file_id, title=None, copy_permissions=False, folder_id=None, copy_comments=True):
        self.chiamate_copy.append(
            {"file_id": file_id, "title": title, "folder_id": folder_id, "copy_permissions": copy_permissions}
        )
        return type("Copia", (), {"id": "backup-id-789"})()


def test_backup_spreadsheet_usa_nome_con_data_e_cartella_dedicata():
    risposta_get = _RispostaFinta(200, {"files": [{"id": "cartella-123"}]})
    client_http_finto = _ClientFinto(risposta_get)
    gspread_finto = _GspreadClientFinto(token="token-finto")

    with patch("src.drive_backup.httpx.Client", return_value=client_http_finto):
        backup_id = backup_spreadsheet(gspread_finto, "spreadsheet-originale-id", oggi=date(2026, 9, 1))

    assert backup_id == "backup-id-789"
    assert len(gspread_finto.chiamate_copy) == 1
    chiamata = gspread_finto.chiamate_copy[0]
    assert chiamata["file_id"] == "spreadsheet-originale-id"
    assert chiamata["title"] == "Backup 2026-09-01"
    assert chiamata["folder_id"] == "cartella-123"
    assert chiamata["copy_permissions"] is False
