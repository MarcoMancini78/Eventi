"""M10 — Feed social: lettura cronologica degli account già seguiti (14.5b, 12.3).

Stesso principio di sync_seguiti.py: lettura passiva, mai un'azione (14.5b
"la lettura passiva è molto meno rilevabile dell'azione"). A differenza del
follow (l'unica automazione del progetto che agisce), qui — come in
sync_seguiti — si applica comunque la stessa verifica di identità già
scritta per il follow: leggere per errore dal profilo personale invece
dell'account dedicato produrrebbe attribuzioni sbagliate in silenzio,
esattamente il rischio già osservato e corretto in passato per il follow
(2026-08-24/25).

Regola di separazione esplicita (14.5b): mai follow e lettura del feed
nella stessa sessione, almeno un'ora di distanza — verificata qui come
precondizione, non solo enunciata.

Selettori DOM: Facebook collaudato dal vivo il 2026-08-27 (3 giri di bug
reali), Instagram collaudato il 2026-08-28 (selettore riscritto da zero
dopo ispezione diretta della sessione reale con Playwright — 0 post letti
al primo tentativo, l'assunzione iniziale su <header> era sbagliata).
Entrambi seguono lo stesso principio del progetto: fermarsi e ispezionare
i dati reali dopo un paio di fallimenti, non continuare a indovinare.
"""
from __future__ import annotations

import hashlib
import re
import sqlite3
import unicodedata
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from .adapters.base import Artefatto
from .config import Config
from .follow import (
    _apri_sessione_browser,
    _assicura_identita_pagina,
    _chiudi_sessione_browser,
    verifica_identita_instagram,
)
from .pipeline import _assicura_source, _pubblica_o_metti_in_quarantena, _registra_artefatto
from .prefilter import scarta_testo
from .extractor.schema import RispostaEstrazione
from .prefilter_immagini import cerca_in_cache, salva_in_cache, scarta_immagine
from .perimetro import risolvi_comune


class SessioneTroppoVicinaAlFollowError(Exception):
    """14.5b: mai follow e lettura feed nella stessa sessione, almeno
    un'ora di distanza. Si ferma piuttosto che rischiare comportamenti
    ravvicinati che sembrano automazione."""


@dataclass
class PostFeed:
    piattaforma: str
    handle_autore: str
    post_id: str
    url: str
    testo: str | None = None
    image_paths: list[str] = field(default_factory=list)


def verifica_separazione_da_follow(conn: sqlite3.Connection, piattaforma: str, minuti_minimi: int = 60) -> None:
    """14.5b: mai follow e lettura feed nella stessa sessione."""
    riga = conn.execute(
        "SELECT valore FROM app_state WHERE chiave = ?", (f"ultimo_lotto_follow_{piattaforma}",)
    ).fetchone()
    if not riga or not riga["valore"]:
        return
    ultimo = datetime.fromisoformat(riga["valore"])
    minuti_trascorsi = (datetime.now() - ultimo).total_seconds() / 60
    if minuti_trascorsi < minuti_minimi:
        raise SessioneTroppoVicinaAlFollowError(
            f"Ultimo lotto di follow {piattaforma} lanciato {minuti_trascorsi:.0f} minuti fa, "
            f"servono almeno {minuti_minimi} minuti di separazione dalla lettura del feed (14.5b)"
        )


def attribuisci_post(conn: sqlite3.Connection, piattaforma: str, handle_autore: str) -> sqlite3.Row | None:
    """12.3: 'l'attribuzione della fonte va ricostruita dal nome
    dell'account nel post'. Se l'handle è già una fonte nota con un
    comune assegnato, ritorna quella riga; altrimenti registra un
    candidato (mai uno scarto, coerente con 04.7/14.4) e ritorna None —
    nessun evento va pubblicato senza un comune attendibile."""
    handle_norm = handle_autore.strip().lower().lstrip("@")
    riga = conn.execute(
        "SELECT * FROM coda_follow WHERE piattaforma=? AND handle=?", (piattaforma, handle_norm)
    ).fetchone()
    if riga and riga["comune"]:
        return riga

    source_id = f"sconosciuto-{piattaforma}-{handle_norm}"
    conn.execute(
        """
        INSERT INTO coda_follow (source_id, piattaforma, handle, url, soggetto, comune, fascia, categoria, stato, note)
        VALUES (?, ?, ?, ?, ?, '', '', 'sconosciuto', 'candidato_da_feed', 'handle visto nel feed, comune da assegnare')
        ON CONFLICT(source_id, piattaforma) DO NOTHING
        """,
        (source_id, piattaforma, handle_norm, _url_da_handle(piattaforma, handle_norm), handle_norm),
    )
    conn.commit()
    return None


def _url_da_handle(piattaforma: str, handle: str) -> str:
    if piattaforma == "instagram":
        return f"https://www.instagram.com/{handle}"
    return f"https://www.facebook.com/{handle}"


def _ultimo_post_visto(conn: sqlite3.Connection, piattaforma: str) -> str | None:
    riga = conn.execute(
        "SELECT valore FROM app_state WHERE chiave = ?", (f"ultimo_post_visto_{piattaforma}",)
    ).fetchone()
    return riga["valore"] if riga else None


def _salva_ultimo_post_visto(conn: sqlite3.Connection, piattaforma: str, post_id: str) -> None:
    conn.execute(
        "INSERT INTO app_state (chiave, valore) VALUES (?, ?) ON CONFLICT(chiave) DO UPDATE SET valore=excluded.valore",
        (f"ultimo_post_visto_{piattaforma}", post_id),
    )
    conn.commit()


def leggi_feed_reale(
    piattaforma: str, config: Config, conn: sqlite3.Connection, sessione_dir: Path | None = None
) -> list[PostFeed]:
    """Scroll cronologico fino all'ultimo post già visto (12.3, 14.5b),
    poi stop — nessun parallelismo, nessuna interazione (14.5b: 'solo
    lettura: niente like, commenti, condivisioni')."""
    verifica_separazione_da_follow(conn, piattaforma)

    ultimo_visto = _ultimo_post_visto(conn, piattaforma)

    contesto = _apri_sessione_browser(piattaforma, sessione_dir)
    try:
        if piattaforma == "facebook":
            _assicura_identita_pagina(contesto, config)
            post = _leggi_feed_facebook(contesto, config, ultimo_visto)
        else:
            verifica_identita_instagram(contesto, config)
            post = _leggi_feed_instagram(contesto, config, ultimo_visto)
    finally:
        _chiudi_sessione_browser(contesto)

    if post:
        _salva_ultimo_post_visto(conn, piattaforma, post[0].post_id)
    return post


# --- Selettori DOM Facebook: riscritti dopo il primo collaudo dal vivo
# (2026-08-27). div[role="article"] NON esiste più nel feed principale di
# Facebook (trovati solo 2 elementi con quel ruolo, entrambi skeleton di
# caricamento residui, aria-label="Caricamento..." — mai contenuto reale).
# Il vero autore del post è affidabile tramite h3 a[href] (verificato:
# isola correttamente "Pro Loco Valfenera", "Pro Loco Roddino", ecc. con
# handle puliti nell'href). Non esiste un contenitore di post con un
# ruolo/attributo stabile: risalendo dal link autore, il testo del vero
# post si riconosce perché ha molte parole UNICHE (>8) — a differenza dei
# contenitori intermedi che ripetono solo "Facebook" (alt-text di icone
# nel carosello di post consigliati) o dei tag di localizzazione geografica
# ("Proloco X si trova a Y, Piemonte", da escludere esplicitamente perché
# non è mai testo di un post, solo un tag). Nessun permalink singolo
# affidabile trovato nel primo collaudo (solo 3 link a permalink.php/posts/
# nell'intera pagina, tutti provenienti da notifiche di commento, non dai
# post del feed) — usa quindi come "post_id" un hash del testo, meno
# preciso di un vero ID ma sufficiente per la change detection.
# -- Selettori Instagram: NON ancora collaudati, primo tentativo.
_JS_RACCOGLI_POST_FACEBOOK = """
() => {
    const risultati = [];
    for (const link of document.querySelectorAll('h3 a[href]')) {
        const href = link.getAttribute('href') || '';
        let nodo = link.closest('h3');
        let scelto = null;
        for (let livelli = 0; livelli < 25 && nodo; livelli++) {
            nodo = nodo.parentElement;
            if (!nodo) break;
            const t = nodo.innerText || '';
            const paroleUniche = new Set(t.split(/\\s+/)).size;
            if (t.length > 80 && paroleUniche > 8 && !t.includes('si trova a')) {
                scelto = nodo;
                break;
            }
        }
        if (!scelto) continue;
        risultati.push({href, permalink: href, testo: scelto.innerText || ''});
    }
    return risultati;
}
"""

# Riscritto dopo il primo collaudo dal vivo (2026-08-28): il feed reale non
# ha alcun <header> dentro <article> (l'assunzione iniziale era sbagliata,
# 0 post letti al primo tentativo) — verificato ispezionando la sessione
# Instagram reale con Playwright. L'autore è il link immediatamente
# precedente al permalink (/p/... o /reel/...) nell'ordine dei link
# dell'articolo, filtrato per essere un profilo (un solo segmento di path,
# non /explore/... o /reels/audio/...). La didascalia vive in
# span._ap3a, ma quella classe compare DUE VOLTE per post (prima
# sull'username-link, poi sul vero testo) — va preso l'ULTIMO elemento,
# non il primo (querySelector prendeva sempre l'username per errore).
_JS_RACCOGLI_POST_INSTAGRAM = """
() => {
    const risultati = [];
    for (const articolo of document.querySelectorAll('article')) {
        const linkPost = articolo.querySelector('a[href*="/p/"], a[href*="/reel/"]');
        if (!linkPost) continue;
        const links = Array.from(articolo.querySelectorAll('a[href]'));
        const idxPost = links.indexOf(linkPost);
        let linkAutore = null;
        for (let i = idxPost - 1; i >= 0; i--) {
            const href = links[i].getAttribute('href') || '';
            if (href.startsWith('/') && !href.includes('/explore/') && !href.includes('/reels/audio/')
                && href.split('/').filter(Boolean).length === 1) {
                linkAutore = links[i];
                break;
            }
        }
        if (!linkAutore) continue;
        const captionEls = articolo.querySelectorAll('span._ap3a');
        const captionEl = captionEls.length > 0 ? captionEls[captionEls.length - 1] : null;
        risultati.push({
            href: linkAutore.getAttribute('href'),
            permalink: linkPost.getAttribute('href'),
            testo: captionEl ? captionEl.innerText : '',
        });
    }
    return risultati;
}
"""


def _handle_da_href_profilo(href: str, piattaforma: str) -> str:
    """Bug reale osservato (2026-08-27): nel feed reale l'href dell'autore
    è un URL ASSOLUTO (https://www.facebook.com/ProLocoBUBBIO?...), non
    relativo come nella pagina 'seguiti' già collaudata in sync_seguiti.py
    — split manuale su '/' produceva 'https:' come falso handle. Usare
    urlparse (come già fatto in prober.py con urljoin) invece di
    manipolare la stringa a mano.

    Stesso bug già risolto altrove (bonifica_social.py) per i profili
    senza username personalizzato: facebook.com/profile.php?id=NNN va
    identificato dall'id nella query string, non dal segmento letterale
    'profile.php' (che collasserebbe profili diversi sullo stesso
    handle-fasullo, come già osservato nel dataset ereditato)."""
    if piattaforma == "facebook":
        query = parse_qs(urlparse(href).query)
        if "id" in query and query["id"]:
            return f"profile.php?id={query['id'][0]}"

    path = urlparse(href).path
    segmenti = [s for s in path.strip("/").split("/") if s]
    return segmenti[0].lower() if segmenti else ""


def _post_id_da_permalink(permalink: str, testo: str = "") -> str:
    """Bug reale osservato (2026-08-27): nel feed principale di Facebook
    l'unico link disponibile per un post è quello dell'autore, con
    parametri di tracking (__cft__/__tn__) che cambiano ad ogni
    caricamento della pagina — usarlo come ID romperebbe la change
    detection (lo stesso post risulterebbe sempre "nuovo"). Se il
    permalink non contiene un vero ID di post riconoscibile (nessun
    /posts/, /videos/, /p/, /reel/), l'ID si basa sul TESTO del post
    (stabile tra un caricamento e l'altro, a differenza dell'URL)."""
    m = re.search(r"/(?:posts|videos|p|reel)/([^/?#]+)", permalink)
    if m:
        return m.group(1)
    if testo:
        return hashlib.sha1(testo.strip().encode("utf-8")).hexdigest()[:16]
    url_pulito = permalink.split("?")[0]
    return re.sub(r"[^a-zA-Z0-9]", "", url_pulito)[-32:] or permalink


_PATTERN_RIGA_RUMORE_FACEBOOK = re.compile(
    r"^(Facebook|·|Segui|Altro\.{3}|\d+\s*(min|h|ago|gg)?)$", re.IGNORECASE
)


def _e_carattere_offuscato(riga: str) -> bool:
    """Bug reale osservato (2026-08-27): alcuni post hanno la data/il
    timestamp offuscati carattere per carattere, ognuno su una riga a sé,
    con un marcatore invisibile appiccicato (es. 't͏' = lettera +
    U+034F COMBINING GRAPHEME JOINER) — probabile misura anti-scraping di
    Facebook contro l'estrazione di innerText. Nota tecnica: U+034F ha
    categoria Unicode Mn (Mark) ma "combining class" pari a zero, quindi
    unicodedata.combining() lo ignora (ritorna 0) — va controllata la
    CATEGORIA (Mn/Mc/Me), non la combining class, per riconoscerlo.
    Una riga così è un solo carattere alfanumerico seguito da ≥1 di questi
    marcatori: non rappresenta testo leggibile, va scartata (non
    "ripulita", non c'è nulla di utile da recuperare in una lettera
    isolata)."""
    if not riga:
        return False
    if all(unicodedata.category(c).startswith("M") for c in riga):
        return True  # riga di soli marcatori invisibili residui, nessuna lettera
    if len(riga) < 2:
        return False
    return riga[0].isalnum() and all(unicodedata.category(c).startswith("M") for c in riga[1:])


def _pulisci_testo_post(testo: str) -> str:
    """Il contenitore del post nel feed include anche righe di rumore che
    precedono il vero testo — 'Facebook' ripetuto molte volte (alt-text di
    icone/avatar in un carosello), punti elenco isolati, 'Segui', reazioni,
    caratteri offuscati (vedi _e_carattere_offuscato). Il NUMERO di
    ripetizioni di 'Facebook' varia da un caricamento all'altro della
    stessa pagina (non è stabile), quindi il testo va ripulito PRIMA di
    calcolare l'hash per la change detection, non solo per leggibilità —
    altrimenti lo stesso post produrrebbe un ID diverso ad ogni lettura."""
    righe = [r.strip() for r in testo.split("\n")]
    righe_pulite = [
        r for r in righe
        if r and not _PATTERN_RIGA_RUMORE_FACEBOOK.match(r) and not _e_carattere_offuscato(r)
    ]
    return "\n".join(righe_pulite).strip()


_JS_ESPANDI_VEDI_ALTRO = {
    "facebook": """
    () => {
        const bottoni = Array.from(document.querySelectorAll('div[role="button"]'))
            .filter(el => (el.innerText || '').trim().startsWith('Altro'));
        bottoni.forEach(b => b.click());
        return bottoni.length;
    }
    """,
    "instagram": """
    () => {
        const bottoni = Array.from(document.querySelectorAll('div[role="button"]'))
            .filter(el => (el.innerText || '').trim().toLowerCase() === 'altro');
        bottoni.forEach(b => b.click());
        return bottoni.length;
    }
    """,
}


def _scroll_feed_e_raccogli(pagina, script_js: str, piattaforma: str, ultimo_visto: str | None, max_scroll: int = 40) -> list[PostFeed]:
    """Scroll cronologico fino all'ultimo post già visto (change detection
    sul post ID, 12.3) o max_scroll (circuit-breaker anti-loop, coerente
    con lo stesso principio già applicato in sync_seguiti._scroll_e_raccogli).

    Prima di leggere il testo di ogni gruppo di post appena caricato, clicca
    i pulsanti "Vedi altro" (2026-09-01, richiesto dall'utente dopo aver
    trovato un evento in quarantena a bassa confidenza per un post
    troncato): non è un'interazione social visibile ad altri utenti (non è
    un like/commento/follow, coerente con 14.5b), solo l'espansione del
    testo che fa anche chi legge normalmente il feed. Collaudato dal vivo
    2026-09-01: su 3 post del feed reale, 2 troncati sono passati da
    292/666 a 979/777 caratteri dopo il click."""
    trovati: dict[str, PostFeed] = {}
    ordine: list[str] = []
    script_espandi = _JS_ESPANDI_VEDI_ALTRO[piattaforma]

    for _ in range(max_scroll):
        pagina.evaluate(script_espandi)
        pagina.wait_for_timeout(500)
        grezzi = pagina.evaluate(script_js)
        fermato = False
        for g in grezzi:
            handle = _handle_da_href_profilo(g["href"], piattaforma)
            if not handle:
                continue
            g["testo"] = _pulisci_testo_post(g.get("testo") or "") if piattaforma == "facebook" else g.get("testo")
            permalink = g.get("permalink") or g["href"]
            post_id = _post_id_da_permalink(permalink, g.get("testo") or "")
            if post_id == ultimo_visto:
                fermato = True
                break
            if post_id not in trovati:
                trovati[post_id] = PostFeed(
                    piattaforma=piattaforma,
                    handle_autore=handle,
                    post_id=post_id,
                    url=permalink if permalink.startswith("http") else f"https://www.{'facebook' if piattaforma=='facebook' else 'instagram'}.com{permalink}",
                    testo=(g.get("testo") or "").strip() or None,
                )
                ordine.append(post_id)
        if fermato:
            break

        pagina.mouse.wheel(0, 2000)
        pagina.wait_for_timeout(1200)

    return [trovati[pid] for pid in ordine]


def _leggi_feed_facebook(contesto: dict, config: Config, ultimo_visto: str | None) -> list[PostFeed]:
    """URL con &sk=h_chr: scheda Feed in ordine cronologico (12.3 'Più
    recenti'), non l'algoritmo di default — da verificare al primo
    collaudo reale, come tutti i selettori di questo modulo."""
    pagina = contesto["browser"].new_page()
    try:
        pagina.goto("https://www.facebook.com/?sk=h_chr", timeout=20000)
        pagina.wait_for_timeout(2000)
        return _scroll_feed_e_raccogli(pagina, _JS_RACCOGLI_POST_FACEBOOK, "facebook", ultimo_visto)
    finally:
        pagina.close()


def _seleziona_tab_seguiti_instagram(pagina) -> None:
    """Bug reale trovato dall'utente (2026-08-29): la home Instagram apre
    di default sulla tab 'Per te' (algoritmo misto, aria-selected=true),
    non sui soli account seguiti — a differenza di Facebook, che ha un
    parametro URL diretto (?sk=h_chr) per il cronologico. Instagram non
    ha un URL equivalente: bisogna cliccare la tab 'Seguiti' dentro
    div[role="tablist"] (2 tab: 'Per te' e 'Seguiti', verificato dal vivo
    2026-08-29). Se le tab non ci sono (UI cambiata, o già su 'Seguiti'
    da una sessione precedente), non solleva errore: il resto del giro
    prosegue comunque, coerente con l'isolamento totale degli errori."""
    tabs = pagina.query_selector_all('div[role="tab"]')
    for tab in tabs:
        if tab.inner_text().strip() == "Seguiti":
            if tab.get_attribute("aria-selected") != "true":
                tab.click()
                pagina.wait_for_timeout(1500)
            return


def _leggi_feed_instagram(contesto: dict, config: Config, ultimo_visto: str | None) -> list[PostFeed]:
    pagina = contesto["browser"].new_page()
    try:
        pagina.goto("https://www.instagram.com/", timeout=20000)
        pagina.wait_for_timeout(2000)
        _seleziona_tab_seguiti_instagram(pagina)
        return _scroll_feed_e_raccogli(pagina, _JS_RACCOGLI_POST_INSTAGRAM, "instagram", ultimo_visto)
    finally:
        pagina.close()


def elabora_post(post: PostFeed, conn: sqlite3.Connection, config: Config, extractor=None) -> str:
    """Attribuzione (12.3) + pre-filtro + estrazione LLM + pubblicazione,
    riusando la stessa logica già collaudata in pipeline.py invece di
    duplicarla. Ritorna l'esito: 'pubblicato' | 'quarantena' | 'scartato' |
    'candidato' (handle sconosciuto, comune non attribuibile) |
    'gruppo_comune_non_inferito' (14.6) | 'senza_testo'.

    14.6: per i gruppi Facebook il comune non va MAI inferito dall'autore
    del post (chi pubblica non è chi organizza) — qui trattato passando
    comune_riferimento=None anche quando l'handle è noto, cosa che
    _pubblica_o_metti_in_quarantena/risolvi_comune_evento già gestiscono
    correttamente affidandosi al solo comune_testuale esplicito nel testo.
    """
    e_gruppo = "/groups/" in post.url
    if e_gruppo:
        comune_riferimento = None
    else:
        riga_fonte = attribuisci_post(conn, post.piattaforma, post.handle_autore)
        if riga_fonte is None:
            return "candidato"
        comune_riferimento = riga_fonte["comune"]

    if not post.testo and not post.image_paths:
        return "senza_testo"

    phash_immagine = None
    if post.testo:
        scarta, _motivo = scarta_testo(post.testo, ha_immagine=bool(post.image_paths))
        if scarta:
            return "scartato"
    elif post.image_paths:
        # Pre-filtro grafico (M4, 12.10, 2026-08-28): applicato solo qui,
        # non anche quando c'è testo — con un testo utile il post passa già
        # dal ramo estrai_da_testo, l'immagine non viene mai inviata al VLM
        # in quel caso (M4 riguarda solo il ramo immagine-sola). Il phash è
        # calcolato una sola volta qui e riusato sotto per la cache, invece
        # di riaprire il file una seconda volta.
        with open(post.image_paths[0], "rb") as fh:
            _bytes_prefiltro = fh.read()
        scarta, _motivo, phash_immagine = scarta_immagine(_bytes_prefiltro)
        if scarta:
            return "scartato"

    if extractor is None:
        return "scartato"

    art = Artefatto(
        source_id=f"feed-{post.piattaforma}-{post.handle_autore}",
        url=post.url,
        kind="social",
        text=post.testo,
        image_paths=post.image_paths,
    )
    # Bug reale osservato (2026-08-27): artifacts.source_id ha una foreign
    # key su sources — a differenza di pipeline.esegui_fonte (che chiama
    # _assicura_source prima di registrare un artefatto), qui la fonte
    # "feed-{piattaforma}-{handle}" non esiste mai in sources, causando
    # IntegrityError al primo post con testo utile.
    _assicura_source(conn, art.source_id)
    artifact_id = _registra_artefatto(conn, art, art.source_id)
    fonte = {"source_id": art.source_id, "comune_riferimento": comune_riferimento, "categoria": "social"}

    # Approssimazione di 08.5 con la sola fascia geografica (2026-08-27, vedi
    # extractor/client.py decidi_degradazione_quota): il comune è già noto
    # qui dall'attribuzione handle->fonte, a differenza di pipeline.py dove
    # va derivato dal source_id.
    riga_comune = risolvi_comune(comune_riferimento, conn) if comune_riferimento else None
    fascia_fonte = riga_comune["fascia"] if riga_comune else None

    if post.testo:
        risposta = extractor.estrai_da_testo(
            testo=post.testo,
            artifact_id=artifact_id,
            fonte=art.source_id,
            categoria_fonte="social",
            comune_fonte=comune_riferimento or "",
            url=post.url,
            fascia_fonte=fascia_fonte,
        )
    else:
        # Post senza didascalia utile ma con locandina/immagine allegata,
        # già passata dal pre-filtro grafico sopra (M4). Prima di spendere
        # una chiamata VLM, controlla la cache pHash (12.10: "la stessa
        # locandina compare su 5-10 canali... è questo componente che
        # decide se il budget regge") — un match entro la soglia di Hamming
        # riusa l'estrazione già fatta, zero chiamate aggiuntive.
        da_cache = cerca_in_cache(conn, phash_immagine) if phash_immagine else None
        if da_cache:
            extraction_json_cache, _model_used = da_cache
            risposta = RispostaEstrazione.model_validate_json(extraction_json_cache)
        else:
            with open(post.image_paths[0], "rb") as fh:
                immagine_bytes = fh.read()
            risposta = extractor.estrai_da_immagine(
                immagine_bytes=immagine_bytes,
                artifact_id=artifact_id,
                fonte=art.source_id,
                categoria_fonte="social",
                comune_fonte=comune_riferimento or "",
                url=post.url,
                fascia_fonte=fascia_fonte,
            )
            if phash_immagine:
                salva_in_cache(conn, phash_immagine, risposta.model_dump_json(), model_used="vlm")

    esiti = []
    for evento_estratto in risposta.eventi:
        if e_gruppo and not evento_estratto.comune_testuale:
            esiti.append("gruppo_comune_non_inferito")
            continue
        esiti.append(_pubblica_o_metti_in_quarantena(evento_estratto, art, fonte, conn, config))

    if not esiti:
        return "scartato"
    if "pubblicato" in esiti:
        return "pubblicato"
    if "quarantena" in esiti:
        return "quarantena"
    return esiti[0]
