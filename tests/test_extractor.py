"""M5: client di estrazione, con provider fittizio (nessuna chiamata di rete reale, 15.1 regola 8)."""
import sqlite3
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src import store
from src.config import Config
from src.extractor.client import ErroreQuotaEsaurita, ExtractorClient, RateLimitError, _chiama_con_retry
from src.extractor.providers import ProviderLLM


def _conn_di_prova() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript(store.SCHEMA_SQL)
    return conn


class ProviderFinto(ProviderLLM):
    def __init__(self, risposte: list[str]):
        self._risposte = list(risposte)
        self.chiamate = 0

    def estrai(self, prompt_sistema, prompt_utente, immagini=None):
        self.chiamate += 1
        return self._risposte.pop(0)


RISPOSTA_VALIDA = """{
  "eventi": [{
    "titolo": "Sagra del Tartufo",
    "descrizione": "Degustazioni in piazza",
    "tipologia": "sagra",
    "data_inizio": "2026-09-12",
    "data_fine": "2026-09-12",
    "ora_inizio": "21:00",
    "ora_fine": null,
    "ricorrenza": {"e_ricorrente": false},
    "luogo_testuale": "Piazza Roma",
    "comune_testuale": "Calosso",
    "indirizzo": null,
    "prezzo": null,
    "organizzatore": null,
    "anno_esplicito": true,
    "confidenza": 92,
    "campi_incerti": [],
    "note_estrazione": null
  }],
  "non_e_un_evento": false,
  "motivo": null
}"""


def test_estrai_da_testo_valida_e_salva_extraction():
    conn = _conn_di_prova()
    provider = ProviderFinto([RISPOSTA_VALIDA])
    client = ExtractorClient(Config(), conn, provider=provider)

    risposta = client.estrai_da_testo(
        testo="Sabato 12 settembre Sagra del Tartufo in Piazza Roma a Calosso.",
        artifact_id="art-1",
        fonte="Pro Loco Calosso",
        categoria_fonte="proloco",
        comune_fonte="Calosso",
        url="https://esempio.it",
    )

    assert len(risposta.eventi) == 1
    assert risposta.eventi[0].titolo == "Sagra del Tartufo"

    salvato = conn.execute("SELECT prompt_version, confidence FROM extractions").fetchone()
    assert salvato["prompt_version"] == "testo_v1"
    assert salvato["confidence"] == 92


def test_budget_esaurito_blocca_la_chiamata():
    conn = _conn_di_prova()
    config = Config(budget_llm_giornaliero=1)
    provider = ProviderFinto([RISPOSTA_VALIDA, RISPOSTA_VALIDA])
    client = ExtractorClient(config, conn, provider=provider)

    client.estrai_da_testo("testo", "art-1", "fonte", "proloco", "Calosso", "https://x.it")

    try:
        client.estrai_da_testo("testo2", "art-2", "fonte", "proloco", "Calosso", "https://x.it")
        assert False, "doveva sollevare ErroreQuotaEsaurita"
    except ErroreQuotaEsaurita:
        pass

    assert provider.chiamate == 1  # la seconda chiamata non è mai partita


def test_json_non_valido_viene_scartato_non_solleva():
    conn = _conn_di_prova()
    provider = ProviderFinto(["questo non è json valido {{{"])
    client = ExtractorClient(Config(), conn, provider=provider)

    risposta = client.estrai_da_testo("testo", "art-1", "fonte", "proloco", "Calosso", "https://x.it")

    assert risposta.eventi == []
    assert risposta.non_e_un_evento is True


def test_evento_con_titolo_troppo_corto_viene_scartato():
    conn = _conn_di_prova()
    risposta_titolo_corto = RISPOSTA_VALIDA.replace('"Sagra del Tartufo"', '"Ok"')
    provider = ProviderFinto([risposta_titolo_corto])
    client = ExtractorClient(Config(), conn, provider=provider)

    risposta = client.estrai_da_testo("testo", "art-1", "fonte", "proloco", "Calosso", "https://x.it")

    assert risposta.eventi == []


def test_data_oltre_limite_sanita_viene_scartata():
    conn = _conn_di_prova()
    risposta_data_lontana = RISPOSTA_VALIDA.replace("2026-09-12", "2035-01-01")
    provider = ProviderFinto([risposta_data_lontana])
    client = ExtractorClient(Config(limite_sanita_anni=2), conn, provider=provider)

    risposta = client.estrai_da_testo(
        "testo", "art-1", "fonte", "proloco", "Calosso", "https://x.it",
        data_riferimento=date(2026, 8, 22),
    )

    assert risposta.eventi == []


def test_retry_su_rate_limit_poi_successo():
    class ProviderConRateLimit(ProviderLLM):
        def __init__(self):
            self.tentativi = 0

        def estrai(self, prompt_sistema, prompt_utente, immagini=None):
            self.tentativi += 1
            if self.tentativi < 2:
                raise Exception("429 rate limit exceeded")
            return RISPOSTA_VALIDA

    provider = ProviderConRateLimit()
    risultato = _chiama_con_retry(provider, "sistema", "utente", None)

    assert provider.tentativi == 2
    assert "Sagra del Tartufo" in risultato
