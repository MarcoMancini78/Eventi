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

Seconda variante (2026-09-14, comuni classificati `wordpress` dal
fingerprinting — nessuno dei 91 espone un endpoint REST eventi utile,
verificato su un campione di 15, ma 56/91 usano di fatto la STESSA
famiglia di template Bootstrap Italia, solo con markup leggermente
diverso): data testuale italiana in `.card-calendar .card-day`
("20 Maggio 2000" o "11 Giugno 2026 - 1 Novembre 2026", non
"GG/MM/AAAA"), titolo in `.cmp-list-card-img__body-title` invece di
`.card-title`. Un solo parser prova prima il formato Dettaglionews
esistente, poi questo come fallback — nessun secondo adattatore, la
struttura a card-wrapper è la stessa.

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

_MESI_ITALIANI = {
    "gennaio": 1, "febbraio": 2, "marzo": 3, "aprile": 4, "maggio": 5, "giugno": 6,
    "luglio": 7, "agosto": 8, "settembre": 9, "ottobre": 10, "novembre": 11, "dicembre": 12,
}
# "20 Maggio 2000" o "11 Giugno 2026 - 1 Novembre 2026" (variante wordpress,
# .card-calendar .card-day): giorno 1-2 cifre, non zero-paddato come nel
# formato GG/MM/AAAA della variante Dettaglionews.
_PATTERN_DATA_TESTUALE = re.compile(
    r"(\d{1,2})\s+(" + "|".join(_MESI_ITALIANI) + r")\s+(\d{4})"
    r"(?:\s*-\s*(\d{1,2})\s+(" + "|".join(_MESI_ITALIANI) + r")\s+(\d{4}))?",
    re.IGNORECASE,
)


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


def _estrai_date_testuale(testo_data: str) -> tuple[str | None, str | None]:
    """'20 Maggio 2000' -> ('2000-05-20', '2000-05-20').
    '11 Giugno 2026 - 1 Novembre 2026' -> ('2026-06-11', '2026-11-01')."""
    m = _PATTERN_DATA_TESTUALE.search(testo_data or "")
    if not m:
        return None, None
    gg1, mese1, aaaa1, gg2, mese2, aaaa2 = m.groups()
    mm1 = _MESI_ITALIANI[mese1.lower()]
    inizio = f"{aaaa1}-{mm1:02d}-{int(gg1):02d}"
    if gg2:
        mm2 = _MESI_ITALIANI[mese2.lower()]
        fine = f"{aaaa2}-{mm2:02d}-{int(gg2):02d}"
    else:
        fine = inizio
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
        # Titolo: '.card-title' (variante Dettaglionews) o
        # '.cmp-list-card-img__body-title' (variante wordpress/card-calendar,
        # 2026-09-14) — mai entrambe sullo stesso evento, provate in ordine.
        titolo_el = _con_classe(card, "card-title") or _con_classe(card, "cmp-list-card-img__body-title")
        if not titolo_el:
            continue  # non tutti i .card-wrapper sono un evento (es. widget feedback pagina)
        titolo = titolo_el[0].text_content().strip()
        if not titolo:
            continue

        # Data: '.category-top .data' con formato GG/MM/AAAA (variante
        # Dettaglionews) o '.card-calendar .card-day' con formato testuale
        # italiano "20 Maggio 2000" (variante wordpress, 2026-09-14).
        data_el = _con_classe(card, "data")
        data_inizio, data_fine = _estrai_date(data_el[0].text_content() if data_el else "")
        if not data_inizio:
            calendario_el = _con_classe(card, "card-day")
            data_inizio, data_fine = _estrai_date_testuale(calendario_el[0].text_content() if calendario_el else "")
        if not data_inizio:
            continue  # 04.7: senza data non è un evento pubblicabile, non se ne indovina una

        descrizione_el = _con_classe(card, "text-paragraph-card") or _con_classe(card, "cmp-list-card-img__body-description")
        descrizione = descrizione_el[0].text_content().strip() if descrizione_el else None

        # Il link è nel genitore del titolo (variante Dettaglionews:
        # '<a><h3 class="card-title">...') o in un figlio (variante
        # wordpress/card-calendar: '<h3 class="cmp-list-card-img__body-title"><a>...'):
        # cercato prima tra i discendenti, poi risalendo i genitori.
        from urllib.parse import urljoin

        url_evento = fetch_url
        link_figlio = titolo_el[0].xpath(".//a[@href]")
        if link_figlio:
            url_evento = urljoin(fetch_url, link_figlio[0].get("href"))
        else:
            link_el = titolo_el[0].getparent()
            while link_el is not None:
                href = link_el.get("href")
                if href:
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
