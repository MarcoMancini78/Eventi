"""Adattatore per famiglia di piattaforma (12.5, L3): template AGID
"pa_design_system" nella variante legacy senza JSON-LD (endpoint tipo
.../Eventi, distinto dalla variante ComWeb/ePublic già coperta da
adapters/jsonld.py con endpoint .../vivere-il-comune/eventi).

Trovato ispezionando dal vivo un campione di 6 comuni classificati
`pa_design_system` da fingerprint.py (17-lavoro-residuo.md, 2026-09-01):
struttura HTML identica su comuni di province diverse (AT, CN, VC, TO,
AL) — un `.card-wrapper` per evento, categoria in un link `?idCat=N`,
data nel formato "GG/MM/AAAA - GG/MM/AAAA" in `.category-top .data`,
titolo in `.card-title`, sintesi in `.text-paragraph-card`.

Seconda variante (2026-09-14, comuni classificati `wordpress` dal
fingerprinting — nessuno dei 91 espone un endpoint REST eventi utile,
verificato su un campione di 15, ma 56/91 usano di fatto la STESSA
famiglia di template Bootstrap Italia, solo con markup leggermente
diverso): data testuale italiana in `.card-calendar .card-day`
("20 Maggio 2000" o "11 Giugno 2026 - 1 Novembre 2026", non
"GG/MM/AAAA"), titolo in `.cmp-list-card-img__body-title` invece di
`.card-title`. Un solo parser prova prima il formato Dettaglionews
esistente, poi questo come fallback — nessun secondo adattatore, la
struttura a card-wrapper è la stessa.

T0 puro: nessuna chiamata LLM, gli stessi campi che l'estrattore
avrebbe dovuto dedurre da un HTML generico sono già qui, strutturati.

Audit del parser (2026-09-17, dopo il caso Acqui Terme) ha trovato altre
varianti sulla stessa famiglia di card-wrapper, aggiunte in questo giro:
- `.card-text` col formato "GG mese AAAA - GG mese AAAA" (Cuneo).
- Doppio `.card-day` sulla stessa card, uno col mese uno con l'anno
  (Collegno) — _con_classe ritorna una lista, il vecchio codice leggeva
  solo il primo elemento.
- `.card-date`/`.card-day` SENZA alcun anno da nessuna parte nella card
  (Carcare, Tiglieto, Pozzolo Formigaro, Albissola Marina): l'anno va
  dedotto (stessa regola già usata dal prompt LLM per le date senza anno
  esplicito) o preso dal titolo se il comune lo scrive lì esplicitamente.
  Attenzione al caso Tiglieto: su alcune pagine questo box non è affatto
  la data dell'evento ma quella di PUBBLICAZIONE della notizia — rilevato
  quando tutte le card della pagina condividono la stessa data odierna
  (vedi `_pagina_usa_data_pubblicazione_non_evento`).
- Ottava variante (Desana): `.data` con mese ABBREVIATO a 3 lettere
  ("25 giu 2026", non "25 Giugno 2026"), titolo in un `<h3>` semplice
  senza classe dedicata (né `.card-title` né
  `.cmp-list-card-img__body-title`).
"""
from __future__ import annotations

import hashlib
import re
from datetime import date

import httpx
import lxml.html

from .base import Adapter, Artefatto

_TIMEOUT_SECONDI = 15
_USER_AGENT_BROWSER = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)

_PATTERN_DATA = re.compile(r"(\d{2})/(\d{2})/(\d{4})\s*(?:-\s*(\d{2})/(\d{2})/(\d{4}))?")

_MESI_ITALIANI = {
    "gennaio": 1, "febbraio": 2, "marzo": 3, "aprile": 4, "maggio": 5, "giugno": 6,
    "luglio": 7, "agosto": 8, "settembre": 9, "ottobre": 10, "novembre": 11, "dicembre": 12,
}
# "20 Maggio 2000" o "11 Giugno 2026 - 1 Novembre 2026" (variante wordpress,
# .card-calendar .card-day): giorno 1-2 cifre, non zero-paddato come nel
# formato GG/MM/AAAA della variante Dettaglionews.
_PATTERN_DATA_TESTUALE = re.compile(
    r"(\d{1,2})\s+(" + "|".join(_MESI_ITALIANI) + r")\s+(\d{4})"
    r"(?:\s*-\s*(\d{1,2})\s+(" + "|".join(_MESI_ITALIANI) + r")\s+(\d{4}))?",
    re.IGNORECASE,
)

# "16 Settembre" senza anno (quinta variante, 2026-09-17: comuni tipo
# Carcare, Tiglieto, Pozzolo Formigaro, Albissola Marina — .card-calendar
# .card-date/.card-day non riportano mai l'anno). Stesso pattern di
# _PATTERN_DATA_TESTUALE ma senza il gruppo anno, per la sola coppia
# giorno+mese che serve a dedurlo con _anno_piu_vicino_nel_futuro.
_PATTERN_GIORNO_MESE_SENZA_ANNO = re.compile(
    r"^\s*(\d{1,2})\s+(" + "|".join(_MESI_ITALIANI) + r")\s*$", re.IGNORECASE
)

# "25 giu 2026" (ottava variante, 2026-09-17, comune-desana): mese
# abbreviato a 3 lettere, non per esteso come _PATTERN_DATA_TESTUALE.
# Le forme "mag"/"giu"/"lug"/"ago"/"set"/"ott"/"nov"/"dic" coincidono con
# le prime 3 lettere del nome per esteso; "gen"/"feb"/"mar"/"apr" idem.
_MESI_ITALIANI_ABBREVIATI = {nome[:3]: numero for nome, numero in _MESI_ITALIANI.items()}
_PATTERN_DATA_MESE_ABBREVIATO = re.compile(
    r"(\d{1,2})\s+(" + "|".join(_MESI_ITALIANI_ABBREVIATI) + r")\.?\s+(\d{4})"
    r"(?:\s*-\s*(\d{1,2})\s+(" + "|".join(_MESI_ITALIANI_ABBREVIATI) + r")\.?\s+(\d{4}))?",
    re.IGNORECASE,
)


def _converti_data(gg: str, mm: str, aaaa: str) -> str:
    return f"{aaaa}-{mm}-{gg}"


def _estrai_date(testo_data: str) -> tuple[str | None, str | None]:
    """'12/08/2026 - 12/08/2026' -> ('2026-08-12', '2026-08-12'). Anche il
    solo giorno singolo, senza intervallo, è nel formato del sito reale."""
    m = _PATTERN_DATA.search(testo_data or "")
    if not m:
        return None, None
    gg1, mm1, aaaa1, gg2, mm2, aaaa2 = m.groups()
    inizio = _converti_data(gg1, mm1, aaaa1)
    fine = _converti_data(gg2, mm2, aaaa2) if gg2 else inizio
    return inizio, fine


def _estrai_date_testuale(testo_data: str) -> tuple[str | None, str | None]:
    """'20 Maggio 2000' -> ('2000-05-20', '2000-05-20').
    '11 Giugno 2026 - 1 Novembre 2026' -> ('2026-06-11', '2026-11-01')."""
    m = _PATTERN_DATA_TESTUALE.search(testo_data or "")
    if not m:
        return None, None
    gg1, mese1, aaaa1, gg2, mese2, aaaa2 = m.groups()
    mm1 = _MESI_ITALIANI[mese1.lower()]
    inizio = f"{aaaa1}-{mm1:02d}-{int(gg1):02d}"
    if gg2:
        mm2 = _MESI_ITALIANI[mese2.lower()]
        fine = f"{aaaa2}-{mm2:02d}-{int(gg2):02d}"
    else:
        fine = inizio
    return inizio, fine


def _estrai_date_mese_abbreviato(testo_data: str) -> tuple[str | None, str | None]:
    """'25 giu 2026' -> ('2026-06-25', '2026-06-25') (ottava variante,
    comune-desana): mese abbreviato a 3 lettere, non per esteso."""
    m = _PATTERN_DATA_MESE_ABBREVIATO.search(testo_data or "")
    if not m:
        return None, None
    gg1, mese1, aaaa1, gg2, mese2, aaaa2 = m.groups()
    mm1 = _MESI_ITALIANI_ABBREVIATI[mese1.lower()]
    inizio = f"{aaaa1}-{mm1:02d}-{int(gg1):02d}"
    if gg2:
        mm2 = _MESI_ITALIANI_ABBREVIATI[mese2.lower()]
        fine = f"{aaaa2}-{mm2:02d}-{int(gg2):02d}"
    else:
        fine = inizio
    return inizio, fine


def _anno_piu_vicino_nel_futuro(giorno: int, mese: int, oggi: date | None = None) -> int:
    """Stessa regola già usata dal prompt dell'estrattore LLM per le date
    senza anno esplicito (src/extractor/prompts/testo_v1.py: 'assumi il
    prossimo anno in cui quella data cade nel futuro') — qui applicata nel
    parser T0 puro, che non passa mai dall'LLM."""
    oggi = oggi or date.today()
    anno = oggi.year
    try:
        candidata = date(anno, mese, giorno)
    except ValueError:
        return anno  # 29 febbraio ecc. su anno non bisestile: lascia l'anno corrente, 04.7
    return anno if candidata >= oggi else anno + 1


_PATTERN_ANNO_NEL_TESTO = re.compile(r"\b(20\d{2})\b")


def _anno_dal_titolo(titolo: str) -> int | None:
    """Cerca un anno a 4 cifre nel titolo/testo della card (caso reale
    2026-09-17, Carcare: 'Antica Fiera del Bestiame dal 28 Agosto al 1°
    Settembre 2026' — il comune scrive l'anno nel titolo proprio perché il
    box calendario non lo riporta). Un anno esplicito scritto dalla fonte
    stessa è sempre più affidabile di una deduzione "prossimo futuro", che
    romperebbe un evento come questo: 28 agosto è già passato rispetto a
    metà settembre, la deduzione lo spingerebbe all'anno dopo pur avendo
    il titolo che dice esplicitamente 2026."""
    m = _PATTERN_ANNO_NEL_TESTO.search(titolo or "")
    return int(m.group(1)) if m else None


def _estrai_giorno_mese_senza_anno(
    testo: str, anno_esplicito: int | None = None, oggi: date | None = None
) -> tuple[str | None, str | None]:
    """'16 Settembre' -> ('2026-09-16', '2026-09-16'). Usa `anno_esplicito`
    se fornito (trovato altrove nella card, es. nel titolo — vedi
    _anno_dal_titolo), altrimenti deduce con _anno_piu_vicino_nel_futuro.
    Nessun intervallo qui: le card di questa variante (2026-09-17: Carcare,
    Tiglieto, Pozzolo Formigaro, Albissola Marina) mostrano sempre e solo
    un giorno singolo in calendario, mai un range — coerente coi dati
    reali ispezionati."""
    m = _PATTERN_GIORNO_MESE_SENZA_ANNO.match((testo or "").strip())
    if not m:
        return None, None
    giorno, mese_nome = m.groups()
    mese = _MESI_ITALIANI[mese_nome.lower()]
    anno = anno_esplicito if anno_esplicito is not None else _anno_piu_vicino_nel_futuro(int(giorno), mese, oggi)
    data_iso = f"{anno}-{mese:02d}-{int(giorno):02d}"
    return data_iso, data_iso


def _con_classe(nodo, classe: str):
    """Equivalente di getElementsByClassName tramite XPath (contains su
    class con spazi ai bordi, per non matchare 'card-title-x' quando si
    cerca 'card-title'). Il pacchetto 'cssselect' non è tra le dipendenze
    del progetto — XPath nativo di lxml basta e non ne aggiunge una nuova.
    'descendant-or-self::' invece di '//' (solo discendenti): un frammento
    HTML minimale (es. un test, o un albero costruito da un solo elemento)
    fa diventare quell'elemento stesso la radice — '//' lo salterebbe."""
    return nodo.xpath(f'descendant-or-self::*[contains(concat(" ", normalize-space(@class), " "), " {classe} ")]')


def _pagina_usa_data_pubblicazione_non_evento(cards: list, oggi: date | None = None) -> bool:
    """Bug reale trovato (2026-09-17, caso Tiglieto): su alcune pagine
    '.card-date'/'.card-day' (quinta variante, senza anno) non sono affatto
    la data dell'evento, ma la data di PUBBLICAZIONE della notizia — lì
    ogni singola card della pagina mostra la stessa identica data odierna
    (il giorno del fetch), un pattern impossibile per un vero calendario
    eventi (che varia naturalmente). Se TUTTE le coppie giorno/mese trovate
    coincidono con oggi ed è più di una, l'intera pagina va trattata come
    priva di questo segnale — 04.7: meglio nessuna data che una inventata
    sistematicamente sbagliata."""
    oggi = oggi or date.today()
    coppie_trovate: list[tuple[int, str]] = []
    for card in cards:
        giorno_el = _con_classe(card, "card-date")
        mese_el = _con_classe(card, "card-day")
        if not giorno_el or not mese_el:
            continue
        testo_giorno = giorno_el[0].text_content().strip()
        testo_mese = mese_el[0].text_content().strip().lower()
        if testo_giorno.isdigit() and testo_mese in _MESI_ITALIANI:
            coppie_trovate.append((int(testo_giorno), testo_mese))

    # Una sola card non è un segnale sufficiente (potrebbe davvero essere
    # l'unico evento di oggi): serve più di una card, e tutte con la STESSA
    # coppia giorno/mese (set di un solo elemento su un elenco di 2+).
    if len(coppie_trovate) < 2 or len(set(coppie_trovate)) != 1:
        return False
    giorno_unico, mese_unico = coppie_trovate[0]
    return giorno_unico == oggi.day and _MESI_ITALIANI[mese_unico] == oggi.month


def parse_pa_design_system(html: str, source_id: str, fetch_url: str, oggi: date | None = None) -> list[Artefatto]:
    try:
        albero = lxml.html.fromstring(html)
    except Exception:
        return []

    cards = _con_classe(albero, "card-wrapper")
    data_pubblicazione_non_evento = _pagina_usa_data_pubblicazione_non_evento(cards, oggi)

    artefatti: list[Artefatto] = []
    for card in cards:
        # Titolo: '.card-title' (variante Dettaglionews) o
        # '.cmp-list-card-img__body-title' (variante wordpress/card-calendar,
        # 2026-09-14) — mai entrambe sullo stesso evento, provate in ordine.
        # Fallback su un <h3> generico SENZA classe dedicata (ottava
        # variante, 2026-09-17, comune-desana) solo come ultima risorsa:
        # meno specifico, ma il widget "feedback pagina" che questo
        # fallback rischierebbe di matchare usa sempre <h2>, mai <h3>
        # (verificato sul caso reale che ha originato quel filtro).
        titolo_el = (
            _con_classe(card, "card-title")
            or _con_classe(card, "cmp-list-card-img__body-title")
            or card.xpath(".//h3")
        )
        if not titolo_el:
            continue  # non tutti i .card-wrapper sono un evento (es. widget feedback pagina)
        titolo = titolo_el[0].text_content().strip()
        if not titolo:
            continue

        # Data: '.category-top .data' può contenere il formato GG/MM/AAAA
        # (variante Dettaglionews classica) OPPURE un formato testuale con
        # giorno della settimana davanti, es. "Martedì, 08 Settembre 2026"
        # (caso reale trovato 2026-09-17: sezione "Notizie" di Acqui Terme,
        # stesso template ma popolata con notizie/eventi invece che con la
        # sezione "Eventi" dedicata, che lì risulta vuota). Prima di
        # rinunciare su questo campo, provano ENTRAMBI i pattern sullo
        # stesso testo — bug precedente: si tentava solo quello numerico e,
        # fallito, si passava subito a '.card-day', che qui contiene solo
        # l'abbreviazione del mese ("set", non "Settembre 2026"), scartando
        # la card interamente pur avendo una data perfettamente leggibile.
        data_el = _con_classe(card, "data")
        testo_data_el = data_el[0].text_content() if data_el else ""
        data_inizio, data_fine = _estrai_date(testo_data_el)
        if not data_inizio:
            data_inizio, data_fine = _estrai_date_testuale(testo_data_el)
        if not data_inizio:
            # "25 giu 2026", mese abbreviato (ottava variante, 2026-09-17,
            # comune-desana) — ancora sullo stesso campo '.data'.
            data_inizio, data_fine = _estrai_date_mese_abbreviato(testo_data_el)
        if not data_inizio:
            # '.card-calendar .card-day' con formato testuale italiano
            # "20 Maggio 2000" (variante wordpress, 2026-09-14). Bug reale
            # (2026-09-17, caso Collegno): alcune card hanno DUE elementi
            # '.card-day' — uno col mese, uno con l'anno ("Novembre",
            # "2026") — e il vecchio codice leggeva solo il primo
            # (_con_classe ritorna una lista, [0] scartava l'anno). Uniti i
            # testi di tutti i '.card-day' trovati, non solo il primo.
            calendario_el = _con_classe(card, "card-day")
            testo_calendario = " ".join(e.text_content().strip() for e in calendario_el)
            data_inizio, data_fine = _estrai_date_testuale(testo_calendario)
        if not data_inizio:
            # '.card-text' col formato "GG mese AAAA - GG mese AAAA"
            # (2026-09-17, caso Cuneo: stessa famiglia di template, ma la
            # data vive in un terzo campo mai controllato finora).
            testo_el = _con_classe(card, "card-text")
            data_inizio, data_fine = _estrai_date_testuale(testo_el[0].text_content() if testo_el else "")
        if not data_inizio and not data_pubblicazione_non_evento:
            # Quinta variante (2026-09-17: Carcare, Tiglieto, Pozzolo
            # Formigaro, Albissola Marina) — '.card-date' (giorno) e
            # '.card-day' (mese) SENZA alcun anno da nessuna parte nel box
            # calendario: l'anno va dedotto O, se il comune lo scrive nel
            # titolo (caso reale Carcare: "...dal 28 Agosto al 1° Settembre
            # 2026"), preso da lì — un anno esplicito scritto dalla fonte
            # batte sempre una deduzione "prossimo futuro" (che qui avrebbe
            # sbagliato: 28 agosto già passato a metà settembre avrebbe
            # dedotto l'anno dopo, mentre il titolo dice chiaramente 2026).
            # Disattivato del tutto (data_pubblicazione_non_evento) quando
            # TUTTE le card della pagina condividono la stessa data odierna
            # — segnale che qui '.card-date'/'.card-day' sono la data di
            # pubblicazione della notizia, non dell'evento (caso Tiglieto).
            giorno_el = _con_classe(card, "card-date")
            mese_el = _con_classe(card, "card-day")
            if giorno_el and mese_el:
                testo_giorno_mese = f"{giorno_el[0].text_content().strip()} {mese_el[0].text_content().strip()}"
                anno_esplicito = _anno_dal_titolo(titolo)
                data_inizio, data_fine = _estrai_giorno_mese_senza_anno(testo_giorno_mese, anno_esplicito)
        if not data_inizio:
            continue  # 04.7: senza data non è un evento pubblicabile, non se ne indovina una

        descrizione_el = _con_classe(card, "text-paragraph-card") or _con_classe(card, "cmp-list-card-img__body-description")
        descrizione = descrizione_el[0].text_content().strip() if descrizione_el else None

        # Il link è nel genitore del titolo (variante Dettaglionews:
        # '<a><h3 class="card-title">...') o in un figlio (variante
        # wordpress/card-calendar: '<h3 class="cmp-list-card-img__body-title"><a>...'):
        # cercato prima tra i discendenti, poi risalendo i genitori.
        from urllib.parse import urljoin

        url_evento = fetch_url
        link_figlio = titolo_el[0].xpath(".//a[@href]")
        if link_figlio:
            url_evento = urljoin(fetch_url, link_figlio[0].get("href"))
        else:
            link_el = titolo_el[0].getparent()
            while link_el is not None:
                href = link_el.get("href")
                if href:
                    url_evento = urljoin(fetch_url, href)
                    break
                link_el = link_el.getparent()

        testo = f"{titolo}\n{descrizione or ''}".strip()
        artefatti.append(
            Artefatto(
                source_id=source_id,
                url=url_evento,
                kind="html",
                text=testo,
                titolo=titolo,
                data_inizio=data_inizio,
                data_fine=data_fine,
                descrizione=descrizione,
                raw_hash=hashlib.sha1(f"{titolo}|{data_inizio}".encode("utf-8")).hexdigest(),
            )
        )
    return artefatti


class PaDesignSystemAdapter(Adapter):
    def fetch(self, fonte: dict) -> list[Artefatto]:
        endpoint = fonte["endpoint"]
        with httpx.Client(timeout=_TIMEOUT_SECONDI, follow_redirects=True) as client:
            risposta = client.get(endpoint, headers={"User-Agent": fonte.get("user_agent", _USER_AGENT_BROWSER)})
            risposta.raise_for_status()
        return parse_pa_design_system(risposta.text, fonte["source_id"], endpoint)
