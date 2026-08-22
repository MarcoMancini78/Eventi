"""Criterio di accettazione M0 (15-guida-implementazione.md), eseguito contro Sheets reali.

Non è un test automatico da CI (tocca la rete e un workbook reale): è uno
script manuale da lanciare una tantum per certificare M0.

  python tests/manual_m0_acceptance.py

Verifica:
1. Scrittura di 500 righe finte in `Eventi` in meno di 10 secondi.
2. Modifica manuale della colonna `note` su una riga, rilancio della
   pubblicazione, e sopravvivenza della modifica.
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.config import load_config
from src.publisher import COLONNE_EVENTI, pubblica_eventi
from src.sheets_client import get_client


def genera_righe_finte(n: int) -> list[dict]:
    righe = []
    for i in range(n):
        righe.append(
            {
                "id": f"test{i:04d}",
                "titolo": f"Evento di prova {i}",
                "descrizione": "Riga generata dal test di accettazione M0",
                "tipologia": "altro",
                "data_inizio": "2026-09-01",
                "ora_inizio": "21:00",
                "data_fine": "2026-09-01",
                "ora_fine": "",
                "serie_id": "",
                "occorrenza": "",
                "comune": "Calosso",
                "luogo": "Piazza di prova",
                "km": 0,
                "minuti": 0,
                "prezzo": "",
                "organizzatore": "",
                "url": "",
                "url_immagine": "",
                "fonti": "test",
                "confidenza": 90,
                "stato": "nuovo",
                "note": "",
                "primo_visto": "2026-08-22",
                "ultimo_visto": "2026-08-22",
                "bloccato": "no",
                "soppressa": "no",
            }
        )
    return righe


def main() -> None:
    config = load_config()
    client = get_client(config)
    sh = client.open_by_key(config.spreadsheet_id_principale)
    ws = sh.worksheet("Eventi")

    print("Passo 1: scrittura di 500 righe finte...")
    righe = genera_righe_finte(500)
    inizio = time.monotonic()
    pubblica_eventi(ws, righe)
    durata = time.monotonic() - inizio
    print(f"  Completato in {durata:.1f} secondi ({'OK' if durata < 10 else 'FUORI SOGLIA (attesa < 10s)'})")

    print("Passo 2: modifica manuale della colonna 'note' sulla riga test0007...")
    valori = ws.get_all_values()
    intestazione = valori[0]
    idx_id = intestazione.index("id")
    idx_note = intestazione.index("note")
    riga_target = next(i for i, r in enumerate(valori) if len(r) > idx_id and r[idx_id] == "test0007")
    ws.update_cell(riga_target + 1, idx_note + 1, "NOTA SCRITTA A MANO - non deve sparire")
    print("  Nota scritta manualmente su test0007.")

    print("Passo 3: rilancio della pubblicazione con gli stessi dati calcolati...")
    pubblica_eventi(ws, righe)

    print("Passo 4: verifica che la nota sia sopravvissuta...")
    valori_dopo = ws.get_all_records()
    riga_dopo = next(r for r in valori_dopo if r.get("id") == "test0007")
    nota_sopravvissuta = riga_dopo.get("note") == "NOTA SCRITTA A MANO - non deve sparire"

    print(f"  Nota attuale: {riga_dopo.get('note')!r}")
    print(f"  Esito: {'PASS' if nota_sopravvissuta else 'FAIL - la modifica manuale è andata persa'}")

    if not nota_sopravvissuta:
        sys.exit(1)


if __name__ == "__main__":
    main()
