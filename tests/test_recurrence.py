"""M6: criterio di accettazione da 15-guida-implementazione.md.

'mercatino la prima domenica del mese, escluso agosto' genera le date
corrette saltando agosto; un'occorrenza soppressa non torna dopo un
riespansione; RRULE e regola_leggibile restano coerenti (03.1.3b, 07.9).
"""
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.recurrence import (
    RegolaRicorrenza,
    costruisci_rrule,
    espandi_occorrenze,
    regola_leggibile,
    stato_decadimento,
)


def test_prima_domenica_del_mese_escluso_agosto():
    regola = RegolaRicorrenza(
        frequenza="mensile",
        giorni_settimana=["SU"],
        ordinale=1,
        mesi_inclusi=[1, 2, 3, 4, 5, 6, 7, 9, 10, 11, 12],
        valida_dal="2026-01-01",
    )
    rrule_str = costruisci_rrule(regola)
    assert rrule_str == "FREQ=MONTHLY;BYDAY=1SU;BYMONTH=1,2,3,4,5,6,7,9,10,11,12"

    occorrenze = espandi_occorrenze(
        rrule_str, valida_dal="2026-01-01", eccezioni=[], orizzonte_giorni=365, oggi=date(2026, 6, 1)
    )

    mesi_generati = {int(d.split("-")[1]) for d in occorrenze}
    assert 8 not in mesi_generati  # agosto escluso

    # ogni occorrenza deve cadere davvero di domenica
    for iso in occorrenze:
        assert date.fromisoformat(iso).weekday() == 6  # 6 = domenica


def test_ultimo_sabato_del_mese():
    regola = RegolaRicorrenza(
        frequenza="mensile", giorni_settimana=["SA"], ordinale=-1,
        mesi_inclusi=list(range(1, 13)), valida_dal="2026-01-01",
    )
    # Tutti i 12 mesi inclusi -> BYMONTH omesso (tabella di riferimento 07.9)
    assert costruisci_rrule(regola) == "FREQ=MONTHLY;BYDAY=-1SA"


def test_occorrenza_soppressa_non_torna_dopo_riespansione():
    regola = RegolaRicorrenza(
        frequenza="mensile", giorni_settimana=["SU"], ordinale=1,
        mesi_inclusi=list(range(1, 13)), valida_dal="2026-01-01",
    )
    rrule_str = costruisci_rrule(regola)

    prima_occ = espandi_occorrenze(rrule_str, "2026-01-01", eccezioni=[], orizzonte_giorni=120, oggi=date(2026, 8, 1))
    assert "2026-09-06" in prima_occ  # prima domenica di settembre 2026

    # L'utente sopprime l'occorrenza di settembre: va in eccezioni.
    dopo_soppressione = espandi_occorrenze(
        rrule_str, "2026-01-01", eccezioni=["2026-09-06"], orizzonte_giorni=120, oggi=date(2026, 8, 1)
    )
    assert "2026-09-06" not in dopo_soppressione


def test_orizzonte_non_genera_oltre_il_limite():
    regola = RegolaRicorrenza(
        frequenza="mensile", giorni_settimana=["SU"], ordinale=1,
        mesi_inclusi=list(range(1, 13)), valida_dal="2020-01-01",
    )
    rrule_str = costruisci_rrule(regola)
    occorrenze = espandi_occorrenze(rrule_str, "2020-01-01", eccezioni=[], orizzonte_giorni=120, oggi=date(2026, 1, 1))

    for iso in occorrenze:
        assert (date.fromisoformat(iso) - date(2026, 1, 1)).days <= 120


def test_regola_leggibile_prima_domenica_escluso_agosto():
    regola = RegolaRicorrenza(
        frequenza="mensile", giorni_settimana=["SU"], ordinale=1,
        mesi_inclusi=[1, 2, 3, 4, 5, 6, 7, 9, 10, 11, 12], valida_dal="2026-01-01",
    )
    testo = regola_leggibile(regola)
    assert "prima domenica" in testo
    assert "agosto" in testo


def test_stato_decadimento_soglie():
    oggi = date(2026, 8, 22)
    assert stato_decadimento("2026-08-01", oggi) == "attiva"  # 21 giorni fa
    assert stato_decadimento("2026-01-01", oggi) == "da_verificare"  # ~230 giorni fa
    assert stato_decadimento("2024-01-01", oggi) == "sospesa"  # oltre 400 giorni
