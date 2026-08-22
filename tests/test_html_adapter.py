"""M3/M5: adattatore HTML generico, su fixture offline (15.1 regola 8)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.adapters.html import contiene_pattern_di_data, parse_html

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
