"""M3: adattatore aggregatori regionali con rendering Playwright
(visitlmr.it). Nessun browser reale nei test (15.1 regola 8) — solo la
logica pura di filtro/normalizzazione URL, con un finto oggetto 'pagina'
per isolare _raccogli_link_eventi dal vero browser."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.adapters.aggregatore_regionale import _raccogli_link_eventi


class _PaginaFinta:
    def __init__(self, href_grezzi):
        self._href_grezzi = href_grezzi

    def evaluate(self, script_js):
        return self._href_grezzi


def test_raccogli_link_eventi_filtra_solo_pattern_eventi():
    pagina = _PaginaFinta([
        "/it/eventi/eventi-top/langhe/settembre/palio-di-asti",
        "/it/carrello",
        "/it/esperienze",
        "/it/eventi/eventi-top/roero/agosto/bra-s",
    ])
    link = _raccogli_link_eventi(pagina, "https://www.visitlmr.it/it/calendario-eventi")
    assert len(link) == 2
    assert all("/it/eventi/" in l for l in link)


def test_raccogli_link_eventi_risolve_url_relativi_in_assoluti():
    pagina = _PaginaFinta(["/it/eventi/eventi-top/langhe/settembre/palio-di-asti"])
    link = _raccogli_link_eventi(pagina, "https://www.visitlmr.it/it/calendario-eventi")
    assert link == ["https://www.visitlmr.it/it/eventi/eventi-top/langhe/settembre/palio-di-asti"]


def test_raccogli_link_eventi_deduplica():
    pagina = _PaginaFinta([
        "/it/eventi/eventi-top/langhe/settembre/palio-di-asti",
        "/it/eventi/eventi-top/langhe/settembre/palio-di-asti",
        "https://www.visitlmr.it/it/eventi/eventi-top/langhe/settembre/palio-di-asti",
    ])
    link = _raccogli_link_eventi(pagina, "https://www.visitlmr.it/it/calendario-eventi")
    assert len(link) == 1


def test_raccogli_link_eventi_ignora_href_vuoti_o_none():
    pagina = _PaginaFinta(["", None, "/it/eventi/eventi-top/langhe/settembre/palio-di-asti"])
    link = _raccogli_link_eventi(pagina, "https://www.visitlmr.it/it/calendario-eventi")
    assert len(link) == 1


def test_raccogli_link_eventi_nessun_match_ritorna_lista_vuota():
    pagina = _PaginaFinta(["/it/carrello", "/it/esperienze", "/it/meteo-e-webcam"])
    link = _raccogli_link_eventi(pagina, "https://www.visitlmr.it/it/calendario-eventi")
    assert link == []
