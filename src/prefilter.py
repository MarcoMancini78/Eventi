"""M4 — Pre-filtro deterministico (12.10, M4). Componente critico: senza GPU
è l'unica difesa del budget LLM. Va scritto prima dell'estrattore, non dopo.

Regola guida: falso negativo (evento vero scartato) è un evento perso per
sempre; falso positivo (scarto mancato) costa solo una chiamata in più. Le
soglie qui sotto sono tarate per un alto richiamo, non per la massima
riduzione — vedi criterio di accettazione M4 (>=95% di richiamo).
"""
from __future__ import annotations

import re
from datetime import date

_PATTERN_DATA_NUMERICA = re.compile(r"\b\d{1,2}[/\-.]\d{1,2}(?:[/\-.]\d{2,4})?\b")
_PATTERN_MESE = re.compile(
    r"\b(gennaio|febbraio|marzo|aprile|maggio|giugno|luglio|agosto|"
    r"settembre|ottobre|novembre|dicembre)\b",
    re.IGNORECASE,
)
_PATTERN_GIORNO_SETTIMANA = re.compile(
    r"\b(luned[iì]|marted[iì]|mercoled[iì]|gioved[iì]|venerd[iì]|sabato|domenica)\b",
    re.IGNORECASE,
)
_PATTERN_RELATIVO = re.compile(
    r"\b(oggi|domani|dopodomani|stasera|stanotte|questo\s+weekend|"
    r"prossim[oa]\s+\w+|weekend)\b",
    re.IGNORECASE,
)

_PAROLE_CHIAVE_EVENTO = re.compile(
    r"\b(sagra|festa|fiera|mercatino|concerto|spettacolo|degustazione|"
    r"rassegna|mostra|cena|serata|proiezione|festival|manifestazione|"
    r"appuntamento|cartellone|inaugurazione)\b",
    re.IGNORECASE,
)

# 04.3, 12.10: post che sistematicamente non contengono eventi.
_PATTERN_NON_EVENTO = re.compile(
    r"\b(auguri|buon\s+natale|buona\s+pasqua|condoglianze|necrologio|"
    r"lutto|viabilità|ordinanza|comunicato\s+stampa|si\s+ringrazia|"
    r"ringraziamo|ringraziament[oi])\b",
    re.IGNORECASE,
)

_LUNGHEZZA_MINIMA_SENZA_IMMAGINE = 40

_PATTERN_ANNO = re.compile(r"\b(20\d{2})\b")


def _contiene_data_futura_o_recente(testo: str, oggi: date) -> bool:
    """Non è una lettura del calendario: è un segnale grezzo di presenza-data.

    L'interpretazione vera della data spetta all'LLM. Qui basta escludere il
    caso ovvio di un pattern numerico che è chiaramente nel passato remoto
    (es. un anno di 3+ anni fa), per scartare i resoconti storici senza
    rischiare falsi negativi su date ambigue.
    """
    for match in _PATTERN_ANNO.finditer(testo):
        anno = int(match.group(1))
        if anno < oggi.year - 1:  # anno passato non recente: quasi certo resoconto storico
            return False
    return True


def ha_segnale_di_evento_futuro(testo: str) -> bool:
    return bool(
        _PATTERN_DATA_NUMERICA.search(testo)
        or _PATTERN_MESE.search(testo)
        or _PATTERN_GIORNO_SETTIMANA.search(testo)
        or _PATTERN_RELATIVO.search(testo)
        or _PATTERN_ANNO.search(testo)
    )


def ha_parola_chiave_di_evento(testo: str) -> bool:
    return bool(_PAROLE_CHIAVE_EVENTO.search(testo))


def corrisponde_a_schema_non_evento(testo: str) -> bool:
    return bool(_PATTERN_NON_EVENTO.search(testo))


def scarta_testo(testo: str, ha_immagine: bool = False, oggi: date | None = None) -> tuple[bool, str]:
    """Ritorna (scarta, motivo). Se scarta=False, il testo passa all'LLM.

    Regole (12.10 "Sul testo"), applicate in ordine dalla più economica:
    - schema noto di non-evento -> scarta
    - nessun pattern di data E nessuna parola chiave -> scarta
    - solo pattern di data al passato -> scarta
    - lunghezza sotto soglia e nessuna immagine -> scarta
    """
    oggi = oggi or date.today()
    testo_pulito = (testo or "").strip()

    if corrisponde_a_schema_non_evento(testo_pulito):
        return True, "schema_non_evento"

    ha_data = ha_segnale_di_evento_futuro(testo_pulito)
    ha_parola_chiave = ha_parola_chiave_di_evento(testo_pulito)
    if not ha_data and not ha_parola_chiave and not ha_immagine:
        # Senza immagine, un testo privo di ogni segnale è quasi certamente
        # scarto. Con immagine potrebbe essere la sola caption di una
        # locandina (T3, 04.1): il giudizio spetta al pre-filtro grafico.
        return True, "nessun_segnale_di_evento"

    if ha_data and not _contiene_data_futura_o_recente(testo_pulito, oggi):
        return True, "solo_date_passate"

    if len(testo_pulito) < _LUNGHEZZA_MINIMA_SENZA_IMMAGINE and not ha_immagine:
        return True, "testo_troppo_corto_senza_immagine"

    return False, ""
