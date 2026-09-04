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


# --- 2026-09-05, richiesto dall'utente (caso Alba 9af7cff0830e): i link di
# dettaglio vanno seguiti SEMPRE, non solo quando l'indice non basta da
# solo — un indice con più anteprime brevi produce comunque un artefatto,
# ma titolo/descrizione/URL/immagine del dettaglio sono sempre più precisi. ---

_HTML_INDICE_CON_DATE_E_LINK_DOMINANTI = """<html><body>
<main>
<h1>Prossimi eventi</h1>
<article><h2>Sagra del Tartufo</h2><p>Sabato 12 settembre 2026, Piazza Roma.</p></article>
<article><h2>Mercatino</h2><p>Domenica 20/09, Via Garibaldi.</p></article>
</main>
<a href="https://comune-prova.it/eventi/sagra-del-tartufo/">Sagra del Tartufo</a>
<a href="https://comune-prova.it/eventi/mercatino-antiquariato/">Mercatino</a>
<a href="https://comune-prova.it/eventi/concerto-piazza/">Concerto</a>
<a href="https://comune-prova.it/eventi/mostra-fotografica/">Mostra</a>
<a href="https://comune-prova.it/eventi/festa-patronale/">Festa patronale</a>
</body></html>"""


def test_html_adapter_fetch_segue_link_dettaglio_anche_se_indice_ha_gia_date():
    """Il caso reale Alba: l'indice ha già >= 2 pattern di data (produrrebbe
    un artefatto da solo, con titolo/descrizione generici), ma esiste un
    prefisso di link dominante -> fetch deve preferire i dettagli."""
    html_dettaglio = (FIXTURES / "esempio_pagina_dettaglio_evento.html").read_text(encoding="utf-8")

    risposta_indice = Mock(status_code=200, text=_HTML_INDICE_CON_DATE_E_LINK_DOMINANTI)
    risposta_indice.raise_for_status = Mock()
    risposta_dettaglio = Mock(status_code=200, text=html_dettaglio)
    risposta_dettaglio.raise_for_status = Mock()

    client_finto = Mock()
    client_finto.get = Mock(side_effect=[risposta_indice] + [risposta_dettaglio] * 5)
    client_finto.__enter__ = Mock(return_value=client_finto)
    client_finto.__exit__ = Mock(return_value=False)

    with patch("src.adapters.html.httpx.Client", return_value=client_finto):
        artefatti = HtmlAdapter().fetch({"source_id": "comune-prova", "endpoint": "https://comune-prova.it/eventi/"})

    # 5 artefatti dai dettagli, non 1 dall'indice: url punta alla notizia
    # vera, non alla pagina elenco generica.
    assert len(artefatti) == 5
    assert all(a.url.startswith("https://comune-prova.it/eventi/") and a.url != "https://comune-prova.it/eventi/" for a in artefatti)


def test_html_adapter_fetch_scarica_og_image_dal_dettaglio(tmp_path, monkeypatch):
    """2026-09-05: la pagina di dettaglio con <meta og:image> deve produrre
    un artefatto con image_paths popolato (file scaricato in locale),
    stesso pattern già usato per le immagini social."""
    import src.adapters.html as html_mod

    monkeypatch.setattr(html_mod, "_CARTELLA_IMMAGINI_HTML", tmp_path)

    html_dettaglio_con_immagine = """<html><head>
    <meta property="og:image" content="https://comune-prova.it/img/locandina.jpg" />
    </head><body>
    <h1>Sagra del Tartufo</h1>
    <p>Sabato 12 settembre 2026, ore 21:00, Piazza Roma.</p>
    </body></html>"""

    risposta_indice = Mock(status_code=200, text=_HTML_INDICE_CON_DATE_E_LINK_DOMINANTI)
    risposta_indice.raise_for_status = Mock()
    risposta_dettaglio = Mock(status_code=200, text=html_dettaglio_con_immagine)
    risposta_dettaglio.raise_for_status = Mock()
    risposta_immagine = Mock(status_code=200, content=b"\xff\xd8\xff\xe0finto-jpeg")
    risposta_immagine.raise_for_status = Mock()

    client_finto = Mock()
    client_finto.get = Mock(side_effect=[risposta_indice] + [risposta_dettaglio, risposta_immagine] * 5)
    client_finto.__enter__ = Mock(return_value=client_finto)
    client_finto.__exit__ = Mock(return_value=False)

    with patch("src.adapters.html.httpx.Client", return_value=client_finto):
        artefatti = HtmlAdapter().fetch({"source_id": "comune-prova", "endpoint": "https://comune-prova.it/eventi/"})

    assert len(artefatti) == 5
    assert artefatti[0].image_paths
    assert Path(artefatti[0].image_paths[0]).read_bytes() == b"\xff\xd8\xff\xe0finto-jpeg"


def test_estrai_og_image_trova_meta_tag():
    html = '<html><head><meta property="og:image" content="https://x.it/img.jpg"/></head></html>'
    from src.adapters.html import estrai_og_image

    assert estrai_og_image(html, "https://x.it/") == "https://x.it/img.jpg"


def test_estrai_og_image_assente_ritorna_none():
    html = "<html><head></head></html>"
    from src.adapters.html import estrai_og_image

    assert estrai_og_image(html, "https://x.it/") is None


def test_trova_link_dettaglio_dominanti_gestisce_prefisso_lingua():
    """Caso reale Alba: primo segmento di path sempre 'it' (lingua) per
    menu E notizie, con un gruppo parallelo di slug numerici (pagine
    categoria) che confonderebbe una soglia puramente quantitativa."""
    html = "<html><body>" + "".join(
        f'<a href="https://x.it/it/news/notizia-vera-numero-{i}">n{i}</a>' for i in range(6)
    ) + "".join(
        f'<a href="https://x.it/it/news-category/{1000+i}">c{i}</a>' for i in range(6)
    ) + '<a href="https://x.it/it/contatti">Contatti</a>' + "</body></html>"

    from src.adapters.html import trova_link_dettaglio_dominanti

    link = trova_link_dettaglio_dominanti(html, "https://x.it/it/news/")
    assert len(link) == 6
    assert all("/it/news/notizia-vera" in l for l in link)
    assert not any("news-category" in l for l in link)
