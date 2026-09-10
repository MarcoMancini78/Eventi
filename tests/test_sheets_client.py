"""2026-09-07: gestione automatica del token OAuth scaduto/revocato
(RefreshError) — un token rotto va archiviato, mai lasciato lì a far
fallire ogni tentativo successivo, e si ricade sul flusso di login pulito
nella stessa esecuzione invece di richiedere un intervento manuale."""
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from google.auth.exceptions import RefreshError

from src import sheets_client
from src.config import Config


def _config_di_prova(tmp_path: Path) -> Config:
    config = Config()
    config.google_oauth_token_json = str(tmp_path / "token.json")
    config.google_oauth_client_json = str(tmp_path / "client.json")
    return config


def test_token_scaduto_con_refresh_error_viene_archiviato_non_cancellato(tmp_path):
    token_path = tmp_path / "token.json"
    token_path.write_text('{"token": "vecchio", "refresh_token": "rt"}')
    config = _config_di_prova(tmp_path)

    creds_scaduti = MagicMock(expired=True, refresh_token="rt", valid=False)
    creds_scaduti.refresh.side_effect = RefreshError("invalid_grant: Token has been expired or revoked.")

    creds_nuovi = MagicMock(valid=True)
    creds_nuovi.to_json.return_value = "{}"

    with patch("src.sheets_client.Credentials.from_authorized_user_file", return_value=creds_scaduti), \
         patch("src.sheets_client.InstalledAppFlow.from_client_secrets_file") as flow_cls:
        flow_cls.return_value.run_local_server.return_value = creds_nuovi
        sheets_client._load_user_credentials(config)

    # Il token rotto è stato rinominato (mai cancellato in silenzio) — al
    # path originale c'è ora il NUOVO token dal login pulito, non più il
    # vecchio (verificato sotto sul contenuto archiviato).
    assert token_path.read_text() == "{}"
    archiviati = list(tmp_path.glob("token.rotto-*.json"))
    assert len(archiviati) == 1
    assert archiviati[0].read_text() == '{"token": "vecchio", "refresh_token": "rt"}'

    # ...e il flusso di login pulito è stato invocato nella stessa esecuzione,
    # senza richiedere un secondo comando manuale.
    flow_cls.return_value.run_local_server.assert_called_once()


def test_token_valido_non_tocca_il_flusso_di_login(tmp_path):
    token_path = tmp_path / "token.json"
    token_path.write_text('{"token": "valido"}')
    config = _config_di_prova(tmp_path)

    creds_validi = MagicMock(expired=False, valid=True)
    creds_validi.to_json.return_value = "{}"

    with patch("src.sheets_client.Credentials.from_authorized_user_file", return_value=creds_validi), \
         patch("src.sheets_client.InstalledAppFlow.from_client_secrets_file") as flow_cls:
        sheets_client._load_user_credentials(config)

    flow_cls.assert_not_called()
