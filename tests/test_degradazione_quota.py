"""Degradazione progressiva della quota LLM (08.5), approssimata con la
sola fascia geografica (decisione con l'utente, 2026-08-27) al posto dei
campi manuali 'priorita'/'polling_diretto' non ancora popolati."""
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.extractor.client import decidi_degradazione_quota
from src.scheduling import fascia_da_source_id
from src import store


def test_sotto_70_percento_procede_sempre():
    assert decidi_degradazione_quota(0.5, fascia=None, e_immagine=True) is None
    assert decidi_degradazione_quota(0.5, fascia="C", e_immagine=True) is None


def test_70_percento_sospende_solo_le_immagini_fuori_fascia_a():
    assert decidi_degradazione_quota(0.75, fascia="B", e_immagine=True) is not None
    assert decidi_degradazione_quota(0.75, fascia="C", e_immagine=True) is not None


def test_70_percento_non_tocca_il_testo():
    """08.5: al 70% si sospendono solo 'le estrazioni da immagini', il testo continua."""
    assert decidi_degradazione_quota(0.75, fascia="C", e_immagine=False) is None


def test_70_percento_non_tocca_fascia_a():
    assert decidi_degradazione_quota(0.75, fascia="A", e_immagine=True) is None


def test_85_percento_sospende_tutto_fuori_fascia_a():
    assert decidi_degradazione_quota(0.90, fascia="B", e_immagine=False) is not None
    assert decidi_degradazione_quota(0.90, fascia="C", e_immagine=True) is not None


def test_85_percento_procede_solo_per_fascia_a():
    assert decidi_degradazione_quota(0.90, fascia="A", e_immagine=False) is None
    assert decidi_degradazione_quota(0.90, fascia="A", e_immagine=True) is None


def test_fascia_none_trattata_come_non_a():
    """Una fonte senza fascia nota (es. comune non risolto) non deve avere
    un trattamento privilegiato rispetto a una fonte B/C esplicita."""
    assert decidi_degradazione_quota(0.90, fascia=None, e_immagine=False) is not None


def test_100_percento_o_oltre_non_decide_qui():
    """Il 100% è gestito da ErroreQuotaEsaurita a monte, non da questa
    funzione — ritorna None per non duplicare la segnalazione."""
    assert decidi_degradazione_quota(1.0, fascia="C", e_immagine=True) is None
    assert decidi_degradazione_quota(1.2, fascia="A", e_immagine=True) is None


def _conn_di_prova() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript(store.SCHEMA_SQL)
    return conn


def test_fascia_da_source_id_risolve_comune_pattern():
    conn = _conn_di_prova()
    conn.execute("INSERT INTO comuni (istat, comune, fascia, attivo) VALUES ('1', 'Calosso', 'A', 'si')")
    conn.commit()

    assert fascia_da_source_id(conn, "comune-calosso") == "A"


def test_fascia_da_source_id_nessun_pattern_ritorna_none():
    conn = _conn_di_prova()
    assert fascia_da_source_id(conn, "proloco-x-sito") is None
    assert fascia_da_source_id(conn, "feed-facebook-x") is None


def test_fascia_da_source_id_comune_non_trovato_ritorna_none():
    conn = _conn_di_prova()
    assert fascia_da_source_id(conn, "comune-sconosciuto") is None
