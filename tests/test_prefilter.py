"""M4: pre-filtro testuale. Criterio di accettazione: alto richiamo sugli eventi veri,
anche a costo di scartare meno scarto (12.10, M4 — un falso negativo è un evento perso per sempre)."""
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.prefilter import scarta_testo

OGGI = date(2026, 8, 22)

# Eventi veri: NESSUNO di questi deve essere scartato (richiamo >= 95%, M4).
EVENTI_VERI = [
    "Sabato 12 settembre 2026 dalle ore 19:00 Sagra del Tartufo in Piazza Roma.",
    "Domenica prossima mercatino dell'antiquariato in Via Garibaldi.",
    "Concerto della banda cittadina il 20/09 alle 21:00.",
    "Rassegna teatrale: tre spettacoli a ottobre, novembre e dicembre 2026.",
    "Degustazione di vini questo weekend in cantina.",
    "Stasera proiezione all'aperto del film in piazza.",
    "La festa patronale si terrà il 15 agosto, come da tradizione locale.",
]

# Scarti veri: post che NON devono generare una chiamata LLM.
NON_EVENTI = [
    "Buon Natale e felice anno nuovo a tutti i cittadini!",
    "Comunicato stampa: ordinanza di viabilità per lavori stradali.",
    "Si ringrazia la Pro Loco per l'organizzazione della scorsa edizione del 2019.",
    "Condoglianze alla famiglia per la recente perdita.",
    "Foto",
    "Bellissima giornata di sole oggi in paese.",
]


def test_richiamo_su_eventi_veri_almeno_95_percento():
    scartati_per_errore = [t for t in EVENTI_VERI if scarta_testo(t, oggi=OGGI)[0]]
    tasso_falsi_negativi = len(scartati_per_errore) / len(EVENTI_VERI)
    assert tasso_falsi_negativi <= 0.05, f"Scartati per errore: {scartati_per_errore}"


def test_non_eventi_vengono_scartati():
    non_scartati = [t for t in NON_EVENTI if not scarta_testo(t, oggi=OGGI)[0]]
    # Tollerabile qualche falso positivo (non scartato), il richiamo sugli
    # eventi veri conta più della precisione sullo scarto (12.10).
    assert len(non_scartati) <= 2, f"Non scartati: {non_scartati}"


def test_schema_auguri_scartato_col_motivo_giusto():
    scarta, motivo = scarta_testo("Buon Natale e felice anno nuovo a tutti!", oggi=OGGI)
    assert scarta is True
    assert motivo == "schema_non_evento"


def test_testo_breve_senza_immagine_scartato_ma_non_se_ha_immagine():
    scarta_senza_img, _ = scarta_testo("Foto", ha_immagine=False, oggi=OGGI)
    scarta_con_img, _ = scarta_testo("Foto", ha_immagine=True, oggi=OGGI)
    assert scarta_senza_img is True
    assert scarta_con_img is False  # potrebbe essere solo la caption di una locandina


def test_data_passata_di_anni_fa_scartata():
    scarta, motivo = scarta_testo("Grande festa del 2019, che serata indimenticabile!", oggi=OGGI)
    assert scarta is True
    assert motivo == "solo_date_passate"
