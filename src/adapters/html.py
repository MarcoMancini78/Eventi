"""Adattatore HTML generico (04.3): T1, nessun selettore CSS per sito.

Scarica la pagina indice, ripulisce il testo con trafilatura, e produce un
artefatto grezzo se contiene abbastanza segnali di data da giustificare la
chiamata all'estrattore. Se una fonte richiede selettori custom per essere
utile, è il segnale che non conviene scriverne uno (04.3).

Link di dettaglio (2026-09-01, trovato con un caso reale — Attraverso
Festival: la pagina "programma" è solo un indice con titolo+prezzo per
evento, le date vivono unicamente nelle 47 pagine di dettaglio linkate.
`_MAX_LINK_DETTAGLIO` era già previsto nel codice ma mai implementato).
Si cerca sempre un prefisso di path dominante tra i link interni (es.
tutti `/eventi/...`): se un solo prefisso ricorre molto più degli altri
(`_SOGLIA_LINK_DOMINANTE` occorrenze — su un sito reale i link di
navigazione ricorrono 2 volte, una nell'header e una nel footer, mentre
un vero elenco di elementi ne produce decine), è il segnale di un elenco
di dettagli, non di menu/categoria/pagine correlate. Si seguono al più
`_MAX_LINK_DETTAGLIO` di quei link.

2026-09-05, richiesto dall'utente (caso Alba 9af7cff0830e): i link di
dettaglio vengono seguiti SEMPRE quando trovati, non solo quando
l'indice non basta da solo — un indice con più anteprime brevi produce
già abbastanza pattern di data da superare la soglia, ma il dettaglio
ha sempre titolo/descrizione/immagine più precisi e un URL che punta
alla notizia vera invece che alla pagina elenco. L'indice resta usato
solo come fallback, quando nessun prefisso dominante viene trovato o
nessuna pagina di dettaglio produce un artefatto valido."""
from __future__ import annotations

import hashlib
import re
from collections import Counter
from pathlib import Path
from urllib.parse import urlparse

import httpx
import lxml.html
import trafilatura

from .base import Adapter, Artefatto

_TIMEOUT_SECONDI = 15
_MAX_LINK_DETTAGLIO = 10  # limite rigido per fonte per run (04.3)
_SOGLIA_LINK_DOMINANTE = 5

_PATTERN_DATA = [
    re.compile(r"\b\d{1,2}[/\-.]\d{1,2}(?:[/\-.]\d{2,4})?\b"),  # 12/09, 12-09-2026
    re.compile(
        r"\b\d{1,2}\s+(gennaio|febbraio|marzo|aprile|maggio|giugno|luglio|agosto|"
        r"settembre|ottobre|novembre|dicembre)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(luned[iì]|marted[iì]|mercoled[iì]|gioved[iì]|venerd[iì]|sabato|domenica)\b",
        re.IGNORECASE,
    ),
]


def contiene_pattern_di_data(testo: str, minimo: int = 2) -> bool:
    """04.3: 'se il testo ripulito contiene >= 2 pattern di data -> passa all'estrattore'."""
    trovati = sum(1 for pattern in _PATTERN_DATA if pattern.search(testo))
    return trovati >= minimo


def estrai_testo_pulito(html: str) -> str | None:
    """trafilatura rimuove menu, footer, cookie banner (04.3)."""
    return trafilatura.extract(html, favor_recall=True)


def estrai_og_image(html: str, pagina_url: str) -> str | None:
    """2026-09-05, richiesto dall'utente (caso Alba 9af7cff0830e): la
    pagina di dettaglio di una notizia ha quasi sempre un'immagine
    principale in <meta property="og:image">, lo standard de facto per
    l'anteprima social — più affidabile di indovinare quale <img> nel
    corpo pagina sia quella giusta (loghi, icone, banner)."""
    try:
        albero = lxml.html.fromstring(html)
        albero.make_links_absolute(pagina_url)
    except Exception:
        return None
    tag = albero.xpath('//meta[@property="og:image"]/@content')
    return tag[0] if tag else None


def parse_html(html: str, source_id: str, fetch_url: str) -> list[Artefatto]:
    testo = estrai_testo_pulito(html)
    if not testo or not contiene_pattern_di_data(testo):
        return []

    return [
        Artefatto(
            source_id=source_id,
            url=fetch_url,
            kind="html",
            text=testo,
            raw_hash=hashlib.sha1(testo.encode("utf-8")).hexdigest(),
            image_urls=[img] if (img := estrai_og_image(html, fetch_url)) else [],
        )
    ]


# 2026-09-05, caso reale (Alba, evento 9af7cff0830e, segnalato dall'utente):
# molti siti comunali prefissano ogni URL con il codice lingua (/it/...),
# rendendo il primo segmento di path identico per menu di navigazione E
# vere pagine di dettaglio (/it/news/xxx) — raggruppare solo su
# segmenti[0] confonde i due casi, il prefisso "dominante" risultava il
# menu statico invece delle notizie. Codici ISO 639-1 a 2 lettere più
# frequenti sui siti PA italiani/UE — non un elenco esaustivo, solo i
# prefissi lingua plausibili da scartare come primo livello.
_PREFISSI_LINGUA = {
    "it", "en", "fr", "de", "es", "pt",
}


def _raggruppa_per_prefisso(link_pagina: list[tuple[str, list[str]]], livelli: int) -> dict[str, list[str]]:
    link_per_prefisso: dict[str, list[str]] = {}
    for path, link in link_pagina:
        segmenti = path.strip("/").split("/")
        if len(segmenti) < livelli or not segmenti[0]:
            continue
        prefisso = "/".join(segmenti[:livelli])
        link_per_prefisso.setdefault(prefisso, []).append(link)
    return link_per_prefisso


def _quota_slug_numerici(link: list[str]) -> float:
    """Frazione di link il cui ultimo segmento di path è puramente
    numerico (es. /it/news-category/112659) — un pattern tipico di
    pagine categoria/tag/ID, non di singole pagine di dettaglio con
    slug leggibile (es. /it/news/presentazione-del-programma-...)."""
    if not link:
        return 0.0
    numerici = sum(1 for l in link if urlparse(l).path.rstrip("/").rsplit("/", 1)[-1].isdigit())
    return numerici / len(link)


def _prefisso_dominante(link_per_prefisso: dict[str, list[str]]) -> tuple[str, list[str]] | None:
    """2026-09-05, caso reale Alba: un sito può avere più elenchi
    legittimi in parallelo sotto lo stesso prefisso a 1 livello (news,
    news-category) con conteggi comparabili — la vecchia soglia '2x il
    secondo' scartava tutto. Tra i gruppi con conteggio comparabile,
    preferisce quello con slug leggibili (poche pagine categoria/tag da
    ID numerico) invece di scartare in blocco."""
    if not link_per_prefisso:
        return None
    candidati = {
        k: v for k, v in link_per_prefisso.items()
        if len(set(v)) >= _SOGLIA_LINK_DOMINANTE and _quota_slug_numerici(v) < 0.5
    }
    if not candidati:
        return None
    conteggi = Counter({k: len(set(v)) for k, v in candidati.items()})
    prefisso_top, n_top = conteggi.most_common(1)[0]
    return prefisso_top, candidati[prefisso_top]


def trova_link_dettaglio_dominanti(html: str, pagina_url: str) -> list[str]:
    """Cerca link interni con un prefisso di path dominante (vedi docstring
    del modulo): candidato a essere l'indice di un elenco di dettagli.
    Esclude link alla pagina stessa, ancore (#...), query string, e feed
    tecnici (/comments/feed/, /wp-json/...) — mai considerati un 'elenco'.

    Prova prima il prefisso a 1 segmento (es. /eventi/xxx); se il primo
    segmento è un codice lingua (es. /it/news/xxx, dove 'it' raggruppa
    insieme menu e notizie senza distinguerli) o non produce un prefisso
    dominante, riprova a 2 segmenti (es. /it/news)."""
    try:
        albero = lxml.html.fromstring(html)
        albero.make_links_absolute(pagina_url)
    except Exception:
        return []

    base = urlparse(pagina_url)
    path_pagina = base.path

    link_pagina: list[tuple[str, list[str]]] = []
    for el, attr, link, _pos in albero.iterlinks():
        # Solo <a href>: iterlinks() include anche <link>/<script>/<img>
        # (css, JS, immagini) che sporcano il rilevamento del prefisso
        # lingua sotto — un foglio di stile /bootstrap-italia/... non è
        # un candidato a pagina di dettaglio.
        if el.tag != "a" or attr != "href":
            continue
        p = urlparse(link)
        if p.netloc != base.netloc or p.fragment or p.query:
            continue
        if p.path in ("/", path_pagina) or "/feed" in p.path or p.path.startswith("/wp-json"):
            continue
        link_pagina.append((p.path, link))

    if not link_pagina:
        return []

    primo_segmento_generico = all(
        path.strip("/").split("/", 1)[0] in _PREFISSI_LINGUA for path, _ in link_pagina
    )

    if not primo_segmento_generico:
        trovato = _prefisso_dominante(_raggruppa_per_prefisso(link_pagina, livelli=1))
        if trovato:
            return sorted(set(trovato[1]))[:_MAX_LINK_DETTAGLIO]

    trovato = _prefisso_dominante(_raggruppa_per_prefisso(link_pagina, livelli=2))
    if trovato:
        return sorted(set(trovato[1]))[:_MAX_LINK_DETTAGLIO]

    return []


_CARTELLA_IMMAGINI_HTML = Path(__file__).resolve().parent.parent.parent / "data" / "cache" / "images"


def _scarica_immagine(url: str, cartella: Path, nome_file: str, client: httpx.Client, user_agent: str) -> str | None:
    try:
        risposta = client.get(url, headers={"User-Agent": user_agent})
        risposta.raise_for_status()
    except httpx.HTTPError:
        return None
    cartella.mkdir(parents=True, exist_ok=True)
    percorso = cartella / nome_file
    percorso.write_bytes(risposta.content)
    return str(percorso)


class HtmlAdapter(Adapter):
    """Adattatore generico: segue sempre i link di dettaglio quando ne
    trova un prefisso dominante (vedi docstring del modulo), invece di
    fermarsi alla pagina indice — 2026-09-05, richiesto dall'utente
    (caso Alba 9af7cff0830e): un indice che elenca più eventi con
    anteprime brevi contiene già abbastanza pattern di data da produrre
    un artefatto da solo, ma il dettaglio ha sempre titolo/descrizione/
    immagine molto più precisi e un URL che punta alla notizia vera
    invece che alla pagina elenco generica. L'indice resta usato solo
    quando non si trova nessun prefisso di path dominante da seguire.

    Il rendering JavaScript (Playwright) va aggiunto come flag per-fonte solo
    se il testo pulito risulta vuoto e la fonte è in polling_diretto (04.3):
    non è compito di questo adattatore di base.
    """

    def fetch(self, fonte: dict) -> list[Artefatto]:
        endpoint = fonte["endpoint"]
        source_id = fonte["source_id"]
        user_agent = fonte.get("user_agent", "EventiLocaliBot/1.0")
        with httpx.Client(timeout=_TIMEOUT_SECONDI, follow_redirects=True) as client:
            risposta = client.get(endpoint, headers={"User-Agent": user_agent})
            risposta.raise_for_status()

            link_dettaglio = trova_link_dettaglio_dominanti(risposta.text, endpoint)
            if not link_dettaglio:
                return parse_html(risposta.text, source_id, endpoint)

            cartella = _CARTELLA_IMMAGINI_HTML / source_id
            trovati: list[Artefatto] = []
            for link in link_dettaglio:
                try:
                    r_dettaglio = client.get(link, headers={"User-Agent": user_agent})
                    r_dettaglio.raise_for_status()
                except httpx.HTTPError:
                    continue  # isolamento totale: un link rotto non blocca gli altri (15.1 regola 4)
                artefatti = parse_html(r_dettaglio.text, source_id, link)
                for art in artefatti:
                    if art.image_urls:
                        nome_file = hashlib.sha1(link.encode("utf-8")).hexdigest()[:16] + ".jpg"
                        percorso = _scarica_immagine(art.image_urls[0], cartella, nome_file, client, user_agent)
                        if percorso:
                            art.image_paths = [percorso]
                trovati.extend(artefatti)

            if trovati:
                return trovati
            # Nessuna pagina di dettaglio ha prodotto un artefatto valido
            # (04.7: vuoto non è un errore, ma qui è meglio ripiegare
            # sull'indice — che può comunque contenere date sue — piuttosto
            # che tornare a mani vuote quando l'indice stesso basterebbe).
            return parse_html(risposta.text, source_id, endpoint)
