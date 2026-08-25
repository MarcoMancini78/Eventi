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

    # Controllo di sanità 06.8: sopra questa soglia di eventi estratti da un
    # solo artefatto, l'intera risposta è scartata come probabile
    # allucinazione. Bug reale osservato (2026-08-25): un vero cartellone
    # teatrale stagionale (46 spettacoli reali e plausibili in un'unica
    # pagina) veniva scartato interamente col valore precedente (20) — non
    # un'allucinazione, solo un artefatto con molti eventi legittimi.
    max_eventi_per_artefatto: int = 60

    # Budget di run (08.1, 08.5)
    budget_run_minuti: int = 180
    budget_feed_minuti: int = 45
    budget_llm_giornaliero: int = 1200
    max_post_social: int = 15
    max_polling_diretto: int = 100

    # Follow (14.4). Default doc: 40/giorno; l'utente ha chiesto 50/giorno
    # come tetto massimo su più lanci manuali nella giornata.
    follow_per_lotto: int = 10
    follow_max_giornalieri: int = 50
    follow_pausa_min_sec: int = 25
    follow_pausa_max_sec: int = 70
    follow_pausa_lunga_ogni: int = 4
    follow_pausa_lunga_min_sec: int = 120
    follow_pausa_lunga_max_sec: int = 240
    follow_intervallo_lotti_min: int = 45

    # 14.1/14.2 opzione A: l'account Facebook dedicato è una Pagina gestita
    # dal profilo personale dell'utente, non un secondo profilo.
    facebook_page_url: str = field(
        default_factory=lambda: os.getenv(
            "FACEBOOK_PAGE_URL", "https://www.facebook.com/profile.php?id=61593736766094"
        )
    )

    # Bug reale osservato (2026-08-25): Facebook non offre più uno switch
    # esplicito "Usa Facebook come Pagina" — un amministratore vede sempre
    # la vista pubblica (bottone "Segui") quando visita la Pagina. L'unico
    # segnale affidabile resta il nome dell'account PERSONALE loggato nella
    # sessione salvata (letto dal blob di configurazione della pagina),
    # confrontato con questo valore atteso.
    facebook_account_name: str = field(
        default_factory=lambda: os.getenv("FACEBOOK_ACCOUNT_NAME", "")
    )

    # Bug reale osservato (2026-08-24): la sessione salvata risultava
    # loggata sul profilo personale invece dell'account dedicato. Username
    # atteso, verificato prima di ogni lettura/azione su Instagram.
    instagram_username: str = field(
        default_factory=lambda: os.getenv("INSTAGRAM_USERNAME", "eventi.langa")
    )

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
    llm_provider: str = field(default_factory=lambda: os.getenv("LLM_PROVIDER", "gemini"))
    imap_host: str = field(default_factory=lambda: os.getenv("IMAP_HOST", ""))
    imap_user: str = field(default_factory=lambda: os.getenv("IMAP_USER", ""))
    imap_password: str = field(default_factory=lambda: os.getenv("IMAP_PASSWORD", ""))
    telegram_bot_token: str = field(
        default_factory=lambda: os.getenv("TELEGRAM_BOT_TOKEN", "")
    )


def load_config() -> Config:
    """Carica la configurazione di default. registry.py la aggiorna dal foglio `Config`."""
    return Config()
