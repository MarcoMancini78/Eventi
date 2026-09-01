"""M3/M5: adattatore HTML generico, su fixture offline (15.1 regola 8)."""
import sys
from pathlib import Path
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.adapters.html import HtmlAdapter, contiene_pattern_di_data, parse_html, trova_link_dettaglio_dominanti

FIXTURES = Path(__file__).parent / "fixtures"


def test_pagina_con_eventi_produce_un_artefatto():
    html = (FIXTURES / "esempio_pagina_eventi.html").read_text(encoding="utf-8")
    artefatti = parse_html(html, source_id="comune-prova", fetch_url="https://comune-prova.it/eventi")

    assert len(artefatti) == 1
    art = artefatti[0]
    assert "Piazza Roma" in art.text
    assert "cookie policy" not in art.text.lower()  # trafilatura rimuove nav/footer (04.3)


def test_pagina_senza_pattern_di_data_viene_scartata_prima_dellestrattore():
    html = (FIXTURES / "esempio_pagina_senza_eventi.html").read_text(encoding="utf-8")
    artefatti = parse_html(html, source_id="comune-prova", fetch_url="https://comune-prova.it/")

    assert artefatti == []


def test_contiene_pattern_di_data_soglia_minima():
    assert contiene_pattern_di_data("Sabato 12 settembre alle 19:00") is True
    assert contiene_pattern_di_data("Ufficio protocollo aperto al pubblico") is False


def test_trova_link_dettaglio_dominanti_riconosce_prefisso_ricorrente():
    """2026-09-01, caso reale: Attraverso Festival ha una pagina indice
    (titolo+prezzo per evento, senza date) che linka 47 pagine /eventi/...
    con la data — nessun altro prefisso di path supera le 2 occorrenze
    (link di navigazione in header/footer)."""
    html = (FIXTURES / "esempio_pagina_indice_senza_date.html").read_text(encoding="utf-8")
    link = trova_link_dettaglio_dominanti(html, "https://festival-prova.it/programma/")

    assert len(link) == 5
    assert all("/eventi/" in l for l in link)
    assert not any("contatti" in l for l in link)


def test_trova_link_dettaglio_dominanti_rispetta_il_limite_massimo():
    html = "<html><body>" + "".join(
        f'<a href="https://x.it/eventi/e{i}/">e{i}</a>' for i in range(20)
    ) + "</body></html>"
    link = trova_link_dettaglio_dominanti(html, "https://x.it/programma/")

    assert len(link) == 10  # _MAX_LINK_DETTAGLIO


def test_trova_link_dettaglio_dominanti_nessun_prefisso_dominante():
    """Poche voci ripetute solo 1-2 volte (navigazione normale, non un
    elenco) non devono attivare il fallback."""
    html = """<html><body>
    <a href="https://x.it/chi-siamo/">Chi siamo</a>
    <a href="https://x.it/contatti/">Contatti</a>
    <a href="https://x.it/privacy/">Privacy</a>
    </body></html>"""
    assert trova_link_dettaglio_dominanti(html, "https://x.it/") == []


def test_html_adapter_fetch_segue_link_dettaglio_quando_indice_senza_date():
    """Collaudo end-to-end del fallback (mock httpx, nessuna rete reale,
    15.1 regola 8): la pagina indice non ha date -> fetch segue il link
    di dettaglio dominante -> quella pagina SI ha date -> un artefatto."""
    html_indice = (FIXTURES / "esempio_pagina_indice_senza_date.html").read_text(encoding="utf-8")
    html_dettaglio = (FIXTURES / "esempio_pagina_dettaglio_evento.html").read_text(encoding="utf-8")

    risposta_indice = Mock(status_code=200, text=html_indice)
    risposta_indice.raise_for_status = Mock()
    risposta_dettaglio = Mock(status_code=200, text=html_dettaglio)
    risposta_dettaglio.raise_for_status = Mock()

    client_finto = Mock()
    client_finto.get = Mock(side_effect=[risposta_indice] + [risposta_dettaglio] * 5)
    client_finto.__enter__ = Mock(return_value=client_finto)
    client_finto.__exit__ = Mock(return_value=False)

    with patch("src.adapters.html.httpx.Client", return_value=client_finto):
        artefatti = HtmlAdapter().fetch({"source_id": "festival-prova", "endpoint": "https://festival-prova.it/programma/"})

    assert len(artefatti) == 5
    assert "Piazza Roma" in artefatti[0].text
    assert artefatti[0].url == "https://festival-prova.it/eventi/spettacolo-cinque/"  # ordine alfabetico dei link trovati
