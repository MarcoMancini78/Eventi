"""M2: adattatori T0 su fixture offline, nessuna chiamata di rete (15.1 regola 8)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.adapters.ical import parse_ical
from src.adapters.jsonld import parse_jsonld
from src.adapters.rss import parse_rss

FIXTURES = Path(__file__).parent / "fixtures"


def test_parse_ical_estrae_due_eventi_con_orario_e_senza():
    testo = (FIXTURES / "esempio.ics").read_text(encoding="utf-8")
    artefatti = parse_ical(testo, source_id="comune-prova", fetch_url="https://comune-prova.it/eventi.ics")

    assert len(artefatti) == 2

    sagra = artefatti[0]
    assert sagra.titolo == "SAGRA DEL TARTUFO"
    assert sagra.data_inizio == "2026-09-12"
    assert sagra.ora_inizio == "21:00"
    assert sagra.luogo_testuale == "Piazza Roma"
    assert sagra.url == "https://comune-prova.it/eventi/sagra-tartufo"

    mercatino = artefatti[1]
    assert mercatino.data_inizio == "2026-09-20"
    assert mercatino.ora_inizio is None


def test_parse_rss_valorizza_context_date_non_data_evento():
    testo = (FIXTURES / "esempio_rss.xml").read_text(encoding="utf-8")
    artefatti = parse_rss(testo, source_id="comune-prova", fetch_url="https://comune-prova.it/feed")

    assert len(artefatti) == 1
    art = artefatti[0]
    assert "Concerto in piazza" in art.text
    assert art.context_date == "2026-08-25"  # data di pubblicazione, non dell'evento (04.3)
    assert art.data_inizio is None  # va estratta dal testo dall'LLM, qui non c'è


def test_parse_jsonld_estrae_campi_strutturati_senza_llm():
    html = (FIXTURES / "esempio_jsonld.html").read_text(encoding="utf-8")
    artefatti = parse_jsonld(html, source_id="teatro-prova", fetch_url="https://teatro-prova.it/eventi")

    assert len(artefatti) == 1
    art = artefatti[0]
    assert art.titolo == "Rassegna Teatrale Autunnale"
    assert art.data_inizio == "2026-10-05"
    assert art.luogo_testuale == "Teatro Comunale"
    assert art.url == "https://teatro-prova.it/eventi/rassegna-autunnale"
