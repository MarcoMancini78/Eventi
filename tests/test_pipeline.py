"""M2: criterio di accettazione end-to-end su fonte T0 (ical), senza rete (fixture)."""
import sqlite3
import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src import pipeline, store
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
