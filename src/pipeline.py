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
                upsert_evento(conn, evento, source_id=fonte["source_id"])
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
        evento_estratto.comune_testuale, fonte.get("comune_riferimento"), conn
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


def _pubblica_o_metti_in_quarantena(evento_estratto, art, fonte: dict, conn: sqlite3.Connection, config: Config) -> str:
    """06.6: sotto soglia_confidenza -> Quarantena, altrimenti Eventi.

    La quarantena vera e propria (foglio dedicato) è compito del publisher
    (M5 completo); qui si applica solo la soglia e si evita di pubblicare
    un evento incerto come se fosse certo.
    """
    if not evento_estratto.data_inizio:
        return "scartato"  # 06.8: data mancante, non pubblicabile né in quarantena senza data

    comune_riga, penalita_comune = risolvi_comune_evento(
        evento_estratto.comune_testuale, fonte.get("comune_riferimento"), conn
    )
    if comune_riga is None:
        return "quarantena"  # 07.3.7: comune_ambiguo

    confidenza_finale = evento_estratto.confidenza + penalita_comune
    if not evento_estratto.anno_esplicito:
        confidenza_finale -= config.penalita_anno_non_esplicito
    if not evento_estratto.luogo_testuale:
        confidenza_finale -= config.penalita_luogo_assente

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
    }

    eid = upsert_evento(conn, evento, source_id=fonte["source_id"])

    if confidenza_finale < config.soglia_confidenza:
        conn.execute("UPDATE events SET stato = 'quarantena' WHERE event_id = ?", (eid,))
        conn.commit()
        return "quarantena"
    return "pubblicato"


def _costruisci_evento_da_artefatto(art, fonte: dict, conn: sqlite3.Connection) -> dict | None:
    comune_riga, penalita = risolvi_comune_evento(
        art.luogo_testuale, fonte.get("comune_riferimento"), conn
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
