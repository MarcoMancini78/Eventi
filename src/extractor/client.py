"""M5: client di estrazione — orchestrazione provider, retry, quota, controlli di sanità.

L'LLM fa una cosa sola: dato un artefatto, restituisce zero o più eventi in
JSON (06.1). Tutta la logica deterministica (perimetro, distanze, dedup,
pubblicazione) resta fuori da qui.

Nota sulla concorrenza (M11, run.py run --paralleli): il lock _LOCK_QUOTA
protegge solo il momento del check (leggi 'usate', confronta col limite),
non l'intera finestra fino al commit della chiamata LLM (che può durare
secondi). Due thread possono quindi, in rari casi, superare il budget di
qualche chiamata in un giorno di picco — accettabile perché il tetto è un
freno operativo sui costi, non un vincolo di fatturazione rigido, e il
costo di un lock a copertura totale (serializzare ogni estrazione) andrebbe
contro lo scopo stesso della parallelizzazione.
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
import threading
from datetime import date, datetime, timedelta

from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from ..config import Config
from .prompts.testo_v1 import PROMPT_VERSION, SISTEMA, costruisci_prompt_utente
from .providers import ProviderLLM, crea_provider
from .schema import RispostaEstrazione

_LIMITE_TITOLO_MIN = 3
_LIMITE_TITOLO_MAX = 200

# Lock a livello di processo: quando piu' thread processano fonti in
# parallelo (M11, run.py run --paralleli), ognuno con la propria connessione
# SQLite, il controllo-e-incremento della quota LLM deve restare atomico
# altrimenti due thread possono leggere lo stesso 'usate' ed entrambi
# procedere, sforando budget_llm_giornaliero. Un Lock in memoria basta
# perche' i worker vivono nello stesso processo Python (thread, non processi
# separati) — non serve un lock a livello di file/DB.
_LOCK_QUOTA = threading.Lock()


class ErroreQuotaEsaurita(Exception):
    """Sollevato quando il budget LLM giornaliero è a 100% (08.5)."""


class EstrazioneSospesaPerQuota(Exception):
    """Sollevato dalle soglie 70%/85% di 08.5 (degradazione progressiva prima
    dell'esaurimento totale) — a differenza di ErroreQuotaEsaurita non
    significa 'niente è più possibile', solo 'non per questa fonte adesso'.
    L'artefatto resta in staging (08.5: 'non vanno persi'), ripreso al
    prossimo giro secondo la stessa logica del 100%."""


def decidi_degradazione_quota(percentuale_usata: float, fascia: str | None, e_immagine: bool) -> str | None:
    """08.5, approssimato con la sola fascia geografica (A/B/C, già popolata
    su ogni fonte) al posto dei campi 'priorita' (1-3) e 'polling_diretto'
    previsti dalla specifica ma non ancora assegnati da nessuna parte
    (richiedono un giudizio manuale dell'utente, non automatizzabile) —
    decisione presa esplicitamente con l'utente il 2026-08-27.

    Ritorna il motivo del blocco, o None se l'estrazione può procedere.
    fascia=None (fonte senza fascia nota, es. social con comune non ancora
    risolto) è trattato come non-A: prudente, non privilegiato.
    """
    if percentuale_usata >= 1.0:
        return None  # ErroreQuotaEsaurita se ne occupa a monte, non qui

    if percentuale_usata >= 0.85 and fascia != "A":
        return f"quota all'{percentuale_usata:.0%}: sotto la soglia 85% restano attive solo le fonti di fascia A"

    if percentuale_usata >= 0.70 and e_immagine and fascia != "A":
        return f"quota al {percentuale_usata:.0%}: sopra la soglia 70% le estrazioni da immagine sono sospese per le fonti non di fascia A"

    return None


class RateLimitError(Exception):
    """429 dal provider: va ritentato con backoff, non è un errore permanente."""


def _conta_chiamate_oggi(conn: sqlite3.Connection, oggi: str) -> int:
    riga = conn.execute(
        "SELECT COUNT(*) FROM extractions WHERE substr(created_at, 1, 10) = ?", (oggi,)
    ).fetchone()
    return riga[0] if riga else 0


@retry(
    retry=retry_if_exception_type(RateLimitError),
    wait=wait_exponential(multiplier=2, min=2, max=60),
    stop=stop_after_attempt(3),
)
def _chiama_con_retry(provider: ProviderLLM, prompt_sistema: str, prompt_utente: str, immagini) -> str:
    try:
        return provider.estrai(prompt_sistema, prompt_utente, immagini)
    except Exception as exc:
        messaggio = str(exc).lower()
        if "429" in messaggio or "rate limit" in messaggio or "quota" in messaggio:
            raise RateLimitError(str(exc)) from exc
        raise


def _controlli_di_sanita(
    risposta: RispostaEstrazione, oggi: date, limite_sanita_anni: int, max_eventi_per_artefatto: int
) -> list[str]:
    """06.8. Ritorna la lista degli scarti (per log per-fonte), filtra risposta.eventi in place."""
    validi = []
    scarti = []
    for evento in risposta.eventi:
        if not (_LIMITE_TITOLO_MIN <= len(evento.titolo.strip()) <= _LIMITE_TITOLO_MAX):
            scarti.append(f"titolo fuori range: {evento.titolo!r}")
            continue
        if evento.data_inizio and evento.data_fine and evento.data_inizio > evento.data_fine:
            evento.data_inizio, evento.data_fine = evento.data_fine, evento.data_inizio
        if evento.data_inizio:
            data_ev = date.fromisoformat(evento.data_inizio)
            limite_min = oggi - timedelta(days=1)
            limite_max = date(oggi.year + limite_sanita_anni, oggi.month, oggi.day)
            if not (limite_min <= data_ev <= limite_max):
                scarti.append(f"data fuori range di sanità: {evento.data_inizio}")
                continue
        validi.append(evento)

    if len(validi) > max_eventi_per_artefatto:
        scarti.append(f"troppi eventi in un artefatto ({len(validi)}), probabile allucinazione")
        validi = []

    risposta.eventi = validi
    return scarti


class ExtractorClient:
    def __init__(self, config: Config, conn: sqlite3.Connection, provider: ProviderLLM | None = None):
        self._config = config
        self._conn = conn
        self._provider = provider or crea_provider(config.llm_provider or "gemini", config.llm_api_key)

    def budget_rimanente(self) -> tuple[int, int]:
        oggi = date.today().isoformat()
        with _LOCK_QUOTA:
            usate = _conta_chiamate_oggi(self._conn, oggi)
        return usate, self._config.budget_llm_giornaliero

    def estrai_da_testo(
        self,
        testo: str,
        artifact_id: str,
        fonte: str,
        categoria_fonte: str,
        comune_fonte: str,
        url: str,
        data_riferimento: date | None = None,
        fascia_fonte: str | None = None,
    ) -> RispostaEstrazione:
        usate, limite = self.budget_rimanente()
        if usate >= limite:
            raise ErroreQuotaEsaurita(f"Budget LLM giornaliero esaurito: {usate}/{limite}")

        motivo = decidi_degradazione_quota(usate / limite, fascia_fonte, e_immagine=False)
        if motivo:
            raise EstrazioneSospesaPerQuota(motivo)

        data_rif = data_riferimento or date.today()
        prompt_utente = costruisci_prompt_utente(
            data_riferimento=data_rif.isoformat(),
            fonte=fonte,
            categoria_fonte=categoria_fonte,
            comune_fonte=comune_fonte,
            url=url,
            testo=testo,
        )

        grezzo = _chiama_con_retry(self._provider, SISTEMA, prompt_utente, None)
        risposta = self._valida_e_salva(grezzo, artifact_id, data_rif, prompt_utente)
        return risposta

    def estrai_da_immagine(
        self,
        immagine_bytes: bytes,
        artifact_id: str,
        fonte: str,
        categoria_fonte: str,
        comune_fonte: str,
        url: str,
        caption: str | None = None,
        data_riferimento: date | None = None,
        fascia_fonte: str | None = None,
    ) -> RispostaEstrazione:
        usate, limite = self.budget_rimanente()
        if usate >= limite:
            raise ErroreQuotaEsaurita(f"Budget LLM giornaliero esaurito: {usate}/{limite}")

        motivo = decidi_degradazione_quota(usate / limite, fascia_fonte, e_immagine=True)
        if motivo:
            raise EstrazioneSospesaPerQuota(motivo)

        from .prompts.testo_v1 import REGOLE_LOCANDINA_AGGIUNTIVE

        data_rif = data_riferimento or date.today()
        prompt_utente = costruisci_prompt_utente(
            data_riferimento=data_rif.isoformat(),
            fonte=fonte,
            categoria_fonte=categoria_fonte,
            comune_fonte=comune_fonte,
            url=url,
            testo="(vedi immagine allegata)",
            caption=caption,
        )
        prompt_sistema = SISTEMA + REGOLE_LOCANDINA_AGGIUNTIVE

        grezzo = _chiama_con_retry(self._provider, prompt_sistema, prompt_utente, [immagine_bytes])
        risposta = self._valida_e_salva(grezzo, artifact_id, data_rif, prompt_utente)
        return risposta

    def _valida_e_salva(
        self, grezzo: str, artifact_id: str, data_riferimento: date, prompt_utente: str | None = None
    ) -> RispostaEstrazione:
        try:
            risposta = RispostaEstrazione.model_validate_json(grezzo)
        except Exception:
            # 06.8: JSON non valido -> 1 retry già fatto dal provider, qui si scarta con log.
            risposta = RispostaEstrazione(eventi=[], non_e_un_evento=True, motivo="json_non_valido")

        scarti = _controlli_di_sanita(
            risposta, data_riferimento, self._config.limite_sanita_anni, self._config.max_eventi_per_artefatto
        )

        # Ora locale, non UTC: il conteggio giornaliero (budget_rimanente)
        # confronta con date.today() (locale, 07.2 "si lavora sempre in ora
        # locale italiana"). Un mismatch di fuso qui rompe il conteggio a
        # cavallo di mezzanotte tra locale e UTC.
        adesso_locale = datetime.now()
        extraction_id = hashlib.sha1(f"{artifact_id}|{adesso_locale.isoformat()}".encode()).hexdigest()[:16]
        self._conn.execute(
            """
            INSERT INTO extractions (extraction_id, artifact_id, model, prompt_version, prompt_utente, raw_output, parsed_json, confidence, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                extraction_id,
                artifact_id,
                self._config.llm_provider or "gemini",
                PROMPT_VERSION,
                prompt_utente,
                grezzo,
                risposta.model_dump_json(),
                risposta.eventi[0].confidenza if risposta.eventi else 0,
                adesso_locale.isoformat(),
            ),
        )
        self._conn.commit()

        if scarti:
            import logging

            logging.getLogger(__name__).warning("Scarti sanità per artifact %s: %s", artifact_id, scarti)

        return risposta
