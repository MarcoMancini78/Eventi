"""M9 — Sincronizzazione della lista 'seguiti' reale con coda_follow.

Lettura passiva, non un'azione (14.5b: "la lettura passiva è molto meno
rilevabile dell'azione"). Sostituisce il riportare a mano in chat ogni
follow fatto dall'app: si legge la lista vera direttamente dalla
piattaforma e si allinea coda_follow di conseguenza.

Comportamento sulle voci sconosciute (non in coda_follow): non si scartano
mai (04.7 — principio generale del progetto, mai silenzioso). Diventano
candidati in quarantena con comune da verificare a mano, non seguiti
automaticamente da nessun lotto finché qualcuno non conferma il comune.
"""
from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from .follow import (
    _apri_sessione_browser,
    _assicura_identita_pagina,
    _chiudi_sessione_browser,
    verifica_identita_instagram,
)
from .config import Config


@dataclass
class EsitoSync:
    aggiornati: int  # handle già in coda_follow, marcati 'seguito'
    nuovi: int  # handle non censiti, aggiunti in quarantena
    handle_letti: int  # totale handle raccolti dalla piattaforma


def confronta_e_aggiorna(conn: sqlite3.Connection, piattaforma: str, handle_seguiti: list[str]) -> EsitoSync:
    """Funzione pura (testabile senza browser): dato l'elenco reale degli
    handle seguiti, allinea coda_follow.

    - handle già presenti in coda_follow, in qualunque stato diverso da
      'seguito' -> marcati 'seguito' con data_follow di oggi
    - handle non presenti -> nuova riga in quarantena, comune vuoto (da
      verificare a mano prima che diventi una fonte attiva)
    """
    oggi = datetime.now().isoformat()
    handle_normalizzati = {h.strip().lower().lstrip("@") for h in handle_seguiti if h.strip()}

    esistenti = conn.execute(
        "SELECT source_id, handle FROM coda_follow WHERE piattaforma = ?", (piattaforma,)
    ).fetchall()
    handle_a_source_id = {r["handle"].lower(): r["source_id"] for r in esistenti if r["handle"]}

    aggiornati = 0
    nuovi = 0

    for handle in handle_normalizzati:
        if handle in handle_a_source_id:
            cur = conn.execute(
                "UPDATE coda_follow SET stato='seguito', data_follow=? WHERE piattaforma=? AND handle=? AND stato != 'seguito'",
                (oggi, piattaforma, handle),
            )
            if cur.rowcount > 0:
                aggiornati += 1
        else:
            source_id = f"sconosciuto-{piattaforma}-{handle}"
            conn.execute(
                """
                INSERT INTO coda_follow (source_id, piattaforma, handle, url, soggetto, comune, fascia, categoria, stato, data_follow, note)
                VALUES (?, ?, ?, ?, ?, '', '', 'sconosciuto', 'quarantena', ?, 'trovato nella lista seguiti, comune da verificare')
                ON CONFLICT(source_id, piattaforma) DO NOTHING
                """,
                (source_id, piattaforma, handle, _url_da_handle(piattaforma, handle), handle, oggi),
            )
            if conn.execute("SELECT changes()").fetchone()[0] > 0:
                nuovi += 1

    conn.commit()
    return EsitoSync(aggiornati=aggiornati, nuovi=nuovi, handle_letti=len(handle_normalizzati))


def _url_da_handle(piattaforma: str, handle: str) -> str:
    if piattaforma == "instagram":
        return f"https://www.instagram.com/{handle}"
    return f"https://www.facebook.com/{handle}"


# --- Interazione browser reale: isolata qui, mai chiamata dai test automatici ---

def leggi_seguiti_reali(piattaforma: str, config: Config, sessione_dir: Path | None = None) -> list[str]:
    """Apre il browser con la sessione salvata, naviga alla lista 'seguiti'
    e scrolla fino in fondo raccogliendo gli handle. Nessuna azione:
    solo lettura, coerente con 14.5b.
    """
    contesto = _apri_sessione_browser(piattaforma, sessione_dir)
    try:
        if piattaforma == "facebook":
            _assicura_identita_pagina(contesto, config)
            return _leggi_seguiti_facebook(contesto, config)
        verifica_identita_instagram(contesto, config)
        return _leggi_seguiti_instagram(contesto, config)
    finally:
        _chiudi_sessione_browser(contesto)


# Estrae solo i profili che hanno accanto un bottone di stato-follow
# ("Segui"/"Segui già"/"Following"/"Follow"): è il segnale più affidabile
# per isolare le vere righe della lista dai link di menu/footer/navigazione,
# che l'HTML reale (fornito dall'utente via ispezione manuale) mostra non
# avere mai un simile bottone accanto. Ogni riga della lista contiene due
# link identici (foto + nome): l'href identifica univocamente il profilo.
_JS_RACCOGLI_RIGHE_CON_BOTTONE_FOLLOW = """
() => {
    const bottoni = Array.from(document.querySelectorAll('button')).filter(b => {
        const testo = (b.innerText || '').trim().toLowerCase();
        return ['segui', 'segui gi\\u00e0', 'following', 'follow'].includes(testo);
    });
    const risultati = new Set();
    for (const bottone of bottoni) {
        let nodo = bottone;
        for (let livelli = 0; livelli < 8 && nodo; livelli++) {
            const link = nodo.querySelector ? nodo.querySelector('a[href]') : null;
            if (link && link.getAttribute('href')) {
                risultati.add(link.getAttribute('href'));
                break;
            }
            nodo = nodo.parentElement;
        }
    }
    return Array.from(risultati);
}
"""


# Su Facebook la lista "Pagine seguite" non ha alcun bottone di stato-follow
# accanto a ogni riga (a differenza di Instagram): l'HTML reale ispezionato
# dall'utente mostra solo un bottone "Altre opzioni" con
# aria-label="Altre opzioni per {nome della pagina}". È lo stesso segnale
# strutturale (un elemento presente solo nelle vere righe della lista, mai
# nei link di menu/navigazione), ma diverso testo/attributo.
_JS_RACCOGLI_RIGHE_CON_ALTRE_OPZIONI = """
() => {
    const bottoni = Array.from(document.querySelectorAll('[aria-label]')).filter(b => {
        const label = (b.getAttribute('aria-label') || '').toLowerCase();
        const inizia = label.startsWith('altre opzioni per') || label.startsWith('more options for');
        // Falso positivo reale osservato: il bottone "Altre opzioni per la
        // lista degli amici" appartiene al tablist stesso, non a una riga
        // della lista di profili.
        const rumore = label.includes('la lista degli amici') || label.includes('the friends list');
        return inizia && !rumore;
    });
    const risultati = new Set();
    for (const bottone of bottoni) {
        let nodo = bottone;
        for (let livelli = 0; livelli < 8 && nodo; livelli++) {
            const link = nodo.querySelector ? nodo.querySelector('a[href]') : null;
            if (link && link.getAttribute('href')) {
                risultati.add(link.getAttribute('href'));
                break;
            }
            nodo = nodo.parentElement;
        }
    }
    return Array.from(risultati);
}
"""

# Diagnostica temporanea (2026-08-25): conta quanti elementi con aria-label
# esistono sulla pagina e quanti iniziano davvero per "altre opzioni per",
# per capire se il problema è il selettore o la risalita del DOM quando il
# risultato finale è 0 nonostante l'utente veda la lista popolata.
_JS_DIAGNOSTICA_FACEBOOK = """
() => {
    const tutti = Array.from(document.querySelectorAll('[aria-label]'));
    const conAriaLabel = tutti.map(el => el.getAttribute('aria-label')).filter(Boolean);
    const opzioni = conAriaLabel.filter(l => l.toLowerCase().includes('opzioni') || l.toLowerCase().includes('options'));
    return {
        totale_elementi_con_aria_label: tutti.length,
        esempio_aria_label: conAriaLabel.slice(0, 15),
        aria_label_con_opzioni: opzioni.slice(0, 10),
    };
}
"""


# Bug reale osservato (Facebook): la lista "Pagine seguite" si apre in un
# riquadro/modale con scroll proprio, non con la pagina intera. Scrollare
# la finestra (mouse.wheel su document) non ha alcun effetto sul contenuto
# del modale, che resta fermo sui primi elementi renderizzati -> 0 risultati
# anche con la lista visibilmente popolata sullo schermo. Instagram invece
# usa lo scroll di pagina normale (verificato nel collaudo precedente):
# scrollare entrambi (finestra + eventuale contenitore interno) copre i due
# casi senza doverli distinguere in anticipo.
_JS_SCROLL_CONTENITORE_INTERNO = """
() => {
    let totale = 0;
    for (const el of document.querySelectorAll('div')) {
        const stile = window.getComputedStyle(el);
        const scrollabile = (stile.overflowY === 'auto' || stile.overflowY === 'scroll');
        if (scrollabile && el.scrollHeight > el.clientHeight + 50) {
            el.scrollTop += 2000;
            totale += el.scrollTop;
        }
    }
    return totale;
}
"""


def _scroll_e_raccogli(pagina, script_js: str, max_scroll: int = 40, pausa_ms: int = 800) -> set[str]:
    """Scroll incrementale eseguendo `script_js` ad ogni passo, fino a
    quando due scroll consecutivi non producono più progresso (fine lista)
    o max_scroll (circuit-breaker anti-loop). Il progresso è misurato sia
    dall'altezza della pagina sia dalla somma degli scrollTop dei
    contenitori interni scrollabili, per coprire entrambi i casi (lista a
    piena pagina o lista in modale)."""
    handle_trovati: set[str] = set()
    progresso_precedente = -1

    for _ in range(max_scroll):
        href_trovati = pagina.evaluate(script_js)
        for href in href_trovati:
            handle = href.strip("/").split("/")[-1].split("?")[0]
            if handle:
                handle_trovati.add(handle)

        pagina.mouse.wheel(0, 2000)
        scroll_interno = pagina.evaluate(_JS_SCROLL_CONTENITORE_INTERNO)
        pagina.wait_for_timeout(pausa_ms)

        altezza_pagina = pagina.evaluate("document.body.scrollHeight")
        progresso_corrente = altezza_pagina + scroll_interno
        if progresso_corrente == progresso_precedente:
            break
        progresso_precedente = progresso_corrente

    return handle_trovati


def _leggi_seguiti_instagram(contesto: dict, config: Config) -> list[str]:
    """Bug reale (2026-08-25): instagram.com/?variant=following NON apre
    alcuna lista di seguiti — è identico alla home normale. Screenshot
    reale dell'utente ha chiarito il percorso corretto: andare sul proprio
    profilo (instagram.com/{username}/) e cliccare il link "N seguiti", che
    apre un popup "Chi segui" — questo sì un vero modale con scroll
    proprio, a differenza della scheda Facebook. Lo username è già
    verificato da verifica_identita_instagram prima di questa chiamata,
    quindi si riusa direttamente da config invece di rileggerlo.

    La raccolta usa il bottone di stato ("Segui già") per isolare le vere
    righe della lista dai link di menu/footer/navigazione (HTML reale
    ispezionato dall'utente: il selettore generico precedente raccoglieva
    anche voci come 'inbox', 'reels', 'privacy', il proprio stesso handle)."""
    pagina = contesto["browser"].new_page()
    try:
        username = (config.instagram_username or "").strip().lower().lstrip("@")
        pagina.goto(f"https://www.instagram.com/{username}/", timeout=20000)
        pagina.wait_for_timeout(2000)

        _clicca_link_seguiti_instagram(pagina)

        return sorted(_scroll_e_raccogli(pagina, _JS_RACCOGLI_RIGHE_CON_BOTTONE_FOLLOW))
    finally:
        pagina.close()


def _clicca_link_seguiti_instagram(pagina) -> None:
    """Il link "N seguiti" in cima al profilo apre il popup "Chi segui":
    senza questo click il popup non è nel DOM e la raccolta trova 0 righe."""
    try:
        elemento = pagina.get_by_text(re.compile(r"seguiti$|following$", re.IGNORECASE)).first
        elemento.click(timeout=5000)
        pagina.wait_for_timeout(1500)
        print("  (diagnostica click) link 'seguiti' cliccato con successo")
    except Exception as exc:
        print(f"  (diagnostica click) impossibile cliccare 'seguiti': {exc}")


def _aggiungi_parametro_query(url: str, chiave: str, valore: str) -> str:
    separatore = "&" if "?" in url else "?"
    return f"{url}{separatore}{chiave}={valore}"


def _leggi_seguiti_facebook(contesto: dict, config: Config) -> list[str]:
    """URL confermato dall'utente ispezionando l'interfaccia reale:
    aggiungere &sk=following (o ?sk=following) all'URL della Pagina mostra
    la scheda "Follower" della Pagina — NON un modale, come si era ipotizzato
    nei giri precedenti, ma la pagina normale con scroll di pagina. Questa
    scheda contiene due sotto-tab interni ("Follower" e "Persone seguite"):
    quello attivo di default è "Follower", quindi la lista dei 53 seguiti
    non è nel DOM finché non si clicca il sotto-tab "Persone seguite"
    (screenshot reale fornito dall'utente, 2026-08-25 — spiega il persistente
    0 nonostante l'utente vedesse la lista popolata: la vedeva DOPO aver
    cliccato il sotto-tab a mano, lo script non lo faceva).

    Isolamento delle righe basato sul bottone "Altre opzioni" (aria-label
    "Altre opzioni per {nome}"): a differenza di Instagram, la lista delle
    Pagine seguite da una Pagina non mostra un bottone di stato-follow
    (HTML reale ispezionato dall'utente: solo un menu a tre puntini)."""
    pagina = contesto["browser"].new_page()
    try:
        url_seguiti = _aggiungi_parametro_query(config.facebook_page_url, "sk", "following")
        pagina.goto(url_seguiti, timeout=20000)
        pagina.wait_for_timeout(1500)

        _clicca_sottotab_persone_seguite(pagina)
        _attendi_righe_altre_opzioni(pagina)

        page_id = _id_pagina_da_url(config.facebook_page_url)
        handle = _scroll_e_raccogli(pagina, _JS_RACCOGLI_RIGHE_CON_ALTRE_OPZIONI)
        if page_id:
            handle = {h for h in handle if page_id not in h}  # mai la propria Pagina

        if not handle:
            diagnostica = pagina.evaluate(_JS_DIAGNOSTICA_FACEBOOK)
            print("DIAGNOSTICA (nessun profilo trovato su Facebook):")
            print(f"  elementi con aria-label sulla pagina: {diagnostica['totale_elementi_con_aria_label']}")
            print(f"  esempi di aria-label trovati: {diagnostica['esempio_aria_label']}")
            print(f"  aria-label che contengono 'opzioni'/'options': {diagnostica['aria_label_con_opzioni']}")

        return sorted(handle)
    finally:
        pagina.close()


def _attendi_righe_altre_opzioni(pagina, timeout_ms: int = 8000) -> None:
    """HTML reale salvato dall'utente (2026-08-25, file 'pagina_facebook')
    conferma che la struttura attesa (bottone "Altre opzioni per {nome}"
    accanto al link profilo) è corretta ed esiste per davvero quando il
    tab "Persone seguite" è attivo — quindi il problema non è il selettore,
    ma il tempo: Facebook carica la lista in modo asincrono dopo l'attivazione
    del tab, e il timeout fisso precedente (1.5s) probabilmente non bastava.
    Nessun errore bloccante se scade: la diagnostica esistente se ne accorge
    comunque con un risultato vuoto."""
    try:
        pagina.wait_for_function(
            """() => Array.from(document.querySelectorAll('[aria-label]')).some(
                el => (el.getAttribute('aria-label') || '').toLowerCase().startsWith('altre opzioni per')
            )""",
            timeout=timeout_ms,
        )
    except Exception:
        pass


def _clicca_sottotab_persone_seguite(pagina) -> None:
    """Il sotto-tab "Persone seguite" (dentro la scheda "Follower" della
    Pagina) non è selezionato di default — si apre prima su "Follower".
    Se non lo clicchiamo, la lista dei profili seguiti non è nel DOM.
    Nessun errore bloccante se non lo troviamo: la diagnostica esistente
    in _leggi_seguiti_facebook segnalerà comunque un risultato vuoto."""
    try:
        elemento = pagina.get_by_text(re.compile(r"^Persone seguite$|^People followed$", re.IGNORECASE)).first
        elemento.scroll_into_view_if_needed(timeout=5000)
        try:
            elemento.click(timeout=5000)
        except Exception:
            # Bug reale osservato: l'elemento risulta risolto ma Playwright
            # lo giudica "not visible" dopo 5s di retry. Un click via JS
            # (el.click()) "riesce" senza sollevare errori ma non attiva
            # il tab (verificato dal vivo: la diagnostica resta identica) —
            # probabile handler React agganciato a eventi mouse sintetici,
            # non al semplice .click() nativo. force=True fa comunque
            # generare a Playwright un evento mouse reale (mousedown/up)
            # sulle coordinate dell'elemento, bypassando solo i controlli
            # di attuabilità (visibilità/stabilità), non l'evento stesso.
            elemento.click(timeout=5000, force=True)
        pagina.wait_for_timeout(1500)
        print("  (diagnostica click) sotto-tab 'Persone seguite' cliccato con successo")
    except Exception as exc:
        print(f"  (diagnostica click) impossibile cliccare 'Persone seguite': {exc}")


def _id_pagina_da_url(page_url: str) -> str | None:
    """ID numerico o handle della propria Pagina, per escluderlo dai
    risultati (bug osservato: la propria Pagina/i suoi link di navigazione
    finivano nella lista dei 'seguiti')."""
    m = re.search(r"[?&]id=(\d+)", page_url)
    if m:
        return m.group(1)
    m = re.search(r"facebook\.com/([^/?#]+)", page_url)
    return m.group(1) if m else None
