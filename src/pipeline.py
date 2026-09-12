"""M2/M5/M11 (parziale): orchestrazione fetch -> pre-filtro -> estrazione -> normalizzazione -> dedup.

I T0 con campi già strutturati (ical, jsonld) bypassano l'estrattore: non
c'è nulla da capire, solo da normalizzare. Gli artefatti T1 generici (html)
che superano il pre-filtro passano dall'estrattore LLM (M5); sotto la
soglia di confidenza vanno in quarantena (06.6), mai scartati in silenzio.

La coda a priorità, il budget di tempo e l'isolamento totale degli errori
(08.3, 08.4) arrivano con M11: qui ogni fonte è comunque isolata in un
try/except, perché è la regola non negoziabile 15.1.4.
"""
from __future__ import annotations

import hashlib
import logging
import sqlite3
from datetime import datetime, timezone

from .adapters.aggregatore_regionale import AggregatoreRegionalePlaywrightAdapter
from .adapters.email_imap import EmailImapAdapter
from .adapters.html import HtmlAdapter
from .adapters.ical import ICalAdapter
from .adapters.jsonld import JsonLdAdapter
from .adapters.pa_design_system import PaDesignSystemAdapter
from .adapters.rss import RssAdapter
from .adapters.telegram import TelegramAdapter
from .config import Config
from .dedup import upsert_evento
from .extractor.client import ErroreQuotaEsaurita, ExtractorClient
from .normalizer import risolvi_comune_evento, titolo_normalizzato, titolo_visualizzato
from .prefilter import scarta_testo
from .series import espandi_serie_in_eventi, upsert_serie

logger = logging.getLogger(__name__)

_ADAPTER_PER_TIER = {
    "T0_ical": ICalAdapter(),
    "T0_jsonld": JsonLdAdapter(),
    "T0_rss": RssAdapter(),
    "T1_html": HtmlAdapter(),
    # M3, 2026-08-28: aggregatori regionali con JSON-LD iniettato via JS
    # (visitlmr.it) — browser reale, costoso per richiesta, va usato con
    # parsimonia (poche fonti di questo tipo, non l'intero perimetro).
    "T0_aggregatore_playwright": AggregatoreRegionalePlaywrightAdapter(),
    # L3 (12.5, 17-lavoro-residuo.md, 2026-09-01): variante legacy del
    # template AGID pa_design_system, senza JSON-LD ma con una struttura
    # HTML identica su centinaia di comuni (verificato su un campione di
    # più province) — selettori dedicati invece del generico T1_html+LLM.
    "T0_pa_design_system": PaDesignSystemAdapter(),
}


def comune_riferimento_da_source_id(source_id: str, conn: sqlite3.Connection) -> str | None:
    """Deriva il comune di riferimento di una fonte 'comune-{slug}' dallo
    stesso slug con cui `run.py import-fonti` costruisce il source_id
    (`nome.lower().replace(' ', '-')`) — nessuna colonna SQL dedicata, lo
    slug nel source_id è già la fonte di verità.

    Indispensabile per le fonti T0 strutturate (pa_design_system, jsonld):
    non passano dall'estrattore LLM, quindi non hanno mai un
    `comune_testuale` da cui risolvere il comune — se `comune_riferimento`
    resta None, `risolvi_comune_evento` non ha nessun livello a cui
    ripiegare e ogni evento viene scartato in silenzio (2026-09-12, bug
    reale trovato su comune-calosso: 159 fonti su 386 con eventi trovati
    ma mai pubblicati, perché il worker del giro schedulato non chiamava
    questa derivazione — la chiamava solo il percorso di ricorrezione
    mirata `correggi-fonte-html`)."""
    if not source_id.startswith("comune-"):
        return None
    slug = source_id[len("comune-"):]
    riga = conn.execute(
        "SELECT comune FROM comuni WHERE LOWER(REPLACE(comune, ' ', '-')) = ?", (slug,)
    ).fetchone()
    return riga["comune"] if riga else None


def esegui_fonte(
    fonte: dict, conn: sqlite3.Connection, config: Config, extractor: ExtractorClient | None = None
) -> dict:
    """Elabora una fonte isolatamente. Ritorna un riepilogo per il Log (03.1.7).

    Non solleva mai: un'eccezione qui non deve mai fermare il run (15.1.4).
    `extractor=None` disabilita l'estrazione LLM: i T1 restano al
    pre-filtro, comportamento utile per i test offline.
    """
    riepilogo = {
        "source_id": fonte["source_id"],
        "artefatti": 0,
        "eventi_pubblicati": 0,
        "eventi_in_quarantena": 0,
        "occorrenze_generate": 0,
        "scartati_prefilter": 0,
        "chiamate_llm": 0,
        "errore": None,
    }

    metodo = fonte["metodo"]
    # email/telegram (M7) leggono credenziali da Config, non disponibile al
    # momento dell'import del modulo: istanziati qui per fonte, a
    # differenza degli adapter in _ADAPTER_PER_TIER che sono stateless.
    if metodo == "T0_email":
        adapter = EmailImapAdapter(config)
    elif metodo == "T0_telegram":
        adapter = TelegramAdapter(config)
    else:
        adapter = _ADAPTER_PER_TIER.get(metodo)
    if adapter is None:
        riepilogo["errore"] = f"metodo sconosciuto: {metodo}"
        return riepilogo

    try:
        artefatti = adapter.fetch(fonte)
    except Exception as exc:  # isolamento totale (15.1 regola 4, 08.4)
        logger.warning("Fonte %s fallita: %s", fonte["source_id"], exc)
        riepilogo["errore"] = str(exc)
        return riepilogo

    riepilogo["artefatti"] = len(artefatti)
    _assicura_source(conn, fonte["source_id"])

    for art in artefatti:
        # I soli T0 con campi già strutturati (ical/jsonld) bypassano il pre-filtro
        # testuale sul titolo: non c'è nulla da scartare, l'evento è già certo.
        if art.titolo and art.data_inizio:
            evento = _costruisci_evento_da_artefatto(art, fonte, conn)
            if evento:
                eid = upsert_evento(conn, evento, source_id=fonte["source_id"])
                # 2026-09-09, richiesto dall'utente (caso Brandizzo
                # 182241c091a6): stesso fix già applicato al ramo T1/LLM in
                # _pubblica_o_metti_in_quarantena — un evento che era finito
                # in quarantena da un giro precedente (es. quando la fonte
                # era ancora T1_html, prima di essere promossa a T0_jsonld)
                # deve uscirne quando il T0 lo ri-conferma con dati certi,
                # non restarci bloccato per sempre. 'quarantena' è un
                # valore calcolato (mai una decisione dell'operatore, a
                # differenza di 'ok'/'scartato'), sicuro da sovrascrivere.
                conn.execute(
                    "UPDATE events SET stato = 'nuovo' WHERE event_id = ? AND stato = 'quarantena'", (eid,)
                )
                conn.commit()
                riepilogo["eventi_pubblicati"] += 1
            continue

        # T1 generico (html): il testo grezzo va pre-filtrato prima di
        # spendere quota LLM (15.1 regola 7).
        scarta, motivo = scarta_testo(art.text or "", ha_immagine=bool(art.image_paths))
        if scarta:
            riepilogo["scartati_prefilter"] += 1
            continue

        if extractor is None:
            continue  # nessun estrattore configurato: l'artefatto resta in coda

        artifact_id = _registra_artefatto(conn, art, fonte["source_id"])
        try:
            from .scheduling import fascia_da_source_id

            risposta = extractor.estrai_da_testo(
                testo=art.text,
                artifact_id=artifact_id,
                fonte=fonte["source_id"],
                categoria_fonte=fonte.get("categoria", "altro"),
                comune_fonte=fonte.get("comune_riferimento") or "",
                url=art.url,
                fascia_fonte=fascia_da_source_id(conn, fonte["source_id"]),
            )
        except ErroreQuotaEsaurita as exc:
            # 08.5: l'artefatto resta con processed_at=null, ripreso il giorno dopo.
            logger.info("Budget LLM esaurito su fonte %s: %s", fonte["source_id"], exc)
            riepilogo["errore"] = str(exc)
            break
        except Exception as exc:  # isolamento totale anche per la chiamata LLM
            logger.warning("Estrazione fallita per artifact %s: %s", artifact_id, exc)
            continue

        riepilogo["chiamate_llm"] += 1
        for evento_estratto in risposta.eventi:
            try:
                if evento_estratto.ricorrenza.e_ricorrente:
                    n_occorrenze = _gestisci_evento_ricorrente(evento_estratto, art, fonte, conn, config)
                    riepilogo["occorrenze_generate"] += n_occorrenze
                    continue

                esito = _pubblica_o_metti_in_quarantena(evento_estratto, art, fonte, conn, config)
                if esito == "pubblicato":
                    riepilogo["eventi_pubblicati"] += 1
                elif esito == "quarantena":
                    riepilogo["eventi_in_quarantena"] += 1
            except Exception as exc:
                # Isolamento totale (15.1 regola 4): un dato malformato in
                # un singolo evento estratto (bug reale osservato,
                # 2026-08-26: giorno della settimana fuori formato che
                # fermava l'intero run multi-fonte) non deve mai propagarsi
                # oltre questo evento — logga e prosegue con gli altri.
                logger.warning(
                    "Evento estratto scartato per errore di normalizzazione (fonte %s): %s",
                    fonte["source_id"], exc,
                )
                riepilogo["errore"] = riepilogo["errore"] or f"evento scartato: {exc}"

    return riepilogo


def _gestisci_evento_ricorrente(evento_estratto, art, fonte: dict, conn: sqlite3.Connection, config: Config) -> int:
    """07.9: un evento ricorrente diventa una Serie, non una riga con testo esplicativo.

    Ritorna il numero di occorrenze pubblicate. Un comune non risolvibile
    o una frequenza non supportata (solo settimanale/mensile, non annuale)
    fanno rinunciare silenziosamente all'espansione: la serie riparte al
    prossimo avvistamento con dati migliori.
    """
    comune_riga, _ = risolvi_comune_evento(
        evento_estratto.comune_testuale, fonte.get("comune_riferimento"), conn,
        categoria_fonte=fonte.get("categoria_soggetto") or fonte.get("categoria"),
    )
    if comune_riga is None:
        return 0

    serie_id = upsert_serie(
        conn,
        evento_estratto.ricorrenza,
        titolo=evento_estratto.titolo,
        tipologia=evento_estratto.tipologia,
        comune=comune_riga["comune"],
        luogo=evento_estratto.luogo_testuale,
        fonte=fonte["source_id"],
    )
    if serie_id is None:
        return 0

    occorrenze = espandi_serie_in_eventi(conn, serie_id, config)
    for occ in occorrenze:
        upsert_evento(conn, occ, source_id=fonte["source_id"])
    return len(occorrenze)


def _assicura_source(conn: sqlite3.Connection, source_id: str) -> None:
    conn.execute("INSERT OR IGNORE INTO sources (source_id) VALUES (?)", (source_id,))
    conn.commit()


def _registra_artefatto(conn: sqlite3.Connection, art, source_id: str) -> str:
    artifact_id = hashlib.sha1(f"{source_id}|{art.url}|{art.raw_hash}".encode()).hexdigest()[:16]
    conn.execute(
        """
        INSERT OR IGNORE INTO artifacts (artifact_id, source_id, url, fetched_at, kind, text, raw_hash)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (artifact_id, source_id, art.url, art.fetched_at, art.kind, art.text, art.raw_hash),
    )
    conn.commit()
    return artifact_id


def _pubblica_o_metti_in_quarantena(
    evento_estratto, art, fonte: dict, conn: sqlite3.Connection, config: Config,
    data_post: str | None = None, ora_post: str | None = None,
) -> str:
    """06.6: sotto soglia_confidenza -> Quarantena, altrimenti Eventi.

    La quarantena vera e propria (foglio dedicato) è compito del publisher
    (M5 completo); qui si applica solo la soglia e si evita di pubblicare
    un evento incerto come se fosse certo.

    `data_post`/`ora_post` (2026-09-06, richiesto dall'utente, caso
    Bergamasco df3ef713fa46): solo per i post Facebook (feed_social.py),
    dove l'URL salvato punta sempre alla pagina dell'autore e mai a un
    permalink del singolo post — con molti post sulla stessa pagina, la
    data/ora di pubblicazione letta dal tooltip è l'unico modo per
    rintracciare quale post specifico ha generato l'evento.
    """
    if not evento_estratto.data_inizio:
        return "scartato"  # 06.8: data mancante, non pubblicabile né in quarantena senza data

    comune_riga, penalita_comune = risolvi_comune_evento(
        evento_estratto.comune_testuale, fonte.get("comune_riferimento"), conn,
        categoria_fonte=fonte.get("categoria_soggetto") or fonte.get("categoria"),
        penalita_fonte_affidabile=config.penalita_comune_da_fonte_affidabile,
        penalita_fonte_generica=config.penalita_comune_da_fonte_generica,
    )
    if comune_riga is None:
        return "quarantena"  # 07.3.7: comune_ambiguo

    confidenza_finale = evento_estratto.confidenza + penalita_comune
    # 2026-09-04, richiesto dall'utente: un evento in quarantena mostrava
    # solo il punteggio finale, senza spiegare quali penalità l'hanno
    # portato sotto soglia — bisognava indovinare cosa mancasse per
    # decidere se promuovere o scartare.
    dettagli_penalita = [f"confidenza LLM: {evento_estratto.confidenza}"]
    if penalita_comune:
        dettagli_penalita.append(f"comune inferito dalla fonte, non dal testo ({penalita_comune})")
    if not evento_estratto.anno_esplicito:
        confidenza_finale -= config.penalita_anno_non_esplicito
        dettagli_penalita.append(f"anno non esplicito nel testo (-{config.penalita_anno_non_esplicito})")
    # 2026-09-07, richiesto dall'utente: il luogo (posto preciso dentro il
    # comune) non penalizza più la confidenza — un evento diffuso o
    # itinerante può non averne uno, è un dettaglio in più quando
    # presente, non un segnale di scarsa certezza quando assente. Il
    # comune (già penalizzato sopra quando inferito) resta l'unico dato
    # di posizione che conta per l'affidabilità.
    dettaglio_confidenza = "; ".join(dettagli_penalita)

    titolo_norm = titolo_normalizzato(evento_estratto.titolo, comune_riga["comune"])
    evento = {
        "titolo": titolo_visualizzato(evento_estratto.titolo),
        "titolo_normalizzato": titolo_norm,
        "descrizione": (evento_estratto.descrizione or "")[:400],
        "tipologia": evento_estratto.tipologia,
        "data_inizio": evento_estratto.data_inizio,
        "ora_inizio": evento_estratto.ora_inizio,
        "data_fine": evento_estratto.data_fine or evento_estratto.data_inizio,
        "ora_fine": evento_estratto.ora_fine,
        "comune": comune_riga["comune"],
        "comune_normalizzato": titolo_normalizzato(comune_riga["comune"]),
        "luogo": evento_estratto.luogo_testuale,
        "km": comune_riga["km"],
        "minuti": comune_riga["minuti"],
        "prezzo": evento_estratto.prezzo,
        "organizzatore": evento_estratto.organizzatore,
        "url": art.url,
        "url_immagine": art.image_paths[0] if art.image_paths else None,
        # Se l'LLM non ha trovato un link esplicito "scopri di più" nel
        # testo, usa l'URL remoto originale dell'immagine (locandina/post)
        # come approfondimento — meglio di niente, e sempre un link reale
        # navigabile invece del solo file scaricato in locale.
        "url_approfondimento": evento_estratto.url_approfondimento or (
            art.image_urls[0] if art.image_urls else None
        ),
        "confidenza": max(0, min(100, confidenza_finale)),
        "dettaglio_confidenza": dettaglio_confidenza,
        "campi_incerti": ", ".join(evento_estratto.campi_incerti) or None,
        "note_estrazione": evento_estratto.note_estrazione,
        "data_post": data_post,
        "ora_post": ora_post,
    }

    eid = upsert_evento(conn, evento, source_id=fonte["source_id"])

    if confidenza_finale < config.soglia_confidenza:
        conn.execute("UPDATE events SET stato = 'quarantena' WHERE event_id = ?", (eid,))
        conn.commit()
        return "quarantena"

    # 2026-09-09, richiesto dall'utente (caso Caselette 272614985a67,
    # secondo giro): un evento già in quarantena da un run precedente, una
    # volta ri-estratto con dati migliori (es. dopo un fix al rilevamento
    # dei link di dettaglio) che portano la confidenza sopra soglia, deve
    # uscire dalla quarantena — prima restava bloccato per sempre a
    # stato='quarantena' anche con confidenza 95, perché upsert_evento non
    # tocca mai 'stato' (deliberatamente, è una colonna che l'operatore
    # può cambiare da Sheets) e qui si scriveva 'quarantena' solo nel ramo
    # sotto soglia, mai il contrario. 'quarantena' è però un valore
    # CALCOLATO da questa stessa funzione, non una decisione
    # dell'operatore (a differenza di 'ok'/'scartato', scritte solo da
    # publisher.applica_azioni_quarantena) — riportarlo a 'nuovo' qui è
    # sicuro. Non tocca 'ok' (già promosso a mano) né 'scartato' (già
    # scartato a mano): quelle restano decisioni dell'operatore, mai
    # sovrascritte da un run automatico.
    conn.execute(
        "UPDATE events SET stato = 'nuovo' WHERE event_id = ? AND stato = 'quarantena'", (eid,)
    )
    conn.commit()
    return "pubblicato"


class ErroreRiprocessaFonteHtml(Exception):
    """Sollevato quando una fonte non può essere ricorretta (es. source_id
    non trovato, o non è una fonte T1_html/aggregatore rilanciabile)."""


# 2026-09-07, esteso (richiesto dall'utente): 'riprocessa_quarantena' deve
# poter rilanciare qualunque fonte "sito web" gestita da esegui_fonte, non
# solo T1_html — T0_jsonld/T0_ical/T0_rss hanno campi già strutturati (bypassano
# l'estrattore) ma un dato mancante può comunque dipendere da un fix al
# parser della fonte, non solo dal rilevamento dei link di dettaglio.
# Esclusi email/telegram (M7): richiedono credenziali/stato IMAP diversi
# da un semplice re-fetch HTTP, fuori scope per una ricorrezione mirata.
_METODI_RIPROCESSABILI = {
    "T1_html", "T0_aggregatore_playwright", "T0_pa_design_system",
    "T0_jsonld", "T0_ical", "T0_rss",
}


def riprocessa_fonti_html(
    source_ids: list[str], conn: sqlite3.Connection, config: Config, extractor: ExtractorClient
) -> list[dict]:
    """Utility di correzione mirata (2026-09-06, richiesto dall'utente dopo
    il caso Casal Cermelli 309f6c8c01f2): un fix alla logica di rilevamento
    dei link di dettaglio (adapters/html.py) non tocca gli eventi già in
    quarantena da un run precedente — la fonte non viene mai rifetchata da
    sola finché non arriva il prossimo giro schedulato, quindi un evento
    con solo l'anteprima (invece del dettaglio completo) resta così finché
    non lo si ricorregge esplicitamente. Analogo a
    feed_social.riprocessa_eventi_instagram, ma per fonte invece che per
    singolo post: qui si rilancia l'intera fonte con l'adapter aggiornato
    (che può trovare più pagine di dettaglio da un solo indice), non un
    singolo URL.

    A differenza del feed social, qui non serve riaprire un URL salvato
    sull'evento (che potrebbe essere l'indice, mai un vero permalink per
    l'HTML generico): si rilancia l'endpoint della FONTE, non del singolo
    evento — è la fonte, non l'evento, a dover essere rivista con la
    logica nuova.

    Ritorna una lista di dict {source_id, esito, dettaglio} — mai solleva
    per un singolo fallimento (isolamento totale, 15.1 regola 4): un
    source_id sbagliato non deve bloccare la correzione degli altri."""
    risultati = []
    for source_id in source_ids:
        try:
            risultati.append(_riprocessa_una_fonte_html(source_id, conn, config, extractor))
        except ErroreRiprocessaFonteHtml as exc:
            risultati.append({"source_id": source_id, "esito": "errore", "dettaglio": str(exc)})
    return risultati


def _riprocessa_una_fonte_html(
    source_id: str, conn: sqlite3.Connection, config: Config, extractor: ExtractorClient
) -> dict:
    riga = conn.execute(
        "SELECT endpoint, tier, categoria FROM sources WHERE source_id = ?", (source_id,)
    ).fetchone()
    if not riga:
        raise ErroreRiprocessaFonteHtml("source_id non trovato in sources")
    if riga["tier"] not in _METODI_RIPROCESSABILI:
        raise ErroreRiprocessaFonteHtml(
            f"tier '{riga['tier']}' non ricorreggibile con questo comando (solo {sorted(_METODI_RIPROCESSABILI)})"
        )
    if not riga["endpoint"]:
        raise ErroreRiprocessaFonteHtml("fonte senza endpoint")

    vecchi_ids = {
        r["event_id"]
        for r in conn.execute(
            "SELECT DISTINCT event_id FROM event_sources WHERE source_id = ?", (source_id,)
        ).fetchall()
    }

    comune_riferimento = comune_riferimento_da_source_id(source_id, conn)

    fonte = {
        "source_id": source_id,
        "endpoint": riga["endpoint"],
        "metodo": riga["tier"],
        "comune_riferimento": comune_riferimento,
        "categoria": riga["categoria"],
    }

    riepilogo = esegui_fonte(fonte, conn, config, extractor)
    if riepilogo.get("errore"):
        return {"source_id": source_id, "esito": "errore", "dettaglio": riepilogo["errore"]}

    nuovi_ids = {
        r["event_id"]
        for r in conn.execute(
            "SELECT DISTINCT event_id FROM event_sources WHERE source_id = ?", (source_id,)
        ).fetchall()
    } - vecchi_ids

    if not nuovi_ids:
        return {
            "source_id": source_id, "esito": "nessun_cambiamento",
            "dettaglio": f"riprocessato: {riepilogo['eventi_pubblicati']} pubblicati, "
                         f"{riepilogo['eventi_in_quarantena']} in quarantena, nessun evento NUOVO creato",
        }

    # A differenza di feed_social._riprocessa_un_evento_instagram (un solo
    # post, quindi al più un vecchio evento da archiviare), qui l'intero
    # indice viene riletto: può produrre più pagine di dettaglio nuove
    # senza che nessun vecchio evento venga sostituito 1:1 (l'indice da
    # solo, prima del fix, produceva un singolo artefatto con più eventi
    # generici). Gli eventi vecchi restano quindi NON toccati qui — è
    # l'operatore a decidere se scartarli dal foglio Quarantena (azione
    # 'scarta'), coerente con 04.7 (mai un dato perso in silenzio).
    return {
        "source_id": source_id, "esito": "nuovi_eventi",
        "dettaglio": f"{len(nuovi_ids)} nuovo/i evento/i: {sorted(nuovi_ids)} — "
                     f"eventi precedenti di questa fonte NON toccati, valutare se scartarli a mano",
    }


def riprocessa_quarantena(conn: sqlite3.Connection, config: Config, extractor: ExtractorClient) -> dict:
    """2026-09-07, richiesto dall'utente: un solo comando che scorre TUTTI
    gli eventi in quarantena e li ricorregge, smistando da solo il tipo di
    fonte di ciascuno — l'operatore non deve più sapere a mano se un
    evento viene da un sito HTML, da Instagram o da Facebook, né cercare
    i source_id/event_id giusti da passare a comandi separati
    (correggi-post, correggi-fonte-html).

    Smistamento per prefisso di source_id (event_sources), non per
    tabella `sources` (le fonti sintetiche 'feed-{piattaforma}-{handle}'
    di feed_social.py non hanno mai un tier lì, vedi feed_social.py):
    - 'feed-instagram-*' -> feed_social.riprocessa_eventi_instagram
      (permalink diretto al post, riapribile).
    - 'feed-facebook-*' -> segnalato esplicitamente come NON
      riprocessabile: l'URL salvato per Facebook è la pagina
      dell'autore, mai un permalink al singolo post (limite noto,
      documentato in feed_social.py — non un bug da aggirare qui,
      resta correzione manuale).
    - ogni altro source_id (siti T0/T1) -> pipeline.riprocessa_fonti_html,
      una sola volta per fonte anche se più eventi in quarantena la
      condividono (rilanciare la stessa fonte più volte nello stesso giro
      sarebbe lavoro ripetuto senza guadagno).

    Un evento con più fonti di tipi diversi viene ricorretto da ciascun
    ramo applicabile (isolamento totale, 15.1 regola 4): un fallimento su
    un ramo non deve bloccare gli altri.

    Ritorna un riepilogo per tipo di fonte — mai un event_id/source_id
    lasciato silenziosamente fuori (04.7): ogni evento in quarantena
    all'inizio del giro compare in almeno una delle liste del risultato."""
    eventi_quarantena = conn.execute(
        "SELECT event_id FROM events WHERE stato = 'quarantena'"
    ).fetchall()

    fonti_instagram: dict[str, list[str]] = {}  # event_id -> [source_id, ...]
    fonti_facebook: dict[str, list[str]] = {}
    fonti_html: dict[str, set[str]] = {}  # source_id -> {event_id, ...}

    for riga in eventi_quarantena:
        event_id = riga["event_id"]
        fonti = conn.execute(
            "SELECT DISTINCT source_id FROM event_sources WHERE event_id = ?", (event_id,)
        ).fetchall()
        for r in fonti:
            source_id = r["source_id"]
            if source_id.startswith("feed-instagram-"):
                fonti_instagram.setdefault(event_id, []).append(source_id)
            elif source_id.startswith("feed-facebook-"):
                fonti_facebook.setdefault(event_id, []).append(source_id)
            else:
                fonti_html.setdefault(source_id, set()).add(event_id)

    risultati_instagram = (
        feed_social_module().riprocessa_eventi_instagram(
            sorted(fonti_instagram), conn, config, extractor
        )
        if fonti_instagram else []
    )

    risultati_html = riprocessa_fonti_html(sorted(fonti_html), conn, config, extractor) if fonti_html else []

    risultati_facebook = [
        {
            "event_id": event_id, "esito": "non_riprocessabile",
            "dettaglio": "Facebook: l'URL salvato è la pagina dell'autore, non un permalink al "
                         "singolo post — non riapribile automaticamente, serve correzione manuale "
                         "(riaprire il feed, cercare il post)",
        }
        for event_id in sorted(fonti_facebook)
    ]

    return {
        "totale_in_quarantena": len(eventi_quarantena),
        "instagram": risultati_instagram,
        "html": risultati_html,
        "facebook_non_riprocessabili": risultati_facebook,
    }


def feed_social_module():
    """Import ritardato (2026-09-07): feed_social importa da pipeline
    (_pubblica_o_metti_in_quarantena), un import diretto in testa al file
    creerebbe un ciclo. Stesso pattern già usato altrove nel modulo per
    import interni tardivi (es. .scheduling in esegui_fonte)."""
    from . import feed_social

    return feed_social


def _costruisci_evento_da_artefatto(art, fonte: dict, conn: sqlite3.Connection) -> dict | None:
    comune_riga, penalita = risolvi_comune_evento(
        art.luogo_testuale, fonte.get("comune_riferimento"), conn,
        categoria_fonte=fonte.get("categoria_soggetto") or fonte.get("categoria"),
    )
    if comune_riga is None:
        return None  # 07.3.7: nessun match -> quarantena (M5, non ancora implementata qui)

    titolo_norm = titolo_normalizzato(art.titolo, comune_riga["comune"])
    return {
        "titolo": titolo_visualizzato(art.titolo),
        "titolo_normalizzato": titolo_norm,
        "descrizione": (art.descrizione or "")[:400],
        "tipologia": "altro",  # la classificazione vera arriva con l'estrattore (M5)
        "data_inizio": art.data_inizio,
        "ora_inizio": art.ora_inizio,
        "data_fine": art.data_fine or art.data_inizio,
        "ora_fine": None,
        "comune": comune_riga["comune"],
        "comune_normalizzato": titolo_normalizzato(comune_riga["comune"]),
        "luogo": art.luogo_testuale,
        "km": comune_riga["km"],
        "minuti": comune_riga["minuti"],
        "prezzo": None,
        "organizzatore": None,
        "url": art.url,
        "url_immagine": art.image_paths[0] if art.image_paths else None,
        "confidenza": 95 + penalita,
    }
