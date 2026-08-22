"""M2: criterio di accettazione end-to-end su fonte T0 (ical), senza rete (fixture)."""
import sqlite3
import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src import pipeline, store
from src.adapters.html import parse_html
from src.config import Config

FIXTURES = Path(__file__).parent / "fixtures"


def _conn_di_prova() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript(store.SCHEMA_SQL)
    conn.execute(
        "INSERT INTO comuni (istat, comune, alias, provincia, lat, lon, km, minuti, fascia, attivo) "
        "VALUES ('1', 'Comune Prova', 'Comune Prova', 'AT', 44.7, 8.2, 5.0, 10, 'A', 'si')"
    )
    return conn


def test_fonte_t0_ical_produce_eventi_pubblicati_senza_llm():
    from src.adapters.ical import parse_ical

    testo_ics = (FIXTURES / "esempio.ics").read_text(encoding="utf-8")

    conn = _conn_di_prova()
    fonte = {"source_id": "comune-prova", "metodo": "T0_ical", "endpoint": "https://comune-prova.it/eventi.ics", "comune_riferimento": "Comune Prova"}

    with patch("src.adapters.ical.ICalAdapter.fetch", return_value=parse_ical(testo_ics, "comune-prova", fonte["endpoint"])):
        riepilogo = pipeline.esegui_fonte(fonte, conn, Config())

    assert riepilogo["errore"] is None
    assert riepilogo["artefatti"] == 2
    assert riepilogo["eventi_pubblicati"] == 2

    eventi = conn.execute("SELECT titolo, comune, data_inizio FROM events ORDER BY data_inizio").fetchall()
    assert len(eventi) == 2
    assert eventi[0]["comune"] == "Comune Prova"


def test_fonte_con_errore_di_rete_e_isolata_non_solleva():
    conn = _conn_di_prova()
    fonte = {"source_id": "fonte-rotta", "metodo": "T0_ical", "endpoint": "https://non-esiste-davvero.invalid/eventi.ics", "comune_riferimento": "Comune Prova"}

    with patch("src.adapters.ical.ICalAdapter.fetch", side_effect=ConnectionError("simulato")):
        riepilogo = pipeline.esegui_fonte(fonte, conn, Config())

    assert riepilogo["errore"] == "simulato"
    assert riepilogo["eventi_pubblicati"] == 0


def test_rilancio_due_volte_non_duplica():
    from src.adapters.ical import parse_ical

    testo_ics = (FIXTURES / "esempio.ics").read_text(encoding="utf-8")
    conn = _conn_di_prova()
    fonte = {"source_id": "comune-prova", "metodo": "T0_ical", "endpoint": "https://comune-prova.it/eventi.ics", "comune_riferimento": "Comune Prova"}

    with patch("src.adapters.ical.ICalAdapter.fetch", return_value=parse_ical(testo_ics, "comune-prova", fonte["endpoint"])):
        pipeline.esegui_fonte(fonte, conn, Config())
        pipeline.esegui_fonte(fonte, conn, Config())

    totale = conn.execute("SELECT COUNT(*) FROM events").fetchone()[0]
    assert totale == 2  # non 4: il secondo run aggiorna, non duplica (M2 criterio di accettazione)


# --- M5: percorso T1 (html) attraverso l'estrattore, con provider fittizio ---

from src.extractor.client import ExtractorClient
from src.extractor.providers import ProviderLLM


class _ProviderFinto(ProviderLLM):
    def __init__(self, risposte: list[str]):
        self._risposte = list(risposte)

    def estrai(self, prompt_sistema, prompt_utente, immagini=None):
        return self._risposte.pop(0)


def _risposta_json(titolo="Sagra del Tartufo", comune="Comune Prova", confidenza=92, luogo="Piazza Roma"):
    return (
        '{"eventi": [{"titolo": "%s", "descrizione": "Degustazioni", "tipologia": "sagra", '
        '"data_inizio": "2026-09-12", "data_fine": "2026-09-12", "ora_inizio": "21:00", "ora_fine": null, '
        '"ricorrenza": {"e_ricorrente": false}, "luogo_testuale": %s, "comune_testuale": "%s", '
        '"indirizzo": null, "prezzo": null, "organizzatore": null, "anno_esplicito": true, '
        '"confidenza": %d, "campi_incerti": [], "note_estrazione": null}], '
        '"non_e_un_evento": false, "motivo": null}'
    ) % (titolo, f'"{luogo}"' if luogo else "null", comune, confidenza)


def test_fonte_t1_html_con_estrattore_pubblica_evento_sopra_soglia():
    conn = _conn_di_prova()
    provider = _ProviderFinto([_risposta_json(confidenza=92)])
    extractor = ExtractorClient(Config(), conn, provider=provider)

    fonte = {"source_id": "sito-prova", "metodo": "T1_html", "endpoint": "https://sito-prova.it/eventi", "comune_riferimento": "Comune Prova"}
    html = (FIXTURES / "esempio_pagina_eventi.html").read_text(encoding="utf-8")

    with patch("src.adapters.html.HtmlAdapter.fetch", return_value=parse_html(html, "sito-prova", fonte["endpoint"])):
        riepilogo = pipeline.esegui_fonte(fonte, conn, Config(), extractor)

    assert riepilogo["chiamate_llm"] == 1
    assert riepilogo["eventi_pubblicati"] == 1
    assert riepilogo["eventi_in_quarantena"] == 0

    riga = conn.execute("SELECT titolo, comune, stato FROM events").fetchone()
    assert riga["titolo"] == "Sagra del Tartufo"
    assert riga["comune"] == "Comune Prova"
    assert riga["stato"] != "quarantena"


def test_fonte_t1_con_confidenza_bassa_va_in_quarantena():
    conn = _conn_di_prova()
    provider = _ProviderFinto([_risposta_json(confidenza=50)])
    extractor = ExtractorClient(Config(soglia_confidenza=70), conn, provider=provider)

    fonte = {"source_id": "sito-prova", "metodo": "T1_html", "endpoint": "https://sito-prova.it/eventi", "comune_riferimento": "Comune Prova"}
    html = (FIXTURES / "esempio_pagina_eventi.html").read_text(encoding="utf-8")

    with patch("src.adapters.html.HtmlAdapter.fetch", return_value=parse_html(html, "sito-prova", fonte["endpoint"])):
        riepilogo = pipeline.esegui_fonte(fonte, conn, Config(soglia_confidenza=70), extractor)

    assert riepilogo["eventi_in_quarantena"] == 1
    assert riepilogo["eventi_pubblicati"] == 0

    riga = conn.execute("SELECT stato FROM events").fetchone()
    assert riga["stato"] == "quarantena"


def test_fonte_t1_con_comune_irrisolvibile_va_in_quarantena_senza_sollevare():
    conn = _conn_di_prova()
    provider = _ProviderFinto([_risposta_json(comune="Comune Che Non Esiste Da Nessuna Parte")])
    extractor = ExtractorClient(Config(), conn, provider=provider)

    fonte = {"source_id": "sito-prova", "metodo": "T1_html", "endpoint": "https://sito-prova.it/eventi", "comune_riferimento": None}
    html = (FIXTURES / "esempio_pagina_eventi.html").read_text(encoding="utf-8")

    with patch("src.adapters.html.HtmlAdapter.fetch", return_value=parse_html(html, "sito-prova", fonte["endpoint"])):
        riepilogo = pipeline.esegui_fonte(fonte, conn, Config(), extractor)

    assert riepilogo["errore"] is None  # non deve mai sollevare (15.1 regola 4)
    assert riepilogo["eventi_in_quarantena"] == 1
    assert riepilogo["eventi_pubblicati"] == 0
    assert conn.execute("SELECT COUNT(*) FROM events").fetchone()[0] == 0  # nessun evento con comune fantasma


def test_run_py_no_llm_non_chiama_lestrattore():
    from src.adapters.ical import parse_ical

    testo_ics = (FIXTURES / "esempio.ics").read_text(encoding="utf-8")
    conn = _conn_di_prova()
    fonte = {"source_id": "sito-prova", "metodo": "T1_html", "endpoint": "https://sito-prova.it/eventi", "comune_riferimento": "Comune Prova"}
    html = (FIXTURES / "esempio_pagina_eventi.html").read_text(encoding="utf-8")

    with patch("src.adapters.html.HtmlAdapter.fetch", return_value=parse_html(html, "sito-prova", fonte["endpoint"])):
        riepilogo = pipeline.esegui_fonte(fonte, conn, Config(), extractor=None)

    assert riepilogo["chiamate_llm"] == 0
    assert riepilogo["eventi_pubblicati"] == 0
