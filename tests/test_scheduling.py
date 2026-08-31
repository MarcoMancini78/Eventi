"""Coda a priorità dinamica (M11, 08.3). Formula presa dalla documentazione,
non indovinata — ogni test verifica un termine specifico in isolamento."""
import sqlite3
import sys
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src import scheduling, store


def _conn_di_prova() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript(store.SCHEMA_SQL)
    return conn


def test_fascia_domina_su_resa_realistica():
    """Una fonte A appena processata batte una fonte C con buona resa
    realistica (08.3: 'La fascia domina tutto il resto').

    Nota: la formula documentata non impone un tetto esplicito a
    resa_storica — con valori estremi (es. 100 eventi utili in 1 minuto
    speso) la resa può matematicamente superare il termine fascia. Qui si
    verifica il caso realistico (pochi eventi utili per fonte, minuti
    nell'ordine della decina), non il caso limite: se emergesse un caso
    reale dove la resa sovrasta la fascia, serve una decisione esplicita
    (es. un tetto a resa_storica), non un'assunzione nel codice."""
    punteggio_a = scheduling.calcola_priorita(
        fascia="A", eventi_totali=0, eventi_utili=0, minuti_spesi=0,
        last_run=date.today().isoformat(), consecutive_errors=0,
    )
    punteggio_c_buona_resa = scheduling.calcola_priorita(
        fascia="C", eventi_totali=10, eventi_utili=3, minuti_spesi=15,
        last_run=date.today().isoformat(), consecutive_errors=0,
    )
    assert punteggio_a > punteggio_c_buona_resa


def test_resa_storica_alza_il_punteggio():
    base = scheduling.calcola_priorita(
        fascia="B", eventi_totali=0, eventi_utili=0, minuti_spesi=10,
        last_run=date.today().isoformat(), consecutive_errors=0,
    )
    con_resa = scheduling.calcola_priorita(
        fascia="B", eventi_totali=10, eventi_utili=10, minuti_spesi=10,
        last_run=date.today().isoformat(), consecutive_errors=0,
    )
    assert con_resa > base


def test_minuti_spesi_zero_non_solleva_divisione_per_zero():
    punteggio = scheduling.calcola_priorita(
        fascia="B", eventi_totali=0, eventi_utili=0, minuti_spesi=0,
        last_run=date.today().isoformat(), consecutive_errors=0,
    )
    assert isinstance(punteggio, float)


def test_giorni_da_ultimo_run_non_ha_tetto():
    """08.3: 'nessuna fonte resta indietro per sempre' — una fonte ferma da
    100 giorni deve avere un punteggio più alto di una ferma da 5, a parità
    di tutto il resto."""
    ferma_da_poco = scheduling.calcola_priorita(
        fascia="B", eventi_totali=0, eventi_utili=0, minuti_spesi=0,
        last_run=(date.today() - timedelta(days=5)).isoformat(), consecutive_errors=0,
    )
    ferma_da_molto = scheduling.calcola_priorita(
        fascia="B", eventi_totali=0, eventi_utili=0, minuti_spesi=0,
        last_run=(date.today() - timedelta(days=100)).isoformat(), consecutive_errors=0,
    )
    assert ferma_da_molto > ferma_da_poco


def test_fonte_mai_processata_parte_in_cima_come_ferma_da_molto():
    mai_processata = scheduling.calcola_priorita(
        fascia="B", eventi_totali=0, eventi_utili=0, minuti_spesi=0,
        last_run=None, consecutive_errors=0,
    )
    ferma_da_un_anno = scheduling.calcola_priorita(
        fascia="B", eventi_totali=0, eventi_utili=0, minuti_spesi=0,
        last_run=(date.today() - timedelta(days=365)).isoformat(), consecutive_errors=0,
    )
    assert mai_processata == ferma_da_un_anno


def test_penalita_errori_riduce_il_punteggio():
    senza_errori = scheduling.calcola_priorita(
        fascia="B", eventi_totali=0, eventi_utili=0, minuti_spesi=0,
        last_run=date.today().isoformat(), consecutive_errors=0,
    )
    con_errori = scheduling.calcola_priorita(
        fascia="B", eventi_totali=0, eventi_utili=0, minuti_spesi=0,
        last_run=date.today().isoformat(), consecutive_errors=3,
    )
    assert con_errori < senza_errori


def test_ordina_fonti_per_priorita_risolve_fascia_dal_source_id():
    conn = _conn_di_prova()
    conn.execute(
        "INSERT INTO comuni (istat, comune, fascia, attivo) VALUES ('1', 'Calosso', 'A', 'si')"
    )
    conn.execute(
        "INSERT INTO comuni (istat, comune, fascia, attivo) VALUES ('2', 'Torino', 'C', 'si')"
    )
    conn.execute("INSERT INTO sources (source_id, tier) VALUES ('comune-torino', 'T1_html')")
    conn.execute("INSERT INTO sources (source_id, tier) VALUES ('comune-calosso', 'T1_html')")
    conn.commit()

    righe = conn.execute(
        "SELECT source_id, endpoint, tier, eventi_totali, eventi_utili, last_run, consecutive_errors FROM sources"
    ).fetchall()
    ordinate = scheduling.ordina_fonti_per_priorita(conn, righe)

    assert ordinate[0]["source_id"] == "comune-calosso"  # fascia A prima di fascia C


def test_ordina_fonti_per_priorita_fonte_senza_fascia_non_esplode():
    """Pro Loco, aggregatori: source_id non nel pattern 'comune-X', nessuna
    fascia risolvibile — non deve sollevare, resta a priorità base."""
    conn = _conn_di_prova()
    conn.execute("INSERT INTO sources (source_id, tier) VALUES ('proloco-x-sito', 'T1_html')")
    conn.commit()

    righe = conn.execute(
        "SELECT source_id, endpoint, tier, eventi_totali, eventi_utili, last_run, consecutive_errors FROM sources"
    ).fetchall()
    ordinate = scheduling.ordina_fonti_per_priorita(conn, righe)
    assert len(ordinate) == 1
