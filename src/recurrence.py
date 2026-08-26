"""M6 — Ricorrenze: campi strutturati -> RRULE -> occorrenze (07.9).

L'LLM non produce mai la RRULE: restituisce campi vincolati (frequenza,
giorno, ordinale, mesi inclusi/esclusi) e questo modulo li converte in modo
deterministico. Far generare una sintassi formale a un modello è una fonte
di errori silenziosi evitabile (07.9).
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta

from dateutil.rrule import rrule, rrulestr, MONTHLY, WEEKLY, MO, TU, WE, TH, FR, SA, SU

_GIORNO_SETTIMANA = {"MO": MO, "TU": TU, "WE": WE, "TH": TH, "FR": FR, "SA": SA, "SU": SU}
_FREQ = {"settimanale": WEEKLY, "mensile": MONTHLY}

# Bug reale osservato (2026-08-26): nonostante il prompt richieda i codici
# RFC5545 (MO/TU/.../SU), un'estrazione LLM ha restituito il nome italiano
# per esteso ("mercoledì"), facendo sollevare KeyError e fermare l'intero
# run multi-fonte (violazione di 15.1 regola 4: nessuna eccezione qui
# doveva mai poter propagarsi fino a interrompere le altre fonti). Difesa
# in profondità: non fidarsi ciecamente del formato anche dopo aver
# chiarito il prompt — normalizza le varianti più prevedibili (italiano,
# inglese, minuscolo) prima di validare.
_ALIAS_GIORNO_SETTIMANA = {
    "lunedì": "MO", "lunedi": "MO", "monday": "MO",
    "martedì": "TU", "martedi": "TU", "tuesday": "TU",
    "mercoledì": "WE", "mercoledi": "WE", "wednesday": "WE",
    "giovedì": "TH", "giovedi": "TH", "thursday": "TH",
    "venerdì": "FR", "venerdi": "FR", "friday": "FR",
    "sabato": "SA", "saturday": "SA",
    "domenica": "SU", "sunday": "SU",
}


def normalizza_giorno_settimana(valore: str) -> str | None:
    """Converte un giorno in codice RFC5545 (MO/TU/.../SU). Ritorna None se
    non riconosciuto, invece di sollevare — il chiamante deve poterlo
    scartare senza far fallire l'intera estrazione (15.1 regola 4)."""
    codice = (valore or "").strip().upper()
    if codice in _GIORNO_SETTIMANA:
        return codice
    return _ALIAS_GIORNO_SETTIMANA.get((valore or "").strip().lower())


@dataclass
class RegolaRicorrenza:
    frequenza: str  # 'settimanale' | 'mensile'
    giorni_settimana: list[str]  # es. ['SU'], o più giorni per 'terzo weekend'
    ordinale: int | None  # 1..4 per prima/seconda/terza/quarta, -1 per ultima
    mesi_inclusi: list[int]
    valida_dal: str
    valida_al: str | None = None


def costruisci_rrule(regola: RegolaRicorrenza) -> str:
    """Costruisce la stringa RRULE (RFC 5545) dai campi strutturati (07.9)."""
    if regola.frequenza not in _FREQ:
        raise ValueError(f"Frequenza non supportata: {regola.frequenza}")

    freq_rfc5545 = "MONTHLY" if regola.frequenza == "mensile" else "WEEKLY"
    parti = [f"FREQ={freq_rfc5545}"]

    giorni = []
    for g in regola.giorni_settimana:
        prefisso = str(regola.ordinale) if (regola.frequenza == "mensile" and regola.ordinale) else ""
        giorni.append(f"{prefisso}{g}")
    if giorni:
        parti.append(f"BYDAY={','.join(giorni)}")

    if regola.mesi_inclusi and len(regola.mesi_inclusi) < 12:
        parti.append(f"BYMONTH={','.join(str(m) for m in sorted(regola.mesi_inclusi))}")

    if regola.valida_al:
        until = regola.valida_al.replace("-", "")
        parti.append(f"UNTIL={until}")

    return ";".join(parti)


def regola_leggibile(regola: RegolaRicorrenza) -> str:
    """Testo umano accanto alla RRULE, per non dover decifrare 'BYDAY=1SU' a occhio (03.1.3b)."""
    NOMI_GIORNO_IT = {
        "MO": "lunedì", "TU": "martedì", "WE": "mercoledì", "TH": "giovedì",
        "FR": "venerdì", "SA": "sabato", "SU": "domenica",
    }
    NOMI_ORDINALE = {1: "prima", 2: "seconda", 3: "terza", 4: "quarta", -1: "ultima"}
    NOMI_MESE = {
        1: "gennaio", 2: "febbraio", 3: "marzo", 4: "aprile", 5: "maggio", 6: "giugno",
        7: "luglio", 8: "agosto", 9: "settembre", 10: "ottobre", 11: "novembre", 12: "dicembre",
    }

    giorni_it = " e ".join(NOMI_GIORNO_IT[g] for g in regola.giorni_settimana)

    if regola.frequenza == "mensile" and regola.ordinale:
        testo = f"{NOMI_ORDINALE.get(regola.ordinale, regola.ordinale)} {giorni_it} del mese"
    elif regola.frequenza == "settimanale":
        testo = f"ogni {giorni_it}"
    else:
        testo = f"{regola.frequenza}, {giorni_it}"

    if regola.mesi_inclusi and len(regola.mesi_inclusi) < 12:
        mesi_esclusi = sorted(set(range(1, 13)) - set(regola.mesi_inclusi))
        if len(mesi_esclusi) <= 2:
            testo += f", escluso {' e '.join(NOMI_MESE[m] for m in mesi_esclusi)}"
        else:
            testo += f", solo {', '.join(NOMI_MESE[m] for m in sorted(regola.mesi_inclusi))}"

    return testo


def espandi_occorrenze(
    rrule_str: str,
    valida_dal: str,
    eccezioni: list[str],
    orizzonte_giorni: int,
    oggi: date | None = None,
) -> list[str]:
    """Genera le date ISO delle occorrenze entro l'orizzonte scorrevole (07.9).

    L'orizzonte è tassativo: senza limite "prima domenica del mese" genera
    righe all'infinito. Le eccezioni (date da non generare, 07.9) sono
    rimosse dopo l'espansione, non incorporate nella RRULE.
    """
    oggi = oggi or date.today()
    inizio = datetime.combine(oggi, datetime.min.time())
    fine = inizio + timedelta(days=orizzonte_giorni)
    dtstart = datetime.fromisoformat(valida_dal)

    regola = rrulestr(rrule_str, dtstart=dtstart)
    occorrenze = regola.between(max(inizio, dtstart), fine, inc=True)

    eccezioni_set = set(eccezioni)
    return [d.date().isoformat() for d in occorrenze if d.date().isoformat() not in eccezioni_set]


def stato_decadimento(ultima_conferma: str, oggi: date | None = None) -> str:
    """attiva / da_verificare / sospesa, in base ai giorni da ultima_conferma (07.9).

    < 120 giorni -> attiva; 120-400 -> da_verificare (confidenza -25);
    > 400 -> sospesa, l'espansore smette di generare occorrenze.
    """
    oggi = oggi or date.today()
    giorni = (oggi - date.fromisoformat(ultima_conferma)).days
    if giorni < 120:
        return "attiva"
    if giorni <= 400:
        return "da_verificare"
    return "sospesa"
