"""16.10-simile, caso reale Acqui Terme (2026-09-17): T0_jsonld_indice —
un indice che elenca eventi ma non espone JSON-LD, mentre ogni pagina di
dettaglio sì (portale turistico WordPress separato dal sito istituzionale)."""
import sys
from pathlib import Path
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.adapters.jsonld_indice import JsonLdIndiceAdapter, trova_link_dettaglio_evento

_HTML_INDICE_SENZA_JSONLD = """<html><body>
<a href="https://turismo-prova.it/event/festa-uno/">Festa uno</a>
<a href="https://turismo-prova.it/event/festa-due/">Festa due</a>
<a href="https://turismo-prova.it/event/festa-tre/">Festa tre</a>
<a href="https://turismo-prova.it/event/festa-quattro/">Festa quattro</a>
<a href="https://turismo-prova.it/event/festa-cinque/">Festa cinque</a>
</body></html>"""

_HTML_DETTAGLIO_CON_EVENT = """<html><head>
<script type="application/ld+json">
{"@context":"https://schema.org","@graph":[
  {"@type":"Organization","name":"Visit Prova"},
  {"@type":"Event","name":"Festa dello Sport","startDate":"2026-09-16T20:45:00+00:00",
   "endDate":"2026-09-16T23:45:00+00:00","url":"https://turismo-prova.it/event/festa-uno/",
   "description":"Un appuntamento sportivo",
   "location":{"@type":"Place","name":"Cinema Teatro Ariston"}}
]}
</script>
</head><body>Festa dello Sport</body></html>"""

_HTML_INDICE_SENZA_LINK_DOMINANTI = """<html><body>
<a href="https://turismo-prova.it/chi-siamo/">Chi siamo</a>
<a href="https://turismo-prova.it/contatti/">Contatti</a>
</body></html>"""


def _client_finto(risposte: list):
    client_finto = Mock()
    client_finto.get = Mock(side_effect=risposte)
    client_finto.__enter__ = Mock(return_value=client_finto)
    client_finto.__exit__ = Mock(return_value=False)
    return client_finto


def _risposta(testo: str):
    r = Mock(status_code=200, text=testo)
    r.raise_for_status = Mock()
    return r


def test_fetch_segue_link_dettaglio_ed_estrae_jsonld_da_ciascuno():
    risposta_indice = _risposta(_HTML_INDICE_SENZA_JSONLD)
    risposta_dettaglio = _risposta(_HTML_DETTAGLIO_CON_EVENT)

    client_finto = _client_finto([risposta_indice] + [risposta_dettaglio] * 5)

    with patch("src.adapters.jsonld_indice.httpx.Client", return_value=client_finto):
        artefatti = JsonLdIndiceAdapter().fetch(
            {"source_id": "comune-acqui-terme-turismo", "endpoint": "https://turismo-prova.it/events/"}
        )

    assert len(artefatti) == 5
    assert artefatti[0].titolo == "Festa dello Sport"
    assert artefatti[0].data_inizio == "2026-09-16"
    assert artefatti[0].luogo_testuale == "Cinema Teatro Ariston"
    assert artefatti[0].source_id == "comune-acqui-terme-turismo"


def test_fetch_senza_link_evento_ripiega_sull_indice_stesso():
    """Se non trova nessun link con path 'event/...', prova comunque a
    estrarre JSON-LD dalla pagina indice stessa (coerente con jsonld.py
    puro) invece di fallire silenziosamente."""
    risposta_indice = _risposta(_HTML_INDICE_SENZA_LINK_DOMINANTI)
    client_finto = _client_finto([risposta_indice])

    with patch("src.adapters.jsonld_indice.httpx.Client", return_value=client_finto):
        artefatti = JsonLdIndiceAdapter().fetch(
            {"source_id": "comune-prova", "endpoint": "https://turismo-prova.it/events/"}
        )

    assert artefatti == []
    assert client_finto.get.call_count == 1  # nessun tentativo di seguire dettagli inesistenti


def test_trova_link_dettaglio_evento_ignora_pagine_categoria_plurali():
    """Bug reale trovato 2026-09-17 (Acqui Terme): un'euristica generica di
    conteggio ('prefisso più frequente') sceglierebbe '/events/category/...'
    e '/events/elenco/...' (plurale, pagine categoria/filtro, numerose e
    tutte diverse tra loro) invece di '/event/{slug}/' (singolare, i veri
    eventi, ripetuti 2 volte ciascuno ma meno numerosi come set). Il
    filtro esplicito sul segmento singolare 'event' evita la confusione."""
    html = """<html><body>
    <a href="https://x.it/events/category/arte-e-cultura/">Arte</a>
    <a href="https://x.it/events/category/cinema/">Cinema</a>
    <a href="https://x.it/events/category/concerto/">Concerto</a>
    <a href="https://x.it/events/category/enogastronomia/">Enogastronomia</a>
    <a href="https://x.it/events/category/sport/">Sport</a>
    <a href="https://x.it/events/category/shopping/">Shopping</a>
    <a href="https://x.it/events/elenco/">Elenco</a>
    <a href="https://x.it/event/festa-uno/">Festa uno</a>
    <a href="https://x.it/event/festa-due/">Festa due</a>
    </body></html>"""
    link = trova_link_dettaglio_evento(html, "https://x.it/events/")
    assert link == ["https://x.it/event/festa-due/", "https://x.it/event/festa-uno/"]


def test_fetch_un_dettaglio_irraggiungibile_non_ferma_gli_altri():
    """15.1 regola 4: isolamento totale anche a livello di singolo link."""
    import httpx as httpx_reale

    risposta_indice = _risposta(_HTML_INDICE_SENZA_JSONLD)
    risposta_dettaglio_ok = _risposta(_HTML_DETTAGLIO_CON_EVENT)

    def _errore_http(*args, **kwargs):
        raise httpx_reale.HTTPStatusError("errore", request=Mock(), response=Mock())

    risposta_fallita = Mock()
    risposta_fallita.raise_for_status = Mock(side_effect=_errore_http)

    client_finto = _client_finto(
        [risposta_indice, risposta_fallita, risposta_dettaglio_ok, risposta_dettaglio_ok, risposta_dettaglio_ok, risposta_dettaglio_ok]
    )

    with patch("src.adapters.jsonld_indice.httpx.Client", return_value=client_finto):
        artefatti = JsonLdIndiceAdapter().fetch(
            {"source_id": "comune-prova", "endpoint": "https://turismo-prova.it/events/"}
        )

    assert len(artefatti) == 4  # 5 link, 1 fallito, 4 riusciti
