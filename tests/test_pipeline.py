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


def _risposta_json(titolo="Sagra del Tartufo", comune="Comune Prova", confidenza=92, luogo="Piazza Roma", anno_esplicito=True):
    return (
        '{"eventi": [{"titolo": "%s", "descrizione": "Degustazioni", "tipologia": "sagra", '
        '"data_inizio": "2026-09-12", "data_fine": "2026-09-12", "ora_inizio": "21:00", "ora_fine": null, '
        '"ricorrenza": {"e_ricorrente": false}, "luogo_testuale": %s, "comune_testuale": "%s", '
        '"indirizzo": null, "prezzo": null, "organizzatore": null, "anno_esplicito": %s, '
        '"confidenza": %d, "campi_incerti": [], "note_estrazione": null}], '
        '"non_e_un_evento": false, "motivo": null}'
    ) % (titolo, f'"{luogo}"' if luogo else "null", comune, "true" if anno_esplicito else "false", confidenza)


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


def test_penalita_anno_non_esplicito_ridotta_a_5_e_luogo_non_penalizza():
    """2026-09-01, richiesto dall'utente: -15 (anno non esplicito) era
    troppo severo per un post social tipico ('stasera') — ridotta a -5.
    2026-09-07, richiesto dall'utente: il luogo (posto preciso dentro il
    comune) non penalizza più — un evento diffuso/itinerante può non
    averne uno, è un dettaglio in più quando presente, non un segnale di
    scarsa certezza quando assente. Confidenza LLM 80, senza anno né
    luogo: solo la penalità anno (-5) si applica, resta a 75 (pubblicato,
    sopra soglia 70)."""
    conn = _conn_di_prova()
    provider = _ProviderFinto([_risposta_json(confidenza=80, luogo=None, anno_esplicito=False)])
    config = Config(soglia_confidenza=70)
    extractor = ExtractorClient(config, conn, provider=provider)

    fonte = {"source_id": "sito-prova", "metodo": "T1_html", "endpoint": "https://sito-prova.it/eventi", "comune_riferimento": "Comune Prova"}
    html = (FIXTURES / "esempio_pagina_eventi.html").read_text(encoding="utf-8")

    with patch("src.adapters.html.HtmlAdapter.fetch", return_value=parse_html(html, "sito-prova", fonte["endpoint"])):
        riepilogo = pipeline.esegui_fonte(fonte, conn, config, extractor)

    assert riepilogo["eventi_pubblicati"] == 1
    assert riepilogo["eventi_in_quarantena"] == 0
    riga = conn.execute("SELECT stato, confidenza FROM events").fetchone()
    assert riga["stato"] != "quarantena"
    assert riga["confidenza"] == 75


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

# data_inizio calcolata da oggi (2026-09-08, trovato dall'utente: la data
# hardcoded '2026-09-06' era diventata "passata" rispetto a date.today()
# col passare dei giorni, facendola scartare dal controllo di sanità —
# un test con una data fissa vicina a "oggi" al momento della scrittura
# scade sempre, prima o poi) invece di una data fissa nel passato.
from datetime import date, timedelta

_RISPOSTA_RICORRENTE = (
    '{"eventi": [{"titolo": "Mercatino dell\'antiquariato", "descrizione": null, "tipologia": "fiera", '
    '"data_inizio": "%s", "data_fine": "%s", "ora_inizio": null, "ora_fine": null, '
    '"ricorrenza": {"e_ricorrente": true, "frequenza": "mensile", "giorni_settimana": ["SU"], '
    '"ordinale": 1, "mesi_inclusi": [1,2,3,4,5,6,7,9,10,11,12], "fine_dichiarata": null, '
    '"testo_originale": "prima domenica del mese, escluso agosto"}, '
    '"luogo_testuale": "Piazza Roma", "comune_testuale": "Comune Prova", '
    '"indirizzo": null, "prezzo": null, "organizzatore": null, "anno_esplicito": true, '
    '"confidenza": 90, "campi_incerti": [], "note_estrazione": null}], '
    '"non_e_un_evento": false, "motivo": null}'
) % (
    (date.today() + timedelta(days=2)).isoformat(),
    (date.today() + timedelta(days=2)).isoformat(),
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


# --- url_approfondimento (2026-09-02, richiesto dall'utente: caso Acqui
# Terme 1a538328a340, un repost con "SCOPRI IL PROGRAMMA COMPLETO:
# www.sito.it" nel testo, mai catturato prima perché lo schema di
# estrazione non aveva un campo dedicato) ---

_RISPOSTA_CON_APPROFONDIMENTO = (
    '{"eventi": [{"titolo": "Sagra del Tartufo", "descrizione": "Degustazioni", "tipologia": "sagra", '
    '"data_inizio": "2026-09-12", "data_fine": "2026-09-12", "ora_inizio": "21:00", "ora_fine": null, '
    '"ricorrenza": {"e_ricorrente": false}, "luogo_testuale": "Piazza Roma", "comune_testuale": "Comune Prova", '
    '"indirizzo": null, "prezzo": null, "organizzatore": null, '
    '"url_approfondimento": "https://www.associazionearchicultura.it/", '
    '"anno_esplicito": true, "confidenza": 92, "campi_incerti": [], "note_estrazione": null}], '
    '"non_e_un_evento": false, "motivo": null}'
)


def test_url_approfondimento_propagato_da_estrazione_a_events():
    conn = _conn_di_prova()
    provider = _ProviderFinto([_RISPOSTA_CON_APPROFONDIMENTO])
    extractor = ExtractorClient(Config(), conn, provider=provider)

    fonte = {"source_id": "sito-prova", "metodo": "T1_html", "endpoint": "https://sito-prova.it/eventi", "comune_riferimento": "Comune Prova"}
    html = (FIXTURES / "esempio_pagina_eventi.html").read_text(encoding="utf-8")

    with patch("src.adapters.html.HtmlAdapter.fetch", return_value=parse_html(html, "sito-prova", fonte["endpoint"])):
        riepilogo = pipeline.esegui_fonte(fonte, conn, Config(), extractor)

    assert riepilogo["eventi_pubblicati"] == 1
    riga = conn.execute("SELECT url, url_approfondimento FROM events").fetchone()
    assert riga["url_approfondimento"] == "https://www.associazionearchicultura.it/"
    assert riga["url"] != riga["url_approfondimento"]  # 'url' resta sempre il link del post sorgente


def test_url_approfondimento_assente_resta_null_non_indovinato():
    """04.7: vuoto non è un errore, mai un valore indovinato."""
    conn = _conn_di_prova()
    provider = _ProviderFinto([_risposta_json(confidenza=92)])  # senza url_approfondimento nel JSON
    extractor = ExtractorClient(Config(), conn, provider=provider)

    fonte = {"source_id": "sito-prova", "metodo": "T1_html", "endpoint": "https://sito-prova.it/eventi", "comune_riferimento": "Comune Prova"}
    html = (FIXTURES / "esempio_pagina_eventi.html").read_text(encoding="utf-8")

    with patch("src.adapters.html.HtmlAdapter.fetch", return_value=parse_html(html, "sito-prova", fonte["endpoint"])):
        pipeline.esegui_fonte(fonte, conn, Config(), extractor)

    riga = conn.execute("SELECT url_approfondimento FROM events").fetchone()
    assert riga["url_approfondimento"] is None


# --- dettaglio_confidenza / campi_incerti / note_estrazione (2026-09-04,
# richiesto dall'utente: un evento in quarantena mostrava solo il
# punteggio finale, senza spiegare cosa mancasse) ---

_RISPOSTA_QUARANTENA_CON_DETTAGLIO = (
    '{"eventi": [{"titolo": "Evento incerto", "descrizione": null, "tipologia": "altro", '
    '"data_inizio": "2026-09-12", "data_fine": "2026-09-12", "ora_inizio": null, "ora_fine": null, '
    '"ricorrenza": {"e_ricorrente": false}, "luogo_testuale": null, "comune_testuale": null, '
    '"indirizzo": null, "prezzo": null, "organizzatore": null, "anno_esplicito": false, '
    '"confidenza": 60, "campi_incerti": ["data_inizio", "organizzatore"], '
    '"note_estrazione": "titolo generico, poche informazioni nel post"}], '
    '"non_e_un_evento": false, "motivo": null}'
)


def test_dettaglio_confidenza_e_campi_incerti_propagati_a_events():
    conn = _conn_di_prova()
    provider = _ProviderFinto([_RISPOSTA_QUARANTENA_CON_DETTAGLIO])
    extractor = ExtractorClient(Config(), conn, provider=provider)

    fonte = {"source_id": "sito-prova", "metodo": "T1_html", "endpoint": "https://sito-prova.it/eventi", "comune_riferimento": "Comune Prova"}
    html = (FIXTURES / "esempio_pagina_eventi.html").read_text(encoding="utf-8")

    with patch("src.adapters.html.HtmlAdapter.fetch", return_value=parse_html(html, "sito-prova", fonte["endpoint"])):
        pipeline.esegui_fonte(fonte, conn, Config(), extractor)

    riga = conn.execute(
        "SELECT stato, confidenza, dettaglio_confidenza, campi_incerti, note_estrazione FROM events"
    ).fetchone()
    assert riga["stato"] == "quarantena"
    # comune_testuale assente -> inferito dal comune_riferimento della fonte
    # (-10, fonte senza categoria nota -> penalità generica); anno non
    # esplicito (-5, default config). Il luogo assente (2026-09-07) non
    # penalizza più.
    assert "comune inferito dalla fonte" in riga["dettaglio_confidenza"]
    assert "anno non esplicito" in riga["dettaglio_confidenza"]
    assert "luogo assente" not in riga["dettaglio_confidenza"]
    assert riga["campi_incerti"] == "data_inizio, organizzatore"
    assert riga["note_estrazione"] == "titolo generico, poche informazioni nel post"


# --- uscita dalla quarantena su ri-estrazione migliore (2026-09-09,
# richiesto dall'utente, caso Caselette 272614985a67, secondo giro): un
# evento già in quarantena, una volta ri-estratto con confidenza sopra
# soglia, deve uscire dalla quarantena invece di restarci bloccato per
# sempre — 'quarantena' è un valore calcolato, non una decisione
# dell'operatore (a differenza di 'ok'/'scartato'). ---


def test_evento_in_quarantena_esce_se_riestratto_con_confidenza_sopra_soglia():
    conn = _conn_di_prova()
    fonte = {"source_id": "sito-prova", "metodo": "T1_html", "endpoint": "https://sito-prova.it/eventi", "comune_riferimento": "Comune Prova"}
    html = (FIXTURES / "esempio_pagina_eventi.html").read_text(encoding="utf-8")

    # Primo giro: confidenza bassa, comune inferito dalla fonte -> quarantena.
    provider1 = _ProviderFinto([
        _risposta_json(confidenza=60).replace('"comune_testuale": "Comune Prova"', '"comune_testuale": null')
    ])
    extractor1 = ExtractorClient(Config(), conn, provider=provider1)
    with patch("src.adapters.html.HtmlAdapter.fetch", return_value=parse_html(html, "sito-prova", fonte["endpoint"])):
        riepilogo1 = pipeline.esegui_fonte(fonte, conn, Config(), extractor1)
    assert riepilogo1["eventi_in_quarantena"] == 1
    riga = conn.execute("SELECT event_id, stato FROM events").fetchone()
    assert riga["stato"] == "quarantena"
    event_id = riga["event_id"]

    # Secondo giro: stesso evento (stessa dedup_key), ri-estratto con
    # confidenza alta e comune esplicito -> deve uscire dalla quarantena.
    provider2 = _ProviderFinto([_risposta_json(confidenza=95)])
    extractor2 = ExtractorClient(Config(), conn, provider=provider2)
    with patch("src.adapters.html.HtmlAdapter.fetch", return_value=parse_html(html, "sito-prova", fonte["endpoint"])):
        riepilogo2 = pipeline.esegui_fonte(fonte, conn, Config(), extractor2)

    assert riepilogo2["eventi_pubblicati"] == 1
    riga = conn.execute("SELECT event_id, stato, confidenza FROM events").fetchone()
    assert riga["event_id"] == event_id  # stesso evento, non un duplicato
    assert riga["stato"] == "nuovo"
    assert riga["confidenza"] == 95


def test_evento_promosso_a_mano_non_viene_toccato_da_un_run_automatico():
    """'ok' (promuovi, decisione dell'operatore via publisher.applica_azioni_quarantena)
    non deve mai essere sovrascritto da un run automatico — a differenza
    di 'quarantena' (calcolato)."""
    conn = _conn_di_prova()
    fonte = {"source_id": "sito-prova", "metodo": "T1_html", "endpoint": "https://sito-prova.it/eventi", "comune_riferimento": "Comune Prova"}
    html = (FIXTURES / "esempio_pagina_eventi.html").read_text(encoding="utf-8")

    provider1 = _ProviderFinto([_risposta_json(confidenza=60).replace('"comune_testuale": "Comune Prova"', '"comune_testuale": null')])
    extractor1 = ExtractorClient(Config(), conn, provider=provider1)
    with patch("src.adapters.html.HtmlAdapter.fetch", return_value=parse_html(html, "sito-prova", fonte["endpoint"])):
        pipeline.esegui_fonte(fonte, conn, Config(), extractor1)

    event_id = conn.execute("SELECT event_id FROM events").fetchone()["event_id"]
    conn.execute("UPDATE events SET stato = 'ok' WHERE event_id = ?", (event_id,))
    conn.commit()

    provider2 = _ProviderFinto([_risposta_json(confidenza=95)])
    extractor2 = ExtractorClient(Config(), conn, provider=provider2)
    with patch("src.adapters.html.HtmlAdapter.fetch", return_value=parse_html(html, "sito-prova", fonte["endpoint"])):
        pipeline.esegui_fonte(fonte, conn, Config(), extractor2)

    riga = conn.execute("SELECT stato FROM events WHERE event_id = ?", (event_id,)).fetchone()
    assert riga["stato"] == "ok"  # non sovrascritto a 'nuovo'


def test_evento_in_quarantena_esce_se_la_fonte_e_promossa_a_t0_jsonld():
    """2026-09-09, richiesto dall'utente (caso Brandizzo 182241c091a6): il
    ramo T0 (ical/jsonld, campi già strutturati, bypassa l'estrattore LLM)
    non applicava il fix 'esci dalla quarantena' — un evento finito in
    quarantena quando la fonte era ancora T1_html restava bloccato per
    sempre anche dopo che la fonte veniva promossa a T0_jsonld e
    ri-confermava lo stesso evento con dati certi."""
    from src.adapters.base import Artefatto

    conn = _conn_di_prova()
    fonte = {"source_id": "comune-prova", "metodo": "T1_html", "endpoint": "https://comune-prova.it/eventi", "comune_riferimento": "Comune Prova"}
    html = (FIXTURES / "esempio_pagina_eventi.html").read_text(encoding="utf-8")

    # Primo giro (T1_html): confidenza bassa, comune inferito -> quarantena.
    provider = _ProviderFinto([_risposta_json(confidenza=60).replace('"comune_testuale": "Comune Prova"', '"comune_testuale": null')])
    extractor = ExtractorClient(Config(), conn, provider=provider)
    with patch("src.adapters.html.HtmlAdapter.fetch", return_value=parse_html(html, "comune-prova", fonte["endpoint"])):
        pipeline.esegui_fonte(fonte, conn, Config(), extractor)

    event_id = conn.execute("SELECT event_id FROM events").fetchone()["event_id"]
    assert conn.execute("SELECT stato FROM events WHERE event_id=?", (event_id,)).fetchone()["stato"] == "quarantena"

    # Secondo giro: la fonte è ora T0_jsonld, stesso evento (stesso
    # titolo/data/comune -> stessa dedup_key) con campi già strutturati.
    art_jsonld = Artefatto(
        source_id="comune-prova", url=fonte["endpoint"], kind="jsonld",
        text="Sagra del Tartufo", titolo="Sagra del Tartufo",
        data_inizio="2026-09-12", data_fine="2026-09-12",
        luogo_testuale="Piazza Roma", descrizione="Degustazioni",
    )
    fonte_jsonld = {**fonte, "metodo": "T0_jsonld"}
    with patch("src.adapters.jsonld.JsonLdAdapter.fetch", return_value=[art_jsonld]):
        riepilogo = pipeline.esegui_fonte(fonte_jsonld, conn, Config())

    assert riepilogo["eventi_pubblicati"] == 1
    riga = conn.execute("SELECT event_id, stato FROM events").fetchone()
    assert riga["event_id"] == event_id  # stesso evento, non un duplicato
    assert riga["stato"] == "nuovo"


# --- riprocessa_fonti_html (2026-09-06, richiesto dall'utente dopo il caso
# Casal Cermelli 309f6c8c01f2): rilancia una fonte T1_html/aggregatore già
# nota, con l'adapter aggiornato, invece di aspettare il prossimo giro
# schedulato — un fix al rilevamento dei link di dettaglio non tocca da
# solo gli eventi già in quarantena da un run precedente. ---


def _inserisci_source(conn: sqlite3.Connection, source_id: str, endpoint: str, tier: str, categoria: str | None = None) -> None:
    conn.execute(
        "INSERT INTO sources (source_id, endpoint, tier, categoria) VALUES (?, ?, ?, ?)",
        (source_id, endpoint, tier, categoria),
    )
    conn.commit()


def test_riprocessa_fonti_html_source_id_sconosciuto_ritorna_errore():
    conn = _conn_di_prova()
    provider = _ProviderFinto([])
    extractor = ExtractorClient(Config(), conn, provider=provider)

    risultati = pipeline.riprocessa_fonti_html(["fonte-mai-vista"], conn, Config(), extractor)

    assert risultati == [{
        "source_id": "fonte-mai-vista", "esito": "errore",
        "dettaglio": "source_id non trovato in sources",
    }]


def test_riprocessa_fonti_html_tier_non_ricorreggibile_ritorna_errore():
    conn = _conn_di_prova()
    # T0_email non è in _METODI_RIPROCESSABILI (richiede credenziali IMAP,
    # non un semplice re-fetch HTTP) — a differenza di T0_ical/T0_jsonld/
    # T0_rss, estesi a _METODI_RIPROCESSABILI il 2026-09-07 per
    # riprocessa_quarantena.
    _inserisci_source(conn, "comune-prova", "imap://mail.comune-prova.it", "T0_email")
    provider = _ProviderFinto([])
    extractor = ExtractorClient(Config(), conn, provider=provider)

    risultati = pipeline.riprocessa_fonti_html(["comune-prova"], conn, Config(), extractor)

    assert risultati[0]["source_id"] == "comune-prova"
    assert risultati[0]["esito"] == "errore"
    assert "non ricorreggibile" in risultati[0]["dettaglio"]


def test_riprocessa_fonti_html_produce_nuovi_eventi_senza_toccare_i_vecchi():
    """Caso Casal Cermelli: un evento vecchio è già in quarantena dalla
    lettura dell'indice (prima del fix), il riprocesso con l'adapter
    aggiornato trova la pagina di dettaglio (con un titolo/descrizione più
    precisi, diversi da quelli letti dall'indice) e produce un evento
    nuovo — il vecchio resta non toccato (l'operatore decide se scartarlo)."""
    conn = _conn_di_prova()
    _inserisci_source(conn, "proloco-prova-sito", "https://proloco-prova.it/eventi", "T1_html", categoria="proloco")

    html_indice = (FIXTURES / "esempio_pagina_eventi.html").read_text(encoding="utf-8")
    art_vecchio = parse_html(html_indice, "proloco-prova-sito", "https://proloco-prova.it/eventi")[0]

    risposta_vecchia = _risposta_json(titolo="Evento generico dall'indice", confidenza=92).replace(
        '"descrizione": "Degustazioni"', '"descrizione": "Poche righe di anteprima"'
    )
    provider = _ProviderFinto([risposta_vecchia])
    extractor = ExtractorClient(Config(), conn, provider=provider)
    with patch("src.adapters.html.HtmlAdapter.fetch", return_value=[art_vecchio]):
        pipeline.esegui_fonte(
            {"source_id": "proloco-prova-sito", "metodo": "T1_html", "endpoint": "https://proloco-prova.it/eventi", "comune_riferimento": "Comune Prova"},
            conn, Config(), extractor,
        )
    id_vecchio = conn.execute("SELECT event_id FROM events").fetchone()["event_id"]

    html_dettaglio = "<html><body><h1>Sagra Vera</h1><p>Sabato 12 settembre 2026, ore 21:00, Piazza Roma.</p></body></html>"
    art_nuovo = parse_html(html_dettaglio, "proloco-prova-sito", "https://proloco-prova.it/eventi/sagra-vera")[0]

    risposta_nuova = _risposta_json(titolo="Sagra Vera", confidenza=92).replace(
        '"descrizione": "Degustazioni"', '"descrizione": "Programma completo con orari e stand gastronomici"'
    )
    provider2 = _ProviderFinto([risposta_nuova])
    extractor2 = ExtractorClient(Config(), conn, provider=provider2)
    with patch("src.adapters.html.HtmlAdapter.fetch", return_value=[art_nuovo]):
        risultati = pipeline.riprocessa_fonti_html(["proloco-prova-sito"], conn, Config(), extractor2)

    assert risultati[0]["esito"] == "nuovi_eventi"
    eventi = conn.execute("SELECT event_id, titolo FROM events ORDER BY titolo").fetchall()
    assert len(eventi) == 2  # il vecchio resta, il nuovo si aggiunge
    assert any(e["event_id"] == id_vecchio for e in eventi)
    assert any(e["titolo"] == "Sagra Vera" for e in eventi)


def test_riprocessa_fonti_html_senza_nuovi_eventi_segnala_nessun_cambiamento():
    conn = _conn_di_prova()
    _inserisci_source(conn, "proloco-prova-sito", "https://proloco-prova.it/eventi", "T1_html")

    html_indice = (FIXTURES / "esempio_pagina_eventi.html").read_text(encoding="utf-8")
    art = parse_html(html_indice, "proloco-prova-sito", "https://proloco-prova.it/eventi")[0]

    provider = _ProviderFinto([_risposta_json(confidenza=92)])
    extractor = ExtractorClient(Config(), conn, provider=provider)

    with patch("src.adapters.html.HtmlAdapter.fetch", return_value=[]):
        risultati = pipeline.riprocessa_fonti_html(["proloco-prova-sito"], conn, Config(), extractor)

    assert risultati[0]["esito"] == "nessun_cambiamento"


# --- riprocessa_quarantena (2026-09-07, richiesto dall'utente): un solo
# comando che scorre tutti gli eventi in quarantena e smista da solo il
# tipo di fonte (sito HTML, feed Instagram, feed Facebook) invece di
# richiedere all'operatore di sapere a mano quale comando/source_id/
# event_id usare per ciascuno. ---


def _inserisci_evento_quarantena(conn: sqlite3.Connection, event_id: str, source_id: str, comune: str = "Comune Prova") -> None:
    conn.execute(
        """
        INSERT INTO events (event_id, dedup_key, titolo, tipologia, data_inizio, comune, stato, primo_visto, ultimo_visto)
        VALUES (?, ?, 'Evento in quarantena', 'altro', '2026-09-12', ?, 'quarantena', '2026-09-01', '2026-09-01')
        """,
        (event_id, event_id, comune),
    )
    conn.execute(
        "INSERT INTO event_sources (event_id, source_id, url, seen_at) VALUES (?, ?, '', '2026-09-01T00:00:00')",
        (event_id, source_id),
    )
    conn.commit()


def test_riprocessa_quarantena_smista_fonte_html():
    conn = _conn_di_prova()
    _inserisci_source(conn, "proloco-prova-sito", "https://proloco-prova.it/eventi", "T1_html")
    _inserisci_evento_quarantena(conn, "ev-html-1", "proloco-prova-sito")

    provider = _ProviderFinto([])
    extractor = ExtractorClient(Config(), conn, provider=provider)

    with patch("src.adapters.html.HtmlAdapter.fetch", return_value=[]):
        riepilogo = pipeline.riprocessa_quarantena(conn, Config(), extractor)

    assert riepilogo["totale_in_quarantena"] == 1
    assert len(riepilogo["html"]) == 1
    assert riepilogo["html"][0]["source_id"] == "proloco-prova-sito"
    assert riepilogo["instagram"] == []
    assert riepilogo["facebook_non_riprocessabili"] == []


def test_riprocessa_quarantena_smista_feed_instagram():
    conn = _conn_di_prova()
    _inserisci_evento_quarantena(conn, "ev-ig-1", "feed-instagram-prolocoprova")

    provider = _ProviderFinto([])
    extractor = ExtractorClient(Config(), conn, provider=provider)

    with patch("src.feed_social.riprocessa_eventi_instagram", return_value=[
        {"event_id": "ev-ig-1", "esito": "nessun_nuovo_evento_creato", "dettaglio": "ok"}
    ]) as mock_riprocessa:
        riepilogo = pipeline.riprocessa_quarantena(conn, Config(), extractor)

    chiamata = mock_riprocessa.call_args[0]
    assert chiamata[0] == ["ev-ig-1"]
    assert chiamata[1] is conn
    assert chiamata[3] is extractor
    assert riepilogo["totale_in_quarantena"] == 1
    assert riepilogo["instagram"] == [{"event_id": "ev-ig-1", "esito": "nessun_nuovo_evento_creato", "dettaglio": "ok"}]
    assert riepilogo["html"] == []
    assert riepilogo["facebook_non_riprocessabili"] == []


def test_riprocessa_quarantena_segnala_feed_facebook_non_riprocessabile():
    conn = _conn_di_prova()
    _inserisci_evento_quarantena(conn, "ev-fb-1", "feed-facebook-prolocoprova")

    provider = _ProviderFinto([])
    extractor = ExtractorClient(Config(), conn, provider=provider)

    riepilogo = pipeline.riprocessa_quarantena(conn, Config(), extractor)

    assert riepilogo["totale_in_quarantena"] == 1
    assert riepilogo["html"] == []
    assert riepilogo["instagram"] == []
    assert len(riepilogo["facebook_non_riprocessabili"]) == 1
    assert riepilogo["facebook_non_riprocessabili"][0]["event_id"] == "ev-fb-1"
    assert "non riapribile" in riepilogo["facebook_non_riprocessabili"][0]["dettaglio"]


def test_riprocessa_quarantena_nessun_evento_ritorna_liste_vuote():
    conn = _conn_di_prova()
    provider = _ProviderFinto([])
    extractor = ExtractorClient(Config(), conn, provider=provider)

    riepilogo = pipeline.riprocessa_quarantena(conn, Config(), extractor)

    assert riepilogo == {
        "totale_in_quarantena": 0, "instagram": [], "html": [], "facebook_non_riprocessabili": [],
    }


def test_riprocessa_quarantena_stessa_fonte_html_rilanciata_una_sola_volta():
    """Due eventi diversi in quarantena dalla stessa fonte non devono
    far rilanciare la fonte due volte nello stesso giro (lavoro ripetuto
    senza guadagno)."""
    conn = _conn_di_prova()
    _inserisci_source(conn, "proloco-prova-sito", "https://proloco-prova.it/eventi", "T1_html")
    _inserisci_evento_quarantena(conn, "ev-html-1", "proloco-prova-sito")
    conn.execute(
        """
        INSERT INTO events (event_id, dedup_key, titolo, tipologia, data_inizio, comune, stato, primo_visto, ultimo_visto)
        VALUES ('ev-html-2', 'ev-html-2', 'Altro evento', 'altro', '2026-09-13', 'Comune Prova', 'quarantena', '2026-09-01', '2026-09-01')
        """
    )
    conn.execute(
        "INSERT INTO event_sources (event_id, source_id, url, seen_at) VALUES ('ev-html-2', 'proloco-prova-sito', '', '2026-09-01T00:00:00')"
    )
    conn.commit()

    provider = _ProviderFinto([])
    extractor = ExtractorClient(Config(), conn, provider=provider)

    with patch("src.adapters.html.HtmlAdapter.fetch", return_value=[]) as mock_fetch:
        riepilogo = pipeline.riprocessa_quarantena(conn, Config(), extractor)

    assert mock_fetch.call_count == 1
    assert len(riepilogo["html"]) == 1


def test_comune_riferimento_da_source_id_deriva_dallo_slug():
    """Bug reale trovato il 2026-09-12 (caso comune-calosso): il worker del
    giro schedulato (run.py _elabora_una_fonte_worker) impostava sempre
    comune_riferimento=None invece di derivarlo dal source_id 'comune-*' —
    per le fonti T0 strutturate (pa_design_system/jsonld, senza estrattore
    LLM che possa risolvere il comune dal testo), questo faceva scartare
    silenziosamente ogni evento la cui pagina non nomina esplicitamente il
    comune. 159 fonti su 386 mostravano il sintomo (eventi trovati mai
    pubblicati)."""
    conn = _conn_di_prova()
    conn.execute(
        "INSERT INTO comuni (istat, comune, alias, provincia, lat, lon, km, minuti, fascia, attivo) "
        "VALUES ('2', 'Calosso', 'Calosso', 'AT', 44.79, 8.26, 0.0, 0, 'A', 'si')"
    )
    conn.commit()

    assert pipeline.comune_riferimento_da_source_id("comune-calosso", conn) == "Calosso"
    assert pipeline.comune_riferimento_da_source_id("comune-inesistente", conn) is None
    assert pipeline.comune_riferimento_da_source_id("proloco-calosso-sito", conn) is None


def test_fonte_t0_pa_design_system_senza_comune_riferimento_esplicito_scarta_evento():
    """Controprova del bug: senza comune_riferimento (come faceva il worker
    prima del fix), un artefatto T0 strutturato senza comune_testuale
    esplicito nel titolo/descrizione non produce alcun evento — a
    differenza di quando comune_riferimento è valorizzato (test successivo)."""
    from src.adapters.base import Artefatto

    conn = _conn_di_prova()
    fonte = {"source_id": "comune-prova", "metodo": "T0_pa_design_system", "endpoint": "https://x.it/Eventi", "comune_riferimento": None}
    art = Artefatto(
        source_id="comune-prova", url="https://x.it/Dettaglionews?IDNews=1", kind="html",
        text="Fiera del Rapulè", titolo="Fiera del Rapulè", data_inizio="2026-10-16", data_fine="2026-10-18",
    )

    with patch("src.adapters.pa_design_system.PaDesignSystemAdapter.fetch", return_value=[art]):
        riepilogo = pipeline.esegui_fonte(fonte, conn, Config())

    assert riepilogo["eventi_pubblicati"] == 0
    assert conn.execute("SELECT COUNT(*) AS n FROM events").fetchone()["n"] == 0


def test_fonte_t0_pa_design_system_con_comune_riferimento_pubblica_evento():
    """Con comune_riferimento valorizzato (il fix), lo stesso artefatto
    dell'evento precedente viene pubblicato correttamente."""
    from src.adapters.base import Artefatto

    conn = _conn_di_prova()
    fonte = {"source_id": "comune-prova", "metodo": "T0_pa_design_system", "endpoint": "https://x.it/Eventi", "comune_riferimento": "Comune Prova"}
    art = Artefatto(
        source_id="comune-prova", url="https://x.it/Dettaglionews?IDNews=1", kind="html",
        text="Fiera del Rapulè", titolo="Fiera del Rapulè", data_inizio="2026-10-16", data_fine="2026-10-18",
    )

    with patch("src.adapters.pa_design_system.PaDesignSystemAdapter.fetch", return_value=[art]):
        riepilogo = pipeline.esegui_fonte(fonte, conn, Config())

    assert riepilogo["eventi_pubblicati"] == 1
    evento = conn.execute("SELECT titolo, comune FROM events").fetchone()
    assert evento["comune"] == "Comune Prova"
