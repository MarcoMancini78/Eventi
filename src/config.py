"""Configurazione centrale. Nessun numero magico altrove nel codice (15.1.1).

I default qui sotto rispecchiano il foglio `Config` (03.1.6) e vengono
sovrascritti dai valori letti dal foglio a ogni run (registry.py).
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

ROOT_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT_DIR / "data"
DB_PATH = DATA_DIR / "eventi.db"

load_dotenv(ROOT_DIR / "config" / ".env")


@dataclass
class Config:
    # Geografia e perimetro (03.1.6, 07.5)
    casa_lat: float = 44.739837
    casa_lon: float = 8.227501
    soglia_fascia_a_km: float = 50.0
    soglia_fascia_b_km: float = 75.0
    soglia_fascia_c_km: float = 100.0
    raggio_max_km: float = 100.0

    # Vista e archiviazione (03.1.6)
    vista_principale_giorni: int = 21
    vista_principale_fasce: tuple[str, ...] = ("A", "B")
    giorni_archiviazione: int = 2
    limite_sanita_anni: int = 2

    # Ricorrenze (03.1.6, 07.9)
    orizzonte_espansione_giorni: int = 120
    serie_decadimento_da_verificare_giorni: int = 120
    serie_decadimento_sospesa_giorni: int = 400

    # Confidenza ed estrazione (06.6)
    soglia_confidenza: int = 70

    # Budget di run (08.1, 08.5)
    budget_run_minuti: int = 180
    budget_feed_minuti: int = 45
    budget_llm_giornaliero: int = 1200
    max_post_social: int = 15
    max_polling_diretto: int = 100

    # Follow (14.4)
    follow_per_lotto: int = 10
    follow_max_giornalieri: int = 40
    follow_pausa_min_sec: int = 25
    follow_pausa_max_sec: int = 70
    follow_intervallo_lotti_min: int = 45

    # Operatività (03.1.6)
    recupero_run_saltati: int = 1

    # Segreti e percorsi, da .env
    # Autenticazione Google via OAuth utente installato (non service account):
    # al primo run si apre il browser per il consenso, poi il token si
    # riusa da google_oauth_token_json senza richiedere login ogni volta.
    google_oauth_client_json: str = field(
        default_factory=lambda: os.getenv(
            "GOOGLE_OAUTH_CLIENT_JSON", str(ROOT_DIR / "config" / "credentials.json")
        )
    )
    google_oauth_token_json: str = field(
        default_factory=lambda: os.getenv(
            "GOOGLE_OAUTH_TOKEN_JSON", str(ROOT_DIR / "config" / "token.json")
        )
    )
    spreadsheet_id_principale: str = field(
        default_factory=lambda: os.getenv("GOOGLE_SPREADSHEET_ID_PRINCIPALE", "")
    )
    spreadsheet_id_anagrafiche: str = field(
        default_factory=lambda: os.getenv("GOOGLE_SPREADSHEET_ID_ANAGRAFICHE", "")
    )
    spreadsheet_id_esteso: str = field(
        default_factory=lambda: os.getenv("GOOGLE_SPREADSHEET_ID_ESTESO", "")
    )
    llm_api_key: str = field(default_factory=lambda: os.getenv("LLM_API_KEY", ""))
    llm_provider: str = field(default_factory=lambda: os.getenv("LLM_PROVIDER", ""))
    imap_host: str = field(default_factory=lambda: os.getenv("IMAP_HOST", ""))
    imap_user: str = field(default_factory=lambda: os.getenv("IMAP_USER", ""))
    imap_password: str = field(default_factory=lambda: os.getenv("IMAP_PASSWORD", ""))
    telegram_bot_token: str = field(
        default_factory=lambda: os.getenv("TELEGRAM_BOT_TOKEN", "")
    )


def load_config() -> Config:
    """Carica la configurazione di default. registry.py la aggiorna dal foglio `Config`."""
    return Config()
