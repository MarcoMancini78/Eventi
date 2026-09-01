"""Adattatore per famiglia di piattaforma (12.5, L3): template AGID
"pa_design_system" nella variante legacy senza JSON-LD (endpoint tipo
.../Eventi, distinto dalla variante ComWeb/ePublic già coperta da
adapters/jsonld.py con endpoint .../vivere-il-comune/eventi).

Trovato ispezionando dal vivo un campione di 6 comuni classificati
`pa_design_system` da fingerprint.py (17-lavoro-residuo.md, 2026-09-01):
struttura HTML identica su comuni di province diverse (AT, CN, VC, TO,
AL) — un `.card-wrapper` per evento, categoria in un link `?idCat=N`,
data nel formato "GG/MM/AAAA - GG/MM/AAAA" in `.category-top .data`,
titolo in `.card-title`, sintesi in `.text-paragraph-card`.

T0 puro: nessuna chiamata LLM, gli stessi campi che l'estrattore
avrebbe dovuto dedurre da un HTML generico sono già qui, strutturati.
"""
from __future__ import annotations

import hashlib
import re

import httpx
import lxml.html

from .base import Adapter, Artefatto

_TIMEOUT_SECONDI = 15
_USER_AGENT_BROWSER = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)

_PATTERN_DATA = re.compile(r"(\d{2})/(\d{2})/(\d{4})\s*(?:-\s*(\d{2})/(\d{2})/(\d{4}))?")


def _converti_data(gg: str, mm: str, aaaa: str) -> str:
    return f"{aaaa}-{mm}-{gg}"


def _estrai_date(testo_data: str) -> tuple[str | None, str | None]:
    """'12/08/2026 - 12/08/2026' -> ('2026-08-12', '2026-08-12'). Anche il
    solo giorno singolo, senza intervallo, è nel formato del sito reale."""
    m = _PATTERN_DATA.search(testo_data or "")
    if not m:
        return None, None
    gg1, mm1, aaaa1, gg2, mm2, aaaa2 = m.groups()
    inizio = _converti_data(gg1, mm1, aaaa1)
    fine = _converti_data(gg2, mm2, aaaa2) if gg2 else inizio
    return inizio, fine


def _con_classe(nodo, classe: str):
    """Equivalente di getElementsByClassName tramite XPath (contains su
    class con spazi ai bordi, per non matchare 'card-title-x' quando si
    cerca 'card-title'). Il pacchetto 'cssselect' non è tra le dipendenze
    del progetto — XPath nativo di lxml basta e non ne aggiunge una nuova.
    'descendant-or-self::' invece di '//' (solo discendenti): un frammento
    HTML minimale (es. un test, o un albero costruito da un solo elemento)
    fa diventare quell'elemento stesso la radice — '//' lo salterebbe."""
    return nodo.xpath(f'descendant-or-self::*[contains(concat(" ", normalize-space(@class), " "), " {classe} ")]')


def parse_pa_design_system(html: str, source_id: str, fetch_url: str) -> list[Artefatto]:
    try:
        albero = lxml.html.fromstring(html)
    except Exception:
        return []

    artefatti: list[Artefatto] = []
    for card in _con_classe(albero, "card-wrapper"):
        titolo_el = _con_classe(card, "card-title")
        if not titolo_el:
            continue  # non tutti i .card-wrapper sono un evento (es. widget feedback pagina)
        titolo = titolo_el[0].text_content().strip()
        if not titolo:
            continue

        data_el = _con_classe(card, "data")
        data_inizio, data_fine = _estrai_date(data_el[0].text_content() if data_el else "")
        if not data_inizio:
            continue  # 04.7: senza data non è un evento pubblicabile, non se ne indovina una

        descrizione_el = _con_classe(card, "text-paragraph-card")
        descrizione = descrizione_el[0].text_content().strip() if descrizione_el else None

        link_el = titolo_el[0].getparent()
        url_evento = fetch_url
        while link_el is not None:
            href = link_el.get("href")
            if href:
                from urllib.parse import urljoin

                url_evento = urljoin(fetch_url, href)
                break
            link_el = link_el.getparent()

        testo = f"{titolo}\n{descrizione or ''}".strip()
        artefatti.append(
            Artefatto(
                source_id=source_id,
                url=url_evento,
                kind="html",
                text=testo,
                titolo=titolo,
                data_inizio=data_inizio,
                data_fine=data_fine,
                descrizione=descrizione,
                raw_hash=hashlib.sha1(f"{titolo}|{data_inizio}".encode("utf-8")).hexdigest(),
            )
        )
    return artefatti


class PaDesignSystemAdapter(Adapter):
    def fetch(self, fonte: dict) -> list[Artefatto]:
        endpoint = fonte["endpoint"]
        with httpx.Client(timeout=_TIMEOUT_SECONDI, follow_redirects=True) as client:
            risposta = client.get(endpoint, headers={"User-Agent": fonte.get("user_agent", _USER_AGENT_BROWSER)})
            risposta.raise_for_status()
        return parse_pa_design_system(risposta.text, fonte["source_id"], endpoint)
