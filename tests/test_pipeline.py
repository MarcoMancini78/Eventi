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


def test_fonte_t0_email_instradata_come_t1_e_pubblica_con_estrattore():
    """M7: email/telegram non hanno campi strutturati precompilati (a
    differenza di ical/jsonld), quindi seguono lo stesso ramo T1-like
    dell'html — verificato qui che pipeline.esegui_fonte le riconosca e le
    faccia passare dall'estrattore, coerente col contratto degli altri
    adapter."""
    from src.adapters.email_imap import EmailImapAdapter, parse_email
    import email as email_stdlib

    conn = _conn_di_prova()
    provider = _ProviderFinto([_risposta_json(confidenza=92)])
    extractor = ExtractorClient(Config(), conn, provider=provider)

    msg = email_stdlib.message_from_string(
        "Subject: Sagra del Tartufo\nFrom: newsletter@proloco.it\n\n"
        "Vi aspettiamo sabato 12 settembre in Piazza Roma per la Sagra del Tartufo, "
        "con degustazioni, musica dal vivo e mercatino artigianale."
    )
    artefatto = parse_email(msg, "email-prova", "casella", "1")

    fonte = {"source_id": "email-prova", "metodo": "T0_email", "endpoint": "proloco.it", "comune_riferimento": "Comune Prova"}
    with patch.object(EmailImapAdapter, "fetch", return_value=[artefatto]):
        riepilogo = pipeline.esegui_fonte(fonte, conn, Config(), extractor)

    assert riepilogo["errore"] is None
    assert riepilogo["chiamate_llm"] == 1
    assert riepilogo["eventi_pubblicati"] == 1


def test_fonte_metodo_sconosciuto_produce_errore_isolato():
    conn = _conn_di_prova()
    fonte = {"source_id": "fonte-strana", "metodo": "T9_inesistente", "endpoint": "x", "comune_riferimento": "Comune Prova"}
    riepilogo = pipeline.esegui_fonte(fonte, conn, Config())
    assert riepilogo["errore"] == "metodo sconosciuto: T9_inesistente"


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


# --- M6 collegato: evento ricorrente estratto -> Serie -> occorrenze ---

_RISPOSTA_RICORRENTE = (
    '{"eventi": [{"titolo": "Mercatino dell\'antiquariato", "descrizione": null, "tipologia": "fiera", '
    '"data_inizio": "2026-09-06", "data_fine": "2026-09-06", "ora_inizio": null, "ora_fine": null, '
    '"ricorrenza": {"e_ricorrente": true, "frequenza": "mensile", "giorni_settimana": ["SU"], '
    '"ordinale": 1, "mesi_inclusi": [1,2,3,4,5,6,7,9,10,11,12], "fine_dichiarata": null, '
    '"testo_originale": "prima domenica del mese, escluso agosto"}, '
    '"luogo_testuale": "Piazza Roma", "comune_testuale": "Comune Prova", '
    '"indirizzo": null, "prezzo": null, "organizzatore": null, "anno_esplicito": true, '
    '"confidenza": 90, "campi_incerti": [], "note_estrazione": null}], '
    '"non_e_un_evento": false, "motivo": null}'
)


def test_fonte_t1_con_evento_ricorrente_genera_serie_e_occorrenze():
    conn = _conn_di_prova()
    provider = _ProviderFinto([_RISPOSTA_RICORRENTE])
    extractor = ExtractorClient(Config(), conn, provider=provider)

    fonte = {"source_id": "sito-prova", "metodo": "T1_html", "endpoint": "https://sito-prova.it/eventi", "comune_riferimento": "Comune Prova"}
    html = (FIXTURES / "esempio_pagina_eventi.html").read_text(encoding="utf-8")

    with patch("src.adapters.html.HtmlAdapter.fetch", return_value=parse_html(html, "sito-prova", fonte["endpoint"])):
        riepilogo = pipeline.esegui_fonte(fonte, conn, Config(), extractor)

    assert riepilogo["occorrenze_generate"] > 0
    assert riepilogo["eventi_pubblicati"] == 0  # non pubblicato come evento singolo

    serie = conn.execute("SELECT * FROM series").fetchall()
    assert len(serie) == 1
    assert "prima domenica" in serie[0]["regola_leggibile"]

    occorrenze = conn.execute("SELECT * FROM events WHERE serie_id IS NOT NULL").fetchall()
    assert len(occorrenze) == riepilogo["occorrenze_generate"]
    for occ in occorrenze:
        assert occ["comune"] == "Comune Prova"
