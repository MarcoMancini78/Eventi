"""M5: client di estrazione — orchestrazione provider, retry, quota, controlli di sanità.

L'LLM fa una cosa sola: dato un artefatto, restituisce zero o più eventi in
JSON (06.1). Tutta la logica deterministica (perimetro, distanze, dedup,
pubblicazione) resta fuori da qui.
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import date, datetime, timedelta

from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from ..config import Config
from .prompts.testo_v1 import PROMPT_VERSION, SISTEMA, costruisci_prompt_utente
from .providers import ProviderLLM, crea_provider
from .schema import RispostaEstrazione

_LIMITE_TITOLO_MIN = 3
_LIMITE_TITOLO_MAX = 200
_MAX_EVENTI_PER_ARTEFATTO = 20  # oltre: probabile allucinazione (06.8)


class ErroreQuotaEsaurita(Exception):
    """Sollevato quando il budget LLM giornaliero è a 100% (08.5)."""


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


def _controlli_di_sanita(risposta: RispostaEstrazione, oggi: date, limite_sanita_anni: int) -> list[str]:
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

    if len(validi) > _MAX_EVENTI_PER_ARTEFATTO:
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
    ) -> RispostaEstrazione:
        usate, limite = self.budget_rimanente()
        if usate >= limite:
            raise ErroreQuotaEsaurita(f"Budget LLM giornaliero esaurito: {usate}/{limite}")

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
        risposta = self._valida_e_salva(grezzo, artifact_id, data_rif)
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
    ) -> RispostaEstrazione:
        usate, limite = self.budget_rimanente()
        if usate >= limite:
            raise ErroreQuotaEsaurita(f"Budget LLM giornaliero esaurito: {usate}/{limite}")

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
        risposta = self._valida_e_salva(grezzo, artifact_id, data_rif)
        return risposta

    def _valida_e_salva(self, grezzo: str, artifact_id: str, data_riferimento: date) -> RispostaEstrazione:
        try:
            risposta = RispostaEstrazione.model_validate_json(grezzo)
        except Exception:
            # 06.8: JSON non valido -> 1 retry già fatto dal provider, qui si scarta con log.
            risposta = RispostaEstrazione(eventi=[], non_e_un_evento=True, motivo="json_non_valido")

        scarti = _controlli_di_sanita(risposta, data_riferimento, self._config.limite_sanita_anni)

        # Ora locale, non UTC: il conteggio giornaliero (budget_rimanente)
        # confronta con date.today() (locale, 07.2 "si lavora sempre in ora
        # locale italiana"). Un mismatch di fuso qui rompe il conteggio a
        # cavallo di mezzanotte tra locale e UTC.
        adesso_locale = datetime.now()
        extraction_id = hashlib.sha1(f"{artifact_id}|{adesso_locale.isoformat()}".encode()).hexdigest()[:16]
        self._conn.execute(
            """
            INSERT INTO extractions (extraction_id, artifact_id, model, prompt_version, raw_output, parsed_json, confidence, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                extraction_id,
                artifact_id,
                self._config.llm_provider or "gemini",
                PROMPT_VERSION,
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
