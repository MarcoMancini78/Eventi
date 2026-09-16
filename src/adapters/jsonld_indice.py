"""Adattatore T0 per indici che elencano eventi ma non espongono JSON-LD
loro stessi, mentre ogni pagina di DETTAGLIO sì (caso reale, 2026-09-17:
turismo.comuneacqui.it/events/ — portale turistico WordPress separato dal
sito istituzionale del comune, plugin eventi con schema.org/Event solo
sulle singole pagine `/event/{slug}/`).

Diverso da `adapters/jsonld.py` (che si aspetta il JSON-LD già
sull'endpoint configurato): qui si segue prima l'indice per trovare i link
di dettaglio, poi si applica `parse_jsonld` a ciascuno. T0 puro: nessuna
chiamata LLM, gli stessi dati che l'estrattore avrebbe dovuto dedurre da un
HTML generico sono già in JSON-LD.

Bug reale trovato (2026-09-17, collaudo su Acqui Terme): la funzione
generica `trova_link_dettaglio_dominanti` di `adapters/html.py`, pensata
per un sito qualunque senza pattern noto, sceglieva `/events/...` (31
link, ma un miscuglio di `/events/category/...` e `/events/elenco/...`,
pagine categoria/filtro, MAI un evento) invece di `/event/...` singolare
(20 link, i veri singoli eventi) — a livello di 1 segmento di path
`events` batte `event` per puro conteggio complessivo, e anche contando i
soli URL distinti vincono le 14 categorie (tutte diverse tra loro) contro
i 10 eventi distinti (linkati 2 volte ciascuno). Nessuna euristica generica
di conteggio risolve questo caso in modo affidabile. Non un fix da fare
nella funzione condivisa (rischioso su 700+ fonti che già la usano con
successo): qui si conosce già la struttura del plugin eventi WordPress
usato da questo sito (permalink SINGOLARE `/event/{slug}/`, la lista è
sempre sotto `/events/...` PLURALE) — si prende esplicitamente il primo
segmento di path uguale a "event", non il prefisso numericamente
dominante. Meno generico di `trova_link_dettaglio_dominanti`, ma corretto
per l'unico scopo di questo adattatore: siti con questo specifico plugin.
"""
from __future__ import annotations

from urllib.parse import urlparse

import httpx
import lxml.html

from .base import Adapter, Artefatto
from .jsonld import parse_jsonld

_TIMEOUT_SECONDI = 15
_MAX_LINK_DETTAGLIO = 15  # stesso limite di adapters/html.py (04.3)
_USER_AGENT_BROWSER = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)


_PREFISSI_DETTAGLIO_EVENTO = ("event",)  # plugin eventi WordPress noti: permalink singolare


def trova_link_dettaglio_evento(html: str, pagina_url: str) -> list[str]:
    """Cerca link interni il cui primo segmento di path è esattamente
    'event' (singolare) — il permalink del plugin eventi WordPress usato
    da questo sito. Deliberatamente NON un prefisso 'dominante' scelto per
    conteggio (vedi motivazione nel docstring del modulo): 'events'
    (plurale, lista/categoria) e 'event' (singolare, dettaglio) sono due
    prefissi diversi che un'euristica di conteggio confonde facilmente."""
    try:
        albero = lxml.html.fromstring(html)
        albero.make_links_absolute(pagina_url)
    except Exception:
        return []

    base = urlparse(pagina_url)
    trovati: set[str] = set()
    for el, attr, link, _pos in albero.iterlinks():
        if el.tag != "a" or attr != "href":
            continue
        p = urlparse(link)
        if p.netloc != base.netloc or p.fragment or p.query:
            continue
        segmenti = [s for s in p.path.strip("/").split("/") if s]
        if len(segmenti) >= 2 and segmenti[0] in _PREFISSI_DETTAGLIO_EVENTO:
            trovati.add(link)

    return sorted(trovati)[:_MAX_LINK_DETTAGLIO]


class JsonLdIndiceAdapter(Adapter):
    def fetch(self, fonte: dict) -> list[Artefatto]:
        endpoint = fonte["endpoint"]
        source_id = fonte["source_id"]
        user_agent = fonte.get("user_agent", _USER_AGENT_BROWSER)

        with httpx.Client(timeout=_TIMEOUT_SECONDI, follow_redirects=True) as client:
            risposta_indice = client.get(endpoint, headers={"User-Agent": user_agent})
            risposta_indice.raise_for_status()

            link_dettaglio = trova_link_dettaglio_evento(risposta_indice.text, endpoint)
            if not link_dettaglio:
                # Nessun prefisso dominante trovato: prova comunque
                # sull'indice stesso, per coerenza con jsonld.py puro
                # (alcuni siti espongono Event anche lì).
                return parse_jsonld(risposta_indice.text, source_id, endpoint)

            artefatti: list[Artefatto] = []
            for link in link_dettaglio:
                try:
                    risposta_dettaglio = client.get(link, headers={"User-Agent": user_agent})
                    risposta_dettaglio.raise_for_status()
                except httpx.HTTPError:
                    continue  # 15.1 regola 4: un dettaglio irraggiungibile non ferma gli altri
                artefatti.extend(parse_jsonld(risposta_dettaglio.text, source_id, link))

        return artefatti
