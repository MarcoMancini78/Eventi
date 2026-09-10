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
# 2026-09-05, richiesto dall'utente (caso Alba, evento 9af7cff0830e): con
# il fallback ora seguito sempre (non solo quando l'indice non basta),
# 10 tagliava fuori notizie reali su siti con più di 10 news nell'indice
# (Alba ne aveva 15-16) — alzato a 15, ancora un limite rigido per fonte
# per run, non per pagina di dettaglio raggiunta.
_MAX_LINK_DETTAGLIO = 15  # limite rigido per fonte per run (04.3)
_SOGLIA_LINK_DOMINANTE = 5

# 2026-09-09, caso reale Caselette (evento 272614985a67, segnalato
# dall'utente): oltre alle vere pagine di dettaglio evento, lo stesso
# prefisso '/appuntamenti/' produce anche pagine-CALENDARIO per singola
# data (es. '/appuntamenti/16-09-2026') — una vista aggregata di TUTTI gli
# eventi di quel giorno, con solo un estratto TRONCATO di ciascuno (nel
# caso reale: "...Santa..." al posto di "Santa Croce", scambiato dall'LLM
# per il titolo). Queste pagine non sono mai il dettaglio di un singolo
# evento, sempre un duplicato/riassunto della vera pagina — riconoscibili
# per forma (ultimo segmento di path = solo una data, nessuno slug
# testuale) indipendentemente dal formato esatto (DD-MM-YYYY o simili).
_PATTERN_SLUG_SOLO_DATA = re.compile(r"^\d{1,4}[-_]\d{1,2}[-_]\d{1,4}$")

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
# 2026-09-08, caso reale Caselette (evento 272614985a67, segnalato
# dall'utente): alcuni PA design system usano il locale IETF/BCP47
# completo (es. 'it-it', 'en-us') invece del solo codice lingua a 2
# lettere — un elenco fisso di stringhe note (come sopra) sarebbe sempre
# incompleto quando cambia la variante. Riconosciuto per FORMA (2-3
# lettere, trattino, 2 lettere maiuscole/minuscole) invece che per un
# elenco enumerato, coerente con lo standard BCP47 (lingua-REGIONE).
_PATTERN_LOCALE_IETF = re.compile(r"^[a-z]{2,3}-[a-z]{2}$", re.IGNORECASE)


def _e_prefisso_lingua(segmento: str) -> bool:
    return segmento in _PREFISSI_LINGUA or bool(_PATTERN_LOCALE_IETF.match(segmento))


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


# 2026-09-06, caso reale (Pro Loco Casal Cermelli, evento 309f6c8c01f2,
# segnalato dall'utente): un CMS Joomla-like mette 'index.php' come
# segmento comune a (quasi) tutte le pagine del sito
# (/plcc/index.php/gli-eventi/..., /plcc/index.php/la-pro-loco/...) — a 1
# livello il prefisso dominante è 'plcc' (63/63 link, l'intero sito), a 2
# livelli è 'plcc/index.php' (62/63, ancora l'intero sito): nessuno dei
# due distingue l'elenco eventi dal resto della navigazione, il vero
# raggruppamento utile ('plcc/index.php/gli-eventi', 30/63) emerge solo al
# 3° livello. Un prefisso che copre la quasi totalità dei link non è un
# elenco di dettagli, è il path-base del sito — va scartato come "troppo
# generico" per far scattare il tentativo al livello successivo, stesso
# principio già applicato ai codici lingua (_PREFISSI_LINGUA) ma generale
# invece che basato su un elenco fisso di stringhe note.
_SOGLIA_PREFISSO_TROPPO_GENERICO = 0.85


def _prefisso_ha_livello_piu_profondo(prefisso: str, link: list[str]) -> bool:
    """Vero solo se il livello successivo (prefisso + 1 segmento) separa
    davvero i link in più di un sotto-gruppo — non solo se i link sono
    più lunghi del prefisso. Distingue il caso Casal Cermelli
    ('plcc/index.php' raggruppa link con MOLTI valori diversi al segmento
    successivo — gli-eventi, la-pro-loco, il-paese... un livello più
    preciso esiste davvero) dal caso di una pagina con un solo livello di
    path per tutti i link (es. '/eventi/e1/', '/eventi/e2/': il segmento
    successivo a 'eventi' è sempre diverso per definizione — e1, e2, e3,
    ... — ma non forma sotto-gruppi: ogni pagina di dettaglio finirebbe
    da sola nel proprio 'prefisso', non un raggruppamento più fine, solo
    l'ultimo slug che identifica ogni singola pagina). Un vero livello
    più profondo produce ALMENO due sotto-gruppi con più di un elemento
    ciascuno; se ogni sotto-gruppo ha un solo elemento, il livello
    attuale è già la granularità giusta, va accettato così com'è."""
    livelli_prefisso = len(prefisso.split("/"))
    sotto_gruppi: dict[str, int] = {}
    for l in link:
        segmenti = urlparse(l).path.strip("/").split("/")
        if len(segmenti) <= livelli_prefisso:
            continue
        sotto_prefisso = "/".join(segmenti[: livelli_prefisso + 1])
        sotto_gruppi[sotto_prefisso] = sotto_gruppi.get(sotto_prefisso, 0) + 1
    return sum(1 for v in sotto_gruppi.values() if v > 1) >= 2


def _prefisso_dominante(
    link_per_prefisso: dict[str, list[str]], totale_link: int = 0, path_pagina_corrente: str | None = None
) -> tuple[str, list[str]] | None:
    """2026-09-05, caso reale Alba: un sito può avere più elenchi
    legittimi in parallelo sotto lo stesso prefisso a 1 livello (news,
    news-category) con conteggi comparabili — la vecchia soglia '2x il
    secondo' scartava tutto. Tra i gruppi con conteggio comparabile,
    preferisce quello con slug leggibili (poche pagine categoria/tag da
    ID numerico) invece di scartare in blocco.

    2026-09-06, caso reale Casal Cermelli: un prefisso che raccoglie quasi
    tutti i link della pagina (>= _SOGLIA_PREFISSO_TROPPO_GENERICO) E ha
    ancora un livello di profondità disponibile sotto di sé è il
    path-base del sito (es. 'index.php' su Joomla), non un elenco di
    dettagli — va escluso dai candidati anche se numericamente il più
    frequente, per lasciare che trova_link_dettaglio_dominanti riprovi a
    un livello di profondità maggiore. Il controllo sul livello più
    profondo evita di scartare per errore un sito con un solo livello di
    path per tutti i link (nulla da guadagnare approfondendo).

    2026-09-08, caso reale Caselette (evento 272614985a67, segnalato
    dall'utente): su un PA design system il menu di navigazione persistente
    ('amministrazione/*', 38 link) può essere numericamente più frequente
    del vero contenuto della pagina che si sta guardando
    ('appuntamenti/*', 15 link) — puro conteggio sceglieva il menu. Se un
    candidato condivide il prefisso della PAGINA CORRENTE (quella su cui
    ci troviamo, es. '/it-it/appuntamenti'), è il segnale più affidabile
    di pertinenza — vince a prescindere dal conteggio, purché superi
    comunque la soglia minima di un vero elenco.

    2026-09-09, caso reale Caselette (evento 272614985a67, secondo giro,
    segnalato dall'utente): il filtro anti-pagine-calendario (vedi
    _PATTERN_SLUG_SOLO_DATA in trova_link_dettaglio_dominanti) toglie di
    peso gli slug '/16-09-2026' ecc. dal gruppo 'appuntamenti', che in un
    giorno con pochi eventi nel calendario può scendere sotto
    _SOGLIA_LINK_DOMINANTE (pensata per un vero elenco con molte voci,
    non per il caso "la pagina corrente ha solo 2-4 eventi oggi") — il
    filtro di soglia scartava allora il prefisso pagina-corrente PRIMA che
    la preferenza sotto potesse applicarsi, facendo ripiegare su un menu
    di navigazione enorme (es. 'servizi', 21 link) invece che sul vero
    contenuto, anche solo 2 dettagli veri. Il match sul prefisso della
    pagina corrente va quindi controllato PRIMA del filtro di soglia
    piena, con una soglia ridotta a 1 (un solo link reale, purché non sia
    rumore da slug numerico) — è comunque il segnale più affidabile di
    pertinenza, indipendentemente da quanti elementi contenga oggi."""
    if not link_per_prefisso:
        return None

    if path_pagina_corrente:
        segmenti_pagina = path_pagina_corrente.strip("/").split("/")
        for prefisso, link in link_per_prefisso.items():
            livelli = len(prefisso.split("/"))
            if livelli <= len(segmenti_pagina) and "/".join(segmenti_pagina[:livelli]) == prefisso:
                if len(set(link)) >= 1 and _quota_slug_numerici(link) < 0.5:
                    return prefisso, link

    candidati = {
        k: v for k, v in link_per_prefisso.items()
        if len(set(v)) >= _SOGLIA_LINK_DOMINANTE and _quota_slug_numerici(v) < 0.5
        and not (
            totale_link and len(set(v)) / totale_link >= _SOGLIA_PREFISSO_TROPPO_GENERICO
            and _prefisso_ha_livello_piu_profondo(k, v)
        )
    }
    if not candidati:
        return None

    conteggi = Counter({k: len(set(v)) for k, v in candidati.items()})
    prefisso_top, n_top = conteggi.most_common(1)[0]
    return prefisso_top, candidati[prefisso_top]


# 2026-09-09, caso reale Buttigliera d'Asti (evento b185450ddcf6,
# segnalato dall'utente): un CMS PA più datato identifica il dettaglio
# con un parametro di query invece che nel path
# ('/Dettaglionews?IDNews=414150', path SEMPRE uguale, solo il valore di
# IDNews cambia) — il raggruppamento per path puro non vede mai questo
# pattern (39 link, tutti collassati sullo stesso path 'Dettaglionews',
# mai riconosciuti come un elenco perché non sono nel path stesso). Il
# filtro principale scarta ogni link con query string a monte (mai un
# candidato a menu/navigazione, coerente col resto del modulo): questi
# link vanno raccolti a parte e provati come ultimo fallback, quando il
# path puro non produce nulla di utile.
def _raggruppa_per_path_e_parametro_query(link_con_query: list[tuple[str, str, str]]) -> dict[str, list[str]]:
    """Raggruppa link con query string per (path, nome del PRIMO
    parametro) — non per il valore, che è l'ID stesso e varia per
    definizione. Un solo parametro nella query, coerente con l'osservato
    reale ('?IDNews=NNNNNN', non una combinazione di più filtri): una
    query con più parametri è più probabile un link con stato/filtri
    (paginazione, ordinamento) che un identificatore di dettaglio."""
    gruppi: dict[str, list[str]] = {}
    for path, query, link in link_con_query:
        parametri = query.split("&")
        if len(parametri) != 1 or "=" not in parametri[0]:
            continue
        nome_parametro = parametri[0].split("=", 1)[0]
        chiave = f"{path}?{nome_parametro}"
        gruppi.setdefault(chiave, []).append(link)
    return gruppi


def trova_link_dettaglio_dominanti(html: str, pagina_url: str) -> list[str]:
    """Cerca link interni con un prefisso di path dominante (vedi docstring
    del modulo): candidato a essere l'indice di un elenco di dettagli.
    Esclude link alla pagina stessa, ancore (#...), query string, e feed
    tecnici (/comments/feed/, /wp-json/...) — mai considerati un 'elenco'.

    Prova prima il prefisso a 1 segmento (es. /eventi/xxx); se il primo
    segmento è un codice lingua (es. /it/news/xxx, dove 'it' raggruppa
    insieme menu e notizie senza distinguerli) o non produce un prefisso
    dominante, riprova a 2 segmenti (es. /it/news). Se anche il prefisso a
    2 segmenti risulta troppo generico (es. 'plcc/index.php' su un CMS
    Joomla-like, dove index.php è il path-base di quasi tutte le pagine
    del sito — caso reale Casal Cermelli, evento 309f6c8c01f2), riprova a
    3 segmenti (es. 'plcc/index.php/gli-eventi')."""
    try:
        albero = lxml.html.fromstring(html)
        albero.make_links_absolute(pagina_url)
    except Exception:
        return []

    base = urlparse(pagina_url)
    path_pagina = base.path

    link_pagina: list[tuple[str, list[str]]] = []
    link_con_query: list[tuple[str, str, str]] = []
    for el, attr, link, _pos in albero.iterlinks():
        # Solo <a href>: iterlinks() include anche <link>/<script>/<img>
        # (css, JS, immagini) che sporcano il rilevamento del prefisso
        # lingua sotto — un foglio di stile /bootstrap-italia/... non è
        # un candidato a pagina di dettaglio.
        if el.tag != "a" or attr != "href":
            continue
        p = urlparse(link)
        if p.netloc != base.netloc or p.fragment:
            continue
        if p.path in ("/", path_pagina) or "/feed" in p.path or p.path.startswith("/wp-json"):
            continue
        if p.query:
            # Raccolti a parte (vedi _raggruppa_per_path_e_parametro_query):
            # mai un candidato al raggruppamento su path puro sotto, ma un
            # possibile elenco quando il dettaglio vive nel parametro
            # invece che nel path (caso Buttigliera d'Asti).
            link_con_query.append((p.path, p.query, link))
            continue
        ultimo_segmento = p.path.rstrip("/").rsplit("/", 1)[-1]
        if _PATTERN_SLUG_SOLO_DATA.match(ultimo_segmento):
            continue  # pagina-calendario per data, mai il dettaglio di un evento (vedi sopra)
        link_pagina.append((p.path, link))

    if not link_pagina and not link_con_query:
        return []

    totale_link = len(link_pagina)

    primo_segmento_generico = all(
        _e_prefisso_lingua(path.strip("/").split("/", 1)[0]) for path, _ in link_pagina
    )

    if not primo_segmento_generico:
        trovato = _prefisso_dominante(_raggruppa_per_prefisso(link_pagina, livelli=1), totale_link, path_pagina)
        if trovato:
            return sorted(set(trovato[1]))[:_MAX_LINK_DETTAGLIO]

    trovato = _prefisso_dominante(_raggruppa_per_prefisso(link_pagina, livelli=2), totale_link, path_pagina)
    if trovato:
        return sorted(set(trovato[1]))[:_MAX_LINK_DETTAGLIO]

    trovato = _prefisso_dominante(_raggruppa_per_prefisso(link_pagina, livelli=3), totale_link, path_pagina)
    if trovato:
        return sorted(set(trovato[1]))[:_MAX_LINK_DETTAGLIO]

    if link_con_query:
        trovato = _prefisso_dominante(_raggruppa_per_path_e_parametro_query(link_con_query), 0, None)
        if trovato:
            # 2026-09-09, caso reale Buttigliera d'Asti: un ID numerico
            # nel parametro di query è quasi sempre auto-incrementale (più
            # alto = più recente) — l'ordine alfabetico usato per gli slug
            # testuali (sorted() sopra) tagliava fuori le notizie più
            # recenti (l'evento reale, IDNews=414150, restava escluso dal
            # limite _MAX_LINK_DETTAGLIO a favore di ID più bassi/vecchi
            # solo perché '344221' < '414150' come stringa). Ordina per
            # valore numerico decrescente quando il valore è numerico;
            # ricade sull'ordine alfabetico per un valore non numerico
            # (isolamento totale, 15.1 regola 4: non deve mai sollevare).
            def _chiave_ordinamento(url: str) -> tuple[int, object]:
                valore = url.rsplit("=", 1)[-1]
                return (0, -int(valore)) if valore.isdigit() else (1, url)

            return sorted(set(trovato[1]), key=_chiave_ordinamento)[:_MAX_LINK_DETTAGLIO]

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
