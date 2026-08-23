"""Bonifica dei link social ereditati dal vecchio workbook (13.4), per popolare CodaFollow.

Livello 1 — sintattico: scarta widget di condivisione, normalizza deep link,
marca ciò che va risolto (permalink di post, ID numerici, gruppi).
Livello 2 — coerenza di entità: se l'handle contiene il nome di un comune
diverso da quello assegnato, è un errore quasi certo -> scarto.
Livello 3 (manuale) non è automatizzabile qui: resta a carico della verifica
umana quando la fonte compare per la prima volta nel feed (14.4).
"""
from __future__ import annotations

import csv
import re
import sqlite3
import unicodedata
from dataclasses import dataclass
from pathlib import Path

from .perimetro import risolvi_comune

_PATTERN_SCARTO_L1 = re.compile(
    r"facebook\.com/(sharer|plugins|profile\.php|story\.php|dialog|login)"
    r"|twitter\.com/intent/"
    r"|notfound"
    r"|(https?://.*){2,}",  # più di un https:// nella stessa stringa: concatenazione
    re.IGNORECASE,
)

_PATTERN_DEEP_LINK_FACEBOOK = re.compile(
    r"^(https?://(?:www\.|m\.|it-it\.)?facebook\.com/([^/?#]+))/"
    r"(events|about|mentions|reels|photos|videos|posts|past_hosted_events)\b",
    re.IGNORECASE,
)
_PATTERN_DEEP_LINK_INSTAGRAM = re.compile(
    r"^(https?://(?:www\.)?instagram\.com/([^/?#]+))/(reels|tagged)\b", re.IGNORECASE
)
_PATTERN_POST_PERMALINK_IG = re.compile(r"instagram\.com/p/[\w-]+", re.IGNORECASE)
_PATTERN_PROFILO_NUMERICO_FB = re.compile(r"facebook\.com/(\d+)/?$")
_PATTERN_GRUPPO_FB = re.compile(r"facebook\.com/groups/", re.IGNORECASE)


def _normalizza_url(url: str) -> str:
    url = url.strip()
    url = re.sub(r"^https?://(www\.|m\.|it-it\.)?facebook\.com", "https://www.facebook.com", url, flags=re.I)
    url = re.sub(r"^https?://(www\.)?instagram\.com", "https://www.instagram.com", url, flags=re.I)

    m = _PATTERN_DEEP_LINK_FACEBOOK.match(url)
    if m:
        return m.group(1)
    m = _PATTERN_DEEP_LINK_INSTAGRAM.match(url)
    if m:
        return m.group(1)
    return url.rstrip("/")


def _normalizza_testo(testo: str) -> str:
    testo = unicodedata.normalize("NFKD", testo.lower())
    return "".join(c for c in testo if not unicodedata.combining(c))


_PATTERN_PROFILO_PEOPLE_FB = re.compile(r"facebook\.com/people/([^/?#]+)/(\d+)", re.I)


def _handle_da_url(url: str, piattaforma: str) -> str:
    if piattaforma == "facebook":
        # facebook.com/people/Nome-Leggibile/12345: il segmento utile è il
        # nome, non "people" (che il pattern generico sotto prenderebbe).
        m_people = _PATTERN_PROFILO_PEOPLE_FB.search(url)
        if m_people:
            return f"{m_people.group(1)}-{m_people.group(2)}"
        m = re.search(r"facebook\.com/([^/?#]+)", url, re.I)
    else:
        m = re.search(r"instagram\.com/([^/?#]+)", url, re.I)
    return m.group(1) if m else ""


@dataclass
class RigaBonificata:
    soggetto: str
    piattaforma: str  # 'facebook' | 'instagram'
    url: str
    handle: str
    comune: str
    stato: str  # 'ok' | 'quarantena' | 'scartato'
    motivo: str = ""


def bonifica_url(url: str, comune_assegnato: str, tutti_i_comuni: list[str]) -> RigaBonificata | None:
    """Livelli 1-2 di 13.4. Ritorna None se l'URL non è nemmeno un candidato."""
    if not url or not url.strip():
        return None

    if _PATTERN_SCARTO_L1.search(url):
        return None  # livello 1: widget di condivisione, concatenazione — scarto muto

    if _PATTERN_GRUPPO_FB.search(url):
        return RigaBonificata("", "facebook", url, "", comune_assegnato, "quarantena", "gruppo_facebook")

    if _PATTERN_POST_PERMALINK_IG.search(url):
        return RigaBonificata("", "instagram", url, "", comune_assegnato, "quarantena", "permalink_post_da_risolvere")

    m_num = _PATTERN_PROFILO_NUMERICO_FB.search(url)
    if m_num:
        return RigaBonificata("", "facebook", url, m_num.group(1), comune_assegnato, "quarantena", "id_numerico_da_risolvere")

    piattaforma = "facebook" if "facebook.com" in url.lower() else ("instagram" if "instagram.com" in url.lower() else None)
    if piattaforma is None:
        return None

    url_norm = _normalizza_url(url)
    handle = _handle_da_url(url_norm, piattaforma)
    if not handle:
        return None

    # Livello 2: coerenza di entità (13.4) — l'handle contiene il nome di un
    # comune diverso da quello assegnato che esiste nel perimetro?
    #
    # Due strategie di match, non una sola sottostringa grezza (troppo
    # incline ai falsi positivi su nomi annidati come "igliano" dentro
    # "vigliano" o "bormida" dentro "monasterobormida", che è oltretutto
    # parte legittima del nome del comune atteso):
    #
    # 1. Se l'handle ha separatori (trattini/underscore, tipico di handle
    #    "leggibili" come "Pro-loco-Garbagna-Al"), il match va cercato per
    #    TOKEN intero: intercetta il caso reale del doc 13.2 senza toccare
    #    parole compresse.
    # 2. Se l'handle è una parola unica senza separatori (es.
    #    "prolocoviglianodasti"), si richiede che il nome del comune sia
    #    prefisso o suffisso dell'handle compatto: i casi reali di handle
    #    scorretti seguono quasi sempre lo schema "prolocoNOMECOMUNE" o
    #    "NOMECOMUNEproloco", non un'infissione a metà stringa.
    token_handle = [t for t in re.split(r"[-_\s]+", _normalizza_testo(handle)) if t]
    handle_compatto = "".join(token_handle)
    comune_atteso_norm = _normalizza_testo(comune_assegnato)
    comune_atteso_compatto = comune_atteso_norm.replace(" ", "").replace("'", "")
    ha_separatori = bool(re.search(r"[-_]", handle))

    for altro_comune in tutti_i_comuni:
        altro_norm = _normalizza_testo(altro_comune)
        if altro_norm == comune_atteso_norm:
            continue
        altro_compatto = altro_norm.replace(" ", "").replace("'", "")
        if altro_compatto in comune_atteso_compatto:
            continue  # "altro" è già una sotto-sequenza del nome del comune atteso: non è un errore
        if len(altro_compatto) < 6 or comune_atteso_compatto in handle_compatto:
            continue

        token_altro = [t for t in altro_norm.split() if t]
        match_per_token = ha_separatori and all(t in token_handle for t in token_altro)
        match_per_affisso = handle_compatto.startswith(altro_compatto) or handle_compatto.endswith(altro_compatto)

        if match_per_token or match_per_affisso:
            return RigaBonificata(
                "", piattaforma, url_norm, handle, comune_assegnato, "quarantena",
                f"possibile_entita_sbagliata: handle contiene '{altro_comune}'",
            )

    return RigaBonificata("", piattaforma, url_norm, handle, comune_assegnato, "ok")


def importa_e_bonifica(
    comuni_csv: Path,
    proloco_csv: Path,
    social_csv: Path,
    conn: sqlite3.Connection,
) -> list[dict]:
    """Legge i tre CSV grezzi, applica la bonifica, filtra sul perimetro caricato in SQLite.

    Ritorna una lista di dict pronti per il foglio CodaFollow, ordinati per
    priorità (14.4): fascia crescente, poi categoria (festa/proloco > comune > altro).
    """
    tutti_i_comuni = [r["comune"] for r in conn.execute("SELECT comune FROM comuni WHERE attivo='si'").fetchall()]
    righe_finali: list[dict] = []

    def _fascia_e_dati_comune(nome_comune: str) -> sqlite3.Row | None:
        return risolvi_comune(nome_comune, conn)

    # Comuni: pagina Facebook istituzionale
    with open(comuni_csv, encoding="utf-8-sig", newline="") as f:
        for riga in csv.DictReader(f, delimiter=";"):
            comune_nome = riga.get("Comune", "").strip()
            comune_riga = _fascia_e_dati_comune(comune_nome)
            if comune_riga is None:
                continue  # fuori perimetro
            bonificata = bonifica_url(riga.get("Facebook", ""), comune_riga["comune"], tutti_i_comuni)
            if bonificata and bonificata.stato == "ok":
                righe_finali.append(_riga_coda_follow(
                    soggetto=f"Comune di {comune_riga['comune']}", categoria="comune",
                    comune_riga=comune_riga, bonificata=bonificata,
                ))

    # Pro Loco: Facebook e Instagram
    with open(proloco_csv, encoding="utf-8-sig", newline="") as f:
        for riga in csv.DictReader(f, delimiter=";"):
            comune_nome = riga.get("Comune", "").strip()
            comune_riga = _fascia_e_dati_comune(comune_nome)
            if comune_riga is None:
                continue
            denominazione = riga.get("Denominazione", "Pro Loco").strip() or "Pro Loco"
            for campo, piattaforma in (("Facebook", "facebook"), ("Instagram", "instagram")):
                bonificata = bonifica_url(riga.get(campo, ""), comune_riga["comune"], tutti_i_comuni)
                if bonificata and bonificata.stato == "ok":
                    righe_finali.append(_riga_coda_follow(
                        soggetto=f"{denominazione} {comune_riga['comune']}", categoria="proloco",
                        comune_riga=comune_riga, bonificata=bonificata,
                    ))

    # Social.csv: aggregatori/teatri già mappati a mano, nessun comune singolo
    # da verificare col livello 2 (spesso sovracomunali) — si accettano se
    # passano il livello 1.
    if social_csv.exists():
        with open(social_csv, encoding="utf-8-sig", newline="") as f:
            for riga in csv.DictReader(f, delimiter=";"):
                nome = riga.get("Nome", "").strip()
                for campo, piattaforma in (("Facebook", "facebook"), ("Instagram", "instagram")):
                    url = riga.get(campo, "")
                    if not url or _PATTERN_SCARTO_L1.search(url):
                        continue
                    url_norm = _normalizza_url(url)
                    handle = _handle_da_url(url_norm, piattaforma)
                    if not handle:
                        continue
                    righe_finali.append({
                        "source_id": f"aggregatore-{_normalizza_testo(nome).replace(' ', '-')}-{piattaforma}",
                        "piattaforma": piattaforma, "handle": handle, "url": url_norm,
                        "soggetto": nome, "comune": "", "fascia": "A",
                        "categoria": "aggregatore", "stato": "da_seguire",
                    })

    _ordina_per_priorita(righe_finali)
    return righe_finali


def _riga_coda_follow(soggetto: str, categoria: str, comune_riga: sqlite3.Row, bonificata: RigaBonificata) -> dict:
    source_id = f"{categoria}-{_normalizza_testo(comune_riga['comune']).replace(' ', '-')}-{bonificata.piattaforma}"
    return {
        "source_id": source_id,
        "piattaforma": bonificata.piattaforma,
        "handle": bonificata.handle,
        "url": bonificata.url,
        "soggetto": soggetto,
        "comune": comune_riga["comune"],
        "fascia": comune_riga["fascia"],
        "categoria": categoria,
        "stato": "da_seguire",
    }


_PESO_CATEGORIA = {"aggregatore": 15, "proloco": 15, "festa": 15, "comune": 10, "teatro": 8}
_PESO_FASCIA = {"A": 60, "B": 40, "C": 20}


def _ordina_per_priorita(righe: list[dict]) -> None:
    """14.4: priorita = (4-fascia)*20 + categoria_peso (qui senza polling_diretto,
    che è un flag manuale non ancora popolato per queste fonti nuove)."""
    def punteggio(r: dict) -> int:
        return _PESO_FASCIA.get(r["fascia"], 0) + _PESO_CATEGORIA.get(r["categoria"], 3)

    righe.sort(key=punteggio, reverse=True)
