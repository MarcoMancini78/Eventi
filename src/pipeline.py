"""M2/M11 (parziale): orchestrazione minima fetch -> pre-filtro -> normalizzazione -> dedup.

Questa è la versione ridotta prevista da M2 ("un evento reale nel foglio,
senza LLM"): copre solo gli adattatori T0/T1 che non richiedono l'estrattore
per i campi già strutturati (ical, jsonld). Per gli artefatti T1 generici
(html) senza data strutturata, l'evento resta grezzo in attesa dell'estrattore
LLM (M5) e non viene ancora pubblicato come riga completa.

La coda a priorità, il budget di tempo e l'isolamento totale degli errori
(08.3, 08.4) arrivano con M11: qui ogni fonte è comunque isolata in un
try/except, perché è la regola non negoziabile 15.1.4.
"""
from __future__ import annotations

import logging
import sqlite3

from .adapters.html import HtmlAdapter
from .adapters.ical import ICalAdapter
from .adapters.jsonld import JsonLdAdapter
from .adapters.rss import RssAdapter
from .config import Config
from .dedup import upsert_evento
from .normalizer import risolvi_comune_evento, titolo_normalizzato, titolo_visualizzato
from .prefilter import scarta_testo

logger = logging.getLogger(__name__)

_ADAPTER_PER_TIER = {
    "T0_ical": ICalAdapter(),
    "T0_jsonld": JsonLdAdapter(),
    "T0_rss": RssAdapter(),
    "T1_html": HtmlAdapter(),
}


def esegui_fonte(fonte: dict, conn: sqlite3.Connection, config: Config) -> dict:
    """Elabora una fonte isolatamente. Ritorna un riepilogo per il Log (03.1.7).

    Non solleva mai: un'eccezione qui non deve mai fermare il run (15.1.4).
    """
    riepilogo = {"source_id": fonte["source_id"], "artefatti": 0, "eventi_pubblicati": 0, "scartati_prefilter": 0, "errore": None}

    adapter = _ADAPTER_PER_TIER.get(fonte["metodo"])
    if adapter is None:
        riepilogo["errore"] = f"metodo sconosciuto: {fonte['metodo']}"
        return riepilogo

    try:
        artefatti = adapter.fetch(fonte)
    except Exception as exc:  # isolamento totale (15.1 regola 4, 08.4)
        logger.warning("Fonte %s fallita: %s", fonte["source_id"], exc)
        riepilogo["errore"] = str(exc)
        return riepilogo

    riepilogo["artefatti"] = len(artefatti)

    for art in artefatti:
        # I soli T0 con campi già strutturati (ical/jsonld) bypassano il pre-filtro
        # testuale sul titolo: non c'è nulla da scartare, l'evento è già certo.
        if art.titolo and art.data_inizio:
            evento = _costruisci_evento_da_artefatto(art, fonte, conn)
            if evento:
                upsert_evento(conn, evento, source_id=fonte["source_id"])
                riepilogo["eventi_pubblicati"] += 1
            continue

        # T1 generico (html): il testo grezzo va pre-filtrato. Se passa,
        # aspetta l'estrattore LLM (M5) — qui non viene ancora pubblicato
        # come evento strutturato.
        scarta, motivo = scarta_testo(art.text or "", ha_immagine=bool(art.image_paths))
        if scarta:
            riepilogo["scartati_prefilter"] += 1
            continue
        # TODO(M5): passare art a extractor.client per ottenere titolo/data.

    return riepilogo


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
