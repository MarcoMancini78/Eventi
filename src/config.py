"""Configurazione centrale. Nessun numero magico altrove nel codice (15.1.1).

Caricata solo da `.env` (`load_config`). Il foglio `Config` e il modulo
`registry.py` che l'avrebbe riletto da Sheets sono stati rimossi il
2026-08-28 (richiesto dall'utente): erano scritti ma mai collegati a
`run.py`, codice morto senza alcun test.
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
    giorni_archiviazione: int = 0
    limite_sanita_anni: int = 2

    # Ricorrenze (03.1.6, 07.9)
    orizzonte_espansione_giorni: int = 120
    serie_decadimento_da_verificare_giorni: int = 120
    serie_decadimento_sospesa_giorni: int = 400

    # Confidenza ed estrazione (06.6). Penalità applicate in pipeline.py
    # quando l'LLM non trova un anno esplicito nel post — ridotta da 15 a
    # 5 il 2026-09-01 (richiesto dall'utente: "stasera" è normale per un
    # post social, non un segnale forte di scarsa affidabilità).
    soglia_confidenza: int = 70
    penalita_anno_non_esplicito: int = 5
    # 2026-09-07, richiesto dall'utente (caso Capriglio/Caprigliola
    # 0fa104f8510b): il comune resta il dato fondamentale, ma la sua
    # affidabilità quando inferito dalla fonte (non dal testo) dipende dal
    # TIPO di fonte — una fonte 'comune'/'proloco' è legata in modo
    # affidabile a un solo comune noto (l'incertezza residua è solo "la
    # Pro Loco può pubblicizzare un evento in un comune vicino"), mentre
    # un aggregatore/raccoglitore di notizie senza comune_testuale nel
    # post è un segnale di scarsa affidabilità della notizia stessa — lì
    # la penalità piena resta giustificata. Il luogo (posto preciso dentro
    # il comune) NON penalizza più (vedi pipeline._pubblica_o_metti_in_quarantena):
    # un evento diffuso o itinerante può non averne uno, è un dettaglio in
    # più quando presente, mai un segnale di scarsa certezza quando assente.
    penalita_comune_da_fonte_affidabile: int = 3
    penalita_comune_da_fonte_generica: int = 10

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

    # Parallelismo del giro multi-fonte (M11, richiesto dall'utente
    # 2026-08-27): ogni worker apre la propria connessione SQLite (WAL
    # abilitato in store.connect), quindi il numero non è vincolato dalla
    # sola CPU ma dalla rete/LLM — 6 è il valore indicato dall'utente come
    # sicuro, non misurato empiricamente qui.
    run_paralleli: int = 6

    # Follow (14.4). Default doc: 40/giorno; l'utente ha chiesto 50/giorno,
    # poi (2026-08-25, riscaldamento ancora in corso fino a ~2026-09-05,
    # rischio accettato esplicitamente) il raddoppio a 100/giorno e lotti
    # da 20 invece di 10.
    follow_per_lotto: int = 20
    follow_max_giornalieri: int = 100
    follow_pausa_min_sec: int = 25
    follow_pausa_max_sec: int = 70
    follow_pausa_lunga_ogni: int = 4
    follow_pausa_lunga_min_sec: int = 120
    follow_pausa_lunga_max_sec: int = 240
    follow_intervallo_lotti_min: int = 45

    # 2026-09-08, richiesto dall'utente: la sessione browser Playwright per
    # Facebook/Instagram è sempre aperta visibile (headless=False, 14.3:
    # "un login/interazione headless è più sospetto") — corretto per
    # follow.login_manuale (l'utente deve poter interagire per il primo
    # login/2FA), ma per i giri automatici senza interazione (lettura feed,
    # sync seguiti, lotto di follow) l'utente può preferire non vedere la
    # finestra comparire. 'True' (default, invariato): finestra visibile
    # normale. 'False': la sessione resta comunque headless=False (stesso
    # fingerprint anti-bot, nessun compromesso sul rischio di rilevamento
    # 14.3) ma la finestra viene minimizzata e spostata fuori dall'area
    # visibile dello schermo subito dopo l'apertura — invisibile
    # all'utente senza rinunciare alla resa "browser reale" verso Facebook/
    # Instagram. Non si applica a login_manuale, che resta sempre visibile
    # per forza (richiede interazione umana diretta).
    browser_visibile: bool = field(
        default_factory=lambda: os.getenv("BROWSER_VISIBILE", "true").strip().lower() != "false"
    )

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
    """Carica la configurazione da `.env`."""
    return Config()
