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

Selettori DOM (Facebook: scheda "Feed → Più recenti"; Instagram: vista
"Seguiti"/cronologica) NON ancora verificati contro l'interfaccia reale
— a differenza di sync_seguiti.py, i cui selettori sono stati corretti in
14 giri di collaudo dal vivo. Vanno considerati un primo tentativo
ragionevole (basato su attributi ARIA/ruoli standard), da aggiustare al
primo collaudo reale seguendo lo stesso principio già applicato altrove
in questo progetto: fermarsi e chiedere l'HTML reale dopo un paio di
fallimenti, non continuare a indovinare.
"""
from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path

from .adapters.base import Artefatto
from .config import Config
from .follow import (
    _apri_sessione_browser,
    _assicura_identita_pagina,
    _chiudi_sessione_browser,
    verifica_identita_instagram,
)
from .pipeline import _pubblica_o_metti_in_quarantena, _registra_artefatto
from .prefilter import scarta_testo


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


# --- Selettori DOM: primo tentativo, da verificare contro l'interfaccia reale ---

_JS_RACCOGLI_POST_FACEBOOK = """
() => {
    const risultati = [];
    for (const articolo of document.querySelectorAll('div[role="article"]')) {
        const linkAutore = articolo.querySelector('h3 a[href], strong a[href]');
        if (!linkAutore) continue;
        const href = linkAutore.getAttribute('href') || '';
        const linkPermalink = articolo.querySelector('a[href*="/posts/"], a[href*="/videos/"], a[href*="story_fbid"]');
        const permalink = linkPermalink ? linkPermalink.getAttribute('href') : href;
        const testo = articolo.innerText || '';
        risultati.push({href, permalink, testo});
    }
    return risultati;
}
"""

_JS_RACCOGLI_POST_INSTAGRAM = """
() => {
    const risultati = [];
    for (const articolo of document.querySelectorAll('article')) {
        const linkAutore = articolo.querySelector('header a[href]');
        if (!linkAutore) continue;
        const href = linkAutore.getAttribute('href') || '';
        const linkPost = articolo.querySelector('a[href*="/p/"], a[href*="/reel/"]');
        const permalink = linkPost ? linkPost.getAttribute('href') : href;
        const caption = articolo.querySelector('h1, span[dir="auto"]');
        risultati.push({href, permalink, testo: caption ? caption.innerText : ''});
    }
    return risultati;
}
"""


def _handle_da_href_profilo(href: str, piattaforma: str) -> str:
    path = href.strip("/").split("?")[0]
    segmenti = [s for s in path.split("/") if s]
    return segmenti[0].lower() if segmenti else ""


def _post_id_da_permalink(permalink: str) -> str:
    m = re.search(r"/(?:posts|videos|p|reel)/([^/?#]+)", permalink)
    if m:
        return m.group(1)
    return re.sub(r"[^a-zA-Z0-9]", "", permalink)[-32:] or permalink


def _scroll_feed_e_raccogli(pagina, script_js: str, piattaforma: str, ultimo_visto: str | None, max_scroll: int = 40) -> list[PostFeed]:
    """Scroll cronologico fino all'ultimo post già visto (change detection
    sul post ID, 12.3) o max_scroll (circuit-breaker anti-loop, coerente
    con lo stesso principio già applicato in sync_seguiti._scroll_e_raccogli)."""
    trovati: dict[str, PostFeed] = {}
    ordine: list[str] = []

    for _ in range(max_scroll):
        grezzi = pagina.evaluate(script_js)
        fermato = False
        for g in grezzi:
            handle = _handle_da_href_profilo(g["href"], piattaforma)
            if not handle:
                continue
            permalink = g.get("permalink") or g["href"]
            post_id = _post_id_da_permalink(permalink)
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


def _leggi_feed_instagram(contesto: dict, config: Config, ultimo_visto: str | None) -> list[PostFeed]:
    pagina = contesto["browser"].new_page()
    try:
        pagina.goto("https://www.instagram.com/", timeout=20000)
        pagina.wait_for_timeout(2000)
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

    if not post.testo:
        return "senza_testo"

    scarta, _motivo = scarta_testo(post.testo, ha_immagine=bool(post.image_paths))
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
    artifact_id = _registra_artefatto(conn, art, art.source_id)
    fonte = {"source_id": art.source_id, "comune_riferimento": comune_riferimento, "categoria": "social"}

    risposta = extractor.estrai_da_testo(
        testo=post.testo,
        artifact_id=artifact_id,
        fonte=art.source_id,
        categoria_fonte="social",
        comune_fonte=comune_riferimento or "",
        url=post.url,
    )

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
